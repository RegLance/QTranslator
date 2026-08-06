"""AI 对话会话存储模块 - QTranslator

会话（session）与上下文（messages）全部保存在本地 JSON 文件中
（AppData/Local/QTranslator/chat_sessions.json），不上传任何服务器。
"""
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ..config import get_config
    from ..utils.logger import log_info, log_error, log_debug
except ImportError:
    from src.config import get_config
    from src.utils.logger import log_info, log_error, log_debug


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_session_id() -> str:
    return uuid.uuid4().hex[:16]


class ChatStore:
    """AI 对话会话本地存储（JSON 文件持久化）"""

    def __init__(self):
        self._path: Path = get_config().app_dir / "chat_sessions.json"
        self._sessions: List[Dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _load(self):
        try:
            if self._path.exists():
                with open(self._path, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                sessions = data.get('sessions', []) if isinstance(data, dict) else []
                # 基本结构校验，坏数据直接丢弃避免崩溃
                self._sessions = [
                    s for s in sessions
                    if isinstance(s, dict) and s.get('id') and isinstance(s.get('messages'), list)
                ]
                log_debug(f"已加载 {len(self._sessions)} 个对话会话: {self._path}")
        except Exception as e:
            log_error(f"加载对话会话失败: {e}")
            self._sessions = []

    def _save(self):
        try:
            tmp_path = self._path.with_suffix('.json.tmp')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump({'sessions': self._sessions}, f, ensure_ascii=False, indent=1)
            tmp_path.replace(self._path)
        except Exception as e:
            log_error(f"保存对话会话失败: {e}")

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------
    def list_sessions(self) -> List[Dict[str, Any]]:
        """按最近更新时间倒序返回会话摘要列表"""
        ordered = sorted(self._sessions, key=lambda s: s.get('updated_at', 0), reverse=True)
        return ordered

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        for s in self._sessions:
            if s.get('id') == session_id:
                return s
        return None

    def create_session(self, title: str = "新对话", skill: str = "") -> Dict[str, Any]:
        """新建会话并置顶"""
        session = {
            'id': _new_session_id(),
            'title': title or "新对话",
            'skill': skill or "",       # 该会话激活的 Skill 名称（可为空）
            'summary': "",              # 历史对话的滚动摘要（上下文压缩产物）
            'summary_count': 0,         # 已被摘要覆盖的消息条数
            'created_at': _now_ms(),
            'updated_at': _now_ms(),
            'messages': [],             # [{"role": "user"/"assistant", "content": str}]
        }
        self._sessions.append(session)
        self._save()
        log_info(f"新建对话会话: {session['id']}")
        return session

    def delete_session(self, session_id: str) -> bool:
        before = len(self._sessions)
        self._sessions = [s for s in self._sessions if s.get('id') != session_id]
        if len(self._sessions) != before:
            self._save()
            log_info(f"删除对话会话: {session_id}")
            return True
        return False

    def rename_session(self, session_id: str, title: str):
        s = self.get_session(session_id)
        if s and title and title.strip():
            s['title'] = title.strip()[:60]
            self._save()

    def set_session_skill(self, session_id: str, skill_name: str):
        s = self.get_session(session_id)
        if s:
            s['skill'] = skill_name or ""
            self._save()

    def set_session_summary(self, session_id: str, summary: str, covered_count: int):
        """保存上下文压缩后的滚动摘要及其覆盖的消息条数"""
        s = self.get_session(session_id)
        if not s:
            return
        s['summary'] = summary or ""
        covered = max(0, int(covered_count or 0))
        s['summary_count'] = min(covered, len(s.get('messages', [])))
        self._save()

    # ------------------------------------------------------------------
    # 消息管理
    # ------------------------------------------------------------------
    def append_message(self, session_id: str, role: str, content: str):
        s = self.get_session(session_id)
        if not s:
            return
        s['messages'].append({'role': role, 'content': content})
        s['updated_at'] = _now_ms()
        # 首条用户消息作为会话标题
        if role == 'user' and (not s.get('title') or s['title'] == "新对话"):
            title = content.strip().replace('\n', ' ')
            s['title'] = title[:24] + ('…' if len(title) > 24 else '')
        self._save()

    def update_last_assistant_message(self, session_id: str, content: str):
        """流式输出完成后，覆盖写入最后一条 assistant 消息"""
        s = self.get_session(session_id)
        if not s:
            return
        if s['messages'] and s['messages'][-1].get('role') == 'assistant':
            s['messages'][-1]['content'] = content
        else:
            s['messages'].append({'role': 'assistant', 'content': content})
        s['updated_at'] = _now_ms()
        self._save()

    def get_context_messages(self, session_id: str) -> List[Dict[str, str]]:
        """获取会话的全部上下文消息（不限制条数，超窗口由摘要压缩处理）"""
        s = self.get_session(session_id)
        if not s:
            return []
        msgs = [
            {'role': m['role'], 'content': m['content']}
            for m in s['messages']
            if m.get('role') in ('user', 'assistant') and m.get('content')
        ]
        return msgs

    def clear_messages(self, session_id: str):
        s = self.get_session(session_id)
        if s:
            s['messages'] = []
            s['summary'] = ""
            s['summary_count'] = 0
            s['updated_at'] = _now_ms()
            self._save()


# 全局实例
_store_instance: Optional[ChatStore] = None


def get_chat_store() -> ChatStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = ChatStore()
    return _store_instance
