"""截图模块：全屏框选截图，返回选中区域的 QImage。

采用 Qt 通行标准做法（全屏遮罩 + 鼠标框选 + QScreen.grabWindow 裁剪），
PyQt6 原生、零额外依赖。关键点：不能用 QRubberBand 的 grab 结果（会得到
透明空白图），必须用框选坐标到已抓取的「全屏底图」上裁剪。

参考来源：
- Qt 论坛 "Save mouse-selected area"（规范的全屏遮罩 + 框选 + grabWindow 用法）
- tik_manager4 的 ui/widgets/screenshot.py（最小 ScreenShot 结构）
"""
import time
from typing import List, Optional

from PyQt6.QtCore import QPointF, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton


def _virtual_geometry() -> QRect:
    """所有显示器的虚拟桌面包围盒（逻辑坐标）。"""
    screens = QGuiApplication.screens()
    left = min(s.geometry().left() for s in screens)
    top = min(s.geometry().top() for s in screens)
    right = max(s.geometry().right() for s in screens)
    bottom = max(s.geometry().bottom() for s in screens)
    return QRect(left, top, right - left + 1, bottom - top + 1)


def _grab_virtual_desktop(virtual: QRect, dpr: float) -> QPixmap:
    """逐屏抓取并拼成一张覆盖虚拟桌面的底图（设备像素 = 逻辑尺寸 × dpr）。

    在「逻辑坐标」里拼图：每个屏幕按其 geometry() 的逻辑矩形贴到画布上，
    Qt 按画布的 devicePixelRatio 自动换算到设备像素。这样无论各屏缩放
    比例（DPR）是否一致，对齐都正确，不会出现偏移 / 黑边。
    """
    result = QPixmap(int(virtual.width() * dpr), int(virtual.height() * dpr))
    result.setDevicePixelRatio(dpr)
    result.fill(Qt.GlobalColor.black)
    painter = QPainter(result)
    for s in QGuiApplication.screens():
        geo = s.geometry()
        pix = s.grabWindow(0)
        # 目标矩形 = 该屏在虚拟桌面中的逻辑位置；把抓到的原始分辨率图像
        # 缩放到这个逻辑矩形（drawPixmap 自动按 dpr 上采样，各屏 DPR 无关）
        target = QRect(geo.topLeft() - virtual.topLeft(), geo.size())
        painter.drawPixmap(target, pix)
    painter.end()
    return result


class ScreenshotOverlay(QDialog):
    """全屏遮罩框选窗口：暗色蒙层 + 选区高亮，Esc 取消 / 回车或双击确认。"""

    def __init__(self, background: QPixmap, virtual: QRect, dpr: float):
        super().__init__()
        self._background = background
        self._dpr = dpr
        self._origin = None  # QPoint，拖拽起点
        self._selection: Optional[QRect] = None
        self._result_image: Optional[QImage] = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(virtual)

        # 选区右下角的确认/取消按钮（框选完成后显示）
        self._tool_confirm = self._make_tool_button(True)
        self._tool_cancel = self._make_tool_button(False)
        self._tool_confirm.hide()
        self._tool_cancel.hide()

    def showEvent(self, event):
        """显示后确保获得键盘焦点（Esc/回车 才有效）。"""
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _make_tool_button(self, confirm: bool) -> QPushButton:
        """确认（对勾）/取消（叉号）小按钮。"""
        btn = QPushButton(self)
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIcon(self._make_tool_icon(confirm))
        btn.setIconSize(QSize(20, 20))
        btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(45, 45, 45, 0.85);
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: rgba(70, 70, 70, 0.95); }
            QPushButton:pressed { background-color: rgba(25, 25, 25, 0.95); }
        """)
        btn.clicked.connect(self._confirm if confirm else self.reject)
        return btn

    @staticmethod
    def _make_tool_icon(confirm: bool) -> QIcon:
        """绘制对勾/叉号图标。"""
        pixmap = QPixmap(20, 20)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255), 2.0,
                            Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        if confirm:
            painter.drawLine(QPointF(5, 11), QPointF(9, 15))
            painter.drawLine(QPointF(9, 15), QPointF(16, 6))
        else:
            painter.drawLine(QPointF(6, 6), QPointF(14, 14))
            painter.drawLine(QPointF(14, 6), QPointF(6, 14))
        painter.end()
        return QIcon(pixmap)

    def _update_toolbar(self):
        """把确认/取消按钮放到选区右下角（越界则挪到选区内部）。"""
        if self._selection is None \
                or self._selection.width() <= 1 or self._selection.height() <= 1:
            self._tool_confirm.hide()
            self._tool_cancel.hide()
            return
        s = self._selection
        gap = 4
        w = self._tool_confirm.width()
        total = w * 2 + gap
        x = max(0, s.right() - total)
        y = s.bottom() + 6
        if y + w > self.height():
            y = s.bottom() - w - 6
        self._tool_cancel.move(x, y)
        self._tool_confirm.move(x + w + gap, y)
        self._tool_cancel.show()
        self._tool_confirm.show()
        self._tool_cancel.raise_()
        self._tool_confirm.raise_()

    # ---- 绘制 ----
    def paintEvent(self, event):
        painter = QPainter(self)
        # 底图铺满整个虚拟桌面
        painter.drawPixmap(self.rect(), self._background)
        # 全屏暗色蒙层
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        if self._selection is not None \
                and self._selection.width() > 0 and self._selection.height() > 0:
            # 选中区域显示原图（明亮），并从底图裁剪对应设备坐标
            src = self._to_device_rect(self._selection)
            painter.drawPixmap(self._selection, self._background, src)
            pen = QPen(QColor(0, 122, 255), 1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._selection)

        # 底部居中提示
        painter.setPen(QColor(255, 255, 255, 220))
        painter.drawText(
            self.rect().adjusted(0, 0, 0, -14),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            "拖动选择截图区域　Esc 取消　回车 / 双击 确认",
        )
        painter.end()

    def _to_device_rect(self, rect: QRect) -> QRect:
        d = self._dpr
        return QRect(int(rect.left() * d), int(rect.top() * d),
                     int(rect.width() * d), int(rect.height() * d))

    # ---- 交互 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._tool_confirm.hide()
            self._tool_cancel.hide()
            self._origin = event.position().toPoint()
            self._selection = QRect(self._origin, self._origin)
            self.update()

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            self._selection = QRect(
                self._origin, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            self._selection = QRect(
                self._origin, event.position().toPoint()).normalized()
            self._origin = None
            self._update_toolbar()
            self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._confirm()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm()
        else:
            super().keyPressEvent(event)

    def _confirm(self):
        if self._selection is not None \
                and self._selection.width() > 1 and self._selection.height() > 1:
            src = self._to_device_rect(self._selection)
            self._result_image = self._background.copy(src).toImage()
        self.accept()

    def result_image(self) -> Optional[QImage]:
        return self._result_image


def capture_region(hide_windows: Optional[List] = None) -> Optional[QImage]:
    """框选截屏，返回选中区域 QImage；取消返回 None。

    hide_windows：截屏前先隐藏的窗口（如翻译窗口，避免其出现在截图中），
    截屏结束后统一恢复显示并置前。
    """
    hidden = []
    if hide_windows:
        for w in hide_windows:
            if w is not None and w.isVisible():
                w.hide()
                hidden.append(w)

    # 让隐藏的窗口真正从屏幕消失，再抓取
    QApplication.processEvents()
    time.sleep(0.2)

    try:
        virtual = _virtual_geometry()
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        background = _grab_virtual_desktop(virtual, dpr)
        if background.isNull():
            return None

        overlay = ScreenshotOverlay(background, virtual, dpr)
        overlay.exec()
        return overlay.result_image()
    finally:
        for w in hidden:
            try:
                w.show()
                w.raise_()
                w.activateWindow()
            except RuntimeError:
                pass  # 窗口已被销毁，忽略
