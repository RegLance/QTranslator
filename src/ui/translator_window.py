"""独立翻译窗口模块 - QTranslator（无边框风格，支持主题切换、纯文本显示）"""
import sys
from typing import Optional
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QComboBox, QFrame,
    QGraphicsDropShadowEffect, QApplication, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QPointF, QTimer
from PyQt6.QtGui import QColor, QCursor, QMouseEvent, QKeySequence, QIcon, QFont, QPixmap, QPainter, QPen

try:
    from ..utils.theme import get_theme, get_scrollbar_style, get_splitter_style, get_menu_style, get_combobox_style, get_hidden_scrollbar_style
    from ..config import get_config
    from ..utils.tts import get_tts
except ImportError:
    from src.utils.theme import get_theme, get_scrollbar_style, get_splitter_style, get_menu_style, get_combobox_style, get_hidden_scrollbar_style
    from src.config import get_config
    from src.utils.tts import get_tts


class StreamingTranslationWorker(QThread):
    """流式翻译工作线程"""

    chunk_received = pyqtSignal(str)
    translation_finished = pyqtSignal(str)
    translation_error = pyqtSignal(str)

    def __init__(self, text: str, target_language: str = None):
        super().__init__()
        self._text = text
        self._target_language = target_language
        self._is_cancelled = False

    def run(self):
        try:
            from src.core.translator import get_translator
            translator = get_translator()
            full_text = ""

            # 使用智能翻译（自动检测语言）
            for chunk in translator.translate_stream(self._text, self._target_language, auto_detect=True):
                if self._is_cancelled:
                    return

                if chunk:
                    full_text += chunk
                    self.chunk_received.emit(chunk)

            if not self._is_cancelled:
                self.translation_finished.emit(full_text)

        except Exception as e:
            if not self._is_cancelled:
                self.translation_error.emit(str(e))

    def cancel(self):
        """取消翻译"""
        self._is_cancelled = True


class StreamingPolishingWorker(QThread):
    """流式润色工作线程"""

    chunk_received = pyqtSignal(str)
    polishing_finished = pyqtSignal(str)
    polishing_error = pyqtSignal(str)

    def __init__(self, text: str):
        super().__init__()
        self._text = text
        self._is_cancelled = False

    def run(self):
        try:
            from src.core.translator import get_translator
            translator = get_translator()
            full_text = ""

            for chunk in translator.polishing_stream(self._text):
                if self._is_cancelled:
                    return

                if chunk:
                    full_text += chunk
                    self.chunk_received.emit(chunk)

            if not self._is_cancelled:
                self.polishing_finished.emit(full_text)

        except Exception as e:
            if not self._is_cancelled:
                self.polishing_error.emit(str(e))

    def cancel(self):
        """取消润色"""
        self._is_cancelled = True


class StreamingSummarizeWorker(QThread):
    """流式总结工作线程"""

    chunk_received = pyqtSignal(str)
    summarize_finished = pyqtSignal(str)
    summarize_error = pyqtSignal(str)

    def __init__(self, text: str, target_language: str = "中文"):
        super().__init__()
        self._text = text
        self._target_language = target_language
        self._is_cancelled = False

    def run(self):
        try:
            from src.core.translator import get_translator
            translator = get_translator()
            full_text = ""

            for chunk in translator.summarize_stream(self._text, self._target_language):
                if self._is_cancelled:
                    return

                if chunk:
                    full_text += chunk
                    self.chunk_received.emit(chunk)

            if not self._is_cancelled:
                self.summarize_finished.emit(full_text)

        except Exception as e:
            if not self._is_cancelled:
                self.summarize_error.emit(str(e))

    def cancel(self):
        """取消总结"""
        self._is_cancelled = True


class TranslatorWindow(QWidget):
    """独立翻译窗口（无边框，支持调整大小、主题切换、纯文本显示）

    同时支持：
    1. 手动输入翻译模式
    2. 划词自动翻译模式（自动填充原文并翻译）
    """

    # 信号
    closed = pyqtSignal()
    translation_completed = pyqtSignal(str, str)  # 原文, 译文 - 翻译完成信号

    def __init__(self):
        super().__init__()

        # 设置窗口对象名称
        self.setObjectName("TranslatorWindow")

        self._current_worker: Optional[StreamingTranslationWorker] = None

        # 窗口状态
        self._is_maximized = False
        self._is_minimized = False  # 最小化状态
        self._normal_geometry: Optional[QRect] = None

        # 拖动状态
        self._is_dragging = False
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None

        # 调整大小状态
        self._is_resizing = False
        self._resize_edge: Optional[str] = None
        self._resize_start_pos: Optional[QPoint] = None
        self._resize_start_geometry: Optional[QRect] = None

        # 加载主题
        self._theme_style = get_config().get('theme.popup_style', 'dark')

        # 字体大小
        self._font_size = get_config().get('font.size', 14)

        # 划词翻译相关
        self._auto_mode = False  # 是否处于自动翻译模式
        self._pending_original_text = ""  # 待翻译的原文

        # 流式翻译高度调整相关
        self._height_animation = None  # 高度调整动画
        self._last_adjusted_height = 0  # 上一次调整的高度（避免重复调整）
        self._height_adjust_timer = None  # 高度调整定时器（延迟调整，减少频繁更新）
        self._is_streaming = False  # 是否正在流式输出
        self._scrollbar_hidden = False  # 滚动条是否被隐藏（流式输出高度增长时）

        self._setup_window_properties()
        self._setup_ui()

    def _setup_window_properties(self):
        """设置窗口属性"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(450, 350)
        self.resize(500, 400)

        # 开启鼠标追踪
        self.setMouseTracking(True)

        # 设置窗口图标（任务栏图标）
        self._set_window_icon()

        # 在 Windows 上启用任务栏点击最小化功能
        self._enable_taskbar_minimize()

    def _set_window_icon(self):
        """设置窗口图标（任务栏图标）"""
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _enable_taskbar_minimize(self):
        """在 Windows 上启用任务栏点击最小化功能"""
        if sys.platform != 'win32':
            return

        try:
            import ctypes
            # 获取窗口句柄
            hwnd = int(self.winId())

            # 获取当前窗口样式
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE = -16

            # 添加 WS_MINIMIZEBOX 样式（允许最小化）
            WS_MINIMIZEBOX = 0x00020000
            WS_SYSMENU = 0x00080000
            new_style = style | WS_MINIMIZEBOX | WS_SYSMENU

            # 设置新样式
            ctypes.windll.user32.SetWindowLongW(hwnd, -16, new_style)
        except Exception:
            pass

    def _create_copy_icon(self, theme: dict) -> QIcon:
        """创建复制图标（两个重叠的空心文档）"""
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 图标颜色使用主题的 muted 文本颜色
        icon_color = QColor(theme.get('text_muted', '#888888'))
        pen = QPen(icon_color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        # 不填充，只绘制边框
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)

        # 绘制后面的文档（偏移位置，稍微小一点）
        painter.drawRoundedRect(6, 1, 10, 13, 2, 2)

        # 绘制前面的文档（主位置）
        painter.drawRoundedRect(2, 4, 10, 13, 2, 2)

        painter.end()

        return QIcon(pixmap)

    def _create_speak_icon(self, theme: dict) -> QIcon:
        """创建朗读图标（播放三角形）"""
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 图标颜色使用主题的 muted 文本颜色
        icon_color = QColor(theme.get('text_muted', '#888888'))

        # 绘制播放三角形
        painter.setBrush(icon_color)
        painter.setPen(Qt.PenStyle.NoPen)

        # 三角形的三个顶点
        triangle = [
            QPointF(5, 3),    # 左上
            QPointF(5, 15),   # 左下
            QPointF(15, 9),   # 右中
        ]
        painter.drawPolygon(*triangle)

        painter.end()

        return QIcon(pixmap)

    def _setup_ui(self):
        """设置 UI"""
        theme = get_theme(self._theme_style)

        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 内容容器
        self._content_frame = QFrame()
        self._content_frame.setObjectName("contentFrame")
        self._content_frame.setStyleSheet(f"""
            QFrame#contentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 8px;
                border: 1px solid {theme['border_color']};
            }}
        """)
        # 开启鼠标追踪
        self._content_frame.setMouseTracking(True)
        layout.addWidget(self._content_frame)

        # 添加阴影效果
        self._shadow_effect = QGraphicsDropShadowEffect()
        self._shadow_effect.setBlurRadius(15)
        self._shadow_effect.setColor(QColor(*theme['shadow_color']))
        self._shadow_effect.setOffset(0, 2)
        self._content_frame.setGraphicsEffect(self._shadow_effect)

        # 内容布局
        content_layout = QVBoxLayout(self._content_frame)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(10)

        # 标题栏
        self._title_bar = QFrame()
        self._title_bar.setObjectName("titleBar")
        self._title_bar.setFixedHeight(28)
        self._title_bar.setStyleSheet(f"""
            QFrame#titleBar {{
                background-color: transparent;
                border-bottom: 1px solid {theme['border_color']};
            }}
            QFrame#titleBar:hover {{
                background-color: {theme['button_bg']};
            }}
        """)
        # 开启鼠标追踪，让鼠标移动事件能传递到主窗口
        self._title_bar.setMouseTracking(True)

        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(8, 0, 8, 0)

        # 标题文字
        self._title_label = QLabel("QTranslator")
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)
        self._title_label.setMouseTracking(True)
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        # 最小化按钮
        self._minimize_btn = QPushButton("─")
        self._minimize_btn.setObjectName("minimizeBtn")
        self._minimize_btn.setFixedSize(20, 20)
        self._minimize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._minimize_btn.setStyleSheet(f"""
            QPushButton#minimizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton#minimizeBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)
        self._minimize_btn.clicked.connect(self._on_minimize)
        title_layout.addWidget(self._minimize_btn)

        # 最大化按钮
        self._maximize_btn = QPushButton("□")
        self._maximize_btn.setObjectName("maximizeBtn")
        self._maximize_btn.setFixedSize(20, 20)
        self._maximize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._maximize_btn.setStyleSheet(f"""
            QPushButton#maximizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#maximizeBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)
        self._maximize_btn.clicked.connect(self._on_maximize)
        title_layout.addWidget(self._maximize_btn)

        # 关闭按钮
        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._close_btn.setStyleSheet(f"""
            QPushButton#closeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton#closeBtn:hover {{
                background-color: {theme['close_hover']};
                color: #ffffff;
            }}
        """)
        self._close_btn.clicked.connect(self.hide)
        title_layout.addWidget(self._close_btn)

        content_layout.addWidget(self._title_bar)

        # 控制栏（语言选择 + 按钮）
        self._control_bar = QFrame()
        self._control_bar.setStyleSheet("QFrame { background-color: transparent; }")
        control_layout = QHBoxLayout(self._control_bar)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(10)

        # 语言选择
        self._lang_label = QLabel("目标语言：")
        self._lang_label.setStyleSheet(f"QLabel {{ color: {theme['text_secondary']}; font-size: 13px; }}")
        control_layout.addWidget(self._lang_label)

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["自动检测", "中文", "英文", "日文", "韩文"])
        self._lang_combo.setFixedHeight(28)
        self._lang_combo.setStyleSheet(get_combobox_style(theme))
        control_layout.addWidget(self._lang_combo)
        control_layout.addStretch()

        # 清空按钮
        self._clear_btn = QPushButton("清空")
        self._clear_btn.setFixedHeight(28)
        self._clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
        """)
        self._clear_btn.clicked.connect(self._clear_all)
        control_layout.addWidget(self._clear_btn)

        # 翻译按钮
        self._translate_btn = QPushButton("翻译")
        self._translate_btn.setFixedSize(60, 28)  # 固定宽度60px，防止状态文字变化导致宽度改变
        self._translate_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._translate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['accent_color']};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['accent_hover']};
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)
        self._translate_btn.clicked.connect(self._start_translation)
        control_layout.addWidget(self._translate_btn)

        # 润色按钮
        self._polishing_btn = QPushButton("润色")
        self._polishing_btn.setFixedSize(50, 28)  # 固定宽度50px
        self._polishing_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._polishing_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)
        self._polishing_btn.clicked.connect(self._start_polishing)
        control_layout.addWidget(self._polishing_btn)

        # 总结按钮
        self._summarize_btn = QPushButton("总结")
        self._summarize_btn.setFixedSize(50, 28)  # 固定宽度50px
        self._summarize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._summarize_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)
        self._summarize_btn.clicked.connect(self._start_summarize)
        control_layout.addWidget(self._summarize_btn)

        content_layout.addWidget(self._control_bar)

        # 分割器
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setStyleSheet(get_splitter_style(theme))
        self._splitter.setHandleWidth(6)
        self._splitter.setChildrenCollapsible(False)

        # 原文输入区域 - 纯文本显示
        self._input_text = QTextEdit()
        self._input_text.setPlaceholderText("输入要翻译的文本...")
        self._input_text.setFont(QFont("Microsoft YaHei", self._font_size))
        self._input_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-size: {self._font_size}px;
            }}
            QTextEdit:focus {{
                border-color: {theme['accent_color']};
            }}
            {get_scrollbar_style(theme)}
        """)
        self._input_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._input_text.customContextMenuRequested.connect(self._show_input_context_menu)
        self._input_text.setAcceptRichText(False)  # 禁用富文本
        self._input_text.installEventFilter(self)  # 安装事件过滤器以处理回车键
        self._splitter.addWidget(self._input_text)

        # 翻译结果显示区域 - 包装在容器中以支持右下角悬浮按钮
        self._output_container = QWidget()
        self._output_container.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
            }}
        """)
        # 不使用布局，使用绝对定位放置文本框和悬浮按钮
        self._output_container.setMinimumHeight(60)

        # 翻译结果文本框
        self._output_text = QTextEdit()
        self._output_text.setParent(self._output_container)
        self._output_text.setReadOnly(True)
        self._output_text.setFont(QFont("Microsoft YaHei", self._font_size))
        self._output_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._output_text.setPlaceholderText("翻译结果...")
        self._output_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {theme['text_primary']};
                border: none;
                border-radius: 4px;
                padding: 8px;
                font-size: {self._font_size}px;
            }}
            {get_scrollbar_style(theme)}
        """)
        self._output_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._output_text.customContextMenuRequested.connect(self._show_output_context_menu)
        self._output_text.setAcceptRichText(False)  # 禁用富文本

        # 悬浮按钮容器（右下角）- 完全透明，无边框
        self._floating_buttons_frame = QFrame()
        self._floating_buttons_frame.setParent(self._output_container)
        self._floating_buttons_frame.setObjectName("floatingButtonsFrame")
        self._floating_buttons_frame.setStyleSheet(f"""
            QFrame#floatingButtonsFrame {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
        """)
        self._floating_buttons_layout = QHBoxLayout(self._floating_buttons_frame)
        self._floating_buttons_layout.setContentsMargins(4, 2, 4, 2)
        self._floating_buttons_layout.setSpacing(2)

        # 朗读按钮（朗读译文）- 使用绘制的播放图标
        self._speak_output_btn = QPushButton()
        self._speak_output_btn.setObjectName("speakOutputBtn")
        self._speak_output_btn.setFixedSize(28, 28)
        self._speak_output_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._speak_output_btn.setToolTip("朗读译文")
        self._speak_output_btn.setIcon(self._create_speak_icon(theme))
        self._speak_output_btn.setStyleSheet(f"""
            QPushButton#speakOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#speakOutputBtn:hover {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QPushButton#speakOutputBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.2);
            }}
        """)
        self._speak_output_btn.clicked.connect(self._speak_output)
        self._floating_buttons_layout.addWidget(self._speak_output_btn)

        # 复制按钮 - 使用绘制的复制图标
        self._copy_output_btn = QPushButton()
        self._copy_output_btn.setObjectName("copyOutputBtn")
        self._copy_output_btn.setFixedSize(28, 28)
        self._copy_output_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._copy_output_btn.setToolTip("复制译文")
        self._copy_output_btn.setIcon(self._create_copy_icon(theme))
        self._copy_output_btn.setStyleSheet(f"""
            QPushButton#copyOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#copyOutputBtn:hover {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QPushButton#copyOutputBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.2);
            }}
        """)
        self._copy_output_btn.clicked.connect(self._copy_all_text)
        self._floating_buttons_layout.addWidget(self._copy_output_btn)

        # 固定悬浮按钮容器大小
        self._floating_buttons_frame.setFixedSize(70, 34)

        self._splitter.addWidget(self._output_container)

        # 设置分割器初始比例（原文框100px，译文框200px）
        self._splitter.setSizes([100, 200])
        content_layout.addWidget(self._splitter, 1)

        # 为输出容器安装事件过滤器，以便处理 resize 事件更新悬浮按钮位置
        self._output_container.installEventFilter(self)

        # 为标题栏安装事件过滤器，以便处理鼠标移动事件更新光标
        self._title_bar.installEventFilter(self)
        self._title_label.installEventFilter(self)
        self._content_frame.installEventFilter(self)

    def _on_minimize(self):
        """最小化窗口"""
        self._is_minimized = True
        self.showMinimized()  # 使用系统最小化

    def is_minimized(self) -> bool:
        """检查窗口是否最小化"""
        return self._is_minimized or self.windowState() & Qt.WindowState.WindowMinimized

    def restore_from_minimized(self):
        """从最小化状态恢复"""
        self._is_minimized = False
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_maximize(self):
        """最大化/还原窗口"""
        if self._is_maximized:
            # 还原
            if self._normal_geometry:
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

    def update_theme(self):
        """更新主题"""
        new_theme = get_config().get('theme.popup_style', 'dark')
        new_font_size = get_config().get('font.size', 14)
        if new_theme != self._theme_style or new_font_size != self._font_size:
            self._theme_style = new_theme
            self._font_size = new_font_size
            self._apply_theme()

    def _apply_theme(self):
        """应用主题"""
        theme = get_theme(self._theme_style)

        # 更新内容框架
        self._content_frame.setStyleSheet(f"""
            QFrame#contentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 8px;
                border: 1px solid {theme['border_color']};
            }}
        """)

        # 更新阴影
        self._shadow_effect.setColor(QColor(*theme['shadow_color']))

        # 更新标题栏
        self._title_bar.setStyleSheet(f"""
            QFrame#titleBar {{
                background-color: transparent;
                border-bottom: 1px solid {theme['border_color']};
            }}
            QFrame#titleBar:hover {{
                background-color: {theme['button_bg']};
            }}
        """)

        # 更新标题标签
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)

        # 更新按钮样式
        self._minimize_btn.setStyleSheet(f"""
            QPushButton#minimizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton#minimizeBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)

        self._maximize_btn.setStyleSheet(f"""
            QPushButton#maximizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#maximizeBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)

        self._close_btn.setStyleSheet(f"""
            QPushButton#closeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton#closeBtn:hover {{
                background-color: {theme['close_hover']};
                color: #ffffff;
            }}
        """)

        # 更新语言标签
        self._lang_label.setStyleSheet(f"QLabel {{ color: {theme['text_secondary']}; font-size: 13px; }}")

        # 更新下拉框
        self._lang_combo.setStyleSheet(get_combobox_style(theme))

        # 更新清空按钮
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
        """)

        # 更新翻译按钮
        self._translate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['accent_color']};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['accent_hover']};
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)

        # 更新润色按钮
        self._polishing_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)

        # 更新总结按钮
        self._summarize_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)

        # 更新分割器
        self._splitter.setStyleSheet(get_splitter_style(theme))

        # 更新输入框
        self._input_text.setFont(QFont("Microsoft YaHei", self._font_size))
        self._input_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-size: {self._font_size}px;
            }}
            QTextEdit:focus {{
                border-color: {theme['accent_color']};
            }}
            {get_scrollbar_style(theme)}
        """)

        # 更新输出框容器
        self._output_container.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
            }}
        """)

        # 更新输出框
        self._output_text.setFont(QFont("Microsoft YaHei", self._font_size))
        self._output_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {theme['text_primary']};
                border: none;
                border-radius: 4px;
                padding: 8px;
                font-size: {self._font_size}px;
            }}
            {get_scrollbar_style(theme)}
        """)

        # 更新悬浮按钮容器样式 - 完全透明，无边框
        self._floating_buttons_frame.setStyleSheet(f"""
            QFrame#floatingButtonsFrame {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
        """)

        # 根据主题设置悬停/点击效果
        if self._theme_style == 'dark':
            hover_bg = "rgba(255, 255, 255, 0.15)"
            pressed_bg = "rgba(255, 255, 255, 0.25)"
        else:
            hover_bg = "rgba(0, 0, 0, 0.1)"
            pressed_bg = "rgba(0, 0, 0, 0.2)"

        # 更新复制按钮样式和图标
        self._copy_output_btn.setIcon(self._create_copy_icon(theme))
        self._copy_output_btn.setStyleSheet(f"""
            QPushButton#copyOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#copyOutputBtn:hover {{
                background-color: {hover_bg};
            }}
            QPushButton#copyOutputBtn:pressed {{
                background-color: {pressed_bg};
            }}
        """)

        # 更新朗读按钮样式和图标
        self._speak_output_btn.setIcon(self._create_speak_icon(theme))
        self._speak_output_btn.setStyleSheet(f"""
            QPushButton#speakOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#speakOutputBtn:hover {{
                background-color: {hover_bg};
            }}
            QPushButton#speakOutputBtn:pressed {{
                background-color: {pressed_bg};
            }}
        """)

    def _copy_all_text(self):
        """复制译文"""
        clipboard = QApplication.clipboard()
        translated_text = self._output_text.toPlainText()
        if translated_text:
            clipboard.setText(translated_text)

    def _speak_output(self):
        """朗读译文"""
        text = self._output_text.toPlainText()
        if text:
            tts = get_tts()
            if tts.is_speaking():
                tts.stop()
            else:
                tts.speak(text)

    def _clear_all(self):
        """清空所有内容并取消正在进行的流式输出任务"""
        # 1. 如果当前有翻译/总结/润色任务正在执行，取消它
        if self._current_worker and self._current_worker.isRunning():
            # 调用取消机制，设置取消标志
            self._current_worker.cancel()
            # 等待线程结束（最多1秒），避免资源泄露
            self._current_worker.wait(1000)
            # 清理 worker 引用
            self._current_worker = None

        # 2. 重置流式输出状态变量
        self._is_streaming = False
        self._scrollbar_hidden = False
        if hasattr(self, '_streaming_text'):
            self._streaming_text = ""

        # 3. 恢复滚动条显示（如果之前被隐藏）
        self._show_output_scrollbar()

        # 4. 清空输入和输出文本框
        self._input_text.clear()
        self._output_text.clear()

        # 5. 重置划词翻译相关状态
        self._auto_mode = False
        self._pending_original_text = ""

        # 6. 重新启用之前被禁用的操作按钮
        self._translate_btn.setEnabled(True)
        self._polishing_btn.setEnabled(True)
        self._summarize_btn.setEnabled(True)

        # 7. 清理高度调整定时器（如果存在）
        if self._height_adjust_timer:
            self._height_adjust_timer.stop()
            self._height_adjust_timer = None

        # 8. 不重置窗口高度，保持当前窗口大小状态
        # 只恢复滚动条显示
        self._show_output_scrollbar()
        self._scrollbar_hidden = False

    def _start_translation(self):
        """开始翻译"""
        text = self._input_text.toPlainText().strip()
        if not text:
            return

        # 取消之前的翻译
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
            self._current_worker = None

        # 清空输出
        self._output_text.clear()
        self._streaming_text = ""

        # 初始化流式状态
        self._is_streaming = True
        self._last_adjusted_height = 0
        self._scrollbar_hidden = False  # 重置滚动条隐藏状态

        # 流式输出开始时隐藏滚动条
        self._hide_output_scrollbar()

        # 禁用按钮（按钮文字保持不变，通过禁用状态表示正在处理）
        self._translate_btn.setEnabled(False)
        self._polishing_btn.setEnabled(False)
        self._summarize_btn.setEnabled(False)

        # 获取目标语言
        target_language = self._lang_combo.currentText()
        if target_language == "自动检测":
            target_language = None  # 使用自动检测

        # 启动翻译线程
        self._current_worker = StreamingTranslationWorker(text, target_language)
        self._current_worker.chunk_received.connect(self._on_chunk_received)
        self._current_worker.translation_finished.connect(self._on_translation_finished)
        self._current_worker.translation_error.connect(self._on_translation_error)
        self._current_worker.start()

    def _on_chunk_received(self, chunk: str):
        """收到翻译片段"""
        try:
            if not hasattr(self, '_streaming_text'):
                self._streaming_text = ""
                self._is_streaming = True
                self._last_adjusted_height = 0

            self._streaming_text += chunk

            # 记录当前滚动条位置，判断用户是否在底部
            scrollbar = self._output_text.verticalScrollBar()
            was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 10  # 允许10px误差

            # 使用 QTextCursor 追加文本，避免频繁 setPlainText 导致滚动条闪烁
            cursor = self._output_text.textCursor()

            # 移动到文档末尾
            cursor.movePosition(cursor.MoveOperation.End)

            # 插入新文本（不重新渲染整个文档）
            cursor.insertText(chunk)

            # 如果用户之前不在底部（正在查看之前的内容），恢复滚动位置
            # 如果用户在底部，则自动滚动到新内容
            if was_at_bottom:
                # 用户在底部，跟随新内容滚动到底部
                scrollbar.setValue(scrollbar.maximum())
            # else: 用户正在查看之前的内容，不改变滚动位置（让用户自由滚动）

            # 触发高度调整（延迟执行，避免频繁更新）
            if self._is_streaming:
                self._schedule_height_adjust()
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _on_translation_finished(self, result: str):
        """翻译完成"""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_translation_finished(result))

    def _do_translation_finished(self, result: str):
        """实际执行翻译完成操作"""
        try:
            self._is_streaming = False
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)

            # 最终高度调整
            QTimer.singleShot(100, self._final_height_adjust)

            # 调试输出
            try:
                from src.utils.logger import log_debug
                log_debug(f"翻译完成，最终高度调整已调度")
            except:
                pass

            # 发出翻译完成信号（用于划词翻译模式）
            if self._auto_mode:
                original_text = self._pending_original_text or self._input_text.toPlainText()
                self.translation_completed.emit(original_text, result)

            self._current_worker = None

            # 保存翻译历史
            if result:
                try:
                    from src.utils.history import add_translation_history
                    target_lang = self._lang_combo.currentText()
                    if target_lang == "自动检测":
                        target_lang = "中文"  # 默认
                    add_translation_history(
                        self._input_text.toPlainText(),
                        result,
                        target_lang,
                        "selection" if self._auto_mode else "manual"
                    )
                except Exception:
                    pass

            # 重置自动翻译模式
            self._auto_mode = False
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _on_translation_error(self, error: str):
        """翻译错误"""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_translation_error(error))

    def _do_translation_error(self, error: str):
        """实际执行翻译错误操作"""
        try:
            self._is_streaming = False
            self._scrollbar_hidden = False
            # 恢复滚动条显示
            self._show_output_scrollbar()
            self._output_text.setPlainText(f"翻译失败: {error}")
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            self._current_worker = None
            # 重置自动翻译模式
            self._auto_mode = False
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _start_polishing(self):
        """开始润色"""
        text = self._input_text.toPlainText().strip()
        if not text:
            return

        # 取消之前的任务
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
            self._current_worker = None

        # 清空输出
        self._output_text.clear()
        self._streaming_text = ""

        # 初始化流式状态
        self._is_streaming = True
        self._last_adjusted_height = 0
        self._scrollbar_hidden = False

        # 流式输出开始时隐藏滚动条
        self._hide_output_scrollbar()

        # 禁用所有操作按钮（按钮文字保持不变，通过禁用状态表示正在处理）
        self._translate_btn.setEnabled(False)
        self._polishing_btn.setEnabled(False)
        self._summarize_btn.setEnabled(False)

        # 启动润色线程
        self._current_worker = StreamingPolishingWorker(text)
        self._current_worker.chunk_received.connect(self._on_chunk_received)
        self._current_worker.polishing_finished.connect(self._on_polishing_finished)
        self._current_worker.polishing_error.connect(self._on_polishing_error)
        self._current_worker.start()

    def _on_polishing_finished(self, result: str):
        """润色完成"""
        # 使用 QTimer 延迟执行，避免在信号槽中直接操作
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_polishing_finished(result))

    def _do_polishing_finished(self, result: str):
        """实际执行润色完成操作（在主线程中）"""
        try:
            self._is_streaming = False
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            self._current_worker = None

            # 最终高度调整
            QTimer.singleShot(100, self._final_height_adjust)

            # 保存润色历史
            if result:
                try:
                    from src.utils.history import add_translation_history
                    add_translation_history(
                        self._input_text.toPlainText(),
                        result,
                        "润色",
                        "polishing"
                    )
                except Exception:
                    pass
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _on_polishing_error(self, error: str):
        """润色错误"""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_polishing_error(error))

    def _do_polishing_error(self, error: str):
        """实际执行润色错误操作（在主线程中）"""
        try:
            self._is_streaming = False
            self._scrollbar_hidden = False
            # 恢复滚动条显示
            self._show_output_scrollbar()
            self._output_text.setPlainText(f"润色失败: {error}")
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            self._current_worker = None
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _start_summarize(self):
        """开始总结"""
        text = self._input_text.toPlainText().strip()
        if not text:
            return

        # 取消之前的任务
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
            self._current_worker = None

        # 清空输出
        self._output_text.clear()
        self._streaming_text = ""

        # 初始化流式状态
        self._is_streaming = True
        self._last_adjusted_height = 0
        self._scrollbar_hidden = False

        # 流式输出开始时隐藏滚动条
        self._hide_output_scrollbar()

        # 禁用所有操作按钮（按钮文字保持不变，通过禁用状态表示正在处理）
        self._translate_btn.setEnabled(False)
        self._polishing_btn.setEnabled(False)
        self._summarize_btn.setEnabled(False)

        # 获取目标语言（用于总结输出的语言）
        target_language = self._lang_combo.currentText()
        if target_language == "自动检测":
            target_language = "中文"

        # 启动总结线程
        self._current_worker = StreamingSummarizeWorker(text, target_language)
        self._current_worker.chunk_received.connect(self._on_chunk_received)
        self._current_worker.summarize_finished.connect(self._on_summarize_finished)
        self._current_worker.summarize_error.connect(self._on_summarize_error)
        self._current_worker.start()

    def _on_summarize_finished(self, result: str):
        """总结完成"""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_summarize_finished(result))

    def _do_summarize_finished(self, result: str):
        """实际执行总结完成操作"""
        try:
            self._is_streaming = False
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            self._current_worker = None

            # 最终高度调整
            QTimer.singleShot(100, self._final_height_adjust)

            # 保存总结历史
            if result:
                try:
                    from src.utils.history import add_translation_history
                    target_lang = self._lang_combo.currentText()
                    if target_lang == "自动检测":
                        target_lang = "中文"
                    add_translation_history(
                        self._input_text.toPlainText(),
                        result,
                        target_lang,
                        "summarize"
                    )
                except Exception:
                    pass
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _on_summarize_error(self, error: str):
        """总结错误"""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_summarize_error(error))

    def _do_summarize_error(self, error: str):
        """实际执行总结错误操作"""
        try:
            self._is_streaming = False
            self._scrollbar_hidden = False
            # 恢复滚动条显示
            self._show_output_scrollbar()
            self._output_text.setPlainText(f"总结失败: {error}")
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            self._current_worker = None
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _show_input_context_menu(self, pos):
        """显示输入框右键菜单"""
        from PyQt6.QtWidgets import QMenu
        theme = get_theme(self._theme_style)

        menu = QMenu(self)
        menu.setStyleSheet(get_menu_style(theme))

        undo_action = menu.addAction("撤销")
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self._input_text.undo)

        redo_action = menu.addAction("重做")
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self._input_text.redo)

        menu.addSeparator()

        cut_action = menu.addAction("剪切")
        cut_action.setShortcut("Ctrl+X")
        cut_action.triggered.connect(self._input_text.cut)

        copy_action = menu.addAction("复制")
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self._input_text.copy)

        paste_action = menu.addAction("粘贴")
        paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(self._input_text.paste)

        menu.addSeparator()

        delete_action = menu.addAction("删除")
        delete_action.triggered.connect(self._input_text.textCursor().removeSelectedText)

        menu.addSeparator()

        select_all_action = menu.addAction("全选")
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self._input_text.selectAll)

        clear_action = menu.addAction("清空")
        clear_action.triggered.connect(self._input_text.clear)

        menu.exec(self._input_text.mapToGlobal(pos))

    def _show_output_context_menu(self, pos):
        """显示输出框右键菜单"""
        from PyQt6.QtWidgets import QMenu
        theme = get_theme(self._theme_style)

        menu = QMenu(self)
        menu.setStyleSheet(get_menu_style(theme))

        copy_action = menu.addAction("复制")
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self._output_text.copy)

        copy_all_action = menu.addAction("复制全部译文")
        copy_all_action.triggered.connect(lambda: QApplication.clipboard().setText(self._output_text.toPlainText()))

        menu.addSeparator()

        select_all_action = menu.addAction("全选")
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self._output_text.selectAll)

        menu.exec(self._output_text.mapToGlobal(pos))

    def _is_over_title_bar_buttons(self, pos: QPoint) -> bool:
        """判断鼠标是否在标题栏按钮区域内（包括按钮之间的间距）"""
        title_bar_height = 28
        # 首先检查是否在标题栏区域
        if pos.y() > title_bar_height:
            return False

        # 计算按钮区域（三个按钮都在标题栏右侧）
        # 按钮大小 20x20
        button_width = 20
        total_buttons_width = button_width * 3 + 8  # 三个按钮，额外8px间距余量

        # 标题栏右边距
        right_margin = 8

        # 按钮区域的左边界
        window_width = self.width()
        buttons_left = window_width - right_margin - total_buttons_width

        # 检查鼠标是否在按钮区域内
        return pos.x() >= buttons_left

    def _get_resize_edge(self, pos: QPoint) -> Optional[str]:
        """判断鼠标位置对应的调整边缘（优化灵敏度）"""
        # 边缘检测区域 - 覆盖整个边框和边缘附近的区域
        edge_margin = 15  # 边缘检测宽度

        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()

        # 分别检测四个方向的边缘（不使用 elif，以支持组合）
        on_left = x <= edge_margin
        on_right = x >= w - edge_margin
        on_top = y <= edge_margin
        on_bottom = y >= h - edge_margin

        # 组合边缘检测结果
        edge = None

        if on_top and on_left:
            edge = 'top-left'
        elif on_top and on_right:
            edge = 'top-right'
        elif on_bottom and on_left:
            edge = 'bottom-left'
        elif on_bottom and on_right:
            edge = 'bottom-right'
        elif on_top:
            edge = 'top'
        elif on_bottom:
            edge = 'bottom'
        elif on_left:
            edge = 'left'
        elif on_right:
            edge = 'right'

        return edge

    def _update_cursor_for_edge(self, edge: Optional[str]):
        """根据边缘更新鼠标光标"""
        cursor_shape = Qt.CursorShape.ArrowCursor
        if edge == 'top-left' or edge == 'bottom-right':
            cursor_shape = Qt.CursorShape.SizeFDiagCursor
        elif edge == 'top-right' or edge == 'bottom-left':
            cursor_shape = Qt.CursorShape.SizeBDiagCursor
        elif edge == 'left' or edge == 'right':
            cursor_shape = Qt.CursorShape.SizeHorCursor
        elif edge == 'top' or edge == 'bottom':
            cursor_shape = Qt.CursorShape.SizeVerCursor

        self.setCursor(QCursor(cursor_shape))

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """鼠标双击事件 - 双击标题栏切换最大化状态"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            title_bar_height = 28

            # 检查是否在标题栏区域且不在按钮区域
            if pos.y() <= title_bar_height and not self._is_over_title_bar_buttons(pos):
                # 双击标题栏任意位置切换最大化
                self._on_maximize()
                return

        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()

            # 优先检测边缘调整区域（让调整大小优先于拖动）
            edge = self._get_resize_edge(pos)
            if edge:
                self._is_resizing = True
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
            else:
                # 不是边缘区域，检测标题栏拖动
                title_bar_height = 28
                if pos.y() <= title_bar_height and not self._is_over_title_bar_buttons(pos):
                    self._is_dragging = True
                    self._drag_start_pos = event.globalPosition().toPoint()
                    self._drag_window_start_pos = self.pos()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件"""
        pos = event.position().toPoint()

        if self._is_dragging and self._drag_start_pos:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            new_pos = self._drag_window_start_pos + delta
            self.move(new_pos)
        elif self._is_resizing and self._resize_start_pos:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            geo = self._resize_start_geometry

            new_x, new_y, new_w, new_h = geo.x(), geo.y(), geo.width(), geo.height()

            edge = self._resize_edge
            if 'left' in edge:
                new_w = geo.width() - delta.x()
                new_x = geo.x() + delta.x()
            if 'right' in edge:
                new_w = geo.width() + delta.x()
            if 'top' in edge:
                new_h = geo.height() - delta.y()
                new_y = geo.y() + delta.y()
            if 'bottom' in edge:
                new_h = geo.height() + delta.y()

            new_w = max(self.minimumWidth(), new_w)
            new_h = max(self.minimumHeight(), new_h)

            if 'left' in edge:
                new_x = geo.x() + geo.width() - new_w
            if 'top' in edge:
                new_y = geo.y() + geo.height() - new_h

            self.setGeometry(new_x, new_y, new_w, new_h)
        else:
            # 智能光标控制
            # 1. 首先检查边框调整区域
            edge = self._get_resize_edge(pos)
            if edge:
                self._update_cursor_for_edge(edge)
            # 2. 其他区域显示默认箭头光标（标题栏不显示拖动光标）
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_start_pos = None
            self._is_resizing = False
            self._resize_edge = None

        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        # 鼠标离开窗口时恢复默认光标
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)

    def eventFilter(self, obj, event):
        """事件过滤器 - 处理子控件的鼠标事件和输入框的键盘事件"""
        # 处理输出容器的 resize 事件（确保属性已存在）
        if hasattr(self, '_output_container') and obj == self._output_container and event.type() == event.Type.Resize:
            self._update_output_layout()
            return False  # 不拦截，让事件继续传播

        # 处理输入框的键盘事件
        if obj == self._input_text and event.type() == event.Type.KeyPress:
            key = event.key()
            # 处理回车键
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                # Shift+回车：换行（不拦截，让 QTextEdit 处理）
                if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                    return False  # 不拦截，让事件继续传播
                # 回车（无修饰）：触发翻译
                if self._input_text.toPlainText().strip():
                    self._start_translation()
                    return True  # 拦截事件，阻止换行

        if event.type() == event.Type.MouseMove:
            # 获取鼠标在主窗口中的位置
            pos = self.mapFromGlobal(obj.mapToGlobal(event.position().toPoint()))

            # 更新光标样式
            edge = self._get_resize_edge(pos)
            if edge:
                self._update_cursor_for_edge(edge)
                obj.setCursor(QCursor(self._get_cursor_shape_for_edge(edge)))
            else:
                # 其他区域显示默认箭头光标（标题栏不显示拖动光标）
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                obj.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        elif event.type() == event.Type.Leave:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            obj.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        return super().eventFilter(obj, event)

    def _update_output_layout(self):
        """更新输出区域的布局（文本框和悬浮按钮位置）"""
        try:
            container_width = self._output_container.width()
            container_height = self._output_container.height()

            # 更新文本框大小（填充整个容器）
            self._output_text.setGeometry(0, 0, container_width, container_height)

            # 更新悬浮按钮位置（右下角，留出一定边距）
            button_width = self._floating_buttons_frame.width()
            button_height = self._floating_buttons_frame.height()
            margin = 6

            # 悬浮按钮位置：右下角，考虑边距
            button_x = container_width - button_width - margin
            button_y = container_height - button_height - margin

            self._floating_buttons_frame.move(button_x, button_y)

        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _get_cursor_shape_for_edge(self, edge: Optional[str]) -> Qt.CursorShape:
        """根据边缘获取光标形状"""
        if edge == 'top-left' or edge == 'bottom-right':
            return Qt.CursorShape.SizeFDiagCursor
        elif edge == 'top-right' or edge == 'bottom-left':
            return Qt.CursorShape.SizeBDiagCursor
        elif edge == 'left' or edge == 'right':
            return Qt.CursorShape.SizeHorCursor
        elif edge == 'top' or edge == 'bottom':
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def changeEvent(self, event):
        """窗口状态变化事件"""
        if event.type() == event.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                # 窗口被最小化
                self._is_minimized = True
            elif self._is_minimized and not (self.windowState() & Qt.WindowState.WindowMinimized):
                # 窗口从最小化恢复
                self._is_minimized = False
        super().changeEvent(event)

    def closeEvent(self, event):
        """窗口关闭事件"""
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
            self._current_worker = None

        # 重置自动翻译模式
        self._auto_mode = False
        self._pending_original_text = ""

        event.ignore()
        self.hide()

    def show_window(self):
        """显示窗口"""
        # 如果窗口处于最小化状态，先恢复正常
        if self.isMinimized():
            self.showNormal()

        self._is_minimized = False
        self.update_theme()

        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2
            y = (screen_geo.height() - self.height()) // 2
            self.move(x, y)

        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        self._input_text.setFocus()

    def keyPressEvent(self, event):
        """键盘事件处理"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return

        # 当焦点不在输入框时，回车键触发翻译
        # 输入框的回车键由事件过滤器处理（回车=翻译，Shift+回车=换行）
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if not self._input_text.hasFocus() and self._input_text.toPlainText().strip():
                self._start_translation()
                return

        super().keyPressEvent(event)

    # ==================== 划词翻译模式支持 ====================

    def _get_screen_bounds(self):
        """获取屏幕可用区域"""
        try:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableVirtualGeometry()
                return (geo.x(), geo.y(), geo.width(), geo.height())
        except Exception:
            pass
        return (0, 0, 1920, 1080)

    def _calculate_position(self, mouse_pos):
        """计算悬浮窗位置（考虑最大高度限制和屏幕边界）

        窗口位置计算策略：
        1. 默认显示在鼠标右下方
        2. 如果右侧空间不足，显示在左侧
        3. 如果下方空间不足（考虑最大高度70%），显示在上方
        4. 确保窗口不会超出屏幕边界
        """
        x, y = mouse_pos
        # 使用鼠标位置所在的屏幕
        try:
            screen = QApplication.screenAt(QPoint(x, y))
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                screen_x, screen_y, screen_w, screen_h = geo.x(), geo.y(), geo.width(), geo.height()
            else:
                screen_x, screen_y, screen_w, screen_h = 0, 0, 1920, 1080
        except Exception:
            screen_x, screen_y, screen_w, screen_h = self._get_screen_bounds()

        win_w = self.width()
        win_h = self.height()

        # 计算最大可能高度（屏幕高度的70%），用于判断位置是否安全
        max_potential_height = int(screen_h * 0.7)

        new_x = x + 15
        new_y = y + 15

        # 检查水平方向：如果右侧空间不足，放到左边
        if new_x + win_w > screen_x + screen_w - 10:
            new_x = x - win_w - 15

        # 检查垂直方向：考虑最大可能高度
        # 如果当前窗口底部加上最大可能高度会超出屏幕，则放到上面
        if new_y + max_potential_height > screen_y + screen_h - 10:
            # 尝试放在鼠标上方
            potential_y = y - max_potential_height - 15
            if potential_y >= screen_y + 10:
                new_y = potential_y
            else:
                # 如果上方也放不下，就贴着屏幕底部放置
                new_y = screen_y + screen_h - max_potential_height - 10

        # 确保不超出左边界
        if new_x < screen_x + 10:
            new_x = screen_x + 10

        # 确保不超出上边界
        if new_y < screen_y + 10:
            new_y = screen_y + 10

        return (new_x, new_y)

    def show_at_mouse(self, mouse_pos=None, text=None):
        """在鼠标位置显示窗口并自动翻译（划词翻译模式）

        Args:
            mouse_pos: 鼠标位置元组 (x, y)，如果为 None 则使用当前鼠标位置
            text: 要翻译的文本，如果为 None 则使用输入框中的文本
        """
        if mouse_pos is None:
            mouse_pos = (QCursor.pos().x(), QCursor.pos().y())

        # 每次显示时重新加载主题和字体配置
        self.update_theme()

        # 如果窗口处于最小化状态，先恢复正常状态
        if self.isMinimized():
            self.showNormal()
            self._is_maximized = False
            self._maximize_btn.setText("□")

        # 重置窗口大小和高度状态
        self._reset_window_height()

        # 计算并移动到鼠标位置
        x, y = self._calculate_position(mouse_pos)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

        # 如果提供了文本，自动填充并翻译
        if text:
            self.auto_translate(text)

    def auto_translate(self, text: str):
        """自动翻译选中的文本

        Args:
            text: 要翻译的文本
        """
        if not text or not text.strip():
            return

        # 保存原文
        self._pending_original_text = text.strip()
        self._auto_mode = True

        # 填充输入框
        self._input_text.setPlainText(self._pending_original_text)

        # 清空输出框
        self._output_text.clear()
        self._streaming_text = ""

        # 自动触发翻译
        self._start_translation()

    def show_loading(self, original_text: str = None):
        """显示加载状态

        Args:
            original_text: 原文内容，如果提供则显示在输入框中
        """
        if original_text:
            self._input_text.setPlainText(original_text)
        self._output_text.setPlainText("正在翻译...")

    def show_streaming_start(self, original_text: str = None):
        """开始流式翻译显示

        Args:
            original_text: 原文内容，如果提供则显示在输入框中
        """
        self._streaming_text = ""
        self._is_streaming = True  # 设置流式状态
        self._last_adjusted_height = 0  # 重置高度记录
        self._scrollbar_hidden = False  # 重置滚动条隐藏状态

        if original_text:
            self._input_text.setPlainText(original_text)

        self._output_text.clear()

        # 流式输出开始时隐藏滚动条
        self._hide_output_scrollbar()

        # 启用按钮
        self._translate_btn.setEnabled(True)
        self._polishing_btn.setEnabled(True)
        self._summarize_btn.setEnabled(True)

    def append_translation_text(self, chunk: str):
        """追加流式翻译文本

        Args:
            chunk: 翻译文本片段
        """
        if not hasattr(self, '_streaming_text'):
            self._streaming_text = ""
        self._streaming_text += chunk
        self._output_text.setPlainText(self._streaming_text)

        # 触发高度调整（延迟执行，避免频繁更新）
        if self._is_streaming:
            self._schedule_height_adjust()

    def finish_streaming(self):
        """完成流式翻译"""
        self._is_streaming = False
        # 清理定时器
        if self._height_adjust_timer:
            self._height_adjust_timer.stop()
            self._height_adjust_timer = None
        # 滚动到顶部
        self._input_text.verticalScrollBar().setValue(0)
        self._output_text.verticalScrollBar().setValue(0)
        # 最终高度调整和屏幕边界检查
        QTimer.singleShot(100, self._final_height_adjust)

    def _final_height_adjust(self):
        """流式翻译结束后的最终高度调整"""
        try:
            # 恢复滚动条显示（流式输出结束后）
            self._show_output_scrollbar()
            self._scrollbar_hidden = False

            # 计算最终所需高度
            target_height = self._calculate_required_height()
            # 立即调整高度（不使用动画）
            self._smooth_adjust_height(target_height, immediate=True)
        except RuntimeError:
            pass
        except Exception:
            pass

    def _get_current_screen_bounds(self) -> tuple:
        """获取窗口当前所在屏幕的可用区域

        Returns:
            tuple: (screen_x, screen_y, screen_w, screen_h)
        """
        try:
            # 优先使用窗口当前所在的屏幕
            screen = QApplication.screenAt(self.geometry().center())
            if screen is None:
                screen = QApplication.screenAt(self.pos())
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                return (geo.x(), geo.y(), geo.width(), geo.height())
        except Exception:
            pass
        return self._get_screen_bounds()

    def _calculate_required_height(self) -> int:
        """计算显示当前内容所需的窗口高度

        保持用户手动调整的原文框高度，只根据译文内容动态调整窗口高度

        Returns:
            所需的窗口高度（像素）
        """
        try:
            # 使用当前窗口所在屏幕
            screen_x, screen_y, screen_w, screen_h = self._get_current_screen_bounds()
            # 最大允许高度（屏幕高度的70%）
            max_height = int(screen_h * 0.7)

            from PyQt6.QtGui import QFontMetrics, QTextDocument

            # 使用窗口宽度计算（输出区域占满窗口宽度减去边距）
            # 窗口内边距 12px * 2 = 24px，输出框内边距 8px * 2 = 16px
            output_width = self.width() - 24 - 16 - 20  # 额外20px余量
            output_width = max(200, output_width)  # 确保最小宽度

            # 计算输出文本高度
            output_font = self._output_text.font()
            output_text = self._output_text.toPlainText()

            if output_text:
                # 使用 QTextDocument 计算精确高度
                doc = QTextDocument()
                doc.setDefaultFont(output_font)
                doc.setTextWidth(output_width)
                doc.setPlainText(output_text)
                output_height = int(doc.size().height()) + 30  # 额外30px边距
                # 确保最小高度
                output_height = max(80, output_height)
            else:
                output_height = 80

            # 获取当前分割器的原文框高度（用户可能手动调整过）
            current_sizes = self._splitter.sizes()
            input_height = current_sizes[0] if current_sizes else 100
            input_height = max(60, input_height)  # 确保最小高度

            # 总高度 = 标题栏 + 控制栏 + 边距 + 输入区 + 分割条 + 输出区
            title_height = 28
            control_height = 38
            splitter_height = 6
            margin = 40

            total_height = title_height + control_height + margin + input_height + splitter_height + output_height

            # 限制在合理范围内
            min_window_height = 350
            total_height = max(min_window_height, min(total_height, max_height))

            return total_height

        except Exception:
            return 400

    def _ensure_within_screen(self):
        """确保窗口完全在屏幕范围内"""
        try:
            screen_x, screen_y, screen_w, screen_h = self._get_current_screen_bounds()
            x, y = self.x(), self.y()
            w, h = self.width(), self.height()

            # 检查右边界
            if x + w > screen_x + screen_w:
                x = screen_x + screen_w - w
            # 检查下边界
            if y + h > screen_y + screen_h:
                y = screen_y + screen_h - h
            # 检查左边界
            if x < screen_x:
                x = screen_x
            # 检查上边界
            if y < screen_y:
                y = screen_y

            # 如果位置需要调整，则移动窗口
            if x != self.x() or y != self.y():
                self.move(x, y)

        except RuntimeError:
            pass
        except Exception:
            pass

    def _calculate_max_height_for_position(self) -> int:
        """根据当前窗口位置计算最大允许高度

        确保窗口不会超出屏幕下边界

        Returns:
            最大允许高度（像素）
        """
        try:
            screen_x, screen_y, screen_w, screen_h = self._get_current_screen_bounds()
            current_y = self.y()

            # 计算从当前位置到底部屏幕边界的可用空间
            available_height = screen_y + screen_h - current_y

            # 但也不能超过屏幕高度的70%
            max_by_screen_percent = int(screen_h * 0.7)

            return min(available_height, max_by_screen_percent)

        except Exception:
            return int(QApplication.primaryScreen().availableGeometry().height() * 0.7)

    def _smooth_adjust_height(self, target_height: int, immediate: bool = False):
        """平滑调整窗口高度

        在调整窗口高度时保持原文框高度不变，只改变译文框高度

        Args:
            target_height: 目标高度
            immediate: 是否立即调整（不使用动画）
        """
        try:
            # 首先根据窗口位置计算最大允许高度（确保不超出屏幕下边界）
            max_height_for_position = self._calculate_max_height_for_position()

            # 限制目标高度不超过位置限制
            target_height = min(target_height, max_height_for_position)

            current_height = self.height()

            # 调试输出
            try:
                from src.utils.logger import log_debug
                log_debug(f"平滑调整高度: 当前={current_height}, 目标={target_height}, 最大={max_height_for_position}")
            except:
                pass

            # 如果高度差异太小，不调整
            if abs(target_height - current_height) < 5:
                return

            # 如果目标高度比当前高度小很多（超过20px），才缩小
            # 这样可以避免小幅度的抖动，但允许窗口增长
            if target_height < current_height - 20:
                return

            self._last_adjusted_height = target_height

            # 获取当前原文框高度（用户可能手动调整过）
            current_sizes = self._splitter.sizes()
            current_input_height = current_sizes[0] if current_sizes else 100

            # 计算译文框目标高度
            # 总高度 = 标题栏(28) + 控制栏(38) + 边距(40) + 原文框 + 分割条(6) + 译文框
            target_output_height = target_height - 28 - 38 - 40 - current_input_height - 6
            target_output_height = max(80, target_output_height)  # 确保最小高度

            if immediate or not self.isVisible():
                self.resize(self.width(), target_height)
                # 保持原文框高度不变
                self._splitter.setSizes([current_input_height, target_output_height])
                # 确保窗口在屏幕范围内
                self._ensure_within_screen()
                return

            # 使用动画平滑调整
            from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QSize

            if self._height_animation is None:
                self._height_animation = QPropertyAnimation(self, "size")
                self._height_animation.setDuration(150)
                self._height_animation.setEasingCurve(QEasingCurve.Type.OutQuad)

            # 停止正在进行的动画
            if self._height_animation.state() == QPropertyAnimation.State.Running:
                self._height_animation.stop()

            current_size = self.size()
            target_size = QSize(self.width(), target_height)

            self._height_animation.setStartValue(current_size)
            self._height_animation.setEndValue(target_size)
            self._height_animation.start()

            # 保持原文框高度不变
            self._splitter.setSizes([current_input_height, target_output_height])

            # 动画完成后检查屏幕边界
            QTimer.singleShot(200, self._ensure_within_screen)

        except RuntimeError:
            pass
        except Exception:
            try:
                self.resize(self.width(), target_height)
                self._ensure_within_screen()
            except:
                pass

    def _schedule_height_adjust(self):
        """调度高度调整（延迟执行，避免频繁更新）"""
        try:
            if self._height_adjust_timer is not None and self._height_adjust_timer.isActive():
                return

            from PyQt6.QtCore import QTimer
            if self._height_adjust_timer is None:
                self._height_adjust_timer = QTimer(self)
                self._height_adjust_timer.setSingleShot(True)
                self._height_adjust_timer.timeout.connect(self._do_height_adjust)

            self._height_adjust_timer.start(50)

        except RuntimeError:
            pass

    def _do_height_adjust(self):
        """执行高度调整"""
        try:
            # 调试输出
            try:
                from src.utils.logger import log_debug
                log_debug(f"_do_height_adjust: _is_streaming={self._is_streaming}, isVisible={self.isVisible()}")
            except:
                pass

            if not self._is_streaming or not self.isVisible():
                return

            target_height = self._calculate_required_height()
            max_height = self._calculate_max_height_for_position()

            # 调试输出
            try:
                from src.utils.logger import log_debug
                log_debug(f"高度调整: 当前={self.height()}, 目标={target_height}, 上次={self._last_adjusted_height}, 最大={max_height}")
            except:
                pass

            # 判断是否达到最大高度限制
            # 如果目标高度超过或接近最大高度，则显示滚动条
            if target_height >= max_height - 10 and self._scrollbar_hidden:
                self._show_output_scrollbar()
                self._scrollbar_hidden = False

            # 只要目标高度不同就尝试调整（让 _smooth_adjust_height 决定是否真正调整）
            self._smooth_adjust_height(target_height)

            # 确保窗口在屏幕范围内
            self._ensure_within_screen()

        except RuntimeError:
            pass

    def _reset_window_height(self):
        """重置窗口高度到默认值（不重置分割器比例）"""
        try:
            self._last_adjusted_height = 0
            self._is_streaming = False
            self._scrollbar_hidden = False

            if self._height_adjust_timer:
                self._height_adjust_timer.stop()
                self._height_adjust_timer = None

            from PyQt6.QtCore import QPropertyAnimation
            if self._height_animation and self._height_animation.state() == QPropertyAnimation.State.Running:
                self._height_animation.stop()

            # 恢复滚动条显示
            self._show_output_scrollbar()

            self.resize(500, 400)

            # 确保窗口在屏幕范围内
            self._ensure_within_screen()

        except RuntimeError:
            pass

    def show_result(self, result):
        """显示翻译结果（非流式）

        Args:
            result: TranslationResult 对象
        """
        if result.error:
            self._output_text.setPlainText(f"翻译失败: {result.error}")
        else:
            self._input_text.setPlainText(result.original_text)
            self._output_text.setPlainText(result.translated_text)

    def hide(self):
        """隐藏窗口"""
        # 重置自动翻译模式状态
        self._auto_mode = False
        self._pending_original_text = ""

        super().hide()
        self.closed.emit()

    def is_auto_mode(self) -> bool:
        """检查是否处于自动翻译模式"""
        return self._auto_mode

    def get_pending_text(self) -> str:
        """获取待翻译的原文"""
        return self._pending_original_text

    def _hide_output_scrollbar(self):
        """隐藏译文框滚动条（流式输出开始时）"""
        try:
            theme = get_theme(self._theme_style)
            # 使用隐藏滚动条的样式
            self._output_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: transparent;
                    color: {theme['text_primary']};
                    border: none;
                    border-radius: 4px;
                    padding: 8px;
                    font-size: {self._font_size}px;
                }}
                {get_hidden_scrollbar_style(theme)}
            """)
            self._scrollbar_hidden = True
        except RuntimeError:
            pass
        except Exception:
            pass

    def _show_output_scrollbar(self):
        """显示译文框滚动条（流式输出结束后）"""
        try:
            theme = get_theme(self._theme_style)
            # 恢复正常的滚动条样式
            self._output_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: transparent;
                    color: {theme['text_primary']};
                    border: none;
                    border-radius: 4px;
                    padding: 8px;
                    font-size: {self._font_size}px;
                }}
                {get_scrollbar_style(theme)}
            """)
            self._scrollbar_hidden = False
        except RuntimeError:
            pass
        except Exception:
            pass


# 全局翻译窗口实例
_translator_window_instance: Optional[TranslatorWindow] = None


def get_translator_window() -> TranslatorWindow:
    """获取全局翻译窗口实例"""
    global _translator_window_instance
    if _translator_window_instance is None:
        _translator_window_instance = TranslatorWindow()
    return _translator_window_instance
