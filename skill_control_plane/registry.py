"""注册表：所有已发现 skill 的单一事实表（SPEC §8.2 schema）。

存储：~/.skill-control-plane/registry.json（本地 JSON、无云端）。
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .discovery import SkillRecord

DEFAULT_REGISTRY_PATH = Path.home() / ".skill-control-plane" / "registry.json"


# ---------- schema ----------


@dataclass
class VerifyState:
    badge: str = "unverified"        # verified / needs-review / blocked / unverified
    score: int = 0
    last_run: str | None = None


@dataclass
class UsageState:
    invocations: int = 0
    last_used: str | None = None
    never_used: bool = True
    # 用量信号来源；Phase 3 加：区分"Claude 离散调用统计"vs"Codex 不支持"vs"未跑过"。
    # 不区分会让 dashboard 把 Codex skill 全标"死重"（误导）。
    source: str = "unknown"     # claude_jsonl / unsupported / unknown
    # Phase 4 加：text-scan 启发式——skill 名在 assistant text 中按会话计数。
    # 用于"隐式使用"信号：Claude Skill tool_use 在真实数据中稀疏（DECISIONS Phase 3
    # 洞察），多数 skill 是 description 加载进 context 后被隐式使用。
    # 启发式：高假阳性（短名/常见词易误报），dashboard 加 disclaimer。
    implicit_mentions: int = 0


@dataclass
class RegistryEntry:
    id: str
    tool: str
    scope: str
    name: str
    path: str
    summary: str = ""
    trigger_keywords: list[str] = field(default_factory=list)
    verify: VerifyState = field(default_factory=VerifyState)
    usage: UsageState = field(default_factory=UsageState)
    freshness_days: int | None = None
    duplicate_of: str | None = None
    enabled: bool = True
    # Phase 4.5：完整 description（不只第一句 summary）。
    # 让搜索能命中 description body 而不止 name+summary；前端按主题 facet 也用得上。
    description: str = ""
    # Phase 4.5：自动 tag（由 tagging.derive_tags 算出，存到 entry 上供前端 facet 用）。
    tags: list[str] = field(default_factory=list)


# ---------- 一句话摘要（--no-llm 默认）----------

# 中英标点都识别；尽量保留句末标点。
_SENT_SEP = re.compile(r"(?<=[。.!?！？])\s*")
_MAX_SUMMARY_LEN = 140


def summarize_no_llm(description: str | None) -> str:
    """从 description 取第一句作为一句话摘要。零密钥、零网络。"""
    if not description:
        return ""
    parts = _SENT_SEP.split(description, maxsplit=1)
    first = (parts[0] if parts else "").strip()
    if len(first) > _MAX_SUMMARY_LEN:
        first = first[: _MAX_SUMMARY_LEN - 3] + "..."
    return first


# ---------- 触发关键词抽取 ----------

_KW_STOP = {
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "with",
    "this", "that", "when", "use", "uses", "used", "using", "skill", "skills",
    "you", "your", "need", "needs", "needed", "etc",
}


def extract_trigger_keywords(description: str | None) -> list[str]:
    """从 description 抽出 ≤8 个粗糙触发关键词。"""
    if not description:
        return []
    en = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", description)
    zh = re.findall(r"[一-鿿]{2,8}", description)
    seen: list[str] = []
    for token in [t.lower() for t in en] + zh:
        if token in _KW_STOP:
            continue
        if token in seen:
            continue
        seen.append(token)
        if len(seen) >= 8:
            break
    return seen


# ---------- 去重检测（token Jaccard）----------


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    en = re.findall(r"[a-z][a-z0-9_\-]{2,}", text.lower())
    zh = re.findall(r"[一-鿿]{2,8}", text)
    return set(en) | set(zh)


def find_duplicates(entries: list[RegistryEntry], threshold: float = 0.6) -> dict[str, str]:
    """识别近似重复对，返回 {dup_id: canonical_id}。

    canonical 选择规则：verified > 较短 summary > 字典序较小 id。
    """
    out: dict[str, str] = {}
    pre = [(_tokens(e.summary), e) for e in entries]
    for i, (ti, ei) in enumerate(pre):
        if not ti:
            continue
        for j in range(i + 1, len(pre)):
            tj, ej = pre[j]
            if not tj:
                continue
            inter = len(ti & tj)
            union = len(ti | tj)
            if union == 0:
                continue
            if inter / union < threshold:
                continue
            canonical, dup = _pick_canonical(ei, ej)
            out.setdefault(dup.id, canonical.id)
    return out


def _pick_canonical(a: RegistryEntry, b: RegistryEntry) -> tuple[RegistryEntry, RegistryEntry]:
    av, bv = (a.verify.badge == "verified"), (b.verify.badge == "verified")
    if av and not bv:
        return a, b
    if bv and not av:
        return b, a
    if len(a.summary) != len(b.summary):
        return (a, b) if len(a.summary) <= len(b.summary) else (b, a)
    return (a, b) if a.id <= b.id else (b, a)


# ---------- 存储 IO ----------


def load(path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, RegistryEntry]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, RegistryEntry] = {}
    for sid, body in (raw.get("skills") or {}).items():
        ve = body.get("verify") or {}
        ue = body.get("usage") or {}
        out[sid] = RegistryEntry(
            id=body.get("id", sid),
            tool=body.get("tool", ""),
            scope=body.get("scope", ""),
            name=body.get("name", ""),
            path=body.get("path", ""),
            summary=body.get("summary", ""),
            trigger_keywords=list(body.get("trigger_keywords") or []),
            verify=VerifyState(**{k: v for k, v in {**asdict(VerifyState()), **ve}.items() if k in VerifyState.__dataclass_fields__}),
            usage=UsageState(**{k: v for k, v in {**asdict(UsageState()), **ue}.items() if k in UsageState.__dataclass_fields__}),
            freshness_days=body.get("freshness_days"),
            duplicate_of=body.get("duplicate_of"),
            enabled=bool(body.get("enabled", True)),
            description=body.get("description", ""),
            tags=list(body.get("tags") or []),
        )
    return out


def save(entries: dict[str, RegistryEntry], path: Path = DEFAULT_REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import time as _t
    from datetime import datetime as _dt, timezone as _tz
    payload = {
        "version": 1,
        "saved_at": _dt.now(_tz.utc).isoformat(),    # 看板显示"上次扫描"
        "skills": {sid: asdict(e) for sid, e in entries.items()},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 构建：SkillRecord → RegistryEntry ----------


def build(records: Iterable[SkillRecord]) -> dict[str, RegistryEntry]:
    entries: dict[str, RegistryEntry] = {}
    now_days = int(time.time() // 86400)
    for r in records:
        desc = r.frontmatter.description if r.frontmatter else None
        summary = summarize_no_llm(desc)
        kws = extract_trigger_keywords(desc)
        freshness: int | None
        try:
            mtime = r.path.stat().st_mtime
            freshness = max(0, now_days - int(mtime // 86400))
        except OSError:
            freshness = None
        entries[r.id] = RegistryEntry(
            id=r.id,
            tool=r.tool,
            scope=r.scope,
            name=r.name,
            path=str(r.path),
            summary=summary,
            trigger_keywords=kws,
            freshness_days=freshness,
            description=desc or "",   # Phase 4.5：保留全 description 供搜索 + facet
        )
    for dup_id, canonical_id in find_duplicates(list(entries.values())).items():
        if dup_id in entries:
            entries[dup_id].duplicate_of = canonical_id
    # Phase 4.5：自动 tag——延迟 import 避免循环依赖
    try:
        from . import tagging
        tagging.assign_tags(entries)
    except ImportError:
        pass
    return entries


def stats(entries: dict[str, RegistryEntry]) -> dict[str, int]:
    by_tool: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    by_badge: dict[str, int] = {}
    dup_count = 0
    for e in entries.values():
        by_tool[e.tool] = by_tool.get(e.tool, 0) + 1
        by_scope[e.scope] = by_scope.get(e.scope, 0) + 1
        by_badge[e.verify.badge] = by_badge.get(e.verify.badge, 0) + 1
        if e.duplicate_of:
            dup_count += 1
    return {
        "total": len(entries),
        "duplicates": dup_count,
        **{f"tool/{k}": v for k, v in by_tool.items()},
        **{f"scope/{k}": v for k, v in by_scope.items()},
        **{f"badge/{k}": v for k, v in by_badge.items()},
    }
