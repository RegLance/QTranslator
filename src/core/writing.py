"""写作服务模块 - 实现划词写作功能

移植自 nextai-translator 的写作功能，包括：
- 写作提示词逻辑
- 流式写作翻译
- 文本替换/插入
"""
import sys
import time
import threading
from typing import Optional, Generator, Callable
from dataclasses import dataclass
from pathlib import Path

# 添加父目录到路径以支持相对导入
_parent_dir = Path(__file__).parent.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

try:
    from ..config import get_config
    from ..utils.logger import log_info, log_error, log_debug, log_warning
    from ..utils.language_detector import detect_language, is_chinese_text, get_translation_direction
except ImportError:
    from config import get_config
    from utils.logger import log_info, log_error, log_debug, log_warning
    from utils.language_detector import detect_language, is_chinese_text, get_translation_direction


@dataclass
class WritingResult:
    """写作结果"""
    original_text: str
    translated_text: str
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    error: Optional[str] = None


class WritingService:
    """写作服务类

    提供划词写作功能，支持：
    - 自动检测源语言并确定目标语言
    - 流式翻译输出
    - 可选保留原文
    """

    def __init__(self):
        """初始化写作服务"""
        self._is_writing = False
        self._current_thread: Optional[threading.Thread] = None
        self._stop_flag = False
        self._translator = None

    def _get_translator(self):
        """获取翻译器实例"""
        if self._translator is None:
            try:
                from .translator import get_translator
                self._translator = get_translator()
            except ImportError:
                from translator import get_translator
                self._translator = get_translator()
        return self._translator

    def _build_writing_prompt(self, text: str, source_lang: str, target_lang: str) -> tuple:
        """构建写作提示词

        参考 nextai-translator 的 translate.ts 中的提示词逻辑

        Args:
            text: 待写作的文本
            source_lang: 源语言名称
            target_lang: 目标语言名称

        Returns:
            tuple: (system_prompt, user_prompt)
        """
        # 判断是否翻译成中文
        to_chinese = target_lang in ['中文', 'zh', 'zh-cn', 'zh-hans']

        if to_chinese:
            # 翻译成中文的提示词
            system_prompt = f"""你是一个专业的翻译引擎，请将文本翻译成{target_lang}。
翻译要求：
1. 保持原文的风格和语气
2. 对于专业术语，给出准确的翻译
3. 如果是代码或技术内容，保持专业性和准确性
4. 直接输出翻译结果，不要添加解释或注释
5. 翻译应该自然流畅，符合目标语言的表达习惯"""
            user_prompt = text
        else:
            # 翻译成其他语言（如英文）的提示词
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

    def get_writing_target_language(self, text: str) -> tuple:
        """根据源文本确定写作目标语言

        遵循双向翻译逻辑：
        - 如果源语言是中文，目标语言是英文
        - 如果源语言是非中文，目标语言是中文

        Args:
            text: 源文本

        Returns:
            tuple: (源语言名称, 目标语言名称)
        """
        source_lang, target_lang, source_code = get_translation_direction(text)
        log_info(f"语言检测: 源语言={source_lang}, 目标语言={target_lang}")
        return (source_lang, target_lang)

    def writing_stream(self, text: str,
                       on_chunk: Callable[[str], None] = None) -> Generator[str, None, None]:
        """流式写作翻译

        Args:
            text: 待写作的文本
            on_chunk: 每次收到新内容时的回调函数

        Yields:
            str: 翻译结果的文本片段
        """
        if not text or not text.strip():
            yield ""
            return

        text = text.strip()

        # 确定翻译方向
        source_lang, target_lang = self.get_writing_target_language(text)
        log_info(f"写作: {source_lang} -> {target_lang}")

        # 构建提示词
        system_prompt, user_prompt = self._build_writing_prompt(text, source_lang, target_lang)

        # 获取翻译器并进行流式翻译
        config = get_config()

        # 检查 API 配置
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

        # 使用翻译器进行流式翻译
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=config.get('translator.timeout', 60),
            )

            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=2000,
                temperature=0.3,
                stream=True,
            )

            for chunk in stream:
                if self._stop_flag:
                    break

                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    if on_chunk:
                        on_chunk(content)
                    yield content

        except Exception as e:
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "401" in error_msg:
                error_msg = "API Key 无效或未配置"
            elif "rate_limit" in error_msg.lower() or "429" in error_msg:
                error_msg = "请求过于频繁，请稍后重试"
            elif "connection" in error_msg.lower():
                error_msg = "网络连接失败"
            else:
                error_msg = f"写作失败: {error_msg}"

            yield f"[错误: {error_msg}]"

    def start_writing(self, text: str, has_selection: bool = True, keep_original: bool = False,
                      on_complete: Callable[[WritingResult], None] = None,
                      on_chunk: Callable[[str], None] = None):
        """开始写作（异步，流式输出）

        Args:
            text: 待写作的文本
            has_selection: 是否有选中文本（True=只替换选中，False=替换全部）
            keep_original: 是否保留原文
            on_complete: 完成时的回调函数
            on_chunk: 每次收到新内容时的回调函数
        """
        if self._is_writing:
            log_warning("写作正在进行中")
            return

        self._is_writing = True
        self._stop_flag = False

        def _writing_thread():
            try:
                result_text = ""
                source_lang, target_lang = self.get_writing_target_language(text)

                # 先准备输入位置（删除选中或移动光标）
                first_chunk = True

                for chunk in self.writing_stream(text, on_chunk):
                    if self._stop_flag:
                        break

                    # 收到第一个有效 chunk 时，先准备输入位置
                    if first_chunk and chunk and not chunk.startswith("[错误"):
                        first_chunk = False
                        self._prepare_for_input(has_selection, keep_original)

                    # 流式输入每个字符
                    if chunk and not chunk.startswith("[错误"):
                        self._stream_type_text(chunk)

                    result_text += chunk

                if not self._stop_flag and result_text and not result_text.startswith("[错误"):
                    result = WritingResult(
                        original_text=text,
                        translated_text=result_text,
                        source_language=source_lang,
                        target_language=target_lang
                    )
                else:
                    result = WritingResult(
                        original_text=text,
                        translated_text=result_text,
                        error=result_text if result_text.startswith("[错误") else "已取消"
                    )

                if on_complete:
                    on_complete(result)

            except Exception as e:
                log_error(f"写作线程错误: {e}")
                if on_complete:
                    on_complete(WritingResult(
                        original_text=text,
                        translated_text="",
                        error=str(e)
                    ))
            finally:
                self._is_writing = False

        self._current_thread = threading.Thread(target=_writing_thread, daemon=True)
        self._current_thread.start()

    def _prepare_for_input(self, has_selection: bool, keep_original: bool = False):
        """准备输入位置

        在流式输入之前执行：
        - 保留原文 + 有选中：取消选中（光标在选中末尾），换行插入译文
        - 保留原文 + 无选中：移动到整个文档末尾，换行插入译文
        - 有选中 + 不保留：删除选中内容
        - 无选中 + 不保留：全选后删除

        Args:
            has_selection: 是否有选中文本
            keep_original: 是否保留原文
        """
        try:
            import keyboard

            # 短暂延迟确保键盘操作生效
            time.sleep(0.05)

            if keep_original:
                if has_selection:
                    # 保留原文 + 有选中：取消选中，光标应该在选中内容的末尾
                    # 按 right 取消选中后光标移动到选中内容右边（末尾位置）
                    keyboard.press_and_release('right')
                    time.sleep(0.02)
                    log_info("保留原文模式（选中）：取消选中，光标在选中内容末尾")
                else:
                    # 保留原文 + 无选中（全文模式）：移动到整个文档末尾
                    # 使用 ctrl+end 移动到文档末尾，而不是 end（只移动到当前行末尾）
                    keyboard.press_and_release('ctrl+end')
                    time.sleep(0.02)
                    log_info("保留原文模式（全文）：移动到文档末尾")

                # 换行，准备插入译文
                time.sleep(0.02)
                keyboard.press_and_release('enter')
                time.sleep(0.02)
                keyboard.press_and_release('enter')
                log_info("已插入两个换行，准备写入译文")
                time.sleep(0.05)

            elif has_selection:
                # 有选中文本：删除选中内容
                keyboard.press('delete')
                keyboard.release('delete')
                log_info("已删除选中的文本，准备流式输入")
                time.sleep(0.05)

            else:
                # 没有选中文本：全选后删除
                keyboard.press_and_release('ctrl+a')
                time.sleep(0.02)
                keyboard.press('delete')
                keyboard.release('delete')
                log_info("已删除全部文本，准备流式输入")
                time.sleep(0.05)

        except ImportError as e:
            log_error(f"缺少必要的库: {e}")
            log_error("请安装 keyboard: pip install keyboard")
        except Exception as e:
            log_error(f"准备输入位置失败: {e}")

    def _stream_type_text(self, text: str):
        """流式输入文本（逐字符输入）

        Args:
            text: 要输入的文本
        """
        try:
            import keyboard

            for char in text:
                if self._stop_flag:
                    break

                if char == '\n':
                    # 换行符使用回车键
                    keyboard.press_and_release('enter')
                elif char == '\t':
                    # Tab 键
                    keyboard.press_and_release('tab')
                else:
                    # 普通字符直接输入
                    keyboard.write(char)

                # 每个字符间短暂延迟，实现流式效果
                time.sleep(0.015)

        except ImportError as e:
            log_error(f"缺少必要的库: {e}")
        except Exception as e:
            log_error(f"流式输入失败: {e}")

    def stop_writing(self):
        """停止写作"""
        self._stop_flag = True
        if self._current_thread and self._current_thread.is_alive():
            self._current_thread.join(timeout=2.0)
        self._is_writing = False

    @property
    def is_writing(self) -> bool:
        """是否正在写作"""
        return self._is_writing


# 全局写作服务实例
_writing_service_instance: Optional[WritingService] = None


def get_writing_service() -> WritingService:
    """获取全局写作服务实例"""
    global _writing_service_instance
    if _writing_service_instance is None:
        _writing_service_instance = WritingService()
    return _writing_service_instance