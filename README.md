# skill-control-plane

> 你本地 skill 库的**控制平面**：用确定性规则（hook）让该用的 skill 在该用的场景**每次都触发**。
> 把社区实测的 ~50% 自动触发率推到接近 100%——⚠️ **当前仅逻辑层成立，真机实验是 P1 关口。**

🚧 **WIP（v0.0.1）**。完整规格见 [SPEC.md](SPEC.md)。

## 60 秒了解

- **痛点**：Claude / Codex 的 skill 由模型读 description 自主触发，社区实测约 50% 成功率；用户因此退回手动斜杠命令，skill 库沦为"装完就忘"的一锤子买卖。装到 100~150 个还会因 token 预算与冲突造成 context rot。
- **解法**：本地控制平面，五件套——
  - **registry** 清点 + 去重 + 一句话摘要
  - **verify** 质量门（结构 + 触发器 lint + 静态安全扫描）
  - **usage** 解析本地 transcript，统计死重 + 挖规则草案
  - **rules + hooks** `rules.yaml` 声明规则；`UserPromptSubmit` hook 命中即注入"必须 Skill(X)"
  - **dashboard** 本地只读看板，一键确认草案
- **跨工具**：Claude Code（`CLAUDE.md` / skills / hooks）+ Codex（`AGENTS.md`）。
- **MIT 开源**，目标星与影响力，不收费。

## 60 秒上手

⚠️ P0 完成前命令为 stub。完整命令将随阶段 1–4 上线。

```bash
uv tool install --editable .   # 或 pipx install -e .
skillcli --help

skillcli scan            # 阶段 1
skillcli verify --all    # 阶段 2
skillcli usage           # 阶段 3
skillcli dashboard       # 阶段 4
skillcli rules validate  # 阶段 6
```

> 备注：CLI 命名为 `skillcli` 而非 SPEC 里写的 `scp`——后者与系统 OpenSSH `scp`（secure copy）撞名。详见 [DECISIONS.md](DECISIONS.md)。

## 进度

- [x] 阶段 0：脚手架（pyproject / LICENSE / CLI stub / DECISIONS）
- [x] 阶段 1：发现与注册（discovery + registry + adapters：**Claude + Codex 同步**）
  - `skillcli scan` 在本机扫到 130 个 skill（67 Claude + 63 Codex），抓到 1 个跨工具重复
  - 17/17 unittest 通过；注册表落地 `~/.skill-control-plane/registry.json`
- [x] 阶段 2：质量门（verify：结构 + 触发器 lint + size + 静态安全扫描）
  - `skillcli verify --all` 把 130 个 skill 分到 verified 66 / needs-review 59 / blocked 5
  - 5 个 blocked **全为真实安全问题**（curl\|sh、rm -rf /、subprocess shell=True），无误报
  - 28/28 unittest（含关键反向：SKILL.md 里教学性危险示例不触发）
- [ ] 阶段 3：用量（usage：Claude JSONL **+** Codex transcript 双解析 + 死重 + 规则建议草案）
- [ ] 阶段 4：看板 P0（dashboard：清单 + 徽章 + 死重 + 用量）
- [ ] 阶段 5：蒸馏票 `ticket-codex-maxxing/`（AGENTS.md / CLAUDE.md / 3 个 skill）
- [ ] 阶段 6（P1）：规则引擎 + hooks（**Claude + Codex 双套**）+ 真机触发率实验（go/no-go 关口）

> Codex 适配为何在 P1 而非 SPEC 原定的 P2：见 [DECISIONS.md](DECISIONS.md) 2026-05-24 · Q5 反转。

## 设计信条

路由 / 策略用代码，判断 / 生成用模型。"特定情况必须调用特定 skill" 本质是确定性规则——必须用 hook 实现，不能让 LLM 猜。

## License

[MIT](LICENSE)。
