"""Phase 4.5 单元测试 · tagging 自动主题 tag。"""
from __future__ import annotations

import unittest

from skill_control_plane.registry import RegistryEntry
from skill_control_plane.tagging import (
    _BLACKLIST,
    assign_tags,
    derive_global_tags,
)


def _e(sid: str, kws: list[str]) -> RegistryEntry:
    return RegistryEntry(
        id=sid, tool="claude", scope="user", name=sid.split(":")[-1],
        path="/tmp/x", trigger_keywords=kws,
    )


class TestDeriveGlobalTags(unittest.TestCase):
    def test_threshold_excludes_low_freq(self):
        """≥3 个 skill 共享才入选——避免单 skill 私有词污染全局 tag。"""
        entries = {
            "a": _e("a", ["image", "draw"]),
            "b": _e("b", ["image", "render"]),
            "c": _e("c", ["image"]),
            "d": _e("d", ["draw"]),         # draw 只出现 2 次
            "e": _e("e", ["unique-thing"]),  # 只 1 次
        }
        tags = dict(derive_global_tags(entries))
        self.assertIn("image", tags)
        self.assertNotIn("draw", tags)
        self.assertNotIn("unique-thing", tags)

    def test_blacklist_excluded_even_if_high_freq(self):
        """通用词（use/skill/when 等）即使高频也不当 tag——它们不传递领域语义。"""
        entries = {
            f"s{i}": _e(f"s{i}", ["use", "this", "skill", "image"])
            for i in range(5)
        }
        tags = dict(derive_global_tags(entries))
        self.assertIn("image", tags)
        for bw in ("use", "this", "skill"):
            self.assertNotIn(bw, tags)
            self.assertIn(bw, _BLACKLIST, msg=f"{bw} 应在黑名单")

    def test_top_n_cap(self):
        """top_n 卡上限——用户看不下 50 个 facet。"""
        entries = {}
        for i in range(30):
            kw = f"topic-{i}"
            entries[f"s{i}-a"] = _e(f"s{i}-a", [kw])
            entries[f"s{i}-b"] = _e(f"s{i}-b", [kw])
            entries[f"s{i}-c"] = _e(f"s{i}-c", [kw])
        tags = derive_global_tags(entries, top_n=10)
        self.assertEqual(len(tags), 10)


class TestAssignTags(unittest.TestCase):
    def test_assigns_intersection(self):
        entries = {
            f"s{i}": _e(f"s{i}", ["image", "ai"]) for i in range(5)
        }
        # 一条额外的、没有共同 tag
        entries["s99"] = _e("s99", ["misc"])
        assign_tags(entries)
        for i in range(5):
            self.assertIn("image", entries[f"s{i}"].tags)
            self.assertIn("ai", entries[f"s{i}"].tags)
        self.assertEqual(entries["s99"].tags, [], "no shared tag → empty")

    def test_returns_global_tags_with_counts(self):
        entries = {
            f"s{i}": _e(f"s{i}", ["pdf"]) for i in range(4)
        }
        result = assign_tags(entries)
        self.assertEqual(result, [("pdf", 4)])


if __name__ == "__main__":
    unittest.main()
