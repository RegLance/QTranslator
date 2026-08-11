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

from PyQt6.QtCore import Qt, QPoint, QRect, QThread, pyqtSignal, QTimer, QEvent
from PyQt6.QtGui import QCursor, QIcon, QPainter, QPen, QColor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextBrowser, QTextEdit, QMenu, QFrame,
    QToolButton, QInputDialog, QSplitter, QSplitterHandle, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QMessageBox, QCheckBox,
    QScrollBar,
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


def _format_content(text: str) -> str:
    """极简 Markdown → HTML：转义 + ```代码块 + 换行"""
    segments = text.split('```')
    parts = []
    for idx, seg in enumerate(segments):
        if idx % 2 == 0:
            parts.append(html.escape(seg).replace('\n', '<br>'))
        else:
            seg2 = seg.strip('\n')
            lines = seg2.split('\n')
            # 去掉首行语言标记（如 ```python）
            if len(lines) > 1 and len(lines[0]) <= 20 and ' ' not in lines[0].strip():
                lines = lines[1:]
            parts.append(f'<pre>{html.escape(chr(10).join(lines))}</pre>')
    return ''.join(parts)


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
                self.chunk.emit(delta.content)
        self.finished_ok.emit(full_text, self._reasoning_full)

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
        self.chunk.emit(answer)
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

        self._setup_ui()
        self._apply_theme()
        self._applied_theme_signature = self._theme_signature()

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

        # 最小化 / 最大化按钮（与翻译窗口同款）
        self._minimize_btn = QPushButton("─")
        self._minimize_btn.setObjectName("chatMinimizeBtn")
        self._minimize_btn.setFixedSize(26, 26)
        self._minimize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._minimize_btn.setToolTip("最小化")
        self._minimize_btn.clicked.connect(self._on_minimize_clicked)
        title_layout.addWidget(self._minimize_btn)

        self._maximize_btn = QPushButton("□")
        self._maximize_btn.setObjectName("chatMaximizeBtn")
        self._maximize_btn.setFixedSize(26, 26)
        self._maximize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._maximize_btn.setToolTip("最大化 / 还原")
        self._maximize_btn.clicked.connect(self._toggle_maximize)
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

        # 消息区
        self._message_view = QTextBrowser()
        self._message_view.setObjectName("messageView")
        self._message_view.setOpenExternalLinks(True)
        right.addWidget(self._message_view, 1)

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
                font-size: 14px; border-radius: 5px;
            }}
            #chatMinimizeBtn:hover, #chatMaximizeBtn:hover {{
                background-color: {accent}; color: #ffffff;
            }}
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
        self._message_view.setStyleSheet(f"""
            #messageView {{
                background-color: {bg}; color: {text1}; border: none;
                font-size: {font_size}px;
            }}
            #messageView QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 2px;
            }}
            #messageView QScrollBar::handle:vertical {{
                background: {border}; border-radius: 4px; min-height: 30px;
            }}
            #messageView QScrollBar::handle:vertical:hover {{ background: {text2}; }}
            #messageView QScrollBar::add-line:vertical, #messageView QScrollBar::sub-line:vertical {{ height: 0; }}
            #messageView QScrollBar::add-page:vertical, #messageView QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)
        self._message_view.document().setDefaultStyleSheet(f"""
            body {{ color: {text1}; font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
                    background-color: {bg}; }}
            td.user {{ background-color: {accent}; color: #ffffff;
                       border-radius: 12px; padding: 8px 12px; margin: 6px 0;
                       text-align: left; }}
            .row-assistant {{ text-align: left; margin: 8px 0; }}
            .role-tag {{ color: {accent}; font-size: 11px; font-weight: 700;
                         letter-spacing: 1px; }}
            .assistant {{ background-color: {bg2}; color: {text1};
                          border: 1px solid {border};
                          border-radius: 12px; padding: 8px 12px; margin-top: 2px; }}
            .info {{ color: {text2}; font-size: 12px; margin: 4px 0; }}
            details.reasoning {{ background-color: {bg2}; color: {text2};
                                 border: 1px solid {border}; border-radius: 10px;
                                 margin: 0 0 4px 0; padding: 6px 10px; font-size: 12px; }}
            details.reasoning summary {{ color: {text2}; font-weight: 600; }}
            .reasoning-body {{ margin-top: 6px; max-height: 150px; }}
            .empty-wrap {{ text-align: center; margin-top: 90px; }}
            .empty-title {{ color: {text1}; font-size: 20px; font-weight: 700;
                            margin-bottom: 8px; }}
            .empty-hint {{ color: {text2}; font-size: 13px; }}
            pre {{ background-color: {border}; padding: 8px; border-radius: 6px;
                   white-space: pre-wrap; font-family: Consolas, monospace; font-size: 13px; }}
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
        """设置窗口图标（任务栏图标），与翻译窗口一致"""
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

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
            # 从最小化唤醒：先还原，否则窗口仍缩在任务栏
            self.showNormal()
        self.show()
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
        self._is_dragging = False
        self._resize_edge = 0
        self._resize_start_geo = None
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
            and event.type() == event.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
            and not isinstance(obj, QScrollBar)  # 滚动条贴边，拖动不能被误判成缩放
        ):
            pos = self.mapFromGlobal(obj.mapToGlobal(event.position().toPoint()))
            edge = self._edge_at(pos)
            if edge and not self._is_maximized:
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = self.geometry()
                self.setCursor(self._resize_cursor(edge))
                self.grabMouse()  # 拖出控件/窗口外仍能收到移动与释放
                return True

        # 悬停同步缩放光标；离开边缘立即还原（行为同翻译窗口）
        if is_hover_target and event.type() == event.Type.MouseMove and not self._resize_edge:
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
    def _render_messages(self, streaming_extra: str = ""):
        session = self._store.get_session(self._current_session_id) if self._current_session_id else None
        messages = (session or {}).get('messages', [])

        parts = []
        if not messages and not streaming_extra:
            parts.append(
                '<div class="empty-wrap"><div class="empty-title">👋 开始对话</div>'
                '<div class="empty-hint">直接输入问题，或划词后从工具栏选择「AI 对话」，'
                '选中的内容会自动带入这里。</div></div>'
            )

        for m in messages:
            role = m.get('role')
            content = m.get('content', '')
            if role == 'user':
                parts.append(
                    '<table width="100%"><tr><td width="20%"></td>'
                    f'<td class="user">{_format_content(content)}</td></tr></table>'
                )
            elif role == 'assistant':
                # 空 assistant 是发送时的占位消息，不渲染空气泡
                if not (content or '').strip():
                    continue
                block = self._render_assistant_block(content, m.get('reasoning', ''))
                parts.append(
                    f'<div class="row-assistant"><span class="role-tag">AI</span>{block}</div>'
                )

        if streaming_extra:
            block = self._render_assistant_block(streaming_extra, self._reasoning_buffer, streaming=True)
            parts.append(
                f'<div class="row-assistant"><span class="role-tag">AI</span>{block}<br>▍</div>'
            )

        self._message_view.setHtml(''.join(parts))
        # 滚动到底部
        bar = self._message_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _render_assistant_block(self, content: str, reasoning: str = "", streaming: bool = False) -> str:
        """助手消息 HTML：思考框（有实际思考文字才显示，默认折叠）+ 正文"""
        parts = []
        reasoning = (reasoning or '').strip()
        if reasoning:
            open_attr = ' open' if streaming else ''
            parts.append(
                f'<details class="reasoning"{open_attr}><summary>💭 思考过程</summary>'
                f'<div class="reasoning-body">{_format_content(reasoning)}</div></details>'
            )
        parts.append(f'<div class="assistant">{_format_content(content)}</div>')
        return ''.join(parts)

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
        if self._config.get('mcp.enabled', True) and manager.available:
            tools = manager.list_tools()
            # 停用的工具不注入给模型（在 MCP 菜单中按工具勾选管理）
            _disabled_tools = set(self._config.get('mcp.disabled_tools', []) or [])
            if _disabled_tools:
                tools = [t for t in tools
                         if f"{t.server}/{t.name}" not in _disabled_tools]

        # 技能本地执行工具（存在技能时才注册；脚本执行需用户确认）
        skill_tools = None
        try:
            if get_skill_manager().load_skills():
                skill_tools = get_skill_local_tools(confirm=self._skill_confirm,
                                                    trusted=self._trusted_skills)
        except Exception as e:
            log_error(f"加载技能本地工具失败: {e}")

        client_kwargs = {
            'api_key': self._config.get('translator.api_key', ''),
            'base_url': self._config.get('translator.base_url', ''),
            'timeout': self._config.get('translator.timeout', 60),
        }
        model = self._config.get('translator.model', '')

        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._send_btn.setEnabled(False)
        self._render_messages(streaming_extra="…")

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
        self._render_messages(streaming_extra=self._stream_buffer)

    def _on_reasoning_chunk(self, chunk: str):
        self._reasoning_buffer += chunk
        # 思考进行中正文未到：思考框先行展示（正文区显示等待光标）
        self._render_messages(streaming_extra=self._stream_buffer or "…")

    def _on_tool_info(self, info: str):
        log_info(info)
        self._render_messages(streaming_extra=(self._stream_buffer + f"\n\n*{info}*" if self._stream_buffer else f"*{info}*"))

    def _on_finished(self, full_text: str, reasoning: str = ""):
        if self._current_session_id and full_text:
            # 覆盖发送时追加的空 assistant 占位；思考内容纯空白则不落库
            reasoning = (reasoning or '').strip()
            self._store.update_last_assistant_message(
                self._current_session_id, full_text, reasoning)
        elif self._current_session_id:
            # 无正文返回：清理占位，不残留空消息
            self._store.remove_trailing_empty_assistant(self._current_session_id)
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._send_btn.setEnabled(True)
        self._reload_session_list()
        self._render_messages()
        # 富文本布局落定后补滚一次，确保严格贴底
        QTimer.singleShot(120, self._scroll_to_bottom)

    def _on_failed(self, error: str):
        if self._current_session_id:
            # 请求失败：清理空 assistant 占位
            self._store.remove_trailing_empty_assistant(self._current_session_id)
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        self._send_btn.setEnabled(True)
        self._render_messages(streaming_extra=f"[请求失败] {error}")

    def _scroll_to_bottom(self):
        bar = self._message_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _cancel_worker(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
            self._worker = None
            self._send_btn.setEnabled(True)
            # 取消请求：清理空 assistant 占位与流式缓冲
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
