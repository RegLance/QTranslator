"""Skills 加载器 - QTranslator

采用开源的 Agent Skills 规范格式（anthropics/skills，SKILL.md + YAML frontmatter）：

    skills/
      my-skill/
        SKILL.md        # 必需，YAML frontmatter + Markdown 正文

SKILL.md 示例：

    ---
    name: code-review
    description: 代码审查专家，对选中代码给出审查意见
    ---
    你是一名资深代码审查专家，请对用户提供的代码 ...

Skills 目录位于 AppData/Local/QTranslator/skills/，用户可自行添加。
被激活的 Skill 其正文会作为系统提示词注入 AI 对话。
"""
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

try:
    from ..config import get_config
    from ..utils.logger import log_info, log_error, log_debug
except ImportError:
    from src.config import get_config
    from src.utils.logger import log_info, log_error, log_debug


@dataclass
class Skill:
    """一个已加载的 Skill"""
    name: str
    description: str
    content: str       # SKILL.md 正文（frontmatter 之后的部分）
    path: str          # SKILL.md 文件路径


_SKILLS_README = """# Skills 目录

把技能放到这个目录，即可在划词工具栏「技能」菜单与 AI 对话窗口中使用。

## 格式（Anthropic Agent Skills 规范）

每个技能一个子目录，目录内包含 `SKILL.md`：

    skills/
      my-skill/
        SKILL.md

`SKILL.md` 必须以 YAML frontmatter 开头：

    ---
    name: 技能名称（工具栏显示用）
    description: 一句话描述这个技能做什么
    ---
    （下面是技能正文，激活技能后会作为系统提示词发给模型）

技能可以引用同目录下的其它资源文件（如模板、脚本）：
在 AI 对话窗口中，模型可以通过内置工具读取这些资源文件，
也可以执行 .py/.bat/.cmd 脚本（每次执行都会弹窗请你确认，
勾选「本会话内此技能不再询问」后免确认）。

修改后无需重启：每次打开工具栏/对话窗口时都会重新扫描本目录。
"""


class SkillManager:
    """Skills 扫描与加载"""

    def __init__(self):
        self._dir: Path = get_config().app_dir / "skills"
        self._ensure_dir()

    @property
    def skills_dir(self) -> Path:
        return self._dir

    def _ensure_dir(self):
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            readme = self._dir / "README.md"
            if not readme.exists():
                readme.write_text(_SKILLS_README, encoding='utf-8')
        except Exception as e:
            log_error(f"创建 skills 目录失败: {e}")

    @staticmethod
    def _parse_skill_file(path: Path) -> Optional[Skill]:
        """解析单个 SKILL.md（frontmatter + 正文）"""
        try:
            text = path.read_text(encoding='utf-8')
        except Exception as e:
            log_error(f"读取 Skill 失败 {path}: {e}")
            return None

        meta = {}
        body = text
        stripped = text.lstrip('\ufeff').strip()
        if stripped.startswith('---'):
            # frontmatter 形如 ---\nkey: value\n---\n正文
            parts = stripped.split('---', 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1]) or {}
                    if not isinstance(meta, dict):
                        meta = {}
                except Exception:
                    meta = {}
                body = parts[2].strip()

        name = str(meta.get('name') or path.parent.name).strip()
        description = str(meta.get('description') or '').strip()
        if not name or not body:
            return None
        return Skill(name=name, description=description, content=body, path=str(path))

    def load_skills(self) -> List[Skill]:
        """扫描 skills 目录，返回所有可用 Skill（每次调用都重新扫描）"""
        skills: List[Skill] = []
        try:
            if not self._dir.exists():
                return skills
            # 标准布局：skills/<name>/SKILL.md
            for skill_md in sorted(self._dir.glob("*/SKILL.md")):
                skill = self._parse_skill_file(skill_md)
                if skill:
                    skills.append(skill)
            # 宽松布局：skills/*.md（README 除外）
            for md in sorted(self._dir.glob("*.md")):
                if md.name.lower() in ('readme.md',):
                    continue
                skill = self._parse_skill_file(md)
                if skill:
                    skills.append(skill)
        except Exception as e:
            log_error(f"扫描 skills 目录失败: {e}")
        log_debug(f"已加载 {len(skills)} 个 skills")
        return skills

    def get_skill(self, name: str) -> Optional[Skill]:
        for s in self.load_skills():
            if s.name == name:
                return s
        return None


# 全局实例
_manager_instance: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = SkillManager()
    return _manager_instance
