"""文本捕获模块 - 使用 selection-hook 进行跨应用文本选择捕获
支持嵌入式 Node.js 运行时，无需用户安装 Node.js
"""
import sys
import os
import json
import time
import subprocess
import threading
from typing import Optional, Tuple
from dataclasses import dataclass
from pathlib import Path


def _is_frozen_env() -> bool:
    """检测是否为 PyInstaller 打包环境"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def _get_base_path() -> Path:
    """获取基础路径

    打包环境: sys._MEIPASS (临时解压目录)
    开发环境: 项目根目录
    """
    if _is_frozen_env():
        return Path(sys._MEIPASS)
    else:
        # src/core -> src -> project_root
        return Path(__file__).parent.parent.parent


def _get_embedded_node_path() -> Optional[str]:
    """获取嵌入的 node.exe 路径"""
    base = _get_base_path()
    node_exe = base / "native" / "node" / "win-x64" / "node.exe"
    if node_exe.exists():
        return str(node_exe)
    return None


@dataclass
class SelectionInfo:
    """选择信息"""
    text: str
    bounds: Optional[Tuple[int, int, int, int]] = None  # (x, y, width, height)
    method: str = "selection-hook"  # 捕获方法
    error: Optional[str] = None


class TextCapture:
    """文本捕获类 - 使用 selection-hook Node.js 服务"""

    def __init__(self):
        """初始化文本捕获"""
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._last_selection: Optional[dict] = None
        self._last_capture_time: float = 0
        self._lock = threading.Lock()
        self._running = False
        self._ready = False
        self._node_path: Optional[str] = None

        # 查找 Node.js 路径
        self._find_node()

        # 启动服务
        self._start_service()

    def _find_node(self):
        """查找 Windows Node.js 可执行文件路径"""
        # 1. 优先检测嵌入式 Node.js
        embedded_node = _get_embedded_node_path()
        if embedded_node:
            self._node_path = embedded_node
            print(f"[TextCapture] 使用嵌入式 Node.js: {embedded_node}", file=sys.stderr)
            return

        # 2. 检查开发环境的 native/node/win-x64/node.exe
        dev_node = Path(__file__).parent.parent.parent / "native" / "node" / "win-x64" / "node.exe"
        if dev_node.exists():
            self._node_path = str(dev_node)
            print(f"[TextCapture] 使用开发环境 Node.js: {dev_node}", file=sys.stderr)
            return

        # 3. 检查 PATH 环境变量
        path_env = os.environ.get('PATH', '').split(os.pathsep)
        for p in path_env:
            node_exe = os.path.join(p, 'node.exe')
            if os.path.isfile(node_exe):
                self._node_path = node_exe
                print(f"[TextCapture] 使用系统 Node.js: {node_exe}", file=sys.stderr)
                return

        # 4. 尝试 Windows 常见安装路径
        common_paths = [
            r"C:\Program Files\nodejs\node.exe",
            r"C:\Program Files (x86)\nodejs\node.exe",
        ]
        for p in common_paths:
            if os.path.isfile(p):
                self._node_path = p
                print(f"[TextCapture] 使用系统 Node.js: {p}", file=sys.stderr)
                return

        # 5. 回退到系统 "node" 命令
        self._node_path = "node"
        print("[TextCapture] 使用系统 PATH 中的 node 命令", file=sys.stderr)

    def _get_service_path(self) -> str:
        """获取 selection-service.js 的路径

        支持 PyInstaller 打包环境
        """
        base = _get_base_path()
        service_path = base / "native" / "selection-service.js"
        return str(service_path)

    def _start_service(self):
        """启动 Node.js 选择监控服务"""
        if self._process is not None:
            return

        service_path = self._get_service_path()
        if not os.path.exists(service_path):
            print(f"错误: selection-service.js 不存在: {service_path}", file=sys.stderr)
            return

        # 获取 native 目录路径
        native_dir = Path(service_path).parent

        # 设置环境变量，确保原生模块可加载
        env = os.environ.copy()
        env['NODE_PATH'] = str(native_dir / "node_modules")

        try:
            # 启动 Node.js 子进程
            self._process = subprocess.Popen(
                [self._node_path, service_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                cwd=str(native_dir),  # 设置工作目录
                env=env,  # 设置环境变量
                creationflags=subprocess.CREATE_NO_WINDOW,
                text=True,
                encoding='utf-8',
                errors='replace'
            )

            self._running = True

            # 启动读取线程
            self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self._reader_thread.start()

            # 就绪信号由读取线程异步设置，避免阻塞 UI 主线程。
            print("[TextCapture] selection-hook 服务启动中", file=sys.stderr)

        except Exception as e:
            print(f"[TextCapture] 启动服务失败: {e}", file=sys.stderr)
            self._process = None
            self._running = False

    def _read_output(self):
        """读取 Node.js 进程的输出（在后台线程运行）"""
        if not self._process or not self._process.stdout:
            return

        try:
            while self._running:
                line = self._process.stdout.readline()
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)

                    # 检查就绪信号
                    if data.get('ready'):
                        self._ready = True
                        continue

                    # 检查错误
                    if data.get('error'):
                        print(f"[TextCapture] 服务错误: {data['error']}", file=sys.stderr)
                        continue

                    # 存储选择数据
                    with self._lock:
                        self._last_selection = data
                        self._last_capture_time = time.time()

                except json.JSONDecodeError:
                    # 忽略非 JSON 输出
                    pass

        except Exception as e:
            if self._running:
                print(f"[TextCapture] 读取输出错误: {e}", file=sys.stderr)

    def capture(self) -> SelectionInfo:
        """捕获当前选中的文本"""
        with self._lock:
            if self._last_selection:
                data = self._last_selection
                text = data.get('text', '')
                x = data.get('x', 0)
                y = data.get('y', 0)

                return SelectionInfo(
                    text=text,
                    bounds=(x, y, 0, 0) if x or y else None,
                    method="selection-hook"
                )

        return SelectionInfo(text="", method="selection-hook")

    def capture_direct(self) -> str:
        """直接捕获文本（简化版本，用于主流程）"""
        with self._lock:
            if self._last_selection:
                return self._last_selection.get('text', '')
        return ""

    def get_last_program(self) -> str:
        """获取最后一次选择的程序名"""
        with self._lock:
            if self._last_selection:
                return self._last_selection.get('program', '')
        return ""

    def clear_selection(self):
        """清除缓存的选中内容（在翻译完成后调用）"""
        with self._lock:
            self._last_selection = None

    def has_new_selection(self, since_time: float) -> bool:
        """检查是否有新的选择（自指定时间以来）"""
        with self._lock:
            return self._last_capture_time > since_time

    def get_last_capture_time(self) -> float:
        """获取最后一次捕获的时间"""
        with self._lock:
            return self._last_capture_time

    def is_ready(self) -> bool:
        """检查服务是否就绪"""
        return self._ready

    def cleanup(self):
        """清理资源"""
        self._running = False

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

        self._ready = False
        print("[TextCapture] 服务已停止", file=sys.stderr)

    def __del__(self):
        """析构函数"""
        self.cleanup()


# 全局文本捕获实例
_capture_instance: Optional[TextCapture] = None


def get_text_capture() -> TextCapture:
    """获取全局文本捕获实例"""
    global _capture_instance
    if _capture_instance is None:
        _capture_instance = TextCapture()
    return _capture_instance


def capture_selection() -> SelectionInfo:
    """快捷函数：捕获当前选择"""
    return get_text_capture().capture()


def capture_text_direct() -> str:
    """快捷函数：直接捕获文本"""
    return get_text_capture().capture_direct()


def clear_text_capture():
    """快捷函数：清除缓存"""
    get_text_capture().clear_selection()


def get_last_program_name() -> str:
    """快捷函数：获取最后一次选择的程序名"""
    return get_text_capture().get_last_program()


# 常见浏览器进程名（Windows）
BROWSER_PROCESS_NAMES = {
    # Chrome 系列
    'chrome.exe',
    'chrome',
    # Firefox
    'firefox.exe',
    'firefox',
    # Edge
    'msedge.exe',
    'msedge',
    'microsoftedge.exe',
    'microsoftedge',
    # Brave
    'brave.exe',
    'brave',
    # Opera
    'opera.exe',
    'opera',
    # Safari (Windows)
    'safari.exe',
    'safari',
    # Vivaldi
    'vivaldi.exe',
    'vivaldi',
    # QQ浏览器
    'qqbrowser.exe',
    'qqbrowser',
    # 360浏览器
    '360se.exe',
    '360se',
    # 搜狗浏览器
    'sogouexplorer.exe',
    'sogouexplorer',
    # UC浏览器
    'ucbrowser.exe',
    'ucbrowser',
}


def is_browser_program(program_name: str) -> bool:
    """判断给定的程序名是否是浏览器

    Args:
        program_name: 程序名（如 'chrome.exe', 'notepad.exe'）

    Returns:
        True 如果是浏览器，False 否则
    """
    if not program_name:
        return False

    # 转换为小写进行匹配
    program_lower = program_name.lower()

    # 直接匹配
    if program_lower in BROWSER_PROCESS_NAMES:
        return True

    # 部分匹配（处理可能的路径或其他变体）
    for browser in BROWSER_PROCESS_NAMES:
        if browser in program_lower or program_lower in browser:
            return True

    return False