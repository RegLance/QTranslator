"""启动动画窗口 — 高帧率缩放脉动 + 状态文字，初始化完成后淡出"""
import math
import time as _time
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF
from PyQt6.QtGui import QPixmap, QColor, QPainter, QFont


# ── 动画参数 ──────────────────────────────────────────────────
SCALE_MIN = 0.94             # 缩放下限
CYCLE_DURATION = 2400        # 单周期毫秒（越大越慢）
FRAME_INTERVAL = 5           # 帧间隔 ms（200fps）


class PulsingIcon(QWidget):
    """可缩放脉动的图标控件

    由外部定时器调用 set_scale() 更新缩放值，paintEvent 中做平滑缩放绘制。
    """

    def __init__(self, pixmap: QPixmap, icon_size: int, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._icon_size = icon_size
        self._scale = 1.0

        padding = 20
        self.setFixedSize(icon_size + padding, icon_size + padding)
        self.setStyleSheet("background-color: transparent;")

    def set_scale(self, v: float):
        self._scale = v
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w = self._icon_size * self._scale
        h = self._icon_size * self._scale
        x = (self.width() - w) / 2
        y = (self.height() - h) / 2

        painter.drawPixmap(
            QRectF(x, y, w, h),
            self._pixmap,
            QRectF(0, 0, self._pixmap.width(), self._pixmap.height()),
        )
        painter.end()


class SplashScreen(QWidget):
    """启动动画窗口

    特性：
    - 屏幕中心显示
    - 高帧率图标缩放脉动（200fps 自定义定时器）
    - 状态文字 + 点动画
    - 事件驱动：初始化完成后由外部触发淡出
    - 无边框、透明背景
    """

    _active_splash: list = []

    DOT_INTERVAL = 400
    FADE_OUT_DURATION = 300
    ICON_SIZE = 120

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._icon_pixmap: Optional[QPixmap] = None
        self._setup_ui()
        self._position_window()

        self._opacity_animation: Optional[QPropertyAnimation] = None

        # 高帧率缩放定时器
        self._scale_timer = QTimer(self)
        self._scale_timer.timeout.connect(self._tick_scale)
        self._scale_timer.setInterval(FRAME_INTERVAL)
        self._scale_start = 0.0

        # 点动画定时器
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._update_dots)
        self._dot_count = 0

        self._on_finished_callback: Optional[callable] = None
        self._status_text = "正在启动"

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.setSpacing(8)

        self._load_icon_pixmap()

        self._icon_widget = PulsingIcon(self._icon_pixmap, self.ICON_SIZE)
        layout.addWidget(self._icon_widget, 0, Qt.AlignmentFlag.AlignCenter)

        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            "color: #555; font-size: 14px; background-color: transparent;"
        )
        layout.addWidget(self._status_label)

        self.setFixedSize(self.ICON_SIZE + 60, self.ICON_SIZE + 106)

    def _load_icon_pixmap(self):
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                self._icon_pixmap = pixmap.scaled(
                    self.ICON_SIZE, self.ICON_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                return
        self._create_fallback_pixmap()

    def _create_fallback_pixmap(self):
        pixmap = QPixmap(self.ICON_SIZE, self.ICON_SIZE)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = 8
        painter.setBrush(QColor(0, 122, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(margin, margin, self.ICON_SIZE - 2 * margin, self.ICON_SIZE - 2 * margin)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 56, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Q")
        painter.end()
        self._icon_pixmap = pixmap

    def _position_window(self):
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2 + geo.x()
            y = (geo.height() - self.height()) // 2 + geo.y()
            self.move(x, y)

    def set_status(self, text: str):
        self._status_text = text
        self._status_label.setText(text)

    def _update_dots(self):
        self._dot_count = (self._dot_count + 1) % 4
        dots = "·" * self._dot_count if self._dot_count > 0 else ""
        self._status_label.setText(f"{self._status_text}{dots.ljust(3)}")

    # ── 高帧率缩放动画 ──────────────────────────────────────

    def _tick_scale(self):
        """每帧更新缩放值（200fps）"""
        elapsed = (_time.perf_counter() - self._scale_start) * 1000.0  # ms
        t = (elapsed % CYCLE_DURATION) / CYCLE_DURATION           # 0..1
        # InOutSine: 0→1→0 over one cycle
        eased = (1.0 - math.cos(2.0 * math.pi * t)) / 2.0
        scale = 1.0 - (1.0 - SCALE_MIN) * eased
        self._icon_widget.set_scale(scale)

    def _start_scale_animation(self):
        """启动缩放脉动定时器"""
        self._scale_start = _time.perf_counter()
        self._scale_timer.start()

    # ── 生命周期 ────────────────────────────────────────────

    def show_splash(self, on_finished: Optional[callable] = None):
        self._on_finished_callback = on_finished
        SplashScreen._active_splash.append(self)
        self.show()

        self._start_scale_animation()
        self._status_label.setText(f"{self._status_text}   ")
        self._dot_timer.start(self.DOT_INTERVAL)

    def start_fade_out(self, on_finished: Optional[callable] = None):
        if on_finished is not None:
            self._on_finished_callback = on_finished

        self._scale_timer.stop()
        self._icon_widget.set_scale(1.0)

        self._dot_timer.stop()
        self._status_label.setText(f"{self._status_text} \u2713")
        QTimer.singleShot(250, self._do_fade_out)

    def _do_fade_out(self):
        self._opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_animation.setDuration(self.FADE_OUT_DURATION)
        self._opacity_animation.setStartValue(1.0)
        self._opacity_animation.setEndValue(0.0)
        self._opacity_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._opacity_animation.finished.connect(self._on_fade_out_finished)
        self._opacity_animation.start()

    def _on_fade_out_finished(self):
        if self._opacity_animation:
            self._opacity_animation.deleteLater()
            self._opacity_animation = None
        if self in SplashScreen._active_splash:
            SplashScreen._active_splash.remove(self)
        self.close()
        self.deleteLater()
        if self._on_finished_callback:
            self._on_finished_callback()
            self._on_finished_callback = None


def show_splash_screen(on_finished: Optional[callable] = None) -> SplashScreen:
    splash = SplashScreen()
    splash.show_splash(on_finished)
    return splash
