"""截图模块：获取框选区域的 QImage。

Windows 下主用系统自带截图工具（Win+Shift+S）：微软原生适配多屏、不同 DPI 缩放，
可彻底规避 Qt 自绘遮罩在混合缩放下的黑边/错位问题。框选确认后结果自动写入剪贴板，
这里监听剪贴板拿图回调。

非 Windows 平台回退到内置的自绘框选（全屏遮罩 + 鼠标框选 + QScreen.grabWindow
裁剪，PyQt6 原生零额外依赖）。关键点：不能用 QRubberBand 的 grab 结果（会得到
透明空白图），必须用框选坐标到已抓取的「全屏底图」上裁剪；多屏高 DPI 时按物理
像素（geometry().topLeft() 为位置、geometry().size() × devicePixelRatio 为尺寸）
逐屏拼接、逐屏裁剪。

参考来源：
- Qt 论坛 "Save mouse-selected area"（规范的全屏遮罩 + 框选 + grabWindow 用法）
- tik_manager4 的 ui/widgets/screenshot.py（最小 ScreenShot 结构）
"""
import sys
import time
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton


def _screen_captures() -> List[Tuple[QRect, QRect, float, QPixmap]]:
    """抓取每块屏，返回 (逻辑矩形, 物理矩形, DPR, 抓图)。

    逻辑矩形 = s.geometry()（供叠加层定位 / 鼠标坐标，含 Qt 的逻辑缝隙）；
    物理矩形 = geometry().topLeft() 位置 + geometry().size() × DPR 尺寸；
    抓图 = 该屏原生分辨率（物理像素）。
    """
    caps = []
    for s in QGuiApplication.screens():
        geo = s.geometry()
        dpr = s.devicePixelRatio()
        logical = QRect(geo)
        physical = QRect(geo.x(), geo.y(),
                         round(geo.width() * dpr), round(geo.height() * dpr))
        grab = s.grabWindow(0)
        caps.append((logical, physical, dpr, grab))
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
            return None
        virtual = _virtual_logical_bbox(caps)
        overlay = ScreenshotOverlay(caps, virtual)
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


def _trigger_win_shift_s():
    """模拟按下 Win+Shift+S，调起 Windows 系统截图工具（截图并自动写入剪贴板）。

    Windows 自带的截图工具已正确适配多屏、不同 DPI 缩放，可彻底规避自绘遮罩在
    混合缩放下的黑边/错位问题。
    """
    import ctypes
    user32 = ctypes.windll.user32
    vk_lwin = 0x5B
    vk_shift = 0x10
    vk_s = 0x53
    keyup = 0x0002

    user32.keybd_event(vk_lwin, 0, 0, 0)
    user32.keybd_event(vk_shift, 0, 0, 0)
    user32.keybd_event(vk_s, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk_s, 0, keyup, 0)
    user32.keybd_event(vk_shift, 0, keyup, 0)
    user32.keybd_event(vk_lwin, 0, keyup, 0)


def trigger_system_screenshot(callback, timeout_ms: int = 60000):
    """调起系统截图，完成后把结果 QImage 回调给 callback（在主线程执行）。

    Windows：模拟 Win+Shift+S 打开系统截图工具，用户框选确认后结果自动写入剪贴板，
    这里监听剪贴板 dataChanged 拿图回调；取消或超时回调 None。
    非 Windows：回退到内置的自绘框选截图（capture_region）。

    callback 签名：callback(image: Optional[QImage])
    """
    if sys.platform != "win32":
        callback(capture_region())
        return

    clipboard = QApplication.clipboard()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.setInterval(timeout_ms)
    settled = False

    def _cleanup():
        try:
            clipboard.dataChanged.disconnect(_on_data_changed)
        except (TypeError, RuntimeError):
            pass
        timer.stop()

    def _on_data_changed():
        nonlocal settled
        if settled:
            return
        if clipboard.mimeData().hasImage():
            image = clipboard.image()
            if image is not None and not image.isNull():
                settled = True
                _cleanup()
                callback(image)

    def _on_timeout():
        nonlocal settled
        if settled:
            return
        settled = True
        _cleanup()
        callback(None)

    timer.timeout.connect(_on_timeout)
    clipboard.dataChanged.connect(_on_data_changed)
    timer.start()
    _trigger_win_shift_s()
