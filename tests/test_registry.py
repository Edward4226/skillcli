"""Phase 1 单元测试 · registry。

测试编码"为什么"，每条断言对应一个产品承诺。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skill_control_plane import registry as reg
from skill_control_plane.discovery import SkillFrontmatter, SkillRecord


def _r(name: str, desc: str | None, tool: str = "claude", scope: str = "user") -> SkillRecord:
    return SkillRecord(
        id=f"{tool}:{scope}:{name}",
        tool=tool,
        scope=scope,
        name=name,
        path=Path("/tmp/nonexistent"),       # stat() 会 OSError，build() 内已兜底
        frontmatter=SkillFrontmatter(name=name, description=desc),
        skill_md_size=100,
    )


class TestSummary(unittest.TestCase):
    """--no-llm 默认行为（Q3）：description 首句。"""

    def test_first_sentence_en(self):
        self.assertEqual(
            reg.summarize_no_llm("Use this when X. Other details."),
            "Use this when X.",
        )

    def test_first_sentence_cn(self):
        self.assertEqual(
            reg.summarize_no_llm("使用本 skill 处理 PDF。其他细节。"),
            "使用本 skill 处理 PDF。",
        )

    def test_no_period_returns_whole(self):
        """没有句末标点就把整句还回去（截到上限）。"""
        s = reg.summarize_no_llm("a single fragment with no period")
        self.assertEqual(s, "a single fragment with no period")

    def test_empty_safe(self):
        self.assertEqual(reg.summarize_no_llm(""), "")
        self.assertEqual(reg.summarize_no_llm(None), "")


class TestDuplicates(unittest.TestCase):
    def test_near_identical_pair_marked(self):
        """SPEC §1.1：duplicate skill 是 context rot 的直接来源。
        意图：近乎同义的两个 skill 必须有一条被标 duplicate_of，否则规则引擎
        在用户场景上无法判定该绑哪个，触发率提升落空。"""
        entries = reg.build([
            _r("pdf", "Use this when you need to read or merge PDF files."),
            _r("pdf-tool", "Use this when you need to read or merge PDF files now."),
        ])
        marked = [e for e in entries.values() if e.duplicate_of]
        self.assertEqual(len(marked), 1)

    def test_unrelated_pair_not_marked(self):
        entries = reg.build([
            _r("pdf", "Use this when you need to read PDF."),
            _r("sql", "Use this when you generate database migrations."),
        ])
        marked = [e for e in entries.values() if e.duplicate_of]
        self.assertEqual(marked, [], "完全无关的两条不应被误标重复")


class TestRoundTrip(unittest.TestCase):
    def test_save_load_preserves_fields(self):
        """注册表是后续阶段的唯一事实源；序列化丢字段 = 用量/质量门数据失真。"""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "registry.json"
            entries = reg.build([_r("demo", "Use this when you demo.")])
            reg.save(entries, target)
            loaded = reg.load(target)
            self.assertEqual(loaded.keys(), entries.keys())
            eid = next(iter(entries))
            self.assertEqual(loaded[eid].summary, entries[eid].summary)
            self.assertEqual(loaded[eid].trigger_keywords, entries[eid].trigger_keywords)
            self.assertEqual(loaded[eid].verify.badge, "unverified")

    def test_load_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(reg.load(Path(td) / "nope.json"), {})


class TestStats(unittest.TestCase):
    def test_buckets_by_tool_and_scope(self):
        entries = reg.build([
            _r("a", "Use when X.", tool="claude", scope="user"),
            _r("b", "Use when Y.", tool="claude", scope="user"),
            _r("c", "Use when Z.", tool="codex", scope="disabled"),
        ])
        s = reg.stats(entries)
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["tool/claude"], 2)
        self.assertEqual(s["tool/codex"], 1)
        self.assertEqual(s["scope/user"], 2)
        self.assertEqual(s["scope/disabled"], 1)


if __name__ == "__main__":
    unittest.main()
