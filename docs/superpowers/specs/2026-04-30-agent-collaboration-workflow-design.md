# Agent Collaboration Workflow Redesign

## 背景

当前默认 agent pipeline 已经具备阶段编排、文件产物交接、局部并行、人工审查、checkpoint resume 和 loopback 能力，但默认流程的职责边界存在结构性问题：

- 方案讨论、方案确认、方案定稿、代码库扫描的顺序不合理。方案定稿必须基于代码库扫描，否则容易脱离真实代码。
- 方案确认和方案定稿语义重叠，当前拆分制造了流程歧义。
- 开发和代码应用职责混杂。默认开发流程应由 developer agent 在 worktree 中直接实施，`code_apply` 只能作为特殊 runtime 的兼容能力。
- 风险识别和代码审查职责高度重叠，应合并。
- 文档整理不应在开发后补，需求、方案、任务和验收标准应在开发前定稿。
- agent 之间仅靠自由文本 artifact 交接还不够，必须有统一的上下文包、输出 schema 和编排者校验。
- 人工确认是规范性 gate，不能自动通过；拒绝必须带理由并回流到对应上游节点。

本设计把默认协作机制收敛为：中心编排、标准 artifact、强人工 gate、拒绝回流、单开发默认、审查风险合并、文档前置。

## 目标

1. 建立长期可维护的 agent 协作默认流程。
2. 确保方案和任务规划基于真实代码库上下文。
3. 把需求确认、任务规划确认、最终验收确立为不可自动跳过的人工 gate。
4. 让人工拒绝成为结构化反馈节点，而不是简单失败状态。
5. 让每个 agent 的输入、输出、上下文和验收规则可配置、可校验、可追溯。
6. 默认使用单开发 agent 实施足够小的需求，避免不必要的并行复杂度。
7. 合并重复阶段，删除默认流程中的废弃或容易误导的节点。

## 非目标

1. 不设计 agent 之间直接互相聊天或互相调度的自治网络。
2. 不默认启用多个开发 agent 同时改代码。
3. 不把 `--yes` 作为人工确认的替代能力。
4. 不在开发完成后补核心设计文档。
5. 不把 `code_apply` 作为默认开发路径。

## 核心原则

1. Orchestrator 是唯一调度中心。agent 只完成被分配的阶段任务，不直接驱动其他 agent。
2. agent 之间通过标准化 artifact 交接。artifact 必须有 schema、状态、证据和下一阶段契约。
3. 编排者负责构造阶段上下文包，并把已确认需求、已确认任务、代码库上下文、反馈和输出规范注入 prompt。
4. 人工 gate 必须停在 `waiting`，只能由人工明确 approve 或 reject。
5. 人工 reject 必须填写理由。空理由不允许提交。
6. reject 后必须带着理由回到指定上游 stage，不允许只把 run 标记为 failed。
7. 先扫描代码库，再定需求和方案。
8. 小需求默认单 developer。只有满足独立边界和无冲突条件时才允许并行开发。
9. 风险识别归入代码审查。
10. 文档在需求定稿和方案任务规划阶段完成，开发阶段只执行已确认方案。

## 新默认 Pipeline

默认阶段顺序：

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

语义流程：

```text
需求输入
  -> 代码库扫描
  -> 多 agent 需求分析
  -> 需求综合定稿
  -> 人工确认需求
  -> 方案与任务规划
  -> 人工确认任务规划
  -> 开发实施
  -> 自动测试 / 质量门禁
  -> 代码审查（含风险识别）
  -> 不通过回流开发
  -> 人工最终验收
  -> 结果复盘
```

## 阶段职责

### intake

`intake` 负责保存原始需求和运行元数据。它不做需求解释、不做方案判断。

输出：

- `requirement.md`
- `run-context.json`

### context_scan

`context_scan` 在需求分析和方案规划前运行。它扫描真实代码库，输出结构、入口、相关模块、现有模式、约束、测试命令、潜在影响面和风险线索。

输出：

- `codebase-context.md`
- `codebase-context.json`

后续 `requirement_synthesis`、`planning`、`develop`、`qa`、`review` 必须引用该上下文。

### requirement_analysis

`requirement_analysis` 可以并行运行多个分析 agent，但它们只产生候选意见，不拥有最终决策权。

推荐 agent：

- `requirements-analyst`：业务目标、用户场景、验收点。
- `edge-case-analyst`：边界条件、异常流程、歧义。
- `codebase-analyst`：结合代码库找影响面和已有实现约束。
- `devils-advocate`：寻找冲突、遗漏、阻断风险。

输出：

- `requirement-analysis/*.md`
- `requirement-analysis/*.json`

### requirement_synthesis

`requirement_synthesis` 是综合裁决节点。它读取多 agent 候选意见和代码库扫描结果，输出唯一的“待人工确认需求”。

它必须说明：

- 采用了哪些意见。
- 拒绝了哪些意见。
- 每个拒绝的理由。
- 是否存在未决问题。
- 最终验收标准。
- 与代码库上下文的对应关系。

输出：

- `requirement-final.md`
- `requirement-final.json`

### requirement_confirm

`requirement_confirm` 是硬人工 gate。

规则：

- 必须进入 `waiting`。
- 不允许 `--yes` 自动通过。
- 不允许 `skip_if_no_blocker` 自动跳过。
- approve 后进入 `planning`。
- reject 必须填写理由，并回流 `requirement_synthesis`。

输出：

- `human-decision-requirement.json`
- `human-decision-requirement.md`

### planning

`planning` 基于已确认需求和代码库扫描结果，完成方案、任务拆分、依赖顺序、文件影响面、测试计划、验收标准、回滚考虑和实施边界。

这里完成核心文档，开发后不再补核心方案文档。

输出：

- `solution-plan.md`
- `solution-plan.json`
- `task-plan.md`
- `task-plan.json`

### task_plan_confirm

`task_plan_confirm` 是硬人工 gate。

规则：

- 必须进入 `waiting`。
- 不允许 `--yes` 自动通过。
- approve 后进入 `develop`。
- reject 必须填写理由，并回流 `planning`。

输出：

- `human-decision-task-plan.json`
- `human-decision-task-plan.md`

### develop

`develop` 默认由一个 developer agent 执行。该 agent 在 worktree 中直接修改代码，并输出实施报告。

默认不使用 `code_apply`。`code_apply` 仅保留为可选兼容 stage，用于不能直接写文件、只能输出 patch block 的 runtime。

输出：

- 实际代码变更。
- `implementation-report.md`
- `implementation-report.json`

### qa

`qa` 运行自动化测试和质量门禁。测试失败不是终止点，而是生成结构化反馈回流 `develop`。

输出：

- `test-report.md`
- `test-report.json`
- `quality-feedback-*.md`（失败时）

### review

`review` 合并代码审查和风险识别。它必须检查：

- 需求覆盖。
- 任务计划覆盖。
- 正确性。
- 测试充分性。
- 回归风险。
- 安全风险。
- 可维护性。
- 部署和回滚影响。
- 是否有废弃代码应删除。

发现必须修改的问题时，回流 `develop`。

输出：

- `review-report.md`
- `review-report.json`

### acceptance_confirm

`acceptance_confirm` 是最终人工验收 gate。

规则：

- 必须进入 `waiting`。
- 不允许 `--yes` 自动通过。
- approve 后进入 `retrospect`。
- reject 必须填写理由，并回流 `develop`。

输出：

- `human-decision-acceptance.json`
- `human-decision-acceptance.md`

### retrospect

`retrospect` 生成交付摘要。它不补核心设计文档，只汇总已经发生的事实、证据、变更和遗留风险。

输出：

- `final-summary.md`
- `final-summary.json`

## 人工 Gate 规范

硬人工 gate：

```text
requirement_confirm
task_plan_confirm
acceptance_confirm
```

统一规则：

1. 必须人工确认。
2. 不能自动通过。
3. `--yes` 对这些 gate 无效。
4. `skip_if_no_blocker` 对这些 gate 无效。
5. API、CLI、UI 都只能把 run 推到 `waiting`。
6. 只有明确的人工作出 approve 才能继续。
7. reject 必须填写理由，空理由不允许提交。
8. 所有人工决策必须写入 artifact、`checkpoint.json` 和 `report.json`。
9. 同一 gate 多次 reject 时必须保留历史记录，不能覆盖。

人工决策 schema：

```json
{
  "stage_id": "task_plan_confirm",
  "decision": "rejected",
  "reason": "任务拆分没有覆盖数据库迁移回滚方案",
  "required_changes": ["补充迁移方案", "补充回滚方案"],
  "target_stage": "planning",
  "decided_by": "human",
  "decided_at": "2026-04-30T00:00:00Z"
}
```

reject 回流规则：

```text
requirement_confirm reject -> requirement_synthesis
task_plan_confirm reject -> planning
acceptance_confirm reject -> develop
```

回流 prompt 必须注入人工拒绝理由，并明确要求：

```text
只围绕人工拒绝理由修正，不扩大范围。
不得重写已确认且未被拒绝的内容。
必须在输出中逐条回应 required_changes。
```

## Artifact 标准

每个核心 artifact 必须有 markdown 和 json 两种形态，markdown 用于人读，json 用于编排者校验和 UI 展示。

核心 artifact：

```text
codebase-context.md / codebase-context.json
requirement-analysis/*.md / requirement-analysis/*.json
requirement-final.md / requirement-final.json
human-decision-requirement.md / human-decision-requirement.json
solution-plan.md / solution-plan.json
task-plan.md / task-plan.json
human-decision-task-plan.md / human-decision-task-plan.json
implementation-report.md / implementation-report.json
test-report.md / test-report.json
review-report.md / review-report.json
human-decision-acceptance.md / human-decision-acceptance.json
final-summary.md / final-summary.json
```

通用 artifact 字段：

```json
{
  "status": "completed",
  "summary": "...",
  "inputs_used": [],
  "decisions": [],
  "open_questions": [],
  "risks": [],
  "acceptance_coverage": [],
  "evidence": [],
  "next_stage_contract": {}
}
```

编排者职责：

- 校验必需 artifact 是否存在。
- 校验 json schema。
- 校验状态字段。
- 校验人工 gate 决策。
- 校验下一阶段所需输入是否已满足。
- 不合格时阻断进入下一 stage。

## 上下文注入机制

Orchestrator 必须为每个 stage 构造标准上下文包，而不是简单拼接文件。

通用上下文包：

```text
run metadata
当前阶段目标
当前阶段允许动作
当前阶段禁止动作
已确认需求
已确认任务
代码库扫描结果
允许读写边界
必须输出的 artifact schema
验收标准
上轮失败或拒绝反馈
完成信号
```

示例：`develop` stage 注入：

```text
requirement-final.json
task-plan.json
codebase-context.json
human-decision-task-plan.json
允许修改文件范围
测试命令
禁止扩大范围
implementation-report schema
```

示例：`review` stage 注入：

```text
requirement-final.json
task-plan.json
implementation-report.json
test-report.json
git diff
review-report schema
```

## 多 Agent 意见综合

需求阶段允许多 agent 并行，但不能把多个输出简单拼接成需求。必须经过 `requirement_synthesis`。

综合器必须输出决策矩阵：

```text
观点来源
观点内容
证据
采用 / 拒绝
理由
对最终需求的影响
是否需要人工决策
```

存在未决问题时，仍进入 `requirement_confirm`，由人工决定。编排者不能自动猜测。

## 开发并行规则

默认不并行开发。

允许并行开发必须同时满足：

1. 需求已拆成独立 requirement unit。
2. 每个 unit 有清晰文件边界。
3. unit 之间依赖已拓扑排序。
4. 不存在同文件写冲突。
5. 每个 unit 有独立测试和验收点。
6. 编排者能合并并验证结果。

不满足以上条件时，统一单 developer agent 执行。

## 废弃和合并项

默认流程变更：

1. 废弃 `plan_confirm` 名称，改为 `requirement_confirm` 和 `task_plan_confirm`。
2. `architect` 不再早于 `context_scan`。
3. `code_apply` 不再作为默认主流程。保留为可选兼容 stage。
4. `risk_analysis` 并入 `review`。
5. `doc` 并入 `planning`，开发后不再补核心文档。
6. `skip_if_no_blocker` 不用于人工确认 gate。
7. `--yes` 不允许跳过人工确认 gate。

## 配置影响

`templates/team.yaml` 应更新为新默认流程。

`pipeline.execution_mode` 仍可保留：

- `serial`：同 stage 多 agent 也串行。
- `parallel`：仅允许声明为 `parallel: true` 的非开发分析 stage 并行。
- `auto`：根据上下文大小选择串行或并行，但不能影响人工 gate，也不能默认启用并行开发。

人工 gate 配置应明确：

```yaml
type: human_review
requires_reason_on_reject: true
allow_auto_approve: false
reject_to: planning
```

## API / CLI / UI 影响

### API

需要支持：

- approve human gate。
- reject human gate 并提交 reason / required_changes。
- 拒绝理由为空时返回 400。
- 返回当前 waiting gate、所需 artifact、历史人工决策。

### CLI

`--yes` 不再通过硬人工 gate。CLI 在 gate 处应显示 waiting 状态和需要人工确认的信息。

### UI

Run Detail 需要展示：

- 当前等待的人工 gate。
- approve / reject 操作。
- reject reason 输入框。
- required changes 输入。
- 历史人工决策。
- reject 回流路径。
- 当前 stage artifact schema 校验状态。

## 数据和状态影响

`checkpoint.json` 需要包含：

- 当前 stage。
- completed stages。
- human decisions。
- reject history。
- loopback target。
- stage retry count。
- requirement unit progress。

`report.json` 需要展示：

- gate waiting 状态。
- 人工决策结果。
- reject reason。
- 回流记录。
- artifact 校验结果。

## 需要修改的主要文件

预计涉及：

```text
templates/team.yaml
templates/agents/*.md
engine/orchestrator.py
engine/models.py
engine/config.py
engine/requirement_splitter.py
api/routes/runs.py
api/runtime.py
web/src/pages/RunDetail.tsx
web/src/components/PipelineTimeline.tsx
web/src/lib/api.ts
tests/test_engine.py
tests/test_routes.py
tests/test_config.py
```

## 验收标准

1. 默认 pipeline 顺序为 `context_scan` 先于需求定稿和 planning。
2. `requirement_confirm`、`task_plan_confirm`、`acceptance_confirm` 必须进入 waiting，不能自动通过。
3. `--yes` 对硬人工 gate 无效。
4. `skip_if_no_blocker` 不存在于硬人工 gate 默认配置。
5. reject 必须带 reason，空 reason 被 API / CLI / UI 拒绝。
6. reject 后按规则回流到 `requirement_synthesis`、`planning` 或 `develop`。
7. 回流 prompt 注入 reject reason 和 required changes。
8. artifact json schema 校验失败时阻断下一 stage。
9. 默认开发阶段只有一个 developer agent。
10. `code_apply` 不在默认 pipeline 中。
11. `risk_analysis` 不在默认 pipeline 中，风险审查包含在 `review`。
12. `doc` 不在默认 pipeline 中，核心文档由 `planning` 产出。
13. QA 失败和 review request changes 都能带结构化反馈回流 `develop`。
14. Run Detail 展示当前人工 gate、reject reason、回流路径和 artifact 校验状态。
15. 自动化测试覆盖 orchestrator、API、配置归一化和关键 UI 行为。

## 实施分解建议

本设计应拆成四个实施批次：

1. **流程和配置重构**：更新默认 pipeline、stage 定义和 prompts，删除默认重复节点。
2. **人工 gate 强化**：实现不可自动通过、reject reason 必填、reject 回流和状态持久化。
3. **artifact 和上下文契约**：引入 schema 校验、stage context package 和 prompt 注入重构。
4. **前端和验收闭环**：Run Detail 展示 gate、artifact 校验、拒绝历史和回流状态，并补齐测试。

这四个批次必须串行闭环。每个批次完成后都要测试、review 和需求验收，再进入下一批次。

## Spec 自审

- 无未决项。
- 需求确认、任务规划确认、最终验收三个硬人工 gate 均已覆盖。
- reject reason 必填和回流路径已覆盖。
- 先代码库扫描再需求/方案定稿已覆盖。
- 开发默认单 agent、并行条件、废弃 `code_apply` 默认路径已覆盖。
- 风险识别并入 review、文档前置到 planning 已覆盖。
- artifact schema、上下文注入、API/CLI/UI、状态持久化和验收标准均已覆盖。
