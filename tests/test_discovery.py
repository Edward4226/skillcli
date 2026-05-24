"""Phase 1 单元测试 · discovery / adapters。

测试编码"为什么"（SPEC §12 / Rule 8），不只测"做了什么"。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skill_control_plane.adapters.claude_code import ClaudeCodeAdapter
from skill_control_plane.adapters.codex import CodexAdapter
from skill_control_plane.discovery import discover, parse_frontmatter


class TestParseFrontmatter(unittest.TestCase):
    def test_single_line_description(self):
        text = "---\nname: pdf\ndescription: Use this when you need to read PDF.\n---\n# body\n"
        fm = parse_frontmatter(text)
        self.assertIsNotNone(fm)
        self.assertEqual(fm.name, "pdf")
        self.assertIn("read PDF", fm.description or "")
        self.assertFalse(fm.description_is_block)

    def test_multiline_block_detected(self):
        """SPEC §7.2：多行 block scalar description 是最常见的解析失败原因，
        必须被识别——否则 Phase 2 的质量门 lint 形同虚设。"""
        text = "---\nname: sketchy\ndescription: |\n  Does many things.\n---\n# body\n"
        fm = parse_frontmatter(text)
        self.assertIsNotNone(fm)
        self.assertTrue(fm.description_is_block, "block scalar `|` 必须被标 is_block")

    def test_empty_description_is_block(self):
        """description 为空也应标 is_block，意图：阶段 2 lint 把"空描述"等同
        于"无效描述"处理（同样触发 ~50% 失败率）。"""
        text = "---\nname: foo\ndescription:\n---\n"
        fm = parse_frontmatter(text)
        self.assertIsNotNone(fm)
        self.assertTrue(fm.description_is_block)

    def test_no_frontmatter_returns_none(self):
        self.assertIsNone(parse_frontmatter("# only body, no frontmatter"))


class TestAdaptersOnMissingHome(unittest.TestCase):
    """意图：用户首次跑 scan 时 ~/.claude 或 ~/.codex 可能不存在，不能崩。"""

    def test_claude_missing_home_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            a = ClaudeCodeAdapter(home=Path(td) / "nope")
            self.assertEqual(a.skill_dirs(), [])
            self.assertEqual(a.transcript_files(), [])

    def test_codex_missing_home_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            a = CodexAdapter(home=Path(td) / "nope")
            self.assertEqual(a.skill_dirs(), [])
            self.assertEqual(a.transcript_files(), [])
            # hook 不支持时返回 None（Phase 6 设计依赖此约定）
            self.assertIsNone(a.hook_config_path())


class TestDiscover(unittest.TestCase):
    def test_picks_up_skill_md_and_id_format(self):
        """意图：discovery 必须按 `tool:scope:name` 三段拼 id；
        下游 registry / rules / hooks 全靠这个主键定位，格式变了所有引用都断。"""
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / ".claude"
            skill_dir = fake / "skills" / "demo"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Use when demo.\n---\n# body\n",
                encoding="utf-8",
            )
            recs = discover(ClaudeCodeAdapter(home=fake))
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0].id, "claude:user:demo")
            self.assertEqual(recs[0].scope, "user")
            self.assertEqual(recs[0].frontmatter.name, "demo")

    def test_codex_layout_scopes(self):
        """Codex 三种 scope（user / disabled / vendor）都要被分别打标。"""
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / ".codex"
            for sub, scope_dir in [
                ("skills", "alpha"),
                ("skills.disabled", "beta"),
                ("vendor_imports/skills/skills", "gamma"),
            ]:
                d = fake / sub / scope_dir
                d.mkdir(parents=True)
                (d / "SKILL.md").write_text(
                    f"---\nname: {scope_dir}\ndescription: Use when {scope_dir}.\n---\n",
                    encoding="utf-8",
                )
            recs = discover(CodexAdapter(home=fake))
            by_scope = {r.scope for r in recs}
            self.assertEqual(by_scope, {"user", "disabled", "vendor"})
            # id 前缀全是 codex
            self.assertTrue(all(r.id.startswith("codex:") for r in recs))


if __name__ == "__main__":
    unittest.main()
