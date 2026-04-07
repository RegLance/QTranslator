"""
PyInstaller 打包脚本 - Translate Copilot
包含 native 目录以支持 selection-hook 文本选择捕获
"""
import os
import sys
import shutil
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()
SRC_DIR = PROJECT_ROOT / "src"
NATIVE_DIR = PROJECT_ROOT / "native"

# 输出版本信息
VERSION = "1.0.0"
APP_NAME = "Translate Copilot"

def get_spec_content() -> str:
    """生成 .spec 文件内容"""

    # 收集所有 Python 源文件
    hidden_imports = [
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "pyperclip",
        "openai",
        "comtypes",
        "comtypes.client",
        "yaml",
        "yaml.safe_load",
        # 新增依赖
        "langdetect",
        "langdetect.lang_detect_exception",
        "keyboard",
    ]

    # 添加所有 src 目录下的模块
    for py_file in SRC_DIR.rglob("*.py"):
        module_name = py_file.relative_to(PROJECT_ROOT).with_suffix("")
        hidden_imports.append(str(module_name).replace(os.sep, "."))

    hidden_imports_str = "\n    ".join(f'"{x}",' for x in hidden_imports)

    return f'''# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Translate Copilot

import sys
from pathlib import Path

block_cipher = None

# 项目根目录
project_root = Path(SPECPATH)

a = Analysis(
    ["run.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # 添加 native 目录 - 包含 selection-hook Node.js 服务
        (str(project_root / "native"), "native"),
        # 添加 assets 目录 - 包含应用图标
        (str(project_root / "assets"), "assets"),
    ],
    hiddenimports=[
        {hidden_imports_str}
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="{APP_NAME}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "icon.ico"),  # 应用图标
)
'''

def create_spec_file():
    """创建 .spec 文件"""
    spec_path = PROJECT_ROOT / "translate_copilot.spec"

    # 绝对路径 - 使用正斜杠
    icon_path = str(PROJECT_ROOT / "assets" / "icon.ico").replace("\\", "/")
    native_path = str(PROJECT_ROOT / "native").replace("\\", "/")
    assets_path = str(PROJECT_ROOT / "assets").replace("\\", "/")

    content = rf'''# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Translate Copilot

import sys
from pathlib import Path

block_cipher = None

# 项目根目录
project_root = Path(SPECPATH)

a = Analysis(
    ["run.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # 添加 native 目录 - 包含 selection-hook Node.js 服务
        ("{native_path}", "native"),
        # 添加 assets 目录 - 包含应用图标
        ("{assets_path}", "assets"),
    ],
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "pyperclip",
        "openai",
        "comtypes",
        "comtypes.client",
        "yaml",
        "yaml.safe_load",
        # 新增依赖包
        "langdetect",
        "langdetect.lang_detect_exception",
        "keyboard",
        # 核心模块
        "src.config",
        "src.main",
        "src.__init__",
        "src.core.hover_detector",
        "src.core.selection_detector",
        "src.core.text_capture",
        "src.core.translator",
        "src.core.__init__",
        # UI 模块
        "src.ui.history_window",
        "src.ui.popup_window",
        "src.ui.translate_button",
        "src.ui.translator_window",
        "src.ui.tray_icon",
        "src.ui.help_window",  # 新增
        "src.ui.__init__",
        # 工具模块
        "src.utils.history",
        "src.utils.logger",
        "src.utils.language_detector",  # 新增
        "src.utils.hotkey_manager",  # 新增
        "src.utils.theme",  # 新增
        "src.utils.__init__",
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="{APP_NAME}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="{icon_path}",  # 应用图标
)
'''
    spec_path.write_text(content, encoding="utf-8")

    print(f"已创建 spec 文件: {spec_path}")
    print(f"图标路径: {icon_path}")
    return spec_path


def build_exe():
    """执行打包"""
    import PyInstaller.__main__

    # 清理之前的 build 目录
    build_dir = PROJECT_ROOT / "build"
    dist_dir = PROJECT_ROOT / "dist"

    if build_dir.exists():
        print("清理旧 build 目录...")
        shutil.rmtree(build_dir)

    if dist_dir.exists():
        print("清理旧 dist 目录...")
        shutil.rmtree(dist_dir)

    # 运行 PyInstaller
    print("开始打包...")
    print("=" * 50)

    PyInstaller.__main__.run([
        str(PROJECT_ROOT / "translate_copilot.spec"),
        "--clean",
        "--noconfirm",
    ])

    print("=" * 50)
    print("打包完成!")
    print(f"输出目录: {dist_dir}")


def main():
    """主函数"""
    print(f"Translate Copilot 打包脚本 v{VERSION}")
    print(f"项目目录: {PROJECT_ROOT}")
    print()

    # 检查 native 目录是否存在
    if not NATIVE_DIR.exists():
        print(f"错误: native 目录不存在: {NATIVE_DIR}")
        return 1

    print(f"Native 目录: {NATIVE_DIR}")
    print(f"包含文件: {list(NATIVE_DIR.rglob('*'))[:10]}...")  # 显示前10个文件

    # 检查 Node.js
    import subprocess
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        print(f"Node.js 版本: {result.stdout.strip()}")
    except FileNotFoundError:
        print("警告: 未找到 Node.js，请确保 Node.js 已安装并在 PATH 中")

    print()

    # 创建 spec 文件
    create_spec_file()
    print()

    # 执行打包
    build_exe()

    return 0


if __name__ == "__main__":
    sys.exit(main())