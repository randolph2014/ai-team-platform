# Project Governance Phase 1 Final Report

验收日期：2026-05-10

验收对象：Project Governance Phase 1：治理骨架。范围限定为 AGENTS 最高约束、Harness governance assets 最小骨架、metadata 命名规范和可机械验证证据。

## 结论

complete_with_warnings。

本阶段已建立最小 Harness Governance Layer 骨架，并用 `engine/harness.py` 当前 schema 证明可加载。未推进 Checks 执行、Task Board 行为或 UI。

## 现状盘点

| 对象 | 当前事实 | 证据 |
|---|---|---|
| AGENTS | 原文件只有 7 条通用规则；本阶段新增 4 条项目级最高约束，保持简短 | `AGENTS.md` |
| 平台默认模板 | `templates/team.yaml` 承载默认 runtime、agent、pipeline、human gate、quality gate；当前已有 `harness_verify` 阶段，但本阶段未修改模板 | `templates/team.yaml` |
| 项目 prompt 覆盖 | repo 根 `.ai/agents/*.md` 当前不存在；本阶段未新增 prompt 覆盖 | `find .ai -maxdepth 4 -type f` |
| Harness Core | 只扫描 `.ai/harness.yaml` 和 `.ai/harness/**`；schema 支持 `rules`、`skills`、`checks`、`baselines`，不支持顶层 `tasks` | `engine/harness.py` |
| Harness tests | 已覆盖 schema、path safety、manifest、skill policy；本阶段新增仓库级治理资产测试 | `tests/test_harness_core.py` |
| 已有未提交改动 | 工作区进入前已有 Checks/UI 计划和报告改动；本阶段未修改这些文件 | `git status --short --branch` |

## 修改文件清单

| 文件 | 为什么改 |
|---|---|
| `AGENTS.md` | 补 ai-team-platform 项目级最高约束：Harness 分层、gate 优先级、repo-file source、阶段隔离和证据声明 |
| `tests/test_harness_core.py` | 新增仓库级治理资产测试，证明 Phase 1 assets 可被当前 loader 加载，且 checks skeleton 没有可执行字段 |
| `.ai/harness.yaml` | 建立当前 engine schema 支持的最小合法 Harness manifest：rules、skills、checks skeleton、baselines |
| `.ai/harness/rules/README.md` | 定义 rules 命名和 metadata 规范 |
| `.ai/harness/rules/phase-boundary.md` | 首批核心规则：阶段边界和证据化完成声明 |
| `.ai/harness/rules/source-of-truth.md` | 首批核心规则：Harness repo-file truth 与分层边界 |
| `.ai/harness/rules/evidence-and-gates.md` | 首批核心规则：不能弱化 human gate、quality gate、AGENTS 和平台安全策略 |
| `.ai/harness/skills/README.md` | 定义 skills 命名、metadata、allowed_agents、forbidden_capabilities 规范 |
| `.ai/harness/skills/phase-scoped-implementation.md` | 首批治理 skill：阶段化实施方法 |
| `.ai/harness/skills/evidence-based-review.md` | 首批治理 skill：证据化评审方法 |
| `.ai/harness/checks/README.md` | 定义 checks 命名和 Phase 1 skeleton 边界 |
| `.ai/harness/checks/checks-contract.md` | 只记录未来 checks 契约，不实现执行 |
| `.ai/harness/baselines/README.md` | 定义 baseline 命名和 raise-only 原则 |
| `.ai/harness/baselines/raise-only-policy.md` | 建立 baseline raise-only、禁止静默降低的规范 |
| `.ai/harness/tasks/README.md` | 定义 task memory 文件边界；说明当前 schema 不支持顶层 tasks |
| `.ai/harness/tasks/state-model.md` | 定义 task memory 状态模型 |
| `.ai/harness/tasks/task-memory-contract.md` | 定义 accepted 写入边界与 event/snapshot 关系 |
| `docs/superpowers/reports/2026-05-10-project-governance-phase-1-final-report.md` | 本阶段验收报告 |

## Phase 1 验收表

| 验收项 | 状态 | 证据 |
|---|---|---|
| AGENTS 补项目级最高约束且保持简短 | PASS | `AGENTS.md` 新增 4 条稳定硬原则 |
| `.ai/harness.yaml` 是当前 engine 支持的最小合法配置 | PASS | `tests/test_harness_core.py::TestRepositoryHarnessGovernanceAssets::test_phase1_governance_assets_load_without_executable_checks` 通过 |
| rules 有命名、metadata 和首批核心规则 | PASS | `.ai/harness/rules/README.md` 和 3 个 rule 文件 |
| skills 有命名、metadata、allowed_agents、forbidden_capabilities | PASS | `.ai/harness/skills/README.md`、2 个 skill 文件、同名 config entries |
| checks 只建立规范骨架，不实现执行 | PASS | `.ai/harness/checks/**`；测试断言所有 check entry 没有 `type`、`command`、`pattern`、`baseline_file`、`timeout_seconds` |
| baselines 建立 raise-only 和禁止静默降低规范 | PASS | `.ai/harness/baselines/raise-only-policy.md` |
| tasks 建立状态、accepted 写入边界、event/snapshot 关系说明 | PASS | `.ai/harness/tasks/state-model.md`、`.ai/harness/tasks/task-memory-contract.md` |
| 不混入进入前已有 Checks/UI 改动 | PASS | `git status --short --branch` 显示 Checks/UI 文件仍为既有未提交改动；本阶段未编辑这些文件 |
| 不推进 Phase 2/3/4 | PASS | 未改 engine/API/UI/QualityGateRunner；checks 仅为文档 skeleton |
| 没有重新引入历史项目 team 入口为项目配置事实源 | PASS | 对本阶段改动文件执行残留扫描，无输出 |

## Verification

红灯：

```text
.venv/bin/python -m pytest tests/test_harness_core.py::TestRepositoryHarnessGovernanceAssets::test_phase1_governance_assets_load_without_executable_checks -q
FAILED
AssertionError: Lists differ: ['harness_config_missing'] != []
```

绿灯：

```text
.venv/bin/python -m pytest tests/test_harness_core.py::TestRepositoryHarnessGovernanceAssets::test_phase1_governance_assets_load_without_executable_checks -q
1 passed in 0.14s
```

用户指定测试：

```text
.venv/bin/python -m pytest tests/test_harness_core.py tests/test_config.py -q
70 passed in 0.33s
```

diff 空白检查：

```text
git diff --check
PASS
```

残留扫描：

```text
rg -n <legacy-project-team-entry-pattern> AGENTS.md .ai/harness.yaml .ai/harness tests/test_harness_core.py
NO MATCH
```

## 剩余风险

1. 当前 Harness loader 只校验 `.ai/harness.yaml` 引用和文件存在性，不解析 Markdown front matter；metadata 文档的深度 schema 校验应留给后续 Checks/Core 扩展，不在本阶段实现。
2. 当前 schema 没有顶层 `tasks` 字段，所以 task memory 只能作为 `.ai/harness/tasks/**` 规范文档进入 manifest；Task Board 行为必须等后续阶段实现。
3. 工作区已有 Checks/UI 计划与报告的未提交改动仍存在；这些不是本阶段产物，本报告不对其完成度负责。

## Scope Boundary

本阶段没有实现 Harness checks 执行、没有新增 Task Board 行为、没有新增 UI，也没有新增第二套 command runner 或 DB-backed Harness 配置事实源。
