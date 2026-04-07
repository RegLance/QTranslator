"""翻译图标按钮组件 - Translate Copilot

优化：解决与网站原生悬浮窗冲突的问题
- 添加延迟显示机制，等待网站悬浮窗消失
- 添加鼠标静止检测，避免在网站交互期间显示
- 更智能的防抖逻辑
"""
import sys
import math
import time
from typing import Optional, Tuple
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QCursor

try:
    from ..config import get_config
    from ..core.text_capture import is_browser_program
except ImportError:
    from config import get_config
    from core.text_capture import is_browser_program


# 按钮尺寸（18px）
BUTTON_SIZE = 18

# 鼠标离开按钮多少像素后自动隐藏（使用逻辑坐标）
HIDE_DISTANCE_THRESHOLD = 50

# 延迟显示时间（毫秒）- 等待网站原生悬浮窗消失
SHOW_DELAY_MS = 300

# 鼠标静止检测时间（毫秒）
MOUSE_STILL_THRESHOLD_MS = 150

# 鼠标移动阈值（像素）- 超过此距离认为鼠标在移动
MOUSE_MOVE_THRESHOLD = 5


class TranslateButton(QWidget):
    """翻译图标按钮

    选中文本后显示的小图标，点击后触发翻译。
    显示 "T" 字符代表 Translate。

    特性：
    - 小巧的圆形图标按钮
    - 跟随选区/鼠标位置显示
    - 延迟显示，避免与网站原生悬浮窗冲突
    - 鼠标静止检测，确保用户体验
    - 点击触发翻译
    - 鼠标距离按钮一定距离后自动隐藏
    """

    # 信号
    clicked = pyqtSignal()
    hidden = pyqtSignal()

    def __init__(self):
        super().__init__()

        config = get_config()
        self._auto_hide_delay = 5000

        self._selected_text: str = ""
        self._auto_hide_timer: Optional[QTimer] = None
        self._mouse_check_timer: Optional[QTimer] = None  # 定时检查鼠标距离
        self._is_just_shown: bool = False  # 刚显示的短暂时间内不检测距离

        # 延迟显示相关
        self._show_delay_timer: Optional[QTimer] = None  # 延迟显示计时器
        self._pending_show_pos: Optional[Tuple[int, int]] = None  # 待显示的位置
        self._pending_text: str = ""  # 待显示的文本

        # 鼠标静止检测相关
        self._mouse_still_timer: Optional[QTimer] = None  # 鼠标静止检测计时器
        self._last_mouse_pos: Optional[Tuple[int, int]] = None  # 上次鼠标位置
        self._last_mouse_time: float = 0  # 上次鼠标检测时间

        # 注意：必须先设置窗口属性，再创建 UI 子控件
        # 否则 setWindowFlags 会销毁已创建的窗口状态，导致首次显示问题
        self._setup_window_properties()
        self._setup_ui()
        self._setup_auto_hide_timer()
        self._setup_mouse_check_timer()
        self._setup_delay_timers()

    def _setup_window_properties(self):
        """设置窗口属性"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)  # 显示但不激活
        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)

        # 确保窗口在初始化时就被创建，避免首次显示问题
        self.create()
        # 强制获取窗口ID，确保底层窗口句柄已创建完成
        # create() 只是准备创建，winId() 才真正触发底层创建
        _ = self.winId()

    def _setup_ui(self):
        """设置 UI"""
        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        pixmap = self._create_icon()
        self._icon_label.setPixmap(pixmap)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._icon_label)

        self.setMouseTracking(True)

    def _create_icon(self) -> QPixmap:
        """创建翻译图标 - 显示 "T" 字符（半透明背景）"""
        pixmap = QPixmap(BUTTON_SIZE, BUTTON_SIZE)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制圆形背景（半透明蓝色，透明度约50%）
        painter.setBrush(QColor(0, 120, 212, 128))  # 半透明蓝色
        painter.setPen(Qt.PenStyle.NoPen)  # 无边框
        painter.drawEllipse(0, 0, BUTTON_SIZE, BUTTON_SIZE)

        # 绘制 "T" 字符
        painter.setPen(QColor(255, 255, 255, 230))  # 半透明白色
        font = QFont("Arial", 10, QFont.Weight.Bold)  # 10px字体在18px按钮中合适
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "T")

        painter.end()

        return pixmap

    def _setup_auto_hide_timer(self):
        """设置自动隐藏计时器"""
        self._auto_hide_timer = QTimer()
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._on_auto_hide)

    def _setup_mouse_check_timer(self):
        """设置鼠标距离检测定时器"""
        self._mouse_check_timer = QTimer()
        self._mouse_check_timer.setInterval(100)  # 每100ms检查一次
        self._mouse_check_timer.timeout.connect(self._check_mouse_distance)

    def _setup_delay_timers(self):
        """设置延迟显示和鼠标静止检测计时器"""
        # 延迟显示计时器 - 等待网站原生悬浮窗消失
        self._show_delay_timer = QTimer()
        self._show_delay_timer.setSingleShot(True)
        self._show_delay_timer.timeout.connect(self._do_delayed_show)

        # 鼠标静止检测计时器
        self._mouse_still_timer = QTimer()
        self._mouse_still_timer.setInterval(50)  # 每50ms检测一次
        self._mouse_still_timer.timeout.connect(self._check_mouse_still)

    def _check_mouse_distance(self):
        """检查鼠标距离，如果离按钮太远则隐藏"""
        if self._is_just_shown or not self.isVisible():
            return

        # 获取鼠标当前位置（逻辑坐标）
        cursor_pos = QCursor.pos()
        mouse_x, mouse_y = cursor_pos.x(), cursor_pos.y()

        # 获取按钮的几何区域
        button_x = self.x()
        button_y = self.y()
        button_w = self.width()
        button_h = self.height()

        # 计算鼠标到按钮中心的距离
        center_x = button_x + button_w // 2
        center_y = button_y + button_h // 2
        distance = math.sqrt((mouse_x - center_x) ** 2 + (mouse_y - center_y) ** 2)

        # 检查鼠标是否在按钮区域附近
        # 如果距离超过阈值，则隐藏按钮
        if distance > HIDE_DISTANCE_THRESHOLD:
            # 额外检查：鼠标不在按钮内部
            if not (button_x <= mouse_x <= button_x + button_w and
                    button_y <= mouse_y <= button_y + button_h):
                self.hide()
                return

        # 重置自动隐藏计时器
        self._auto_hide_timer.stop()
        self._auto_hide_timer.start(self._auto_hide_delay)

    def _check_mouse_still(self):
        """检测鼠标是否静止 - 用于判断网站悬浮窗是否消失"""
        cursor_pos = QCursor.pos()
        current_pos = (cursor_pos.x(), cursor_pos.y())
        current_time = time.time()

        if self._last_mouse_pos is not None:
            # 计算鼠标移动距离
            dx = current_pos[0] - self._last_mouse_pos[0]
            dy = current_pos[1] - self._last_mouse_pos[1]
            distance = math.sqrt(dx * dx + dy * dy)

            # 如果鼠标移动超过阈值，重置计时
            if distance > MOUSE_MOVE_THRESHOLD:
                self._last_mouse_time = current_time
                self._last_mouse_pos = current_pos
                return

        # 检查鼠标是否静止足够长时间
        if self._last_mouse_time > 0:
            still_duration = (current_time - self._last_mouse_time) * 1000  # 转换为毫秒
            if still_duration >= MOUSE_STILL_THRESHOLD_MS:
                # 鼠标已静止足够长时间，可以显示按钮
                self._mouse_still_timer.stop()
                self._do_show_after_still()

        self._last_mouse_pos = current_pos

    def _do_show_after_still(self):
        """鼠标静止后执行延迟显示"""
        if self._pending_show_pos is None:
            return

        # 启动延迟显示计时器
        self._show_delay_timer.start(SHOW_DELAY_MS)

    def _do_delayed_show(self):
        """延迟显示 - 在网站原生悬浮窗消失后显示"""
        if self._pending_show_pos is None:
            return

        x, y = self._pending_show_pos
        self._selected_text = self._pending_text

        # 计算显示位置（鼠标右下方）
        new_x = x + 8
        new_y = y + 8

        # 获取当前鼠标位置，更新基准点
        cursor_pos = QCursor.pos()
        mouse_x, mouse_y = cursor_pos.x(), cursor_pos.y()

        # 确保不超出屏幕边界
        try:
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.availableVirtualGeometry()
                # 如果右边超出，放到左边
                if new_x + BUTTON_SIZE > screen_geo.x() + screen_geo.width():
                    new_x = mouse_x - BUTTON_SIZE - 8
                # 如果下边超出，放到上边
                if new_y + BUTTON_SIZE > screen_geo.y() + screen_geo.height():
                    new_y = mouse_y - BUTTON_SIZE - 8
                # 确保不超出左边
                if new_x < screen_geo.x():
                    new_x = screen_geo.x() + 5
                # 确保不超出上边
                if new_y < screen_geo.y():
                    new_y = screen_geo.y() + 5
        except Exception:
            pass

        # 如果当前可见，先隐藏再显示（确保窗口状态正确）
        if self.isVisible():
            super().hide()

        self.move(new_x, new_y)
        self._is_just_shown = True

        # 确保窗口已创建
        if not self.winId():
            self.create()

        # 使用 show() 和 raise_() 确保窗口显示并置顶
        self.show()
        self.raise_()

        # 强制刷新窗口
        self.repaint()
        QApplication.processEvents()

        # 启动鼠标距离检测
        self._mouse_check_timer.start()

        # 启动自动隐藏计时器
        self._auto_hide_timer.start(self._auto_hide_delay)

        # 500ms 后重置刚显示状态，开始检测距离
        QTimer.singleShot(500, self._reset_just_shown)

        # 清除待显示状态
        self._pending_show_pos = None
        self._pending_text = ""

    def show_at_position(self, pos: Optional[Tuple[int, int]], selected_text: str = "", program_name: str = ""):
        """在指定位置显示图标按钮 - 根据环境智能选择显示方式

        在浏览器环境中使用延迟显示（避免与网站原生悬浮窗冲突）
        在其他环境中立即显示（避免用户体验问题）

        Args:
            pos: 显示位置，None 则使用鼠标当前位置
            selected_text: 选中的文本
            program_name: 来源程序名（用于判断是否是浏览器）
        """
        # 判断是否是浏览器环境
        is_browser = is_browser_program(program_name)

        if pos is None:
            cursor_pos = QCursor.pos()
            x, y = cursor_pos.x(), cursor_pos.y()
        else:
            x, y = pos

        if is_browser:
            # 浏览器环境：使用延迟显示
            self._show_with_delay(x, y, selected_text)
        else:
            # 非浏览器环境：立即显示
            self._do_immediate_show(x, y, selected_text)

    def _do_immediate_show(self, x: int, y: int, selected_text: str):
        """立即显示图标按钮"""
        self._selected_text = selected_text

        # 计算显示位置（鼠标右下方）
        new_x = x + 8
        new_y = y + 8

        # 确保不超出屏幕边界
        try:
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.availableVirtualGeometry()
                if new_x + BUTTON_SIZE > screen_geo.x() + screen_geo.width():
                    new_x = x - BUTTON_SIZE - 8
                if new_y + BUTTON_SIZE > screen_geo.y() + screen_geo.height():
                    new_y = y - BUTTON_SIZE - 8
                if new_x < screen_geo.x():
                    new_x = screen_geo.x() + 5
                if new_y < screen_geo.y():
                    new_y = screen_geo.y() + 5
        except Exception:
            pass

        # 如果当前可见，先隐藏再显示
        if self.isVisible():
            super().hide()

        self.move(new_x, new_y)
        self._is_just_shown = True

        # 确保窗口已创建
        if not self.winId():
            self.create()

        self.show()
        self.raise_()

        # 强制刷新窗口
        self.repaint()
        QApplication.processEvents()

        # 启动鼠标距离检测
        self._mouse_check_timer.start()

        # 启动自动隐藏计时器
        self._auto_hide_timer.start(self._auto_hide_delay)

        # 500ms 后重置刚显示状态，开始检测距离
        QTimer.singleShot(500, self._reset_just_shown)

    def _show_with_delay(self, x: int, y: int, selected_text: str):
        """浏览器环境下的延迟显示逻辑

        流程：
        1. 保存待显示的位置和文本
        2. 等待一段延迟时间（让网站悬浮窗消失）
        3. 显示T图标
        """
        # 保存待显示的信息
        self._pending_show_pos = (x, y)
        self._pending_text = selected_text

        # 停止之前的计时器
        self._show_delay_timer.stop()

        # 直接启动延迟显示计时器（简化逻辑，移除鼠标静止检测）
        self._show_delay_timer.start(SHOW_DELAY_MS + MOUSE_STILL_THRESHOLD_MS)

    def show_at_position_immediate(self, pos: Optional[Tuple[int, int]], selected_text: str = ""):
        """立即显示图标按钮（不经过延迟检测）

        用于兼容某些不需要延迟的场景
        """
        if pos is None:
            cursor_pos = QCursor.pos()
            x, y = cursor_pos.x(), cursor_pos.y()
        else:
            x, y = pos

        self._selected_text = selected_text

        # 计算显示位置（鼠标右下方）
        new_x = x + 8
        new_y = y + 8

        # 确保不超出屏幕边界
        try:
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.availableVirtualGeometry()
                # 如果右边超出，放到左边
                if new_x + BUTTON_SIZE > screen_geo.x() + screen_geo.width():
                    new_x = x - BUTTON_SIZE - 8
                # 如果下边超出，放到上边
                if new_y + BUTTON_SIZE > screen_geo.y() + screen_geo.height():
                    new_y = y - BUTTON_SIZE - 8
                # 确保不超出左边
                if new_x < screen_geo.x():
                    new_x = screen_geo.x() + 5
                # 确保不超出上边
                if new_y < screen_geo.y():
                    new_y = screen_geo.y() + 5
        except Exception:
            pass

        # 先隐藏确保重置状态（仅在可见时）
        if self.isVisible():
            super().hide()

        self.move(new_x, new_y)
        self._is_just_shown = True

        # 使用 show() 和 raise_() 确保窗口显示并置顶
        self.show()
        self.raise_()
        self.activateWindow()

        # 强制更新窗口
        self.update()

        # 启动鼠标距离检测
        self._mouse_check_timer.start()

        # 启动自动隐藏计时器
        self._auto_hide_timer.start(self._auto_hide_delay)

        # 500ms 后重置刚显示状态，开始检测距离
        QTimer.singleShot(500, self._reset_just_shown)

    def get_selected_text(self) -> str:
        """获取保存的选中文本"""
        return self._selected_text

    def set_selected_text(self, text: str):
        """设置选中的文本"""
        self._selected_text = text

    def hide(self):
        """隐藏按钮"""
        self._auto_hide_timer.stop()
        self._mouse_check_timer.stop()
        self._show_delay_timer.stop()  # 停止延迟显示
        self._mouse_still_timer.stop()  # 停止鼠标静止检测
        self._selected_text = ""
        self._pending_show_pos = None  # 清除待显示状态
        self._pending_text = ""
        self._last_mouse_pos = None  # 重置鼠标位置记录
        self._last_mouse_time = 0
        super().hide()
        self.hidden.emit()

    def _on_auto_hide(self):
        """自动隐藏"""
        self.hide()

    def enterEvent(self, event):
        """鼠标进入 - 暂停自动隐藏"""
        self._auto_hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开 - 重启自动隐藏"""
        if self._is_just_shown:
            super().leaveEvent(event)
            return
        # 离开按钮后设置一个较短的超时后隐藏
        self._auto_hide_timer.start(1000)
        super().leaveEvent(event)

    def _reset_just_shown(self):
        """重置刚显示状态"""
        self._is_just_shown = False

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            self.hide()
        super().mousePressEvent(event)


# 全局实例
_button_instance: Optional[TranslateButton] = None


def get_translate_button() -> TranslateButton:
    """获取全局翻译按钮实例"""
    global _button_instance
    if _button_instance is None:
        _button_instance = TranslateButton()
    return _button_instance