"""Claude Code 适配。

数据源（阶段 1 侦察确认，见 DECISIONS.md 2026-05-24 阶段 1）：
  - skill 目录：~/.claude/skills/<name>/SKILL.md  (user scope)
  - transcript：~/.claude/projects/<proj>/<uuid>.jsonl
    每行 = {message: {content: [{type, ...}]}, ...}
    Skill 调用 = content[].type=="tool_use" AND name=="Skill"
    Skill 名取自 input.skill（或 fallback: name/command/skill_name）
  - hook 配置：~/.claude/settings.json
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from .base import Adapter, SkillDir, ToolUseRecord

# Claude 真实 tool_use.name = "Skill"（大写 S）。原型用了小写——
# 这里写成 case-insensitive 兜底，避免遗漏。
_SKILL_TOOL_NAMES = {"skill"}
_SKILL_INPUT_KEYS = ("skill", "name", "command", "skill_name")


class ClaudeCodeAdapter(Adapter):
    tool = "claude"

    def __init__(self, home: Path | None = None) -> None:
        self.home = home if home is not None else Path.home() / ".claude"

    def skill_dirs(self) -> list[SkillDir]:
        out: list[SkillDir] = []
        user = self.home / "skills"
        if user.is_dir():
            for entry in sorted(user.iterdir()):
                if entry.is_dir() and (entry / "SKILL.md").is_file():
                    out.append(SkillDir(entry, "user"))
        # project scope（项目内 .claude/skills/）阶段 1 暂不全盘扫——
        # 那需要遍历用户所有项目目录，开销大。等用户在某个项目里跑 skillcli scan
        # 时再考虑加 cwd-relative 扫描。
        return out

    def transcript_files(self) -> list[Path]:
        projects = self.home / "projects"
        if not projects.is_dir():
            return []
        return sorted(projects.rglob("*.jsonl"))

    def parse_skill_invocations(self, transcript: Path) -> Iterator[ToolUseRecord]:
        try:
            f = transcript.open(encoding="utf-8", errors="ignore")
        except OSError:
            return
        with f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = str(obj.get("timestamp", ""))
                msg = obj.get("message") or {}
                content = msg.get("content") if isinstance(msg, dict) else None
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") != "tool_use":
                        continue
                    name = str(blk.get("name") or "")
                    skill_name: str | None = None
                    if name.lower() in _SKILL_TOOL_NAMES:
                        inp = blk.get("input") or {}
                        if isinstance(inp, dict):
                            for k in _SKILL_INPUT_KEYS:
                                v = inp.get(k)
                                if v:
                                    skill_name = str(v).split()[0]  # "foo (args)" → "foo"
                                    break
                    yield ToolUseRecord(
                        timestamp=ts,
                        tool_name=name,
                        skill_name=skill_name,
                        raw_path=transcript,
                    )

    def hook_config_path(self) -> Path | None:
        return self.home / "settings.json"
