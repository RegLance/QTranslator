"""全屏框选截图 + OCR（RapidOCR）。"""
from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPen, QPixmap, QScreen
from PyQt6.QtWidgets import QWidget

try:
    from ..utils.logger import log_debug, log_error, log_info
except ImportError:
    from src.utils.logger import log_debug, log_error, log_info


def virtual_desktop_rect() -> QRect:
    """所有显示器几何的并集（全局桌面坐标）。"""
    screens = QGuiApplication.screens()
    if not screens:
        return QRect()
    u = screens[0].geometry()
    for s in screens[1:]:
        u = u.united(s.geometry())
    return u


def _composite_desktop_pixmap(union: QRect) -> QPixmap:
    """拼接所有屏幕的 grab，与 union 对齐（多显示器 OCR 选区）。

    使用虚拟桌面「逻辑像素」尺寸的底图，将每块 grab 缩放绘制到对应 screen.geometry()
    矩形内。避免旧实现用整桌 max(devicePixelRatio) 画布 + 左上角对齐粘贴各屏 pixmap 时，
    与各屏实际 DPR/像素尺寸不一致而出现大段未覆盖黑区（常见于左右/上下排列且缩放比例不同）。
    """
    screens = QGuiApplication.screens()
    if not screens or union.isNull():
        return QPixmap()
    w, h = union.width(), union.height()
    if w <= 0 or h <= 0:
        return QPixmap()
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(QColor(0, 0, 0))
    painter = QPainter(image)
    for screen in screens:
        sg = screen.geometry()
        ox = sg.x() - union.x()
        oy = sg.y() - union.y()
        chunk = screen.grabWindow(0)
        if chunk.isNull():
            log_debug(f"截图识字: grabWindow 为空, screen={screen.name()!r}")
            continue
        dst = QRect(ox, oy, sg.width(), sg.height())
        src = QRect(0, 0, chunk.width(), chunk.height())
        # PyQt6：三参数重载要求目标矩形与源矩形同为 QRect 或同为 QRectF，不可混用。
        painter.drawPixmap(dst, chunk, src)
    painter.end()
    return QPixmap.fromImage(image)


class SnipOverlay(QWidget):
    """拼接全部显示器画面后，在虚拟桌面上框选区域。"""

    region_captured = pyqtSignal(object)  # QPixmap
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        geo = virtual_desktop_rect()
        self.setGeometry(geo)
        self._pixmap = _composite_desktop_pixmap(geo)
        self._start = None
        self._current = None
        self._selecting = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._pixmap, self._pixmap.rect())
        shade = QColor(0, 0, 0, 110)
        if self._selecting and self._start and self._current:
            r = QRect(self._start, self._current).normalized()
            W, H = self.width(), self.height()
            painter.fillRect(0, 0, W, max(0, r.top()), shade)
            painter.fillRect(0, max(0, r.bottom()), W, max(0, H - r.bottom()), shade)
            painter.fillRect(0, r.top(), max(0, r.left()), r.height(), shade)
            painter.fillRect(r.right(), r.top(), max(0, W - r.right()), r.height(), shade)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r.adjusted(0, 0, -1, -1))
        else:
            painter.fillRect(self.rect(), shade)

    def showEvent(self, event):
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._selecting = True
            self._start = event.pos()
            self._current = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            r = QRect(self._start, event.pos()).normalized()
            if r.width() >= 4 and r.height() >= 4:
                self._emit_crop(r)
            else:
                self.cancelled.emit()
            self.deleteLater()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.deleteLater()
            return
        super().keyPressEvent(event)

    def _emit_crop(self, rect: QRect):
        dpr = float(self._pixmap.devicePixelRatio() or 1.0)
        dx = int(round(rect.x() * dpr))
        dy = int(round(rect.y() * dpr))
        dw = max(1, int(round(rect.width() * dpr)))
        dh = max(1, int(round(rect.height() * dpr)))
        cropped = self._pixmap.copy(dx, dy, dw, dh)
        if cropped.isNull():
            log_debug("截图识字: 裁剪结果为空")
            self.cancelled.emit()
            return
        self.region_captured.emit(cropped)


class RapidOcrWorkerThread(QThread):
    """在后台线程运行 OCR。传入主线程已转好的 RGB numpy（H×W×3 uint8），禁止传 QPixmap。"""

    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, rgb_numpy: "object", parent=None):
        super().__init__(parent)
        self._rgb_numpy = rgb_numpy

    def run(self):
        try:
            sh = getattr(self._rgb_numpy, "shape", None)
            log_info(f"[OCR] 工作线程 run() 开始, ndarray shape={sh}")
            try:
                from ..utils.rapidocr_engine import run_ocr_on_rgb_numpy
            except ImportError:
                from src.utils.rapidocr_engine import run_ocr_on_rgb_numpy
            text = run_ocr_on_rgb_numpy(self._rgb_numpy)
            log_info(f"[OCR] 工作线程 run() 结束, 返回文本长度={len(text or '')}")
            self.finished_ok.emit(text or "")
        except Exception as e:
            log_error(f"RapidOCR 执行失败: {e}")
            self.failed.emit(str(e))


def screen_at_cursor() -> QScreen:
    screen = QGuiApplication.screenAt(QCursor.pos())
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    return screen
