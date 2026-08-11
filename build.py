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
VERSION = "2.1.0"
APP_NAME = "QTranslator"

def create_spec_file():
    """创建 .spec 文件"""
    spec_path = PROJECT_ROOT / "qtranslator.spec"

    # 绝对路径 - 使用正斜杠
    icon_path = str(PROJECT_ROOT / "assets" / "icon.ico").replace("\\", "/")
    native_path = str(PROJECT_ROOT / "native").replace("\\", "/")
    assets_path = str(PROJECT_ROOT / "assets").replace("\\", "/")
    # 嵌入式 Node.js 运行时路径
    node_runtime_path = str(NODE_RUNTIME_DIR).replace("\\", "/")

    content = rf'''# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for QTranslator (onefile 模式)

import sys
from pathlib import Path

try:
    from PyInstaller.utils.hooks import collect_all
except ImportError:
    collect_all = None

block_cipher = None

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

# 项目根目录
project_root = Path(SPECPATH)

a = Analysis(
    ["src/main.py"],
    pathex=[str(project_root)],
    binaries=_mcp_binaries,
    datas=[
        # 添加 native 目录 - 包含 selection-hook Node.js 服务和嵌入式 Node.js 运行时
        ("{native_path}", "native"),
        # 添加 assets 目录 - 包含应用图标
        ("{assets_path}", "assets"),
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
        # 新增依赖包
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
        "src.core.chat_store",      # AI 对话会话本地存储
        "src.core.skills",          # Skills（SKILL.md）加载器
        "src.core.skill_tools",     # 技能本地执行工具（读文件/跑脚本）
        "src.core.custom_actions",  # 自定义工具栏功能扩展
        "src.core.mcp_client",      # MCP 客户端管理器
        "src.core.__init__",
        # UI 模块
        "src.ui.splash_screen",
        "src.ui.history_window",
        "src.ui.popup_window",
        "src.ui.word_popup",
        "src.ui.translate_button",
        "src.ui.selection_toolbar",  # 划词悬浮工具栏
        "src.ui.chat_window",        # AI 对话独立窗口
        "src.ui.translator_window",
        "src.ui.tray_icon",
        "src.ui.help_window",
        "src.ui.vocabulary_window",
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
        "src.utils.context_probe",
        "src.utils.polish_diff",
        "src.utils.selection_blacklist",
        "src.utils.update_checker",
        "src.utils.vocabulary",
        "src.utils.window_front",
        "src.utils.__init__",
    ] + _mcp_hiddenimports,
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