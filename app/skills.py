"""Live loader for OneRad's application runtime skills.

Each call reads UTF-8 Markdown from disk.  Deliberately avoiding a cache makes
prompt edits effective for the next model invocation without restarting the
server.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillLoadError(RuntimeError):
    """Raised when an application skill cannot be loaded safely."""


def skill_path(name: str) -> Path:
    """Return the canonical SKILL.md path for a validated skill name."""

    if not _SKILL_NAME_PATTERN.fullmatch(name):
        raise SkillLoadError(f"非法 skill 名称: {name!r}")
    return SKILLS_DIR / name / "SKILL.md"


def _markdown_body(markdown: str) -> str:
    """Strip optional YAML frontmatter while preserving the Markdown body."""

    normalized = markdown.lstrip("\ufeff")
    if not normalized.startswith("---"):
        return normalized.strip()
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        return normalized.strip()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).strip()
    return normalized.strip()


def load_skill(name: str) -> str:
    """Read one skill from disk and return its non-empty Markdown body."""

    path = skill_path(name)
    try:
        markdown = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SkillLoadError(f"缺少运行时 skill 文件: {path}") from exc
    except UnicodeDecodeError as exc:
        raise SkillLoadError(f"运行时 skill 不是有效 UTF-8: {path}") from exc
    except OSError as exc:
        raise SkillLoadError(f"无法读取运行时 skill: {path} ({exc})") from exc

    body = _markdown_body(markdown)
    if not body:
        raise SkillLoadError(f"运行时 skill 内容为空: {path}")
    return body


def load_skill_bundle(names: Iterable[str]) -> str:
    """Load multiple skills in order and combine them into one system prompt."""

    sections = []
    for name in names:
        sections.append(f"<!-- OneRad skill: {name} -->\n{load_skill(name)}")
    return "\n\n---\n\n".join(sections)
