import asyncio
import os
from typing import Dict, List, Optional, Type, Any
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from langchain_tavily import TavilySearch
from functools import lru_cache
import logging
import time

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 输入参数的 Pydantic 模型
class WeatherSearchInput(BaseModel):
    destination: str = Field(..., description="目标地点，例如 'Paris' 或 'New York'")
    month: str = Field(..., description="指定月份，例如 'November 2025' 或 '2025-11'")
    max_results: Optional[int] = Field(5, description="最大返回结果数量，默认为 5")

# 搜索结果的 Pydantic 模型
class WeatherSearchResult(BaseModel):
    weather_summary: str = Field(..., description="天气摘要信息")
    answer: Optional[str] = Field(None, description="Tavily提供的直接答案")
    web_results: List[Dict] = Field(default_factory=list, description="网页搜索结果，包含URL信息")
    error: Optional[str] = Field(None, description="错误信息（如果有）")

# 限速搜索器类
class RateLimitedSearcher:
    def __init__(self):
        import os
        tavily_api_key = os.environ.get("TAVILY_API_KEY")
        if not tavily_api_key:
            raise ValueError("TAVILY_API_KEY environment variable is required")
        # 创建Tavily搜索实例，开启摘要功能
        self.search = TavilySearch(
            max_results=5,
            include_answer=True,  # 开启摘要功能
            search_depth="basic"
        )
        self.last_request = 0
        self.min_interval = 0.2  # Tavily API限制更宽松，每秒1次请求

    async def search_with_rate_limit(self, query: str) -> Dict:
        current_time = time.time()
        if current_time - self.last_request < self.min_interval:
            await asyncio.sleep(self.min_interval - (current_time - self.last_request))
        
        self.last_request = time.time()
        try:
            # 使用Tavily搜索，直接获取包含答案的结果
            results = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.search.invoke({"query": query})
            )
            return results
        except Exception as e:
            logger.error(f"Tavily搜索失败: {str(e)}")
            return {"error": str(e), "answer": None, "results": []}

# 全局搜索器实例
_global_searcher = None

def get_global_searcher():
    global _global_searcher
    if _global_searcher is None:
        _global_searcher = RateLimitedSearcher()
    return _global_searcher

# 天气搜索工具类
class WeatherSearchTool(StructuredTool):
    name: str = "weather_search"
    description: str = (
        "使用Tavily搜索指定地点和月份的历史天气信息，快速获取天气摘要和直接答案。"
        "返回结构化的天气摘要信息，包含平均温度、降雨量等关键数据。适合用于旅行规划中的天气评估。"
    )
    args_schema: Type[BaseModel] = WeatherSearchInput
    return_direct: bool = True
    handle_tool_error: bool = True

    def __init__(self, **kwargs):
        super().__init__(
            coroutine=self._arun,
            name="weather_search",
            description="使用Tavily搜索指定地点和月份的历史天气信息，快速获取天气摘要和直接答案。返回结构化的天气摘要信息，包含平均温度、降雨量等关键数据。适合用于旅行规划中的天气评估。",
            args_schema=WeatherSearchInput,
            return_direct=True,
            handle_tool_error=True,
            **kwargs
        )

    # 优化查询构建 - 针对Tavily优化
    def _build_query(self, destination: str, month: str) -> str:
        return (
            f"{destination}{month}的历史平均气温（℃）、降雨量（毫米）和典型气候特征是什么？"
            f"请提供总体天气概况、常见天气模式和旅行建议。"
        )

    # 处理Tavily搜索结果
    def _process_tavily_results(self, results: Dict) -> tuple[str, List[Dict]]:
        # 优先使用Tavily提供的直接答案
        if results.get("answer"):
            weather_summary = results["answer"]
        else:
            # 如果没有直接答案，从搜索结果中提取天气信息
            weather_summary = f"{results.get('query', '天气查询')}的天气信息:\n"
            
            # 处理搜索结果
            search_results = results.get("results", [])
            if search_results:
                for i, result in enumerate(search_results[:3], 1):
                    title = result.get("title", "无标题")
                    content = result.get("content", "")
                    weather_summary += f"{i}. {title}: {content[:150]}...\n"
            else:
                weather_summary += "未找到相关的天气信息。"
        
        # 提取网页结果信息（保留URL）
        web_results = []
        search_results = results.get("results", [])
        for result in search_results[:5]:  # 最多保留5个结果
            web_results.append({
                "title": result.get("title", "无标题"),
                "link": result.get("url", ""),
                "snippet": result.get("content", "")[:200]
            })
        
        return weather_summary, web_results

    # 异步执行搜索
    async def _arun(self, destination: str, month: str, max_results: Optional[int] = 5) -> WeatherSearchResult:
        try:
            # 获取搜索器实例
            searcher = get_global_searcher()
            
            # 构建搜索查询
            weather_query = self._build_query(destination, month)

            # 执行Tavily搜索
            search_results = await searcher.search_with_rate_limit(weather_query)

            # 处理Tavily结果
            weather_summary, web_results = self._process_tavily_results(search_results)
            
            # 构建返回结果
            result = WeatherSearchResult(
                weather_summary=weather_summary,
                answer=search_results.get("answer"),
                web_results=web_results,
            )

            # 检查是否有错误
            if isinstance(search_results, dict) and search_results.get("error"):
                result.error = f"Tavily搜索错误: {search_results['error']}"
                logger.warning(result.error)

            return result

        except Exception as e:
            logger.error(f"天气搜索工具执行失败: {str(e)}")
            return WeatherSearchResult(
                weather_summary="天气搜索失败，请检查网络连接或API配置。",
                web_results=[],
                error=f"执行失败: {str(e)}"
            )

    # 同步执行（供兼容性）
    def _run(self, destination: str, month: str, max_results: Optional[int] = 5) -> WeatherSearchResult:
        return asyncio.run(self._arun(destination, month, max_results))

# 缓存搜索结果以优化性能
@lru_cache(maxsize=100)
def cached_weather_search(destination: str, month: str, max_results: int = 5) -> Dict:
    tool = WeatherSearchTool()
    result = asyncio.run(tool._arun(destination, month, max_results))
    return result.model_dump()

# 测试代码
if __name__ == "__main__":
    async def test_weather_search():
        tool = WeatherSearchTool()
        result = await tool._arun(
            destination="Paris",
            month="November 2025",
            max_results=3
        )
        print("Tavily天气搜索结果:")
        print(f"天气摘要: {result.weather_summary}")
        if result.answer:
            print(f"直接答案: {result.answer}")
        print(f"网页结果数量: {len(result.web_results)}")
        for i, web_result in enumerate(result.web_results, 1):
            print(f"网页结果 {i}: {web_result.get('title', '无标题')}")
            print(f"  链接: {web_result.get('link', '无链接')}")
        if result.error:
            print(f"错误: {result.error}")

    asyncio.run(test_weather_search())