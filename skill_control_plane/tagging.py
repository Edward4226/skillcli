"""自动主题 tag（Phase 4.5）。

词频启发：把所有 skill 的 trigger_keywords 汇总，挑出现频次 ≥ MIN_OCCURRENCES
的前 TOP_N 个作为全局 tag。每个 skill 的 tags = 它的 trigger_keywords 与全局 tag 的交集。

为什么用启发式而非 LLM：Q3 用户拍板默认 --no-llm；启发式离线、零密钥、可解释。
代价是 tag 不够"语义"——同义词（pdf / 文档 / document）不会合并。
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import RegistryEntry

# 调参：太多 tag 用户晕、太少 tag 没区分度。10-15 是合理范围。
TOP_N = 15
MIN_OCCURRENCES = 3

# 这些词太通用，即使高频也不当 tag——出现率高但不传递语义信号。
# Phase 4.5 真机调参：跑完一次 scan，看到 'any/asks/creating/user/generates' 这类高频
# 但无领域语义的词进了 tag 列表，加进黑名单。
_BLACKLIST = {
    # 触发短语本身（不算 tag）
    "use", "uses", "using", "used", "skill", "skills",
    "this", "that", "when", "you", "your", "the", "and", "for", "with",
    "need", "needs", "needed", "want", "wants", "wanted",
    "etc", "via", "from", "into", "onto",
    # 真机数据里高频但无领域信号
    "any", "all", "some", "most", "asks", "asking",
    "create", "creates", "creating", "created",
    "generate", "generates", "generating", "generated",
    "user", "users", "task", "tasks",
    "make", "makes", "making", "made", "doing", "does", "done",
    "based", "based-on",
}


def derive_global_tags(
    entries: dict[str, "RegistryEntry"],
    *,
    top_n: int = TOP_N,
    min_occurrences: int = MIN_OCCURRENCES,
) -> list[tuple[str, int]]:
    """统计全局 trigger_keywords 频次，过滤黑名单 + 频次阈值，返回 [(tag, count)]。"""
    counter: Counter[str] = Counter()
    for e in entries.values():
        for kw in e.trigger_keywords:
            k = kw.lower().strip()
            if not k or k in _BLACKLIST:
                continue
            counter[k] += 1
    out: list[tuple[str, int]] = []
    for tag, n in counter.most_common():
        if n < min_occurrences:
            break
        out.append((tag, n))
        if len(out) >= top_n:
            break
    return out


def assign_tags(entries: dict[str, "RegistryEntry"]) -> list[tuple[str, int]]:
    """计算全局 tag 表，按 entry.trigger_keywords 交集分配给每个 entry。

    **副作用**：直接修改 entries[*].tags。返回全局 tag 列表（带计数）供 UI 用。
    """
    global_tags = derive_global_tags(entries)
    tag_set = {t for t, _ in global_tags}
    for e in entries.values():
        e.tags = [
            kw.lower().strip()
            for kw in e.trigger_keywords
            if kw.lower().strip() in tag_set
        ]
        # 去重并保序
        seen: set[str] = set()
        deduped: list[str] = []
        for t in e.tags:
            if t not in seen:
                seen.add(t)
                deduped.append(t)
        e.tags = deduped
    return global_tags
