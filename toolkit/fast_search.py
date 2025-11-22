# toolkit/fast_search.py
from typing import Any, Dict, List, Optional
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field
from langchain_tavily import TavilySearch
import os
from dotenv import load_dotenv
from .logging_config import fast_search_logger

class FastSearchInput(BaseModel):
    """快速搜索工具的输入参数模型"""
    query: str = Field(..., description="搜索查询内容，需要提供具体的搜索关键词或问题")
    time_range: str = Field(
        default="week", 
        description="搜索时间范围，可选值：'day'(一天内), 'week'(一周内), 'month'(一月内), 'year'(一年内)"
    )

class FastSearchTool(StructuredTool):
    """快速网络搜索工具，专注于摘要性信息检索"""
    
    def __init__(self, **kwargs):
        # 首先尝试从toolkit/.env文件加载API密钥
        env_file_path = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_file_path):
            load_dotenv(env_file_path)
            fast_search_logger.info(f"已从 {env_file_path} 加载环境变量")
        
        # 确保API密钥已设置（优先使用toolkit/.env中的密钥）
        if not os.environ.get("TAVILY_API_KEY"):
            raise ValueError("TAVILY_API_KEY environment variable is required. 请检查toolkit/.env文件或系统环境变量")

        super().__init__(
            func=self._run,
            name="fast_search",
            description="""专门用于快速搜索摘要性信息的工具。当需要获取实时、准确的事实性信息时使用此工具。
特别适合：新闻检索、事实查询、实时信息获取、快速知识补充等场景。
输入需要包含具体的搜索查询和时间范围。""",
            args_schema=FastSearchInput,
            return_direct=False,  # 允许代理继续处理
            **kwargs
        )

    def _run(self, **kwargs) -> str:
        """执行快速搜索并返回格式化摘要"""
        try:
            # 提取输入参数
            query = kwargs.get('query', '')
            time_range = kwargs.get('time_range', 'week')
            
            if not query:
                return "错误：查询内容不能为空"
            
            # 创建Tavily搜索实例，固定大多数参数
            tavily_client = TavilySearch(
                max_results=5,  # 限制结果数量以提高速度
                topic="general",
                include_answer=True,  # 包含直接答案
                include_raw_content=True,  # 包含原始内容
                include_images=False,  # 不包含图片
                include_image_descriptions=False,  # 不包含图片描述
                search_depth="basic",  # 使用基本搜索以提高速度
                time_range=None  # 允许外部指定时间范围
            )
            
            # 构建搜索参数
            search_params = {
                "query": query,
                "time_range": time_range
            }
            
            # 执行搜索
            result = tavily_client.invoke(search_params)
            
            # 格式化搜索结果摘要
            summary = self._format_search_results_llm(result, query)
            
            return summary
            
        except Exception as e:
            return f"搜索执行失败：{str(e)}"

    def _format_search_results_llm(self, result: Dict[str, Any], query: str) -> Dict[str, Any]:
        """格式化搜索结果为 LLM 友好型结构化信息"""
        
        structured_output = {
            "query": query,
            "answer": result.get("answer", None),
            "total_results": len(result.get("results", [])),
            "results": [],
            "follow_up_questions": result.get("follow_up_questions", []),
            "meta_summary": ""
        }

        results = result.get("results", [])

        for item in results[:5]:  # 取前5条以控制上下文长度
            structured_output["results"].append({
                "title": item.get("title", None),
                "summary": item.get("content", None),
                "url": item.get("url", None),
                "score": item.get("score", None),  # 若 Tavily 或 Serper 返回 relevance 分数
                "published_time": item.get("published_time", None)
            })

        # 自动生成 LLM 可理解的摘要信息
        answer_text = (
            f"直接回答：{result['answer']}。" if result.get("answer") else "无直接回答。"
        )
        structured_output["meta_summary"] = (
            f"针对查询“{query}”，共检索到 {structured_output['total_results']} 条结果。"
            f"{answer_text} "
            f"前 {len(structured_output['results'])} 条结果包含标题、摘要和来源链接。"
        )

        return structured_output


    async def _arun(self, **kwargs) -> str:
        """异步执行搜索"""
        return self._run(**kwargs)



def create_fast_search_tool() -> FastSearchTool:
    """
    创建并返回快速搜索工具实例

Returns:
    FastSearchTool: 配置好的快速搜索工具实例
"""
    return FastSearchTool()