"""AI 对话窗口 - QTranslator

独立于翻译窗口的对话窗口（类似豆包 / Cherry Studio 的划词「AI 对话」入口）：
- 左侧会话列表：可新建 / 重命名 / 删除对话 session
- 会话上下文与 session 全部保存在本地（ChatStore → chat_sessions.json）
- 支持激活 Skill（SKILL.md 正文注入系统提示词）
- 支持 MCP 工具调用（官方 mcp SDK，工具在后台由 MCPClientManager 托管）
"""
import html
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import (Qt, QPoint, QRect, QThread, pyqtSignal, QTimer,
                          QEvent, QEasingCurve, QTimeLine)
from PyQt6.QtGui import QCursor, QIcon, QPainter, QPen, QColor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextBrowser, QPlainTextEdit, QMenu, QFrame,
    QToolButton, QInputDialog, QSplitter, QSplitterHandle, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QMessageBox, QCheckBox,
    QScrollBar, QScrollArea, QAbstractButton, QAbstractSlider,
    QAbstractScrollArea, QSizePolicy,
)

try:
    from ..config import get_config, APP_NAME
    from ..utils.logger import log_info, log_error, log_debug
    from ..utils.theme import get_theme
    from ..core.chat_store import get_chat_store
    from ..core.skills import get_skill_manager
    from ..core.skill_tools import get_skill_local_tools
    from ..core.mcp_client import get_mcp_manager, MCPToolInfo
except ImportError:
    from src.config import get_config, APP_NAME
    from src.utils.logger import log_info, log_error, log_debug
    from src.utils.theme import get_theme
    from src.core.chat_store import get_chat_store
    from src.core.skills import get_skill_manager
    from src.core.skill_tools import get_skill_local_tools
    from src.core.mcp_client import get_mcp_manager, MCPToolInfo

BASE_SYSTEM_PROMPT = (
    "你是 QTranslator 内置的 AI 助手，可以回答用户基于划词内容或自由输入的问题。"
    "请使用与用户相同的语言回答，回答简洁清晰，必要时使用 Markdown 格式。"
)

MAX_TOOL_ROUNDS = 5  # MCP 工具调用最大轮数，防止死循环


# ── Markdown -> Qt 富文本（Qt 仅支持 HTML 子集：
# https://doc.qt.io/qt-6/richtext-html-subset.html）──
_RE_HEADING = re.compile(r'^(#{1,4})\s+(.+)$')
_RE_HR = re.compile(r'^(-{3,}|\*{3,}|_{3,})$')
_RE_QUOTE = re.compile(r'^>\s?(.*)$')
_RE_UL = re.compile(r'^[-*+]\s+(.+)$')
_RE_OL = re.compile(r'^\d+[.)]\s+(.+)$')
_RE_TABLE_SEP_CELL = re.compile(r'^:?-+:?$')
_RE_INLINE_CODE = re.compile(r'`([^`\n]+)`')
_RE_LINK = re.compile(r'\[([^\]]+)\]\(([^)\s]+)\)')
_RE_BOLD = re.compile(r'\*\*(.+?)\*\*')
_RE_ITALIC = re.compile(r'\*([^\s*](?:[^*\n]*?[^\s*])?)\*')
_RE_STRIKE = re.compile(r'~~(.+?)~~')


def _inline_md(text: str) -> str:
    """行内 Markdown：链接/加粗/斜体/删除线/行内代码（入参须已 html 转义）"""
    codes: List[str] = []

    def _keep_code(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = _RE_INLINE_CODE.sub(_keep_code, text)
    text = _RE_LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _RE_BOLD.sub(r'<b>\1</b>', text)
    text = _RE_ITALIC.sub(r'<i>\1</i>', text)
    text = _RE_STRIKE.sub(r'<s>\1</s>', text)
    for i, code in enumerate(codes):
        text = text.replace(
            f"\x00{i}\x00",
            f'<span style="font-family: Consolas, monospace; '
            f'background-color: rgba(128, 128, 128, 0.22);">{code}</span>')
    return text


def _blocks_to_html(text: str, keep_blanks: bool = False) -> str:
    """块级 Markdown：标题/列表/引用/表格/分隔线，其余按段落（行间 <br>）"""
    parts: List[str] = []
    para: List[str] = []
    list_tag = ''

    def flush_para():
        if para:
            parts.append('<br>'.join(para))
            para.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            parts.append(f'</{list_tag}>')
            list_tag = ''

    lines = text.split('\n')
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped:
            flush_para()
            close_list()
            if keep_blanks:
                # 忠实保留空行：段落间 k 个空行 = k+1 个换行（含前行结尾的
                # 换行）；段首/段尾 k 个空行 = k 个换行。原实现每段间断恒定
                # 少 1 个换行，空行被吞，定稿纯文本→富文本切换时内容缩短、
                # 整段文字上跳
                j = i
                while j < len(lines) and not lines[j].strip():
                    j += 1
                _middle = bool(parts) and j < len(lines)
                parts.append('<br>' * (j - i + (1 if _middle else 0)))
                i = j
            else:
                parts.append('<br>')
                i += 1
            continue

        m = _RE_HEADING.match(stripped)
        if m:
            flush_para()
            close_list()
            lv = len(m.group(1))
            parts.append(f'<h{lv}>{_inline_md(html.escape(m.group(2)))}</h{lv}>')
            i += 1
            continue

        if _RE_HR.match(stripped):
            flush_para()
            close_list()
            parts.append('<hr>')
            i += 1
            continue

        m = _RE_QUOTE.match(stripped)
        if m:
            flush_para()
            close_list()
            parts.append(f'<blockquote>{_inline_md(html.escape(m.group(1)))}</blockquote>')
            i += 1
            continue

        # 表格：连续以 | 开头的行（首行为表头，|---| 分隔行跳过）
        if stripped.startswith('|') and i + 1 < len(lines) \
                and lines[i + 1].strip().startswith('|'):
            flush_para()
            close_list()
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                rows.append(lines[i].strip())
                i += 1
            tbl = ['<table border="1" cellspacing="0" cellpadding="4">']
            for r_i, r in enumerate(rows):
                cells = [c.strip() for c in r.strip('|').split('|')]
                if all(_RE_TABLE_SEP_CELL.match(c) for c in cells if c):
                    continue
                tag = 'th' if r_i == 0 else 'td'
                tbl.append('<tr>' + ''.join(
                    f'<{tag}>{_inline_md(html.escape(c))}</{tag}>' for c in cells
                ) + '</tr>')
            tbl.append('</table>')
            parts.append(''.join(tbl))
            continue

        m = _RE_UL.match(stripped)
        if m:
            flush_para()
            if list_tag != 'ul':
                close_list()
                parts.append('<ul>')
                list_tag = 'ul'
            parts.append(f'<li>{_inline_md(html.escape(m.group(1)))}</li>')
            i += 1
            continue

        m = _RE_OL.match(stripped)
        if m:
            flush_para()
            if list_tag != 'ol':
                close_list()
                parts.append('<ol>')
                list_tag = 'ol'
            parts.append(f'<li>{_inline_md(html.escape(m.group(1)))}</li>')
            i += 1
            continue

        if list_tag:
            close_list()
        para.append(_inline_md(html.escape(lines[i])))
        i += 1

    flush_para()
    close_list()
    return ''.join(parts)


def _format_content(text: str, keep_blanks: bool = False) -> str:
    """Markdown → Qt 富文本 HTML：代码块 / 标题 / 列表 / 引用 / 表格 / 行内样式；
    keep_blanks=True 时忠实保留段落间空行（思考框定稿与流式纯文本逐行一致）"""
    segments = text.split('```')
    parts = []
    for idx, seg in enumerate(segments):
        if idx % 2 == 0:
            parts.append(_blocks_to_html(seg, keep_blanks))
        else:
            seg2 = seg.strip('\n')
            lines = seg2.split('\n')
            # 去掉首行语言标记（如 ```python）
            if len(lines) > 1 and len(lines[0]) <= 20 and ' ' not in lines[0].strip():
                lines = lines[1:]
            # white-space: pre-wrap 保留代码换行缩进，超宽行在气泡内自动折行；
            # 裸 <pre> 按单行布局，超出气泡宽度的部分会在右缘被裁掉（回复被截断）
            parts.append(
                f'<pre style="white-space: pre-wrap;">{html.escape(chr(10).join(lines))}</pre>'
            )
    return ''.join(parts)


def _hex_to_rgba(hex_color: str, alpha: int) -> str:
    """#RRGGBB -> rgba()（用于半透明气泡底色），解析失败退回透明灰"""
    h = (hex_color or '').lstrip('#')
    try:
        if len(h) == 3:
            h = ''.join(ch * 2 for ch in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    except Exception:
        return f"rgba(128, 128, 128, {alpha})"


# ── 上下文压缩策略 ──
# 移植开源方案：LangChain 的 ConversationSummaryBufferMemory（MIT 许可）摘要缓冲模式：
# 最近的消息原文保留，较早的消息被滚动摘要压缩。
# token 计数优先用 OpenAI 开源的 tiktoken（已安装时），否则退化为 CJK 启发式估算。
CONTEXT_USAGE_RATIO = 0.7   # 上下文超过约 70% 模型窗口时触发压缩


def _split_think_tags(text: str):
    """把 <think>...</think> 内嵌思考拆成 (思考, 正文)。

    MiniMax 等模型不走 reasoning_content 字段，而是把思考以 <think> 标签
    形式混在正文里返回——不拆分的话标签会原样显示给用户。
    支持多段 think；未闭合的 <think> 视为其后全部是思考。
    无标签时返回 ('', 原文)。"""
    if not text or '<think>' not in text.lower():
        return '', text
    lower = text.lower()
    parts = []
    reasons = []
    pos = 0
    n = len(text)
    while pos < n:
        i = lower.find('<think>', pos)
        if i < 0:
            parts.append(text[pos:])
            break
        parts.append(text[pos:i])
        j = lower.find('</think>', i + 7)
        if j < 0:
            reasons.append(text[i + 7:])
            break
        reasons.append(text[i + 7:j])
        pos = j + 8
    return '\n'.join(r.strip() for r in reasons if r.strip()), \
        ''.join(parts).strip()
KEEP_RECENT_RATIO = 0.5     # 压缩后最近消息保留约 50% 窗口预算
MIN_KEEP_RECENT = 4         # 最近至少保留 4 条消息不参与摘要
SUMMARY_PROMPT = (
    "你是对话归档员。请把下面的对话历史压缩成一段简洁、完整的摘要，"
    "保留关键事实、决定、用户需求与未完成事项，"
    "使用与对话相同的语言，只输出摘要本身。"
)

_tiktoken_enc = None
_tiktoken_tried = False


def estimate_tokens(text: str) -> int:
    """token 估算：优先 tiktoken（cl100k_base），否则 CJK≈1 token/字、其它≈4 字符/token"""
    global _tiktoken_enc, _tiktoken_tried
    if not text:
        return 0
    if not _tiktoken_tried:
        _tiktoken_tried = True
        try:
            import tiktoken
            _tiktoken_enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tiktoken_enc = None
    if _tiktoken_enc is not None:
        try:
            return len(_tiktoken_enc.encode(text))
        except Exception:
            pass
    cjk = sum(1 for c in text
              if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f'
              or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
    return cjk + (len(text) - cjk + 3) // 4


def _estimate_api_tokens(messages: List[Dict[str, Any]]) -> int:
    return sum(estimate_tokens(str(m.get('content') or '')) + 4 for m in messages)


class ChatWorker(QThread):
    """对话请求后台线程（上下文压缩 / 流式输出 / MCP 工具调用循环）"""

    chunk = pyqtSignal(str)          # 流式文本片段
    reasoning_chunk = pyqtSignal(str)  # 思考模型的思考内容片段（reasoning_content）
    tool_info = pyqtSignal(str)      # MCP 工具调用过程提示
    confirm_request = pyqtSignal(str, str)  # 技能脚本执行确认请求（技能名, 描述）
    finished_ok = pyqtSignal(str, str)  # 完成，(完整文本, 完整思考内容)
    failed = pyqtSignal(str)         # 失败，错误信息
    context_compressed = pyqtSignal(str, str, int)  # (session_id, 新摘要, 覆盖条数)

    def __init__(self, session_id: str, system_prompt: str,
                 history: List[Dict[str, str]], summary: str, summary_count: int,
                 model: str, client_kwargs: Dict[str, Any], context_limit: int,
                 tools: Optional[List[MCPToolInfo]] = None,
                 skill_tools=None):
        super().__init__()
        self._session_id = session_id
        self._system_prompt = system_prompt
        self._history = history
        self._summary = summary or ""
        self._summary_count = max(0, int(summary_count or 0))
        self._model = model
        self._client_kwargs = client_kwargs
        self._context_limit = max(4096, int(context_limit or 32768))
        self._tools = tools or []
        self._skill_tools = skill_tools
        self._cancelled = False
        self._messages: List[Dict[str, Any]] = []
        self._reasoning_full = ""  # 思考模型累积的完整思考内容
        # <think> 标签流式解析状态（思考内嵌正文的模型，如 MiniMax）
        self._think_state = 'normal'
        self._think_buf = ""

    def cancel(self):
        self._cancelled = True

    # ---------------- 技能脚本执行确认（阻塞等待主窗口弹窗结果） ----------------
    def ask_user_confirm(self, skill_name: str, desc: str) -> bool:
        self._confirm_ok = False
        self._confirm_event = threading.Event()
        log_info(f"[Confirm] 后台线程等待用户确认: {skill_name}")
        self.confirm_request.emit(skill_name, desc)
        if not self._confirm_event.wait(120):
            log_info(f"[Confirm] 等待确认超时(120s)按拒绝处理: {skill_name}")
            return False  # 超时按拒绝处理
        log_info(f"[Confirm] 收到确认结果: {skill_name} ok={self._confirm_ok}")
        return self._confirm_ok

    def deliver_confirm(self, ok: bool):
        self._confirm_ok = bool(ok)
        if getattr(self, "_confirm_event", None):
            self._confirm_event.set()

    def run(self):
        try:
            from openai import OpenAI
            client = OpenAI(**self._client_kwargs)

            # 按模型上下文窗口做摘要缓冲压缩（不限消息条数）
            self._messages = self._build_context(client)

            if self._tools or self._skill_tools:
                self._run_with_tools(client)
            else:
                self._run_stream(client)
        except Exception as e:
            if not self._cancelled:
                self.failed.emit(str(e))

    # ---------------- 上下文压缩（摘要缓冲模式） ----------------
    def _build_context(self, client) -> List[Dict[str, Any]]:
        """组装发送给模型的上下文；估算超窗口阈值时压缩较早消息为滚动摘要"""
        history = self._history[self._summary_count:]
        api_messages = [{"role": "system", "content": self._system_prompt}]
        if self._summary:
            api_messages.append({
                "role": "system",
                "content": f"以下是之前与用户对话的摘要：\n{self._summary}",
            })
        api_messages += history

        budget = int(self._context_limit * CONTEXT_USAGE_RATIO)
        if len(history) <= MIN_KEEP_RECENT or _estimate_api_tokens(api_messages) <= budget:
            return api_messages

        # 确定切分点：从后往前累计，保留最近消息（至少 MIN_KEEP_RECENT 条）
        keep_budget = int(budget * KEEP_RECENT_RATIO)
        keep_from = len(history)
        acc = 0
        for i in range(len(history) - 1, -1, -1):
            kept = len(history) - keep_from
            t = estimate_tokens(json.dumps(history[i], ensure_ascii=False))
            if kept >= MIN_KEEP_RECENT and acc + t > keep_budget:
                break
            acc += t
            keep_from = i
        if keep_from <= 0:
            return api_messages  # 全部都是近期消息，无法再压缩

        old_msgs = history[:keep_from]
        new_summary = self._summarize(client, self._summary, old_msgs)
        if not new_summary or self._cancelled:
            return api_messages

        covered = self._summary_count + keep_from
        self._summary = new_summary
        self._summary_count = covered
        self.context_compressed.emit(self._session_id, new_summary, covered)
        log_info(f"对话上下文已压缩: 摘要覆盖前 {covered} 条消息，摘要 {len(new_summary)} 字")

        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "system", "content": f"以下是之前与用户对话的摘要：\n{new_summary}"},
        ] + history[keep_from:]

    def _summarize(self, client, old_summary: str, messages: List[Dict[str, str]]) -> str:
        """调用模型把较早的对话历史压缩为摘要（非流式）"""
        lines = []
        if old_summary:
            lines.append(f"已有摘要：\n{old_summary}")
        lines.append("新增对话：")
        for m in messages:
            role_label = "用户" if m.get('role') == 'user' else "助手"
            lines.append(f"{role_label}: {m.get('content', '')}")
        try:
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": "\n".join(lines)},
                ],
                stream=False,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            log_error(f"上下文压缩失败，按原上下文发送: {e}")
            return ""

    # ---------------- 纯流式（无工具） ----------------
    def _run_stream(self, client):
        stream = client.chat.completions.create(
            model=self._model,
            messages=self._messages,
            stream=True,
        )
        full_text = ""
        for chunk in stream:
            if self._cancelled:
                return
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # 思考模型的思考过程（reasoning_content），与正文分开流式输出
            reasoning = getattr(delta, 'reasoning_content', None)
            if reasoning:
                self._reasoning_full += reasoning
                self.reasoning_chunk.emit(reasoning)
            if delta.content:
                full_text += delta.content
                self._feed_content(delta.content)
        self._feed_content(None)  # 冲刷缓冲：残留的部分标签按正文输出
        self.finished_ok.emit(full_text, self._reasoning_full)

    def _feed_content(self, text):
        """正文流状态机：把 <think>...</think> 内嵌思考拆到 reasoning 通道。

        标签可能跨 chunk 分裂（如 '<th' + 'ink>'），尾部疑似部分标签先
        留在缓冲等下一块；text=None 表示流结束，冲刷全部缓冲。"""
        if text is None:
            if self._think_buf:
                self._emit_body(self._think_buf)
                self._think_buf = ""
            self._think_state = 'normal'
            return
        self._think_buf += text
        while True:
            if self._think_state == 'normal':
                idx = self._think_buf.lower().find('<think>')
                if idx >= 0:
                    if idx:
                        self._emit_body(self._think_buf[:idx])
                    self._think_buf = self._think_buf[idx + 7:]
                    self._think_state = 'think'
                    if not self._reasoning_full:
                        log_info('[Chat] 检测到内嵌 <think> 标签（思考混在正文中）')
                    continue
                hold = self._partial_suffix_len(self._think_buf, '<think>')
                if hold:
                    self._emit_body(self._think_buf[:-hold])
                    self._think_buf = self._think_buf[-hold:]
                else:
                    self._emit_body(self._think_buf)
                    self._think_buf = ""
                return
            else:
                idx = self._think_buf.lower().find('</think>')
                if idx >= 0:
                    if idx:
                        self._emit_think(self._think_buf[:idx])
                    self._think_buf = self._think_buf[idx + 8:]
                    self._think_state = 'normal'
                    continue
                hold = self._partial_suffix_len(self._think_buf, '</think>')
                if hold:
                    self._emit_think(self._think_buf[:-hold])
                    self._think_buf = self._think_buf[-hold:]
                else:
                    self._emit_think(self._think_buf)
                    self._think_buf = ""
                return

    @staticmethod
    def _partial_suffix_len(buf: str, tag: str) -> int:
        """buf 尾部与 tag 前缀重叠的长度（如 buf 以 '<thi' 结尾对 '<think>' 返回 4）"""
        low = buf.lower()
        for k in range(min(len(tag) - 1, len(low)), 0, -1):
            if low.endswith(tag[:k]):
                return k
        return 0

    def _emit_body(self, text: str):
        if text:
            self.chunk.emit(text)

    def _emit_think(self, text: str):
        if text:
            self._reasoning_full += text
            self.reasoning_chunk.emit(text)

    # ---------------- 带 MCP 工具调用（非流式循环） ----------------
    def _run_with_tools(self, client):
        # OpenAI function name 仅允许 [a-zA-Z0-9_-]，用「服务器__工具名」映射
        name_map: Dict[str, MCPToolInfo] = {}
        openai_tools = []
        for t in self._tools:
            safe_server = re.sub(r'[^a-zA-Z0-9_-]', '_', t.server)
            fn_name = f"{safe_server}__{t.name}"[:64]
            name_map[fn_name] = t
            tool_def = t.to_openai_tool()
            tool_def['function']['name'] = fn_name
            openai_tools.append(tool_def)

        # 技能本地执行工具（read_skill_file / run_skill_script）
        local_tools = set()
        if self._skill_tools is not None:
            for tool_def in self._skill_tools.openai_tools():
                local_tools.add(tool_def['function']['name'])
                openai_tools.append(tool_def)

        msgs = list(self._messages)
        manager = get_mcp_manager()
        answer = ""

        for _ in range(MAX_TOOL_ROUNDS):
            if self._cancelled:
                return
            resp = client.chat.completions.create(
                model=self._model,
                messages=msgs,
                tools=openai_tools,
            )
            msg = resp.choices[0].message
            # 思考模型的思考过程（非流式响应中在 message.reasoning_content）
            rc = getattr(msg, 'reasoning_content', None)
            if rc:
                if not self._reasoning_full:
                    log_info(f'[Chat] reasoning_content 非流式到达 (len={len(rc)})')
                self._reasoning_full += rc
                # 分块 emit 模拟流式思考显示
                for _ri in range(0, len(rc), 30):
                    if self._cancelled:
                        return
                    self.reasoning_chunk.emit(rc[_ri:_ri + 30])
                    time.sleep(0.01)
            tool_calls = getattr(msg, 'tool_calls', None)
            if not tool_calls:
                answer = msg.content or ""
                break

            # 记录 assistant 的 tool_calls
            msgs.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    } for tc in tool_calls
                ],
            })

            # 逐个执行工具
            for tc in tool_calls:
                if self._cancelled:
                    return
                tool_info = name_map.get(tc.function.name)
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except Exception:
                    args = {}
                if tc.function.name in local_tools:
                    self.tool_info.emit(f"调用技能本地工具 {tc.function.name} ...")
                    result = self._skill_tools.call(tc.function.name, args)
                elif not tool_info:
                    result = f"[未知工具 {tc.function.name}]"
                else:
                    self.tool_info.emit(f"调用 MCP 工具 {tool_info.server}/{tool_info.name} ...")
                    try:
                        result = manager.call_tool(tool_info.server, tool_info.name, args)
                    except Exception as e:
                        result = f"[工具调用失败: {e}]"
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result[:20000],
                })
        else:
            answer = answer or "[已达到最大工具调用轮数]"

        if not answer:
            answer = "[模型未返回内容]"
        # 思考内嵌正文的模型（MiniMax 等）：把 <think> 段拆到思考框；
        # 已有 reasoning_content 的模型不重复拆
        if not self._reasoning_full:
            _think_part, _body_part = _split_think_tags(answer)
            if _think_part:
                log_info(f'[Chat] 非流式响应拆出内嵌思考 (len={len(_think_part)})')
                self._reasoning_full = _think_part
                for _ri in range(0, len(_think_part), 30):
                    if self._cancelled:
                        return
                    self.reasoning_chunk.emit(_think_part[_ri:_ri + 30])
                    time.sleep(0.01)
                answer = _body_part or "[模型未返回正文]"
        # 非流式路径：分块 emit 模拟流式显示（API 已一次性返回，
        # 逐块呈现避免整段瞬间弹出的突兀感）
        for _ri in range(0, len(answer), 20):
            if self._cancelled:
                return
            self.chunk.emit(answer[_ri:_ri + 20])
            time.sleep(0.015)
        self.finished_ok.emit(answer, self._reasoning_full)


class SessionItemDelegate(QStyledItemDelegate):
    """会话条目绘制：QSS 负责底色/边框/文字，这里只在条目右侧叠加垃圾桶删除图标（垂直居中）"""

    #: 垃圾桶图标 + 两侧留白的总占位宽度（_reload_session_list 计算标题省略宽度时同步使用）
    DELETE_ZONE_WIDTH = 26

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        # QPalette.text 是方法（返回 QBrush），必须 text() 调用，
        # 直接 .text 拿到的是绑定方法对象，运行期 AttributeError 崩溃
        color = QColor(option.palette.text().color())
        # 条目底色较深时（选中态等）跟随文字色，保证图标可见
        r = option.rect
        icon_w = 14
        x = r.right() - 8 - icon_w
        y = r.top() + max(0, (r.height() - 16) // 2)  # 垂直居中
        pixmap = ChatWindow._create_trash_icon(color)
        painter.drawPixmap(x, y, 14, 14, pixmap)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 44))
        return size


class StayOpenMenu(QMenu):
    """勾选类条目点击后菜单留在原地不收起，方便连续切换多个工具。

    Qt 菜单默认触发任何条目即关闭，且没有开关可留；这里拦截
    勾选条目（checkable）的鼠标/回车激活：手动翻转勾选态、不下传基类，
    菜单便不会收起。普通条目仍按常规行为点击后关闭。
    """

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            act = self.actionAt(event.position().toPoint())
            if act is not None and act.isEnabled() and act.isCheckable():
                act.toggle()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            act = self.activeAction()
            if act is not None and act.isEnabled() and act.isCheckable():
                act.toggle()
                return
        super().keyPressEvent(event)


class _ReserveWidget(QWidget):
    """流式思考增长占位：高度 = max(0, 上限 - 思考框当前高度)。
    sizeHint 直接引用思考框高度，与思考框在同一遍布局中定稿"""

    def __init__(self, scroll, cap: int, parent=None):
        super().__init__(parent)
        self._rs = scroll
        self._cap = cap
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(1, max(0, self._cap - self._rs.minimumHeight()))

    def heightForWidth(self, w):
        return self.sizeHint().height()


class _BubbleRow(QWidget):
    """消息气泡行：悬停时在右上角显示回退按钮（悬浮定位，不入布局，
    不影响气泡宽度度量）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_btn: Optional[QPushButton] = None

    def set_hover_button(self, btn: QPushButton):
        self._hover_btn = btn
        btn.setParent(self)
        btn.hide()
        self._layout_btn()

    def _layout_btn(self):
        if self._hover_btn is not None:
            self._hover_btn.move(
                max(self.width() - self._hover_btn.width() - 5, 0),
                max(self.height() - self._hover_btn.height() - 2, 0))
            self._hover_btn.raise_()

    def enterEvent(self, event):
        if self._hover_btn is not None:
            self._hover_btn.show()
            self._layout_btn()
        super().enterEvent(event)

    def leaveEvent(self, event):
        # 移入子控件（气泡文字/按钮）同样触发 leave：
        # 光标真正离开本行区域才隐藏
        if self._hover_btn is not None and self._hover_btn.isVisible():
            if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
                self._hover_btn.hide()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        self._layout_btn()
        super().resizeEvent(event)


class _SmoothWheelScroll(QScrollArea):
    """滚轮平滑滚动：滚轮输入累加为目标偏移，QTimeLine 逐帧缓动推进
    （OutQuad），替代默认阶梯式 singleStep 跳变。动画中再滚轮则从
    当前值重定目标续接，手感连贯。程序化跳底前须先 stopSmooth()，
    否则动画残留会把滚动值拉回旧目标。"""

    # 滚轮速度旋钮（子类可覆写）：单次滚轮输入的距离倍率、动画时长夹取区间
    _wheel_step = 1.0
    _wheel_dur = (120, 260)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._smooth_tl = None   # 滚动动画 QTimeLine
        self._smooth_target = 0  # 累加的滚动目标值

    def stopSmooth(self):
        if self._smooth_tl is not None:
            self._smooth_tl.stop()
            self._smooth_tl = None

    def smoothWheel(self, delta: int):
        bar = self.verticalScrollBar()
        # 触摸板 pixelDelta 细粒度小步累加；鼠标滚轮一格 ±120
        step = int(round(-delta * self._wheel_step))
        base = self._smooth_target \
            if self._smooth_tl is not None else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), base + step))
        if target == bar.value():
            self.stopSmooth()
            return
        self._smooth_target = target
        if self._smooth_tl is not None:
            self._smooth_tl.stop()
        # 时长随距离伸缩：短程迅捷、长程不拖沓；16ms 更新节拍
        # （QTimeLine 默认 33ms 仅约 30 帧/秒，减半后贴齐显示刷新率）
        dist = abs(target - bar.value())
        dur = max(self._wheel_dur[0], min(self._wheel_dur[1], dist * 3 // 2))
        tl = QTimeLine(dur, self)
        tl.setUpdateInterval(16)
        tl.setFrameRange(bar.value(), target)
        tl.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutQuad))
        tl.frameChanged.connect(bar.setValue)
        tl.finished.connect(self._on_smooth_done)
        self._smooth_tl = tl
        tl.start()

    def _on_smooth_done(self):
        self._smooth_tl = None


class _ReasoningScroll(_SmoothWheelScroll):
    """思考框滚动区：流式瞬时长高（平滑动画读起来像「新行滑动」，已停用）"""

    # 滚轮节奏比主消息区慢：内容短、行距密，快了容易滚过头
    _wheel_step = 0.6
    _wheel_dur = (150, 320)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 框高始终由 min==max 钳定（折叠/动画均为固定值），垂直方向必须
        # 声明 Fixed：默认 Expanding 会沿 expandingDirections 一路上传染到行
        # 布局，消息区剩余空间会被分进本行、沉淀到思考块标题行，「思考过程」
        # 被垂直拉伸居中而悬空（内容越短越明显，首条消息必现）
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self._grow_anim = None  # QTimeLine 增长动画（见 animateToHeight）
        self._animate_grow = False  # 长高动画开关（恒 False：动画读起来像新行滑动）
        self._reserve_w = None  # 引用本框高度的流式占位 widget

    def wheelEvent(self, ev):
        """滚轮到边界即停：内容滚到底/顶后吞掉滚轮事件，不再外传给
        主消息区（默认行为会继续滚动外层界面，阅读思考内容时易误触）。
        内容不足 5 行（无滚动余量）时不拦截，照常传给外层。"""
        bar = self.verticalScrollBar()
        if bar.maximum() > bar.minimum():
            delta = ev.pixelDelta().y() if not ev.pixelDelta().isNull() \
                else ev.angleDelta().y()
            if (delta < 0 and bar.value() >= bar.maximum()) or \
                    (delta > 0 and bar.value() <= bar.minimum()):
                ev.accept()
                return
            if delta != 0:
                self.smoothWheel(delta)
                ev.accept()
                return
        super().wheelEvent(ev)

    def applyHeight(self, h):
        """设置固定高度；同时使引用本框高度的占位重新度量。
        占位的 sizeHint 直接引用框高，两者在同一遍布局中一起定稿，
        容器总高严格恒定（避免两次布局间的中间态引起滚动 range 抖动）"""
        if self.minimumHeight() != h or self.maximumHeight() != h:
            self.setFixedHeight(h)
            if self._reserve_w is not None:
                self._reserve_w.updateGeometry()

    def animateToHeight(self, target: int):
        """从当前高度平滑过渡到 target；动画中再次调用则重定目标续接。
        不用 QPropertyAnimation：其帧更新在上一帧布局定稿前触发，直接设高
        会带着旧占位高度先做一轮布局（总高瞬间 ±数像素、标题一帧抖动）。
        改用 0ms 定时器逐帧推进：posted timer 先于动画 update 事件触发，
        框高与占位高在同一事件内同步设置，布局生效时两者皆为新值"""
        cur = self.minimumHeight()
        if target == cur:
            return
        if self._grow_anim is not None:
            self._grow_anim.stop()
        # 时长随增幅伸缩：约 6ms/px，夹在 80~220ms，逐行增长时衔接连贯
        dur = max(80, min(220, abs(target - cur) * 6))
        tl = QTimeLine(dur, self)
        tl.setFrameRange(cur, target)
        tl.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutQuad))
        tl.frameChanged.connect(self.applyHeight)
        tl.finished.connect(lambda: self.applyHeight(target))
        self._grow_anim = tl
        tl.start()


class ChatWindow(QWidget):
    """AI 对话独立窗口"""

    closed = pyqtSignal()
    # MCP 连接状态事件（后台线程经此信号转发回主线程刷新菜单）
    _mcp_status_sig = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("ChatWindow")
        self.setWindowTitle(f"{APP_NAME} - AI 对话")

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        # 用时置顶、切走降级：「始终置顶」设置只控制翻译窗口
        try:
            from ..utils.window_front import install_activation_topmost
        except ImportError:
            from src.utils.window_front import install_activation_topmost
        install_activation_topmost(self)
        # Windows 手势（Win+方向键贴靠/最大化、任务栏最小化），与翻译窗口一致
        self._enable_windows_window_management()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(720, 480)
        self.resize(920, 640)

        self._config = get_config()
        self._store = get_chat_store()
        self._theme = get_theme()

        # 任务栏图标：与翻译窗口保持一致（assets/icon.png）
        self._set_window_icon()

        # MCP 连接状态：「连接中」标记 + 后台事件监听（经 pyqtSignal 切回主线程）
        self._mcp_connecting = False
        self._mcp_status_sig.connect(self._on_mcp_status_event)
        get_mcp_manager().add_status_listener(self._mcp_status_sig.emit)

        # 拖动状态
        self._is_dragging = False
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None

        # 最大化状态（标题栏按钮 / 双击标题栏 / Win+方向键共用）
        self._is_maximized = False
        self._normal_geometry: Optional[QRect] = None

        # 边缘缩放状态（无框窗口拖拽边缘调整大小）
        self._resize_edge = 0
        self._resize_start_pos: Optional[QPoint] = None
        self._resize_start_geo: Optional[QRect] = None

        self._current_session_id: Optional[str] = None
        self._worker: Optional[ChatWorker] = None
        self._trusted_skills: set = set()  # 本会话勾选过「不再询问」的技能
        self._stream_buffer = ""
        self._reasoning_buffer = ""  # 思考模型的流式思考内容缓冲
        self._reason_follow = True  # 思考框折叠时是否跟随到底
        self._main_follow = True  # 主消息区是否自动跟随到底

        self._setup_ui()
        self._apply_theme()
        self._applied_theme_signature = self._theme_signature()

        # 气泡最大宽在渲染时按当时聊天区宽度定死，窗口变宽后防抖重排气泡
        self._last_render_width = 0
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(200)
        self._relayout_timer.timeout.connect(self._relayout_on_resize)
        # 会话条目标题当前截断宽度（_reload_session_list 更新，resize 时对比）
        self._session_list_title_w = 0

        # 流式刷新节流：chunk 先入缓冲，合并后最多约 50 次/秒刷新气泡。
        # singleShot 合并自保：单次刷新耗时变长时后续 chunk 自动合并、
        # 实际频率自然回落，长回复的全量富文本重排不会堆积卡死
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(20)
        self._flush_timer.timeout.connect(self._update_stream_display)

        # 已取消但仍在跑的 worker：保持引用直到结束，防止 QThread 运行中被回收 abort
        self._zombie_workers: List[ChatWorker] = []

        # 鼠标追踪：未按键时也响应移动，及时切换边缘缩放光标
        self.setMouseTracking(True)
        self._content_frame.setMouseTracking(True)
        self._title_bar.setMouseTracking(True)
        self._side_panel.setMouseTracking(True)
        # 子控件占据整个窗口，边缘按下/悬停事件到不了窗口自身，
        # 通过事件过滤器在内容容器及其全部后代上拦截处理。
        # 必须装到每个后代：会话列表/消息视图等控件会自行接受鼠标移动
        # 事件不向上传播，只装在容器上会漏掉它们所在区域（如左边缘）
        self._content_frame.installEventFilter(self)
        for _w in self.findChildren(QWidget):
            if _w is not self._input_edit:
                _w.installEventFilter(self)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._content_frame = QFrame()
        self._content_frame.setObjectName("chatContentFrame")
        outer.addWidget(self._content_frame)

        root = QVBoxLayout(self._content_frame)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 标题栏 ----
        self._title_bar = QFrame()
        self._title_bar.setObjectName("chatTitleBar")
        self._title_bar.setFixedHeight(36)
        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(12, 0, 8, 0)

        self._title_label = QLabel(f"{APP_NAME} · AI 对话")
        self._title_label.setObjectName("chatTitleLabel")
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        # 最小化 / 最大化 / 关闭按钮（与翻译窗口完全一致：22x22 圆形 hover）
        self._minimize_btn = QPushButton("─")
        self._minimize_btn.setObjectName("chatMinimizeBtn")
        self._minimize_btn.setFixedSize(22, 22)
        self._minimize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._minimize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._minimize_btn.setToolTip("最小化")
        self._minimize_btn.clicked.connect(self._on_minimize_clicked)
        title_layout.addWidget(self._minimize_btn)

        self._maximize_btn = QPushButton("□")
        self._maximize_btn.setObjectName("chatMaximizeBtn")
        self._maximize_btn.setFixedSize(22, 22)
        self._maximize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._maximize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._maximize_btn.setToolTip("最大化 / 还原")
        self._maximize_btn.clicked.connect(self._toggle_maximize)
        title_layout.addWidget(self._maximize_btn)

        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("chatCloseBtn")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close_btn.clicked.connect(self._on_close_clicked)
        title_layout.addWidget(self._close_btn)
        root.addWidget(self._title_bar)

        # ---- 主体：左侧会话列表 + 右侧对话区（分割线可左右拖动） ----
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("chatSplitter")
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(6)
        self._splitter.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # 左侧（独立侧边栏容器，单独底色）
        self._side_panel = QFrame()
        self._side_panel.setObjectName("chatSidePanel")
        self._side_panel.setMinimumWidth(160)
        side = QVBoxLayout(self._side_panel)
        side.setContentsMargins(10, 10, 8, 10)
        side.setSpacing(8)

        self._new_session_btn = QPushButton("＋ 新建对话")
        self._new_session_btn.setObjectName("newSessionBtn")
        self._new_session_btn.setMinimumHeight(36)
        self._new_session_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._new_session_btn.clicked.connect(self._on_new_session)
        side.addWidget(self._new_session_btn)

        self._session_list = QListWidget()
        self._session_list.setObjectName("sessionList")
        self._session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._session_list.customContextMenuRequested.connect(self._on_session_context_menu)
        self._session_list.itemClicked.connect(self._on_session_item_clicked)
        # 垃圾桶删除按钮等条目装饰由委托绘制（文字/边框仍走 QSS）
        self._session_list.setItemDelegate(SessionItemDelegate(self._session_list))
        side.addWidget(self._session_list, 1)

        self._splitter.addWidget(self._side_panel)

        # 右侧容器
        right_widget = QWidget()
        right_widget.setObjectName("chatRightPanel")
        right_widget.setMinimumWidth(380)
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(12, 10, 12, 12)
        right.setSpacing(10)

        # 右侧顶栏：技能 + MCP
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self._skill_label = QLabel("技能:")
        self._skill_combo = QToolButton()
        self._skill_combo.setObjectName("skillBtn")
        self._skill_combo.setText("无技能")
        self._skill_combo.setMinimumHeight(28)
        self._skill_combo.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._skill_combo.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._skill_menu = QMenu(self._skill_combo)
        self._skill_combo.setMenu(self._skill_menu)
        top_bar.addWidget(self._skill_label)
        top_bar.addWidget(self._skill_combo)

        top_bar.addStretch()

        self._mcp_btn = QToolButton()
        self._mcp_btn.setObjectName("mcpBtn")
        self._mcp_btn.setText("MCP")
        self._mcp_btn.setMinimumHeight(28)
        self._mcp_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._mcp_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._mcp_menu = StayOpenMenu(self._mcp_btn)
        self._mcp_btn.setMenu(self._mcp_menu)
        top_bar.addWidget(self._mcp_btn)

        self._clear_ctx_btn = QPushButton("清空上下文")
        self._clear_ctx_btn.setObjectName("clearCtxBtn")
        self._clear_ctx_btn.setMinimumHeight(28)
        self._clear_ctx_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._clear_ctx_btn.clicked.connect(self._on_clear_context)
        top_bar.addWidget(self._clear_ctx_btn)

        right.addLayout(top_bar)

        # 消息区（控件式气泡：QSS 支持圆角，Qt 富文本不支持 border-radius）
        self._message_scroll = _SmoothWheelScroll()
        self._message_scroll.setObjectName("messageView")
        self._message_scroll.setWidgetResizable(True)
        self._message_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 纵向滚动条常驻：AsNeeded 会在流式内容越过视口高度时弹出滚动条、
        # 视口收窄 8px、全部气泡重排（用户感知「整段文字跳一下」，首条
        # 对话必越阈值故易复现）；禁用态由 QSS 设为透明，空闲不可见但
        # 宽度恒定 → 永不重排
        self._message_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._message_container = QWidget()
        self._message_container.setObjectName("messageContainer")
        self._message_layout = QVBoxLayout(self._message_container)
        self._message_layout.setContentsMargins(4, 10, 10, 10)
        self._message_layout.setSpacing(10)
        self._message_scroll.setWidget(self._message_container)
        _mbar = self._message_scroll.verticalScrollBar()
        _mbar.rangeChanged.connect(self._on_main_range_changed)
        _mbar.valueChanged.connect(self._on_main_scroll_moved)
        self._stream_label: Optional[QLabel] = None  # 流式输出中的气泡正文
        self._stream_reason_label: Optional[QLabel] = None  # 流式思考块内容
        self._stream_reason_scroll: Optional[QScrollArea] = None
        self._stream_row: Optional[QWidget] = None  # 流式输出所在的行容器
        self._stream_reserve = None  # (占位 spacer, 5行上限高)：思考增长补偿
        right.addWidget(self._message_scroll, 1)

        # 输入区
        input_bar = QHBoxLayout()
        input_bar.setSpacing(6)
        self._input_edit = QPlainTextEdit()
        self._input_edit.setObjectName("chatInput")
        self._input_edit.setPlaceholderText("输入消息，Enter 发送，Shift+Enter 换行")
        self._input_edit.setFixedHeight(64)
        self._input_edit.installEventFilter(self)
        input_bar.addWidget(self._input_edit, 1)

        self._send_btn = QPushButton("发送")
        self._send_btn.setObjectName("sendBtn")
        self._send_btn.setFixedSize(76, 64)
        self._send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._send_btn.clicked.connect(lambda: self.send_message())
        input_bar.addWidget(self._send_btn)
        right.addLayout(input_bar)

        self._splitter.addWidget(right_widget)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([220, 700])
        # 拖动分割条改变侧栏宽度时，按新宽度重排会话条目标题省略
        self._splitter.splitterMoved.connect(self._on_splitter_moved)
        root.addWidget(self._splitter, 1)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def _theme_signature(self):
        """影响样式的主题签名（主题名 + 自定义色 + 字号）"""
        return (
            self._config.get('theme.popup_style', 'dark'),
            self._config.get('theme.custom_accent', '#007AFF'),
            self._config.get('theme.custom_bg', '#2d2d2d'),
            self._config.get('font.size', 15),
        )

    def _apply_theme(self):
        self._theme = get_theme(self._config.get('theme.popup_style', 'dark'))
        t = self._theme
        bg = t['bg_color']
        bg2 = t['bg_secondary']
        border = t['border_color']
        text1 = t['text_primary']
        text2 = t['text_secondary']
        accent = t['accent_color']
        accent_hover = t['accent_hover']
        font_size = self._config.get('font.size', 15)
        # 思考气泡底色：主题色浅调（约 10% 不透明），与正文气泡区分
        self._reasoning_tint = _hex_to_rgba(accent, 26)

        self._content_frame.setStyleSheet(f"""
            #chatContentFrame {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
        """)
        self._title_bar.setStyleSheet(f"""
            #chatTitleBar {{ background-color: {bg2}; border-top-left-radius: 10px; border-top-right-radius: 10px; }}
            #chatTitleLabel {{ color: {text1}; font-size: 13px; font-weight: 600; background: transparent; }}
            #chatMinimizeBtn {{
                background-color: transparent; color: {t['text_muted']}; border: none;
                border-radius: 11px; font-size: 10px; font-weight: bold;
            }}
            #chatMinimizeBtn:hover {{
                background-color: {t['button_hover']}; color: {text1};
            }}
            #chatMaximizeBtn {{
                background-color: transparent; color: {t['text_muted']}; border: none;
                border-radius: 11px; font-size: 12px; font-weight: bold;
                padding-bottom: 2px;
            }}
            #chatMaximizeBtn:hover {{
                background-color: {t['button_hover']}; color: {text1};
            }}
            #chatCloseBtn {{
                background-color: transparent; color: {t['text_muted']}; border: none;
                border-radius: 11px; font-size: 14px; font-weight: bold;
                padding-bottom: 1px;
            }}
            #chatCloseBtn:hover {{
                background-color: {t['close_hover']}; color: #ffffff;
            }}
        """)
        self._side_panel.setStyleSheet(f"""
            #chatSidePanel {{
                background-color: {bg2};
                border-bottom-left-radius: 10px;
            }}
        """)
        self._splitter.setStyleSheet(f"""
            #chatSplitter::handle {{ background-color: {bg}; }}
            #chatSplitter::handle:hover {{ background-color: {accent}; }}
            #chatSplitter::handle:pressed {{ background-color: {accent_hover}; }}
        """)
        # 条目透明底：文字色按侧栏背景亮度自动选黑/白，避免深色底黑字看不清
        item_text = getattr(self, '_session_item_text_color', None) or self._contrast_color(bg2)
        self._session_list.setStyleSheet(f"""
            #sessionList {{
                background-color: transparent; border: none; color: {item_text};
                font-size: {max(font_size - 2, 12)}px; outline: none;
            }}
            #sessionList::item {{
                padding: 8px 10px; border-radius: 8px; margin: 1px 2px;
                color: {item_text};
            }}
            #sessionList::item:selected {{ background-color: transparent; color: {item_text}; border: 1px solid {text2}; }}
            #sessionList::item:hover:!selected {{ border: 1px solid {border}; }}
            #sessionList QScrollBar:vertical {{
                background: transparent; width: 6px; margin: 2px;
            }}
            #sessionList QScrollBar::handle:vertical {{
                background: {border}; border-radius: 3px; min-height: 24px;
            }}
            #sessionList QScrollBar::handle:vertical:hover {{ background: {text2}; }}
            #sessionList QScrollBar::add-line:vertical, #sessionList QScrollBar::sub-line:vertical {{ height: 0; }}
            #sessionList QScrollBar::add-page:vertical, #sessionList QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)
        self._new_session_btn.setStyleSheet(f"""
            #newSessionBtn {{
                background-color: {accent}; color: #ffffff; border: none;
                border-radius: 8px; font-size: 13px; font-weight: 600;
            }}
            #newSessionBtn:hover {{ background-color: {accent_hover}; }}
            #newSessionBtn:pressed {{ background-color: {accent_hover}; }}
        """)
        self._skill_combo.setStyleSheet(f"""
            #skillBtn {{
                background-color: {bg2}; color: {text1};
                border: 1px solid {border}; border-radius: 14px;
                padding: 3px 12px; font-size: 12px;
            }}
            #skillBtn:hover {{ border-color: {accent}; color: {accent}; }}
            #skillBtn::menu-indicator {{ image: none; }}
        """)
        self._mcp_btn.setStyleSheet(f"""
            #mcpBtn {{
                background-color: {bg2}; color: {text1};
                border: 1px solid {border}; border-radius: 14px;
                padding: 3px 12px; font-size: 12px;
            }}
            #mcpBtn:hover {{ border-color: {accent}; color: {accent}; }}
            #mcpBtn::menu-indicator {{ image: none; }}
        """)
        self._clear_ctx_btn.setStyleSheet(f"""
            #clearCtxBtn {{
                background-color: transparent; color: {text2};
                border: 1px solid {border}; border-radius: 14px;
                padding: 3px 12px; font-size: 12px;
            }}
            #clearCtxBtn:hover {{ color: {text1}; border-color: {accent}; }}
        """)
        self._message_scroll.setStyleSheet(f"""
            #messageView {{
                background-color: {bg}; border: none;
            }}
            #messageContainer {{ background: transparent; }}
            #messageView QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 2px;
            }}
            #messageView QScrollBar::handle:vertical {{
                background: {border}; border-radius: 4px; min-height: 30px;
            }}
            #messageView QScrollBar::handle:vertical:hover {{ background: {text2}; }}
            #messageView QScrollBar::add-line:vertical, #messageView QScrollBar::sub-line:vertical {{ height: 0; }}
            #messageView QScrollBar::add-page:vertical, #messageView QScrollBar::sub-page:vertical {{ background: transparent; }}
            #messageView QScrollBar:vertical:disabled {{ background: transparent; }}
            #messageView QScrollBar::handle:vertical:disabled {{ background: transparent; }}
            #bubbleUser {{
                background-color: {accent}; color: #ffffff;
                border-radius: 12px; padding: 8px 12px;
                font-size: {font_size}px;
            }}
            #bubbleAssistant {{
                background-color: {bg2}; color: {text1};
                border: 1px solid {border};
                border-radius: 12px; padding: 8px 12px;
                font-size: {font_size}px;
            }}
            #bubbleUser pre, #bubbleAssistant pre {{
                background-color: {border}; padding: 6px;
                font-family: Consolas, monospace;
            }}
            #bubbleAssistant QLabel {{ background: transparent; }}
            #bubbleReasoning {{
                background-color: {self._reasoning_tint};
                border: 1px dashed {border};
                border-radius: 12px;
            }}
            #bubbleReasoning QLabel {{ background: transparent; }}
            #bubbleContentText {{ color: {text1}; font-size: {font_size}px; }}
            #reasoningTitle {{
                color: {text2}; font-size: 12px; background: transparent;
            }}
            #reasoningContent {{
                color: {text2}; background: transparent;
                font-size: {max(font_size - 1, 12)}px;
            }}
            #reasoningScroll {{ background: transparent; border: none; }}
            #reasoningScroll QScrollBar:vertical {{
                background: transparent; width: 6px; margin: 1px;
            }}
            #reasoningScroll QScrollBar::handle:vertical {{
                background: {border}; border-radius: 3px; min-height: 20px;
            }}
            #reasoningScroll QScrollBar::handle:vertical:hover {{ background: {text2}; }}
            #reasoningScroll QScrollBar::add-line:vertical, #reasoningScroll QScrollBar::sub-line:vertical {{ height: 0; }}
            #reasoningScroll QScrollBar::add-page:vertical, #reasoningScroll QScrollBar::sub-page:vertical {{ background: transparent; }}
            #emptyHint {{
                color: {text2}; font-size: 13px; background: transparent;
            }}
            #emptyTitle {{
                color: {text1}; font-size: 20px; font-weight: 700; background: transparent;
            }}
        """)
        self._input_edit.setStyleSheet(f"""
            #chatInput {{
                background: {bg2}; color: {text1};
                border: 1px solid {border}; border-radius: 12px;
                padding: 8px 10px; font-size: {font_size}px;
                selection-background-color: {accent}; selection-color: #ffffff;
            }}
            #chatInput:focus {{ border: 2px solid {accent}; padding: 7px 9px; }}
            #chatInput QScrollBar:vertical {{
                background: transparent; width: 6px; margin: 2px;
            }}
            #chatInput QScrollBar::handle:vertical {{
                background: {border}; border-radius: 3px; min-height: 20px;
            }}
            #chatInput QScrollBar::add-line:vertical, #chatInput QScrollBar::sub-line:vertical {{ height: 0; }}
            #chatInput QScrollBar::add-page:vertical, #chatInput QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)
        self._send_btn.setStyleSheet(f"""
            #sendBtn {{
                background-color: {accent}; color: #ffffff; border: none;
                border-radius: 12px; font-size: 14px; font-weight: 600;
            }}
            #sendBtn:hover {{ background-color: {accent_hover}; }}
            #sendBtn:pressed {{ background-color: {accent_hover}; }}
            #sendBtn:disabled {{ background-color: {border}; color: {text2}; }}
        """)
        self._skill_label.setStyleSheet(f"color: {text2}; font-size: 12px; background: transparent;")

        # 侧栏背景亮度决定的条目文字色（供渲染委托的垃圾桶图标跟随）
        self._session_item_text_color = self._contrast_color(bg2)

    @staticmethod
    def _contrast_color(bg_hex: str) -> str:
        """按背景色 BT.601 亮度自动选对比文字色：深色背景白字、浅色背景黑字"""
        fallback_bg = '#2d2d2d'
        try:
            c = QColor(bg_hex)
            if not c.isValid():
                c = QColor(fallback_bg)
        except Exception:
            c = QColor(fallback_bg)
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        return '#ffffff' if lum < 140 else '#1f1f1f'

    @staticmethod
    def _create_trash_icon(color: QColor):
        """绘制垃圾桶删除图标（桶盖 + 桶身 + 内部纹理），仿翻译窗口 _create_copy_icon 风格"""
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtCore import QPointF
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color, 1.3, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        def line(x1, y1, x2, y2):
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # 提手
        line(6.5, 2.5, 9.5, 2.5)
        # 桶盖
        line(3.5, 4.5, 12.5, 4.5)
        # 桶身（上宽下窄收口）
        line(4.8, 4.5, 5.6, 13.0)
        line(11.2, 4.5, 10.4, 13.0)
        line(5.6, 13.0, 10.4, 13.0)
        # 内部纹理
        line(7.0, 7.0, 7.0, 11.0)
        line(9.0, 7.0, 9.0, 11.0)
        painter.end()
        return pixmap

    def _set_window_icon(self):
        """设置窗口图标（任务栏图标），Win32 API 兜底确保打包后可用"""
        import sys
        # 解析资源路径（兼容打包环境）
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent.parent
        icon_png = base / "assets" / "icon.png"
        icon_ico = base / "assets" / "icon.ico"
        # Qt 层设置（开发模式通常够用）
        if icon_png.exists():
            from PyQt6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(icon_png)))
        # Win32 API 兜底：直接加载 ICO 并设置 WM_SETICON
        try:
            import ctypes
            hwnd = int(self.winId())
            LR_LOADFROMFILE = 0x0010
            IMAGE_ICON = 1
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            hicon = None
            # 优先加载 ICO（包含多尺寸，任务栏效果最好）
            if icon_ico.exists():
                hicon = ctypes.windll.user32.LoadImageW(
                    None, str(icon_ico), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            # 回退到 PNG
            if not hicon and icon_png.exists():
                hicon = ctypes.windll.user32.LoadImageW(
                    None, str(icon_png), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
        except Exception:
            pass


    # ------------------------------------------------------------------
    # 窗口显示 / 拖动
    # ------------------------------------------------------------------
    def show_window(self):
        # 主题/字号变更后重新应用样式（跟随设置）
        sig = self._theme_signature()
        if sig != self._applied_theme_signature:
            self._apply_theme()
            self._applied_theme_signature = sig
        self._refresh_skills()
        self._refresh_mcp_menu()
        if self.isMinimized():
            # 从最小化唤醒：先还原，否则窗口仍缩在任务栏
            self.showNormal()
        self.show()
        # show() 之后侧栏视口宽度才真实：按实际宽度省略会话标题。
        # show 前刷新用的是退化宽度，长标题会先被重度截断、随后防抖
        # relayout 再按真实宽度重刷（肉眼可见「截断后恢复」）；
        # 选中同步（_ensure_session）也依赖列表先就绪
        self._reload_session_list()
        # 首次打开：show() 之后布局才有真实视口宽度，此时再渲染消息，
        # 气泡直接按正确宽度定稿；在 show 前渲染会按退化宽度排版，
        # 随后 resize 防抖再重排 → 首次进入消息区肉眼可见「调整一下」
        if self._current_session_id is None:
            self._ensure_session()
        # 唤醒时刻短暂置前一次（「始终置顶」设置只控制翻译窗口）
        try:
            from ..utils.window_front import bring_to_front_once
        except ImportError:
            from src.utils.window_front import bring_to_front_once
        bring_to_front_once(self)

    def show_with_text(self, text: str, skill: str = ""):
        """从划词工具栏唤起：预填选中文本，可选激活指定技能"""
        self.show_window()
        if skill:
            self._activate_skill(skill)
        if text:
            self._input_edit.setPlainText(text.strip())
            self._input_edit.setFocus()

    def append_action_result(self, action_name: str, selected_text: str, result: str):
        """自定义工具栏功能的执行结果展示在对话窗口中"""
        self.show_window()
        sid = self._current_session_id
        if not sid:
            return
        quote = selected_text.strip()
        if len(quote) > 200:
            quote = quote[:200] + "…"
        self._store.append_message(sid, 'user', f"[自定义功能: {action_name}]\n{quote}")
        self._store.append_message(sid, 'assistant', result or "（已执行，无返回内容）")
        self._render_messages()

    def _on_minimize_clicked(self):
        self.showMinimized()

    def _toggle_maximize(self):
        """最大化/还原：标题栏按钮与双击标题栏共用（行为同翻译窗口）"""
        if self._is_maximized:
            if self._normal_geometry:
                self.setGeometry(self._normal_geometry)
            else:
                self.showNormal()
            self._is_maximized = False
            self._maximize_btn.setText("□")
        else:
            self._normal_geometry = self.geometry()
            screen = QApplication.screenAt(self.geometry().center())
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen:
                self.setGeometry(screen.availableGeometry())
                self._is_maximized = True
                self._maximize_btn.setText("❐")

    def _enable_windows_window_management(self):
        """Windows 上启用 Win+方向键贴靠/最大化与任务栏最小化（同翻译窗口）"""
        try:
            if not sys.platform.startswith("win"):
                return
            import ctypes
            hwnd = int(self.winId())
            GWL_STYLE = -16
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            # WS_THICKFRAME/WS_MAXIMIZEBOX 让 Windows 识别该无边框窗口
            # 可贴靠/最大化，因而支持 Win+方向键等系统窗口管理快捷键
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            new_style = style | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
            # 通知 Windows 重新计算非客户区样式，否则快捷键可能不立即生效
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020)  # NOMOVE|NOSIZE|NOZORDER|NOACTIVATE|FRAMECHANGED
        except Exception:
            pass

    def _on_close_clicked(self):
        self.hide()
        self.closed.emit()

    def closeEvent(self, event):
        """点系统关闭也仅隐藏，保留会话状态"""
        event.ignore()
        self.hide()
        self.closed.emit()

    def leaveEvent(self, event):
        """鼠标离开窗口时恢复默认光标（同翻译窗口）"""
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)

    def hideEvent(self, event):
        """窗口隐藏时清理拖拽/缩放状态与残留鼠标抓取，避免全应用输入被锁"""
        self._is_dragging = False
        self._resize_edge = 0
        self._resize_start_geo = None
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.releaseMouse()
        super().hideEvent(event)

    def changeEvent(self, event):
        """Win+方向键等系统快捷键触发的窗口状态变化：同步最大化标记与按钮图标"""
        if event.type() == QEvent.Type.WindowStateChange:
            state = self.windowState()
            if state & Qt.WindowState.WindowMaximized:
                self._is_maximized = True
                self._maximize_btn.setText("❐")
            elif self._is_maximized and state == Qt.WindowState.WindowNoState:
                self._is_maximized = False
                self._maximize_btn.setText("□")
        super().changeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 尺寸变化停止后（拖拽边缘/最大化）再重排，避免频繁重建气泡
        self._relayout_timer.start()

    def _relayout_on_resize(self):
        """窗口尺寸稳定后按新聊天区宽度重排气泡"""
        # 窗口 resize 会压缩/拉伸侧栏但不触发 splitterMoved，
        # 截断宽度需按新的列表宽度重算，否则窄窗下条目右侧被截
        sl_w = self._session_list.viewport().width()
        new_title_w = max(sl_w - SessionItemDelegate.DELETE_ZONE_WIDTH - 16, 48)
        if sl_w > 50 and new_title_w != self._session_list_title_w:
            self._reload_session_list()
        vp_w = self._message_scroll.viewport().width()
        if vp_w < 50:
            return  # 最小化等退化尺寸不处理
        m = self._message_layout.contentsMargins()
        usable = max(vp_w - m.left() - m.right(), 200)
        if usable == self._last_render_width:
            return
        if self._worker and self._worker.isRunning():
            return  # 流式输出中不打断，结束后会重渲染
        self._render_messages()

    # ------------------------------------------------------------------
    # 窗口拖动 / 边缘缩放
    # ------------------------------------------------------------------
    _EDGE_LEFT, _EDGE_RIGHT, _EDGE_TOP, _EDGE_BOTTOM = 1, 2, 4, 8
    _RESIZE_BORDER = 15  # 边缘命中区域（像素，与翻译窗口一致）

    def _edge_at(self, pos) -> int:
        """返回鼠标位置命中的边缘位组合（可为角）"""
        r = self.rect()
        b = self._RESIZE_BORDER
        edge = 0
        if pos.x() <= r.left() + b:
            edge |= self._EDGE_LEFT
        elif pos.x() >= r.right() - b:
            edge |= self._EDGE_RIGHT
        if pos.y() <= r.top() + b:
            edge |= self._EDGE_TOP
        elif pos.y() >= r.bottom() - b:
            edge |= self._EDGE_BOTTOM
        return edge

    def _resize_cursor(self, edge: int):
        L, R, T, B = self._EDGE_LEFT, self._EDGE_RIGHT, self._EDGE_TOP, self._EDGE_BOTTOM
        if edge in (L, R):
            return Qt.CursorShape.SizeHorCursor
        if edge in (T, B):
            return Qt.CursorShape.SizeVerCursor
        if edge in (L | T, R | B):
            return Qt.CursorShape.SizeFDiagCursor
        if edge in (R | T, L | B):
            return Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.ArrowCursor

    def _interactive_child_at(self, pos) -> bool:
        """窗口坐标 pos 下是否为交互控件（可选文本气泡 / 列表 / 滚动区 / 按钮 / 输入框）。
        这类控件上的按下交给控件自己处理，不拦截成边缘缩放，
        否则贴边的会话列表条目、气泡内边距等会被误拦成窗口缩放"""
        w = self._content_frame.childAt(pos)
        while w is not None and w is not self._content_frame:
            if isinstance(w, (QAbstractScrollArea, QAbstractButton)):
                return True
            if isinstance(w, QLabel) and (
                w.textInteractionFlags()
                & Qt.TextInteractionFlag.TextSelectableByMouse
            ):
                return True
            w = w.parentWidget()
        return False

    def _do_resize(self, gpos: QPoint):
        """根据拖动位移重算窗口几何（不小于最小尺寸）"""
        start = self._resize_start_geo
        geo = QRect(start)
        dx = gpos.x() - self._resize_start_pos.x()
        dy = gpos.y() - self._resize_start_pos.y()
        min_w, min_h = self.minimumWidth(), self.minimumHeight()

        if self._resize_edge & self._EDGE_RIGHT:
            geo.setWidth(max(min_w, start.width() + dx))
        if self._resize_edge & self._EDGE_BOTTOM:
            geo.setHeight(max(min_h, start.height() + dy))
        if self._resize_edge & self._EDGE_LEFT:
            new_w = max(min_w, start.width() - dx)
            geo.setRect(start.right() - new_w + 1, geo.y(), new_w, geo.height())
        if self._resize_edge & self._EDGE_TOP:
            new_h = max(min_h, start.height() - dy)
            geo.setRect(geo.x(), start.bottom() - new_h + 1, geo.width(), new_h)
        self.setGeometry(geo)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            edge = self._edge_at(pos)
            if edge and not self._is_maximized:
                # 边缘/角落：进入缩放模式（最大化时不可缩放）
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = self.geometry()
                self.setCursor(self._resize_cursor(edge))
                self.grabMouse()  # 拖出窗口外仍能收到移动与释放
            elif not self._is_maximized and self._title_bar.geometry().contains(pos):
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_window_start_pos = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        gpos = event.globalPosition().toPoint()
        if self._resize_edge and self._resize_start_geo is not None:
            self._do_resize(gpos)
        elif self._is_dragging and self._drag_start_pos:
            delta = gpos - self._drag_start_pos
            self.move(self._drag_window_start_pos + delta)
        elif event.buttons() == Qt.MouseButton.NoButton:
            # 悬停时切换边缘光标（最大化状态无边缘缩放）
            if self._is_maximized:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            else:
                self.setCursor(self._resize_cursor(self._edge_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        was_moving = self._is_dragging or bool(self._resize_edge)
        self._is_dragging = False
        self._resize_edge = 0
        self._resize_start_geo = None
        if was_moving and (self._stream_buffer or self._reasoning_buffer):
            # 拖动期间暂停的流式刷新，松手后一次性补上
            self._schedule_flush()
        # 必须与 grabMouse 配对：Qt 显式抓取不会在松手时自动解除，
        # 漏掉 releaseMouse 会让本窗口永久窃取全应用鼠标输入（所有按钮点不了）
        self.releaseMouse()
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """双击标题栏切换最大化/还原（同翻译窗口）"""
        if event.button() == Qt.MouseButton.LeftButton and \
                self._title_bar.geometry().contains(event.position().toPoint()):
            self._toggle_maximize()
            return
        super().mouseDoubleClickEvent(event)

    def eventFilter(self, obj, event):
        is_child = (
            isinstance(obj, QWidget)
            and obj is not self._input_edit
            and not isinstance(obj, QSplitterHandle)
            and self._content_frame.isAncestorOf(obj)
        )
        is_hover_target = is_child or obj is self._input_edit

        # 子控件（内容容器及其后代）上的边缘按下：子控件占满窗口，
        # 不拦截的话边缘按下事件到不了窗口，缩放无法启动
        if (
            is_child
            and not isinstance(obj, (QAbstractButton, QAbstractSlider))
            and event.type() == event.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            pos = self.mapFromGlobal(obj.mapToGlobal(event.position().toPoint()))
            edge = self._edge_at(pos)
            if edge and not self._is_maximized and not self._interactive_child_at(pos):
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = self.geometry()
                self.setCursor(self._resize_cursor(edge))
                self.grabMouse()  # 拖出控件/窗口外仍能收到移动与释放
                return True

        # 悬停同步缩放光标；离开边缘立即还原（行为同翻译窗口）
        if is_hover_target and event.type() == event.Type.MouseMove \
                and not self._resize_edge and not self._is_dragging:
            pos = self.mapFromGlobal(obj.mapToGlobal(event.position().toPoint()))
            edge = self._edge_at(pos)
            if edge and not self._is_maximized:
                cursor = self._resize_cursor(edge)
                self.setCursor(QCursor(cursor))
                obj.setCursor(QCursor(cursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                obj.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        elif is_hover_target and event.type() == event.Type.Leave:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            obj.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        if obj is self._input_edit and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False  # Shift+Enter 换行
                self.send_message()
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------
    def _ensure_session(self):
        sessions = self._store.list_sessions()
        if sessions:
            self._select_session(sessions[0]['id'])
        else:
            self._on_new_session(select=True)

    def _reload_session_list(self):
        current_sid = self._current_session_id
        # 标题按侧栏当前可视宽度省略（预留垃圾桶按钮区与条目内边距），避免条目超宽截断圆角
        list_w = max(self._session_list.viewport().width(), 100)
        title_w = max(list_w - SessionItemDelegate.DELETE_ZONE_WIDTH - 16, 48)
        self._session_list_title_w = title_w
        fm = self._session_list.fontMetrics()
        self._session_list.clear()
        for s in self._store.list_sessions():
            title = (s.get('title') or "新对话").strip() or "新对话"
            elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, title_w)
            try:
                when = datetime.fromtimestamp(s.get('updated_at', 0) / 1000).strftime('%m-%d %H:%M')
            except Exception:
                when = ""
            item = QListWidgetItem(f"{elided}\n{when}")
            item.setData(Qt.ItemDataRole.UserRole, s['id'])
            item.setData(Qt.ItemDataRole.UserRole + 1, title)  # 完整标题（重命名预填用）
            self._session_list.addItem(item)
            if s['id'] == current_sid:
                item.setSelected(True)

    def _on_splitter_moved(self, pos, index):
        """拖动分割条调整侧栏宽度后，按新宽度重排会话条目的标题省略"""
        self._reload_session_list()
        self._relayout_timer.start()

    def _on_new_session(self, select: bool = True):
        session = self._store.create_session()
        self._reload_session_list()
        if select:
            self._select_session(session['id'])

    def _on_session_item_clicked(self, item: QListWidgetItem):
        # 点击条目右侧垃圾桶区域 → 删除（行为同右键菜单删除）；其余区域切换会话
        rect = self._session_list.visualItemRect(item)
        if rect.isValid() and self._session_list.viewport().mapFromGlobal(QCursor.pos()).x() \
                >= rect.right() - SessionItemDelegate.DELETE_ZONE_WIDTH:
            self._delete_session(item.data(Qt.ItemDataRole.UserRole))
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        if sid and sid != self._current_session_id:
            self._select_session(sid)

    def _delete_session(self, sid):
        if not sid:
            return
        self._store.delete_session(sid)
        if sid == self._current_session_id:
            self._current_session_id = None
        self._reload_session_list()
        self._ensure_session()

    def _select_session(self, session_id: str):
        self._cancel_worker()
        self._current_session_id = session_id
        session = self._store.get_session(session_id)
        skill_name = session.get('skill', '') if session else ''
        self._update_skill_button(skill_name)
        # 同步列表选中态
        for i in range(self._session_list.count()):
            item = self._session_list.item(i)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) == session_id)
        self._render_messages()

    def _on_session_context_menu(self, pos):
        item = self._session_list.itemAt(pos)
        if not item:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        rename_act = menu.addAction("重命名")
        delete_act = menu.addAction("删除")
        chosen = menu.exec(self._session_list.mapToGlobal(pos))
        if chosen == rename_act:
            # 预填取存储里的完整标题（item.text() 是省略/含时间的显示文本）
            session = self._store.get_session(sid) or {}
            old_title = (session.get('title') or "新对话").strip() or "新对话"
            new_title, ok = QInputDialog.getText(self, "重命名对话", "新名称:", text=old_title)
            if ok and new_title.strip():
                self._store.rename_session(sid, new_title)
                self._reload_session_list()
        elif chosen == delete_act:
            self._delete_session(sid)

    def _on_clear_context(self):
        if self._current_session_id:
            self._cancel_worker()
            self._store.clear_messages(self._current_session_id)
            # 上下文从零开始：会话名一并重置，滚动摘要同步清空避免残留旧语境
            self._store.rename_session(self._current_session_id, "新对话")
            self._store.set_session_summary(self._current_session_id, "", 0)
            self._reload_session_list()
            self._render_messages()

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def _refresh_skills(self):
        self._skill_menu.clear()
        manager = get_skill_manager()
        skills = manager.load_skills()

        # 技能执行总开关（与 MCP 菜单的"启用 MCP 工具"对应）
        enable_act = self._skill_menu.addAction("启用技能执行")
        enable_act.setCheckable(True)
        enable_act.setChecked(self._config.get('skills.enabled', False))
        enable_act.toggled.connect(self._on_toggle_skills_enabled)
        self._skill_menu.addSeparator()

        none_act = self._skill_menu.addAction("无技能")
        none_act.setCheckable(True)
        current = self._current_skill_name()
        none_act.setChecked(not current)
        none_act.triggered.connect(lambda: self._activate_skill(""))

        if skills:
            self._skill_menu.addSeparator()
        for skill in skills:
            label = skill.name + (f"（{skill.description[:20]}）" if skill.description else "")
            act = self._skill_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(current == skill.name)
            act.triggered.connect(lambda checked=False, n=skill.name: self._activate_skill(n))

        self._skill_menu.addSeparator()
        open_dir_act = self._skill_menu.addAction("打开 skills 目录…")
        open_dir_act.triggered.connect(
            lambda: os.startfile(str(manager.skills_dir))
        )

    def _current_skill_name(self) -> str:
        session = self._store.get_session(self._current_session_id) if self._current_session_id else None
        return (session or {}).get('skill', '')

    def _update_skill_button(self, skill_name: str):
        self._skill_combo.setText(f"技能: {skill_name}" if skill_name else "无技能")

    def _activate_skill(self, skill_name: str):
        if self._current_session_id:
            self._store.set_session_skill(self._current_session_id, skill_name)
        self._update_skill_button(skill_name)
        self._refresh_skills()
        if skill_name:
            log_info(f"对话激活技能: {skill_name}")

    # ------------------------------------------------------------------
    # MCP 菜单
    # ------------------------------------------------------------------
    def _refresh_mcp_menu(self):
        self._mcp_menu.clear()
        manager = get_mcp_manager()

        enable_act = self._mcp_menu.addAction("启用 MCP 工具")
        enable_act.setCheckable(True)
        enable_act.setChecked(self._config.get('mcp.enabled', False))
        enable_act.toggled.connect(self._on_toggle_mcp_enabled)

        self._mcp_menu.addSeparator()

        if not manager.available:
            self._mcp_menu.addAction("未安装 mcp 包（pip install mcp）").setEnabled(False)
        elif self._mcp_connecting or manager.reconnecting:
            self._mcp_menu.addAction("⏳ 正在连接 MCP 服务器…").setEnabled(False)
        else:
            statuses = manager.server_statuses()
            if not statuses:
                self._mcp_menu.addAction("未配置 MCP 服务器").setEnabled(False)
            disabled_tools = set(self._config.get('mcp.disabled_tools', []) or [])
            tools_by_server = {}
            for t in manager.list_tools():
                tools_by_server.setdefault(t.server, []).append(t)
            for st in statuses:
                if st.connected:
                    server_tools = tools_by_server.get(st.name, [])
                    sub = StayOpenMenu(
                        f"✓ {st.name}（{len(server_tools)} 个工具）", self._mcp_menu)
                    self._mcp_menu.addMenu(sub)
                    if not server_tools:
                        sub.addAction("（无工具）").setEnabled(False)
                    for t in server_tools:
                        tid = f"{t.server}/{t.name}"
                        act = sub.addAction(t.name)
                        act.setCheckable(True)
                        act.setChecked(tid not in disabled_tools)
                        act.setToolTip((t.description or "").strip() or "（无描述）")
                        act.toggled.connect(
                            lambda checked, _tid=tid: self._on_toggle_mcp_tool(_tid))
                else:
                    label = f"✗ {st.name}：{st.error[:30] or '连接失败'}"
                    act = self._mcp_menu.addAction(label)
                    act.setEnabled(False)
                    # 完整失败原因悬停可见（详细错误也已写入日志）
                    act.setToolTip(st.error or "连接失败")

        self._mcp_menu.addSeparator()
        reconnect_act = self._mcp_menu.addAction("重新连接")
        reconnect_act.triggered.connect(self._on_mcp_reconnect)
        open_cfg_act = self._mcp_menu.addAction("打开配置文件…")
        open_cfg_act.triggered.connect(
            lambda: os.startfile(str(manager.config_path))
        )

        self._update_mcp_btn_text()

    def _update_mcp_btn_text(self):
        """按钮计数只统计启用中的工具；停用某工具后数字随之变化"""
        manager = get_mcp_manager()
        tools = manager.list_tools()
        _disabled = set(self._config.get('mcp.disabled_tools', []) or [])
        enabled_tools = [t for t in tools
                         if f"{t.server}/{t.name}" not in _disabled]
        if self._mcp_connecting or manager.reconnecting:
            self._mcp_btn.setText("MCP（连接中…）")
        else:
            self._mcp_btn.setText(
                f"MCP（{len(enabled_tools)}）" if enabled_tools else "MCP")

    def _on_toggle_mcp_enabled(self, checked: bool):
        self._config.set('mcp.enabled', checked)
        self._config.save()

    def _on_toggle_skills_enabled(self, checked: bool):
        self._config.set('skills.enabled', checked)
        self._config.save()
        self._refresh_skills()

    def _on_toggle_mcp_tool(self, tool_id: str):
        """启用/停用单个 MCP 工具（停用后不再注入给模型），持久保存"""
        disabled = list(self._config.get('mcp.disabled_tools', []) or [])
        if tool_id in disabled:
            disabled.remove(tool_id)
            log_info(f"MCP 工具启用: {tool_id}")
        else:
            disabled.append(tool_id)
            log_info(f"MCP 工具停用: {tool_id}")
        self._config.set('mcp.disabled_tools', disabled)
        self._config.save()
        # 勾选状态已由点击本身翻转，菜单保持展开，只需更新按钮计数
        self._update_mcp_btn_text()

    def _on_mcp_reconnect(self):
        manager = get_mcp_manager()
        if manager.reconnecting:
            return
        # 立即进入「连接中」状态；完成后 done 事件自动回主线程刷新最终结果。
        # reconnect() 内部会在未启动时自动走首次启动流程，不能再额外调 start()，
        # 否则两条连接流程并发（重复拉起子进程）
        self._mcp_connecting = True
        self._refresh_mcp_menu()
        manager.reconnect()

    def _on_mcp_status_event(self, event: str):
        """MCP 后台线程的连接状态事件（经信号已切回主线程），实时刷新菜单与按钮"""
        if event.startswith("done:"):
            self._mcp_connecting = False
        self._refresh_mcp_menu()

    # ------------------------------------------------------------------
    # 消息渲染与发送
    # ------------------------------------------------------------------
    def _render_messages(self, streaming_extra: str = "", streaming_reasoning: str = "",
                         force_scroll: bool = False, reasoning_plain: bool = False):
        session = self._store.get_session(self._current_session_id) if self._current_session_id else None
        messages = (session or {}).get('messages', [])

        # 只有用户停留在底部附近时才自动跟随滚动（修复生成时向上滚动导致的闪烁）
        bar = self._message_scroll.verticalScrollBar()
        stick = force_scroll or bar.value() >= bar.maximum() - 30

        # 计算视口宽度，用于限制气泡最大宽（避免 QLabel 富文本因无宽度
        # 约束而撑宽容器 → 水平溢出 → 文字被截断）
        vp_w = self._message_scroll.viewport().width()
        layout_margins = self._message_layout.contentsMargins()
        usable = max(vp_w - layout_margins.left() - layout_margins.right(), 200)
        self._last_render_width = usable

        # 清空旧气泡
        self._stream_label = None
        self._stream_reason_label = None
        self._stream_reason_scroll = None
        self._stream_row = None
        self._stream_reserve = None
        while self._message_layout.count():
            item = self._message_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not messages and not streaming_extra:
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(0, 90, 0, 0)
            wl.setSpacing(8)
            title = QLabel("👋 开始对话")
            title.setObjectName("emptyTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setMaximumWidth(usable)
            hint = QLabel("直接输入问题，或划词后从工具栏选择「AI 对话」，\n选中的内容会自动带入这里。")
            hint.setObjectName("emptyHint")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setMaximumWidth(usable)
            wl.addWidget(title)
            wl.addWidget(hint)
            self._message_layout.addWidget(wrap)

        for _idx, m in enumerate(messages):
            role = m.get('role')
            content = m.get('content', '')
            if role == 'assistant' and not content and not (m.get('reasoning') or ''):
                continue  # 流式占位消息（完成时原地填充），不渲染空气泡
            reasoning = m.get('reasoning') or ''
            if role == 'assistant' and not reasoning and content \
                    and '<think>' in content.lower():
                # 旧消息存储时未拆分内嵌思考标签：渲染时拆到思考框
                reasoning, content = _split_think_tags(content)
            if role in ('user', 'assistant'):
                # 流式生成中不显示回退按钮（此刻数据正在写入）
                _rw = None if (self._worker and self._worker.isRunning()) else _idx
                row, _ = self._make_bubble(
                    role, content, reasoning=reasoning, usable=usable,
                    rewind_index=_rw)
                self._message_layout.addWidget(row)

        if streaming_extra or streaming_reasoning:
            # 光标紧跟末行文本（不独占一行）：定稿去掉光标时气泡高度不变
            # lstrip 与 _update_stream_display / 定稿对齐（见上）
            _se = streaming_extra.lstrip()
            content_html = (_format_content(_se) if _se else "") + "▍"
            row, label = self._make_bubble(
                'assistant', content_html, reasoning=streaming_reasoning,
                html_ready=True, usable=usable, reasoning_plain=reasoning_plain)
            # 流式中高频更新：禁掉文本选择（可选中富文本 QLabel 快速 setText
            # 是 Qt 易崩溃路径），结束后重渲染会恢复可选
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            # 思考阶段只显示思考气泡：正文气泡在首个正文 chunk 到达前隐藏；
            # 无思考时保持可见（正文流式中 / 工具状态 / 失败信息）
            label.setVisible(bool(streaming_extra.strip())
                             or not streaming_reasoning.strip())
            self._stream_label = label
            rlabel = row.findChild(QLabel, "reasoningContent")
            if rlabel is not None:
                rlabel.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                self._stream_reason_label = rlabel
                self._stream_reason_scroll = row.findChild(QScrollArea, "reasoningScroll")
                # 折叠态自动跟随：rangeChanged 在布局更新范围的同帧（绘制前）触发，
                # 补偿 setText 后用旧范围滚动的一帧滞后（末行闪烁根因）；
                # valueChanged 记录用户是否手动上滚，上滚则暂停跟随
                if self._stream_reason_scroll is not None:
                    _rb = self._stream_reason_scroll.verticalScrollBar()
                    _rb.rangeChanged.connect(self._on_reason_range_changed)
                    _rb.valueChanged.connect(self._on_reason_scroll_moved)
                    # 此时行未入布局、视口宽度不可信，必须显式传宽度供折行度量
                    # 此时行未入布局、视口宽度不可信，必须显式传宽度供折行度量
                    #（usable - 24 = 布局后滚动区视口的真实最终宽度）
                    # 不做逐行长高动画：平滑过渡读起来像「新行在滑动」（用户
                    # 反馈）；瞬时长高让新行直接进入新增空间、首行纹丝不动
                    self._stream_reason_scroll._animate_grow = False
                    # 占位补偿：思考框每长高 1px，占位（sizeHint 引用框高）
                    # 缩小 1px，消息区总高恒定 → rangeChanged 不再触发底部
                    # 跟随 → 「思考过程」标题位置固定、内容向下生长；长到
                    # 5 行上限后占位归零。仅纯思考阶段创建（必须先于 fit 登记，
                    # 使 fit/动画的每次 applyHeight 都触发占位重新度量）：
                    # 正文开始后思考停止增长，占位只剩空隙、移除时塌陷
                    if not streaming_extra.strip():
                        from math import ceil
                        _cap5 = int(ceil(self._reason_line_h(self._stream_reason_label) * 5))
                        _sp = _ReserveWidget(self._stream_reason_scroll, _cap5)
                        self._stream_reserve = (_sp, _cap5)
                        self._stream_reason_scroll._reserve_w = _sp
                    # 与 _make_reasoning_block 初始 fit 同基准（usable - 24）：
                    # 宽度基准不一会让入布局后的重测折行变化、整段文字偶发跳变
                    self._fit_reasoning_scroll(self._stream_reason_scroll,
                                               width_hint=max(usable - 24, 60))
            self._message_layout.addWidget(row)
            self._stream_row = row
            if self._stream_reserve is not None:
                # 占位插入行内布局（思考气泡与正文之间）：思考框长高 Δ、
                # 占位缩小 Δ，行高严格恒定 → 消息区总高永不变，滚动条
                # range 无变化，「思考过程」标题位置绝对固定
                row.layout().insertWidget(1, self._stream_reserve[0])
                self._stream_reserve[0].updateGeometry()

        self._message_layout.addStretch()
        if stick:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _make_bubble(self, role: str, content: str, reasoning: str = "",
                     html_ready: bool = False, usable: int = 400,
                     reasoning_plain: bool = False,
                     rewind_index: Optional[int] = None):
        """创建单条消息气泡（返回行容器与正文 QLabel）；
        带思考过程时思考块作为独立气泡叠在正文气泡上方；
        rewind_index 非 None 时悬停显示「回退到此」按钮"""
        text_html = content if html_ready else _format_content(content)
        label = QLabel(text_html)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setMinimumWidth(40)
        # 撑满聊天区可用宽度（不加 maxWidth 会按未换行宽度撑大容器 → 溢出截断）
        label.setMaximumWidth(usable)

        row = _BubbleRow()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)  # 思考气泡与正文气泡的间距

        if reasoning.strip() and role == 'assistant':
            # 思考过程独立成气泡，正文气泡紧随其下
            lay.addWidget(self._make_reasoning_bubble(reasoning, usable, reasoning_plain))
        label.setObjectName("bubbleUser" if role == 'user' else "bubbleAssistant")
        lay.addWidget(label)  # 占满整行，与聊天区同宽
        if rewind_index is not None:
            _bubble_bg = (get_theme()['accent_color'] if role == 'user'
                          else get_theme()['bg_secondary'])
            row.set_hover_button(self._make_rewind_btn(rewind_index, _bubble_bg))
            self._install_rewind_menu(label, rewind_index, content)
        return row, label

    @staticmethod
    def _contrast_color(hex_color: str) -> str:
        """给定背景色返回对比前景色（亮度 < 0.5 → 白，否则黑）"""
        try:
            h = hex_color.lstrip('#')
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            return '#ffffff' if lum < 0.5 else '#000000'
        except Exception:
            return '#ffffff'

    def _make_rewind_btn(self, index: int, bubble_bg: str) -> QPushButton:
        """创建回退按钮（图标色与气泡底色对比，点击回退到第 index 条）"""
        btn = QPushButton("↵")
        btn.setObjectName("rewindBtn")
        btn.setFixedSize(22, 22)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip("回退到这条消息（删除之后的对话）")
        theme = get_theme()
        # 透明背景无边框；图标色按气泡底色对比（深气泡白/浅气泡黑）
        icon_color = self._contrast_color(bubble_bg)
        btn.setStyleSheet(f"""
            QPushButton#rewindBtn {{
                background-color: transparent;
                color: {icon_color};
                border: none;
                border-radius: 11px;
                font-size: 14px;
            }}
            QPushButton#rewindBtn:hover {{
                background-color: {theme['button_hover']};
                color: {icon_color};
            }}
        """)
        btn.clicked.connect(
            lambda _=False, i=index: self._rewind_to(i))
        return btn

    def _install_rewind_menu(self, label, index: int, content: str):
        """消息气泡右键菜单：回退到这条消息 / 复制消息"""
        label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        label.customContextMenuRequested.connect(
            lambda pos, i=index, c=content: self._show_message_menu(
                i, c, label.mapToGlobal(pos)))

    def _show_message_menu(self, index: int, content: str, global_pos):
        """消息右键菜单（流式生成中不显示回退项）"""
        menu = QMenu(self)
        act_rewind = None
        if not (self._worker and self._worker.isRunning()):
            act_rewind = menu.addAction("↵ 回退到这条消息")
            menu.addSeparator()
        act_copy = menu.addAction("复制消息")
        chosen = menu.exec(global_pos)
        if chosen is act_rewind and act_rewind is not None:
            self._rewind_to(index)
        elif chosen is act_copy:
            QApplication.clipboard().setText(content)

    def _rewind_to(self, index: int):
        """回退对话到第 index 条消息：保留该条及其之前全部，删除其后对话"""
        if self._worker and self._worker.isRunning():
            return  # 流式生成中数据正在写入，禁止回退
        if not self._current_session_id:
            return
        self._store.truncate_messages(self._current_session_id, index + 1)
        self._render_messages(force_scroll=True)
        self._input_edit.setFocus()

    def _make_reasoning_bubble(self, reasoning: str, usable: int, plain: bool = False) -> QWidget:
        """思考过程独立气泡：浅底 + 虚线边框，与正文气泡视觉区分"""
        bubble = QWidget()
        bubble.setObjectName("bubbleReasoning")
        bubble.setMaximumWidth(usable)
        bl = QVBoxLayout(bubble)
        # QWidget 容器的 QSS padding 不影响子控件布局，须用布局边距代替，
        # 否则内容会贴住气泡角落、凸出圆角弧外
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(0)
        bl.addWidget(self._make_reasoning_block(reasoning, plain, usable))
        return bubble

    def _reason_line_h(self, label) -> float:
        """富文本实测行高（思考框高度计算的统一基准）：
        文档边距清零与 QLabel 渲染保持一致（QLabel 内部即 0 边距）"""
        from PyQt6.QtGui import QTextDocument
        _d = QTextDocument()
        _d.setDocumentMargin(0)
        _d.setDefaultFont(label.font())
        _d.setTextWidth(100000)
        _d.setHtml('测\x3cbr\x3e测')
        return _d.size().height() / 2.0

    def _fit_reasoning_scroll(self, scroll, width_hint: int = 0):
        """思考框高度自适应：内容不足 5 行按内容收缩（最少 1 行），
        超过 5 行封顶滚动（顶部「思考过程」标题固定占 1 行，整块合计 6 行）"""
        if scroll is None:
            return
        label = scroll.findChild(QLabel, "reasoningContent")
        if label is None:
            return
        from math import ceil
        # 行高一律按富文本实测（定稿/历史的最终渲染形态）：流式纯文本的
        # fontMetrics 行距偏大，混用两套基准会在定稿瞬间产生高度跳变
        line_h = self._reason_line_h(label)
        # 内容上限精确等于 5 行高度，不留松弛：任何多余像素都会露出下一行；
        # 顶部「思考过程」标题固定占 1 行，与内容 5 行合计整块 6 行
        collapsed_h = int(ceil(line_h * 5))
        min_h = int(ceil(line_h))
        if getattr(scroll, '_capped', False):
            return  # 已达上限（内容超 5 行需框内滚动）：内容只增不减，无需再算
        # 行未入布局时 scroll 视口是默认小宽度（约 98px），据此折行会把
        # 短内容误判成多行封顶；显式 width_hint 由调用方按可用宽度算出，优先
        if width_hint > 10:
            w = width_hint
        else:
            w = scroll.viewport().width()
            if w < 120:  # 未入布局的默认小视口不可信，回退消息区可用宽度
                w = max(self._message_scroll.viewport().width() - 60, 200)
        # 直接按视口宽度测量：heightForWidth 语义即「控件宽 w 时的高度」，
        # 富文本 documentMargin 由其内部自洽处理；再减 4px 会把边界带的行
        # 多算一行 → 提前封顶/跟随 → 整段文字无故上移（低概率跳变来源）
        doc_h = label.heightForWidth(max(w, 40))
        h = max(min(doc_h, collapsed_h), min_h)
        # 严格大于才算封顶：恰好 5 行无滚动余量
        scroll._capped = (doc_h > collapsed_h)
        # 纵向滚动条永久隐藏：封顶瞬间滚动条首次出现会占掉约一个字的宽度，
        # 视口变窄、全部行提前折行，整段文字跳一下（「最后一格空着就换行」
        # 的来源）；隐藏后滚轮滚动与代码滚动（setValue）不受影响
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 高度未变但 min/max 不一致时必须即时重设以同步约束
        if scroll.minimumHeight() != scroll.maximumHeight():
            scroll.applyHeight(h)
        elif h > scroll.height() and getattr(scroll, '_animate_grow', False) \
                and self.isVisible():
            # 流式增长：平滑过渡到目标高度（逐行连贯长高）
            scroll.animateToHeight(h)
        elif scroll.height() != h:
            scroll.applyHeight(h)

    def _make_reasoning_block(self, reasoning: str, plain: bool = False,
                              usable_w: int = 0) -> QWidget:
        """思考过程块：标题 + 高度自适应的可滚动内容区
        （内容少按内容收缩，最多 5 行；顶部标题固定占 1 行）"""
        block = QWidget()
        block.setObjectName("reasoningBlock")
        vl = QVBoxLayout(block)
        vl.setContentsMargins(0, 0, 0, 6)
        vl.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel("💭 思考过程")
        title.setObjectName("reasoningTitle")
        header.addWidget(title)
        header.addStretch()
        vl.addLayout(header)

        scroll = _ReasoningScroll()
        scroll.setObjectName("reasoningScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        rlabel = QLabel()
        rlabel.setObjectName("reasoningContent")
        if plain:
            # 流式中用纯文本格式：每次 setText 免富文本全量解析，
            # 长思考高频刷新下开销远小于富文本（结束后重建才按富文本渲染）
            rlabel.setTextFormat(Qt.TextFormat.PlainText)
            rlabel.setText(reasoning)
        else:
            rlabel.setTextFormat(Qt.TextFormat.RichText)
            # keep_blanks：与流式纯文本逐行一致，定稿/重建不因空行消失跳变
            rlabel.setText(_format_content(reasoning, keep_blanks=True))
        rlabel.setWordWrap(True)
        rlabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # 以与 QSS（#reasoningContent）一致的字号度量行高，
        # 否则按默认字体度量会让折叠高度不足实际的 6 行
        _fs = max(int(self._config.get('font.size', 15)) - 1, 12)
        _f = rlabel.font()
        _f.setPixelSize(_fs)
        rlabel.setFont(_f)
        scroll.setWidget(rlabel)
        vl.addWidget(scroll)

        # 初始高度按内容自适应（1~6 行）；布局落定后流式/定稿路径会再校正。
        # 首次用 setFixedHeight 使 min==max，供流式折叠态判断使用
        scroll.setFixedHeight(rlabel.fontMetrics().lineSpacing() + 6)
        scroll._capped = False
        self._fit_reasoning_scroll(scroll,
                                   width_hint=max(usable_w - 24, 60))

        return block

    def _scroll_to_bottom(self):
        # 滚动到底。不可 adjustSize：widgetResizable 下容器高度由滚动区管理，
        # 手动改高会与布局互相拉扯，流式中每帧震荡造成文字抖动；
        # 布局滞后一帧的范围变化由 rangeChanged 同帧补偿。
        # 先 activate 使布局定稿：富文本气泡高度需一轮布局才算出，
        # 未定稿时 maximum() 仍为旧值（重建后为 0），setValue 不生效
        self._message_container.layout().activate()
        # 布局落定后滚动条才可能首次出现、视口随之收窄约一条滚动条宽：
        # 把渲染宽度基准同步为真实折行宽度，否则 show() 后的防抖 relayout
        # 误判「宽度变了」整段重建消息区（进窗口瞬间右侧气泡跳动调整）
        _m = self._message_layout.contentsMargins()
        self._last_render_width = max(
            self._message_scroll.viewport().width() - _m.left() - _m.right(), 200)
        bar = self._message_scroll.verticalScrollBar()
        self._message_scroll.stopSmooth()
        bar.setValue(bar.maximum())

    def _finalize_stream_row(self):
        """流式气泡原地定稿为完成态，不替换、不重建任何行。
        替换行（insert 新行 + remove 旧行）时，新气泡富文本 QLabel 的
        初始高度尚未约束计算（heightForWidth 需布局轮次，默认仅几十像素），
        移除旧行后滚动内容总高瞬间塌陷、滚动值被夹到极小 max，
        视觉上先闪到顶部再跳回底部。原地定稿只改文本与交互属性，
        高度随文本微调，滚动范围连续无闪动；上滚用户的位置也天然保持。
        返回是否完成原地定稿（False 表示退回了全量重建）"""
        session = self._store.get_session(self._current_session_id) \
            if self._current_session_id else None
        messages = (session or {}).get('messages', [])
        last = messages[-1] if messages else None
        row = self._stream_row
        label = self._stream_label
        idx = self._message_layout.indexOf(row) if row is not None else -1
        if idx < 0 or label is None or last is None or last.get('role') != 'assistant':
            self._render_messages()  # 结构不符时退回全量重建
            return False
        vp_w = self._message_scroll.viewport().width()
        margins = self._message_layout.contentsMargins()
        usable = max(vp_w - margins.left() - margins.right(), 200)
        # 正文：去掉流式光标、恢复文本可选
        label.setText(_format_content(last.get('content', '')))
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setVisible(bool(last.get('content', '').strip()))  # 不留空壳气泡
        # 思考框：流式期纯文本（免高频富文本解析）→ 定稿按富文本渲染
        rlabel = self._stream_reason_scroll.findChild(QLabel, "reasoningContent") \
            if self._stream_reason_scroll is not None else None
        rs = self._stream_reason_scroll
        if rlabel is not None:
            stored_reasoning = last.get('reasoning') or ''
            if stored_reasoning:
                rlabel.setTextFormat(Qt.TextFormat.RichText)
                # keep_blanks：保留段落间空行，与流式显示逐行一致，消除跳变
                rlabel.setText(_format_content(stored_reasoning, keep_blanks=True))
            rlabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            # 思考完成：清 _capped 强制按富文本行高重算；
            # 停止并关闭增长动画，使定稿高度即时落定（避免动画帧覆盖定稿值）
            if rs._grow_anim is not None:
                rs._grow_anim.stop()
            rs._reserve_w = None
            if self._stream_reserve is not None:
                _sp = self._stream_reserve[0]
                _host = _sp.parentWidget()
                if _host is not None and _host.layout() is not None:
                    _host.layout().removeWidget(_sp)
                _sp.deleteLater()
                self._stream_reserve = None
            rs._animate_grow = False
            rs._capped = False
            # 定稿时行已在布局中、视口宽度可信：与流式测量保持同一宽度
            # 基准，避免 width_hint=usable（更宽）少折行导致框高回缩
            self._fit_reasoning_scroll(rs)
        # 定稿完成后为本行补回退按钮（流式期不创建，避免生成中回退）
        if isinstance(row, _BubbleRow) and row._hover_btn is None:
            row.set_hover_button(self._make_rewind_btn(
                len(messages) - 1, get_theme()['bg_secondary']))
            self._install_rewind_menu(label, len(messages) - 1,
                                      last.get('content', ''))
        self._stream_row = None
        self._stream_label = None
        self._stream_reason_label = None
        self._stream_reason_scroll = None
        self._last_render_width = usable
        return True
    def _on_main_range_changed(self, _min: int, maxv: int):
        """消息区内容长高：绘制前同帧滚到底，补偿 setText 后布局未完成的一帧滞后"""
        bar = self._message_scroll.verticalScrollBar()
        if self.sender() is not bar:
            return
        if not self._main_follow:
            return
        if not (self._worker and self._worker.isRunning()):
            return
        self._message_scroll.stopSmooth()
        bar.setValue(maxv)

    def _on_main_scroll_moved(self, value: int):
        """用户在主消息区上滚时暂停自动跟随，滚回底部附近恢复"""
        bar = self._message_scroll.verticalScrollBar()
        if self.sender() is not bar:
            return
        self._main_follow = (bar.maximum() - value) <= 40

    def _near_bottom(self) -> bool:
        return self._main_follow

    def _scroll_last_reasoning_to_bottom(self):
        """回复结束后把最后一个思考框滚到底（与流式跟随位置一致，
        否则重建后回到第一行，视觉上像思考完突然跳上去）"""
        rs = None
        for i in range(self._message_layout.count() - 1, -1, -1):
            item = self._message_layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None:
                rs = w.findChild(QScrollArea, "reasoningScroll")
                if rs is not None:
                    break
        if rs is None:
            return
        inner = rs.widget()
        if inner is not None:
            w = rs.viewport().width()
            if w > 0 and inner.width() != w:
                inner.resize(w, inner.height())
            inner.adjustSize()
        bar = rs.verticalScrollBar()
        rs.stopSmooth()
        bar.setValue(bar.maximum())

    def _on_reason_range_changed(self, _min: int, maxv: int):
        """思考框内容长高导致滚动范围变化：绘制前同帧滚到底，避免末行闪烁"""
        rs = self._stream_reason_scroll
        if rs is None or self.sender() is not rs.verticalScrollBar():
            return  # 上一代已重建的旧滚动条
        if not getattr(self, '_reason_follow', True):
            return
        if not (self._worker and self._worker.isRunning()):
            return
        rs.stopSmooth()
        rs.verticalScrollBar().setValue(maxv)

    def _on_reason_scroll_moved(self, value: int):
        """用户手动滚离底部时暂停跟随，滚回底部恢复"""
        rs = self._stream_reason_scroll
        if rs is None or self.sender() is not rs.verticalScrollBar():
            return
        self._reason_follow = (rs.verticalScrollBar().maximum() - value) < 40

    def _update_stream_display(self, body_extra: str = ""):
        """按当前缓冲（思考 + 正文）刷新流式气泡"""
        if self._is_dragging or self._resize_edge:
            return  # 拖动中跳过（singleShot 定时器随之停止），松手后补刷
        body = self._stream_buffer + body_extra
        need_reasoning = bool(self._reasoning_buffer.strip())
        has_reason_ui = self._stream_reason_label is not None
        if self._stream_label is not None and (not need_reasoning or has_reason_ui):
            # 只更新流式气泡，不重建全部消息（减少重绘与滚动跳动）
            stick = self._near_bottom()
            # 光标紧跟末行文本（不独占一行）：定稿去掉光标时气泡高度不变
            # lstrip 去掉正文起始空白： 模型  后的换行会进入缓冲，
            # 被渲染成开头空行；定稿内容经 _split_think_tags strip 后无此
            # 空行 → 单行正文定稿瞬间收缩一行。流式同 lstrip 保持一致
            disp = body.lstrip()
            body_html = (_format_content(disp) if disp else "") + "▍"
            if self._stream_label.text() != body_html:
                self._stream_label.setText(body_html)
            # 思考阶段只显示思考气泡，首个正文 chunk 到达时正文气泡才出现
            self._stream_label.setVisible(bool(body.strip()) or not need_reasoning)
            if body.strip() and self._stream_reserve is not None:
                # 正文开始 = 思考停止增长：占位使命完成，与正文气泡同帧移除，
                # 空隙即时闭合；留到定稿才移除会出现「正文先出现、随后整段
                # 往上缩」的塌陷跳变
                _sp = self._stream_reserve[0]
                _host = _sp.parentWidget()
                if _host is not None and _host.layout() is not None:
                    _host.layout().removeWidget(_sp)
                _sp.deleteLater()
                self._stream_reserve = None
                if self._stream_reason_scroll is not None:
                    self._stream_reason_scroll._reserve_w = None
            if need_reasoning:
                # 标签为纯文本格式：直接写原始缓冲，免转义与解析
                # strip 去首尾空白：内嵌思考标签模型的思考紧随开标签带前导
                # 换行，会被渲染成开头空行、单行思考显示两行高；落库/兜底
                # 路径（_split_think_tags）均 strip，流式同 strip 保持一致
                self._stream_reason_label.setText(self._reasoning_buffer.strip())
                rs = self._stream_reason_scroll
                # 思考增长时框随内容长高，到 6 行上限后不再变化
                self._fit_reasoning_scroll(rs)
                if rs.minimumHeight() == rs.maximumHeight() and self._reason_follow:
                    # 折叠且用户未上滚：跟随到最新。滚动条范围滞后一帧，
                    # 直接读 maximum() 在封顶帧会读到旧值 0 滚不动、积累到
                    # 下一帧一次跳两行；改用本次测量的内容高算目标，先
                    # setRange 再 setValue，同帧到位，每行只移一行
                    rbar = rs.verticalScrollBar()
                    _vw = rs.viewport().width()
                    if _vw >= 120:  # 视口已布局：测量可信
                        _doc = self._stream_reason_label.heightForWidth(max(_vw, 40))
                        _max = max(0, _doc - rs.viewport().height())
                        rbar.setRange(0, _max)
                        rbar.setValue(_max)
                    else:  # 视口未布局完成：等 rangeChanged 同帧补偿
                        rbar.setValue(rbar.maximum())
            if stick:
                QTimer.singleShot(0, self._scroll_to_bottom)
        else:
            # 思考首次到达等结构变化场景：重建气泡
            self._render_messages(
                streaming_extra=body,
                streaming_reasoning=self._reasoning_buffer.strip(),
                reasoning_plain=True)

    def _schedule_flush(self):
        """合并高频chunk：计时器未激活时安排一次刷新，期间的 chunk 一并呈现"""
        if self._is_dragging or self._resize_edge:
            return  # 拖动/缩放中暂停 UI 刷新：富文本重排与窗口重绘竞争主线程掉帧；
            # 缓冲照常累积，mouseReleaseEvent 松手后补刷
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def send_message(self, text: Optional[str] = None):
        if self._worker and self._worker.isRunning():
            return
        content = (text if text is not None else self._input_edit.toPlainText()).strip()
        if not content:
            return
        if not self._current_session_id:
            self._on_new_session()

        sid = self._current_session_id
        self._store.append_message(sid, 'user', content)
        # 同步追加空 assistant 占位：完成时原地覆盖，避免多轮会话下
        # 末尾是 user 导致落库错位 / 渲染兜底重建引起滚动跳顶
        self._store.append_message(sid, 'assistant', '')
        self._input_edit.clear()
        self._reload_session_list()

        # 组装消息（上下文不限条数，由后台线程按模型窗口摘要压缩）
        system_prompt = BASE_SYSTEM_PROMPT
        skill_name = self._current_skill_name()
        if skill_name:
            skill = get_skill_manager().get_skill(skill_name)
            if skill:
                system_prompt += f"\n\n当前激活的技能「{skill.name}」要求：\n{skill.content}"

        session = self._store.get_session(sid) or {}
        history = [
            {'role': m['role'], 'content': m['content']}
            for m in session.get('messages', [])
            if m.get('role') in ('user', 'assistant') and m.get('content')
        ]
        summary = session.get('summary', '') or ""
        summary_count = int(session.get('summary_count', 0) or 0)
        if summary_count > len(history):
            summary, summary_count = "", 0
        context_limit = self._config.get('chat.model_context_limit', 32768)

        # MCP 工具
        tools: List[MCPToolInfo] = []
        manager = get_mcp_manager()
        if self._config.get('mcp.enabled', False) and manager.available:
            tools = manager.list_tools()
            # 停用的工具不注入给模型（在 MCP 菜单中按工具勾选管理）
            _disabled_tools = set(self._config.get('mcp.disabled_tools', []) or [])
            if _disabled_tools:
                tools = [t for t in tools
                         if f"{t.server}/{t.name}" not in _disabled_tools]

        # 技能本地执行工具（存在技能时才注册；脚本执行需用户确认）
        skill_tools = None
        if self._config.get('skills.enabled', False):
            try:
                if get_skill_manager().load_skills():
                    skill_tools = get_skill_local_tools(confirm=self._skill_confirm,
                                                        trusted=self._trusted_skills)
            except Exception as e:
                log_error(f"加载技能本地工具失败: {e}")

        # API 配置：取消"与翻译共用"且独立配置已填写时走对话专用 API
        # （设置里测试通过的那套）；否则继续用与翻译相同的模型配置
        if (not self._config.get('chat.use_shared_api', True)) \
                and self._config.get('chat.base_url', '') \
                and self._config.get('chat.model', ''):
            client_kwargs = {
                'api_key': self._config.get('chat.api_key', ''),
                'base_url': self._config.get('chat.base_url', ''),
                'timeout': self._config.get('chat.timeout', 60),
            }
            model = self._config.get('chat.model', '')
        else:
            client_kwargs = {
                'api_key': self._config.get('translator.api_key', ''),
                'base_url': self._config.get('translator.base_url', ''),
                'timeout': self._config.get('translator.timeout', 60),
            }
            model = self._config.get('translator.model', '')

        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._reason_follow = True
        self._main_follow = True
        self._send_btn.setEnabled(False)
        # 不渲染 "…" 占位气泡：发送后先只显示用户消息，思考框随首个
        # 思考 chunk 出现，正文框随首个正文 chunk 出现
        self._render_messages(force_scroll=True)

        self._worker = ChatWorker(sid, system_prompt, history, summary, summary_count,
                                  model, client_kwargs, context_limit, tools, skill_tools)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.reasoning_chunk.connect(self._on_reasoning_chunk)
        self._worker.tool_info.connect(self._on_tool_info)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.context_compressed.connect(self._on_context_compressed)
        self._worker.confirm_request.connect(self._on_confirm_request)
        self._worker.start()

    def _on_context_compressed(self, session_id: str, summary: str, covered: int):
        """后台线程完成历史压缩后，持久滚动摘要与覆盖条数"""
        self._store.set_session_summary(session_id, summary, covered)

    # ---------------- 技能脚本执行确认 ----------------
    def _skill_confirm(self, skill_name: str, desc: str) -> bool:
        """技能本地工具在后台线程调用的确认回调：经 worker 阻塞等待主窗口弹窗结果"""
        if skill_name in self._trusted_skills:
            return True
        worker = self._worker
        if worker is None:
            return False
        return worker.ask_user_confirm(skill_name, desc)

    def _on_confirm_request(self, skill_name: str, desc: str):
        """技能脚本执行确认弹窗（主线程）；勾选信任后本会话不再询问"""
        worker = self._worker
        if worker is None:
            return
        log_info(f"技能脚本确认弹窗: {skill_name}")
        box = QMessageBox(self)
        box.setWindowTitle("技能脚本执行确认")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"AI 请求执行技能目录中的脚本：\n\n{desc}")
        box.setStandardButtons(QMessageBox.StandardButton.Ok
                               | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Ok).setText("允许执行")
        box.button(QMessageBox.StandardButton.Cancel).setText("拒绝")
        cb = QCheckBox("本会话内此技能不再询问")
        box.setCheckBox(cb)
        # 模态弹窗必须抢到前台：QMessageBox 是应用级模态，一旦弹窗
        # 落在后面/看不见，整个应用就被模态锁住——其它窗口都能
        # 激活置顶，但所有按钮都点不了。先 show 再做 Win32 前台抢占，
        # 最后进 exec 模态循环
        box.show()
        box.raise_()
        box.activateWindow()
        if sys.platform == "win32":
            import ctypes
            user32 = ctypes.windll.user32
            # 必须声明 argtypes：否则 64 位句柄按 32 位截断，调用静默失效
            user32.SetWindowPos.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            hwnd = int(box.winId())
            SWP_NOMOVE, SWP_NOSIZE = 0x0002, 0x0001
            # 临时置顶后立即释放：落在非置顶带最顶端，压过所有窗口
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE)
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE)
            user32.SetForegroundWindow(hwnd)
        log_info(f"[Confirm] 确认弹窗已显示，进入模态循环: {skill_name}")
        _t0 = time.time()
        ok = box.exec() == QMessageBox.StandardButton.Ok
        log_info(f"[Confirm] 确认弹窗关闭: {skill_name} ok={ok} "
                 f"勾选信任={cb.isChecked()} 持续={time.time() - _t0:.1f}s")
        if ok and cb.isChecked():
            self._trusted_skills.add(skill_name)
        worker.deliver_confirm(ok)

    def _on_chunk(self, chunk: str):
        self._stream_buffer += chunk
        self._schedule_flush()

    def _on_reasoning_chunk(self, chunk: str):
        self._reasoning_buffer += chunk
        self._schedule_flush()

    def _on_tool_info(self, info: str):
        log_info(info)
        extra = f"\n\n*{info}*" if self._stream_buffer else f"*{info}*"
        self._update_stream_display(body_extra=extra)

    def _on_finished(self, full_text: str, reasoning: str = ""):
        self._flush_timer.stop()
        _bar = self._message_scroll.verticalScrollBar()
        was_at_bottom = self._main_follow or _bar.value() >= _bar.maximum() - 30
        had_reasoning = bool(self._reasoning_buffer.strip())
        # 兜底：正文里仍残留 <think> 标签时（未经流式解析的异常路径）拆出
        _t, _b = _split_think_tags(full_text)
        if _t:
            full_text = _b
            if not had_reasoning:
                self._reasoning_buffer = _t
                had_reasoning = True
        if self._current_session_id and full_text:
            # 纯空白思考内容视为无思考（部分非思考模型会回传空白 reasoning_content）
            self._store.update_last_assistant_message(
                self._current_session_id, full_text,
                reasoning=self._reasoning_buffer.strip() if had_reasoning else '')
        elif self._current_session_id:
            # 无正文返回：清理占位，不残留空消息
            self._store.remove_trailing_empty_assistant(self._current_session_id)
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._send_btn.setEnabled(True)
        self._reload_session_list()
        # 原地把流式行换成完成气泡（不全量重建）：重建会瞬间把滚动范围
        # 归零、value 回 0，视觉上先闪到顶部再跳回底部
        swapped = self._finalize_stream_row()
        if was_at_bottom:
            if swapped:
                # 原地定稿不换行，高度仅随文本微调：同帧滚到底即可，
                # 残余一帧的 rangeChanged 由 _on_main_range_changed 补偿
                self._scroll_to_bottom()
            else:
                # 全量重建后滚动范围需重新落定，同步滚时机过早，延迟补滚
                QTimer.singleShot(0, self._scroll_to_bottom)
                QTimer.singleShot(120, self._scroll_to_bottom)
        if had_reasoning:
            # 保持与流式跟随一致的阅读位置：完成后的思考框不跳回第一行
            QTimer.singleShot(0, self._scroll_last_reasoning_to_bottom)
            QTimer.singleShot(120, self._scroll_last_reasoning_to_bottom)

    def _on_failed(self, error: str):
        self._flush_timer.stop()
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._send_btn.setEnabled(True)
        if self._current_session_id:
            # 清理本轮的空 assistant 占位，失败不残留空消息
            self._store.remove_trailing_empty_assistant(self._current_session_id)
        self._render_messages(streaming_extra=f"[请求失败] {error}")

    def _cancel_worker(self):
        worker = self._worker
        self._worker = None
        self._flush_timer.stop()
        if worker and worker.isRunning():
            worker.cancel()
            # 断开 UI 信号：已取消的输出不再刷新界面（会话可能已切走）
            for sig, slot in ((worker.chunk, self._on_chunk),
                              (worker.reasoning_chunk, self._on_reasoning_chunk),
                              (worker.tool_info, self._on_tool_info),
                              (worker.finished_ok, self._on_finished),
                              (worker.failed, self._on_failed),
                              (worker.context_compressed,
                               self._on_context_compressed),
                              (worker.confirm_request,
                               self._on_confirm_request)):
                try:
                    sig.disconnect(slot)
                except TypeError:
                    pass
            if not worker.wait(2000):
                # 网络读取无法立即中断：保持引用直到线程自然结束，
                # 否则 QThread 在运行中被回收会直接 abort 进程
                self._zombie_workers.append(worker)
                worker.finished.connect(
                    lambda: self._zombie_workers.remove(worker)
                    if worker in self._zombie_workers else None)
        self._send_btn.setEnabled(True)
        if self._current_session_id:
            self._store.remove_trailing_empty_assistant(self._current_session_id)
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._render_messages()


# 全局实例
_chat_window_instance: Optional[ChatWindow] = None


def get_chat_window() -> ChatWindow:
    global _chat_window_instance
    if _chat_window_instance is None:
        _chat_window_instance = ChatWindow()
    return _chat_window_instance
