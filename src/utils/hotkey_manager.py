"""全局热键管理模块 - 用于注册和管理全局快捷键

支持多个热键注册：
- 翻译窗口热键
- 写作热键

优化：
- 使用 keyboard 库返回的句柄进行精确注销，避免字符串匹配失败导致的钩子泄漏
- 添加定期健康检查，在锁屏/解锁后自动重新注册热键
"""
import sys
from typing import Optional, Callable, Dict, Any
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QMetaObject, QTimer

try:
    from ..utils.logger import log_info, log_error, log_debug
except ImportError:
    from src.utils.logger import log_info, log_error, log_debug


class HotkeyManager(QObject):
    """全局热键管理器"""

    # 信号
    hotkey_triggered = pyqtSignal()  # 翻译窗口热键触发信号
    writing_hotkey_triggered = pyqtSignal()  # 写作热键触发信号

    def __init__(self):
        super().__init__()
        self._hotkeys: Dict[str, str] = {}  # hotkey_name -> hotkey_string
        self._hotkey_handles: Dict[str, Any] = {}  # hotkey_name -> keyboard hook handle
        self._keyboard = None
        self._is_listening = False

        # 健康检查计时器：每 60 秒检查一次热键是否仍然有效
        self._health_check_timer = QTimer()
        self._health_check_timer.setInterval(60000)
        self._health_check_timer.timeout.connect(self._check_hotkey_health)

    def register_hotkey(self, hotkey: str, callback: Callable = None, name: str = "translator_window") -> bool:
        """注册全局热键

        Args:
            hotkey: 热键字符串，如 "Ctrl+O"
            callback: 热键触发时的回调函数（可选，建议使用信号）
            name: 热键名称，用于标识不同的热键

        Returns:
            bool: 是否成功注册
        """
        # 如果该名称的热键已存在，先注销
        self.unregister_hotkey(name)

        self._hotkeys[name] = hotkey

        try:
            import keyboard

            # 转换热键格式
            # PyQt格式: Ctrl+O -> keyboard格式: ctrl+o
            kb_hotkey = hotkey.lower()

            # 根据热键名称选择回调
            if name == "writing":
                callback_func = self._on_writing_hotkey_pressed
            else:
                callback_func = self._on_hotkey_pressed

            # 注册热键并保存返回的句柄，用于精确注销
            handle = keyboard.add_hotkey(kb_hotkey, callback_func)
            self._hotkey_handles[name] = handle
            self._keyboard = keyboard
            self._is_listening = True

            # 启动健康检查（如果尚未启动）
            if not self._health_check_timer.isActive():
                self._health_check_timer.start()

            log_info(f"已注册全局热键 [{name}]: {hotkey}")
            return True

        except ImportError:
            log_error("未安装 keyboard 库，无法使用全局热键功能")
            return False
        except Exception as e:
            log_error(f"注册热键失败: {e}")
            return False

    def unregister_hotkey(self, name: str = None):
        """注销热键

        Args:
            name: 热键名称，如果为 None 则注销所有热键
        """
        if not self._keyboard:
            return

        if name is None:
            # 注销所有热键
            for hotkey_name in list(self._hotkeys.keys()):
                self._remove_hotkey(hotkey_name)
            self._hotkeys.clear()
            self._hotkey_handles.clear()
        elif name in self._hotkeys:
            self._remove_hotkey(name)
            del self._hotkeys[name]
            self._hotkey_handles.pop(name, None)

        if not self._hotkeys:
            self._is_listening = False

    def _remove_hotkey(self, name: str):
        """移除单个热键（使用句柄精确注销）"""
        if not self._keyboard:
            return

        # 优先使用保存的句柄进行注销（更精确可靠）
        handle = self._hotkey_handles.get(name)
        if handle is not None:
            try:
                self._keyboard.remove_hotkey(handle)
                log_debug(f"已通过句柄注销热键: {name}")
                return
            except Exception as e:
                log_debug(f"通过句柄注销热键失败，尝试字符串方式: {e}")

        # 回退：使用热键字符串注销
        hotkey = self._hotkeys.get(name)
        if hotkey:
            try:
                kb_hotkey = hotkey.lower()
                self._keyboard.remove_hotkey(kb_hotkey)
                log_debug(f"已通过字符串注销热键: {hotkey}")
            except Exception as e:
                log_error(f"注销热键失败: {e}")

    def _check_hotkey_health(self):
        """定期检查热键是否仍然有效

        Windows 在锁屏/解锁后，keyboard 库的低级键盘钩子可能被系统卸载。
        通过尝试重新注册来恢复。
        """
        if not self._is_listening or not self._keyboard:
            return

        try:
            # 检查 keyboard 的内部钩子是否还存活
            # keyboard 库使用一个全局的钩子线程，如果线程死了需要重新注册
            import keyboard
            # 尝试调用一个轻量操作来检测钩子是否还活着
            # 如果 keyboard 内部的钩子线程已经终止，这里会出错
            if hasattr(keyboard, '_listener') and keyboard._listener is not None:
                if hasattr(keyboard._listener, 'is_alive') and not keyboard._listener.is_alive():
                    log_info("[热键管理器] 检测到键盘钩子线程已终止，正在重新注册...")
                    self._reinstall_all_hotkeys()
        except Exception as e:
            log_debug(f"热键健康检查异常: {e}")
            # 出现异常可能意味着钩子已损坏，尝试重装
            self._reinstall_all_hotkeys()

    def _reinstall_all_hotkeys(self):
        """重新安装所有热键"""
        # 保存当前热键配置
        saved_hotkeys = dict(self._hotkeys)

        # 尝试清理旧的钩子
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass

        self._hotkeys.clear()
        self._hotkey_handles.clear()

        # 重新注册所有热键
        for name, hotkey in saved_hotkeys.items():
            self.register_hotkey(hotkey, name=name)

        log_info(f"[热键管理器] 已重新注册 {len(saved_hotkeys)} 个热键")

    def _on_hotkey_pressed(self):
        """翻译窗口热键按下时的处理"""
        log_debug(f"翻译窗口热键触发")
        self.hotkey_triggered.emit()

    def _on_writing_hotkey_pressed(self):
        """写作热键按下时的处理"""
        log_debug(f"写作热键触发")
        self.writing_hotkey_triggered.emit()

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
        self._health_check_timer.stop()
        self.unregister_hotkey()
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