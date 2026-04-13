"""鼠标悬停检测模块 - 性能优化版

关键优化：
1. 钩子回调中避免任何阻塞操作
2. 使用队列将事件处理延迟到工作线程
3. 添加暂停标志，在UI重操作时快速跳过处理
4. 定期健康检查，自动恢复被系统卸载的鼠标钩子
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
except ImportError:
    from src.config import get_config


@dataclass
class MousePosition:
    """鼠标位置信息"""
    x: int
    y: int
    timestamp: float


class HoverDetector(QObject):
    """鼠标悬停检测器 - 性能优化版

    检测用户选中文本后鼠标悬停的事件。

    性能优化要点：
    1. 钩子回调只做轻量操作（坐标记录、队列写入）
    2. 使用处理计时器在工作线程处理重操作
    3. 提供 pause/resume 接口，在UI重操作期间暂停处理
    4. 定期健康检查，检测钩子是否被系统卸载并自动恢复
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

        # 钩子健康检查相关
        self._last_hook_activity_time: float = 0.0  # 钩子最后一次活动时间
        self._health_check_timer: Optional[QTimer] = None
        # 如果超过此时间（秒）没有收到任何鼠标事件，认为钩子已失效
        self._hook_timeout_seconds: float = 30.0
        self._restart_count: int = 0  # 重启计数，用于日志追踪

        # 初始化计时器
        self._init_timer()

    def _init_timer(self):
        """初始化悬停计时器"""
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_hover_timeout)

        # 健康检查计时器：每 15 秒检查一次钩子是否还在工作
        self._health_check_timer = QTimer()
        self._health_check_timer.setInterval(15000)
        self._health_check_timer.timeout.connect(self._check_hook_health)

    def start(self):
        """启动检测"""
        if self._mouse_listener is not None:
            return

        self._start_listener()
        # 启动健康检查
        self._health_check_timer.start()
        print("悬停检测器已启动")

    def _start_listener(self):
        """启动鼠标监听器（内部方法，支持重启）"""
        # 确保旧的监听器已清理
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

        self._last_hook_activity_time = time.time()
        self._mouse_listener = mouse.Listener(
            on_release=self._on_mouse_release,
            on_move=self._on_mouse_move
        )
        self._mouse_listener.daemon = True
        self._mouse_listener.start()

    def _check_hook_health(self):
        """定期检查鼠标钩子是否仍然有效

        Windows 在以下情况会自动卸载低级鼠标钩子：
        1. 钩子回调超时（默认 LowLevelHooksTimeout = 1000ms）
        2. 锁屏/解锁导致桌面切换
        3. UAC 提权对话框弹出

        检测方法：如果长时间没有收到任何鼠标事件，说明钩子可能已失效。
        """
        if not self._is_enabled or self._is_paused:
            # 暂停状态下不检查，但更新活动时间避免误判
            self._last_hook_activity_time = time.time()
            return

        elapsed = time.time() - self._last_hook_activity_time
        if elapsed > self._hook_timeout_seconds:
            self._restart_count += 1
            print(f"[警告] 鼠标钩子可能已失效（{elapsed:.0f}秒无活动），"
                  f"正在重新安装... (第{self._restart_count}次重启)")
            self._start_listener()

        # 同时检查 listener 线程是否还活着
        if self._mouse_listener is not None and not self._mouse_listener.is_alive():
            self._restart_count += 1
            print(f"[警告] 鼠标监听线程已终止，正在重启... (第{self._restart_count}次重启)")
            self._start_listener()

    def stop(self):
        """停止检测"""
        if self._health_check_timer is not None:
            self._health_check_timer.stop()

        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None

        if self._hover_timer is not None:
            self._hover_timer.stop()

        print("悬停检测器已停止")

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
        # 更新钩子活动时间（证明钩子仍然工作）
        self._last_hook_activity_time = time.time()

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
        # 更新钩子活动时间（证明钩子仍然工作）
        self._last_hook_activity_time = time.time()

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