"""启动慢诊断（二）：定位是哪个模块/依赖导入慢

背景：两台机器直接跑 `python main.py` 一样慢（慢机 20s+），
说明瓶颈在 Python 层而非打包层。本脚本分层计时：
  1. 解释器裸启动
  2. 纯标准库导入
  3. 各重依赖单独导入（PyQt6 / comtypes / pywin32 / TTS / 网络库…）
  4. -X importtime 全量导入剖析，输出最慢的 30 个模块

用法（用运行 main.py 的同一个 python，比如项目 venv 的 python）：
    python diag_importtime.py
在慢、快两台机器各跑一次，把输出（含生成的 importtime_report.txt）发回对比。
"""
import subprocess
import sys
import time

PY = sys.executable

# 重依赖清单：项目实际用到的所有"重"模块
HEAVY_MODS = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtMultimedia",
    "comtypes.client",
    "win32com.client",
    "pythoncom",
    "pyttsx3",
    "edge_tts",
    "aiohttp",
    "openai",
    "yaml",
    "langdetect",
    "keyboard",
    "pynput",
    "pyperclip",
    "mcp",
    "anyio",
]


def run_timed(label, args, timeout=300):
    t0 = time.time()
    try:
        r = subprocess.run([PY] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        dt = time.time() - t0
        line = f"{label:<40s} {dt:8.2f}s  rc={r.returncode}"
        print(line, flush=True)
        if r.returncode != 0:
            tail = (r.stderr or "").strip().splitlines()
            if tail:
                print(f"    stderr: {tail[-1][:200]}", flush=True)
        return dt
    except subprocess.TimeoutExpired:
        print(f"{label:<40s}  TIMEOUT(>{timeout}s)", flush=True)
        return -1


def parse_importtime(text):
    """解析 -X importtime 输出，按 cumulative 微秒排序"""
    rows = []
    for line in text.splitlines():
        if not line.startswith("import time:"):
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        try:
            self_us = int(parts[0].split(":", 1)[1].strip())
            cum_us = int(parts[1].strip())
        except ValueError:
            continue
        name = parts[2].strip()
        rows.append((cum_us, self_us, name))
    rows.sort(reverse=True)
    return rows


def main():
    print("=" * 60, flush=True)
    print(f"python: {PY}", flush=True)
    print(f"version: {sys.version.split()[0]}", flush=True)
    print("=" * 60, flush=True)

    t_all0 = time.time()

    print("\n--- 第一阶段：分层计时（每项都是独立子进程）---", flush=True)
    run_timed("裸解释器 python -V", ["-V"])
    run_timed("纯标准库 import json,os", ["-c", "import json, os"])

    print("\n--- 第二阶段：各重依赖单独导入 ---", flush=True)
    for m in HEAVY_MODS:
        run_timed(f"import {m}", ["-c", f"import {m}"])

    print("\n--- 第三阶段：-X importtime 全量剖析 ---", flush=True)
    # 以 PyQt6.QtWidgets 为目标做一次完整导入链剖析
    r = subprocess.run([PY, "-X", "importtime", "-c",
                        "import PyQt6.QtWidgets"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    rows = parse_importtime(r.stderr or "")
    report_lines = [f"# importtime top30 (PyQt6.QtWidgets), python={PY}",
                    f"# total={time.time() - t_all0:.2f}s",
                    f"{'cumulative(ms)':>16s} {'self(ms)':>10s}  module"]
    for cum_us, self_us, name in rows[:30]:
        report_lines.append(f"{cum_us/1000:16.1f} {self_us/1000:10.1f}  {name}")
    report = "\n".join(report_lines)
    print(report, flush=True)
    try:
        with open("importtime_report.txt", "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print("\n已保存 importtime_report.txt", flush=True)
    except OSError:
        pass

    print(f"\n全部耗时合计: {time.time() - t_all0:.2f}s", flush=True)


if __name__ == "__main__":
    main()
