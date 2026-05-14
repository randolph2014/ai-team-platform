# Agent Handoff Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pipeline configuration the source of truth for agent handoff inputs and outputs, with structured planning challenge artifacts and schema validation.

**Architecture:** Keep Orchestrator as the central handoff controller. Split planning into draft, challenge, and finalize stages in pipeline config; define JSON schemas for the new artifacts; update prompts to follow stage-specific contracts; validate existing structured input artifacts before entering downstream stages.

**Tech Stack:** Python 3.14-compatible code, YAML pipeline templates, JSON schema files under `engine/schemas`, pytest.

---

## Files

- Modify: `engine/config.py` for fallback default pipeline and stage-entry validation targets.
- Modify: `templates/team.yaml` for platform default pipeline.
- Modify: `engine/artifact_contracts.py` for new schema registrations.
- Modify: `engine/orchestrator.py` for stricter input artifact validation.
- Modify: `templates/agents/planner.md` and `templates/agents/challenger.md` for stage-specific output contracts.
- Add: `engine/schemas/solution-plan.json`, `engine/schemas/plan-draft.json`, `engine/schemas/plan-review.json`.
- Modify: `tests/test_config.py`, `tests/test_artifact_contracts.py`, and `tests/test_engine.py`.

## Tasks

### Task 1: Pipeline Handoff Shape

- [x] Add failing config tests that assert the default pipeline contains `planning_draft`, `plan_challenge`, and `planning_finalize` in that order.
- [x] Update `templates/team.yaml` and `engine/config.py` to make those stages the default handoff sequence.
- [x] Verify config tests pass.

### Task 2: Structured Planning Artifacts

- [x] Add failing artifact contract tests for `solution-plan.json`, `plan-draft.json`, and `plan-review.json`.
- [x] Add schemas and register them in `engine/artifact_contracts.py`.
- [x] Verify artifact contract tests pass.

### Task 3: Prompt Contracts

- [x] Add prompt contract assertions for `plan-draft.json`, `plan-review.json`, and `planning_finalize`.
- [x] Update Planner and Challenger prompts to output exactly the configured artifacts for their active stages.
- [x] Verify prompt contract tests pass.

### Task 4: Input Validation

- [x] Add an orchestrator test proving a downstream stage fails before execution when an existing input JSON artifact is malformed or schema-invalid.
- [x] Implement generic stage-entry validation for declared concrete JSON inputs.
- [x] Verify focused engine tests pass.

### Task 5: Regression

- [x] Run `tests/test_artifact_contracts.py`, `tests/test_config.py`, and the relevant engine contract tests.
- [x] Run `git diff --check`.
- [x] Report any pre-existing dirty worktree risk separately from this change.
