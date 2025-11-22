from typing import Any, Dict, List, Optional, Union, Literal
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
import math
from .logging_config import path_navigate_logger

class PathNavigateInput(BaseModel):
    """路径规划工具输入参数模型"""
    routes: List[Dict[str, str]] = Field(
        ..., 
        description="路径列表，每个路径包含origin(起点)和destination(终点)，如：[{'origin': '北京市朝阳区', 'destination': '上海市浦东新区'}]",
        min_items=1,
        max_items=20
    )
    travel_mode: Literal["driving", "walking", "transit", "bicycling"] = Field(
        default="driving",
        description="出行方式：'driving'(驾车)/'walking'(步行)/'transit'(公交)/'bicycling'(骑行)"
    )
    strategy: int = Field(
        default=0,
        ge=0,
        le=9,
        description="驾车策略(仅driving有效)：0-速度优先/1-费用优先/2-距离优先/3-不走高速/4-躲避拥堵/5-多策略/6-不走高速且避免收费/7-不走高速且躲避拥堵/8-避免收费且躲避拥堵/9-不走高速避免收费且躲避拥堵"
    )
    city: Optional[str] = Field(
        default=None,
        description="城市名称(公交路径规划时推荐使用)，如：'北京市'"
    )

# 模块级别的配置变量，避免Pydantic属性冲突
_api_key = None
_initialized = False

# API端点常量
GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"
WALKING_URL = "https://restapi.amap.com/v3/direction/walking"
TRANSIT_URL = "https://restapi.amap.com/v3/direction/transit/integrated"
BICYCLING_URL = "https://restapi.amap.com/v3/direction/bicycling"

class PathNavigateTool(StructuredTool):
    """路径规划工具，集成高德地理编码和路径规划API"""
    
    def __init__(self, **kwargs):
        global _api_key, _initialized
        
        # 确保只初始化一次
        if not _initialized:
            # 加载环境变量
            env_file_path = os.path.join(os.path.dirname(__file__), '.env')
            if os.path.exists(env_file_path):
                load_dotenv(env_file_path)
                path_navigate_logger.info(f"已从 {env_file_path} 加载环境变量")
            
            # 确保API密钥已设置
            if not os.environ.get("AMAP_API_KEY"):
                raise ValueError("AMAP_API_KEY environment variable is required. 请检查toolkit/.env文件或系统环境变量")
            
            # 设置全局变量
            _api_key = os.environ.get("AMAP_API_KEY")
            _initialized = True
        
        # 调用父类初始化
        super().__init__(
            func=self._run,
            name="path_navigate",
            description="""专业的路径规划工具。支持驾车、步行、公交、骑行等多种出行方式的路径规划。
特别适合：出行规划、导航查询、多地点路线对比等场景。
输入需要包含起点终点列表、出行方式和路径策略。
注意：工具会自动将地址转换为经纬度坐标后进行路径规划。""",
            args_schema=PathNavigateInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        """同步执行路径规划"""
        try:
            # 异步执行并等待结果
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._arun(**kwargs))
            loop.close()
            return result
        except Exception as e:
            return {"error": f"路径规划执行失败：{str(e)}"}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        """异步执行路径规划（并行处理多个路径）"""
        try:
            # 提取输入参数
            routes = kwargs.get('routes', [])
            travel_mode = kwargs.get('travel_mode', 'driving')
            strategy = kwargs.get('strategy', 0)
            city = kwargs.get('city', None)
            
            # 参数验证
            if not routes:
                return {"error": "路径列表不能为空"}
            if len(routes) > 20:
                return {"error": "路径数量不能超过20个"}
            
            # 并行执行路径规划任务
            results = await self._parallel_navigate(routes, travel_mode, strategy, city)
            
            # 格式化输出
            formatted = self._format_navigate_results(results, travel_mode, strategy)
            return formatted

        except Exception as e:
            return {"error": f"路径规划异步执行失败：{str(e)}"}

    async def _parallel_navigate(
        self, 
        routes: List[Dict[str, str]], 
        travel_mode: str, 
        strategy: int,
        city: Optional[str]
    ) -> List[Dict[str, Any]]:
        """并行执行多个路径规划任务"""
        loop = asyncio.get_event_loop()
        results = []
        
        # 使用线程池执行器处理I/O密集型任务
        with ThreadPoolExecutor(max_workers=min(10, len(routes))) as executor:
            # 为每个路径创建规划任务
            tasks = []
            for route in routes:
                task = loop.run_in_executor(
                    executor,
                    partial(
                        self._safe_navigate_with_retry,
                        origin=route.get('origin'),
                        destination=route.get('destination'),
                        travel_mode=travel_mode,
                        strategy=strategy,
                        city=city,
                        retries=3,
                        delay=2.0
                    )
                )
                tasks.append(task)
            
            # 等待所有任务完成
            done = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for i, result in enumerate(done):
                if isinstance(result, Exception):
                    results.append({
                        'origin': routes[i].get('origin'),
                        'destination': routes[i].get('destination'),
                        'error': str(result),
                        'status': 'failed'
                    })
                else:
                    results.append(result)
        
        return results

    def _safe_navigate_with_retry(
        self, 
        origin: str, 
        destination: str, 
        travel_mode: str,
        strategy: int,
        city: Optional[str],
        retries: int = 3, 
        delay: float = 2.0
    ) -> Dict[str, Any]:
        """带重试机制的路径规划执行"""
        for attempt in range(1, retries + 1):
            try:
                path_navigate_logger.info(f"第 {attempt} 次尝试规划 {origin} -> {destination}...")
                
                # 步骤1：地理编码获取经纬度
                origin_location = self._geocode_address(origin, city, retries=2)
                if not origin_location['success']:
                    return {
                        'origin': origin,
                        'destination': destination,
                        'error': f"起点地理编码失败: {origin_location.get('error')}",
                        'status': 'failed'
                    }
                
                destination_location = self._geocode_address(destination, city, retries=2)
                if not destination_location['success']:
                    return {
                        'origin': origin,
                        'destination': destination,
                        'error': f"终点地理编码失败: {destination_location.get('error')}",
                        'status': 'failed'
                    }
                
                # 步骤2：路径规划
                navigate_result = self._navigate_route(
                    origin_location['location'],
                    destination_location['location'],
                    travel_mode,
                    strategy,
                    city
                )
                
                if not navigate_result['success']:
                    return {
                        'origin': origin,
                        'destination': destination,
                        'error': f"路径规划失败: {navigate_result.get('error')}",
                        'status': 'failed'
                    }
                
                # 成功返回结果
                return {
                    'origin': origin,
                    'destination': destination,
                    'origin_location': origin_location['location'],
                    'destination_location': destination_location['location'],
                    'route_info': navigate_result['route_info'],
                    'status': 'success'
                }
                
            except Exception as e:
                path_navigate_logger.warning(f"第 {attempt} 次尝试失败: {str(e)}")
                if attempt == retries:
                    return {
                        'origin': origin,
                        'destination': destination,
                        'error': f"路径规划重试失败: {str(e)}",
                        'status': 'failed'
                    }
                time.sleep(delay)
        
        return {
            'origin': origin,
            'destination': destination,
            'error': "路径规划执行失败",
            'status': 'failed'
        }

    def _geocode_address(self, address: str, city: Optional[str] = None, retries: int = 2) -> Dict[str, Any]:
        """地理编码：将地址转换为经纬度坐标"""
        for attempt in range(1, retries + 1):
            try:
                params = {
                    'key': _api_key,
                    'address': address,
                    'output': 'json'
                }
                
                if city:
                    params['city'] = city
                
                response = requests.get(GEOCODE_URL, params=params, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                
                if data.get('status') == '1' and data.get('geocodes'):
                    geocode = data['geocodes'][0]
                    return {
                        'success': True,
                        'location': {
                            'address': geocode.get('formatted_address', address),
                            'longitude': float(geocode.get('location', '0,0').split(',')[0]),
                            'latitude': float(geocode.get('location', '0,0').split(',')[1]),
                            'city': geocode.get('city', ''),
                            'district': geocode.get('district', '')
                        }
                    }
                else:
                    error_msg = data.get('info', '地理编码失败')
                    return {
                        'success': False,
                        'error': error_msg
                    }
                    
            except Exception as e:
                if attempt == retries:
                    return {
                        'success': False,
                        'error': f"地理编码请求失败: {str(e)}"
                    }
                time.sleep(1)
        
        return {
            'success': False,
            'error': "地理编码执行失败"
        }

    def _navigate_route(
        self, 
        origin: Dict[str, Any], 
        destination: Dict[str, Any], 
        travel_mode: str,
        strategy: int,
        city: Optional[str]
    ) -> Dict[str, Any]:
        """执行路径规划"""
        try:
            # 构建基础参数
            params = {
                'key': _api_key,
                'origin': f"{origin['longitude']},{origin['latitude']}",
                'destination': f"{destination['longitude']},{destination['latitude']}",
                'output': 'json'
            }
            
            # 根据出行方式选择API端点
            if travel_mode == 'driving':
                url = DRIVING_URL
                params['strategy'] = strategy
            elif travel_mode == 'walking':
                url = WALKING_URL
            elif travel_mode == 'transit':
                url = TRANSIT_URL
                if city:
                    params['city'] = city
            elif travel_mode == 'bicycling':
                url = BICYCLING_URL
            else:
                return {
                    'success': False,
                    'error': f"不支持的出行方式: {travel_mode}"
                }
            
            # 发送请求
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('status') == '1':
                route_info = self._parse_route_data(data, travel_mode)
                return {
                    'success': True,
                    'route_info': route_info
                }
            else:
                error_msg = data.get('info', '路径规划失败')
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f"路径规划请求失败: {str(e)}"
            }

    def _parse_route_data(self, data: Dict[str, Any], travel_mode: str) -> Dict[str, Any]:
        """解析路径规划结果"""
        route_info = {
            'travel_mode': travel_mode,
            'distance': 0,
            'duration': 0,
            'steps': [],
            'polyline': '',
            'tolls': 0,
            'toll_distance': 0,
            'traffic_lights': 0
        }
        
        if travel_mode == 'driving':
            route = data.get('route', {})
            paths = route.get('paths', [])
            if paths:
                path = paths[0]
                route_info.update({
                    'distance': path.get('distance', 0),
                    'duration': path.get('duration', 0),
                    'tolls': path.get('tolls', 0),
                    'toll_distance': path.get('toll_distance', 0),
                    'traffic_lights': path.get('traffic_lights', 0),
                    'steps': path.get('steps', [])
                })
        elif travel_mode == 'walking':
            route = data.get('route', {})
            paths = route.get('paths', [])
            if paths:
                path = paths[0]
                route_info.update({
                    'distance': path.get('distance', 0),
                    'duration': path.get('duration', 0),
                    'steps': path.get('steps', [])
                })
        elif travel_mode == 'transit':
            route = data.get('route', {})
            transits = route.get('transits', [])
            if transits:
                transit = transits[0]
                route_info.update({
                    'distance': transit.get('distance', 0),
                    'duration': transit.get('duration', 0),
                    'cost': transit.get('cost', 0),
                    'walking_distance': transit.get('walking_distance', 0),
                    'segments': transit.get('segments', [])
                })
        elif travel_mode == 'bicycling':
            route = data.get('route', {})
            paths = route.get('paths', [])
            if paths:
                path = paths[0]
                route_info.update({
                    'distance': path.get('distance', 0),
                    'duration': path.get('duration', 0),
                    'steps': path.get('steps', [])
                })
        
        return route_info

    def _format_navigate_results(
        self, 
        results: List[Dict[str, Any]], 
        travel_mode: str, 
        strategy: int
    ) -> Dict[str, Any]:
        """格式化路径规划结果"""
        successful_routes = []
        failed_routes = []
        
        for result in results:
            if result.get('status') == 'success':
                route_info = result['route_info']
                
                # 格式化单条成功路径
                formatted_route = {
                    'origin': result['origin'],
                    'destination': result['destination'],
                    'distance': self._format_distance(route_info.get('distance', 0)),
                    'duration': self._format_duration(route_info.get('duration', 0)),
                    'travel_mode': travel_mode
                }
                
                # 添加特定出行方式的额外信息
                if travel_mode == 'driving':
                    formatted_route.update({
                        'tolls': route_info.get('tolls', 0),
                        'toll_distance': self._format_distance(route_info.get('toll_distance', 0)),
                        'traffic_lights': route_info.get('traffic_lights', 0),
                        'strategy': self._get_strategy_name(strategy)
                    })
                elif travel_mode == 'transit':
                    formatted_route.update({
                        'cost': route_info.get('cost', 0),
                        'walking_distance': self._format_distance(route_info.get('walking_distance', 0))
                    })
                
                successful_routes.append(formatted_route)
            else:
                failed_routes.append({
                    'origin': result['origin'],
                    'destination': result['destination'],
                    'error': result.get('error', '未知错误')
                })
        
        return {
            'successful_routes': successful_routes,
            'failed_routes': failed_routes,
            'total_routes': len(results),
            'successful_count': len(successful_routes),
            'failed_count': len(failed_routes),
            'travel_mode': travel_mode,
            'strategy': self._get_strategy_name(strategy) if travel_mode == 'driving' else None
        }

    def _format_distance(self, distance: int) -> str:
        """格式化距离"""
        if distance < 1000:
            return f"{distance}米"
        else:
            return f"{distance/1000:.1f}公里"

    def _format_duration(self, duration: int) -> str:
        """格式化时间"""
        if duration < 60:
            return f"{duration}秒"
        elif duration < 3600:
            return f"{duration//60}分钟"
        else:
            hours = duration // 3600
            minutes = (duration % 3600) // 60
            return f"{hours}小时{minutes}分钟"

    def _get_strategy_name(self, strategy: int) -> str:
        """获取策略名称"""
        strategy_names = {
            0: "速度优先",
            1: "费用优先", 
            2: "距离优先",
            3: "不走高速",
            4: "躲避拥堵",
            5: "多策略",
            6: "不走高速且避免收费",
            7: "不走高速且躲避拥堵",
            8: "避免收费且躲避拥堵",
            9: "不走高速避免收费且躲避拥堵"
        }
        return strategy_names.get(strategy, "未知策略")

def create_path_navigate_tool() -> PathNavigateTool:
    """
    创建并返回路径规划工具实例
    
    Returns:
        PathNavigateTool: 配置好的路径规划工具实例
    """
    return PathNavigateTool()