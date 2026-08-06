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

from PyQt6.QtCore import Qt, QPoint, QRect, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextBrowser, QTextEdit, QMenu, QFrame,
    QToolButton, QInputDialog, QSplitter, QSplitterHandle,
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
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_text += content
                self.chunk.emit(content)
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
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(720, 480)
        self.resize(920, 640)

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

        self._current_session_id: Optional[str] = None
        self._worker: Optional[ChatWorker] = None
        self._stream_buffer = ""

        self._setup_ui()
        self._apply_theme()
        self._applied_theme_signature = self._theme_signature()

        # 鼠标追踪：未按键时也响应移动，及时切换边缘缩放光标
        self.setMouseTracking(True)
        self._content_frame.setMouseTracking(True)
        self._title_bar.setMouseTracking(True)
        self._side_panel.setMouseTracking(True)
        # 子控件占据整个窗口，边缘按下/悬停事件到不了窗口自身，
        # 通过事件过滤器在内容容器（含全部后代）上拦截处理
        self._content_frame.installEventFilter(self)

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
                padding: 8px 10px; border-radius: 8px; margin: 1px 2px;
            }}
            #sessionList::item:selected {{ background-color: {accent}; color: #ffffff; }}
            #sessionList::item:hover:!selected {{ background-color: {border}; }}
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
        self.show()
        self.raise_()
        self.activateWindow()

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
        self.setCursor(self._resize_cursor(self._edge_at(event.position().toPoint())))
        super().mouseReleaseEvent(event)

    def eventFilter(self, obj, event):
        is_child = (
            isinstance(obj, QWidget)
            and obj is not self._input_edit
            and not isinstance(obj, QSplitterHandle)
            and self._content_frame.isAncestorOf(obj)
        )

        # 子控件（内容容器及其后代）上的边缘按下：子控件占满窗口，
        # 不拦截的话边缘按下事件到不了窗口，缩放无法启动
        if (
            is_child
            and event.type() == event.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            pos = self.mapFromGlobal(obj.mapToGlobal(event.position().toPoint()))
            edge = self._edge_at(pos)
            if edge:
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = self.geometry()
                self.setCursor(self._resize_cursor(edge))
                self.grabMouse()  # 拖出控件/窗口外仍能收到移动与释放
                return True

        # 未按键时在子控件上悬停也同步缩放光标（不覆盖按钮等非箭头光标）
        if is_child and event.type() == event.Type.MouseMove and not self._resize_edge:
            pos = self.mapFromGlobal(obj.mapToGlobal(event.position().toPoint()))
            edge = self._edge_at(pos)
            if edge:
                cursor = self._resize_cursor(edge)
                self.setCursor(cursor)
                obj.setCursor(cursor)
                self._resize_cursor_child = obj
            elif (
                self._resize_cursor_child is not None
                and self._resize_cursor_child.cursor().shape() != Qt.CursorShape.ArrowCursor
            ):
                # 离开边缘：还原被临时改过光标的子控件
                self._resize_cursor_child.unsetCursor()
                self._resize_cursor_child = None
                self.setCursor(Qt.CursorShape.ArrowCursor)

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
        for s in self._store.list_sessions():
            title = (s.get('title') or "新对话").strip() or "新对话"
            if len(title) > 18:
                title = title[:18] + "…"
            try:
                when = datetime.fromtimestamp(s.get('updated_at', 0) / 1000).strftime('%m-%d %H:%M')
            except Exception:
                when = ""
            item = QListWidgetItem(f"{title}\n{when}")
            item.setData(Qt.ItemDataRole.UserRole, s['id'])
            self._session_list.addItem(item)
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
            new_title, ok = QInputDialog.getText(self, "重命名对话", "新名称:", text=item.text())
            if ok and new_title.strip():
                self._store.rename_session(sid, new_title)
                self._reload_session_list()
        elif chosen == delete_act:
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
                parts.append(
                    f'<div class="row-assistant"><span class="role-tag">AI</span>'
                    f'<div class="assistant">{_format_content(content)}</div></div>'
                )

        if streaming_extra:
            parts.append(
                f'<div class="row-assistant"><span class="role-tag">AI</span>'
                f'<div class="assistant">{_format_content(streaming_extra)}<br>▍</div></div>'
            )

        self._message_view.setHtml(''.join(parts))
        # 滚动到底部
        bar = self._message_view.verticalScrollBar()
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

        client_kwargs = {
            'api_key': self._config.get('translator.api_key', ''),
            'base_url': self._config.get('translator.base_url', ''),
            'timeout': self._config.get('translator.timeout', 60),
        }
        model = self._config.get('translator.model', '')

        self._stream_buffer = ""
        self._send_btn.setEnabled(False)
        self._render_messages(streaming_extra="…")

        self._worker = ChatWorker(sid, system_prompt, history, summary, summary_count,
                                  model, client_kwargs, context_limit, tools)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.tool_info.connect(self._on_tool_info)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.context_compressed.connect(self._on_context_compressed)
        self._worker.start()

    def _on_context_compressed(self, session_id: str, summary: str, covered: int):
        """后台线程完成历史压缩后，持久滚动摘要与覆盖条数"""
        self._store.set_session_summary(session_id, summary, covered)

    def _on_chunk(self, chunk: str):
        self._stream_buffer += chunk
        self._render_messages(streaming_extra=self._stream_buffer)

    def _on_tool_info(self, info: str):
        log_info(info)
        self._render_messages(streaming_extra=(self._stream_buffer + f"\n\n*{info}*" if self._stream_buffer else f"*{info}*"))

    def _on_finished(self, full_text: str):
        if self._current_session_id and full_text:
            self._store.update_last_assistant_message(self._current_session_id, full_text)
        self._stream_buffer = ""
        self._send_btn.setEnabled(True)
        self._reload_session_list()
        self._render_messages()

    def _on_failed(self, error: str):
        self._stream_buffer = ""
        self._send_btn.setEnabled(True)
        self._render_messages(streaming_extra=f"[请求失败] {error}")

    def _cancel_worker(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
            self._worker = None
            self._send_btn.setEnabled(True)


# 全局实例
_chat_window_instance: Optional[ChatWindow] = None


def get_chat_window() -> ChatWindow:
    global _chat_window_instance
    if _chat_window_instance is None:
        _chat_window_instance = ChatWindow()
    return _chat_window_instance
