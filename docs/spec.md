# AI Team Platform — 需求规格说明书 (Spec)

> 版本: 2.0 | 日期: 2026-04-23 | 状态: Draft
> 变更: 基于 brave-cabin 评审修订，质量优先，去掉 Multica 依赖

---

## 1. 项目愿景

**一句话：说一个需求，交付一个可上线的版本。**

不是 demo，不是 prototype，不是中看不中用的 POC。而是经过方案设计、代码实现、自动化测试、代码审查、质量门禁后，可以真正合并到主分支的交付物。

### 1.1 核心判断

当前 ai-team 的瓶颈**不是基础设施不足**（没有 PostgreSQL/没有 WebSocket/没有看板），而是**质量问题**：

1. Agent 不理解项目现有代码（无 codebase context injection）
2. 开发完没有自动跑测试验证（test → fix 循环缺失）
3. 代码审查反馈无法自动回流修改代码（loopback 太粗糙）
4. Agent prompt 太泛，没有针对项目定制

**先解决质量问题，再解决工程问题。** 基础设施（持久化、WebSocket、前端）在质量验证通过后再建设。

### 1.2 项目定位

将 ai-team 从一个 CLI 工具演进为一个 **平台**：
- 核心是 **编排引擎**（基于现有 ai-team runner，经过实战验证）
- 引擎可独立 CLI/API 运行
- 前端是自建轻量面板，专为 pipeline 监控设计
- 不依赖任何第三方平台（如 Multica）

---

## 2. 核心设计决策

### 2.1 技术选型

| 层级 | 技术 | 理由 |
|------|------|------|
| 编排引擎 | Python 3.11+ | 直接复用 ai-team runner 1925 行实战代码 |
| HTTP 服务 | FastAPI | 原生 async、WebSocket、自动 API 文档 |
| 数据库 | PostgreSQL 17 | 并发写入、后续扩展无技术债 |
| 前端 | React + Tailwind + shadcn/ui | 轻量、组件丰富、pipeline 场景够用 |
| 实时通信 | WebSocket (FastAPI) | agent 执行可能 30 分钟，轮询不合适 |
| 代码隔离 | Git Worktree | per-run 隔离，develop + verify 共享同一 worktree |
| 部署 | Docker Compose | Engine + PostgreSQL + 前端 |

**为什么不用 Multica？**
- Multica 是通用看板系统，Issue/Agent/Project 模型与 pipeline/run/stage 概念是强行映射
- API 不稳定（几天一版），集成维护成本高
- 个人/小团队场景下，一个专门的 pipeline 面板比通用看板更合适
- 技术栈统一（Python 全栈），不引入 Go 生态

### 2.2 架构原则

1. **引擎是核心，前端是可选项** — `python3 run.py` 仍然可用，不依赖任何服务
2. **质量优先于工程** — Phase 0 先证明"pipeline 能交付好代码"，再建基础设施
3. **产物即状态** — 文件系统的产物契约保持不变，持久化层在文件之上叠加
4. **Agent 是可替换的执行单元** — Hermes、Claude Code、Codex 通过统一接口调用
5. **渐进式演进** — 每个 Phase 独立可用，不依赖后续 Phase

---

## 3. 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        用户交互层                                 │
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐  │
│  │  Pipeline Dashboard  │  │    CLI (ai-team run.py)          │  │
│  │  (React SPA)         │  │    (现有能力，保持兼容)           │  │
│  │  - Pipeline 列表     │  │                                  │  │
│  │  - 执行进度监控      │  │                                  │  │
│  │  - Agent 实时输出    │  │                                  │  │
│  │  - 产物查看/下载     │  │                                  │  │
│  │  - Pipeline 编辑     │  │                                  │  │
│  └─────────┬────────────┘  └──────────────┬───────────────────┘  │
└────────────┼──────────────────────────────┼──────────────────────┘
             │ REST API                      │ 直接调用
             │ WebSocket (实时进度)          │
┌────────────▼──────────────────────────────▼──────────────────────┐
│                  Workflow Engine (Python / FastAPI)                │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Pipeline Orchestrator (核心，基于现有 ai-team runner)      │  │
│  │  - 阶段串联/并行执行                                       │  │
│  │  - 输入输出契约                                             │  │
│  │  - loopback 回流机制                                       │  │
│  │  - verify_cmd 真实验证                                     │  │
│  │  - human_review 审查门                                     │  │
│  │  - when 条件执行                                           │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────┐ ┌──────────────┐ ┌────────────────────────┐  │
│  │  Context       │ │  Worktree    │ │  Quality Gates         │  │
│  │  Scanner       │ │  Manager     │ │  (编译/测试/审查/安全)  │  │
│  │  (代码上下文)  │ │  (代码隔离)  │ │  (Phase 0 核心)         │  │
│  └────────────────┘ └──────────────┘ └────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  REST API + WebSocket Server (FastAPI)                      │  │
│  └────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬──────────────────────────────────┘
                                │ subprocess
┌───────────────────────────────▼──────────────────────────────────┐
│                     Agent Runtime Layer                           │
│  ┌──────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────┐   │
│  │ Hermes   │  │  Claude Code │  │  Codex   │  │  OpenCode  │   │
│  │(待验证)  │  │  (已验证)    │  │  (备选)  │  │  (备选)    │   │
│  └──────────┘  └──────────────┘  └──────────┘  └────────────┘   │
└───────────────────────────────┬──────────────────────────────────┘
                                │ git worktree (代码隔离)
┌───────────────────────────────▼──────────────────────────────────┐
│                     项目代码仓库                                   │
│  main ─────●────●────●────●────●────●────●── (稳定分支)          │
│              │                                                  │
│  worktree ───┘  develop + verify 共享同一个 worktree              │
│              全部通过后 squash merge 回 main                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. 功能需求

### 4.1 Phase 0：质量优先（核心阶段）

> 目标：让单次需求的交付质量从"demo 级"提升到"可合并"级别。
> 工期：3-4 周

#### 4.1.1 Codebase Context Scanner

**问题**：当前 tech-lead agent 拿到的只有 requirement + solution-draft.md，完全不知道项目现有代码长什么样。这是 demo 级交付的根本原因——agent 在"盲写"。

**方案**：在 develop 阶段开始前，自动扫描项目并生成上下文摘要，注入到 agent prompt 中。

**扫描内容**：

```
1. 项目结构（目录树，排除 node_modules/.git/build 等）
2. 框架识别（SwiftUI / Next.js / Spring Boot 等）
3. 依赖清单（Package.swift / package.json / pom.xml 等）
4. 编码规范（.swiftlint.yml / .eslintrc / .editorconfig 等）
5. 关键文件内容：
   - 入口文件（App.swift / main.ts / Application.java）
   - 数据模型（Models/ / models/ / domain/）
   - 路由/API 定义
   - 现有测试文件（了解测试风格）
6. 最近变更（git log --oneline -20）
```

**注入策略**：

- 方案阶段（plan/architect）：注入项目结构 + 框架识别 + 最近变更
- 开发阶段（develop）：注入上述全部 + 相关文件内容
- 审查阶段（verify）：注入变更文件 diff + 相关上下文

**配置**：

```yaml
context_scanner:
  enabled: true
  # 需要排除的目录
  exclude_dirs:
    - node_modules
    - .git
    - build
    - .build
    - DerivedData
    - Pods
  # 最大注入文件大小（字符数），超过则截断
  max_file_size: 50000
  # 需要扫描的文件 glob 模式
  include_patterns:
    - "**/*.swift"
    - "**/*.ts"
    - "**/*.tsx"
    - "**/*.py"
    - "**/Package.swift"
    - "**/package.json"
    - "**/*.md"  # README / CHANGELOG
  # 关键文件（始终注入完整内容）
  key_files:
    - "AGENTS.md"
    - "CLAUDE.md"
    - ".swiftlint.yml"
    - ".eslintrc.*"
```

**实现**：Python 模块，`context_scanner.py`，被 orchestrator 在每个阶段开始时调用。

#### 4.1.2 Worktree Manager

**问题**：当前 ai-team 所有 agent 在同一个工作目录操作，多 Agent 并行必然冲突。而且直接在 main 分支改代码，失败后需要手动回滚。

**方案**：per-run worktree 隔离。

**核心逻辑**：

```
1. pipeline run 开始时：
   - 基于 main 分支创建一个 worktree: .ai/worktrees/<run-id>/
   - plan/architect 阶段不需要 worktree（只读项目）

2. develop 阶段：
   - 在 worktree 中执行
   - agent 的 cwd 设为 worktree 路径

3. verify 阶段（QA / Code Reviewer）：
   - 在同一个 worktree 中执行
   - reviewer 看到的是 developer 的实际产出（不是 main 分支的干净代码）
   - quality gates（编译/测试）也在 worktree 中执行

4. pipeline 全部通过后：
   - squash merge worktree → main
   - 清理 worktree

5. pipeline 失败/取消时：
   - 清理 worktree（不合并）
   - main 分支不受影响
```

**为什么是 per-run 而不是 per-stage**：

- per-stage（我之前的方案）有逻辑缺陷：develop 和 verify 在不同 worktree，reviewer 看不到 developer 的代码
- per-run 让 develop + verify 共享同一个 worktree，审查的是真实产出
- plan/architect 不改代码，不需要 worktree

**合并策略**：

```yaml
worktree:
  enabled: true
  strategy: "per-run"           # 一个 pipeline run 一个 worktree
  base_branch: "main"
  merge_strategy: "squash"      # squash | merge-commit
  auto_cleanup: true            # pipeline 结束后自动清理
  merge_on_conflict: "pause"    # pause (暂停等人工) | abort (直接失败)
```

**异常处理**：
- 合并冲突：暂停 pipeline，输出冲突文件列表，等待人工解决后 resume
- 引擎崩溃重启：检测残留 worktree，提供 `ai-team cleanup` 命令
- 磁盘空间不足：合并前检查，不足时 fail-fast

#### 4.1.3 Quality Gates（简化版）+ Test-Fix 循环

**问题**：当前 pipeline 是线性的——develop 失败就停，测试失败也直接停。没有自动修复循环。

**方案**：在 develop 阶段之后、verify 阶段之前，插入质量门禁 + 自动重试循环。

**执行流程**：

```
develop 阶段完成
    │
    ▼
Quality Gate 1: 编译 (swift build / npm run build)
    │
    ├── 通过 → 继续
    │
    └── 失败 → 把编译错误注入 developer agent prompt → 重试 develop
                │
                ├── 重试成功 → 回到 Quality Gate 1
                │
                └── 超过 max_retries → pipeline 失败，报告错误
    │
    ▼
Quality Gate 2: 测试 (swift test / npm test)
    │
    ├── 通过 → 继续
    │
    └── 失败 → 把测试失败输出注入 developer agent prompt → 重试 develop
                │
                ├── 重试成功 → 回到 Quality Gate 2
                │
                └── 超过 max_retries → pipeline 失败，报告错误
    │
    ▼
verify 阶段 (QA + Code Reviewer)
```

**配置**：

```yaml
quality_gates:
  - name: "编译通过"
    type: command
    command: "swift build -c debug"
    required: true                    # 失败则阻断
    max_retries: 3                    # 自动重试次数
    retry_stage: "develop"            # 重试哪个阶段

  - name: "单元测试"
    type: command
    command: "swift test --parallel"
    required: true
    max_retries: 3
    retry_stage: "develop"

  - name: "代码覆盖率 > 80%"
    type: threshold
    command: "swift test --coverage"
    parse: "regex:Total coverage: ([\\d.]+)%"
    threshold: 80
    operator: ">="
    required: false                   # 不通过只警告，不阻断
    max_retries: 1

  - name: "安全扫描"
    type: command
    command: "tirith scan ."
    required: true
    max_retries: 1
```

**重试机制**：

重试时，把以下信息注入到 developer agent 的 prompt 中：

```markdown
## 质量门禁失败反馈（第 N 次重试）

### 失败门禁：编译通过
### 命令：swift build -c debug
### 错误输出：
```
<actual error output>
```
### 请修复以上错误后重新提交。
```

这与现有 loopback 机制类似，但 loopback 是 verify 阶段触发回到 develop，而 quality_gates 是 develop 阶段之后立即触发。两者共存不冲突。

#### 4.1.4 Agent Prompt 增强

**问题**：所有 agent 用通用 prompt，没有项目级定制。

**方案**：在现有 agent prompt 基础上，通过项目级配置增强关键行为。

**solution-architect 增强**：

```markdown
## 输出要求（增强）
你的方案必须包含一个"实施清单"章节：
- 需要修改的文件列表（路径 + 修改原因）
- 需要新建的文件列表（路径 + 职责）
- 需要修改的配置/依赖
- 预估影响范围（哪些模块会受影响）
```

**tech-lead 增强**：

```markdown
## 工作流程（增强）
1. 先阅读实施清单中列出的文件，理解现有代码
2. 按实施清单逐文件修改，不要跳过
3. 每个文件修改后，说明修改内容
4. 全部修改完成后，运行验证命令确认编译通过
5. 如果编译失败，根据错误信息修复

## 证据要求（增强）
- 必须列出每个修改的文件及其变更摘要
- 必须说明验证命令的实际输出
```

**code-reviewer 增强**：

```markdown
## 审查增强
- 检查实施清单中的所有文件是否都已修改
- 检查修改是否符合项目编码规范（参考注入的 lint 配置）
- 检查是否有遗漏的边界场景
- 如果存在"假设已修改但实际未修改"的结论，标记为 Critical
```

**配置方式**：

项目级 `.ai/agents/` 目录下的 prompt 文件会覆盖默认 prompt：

```
项目根目录/
  .ai/
    team.yaml
    agents/
      tech-lead.md        # 覆盖默认 tech-lead prompt
      code-reviewer.md    # 覆盖默认 code-reviewer prompt
```

prompt 解析优先级：
1. 项目 `.ai/agents/<name>.md`（项目级定制）
2. team.yaml 中 `prompt:` 指定的路径
3. skill 目录 `agents/<name>.md`（默认）

这与现有机制一致，只是文档中更明确地推荐项目级定制。

#### 4.1.5 简单 API（无持久化）

**问题**：纯 CLI 无法被外部系统（如后续的前端）调用。

**方案**：提供一个极简 FastAPI 服务，只做"触发运行 + 查看状态 + 获取产物"，不持久化。

**API 端点**：

```
POST   /api/runs                    # 触发 pipeline 执行
  Body: { "requirement": "...", "workdir": "/path/to/project" }
  Response: { "run_id": "...", "output_dir": "..." }

GET    /api/runs                    # 列出正在运行的 pipeline
  Response: [{ "run_id": "...", "status": "running", "pipeline": "..." }]

GET    /api/runs/{id}               # 获取执行状态（从文件系统读取）
  Response: { "status": "...", "stages": [...], "artifacts": [...] }

GET    /api/runs/{id}/artifacts     # 列出产物文件
GET    /api/runs/{id}/artifacts/{file}  # 下载产物文件

WS     /ws/runs/{id}                # 实时输出流
```

**实现要点**：
- 状态从文件系统读取（`.ai/team-output/*/report.json`），不依赖数据库
- WebSocket 推送 agent 实时输出（复用 run.py 的 stream_process_output 逻辑）
- `ai-team serve` 命令启动服务

---

### 4.2 Phase 1：持久化 + 前端面板

> 目标：pipeline 执行可观察、可管理、可追溯。
> 工期：2-3 周

#### 4.2.1 PostgreSQL 持久化

**数据模型**：

```sql
-- Pipeline 定义
CREATE TABLE pipeline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    project_path TEXT NOT NULL,
    config JSONB NOT NULL,          -- 完整的 team.yaml 内容
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Pipeline 版本历史
CREATE TABLE pipeline_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL REFERENCES pipeline(id) ON DELETE CASCADE,
    version INT NOT NULL,
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(pipeline_id, version)
);

-- Pipeline 执行实例
CREATE TABLE pipeline_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID REFERENCES pipeline(id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    project_root TEXT NOT NULL,
    main_branch TEXT NOT NULL DEFAULT 'main',
    requirement TEXT,
    trigger_source TEXT NOT NULL DEFAULT 'manual'
        CHECK (trigger_source IN ('manual', 'api', 'webhook')),
    worktree_path TEXT,
    context JSONB NOT NULL DEFAULT '{}',
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_seconds FLOAT
);

-- 阶段执行实例
CREATE TABLE stage_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_run_id UUID NOT NULL REFERENCES pipeline_run(id) ON DELETE CASCADE,
    stage_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    iteration INT NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped', 'cancelled')),
    is_parallel BOOLEAN NOT NULL DEFAULT false,
    loopback_from TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds FLOAT,
    output_dir TEXT,
    UNIQUE(pipeline_run_id, stage_id, iteration)
);

-- Agent 执行实例
CREATE TABLE agent_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stage_run_id UUID NOT NULL REFERENCES stage_run(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    role TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'timeout', 'cancelled')),
    output_file TEXT,
    raw_log_file TEXT,
    exit_code INT,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds FLOAT
);

-- 质量门禁执行记录
CREATE TABLE quality_gate_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stage_run_id UUID NOT NULL REFERENCES stage_run(id) ON DELETE CASCADE,
    gate_name TEXT NOT NULL,
    gate_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'passed', 'failed', 'skipped')),
    command TEXT,
    exit_code INT,
    output TEXT,
    required BOOLEAN NOT NULL DEFAULT true,
    retry_count INT NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- 索引
CREATE INDEX idx_pipeline_run_status ON pipeline_run(status, created_at DESC);
CREATE INDEX idx_pipeline_run_pipeline ON pipeline_run(pipeline_id, created_at DESC);
CREATE INDEX idx_stage_run_pipeline ON stage_run(pipeline_run_id, iteration);
CREATE INDEX idx_agent_run_stage ON agent_run(stage_run_id);
CREATE INDEX idx_quality_gate_stage ON quality_gate_run(stage_run_id);
```

#### 4.2.2 Pipeline Dashboard（前端面板）

**技术栈**：React + TypeScript + Tailwind CSS + shadcn/ui

**页面结构**：

```
/dashboard                    # 仪表盘：最近的 pipeline 运行概览
/pipelines                    # Pipeline 列表（模板库）
/pipelines/{id}               # Pipeline 详情 + 配置编辑
/runs                         # 执行记录列表
/runs/{id}                    # 单次执行详情（核心页面）
  ├── 执行状态时间线（阶段 + agent 状态）
  ├── Agent 实时输出（WebSocket 推送）
  ├── 质量门禁结果
  ├── 产物文件列表（可查看/下载）
  └── loopback 回流记录
/settings                      # 全局设置（provider 配置等）
```

**核心页面：Run Detail**

这是最有价值的页面，需要展示：

```
┌─────────────────────────────────────────────────┐
│  Pipeline: LifeRhythm 标准交付  Run #42         │
│  Status: ● running    Started: 10:23    Elapsed: 15m │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌─ plan (parallel) ────── ✓ done (2m) ───────┐ │
│  │  ✓ brainstormer   2m  brainstorm.md         │ │
│  │  ✓ devils-advocate 1m  gap-analysis.md      │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ architect ─────────── ✓ done (3m) ────────┐ │
│  │  ✓ solution-architect 3m  solution-draft.md │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ develop ────────────── ● running (8m) ─────┐ │
│  │  ● tech-lead   8m                           │ │
│  │                                              │ │
│  │  [Agent 实时输出]                             │ │
│  │  > Reading Project.swift...                   │ │
│  │  > Found 3 companion views to modify         │ │
│  │  > Creating CheckinViewModel.swift...         │ │
│  │  > █                                        │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ quality_gates ─────── ○ pending ───────────┐ │
│  │  ○ 编译通过                                   │ │
│  │  ○ 单元测试                                   │ │
│  │  ○ 代码覆盖率                                 │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ verify (parallel) ──── ○ pending ───────────┐ │
│  │  ○ qa-automation                              │ │
│  │  ○ code-reviewer                              │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ accept ─────────────── ○ pending ───────────┐ │
│  │  ○ human_review                               │ │
│  └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

**WebSocket 事件**：

```
run:started          { run_id, pipeline_id, requirement }
stage:started        { run_id, stage_id, stage_name, iteration }
agent:started        { run_id, stage_id, agent_name }
agent:output         { run_id, stage_id, agent_name, text }     # 实时输出
agent:heartbeat      { run_id, stage_id, agent_name, elapsed }
agent:completed      { run_id, stage_id, agent_name, status, duration }
gate:started         { run_id, gate_name }
gate:result          { run_id, gate_name, status, output }
loopback:triggered   { run_id, from_stage, to_stage, iteration }
stage:completed      { run_id, stage_id, status, duration }
run:completed        { run_id, status, summary }
```

#### 4.2.3 Cost Tracking

每次 pipeline 运行记录：
- 总耗时
- 各 agent 耗时
- 总 token 消耗（从 agent 输出中解析，如果 provider 支持）

用于优化 prompt 和选择 provider。

---

### 4.3 Phase 2：高级能力

> 目标：从"能跑"到"好用"。
> 工期：按需

**功能清单**：

1. **可视化 Pipeline 编辑器**
   - 基于 React Flow 的拖拽编辑器
   - 节点类型：Agent 执行、条件判断、并行分支、人工审查、质量门禁
   - 保存后同步到 Workflow Engine

2. **CI/CD 集成**
   - pipeline 完成后自动创建 PR（GitHub CLI）
   - 触发 CI 检查，结果反馈到 pipeline 状态

3. **Webhook 触发**
   - GitHub PR 创建 / Issue 标签变更时自动触发 pipeline

4. **Pipeline 模板库**
   - 预设模板：iOS 项目、Web 项目、后端服务、通用
   - 社区贡献模板

5. **增量修改增强**
   - 让 agent 只修改需要改的文件
   - 支持逐步修改（先改一个文件，测试通过，再改下一个）

6. **Agent 能力评估**
   - 记录每个 agent/provider 在不同项目上的交付质量
   - 为 provider 选择提供数据支撑

---

## 5. 项目级配置（完整示例）

```yaml
# .ai/team.yaml (LifeRhythm 项目)

metadata:
  name: "LifeRhythm 标准交付"
  version: "1.0"

# Provider 配置（现有，保持不变）
providers:
  Claude:
    cli: claude
    args: ["-p", "--output-format", "stream-json"]
    output_format: claude-stream-json

# Agent 定义（现有，保持不变）
agents:
  - name: architect
    provider: Claude
    role: architect
    prompt: agents/solution-architect.md

  - name: developer
    provider: Claude
    role: developer
    prompt: agents/tech-lead.md

  - name: qa
    provider: Claude
    role: tester
    prompt: agents/qa-automation.md

  - name: reviewer
    provider: Claude
    role: reviewer
    prompt: agents/code-reviewer.md

# === 新增配置 ===

# 代码上下文扫描
context_scanner:
  enabled: true
  exclude_dirs:
    - node_modules
    - .git
    - build
    - .build
    - DerivedData
    - Pods
  max_file_size: 50000
  include_patterns:
    - "**/*.swift"
    - "**/Package.swift"
    - "AGENTS.md"
    - "CLAUDE.md"
    - ".swiftlint.yml"
  key_files:
    - "AGENTS.md"
    - "CLAUDE.md"

# Worktree 隔离
worktree:
  enabled: true
  strategy: "per-run"
  base_branch: "main"
  merge_strategy: "squash"
  auto_cleanup: true
  merge_on_conflict: "pause"

# 质量门禁
quality_gates:
  - name: "Swift 编译"
    type: command
    command: "swift build -c debug"
    required: true
    max_retries: 3
    retry_stage: "develop"

  - name: "单元测试"
    type: command
    command: "swift test --parallel"
    required: true
    max_retries: 3
    retry_stage: "develop"

  - name: "代码覆盖率"
    type: threshold
    command: "swift test --coverage"
    parse: "regex:Total coverage: ([\\d.]+)%"
    threshold: 80
    operator: ">="
    required: false
    max_retries: 1

# Pipeline 定义（现有，保持不变）
pipeline:
  - id: plan
    name: "方案讨论"
    parallel: true
    agents: [architect]
    input: requirement
    output:
      architect: solution-draft.md

  - id: develop
    name: "开发"
    agents: [developer]
    input: [requirement, solution-draft.md]
    output:
      developer: tech-lead-output.md

  - id: verify
    name: "测试 + 审查"
    parallel: true
    stop_parallel_on_first_error: false
    agents: [qa, reviewer]
    input: [requirement, solution-draft.md, "*-output.md"]
    output:
      qa: test-report.md
      reviewer: review-report.md
    loopback_to: develop
    loopback_trigger: "Request Changes"
    max_retries: 2

  - id: accept
    name: "人工验收"
    type: human_review

# Runner 配置（现有，保持不变）
runner:
  agent_timeout_seconds: 1800
  heartbeat_seconds: 60
  parallel_log_mode: interleaved

# 持久化（Phase 1 启用）
persistence:
  enabled: false
  database_url: ${AI_TEAM_DB_URL}
```

---

## 6. 目录结构

```
~/.agents/skills/ai-team/
├── SKILL.md                    # 现有 skill 定义（保持兼容）
├── team.yaml                   # 默认 pipeline 配置
├── agents/                     # Agent prompt 文件
│   ├── brainstormer.md
│   ├── devils-advocate.md
│   ├── solution-architect.md
│   ├── tech-lead.md
│   ├── qa-automation.md
│   └── code-reviewer.md
├── scripts/
│   ├── run.py                  # 现有 CLI runner（保持兼容，不改动）
│   ├── health-check.py         # 现有健康检查
│   ├── resolve_entry.py        # 现有入口解析
│   └── serve.py                # [Phase 0] FastAPI 服务入口
├── engine/                     # [Phase 0] 引擎核心模块
│   ├── __init__.py
│   ├── orchestrator.py         # Pipeline 编排（从 run.py 提取，非重构）
│   ├── config.py               # 配置加载与校验
│   ├── models.py               # Pydantic 数据模型
│   ├── agent_runner.py         # Agent 执行（从 run.py 提取）
│   ├── context_scanner.py      # [新增] 代码上下文扫描
│   ├── worktree.py             # [新增] Git Worktree 管理
│   ├── quality_gates.py        # [新增] 质量门禁 + Test-Fix 循环
│   └── events.py               # 内部事件系统
├── api/                        # [Phase 0] REST API
│   ├── __init__.py
│   ├── app.py                  # FastAPI app
│   ├── routes/
│   │   ├── runs.py
│   │   └── artifacts.py
│   └── ws.py                   # WebSocket handler
├── persistence/                # [Phase 1] 持久化层
│   ├── __init__.py
│   ├── database.py
│   ├── models.py               # SQLAlchemy 模型
│   └── migrations/
│       └── 001_init.up.sql
└── web/                        # [Phase 1] 前端
    ├── package.json
    ├── src/
    │   ├── App.tsx
    │   ├── pages/
    │   │   ├── Dashboard.tsx
    │   │   ├── RunDetail.tsx
    │   │   └── Settings.tsx
    │   └── components/
    │       ├── PipelineTimeline.tsx
    │       ├── AgentOutput.tsx
    │       └── QualityGateResult.tsx
    └── vite.config.ts
```

**关键约束**：Phase 0 不重构 `run.py`。`engine/` 下的模块是从 `run.py` **提取**（复制 + 适配），不是原地重构。`run.py` 保持原样，确保 CLI 兼容性。

---

## 7. 分阶段实施计划

### Phase 0：质量优先（3-4 周）

| 序号 | 任务 | 工期 | 对质量的影响 | 风险 |
|------|------|------|------------|------|
| 1 | Context Scanner | 1 周 | 直接决定 agent 能否写出贴合项目的代码 | 低（新模块，不影响现有代码） |
| 2 | Worktree Manager (per-run) | 1 周 | 解决多 Agent 并行安全问题 | 中（git worktree 边界情况多） |
| 3 | Quality Gates + Test-Fix 循环 | 3 天 | develop 后自动验证，失败自动重试 | 低（基于现有 verify_cmd 扩展） |
| 4 | Agent Prompt 增强 | 3 天 | 提升每个 agent 的输出质量 | 低（改 prompt 文件） |
| 5 | 简单 API (FastAPI) | 3 天 | 不直接提升质量，为 Phase 1 前端铺路 | 低 |

**不做**：
- 不重构 run.py（提取而非重构）
- 不做 PostgreSQL
- 不做前端
- 不做 Multica

**验收标准**：
- 给 LifeRhythm 一个中等需求（如"实现一个新的 Companion 视图"）
- pipeline 全自动运行到 human_review 阶段
- develop 阶段后自动编译 + 测试通过
- 如果编译/测试失败，自动重试最多 3 次
- 代码在 worktree 中隔离，main 分支不受影响
- 全部通过后 squash merge 到 main

### Phase 1：持久化 + 前端（2-3 周）

| 序号 | 任务 | 工期 |
|------|------|------|
| 1 | PostgreSQL 持久化层 | 1 周 |
| 2 | WebSocket 实时推送 | 3 天 |
| 3 | Pipeline Dashboard 前端 | 1 周 |
| 4 | Cost Tracking | 2 天 |

### Phase 2：高级能力（按需）

- 可视化 Pipeline 编辑器
- CI/CD 集成
- Webhook 触发
- Pipeline 模板库
- Agent 能力评估

---

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Agent 输出质量不达标 | 高 | 高 | Context Scanner + Prompt 增强 + Quality Gates 三重保障 |
| Worktree 合并冲突 | 中 | 高 | 暂停 + 人工解决 + 自动恢复；Phase 0 只用 squash |
| Agent 执行超时 | 中 | 中 | 现有 timeout + heartbeat，增强重试策略 |
| run.py 提取引入差异 | 中 | 中 | 提取而非重构，run.py 保持原样不动 |
| 前端工期超支 | 中 | 低 | Phase 1 独立可用，前端延期不影响引擎 |

---

## 9. 成功指标

### Phase 0 完成后：
- 给一个中等复杂度需求，pipeline 全自动到 human_review 阶段（除人工验收外零干预）
- develop 阶段后自动编译 + 测试通过（或自动重试后通过）
- 代码在 worktree 中隔离，main 分支安全
- 全部通过后可 squash merge 到 main
- 所有产物可追溯

### Phase 1 完成后增加：
- 在 Web 面板看到 pipeline 实时执行进度
- Agent 输出实时流式展示
- 历史执行记录可查询

### Phase 2 完成后增加：
- 拖拽编辑 pipeline
- CI/CD 自动集成
- 多项目并行管理

---

## 附录 A：与现有 ai-team 的兼容性

所有现有用法保持不变：
- `python3 run.py "需求描述"` — 仍然可用
- `python3 run.py --spec-file docs/spec.md --yes` — 仍然可用
- `python3 run.py --resume latest --only-stage verify` — 仍然可用
- `.ai/team.yaml` — 现有字段全部兼容，新增字段为 optional

`persistence.enabled` 默认 `false`。不配置 PostgreSQL 时，`ai-team serve` 以文件系统模式运行，行为与现在一致。

## 附录 B：Phase 0 不做什么（以及为什么）

| 不做 | 理由 |
|------|------|
| 不重构 run.py | 1925 行零测试，重构风险高。采用提取策略，run.py 保持原样 |
| 不做 PostgreSQL | Phase 0 的核心是质量，不是持久化。文件系统够用 |
| 不做前端 | 没有 API 和持久化，前端无数据可展示 |
| 不做 Multica | ROI 不高，自建面板更合适 |
| 不做部署集成 | 你说放一放 |
| 不做可视化编辑器 | 没有前端基础，编辑器无从谈起 |

## 附录 C：brave-cabin 评审回复

| 评审意见 | 回应 |
|---------|------|
| 方向偏差，基础设施 ≠ 质量 | 接受。Phase 0 重排为质量优先 |
| Worktree per-stage 有缺陷 | 接受。改为 per-run |
| Quality Gates 放 Phase 3 不对 | 接受。提到 Phase 0 |
| Codebase Context Injection 缺失 | 接受。新增为 Phase 0 第一优先级 |
| Test-Fix 循环缺失 | 接受。新增到 Quality Gates |
| 工期估算不足 | 接受。Phase 0 调整为 3-4 周，不重构 run.py |
| 不需要 Multica | 接受。自建前端面板 |
| 用 SQLite 替代 PostgreSQL | 不接受。并发写入会锁库，且后续迁移成本更高 |
| 不需要 WebSocket，用轮询 | 不接受。agent 可能跑 30 分钟，轮询不合适 |
