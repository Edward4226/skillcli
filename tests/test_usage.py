"""Phase 3 单元测试 · usage 用量闭环。

每条断言对应一个产品承诺：
  - 大小写不敏感的 Skill 匹配（原型踩坑的"小写匹配漏 100%"问题，详 Phase 1 侦察）
  - 多键名 fallback（name / command / skill_name 都要认）
  - 坏行不崩（SPEC §10.3）
  - cwd 集中度挖规则（SPEC §10.2 #3，闭环承诺）
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from skill_control_plane.adapters.claude_code import ClaudeCodeAdapter
from skill_control_plane.usage import (
    RuleSuggestion,
    SkillInvocation,
    aggregate_stats,
    mine_rule_suggestions,
    parse_claude_invocations,
    save_suggestions,
)


def _ts(days_ago: int = 0) -> str:
    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return d.isoformat().replace("+00:00", "Z")


def _mk_jsonl(path: Path, lines: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def _setup_fake_home(td: Path) -> Path:
    home = td / ".claude"
    (home / "projects" / "p1").mkdir(parents=True)
    return home


class TestParseClaude(unittest.TestCase):

    def test_skill_tool_use_extracted_with_cwd(self):
        """tool_use{name='Skill',input:{skill:'pdf'}} 必须被识别为 pdf 调用 + 当时 cwd。
        意图：原型按小写匹配漏 100% 真实数据；锁住大小写不敏感 + cwd 透传。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_fake_home(Path(td))
            _mk_jsonl(home / "projects" / "p1" / "s.jsonl", [
                {"type": "assistant", "timestamp": _ts(1), "cwd": "/home/u/proj",
                 "message": {"role": "assistant", "content": [
                     {"type": "tool_use", "name": "Skill", "input": {"skill": "pdf"}}
                 ]}},
            ])
            invs = list(parse_claude_invocations(ClaudeCodeAdapter(home=home)))
            self.assertEqual(len(invs), 1)
            self.assertEqual(invs[0].skill_name, "pdf")
            self.assertEqual(invs[0].cwd, "/home/u/proj")

    def test_skill_name_with_args_split_to_first_token(self):
        with tempfile.TemporaryDirectory() as td:
            home = _setup_fake_home(Path(td))
            _mk_jsonl(home / "projects" / "p1" / "s.jsonl", [
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"content": [
                     {"type": "tool_use", "name": "Skill", "input": {"skill": "db-migrate apply"}}
                 ]}},
            ])
            invs = list(parse_claude_invocations(ClaudeCodeAdapter(home=home)))
            self.assertEqual(invs[0].skill_name, "db-migrate")

    def test_fallback_input_keys_recognised(self):
        """input 用 'name' / 'command' 都要认——原型已踩坑。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_fake_home(Path(td))
            _mk_jsonl(home / "projects" / "p1" / "s.jsonl", [
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"content": [
                     {"type": "tool_use", "name": "Skill", "input": {"name": "alpha"}}
                 ]}},
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"content": [
                     {"type": "tool_use", "name": "Skill", "input": {"command": "beta"}}
                 ]}},
            ])
            invs = list(parse_claude_invocations(ClaudeCodeAdapter(home=home)))
            self.assertEqual({i.skill_name for i in invs}, {"alpha", "beta"})

    def test_since_filters_old_invocations(self):
        """超出 since_days 必须被丢——用户 --since 30 不期待算 100 天前的。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_fake_home(Path(td))
            _mk_jsonl(home / "projects" / "p1" / "s.jsonl", [
                {"type": "assistant", "timestamp": _ts(100),
                 "message": {"content": [
                     {"type": "tool_use", "name": "Skill", "input": {"skill": "old"}}
                 ]}},
                {"type": "assistant", "timestamp": _ts(5),
                 "message": {"content": [
                     {"type": "tool_use", "name": "Skill", "input": {"skill": "new"}}
                 ]}},
            ])
            invs = list(parse_claude_invocations(ClaudeCodeAdapter(home=home), since_days=30))
            self.assertEqual({i.skill_name for i in invs}, {"new"})

    def test_non_skill_tools_ignored(self):
        """Bash / Read 等非 Skill 调用不进 usage——usage 只算 skill。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_fake_home(Path(td))
            _mk_jsonl(home / "projects" / "p1" / "s.jsonl", [
                {"type": "assistant", "timestamp": _ts(1),
                 "message": {"content": [
                     {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                     {"type": "tool_use", "name": "Read", "input": {"file_path": "/x"}},
                 ]}},
            ])
            self.assertEqual(list(parse_claude_invocations(ClaudeCodeAdapter(home=home))), [])

    def test_bad_line_does_not_crash(self):
        """坏行跳过 + 后续好行照常解 (SPEC §10.3)。"""
        with tempfile.TemporaryDirectory() as td:
            home = _setup_fake_home(Path(td))
            (home / "projects" / "p1" / "s.jsonl").write_text(
                "{this is not json\n" + json.dumps({
                    "type": "assistant", "timestamp": _ts(1),
                    "message": {"content": [
                        {"type": "tool_use", "name": "Skill", "input": {"skill": "ok"}}
                    ]},
                }) + "\n",
                encoding="utf-8",
            )
            invs = list(parse_claude_invocations(ClaudeCodeAdapter(home=home)))
            self.assertEqual(len(invs), 1)
            self.assertEqual(invs[0].skill_name, "ok")


class TestAggregate(unittest.TestCase):

    def test_counts_and_last_used_and_distinct_cwds(self):
        invs = [
            SkillInvocation("pdf", "2026-05-20T00:00:00Z", cwd="/a"),
            SkillInvocation("pdf", "2026-05-23T00:00:00Z", cwd="/b"),
            SkillInvocation("sql", "2026-05-21T00:00:00Z", cwd="/c"),
        ]
        stats = aggregate_stats(invs)
        self.assertEqual(stats["pdf"].invocations, 2)
        self.assertEqual(stats["pdf"].last_used, "2026-05-23T00:00:00Z")
        self.assertEqual(set(stats["pdf"].distinct_cwds), {"/a", "/b"})
        self.assertEqual(stats["sql"].invocations, 1)


class TestRuleMining(unittest.TestCase):

    def test_concentrated_cwd_yields_rule(self):
        """5 次中 4 次同 cwd → 必须挖出 cwd_glob 规则。SPEC §10.2 #3 闭环承诺。"""
        invs = [
            SkillInvocation("db-migrate", _ts(i), cwd="/home/u/proj/db/migrations")
            for i in range(1, 5)
        ] + [SkillInvocation("db-migrate", _ts(5), cwd="/somewhere/else")]
        sugs = mine_rule_suggestions(invs)
        self.assertEqual(len(sugs), 1)
        s = sugs[0]
        self.assertEqual(s.require_skill, "db-migrate")
        self.assertEqual(s.enforcement, "suggest")
        self.assertTrue(any("migrations" in g for g in s.when_cwd_glob))

    def test_scattered_cwd_no_rule(self):
        """5 次 5 个不同 cwd → 不挖（无集中度）。"""
        invs = [SkillInvocation("x", _ts(i), cwd=f"/p{i}") for i in range(5)]
        self.assertEqual(mine_rule_suggestions(invs), [])

    def test_too_few_invocations_no_rule(self):
        """< 3 次不挖——单次偶然不算模式，会污染规则库。"""
        invs = [SkillInvocation("x", _ts(1), cwd="/a"), SkillInvocation("x", _ts(2), cwd="/a")]
        self.assertEqual(mine_rule_suggestions(invs), [])


class TestSaveSuggestions(unittest.TestCase):

    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "s.json"
            sugs = [RuleSuggestion(
                id="auto-x", description="d",
                when_cwd_glob=["**/x/**"], require_skill="x",
                enforcement="suggest", evidence={"n": 1},
            )]
            save_suggestions(sugs, target)
            obj = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(obj["version"], 1)
            self.assertEqual(len(obj["suggestions"]), 1)
            self.assertEqual(obj["suggestions"][0]["require_skill"], "x")


if __name__ == "__main__":
    unittest.main()
