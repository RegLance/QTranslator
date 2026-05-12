"""朗读按钮：从开始朗读到结束（含合成/缓冲）显示转圈，读完或停止后恢复图标。"""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QObject, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QPushButton, QWidget


class _MainThreadEndPrepare(QObject):
    """TTS 完成/停止回调常在后台线程；用信号投递到 GUI 线程再恢复按钮图标。"""

    _request = pyqtSignal()

    def __init__(self, indicator: "TtsSpeakPrepareIndicator", parent: QWidget) -> None:
        super().__init__(parent)
        self._indicator = indicator
        self._request.connect(self._indicator.end_prepare)

    def request_end_prepare(self) -> None:
        self._request.emit()


class TtsSpeakPrepareIndicator:
    """绑定朗读按钮：朗读进行中转圈，on_finish / on_stop 后恢复。"""

    def __init__(
        self,
        parent_widget: QWidget,
        button: QPushButton,
        theme_getter: Callable[[], dict[str, Any]],
        icon_from_theme: Callable[[dict[str, Any]], QIcon],
    ) -> None:
        self._btn = button
        self._theme_getter = theme_getter
        self._icon_factory = icon_from_theme
        self._normal_icon = icon_from_theme(theme_getter())
        self._active = False
        self._angle = 0
        self._timer = QTimer(parent_widget)
        self._timer.timeout.connect(self._on_tick)
        self._timer.setInterval(80)
        self._main_thread_end = _MainThreadEndPrepare(self, parent_widget)

    def is_preparing(self) -> bool:
        return self._active

    def sync_theme_icons(self) -> None:
        self._normal_icon = self._icon_factory(self._theme_getter())
        if not self._active:
            self._btn.setIcon(self._normal_icon)

    def attach_to_tts_engine(self, tts: Any) -> None:
        def _end_on_main() -> None:
            self._main_thread_end.request_end_prepare()

        tts.set_callbacks(
            on_start=None,
            on_finish=_end_on_main,
            on_stop=_end_on_main,
        )

    def start_prepare(self) -> None:
        if self._active:
            return
        self._normal_icon = self._icon_factory(self._theme_getter())
        self._active = True
        self._angle = 0
        self._btn.setIcon(self._spinner_icon())
        self._timer.start()

    def end_prepare(self) -> None:
        if not self._active:
            return
        self._timer.stop()
        self._active = False
        self._normal_icon = self._icon_factory(self._theme_getter())
        self._btn.setIcon(self._normal_icon)

    def _on_tick(self) -> None:
        if not self._active:
            self._timer.stop()
            return
        self._angle = (self._angle + 32) % 360
        self._btn.setIcon(self._spinner_icon())

    def _spinner_icon(self) -> QIcon:
        theme = self._theme_getter()
        icon_color = QColor(theme.get("text_muted", "#888888"))

        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pen = QPen(
            icon_color,
            2.0,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)

        arc_rect = QRectF(2.0, 2.0, 14.0, 14.0)
        start_deg = float(self._angle % 360)
        span_deg = 300.0
        painter.drawArc(
            arc_rect,
            int(start_deg * 16),
            int(span_deg * 16),
        )

        painter.end()

        return QIcon(pixmap)
