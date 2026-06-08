"""规则引擎测试（SPEC §9.3 验收 + §12 测试策略）。

测的是**意图**而非实现细节（Rule 8）：
- 命中 SQL 上下文 → 必须注入强制 Skill(db-migrate)；
- 不相关上下文 → 必须静默（不注入）；
- 引用未验证 skill 的规则 → **必须**校验失败（强制触发未验证 skill 违背产品核心承诺）。
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from skill_control_plane.cli import main
from skill_control_plane.registry import RegistryEntry, VerifyState
from skill_control_plane.rules import (
    Rule,
    RuleContext,
    RuleParseError,
    RuleWhen,
    context_from_claude_prompt,
    evaluate,
    find_rules_file,
    load_rules_path,
    match_rules,
    parse_rules,
    render_injection,
    validate_rules,
)

_SAMPLE_JSON = Path(__file__).resolve().parents[1] / "examples" / "rules.sample.json"


def _sql_rule(mode: str = "enforce") -> Rule:
    return Rule(
        id="sql-migrate",
        require_skill="claude:user:db-migrate",
        description="改 SQL 时强制走迁移 skill",
        when=RuleWhen(file_glob=["**/*.sql"], intent_keywords=["migration", "建表"]),
        mode=mode,
        message="检测到 SQL 变更：必须先用 db-migrate 评估迁移安全。",
    )


def _registry(badge: str = "verified") -> dict[str, RegistryEntry]:
    return {
        "claude:user:db-migrate": RegistryEntry(
            id="claude:user:db-migrate", tool="claude", scope="user",
            name="db-migrate", path="/x", verify=VerifyState(badge=badge),
        )
    }


class TestMatch(unittest.TestCase):
    def test_file_glob_hit_nested(self):
        # SPEC §9.3：给定改 *.sql 的上下文 → 命中（单 file_glob 规则，隔离测 glob）。
        rule = Rule(id="g", require_skill="x", when=RuleWhen(file_glob=["**/*.sql"]))
        ctx = RuleContext(files=["db/migrate/001_init.sql"])
        self.assertEqual([r.id for r in match_rules([rule], ctx)], ["g"])

    def test_file_glob_hit_toplevel(self):
        # ** 应同时覆盖顶层无目录的文件，否则规则会漏命中根目录改动。
        rule = Rule(id="g", require_skill="x", when=RuleWhen(file_glob=["**/*.sql"]))
        self.assertTrue(match_rules([rule], RuleContext(files=["schema.sql"])))

    def test_intent_keyword_hit_cjk(self):
        # 中文 intent 命中——类别内 OR；单 intent 规则隔离测关键词匹配。
        rule = Rule(id="i", require_skill="x", when=RuleWhen(intent_keywords=["建表"]))
        self.assertTrue(match_rules([rule], RuleContext(intent="帮我建表加一个字段")))

    def test_sql_rule_needs_both_file_and_intent(self):
        # _sql_rule 同时约束 file_glob+intent_keywords（镜像 SPEC §9.1 样例）：
        # 二者 AND——只改 .sql 但 intent 无关，不应命中（避免过度强制打扰）。
        only_file = RuleContext(files=["a.sql"], intent="顺手改个注释")
        self.assertEqual(match_rules([_sql_rule()], only_file), [])
        both = RuleContext(files=["a.sql"], intent="加一次 migration")
        self.assertTrue(match_rules([_sql_rule()], both))

    def test_unrelated_context_silent(self):
        # SPEC §9.3：不相关上下文 → 不命中（hook 必须静默）。
        ctx = RuleContext(files=["app/main.py"], intent="重构登录逻辑")
        self.assertEqual(match_rules([_sql_rule()], ctx), [])

    def test_categories_are_anded(self):
        # 同一规则给了 file_glob+task_type，二者 AND：文件命中但 task_type 不符 → 不命中。
        rule = Rule(
            id="r", require_skill="claude:user:db-migrate",
            when=RuleWhen(file_glob=["**/*.sql"], task_type=["edit"]),
        )
        hit = RuleContext(files=["a.sql"], task_type="edit")
        miss = RuleContext(files=["a.sql"], task_type="ask")
        self.assertTrue(match_rules([rule], hit))
        self.assertEqual(match_rules([rule], miss), [])

    def test_absent_category_not_constraining(self):
        # 规则只约束 file_glob；ctx 未给 git_status 不应导致漏判。
        rule = Rule(id="r", require_skill="x", when=RuleWhen(file_glob=["**/*.sql"]))
        self.assertTrue(match_rules([rule], RuleContext(files=["a.sql"])))

    def test_git_status_intersection(self):
        rule = Rule(id="r", require_skill="x", when=RuleWhen(git_status=["staged"]))
        self.assertTrue(match_rules([rule], RuleContext(git_status=["staged", "modified"])))
        self.assertEqual(match_rules([rule], RuleContext(git_status=["modified"])), [])

    def test_dir_prefix(self):
        rule = Rule(id="r", require_skill="x", when=RuleWhen(dir=["infra/"]))
        self.assertTrue(match_rules([rule], RuleContext(files=["infra/deploy.tf"])))
        self.assertEqual(match_rules([rule], RuleContext(files=["src/app.py"])), [])

    def test_dir_matches_absolute_cwd(self):
        # 真实 hook 拿到的是绝对 cwd；dir 规则必须能按路径段命中，否则形同虚设。
        rule = Rule(id="r", require_skill="x", when=RuleWhen(dir=["infra/"]))
        self.assertTrue(match_rules([rule], RuleContext(dir="/Users/x/repo/infra/db")))
        self.assertTrue(match_rules([rule], RuleContext(dir="/Users/x/repo/infra")))
        self.assertEqual(match_rules([rule], RuleContext(dir="/Users/x/repo/src")), [])

    def test_intent_only_rule_fires_without_files(self):
        # UserPromptSubmit 无文件上下文；intent-only 规则必须仅凭 prompt 触发。
        rule = Rule(id="d", require_skill="x",
                    when=RuleWhen(intent_keywords=["删库", "drop table"]))
        self.assertTrue(match_rules([rule], RuleContext(intent="帮我删库跑路")))
        self.assertEqual(match_rules([rule], RuleContext(intent="加个功能")), [])


class TestValidate(unittest.TestCase):
    def test_verified_skill_passes(self):
        self.assertEqual(validate_rules([_sql_rule()], _registry("verified")), [])

    def test_unverified_skill_fails(self):
        # §12 核心反向断言：require.skill 未 verified → **必须**报错。
        # 为什么：强制触发一个没过质量门的 skill，正是产品要消灭的风险。
        errs = validate_rules([_sql_rule()], _registry("needs-review"))
        self.assertTrue(any("db-migrate" in e and "verified" in e for e in errs))

    def test_missing_skill_fails(self):
        errs = validate_rules([_sql_rule()], {})
        self.assertTrue(any("不在注册表" in e for e in errs))

    def test_duplicate_ids_fail(self):
        errs = validate_rules([_sql_rule(), _sql_rule()], _registry())
        self.assertTrue(any("重复" in e for e in errs))

    def test_empty_when_fails(self):
        rule = Rule(id="catch-all", require_skill="claude:user:db-migrate", when=RuleWhen())
        errs = validate_rules([rule], _registry())
        self.assertTrue(any("when 为空" in e for e in errs))


class TestRenderInjection(unittest.TestCase):
    _SQL_CTX = RuleContext(files=["a.sql"], intent="加一次 migration")

    def test_enforce_names_skill_and_is_imperative(self):
        # SPEC §9.3：输出须含强制 Skill(db-migrate) 指令。
        out = render_injection(match_rules([_sql_rule("enforce")], self._SQL_CTX))
        self.assertIn("Skill(db-migrate)", out)
        self.assertIn("必须", out)

    def test_suggest_is_soft(self):
        out = render_injection(match_rules([_sql_rule("suggest")], self._SQL_CTX))
        self.assertIn("Skill(db-migrate)", out)
        self.assertIn("建议", out)

    def test_no_match_is_empty(self):
        self.assertEqual(render_injection([]), "")


class TestParse(unittest.TestCase):
    def _doc(self) -> dict:
        return {
            "version": 1,
            "rules": [{
                "id": "sql-migrate",
                "description": "改 SQL 时强制走迁移",
                "when": {"file_glob": ["**/*.sql"], "intent_keywords": ["建表"]},
                "require": {"skill": "claude:user:db-migrate", "mode": "enforce"},
                "message": "必须先评估迁移安全。",
            }],
        }

    def test_parse_roundtrip(self):
        rules = parse_rules(self._doc())
        self.assertEqual(len(rules), 1)
        r = rules[0]
        self.assertEqual(r.id, "sql-migrate")
        self.assertEqual(r.require_skill, "claude:user:db-migrate")
        self.assertEqual(r.skill_name, "db-migrate")
        self.assertEqual(r.when.file_glob, ["**/*.sql"])

    def test_string_scalar_coerced_to_list(self):
        doc = self._doc()
        doc["rules"][0]["when"]["file_glob"] = "**/*.sql"   # 标量也接受
        self.assertEqual(parse_rules(doc)[0].when.file_glob, ["**/*.sql"])

    def test_missing_require_skill_raises(self):
        doc = self._doc()
        del doc["rules"][0]["require"]["skill"]
        with self.assertRaises(RuleParseError):
            parse_rules(doc)

    def test_bad_version_raises(self):
        with self.assertRaises(RuleParseError):
            parse_rules({"version": 99, "rules": []})

    def test_unknown_when_key_raises(self):
        doc = self._doc()
        doc["rules"][0]["when"]["typo_key"] = ["x"]
        with self.assertRaises(RuleParseError):
            parse_rules(doc)

    def test_bad_mode_raises(self):
        doc = self._doc()
        doc["rules"][0]["require"]["mode"] = "forcefully"
        with self.assertRaises(RuleParseError):
            parse_rules(doc)


class TestLoaders(unittest.TestCase):
    def test_load_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rules.json"
            p.write_text(json.dumps({
                "version": 1,
                "rules": [{"id": "r", "when": {"intent_keywords": ["x"]},
                           "require": {"skill": "claude:user:foo"}}],
            }), encoding="utf-8")
            rules = load_rules_path(p)
            self.assertEqual(rules[0].require_skill, "claude:user:foo")

    def test_sample_json_parses(self):
        # 仓库里的 examples/rules.sample.json 必须始终可解析（防样例腐烂）。
        rules = load_rules_path(_SAMPLE_JSON)
        self.assertEqual(
            {r.id for r in rules},
            {"sql-migrate", "infra-careful", "danger-intent-careful"},
        )

    def test_yaml_path_degrades_honestly(self):
        # 没装 PyYAML 时读 .yaml 必须报清晰错误，而不是 ImportError 裸奔（Rule 11）。
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rules.yaml"
            p.write_text("version: 1\nrules: []\n", encoding="utf-8")
            try:
                import yaml  # noqa: F401
                has_yaml = True
            except ImportError:
                has_yaml = False
            if has_yaml:
                self.assertEqual(load_rules_path(p), [])
            else:
                with self.assertRaises(RuleParseError):
                    load_rules_path(p)

    def test_find_prefers_json(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "rules.json").write_text("{}", encoding="utf-8")
            (Path(d) / "rules.yaml").write_text("", encoding="utf-8")
            self.assertEqual(find_rules_file(Path(d)).name, "rules.json")

    def test_find_none_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(find_rules_file(Path(d)))


class TestHookContext(unittest.TestCase):
    def test_context_from_prompt(self):
        ctx = context_from_claude_prompt({"prompt": "加一次 migration", "cwd": "/repo"})
        self.assertEqual(ctx.intent, "加一次 migration")
        self.assertEqual(ctx.dir, "/repo")

    def test_context_tolerates_missing_fields(self):
        ctx = context_from_claude_prompt({})
        self.assertEqual(ctx.intent, "")
        self.assertIsNone(ctx.dir)

    def test_evaluate_end_to_end(self):
        # sample 规则 + "改 sql 且要 migration" 上下文 → 注入强制 db-migrate。
        rules = load_rules_path(_SAMPLE_JSON)
        ctx = RuleContext(files=["db/001.sql"], intent="加一次 migration")
        self.assertIn("Skill(db-migrate)", evaluate(rules, ctx))


class TestCli(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_rules_test_hits(self):
        code, out, _ = self._run([
            "rules", "test", "--rules", str(_SAMPLE_JSON),
            "--intent", "加一次 migration", "--file", "db/x.sql",
        ])
        self.assertEqual(code, 0)
        self.assertIn("sql-migrate", out)
        self.assertIn("Skill(db-migrate)", out)

    def test_rules_test_no_hit_is_silent(self):
        code, out, _ = self._run([
            "rules", "test", "--rules", str(_SAMPLE_JSON), "--intent", "改个 README",
        ])
        self.assertEqual(code, 0)
        self.assertIn("无规则命中", out)

    def test_rules_missing_file_returns_2(self):
        code, _, err = self._run(["rules", "validate", "--rules", "/no/such/rules.json"])
        self.assertEqual(code, 2)
        self.assertIn("不存在", err)


if __name__ == "__main__":
    unittest.main()
