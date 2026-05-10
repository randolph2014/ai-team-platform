# AI Team Platform Harness Governance Design

## 背景

AI Team Platform 已经具备阶段编排、代码库扫描、需求综合、人工 gate、开发、QA、Review、最终验收、artifact 契约、worktree 和 quality gates。下一步差异化能力不应该是继续增加 agent 角色，而是建立项目级 Harness Governance Layer：用仓库内可版本化的工程知识约束 agent。

本设计基于以下输入：

- 当前 agent 协作流设计。
- AI Team Platform Harness Engineering 迭代方向。
- `/Users/wurui/Downloads/AI_Team_Platform_Harness_Issues_Recommendations.docx`。
- 当前仓库中 project registry、quality gates、settings、context scan、run API 的实现现状。

这次需求最大的交付风险不是“方案没聊清楚”，而是实现阶段上下文衰减：功能点太多时，后续实现容易忘掉前面的硬约束，最后交付结果被口头包装成完成。这个 spec 的目的就是把关键要求变成稳定约束 ID、追踪矩阵、硬验收门槛和可核查证据。

## 产品定位

AI Team Platform 不只是运行 agent 的工具。

它应该成为需求交付平台：

1. 用项目级 Harness 资产约束 agent。
2. 用 rules、skills、checks、baselines、task memory 固化团队工程经验。
3. 复用现有 pipeline、human gates、quality gates、artifact contracts 和 worktree 执行能力。
4. 把历史决策输入下一次需求上下文。
5. 让完成声明可以被证据审计，而不是依赖 agent 自我报告。

## 目标

1. 定义独立的 Harness Governance Layer，并且可以分阶段落地。
2. 以仓库文件作为 Harness 配置真相源。
3. 所有公共 Harness API 使用 `project_id`，不暴露 `workdir`。
4. command check 复用现有 Quality Gate runner。
5. 交付拆成 Core、Checks、Task Board、UI 四个子迭代。
6. 通过 traceability matrix 和证据化完成声明，降低上下文衰减导致的漏实现、假完成风险。
7. 把危险捷径变成可阻断或可见的问题：路径穿越、symlink escape、任意命令执行、baseline 降低、UI stale 写入、skills 覆盖平台安全策略。

## 非目标

1. 不实现第二套 pipeline engine。
2. 不为 Harness command check 实现第二套 command runner。
3. 不把 DB 作为 Harness 配置真相源。
4. 不允许 production Harness API 使用 `workdir`。
5. 不新增大量默认 agent 角色。
6. 不允许 Harness skills 覆盖平台安全策略、human gate、quality gate 或系统级指令。
7. 不把 UI 做成任意仓库文件编辑器。
8. 不自动降低 baseline。
9. 不把完整 Harness、Task Board、UI 和模板更新塞进一个大迭代。

## 与现有协作流的关系

Harness 是现有交付流程的治理层，不替代现有流程。

现有默认流程保持为：

```text
intake
context_scan
requirement_analysis
requirement_synthesis
requirement_confirm
planning
task_plan_confirm
develop
qa
review
acceptance_confirm
retrospect
```

Harness 在以下节点接入：

- `context_scan`：注入 Harness 摘要、rules 索引、skills 索引、checks 摘要、baselines 摘要和 related historical tasks。
- `requirement_synthesis`：要求对相关历史决策明确采用或拒绝，并写出理由。
- `planning`：把任务绑定到 Harness checks、baseline 影响和验证命令。
- `develop`：把 Harness rules 和 skills 作为项目上下文，但不允许它们覆盖平台安全策略。
- `qa`：运行 Harness checks 和 quality gates，生成结构化反馈。
- `review`：检查需求覆盖、baseline 完整性、checks 完整性、禁用/绕过行为和废弃代码删除。
- `acceptance_confirm`：最终人工验收通过后，才允许写入 accepted task memory。
- `retrospect`：汇总 Harness 结果、warning、残余风险和 task board 更新。

## 真相源模型

Harness 配置真相源是仓库文件：

```text
.ai/harness.yaml
.ai/harness/rules/**
.ai/harness/skills/**
.ai/harness/baselines/**
.ai/harness/tasks/*.json
.ai/harness/task-events/*.json
.ai/harness/task-board.json
```

DB 不是 Harness 配置真相源。

DB 是以下数据的事实源：

- Harness 执行结果。
- run history。
- check results。
- audit logs。
- UI result cache。
- user / project permission state。

`task-board.json` 只能作为可选 snapshot。存在并发写入时，它不能作为唯一持久状态源。

## 公共 API 边界

所有公共 Harness API 必须使用 `project_id`：

```text
GET  /api/projects/{project_id}/harness
PUT  /api/projects/{project_id}/harness
POST /api/projects/{project_id}/harness/validate
POST /api/projects/{project_id}/harness/checks/run
GET  /api/projects/{project_id}/task-board
POST /api/projects/{project_id}/task-board/events
```

后端解析链路：

```text
project_id
  -> project registry
  -> project_root
  -> workspace allowlist validation
  -> user permission validation
  -> Harness path safety validation
  -> file access
```

production 模式下，任何 Harness API 只要接受或收到 `workdir`，都必须拒绝。

development 兼容路径只能存在于 Harness 公共 API 之外，必须返回 deprecated warning，并且不能在 production 模式启用。

## 安全优先级

Harness assets 是项目上下文，不是最高策略源。

优先级顺序：

```text
system/developer policy
> platform safety policy
> pipeline template
> harness rules/skills/checks/baselines
> user requirement
> agent generated content
```

Harness skills 必须支持元数据：

```yaml
skills:
  - id: safe-refactor
    title: Safe Refactor
    file: .ai/harness/skills/safe-refactor.md
    allowed_agents:
      - developer
      - reviewer
    forbidden_capabilities:
      - modify_baselines
      - disable_checks
      - access_secrets
      - bypass_human_gate
```

如果 Harness skill 与平台安全策略冲突，平台安全策略优先。

## Manifest 与冲突模型

Harness 是多文件资产包，单文件 `file_hash` 不足以保护整体一致性。

所有支持编辑的读取响应必须返回 `manifest_hash`：

```json
{
  "manifest_hash": "sha256:...",
  "files": [
    {
      "path": ".ai/harness.yaml",
      "hash": "sha256:..."
    },
    {
      "path": ".ai/harness/rules/security.md",
      "hash": "sha256:..."
    }
  ]
}
```

所有写入请求必须带上客户端最后一次看到的 `manifest_hash`。

如果提交的 hash 已过期，API 必须返回 `409 Conflict`：

```json
{
  "error": "manifest_conflict",
  "current_manifest_hash": "sha256:...",
  "changed_files": [
    ".ai/harness.yaml",
    ".ai/harness/rules/security.md"
  ]
}
```

单文件 `file_hash` 可以作为 UI 辅助优化，但不能替代 `manifest_hash`。

## Harness Report 契约

每次 Harness 验证必须生成 `harness-report.json`。

必需字段：

```json
{
  "schema_version": "1.0",
  "run_id": "run_xxx",
  "project_id": "project_xxx",
  "stage_id": "harness_verify",
  "harness_config_hash": "sha256:...",
  "generated_at": "2026-05-09T00:00:00Z",
  "status": "pass|warning|fail",
  "blocking": false,
  "summary": {
    "total": 0,
    "passed": 0,
    "warnings": 0,
    "failed": 0,
    "skipped": 0
  },
  "checks": [],
  "baseline_results": [],
  "rule_violations": [],
  "warnings": [],
  "evidence": [],
  "next_stage_contract": {}
}
```

每个 check result 必须包含：

```json
{
  "id": "no-messagebox",
  "type": "pattern|command|baseline",
  "status": "pass|warning|fail|skipped",
  "severity": "info|warning|error",
  "blocking": true,
  "duration_ms": 0,
  "exit_code": null,
  "matched_files": [],
  "output_excerpt": "",
  "evidence_refs": []
}
```

## 硬约束

这些 ID 是后续 implementation plan、code review 和 acceptance 的控制面。未来不能在缺少证据行的情况下声明完成。

| ID | 约束 | 验证方式 |
|---|---|---|
| H-API-001 | 公共 Harness API 使用 `project_id`，不使用 `workdir`。 | Route tests 证明 production Harness endpoint 不接受 `workdir`。 |
| H-API-002 | production 模式拒绝包含 `workdir` 的 Harness request。 | API test 期望 `400` 或 `403`。 |
| H-PROJ-001 | Core 通过 project registry 解析 `project_id -> project_root`。 | valid、missing、deleted project 的单测和 route tests。 |
| H-PROJ-002 | 解析出的 project root 必须通过 workspace allowlist validation。 | allowed / disallowed roots 单测。 |
| H-PERM-001 | Harness file access 必须校验用户 project 权限。 | authorized / unauthorized route tests。 |
| H-PATH-001 | Harness file access 仅限 `.ai/harness.yaml` 和 `.ai/harness/**`。 | path safety tests。 |
| H-PATH-002 | 拒绝 absolute path injection、`../` 和 symlink escape。 | path traversal / symlink tests。 |
| H-SCHEMA-001 | Harness config 和 asset metadata 使用前必须 schema validate。 | invalid schema 返回 `400` 且不写入。 |
| H-MANIFEST-001 | Harness read/write API 使用 `manifest_hash`。 | stale write 返回 `409`。 |
| H-MANIFEST-002 | `file_hash` 不能替代 manifest 级冲突检测。 | 修改另一个 Harness 文件后，旧 manifest 写入返回冲突。 |
| H-QG-001 | command check 通过现有 Quality Gate runner 执行。 | spy 或 integration test 证明调用 `run_quality_gate(s)` 路径。 |
| H-QG-002 | Harness 不实现第二套 command execution engine。 | code review 确认无并行 command runner。 |
| H-CMD-001 | command check 强制 project/worktree cwd 限制。 | command cwd tests。 |
| H-CMD-002 | command check 强制 timeout，超时失败。 | timeout test。 |
| H-CMD-003 | command output 在报告中截断。 | long-output test。 |
| H-CMD-004 | command env 使用白名单，不盲目继承全环境。 | env isolation test。 |
| H-CMD-005 | production command check 只运行已审核 Harness config。 | production route / config tests。 |
| H-PATTERN-001 | pattern check 报告 rule ID、file、line、severity 和 evidence。 | pattern fixture test。 |
| H-BASE-001 | baseline check 默认 raise-only。 | baseline compare tests。 |
| H-BASE-002 | baseline 降低必须阻断，除非人工批准或 PR review。 | baseline lower test。 |
| H-BASE-003 | developer agent 不能静默修改 baseline 文件后继续通过。 | review 或 gate test 检测 baseline file changes。 |
| H-SKILL-001 | Harness skills 不能覆盖 system、platform、human gate、quality gate policy。 | prompt/context assembly tests。 |
| H-SKILL-002 | skills 支持 `allowed_agents` 和 `forbidden_capabilities`。 | loader schema tests。 |
| H-TASK-001 | task memory 记录 accepted success 之外的历史状态。 | task state tests。 |
| H-TASK-002 | QA failed、review changes requested、acceptance rejected、cancelled run 不污染 accepted state。 | task event tests。 |
| H-TASK-003 | related tasks 注入 `context_scan` 输出。 | context scan test。 |
| H-TASK-004 | requirement 和 planning 输出必须对 related tasks 说明采用或拒绝理由。 | artifact validation test。 |
| H-TASK-005 | task events 可追溯到 `run_id`、`artifact_dir` 和 decision IDs。 | schema tests。 |
| H-UI-001 | UI 只能编辑 Harness 文件，不能编辑任意仓库文件。 | API 和 UI tests。 |
| H-UI-002 | UI 保存必须包含 `manifest_hash`，stale save 显示冲突。 | UI test。 |
| H-UI-003 | UI 渲染 Harness markdown 必须 sanitize。 | UI sanitize test。 |
| H-UI-004 | 无权限用户看不到编辑入口。 | UI permission test。 |
| H-REPORT-001 | `harness-report.json` 符合必需 schema。 | schema validation test。 |
| H-REPORT-002 | warning check 不阻断 pipeline，但必须在 report 和 UI 可见。 | pipeline / UI tests。 |
| H-REPORT-003 | error check 阻断 pipeline 并生成反馈。 | pipeline test。 |
| H-DOD-001 | 没有填好的 traceability matrix，不能声明子迭代完成。 | PR checklist / review gate。 |
| H-DOD-002 | 没有 fresh command output 和逐需求证据，不能声明完成。 | final report format check。 |

## 子迭代 1：Core

### 目标

建立安全的 Harness asset model，不执行复杂检查。

### 范围

- Project Resolver。
- Harness Loader。
- Harness schema validation。
- Path safety。
- Manifest hash。
- Context scan Harness summary injection。
- 公共 `project_id` API 边界。

### 预计影响文件

具体文件必须在 implementation plan 阶段重新确认。当前预计包括：

```text
engine/harness.py
engine/context_scanner.py
api/routes/harness.py
api/routes/projects.py
api/main.py
tests/test_harness_core.py
tests/test_routes.py
```

### 验收标准

1. production 模式拒绝 Harness API 中的 `workdir`。
2. 非法 `project_id` 返回 `404`。
3. 无权限 project access 返回 `403`。
4. 不在 allowlist 的 project root 返回 `403`。
5. path traversal 和 symlink escape 被拒绝。
6. 非法 Harness schema 返回 `400`。
7. `manifest_hash` 稳定且可复现。
8. 存在 Harness assets 时，`context_scan` 注入 Harness 摘要。
9. Core 范围内的 traceability rows 全部为 `verified`。

## 子迭代 2：Checks

### 目标

实现可执行 Harness verification，并复用现有 Quality Gate runner。

### 范围

- `harness_verify` stage type。
- Pattern checks。
- Command checks 转换为 Quality Gate config。
- Baseline checks。
- `harness-report.json`。
- Pipeline blocking semantics。

### 执行边界

command checks 必须调用现有 Quality Gate runner。Harness 可以转换配置和聚合结果，但不能直接执行命令。

### 验收标准

1. command checks 复用 `run_quality_gate` 或 `run_quality_gates`。
2. command timeout 失败。
3. 非 0 exit code 按 severity 映射。
4. 长输出被截断。
5. command env 由白名单控制。
6. baseline lower 被阻断，除非有明确批准。
7. Error 级失败阻断 pipeline。
8. Warning 级失败继续流转，但必须写入 report 和 UI 数据。
9. `harness-report.json` 通过 schema validation。
10. Checks 范围内的 traceability rows 全部为 `verified`。

## 子迭代 3：Task Board

### 目标

建立项目级任务记忆，让历史需求、历史决策、失败记录和已验收工作影响未来上下文。

### 范围

- `.ai/harness/tasks/*.json`。
- `.ai/harness/task-events/*.json`。
- 可选 `.ai/harness/task-board.json` snapshot。
- Task state model。
- Related task matching。
- Context scan injection。
- Artifact validation 要求 adopt / reject reasons。

### 推荐状态模型

```text
proposed
planned
in_progress
blocked
qa_failed
review_changes_requested
accepted
rejected
cancelled
archived
```

### 验收标准

1. accepted、rejected、failed、cancelled histories 均能无歧义表达。
2. QA failed 和 review rejected 不会进入 accepted state。
3. 只有最终人工验收通过后才能写入 accepted state。
4. related tasks 按 requirement text、tags、touched files、historical decisions 匹配。
5. requirement 和 planning artifacts 必须说明采用或拒绝的历史决策。
6. 并发写入不能互相覆盖。
7. Task Board 范围内的 traceability rows 全部为 `verified`。

## 子迭代 4：UI

### 目标

在 Core、Checks、Task Board API 稳定后，提供完整 Harness 管理界面。

### 范围

- Harness 页面五个 tab：
  - Rules。
  - Skills。
  - Checks。
  - Baselines。
  - Task Board。
- Manifest conflict handling。
- Permission-aware editing。
- 保存前 schema validation。
- Markdown sanitization。
- RunDetail Harness report display。

### 验收标准

1. UI 使用 `project_id` APIs。
2. UI edit save 包含 `manifest_hash`。
3. stale save 显示冲突，不覆盖文件。
4. invalid config 不写入磁盘。
5. 无权限用户看不到编辑入口。
6. UI 不能编辑 Harness 路径之外的文件。
7. Markdown 内容被 sanitize。
8. RunDetail 展示 blocking reason、warnings、baseline changes 和 check evidence。
9. UI 范围内的 traceability rows 全部为 `verified`。

## Traceability Matrix

每个 implementation plan 和 final report 都必须包含这个矩阵。

`plan-time` 表示该列必须在对应子迭代 implementation plan 中填实；填实前不允许开始编码。

| Requirement ID | Sub-Iteration | Design Source | Implementation Files | Tests | Verification Command | Status | Evidence |
|---|---|---|---|---|---|---|---|
| H-API-001 | Core | Public API Boundary | plan-time | plan-time | plan-time | pending | plan-time |
| H-API-002 | Core | Public API Boundary | plan-time | plan-time | plan-time | pending | plan-time |
| H-PROJ-001 | Core | Public API Boundary | plan-time | plan-time | plan-time | pending | plan-time |
| H-PROJ-002 | Core | Public API Boundary | plan-time | plan-time | plan-time | pending | plan-time |
| H-PERM-001 | Core | Public API Boundary | plan-time | plan-time | plan-time | pending | plan-time |
| H-PATH-001 | Core | Source Of Truth Model | plan-time | plan-time | plan-time | pending | plan-time |
| H-PATH-002 | Core | Source Of Truth Model | plan-time | plan-time | plan-time | pending | plan-time |
| H-SCHEMA-001 | Core | Manifest And Conflict Model | plan-time | plan-time | plan-time | pending | plan-time |
| H-MANIFEST-001 | Core | Manifest And Conflict Model | plan-time | plan-time | plan-time | pending | plan-time |
| H-MANIFEST-002 | Core | Manifest And Conflict Model | plan-time | plan-time | plan-time | pending | plan-time |
| H-QG-001 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-QG-002 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-CMD-001 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-CMD-002 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-CMD-003 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-CMD-004 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-CMD-005 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-PATTERN-001 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-BASE-001 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-BASE-002 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-BASE-003 | Checks | Sub-Iteration 2 | plan-time | plan-time | plan-time | pending | plan-time |
| H-SKILL-001 | Core | Security Priority | plan-time | plan-time | plan-time | pending | plan-time |
| H-SKILL-002 | Core | Security Priority | plan-time | plan-time | plan-time | pending | plan-time |
| H-TASK-001 | Task Board | Sub-Iteration 3 | plan-time | plan-time | plan-time | pending | plan-time |
| H-TASK-002 | Task Board | Sub-Iteration 3 | plan-time | plan-time | plan-time | pending | plan-time |
| H-TASK-003 | Task Board | Sub-Iteration 3 | plan-time | plan-time | plan-time | pending | plan-time |
| H-TASK-004 | Task Board | Sub-Iteration 3 | plan-time | plan-time | plan-time | pending | plan-time |
| H-TASK-005 | Task Board | Sub-Iteration 3 | plan-time | plan-time | plan-time | pending | plan-time |
| H-UI-001 | UI | Sub-Iteration 4 | plan-time | plan-time | plan-time | pending | plan-time |
| H-UI-002 | UI | Sub-Iteration 4 | plan-time | plan-time | plan-time | pending | plan-time |
| H-UI-003 | UI | Sub-Iteration 4 | plan-time | plan-time | plan-time | pending | plan-time |
| H-UI-004 | UI | Sub-Iteration 4 | plan-time | plan-time | plan-time | pending | plan-time |
| H-REPORT-001 | Checks | Harness Report Contract | plan-time | plan-time | plan-time | pending | plan-time |
| H-REPORT-002 | Checks | Harness Report Contract | plan-time | plan-time | plan-time | pending | plan-time |
| H-REPORT-003 | Checks | Harness Report Contract | plan-time | plan-time | plan-time | pending | plan-time |
| H-DOD-001 | All | Definition Of Done | plan-time | plan-time | plan-time | pending | plan-time |
| H-DOD-002 | All | Definition Of Done | plan-time | plan-time | plan-time | pending | plan-time |

## 实施协议

每个子迭代必须按以下顺序推进：

1. 只为一个子迭代创建 implementation plan。
2. 把该子迭代相关 traceability rows 复制到 plan。
3. 编码前填实这些 rows 中的 `plan-time`。
4. 只实现范围内的 rows。
5. 运行 rows 中列出的验证命令。
6. 用证据更新 row status。
7. 做 code review，重点审需求覆盖和禁用捷径。
8. 输出子迭代 final report。
9. 进入下一个子迭代前必须等人工验收。

未经用户明确批准，不允许跨子迭代混做。

## 完成声明规则

agent 不允许在缺少以下信息时声明子迭代完成：

1. 已完成的 requirement IDs。
2. 每个 requirement ID 对应的修改文件。
3. 每个 requirement ID 对应的新增或更新测试。
4. fresh verification commands 和 exit results。
5. 剩余 warnings 和 risks。
6. 未完成 requirement IDs 的明确列表。
7. 确认 in-scope traceability rows 中没有 `plan-time`。

允许的 final status：

```text
complete
complete_with_warnings
blocked
partial
failed
```

只有所有 in-scope requirement rows 都是 `verified`，且所有 blocking checks 通过，才能使用 `complete`。

只有所有 in-scope requirement rows 都是 `verified`，没有 blocking checks 失败，并且列出非阻断 warning，才能使用 `complete_with_warnings`。

只要存在任何 in-scope row 未验证，就必须使用 `partial`。

## 停止规则

出现以下情况时，implementation 必须停止并汇报：

1. 硬约束与当前仓库架构冲突。
2. 某个必需 route 无法在不扩大迁移面的情况下改成 `project_id`。
3. Quality Gate runner 无法安全满足 command check 要求。
4. baseline 审批语义依赖缺失的 human gate 能力。
5. Task Board 并发模型必须在 event model 和 snapshot model 之间做用户决策。
6. UI 需要编辑 `.ai/harness.yaml` 或 `.ai/harness/**` 之外的文件。
7. 验证命令在计划修复轮次后仍失败。
8. agent 无法为任一 in-scope traceability row 填写证据。

agent 不得把这些情况包装成完成。

## Baseline 更新策略

Baseline checks 默认：

```yaml
baselines:
  mode: raise_only
  update_policy: human_approval_required
  allow_auto_update: false
```

规则：

1. 当前指标高于 baseline 时通过，并可以建议 raise baseline。
2. 当前指标低于 baseline 时按 severity fail 或 warn。
3. baseline 文件降低必须阻断，除非人工批准或 PR review。
4. developer agent 不能修改 baseline 文件后继续伪装为 checks passed。
5. baseline changes 必须出现在 Harness report 和 review output 中。

## Command Check 安全

Harness command checks 必须继承 Quality Gate execution path，并要求以下保证：

1. cwd 限制在 project root 或 active worktree root。
2. timeout 必填。
3. output 被截断。
4. env 使用白名单。
5. 执行前拒绝 path traversal 和 symlink escape。
6. production 模式只运行已审核 Harness command config。
7. 结果包含 exit code、duration、output excerpt、severity 和 blocking。

如果现有 Quality Gate runner 暂不支持某项保证，Checks 子迭代必须扩展共享 runner，不能增加 Harness-only command executor。

## Task Board 存储模型

推荐模型：

```text
.ai/harness/tasks/
  T-0001.json
  T-0002.json

.ai/harness/task-events/
  20260509T101010Z-run-abc-created.json
  20260509T102000Z-run-abc-qa-failed.json
  20260509T103000Z-run-abc-accepted.json

.ai/harness/task-board.json
```

`task-board.json` 是生成或人工刷新的 snapshot。并发写入存在时，权威写入模型应是 task files + event files。

Task record 必须包含：

```json
{
  "id": "T-0001",
  "title": "Harness Core project resolver",
  "state": "accepted",
  "tags": ["harness", "core"],
  "related_files": [],
  "run_ids": [],
  "artifact_dirs": [],
  "decision_ids": [],
  "created_at": "2026-05-09T00:00:00Z",
  "updated_at": "2026-05-09T00:00:00Z"
}
```

## 测试计划

未来实现必须默认运行以下命令：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py -q
cd web && npm run test
cd web && npm run build
git diff --check
```

子迭代 plan 可以补充更窄的命令，但不能删除完整验证命令，除非用户明确批准缩小验证范围。

## 当前仓库证据

影响本设计的当前仓库证据：

1. 仓库已有 `project` 表和 `ProjectRepo`，所以 Core 应硬化现有 project registry，而不是新建一套 registry。
2. run API 已有 production 模式下要求 `project_id` 并拒绝 `workdir` 的模式，所以 Harness 应采用更严格的公共契约。
3. Quality Gate runner 已有 command 和 threshold 执行能力，所以 Harness command checks 应复用它。
4. Quality Gate runner 当前使用 `shell=True`，所以 Checks 子迭代必须硬化共享 runner，而不是复制 runner。
5. Settings API 当前仍使用 `workdir` 且 settings 写 DB，所以 Harness UI/API 必须采用新的 repo-file-first contract。
6. Context scanner 默认排除 `.ai`，所以 Core 必须显式注入 Harness summary，而不是依赖通用 tree scanning。
7. 当前协作流已有 context scan、human gates、QA、review、acceptance、retrospect，因此 Harness 应挂载在这些节点上，不替代它们。

## 本 Spec 验收条件

这份 spec 只有在以下条件被用户接受后，才能进入 implementation planning：

1. 接受 Core / Checks / Task Board / UI 四个子迭代拆分。
2. 接受 `manifest_hash` 作为必要写入冲突检测机制。
3. 接受 task files + task events 作为首选 Task Board 存储模型。
4. 接受 Core 必须包含 Project Resolver，而不是把它当 assumption。
5. 接受未来完成声明必须绑定 traceability rows 和 fresh command output。

如果任一条件变化，必须先更新本 spec，再写 implementation plan。
