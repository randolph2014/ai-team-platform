# Harness Checks

This directory defines executable Harness checks for project governance.

## Naming

- Use `checks.<concern>.<name>` for check specs.
- Use `type: pattern`, `type: command`, or `type: baseline` in `.ai/harness.yaml`.
- Command checks must reuse the existing Quality Gate runner through `engine.harness_checks.run_harness_verification()`.
- Blocking checks must surface failure in both the individual check result and the top-level Harness report.

## Phase 3 Boundary

Phase 3 enables executable checks only. It does not introduce Task Board UI, database-backed Harness configuration, or a second command runner.
