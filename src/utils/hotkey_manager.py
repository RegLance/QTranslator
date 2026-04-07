"""全局热键管理模块 - 用于注册和管理全局快捷键"""
import sys
from typing import Optional, Callable
from PyQt6.QtCore import QObject, pyqtSignal

try:
    from ..utils.logger import log_info, log_error, log_debug
except ImportError:
    from utils.logger import log_info, log_error, log_debug


class HotkeyManager(QObject):
    """全局热键管理器"""

    # 信号
    hotkey_triggered = pyqtSignal()  # 热键触发信号

    def __init__(self):
        super().__init__()
        self._hotkey: Optional[str] = None
        self._callback: Optional[Callable] = None
        self._is_listening = False
        self._keyboard = None

    def register_hotkey(self, hotkey: str, callback: Callable = None) -> bool:
        """注册全局热键

        Args:
            hotkey: 热键字符串，如 "Ctrl+Shift+T"
            callback: 热键触发时的回调函数

        Returns:
            bool: 是否成功注册
        """
        # 先注销旧热键
        self.unregister_hotkey()

        self._hotkey = hotkey
        self._callback = callback

        try:
            import keyboard

            # 转换热键格式
            # PyQt格式: Ctrl+Shift+T -> keyboard格式: ctrl+shift+t
            kb_hotkey = hotkey.lower().replace("+", "+")

            # 注册热键
            keyboard.add_hotkey(kb_hotkey, self._on_hotkey_pressed)
            self._keyboard = keyboard
            self._is_listening = True

            log_info(f"已注册全局热键: {hotkey}")
            return True

        except ImportError:
            log_error("未安装 keyboard 库，无法使用全局热键功能")
            return False
        except Exception as e:
            log_error(f"注册热键失败: {e}")
            return False

    def unregister_hotkey(self):
        """注销当前热键"""
        if self._keyboard and self._hotkey:
            try:
                kb_hotkey = self._hotkey.lower().replace("+", "+")
                self._keyboard.remove_hotkey(kb_hotkey)
                log_debug(f"已注销热键: {self._hotkey}")
            except Exception as e:
                log_error(f"注销热键失败: {e}")

        self._is_listening = False

    def _on_hotkey_pressed(self):
        """热键按下时的处理"""
        log_debug(f"热键触发: {self._hotkey}")

        # 发射信号
        self.hotkey_triggered.emit()

        # 调用回调
        if self._callback:
            try:
                self._callback()
            except Exception as e:
                log_error(f"热键回调执行失败: {e}")

    def update_hotkey(self, new_hotkey: str) -> bool:
        """更新热键

        Args:
            new_hotkey: 新的热键字符串

        Returns:
            bool: 是否成功更新
        """
        if self._callback:
            return self.register_hotkey(new_hotkey, self._callback)
        return self.register_hotkey(new_hotkey)

    def stop(self):
        """停止热键监听"""
        self.unregister_hotkey()

    @property
    def is_listening(self) -> bool:
        """是否正在监听"""
        return self._is_listening

    @property
    def current_hotkey(self) -> Optional[str]:
        """当前热键"""
        return self._hotkey


# 全局热键管理器实例
_hotkey_manager_instance: Optional[HotkeyManager] = None


def get_hotkey_manager() -> HotkeyManager:
    """获取全局热键管理器实例"""
    global _hotkey_manager_instance
    if _hotkey_manager_instance is None:
        _hotkey_manager_instance = HotkeyManager()
    return _hotkey_manager_instance