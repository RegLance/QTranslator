"""高 DPI（per-monitor DPI awareness）显示唤醒后失同步修复。

背景：程序以 per-monitor DPI 感知运行（main.py 里 `SetProcessDpiAwareness(2)`）。
锁屏 / 显示器休眠唤醒时，Windows 会重新初始化显示器，每个窗口缓存的 DPI 可能
短暂回落（如 96），Qt 据此把无边框窗口缩小；唤醒稳定后系统不一定补发
WM_DPICHANGED，于是所有窗口「缩小一圈」。手动拖动窗口会触发 Windows 按显示器
重新评估该窗口的 DPI，所以拖动能恢复。

修复：在窗口显示、以及系统报告显示器 / DPI 变化时，用 Win32
`GetDpiForMonitor` 读取显示器真实 DPI，与 `GetDpiForWindow`（窗口当前 DPI）以及
Qt 缓存的 `devicePixelRatioF` 比对；不一致则通过一次 1px 原位微移强制 Windows
重新评估该窗口 DPI（等同拖动窗口触发的机制），让 Qt 重排窗口。

全部逻辑事件驱动、且仅在确实失同步时动作，正常情况下是 no-op，无性能开销。
"""

import sys
import ctypes

# 允许的 DPR 偏差（应对非整数缩放下的浮点舍入，如 1.25 vs 1.24999...）
_DPR_EPS = 0.02


def is_supported() -> bool:
    return sys.platform == "win32"


# ---------------------------------------------------------------------------
# Win32 原型（显式声明 argtypes/restype，避免 64 位句柄被截断）
# ---------------------------------------------------------------------------

def _user32():
    u = ctypes.windll.user32
    u.GetDpiForWindow.restype = ctypes.c_uint
    u.GetDpiForWindow.argtypes = [ctypes.c_void_p]
    u.MonitorFromWindow.restype = ctypes.c_void_p
    u.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    u.GetWindowRect.restype = ctypes.c_int
    u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    u.SetWindowPos.restype = ctypes.c_int
    u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    return u


def _shcore():
    s = ctypes.windll.shcore
    s.GetDpiForMonitor.restype = ctypes.c_long
    s.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                   ctypes.c_void_p, ctypes.c_void_p]
    return s


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


# ---------------------------------------------------------------------------
# DPI 查询
# ---------------------------------------------------------------------------

def get_native_dpi(widget) -> int:
    """Windows 为窗口缓存的 DPI（如 96/120/144）；失败返回 0。"""
    if not is_supported():
        return 0
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return 0
        return int(_user32().GetDpiForWindow(hwnd))
    except Exception:
        return 0


def get_monitor_dpi(widget) -> int:
    """窗口所在显示器的真实 DPI（依据显示器，权威值）；失败返回 0。"""
    if not is_supported():
        return 0
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return 0
        user32 = _user32()
        # MONITOR_DEFAULTTONEAREST = 2
        hmon = user32.MonitorFromWindow(hwnd, 2)
        if not hmon:
            return 0
        shcore = _shcore()
        # MDT_EFFECTIVE_DPI = 0
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) != 0:
            return 0
        return int(dpi_x.value)
    except Exception:
        return 0


def _qt_dpr(widget) -> float:
    """Qt 缓存的每窗口 devicePixelRatio；失败回退 1.0。"""
    handle = widget.windowHandle()
    if handle is not None:
        try:
            return float(handle.devicePixelRatioF())
        except Exception:
            pass
    try:
        return float(widget.devicePixelRatioF())
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# 重同步
# ---------------------------------------------------------------------------

def is_dpi_mismatched(widget) -> bool:
    monitor_dpi = get_monitor_dpi(widget)
    if not monitor_dpi:
        return False

    # 窗口级 DPI 与显示器真实 DPI 不一致（Windows 侧失同步）
    window_dpi = get_native_dpi(widget)
    if window_dpi and window_dpi != monitor_dpi:
        return True

    # 窗口 DPI 正确但 Qt 缓存 DPR 未跟上（Qt 侧失同步）
    if abs(monitor_dpi / 96.0 - _qt_dpr(widget)) > _DPR_EPS:
        return True

    return False


def _nudge(window) -> None:
    """原位微移 1px 再复位，触发 Windows 按显示器重新评估窗口 DPI。

    两次 SetWindowPos 在同一段同步代码内完成，肉眼不可见。
    """
    hwnd = int(window.winId())
    if not hwnd:
        return
    user32 = _user32()
    rect = _RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return

    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE

    user32.SetWindowPos(hwnd, 0, rect.left + 1, rect.top, 0, 0, flags)
    user32.SetWindowPos(hwnd, 0, rect.left, rect.top, 0, 0, flags)


def sync_window_dpi(widget) -> bool:
    """若窗口 DPI 失同步则强制重新评估；返回是否执行了修复。"""
    if not is_supported() or not is_dpi_mismatched(widget):
        return False
    try:
        _nudge(widget)
        return True
    except Exception:
        return False


def sync_all_windows() -> int:
    """重同步所有可见顶层窗口；返回实际修复的窗口数。"""
    if not is_supported():
        return 0
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception:
        return 0
    app = QApplication.instance()
    if app is None:
        return 0
    fixed = 0
    for w in app.topLevelWidgets():
        try:
            if w.isVisible() and sync_window_dpi(w):
                fixed += 1
        except RuntimeError:
            continue
    return fixed


# ---------------------------------------------------------------------------
# 全局监听
# ---------------------------------------------------------------------------

def install_dpi_monitor(app) -> None:
    """在 QApplication 上安装全局显示器 / DPI 变化监听（仅 Windows）。

    显示器休眠唤醒往往发生在窗口隐藏期间，Qt 可能收不到 WM_DPICHANGED；
    这里监听显示器与 DPI 变化，一旦触发立即重同步所有窗口。
    """
    if not is_supported():
        return
    try:
        app.screenAdded.connect(_on_screen_added)
        app.screenRemoved.connect(_on_screen_changed)
    except Exception:
        pass
    try:
        for screen in app.screens():
            _attach_screen(screen)
    except Exception:
        pass


def _attach_screen(screen) -> None:
    for sig_name in ("logicalDotsPerInchChanged",
                     "physicalDotsPerInchChanged",
                     "geometryChanged"):
        try:
            getattr(screen, sig_name).connect(_on_screen_changed)
        except Exception:
            pass


def _on_screen_added(screen) -> None:
    _attach_screen(screen)
    _on_screen_changed()


def _on_screen_changed(*_args) -> None:
    try:
        from PyQt6.QtCore import QTimer
        # 显示器 / DPI 变化可能连续多次，延迟一拍统一重同步
        QTimer.singleShot(0, sync_all_windows)
    except Exception:
        pass
