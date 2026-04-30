"""文本捕获模块 - 使用 selection-hook 进行跨应用文本选择捕获
支持嵌入式 Node.js 运行时，无需用户安装 Node.js
"""
import sys
import os
import json
import time
import uuid
import ctypes
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
        self._pending_requests = {}
        self._pending_lock = threading.Lock()
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
                stdin=subprocess.PIPE,
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

                    # 当前选区查询响应
                    if data.get('type') == 'current-selection':
                        request_id = data.get('requestId')
                        with self._pending_lock:
                            pending = self._pending_requests.get(request_id)
                            if pending:
                                pending['data'] = data
                                pending['event'].set()
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

    def get_current_selection(self, timeout: float = 0.5) -> SelectionInfo:
        """主动查询当前真实选区。

        与 capture_direct() 不同，这里不是读取上一次缓存的选择事件，
        而是让 selection-hook 在快捷键触发当下查询当前选区。
        """
        if not self._process or not self._process.stdin:
            return SelectionInfo(text="", method="selection-hook")

        request_id = uuid.uuid4().hex
        event = threading.Event()
        pending = {'event': event, 'data': None}

        with self._pending_lock:
            self._pending_requests[request_id] = pending

        try:
            self._process.stdin.write(json.dumps({
                'cmd': 'get-current-selection',
                'id': request_id,
            }) + '\n')
            self._process.stdin.flush()

            if not event.wait(timeout):
                return SelectionInfo(text="", method="selection-hook", error="timeout")

            data = pending.get('data') or {}
            text = data.get('text', '') or ''
            x = data.get('x', 0)
            y = data.get('y', 0)
            return SelectionInfo(
                text=text,
                bounds=(x, y, 0, 0) if x or y else None,
                method=data.get('method', 'selection-hook') or 'selection-hook',
                error=data.get('error')
            )
        except Exception as e:
            return SelectionInfo(text="", method="selection-hook", error=str(e))
        finally:
            with self._pending_lock:
                self._pending_requests.pop(request_id, None)

    def get_selected_text_nextai_style(self) -> SelectionInfo:
        """按 nextai-translator 的思路获取当前真实选区。

        优先使用非剪贴板方法：
        1. Scintilla 直接读取选区（Notepad++、SciTE、部分编辑器）
        2. Windows UI Automation TextPattern（浏览器、VS Code、WPF/UWP 等）

        不在这里使用 Ctrl+C 作为兜底，因为很多编辑器在无选区时会复制当前行，
        会把“光标所在行”误判为选区。
        """
        text = self._get_selected_text_by_scintilla()
        if text:
            return SelectionInfo(text=text, method="scintilla")

        text = self._get_selected_text_by_uia()
        if text:
            return SelectionInfo(text=text, method="uia")

        return SelectionInfo(text="", method="nextai-style")

    def _get_selected_text_by_scintilla(self) -> str:
        """通过 Scintilla 消息读取当前选区。"""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.VirtualAllocEx.restype = ctypes.c_void_p
            kernel32.VirtualAllocEx.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_ulong,
                ctypes.c_ulong,
            ]
            kernel32.VirtualFreeEx.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_ulong,
            ]
            kernel32.ReadProcessMemory.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
            ]

            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return ""

            scintilla_hwnd = self._find_child_window_by_class(hwnd, "Scintilla")
            if not scintilla_hwnd:
                return ""

            SCI_GETSELECTIONSTART = 2143
            SCI_GETSELECTIONEND = 2145
            SCI_GETSELTEXT = 2161

            sel_start = user32.SendMessageW(scintilla_hwnd, SCI_GETSELECTIONSTART, 0, 0)
            sel_end = user32.SendMessageW(scintilla_hwnd, SCI_GETSELECTIONEND, 0, 0)
            if sel_start == sel_end:
                return ""

            sel_len = abs(sel_end - sel_start)
            if sel_len <= 0 or sel_len > 10 * 1024 * 1024:
                return ""

            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(scintilla_hwnd, ctypes.byref(process_id))
            if not process_id.value:
                return ""

            PROCESS_VM_OPERATION = 0x0008
            PROCESS_VM_READ = 0x0010
            PROCESS_VM_WRITE = 0x0020
            MEM_COMMIT = 0x1000
            MEM_RESERVE = 0x2000
            MEM_RELEASE = 0x8000
            PAGE_READWRITE = 0x04

            process_handle = kernel32.OpenProcess(
                PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE,
                False,
                process_id.value,
            )
            if not process_handle:
                return ""

            remote_buffer = None
            try:
                buffer_size = sel_len + 1
                remote_buffer = kernel32.VirtualAllocEx(
                    process_handle,
                    None,
                    buffer_size,
                    MEM_COMMIT | MEM_RESERVE,
                    PAGE_READWRITE,
                )
                if not remote_buffer:
                    return ""

                user32.SendMessageW(
                    scintilla_hwnd,
                    SCI_GETSELTEXT,
                    0,
                    ctypes.c_void_p(remote_buffer),
                )

                local_buffer = ctypes.create_string_buffer(buffer_size)
                bytes_read = ctypes.c_size_t()
                ok = kernel32.ReadProcessMemory(
                    process_handle,
                    remote_buffer,
                    local_buffer,
                    buffer_size,
                    ctypes.byref(bytes_read),
                )
                if not ok:
                    return ""

                raw = local_buffer.raw.split(b'\x00', 1)[0]
                return raw.decode('utf-8', errors='replace')
            finally:
                if remote_buffer:
                    kernel32.VirtualFreeEx(process_handle, remote_buffer, 0, MEM_RELEASE)
                kernel32.CloseHandle(process_handle)
        except Exception:
            return ""

    def _find_child_window_by_class(self, parent_hwnd: int, class_name: str) -> int:
        """递归查找指定类名的子窗口。"""
        user32 = ctypes.windll.user32
        buffer = ctypes.create_unicode_buffer(256)

        direct = user32.FindWindowExW(parent_hwnd, 0, class_name, None)
        if direct:
            return direct

        found = 0

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_child(hwnd, _lparam):
            nonlocal found
            user32.GetClassNameW(hwnd, buffer, 256)
            if buffer.value == class_name:
                found = hwnd
                return False

            nested = self._find_child_window_by_class(hwnd, class_name)
            if nested:
                found = nested
                return False

            return True

        user32.EnumChildWindows(parent_hwnd, enum_child, 0)
        return found

    def _get_selected_text_by_uia(self) -> str:
        """通过 Windows UI Automation TextPattern 读取当前选区。"""
        try:
            import comtypes.client
            try:
                from comtypes.gen import UIAutomationClient
            except ImportError:
                comtypes.client.GetModule('UIAutomationCore.dll')
                from comtypes.gen import UIAutomationClient

            automation = comtypes.client.CreateObject(
                UIAutomationClient.CUIAutomation,
                interface=UIAutomationClient.IUIAutomation,
            )
            focused = automation.GetFocusedElement()
            if not focused:
                return ""

            pattern = focused.GetCurrentPattern(UIAutomationClient.UIA_TextPatternId)
            if not pattern:
                return ""

            text_pattern = pattern.QueryInterface(UIAutomationClient.IUIAutomationTextPattern)
            ranges = text_pattern.GetSelection()
            if not ranges or ranges.Length <= 0:
                return ""

            selected_range = ranges.GetElement(0)
            text = selected_range.GetText(-1)
            return text or ""
        except Exception:
            return ""

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

    def stop_selection_hook(self):
        """终止 selection-hook 子进程（全局鼠标/文本钩子）。可与 start_selection_hook() 配对反复调用。"""
        self._running = False

        with self._pending_lock:
            for pending in self._pending_requests.values():
                pending['event'].set()
            self._pending_requests.clear()

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
        self._reader_thread = None

        self._ready = False
        with self._lock:
            self._last_selection = None
            self._last_capture_time = 0.0

        print("[TextCapture] selection-hook 已停止", file=sys.stderr)

    def start_selection_hook(self):
        """启动 selection-hook 子进程（托盘重新启用划词时调用）。"""
        self._start_service()

    def cleanup(self):
        """应用退出时释放资源"""
        self.stop_selection_hook()
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