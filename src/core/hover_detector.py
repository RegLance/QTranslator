"""鼠标悬停检测模块 - 性能优化版

关键优化：
1. 钩子回调中避免任何阻塞操作
2. 使用队列将事件处理延迟到工作线程
3. 添加暂停标志，在UI重操作时快速跳过处理
4. 定期重启鼠标监听器，防止长时间运行导致钩子失效
5. 检测系统休眠/锁屏恢复，自动重建钩子
"""
import time
import threading
from typing import Optional, Callable, Tuple
from dataclasses import dataclass
import sys
from pathlib import Path
from collections import deque
from pynput import mouse
from PyQt6.QtCore import QTimer, QObject, pyqtSignal, QMetaObject, Qt

try:
    from ..config import get_config
    from ..utils.logger import log_info, log_error, log_debug
except ImportError:
    from src.config import get_config
    from src.utils.logger import log_info, log_error, log_debug


@dataclass
class MousePosition:
    """鼠标位置信息"""
    x: int
    y: int
    timestamp: float


# 定期重启间隔（毫秒）- 每 2 小时重启一次鼠标监听器
LISTENER_RESTART_INTERVAL_MS = 2 * 60 * 60 * 1000

# 健康检查间隔（毫秒）- 每 5 分钟检查一次
HEALTH_CHECK_INTERVAL_MS = 5 * 60 * 1000

# 系统恢复检测阈值（秒）- 超过此时间没有鼠标事件则认为系统可能休眠过
SYSTEM_RESUME_THRESHOLD_SEC = 300


class HoverDetector(QObject):
    """鼠标悬停检测器 - 性能优化版

    检测用户选中文本后鼠标悬停的事件。

    性能优化要点：
    1. 钩子回调只做轻量操作（坐标记录、队列写入）
    2. 使用处理计时器在工作线程处理重操作
    3. 提供 pause/resume 接口，在UI重操作期间暂停处理
    4. 定期重启鼠标监听器，防止长时间运行后钩子劣化
    5. 检测系统休眠/锁屏恢复，自动重建钩子
    """

    # 信号定义
    hover_triggered = pyqtSignal()  # 悬停触发信号
    selection_detected = pyqtSignal()  # 选择检测信号

    def __init__(self):
        """初始化悬停检测器"""
        super().__init__()

        self._mouse_listener: Optional[mouse.Listener] = None
        self._hover_timer: Optional[QTimer] = None
        self._last_position: Optional[MousePosition] = None
        self._is_enabled = True
        self._is_hovering = False

        # 暂停标志 - 在UI重操作期间设置为True，让钩子回调快速跳过
        self._is_paused = False

        # 加载配置（在初始化时一次性加载，避免在钩子回调中读取）
        self._delay_ms = get_config().get('hover.delay_ms', 300)
        self._area_padding = get_config().get('hover.area_padding', 15)

        # 最后一次鼠标事件时间（用于健康检查和系统恢复检测）
        self._last_event_time: float = time.time()

        # 重启锁 - 防止并发重启
        self._restart_lock = threading.Lock()

        # 初始化计时器
        self._init_timer()

        # 健康检查计时器
        self._health_check_timer = QTimer()
        self._health_check_timer.timeout.connect(self._health_check)

        # 定期重启计时器
        self._restart_timer = QTimer()
        self._restart_timer.timeout.connect(self._scheduled_restart)

    def _init_timer(self):
        """初始化悬停计时器"""
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_hover_timeout)

    def start(self):
        """启动检测"""
        if self._mouse_listener is not None:
            return

        self._start_listener()

        # 启动健康检查（每 5 分钟）
        self._health_check_timer.start(HEALTH_CHECK_INTERVAL_MS)

        # 启动定期重启（每 2 小时）
        self._restart_timer.start(LISTENER_RESTART_INTERVAL_MS)

        log_info("悬停检测器已启动（含健康检查和定期重启）")

    def _start_listener(self):
        """启动鼠标监听器"""
        if self._mouse_listener is not None:
            return

        try:
            self._mouse_listener = mouse.Listener(
                on_release=self._on_mouse_release,
                on_move=self._on_mouse_move
            )
            self._mouse_listener.start()
            self._last_event_time = time.time()
        except Exception as e:
            log_error(f"启动鼠标监听器失败: {e}")

    def _stop_listener(self):
        """停止鼠标监听器"""
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

    def stop(self):
        """停止检测"""
        self._health_check_timer.stop()
        self._restart_timer.stop()

        self._stop_listener()

        if self._hover_timer is not None:
            self._hover_timer.stop()

        log_info("悬停检测器已停止")

    def pause(self):
        """暂停检测（在UI重操作期间调用）

        这会让钩子回调快速返回，避免因主线程繁忙导致超时
        """
        self._is_paused = True
        if self._hover_timer:
            self._hover_timer.stop()
        self._is_hovering = False

    def resume(self):
        """恢复检测"""
        self._is_paused = False

    def set_enabled(self, enabled: bool):
        """设置是否启用检测"""
        self._is_enabled = enabled
        if not enabled:
            self._hover_timer.stop()
            self._is_hovering = False

    def set_delay(self, delay_ms: int):
        """设置悬停延迟时间"""
        self._delay_ms = delay_ms

    def _on_mouse_release(self, button, x, y):
        """鼠标释放事件处理 - 钩子回调，必须快速返回"""
        # 更新事件时间（始终更新，用于健康检查）
        self._last_event_time = time.time()

        # 快速检查：如果暂停或禁用，立即返回
        if self._is_paused or not self._is_enabled:
            return

        # 只处理左键释放
        if button != mouse.Button.left:
            return

        # 记录位置（轻量操作）
        self._last_position = MousePosition(x=x, y=y, timestamp=time.time())
        self._is_hovering = True

        # 使用 Qt 的线程安全方式发送信号
        # QMetaObject.invokeMethod 确保在主线程执行
        try:
            QMetaObject.invokeMethod(
                self,
                "_emit_selection_detected",
                Qt.ConnectionType.QueuedConnection
            )
        except Exception:
            pass

        # 启动悬停计时器（线程安全）
        try:
            QMetaObject.invokeMethod(
                self,
                "_start_hover_timer",
                Qt.ConnectionType.QueuedConnection
            )
        except Exception:
            pass

    def _on_mouse_move(self, x, y):
        """鼠标移动事件处理 - 钩子回调，必须快速返回"""
        # 更新事件时间（始终更新，用于健康检查）
        self._last_event_time = time.time()

        # 快速检查：如果暂停、禁用或不在悬停状态，立即返回
        if self._is_paused or not self._is_enabled or not self._is_hovering:
            return

        # 检查是否移动超出允许区域
        if self._last_position is not None:
            dx = abs(x - self._last_position.x)
            dy = abs(y - self._last_position.y)

            # 如果移动超出阈值，取消悬停
            if dx > self._area_padding or dy > self._area_padding:
                self._is_hovering = False
                # 使用线程安全方式停止计时器
                try:
                    QMetaObject.invokeMethod(
                        self,
                        "_stop_hover_timer",
                        Qt.ConnectionType.QueuedConnection
                    )
                except Exception:
                    pass

    # --- 线程安全的槽方法 ---
    def _emit_selection_detected(self):
        """在主线程中发送选择检测信号"""
        self.selection_detected.emit()

    def _start_hover_timer(self):
        """在主线程中启动悬停计时器"""
        if self._hover_timer and self._is_hovering:
            self._hover_timer.start(self._delay_ms)

    def _stop_hover_timer(self):
        """在主线程中停止悬停计时器"""
        if self._hover_timer:
            self._hover_timer.stop()

    def _on_hover_timeout(self):
        """悬停时间到达处理"""
        if not self._is_enabled or self._is_paused:
            return

        self._is_hovering = False
        self.hover_triggered.emit()

    def _health_check(self):
        """健康检查 - 检测系统休眠恢复后钩子是否失效

        当系统从休眠恢复时，Windows 低级鼠标钩子可能被系统移除。
        通过检测长时间无鼠标事件来判断是否需要重建钩子。

        注意：锁屏期间也会出现长时间无鼠标事件，但锁屏时重启无意义，
        所以通过 OpenInputDesktop 判断是否处于锁屏状态来跳过。
        锁屏→解锁的恢复由 MainController._on_session_restored 统一处理。
        """
        current_time = time.time()
        time_gap = current_time - self._last_event_time

        if time_gap > SYSTEM_RESUME_THRESHOLD_SEC:
            # 检查是否处于锁屏状态（Windows），锁屏期间跳过重启
            if sys.platform == 'win32':
                try:
                    import ctypes
                    hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0001)
                    if not hdesk:
                        # 锁屏中，更新时间戳避免反复触发，跳过重启
                        self._last_event_time = current_time
                        return
                    ctypes.windll.user32.CloseDesktop(hdesk)
                except Exception:
                    pass

            log_info(f"检测到 {time_gap:.0f} 秒无鼠标事件，桌面已解锁，重启鼠标监听器")
            self._restart_listener()

    def _scheduled_restart(self):
        """定期重启鼠标监听器 - 防止长时间运行后性能劣化"""
        log_debug("定期重启鼠标监听器")
        self._restart_listener()

    def _restart_listener(self):
        """重启鼠标监听器（线程安全）"""
        if not self._restart_lock.acquire(blocking=False):
            return  # 已有重启在进行中

        try:
            self._is_hovering = False
            self._stop_listener()
            self._start_listener()
            log_info("鼠标监听器已重启")
        except Exception as e:
            log_error(f"重启鼠标监听器失败: {e}")
        finally:
            self._restart_lock.release()

    def get_last_position(self) -> Optional[Tuple[int, int]]:
        """获取最后一次鼠标位置"""
        if self._last_position is not None:
            return (self._last_position.x, self._last_position.y)
        return None

    def cleanup(self):
        """清理资源"""
        self.stop()


# 全局悬停检测器实例
_detector_instance: Optional[HoverDetector] = None


def get_hover_detector() -> HoverDetector:
    """获取全局悬停检测器实例"""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = HoverDetector()
    return _detector_instance
