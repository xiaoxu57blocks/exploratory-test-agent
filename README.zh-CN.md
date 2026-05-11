# exploratory-test-agent

[![Status](https://img.shields.io/badge/status-POC-orange)](#)
[![License](https://img.shields.io/badge/license-TBD-lightgrey)](#%E8%AE%B8%E5%8F%AF%E8%AF%81)
[![Built with Claude Code](https://img.shields.io/badge/built%20with-Claude%20Code-7C3AED)](https://claude.com/claude-code)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](#%E8%B4%A1%E7%8C%AE)

[English](./README.md) · [简体中文](./README.zh-CN.md)

> **把工单变成一次"真正跑过"的端到端测试，再把这次跑通的轨迹归档 —— 不是事先猜出来的脚本。**

这是一个由大模型驱动的探索性测试 Agent。它读取工单 ID，在真实浏览器里端到端地把你的应用跑一遍；只有当一个测试**真的跑通**之后，它才会生成对应的 Playwright `.spec.ts`。换句话说，最终归档的脚本是一份**已知可工作路径的录像**，而不是基于假设预先写下的选择器。

基于 [Claude Code](https://claude.com/claude-code) 的 agent + skill 能力构建。每个工单都会收到一条评论，附带截图和结果摘要。

> **状态：POC（概念验证）。** 建议小批量运行，每个阶段都人工 review，凡是不可逆的动作 Agent 都会先问你。

---

## 为什么做这个

传统的 Playwright 套件是**事先**根据对 DOM 的假设写出来的。UI 一变就坏，需要不断维护。它也帮不了你做工单分诊 —— 它只能告诉你"已知流程是不是还能跑"，告诉不了你"PR #1234 这次具体的改动是不是真的实现了工单要求"。

这个 Agent 把这两件事都翻过来了：

1. **Agent 看着页面**（DOM snapshot + 截图）即时决定下一次点哪里。运行时吸收 UI 差异，远比事先把它编码下来要省事。
2. **Agent 在写测试场景前会读关联 PR 的 diff**（通过 GitHub MCP）。它测的是 PR **真正发布出来的东西**，而不是工单文本里许诺的东西。
3. **Playwright 是产物，不是运行时。** 一次运行只有在所有主场景都通过后，才会把成功的 trace 翻译成 `.spec.ts`。失败的运行只产出截图、结果和工单评论，**不**产出 spec —— 因为一份坏掉的录像比没有录像更糟。

---

## 运作方式

### 流水线

```
工单 ID ──▶ fetch ──▶ triage ──▶ [人工确认] ──▶ data-plan ──▶ spec ──▶ execute ──▶ report ──▶ 工单评论
                                                                            │              ▲
                                                                     （通过 MCP    （per-unit：
                                                                      驱动 Chrome、 一个单元跑完，
                                                                      记录每一步）   立刻给对应工单
                                                                            │      发评论）
                                                                            ▼
                                                              generated.spec.ts（仅在 PASS 时产出）
                                                                            │
                                                              可选、手动：
                                                              /archive-to-portal ──▶ <your-playwright-repo> 分支
```

### Agent 角色

| Agent | 职责 | 读取 | 写入 |
|---|---|---|---|
| `linear-fetcher` | 拉取工单正文、评论、附件 | 工单 MCP | `01-fetch.json` |
| `test-triage` | 决定每个工单要不要测；把工单聚成单元；推断用户角色 | `01-fetch.json` | `02-triage.json` |
| `test-data-planner` | 决定每个单元是新建 case 还是复用 case；按 event-type 覆盖度选 fixture；必要时通过 Drive 搜索补全 manifest | `02-triage.json`、GitHub MCP、`fixtures/manifest.json` | `02b-data-plan.json` |
| `test-strategist` | 读关联 PR 的 diff；执行三轮 gate 扫描（直接 flag 引用 → MobX/store getter 包装 → lazy import）将每个 gate 归类为 feature flag 或 data gate；写一份基于"实际发布代码"的 Requirement Spec；把 data_setup 绑到 data plan | `02b-data-plan.json`、GitHub MCP | `03-spec-<unit>.md` 加 `.json` 副本 |
| `test-executor` | 一步步驱动 Chrome；记录每一个动作；评估每个 Then。**这是 in-context runbook，不是 sub-agent** —— 由 orchestrator 在主会话中执行，因为 Chrome DevTools MCP 工具是 deferred 的，不会传递给 spawn 出来的子 agent。 | `03-spec-<unit>.json`、`02b-data-plan.json`、Chrome DevTools MCP | `trace.jsonl`、`screenshots/`、`result.json`、`generated.spec.ts` |
| `linear-reporter` | 在每个工单上发评论，附结果和截图。每次构建评论前读取 `prompts/linear-comment-template.md` 以保证格式一致。两种模式：per-unit（一个单元跑完就发一条）和聚合（运行结束时写 `05-summary.md`） | `result.json`、`prompts/linear-comment-template.md` | 工单评论 + `05-summary.md` |
| `portal-archiver` | （手动触发）把 `generated.spec.ts` 适配进你的 Playwright 仓库的目录约定，落到一个分支上 | `generated.spec.ts` | `<your-playwright-repo>` 上的分支 |

### 置信度门控

工单数据天然不完整。每条 triage 决策都带有 `high` / `medium` / `low` 置信度和一个推断出来的用户角色。**medium 和 low 决策**，以及任何角色推断不明的情况，都会显式抛给用户确认。**任何工单都不会被悄悄跳过** —— 每一个被跳过的工单都会在 `02-triage.json` 里写明原因。

### Schema 校验的产物

每次运行会落在 `artifacts/<run-id>/` 目录下（gitignored）。流水线各阶段之间是通过文件交接的，不是内存消息传递 —— 每个产物都被 `scripts/check-phase.py` 用 JSON Schema 校验过，畸形的交接会在前一阶段就把流水线截停，不会污染下游 agent：

```
artifacts/<run-id>/
├── 01-fetch.json               # 原始工单数据
├── 02-triage.json              # 每个工单的 test/skip 决策 + 置信度
├── 02b-data-plan.json          # 每单元的 case_decision（create_fresh / reuse_existing）+ fixtures
├── 03-spec-<unit>.md           # Requirement Spec（人读版本）
├── 03-spec-<unit>.json         # 同一份 spec 的机读版本（executor 读的契约）
├── 04-run-<unit>/
│   ├── trace.jsonl             # 每一步一条 JSON（schema 校验）
│   ├── screenshots/            # 每个 checkpoint 和每次失败的 PNG
│   ├── result.json             # 每个场景的 pass/fail（schema 校验）
│   └── generated.spec.ts       # Playwright 翻译，仅在 PASS 时产出
├── case-group-<N>/
│   └── case_id.txt             # 该组 executor 创建/复用的 case；同组兄弟单元会复用它
└── 05-summary.md               # 整次运行的最终汇总
```

Schema 在 [`schemas/`](./schemas/) 下；校验器是 `scripts/validate-artifact.py`。

### Review 后再归档

`<your-playwright-repo>`（正式回归套件）保持干净：除非你显式运行 `/archive-to-portal` 并 review 了 diff，否则什么都不会落进去。本仓库**永远不会主动 push 到那里**。

### 凭证不出本地

测试凭证在每次运行开始时读一次，只保存在 agent 本地内存里。截图前会做密码遮罩；密码不会出现在 `trace.jsonl` / `result.json` / `generated.spec.ts` / 聊天里的任何地方。生成的 spec 用环境变量占位符引用凭证，绝不内联具体值。

---

## 快速开始

### 前置条件

- [Claude Code](https://claude.com/claude-code)
- Node 20+（用 `npx mcp-remote`）
- Python 3.11+（脚本只用标准库）
- Chrome
- 一个工单系统 workspace 和待测工单（Linear MCP 是参考实现）
- 关联 PR 所在仓库的 GitHub PAT
- 能访问 fixture Drive 文件夹的 Google 账号
- *（可选）*用来归档通过测试的 Playwright 仓库 —— 即你的 `<your-playwright-repo>`

完整的分步骤搭建（4 个 MCP server + OAuth 流程）见 **[docs/SETUP.md](./docs/SETUP.md)**。第一次大约 20 分钟。

### 跑一次测试

在本仓库的 Claude Code 会话里：

```
> /test-tickets LIN-123,LIN-456
```

默认 **prod**。需要切到 stg 用 `--env=stg`。也支持自然语言 —— `测试 LIN-123, LIN-456` 等价于上面那条命令。

只有当 triage 不确定的时候 Agent 才会暂停等你确认 —— 比如某个工单是 medium/low 置信度，或者用户角色推不出来。一次干净的高置信度 triage 会一路跑到出报告。每个工单的评论会在它对应的单元跑完那一刻就发出去，你能实时看到每个工单的结果，不必等整批跑完。

### 查看一次运行

打开 `artifacts/<run-id>/` —— 所有产物都是纯 JSON 或 markdown。工单评论里会回链到它。

### 归档一个通过的测试

review 完 `generated.spec.ts` 之后：

```
> /archive-to-portal 2026-05-07_1430_LIN-123/unit-1
```

会按你的 Playwright 仓库的目录结构（pages/、fixtures、命名约定）适配 spec，并创建一个分支。**它不会 push** —— 你自己 review diff 然后 `git push`。

---

## 目录结构

```
.claude/
  agents/                # 每个 sub-agent 一个 .md —— 这就是它们的 prompt
  skills/                # /test-tickets、/create-case、/switch-account、/toggle-feature-flag、/archive-to-portal、/retro
  settings.json          # 入库：权限白名单、MCP servers
  settings.local.json    # gitignored：个人路径、密钥
  test-env.local.json    # gitignored：测试租户凭证
artifacts/               # gitignored：每次运行的产物
fixtures/
  manifest.json          # 入库：fixture 名 → Drive file id 映射
  cache/                 # gitignored：下载下来的 PDF
prompts/
  linear-comment-template.md  # Linear 评论格式的唯一权威来源
  strategy-template.md        # test-strategist 用的 Requirement Spec 模板
  triage-rules.md             # test-triage 的确定性分诊规则
schemas/                 # spec / trace / result 的 JSON Schema
scripts/
  attach-screenshot-to-comment.py   # 压缩 + 上传 + 删除附件的小工具
  check-phase.py                    # orchestrator 在每个阶段之间做 pre-flight
  get-fixture.py                    # 名称 → 缓存文件，走 Drive API
  google-drive.py                   # OAuth 客户端 + 查找/下载
  validate-artifact.py              # schema 校验器
  verify-mcp.sh                     # 工单 MCP OAuth 引导
docs/
  SETUP.md
CLAUDE.md                # 每次会话 agent 都会读的运行手册
```

## 硬性规则速览

- **绝不悄悄跳过。** 每个被跳过的工单必须有书面理由。每条验收标准必须映射到 spec 里的一个场景 —— 即便它需要的用户角色不是当前单元默认角色（executor 会通过 `/switch-account` 在运行中途切账号）。
- **默认用全新测试数据。** 如果单元需要特定的数据形态，planner 会带着合适的 fixture 新建一个 case，而不是去现有 case 池里翻找。只有当用户/spec 显式指定了某个 case，或者改动本身和数据无关时，才复用。
- **Spec 以 PR diff 为准，不以工单文本为准。** 当工单承诺 X 但 PR 没有发布 X，那是 Open question，不是测试场景。
- **场景执行中不许 reload，除非 spec 显式要求。** Reload 会抹掉"应该实时更新但没更新"的证据；这一类 bug 需要先有一次"不刷新就观察"的确认。
- **测试租户之外不允许任何 production 写入。** 在 `test-env.local.json` 里按环境配置。
- **Feature flag 和 data gate 要明确区分，不能靠猜。** strategist 对每个关联 PR diff 执行三轮扫描，区分 localStorage override 类 flag（由 `/toggle-feature-flag` 处理）和 `job_meta.ai_first` 这类 data gate（由创建 case 时的类型决定）。把两者混淆会导致测试静默失败。
- **工单系统里的关系字段是工单 owner 的事。** 本 Agent 只发评论，仅此而已 —— 永远不动 `relatedTo` / `blocks` / `parentId`。某些工单系统（如 Linear）会自动从评论正文里的工单 ID 文本生成 "related issue" 反向链接，所以跨工单的 workflow 上下文只放在本地 `05-summary.md` 里，永远不写进评论。

完整的 agent 端运行规则见 **[CLAUDE.md](./CLAUDE.md)**。

---

## 贡献

这是一个早期 POC，但欢迎 PR。开始前请注意几点：

- **把 agent 契约当作 API 看待。** `.claude/agents/` 下每个 sub-agent 的 `.md` 既是 prompt 也是契约 —— 改动要慎重，产物形状变了，记得同步更新 `schemas/`。
- **不要随意新增 schema。** "用 schema 校验过的 JSON 做交接"是流水线可调试性的根基。优先扩展现有 schema，而不是另起一个平行的。
- **fixture 里不能有真实客户数据。** `fixtures/manifest.json` 入库；底下的 PDF 文件放在你自己掌控的 Drive 文件夹里。提交进本仓库的 fixture 必须要么是合成数据，要么是已经公开的样例文档。
- **大改动先开 issue。** "大改动" = 新增 agent、新增 skill、破坏式 schema 变更、或任何涉及 Linear / GitHub 写操作语义的变更。

Bug 报告和小修复可以直接提 PR。

## 许可证

TBD.
