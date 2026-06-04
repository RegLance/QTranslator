"""
音标服务模块 - 基于 CMU Pronouncing Dictionary 的离线音标生成
提供美式 (General American) 和英式 (Received Pronunciation) IPA 音标
替换 AI 生成的不准确音标
"""
import re
import sys
from pathlib import Path
from typing import Optional, Dict, Tuple, List

# 日志 (惰性引用，避免循环导入)
_log_info = None

def _get_log_info():
    """惰性获取 log_info 函数"""
    global _log_info
    if _log_info is None:
        try:
            from ..utils.logger import log_info
            _log_info = log_info
        except ImportError:
            from src.utils.logger import log_info
            _log_info = log_info
    return _log_info


# ============================================================================
# ARPAbet → IPA 音素映射
# ============================================================================

# 美式 IPA (General American)
_ARPABET_TO_IPA_US: Dict[str, str] = {
    # 元音
    'AA': 'ɑ',   # odd, father
    'AE': 'æ',   # at, cat
    'AH': 'ʌ',   # hut, but
    'AO': 'ɔ',   # ought, caught
    'AW': 'aʊ',  # cow, how
    'AY': 'aɪ',  # hide, my
    'EH': 'e',   # ed, get (Google 风格: e, 非 ɛ)
    'ER': 'ɜr',  # hurt (Google 风格: ɜr, 非 ɝ)
    'EY': 'eɪ',  # ate, say
    'IH': 'ɪ',   # it, bit
    'IY': 'i',   # eat, see
    'OW': 'oʊ',  # oat, go (美式)
    'OY': 'ɔɪ',  # toy, boy
    'UH': 'ʊ',   # hood, good
    'UW': 'u',   # two, food
    # 辅音
    'B': 'b',    'CH': 'tʃ',  'D': 'd',    'DH': 'ð',
    'F': 'f',    'G': 'g',    'HH': 'h',   'JH': 'dʒ',
    'K': 'k',    'L': 'l',    'M': 'm',    'N': 'n',
    'NG': 'ŋ',   'P': 'p',    'R': 'r',    'S': 's',
    'SH': 'ʃ',   'T': 't',    'TH': 'θ',   'V': 'v',
    'W': 'w',    'Y': 'j',    'Z': 'z',    'ZH': 'ʒ',
}

# 英式 IPA (Received Pronunciation) - 仅列出与美式不同的映射
_ARPABET_TO_IPA_UK: Dict[str, str] = {
    **{k: v for k, v in _ARPABET_TO_IPA_US.items()},
    # 以下覆盖英式特有映射
    'OW': 'əʊ',  # oat, go (英式)
    # ER 在英式中根据轻重音不同而变，在转换函数中动态处理
}

# 元音音素集合 (不含数字后缀)
_VOWEL_SET = {'AA', 'AE', 'AH', 'AO', 'AW', 'AY', 'EH', 'ER', 'EY',
              'IH', 'IY', 'OW', 'OY', 'UH', 'UW'}


# ============================================================================
# 字典加载
# ============================================================================

# 全局缓存
_dict: Optional[Dict[str, List[List[str]]]] = None
_loaded: bool = False


def _get_data_dir() -> Path:
    """获取数据目录路径 (兼容开发环境和 PyInstaller 打包环境)"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent  # src/
    return base / 'data'


def load_dictionary() -> Dict[str, List[List[str]]]:
    """加载 CMU Pronouncing Dictionary 到内存。

    返回:
        dict: {word_lowercase: [[phoneme1, phoneme2, ...], ...]}
        例如: {'hello': [['HH', 'AH0', 'L', 'OW1']]}
    """
    global _dict, _loaded

    if _loaded and _dict is not None:
        return _dict

    _dict = {}
    dict_path = _get_data_dir() / 'cmudict.dict'

    if not dict_path.exists():
        print(f"[phonetic] 警告: 音标字典文件不存在: {dict_path}")
        _loaded = True
        return _dict

    try:
        content = dict_path.read_text(encoding='latin-1')
    except Exception as e:
        print(f"[phonetic] 读取字典文件失败: {e}")
        _loaded = True
        return _dict

    for line in content.split('\n'):
        line = line.strip()
        # 跳过注释行和空行
        if not line or line.startswith(';;;'):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        # 单词 (小写，去掉变体后缀如 "word(2)")
        raw_word = parts[0]
        word = raw_word.split('(')[0].lower()
        phonemes = parts[1:]

        if word not in _dict:
            _dict[word] = []
        _dict[word].append(phonemes)

    _loaded = True
    return _dict


# ============================================================================
# ARPAbet → IPA 转换核心
# ============================================================================

def _split_syllables(phonemes: List[str]) -> List[List[str]]:
    """将 ARPAbet 音素序列按元音位置切分为音节。

    每个元音及其前面到上一元音后的辅音构成一个音节，
    尾随辅音归入最后一个音节。
    例如 ['HH','AH0','L','OW1'] → [['HH','AH0'], ['L','OW1']]
    """
    # 找到所有元音位置
    vowel_positions = [i for i, p in enumerate(phonemes)
                       if re.sub(r'[0-2]$', '', p) in _VOWEL_SET]

    if not vowel_positions:
        return [list(phonemes)]

    syllables: List[List[str]] = []
    prev_end = 0

    for vp in vowel_positions:
        syllables.append(phonemes[prev_end:vp + 1])
        prev_end = vp + 1

    # 尾随辅音归入最后一个音节
    if prev_end < len(phonemes):
        syllables[-1].extend(phonemes[prev_end:])

    return syllables


def _get_stress(phoneme: str) -> int:
    """从 ARPAbet 音素中提取重音等级: 0=非重音, 1=主重音, 2=次重音"""
    m = re.search(r'([0-2])$', phoneme)
    if m:
        return int(m.group(1))
    return 0


def _arpabet_to_ipa(phonemes: List[str], uk: bool = False) -> str:
    """将 ARPAbet 音素序列转换为 IPA 字符串。

    Args:
        phonemes: ARPAbet 音素列表，如 ['HH', 'AH0', 'L', 'OW1']
        uk: True 输出英式 IPA, False 输出美式 IPA

    Returns:
        IPA 字符串，如 "həˈloʊ"
    """
    ipa_map = _ARPABET_TO_IPA_UK if uk else _ARPABET_TO_IPA_US
    syllables = _split_syllables(phonemes)

    result_parts: List[str] = []
    prev_is_r = False  # 用于追踪英式非儿化处理

    for syl_idx, syllable in enumerate(syllables):
        # 查找音节中的元音及其重音
        vowel_idx = -1
        vowel_arpabet = ''
        stress = 0

        for i, p in enumerate(syllable):
            p_clean = re.sub(r'[0-2]$', '', p)
            if p_clean in _VOWEL_SET:
                vowel_idx = i
                vowel_arpabet = p_clean
                stress = _get_stress(p)
                break

        if vowel_idx < 0:
            # 无元音的音节 (理论上不应该发生)
            for p in syllable:
                p_clean = re.sub(r'[0-2]$', '', p)
                ipa = ipa_map.get(p_clean, p_clean.lower())
                result_parts.append(ipa)
            continue

        # 处理重音符号 (放在音节开头)
        if stress == 1:
            result_parts.append('ˈ')
        elif stress == 2:
            result_parts.append('ˌ')

        # 处理元音前的辅音 (onset)
        for i in range(vowel_idx):
            p_clean = re.sub(r'[0-2]$', '', syllable[i])
            if p_clean in ipa_map:
                result_parts.append(ipa_map[p_clean])

        # 检查元音后面是否有 R (用于英式非儿化)
        has_trailing_r = False
        r_index = -1

        for i in range(vowel_idx + 1, len(syllable)):
            p_clean = re.sub(r'[0-2]$', '', syllable[i])
            if p_clean == 'R':
                has_trailing_r = True
                r_index = i
                break

        # 检查下一个音节是否以元音开头 (linking R: ER 在元音前保留 R)
        next_starts_with_vowel = False
        if syl_idx + 1 < len(syllables):
            next_syl = syllables[syl_idx + 1]
            next_starts_with_vowel = (
                len(next_syl) > 0 and
                re.sub(r'[0-2]$', '', next_syl[0]) in _VOWEL_SET
            )

        # 处理元音 (含弱化规则)
        ipa_vowel = ipa_map.get(vowel_arpabet, vowel_arpabet.lower())

        # 非重音元音弱化规则
        if stress == 0:
            if vowel_arpabet == 'AH':
                ipa_vowel = 'ə'  # AH0 → ə
            elif vowel_arpabet == 'IH':
                ipa_vowel = 'ɪ'  # IH0 → ɪ (保持)

        # 美式 ER 处理（Google 风格: 非重音 ər, 重音 ɜr）
        if not uk and vowel_arpabet == 'ER' and stress == 0:
            ipa_vowel = 'ər'

        # 英式特殊处理
        if uk:
            if vowel_arpabet == 'ER':
                if next_starts_with_vowel:
                    # linking R: ER 后接元音，保留 r 音
                    ipa_vowel = 'ɜːr' if stress > 0 else 'ər'
                else:
                    ipa_vowel = 'ɜː' if stress > 0 else 'ə'
            elif has_trailing_r:
                # 英式非儿化: R 不发音，元音变长
                rhotic_map = {
                    'ɑ': 'ɑː', 'ɔ': 'ɔː',
                    'e': 'eə', 'ɪ': 'ɪə', 'ʊ': 'ʊə',
                }
                ipa_vowel = rhotic_map.get(ipa_vowel, ipa_vowel + 'ː')

        result_parts.append(ipa_vowel)

        # 处理元音后的辅音 (coda)
        for i in range(vowel_idx + 1, len(syllable)):
            p_clean = re.sub(r'[0-2]$', '', syllable[i])
            if p_clean == 'R':
                if uk and has_trailing_r and i == r_index:
                    # 英式: 元音后的 R 不发音 (非儿化)
                    continue
                else:
                    result_parts.append(ipa_map.get('R', 'r'))
            elif p_clean in ipa_map:
                result_parts.append(ipa_map[p_clean])

    return ''.join(result_parts)


# ============================================================================
# 公开 API
# ============================================================================

def get_ipa(word: str) -> Optional[Dict[str, str]]:
    """查询单词的美式和英式 IPA 音标。

    Args:
        word: 英语单词，如 "hello"

    Returns:
        {'us': 'həˈloʊ', 'uk': 'həˈləʊ'} 或 None (如果不在字典中)
        当美式和英式相同时，两者值相同
    """
    if not word or not word.strip():
        return None

    dictionary = load_dictionary()
    word_lower = word.strip().lower()

    # 去掉末尾的标点符号 (如 "word." → "word")
    word_clean = re.sub(r'[.,!?:;]+$', '', word_lower)

    # 查找单词
    pronunciations = dictionary.get(word_clean)
    if not pronunciations:
        # 尝试去掉所有格 ('s)
        if word_clean.endswith("'s"):
            pronunciations = dictionary.get(word_clean[:-2])
        # 尝试去掉常见后缀，查找词根
        if not pronunciations:
            for suffix in ['ing', 'ed', 'er', 'est', 'ly', 'ness', 'ment', 'able']:
                if word_clean.endswith(suffix) and len(word_clean) > len(suffix) + 2:
                    root = word_clean[:-len(suffix)]
                    if root in dictionary:
                        pronunciations = dictionary[root]
                        break
                    # 恢复双写辅音
                    if root.endswith(root[-1]):
                        single = root[:-1]
                        if single in dictionary:
                            pronunciations = dictionary[single]
                            break

    if not pronunciations:
        return None

    # 取第一个发音
    phonemes = pronunciations[0]

    # 生成美式和英式 IPA
    ipa_us = _arpabet_to_ipa(phonemes, uk=False)
    ipa_uk = _arpabet_to_ipa(phonemes, uk=True)

    return {'us': ipa_us, 'uk': ipa_uk}


def get_phonetic_display(word: str) -> Optional[str]:
    """获取用于显示的格式化音标字符串。

    规则:
    - 如果美式和英式相同，只显示一个: /həˈloʊ/
    - 如果不相同，分别显示: 美 /həˈloʊ/ 英 /həˈləʊ/

    Args:
        word: 英语单词

    Returns:
        格式化后的音标字符串，如 "/həˈloʊ/" 或 "美 /həˈloʊ/ 英 /həˈləʊ/"
        如果单词不在字典中则返回 None
    """
    result = get_ipa(word)
    if not result:
        return None

    us, uk = result['us'], result['uk']

    if us == uk:
        return f"/{us}/"
    else:
        return f"美 /{us}/ 英 /{uk}/"


def _normalize_ipa(ipa: str) -> str:
    """归一化 IPA 字符串用于比较，消除字体/风格差异。

    将不同转写体系中表示相同发音的符号统一：
    - ɛ / e 都归一化为 e (Google 风格)
    - 去除所有重音符号 (ˈ ˌ)
    - 去除长音符号 (ː)
    - ɝ / ɚ 归一化为 ər
    - ɡ / g 归一化为 g
    """
    return (ipa
        .replace('ɛ', 'e')
        .replace('ɝ', 'ər').replace('ɚ', 'ər')
        .replace('ɡ', 'g')
        .replace('ˈ', '').replace('ˌ', '')
        .replace('ː', '')
        .replace(' ', ''))


def correct_phonetic_in_text(text: str, word: str) -> str:
    """在翻译结果文本中，用字典音标替换 AI 生成的音标。

    匹配模式: [<语言>]· /<音标>/
    例如: "[英语]· /həˈloʊ/" → "[英语]· 美 /həˈloʊ/ 英 /həˈləʊ/"

    Args:
        text: LLM 返回的完整翻译文本
        word: 被翻译的源单词

    Returns:
        替换后的文本。如果单词不在字典中或不匹配格式，返回原文本。
    """
    log_info = _get_log_info()
    phonetic_display = get_phonetic_display(word)

    if not phonetic_display:
        # 单词不在 CMU 字典中，保留 AI 生成的音标
        msg = f"[音标] 单词 '{word}' 不在字典中，保留 AI 音标"
        log_info(msg)
        print(msg)
        return text

    # 匹配音标行: [xxx]· /yyy/ 或 [xxx]· /yyy/ (后缀内容)
    # 去掉 $ 以容忍 LLM 在行尾附加内容（如词性标注）
    # 语言标记可能是中文、英文等，如 [英语]、[English]、[en]
    pattern = r'^(\[[^\]]+\]\s*·)\s*/[^/]+/'

    lines = text.split('\n')
    replaced = False
    old_phonetic_line = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        match = re.match(pattern, stripped)
        if match:
            old_phonetic_line = stripped
            # 提取旧音标 (形如 /xxx/ 的中间部分)
            m_old = re.search(r'/([^/]+)/', stripped)
            old_phonetic_raw = m_old.group(1) if m_old else ''
            # 归一化比较
            new_phonetic_raw = phonetic_display.replace('美 /', '').replace(' 英 /', '').replace('/', '')
            if _normalize_ipa(old_phonetic_raw) == _normalize_ipa(new_phonetic_raw):
                msg = f"[音标] 单词 '{word}' AI 音标已正确，无需替换: {old_phonetic_line}"
                log_info(msg)
                print(msg)
                return text
            # 计算原始行前导空白以保持格式
            leading = line[:len(line) - len(line.lstrip())]
            prefix = match.group(1)
            lines[i] = f"{leading}{prefix} {phonetic_display}"
            replaced = True
            break

    if replaced:
        msg = f"[音标] 单词 '{word}' 音标已替换: {old_phonetic_line} -> {phonetic_display}"
        log_info(msg)
        print(msg)
    else:
        # 输出前几行帮助调试格式问题
        preview = ' | '.join(lines[:4]) if len(lines) > 0 else '(空)'
        msg = f"[音标] 单词 '{word}' 在字典中但未匹配到音标行格式，保留原文。响应前4行: {preview}"
        log_info(msg)
        print(msg)

    return '\n'.join(lines)


# ============================================================================
# 预加载 (模块导入时执行，不阻塞)
# ============================================================================

import threading


def _preload_async():
    """异步预加载字典，避免首次查询时卡顿"""
    try:
        load_dictionary()
    except Exception:
        pass


_preload_thread = threading.Thread(target=_preload_async, daemon=True)
_preload_thread.start()
