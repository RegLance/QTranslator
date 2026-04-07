"""配置管理模块 - Translate Copilot"""
import os
import sys
import yaml
import json
from pathlib import Path
from typing import Any, Dict


# 应用名称
APP_NAME = "Translate Copilot"
APP_ID = "com.translate.copilot"


def get_app_data_dir() -> Path:
    """获取应用数据目录（在用户AppData目录下）"""
    if sys.platform == 'win32':
        # Windows: C:\Users\用户名\AppData\Local\Translate Copilot
        base_dir = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        app_dir = Path(base_dir) / APP_NAME
    elif sys.platform == 'darwin':
        # macOS: ~/Library/Application Support/Translate Copilot
        app_dir = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        # Linux: ~/.config/translate-copilot
        app_dir = Path.home() / ".config" / "translate-copilot"
    
    # 确保目录存在
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


class Config:
    """配置管理类"""

    def __init__(self):
        """初始化配置"""
        self._app_dir = get_app_data_dir()
        self._config_path = self._app_dir / "config.yaml"
        self._cache_path = self._app_dir / "cache.json"
        
        print(f"配置目录: {self._app_dir}", file=sys.stderr)
        print(f"配置文件: {self._config_path}", file=sys.stderr)
        
        # 加载配置
        if self._config_path.exists():
            self._config = self._load_config(str(self._config_path))
        else:
            # 尝试从旧位置迁移
            self._migrate_from_old_location()
            if not self._config_path.exists():
                self._config = self._get_default_config()
                self.save()

    def _migrate_from_old_location(self):
        """从旧位置迁移配置"""
        src_dir = Path(__file__).parent
        project_dir = src_dir.parent
        old_config = project_dir / "config.yaml"
        
        if old_config.exists():
            try:
                import shutil
                shutil.copy(str(old_config), str(self._config_path))
                print(f"已迁移配置文件到: {self._config_path}", file=sys.stderr)
                self._config = self._load_config(str(self._config_path))
            except Exception as e:
                print(f"迁移配置文件失败: {e}", file=sys.stderr)
                self._config = self._get_default_config()

    def _load_config(self, path: str) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config is None:
                    return self._get_default_config()
                return self._merge_with_defaults(config)
        except Exception as e:
            print(f"加载配置文件失败: {e}", file=sys.stderr)
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置（不包含 API 配置，用户需要自己填写）"""
        return {
            'translator': {
                'api_key': '',
                'model': '',
                'base_url': '',
                'timeout': 30,
            },
            'target_language': '中文',
            'theme': {
                'popup_style': 'dark',  # 'dark' 或 'light'
                'opacity': 0.95,
            },
            'font': {
                'size': 14,  # 字体大小
            },
            'hotkey': {
                'translator_window': 'Ctrl+Shift+T',  # 唤醒翻译窗口的快捷键
                'writing': 'Ctrl+Shift+W',  # 写作快捷键
            },
            'startup': {
                'auto_start': False,  # 开机自启
            },
            'popup': {
                'opacity': 0.95,
            },
            'writing': {
                'keep_original': False,  # 保留原文
            },
        }

    def _merge_with_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """合并用户配置与默认配置"""
        defaults = self._get_default_config()

        def merge_dict(base: dict, override: dict) -> dict:
            result = base.copy()
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = merge_dict(result[key], value)
                else:
                    result[key] = value
            return result

        return merge_dict(defaults, config)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持点分隔的嵌套键）"""
        keys = key.split('.')
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key: str, value: Any):
        """设置配置值"""
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    def save(self):
        """保存配置到文件"""
        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(self._config, f, allow_unicode=True, default_flow_style=False)
            print(f"配置已保存到: {self._config_path}", file=sys.stderr)
        except Exception as e:
            print(f"保存配置文件失败: {e}", file=sys.stderr)

    @property
    def app_dir(self) -> Path:
        """应用数据目录"""
        return self._app_dir

    @property
    def config_path(self) -> Path:
        """配置文件路径"""
        return self._config_path

    @property
    def translator(self) -> Dict[str, Any]:
        """翻译服务配置"""
        return self._config.get('translator', {})

    @property
    def target_language(self) -> str:
        """目标语言"""
        return self._config.get('target_language', '中文')

    @property
    def theme(self) -> Dict[str, Any]:
        """主题配置"""
        return self._config.get('theme', {})

    @property
    def startup(self) -> Dict[str, Any]:
        """启动配置"""
        return self._config.get('startup', {})


# 全局配置实例
_config_instance: Config = None


def get_config() -> Config:
    """获取全局配置实例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reload_config():
    """重新加载配置"""
    global _config_instance
    _config_instance = Config()