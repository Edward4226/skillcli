"""skillcli CLI 入口（阶段 0 stub）。

阶段 0 只保证 `skillcli --help` 可读、所有子命令注册到位；每个子命令打印
"未实装（见 SPEC §14 阶段 N）"并返回退出码 2，避免下游脚本误以为成功。
真实实现按阶段 1–6 逐步上线。

CLI 名为何不是规格 §4/§11 里的 `scp`：与系统 OpenSSH `scp`（secure copy）撞名，
脚手架自检立刻击中，DECISIONS 2026-05-24 记一笔已改用 `skillcli`（用户拍板）。
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


def _cmd_scan(_args: argparse.Namespace) -> int:
    return _not_implemented("scan", 1)


def _cmd_verify(_args: argparse.Namespace) -> int:
    return _not_implemented("verify", 2)


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
