"""配置管理模块 - QTranslator"""
import os
import sys
import yaml
import json
import traceback
from pathlib import Path
from typing import Any, Dict
from datetime import datetime


# 应用名称
APP_NAME = "QTranslator"
APP_ID = "com.qtranslator.app"


def get_app_data_dir() -> Path:
    """获取应用数据目录（在用户AppData目录下）"""
    if sys.platform == 'win32':
        # Windows: C:\Users\用户名\AppData\Local\QTranslator
        base_dir = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        app_dir = Path(base_dir) / APP_NAME
    elif sys.platform == 'darwin':
        # macOS: ~/Library/Application Support/QTranslator
        app_dir = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        # Linux: ~/.config/qtranslator
        app_dir = Path.home() / ".config" / "qtranslator"

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
        self._backup_path = self._app_dir / "config.yaml.bak"
        self._crash_log_path = self._app_dir / "crash.log"

        print(f"配置目录: {self._app_dir}", file=sys.stderr)
        print(f"配置文件: {self._config_path}", file=sys.stderr)

        # 加载配置
        if self._config_path.exists():
            self._config = self._load_config(str(self._config_path))
            # 验证加载的配置是否有效（至少包含基本结构）
            if not self._validate_config(self._config):
                print("配置文件验证失败，尝试从备份恢复", file=sys.stderr)
                self._restore_from_backup()
        else:
            # 尝试从旧位置迁移
            self._migrate_from_old_location()
            if not self._config_path.exists():
                self._config = self._get_default_config()
                self.save()

    def _validate_config(self, config: Dict[str, Any]) -> bool:
        """验证配置是否有效"""
        if config is None:
            return False
        # 检查必需的配置结构（translator 不再必需，已硬编码）
        required_keys = ['target_language', 'theme']
        for key in required_keys:
            if key not in config:
                print(f"配置缺少必需字段: {key}", file=sys.stderr)
                return False
        return True

    def _restore_from_backup(self):
        """从备份恢复配置"""
        if self._backup_path.exists():
            try:
                self._config = self._load_config(str(self._backup_path))
                if self._validate_config(self._config):
                    print("已从备份恢复配置", file=sys.stderr)
                    # 恢复后重新保存
                    self.save()
                    return
            except Exception as e:
                print(f"从备份恢复失败: {e}", file=sys.stderr)
        # 如果备份也无效，使用默认配置
        print("使用默认配置", file=sys.stderr)
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
                content = f.read()
                if not content.strip():
                    print(f"配置文件为空: {path}", file=sys.stderr)
                    return self._get_default_config()
                config = yaml.safe_load(content)
                if config is None:
                    return self._get_default_config()
                
                # 清理硬编码的配置项（不再从配置文件读取）
                if 'translator' in config and isinstance(config['translator'], dict):
                    for key in ['api_key', 'base_url', 'model', 'timeout', 'no_proxy']:
                        if key in config['translator']:
                            del config['translator'][key]
                # 如果 translator 为空，删除整个键
                if 'translator' in config and isinstance(config['translator'], dict) and not config['translator']:
                    del config['translator']
                
                return self._merge_with_defaults(config)
        except yaml.YAMLError as e:
            print(f"YAML解析错误: {e}", file=sys.stderr)
            return self._get_default_config()
        except Exception as e:
            print(f"加载配置文件失败: {e}", file=sys.stderr)
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置（API 配置已硬编码）"""
        return {
            'target_language': '中文',
            'theme': {
                'popup_style': 'dark',  # 'dark' 或 'light'
                'opacity': 0.95,
            },
            'font': {
                'size': 15,  # 字体大小
            },
            'hotkey': {
                'translator_window': 'Ctrl+O',  # 唤醒翻译窗口的快捷键
                'writing': 'Ctrl+I',  # 写作快捷键
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
            'translator_window': {
                'fixed_height_mode': False,  # 固定高度模式（勾选后不自动调整窗口高度）
                'remember_window_position': False,  # 记忆窗口位置（勾选后记住窗口关闭时的位置）
            },
            'selection': {
                'browser_delay_ms': 450,  # 浏览器环境下划词延迟（毫秒）
            },
        }

    def _merge_with_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """合并用户配置与默认配置"""
        defaults = self._get_default_config()

        def merge_dict(base: dict, override: dict, parent_key: str = '') -> dict:
            result = base.copy()
            for key, value in override.items():
                # 跳过硬编码的配置项（在 translator 下）
                if parent_key == 'translator' and key in ('api_key', 'base_url', 'model', 'timeout', 'no_proxy'):
                    continue
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = merge_dict(result[key], value, key)
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
        """保存配置到文件（带备份机制和验证）"""
        try:
            # 先创建备份（如果原文件存在且有效）
            if self._config_path.exists():
                try:
                    import shutil
                    shutil.copy(str(self._config_path), str(self._backup_path))
                except Exception as e:
                    print(f"创建备份失败: {e}", file=sys.stderr)

            # 写入新配置
            config_content = yaml.safe_dump(
                self._config,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False  # 保持原有顺序
            )

            with open(self._config_path, 'w', encoding='utf-8') as f:
                f.write(config_content)

            # 验证保存是否成功 - 立即重新加载验证
            with open(self._config_path, 'r', encoding='utf-8') as f:
                saved_content = f.read()
                saved_config = yaml.safe_load(saved_content)
                if saved_config is None:
                    raise Exception("保存后配置文件为空")

            print(f"配置已保存到: {self._config_path}", file=sys.stderr)

        except yaml.YAMLError as e:
            print(f"YAML序列化错误: {e}", file=sys.stderr)
            self._log_crash(f"配置保存YAML错误: {e}\n{traceback.format_exc()}")
        except Exception as e:
            print(f"保存配置文件失败: {e}", file=sys.stderr)
            self._log_crash(f"配置保存失败: {e}\n{traceback.format_exc()}")

    def _log_crash(self, message: str):
        """记录崩溃日志"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self._crash_log_path, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*50}\n")
                f.write(f"[{timestamp}] CRASH LOG\n")
                f.write(f"{'='*50}\n")
                f.write(message)
                f.write(f"\n{'='*50}\n")
        except Exception:
            pass  # 避免日志写入失败导致程序崩溃

    @property
    def crash_log_path(self) -> Path:
        """崩溃日志路径"""
        return self._crash_log_path

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