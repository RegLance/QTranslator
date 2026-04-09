"""翻译历史模块 - 保存和管理翻译历史记录"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict

try:
    from ..config import get_config, APP_NAME
    from ..utils.logger import log_info, log_error, log_debug
except ImportError:
    from src.config import get_config, APP_NAME
    from src.utils.logger import log_info, log_error, log_debug


@dataclass
class HistoryItem:
    """翻译历史条目"""
    id: str  # 唯一标识（时间戳）
    timestamp: str  # 翻译时间
    original_text: str  # 原文
    translated_text: str  # 译文
    target_language: str  # 目标语言
    source: str  # 来源：selection（划词）或 manual（手动输入）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HistoryItem':
        """从字典创建"""
        return cls(**data)


class TranslationHistory:
    """翻译历史管理类"""
    
    _instance: Optional['TranslationHistory'] = None
    
    MAX_HISTORY_COUNT = 100  # 最大历史记录数量
    
    def __init__(self):
        """初始化翻译历史"""
        self._config = get_config()
        self._history_dir = self._config.app_dir / "history"
        self._history_file = self._history_dir / "translations.json"
        
        # 确保目录存在
        self._history_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载历史记录
        self._history: List[HistoryItem] = self._load_history()
        
        log_debug(f"翻译历史初始化完成，共 {len(self._history)} 条记录")
        
    @classmethod
    def get_instance(cls) -> 'TranslationHistory':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = TranslationHistory()
        return cls._instance
    
    def _load_history(self) -> List[HistoryItem]:
        """加载历史记录"""
        if not self._history_file.exists():
            return []
        
        try:
            with open(self._history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [HistoryItem.from_dict(item) for item in data]
        except Exception as e:
            log_error(f"加载翻译历史失败: {e}")
            return []
    
    def _save_history(self):
        """保存历史记录"""
        try:
            data = [item.to_dict() for item in self._history]
            with open(self._history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log_debug(f"翻译历史已保存，共 {len(self._history)} 条记录")
        except Exception as e:
            log_error(f"保存翻译历史失败: {e}")
    
    def add_record(self, original_text: str, translated_text: str,
                   target_language: str, source: str = "selection") -> HistoryItem:
        """添加翻译记录
        
        Args:
            original_text: 原文
            translated_text: 译文
            target_language: 目标语言
            source: 来源（selection 或 manual）
            
        Returns:
            HistoryItem: 创建的历史记录
        """
        # 生成唯一 ID（时间戳）
        timestamp = datetime.now()
        id_str = timestamp.strftime("%Y%m%d%H%M%S%f")
        
        # 创建历史记录
        item = HistoryItem(
            id=id_str,
            timestamp=timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            original_text=original_text,
            translated_text=translated_text,
            target_language=target_language,
            source=source
        )
        
        # 添加到历史列表（最新的在最前面）
        self._history.insert(0, item)
        
        # 限制历史记录数量
        if len(self._history) > self.MAX_HISTORY_COUNT:
            self._history = self._history[:self.MAX_HISTORY_COUNT]
        
        # 保存
        self._save_history()
        
        log_info(f"添加翻译历史: [{target_language}] 原文={original_text[:30]}...")
        
        return item
    
    def get_history(self, limit: int = 50) -> List[HistoryItem]:
        """获取历史记录
        
        Args:
            limit: 最大数量
            
        Returns:
            List[HistoryItem]: 历史记录列表
        """
        return self._history[:limit]
    
    def search_history(self, keyword: str) -> List[HistoryItem]:
        """搜索历史记录
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            List[HistoryItem]: 匹配的记录
        """
        keyword = keyword.lower()
        results = []
        for item in self._history:
            if keyword in item.original_text.lower() or \
               keyword in item.translated_text.lower():
                results.append(item)
        return results
    
    def delete_record(self, id_str: str) -> bool:
        """删除指定记录
        
        Args:
            id_str: 记录 ID
            
        Returns:
            bool: 是否成功删除
        """
        for i, item in enumerate(self._history):
            if item.id == id_str:
                self._history.pop(i)
                self._save_history()
                log_info(f"删除翻译历史: {id_str}")
                return True
        return False
    
    def clear_history(self):
        """清空所有历史记录"""
        self._history.clear()
        self._save_history()
        log_info("翻译历史已清空")
    
    def get_recent_languages(self) -> List[str]:
        """获取最近使用的目标语言"""
        languages = []
        for item in self._history:
            if item.target_language not in languages:
                languages.append(item.target_language)
        return languages[:5]  # 返回最近5种语言
    
    @property
    def history_file(self) -> Path:
        """历史文件路径"""
        return self._history_file
    
    @property
    def history_dir(self) -> Path:
        """历史目录"""
        return self._history_dir


# 全局历史实例
_history_instance: Optional[TranslationHistory] = None


def get_history() -> TranslationHistory:
    """获取全局历史实例"""
    global _history_instance
    if _history_instance is None:
        _history_instance = TranslationHistory()
    return _history_instance


def add_translation_history(original: str, translated: str,
                             target_lang: str, source: str = "selection") -> HistoryItem:
    """添加翻译历史（便捷函数）"""
    return get_history().add_record(original, translated, target_lang, source)


def get_translation_history(limit: int = 50) -> List[HistoryItem]:
    """获取翻译历史（便捷函数）"""
    return get_history().get_history(limit)