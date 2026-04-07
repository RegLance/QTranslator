# -*- mode: python ; coding: utf-8 -*-
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
        ("E:/qoder/Translate-Copilot/native", "native"),
        # 添加 assets 目录 - 包含应用图标
        ("E:/qoder/Translate-Copilot/assets", "assets"),
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
        "src.config",
        "src.main",
        "src.__init__",
        "src.core.hover_detector",
        "src.core.selection_detector",
        "src.core.text_capture",
        "src.core.translator",
        "src.core.__init__",
        "src.ui.history_window",
        "src.ui.popup_window",
        "src.ui.translate_button",
        "src.ui.translator_window",
        "src.ui.tray_icon",
        "src.ui.__init__",
        "src.utils.history",
        "src.utils.logger",
        "src.utils.__init__",
    ],
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
    name="Translate Copilot",
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
    icon="E:/qoder/Translate-Copilot/assets/icon.ico",  # 应用图标
)
