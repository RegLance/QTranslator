"""日志模块 - 将日志保存到配置目录"""
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    from ..config import get_config, APP_NAME
except ImportError:
    from src.config import get_config, APP_NAME


class FileLogHandler(logging.Handler):
    """文件日志处理器"""
    
    def __init__(self, log_path: Path):
        super().__init__()
        self._log_path = log_path
        self._ensure_log_file()
        
    def _ensure_log_file(self):
        """确保日志文件存在"""
        if not self._log_path.parent.exists():
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            
    def emit(self, record: logging.LogRecord):
        """写入日志记录"""
        try:
            msg = self.format(record)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_line = f"[{timestamp}] [{record.levelname}] {msg}\n"
            
            with open(self._log_path, 'a', encoding='utf-8') as f:
                f.write(log_line)
        except Exception:
            pass


class Logger:
    """日志管理器"""
    
    _instance: Optional['Logger'] = None
    
    def __init__(self):
        """初始化日志"""
        self._config = get_config()
        self._log_dir = self._config.app_dir / "logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        
        # 当前日志文件（按日期命名）
        today = datetime.now().strftime("%Y-%m-%d")
        self._log_file = self._log_dir / f"{today}.log"
        
        # 创建 Python logger
        self._logger = logging.getLogger(APP_NAME)
        self._logger.setLevel(logging.DEBUG)
        
        # 清除现有的 handlers
        self._logger.handlers.clear()
        
        # 添加文件 handler
        file_handler = FileLogHandler(self._log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter('%(message)s'))
        self._logger.addHandler(file_handler)
        
        # 同时输出到 stderr（控制台）
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.INFO)
        stderr_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        self._logger.addHandler(stderr_handler)
        
    @classmethod
    def get_instance(cls) -> 'Logger':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = Logger()
        return cls._instance
    
    @property
    def log_file(self) -> Path:
        """当前日志文件路径"""
        return self._log_file
    
    @property
    def log_dir(self) -> Path:
        """日志目录"""
        return self._log_dir
    
    def debug(self, msg: str):
        """记录调试信息"""
        self._logger.debug(msg)
        
    def info(self, msg: str):
        """记录一般信息"""
        self._logger.info(msg)
        
    def warning(self, msg: str):
        """记录警告"""
        self._logger.warning(msg)
        
    def error(self, msg: str):
        """记录错误"""
        self._logger.error(msg)
        
    def exception(self, msg: str):
        """记录异常（包含堆栈信息）"""
        self._logger.exception(msg)
        
    def log_translation(self, original: str, translated: str, target_lang: str):
        """记录翻译历史"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"翻译记录: [{target_lang}] 原文: {original[:100]}... -> 译文: {translated[:100]}..."
        self.info(log_entry)
        
    def clear_old_logs(self, days: int = 7):
        """清理旧日志文件"""
        try:
            cutoff_date = datetime.now() - datetime.timedelta(days=days)
            for log_file in self._log_dir.glob("*.log"):
                try:
                    date_str = log_file.stem  # 文件名格式: YYYY-MM-DD.log
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if file_date < cutoff_date:
                        log_file.unlink()
                        self.info(f"清理旧日志: {log_file.name}")
                except ValueError:
                    pass  # 非日期格式的文件名跳过
        except Exception as e:
            self.error(f"清理日志失败: {e}")


# 全局日志实例
_logger_instance: Optional[Logger] = None


def get_logger() -> Logger:
    """获取全局日志实例"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger()
    return _logger_instance


def log_debug(msg: str):
    """记录调试信息"""
    get_logger().debug(msg)


def log_info(msg: str):
    """记录一般信息"""
    get_logger().info(msg)


def log_warning(msg: str):
    """记录警告"""
    get_logger().warning(msg)


def log_error(msg: str):
    """记录错误"""
    get_logger().error(msg)


def log_exception(msg: str):
    """记录异常"""
    get_logger().exception(msg)


def log_translation(original: str, translated: str, target_lang: str):
    """记录翻译历史"""
    get_logger().log_translation(original, translated, target_lang)