"""QTranslator - 主入口文件"""
import sys
import os
import time
import traceback
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFormLayout, QComboBox,
    QCheckBox, QGroupBox, QMessageBox, QSizePolicy, QFrame,
    QGraphicsDropShadowEffect, QScrollArea, QMenu, QWidget,
    QSpinBox, QKeySequenceEdit, QColorDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QPoint, QTimer, QPropertyAnimation, QRect, QByteArray
from PyQt6.QtGui import QFont, QColor, QCursor, QMouseEvent, QAction, QIcon, QPixmap, QPainter, QPen, QKeySequence, QPalette, QPolygonF, QBrush
from PyQt6.QtCore import QPointF
from PyQt6.QtSvg import QSvgRenderer

# 设置高 DPI 支持
if sys.platform == 'win32':
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwareness(2)
    except Exception:
        pass


# ============================================================================
# 自定义 SpinBox 组件（带三角形箭头）
# ============================================================================

class StyledSpinBox(QSpinBox):
    """带自定义小箭头的 SpinBox（精致对称设计）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._arrow_color = QColor('#999999')
        self._hover_color = QColor('#cccccc')
        self._pressed_color = QColor('#ffffff')
        self._up_hover = False
        self._down_hover = False
        self._up_pressed = False
        self._down_pressed = False

    def set_arrow_color(self, color: str):
        """设置箭头颜色"""
        self._arrow_color = QColor(color)

    def _get_button_rects(self):
        """计算上下按钮的矩形区域（对称布局）"""
        btn_width = 18
        rect = self.rect()
        right = rect.right() - 1
        top = rect.top() + 1
        half_h = rect.height() // 2

        up_rect = QRect(right - btn_width, top, btn_width, half_h)
        down_rect = QRect(right - btn_width, top + half_h, btn_width, rect.height() - half_h - 1)
        return up_rect, down_rect

    def paintEvent(self, event):
        """自定义绘制事件"""
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        up_rect, down_rect = self._get_button_rects()

        # 绘制上箭头
        up_color = self._pressed_color if self._up_pressed else (self._hover_color if self._up_hover else self._arrow_color)
        self._draw_arrow(painter, up_rect, 'up', up_color)

        # 绘制下箭头
        down_color = self._pressed_color if self._down_pressed else (self._hover_color if self._down_hover else self._arrow_color)
        self._draw_arrow(painter, down_rect, 'down', down_color)

    def _draw_arrow(self, painter: QPainter, rect: QRect, direction: str, color: QColor):
        """绘制精致小三角形箭头（箭头靠右，左右留白对称）"""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))

        polygon = QPolygonF()
        # 箭头中心往右偏1.5px，补偿 border-left 分隔线，使箭头左右留白对称
        cx = rect.center().x() + 1.5
        cy = rect.center().y()
        w = 3.5   # 半宽
        h = 2.5   # 半高

        if direction == 'up':
            polygon.append(QPointF(cx, cy - h))
            polygon.append(QPointF(cx - w, cy + h))
            polygon.append(QPointF(cx + w, cy + h))
        else:
            polygon.append(QPointF(cx - w, cy - h))
            polygon.append(QPointF(cx + w, cy - h))
            polygon.append(QPointF(cx, cy + h))

        painter.drawPolygon(polygon)

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        up_rect, down_rect = self._get_button_rects()

        if up_rect.contains(event.pos()):
            self._up_pressed = True
            self.stepUp()
            self.update()
            return
        elif down_rect.contains(event.pos()):
            self._down_pressed = True
            self.stepDown()
            self.update()
            return

        super().mousePressEvent(event)
        self.update()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        self._up_pressed = False
        self._down_pressed = False
        super().mouseReleaseEvent(event)
        self.update()

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        up_rect, down_rect = self._get_button_rects()

        old_up_hover = self._up_hover
        old_down_hover = self._down_hover

        self._up_hover = up_rect.contains(event.pos())
        self._down_hover = down_rect.contains(event.pos())

        if old_up_hover != self._up_hover or old_down_hover != self._down_hover:
            self.update()

        super().mouseMoveEvent(event)


# ============================================================================
# 全局异常处理器和闪退日志机制
# ============================================================================

class CrashHandler:
    """闪退处理和日志记录器"""

    _instance: Optional['CrashHandler'] = None
    _crash_log_path: Optional[Path] = None

    @classmethod
    def initialize(cls):
        """初始化闪退处理器"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        # 获取崩溃日志路径
        try:
            # 尝试从配置获取路径
            if sys.platform == 'win32':
                base_dir = Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')))
                app_dir = base_dir / "QTranslator"
            else:
                app_dir = Path.home() / ".config" / "qtranslator"

            app_dir.mkdir(parents=True, exist_ok=True)
            self._crash_log_path = app_dir / "crash.log"
        except Exception:
            # 如果无法创建目录，使用临时目录
            import tempfile
            self._crash_log_path = Path(tempfile.gettempdir()) / "qtranslator_crash.log"

        # 设置全局异常处理器
        self._setup_exception_hooks()

    def _setup_exception_hooks(self):
        """设置全局异常钩子"""
        # 设置 sys.excepthook 处理主线程异常
        sys.excepthook = self._handle_exception

        # 处理 Qt 信号槽中的异常
        try:
            # PyQt6 没有直接的异常钩子，我们需要通过其他方式
            # 但可以设置线程异常钩子
            threading.excepthook = self._handle_threading_exception
        except AttributeError:
            # Python 3.7 以下版本没有 threading.excepthook
            pass

    def _handle_exception(self, exc_type, exc_value, exc_traceback):
        """处理主线程异常"""
        # 先记录日志
        self._log_crash(exc_type, exc_value, exc_traceback, "MainThread")

        # 调用默认处理器（显示错误对话框或退出）
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def _handle_threading_exception(self, args):
        """处理线程异常 (Python 3.8+)"""
        # args 是 threading.ExceptHookArgs 类型
        self._log_crash(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            args.thread.name if args.thread else "UnknownThread"
        )
        # 调用默认处理器
        threading.__excepthook__(args)

    def _log_crash(self, exc_type, exc_value, exc_traceback, thread_name: str):
        """记录崩溃日志"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 格式化异常信息
            exc_info = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

            # 写入崩溃日志
            with open(self._crash_log_path, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{timestamp}] CRASH DETECTED\n")
                f.write(f"Thread: {thread_name}\n")
                f.write(f"{'='*60}\n")
                f.write(exc_info)
                f.write(f"\n{'='*60}\n")

            print(f"\n崩溃日志已写入: {self._crash_log_path}", file=sys.stderr)
            print(f"崩溃详情:\n{exc_info}", file=sys.stderr)

        except Exception as e:
            print(f"写入崩溃日志失败: {e}", file=sys.stderr)
            print(f"崩溃详情:\n{exc_info}", file=sys.stderr)

    @property
    def crash_log_path(self) -> Path:
        return self._crash_log_path


def log_exception_safe(message: str, exc: Exception):
    """安全地记录异常（避免日志记录本身崩溃）"""
    try:
        crash_handler = CrashHandler.initialize()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        exc_info = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        with open(crash_handler.crash_log_path, 'a', encoding='utf-8') as f:
            f.write(f"\n[{timestamp}] {message}\n")
            f.write(f"Exception: {exc_info}\n")
    except Exception:
        pass


# 在导入模块前初始化闪退处理器
CrashHandler.initialize()

# 支持两种导入方式
try:
    from .config import get_config, APP_NAME
    from .core.text_capture import get_text_capture, capture_text_direct
    from .core.selection_detector import get_selection_detector
    from .core.translator import get_translator, reinitialize_translator
    from .core.writing import get_writing_service, WritingResult
    from .ui.translate_button import get_translate_button
    from .ui.tray_icon import get_tray_icon
    from .ui.translator_window import get_translator_window
    from .ui.history_window import get_history_window
    from .ui.help_window import get_help_window
    from .ui.splash_screen import show_splash_screen
    from .utils.logger import get_logger, log_info, log_error, log_debug
    from .utils.history import add_translation_history
    from .utils.theme import get_theme, get_scrollbar_style, get_lineedit_style, get_combobox_style, get_checkbox_style, get_spinbox_style, THEME_DISPLAY_NAMES
    from .utils.hotkey_manager import get_hotkey_manager
except ImportError:
    # 打包后的导入路径
    from src.config import get_config, APP_NAME
    from src.core.text_capture import get_text_capture, capture_text_direct
    from src.core.selection_detector import get_selection_detector
    from src.core.translator import get_translator, reinitialize_translator
    from src.core.writing import get_writing_service, WritingResult
    from src.ui.translate_button import get_translate_button
    from src.ui.tray_icon import get_tray_icon
    from src.ui.translator_window import get_translator_window
    from src.ui.history_window import get_history_window
    from src.ui.help_window import get_help_window
    from src.ui.splash_screen import show_splash_screen
    from src.utils.logger import get_logger, log_info, log_error, log_debug
    from src.utils.history import add_translation_history
    from src.utils.theme import get_theme, get_scrollbar_style, get_lineedit_style, get_combobox_style, get_checkbox_style, get_spinbox_style, THEME_DISPLAY_NAMES
    from src.utils.hotkey_manager import get_hotkey_manager


def setup_auto_start(enable: bool):
    """设置开机自启（Windows）"""
    if sys.platform != 'win32':
        return False
    
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_id = APP_NAME.replace(" ", "")
        
        if enable:
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
            else:
                main_py = Path(__file__).parent.parent / "__main__.py"
                exe_path = f'"{sys.executable}" "{main_py}"'
            
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, app_id, 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            return True
        else:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(key, app_id)
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass
            return True
    except Exception as e:
        log_error(f"设置开机自启失败: {e}")
        return False


class SettingsDialog(QDialog):
    """设置对话框（无边框风格）"""

    def __init__(self):
        super().__init__()

        # 设置窗口对象名称，用于识别
        self.setObjectName("SettingsDialog")

        # 拖动状态
        self._is_dragging = False
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None

        # 主题
        self._theme = get_theme()

        # 设置无边框窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(480, 620)
        self.resize(500, 680)

        self._config = get_config()
        self._setup_ui()
        self._load_settings()

        # 应用主题
        self._apply_theme()
        # 居中显示

        self._center_window()

    def _center_window(self):
        """窗口居中显示"""
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2 + screen_geo.x()
            y = (screen_geo.height() - self.height()) // 2 + screen_geo.y()
            self.move(x, y)

    def _setup_ui(self):
        """设置UI（无边框风格）- 只创建控件，样式由 _apply_theme 设置"""
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 内容容器
        self._content_frame = QFrame()
        self._content_frame.setObjectName("contentFrame")
        layout.addWidget(self._content_frame)

        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 2)
        self._content_frame.setGraphicsEffect(shadow)

        # 内容布局
        content_layout = QVBoxLayout(self._content_frame)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(12)

        # 标题栏
        self._title_bar = QFrame()
        self._title_bar.setObjectName("titleBar")
        self._title_bar.setFixedHeight(28)
        # 不设置整体光标，在 mouseMoveEvent 中动态控制

        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(8, 0, 8, 0)

        # 标题文字
        self._title_label = QLabel("设置")
        self._title_label.setObjectName("titleLabel")
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        # 关闭按钮
        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.clicked.connect(self.reject)
        title_layout.addWidget(self._close_btn)

        content_layout.addWidget(self._title_bar)

        # 滚动区域
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 滚动内容容器
        self._scroll_content = QWidget()
        scroll_layout = QVBoxLayout(self._scroll_content)
        scroll_layout.setSpacing(16)
        scroll_layout.setContentsMargins(8, 8, 8, 16)  # 底部增加边距避免视觉截断

        # API 配置组
        self._api_group = QGroupBox("API 配置")
        api_layout = QFormLayout(self._api_group)
        api_layout.setSpacing(10)
        api_layout.setContentsMargins(12, 20, 12, 12)
        api_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._api_url_edit = QLineEdit()
        self._api_url_edit.setMinimumHeight(32)
        self._api_url_edit.setPlaceholderText("https://api.openai.com/v1")
        self._api_url_label = QLabel("Base URL:")
        api_layout.addRow(self._api_url_label, self._api_url_edit)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setMinimumHeight(32)
        self._api_key_edit.setPlaceholderText("sk-...")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        # 设置右侧边距，为眼睛按钮留出空间
        self._api_key_edit.setTextMargins(0, 0, 32, 0)
        self._api_key_label = QLabel("API Key:")
        
        # 创建眼睛按钮（作为 QAction 添加到输入框内部）
        self._api_key_toggle_action = QAction(self._api_key_edit)
        self._api_key_toggle_action.setIcon(self._get_eye_icon(False))  # 默认显示闭眼图标
        self._api_key_toggle_action.triggered.connect(self._toggle_api_key_visibility)
        self._api_key_edit.addAction(self._api_key_toggle_action, QLineEdit.ActionPosition.TrailingPosition)
        
        api_layout.addRow(self._api_key_label, self._api_key_edit)

        self._model_edit = QLineEdit()
        self._model_edit.setMinimumHeight(32)
        self._model_edit.setPlaceholderText("gpt-4o-mini")
        self._model_label = QLabel("Model:")
        api_layout.addRow(self._model_label, self._model_edit)

        # 添加说明文字
        self._model_hint_label = QLabel("推荐使用Instruct模型，Thinking模型响应会比较慢")
        self._model_hint_label.setProperty("class", "hint")
        self._model_hint_label.setWordWrap(True)
        api_layout.addRow("", self._model_hint_label)

        self._no_proxy_edit = QLineEdit()
        self._no_proxy_edit.setMinimumHeight(32)
        self._no_proxy_edit.setPlaceholderText("localhost,127.0.0.1")
        self._no_proxy_label = QLabel("No Proxy:")
        api_layout.addRow(self._no_proxy_label, self._no_proxy_edit)

        scroll_layout.addWidget(self._api_group)

        # 翻译设置组
        self._trans_group = QGroupBox("翻译设置")
        trans_layout = QFormLayout(self._trans_group)
        trans_layout.setSpacing(10)
        trans_layout.setContentsMargins(12, 20, 12, 12)
        trans_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._browser_delay_spin = StyledSpinBox()
        self._browser_delay_spin.setRange(0, 2000)
        self._browser_delay_spin.setValue(450)
        self._browser_delay_spin.setMinimumHeight(32)
        self._browser_delay_spin.setSuffix(" ms")
        self._browser_delay_label = QLabel("浏览器划词延迟:")
        trans_layout.addRow(self._browser_delay_label, self._browser_delay_spin)

        scroll_layout.addWidget(self._trans_group)

        # 外观设置组
        self._theme_group = QGroupBox("外观设置")
        theme_layout = QFormLayout(self._theme_group)
        theme_layout.setSpacing(10)
        theme_layout.setContentsMargins(12, 20, 12, 12)
        theme_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 主题选择下拉框（使用 THEME_DISPLAY_NAMES 填充）
        self._theme_keys = list(THEME_DISPLAY_NAMES.keys())
        self._popup_style_combo = QComboBox()
        self._popup_style_combo.addItems(list(THEME_DISPLAY_NAMES.values()))
        self._popup_style_combo.setMinimumHeight(32)
        self._popup_style_label = QLabel("窗口样式:")
        theme_layout.addRow(self._popup_style_label, self._popup_style_combo)

        # 自定义主题：强调色选择器
        self._custom_accent = '#007AFF'
        self._accent_color_btn = QPushButton()
        self._accent_color_btn.setFixedSize(80, 32)
        self._accent_color_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._accent_color_btn.clicked.connect(self._pick_accent_color)
        self._accent_color_label = QLabel("强调色:")
        theme_layout.addRow(self._accent_color_label, self._accent_color_btn)

        # 自定义主题：背景色选择器
        self._custom_bg = '#2d2d2d'
        self._bg_color_btn = QPushButton()
        self._bg_color_btn.setFixedSize(80, 32)
        self._bg_color_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._bg_color_btn.clicked.connect(self._pick_bg_color)
        self._bg_color_label = QLabel("背景色:")
        theme_layout.addRow(self._bg_color_label, self._bg_color_btn)

        # 根据当前选择控制颜色选择器可见性
        self._popup_style_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        self._update_custom_color_visibility()

        scroll_layout.addWidget(self._theme_group)

        # 字体设置组
        self._font_group = QGroupBox("字体设置")
        font_layout = QFormLayout(self._font_group)
        font_layout.setSpacing(10)
        font_layout.setContentsMargins(12, 20, 12, 12)
        font_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._font_size_spin = StyledSpinBox()
        self._font_size_spin.setRange(10, 24)
        self._font_size_spin.setValue(14)
        self._font_size_spin.setMinimumHeight(32)
        self._font_size_spin.setSuffix(" px")
        self._font_size_label = QLabel("字体大小:")
        font_layout.addRow(self._font_size_label, self._font_size_spin)

        scroll_layout.addWidget(self._font_group)

        # 快捷键设置组
        self._hotkey_group = QGroupBox("快捷键设置")
        hotkey_layout = QFormLayout(self._hotkey_group)
        hotkey_layout.setSpacing(10)
        hotkey_layout.setContentsMargins(12, 20, 12, 12)
        hotkey_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 翻译窗口快捷键按钮
        self._hotkey_btn = QPushButton("Ctrl+O")
        self._hotkey_btn.setObjectName("hotkeyBtn")
        self._hotkey_btn.setMinimumHeight(32)
        self._hotkey_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hotkey_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._hotkey_label = QLabel("唤醒翻译窗口:")
        hotkey_layout.addRow(self._hotkey_label, self._hotkey_btn)

        # 写作快捷键按钮
        self._writing_hotkey_btn = QPushButton("Ctrl+I")
        self._writing_hotkey_btn.setObjectName("hotkeyBtn2")
        self._writing_hotkey_btn.setMinimumHeight(32)
        self._writing_hotkey_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._writing_hotkey_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._writing_hotkey_label = QLabel("划词写作:")
        hotkey_layout.addRow(self._writing_hotkey_label, self._writing_hotkey_btn)

        # 快捷键提示文字
        self._hotkey_hint_label = QLabel("点击按钮后按下新的快捷键组合")
        self._hotkey_hint_label.setProperty("class", "hint")
        self._hotkey_hint_label.setWordWrap(True)
        hotkey_layout.addRow("", self._hotkey_hint_label)

        # 存储当前快捷键值
        self._hotkey_value = "Ctrl+O"
        self._writing_hotkey_value = "Ctrl+I"

        # 监听按钮点击
        self._hotkey_btn.clicked.connect(lambda: self._start_hotkey_capture("translator"))
        self._writing_hotkey_btn.clicked.connect(lambda: self._start_hotkey_capture("writing"))

        scroll_layout.addWidget(self._hotkey_group)

        # 写作设置组
        self._writing_group = QGroupBox("写作设置")
        writing_layout = QVBoxLayout(self._writing_group)
        writing_layout.setSpacing(8)
        writing_layout.setContentsMargins(12, 20, 12, 12)

        self._keep_original_check = QCheckBox("保留原文")
        self._keep_original_check.toggled.connect(self._on_checkbox_toggled)
        writing_layout.addWidget(self._keep_original_check)

        # 添加说明文字
        self._writing_hint_label = QLabel("勾选后，写作时会在原文下方另起一行插入翻译结果")
        self._writing_hint_label.setProperty("class", "checkbox-hint")
        self._writing_hint_label.setWordWrap(True)
        writing_layout.addWidget(self._writing_hint_label)

        # 换行快捷键选择
        newline_layout = QHBoxLayout()
        newline_layout.setContentsMargins(28, 0, 0, 0)
        self._newline_hotkey_label = QLabel("换行快捷键:")
        self._newline_hotkey_combo = QComboBox()
        self._newline_hotkey_combo.addItems(["enter", "shift+enter", "ctrl+enter"])
        self._newline_hotkey_combo.setMinimumHeight(32)
        newline_layout.addWidget(self._newline_hotkey_label)
        newline_layout.addWidget(self._newline_hotkey_combo)
        newline_layout.addStretch()
        writing_layout.addLayout(newline_layout)

        # 动画输入勾选
        self._animation_check = QCheckBox("动画输入（逐字输入效果）")
        self._animation_check.toggled.connect(self._on_checkbox_toggled)
        writing_layout.addWidget(self._animation_check)

        scroll_layout.addWidget(self._writing_group)

        # 润色设置组
        self._polishing_group = QGroupBox("润色设置")
        polishing_layout = QVBoxLayout(self._polishing_group)
        polishing_layout.setSpacing(8)
        polishing_layout.setContentsMargins(12, 20, 12, 12)

        self._polishing_show_diff_check = QCheckBox("显示润色差异")
        self._polishing_show_diff_check.toggled.connect(self._on_checkbox_toggled)
        polishing_layout.addWidget(self._polishing_show_diff_check)

        # 添加说明文字
        self._polishing_show_diff_hint_label = QLabel("勾选后，润色结果将使用删除线标记被删除的文字，使用粗体标记新增或修改的文字")
        self._polishing_show_diff_hint_label.setProperty("class", "checkbox-hint")
        self._polishing_show_diff_hint_label.setWordWrap(True)
        polishing_layout.addWidget(self._polishing_show_diff_hint_label)

        scroll_layout.addWidget(self._polishing_group)

        # 翻译窗口设置组
        self._translator_window_group = QGroupBox("翻译窗口设置")
        translator_window_layout = QVBoxLayout(self._translator_window_group)
        translator_window_layout.setSpacing(8)
        translator_window_layout.setContentsMargins(12, 20, 12, 12)

        self._fixed_height_check = QCheckBox("固定窗口高度")
        self._fixed_height_check.toggled.connect(self._on_checkbox_toggled)
        translator_window_layout.addWidget(self._fixed_height_check)

        # 添加说明文字
        self._fixed_height_hint_label = QLabel("勾选后，原文框固定180px，译文框固定360px，不随内容自动调整")
        self._fixed_height_hint_label.setProperty("class", "checkbox-hint")
        self._fixed_height_hint_label.setWordWrap(True)
        translator_window_layout.addWidget(self._fixed_height_hint_label)

        # 记忆窗口大小勾选框
        self._remember_size_check = QCheckBox("固定窗口大小（上一次调整的大小）")
        self._remember_size_check.toggled.connect(self._on_checkbox_toggled)
        translator_window_layout.addWidget(self._remember_size_check)

        # 添加说明文字
        self._remember_size_hint_label = QLabel("勾选后，翻译窗口会记住用户最后一次手动调整的大小，下次唤醒时恢复")
        self._remember_size_hint_label.setProperty("class", "checkbox-hint")
        self._remember_size_hint_label.setWordWrap(True)
        translator_window_layout.addWidget(self._remember_size_hint_label)

        # 记忆窗口位置勾选框
        self._remember_position_check = QCheckBox("记忆窗口位置")
        self._remember_position_check.toggled.connect(self._on_checkbox_toggled)
        translator_window_layout.addWidget(self._remember_position_check)

        # 添加说明文字
        self._remember_position_hint_label = QLabel("勾选后，翻译窗口会记住上次关闭时的位置。程序重启后位置重置")
        self._remember_position_hint_label.setProperty("class", "checkbox-hint")
        self._remember_position_hint_label.setWordWrap(True)
        translator_window_layout.addWidget(self._remember_position_hint_label)

        # 始终置顶勾选框
        self._always_on_top_check = QCheckBox("始终置顶")
        self._always_on_top_check.toggled.connect(self._on_checkbox_toggled)
        translator_window_layout.addWidget(self._always_on_top_check)

        # 添加说明文字
        self._always_on_top_hint_label = QLabel("勾选后，翻译窗口始终显示在所有窗口最上层。不勾选时，窗口可被其他窗口覆盖，通过快捷键、双击托盘图标或点击任务栏图标可重新唤醒")
        self._always_on_top_hint_label.setProperty("class", "checkbox-hint")
        self._always_on_top_hint_label.setWordWrap(True)
        translator_window_layout.addWidget(self._always_on_top_hint_label)

        scroll_layout.addWidget(self._translator_window_group)

        # 系统设置组
        self._sys_group = QGroupBox("系统设置")
        sys_layout = QVBoxLayout(self._sys_group)
        sys_layout.setSpacing(8)
        sys_layout.setContentsMargins(12, 20, 12, 12)

        self._auto_start_check = QCheckBox("开机自动启动")
        self._auto_start_check.toggled.connect(self._on_checkbox_toggled)
        sys_layout.addWidget(self._auto_start_check)

        scroll_layout.addWidget(self._sys_group)

        self._scroll_area.setWidget(self._scroll_content)
        content_layout.addWidget(self._scroll_area, 1)

        # 底部按钮栏
        self._btn_bar = QFrame()
        self._btn_bar.setObjectName("btnBar")
        btn_layout = QHBoxLayout(self._btn_bar)
        btn_layout.setContentsMargins(0, 8, 0, 0)
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.setFixedHeight(32)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("保存")
        self._save_btn.setObjectName("saveBtn")
        self._save_btn.setFixedHeight(32)
        self._save_btn.clicked.connect(self._save_settings)
        btn_layout.addWidget(self._save_btn)

        content_layout.addWidget(self._btn_bar)

    def _create_uncheck_icon(self) -> QIcon:
        """创建未勾选图标（圆角方框，顶部留1px微调对齐）"""
        pixmap = QPixmap(16, 17)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 顶部偏移1px，让勾选框与文字垂直居中对齐
        painter.setBrush(QColor(self._theme['input_bg']))
        painter.setPen(QPen(QColor(self._theme['scrollbar_handle']), 1.2))
        painter.drawRoundedRect(1, 2, 14, 14, 4, 4)

        painter.end()

        return QIcon(pixmap)


    def _create_check_icon(self) -> QIcon:
        """创建勾选图标（圆角填充 + 小对勾，顶部留1px微调对齐）"""
        pixmap = QPixmap(16, 17)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 顶部偏移1px，让勾选框与文字垂直居中对齐
        painter.setBrush(QColor(self._theme['accent_color']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(1, 2, 14, 14, 4, 4)

        # 绘制白色小对勾 ✓
        painter.setPen(QPen(QColor(255, 255, 255), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(4, 9, 6, 12)   # 短竖
        painter.drawLine(6, 12, 12, 6)  # 长斜

        painter.end()

        return QIcon(pixmap)

    def _apply_theme(self):
        """应用主题样式 - 使用单一合并样式表，避免逐控件 setStyleSheet 的性能开销"""
        t = self._theme

        # 构建合并样式表，一次性应用到 contentFrame 及其所有子控件
        consolidated_style = f"""
            /* 内容容器 */
            QFrame#contentFrame {{
                background-color: {t['bg_color']};
                border-radius: 8px;
                border: 1px solid {t['border_color']};
            }}

            /* 标题栏 */
            QFrame#titleBar {{
                background-color: transparent;
                border-bottom: 1px solid {t['border_color']};
            }}
            QFrame#titleBar:hover {{
                background-color: {t['border_color']};
            }}

            /* 标题文字 */
            QLabel#titleLabel {{
                color: {t['text_muted']};
                font-size: 12px;
            }}

            /* 关闭按钮 */
            QPushButton#closeBtn {{
                background-color: transparent;
                color: {t['text_muted']};
                border: none;
                border-radius: 11px;
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 1px;
            }}
            QPushButton#closeBtn:hover {{
                background-color: {t['close_hover']};
                color: #ffffff;
            }}

            /* 滚动区域 */
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}

            /* 滚动条 */
            {get_scrollbar_style(t)}

            /* 滚动内容容器 */
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}

            /* 分组框 */
            QGroupBox {{
                color: {t['group_title']};
                font-size: 14px;
                font-weight: bold;
                border: 1px solid {t['border_color']};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 8px;
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}

            /* 表单标签（默认） */
            QGroupBox QLabel {{
                color: {t['text_secondary']};
                font-size: 13px;
            }}

            /* 提示标签 */
            QLabel[class="hint"] {{
                color: {t['text_muted']};
                font-size: 11px;
            }}

            /* 勾选框下方提示标签（与勾选文字对齐） */
            QLabel[class="checkbox-hint"] {{
                color: {t['text_muted']};
                font-size: 11px;
                margin-left: 26px;
            }}

            /* 输入框 */
            QLineEdit {{
                background-color: {t['input_bg']};
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                padding: 6px 10px;
                color: {t['text_primary']};
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {t['input_focus']};
            }}

            /* 下拉框 */
            QComboBox {{
                background-color: {t['input_bg']};
                color: {t['text_primary']};
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QComboBox:hover {{
                border-color: {t['accent_color']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {t['bg_color']};
                color: {t['text_primary']};
                selection-background-color: {t['accent_color']};
                selection-color: #ffffff;
                border: 1px solid {t['border_color']};
                border-radius: 6px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                border: none;
                padding: 2px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {t['button_hover']};
                color: {t['text_primary']};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {t['accent_color']};
                color: #ffffff;
            }}

            /* 数字输入框 */
            QSpinBox {{
                background-color: {t['input_bg']};
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                padding: 4px 8px;
                padding-right: 26px;
                color: {t['text_primary']};
                font-size: 13px;
            }}
            QSpinBox:focus {{
                border-color: {t['accent_color']};
            }}
            QSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: right top;
                width: 18px;
                border: none;
                border-top-right-radius: 5px;
                border-left: 1px solid {t['input_border']};
                background-color: transparent;
            }}
            QSpinBox::up-button:hover {{
                background-color: {t['button_hover']};
            }}
            QSpinBox::up-button:pressed {{
                background-color: {t['accent_color']};
            }}
            QSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: right bottom;
                width: 18px;
                border: none;
                border-bottom-right-radius: 5px;
                border-left: 1px solid {t['input_border']};
                background-color: transparent;
            }}
            QSpinBox::down-button:hover {{
                background-color: {t['button_hover']};
            }}
            QSpinBox::down-button:pressed {{
                background-color: {t['accent_color']};
            }}

            /* 快捷键按钮 */
            QPushButton#hotkeyBtn, QPushButton#hotkeyBtn2 {{
                background-color: {t['input_bg']};
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                padding: 4px 12px;
                color: {t['text_primary']};
                font-size: 13px;
                text-align: left;
            }}
            QPushButton#hotkeyBtn:hover, QPushButton#hotkeyBtn2:hover {{
                border-color: {t['accent_color']};
            }}
            QPushButton#hotkeyBtn:focus, QPushButton#hotkeyBtn2:focus {{
                border-color: {t['accent_color']};
                background-color: {t['accent_color']};
                color: #ffffff;
            }}

            /* 复选框 */
            QCheckBox {{
                color: {t['text_primary']};
                font-size: 13px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 0px;
                height: 0px;
                margin: 0px;
                padding: 0px;
                border: none;
            }}

            /* 底部按钮栏 */
            QFrame#btnBar {{
                background-color: transparent;
                border: none;
            }}

            /* 取消按钮 */
            QPushButton#cancelBtn {{
                background-color: {t['button_bg']};
                color: {t['text_primary']};
                border: none;
                border-radius: 6px;
                padding: 0 20px;
                font-size: 13px;
            }}
            QPushButton#cancelBtn:hover {{
                background-color: {t['button_hover']};
            }}

            /* 保存按钮 */
            QPushButton#saveBtn {{
                background-color: {t['accent_color']};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton#saveBtn:hover {{
                background-color: {t['accent_hover']};
            }}
        """

        # 一次性应用合并样式表
        self._content_frame.setStyleSheet(consolidated_style)

        # 动态样式：颜色选择器按钮（背景色随用户选择变化，需单独设置）
        self._update_color_btn_style(self._accent_color_btn, self._custom_accent)
        self._update_color_btn_style(self._bg_color_btn, self._custom_bg)

        # SpinBox 自定义箭头颜色
        self._font_size_spin.set_arrow_color(t['text_secondary'])
        self._browser_delay_spin.set_arrow_color(t['text_secondary'])

        # 缓存复选框图标并应用
        self._cached_check_icon = self._create_check_icon()
        self._cached_uncheck_icon = self._create_uncheck_icon()
        for cb in (self._auto_start_check, self._keep_original_check,
                   self._fixed_height_check, self._remember_size_check,
                   self._remember_position_check, self._always_on_top_check,
                   self._polishing_show_diff_check, self._animation_check):
            cb.setIcon(self._cached_check_icon if cb.isChecked() else self._cached_uncheck_icon)

    def _start_hotkey_capture(self, target: str):
        """开始捕获快捷键"""
        if target == "translator":
            self._hotkey_btn.setText("请按下快捷键...")
            self._hotkey_btn.setFocus()
            self._capturing_hotkey_target = "translator"
        else:
            self._writing_hotkey_btn.setText("请按下快捷键...")
            self._writing_hotkey_btn.setFocus()
            self._capturing_hotkey_target = "writing"

    def keyPressEvent(self, event):
        """键盘事件处理 - 用于捕获快捷键"""
        if hasattr(self, '_capturing_hotkey_target') and self._capturing_hotkey_target:
            key = event.key()
            modifiers = event.modifiers()

            # 忽略单独的功能键
            if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
                return

            # 构建快捷键字符串
            key_sequence_parts = []
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                key_sequence_parts.append("Ctrl")
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                key_sequence_parts.append("Shift")
            if modifiers & Qt.KeyboardModifier.AltModifier:
                key_sequence_parts.append("Alt")
            if modifiers & Qt.KeyboardModifier.MetaModifier:
                key_sequence_parts.append("Meta")

            # 获取按键名称
            key_name = QKeySequence(key).toString()
            key_sequence_parts.append(key_name)

            hotkey = "+".join(key_sequence_parts)

            # 更新对应的快捷键
            if self._capturing_hotkey_target == "translator":
                self._hotkey_value = hotkey
                self._hotkey_btn.setText(hotkey)
            else:
                self._writing_hotkey_value = hotkey
                self._writing_hotkey_btn.setText(hotkey)

            self._capturing_hotkey_target = None
            return

        super().keyPressEvent(event)

    def _on_checkbox_toggled(self, checked: bool):
        """复选框状态改变时更新图标（使用缓存图标）并处理互斥逻辑"""
        sender = self.sender()
        if sender and hasattr(self, '_cached_check_icon'):
            sender.setIcon(self._cached_check_icon if checked else self._cached_uncheck_icon)
        
        # 处理固定窗口高度和固定窗口大小的互斥逻辑
        if sender == self._fixed_height_check and checked:
            # 如果勾选了固定窗口高度，取消固定窗口大小
            self._remember_size_check.setChecked(False)
        elif sender == self._remember_size_check and checked:
            # 如果勾选了固定窗口大小，取消固定窗口高度
            self._fixed_height_check.setChecked(False)

    def update_theme(self):
        """更新主题"""
        self._theme = get_theme()
        self._apply_theme()
        # 更新眼睛按钮图标
        if hasattr(self, '_api_key_toggle_action'):
            current_mode = self._api_key_edit.echoMode()
            self._api_key_toggle_action.setIcon(self._get_eye_icon(current_mode == QLineEdit.EchoMode.Normal))

    def _is_over_title_bar_button(self, pos: QPoint) -> bool:
        """判断鼠标是否在标题栏按钮区域内"""
        title_bar_height = 28
        # 首先检查是否在标题栏区域
        if pos.y() > title_bar_height:
            return False

        # 关闭按钮在标题栏右侧，按钮大小 20x20
        button_width = 20
        right_margin = 8

        # 按钮区域的左边界
        window_width = self.width()
        button_left = window_width - right_margin - button_width - 4  # 额外4px余量

        # 检查鼠标是否在按钮区域内
        return pos.x() >= button_left

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            title_bar_height = 28
            # 只有在标题栏的非按钮区域才开始拖动
            if pos.y() <= title_bar_height and not self._is_over_title_bar_button(pos):
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
        else:
            # 智能光标控制
            title_bar_height = 28
            # 检查是否在标题栏非按钮区域（显示拖动光标）
            if pos.y() <= title_bar_height and not self._is_over_title_bar_button(pos):
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            # 其他区域显示默认箭头光标
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_start_pos = None

        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        # 鼠标离开窗口时恢复默认光标
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)

    def _load_settings(self):
        """加载设置"""
        # API 配置
        self._api_url_edit.setText(self._config.get('translator.base_url', ''))
        self._api_key_edit.setText(self._config.get('translator.api_key', ''))
        self._model_edit.setText(self._config.get('translator.model', ''))
        self._no_proxy_edit.setText(self._config.get('translator.no_proxy', '109.105.120.122'))

        # 浏览器划词延迟
        browser_delay = self._config.get('selection.browser_delay_ms', 450)
        self._browser_delay_spin.setValue(browser_delay)

        popup_style = self._config.get('theme.popup_style', 'dark')
        if popup_style in self._theme_keys:
            self._popup_style_combo.setCurrentIndex(self._theme_keys.index(popup_style))
        else:
            self._popup_style_combo.setCurrentIndex(0)

        # 加载自定义颜色
        self._custom_accent = self._config.get('theme.custom_accent', '#007AFF')
        self._custom_bg = self._config.get('theme.custom_bg', '#2d2d2d')
        self._update_color_btn_style(self._accent_color_btn, self._custom_accent)
        self._update_color_btn_style(self._bg_color_btn, self._custom_bg)
        self._update_custom_color_visibility()

        # 字体大小
        font_size = self._config.get('font.size', 14)
        self._font_size_spin.setValue(font_size)

        # 快捷键
        hotkey = self._config.get('hotkey.translator_window', 'Ctrl+O')
        self._hotkey_value = hotkey
        self._hotkey_btn.setText(hotkey)

        # 写作快捷键
        writing_hotkey = self._config.get('hotkey.writing', 'Ctrl+I')
        self._writing_hotkey_value = writing_hotkey
        self._writing_hotkey_btn.setText(writing_hotkey)

        # 保留原文选项
        keep_original = self._config.get('writing.keep_original', False)
        self._keep_original_check.setChecked(keep_original)

        # 换行快捷键选项
        newline_hotkey = self._config.get('writing.newline_hotkey', 'enter')
        index = self._newline_hotkey_combo.findText(newline_hotkey)
        if index >= 0:
            self._newline_hotkey_combo.setCurrentIndex(index)

        # 动画输入选项
        animation = self._config.get('writing.animation', True)
        self._animation_check.setChecked(animation)

        # 显示润色差异选项
        polishing_show_diff = self._config.get('polishing.show_diff', False)
        self._polishing_show_diff_check.setChecked(polishing_show_diff)

        # 固定高度模式选项
        fixed_height_mode = self._config.get('translator_window.fixed_height_mode', False)
        self._fixed_height_check.setChecked(fixed_height_mode)

        # 记忆窗口位置选项
        remember_position = self._config.get('translator_window.remember_window_position', False)
        self._remember_position_check.setChecked(remember_position)
        
        # 记忆窗口大小选项
        remember_size = self._config.get('translator_window.remember_window_size', False)
        self._remember_size_check.setChecked(remember_size)

        # 始终置顶选项
        always_on_top = self._config.get('translator_window.always_on_top', False)
        self._always_on_top_check.setChecked(always_on_top)

        self._auto_start_check.setChecked(self._config.get('startup.auto_start', False))

        # 禁用滚轮事件，避免误触
        self._disable_wheel_event(self._popup_style_combo)
        self._disable_wheel_event(self._font_size_spin)
        self._disable_wheel_event(self._browser_delay_spin)
        self._disable_wheel_event(self._newline_hotkey_combo)

        # 预初始化 ComboBox 下拉视图，避免首次点击卡顿
        self._popup_style_combo.view()
        self._newline_hotkey_combo.view()

    def _disable_wheel_event(self, widget):
        """禁用控件的鼠标滚轮事件，防止误触"""
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        """事件过滤器，用于禁用控件的滚轮事件并转发给滚动区域"""
        if event.type() == event.Type.Wheel:
            # 将滚轮事件转发给滚动区域，而不是直接吞掉
            if hasattr(self, '_scroll_area') and self._scroll_area:
                QApplication.sendEvent(self._scroll_area.verticalScrollBar(), event)
            return True
        return super().eventFilter(obj, event)

    def _on_theme_combo_changed(self, index):
        """主题下拉框选项变更时，控制自定义颜色选择器的可见性"""
        self._update_custom_color_visibility()

    def _update_custom_color_visibility(self):
        """根据当前主题选择更新颜色选择器的可见性"""
        is_custom = self._theme_keys[self._popup_style_combo.currentIndex()] == 'custom'
        self._accent_color_label.setVisible(is_custom)
        self._accent_color_btn.setVisible(is_custom)
        self._bg_color_label.setVisible(is_custom)
        self._bg_color_btn.setVisible(is_custom)

    def _update_color_btn_style(self, btn, hex_color):
        """更新颜色按钮的背景色显示"""
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {hex_color};
                border: 1px solid {self._theme.get('border_color', '#3d3d3d')};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                border-color: {self._theme.get('accent_color', '#007AFF')};
                border-width: 2px;
            }}
        """)

    def _toggle_api_key_visibility(self):
        """切换 API Key 显示/隐藏"""
        current_mode = self._api_key_edit.echoMode()
        if current_mode == QLineEdit.EchoMode.Password:
            # 显示密码
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._api_key_toggle_action.setIcon(self._get_eye_icon(True))
        else:
            # 隐藏密码
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._api_key_toggle_action.setIcon(self._get_eye_icon(False))

    def _get_eye_icon(self, visible: bool) -> QIcon:
        """获取眼睛图标
        
        Args:
            visible: True 表示显示睁眼图标，False 表示显示闭眼图标
        """
        if visible:
            # 睁眼图标
            svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                <path fill="''' + self._theme['text_secondary'] + '''" d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/>
            </svg>'''
        else:
            # 闭眼图标（带斜线）
            svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                <path fill="''' + self._theme['text_secondary'] + '''" d="M12 7c2.76 0 5 2.24 5 5 0 .65-.13 1.26-.36 1.83l2.92 2.92c1.51-1.26 2.7-2.89 3.43-4.75-1.73-4.39-6-7.5-11-7.5-1.4 0-2.74.25-3.98.7l2.16 2.16C10.74 7.13 11.35 7 12 7zM2 4.27l2.28 2.28.46.46C3.08 8.3 1.78 10.02 1 12c1.73 4.39 6 7.5 11 7.5 1.55 0 3.03-.3 4.38-.84l.42.42L19.73 22 21 20.73 3.27 3 2 4.27zM7.53 9.8l1.55 1.55c-.05.21-.08.43-.08.65 0 1.66 1.34 3 3 3 .22 0 .44-.03.65-.08l1.55 1.55c-.67.33-1.41.53-2.2.53-2.76 0-5-2.24-5-5 0-.79.2-1.53.53-2.2zm4.31-.78l3.15 3.15.02-.16c0-1.66-1.34-3-3-3l-.17.01z"/>
            </svg>'''
        
        # 使用 QSvgRenderer 渲染高清图标
        renderer = QSvgRenderer(svg.encode('utf-8'))
        pixmap = QPixmap(24, 24)  # 使用更大的尺寸确保清晰度
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        
        return QIcon(pixmap)

    def _pick_accent_color(self):
        """弹出颜色对话框选择强调色"""
        color = QColorDialog.getColor(QColor(self._custom_accent), self, "选择强调色")
        if color.isValid():
            self._custom_accent = color.name()
            self._update_color_btn_style(self._accent_color_btn, self._custom_accent)

    def _pick_bg_color(self):
        """弹出颜色对话框选择背景色"""
        color = QColorDialog.getColor(QColor(self._custom_bg), self, "选择背景色")
        if color.isValid():
            self._custom_bg = color.name()
            self._update_color_btn_style(self._bg_color_btn, self._custom_bg)

    def _save_settings(self):
        """保存设置"""
        try:
            selection_detector = get_selection_detector()
            selection_detector.pause()
        except Exception:
            pass

        try:
            # 快捷键 - 先获取旧的热键，用于判断是否需要重新注册
            old_hotkey = self._config.get('hotkey.translator_window', 'Ctrl+O')
            new_hotkey = self._hotkey_value

            # 写作快捷键
            old_writing_hotkey = self._config.get('hotkey.writing', 'Ctrl+I')
            new_writing_hotkey = self._writing_hotkey_value

            # API 配置
            self._config.set('translator.base_url', self._api_url_edit.text().strip())
            self._config.set('translator.api_key', self._api_key_edit.text().strip())
            self._config.set('translator.model', self._model_edit.text().strip())
            self._config.set('translator.no_proxy', self._no_proxy_edit.text().strip())

            # 浏览器划词延迟
            self._config.set('selection.browser_delay_ms', self._browser_delay_spin.value())

            selected_key = self._theme_keys[self._popup_style_combo.currentIndex()]
            self._config.set('theme.popup_style', selected_key)
            if selected_key == 'custom':
                self._config.set('theme.custom_accent', self._custom_accent)
                self._config.set('theme.custom_bg', self._custom_bg)

            # 字体大小
            self._config.set('font.size', self._font_size_spin.value())

            # 快捷键
            self._config.set('hotkey.translator_window', new_hotkey)
            self._config.set('hotkey.writing', new_writing_hotkey)

            # 写作设置
            keep_original = self._keep_original_check.isChecked()
            self._config.set('writing.keep_original', keep_original)
            self._config.set('writing.newline_hotkey', self._newline_hotkey_combo.currentText())
            self._config.set('writing.animation', self._animation_check.isChecked())

            # 润色设置
            polishing_show_diff = self._polishing_show_diff_check.isChecked()
            self._config.set('polishing.show_diff', polishing_show_diff)

            # 翻译窗口固定高度模式
            fixed_height_mode = self._fixed_height_check.isChecked()
            self._config.set('translator_window.fixed_height_mode', fixed_height_mode)

            # 翻译窗口记忆位置
            remember_position = self._remember_position_check.isChecked()
            self._config.set('translator_window.remember_window_position', remember_position)
            
            # 翻译窗口记忆大小
            remember_size = self._remember_size_check.isChecked()
            self._config.set('translator_window.remember_window_size', remember_size)

            # 翻译窗口始终置顶
            always_on_top = self._always_on_top_check.isChecked()
            self._config.set('translator_window.always_on_top', always_on_top)

            auto_start = self._auto_start_check.isChecked()
            self._config.set('startup.auto_start', auto_start)
            setup_auto_start(auto_start)

            self._config.save()

            # 重新初始化翻译器和写作服务（API 配置可能已变更）
            try:
                reinitialize_translator()
            except Exception:
                pass
            try:
                writing_service = get_writing_service()
                writing_service.reinitialize()
            except Exception:
                pass

            # 如果热键改变了，重新注册热键
            hotkey_manager = get_hotkey_manager()
            if old_hotkey != new_hotkey:
                try:
                    hotkey_manager.update_hotkey(new_hotkey, "translator_window")
                    log_info(f"翻译窗口热键已更新: {old_hotkey} -> {new_hotkey}")
                except Exception as e:
                    log_error(f"更新翻译窗口热键失败: {e}")

            if old_writing_hotkey != new_writing_hotkey:
                try:
                    hotkey_manager.update_hotkey(new_writing_hotkey, "writing")
                    log_info(f"写作热键已更新: {old_writing_hotkey} -> {new_writing_hotkey}")
                except Exception as e:
                    log_error(f"更新写作热键失败: {e}")

            # 更新所有窗口主题
            self._update_all_themes()

            # 使用简洁的保存成功提示
            self._show_save_success_toast()
        finally:
            try:
                selection_detector = get_selection_detector()
                selection_detector.resume()
            except Exception:
                pass

    def _update_all_themes(self):
        """通过信号广播通知所有窗口更新主题"""
        try:
            from .utils.theme import get_theme_manager
        except ImportError:
            from src.utils.theme import get_theme_manager
        get_theme_manager().notify_theme_changed()

    def _show_message_dialog(self, title: str, message: str, msg_type: str = "info"):
        """显示 toast 消息提示"""
        # 先关闭设置对话框
        self.accept()
        # 延迟显示 Toast（确保对话框已完全关闭）
        QTimer.singleShot(100, lambda: ToastWidget.show_message(title, message, msg_type))

    def _show_save_success_toast(self):
        """显示保存成功提示（简洁版：只显示绿色\"保存成功\"）"""
        # 先关闭设置对话框
        self.accept()
        # 延迟显示简洁 Toast
        QTimer.singleShot(100, lambda: SimpleToastWidget.show_message("保存成功"))

    def closeEvent(self, event):
        """隐藏而非销毁，保持单例可用"""
        event.ignore()
        self.hide()


_settings_dialog_instance: Optional[SettingsDialog] = None


def get_settings_dialog() -> SettingsDialog:
    """获取设置对话框单例"""
    global _settings_dialog_instance
    if _settings_dialog_instance is None:
        _settings_dialog_instance = SettingsDialog()
    return _settings_dialog_instance


class FadeableToastBase(QWidget):
    """Toast 淡出动画基类"""

    # 子类需覆盖此列表
    _active_toasts = []

    def __init__(self, auto_close_ms: int = 2000):
        super().__init__(None)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # 自动关闭定时器
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self._fade_out)

        # 淡出动画
        self._opacity = 1.0
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._do_fade)

        self._auto_close_ms = auto_close_ms

    def _start_auto_close(self):
        """启动自动关闭计时器（子类在 UI 初始化完成后调用）"""
        self._close_timer.start(self._auto_close_ms)

    def _position_at_bottom_center(self, margin_bottom: int = 60):
        """定位窗口到屏幕底部中央"""
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2
            y = screen_geo.height() - self.height() - margin_bottom
            self.move(x, y)

    def _fade_out(self):
        """开始淡出"""
        self._fade_timer.start(30)

    def _do_fade(self):
        """执行淡出动画"""
        self._opacity -= 0.05
        if self._opacity <= 0:
            self._fade_timer.stop()
            self.close()
            toast_list = type(self)._active_toasts
            if self in toast_list:
                toast_list.remove(self)
            self.deleteLater()
        else:
            self.setWindowOpacity(self._opacity)


class SimpleToastWidget(FadeableToastBase):
    """简洁 Toast 消息提示组件（单行文字，宽度自适应）"""

    _active_toasts = []

    def __init__(self, message: str):
        super().__init__(auto_close_ms=2000)

        self._setup_ui(message)
        self._position_at_bottom_center(margin_bottom=60)
        self._start_auto_close()

    def _setup_ui(self, message: str):
        """设置UI - 单行文字，宽度自适应"""
        # 使用 QFrame 作为容器，避免样式影响子控件
        self._container = QFrame(self)
        self._container.setObjectName("toastContainer")

        # 主布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self._container)

        # 内容布局
        layout = QHBoxLayout(self._container)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(6)

        # 绿色背景 - 只应用到容器
        bg_color = "#1a7f37"

        self._container.setStyleSheet(f"""
            QFrame#toastContainer {{
                background-color: {bg_color};
                border-radius: 6px;
            }}
        """)

        # 勾选图标
        icon_label = QLabel("✓")
        icon_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                background-color: transparent;
            }
        """)
        layout.addWidget(icon_label)

        # 文字
        msg_label = QLabel(message)
        msg_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 13px;
                background-color: transparent;
            }
        """)
        layout.addWidget(msg_label)

        # 宽度自适应文字长度
        self.adjustSize()

        # 添加阴影
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

    @staticmethod
    def show_message(message: str):
        """静态方法：显示简洁Toast消息"""
        toast = SimpleToastWidget(message)
        SimpleToastWidget._active_toasts.append(toast)
        toast.show()


class ToastWidget(FadeableToastBase):
    """Toast 消息提示组件"""

    _active_toasts = []

    def __init__(self, title: str, message: str, msg_type: str = "info"):
        super().__init__(auto_close_ms=2500)

        self._setup_ui(title, message, msg_type)
        self._position_at_bottom_center(margin_bottom=80)
        self._start_auto_close()

    def _setup_ui(self, title: str, message: str, msg_type: str):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        # 根据类型设置颜色
        if msg_type == "success" or msg_type == "info":
            bg_color = "#1a7f37"
            icon = "✓"
        elif msg_type == "warning":
            bg_color = "#d29922"
            icon = "⚠"
        elif msg_type == "error":
            bg_color = "#cf222e"
            icon = "✕"
        else:
            bg_color = "#007AFF"  # macOS 风格现代蓝
            icon = "✓"

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border-radius: 8px;
            }}
        """)

        # 标题
        title_label = QLabel(f"{icon} {title}")
        title_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        layout.addWidget(title_label)

        # 消息
        msg_label = QLabel(message)
        msg_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 12px;
            }
        """)
        layout.addWidget(msg_label)

        # 设置固定宽度
        self.setFixedWidth(280)
        self.adjustSize()

        # 添加阴影
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

    @staticmethod
    def show_message(title: str, message: str, msg_type: str = "info"):
        """静态方法：显示Toast消息"""
        toast = ToastWidget(title, message, msg_type)
        ToastWidget._active_toasts.append(toast)
        toast.show()


class MainController(QObject):
    """主控制器"""

    def __init__(self):
        super().__init__()

        self._config = get_config()
        self._selection_detector = get_selection_detector()
        self._translate_button = get_translate_button()
        self._tray_icon = get_tray_icon()
        self._translator = get_translator()
        self._text_capture = get_text_capture()
        self._hotkey_manager = get_hotkey_manager()
        self._writing_service = get_writing_service()

        # 翻译窗口实例
        self._translator_window = get_translator_window()
        self._current_worker = None
        self._last_text: str = ""

        # 系统恢复检测 - 用于在休眠/锁屏恢复后重新注册热键
        self._last_health_check_time = time.time()
        self._session_was_locked = False  # Windows 锁屏状态跟踪
        self._system_health_timer = QTimer()
        self._system_health_timer.timeout.connect(self._on_system_health_check)
        self._system_health_timer.start(10000)  # 每 10 秒检查一次（需要快速检测解锁）

        self._connect_signals()
        self._check_config()
        self._setup_hotkey()

    def _connect_signals(self):
        self._selection_detector.selection_finished.connect(self._on_selection_finished)
        self._translate_button.clicked.connect(self._on_translate_button_clicked)
        self._tray_icon.enabled_changed.connect(self._on_enabled_changed)
        self._tray_icon.settings_requested.connect(self._on_settings_requested)
        self._tray_icon.exit_requested.connect(self._on_exit_requested)
        self._tray_icon.translator_window_requested.connect(self._on_translator_window_requested)
        self._tray_icon.history_requested.connect(self._on_history_requested)
        self._tray_icon.help_requested.connect(self._on_help_requested)
        # 翻译窗口关闭信号
        self._translator_window.closed.connect(self._on_translator_window_closed)
        self._hotkey_manager.hotkey_triggered.connect(self._on_hotkey_triggered)
        self._hotkey_manager.writing_hotkey_triggered.connect(self._on_writing_hotkey_triggered)

    def _check_config(self):
        """检查配置（API 配置已硬编码，无需检查）"""
        pass

    def _setup_hotkey(self):
        """设置全局热键"""
        is_auto_start = self._config.get('startup.auto_start', False)
        self._hotkey_retry_count = 0

        if is_auto_start:
            # 开机自启时延迟注册热键，等待 Windows 桌面环境完全就绪
            log_info("开机自启模式，延迟 5 秒注册热键")
            QTimer.singleShot(5000, self._register_all_hotkeys)
        else:
            self._register_all_hotkeys()

    def _register_all_hotkeys(self):
        """注册所有热键（支持重试）"""
        hotkey = self._config.get('hotkey.translator_window', 'Ctrl+O')
        success1 = self._hotkey_manager.register_hotkey(hotkey, name="translator_window")
        log_debug(f"注册翻译窗口热键: {hotkey}, 结果: {success1}")

        writing_hotkey = self._config.get('hotkey.writing', 'Ctrl+I')
        success2 = self._hotkey_manager.register_hotkey(writing_hotkey, name="writing")
        log_debug(f"注册写作热键: {writing_hotkey}, 结果: {success2}")

        if not success1 or not success2:
            self._hotkey_retry_count += 1
            if self._hotkey_retry_count <= 3:
                delay = self._hotkey_retry_count * 5000  # 5s, 10s, 15s
                log_info(f"部分热键注册失败，第 {self._hotkey_retry_count} 次重试将在 {delay//1000} 秒后执行")
                QTimer.singleShot(delay, self._register_all_hotkeys)
            else:
                log_error("热键注册多次重试失败，请手动重启软件")

    def _on_system_health_check(self):
        """系统健康检查 - 检测休眠恢复和锁屏解锁

        两种场景：
        1. 系统休眠/睡眠恢复：进程被挂起，QTimer 不触发，通过定时器间隔检测
        2. 屏幕锁定/解锁：进程正常运行，QTimer 正常触发，通过 OpenInputDesktop API 检测

        两种场景下 pynput 的 WH_KEYBOARD_LL 钩子（热键）
        都可能被 Windows 系统移除，需要在恢复后重新注册。
        """
        current_time = time.time()
        gap = current_time - self._last_health_check_time
        self._last_health_check_time = current_time

        # 场景1：检测系统休眠/睡眠恢复（定时器间隔远超预期）
        if gap > 120:  # 超过 2 分钟
            log_info(f"检测到系统从休眠恢复（间隔 {gap:.0f} 秒）")
            self._session_was_locked = False
            QTimer.singleShot(2000, self._on_session_restored)
            return

        # 场景2：检测 Windows 锁屏/解锁（通过 OpenInputDesktop API）
        if sys.platform == 'win32':
            self._check_session_lock_state()

    def _check_session_lock_state(self):
        """检测 Windows 会话锁定状态变化

        使用 OpenInputDesktop API 判断当前桌面是否可访问：
        - 正常桌面：OpenInputDesktop 返回有效句柄
        - 锁屏/安全桌面：OpenInputDesktop 返回 NULL（无权访问 Winlogon 桌面）
        """
        try:
            import ctypes
            # DESKTOP_READOBJECTS = 0x0001
            hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0001)
            is_unlocked = bool(hdesk)
            if hdesk:
                ctypes.windll.user32.CloseDesktop(hdesk)

            was_locked = self._session_was_locked
            self._session_was_locked = not is_unlocked

            # 检测到从锁屏 → 解锁的状态转换
            if was_locked and is_unlocked:
                log_info("检测到屏幕解锁，重新注册热键并重启鼠标监听")
                QTimer.singleShot(2000, self._on_session_restored)
        except Exception:
            pass

    def _on_session_restored(self):
        """会话恢复后的统一处理（休眠恢复/屏幕解锁共用）"""
        # 重建 pynput 热键监听器（stop + 新建 + start）
        # Windows 锁屏/休眠会静默卸载 WH_KEYBOARD_LL 钩子
        self._hotkey_retry_count = 0
        self._hotkey_manager.reinstall_all()

    def _pre_render_windows(self):
        """预创建并预渲染所有窗口，消除首次显示延迟"""
        windows_to_prerender = []

        # 翻译窗口（已在 __init__ 创建，但未渲染）
        windows_to_prerender.append(self._translator_window)

        # 历史窗口（懒加载单例，此处触发创建）
        try:
            from .ui.history_window import get_history_window
        except ImportError:
            from src.ui.history_window import get_history_window
        try:
            windows_to_prerender.append(get_history_window())
        except Exception as e:
            log_error(f"预创建历史窗口失败: {e}")

        # 帮助窗口（懒加载单例，此处触发创建）
        try:
            from .ui.help_window import get_help_window
        except ImportError:
            from src.ui.help_window import get_help_window
        try:
            windows_to_prerender.append(get_help_window())
        except Exception as e:
            log_error(f"预创建帮助窗口失败: {e}")

        # 设置对话框（新增单例，此处触发创建）
        try:
            windows_to_prerender.append(get_settings_dialog())
        except Exception as e:
            log_error(f"预创建设置对话框失败: {e}")

        # 离屏预渲染：移至屏幕外 → show → 处理渲染事件 → hide
        offscreen_pos = QPoint(-9999, -9999)
        for widget in windows_to_prerender:
            try:
                original_pos = widget.pos()
                widget.move(offscreen_pos)
                widget.show()
                QApplication.processEvents()
                widget.hide()
                widget.move(original_pos)
            except Exception as e:
                log_error(f"预渲染窗口失败: {type(widget).__name__}: {e}")

        log_info("窗口预渲染完成")

        # 预热翻译器（后台线程，不阻塞UI）
        import threading
        def _warmup():
            try:
                # 预热语言检测模型
                from .utils.language_detector import detect_language
                detect_language("Hello")
                log_debug("语言检测预热完成")
            except Exception:
                pass
            try:
                # 预热API连接（建立DNS+TCP+SSL连接，后续翻译复用）
                if self._translator and self._translator._client:
                    self._translator._client.models.list(limit=1, timeout=5)
                    log_debug("API连接预热完成")
            except Exception:
                pass  # 预热失败不影响正常使用
        threading.Thread(target=_warmup, daemon=True).start()

    def start(self):
        self._selection_detector.start()
        self._tray_icon.show()
        log_info(f"{APP_NAME} 已启动")
        # 延迟预渲染所有窗口，消除首次打开延迟
        QTimer.singleShot(800, self._pre_render_windows)

    def stop(self):
        # 停止系统健康检查
        self._system_health_timer.stop()

        self._selection_detector.stop()
        self._selection_detector.cleanup()

        # 停止热键监听
        self._hotkey_manager.stop()

        # 停止写作服务
        if self._writing_service:
            self._writing_service.stop_writing()

        if self._current_worker:
            self._current_worker.cancel()
            self._current_worker.quit()
            self._current_worker = None

        self._translate_button.hide()
        # 隐藏翻译窗口
        self._translator_window.hide()
        self._tray_icon.hide()
        self._tray_icon.cleanup()
        self._text_capture.cleanup()

        # 确保历史记录保存到磁盘
        try:
            from .utils.history import get_history
        except ImportError:
            from src.utils.history import get_history
        try:
            get_history().flush()
        except Exception:
            pass

        log_info(f"{APP_NAME} 已停止")

    def _on_hotkey_triggered(self):
        """热键触发时显示/隐藏翻译窗口（实现切换功能）"""
        log_debug("热键触发")

        # 如果翻译窗口已经可见且未最小化
        if self._translator_window.isVisible() and not self._translator_window.is_minimized():
            # 非置顶模式下，窗口可能被其他窗口覆盖
            # 如果窗口不在前台（未激活），则唤醒到前台而非隐藏
            if not self._translator_window._always_on_top and not self._translator_window.is_foreground:
                log_debug("翻译窗口被覆盖，唤醒到前台")
                self._translator_window.bring_to_front()
                return
            log_debug("翻译窗口已可见，隐藏窗口")
            self._translator_window.hide()
            self._last_text = ""
            return

        # 先隐藏划词翻译相关窗口
        self._translate_button.hide()
        self._last_text = ""

        # 如果窗口最小化了，恢复窗口
        if self._translator_window.is_minimized():
            log_debug("翻译窗口最小化状态，恢复窗口")
            self._translator_window.restore_from_minimized()
        else:
            # 显示翻译窗口
            log_debug("显示翻译窗口")
            self._translator_window.show_window()

    def _on_writing_hotkey_triggered(self):
        """写作热键触发时执行写作功能

        获取文本的方式（优先级从高到低）：
        1. 使用 Ctrl+C + 标记检测当前是否真的有选中文本
           （比 selection-hook 更可靠，因为 selection-hook 可能返回陈旧数据）
        2. 如果没有选中，则使用 ctrl+a + ctrl+c 获取全文

        关键改进：不再优先使用 selection-hook，因为它无法区分
        "当前真的有选中"和"之前选中过但现在已经没有选中了"，
        会导致用户未选中文本时误判为有选中，从而跳过 ctrl+a。
        """
        log_debug("写作热键触发")

        # 检查是否已在写作中
        if self._writing_service.is_writing:
            log_debug("写作正在进行中，跳过")
            return

        # 检查是否启用了翻译功能
        if not self._tray_icon._is_enabled:
            log_debug("翻译功能已禁用，跳过写作")
            return

        try:
            import keyboard
            import pyperclip
            import uuid

            # 释放热键相关的按键（Ctrl/Shift 可能仍处于按下状态）
            keyboard.release('ctrl')
            keyboard.release('shift')
            time.sleep(0.05)

            # 保存当前剪贴板内容
            saved_clipboard = ""
            try:
                saved_clipboard = pyperclip.paste()
            except Exception:
                pass

            # 设置唯一标记到剪贴板，用于检测 Ctrl+C 是否成功更新剪贴板
            # 如果 Ctrl+C 后剪贴板仍为此标记，说明没有选中文本
            # （比比较 saved_clipboard 更可靠，因为选中文本可能恰好与旧剪贴板相同）
            marker = f"__QTRANSLATOR_SEL_{uuid.uuid4().hex}__"
            try:
                pyperclip.copy(marker)
            except Exception:
                pass
            time.sleep(0.03)

            # 释放修饰键确保 Ctrl+C 能正常工作
            keyboard.release('ctrl')
            keyboard.release('shift')
            time.sleep(0.05)

            # 尝试 Ctrl+C 复制当前选中内容
            keyboard.press('ctrl')
            time.sleep(0.02)
            keyboard.press('c')
            time.sleep(0.02)
            keyboard.release('c')
            time.sleep(0.02)
            keyboard.release('ctrl')
            time.sleep(0.1)

            keyboard.release('ctrl')
            keyboard.release('shift')

            # 读取剪贴板内容
            clipboard_text = ""
            try:
                clipboard_text = pyperclip.paste()
            except Exception:
                pass

            # 判断是否有选中文本：剪贴板不再是标记值，说明 Ctrl+C 成功复制了选中内容
            has_real_selection = (clipboard_text
                                  and clipboard_text.strip()
                                  and clipboard_text != marker)

            if has_real_selection:
                log_info(f"通过 Ctrl+C 检测到选中文本: '{clipboard_text[:100]}...'")
                # 恢复剪贴板
                if saved_clipboard:
                    try:
                        pyperclip.copy(saved_clipboard)
                    except Exception:
                        pass
                # 不取消选中！文本保持选中状态，交给 _prepare_for_input 处理：
                #   keep_original=True: right 键移到选区末尾 → 插入换行 → 翻译在原文下方
                #   keep_original=False: delete 键删除选中文本 → 替换为翻译
                # 如果这里按 left 取消选中，光标会移到选区开头，
                # 后续 right 只移1个字符，翻译会被插入原文中间
                self._start_writing(clipboard_text.strip(), has_selection=True)
                return

            # 没有选中内容，恢复剪贴板并获取全文
            log_info("未检测到选中文本，获取全文")
            if saved_clipboard:
                try:
                    pyperclip.copy(saved_clipboard)
                except Exception:
                    pass
            self._get_all_text_for_writing_async()

        except Exception as e:
            log_error(f"写作热键处理失败: {e}")

    def _get_all_text_for_writing_async(self):
        """异步获取全文并开始写作

        通过在 ctrl+a + ctrl+c 前设置唯一标记到剪贴板，
        操作后检测剪贴板是否被更新，避免因目标应用不支持
        ctrl+a 而误用旧剪贴板内容作为全文。
        """
        try:
            import keyboard
            import pyperclip
            import uuid

            # 保存当前剪贴板内容
            saved_clipboard = ""
            try:
                saved_clipboard = pyperclip.paste()
            except Exception:
                pass

            # 生成唯一标记，设置到剪贴板
            # 这样如果 ctrl+a + ctrl+c 失败（如目标应用不支持全选），
            # 剪贴板仍为此标记，我们可以检测到并报错
            clipboard_marker = f"__QTRANSLATOR_MARKER_{uuid.uuid4().hex}__"
            try:
                pyperclip.copy(clipboard_marker)
            except Exception:
                pass
            time.sleep(0.03)

            # 再次确保按键状态正确
            keyboard.release('ctrl')
            keyboard.release('shift')
            time.sleep(0.05)

            # 全选并复制
            keyboard.press('ctrl')
            time.sleep(0.02)
            keyboard.press('a')
            time.sleep(0.02)
            keyboard.release('a')
            time.sleep(0.02)
            keyboard.release('ctrl')
            time.sleep(0.05)

            keyboard.press('ctrl')
            time.sleep(0.02)
            keyboard.press('c')
            time.sleep(0.02)
            keyboard.release('c')
            time.sleep(0.02)
            keyboard.release('ctrl')

            # 等待剪贴板更新
            QTimer.singleShot(200, lambda: self._process_full_text_for_writing(
                saved_clipboard, clipboard_marker))

        except Exception as e:
            log_error(f"获取全文失败: {e}")

    def _process_full_text_for_writing(self, saved_clipboard: str,
                                        clipboard_marker: str = ""):
        """处理全文获取结果并开始写作

        Args:
            saved_clipboard: 操作前的剪贴板内容，用于恢复
            clipboard_marker: 操作前设置的唯一标记，用于检测 ctrl+a+ctrl+c 是否成功
        """
        try:
            import pyperclip
            import keyboard

            text = pyperclip.paste()

            # 检测 ctrl+a + ctrl+c 是否成功
            # 如果剪贴板仍是标记值，说明目标应用不支持全选或复制失败
            if clipboard_marker and text == clipboard_marker:
                # 取消可能存在的选中状态
                keyboard.release('ctrl')
                keyboard.release('shift')
                time.sleep(0.03)
                keyboard.press_and_release('left')
                self._restore_clipboard(saved_clipboard)
                return

            log_info(f"全文内容: '{text[:100] if text else '(空)'}'")

            if text and text.strip():
                # 取消选中（按左箭头移动光标到开头）
                keyboard.release('ctrl')
                keyboard.release('shift')
                time.sleep(0.05)
                keyboard.press_and_release('left')

                # 立即恢复剪贴板（不用定时器，避免与写作线程的剪贴板操作竞态）
                self._restore_clipboard(saved_clipboard)

                # 开始写作（全文模式）
                self._start_writing(text.strip(), has_selection=False)
            else:
                self._restore_clipboard(saved_clipboard)
                log_debug("没有可用的文本进行写作")

        except Exception as e:
            log_error(f"处理全文失败: {e}")
            self._restore_clipboard(saved_clipboard)

    def _restore_clipboard(self, saved_clipboard: str):
        """恢复剪贴板内容"""
        if saved_clipboard:
            try:
                import pyperclip
                pyperclip.copy(saved_clipboard)
                log_debug("剪贴板已恢复")
            except Exception:
                pass

    def _start_writing(self, text: str, has_selection: bool = True):
        """开始写作

        Args:
            text: 待写作的文本
            has_selection: 是否有选中文本（True=只替换选中，False=替换全部）
        """
        if not text or not text.strip():
            return

        log_info(f"开始写作 - 文本内容: '{text[:100]}...' (has_selection={has_selection})")

        # 获取保留原文设置
        keep_original = self._config.get('writing.keep_original', False)

        # 不显示 Toast 提示，避免获取焦点导致选中状态消失

        # 开始写作
        def on_complete(result: WritingResult):
            if result.error:
                ToastWidget.show_message("写作失败", result.error, "error")
            else:
                ToastWidget.show_message("写作完成", "文本已处理完成", "success")
                log_info(f"写作完成: {result.source_language} -> {result.target_language}")

        self._writing_service.writing_command(
            text,
            has_selection=has_selection,
            keep_original=keep_original,
            on_complete=on_complete
        )

    def _on_selection_finished(self):
        """划词选择完成 - 显示翻译图标按钮"""
        if not self._tray_icon._is_enabled:
            return

        text = capture_text_direct()

        if not text or not text.strip():
            self._translate_button.hide()
            return

        # 获取鼠标位置
        mouse_pos = self._selection_detector.get_last_position()

        if mouse_pos is None:
            from PyQt6.QtGui import QCursor
            cursor = QCursor.pos()
            mouse_pos = (cursor.x(), cursor.y())

        # 获取来源程序名（用于判断是否是浏览器，决定图标显示延迟）
        try:
            from .core.text_capture import get_last_program_name
            program_name = get_last_program_name()
        except ImportError:
            from src.core.text_capture import get_last_program_name
            program_name = get_last_program_name()

        # 保存选中文本到翻译按钮（不更新 _last_text，它只记录最后一次发起翻译的文本）
        selected_text = text.strip()
        self._translate_button.set_selected_text(selected_text)

        # 显示翻译图标按钮（统一方式）
        self._translate_button.show_at_position(mouse_pos, selected_text, program_name)

    def _on_translate_button_clicked(self):
        """翻译按钮点击 - 使用 translator_window 进行翻译"""
        text = self._translate_button.get_selected_text()
        if not text or not text.strip():
            return

        # 检查是否已经有相同的文本正在翻译
        if text == self._last_text and self._translator_window.isVisible() and self._translator_window.is_auto_mode():
            return

        self._last_text = text.strip()

        # 使用用户实际点击时的鼠标位置，让翻译窗口出现在点击位置附近
        cursor_pos = QCursor.pos()
        mouse_pos = (cursor_pos.x(), cursor_pos.y())

        # 使用 translator_window 的自动翻译功能
        self._translator_window.show_at_mouse(mouse_pos, self._last_text)

    def _on_translator_window_closed(self):
        """翻译窗口关闭"""
        self._last_text = ""

    def _on_enabled_changed(self, enabled: bool):
        self._selection_detector.set_enabled(enabled)

        if enabled:
            self._tray_icon.show_message(APP_NAME, "已启用", "info")
        else:
            self._tray_icon.show_message(APP_NAME, "已禁用", "info")
            self._translate_button.hide()
            self._translator_window.hide()

    def _on_settings_requested(self):
        dialog = get_settings_dialog()
        dialog._load_settings()
        dialog._center_window()
        dialog.exec()

    def _on_translator_window_requested(self):
        """双击托盘或点击菜单显示翻译窗口"""
        # 先隐藏划词翻译相关窗口
        self._translate_button.hide()
        self._last_text = ""

        # 如果窗口已可见，唤醒到前台
        if self._translator_window.isVisible() and not self._translator_window.is_minimized():
            self._translator_window.bring_to_front()
        else:
            # 显示翻译窗口
            self._translator_window.show_window()

    def _on_history_requested(self):
        """显示翻译历史窗口"""
        self._translate_button.hide()
        self._last_text = ""

        # 显示历史窗口
        history_window = get_history_window()
        history_window.show_window()

    def _on_help_requested(self):
        """显示帮助窗口"""
        self._translate_button.hide()

        # 显示帮助窗口
        help_window = get_help_window()
        help_window.show()
        help_window.activateWindow()
        help_window.raise_()

    def _on_exit_requested(self):
        self.stop()
        QApplication.quit()


class SingleInstance:
    """单实例检查器（使用 Windows Mutex）"""

    def __init__(self, app_id: str):
        self._app_id = app_id
        self._mutex = None
        self._is_first_instance = False

    def try_lock(self) -> bool:
        """尝试获取实例锁，返回是否是第一个实例"""
        if sys.platform == 'win32':
            try:
                import ctypes
                # 创建命名 Mutex
                mutex_name = f"Global\\{self._app_id}"
                self._mutex = ctypes.windll.kernel32.CreateMutexW(
                    None, False, mutex_name
                )
                last_error = ctypes.windll.kernel32.GetLastError()

                # ERROR_ALREADY_EXISTS = 183，表示 Mutex 已存在
                if last_error == 183:
                    self._is_first_instance = False
                    return False
                else:
                    self._is_first_instance = True
                    return True
            except Exception as e:
                log_error(f"创建 Mutex 失败: {e}")
                # 如果创建失败，允许程序继续运行
                return True
        else:
            # 非 Windows 平台，暂时允许多实例
            return True

    def release(self):
        """释放实例锁"""
        if sys.platform == 'win32' and self._mutex:
            try:
                import ctypes
                ctypes.windll.kernel32.ReleaseMutex(self._mutex)
                ctypes.windll.kernel32.CloseHandle(self._mutex)
            except Exception:
                pass
            self._mutex = None


def main():
    # 单实例检查
    try:
        from .config import APP_ID
    except ImportError:
        from src.config import APP_ID
    single_instance = SingleInstance(APP_ID)

    if not single_instance.try_lock():
        # 已有实例在运行，显示提示
        app = QApplication(sys.argv)
        QMessageBox.warning(
            None,
            APP_NAME,
            f"{APP_NAME} 已经在运行中！\n\n请在系统托盘查找已有实例。",
            QMessageBox.StandardButton.Ok
        )
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    # 设置应用图标（任务栏图标）
    icon_path = Path(__file__).parent.parent / "assets" / "icon.png"
    if icon_path.exists():
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))

    # 主控制器引用（延迟初始化）
    controller = None

    # 定义启动完成后的初始化函数
    def on_splash_finished():
        nonlocal controller
        controller = MainController()
        controller.start()
        # 启动时清理旧日志（超过 7 天的日志文件）
        try:
            get_logger().clear_old_logs(days=7)
        except Exception:
            pass

    # 显示启动动画，动画完成后初始化主控制器
    show_splash_screen(on_splash_finished)

    exit_code = app.exec()

    if controller:
        controller.stop()
    # 释放单实例锁
    single_instance.release()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()