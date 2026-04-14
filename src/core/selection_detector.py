"""选择检测模块 - 监听文本选择事件

优化：
- 检测系统休眠/锁屏恢复，避免锁屏期间无效轮询
- 恢复后重置状态，防止事件堆积
"""
import sys
import time
from typing import Optional, Tuple
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

try:
    from ..config import get_config, APP_NAME
    from ..utils.logger import log_info, log_debug
except ImportError:
    from src.config import get_config, APP_NAME
    from src.utils.logger import log_info, log_debug


@dataclass
class MousePosition:
    x: int
    y: int
    timestamp: float


class SelectionDetector(QObject):
    """选择检测器 - 通过监听 text_capture 的选择事件来驱动

    工作流程：
    1. text_capture (selection-hook) 实时监听全局文本选择
    2. 当检测到新选择时，通过轮询检查更新
    3. 检查是否在应用自己的窗口中选择，如果是则忽略
    4. 发出 selection_finished 信号
    """

    selection_finished = pyqtSignal()
    selection_cleared = pyqtSignal()

    def __init__(self):
        super().__init__()

        self._last_position: Optional[MousePosition] = None
        self._is_enabled = True
        self._is_paused = False  # 暂停标志

        # 上一次捕获的时间戳，用于检测新选择
        self._last_capture_time = 0.0

        # 上一次轮询的实际时间 - 用于检测系统休眠/恢复
        self._last_poll_wall_time: float = time.time()

        # 轮询定时器 - 检查是否有新的选择
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_interval = 50  # 50ms 检查一次

        # 文本捕获引用（延迟获取）
        self._text_capture = None

    def pause(self):
        """暂停检测"""
        self._is_paused = True

    def resume(self):
        """恢复检测"""
        self._is_paused = False

    def _get_text_capture(self):
        """延迟获取 text_capture 实例"""
        if self._text_capture is None:
            try:
                from .text_capture import get_text_capture
                self._text_capture = get_text_capture()
            except ImportError:
                from src.core.text_capture import get_text_capture
                self._text_capture = get_text_capture()
        return self._text_capture

    def _is_own_window_active(self) -> bool:
        """检查当前活动窗口是否是应用自己的窗口
        
        如果用户在我们的翻译窗口、历史窗口或设置窗口中选择文本，
        不应该触发翻译按钮。
        """
        try:
            # 获取应用程序的所有顶层窗口
            app = QApplication.instance()
            if not app:
                return False
            
            # 获取当前活动窗口（前台窗口）
            for widget in app.topLevelWidgets():
                if widget.isVisible() and widget.isActiveWindow():
                    # 如果有我们的窗口是活动的，忽略选择
                    widget_name = widget.objectName() or widget.__class__.__name__
                    # 检查是否是我们的窗口
                    if widget_name in ['TranslatorWindow', 'HistoryWindow', 'SettingsDialog', 
                                       'PopupWindow', 'TranslatorWindow']:
                        return True
                    # 也检查类名
                    if 'TranslatorWindow' in str(type(widget)) or \
                       'HistoryWindow' in str(type(widget)) or \
                       'SettingsDialog' in str(type(widget)) or \
                       'PopupWindow' in str(type(widget)):
                        return True
            
            # 使用 Windows API 检查前台窗口是否是应用自己的窗口
            # 注意：不再使用窗口标题判断，因为会导致误判（如 PyCharm 打开 QTranslator 项目）
            if sys.platform == 'win32':
                try:
                    import ctypes
                    hwnd = ctypes.windll.user32.GetForegroundWindow()
                    if hwnd:
                        # 获取窗口类名来判断是否是我们的 PyQt 窗口
                        # PyQt6 窗口类名通常包含 "Qt6" 或 "QWidget"
                        class_name_buffer = ctypes.create_unicode_buffer(256)
                        ctypes.windll.user32.GetClassNameW(hwnd, class_name_buffer, 256)
                        class_name = class_name_buffer.value

                        # 检查是否是 Qt 窗口类（我们的应用窗口）
                        # PyQt6 主窗口类名通常是 "Qt6QWindowIcon" 或类似
                        if class_name and ('Qt6' in class_name or 'QWidget' in class_name):
                            # 进一步检查：获取窗口进程ID，确认是否是我们自己的进程
                            process_id = ctypes.c_ulong()
                            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                            current_pid = ctypes.windll.kernel32.GetCurrentProcessId()
                            # 只有进程ID也匹配，才是我们自己的窗口
                            if process_id.value == current_pid:
                                return True
                except Exception:
                    pass
                    
        except Exception:
            pass
        
        return False

    def start(self):
        """启动检测"""
        if self._poll_timer.isActive():
            return

        # 确保 text_capture 服务已启动
        tc = self._get_text_capture()
        if tc:
            # 等待服务就绪
            timeout = 5.0
            start = time.time()
            while not tc.is_ready() and time.time() - start < timeout:
                time.sleep(0.1)

            if tc.is_ready():
                print("[INFO] Selection detector started (selection-hook mode)", file=sys.stderr)
            else:
                print("[WARN] Selection service not ready, using fallback mode", file=sys.stderr)

        self._poll_timer.start(self._poll_interval)

    def stop(self):
        """停止检测"""
        self._poll_timer.stop()
        print("[INFO] Selection detector stopped", file=sys.stderr)

    def set_enabled(self, enabled: bool):
        self._is_enabled = enabled

    def _on_poll(self):
        """轮询检查是否有新的文本选择"""
        current_wall_time = time.time()

        # 检测系统休眠/锁屏恢复：如果两次轮询间隔远超预期，说明系统经历了休眠
        # 正常间隔约 50ms，超过 60 秒说明系统刚恢复
        wall_gap = current_wall_time - self._last_poll_wall_time
        self._last_poll_wall_time = current_wall_time

        if wall_gap > 60:
            # 系统刚从休眠/锁屏恢复，丢弃休眠期间积累的旧选择事件
            log_info(f"检测到系统恢复（轮询间隔 {wall_gap:.0f} 秒），重置选择检测状态")
            tc = self._get_text_capture()
            if tc:
                self._last_capture_time = tc.get_last_capture_time()
            return

        if not self._is_enabled or self._is_paused:
            return

        # 检查是否在我们自己的窗口中选择
        if self._is_own_window_active():
            return

        tc = self._get_text_capture()
        if not tc:
            return

        # 检查是否有新选择
        if tc.has_new_selection(self._last_capture_time):
            # 更新时间戳
            self._last_capture_time = tc.get_last_capture_time()

            # 获取选择位置
            info = tc.capture()
            x, y = 0, 0
            if info.bounds:
                x, y, _, _ = info.bounds

            # 如果位置无效（都是0），使用当前鼠标位置
            if x == 0 and y == 0:
                cursor_pos = QCursor.pos()
                x, y = cursor_pos.x(), cursor_pos.y()

            self._last_position = MousePosition(x=x, y=y, timestamp=self._last_capture_time)

            # 发出信号
            self.selection_finished.emit()

    def get_last_position(self) -> Optional[Tuple[int, int]]:
        if self._last_position:
            return (self._last_position.x, self._last_position.y)
        return None

    def cleanup(self):
        self.stop()


# 全局实例
_detector_instance: Optional[SelectionDetector] = None


def get_selection_detector() -> SelectionDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = SelectionDetector()
    return _detector_instance