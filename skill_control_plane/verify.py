"""质量门：判定一个 skill 是否 verified / needs-review / blocked。

SPEC §7。**静态扫描，不执行任何脚本。** "宁可误报让人看，不可漏报。"

输出 VerifyResult{ id, badge, score, checks: [CheckResult] }。
- error 级有任意未过项 → badge=blocked
- 否则有 warn 未过项 → badge=needs-review
- 全过 → badge=verified

score（启发式）：100 − 50×error − 15×warn，下限 0。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import parse_frontmatter

# ---------- 配置（数值与模式集中此处，便于调参） ----------

SKILL_MD_LINE_LIMIT = 500           # SPEC §7.2 推荐
DESCRIPTION_MIN_LEN = 20            # 太短没法当 trigger
DESCRIPTION_MAX_LEN = 1024          # 太长会被截断
SCORE_PENALTY_ERROR = 50
SCORE_PENALTY_WARN = 15

# 只扫脚本类扩展名；.md/.txt 等文档不扫——避免把 SKILL.md 里"教学性危险示例"
# 误判为攻击。文档表述意图，脚本承载执行；DANGER_PATTERNS 命中脚本才是真威胁。
SCANNABLE_EXTS = {
    ".sh", ".bash", ".zsh", ".ksh", ".fish",
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".rb", ".pl", ".php", ".lua", ".r", ".jl",
}

# 排除依赖 / 构建 / 缓存目录——这些不是 skill 作者写的代码。
# 真机 verify --all 数据揭示：不排除 node_modules/ 会让任何带 JS 依赖的 skill
# 误判 blocked（DECISIONS 2026-05-24 Phase 2 调参）。
EXCLUDED_DIR_PARTS = {
    "node_modules", "vendor", "vendored", "third_party", "third-party",
    ".venv", "venv", "env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "dist", "build", "out", "target",
    ".git",
}

# 高危模式（移植自 prototype/scripts/verify_skill.py，沙箱已验证 4/4 通过；
# 加了若干 Python/JS 动态执行模式）
DANGER_PATTERNS: list[tuple[str, str]] = [
    # 远程脚本管道执行
    (r"curl[^\n|]*\|\s*(ba)?sh", "管道执行远程脚本 (curl|sh)"),
    (r"wget[^\n|]*\|\s*(ba)?sh", "管道执行远程脚本 (wget|sh)"),
    (r"base64\s+-d[^\n|]*\|\s*(ba)?sh", "base64 解码后执行"),
    # 破坏性命令
    (r"rm\s+-rf\s+/", "rm -rf 根路径"),
    (r"chmod\s+777", "chmod 777 (过度授权)"),
    # 提权
    (r"\bsudo\s", "sudo 提权"),
    # 动态代码执行（negative lookbehind 排除 obj.eval(/obj.exec( 这类方法调用，
    # 否则 JS 的 regex.exec / child_process.exec 也匹配——大量误报）
    (r"\beval\s+[\"'$(]", "eval 动态执行 (shell)"),
    (r"(?<![\w.])eval\s*\(", "eval(...) 动态执行 (Python/JS)"),
    (r"(?<![\w.])exec\s*\(", "exec(...) 动态执行 (Python)"),
    (r"\bos\.system\s*\(", "os.system 执行任意命令"),
    (r"shell\s*=\s*True", "subprocess shell=True (注入面)"),
]

TRIGGER_WORDS = [
    "use when", "use this", "when you", "when the", "when needed",
    "trigger when", "use to",
    "当", "用于", "在", "触发", "需要",
]


# ---------- 数据结构 ----------


@dataclass
class CheckResult:
    name: str
    level: str           # error / warn / info
    passed: bool
    msg: str


@dataclass
class VerifyResult:
    id: str
    badge: str           # verified / needs-review / blocked
    score: int           # 0-100
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def errors(self) -> list[CheckResult]:
        return [c for c in self.checks if c.level == "error" and not c.passed]

    @property
    def warns(self) -> list[CheckResult]:
        return [c for c in self.checks if c.level == "warn" and not c.passed]


# ---------- 单项检查 ----------


def _check_structure(path: Path) -> CheckResult:
    """SKILL.md 存在且 frontmatter 含 name + description。失败=error。"""
    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        return CheckResult("structure", "error", False, "缺少 SKILL.md")
    text = skill_md.read_text(encoding="utf-8", errors="ignore")
    fm = parse_frontmatter(text)
    if not fm:
        return CheckResult(
            "structure", "error", False,
            "缺少 YAML frontmatter（需要 --- 包裹）",
        )
    missing = []
    if not fm.name:
        missing.append("name")
    if not fm.description:
        missing.append("description")
    if missing:
        return CheckResult(
            "structure", "error", False,
            f"frontmatter 缺少必填字段：{', '.join(missing)}",
        )
    return CheckResult("structure", "error", True, "frontmatter 结构 OK")


def _check_trigger_style(path: Path) -> CheckResult:
    """description 是触发式写法（"use when…" / "当…时"）。失败=warn。

    这是 SPEC §1.1 提到的 ~50% 触发率失败的最大根因之一。
    """
    text = (path / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    fm = parse_frontmatter(text)
    if not fm or not fm.description:
        return CheckResult("trigger_style", "warn", False, "无 description 无法 lint")
    if fm.description_is_block:
        return CheckResult(
            "trigger_style", "warn", False,
            "description 是多行 block scalar 或空值——会被解析器截断；这是 ~50% 触发率失败的最大根因之一",
        )
    desc_lower = fm.description.lower()
    if not any(w in desc_lower for w in TRIGGER_WORDS):
        return CheckResult(
            "trigger_style", "warn", False,
            "description 不是触发式写法（缺 'use when / 当…时' 类触发词），模型不知道何时该唤起",
        )
    return CheckResult("trigger_style", "warn", True, "description 是触发式写法")


def _check_description_length(path: Path) -> CheckResult:
    text = (path / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    fm = parse_frontmatter(text)
    if not fm or not fm.description:
        return CheckResult("description_length", "warn", False, "无 description")
    n = len(fm.description)
    if n < DESCRIPTION_MIN_LEN:
        return CheckResult(
            "description_length", "warn", False,
            f"description 过短 ({n} < {DESCRIPTION_MIN_LEN} 字符)，模型缺触发线索",
        )
    if n > DESCRIPTION_MAX_LEN:
        return CheckResult(
            "description_length", "warn", False,
            f"description 过长 ({n} > {DESCRIPTION_MAX_LEN} 字符)，挤占 context 预算",
        )
    return CheckResult("description_length", "warn", True, f"description 长度 OK ({n} 字符)")


def _check_size(path: Path) -> CheckResult:
    """SKILL.md ≤ 500 行（SPEC §7.2）。超出=warn——占 context 预算。"""
    skill_md = path / "SKILL.md"
    try:
        with skill_md.open(encoding="utf-8", errors="ignore") as f:
            n = sum(1 for _ in f)
    except OSError:
        return CheckResult("size", "warn", False, "无法读 SKILL.md")
    if n > SKILL_MD_LINE_LIMIT:
        return CheckResult(
            "size", "warn", False,
            f"SKILL.md {n} 行 > {SKILL_MD_LINE_LIMIT}——会挤占 context 预算",
        )
    return CheckResult("size", "warn", True, f"SKILL.md {n} 行（≤ {SKILL_MD_LINE_LIMIT}）")


def _check_security_scan(path: Path) -> CheckResult:
    """静态扫脚本类文件（SCANNABLE_EXTS）匹配 DANGER_PATTERNS。

    命中任一 → error，整条 skill blocked。**不扫 .md/.txt 等文档**——文档可能
    含教学性危险示例（如 README 说"运行 rm -rf /tmp/foo"），不是执行面。
    """
    hits: list[str] = []
    for sub in path.rglob("*"):
        if not sub.is_file():
            continue
        ext = sub.suffix.lower()
        if ext not in SCANNABLE_EXTS:
            continue
        rel = sub.relative_to(path)
        # 跳过依赖 / 构建 / 缓存目录——非 skill 作者代码
        if any(part in EXCLUDED_DIR_PARTS for part in rel.parts):
            continue
        try:
            content = sub.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat, label in DANGER_PATTERNS:
            if re.search(pat, content):
                hits.append(f"{rel}: {label}")
    if hits:
        shown = "; ".join(hits[:5])
        if len(hits) > 5:
            shown += f" ... (+{len(hits) - 5} more)"
        return CheckResult("security_scan", "error", False, shown)
    return CheckResult("security_scan", "error", True, "脚本静态安全扫描通过")


# 检查顺序：structure 先（失败时跳过后续）
_POST_STRUCTURE_CHECKS = [
    _check_trigger_style,
    _check_description_length,
    _check_size,
    _check_security_scan,
]


# ---------- 主入口 + 评分 ----------


def verify_dir(path: Path, *, sid: str | None = None) -> VerifyResult:
    """对一个 skill 目录跑全部检查。

    sid（如 "claude:user:pdf"）缺省时按目录名兜底；写回 registry 时调用方应显式传入。
    """
    if sid is None:
        sid = f"unknown:user:{path.name}"

    results: list[CheckResult] = []
    sresult = _check_structure(path)
    results.append(sresult)
    # structure 失败时其它检查无意义（且会因找不到文件而崩）——直接跳
    if sresult.passed:
        for check in _POST_STRUCTURE_CHECKS:
            results.append(check(path))

    badge, score = _grade(results)
    return VerifyResult(id=sid, badge=badge, score=score, checks=results)


def _grade(checks: list[CheckResult]) -> tuple[str, int]:
    errors = sum(1 for c in checks if c.level == "error" and not c.passed)
    warns = sum(1 for c in checks if c.level == "warn" and not c.passed)
    score = max(0, 100 - SCORE_PENALTY_ERROR * errors - SCORE_PENALTY_WARN * warns)
    if errors > 0:
        return "blocked", score
    if warns > 0:
        return "needs-review", score
    return "verified", score
