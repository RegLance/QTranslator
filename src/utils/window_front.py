"""窗口前置策略工具：统一的「用时置顶、切走降级」。

适用于所有非翻译功能窗口（设置对话框 / 历史记录 / 单词收藏 / 帮助 /
单词弹窗 / AI 对话等）：

- 唤醒/唤起（bring_to_front_once）：raise + activateWindow，再用 Win32
  SetWindowPos(HWND_TOPMOST) 突破 Windows 前台锁定、可靠把窗口拉到最前并获取焦点。
  随后按翻译窗口的置顶状态分两种情况：
  · 翻译窗口未开启「始终置顶」→ 立即 SetWindowPos(HWND_NOTOPMOST) 降回普通窗口，
    不常驻置顶；
  · 翻译窗口开启了「始终置顶」（处于置顶带）→ 保持置顶带、不立即降级，让本窗口
    停留在翻译窗口上方（Win32 中普通带窗口永远盖不过置顶带窗口，此时若立即降级会
    掉到翻译窗口下方），待失焦时由下面的事件过滤器降级，翻译窗口随之自然回到顶层。
- 失去焦点（install_activation_topmost 安装的事件过滤器）：WindowDeactivate
  时，若窗口仍处在置顶带则降级为普通窗口；已是普通窗口则不做任何操作
  （避免 HWND_NOTOPMOST 把它重新插到普通带顶端、反而盖住刚激活的目标窗口）。
- 全程不设置 Qt.WindowType.WindowStaysOnTopHint。

例外（不使用本模块，各自保留 WindowStaysOnTopHint）：
- 翻译窗口：常驻置顶由 translator_window 的 always_on_top 用户设置独立控制。
- 划词工具栏 / 自定义 Tooltip / Toast / 启动画面：均为不抢焦点或即时展示的
  悬浮 UI（WindowDoesNotAcceptFocus / WA_ShowWithoutActivating / Tool），
  需要盖在其他应用之上才有意义，与「获取前台焦点后降级」策略天然不适用。
"""
import sys

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QMessageBox, QWidget

# Win32 常量
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008


def _user32():
    """取 user32 并声明原型：64 位下句柄必须按指针宽度传递，否则被截断成
    32 位会导致 SetWindowPos / GetWindowLongW 静默失效。"""
    import ctypes
    u = ctypes.windll.user32
    u.SetWindowPos.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.GetWindowLongW.restype = ctypes.c_long
    return u


def _set_topmost(widget: QWidget, on: bool) -> None:
    """Win32 下切换窗口置顶状态；非 Windows 平台为空操作。"""
    if sys.platform != "win32":
        return
    try:
        u = _user32()
        hwnd = int(widget.winId())
        insert_after = _HWND_TOPMOST if on else _HWND_NOTOPMOST
        u.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0,
                       _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
    except Exception:
        pass


def _is_topmost(widget: QWidget) -> bool:
    """窗口当前是否处于置顶带（扩展样式含 WS_EX_TOPMOST）；非 Windows 返回 False。"""
    if sys.platform != "win32":
        return False
    try:
        u = _user32()
        hwnd = int(widget.winId())
        return bool(u.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOPMOST)
    except Exception:
        return False


def _demote_if_topmost(widget: QWidget) -> None:
    """仅当窗口仍在置顶带时才降级为普通窗口。

    已是普通窗口则不做任何 SetWindowPos：否则 HWND_NOTOPMOST 会把它重新插到
    普通带顶端，反而盖住刚被点击激活的目标窗口（正是"切不走"的时序竞态根源）。
    """
    was_topmost = _is_topmost(widget)
    if was_topmost:
        _set_topmost(widget, False)


def _translator_always_on_top() -> bool:
    """翻译窗口是否开启了「始终置顶」（处于 Win32 置顶带）。

    开启时，被唤醒的功能窗口必须保持置顶带才能停留在翻译窗口上方——普通带窗口
    永远盖不过置顶带窗口。读取用户配置 translator_window.always_on_top
    （translator_window 依此决定是否加 WindowStaysOnTopHint）；读取失败按未开启
    处理，退回「立即降级」的保守行为。
    """
    try:
        from ..config import get_config
    except ImportError:
        from src.config import get_config
    try:
        val = bool(get_config().get('translator_window.always_on_top', False))
        return val
    except Exception:
        return False


class _ActivationTopMostFilter(QObject):
    """失焦即降级：窗口失去激活时确保退出置顶带，允许被其他正常窗口覆盖。

    激活时不做常驻置顶——唤起时的置顶由 bring_to_front_once 负责。当翻译窗口
    常驻置顶时，被唤醒窗口会保持置顶带以停留在其上方，正是靠本过滤器在失焦时把它
    降级、让翻译窗口自然回到顶层。（旧实现在 WindowActivate 时设为常驻 TOPMOST，
    会让窗口一直盖住别人、切不走；此处只保留失活降级，从根上消除该问题。）
    """

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.WindowDeactivate:
            # 模态消息框打开期间不降级：消息框是设置窗口的 owned window，Windows
            # 会让 owned window 跟随 owner 的 z 序——此时降级设置窗口会把消息框
            # 一并拖出置顶带，导致它被「始终置顶」的翻译窗口盖住、应用锁死。
            if getattr(obj, "_modal_box_active", False):
                return super().eventFilter(obj, event)
            _demote_if_topmost(obj)
        return super().eventFilter(obj, event)


def install_activation_topmost(widget: QWidget) -> None:
    """安装「失焦降级」过滤器，让窗口切走后不常驻置顶。重复调用安全（只装一次）。"""
    if getattr(widget, "_activation_topmost_filter", None) is not None:
        return
    f = _ActivationTopMostFilter(widget)
    widget._activation_topmost_filter = f  # 持有引用防止被 GC
    widget.installEventFilter(f)


def bring_to_front_once(widget: QWidget) -> None:
    """唤醒窗口到前台：raise/激活 + Win32 置顶抢前台，按翻译窗口置顶状态决定是否立即降级。

    HWND_TOPMOST 用于突破 Windows 前台锁定、可靠获取前台焦点，并能临时盖过处于
    置顶带的窗口。随后：
    - 翻译窗口未「始终置顶」→ 立即切回 HWND_NOTOPMOST 成为普通窗口（不常驻置顶），
      切到其他应用时可被正常覆盖；
    - 翻译窗口「始终置顶」→ 保持置顶带、不立即降级，让本窗口停留在翻译窗口上方
      （普通带窗口永远盖不过置顶带窗口，此时立即降级会掉到翻译窗口下方）；待本窗口
      失焦时由 install_activation_topmost 的过滤器降级，翻译窗口随之自然回到顶层。
    """
    widget.raise_()
    widget.activateWindow()
    _set_topmost(widget, True)   # 抢前台：强制拉到最前（含盖过常驻置顶的翻译窗口）
    if not _translator_always_on_top():
        _set_topmost(widget, False)  # 无置顶冲突：立即降级为普通窗口，不常驻置顶


def show_modal_message_box(
    parent: QWidget,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> int:
    """显示置顶模态消息框，返回 exec() 的点击结果。

    从设置对话框等「用时置顶」窗口弹出的模态框必须临时进入置顶带：否则翻译窗口
    开启「始终置顶」时，消息框落在普通带、被翻译窗口盖住，用户看不到提示、又因
    应用级模态无法操作任何窗口，整个应用被锁死（设置窗口失焦降级后掉到翻译窗口
    下方，翻译窗口随之盖住消息框）。

    消息框关闭后，父窗口已被降级到普通带；这里再把它拉回前台（翻译窗口常驻置顶
    时 bring_to_front_once 会重新放回置顶带），否则父窗口会留在翻译窗口下方。
    """
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    if default_button != QMessageBox.StandardButton.NoButton:
        box.setDefaultButton(default_button)
    # 常驻置顶：Qt 标志 + Win32 双重保证消息框停留在置顶带，避免被翻译窗口盖住
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    box.show()
    box.raise_()
    box.activateWindow()
    # 进入置顶带：确保盖过「始终置顶」的翻译窗口（show 之后 winId 才有效）
    _set_topmost(box, True)

    # 模态打开期间标记父窗口：其失焦降级会把 owned 的消息框一并拖出置顶带，
    # 这里让过滤器跳过降级，保持父窗口（连同消息框）停留在置顶带
    if parent is not None:
        parent._modal_box_active = True
    try:
        result = box.exec()
    finally:
        if parent is not None:
            parent._modal_box_active = False
    box.deleteLater()

    if parent is not None:
        bring_to_front_once(parent)
    return result
