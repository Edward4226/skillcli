"""Phase 4.5 单元测试 · issues 引擎。"""
from __future__ import annotations

import unittest

from skill_control_plane.issues import (
    SEVERITY_HIGH, SEVERITY_LOW, SEVERITY_MED,
    compute_issues_for_entry,
    flatten_issues,
    group_issues_by_type,
)
from skill_control_plane.registry import RegistryEntry, UsageState, VerifyState


def _e(**kw) -> RegistryEntry:
    defaults = dict(
        id="claude:user:demo", tool="claude", scope="user", name="demo",
        path="/x",
    )
    return RegistryEntry(**{**defaults, **kw})


class TestComputeIssues(unittest.TestCase):
    def test_blocked_yields_high_security(self):
        e = _e(verify=VerifyState(badge="blocked", score=30))
        issues = compute_issues_for_entry(e)
        sec = [i for i in issues if i.type == "security"]
        self.assertEqual(len(sec), 1)
        self.assertEqual(sec[0].severity, SEVERITY_HIGH)

    def test_needs_review_with_non_trigger_yields_med_trigger_with_rewrite(self):
        """needs-review + 非触发式 description → med trigger_style + 给出改写模板。
        意图：Issues tab 必须给出"具体怎么修"，不只"哪里错了"。"""
        e = _e(
            verify=VerifyState(badge="needs-review", score=85),
            description="Does some interesting things to your files.",
            trigger_keywords=["interesting", "files", "operations"],
        )
        issues = compute_issues_for_entry(e)
        triggers = [i for i in issues if i.type == "trigger_style"]
        self.assertTrue(triggers, "non-trigger description 必须挖出 issue")
        # how_to_fix 必须含"模板"或"改写"或"Use this skill when"
        self.assertTrue(
            any(kw in triggers[0].how_to_fix
                for kw in ("模板", "改写", "Use this skill when"))
        )

    def test_block_scalar_description_yields_issue(self):
        e = _e(
            verify=VerifyState(badge="needs-review"),
            description="|",   # block scalar marker
        )
        issues = compute_issues_for_entry(e)
        block_issues = [i for i in issues if "block scalar" in i.why or "block" in i.why]
        self.assertTrue(block_issues)

    def test_duplicate_yields_med(self):
        e = _e(duplicate_of="claude:user:other")
        issues = compute_issues_for_entry(e)
        dups = [i for i in issues if i.type == "duplicate"]
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0].severity, SEVERITY_MED)
        self.assertIn("claude:user:other", dups[0].how_to_fix)

    def test_dead_skill_yields_low(self):
        """30 天无显式+无隐式+老文件 → low dead issue。
        意图：dead 是低优清理项，不是 high；不要打扰用户。"""
        e = _e(
            usage=UsageState(invocations=0, implicit_mentions=0, source="claude_jsonl"),
            freshness_days=60,
        )
        issues = compute_issues_for_entry(e)
        dead = [i for i in issues if i.type == "dead"]
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0].severity, SEVERITY_LOW)

    def test_fresh_dead_skill_not_flagged(self):
        """刚装的 skill（freshness < 30）不应标 dead——给个 grace period。"""
        e = _e(
            usage=UsageState(invocations=0, implicit_mentions=0, source="claude_jsonl"),
            freshness_days=5,
        )
        issues = compute_issues_for_entry(e)
        self.assertEqual([i for i in issues if i.type == "dead"], [])

    def test_stale_skill_yields_low(self):
        e = _e(freshness_days=120)
        issues = compute_issues_for_entry(e)
        stale = [i for i in issues if i.type == "stale"]
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].severity, SEVERITY_LOW)

    def test_codex_skill_does_not_get_dead_issue(self):
        """Codex 用量是 'unsupported'——不能凭"0 调用"标 dead，那叫栽赃。"""
        e = _e(
            tool="codex",
            usage=UsageState(invocations=0, implicit_mentions=0, source="unsupported"),
            freshness_days=60,
        )
        issues = compute_issues_for_entry(e)
        self.assertEqual([i for i in issues if i.type == "dead"], [])

    def test_clean_skill_yields_no_issues(self):
        e = _e(
            verify=VerifyState(badge="verified", score=100),
            usage=UsageState(invocations=5, source="claude_jsonl"),
            freshness_days=10,
        )
        self.assertEqual(compute_issues_for_entry(e), [])


class TestSortAndGroup(unittest.TestCase):
    def test_flatten_sorts_high_first(self):
        per = {
            "a": [
                # mix severities
                compute_issues_for_entry(_e(id="a", freshness_days=120))[0],          # stale low
            ],
            "b": [
                compute_issues_for_entry(_e(id="b", verify=VerifyState(badge="blocked")))[0],  # high
            ],
        }
        flat = flatten_issues(per)
        self.assertEqual(flat[0].severity, SEVERITY_HIGH)

    def test_group_by_type_buckets(self):
        per = {
            "a": [compute_issues_for_entry(_e(id="a", verify=VerifyState(badge="blocked")))[0]],
            "b": [compute_issues_for_entry(_e(id="b", duplicate_of="x"))[0]],
        }
        grouped = group_issues_by_type(per)
        self.assertIn("security", grouped)
        self.assertIn("duplicate", grouped)


if __name__ == "__main__":
    unittest.main()
