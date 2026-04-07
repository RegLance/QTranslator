"""翻译服务模块 - OpenAI API 封装（支持流式翻译、智能语言检测）"""
import hashlib
from typing import Optional, Dict, Generator, Callable
from dataclasses import dataclass
import sys
from pathlib import Path

# 添加父目录到路径以支持相对导入
_parent_dir = Path(__file__).parent.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

from openai import OpenAI

try:
    from ..config import get_config
    from ..utils.logger import log_warning, log_info, log_translation, log_debug
    from ..utils.language_detector import detect_language, is_chinese_text, get_translation_direction
except ImportError:
    from config import get_config
    from utils.logger import log_warning, log_info, log_translation, log_debug
    from utils.language_detector import detect_language, is_chinese_text, get_translation_direction


@dataclass
class TranslationResult:
    """翻译结果"""
    original_text: str
    translated_text: str
    source_language: Optional[str] = None
    target_language: str = "中文"
    error: Optional[str] = None


class Translator:
    """翻译服务类"""

    def __init__(self):
        """初始化翻译服务"""
        self._client: Optional[OpenAI] = None
        self._cache: Dict[str, TranslationResult] = {}
        self._init_client()

    def _init_client(self):
        """初始化 OpenAI 客户端"""
        config = get_config()
        api_key = config.get('translator.api_key', '')

        if not api_key:
            log_warning("未配置 OpenAI API Key，请在 config.yaml 中设置")
            self._client = None
            return

        self._client = OpenAI(
            api_key=api_key,
            base_url=config.get('translator.base_url', 'https://api.openai.com/v1'),
            timeout=config.get('translator.timeout', 60),
        )

    def _get_cache_key(self, text: str, target_language: str, source_language: str = None) -> str:
        """生成缓存键"""
        return hashlib.md5(f"{text}:{source_language}:{target_language}".encode()).hexdigest()

    def _build_translation_prompt(self, text: str, source_lang: str, target_lang: str) -> tuple:
        """构建翻译提示词（参考 nextai-translator）
        
        Returns:
            tuple: (system_prompt, user_prompt)
        """
        # 判断是否翻译成中文
        to_chinese = target_lang in ['中文', 'zh', 'zh-cn', 'zh-hans']
        
        # 判断是否是单词模式（短文本且无空格或只有一个单词）
        is_single_word = len(text.strip()) <= 20 and (
            ' ' not in text.strip() or 
            (text.strip().count(' ') == 0 and len(text.strip()) < 15)
        )
        
        if to_chinese:
            # 翻译成中文
            if is_single_word and not is_chinese_text(text):
                # 单词模式：详细翻译
                system_prompt = """你是一个翻译引擎，请翻译给出的文本，只需要翻译不需要解释。
当且仅当文本只有一个单词时，请给出单词原始形态（如果有）、单词的语种、对应的音标、所有含义（含词性）、双语示例，至少三条例句。
如果你认为单词拼写错误，请提示我最可能的正确拼写，否则请严格按照下面格式给到翻译结果：

<单词>
[<语种>]· /[<音标>]
[<词性缩写>] <中文含义>]
例句：
<序号><例句>(例句翻译)
词源：
<词源>"""
                user_prompt = f"单词是：{text}"
            else:
                # 普通翻译模式
                system_prompt = f"""你是一个专业的翻译引擎，请将文本翻译成{target_lang}。
翻译要求：
1. 保持原文的风格和语气
2. 对于专业术语，给出准确的翻译
3. 如果是代码或技术内容，保持专业性和准确性
4. 直接输出翻译结果，不要添加解释或注释
5. 翻译应该自然流畅，符合目标语言的表达习惯"""
                user_prompt = text
        else:
            # 翻译成其他语言（如英文）
            if is_single_word and is_chinese_text(text):
                # 中文单词翻译成英文
                system_prompt = f"""You are a professional translation engine.
Please translate the text into {target_lang} without explanation.
When the text has only one word or short phrase, please act as a professional Chinese-English dictionary,
and list all senses with parts of speech, sentence examples (at least 3).

Format:
<word>
[<part of speech>] <meaning>
Examples:
<index>. <sentence>(<sentence translation>)"""
                user_prompt = f"The word/phrase is: {text}"
            else:
                # 普通翻译模式
                system_prompt = f"""You are a professional translation engine.
Please translate the text into {target_lang} without explanation.

Requirements:
1. Keep the style and tone of the original text
2. For professional terms, provide accurate translations
3. For code or technical content, maintain professionalism and accuracy
4. Output the translation directly without adding explanations
5. The translation should be natural and fluent"""
                user_prompt = text

        return (system_prompt, user_prompt)

    def _build_smart_prompt(self, text: str) -> tuple:
        """构建智能翻译提示词（自动检测语言并确定翻译方向）
        
        Returns:
            tuple: (system_prompt, user_prompt, source_lang, target_lang)
        """
        # 检测语言并确定翻译方向
        source_lang, target_lang, source_code = get_translation_direction(text)
        
        log_debug(f"智能翻译: {source_lang} -> {target_lang}")
        
        system_prompt, user_prompt = self._build_translation_prompt(text, source_lang, target_lang)
        
        return (system_prompt, user_prompt, source_lang, target_lang)

    def translate_stream(self, text: str, target_language: str = None,
                         on_chunk: Callable[[str], None] = None,
                         auto_detect: bool = True) -> Generator[str, None, None]:
        """流式翻译文本

        Args:
            text: 待翻译的文本
            target_language: 目标语言（如果为None且auto_detect=True，则自动检测）
            on_chunk: 每次收到新内容时的回调函数
            auto_detect: 是否自动检测语言并确定翻译方向

        Yields:
            str: 翻译结果的文本片段
        """
        if not text or not text.strip():
            yield ""
            return

        text = text.strip()
        
        # 智能检测语言并确定翻译方向
        if auto_detect and target_language is None:
            source_lang, target_lang, source_code = get_translation_direction(text)
            system_prompt, user_prompt = self._build_translation_prompt(text, source_lang, target_lang)
            cache_key = self._get_cache_key(text, target_lang, source_lang)
        else:
            # 使用指定的目标语言
            if target_language is None:
                target_language = get_config().target_language
            
            # 检测源语言
            source_code, source_lang = detect_language(text)
            system_prompt, user_prompt = self._build_translation_prompt(text, source_lang, target_language)
            cache_key = self._get_cache_key(text, target_language, source_lang)
            target_lang = target_language

        # 检查缓存
        if cache_key in self._cache:
            cached_result = self._cache[cache_key].translated_text
            yield cached_result
            return

        # 检查客户端
        if self._client is None:
            config = get_config()
            api_key = config.get('translator.api_key', '')
            base_url = config.get('translator.base_url', '')
            model = config.get('translator.model', '')

            if not api_key:
                yield "[错误: 请先在设置中配置 API Key]"
                return
            if not base_url:
                yield "[错误: 请先在设置中配置 Base URL]"
                return
            if not model:
                yield "[错误: 请先在设置中配置 Model]"
                return

            self._init_client()
            if self._client is None:
                yield "[错误: API 配置无效，请检查设置]"
                return

        try:
            model = get_config().get('translator.model', 'gpt-4o-mini')
            stream = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1000,
                temperature=0.3,
                stream=True,
            )

            full_text = ""
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_text += content
                    if on_chunk:
                        on_chunk(content)
                    yield content

            # 存入缓存
            result = TranslationResult(
                original_text=text,
                translated_text=full_text.strip(),
                source_language=source_lang,
                target_language=target_lang
            )
            self._cache[cache_key] = result

        except Exception as e:
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "401" in error_msg:
                error_msg = "API Key 无效或未配置"
            elif "rate_limit" in error_msg.lower() or "429" in error_msg:
                error_msg = "请求过于频繁，请稍后重试"
            elif "connection" in error_msg.lower():
                error_msg = "网络连接失败"
            else:
                error_msg = f"翻译失败: {error_msg}"

            yield f"[错误: {error_msg}]"

    def translate_sync(self, text: str, target_language: str = None,
                        auto_detect: bool = True) -> TranslationResult:
        """同步翻译（用于非流式场景）"""
        if not text or not text.strip():
            return TranslationResult(
                original_text=text,
                translated_text="",
                error="文本为空"
            )

        text = text.strip()
        
        # 智能检测语言并确定翻译方向
        if auto_detect and target_language is None:
            source_lang, target_lang, source_code = get_translation_direction(text)
            system_prompt, user_prompt = self._build_translation_prompt(text, source_lang, target_lang)
            cache_key = self._get_cache_key(text, target_lang, source_lang)
        else:
            if target_language is None:
                target_language = get_config().target_language
            
            source_code, source_lang = detect_language(text)
            system_prompt, user_prompt = self._build_translation_prompt(text, source_lang, target_language)
            cache_key = self._get_cache_key(text, target_language, source_lang)
            target_lang = target_language

        # 检查缓存
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 检查客户端
        if self._client is None:
            config = get_config()
            api_key = config.get('translator.api_key', '')
            base_url = config.get('translator.base_url', '')
            model = config.get('translator.model', '')

            if not api_key:
                return TranslationResult(
                    original_text=text,
                    translated_text="",
                    error="请先在设置中配置 API Key",
                    target_language=target_lang
                )
            if not base_url:
                return TranslationResult(
                    original_text=text,
                    translated_text="",
                    error="请先在设置中配置 Base URL",
                    target_language=target_lang
                )
            if not model:
                return TranslationResult(
                    original_text=text,
                    translated_text="",
                    error="请先在设置中配置 Model",
                    target_language=target_lang
                )

            self._init_client()
            if self._client is None:
                return TranslationResult(
                    original_text=text,
                    translated_text="",
                    error="API 配置无效，请检查设置",
                    target_language=target_lang
                )

        try:
            model = get_config().get('translator.model', 'gpt-4o-mini')
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1000,
                temperature=0.3,
            )

            translated_text = response.choices[0].message.content.strip()

            result = TranslationResult(
                original_text=text,
                translated_text=translated_text,
                source_language=source_lang,
                target_language=target_lang
            )

            self._cache[cache_key] = result
            return result

        except Exception as e:
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "401" in error_msg:
                error_msg = "API Key 无效或未配置"
            elif "rate_limit" in error_msg.lower() or "429" in error_msg:
                error_msg = "请求过于频繁，请稍后重试"
            elif "connection" in error_msg.lower():
                error_msg = "网络连接失败"

            return TranslationResult(
                original_text=text,
                translated_text="",
                error=error_msg,
                target_language=target_lang
            )

    def clear_cache(self):
        """清除翻译缓存"""
        self._cache.clear()

    def reinitialize(self):
        """重新初始化客户端（配置变更后）"""
        self._init_client()


# 全局翻译器实例
_translator_instance: Optional[Translator] = None


def get_translator() -> Translator:
    """获取全局翻译器实例"""
    global _translator_instance
    if _translator_instance is None:
        _translator_instance = Translator()
    return _translator_instance


def reinitialize_translator():
    """重新初始化翻译器"""
    global _translator_instance
    if _translator_instance is not None:
        _translator_instance.reinitialize()
    else:
        _translator_instance = Translator()