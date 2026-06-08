"""规则引擎（SPEC §9）：在特定情况下，必须调用某个已验证 skill。

**确定性、代码决定、不让 LLM 猜**（设计信条 / Rule 5）。本模块是 hooks 的公共
匹配逻辑（SPEC §9.2：公共匹配放 rules.py 复用，宿主适配差异放 adapters/）。

可测核心（parse / validate / match / render）**纯 stdlib、操作 dict**，不依赖
PyYAML——`rules.yaml` 的磁盘读取隔离在 load_rules_file()，仅在真用到时才 import
pyyaml。这样测试零依赖，与既有模块（usage/verify 等）保持一致。
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from .registry import RegistryEntry

# rules.yaml 顶层 version；与 SPEC §9.1 一致。
SCHEMA_VERSION = 1

# 合法的条件类别（全部可代码判定，SPEC §9.1）。
WHEN_KEYS = ("file_glob", "intent_keywords", "task_type", "git_status", "dir")

# 合法的动作模式。
MODES = ("enforce", "suggest")

VERIFIED_BADGE = "verified"


class RuleParseError(ValueError):
    """rules.yaml / dict 结构非法（失败要响，Rule 11）。"""


# ---------- schema ----------


@dataclass
class RuleWhen:
    """规则的命中条件；同时给出的类别取 **AND**，未给出的类别忽略（SPEC §9.1）。"""

    file_glob: list[str] = field(default_factory=list)
    intent_keywords: list[str] = field(default_factory=list)
    task_type: list[str] = field(default_factory=list)
    git_status: list[str] = field(default_factory=list)
    dir: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.file_glob or self.intent_keywords or self.task_type
            or self.git_status or self.dir
        )


@dataclass
class Rule:
    id: str
    require_skill: str           # 必须是注册表中 badge==verified 的 skill id
    description: str = ""
    when: RuleWhen = field(default_factory=RuleWhen)
    mode: str = "enforce"        # enforce=强制注入；suggest=软提示
    message: str = ""

    @property
    def skill_name(self) -> str:
        """从 id（如 claude:user:db-migrate）取末段做 Skill(x) 调用名。"""
        return self.require_skill.split(":")[-1] if self.require_skill else ""


@dataclass
class RuleContext:
    """运行时上下文；由 hook 从宿主输入里组装后传入（SPEC §9.2）。"""

    files: list[str] = field(default_factory=list)     # 变更/打开的文件路径
    intent: str = ""                                   # 用户 prompt 文本
    task_type: str | None = None                       # edit / ask / ...
    git_status: list[str] = field(default_factory=list)  # staged / modified / ...
    dir: str | None = None                             # 当前工作目录


# ---------- 解析 ----------


def parse_rules(data: dict) -> list[Rule]:
    """把已解析的 dict（来自 yaml/json）转成 Rule 列表。结构非法即抛 RuleParseError。"""
    if not isinstance(data, dict):
        raise RuleParseError("rules 顶层必须是 mapping")
    version = data.get("version")
    if version != SCHEMA_VERSION:
        raise RuleParseError(f"version 必须为 {SCHEMA_VERSION}，得到 {version!r}")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        raise RuleParseError("rules 必须是列表")

    out: list[Rule] = []
    for i, r in enumerate(raw_rules):
        where = f"rules[{i}]"
        if not isinstance(r, dict):
            raise RuleParseError(f"{where} 必须是 mapping")
        rid = r.get("id")
        if not rid or not isinstance(rid, str):
            raise RuleParseError(f"{where} 缺少非空字符串 id")
        require = r.get("require")
        if not isinstance(require, dict) or not require.get("skill"):
            raise RuleParseError(f"{where} ({rid}) 缺少 require.skill")
        mode = require.get("mode", "enforce")
        if mode not in MODES:
            raise RuleParseError(f"{where} ({rid}) mode 非法：{mode!r}，须为 {MODES}")

        raw_when = r.get("when") or {}
        if not isinstance(raw_when, dict):
            raise RuleParseError(f"{where} ({rid}) when 必须是 mapping")
        unknown = set(raw_when) - set(WHEN_KEYS)
        if unknown:
            raise RuleParseError(f"{where} ({rid}) when 含未知条件：{sorted(unknown)}")
        when = RuleWhen(
            file_glob=_as_str_list(raw_when.get("file_glob")),
            intent_keywords=_as_str_list(raw_when.get("intent_keywords")),
            task_type=_as_str_list(raw_when.get("task_type")),
            git_status=_as_str_list(raw_when.get("git_status")),
            dir=_as_str_list(raw_when.get("dir")),
        )
        out.append(Rule(
            id=rid,
            require_skill=require["skill"],
            description=r.get("description", ""),
            when=when,
            mode=mode,
            message=r.get("message", ""),
        ))
    return out


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return list(value)
    raise RuleParseError(f"期望字符串或字符串列表，得到 {value!r}")


# ---------- 校验（rules validate）----------


def validate_rules(rules: list[Rule], registry: dict[str, RegistryEntry]) -> list[str]:
    """校验规则集，返回错误列表（空=通过）。

    核心约束（SPEC §9.1 / §12）：require.skill 必须在注册表中**且 badge==verified**，
    否则报错。这是产品核心承诺——绝不强制触发一个未经质量门的 skill。失败要响。
    """
    errors: list[str] = []
    seen: set[str] = set()
    for r in rules:
        if r.id in seen:
            errors.append(f"规则 id 重复：{r.id}")
        seen.add(r.id)

        if r.when.is_empty():
            errors.append(f"规则 {r.id}：when 为空，会无条件命中所有上下文")

        entry = registry.get(r.require_skill)
        if entry is None:
            errors.append(
                f"规则 {r.id}：require.skill={r.require_skill!r} 不在注册表中"
            )
        elif entry.verify.badge != VERIFIED_BADGE:
            errors.append(
                f"规则 {r.id}：require.skill={r.require_skill!r} 的 badge="
                f"{entry.verify.badge!r}，非 verified 不可强制触发"
            )
    return errors


# ---------- 匹配 ----------


def match_rules(rules: list[Rule], ctx: RuleContext) -> list[Rule]:
    """返回所有命中 ctx 的规则。空 when 不命中（由 validate 拦截，这里保守跳过）。"""
    return [r for r in rules if not r.when.is_empty() and _matches(r.when, ctx)]


def _matches(when: RuleWhen, ctx: RuleContext) -> bool:
    # 各类别 AND；某类别未给出（空列表）则视为不约束。
    if when.file_glob and not any(
        _glob_match(p, f) for p in when.file_glob for f in ctx.files
    ):
        return False
    if when.intent_keywords:
        low = ctx.intent.lower()
        if not any(kw.lower() in low for kw in when.intent_keywords):
            return False
    if when.task_type and (ctx.task_type or "") not in when.task_type:
        return False
    if when.git_status and not (set(when.git_status) & set(ctx.git_status)):
        return False
    if when.dir:
        if not _dir_match(when.dir, ctx):
            return False
    return True


def _glob_match(pattern: str, path: str) -> bool:
    """glob 匹配；兼容 ``**/`` 前缀（也匹配顶层无目录的文件）。"""
    norm = path.replace("\\", "/")
    if fnmatch.fnmatch(norm, pattern):
        return True
    # "**/*.sql" 应同时命中顶层 "x.sql"：退一步比 basename。
    tail = pattern.rsplit("/", 1)[-1]
    return fnmatch.fnmatch(norm.rsplit("/", 1)[-1], tail)


def _dir_match(dirs: list[str], ctx: RuleContext) -> bool:
    """目录匹配。兼容相对前缀（"infra/foo.tf"）与绝对 cwd（"/repo/infra"）——
    后者按**路径段**匹配，否则 hook 拿到的绝对 cwd 永远命不中相对规则。"""
    cands = list(ctx.files)
    if ctx.dir:
        cands.append(ctx.dir)
    for d in dirs:
        prefix = d.replace("\\", "/").strip("/")
        if not prefix:
            continue
        seg = "/" + prefix + "/"
        for c in cands:
            cn = c.replace("\\", "/")
            if (cn == prefix or cn.startswith(prefix + "/")
                    or seg in cn or cn.endswith("/" + prefix)):
                return True
    return False


# ---------- 注入文本 ----------


def render_injection(matched: list[Rule]) -> str:
    """把命中规则渲染成注入给宿主的指令文本。无命中→空串（hook 静默）。

    enforce：强制"必须先评估并激活 Skill(x)"；suggest：软提示。指令文本含
    Skill(<name>) 以便宿主识别（SPEC §9.3 验收）。hook 只注入文本，不直接执行。
    """
    if not matched:
        return ""
    lines: list[str] = []
    enforced = [r for r in matched if r.mode == "enforce"]
    suggested = [r for r in matched if r.mode == "suggest"]

    for r in enforced:
        note = f" {r.message}" if r.message else ""
        lines.append(
            f"[skill-control-plane] 规则 {r.id} 命中：你必须先评估并激活 "
            f"Skill({r.skill_name}) 再继续。{note}".rstrip()
        )
    for r in suggested:
        note = f" {r.message}" if r.message else ""
        lines.append(
            f"[skill-control-plane] 规则 {r.id} 命中（建议）：考虑使用 "
            f"Skill({r.skill_name})。{note}".rstrip()
        )
    return "\n".join(lines)


# ---------- 运行时求值（hook 复用）----------


def evaluate(rules: list[Rule], ctx: RuleContext) -> str:
    """匹配 + 渲染的一步快捷方式；hook 与 `rules test` 共用。"""
    return render_injection(match_rules(rules, ctx))


def context_from_claude_prompt(payload: dict) -> RuleContext:
    """从 Claude Code UserPromptSubmit 的 stdin JSON 组装 RuleContext。

    UserPromptSubmit 在 prompt 提交时触发，此刻没有"变更文件"，所以主要用得上
    intent（prompt 文本）+ dir（cwd）。file_glob/git_status 留给 PreToolUse（P1）。
    适配宿主特有的 payload 形状（SPEC §9.2：适配差异隔离）。
    """
    return RuleContext(
        intent=str(payload.get("prompt") or ""),
        dir=payload.get("cwd") or None,
    )


# ---------- 磁盘 IO（rules.json 为运行时规范；rules.yaml 可选人写源）----------

# 运行时规范文件：hook 读它，零依赖（DECISIONS：hook 须零依赖，故 json 优先）。
DEFAULT_RULES_DIR = Path.home() / ".skill-control-plane"


def find_rules_file(base_dir: Path = DEFAULT_RULES_DIR) -> Path | None:
    """定位规则文件：优先 rules.json（hook 用），回退 rules.yaml。都没有→None。"""
    for name in ("rules.json", "rules.yaml", "rules.yml"):
        cand = Path(base_dir) / name
        if cand.is_file():
            return cand
    return None


def load_rules_path(path: Path) -> list[Rule]:
    """按扩展名加载规则文件 → Rule 列表。.json 走 stdlib；.yaml/.yml 需 PyYAML。"""
    import json

    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuleParseError(f"{path} 不是合法 JSON：{exc}") from exc
        return parse_rules(data)
    # YAML 路径（可选依赖，诚实降级 Rule 11）
    try:
        import yaml
    except ImportError as exc:
        raise RuleParseError(
            f"读取 {path.name} 需要 PyYAML：pip install 'skill-control-plane[yaml]'，"
            f"或改用零依赖的 rules.json。"
        ) from exc
    return parse_rules(yaml.safe_load(text))
