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


def _screen_logical_dpi(widget) -> int:
    """Qt 缓存的窗口所在屏幕 logicalDotsPerInch；失败返回 0。"""
    try:
        from PyQt6.QtWidgets import QApplication
        handle = widget.windowHandle()
        screen = handle.screen() if handle is not None else None
        if screen is None:
            screen = QApplication.screenAt(widget.mapToGlobal(widget.rect().center())) \
                if not widget.rect().isEmpty() else QApplication.primaryScreen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return 0
        return int(round(screen.logicalDotsPerInch()))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# 重同步
# ---------------------------------------------------------------------------

def _diagnose(widget, tag: str) -> None:
    """把窗口的 DPI / 尺寸状态写入日志，用于定位唤醒后窗口缩小问题。"""
    try:
        from ..utils.logger import log_warning
    except ImportError:
        from src.utils.logger import log_warning
    try:
        w = widget.width()
        h = widget.height()
        min_w = widget.minimumWidth()
        min_h = widget.minimumHeight()
        max_w = widget.maximumWidth()
        max_h = widget.maximumHeight()
        info = (
            f"[DPI诊断][{tag}] size={w}x{h} min={min_w}x{min_h} max={max_w}x{max_h} "
            f"qtDPR={_qt_dpr(widget):.3f} monitorDpi={get_monitor_dpi(widget)} "
            f"windowDpi={get_native_dpi(widget)} screenLogDpi={_screen_logical_dpi(widget)} "
            f"visible={widget.isVisible()}"
        )
        log_warning(info)
    except Exception:
        pass


def is_dpi_mismatched(widget) -> bool:
    monitor_dpi = get_monitor_dpi(widget)
    screen_dpi = _screen_logical_dpi(widget)

    # 显示器真实 DPI（优先）或 Qt 屏幕 DPI 作为基准
    truth_dpi = monitor_dpi or screen_dpi
    if not truth_dpi:
        return False

    # 窗口级 DPI 与基准不一致（Windows 侧失同步）
    window_dpi = get_native_dpi(widget)
    if window_dpi and window_dpi != truth_dpi:
        return True

    # 窗口 DPI 正确但 Qt 缓存 DPR 未跟上（Qt 侧失同步）
    if abs(truth_dpi / 96.0 - _qt_dpr(widget)) > _DPR_EPS:
        return True

    return False


def _nudge(window) -> None:
    """原位微移 1px 再复位，触发 Qt 重新评估窗口所在屏幕与 DPR。

    同时用 Qt move 与原生 SetWindowPos 双路触发，覆盖不同失效场景；
    1px 位移在同一段同步代码内完成，肉眼不可见。
    """
    # 1) Qt 路径：move 会让 Qt 重新评估 screen/DPR（等同拖动窗口）
    try:
        pos = window.pos()
        window.move(pos.x() + 1, pos.y())
        window.move(pos.x(), pos.y())
    except Exception:
        pass

    # 2) 原生路径：SetWindowPos 触发 Windows 侧 DPI 重评估
    try:
        hwnd = int(window.winId())
        if hwnd:
            user32 = _user32()
            rect = _RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                SWP_NOSIZE = 0x0001
                SWP_NOZORDER = 0x0004
                SWP_NOACTIVATE = 0x0010
                flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
                user32.SetWindowPos(hwnd, 0, rect.left + 1, rect.top, 0, 0, flags)
                user32.SetWindowPos(hwnd, 0, rect.left, rect.top, 0, 0, flags)
    except Exception:
        pass


def sync_window_dpi(widget) -> bool:
    """若窗口 DPI 失同步则强制重新评估；返回是否执行了修复。"""
    if not is_supported():
        return False
    _diagnose(widget, "show")
    if not is_dpi_mismatched(widget):
        return False
    try:
        _nudge(widget)
        _diagnose(widget, "after-nudge")
        _reapply_intended(widget)
        refresh_layered_render(widget)
        return True
    except Exception:
        return False


def _nudge_if_dpi_mismatched(window) -> bool:
    """轻量版 DPI 检查：仅在确实失同步时 nudge，且只在真正修复时写日志。

    供尺寸守卫定时器周期调用，避免每次都写「show」诊断刷屏。
    """
    if not is_dpi_mismatched(window):
        return False
    try:
        _nudge(window)
        _diagnose(window, "nudge-dpr")
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


_REASSERT_INTERVAL_MS = 3000
_REASSERT_MAX_TICKS = 40  # 约 120 秒：覆盖显示器深度休眠唤醒后的异步重建窗口
_REASSERT_SHRINK_WINDOW_TICKS = 10  # 约 30 秒：仅在此窗口内纠正"无用户操作的骤缩"


def _guard_skip(window) -> bool:
    """这些状态下尺寸是"有意/动态"的，守卫与兜底一律不干预。"""
    try:
        if window.isMinimized() or window.isMaximized():
            return True
        if getattr(window, "_is_resizing", False):
            return True
        if getattr(window, "_is_streaming", False):
            return True
    except Exception:
        return True
    return False


def note_user_resize(window) -> None:
    """用户手动调整尺寸后调用：把意图/保护目标更新为用户新尺寸并停用棘轮守卫。

    守卫只该纠正"系统唤醒缩小"，不该与用户手动调整对抗；用户一旦手动调整，
    其尺寸即成为新的意图尺寸，守卫停止、屏幕变化兜底也按新目标判断。
    """
    try:
        size = (window.width(), window.height())
        window._intended_size = size
        window._reassert_target = size
    except Exception:
        pass
    _stop_guard(window)


def _reapply_intended(window) -> None:
    """DPI 重评估(nudge)后把尺寸恢复回意图尺寸，从源头消除唤醒"撑大/缩小"。

    仅对 opt-in 窗口（翻译窗）生效；流式/最大化/拖拽中不干预。
    """
    if not getattr(window, "_dpi_guard_opt_in", False):
        return
    if _guard_skip(window):
        return
    try:
        intended = getattr(window, "_intended_size", None)
        if not intended:
            return
        tw, th = intended
        if (window.width(), window.height()) != (tw, th):
            window.resize(max(tw, window.minimumWidth()), max(th, window.minimumHeight()))
    except Exception:
        pass


def refresh_layered_render(window) -> None:
    """唤醒/表面重建后强制重建 layered 窗的阴影 effect 渲染。

    锁屏唤醒时 Windows/DWM 重建 layered 表面，但不经过 Qt 的 hide/show，
    QGraphicsDropShadowEffect 的像素缓存对着新表面失效 → 阴影丢失。
    这里禁用→重启用 effect 强制整体重建，并 +1/-1px 尺寸抖动 + repaint 强制
    全量重绘（同 word_popup 的 workaround）。仅 opt-in 窗口；
    流式/最大化/拖拽中不干预；0.5s 节流避免同批信号重复抖动。
    """
    if not getattr(window, "_dpi_guard_opt_in", False):
        return
    if _guard_skip(window):
        return
    import time
    now = time.monotonic()
    if now - getattr(window, "_last_layered_refresh", 0.0) < 0.5:
        return
    try:
        window._last_layered_refresh = now
    except Exception:
        pass
    try:
        from PyQt6.QtCore import QTimer
        frame = getattr(window, "_content_frame", None)
        target = frame if frame is not None else window
        eff = target.graphicsEffect()
        if eff is not None:
            eff.setEnabled(False)
            eff.setEnabled(True)
        if window.isVisible() and not window.isMaximized():
            _h = window.height()
            window.resize(window.width(), _h + 1)
            window.resize(window.width(), _h)
            window.repaint()
            QTimer.singleShot(0, window.repaint)
    except Exception:
        pass


def reassert_after_show(window) -> None:
    """在窗口显示后持续重断言其尺寸，修复锁屏/显示器唤醒后被系统缩小的问题。

    背景：程序所有主窗口都是无边框 + `WA_TranslucentBackground`（Windows
    layered 窗口）。长时间锁屏（显示器进入深度休眠）后再唤醒，Windows / DWM
    有一个异步的显示重建过程，会把已显示的 layered 窗口缩小一圈（原生
    WM_SIZE 直接改尺寸，Qt 的 minimumSize 约束对原生 resize 不生效）。手动
    拖动边缘之所以能恢复，是因为拖动触发 Qt 重排并把它钳制到 minimumSize——
    但只是到最小值（如 450×660），而非默认值（500×660），所以用户感觉「还
    稍微小一点」。

    由于重建是异步、延迟且非必现的，只在 show 后一次性地检查不够；这里用一个
    低频定时器在显示后持续盯 2 分钟，一旦发现窗口尺寸小于显示时的尺寸（或小于
    minimumSize——这一定是异常，Qt 对 resize/拖动都强制最小值，只有原生
    WM_SIZE 能绕过），就恢复目标尺寸。仅在确实缩小时动作，正常情况（以及
    流式输出时窗口自动变大）是 no-op，无可见副作用。

    窗口显示时的尺寸由调用方在 `show()` 之前通过 `resize()` 设定，因此
    Show 事件触发时捕获到的即为目标尺寸。
    """
    if not is_supported():
        return
    try:
        from PyQt6.QtCore import QTimer
    except Exception:
        return
    try:
        # 优先用"意图尺寸"（记忆尺寸/预设/用户手动调整后的尺寸），
        # 不从唤醒后可能已被 DPI 重评估撑大/缩小的实时尺寸抓目标。
        intended = getattr(window, "_intended_size", None)
        if intended:
            target_w, target_h = intended
        else:
            target_w = window.width()
            target_h = window.height()
            window._intended_size = (target_w, target_h)
    except Exception:
        return
    if target_w <= 0 or target_h <= 0:
        return

    # 记录目标尺寸，供屏幕变化时的兜底恢复使用
    try:
        window._reassert_target = (target_w, target_h)
    except Exception:
        pass

    _stop_guard(window)

    state = {"ticks": 0}

    def _check() -> None:
        try:
            if not window.isVisible() or _guard_skip(window):
                return
            cur_w = window.width()
            cur_h = window.height()
            min_w = window.minimumWidth()
            min_h = window.minimumHeight()
            # 收窄纠正条件：小于 minimumSize 一定是异常（原生 WM_SIZE 绕过 Qt 约束）；
            # "小于目标"只在 show 后短窗口内纠正（唤醒骤缩），不再长期与用户对抗。
            shrink_anomaly = cur_w < min_w or cur_h < min_h
            recent_shrink = (
                state["ticks"] <= _REASSERT_SHRINK_WINDOW_TICKS
                and (cur_w < target_w or cur_h < target_h)
            )
            if shrink_anomaly or recent_shrink:
                fix_w = max(target_w, min_w)
                fix_h = max(target_h, min_h)
                _diagnose(window, f"reassert:{fix_w}x{fix_h}")
                window.resize(fix_w, fix_h)
            # DPR 失同步（Qt 缓存 DPR 与显示器不一致，如唤醒后回落 1.0）→ nudge 触发重评估
            if _nudge_if_dpi_mismatched(window):
                _reapply_intended(window)
                refresh_layered_render(window)
        except Exception:
            pass

    def _tick() -> None:
        try:
            state["ticks"] += 1
            if state["ticks"] > _REASSERT_MAX_TICKS:
                _stop_guard(window)
                return
            _check()
        except Exception:
            _stop_guard(window)

    timer = QTimer(window)
    timer.setInterval(_REASSERT_INTERVAL_MS)
    timer.timeout.connect(_tick)
    try:
        window._reassert_timer = timer
    except Exception:
        pass
    timer.start()
    _check()  # 立即检查一次，覆盖 show 后同步缩小的场景


def _stop_guard(window) -> None:
    """停止并释放窗口上挂的尺寸守卫定时器。"""
    try:
        t = getattr(window, "_reassert_timer", None)
        if t is not None:
            try:
                t.stop()
                t.deleteLater()
            except Exception:
                pass
            try:
                window._reassert_timer = None
            except Exception:
                pass
    except Exception:
        pass


def reassert_all_visible() -> int:
    """屏幕/显示变化后，对所有可见主窗口按记录的目标尺寸重断言；返回修复数。"""
    if not is_supported():
        return 0
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
    except Exception:
        return 0
    app = QApplication.instance()
    if app is None:
        return 0
    fixed = 0
    for w in app.topLevelWidgets():
        try:
            if not w.isVisible():
                continue
            if w.windowType() != Qt.WindowType.Window:
                continue
            if _guard_skip(w):
                continue
            target = getattr(w, "_reassert_target", None)
            if not target:
                continue
            tw, th = target
            cw, ch = w.width(), w.height()
            mw, mh = w.minimumWidth(), w.minimumHeight()
            # 目标已随用户手动调整更新（note_user_resize），故"小于目标"即系统骤缩；
            # 流式/最大化/拖拽中不干预。
            if cw < tw or ch < th or cw < mw or ch < mh:
                fw = max(tw, mw)
                fh = max(th, mh)
                _diagnose(w, f"reassert-all:{fw}x{fh}")
                w.resize(fw, fh)
                fixed += 1
            # 唤醒/屏幕变化即使尺寸未变，layered 表面也可能已重建 → 重建阴影渲染
            refresh_layered_render(w)
        except Exception:
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
        # 显示器 / DPI 变化可能连续多次，延迟一拍统一重同步 + 尺寸兜底
        QTimer.singleShot(0, sync_all_windows)
        QTimer.singleShot(0, reassert_all_visible)
    except Exception:
        pass
