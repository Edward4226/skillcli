"""适配层抽象。

把 Claude 与 Codex 的差异收敛到一个接口，让上层 discovery / registry / usage
代码与具体工具无关。每个工具一个 Adapter 实现：
  - skill_dirs:    阶段 1 用
  - transcript_files / parse_skill_invocations:  阶段 3 用
  - hook_config_path:  阶段 6 用
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillDir:
    """一个 skill 的源信息：路径 + scope。"""

    path: Path
    scope: str          # "user" | "project" | "vendor" | "disabled"

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class ToolUseRecord:
    """transcript 里一次工具调用（含 skill 调用）。Phase 3 用。"""

    timestamp: str
    tool_name: str
    skill_name: str | None      # 是 skill 调用则填 skill 名；否则 None
    raw_path: Path


class Adapter(ABC):
    """工具适配器基类。"""

    tool: str   # 唯一前缀，如 "claude" / "codex"

    @abstractmethod
    def skill_dirs(self) -> list[SkillDir]:
        """返回此工具下所有顶层 skill 目录，每条已确定 scope。"""

    @abstractmethod
    def transcript_files(self) -> list[Path]:
        """返回此工具的 transcript / 会话 JSONL 文件列表。"""

    @abstractmethod
    def parse_skill_invocations(self, transcript: Path) -> Iterator[ToolUseRecord]:
        """从单个 transcript 抽 skill 调用（含其他 tool 调用）。Phase 3 用。"""

    @abstractmethod
    def hook_config_path(self) -> Path | None:
        """此工具的 hook 配置文件路径；不支持则 None。"""
