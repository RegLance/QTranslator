"""提醒管理器 - 管理多条提醒，按各自调度弹出提醒悬浮窗。

支持模式：
- interval：每隔 N 分钟
- once：指定日期时间，一次性（触发后记录 last_fired，重启不重复弹）
- daily：每天固定时间
- weekly：每周固定星期与时间
- monthly：每月固定日期与时间

用一个 1 秒周期的 QTimer 在主线程轮询各提醒的到期时间（比较墙钟），到点弹悬浮窗，
无需跨线程。配置由 reminder_window 保存后调用 configure() 生效；main 启动时按配置恢复。
"""
import calendar
from datetime import datetime, timedelta

from PyQt6.QtCore import QObject, QTimer

try:
    from ..utils.logger import log_info
    from ..config import get_config
except ImportError:
    from src.utils.logger import log_info
    from src.config import get_config


WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _parse_time(s):
    """解析 'HH:MM' 返回 (hour, minute)，失败返回 (9, 0)。"""
    try:
        hh, mm = str(s).split(':')
        return int(hh), int(mm)
    except (ValueError, AttributeError):
        return 9, 0


def _next_monthly(now: datetime, day: int, hour: int, minute: int) -> datetime:
    """计算「每月 day 号 hour:minute」的下一次触发时间（自动处理 2 月 30/31 号等）。"""
    def _candidate(y, m):
        last = calendar.monthrange(y, m)[1]
        return datetime(y, m, min(day, last), hour, minute)

    year, month = now.year, now.month
    candidate = _candidate(year, month)
    if candidate <= now:
        month += 1
        if month > 12:
            month = 1
            year += 1
        candidate = _candidate(year, month)
    return candidate


def compute_next_fire(item: dict, now: datetime = None):
    """计算某条提醒的下次触发时间；无（未启用/无内容/一次性已触发）返回 None。"""
    if now is None:
        now = datetime.now()
    message = (item.get('message') or '').strip()
    if not message:
        return None

    mode = item.get('mode', 'interval')
    try:
        if mode == 'interval':
            try:
                minutes = max(1, int(item.get('interval_minutes', 30)))
            except (TypeError, ValueError):
                minutes = 30
            return now + timedelta(minutes=minutes)

        if mode == 'once':
            dt_str = item.get('datetime') or ''
            scheduled = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            # 已触发过则不再触发（保留条目，用户编辑时间后会重置）
            if item.get('last_fired') == dt_str:
                return None
            return scheduled

        if mode == 'daily':
            hh, mm = _parse_time(item.get('time', '09:00'))
            candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate

        if mode == 'weekly':
            hh, mm = _parse_time(item.get('time', '09:00'))
            weekday = int(item.get('weekday', 0)) % 7
            days_ahead = (weekday - now.weekday()) % 7
            candidate = (now + timedelta(days=days_ahead)).replace(
                hour=hh, minute=mm, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=7)
            return candidate

        if mode == 'monthly':
            hh, mm = _parse_time(item.get('time', '09:00'))
            day = max(1, min(31, int(item.get('day', 1))))
            return _next_monthly(now, day, hh, mm)
    except (ValueError, TypeError):
        return None
    return None


class ReminderManager(QObject):
    """多条提醒调度器：统一用一个 1 秒轮询计时器检查到期。"""

    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._items = []       # 原始提醒配置列表
        self._next_fires = []  # 与 items 对齐的下次触发时间（datetime 或 None）

    def configure(self, items):
        """应用整份提醒列表。"""
        self._items = [dict(i) for i in (items or [])]
        self._reschedule()
        log_info(f"提醒配置: 共 {len(self._items)} 条")

    def _reschedule(self):
        now = datetime.now()
        self._next_fires = [
            compute_next_fire(i, now) if i.get('enabled') else None
            for i in self._items
        ]
        self._restart_timer()

    def _restart_timer(self):
        has_work = any(nf is not None for nf in self._next_fires)
        if has_work and not self._timer.isActive():
            self._timer.start(1000)
        elif not has_work:
            self._timer.stop()

    def _tick(self):
        now = datetime.now()
        once_fired = False
        for idx, item in enumerate(self._items):
            nf = self._next_fires[idx]
            if nf is None or not item.get('enabled'):
                continue
            if now < nf:
                continue

            self._fire(item)

            if item.get('mode') == 'once':
                item['last_fired'] = item.get('datetime')
                self._next_fires[idx] = None
                once_fired = True
            else:
                self._next_fires[idx] = compute_next_fire(item, now)

        if once_fired:
            self._persist_once_state()
        self._restart_timer()

    def _fire(self, item):
        message = (item.get('message') or '').strip()
        if not message:
            return
        try:
            from ..ui.reminder_popup import show_reminder_popup
        except ImportError:
            from src.ui.reminder_popup import show_reminder_popup
        show_reminder_popup(message)

    def _persist_once_state(self):
        """一次性提醒触发后把 last_fired 写回配置，避免重启后重复弹。"""
        try:
            cfg = get_config()
            cfg.set('reminder.items', self._items)
            cfg.save()
        except Exception:
            pass

    def stop(self):
        self._timer.stop()


_reminder_instance = None


def get_reminder_manager() -> ReminderManager:
    """获取全局提醒管理器实例。"""
    global _reminder_instance
    if _reminder_instance is None:
        _reminder_instance = ReminderManager()
    return _reminder_instance
