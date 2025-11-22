# toolkit/area_weather.py

from typing import Any, Dict, List, Optional, Union
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field
import asyncio
from concurrent.futures import ThreadPoolExecutor
import requests
import json
import os
from dotenv import load_dotenv
import time
from functools import partial
from .logging_config import area_weather_logger

class AreaWeatherInput(BaseModel):
    """天气查询工具输入参数模型"""
    locations: List[str] = Field(..., description="查询地点列表，支持城市名、区县名，如：['北京市', '上海市']")
    weather_type: str = Field(
        default="realtime",
        description="天气类型：'realtime'(实况天气)/'forecast'(天气预报)"
    )
    days: int = Field(
        default=1,
        ge=1,
        le=4,
        description="预报天数，仅对天气预报有效，范围1-4天"
    )
    
    # 添加模型配置避免递归错误
    model_config = {
        "arbitrary_types_allowed": True,
        "validate_assignment": True
    }

# 模块级别的配置变量，避免Pydantic属性冲突
_api_key = None
_adcode_cache = None
_initialized = False

class AreaWeatherTool(StructuredTool):
    """区域天气查询工具，集成高德天气API和行政区查询"""
    
    def __init__(self, **kwargs):
        global _api_key, _adcode_cache, _initialized
        
        # 确保只初始化一次
        if not _initialized:
            # 首先尝试从toolkit/.env文件加载API密钥
            env_file_path = os.path.join(os.path.dirname(__file__), '.env')
            if os.path.exists(env_file_path):
                load_dotenv(env_file_path)
                area_weather_logger.info(f"已从 {env_file_path} 加载环境变量")
            
            # 确保API密钥已设置
            if not os.environ.get("AMAP_API_KEY"):
                raise ValueError("AMAP_API_KEY environment variable is required. 请检查toolkit/.env文件或系统环境变量")
            
            # 设置全局变量
            _api_key = os.environ.get("AMAP_API_KEY")
            _adcode_cache = self._load_adcode_cache()
            _initialized = True
        
        # 调用父类初始化
        super().__init__(
            func=self._run,
            name="area_weather",
            description="""专业的区域天气查询工具。支持多地点实况天气和天气预报查询。
特别适合：旅行规划、出行安排、天气监控等场景。
输入需要包含地点列表和天气类型。""",
            args_schema=AreaWeatherInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs
        )

    def _load_adcode_cache(self) -> Dict[str, str]:
        """加载本地adcode缓存"""
        cache_file = os.path.join(os.path.dirname(__file__), 'tool_dependency', 'adcoder.json')
        adcode_cache = {}
        
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    adcode_data = json.load(f)
                    for item in adcode_data:
                        if '中文名' in item and 'adcode' in item:
                            adcode_cache[item['中文名']] = item['adcode']
            area_weather_logger.info(f"已加载 {len(adcode_cache)} 个行政区adcode缓存")
        except Exception as e:
            area_weather_logger.warning(f"加载adcode缓存失败: {str(e)}")
        
        return adcode_cache

    def _run(self, **kwargs) -> Dict[str, Any]:
        """同步执行天气查询"""
        try:
            # 异步执行并等待结果
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._arun(**kwargs))
            loop.close()
            return result
        except Exception as e:
            return {"error": f"天气查询执行失败：{str(e)}"}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        """异步执行天气查询（并行多地点查询）"""
        try:
            # 提取输入参数
            locations = kwargs.get('locations', [])
            weather_type = kwargs.get('weather_type', 'realtime')
            days = kwargs.get('days', 1)
            
            # 参数验证
            if not locations:
                return {"error": "地点列表不能为空"}
            if len(locations) > 10:
                return {"error": "地点数量不能超过10个"}
            if weather_type not in ['realtime', 'forecast']:
                return {"error": "天气类型必须是'realtime'或'forecast'"}
            
            # 并行执行天气查询
            results = await self._parallel_weather_query(locations, weather_type, days)
            
            # 格式化输出
            formatted = self._format_weather_results(results, weather_type)
            return formatted

        except Exception as e:
            return {"error": f"天气查询异步执行失败：{str(e)}"}

    async def _parallel_weather_query(self, locations: List[str], weather_type: str, days: int) -> List[Dict[str, Any]]:
        """并行执行多个地点天气查询，带重试机制"""
        loop = asyncio.get_event_loop()
        results = []
        
        # 使用线程池执行器处理I/O密集型任务
        with ThreadPoolExecutor(max_workers=min(5, len(locations))) as executor:
            # 为每个地点创建查询任务
            tasks = []
            for location in locations:
                task = loop.run_in_executor(
                    executor,
                    partial(
                        self._safe_weather_query_with_retry,
                        location=location,
                        weather_type=weather_type,
                        days=days,
                        retries=3,
                        delay=1.0
                    )
                )
                tasks.append(task)
            
            # 等待所有任务完成
            done = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for i, result in enumerate(done):
                if isinstance(result, Exception):
                    results.append({
                        'location': locations[i],
                        'error': str(result),
                        'status': 'failed'
                    })
                else:
                    results.append(result)
        
        return results

    def _safe_weather_query_with_retry(self, location: str, weather_type: str, days: int, 
                                      retries: int = 3, delay: float = 1.0) -> Dict[str, Any]:
        """带重试机制的天气查询执行"""
        for attempt in range(1, retries + 1):
            try:
                area_weather_logger.info(f"第 {attempt} 次尝试查询 {location}...")
                
                # 获取地点adcode
                adcode = self._get_location_adcode(location)
                if not adcode:
                    return {
                        'location': location,
                        'error': f"无法获取地点 '{location}' 的行政区编码",
                        'status': 'failed'
                    }
                
                # 执行天气查询
                if weather_type == 'realtime':
                    result = self._query_realtime_weather(adcode)
                else:
                    result = self._query_forecast_weather(adcode, days)
                
                # 添加成功状态
                result['status'] = 'success'
                result['location'] = location
                result['adcode'] = adcode
                
                area_weather_logger.info(f"成功查询 {location}")
                return result
                
            except Exception as e:
                area_weather_logger.warning(f"第 {attempt} 次查询 {location} 失败: {str(e)}")
                if attempt < retries:
                    time.sleep(delay)
                else:
                    return {
                        'location': location,
                        'error': f"查询失败: {str(e)}",
                        'status': 'failed'
                    }
        
        return {
            'location': location,
            'error': "查询失败：重试次数已用完",
            'status': 'failed'
        }

    def _get_location_adcode(self, location: str) -> Optional[str]:
        """获取地点的行政区编码(adcode)"""
        # 首先检查缓存
        if location in _adcode_cache:
            return _adcode_cache[location]
        
        # 如果缓存中没有，尝试通过API查询
        try:
            # 行政区查询API
            url = "https://restapi.amap.com/v3/config/district"
            params = {
                'key': _api_key,
                'keywords': location,
                'subdistrict': 0,
                'extensions': 'base'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data.get('status') == '1' and data.get('districts'):
                district = data['districts'][0]
                adcode = district.get('adcode')
                if adcode:
                    # 更新缓存
                    _adcode_cache[location] = adcode
                    return adcode
            
            return None
            
        except Exception as e:
            area_weather_logger.error(f"查询 {location} 行政区编码失败: {str(e)}")
            return None

    def _query_realtime_weather(self, adcode: str) -> Dict[str, Any]:
        """查询实况天气"""
        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {
            'key': _api_key,
            'city': adcode,
            'extensions': 'base'
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get('status') == '1' and data.get('lives'):
            weather_data = data['lives'][0]
            return {
                'weather': weather_data.get('weather', ''),
                'temperature': weather_data.get('temperature', ''),
                'winddirection': weather_data.get('winddirection', ''),
                'windpower': weather_data.get('windpower', ''),
                'humidity': weather_data.get('humidity', ''),
                'reporttime': weather_data.get('reporttime', '')
            }
        else:
            raise Exception(f"天气查询失败: {data.get('info', '未知错误')}")

    def _query_forecast_weather(self, adcode: str, days: int) -> Dict[str, Any]:
        """查询天气预报"""
        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {
            'key': _api_key,
            'city': adcode,
            'extensions': 'all'
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get('status') == '1' and data.get('forecasts'):
            forecast_data = data['forecasts'][0]
            casts = forecast_data.get('casts', [])
            
            # 根据请求的天数返回预报数据
            result = {
                'forecasts': casts[:days],
                'city': forecast_data.get('city', ''),
                'adcode': forecast_data.get('adcode', ''),
                'reporttime': forecast_data.get('reporttime', '')
            }
            return result
        else:
            raise Exception(f"天气预报查询失败: {data.get('info', '未知错误')}")

    def _format_weather_results(self, results: List[Dict[str, Any]], weather_type: str) -> Dict[str, Any]:
        """格式化天气查询结果"""
        successful_results = [r for r in results if r.get('status') == 'success']
        failed_results = [r for r in results if r.get('status') == 'failed']
        
        formatted = {
            'summary': {
                'total_queries': len(results),
                'successful': len(successful_results),
                'failed': len(failed_results),
                'weather_type': weather_type
            },
            'successful_queries': successful_results,
            'failed_queries': failed_results
        }
        
        # 添加详细结果
        if weather_type == 'realtime':
            formatted['realtime_data'] = [
                {
                    'location': r['location'],
                    'weather': r.get('weather', ''),
                    'temperature': r.get('temperature', ''),
                    'wind': f"{r.get('winddirection', '')} {r.get('windpower', '')}",
                    'humidity': r.get('humidity', ''),
                    'report_time': r.get('reporttime', '')
                }
                for r in successful_results
            ]
        else:
            formatted['forecast_data'] = [
                {
                    'location': r['location'],
                    'forecasts': r.get('forecasts', []),
                    'report_time': r.get('reporttime', '')
                }
                for r in successful_results
            ]
        
        return formatted