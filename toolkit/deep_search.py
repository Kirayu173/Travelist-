# toolkit/deep_search.py

from typing import Any, Dict, List, Optional, Union
from langchain_core.tools.structured import StructuredTool
from langchain_community.utilities import GoogleSerperAPIWrapper
from pydantic import BaseModel, Field
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from .config_utils import load_env, get_key, require_key
from .logging_config import deep_search_logger

class DeepSearchInput(BaseModel):
    """深度搜索工具的输入参数模型"""
    origin_city: str = Field(..., description="出发城市名称，如：北京")
    destination_city: str = Field(..., description="目的地城市名称，如：上海")
    start_date: str = Field(..., description="旅行开始日期，格式：YYYY-MM-DD")
    end_date: str = Field(..., description="旅行结束日期，格式：YYYY-MM-DD")
    num_travelers: int = Field(default=1, description="旅行人数，默认1人")
    search_type: str = Field(
        default="all",
        description="搜索类型，可选值：'all'(全部), 'hotel'(酒店), 'transport'(交通), 'activity'(活动)"
    )

class DeepSearchTool(StructuredTool):
    """深度网络搜索工具，集成酒店、交通、活动三大检索功能"""
    
    def __init__(self, **kwargs):
        # 使用统一的配置加载工具
        load_env()
        
        # 确保API密钥已设置
        try:
            require_key("SERPER_API_KEY")
            deep_search_logger.info("SERPER_API_KEY 环境变量已成功加载")
        except ValueError as e:
            deep_search_logger.error(f"API密钥配置错误: {str(e)}")
            raise
        
        super().__init__(
            func=self._run,
            name="deep_search",
            description="""专业的旅行信息深度搜索工具。能够同时检索指定地点、日期的酒店、交通和活动信息。
	特别适合：旅行规划、目的地研究、行程安排等综合信息查询。
	输入需要包含出发城市、目的地城市、旅行日期范围和搜索类型。""",
            args_schema=DeepSearchInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs
        )
    
    def _run(self, **kwargs) -> str:
        """执行深度搜索并返回格式化结果"""
        try:
            # 提取输入参数
            origin_city = kwargs.get('origin_city', '')
            destination_city = kwargs.get('destination_city', '')
            start_date = kwargs.get('start_date', '')
            end_date = kwargs.get('end_date', '')
            num_travelers = kwargs.get('num_travelers', 1)
            search_type = kwargs.get('search_type', 'all')
            
            # 验证必要参数
            if not all([origin_city, destination_city, start_date, end_date]):
                return "错误：缺少必要的搜索参数（出发城市、目的地城市、开始日期、结束日期）"
            
            # 创建Serper搜索实例，固定参数配置
            serper_client = GoogleSerperAPIWrapper(
                search_engine="google",  # 固定为谷歌搜索
                k=10,  # 默认结果数量
            )
            
            # 根据搜索类型执行相应的搜索
            results = {}
            
            if search_type in ['all', 'hotel']:
                results['hotel'] = self._search_hotels(
                    serper_client, destination_city, start_date, end_date, num_travelers, origin_city
                )
            
            if search_type in ['all', 'transport']:
                results['transport'] = self._search_transport(
                    serper_client, origin_city, destination_city, start_date, end_date, num_travelers
                )
            
            if search_type in ['all', 'activity']:
                results['activity'] = self._search_activities(
                    serper_client, destination_city, origin_city, start_date, end_date
                )
            
            # 格式化搜索结果
            formatted_results = self._format_search_results(results, search_type)
            
            return formatted_results
            
        except Exception as e:
            return f"深度搜索执行失败：{str(e)}"
    
    def _search_hotels(self, serper_client: GoogleSerperAPIWrapper, destination_city: str, start_date: str, 
                      end_date: str, num_travelers: int, origin_city: str) -> Dict[str, Any]:
        """酒店搜索逻辑"""
        # 构建酒店搜索查询语句（与tavily_search_utils.py保持一致）
        query = (
            f"budget hotels in {destination_city} from {start_date} "
            f"to {end_date} for {num_travelers} guests, departing from {origin_city}"
        )
        
        # 执行搜索
        return serper_client.results(query)
    
    def _search_transport(self, serper_client: GoogleSerperAPIWrapper, origin_city: str, destination_city: str,
                         start_date: str, end_date: str, num_travelers: int) -> Dict[str, Any]:
        """交通搜索逻辑"""
        # 构建交通搜索查询语句（与tavily_search_utils.py保持一致）
        query = (
            f"cheap transportation options from {origin_city} to {destination_city} "
            f"between {start_date} and {end_date} for {num_travelers} people. "
            f"Include flights, trains, and buses if available."
        )
        
        # 执行搜索
        return serper_client.results(query)
    
    def _search_activities(self, serper_client: GoogleSerperAPIWrapper, destination_city: str, origin_city: str,
                          start_date: str, end_date: str) -> Dict[str, Any]:
        """活动搜索逻辑"""
        # 构建活动搜索查询语句（与tavily_search_utils.py保持一致）
        query = (
            f"top-rated activities and things to do in {destination_city} "
            f"for travelers from {origin_city} "
            f"during {start_date} to {end_date}"
        )
        
        # 执行搜索
        return serper_client.results(query)
    
    def _format_search_results(self, results: Dict[str, Any], search_type: str) -> str | Dict[str, Any]:
        """
        格式化深度搜索结果
        """

        structured_output = {
            "metadata": {
                "search_type": search_type,
                "total_categories": 0,
            },
            "categories": []
        }

        # 定义类别映射（名称 + 图标）
        category_labels = {
            "hotel": "酒店信息",
            "transport": "交通信息",
            "activity": "活动信息"
        }

        # 遍历结果类别
        for category, data in results.items():
            if not data or 'organic' not in data:
                continue

            items = []
            for item in data['organic'][:5]:
                items.append({
                    "title": item.get("title", "无标题"),
                    "snippet": item.get("snippet", ""),
                    "link": item.get("link", ""),
                })

            structured_output["categories"].append({
                "type": category,
                "label": category_labels.get(category, category),
                "count": len(data['organic']),
                "items": items
            })

        structured_output["metadata"]["total_categories"] = len(structured_output["categories"])

        # === 输出模式 ===
        return structured_output

    async def _arun(self, **kwargs) -> str:
        """异步执行深度搜索（并行酒店/交通/活动三类检索）"""
        try:
            # 提取输入参数
            origin_city = kwargs.get('origin_city', '')
            destination_city = kwargs.get('destination_city', '')
            start_date = kwargs.get('start_date', '')
            end_date = kwargs.get('end_date', '')
            num_travelers = kwargs.get('num_travelers', 1)
            search_type = kwargs.get('search_type', 'all')

            # 校验参数
            if not all([origin_city, destination_city, start_date, end_date]):
                return "错误：缺少必要的搜索参数（出发城市、目的地城市、开始日期、结束日期）"

            # 创建 Serper 客户端
            serper_client = GoogleSerperAPIWrapper(
                search_engine="google",
                k=10,
            )

            # 并行执行搜索任务
            loop = asyncio.get_event_loop()
            search_tasks = []

            # 根据搜索类型创建对应的搜索任务
            if search_type in ['all', 'hotel']:
                hotel_task = loop.run_in_executor(
                    None,
                    self._search_hotels,
                    serper_client, destination_city, start_date, end_date, num_travelers, origin_city
                )
                search_tasks.append(('hotel', hotel_task))

            if search_type in ['all', 'transport']:
                transport_task = loop.run_in_executor(
                    None,
                    self._search_transport,
                    serper_client, origin_city, destination_city, start_date, end_date, num_travelers
                )
                search_tasks.append(('transport', transport_task))

            if search_type in ['all', 'activity']:
                activity_task = loop.run_in_executor(
                    None,
                    self._search_activities,
                    serper_client, destination_city, origin_city, start_date, end_date
                )
                search_tasks.append(('activity', activity_task))

            # 等待所有任务完成
            results = {}
            for category, task in search_tasks:
                try:
                    results[category] = await task
                except Exception as e:
                    deep_search_logger.error(f"{category} 搜索失败: {str(e)}")
                    results[category] = {'organic': []}

            # 格式化结果
            formatted_results = self._format_search_results(results, search_type)
            return formatted_results

        except Exception as e:
            return f"深度搜索异步执行失败：{str(e)}"

def create_deep_search_tool() -> DeepSearchTool:
    """创建并返回深度搜索工具实例"""
    return DeepSearchTool()