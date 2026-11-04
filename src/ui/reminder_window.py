"""提醒设置窗口 - 多条提醒的列表管理 + 单条新增/编辑。

每条提醒支持五种模式：循环（每隔 N 分钟）/ 指定时间（一次性）/
每天 / 每周 / 每月。列表内可单独开关、编辑、删除某条提醒。
配置存于 config.yaml 的 reminder.items，保存后调用 ReminderManager.configure() 生效。
"""
import uuid
from typing import Optional

from PyQt6.QtCore import Qt, QPoint, QRect, QPointF, QTime, QDateTime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGraphicsDropShadowEffect, QCheckBox, QSpinBox, QComboBox, QLineEdit,
    QApplication, QScrollArea, QStackedWidget, QTimeEdit, QDateTimeEdit,
    QAbstractSpinBox, QMessageBox,
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QPen, QBrush, QPolygonF

try:
    from ..config import get_config
    from ..utils.theme import get_theme, get_theme_manager, get_checkbox_style
    from ..core.reminder import WEEKDAY_NAMES
except ImportError:
    from src.config import get_config
    from src.utils.theme import get_theme, get_theme_manager, get_checkbox_style
    from src.core.reminder import WEEKDAY_NAMES


# 预置提醒内容
PRESETS = {
    "喝水提醒": "该喝水啦，起来接杯水休息一下吧～",
    "久坐提醒": "久坐伤身，站起来活动一下筋骨吧～",
    "护眼提醒": "眼睛该休息了，看看远处放松一下吧～",
    "自定义": "",
}

# 模式：与 ReminderManager 中的 mode 值一一对应
MODES = ["interval", "once", "daily", "weekly", "monthly"]
MODE_LABELS = ["循环提醒", "指定时间（一次性）", "每天", "每周", "每月"]


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

        up_color = self._pressed_color if self._up_pressed else (self._hover_color if self._up_hover else self._arrow_color)
        self._draw_arrow(painter, up_rect, 'up', up_color)

        down_color = self._pressed_color if self._down_pressed else (self._hover_color if self._down_hover else self._arrow_color)
        self._draw_arrow(painter, down_rect, 'down', down_color)

    def _draw_arrow(self, painter: QPainter, rect: QRect, direction: str, color: QColor):
        """绘制精致小三角形箭头（箭头靠右，左右留白对称）"""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))

        polygon = QPolygonF()
        cx = rect.center().x() + 1.5
        cy = rect.center().y()
        w = 3.5
        h = 2.5

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
        self._up_pressed = False
        self._down_pressed = False
        super().mouseReleaseEvent(event)
        self.update()

    def mouseMoveEvent(self, event):
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
        self._enable_windows_window_management()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._set_window_icon()
        self.setFixedSize(500, 620)

        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None
        self._content_frame: Optional[QFrame] = None

        # 工作数据：提醒列表（来自配置）与当前正在编辑的条目 id（None=新增）
        self._items = []
        self._editing_id: Optional[str] = None

        # 外层布局只创建一次；主题变化时只重建内部 content_frame
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self._build_content()
        self._load_items_from_config()
        self._render_list()
        self._reset_editor()

        get_theme_manager().theme_changed.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
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
        content.setSpacing(8)

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

        # 列表标题
        list_header = QHBoxLayout()
        list_header.addWidget(self._make_label("提醒列表", theme))
        list_header.addStretch()
        content.addLayout(list_header)

        # 提醒列表（滚动）
        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_scroll.setWidget(self._list_container)
        content.addWidget(self._list_scroll, 1)

        # 添加按钮
        add_row = QHBoxLayout()
        add_row.addStretch()
        self._add_btn = QPushButton("＋ 添加提醒")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {theme['accent_color']};
                border: 1px dashed {theme['accent_color']}; border-radius: 6px;
                padding: 6px 20px; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {theme['list_item_hover']}; }}
        """)
        self._add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._add_btn)
        add_row.addStretch()
        content.addLayout(add_row)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"QFrame {{ color: {theme['border_color']}; background-color: {theme['border_color']}; max-height: 1px; }}")
        content.addWidget(sep)

        # 编辑器
        content.addWidget(self._make_label("编辑提醒", theme))
        self._editor_frame = QFrame()
        self._editor_frame.setStyleSheet(f"""
            QFrame {{ background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px; }}
        """)
        editor = QVBoxLayout(self._editor_frame)
        editor.setContentsMargins(12, 10, 12, 10)
        editor.setSpacing(8)

        # 模式选择
        mode_row = QHBoxLayout()
        mode_row.addWidget(self._make_label("模式", theme))
        self._mode_combo = StyledComboBox()
        self._mode_combo.addItems(MODE_LABELS)
        self._mode_combo.setStyleSheet(self._combo_style(theme))
        self._mode_combo.set_arrow_color(theme['text_secondary'])
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_combo, 1)
        editor.addLayout(mode_row)

        # 模式参数区（堆叠页）
        self._params_stack = QStackedWidget()
        self._params_stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
        self._build_param_pages(theme)
        editor.addWidget(self._params_stack)

        # 预设
        preset_row = QHBoxLayout()
        preset_row.addWidget(self._make_label("预设内容", theme))
        self._preset_combo = StyledComboBox()
        self._preset_combo.addItems(list(PRESETS.keys()))
        self._preset_combo.setStyleSheet(self._combo_style(theme))
        self._preset_combo.set_arrow_color(theme['text_secondary'])
        self._preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_row.addWidget(self._preset_combo, 1)
        editor.addLayout(preset_row)

        # 提醒内容
        msg_row = QHBoxLayout()
        msg_row.addWidget(self._make_label("提醒内容", theme))
        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText("输入提醒内容...")
        self._message_edit.setStyleSheet(self._lineedit_style(theme))
        self._message_edit.textEdited.connect(self._on_message_edited)
        msg_row.addWidget(self._message_edit, 1)
        editor.addLayout(msg_row)

        # 保存 / 取消
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setStyleSheet(self._secondary_btn_style(theme))
        self._cancel_btn.clicked.connect(self._reset_editor)
        btn_row.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("添加提醒")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setStyleSheet(self._primary_btn_style(theme))
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)
        editor.addLayout(btn_row)

        content.addWidget(self._editor_frame)

        # 用于拖动的标题栏
        self._title_bar.installEventFilter(self)

    def _build_param_pages(self, theme):
        """构建各模式对应的参数输入页。"""
        # 循环：间隔分钟
        page0 = QWidget()
        l0 = QHBoxLayout(page0)
        l0.setContentsMargins(0, 0, 0, 0)
        l0.addWidget(self._make_label("间隔", theme))
        self._interval_spin = StyledSpinBox()
        self._interval_spin.setRange(1, 1440)
        self._interval_spin.setValue(30)
        self._interval_spin.setSuffix(" 分钟")
        self._interval_spin.setStyleSheet(self._spinbox_style(theme))
        self._interval_spin.set_arrow_color(theme['text_secondary'])
        l0.addWidget(self._interval_spin, 1)
        self._params_stack.addWidget(page0)

        # 指定时间：日期 + 时间
        page1 = QWidget()
        l1 = QHBoxLayout(page1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.addWidget(self._make_label("时间", theme))
        self._once_datetime = QDateTimeEdit()
        self._once_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._once_datetime.setCalendarPopup(True)
        self._once_datetime.setStyleSheet(self._timeedit_style(theme))
        l1.addWidget(self._once_datetime, 1)
        self._params_stack.addWidget(page1)

        # 每天：时间
        page2 = QWidget()
        l2 = QHBoxLayout(page2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.addWidget(self._make_label("时间", theme))
        self._daily_time = QTimeEdit()
        self._daily_time.setDisplayFormat("HH:mm")
        self._daily_time.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self._daily_time.setStyleSheet(self._timeedit_style(theme))
        l2.addWidget(self._daily_time, 1)
        self._params_stack.addWidget(page2)

        # 每周：星期 + 时间
        page3 = QWidget()
        l3 = QHBoxLayout(page3)
        l3.setContentsMargins(0, 0, 0, 0)
        l3.addWidget(self._make_label("星期", theme))
        self._weekly_weekday = StyledComboBox()
        self._weekly_weekday.addItems(WEEKDAY_NAMES)
        self._weekly_weekday.setStyleSheet(self._combo_style(theme))
        self._weekly_weekday.set_arrow_color(theme['text_secondary'])
        l3.addWidget(self._weekly_weekday, 1)
        l3.addWidget(self._make_label("时间", theme, width=40))
        self._weekly_time = QTimeEdit()
        self._weekly_time.setDisplayFormat("HH:mm")
        self._weekly_time.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self._weekly_time.setStyleSheet(self._timeedit_style(theme))
        l3.addWidget(self._weekly_time, 1)
        self._params_stack.addWidget(page3)

        # 每月：日期 + 时间
        page4 = QWidget()
        l4 = QHBoxLayout(page4)
        l4.setContentsMargins(0, 0, 0, 0)
        l4.addWidget(self._make_label("日期", theme))
        self._monthly_day = StyledSpinBox()
        self._monthly_day.setRange(1, 31)
        self._monthly_day.setValue(1)
        self._monthly_day.setSuffix(" 号")
        self._monthly_day.setStyleSheet(self._spinbox_style(theme))
        self._monthly_day.set_arrow_color(theme['text_secondary'])
        l4.addWidget(self._monthly_day, 1)
        l4.addWidget(self._make_label("时间", theme, width=40))
        self._monthly_time = QTimeEdit()
        self._monthly_time.setDisplayFormat("HH:mm")
        self._monthly_time.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self._monthly_time.setStyleSheet(self._timeedit_style(theme))
        l4.addWidget(self._monthly_time, 1)
        self._params_stack.addWidget(page4)

    # ------------------------------------------------------------------
    # 列表渲染
    # ------------------------------------------------------------------
    def _render_list(self):
        theme = get_theme(self._theme_style)
        self._clear_layout(self._list_layout)

        if not self._items:
            empty = QLabel("暂无提醒，点击上方「添加提醒」新建")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"QLabel {{ color: {theme['text_muted']}; font-size: 12px; padding: 20px; }}")
            self._list_layout.addWidget(empty)
        else:
            for item in self._items:
                self._list_layout.addWidget(self._make_list_row(item, theme))
        self._list_layout.addStretch()

    def _make_list_row(self, item: dict, theme: dict) -> QFrame:
        iid = item.get('id', '')
        row = QFrame()
        row.setStyleSheet(f"""
            QFrame {{ background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px; }}
        """)
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)

        check = QCheckBox()
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.setStyleSheet(get_checkbox_style(theme))
        check.setIcon(self._check_icon(theme, bool(item.get('enabled', True))))
        check.setChecked(bool(item.get('enabled', True)))
        check.toggled.connect(lambda checked, c=check, id_=iid: self._on_item_toggle(id_, checked, c))
        h.addWidget(check)

        summary = QLabel(self._summarize(item))
        summary.setWordWrap(True)
        summary.setStyleSheet(f"QLabel {{ color: {theme['text_primary']}; font-size: 13px; }}")
        h.addWidget(summary, 1)

        edit_btn = QPushButton("编辑")
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setStyleSheet(self._secondary_btn_style(theme))
        edit_btn.clicked.connect(lambda _, id_=iid: self._start_edit(id_))
        h.addWidget(edit_btn)

        del_btn = QPushButton("删除")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(self._danger_btn_style(theme))
        del_btn.clicked.connect(lambda _, id_=iid: self._delete_item(id_))
        h.addWidget(del_btn)

        return row

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
            elif child.layout() is not None:
                ReminderWindow._clear_layout(child.layout())

    # ------------------------------------------------------------------
    # 数据读写
    # ------------------------------------------------------------------
    def _load_items_from_config(self):
        raw = get_config().get('reminder.items', []) or []
        self._items = [dict(i) for i in raw if isinstance(i, dict)]

    def _persist(self):
        config = get_config()
        config.set('reminder.items', self._items)
        config.save()
        try:
            from ..core.reminder import get_reminder_manager
        except ImportError:
            from src.core.reminder import get_reminder_manager
        get_reminder_manager().configure(self._items)

    def _find_item(self, iid: str):
        for idx, item in enumerate(self._items):
            if item.get('id') == iid:
                return idx, item
        return None, None

    @staticmethod
    def _summarize(item: dict) -> str:
        mode = item.get('mode', 'interval')
        if mode == 'interval':
            sched = f"每 {item.get('interval_minutes', 30)} 分钟"
        elif mode == 'once':
            sched = item.get('datetime', '')
        elif mode == 'daily':
            sched = f"每天 {item.get('time', '')}"
        elif mode == 'weekly':
            sched = f"每周{WEEKDAY_NAMES[int(item.get('weekday', 0)) % 7]} {item.get('time', '')}"
        elif mode == 'monthly':
            sched = f"每月 {item.get('day', 1)} 号 {item.get('time', '')}"
        else:
            sched = mode
        msg = (item.get('message') or '').strip()
        return f"{sched}：{msg}" if msg else sched

    # ------------------------------------------------------------------
    # 列表操作
    # ------------------------------------------------------------------
    def _on_item_toggle(self, iid: str, checked: bool, check_widget):
        _, item = self._find_item(iid)
        if item is None:
            return
        item['enabled'] = bool(checked)
        theme = get_theme(self._theme_style)
        check_widget.setIcon(self._check_icon(theme, bool(checked)))
        self._persist()

    def _on_add(self):
        self._reset_editor()

    def _start_edit(self, iid: str):
        _, item = self._find_item(iid)
        if item is None:
            return
        self._editing_id = iid
        self._populate_form(item)
        self._save_btn.setText("保存修改")

    def _delete_item(self, iid: str):
        try:
            from ..utils.window_front import show_modal_message_box
        except ImportError:
            from src.utils.window_front import show_modal_message_box
        result = show_modal_message_box(
            self,
            QMessageBox.Icon.Question,
            "删除提醒",
            "确定要删除这条提醒吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        idx, _ = self._find_item(iid)
        if idx is not None:
            self._items.pop(idx)
        self._persist()
        if self._editing_id == iid:
            self._reset_editor()
        self._render_list()

    # ------------------------------------------------------------------
    # 编辑器
    # ------------------------------------------------------------------
    def _reset_editor(self):
        self._editing_id = None
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(0)
        self._mode_combo.blockSignals(False)
        self._params_stack.setCurrentIndex(0)
        self._interval_spin.setValue(30)
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText("自定义")
        self._preset_combo.blockSignals(False)
        self._message_edit.setText("")
        self._save_btn.setText("添加提醒")

    def _populate_form(self, item: dict):
        mode = item.get('mode', 'interval')
        idx = MODES.index(mode) if mode in MODES else 0
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(idx)
        self._mode_combo.blockSignals(False)
        self._params_stack.setCurrentIndex(idx)

        if mode == 'interval':
            self._interval_spin.setValue(int(item.get('interval_minutes', 30)))
        elif mode == 'once':
            dt = QDateTime.fromString(item.get('datetime', ''), "yyyy-MM-dd HH:mm")
            if not dt.isValid():
                dt = QDateTime.currentDateTime().addSecs(3600)
            self._once_datetime.setDateTime(dt)
        elif mode == 'daily':
            t = QTime.fromString(item.get('time', '09:00'), "HH:mm")
            if not t.isValid():
                t = QTime(9, 0)
            self._daily_time.setTime(t)
        elif mode == 'weekly':
            self._weekly_weekday.setCurrentIndex(int(item.get('weekday', 0)) % 7)
            t = QTime.fromString(item.get('time', '09:00'), "HH:mm")
            if not t.isValid():
                t = QTime(9, 0)
            self._weekly_time.setTime(t)
        elif mode == 'monthly':
            self._monthly_day.setValue(max(1, min(31, int(item.get('day', 1)))))
            t = QTime.fromString(item.get('time', '09:00'), "HH:mm")
            if not t.isValid():
                t = QTime(9, 0)
            self._monthly_time.setTime(t)

        msg = item.get('message', '')
        self._message_edit.setText(msg)
        preset = "自定义"
        for name, text in PRESETS.items():
            if text and text == msg:
                preset = name
                break
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText(preset)
        self._preset_combo.blockSignals(False)

    def _build_item_from_form(self) -> dict:
        mode = MODES[self._mode_combo.currentIndex()]
        item = {
            'enabled': True,
            'mode': mode,
            'message': self._message_edit.text().strip(),
        }
        if mode == 'interval':
            item['interval_minutes'] = self._interval_spin.value()
        elif mode == 'once':
            item['datetime'] = self._once_datetime.dateTime().toString("yyyy-MM-dd HH:mm")
        elif mode == 'daily':
            item['time'] = self._daily_time.time().toString("HH:mm")
        elif mode == 'weekly':
            item['weekday'] = self._weekly_weekday.currentIndex()
            item['time'] = self._weekly_time.time().toString("HH:mm")
        elif mode == 'monthly':
            item['day'] = self._monthly_day.value()
            item['time'] = self._monthly_time.time().toString("HH:mm")
        return item

    def _on_save(self):
        new_item = self._build_item_from_form()
        if not new_item.get('message'):
            new_item['message'] = PRESETS.get("喝水提醒", "该起来活动一下啦～")

        if self._editing_id is not None:
            idx, old = self._find_item(self._editing_id)
            if old is not None:
                # 一次性提醒：时间未变则保留 last_fired，避免重复触发
                if old.get('mode') == 'once' and new_item.get('datetime') == old.get('datetime'):
                    new_item['last_fired'] = old.get('last_fired')
                new_item['id'] = old['id']
                new_item['enabled'] = old.get('enabled', True)
                self._items[idx] = new_item
        else:
            new_item['id'] = uuid.uuid4().hex[:12]
            self._items.append(new_item)

        self._persist()
        self._reset_editor()
        self._render_list()

    def _on_mode_changed(self, index: int):
        self._params_stack.setCurrentIndex(max(0, min(index, self._params_stack.count() - 1)))

    def _on_preset_changed(self, name: str):
        text = PRESETS.get(name, "")
        if text:
            self._message_edit.setText(text)

    def _on_message_edited(self, _text: str):
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText("自定义")
        self._preset_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # 主题 / 显示
    # ------------------------------------------------------------------
    def _rebuild_content(self):
        if self._content_frame is not None:
            self._outer.removeWidget(self._content_frame)
            self._content_frame.deleteLater()
            self._content_frame = None
        self._build_content()

    def _on_theme_changed(self):
        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._rebuild_content()
        self._load_items_from_config()
        self._render_list()
        self._reset_editor()

    def show_window(self):
        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._rebuild_content()
        self._load_items_from_config()
        self._render_list()
        self._reset_editor()
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

    # ------------------------------------------------------------------
    # 样式 / 图标工具
    # ------------------------------------------------------------------
    @staticmethod
    def _make_label(text: str, theme: dict, width: int = 64) -> QLabel:
        lbl = QLabel(text)
        lbl.setFixedWidth(width)
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
            QSpinBox:focus {{ border-color: {theme['accent_color']}; }}
            QSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: right top;
                width: 18px;
                border: none;
                border-top-right-radius: 5px;
                border-left: 1px solid {theme['input_border']};
                background-color: transparent;
            }}
            QSpinBox::up-button:hover {{ background-color: {theme['button_hover']}; }}
            QSpinBox::up-button:pressed {{ background-color: {theme['accent_color']}; }}
            QSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: right bottom;
                width: 18px;
                border: none;
                border-bottom-right-radius: 5px;
                border-left: 1px solid {theme['input_border']};
                background-color: transparent;
            }}
            QSpinBox::down-button:hover {{ background-color: {theme['button_hover']}; }}
            QSpinBox::down-button:pressed {{ background-color: {theme['accent_color']}; }}
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
            QComboBox:hover {{ border-color: {theme['accent_color']}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background-color: {theme['bg_color']};
                color: {theme['text_primary']};
                selection-background-color: {theme['accent_color']};
                selection-color: #ffffff;
                border: 1px solid {theme['border_color']};
                border-radius: 6px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{ border: none; padding: 2px; }}
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

    @staticmethod
    def _timeedit_style(theme: dict) -> str:
        return f"""
            QDateTimeEdit, QTimeEdit {{
                background-color: {theme['input_bg']};
                border: 1px solid {theme['input_border']};
                border-radius: 6px; padding: 4px 8px;
                color: {theme['text_primary']}; font-size: 13px;
            }}
            QDateTimeEdit:focus, QTimeEdit:focus {{ border-color: {theme['accent_color']}; }}
            QDateTimeEdit::drop-down {{
                subcontrol-origin: border;
                subcontrol-position: right center;
                width: 20px;
                border: none;
                border-left: 1px solid {theme['input_border']};
                background-color: transparent;
            }}
            QDateTimeEdit::up-button, QDateTimeEdit::down-button,
            QTimeEdit::up-button, QTimeEdit::down-button {{
                background-color: transparent;
                border: none;
            }}
            QDateTimeEdit::up-button:hover, QDateTimeEdit::down-button:hover,
            QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {{
                background-color: {theme['button_hover']};
            }}
        """

    @staticmethod
    def _primary_btn_style(theme: dict) -> str:
        return f"""
            QPushButton {{
                background-color: {theme['accent_color']}; color: #ffffff;
                border: none; border-radius: 5px; padding: 7px 20px;
                font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {theme['accent_hover']}; }}
        """

    @staticmethod
    def _secondary_btn_style(theme: dict) -> str:
        return f"""
            QPushButton {{
                background-color: transparent; color: {theme['text_secondary']};
                border: 1px solid {theme['border_color']}; border-radius: 5px;
                padding: 6px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ color: {theme['text_primary']}; border-color: {theme['text_secondary']}; }}
        """

    @staticmethod
    def _danger_btn_style(theme: dict) -> str:
        return f"""
            QPushButton {{
                background-color: transparent; color: {theme['text_muted']};
                border: 1px solid {theme['border_color']}; border-radius: 5px;
                padding: 6px 12px; font-size: 12px;
            }}
            QPushButton:hover {{ color: {theme['close_hover']}; border-color: {theme['close_hover']}; }}
        """

    def _enable_windows_window_management(self):
        """Windows Win32 样式：确保任务栏图标 + 系统快捷键（与其他功能窗口一致）。"""
        import sys
        try:
            if not sys.platform.startswith("win"):
                return
            import ctypes
            hwnd = int(self.winId())
            GWL_STYLE = -16
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            new_style = style | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            )
        except Exception:
            pass

    def _set_window_icon(self):
        """设置窗口图标（任务栏图标），Win32 API 兜底确保打包后可用。"""
        import sys
        from pathlib import Path
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent.parent
        icon_png = base / "assets" / "icon.png"
        icon_ico = base / "assets" / "icon.ico"
        if icon_png.exists():
            self.setWindowIcon(QIcon(str(icon_png)))
        try:
            import ctypes
            hwnd = int(self.winId())
            LR_LOADFROMFILE = 0x0010
            IMAGE_ICON = 1
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            hicon = None
            if icon_ico.exists():
                hicon = ctypes.windll.user32.LoadImageW(
                    None, str(icon_ico), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if not hicon and icon_png.exists():
                hicon = ctypes.windll.user32.LoadImageW(
                    None, str(icon_png), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
        except Exception:
            pass


_reminder_window_instance = None


def get_reminder_window() -> ReminderWindow:
    """获取全局提醒设置窗口实例。"""
    global _reminder_window_instance
    if _reminder_window_instance is None:
        _reminder_window_instance = ReminderWindow()
    return _reminder_window_instance
