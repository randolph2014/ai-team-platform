---
id: checks.contract.skeleton-only
title: Harness Checks Contract
type: check-spec
severity: info
status: active
phase: phase-3
---

# Harness Checks Contract

This file records the active executable check contract.

Executable checks must include:

- stable ID
- type: `pattern`, `command`, or `baseline`
- severity and blocking semantics
- evidence fields for report generation
- safe file globs or safe command cwd
- timeout for command checks

Command checks are translated into the existing Quality Gate execution path. Harness must not grow a second command runner.

Harness report check results must include `id`, `status`, `blocking`, `duration_ms`, `exit_code`, and `evidence_refs`. Blocking failures must prevent downstream stage progress through the `harness_verify` stage or report `next_stage_contract.blocked=true`.
