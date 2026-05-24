"""扫各 adapter 的 skill 目录、解析 SKILL.md frontmatter，产 SkillRecord 列表。

frontmatter 用标准库正则解析（不引 PyYAML，按 SPEC §4 标准库优先）。
只支持单层 `key: value` 与多行 block scalar 检测——后者是 Phase 2 lint 的重点。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .adapters.base import Adapter

_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)
_LINE_RE = re.compile(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$")
_BLOCK_INDICATORS = {"|", ">", "|-", ">-", "|+", ">+"}


@dataclass
class SkillFrontmatter:
    name: str | None = None
    description: str | None = None
    description_is_block: bool = False     # 多行 block scalar / 空值 → True；Phase 2 拦
    raw: dict[str, str] = field(default_factory=dict)


def parse_frontmatter(text: str) -> SkillFrontmatter | None:
    """返回 SkillFrontmatter；没有 frontmatter 时返回 None。"""
    m = _FRONT_RE.match(text)
    if not m:
        return None
    body = m.group(1)
    fm = SkillFrontmatter()
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        lm = _LINE_RE.match(line)
        if not lm:
            continue
        k, v = lm.group(1), lm.group(2).strip()
        fm.raw[k] = v
        if k == "name":
            fm.name = v or None
        elif k == "description":
            fm.description = v or None
            fm.description_is_block = (v in _BLOCK_INDICATORS) or (v == "")
    return fm


@dataclass
class SkillRecord:
    """discovery 产出的单条记录——registry 的上游。"""

    id: str                          # tool:scope:name
    tool: str
    scope: str
    name: str
    path: Path
    frontmatter: SkillFrontmatter | None
    skill_md_size: int               # SKILL.md 字节数（Phase 2 size lint 用）


def _make_id(tool: str, scope: str, name: str) -> str:
    return f"{tool}:{scope}:{name}"


def discover(adapter: Adapter) -> list[SkillRecord]:
    out: list[SkillRecord] = []
    for sd in adapter.skill_dirs():
        skill_md = sd.path / "SKILL.md"
        try:
            text = skill_md.read_text(encoding="utf-8", errors="ignore")
            size = skill_md.stat().st_size
        except OSError:
            continue
        fm = parse_frontmatter(text)
        # frontmatter name 优先；缺则 fallback 目录名
        name = (fm.name if (fm and fm.name) else sd.name)
        out.append(
            SkillRecord(
                id=_make_id(adapter.tool, sd.scope, name),
                tool=adapter.tool,
                scope=sd.scope,
                name=name,
                path=sd.path,
                frontmatter=fm,
                skill_md_size=size,
            )
        )
    return out


def discover_all(adapters: list[Adapter]) -> list[SkillRecord]:
    out: list[SkillRecord] = []
    for a in adapters:
        out.extend(discover(a))
    return out
