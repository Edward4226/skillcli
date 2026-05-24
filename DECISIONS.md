# DECISIONS

实现期所有取舍、与规格冲突的现实、用户拍板的小决策——按日期流水记录。
遵循规格 §0 / Rule 6 / Rule 9：**遇到与 SPEC 矛盾的现实就停下记一条，再继续，不许静默绕过**。

---

## 2026-05-24 · 阶段 0 启动

### 环境差异（已与用户对齐）
- 工作目录 `/Users/edward/cowork 5000星项目推进/` 启动时为空。
- 规格 + 原型在 `/Users/edward/for claude/`（含 `Skill控制平面_交付规格_v1.md`、`skill-control-layer/{01-MVP规格.md,02-竞品差异.md,03-原型验证记录.md,prototype/}`）。
- 阶段 1–3 直接读取那里的 `prototype/` 复用核心逻辑（hook/route_skill.py 的匹配函数、scripts/verify_skill.py 的 DANGER_PATTERNS、scripts/usage_report.py 的 iter_jsonl + 多键 fallback、examples/ 的金样本）；**不复制到本仓库**，避免双副本漂移。

### 用户已拍板（Q1 / Q2）
- **Q1 仓库位置**：选定空的工作目录 `/Users/edward/cowork 5000星项目推进/` 作为代码根。
- **Q2 蒸馏票排程**：按规格 §14 顺序，阶段 5 在阶段 4 之后做。

### 暂按推荐默认走、待用户最终拍板（Q3 / Q4 / Q5）
- **Q3 `scp scan` 摘要默认行为** → 当前默认 `--no-llm`（取 description 首句，零配置、可离线）；`--llm` 显式开启。
  理由：诚实 + 快 + 零密钥；首次安装即可用。
- **Q4 命名** → 主仓 `skill-control-plane`（pip 包 `skill-control-plane`，Python 包 `skill_control_plane`，CLI `scp`）；蒸馏票子产物 `codex-maxxing`（GitHub 上无人注册，已核）。
  pyproject 中的 `project.urls.Source` 暂填 `_TBD_`，等仓库 owner 定了再换。
- **Q5 Codex 适配** → P0/P1 全为 TODO 桩，真适配放 P2（与规格 §14 阶段 1 默认一致）。

### 阶段 0 脚手架范围（最小可装可跑）
- 顶层：`README.md`、`SPEC.md`（从外部冻结副本）、`DECISIONS.md`、`LICENSE`、`pyproject.toml`、`.gitignore`。
- Python 包：`skill_control_plane/__init__.py`、`skill_control_plane/cli.py`（六子命令 stub）。
- **不**在 P0 创建空的 `hooks/`、`tests/`、`examples/`、`ticket-codex-maxxing/`、`adapters/`、`dashboard/`——它们由各自阶段触发时创建，避免"骨架满天空目录"的半成品感。

---

## 2026-05-24 · 阶段 0 完成

### 触地时浮现的两个 SPEC 出入（已修正、用户已确认）

1. **CLI 名 `scp` 撞系统 OpenSSH `scp`**（secure copy，`/usr/bin/scp`）。
   - 改为：`skillcli`（用户拍板）。
   - 影响：`pyproject.toml [project.scripts]`、`skill_control_plane/cli.py`（prog + 文案 + version 字符串）、`README.md`。
   - **SPEC.md 不改动**（冻结副本，保留原貌作为来源对照）；实现层与 SPEC 命名差异以本 DECISIONS 为准。后续若 SPEC 重修，把"scp → skillcli"统一替换。
2. **`pip install -e .` 被 PEP 668 拒绝**（Python 由 uv 管理，标 externally-managed）。
   - 改为：`uv tool install --editable .`，工件落 `/Users/edward/.local/bin/skillcli`。
   - README 同步更新安装命令为 `uv tool install --editable .`，并写 `pipx install -e .` 作为备选。

### 自检通过
- `skillcli --version` → `skillcli 0.0.1`
- `skillcli --help` 列出 6 子命令（scan / verify / usage / rules / dashboard / doctor）
- `skillcli scan` → "未实装（SPEC §14 阶段 1）" + exit 2
- `skillcli rules validate` → "未实装（SPEC §14 阶段 6）" + exit 2
- `skillcli verify --help` → 显示 path / --all 参数

### 落地文件清单
```
/pyproject.toml
/LICENSE                                  MIT
/README.md                                stub: hook + 60s + 进度表
/.gitignore                               Python + macOS + 本地状态文件
/DECISIONS.md                             本文件
/SPEC.md                                  从 /Users/edward/for claude/Skill控制平面_交付规格_v1.md 冻结副本
/skill_control_plane/__init__.py          __version__ = "0.0.1"
/skill_control_plane/cli.py               argparse 6 子命令 stub，全部 --help 可读
工件：/Users/edward/.local/bin/skillcli  (uv tool managed)
```

### 未做但合规的省略
- 不创建空的 `hooks/` `tests/` `examples/` `ticket-codex-maxxing/` `adapters/` `dashboard/` 目录——按"创建当其阶段触发时再加"原则，避免半成品骨架感。

---

## 2026-05-24 · Q3 / Q5 用户拍板

### Q3 = 确认默认 `--no-llm`
- `skillcli scan` 一句话摘要走 description 首句（零配置、可离线、零密钥）。
- `--llm` 显式开启更精确的 LLM 摘要版本。

### Q5 反转：Codex 适配从 P2 stub 提前到 **P0/P1**
- **理由（用户）**：Codex 用户体量较大，等到 P2 真装会错过早期采纳曲线。
- **与 SPEC §14 的偏离**（SPEC.md 冻结副本不动，以本条为准）：
  - **阶段 1**：`adapters/claude_code.py` 与 `adapters/codex.py` **同时实装**；discovery / registry 同时扫描两套路径。
  - **阶段 3 usage**：解析 Claude JSONL **与** Codex transcript 两套格式（Codex 的会话存储确切路径与字段形状由实现期确认，记入本文件）。
  - **阶段 6 hooks**：`hooks/claude/enforce_skill.py` **与** `hooks/codex/enforce_skill.py` **同步**实装。
  - **P2 剩余**：`PreToolUse` 拦截、上下文 X 光、MCP 体积审计（与 Codex 无关的扩张项）。
- README.md 的「进度」段同步更新，把"两个 adapter / 两套 hook"明示在 P1。

---

## 2026-05-24 · skillcli-dev 私仓立项

- **目的**：放内部材料、进行中文档、策略与计划等"不适合公开"的内容。
  与公开 `skillcli` 仓双轨：公开仓只放可发布的实现 + 用户文档；私仓放决策路径、竞品分析、原型遗物、运营策略。
- **状态**：`gh repo create skillcli-dev --private`（owner = Edward4226）。
- **候选首批内容**（待用户拍板才搬，**不**先斩后奏）：
  - `/Users/edward/for claude/Claude-Code-启动移交手册.md`（本会话起源）
  - `/Users/edward/for claude/Agent驱动开源项目-冲星与赞助策略.md`
  - `/Users/edward/for claude/skill-control-layer/01-MVP规格.md` `02-竞品差异.md` `03-原型验证记录.md`
  - `/Users/edward/for claude/skill-control-layer/prototype/`（三支柱原型脚本与金样本，阶段 1–3 的来源）
- **未确认前**，不复制/不推送任何 `/Users/edward/for claude/` 内容。

---

## 2026-05-24 · 仓库上 GitHub

- **GitHub 名头核查**：`skillcli` 在 GitHub 完全空地——22 个 `q=skillcli+in:name` 结果全是 `skillclip/skillclimb/skillclient/skillclicker/...` 等更长变体，**无人占有精确 `skillcli`**；`Edward4226/skillcli` 验证 404。
- **创建**：`gh repo create skillcli --public --source=. --push`，owner = `Edward4226`。
- **命名清单**（GitHub repo / pip 包 / Python 包 / CLI 四者不同，故记此澄清）：
  - GitHub 仓库：`Edward4226/skillcli`
  - pip 包：`skill-control-plane`（按 SPEC §4 不动）
  - Python 包：`skill_control_plane`
  - CLI 入口：`skillcli`
- pyproject.toml `[project.urls].Source` 由 `_TBD_` 占位改为 `https://github.com/Edward4226/skillcli`。

---
<!-- 后续条目按 ## YYYY-MM-DD · <主题> 追加 -->
