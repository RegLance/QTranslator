"""悬浮窗模块 - 翻译结果显示（支持滚动、拖动、调整大小、深色/浅色主题）"""
from typing import Optional, Tuple
import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QApplication,
    QScrollArea, QSizePolicy, QSplitter
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint, QSize, pyqtSignal, QRect
from PyQt6.QtGui import QFont, QColor, QPalette, QCursor, QMouseEvent, QKeySequence, QIcon

try:
    from ..config import get_config
    from ..core.translator import TranslationResult
    from ..utils.logger import log_debug, log_error
except ImportError:
    from config import get_config
    from core.translator import TranslationResult
    from utils.logger import log_debug, log_error


# 主题样式定义
THEMES = {
    'dark': {
        'bg_color': '#2d2d2d',
        'border_color': '#3d3d3d',
        'title_color': '#888888',
        'title_hover': '#3d3d3d',
        'original_bg': '#252525',
        'original_text': '#aaaaaa',
        'result_text': '#ffffff',
        'scrollbar_bg': '#2d2d2d',
        'scrollbar_handle': '#5d5d5d',
        'scrollbar_hover': '#6d6d6d',
        'splitter_color': '#3d3d3d',
        'splitter_hover': '#5d5d5d',
        'splitter_pressed': '#6d6d6d',
        'loading_text': '#666666',
        'error_text': '#ff6b6b',
        'close_hover': '#ff6b6b',
        'shadow_color': QColor(0, 0, 0, 100),
    },
    'light': {
        'bg_color': '#f5f5f5',
        'border_color': '#e0e0e0',
        'title_color': '#888888',
        'title_hover': '#e8e8e8',
        'original_bg': '#ebebeb',
        'original_text': '#555555',
        'result_text': '#333333',
        'scrollbar_bg': '#f0f0f0',
        'scrollbar_handle': '#c0c0c0',
        'scrollbar_hover': '#a0a0a0',
        'splitter_color': '#e0e0e0',
        'splitter_hover': '#d0d0d0',
        'splitter_pressed': '#c0c0c0',
        'loading_text': '#888888',
        'error_text': '#d32f2f',
        'close_hover': '#ff6b6b',
        'shadow_color': QColor(0, 0, 0, 50),
    }
}


class PopupWindow(QWidget):
    """翻译悬浮窗

    特性：
    - 无边框、置顶显示
    - 半透明背景、圆角设计
    - 自动定位到鼠标附近
    - 支持滚动条查看长文本
    - 支持用户拖动窗口
    - 支持用户调整窗口大小
    - 支持拖动调整原文/翻译区域比例
    - 鼠标悬停时保持显示
    """

    # 信号
    closed = pyqtSignal()

    def __init__(self):
        """初始化悬浮窗"""
        super().__init__()

        # 设置窗口对象名称，用于识别
        self.setObjectName("PopupWindow")

        # 加载配置
        config = get_config()
        self._opacity = config.get('popup.opacity', 0.95)
        self._auto_close_delay = config.get('popup.auto_close_delay', 10000)  # 10秒
        self._theme_style = config.get('theme.popup_style', 'dark')

        # 窗口尺寸限制
        self._min_width = 300
        self._min_height = 200
        self._default_width = 450
        self._default_height = 350

        # 状态
        self._is_loading = False
        self._current_result: Optional[TranslationResult] = None
        self._auto_close_timer: Optional[QTimer] = None
        self._is_just_shown: bool = False

        # 拖动状态
        self._is_dragging = False
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None

        # 调整大小状态
        self._is_resizing = False
        self._resize_edge: Optional[str] = None
        self._resize_start_pos: Optional[QPoint] = None
        self._resize_start_geometry: Optional[QRect] = None

        # 阴影效果（保存引用以便更新）
        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None

        # 初始化 UI
        self._setup_ui()
        self._apply_theme(self._theme_style)
        self._setup_window_properties()
        self._setup_auto_close_timer()

    def _set_window_icon(self):
        """设置窗口图标（任务栏图标）"""
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _setup_window_properties(self):
        """设置窗口属性"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(self._opacity)

        self.setMinimumSize(self._min_width, self._min_height)
        self.resize(self._default_width, self._default_height)

        self.setMouseTracking(True)

    def _setup_ui(self):
        """设置 UI 组件"""
        # 主布局
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # 内容容器
        self._content_frame = QFrame()
        self._content_frame.setObjectName("contentFrame")
        self._content_frame.setStyleSheet("""
            QFrame#contentFrame {
                background-color: #2d2d2d;
                border-radius: 8px;
                border: 1px solid #3d3d3d;
            }
        """)
        self._layout.addWidget(self._content_frame)

        # 添加阴影效果
        self._shadow_effect = QGraphicsDropShadowEffect()
        self._shadow_effect.setBlurRadius(15)
        self._shadow_effect.setColor(QColor(0, 0, 0, 100))
        self._shadow_effect.setOffset(0, 2)
        self._content_frame.setGraphicsEffect(self._shadow_effect)

        # 内容布局
        self._content_layout = QVBoxLayout(self._content_frame)
        self._content_layout.setContentsMargins(12, 8, 12, 12)
        self._content_layout.setSpacing(0)

        # 标题栏
        self._title_bar = QFrame()
        self._title_bar.setObjectName("titleBar")
        self._title_bar.setFixedHeight(24)
        self._title_bar.setStyleSheet("""
            QFrame#titleBar {
                background-color: transparent;
                border-bottom: 1px solid #3d3d3d;
            }
            QFrame#titleBar:hover {
                background-color: #3d3d3d;
            }
        """)
        self._title_bar.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(8, 0, 8, 0)

        self._title_label = QLabel("翻译结果")
        self._title_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 12px;
            }
        """)
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setStyleSheet("""
            QPushButton#closeBtn {
                background-color: transparent;
                color: #888888;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#closeBtn:hover {
                background-color: #ff6b6b;
                color: #ffffff;
            }
        """)
        self._close_btn.clicked.connect(self.hide)
        title_layout.addWidget(self._close_btn)

        self._content_layout.addWidget(self._title_bar)

        # 分割器 - 让用户可以调整原文和翻译结果的比例
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #3d3d3d;
                height: 6px;
                margin: 2px 0px;
                border-radius: 3px;
            }
            QSplitter::handle:hover {
                background-color: #5d5d5d;
            }
            QSplitter::handle:pressed {
                background-color: #6d6d6d;
            }
        """)
        self._splitter.setHandleWidth(6)
        self._splitter.setChildrenCollapsible(False)  # 防止完全折叠

        # ===== 原文滚动区域 =====
        self._original_scroll = QScrollArea()
        self._original_scroll.setObjectName("originalScroll")
        self._original_scroll.setStyleSheet("""
            QScrollArea#originalScroll {
                background-color: transparent;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
            }
            QScrollArea#originalScroll > QWidget > QWidget {
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #5d5d5d;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6d6d6d;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background-color: transparent;
            }
        """)
        self._original_scroll.setWidgetResizable(True)
        self._original_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._original_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._original_scroll.setMinimumHeight(60)

        # 原文容器
        self._original_container = QWidget()
        self._original_container.setStyleSheet("background-color: #252525; border-radius: 4px;")
        self._original_inner_layout = QVBoxLayout(self._original_container)
        self._original_inner_layout.setContentsMargins(8, 8, 8, 8)

        # 原文标签
        self._original_label = QLabel()
        self._original_label.setObjectName("originalLabel")
        self._original_label.setStyleSheet("""
            QLabel#originalLabel {
                color: #aaaaaa;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        self._original_label.setWordWrap(True)
        self._original_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._original_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._original_label.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
        self._original_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._original_label.customContextMenuRequested.connect(self._show_original_context_menu)
        self._original_inner_layout.addWidget(self._original_label)

        self._original_scroll.setWidget(self._original_container)
        self._splitter.addWidget(self._original_scroll)

        # ===== 翻译结果滚动区域 =====
        self._result_scroll = QScrollArea()
        self._result_scroll.setObjectName("resultScroll")
        self._result_scroll.setStyleSheet("""
            QScrollArea#resultScroll {
                background-color: transparent;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
            }
            QScrollArea#resultScroll > QWidget > QWidget {
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #5d5d5d;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6d6d6d;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background-color: transparent;
            }
        """)
        self._result_scroll.setWidgetResizable(True)
        self._result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._result_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._result_scroll.setMinimumHeight(50)  # 降低最小高度，使窗口更紧凑

        # 翻译结果容器
        self._result_container = QWidget()
        self._result_container.setStyleSheet("background-color: transparent;")
        self._result_inner_layout = QVBoxLayout(self._result_container)
        self._result_inner_layout.setContentsMargins(8, 8, 8, 8)

        # 翻译结果标签
        self._result_label = QLabel()
        self._result_label.setObjectName("resultLabel")
        self._result_label.setStyleSheet("""
            QLabel#resultLabel {
                color: #ffffff;
                font-size: 14px;
                line-height: 1.6;
            }
        """)
        self._result_label.setWordWrap(True)
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._result_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._result_label.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
        self._result_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._result_label.customContextMenuRequested.connect(self._show_result_context_menu)
        self._result_inner_layout.addWidget(self._result_label)

        self._result_scroll.setWidget(self._result_container)
        self._splitter.addWidget(self._result_scroll)

        # 设置分割器初始比例 (原文:翻译 = 1:3)
        self._splitter.setSizes([100, 300])
        self._content_layout.addWidget(self._splitter, 1)

        # 加载动画标签
        self._loading_label = QLabel("正在翻译...")
        self._loading_label.setObjectName("loadingLabel")
        self._loading_label.setStyleSheet("""
            QLabel#loadingLabel {
                color: #666666;
                font-size: 13px;
                padding: 20px;
            }
        """)
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_layout.addWidget(self._loading_label)
        self._loading_label.hide()

        # 错误标签
        self._error_label = QLabel()
        self._error_label.setObjectName("errorLabel")
        self._error_label.setStyleSheet("""
            QLabel#errorLabel {
                color: #ff6b6b;
                font-size: 13px;
                padding: 10px;
            }
        """)
        self._error_label.setWordWrap(True)
        self._content_layout.addWidget(self._error_label)
        self._error_label.hide()

    def _setup_auto_close_timer(self):
        """设置自动关闭计时器"""
        self._auto_close_timer = QTimer()
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self._on_auto_close)

    def _apply_theme(self, theme_name: str):
        """应用主题样式"""
        theme = THEMES.get(theme_name, THEMES['dark'])

        # 内容容器样式
        self._content_frame.setStyleSheet(f"""
            QFrame#contentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 8px;
                border: 1px solid {theme['border_color']};
            }}
        """)

        # 更新阴影效果
        if self._shadow_effect:
            self._shadow_effect.setColor(theme['shadow_color'])

        # 标题栏样式
        self._title_bar.setStyleSheet(f"""
            QFrame#titleBar {{
                background-color: transparent;
                border-bottom: 1px solid {theme['border_color']};
            }}
            QFrame#titleBar:hover {{
                background-color: {theme['title_hover']};
            }}
        """)

        # 标题标签样式
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['title_color']};
                font-size: 12px;
            }}
        """)

        # 关闭按钮样式
        self._close_btn.setStyleSheet(f"""
            QPushButton#closeBtn {{
                background-color: transparent;
                color: {theme['title_color']};
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

        # 分割器样式
        self._splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {theme['splitter_color']};
                height: 6px;
                margin: 2px 0px;
                border-radius: 3px;
            }}
            QSplitter::handle:hover {{
                background-color: {theme['splitter_hover']};
            }}
            QSplitter::handle:pressed {{
                background-color: {theme['splitter_pressed']};
            }}
        """)

        # 原文滚动区域样式
        self._original_scroll.setStyleSheet(f"""
            QScrollArea#originalScroll {{
                background-color: transparent;
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
            }}
            QScrollArea#originalScroll > QWidget > QWidget {{
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background-color: {theme['scrollbar_bg']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme['scrollbar_handle']};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme['scrollbar_hover']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background-color: transparent;
            }}
        """)

        # 原文容器样式
        self._original_container.setStyleSheet(f"background-color: {theme['original_bg']}; border-radius: 4px;")

        # 原文标签样式
        self._original_label.setStyleSheet(f"""
            QLabel#originalLabel {{
                color: {theme['original_text']};
                font-size: 13px;
                line-height: 1.5;
            }}
        """)

        # 翻译结果滚动区域样式
        self._result_scroll.setStyleSheet(f"""
            QScrollArea#resultScroll {{
                background-color: transparent;
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
            }}
            QScrollArea#resultScroll > QWidget > QWidget {{
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background-color: {theme['scrollbar_bg']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme['scrollbar_handle']};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme['scrollbar_hover']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background-color: transparent;
            }}
        """)

        # 翻译结果标签样式
        self._result_label.setStyleSheet(f"""
            QLabel#resultLabel {{
                color: {theme['result_text']};
                font-size: 14px;
                line-height: 1.6;
            }}
        """)

        # 加载标签样式
        self._loading_label.setStyleSheet(f"""
            QLabel#loadingLabel {{
                color: {theme['loading_text']};
                font-size: 13px;
                padding: 20px;
            }}
        """)

        # 错误标签样式
        self._error_label.setStyleSheet(f"""
            QLabel#errorLabel {{
                color: {theme['error_text']};
                font-size: 13px;
                padding: 10px;
            }}
        """)

    def _get_screen_bounds(self) -> Tuple[int, int, int, int]:
        """获取屏幕可用区域"""
        try:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableVirtualGeometry()
                return (geo.x(), geo.y(), geo.width(), geo.height())
        except Exception:
            pass
        return (0, 0, 1920, 1080)

    def _calculate_position(self, mouse_pos: Tuple[int, int]) -> Tuple[int, int]:
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

    def _ensure_within_screen(self):
        """确保窗口在屏幕范围内"""
        screen_x, screen_y, screen_w, screen_h = self._get_screen_bounds()
        x, y = self.x(), self.y()
        w, h = self.width(), self.height()

        if x + w > screen_x + screen_w - 5:
            x = screen_x + screen_w - w - 5
        if y + h > screen_y + screen_h - 5:
            y = screen_y + screen_h - h - 5
        if x < screen_x + 5:
            x = screen_x + 5
        if y < screen_y + 5:
            y = screen_y + 5

        self.move(x, y)

    def show_at_mouse(self, mouse_pos: Tuple[int, int] = None):
        """在鼠标位置显示悬浮窗"""
        log_debug("PopupWindow.show_at_mouse() 被调用")
        if mouse_pos is None:
            mouse_pos = (QCursor.pos().x(), QCursor.pos().y())

        # 每次显示时重新加载主题配置
        config = get_config()
        new_theme = config.get('theme.popup_style', 'dark')
        if new_theme != self._theme_style:
            self._theme_style = new_theme
            self._apply_theme(self._theme_style)

        self.resize(self._default_width, self._default_height)
        
        # 重置分割器比例
        self._splitter.setSizes([100, 300])

        x, y = self._calculate_position(mouse_pos)
        self.move(x, y)
        self._is_just_shown = True
        self.show()
        self.raise_()

        self._auto_close_timer.start(self._auto_close_delay)
        log_debug(f"PopupWindow 显示在 ({x}, {y})")

        QTimer.singleShot(800, self._reset_just_shown)

    def show_loading(self, original_text: str = None):
        """显示加载状态"""
        self._is_loading = True
        self._current_result = None

        if original_text:
            self._original_label.setText(original_text)
            self._original_scroll.show()
        else:
            self._original_scroll.hide()

        self._loading_label.show()
        self._result_scroll.hide()
        self._error_label.hide()

    def show_streaming_start(self, original_text: str = None):
        """开始流式翻译显示"""
        self._is_loading = False
        self._current_result = None
        self._streaming_text = ""
        self._result_shown = False  # 标记翻译结果是否已显示

        # 显示原文
        if original_text:
            self._original_label.setText(original_text)
            self._original_scroll.show()
        else:
            self._original_scroll.hide()

        # 清空翻译结果，但暂时隐藏输出区域（等待实际翻译内容）
        self._result_label.setText("")
        self._result_scroll.hide()  # 隐藏翻译结果区域，等待实际内容
        self._loading_label.hide()
        self._error_label.hide()

        # 窗口大小暂时只适应原文区域
        self._adjust_initial_window_height()

    def append_translation_text(self, chunk: str):
        """追加流式翻译文本"""
        if not hasattr(self, '_streaming_text'):
            self._streaming_text = ""
            self._result_shown = False

        self._streaming_text += chunk
        self._result_label.setText(self._streaming_text)

        # 首次收到翻译内容时，显示翻译结果区域
        if not self._result_shown:
            self._result_shown = True
            self._result_scroll.show()

        # 延迟调整窗口高度，确保 UI 已更新
        QTimer.singleShot(50, self._adjust_window_height)

    def finish_streaming(self):
        """完成流式翻译"""
        # 滚动到顶部
        self._original_scroll.verticalScrollBar().setValue(0)
        self._result_scroll.verticalScrollBar().setValue(0)

        # 最终调整窗口大小
        QTimer.singleShot(100, self._adjust_window_height)

        # 重置自动关闭计时器
        self._auto_close_timer.start(self._auto_close_delay)

    def _adjust_initial_window_height(self):
        """调整初始窗口高度（只有原文区域时）"""
        try:
            # 获取屏幕尺寸
            screen_x, screen_y, screen_w, screen_h = self._get_screen_bounds()

            # 最大允许高度（屏幕高度的50%）
            max_height = int(screen_h * 0.5)

            # 标题高度
            title_height = 24
            margin = 30

            # 原文区域高度
            original_height = 80
            if self._original_scroll.isVisible():
                original_text = self._original_label.text()
                from PyQt6.QtGui import QFontMetrics
                original_font = self._original_label.font()
                fm = QFontMetrics(original_font)

                # 估算原文行数
                lines = original_text.split('\n')
                total_lines = 0
                char_width = fm.horizontalAdvance('M')
                if char_width > 0:
                    chars_per_line = max(20, (self.width() - 40) // char_width)
                    for line in lines:
                        if len(line) == 0:
                            total_lines += 1
                        else:
                            total_lines += (len(line) + chars_per_line - 1) // chars_per_line
                else:
                    total_lines = len(lines)

                line_height = fm.lineSpacing()
                original_height = min(120, total_lines * line_height + 20)

            # 总高度 = 标题 + 原文 + 边距（没有翻译结果区域）
            total_height = title_height + original_height + margin

            # 限制在合理范围内
            total_height = max(self._min_height, min(total_height, max_height))

            # 保持当前宽度，只调整高度
            self.resize(self.width(), int(total_height))

        except Exception as e:
            log_error(f"调整初始窗口高度失败: {e}")
            self.resize(self._default_width, self._min_height)

    def _adjust_window_height(self):
        """根据内容动态调整窗口高度"""
        try:
            # 获取屏幕尺寸
            screen_x, screen_y, screen_w, screen_h = self._get_screen_bounds()

            # 最大允许高度（屏幕高度的50%）
            max_height = int(screen_h * 0.5)

            # 使用 QFontMetrics 计算文本高度
            from PyQt6.QtGui import QFontMetrics
            result_font = self._result_label.font()
            fm = QFontMetrics(result_font)

            # 计算翻译文本所需高度
            text = self._result_label.text()
            if not text:
                return

            # 估算行数（每行约容纳的字符数）
            char_width = fm.horizontalAdvance('M')  # 平均字符宽度
            if char_width > 0:
                chars_per_line = (self.width() - 40) // char_width
                chars_per_line = max(20, chars_per_line)  # 至少20个字符

                # 估算行数
                lines = text.split('\n')
                total_lines = 0
                for line in lines:
                    if len(line) == 0:
                        total_lines += 1
                    else:
                        total_lines += (len(line) + chars_per_line - 1) // chars_per_line

                # 计算高度
                line_height = fm.lineSpacing()
                result_height = total_lines * line_height + 30
                # 确保最小高度，避免一开始太小
                result_height = max(50, result_height)
            else:
                result_height = 100

            # 原文区域高度（固定或简单计算）
            original_height = 80
            if self._original_scroll.isVisible():
                original_text = self._original_label.text()
                original_lines = len(original_text.split('\n'))
                original_height = min(100, original_lines * 20 + 20)

            # 总高度 = 标题 + 原文 + 分隔条 + 翻译 + 边距
            title_height = 24
            splitter_height = 10
            margin = 30

            total_height = title_height + original_height + splitter_height + result_height + margin

            # 限制在合理范围内
            total_height = max(self._min_height, min(total_height, max_height))

            # 保持当前宽度，只调整高度
            self.resize(self.width(), int(total_height))

        except Exception as e:
            log_error(f"调整窗口高度失败: {e}")

    def show_result(self, result: TranslationResult):
        """显示翻译结果（非流式）"""
        self._is_loading = False
        self._current_result = result

        self._loading_label.hide()

        if result.error:
            self._error_label.setText(f"翻译失败: {result.error}")
            self._error_label.show()
            self._result_scroll.hide()
            self._original_scroll.hide()
        else:
            # 显示原文
            self._original_label.setText(result.original_text)
            self._original_scroll.show()

            # 显示翻译结果
            self._result_label.setText(result.translated_text)
            self._result_scroll.show()
            self._error_label.hide()

            # 滚动到顶部
            self._original_scroll.verticalScrollBar().setValue(0)
            self._result_scroll.verticalScrollBar().setValue(0)

        self._auto_close_timer.start(self._auto_close_delay)

    def hide(self):
        """隐藏悬浮窗"""
        log_debug("PopupWindow.hide() 被调用")
        self._auto_close_timer.stop()
        super().hide()
        self.closed.emit()

    def _on_auto_close(self):
        """自动关闭处理"""
        log_debug("PopupWindow._on_auto_close 触发")
        self.hide()

    def _reset_just_shown(self):
        """重置刚显示状态"""
        log_debug("PopupWindow._reset_just_shown 刚显示状态已重置")
        self._is_just_shown = False

    def _get_resize_edge(self, pos: QPoint) -> Optional[str]:
        """判断鼠标位置对应的调整边缘"""
        margin = 8
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()

        edge = None

        if x <= margin and y <= margin:
            edge = 'top-left'
        elif x >= w - margin and y <= margin:
            edge = 'top-right'
        elif x <= margin and y >= h - margin:
            edge = 'bottom-left'
        elif x >= w - margin and y >= h - margin:
            edge = 'bottom-right'
        elif x <= margin:
            edge = 'left'
        elif x >= w - margin:
            edge = 'right'
        elif y <= margin:
            edge = 'top'
        elif y >= h - margin:
            edge = 'bottom'

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

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            if self._title_bar.geometry().contains(int(pos.x()), int(pos.y())):
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_window_start_pos = self.pos()
                log_debug("开始拖动窗口")
            else:
                edge = self._get_resize_edge(event.position().toPoint())
                if edge:
                    self._is_resizing = True
                    self._resize_edge = edge
                    self._resize_start_pos = event.globalPosition().toPoint()
                    self._resize_start_geometry = self.geometry()
                    log_debug(f"开始调整大小: {edge}")

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件"""
        if self._is_dragging and self._drag_start_pos:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            new_pos = self._drag_window_start_pos + delta
            self.move(new_pos)
            self._ensure_within_screen()

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

            new_w = max(self._min_width, new_w)
            new_h = max(self._min_height, new_h)

            if 'left' in edge:
                new_x = geo.x() + geo.width() - new_w

            if 'top' in edge:
                new_y = geo.y() + geo.height() - new_h

            self.setGeometry(new_x, new_y, new_w, new_h)
            self._ensure_within_screen()

        else:
            edge = self._get_resize_edge(event.position().toPoint())
            self._update_cursor_for_edge(edge)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging:
                log_debug("结束拖动窗口")
                self._is_dragging = False
                self._drag_start_pos = None
            if self._is_resizing:
                log_debug("结束调整大小")
                self._is_resizing = False
                self._resize_edge = None

        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        """鼠标进入事件"""
        log_debug("PopupWindow.enterEvent 鼠标进入窗口")
        self._auto_close_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        if self._is_just_shown:
            log_debug("PopupWindow.leaveEvent 被忽略（刚显示状态）")
            super().leaveEvent(event)
            return

        # 检查是否启用了鼠标离开自动关闭
        config = get_config()
        auto_close_on_leave = config.get('popup.auto_close_on_leave', True)

        if auto_close_on_leave:
            log_debug("PopupWindow.leaveEvent 鼠标离开窗口，3秒后关闭")
            self._auto_close_timer.start(3000)
        else:
            log_debug("PopupWindow.leaveEvent 鼠标离开窗口，自动关闭已禁用")

        super().leaveEvent(event)

    def _show_original_context_menu(self, pos):
        """显示原文右键菜单"""
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                color: #e0e0e0;
                padding: 6px 20px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background-color: #0078d4;
                border-radius: 3px;
            }
        """)

        # 复制选中文本
        copy_action = menu.addAction("复制")
        copy_action.triggered.connect(lambda: self._copy_selected_text(self._original_label))

        # 复制全部原文
        copy_all_action = menu.addAction("复制全部原文")
        copy_all_action.triggered.connect(self._copy_all_original)

        menu.addSeparator()

        # 复制全部（原文+译文）
        copy_both_action = menu.addAction("复制原文和译文")
        copy_both_action.triggered.connect(self._copy_all_text)

        menu.exec(self._original_label.mapToGlobal(pos))

    def _show_result_context_menu(self, pos):
        """显示译文右键菜单"""
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                color: #e0e0e0;
                padding: 6px 20px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background-color: #0078d4;
                border-radius: 3px;
            }
        """)

        # 复制选中文本
        copy_action = menu.addAction("复制")
        copy_action.triggered.connect(lambda: self._copy_selected_text(self._result_label))

        # 复制全部译文
        copy_all_action = menu.addAction("复制全部译文")
        copy_all_action.triggered.connect(self._copy_all_result)

        menu.addSeparator()

        # 复制全部（原文+译文）
        copy_both_action = menu.addAction("复制原文和译文")
        copy_both_action.triggered.connect(self._copy_all_text)

        menu.exec(self._result_label.mapToGlobal(pos))

    def _copy_selected_text(self, label: QLabel):
        """复制标签中选中的文本"""
        from PyQt6.QtWidgets import QApplication
        selected_text = label.selectedText()
        if selected_text:
            clipboard = QApplication.clipboard()
            clipboard.setText(selected_text)

    def _copy_all_original(self):
        """复制全部原文"""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self._original_label.text())

    def _copy_all_result(self):
        """复制全部译文"""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self._result_label.text())

    def _copy_all_text(self):
        """复制原文和译文"""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        text = f"原文：\n{self._original_label.text()}\n\n译文：\n{self._result_label.text()}"
        clipboard.setText(text)

    def keyPressEvent(self, event):
        """键盘事件处理"""
        # Ctrl+C: 复制选中内容
        if event.matches(QKeySequence.StandardKey.Copy):
            # 检查哪个标签有选中内容
            original_selected = self._original_label.selectedText()
            result_selected = self._result_label.selectedText()
            
            if original_selected:
                self._copy_selected_text(self._original_label)
            elif result_selected:
                self._copy_selected_text(self._result_label)
            else:
                # 默认复制译文
                self._copy_all_result()
            return

        # Escape: 隐藏窗口
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return

        super().keyPressEvent(event)


# 全局悬浮窗实例
_popup_instance: Optional[PopupWindow] = None


def get_popup_window() -> PopupWindow:
    """获取全局悬浮窗实例"""
    global _popup_instance
    if _popup_instance is None:
        _popup_instance = PopupWindow()
    return _popup_instance