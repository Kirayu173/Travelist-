# toolkit/deep_extract.py

from typing import Any, Dict, List, Optional, Union
from langchain_core.tools.structured import StructuredTool
from langchain_tavily import TavilyExtract
from pydantic import BaseModel, Field
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from dotenv import load_dotenv
import time
from functools import partial
import re
from .logging_config import deep_extract_logger
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.text_rank import TextRankSummarizer

class DeepExtractInput(BaseModel):
    """深度网页提取工具的输入参数模型"""
    urls: List[str] = Field(..., description="要抓取的网页URL列表，最多15个URL")
    query: str = Field(..., description="提取信息的查询内容，如：'提取产品信息'")

class DeepExtractTool(StructuredTool):
    """深度网页提取工具，基于TavilyExtract API实现多网页并行抓取"""
    
    def __init__(self, **kwargs):
        # 首先尝试从toolkit/.env文件加载API密钥
        env_file_path = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_file_path):
            load_dotenv(env_file_path)
            deep_extract_logger.info(f"已从 {env_file_path} 加载环境变量")
        
        # 确保API密钥已设置（优先使用toolkit/.env中的密钥）
        if not os.environ.get("TAVILY_API_KEY"):
            raise ValueError("TAVILY_API_KEY environment variable is required. 请检查toolkit/.env文件或系统环境变量")
        
        super().__init__(
            func=self._run,
            name="deep_extract",
            description="""专业的网页信息深度提取工具。能够并行抓取多个网页并提取结构化信息。
特别适合：批量网页数据提取、竞品分析、内容聚合等场景。
输入需要包含URL列表、提取查询。""",
            args_schema=DeepExtractInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs
        )

    def _run(self, **kwargs) -> str:
        """同步执行深度网页提取"""
        try:
            # 初始化TavilyExtract客户端，固定参数配置
            self.extract_client = TavilyExtract(
                include_answer=True,           # 包含直接答案
                include_raw_content=True,      # 包含原始内容
                search_depth="basic",          # 标准搜索深度
                include_image_descriptions=False  # 不包含图片描述
            )
            # 异步执行并等待结果
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._arun(**kwargs))
            loop.close()
            return result
        except Exception as e:
            return f"深度提取执行失败：{str(e)}"

    async def _arun(self, **kwargs) -> str:
        """异步执行深度网页提取（并行抓取多个URL）"""
        try:
            # 提取输入参数
            urls = kwargs.get('urls', [])
            query = kwargs.get('query', '')
            
            # 参数验证
            if not urls:
                return "错误：URL列表不能为空"
            if not query:
                return "错误：查询内容不能为空"
            if len(urls) > 15:
                return "错误：URL数量不能超过15个"
            
            # 初始化TavilyExtract客户端，固定参数配置
            extract_client = TavilyExtract(
                include_answer=True,           # 包含直接答案
                include_raw_content=True,      # 包含原始内容
                search_depth="basic",          # 标准搜索深度
                include_image_descriptions=False  # 不包含图片描述
            )
            
            # 并行执行提取任务
            results = await self._parallel_extract(extract_client, urls, query)
            
            # 格式化输出
            formatted = self._format_extract_results(results, query)
            return formatted

        except Exception as e:
            return f"深度提取异步执行失败：{str(e)}"

    async def _parallel_extract(self, extract_client: TavilyExtract, urls: List[str], query: str) -> List[Dict[str, Any]]:
        """并行执行多个网页提取任务，带重试机制"""
        loop = asyncio.get_event_loop()
        results = []
        
        # 使用线程池执行器处理I/O密集型任务
        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as executor:
            # 为每个URL创建提取任务
            tasks = []
            for url in urls:
                task = loop.run_in_executor(
                    executor,
                    partial(
                        self._safe_extract_with_retry,
                        extract_client=extract_client,
                        urls=[url],  # 传递URL列表，即使只有一个URL
                        query=query,
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
                        'url': urls[i],
                        'error': str(result),
                        'status': 'failed'
                    })
                else:
                    results.append(result)
        
        return results

    def _safe_extract_with_retry(self, extract_client: TavilyExtract, urls: List[str], query: str, 
                                retries: int = 3, delay: float = 2.0) -> Dict[str, Any]:
        """带重试机制的网页提取执行"""
        # 只处理第一个URL（批量处理时每个任务处理一个URL）
        url = urls[0] if urls else ""
        
        for attempt in range(1, retries + 1):
            try:
                deep_extract_logger.info(f"第 {attempt} 次尝试提取 {url}...")
                
                # 构建提取参数 - 根据官方文档，TavilyExtract需要urls参数
                extract_params = {
                    "query": query,
                    "urls": urls  # 传递URL列表
                }
                
                # 执行提取
                result = extract_client.invoke(extract_params)
                
                # 处理TavilyExtract返回的结果结构
                # TavilyExtract可能返回多种格式：
                # 1. 直接结果字典: {'raw_content': ..., 'title': ...}
                # 2. 包含results字段的字典: {'results': [{'raw_content': ...}], ...}
                # 3. 错误响应: {'error': ...}
                if isinstance(result, dict):
                    extracted_data = None
                    
                    # 首先检查是否直接包含raw_content字段（直接返回结果）
                    if 'raw_content' in result:
                        deep_extract_logger.info("✅ 直接包含raw_content字段，使用整个响应")
                        extracted_data = result
                    
                    # 然后检查results字段
                    elif 'results' in result:
                        if result['results'] and isinstance(result['results'], list):
                            deep_extract_logger.info("✅ 找到results字段，使用第一个结果")
                            extracted_data = result['results'][0]
                        else:
                            deep_extract_logger.warning("⚠️ results字段为空或不是列表")
                    
                    # 检查错误信息
                    elif 'error' in result:
                        deep_extract_logger.error(f"❌ API返回错误: {result.get('error', '未知错误')}")
                        return {
                            'url': url,
                            'error': f"API错误: {result.get('error', '未知错误')}",
                            'status': 'failed'
                        }
                    
                    else:
                        deep_extract_logger.warning(f"❓ 未知API返回结构: {list(result.keys())}")
                    
                    # 如果成功提取到数据
                    if extracted_data and isinstance(extracted_data, dict):
                        # 对提取的内容进行预处理
                        extracted_data = self._preprocess_extracted_content(extracted_data, url)
                        
                        # 确保包含必要的字段
                        extracted_data['status'] = 'success'
                        extracted_data['url'] = url
                        # 将raw_content映射到content字段
                        if 'raw_content' in extracted_data:
                            extracted_data['content'] = extracted_data['raw_content']
                        deep_extract_logger.info(f"✅ 成功提取 {url}")
                        return extracted_data
                    else:
                        # 没有提取到有效数据
                        return {
                            'url': url,
                            'error': '未提取到任何内容',
                            'status': 'failed'
                        }
                else:
                    # 返回格式不符合预期 - 检查是否为字符串类型的错误信息
                    if isinstance(result, str):
                        # 如果是字符串，很可能是错误信息
                        deep_extract_logger.error(f"❌ API返回错误信息: {result}")
                        return {
                            'url': url,
                            'error': f'API错误: {result}',
                            'status': 'failed'
                        }
                    else:
                        # 其他未知格式
                        deep_extract_logger.error(f"❌ API返回格式异常: {type(result)}")
                        deep_extract_logger.error(f"❌ 原始返回结果: {result}")
                        return {
                            'url': url,
                            'error': f'API返回格式异常: {type(result)} - 原始结果: {str(result)[:200]}',
                            'status': 'failed'
                        }
                
            except Exception as e:
                deep_extract_logger.warning(f"第 {attempt} 次尝试失败: {str(e)}")
                if attempt == retries:
                    return {
                        'url': url,
                        'error': f"提取失败: {str(e)}",
                        'status': 'failed'
                    }
                # 等待后重试
                time.sleep(delay)
        
        return {
            'url': url,
            'error': '未知错误',
            'status': 'failed'
        }

    def _preprocess_extracted_content(self, extracted_data: Dict[str, Any], url: str) -> Dict[str, Any]:
        """
        对提取的网页内容进行预处理（同步版，集成 TextRank 摘要逻辑）

        Args:
            extracted_data: 从 TavilyExtract API 返回的原始数据
            url: 当前处理的 URL

        Returns:
            预处理后的数据
        """
        try:
            # ========== 1. 清理 HTML 标签和特殊字符 ==========
            if 'raw_content' in extracted_data and extracted_data['raw_content']:
                def _clean_html(text: str) -> str:
                    text = re.sub(r'<[^>]+>', '', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text

                extracted_data['raw_content'] = _clean_html(extracted_data['raw_content'])

            # ========== 2. 快速去噪 ==========
            def _quick_clean(text: str) -> str:
                text = re.sub(r"http[s]?://\S+", "", text)
                text = re.sub(r"【.*?】", "", text)
                text = re.sub(r"广告|扫码|点击|订阅|阅读全文", "", text)
                text = re.sub(r"版权|免责声明|联系我们.*?$", "", text)
                text = re.sub(r"\s+", " ", text)
                return text.strip()

            if 'raw_content' in extracted_data:
                extracted_data['raw_content'] = _quick_clean(extracted_data['raw_content'])

            # ========== 3. 自动摘要逻辑 ==========
            max_length = 8000          # 硬截断上限
            summary_threshold = 2000   # 超过此长度触发摘要

            if 'raw_content' in extracted_data and extracted_data['raw_content']:
                raw_text = extracted_data['raw_content']

                if len(raw_text) > max_length:
                    raw_text = raw_text[:max_length] + "..."

                if len(raw_text) >= summary_threshold:
                    def _textrank_summary(text: str) -> str:
                        """TextRank 摘要逻辑"""
                        try:
                            deep_extract_logger.info(f"开始TextRank摘要处理，文本长度: {len(text)} 字符")
                            
                            # 检查文本是否为空或过短
                            if not text or len(text.strip()) < 100:
                                deep_extract_logger.warning("文本过短，跳过摘要处理")
                                return text
                            
                            # 使用正确的TextRank导入方式
                            from summa import summarizer
                            if len(text) < 4000:
                                ratio = 0.2
                            else:
                                ratio = 0.1
                            
                            deep_extract_logger.info(f"使用比例 {ratio} 进行摘要")
                            
                            # 执行摘要
                            summary_text = summarizer.summarize(text, ratio=ratio)
                            
                            # 检查摘要结果
                            if summary_text:
                                deep_extract_logger.info(f"TextRank摘要完成，摘要长度: {len(summary_text)} 字符")
                                return summary_text
                            else:
                                deep_extract_logger.warning("TextRank摘要返回空结果，返回原始文本")
                                return text
                            
                        except ImportError as e:
                            deep_extract_logger.error(f"TextRank依赖导入失败: {str(e)}", exc_info=True)
                            return text
                        except Exception as e:
                            deep_extract_logger.error(f"TextRank摘要处理失败: {str(e)}", exc_info=True)
                            # 摘要失败时返回原始文本
                            return text

                    try:
                        summary_text = _textrank_summary(raw_text)
                        extracted_data['summary'] = summary_text
                        extracted_data['raw_content'] = summary_text
                        extracted_data['is_summarized'] = True
                    except Exception as e:
                        extracted_data['is_summarized'] = False
                        deep_extract_logger.warning(f"TextRank 摘要失败 ({url}): {str(e)}")
                else:
                    extracted_data['is_summarized'] = False

            # ========== 4. 增强标题信息 ==========
            if not extracted_data.get('title') or extracted_data['title'] == '':
                if 'raw_content' in extracted_data:
                    title = extracted_data['raw_content'][:100].strip()
                    if title:
                        extracted_data['title'] = title
                else:
                    extracted_data['title'] = url.split('/')[-1] if '/' in url else url

            # ========== 5. 添加元数据 ==========
            extracted_data['preprocessed_at'] = time.time()
            extracted_data['content_length'] = len(extracted_data.get('raw_content', ''))

            deep_extract_logger.info(
                f"✅ 预处理完成: {url}, 长度: {extracted_data['content_length']}, 是否摘要: {extracted_data.get('is_summarized', False)}"
            )

        except Exception as e:
            deep_extract_logger.error(f"❌ 预处理失败 {url}: {str(e)}", exc_info=True)

        return extracted_data



    def _format_extract_results(self, results: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        """格式化提取结果为 LLM 友好型结构化输出"""
        
        summary = {
            "query": query,
            "total_urls": len(results),
            "success_count": 0,
            "failed_count": 0,
            "success_rate": 0.0,
            "records": []  # 每个URL的结构化记录
        }

        for result in results:
            record = {
                "url": result.get("url", None),
                "status": result.get("status", "unknown"),
                "answer": result.get("answer", None),
                "title": result.get("title", None),
                "content": result.get("content", None),
                "error": result.get("error", None)
            }
            
            # 统计成功/失败数量
            if record["status"] == "success":
                summary["success_count"] += 1
            elif record["status"] == "failed":
                summary["failed_count"] += 1
            
            summary["records"].append(record)
        
        # 计算成功率
        if summary["total_urls"] > 0:
            summary["success_rate"] = round(summary["success_count"] / summary["total_urls"] * 100, 2)
        
        return summary

def create_deep_extract_tool() -> DeepExtractTool:
    """创建并返回深度提取工具实例"""
    return DeepExtractTool()