"""语言检测模块 - 支持百度 / Google / Bing 联网检测，失败则回退本地 langdetect。"""
import json
import re
import ssl
from typing import Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from langdetect import detect, LangDetectException

try:
    from ..utils.logger import log_debug, log_warning, log_info
except ImportError:
    from src.utils.logger import log_debug, log_warning, log_info

# ---------------------------------------------------------------------------
# 本地检测（与原 QTranslator 行为一致）：中文比例 + langdetect
# ---------------------------------------------------------------------------

CHINESE_CODES = ['zh-cn', 'zh-tw', 'zh-hans', 'zh-hant', 'zh']

LANG_CODE_TO_NAME: Dict[str, str] = {
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
    'hu': '匈牙利文',
    'id': '印尼文',
    'hi': '印地文',
    'mn': '蒙古文',
    'fa': '波斯文',
}

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

_VALID_ENGINES = frozenset({'baidu', 'google', 'bing', 'local'})

# 联网 API → (内部 lang_code, 界面语言名)
_GOOGLE_CODES: Dict[str, Tuple[str, str]] = {
    'zh-CN': ('zh-cn', '中文'),
    'zh-TW': ('zh-tw', '中文'),
    'ja': ('ja', '日文'),
    'en': ('en', '英文'),
    'ko': ('ko', '韩文'),
    'fr': ('fr', '法文'),
    'es': ('es', '西班牙文'),
    'ru': ('ru', '俄文'),
    'de': ('de', '德文'),
    'it': ('it', '意大利文'),
    'tr': ('tr', '土耳其文'),
    'pt': ('pt', '葡萄牙文'),
    'vi': ('vi', '越南文'),
    'id': ('id', '印尼文'),
    'th': ('th', '泰文'),
    'ar': ('ar', '阿拉伯文'),
    'hi': ('hi', '印地文'),
    'mn': ('mn', '蒙古文'),
    'fa': ('fa', '波斯文'),
}

_BAIDU_CODES: Dict[str, Tuple[str, str]] = {
    'zh': ('zh-cn', '中文'),
    'cht': ('zh-tw', '中文'),
    'en': ('en', '英文'),
    'jp': ('ja', '日文'),
    'kor': ('ko', '韩文'),
    'fra': ('fr', '法文'),
    'spa': ('es', '西班牙文'),
    'ru': ('ru', '俄文'),
    'de': ('de', '德文'),
    'it': ('it', '意大利文'),
    'tr': ('tr', '土耳其文'),
    'pt': ('pt', '葡萄牙文'),
    'vie': ('vi', '越南文'),
    'id': ('id', '印尼文'),
    'th': ('th', '泰文'),
    'ar': ('ar', '阿拉伯文'),
    'hi': ('hi', '印地文'),
    'per': ('fa', '波斯文'),
}

# Microsoft Translator Detect 返回的 language 字段
_BING_CODES: Dict[str, Tuple[str, str]] = {
    'zh-hans': ('zh-cn', '中文'),
    'zh-chs': ('zh-cn', '中文'),
    'zh-cn': ('zh-cn', '中文'),
    'zh-hant': ('zh-tw', '中文'),
    'zh-cht': ('zh-tw', '中文'),
    'zh-tw': ('zh-tw', '中文'),
    'ja': ('ja', '日文'),
    'en': ('en', '英文'),
    'ko': ('ko', '韩文'),
    'fr': ('fr', '法文'),
    'es': ('es', '西班牙文'),
    'ru': ('ru', '俄文'),
    'de': ('de', '德文'),
    'it': ('it', '意大利文'),
    'tr': ('tr', '土耳其文'),
    'pt-br': ('pt', '葡萄牙文'),
    'pt-pt': ('pt', '葡萄牙文'),
    'pt': ('pt', '葡萄牙文'),
    'vi': ('vi', '越南文'),
    'id': ('id', '印尼文'),
    'th': ('th', '泰文'),
    'ar': ('ar', '阿拉伯文'),
    'hi': ('hi', '印地文'),
    'nl': ('nl', '荷兰文'),
    'pl': ('pl', '波兰文'),
    'hu': ('hu', '匈牙利文'),
}

_MERGED_BING: Dict[str, Tuple[str, str]] = {
    k.lower(): v for k, v in _BING_CODES.items()
}


def _map_or_fallback(pair: Tuple[str, str]) -> Tuple[str, str]:
    code, name = pair
    nm = LANG_CODE_TO_NAME.get(code, name)
    return (code, nm)


_MISSING_NAME = '英文'


def is_chinese_text(text: str) -> bool:
    """判断文本是否主要是中文"""
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    non_space_chars = re.sub(r'\s', '', text)

    if len(non_space_chars) == 0:
        return False

    ratio = len(chinese_chars) / len(non_space_chars)
    result = ratio > 0.3

    log_debug(
        f"[语言检测] 中文字符数={len(chinese_chars)}, "
        f"总字符数={len(non_space_chars)}, 比例={ratio:.2f}, 判断为中文={result}"
    )

    return result


def _detect_language_local(text: str) -> Tuple[str, str]:
    """原 QTranslator 本地逻辑：中文比例优先，其余 langdetect。"""
    if not text or not text.strip():
        return ('en', '英文')

    text = text.strip()

    if is_chinese_text(text):
        return ('zh', '中文')

    try:
        sample = text[:200] if len(text) > 200 else text
        lang_code = detect(sample)
        lang_name = LANG_CODE_TO_NAME.get(lang_code, _MISSING_NAME)
        log_debug(f"检测到语言(本地): {lang_code} -> {lang_name}")
        return (lang_code, lang_name)

    except LangDetectException as e:
        log_warning(f"语言检测失败(本地 langdetect): {e}，默认使用英文")
        return ('en', '英文')
    except Exception as e:
        log_warning(f"语言检测异常(本地): {e}")
        return ('en', '英文')


def _get_detection_config() -> Tuple[str, float]:
    try:
        from ..config import get_config
    except ImportError:
        from src.config import get_config
    cfg = get_config()
    engine = str(cfg.get('language_detection.engine', 'local') or 'local').strip().lower()
    if engine not in _VALID_ENGINES:
        engine = 'local'
    timeout_raw = cfg.get('language_detection.timeout', 3)
    try:
        timeout = float(timeout_raw)
        timeout = max(3.0, min(60.0, timeout))
    except (TypeError, ValueError):
        timeout = 3.0
    return engine, timeout


def _truncate_cloud(text: str, max_len: int = 1000) -> str:
    s = text.strip()
    return s[:max_len] if len(s) > max_len else s


_EDGE_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0'
)


def _urlopen_req(req: Request, timeout: float) -> bytes:
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def _detect_baidu(text: str, timeout: float) -> Optional[Tuple[str, str]]:
    params = urlencode({'query': text})
    url = 'https://fanyi.baidu.com/langdetect?' + params
    req = Request(
        url,
        method='POST',
        headers={
            'User-Agent': _EDGE_UA,
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': 'https://fanyi.baidu.com/',
        },
        data=b'',
    )
    raw = _urlopen_req(req, timeout)
    jsn = json.loads(raw.decode('utf-8', errors='replace'))
    lan = jsn.get('lan') if isinstance(jsn, dict) else None
    if lan and lan in _BAIDU_CODES:
        return _map_or_fallback(_BAIDU_CODES[lan])
    return None


def _detect_google(text: str, timeout: float) -> Optional[Tuple[str, str]]:
    parts = [('dt', x) for x in ('at', 'bd', 'ex', 'ld', 'md', 'qca', 'rw', 'rm', 'ss', 't')]
    parts += [
        ('client', 'gtx'),
        ('sl', 'auto'),
        ('tl', 'zh-CN'),
        ('hl', 'zh-CN'),
        ('ie', 'UTF-8'),
        ('oe', 'UTF-8'),
        ('otf', '1'),
        ('ssel', '0'),
        ('tsel', '0'),
        ('kc', '7'),
        ('q', text),
    ]
    url = 'https://translate.google.com/translate_a/single?' + urlencode(parts)
    req = Request(url, method='GET', headers={'User-Agent': _EDGE_UA, 'Accept': '*/*'})
    raw = _urlopen_req(req, timeout)
    result = json.loads(raw.decode('utf-8', errors='replace'))
    if not isinstance(result, list) or len(result) < 3:
        return None
    code = result[2]
    if not code or not isinstance(code, str):
        return None
    if code in _GOOGLE_CODES:
        return _map_or_fallback(_GOOGLE_CODES[code])
    return None


def _detect_bing(text: str, timeout: float) -> Optional[Tuple[str, str]]:
    token_url = 'https://edge.microsoft.com/translate/auth'
    token_req = Request(token_url, method='GET', headers={'User-Agent': _EDGE_UA})
    token_bytes = _urlopen_req(token_req, timeout)
    token = token_bytes.decode('utf-8', errors='replace').strip()
    if not token:
        return None

    q = urlencode({'api-version': '3.0'})
    endpoint = f'https://api-edge.cognitive.microsofttranslator.com/detect?{q}'
    body = json.dumps([{'Text': text}], ensure_ascii=False).encode('utf-8')
    req = Request(
        endpoint,
        method='POST',
        data=body,
        headers={
            'accept': '*/*',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'authorization': 'Bearer ' + token,
            'cache-control': 'no-cache',
            'content-type': 'application/json',
            'origin': 'https://www.microsoft.com',
            'pragma': 'no-cache',
            'referer': 'https://www.microsoft.com/',
            'User-Agent': _EDGE_UA,
        },
    )
    raw = _urlopen_req(req, timeout)
    result = json.loads(raw.decode('utf-8', errors='replace'))
    if not isinstance(result, list) or not result:
        return None
    lang = result[0].get('language') if isinstance(result[0], dict) else None
    if not lang or not isinstance(lang, str):
        return None
    key = lang.lower().strip()
    if key in _MERGED_BING:
        return _map_or_fallback(_MERGED_BING[key])
    # 未知 ISO 代码：用代码本身 + 占位名，仍可参与「非中文 → 翻译成中文」
    short = key.split('-')[0]
    name = LANG_CODE_TO_NAME.get(short, LANG_CODE_TO_NAME.get(key, _MISSING_NAME))
    return (short if len(short) <= 8 else short[:8], name)


def _try_online(engine: str, text: str, timeout: float) -> Optional[Tuple[str, str]]:
    """单次联网尝试；任一异常由上层捕获。"""
    if engine == 'baidu':
        return _detect_baidu(text, timeout)
    if engine == 'google':
        return _detect_google(text, timeout)
    if engine == 'bing':
        return _detect_bing(text, timeout)
    return None


def detect_language(text: str) -> Tuple[str, str]:
    """检测文本语言。

    根据配置 ``language_detection.engine``：baidu / google /bing / local。
    联网引擎失败（网络、HTTP、解析异常）时回退本地 ``_detect_language_local``。
    """
    engine, timeout = _get_detection_config()

    if not text or not text.strip():
        return ('en', '英文')

    if engine == 'local':
        return _detect_language_local(text)

    sample = _truncate_cloud(text)
    try:
        got = _try_online(engine, sample, timeout)
        if got is not None:
            log_info(
                f"[语言检测] 联网成功 engine={engine} timeout={timeout:g}s "
                f"-> {got[1]} ({got[0]})"
            )
            return got
        log_warning(f"[语言检测] 联网引擎 {engine} 无有效结果，回退本地")
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, TypeError, KeyError, IndexError, ValueError) as e:
        log_warning(f"[语言检测] 联网引擎 {engine} 失败 ({type(e).__name__}: {e})，回退本地")
    except Exception as e:
        log_warning(f"[语言检测] 联网引擎 {engine} 异常 ({type(e).__name__}: {e})，回退本地")

    local_result = _detect_language_local(text)
    log_info(
        f"[语言检测] 联网失败已回退本地 engine={engine} timeout={timeout:g}s "
        f"-> {local_result[1]} ({local_result[0]})"
    )
    return local_result


def get_target_language_for_text(text: str, default_target: str = '中文') -> str:
    """根据源文本自动确定目标语言"""
    lang_code, lang_name = detect_language(text)

    if lang_code in CHINESE_CODES or lang_name == '中文':
        return '英文'

    return '中文'


def get_translation_direction(text: str) -> Tuple[str, str, str]:
    """获取翻译方向: (源语言名称, 目标语言名称, 源语言代码)"""
    lang_code, lang_name = detect_language(text)

    if lang_code in CHINESE_CODES or lang_name == '中文':
        return ('中文', '英文', lang_code)
    else:
        return (lang_name, '中文', lang_code)


class LanguageDetector:
    """语言检测器类"""

    def detect(self, text: str) -> Tuple[str, str]:
        return detect_language(text)

    def is_chinese(self, text: str) -> bool:
        return is_chinese_text(text)

    def get_target_language(self, text: str) -> str:
        return get_target_language_for_text(text)

    def get_translation_direction(self, text: str) -> Tuple[str, str, str]:
        return get_translation_direction(text)


_detector_instance: Optional[LanguageDetector] = None


def get_language_detector() -> LanguageDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = LanguageDetector()
    return _detector_instance
