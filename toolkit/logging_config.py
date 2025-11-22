# toolkit/logging_config.py
"""
工具模块的统一日志配置

功能特性：
1. 统一的日志格式和级别管理
2. 文件和控制台双重输出
3. 按日期自动分割日志文件
4. 支持不同工具模块的独立日志器
5. 去除表情符号，使用标准日志格式
"""
import logging
import os
from datetime import datetime
from typing import Dict, Optional

class ToolkitLogger:
    """工具包日志管理器"""
    
    # 日志级别映射
    LOG_LEVELS = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    
    def __init__(self, log_level: str = 'INFO', log_to_console: bool = True):
        """
        初始化日志管理器
        
        Args:
            log_level: 日志级别，可选 DEBUG/INFO/WARNING/ERROR/CRITICAL
            log_to_console: 是否输出到控制台
        """
        self.log_level = self.LOG_LEVELS.get(log_level.upper(), logging.INFO)
        self.log_to_console = log_to_console
        self.loggers: Dict[str, logging.Logger] = {}
        
        # 创建日志目录
        self.log_dir = os.path.join(os.path.dirname(__file__), 'logs')
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        # 配置根日志器
        self._setup_root_logger()
    
    def _setup_root_logger(self):
        """配置根日志器"""
        # 日志文件名格式：toolkit_YYYYMMDD.log
        log_file = os.path.join(
            self.log_dir, 
            f'toolkit_{datetime.now().strftime("%Y%m%d")}.log'
        )
        
        # 配置日志格式
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        date_format = '%Y-%m-%d %H:%M:%S'
        
        # 创建根日志器
        root_logger = logging.getLogger('toolkit')
        root_logger.setLevel(self.log_level)
        
        # 避免重复添加处理器
        if not root_logger.handlers:
            # 文件处理器
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(self.log_level)
            file_formatter = logging.Formatter(log_format, date_format)
            file_handler.setFormatter(file_formatter)
            
            # 控制台处理器
            if self.log_to_console:
                console_handler = logging.StreamHandler()
                console_handler.setLevel(self.log_level)
                console_formatter = logging.Formatter('%(levelname)s - %(message)s')
                console_handler.setFormatter(console_formatter)
                root_logger.addHandler(console_handler)
            
            root_logger.addHandler(file_handler)
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        获取指定名称的日志器
        
        Args:
            name: 日志器名称，通常是工具模块名
            
        Returns:
            logging.Logger: 配置好的日志器实例
        """
        if name not in self.loggers:
            logger = logging.getLogger(f'toolkit.{name}')
            logger.setLevel(self.log_level)
            self.loggers[name] = logger
        
        return self.loggers[name]
    
    def set_level(self, level: str):
        """
        动态设置日志级别
        
        Args:
            level: 新的日志级别
        """
        new_level = self.LOG_LEVELS.get(level.upper(), logging.INFO)
        self.log_level = new_level
        
        # 更新所有日志器的级别
        root_logger = logging.getLogger('toolkit')
        root_logger.setLevel(new_level)
        
        for handler in root_logger.handlers:
            handler.setLevel(new_level)
        
        for logger in self.loggers.values():
            logger.setLevel(new_level)

# 创建默认的日志管理器实例
logger_manager = ToolkitLogger(log_level='INFO', log_to_console=True)

# 为各个工具模块预定义日志器
area_weather_logger = logger_manager.get_logger('area_weather')
path_navigate_logger = logger_manager.get_logger('path_navigate')
deep_search_logger = logger_manager.get_logger('deep_search')
deep_extract_logger = logger_manager.get_logger('deep_extract')
fast_search_logger = logger_manager.get_logger('fast_search')
current_time_logger = logger_manager.get_logger('current_time')

# 便捷函数
def get_logger(name: str) -> logging.Logger:
    """便捷函数：获取指定名称的日志器"""
    return logger_manager.get_logger(name)

def set_log_level(level: str):
    """便捷函数：设置全局日志级别"""
    logger_manager.set_level(level)

def disable_console_output():
    """便捷函数：禁用控制台输出"""
    global logger_manager
    logger_manager = ToolkitLogger(log_level='INFO', log_to_console=False)

# 模块初始化信息
area_weather_logger.info("日志配置模块初始化完成")
area_weather_logger.info(f"日志文件目录: {logger_manager.log_dir}")
area_weather_logger.info(f"当前日志级别: {logging.getLevelName(logger_manager.log_level)}")
