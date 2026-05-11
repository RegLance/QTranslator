"""全局热键管理模块 - 用于注册和管理全局快捷键

使用 pynput.keyboard.GlobalHotKeys 实现全局热键监听。
相比 keyboard 库，pynput 提供干净的 stop/start 生命周期，
锁屏恢复时只需重建 listener，无需 hack 内部状态。

支持多个热键注册：
- 翻译窗口热键
- 写作热键
- 选中内容翻译热键（Excel/PPT 等场景）
"""
import sys
import threading
from typing import Optional, Callable, Dict
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QMetaObject

try:
    from ..utils.logger import log_info, log_error, log_debug
except ImportError:
    from src.utils.logger import log_info, log_error, log_debug


# Qt 格式 -> pynput 格式的修饰键/特殊键映射
_KEY_MAP = {
    'ctrl': '<ctrl>',
    'shift': '<shift>',
    'alt': '<alt>',
    'meta': '<cmd>',
    'space': '<space>',
    'tab': '<tab>',
    'enter': '<enter>',
    'return': '<enter>',
    'backspace': '<backspace>',
    'delete': '<delete>',
    'escape': '<esc>',
    'esc': '<esc>',
    'home': '<home>',
    'end': '<end>',
    'insert': '<insert>',
    'pageup': '<page_up>',
    'pagedown': '<page_down>',
    'up': '<up>',
    'down': '<down>',
    'left': '<left>',
    'right': '<right>',
}

# 功能键单独处理: F1~F24
for _i in range(1, 25):
    _KEY_MAP[f'f{_i}'] = f'<f{_i}>'


def _convert_hotkey_format(hotkey: str) -> Optional[str]:
    """将 Qt 格式的热键字符串转换为 pynput 格式

    Qt 格式: "Ctrl+O", "Ctrl+Shift+A", "Alt+F1"
    pynput 格式: "<ctrl>+o", "<ctrl>+<shift>+a", "<alt>+<f1>"

    Returns:
        转换后的 pynput 格式字符串，转换失败返回 None
    """
    try:
        parts = hotkey.split('+')
        converted = []
        for part in parts:
            part_stripped = part.strip()
            part_lower = part_stripped.lower()

            if part_lower in _KEY_MAP:
                converted.append(_KEY_MAP[part_lower])
            elif len(part_stripped) == 1:
                # 单个字符键（字母、数字、符号）
                converted.append(part_stripped.lower())
            else:
                # 尝试作为 pynput 特殊键名
                converted.append(f'<{part_lower}>')

        result = '+'.join(converted)

        # 用 HotKey.parse 验证格式是否合法
        from pynput.keyboard import HotKey
        HotKey.parse(result)

        return result
    except Exception as e:
        log_error(f"热键格式转换失败: '{hotkey}' -> {e}")
        return None


class HotkeyManager(QObject):
    """全局热键管理器（基于 pynput.keyboard.GlobalHotKeys）"""

    # 信号
    hotkey_triggered = pyqtSignal()  # 翻译窗口热键触发信号
    writing_hotkey_triggered = pyqtSignal()  # 写作热键触发信号
    selection_translate_hotkey_triggered = pyqtSignal()  # 选中内容翻译热键（主动取词）

    def __init__(self):
        super().__init__()
        self._hotkeys: Dict[str, str] = {}  # hotkey_name -> hotkey_string (Qt 格式)
        self._listener = None  # pynput GlobalHotKeys 实例
        self._is_listening = False
        self._restart_lock = threading.Lock()

    def register_hotkey(self, hotkey: str, callback: Callable = None, name: str = "translator_window") -> bool:
        """注册全局热键

        Args:
            hotkey: 热键字符串，如 "Ctrl+O"（Qt 格式）
            callback: 热键触发时的回调函数（可选，建议使用信号）
            name: 热键名称，用于标识不同的热键

        Returns:
            bool: 是否成功注册
        """
        # 验证格式是否可转换
        pynput_format = _convert_hotkey_format(hotkey)
        if pynput_format is None:
            log_error(f"无法注册热键 [{name}]: 格式转换失败 '{hotkey}'")
            return False

        self._hotkeys[name] = hotkey
        return self._rebuild_listener()

    def unregister_hotkey(self, name: str = None):
        """注销热键

        Args:
            name: 热键名称，如果为 None 则注销所有热键
        """
        if name is None:
            self._hotkeys.clear()
        elif name in self._hotkeys:
            del self._hotkeys[name]

        self._rebuild_listener()

    def reinstall_all(self):
        """重建热键监听器（用于锁屏恢复等场景）

        pynput 的 GlobalHotKeys 基于 WH_KEYBOARD_LL 钩子，
        Windows 锁屏时钩子可能被系统卸载。
        只需 stop + 新建 + start 即可恢复，无需任何内部状态 hack。
        """
        self._rebuild_listener()

    def _rebuild_listener(self) -> bool:
        """重建 GlobalHotKeys 监听器（核心方法）

        停止旧的 listener，根据当前 _hotkeys 创建新的。
        线程安全，防止并发重建。

        Returns:
            bool: 是否成功构建并启动
        """
        if not self._restart_lock.acquire(blocking=False):
            return False  # 已有重建在进行中

        try:
            # 停止旧的 listener
            if self._listener is not None:
                try:
                    self._listener.stop()
                except Exception:
                    pass
                self._listener = None

            # 如果没有热键需要监听
            if not self._hotkeys:
                self._is_listening = False
                return True

            # 构建 pynput 热键字典
            pynput_hotkeys = {}
            for name, hotkey in self._hotkeys.items():
                pynput_format = _convert_hotkey_format(hotkey)
                if pynput_format is None:
                    continue

                if name == "writing":
                    pynput_hotkeys[pynput_format] = self._on_writing_hotkey_pressed
                elif name == "selection_translate":
                    pynput_hotkeys[pynput_format] = self._on_selection_translate_pressed
                else:
                    pynput_hotkeys[pynput_format] = self._on_hotkey_pressed

            if not pynput_hotkeys:
                self._is_listening = False
                log_error("所有热键格式转换失败，无法注册")
                return False

            # 创建并启动新的 listener
            from pynput.keyboard import GlobalHotKeys
            self._listener = GlobalHotKeys(pynput_hotkeys)
            self._listener.start()
            self._is_listening = True

            hotkey_info = ', '.join(f'{n}: {h}' for n, h in self._hotkeys.items())
            log_info(f"已注册全局热键: {hotkey_info}")
            return True

        except Exception as e:
            log_error(f"重建热键监听器失败: {e}")
            self._is_listening = False
            return False
        finally:
            self._restart_lock.release()

    def _on_hotkey_pressed(self):
        """翻译窗口热键按下（pynput 线程回调 -> 切到 Qt 主线程）"""
        log_debug("翻译窗口热键触发")
        try:
            QMetaObject.invokeMethod(
                self, "_emit_hotkey_triggered",
                Qt.ConnectionType.QueuedConnection
            )
        except Exception:
            pass

    def _on_writing_hotkey_pressed(self):
        """写作热键按下（pynput 线程回调 -> 切到 Qt 主线程）"""
        log_debug("写作热键触发")
        try:
            QMetaObject.invokeMethod(
                self, "_emit_writing_hotkey_triggered",
                Qt.ConnectionType.QueuedConnection
            )
        except Exception:
            pass

    def _on_selection_translate_pressed(self):
        """选中内容翻译热键（pynput 线程 -> Qt 主线程）"""
        log_debug("选中内容翻译热键触发")
        try:
            QMetaObject.invokeMethod(
                self, "_emit_selection_translate_hotkey_triggered",
                Qt.ConnectionType.QueuedConnection
            )
        except Exception:
            pass

    @pyqtSlot()
    def _emit_hotkey_triggered(self):
        """主线程执行：发射翻译窗口热键信号"""
        self.hotkey_triggered.emit()

    @pyqtSlot()
    def _emit_writing_hotkey_triggered(self):
        """主线程执行：发射写作热键信号"""
        self.writing_hotkey_triggered.emit()

    @pyqtSlot()
    def _emit_selection_translate_hotkey_triggered(self):
        self.selection_translate_hotkey_triggered.emit()

    def update_hotkey(self, new_hotkey: str, name: str = "translator_window") -> bool:
        """更新热键

        Args:
            new_hotkey: 新的热键字符串
            name: 热键名称

        Returns:
            bool: 是否成功更新
        """
        return self.register_hotkey(new_hotkey, name=name)

    def get_hotkey(self, name: str = "translator_window") -> Optional[str]:
        """获取指定名称的热键

        Args:
            name: 热键名称

        Returns:
            str: 热键字符串，如果不存在则返回 None
        """
        return self._hotkeys.get(name)

    def stop(self):
        """停止热键监听"""
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        self._hotkeys.clear()
        self._is_listening = False

    @property
    def is_listening(self) -> bool:
        """是否正在监听"""
        return self._is_listening


# 全局热键管理器实例
_hotkey_manager_instance: Optional[HotkeyManager] = None


def get_hotkey_manager() -> HotkeyManager:
    """获取全局热键管理器实例"""
    global _hotkey_manager_instance
    if _hotkey_manager_instance is None:
        _hotkey_manager_instance = HotkeyManager()
    return _hotkey_manager_instance
