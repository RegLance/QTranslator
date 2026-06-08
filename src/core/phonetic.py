"""本地音标查询模块

使用开源 ipa-dict 词典（MIT 许可，open-dict-data/ipa-dict）在本地离线查询英文单词的
IPA 音标，用于替换大模型生成的、可能不准确的音标。

词典文件为纯文本，每行格式为：

    word<TAB>/ipa1/, /ipa2/, ...

运行时完全离线，不需要联网。
"""
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

try:
    from ..utils.logger import log_debug, log_warning
except ImportError:  # 打包后或直接运行
    from src.utils.logger import log_debug, log_warning


def _is_frozen_env() -> bool:
    """检测是否为 PyInstaller 打包环境"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def _get_base_path() -> Path:
    """获取资源基础路径（兼容开发环境与打包环境）"""
    if _is_frozen_env():
        return Path(sys._MEIPASS)
    # src/core -> src -> project_root
    return Path(__file__).parent.parent.parent


# 支持的口音 -> 词典文件名
_ACCENT_FILES = {
    "us": "en_US.txt",
    "uk": "en_UK.txt",
}


# ---------------------------------------------------------------------------
# Google / Oxford 风格 IPA 归一化
#
# ipa-dict 的英美词典分别采用 Wiktionary / eSpeak 风格，符号偏「窄式」，
# 与谷歌翻译、Oxford、Cambridge 等现代词典展示的「音位式」IPA 有差异。
# 这里做一层归一化，让显示风格接近大众熟悉的词典音标。
# ---------------------------------------------------------------------------

_STRESS = {"ˈ", "ˌ"}
_LENGTH = {"ː", "ˑ"}
# 用于音节/重音判断的元音符号（含 r 色彩元音 ɝ/ɚ、近开 ɐ 等原始符号）
_VOWELS = set("iɪeɛæaəɜɐʌɑɒɔoʊuyøœɤɯɵʉɨɘɞ") | {"ɝ", "ɚ"}
# 这些组合标记/连接符在判断辅音时应跳过
_SKIP = set(" .ˑ̩̃ʲʷˠⁿ̪̬̥͡‿")

# 符号替换：窄式 -> 谷歌/Oxford 风格
_SUBS = [
    ("ɹ", "r"),   # 卷舌 r -> 普通 r
    ("ɡ", "g"),   # 单层 g -> 普通 g
    ("ɫ", "l"),   # 软腭化（暗）l -> 普通 l
    ("ɛ", "e"),   # DRESS 元音 ɛ -> e（谷歌风格）
    ("ɐ", "ə"),   # 近开央元音 -> schwa
    ("ɝ", "ər"),  # 美式重读 r 色彩元音 -> ər
    ("ɚ", "ər"),  # 美式非重读 r 色彩元音 -> ər
    ("ᵻ", "ɪ"),
]

# 合法英语首辅音簇（用于把重音号移到音节首，避免移过音节边界）
# 注：dʒ/tʃ/ts/dz 是单个塞擦音音位，应作为整体计入音节首，不能被重音号拆开
_ONSETS = {
    "dʒ", "tʃ", "ts", "dz",
    "pl", "pr", "pj", "bl", "br", "bj", "tr", "tw", "tj", "dr", "dw", "dj",
    "kl", "kr", "kw", "kj", "gl", "gr", "gw", "gj", "fl", "fr", "fj", "vr",
    "vj", "θr", "θw", "θj", "ʃr", "sl", "sw", "sp", "st", "sk", "sm", "sn",
    "sf", "sj", "hj", "mj", "nj", "lj",
    "spr", "spl", "str", "skr", "skw", "skl", "spj", "stj", "skj",
}


def _is_consonant(ch: str) -> bool:
    return ch not in _VOWELS and ch not in _STRESS and ch not in _LENGTH and ch not in _SKIP


def _count_syllables(ipa: str) -> int:
    """按元音组（含长音符号）数量估算音节数。"""
    count = 0
    in_vowel = False
    for ch in ipa:
        is_v = ch in _VOWELS or ch in _LENGTH
        if is_v and not in_vowel:
            count += 1
        in_vowel = is_v
    return count


def _onset_len(cons: list) -> int:
    """给定紧贴元音前的辅音串（按出现顺序），返回应归入音节首的辅音个数。"""
    n = len(cons)
    if n == 0:
        return 0
    for size in (3, 2):
        if n >= size and "".join(cons[-size:]) in _ONSETS:
            return size
    return 1


def _drop_post_primary_secondary(ipa: str) -> str:
    """删除位于主重音之后的次重音号 ˌ。

    美式（CMU/Wiktionary）来源会给 -ate/-ize 等词尾全元音标次重音
    （如 escalate /ˈeskəˌleɪt/），而谷歌/Oxford 不显示这种主重音之后的次重音。
    主重音之前的次重音是真实的（如 organization /ˌɔːgənaɪˈzeɪʃən/），需保留。
    """
    pi = ipa.find("ˈ")
    if pi == -1:
        return ipa
    return ipa[: pi + 1] + ipa[pi + 1:].replace("ˌ", "")


def _move_stress_to_onset(ipa: str) -> str:
    """把重音号移动到音节首辅音之前（近似最大首辅音簇规则）。"""
    out: list = []
    for ch in ipa:
        if ch in _STRESS:
            # 收集 out 末尾紧邻的辅音串（遇元音/重音/长音停止）
            j = len(out)
            while j > 0 and _is_consonant(out[j - 1]):
                j -= 1
            cons = out[j:]
            keep = _onset_len(cons)
            insert_at = len(out) - keep
            out.insert(insert_at, ch)
        else:
            out.append(ch)
    return "".join(out)


def _normalize_google_style(raw_ipa: str, move_stress: bool = False) -> str:
    """把单个音标（不含斜杠）归一化为谷歌/Oxford 风格。

    Args:
        raw_ipa: 原始音标
        move_stress: 是否把重音号移到音节首。英式（eSpeak 风格）的重音标在元音前，
            需要移动；美式（Wiktionary 风格）重音已在音节首，无需移动。
    """
    s = raw_ipa.strip().strip("/[]").strip()
    if not s:
        return ""

    monosyllabic = _count_syllables(s) <= 1

    for src, dst in _SUBS:
        s = s.replace(src, dst)

    if monosyllabic:
        # 单音节词按词典惯例不标重音
        for mark in _STRESS:
            s = s.replace(mark, "")
    else:
        if move_stress:
            s = _move_stress_to_onset(s)
        # 删除主重音之后的次重音（谷歌/Oxford 风格）
        s = _drop_post_primary_secondary(s)

    return s


class PhoneticDict:
    """本地 IPA 音标词典（按口音惰性加载并缓存）"""

    def __init__(self):
        self._dicts: Dict[str, Dict[str, str]] = {}
        self._lock = threading.Lock()

    def _dict_dir(self) -> Path:
        return _get_base_path() / "assets" / "phonetic"

    def _load_accent(self, accent: str) -> Dict[str, str]:
        """加载某个口音的词典文件，返回 {word: "/ipa/"} 映射。

        只取每行的第一个音标作为主音标。加载失败返回空字典（不抛异常）。
        """
        filename = _ACCENT_FILES.get(accent)
        if not filename:
            return {}

        path = self._dict_dir() / filename
        mapping: Dict[str, str] = {}
        if not path.exists():
            log_warning(f"音标词典文件不存在: {path}")
            return mapping

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line or "\t" not in line:
                        continue
                    word, ipa_field = line.split("\t", 1)
                    # 一行可能有多个音标，用 ", " 分隔，取第一个作为主音标
                    first = ipa_field.split(",", 1)[0].strip()
                    if first:
                        mapping[word.strip().lower()] = first
            log_debug(f"已加载音标词典 {filename}：{len(mapping)} 条")
        except Exception as e:
            log_warning(f"加载音标词典失败 {path}: {e}")
            return {}

        return mapping

    def _get_dict(self, accent: str) -> Dict[str, str]:
        accent = accent.lower()
        if accent not in self._dicts:
            with self._lock:
                if accent not in self._dicts:
                    self._dicts[accent] = self._load_accent(accent)
        return self._dicts[accent]

    @staticmethod
    def _normalize(word: str) -> str:
        """规范化待查单词：去首尾空白/标点、转小写。"""
        return word.strip().strip(".,!?;:\"'()[]{}").lower()

    def lookup(self, word: str, accent: str = "us") -> Optional[str]:
        """查询单词音标（原始 ipa-dict 形式，含斜杠）。

        Args:
            word: 待查单词
            accent: "us" 或 "uk"

        Returns:
            形如 "/ˈwɝd/" 的音标字符串（含斜杠）；未命中返回 None。
        """
        if not word:
            return None
        key = self._normalize(word)
        if not key:
            return None
        return self._get_dict(accent).get(key)

    def _lookup_normalized(self, word: str, accent: str) -> Optional[str]:
        """查询并归一化为谷歌风格的单一音标（不含斜杠），未命中返回 None。"""
        raw = self.lookup(word, accent)
        if not raw:
            return None
        # 一行可能有多个候选音标，取第一个
        first = raw.split(",", 1)[0]
        norm = _normalize_google_style(first, move_stress=(accent.lower() == "uk"))
        return norm or None

    def lookup_dual(self, word: str) -> Optional[str]:
        """查询英式 + 美式音标，返回适合展示的字符串。

        规则：
        - 英美归一化后相同：合并为单个 "/音标/"
        - 不同：返回 "英 /uk/ 美 /us/"
        - 仅命中其一：返回带标签的单个
        - 都未命中：返回 None
        """
        uk = self._lookup_normalized(word, "uk")
        us = self._lookup_normalized(word, "us")

        if uk and us:
            if uk == us:
                return f"/{us}/"
            return f"英 /{uk}/ 美 /{us}/"
        if us:
            return f"美 /{us}/"
        if uk:
            return f"英 /{uk}/"
        return None


# 全局单例
_phonetic_dict: Optional[PhoneticDict] = None
_singleton_lock = threading.Lock()


def get_phonetic_dict() -> PhoneticDict:
    """获取全局音标词典单例"""
    global _phonetic_dict
    if _phonetic_dict is None:
        with _singleton_lock:
            if _phonetic_dict is None:
                _phonetic_dict = PhoneticDict()
    return _phonetic_dict


def lookup_ipa(word: str, accent: str = "us") -> Optional[str]:
    """便捷函数：查询单词的本地 IPA 音标（含斜杠），未命中返回 None。"""
    return get_phonetic_dict().lookup(word, accent)


def lookup_dual_ipa(word: str) -> Optional[str]:
    """便捷函数：查询英美双音标（谷歌风格、相同则合并），未命中返回 None。"""
    return get_phonetic_dict().lookup_dual(word)
