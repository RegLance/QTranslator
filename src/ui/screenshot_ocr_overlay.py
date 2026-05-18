"""全屏框选截图 + OCR（RapidOCR）。"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap, QScreen
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
    """拼接所有屏幕的 grab，与 union 对齐（多显示器 OCR 选区）。"""
    screens = QGuiApplication.screens()
    if not screens or union.isNull():
        log_info("[OCR][截图拼接] 中止: 无屏幕或 union 为空")
        return QPixmap()

    max_dpr = max(float(s.devicePixelRatio() or 1.0) for s in screens)
    w_px = int(union.width() * max_dpr)
    h_px = int(union.height() * max_dpr)

    log_info(
        "[OCR][截图拼接] 虚拟桌面 union=(%d,%d) 逻辑=%d×%d | max_dpr=%.4f | "
        "画布像素=%d×%d | 屏幕数=%d"
        % (
            union.x(),
            union.y(),
            union.width(),
            union.height(),
            max_dpr,
            w_px,
            h_px,
            len(screens),
        )
    )

    for i, s in enumerate(screens):
        sg = s.geometry()
        ag = s.availableGeometry()
        ps = (s.physicalDotsPerInchX(), s.physicalDotsPerInchY())
        log_info(
            "[OCR][截图拼接] 屏[%d] name=%r primary=%s | geometry=(%d,%d) %d×%d | "
            "available=(%d,%d) %d×%d | dpr=%s | dpi=(%.1f,%.1f)"
            % (
                i,
                s.name(),
                s == QGuiApplication.primaryScreen(),
                sg.x(),
                sg.y(),
                sg.width(),
                sg.height(),
                ag.x(),
                ag.y(),
                ag.width(),
                ag.height(),
                s.devicePixelRatio(),
                ps[0],
                ps[1],
            )
        )

    if w_px <= 0 or h_px <= 0:
        log_info("[OCR][截图拼接] 中止: 画布尺寸无效")
        return QPixmap()

    result = QPixmap(w_px, h_px)
    result.setDevicePixelRatio(max_dpr)
    result.fill(QColor(0, 0, 0))
    painter = QPainter(result)
    for i, screen in enumerate(screens):
        sg = screen.geometry()
        ox = sg.x() - union.x()
        oy = sg.y() - union.y()
        chunk = screen.grabWindow(0)
        cw = chunk.width()
        ch = chunk.height()
        cdpr = float(chunk.devicePixelRatio() or 1.0)
        # 说明：用户肉眼「整屏往左移、右侧一条黑」常见对应关系是——在 union 坐标里，
        # 该屏区块「应该」占满 [ox, ox+geo.w)，但若 grab 在 QPainter 里绘出的逻辑宽度
        # < geo.w，则右侧会露合成底色的黑（不是遮罩画上去的）。
        exp_right = ox + sg.width()
        content_right = ox + cw  # PyQt6：一般为设备无关像素宽，与 drawPixmap 铺宽一致
        h_gap_px = sg.width() - cw
        log_info(
            "[OCR][截图拼接] 粘贴[%d] offset_union=(%d,%d) | grab null=%s | "
            "chunk=%d×%d chunk_dpr=%.4f | geo 逻辑=%d×%d | "
            "差(chunk−geo)=(%d,%d) | 水平: 内容右沿=%d geo右沿=%d 未铺满宽(+=右侧黑)=%d"
            % (
                i,
                ox,
                oy,
                chunk.isNull(),
                cw,
                ch,
                cdpr,
                sg.width(),
                sg.height(),
                cw - sg.width(),
                ch - sg.height(),
                content_right,
                exp_right,
                h_gap_px,
            )
        )
        if chunk.isNull():
            continue
        painter.drawPixmap(QPoint(ox, oy), chunk)
    painter.end()

    rdpr = float(result.devicePixelRatio() or 1.0)
    log_w = result.width()
    log_h = result.height()
    approx_logical_w = log_w / rdpr if rdpr else float(log_w)
    approx_logical_h = log_h / rdpr if rdpr else float(log_h)
    log_info(
        "[OCR][截图拼接] 合成完成 result 报告 size=%d×%d dpr=%.4f | "
        "约逻辑尺寸 %.1f×%.1f (size/dpr) | 期望逻辑 %d×%d"
        % (
            log_w,
            log_h,
            rdpr,
            approx_logical_w,
            approx_logical_h,
            union.width(),
            union.height(),
        )
    )
    return result


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
        log_info(
            "[OCR][截图叠加] SnipOverlay geometry=(%d,%d) %d×%d | widget_dpr=%.4f"
            % (geo.x(), geo.y(), geo.width(), geo.height(), self.devicePixelRatio())
        )
        self._pixmap = _composite_desktop_pixmap(geo)
        pm = self._pixmap
        log_info(
            "[OCR][截图叠加] 底图 QPixmap 报告 size=%d×%d dpr=%.4f | "
            "控件逻辑=%d×%d | 若二者逻辑尺寸不一致 paint 会错位/露黑"
            % (
                pm.width(),
                pm.height(),
                float(pm.devicePixelRatio() or 1.0),
                self.width(),
                self.height(),
            )
        )
        self._start = None
        self._current = None
        self._selecting = False
        self._paint_logged = False

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self._paint_logged:
            self._paint_logged = True
            pm = self._pixmap
            pm_dpr = float(pm.devicePixelRatio() or 1.0)
            wg_dpr = float(self.devicePixelRatio() or 1.0)
            dr = self.rect()
            sr = pm.rect()
            log_info(
                "[OCR][截图叠加] paintEvent(仅记一次): dest(self.rect)=%dx%d 逻辑 | "
                "src(pm.rect)=%dx%d | pm.dpr=%.4f widget.dpr=%.4f | "
                "drawPixmap 会把 src 缩放到 dest；若两边逻辑尺寸不一致会像「平移/漏边」"
                % (dr.width(), dr.height(), sr.width(), sr.height(), pm_dpr, wg_dpr)
            )
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
        wh = self.windowHandle()
        if wh is not None:
            scr = wh.screen()
            log_info(
                "[OCR][截图叠加] show 后 window dpr=%.4f | window.screen=%r"
                % (
                    wh.devicePixelRatio(),
                    scr.name() if scr is not None else None,
                )
            )
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
        dpr = self._pixmap.devicePixelRatio()
        dx = int(rect.x() * dpr)
        dy = int(rect.y() * dpr)
        dw = max(1, int(rect.width() * dpr))
        dh = max(1, int(rect.height() * dpr))
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
