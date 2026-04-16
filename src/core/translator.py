"""翻译服务模块 - OpenAI API 封装（支持流式翻译、智能语言检测）"""
import hashlib
import threading
import traceback
from collections import OrderedDict
from typing import Optional, Dict, Generator, Callable, Tuple
from dataclasses import dataclass
import sys
from pathlib import Path
from datetime import datetime

# 添加父目录到路径以支持相对导入
_parent_dir = Path(__file__).parent.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

from openai import OpenAI

try:
    from ..config import get_config
    from ..utils.logger import log_warning, log_info, log_translation, log_debug, log_error
    from ..utils.language_detector import detect_language, is_chinese_text, get_translation_direction
except ImportError:
    # 打包后或直接运行时的导入路径
    from src.config import get_config
    from src.utils.logger import log_warning, log_info, log_translation, log_debug, log_error
    from src.utils.language_detector import detect_language, is_chinese_text, get_translation_direction


# 语言检测锁，确保线程安全
_language_detect_lock = threading.Lock()


def _log_crash_safe(message: str, exc: Exception = None):
    """安全地记录崩溃日志"""
    try:
        crash_path = get_config().crash_log_path
        crash_path.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(crash_path, 'a', encoding='utf-8') as f:
            f.write(f"\n[{timestamp}] Translator: {message}\n")
            if exc:
                f.write(f"Exception: {type(exc).__name__}: {exc}\n")
                f.write(traceback.format_exc())
            f.write("-" * 40 + "\n")
    except Exception:
        pass  # 避免日志写入失败导致程序崩溃


@dataclass
class TranslationResult:
    """翻译结果"""
    original_text: str
    translated_text: str
    source_language: Optional[str] = None
    target_language: str = "中文"
    error: Optional[str] = None
    mode: str = "translate"  # translate, polishing, summarize


class Translator:
    """翻译服务类"""

    MAX_CACHE_SIZE = 500  # 缓存最大条目数

    def __init__(self):
        """初始化翻译服务"""
        self._client: Optional[OpenAI] = None
        self._cache: OrderedDict[str, TranslationResult] = OrderedDict()
        self._last_error: Optional[str] = None
        self._load_api_config()
        self._init_client()

    def _load_api_config(self):
        """从配置文件加载 API 配置"""
        config = get_config()
        self._api_key = config.get('translator.api_key', '')
        self._base_url = config.get('translator.base_url', '')
        self._model = config.get('translator.model', '')
        self._timeout = config.get('translator.timeout', 60)
        self._no_proxy = config.get('translator.no_proxy', '')

    def _init_client(self):
        """初始化 OpenAI 客户端"""
        try:
            # 设置 no_proxy 环境变量（用于控制不使用代理的地址）
            if self._no_proxy:
                import os
                os.environ['NO_PROXY'] = self._no_proxy
                os.environ['no_proxy'] = self._no_proxy
                log_debug(f"已设置 NO_PROXY: {self._no_proxy}")

            # 创建客户端
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
            )
            self._last_error = None
            log_info(f"翻译客户端已初始化: base_url={self._base_url}, model={self._model}")

        except Exception as e:
            log_error(f"初始化翻译客户端失败: {e}")
            _log_crash_safe("初始化翻译客户端失败", e)
            self._client = None
            self._last_error = str(e)

    def get_last_error(self) -> Optional[str]:
        """获取最后的错误信息"""
        return self._last_error

    def _get_cache_key(self, text: str, target_language: str, source_language: str = None) -> str:
        """生成缓存键"""
        return hashlib.md5(f"{text}:{source_language}:{target_language}".encode()).hexdigest()

    def _put_cache(self, key: str, result: TranslationResult):
        """存入缓存（LRU 淘汰策略）"""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = result
        while len(self._cache) > self.MAX_CACHE_SIZE:
            self._cache.popitem(last=False)

    def _ensure_client(self) -> bool:
        """确保客户端可用，返回是否成功"""
        if self._client is None:
            self._init_client()
        return self._client is not None

    @staticmethod
    def _classify_error(e: Exception, fallback_prefix: str = "操作失败") -> str:
        """将异常分类为用户友好的错误消息"""
        error_msg = str(e)
        if "api_key" in error_msg.lower() or "401" in error_msg:
            return "API Key 无效或未配置"
        elif "404" in error_msg:
            return "API URL 无效或模型不存在，请检查 Base URL 和 Model 配置"
        elif "rate_limit" in error_msg.lower() or "429" in error_msg:
            return "请求过于频繁，请稍后重试"
        elif "connection" in error_msg.lower() or "timeout" in error_msg.lower():
            return "网络连接失败或超时，请检查网络"
        elif "model" in error_msg.lower():
            return "模型不存在或不可用，请检查 Model 配置"
        return f"{fallback_prefix}: {error_msg}"

    def _stream_request(self, system_prompt: str, user_prompt: str,
                        on_chunk: Callable[[str], None] = None,
                        error_prefix: str = "操作失败") -> Generator[str, None, str]:
        """通用流式请求（客户端检查、流式迭代、错误分类）
        
        Yields:
            str: 流式文本片段
            
        Returns:
            str: 完整文本（通过 generator 的 return value）
        """
        if not self._ensure_client():
            yield "[错误: API 客户端初始化失败]"
            return ""

        try:
            stream = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                stream=True,
            )

            chunks = []
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    chunks.append(content)
                    if on_chunk:
                        on_chunk(content)
                    yield content

            return "".join(chunks)

        except Exception as e:
            error_msg = self._classify_error(e, error_prefix)
            self._last_error = error_msg
            yield f"[错误: {error_msg}]"
            return ""

    def _resolve_language_and_prompt(self, text: str, target_language: str = None,
                                      auto_detect: bool = True) -> Tuple[str, str, str, str, str]:
        """解析语言方向并构建 prompt
        
        Returns:
            tuple: (system_prompt, user_prompt, cache_key, source_lang, target_lang)
        """
        if auto_detect and target_language is None:
            source_lang, target_lang, source_code = get_translation_direction(text)
        else:
            if target_language is None:
                target_language = get_config().target_language
            source_code, source_lang = detect_language(text)
            target_lang = target_language

        system_prompt, user_prompt = self._build_translation_prompt(text, source_lang, target_lang)
        cache_key = self._get_cache_key(text, target_lang, source_lang)
        return system_prompt, user_prompt, cache_key, source_lang, target_lang

    def _build_translation_prompt(self, text: str, source_lang: str, target_lang: str) -> tuple:
        """构建翻译提示词（参考 nextai-translator）
        
        Returns:
            tuple: (system_prompt, user_prompt)
        """
        # 判断是否翻译成中文
        to_chinese = target_lang in ['中文', 'zh', 'zh-cn', 'zh-hans']
        
        # 判断是否是单词模式（仅适用于拉丁字母为主的短文本，如英文单词）
        # 韩文、日文等 CJK 文字即使无空格也可能是完整短语，不应触发单词词典模式
        stripped = text.strip()
        is_latin_dominant = stripped.isascii() or all(
            c.isascii() or c in '·''""—–' for c in stripped
        )
        is_single_word = is_latin_dominant and len(stripped) <= 20 and ' ' not in stripped
        
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
                system_prompt = f"""你是一个专业的翻译引擎，请将以下{source_lang}文本翻译成{target_lang}。
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
Please translate the following {source_lang} text into {target_lang} without explanation.

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

    def _build_polishing_prompt(self, text: str) -> tuple:
        """构建润色提示词（参考 nextai-translator）

        Returns:
            tuple: (system_prompt, user_prompt)
        """
        # 检测源语言（使用锁确保线程安全）
        with _language_detect_lock:
            source_code, source_lang = detect_language(text)

        system_prompt = 'You are an expert translator, translate directly without explanation.'

        command_prompt = f"""Please edit the following sentences in {source_lang} to improve clarity, conciseness, and coherence, making them match the expression of native speakers. Use Markdown format to highlight the changes: use ~~strikethrough~~ for deleted text and **bold** for added or modified text. Keep the unchanged parts as they are."""

        user_prompt = f"Only reply the result and nothing else. {command_prompt}:\n\n{text.strip()}"

        return (system_prompt, user_prompt)

    def _build_summarize_prompt(self, text: str, target_lang: str = "中文") -> tuple:
        """构建总结提示词（参考 nextai-translator）

        Args:
            text: 待总结的文本
            target_lang: 总结输出语言

        Returns:
            tuple: (system_prompt, user_prompt)
        """
        system_prompt = "You are a professional text summarizer, you can only summarize the text, don't interpret it."

        command_prompt = f"Please summarize this text in the most concise language and must use {target_lang} language!"

        user_prompt = f"Only reply the result and nothing else. {command_prompt}:\n\n{text.strip()}"

        return (system_prompt, user_prompt)

    def polishing_stream(self, text: str,
                         on_chunk: Callable[[str], None] = None) -> Generator[str, None, None]:
        """流式润色文本

        Args:
            text: 待润色的文本
            on_chunk: 每次收到新内容时的回调函数

        Yields:
            str: 润色结果的文本片段
        """
        if not text or not text.strip():
            yield ""
            return

        text = text.strip()
        system_prompt, user_prompt = self._build_polishing_prompt(text)
        yield from self._stream_request(system_prompt, user_prompt, on_chunk, "润色失败")

    def summarize_stream(self, text: str, target_language: str = "中文",
                         on_chunk: Callable[[str], None] = None) -> Generator[str, None, None]:
        """流式总结文本

        Args:
            text: 待总结的文本
            target_language: 总结输出语言
            on_chunk: 每次收到新内容时的回调函数

        Yields:
            str: 总结结果的文本片段
        """
        if not text or not text.strip():
            yield ""
            return

        text = text.strip()
        system_prompt, user_prompt = self._build_summarize_prompt(text, target_language)
        yield from self._stream_request(system_prompt, user_prompt, on_chunk, "总结失败")

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
        system_prompt, user_prompt, cache_key, source_lang, target_lang = \
            self._resolve_language_and_prompt(text, target_language, auto_detect)

        # 检查缓存
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            yield self._cache[cache_key].translated_text
            return

        # 执行流式请求
        full_text_chunks = []
        for content in self._stream_request(system_prompt, user_prompt, on_chunk, "翻译失败"):
            full_text_chunks.append(content)
            yield content

        # 存入缓存（仅在成功时）
        full_text = "".join(full_text_chunks)
        if full_text and not full_text.startswith("[错误:"):
            result = TranslationResult(
                original_text=text,
                translated_text=full_text.strip(),
                source_language=source_lang,
                target_language=target_lang
            )
            self._put_cache(cache_key, result)

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
        system_prompt, user_prompt, cache_key, source_lang, target_lang = \
            self._resolve_language_and_prompt(text, target_language, auto_detect)

        # 检查缓存
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        # 检查客户端
        if not self._ensure_client():
            return TranslationResult(
                original_text=text,
                translated_text="",
                error="API 客户端初始化失败",
                target_language=target_lang
            )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
            )

            translated_text = response.choices[0].message.content.strip()

            result = TranslationResult(
                original_text=text,
                translated_text=translated_text,
                source_language=source_lang,
                target_language=target_lang
            )

            self._put_cache(cache_key, result)
            return result

        except Exception as e:
            error_msg = self._classify_error(e, "翻译失败")
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
        self._load_api_config()
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