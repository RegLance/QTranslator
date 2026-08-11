"""窗口置顶策略工具。

策略（用户定义）：
- 「始终置顶」设置只控制翻译窗口（翻译窗口按设置持有 WindowStaysOnTopHint）
- 其他窗口：正在使用（激活）的窗口置顶；鼠标/键盘切到其他窗口时立即降级。
  激活状态由 WindowActivate / WindowDeactivate 事件维持，
  不做延时释放，避免可见的"闪一下"。
"""
import sys

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QWidget


def _set_topmost(widget: QWidget, on: bool) -> None:
    """Win32 下切换窗口置顶状态；非 Windows 平台为空操作。

    降级（on=False）时插到「当前前台窗口」（刚被点击的窗口）之下，
    效果等同普通窗口：降级窗口被点中的目标窗口挡住，而不是钉在
    非置顶带顶端继续盖住别人。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # 必须声明 argtypes：否则 64 位句柄按 32 位截断，SetWindowPos 静默失效
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        hwnd = int(widget.winId())
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
        if on:
            insert_after = -1  # HWND_TOPMOST
        else:
            # 必须声明 restype：否则 64 位句柄被截成 int，
            # 比较与插入位置都会出错
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            fg = user32.GetForegroundWindow()
            insert_after = fg if (fg and fg != hwnd) else -2
        user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        pass


class _ActivationTopMostFilter(QObject):
    """激活时置顶、失活时降级"""

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.WindowActivate:
            _set_topmost(obj, True)
        elif et == QEvent.Type.WindowDeactivate:
            _set_topmost(obj, False)
        return super().eventFilter(obj, event)


def install_activation_topmost(widget: QWidget) -> None:
    """让窗口"用时置顶、切走降级"。重复调用安全（只安装一次）。"""
    if getattr(widget, "_activation_topmost_filter", None) is not None:
        return
    f = _ActivationTopMostFilter(widget)
    widget._activation_topmost_filter = f  # 持有引用防止被 GC
    widget.installEventFilter(f)


def bring_to_front_once(widget: QWidget) -> None:
    """唤醒窗口到最前：raise/激活 + 立即置顶。

    置顶状态由 install_activation_topmost 的激活/失活事件持续维持，
    这里不做延时释放（避免可见的"闪一下"）。
    """
    widget.raise_()
    widget.activateWindow()
    _set_topmost(widget, True)
