"""全屏框选截图 + OCR（RapidOCR）。"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPen, QPixmap, QScreen
from PyQt6.QtWidgets import QWidget

try:
    from ..utils.logger import log_debug, log_error, log_info
except ImportError:
    from src.utils.logger import log_debug, log_error, log_info


def _pixmap_logical_size(pm: QPixmap) -> tuple[int, int]:
    dpr = float(pm.devicePixelRatio() or 1.0)
    if dpr <= 0:
        dpr = 1.0
    return int(round(pm.width() / dpr)), int(round(pm.height() / dpr))


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
    """在设备像素画布上拼接各屏 grab，供框选裁剪使用（不缩放，保持清晰）。"""
    screens = QGuiApplication.screens()
    if not screens or union.isNull():
        return QPixmap()

    max_dpr = max(float(s.devicePixelRatio() or 1.0) for s in screens)
    w_px = int(round(union.width() * max_dpr))
    h_px = int(round(union.height() * max_dpr))
    if w_px <= 0 or h_px <= 0:
        return QPixmap()

    image = QImage(w_px, h_px, QImage.Format.Format_RGB32)
    image.fill(QColor(0, 0, 0).rgb())

    painter = QPainter(image)
    for screen in screens:
        sg = screen.geometry()
        dpr = float(screen.devicePixelRatio() or 1.0)
        ox = int(round((sg.x() - union.x()) * max_dpr))
        oy = int(round((sg.y() - union.y()) * max_dpr))
        chunk = screen.grabWindow(0)
        if chunk.isNull():
            continue
        dst = QRect(ox, oy, chunk.width(), chunk.height())
        src = QRect(0, 0, chunk.width(), chunk.height())
        painter.drawPixmap(dst, chunk, src)
    painter.end()

    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(max_dpr)
    return result


class _SnipScreenPanel(QWidget):
    """单块显示器上的选区遮罩（避免 Windows 下单窗口跨屏绘制错位）。"""

    def __init__(self, screen_geom: QRect, chunk: QPixmap, controller: "SnipOverlay"):
        super().__init__(None)
        self._controller = controller
        self._chunk = chunk
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(screen_geom)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._chunk)
        shade = QColor(0, 0, 0, 110)
        sel = self._controller.selection_in_local(self)
        if sel is not None:
            r = sel
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
        self._controller.on_panel_shown(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._controller.begin_selection(self.mapToGlobal(event.pos()), self)

    def mouseMoveEvent(self, event):
        self._controller.update_selection(self.mapToGlobal(event.pos()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._controller.finish_selection(self.mapToGlobal(event.pos()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._controller.cancel()
            return
        super().keyPressEvent(event)


class SnipOverlay(QWidget):
    """多屏选区：每块屏独立窗口显示 grab，裁剪仍从虚拟桌面合成图取。"""

    region_captured = pyqtSignal(object)
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._union = virtual_desktop_rect()
        self._composite = _composite_desktop_pixmap(self._union)
        self._panels: list[_SnipScreenPanel] = []
        self._selecting = False
        self._start_global: QPoint | None = None
        self._current_global: QPoint | None = None
        self._focus_panel: _SnipScreenPanel | None = None

        screens = QGuiApplication.screens()
        log_info(
            "[OCR][截图叠加] 多屏模式 union=(%d,%d) %d×%d | 屏数=%d | 合成图=%d×%d dpr=%.4f"
            % (
                self._union.x(),
                self._union.y(),
                self._union.width(),
                self._union.height(),
                len(screens),
                self._composite.width(),
                self._composite.height(),
                float(self._composite.devicePixelRatio() or 1.0),
            )
        )
        for i, screen in enumerate(screens):
            sg = screen.geometry()
            chunk = screen.grabWindow(0)
            clw, clh = _pixmap_logical_size(chunk)
            gap_y = ""
            if i > 0:
                prev = screens[i - 1].geometry()
                gap = sg.y() - (prev.y() + prev.height())
                if gap != 0:
                    gap_y = f" | 与上一屏垂直间隙={gap}px"
            log_info(
                "[OCR][截图叠加] 屏[%d] panel geometry=(%d,%d) %d×%d | chunk 逻辑≈%d×%d%s"
                % (i, sg.x(), sg.y(), sg.width(), sg.height(), clw, clh, gap_y)
            )
            panel = _SnipScreenPanel(sg, chunk, self)
            self._panels.append(panel)

    def show(self):
        for panel in self._panels:
            panel.show()
        if self._panels:
            self._panels[0].activateWindow()
            self._panels[0].setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def close(self):
        for panel in self._panels:
            panel.close()
        super().close()

    def deleteLater(self):
        for panel in self._panels:
            panel.deleteLater()
        self._panels.clear()
        super().deleteLater()

    def on_panel_shown(self, panel: _SnipScreenPanel):
        panel.raise_()

    def begin_selection(self, global_pos: QPoint, panel: _SnipScreenPanel):
        self._selecting = True
        self._start_global = global_pos
        self._current_global = global_pos
        self._focus_panel = panel
        panel.grabMouse()
        self._repaint_panels()

    def update_selection(self, global_pos: QPoint):
        if self._selecting:
            self._current_global = global_pos
            self._repaint_panels()

    def finish_selection(self, global_pos: QPoint):
        if not self._selecting:
            return
        self._release_grab()
        self._selecting = False
        self._current_global = global_pos
        r = QRect(self._start_global, self._current_global).normalized()
        self._repaint_panels()
        if r.width() >= 4 and r.height() >= 4:
            self._emit_crop(r)
        else:
            self.cancelled.emit()
        self.deleteLater()

    def cancel(self):
        self._release_grab()
        self.cancelled.emit()
        self.deleteLater()

    def _release_grab(self):
        if self._focus_panel is not None:
            try:
                self._focus_panel.releaseMouse()
            except Exception:
                pass
            self._focus_panel = None

    def selection_in_local(self, panel: _SnipScreenPanel) -> QRect | None:
        if not self._selecting or self._start_global is None or self._current_global is None:
            return None
        gr = QRect(self._start_global, self._current_global).normalized()
        top_left = panel.mapFromGlobal(gr.topLeft())
        bottom_right = panel.mapFromGlobal(gr.bottomRight())
        lr = QRect(top_left, bottom_right).normalized()
        lr &= panel.rect()
        if lr.isNull():
            return None
        return lr

    def _repaint_panels(self):
        for panel in self._panels:
            panel.update()

    def _emit_crop(self, rect_global: QRect):
        """rect_global 为相对虚拟桌面 union 左上角的逻辑坐标。"""
        lx = rect_global.x() - self._union.x()
        ly = rect_global.y() - self._union.y()
        dpr = float(self._composite.devicePixelRatio() or 1.0)
        dx = int(round(lx * dpr))
        dy = int(round(ly * dpr))
        dw = max(1, int(round(rect_global.width() * dpr)))
        dh = max(1, int(round(rect_global.height() * dpr)))
        pw, ph = self._composite.width(), self._composite.height()
        if dx < 0:
            dw += dx
            dx = 0
        if dy < 0:
            dh += dy
            dy = 0
        if dx >= pw or dy >= ph:
            log_debug("截图识字: 裁剪区域完全在合成图外")
            self.cancelled.emit()
            return
        dw = min(dw, pw - dx)
        dh = min(dh, ph - dy)
        cropped = self._composite.copy(dx, dy, dw, dh)
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
