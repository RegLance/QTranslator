"""单词收藏（原文唯一键 + 译文/笔记）。"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ..config import get_config
    from ..utils.logger import log_debug, log_error, log_info
except ImportError:
    from src.config import get_config
    from src.utils.logger import log_debug, log_error, log_info


@dataclass
class VocabularyItem:
    """收藏条目：word 为唯一主键（可为词或短句）。"""

    word: str
    translation: str
    target_language: str = ""
    review_count: int = 1
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VocabularyItem":
        return cls(
            word=str(data.get("word", "")),
            translation=str(data.get("translation", data.get("description", ""))),
            target_language=str(data.get("target_language", "")),
            review_count=int(data.get("review_count", 1)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


class WordVocabulary:
    _instance: Optional["WordVocabulary"] = None

    MAX_ITEMS = 5000

    def __init__(self) -> None:
        self._config = get_config()
        self._dir = self._config.app_dir / "vocabulary"
        self._file = self._dir / "words.json"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._save_timer: Optional[threading.Timer] = None
        self._save_lock = threading.Lock()
        self._items: Dict[str, VocabularyItem] = {}
        self._order: List[str] = []
        self._load()

    @classmethod
    def get_instance(cls) -> "WordVocabulary":
        if cls._instance is None:
            cls._instance = WordVocabulary()
        return cls._instance

    def _load(self) -> None:
        if not self._file.exists():
            log_debug("单词收藏：无已有文件")
            return
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                for d in raw:
                    it = VocabularyItem.from_dict(d)
                    if it.word:
                        self._items[it.word] = it
                self._order = [str(d.get("word", "")) for d in raw if d.get("word")]
            log_debug(f"单词收藏加载完成，共 {len(self._items)} 条")
        except Exception as e:
            log_error(f"加载单词收藏失败: {e}")

    def _schedule_save(self) -> None:
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(1.0, self._do_save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _do_save(self) -> None:
        try:
            lst = [self._items[k].to_dict() for k in self._order if k in self._items]
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(lst, f, ensure_ascii=False, indent=2)
            log_debug(f"单词收藏已保存 {len(lst)} 条")
        except Exception as e:
            log_error(f"保存单词收藏失败: {e}")

    def flush(self) -> None:
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
        self._do_save()

    def is_collected(self, word: str) -> bool:
        """是否与单词本中某条记录的「原文」完全一致（strip 后字符串相等，区分大小写）。"""
        w = (word or "").strip()
        return w in self._items

    def get_item(self, word: str) -> Optional[VocabularyItem]:
        return self._items.get((word or "").strip())

    def put_item(self, word: str, translation: str, target_language: str = "") -> VocabularyItem:
        w = (word or "").strip()
        if not w:
            raise ValueError("word 不能为空")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if w in self._items:
            it = self._items[w]
            it.translation = translation or ""
            it.target_language = target_language or it.target_language
            it.review_count = min(it.review_count + 1, 999999)
            it.updated_at = now
        else:
            it = VocabularyItem(
                word=w,
                translation=translation or "",
                target_language=target_language or "",
                review_count=1,
                created_at=now,
                updated_at=now,
            )
            self._items[w] = it
            self._order.insert(0, w)
        while len(self._order) > self.MAX_ITEMS:
            old = self._order.pop()
            self._items.pop(old, None)
        self._schedule_save()
        log_info(f"单词收藏: 已保存「{w[:24]}…」" if len(w) > 24 else f"单词收藏: 已保存「{w}」")
        return it

    def remove_item(self, word: str) -> bool:
        w = (word or "").strip()
        if w not in self._items:
            return False
        del self._items[w]
        try:
            self._order.remove(w)
        except ValueError:
            pass
        self._schedule_save()
        log_debug(f"单词收藏: 已删除「{w[:30]}」")
        return True

    def list_items(self) -> List[VocabularyItem]:
        return [self._items[k] for k in self._order if k in self._items]

    def clear_all(self) -> None:
        self._items.clear()
        self._order.clear()
        self._schedule_save()
        log_info("单词收藏已清空")

    def search(self, keyword: str) -> List[VocabularyItem]:
        k = (keyword or "").strip().lower()
        if not k:
            return self.list_items()
        out: List[VocabularyItem] = []
        for item in self.list_items():
            if k in item.word.lower() or k in item.translation.lower():
                out.append(item)
        return out

    def list_frequency_items(self, limit: int = 50) -> List[VocabularyItem]:
        """按 review_count 降序取前 limit 条（供词汇短文等按频率选词）。"""
        lim = max(0, int(limit))
        if lim == 0:
            return []
        items = [self._items[k] for k in self._order if k in self._items]
        items.sort(key=lambda x: (-x.review_count, x.word.lower()))
        return items[:lim]

    @property
    def file_path(self) -> Path:
        return self._file


def get_vocabulary() -> WordVocabulary:
    return WordVocabulary.get_instance()
