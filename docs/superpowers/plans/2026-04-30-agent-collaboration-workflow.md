# Agent Collaboration Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the default AI Team agent collaboration workflow so code context comes before planning, human gates cannot be auto-approved, rejections require reasons and loop back, and agents exchange validated artifacts through orchestrator-injected context.

**Architecture:** Keep Orchestrator as the single scheduler. Add explicit human-decision and artifact-contract models, route hard human gates through structured decisions, and move the default pipeline to context-first requirements synthesis, planning, single-agent development, QA, review, acceptance, and retrospect. UI and API expose human decisions as first-class actions instead of using `resume?yes=true` as an approval shortcut.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, unittest/pytest-compatible tests, React 18, TypeScript, Vite, Vitest.

---

## Preflight Constraints

- The current working tree may contain unrelated staged and unstaged changes. Before implementation, run `git status --short --branch` and use a dedicated worktree or commit only explicit plan files.
- Do not include `.coverage` or unrelated runtime/settings/frontend changes in commits for this work unless they are intentionally modified by a task below.
- Local validation commands should use `.venv/bin/python`, not `/usr/bin/python3`, because the project requires Python 3.11+ and the repository `.venv` is Python 3.12.

## Target File Structure

- Modify: `templates/team.yaml`  
  Owns the default workflow and stage contracts.
- Modify: `engine/models.py`  
  Owns serializable run, stage, human decision, artifact validation, and checkpoint models.
- Create: `engine/human_gate.py`  
  Owns hard human gate semantics, decision validation, decision artifact rendering, and reject feedback rendering.
- Create: `engine/artifact_contracts.py`  
  Owns lightweight artifact schema validation for stage outputs.
- Create: `engine/stage_context.py`  
  Owns stage context package construction and prompt rendering inputs.
- Modify: `engine/orchestrator.py`  
  Owns scheduling, human decision handling, reject loopback, artifact validation, checkpoint persistence, and stage cwd policy.
- Modify: `api/runtime.py`  
  Passes explicit human decisions to background resume.
- Modify: `api/routes/runs.py`  
  Adds explicit human decision endpoint and blocks empty reject reason.
- Modify: `web/src/lib/types.ts`  
  Adds human decision and artifact validation types.
- Modify: `web/src/lib/api.ts`  
  Adds `submitHumanDecision`.
- Modify: `web/src/components/PipelineTimeline.tsx`  
  Shows hard gate actions, reject reason input, decision history, and validation state.
- Modify: `web/src/pages/RunDetail.tsx`  
  Refreshes run detail after decision submission.
- Modify: `web/src/styles.css`  
  Adds gate and validation styling.
- Test: `tests/test_config.py`
- Test: `tests/test_engine.py`
- Test: `tests/test_routes.py`
- Test: `web/src/test/HumanGateActions.test.tsx`

---

### Task 1: Default Pipeline and Config Contract

**Files:**
- Modify: `templates/team.yaml`
- Modify: `engine/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests for the new default workflow**

Add this test class to `tests/test_config.py`:

```python
class TestDefaultAgentCollaborationWorkflow(unittest.TestCase):
    def test_default_pipeline_is_context_first_and_has_hard_human_gates(self) -> None:
        from engine.config import load_config

        loaded = load_config(Path.cwd())
        stages = loaded.config["pipeline"]
        stage_ids = [stage["id"] for stage in stages]

        self.assertEqual(
            stage_ids,
            [
                "context_scan",
                "requirement_analysis",
                "requirement_synthesis",
                "requirement_confirm",
                "planning",
                "task_plan_confirm",
                "develop",
                "qa",
                "review",
                "acceptance_confirm",
                "retrospect",
            ],
        )
        self.assertLess(stage_ids.index("context_scan"), stage_ids.index("requirement_synthesis"))
        self.assertLess(stage_ids.index("context_scan"), stage_ids.index("planning"))

        gates = {stage["id"]: stage for stage in stages if stage.get("type") == "human_review"}
        self.assertEqual(set(gates), {"requirement_confirm", "task_plan_confirm", "acceptance_confirm"})
        for gate in gates.values():
            self.assertFalse(gate.get("allow_auto_approve"))
            self.assertTrue(gate.get("requires_reason_on_reject"))
            self.assertNotIn("skip_if_no_blocker", gate)

    def test_default_pipeline_removes_ambiguous_or_duplicate_stages(self) -> None:
        from engine.config import load_config

        loaded = load_config(Path.cwd())
        stage_ids = [stage["id"] for stage in loaded.config["pipeline"]]

        self.assertNotIn("plan_confirm", stage_ids)
        self.assertNotIn("architect", stage_ids)
        self.assertNotIn("code_apply", stage_ids)
        self.assertNotIn("risk_analysis", stage_ids)
        self.assertNotIn("doc", stage_ids)
```

- [ ] **Step 2: Run the new config tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_config.TestDefaultAgentCollaborationWorkflow -v
```

Expected: fails because the current default pipeline still includes `architect`, `code_apply`, `risk_analysis`, `doc`, and the old gate semantics.

- [ ] **Step 3: Update `templates/team.yaml` default pipeline**

Replace the current `pipeline.stages` body with this stage list. Keep existing `runtimes`, `agents`, `worktree`, and `runner` sections unless a prompt reference below requires a new agent entry.

```yaml
pipeline:
  execution_mode: parallel
  stages:
    - id: context_scan
      name: "代码库扫描"
      type: context_scan
      output_file: codebase-context.md
      output_json: codebase-context.json

    - id: requirement_analysis
      name: "需求分析"
      parallel: true
      agents: [requirements-analyst, devils-advocate]
      input: [requirement, codebase-context.md, codebase-context.json]
      output:
        requirements-analyst: requirement-analysis.md
        devils-advocate: requirement-gap-analysis.md
      required_artifacts:
        - requirement-analysis.md
        - requirement-gap-analysis.md

    - id: requirement_synthesis
      name: "需求综合定稿"
      parallel: false
      agents: [requirements-analyst]
      input:
        - requirement
        - codebase-context.md
        - codebase-context.json
        - requirement-analysis.md
        - requirement-gap-analysis.md
        - human-decision-requirement*.json
      output:
        requirements-analyst: requirement-final.md
      required_artifacts:
        - requirement-final.md

    - id: requirement_confirm
      name: "需求人工确认"
      type: human_review
      input: [requirement-final.md]
      output_file: human-decision-requirement.md
      decision_file: human-decision-requirement.json
      allow_auto_approve: false
      requires_reason_on_reject: true
      reject_to: requirement_synthesis

    - id: planning
      name: "方案与任务规划"
      parallel: false
      agents: [planner]
      input:
        - requirement-final.md
        - requirement-final.json
        - codebase-context.md
        - codebase-context.json
        - human-decision-requirement.json
        - human-decision-task-plan*.json
      output:
        planner: task-plan.md
      required_artifacts:
        - task-plan.md

    - id: task_plan_confirm
      name: "任务规划人工确认"
      type: human_review
      input: [task-plan.md]
      output_file: human-decision-task-plan.md
      decision_file: human-decision-task-plan.json
      allow_auto_approve: false
      requires_reason_on_reject: true
      reject_to: planning

    - id: develop
      name: "开发实施"
      parallel: false
      agents: [tech-lead]
      input:
        - requirement-final.md
        - requirement-final.json
        - codebase-context.md
        - codebase-context.json
        - task-plan.md
        - task-plan.json
        - human-decision-task-plan.json
        - human-decision-acceptance*.json
      output:
        tech-lead: implementation-report.md
      required_artifacts:
        - implementation-report.md

    - id: qa
      name: "自动测试"
      parallel: false
      agents: [qa-automation]
      input:
        - requirement-final.md
        - task-plan.md
        - implementation-report.md
        - git-diff
      output:
        qa-automation: test-report.md
      required_artifacts:
        - test-report.md
      loopback_to: develop
      loopback_trigger: ["FAILED", "ERROR", "失败", "exit code: 1", "退出码: 1"]
      max_retries: 2

    - id: review
      name: "代码审查与风险识别"
      parallel: false
      agents: [code-reviewer]
      input:
        - requirement-final.md
        - task-plan.md
        - implementation-report.md
        - test-report.md
        - git-diff
      output:
        code-reviewer: review-report.md
      required_artifacts:
        - review-report.md
      loopback_to: develop
      loopback_trigger: "Request Changes"
      max_retries: 2

    - id: acceptance_confirm
      name: "最终人工验收"
      type: human_review
      input:
        - requirement-final.md
        - task-plan.md
        - implementation-report.md
        - test-report.md
        - review-report.md
        - git-diff
      output_file: human-decision-acceptance.md
      decision_file: human-decision-acceptance.json
      allow_auto_approve: false
      requires_reason_on_reject: true
      reject_to: develop

    - id: retrospect
      name: "结果复盘"
      parallel: false
      agents: [retrospect]
      input:
        - requirement-final.md
        - task-plan.md
        - implementation-report.md
        - test-report.md
        - review-report.md
        - human-decision-acceptance.json
        - git-diff
      output:
        retrospect: retrospect-report.md
      json_artifacts:
        - retrospect-report.json
      required_artifacts:
        - retrospect-report.md
        - retrospect-report.json
```

- [ ] **Step 4: Update `engine/config.py` fallback `DEFAULT_CONFIG`**

Mirror the same stage order and hard gate fields in `DEFAULT_CONFIG["pipeline"]` so behavior is consistent when `templates/team.yaml` is unavailable.

- [ ] **Step 5: Run config tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_config.TestDefaultAgentCollaborationWorkflow -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add templates/team.yaml engine/config.py tests/test_config.py
git commit -m "feat: redefine default agent workflow"
```

---

### Task 2: Human Decision Models and Hard Gate Semantics

**Files:**
- Modify: `engine/models.py`
- Create: `engine/human_gate.py`
- Modify: `engine/orchestrator.py`
- Test: `tests/test_engine.py`

- [ ] **Step 1: Write failing engine tests for non-auto-approved hard gates and reject loopback**

Add this test class to `tests/test_engine.py`:

```python
class TestHardHumanGateWorkflow(unittest.TestCase):
    def _write_config(self, root: Path) -> Path:
        config = root / "team.yaml"
        config.write_text(
            """
runtimes:
  Req:
    cli: mock
    response: "final requirement"
  Plan:
    cli: mock
    response: "task plan"
agents:
  - name: req
    runtime_id: Req
    role: analyst
    prompt: agents/req.md
  - name: planner
    runtime_id: Plan
    role: planner
    prompt: agents/planner.md
pipeline:
  - id: requirement_synthesis
    name: Requirement Synthesis
    agents: [req]
    input: requirement
    output:
      req: requirement-final.md
  - id: requirement_confirm
    name: Requirement Confirm
    type: human_review
    output_file: human-decision-requirement.md
    decision_file: human-decision-requirement.json
    allow_auto_approve: false
    requires_reason_on_reject: true
    reject_to: requirement_synthesis
  - id: planning
    name: Planning
    agents: [planner]
    input: [requirement-final.md, human-decision-requirement.json]
    output:
      planner: task-plan.md
worktree:
  enabled: false
""",
            encoding="utf-8",
        )
        (root / "agents").mkdir()
        (root / "agents" / "req.md").write_text("You finalize requirements.", encoding="utf-8")
        (root / "agents" / "planner.md").write_text("You plan tasks.", encoding="utf-8")
        return config

    def test_hard_human_gate_waits_even_when_yes_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)

            report = Orchestrator(root, config_path=str(config)).run("ship auth", run_id="gate-waits", yes=True)

            self.assertEqual(report.status, "waiting")
            gate = report.stages[-1]
            self.assertEqual(gate.stage_id, "requirement_confirm")
            self.assertEqual(gate.status, "waiting")
            output_dir = Path(report.output_dir)
            self.assertTrue((output_dir / "checkpoint.json").exists())
            decision = json.loads((output_dir / "human-decision-requirement.json").read_text(encoding="utf-8"))
            self.assertEqual(decision["decision"], "waiting")

    def test_reject_decision_requires_reason_and_loops_back_to_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            waiting = Orchestrator(root, config_path=str(config)).run("ship auth", run_id="gate-reject")
            self.assertEqual(waiting.status, "waiting")

            decision = HumanDecision(
                stage_id="requirement_confirm",
                decision="rejected",
                reason="需求没有说明登录失败提示",
                required_changes=["补充登录失败提示验收标准"],
                target_stage="requirement_synthesis",
            )
            resumed = Orchestrator(root, config_path=str(config)).run(
                "ship auth",
                run_id="gate-reject",
                resume=True,
                human_decision=decision,
            )

            self.assertEqual(resumed.status, "waiting")
            stage_ids = [stage.stage_id for stage in resumed.stages]
            self.assertGreaterEqual(stage_ids.count("requirement_synthesis"), 2)
            feedback = Path(resumed.output_dir) / "human-feedback-requirement_confirm-1.md"
            self.assertTrue(feedback.exists())
            self.assertIn("需求没有说明登录失败提示", feedback.read_text(encoding="utf-8"))
```

Also add imports at the top of `tests/test_engine.py`:

```python
import json
from engine.models import HumanDecision
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_engine.TestHardHumanGateWorkflow -v
```

Expected: fails because `HumanDecision` does not exist and `yes=True` currently auto-approves waiting gates.

- [ ] **Step 3: Add human decision models to `engine/models.py`**

Add after `QualityGateRun`:

```python
HumanDecisionValue = Literal["waiting", "approved", "rejected"]


class HumanDecision(BaseModel):
    stage_id: str
    decision: HumanDecisionValue
    reason: str = ""
    required_changes: List[str] = Field(default_factory=list)
    target_stage: Optional[str] = None
    decided_by: str = "human"
    decided_at: str = Field(default_factory=utc_now)

    def validate_for_stage(self, requires_reason_on_reject: bool = True) -> None:
        if self.decision == "rejected" and requires_reason_on_reject and not self.reason.strip():
            raise ValueError("reject reason is required")
```

Add to `StageRun`:

```python
    human_decision: Optional[HumanDecision] = None
    loopback_to: Optional[str] = None
```

Add to `RunReport`:

```python
    human_decisions: List[HumanDecision] = Field(default_factory=list)
```

- [ ] **Step 4: Create `engine/human_gate.py`**

Create:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .models import HumanDecision, utc_now

HARD_HUMAN_GATES = {"requirement_confirm", "task_plan_confirm", "acceptance_confirm"}


def is_hard_human_gate(stage: Dict[str, Any]) -> bool:
    return stage.get("type") == "human_review" and stage.get("id") in HARD_HUMAN_GATES


def decision_json_name(stage: Dict[str, Any]) -> str:
    return str(stage.get("decision_file") or f"human-decision-{stage.get('id', 'gate')}.json")


def decision_markdown_name(stage: Dict[str, Any]) -> str:
    return str(stage.get("output_file") or f"human-decision-{stage.get('id', 'gate')}.md")


def waiting_decision(stage: Dict[str, Any]) -> HumanDecision:
    return HumanDecision(
        stage_id=str(stage.get("id")),
        decision="waiting",
        target_stage=stage.get("reject_to"),
        decided_by="system",
        decided_at=utc_now(),
    )


def normalize_decision(stage: Dict[str, Any], decision: HumanDecision) -> HumanDecision:
    stage_id = str(stage.get("id"))
    if decision.stage_id != stage_id:
        raise ValueError(f"decision stage_id {decision.stage_id} does not match waiting stage {stage_id}")
    requires_reason = bool(stage.get("requires_reason_on_reject", True))
    decision.validate_for_stage(requires_reason_on_reject=requires_reason)
    if decision.decision == "rejected":
        target = decision.target_stage or stage.get("reject_to")
        if not target:
            raise ValueError(f"reject target is required for stage {stage_id}")
        decision.target_stage = str(target)
    return decision


def write_decision_artifacts(stage: Dict[str, Any], output_dir: Path, decision: HumanDecision) -> None:
    payload = decision.model_dump(mode="json")
    (output_dir / decision_json_name(stage)).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "## Human Decision",
        "",
        f"- Stage: `{decision.stage_id}`",
        f"- Decision: `{decision.decision}`",
        f"- Decided by: `{decision.decided_by}`",
        f"- Decided at: `{decision.decided_at}`",
    ]
    if decision.reason:
        lines.extend(["", "## Reason", "", decision.reason.strip()])
    if decision.required_changes:
        lines.extend(["", "## Required Changes"])
        lines.extend([f"- {item}" for item in decision.required_changes])
    if decision.target_stage:
        lines.extend(["", f"Loopback target: `{decision.target_stage}`"])
    (output_dir / decision_markdown_name(stage)).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def render_reject_feedback(decision: HumanDecision, retry_count: int) -> str:
    changes = "\n".join(f"- {item}" for item in decision.required_changes) or "- 未提供逐条修改项"
    return "\n".join(
        [
            f"## 人工拒绝反馈（第 {retry_count} 次）",
            "",
            f"Gate `{decision.stage_id}` 被人工拒绝。",
            "",
            "### 拒绝理由",
            decision.reason.strip(),
            "",
            "### 必须修改",
            changes,
            "",
            "只围绕以上人工拒绝理由修正，不扩大范围。不得重写已确认且未被拒绝的内容。",
        ]
    )
```

- [ ] **Step 5: Change `Orchestrator.run` signature**

Modify `engine/orchestrator.py` imports:

```python
from .human_gate import normalize_decision, render_reject_feedback, waiting_decision, write_decision_artifacts
from .models import AgentDefinition, AgentRun, HumanDecision, RequirementUnit, RequirementUnitProgress, RunReport, StageRun, model_to_dict, utc_now
```

Change `run` signature:

```python
        human_decision: Optional[HumanDecision] = None,
```

Thread `human_decision` through `_run_requirement_units` and `_run_stage_sequence`.

- [ ] **Step 6: Change `_run_human_review_stage`**

Replace the decision logic with:

```python
        if human_decision is None:
            decision = waiting_decision(stage)
            write_decision_artifacts(stage, output_dir, decision)
            stage_run.status = "waiting"
            stage_run.human_decision = decision
            stage_run.completed_at = utc_now()
            stage_run.duration_seconds = _duration(start)
            self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
            return stage_run

        try:
            decision = normalize_decision(stage, human_decision)
        except ValueError as exc:
            stage_run.status = "failed"
            stage_run.error_message = str(exc)
            stage_run.completed_at = utc_now()
            stage_run.duration_seconds = _duration(start)
            return stage_run

        write_decision_artifacts(stage, output_dir, decision)
        stage_run.human_decision = decision
        report.human_decisions.append(decision)
        if decision.decision == "approved":
            stage_run.status = "completed"
        elif decision.decision == "rejected":
            stage_run.status = "completed"
            stage_run.loopback_to = decision.target_stage
        else:
            stage_run.status = "waiting"
```

Remove the current `yes`, `reject`, `skip_if_no_blocker`, and `stdin` auto-approval branches for hard human gates. Keep non-hard legacy human stages only if needed by tests; hard gates must ignore `yes`.

- [ ] **Step 7: Add rejected human decision loopback handling in `_run_stage_sequence`**

After `output_content = self._stage_output_text(stage_run)`, add a branch before normal loopback trigger:

```python
            if stage_run.human_decision and stage_run.human_decision.decision == "rejected":
                target = stage_run.human_decision.target_stage
                if not target or target not in stage_index_by_id:
                    raise OrchestratorError(f"Human reject target not found: {target}")
                count = loop_counts.get(stage_id, 0) + 1
                loop_counts[stage_id] = count
                target_index = stage_index_by_id[target]
                target_stage_ids = {s.get("id") for s in stages[target_index:]}
                completed_stages[:] = [item for item in completed_stages if item not in target_stage_ids]
                extra_feedback = render_reject_feedback(stage_run.human_decision, count)
                feedback_file = artifact_dir / f"human-feedback-{stage_id}-{count}.md"
                feedback_file.write_text(extra_feedback, encoding="utf-8")
                self._save_checkpoint(report_dir, report.run_id, completed_stages, worktree_path, mode=checkpoint_mode, units=checkpoint_units)
                self._write_report(report, report_dir)
                index = target_index
                continue
```

- [ ] **Step 8: Include human decisions in checkpoint**

Modify `_save_checkpoint` signature to accept `human_decisions: Optional[List[HumanDecision]] = None`, and include:

```python
            "human_decisions": [model_to_dict(item) for item in human_decisions or []],
```

Pass `report.human_decisions` from `_run_stage_sequence` calls.

- [ ] **Step 9: Run hard gate tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_engine.TestHardHumanGateWorkflow -v
```

Expected: tests pass.

- [ ] **Step 10: Commit Task 2**

Run:

```bash
git add engine/models.py engine/human_gate.py engine/orchestrator.py tests/test_engine.py
git commit -m "feat: enforce hard human gate decisions"
```

---

### Task 3: Explicit API and Runtime Human Decision Flow

**Files:**
- Modify: `api/runtime.py`
- Modify: `api/routes/runs.py`
- Test: `tests/test_routes.py`

- [ ] **Step 1: Write failing route tests**

Add to `tests/test_routes.py` in `TestRunsRoutes`:

```python
    def test_human_decision_reject_requires_reason(self) -> None:
        run_id = "decision-reason-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": []}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "stages": [
                        {
                            "stage_id": "requirement_confirm",
                            "stage_name": "Requirement Confirm",
                            "status": "waiting",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        response = self.client.post(
            f"/api/runs/{run_id}/human-decision",
            params={"workdir": str(self.project_root)},
            json={"stage_id": "requirement_confirm", "decision": "rejected", "reason": ""},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.json()["detail"])

    def test_human_decision_endpoint_passes_structured_decision_to_runtime(self) -> None:
        run_id = "decision-submit-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": []}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "stages": [
                        {
                            "stage_id": "task_plan_confirm",
                            "stage_name": "Task Plan Confirm",
                            "status": "waiting",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch("api.runtime.resume_run_background", return_value=output_dir) as resume_bg:
            response = self.client.post(
                f"/api/runs/{run_id}/human-decision",
                params={"workdir": str(self.project_root)},
                json={
                    "stage_id": "task_plan_confirm",
                    "decision": "rejected",
                    "reason": "任务缺少回滚方案",
                    "required_changes": ["补充回滚方案"],
                    "target_stage": "planning",
                },
            )

        self.assertEqual(response.status_code, 200)
        decision = resume_bg.call_args.kwargs["human_decision"]
        self.assertEqual(decision.stage_id, "task_plan_confirm")
        self.assertEqual(decision.reason, "任务缺少回滚方案")
        self.assertEqual(decision.required_changes, ["补充回滚方案"])
```

- [ ] **Step 2: Run route tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_routes.TestRunsRoutes.test_human_decision_reject_requires_reason tests.test_routes.TestRunsRoutes.test_human_decision_endpoint_passes_structured_decision_to_runtime -v
```

Expected: fails because `/api/runs/{run_id}/human-decision` does not exist.

- [ ] **Step 3: Update `api/runtime.py`**

Import `HumanDecision`:

```python
from engine.models import HumanDecision, RunReport, utc_now
```

Change `resume_run_background` signature:

```python
def resume_run_background(
    run_id: str,
    workdir: str,
    yes: bool = False,
    reject: bool = False,
    config_path: Optional[str] = None,
    execution_mode: Optional[str] = None,
    human_decision: Optional[HumanDecision] = None,
) -> Path:
```

Pass it into `orchestrator.run`:

```python
orchestrator.run(
    requirement=requirement,
    run_id=run_id,
    yes=yes,
    reject=reject,
    resume=True,
    execution_mode=execution_mode,
    human_decision=human_decision,
)
```

- [ ] **Step 4: Add request model and endpoint to `api/routes/runs.py`**

Import `HumanDecision`:

```python
from engine.models import HumanDecision
```

Add model:

```python
class HumanDecisionRequest(BaseModel):
    stage_id: str
    decision: str
    reason: str = ""
    required_changes: List[str] = []
    target_stage: Optional[str] = None
```

Add endpoint after `resume_run`:

```python
    @router.post("/runs/{run_id}/human-decision")
    async def submit_human_decision(
        run_id: str,
        body: HumanDecisionRequest,
        workdir: str = Query(default="."),
        config_path: Optional[str] = Query(default=None),
        execution_mode: Optional[str] = Query(default=None),
        user: Dict[str, Any] = _get_auth(),
    ):
        from ..runtime import resume_run_background

        if body.decision not in {"approved", "rejected"}:
            raise HTTPException(status_code=400, detail="decision must be approved or rejected")
        if body.decision == "rejected" and not body.reason.strip():
            raise HTTPException(status_code=400, detail="reject reason is required")

        project_root = project_for_run(run_id, workdir)
        output_dir = project_root / ".ai" / "team-output" / run_id
        if not output_dir.exists():
            raise HTTPException(status_code=404, detail="run not found")
        if not (output_dir / "checkpoint.json").exists():
            raise HTTPException(status_code=400, detail="no checkpoint found, cannot resume")

        report_file = output_dir / "report.json"
        if report_file.exists():
            report = load_report(report_file)
            if report.status != "waiting":
                raise HTTPException(status_code=400, detail=f"run status is {report.status}, cannot submit human decision")
            config_path = config_path or report.config_path

        decision = HumanDecision(
            stage_id=body.stage_id,
            decision=body.decision,
            reason=body.reason,
            required_changes=body.required_changes,
            target_stage=body.target_stage,
        )
        resumed_output_dir = resume_run_background(
            run_id=run_id,
            workdir=workdir,
            config_path=config_path,
            execution_mode=execution_mode,
            human_decision=decision,
        )
        return {"run_id": run_id, "status": "resuming", "output_dir": str(resumed_output_dir)}
```

- [ ] **Step 5: Run route tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_routes.TestRunsRoutes.test_human_decision_reject_requires_reason tests.test_routes.TestRunsRoutes.test_human_decision_endpoint_passes_structured_decision_to_runtime -v
```

Expected: tests pass.

- [ ] **Step 6: Run resume route regression**

Run:

```bash
.venv/bin/python -m unittest tests.test_routes.TestRunsRoutes.test_resume_run_passes_config_path_and_execution_mode -v
```

Expected: existing resume regression still passes. This endpoint may remain for non-hard technical resume, but hard human gate UI must use `/human-decision`.

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add api/runtime.py api/routes/runs.py tests/test_routes.py
git commit -m "feat: add explicit human decision API"
```

---

### Task 4: Artifact Contracts and Stage Context Package

**Files:**
- Create: `engine/artifact_contracts.py`
- Create: `engine/stage_context.py`
- Modify: `engine/models.py`
- Modify: `engine/orchestrator.py`
- Test: `tests/test_engine.py`

- [ ] **Step 1: Write failing artifact validation and context injection tests**

Add to `tests/test_engine.py`:

```python
class TestArtifactContractsAndStageContext(unittest.TestCase):
    def test_required_artifact_missing_blocks_next_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "team.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "plain text without required json"
agents:
  - name: req
    runtime_id: Mock
    prompt: agents/req.md
pipeline:
  - id: requirement_synthesis
    agents: [req]
    input: requirement
    output:
      req: requirement-final.md
    required_artifacts:
      - requirement-final.json
  - id: planning
    agents: [req]
    input: [requirement-final.json]
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "req.md").write_text("You write output.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("req")

            self.assertEqual(report.status, "failed")
            self.assertIn("required artifact missing", report.error_message)
            self.assertTrue(report.stages[0].artifact_validations)

    def test_stage_context_includes_contract_and_confirmed_artifacts(self) -> None:
        from engine.stage_context import build_stage_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            (output_dir / "requirement-final.json").write_text('{"status":"completed","summary":"req"}', encoding="utf-8")
            (output_dir / "task-plan.json").write_text('{"status":"completed","summary":"plan"}', encoding="utf-8")

            context = build_stage_context(
                stage={"id": "develop", "name": "开发实施", "required_artifacts": ["implementation-report.json"]},
                output_dir=output_dir,
                cwd=root,
                input_items=["requirement-final.json", "task-plan.json"],
                extra_feedback="人工拒绝反馈",
                schema_hint={"required": ["status", "summary"]},
            )

            self.assertIn("## Stage Contract", context)
            self.assertIn("implementation-report.json", context)
            self.assertIn("人工拒绝反馈", context)
            self.assertIn("Artifact: `requirement-final.json`", context)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_engine.TestArtifactContractsAndStageContext -v
```

Expected: fails because `engine.stage_context` and artifact validation fields do not exist.

- [ ] **Step 3: Add artifact validation model to `engine/models.py`**

Add after `QualityGateRun`:

```python
class ArtifactValidationRun(BaseModel):
    artifact: str
    status: Literal["passed", "failed"] = "passed"
    message: str = ""
```

Add to `StageRun`:

```python
    artifact_validations: List[ArtifactValidationRun] = Field(default_factory=list)
```

- [ ] **Step 4: Create `engine/artifact_contracts.py`**

Create:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .models import ArtifactValidationRun

COMMON_JSON_REQUIRED = {"status", "summary"}


def _validate_json_artifact(path: Path) -> ArtifactValidationRun:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ArtifactValidationRun(artifact=path.name, status="failed", message=f"invalid json: {exc}")
    if not isinstance(payload, dict):
        return ArtifactValidationRun(artifact=path.name, status="failed", message="json artifact must be an object")
    missing = sorted(COMMON_JSON_REQUIRED - set(payload))
    if missing:
        return ArtifactValidationRun(artifact=path.name, status="failed", message=f"missing required fields: {', '.join(missing)}")
    return ArtifactValidationRun(artifact=path.name, status="passed", message="ok")


def validate_required_artifacts(stage: Dict[str, Any], output_dir: Path) -> List[ArtifactValidationRun]:
    results: List[ArtifactValidationRun] = []
    for artifact in stage.get("required_artifacts") or []:
        path = output_dir / str(artifact)
        if not path.exists():
            results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message="required artifact missing"))
            continue
        if path.suffix == ".json":
            results.append(_validate_json_artifact(path))
        else:
            results.append(ArtifactValidationRun(artifact=str(artifact), status="passed", message="exists"))
    return results


def has_artifact_validation_failure(results: List[ArtifactValidationRun]) -> bool:
    return any(item.status == "failed" for item in results)
```

- [ ] **Step 5: Create `engine/stage_context.py`**

Create:

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _artifact_section(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lstrip(".")
    lang = "markdown" if suffix == "md" else suffix
    return f"## Artifact: `{path.name}`\n```{lang}\n{content}\n```\n"


def _git_diff(cwd: Path) -> str:
    result = subprocess.run(["git", "diff", "--"], cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def build_stage_context(
    stage: Dict[str, Any],
    output_dir: Path,
    cwd: Path,
    input_items: Iterable[Any],
    extra_feedback: str = "",
    schema_hint: Optional[Dict[str, Any]] = None,
) -> str:
    parts = [
        "## Stage Contract",
        f"- Stage: `{stage.get('id')}` / `{stage.get('name', stage.get('id'))}`",
        f"- Working directory: `{cwd}`",
    ]
    required = [str(item) for item in stage.get("required_artifacts") or []]
    if required:
        parts.append("- Required artifacts:")
        parts.extend([f"  - `{item}`" for item in required])
    parts.extend(
        [
            "- Human gate rule: hard gates require explicit human approval and reject reason.",
            "- Scope rule: only change files required by the confirmed requirement and task plan.",
            "",
        ]
    )
    if schema_hint:
        parts.extend(["## Output Schema", "```json", json.dumps(schema_hint, ensure_ascii=False, indent=2), "```", ""])
    if extra_feedback:
        parts.extend(["## Feedback", extra_feedback.rstrip(), ""])
    for item in _as_list(input_items):
        if item == "git-diff":
            parts.extend(["## git-diff", "```diff", _git_diff(cwd) or "(no diff)", "```", ""])
        elif isinstance(item, str) and "*" in item:
            for path in sorted(output_dir.glob(item)):
                parts.append(_artifact_section(path))
        elif isinstance(item, str):
            path = output_dir / item
            if path.exists():
                parts.append(_artifact_section(path))
    return "\n".join(parts).rstrip() + "\n"
```

- [ ] **Step 6: Wire artifact validation into `engine/orchestrator.py`**

Import:

```python
from .artifact_contracts import has_artifact_validation_failure, validate_required_artifacts
from .stage_context import build_stage_context
```

After an agent stage completes successfully and before appending it to report:

```python
                if stage_run.status == "completed":
                    validations = validate_required_artifacts(stage, output_dir)
                    stage_run.artifact_validations.extend(validations)
                    if has_artifact_validation_failure(validations):
                        failed = "; ".join(f"{item.artifact}: {item.message}" for item in validations if item.status == "failed")
                        stage_run.status = "failed"
                        stage_run.error_message = failed
```

- [ ] **Step 7: Replace `_render_prompt` input assembly with `build_stage_context`**

In `_render_prompt`, replace `inputs = self._collect_inputs(...)` and `parts.extend(inputs)` with:

```python
        context = build_stage_context(
            stage=stage,
            output_dir=output_dir,
            cwd=cwd,
            input_items=stage.get("input") or "requirement",
            extra_feedback=extra_feedback,
            schema_hint={"required": ["status", "summary", "evidence"]},
        )
```

Then append `context` after the base prompt.

- [ ] **Step 8: Run artifact and context tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_engine.TestArtifactContractsAndStageContext -v
```

Expected: tests pass.

- [ ] **Step 9: Commit Task 4**

Run:

```bash
git add engine/models.py engine/artifact_contracts.py engine/stage_context.py engine/orchestrator.py tests/test_engine.py
git commit -m "feat: validate artifacts and inject stage context"
```

---

### Task 5: Prompt Contracts for the New Workflow

**Files:**
- Modify: `templates/agents/requirements-analyst.md`
- Modify: `templates/agents/devils-advocate.md`
- Modify: `templates/agents/planner.md`
- Modify: `templates/agents/tech-lead.md`
- Modify: `templates/agents/qa-automation.md`
- Modify: `templates/agents/code-reviewer.md`
- Modify: `templates/agents/retrospect.md`
- Test: `tests/test_config.py`

- [ ] **Step 1: Add prompt contract regression test**

Add to `tests/test_config.py`:

```python
class TestPromptContracts(unittest.TestCase):
    def test_default_prompts_reference_required_artifact_contracts(self) -> None:
        prompt_dir = Path("templates/agents")
        expected = {
            "requirements-analyst.md": ["requirement-final.json", "status", "summary", "acceptance_coverage"],
            "planner.md": ["task-plan.json", "solution-plan.json", "status", "summary", "evidence"],
            "tech-lead.md": ["implementation-report.json", "git diff", "只修改"],
            "qa-automation.md": ["test-report.json", "acceptance_coverage"],
            "code-reviewer.md": ["review-report.json", "风险", "Request Changes"],
            "retrospect.md": ["retrospect-report.json", "交付摘要"],
        }
        for filename, needles in expected.items():
            content = (prompt_dir / filename).read_text(encoding="utf-8")
            for needle in needles:
                self.assertIn(needle, content, f"{filename} missing {needle}")
```

- [ ] **Step 2: Run prompt contract test and verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_config.TestPromptContracts -v
```

Expected: fails because current prompts do not consistently require the new JSON artifact contracts.

- [ ] **Step 3: Update `requirements-analyst.md`**

Ensure it instructs requirement synthesis to output both:

```text
必须输出：
1. requirement-final.md：人类可读的定稿候选需求。
2. requirement-final.json：机器可校验的需求 artifact。

requirement-final.json 必须包含：
- status: "completed"
- summary
- inputs_used
- decisions
- open_questions
- risks
- acceptance_coverage
- evidence
- next_stage_contract

你必须逐条说明多 agent 意见中哪些被采用、哪些被拒绝，以及拒绝理由。
如果仍有歧义，写入 open_questions，不能替用户猜测。
```

- [ ] **Step 4: Update `planner.md`**

Ensure it requires:

```text
必须基于 requirement-final.json 和 codebase-context.json 输出：
1. solution-plan.json
2. task-plan.md / task-plan.json

task-plan.json 必须包含：
- status: "completed"
- summary
- tasks
- execution_order
- file_boundaries
- test_plan
- rollback_considerations
- acceptance_coverage
- evidence
- next_stage_contract
```

- [ ] **Step 5: Update `tech-lead.md`**

Ensure it requires direct worktree implementation and forbids scope expansion:

```text
你必须直接在 Working directory 中实施代码修改。
不要只输出 patch 文本，除非 runtime 明确不支持写文件。
只修改 task-plan.json 和人工反馈要求的范围。
完成后输出 implementation-report.md 和 implementation-report.json。
implementation-report.json 必须包含 status、summary、changed_files、tests_run、acceptance_coverage、evidence、risks。
```

- [ ] **Step 6: Update `qa-automation.md` and `code-reviewer.md`**

For QA:

```text
输出 test-report.md 和 test-report.json。
test-report.json 必须包含 status、summary、commands、results、acceptance_coverage、evidence。
如有阻断失败，必须包含 FAILED 或 ERROR，供编排器回流 develop。
```

For review:

```text
输出 review-report.md 和 review-report.json。
审查必须合并风险识别，覆盖正确性、需求覆盖、测试充分性、回归风险、安全风险、可维护性、部署和回滚影响、废弃代码。
如需要修改，必须输出 Request Changes。
```

- [ ] **Step 7: Run prompt contract test**

Run:

```bash
.venv/bin/python -m unittest tests.test_config.TestPromptContracts -v
```

Expected: test passes.

- [ ] **Step 8: Commit Task 5**

Run:

```bash
git add templates/agents/requirements-analyst.md templates/agents/devils-advocate.md templates/agents/planner.md templates/agents/tech-lead.md templates/agents/qa-automation.md templates/agents/code-reviewer.md templates/agents/retrospect.md tests/test_config.py
git commit -m "docs: define agent artifact prompt contracts"
```

---

### Task 6: Frontend Human Gate UX

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/components/PipelineTimeline.tsx`
- Modify: `web/src/pages/RunDetail.tsx`
- Modify: `web/src/styles.css`
- Create: `web/src/test/HumanGateActions.test.tsx`

- [ ] **Step 1: Write failing Vitest for reject reason requirement**

Create `web/src/test/HumanGateActions.test.tsx`:

```tsx
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PipelineTimeline } from '../components/PipelineTimeline';

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api');
  return {
    ...actual,
    rememberedWorkdir: () => '/repo',
    submitHumanDecision: vi.fn().mockResolvedValue({ run_id: 'r1', status: 'resuming', output_dir: '/tmp/out' }),
  };
});

describe('human gate actions', () => {
  it('requires a reject reason before submitting rejection', async () => {
    const { submitHumanDecision } = await import('../lib/api');
    render(
      <PipelineTimeline
        run={{
          run_id: 'r1',
          status: 'waiting',
          requirement: 'req',
          project_root: '/repo',
          output_dir: '/tmp/out',
          config_source: 'project',
          artifacts: [],
          stages: [
            {
              stage_id: 'task_plan_confirm',
              stage_name: '任务规划人工确认',
              status: 'waiting',
              is_parallel: false,
              type: 'human_review',
              agents: [],
              quality_gates: [],
            },
          ],
        }}
        onStageAction={() => undefined}
      />
    );

    const reject = screen.getByRole('button', { name: /拒绝/ });
    expect(reject).toBeDisabled();
    fireEvent.change(screen.getByLabelText('拒绝理由'), { target: { value: '任务缺少回滚方案' } });
    expect(reject).not.toBeDisabled();
    fireEvent.click(reject);

    await waitFor(() => {
      expect(submitHumanDecision).toHaveBeenCalledWith('r1', '/repo', {
        stage_id: 'task_plan_confirm',
        decision: 'rejected',
        reason: '任务缺少回滚方案',
        required_changes: [],
      });
    });
  });
});
```

- [ ] **Step 2: Run the new frontend test and verify it fails**

Run:

```bash
npm run test -- HumanGateActions.test.tsx
```

Expected: fails because `submitHumanDecision` does not exist and current reject button does not require a reason.

- [ ] **Step 3: Update `web/src/lib/types.ts`**

Add:

```ts
export interface HumanDecision {
  stage_id: string;
  decision: 'waiting' | 'approved' | 'rejected';
  reason?: string;
  required_changes?: string[];
  target_stage?: string;
  decided_by?: string;
  decided_at?: string;
}

export interface ArtifactValidationRun {
  artifact: string;
  status: 'passed' | 'failed';
  message: string;
}
```

Add to `StageRun`:

```ts
  human_decision?: HumanDecision;
  loopback_to?: string;
  artifact_validations?: ArtifactValidationRun[];
```

Add to `RunReport`:

```ts
  human_decisions?: HumanDecision[];
```

- [ ] **Step 4: Update `web/src/lib/api.ts`**

Import `HumanDecision` and add:

```ts
export async function submitHumanDecision(
  runId: string,
  workdir: string,
  decision: Pick<HumanDecision, 'stage_id' | 'decision' | 'reason' | 'required_changes' | 'target_stage'>
): Promise<{ run_id: string; status: string; output_dir: string }> {
  const response = await apiFetch(`/runs/${runId}/human-decision${runQuery(workdir)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(decision),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '提交人工决策失败' }));
    throw new Error(error.detail || `提交人工决策失败: ${response.status}`);
  }
  return response.json();
}
```

- [ ] **Step 5: Replace `ReviewActions` in `PipelineTimeline.tsx`**

Change it to use `submitHumanDecision`, a reject textarea, and disabled reject button:

```tsx
const [reason, setReason] = useState('');
const [requiredChanges, setRequiredChanges] = useState('');

function handleApprove() {
  setActing(true);
  setError(null);
  submitHumanDecision(runId, workdir, {
    stage_id: stage.stage_id,
    decision: 'approved',
    reason: '',
    required_changes: [],
  })
    .then(() => onActionDone())
    .catch((e: Error) => setError(e.message))
    .finally(() => setActing(false));
}

function handleReject() {
  const trimmedReason = reason.trim();
  if (!trimmedReason) {
    setError('拒绝必须填写理由');
    return;
  }
  setActing(true);
  setError(null);
  submitHumanDecision(runId, workdir, {
    stage_id: stage.stage_id,
    decision: 'rejected',
    reason: trimmedReason,
    required_changes: requiredChanges.split('\n').map((item) => item.trim()).filter(Boolean),
  })
    .then(() => onActionDone())
    .catch((e: Error) => setError(e.message))
    .finally(() => setActing(false));
}
```

Render:

```tsx
<label className="reviewReasonField">
  <span>拒绝理由</span>
  <textarea value={reason} onChange={(event) => setReason(event.target.value)} />
</label>
<label className="reviewReasonField">
  <span>必须修改项</span>
  <textarea value={requiredChanges} onChange={(event) => setRequiredChanges(event.target.value)} />
</label>
<button className="button reviewRejectButton" onClick={handleReject} disabled={acting || !reason.trim()}>
  <XCircle size={14} /> 拒绝
</button>
```

- [ ] **Step 6: Show validation and decision state**

In `StageCard`, after quality gates, render artifact validation failures:

```tsx
{stage.artifact_validations?.length ? (
  <div className="artifactValidationList">
    {stage.artifact_validations.map((item) => (
      <div className={`artifactValidation artifactValidation-${item.status}`} key={item.artifact}>
        <span>{item.artifact}</span>
        <strong>{item.status === 'passed' ? '通过' : '失败'}</strong>
        <small>{item.message}</small>
      </div>
    ))}
  </div>
) : null}
{stage.human_decision ? (
  <div className="humanDecisionSummary">
    <strong>人工决策：{stage.human_decision.decision}</strong>
    {stage.human_decision.reason ? <p>{stage.human_decision.reason}</p> : null}
    {stage.loopback_to ? <small>回流到：{stage.loopback_to}</small> : null}
  </div>
) : null}
```

- [ ] **Step 7: Add CSS**

Add to `web/src/styles.css`:

```css
.reviewReasonField {
  display: grid;
  gap: 6px;
  color: var(--text-muted);
  font-size: 13px;
}

.reviewReasonField textarea {
  min-height: 76px;
  resize: vertical;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  border-radius: 6px;
  padding: 8px;
}

.artifactValidationList,
.humanDecisionSummary {
  margin-top: 12px;
  display: grid;
  gap: 8px;
}

.artifactValidation,
.humanDecisionSummary {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
}

.artifactValidation-failed {
  border-color: var(--danger);
}
```

- [ ] **Step 8: Run frontend test**

Run:

```bash
npm run test -- HumanGateActions.test.tsx
```

Expected: test passes.

- [ ] **Step 9: Run frontend build**

Run:

```bash
npm run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 10: Commit Task 6**

Run:

```bash
git add web/src/lib/types.ts web/src/lib/api.ts web/src/components/PipelineTimeline.tsx web/src/pages/RunDetail.tsx web/src/styles.css web/src/test/HumanGateActions.test.tsx
git commit -m "feat: add human gate decision UI"
```

---

### Task 7: End-to-End Regression and Cleanup

**Files:**
- Modify: tests touched by previous tasks if regressions require updates.
- Do not modify product files unless a failing test proves a real defect.

- [ ] **Step 1: Run targeted backend suite**

Run:

```bash
.venv/bin/python -m unittest tests.test_config tests.test_engine tests.test_routes -v
```

Expected: all tests pass except any pre-existing skipped tests.

- [ ] **Step 2: Run full backend suite**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass except existing intentional skips.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
npm run test
```

Expected: all Vitest tests pass.

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 5: Run diff hygiene**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 6: Manual local smoke**

Start services if not already running:

```bash
.venv/bin/ai-team serve --host 127.0.0.1 --port 8000 --reload
cd web && npm run dev -- --host 127.0.0.1
```

Verify:

```bash
curl -sS http://127.0.0.1:8000/health
curl -I -sS http://127.0.0.1:5173/dashboard
```

Expected:

```text
{"status":"ok"}
HTTP/1.1 200 OK
```

- [ ] **Step 7: Commit final test adjustments only if needed**

If Step 1-6 require test-only adjustments, commit them:

```bash
git add tests web/src/test
git commit -m "test: cover agent workflow redesign"
```

- [ ] **Step 8: Final status report**

Run:

```bash
git status --short --branch
```

Expected: only unrelated pre-existing changes remain. Summarize new commits and validation commands in the final handoff.

---

## Self-Review

### Spec Coverage

- Context before planning: Task 1 rewrites default pipeline and Task 4 injects context.
- Mandatory human gates: Task 1 config, Task 2 orchestrator, Task 3 API, Task 6 UI.
- Reject reason and loopback: Task 2 model/orchestrator, Task 3 API validation, Task 6 UI reason field.
- Artifact standards: Task 4 validation, Task 5 prompt contracts.
- Single developer default and `code_apply` removal: Task 1 pipeline, Task 5 developer prompt.
- Risk merged into review: Task 1 pipeline and Task 5 reviewer prompt.
- Docs front-loaded into planning: Task 1 pipeline and Task 5 planner prompt.
- UI visibility: Task 6.
- Tests and validation: Task 7.

### Placeholder Scan

This plan contains no unresolved placeholders or open-ended implementation steps. All tasks include exact files, concrete code snippets, commands, and expected outcomes.

### Type Consistency

The plan consistently uses:

- `HumanDecision`
- `ArtifactValidationRun`
- `human_decision`
- `artifact_validations`
- `submitHumanDecision`
- `/api/runs/{run_id}/human-decision`
- hard gate ids `requirement_confirm`, `task_plan_confirm`, `acceptance_confirm`
