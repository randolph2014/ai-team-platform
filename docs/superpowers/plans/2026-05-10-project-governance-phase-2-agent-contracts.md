# Project Governance Phase 2 Agent Contracts Implementation Plan

**Goal:** Make agent collaboration artifacts mechanically require traceability evidence so plans, implementation, QA, and review cannot claim completion without file/test/Harness evidence.

**Architecture:** Keep the existing pipeline and agent roles. Tighten the artifact contract layer first, then align planner/coder/reviewer prompts with the schema. This phase does not implement new checks, Task Board behavior, or UI.

**Tech Stack:** Python 3.12, JSON schema files under `engine/schemas`, `engine/artifact_contracts.py`, existing prompt templates under `templates/agents`, pytest.

---

## Scope

In scope:

- Add a schema for `implementation-report.json`.
- Register the schema in `engine/artifact_contracts.py`.
- Require `acceptance_coverage` and `evidence` in `test-report.json`.
- Require `findings`, `evidence`, and `risks` in `review-report.json`.
- Add a shared `traceability` field to implementation, test, and review report schemas.
- Update default agent prompts so Coder/Reviewer/QA explicitly produce traceability evidence.
- Add tests that prove the new contracts fail without traceability/evidence and pass with it.

Out of scope:

- New Harness check execution.
- Task Board implementation changes.
- UI changes.
- DB-backed Harness configuration.
- Changing pipeline stage ordering.

## Acceptance Matrix

| ID | Requirement | Implementation Files | Tests | Verification |
|---|---|---|---|---|
| P2-001 | `implementation-report.json` is schema-validated | `engine/schemas/implementation-report.json`; `engine/artifact_contracts.py` | `tests/test_artifact_contracts.py` | pytest artifact contracts |
| P2-002 | implementation report requires `traceability`, `acceptance_coverage`, `evidence` | `engine/schemas/implementation-report.json` | `tests/test_artifact_contracts.py` | pytest artifact contracts |
| P2-003 | test report requires `acceptance_coverage`, `evidence`, and `traceability` | `engine/schemas/test-report.json` | `tests/test_artifact_contracts.py` | pytest artifact contracts |
| P2-004 | review report requires `findings`, `evidence`, `risks`, and `traceability` | `engine/schemas/review-report.json` | `tests/test_artifact_contracts.py` | pytest artifact contracts |
| P2-005 | prompts instruct agents to output traceability evidence | `templates/agents/coder.md`; `templates/agents/reviewer.md`; `templates/agents/qa-automation.md`; `templates/agents/code-reviewer.md`; `templates/agents/tech-lead.md` | `tests/test_config.py` | pytest prompt contract tests |
| P2-006 | phase boundary remains intact | report and scans | grep/rg scan | no Checks/Task Board/UI behavior introduced |

## Implementation Steps

1. Add failing tests in `tests/test_artifact_contracts.py`:
   - `load_schema_for_artifact("implementation-report.json")` returns a schema.
   - implementation report without `traceability` fails.
   - implementation report with `traceability` passes.
   - test report without `traceability` fails.
   - review report without `traceability` fails.

2. Add failing prompt contract tests in `tests/test_config.py`:
   - Coder/Tech Lead prompts mention `traceability`.
   - Reviewer/QA prompts mention `traceability`.
   - Prompts mention Harness evidence and file/test evidence.

3. Implement schemas:
   - Create `engine/schemas/implementation-report.json`.
   - Add `implementation-report.json` to `SCHEMA_FILE_MAP`.
   - Add `traceability` definitions to implementation/test/review schemas.

4. Update prompts:
   - Coder/Tech Lead: implementation reports must map each acceptance ID to changed files, tests run, Harness evidence, and status.
   - QA/Reviewer: test/review reports must validate task-plan coverage and provide traceability evidence.
   - Keep wording concise; do not add new roles.

5. Verify:
   - `.venv/bin/python -m pytest tests/test_artifact_contracts.py tests/test_config.py -q`
   - `.venv/bin/python -m pytest tests/test_harness_core.py -q`
   - `git diff --check`
   - residual scan for legacy project team config entry.

## Stop Conditions

- If current report schemas are consumed by old generated artifacts in a way that breaks existing tests outside this phase, stop and report the compatibility decision needed.
- If adding traceability would require changing orchestrator behavior instead of artifact schema/prompt contracts, stop and split into a separate phase.
- If any Phase 3/4 implementation is needed to make tests pass, stop; this phase must remain contract-only.
