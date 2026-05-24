"""Issues 引擎（Phase 4.5）。

把"每个 skill 该让用户操心的事"显式列出来——含 why（一句话原因）+ how_to_fix
（一句话指引）。Dashboard 的 Issues Tab 按 issue type 分组展示，让用户的"清理"
任务从浏览器一步可达，不用再回 CLI 解析。

Issue 不存进 registry——纯函数计算，对当前 registry 状态求得。这样 verify/usage
任一更新后，下次看板加载就能看到新 issue。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import RegistryEntry

# 严重度：high 必须处理（安全/破坏性）、med 建议处理（影响触发率/质量）、low 长期清理
SEVERITY_HIGH = "high"
SEVERITY_MED = "med"
SEVERITY_LOW = "low"


@dataclass
class Issue:
    skill_id: str
    severity: str        # high / med / low
    type: str            # security / structure / trigger_style / size / duplicate / dead / stale
    why: str             # 一句话：为什么这是个问题
    how_to_fix: str      # 一句话：怎么修

    def to_dict(self) -> dict:
        return asdict(self)


# 阈值
DEAD_FRESHNESS_THRESHOLD_DAYS = 30      # 死重还要求 freshness 也老才算（新装的不算死）
STALE_THRESHOLD_DAYS = 90


def compute_issues_for_entry(e: "RegistryEntry") -> list[Issue]:
    """对单个 entry 算 issues。纯函数。"""
    out: list[Issue] = []

    # 1. 安全/结构：badge=blocked 必有 error，全升 high
    if e.verify.badge == "blocked":
        # error 文本已经在 verify 里跑过，这里给 high 级 issue
        out.append(Issue(
            skill_id=e.id, severity=SEVERITY_HIGH, type="security",
            why="质量门检测到高危/结构错误（curl|sh、rm -rf、缺 SKILL.md 等）。"
                "放行这类 skill 会让控制平面变成攻击面或注册表脏数据。",
            how_to_fix=f"打开 {e.path}，按照 verify 的报错逐项修；"
                       "或直接禁用：mv 此目录到 *.disabled/ 即可暂时屏蔽。",
        ))

    # 2. 触发式 lint：badge=needs-review 时挖具体原因 —— **加可执行的改写模板**
    if e.verify.badge == "needs-review":
        # description 触发式问题
        if not _looks_like_trigger(e.description):
            out.append(Issue(
                skill_id=e.id, severity=SEVERITY_MED, type="trigger_style",
                why="description 不是触发式写法（缺 'use when / 当…时' 类触发词），"
                    "模型不知道何时该唤起；这是 ~50% 触发率失败的最大根因之一。",
                how_to_fix=_suggest_trigger_rewrite(e),
            ))
        # description 多行 block
        if _looks_like_block_scalar(e.description):
            out.append(Issue(
                skill_id=e.id, severity=SEVERITY_MED, type="trigger_style",
                why="description 用了 YAML block scalar（| 或 >），解析器会把它截断为空字符串；"
                    "模型实际看到的 description 是 '|' 而非真实内容。",
                how_to_fix="把 description 改为单行字符串：'description: Use this skill when ...'。"
                           "不要用 '|' 或 '>' 多行块。",
            ))
        # 长度问题
        if e.description and len(e.description) < 20:
            out.append(Issue(
                skill_id=e.id, severity=SEVERITY_MED, type="trigger_style",
                why=f"description 过短（{len(e.description)} 字符），缺乏触发线索。",
                how_to_fix="补全 description 到至少 20 字符，"
                           "包含触发条件、典型用户输入特征。",
            ))

    # 3. 重复：duplicate_of 标了
    if e.duplicate_of:
        out.append(Issue(
            skill_id=e.id, severity=SEVERITY_MED, type="duplicate",
            why=f"description 与 {e.duplicate_of} 高度重合。"
                "重复 skill 让模型选错（context rot 直接来源），稀释触发率。",
            how_to_fix=f"对比与 {e.duplicate_of}：保留一个、禁用另一个；"
                       "或在 description 里明确区分触发场景。",
        ))

    # 4. 死重：Claude 侧 + 无显式调用 + 无隐式提及 + 不是新装
    if (
        e.usage.source == "claude_jsonl"
        and (e.usage.invocations or 0) == 0
        and (e.usage.implicit_mentions or 0) == 0
        and (e.freshness_days or 0) >= DEAD_FRESHNESS_THRESHOLD_DAYS
    ):
        out.append(Issue(
            skill_id=e.id, severity=SEVERITY_LOW, type="dead",
            why=f"30 天内既没显式 Skill() 调用也没隐式名提及；"
                f"且文件已 {e.freshness_days} 天未更新——疑似装完就忘的一锤子买卖。",
            how_to_fix=f"考虑归档：mv {e.path} 到 *.disabled/；"
                       "若有意保留也建议禁用，省 context 预算。",
        ))

    # 5. 长期未更新：freshness > 90 天
    if (e.freshness_days or 0) >= STALE_THRESHOLD_DAYS:
        out.append(Issue(
            skill_id=e.id, severity=SEVERITY_LOW, type="stale",
            why=f"SKILL.md 已 {e.freshness_days} 天未修改。"
                "skill 周边依赖（API/格式/最佳实践）可能已变。",
            how_to_fix="复核：依赖的工具/库是否升级？描述是否仍准确？过期建议归档。",
        ))

    return out


def compute_all_issues(entries: dict[str, "RegistryEntry"]) -> dict[str, list[Issue]]:
    return {sid: compute_issues_for_entry(e) for sid, e in entries.items()}


def flatten_issues(per_entry: dict[str, list[Issue]]) -> list[Issue]:
    """全表展平 + 按严重度排序（high 在前），方便 dashboard Issues tab 用。"""
    flat: list[Issue] = []
    for issues in per_entry.values():
        flat.extend(issues)
    rank = {SEVERITY_HIGH: 0, SEVERITY_MED: 1, SEVERITY_LOW: 2}
    flat.sort(key=lambda i: (rank.get(i.severity, 9), i.type, i.skill_id))
    return flat


def group_issues_by_type(per_entry: dict[str, list[Issue]]) -> dict[str, list[Issue]]:
    """按 issue.type 分桶——Issues tab 默认这样分组展示。"""
    out: dict[str, list[Issue]] = {}
    for issues in per_entry.values():
        for iss in issues:
            out.setdefault(iss.type, []).append(iss)
    return out


# ---------- 模板辅助 ----------

_TRIGGER_WORDS = (
    "use when", "use this", "when you", "when the", "when needed",
    "trigger when", "use to", "当", "用于", "在", "触发", "需要",
)


def _looks_like_trigger(description: str) -> bool:
    if not description:
        return False
    low = description.lower()
    return any(w in low for w in _TRIGGER_WORDS)


def _looks_like_block_scalar(description: str) -> bool:
    return description in ("|", ">", "|-", ">-", "|+", ">+") or description == ""


def _suggest_trigger_rewrite(e: "RegistryEntry") -> str:
    """生成具体的"建议改写"提示，尽量用 entry 自己的信息。"""
    # 优先从前几个 trigger_keywords 构造一个 "Use this skill when..." 模板
    kws = [k for k in e.trigger_keywords[:3] if len(k) >= 3]
    if kws:
        kws_text = " / ".join(kws)
        return (
            f"改写为触发式开头。建议模板：'Use this skill when the user works on "
            f"[{kws_text}] tasks.'  或：'当用户需要 [{kws_text}] 时使用本 skill。'  "
            f"把抽象功能描述改成「何时触发」。"
        )
    # 没有触发词时退回通用模板
    return (
        "改写为触发式开头。建议模板：'Use this skill when [描述触发场景].' "
        "或：'当 [触发条件] 时使用本 skill。'  关键是把抽象功能描述改成「何时触发」。"
    )


def stats(per_entry: dict[str, list[Issue]]) -> dict[str, int]:
    """severity / type 统计——给 Overview tab 的健康分用。"""
    by_sev: dict[str, int] = {}
    by_type: dict[str, int] = {}
    total = 0
    for issues in per_entry.values():
        for iss in issues:
            total += 1
            by_sev[iss.severity] = by_sev.get(iss.severity, 0) + 1
            by_type[iss.type] = by_type.get(iss.type, 0) + 1
    return {
        "total": total,
        **{f"severity/{k}": v for k, v in by_sev.items()},
        **{f"type/{k}": v for k, v in by_type.items()},
    }
