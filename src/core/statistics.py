"""工作量统计 - 键盘敲击、鼠标移动距离、滚轮、左右键点击，按天统计。

实现要点：

- 全局监听用 pynput（keyboard.Listener + mouse.Listener），回调跑在 pynput 线程，
  只在一个线程锁保护下累加「今日实时计数」，不碰 Qt 对象。
- 主线程用一个 QTimer（每秒）检查是否跨天；跨天就把今日计数归档进历史、开启新一天。
  数据定期（约 5 分钟）落盘到 app_dir/statistics.json，按日期键存原始像素/次数。
- 鼠标移动距离是「估算」：系统只给像素位移，按常见 24~27 寸显示器取 25 寸对角线
  配合物理分辨率估算 PPI，再折算成实际距离（像素 / PPI * 2.54 = 厘米）；并按
  200ms 间隔采样、只累加两点间直线距离，避免高频采样把完整曲线路径算进去虚高。
- 距离按原始像素存储，展示时才换算，避免 DPI 变化导致历史数据失真。
"""
import json
import math
import threading
import time
from datetime import date
from typing import Dict, Optional

from PyQt6.QtCore import QObject, QTimer

try:
    from ..config import get_config
    from ..utils.logger import log_info, log_exception
except ImportError:
    from src.config import get_config
    from src.utils.logger import log_info, log_exception


def _system_dpi() -> int:
    """估算屏幕 PPI：按常见 24~27 寸显示器取 25 寸对角线，配合物理分辨率换算。

    之前用 EDID 上报的物理毫米数(HORZSIZE)换算，但不少显示器/驱动上报的尺寸不准，
    且混合缩放/多屏下更不可靠。按用户要求「屏幕大部分是 24~27 寸」，这里固定取
    25 寸对角线，用物理分辨率算对角线 PPI，结果稳定、量级合理。失败回退 96。
    """
    try:
        import ctypes
        LOGPIXELSX = 88
        DESKTOPHORZRES = 118
        DESKTOPVERTRES = 117
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        user32.GetDC.restype = ctypes.c_void_p
        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.GetDeviceCaps.restype = ctypes.c_int
        gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
        hdc = user32.GetDC(0)
        if not hdc:
            return 96
        try:
            w = gdi32.GetDeviceCaps(hdc, DESKTOPHORZRES)
            h = gdi32.GetDeviceCaps(hdc, DESKTOPVERTRES)
            if w > 0 and h > 0:
                diag_px = (w * w + h * h) ** 0.5
                ppi = diag_px / 25.0  # 25 寸对角线
                if 60 <= ppi <= 300:
                    return int(round(ppi))
            dpi = gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
            return int(dpi) if dpi else 96
        finally:
            user32.ReleaseDC(0, hdc)
    except Exception:
        return 96


class StatisticsTracker(QObject):
    """按天统计工作量，单例。"""

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._path = get_config().app_dir / "statistics.json"
        self._today = date.today().isoformat()
        self._days: Dict[str, dict] = {}
        self._live = self._new_counter()
        self._load()

        self._keyboard_listener = None
        self._mouse_listener = None
        self._pressed_keys = set()
        self._last_mouse_pos: Optional[tuple] = None
        self._last_sample_time = 0.0
        self._enabled = False
        self._tick_count = 0

        # 主线程定时器：跨天检查 + 定期落盘
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(1000)

    @staticmethod
    def _new_counter() -> dict:
        return {"key": 0, "distance_px": 0.0, "wheel": 0, "left": 0, "right": 0}

    # ---- 数据读写 ----
    def _load(self):
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._days = {k: v for k, v in raw.items() if isinstance(v, dict)}
            # 今日若已有历史记录（上次会话），继承到实时计数继续累加
            if self._today in self._days:
                saved = self._days.pop(self._today)
                with self._lock:
                    self._live = self._merge(self._new_counter(), saved)
        except Exception:
            log_exception("加载统计数据失败")
            self._days = {}

    @staticmethod
    def _merge(base: dict, extra: dict) -> dict:
        for k in base:
            if k not in extra:
                continue
            if k == "distance_px":
                base[k] = float(extra[k] or 0.0)
            else:
                try:
                    base[k] = int(extra[k] or 0)
                except (TypeError, ValueError):
                    base[k] = 0
        return base

    def _persist(self):
        try:
            with self._lock:
                snapshot = dict(self._days)
                snapshot[self._today] = dict(self._live)
            self._path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            log_exception("保存统计数据失败")

    def _on_tick(self):
        if not self._enabled:
            return
        today = date.today().isoformat()
        if today != self._today:
            old = self._today
            with self._lock:
                self._days[old] = dict(self._live)
                self._live = self._new_counter()
                self._today = today
            log_info(f"统计跨天：归档 {old}，开启 {today}")
            self._persist()
            return
        self._tick_count += 1
        if self._tick_count >= 300:
            self._tick_count = 0
            self._persist()

    # ---- 启用/停止 ----
    def set_enabled(self, enabled: bool):
        if enabled and not self._enabled:
            self._start_listeners()
        elif not enabled and self._enabled:
            self._stop_listeners()
        self._enabled = bool(enabled)
        if self._enabled:
            self._persist()

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def _start_listeners(self):
        try:
            from pynput import keyboard, mouse
        except Exception as e:
            log_info(f"导入 pynput 失败，无法统计: {e}")
            return
        try:
            self._keyboard_listener = keyboard.Listener(
                on_press=self._on_key_press, on_release=self._on_key_release)
            self._mouse_listener = mouse.Listener(
                on_move=self._on_mouse_move, on_scroll=self._on_mouse_scroll,
                on_click=self._on_mouse_click)
            self._keyboard_listener.start()
            self._mouse_listener.start()
            log_info("工作量统计已启动")
        except Exception:
            log_exception("启动统计监听失败")
            self._keyboard_listener = None
            self._mouse_listener = None

    def _stop_listeners(self):
        for lst in (self._keyboard_listener, self._mouse_listener):
            if lst is not None:
                try:
                    lst.stop()
                except Exception:
                    pass
        self._keyboard_listener = None
        self._mouse_listener = None
        self._pressed_keys.clear()
        self._last_mouse_pos = None
        log_info("工作量统计已停止")

    # ---- 监听回调（pynput 线程，仅累加计数，不碰 Qt） ----
    @staticmethod
    def _key_id(key):
        try:
            return getattr(key, 'vk', None) or getattr(key, 'char', None) or str(key)
        except Exception:
            return str(key)

    def _on_key_press(self, key):
        key_id = self._key_id(key)
        with self._lock:
            if key_id in self._pressed_keys:
                return  # 长按自动重复，不计
            self._pressed_keys.add(key_id)
            self._live["key"] += 1

    def _on_key_release(self, key):
        key_id = self._key_id(key)
        with self._lock:
            self._pressed_keys.discard(key_id)

    def _on_mouse_move(self, x, y):
        now = time.monotonic()
        with self._lock:
            if self._last_mouse_pos is None:
                self._last_mouse_pos = (x, y)
                self._last_sample_time = now
                return
            # 时间采样（200ms）：pynput 移动事件频率可达上千 Hz，逐像素累加会把
            # 曲线的完整路径都算进去导致虚高；按固定间隔采样、只累加两点间直线距离，
            # 才贴近「鼠标移动了多远」的直觉。
            if now - self._last_sample_time < 0.2:
                return
            lx, ly = self._last_mouse_pos
            dx = x - lx
            dy = y - ly
            self._last_mouse_pos = (x, y)
            self._last_sample_time = now
            # 超过阈值视为光标跳变（跨屏/系统定位），忽略本次距离
            if abs(dx) > 3000 or abs(dy) > 3000:
                return
            dist = math.hypot(dx, dy)
            # 最小阈值过滤静止时的 1~2px 抖动
            if dist >= 5.0:
                self._live["distance_px"] += dist

    def _on_mouse_scroll(self, x, y, dx, dy):
        with self._lock:
            self._live["wheel"] += abs(int(dx)) + abs(int(dy))

    def _on_mouse_click(self, x, y, button, pressed):
        if not pressed:
            return
        name = getattr(button, 'name', '')
        with self._lock:
            if name == 'left':
                self._live["left"] += 1
            elif name == 'right':
                self._live["right"] += 1

    # ---- 读取接口 ----
    def dpi(self) -> int:
        return _system_dpi()

    @staticmethod
    def px_to_cm(px: float, dpi: int) -> float:
        return px / max(dpi, 1) * 2.54

    def today_snapshot(self) -> dict:
        """今日实时数据（distance_cm 已换算，dpi 为当前换算基准）。"""
        with self._lock:
            live = dict(self._live)
        out = dict(live)
        out["distance_cm"] = self.px_to_cm(out.get("distance_px", 0.0), self.dpi())
        out["dpi"] = self.dpi()
        return out

    def history(self) -> list:
        """全部历史（含今日），按日期倒序，distance_cm 已换算。"""
        dpi = self.dpi()
        with self._lock:
            days = dict(self._days)
            days[self._today] = dict(self._live)
        result = []
        for d in sorted(days.keys(), reverse=True):
            row = dict(days[d])
            row["date"] = d
            row["distance_cm"] = self.px_to_cm(row.get("distance_px", 0.0), dpi)
            result.append(row)
        return result

    def clear_today(self):
        with self._lock:
            self._live = self._new_counter()
        self._persist()

    def stop(self):
        self._stop_listeners()
        self._tick.stop()
        self._persist()


_statistics_instance = None


def get_statistics_tracker() -> StatisticsTracker:
    """获取全局统计跟踪器实例。"""
    global _statistics_instance
    if _statistics_instance is None:
        _statistics_instance = StatisticsTracker()
    return _statistics_instance
