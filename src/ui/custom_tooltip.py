# -*- coding: utf-8 -*-
"""自定义 Tooltip 实现（替代 Qt 原生 QToolTip）。

Qt 6 原生 QToolTip（QTipLabel 单例）在 Windows 上存在无法根治的问题：
1. 首帧按 QApplication 默认字体渲染，QSS 生效后才重算尺寸，
   首次显示会出现「先大后小」的缩放动画；
2. 样式缓存不随主题切换失效，深色切浅色后仍可能黑底。

因此用自定义顶层 ToolTip 窗口 + QLabel 完全替代：样式由自身 QSS
（ID 选择器，不影响其他控件）控制，字体在 setText 前已固定为 12px，
首次显示即最终大小，无任何尺寸动画。
"""
from typing import Optional

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..utils.theme import ThemeManager, get_theme

_FONT_PX = 12
_HIDE_MS_PER_CHAR = 60      # 超时隐藏：约 60ms/字符（近似原生节奏）
_HIDE_MS_MIN = 2000
_HIDE_MS_MAX = 10000
_OFFSET = QPoint(16, 20)    # 光标右下方偏移（近似原生 QToolTip 位置）
_MAX_WIDTH_MARGIN = 80      # 长文本换行：屏幕可用宽减去此边距


class CustomTooltip(QFrame):
    """应用级 tooltip 单例（懒加载创建，首次悬停时才实例化）。"""

    _instance: Optional['CustomTooltip'] = None
    _source: Optional[QWidget] = None

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # 不抢鼠标事件：悬停气泡上仍可正常点击下层控件
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # 整体透明画布，仅 QSS 圆角背景可见（圆角外透出屏幕）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("customTooltip")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(self)
        self._label.setObjectName("customTooltipLabel")
        self._label.setWordWrap(True)
        # 字体直接固定为 12px（不依赖 QSS font-size 的 polish 时序）
        _font = QFont(self._label.font())
        _font.setPixelSize(_FONT_PX)
        self._label.setFont(_font)
        layout.addWidget(self._label)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self._apply_theme()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    # ---------- 单例接口 ----------

    @classmethod
    def instance(cls) -> 'CustomTooltip':
        if cls._instance is None:
            cls._instance = CustomTooltip()
        return cls._instance

    @classmethod
    def show_text(cls, text: str, global_pos: QPoint,
                  source: Optional[QWidget] = None) -> None:
        """在 global_pos 附近显示 tooltip（替代 QToolTip.showText）。"""
        tip = cls.instance()
        cls._source = source
        tip._label.setText(text)
        tip._limit_width(global_pos)
        tip._label.adjustSize()
        tip.adjustSize()
        tip._move_near(global_pos)
        tip._restart_hide_timer()
        tip.show()
        tip.raise_()

    @classmethod
    def hide_tip(cls) -> None:
        if cls._instance is not None and cls._instance.isVisible():
            cls._instance.hide()

    @classmethod
    def is_shown_for(cls, widget: QWidget) -> bool:
        return (cls._instance is not None
                and cls._instance.isVisible()
                and cls._source is widget)

    # ---------- 内部 ----------

    def _apply_theme(self) -> None:
        theme = get_theme()
        self.setStyleSheet(f"""
            #customTooltip {{
                background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
            }}
            #customTooltipLabel {{
                color: {theme['text_primary']};
                background: transparent;
                padding: 4px 8px;
            }}
        """)

    def _limit_width(self, pos: QPoint) -> None:
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            self._label.setMaximumWidth(
                max(100, screen.availableGeometry().width() - _MAX_WIDTH_MARGIN))
        else:
            self._label.setMaximumWidth(16777215)

    def _move_near(self, pos: QPoint) -> None:
        p = QPoint(pos + _OFFSET)
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            if p.x() + self.width() > avail.right():
                p.setX(max(avail.left(), pos.x() - _OFFSET.x() - self.width()))
            if p.y() + self.height() > avail.bottom():
                p.setY(max(avail.top(), pos.y() - _OFFSET.y() - self.height()))
        self.move(p)

    def _restart_hide_timer(self) -> None:
        ms = max(_HIDE_MS_MIN,
                 min(len(self._label.text()) * _HIDE_MS_PER_CHAR, _HIDE_MS_MAX))
        self._hide_timer.start(ms)

    def _on_theme_changed(self) -> None:
        self._apply_theme()
        if self.isVisible():
            self._label.adjustSize()
            self.adjustSize()
