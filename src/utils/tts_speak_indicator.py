"""朗读按钮准备阶段：圆形进度动画；on_start 后与正常播放图标一致。"""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QPushButton, QWidget


class TtsSpeakPrepareIndicator:
    """绑定单个朗读 QPushButton：在等待 TTS 出声时显示转圈图标。"""

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

    def is_preparing(self) -> bool:
        return self._active

    def sync_theme_icons(self) -> None:
        self._normal_icon = self._icon_factory(self._theme_getter())
        if not self._active:
            self._btn.setIcon(self._normal_icon)

    def attach_to_tts_engine(self, tts: Any) -> None:
        def _end_on_main() -> None:
            QTimer.singleShot(0, self.end_prepare)

        def _on_start() -> None:
            _end_on_main()

        tts.set_callbacks(
            on_start=_on_start,
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
