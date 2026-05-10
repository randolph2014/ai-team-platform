---
id: checks.phase3.quality-gate-policy
title: Phase 3 Quality Gate Policy Smoke
type: command-check
severity: error
status: active
phase: phase-3
---

# Phase 3 Quality Gate Policy Smoke

This check proves that repository Harness command checks are executable and routed through the shared quality gate path.

Current command:

```text
.venv/bin/python -m pytest tests/test_quality_gates.py::TestQualityGateExecutionPolicy::test_policy_requires_timeout -q
```

Execution requirements:

- The command is declared in `.ai/harness.yaml`, not in DB state.
- The command is executed by `engine.harness_checks.run_harness_verification()` through `run_quality_gates()`.
- The check is blocking when it fails.
- The resulting Harness report must include check ID, status, blocking flag, duration, exit code, and evidence refs.
- This check must not bypass AGENTS.md, human gates, quality gates, or platform safety policy.
