# Skill 控制平面 + codex-maxxing 蒸馏票 —— 实现交付规格 v1

> 本文件是给 **Claude Code（或 Codex）** 的实现规格（PRD + 技术规格 + 分阶段实现 checklist）。
> 读者是一个能写代码的 agent。请把本文件放在仓库根目录作为 `SPEC.md`，按"§14 给实现 agent 的执行顺序"分阶段推进。
>
> **语言约定**：交付物（代码注释、README、产出的 .md）优先简体中文，行业术语保留英文（skill / hook / AGENTS.md / token 等）。
> **工程信条（必须遵守）**：① 先想清楚再写，假设要写明；② 简单优先，不做没要求的抽象；③ 外科手术式改动；④ 路由用代码、判断才用模型；⑤ 失败要响——跳过任何步骤就不算"完成"。

---

## 0. 文档怎么用（给实现 agent 的元指令）

1. **先读 §1–§4** 建立全局心智模型，再读你当前阶段对应的模块章节。
2. **不要一次实现全部。** 按 §13 的 `P0 → P1 → P2` 推进，每个 `P` 都要能独立跑起来 + 通过该阶段的验收标准（§12）。
3. **每个模块都有"验收标准"小节**，它就是你的成功判据（Rule 4：定义成功，循环到验证通过）。测试要编码"为什么"，不只是"做了什么"（Rule 8）。
4. **遇到与本规格矛盾的现实**（依赖装不上、API 变了、hook 行为与描述不符），**停下来在 `DECISIONS.md` 里记一条**，说明冲突与你的取舍，再继续（Rule 6/9）。不要静默绕过。
5. **版权红线**：本项目的核心是"把权威知识安装包式简化"。蒸馏 = 用自己的话重构成可执行规则 + 署名 + 链接原文。**禁止整段照搬原文表达**（尤其 Jason Liu 原文的示例 prompt，必须改写）。详见 §5.1。

---

## 1. 背景与要解决的问题

### 1.1 痛点（已被官方数据坐实）

- **Skill 是模型自主触发的，但触发不可靠。** Claude/Codex 的 skill 靠 `name + description` 去匹配用户请求来决定要不要用；社区实测真实会话里**自动触发成功率约 50%**。根因：模型倾向于"按它理解的方式直接干活"，不会主动去检查是否存在对应 skill。
- **于是大家退回去手动打斜杠命令** —— skill 变成"一锤子买卖"：装完就忘，想起来才用。
- **Skill 越多越糟。** 有字符预算上限，装到 100–150 个后互相稀释、互相冲突，出现 "context rot（上下文腐烂）"：注意力被稀释、指令冲突、token 预算被挤占、输出质量下降。
- **没有观测与治理。** 用户不知道每个 skill 到底干嘛、哪些从没被调用过（死重）、哪些重复冲突、哪些已损坏或过期。

### 1.2 市场空位（已核验，2026-05）

- 直接竞品（skill 路由/治理/清理类）全部 **< 15 星**：`hussi9/skill-router`(6)、`khendzel/skills-janitor`(12)、`alexgreensh/token-optimizer`(13, AGPL 不可复用)、`egorfedorov/claude-context-optimizer`(3)。
- 相邻赛道有巨头，但**没有一个是"控制层"**：`musistudio/claude-code-router`(33.9k，是**模型**路由)、`alirezarezvani/claude-skills`(15.3k，是**内容合集**)、`ryoppippi/ccusage`(14.2k，是**成本**分析)。
- **结论**：控制层是真空地。但"照搬功能"会停在十几星——赢点必须是 **具象化痛点 + 零摩擦自动规则 + 质量门 + 分发**，而不是再做一个更漂亮的 janitor。

### 1.3 两个产品支柱的合体逻辑（护城河）

```
蒸馏（产出优质内容） → 质量门（验证） → 注册表（信任） → 规则引擎（在该用时确定性强制触发） → 用量闭环（学习/再优化）
```

- **codex-maxxing 蒸馏票** 提供"优质内容"的源头（一个会爆的 drop-in 配置 + 一批高质量 skill）。
- **控制平面** 让这些 skill 不再是一锤子买卖：被验证、被信任、在对的场景自动出场。
- 一句话定位：**"把权威知识做成已验证、会自动在对的时候出场的 skill。"**

---

## 2. 产品定位与价值主张

| 维度 | 内容 |
|---|---|
| 一句话 | 你本地 skill 库的 **控制平面（control plane）**：把路由+策略做成确定性的，把生成留给模型。 |
| 最尖锐的钩子 | "你的 skill 只有约 50% 会自动触发——这个让该用的那个**每次都触发**。" |
| 目标用户 | 装了几十~上百个 skill 的 Claude Code / Codex 重度用户。 |
| 跨工具 | 同时支持 **Codex（AGENTS.md）** 与 **Claude Code（CLAUDE.md / skills / hooks）**。 |
| 商业模式 | 开源（MIT），非商业化收费。目标是星与影响力，不是营收。 |
| 反指标（不要做） | 不做又一个成本统计器（ccusage 已占）；不做又一个 skill 合集；不做又一个一次性 audit 报告器。 |

### 2.1 设计信条（直接对应用户工程规则）

- **路由/策略用代码（hook），判断/生成用模型。** "特定情况必须调用特定 skill" 本质是确定性规则，必须用 hook 实现，不能让 LLM 猜。
- **降低写规则的摩擦到几乎为零。** 不让用户从零写规则，而是**从历史用量自动生成规则草案**让用户一键确认。
- **价值要可见、可演示、可截图。** 把"触发率 50%→接近 100%"做成能演示的 before/after。

---

## 3. 整体架构

### 3.1 两个平面

```
┌───────────────────────────────────────────────────────────────┐
│  控制平面 (Control Plane) —— 人类在这里治理，确定性代码在这里兑现      │
│                                                                 │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌─────────────┐  │
│   │ 注册表    │   │ 质量门    │   │ 规则引擎  │   │ 用量闭环      │  │
│   │ registry │   │ verify   │   │ rules    │   │ usage        │  │
│   └────┬─────┘   └────┬─────┘   └────┬─────┘   └──────┬──────┘  │
│        │              │              │                │         │
│        └──────────────┴───── 本地只读看板 (dashboard) ─┘         │
└───────────────────────────────┬───────────────────────────────┘
                                 │ 通过 hook 注入 / 拦截
                                 ▼
┌───────────────────────────────────────────────────────────────┐
│  推理平面 (Inference Plane) —— Claude Code / Codex 实际运行的地方   │
│   UserPromptSubmit hook → 注入"必须评估并激活 skill X"             │
│   PreToolUse hook       → 拦截/放行工具调用                        │
└───────────────────────────────────────────────────────────────┘
```

- **控制平面**全部是本地、读本地文件、确定性的，不需要任何云端权限。
- **推理平面**是宿主 agent；我们只通过它原生支持的 **hooks** 注入确定性行为，不 fork、不改宿主。

### 3.2 数据流（端到端，一条规则的生命周期）

```
1. usage 解析本地 transcript → 发现"用户每次改 *.sql 都手动调了 db-migrate"
2. usage 生成规则草案 → 写入 suggestions.json
3. dashboard 展示草案 → 用户一键"确认"
4. 确认后写入 rules.yaml（条件: glob *.sql；动作: 强制 Skill(db-migrate)）
5. 被规则引用的 skill 必须先过 verify（质量门），通过才允许绑定
6. 运行时 UserPromptSubmit/PreToolUse hook 读 rules.yaml → 命中则注入强制指令
7. usage 持续度量该规则命中后的触发率 → 回到 dashboard 形成闭环
```

---

## 4. 仓库结构（跨工具 monorepo）

> 技术栈基线：**Python 3.11+（标准库优先）** 作为 CLI/解析/质量门主体；**单文件本地 web 看板**（原生 HTML+JS，CDN 引 Chart.js，不引入构建链）。理由：装得简单（`pipx install` / `uvx`）、零构建、跨平台。除非有充分理由，不要引入重框架（Rule 2）。

```
skill-control-plane/
├── README.md                      # 面向用户：一句话价值 + 60秒上手 + before/after 演示
├── SPEC.md                        # 本文件
├── DECISIONS.md                   # 实现期所有取舍记录（Rule 6/9）
├── LICENSE                        # MIT
├── pyproject.toml                 # 入口: scp = skill_control_plane.cli:main
│
├── skill_control_plane/           # 控制平面核心（Python 包）
│   ├── __init__.py
│   ├── cli.py                     # 统一 CLI 入口（见 §11）
│   ├── registry.py                # 注册表读写 (§8)
│   ├── verify.py                  # 质量门 (§7)
│   ├── rules.py                   # 规则引擎：加载/匹配/产出注入文本 (§9)
│   ├── usage.py                   # transcript 解析 + 统计 + 死重 + 规则建议 (§10)
│   ├── discovery.py               # 扫描本地 skill（Claude & Codex 两套路径）
│   ├── adapters/                  # 跨工具适配层（关键！）
│   │   ├── __init__.py
│   │   ├── base.py                # 抽象: 定位skill目录/transcript/hook配置
│   │   ├── claude_code.py         # ~/.claude/* 适配
│   │   └── codex.py               # ~/.codex/* + AGENTS.md 适配
│   └── dashboard/
│       ├── server.py              # 本地只读 http 服务（标准库 http.server）
│       └── index.html             # 单文件看板 (§11.dashboard)
│
├── hooks/                         # 装进宿主的 hook 脚本（确定性，跨工具）
│   ├── claude/
│   │   └── enforce_skill.py       # UserPromptSubmit / PreToolUse for Claude Code
│   └── codex/
│       └── enforce_skill.py       # Codex 对应 hook
│
├── ticket-codex-maxxing/          # 模块一：蒸馏票（可独立发布的子产物）(§5)
│   ├── README.md                  # 署名 + 链接原文 + 一句话框架 + 60秒上手
│   ├── AGENTS.md                  # Codex 版 drop-in
│   ├── CLAUDE.md                  # Claude Code 版 drop-in
│   └── skills/                    # 3 个配套 skill（双格式见 §5.5）
│       ├── verified-goal/
│       ├── chief-of-staff-heartbeat/
│       └── memory-as-files/
│
├── examples/                      # 示例数据，供测试与演示
│   ├── skills/                    # 几个好/坏 skill 样本（喂给 verify）
│   ├── transcripts/               # 合成 transcript（喂给 usage）
│   └── rules.sample.yaml
│
└── tests/                         # pytest（每模块的验收测试，§12）
    ├── test_verify.py
    ├── test_rules.py
    ├── test_usage.py
    └── test_adapters.py
```

> **note**：`ticket-codex-maxxing/` 既是控制平面的"第一批已验证内容"，也可以**单独拎出去作为一个独立仓库发布**（蒸馏票要趁热）。所以它对控制平面只有"数据依赖"，没有"代码依赖"——保持解耦。

---

## 5. 模块一：codex-maxxing 蒸馏票

### 5.1 来源、署名与版权红线（必须先读）

- **源**：Jason Liu（jxnl，OpenAI Codex 团队）《Codex-maxxing》，2026-05-10，原文 https://jxnl.co/writing/2026/05/10/codex-maxxing/
- **GitHub 名头核验**：`codex-maxxing` 仓库名当前**无人注册**（GitHub API 精确搜索 0 结果）；这块是空地。
- **版权红线（硬性）**：
  1. 蒸馏 = 把原文的"观察/方法"用**我们自己的话**重构成**可执行规则**，不是搬运。
  2. **原文里的示例 prompt（Chief of Staff 那段、退款那段、目标那段）一律改写**，不得逐字复制。
  3. 每个产出文件头部必须有署名块：`# 灵感来源：Jason Liu《Codex-maxxing》(2026-05-10) <链接>。本文件是其方法的可执行蒸馏，非原文转载。`
  4. 全文最多保留一句极短引用（< 15 词）并加引号。建议保留这句框架金句：`"Ambition without verification is just a wish."`（用于解释 Goals 原语）。

### 5.2 九个原语 → 可执行规则/产出物 映射

> 这是蒸馏的核心：把"经验"变成 agent 能照着做的"规则/技能"。每条都要写成"何时触发 + 做什么"。

| # | 原语 | 一句话本质 | 蒸馏成什么（落到 AGENTS.md/CLAUDE.md 规则 or skill） |
|---|---|---|---|
| 1 | Durable threads（长青线程） | 每个重要工作流钉一个可压缩、长期存续的线程 | 规则："重要工作流要钉长青线程而非开新会话；定期compaction"。+ 文档说明 Cmd-1~9 跳转。 |
| 2 | Voice input（语音输入） | 把未加工的思考喂给 agent | 规则："接受并善用粗糙/口语化输入，不要求用户先组织好语言；可从转录稿起手"。 |
| 3 | Steering（实时转向） | 任务进行中随时插入指令、排队意图 | 规则："执行长任务时，把后续意图排成队列，不必等每步完成；允许中途修正"。 |
| 4 | Memory = 文件（记忆即文件） | 把线程学到的东西序列化成可 diff 的文件 | **skill: `memory-as-files`**（见 §5.5）。规则："重要上下文写进 vault 文件并入 git，用 diff 当记忆审查面"。 |
| 5 | Computer/Browser use | 区分本地网页/登录态/纯 GUI 三种触达 | 规则：明确 `$browser`（本地网页）/`@chrome`（登录态多标签）/`@computer`（纯GUI）的选择标准 + 常用连接器。 |
| 6 | Remote control（远程遥控） | 长任务可从手机继续遥控 | 规则（信息性）："长任务设计成可暂停/可远程接管；到决策点再要人介入"。 |
| 7 | Heartbeats（心跳） | 线程自调度的周期任务 | **skill: `chief-of-staff-heartbeat`**（见 §5.5）。规则："周期性监控类工作交给心跳，跨工具循环；草稿不自动发送"。 |
| 8 | Goals（带验证的目标） | 长任务要有可验证的成功判据 | **skill: `verified-goal`**（见 §5.5）。规则金句："没有验证的雄心只是许愿"——任何长任务先定 oracle（测试/判据）。 |
| 9 | Side panel（侧边栏/工件） | 在侧栏 inspect/操作/审改工件，输出优先 HTML | 规则："产出优先做成可交互的单文件 `index.html` 而非纯 Markdown；小工件零服务器优先"。 |

### 5.3 `AGENTS.md`（Codex 版）规格

**目标**：用户把这一个文件丢进项目根（或 `~/.codex/`），Codex 立刻获得"codex-maxxing 式"的工作回路默认值。

结构要求（实现 agent 照此写，全部用原创措辞）：

```markdown
# 灵感来源：Jason Liu《Codex-maxxing》(2026-05-10) https://jxnl.co/...
# 本文件是其方法的可执行蒸馏，非原文转载。

## 工作回路默认值（Operating Loop Defaults）
- 长青线程：重要工作流钉长期线程，定期 compaction，而不是反复开新会话。
- 输入：接受口语化/粗糙输入与转录稿；不要求用户先组织好措辞。
- 转向：执行长任务时把后续意图排队，允许中途修正，不必等每步完成。

## 记忆即文件（Memory as Files）
- 重要上下文写进 vault（people/ projects/ notes/ TODO.md），入 git，用 diff 复核。
- 触发：当了解到新的人/项目进展/关闭一个 open loop 时，更新对应文件。

## 工具触达分层
- $browser=本地网页检查；@chrome=登录态多标签；@computer=纯GUI才用。
- 常用连接器：$slack / $gmail / $calendar。

## 周期任务（Heartbeats）
- 监控类工作用周期心跳；草稿默认"只起草不发送"，由人确认。

## 带验证的目标（Verified Goals）
- 任何长任务先定义可验证的成功判据（oracle），如"必须通过原库全部单测"。
- 信条："没有验证的雄心只是许愿。"

## 产出物
- 输出优先做成可交互的单文件 index.html（零服务器优先），而非纯 Markdown。
```

> 约束：保持 < 約 80–120 行、可直接粘贴即生效；每条都是"可执行规则"而非散文。这正是 Karpathy 那个 70 行 / 4 条爆款的"形状"。

### 5.4 `CLAUDE.md`（Claude Code 版）规格

- 内容**语义等价** §5.3，但适配 Claude Code 术语：把 Codex 专有的 `$browser/@chrome/@computer/$slack` 这类语法，替换为 Claude Code 对应能力的描述（如"使用浏览器工具/计算机使用/连接的 MCP"），并指向 Claude 的 skills/hooks 机制。
- 凡是 Codex 独有、Claude 无对应的能力（如 Codex pets），在 CLAUDE.md 里**省略**而不是硬译。
- 同样保留署名块与"记忆即文件 + 带验证目标 + 输出优先 HTML"这些**工具无关**的核心规则。
- **跨工具差异处理（Rule 6：冲突不取平均）**：当两套工具能力不一致时，**分别给出各自最优写法**，并在 `ticket-codex-maxxing/README.md` 的对照表里标明差异，不要写一份"最大公约数"的含糊版本。

### 5.5 三个配套 skill 规格（双格式：Claude skill + Codex skill）

> 每个 skill 出两份：`SKILL.md`（Claude Code 格式：YAML frontmatter `name`/`description`，description 必须写成触发器"use this skill when you need to …"）与 Codex 对应格式。两者正文共享，只是 frontmatter/装载方式不同。每个 skill 都要**能过本项目自己的质量门 verify（§7）**——吃自己的狗粮。

#### skill A：`verified-goal`（带验证的目标）
- **何时触发**：用户给出一个大/长任务但没给可验证的完成判据时。
- **做什么**：引导/自动产出一个"目标卡"——目标 + 明确的 oracle（测试命令、可比对的基准、可量化的验收），并在执行末尾真正运行该 oracle 来判定"完成"。
- **产出**：`goal.md`（目标 + 判据 + 验证命令 + 结果）。
- **反模式提示**：拒绝"实现这个 md 计划"式的弱目标。

#### skill B：`chief-of-staff-heartbeat`（周期助理心跳）
- **何时触发**：用户想要"周期性盯着某个来源并在有动静时行动"。
- **做什么**：生成一个心跳任务配置（cadence + 监控源 + 触发条件 + 动作），动作默认"只起草不发送 / 只汇总不执行"。
- **落地**：复用本机的 scheduled-task 能力或宿主的定时机制；**示例 prompt 全部原创改写**（不得抄原文那段 Slack/Gmail 文案）。
- **安全**：任何"发送/购买/提交"类动作必须留给人确认（对齐本项目安全规则）。

#### skill C：`memory-as-files`（记忆即文件 vault）
- **何时触发**：跨会话需要持久、可审查的上下文记忆时。
- **做什么**：初始化/维护一个 vault（`TODO.md` + `people/ projects/ notes/`），约定 agent 在了解新信息时更新对应文件；vault 入 git，用 diff 作为"记忆审查面"。
- **产出**：vault 脚手架 + 一份维护规则（写进该 skill 的 SKILL.md）。

### 5.6 模块一验收标准

- [ ] `AGENTS.md` 与 `CLAUDE.md` 均 < 120 行、可直接粘贴、每条是可执行规则、含署名块。
- [ ] 三个 skill 各有双格式文件，且**全部通过 `scp verify`（§7）**。
- [ ] 全仓库无任何 ≥15 词的原文照搬（用脚本对原文做 n-gram 查重，见 §12 测试）。
- [ ] `ticket-codex-maxxing/README.md` 有：一句话框架、署名+链接、60 秒上手、Codex/Claude 差异对照表。

---

## 6. 模块二~六总览：完整控制层

> 实现顺序建议：**discovery → verify → registry → usage → rules/hooks → dashboard**。前四个是纯本地读+分析（低风险、可快速验收），后两个涉及注入宿主行为（需真机验证）。

先定义贯穿各模块的**统一 skill 标识**：`tool:scope:name`，例如 `claude:user:pdf`、`codex:project:db-migrate`。所有模块用它当主键。

---

## 7. 模块二：质量门 `verify`（§ 对应 `verify.py`）

**职责**：判定一个 skill 是否"已验证、可信任、可被规则绑定"。这是"让每个 skill 成为成熟产品"的关口。

### 7.1 输入/输出
- 输入：一个 skill 目录（含 `SKILL.md` + 可选脚本）。
- 输出：`VerifyResult{ id, passed: bool, score: int, checks: [{name, level, msg}], badge }`，并可写回注册表（§8）。
- 退出码：CLI `scp verify <path>` 通过=0，有 `error` 级=1（**失败要响**，Rule 11）。

### 7.2 检查项（分 `error` / `warn` / `info` 三级）

| 检查 | 级别 | 说明 |
|---|---|---|
| 结构完整 | error | 有 `SKILL.md`，frontmatter 含 `name` + `description`。 |
| description 是触发器 | warn | description 应是"use when…"式触发语，而非功能罗列（直接关系到 50% 触发率问题）。给出 lint 建议。 |
| 描述长度/SKILL.md 体积 | warn | SKILL.md 控制在 ~500 行内；description 过长/过空都告警。 |
| **脚本安全扫描** | error | 静态扫描脚本中的高危模式：`curl\|sh`、`wget\|...\|bash`、`rm -rf`、`sudo`、`eval`、明文外发网络地址、`base64 -d\|sh` 等。命中=拦截。 |
| 触发关键词缺失 | info | 从 description 抽取触发关键词，供 usage/rules 复用。 |
| 新鲜度 | info | 依据文件 mtime/历史，标记"X 天未更新"。 |

> **重要边界**：安全扫描是**静态、保守**的——宁可误报让人看，不可漏报。它不执行任何脚本。任何"自动修复"都不在 P0 范围。

### 7.3 徽章
- `verified`（无 error 且 score ≥ 阈值）、`needs-review`（有 warn）、`blocked`（有 error）。
- **只有 `verified` 的 skill 允许被规则引擎绑定为"强制触发"**（§9）。这是质量门与规则引擎的硬连接。

### 7.4 验收标准
- [ ] 对 `examples/skills/` 里的好样本→`verified`；坏样本（多行无触发 description + `curl|sh` + `rm -rf` + `sudo`）→`blocked` 且每条命中都列出。
- [ ] 退出码正确；纯静态、不执行脚本。

---

## 8. 模块三：注册表 `registry`（§ 对应 `registry.py`）

**职责**：所有已发现 skill 的单一事实来源（清点 + 信任状态 + 一句话摘要 + 用量摘要）。

### 8.1 存储
- 本地 JSON：`~/.skill-control-plane/registry.json`（路径可配）。纯本地，无云端。
- 每次 `scp scan` 重建/增量更新。

### 8.2 schema（单条）
```json
{
  "id": "claude:user:pdf",
  "tool": "claude",
  "scope": "user",
  "name": "pdf",
  "path": "/abs/path/to/skill",
  "summary": "一句话：这个 skill 到底干嘛（由模型对 SKILL.md 生成，见下）",
  "trigger_keywords": ["pdf", "extract", "merge"],
  "verify": { "badge": "verified", "score": 86, "last_run": "..." },
  "usage": { "invocations": 12, "last_used": "...", "never_used": false },
  "freshness_days": 41,
  "duplicate_of": null,
  "enabled": true
}
```

### 8.3 一句话摘要（这里**才**用模型 —— Rule 5）
- 对每个 skill 的 `SKILL.md` 生成一行"它到底干嘛"。**这是判断/摘要任务，符合"模型只做判断"的信条。**
- 其余全部用代码：扫描、解析、去重判定、统计。

### 8.4 去重/冲突检测（用代码，不用模型）
- 对 `description`/`trigger_keywords` 做相似度（如 TF-IDF / 简单 token Jaccard）找高度雷同对 → 标 `duplicate_of`。高相似的两个 skill 会让模型选错，是 context rot 的直接来源。

### 8.5 验收标准
- [ ] `scp scan` 能同时发现 Claude 与 Codex 两套路径下的 skill（经 `adapters/`）。
- [ ] 去重能把"两个近乎同义的 skill"标出来。
- [ ] 摘要这一步可被 `--no-llm` 关闭（离线可用）。

---

## 9. 模块四：规则引擎 `rules` + hooks（§ 对应 `rules.py` + `hooks/`）

**职责**：实现"在特定情况下，必须调用某个已验证 skill"。**确定性、代码决定、不让 LLM 猜**。

### 9.1 规则 schema（`rules.yaml`）
```yaml
version: 1
rules:
  - id: sql-migrate
    description: 改 SQL 时强制走迁移 skill
    when:                      # 条件（AND）；任一类可省略
      file_glob: ["**/*.sql"]  # 命中变更/打开的文件
      intent_keywords: ["migration", "alter table", "建表"]
      task_type: ["edit"]      # 可选
      git_status: ["staged"]   # 可选
    require:
      skill: "claude:user:db-migrate"   # 必须是 verified 的
      mode: "enforce"          # enforce=强制注入；suggest=仅提示
    message: "检测到 SQL 变更：必须先用 db-migrate skill 评估迁移安全。"
```

- **条件类型（全部可代码判定）**：`file_glob`、`intent_keywords`、`task_type`、`git_status`、`dir`。
- **动作**：`enforce`（注入"你必须先 Skill(x)"）或 `suggest`（软提示）。
- **约束**：`require.skill` 必须在注册表中且 `badge == verified`，否则 `scp rules validate` 报错（**失败要响**）。

### 9.2 hook 落地（跨工具）

> hooks 是宿主原生的确定性扩展点——"每当 X 就总是 Y"本质就是 hook。我们只写 hook 脚本，让用户把它接进自己的宿主配置（README 给步骤）。

| 宿主 | 接入点 | 脚本 | 行为 |
|---|---|---|---|
| Claude Code | `UserPromptSubmit` | `hooks/claude/enforce_skill.py` | 在模型看到 prompt 前，按 `rules.yaml` 匹配当前上下文，命中则**注入**"必须评估并激活 Skill(x)"。 |
| Claude Code | `PreToolUse`（P1） | 同上 | 工具开火前校验，必要时阻止"绕过该 skill"的调用。 |
| Codex | 对应 hook 机制 | `hooks/codex/enforce_skill.py` | 同语义，适配 Codex 的 hook/配置格式。 |

- hook 脚本必须：**纯本地、快（<100ms 量级）、零网络、读 `rules.yaml` + 当前上下文**。
- hook 只注入"指令文本"，**不直接执行 skill**——真正调用仍由宿主完成；这样既确定性触发，又不破坏宿主沙箱与安全边界。
- **跨工具差异（Rule 6）**：两个宿主的 hook 输入/输出协议不同，分别实现，公共匹配逻辑放 `rules.py` 复用，适配差异放 `adapters/`。

### 9.3 验收标准（逻辑层可在沙箱验证；端到端需真机）
- [ ] 命中场景：给定 `rules.yaml` + 一个"改 *.sql"的上下文 → hook 输出含强制 `Skill(db-migrate)` 指令。
- [ ] 不相关场景：上下文无关 → hook 静默（无注入）。
- [ ] `rules validate`：引用未验证 skill → 报错并指出。
- [ ] **真机触发率实验（P1，关键）**：接进 `~/.claude/settings.json`，用 1~2 个真 skill 测 before/after 触发率，记录到 `DECISIONS.md`。**这是整个项目成立与否的核心实验。**

---

## 10. 模块五：用量闭环 `usage`（§ 对应 `usage.py`）

**职责**：从本地 transcript 解析真实用量，驱动死重清理 + 规则建议。**这是"零摩擦自动规则"的引擎。**

### 10.1 数据源（已验证可解析）
- **Claude Code**：`~/.claude/projects/<项目>/<session>.jsonl`，每行 JSON，`tool_use` 块带 `name`/`input`/时间戳。skill 调用可从中解析。
- **Codex**：经 `adapters/codex.py` 定位其会话/历史存储（实现期确认确切路径与格式，记入 `DECISIONS.md`）。
- 全部本地文件，无需任何云端权限。

### 10.2 产出
1. **用量统计**：每个 skill 的调用次数、最近使用、时间分布；标出 `never_used`（死重）。
2. **死重清单**：从没被调用过的 skill → 建议禁用/归档。
3. **规则建议**（核心）：检测"用户反复在某条件下手动调用某 skill"的模式 → 生成 `rules.yaml` 草案写入 `suggestions.json`，等用户在看板一键确认。
   - 例：发现"每次编辑 `*.sql` 后 N 次里有 M 次手动调了 `db-migrate`"→ 建议一条 `file_glob: *.sql → enforce db-migrate`。
4. **触发率度量**：规则上线后，度量"命中规则的场景里 skill 实际被触发的比例"，回灌看板形成闭环。

### 10.3 约束
- 解析要对**格式缺失/损坏行**鲁棒（跳过坏行并计数，不崩溃）。
- 模式识别用**代码**（频次/共现统计），不用模型（Rule 5：路由/确定性变换用代码）。

### 10.4 验收标准
- [ ] 对 `examples/transcripts/` 合成数据：调用次数统计准确、死重识别准确。
- [ ] 能从合成的"反复手动调用"模式中产出至少一条规则草案。
- [ ] 坏行不导致崩溃。

---

## 11. 模块六：本地只读看板 `dashboard` + CLI

### 11.1 看板（`dashboard/index.html` + `server.py`）
- **形态**：一条命令 `scp dashboard` 在本机起一个**只读** http 服务，浏览器打开读本地 `registry.json` / `usage` / `suggestions.json`。**不要登录、不要部署、不要写云端。**
- **页面（P0 最小集）**：
  1. **Skill 清单**：每个 skill 一行——名称 + 一句话摘要 + 徽章(verified/needs-review/blocked) + 用量 + 新鲜度 + 启用开关状态。
  2. **死重区**：never_used + duplicate_of 列表。
  3. **规则建议区（零摩擦闭环的关键）**：展示 `suggestions.json` 的规则草案，每条一个"确认"按钮（确认动作见下）。
  4. **before/after**：规则上线前后触发率对比（演示用，能截图）。
- **技术**：单文件 HTML + 原生 JS，CDN 引 Chart.js（仅此一个外部依赖）。**禁止 localStorage 之外的浏览器存储**做持久化；持久化一律走后端写本地文件。
- **"只读"的例外**：看板本身只读展示；"确认规则/启用禁用"这类**写操作**通过本地 `server.py` 的受限端点落到本地文件（仅本机、仅这几个白名单操作），不算违反"只读浏览"。实现时把读/写端点分清楚并在 README 说明。

### 11.2 CLI（`cli.py`，命令一览）

| 命令 | 作用 |
|---|---|
| `scp scan` | 发现所有 skill，重建注册表（含摘要、去重）。 |
| `scp verify <path|--all>` | 跑质量门，写回徽章。 |
| `scp usage [--since N]` | 解析 transcript，出用量 + 死重 + 规则建议。 |
| `scp rules validate` | 校验 `rules.yaml`（引用的 skill 是否 verified 等）。 |
| `scp rules test <ctx>` | 用一个模拟上下文测哪些规则命中、会注入什么（离线验证 hook 逻辑）。 |
| `scp dashboard` | 起本地看板。 |
| `scp doctor` | 一键体检：装在哪、宿主是否接了 hook、注册表健康度。 |

- 所有命令**离线可跑**（`--no-llm` 时摘要降级为"取 description 首句"）。
- 输出对人友好；`--json` 出机器可读。

### 11.3 验收标准
- [ ] `scp scan && scp verify --all && scp dashboard` 三条命令能跑通，看板显示真实本地数据。
- [ ] 看板"确认规则"按钮能把一条草案写进 `rules.yaml`。
- [ ] 全程零网络（除可选的摘要 LLM 调用与 Chart.js CDN）。

---

## 12. 测试策略（Rule 8：测意图，不只测行为）

- 每个模块的 `tests/test_*.py` 用 `examples/` 里的固定样本，断言要编码"为什么"：
  - `test_verify`：断言**带 `curl|sh` 的脚本必须被 `blocked`**——因为放行它就等于让控制平面变成攻击面（这才是这条测试存在的理由，注释里写明）。
  - `test_rules`：断言**引用未验证 skill 的规则必须校验失败**——因为"强制触发未验证 skill"违背产品核心承诺。
  - `test_usage`：断言**坏行被跳过且计数**、死重识别准确。
  - `test_adapters`：断言 Claude/Codex 两套路径都能被发现。
- **版权查重测试**：写一个脚本对 `ticket-codex-maxxing/` 全部文本与原文做 n-gram（如 n=15 词）比对，**任何 ≥15 词重叠即测试失败**。这把版权红线变成 CI 可验证项。
- 测试必须能"在业务逻辑变错时失败"。若一条测试无论实现对错都通过，删掉重写。

---

## 13. MVP 范围切分（P0 一下午 / P1 / P2）

### P0（目标：一下午能跑、能截图、能发出去）
1. `ticket-codex-maxxing/`：`AGENTS.md` + `CLAUDE.md` + 3 个 skill（双格式）+ README（§5）。**这部分本身就能作为蒸馏票独立发布。**
2. `discovery` + `registry`（含一句话摘要、去重）+ `verify`（质量门含安全扫描）。
3. `usage`：用量统计 + 死重清单（规则建议可放 P1）。
4. `scp dashboard` 最小看板：清单 + 徽章 + 死重 + 用量。
5. README：一句话钩子（50%→接近100%）+ 60 秒上手 + before/after 占位。

### P1（目标：闭环成立 + 核心实验）
6. `rules` 引擎 + `hooks/claude/enforce_skill.py`（`UserPromptSubmit`）。
7. `usage` 的**规则建议**生成 + 看板"一键确认"写回 `rules.yaml`。
8. **真机触发率实验**（§9.4）：接进 Claude Code，测 before/after，写进 README 当卖点。

### P2（扩张）
9. `hooks/.../PreToolUse` 拦截"绕过该 skill"的调用。
10. Codex hook 完整打通 + Codex transcript 解析。
11. 上下文 X 光 / MCP 体积审计（控制平面的"兄弟"功能，作为后续扩张）。

> **不要在 P0 做**：自动修复 skill、云端同步、账号体系、重前端框架、MCP 审计。砍掉一切非必要（Rule 2）。

---

## 14. 给实现 agent 的执行顺序（照此分阶段，每步自检）

```
阶段 0：脚手架
  - 建仓库结构(§4)、pyproject、LICENSE(MIT)、空的 DECISIONS.md
  - 确认 `scp --help` 能跑

阶段 1：发现与注册（纯读，低风险）
  - 实现 adapters/base + claude_code（先 Claude，Codex 标 TODO）
  - 实现 discovery + registry（先 --no-llm 版摘要）
  - 自检：scp scan 能列出本机真实 skill   ← checkpoint，结果写 DECISIONS.md

阶段 2：质量门（这是与"成熟产品"承诺直接挂钩的模块）
  - 实现 verify（结构/触发器lint/安全扫描）
  - 写 examples/skills 好坏样本 + test_verify
  - 自检：好样本 verified、坏样本 blocked

阶段 3：用量
  - 实现 usage（解析 Claude JSONL → 统计 + 死重）
  - 写 examples/transcripts + test_usage
  - 自检：统计/死重准确、坏行不崩

阶段 4：看板 P0
  - server.py + index.html（清单+徽章+死重+用量）
  - 自检：scan→verify→dashboard 三连通

阶段 5：蒸馏票（可与 1–4 并行，无代码依赖）
  - 按 §5 写 AGENTS.md/CLAUDE.md/3 skill/README
  - 让 3 个 skill 过 verify；跑版权 n-gram 查重测试
  - 自检：无 ≥15 词照搬、全部 verified

阶段 6（P1）：规则引擎 + hook + 闭环 + 真机实验
  - rules.py + hooks/claude/enforce_skill.py
  - usage 规则建议 + 看板一键确认
  - 真机触发率 before/after 实验 → 写进 README

每个阶段结束：更新本仓库 README 的"进度"，在 DECISIONS.md 记下取舍与意外。
失败/跳过任何子项 → 不得标记该阶段完成（Rule 11）。
```

---

## 15. 风险与诚实边界（必须保留在交付物里）

1. **平台吸收风险（最大）**：Anthropic/OpenAI 手握 hooks + 允许/拒绝名单 + 企业治理叙事，可能自己出原生"skill 规则"。对策：**跨工具**（Codex+Claude 都吃）、**做得快做得深**、占住它短期不一定做的层——自动生成规则 + 质量门 + 用量学习的易用性。
2. **触发率提升尚未真机坐实**："50%→接近100%"是核心论点，但只在逻辑层成立；**P1 的真机实验是 go/no-go 关口**。若实验不达预期，整个"强制触发"卖点要重估——这点必须诚实写进 README，不要预先吹成既成事实。
3. **规则太死会变脆、惹人烦**：价值在"好默认 + 易写 + 从用量学"，不是把一切强制。默认多用 `suggest`，`enforce` 留给用户明确确认的高价值规则。
4. **"优质/已验证"难做到客观**：质量门是"安全扫描 + 触发器 lint + 结构 + 用量信号"的组合启发式，不是真理。徽章语义要诚实（verified ≠ 绝对安全）。
5. **蒸馏票是彩票**：病毒性不可制造；codex-maxxing 趁热但可能很快冷却。当作低成本非对称下注，不押全部预期。
6. **版权**：见 §5.1，用 CI 查重把红线变成可验证项。

---

## 16. 附录 A：竞品差异速查（写进 README 的对照表来源）

| 项目 | 星 | 是什么 | 它**不**做的（=我们的空位） |
|---|---|---|---|
| ccusage | 14.2k | 成本/用量统计 | 不治理、不强制触发、不质量门 |
| claude-code-router | 33.9k | **模型**路由 | 不是 skill 路由 |
| claude-skills 等合集 | 15.3k | skill **内容库** | 发现/安装，非治理/编排 |
| skill-router | 6 | 让模型自路由（提示工程） | 非代码确定性、无注册表、无质量门 |
| token-optimizer | 13 | 一次性 audit（**AGPL，不可复用**） | 无强制触发、无质量门、无闭环 |
| skills-janitor | 12 | 审计/用量/查重 | 只报告不强制、无规则引擎、无 hook |

**我们的 4 条精确差异**：① 用 hook 做**代码级确定性强制触发**（非靠模型自觉）；② **质量门 + 已验证才可绑定**；③ **从用量自动生成规则**（零摩擦闭环）；④ **跨工具 + 可视看板**把抽象价值具象化。

## 17. 附录 B：可复用/不可复用清单（许可证）

- ✅ 可参考/复用（MIT）：`skills-janitor`、`claude-context-optimizer`、`ccusage`（解析 JSONL 的思路）。
- ❌ 不可复用：`token-optimizer`（AGPL-3.0，传染性，会污染我们的 MIT）。
- 复用时遵守署名与 MIT 条款；本项目自身 LICENSE = MIT。

## 18. 附录 C：关键参考链接（供实现期查证）

- Jason Liu《Codex-maxxing》原文：https://jxnl.co/writing/2026/05/10/codex-maxxing/
- Anthropic《Building Effective Agents》《Claude Code Best Practices》《Effective context engineering》（agent/上下文工程正典）
- Anthropic Agent Skills / Skill authoring best practices（description 是触发器、SKILL.md ≤500 行）
- Anthropic Claude Code hooks 文档（UserPromptSubmit / PreToolUse）
- OpenAI Codex AGENTS.md 指南 / skills 目录
- 关于触发率 ~50% 与 context rot 的社区实测文章（写 README 钩子时引用）

---

*文档结束。实现期的所有偏离与取舍，请持续记录在 `DECISIONS.md`。*
