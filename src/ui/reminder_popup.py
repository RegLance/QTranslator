"""提醒悬浮窗 - 到点时在屏幕右下角弹出，无声音，点「知道了」关闭。

与自定义 Tooltip 不同：本窗口需要可点击（「知道了」按钮），因此不使用
WA_ShowWithoutActivating / WA_TransparentForMouseEvents；用 Tool + 置顶，
不抢前台焦点、不出现在任务栏，同时按钮可正常点击。超时自动关闭。
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGraphicsDropShadowEffect, QApplication,
)

try:
    from ..utils.theme import get_theme
except ImportError:
    from src.utils.theme import get_theme


class ReminderPopup(QWidget):
    """提醒悬浮窗（单例）。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._auto_close = QTimer(self)
        self._auto_close.setSingleShot(True)
        self._auto_close.timeout.connect(self.hide)

        self._setup_ui()

    def _setup_ui(self):
        theme = get_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._frame = QFrame()
        self._frame.setObjectName("reminderFrame")
        self._frame.setStyleSheet(f"""
            QFrame#reminderFrame {{
                background-color: {theme['bg_color']};
                border-radius: 10px;
                border: 1px solid {theme['border_color']};
            }}
        """)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(*theme['shadow_color']))
        shadow.setOffset(0, 4)
        self._frame.setGraphicsEffect(shadow)
        layout.addWidget(self._frame)

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(18, 16, 18, 14)
        frame_layout.setSpacing(12)

        # 标题
        title = QLabel("⏰ 提醒")
        title.setStyleSheet(f"""
            QLabel {{
                color: {theme['accent_color']};
                font-size: 13px;
                font-weight: bold;
            }}
        """)
        frame_layout.addWidget(title)

        # 内容
        self._message_label = QLabel()
        self._message_label.setWordWrap(True)
        self._message_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_primary']};
                font-size: 14px;
                line-height: 1.5;
            }}
        """)
        self._message_label.setMinimumWidth(220)
        frame_layout.addWidget(self._message_label)

        # 知道了按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QPushButton("知道了")
        self._ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ok_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['accent_color']};
                color: #ffffff;
                border: none;
                border-radius: 5px;
                padding: 6px 18px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {theme['accent_hover']}; }}
        """)
        self._ok_btn.clicked.connect(self.hide)
        btn_layout.addWidget(self._ok_btn)
        frame_layout.addLayout(btn_layout)

    def _apply_theme(self):
        theme = get_theme()
        self._frame.setStyleSheet(f"""
            QFrame#reminderFrame {{
                background-color: {theme['bg_color']};
                border-radius: 10px;
                border: 1px solid {theme['border_color']};
            }}
        """)

    def show_message(self, message: str):
        """显示提醒内容（替换内容、更新主题、定位到右下角并弹出）。"""
        self._apply_theme()
        self._message_label.setText(message)
        self.adjustSize()

        # 定位到主屏右下角
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            margin = 24
            x = geo.right() - self.width() - margin
            y = geo.bottom() - self.height() - margin
            self.move(x, y)

        self.show()
        self.raise_()
        # 自动关闭（无声音，靠视觉提醒）
        self._auto_close.start(20000)


_reminder_popup_instance = None


def show_reminder_popup(message: str):
    """弹出提醒悬浮窗。"""
    global _reminder_popup_instance
    if _reminder_popup_instance is None:
        _reminder_popup_instance = ReminderPopup()
    _reminder_popup_instance.show_message(message)
