# toolkit/config_utils.py

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# 配置日志
logger = logging.getLogger(__name__)

class ConfigLoader:
    """统一的配置加载工具类，提供多路径环境变量加载机制"""
    
    @staticmethod
    def load_environment_variables() -> bool:
        """
        从多个可能的路径加载环境变量，支持优先级机制
        
        加载顺序（从高到低优先级）：
        1. 当前目录的 .env 文件
        2. toolkit 目录的 .env 文件
        3. 项目根目录的 .env 文件
        4. 环境变量中已存在的值（不被覆盖）
        
        Returns:
            bool: 至少成功加载一个 .env 文件返回 True，否则返回 False
        """
        loaded = False
        
        # 获取各种可能的 .env 文件路径
        paths_to_try = [
            # 1. 当前目录的 .env
            Path.cwd() / ".env",
            # 2. toolkit 目录的 .env
            Path(__file__).parent / ".env",
            # 3. 项目根目录的 .env (尝试多种可能的上移层级)
            Path(__file__).resolve().parent.parent / ".env",
            Path(__file__).resolve().parent.parent.parent / ".env",
            Path(__file__).resolve().parent.parent.parent.parent / ".env",
            Path(__file__).resolve().parent.parent.parent.parent.parent / ".env"
        ]
        
        # 移除重复路径并尝试加载
        unique_paths = list(dict.fromkeys(paths_to_try))  # 保持顺序并去重
        
        for env_path in unique_paths:
            if env_path.exists():
                try:
                    load_dotenv(env_path)
                    logger.info(f"成功从 {env_path} 加载环境变量")
                    loaded = True
                except Exception as e:
                    logger.error(f"从 {env_path} 加载环境变量失败: {str(e)}")
        
        if not loaded:
            logger.warning("未找到或无法加载任何 .env 文件，将使用系统环境变量")
        
        return loaded
    
    @staticmethod
    def get_api_key(key_name: str, default: str = None) -> str:
        """
        获取指定的 API 密钥
        
        Args:
            key_name: 环境变量名称
            default: 默认值，如果环境变量未设置则返回
            
        Returns:
            str: API 密钥或默认值
        """
        value = os.getenv(key_name, default)
        if value is None:
            logger.warning(f"API 密钥 '{key_name}' 未设置")
        return value
    
    @staticmethod
    def ensure_api_key(key_name: str) -> None:
        """
        确保指定的 API 密钥已设置，否则抛出异常
        
        Args:
            key_name: 环境变量名称
            
        Raises:
            ValueError: 如果 API 密钥未设置
        """
        value = os.getenv(key_name)
        if not value:
            raise ValueError(f"API 密钥 '{key_name}' 未设置，请检查 .env 文件或系统环境变量")

# 初始化：尝试加载环境变量
_config_loaded = ConfigLoader.load_environment_variables()

# 导出便捷函数
def load_env() -> bool:
    """快捷函数：加载环境变量"""
    return ConfigLoader.load_environment_variables()

def get_key(key_name: str, default: str = None) -> str:
    """快捷函数：获取 API 密钥"""
    return ConfigLoader.get_api_key(key_name, default)

def require_key(key_name: str) -> None:
    """快捷函数：确保 API 密钥已设置"""
    return ConfigLoader.ensure_api_key(key_name)
