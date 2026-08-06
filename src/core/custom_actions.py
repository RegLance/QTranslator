"""自定义工具栏功能扩展 - QTranslator

用户可以在 actions 目录（AppData/Local/QTranslator/actions/）下放置 .py 文件，
每个文件即一个工具栏按钮（扩展接口，方法由用户自己添加，如：提问题、提 bug、
调用自己的服务等）。

扩展约定（每个 .py 文件）：

    ACTION_NAME = "按钮显示名"     # 可选，缺省用文件名
    ACTION_ICON = "❓"              # 可选，按钮前缀图标文字

    def run(text: str) -> str:
        '''text 为当前划词选中的文本；返回值显示在 AI 对话窗口中。
        返回空字符串则只提示"已执行"。'''
        return "处理结果..."

actions 目录中的文件在每次划词弹出工具栏时重新加载，改完即时生效。
"""
import importlib.util
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

try:
    from ..config import get_config
    from ..utils.logger import log_info, log_error, log_debug
except ImportError:
    from src.config import get_config
    from src.utils.logger import log_info, log_error, log_debug


@dataclass
class CustomAction:
    """一个用户自定义工具栏功能"""
    name: str                    # 按钮显示名
    icon: str                    # 前缀图标文字（可为空）
    file_path: str               # 扩展脚本路径
    run: Callable[[str], str]    # run(text) -> result


_EXAMPLE_DOC_ONLY = ''  # 不再自动生成示例文件；用户按模块文档约定自行创建 .py 扩展


class CustomActionManager:
    """自定义功能扫描与加载"""

    def __init__(self):
        self._dir: Path = get_config().app_dir / "actions"
        self._ensure_dir()

    @property
    def actions_dir(self) -> Path:
        return self._dir

    def _ensure_dir(self):
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_error(f"创建 actions 目录失败: {e}")

    def load_actions(self) -> List[CustomAction]:
        """扫描 actions 目录并加载所有扩展（每次调用都重新加载，改完即时生效）"""
        actions: List[CustomAction] = []
        try:
            if not self._dir.exists():
                return actions
            for py_file in sorted(self._dir.glob("*.py")):
                action = self._load_one(py_file)
                if action:
                    actions.append(action)
        except Exception as e:
            log_error(f"扫描 actions 目录失败: {e}")
        log_debug(f"已加载 {len(actions)} 个自定义功能")
        return actions

    def _load_one(self, py_file: Path) -> Optional[CustomAction]:
        """加载单个扩展脚本；任何错误只跳过该文件，不影响其它扩展"""
        module_name = f"_qtranslator_action_{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, str(py_file))
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            run_fn = getattr(module, 'run', None)
            if not callable(run_fn):
                log_error(f"自定义功能缺少 run(text) 函数，已跳过: {py_file.name}")
                return None

            name = str(getattr(module, 'ACTION_NAME', '') or py_file.stem).strip()
            icon = str(getattr(module, 'ACTION_ICON', '') or '').strip()
            return CustomAction(name=name, icon=icon, file_path=str(py_file), run=run_fn)
        except Exception as e:
            log_error(f"加载自定义功能失败 {py_file.name}: {e}\n{traceback.format_exc()}")
            return None


# 全局实例
_manager_instance: Optional[CustomActionManager] = None


def get_custom_action_manager() -> CustomActionManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = CustomActionManager()
    return _manager_instance
