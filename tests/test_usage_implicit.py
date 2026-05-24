"""Phase 4 单元测试 · usage.count_implicit_mentions（text-scan 启发式）。

意图（per Rule 8 / SPEC §12）：每条断言对应一个产品承诺，特别是用于
对冲 Phase 3 洞察"显式 Skill 调用稀疏"的关键信号。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from skill_control_plane.adapters.claude_code import ClaudeCodeAdapter
from skill_control_plane.usage import count_implicit_mentions


def _ts(days_ago: int = 0) -> str:
    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return d.isoformat().replace("+00:00", "Z")


def _setup_home(td: Path, lines: list[dict]) -> Path:
    home = td / ".claude"
    proj = home / "projects" / "p1"
    proj.mkdir(parents=True)
    with (proj / "s.jsonl").open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return home


class TestImplicit(unittest.TestCase):
    def test_name_in_assistant_text_counts(self):
        """skill 名出现在 assistant text → +1（per session）。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_home(Path(td), [
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"role": "assistant", "content": [
                     {"type": "text", "text": "I'll use the database-migrate skill for this."}
                 ]}},
            ])
            counts = count_implicit_mentions(ClaudeCodeAdapter(home=home), ["database-migrate"])
            self.assertEqual(counts["database-migrate"], 1)

    def test_short_name_excluded_by_default(self):
        """≤ 4 字符的名不参与（'pdf'/'sql' 这类常见词假阳性极高）。
        意图：text-scan 必须有"最低名长"屏障，否则用户看见的 implicit 数全是噪声。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_home(Path(td), [
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"role": "assistant", "content": [
                     {"type": "text", "text": "We'll use the pdf tool to handle this."}
                 ]}},
            ])
            counts = count_implicit_mentions(ClaudeCodeAdapter(home=home), ["pdf"])
            self.assertEqual(counts["pdf"], 0)

    def test_word_boundary_required(self):
        """\\b 词边界——'using the browser' 不应匹配 'browse'（避免子串误报）。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_home(Path(td), [
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"role": "assistant", "content": [
                     {"type": "text", "text": "I'll use the browser to load the page."}
                 ]}},
            ])
            counts = count_implicit_mentions(ClaudeCodeAdapter(home=home), ["browse"])
            # 'browse' 是 6 字符（过 min_name_len 阈），但 'browser' 不应匹配 'browse'
            self.assertEqual(counts["browse"], 0)

    def test_standalone_word_does_match(self):
        """'browse' 作为独立词应被匹配。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_home(Path(td), [
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"role": "assistant", "content": [
                     {"type": "text", "text": "Let me browse this site briefly."}
                 ]}},
            ])
            counts = count_implicit_mentions(ClaudeCodeAdapter(home=home), ["browse"])
            self.assertEqual(counts["browse"], 1)

    def test_multiple_mentions_same_session_count_once(self):
        """同 session 多次提及 → 只 +1（避免单 session 灌水）。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_home(Path(td), [
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"role": "assistant", "content": [
                     {"type": "text", "text": "running deepdive. deepdive deepdive."}
                 ]}},
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"role": "assistant", "content": [
                     {"type": "text", "text": "more deepdive output here"}
                 ]}},
            ])
            counts = count_implicit_mentions(ClaudeCodeAdapter(home=home), ["deepdive"])
            self.assertEqual(counts["deepdive"], 1)

    def test_user_messages_excluded(self):
        """user prompt 里提到的 skill 名不算 implicit usage——
        意图：用户问"是否要用 X skill"不代表 X 被用了。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_home(Path(td), [
                {"type": "user", "timestamp": _ts(1),
                 "message": {"role": "user", "content": [
                     {"type": "text", "text": "Should I use the deepdive skill?"}
                 ]}},
            ])
            counts = count_implicit_mentions(ClaudeCodeAdapter(home=home), ["deepdive"])
            self.assertEqual(counts["deepdive"], 0)

    def test_since_filters_old(self):
        with tempfile.TemporaryDirectory() as td:
            home = _setup_home(Path(td), [
                {"type": "assistant", "timestamp": _ts(100),
                 "message": {"role": "assistant", "content": [
                     {"type": "text", "text": "long ago I used deepdive here"}
                 ]}},
            ])
            counts = count_implicit_mentions(
                ClaudeCodeAdapter(home=home), ["deepdive"], since_days=30,
            )
            self.assertEqual(counts["deepdive"], 0)

    def test_empty_input_safe(self):
        with tempfile.TemporaryDirectory() as td:
            home = _setup_home(Path(td), [])
            # 空 skill 列表 → 空结果
            self.assertEqual(count_implicit_mentions(ClaudeCodeAdapter(home=home), []), {})


if __name__ == "__main__":
    unittest.main()
