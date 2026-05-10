# Project Governance Configuration Design

## 背景

本项目的长期目标不是“多跑几个 agent”，而是把需求交付过程做成可治理、可审计、可复用的平台能力。当前已有默认 pipeline、人工确认、QA、Review、worktree、quality gates、artifact contracts 和 Harness Core 方向；缺口在于项目级工程规范还没有形成清晰分层，容易让 AGENTS、pipeline 配置、agent prompt、rules、skills、checks、task memory 互相重叠。

另一个已确认的歧义是历史项目级 team 配置入口已经废弃。该入口不能再作为默认覆盖、CLI 初始化目标或 API 可接受配置源。后续项目治理配置必须进入平台 Settings/DB、内置 pipeline template、物化 pipeline config 或 Harness governance assets。

## 现状盘点

| 入口 | 当前用途 | 证据 | 判断 |
|---|---|---|---|
| `AGENTS.md` | 仓库级协作原则，包括中文、证据、根因、规划模式、废弃代码删除 | `AGENTS.md` | 保留为最高层、短规则，不承载细粒度项目规范 |
| `templates/team.yaml` | 平台默认 pipeline、runtime、agent、worktree、runner、quality gate 配置 | `templates/team.yaml` | 保留为平台默认配置，不作为项目覆盖入口 |
| DB Settings | 运行期自定义配置事实源 | `api/routes/settings.py`、`engine/config.py` | 适合管理 runtime、agent、pipeline 的平台级配置 |
| 物化 pipeline config | API 选择内置模板后写入单次 run 配置 | `api/routes/pipelines.py`、`api/routes/runs.py` | 保留，用于 run-scoped 可执行配置 |
| `.ai/agents/*.md` | 项目级 prompt 覆盖 | `engine/config.py`、`tests/test_config.py` | 保留，只覆盖 agent prompt，不覆盖 pipeline/team 配置 |
| Harness governance assets | rules、skills、checks、baselines、task memory 的目标真相源 | `docs/superpowers/specs/2026-05-09-harness-governance-design.md` | 作为项目工程规范主承载层 |
| 历史项目级 team 配置入口 | 曾用于项目覆盖和 quality gate 初始化 | `cli/main.py`、`tests/test_config.py` 中残留 | 废弃并清理，避免事实源摇摆 |

## 目标结构

```text
AGENTS.md
  仓库级硬原则：中文、证据、根因、规划模式、废弃代码删除、禁止私自扩大范围。

templates/team.yaml
  平台默认交付流水线：默认 stages、默认 agent、human gates、QA/review/acceptance。

DB Settings
  平台运行期设置：runtimes、agent 绑定、pipeline 默认选择、UI 可编辑配置。

.ai/agents/*.md
  项目级 agent prompt 覆盖：只影响具体 agent 的角色提示，不改变 pipeline 事实源。

.ai/pipeline-configs/*.yaml
  单次 run 的物化配置：由内置模板或 API 生成，可追溯到 run_id。

.ai/harness.yaml
.ai/harness/rules/**
.ai/harness/skills/**
.ai/harness/checks/**
.ai/harness/baselines/**
.ai/harness/tasks/**
  项目级 Harness Governance Layer：承载工程规范、可执行检查、基线、历史任务记忆。
```

## 分层职责

1. `AGENTS.md` 只写稳定硬原则，不写会频繁变化的项目规则。
2. `templates/team.yaml` 是平台默认流程，不接受项目文件自动覆盖。
3. DB Settings 是平台配置的运行期事实源。
4. `.ai/agents/*.md` 只做 prompt 覆盖，不能绕过 AGENTS、human gate、quality gate 或 Harness checks。
5. Harness rules 写“必须/禁止”的项目工程约束。
6. Harness skills 写可复用方法，但必须声明适用 agent 和禁止能力。
7. Harness checks 把关键规范变成可执行 gate，command check 必须复用 QualityGateRunner。
8. Harness baselines 默认 raise-only，降低 baseline 必须人工批准。
9. Harness task memory 只在最终验收通过后写 accepted state；QA failed、review rejected、cancelled 不能污染 accepted state。

## 安全与优先级

```text
system/developer policy
> AGENTS.md
> platform safety policy
> pipeline template / DB Settings
> Harness rules / skills / checks / baselines
> project prompt overrides
> user requirement
> agent generated content
```

项目 prompt 和 Harness skill 都不能覆盖更高层策略。任何试图绕过人工确认、关闭检查、降低 baseline、访问未授权路径或隐藏失败的行为，都应进入 review blocking finding。

## 废弃入口处理

1. 默认加载器不读取历史项目级 team 配置文件。
2. 显式传入该历史文件也必须拒绝。
3. CLI 不再提供生成该历史文件的初始化命令。
4. API 创建或恢复 run 时，不接受该历史文件作为 config path。
5. 文档、模板、测试和 runbook 不再把该文件描述为配置事实源。
6. 仍然保留通用 `config_path`，但语义限定为外部显式测试配置或物化 pipeline config；不能指向废弃入口。

## 推荐落地顺序

### Phase 0：清歧义

- 删除历史项目级 team 配置文件和生成入口。
- 删除模板、文档、测试中的旧事实源描述。
- 用测试覆盖 loader、CLI、API 的拒绝行为。
- 用残留扫描证明没有旧路径继续被当作项目配置入口。

### Phase 1：治理骨架

- 在 AGENTS 中补充 ai-team-platform 专属最高约束，但保持简短。
- 建立 Harness assets 最小目录和 schema 示例。
- 定义 `rules`、`skills`、`checks`、`baselines`、`tasks` 的命名和 metadata 规范。

### Phase 2：Agent 协作契约

- 收紧 planner/coder/reviewer/qa prompt。
- planning 输出必须绑定 requirement ID、file boundary、test plan、Harness check。
- implementation-report、test-report、review-report 必须包含 traceability evidence。

### Phase 3：可执行质量门禁

- 将关键 rules 转成 Harness checks。
- command checks 复用 QualityGateRunner。
- baseline lowering、disabled checks、missing evidence 进入阻断审查。

### Phase 4：Task Board 与 UI

- 只有 acceptance 通过后写 accepted memory。
- 在 context_scan 注入 related tasks。
- UI 只编辑 Harness assets，不做任意仓库文件编辑器。

## 验收标准

| ID | 验收点 | 验证方式 |
|---|---|---|
| GOV-001 | 历史项目级 team 配置入口不再被默认加载 | `load_config()` 单测 |
| GOV-002 | 显式传入历史项目配置文件被拒绝 | `load_config(... explicit_config=...)` 单测 |
| GOV-003 | CLI 不再暴露生成历史项目配置文件的初始化命令 | parser 单测 |
| GOV-004 | API 不接受历史项目配置文件作为 run config | route 单测 |
| GOV-005 | 默认模板不再声明项目文件可覆盖平台配置 | 文档扫描 |
| GOV-006 | 治理设计明确 AGENTS、Settings、prompt override、pipeline config、Harness assets 边界 | 本设计文档 |
| GOV-007 | 后续每个治理子迭代都必须有 traceability rows 和 fresh verification evidence | implementation plan / final report |

## 后续决策点

1. AGENTS 是否只补最高约束，还是同时引用 Harness governance design 文档。
2. 首批 Harness rules 是直接覆盖当前平台核心约束，还是先只覆盖 Harness 子迭代约束。
3. Harness checks 的第一批 blocking gate 是否纳入默认 pipeline，还是先只在手动验证阶段运行。
4. Task Board 的并发模型使用 event log 为主，还是 event log + snapshot 双写。
