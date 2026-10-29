"""提醒管理器 - 按周期弹出提醒悬浮窗。

计时器跑在 Qt 主线程（QTimer），到点后直接在主线程显示悬浮窗，无需跨线程。
配置由 reminder_window 保存后调用 configure() 生效；main 启动时按配置恢复。
"""
from PyQt6.QtCore import QObject, QTimer

try:
    from ..utils.logger import log_info
except ImportError:
    from src.utils.logger import log_info


class ReminderManager(QObject):
    """周期提醒：启用后每隔 interval_minutes 分钟弹一次悬浮窗。"""

    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timeout)
        self._enabled = False
        self._interval_minutes = 30
        self._message = ""

    def configure(self, enabled: bool, interval_minutes, message: str):
        """应用提醒配置：启用状态 / 周期（分钟）/ 内容。"""
        self._enabled = bool(enabled)
        try:
            self._interval_minutes = max(1, int(interval_minutes or 30))
        except (TypeError, ValueError):
            self._interval_minutes = 30
        self._message = (message or "").strip()
        self._restart_timer()
        log_info(f"提醒配置: 启用={self._enabled}, 每 {self._interval_minutes} 分钟, "
                 f"内容={self._message!r}")

    def _restart_timer(self):
        self._timer.stop()
        if self._enabled and self._message:
            self._timer.start(self._interval_minutes * 60 * 1000)

    def _on_timeout(self):
        if not self._message:
            return
        try:
            from ..ui.reminder_popup import show_reminder_popup
        except ImportError:
            from src.ui.reminder_popup import show_reminder_popup
        show_reminder_popup(self._message)

    def stop(self):
        self._timer.stop()


_reminder_instance = None


def get_reminder_manager() -> ReminderManager:
    """获取全局提醒管理器实例。"""
    global _reminder_instance
    if _reminder_instance is None:
        _reminder_instance = ReminderManager()
    return _reminder_instance
