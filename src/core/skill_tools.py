"""Skill 本地执行工具 - QTranslator

给 AI 对话提供两个内置工具，注册进与 MCP 工具相同的 function calling
循环（见 ChatWorker._run_with_tools），让技能从纯提示词注入升级为真实执行：

- read_skill_file：读取技能目录内的资源文件（模板、参考资料等）
- run_skill_script：执行技能目录内的脚本（需用户弹窗确认）

安全边界：
- 文件/脚本路径被限制在技能自身目录内（resolve 校验，拒绝 .. 逃逸）
- 脚本执行默认每次弹窗确认（窗口层支持勾选「本会话不再询问」）
- 脚本超时 60 秒，输出超长截断
"""
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

try:
    from .skills import get_skill_manager
    from ..utils.logger import log_info, log_error
except ImportError:
    from src.core.skills import get_skill_manager
    from src.utils.logger import log_info, log_error

LOCAL_PREFIX = "local"
SCRIPT_TIMEOUT = 60          # 脚本执行超时（秒）
MAX_OUTPUT = 20000           # 输出截断长度（与 MCP 工具结果一致）
MAX_READ = 200000            # 文件读取截断长度
RUNNABLE_EXTS = {".py", ".bat", ".cmd"}

ConfirmFn = Callable[[str, str], bool]  # (技能名, 描述) -> 是否允许


def _python_exe() -> Optional[str]:
    """运行 .py 脚本的解释器：开发态用当前解释器；打包后退回系统 PATH 的 python"""
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or shutil.which("python3")


def _decode(b: bytes) -> str:
    """子进程输出解码：优先 utf-8，失败退 gbk（Windows cmd 常见）"""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="replace")


class SkillLocalTools:
    """技能本地工具的定义与执行（每次发送对话时创建，绑定当前窗口确认回调）"""

    def __init__(self, confirm: Optional[ConfirmFn] = None,
                 trusted: Optional[Set[str]] = None):
        self._confirm = confirm
        self._trusted = trusted if trusted is not None else set()

    # ---------------- 工具定义（OpenAI function calling schema） ----------------
    def openai_tools(self) -> list:
        names = "\u3001".join(s.name for s in get_skill_manager().load_skills()) or "(无)"
        return [
            {
                "type": "function",
                "function": {
                    "name": f"{LOCAL_PREFIX}__read_skill_file",
                    "description": "读取技能目录内的资源文件（如技能正文提到的模板、参考资料）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill": {"type": "string",
                                      "description": f"技能名称。可用技能：{names}"},
                            "path": {"type": "string",
                                     "description": "技能目录内的相对文件路径，如 template.md"},
                        },
                        "required": ["skill", "path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{LOCAL_PREFIX}__run_skill_script",
                    "description": ("执行技能目录内的脚本（.py/.bat/.cmd）并返回其输出；"
                                    "该操作会弹窗向用户请求确认，调用前请先向用户说明你要做什么"),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill": {"type": "string",
                                      "description": f"技能名称。可用技能：{names}"},
                            "script": {"type": "string",
                                       "description": "技能目录内的相对脚本路径"},
                            "args": {"type": "string",
                                     "description": "传给脚本的命令行参数（可为空）"},
                        },
                        "required": ["skill", "script"],
                    },
                },
            },
        ]

    # ---------------- 执行分发 ----------------
    def call(self, fn_name: str, args: Dict[str, Any]) -> str:
        try:
            if fn_name == f"{LOCAL_PREFIX}__read_skill_file":
                return self._read_file(str(args.get("skill") or ""),
                                       str(args.get("path") or ""))
            if fn_name == f"{LOCAL_PREFIX}__run_skill_script":
                return self._run_script(str(args.get("skill") or ""),
                                        str(args.get("script") or ""),
                                        str(args.get("args") or ""))
            return f"[未知本地工具 {fn_name}]"
        except Exception as e:
            log_error(f"技能本地工具执行异常: {e}")
            return f"[本地工具执行失败: {e}]"

    # ---------------- 内部实现 ----------------
    def _resolve(self, skill_name: str, rel: str):
        """把相对路径解析到技能目录内，返回 (技能根目录, 目标路径, 错误信息)"""
        skill = get_skill_manager().get_skill(skill_name)
        if not skill:
            return None, None, f"[技能不存在: {skill_name}]"
        base = Path(skill.path).parent.resolve()
        target = (base / rel.lstrip("/\\")).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return None, None, f"[非法路径（超出技能目录）: {rel}]"
        return base, target, None

    def _read_file(self, skill_name: str, rel: str) -> str:
        _base, target, err = self._resolve(skill_name, rel)
        if err:
            return err
        if not target.is_file():
            return f"[文件不存在: {rel}]"
        try:
            data = target.read_bytes()[:MAX_READ]
        except Exception as e:
            return f"[读取文件失败: {e}]"
        return _decode(data)

    def _run_script(self, skill_name: str, rel: str, args_str: str) -> str:
        base, target, err = self._resolve(skill_name, rel)
        if err:
            return err
        if not target.is_file():
            return f"[脚本不存在: {rel}]"
        if target.suffix.lower() not in RUNNABLE_EXTS:
            return f"[不支持的脚本类型: {target.suffix}（仅 .py/.bat/.cmd）]"
        # 确认（窗口层已勾选信任的技能直接放行）
        if skill_name not in self._trusted:
            desc = f"技能：{skill_name}\n脚本：{rel}"
            if args_str:
                desc += f"\n参数：{args_str}"
            allowed = self._confirm(skill_name, desc) if self._confirm else False
            if not allowed:
                return "[用户拒绝了脚本执行]"
        try:
            argv_extra = shlex.split(args_str) if args_str else []
        except ValueError:
            argv_extra = args_str.split()
        if target.suffix.lower() == ".py":
            py = _python_exe()
            if not py:
                return "[未找到 python 解释器，无法执行 .py 脚本]"
            cmd = [py, str(target)] + argv_extra
        else:
            cmd = ["cmd", "/c", str(target)] + argv_extra
        kwargs: Dict[str, Any] = dict(cwd=str(base), timeout=SCRIPT_TIMEOUT)
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW：不弹黑窗口
        try:
            r = subprocess.run(cmd, capture_output=True, **kwargs)
        except subprocess.TimeoutExpired:
            return f"[脚本执行超时（{SCRIPT_TIMEOUT}秒）]"
        except Exception as e:
            return f"[脚本执行失败: {e}]"
        out = _decode(r.stdout or b"")
        errout = _decode(r.stderr or b"")
        log_info(f"技能脚本已执行: {skill_name}/{rel} rc={r.returncode}")
        text = out + (f"\n[stderr]\n{errout}" if errout.strip() else "")
        return text[:MAX_OUTPUT] or f"[脚本无输出，退出码 {r.returncode}]"


def get_skill_local_tools(confirm: Optional[ConfirmFn] = None,
                          trusted: Optional[Set[str]] = None) -> SkillLocalTools:
    """每次对话请求创建新实例（confirm 绑定当前窗口的确认通道）"""
    return SkillLocalTools(confirm=confirm, trusted=trusted)
