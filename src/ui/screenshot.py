"""截图模块：获取框选区域的 QImage。

统一走「自绘全屏遮罩 + python-mss 采集」的方案：

- 采集用 python-mss（MIT，纯 ctypes，Windows 走 GDI）：它直接给出每块屏的
  真实物理像素矩形（left/top/width/height），从根本上解决多屏、不同 DPI 缩放
  下的「黑边/错位」问题——之前把 QScreen.geometry() 的逻辑坐标直接当物理坐标
  用，在混合缩放下必然错位。
- 框选用自绘遮罩（ScreenshotOverlay，逻辑坐标），确认后把逻辑选区按每块屏的
  devicePixelRatio 映射回物理坐标，再从 mss 抓的物理底图上裁剪拼接。
- mss 不可用（未安装/抓取失败）时回退到 QScreen.grabWindow 的旧实现
  （单屏 / 均一缩放下仍正确）。

关键点：不能用 QRubberBand 的 grab 结果（会得到透明空白图），必须用框选坐标到
已抓取的「全屏底图」上裁剪。
"""
import sys
import time
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton


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


def _virtual_logical_bbox(caps: List[Tuple[QRect, QRect, float, QPixmap]]) -> QRect:
    """叠加层需要覆盖的逻辑包围盒（所有屏 geometry() 的并集）。"""
    left = min(r.left() for r, _, _, _ in caps)
    top = min(r.top() for r, _, _, _ in caps)
    right = max(r.right() for r, _, _, _ in caps)
    bottom = max(r.bottom() for r, _, _, _ in caps)
    return QRect(left, top, right - left + 1, bottom - top + 1)


class ScreenshotOverlay(QDialog):
    """全屏遮罩框选窗口：暗色蒙层 + 选区高亮，Esc 取消 / 回车或双击确认。

    多屏不同 DPR 时按物理坐标逐屏绘制与裁剪，保证选区与最终截图一致。
    """

    def __init__(self, caps: List[Tuple[QRect, QRect, float, QPixmap]], virtual: QRect):
        super().__init__()
        self._caps = caps  # [(logical, physical, dpr, grab), ...]
        self._origin = None  # QPoint，拖拽起点（逻辑坐标）
        self._selection: Optional[QRect] = None  # 逻辑坐标
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
        # 逐屏绘制底图（逻辑坐标），Qt 按各屏 DPR 渲染到物理像素
        for logical, _physical, _dpr, grab in self._caps:
            painter.drawPixmap(logical, grab)
        # 全屏暗色蒙层
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        if self._selection is not None \
                and self._selection.width() > 0 and self._selection.height() > 0:
            # 选中区域显示原图（明亮）
            for logical, _physical, dpr, grab in self._caps:
                inter = logical.intersected(self._selection)
                if inter.isEmpty():
                    continue
                off = inter.topLeft() - logical.topLeft()
                src = QRect(round(off.x() * dpr), round(off.y() * dpr),
                            round(inter.width() * dpr), round(inter.height() * dpr))
                painter.drawPixmap(inter, grab, src)
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
            self._result_image = self._crop(self._selection)
        self.accept()

    def _crop(self, selection: QRect) -> Optional[QImage]:
        """把逻辑选区逐屏映射到物理坐标并裁剪，拼成一张最终图（物理像素）。"""
        parts = []  # (物理全局矩形, 裁剪出的 QPixmap)
        for logical, physical, dpr, grab in self._caps:
            inter = logical.intersected(selection)
            if inter.isEmpty():
                continue
            off = inter.topLeft() - logical.topLeft()
            px = physical.x() + round(off.x() * dpr)
            py = physical.y() + round(off.y() * dpr)
            pw = round(inter.width() * dpr)
            ph = round(inter.height() * dpr)
            # 在 grab（物理像素）里的裁剪矩形
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

    def result_image(self) -> Optional[QImage]:
        return self._result_image


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

    try:
        caps = _screen_captures()
        if not caps:
            _log("未抓到任何屏幕，取消")
            return None
        virtual = _virtual_logical_bbox(caps)
        overlay = ScreenshotOverlay(caps, virtual)
        overlay.exec()
        result = overlay.result_image()
        has = result is not None and not result.isNull()
        _log(f"框选完成: {'有图' if has else '取消'}"
             + (f"，尺寸={result.width()}x{result.height()}" if has else ""))
        _flush_log()
        return result
    finally:
        for w in hidden:
            try:
                w.show()
                w.raise_()
                w.activateWindow()
            except RuntimeError:
                pass  # 窗口已被销毁，忽略
