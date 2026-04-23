"""版本更新检查模块 - QTranslator"""
import json
import sys
import urllib.request
import urllib.error
from typing import Optional

try:
    from ..config import APP_VERSION
except ImportError:
    from src.config import APP_VERSION


UPDATE_CHECK_URL = "http://109.105.111.17:5005/update"
UPDATE_GITHUB_URL = "https://github.com/SQAG/QTranslator/releases"
TOOL_NAME = "QTranslator"
CHECK_TIMEOUT = 5  # 请求超时时间（秒），避免网络不通时长时间等待


def check_for_update() -> Optional[str]:
    """检查是否有新版本可用

    向更新服务器发送当前版本号，比较返回的版本号。

    Returns:
        如果有新版本，返回新版本号；否则返回 None。
    """
    try:
        print(f"[UpdateChecker] 开始检查更新, 当前版本: {APP_VERSION}, URL: {UPDATE_CHECK_URL}", file=sys.stderr)

        payload = json.dumps({
            "tool": TOOL_NAME,
            "version": APP_VERSION
        }).encode('utf-8')

        req = urllib.request.Request(
            UPDATE_CHECK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        remote_version = data.get("version", "")
        print(f"[UpdateChecker] 远程版本: {remote_version}, 比较结果: {_compare_versions(remote_version, APP_VERSION)}", file=sys.stderr)

        if remote_version and _compare_versions(remote_version, APP_VERSION) > 0:
            print(f"[UpdateChecker] 发现新版本: {remote_version}", file=sys.stderr)
            return remote_version

        print(f"[UpdateChecker] 无新版本", file=sys.stderr)
        return None

    except Exception as e:
        print(f"[UpdateChecker] 检查更新失败: {e}", file=sys.stderr)
        return None


def _compare_versions(v1: str, v2: str) -> int:
    """比较两个语义化版本号

    Args:
        v1: 版本号1 (如 "1.2.3")
        v2: 版本号2 (如 "1.0.0")

    Returns:
        v1 > v2 返回正数，v1 == v2 返回 0，v1 < v2 返回负数
    """
    def parse_ver(v):
        parts = []
        for p in v.strip().split('.'):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return parts

    parts1 = parse_ver(v1)
    parts2 = parse_ver(v2)

    for a, b in zip(parts1, parts2):
        if a != b:
            return a - b

    return len(parts1) - len(parts2)


def get_update_url() -> str:
    """获取更新下载地址（GitHub Releases）"""
    return UPDATE_GITHUB_URL
