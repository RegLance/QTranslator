# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for QTranslator (onedir 模式)

import sys
from pathlib import Path

try:
    from PyInstaller.utils.hooks import collect_all
except ImportError:
    collect_all = None

block_cipher = None

# 项目根目录
project_root = Path(SPECPATH)

# 官方 MCP Python SDK（modelcontextprotocol/python-sdk）：
# 包内存在动态导入，整包收集确保打包后可用
_mcp_datas = []
_mcp_binaries = []
_mcp_hiddenimports = []
if collect_all is not None:
    try:
        _mcp_datas, _mcp_binaries, _mcp_hiddenimports = collect_all("mcp")
    except Exception:
        pass

a = Analysis(
    ["src/main.py"],
    pathex=[str(project_root)],
    binaries=_mcp_binaries,
    datas=[
        # 添加 native 目录 - 包含 selection-hook Node.js 服务和嵌入式 Node.js 运行时
        ("E:/qoder/QTranslator/native", "native"),
        # 添加 assets 目录 - 包含应用图标
        ("E:/qoder/QTranslator/assets", "assets"),
    ] + _mcp_datas,
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
        # 依赖包
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
        # MCP 客户端（官方 mcp SDK）及其异步运行时
        "mcp",
        "mcp.client",
        "mcp.client.session",
        "mcp.client.stdio",
        "anyio",
        "anyio._backends",
        "anyio._backends._asyncio",
        # 核心模块
        "src.config",
        "src.main",
        "src.__init__",
        "src.core.selection_detector",
        "src.core.text_capture",
        "src.core.translator",
        "src.core.phonetic",
        "src.core.writing",
        "src.core.api_config",
        "src.core.chat_store",      # AI 对话会话本地存储
        "src.core.skills",          # Skills（SKILL.md）加载器
        "src.core.custom_actions",  # 自定义工具栏功能扩展
        "src.core.mcp_client",      # MCP 客户端管理器
        "src.core.__init__",
        # UI 模块
        "src.ui.history_window",
        "src.ui.popup_window",
        "src.ui.translate_button",
        "src.ui.selection_toolbar",  # 划词悬浮工具栏
        "src.ui.chat_window",        # AI 对话独立窗口
        "src.ui.translator_window",
        "src.ui.tray_icon",
        "src.ui.help_window",
        "src.ui.__init__",
        # 工具模块
        "src.utils.history",
        "src.utils.logger",
        "src.utils.language_detector",
        "src.utils.hotkey_manager",
        "src.utils.theme",
        "src.utils.tts",
        "src.utils.tts_media",
        "src.utils.tts_speak_indicator",
        "src.utils.__init__",
    ] + _mcp_hiddenimports,
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
    [],
    exclude_binaries=True,  # onedir：二进制文件放入 COLLECT 目录
    name="QTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 关闭 UPX：压缩 DLL 加载需解压且易被杀软深扫，拖慢启动
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="E:/qoder/QTranslator/assets/icon.ico",  # 应用图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,  # 同上
    upx_exclude=[],
    name="QTranslator",
)
