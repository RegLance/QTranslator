"""企业版慢机诊断脚本（standalone）：
A. 冷读 vs 热读 dist 目录全部文件 —— 若热读也极慢，说明每次文件读取
   都被实时拦截扫描（杀软/EDR），而不是首次扫描缓存问题
B. 加载 PyQt6 计时 —— 与正常机器对比（正常约 1 秒内）
C. 列出 dist 文件数量/大小 —— 扫描对象规模
用法: 把本文件复制到装有 dist/QTranslator 的机器上，
      用任意 Python 运行: python diag_slow.py
"""
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DIST = None
for cand in (Path(sys.argv[1]) if len(sys.argv) > 1 else None,
             Path(__file__).parent / "dist" / "QTranslator",
             Path(__file__).parent / "dist"):
    if cand and cand.exists() and any(cand.iterdir()):
        DIST = cand
        break
if DIST is None:
    print("未找到 dist/QTranslator 目录，请将其作为第一个参数传入")
    sys.exit(1)

files = [p for p in DIST.rglob("*") if p.is_file()]
total = sum(p.stat().st_size for p in files)
print(f"目录: {DIST}")
print(f"文件数: {len(files)}  总大小: {total / 1048576:.1f} MB")

t0 = time.time()
for p in files:
    p.read_bytes()
cold = time.time() - t0
print(f"[A1] 冷读全部文件: {cold:.2f}s  ({total / 1048576 / max(cold, 1e-6):.1f} MB/s)")

t0 = time.time()
for p in files:
    p.read_bytes()
warm = time.time() - t0
print(f"[A2] 热读全部文件: {warm:.2f}s  ({total / 1048576 / max(warm, 1e-6):.1f} MB/s)")
if warm > 5:
    print("     → 热读仍然很慢：每次文件读取都被实时拦截扫描（杀软/EDR 内核过滤驱动）")
elif cold > 3 * max(warm, 0.1):
    print("     → 冷读远慢于热读：首次扫描有缓存，二次启动会明显变快")
else:
    print("     → 文件读取速度正常，慢点不在磁盘扫描")

try:
    t0 = time.time()
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    dt = time.time() - t0
    print(f"[B]  PyQt6 导入耗时: {dt:.2f}s （正常机器通常 < 1.5s）")
except ImportError:
    print("[B]  本机未安装 PyQt6，跳过")
