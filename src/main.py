"""QTranslator - 主入口文件"""
from __future__ import annotations
import sys
from pathlib import Path

# 确保 src 和项目根目录在 sys.path 中（直接运行 main.py 时）
_src_dir = Path(__file__).parent
_project_dir = _src_dir.parent
for _d in (str(_src_dir), str(_project_dir)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

# SplashScreen 提前导入（已在下方 import 块中导入，此处备选）
try:
    from .ui.splash_screen import SplashScreen
except ImportError:
    from src.ui.splash_screen import SplashScreen
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
    QSpinBox, QKeySequenceEdit, QColorDialog, QSlider, QToolTip,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QPoint, QTimer, QPropertyAnimation, QRect, QByteArray, QEvent, QSize
from PyQt6.QtGui import QFont, QColor, QCursor, QMouseEvent, QAction, QIcon, QPixmap, QPainter, QPen, QKeySequence, QPolygonF, QBrush, QGuiApplication
from PyQt6.QtCore import QPointF
from PyQt6.QtSvg import QSvgRenderer

try:
    from .utils.context_probe import probe_context_limit, guess_context_limit
except ImportError:
    from src.utils.context_probe import probe_context_limit, guess_context_limit

# 设置 Windows 高 DPI 支持
import ctypes
try:
    ctypes.windll.user32.SetProcessDpiAwareness(2)
except Exception:
    pass


# ── 启动耗时打点：定位慢启动（bootloader/DLL 加载 vs Python 导入 vs 初始化）──
import time as _boot_time
_MODULE_ENTER = _boot_time.time()


def _process_create_ts():
    """进程创建时间戳（含 PyInstaller bootloader 启动前的时刻）"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32

        class _FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                        ("dwHighDateTime", ctypes.c_uint32)]

        # 必须显式声明原型：GetCurrentProcess 返回的伪句柄高位全 1，
        # 默认按 32 位 int 处理会丢失信息导致 GetProcessTimes 失败
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [
            ctypes.POINTER(_FILETIME)] * 4
        create = _FILETIME()
        dummy = _FILETIME()
        if k32.GetProcessTimes(k32.GetCurrentProcess(),
                               ctypes.byref(create), ctypes.byref(dummy),
                               ctypes.byref(dummy), ctypes.byref(dummy)):
            ft100ns = create.dwLowDateTime | (create.dwHighDateTime << 32)
            return ft100ns / 1e7 - 11644473600  # FILETIME → Unix 时间戳
    except Exception:
        pass
    return None


_PROCESS_CREATE = _process_create_ts()


def _startup_timing(label):
    """启动阶段耗时打点 → logs/startup_timing.log（排查企业版慢启动用）"""
    try:
        now = time.time()
        parts = [datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], label]
        if _PROCESS_CREATE is not None:
            parts.append(f"进程创建至今={now - _PROCESS_CREATE:.2f}s")
        parts.append(f"模块导入至今={now - _MODULE_ENTER:.2f}s")
        parts.append(f"frozen={getattr(sys, 'frozen', False)}")
        log_dir = Path(os.environ.get(
            "LOCALAPPDATA", str(Path.home()))) / "QTranslator" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "startup_timing.log", "a", encoding="utf-8") as f:
            f.write(" | ".join(parts) + "\n")
    except Exception:
        pass


_startup_timing('main 模块导入完成（含 PyQt6/全部依赖加载）')


class _CtxProbeEmitter(QObject):
    """上下文探测后台线程 -> 主线程信号桥"""
    done = pyqtSignal(int, int, str)  # (序号, tokens, 来源 api/guess)


class _ChatApiTestWorker(QThread):
    """AI 对话独立 API 连通性测试线程：发一条最小请求验证通路，
    成功后顺带探测模型上下文长度（/models 端点优先，查不到退回内置表）"""
    ok = pyqtSignal(int)    # 测试通过，参数为探测到的上下文 tokens（0=未探测到）
    fail = pyqtSignal(str)  # 测试失败，参数为错误信息

    def __init__(self, api_key: str, base_url: str, model: str,
                 timeout: int, parent=None):
        super().__init__(parent)
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout = max(5, int(timeout or 60))

    def run(self):
        try:
            from openai import OpenAI
            # max_retries=0：测试要快速反馈不通，不做 SDK 默认 2 次自动重试
            client = OpenAI(api_key=self._api_key or 'sk-no-key',
                            base_url=self._base_url, timeout=self._timeout,
                            max_retries=0)
            # 最小请求：只要求 1 个 token，验证 key/base_url/model 全链路可用
            client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                stream=False,
            )
        except Exception as e:
            self.fail.emit(str(e).strip() or type(e).__name__)
            return
        # 测试通过：探测上下文窗口（探测失败不影响测试结论）
        tokens = probe_context_limit(self._base_url, self._api_key, self._model,
                                     timeout=min(self._timeout, 8.0))
        if not tokens:
            tokens = guess_context_limit(self._model)
        self.ok.emit(int(tokens or 0))


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


class ClickableLabel(QLabel):
    """可点击标签（用于快捷键清除按钮，避免 QPushButton 在 Windows 上的默认焦点框）"""

    clicked = pyqtSignal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


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
            # Windows: C:\Users\用户名\AppData\Local\QTranslator
            base_dir = Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')))
            app_dir = base_dir / "QTranslator"

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

# ── 启动计时 ──
_import_t0 = time.time()
_startup_timings = []

def _startup_log(msg: str):
    now = time.time()
    _startup_timings.append((now, msg))
    print(f"[Startup] {msg}", file=sys.stderr, flush=True)

def _flush_startup_log():
    try:
        logger = get_logger()
        for _ts, _msg in _startup_timings:
            logger.info(f"[Startup] {_msg}")
    except Exception:
        pass
    _startup_timings.clear()

# ── 模块导入 ──
try:
    from .config import get_config, APP_NAME
    from .core.text_capture import get_text_capture, capture_text_direct
    from .core.selection_detector import get_selection_detector
    from .core.translator import get_translator, reinitialize_translator
    from .core.writing import get_writing_service, WritingResult
    from .core.custom_actions import get_custom_action_manager
    from .core.mcp_client import get_mcp_manager
    from .ui.translate_button import get_translate_button
    from .ui.selection_toolbar import get_selection_toolbar
    from .ui.word_popup import show_word_popup, is_english_word
    from .ui.chat_window import get_chat_window
    from .ui.tray_icon import get_tray_icon
    from .ui.translator_window import get_translator_window
    from .ui.history_window import get_history_window
    from .ui.vocabulary_window import get_vocabulary_window
    from .ui.help_window import get_help_window
    from .ui.splash_screen import SplashScreen
    from .utils.logger import get_logger, log_info, log_error, log_debug, log_warning, log_exception
    from .utils.history import add_translation_history
    from .utils.theme import get_theme, get_scrollbar_style, get_lineedit_style, get_combobox_style, get_checkbox_style, get_spinbox_style, THEME_DISPLAY_NAMES
    from .utils.hotkey_manager import get_hotkey_manager
    from .utils.selection_blacklist import (
        normalize_blacklist_entries, normalize_exe, entries_for_config, get_active_blacklist_exes,
    )
    from .utils.tts import (
        EDGE_TTS_VOICE_PRESETS, EDGE_TTS_RATE_SLIDER_MIN, EDGE_TTS_RATE_SLIDER_MAX,
        EDGE_TTS_VOLUME_SLIDER_MIN, EDGE_TTS_VOLUME_SLIDER_MAX,
        edge_percent_from_slider, parse_edge_percent_for_slider,
    )
except ImportError:
    from src.config import get_config, APP_NAME
    from src.core.text_capture import get_text_capture, capture_text_direct
    from src.core.selection_detector import get_selection_detector
    from src.core.translator import get_translator, reinitialize_translator
    from src.core.writing import get_writing_service, WritingResult
    from src.core.custom_actions import get_custom_action_manager
    from src.core.mcp_client import get_mcp_manager
    from src.ui.translate_button import get_translate_button
    from src.ui.selection_toolbar import get_selection_toolbar
    from src.ui.word_popup import show_word_popup, is_english_word
    from src.ui.chat_window import get_chat_window
    from src.ui.tray_icon import get_tray_icon
    from src.ui.translator_window import get_translator_window
    from src.ui.history_window import get_history_window
    from src.ui.vocabulary_window import get_vocabulary_window
    from src.ui.help_window import get_help_window
    from src.ui.splash_screen import SplashScreen
    from src.utils.logger import get_logger, log_info, log_error, log_debug, log_warning, log_exception
    from src.utils.history import add_translation_history
    from src.utils.theme import get_theme, get_scrollbar_style, get_lineedit_style, get_combobox_style, get_checkbox_style, get_spinbox_style, THEME_DISPLAY_NAMES
    from src.utils.hotkey_manager import get_hotkey_manager
    from src.utils.selection_blacklist import (
        normalize_blacklist_entries, normalize_exe, entries_for_config, get_active_blacklist_exes,
    )
    from src.utils.tts import (
        EDGE_TTS_VOICE_PRESETS, EDGE_TTS_RATE_SLIDER_MIN, EDGE_TTS_RATE_SLIDER_MAX,
        EDGE_TTS_VOLUME_SLIDER_MIN, EDGE_TTS_VOLUME_SLIDER_MAX,
        edge_percent_from_slider, parse_edge_percent_for_slider,
    )

_startup_log(f"模块导入总计: {(time.time() - _import_t0) * 1000:.0f}ms")

def _auto_start_exe_path() -> str:
    """当前生效的自启命令：打包版为 exe 路径，开发模式为 python + __main__.py。"""
    if getattr(sys, 'frozen', False):
        return sys.executable
    main_py = Path(__file__).parent.parent / "__main__.py"
    return f'"{sys.executable}" "{main_py}"'


def setup_auto_start(enable: bool):
    """设置开机自启（Windows）"""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_id = APP_NAME.replace(" ", "")
        
        if enable:
            exe_path = _auto_start_exe_path()
            
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


def sync_auto_start_path():
    """开机自启自愈：auto_start 开启时，若注册表中的启动命令与当前
    不一致（用户替换/移动了 exe，或键值缺失），重写为当前路径，
    保证更换 exe 后开机自启不失效。"""
    try:
        if not get_config().get('startup.auto_start', False):
            return
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_id = APP_NAME.replace(" ", "")
        exe_path = _auto_start_exe_path()
        current = None
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                 winreg.KEY_READ)
            try:
                current, _ = winreg.QueryValueEx(key, app_id)
            except FileNotFoundError:
                current = None
            winreg.CloseKey(key)
        except FileNotFoundError:
            current = None
        if current != exe_path:
            setup_auto_start(True)
    except Exception as e:
        log_error(f"开机自启自愈失败: {e}")


class SettingsDialog(QWidget):
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

        # 主题切换时立即刷新（含 QToolTip 等窗口级样式，否则切主题后设置窗口仍是旧样式）
        try:
            from .utils.theme import get_theme_manager
        except ImportError:
            from src.utils.theme import get_theme_manager
        get_theme_manager().theme_changed.connect(self.update_theme)

        # 设置无边框窗口属性
        # 不常驻置顶：「始终置顶」设置只控制翻译窗口
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 用时置顶、切走降级：「始终置顶」设置只控制翻译窗口
        try:
            from .utils.window_front import install_activation_topmost
        except ImportError:
            from src.utils.window_front import install_activation_topmost
        install_activation_topmost(self)
        self._enable_windows_window_management()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(480, 620)
        self.resize(500, 680)

        # 任务栏图标
        self._set_window_icon()

        self._config = get_config()
        self._applied_theme_signature = None
        self._setup_ui()
        self._load_settings()

        # 应用主题
        self._apply_theme()
        # 居中显示

        self._center_window()


    def _enable_windows_window_management(self):
        """Windows Win32 样式：确保任务栏图标 + 系统快捷键"""
        try:
            if not __import__("sys").platform.startswith("win"):
                return
            import ctypes
            hwnd = int(self.winId())
            GWL_STYLE = -16
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            new_style = style | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            )
        except Exception:
            pass

    def _set_window_icon(self):
        """设置窗口图标（任务栏图标），Win32 API 兜底确保打包后可用"""
        import sys
        # 解析资源路径（兼容打包环境）
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent
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
        self._close_btn.clicked.connect(self.hide)
        title_layout.addWidget(self._close_btn)

        content_layout.addWidget(self._title_bar)

        # 滚动区域
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 垂直滚动条常显：避免内容高度变化时滚动条出现/消失导致视口宽度变化
        # → 所有控件横向重排 → 界面闪烁
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

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

        self._lang_detect_combo = QComboBox()
        self._lang_detect_combo.setMinimumHeight(32)
        _lang_items = (
            ("百度", "baidu"),
            ("Google", "google"),
            ("Bing", "bing"),
            ("本地", "local"),
        )
        for lab, val in _lang_items:
            self._lang_detect_combo.addItem(lab, val)
        self._lang_detect_label = QLabel("语种检测:")
        api_layout.addRow(self._lang_detect_label, self._lang_detect_combo)

        self._lang_detect_hint_label = QLabel(
            "任一网关请求失败或解析不到语言时，会自动回退使用本地检测。"
        )
        self._lang_detect_hint_label.setProperty("class", "hint")
        self._lang_detect_hint_label.setWordWrap(True)
        api_layout.addRow("", self._lang_detect_hint_label)

        scroll_layout.addWidget(self._api_group)

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
        self._hotkey_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._hotkey_btn.setAutoDefault(False)
        self._hotkey_btn.setDefault(False)
        self._hotkey_label = QLabel("唤醒翻译窗口:")
        self._hotkey_row, self._hotkey_clear_btn = self._create_hotkey_row(self._hotkey_btn)
        hotkey_layout.addRow(self._hotkey_label, self._hotkey_row)

        # 写作快捷键按钮
        self._writing_hotkey_btn = QPushButton("Ctrl+I")
        self._writing_hotkey_btn.setObjectName("hotkeyBtn2")
        self._writing_hotkey_btn.setMinimumHeight(32)
        self._writing_hotkey_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._writing_hotkey_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._writing_hotkey_btn.setAutoDefault(False)
        self._writing_hotkey_btn.setDefault(False)
        self._writing_hotkey_label = QLabel("划词写作:")
        self._writing_hotkey_row, self._writing_hotkey_clear_btn = self._create_hotkey_row(
            self._writing_hotkey_btn
        )
        hotkey_layout.addRow(self._writing_hotkey_label, self._writing_hotkey_row)

        self._selection_translate_hotkey_btn = QPushButton("Ctrl+`")
        self._selection_translate_hotkey_btn.setObjectName("hotkeyBtn3")
        self._selection_translate_hotkey_btn.setMinimumHeight(32)
        self._selection_translate_hotkey_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._selection_translate_hotkey_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._selection_translate_hotkey_btn.setAutoDefault(False)
        self._selection_translate_hotkey_btn.setDefault(False)
        self._selection_translate_hotkey_label = QLabel("选中翻译:")
        self._selection_translate_hotkey_row, self._selection_translate_hotkey_clear_btn = (
            self._create_hotkey_row(self._selection_translate_hotkey_btn)
        )
        hotkey_layout.addRow(self._selection_translate_hotkey_label, self._selection_translate_hotkey_row)

        self._ai_chat_hotkey_btn = QPushButton("Ctrl+Shift+P")
        self._ai_chat_hotkey_btn.setObjectName("hotkeyBtn4")
        self._ai_chat_hotkey_btn.setMinimumHeight(32)
        self._ai_chat_hotkey_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._ai_chat_hotkey_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._ai_chat_hotkey_btn.setAutoDefault(False)
        self._ai_chat_hotkey_btn.setDefault(False)
        self._ai_chat_hotkey_label = QLabel("AI 对话:")
        self._ai_chat_hotkey_row, self._ai_chat_hotkey_clear_btn = (
            self._create_hotkey_row(self._ai_chat_hotkey_btn)
        )
        hotkey_layout.addRow(self._ai_chat_hotkey_label, self._ai_chat_hotkey_row)

        # 快捷键提示文字
        self._hotkey_hint_label = QLabel("点击按钮后按下新的快捷键组合，点击 × 可清除")
        self._hotkey_hint_label.setProperty("class", "hint")
        self._hotkey_hint_label.setWordWrap(True)
        hotkey_layout.addRow("", self._hotkey_hint_label)

        # 存储当前快捷键值
        self._hotkey_value = "Ctrl+O"
        self._writing_hotkey_value = "Ctrl+I"
        self._selection_translate_hotkey_value = "Ctrl+`"
        self._ai_chat_hotkey_value = "Ctrl+Shift+P"

        # 监听按钮点击
        self._hotkey_btn.clicked.connect(lambda: self._start_hotkey_capture("translator"))
        self._writing_hotkey_btn.clicked.connect(lambda: self._start_hotkey_capture("writing"))
        self._selection_translate_hotkey_btn.clicked.connect(
            lambda: self._start_hotkey_capture("selection_translate")
        )
        self._ai_chat_hotkey_btn.clicked.connect(
            lambda: self._start_hotkey_capture("ai_chat")
        )
        self._hotkey_clear_btn.clicked.connect(lambda: self._clear_hotkey("translator"))
        self._writing_hotkey_clear_btn.clicked.connect(lambda: self._clear_hotkey("writing"))
        self._selection_translate_hotkey_clear_btn.clicked.connect(
            lambda: self._clear_hotkey("selection_translate")
        )
        self._ai_chat_hotkey_clear_btn.clicked.connect(
            lambda: self._clear_hotkey("ai_chat")
        )

        scroll_layout.addWidget(self._hotkey_group)

        # 划词黑名单
        self._blacklist_group = QGroupBox("划词黑名单")
        blacklist_outer = QVBoxLayout(self._blacklist_group)
        blacklist_outer.setSpacing(8)
        blacklist_outer.setContentsMargins(12, 20, 12, 12)

        self._blacklist_hint_label = QLabel(
            "左侧为划词黑名单（这些程序中不显示划词图标）；点击 → 移出后出现在右侧，"
            "可从右侧点击 ← 重新加入黑名单。进程名可在任务管理器「详细信息」中查看。"
        )
        self._blacklist_hint_label.setProperty("class", "hint")
        self._blacklist_hint_label.setWordWrap(True)
        blacklist_outer.addWidget(self._blacklist_hint_label)

        panels_row = QHBoxLayout()
        panels_row.setSpacing(12)

        # 左侧：黑名单
        left_panel = QVBoxLayout()
        left_panel.setSpacing(6)
        self._blacklist_left_title = QLabel("黑名单")
        self._blacklist_left_title.setProperty("class", "blacklistPanelTitle")
        left_panel.addWidget(self._blacklist_left_title)

        self._blacklist_active_host = QWidget()
        self._blacklist_active_layout = QVBoxLayout(self._blacklist_active_host)
        self._blacklist_active_layout.setContentsMargins(0, 0, 0, 0)
        self._blacklist_active_layout.setSpacing(4)

        self._blacklist_active_scroll = QScrollArea()
        self._blacklist_active_scroll.setWidgetResizable(True)
        self._blacklist_active_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self._blacklist_active_scroll.setMinimumHeight(160)
        self._blacklist_active_scroll.setMaximumHeight(200)
        self._blacklist_active_scroll.setWidget(self._blacklist_active_host)
        left_panel.addWidget(self._blacklist_active_scroll)

        # 右侧：已移出
        right_panel = QVBoxLayout()
        right_panel.setSpacing(6)
        self._blacklist_right_title = QLabel("已移出黑名单")
        self._blacklist_right_title.setProperty("class", "blacklistPanelTitle")
        right_panel.addWidget(self._blacklist_right_title)

        self._blacklist_inactive_host = QWidget()
        self._blacklist_inactive_layout = QVBoxLayout(self._blacklist_inactive_host)
        self._blacklist_inactive_layout.setContentsMargins(0, 0, 0, 0)
        self._blacklist_inactive_layout.setSpacing(4)

        self._blacklist_inactive_scroll = QScrollArea()
        self._blacklist_inactive_scroll.setWidgetResizable(True)
        self._blacklist_inactive_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self._blacklist_inactive_scroll.setMinimumHeight(160)
        self._blacklist_inactive_scroll.setMaximumHeight(200)
        self._blacklist_inactive_scroll.setWidget(self._blacklist_inactive_host)
        right_panel.addWidget(self._blacklist_inactive_scroll)

        panels_row.addLayout(left_panel, 1)
        panels_row.addLayout(right_panel, 1)
        blacklist_outer.addLayout(panels_row)

        add_row = QWidget()
        add_layout = QHBoxLayout(add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.setSpacing(8)
        self._blacklist_app_edit = QLineEdit()
        self._blacklist_app_edit.setPlaceholderText("应用名称")
        self._blacklist_app_edit.setMinimumHeight(32)
        self._blacklist_exe_edit = QLineEdit()
        self._blacklist_exe_edit.setPlaceholderText("进程名，如 notepad.exe")
        self._blacklist_exe_edit.setMinimumHeight(32)
        self._blacklist_add_btn = QPushButton("添加")
        self._blacklist_add_btn.setObjectName("blacklistAddBtn")
        self._blacklist_add_btn.setMinimumHeight(32)
        self._blacklist_add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._blacklist_add_btn.clicked.connect(self._on_add_blacklist_entry)
        add_layout.addWidget(self._blacklist_app_edit, 2)
        add_layout.addWidget(self._blacklist_exe_edit, 2)
        add_layout.addWidget(self._blacklist_add_btn, 0)
        blacklist_outer.addWidget(add_row)

        self._blacklist_entries = []
        scroll_layout.addWidget(self._blacklist_group)

        # 划词工具栏设置组
        self._toolbar_group = QGroupBox("划词工具栏")
        toolbar_layout = QFormLayout(self._toolbar_group)
        toolbar_layout.setSpacing(10)
        toolbar_layout.setContentsMargins(12, 20, 12, 12)
        toolbar_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._trigger_mode_combo = QComboBox()
        self._trigger_mode_combo.setMinimumHeight(32)
        self._trigger_mode_combo.addItem("悬浮工具栏（翻译/润色/总结/AI对话/自定义）", "toolbar")
        self._trigger_mode_combo.addItem("翻译图标按钮（经典模式）", "button")
        self._trigger_mode_label = QLabel("划词触发方式:")
        toolbar_layout.addRow(self._trigger_mode_label, self._trigger_mode_combo)

        ext_btn_row = QHBoxLayout()
        ext_btn_row.setSpacing(8)
        self._open_actions_dir_btn = QPushButton("打开自定义功能目录")
        self._open_actions_dir_btn.setMinimumHeight(30)
        self._open_actions_dir_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._open_actions_dir_btn.clicked.connect(self._on_open_actions_dir)
        ext_btn_row.addWidget(self._open_actions_dir_btn)

        self._open_skills_dir_btn = QPushButton("打开技能目录")
        self._open_skills_dir_btn.setMinimumHeight(30)
        self._open_skills_dir_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._open_skills_dir_btn.clicked.connect(self._on_open_skills_dir)
        ext_btn_row.addWidget(self._open_skills_dir_btn)

        self._open_mcp_cfg_btn = QPushButton("打开 MCP 配置")
        self._open_mcp_cfg_btn.setMinimumHeight(30)
        self._open_mcp_cfg_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._open_mcp_cfg_btn.clicked.connect(self._on_open_mcp_config)
        ext_btn_row.addWidget(self._open_mcp_cfg_btn)
        ext_btn_row.addStretch()
        toolbar_layout.addRow("", ext_btn_row)

        # 高级：actions/ 目录 .py 扩展勾选区（_load_settings 中根据目录动态重建）
        self._action_checks_box = QWidget()
        self._action_checks_layout = QVBoxLayout(self._action_checks_box)
        self._action_checks_layout.setContentsMargins(0, 0, 0, 0)
        self._action_checks_layout.setSpacing(4)
        toolbar_layout.addRow("", self._action_checks_box)

        scroll_layout.addWidget(self._toolbar_group)

        # AI 对话设置组
        self._chat_group = QGroupBox("AI 对话")
        chat_layout = QVBoxLayout(self._chat_group)
        chat_layout.setSpacing(8)
        chat_layout.setContentsMargins(12, 20, 12, 12)

        # 共用 API 勾选框（全宽，与其他设置组风格一致）
        self._chat_shared_api_check = QCheckBox("与翻译共用 API 配置")
        self._chat_shared_api_check.setChecked(True)
        self._chat_shared_api_check.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._chat_shared_api_check.toggled.connect(self._on_chat_shared_api_toggled)
        chat_layout.addWidget(self._chat_shared_api_check)

        self._chat_shared_api_hint_label = QLabel(
            "取消后可使用独立于翻译功能的 API Key、Base URL、Model 和 Timeout"
        )
        self._chat_shared_api_hint_label.setProperty("class", "checkbox-hint")
        self._chat_shared_api_hint_label.setWordWrap(True)
        chat_layout.addWidget(self._chat_shared_api_hint_label)

        # 模型上下文长度（行内标签 + 输入框）
        ctx_row = QHBoxLayout()
        ctx_row.setSpacing(8)
        ctx_label = QLabel("模型上下文长度:")
        self._ctx_limit_spin = StyledSpinBox()
        self._ctx_limit_spin.setMinimumHeight(32)
        self._ctx_limit_spin.setRange(4096, 1048576)
        self._ctx_limit_spin.setSingleStep(1024)
        self._ctx_limit_spin.setSuffix(" tokens")
        ctx_row.addWidget(ctx_label)
        ctx_row.addWidget(self._ctx_limit_spin, 1)
        ctx_row.addStretch(3)
        chat_layout.addLayout(ctx_row)

        # 上下文长度说明
        self._chat_hint_label = QLabel(
            "对话历史不限条数；超过约 70% 上下文窗口时，自动按开源摘要缓冲策略\n"
            "（LangChain ConversationSummaryBufferMemory 模式）压缩较早对话为摘要，最近消息原文保留。"
        )
        self._chat_hint_label.setProperty("class", "hint")
        self._chat_hint_label.setWordWrap(True)
        chat_layout.addWidget(self._chat_hint_label)

        # --- AI 对话独立 API 字段（勾选"共用"时隐藏） ---
        self._chat_api_form_widget = QWidget()
        self._chat_api_form_widget.setObjectName("chatApiFormWidget")
        self._chat_api_form_widget.setAutoFillBackground(False)
        # 必须带 ID 选择器：无选择器 QSS 在样式链合并时会误匹配 QToolTip，
        # 把 tooltip 背景覆盖成 transparent（透出黑色）
        self._chat_api_form_widget.setStyleSheet(
            "#chatApiFormWidget { background: transparent; }")
        chat_api_form = QFormLayout(self._chat_api_form_widget)
        chat_api_form.setSpacing(10)
        chat_api_form.setContentsMargins(0, 4, 0, 0)
        chat_api_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._chat_api_key_edit = QLineEdit()
        self._chat_api_key_edit.setMinimumHeight(32)
        self._chat_api_key_edit.setPlaceholderText("sk-...")
        self._chat_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._chat_api_key_edit.setTextMargins(0, 0, 32, 0)
        self._chat_api_key_label = QLabel("API Key:")
        chat_api_form.addRow(self._chat_api_key_label, self._chat_api_key_edit)

        self._chat_api_url_edit = QLineEdit()
        self._chat_api_url_edit.setMinimumHeight(32)
        self._chat_api_url_edit.setPlaceholderText("https://api.openai.com/v1")
        self._chat_api_url_label = QLabel("Base URL:")
        chat_api_form.addRow(self._chat_api_url_label, self._chat_api_url_edit)

        self._chat_model_edit = QLineEdit()
        self._chat_model_edit.setMinimumHeight(32)
        self._chat_model_edit.setPlaceholderText("gpt-4o-mini")
        self._chat_model_label = QLabel("Model:")
        chat_api_form.addRow(self._chat_model_label, self._chat_model_edit)

        self._chat_timeout_spin = StyledSpinBox()
        self._chat_timeout_spin.setMinimumHeight(32)
        self._chat_timeout_spin.setRange(10, 600)
        self._chat_timeout_spin.setValue(60)
        self._chat_timeout_spin.setSuffix(" 秒")
        self._chat_timeout_label = QLabel("Timeout:")
        chat_api_form.addRow(self._chat_timeout_label, self._chat_timeout_spin)

        self._chat_api_test_btn = QPushButton("测试连接")
        self._chat_api_test_btn.setObjectName("chatApiTestBtn")
        self._chat_api_test_btn.setMinimumHeight(32)
        self._chat_api_test_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._chat_api_test_btn.setToolTip("发送一条最小请求验证此 API 是否可用，"
                                           "通过后自动更新模型上下文长度")
        self._chat_api_test_btn.clicked.connect(self._on_test_chat_api)
        chat_api_form.addRow("连接测试:", self._chat_api_test_btn)
        self._chat_api_test_worker = None

        chat_layout.addWidget(self._chat_api_form_widget)
        self._on_chat_shared_api_toggled(True)

        scroll_layout.addWidget(self._chat_group)

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
        self._polishing_show_diff_hint_label = QLabel("勾选后，润色完成时将对原文与结果做词/短语级比对：浅红为删除片段，浅绿为新增片段")
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

        # 划词查词勾选框（应用内：翻译窗口原文/译文框）
        self._word_popup_check = QCheckBox("启用划词查词（应用内）")
        self._word_popup_check.toggled.connect(self._on_checkbox_toggled)
        translator_window_layout.addWidget(self._word_popup_check)

        self._word_popup_hint_label = QLabel("勾选后，在原文框或译文框中选中单个英文单词时，自动弹出单词释义和发音弹窗")
        self._word_popup_hint_label.setProperty("class", "checkbox-hint")
        self._word_popup_hint_label.setWordWrap(True)
        translator_window_layout.addWidget(self._word_popup_hint_label)

        # 划词查词勾选框（应用外：桌面任意位置）
        self._word_popup_global_check = QCheckBox("启用划词查词（应用外）")
        self._word_popup_global_check.toggled.connect(self._on_checkbox_toggled)
        translator_window_layout.addWidget(self._word_popup_global_check)

        self._word_popup_global_hint_label = QLabel("勾选后，在翻译窗口外的桌面任意位置（如浏览器、文档）选中单个英文单词时，自动弹出单词释义和发音弹窗")
        self._word_popup_global_hint_label.setProperty("class", "checkbox-hint")
        self._word_popup_global_hint_label.setWordWrap(True)
        translator_window_layout.addWidget(self._word_popup_global_hint_label)

        scroll_layout.addWidget(self._translator_window_group)

        # 朗读 TTS 设置
        self._tts_group = QGroupBox("朗读 (TTS)")
        tts_layout = QFormLayout(self._tts_group)
        tts_layout.setSpacing(10)
        tts_layout.setContentsMargins(12, 20, 12, 12)
        tts_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._tts_provider_combo = QComboBox()
        self._tts_provider_combo.addItems(["系统语音 (离线)", "Microsoft Edge 在线"])
        self._tts_provider_combo.setMinimumHeight(32)
        self._tts_provider_combo.currentIndexChanged.connect(
            lambda _i: self._update_tts_edge_controls_enabled()
        )

        self._tts_edge_voice_combo = QComboBox()
        self._tts_edge_voice_combo.setMinimumHeight(32)

        self._tts_rate_slider = QSlider(Qt.Orientation.Horizontal)
        self._tts_rate_slider.setRange(EDGE_TTS_RATE_SLIDER_MIN, EDGE_TTS_RATE_SLIDER_MAX)
        self._tts_rate_slider.setSingleStep(5)
        self._tts_rate_slider.setPageStep(10)
        self._tts_rate_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._tts_rate_slider.setTickInterval(25)
        self._tts_rate_value_label = QLabel("+0%")
        self._tts_rate_value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._tts_rate_value_label.setFixedWidth(46)
        self._tts_rate_slider.valueChanged.connect(self._on_tts_rate_slider_changed)
        _rate_row = QWidget()
        _rate_layout = QHBoxLayout(_rate_row)
        _rate_layout.setContentsMargins(0, 2, 0, 2)
        _rate_layout.setSpacing(8)
        _rate_layout.addWidget(self._tts_rate_slider, 1)
        _rate_layout.addWidget(self._tts_rate_value_label)

        self._tts_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._tts_volume_slider.setRange(EDGE_TTS_VOLUME_SLIDER_MIN, EDGE_TTS_VOLUME_SLIDER_MAX)
        self._tts_volume_slider.setSingleStep(5)
        self._tts_volume_slider.setPageStep(10)
        self._tts_volume_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._tts_volume_slider.setTickInterval(25)
        self._tts_volume_value_label = QLabel("+0%")
        self._tts_volume_value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._tts_volume_value_label.setFixedWidth(46)
        self._tts_volume_slider.valueChanged.connect(self._on_tts_volume_slider_changed)
        _vol_row = QWidget()
        _vol_layout = QHBoxLayout(_vol_row)
        _vol_layout.setContentsMargins(0, 2, 0, 2)
        _vol_layout.setSpacing(8)
        _vol_layout.addWidget(self._tts_volume_slider, 1)
        _vol_layout.addWidget(self._tts_volume_value_label)

        tts_layout.addRow(QLabel("引擎:"), self._tts_provider_combo)
        tts_layout.addRow(QLabel("Edge 音色:"), self._tts_edge_voice_combo)
        tts_layout.addRow(QLabel("语速:"), _rate_row)
        tts_layout.addRow(QLabel("音量:"), _vol_row)
        self._tts_hint_label = QLabel(
            "Edge tts需联网，使用神经网络朗读；合成或播放失败时会自动改用系统语音。"
        )
        self._tts_hint_label.setProperty("class", "checkbox-hint")
        self._tts_hint_label.setWordWrap(True)
        tts_layout.addRow("", self._tts_hint_label)
        self._update_tts_edge_controls_enabled()
        scroll_layout.addWidget(self._tts_group)

        # 系统设置组
        self._sys_group = QGroupBox("系统设置")
        sys_layout = QVBoxLayout(self._sys_group)
        sys_layout.setSpacing(8)
        sys_layout.setContentsMargins(12, 20, 12, 12)

        self._auto_start_check = QCheckBox("开机自动启动")
        self._auto_start_check.toggled.connect(self._on_checkbox_toggled)
        sys_layout.addWidget(self._auto_start_check)

        self._disable_update_check = QCheckBox("禁用更新检查")
        self._disable_update_check.toggled.connect(self._on_checkbox_toggled)
        sys_layout.addWidget(self._disable_update_check)

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
        self._cancel_btn.clicked.connect(self.hide)
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

        # 计算 disabled 输入框背景色（比 input_bg 略暗，用于置灰态）
        _disabled_c = QColor(t['input_bg'])
        t['input_disabled_bg'] = _disabled_c.darker(108).name()

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
            QLineEdit:disabled {{
                color: {t['text_muted']};
                background-color: {t['input_disabled_bg']};
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
            QSpinBox:disabled {{
                color: {t['text_muted']};
                background-color: {t['input_disabled_bg']};
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
            QPushButton#hotkeyBtn, QPushButton#hotkeyBtn2, QPushButton#hotkeyBtn3, QPushButton#hotkeyBtn4 {{
                background-color: {t['input_bg']};
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                padding: 4px 12px;
                color: {t['text_primary']};
                font-size: 13px;
                text-align: left;
            }}
            QPushButton#hotkeyBtn:hover, QPushButton#hotkeyBtn2:hover, QPushButton#hotkeyBtn3:hover, QPushButton#hotkeyBtn4:hover {{
                border-color: {t['accent_color']};
            }}
            QPushButton#hotkeyBtn:focus, QPushButton#hotkeyBtn2:focus, QPushButton#hotkeyBtn3:focus, QPushButton#hotkeyBtn4:focus {{
                outline: none;
                border: 1px solid {t['input_border']};
                background-color: {t['input_bg']};
                color: {t['text_primary']};
            }}
            QLabel#hotkeyClearBtn {{
                background-color: transparent;
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                color: {t['text_muted']};
                font-size: 16px;
                font-weight: bold;
                padding: 0;
            }}
            QLabel#hotkeyClearBtn:hover {{
                border: 1px solid {t['input_border']};
                color: {t['text_primary']};
                background-color: {t['button_hover']};
            }}

            QWidget#blacklistRow {{
                background-color: transparent;
            }}
            QLabel[class="blacklistPanelTitle"] {{
                color: {t['group_title']};
                font-size: 13px;
                font-weight: bold;
            }}
            QLabel#blacklistAppLabel {{
                color: {t['text_primary']};
                font-size: 13px;
            }}
            QLabel#blacklistExeLabel {{
                color: {t['text_muted']};
                font-size: 11px;
            }}
            QPushButton#blacklistMoveOutBtn, QPushButton#blacklistMoveInBtn {{
                background-color: transparent;
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                color: {t['text_muted']};
                font-size: 14px;
                font-weight: bold;
                min-width: 28px;
                max-width: 28px;
                min-height: 28px;
                max-height: 28px;
                padding: 0;
            }}
            QPushButton#blacklistMoveOutBtn:hover {{
                border-color: {t['accent_color']};
                color: {t['accent_color']};
                background-color: {t['button_hover']};
            }}
            QPushButton#blacklistMoveInBtn:hover {{
                border-color: {t['accent_color']};
                color: {t['accent_color']};
                background-color: {t['button_hover']};
            }}
            QPushButton#blacklistAddBtn {{
                background-color: {t['input_bg']};
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                color: {t['text_primary']};
                font-size: 13px;
                padding: 4px 14px;
            }}
            QPushButton#blacklistAddBtn:hover {{
                border-color: {t['accent_color']};
            }}

            /* AI 对话 API 测试按钮 */
            QPushButton#chatApiTestBtn {{
                background-color: {t['input_bg']};
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                color: {t['text_primary']};
                font-size: 13px;
                padding: 4px 14px;
            }}
            QPushButton#chatApiTestBtn:hover {{
                border-color: {t['accent_color']};
            }}
            QPushButton#chatApiTestBtn:disabled {{
                color: {t['text_muted']};
                background-color: {t['input_disabled_bg']};
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

        # Tooltip 是独立顶层控件，不能通过 _content_frame 的样式表覆盖，
        # 需在窗口层级设置（解决深色主题下 tooltip 黑条不可见问题）
        self.setStyleSheet(f"""
            QToolTip {{
                background-color: {t['bg_secondary']};
                color: {t['text_primary']};
                border: 1px solid {t['border_color']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
        """)

        # 动态样式：颜色选择器按钮（背景色随用户选择变化，需单独设置）
        self._update_color_btn_style(self._accent_color_btn, self._custom_accent)
        self._update_color_btn_style(self._bg_color_btn, self._custom_bg)

        # SpinBox 自定义箭头颜色
        self._font_size_spin.set_arrow_color(t['text_secondary'])
        self._ctx_limit_spin.set_arrow_color(t['text_secondary'])
        self._chat_timeout_spin.set_arrow_color(t['text_secondary'])

        # 缓存复选框图标并应用
        self._cached_check_icon = self._create_check_icon()
        self._cached_uncheck_icon = self._create_uncheck_icon()
        for cb in (self._auto_start_check, self._keep_original_check,
                   self._fixed_height_check, self._remember_size_check,
                   self._remember_position_check, self._always_on_top_check,
                   self._polishing_show_diff_check, self._animation_check,
                   self._word_popup_check, self._word_popup_global_check,
                   self._disable_update_check,
                   self._chat_shared_api_check):
            cb.setIcon(self._cached_check_icon if cb.isChecked() else self._cached_uncheck_icon)
        self._applied_theme_signature = self._get_theme_signature()

    def _get_theme_signature(self):
        """获取影响设置窗口样式的主题签名。"""
        return (
            self._config.get('theme.popup_style', 'dark'),
            self._config.get('theme.custom_accent', '#007AFF'),
            self._config.get('theme.custom_bg', '#2d2d2d'),
        )

    def _create_hotkey_row(self, hotkey_btn: QPushButton):
        """创建「快捷键按钮 + 清除按钮」行布局"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        hotkey_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        clear_btn = ClickableLabel("×")
        clear_btn.setObjectName("hotkeyClearBtn")
        clear_btn.setFixedSize(32, 32)
        clear_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clear_btn.setToolTip("清除快捷键")

        layout.addWidget(hotkey_btn)
        layout.addWidget(clear_btn)
        return row, clear_btn

    def _set_hotkey_btn_text(self, btn: QPushButton, value: str):
        """根据快捷键值更新按钮显示文本"""
        btn.setText(value if value else "点击设置快捷键")

    def _clear_blacklist_panel(self, layout: QVBoxLayout):
        """清空某一侧黑名单列表 UI。"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _create_blacklist_row_widget(
        self,
        entry: dict,
        *,
        side: str,
        target_layout: QVBoxLayout,
    ):
        """创建黑名单行：side 为 active（左）或 inactive（右）。"""
        row = QWidget()
        row.setObjectName("blacklistRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        app_label = QLabel(str(entry.get("app_name") or entry.get("exe", "")))
        app_label.setObjectName("blacklistAppLabel")
        exe_label = QLabel(str(entry.get("exe", "")))
        exe_label.setObjectName("blacklistExeLabel")
        text_col.addWidget(app_label)
        text_col.addWidget(exe_label)

        exe_key = str(entry.get("exe", ""))
        if side == "active":
            action_btn = QPushButton("→")
            action_btn.setObjectName("blacklistMoveOutBtn")
            action_btn.setToolTip("移出黑名单")
            action_btn.clicked.connect(lambda _checked=False, e=exe_key: self._on_move_blacklist_out(e))
        else:
            action_btn = QPushButton("←")
            action_btn.setObjectName("blacklistMoveInBtn")
            action_btn.setToolTip("加入黑名单")
            action_btn.clicked.connect(lambda _checked=False, e=exe_key: self._on_move_blacklist_in(e))

        action_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout.addLayout(text_col, 1)
        layout.addWidget(action_btn, 0)
        target_layout.addWidget(row)

    def _reload_blacklist_ui(self, entries=None):
        """根据条目数据刷新左右两侧黑名单列表。"""
        if entries is None:
            entries = normalize_blacklist_entries(self._config.get('selection.blacklist'))
        self._blacklist_entries = normalize_blacklist_entries(entries)

        active_entries = [e for e in self._blacklist_entries if e.get("enabled", True)]
        inactive_entries = [e for e in self._blacklist_entries if not e.get("enabled", True)]

        self._clear_blacklist_panel(self._blacklist_active_layout)
        self._clear_blacklist_panel(self._blacklist_inactive_layout)

        for entry in active_entries:
            self._create_blacklist_row_widget(entry, side="active", target_layout=self._blacklist_active_layout)
        for entry in inactive_entries:
            self._create_blacklist_row_widget(entry, side="inactive", target_layout=self._blacklist_inactive_layout)

        self._blacklist_active_layout.addStretch(1)
        self._blacklist_inactive_layout.addStretch(1)

        self._blacklist_left_title.setText(f"黑名单 ({len(active_entries)})")
        self._blacklist_right_title.setText(f"已移出黑名单 ({len(inactive_entries)})")

    def _collect_blacklist_entries_from_ui(self):
        """收集当前黑名单配置（enabled=True 为左侧黑名单）。"""
        return entries_for_config(self._blacklist_entries)

    def _set_blacklist_entry_enabled(self, exe: str, enabled: bool):
        """切换条目在左/右列表间的归属。"""
        for item in self._blacklist_entries:
            if item.get("exe") == exe:
                item["enabled"] = enabled
                break
        self._reload_blacklist_ui(self._blacklist_entries)

    def _on_move_blacklist_out(self, exe: str):
        """从黑名单移出到右侧。"""
        self._set_blacklist_entry_enabled(exe, False)

    def _on_move_blacklist_in(self, exe: str):
        """从右侧重新加入黑名单。"""
        self._set_blacklist_entry_enabled(exe, True)

    def _on_add_blacklist_entry(self):
        """添加自定义条目到左侧黑名单。"""
        exe = normalize_exe(self._blacklist_exe_edit.text())
        app_name = self._blacklist_app_edit.text().strip()
        if not exe:
            self._show_message_dialog("提示", "请输入进程名，例如 notepad.exe", "warning")
            return
        if not app_name:
            app_name = exe

        for entry in self._blacklist_entries:
            if entry.get("exe") == exe:
                if entry.get("enabled", True):
                    self._show_message_dialog("提示", f"{app_name} 已在黑名单中", "warning")
                else:
                    entry["app_name"] = app_name
                    entry["enabled"] = True
                    self._blacklist_exe_edit.clear()
                    self._blacklist_app_edit.clear()
                    self._reload_blacklist_ui(self._blacklist_entries)
                return

        self._blacklist_entries.append({
            "exe": exe,
            "app_name": app_name,
            "enabled": True,
        })
        self._blacklist_exe_edit.clear()
        self._blacklist_app_edit.clear()
        self._reload_blacklist_ui(self._blacklist_entries)

    def _release_hotkey_focus(self):
        """清除快捷键按钮的焦点，避免出现主题色边框"""
        for btn in (
            self._hotkey_btn,
            self._writing_hotkey_btn,
            self._selection_translate_hotkey_btn,
            self._ai_chat_hotkey_btn,
        ):
            btn.clearFocus()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _clear_hotkey(self, target: str):
        """清除指定快捷键"""
        if getattr(self, '_capturing_hotkey_target', None) == target:
            self._capturing_hotkey_target = None

        if target == "translator":
            self._hotkey_value = ""
            self._set_hotkey_btn_text(self._hotkey_btn, "")
        elif target == "writing":
            self._writing_hotkey_value = ""
            self._set_hotkey_btn_text(self._writing_hotkey_btn, "")
        elif target == "selection_translate":
            self._selection_translate_hotkey_value = ""
            self._set_hotkey_btn_text(self._selection_translate_hotkey_btn, "")
        elif target == "ai_chat":
            self._ai_chat_hotkey_value = ""
            self._set_hotkey_btn_text(self._ai_chat_hotkey_btn, "")

        # 延迟到事件处理结束后再释放焦点，避免点击 × 后左侧按钮残留高亮
        QTimer.singleShot(0, self._release_hotkey_focus)

    def _start_hotkey_capture(self, target: str):
        """开始捕获快捷键"""
        if target == "translator":
            self._hotkey_btn.setText("请按下快捷键...")
            self._capturing_hotkey_target = "translator"
        elif target == "writing":
            self._writing_hotkey_btn.setText("请按下快捷键...")
            self._capturing_hotkey_target = "writing"
        elif target == "selection_translate":
            self._selection_translate_hotkey_btn.setText("请按下快捷键...")
            self._capturing_hotkey_target = "selection_translate"
        elif target == "ai_chat":
            self._ai_chat_hotkey_btn.setText("请按下快捷键...")
            self._capturing_hotkey_target = "ai_chat"
        # 焦点放在对话框上接收按键，避免快捷键按钮出现主题色边框
        self.setFocus(Qt.FocusReason.OtherFocusReason)

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

            # 冲突检测：与其他功能的快捷键重复时拒绝。
            # 重复组合在 pynput 注册字典中会同 key 覆盖，先设置的功能会静默失效
            _target = self._capturing_hotkey_target
            _all_hotkeys = {
                "translator": (self._hotkey_value, self._hotkey_btn, "唤醒翻译窗口"),
                "writing": (self._writing_hotkey_value, self._writing_hotkey_btn, "划词写作"),
                "selection_translate": (self._selection_translate_hotkey_value,
                                        self._selection_translate_hotkey_btn, "选中翻译"),
                "ai_chat": (self._ai_chat_hotkey_value, self._ai_chat_hotkey_btn, "AI 对话"),
            }
            _dup_label = next(
                (label for name, (val, _b, label) in _all_hotkeys.items()
                 if name != _target and val and val == hotkey),
                None,
            )
            if _dup_label:
                QMessageBox.warning(
                    self, "快捷键冲突",
                    f"「{hotkey}」已被「{_dup_label}」使用，请换一个组合。")
                _orig_value, _orig_btn, _ = _all_hotkeys[_target]
                self._set_hotkey_btn_text(_orig_btn, _orig_value)
                self._capturing_hotkey_target = None
                QTimer.singleShot(0, self._release_hotkey_focus)
                return

            # 更新对应的快捷键
            if self._capturing_hotkey_target == "translator":
                self._hotkey_value = hotkey
                self._set_hotkey_btn_text(self._hotkey_btn, hotkey)
            elif self._capturing_hotkey_target == "writing":
                self._writing_hotkey_value = hotkey
                self._set_hotkey_btn_text(self._writing_hotkey_btn, hotkey)
            elif self._capturing_hotkey_target == "selection_translate":
                self._selection_translate_hotkey_value = hotkey
                self._set_hotkey_btn_text(self._selection_translate_hotkey_btn, hotkey)
            elif self._capturing_hotkey_target == "ai_chat":
                self._ai_chat_hotkey_value = hotkey
                self._set_hotkey_btn_text(self._ai_chat_hotkey_btn, hotkey)

            self._capturing_hotkey_target = None
            QTimer.singleShot(0, self._release_hotkey_focus)
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

    def _title_bar_rect_in_window(self) -> QRect:
        """标题栏在窗口坐标系下的矩形（含 content_layout 上边距，勿用 pos.y()<=28）。"""
        top_left = self._title_bar.mapTo(self, QPoint(0, 0))
        return QRect(top_left, self._title_bar.size())

    def _is_over_title_bar_button(self, pos: QPoint) -> bool:
        """判断鼠标是否在标题栏按钮区域内"""
        if not self._title_bar_rect_in_window().contains(pos):
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
            # 只有在标题栏的非按钮区域才开始拖动
            if self._title_bar_rect_in_window().contains(pos) and not self._is_over_title_bar_button(pos):
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
            # 检查是否在标题栏非按钮区域（显示拖动光标）
            if self._title_bar_rect_in_window().contains(pos) and not self._is_over_title_bar_button(pos):
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

        ld_eng = self._config.get('language_detection.engine', 'local') or 'local'
        _ldi = self._lang_detect_combo.findData(ld_eng)
        _lfallback = self._lang_detect_combo.findData('local')
        self._lang_detect_combo.setCurrentIndex(_ldi if _ldi >= 0 else max(0, _lfallback))

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
        hotkey = self._config.get('hotkey.translator_window', 'Ctrl+O') or ''
        self._hotkey_value = hotkey
        self._set_hotkey_btn_text(self._hotkey_btn, hotkey)

        # 写作快捷键
        writing_hotkey = self._config.get('hotkey.writing', 'Ctrl+I') or ''
        self._writing_hotkey_value = writing_hotkey
        self._set_hotkey_btn_text(self._writing_hotkey_btn, writing_hotkey)

        sel_tr_hotkey = self._config.get('hotkey.selection_translate', 'Ctrl+`') or ''
        self._selection_translate_hotkey_value = sel_tr_hotkey
        self._set_hotkey_btn_text(self._selection_translate_hotkey_btn, sel_tr_hotkey)

        # AI 对话默认快捷键改为 Ctrl+Shift+P：配置仍是旧默认值视为未自定义，自动迁移
        if (self._config.get('hotkey.ai_chat', 'Ctrl+Shift+P') or '') in ('Ctrl+Shift+A', 'Ctrl+U'):
            self._config.set('hotkey.ai_chat', 'Ctrl+Shift+P')
        ai_chat_hotkey = self._config.get('hotkey.ai_chat', 'Ctrl+Shift+P') or ''
        self._ai_chat_hotkey_value = ai_chat_hotkey
        self._set_hotkey_btn_text(self._ai_chat_hotkey_btn, ai_chat_hotkey)

        # 划词触发方式（悬浮工具栏 / 图标按钮）
        trigger_mode = self._config.get('selection.trigger_mode', 'toolbar') or 'toolbar'
        _tmi = self._trigger_mode_combo.findData(trigger_mode)
        self._trigger_mode_combo.setCurrentIndex(_tmi if _tmi >= 0 else 0)

        # AI 对话模型上下文长度
        try:
            ctx_limit = int(self._config.get('chat.model_context_limit', 32768))
        except (TypeError, ValueError):
            ctx_limit = 32768
        self._ctx_limit_spin.setValue(min(max(ctx_limit, 4096), 1048576))

        # AI 对话独立 API 配置
        use_shared = self._config.get('chat.use_shared_api', True)
        self._chat_shared_api_check.setChecked(use_shared)
        self._chat_api_key_edit.setText(self._config.get('chat.api_key', ''))
        self._chat_api_url_edit.setText(self._config.get('chat.base_url', ''))
        self._chat_model_edit.setText(self._config.get('chat.model', ''))
        try:
            chat_timeout = int(self._config.get('chat.timeout', 60))
        except (TypeError, ValueError):
            chat_timeout = 60
        self._chat_timeout_spin.setValue(max(10, min(chat_timeout, 600)))
        self._on_chat_shared_api_toggled(use_shared)

        # actions/ 目录 .py 扩展勾选列表
        _enabled_actions = self._config.get('selection.custom_actions', {}) or {}
        while self._action_checks_layout.count():
            item = self._action_checks_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._action_check_items = []
        try:
            _all_actions = get_custom_action_manager().load_actions()
        except Exception:
            _all_actions = []
        for _action in _all_actions:
            _fname = os.path.basename(_action.file_path)
            _cb = QCheckBox(f"显示 {(_action.icon + ' ' + _action.name).strip()}")
            _cb.setToolTip(_action.file_path)
            _cb.setChecked(bool(_enabled_actions.get(_fname)))
            _cb.toggled.connect(self._on_checkbox_toggled)
            self._action_checks_layout.addWidget(_cb)
            self._action_check_items.append((_fname, _cb))

        # 保留原文选项
        keep_original = self._config.get('writing.keep_original', False)
        self._keep_original_check.setChecked(keep_original)

        # 换行快捷键选项
        newline_hotkey = self._config.get('writing.newline_hotkey', 'enter')
        index = self._newline_hotkey_combo.findText(newline_hotkey)
        if index >= 0:
            self._newline_hotkey_combo.setCurrentIndex(index)

        tts_prov = self._config.get('tts.provider', 'system')
        self._tts_provider_combo.setCurrentIndex(0 if tts_prov != 'edge' else 1)
        self._reload_tts_edge_voice_combo(self._config.get('tts.edge_voice', '') or '')
        rate_val = parse_edge_percent_for_slider(
            self._config.get('tts.edge_rate', '+0%'),
            default=0,
            min_v=EDGE_TTS_RATE_SLIDER_MIN,
            max_v=EDGE_TTS_RATE_SLIDER_MAX,
        )
        self._tts_rate_slider.blockSignals(True)
        self._tts_rate_slider.setValue(rate_val)
        self._tts_rate_slider.blockSignals(False)
        self._on_tts_rate_slider_changed(rate_val)
        vol_val = parse_edge_percent_for_slider(
            self._config.get('tts.edge_volume', '+0%'),
            default=0,
            min_v=EDGE_TTS_VOLUME_SLIDER_MIN,
            max_v=EDGE_TTS_VOLUME_SLIDER_MAX,
        )
        self._tts_volume_slider.blockSignals(True)
        self._tts_volume_slider.setValue(vol_val)
        self._tts_volume_slider.blockSignals(False)
        self._on_tts_volume_slider_changed(vol_val)

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

        # 划词查词选项（应用内 / 应用外分开）
        word_popup_enabled = self._config.get('word_popup.enabled', True)
        self._word_popup_check.setChecked(word_popup_enabled)
        word_popup_global_enabled = self._config.get('word_popup.global_enabled', True)
        self._word_popup_global_check.setChecked(word_popup_global_enabled)

        self._auto_start_check.setChecked(self._config.get('startup.auto_start', False))

        self._disable_update_check.setChecked(
            not self._config.get('updater.enabled', True)
        )

        self._reload_blacklist_ui()

        # 禁用滚轮事件，避免误触
        self._disable_wheel_event(self._popup_style_combo)
        self._disable_wheel_event(self._trigger_mode_combo)
        self._disable_wheel_event(self._lang_detect_combo)
        self._disable_wheel_event(self._font_size_spin)
        self._disable_wheel_event(self._ctx_limit_spin)
        self._disable_wheel_event(self._chat_timeout_spin)

        # 用户填写 API 后自动探测模型上下文窗口并回填（防抖 800ms，后台线程）
        self._ctx_probe_seq = 0
        self._ctx_probe_emitter = _CtxProbeEmitter()
        self._ctx_probe_emitter.done.connect(self._on_context_probed)
        self._ctx_probe_timer = QTimer(self)
        self._ctx_probe_timer.setSingleShot(True)
        self._ctx_probe_timer.setInterval(800)
        self._ctx_probe_timer.timeout.connect(self._probe_context_limit)
        for _ed in (self._api_url_edit, self._api_key_edit, self._model_edit,
                    self._chat_api_url_edit, self._chat_api_key_edit,
                    self._chat_model_edit):
            _ed.textChanged.connect(self._schedule_context_probe)
        self._chat_shared_api_check.toggled.connect(self._schedule_context_probe)
        QTimer.singleShot(600, self._probe_context_limit)  # 按现有配置先探测一次
        self._disable_wheel_event(self._newline_hotkey_combo)
        self._disable_wheel_event(self._tts_provider_combo)
        self._disable_wheel_event(self._tts_edge_voice_combo)
        self._disable_wheel_event(self._tts_rate_slider)
        self._disable_wheel_event(self._tts_volume_slider)

        # 预初始化 ComboBox 下拉视图，避免首次点击卡顿
        self._popup_style_combo.view()
        self._newline_hotkey_combo.view()
        self._lang_detect_combo.view()
        self._tts_provider_combo.view()
        self._tts_edge_voice_combo.view()

        self._update_tts_edge_controls_enabled()

    def _schedule_context_probe(self, *_args):
        """API 相关输入变化后防抖，避免每次按键都发请求"""
        self._ctx_probe_timer.start()

    def _probe_context_limit(self):
        """探测模型最大上下文：优先 /models 端点，查不到退回内置表，回填"""
        if self._chat_shared_api_check.isChecked():
            base = self._api_url_edit.text().strip()
            key = self._api_key_edit.text().strip()
            model = self._model_edit.text().strip()
        else:
            base = self._chat_api_url_edit.text().strip()
            key = self._chat_api_key_edit.text().strip()
            model = self._chat_model_edit.text().strip()
        if not model:
            return
        self._ctx_probe_seq += 1
        seq = self._ctx_probe_seq

        def _work():
            val = probe_context_limit(base, key, model) if base else None
            source = 'api'
            if not val:
                val = guess_context_limit(model)
                source = 'guess'
            self._ctx_probe_emitter.done.emit(seq, int(val or 0), source)

        threading.Thread(target=_work, daemon=True).start()

    def _on_context_probed(self, seq: int, tokens: int, source: str):
        """探测结果回填上下文长度输入框（过期序号丢弃）"""
        if seq != self._ctx_probe_seq or tokens < 4096:
            return
        self._ctx_limit_spin.setValue(min(max(tokens, 4096), 1048576))
        self._ctx_limit_spin.setToolTip(
            "自动回填: " + ("查询 /models 端点获得" if source == 'api'
                                else "端点无上下文字段，按内置已知模型表推断"))

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

    def _tts_combo_voice_id_at(self, row: int) -> str:
        d = self._tts_edge_voice_combo.itemData(row)
        if d is None:
            return ""
        return str(d).strip()

    def _reload_tts_edge_voice_combo(self, configured_voice_id: str):
        combo = self._tts_edge_voice_combo
        cfg = (configured_voice_id or "").strip()
        combo.blockSignals(True)
        combo.clear()
        for label, vid in EDGE_TTS_VOICE_PRESETS:
            combo.addItem(label, vid)
        match_i = -1
        for i in range(combo.count()):
            if self._tts_combo_voice_id_at(i) == cfg:
                match_i = i
                break
        if match_i < 0:
            if cfg:
                combo.insertItem(1, f"自定义 ({cfg})", cfg)
                match_i = 1
            else:
                match_i = 0
        combo.setCurrentIndex(match_i)
        combo.blockSignals(False)

    def _on_tts_rate_slider_changed(self, value: int):
        self._tts_rate_value_label.setText(f"{int(value):+d}%")

    def _on_tts_volume_slider_changed(self, value: int):
        self._tts_volume_value_label.setText(f"{int(value):+d}%")

    def _update_tts_edge_controls_enabled(self):
        edge = self._tts_provider_combo.currentIndex() == 1
        self._tts_edge_voice_combo.setEnabled(edge)
        self._tts_rate_slider.setEnabled(edge)
        self._tts_volume_slider.setEnabled(edge)
        self._tts_rate_value_label.setEnabled(edge)
        self._tts_volume_value_label.setEnabled(edge)

    def _on_chat_shared_api_toggled(self, checked: bool):
        """勾选'与翻译共用 API'时置灰 AI 对话独立 API 字段"""
        if hasattr(self, '_cached_check_icon'):
            cb = self._chat_shared_api_check
            cb.setIcon(self._cached_check_icon if checked else self._cached_uncheck_icon)
        enabled = not checked
        self._chat_api_key_edit.setEnabled(enabled)
        self._chat_api_url_edit.setEnabled(enabled)
        self._chat_model_edit.setEnabled(enabled)
        self._chat_timeout_spin.setEnabled(enabled)
        self._chat_api_test_btn.setEnabled(enabled)

    def _on_test_chat_api(self):
        """测试 AI 对话独立 API 连通性：后台线程发最小请求，
        通过则回填探测到的上下文长度，失败则提示回退共用翻译 API"""
        base = self._chat_api_url_edit.text().strip()
        key = self._chat_api_key_edit.text().strip()
        model = self._chat_model_edit.text().strip()
        if not base or not model:
            QMessageBox.warning(self, "测试失败", "请先填写 Base URL 和 Model。")
            return
        if self._chat_api_test_worker is not None \
                and self._chat_api_test_worker.isRunning():
            return
        self._chat_api_test_btn.setEnabled(False)
        self._chat_api_test_btn.setText("测试中…")
        self._chat_api_test_worker = _ChatApiTestWorker(
            key, base, model, int(self._chat_timeout_spin.value()), self)
        self._chat_api_test_worker.ok.connect(self._on_chat_api_test_ok)
        self._chat_api_test_worker.fail.connect(self._on_chat_api_test_fail)
        self._chat_api_test_worker.finished.connect(self._on_chat_api_test_done)
        self._chat_api_test_worker.start()

    def _on_chat_api_test_ok(self, tokens: int):
        """测试通过：更新最大上下文 token（随设置保存生效）"""
        if tokens >= 4096:
            self._ctx_limit_spin.setValue(min(max(tokens, 4096), 1048576))
            QMessageBox.information(
                self, "测试通过",
                f"API 连接正常，模型上下文长度已更新为 {tokens} tokens。\n"
                f"点击保存后生效。")
        else:
            QMessageBox.information(
                self, "测试通过",
                "API 连接正常。未能自动探测到该模型的上下文长度，\n"
                "将沿用当前上下文长度设置。")

    def _on_chat_api_test_fail(self, error: str):
        """测试不通：提示用户，回退继续用和翻译一样的模型配置"""
        QMessageBox.warning(
            self, "测试失败",
            f"无法连接该 API：\n{error}\n\n"
            f"对话将继续使用与翻译相同的模型配置。")
        # 回退到"与翻译共用 API"（toggled 会自动置灰独立 API 字段）
        self._chat_shared_api_check.setChecked(True)

    def _on_chat_api_test_done(self):
        """测试收尾：恢复按钮文案与启用态"""
        self._chat_api_test_btn.setText("测试连接")
        self._chat_api_test_btn.setEnabled(
            not self._chat_shared_api_check.isChecked())

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

            old_sel_tr_hotkey = self._config.get('hotkey.selection_translate', 'Ctrl+`')
            new_sel_tr_hotkey = self._selection_translate_hotkey_value

            old_ai_chat_hotkey = self._config.get('hotkey.ai_chat', 'Ctrl+Shift+P')
            new_ai_chat_hotkey = self._ai_chat_hotkey_value

            old_blacklist_exes = get_active_blacklist_exes(self._config.get('selection.blacklist'))
            new_blacklist_entries = self._collect_blacklist_entries_from_ui()
            new_blacklist_exes = get_active_blacklist_exes(new_blacklist_entries)

            # API 配置
            self._config.set('translator.base_url', self._api_url_edit.text().strip())
            self._config.set('translator.api_key', self._api_key_edit.text().strip())
            self._config.set('translator.model', self._model_edit.text().strip())
            self._config.set('translator.no_proxy', self._no_proxy_edit.text().strip())
            _lde = self._lang_detect_combo.currentData()
            self._config.set('language_detection.engine', str(_lde or 'local'))

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
            self._config.set('hotkey.selection_translate', new_sel_tr_hotkey)
            self._config.set('hotkey.ai_chat', new_ai_chat_hotkey)
            self._config.set('selection.blacklist', new_blacklist_entries)

            # 划词触发方式（悬浮工具栏 / 图标按钮）
            _trigger_mode = str(self._trigger_mode_combo.currentData() or 'toolbar')
            self._config.set('selection.trigger_mode', _trigger_mode)

            # AI 对话模型上下文长度
            self._config.set('chat.model_context_limit', int(self._ctx_limit_spin.value()))

            # AI 对话独立 API 配置
            self._config.set('chat.use_shared_api', bool(self._chat_shared_api_check.isChecked()))
            self._config.set('chat.api_key', self._chat_api_key_edit.text().strip())
            self._config.set('chat.base_url', self._chat_api_url_edit.text().strip())
            self._config.set('chat.model', self._chat_model_edit.text().strip())
            self._config.set('chat.timeout', int(self._chat_timeout_spin.value()))

            # 工具栏按钮自定义：actions/ 目录 .py 扩展显示开关
            _action_map = {
                _fname: bool(_cb.isChecked())
                for _fname, _cb in getattr(self, '_action_check_items', [])
            }
            self._config.set('selection.custom_actions', _action_map)

            # 写作设置
            keep_original = self._keep_original_check.isChecked()
            self._config.set('writing.keep_original', keep_original)
            self._config.set('writing.newline_hotkey', self._newline_hotkey_combo.currentText())
            self._config.set('writing.animation', self._animation_check.isChecked())

            self._config.set('tts.provider', 'edge' if self._tts_provider_combo.currentIndex() == 1 else 'system')
            _vd = self._tts_edge_voice_combo.currentData()
            _voice = "" if _vd is None else str(_vd).strip()
            self._config.set('tts.edge_voice', _voice)
            self._config.set('tts.edge_rate', edge_percent_from_slider(self._tts_rate_slider.value()))
            self._config.set('tts.edge_volume', edge_percent_from_slider(self._tts_volume_slider.value()))

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

            # 划词查词（应用内 / 应用外分开）
            word_popup_enabled = self._word_popup_check.isChecked()
            self._config.set('word_popup.enabled', word_popup_enabled)
            word_popup_global_enabled = self._word_popup_global_check.isChecked()
            self._config.set('word_popup.global_enabled', word_popup_global_enabled)

            auto_start = self._auto_start_check.isChecked()
            self._config.set('startup.auto_start', auto_start)
            setup_auto_start(auto_start)

            disable_update = self._disable_update_check.isChecked()
            self._config.set('updater.enabled', not disable_update)

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

            if old_sel_tr_hotkey != new_sel_tr_hotkey:
                try:
                    hotkey_manager.update_hotkey(new_sel_tr_hotkey, "selection_translate")
                    log_info(f"选中翻译热键已更新: {old_sel_tr_hotkey} -> {new_sel_tr_hotkey}")
                except Exception as e:
                    log_error(f"更新选中翻译热键失败: {e}")

            if old_ai_chat_hotkey != new_ai_chat_hotkey:
                try:
                    hotkey_manager.update_hotkey(new_ai_chat_hotkey, "ai_chat")
                    log_info(f"AI 对话热键已更新: {old_ai_chat_hotkey} -> {new_ai_chat_hotkey}")
                except Exception as e:
                    log_error(f"更新 AI 对话热键失败: {e}")

            if old_blacklist_exes != new_blacklist_exes:
                try:
                    text_capture = get_text_capture()
                    if text_capture.is_ready():
                        text_capture.update_selection_blacklist(new_blacklist_exes)
                    log_info(f"划词黑名单已更新: {len(old_blacklist_exes)} -> {len(new_blacklist_exes)} 项")
                except Exception as e:
                    log_error(f"更新划词黑名单失败: {e}")

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
        self.hide()
        # 延迟显示 Toast（确保对话框已完全关闭）
        QTimer.singleShot(100, lambda: ToastWidget.show_message(title, message, msg_type))

    def _show_save_success_toast(self):
        """显示保存成功提示（简洁版：只显示绿色\"保存成功\"）"""
        # 先关闭设置对话框
        self.hide()
        # 延迟显示简洁 Toast
        QTimer.singleShot(100, lambda: SimpleToastWidget.show_message("保存成功"))

    # ── 扩展目录快捷入口 ──
    def _open_dir_safe(self, path):
        try:
            from pathlib import Path
            Path(path).mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        except Exception as e:
            log_error(f"打开目录失败: {e}")

    def _on_open_actions_dir(self):
        try:
            self._open_dir_safe(get_custom_action_manager().actions_dir)
        except Exception as e:
            log_error(f"打开 actions 目录失败: {e}")

    def _on_open_skills_dir(self):
        try:
            from .core.skills import get_skill_manager
        except ImportError:
            from src.core.skills import get_skill_manager
        try:
            self._open_dir_safe(get_skill_manager().skills_dir)
        except Exception as e:
            log_error(f"打开 skills 目录失败: {e}")

    def _on_open_mcp_config(self):
        try:
            cfg_path = get_mcp_manager().config_path
            os.startfile(str(cfg_path))
            # 修改配置后需要重连，这里顺便触发一次延迟重连
            QTimer.singleShot(2000, lambda: get_mcp_manager().reconnect())
        except Exception as e:
            log_error(f"打开 MCP 配置失败: {e}")

    def show_window(self):
        """显示设置窗口；如果已打开则复用并唤醒。"""
        self._load_settings()
        if self._applied_theme_signature != self._get_theme_signature():
            self._theme = get_theme()
            self._apply_theme()

        if not self.isVisible():
            self._center_window()

        self.show()
        # 唤醒时刻短暂置前一次
        try:
            from .utils.window_front import bring_to_front_once
        except ImportError:
            from src.utils.window_front import bring_to_front_once
        bring_to_front_once(self)

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
            bg_color = "#007AFF"  # 现代蓝
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


class CustomActionWorker(QThread):
    """自定义工具栏功能的后台执行线程（用户扩展 run(text) 可能耗时）"""

    done = pyqtSignal(object, str, str)   # (action, 选中文本, 结果)
    failed = pyqtSignal(object, str)      # (action, 错误信息)

    def __init__(self, action, text: str):
        super().__init__()
        self._action = action
        self._text = text

    def run(self):
        try:
            result = self._action.run(self._text)
            self.done.emit(self._action, self._text, str(result or ""))
        except Exception as e:
            self.failed.emit(self._action, str(e))


class MainController(QObject):
    """主控制器"""

    writing_completed = pyqtSignal(object)
    initialized = pyqtSignal()

    def __init__(self):
        super().__init__()
        import time as _t; _start = _t.time()
        def _lap(label):
            nonlocal _start
            now = _t.time(); dt = now - _start; _start = now
            _startup_log(f"{label}: {dt*1000:.0f}ms")

        self._config = get_config(); _lap("get_config")
        self._selection_detector = get_selection_detector(); _lap("selection_detector")
        self._translate_button = get_translate_button(); _lap("translate_button")
        self._tray_icon = get_tray_icon(); _lap("tray_icon")
        self._translator = get_translator(); _lap("translator")
        self._text_capture = get_text_capture(); _lap("text_capture")
        self._hotkey_manager = get_hotkey_manager(); _lap("hotkey_manager")
        self._writing_service = get_writing_service(); _lap("writing_service")

        # 划词悬浮工具栏（toolbar 模式下划词时弹出）
        self._selection_toolbar = get_selection_toolbar()
        self._action_worker: Optional[CustomActionWorker] = None

        # MCP 客户端管理器：延迟启动，避免拖慢启动速度
        QTimer.singleShot(3000, self._start_mcp_manager)

        # TextCapture 初始化时会自动启动 selection-hook；若用户上次关闭了划词，立即停掉
        if not self._config.get('selection.enabled', True):
            self._text_capture.stop_selection_hook()
            self._selection_detector.set_enabled(False)

        # 翻译窗口实例
        self._translator_window = get_translator_window()
        self._current_worker = None
        self._last_text: str = ""

        # 系统恢复检测
        self._last_health_check_time = time.time()
        self._session_was_locked = False
        self._system_health_timer = QTimer()
        self._system_health_timer.timeout.connect(self._on_system_health_check)
        self._system_health_timer.start(10000)

        self._connect_signals(); _lap("connect_signals")
        self._check_config(); _lap("check_config")
        self._setup_hotkey(); _lap("setup_hotkey")
        _flush_startup_log()  # 将缓存计时写入日志文件
        try:
            try:
                from .utils.tts_media import ensure_tts_media_bridge
            except ImportError:
                from src.utils.tts_media import ensure_tts_media_bridge
            ensure_tts_media_bridge(); _lap("tts_media_bridge")
        except Exception:
            pass
        except Exception:
            pass

    def _connect_signals(self):
        self._selection_detector.selection_finished.connect(self._on_selection_finished)
        self._translate_button.clicked.connect(self._on_translate_button_clicked)
        self._selection_toolbar.translate_requested.connect(self._on_toolbar_translate)
        self._selection_toolbar.polish_requested.connect(self._on_toolbar_polish)
        self._selection_toolbar.summarize_requested.connect(self._on_toolbar_summarize)
        self._selection_toolbar.chat_requested.connect(self._on_toolbar_chat)
        self._selection_toolbar.action_requested.connect(self._on_toolbar_action)
        self._tray_icon.enabled_changed.connect(self._on_enabled_changed)
        self._tray_icon.settings_requested.connect(self._on_settings_requested)
        self._tray_icon.exit_requested.connect(self._on_exit_requested)
        self._tray_icon.translator_window_requested.connect(self._on_translator_window_requested)
        self._tray_icon.history_requested.connect(self._on_history_requested)
        self._tray_icon.vocabulary_requested.connect(self._on_vocabulary_requested)
        self._tray_icon.chat_requested.connect(self._on_chat_requested)
        self._tray_icon.help_requested.connect(self._on_help_requested)
        # 翻译窗口关闭信号
        self._translator_window.closed.connect(self._on_translator_window_closed)
        self._translator_window.settings_requested.connect(self._on_settings_requested)
        self._hotkey_manager.hotkey_triggered.connect(self._on_hotkey_triggered)
        self._hotkey_manager.writing_hotkey_triggered.connect(self._on_writing_hotkey_triggered)
        self._hotkey_manager.selection_translate_hotkey_triggered.connect(
            self._on_selection_translate_hotkey_triggered
        )
        self._hotkey_manager.ai_chat_hotkey_triggered.connect(self._on_ai_chat_hotkey_triggered)
        self.writing_completed.connect(self._on_writing_completed)
        get_vocabulary_window().open_in_translator.connect(self._on_vocabulary_open_in_translator)

    def _start_mcp_manager(self):
        """延迟启动 MCP 客户端管理器（后台线程连接已配置的 MCP 服务器）"""
        try:
            get_mcp_manager().start()
        except Exception as e:
            log_error(f"启动 MCP 管理器失败: {e}")

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
        # AI 对话默认快捷键改为 Ctrl+Shift+P：配置仍是旧默认值视为未自定义，自动迁移
        if (self._config.get('hotkey.ai_chat', 'Ctrl+Shift+P') or '') in ('Ctrl+Shift+A', 'Ctrl+U'):
            self._config.set('hotkey.ai_chat', 'Ctrl+Shift+P')
        hotkey = self._config.get('hotkey.translator_window', 'Ctrl+O') or ''
        if hotkey.strip():
            success1 = self._hotkey_manager.register_hotkey(hotkey, name="translator_window")
            log_debug(f"注册翻译窗口热键: {hotkey}, 结果: {success1}")
        else:
            self._hotkey_manager.unregister_hotkey("translator_window")
            success1 = True
            log_debug("翻译窗口热键未设置，已跳过注册")

        writing_hotkey = self._config.get('hotkey.writing', 'Ctrl+I') or ''
        if writing_hotkey.strip():
            success2 = self._hotkey_manager.register_hotkey(writing_hotkey, name="writing")
            log_debug(f"注册写作热键: {writing_hotkey}, 结果: {success2}")
        else:
            self._hotkey_manager.unregister_hotkey("writing")
            success2 = True
            log_debug("写作热键未设置，已跳过注册")

        sel_tr_hotkey = self._config.get('hotkey.selection_translate', 'Ctrl+`') or ''
        if sel_tr_hotkey.strip():
            success3 = self._hotkey_manager.register_hotkey(sel_tr_hotkey, name="selection_translate")
            log_debug(f"注册选中翻译热键: {sel_tr_hotkey}, 结果: {success3}")
        else:
            self._hotkey_manager.unregister_hotkey("selection_translate")
            success3 = True
            log_debug("选中翻译热键未设置，已跳过注册")

        ai_chat_hotkey = self._config.get('hotkey.ai_chat', 'Ctrl+Shift+P') or ''
        if ai_chat_hotkey.strip():
            success4 = self._hotkey_manager.register_hotkey(ai_chat_hotkey, name="ai_chat")
            log_debug(f"注册 AI 对话热键: {ai_chat_hotkey}, 结果: {success4}")
        else:
            self._hotkey_manager.unregister_hotkey("ai_chat")
            success4 = True
            log_debug("AI 对话热键未设置，已跳过注册")

        if not success1 or not success2 or not success3 or not success4:
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
        import threading
        import sys as _sys

        _all_start = time.time()
        def _lap(label):
            nonlocal _all_start
            now = time.time(); dt = now - _all_start; _all_start = now
            _startup_log(f"pre_render:{label}: {dt*1000:.0f}ms")

        # 两阶段完成标记：pre_render / warmup
        self._ready_flags = {'pre_render': False, 'warmup': False}

        try:
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
            _lap("history_window")

            # 帮助窗口（懒加载单例，此处触发创建）
            try:
                from .ui.help_window import get_help_window
            except ImportError:
                from src.ui.help_window import get_help_window
            try:
                windows_to_prerender.append(get_help_window())
            except Exception as e:
                log_error(f"预创建帮助窗口失败: {e}")
            _lap("help_window")

            # 设置对话框
            try:
                windows_to_prerender.append(get_settings_dialog())
            except Exception as e:
                log_error(f"预创建设置对话框失败: {e}")
            _lap("settings_dialog")

            try:
                windows_to_prerender.append(get_vocabulary_window())
            except Exception as e:
                log_error(f"预创建单词收藏窗口失败: {e}")
            _lap("vocabulary_window")

            # 离屏预渲染
            offscreen_pos = QPoint(-9999, -9999)
            for widget in windows_to_prerender:
                try:
                    original_pos = widget.pos()
                    if widget is self._translator_window:
                        try:
                            widget._splitter.setStretchFactor(0, 0)
                            widget._splitter.setStretchFactor(1, 1)
                            if widget._fixed_height_mode:
                                widget._splitter.setSizes([180, 360])
                            else:
                                widget._splitter.setSizes([120, 180])
                        except Exception:
                            pass
                    widget.move(offscreen_pos)
                    widget.show()
                    QApplication.processEvents()
                    widget.hide()
                    widget.move(original_pos)
                except Exception as e:
                    log_error(f"预渲染窗口失败: {type(widget).__name__}: {e}")
            _lap(f"offscreen_render ({len(windows_to_prerender)} windows)")

            log_info("窗口预渲染完成")

            # 预热翻译器（后台线程，不阻塞启动）
            threading.Thread(target=self._warmup_translator_in_thread, daemon=True).start()
            _lap("start_warmup_thread")
        finally:
            self._ready_flags['pre_render'] = True

        # pre_render 完成即发射 initialized（warmup 后台继续）
        print("[Startup] pre_render done, emitting initialized", file=sys.stderr, flush=True)
        self.initialized.emit()

    def _warmup_translator_in_thread(self):
        """后台线程：预热语言检测 + API 连接"""
        _w = time.time()
        try:
            try:
                try:
                    from .utils.language_detector import detect_language
                except ImportError:
                    from src.utils.language_detector import detect_language
                detect_language("Hello")
                _dt = (time.time() - _w) * 1000
                _startup_log(f"warmup:lang_detect: {_dt:.0f}ms")
                log_info("语言检测预热完成")
            except Exception as e:
                _startup_log(f"warmup:lang_detect failed: {e}")
            try:
                if self._translator and self._translator._client:
                    _w2 = time.time()
                    self._translator._client.chat.completions.create(
                        model=self._translator._model,
                        messages=[
                            {"role": "system", "content": "You are a connection warmup probe."},
                            {"role": "user", "content": "ping"},
                        ],
                        temperature=0,
                        max_tokens=1,
                        timeout=2,
                    )
                    _dt2 = (time.time() - _w2) * 1000
                    _startup_log(f"warmup:api_ping: {_dt2:.0f}ms")
                    log_info("API连接预热完成")
                else:
                    _startup_log("warmup:api_ping skipped (no client)")
            except Exception as e:
                log_info(f"API连接预热失败: {e}")
        finally:
            self._ready_flags['warmup'] = True

    def _check_all_ready(self):
        """检查所有预热是否完成，完成后发射 initialized 信号"""
        if all(self._ready_flags.values()):
            self._check_ready_timer.stop()
            self.initialized.emit()

    def start(self):
        selection_enabled = self._config.get('selection.enabled', True)
        self._selection_detector.set_enabled(selection_enabled)
        self._selection_detector.start()
        if not selection_enabled:
            self._text_capture.stop_selection_hook()
        self._tray_icon.show()
        log_info(f"{APP_NAME} 已启动（划词{'已启用' if selection_enabled else '已禁用'}）")
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
        self._selection_toolbar.hide_toolbar()
        # 隐藏翻译窗口
        self._translator_window.hide()
        self._tray_icon.hide()
        self._tray_icon.cleanup()
        self._text_capture.cleanup()

        # 关闭 MCP 客户端（断开子进程连接）
        try:
            get_mcp_manager().shutdown()
        except Exception:
            pass

        # 确保历史记录保存到磁盘
        try:
            from .utils.history import get_history
        except ImportError:
            from src.utils.history import get_history
        try:
            get_history().flush()
        except Exception:
            pass
        try:
            from .utils.vocabulary import get_vocabulary
        except ImportError:
            from src.utils.vocabulary import get_vocabulary
        try:
            get_vocabulary().flush()
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

    def _on_selection_translate_hotkey_triggered(self):
        """选中内容翻译热键：主动取当前选区并打开翻译（适合 Excel / PowerPoint 等）。

        取词优先级：UIA → selection-hook（仅启用划词时）→ 剪贴板模拟 Ctrl+C。
        「启用划词」关闭时仍可用 UIA 与剪贴板路径，仅跳过 selection-hook。
        """
        log_debug("选中翻译热键触发")

        cursor_pos = QCursor.pos()
        mouse_pos = (cursor_pos.x(), cursor_pos.y())

        try:
            import keyboard
            import pyperclip

            self._wait_for_modifier_release(keyboard)

            saved_clipboard = ""
            try:
                saved_clipboard = pyperclip.paste()
            except Exception:
                pass

            current_selection = self._text_capture.get_selected_text_direct()
            text = (current_selection.text or "").strip()
            log_debug(
                f"选中翻译: method={current_selection.method}, "
                f"len={len(text)}"
            )

            if not text and self._tray_icon._is_enabled:
                hook_sel = self._text_capture.get_current_selection(timeout=0.65)
                text = (hook_sel.text or "").strip()
                if text:
                    log_debug(
                        f"选中翻译: selection-hook 查询 method={hook_sel.method}, "
                        f"error={hook_sel.error}"
                    )
            elif not text:
                log_debug("划词未启用，跳过 selection-hook 取词")

            editor_selection_state = self._get_foreground_editor_selection_state()
            if not text and editor_selection_state is not False:
                text = (
                    self._probe_selected_text_by_clipboard(
                        keyboard, pyperclip, saved_clipboard
                    )
                    or ""
                ).strip()

            self._translate_button.hide()
            self._selection_toolbar.hide_toolbar()

            if not text:
                self._tray_icon.show_message(
                    APP_NAME,
                    "未能获取选中内容，可先复制后再试或检查焦点是否在编辑区域",
                    "warning",
                )
                return

            if (
                text == self._last_text
                and self._translator_window.isVisible()
                and self._translator_window.is_auto_mode()
            ):
                self._translator_window.bring_to_front()
                return

            self._last_text = text
            self._translator_window.show_at_mouse(mouse_pos, self._last_text)
        except Exception as e:
            log_error(f"选中翻译热键处理失败: {e}")

    def _on_writing_hotkey_triggered(self):
        """写作热键触发时执行写作功能

        获取文本的方式（优先级从高到低）：
        1. 使用 selection-hook.getCurrentSelection() 主动查询当前真实选区
        2. 如果没有选中，则使用 ctrl+a + ctrl+a + ctrl+c 获取全文

        这样避免 Notepad++、VS Code、JetBrains 等编辑器在无选区时
        Ctrl+C 复制当前行/当前段，导致误判为用户选中了文本。
        """
        log_debug("写作热键触发")
        log_info(f"[写作诊断] 热键触发，前台窗口: {self._get_foreground_window_snapshot()}")

        # 检查是否已在写作中
        if self._writing_service.is_writing:
            log_debug("写作正在进行中，跳过")
            return

        try:
            import keyboard
            import pyperclip

            # 等待用户松开触发热键时按住的 Ctrl/Shift，避免后续模拟 Ctrl+C 退化成普通 c。
            self._wait_for_modifier_release(keyboard)

            # 保存当前剪贴板内容
            saved_clipboard = ""
            try:
                saved_clipboard = pyperclip.paste()
            except Exception:
                pass
            log_info(f"[写作诊断] 触发前剪贴板: {self._format_text_snapshot(saved_clipboard)}")

            current_selection = self._text_capture.get_selected_text_direct()
            selected_text = current_selection.text or ""
            log_info(f"[写作诊断] 选区查询: method={current_selection.method}, "
                     f"error={current_selection.error}, "
                     f"{self._format_text_snapshot(selected_text)}")
            editor_selection_state = self._get_foreground_editor_selection_state()
            log_info(f"[写作诊断] 前台编辑控件选区状态: {editor_selection_state}")

            has_current_selection = False
            if editor_selection_state is False:
                log_info("[写作诊断] 前台编辑控件确认无选区，按无选区处理")
            elif editor_selection_state is True:
                has_current_selection = bool(selected_text and selected_text.strip())
            else:
                # Scintilla/UIA 都是非剪贴板的真实选区查询，不会触发“复制当前行”。
                has_current_selection = bool(selected_text and selected_text.strip())

            if has_current_selection:
                log_info(f"检测到当前选中文本: {self._format_text_snapshot(selected_text)}")
                self._start_writing(selected_text, has_selection=True)
                return

            if editor_selection_state is not False:
                clipboard_selection = self._probe_selected_text_by_clipboard(
                    keyboard,
                    pyperclip,
                    saved_clipboard,
                )
                if clipboard_selection and clipboard_selection.strip():
                    log_info(f"通过剪贴板探测到选中文本: "
                             f"{self._format_text_snapshot(clipboard_selection)}")
                    self._start_writing(clipboard_selection, has_selection=True)
                    return

            # 没有选中内容，恢复剪贴板并获取全文
            log_info("[写作诊断] 当前无选中文本，进入全文获取流程")
            try:
                pyperclip.copy(saved_clipboard)
            except Exception:
                pass
            self._get_all_text_for_writing_async()

        except Exception as e:
            log_error(f"写作热键处理失败: {e}")

    def _probe_selected_text_by_clipboard(self, keyboard_module, pyperclip_module,
                                          saved_clipboard: str) -> str:
        """用剪贴板探测当前选区，并立即恢复剪贴板。"""
        try:
            import uuid

            marker = f"__QTRANSLATOR_NO_SELECTION_{uuid.uuid4().hex}__"
            pyperclip_module.copy(marker)
            time.sleep(0.03)

            self._send_hotkey_safely(keyboard_module, 'ctrl+c')
            time.sleep(0.12)

            copied_text = pyperclip_module.paste()
            log_info(f"[写作诊断] 剪贴板选区探测: "
                     f"is_marker={copied_text == marker}, "
                     f"{self._format_text_snapshot(copied_text)}")

            if saved_clipboard is not None:
                try:
                    pyperclip_module.copy(saved_clipboard)
                except Exception:
                    pass

            if copied_text and copied_text != marker:
                return copied_text
        except Exception as e:
            log_debug(f"剪贴板选区探测失败: {e}")
            try:
                if saved_clipboard is not None:
                    pyperclip_module.copy(saved_clipboard)
            except Exception:
                pass

        return ""

    def _get_recent_selection_snapshot(self, max_age: float = 10.0) -> dict:
        """获取近期 selection-hook 选区摘要，用于验证 Ctrl+C 是否真的复制了选区。"""
        snapshot = {
            'text': '',
            'program': '',
            'age': float('inf'),
            'is_recent': False,
        }

        try:
            capture_time = self._text_capture.get_last_capture_time()
            if capture_time <= 0:
                return snapshot

            age = time.time() - capture_time
            text = capture_text_direct()
            try:
                from .core.text_capture import get_last_program_name
            except ImportError:
                from src.core.text_capture import get_last_program_name

            snapshot.update({
                'text': text or '',
                'program': get_last_program_name() or '',
                'age': age,
                'is_recent': age <= max_age,
            })
        except Exception:
            pass

        return snapshot

    def _matches_recent_selection(self, clipboard_text: str, selection_snapshot: dict) -> bool:
        """判断 Ctrl+C 内容是否与近期真实划词选区一致。"""
        if not selection_snapshot.get('is_recent'):
            return False

        selection_text = selection_snapshot.get('text') or ''
        if not clipboard_text or not selection_text:
            return False

        def normalize(value: str) -> str:
            return value.replace('\r\n', '\n').replace('\r', '\n').strip()

        return normalize(clipboard_text) == normalize(selection_text)

    def _get_foreground_editor_selection_state(self):
        """读取前台编辑控件是否有选区。

        返回 True/False 表示已确认有/无选区；返回 None 表示当前控件不支持直接读取。
        目前覆盖 Notepad++ 等基于 Scintilla 的编辑器，用来避开无选区 Ctrl+C 复制当前行。
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None

            thread_id = user32.GetWindowThreadProcessId(hwnd, None)

            class GUITHREADINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND),
                    ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND),
                    ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND),
                    ("hwndCaret", wintypes.HWND),
                    ("rcCaret", wintypes.RECT),
                ]

            gui_info = GUITHREADINFO()
            gui_info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui_info)):
                return None

            focus_hwnd = gui_info.hwndFocus
            if not focus_hwnd:
                return None

            class_name_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(focus_hwnd, class_name_buffer, 256)
            class_name = class_name_buffer.value

            if class_name == 'Scintilla':
                SCI_GETSELECTIONSTART = 2143
                SCI_GETSELECTIONEND = 2145
                start = user32.SendMessageW(focus_hwnd, SCI_GETSELECTIONSTART, 0, 0)
                end = user32.SendMessageW(focus_hwnd, SCI_GETSELECTIONEND, 0, 0)
                return start != end

            if (class_name == 'Edit'
                    or class_name.startswith('RichEdit')
                    or class_name.startswith('RICHEDIT')
                    or 'EDIT' in class_name.upper()):
                EM_GETSEL = 0x00B0
                start = wintypes.DWORD()
                end = wintypes.DWORD()
                user32.SendMessageW(
                    focus_hwnd,
                    EM_GETSEL,
                    ctypes.byref(start),
                    ctypes.byref(end),
                )
                return start.value != end.value

            return None
        except Exception as e:
            log_debug(f"读取前台编辑控件选区状态失败: {e}")
            return None

    def _format_text_snapshot(self, text: str, limit: int = 80) -> str:
        """格式化文本诊断信息，避免日志里输出大段正文。"""
        if text is None:
            return "text=None"

        normalized = text.replace('\r\n', '\n').replace('\r', '\n')
        preview = normalized.replace('\n', '\\n')
        head = preview[:limit]
        tail = preview[-limit:] if len(preview) > limit else preview
        return (f"len={len(text)}, stripped_len={len(text.strip())}, "
                f"lines={normalized.count(chr(10)) + 1 if normalized else 0}, "
                f"head='{head}', tail='{tail}'")

    def _get_foreground_window_snapshot(self) -> str:
        """获取前台窗口摘要，辅助分析不同编辑器的快捷键行为。"""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return "hwnd=0"

            title_buffer = ctypes.create_unicode_buffer(256)
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title_buffer, 256)
            user32.GetClassNameW(hwnd, class_buffer, 256)

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return (f"hwnd={hwnd}, pid={pid.value}, "
                    f"class='{class_buffer.value}', title='{title_buffer.value[:120]}'")
        except Exception as e:
            return f"unknown ({e})"

    def _wait_for_modifier_release(self, keyboard_module, timeout: float = 0.8):
        """等待真实修饰键释放，避免物理松键事件打断模拟组合键。"""
        modifiers = ('ctrl', 'shift', 'alt')
        start = time.time()
        while time.time() - start < timeout:
            try:
                if not any(keyboard_module.is_pressed(key) for key in modifiers):
                    break
            except Exception:
                break
            time.sleep(0.02)

        # 清理 keyboard 库可能保留的模拟状态；真实按键若还未松开，上面的等待已尽量避开竞态。
        for key in modifiers:
            try:
                keyboard_module.release(key)
            except Exception:
                pass
        time.sleep(0.05)

    def _send_hotkey_safely(self, keyboard_module, hotkey: str):
        """安全发送组合键，优先避免组合键退化成普通字符输入。"""
        self._wait_for_modifier_release(keyboard_module)
        keyboard_module.press_and_release(hotkey)

    def _get_all_text_for_writing_async(self):
        """异步获取全文并开始写作

        通过在 ctrl+a + ctrl+a + ctrl+c 前设置唯一标记到剪贴板，
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

            # 全选并复制。部分网页编辑器第一次 Ctrl+A 只选中当前行/段落，
            # 第二次才会扩展到整个编辑区域。每一步都复制并记录，便于确认编辑器行为。
            self._send_hotkey_safely(keyboard, 'ctrl+a')
            time.sleep(0.08)
            self._send_hotkey_safely(keyboard, 'ctrl+c')
            time.sleep(0.12)
            first_select_text = ""
            try:
                first_select_text = pyperclip.paste()
            except Exception:
                pass
            log_info(f"[写作诊断] 第一次 Ctrl+A 后复制: "
                     f"is_marker={first_select_text == clipboard_marker}, "
                     f"{self._format_text_snapshot(first_select_text)}")

            self._send_hotkey_safely(keyboard, 'ctrl+a')
            time.sleep(0.08)
            self._send_hotkey_safely(keyboard, 'ctrl+c')
            time.sleep(0.12)
            second_select_text = ""
            try:
                second_select_text = pyperclip.paste()
            except Exception:
                pass
            log_info(f"[写作诊断] 第二次 Ctrl+A 后复制: "
                     f"is_marker={second_select_text == clipboard_marker}, "
                     f"{self._format_text_snapshot(second_select_text)}")

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
            log_info(f"[写作诊断] 准备开始全文写作，剪贴板最终内容: "
                     f"is_marker={text == clipboard_marker}, {self._format_text_snapshot(text)}")

            # 检测 ctrl+a + ctrl+a + ctrl+c 是否成功
            # 如果剪贴板仍是标记值，说明目标应用不支持全选或复制失败
            if clipboard_marker and text == clipboard_marker:
                # 取消可能存在的选中状态
                keyboard.release('ctrl')
                keyboard.release('shift')
                time.sleep(0.03)
                keyboard.press_and_release('left')
                self._restore_clipboard(saved_clipboard)
                return

            log_info(f"全文内容: {self._format_text_snapshot(text)}")

            if text and text.strip():
                keyboard.release('ctrl')
                keyboard.release('shift')

                # 立即恢复剪贴板（不用定时器，避免与写作线程的剪贴板操作竞态）
                self._restore_clipboard(saved_clipboard)

                # 当前全文仍保持选中，直接按选区替换，避免写入阶段再次 Ctrl+A 只选中当前行。
                self._start_writing(text, has_selection=True)
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
            # writing_command 的 on_complete 在后台线程中触发，UI 交给 Qt 信号回到主线程处理。
            self.writing_completed.emit(result)

        self._writing_service.writing_command(
            text,
            has_selection=has_selection,
            keep_original=keep_original,
            on_complete=on_complete
        )

    def _on_writing_completed(self, result: WritingResult):
        """写作完成回调（运行在 Qt 主线程）。"""
        if result.error:
            ToastWidget.show_message("写作失败", result.error, "error")
        else:
            SimpleToastWidget.show_message("写作完成")
            log_info(f"写作完成: {result.source_language} -> {result.target_language}")

    def _on_selection_finished(self):
        """划词选择完成 - 根据设置显示悬浮工具栏或翻译图标按钮"""
        if not self._tray_icon._is_enabled:
            return

        text = capture_text_direct()
        try:
            from .core.text_capture import get_last_program_name
            program_name = get_last_program_name()
        except ImportError:
            from src.core.text_capture import get_last_program_name
            program_name = get_last_program_name()

        trigger_mode = self._config.get('selection.trigger_mode', 'toolbar')

        if not text or not text.strip():
            self._translate_button.hide()
            self._selection_toolbar.hide_toolbar()
            return

        # 获取鼠标位置
        mouse_pos = self._selection_detector.get_last_position()

        if mouse_pos is None:
            # 别名导入：避免遮蔽模块级 QCursor（下方查词分支使用全局 QCursor）
            from PyQt6.QtGui import QCursor as _QCursorFallback
            cursor = _QCursorFallback.pos()
            mouse_pos = (cursor.x(), cursor.y())

        selected_text = text.strip()

        # 查词优先：单个英文单词直接弹释义弹窗（与翻译窗口内划词查词一致），
        # 不再弹工具栏/图标按钮；由设置「启用划词查词（应用外）」开关控制。
        # 锚点取实时鼠标位置（mouse_pos 是选区包围盒左上角，可能离鼠标很远），
        # 卡片出现在鼠标右下角
        if self._config.get('word_popup.global_enabled', True) \
                and is_english_word(selected_text):
            self._translate_button.hide()
            self._selection_toolbar.hide_toolbar()
            show_word_popup(selected_text, QCursor.pos(), None)
            return

        if trigger_mode == 'toolbar':
            # 悬浮工具栏模式（豆包 / Cherry Studio 风格）
            self._translate_button.hide()
            self._selection_toolbar.set_selected_text(selected_text)
            self._selection_toolbar.show_at_position(mouse_pos, selected_text)
            return

        # 图标按钮模式（原有行为）
        self._selection_toolbar.hide_toolbar()
        # 保存选中文本到翻译按钮（不更新 _last_text，它只记录最后一次发起翻译的文本）
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

    # ── 划词悬浮工具栏信号处理 ──
    def _toolbar_current_text(self) -> str:
        return (self._selection_toolbar.get_selected_text() or "").strip()

    def _on_toolbar_translate(self):
        """工具栏「翻译」- 与图标按钮点击行为一致"""
        text = self._toolbar_current_text()
        if not text:
            return
        if text == self._last_text and self._translator_window.isVisible() and self._translator_window.is_auto_mode():
            return
        self._last_text = text
        cursor_pos = QCursor.pos()
        self._translator_window.show_at_mouse((cursor_pos.x(), cursor_pos.y()), text)

    def _on_toolbar_polish(self):
        """工具栏「润色」- 翻译窗口润色模式"""
        self._toolbar_run_function('polishing')

    def _on_toolbar_summarize(self):
        """工具栏「总结」- 翻译窗口总结模式"""
        self._toolbar_run_function('summarize')

    def _toolbar_run_function(self, function: str):
        text = self._toolbar_current_text()
        if not text:
            return
        self._last_text = text
        cursor_pos = QCursor.pos()
        self._translator_window.show_at_mouse_with_function(
            (cursor_pos.x(), cursor_pos.y()), text, function
        )

    def _on_toolbar_chat(self, text: str):
        """工具栏「AI对话」- 打开独立对话窗口并预填选中文本"""
        self._translate_button.hide()
        get_chat_window().show_with_text(text or self._toolbar_current_text())

    def _on_toolbar_action(self, action):
        """工具栏自定义功能 - 后台执行用户扩展 run(text)，结果展示在 AI 对话窗口"""
        if self._action_worker and self._action_worker.isRunning():
            ToastWidget.show_message("自定义功能", "上一个功能还在执行中", "info")
            return
        text = self._toolbar_current_text()
        self._action_worker = CustomActionWorker(action, text)
        self._action_worker.done.connect(self._on_action_done)
        self._action_worker.failed.connect(self._on_action_failed)
        self._action_worker.start()

    def _on_action_done(self, action, selected_text: str, result: str):
        get_chat_window().append_action_result(action.name, selected_text, result)
        if not result:
            SimpleToastWidget.show_message(f"{action.name} 已执行")

    def _on_action_failed(self, action, error: str):
        log_error(f"自定义功能 {action.name} 执行失败: {error}")
        ToastWidget.show_message("执行失败", f"{action.name}: {error}", "error")

    def _on_translator_window_closed(self):
        """翻译窗口关闭"""
        self._last_text = ""

    def _on_enabled_changed(self, enabled: bool):
        # 关闭划词时停止 selection-hook 子进程与划词图标检测；快捷键仍可用 UIA/剪贴板取词。
        if enabled:
            self._text_capture.start_selection_hook()
            self._selection_detector.set_enabled(True)
            self._tray_icon.show_message(APP_NAME, "划词监听已启用", "info")
        else:
            self._selection_detector.set_enabled(False)
            self._translate_button.hide()
            self._selection_toolbar.hide_toolbar()
            self._text_capture.stop_selection_hook()
            self._tray_icon.show_message(APP_NAME, "划词监听已禁用", "info")

    def _on_settings_requested(self):
        dialog = get_settings_dialog()
        dialog.show_window()

    def _on_translator_window_requested(self):
        """双击托盘或点击菜单显示翻译窗口"""
        # 先隐藏划词翻译相关窗口
        self._translate_button.hide()
        self._selection_toolbar.hide_toolbar()
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
        self._selection_toolbar.hide_toolbar()
        self._last_text = ""

        # 显示历史窗口
        history_window = get_history_window()
        history_window.show_window()

    def _on_vocabulary_requested(self):
        self._translate_button.hide()
        self._selection_toolbar.hide_toolbar()
        get_vocabulary_window().show_window()

    def _on_chat_requested(self):
        """托盘菜单打开 AI 对话窗口"""
        self._translate_button.hide()
        self._selection_toolbar.hide_toolbar()
        get_chat_window().show_window()

    def _on_ai_chat_hotkey_triggered(self):
        """AI 对话快捷键：唤起/置顶 AI 对话窗口"""
        self._translate_button.hide()
        self._selection_toolbar.hide_toolbar()
        get_chat_window().show_window()

    def _on_vocabulary_open_in_translator(self, word: str, translation: str):
        self._translate_button.hide()
        self._selection_toolbar.hide_toolbar()
        self._translator_window.load_translation_pair(word, translation)
        self._translator_window.show_window()

    def _on_help_requested(self):
        """显示帮助窗口"""
        self._translate_button.hide()
        self._selection_toolbar.hide_toolbar()

        # 显示帮助窗口
        help_window = get_help_window()
        help_window.show_window()

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

    def release(self):
        """释放实例锁"""
        if self._mutex:
            try:
                import ctypes
                ctypes.windll.kernel32.ReleaseMutex(self._mutex)
                ctypes.windll.kernel32.CloseHandle(self._mutex)
            except Exception:
                pass
            self._mutex = None


class TranslatorApp(QApplication):
    """QApplication 子类：为所有 widget 开启非激活窗口 tooltip 显示。

    Qt 6 默认只在激活窗口显示 tooltip（Qt 5 的 AA_AlwaysShowToolTips 已移除），
    而 QTranslator 常与其他应用并排使用（划词/对照场景），非激活窗口也需弹提示。
    Qt 6 保留的 WA_AlwaysShowToolTips 是 widget 级属性，在 Show 事件时设置，
    覆盖所有窗口与子控件。"""

    def notify(self, receiver, event):
        if event.type() == QEvent.Type.Show and isinstance(receiver, QWidget):
            try:
                receiver.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
            except Exception:
                pass
            if receiver.objectName() == "qtooltip_label":
                # tooltip 是应用级共享单例，样式缓存不随窗口样式表更新而失效：
                # 强制重解析（字体/颜色/padding 全部按当前 QSS 生效）后按最终
                # 样式重算尺寸，首帧即最终大小。resize 与 Qt updateSize 同样
                # 加 +1px extra，并限制不超过屏幕可用宽（与 Qt 换行逻辑一致）。
                try:
                    receiver.style().unpolish(receiver)
                    receiver.style().polish(receiver)
                    _new_size = receiver.sizeHint() + QSize(1, 0)
                    _avail = QGuiApplication.primaryScreen().availableGeometry()
                    if _new_size.width() <= _avail.width():
                        receiver.resize(_new_size)
                except Exception:
                    pass
        return super().notify(receiver, event)


def main():
    """主入口。"""
    _startup_timing('main() 入口')

    # Windows 任务栏图标：必须在 QApplication 创建前设 AppUserModelID，
    # 否则进程任务栏图标用 python.exe 默认图标而非应用图标
    if sys.platform.startswith('win'):
        try:
            import ctypes
            try:
                from .config import APP_ID
            except ImportError:
                from src.config import APP_ID
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    app = TranslatorApp(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Tooltip 原生字体与各窗口 QSS 的 font-size: 12px 对齐：
    # 首次显示的 tooltip 在 QSS 生效前按 QApplication 默认字体定尺寸，
    # 系统字体偏大时首显会明显偏大；统一 12px 让首显即最终大小
    try:
        _tip_font = QFont(app.font())
        _tip_font.setPointSizeF(-1.0)
        _tip_font.setPixelSize(12)
        QToolTip.setFont(_tip_font)
    except Exception:
        pass

    # Tooltip 全局 palette 与初始主题对齐：QSS 失效（如系统深色模式）
    # 时 tooltip 也不会黑底白字，始终跟随应用主题
    try:
        from .utils.theme import refresh_tooltip_style
    except ImportError:
        from src.utils.theme import refresh_tooltip_style
    refresh_tooltip_style()

    splash = SplashScreen()
    splash.show_splash()
    app.processEvents()

    # 开机自启自愈：exe 被替换/移动后，把注册表自启路径重写为当前路径
    sync_auto_start_path()

    try:
        from .config import APP_ID, APP_NAME
    except ImportError:
        from src.config import APP_ID, APP_NAME
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    icon_path = Path(__file__).parent.parent / "assets" / "icon.png"
    if icon_path.exists():
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))

    # ── 单实例检查 ──
    single_instance = SingleInstance(APP_ID)
    if not single_instance.try_lock():
        splash.close()
        QMessageBox.warning(None, APP_NAME,
            f"{APP_NAME} 已经在运行中！\n\n请在系统托盘查找已有实例。",
            QMessageBox.StandardButton.Ok)
        sys.exit(0)

    # ── 创建主控制器（splash 持续动画）──
    controller = MainController()

    # ── 初始化完成 → 直接关闭 splash 显示翻译窗口 ──
    def on_initialized():
        print("[Startup] initialized, closing splash", file=sys.stderr, flush=True)
        _startup_timing('初始化完成，翻译窗口即将显示')
        splash.close()
        splash.deleteLater()
        controller._on_translator_window_requested()

    controller.initialized.connect(on_initialized)
    controller.start()

    try:
        get_logger().clear_old_logs(days=7)
    except Exception:
        pass

    exit_code = app.exec()
    if controller:
        controller.stop()
    single_instance.release()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()