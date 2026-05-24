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

## 2026-05-24 · 阶段 1 侦察：Claude 与 Codex 路径 / 格式 / hook 机制实测

> 这条把 SPEC §10.1 留作"实现期确认"的内容落地。下游 phase 3/6 的设计依赖这里。

### Skill 目录（已实测）
| 工具 | 路径 | 数量 |
|---|---|---|
| Claude | `~/.claude/skills/` | 67 |
| Codex (active) | `~/.codex/skills/` | 64 |
| Codex (disabled) | `~/.codex/skills.disabled/` | 2 |
| Codex (vendor) | `~/.codex/vendor_imports/skills/skills/` | 0（目录在但空，仍要扫） |

**单条 skill 约定相同**：都是 `<dir>/SKILL.md` + 可选脚本文件；frontmatter 含 `name` + `description`（YAML）。**adapters 共享解析逻辑可行**。

### Transcript 路径与格式（已实测）
| 工具 | 路径 | 行格式 | Skill 调用怎么记 |
|---|---|---|---|
| Claude | `~/.claude/projects/<proj>/*.jsonl` | `{message: {content: [{type, ...}]}, ...}`；tool_use 块在 `message.content[]` 内 | **离散 tool_use**，`name="Skill"`（大写 S），`input.skill="<skill-name>"` |
| Codex | `~/.codex/archived_sessions/rollout-<ISO>-<uuid>.jsonl` + `sessions/` | `{timestamp, type, payload}`；type ∈ {session_meta, event_msg, response_item, turn_context} | **无离散 Skill 调用**；skill 内容通过 SKILL.md 注入 prompt，由 model 在 response message 里"使用"——无法直接计数 |

### ❗ 与原型假设的偏离（必须修正）
原型 `scripts/usage_report.py` 设：
```python
SKILL_TOOL_NAMES = {"skill"}    # 小写
```
真实 Claude 数据是 `"Skill"`（大写 S）。**按原型逐字搬会漏掉 100% 真实 skill 调用。** 实装改为大小写不敏感匹配 / 显式 `{"Skill", "skill"}`。

### ❗ Codex hook 机制缺口（影响 Phase 6）
- `~/.codex/config.toml` 里 hook 相关 section **只有 `[hooks.state]`**，且**段体为空**（无 key=value）——这是状态存储位，不是 hook 定义入口。
- `codex --help` 与 `codex plugin --help` 均无 `hook` 子命令。
- **Codex 不像 Claude 那样暴露 `UserPromptSubmit` / `PreToolUse` 等 per-prompt 拦截**。
- **唯一已知的"注入指令"路径是 AGENTS.md**（启动时加载，非每 prompt 触发）——这比 Claude hook 弱一档。
- 待研究：
  - `codex remote-control`（experimental，可能提供事件流入口）
  - `codex mcp-server`（也许 MCP 协议层有 hook 等价物）
  - plugin marketplace 机制（目前只看到 `[plugins.X@openai-curated]` 类条目，是工具加载非 hook）
- **Phase 6 的"Codex 同步实装 hook"承诺需要降级或重设计**——这点等 Phase 6 临近时再深挖；记到这里防止遗忘。

### Phase 1 不受影响 ✅
discovery + registry 只需要扫目录 + 解析 SKILL.md。两套路径对称，实装直接走。Codex 用量统计（Phase 3）和 Codex hook（Phase 6）的复杂性已记录，**不在 Phase 1 范围内被迫处理**。

### Phase 3 设计预警
Codex 用量统计需要**替代信号**而非 tool_use 计数。候选：
1. 解 Codex rollout 的 response_item.payload.content[] 文本扫 "Skill(xxx)" / "SKILL.md" 引用
2. AGENTS.md 段被引用（model 在回复中复述 SKILL.md 内容的痕迹）
3. 仅按"用户在 prompt 里显式 @ skill"统计
**结论**：先在 Phase 3 时再选；现在不锁。

---

## 2026-05-24 · 阶段 1 完成

### 实装范围（与 SPEC §14 阶段 1 + Q5 反转一致）
- `skill_control_plane/adapters/{__init__,base,claude_code,codex}.py`
- `skill_control_plane/discovery.py`（含标准库 frontmatter 解析，不引 PyYAML）
- `skill_control_plane/registry.py`（SPEC §8.2 schema、--no-llm 摘要、token Jaccard 去重）
- `skill_control_plane/cli.py` _cmd_scan 接线
- `tests/{test_discovery,test_registry}.py`（unittest，17 条）

### 真机自检
- `skillcli scan` 输出：**130 个 skill**（claude 67 + codex 63）
- 抓到 **1 个跨工具重复**：`codex:user:frontend-design` ↔ `claude:user:frontend-design`——这是控制平面想消除的典型 context rot 来源
- 注册表落 `~/.skill-control-plane/registry.json`
- 17/17 unittest pass

### 侦察预估 vs 真机的差异（不是 bug，是 adapter 行为正确）
- 侦察说 Codex `skills.disabled/` 有 2 个 → 真机 adapter 报 0（"disabled" scope）
- 侦察说 Codex `skills/` 有 64 个 → 真机 adapter 报 63（"user" scope）
- 原因：`ls -d <dir>/*/` 数 dir，但**不是每个 dir 都含 SKILL.md**：
  - `skills/` 里 1 个 dir 无 SKILL.md
  - `skills.disabled/` 里 2 个 dir 都无 SKILL.md
- 结论：adapter 正确——"存在目录" ≠ "是有效 skill"。

### --llm 实装边界
- Q3 默认 `--no-llm`，已实装；行为=取 description 首句。
- `--llm` 被 cli 接受但**降级**到 `--no-llm` 行为，并打一条 stderr 警告（Phase 3+ 实装）。
  待 Phase 3/4 视 LLM 客户端策略再决定（OpenAI / Anthropic SDK / 本地）。

---

## 2026-05-24 · Phase 2 完成

### 实装
- `skill_control_plane/verify.py`：5 项检查 + 三档徽章 + 评分
- `cli.py` `_cmd_verify`：支持 `<path>` 单条 / `--all` 批量；批量时写回 `registry.verify`
- `tests/test_verify.py`：11 条 unittest，含关键反向（SKILL.md 教学性危险示例**不**触发）
- 累计 17 + 11 = **28/28 unittest pass**

### 真机 `skillcli verify --all`（130 skills）
- **verified: 66 (51%)**
- needs-review: 59 (45%)
- blocked: 5 (4%)

数据吻合"~50% 触发率失败"叙事：约一半 skill 有 trigger/length/size 类 lint 问题，直接对应规格 §1.1 的痛点。

### 5 个 blocked 全为真实安全问题（**非误报**）
- `claude:user:baoyu-post-to-wechat` / `baoyu-post-to-x`: scripts 含 `curl|sh`
- `claude:user:careful`: `bin/check-careful.sh` 含 `rm -rf /`
- `claude:user:gstack`: 测试文件含 `rm -rf /` + 脚本含 `curl|sh`
- `claude:user:webapp-testing`: `scripts/with_server.py` 含 `subprocess shell=True`

这些是**真实需要 skill 用户知情**的高危模式——质量门把它们打 blocked 是正确的。是否允许使用由用户自行决定（未来 dashboard 提供 override 开关）。

### 触地调参（与第一版 verify.py 的差异，记录避免回退）
1. **排除依赖/构建/缓存目录**（`EXCLUDED_DIR_PARTS`）：
   第一版扫 `node_modules/` 致 `brave-search` 误报 35+ hit。
   加排除后误报清零。包含：`node_modules / vendor / .venv / venv / __pycache__ / .pytest_cache / .mypy_cache / dist / build / out / target / .git / .tox`。
2. **`exec` / `eval` 加 negative lookbehind**：
   第一版 `\beval\s*\(` 把 JS `regex.exec()` / `child_process.exec()` 也匹配。
   改 `(?<![\w.])eval\s*\(` / `(?<![\w.])exec\s*\(` 后只匹配顶层调用。
3. **不扫 `.md / .txt` 等文档**（`SCANNABLE_EXTS` 白名单）：
   文档表述意图，脚本承载执行；混淆二者会让教学型 skill 大量误判。
   测试 `test_danger_in_md_does_not_trigger` 锁住此行为。

### 评分公式
`score = max(0, 100 − 50×error − 15×warn)`，下限 0。
- verified = 0 error + 0 warn （100 分）
- needs-review = 0 error + ≥1 warn （70-85 常见）
- blocked = ≥1 error

---

## 2026-05-24 · Phase 3 完成 + 一个重要的产品洞察

### 实装
- `skill_control_plane/usage.py`：`SkillInvocation`（含 cwd + user_prompt 上下文）、`parse_claude_invocations` 流式解析、`aggregate_stats`、`mine_rule_suggestions`（cwd 集中度启发式）、`save_suggestions` 落 `~/.skill-control-plane/suggestions.json`
- `cli.py` `_cmd_usage` 接通：用量 + 死重 + 规则建议
- `registry.UsageState` 加 `source` 字段（`claude_jsonl` / `unsupported` / `unknown`），让 Codex 不被误标"死重"
- `tests/test_usage.py`：11 条 unittest（覆盖大小写不敏感、多键名 fallback、since 过滤、坏行不崩、cwd 集中度规则、< 3 次不挖）
- 累计 17 + 11 + 11 = **39/39 unittest pass**

### 用户拍板：Codex 用量"诚实降级"
Codex transcript 无离散 `Skill` tool 调用（Phase 1 侦察）。用户选 C 选项：
- Codex skill 的 `usage.source = "unsupported"`、`invocations = 0`
- 看板（Phase 4）凭此字段与 Claude "死重" 区分，不假装做不到的事

### ⚠️ 真机数据揭示的**产品洞察**（重要）
真机 `skillcli usage --since 30`：**过去 30 天 0 次 Claude `Skill` 调用**（67 个 Claude skill 全死）。
扩到 `--since 365` 才 6 次（2026-03-20 一天用了 office-hours / plan-ceo-review / plan-eng-review / design-consultation / qa）。

**洞察**：Claude 的 `Skill` tool_use 在真实使用中**极稀疏**。绝大多数 skill 是**隐式使用**——
skill 的 description 被加载进 context，模型按指引行动，**不会显式发起 `Skill(x)` 调用**。
`Skill()` 显式调用只在"模型决定深入某个 skill 的子工作流"时触发。

**对产品的影响**（必须诚实写进未来 README 与 dashboard）：
1. "死重 = `Skill` 调用次数 = 0" 太严苛——本机 67 个全是"死重"，看板没用
2. **Phase 4 dashboard 必须** 区分"显式调用 vs 语义参与度"，至少加 disclaimer
3. 如要"看起来不全死"，可加二级信号：assistant response 文本扫 skill 名引用 / SKILL.md 段被复述
4. **不加的代价**：用户觉得"我明明用过怎么显示 0" → 信任受损

### 决定
- Phase 3 P0 **保留仅显式 `Skill` tool_use 计数**：精确、零幻觉、可解释。
- Phase 4 dashboard 加 disclaimer + 区分 source；若必要再加二级信号（text-scan 启发式）。
- 这是 **诚实 vs 易用** 的取舍——与 Codex "unsupported" 的诚实降级一致。
- 该洞察也是控制平面叙事的有力素材：**"你的 skill 多数从没显式触发过——这是为什么需要规则引擎强制触发"**——把 sparse signal 反过来当卖点。

### Phase 4 设计含义
- 看板上 Claude skill 默认按 verify badge 排序（verified 在前），不按 invocations
- 给"从未显式调用"的 skill 加 "0 explicit calls (skills often used implicitly)" tooltip
- Codex skill 在 dashboard 上标 "Codex (usage tracking not supported)"

---

## 2026-05-24 · Phase 4 完成

### 实装
- `skill_control_plane/usage.py`：`count_implicit_mentions` text-scan 启发式（≥5 字符名、词边界、per-session 计数）
- `skill_control_plane/registry.py`：`UsageState` 加 `implicit_mentions` 字段；`save()` 加 `saved_at` 时间戳（看板"上次扫描"显示用）
- `skill_control_plane/cli.py` `_cmd_usage`：同时计算 + 写回 implicit；死重定义=显式 0 + 隐式 0
- `skill_control_plane/dashboard/{server.py, index.html, __init__.py}`：stdlib http.server + 单文件前端 + Chart.js CDN
- `skill_control_plane/cli.py` `_cmd_dashboard`：接通，含 `--port` / `--no-browser`
- `tests/test_usage_implicit.py` (8) + `tests/test_dashboard.py` (6)：覆盖 text-scan 边界 + dashboard 端点协议
- 累计 39 + 8 + 6 = **53/53 unittest pass**

### 看板设计（普通用户视角）
按用户要求"极致的可视化和易用性"：
1. **首屏摘要 6 卡**（总数 / verified / needs-review / blocked / 用量信号 / 死重+重复）——一眼看健康度
2. **双图**：徽章饼图 + 工具×scope 饼图（Chart.js doughnut）
3. **黄色 disclaimer**：显式 vs 隐式信号说明 + Codex 不支持说明——用户不会被数据误导
4. **Skill 列表**：可搜（名/摘要）+ 9 个 filter chip（全部/verified/needs-review/blocked/used/dead/dup/Claude/Codex）+ 点击行展开详情（verify checks + trigger_kw + path + dup 链）
5. **4 个 callout 区**：安全告警（红） / 跨工具重复（紫） / 死重（灰） / 规则建议（蓝）——把"该看的东西"主动推到用户眼前
6. 默认排序：blocked → needs-review → verified → unverified，同档按用量降序——最需要决策的先出现
7. 全部 vanilla JS + 内联 CSS + Chart.js CDN，**零构建链**

### 隐式信号设计
显式 Skill tool_use 在真实数据中稀疏（Phase 3 洞察），所以加 text-scan 兜底。**关键约束**：
- 最低名长 5 字符：'pdf'/'sql'/'qa' 这类常见词假阳性极高，必须屏蔽
- 词边界：'browser' 不应匹配 'browse'
- per-session 计数：一个会话里多次提到同一 skill 只算 1（避免单 session 灌水）
- 仅扫 assistant text content：用户 prompt 不算（"我是否要用 X" ≠ X 被用了）

真机验证：本机抓到 `codex 12 / review 5 / frontend-design 1 / guard 1` 等命中——
全部合理（我们整个 Phase 都在谈 codex；review 也确实在文中出现）。死重从 67 降到 63。

**Disclaimer 永远显示**：在 dashboard 顶部黄条 + 每个 stat-card 的副标题，让用户清楚
"explicit=精确 / implicit=启发式可能误报"。诚实优先。

### 看板"只读"承诺的硬约束
- server.py **不实装 `do_POST`**——任何 POST 自动返回 501，HTTP 协议层兜底
- 测试 `test_post_not_allowed` 锁住此承诺：若未来不小心实装写端点，CI 立即红
- 规则"一键确认"功能（SPEC §11.1 提及）留给 Phase 6（rules.yaml 与之同期）

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
