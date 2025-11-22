# toolkit/current_time.py

from typing import Any, Dict, Optional
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field
import datetime
import pytz
from zoneinfo import ZoneInfo
import time

class CurrentTimeInput(BaseModel):
    """时间工具输入参数模型"""
    timezone: Optional[str] = Field(
        default=None,
        description="可选时区名称，如：'Asia/Shanghai'、'America/New_York'、'UTC'等。不指定时使用系统时区"
    )
    format: Optional[str] = Field(
        default="%Y-%m-%d %H:%M:%S %Z%z",
        description="时间格式字符串，默认：YYYY-MM-DD HH:MM:SS 时区偏移"
    )

class CurrentTimeTool(StructuredTool):
    """时间工具，快速获取当前时间和指定时区的时间信息"""
    
    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            name="current_time",
            description="""快速获取当前时间信息的工具。支持获取系统当前时间或指定时区的时间。
特别适合：时间同步、时区转换、时间戳生成、日程安排等场景。
输入可以指定时区和时间格式，不指定时使用系统默认设置。""",
            args_schema=CurrentTimeInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs
        )

    def _run(self, **kwargs) -> str:
        """同步执行时间获取"""
        try:
            return self._get_current_time(**kwargs)
        except Exception as e:
            return f"时间获取失败：{str(e)}"

    async def _arun(self, **kwargs) -> str:
        """异步执行时间获取"""
        try:
            return self._get_current_time(**kwargs)
        except Exception as e:
            return f"时间获取失败：{str(e)}"

    def _get_current_time(self, **kwargs) -> str:
        """获取当前时间信息"""
        # 提取输入参数
        timezone_str = kwargs.get('timezone')
        time_format = kwargs.get('format', "%Y-%m-%d %H:%M:%S %Z%z")
        
        # 获取当前时间
        if timezone_str:
            # 使用指定时区
            try:
                # 尝试使用zoneinfo（Python 3.9+）
                if hasattr(__import__('zoneinfo'), 'ZoneInfo'):
                    tz = ZoneInfo(timezone_str)
                    current_time = datetime.datetime.now(tz)
                else:
                    # 回退到pytz
                    tz = pytz.timezone(timezone_str)
                    current_time = datetime.datetime.now(tz)
            except Exception as e:
                return f"时区 '{timezone_str}' 无效或不受支持：{str(e)}"
        else:
            # 使用系统时区
            current_time = datetime.datetime.now()
        
        # 格式化时间信息
        formatted_time = self._format_time_info(current_time, time_format, timezone_str)
        
        return formatted_time

    def _format_time_info(self, current_time: datetime.datetime,
                            time_format: str,
                            timezone_str: Optional[str] = None) -> Dict[str, Any]:
        """格式化时间信息为 LLM 友好型结构化输出"""

        result: Dict[str, Any] = {}

        # === 基本时间格式 ===
        try:
            formatted_time = current_time.strftime(time_format)
        except Exception:
            formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S %Z%z")

        result["current_time"] = formatted_time
        result["iso_format"] = current_time.isoformat()
        result["timezone"] = timezone_str or (current_time.tzname() or "local")

        # === 时间戳信息 ===
        timestamp = current_time.timestamp()
        result["timestamp"] = {
            "unix": int(timestamp),
            "milliseconds": int(timestamp * 1000)
        }

        # === 日期组成部分 ===
        result["date_components"] = {
            "year": current_time.year,
            "month": current_time.month,
            "month_name": current_time.strftime("%B"),
            "day": current_time.day,
            "weekday": current_time.weekday() + 1,
            "weekday_name": current_time.strftime("%A")
        }

        # === 时间组成部分 ===
        result["time_components"] = {
            "hour": current_time.hour,
            "minute": current_time.minute,
            "second": current_time.second,
            "microsecond": current_time.microsecond
        }

        # === 时区偏移 ===
        utc_offset = None
        if current_time.tzinfo:
            offset = current_time.utcoffset()
            if offset:
                utc_offset = offset.total_seconds() / 3600
        result["utc_offset_hours"] = utc_offset


        # === 汇总描述（供 LLM 快速理解） ===
        result["summary"] = (
            f"Current time: {formatted_time}, "
            f"Timezone: {result['timezone']}, "
            f"UTC offset: {utc_offset or 'unknown'}h"
        )

        return result

    def _get_common_timezones(self) -> Dict[str, str]:
        """获取常用时区列表"""
        return {
            "UTC": "协调世界时",
            "Asia/Shanghai": "中国标准时间",
            "Asia/Tokyo": "日本时间", 
            "America/New_York": "美国东部时间",
            "Europe/London": "英国时间",
            "Europe/Paris": "法国时间",
            "Australia/Sydney": "悉尼时间",
            "Asia/Singapore": "新加坡时间",
            "Asia/Dubai": "迪拜时间",
            "America/Los_Angeles": "美国太平洋时间"
        }

def create_current_time_tool() -> CurrentTimeTool:
    """
    创建并返回时间工具实例

    Returns:
        CurrentTimeTool: 配置好的时间工具实例
    """
    return CurrentTimeTool()
