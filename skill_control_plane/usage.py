"""用量闭环（SPEC §10）。

输入：本地 Claude transcript JSONL（与 Codex transcript——见诚实降级说明）。
产出：
  - 每个 skill 的调用次数 / 最近时间 / 出现过的 cwd 列表
  - 死重清单（从未触发过的 skill）
  - 规则草案：从"反复手动调用 + cwd 集中"模式挖出的 RuleSuggestion，写
    ~/.skill-control-plane/suggestions.json，待用户在看板（Phase 4）一键确认。

**Codex 侧诚实降级**：Codex transcript 无离散 Skill tool 调用（Phase 1 侦察
确认；DECISIONS 2026-05-24 阶段 1）。这里 Codex 不参与统计；entries[id].usage.source
标为 "unsupported"，与 Claude 的 "claude_jsonl" 与未跑过的 "unknown" 区分。
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .adapters.claude_code import ClaudeCodeAdapter

DEFAULT_SUGGESTIONS_PATH = Path.home() / ".skill-control-plane" / "suggestions.json"


# ---------- 数据结构 ----------


@dataclass
class SkillInvocation:
    """一次 skill 调用的上下文（用于规则挖掘）。"""

    skill_name: str
    timestamp: str
    cwd: str | None = None
    user_prompt: str | None = None       # 该 tool_use 之前最近的一条 user message 文本（截断）


@dataclass
class UsageStats:
    skill_name: str
    invocations: int
    last_used: str | None
    distinct_cwds: list[str] = field(default_factory=list)


@dataclass
class RuleSuggestion:
    """从用量挖出的规则草案——格式对齐 SPEC §9.1 的 rules.yaml 条目。"""

    id: str
    description: str
    when_cwd_glob: list[str]
    require_skill: str
    enforcement: str            # suggest（保守默认）/ mandatory
    evidence: dict              # 解释为什么挖出（让用户验证）


# ---------- Claude JSONL 解析 ----------


_SKILL_TOOL_NAMES = {"skill"}
_SKILL_INPUT_KEYS = ("skill", "name", "command", "skill_name")
_USER_PROMPT_MAX = 500


def _extract_text(content) -> str | None:
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for blk in content:
        if isinstance(blk, dict) and blk.get("type") == "text":
            t = blk.get("text")
            if isinstance(t, str):
                parts.append(t)
    return " ".join(parts) if parts else None


def parse_claude_invocations(
    adapter: ClaudeCodeAdapter | None = None,
    *,
    since_days: int = 30,
) -> Iterator[SkillInvocation]:
    """流式解析 Claude transcript，yield SkillInvocation。

    上下文捕获策略：流式扫描，记 last_cwd / last_user_prompt；遇到 skill tool_use
    时把当时的上下文 attach 上。**不要求每行都有 cwd**——大量 line 不带 cwd 字段，
    但顶层 obj.get("cwd") 会被认为是"本会话的 cwd"，向后传播。
    """
    a = adapter or ClaudeCodeAdapter()
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    for path in a.transcript_files():
        try:
            f = path.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with f:
            last_cwd: str | None = None
            last_user_prompt: str | None = None
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # 维护 cwd 状态
                cwd_val = obj.get("cwd")
                if isinstance(cwd_val, str) and cwd_val:
                    last_cwd = cwd_val

                msg = obj.get("message") or {}
                content = msg.get("content") if isinstance(msg, dict) else None

                # 维护 last_user_prompt
                if obj.get("type") == "user":
                    text = _extract_text(content)
                    if text:
                        last_user_prompt = text[:_USER_PROMPT_MAX]

                # 扫描该行的 tool_use 块
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") != "tool_use":
                        continue
                    name = str(blk.get("name") or "")
                    if name.lower() not in _SKILL_TOOL_NAMES:
                        continue
                    inp = blk.get("input") or {}
                    skill: str | None = None
                    if isinstance(inp, dict):
                        for k in _SKILL_INPUT_KEYS:
                            v = inp.get(k)
                            if v:
                                skill = str(v).split()[0]
                                break
                    if not skill:
                        continue

                    ts = str(obj.get("timestamp", ""))
                    # since 过滤
                    if ts and _parse_iso(ts) is not None and _parse_iso(ts) < cutoff:
                        continue

                    yield SkillInvocation(
                        skill_name=skill,
                        timestamp=ts,
                        cwd=last_cwd,
                        user_prompt=last_user_prompt,
                    )


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ---------- 隐式使用信号（text-scan，Phase 4）----------

import re as _re


def count_implicit_mentions(
    adapter: ClaudeCodeAdapter | None = None,
    skill_names: list[str] | None = None,
    *,
    since_days: int = 30,
    min_name_len: int = 5,
) -> dict[str, int]:
    """统计"skill 名出现在 assistant text 内容里"的会话数（不是字数）。

    **启发式 + 假阳性高**：短名（"pdf" / "browse"）易被普通文本命中。
    缓解：① 只统计 len ≥ min_name_len 的名；② 词边界匹配；③ 每会话 +1 而非每次出现。
    用途：作为"显式 Skill tool_use"的补充——Phase 3 真机发现显式调用极稀疏。
    Dashboard 必须显示 disclaimer。
    """
    if skill_names is None:
        return {}
    a = adapter or ClaudeCodeAdapter()
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    patterns = {
        name: _re.compile(rf"\b{_re.escape(name)}\b", _re.IGNORECASE)
        for name in skill_names
        if len(name) >= min_name_len
    }
    counts: dict[str, int] = {name: 0 for name in skill_names}
    if not patterns:
        return counts

    for path in a.transcript_files():
        # 每个 transcript 一个会话；按 session 算 hit
        session_hit: set[str] = set()
        try:
            f = path.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = obj.get("timestamp", "")
                if ts:
                    d = _parse_iso(ts)
                    if d is not None and d < cutoff:
                        continue
                msg = obj.get("message") or {}
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict) or blk.get("type") != "text":
                        continue
                    text = blk.get("text") or ""
                    if not isinstance(text, str):
                        continue
                    for name, pat in patterns.items():
                        if name in session_hit:
                            continue
                        if pat.search(text):
                            session_hit.add(name)
        for name in session_hit:
            counts[name] += 1
    return counts


# ---------- 聚合 ----------


def aggregate_stats(invocations: list[SkillInvocation]) -> dict[str, UsageStats]:
    by_skill: dict[str, list[SkillInvocation]] = defaultdict(list)
    for inv in invocations:
        by_skill[inv.skill_name].append(inv)
    out: dict[str, UsageStats] = {}
    for skill, invs in by_skill.items():
        invs.sort(key=lambda i: i.timestamp)
        out[skill] = UsageStats(
            skill_name=skill,
            invocations=len(invs),
            last_used=invs[-1].timestamp if invs else None,
            distinct_cwds=sorted({i.cwd for i in invs if i.cwd}),
        )
    return out


# ---------- 规则建议挖掘 ----------


def mine_rule_suggestions(
    invocations: list[SkillInvocation],
    *,
    min_invocations: int = 3,
    min_cwd_concentration: float = 0.5,
) -> list[RuleSuggestion]:
    """对每个 ≥ min_invocations 次的 skill 挖规则：若 ≥ min_cwd_concentration 比例
    的调用共享同一 cwd，suggest 一条 cwd-glob 规则（enforcement=suggest，**默认不强制**——
    用户在看板确认后才升级 mandatory；符合 SPEC §2.1"降低写规则的摩擦到几乎为零"）。

    P0 启发式简洁：取最常见的 cwd 末三段做 glob。后续 phase 可加 file_glob / intent_keywords。
    """
    out: list[RuleSuggestion] = []
    by_skill: dict[str, list[SkillInvocation]] = defaultdict(list)
    for inv in invocations:
        by_skill[inv.skill_name].append(inv)

    for skill, invs in by_skill.items():
        if len(invs) < min_invocations:
            continue
        cwd_counts = Counter(i.cwd for i in invs if i.cwd)
        if not cwd_counts:
            continue
        top_cwd, top_n = cwd_counts.most_common(1)[0]
        ratio = top_n / len(invs)
        if ratio < min_cwd_concentration:
            continue
        glob = _cwd_to_glob(top_cwd)
        out.append(
            RuleSuggestion(
                id=f"auto-{skill}-{abs(hash(glob)) % 100000}",
                description=f"在 {top_cwd} 子目录下倾向于调用 {skill}（{top_n}/{len(invs)} 次）",
                when_cwd_glob=[glob],
                require_skill=skill,
                enforcement="suggest",
                evidence={
                    "total_invocations": len(invs),
                    "top_cwd": top_cwd,
                    "concentration_ratio": round(ratio, 2),
                    "distinct_cwds_count": len(cwd_counts),
                },
            )
        )
    return out


def _cwd_to_glob(cwd: str) -> str:
    parts = Path(cwd).parts
    if len(parts) >= 3:
        # 取末三段做 "**/<a>/<b>/<c>/**"——既具体到能命中，又允许在子目录里触发
        tail = "/".join(parts[-3:])
        return f"**/{tail}/**"
    return f"{cwd.rstrip('/')}/**"


# ---------- suggestions.json 持久化 ----------


def save_suggestions(
    suggestions: list[RuleSuggestion],
    path: Path = DEFAULT_SUGGESTIONS_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suggestions": [asdict(s) for s in suggestions],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
