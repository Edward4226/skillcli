"""Codex 适配。

数据源（阶段 1 侦察确认，见 DECISIONS.md 2026-05-24 阶段 1）：
  - skill 目录：
      ~/.codex/skills/<name>/SKILL.md             (user scope, active)
      ~/.codex/skills.disabled/<name>/SKILL.md    (disabled scope)
      ~/.codex/vendor_imports/skills/skills/<name>/SKILL.md (vendor scope)
  - transcript：~/.codex/{sessions,archived_sessions}/rollout-<ISO>-<uuid>.jsonl
    每行 = {timestamp, type, payload}；type ∈ {session_meta, event_msg,
                                             response_item, turn_context}
    **Codex 无离散 "Skill" 调用**——skill 通过 SKILL.md 注入 prompt 后由 model
    在 response message 里"使用"。Phase 3 用替代信号统计 skill 用量。
    本 adapter 的 parse_skill_invocations 只抽 function_call / tool_call，
    skill_name 永远 None。
  - hook：暂无（~/.codex/config.toml 仅 [hooks.state] 段且为空，
    codex CLI 无 hook 子命令）。返回 None；Phase 6 重新设计。
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from .base import Adapter, SkillDir, ToolUseRecord


class CodexAdapter(Adapter):
    tool = "codex"

    def __init__(self, home: Path | None = None) -> None:
        self.home = home if home is not None else Path.home() / ".codex"

    def skill_dirs(self) -> list[SkillDir]:
        out: list[SkillDir] = []
        layout = [
            (self.home / "skills", "user"),
            (self.home / "skills.disabled", "disabled"),
            (self.home / "vendor_imports" / "skills" / "skills", "vendor"),
        ]
        for base, scope in layout:
            if not base.is_dir():
                continue
            for entry in sorted(base.iterdir()):
                if entry.is_dir() and (entry / "SKILL.md").is_file():
                    out.append(SkillDir(entry, scope))
        return out

    def transcript_files(self) -> list[Path]:
        out: list[Path] = []
        for sub in ("sessions", "archived_sessions"):
            d = self.home / sub
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.jsonl")):
                out.append(p)
        return out

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
                if obj.get("type") != "response_item":
                    continue
                payload = obj.get("payload") or {}
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") in ("function_call", "tool_call"):
                    name = str(payload.get("name") or "")
                    yield ToolUseRecord(
                        timestamp=str(obj.get("timestamp", "")),
                        tool_name=name,
                        skill_name=None,
                        raw_path=transcript,
                    )

    def hook_config_path(self) -> Path | None:
        # 见模块 docstring；Phase 6 重新设计后填回。
        return None
