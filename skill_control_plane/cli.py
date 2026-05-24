"""skillcli CLI 入口。

阶段 1 接通 `scan`；verify / usage / rules / dashboard / doctor 仍是 stub，
打印"未实装（见 SPEC §14 阶段 N）"并返回退出码 2。
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


def _cmd_usage(_args: argparse.Namespace) -> int:
    return _not_implemented("usage", 3)


def _cmd_rules(args: argparse.Namespace) -> int:
    return _not_implemented(f"rules {args.action}", 6)


def _cmd_dashboard(_args: argparse.Namespace) -> int:
    return _not_implemented("dashboard", 4)


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
                   help="validate=校验 rules.yaml；test=用上下文模拟匹配")
    s.set_defaults(func=_cmd_rules)

    s = sub.add_parser("dashboard", help="启本地只读看板（阶段 4）")
    s.add_argument("--port", type=int, default=7878)
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
