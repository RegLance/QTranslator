"""划词悬浮工具栏 - QTranslator

类似豆包 / Cherry Studio 的划词工具栏：选中文本后在光标附近弹出横条，
提供 翻译 / 润色 / 总结 / AI对话 四个内置功能（始终显示），
并支持 actions/ 目录下用户自写的 .py 扩展（设置中勾选后显示）。

窗口为无边框置顶工具窗口，不抢占焦点（WA_ShowWithoutActivating），
鼠标移出后自动隐藏。
"""
import math
import os
import sys
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QPushButton, QFrame,
)

try:
    from ..config import get_config, APP_NAME
    from ..utils.logger import log_debug
    from ..utils.theme import get_theme
    from ..core.custom_actions import get_custom_action_manager, CustomAction
    from .translate_button import BUTTON_SIZE, HIDE_DISTANCE_THRESHOLD
except ImportError:
    from src.config import get_config, APP_NAME
    from src.utils.logger import log_debug
    from src.utils.theme import get_theme
    from src.core.custom_actions import get_custom_action_manager, CustomAction
    from src.ui.translate_button import BUTTON_SIZE, HIDE_DISTANCE_THRESHOLD

TOOLBAR_HEIGHT = 34          # 工具栏高度（逻辑像素）
MOUSE_CHECK_INTERVAL_MS = 100   # 鼠标距离检测间隔，与翻译图标按钮一致
JUST_SHOWN_GRACE_MS = 500    # 刚弹出时的保护期，不做距离检测

# 翻译图标按钮的消失规则：距中心超 HIDE_DISTANCE_THRESHOLD(50) 逻辑像素隐藏，
# 按钮半径 BUTTON_SIZE/2 = 12，等效于边缘外 38px。工具栏是宽矩形，改用
# 鼠标到矩形（实时宽高决定）边缘的距离计算，取同样的 38px 边缘余量，手感一致。
HIDE_EDGE_THRESHOLD = HIDE_DISTANCE_THRESHOLD - BUTTON_SIZE // 2


class SelectionToolbar(QWidget):
    """划词悬浮工具栏"""

    translate_requested = pyqtSignal()        # 翻译
    polish_requested = pyqtSignal()           # 润色
    summarize_requested = pyqtSignal()        # 总结
    chat_requested = pyqtSignal(str)          # AI 对话（携带选中文本）
    action_requested = pyqtSignal(object)     # actions/ 目录 .py 扩展（CustomAction 对象）

    def __init__(self):
        super().__init__()
        self.setObjectName("SelectionToolbar")

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(TOOLBAR_HEIGHT)

        self._config = get_config()
        self._selected_text = ""

        # 容器（圆角背景）：无边距，避免工具栏四周出现透明框
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._bar = QFrame()
        self._bar.setObjectName("toolbarBar")
        outer.addWidget(self._bar)

        self._row = QHBoxLayout(self._bar)
        self._row.setContentsMargins(6, 4, 6, 4)
        self._row.setSpacing(2)

        # 鼠标距离检测定时器：离工具栏边缘超过余量自动隐藏（与翻译按钮一致）
        self._mouse_check_timer = QTimer(self)
        self._mouse_check_timer.setInterval(MOUSE_CHECK_INTERVAL_MS)
        self._mouse_check_timer.timeout.connect(self._check_mouse_distance)
        self._is_just_shown = False

        # 全局点击检测：点击工具栏以外的地方即隐藏
        self._click_check_timer = QTimer(self)
        self._click_check_timer.timeout.connect(self._check_outside_click)
        self._click_check_timer.start(300)

        self._apply_theme()

        # 主题切换时立即刷新（否则切主题后工具栏仍是旧样式）
        try:
            from ..utils.theme import get_theme_manager
        except ImportError:
            from src.utils.theme import get_theme_manager
        get_theme_manager().theme_changed.connect(self._apply_theme)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def _apply_theme(self):
        theme = get_theme(self._config.get('theme.popup_style', 'dark'))
        self._theme = theme
        bg = theme['bg_color']
        border = theme['border_color']
        text1 = theme['text_primary']
        accent = theme['accent_color']
        accent_hover = theme['accent_hover']

        self._bar.setStyleSheet(f"""
            #toolbarBar {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)
        self._btn_style = f"""
            QPushButton {{
                background: transparent; color: {text1}; border: none;
                border-radius: 5px; padding: 3px 9px; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {accent}; color: #ffffff; }}
            QPushButton:pressed {{ background-color: {accent_hover}; color: #ffffff; }}
        """

    # ------------------------------------------------------------------
    # 按钮构建
    # ------------------------------------------------------------------
    def _clear_row(self):
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _make_button(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(self._btn_style)
        btn.clicked.connect(slot)
        return btn

    def _rebuild(self):
        """每次弹出时重建按钮行（actions/ 扩展可能已变化）"""
        self._clear_row()
        self._apply_theme()

        # 内置四功能（始终显示）
        self._row.addWidget(self._make_button("🌐 翻译", self._on_translate))
        self._row.addWidget(self._make_button("✨ 润色", self._on_polish))
        self._row.addWidget(self._make_button("📝 总结", self._on_summarize))
        self._row.addWidget(self._make_button("💬 AI对话", self._on_chat))

        # actions/ 目录 .py 扩展：默认不显示，在设置中勾选后才出现
        try:
            all_actions = get_custom_action_manager().load_actions()
        except Exception:
            all_actions = []
        enabled_map = self._config.get('selection.custom_actions', {}) or {}
        actions = [
            a for a in all_actions
            if enabled_map.get(os.path.basename(a.file_path))
        ]
        if actions:
            self._row.addWidget(self._make_separator())
            for action in actions[:6]:  # 最多显示 6 个，避免工具栏过长
                label = f"{action.icon} {action.name}".strip()
                btn = self._make_button(label, lambda checked=False, a=action: self._on_action(a))
                btn.setToolTip(f"自定义功能：{action.file_path}")
                self._row.addWidget(btn)

        self._row.addStretch()
        self.adjustSize()

    def _make_separator(self) -> QFrame:
        line = QFrame()
        line.setObjectName("toolbarDivider")
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
        line.setStyleSheet(
            f"#toolbarDivider {{ background-color: {self._theme['border_color']}; border: none; }}")
        return line

    # ------------------------------------------------------------------
    # 显示 / 隐藏
    # ------------------------------------------------------------------
    def show_at_position(self, pos: Tuple[int, int], selected_text: str):
        """在划词位置附近弹出工具栏"""
        self._selected_text = selected_text or ""
        self._rebuild()

        # 定位以当前鼠标为准：QCursor.pos() 返回逻辑像素，与 move() 同一坐标系。
        # 传入的 pos 可能来自 selection-hook（物理像素），在高 DPI（应用为
        # per-monitor DPI-aware）下直接混用会明显偏移到下方/右侧。
        try:
            cursor = QCursor.pos()
            x, y = cursor.x(), cursor.y()
        except Exception:
            x, y = pos

        # 定位：鼠标右下方（右 10px、下 8px），空间不足则翻转到左侧/上方，并夹紧到屏幕内
        win_w, win_h = self.width(), self.height()
        try:
            screen = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
            geo = screen.availableGeometry()
        except Exception:
            geo = None

        if geo is not None:
            new_x = x + 10
            new_y = y + 8
            if new_y + win_h > geo.bottom() - 6:
                new_y = y - win_h - 8
            if new_x + win_w > geo.right() - 6:
                new_x = x - win_w - 10
            new_x = max(geo.left() + 6, min(new_x, geo.right() - win_w - 6))
            new_y = max(geo.top() + 6, min(new_y, geo.bottom() - win_h - 6))
        else:
            new_x, new_y = x + 10, y + 8

        self.move(new_x, new_y)
        self.show()
        self.raise_()
        self._is_just_shown = True
        QTimer.singleShot(JUST_SHOWN_GRACE_MS, self._reset_just_shown)
        self._mouse_check_timer.start()
        log_debug(f"划词工具栏弹出于 ({new_x}, {new_y})")

    def set_selected_text(self, text: str):
        self._selected_text = text or ""

    def get_selected_text(self) -> str:
        return self._selected_text

    def hide_toolbar(self):
        self._hide_now()

    def _hide_now(self):
        if self.isVisible():
            self._mouse_check_timer.stop()
            self.hide()

    # ------------------------------------------------------------------
    # 自动隐藏
    # ------------------------------------------------------------------
    def _reset_just_shown(self):
        self._is_just_shown = False

    def _check_mouse_distance(self):
        """鼠标离工具栏边缘超 HIDE_EDGE_THRESHOLD 自动隐藏（与翻译按钮同手感）

        翻译按钮以「距中心 > 50 逻辑像素」为隐藏阈值；工具栏是宽矩形，
        改为计算鼠标到矩形（实时宽高）的直线距离：矩形内为 0，
        矩形外为到最近边/角的距离。
        """
        if self._is_just_shown or not self.isVisible():
            return
        if QApplication.activePopupWidget() is not None:
            return  # 弹出菜单打开时不隐藏
        rect = self.frameGeometry()
        pos = QCursor.pos()
        dx = max(rect.left() - pos.x(), 0, pos.x() - rect.right())
        dy = max(rect.top() - pos.y(), 0, pos.y() - rect.bottom())
        if math.hypot(dx, dy) > HIDE_EDGE_THRESHOLD:
            self._hide_now()

    def _check_outside_click(self):
        """鼠标在工具栏之外按下左键 → 隐藏（点别处即消失）"""
        if not self.isVisible():
            return
        try:
            import ctypes
            VK_LBUTTON = 0x01
            if not (ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                return
            pos = QCursor.pos()
            margin = 4
            rect = self.frameGeometry().adjusted(-margin, -margin, margin, margin)
            if not rect.contains(pos) and QApplication.activePopupWidget() is None:
                self._hide_now()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 按钮回调
    # ------------------------------------------------------------------
    def _on_translate(self):
        self._hide_now()
        self.translate_requested.emit()

    def _on_polish(self):
        self._hide_now()
        self.polish_requested.emit()

    def _on_summarize(self):
        self._hide_now()
        self.summarize_requested.emit()

    def _on_chat(self):
        self._hide_now()
        self.chat_requested.emit(self._selected_text)

    def _on_action(self, action: CustomAction):
        self._hide_now()
        self.action_requested.emit(action)


# 全局实例
_toolbar_instance: Optional[SelectionToolbar] = None


def get_selection_toolbar() -> SelectionToolbar:
    global _toolbar_instance
    if _toolbar_instance is None:
        _toolbar_instance = SelectionToolbar()
    return _toolbar_instance
