"""
PyInstaller 打包脚本 - QTranslator
包含 native 目录以支持 selection-hook 文本选择捕获
包含嵌入式 Node.js 运行时，无需用户安装 Node.js
"""
import os
import sys
import shutil
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()
SRC_DIR = PROJECT_ROOT / "src"
NATIVE_DIR = PROJECT_ROOT / "native"
NODE_RUNTIME_DIR = NATIVE_DIR / "node" / "win-x64"

# 输出版本信息
VERSION = "2.0.0"
APP_NAME = "QTranslator"

# 打包时不包含的 OCR 资源（已移除日文/俄文识别支持）
_OCR_BUNDLE_EXCLUDE_NAMES = frozenset({
    "japan_PP-OCRv3_rec_infer.onnx",
    "cyrillic_PP-OCRv3_rec_infer.onnx",
    "japan_dict.txt",
    "cyrillic_dict.txt",
})


def collect_assets_datas(assets_dir: Path | None = None) -> list[tuple[str, str]]:
    """生成 PyInstaller datas 条目，排除日文/俄文 OCR 模型与字典。"""
    root = assets_dir or (PROJECT_ROOT / "assets")
    if not root.is_dir():
        return []
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in _OCR_BUNDLE_EXCLUDE_NAMES:
            continue
        rel = path.relative_to(root)
        dest = "assets" if rel.parent == Path(".") else f"assets/{rel.parent.as_posix()}"
        entries.append((str(path).replace("\\", "/"), dest))
    return entries


def get_spec_content() -> str:
    """生成 .spec 文件内容"""

    # 收集所有 Python 源文件
    hidden_imports = [
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "pynput.keyboard._win32",
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
        # TTS 相关依赖
        "pyttsx3",
        "edge_tts",
        "aiohttp",
        "PyQt6.QtMultimedia",
        "win32com.client",
        "pythoncom",
        "pywin32",
    ]

    # 添加所有 src 目录下的模块
    for py_file in SRC_DIR.rglob("*.py"):
        module_name = py_file.relative_to(PROJECT_ROOT).with_suffix("")
        hidden_imports.append(str(module_name).replace(os.sep, "."))

    hidden_imports_str = "\n    ".join(f'"{x}",' for x in hidden_imports)

    return f'''# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for QTranslator

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

block_cipher = None

project_root = Path(SPECPATH)

try:
    import rapidocr_onnxruntime as _rapidocr_pkg

    _rapidocr_root = Path(_rapidocr_pkg.__file__).resolve().parent
    _ocr_datas = [(str(_rapidocr_root / "config.yaml"), "rapidocr_onnxruntime")]
except Exception:
    _ocr_datas = []

_ocr_hidden = collect_submodules("rapidocr_onnxruntime")

_binaries = []
for _hook in ("onnxruntime", "cv2"):
    try:
        _binaries += collect_dynamic_libs(_hook)
    except Exception:
        pass

a = Analysis(
    ["run.py"],
    pathex=[str(project_root)],
    binaries=_binaries,
    datas=[
        (str(project_root / "native"), "native"),
        (str(project_root / "assets"), "assets"),
    ]
    + _ocr_datas,
    hiddenimports=[
        {hidden_imports_str}
        "onnxruntime",
        "cv2",
        "numpy",
        "PIL",
        "rapidocr_onnxruntime",
        "src.ui.screenshot_ocr_overlay",
        "src.utils.rapidocr_engine",
        "src.utils.vocabulary",
        "src.ui.vocabulary_window",
    ]
    + _ocr_hidden,
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
    spec_path = PROJECT_ROOT / "qtranslator.spec"

    # 绝对路径 - 使用正斜杠
    icon_path = str(PROJECT_ROOT / "assets" / "icon.ico").replace("\\", "/")
    native_path = str(PROJECT_ROOT / "native").replace("\\", "/")
    assets_datas_lines = "\n".join(
        f'        ("{src}", "{dest}"),'
        for src, dest in collect_assets_datas()
    )
    if not assets_datas_lines:
        assets_datas_lines = "        # (无 assets 文件)"

    content = rf'''# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for QTranslator

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

block_cipher = None

# 项目根目录
project_root = Path(SPECPATH)

try:
    import rapidocr_onnxruntime as _rapidocr_pkg

    _rapidocr_root = Path(_rapidocr_pkg.__file__).resolve().parent
    _ocr_datas = [(str(_rapidocr_root / "config.yaml"), "rapidocr_onnxruntime")]
except Exception:
    _ocr_datas = []

_ocr_hidden = collect_submodules("rapidocr_onnxruntime")

_assets_datas = [
{assets_datas_lines}
]

_binaries = []
for _hook in ("onnxruntime", "cv2"):
    try:
        _binaries += collect_dynamic_libs(_hook)
    except Exception:
        pass

a = Analysis(
    ["run.py"],
    pathex=[str(project_root)],
    binaries=_binaries,
    datas=[
        ("{native_path}", "native"),
    ]
    + _assets_datas
    + _ocr_datas,
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "pynput.keyboard._win32",
        "pyperclip",
        "openai",
        "comtypes",
        "comtypes.client",
        "yaml",
        "yaml.safe_load",
        "langdetect",
        "langdetect.lang_detect_exception",
        "keyboard",
        "pyttsx3",
        "edge_tts",
        "aiohttp",
        "PyQt6.QtMultimedia",
        "win32com.client",
        "pythoncom",
        "pywin32",
        "onnxruntime",
        "cv2",
        "numpy",
        "PIL",
        "rapidocr_onnxruntime",
        "src.config",
        "src.main",
        "src.__init__",
        "src.core.selection_detector",
        "src.core.text_capture",
        "src.core.translator",
        "src.core.writing",
        "src.core.api_config",
        "src.core.__init__",
        "src.ui.history_window",
        "src.ui.popup_window",
        "src.ui.translate_button",
        "src.ui.translator_window",
        "src.ui.tray_icon",
        "src.ui.help_window",
        "src.ui.screenshot_ocr_overlay",
        "src.ui.__init__",
        "src.utils.history",
        "src.utils.logger",
        "src.utils.language_detector",
        "src.utils.hotkey_manager",
        "src.utils.theme",
        "src.utils.tts",
        "src.utils.tts_media",
        "src.utils.tts_speak_indicator",
        "src.utils.rapidocr_engine",
        "src.utils.vocabulary",
        "src.ui.vocabulary_window",
        "src.utils.__init__",
    ]
    + _ocr_hidden,
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
        str(PROJECT_ROOT / "qtranslator.spec"),
        "--clean",
        "--noconfirm",
    ])

    print("=" * 50)
    print("打包完成!")
    print(f"输出目录: {dist_dir}")


def main():
    """主函数"""
    print(f"QTranslator 打包脚本 v{VERSION}")
    print(f"项目目录: {PROJECT_ROOT}")
    print()

    # 检查 native 目录是否存在
    if not NATIVE_DIR.exists():
        print(f"错误: native 目录不存在: {NATIVE_DIR}")
        return 1

    print(f"Native 目录: {NATIVE_DIR}")

    # 检查嵌入式 Node.js 运行时
    node_exe = NODE_RUNTIME_DIR / "node.exe"
    if node_exe.exists():
        print(f"嵌入式 Node.js: {node_exe}")
        import subprocess
        try:
            result = subprocess.run([str(node_exe), "--version"], capture_output=True, text=True)
            print(f"Node.js 版本: {result.stdout.strip()}")
        except Exception as e:
            print(f"警告: 无法验证 node.exe: {e}")
    else:
        print(f"警告: 嵌入式 Node.js 不存在: {node_exe}")
        print("请先运行: python scripts/prepare_node_runtime.py")
        print("或手动下载 node.exe 放到 native/node/win-x64/ 目录")
        print()
        # 询问是否继续
        try:
            response = input("是否继续打包？（打包后应用将需要用户安装 Node.js）[y/N]: ").strip().lower()
            if response != 'y':
                print("取消打包")
                return 1
        except EOFError:
            print("自动继续（非交互模式）")

    print()

    # 创建 spec 文件
    create_spec_file()
    print()

    # 执行打包
    build_exe()

    return 0


if __name__ == "__main__":
    sys.exit(main())