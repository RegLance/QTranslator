"""语言检测模块 - 智能检测文本语言"""
import re
from typing import Optional, Tuple
from langdetect import detect, LangDetectException

try:
    from ..utils.logger import log_debug, log_warning
except ImportError:
    from src.utils.logger import log_debug, log_warning


# 中文语言代码列表
CHINESE_CODES = ['zh-cn', 'zh-tw', 'zh-hans', 'zh-hant', 'zh']

# 语言代码到语言名称的映射
LANG_CODE_TO_NAME = {
    'zh': '中文',
    'zh-cn': '中文',
    'zh-tw': '中文',
    'zh-hans': '中文',
    'zh-hant': '中文',
    'en': '英文',
    'ja': '日文',
    'ko': '韩文',
    'fr': '法文',
    'de': '德文',
    'es': '西班牙文',
    'ru': '俄文',
    'pt': '葡萄牙文',
    'it': '意大利文',
    'ar': '阿拉伯文',
    'th': '泰文',
    'vi': '越南文',
    'nl': '荷兰文',
    'pl': '波兰文',
    'tr': '土耳其文',
}

# 语言名称到语言代码的映射
LANG_NAME_TO_CODE = {
    '中文': 'zh',
    '英文': 'en',
    '日文': 'ja',
    '韩文': 'ko',
    '法文': 'fr',
    '德文': 'de',
    '西班牙文': 'es',
    '俄文': 'ru',
    '葡萄牙文': 'pt',
    '意大利文': 'it',
}


def is_chinese_text(text: str) -> bool:
    """判断文本是否主要是中文
    
    Args:
        text: 待检测文本
        
    Returns:
        bool: 是否为中文文本
    """
    # 统计中文字符数量
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    # 统计所有非空白字符
    non_space_chars = re.sub(r'\s', '', text)
    
    if len(non_space_chars) == 0:
        return False
    
    ratio = len(chinese_chars) / len(non_space_chars)
    result = ratio > 0.3
    
    # 调试日志
    log_debug(f"[语言检测] 中文字符数={len(chinese_chars)}, 总字符数={len(non_space_chars)}, 比例={ratio:.2f}, 判断为中文={result}")
    
    return result


def detect_language(text: str) -> Tuple[str, str]:
    """检测文本语言
    
    Args:
        text: 待检测文本
        
    Returns:
        Tuple[str, str]: (语言代码, 语言名称)
    """
    if not text or not text.strip():
        return ('en', '英文')
    
    text = text.strip()
    
    # 先用本地规则快速判断中文
    if is_chinese_text(text):
        return ('zh', '中文')
    
    # 使用 langdetect 进行检测
    try:
        # 截取前 200 个字符进行检测，提高效率
        sample = text[:200] if len(text) > 200 else text
        lang_code = detect(sample)
        
        # 转换为语言名称
        lang_name = LANG_CODE_TO_NAME.get(lang_code, '英文')
        
        log_debug(f"检测到语言: {lang_code} -> {lang_name}")
        return (lang_code, lang_name)
        
    except LangDetectException as e:
        log_warning(f"语言检测失败: {e}，默认使用英文")
        return ('en', '英文')
    except Exception as e:
        log_warning(f"语言检测异常: {e}")
        return ('en', '英文')


def get_target_language_for_text(text: str, default_target: str = '中文') -> str:
    """根据源文本自动确定目标语言
    
    当文本是非中文时，翻译成中文；当文本是中文时，翻译成英文。
    
    Args:
        text: 源文本
        default_target: 默认目标语言（当无法检测时使用）
        
    Returns:
        str: 目标语言名称
    """
    lang_code, lang_name = detect_language(text)
    
    # 如果检测到的是中文，目标语言是英文
    if lang_code in CHINESE_CODES or lang_name == '中文':
        return '英文'
    
    # 如果检测到的是非中文，目标语言是中文
    return '中文'


def get_translation_direction(text: str) -> Tuple[str, str, str]:
    """获取翻译方向
    
    Args:
        text: 源文本
        
    Returns:
        Tuple[str, str, str]: (源语言名称, 目标语言名称, 源语言代码)
    """
    lang_code, lang_name = detect_language(text)
    
    if lang_code in CHINESE_CODES or lang_name == '中文':
        return ('中文', '英文', lang_code)
    else:
        return (lang_name, '中文', lang_code)


class LanguageDetector:
    """语言检测器类"""
    
    def __init__(self):
        """初始化语言检测器"""
        pass
    
    def detect(self, text: str) -> Tuple[str, str]:
        """检测语言"""
        return detect_language(text)
    
    def is_chinese(self, text: str) -> bool:
        """判断是否为中文"""
        return is_chinese_text(text)
    
    def get_target_language(self, text: str) -> str:
        """获取目标语言"""
        return get_target_language_for_text(text)
    
    def get_translation_direction(self, text: str) -> Tuple[str, str, str]:
        """获取翻译方向"""
        return get_translation_direction(text)


# 全局检测器实例
_detector_instance: Optional[LanguageDetector] = None


def get_language_detector() -> LanguageDetector:
    """获取全局语言检测器实例"""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = LanguageDetector()
    return _detector_instance