# Harness Checks Implementation Plan

> **For implementation agents:** This plan covers only Harness Checks. Do not implement Task Board workflow, UI pages, RunDetail display, or a second command runner. If any step needs those areas, stop and report before editing source files.

**Goal:** Add executable Harness verification for `harness_verify`: pattern checks, command checks through the shared Quality Gate runner, raise-only baseline checks, `harness-report.json`, and pipeline blocking semantics.

**Architecture:** Reuse the Core repo-file Harness loader as the source of truth. Add a Checks engine that converts Harness command checks into Quality Gate config and calls `engine.quality_gates.run_quality_gates`; pattern and baseline checks stay in the Harness Checks engine because they are not shell-command execution. Harden the shared Quality Gate runner with opt-in execution policy for cwd allowlists, mandatory timeouts, output truncation, and env allowlists so existing non-Harness quality gate behavior remains compatible unless the new policy is enabled.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PyYAML, unittest/pytest-compatible tests.

---

## Startup Evidence

- Repository-root `AGENTS.md` exists and matches the session instructions.
- `docs/superpowers/specs/2026-05-09-harness-governance-design.md` was read. Checks scope is `harness_verify`, pattern checks, command-to-quality-gate conversion, baseline checks, `harness-report.json`, pipeline blocking, and shared Quality Gate runner hardening.
- `docs/superpowers/specs/2026-04-30-agent-collaboration-workflow-design.md` was read. The Checks stage must respect centralized orchestration, artifact contracts, structured feedback, and human gate boundaries.
- `docs/superpowers/plans/2026-05-09-harness-core.md` was read.
- `docs/superpowers/reports/2026-05-09-harness-core-final-report.md` was read.
- Core final status is `complete`.
- Every Core in-scope row in the Core final report is `verified`.
- Core final report lists no unfinished items, no skipped verification, and no blocking risk. It explicitly says Checks execution, Task Board workflow, and UI were not implemented.
- `git status --short --branch` before Checks planning:
  - `## main...origin/main [ahead 1]`
  - `?? docs/superpowers/plans/2026-05-09-harness-task-board.md`
  - `?? docs/superpowers/plans/2026-05-09-harness-ui.md`

## Current Code Evidence

- `engine/quality_gates.py` provides the existing shared execution path:
  - `run_quality_gates(gates, cwd, run_id, bus=None, retry_count=0)`
  - `run_quality_gate(gate, cwd, run_id, bus=None, retry_count=0)`
  - `_run_command(command, cwd, timeout)`
- Current `_run_command` uses `subprocess.run(..., shell=True, env inherited by default)`. It accepts a timeout but does not require one, so Harness command checks must enable a stricter shared-runner policy.
- Existing quality gates already truncate `QualityGateRun.output` to the last 20,000 characters, but the limit is hard-coded. Harness needs a report-visible and testable truncation limit.
- `engine/orchestrator.py` already runs global `quality_gates` after `develop` through `_run_develop_quality_loop`; Checks must not replace that path.
- `engine/orchestrator.py` dispatches stage types for `context_scan`, `human_review`, and deprecated `code_apply`; Checks should add a separate `harness_verify` stage branch.
- `engine/models.py` already has `QualityGateRun`, `StageRun.quality_gates`, and status values `passed/failed/warning/skipped`.
- Core `engine/harness.py` already loads `.ai/harness.yaml`, validates Harness refs, computes manifest hash, and summarizes rules/skills/checks/baselines.
- `engine/artifact_contracts.py` supports schema-backed validation through `SCHEMA_FILE_MAP` and `engine/schemas/*.json`; `harness-report.json` should join that mechanism.

## Hard Scope Boundaries

- In scope:
  - `harness_verify` stage type and backend execution path.
  - Pattern checks.
  - Command checks converted into Quality Gate config.
  - Baseline checks with default `raise_only` semantics.
  - `harness-report.json` schema and artifact validation.
  - Pipeline blocking: warnings continue, errors block and generate feedback.
  - Shared Quality Gate runner hardening for Harness command checks.
  - Optional backend `POST /api/projects/{project_id}/harness/checks/run` using existing Core `project_id` resolver.
- Out of scope:
  - Task Board workflow, task files/events, related-task matching, or accepted task memory.
  - UI pages, navigation, RunDetail display, markdown rendering, or frontend API client changes.
  - A second command runner or any Harness-only shell execution path.
  - Baseline auto-update or automatic baseline lowering.

## Exact QualityGateRunner Reuse Path

Harness command checks must follow this call chain:

```text
engine/orchestrator.py::_run_harness_verify_stage
  -> engine/harness_checks.py::run_harness_verification
  -> engine/harness_checks.py::_run_command_checks
  -> engine.quality_gates.run_quality_gates
  -> engine.quality_gates.run_quality_gate
  -> engine.quality_gates._run_command
```

Manual API execution must use the same engine path:

```text
api/routes/harness.py::run_harness_checks
  -> engine/harness_checks.py::run_harness_verification
  -> engine/harness_checks.py::_run_command_checks
  -> engine.quality_gates.run_quality_gates
```

`engine/harness_checks.py` must not import `subprocess`, `os.system`, `asyncio.create_subprocess*`, or any shell execution helper. Tests must enforce this with a static guard and a spy proving `run_quality_gates` is called.

## Planned File Changes

- Modify: `engine/quality_gates.py`
  - Add a backwards-compatible execution policy for cwd allowlists, required timeout, output limit, and env allowlist.
  - Keep existing callers compatible when no policy is provided.
- Modify: `engine/models.py`
  - Add optional `cwd` and `output_truncated` fields to `QualityGateRun` only if needed for report evidence.
- Modify: `engine/harness.py`
  - Extend `HarnessCheckRef` schema for Checks fields: `timeout_seconds`, `globs`, `exclude`, `baseline_file`, `metric`, `operator`, `threshold`, `env_allowlist`, and optional relative `cwd`.
  - Keep Core path safety and manifest behavior unchanged.
- Create: `engine/harness_checks.py`
  - Owns pattern/baseline/check aggregation, command-to-quality-gate conversion, `harness-report.json` construction, and feedback rendering.
- Modify: `engine/orchestrator.py`
  - Add `harness_verify` stage dispatch and pipeline blocking behavior.
- Modify: `engine/artifact_contracts.py`
  - Register `harness-report.json`.
- Create: `engine/schemas/harness-report.json`
  - Schema for the Harness Report contract.
- Modify: `api/routes/harness.py`
  - Add `POST /api/projects/{project_id}/harness/checks/run` if it can reuse the same execution path without UI/Task Board dependencies.
- Modify: `engine/config.py`
  - Add `harness_verify` to default config only if the stage can remain backend-only and artifact-based.
- Modify: `templates/team.yaml`
  - Add backend-only `harness_verify` stage after `qa` and before `review`, with `harness-report.json` as required artifact.
- Modify: `api/routes/pipelines.py`
  - Hydrate built-in pipeline templates with `harness_verify` stage metadata if default templates include the stage.
- Create: `tests/test_harness_checks.py`
  - Unit tests for pattern, command conversion, baseline, report schema, and static no-second-runner guard.
- Modify: `tests/test_quality_gates.py`
  - Shared runner hardening tests.
- Modify: `tests/test_engine.py`
  - Orchestrator `harness_verify` stage pass/warn/fail and feedback behavior.
- Modify: `tests/test_harness_routes.py`
  - Backend checks run route tests if the route is added.
- Modify: `tests/test_artifact_contracts.py`
  - `harness-report.json` schema validation tests.
- Modify: `tests/test_config.py` and `tests/test_routes.py`
  - Default/built-in pipeline stage metadata tests if template/config hydration changes.

No implementation should modify `web/**` or any Task Board storage/API files in this sub-iteration.

## Harness Checks Config Contract

The implementation should support this minimal Checks schema through the existing `.ai/harness.yaml`:

```yaml
schema_version: "1.0"
checks:
  - id: no-messagebox
    title: No MessageBox
    type: pattern
    pattern: "MessageBox"
    globs:
      - "src/**/*.py"
    severity: error
    blocking: true

  - id: pytest
    title: Pytest
    type: command
    command: ".venv/bin/python -m pytest -q"
    timeout_seconds: 120
    severity: error
    blocking: true
    env_allowlist:
      - PATH
      - HOME
      - VIRTUAL_ENV
      - PYTHONPATH

  - id: baseline-coverage
    title: Coverage Baseline
    type: baseline
    baseline_file: ".ai/harness/baselines/coverage.json"
    severity: error
    blocking: true
```

Baseline file format:

```json
{
  "schema_version": "1.0",
  "mode": "raise_only",
  "metrics": {
    "coverage": 82.5,
    "max_errors": 0
  }
}
```

Baseline checks compare the working baseline file against the last committed version of the same file. Equal or raised numeric baselines pass. Lowered numeric baselines fail and block by default. If no committed baseline exists, report a warning and do not auto-approve lowering.

## Harness Report Contract

Every `harness_verify` execution writes `harness-report.json` to the run artifact directory:

```json
{
  "schema_version": "1.0",
  "run_id": "run_xxx",
  "project_id": "project_xxx",
  "stage_id": "harness_verify",
  "harness_config_hash": "sha256:...",
  "generated_at": "2026-05-10T00:00:00Z",
  "status": "pass",
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

`warning` results must remain non-blocking but visible in this report. `error` results with `blocking: true` must set report `status: "fail"`, `blocking: true`, fail the `harness_verify` stage, and write `harness-feedback.md` with the failing evidence for loopback.

## Traceability Matrix

These rows are copied from the Checks scope of `docs/superpowers/specs/2026-05-09-harness-governance-design.md` plus all-iteration DoD rows. No Checks in-scope row contains the governance placeholder token.

| Requirement ID | Sub-Iteration | Design Source | Implementation Files | Tests | Verification Command | Status | Evidence |
|---|---|---|---|---|---|---|---|
| H-QG-001 | Checks | Sub-Iteration 2 | `engine/harness_checks.py`, `engine/quality_gates.py`, `engine/orchestrator.py`, `api/routes/harness.py` | `tests/test_harness_checks.py::TestHarnessCommandChecks::test_command_checks_reuse_quality_gate_runner`; `tests/test_harness_orchestrator.py::TestHarnessVerifyStage`; `tests/test_harness_routes.py::TestHarnessChecksRunApi::test_checks_run_uses_repository_config` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessCommandChecks tests/test_harness_orchestrator.py tests/test_harness_routes.py::TestHarnessChecksRunApi -q` | verified | Evidence: command spy proves `engine.harness_checks` calls `run_quality_gates`; orchestrator/API route both call `run_harness_verification`; combined focused pytest passed (`153 passed`, then `343 passed`). |
| H-QG-002 | Checks | Sub-Iteration 2 | `engine/harness_checks.py`, `engine/quality_gates.py` | `tests/test_harness_checks.py::TestHarnessChecksNoSecondRunner::test_harness_checks_does_not_import_subprocess_or_os_system`; command spy in `TestHarnessCommandChecks` | `! rg -n "subprocess|os\\.system|create_subprocess" engine/harness_checks.py`; `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessChecksNoSecondRunner tests/test_harness_checks.py::TestHarnessCommandChecks -q` | verified | Evidence: static guard command exit 0; no shell execution import in Harness Checks; command execution remains in `engine.quality_gates._run_command`. |
| H-CMD-001 | Checks | Sub-Iteration 2 | `engine/quality_gates.py`, `engine/harness_checks.py`, `engine/orchestrator.py`, `engine/harness.py` | `tests/test_quality_gates.py::TestQualityGateExecutionPolicy::test_policy_rejects_cwd_outside_allowed_roots`; `tests/test_quality_gates.py::TestQualityGateExecutionPolicy::test_policy_rejects_missing_cwd`; `tests/test_harness_core.py::TestHarnessSchemaValidation::test_check_schema_rejects_unsafe_command_cwd`; `tests/test_harness_checks.py::TestHarnessCommandChecks::test_command_check_cwd_is_limited_to_safe_relative_path` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessCommandChecks tests/test_quality_gates.py::TestQualityGateExecutionPolicy -q` | verified | Evidence: `12 passed`; unsafe cwd rejected before execution, missing cwd rejected by the shared runner policy, allowed relative cwd executes through Quality Gate, and shared runner policy rejects cwd outside allowed roots. |
| H-CMD-002 | Checks | Sub-Iteration 2 | `engine/quality_gates.py`, `engine/harness.py`, `engine/harness_checks.py` | `tests/test_quality_gates.py::TestQualityGateExecutionPolicy::test_policy_requires_timeout`; `tests/test_harness_core.py::TestHarnessSchemaValidation::test_check_schema_requires_command_timeout_and_metadata`; `tests/test_harness_checks.py::TestHarnessCommandChecks::test_command_timeout_failure_blocks_pipeline` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation tests/test_harness_checks.py::TestHarnessCommandChecks tests/test_quality_gates.py::TestQualityGateExecutionPolicy -q` | verified | Evidence: command checks require positive `timeout_seconds`; timed out command reports exit code `124`, failed status, and blocking report. |
| H-CMD-003 | Checks | Sub-Iteration 2 | `engine/quality_gates.py`, `engine/harness_checks.py`, `engine/schemas/harness-report.json` | `tests/test_quality_gates.py::TestQualityGateExecutionPolicy::test_policy_truncates_output`; `tests/test_harness_checks.py::TestHarnessCommandChecks::test_command_output_is_truncated_in_report` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessCommandChecks tests/test_quality_gates.py::TestQualityGateExecutionPolicy -q` | verified | Evidence: `12 passed`; long command output is truncated to configured limit and Harness evidence includes `quality_gate:<id>:output_truncated`. |
| H-CMD-004 | Checks | Sub-Iteration 2 | `engine/quality_gates.py`, `engine/harness_checks.py` | `tests/test_quality_gates.py::TestQualityGateExecutionPolicy::test_policy_env_uses_allowlist`; `tests/test_harness_checks.py::TestHarnessCommandChecks::test_command_env_allowlist_prevents_secret_inheritance` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessCommandChecks tests/test_quality_gates.py::TestQualityGateExecutionPolicy -q` | verified | Evidence: unlisted `HARNESS_SECRET_TOKEN` is absent from command output; shared runner builds env from allowlist when policy is enabled. |
| H-CMD-005 | Checks | Sub-Iteration 2 | `engine/harness_checks.py`, `api/routes/harness.py`, `engine/orchestrator.py` | `tests/test_harness_checks.py::TestHarnessCommandChecks::test_production_dirty_command_config_fails_closed`; `tests/test_harness_routes.py::TestHarnessChecksRunApi::test_checks_run_in_production_rejects_dirty_command_config`; `tests/test_harness_routes.py::TestHarnessChecksRunApi::test_checks_run_rejects_body_defined_commands` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessCommandChecks tests/test_harness_routes.py::TestHarnessChecksRunApi -q` | verified | Evidence: production command checks reject dirty/uncommitted Harness command config; route rejects request-body command definitions and only reads repo Harness config. |
| H-PATTERN-001 | Checks | Sub-Iteration 2 | `engine/harness.py`, `engine/harness_checks.py`, `engine/schemas/harness-report.json` | `tests/test_harness_checks.py::TestHarnessPatternChecks::test_warning_pattern_check_reports_without_blocking`; `tests/test_harness_checks.py::TestHarnessPatternChecks::test_error_pattern_check_blocks_pipeline` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessPatternChecks -q` | verified | Evidence: pattern results include check/rule ID, file, line, severity, evidence refs, and warning-vs-error blocking behavior. |
| H-BASE-001 | Checks | Sub-Iteration 2 | `engine/harness.py`, `engine/harness_checks.py` | `tests/test_harness_checks.py::TestHarnessBaselineChecks::test_baseline_raise_only_allows_equal_or_raise`; `tests/test_harness_checks.py::TestHarnessBaselineChecks::test_missing_committed_baseline_warns_without_auto_lowering` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessBaselineChecks -q` | verified | Evidence: equal/raised numeric baseline passes; missing committed baseline warns and no auto-update/lowering path is implemented. |
| H-BASE-002 | Checks | Sub-Iteration 2 | `engine/harness_checks.py`, `engine/orchestrator.py` | `tests/test_harness_checks.py::TestHarnessBaselineChecks::test_baseline_lowering_blocks_without_approval`; `tests/test_harness_orchestrator.py::TestHarnessVerifyStage::test_harness_verify_blocks_pipeline_on_error_check` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessBaselineChecks tests/test_harness_orchestrator.py -q` | verified | Evidence: lowered baseline produces failed blocking result; no approval bypass exists in this sub-iteration, so lowering remains fail-closed. |
| H-BASE-003 | Checks | Sub-Iteration 2 | `engine/harness_checks.py`, `engine/orchestrator.py` | `tests/test_harness_checks.py::TestHarnessBaselineChecks::test_baseline_lowering_blocks_without_approval`; `tests/test_harness_checks.py::TestHarnessBaselineChecks::test_baseline_raise_only_allows_equal_or_raise` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessBaselineChecks -q` | verified | Evidence: committed baseline is read with fixed git commands; changed baseline values are reported in `baseline_results.changes`, and lowered values cannot silently pass. |
| H-REPORT-001 | Checks | Harness Report Contract | `engine/harness_checks.py`, `engine/schemas/harness-report.json`, `engine/artifact_contracts.py`, `tests/test_artifact_contracts.py` | `tests/test_harness_checks.py::TestHarnessReportContract::test_report_is_written_and_validates_contract`; `tests/test_artifact_contracts.py::TestSchemaLoading::test_load_all_schemas` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessReportContract tests/test_artifact_contracts.py::TestSchemaLoading -q` | verified | Evidence: `harness-report.json` is written and validates through `validate_artifact`; schema is registered in `SCHEMA_FILE_MAP`. |
| H-REPORT-002 | Checks | Harness Report Contract | `engine/harness_checks.py`, `engine/orchestrator.py`, `engine/schemas/harness-report.json` | `tests/test_harness_checks.py::TestHarnessPatternChecks::test_warning_pattern_check_reports_without_blocking`; `tests/test_harness_orchestrator.py::TestHarnessVerifyStage::test_harness_verify_keeps_warning_nonblocking` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessPatternChecks tests/test_harness_orchestrator.py -q` | verified | Evidence: warning checks produce report status `warning`, keep `blocking=false`, and `harness_verify` stage completes. No `web/**` files were modified. |
| H-REPORT-003 | Checks | Harness Report Contract | `engine/harness_checks.py`, `engine/orchestrator.py` | `tests/test_harness_checks.py::TestHarnessPatternChecks::test_error_pattern_check_blocks_pipeline`; `tests/test_harness_orchestrator.py::TestHarnessVerifyStage::test_harness_verify_blocks_pipeline_on_error_check` | `.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessPatternChecks tests/test_harness_orchestrator.py -q` | verified | Evidence: error check sets `status=fail`, `blocking=true`, fails the `harness_verify` stage, and writes `harness-feedback.md`. |
| H-DOD-001 | All | Definition Of Done | `docs/superpowers/plans/2026-05-09-harness-checks.md`; `docs/superpowers/reports/2026-05-09-harness-checks-final-report.md` | Manual review plus placeholder-token grep; final report matrix | `TOKEN="$(printf 'plan%s' '-time')"; ! rg -n "$TOKEN" docs/superpowers/plans/2026-05-09-harness-checks.md` | verified | Evidence: placeholder-token grep exit 0; final report will carry all Checks IDs with `verified` status. |
| H-DOD-002 | All | Definition Of Done | All Checks implementation files and final report | Fresh focused tests, full backend tests, frontend smoke, diff hygiene, and final report evidence | `.venv/bin/python -m unittest discover -s tests -v`; `.venv/bin/python -m pytest tests/test_harness*.py tests/test_quality_gates.py tests/test_engine.py tests/test_routes.py tests/test_artifact_contracts.py tests/test_config.py -q`; `cd web && npm run test`; `cd web && npm run build`; `git diff --check` | verified | Evidence: unittest `795 tests OK (skipped=2)`; pytest `343 passed, 2 warnings`; web test `7 files/21 tests passed`; web build passed with chunk-size warning; `git diff --check` exit 0. |

## Implementation Tasks

### Task 1: Extend Harness Check Schema For Checks Metadata

**Objective:** Make `.ai/harness.yaml` able to describe pattern, command, and baseline checks without executing anything.

**Files:**

- Modify: `engine/harness.py`
- Test: `tests/test_harness_core.py`
- Test: `tests/test_harness_checks.py`

Steps:

1. Add failing tests for valid pattern, command, and baseline check config.
2. Add failing tests for invalid command check without `timeout_seconds`.
3. Add failing tests for invalid relative `cwd` with `..` or absolute path.
4. Extend `HarnessCheckRef` with Check-specific fields while keeping `extra="forbid"`.
5. Keep Core loader behavior read-only; do not execute checks in `engine/harness.py`.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation tests/test_harness_checks.py::TestHarnessConfigSchema -q
```

### Task 2: Harden Shared Quality Gate Runner With Opt-In Policy

**Objective:** Add cwd, timeout, output, and env controls to the existing Quality Gate runner without breaking existing non-Harness callers.

**Files:**

- Modify: `engine/quality_gates.py`
- Test: `tests/test_quality_gates.py`

Steps:

1. Add `QualityGateExecutionPolicy` or equivalent optional policy object.
2. Add failing tests proving existing `run_quality_gate(...)` calls still work with no policy.
3. Add failing tests proving policy rejects cwd outside allowed roots.
4. Add failing tests proving policy can require timeout.
5. Add failing tests proving output limit is applied.
6. Add failing tests proving env is allowlisted when policy is enabled.
7. Implement policy in `run_quality_gate` / `run_quality_gates` and `_run_command`.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_quality_gates.py::TestQualityGateExecutionPolicy tests/test_quality_gates.py::TestQualityGateCommand -q
```

### Task 3: Add Harness Checks Engine And Report Builder

**Objective:** Create one backend engine for Checks aggregation and `harness-report.json` output.

**Files:**

- Create: `engine/harness_checks.py`
- Create: `engine/schemas/harness-report.json`
- Modify: `engine/artifact_contracts.py`
- Test: `tests/test_harness_checks.py`
- Test: `tests/test_artifact_contracts.py`

Steps:

1. Add failing schema tests for required Harness Report fields.
2. Implement report dataclasses/helpers or Pydantic models.
3. Build summary counts from check results.
4. Register `harness-report.json` in `SCHEMA_FILE_MAP`.
5. Keep report generation independent of UI and Task Board.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessReport tests/test_artifact_contracts.py -q
```

### Task 4: Implement Pattern Checks

**Objective:** Scan safe project files for configured patterns and produce evidence-rich results.

**Files:**

- Modify: `engine/harness_checks.py`
- Test: `tests/test_harness_checks.py`

Steps:

1. Add failing fixture tests for a matched pattern.
2. Add failing tests for line number, file path, severity, and evidence refs.
3. Add warning and error severity tests.
4. Implement glob filtering with project-root path safety.
5. Add output to `rule_violations` and `checks` in report.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessPatternChecks -q
```

### Task 5: Implement Command Check Conversion Through QualityGateRunner

**Objective:** Convert Harness command checks into Quality Gate configs and execute only through `run_quality_gates`.

**Files:**

- Modify: `engine/harness_checks.py`
- Modify: `engine/quality_gates.py`
- Test: `tests/test_harness_checks.py`
- Test: `tests/test_quality_gates.py`

Steps:

1. Add spy test proving `engine.harness_checks._run_command_checks` calls `run_quality_gates`.
2. Add static guard proving `engine/harness_checks.py` has no subprocess or shell execution imports.
3. Map Harness `severity/blocking` to Quality Gate `required`.
4. Pass policy with allowed roots, required timeout, output limit, and env allowlist.
5. Convert `QualityGateRun` results into Harness check results.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessCommandChecks tests/test_quality_gates.py::TestQualityGateExecutionPolicy -q
```

### Task 6: Implement Raise-Only Baseline Checks

**Objective:** Detect baseline lowering and block by default without auto-updating baselines.

**Files:**

- Modify: `engine/harness_checks.py`
- Test: `tests/test_harness_checks.py`

Steps:

1. Add tests for equal, raised, lowered, missing committed baseline, and malformed baseline files.
2. Read committed baseline content with fixed platform git commands, not Harness-provided commands.
3. Compare numeric values in `metrics`.
4. Lowered values become failed blocking results.
5. Missing committed baseline becomes warning; no auto-update is written.
6. If implementation cannot prove an existing human approval or PR review contract for lowering bypass, do not implement a bypass.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_checks.py::TestHarnessBaselineChecks -q
```

### Task 7: Add `harness_verify` Stage Type And Blocking Semantics

**Objective:** Run Harness Checks as a pipeline stage and block only on blocking failures.

**Files:**

- Modify: `engine/orchestrator.py`
- Modify: `engine/config.py`
- Modify: `templates/team.yaml`
- Modify: `api/routes/pipelines.py`
- Test: `tests/test_engine.py`
- Test: `tests/test_config.py`
- Test: `tests/test_routes.py`

Steps:

1. Add failing orchestrator tests for pass, warning, and error Harness reports.
2. Add `harness_verify` branch before generic agent-stage execution.
3. Write `harness-report.json` to artifact dir.
4. Mark stage completed for pass/warning.
5. Mark stage failed for blocking error and write `harness-feedback.md`.
6. Add backend-only stage metadata after `qa` and before `review`.
7. Keep UI display untouched.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_engine.py::EngineTests::test_harness_verify_warning_completes_stage_and_keeps_report_artifact tests/test_engine.py::EngineTests::test_harness_verify_error_blocks_pipeline_and_writes_feedback tests/test_config.py tests/test_routes.py -q
```

### Task 8: Add Backend Checks Run Route

**Objective:** Expose project-scoped backend execution without `workdir` and without ad-hoc command execution.

**Files:**

- Modify: `api/routes/harness.py`
- Test: `tests/test_harness_routes.py`

Steps:

1. Add `POST /api/projects/{project_id}/harness/checks/run`.
2. Reuse Core `_resolve_project_root` and `_reject_workdir`.
3. Do not accept command definitions in request body.
4. Load checks from repo Harness config only.
5. In production, reject dirty Harness command config before execution.
6. Return the generated Harness report.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_routes.py::TestHarnessChecksRunApi -q
```

### Task 9: Verification And Final Report Preparation

**Objective:** Produce fresh evidence before any completion claim.

**Files:**

- Create after implementation: `docs/superpowers/reports/2026-05-09-harness-checks-final-report.md`

Steps:

1. Run all focused commands from tasks 1-8.
2. Run full backend unittest:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

3. Run focused pytest:

```bash
.venv/bin/python -m pytest tests/test_harness*.py tests/test_quality_gates.py tests/test_engine.py tests/test_routes.py tests/test_artifact_contracts.py tests/test_config.py -q
```

4. Run frontend smoke even though no UI code is modified:

```bash
cd web && npm run test
cd web && npm run build
```

5. Run diff hygiene:

```bash
git diff --check
```

6. Create Checks final report with each in-scope row marked `verified`, `partial`, or `blocked`.
7. If any row is not `verified`, final status must not be `complete`.

## Stop Rules

Stop and report before continuing if any of these occurs:

1. Completing any Checks requirement needs Task Board workflow, task memory, task events, related-task matching, UI pages, or RunDetail display.
2. Quality Gate runner hardening would break existing `quality_gates` behavior for callers that do not opt into Harness execution policy.
3. Command checks cannot be executed through `run_quality_gate(s)` and would require a Harness-only command runner.
4. A command check can bypass project/worktree cwd restrictions.
5. Baseline lowering approval requires a new human-review system or PR-review integration that does not already exist in the current platform.
6. Production command checks cannot be made fail-closed against ad-hoc or dirty Harness command config.
7. Any Checks in-scope traceability row cannot be given concrete implementation files, tests, verification command, and evidence.

## Self-Check

- [x] Repository-root `AGENTS.md` was read.
- [x] Harness governance spec was read.
- [x] Agent collaboration workflow spec was read.
- [x] Core plan was read.
- [x] Core final report was read.
- [x] `git status --short --branch` was run before Checks planning.
- [x] Core final status is `complete`.
- [x] Core in-scope rows in final report are `verified`.
- [x] Core final report has no blocking risk.
- [x] Plan is limited to Harness Checks.
- [x] Task Board and UI implementation are explicitly out of scope.
- [x] Checks in-scope requirement IDs are all present in the traceability matrix.
- [x] Each in-scope row has Implementation Files, Tests, Verification Command, and expected Evidence filled.
- [x] The plan specifies the concrete QualityGateRunner reuse path.
- [x] Stop rules include Task Board/UI dependency, QualityGateRunner compatibility risk, and baseline approval capability gaps.
- [x] The plan stops before implementation code.
