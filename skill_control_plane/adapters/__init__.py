"""跨工具适配层：把 Claude 与 Codex 在 skill 目录 / transcript / hook 上的差异统一。"""
from .base import Adapter, SkillDir, ToolUseRecord
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter

__all__ = [
    "Adapter",
    "SkillDir",
    "ToolUseRecord",
    "ClaudeCodeAdapter",
    "CodexAdapter",
]
