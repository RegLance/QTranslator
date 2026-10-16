"""截图模块：获取框选区域的 QImage。

采集与框选分离：

- 采集用 python-mss（MIT，纯 ctypes，Windows 走 GDI）：直接给出每块屏的
  真实物理像素矩形（left/top/width/height），从根本上解决多屏、不同 DPI 缩放
  下的「黑边/错位」——之前把 QScreen.geometry() 的逻辑坐标直接当物理坐标用，
  在混合缩放下必然错位。
- 框选用「每块屏一个遮罩窗口」（ScreenshotOverlay）。单个 QWidget 跨多块不同
  缩放比例的屏幕时，Qt 只会按其中一块屏的 DPR 渲染整窗、导致副屏错位，所以必须
  一块屏一个窗口、各自按本屏 DPR 渲染。遮罩不再画截图底图，而是「半透明蒙层 +
  选区擦除亮显」直接透出真实屏幕，既省性能又不会错位。
- 确认后按每块屏的 devicePixelRatio 把逻辑选区映射回物理坐标，从 mss 抓的
  物理底图上裁剪拼接。mss 不可用时回退到 QScreen.grabWindow 的旧实现。

关键点：不能用 QRubberBand 的 grab 结果（会得到透明空白图），必须用框选坐标到
已抓取的「全屏底图」上裁剪。
"""
import time
from typing import List, Optional, Tuple

from PyQt6.QtCore import QEventLoop, QPoint, QPointF, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget


def _log(msg: str) -> None:
    """写截图相关日志（懒加载 logger，避免模块导入顺序/循环问题）。"""
    try:
        from ..utils.logger import log_debug
    except ImportError:
        from src.utils.logger import log_debug
    log_debug(f"[screenshot] {msg}")


def _log_exception(msg: str) -> None:
    try:
        from ..utils.logger import log_exception
    except ImportError:
        from src.utils.logger import log_exception
    log_exception(f"[screenshot] {msg}")


def _flush_log() -> None:
    try:
        from ..utils.logger import log_flush
    except ImportError:
        from src.utils.logger import log_flush
    log_flush()


def _mss_to_qpixmap(shot) -> QPixmap:
    """mss 抓图（BGRA 原始字节）→ QPixmap（物理像素）。

    mss 的 shot.bgra 是 [B,G,R,A] 顺序的 32 位字节流；QImage.Format_RGB32 的
    内存布局恰为 [B,G,R,0xff]，两者对齐，颜色正确且不透明。

    关键：QImage(bytes, ...) 只是「包装」mss 的字节缓冲区、并不复制，一旦 shot
    和 mss 上下文释放，这块内存就是野指针，后续 copy()/drawPixmap() 会段错误
    （即「闪退」）。必须立即 .copy() 深拷贝脱离该缓冲区。
    """
    img = QImage(shot.bgra, shot.width, shot.height, shot.width * 4,
                 QImage.Format.Format_RGB32)
    return QPixmap.fromImage(img.copy())


def _screen_captures() -> List[Tuple[QRect, QRect, float, QPixmap]]:
    """抓取每块屏，返回 (逻辑矩形, 物理矩形, DPR, 抓图)。优先 mss，失败回退 Qt。"""
    try:
        return _screen_captures_mss()
    except Exception:
        _log_exception("mss 抓屏失败，回退 QScreen.grabWindow")
        return _screen_captures_qt()


def _screen_captures_mss() -> List[Tuple[QRect, QRect, float, QPixmap]]:
    """用 mss 逐屏抓取：逻辑矩形来自 Qt，物理矩形/像素来自 mss。"""
    import mss

    screens = sorted(QGuiApplication.screens(),
                     key=lambda s: (s.geometry().x(), s.geometry().y()))
    caps: List[Tuple[QRect, QRect, float, QPixmap]] = []
    with mss.mss() as sct:
        monitors = sorted(sct.monitors[1:], key=lambda m: (m["left"], m["top"]))
        _log(f"mss 屏数={len(monitors)}，Qt 屏数={len(screens)}")
        for s, mon in _pair_screens(screens, monitors):
            geo = s.geometry()
            dpr = s.devicePixelRatio()
            logical = QRect(geo)
            if mon is None:
                # 配对失败：用逻辑原点 × DPR 近似（单屏/均一缩放下正确）
                pw = round(geo.width() * dpr)
                ph = round(geo.height() * dpr)
                mon = {"left": round(geo.x() * dpr), "top": round(geo.y() * dpr),
                       "width": pw, "height": ph}
            physical = QRect(mon["left"], mon["top"], mon["width"], mon["height"])
            shot = sct.grab({"left": mon["left"], "top": mon["top"],
                             "width": mon["width"], "height": mon["height"]})
            caps.append((logical, physical, dpr, _mss_to_qpixmap(shot)))
    return caps


def _pair_screens(screens, monitors):
    """按位置顺序配对 Qt 屏幕与 mss 物理显示器；数量不符时退化为物理尺寸匹配。

    两侧都按 (x, y) 升序排列后，物理/逻辑的左右上下相对顺序一致，逐位配对即可
    正确处理同尺寸、不同 DPI 的多屏。
    """
    if len(screens) == len(monitors):
        return list(zip(screens, monitors))
    pairs = []
    remaining = list(monitors)
    for s in screens:
        geo = s.geometry()
        dpr = s.devicePixelRatio()
        pw = round(geo.width() * dpr)
        ph = round(geo.height() * dpr)
        matched = None
        for i, m in enumerate(remaining):
            if m["width"] == pw and m["height"] == ph:
                matched = remaining.pop(i)
                break
        pairs.append((s, matched))
    return pairs


def _screen_captures_qt() -> List[Tuple[QRect, QRect, float, QPixmap]]:
    """回退实现：QScreen.grabWindow（单屏/均一缩放下正确）。"""
    caps = []
    for s in QGuiApplication.screens():
        geo = s.geometry()
        dpr = s.devicePixelRatio()
        logical = QRect(geo)
        physical = QRect(geo.x(), geo.y(),
                         round(geo.width() * dpr), round(geo.height() * dpr))
        caps.append((logical, physical, dpr, s.grabWindow(0)))
    return caps


class ScreenshotSession:
    """跨屏共享的框选状态与结果（选区坐标均为虚拟桌面逻辑坐标）。"""

    def __init__(self):
        self.caps: List[Tuple[QRect, QRect, float, QPixmap]] = []
        self.overlays: List["ScreenshotOverlay"] = []
        self.loop: Optional[QEventLoop] = None
        self.origin: Optional[QPoint] = None
        self.selection: Optional[QRect] = None
        self.result_selection: Optional[QRect] = None

    def set_selection(self, rect: QRect):
        self.selection = rect
        for ov in self.overlays:
            ov.update()
            ov._update_toolbar()

    def active_overlay(self) -> Optional["ScreenshotOverlay"]:
        """选区右下角落在哪块屏，确认/取消按钮就显示在哪块屏的遮罩上。"""
        if self.selection is not None:
            br = self.selection.bottomRight()
            for ov in self.overlays:
                if ov._logical.contains(br):
                    return ov
        return self.overlays[-1] if self.overlays else None

    def finish(self, selection: Optional[QRect]):
        self.result_selection = selection
        if self.loop is not None:
            self.loop.quit()


class ScreenshotOverlay(QWidget):
    """单个显示器上的遮罩窗口：半透明蒙层 + 选区擦除亮显。

    每个屏一个实例、覆盖该屏的「逻辑矩形」，Qt 会按本屏 DPR 正确渲染，避免
    单窗跨屏时的缩放错位。
    """

    def __init__(self, session: ScreenshotSession, logical_rect: QRect):
        super().__init__()
        self._session = session
        self._logical = QRect(logical_rect)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(self._logical)

        # 选区右下角的确认/取消按钮（框选完成后显示）
        self._tool_confirm = self._make_tool_button(True)
        self._tool_cancel = self._make_tool_button(False)
        self._tool_confirm.hide()
        self._tool_cancel.hide()

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
        btn.clicked.connect(self._confirm if confirm else self._cancel)
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
        """把确认/取消按钮放到选区右下角（仅显示在当前活动遮罩上）。"""
        active = self._session.active_overlay()
        if active is not self:
            self._tool_confirm.hide()
            self._tool_cancel.hide()
            return
        sel = self._session.selection
        if sel is None or sel.width() <= 1 or sel.height() <= 1:
            self._tool_confirm.hide()
            self._tool_cancel.hide()
            return
        inter = self._logical.intersected(sel)
        if inter.isEmpty():
            self._tool_confirm.hide()
            self._tool_cancel.hide()
            return
        local = inter.translated(-self._logical.x(), -self._logical.y())
        gap = 4
        w = self._tool_confirm.width()
        total = w * 2 + gap
        x = max(0, local.right() - total)
        y = local.bottom() + 6
        if y + w > self.height():
            y = local.bottom() - w - 6
        self._tool_cancel.move(x, y)
        self._tool_confirm.move(x + w + gap, y)
        self._tool_cancel.show()
        self._tool_confirm.show()
        self._tool_cancel.raise_()
        self._tool_confirm.raise_()

    # ---- 绘制 ----
    def paintEvent(self, event):
        painter = QPainter(self)
        # 半透明暗色蒙层，透出真实屏幕
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        sel = self._session.selection
        if sel is not None and sel.width() > 0 and sel.height() > 0:
            inter = self._logical.intersected(sel)
            if not inter.isEmpty():
                local = inter.translated(-self._logical.x(), -self._logical.y())
                # 擦除选区蒙层，露出真实屏幕（明亮）
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                painter.fillRect(local, QColor(0, 0, 0, 0))
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                painter.setPen(QPen(QColor(0, 122, 255), 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(local)
        painter.end()

    # ---- 交互 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._tool_confirm.hide()
            self._tool_cancel.hide()
            self._session.origin = event.globalPosition().toPoint()
            self._session.set_selection(QRect(self._session.origin, self._session.origin))
            self.grabMouse()
            self.activateWindow()
            self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def mouseMoveEvent(self, event):
        if self._session.origin is not None:
            rect = QRect(self._session.origin,
                         event.globalPosition().toPoint()).normalized()
            self._session.set_selection(rect)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._session.origin is not None:
            rect = QRect(self._session.origin,
                         event.globalPosition().toPoint()).normalized()
            self._session.origin = None
            self._session.set_selection(rect)
            self.releaseMouse()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._confirm()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm()
        else:
            super().keyPressEvent(event)

    def _confirm(self):
        sel = self._session.selection
        if sel is not None and sel.width() > 1 and sel.height() > 1:
            self._session.finish(sel)
        else:
            self._session.finish(None)

    def _cancel(self):
        self._session.finish(None)


def _crop_selection(caps: List[Tuple[QRect, QRect, float, QPixmap]],
                    selection: QRect) -> Optional[QImage]:
    """把逻辑选区逐屏映射到物理坐标并裁剪，拼成一张最终图（物理像素）。"""
    parts = []  # (物理全局矩形, 裁剪出的 QPixmap)
    for logical, physical, dpr, grab in caps:
        inter = logical.intersected(selection)
        if inter.isEmpty():
            continue
        off = inter.topLeft() - logical.topLeft()
        px = physical.x() + round(off.x() * dpr)
        py = physical.y() + round(off.y() * dpr)
        pw = round(inter.width() * dpr)
        ph = round(inter.height() * dpr)
        crop = grab.copy(QRect(px - physical.x(), py - physical.y(), pw, ph))
        parts.append((QRect(px, py, pw, ph), crop))
    if not parts:
        return None
    left = min(r.left() for r, _ in parts)
    top = min(r.top() for r, _ in parts)
    right = max(r.right() for r, _ in parts)
    bottom = max(r.bottom() for r, _ in parts)
    result = QImage(right - left + 1, bottom - top + 1,
                    QImage.Format.Format_ARGB32)
    result.fill(Qt.GlobalColor.black)
    painter = QPainter(result)
    for r, crop in parts:
        painter.drawPixmap(r.left() - left, r.top() - top, crop)
    painter.end()
    return result


def capture_region(hide_windows: Optional[List] = None) -> Optional[QImage]:
    """框选截屏，返回选中区域 QImage；取消返回 None。

    hide_windows：截屏前先隐藏的窗口（如翻译窗口，避免其出现在截图中），
    截屏结束后统一恢复显示并置前。
    """
    _log("开始框选截图")
    hidden = []
    if hide_windows:
        for w in hide_windows:
            if w is not None and w.isVisible():
                w.hide()
                hidden.append(w)

    # 让隐藏的窗口真正从屏幕消失，再抓取
    QApplication.processEvents()
    time.sleep(0.2)

    overlays: List[ScreenshotOverlay] = []
    try:
        caps = _screen_captures()
        if not caps:
            _log("未抓到任何屏幕，取消")
            return None

        session = ScreenshotSession()
        session.caps = caps
        for logical, _p, _d, _g in caps:
            overlays.append(ScreenshotOverlay(session, logical))
        session.overlays = overlays

        loop = QEventLoop()
        session.loop = loop
        for ov in overlays:
            ov.show()
        if overlays:
            overlays[0].raise_()
            overlays[0].activateWindow()
            overlays[0].setFocus(Qt.FocusReason.ActiveWindowFocusReason)

        loop.exec()

        sel = session.result_selection
        result = _crop_selection(caps, sel) if sel is not None else None
        has = result is not None and not result.isNull()
        _log(f"框选完成: {'有图' if has else '取消'}"
             + (f"，尺寸={result.width()}x{result.height()}" if has else ""))
        _flush_log()
        return result
    finally:
        for ov in overlays:
            try:
                ov.releaseMouse()
                ov.close()
            except RuntimeError:
                pass
        for w in hidden:
            try:
                w.show()
                w.raise_()
                w.activateWindow()
            except RuntimeError:
                pass  # 窗口已被销毁，忽略
