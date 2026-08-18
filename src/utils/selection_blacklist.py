"""划词黑名单：默认项、配置归一化与生效列表提取。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

# 默认黑名单（与早期 selection-service 内置列表一致）
DEFAULT_SELECTION_BLACKLIST: List[Dict[str, Any]] = [
    {"exe": "explorer.exe", "app_name": "Windows 资源管理器", "enabled": True},
    {"exe": "snipaste.exe", "app_name": "Snipaste 截图", "enabled": True},
    {"exe": "pixpin.exe", "app_name": "PixPin 截图", "enabled": True},
    {"exe": "sharex.exe", "app_name": "ShareX 截图", "enabled": True},
    {"exe": "excel.exe", "app_name": "Microsoft Excel", "enabled": False},
    {"exe": "powerpnt.exe", "app_name": "Microsoft PowerPoint", "enabled": False},
    {"exe": "photoshop.exe", "app_name": "Adobe Photoshop", "enabled": True},
    {"exe": "illustrator.exe", "app_name": "Adobe Illustrator", "enabled": True},
    {"exe": "adobe premiere pro.exe", "app_name": "Adobe Premiere Pro", "enabled": True},
    {"exe": "afterfx.exe", "app_name": "Adobe After Effects", "enabled": True},
    {"exe": "adobe audition.exe", "app_name": "Adobe Audition", "enabled": True},
    {"exe": "blender.exe", "app_name": "Blender", "enabled": True},
    {"exe": "3dsmax.exe", "app_name": "3ds Max", "enabled": True},
    {"exe": "maya.exe", "app_name": "Autodesk Maya", "enabled": True},
    {"exe": "acad.exe", "app_name": "AutoCAD", "enabled": True},
    {"exe": "sldworks.exe", "app_name": "SOLIDWORKS", "enabled": True},
    {"exe": "mstsc.exe", "app_name": "远程桌面连接", "enabled": True},
]

_DEFAULT_BY_EXE = {item["exe"]: item for item in DEFAULT_SELECTION_BLACKLIST}


def normalize_exe(name: str) -> str:
    """规范化进程名：小写，无后缀时补 .exe。"""
    s = (name or "").strip().lower()
    if not s:
        return ""
    if not s.endswith(".exe"):
        s += ".exe"
    return s


def _coerce_entry(raw: Any) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    exe = normalize_exe(str(raw.get("exe", "") or ""))
    if not exe:
        return None
    app_name = str(raw.get("app_name", "") or raw.get("name", "") or exe).strip() or exe
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        enabled = bool(enabled)
    return {"exe": exe, "app_name": app_name, "enabled": enabled}


def normalize_blacklist_entries(entries: Any) -> List[Dict[str, Any]]:
    """将配置中的黑名单归一化为条目列表；缺省时返回默认列表副本。"""
    if not entries:
        return deepcopy(DEFAULT_SELECTION_BLACKLIST)

    result: List[Dict[str, Any]] = []
    seen = set()
    if isinstance(entries, list):
        for raw in entries:
            item = _coerce_entry(raw)
            if not item or item["exe"] in seen:
                continue
            seen.add(item["exe"])
            default = _DEFAULT_BY_EXE.get(item["exe"])
            if default and not raw.get("app_name") and not raw.get("name"):
                item["app_name"] = default["app_name"]
            result.append(item)

    return result if result else deepcopy(DEFAULT_SELECTION_BLACKLIST)


def get_active_blacklist_exes(entries: Any) -> List[str]:
    """返回当前启用的黑名单进程名列表（供 selection-hook 使用）。"""
    normalized = normalize_blacklist_entries(entries)
    return [item["exe"] for item in normalized if item.get("enabled", True)]


def entries_for_config(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """序列化写入配置文件。"""
    out: List[Dict[str, Any]] = []
    for item in normalize_blacklist_entries(entries):
        out.append({
            "exe": item["exe"],
            "app_name": item["app_name"],
            "enabled": bool(item.get("enabled", True)),
        })
    return out
