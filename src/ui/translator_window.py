"""独立翻译窗口模块 - Translate Copilot（无边框风格，支持主题切换、纯文本显示）"""
import sys
from typing import Optional
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QComboBox, QFrame,
    QGraphicsDropShadowEffect, QApplication, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import QColor, QCursor, QMouseEvent, QKeySequence, QIcon, QFont

try:
    from ..utils.theme import get_theme, get_scrollbar_style, get_splitter_style, get_menu_style, get_combobox_style
    from ..config import get_config
    from ..utils.tts import get_tts
except ImportError:
    from utils.theme import get_theme, get_scrollbar_style, get_splitter_style, get_menu_style, get_combobox_style
    from config import get_config
    from utils.tts import get_tts


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
            from core.translator import get_translator
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
            from core.translator import get_translator
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
            from core.translator import get_translator
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
        self._title_label = QLabel("翻译窗口")
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
        self._splitter.addWidget(self._input_text)

        # 翻译结果显示区域 - 包装在容器中以支持右下角按钮
        self._output_container = QWidget()
        self._output_container.setStyleSheet(f"""
            QWidget {{
                background-color: transparent;
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
            }}
        """)
        self._output_layout = QVBoxLayout(self._output_container)
        self._output_layout.setContentsMargins(0, 0, 0, 0)
        self._output_layout.setSpacing(0)

        # 翻译结果文本框
        self._output_text = QTextEdit()
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
        self._output_layout.addWidget(self._output_text, 1)

        # 底部按钮区域
        self._output_button_layout = QHBoxLayout()
        self._output_button_layout.setContentsMargins(8, 0, 8, 4)
        self._output_button_layout.addStretch()

        # 朗读按钮（朗读译文）
        self._speak_output_btn = QPushButton("▶")
        self._speak_output_btn.setObjectName("speakOutputBtn")
        self._speak_output_btn.setFixedSize(20, 20)
        self._speak_output_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._speak_output_btn.setToolTip("朗读译文")
        self._speak_output_btn.setStyleSheet("""
            QPushButton#speakOutputBtn {
                background-color: transparent;
                color: #888888;
                border: none;
                border-radius: 3px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton#speakOutputBtn:hover {
                background-color: transparent;
                color: #333333;
            }
            QPushButton#speakOutputBtn:pressed {
                background-color: rgba(0, 0, 0, 0.1);
            }
        """)
        self._speak_output_btn.clicked.connect(self._speak_output)
        self._output_button_layout.addWidget(self._speak_output_btn)

        # 复制按钮
        self._copy_output_btn = QPushButton("⎘")
        self._copy_output_btn.setObjectName("copyOutputBtn")
        self._copy_output_btn.setFixedSize(20, 20)
        self._copy_output_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._copy_output_btn.setToolTip("复制译文")
        self._copy_output_btn.setStyleSheet("""
            QPushButton#copyOutputBtn {
                background-color: transparent;
                color: #888888;
                border: none;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton#copyOutputBtn:hover {
                background-color: transparent;
                color: #333333;
            }
            QPushButton#copyOutputBtn:pressed {
                background-color: rgba(0, 0, 0, 0.1);
            }
        """)
        self._copy_output_btn.clicked.connect(self._copy_all_text)
        self._output_button_layout.addWidget(self._copy_output_btn)

        self._output_layout.addLayout(self._output_button_layout)

        self._splitter.addWidget(self._output_container)

        # 设置分割器初始比例
        self._splitter.setSizes([150, 150])
        content_layout.addWidget(self._splitter, 1)

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
                background-color: transparent;
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

        # 更新复制按钮样式
        self._copy_output_btn.setStyleSheet(f"""
            QPushButton#copyOutputBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 3px;
                font-size: 11px;
            }}
            QPushButton#copyOutputBtn:hover {{
                background-color: transparent;
                color: {theme['text_primary']};
            }}
            QPushButton#copyOutputBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
        """)

        # 更新朗读按钮样式
        self._speak_output_btn.setStyleSheet(f"""
            QPushButton#speakOutputBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 3px;
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton#speakOutputBtn:hover {{
                background-color: transparent;
                color: {theme['text_primary']};
            }}
            QPushButton#speakOutputBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.1);
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
        """清空所有内容"""
        self._input_text.clear()
        self._output_text.clear()
        self._auto_mode = False
        self._pending_original_text = ""

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
            self._streaming_text += chunk
            self._output_text.setPlainText(self._streaming_text)
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
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)

            # 发出翻译完成信号（用于划词翻译模式）
            if self._auto_mode:
                original_text = self._pending_original_text or self._input_text.toPlainText()
                self.translation_completed.emit(original_text, result)

            self._current_worker = None

            # 保存翻译历史
            if result:
                try:
                    from utils.history import add_translation_history
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
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            self._current_worker = None

            # 保存润色历史
            if result:
                try:
                    from utils.history import add_translation_history
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
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            self._current_worker = None

            # 保存总结历史
            if result:
                try:
                    from utils.history import add_translation_history
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
        """事件过滤器 - 处理子控件的鼠标事件以更新光标"""
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

        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
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
        """计算悬浮窗位置"""
        x, y = mouse_pos
        screen_x, screen_y, screen_w, screen_h = self._get_screen_bounds()

        win_w = self.width()
        win_h = self.height()

        new_x = x + 15
        new_y = y + 15

        if new_x + win_w > screen_x + screen_w - 10:
            new_x = x - win_w - 15

        if new_y + win_h > screen_y + screen_h - 10:
            new_y = y - win_h - 15

        if new_x < screen_x + 10:
            new_x = screen_x + 10

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

        # 重置窗口大小
        self.resize(500, 400)

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

        if original_text:
            self._input_text.setPlainText(original_text)

        self._output_text.clear()

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

    def finish_streaming(self):
        """完成流式翻译"""
        # 滚动到顶部
        self._input_text.verticalScrollBar().setValue(0)
        self._output_text.verticalScrollBar().setValue(0)

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


# 全局翻译窗口实例
_translator_window_instance: Optional[TranslatorWindow] = None


def get_translator_window() -> TranslatorWindow:
    """获取全局翻译窗口实例"""
    global _translator_window_instance
    if _translator_window_instance is None:
        _translator_window_instance = TranslatorWindow()
    return _translator_window_instance
