"""启动动画窗口 - 在屏幕中心显示应用程序图标，带有渐变动画效果"""
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QColor, QPainter, QFont


class SplashScreen(QWidget):
    """启动动画窗口
    
    特性：
    - 屏幕中心显示
    - 渐变淡出动画
    - 短暂停留
    - 无边框、透明背景
    """

    # 全局列表，保持 Splash 引用防止被垃圾回收
    _active_splash: list = []

    # 动画时长配置（毫秒）
    STAY_DURATION = 1000        # 停留时长
    FADE_OUT_DURATION = 300     # 淡出时长
    ICON_SIZE = 120             # 图标大小

    def __init__(self):
        """初始化启动动画窗口"""
        super().__init__()

        # 设置窗口属性：无边框、置顶、透明背景
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._setup_ui()
        self._position_window()

        # 窗口透明度动画
        self._opacity_animation: Optional[QPropertyAnimation] = None

        # 状态定时器
        self._stay_timer = QTimer(self)
        self._stay_timer.setSingleShot(True)
        self._stay_timer.timeout.connect(self._start_fade_out)

        # 动画完成回调
        self._on_finished_callback: Optional[callable] = None

    def _setup_ui(self):
        """设置 UI"""
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 图标标签 - 确保透明背景
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("background-color: transparent;")

        # 加载图标
        self._load_icon()

        layout.addWidget(self._icon_label)

        # 设置窗口大小
        self.setFixedSize(self.ICON_SIZE + 60, self.ICON_SIZE + 60)

    def _load_icon(self):
        """加载应用程序图标"""
        # 尝试从 assets 目录加载 PNG 图标
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"

        if icon_path.exists():
            # 加载 PNG 图标
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # 缩放到目标大小，保持原始颜色
                scaled_pixmap = pixmap.scaled(
                    self.ICON_SIZE, self.ICON_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self._icon_label.setPixmap(scaled_pixmap)
                return

        # 如果加载失败，绘制备用图标
        self._create_fallback_icon()

    def _create_fallback_icon(self):
        """绘制应用程序图标（蓝色圆形背景 + 白色 T）"""
        pixmap = QPixmap(self.ICON_SIZE, self.ICON_SIZE)
        pixmap.fill(QColor(0, 0, 0, 0))  # 透明背景

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制蓝色圆形背景
        margin = 8
        painter.setBrush(QColor(0, 122, 255))  # macOS 风格现代蓝
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(margin, margin, self.ICON_SIZE - 2*margin, self.ICON_SIZE - 2*margin)

        # 绘制白色 "Q" 字
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Arial", 56, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Q")

        painter.end()

        self._icon_label.setPixmap(pixmap)

    def _position_window(self):
        """定位窗口 - 屏幕中心"""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2 + screen_geo.x()
            y = (screen_geo.height() - self.height()) // 2 + screen_geo.y()
            self.move(x, y)

    def show_splash(self, on_finished: Optional[callable] = None):
        """显示启动动画
        
        Args:
            on_finished: 动画完成后的回调函数
        """
        self._on_finished_callback = on_finished

        # 添加到全局列表，防止被垃圾回收
        SplashScreen._active_splash.append(self)

        # 直接显示（无淡入动画，保持颜色正常）
        self.show()

        # 立即开始停留计时
        self._stay_timer.start(self.STAY_DURATION)

    def _start_fade_out(self):
        """开始淡出动画"""
        self._opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_animation.setDuration(self.FADE_OUT_DURATION)
        self._opacity_animation.setStartValue(1.0)
        self._opacity_animation.setEndValue(0.0)
        self._opacity_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # 淡出完成后关闭窗口
        self._opacity_animation.finished.connect(self._on_fade_out_finished)
        self._opacity_animation.start()

    def _on_fade_out_finished(self):
        """淡出动画完成"""
        # 清理动画对象
        if self._opacity_animation:
            self._opacity_animation.deleteLater()
            self._opacity_animation = None

        # 从全局列表移除引用
        if self in SplashScreen._active_splash:
            SplashScreen._active_splash.remove(self)

        # 关闭窗口
        self.close()
        self.deleteLater()

        # 执行回调
        if self._on_finished_callback:
            self._on_finished_callback()
            self._on_finished_callback = None


def show_splash_screen(on_finished: Optional[callable] = None) -> SplashScreen:
    """显示启动动画（便捷函数）
    
    Args:
        on_finished: 动画完成后的回调函数
        
    Returns:
        SplashScreen 实例
    """
    splash = SplashScreen()
    splash.show_splash(on_finished)
    return splash
