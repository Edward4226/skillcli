# ARCHITECTURE

本文件给"想读懂代码、想加新 adapter、想加新 issue 类型"的工程师。它不复述 SPEC 的产品 vision——
那部分见 [SPEC.md](SPEC.md)；它也不解释每个取舍的来龙去脉——那部分见 [DECISIONS.md](DECISIONS.md)。
本文件只回答三个问题：**代码长什么样、数据怎么流、加东西要碰哪几个文件**。

适用版本：v0.0.1（Phase 4.5 完成；Phase 5/6 占位，见 §8）。

---

## §1 一图概览

### 1.1 端到端数据流

```
   ~/.claude/skills/*           ~/.codex/skills/*
   ~/.codex/skills.disabled/*   ~/.codex/vendor_imports/skills/skills/*
            │                              │
            └──────────┬───────────────────┘
                       ▼
         ┌─────────────────────────────┐
         │  adapters/{claude_code,     │   SkillDir / Adapter ABC
         │           codex}.py         │
         └─────────────┬───────────────┘
                       ▼
         ┌─────────────────────────────┐
         │  discovery.py               │   SkillRecord（含 frontmatter）
         │  parse_frontmatter() + 扫盘 │
         └─────────────┬───────────────┘
                       ▼
         ┌─────────────────────────────┐   ┌──────────────────┐
         │  registry.py                │   │ tagging.py       │
         │  build() → 摘要 / kw / 去重 │──▶│ assign_tags()    │
         └─────────────┬───────────────┘   └──────────────────┘
                       │
              ┌────────┼──────────┐
              ▼        ▼          ▼
       verify.py   usage.py   issues.py
        (徽章)    (用量+建议)  (派生 issue)
              │        │          │
              └────────┼──────────┘
                       ▼
         ┌─────────────────────────────┐
         │  ~/.skill-control-plane/    │
         │    registry.json            │   持久化
         │    suggestions.json         │
         └─────────────┬───────────────┘
                       ▼
         ┌─────────────────────────────┐
         │  dashboard/server.py        │   HTTP /api/{registry,
         │  dashboard/index.html       │   suggestions,tags,issues}.json
         └─────────────────────────────┘
```

### 1.2 CLI 与模块的对应

| 命令 | 入口 | 主要模块 |
|---|---|---|
| `skillcli scan` | `cli._cmd_scan` | adapters → discovery → registry → tagging |
| `skillcli verify [path\|--all]` | `cli._cmd_verify` | verify → registry（写回 badge） |
| `skillcli usage --since N` | `cli._cmd_usage` | usage → registry（写回 usage）+ suggestions.json |
| `skillcli dashboard --port N` | `cli._cmd_dashboard` | dashboard.server（读 registry/suggestions，派生 tags/issues） |
| `skillcli rules {validate,test}` | `cli._cmd_rules` | **Phase 6 TODO**（见 §8） |
| `skillcli doctor` | `cli._cmd_doctor` | **TODO 占位** |

### 1.3 三个外部不变量

- 注册表唯一 ID 格式：`tool:scope:name`（discovery.py:63 `_make_id`）。这是跨模块主键。
- 注册表落点：`~/.skill-control-plane/registry.json`（registry.py:16）。
- 建议落点：`~/.skill-control-plane/suggestions.json`（usage.py:25）。

---

## §2 9 个模块各干嘛

> 每条 ≤ 100 字。完整接口看源码；这里只标"它是什么 + 它的关键决策点 + 你会改它的时候要碰的行"。

### 2.1 `cli.py` — 入口调度（339 行）

argparse 注册 6 子命令，每个 `_cmd_*` 函数延迟 import 自己模块，避免冷启动慢。
`scan` 调用 ClaudeCodeAdapter + CodexAdapter 同时扫；`usage` 仅 Claude 扫，Codex 标 source=unsupported（cli.py:178-184）。
全部命令支持 `--help`；`rules`/`doctor` 是 stub，打"未实装"返 2。

### 2.2 `adapters/` — 跨工具抽象层（4 文件）

- `base.py:39 Adapter` ABC 定义 4 个抽象方法：`skill_dirs / transcript_files / parse_skill_invocations / hook_config_path`。
- `claude_code.py` 扫 `~/.claude/skills/`，transcript 找 `~/.claude/projects/<proj>/*.jsonl`。
- `codex.py` 扫 `~/.codex/{skills, skills.disabled, vendor_imports/skills/skills}/`，三种 scope；`hook_config_path()` 返 None（Phase 6 缺口）。

详见 §4。

### 2.3 `discovery.py` — 扫盘 + 解 frontmatter（97 行）

无 PyYAML，用 `_FRONT_RE` + `_LINE_RE`（discovery.py:14-15）自己解。
只支持单层 `key: value`；多行 block scalar 不解析，但**显式标 `description_is_block=True`**（discovery.py:46）——
这是 Phase 2 verify 的关键 lint 输入（block scalar 会被 YAML 解析器截空 → 触发率断崖）。

### 2.4 `registry.py` — 单一事实表（259 行）

`RegistryEntry`（registry.py:44）是核心 schema。`build()` 流程：摘要（取 description 首句，
registry.py:72 `summarize_no_llm`）→ 触发关键词抽取（中英双语正则）→ token Jaccard 去重
（registry.py:121 `find_duplicates` 阈值 0.6）→ 自动 tag（延迟 import tagging）。
JSON 持久化带 `saved_at` 时间戳供看板显示。

### 2.5 `verify.py` — 5 项静态检查 + 三档徽章（261 行）

5 检查：structure（error）/ trigger_style / description_length / size / security_scan。
评分：`100 − 50×error − 15×warn`（下限 0）。徽章：error→blocked / warn→needs-review / 全过→verified。
关键调参在文件头常量段（verify.py:21-66）：`SCANNABLE_EXTS` 白名单 + `EXCLUDED_DIR_PARTS` 黑名单 + `DANGER_PATTERNS`。

### 2.6 `usage.py` — 用量闭环（335 行）

三件事：① `parse_claude_invocations` 流式解析 Claude JSONL，attach cwd/user_prompt 上下文；
② `count_implicit_mentions` text-scan 启发式（≥5 字符 + 词边界 + per-session 计数，usage.py:178-186）；
③ `mine_rule_suggestions` 按 cwd 集中度挖规则草案（≥3 次 + ≥50% 同 cwd → suggest，usage.py:270）。
Codex 不参与统计，由 cli 层标 source=unsupported。

### 2.7 `tagging.py` — 词频自动 tag（86 行）

`derive_global_tags` 数全表 trigger_keywords 频次，过滤 `_BLACKLIST`（tagging.py:24-37），
top 15 + ≥3 次的进全局 tag 表。`assign_tags` 副作用回填到 `entries[*].tags`。
**纯启发式、无 LLM**——同义词不会合并（"pdf" / "文档" / "document" 分开计）。

### 2.8 `issues.py` — 派生式问题清单（196 行）

`Issue{skill_id, severity, type, why, how_to_fix}`（issues.py:24）。
5 种 type：security（高）/ trigger_style（中）/ duplicate（中）/ dead（低）/ stale（低）。
**纯函数**，不存盘——每次看板加载实时算。`_suggest_trigger_rewrite`（issues.py:163）
用 entry 的 trigger_keywords 拼"建议改写模板"，让用户不对着错误信息发呆。

### 2.9 `dashboard/` — 本地只读看板（server.py 145 行 + index.html 1210 行）

`server.py` 是 stdlib `http.server`，5 个 GET 端点（`/api/registry|suggestions|tags|issues|health`）+ `/index.html`，
**完全没有 `do_POST`**（server.py:67）——任何 POST 自动返 501。
`index.html` 三 tab（overview/library/issues）+ Chart.js CDN + 内联 CSS/JS，零构建链。

---

## §3 关键数据结构

> 全部是 `@dataclass`，没有继承层级。这里给主键、字段、出处。

### 3.1 `RegistryEntry` — registry.py:44

```
id              "claude:user:pdf"            # 主键，格式 tool:scope:name
tool            "claude" | "codex"
scope           "user" | "project" | "vendor" | "disabled"
name            从 frontmatter.name 取，缺则目录名
path            绝对路径（str）
summary         description 首句（≤140 字符）
description     完整 description（Phase 4.5 加，供搜索 + facet）
trigger_keywords [str]                       # ≤8 个，中英双语抽取
verify          VerifyState
usage           UsageState
freshness_days  目录 mtime → 今天差天数
duplicate_of    str | None                   # 指向 canonical id
enabled         bool
tags            [str]                        # tagging.assign_tags 回填
```

### 3.2 `VerifyState` / `VerifyResult` — registry.py:22 + verify.py:87

`VerifyState` 是注册表里持久化的"上次跑的徽章"：`{badge, score, last_run}`。
`VerifyResult` 是 verify 运行时的完整产物：`{id, badge, score, checks: [CheckResult]}`，
其中 `CheckResult{name, level, passed, msg}`（verify.py:79）。两个不是同一个东西——
后者用于 CLI 详细打印，前者只存徽章 + 分数。

### 3.3 `UsageState` — registry.py:29

```
invocations         显式 Skill tool_use 次数
last_used           ISO timestamp | None
never_used          bool
source              "claude_jsonl" | "unsupported" | "unknown"   # Phase 3 加
implicit_mentions   text-scan 命中的会话数                        # Phase 4 加
```

`source` 字段的存在理由是诚实降级——见 §5 决策 5。

### 3.4 `Issue` — issues.py:24

```
skill_id     "claude:user:pdf"
severity     "high" | "med" | "low"
type         "security" | "trigger_style" | "duplicate" | "dead" | "stale"
why          一句话：为什么是问题（带产品后果，不是干描述）
how_to_fix   一句话：怎么修（尽量给可执行命令或模板）
```

### 3.5 `SkillInvocation` / `UsageStats` / `RuleSuggestion` — usage.py:32-58

`SkillInvocation` 是一次解析出的"曾经用过"事件，带 cwd / user_prompt 上下文（供规则挖掘）。
`UsageStats` 是聚合层（每 skill 一条）。`RuleSuggestion` 是挖出的草案，字段对齐 SPEC §9.1 的 `rules.yaml` 条目，
但 `enforcement` 默认 `"suggest"`（不强制）——用户在看板确认后才升级 mandatory。

### 3.6 `SkillDir` / `SkillRecord` / `Adapter` — adapters/base.py + discovery.py:50

`SkillDir{path, scope}`（base.py:17）是 adapter 给 discovery 的最小返回单元。
`SkillRecord` 是 discovery 给 registry 的中间结构，含解析后的 `frontmatter` 与 `skill_md_size`（供 verify 的 size lint）。
`Adapter` ABC 的 4 个抽象方法是跨工具的契约——见下一节。

---

## §4 跨工具适配：怎么加第三个 tool

### 4.1 Adapter 接口

`adapters/base.py:39 Adapter` 强制 4 个抽象方法 + 一个类属性：

```python
class Adapter(ABC):
    tool: str                                                # "claude" / "codex" / ...
    def skill_dirs(self) -> list[SkillDir]: ...              # Phase 1：扫 skill 目录
    def transcript_files(self) -> list[Path]: ...            # Phase 3：本工具的会话 JSONL
    def parse_skill_invocations(self, transcript: Path) \
        -> Iterator[ToolUseRecord]: ...                      # Phase 3：抽 tool_use
    def hook_config_path(self) -> Path | None: ...           # Phase 6：hook 配置文件
```

### 4.2 Claude vs Codex 的两个走向

**对称的部分**：两者 skill 目录都是 `<dir>/SKILL.md + 可选脚本`；frontmatter 都用 YAML 头；
discovery + registry + verify 都不用知道 tool 是什么——这就是 adapter 抽象的目的。

**不对称的部分**：

| 维度 | Claude | Codex |
|---|---|---|
| skill scope | 仅 user | user / disabled / vendor 三种 |
| transcript 行格式 | `{message: {content: [...]}, ...}` | `{timestamp, type, payload}` |
| Skill 调用 | 离散 `tool_use` 块，name="Skill" | 无离散 Skill 调用（通过 SKILL.md 注入 prompt） |
| hook | `~/.claude/settings.json` | 无 hook 入口（Phase 6 缺口） |

所以 `usage.parse_claude_invocations` 是 Claude 专用的，**不**通过 `Adapter.parse_skill_invocations`
走——因为 Codex 那个永远返回 `skill_name=None`，强行复用反而绕。Phase 3 我们选诚实降级：
`CodexAdapter` 实现 `parse_skill_invocations` 但只抽出 function_call / tool_call（codex.py:58），
不假装能数 Skill 调用。

### 4.3 实战：加一个 cursor adapter 要改的 6 处

假设 Cursor 也有 skills 和 transcript，要把它接进控制平面：

1. **新建 `skill_control_plane/adapters/cursor.py`**：继承 `Adapter`，实现 4 个方法。
   - `skill_dirs`：定位 Cursor 的 skill 目录（如 `~/.cursor/skills/`），返回 `[SkillDir(...)]`。
   - `transcript_files`：定位 Cursor 的会话日志。**如果没有可解析 transcript，返 `[]` 即可。**
   - `parse_skill_invocations`：能解就解，不能就空生成器（不要 raise）。
   - `hook_config_path`：有 hook 机制就指向；没有就 `return None`（与 Codex 同）。

2. **在 `adapters/__init__.py` 导出**：加 `from .cursor import CursorAdapter` 和 `__all__` 一项。

3. **在 `cli.py:_cmd_scan` 的 adapters 列表加一条**（cli.py:35）：
   ```python
   adapters = [ClaudeCodeAdapter(), CodexAdapter(), CursorAdapter()]
   ```

4. **决定 usage 怎么办**：
   - 如果 Cursor 的 transcript **有离散 Skill 调用**：在 `usage.py` 加一个 `parse_cursor_invocations`
     （复制 `parse_claude_invocations` 的形状，改字段名），在 `cli._cmd_usage` 里像 Claude 一样写回
     `source="cursor_jsonl"`。
   - 如果 Cursor **没有可解析的 Skill 调用**：什么都不加，在 `cli._cmd_usage` 加一个 `elif e.tool == "cursor"`
     分支，标 `source="unsupported"`，与 Codex 同（cli.py:178-184）。**诚实降级胜过假装统计。**

5. **测试**：在 `tests/test_discovery.py` 加一条断言 cursor 路径下的 skill 能被扫到（参考现有 Claude/Codex 的测试形状）。
   如果加了 usage 解析，也在 `tests/test_usage.py` 加一条"坏行不崩 + 大小写不敏感"的测试。

6. **如有 hook 机制**：等 Phase 6 `rules.py` 与 `hooks/` 落地后，在 `hooks/cursor/enforce_skill.py` 加脚本。
   现在不用做。

**注意**：discovery / registry / verify / tagging / issues / dashboard **完全不用改**。这是抽象的回报。
如果你发现你需要改它们中的任何一个，那大概率是 Adapter 接口没覆盖你的情况——优先扩 Adapter 而不是污染上层。

### 4.4 Adapter 接口当前的局限

- `parse_skill_invocations` 返 `ToolUseRecord`（base.py:30），但 `usage.parse_claude_invocations`
  没用它——直接读 JSONL 拿 cwd / user_prompt 上下文。这是已知不对齐：`ToolUseRecord` 不够富，缺 cwd。
  Phase 6 加 rules / hook 时会重审。
- `Adapter.tool` 是字符串，无 enum——加新工具时要保证唯一，但没有编译期检查。

---

## §5 设计决策表

> 表里每条都是"我们选了 X 而非 Y，因为 Z；权衡是 W"。完整历史推理在 [DECISIONS.md](DECISIONS.md)。

### 决策 1：标准库 only，不引 PyYAML / requests

**我们选**：自己写 frontmatter 正则解析（discovery.py:14-46）；http server 用 `http.server`；HTTP client 不用——本机零网络。

**而非**：装 PyYAML + requests + Flask。

**因为**：① `pyproject.toml` 的 `dependencies = []` 让 `uv tool install --editable .` / `pipx install` 装得极快、零编译；
② 控制平面是基础设施，依赖少 = 升级少 = 攻击面小；③ frontmatter 只需 `key: value` 一层，
正则足够（带宽换简洁）。

**权衡**：失去 PyYAML 的鲁棒解析能力——多行 block scalar（`description: |`）我们不解析，
只在 `description_is_block=True`（discovery.py:46）标记给 verify 警告。这正好对应 SPEC §1.1
"~50% 触发率失败"的根因之一（block scalar 被解析器截空），所以**不解析反而是对的**——
能让用户警觉，否则解出来值反而隐藏了真问题。

### 决策 2：dashboard 默认 read-only，POST 自动 501

**我们选**：`server.py` **完全不实装 `do_POST`**（server.py:67 注释 + test_dashboard.py:92-103 锁住）。

**而非**：实装 `/api/confirm-rule` 写端点让看板能改 `rules.yaml`。

**因为**：① SPEC §11.1 明说看板"只读浏览"；② 写端点意味着 CSRF / 鉴权 / 输入校验三件套——
本机服务也不能假设 localhost = trusted（浏览器其他 tab 可以发 fetch）；③ 当前没有 `rules.yaml`
要确认——规则引擎是 Phase 6。

**权衡**：失去"一键确认规则"的丝滑感。Phase 6 加 rules 时再设计写端点的协议（origin check + 白名单端点）。
现在比较 / 批量 dry-run 等"看似要写"的功能全在前端 JS 算 + 浏览器下载，零服务端写。

`tests/test_dashboard.py:92` `test_post_not_allowed` 把这个承诺锁进 CI——
未来谁不小心加了 `do_POST`，测试立刻红。

### 决策 3：tagging 是词频启发式，加 disclaimer，不用 LLM

**我们选**：`tagging.py` 数 trigger_keywords 频次，过黑名单（tagging.py:24-37），取 top 15 ≥3 次。

**而非**：调 LLM 给每个 skill 生成 1-3 个语义 tag。

**因为**：① Q3 用户拍板默认 `--no-llm`，离线 / 零密钥；② 启发式可解释（用户能看懂为什么这个 tag 出现）；
③ 真机调参 4-5 次就把信号洗干净了（DECISIONS Phase 4.5 黑名单扩到 30+ 词）。

**权衡**：同义词不合并——"pdf" / "文档" / "document" 在 tag 列表里分开计。前端 facet 多一项，
但用户多个入口找同一类 skill 也不算坏事。

**Disclaimer**：dashboard `index.html` 顶部黄条 + 每个 stat-card 副标题永远显示
"explicit=精确 / implicit=启发式可能误报"——诚实优先。

### 决策 4：`implicit_mentions` 要求 ≥5 字符名 + 词边界

**我们选**：`count_implicit_mentions(min_name_len=5)`（usage.py:178）+ `\b{name}\b` 正则
（usage.py:193）+ per-session 计数（usage.py:236-238）。

**而非**：① 任意长度名匹配；② 全文 substring 匹配；③ 每次出现 +1。

**因为**：
- "pdf" / "sql" / "qa" 这类常见词假阳性极高——用户 prompt 里随口说"qa一下"会被算成 skill 命中。
- "browse" 不应匹配 "browser"——词边界拦得住。
- 一个会话里 assistant 反复说"frontend-design"应该只算 1 次会话使用，不是 N 次（避免单会话灌水）。

**权衡**：短名 skill（如 Claude 自带的 `pdf`、`qa`）拿不到隐式信号——但这些 skill 通常是高频显式调用对象，
不靠隐式信号也能识别"非死重"。如果未来有需要，可以加白名单覆盖。

### 决策 5：Codex usage = unsupported（诚实降级）

**我们选**：`CodexAdapter.parse_skill_invocations` 不抽 Skill 调用（codex.py:58 只抽 function_call / tool_call，
skill_name 永远 None）；`cli._cmd_usage` 把所有 Codex skill 的 `usage.source` 标 "unsupported"
（cli.py:178-184），dashboard 据此**不**把它们归"死重"。

**而非**：① 强行用文本扫描假装统计；② 完全不显示 Codex skill。

**因为**：Phase 1 真机侦察确认 Codex transcript 结构是 `{timestamp, type, payload}`，
没有离散 Skill tool_use——skill 通过把 SKILL.md 内容注入 prompt 来生效，模型"使用"它的痕迹
分散在 assistant message 文字里，**没有可靠信号能数**。假装统计会让用户怀疑数据准确度
（"我明明用过怎么显示 0"），信任受损。

**权衡**：Codex 用户在看板上看到的 130 个 skill 里有 63 个标 "Codex (usage tracking not supported)"——
透明但不漂亮。是 SPEC §15 "诚实边界" 的直接落地：徽章语义要诚实。

### 附带决策（简记）

| 项 | 选了 | 因为 |
|---|---|---|
| CLI 名 | `skillcli` 而非 SPEC 写的 `scp` | OpenSSH `scp` 撞名（DECISIONS 2026-05-24 阶段 0 完成） |
| 安装方式 | `uv tool install --editable .` | `pip install -e .` 被 PEP 668 拒（Python 由 uv 管理）|
| `--no-llm` 默认 | 取 description 首句 | 零配置 / 零密钥 / 可离线（Q3） |
| Codex 提前到 P0-P1 | adapters + discovery 同步实装 Claude+Codex | 错过早期采纳曲线代价大（Q5 反转） |
| 排除 `node_modules` 等 | `verify.py:39 EXCLUDED_DIR_PARTS` | 否则 `brave-search` 等带 JS 依赖的 skill 全误报 |
| `.md/.txt` 不扫安全模式 | `verify.py:30 SCANNABLE_EXTS` 白名单 | 文档表述意图（"别用 `rm -rf /`"），脚本承载执行；混淆 = 教学型 skill 大量误判 |
| eval/exec negative lookbehind | `verify.py:60-63` | 否则 JS `regex.exec()` / `child_process.exec()` 都匹配 |
| 注册表去重阈值 0.6 | `registry.py:121 find_duplicates(threshold=0.6)` | 真机本机只抓到 1 对真重复（codex/claude 同名 frontend-design），无误报 |
| 规则挖掘 ≥3 次 + ≥50% cwd | `usage.py:270` | 阈值低会产假规则草案；用户每个草案都要看，假草案 = 注意力税 |

---

## §6 测试策略

### 6.1 框架与运行

**unittest only**——没用 pytest（`pyproject.toml` 把 pytest 放在可选 dev extras）。
理由：与"标准库 only"一致，新贡献者不需要先 `pip install pytest`。

```bash
python -m unittest discover -s tests -v
```

当前 69/69 pass（17 discovery+registry / 11 verify / 11+8 usage / 6 dashboard / 6 tagging / 10 issues）。

### 6.2 测意图非行为（每个测试断言一个产品承诺）

测试方法名直接编码承诺，docstring 写"放过这个会怎么样"。范例：

- `test_verify.test_curl_pipe_sh_blocks`：放过 = "已验证 skill" 成远程任意代码执行入口
- `test_verify.test_danger_in_md_does_not_trigger`：误报 = 教学型 skill 大量错杀
- `test_verify.test_multiline_block_description`：放过 = SPEC §1.1 触发率提升落空
- `test_dashboard.test_post_not_allowed`：放过 = 攻破"本地只读"承诺

如果一条测试无论实现对错都通过——删掉重写。这是 SPEC §12 / Rule 8 的硬要求。

### 6.3 真实 HTTPServer 端点测，不 mock

`tests/test_dashboard.py` 起 ephemeral 端口的真 `HTTPServer`（test_dashboard.py:18 `_pick_port`），
用 `urllib.request` 真请求。理由：mock 出来的端点契约只能测它自己；真起 server 才能发现
"前端硬依赖 `skills` 字段，而后端某次重构改名了"这类破裂。

### 6.4 反向测试与正向测试同等重要

`test_verify.py` 里既测"curl|sh 必须 blocked"也测"SKILL.md 里写 `Don't curl|sh` 教学例子必须 verified"。
反向测试保 verify 不会"过紧"——如果只有正向测，verify.py 改严一点就过；反向测把"严过头会教学型 skill
错杀"的代价编码进去。

---

## §7 怎么贡献

### 7.1 加一个新 adapter

见 §4.3 的 6 步清单。核心：discovery / registry / verify / tagging / issues / dashboard 不用改。

### 7.2 加一个新 issue 类型

场景示例：想加 "license_missing" 类型（skill 目录缺 LICENSE 提示）。

1. **`issues.py:21` 加 type 常量** 不是必须，type 是自由 string；但建议在文件头记一行。
2. **`issues.py:compute_issues_for_entry`** 加一个 `if` 分支。注意：
   - 选合适的 severity（high 必须处理 / med 影响触发率 / low 长期清理）
   - `why` 写产品后果（不是干描述："license 缺失会让分发 / fork 时合规风险"）
   - `how_to_fix` 给可执行模板（"在 `<path>` 加 LICENSE 文件，建议 MIT"）
3. **`tests/test_issues.py` 加测**：构造 fixture entry，断言 `compute_issues_for_entry(e)` 含一条 type=="license_missing"。
4. **dashboard 不用改**——`/api/issues.json` 端点是泛型，前端按 type 分组自动出新桶。

### 7.3 加一个 tag rule（调黑名单 / 改阈值）

- 加词：`tagging.py:24 _BLACKLIST` 集合。**注意保持 lowercase**。
- 调阈值：`tagging.py:18-19` `TOP_N` / `MIN_OCCURRENCES`。
- 加完跑 `skillcli scan && skillcli dashboard`，在看板 Library tab 的 facet 边栏看 tag 列表，验证调整效果。
- 如果改的是测试覆盖到的边界（如最小出现次数），在 `tests/test_tagging.py` 加测。

### 7.4 加新 verify 检查

`verify.py:_POST_STRUCTURE_CHECKS`（verify.py:221）是顺序列表。

1. 写一个 `_check_yourthing(path: Path) -> CheckResult` 函数。
2. 决定 level（`error` → blocked / `warn` → needs-review / `info` → 仅展示）。
3. 加到 `_POST_STRUCTURE_CHECKS` 列表。
4. `tests/test_verify.py` 加正向 + 反向各一条测试。

如果新检查涉及外部命令执行——**不要**。verify 是静态扫描（SPEC §7.2）。

---

## §8 还没建的（Phase 5/6 占位）

按 SPEC §13 的 P0/P1/P2 切分，当前完成的是 P0 范围 + Codex 提前 + Phase 4.5 UX 重做。
**还没建**：

| 模块 | SPEC 章节 | 当前状态 |
|---|---|---|
| `rules.py` | §9 | 占位（cli `_cmd_rules` 打"未实装"） |
| `hooks/claude/enforce_skill.py` | §9.2 | 未建 |
| `hooks/codex/enforce_skill.py` | §9.2 | 未建（且 Codex hook 机制本身缺口——见下） |
| `ticket-codex-maxxing/` | §5 | 未建 |
| 一键确认规则的看板写端点 | §11.1 | 未建（do_POST 故意没实装，见决策 2） |
| 真机触发率 before/after 实验 | §9.4 | 未做（go/no-go 关口） |
| `doctor` 命令 | §11.2 | stub |
| LLM 摘要（`--llm`） | §8.3 | 接受 flag 但降级到 `--no-llm`，打 stderr 警告 |

**已知 Phase 6 设计缺口**：Codex 不像 Claude 那样暴露 `UserPromptSubmit` / `PreToolUse` 等 per-prompt
拦截点（DECISIONS 2026-05-24 阶段 1 侦察），`~/.codex/config.toml` 的 `[hooks.state]` 是状态存储位
不是 hook 定义入口。`codex.py:hook_config_path()` 返 None 是诚实标记，不是 bug。
Phase 6 临近时需要重新设计 Codex 端"如何注入确定性触发"——可能要走 AGENTS.md 注入 + remote-control
事件流，比 Claude hook 弱一档。

---

## 末尾

- 历史推理与所有取舍：[DECISIONS.md](DECISIONS.md)
- 原始产品 vision 与 §3-§11 模块规格：[SPEC.md](SPEC.md)

文件内的所有行号是 v0.0.1（Phase 4.5 完成时）的快照——重大重构后请同步本文件，不要让它腐烂。
