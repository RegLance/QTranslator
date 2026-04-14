"""翻译图标按钮组件 - QTranslator

优化：解决与网站原生悬浮窗冲突的问题
- 浏览器环境下延迟显示，等待网站悬浮窗消失
- 非浏览器环境立即显示

Windows 平台使用纯 Win32 API 创建窗口（消除 Windows 11 DWM 阴影），
其他平台使用 Qt QWidget。
"""
import sys
import math
from typing import Optional, Tuple
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

try:
    from ..config import get_config
    from ..core.text_capture import is_browser_program
except ImportError:
    from src.config import get_config
    from src.core.text_capture import is_browser_program


# 按钮尺寸（18px）
BUTTON_SIZE = 18

# 鼠标离开按钮多少像素后自动隐藏（使用逻辑坐标）
HIDE_DISTANCE_THRESHOLD = 50

# 浏览器环境下延迟显示时间（毫秒）- 等待网站原生悬浮窗消失
DEFAULT_BROWSER_DELAY_MS = 450


# ============================================================================
# Windows 平台：纯 Win32 API 实现（消除 Windows 11 DWM 阴影）
# ============================================================================
if sys.platform == 'win32':
    import ctypes
    from PyQt6.QtCore import QObject

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _gdi32 = ctypes.windll.gdi32

    # Win32 常量
    _WS_POPUP = 0x80000000
    _WS_VISIBLE = 0x10000000
    _WS_CLIPSIBLINGS = 0x04000000
    _WS_EX_TOPMOST = 0x00000008
    _WS_EX_NOACTIVATE = 0x08000000
    _WS_EX_NOREDIRECTIONBITMAP = 0x00200000

    _WM_PAINT = 0x000F
    _WM_LBUTTONDOWN = 0x0201
    _WM_ERASEBKGND = 0x0014
    _WM_DESTROY = 0x0002
    _WM_SHOWWINDOW = 0x0018

    _SW_HIDE = 0
    _SW_SHOWNOACTIVATE = 4

    _SWP_NOMOVE = 0x0002
    _SWP_NOSIZE = 0x0001
    _SWP_NOZORDER = 0x0004
    _SWP_NOACTIVATE = 0x0010
    _SWP_FRAMECHANGED = 0x0020

    # WNDPROC 回调类型：LRESULT CALLBACK WndProc(HWND, UINT, WPARAM, LPARAM)
    # 在 64 位 Windows 上，所有参数都是 8 字节
    _WNDPROC = ctypes.CFUNCTYPE(
        ctypes.c_int64,      # LRESULT (64-bit)
        ctypes.c_void_p,     # HWND
        ctypes.c_uint,       # UINT
        ctypes.c_uint64,     # WPARAM (64-bit)
        ctypes.c_int64       # LPARAM (64-bit, signed)
    )

    # WNDCLASSEXW 结构体
    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("style", ctypes.c_uint),
            ("lpfnWndProc", _WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", ctypes.c_void_p),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", ctypes.c_wchar_p),
            ("lpszClassName", ctypes.c_wchar_p),
            ("hIconSm", ctypes.c_void_p),
        ]

    # 模块级窗口类注册（只注册一次）
    _window_class_registered = False
    _wndproc_ref = None  # 防止回调被垃圾回收

    def _register_window_class(wndproc):
        global _window_class_registered, _wndproc_ref
        if _window_class_registered:
            return
        _wndproc_ref = wndproc
        hInstance = _kernel32.GetModuleHandleW(None)
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = wndproc
        wc.hInstance = hInstance
        wc.hCursor = _user32.LoadCursorW(None, ctypes.c_void_p(32512))  # IDC_ARROW
        wc.lpszClassName = "QTranslatorBtn"
        _user32.RegisterClassExW(ctypes.byref(wc))
        _window_class_registered = True

    class TranslateButton(QObject):
        """翻译图标按钮（纯 Win32 实现）

        使用 Win32 API 直接创建 WS_POPUP 窗口，
        设置 WS_EX_NOREDIRECTIONBITMAP 阻止 DWM 创建重定向表面，
        从根本上消除 Windows 11 DWM 合成阴影。

        特性：
        - 小巧的圆形图标按钮
        - 跟随选区/鼠标位置显示
        - 浏览器环境下延迟显示，避免与网站悬浮窗冲突
        - 点击触发翻译
        - 鼠标距离按钮一定距离后自动隐藏
        - 无 DWM 阴影
        """

        clicked = pyqtSignal()
        hidden = pyqtSignal()

        def __init__(self):
            super().__init__()

            self._auto_hide_delay = 5000
            self._selected_text: str = ""
            self._is_just_shown: bool = False
            self._visible: bool = False
            self._pos_x: int = -100
            self._pos_y: int = -100

            # 延迟显示相关
            self._show_delay_timer: Optional[QTimer] = None
            self._pending_show_pos: Optional[Tuple[int, int]] = None
            self._pending_text: str = ""

            # 创建原生窗口
            self.hwnd: int = 0
            self._create_native_window()

            # 设置计时器
            self._auto_hide_timer = QTimer()
            self._auto_hide_timer.setSingleShot(True)
            self._auto_hide_timer.timeout.connect(self._on_auto_hide)

            self._mouse_check_timer = QTimer()
            self._mouse_check_timer.setInterval(100)
            self._mouse_check_timer.timeout.connect(self._check_mouse_distance)

            self._show_delay_timer = QTimer()
            self._show_delay_timer.setSingleShot(True)
            self._show_delay_timer.timeout.connect(self._do_delayed_show)

        def _create_native_window(self):
            """创建纯 Win32 弹出窗口"""
            hInstance = _kernel32.GetModuleHandleW(None)

            # 注册窗口类（使用模块级回调，防止 GC）
            _register_window_class(_WNDPROC(self._wndproc_handler))

            # 创建窗口：WS_POPUP + WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_NOREDIRECTIONBITMAP
            # WS_EX_NOREDIRECTIONBITMAP 是关键：阻止 DWM 创建重定向表面，没有阴影
            self.hwnd = _user32.CreateWindowExW(
                _WS_EX_TOPMOST | _WS_EX_NOACTIVATE | _WS_EX_NOREDIRECTIONBITMAP,
                "QTranslatorBtn",
                "",
                _WS_POPUP,
                -100, -100, BUTTON_SIZE, BUTTON_SIZE,
                0, 0, hInstance, 0
            )

            # 设置圆形区域裁剪
            hrgn = _gdi32.CreateEllipticRgn(0, 0, BUTTON_SIZE, BUTTON_SIZE)
            _user32.SetWindowRgn(self.hwnd, hrgn, True)

        def _wndproc_handler(self, hwnd, msg, wparam, lparam):
            """Win32 窗口过程"""
            if msg == _WM_PAINT:
                self._paint(hwnd)
                return 0
            elif msg == _WM_LBUTTONDOWN:
                self.clicked.emit()
                QTimer.singleShot(100, self.hide)
                return 0
            elif msg == _WM_ERASEBKGND:
                return 1  # 防止闪烁

            return ctypes.windll.user32.DefWindowProcW(
                ctypes.c_void_p(hwnd), ctypes.c_uint(msg),
                ctypes.c_uint64(wparam), ctypes.c_int64(lparam)
            )

        def _paint(self, hwnd):
            """GDI 绘制蓝色圆形 + 白色 Q"""
            # 使用标准 BeginPaint/EndPaint 处理 WM_PAINT
            class PAINTSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("hdc", ctypes.c_void_p),
                    ("fErase", ctypes.c_int),
                    ("rcPaint", ctypes.c_long * 4),
                    ("fRestore", ctypes.c_int),
                    ("fIncUpdate", ctypes.c_int),
                    ("rgbReserved", ctypes.c_byte * 32),
                ]

            ps = PAINTSTRUCT()
            hdc = _user32.BeginPaint(hwnd, ctypes.byref(ps))

            # 绘制蓝色圆形：RGB(0,122,255) -> BGR 0x00FF7A00
            blue_brush = _gdi32.CreateSolidBrush(0x00FF7A00)
            null_pen = _gdi32.GetStockObject(5)  # NULL_PEN
            old_brush = _gdi32.SelectObject(hdc, blue_brush)
            old_pen = _gdi32.SelectObject(hdc, null_pen)
            _gdi32.Ellipse(hdc, 0, 0, BUTTON_SIZE, BUTTON_SIZE)
            _gdi32.SelectObject(hdc, old_brush)
            _gdi32.SelectObject(hdc, old_pen)
            _gdi32.DeleteObject(blue_brush)

            # 绘制白色 "Q"
            font = _gdi32.CreateFontW(
                -12, 0, 0, 0, 700, 0, 0, 0,
                0, 0, 0, 0,
                0, "Arial"
            )
            old_font = _gdi32.SelectObject(hdc, font)
            _gdi32.SetTextColor(hdc, 0x00FFFFFF)  # 白色
            _gdi32.SetBkMode(hdc, 1)  # TRANSPARENT

            # DT_CENTER=1 | DT_VCENTER=4 | DT_SINGLELINE=0x20 = 0x25
            rect = (ctypes.c_long * 4)(0, 0, BUTTON_SIZE, BUTTON_SIZE)
            _user32.DrawTextW(hdc, "Q", 1, rect, 0x25)

            _gdi32.SelectObject(hdc, old_font)
            _gdi32.DeleteObject(font)

            _user32.EndPaint(hwnd, ctypes.byref(ps))

        # ---- 公共接口（与 Qt 版本兼容）----

        def isVisible(self):
            return self._visible

        def x(self):
            return self._pos_x

        def y(self):
            return self._pos_y

        def width(self):
            return BUTTON_SIZE

        def height(self):
            return BUTTON_SIZE

        def show_at_position(self, pos, selected_text="", program_name=""):
            is_browser = is_browser_program(program_name)
            if pos is None:
                cursor_pos = QCursor.pos()
                x, y = cursor_pos.x(), cursor_pos.y()
            else:
                x, y = pos

            if is_browser:
                self._show_with_delay(x, y, selected_text)
            else:
                self._do_immediate_show(x, y, selected_text)

        def show_at_position_immediate(self, pos, selected_text=""):
            if pos is None:
                cursor_pos = QCursor.pos()
                x, y = cursor_pos.x(), cursor_pos.y()
            else:
                x, y = pos
            self._selected_text = selected_text
            self._native_show(x + 8, y + 8)

        def get_selected_text(self):
            return self._selected_text

        def set_selected_text(self, text):
            self._selected_text = text

        def hide(self):
            self._auto_hide_timer.stop()
            self._mouse_check_timer.stop()
            self._show_delay_timer.stop()
            self._selected_text = ""
            self._pending_show_pos = None
            self._pending_text = ""
            self._visible = False
            _user32.ShowWindow(self.hwnd, _SW_HIDE)
            self.hidden.emit()

        # ---- 内部方法 ----

        def _native_show(self, new_x, new_y):
            """显示原生窗口"""
            # 确保不超出屏幕边界
            try:
                screen = QApplication.primaryScreen()
                if screen:
                    geo = screen.availableVirtualGeometry()
                    if new_x + BUTTON_SIZE > geo.x() + geo.width():
                        new_x = self._pos_x - BUTTON_SIZE - 8 if new_x == self._pos_x + 8 else new_x
                        new_x = max(new_x, geo.x() + 5)
                    if new_y + BUTTON_SIZE > geo.y() + geo.height():
                        new_y = self._pos_y - BUTTON_SIZE - 8 if new_y == self._pos_y + 8 else new_y
                        new_y = max(new_y, geo.y() + 5)
            except Exception:
                pass

            self._pos_x = new_x
            self._pos_y = new_y
            self._visible = True
            self._is_just_shown = True

            # 移动并显示窗口
            _user32.SetWindowPos(
                self.hwnd, ctypes.c_void_p(-1),  # HWND_TOPMOST
                new_x, new_y, BUTTON_SIZE, BUTTON_SIZE,
                _SWP_NOACTIVATE | _SWP_FRAMECHANGED
            )
            _user32.ShowWindow(self.hwnd, _SW_SHOWNOACTIVATE)
            _user32.InvalidateRect(self.hwnd, None, True)

            # 启动计时器
            self._mouse_check_timer.start()
            self._auto_hide_timer.start(self._auto_hide_delay)
            QTimer.singleShot(500, self._reset_just_shown)

        def _do_immediate_show(self, x, y, selected_text):
            self._selected_text = selected_text
            self._native_show(x + 8, y + 8)

        def _show_with_delay(self, x, y, selected_text):
            self._pending_show_pos = (x, y)
            self._pending_text = selected_text
            self._show_delay_timer.stop()
            delay_ms = get_config().get('selection.browser_delay_ms', DEFAULT_BROWSER_DELAY_MS)
            self._show_delay_timer.start(delay_ms)

        def _do_delayed_show(self):
            if self._pending_show_pos is None:
                return
            x, y = self._pending_show_pos
            self._selected_text = self._pending_text
            self._pending_show_pos = None
            self._pending_text = ""

            cursor_pos = QCursor.pos()
            self._native_show(cursor_pos.x() + 8, cursor_pos.y() + 8)

        def _check_mouse_distance(self):
            if self._is_just_shown or not self._visible:
                return
            cursor_pos = QCursor.pos()
            mx, my = cursor_pos.x(), cursor_pos.y()
            cx = self._pos_x + BUTTON_SIZE // 2
            cy = self._pos_y + BUTTON_SIZE // 2
            distance = math.sqrt((mx - cx) ** 2 + (my - cy) ** 2)
            if distance > HIDE_DISTANCE_THRESHOLD:
                if not (self._pos_x <= mx <= self._pos_x + BUTTON_SIZE and
                        self._pos_y <= my <= self._pos_y + BUTTON_SIZE):
                    self.hide()
                    return
            self._auto_hide_timer.stop()
            self._auto_hide_timer.start(self._auto_hide_delay)

        def _on_auto_hide(self):
            self.hide()

        def _reset_just_shown(self):
            self._is_just_shown = False


# ============================================================================
# 非 Windows 平台：Qt QWidget 实现
# ============================================================================
else:
    from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QIcon, QRegion
    from pathlib import Path

    class TranslateButton(QWidget):
        """翻译图标按钮（Qt 实现，用于非 Windows 平台）"""

        clicked = pyqtSignal()
        hidden = pyqtSignal()

        def __init__(self):
            super().__init__()

            self._auto_hide_delay = 5000
            self._selected_text: str = ""
            self._auto_hide_timer: Optional[QTimer] = None
            self._mouse_check_timer: Optional[QTimer] = None
            self._is_just_shown: bool = False
            self._show_delay_timer: Optional[QTimer] = None
            self._pending_show_pos: Optional[Tuple[int, int]] = None
            self._pending_text: str = ""

            self._setup_window_properties()
            self._setup_ui()
            self._setup_auto_hide_timer()
            self._setup_mouse_check_timer()
            self._setup_delay_timers()

        def _setup_window_properties(self):
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool |
                Qt.WindowType.NoDropShadowWindowHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            self.create()
            _ = self.winId()

        def _setup_ui(self):
            self._icon_label = QLabel(self)
            self._icon_label.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            pixmap = self._create_icon()
            self._icon_label.setPixmap(pixmap)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self._icon_label)
            self.setMouseTracking(True)

        def _create_icon(self) -> QPixmap:
            icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
            if icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                if not pixmap.isNull():
                    return pixmap.scaled(
                        BUTTON_SIZE, BUTTON_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
            pixmap = QPixmap(BUTTON_SIZE, BUTTON_SIZE)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(0, 122, 255, 128))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(0, 0, BUTTON_SIZE, BUTTON_SIZE)
            painter.setPen(QColor(255, 255, 255, 230))
            font = QFont("Arial", 10, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "T")
            painter.end()
            return pixmap

        def _setup_auto_hide_timer(self):
            self._auto_hide_timer = QTimer()
            self._auto_hide_timer.setSingleShot(True)
            self._auto_hide_timer.timeout.connect(self._on_auto_hide)

        def _setup_mouse_check_timer(self):
            self._mouse_check_timer = QTimer()
            self._mouse_check_timer.setInterval(100)
            self._mouse_check_timer.timeout.connect(self._check_mouse_distance)

        def _setup_delay_timers(self):
            self._show_delay_timer = QTimer()
            self._show_delay_timer.setSingleShot(True)
            self._show_delay_timer.timeout.connect(self._do_delayed_show)

        def _check_mouse_distance(self):
            if self._is_just_shown or not self.isVisible():
                return
            cursor_pos = QCursor.pos()
            mx, my = cursor_pos.x(), cursor_pos.y()
            bx, by, bw, bh = self.x(), self.y(), self.width(), self.height()
            cx, cy = bx + bw // 2, by + bh // 2
            distance = math.sqrt((mx - cx) ** 2 + (my - cy) ** 2)
            if distance > HIDE_DISTANCE_THRESHOLD:
                if not (bx <= mx <= bx + bw and by <= my <= by + bh):
                    self.hide()
                    return
            self._auto_hide_timer.stop()
            self._auto_hide_timer.start(self._auto_hide_delay)

        def _do_delayed_show(self):
            if self._pending_show_pos is None:
                return
            x, y = self._pending_show_pos
            self._selected_text = self._pending_text
            self._pending_show_pos = None
            self._pending_text = ""
            cursor_pos = QCursor.pos()
            new_x, new_y = cursor_pos.x() + 8, cursor_pos.y() + 8
            try:
                screen = QApplication.primaryScreen()
                if screen:
                    geo = screen.availableVirtualGeometry()
                    if new_x + BUTTON_SIZE > geo.x() + geo.width():
                        new_x = cursor_pos.x() - BUTTON_SIZE - 8
                    if new_y + BUTTON_SIZE > geo.y() + geo.height():
                        new_y = cursor_pos.y() - BUTTON_SIZE - 8
                    new_x = max(new_x, geo.x() + 5)
                    new_y = max(new_y, geo.y() + 5)
            except Exception:
                pass
            if self.isVisible():
                super().hide()
            self.move(new_x, new_y)
            self._is_just_shown = True
            if not self.winId():
                self.create()
            self.show()
            self.raise_()
            self.repaint()
            QApplication.processEvents()
            self._mouse_check_timer.start()
            self._auto_hide_timer.start(self._auto_hide_delay)
            QTimer.singleShot(500, self._reset_just_shown)

        def show_at_position(self, pos, selected_text="", program_name=""):
            is_browser = is_browser_program(program_name)
            if pos is None:
                cursor_pos = QCursor.pos()
                x, y = cursor_pos.x(), cursor_pos.y()
            else:
                x, y = pos
            if is_browser:
                self._show_with_delay(x, y, selected_text)
            else:
                self._do_immediate_show(x, y, selected_text)

        def _do_immediate_show(self, x, y, selected_text):
            self._selected_text = selected_text
            new_x, new_y = x + 8, y + 8
            try:
                screen = QApplication.primaryScreen()
                if screen:
                    geo = screen.availableVirtualGeometry()
                    if new_x + BUTTON_SIZE > geo.x() + geo.width():
                        new_x = x - BUTTON_SIZE - 8
                    if new_y + BUTTON_SIZE > geo.y() + geo.height():
                        new_y = y - BUTTON_SIZE - 8
                    new_x = max(new_x, geo.x() + 5)
                    new_y = max(new_y, geo.y() + 5)
            except Exception:
                pass
            if self.isVisible():
                super().hide()
            self.move(new_x, new_y)
            self._is_just_shown = True
            if not self.winId():
                self.create()
            self.show()
            self.raise_()
            self.repaint()
            QApplication.processEvents()
            self._mouse_check_timer.start()
            self._auto_hide_timer.start(self._auto_hide_delay)
            QTimer.singleShot(500, self._reset_just_shown)

        def _show_with_delay(self, x, y, selected_text):
            self._pending_show_pos = (x, y)
            self._pending_text = selected_text
            self._show_delay_timer.stop()
            delay_ms = get_config().get('selection.browser_delay_ms', DEFAULT_BROWSER_DELAY_MS)
            self._show_delay_timer.start(delay_ms)

        def show_at_position_immediate(self, pos, selected_text=""):
            if pos is None:
                cursor_pos = QCursor.pos()
                x, y = cursor_pos.x(), cursor_pos.y()
            else:
                x, y = pos
            self._selected_text = selected_text
            new_x, new_y = x + 8, y + 8
            try:
                screen = QApplication.primaryScreen()
                if screen:
                    geo = screen.availableVirtualGeometry()
                    if new_x + BUTTON_SIZE > geo.x() + geo.width():
                        new_x = x - BUTTON_SIZE - 8
                    if new_y + BUTTON_SIZE > geo.y() + geo.height():
                        new_y = y - BUTTON_SIZE - 8
                    new_x = max(new_x, geo.x() + 5)
                    new_y = max(new_y, geo.y() + 5)
            except Exception:
                pass
            if self.isVisible():
                super().hide()
            self.move(new_x, new_y)
            self._is_just_shown = True
            self.show()
            self.raise_()
            self.activateWindow()
            self.update()
            self._mouse_check_timer.start()
            self._auto_hide_timer.start(self._auto_hide_delay)
            QTimer.singleShot(500, self._reset_just_shown)

        def get_selected_text(self):
            return self._selected_text

        def set_selected_text(self, text):
            self._selected_text = text

        def hide(self):
            self._auto_hide_timer.stop()
            self._mouse_check_timer.stop()
            self._show_delay_timer.stop()
            self._selected_text = ""
            self._pending_show_pos = None
            self._pending_text = ""
            super().hide()
            self.hidden.emit()

        def _on_auto_hide(self):
            self.hide()

        def enterEvent(self, event):
            self._auto_hide_timer.stop()
            super().enterEvent(event)

        def leaveEvent(self, event):
            if self._is_just_shown:
                super().leaveEvent(event)
                return
            self._auto_hide_timer.start(1000)
            super().leaveEvent(event)

        def _reset_just_shown(self):
            self._is_just_shown = False

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit()
                QTimer.singleShot(100, self.hide)
            super().mousePressEvent(event)


# 全局实例
_button_instance: Optional[TranslateButton] = None


def get_translate_button() -> TranslateButton:
    """获取全局翻译按钮实例"""
    global _button_instance
    if _button_instance is None:
        _button_instance = TranslateButton()
    return _button_instance
