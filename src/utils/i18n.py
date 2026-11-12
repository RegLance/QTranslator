"""全局界面语言管理模块 - QTranslator

轻量界面国际化（i18n）实现，与 ThemeManager 相同的信号广播模式：

- 以中文原文为 key，在 EN 对照表（i18n_en.py）中查英文译文；查不到自动回退中文，
  因此漏翻不会导致界面出现空白或异常。
- 配置项 ``ui.language``：``system``（跟随系统，默认）/ ``zh`` / ``en``。
- 切换语言时发射 ``language_changed`` 信号，各窗口通过 ``retranslate_ui()``
  即时重设文案，无需重启；切换过程不改变任何窗口尺寸。

注意：只翻译界面文案。翻译引擎提示词、AI 系统提示词、日志、语言检测逻辑、
TTS 语种参数等功能性字符串一律不走 t()。
"""
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QLocale

try:
    from ..config import get_config
except ImportError:
    from src.config import get_config

try:
    from .i18n_en import EN
except ImportError:
    from src.utils.i18n_en import EN


# 支持的语言设置值
LANGUAGE_SETTINGS = ('system', 'zh', 'en')

# 当前生效语言（'zh' / 'en'），启动时由 init_i18n() 解析
_effective_language: str = 'zh'
_initialized: bool = False


def _resolve(setting: str) -> str:
    """把语言设置解析为生效语言：system 按操作系统区域语言判断"""
    if setting == 'zh':
        return 'zh'
    if setting == 'en':
        return 'en'
    # system（含非法值兜底）：系统区域为中文则中文，否则英文
    try:
        return 'zh' if QLocale.system().language() == QLocale.Language.Chinese else 'en'
    except Exception:
        return 'zh'


def init_i18n():
    """启动时初始化生效语言（不发信号）。应在 QApplication 创建后尽早调用。"""
    global _effective_language, _initialized
    setting = get_config().get('ui.language', 'system') or 'system'
    _effective_language = _resolve(setting)
    _initialized = True


def _ensure_initialized():
    global _initialized
    if not _initialized:
        init_i18n()


def current_language() -> str:
    """当前生效的界面语言：'zh' 或 'en'"""
    _ensure_initialized()
    return _effective_language


def get_language_setting() -> str:
    """当前语言设置：'system' / 'zh' / 'en'"""
    return get_config().get('ui.language', 'system') or 'system'


def t(text: str, *args, **kwargs) -> str:
    """翻译界面文案。

    以中文原文为 key 查英文对照表；中文模式或查不到译文时原样返回。
    带参数时按 str.format 规则填充占位符，例如::

        t("共 {0} 条", count)
        t("已用 {used} / {total}", used=a, total=b)
    """
    _ensure_initialized()
    if _effective_language == 'en':
        text = EN.get(text, text)
    if args or kwargs:
        try:
            return text.format(*args, **kwargs)
        except (IndexError, KeyError, ValueError):
            return text
    return text


class I18nManager(QObject):
    """语言变更信号管理器（单例）

    各窗口通过 connect language_changed 信号调用自身 retranslate_ui()，
    无需在 SettingsDialog 中手动枚举每个窗口（与 ThemeManager 一致）。
    """
    language_changed = pyqtSignal()

    _instance: Optional['I18nManager'] = None

    @classmethod
    def instance(cls) -> 'I18nManager':
        if cls._instance is None:
            cls._instance = I18nManager()
        return cls._instance

    def notify_language_changed(self):
        """发射语言变更信号"""
        self.language_changed.emit()


def get_i18n_manager() -> I18nManager:
    """获取全局语言管理器"""
    return I18nManager.instance()


def set_language(setting: str, persist: bool = True):
    """切换界面语言（即时生效）。

    Args:
        setting: 'system' / 'zh' / 'en'
        persist: 是否写入配置文件（默认写入）
    """
    global _effective_language
    if setting not in LANGUAGE_SETTINGS:
        setting = 'system'
    if persist:
        config = get_config()
        config.set('ui.language', setting)
        config.save()
    new_effective = _resolve(setting)
    if new_effective != _effective_language:
        _effective_language = new_effective
        get_i18n_manager().notify_language_changed()
