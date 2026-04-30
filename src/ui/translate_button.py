"""翻译图标按钮组件 - QTranslator

Windows 平台使用 WS_EX_LAYERED + UpdateLayeredWindow 创建分层窗口，
由应用自己提供 premultiplied BGRA 位图作为最终合成结果 ——
DWM 直接采用位图不加任何后处理（无阴影、无 peek、无 blur）。

坐标完全走物理像素路径（Win32 `GetCursorPos` + `GetSystemMetrics`），
图标大小按显示器 DPI 缩放（base 28 × scale），适配 100%/125%/150%/200%。
"""
import math
from pathlib import Path
from typing import Optional, Tuple
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import QCursor, QImage
from PyQt6.QtWidgets import QApplication

# 按钮基础尺寸（逻辑像素，100% DPI 下的大小）
# Windows 分支会按实际 DPI 缩放到物理像素再绘制。
BUTTON_SIZE = 24

# 鼠标离开按钮多少像素后自动隐藏（使用逻辑坐标）
HIDE_DISTANCE_THRESHOLD = 50

# 点击动画参数（弹跳 + 渐隐）
CLICK_ANIM_BOUNCE_MS = 200          # 弹跳阶段时长（毫秒）
CLICK_ANIM_FADE_MS = 150            # 渐隐阶段时长（毫秒）
CLICK_ANIM_DURATION_MS = CLICK_ANIM_BOUNCE_MS + CLICK_ANIM_FADE_MS
CLICK_ANIM_FRAME_MS = 16            # 每帧间隔（约60fps）
CLICK_ANIM_FRAMES = CLICK_ANIM_DURATION_MS // CLICK_ANIM_FRAME_MS
CLICK_ANIM_BOUNCE_HEIGHT = 10      # 弹跳高度（逻辑像素）
CLICK_ANIM_BOUNCE_RATIO = CLICK_ANIM_BOUNCE_MS / CLICK_ANIM_DURATION_MS  # 弹跳阶段占比


# ============================================================================
# Windows 平台：UpdateLayeredWindow（无 DWM 阴影）+ DPI-aware 物理像素定位
# ============================================================================
# 机制说明：
#   ❌ 旧方案用 SetWindowRgn + WS_EX_NOREDIRECTIONBITMAP：
#       - SetWindowRgn 本身会被 Win11 DWM 识别为"非矩形窗口"并自动添加阴影
#       - WS_EX_NOREDIRECTIONBITMAP 必须配合 DirectComposition，
#         用 GDI 画会被 DWM 静默重新分配重定向表面 → 阴影依然出现
#   ✅ 本方案用 WS_EX_LAYERED + UpdateLayeredWindow：
#       - 应用自己提供 premultiplied BGRA 位图作为"最终合成结果"
#       - DWM 直接取用，不插手也不做任何后处理（阴影/peek/blur 全无）
#       - 圆形来自 PNG 的 alpha 通道，不需要 SetWindowRgn
#
# 定位修复：
#   Qt 的 QCursor.pos() 返回的是"逻辑像素"（按 Qt 的 DPI 系统已缩放）。
#   而 Win32 UpdateLayeredWindow / SetWindowPos / GetCursorPos 吃"物理像素"。
#   在 150% 缩放下直接混用会让图标偏移到鼠标左上方。
#   本分支全程只走物理像素：
#     - 位置从 GetCursorPos（物理）取
#     - 边界从 GetSystemMetrics（物理）取
#     - 位图按 BUTTON_SIZE × DPI 缩放，DIB section 也分配物理尺寸
# ============================================================================
import ctypes

from PyQt6.QtCore import QObject

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_gdi32 = ctypes.windll.gdi32

# ---- Win32 常量 ----
_WS_POPUP = 0x80000000
_WS_EX_LAYERED = 0x00080000            # 分层窗口（关键）
_WS_EX_TOPMOST = 0x00000008
_WS_EX_NOACTIVATE = 0x08000000         # 不抢焦点
_WS_EX_TOOLWINDOW = 0x00000080         # 不进任务栏/Alt+Tab

_ULW_ALPHA = 0x00000002
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01

_BI_RGB = 0
_DIB_RGB_COLORS = 0

_WM_LBUTTONDOWN = 0x0201
_WM_DESTROY = 0x0002

_SW_HIDE = 0
_SW_SHOWNOACTIVATE = 4

_HWND_TOPMOST = -1
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010

_LOGPIXELSX = 88

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

# ---- 函数原型（64 位下显式声明，防止指针被截断）----
_user32.CreateWindowExW.restype = ctypes.c_void_p
_user32.GetDC.restype = ctypes.c_void_p
_user32.GetDC.argtypes = [ctypes.c_void_p]
_user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.UpdateLayeredWindow.restype = ctypes.c_int
_user32.UpdateLayeredWindow.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
    ctypes.c_uint,
]
_user32.GetCursorPos.argtypes = [ctypes.c_void_p]
_user32.GetCursorPos.restype = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int
_gdi32.CreateDIBSection.restype = ctypes.c_void_p
_gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
_gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_gdi32.SelectObject.restype = ctypes.c_void_p
_gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
_gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
_gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
_gdi32.GetDeviceCaps.restype = ctypes.c_int

# ---- 结构体 ----
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_uint),
        ("biSizeImage", ctypes.c_uint),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint),
        ("biClrImportant", ctypes.c_uint),
    ]

class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_uint * 3),
    ]

_WNDPROC = ctypes.CFUNCTYPE(
    ctypes.c_int64,
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.c_uint64,
    ctypes.c_int64,
)

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
_wndproc_ref = None  # 防止回调被 GC

def _register_window_class(wndproc):
    global _window_class_registered, _wndproc_ref
    if _window_class_registered:
        return
    _wndproc_ref = wndproc
    hInstance = _kernel32.GetModuleHandleW(None)
    wc = _WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
    wc.style = 0  # 不要 CS_DROPSHADOW
    wc.lpfnWndProc = wndproc
    wc.hInstance = hInstance
    wc.hCursor = _user32.LoadCursorW(None, ctypes.c_void_p(32512))  # IDC_ARROW
    wc.hbrBackground = None  # 分层窗口不要背景刷
    wc.lpszClassName = "QTranslatorBtnLayered"
    _user32.RegisterClassExW(ctypes.byref(wc))
    _window_class_registered = True

def _get_dpi_scale() -> float:
    """主显示器 DPI 缩放（1.0 / 1.25 / 1.5 / 2.0 …）。"""
    hdc = _user32.GetDC(None)
    try:
        dpi = _gdi32.GetDeviceCaps(hdc, _LOGPIXELSX)
        return max(1.0, dpi / 96.0) if dpi > 0 else 1.0
    finally:
        _user32.ReleaseDC(None, hdc)

def _get_cursor_physical() -> Tuple[int, int]:
    """Win32 GetCursorPos —— 返回的就是物理像素。"""
    pt = _POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def _load_icon_as_bgra_premultiplied(icon_path: str, size: int) -> bytes:
    """用 QImage 加载 PNG，输出 premultiplied BGRA。

    Qt 的 Format_ARGB32_Premultiplied 在小端架构（x86/x64）上
    内存布局刚好就是 B, G, R, A —— 正是 UpdateLayeredWindow 要的格式。

    注意：WS_EX_LAYERED 窗口使用 UpdateLayeredWindow 时，Windows 根据
    alpha 通道做 hit-test —— alpha=0 的像素鼠标事件会穿透。
    为保证整个图标区域都可点击（包括透明部分如字母空洞、圆角外围），
    将 alpha=0 的像素改为 alpha=1（肉眼不可见但 hit-test 可通过）。
    """
    img = QImage(icon_path)
    if img.isNull():
        raise FileNotFoundError(f"failed to load icon: {icon_path}")
    img = img.scaled(
        size, size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    bits = img.constBits()
    bits.setsize(img.sizeInBytes())
    data = bytearray(bits)
    # BGRA 格式：每 4 字节 [B, G, R, A]，将 alpha=0 改为 alpha=1
    for i in range(3, len(data), 4):
        if data[i] == 0:
            data[i] = 1
    return bytes(data)

class TranslateButton(QObject):
    """翻译图标按钮（UpdateLayeredWindow + DPI-aware 定位）

    - UpdateLayeredWindow → Win11 无阴影
    - GetCursorPos / GetSystemMetrics → 全程物理像素，不受 Qt 高 DPI 误导
    - 图标按 DPI 缩放（base BUTTON_SIZE × scale），100%/125%/150%/200% 都锐利
    - 始终出现在鼠标右下方（+8 逻辑像素 × DPI）
    """

    clicked = pyqtSignal()
    hidden = pyqtSignal()

    def __init__(self):
        super().__init__()

        self._auto_hide_delay = 5000
        self._selected_text: str = ""
        self._is_just_shown: bool = False
        self._visible: bool = False
        self._pos_x: int = -1000       # 物理像素
        self._pos_y: int = -1000

        # DPI 与物理像素尺寸
        self._scale = _get_dpi_scale()
        # self._phys_size = int(round(BUTTON_SIZE * self._scale))
        self._phys_size = int(BUTTON_SIZE)
        self._phys_offset = int(round(8 * self._scale))              # 鼠标右下 8 逻辑像素
        self._phys_hide_threshold = int(round(HIDE_DISTANCE_THRESHOLD * self._scale))

        # Win32 资源
        self.hwnd: int = 0
        self._hdc_mem = None
        self._hbitmap = None
        self._old_bitmap = None
        self._original_bgra: Optional[bytes] = None       # 原始位图数据（动画恢复用）
        self._bits_ptr = None                             # DIB section 位指针

        self._create_native_window()
        self._prepare_layered_bitmap()

        # 计时器
        self._auto_hide_timer = QTimer()
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._on_auto_hide)

        self._mouse_check_timer = QTimer()
        self._mouse_check_timer.setInterval(100)
        self._mouse_check_timer.timeout.connect(self._check_mouse_distance)

        # 点击动画
        self._click_anim_step: int = 0
        self._click_anim_timer = QTimer()
        self._click_anim_timer.setInterval(CLICK_ANIM_FRAME_MS)
        self._click_anim_timer.timeout.connect(self._on_click_anim_frame)

    # ---- 窗口创建 ----
    def _create_native_window(self):
        hInstance = _kernel32.GetModuleHandleW(None)
        _register_window_class(_WNDPROC(self._wndproc_handler))

        ex_style = (
            _WS_EX_LAYERED
            | _WS_EX_TOPMOST
            | _WS_EX_NOACTIVATE
            | _WS_EX_TOOLWINDOW
        )

        hwnd = _user32.CreateWindowExW(
            ex_style,
            "QTranslatorBtnLayered",
            "",
            _WS_POPUP,
            -1000, -1000, self._phys_size, self._phys_size,
            0, 0, hInstance, 0,
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
        self.hwnd = hwnd
        # 注意：不调用 SetWindowRgn —— 形状由 PNG alpha 决定。

    # ---- 图标位图准备（一次性，按物理像素）----
    def _prepare_layered_bitmap(self):
        icon_path = (
            Path(__file__).parent.parent.parent / "assets" / "icon.png"
        )
        if not icon_path.exists():
            raise FileNotFoundError(f"icon not found: {icon_path}")

        phys_size = self._phys_size
        bgra = _load_icon_as_bgra_premultiplied(str(icon_path), phys_size)
        self._original_bgra = bgra

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = phys_size
        bmi.bmiHeader.biHeight = -phys_size  # 负值 = 自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = _BI_RGB

        bits_ptr = ctypes.c_void_p()
        hbitmap = _gdi32.CreateDIBSection(
            None,
            ctypes.byref(bmi),
            _DIB_RGB_COLORS,
            ctypes.byref(bits_ptr),
            None,
            0,
        )
        if not hbitmap or not bits_ptr.value:
            raise OSError("CreateDIBSection failed")
        self._hbitmap = hbitmap
        self._bits_ptr = bits_ptr

        ctypes.memmove(bits_ptr, bgra, len(bgra))

        hdc_screen = _user32.GetDC(None)
        self._hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
        self._old_bitmap = _gdi32.SelectObject(self._hdc_mem, self._hbitmap)
        _user32.ReleaseDC(None, hdc_screen)

    def _wndproc_handler(self, hwnd, msg, wparam, lparam):
        """分层窗口不收 WM_PAINT，只处理点击。"""
        if msg == _WM_LBUTTONDOWN:
            if self._click_anim_timer.isActive():
                return 0
            self.clicked.emit()
            self._start_click_animation()
            return 0
        if msg == _WM_DESTROY:
            return 0
        return ctypes.windll.user32.DefWindowProcW(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(msg),
            ctypes.c_uint64(wparam),
            ctypes.c_int64(lparam),
        )

    # ---- 公共接口 ----
    def isVisible(self):
        return self._visible

    def x(self):
        return self._pos_x

    def y(self):
        return self._pos_y

    def width(self):
        return self._phys_size

    def height(self):
        return self._phys_size

    def show_at_position(self, pos, selected_text="", program_name=""):
        """pos / program_name 保留签名兼容；定位一律从 GetCursorPos 读物理像素。"""
        cx, cy = _get_cursor_physical()
        self._do_immediate_show(cx, cy, selected_text)

    def show_at_position_immediate(self, pos, selected_text=""):
        cx, cy = _get_cursor_physical()
        self._selected_text = selected_text
        self._native_show(cx, cy)

    def get_selected_text(self):
        return self._selected_text

    def set_selected_text(self, text):
        self._selected_text = text

    def hide(self):
        self._auto_hide_timer.stop()
        self._mouse_check_timer.stop()
        self._click_anim_timer.stop()
        self._selected_text = ""
        self._visible = False
        _user32.ShowWindow(self.hwnd, _SW_HIDE)
        self.hidden.emit()

    # ---- 核心：UpdateLayeredWindow 合成 + 物理像素定位 ----
    def _native_show(self, cursor_phys_x, cursor_phys_y):
        """(cursor_phys_x, cursor_phys_y) 必须是物理像素。
        图标出现在鼠标右下方 +8 逻辑像素（按 DPI 缩放后的物理像素）。
        """
        # 停止可能正在进行的点击动画，恢复原始位图
        self._click_anim_timer.stop()
        if self._original_bgra and self._bits_ptr and self._bits_ptr.value:
            ctypes.memmove(self._bits_ptr, self._original_bgra, len(self._original_bgra))

        size = self._phys_size
        off = self._phys_offset
        new_x = cursor_phys_x + off
        new_y = cursor_phys_y + off

        # 边界检查（物理像素）
        try:
            vx = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
            vy = _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
            vw = _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
            vh = _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
            if new_x + size > vx + vw:
                new_x = max(cursor_phys_x - size - off, vx + 2)
            if new_y + size > vy + vh:
                new_y = max(cursor_phys_y - size - off, vy + 2)
            if new_x < vx:
                new_x = vx + 2
            if new_y < vy:
                new_y = vy + 2
        except Exception:
            pass

        self._pos_x = new_x
        self._pos_y = new_y
        self._visible = True
        self._is_just_shown = True

        pt_dst = _POINT(new_x, new_y)
        sz = _SIZE(size, size)
        pt_src = _POINT(0, 0)
        blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)

        hdc_screen = _user32.GetDC(None)
        _user32.UpdateLayeredWindow(
            ctypes.c_void_p(self.hwnd),
            ctypes.c_void_p(hdc_screen),
            ctypes.byref(pt_dst),
            ctypes.byref(sz),
            ctypes.c_void_p(self._hdc_mem),
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            _ULW_ALPHA,
        )
        _user32.ReleaseDC(None, hdc_screen)

        _user32.ShowWindow(self.hwnd, _SW_SHOWNOACTIVATE)
        _user32.SetWindowPos(
            ctypes.c_void_p(self.hwnd),
            ctypes.c_void_p(_HWND_TOPMOST),
            0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
        )

        self._mouse_check_timer.start()
        self._auto_hide_timer.start(self._auto_hide_delay)
        QTimer.singleShot(500, self._reset_just_shown)

    def _do_immediate_show(self, cx, cy, selected_text):
        self._selected_text = selected_text
        self._native_show(cx, cy)

    def _check_mouse_distance(self):
        if self._is_just_shown or not self._visible:
            return
        mx, my = _get_cursor_physical()
        size = self._phys_size
        cx = self._pos_x + size // 2
        cy = self._pos_y + size // 2
        distance = math.sqrt((mx - cx) ** 2 + (my - cy) ** 2)
        if distance > self._phys_hide_threshold:
            if not (self._pos_x <= mx <= self._pos_x + size and
                    self._pos_y <= my <= self._pos_y + size):
                self.hide()
                return
        self._auto_hide_timer.stop()
        self._auto_hide_timer.start(self._auto_hide_delay)

    def _on_auto_hide(self):
        self.hide()

    def _reset_just_shown(self):
        self._is_just_shown = False

    # ---- 点击动画（弹跳 + 渐隐）----
    def _start_click_animation(self):
        """启动点击动画：先弹跳向上再落回，然后渐隐消失。"""
        if not self._bits_ptr or not self._bits_ptr.value:
            QTimer.singleShot(100, self.hide)
            return
        self._mouse_check_timer.stop()
        self._auto_hide_timer.stop()
        self._click_anim_step = 0
        self._anim_start_x = self._pos_x
        self._anim_start_y = self._pos_y
        self._click_anim_timer.start()

    def _on_click_anim_frame(self):
        """每一帧更新位置和透明度。

        动画分两阶段：
        - 弹跳阶段（0 ~ BOUNCE_RATIO）：图标向上弹起再落回原位
        - 渐隐阶段（BOUNCE_RATIO ~ 1.0）：图标原地渐隐消失
        """
        self._click_anim_step += 1
        if self._click_anim_step > CLICK_ANIM_FRAMES:
            self._click_anim_timer.stop()
            self.hide()
            return

        progress = self._click_anim_step / CLICK_ANIM_FRAMES

        # 弹跳阶段：抛物线 Y 偏移（上弹后回落）
        bounce_px = int(CLICK_ANIM_BOUNCE_HEIGHT * self._scale)
        if progress <= CLICK_ANIM_BOUNCE_RATIO:
            # 归一化弹跳进度 0~1
            bp = progress / CLICK_ANIM_BOUNCE_RATIO
            # 抛物线：4 * bp * (1 - bp) 在 bp=0.5 时达到峰值1
            offset_y = int(bounce_px * 4 * bp * (1 - bp))
            opacity = 1.0
        else:
            # 渐隐阶段：图标回到原位，透明度线性降为0
            offset_y = 0
            fp = (progress - CLICK_ANIM_BOUNCE_RATIO) / (1.0 - CLICK_ANIM_BOUNCE_RATIO)
            opacity = 1.0 - fp

        # 恢复原始位图数据
        if self._original_bgra:
            ctypes.memmove(self._bits_ptr, self._original_bgra, len(self._original_bgra))

        new_x = self._anim_start_x
        new_y = self._anim_start_y - offset_y
        self._pos_x = new_x
        self._pos_y = new_y

        phys_size = self._phys_size
        pt_dst = _POINT(new_x, new_y)
        sz = _SIZE(phys_size, phys_size)
        pt_src = _POINT(0, 0)
        alpha_byte = max(0, int(255 * opacity))
        blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, alpha_byte, _AC_SRC_ALPHA)

        hdc_screen = _user32.GetDC(None)
        _user32.UpdateLayeredWindow(
            ctypes.c_void_p(self.hwnd),
            ctypes.c_void_p(hdc_screen),
            ctypes.byref(pt_dst),
            ctypes.byref(sz),
            ctypes.c_void_p(self._hdc_mem),
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            _ULW_ALPHA,
        )
        _user32.ReleaseDC(None, hdc_screen)

    def __del__(self):
        try:
            if self._hdc_mem and self._old_bitmap:
                _gdi32.SelectObject(self._hdc_mem, self._old_bitmap)
            if self._hbitmap:
                _gdi32.DeleteObject(self._hbitmap)
            if self._hdc_mem:
                _gdi32.DeleteDC(self._hdc_mem)
            if self.hwnd:
                _user32.DestroyWindow(ctypes.c_void_p(self.hwnd))
        except Exception:
            pass

# 全局实例
_button_instance: Optional[TranslateButton] = None


def get_translate_button() -> TranslateButton:
    """获取全局翻译按钮实例"""
    global _button_instance
    if _button_instance is None:
        _button_instance = TranslateButton()
    return _button_instance
