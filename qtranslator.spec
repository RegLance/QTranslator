# -*- mode: python ; coding: utf-8 -*-
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

# 打包排除日文/俄文 OCR 模型与字典（与 build.collect_assets_datas 一致）
_OCR_BUNDLE_EXCLUDE = frozenset({
    "japan_PP-OCRv3_rec_infer.onnx",
    "cyrillic_PP-OCRv3_rec_infer.onnx",
    "japan_dict.txt",
    "cyrillic_dict.txt",
})


def _collect_assets_datas():
    root = project_root / "assets"
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in _OCR_BUNDLE_EXCLUDE:
            continue
        rel = path.relative_to(root)
        dest = "assets" if rel.parent == Path(".") else f"assets/{rel.parent.as_posix()}"
        out.append((str(path), dest))
    return out


_assets_datas = _collect_assets_datas()

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
        "src.ui.vocabulary_window",
        "src.utils.vocabulary",
        "src.utils.__init__",
    ]
    + _ocr_hidden,
    hookspath=[],
    hooksconfig={},
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
    name="QTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "icon.ico"),
)
