"""工作量统计窗口 - 开关、今日数据、清空当天、历史记录。"""
from typing import Optional

from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGraphicsDropShadowEffect, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QApplication, QMessageBox,
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QPen

try:
    from ..config import get_config
    from ..utils.theme import get_theme, get_theme_manager, get_scrollbar_style, get_checkbox_style
except ImportError:
    from src.config import get_config
    from src.utils.theme import get_theme, get_theme_manager, get_scrollbar_style, get_checkbox_style


def _format_distance(cm: float) -> str:
    """把厘米换算成易读的米/厘米表示。"""
    try:
        cm = float(cm or 0.0)
    except (TypeError, ValueError):
        cm = 0.0
    if cm >= 100:
        return f"{cm / 100.0:.2f} 米"
    return f"{cm:.0f} 厘米"


class StatisticsWindow(QWidget):
    """工作量统计窗口（无边框）。"""

    def __init__(self):
        super().__init__()
        self.setObjectName("StatisticsWindow")
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
        self.setMinimumSize(520, 460)
        self.resize(560, 560)

        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None
        self._content_frame: Optional[QFrame] = None
        self._rendered_date = None

        try:
            from ..core.statistics import get_statistics_tracker
        except ImportError:
            from src.core.statistics import get_statistics_tracker
        self._tracker = get_statistics_tracker()

        # 外层布局只创建一次；主题变化时只重建内部 content_frame
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self._build_content()

        # 每秒刷新今日数据（窗口显示期间）
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_today)
        self._refresh_timer.start(1000)

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

        title = QLabel("工作量统计")
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
        toggle_row = QHBoxLayout()
        self._enabled_check = QCheckBox("启用统计")
        self._enabled_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._enabled_check.setStyleSheet(get_checkbox_style(theme))
        self._enabled_check.setIcon(self._check_icon(theme, False))
        self._enabled_check.toggled.connect(self._on_toggle)
        toggle_row.addWidget(self._enabled_check)
        toggle_row.addStretch()
        content.addLayout(toggle_row)

        # 说明：娱乐功能，数据仅存本地
        note = QLabel("统计为娱乐功能，数据只存于本地")
        note.setStyleSheet(f"QLabel {{ color: {theme['text_muted']}; font-size: 11px; }}")
        content.addWidget(note)

        # 今日数据
        content.addWidget(self._make_section_label("今日数据", theme))
        self._today_frame = QFrame()
        self._today_frame.setStyleSheet(f"""
            QFrame {{ background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px; }}
        """)
        today_layout = QHBoxLayout(self._today_frame)
        today_layout.setContentsMargins(12, 12, 12, 12)
        today_layout.setSpacing(8)

        self._stat_labels = {}
        for key, label in (("key", "键盘敲击"), ("distance", "移动距离"),
                           ("wheel", "滚轮"), ("left", "左键"), ("right", "右键")):
            col = QVBoxLayout()
            val = QLabel("0")
            val.setObjectName(f"stat_{key}")
            val.setStyleSheet(f"QLabel {{ color: {theme['accent_color']}; font-size: 18px; font-weight: bold; }}")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap = QLabel(label)
            cap.setStyleSheet(f"QLabel {{ color: {theme['text_muted']}; font-size: 11px; }}")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(val)
            col.addWidget(cap)
            self._stat_labels[key] = val
            today_layout.addLayout(col, 1)
        content.addWidget(self._today_frame)

        # 清空当天按钮
        clear_row = QHBoxLayout()
        clear_row.addStretch()
        self._clear_btn = QPushButton("清空当天数据")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {theme['text_muted']};
                border: 1px solid {theme['border_color']}; border-radius: 5px;
                padding: 4px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ color: {theme['close_hover']}; border-color: {theme['close_hover']}; }}
        """)
        self._clear_btn.clicked.connect(self._on_clear_today)
        clear_row.addWidget(self._clear_btn)
        content.addLayout(clear_row)

        # 历史记录
        content.addWidget(self._make_section_label("历史记录", theme))
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["日期", "键盘敲击", "移动距离", "滚轮", "左键", "右键"])
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 6px; color: {theme['text_primary']};
                font-size: 12px; gridline-color: {theme['border_color']};
            }}
            QTableWidget::item {{ padding: 4px; }}
            QTableWidget::item:selected {{ background-color: {theme['list_item_hover']}; }}
            QHeaderView::section {{
                background-color: {theme['button_bg']};
                color: {theme['text_secondary']};
                border: none; padding: 6px 4px; font-size: 12px;
                border-bottom: 1px solid {theme['border_color']};
            }}
            {get_scrollbar_style(theme)}
        """)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        content.addWidget(self._table, 1)

        self._title_bar.installEventFilter(self)

    @staticmethod
    def _make_section_label(text: str, theme: dict) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"QLabel {{ color: {theme['accent_color']}; font-size: 13px; font-weight: bold; }}")
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

    def _sync_enabled_check(self):
        """无副作用地同步开关状态与图标（不触发 toggled / 重复保存）。"""
        theme = get_theme(self._theme_style)
        enabled = self._tracker.is_enabled
        self._enabled_check.blockSignals(True)
        self._enabled_check.setChecked(enabled)
        self._enabled_check.setIcon(self._check_icon(theme, enabled))
        self._enabled_check.blockSignals(False)

    def _on_toggle(self, enabled: bool):
        theme = get_theme(self._theme_style)
        self._enabled_check.setIcon(self._check_icon(theme, enabled))
        config = get_config()
        config.set('statistics.enabled', enabled)
        config.save()
        self._tracker.set_enabled(enabled)

    def _refresh_today(self):
        snap = self._tracker.today_snapshot()
        self._stat_labels["key"].setText(str(int(snap.get("key", 0))))
        self._stat_labels["distance"].setText(_format_distance(snap.get("distance_cm", 0.0)))
        self._stat_labels["wheel"].setText(str(int(snap.get("wheel", 0))))
        self._stat_labels["left"].setText(str(int(snap.get("left", 0))))
        self._stat_labels["right"].setText(str(int(snap.get("right", 0))))
        # 仅当日期变化（或首次）时重建历史表，避免每秒重建导致滚动位置/选中被重置
        from datetime import date as _date
        today = _date.today().isoformat()
        if getattr(self, '_rendered_date', None) != today:
            self._rendered_date = today
            self._refresh_history()

    def _refresh_history(self):
        rows = self._tracker.history()
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            d = row.get("date", "")
            cells = [
                d,
                str(int(row.get("key", 0))),
                _format_distance(row.get("distance_cm", 0.0)),
                str(int(row.get("wheel", 0))),
                str(int(row.get("left", 0))),
                str(int(row.get("right", 0))),
            ]
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j == 0:
                    item.setForeground(Qt.GlobalColor.gray)
                self._table.setItem(i, j, item)

    def _on_clear_today(self):
        try:
            from ..utils.window_front import show_modal_message_box
        except ImportError:
            from src.utils.window_front import show_modal_message_box
        result = show_modal_message_box(
            self,
            QMessageBox.Icon.Question,
            "清空当天数据",
            "确定要清空今天的统计数据吗？\n历史记录不会被影响。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            self._tracker.clear_today()
            self._refresh_today()
            self._refresh_history()

    def _rebuild_content(self):
        if self._content_frame is not None:
            self._outer.removeWidget(self._content_frame)
            self._content_frame.deleteLater()
            self._content_frame = None
        self._build_content()

    def _on_theme_changed(self):
        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._rebuild_content()
        # 重建后回填开关状态（theme_changed 可能在任何时刻触发）
        self._sync_enabled_check()
        self._rendered_date = None

    def show_window(self):
        # 用当前主题重建，保证打开时样式正确
        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._rebuild_content()
        self._sync_enabled_check()
        self._rendered_date = None
        self._refresh_today()
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


_statistics_window_instance = None


def get_statistics_window() -> StatisticsWindow:
    """获取全局统计窗口实例。"""
    global _statistics_window_instance
    if _statistics_window_instance is None:
        _statistics_window_instance = StatisticsWindow()
    return _statistics_window_instance
