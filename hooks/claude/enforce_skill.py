#!/usr/bin/env python3
"""Claude Code `UserPromptSubmit` hook：按 rules.json 命中即注入"必须 Skill(x)"。

接入（README 有完整步骤）：在 ~/.claude/settings.json 的 hooks.UserPromptSubmit
里指向本脚本。Claude 把一段 JSON 从 stdin 传入（含 prompt / cwd），脚本把命中
规则的注入文本打到 stdout——Claude 会在模型看到 prompt 前把它并入上下文。

设计约束（SPEC §9.2）：纯本地、快（<100ms）、零网络、**零第三方依赖**——所以读
rules.json（stdlib），公共匹配逻辑复用 skill_control_plane.rules。

**失败安全**：任何异常都静默退出 0，绝不阻断用户的 prompt——hook 出错不该让宿主卡住。
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        from skill_control_plane.rules import (
            context_from_claude_prompt,
            evaluate,
            find_rules_file,
            load_rules_path,
        )

        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}

        rules_file = find_rules_file()
        if rules_file is None:
            return 0  # 没配规则 → 静默放行

        rules = load_rules_path(rules_file)
        injection = evaluate(rules, context_from_claude_prompt(payload))
        if injection:
            print(injection)
    except Exception as exc:  # 失败安全：绝不阻断宿主
        print(f"[skill-control-plane] hook 跳过（{type(exc).__name__}: {exc}）",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
