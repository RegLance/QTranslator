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
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, QPointF, QSize, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QCursor, QIcon, QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QMenu, QFrame,
    QToolButton, QInputDialog, QSplitter, QSplitterHandle, QScrollArea,
    QAbstractButton, QAbstractSlider, QAbstractScrollArea,
)

try:
    from ..config import get_config, APP_NAME
    from ..utils.logger import log_info, log_error, log_debug
    from ..utils.theme import get_theme
    from ..core.chat_store import get_chat_store
    from ..core.skills import get_skill_manager
    from ..core.mcp_client import get_mcp_manager, MCPToolInfo
except ImportError:
    from src.config import get_config, APP_NAME
    from src.utils.logger import log_info, log_error, log_debug
    from src.utils.theme import get_theme
    from src.core.chat_store import get_chat_store
    from src.core.skills import get_skill_manager
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


def _blocks_to_html(text: str) -> str:
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


def _format_content(text: str) -> str:
    """Markdown → Qt 富文本 HTML：代码块 / 标题 / 列表 / 引用 / 表格 / 行内样式"""
    segments = text.split('```')
    parts = []
    for idx, seg in enumerate(segments):
        if idx % 2 == 0:
            parts.append(_blocks_to_html(seg))
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


def _contrast_color(bg_hex: str) -> str:
    """按背景亮度返回对比文字色：深色背景→白字，浅色背景→黑字"""
    h = (bg_hex or '').lstrip('#')
    try:
        if len(h) == 3:
            h = ''.join(ch * 2 for ch in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        return '#ffffff'
    # ITU-R BT.601 亮度，>150 视为浅色背景
    return '#000000' if 0.299 * r + 0.587 * g + 0.114 * b > 150 else '#ffffff'


def _trash_icon(color: str) -> QIcon:
    """绘制垃圾桶图标（emoji 字体渲染不一致，绘制图标颜色可控）；
    Active 模式（悬停/按下）使用红色"""
    def _draw(c: str) -> QPixmap:
        pix = QPixmap(20, 20)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(c))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(8.5, 4), QPointF(11.5, 4))   # 提手
        p.drawLine(QPointF(3.5, 6.5), QPointF(16.5, 6.5))  # 盖沿
        p.drawRoundedRect(QRectF(5.5, 6.5, 9, 10.5), 1.5, 1.5)  # 桶身
        p.drawLine(QPointF(8.6, 9.5), QPointF(8.6, 14))   # 内纹
        p.drawLine(QPointF(11.4, 9.5), QPointF(11.4, 14))
        p.end()
        return pix
    icon = QIcon()
    icon.addPixmap(_draw(color), QIcon.Mode.Normal)
    icon.addPixmap(_draw('#e81123'), QIcon.Mode.Active)
    return icon


# ── 上下文压缩策略 ──
# 移植开源方案：LangChain 的 ConversationSummaryBufferMemory（MIT 许可）摘要缓冲模式：
# 最近的消息原文保留，较早的消息被滚动摘要压缩。
# token 计数优先用 OpenAI 开源的 tiktoken（已安装时），否则退化为 CJK 启发式估算。
CONTEXT_USAGE_RATIO = 0.7   # 上下文超过约 70% 模型窗口时触发压缩
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
    reasoning = pyqtSignal(str)      # 思考模型的思考过程片段（reasoning_content）
    tool_info = pyqtSignal(str)      # MCP 工具调用过程提示
    finished_ok = pyqtSignal(str)    # 完成，完整文本
    failed = pyqtSignal(str)         # 失败，错误信息
    context_compressed = pyqtSignal(str, str, int)  # (session_id, 新摘要, 覆盖条数)

    def __init__(self, session_id: str, system_prompt: str,
                 history: List[Dict[str, str]], summary: str, summary_count: int,
                 model: str, client_kwargs: Dict[str, Any], context_limit: int,
                 tools: Optional[List[MCPToolInfo]] = None):
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
        self._cancelled = False
        self._messages: List[Dict[str, Any]] = []

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            from openai import OpenAI
            client = OpenAI(**self._client_kwargs)

            # 按模型上下文窗口做摘要缓冲压缩（不限消息条数）
            self._messages = self._build_context(client)

            if self._tools:
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
            # 思考模型（DeepSeek-R1 / QwQ 等）的思考过程走 reasoning_content 字段
            rc = getattr(delta, 'reasoning_content', None)
            if rc:
                self.reasoning.emit(rc)
            if delta.content:
                full_text += delta.content
                self.chunk.emit(delta.content)
        self.finished_ok.emit(full_text)

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
            rc = getattr(msg, 'reasoning_content', None)
            if rc:
                self.reasoning.emit(rc)
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
                if not tool_info:
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
        self.chunk.emit(answer)
        self.finished_ok.emit(answer)


class ChatWindow(QWidget):
    """AI 对话独立窗口"""

    closed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("ChatWindow")
        self.setWindowTitle(f"{APP_NAME} - AI 对话")

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(720, 480)
        self.resize(920, 640)

        # 窗口状态（最大化/最小化，与翻译窗口一致）
        self._is_maximized = False
        self._is_minimized = False
        self._normal_geometry: Optional[QRect] = None

        self._config = get_config()
        self._store = get_chat_store()
        self._theme = get_theme()

        # 拖动状态
        self._is_dragging = False
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None

        # 边缘缩放状态（无框窗口拖拽边缘调整大小）
        self._resize_edge = 0
        self._resize_start_pos: Optional[QPoint] = None
        self._resize_start_geo: Optional[QRect] = None
        self._resize_cursor_child: Optional[QWidget] = None  # 被设过缩放光标的子控件
        self._last_edge_shape = Qt.CursorShape.ArrowCursor  # 上次同步的边缘光标形状
        self._sync_cursor_child: Optional[QWidget] = None  # 被轮询设过光标的子控件

        self._current_session_id: Optional[str] = None
        self._worker: Optional[ChatWorker] = None
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._reason_follow = True  # 思考框折叠时是否跟随到底
        self._main_follow = True  # 主消息区是否自动跟随到底


        self._setup_ui()
        self._apply_theme()
        self._applied_theme_signature = self._theme_signature()

        # 在 Windows 上启用任务栏最小化和 Win+方向键贴靠/最大化
        self._enable_windows_window_management()

        # 鼠标追踪：未按键时也响应移动，及时切换边缘缩放光标
        self.setMouseTracking(True)
        self._content_frame.setMouseTracking(True)
        self._title_bar.setMouseTracking(True)
        self._side_panel.setMouseTracking(True)
        # 子控件占据整个窗口，边缘按下/悬停事件到不了窗口自身，
        # 通过事件过滤器在内容容器（含全部后代）上拦截处理
        self._content_frame.installEventFilter(self)
        # 应用级鼠标移动监听：可选中气泡/列表等子控件会接受移动事件，
        # 窗口级 mouseMoveEvent 收不到，光标离开边缘区无法立刻复原；
        # 应用级过滤器先于任何子控件收到全部移动事件，可即时检查复原
        QApplication.instance().installEventFilter(self)

        # 气泡最大宽在渲染时按当时聊天区宽度定死，窗口变宽后防抖重排气泡
        self._last_render_width = 0
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(200)
        self._relayout_timer.timeout.connect(self._relayout_on_resize)

        # 流式刷新节流：chunk 先入缓冲，合并后最多约 25 次/秒刷新气泡，
        # 避免长回复时每个 chunk 都全量重排富文本导致卡死
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(40)
        self._flush_timer.timeout.connect(self._update_stream_display)

        # 边缘光标同步：可选中文本等子控件会接受鼠标移动事件，事件不再冒泡到
        # 窗口，窗口级 mouseMoveEvent 不触发，离开边缘后缩放光标迟迟不复原；
        # 轮询鼠标位置主动同步（与划词工具栏/翻译图标按钮同方案）
        self._cursor_check_timer = QTimer(self)
        self._cursor_check_timer.setInterval(100)
        self._cursor_check_timer.timeout.connect(self._sync_edge_cursor)
        self._cursor_check_timer.start()
        # 已取消但仍在跑的 worker：保持引用直到结束，防止 QThread 运行中被回收 abort
        self._zombie_workers: List[ChatWorker] = []

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

        self._minimize_btn = QPushButton("─")
        self._minimize_btn.setObjectName("chatMinimizeBtn")
        self._minimize_btn.setFixedSize(26, 26)
        self._minimize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._minimize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._minimize_btn.clicked.connect(self._on_minimize)
        title_layout.addWidget(self._minimize_btn)

        self._maximize_btn = QPushButton("□")
        self._maximize_btn.setObjectName("chatMaximizeBtn")
        self._maximize_btn.setFixedSize(26, 26)
        self._maximize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._maximize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._maximize_btn.clicked.connect(self._on_maximize)
        title_layout.addWidget(self._maximize_btn)

        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("chatCloseBtn")
        self._close_btn.setFixedSize(26, 26)
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
        self._mcp_menu = QMenu(self._mcp_btn)
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
        self._message_scroll = QScrollArea()
        self._message_scroll.setObjectName("messageView")
        self._message_scroll.setWidgetResizable(True)
        self._message_scroll.setFrameShape(QFrame.Shape.NoFrame)
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
        right.addWidget(self._message_scroll, 1)

        # 输入区
        input_bar = QHBoxLayout()
        input_bar.setSpacing(6)
        self._input_edit = QTextEdit()
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
        # 侧栏宽度变化后重排会话条目：标题按新宽度省略，避免超宽截断圆角
        self._splitter.splitterMoved.connect(self._reload_session_list)
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
        self._reasoning_color = text2
        # 思考气泡底色：主题色浅调（约 10% 不透明），与正文气泡区分
        self._reasoning_tint = _hex_to_rgba(accent, 26)
        # 侧栏条目文字色：条目透明底，按侧栏底色亮度选黑/白，避免深色背景黑字看不清
        self._session_text_color = _contrast_color(bg2)

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
            #chatMinimizeBtn, #chatMaximizeBtn {{
                background: transparent; color: {text2}; border: none;
                font-size: 12px; font-weight: bold; border-radius: 5px;
            }}
            #chatMinimizeBtn:hover, #chatMaximizeBtn:hover {{ background-color: {border}; color: {text1}; }}
            #chatCloseBtn {{
                background: transparent; color: {text2}; border: none;
                font-size: 16px; border-radius: 5px;
            }}
            #chatCloseBtn:hover {{ background-color: #e81123; color: #ffffff; }}
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
        self._session_list.setStyleSheet(f"""
            #sessionList {{
                background-color: transparent; border: none; color: {text1};
                font-size: {max(font_size - 2, 12)}px; outline: none;
            }}
            #sessionList::item {{
                padding: 0; border-radius: 8px; margin: 2px 1px;
            }}
            #sessionList::item:selected {{
                background: transparent; border: 1px solid {text2};
            }}
            #sessionList::item:hover:!selected {{
                background: transparent; border: 1px solid {border};
            }}
            #sessionRow {{ background: transparent; }}
            #sessionRowLabel {{ background: transparent; color: {self._session_text_color}; }}
            #sessionDelBtn {{
                background: transparent; border: none; border-radius: 5px;
            }}
            #sessionDelBtn:hover {{ background-color: {border}; }}
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
            #reasoningToggleBtn {{
                background-color: transparent; color: {text2};
                border: 1px solid {border}; border-radius: 10px;
                padding: 1px 10px; font-size: 11px;
            }}
            #reasoningToggleBtn:hover {{ color: {text1}; border-color: {accent}; }}
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
                background-color: {bg2}; color: {text1};
                border: 1px solid {border}; border-radius: 12px;
                padding: 8px 10px; font-size: {font_size}px;
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
        self._reload_session_list()
        if self._current_session_id is None:
            self._ensure_session()
        if self.isMinimized():
            # 从最小化恢复（任务栏/快捷键再次唤起）
            self._is_minimized = False
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self._bring_to_front()

    def _bring_to_front(self):
        """Win32：可靠抢占前台焦点。全局热键从其他进程（如 PyCharm）唤起时，
        仅 raise_/activateWindow 拿不到前台权限，窗口会闪一下又被原窗口盖回；
        AttachThreadInput + TOPMOST/NOTOPMOST 技巧可拉到最前且不保持置顶"""
        if sys.platform != 'win32':
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            foreground_tid = user32.GetWindowThreadProcessId(
                user32.GetForegroundWindow(), None)
            current_tid = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = False
            if foreground_tid and foreground_tid != current_tid:
                attached = user32.AttachThreadInput(current_tid, foreground_tid, True)
            SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)  # HWND_TOPMOST
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)  # HWND_NOTOPMOST
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            if attached:
                user32.AttachThreadInput(current_tid, foreground_tid, False)
        except Exception:
            pass

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

    def _on_close_clicked(self):
        self.hide()
        self.closed.emit()

    def hideEvent(self, event):
        # 隐藏前还原子控件光标，避免下次显示时残留缩放光标
        self._restore_sync_cursor_child()
        super().hideEvent(event)

    def _on_minimize(self):
        """最小化窗口"""
        self._is_minimized = True
        self.showMinimized()  # 使用系统最小化

    def _on_maximize(self):
        """最大化/还原窗口"""
        if self._is_maximized or self.isMaximized():
            # 还原
            if self.isMaximized():
                # 系统最大化（Win+↑）：由系统还原到原尺寸
                self.showNormal()
            elif self._normal_geometry:
                self.setGeometry(self._normal_geometry)
            self._is_maximized = False
            self._maximize_btn.setText("□")
        else:
            # 最大化
            self._normal_geometry = self.geometry()
            # 获取窗口当前所在的屏幕（而不是主屏幕）
            screen = QApplication.screenAt(self.geometry().center())
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen:
                self.setGeometry(screen.availableGeometry())
            self._is_maximized = True
            self._maximize_btn.setText("❐")

    def changeEvent(self, event):
        """同步系统窗口状态（Win+↑ 最大化 / Win+↓ 还原）与按钮图标"""
        if event.type() == event.Type.WindowStateChange:
            if self.isMaximized():
                self._is_maximized = True
                self._maximize_btn.setText("❐")
            elif self.isMinimized():
                pass
            elif self._is_maximized:
                self._is_maximized = False
                self._maximize_btn.setText("□")
            if not self.isMinimized():
                self._is_minimized = False
        super().changeEvent(event)

    def _enable_windows_window_management(self):
        """在 Windows 上启用系统窗口管理快捷键和任务栏最小化。"""
        try:
            if not sys.platform.startswith("win"):
                return

            import ctypes
            # 获取窗口句柄
            hwnd = int(self.winId())

            # 获取当前窗口样式
            GWL_STYLE = -16
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)

            # WS_THICKFRAME/WS_MAXIMIZEBOX 让 Windows 识别该无边框窗口可贴靠/最大化，
            # 因而支持 Win+方向键等系统窗口管理快捷键。
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            new_style = style | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU

            # 设置新样式
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)

            # 通知 Windows 重新计算非客户区样式，否则快捷键/贴靠状态可能不立即生效。
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            )
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 尺寸变化停止后（拖拽边缘/最大化）再重排，避免频繁重建气泡
        self._relayout_timer.start()

    def _relayout_on_resize(self):
        """窗口尺寸稳定后按新聊天区宽度重排气泡"""
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

    def closeEvent(self, event):
        """点系统关闭也仅隐藏，保留会话状态"""
        event.ignore()
        self.hide()
        self.closed.emit()

    # ------------------------------------------------------------------
    # 窗口拖动 / 边缘缩放
    # ------------------------------------------------------------------
    _EDGE_LEFT, _EDGE_RIGHT, _EDGE_TOP, _EDGE_BOTTOM = 1, 2, 4, 8
    _RESIZE_BORDER = 15  # 边缘命中区域（像素，与翻译窗口一致）

    def _edge_at(self, pos) -> int:
        """返回鼠标位置命中的边缘位组合（可为角）"""
        # 最大化状态下不允许边缘缩放（与系统最大化窗口一致）
        if self._is_maximized or self.isMaximized():
            return 0
        # 标题栏区域整体不参与边缘检测：标题栏内的最小化/最大化/关闭按钮
        # 上半部落在检测带内，若命中会把按钮点击误拦截成边缘缩放，导致按钮无法点击
        if self._title_bar.geometry().contains(int(pos.x()), int(pos.y())):
            return 0
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

    def _sync_edge_cursor(self):
        """轮询鼠标位置同步边缘缩放光标。可选中气泡/文本框会接受鼠标移动事件，
        事件不冒泡到窗口，窗口级 mouseMoveEvent 不触发，
        导致离开边缘后缩放光标残留；这里主动检查并复原"""
        if not self.isVisible() or self._resize_edge or self._is_dragging:
            return
        if QWidget.mouseGrabber() is not None:
            return  # 拖拽/选择过程中光标由抓取方管理
        gpos = QCursor.pos()
        if gpos is None:
            return
        pos = self.mapFromGlobal(gpos)
        if not self.rect().contains(pos):
            return  # 鼠标在窗口外：由 leaveEvent 负责复原
        shape = self._resize_cursor(self._edge_at(pos))
        if shape != self._last_edge_shape:
            self._last_edge_shape = shape
            self.setCursor(shape)
        child = self.childAt(pos)
        if shape == Qt.CursorShape.ArrowCursor or child is None or child is self:
            self._restore_sync_cursor_child()
            return
        if child is self._sync_cursor_child:
            return
        if child.testAttribute(Qt.WidgetAttribute.WA_SetCursor):
            self._restore_sync_cursor_child()
            return  # 按钮/输入框/滚动条等自带光标，不覆盖
        self._restore_sync_cursor_child()
        # 窗口级 setCursor 在鼠标停在子控件上时不一定刷新原生光标，
        # 直接设到鼠标下的子控件才能即时生效
        child.setCursor(shape)
        self._sync_cursor_child = child

    def _restore_sync_cursor_child(self):
        """还原被轮询改过光标的子控件"""
        if self._sync_cursor_child is not None:
            try:
                self._sync_cursor_child.unsetCursor()
            except RuntimeError:
                pass
            self._sync_cursor_child = None

    def _interactive_child_at(self, pos) -> bool:
        """窗口坐标 pos 下是否为交互控件（可选文本气泡 / 列表 / 滚动区 / 按钮 / 输入框）。
        这类控件上的按下交给控件自己处理，不拦截成边缘缩放，
        否则贴边的会话列表条目、气泡内边距等会被误拦成窗口缩放"""
        w = self._content_frame.childAt(pos)
        while w is not None and w is not self._content_frame:
            if isinstance(w, (QAbstractScrollArea, QAbstractButton, QTextEdit)):
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
            if edge:
                # 边缘/角落：进入缩放模式
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = self.geometry()
                self.setCursor(self._resize_cursor(edge))
            elif self._title_bar.geometry().contains(pos):
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
            # 悬停时切换边缘光标
            self.setCursor(self._resize_cursor(self._edge_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._is_dragging = False
        self._resize_edge = 0
        self._resize_start_geo = None
        if self._resize_cursor_child is not None:
            self._resize_cursor_child.unsetCursor()
            self._resize_cursor_child = None
        self._restore_sync_cursor_child()
        # 显式释放鼠标抓取，避免抓取卡死导致全局点击失效（仅在自己是抓取者时）
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.setCursor(self._resize_cursor(self._edge_at(event.position().toPoint())))
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """鼠标双击事件 - 双击标题栏切换最大化状态"""
        if event.button() == Qt.MouseButton.LeftButton and not self._resize_edge:
            pos = event.position().toPoint()
            # 双击标题栏任意位置切换最大化（按钮自身消费点击，不会到这里）
            if self._title_bar.geometry().contains(pos):
                self._on_maximize()
                return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        """鼠标离开窗口：复原默认箭头，避免缩放光标残留"""
        self._restore_sync_cursor_child()
        if self._resize_cursor_child is not None:
            self._resize_cursor_child.unsetCursor()
            self._resize_cursor_child = None
        if not self._resize_edge:
            self._last_edge_shape = Qt.CursorShape.ArrowCursor
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def eventFilter(self, obj, event):
        # 任何鼠标移动（无论被哪个子控件接受）都立即检查是否离开边缘缩放区：
        # 在区内→同步缩放光标，离开→即刻复原，不等 100ms 轮询（轮询作兜底）
        if event.type() == event.Type.MouseMove:
            if self.isVisible() and not self._resize_edge and not self._is_dragging:
                self._sync_edge_cursor()
            return False
        if (isinstance(obj, QWidget) and obj.objectName() == "sessionRow"
                and event.type() == event.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            sid = obj.property("sid")
            if sid:
                self._select_session(sid)
            return False
        is_child = (
            isinstance(obj, QWidget)
            and obj is not self._input_edit
            and not isinstance(obj, QSplitterHandle)
            and self._content_frame.isAncestorOf(obj)
        )

        # 子控件（内容容器及其后代）上的边缘按下：子控件占满窗口，
        # 不拦截的话边缘按下事件到不了窗口，缩放无法启动。
        # 按钮/滚动条类控件绝不拦截：按钮自身会处理按下（如发送按钮贴右边/下边、
        # 标题栏按钮在顶部检测带内），消息区滚动条贴右边缘，拦截会导致无法点击/滚动
        if (
            is_child
            and not isinstance(obj, (QAbstractButton, QAbstractSlider))
            and event.type() == event.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            pos = self.mapFromGlobal(obj.mapToGlobal(event.position().toPoint()))
            edge = self._edge_at(pos)
            if edge and not self._interactive_child_at(pos):
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = self.geometry()
                self.setCursor(self._resize_cursor(edge))
                try:
                    # 拖出控件/窗口外仍能收到移动与释放；
                    # 抓取失败（如弹窗正持有抓取）则放弃本次缩放，避免事件被吞后无后续释放
                    self.grabMouse()
                except Exception:
                    self._resize_edge = 0
                    self._resize_start_geo = None
                    self.setCursor(Qt.CursorShape.ArrowCursor)
                    return False
                return True

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
        self._session_list.clear()
        fm = self._session_list.fontMetrics()
        # 标题按侧栏当前宽度省略：条目超宽会撑出视口，选中态圆角被截断
        max_title_w = max(self._session_list.viewport().width() - 60, 60)
        for s in self._store.list_sessions():
            title = (s.get('title') or "新对话").strip() or "新对话"
            title = fm.elidedText(title, Qt.TextElideMode.ElideRight, max_title_w)
            try:
                when = datetime.fromtimestamp(s.get('updated_at', 0) / 1000).strftime('%m-%d %H:%M')
            except Exception:
                when = ""
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, s['id'])
            row = QWidget()
            row.setObjectName("sessionRow")
            row.setProperty("sid", s['id'])
            row.installEventFilter(self)  # 行内点击（控件覆盖 item）→ 切换会话
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 8, 6, 8)
            rl.setSpacing(4)
            label = QLabel(f"{title}\n{when}")
            label.setObjectName("sessionRowLabel")
            rl.addWidget(label, 1)
            del_btn = QPushButton()
            del_btn.setObjectName("sessionDelBtn")
            del_btn.setFixedSize(20, 20)
            # 绘制图标替代 emoji：颜色跟主题走，悬停走 QIcon Active 模式变红
            del_btn.setIcon(_trash_icon((getattr(self, '_theme', None) or {}).get('text_secondary', '#999999')))
            del_btn.setIconSize(QSize(14, 14))
            del_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            del_btn.setToolTip("删除对话")
            del_btn.clicked.connect(
                lambda checked=False, sid=s['id']: self._delete_session(sid))
            rl.addWidget(del_btn, 0, Qt.AlignmentFlag.AlignVCenter)
            self._session_list.addItem(item)
            self._session_list.setItemWidget(item, row)
            item.setSizeHint(QSize(0, row.sizeHint().height()))
            if s['id'] == current_sid:
                item.setSelected(True)

    def _on_new_session(self, select: bool = True):
        session = self._store.create_session()
        self._reload_session_list()
        if select:
            self._select_session(session['id'])

    def _on_session_item_clicked(self, item: QListWidgetItem):
        sid = item.data(Qt.ItemDataRole.UserRole)
        if sid and sid != self._current_session_id:
            self._select_session(sid)

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
            old_title = (self._store.get_session(sid) or {}).get('title', '')
            new_title, ok = QInputDialog.getText(self, "重命名对话", "新名称:", text=old_title)
            if ok and new_title.strip():
                self._store.rename_session(sid, new_title)
                self._reload_session_list()
        elif chosen == delete_act:
            self._delete_session(sid)

    def _delete_session(self, sid: str):
        """删除会话（右键菜单与条目删除按钮共用）"""
        self._store.delete_session(sid)
        if sid == self._current_session_id:
            self._current_session_id = None
        self._reload_session_list()
        self._ensure_session()

    def _on_clear_context(self):
        if self._current_session_id:
            self._cancel_worker()
            self._store.clear_messages(self._current_session_id)
            self._render_messages()

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def _refresh_skills(self):
        self._skill_menu.clear()
        manager = get_skill_manager()
        skills = manager.load_skills()

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
        enable_act.setChecked(self._config.get('mcp.enabled', True))
        enable_act.triggered.connect(self._on_toggle_mcp_enabled)

        self._mcp_menu.addSeparator()

        if not manager.available:
            self._mcp_menu.addAction("未安装 mcp 包（pip install mcp）").setEnabled(False)
        else:
            statuses = manager.server_statuses()
            if not statuses:
                self._mcp_menu.addAction("未配置 MCP 服务器").setEnabled(False)
            for st in statuses:
                if st.connected:
                    label = f"✓ {st.name}（{st.tool_count} 个工具）"
                else:
                    label = f"✗ {st.name}：{st.error[:30] or '连接失败'}"
                self._mcp_menu.addAction(label).setEnabled(False)

        self._mcp_menu.addSeparator()
        reconnect_act = self._mcp_menu.addAction("重新连接")
        reconnect_act.triggered.connect(self._on_mcp_reconnect)
        open_cfg_act = self._mcp_menu.addAction("打开配置文件…")
        open_cfg_act.triggered.connect(
            lambda: os.startfile(str(manager.config_path))
        )

        tools = manager.list_tools()
        self._mcp_btn.setText(f"MCP（{len(tools)}）" if tools else "MCP")

    def _on_toggle_mcp_enabled(self, checked: bool):
        self._config.set('mcp.enabled', checked)
        self._config.save()

    def _on_mcp_reconnect(self):
        manager = get_mcp_manager()
        manager.start()
        manager.reconnect()
        QTimer.singleShot(1500, self._refresh_mcp_menu)

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

        for m in messages:
            role = m.get('role')
            content = m.get('content', '')
            if role == 'assistant' and not content and not (m.get('reasoning') or ''):
                continue  # 流式占位消息（完成时原地填充），不渲染空气泡
            if role in ('user', 'assistant'):
                row, _ = self._make_bubble(
                    role, content, reasoning=m.get('reasoning') or '', usable=usable)
                self._message_layout.addWidget(row)

        if streaming_extra or streaming_reasoning:
            content_html = (_format_content(streaming_extra) if streaming_extra else "") + "<br>▍"
            row, label = self._make_bubble(
                'assistant', content_html, reasoning=streaming_reasoning,
                html_ready=True, usable=usable, reasoning_plain=reasoning_plain)
            # 流式中高频更新：禁掉文本选择（可选中富文本 QLabel 快速 setText
            # 是 Qt 易崩溃路径），结束后重渲染会恢复可选
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
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
            toggle = row.findChild(QPushButton, "reasoningToggleBtn")
            if toggle is not None:
                # 思考中禁止展开：内容仍在增长，展开态会随刷新剧烈抖动；
                # 结束后整体重建，新按钮自动恢复可用
                toggle.setEnabled(False)
                toggle.setToolTip("思考完成后可展开查看")
            self._message_layout.addWidget(row)
            self._stream_row = row

        self._message_layout.addStretch()
        if stick:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _make_bubble(self, role: str, content: str, reasoning: str = "",
                     html_ready: bool = False, usable: int = 400,
                     reasoning_plain: bool = False):
        """创建单条消息气泡（返回行容器与正文 QLabel）；
        带思考过程时思考块作为独立气泡叠在正文气泡上方"""
        text_html = content if html_ready else _format_content(content)
        label = QLabel(text_html)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setMinimumWidth(40)
        # 撑满聊天区可用宽度（不加 maxWidth 会按未换行宽度撑大容器 → 溢出截断）
        label.setMaximumWidth(usable)

        row = QWidget()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)  # 思考气泡与正文气泡的间距

        if reasoning.strip() and role == 'assistant':
            # 思考过程独立成气泡，正文气泡紧随其下
            lay.addWidget(self._make_reasoning_bubble(reasoning, usable, reasoning_plain))
        label.setObjectName("bubbleUser" if role == 'user' else "bubbleAssistant")
        lay.addWidget(label)  # 占满整行，与聊天区同宽
        return row, label

    def _make_reasoning_bubble(self, reasoning: str, usable: int, plain: bool = False) -> QWidget:
        """思考过程独立气泡：浅底 + 虚线边框，与正文气泡视觉区分"""
        bubble = QWidget()
        bubble.setObjectName("bubbleReasoning")
        bubble.setMaximumWidth(usable)
        bl = QVBoxLayout(bubble)
        # QWidget 容器的 QSS padding 不影响子控件布局，须用布局边距代替，
        # 否则「展开」按钮会贴住气泡角落、凸出圆角弧外
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(0)
        bl.addWidget(self._make_reasoning_block(reasoning, plain))
        return bubble

    def _make_reasoning_block(self, reasoning: str, plain: bool = False) -> QWidget:
        """思考过程块：标题 + 展开/收起按钮 + 默认 6 行高的可滚动内容区"""
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
        toggle = QPushButton("展开")
        toggle.setObjectName("reasoningToggleBtn")
        toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        toggle.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        header.addWidget(toggle)
        vl.addLayout(header)

        scroll = QScrollArea()
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
            rlabel.setText(_format_content(reasoning))
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

        # 折叠高度 = 6 行文字
        collapsed_h = rlabel.fontMetrics().lineSpacing() * 6 + 6
        scroll.setFixedHeight(collapsed_h)

        def _on_toggle():
            if toggle.text() == "展开":
                scroll.setMinimumHeight(0)
                scroll.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX：完全展开
                toggle.setText("收起")
            else:
                scroll.setFixedHeight(collapsed_h)
                toggle.setText("展开")

        toggle.clicked.connect(_on_toggle)
        return block

    def _scroll_to_bottom(self):
        # 滚动到底。不可 adjustSize：widgetResizable 下容器高度由滚动区管理，
        # 手动改高会与布局互相拉扯，流式中每帧震荡造成文字抖动；
        # 布局滞后一帧的范围变化由 rangeChanged 同帧补偿。
        # 先 activate 使布局定稿：富文本气泡高度需一轮布局才算出，
        # 未定稿时 maximum() 仍为旧值（重建后为 0），setValue 不生效
        self._message_container.layout().activate()
        bar = self._message_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _finalize_stream_row(self):
        """把流式气泡原地替换为完成气泡，其余消息不动。
        全量重建会瞬间清空布局（滚动范围归零、value 回 0），
        造成视觉上先闪到顶部再跳到底部；原地替换只换最后一行，
        滚动范围连续无闪动。上方消息不受影响，上滚用户的位置也天然保持。
        返回是否完成原地替换（False 表示退回了全量重建）"""
        session = self._store.get_session(self._current_session_id) \
            if self._current_session_id else None
        messages = (session or {}).get('messages', [])
        last = messages[-1] if messages else None
        old_row = self._stream_row
        idx = self._message_layout.indexOf(old_row) if old_row is not None else -1
        if idx < 0 or last is None or last.get('role') != 'assistant':
            self._render_messages()  # 结构不符时退回全量重建
            return False
        vp_w = self._message_scroll.viewport().width()
        margins = self._message_layout.contentsMargins()
        usable = max(vp_w - margins.left() - margins.right(), 200)
        row, _ = self._make_bubble(
            'assistant', last.get('content', ''),
            reasoning=last.get('reasoning') or '', usable=usable)
        self._message_layout.insertWidget(idx, row)
        self._message_layout.removeWidget(old_row)
        old_row.deleteLater()
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
        bar.setValue(bar.maximum())

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
        # assistant 占位消息：完成后 update_last_assistant_message 覆盖这最后一条。
        # 无占位时多轮会话末尾是 user，覆盖会追加到末尾或误改更早的 assistant，
        # 且完成渲染的结构校验失败退回全量重建，滚动位置失控
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
        if self._config.get('mcp.enabled', True) and manager.available:
            tools = manager.list_tools()

        # 独立 API 配置：勾选"与翻译共用"时走 translator 段，否则走 chat 段
        if self._config.get('chat.use_shared_api', True):
            client_kwargs = {
                'api_key': self._config.get('translator.api_key', ''),
                'base_url': self._config.get('translator.base_url', ''),
                'timeout': self._config.get('translator.timeout', 60),
            }
            model = self._config.get('translator.model', '')
        else:
            client_kwargs = {
                'api_key': self._config.get('chat.api_key', ''),
                'base_url': self._config.get('chat.base_url', ''),
                'timeout': self._config.get('chat.timeout', 60),
            }
            model = self._config.get('chat.model', '')

        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._reason_follow = True
        self._main_follow = True
        self._send_btn.setEnabled(False)
        self._render_messages(streaming_extra="…", force_scroll=True)

        self._worker = ChatWorker(sid, system_prompt, history, summary, summary_count,
                                  model, client_kwargs, context_limit, tools)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.reasoning.connect(self._on_reasoning)
        self._worker.tool_info.connect(self._on_tool_info)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.context_compressed.connect(self._on_context_compressed)
        self._worker.start()

    def _on_context_compressed(self, session_id: str, summary: str, covered: int):
        """后台线程完成历史压缩后，持久滚动摘要与覆盖条数"""
        self._store.set_session_summary(session_id, summary, covered)

    def _update_stream_display(self, body_extra: str = ""):
        """按当前缓冲（思考 + 正文）刷新流式气泡"""
        body = self._stream_buffer + body_extra
        need_reasoning = bool(self._reasoning_buffer.strip())
        has_reason_ui = self._stream_reason_label is not None
        if self._stream_label is not None and (not need_reasoning or has_reason_ui):
            # 只更新流式气泡，不重建全部消息（减少重绘与滚动跳动）
            stick = self._near_bottom()
            body_html = (_format_content(body) if body else "") + "<br>▍"
            if self._stream_label.text() != body_html:
                self._stream_label.setText(body_html)
            if need_reasoning:
                # 标签为纯文本格式：直接写原始缓冲，免转义与解析
                self._stream_reason_label.setText(self._reasoning_buffer)
                rs = self._stream_reason_scroll
                if rs.minimumHeight() == rs.maximumHeight() and self._reason_follow:
                    # 折叠且用户未上滚：跟随到最新
                    # （范围滞后一帧由 rangeChanged 同帧补偿，见 _on_reason_range_changed）
                    rbar = rs.verticalScrollBar()
                    rbar.setValue(rbar.maximum())
            if stick:
                QTimer.singleShot(0, self._scroll_to_bottom)
        else:
            # 思考首次到达等结构变化场景：重建气泡
            self._render_messages(
                streaming_extra=body,
                streaming_reasoning=self._reasoning_buffer,
                reasoning_plain=True)

    def _on_reason_range_changed(self, _min: int, maxv: int):
        """思考框内容长高导致滚动范围变化：绘制前同帧滚到底，避免末行闪烁"""
        rs = self._stream_reason_scroll
        if rs is None or self.sender() is not rs.verticalScrollBar():
            return  # 上一代已重建的旧滚动条
        if not getattr(self, '_reason_follow', True):
            return
        if not (self._worker and self._worker.isRunning()):
            return
        if rs.minimumHeight() != rs.maximumHeight():
            return  # 展开态不自动跟随
        rs.verticalScrollBar().setValue(maxv)

    def _on_reason_scroll_moved(self, value: int):
        """用户手动滚离底部时暂停跟随，滚回底部恢复"""
        rs = self._stream_reason_scroll
        if rs is None or self.sender() is not rs.verticalScrollBar():
            return
        self._reason_follow = (rs.verticalScrollBar().maximum() - value) < 40

    def _schedule_flush(self):
        """合并高频 chunk：计时器未激活时安排一次刷新，期间的 chunk 一并呈现"""
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _on_reasoning(self, chunk: str):
        self._reasoning_buffer += chunk
        self._schedule_flush()

    def _on_chunk(self, chunk: str):
        self._stream_buffer += chunk
        self._schedule_flush()

    def _on_tool_info(self, info: str):
        log_info(info)
        extra = f"\n\n*{info}*" if self._stream_buffer else f"*{info}*"
        self._update_stream_display(body_extra=extra)

    def _on_finished(self, full_text: str):
        self._flush_timer.stop()
        _bar = self._message_scroll.verticalScrollBar()
        was_at_bottom = self._main_follow or _bar.value() >= _bar.maximum() - 30
        had_reasoning = bool(self._reasoning_buffer.strip())
        if self._current_session_id and full_text:
            # 纯空白思考内容视为无思考（部分非思考模型会回传空白 reasoning_content）
            self._store.update_last_assistant_message(
                self._current_session_id, full_text,
                reasoning=self._reasoning_buffer if had_reasoning else '')
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._send_btn.setEnabled(True)
        self._reload_session_list()
        # 原地把流式行换成完成气泡（不全量重建）：重建会瞬间把滚动范围
        # 归零、value 回 0，视觉上先闪到顶部再跳回底部
        swapped = self._finalize_stream_row()
        if was_at_bottom:
            if swapped:
                self._scroll_to_bottom()
                # 完成气泡可能比流式气泡更高，滚动范围在替换后异步增长，
                # 落定后再补滚一次保持贴底
                QTimer.singleShot(120, self._scroll_to_bottom)
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
                              (worker.reasoning, self._on_reasoning),
                              (worker.tool_info, self._on_tool_info),
                              (worker.finished_ok, self._on_finished),
                              (worker.failed, self._on_failed),
                              (worker.context_compressed,
                               self._on_context_compressed)):
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


# 全局实例
_chat_window_instance: Optional[ChatWindow] = None


def get_chat_window() -> ChatWindow:
    global _chat_window_instance
    if _chat_window_instance is None:
        _chat_window_instance = ChatWindow()
    return _chat_window_instance
