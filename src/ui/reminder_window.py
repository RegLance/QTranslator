"""提醒设置窗口 - 设置提醒周期、预设内容与自定义内容。"""
from typing import Optional

from PyQt6.QtCore import Qt, QPoint, QRect, QPointF
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGraphicsDropShadowEffect, QCheckBox, QSpinBox, QComboBox, QLineEdit,
    QApplication,
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QPen, QBrush, QPolygonF

try:
    from ..config import get_config
    from ..utils.theme import get_theme, get_theme_manager, get_checkbox_style
except ImportError:
    from src.config import get_config
    from src.utils.theme import get_theme, get_theme_manager, get_checkbox_style


# 预置提醒内容
PRESETS = {
    "喝水提醒": "该喝水啦，起来接杯水休息一下吧～",
    "久坐提醒": "久坐伤身，站起来活动一下筋骨吧～",
    "护眼提醒": "眼睛该休息了，看看远处放松一下吧～",
    "自定义": "",
}


class StyledSpinBox(QSpinBox):
    """带自定义小箭头的 SpinBox（与设置窗口一致，避免 QSS 下默认箭头缺失）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._arrow_color = QColor('#999999')
        self._hover_color = QColor('#cccccc')
        self._pressed_color = QColor('#ffffff')
        self._up_hover = False
        self._down_hover = False
        self._up_pressed = False
        self._down_pressed = False

    def set_arrow_color(self, color: str):
        """设置箭头颜色"""
        self._arrow_color = QColor(color)

    def _get_button_rects(self):
        """计算上下按钮的矩形区域（对称布局）"""
        btn_width = 18
        rect = self.rect()
        right = rect.right() - 1
        top = rect.top() + 1
        half_h = rect.height() // 2

        up_rect = QRect(right - btn_width, top, btn_width, half_h)
        down_rect = QRect(right - btn_width, top + half_h, btn_width, rect.height() - half_h - 1)
        return up_rect, down_rect

    def paintEvent(self, event):
        """自定义绘制事件"""
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        up_rect, down_rect = self._get_button_rects()

        # 绘制上箭头
        up_color = self._pressed_color if self._up_pressed else (self._hover_color if self._up_hover else self._arrow_color)
        self._draw_arrow(painter, up_rect, 'up', up_color)

        # 绘制下箭头
        down_color = self._pressed_color if self._down_pressed else (self._hover_color if self._down_hover else self._arrow_color)
        self._draw_arrow(painter, down_rect, 'down', down_color)

    def _draw_arrow(self, painter: QPainter, rect: QRect, direction: str, color: QColor):
        """绘制精致小三角形箭头（箭头靠右，左右留白对称）"""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))

        polygon = QPolygonF()
        # 箭头中心往右偏1.5px，补偿 border-left 分隔线，使箭头左右留白对称
        cx = rect.center().x() + 1.5
        cy = rect.center().y()
        w = 3.5   # 半宽
        h = 2.5   # 半高

        if direction == 'up':
            polygon.append(QPointF(cx, cy - h))
            polygon.append(QPointF(cx - w, cy + h))
            polygon.append(QPointF(cx + w, cy + h))
        else:
            polygon.append(QPointF(cx - w, cy - h))
            polygon.append(QPointF(cx + w, cy - h))
            polygon.append(QPointF(cx, cy + h))

        painter.drawPolygon(polygon)

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        up_rect, down_rect = self._get_button_rects()

        if up_rect.contains(event.pos()):
            self._up_pressed = True
            self.stepUp()
            self.update()
            return
        elif down_rect.contains(event.pos()):
            self._down_pressed = True
            self.stepDown()
            self.update()
            return

        super().mousePressEvent(event)
        self.update()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        self._up_pressed = False
        self._down_pressed = False
        super().mouseReleaseEvent(event)
        self.update()

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        up_rect, down_rect = self._get_button_rects()

        old_up_hover = self._up_hover
        old_down_hover = self._down_hover

        self._up_hover = up_rect.contains(event.pos())
        self._down_hover = down_rect.contains(event.pos())

        if old_up_hover != self._up_hover or old_down_hover != self._down_hover:
            self.update()

        super().mouseMoveEvent(event)


class StyledComboBox(QComboBox):
    """带自定义下拉箭头的 ComboBox（QSS 下默认箭头不显示）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._arrow_color = QColor('#999999')

    def set_arrow_color(self, color: str):
        """设置箭头颜色"""
        self._arrow_color = QColor(color)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._arrow_color))

        # 下拉箭头画在右侧 drop-down 区域（宽度 20px）中央
        drop_width = 20
        cx = self.width() - drop_width / 2.0
        cy = self.height() / 2.0
        w = 4.0
        h = 3.0

        polygon = QPolygonF()
        polygon.append(QPointF(cx - w, cy - h))
        polygon.append(QPointF(cx + w, cy - h))
        polygon.append(QPointF(cx, cy + h))
        painter.drawPolygon(polygon)


class ReminderWindow(QWidget):
    """提醒设置窗口（无边框）。"""

    def __init__(self):
        super().__init__()
        self.setObjectName("ReminderWindow")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        try:
            from ..utils.window_front import install_activation_topmost
        except ImportError:
            from src.utils.window_front import install_activation_topmost
        install_activation_topmost(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(400, 330)

        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None
        self._content_frame: Optional[QFrame] = None

        # 外层布局只创建一次；主题变化时只重建内部 content_frame
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self._build_content()
        self._load_from_config()

        get_theme_manager().theme_changed.connect(self._on_theme_changed)

    def _build_content(self):
        theme = get_theme(self._theme_style)

        self._content_frame = QFrame()
        self._content_frame.setObjectName("contentFrame")
        self._content_frame.setStyleSheet(f"""
            QFrame#contentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 8px;
                border: 1px solid {theme['border_color']};
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self._content_frame)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(*theme['shadow_color']))
        shadow.setOffset(0, 2)
        self._content_frame.setGraphicsEffect(shadow)
        self._outer.addWidget(self._content_frame)

        content = QVBoxLayout(self._content_frame)
        content.setContentsMargins(14, 8, 14, 14)
        content.setSpacing(10)

        # 标题栏
        self._title_bar = QFrame()
        self._title_bar.setFixedHeight(28)
        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(6, 0, 2, 0)

        title = QLabel("提醒设置")
        title.setStyleSheet(f"QLabel {{ color: {theme['text_muted']}; font-size: 12px; }}")
        title_layout.addWidget(title)
        title_layout.addStretch()

        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {theme['text_muted']};
                border: none; border-radius: 11px; font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {theme['close_hover']}; color: #ffffff; }}
        """)
        self._close_btn.clicked.connect(self.hide)
        title_layout.addWidget(self._close_btn)
        content.addWidget(self._title_bar)

        # 启用开关（图标样式与设置窗口一致）
        self._enabled_check = QCheckBox("启用提醒")
        self._enabled_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._enabled_check.setStyleSheet(get_checkbox_style(theme))
        self._enabled_check.setIcon(self._check_icon(theme, False))
        self._enabled_check.toggled.connect(self._on_enabled_toggled)
        content.addWidget(self._enabled_check)

        # 提醒周期
        row1 = QHBoxLayout()
        row1.addWidget(self._make_label("提醒周期", theme))
        self._interval_spin = StyledSpinBox()
        self._interval_spin.setRange(1, 1440)
        self._interval_spin.setValue(30)
        self._interval_spin.setSuffix(" 分钟")
        self._interval_spin.setStyleSheet(self._spinbox_style(theme))
        self._interval_spin.set_arrow_color(theme['text_secondary'])
        row1.addWidget(self._interval_spin, 1)
        content.addLayout(row1)

        # 预设
        row2 = QHBoxLayout()
        row2.addWidget(self._make_label("预设内容", theme))
        self._preset_combo = StyledComboBox()
        self._preset_combo.addItems(list(PRESETS.keys()))
        self._preset_combo.setStyleSheet(self._combo_style(theme))
        self._preset_combo.set_arrow_color(theme['text_secondary'])
        self._preset_combo.currentTextChanged.connect(self._on_preset_changed)
        row2.addWidget(self._preset_combo, 1)
        content.addLayout(row2)

        # 提醒内容
        content.addWidget(self._make_label("提醒内容", theme))
        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText("输入提醒内容...")
        self._message_edit.setStyleSheet(self._lineedit_style(theme))
        self._message_edit.textEdited.connect(self._on_message_edited)
        content.addWidget(self._message_edit)

        content.addStretch()

        # 保存按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._save_btn = QPushButton("保存")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['accent_color']}; color: #ffffff;
                border: none; border-radius: 5px; padding: 7px 26px;
                font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {theme['accent_hover']}; }}
        """)
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)
        content.addLayout(btn_row)

        # 用于拖动的标题栏
        self._title_bar.installEventFilter(self)

    @staticmethod
    def _make_label(text: str, theme: dict) -> QLabel:
        lbl = QLabel(text)
        lbl.setFixedWidth(64)
        lbl.setStyleSheet(f"QLabel {{ color: {theme['text_secondary']}; font-size: 13px; }}")
        return lbl

    @staticmethod
    def _check_icon(theme: dict, checked: bool) -> QIcon:
        """勾选/未勾选图标（与设置窗口一致的圆角框 + 对勾）。"""
        pixmap = QPixmap(16, 17)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if checked:
            painter.setBrush(QColor(theme['accent_color']))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(1, 2, 14, 14, 4, 4)
            painter.setPen(QPen(QColor(255, 255, 255), 1.8, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(4, 9, 6, 12)
            painter.drawLine(6, 12, 12, 6)
        else:
            painter.setBrush(QColor(theme['input_bg']))
            painter.setPen(QPen(QColor(theme['scrollbar_handle']), 1.2))
            painter.drawRoundedRect(1, 2, 14, 14, 4, 4)
        painter.end()
        return QIcon(pixmap)

    def _on_enabled_toggled(self, checked: bool):
        theme = get_theme(self._theme_style)
        self._enabled_check.setIcon(self._check_icon(theme, checked))

    @staticmethod
    def _spinbox_style(theme: dict) -> str:
        return f"""
            QSpinBox {{
                background-color: {theme['input_bg']};
                border: 1px solid {theme['input_border']};
                border-radius: 6px;
                padding: 4px 8px;
                padding-right: 26px;
                color: {theme['text_primary']};
                font-size: 13px;
            }}
            QSpinBox:focus {{
                border-color: {theme['accent_color']};
            }}
            QSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: right top;
                width: 18px;
                border: none;
                border-top-right-radius: 5px;
                border-left: 1px solid {theme['input_border']};
                background-color: transparent;
            }}
            QSpinBox::up-button:hover {{
                background-color: {theme['button_hover']};
            }}
            QSpinBox::up-button:pressed {{
                background-color: {theme['accent_color']};
            }}
            QSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: right bottom;
                width: 18px;
                border: none;
                border-bottom-right-radius: 5px;
                border-left: 1px solid {theme['input_border']};
                background-color: transparent;
            }}
            QSpinBox::down-button:hover {{
                background-color: {theme['button_hover']};
            }}
            QSpinBox::down-button:pressed {{
                background-color: {theme['accent_color']};
            }}
        """

    @staticmethod
    def _combo_style(theme: dict) -> str:
        return f"""
            QComboBox {{
                background-color: {theme['input_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['input_border']};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QComboBox:hover {{
                border-color: {theme['accent_color']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme['bg_color']};
                color: {theme['text_primary']};
                selection-background-color: {theme['accent_color']};
                selection-color: #ffffff;
                border: 1px solid {theme['border_color']};
                border-radius: 6px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                border: none;
                padding: 2px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {theme['accent_color']};
                color: #ffffff;
            }}
        """

    @staticmethod
    def _lineedit_style(theme: dict) -> str:
        return f"""
            QLineEdit {{
                background-color: {theme['input_bg']};
                border: 1px solid {theme['input_border']};
                border-radius: 5px; padding: 6px 8px;
                color: {theme['text_primary']}; font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {theme['accent_color']}; }}
        """

    def _load_from_config(self):
        config = get_config()
        self._enabled_check.setChecked(config.get('reminder.enabled', False))
        self._interval_spin.setValue(int(config.get('reminder.interval_minutes', 30)))
        msg = config.get('reminder.message', '')
        if not msg:
            msg = PRESETS.get("喝水提醒", "")
        self._message_edit.setText(msg)
        # 根据当前内容回填预设选中项
        preset = "自定义"
        for name, text in PRESETS.items():
            if text and text == msg:
                preset = name
                break
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText(preset)
        self._preset_combo.blockSignals(False)

    def _on_preset_changed(self, name: str):
        text = PRESETS.get(name, "")
        if text:
            self._message_edit.setText(text)

    def _on_message_edited(self, _text: str):
        # 用户手动编辑时，预设切换到「自定义」
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText("自定义")
        self._preset_combo.blockSignals(False)

    def _on_save(self):
        enabled = self._enabled_check.isChecked()
        interval = self._interval_spin.value()
        message = self._message_edit.text().strip()
        if not message:
            message = PRESETS.get("喝水提醒", "该起来活动一下啦～")

        config = get_config()
        config.set('reminder.enabled', enabled)
        config.set('reminder.interval_minutes', interval)
        config.set('reminder.message', message)
        config.save()

        try:
            from ..core.reminder import get_reminder_manager
        except ImportError:
            from src.core.reminder import get_reminder_manager
        get_reminder_manager().configure(enabled, interval, message)

        self.hide()

    def _rebuild_content(self):
        if self._content_frame is not None:
            self._outer.removeWidget(self._content_frame)
            self._content_frame.deleteLater()
            self._content_frame = None
        self._build_content()

    def _on_theme_changed(self):
        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._rebuild_content()
        self._load_from_config()

    def show_window(self):
        # 用当前主题重建，保证打开时样式正确
        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._rebuild_content()
        self._load_from_config()
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2 + geo.x()
            y = (geo.height() - self.height()) // 2 + geo.y()
            self.move(x, y)
        self.show()
        try:
            from ..utils.window_front import bring_to_front_once
        except ImportError:
            from src.utils.window_front import bring_to_front_once
        bring_to_front_once(self)

    def eventFilter(self, obj, event):
        if obj is self._title_bar:
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_window_start_pos = self.pos()
                return True
            if event.type() == event.Type.MouseMove and self._drag_start_pos:
                delta = event.globalPosition().toPoint() - self._drag_start_pos
                self.move(self._drag_window_start_pos + delta)
                return True
            if event.type() == event.Type.MouseButtonRelease:
                self._drag_start_pos = None
        return super().eventFilter(obj, event)


_reminder_window_instance = None


def get_reminder_window() -> ReminderWindow:
    """获取全局提醒设置窗口实例。"""
    global _reminder_window_instance
    if _reminder_window_instance is None:
        _reminder_window_instance = ReminderWindow()
    return _reminder_window_instance
