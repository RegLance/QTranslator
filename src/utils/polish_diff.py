"""润色结果与原文的差异比对，输出为 HTML（用于译文框高亮显示）。

粒度：比「整句」更细——空白序列、拉丁词（含数字、撇号/连字符）、标点单字；
连续中日韩等非拉丁片段作为短语块（内部不再拆单字）。
"""
from __future__ import annotations

import difflib
import html
import re
import unicodedata as _udata
from typing import List

_LATIN_TOKEN = re.compile(r"[A-Za-z0-9_]+(?:'[A-Za-z]+)?(?:-[A-Za-z0-9_]+)?", re.ASCII)

_BG_DELETED = "#ffdddd"
_BG_ADDED = "#ddffdd"


def _is_punctuation_mark(ch: str) -> bool:
    """标点符号单字自成片段（Unicode P*，不含 Pc 连接符如 '_'）。"""
    if len(ch) != 1:
        return False
    cat = _udata.category(ch)
    if cat == "Pc":
        return False
    return cat.startswith("P")


def split_into_units(text: str) -> List[str]:
    """将文本拆成词/短语级片段。"""
    text = text or ""
    if not text.strip():
        return []

    units: List[str] = []
    pos = 0
    n = len(text)

    while pos < n:
        # 空白
        if text[pos].isspace():
            j = pos + 1
            while j < n and text[j].isspace():
                j += 1
            units.append(text[pos:j])
            pos = j
            continue

        # 英文/数字词
        m = _LATIN_TOKEN.match(text, pos)
        if m:
            units.append(m.group(0))
            pos = m.end()
            continue

        # 标点单字（含全角中英文标点）
        if _is_punctuation_mark(text[pos]):
            units.append(text[pos])
            pos += 1
            continue

        # 非标点连续块（短语等）；遇空白、标点或英文词起始即结束
        j = pos + 1
        while j < n:
            if text[j].isspace():
                break
            if _is_punctuation_mark(text[j]):
                break
            if _LATIN_TOKEN.match(text, j):
                break
            j += 1
        units.append(text[pos:j])
        pos = j

    return [u for u in units if u]


def join_units(parts: List[str]) -> str:
    """将片段按序拼回。"""
    if not parts:
        return ""
    return "".join(parts)


def build_polish_diff_html(
    original: str,
    polished: str,
    *,
    text_color: str,
    font_family_css: str,
    font_size_px: int,
    bg_deleted: str = _BG_DELETED,
    bg_added: str = _BG_ADDED,
) -> str:
    """将原文与润色结果做词/短语级 diff，生成浅红/浅绿背景的 HTML。"""
    a = split_into_units(original)
    b = split_into_units(polished)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)

    ff = html.escape(font_family_css, quote=True)
    style_common = (
        f"color:{html.escape(text_color)};"
        f"font-family:{ff};"
        f"font-size:{int(font_size_px)}px;"
    )
    out: List[str] = [
        f'<div style="{style_common}white-space: pre-wrap; word-wrap: break-word;">'
    ]

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            chunk = join_units(a[i1:i2])
            out.append(html.escape(chunk))
        elif tag == "delete":
            chunk = join_units(a[i1:i2])
            out.append(
                f'<span style="background-color:{html.escape(bg_deleted)};">'
                f"{html.escape(chunk)}</span>"
            )
        elif tag == "insert":
            chunk = join_units(b[j1:j2])
            out.append(
                f'<span style="background-color:{html.escape(bg_added)};">'
                f"{html.escape(chunk)}</span>"
            )
        else:
            old_chunk = join_units(a[i1:i2])
            new_chunk = join_units(b[j1:j2])
            out.append(
                f'<span style="background-color:{html.escape(bg_deleted)};">'
                f"{html.escape(old_chunk)}</span> "
                f'<span style="background-color:{html.escape(bg_added)};">'
                f"{html.escape(new_chunk)}</span>"
            )

    out.append("</div>")
    return "".join(out)
