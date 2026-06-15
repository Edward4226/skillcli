"""skillcli CLI 入口。

已实装：scan（发现+注册表）、verify（质量门）、usage（用量/死重/规则建议）、
rules（validate|test，确定性规则引擎）、dashboard（本地只读看板）。
仍为 stub：doctor —— 打印"未实装（见 SPEC §14 阶段 N）"并返回退出码 2。
"""
from __future__ import annotations

import argparse
import sys
from typing import Sequence

EXIT_NOT_IMPLEMENTED = 2


def _not_implemented(name: str, phase: int) -> int:
    print(
        f"skillcli {name}: 未实装（SPEC §14 阶段 {phase}）。\n"
        f"  当前在阶段 0；查看 README.md 的「进度」段了解上线时间。",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


def _cmd_scan(args: argparse.Namespace) -> int:
    from .adapters import ClaudeCodeAdapter, CodexAdapter
    from .discovery import discover_all
    from . import registry as reg

    if not args.no_llm:
        print(
            "⚠️ --llm 暂未实装（Phase 1 不依赖 LLM），降级到 --no-llm 行为。",
            file=sys.stderr,
        )

    adapters = [ClaudeCodeAdapter(), CodexAdapter()]
    records = discover_all(adapters)
    if not records:
        print(
            "未发现任何 skill。检查 ~/.claude/skills/ 与 ~/.codex/skills/ 是否存在。",
            file=sys.stderr,
        )
        return 1

    entries = reg.build(records)
    target = reg.DEFAULT_REGISTRY_PATH
    try:
        reg.save(entries, target)
    except OSError as e:
        print(f"写注册表失败: {e}", file=sys.stderr)
        return 1

    print(f"扫描完成：共 {len(entries)} 个 skill")
    for k, v in reg.stats(entries).items():
        if k == "total":
            continue
        print(f"  {k:20s} {v}")
    print(f"\n已写入 {target}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from collections import Counter
    from datetime import datetime
    from pathlib import Path

    from . import registry as reg
    from .verify import verify_dir

    if args.path and args.all:
        print("--path 与 --all 互斥；二选一。", file=sys.stderr)
        return 2

    if args.path:
        target = Path(args.path)
        if not target.is_dir():
            print(f"不是目录：{target}", file=sys.stderr)
            return 1
        result = verify_dir(target)
        _print_verify_detail(result)
        return 0 if result.badge != "blocked" else 1

    if not args.all:
        print("用法：skillcli verify <path>  或  skillcli verify --all", file=sys.stderr)
        return 2

    entries = reg.load()
    if not entries:
        print("注册表为空。请先跑 `skillcli scan`。", file=sys.stderr)
        return 1
    now = datetime.utcnow().isoformat() + "Z"
    results = []
    for sid, e in entries.items():
        r = verify_dir(Path(e.path), sid=sid)
        results.append(r)
        entries[sid].verify = reg.VerifyState(
            badge=r.badge, score=r.score, last_run=now,
        )
    reg.save(entries)
    _print_verify_summary(results)
    return 0


def _print_verify_detail(r) -> None:
    icons = {"verified": "✅", "needs-review": "⚠️", "blocked": "❌"}
    print(f"{icons.get(r.badge, '?')} {r.id}  ({r.badge}, score={r.score}/100)")
    for c in r.checks:
        flag = "✓" if c.passed else "✗"
        print(f"  {flag} [{c.level}] {c.name}: {c.msg}")


def _print_verify_summary(results) -> None:
    from collections import Counter
    badges = Counter(r.badge for r in results)
    print(f"质量门跑完：{len(results)} 个 skill")
    for badge in ("verified", "needs-review", "blocked"):
        print(f"  {badge:14s} {badges[badge]}")
    blocked = [r for r in results if r.badge == "blocked"]
    if blocked:
        print(f"\n被阻止 ({len(blocked)}) — 头 10 条 + 头 3 个错因：")
        for r in blocked[:10]:
            print(f"  ❌ {r.id}")
            for e in r.errors[:3]:
                print(f"     - {e.msg}")
    needs = [r for r in results if r.badge == "needs-review"]
    if needs:
        print(f"\n待 review ({len(needs)}) — 头 5 条 + 头 2 个 warn：")
        for r in needs[:5]:
            print(f"  ⚠️ {r.id} (score {r.score})")
            for w in r.warns[:2]:
                print(f"     - {w.msg}")


def _cmd_usage(args: argparse.Namespace) -> int:
    from . import registry as reg
    from .adapters import ClaudeCodeAdapter
    from .usage import (
        DEFAULT_SUGGESTIONS_PATH,
        aggregate_stats,
        count_implicit_mentions,
        mine_rule_suggestions,
        parse_claude_invocations,
        save_suggestions,
    )

    claude_a = ClaudeCodeAdapter()
    invocations = list(parse_claude_invocations(claude_a, since_days=args.since))
    stats = aggregate_stats(invocations)
    suggestions = mine_rule_suggestions(invocations)

    entries = reg.load()
    if not entries:
        print("注册表为空。请先跑 `skillcli scan`。", file=sys.stderr)
        return 1

    # 隐式信号（Phase 4）：text-scan Claude skill 名在 assistant text 中出现的会话数。
    # 启发式、假阳性高，dashboard 加 disclaimer。
    claude_names = [e.name for e in entries.values() if e.tool == "claude"]
    implicit = count_implicit_mentions(claude_a, claude_names, since_days=args.since)

    for sid, e in entries.items():
        if e.tool == "claude":
            s = stats.get(e.name)
            imp = implicit.get(e.name, 0)
            if s:
                entries[sid].usage = reg.UsageState(
                    invocations=s.invocations,
                    last_used=s.last_used,
                    never_used=False,
                    source="claude_jsonl",
                    implicit_mentions=imp,
                )
            else:
                entries[sid].usage = reg.UsageState(
                    invocations=0, last_used=None, never_used=(imp == 0),
                    source="claude_jsonl",
                    implicit_mentions=imp,
                )
        elif e.tool == "codex":
            # 诚实降级（Q5/Phase 1 侦察决定）：Codex 无离散 Skill 调用，
            # 隐式信号同样不靠谱（Codex transcript 结构完全不同），先一律 0。
            entries[sid].usage = reg.UsageState(
                invocations=0, last_used=None, never_used=True,
                source="unsupported", implicit_mentions=0,
            )
    reg.save(entries)
    save_suggestions(suggestions)

    # ---- 打印 ----
    print(
        f"扫了过去 {args.since} 天的 Claude transcripts，"
        f"共 {len(invocations)} 次 skill 调用，覆盖 {len(stats)} 个不同 skill。\n"
    )
    if stats:
        print("Top 10 显式 Skill 调用：")
        for s in sorted(stats.values(), key=lambda x: -x.invocations)[:10]:
            print(f"  {s.invocations:5d}  {s.skill_name}")
        print()

    # 隐式信号 top
    nonzero_implicit = sorted(
        [(name, n) for name, n in implicit.items() if n > 0],
        key=lambda kv: -kv[1],
    )
    if nonzero_implicit:
        print(f"Top 10 隐式提及（text-scan 启发式，≥5 字符名）：")
        for name, n in nonzero_implicit[:10]:
            print(f"  {n:5d}  {name}")
        print()

    used_names = set(stats.keys())
    # 死重：显式 + 隐式都 0 才算
    nonempty_implicit = {n for n, c in implicit.items() if c > 0}
    dead_claude = [
        e for e in entries.values()
        if e.tool == "claude"
        and e.name not in used_names
        and e.name not in nonempty_implicit
    ]
    if dead_claude:
        print(f"💀 死重（Claude 侧，{args.since} 天内从未调用）：{len(dead_claude)} 个")
        for e in dead_claude[:10]:
            print(f"   {e.id}")
        if len(dead_claude) > 10:
            print(f"   ... +{len(dead_claude) - 10} more")
        print()

    if suggestions:
        print(f"📋 规则建议：{len(suggestions)} 条 → {DEFAULT_SUGGESTIONS_PATH}")
        for s in suggestions[:5]:
            print(f"  → {s.description}")
            print(f"     when cwd_glob = {s.when_cwd_glob[0]}")
            print(f"     require_skill = {s.require_skill}  (enforcement={s.enforcement})")
        if len(suggestions) > 5:
            print(f"  ... +{len(suggestions) - 5} more")
    else:
        print("📋 暂无规则建议（需 ≥3 次调用 + ≥50% cwd 集中度）。")

    print(
        f"\n[Codex] 用量诚实降级：Codex transcript 无离散 Skill 调用——"
        f"Codex skill usage.source='unsupported'，看板凭此与 Claude 死重区分。"
    )
    return 0


def _cmd_rules(args: argparse.Namespace) -> int:
    from pathlib import Path

    from . import registry as reg
    from .rules import (
        RuleContext,
        RuleParseError,
        evaluate,
        find_rules_file,
        load_rules_path,
        match_rules,
        validate_rules,
    )

    rules_file = Path(args.rules) if args.rules else find_rules_file()
    if rules_file is None:
        print(
            "未找到规则文件。默认查找 ~/.skill-control-plane/rules.json|yaml，"
            "或用 --rules <path> 指定。",
            file=sys.stderr,
        )
        return 2
    if not Path(rules_file).is_file():
        print(f"规则文件不存在：{rules_file}", file=sys.stderr)
        return 2
    try:
        rules = load_rules_path(Path(rules_file))
    except RuleParseError as e:
        print(f"规则文件解析失败：{e}", file=sys.stderr)
        return 1

    if args.action == "validate":
        entries = reg.load()
        if not entries:
            print("注册表为空，无法校验 require.skill。请先跑 `skillcli scan`。",
                  file=sys.stderr)
            return 1
        errors = validate_rules(rules, entries)
        if errors:
            print(f"❌ 校验失败（{len(errors)} 条）：", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print(f"✅ {len(rules)} 条规则全部通过校验（引用 skill 均 verified）。")
        return 0

    # action == "test"：用模拟上下文看命中 + 注入
    ctx = RuleContext(
        files=args.files,
        intent=args.intent,
        task_type=args.task_type,
        git_status=args.git_status,
        dir=args.dir,
    )
    matched = match_rules(rules, ctx)
    if not matched:
        print("无规则命中（hook 此时会静默，不注入）。")
        return 0
    print(f"命中 {len(matched)} 条规则：{', '.join(r.id for r in matched)}\n")
    print("hook 将注入：\n" + evaluate(rules, ctx))
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    from .dashboard.server import serve
    try:
        serve(port=args.port, open_browser=not args.no_browser)
        return 0
    except OSError as e:
        print(f"启动失败：{e}（端口可能被占；试 --port <其它>）", file=sys.stderr)
        return 1


def _cmd_doctor(_args: argparse.Namespace) -> int:
    return _not_implemented("doctor", 4)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skillcli",
        description=(
            "skill-control-plane: 本地 skill 库的控制平面（确定性规则 + 质量门 + 用量闭环）。"
            "  把 ~50% 自动触发率推到接近 100%。"
        ),
        epilog="完整规格见仓库根的 SPEC.md。",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=_version_string(),
    )
    sub = parser.add_subparsers(dest="cmd", metavar="<command>")

    s = sub.add_parser(
        "scan", help="发现本地 skill 并重建注册表（阶段 1）"
    )
    s.add_argument("--no-llm", action="store_true", default=True,
                   help="一句话摘要使用 description 首句（默认开启，离线）")
    s.add_argument("--llm", dest="no_llm", action="store_false",
                   help="改用 LLM 生成更精确的一句话摘要（需要密钥）")
    s.set_defaults(func=_cmd_scan)

    s = sub.add_parser(
        "verify", help="跑质量门：结构 + 触发器 lint + 静态安全扫描（阶段 2）"
    )
    s.add_argument("path", nargs="?", help="skill 目录路径")
    s.add_argument("--all", action="store_true",
                   help="对注册表内全部 skill 跑 verify")
    s.set_defaults(func=_cmd_verify)

    s = sub.add_parser(
        "usage", help="解析 transcript → 用量 / 死重 / 规则建议草案（阶段 3）"
    )
    s.add_argument("--since", type=int, default=30, metavar="N",
                   help="最近 N 天（默认 30）")
    s.set_defaults(func=_cmd_usage)

    s = sub.add_parser("rules", help="规则引擎相关（阶段 6）")
    s.add_argument("action", choices=["validate", "test"],
                   help="validate=校验规则文件；test=用上下文模拟匹配")
    s.add_argument("--rules", metavar="PATH",
                   help="规则文件路径（默认 ~/.skill-control-plane/rules.json|yaml）")
    s.add_argument("--intent", default="", help="[test] 模拟 prompt 文本")
    s.add_argument("--file", action="append", default=[], dest="files",
                   metavar="PATH", help="[test] 模拟变更文件，可多次")
    s.add_argument("--task-type", default=None, help="[test] edit/ask/...")
    s.add_argument("--git-status", action="append", default=[], dest="git_status",
                   metavar="STATE", help="[test] staged/modified，可多次")
    s.add_argument("--dir", default=None, help="[test] 当前目录")
    s.set_defaults(func=_cmd_rules)

    s = sub.add_parser("dashboard", help="启本地只读看板（阶段 4）")
    s.add_argument("--port", type=int, default=7878)
    s.add_argument("--no-browser", action="store_true",
                   help="不自动打开浏览器（CI / 远端用）")
    s.set_defaults(func=_cmd_dashboard)

    s = sub.add_parser("doctor", help="一键体检（阶段 4）")
    s.set_defaults(func=_cmd_doctor)

    return parser


def _version_string() -> str:
    try:
        from . import __version__
        return f"skillcli {__version__}"
    except Exception:  # 防御性：包未正确安装时仍可 --version
        return "skillcli 0.0.1"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
