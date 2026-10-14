"""诊断多屏截图：打印每块屏的几何/DPR，以及 grabWindow(0) 结果的实际尺寸与内容边界。

用法：在项目根目录运行  python diagnose_screens.py
"""
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication


def main():
    app = QApplication(sys.argv)
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()

    print("=== 每块屏幕 ===")
    for i, s in enumerate(screens):
        g = s.geometry()
        print(f"[{i}] name={s.name()!r} primary={s is primary} "
              f"geometry=({g.x()},{g.y()}) {g.width()}x{g.height()} "
              f"dpr={s.devicePixelRatio()} "
              f"logicalDpi={s.logicalDotsPerInch()} physicalDpi={s.physicalDotsPerInch()}")

    left = min(s.geometry().left() for s in screens)
    top = min(s.geometry().top() for s in screens)
    right = max(s.geometry().right() for s in screens)
    bottom = max(s.geometry().bottom() for s in screens)
    print(f"=== 虚拟桌面包围盒 = ({left},{top})..({right},{bottom}) "
          f"尺寸={right - left + 1}x{bottom - top + 1}")
    print(f"=== 主屏 dpr = {primary.devicePixelRatio()}")

    # 修正后（位置除回 dpr）的布局
    dpr = primary.devicePixelRatio()
    print("=== 修正后布局（位置 ÷ dpr）===")
    for i, s in enumerate(screens):
        g = s.geometry()
        print(f"[{i}] 修正位置=({round(g.x() / dpr)},{round(g.y() / dpr)}) "
              f"尺寸={g.width()}x{g.height()}")

    print("=== grabWindow(0) 结果 ===")
    for i, s in enumerate(screens):
        pix = s.grabWindow(0)
        if pix.isNull():
            print(f"[{i}] NULL")
            continue
        img = pix.toImage()
        w, h = pix.width(), pix.height()
        print(f"[{i}] grab 尺寸={w}x{h} dpr={pix.devicePixelRatio()} "
              f"(期望 device = {int(s.geometry().width() * s.devicePixelRatio())}x"
              f"{int(s.geometry().height() * s.devicePixelRatio())})")
        # 内容边界：非纯黑像素的包围盒（采样）
        minx, miny, maxx, maxy = w, h, -1, -1
        stepx = max(1, w // 80)
        stepy = max(1, h // 80)
        for y in range(0, h, stepy):
            for x in range(0, w, stepx):
                c = img.pixelColor(x, y)
                if c.red() > 8 or c.green() > 8 or c.blue() > 8:
                    if x < minx:
                        minx = x
                    if x > maxx:
                        maxx = x
                    if y < miny:
                        miny = y
                    if y > maxy:
                        maxy = y
        print(f"[{i}] 非黑内容包围盒（采样）= ({minx},{miny})..({maxx},{maxy}) "
              f"{'(整屏无黑边)' if minx == 0 and miny == 0 and maxx == w - 1 and maxy == h - 1 else '(有黑边!)'}")


if __name__ == "__main__":
    main()
