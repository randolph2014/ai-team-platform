---
id: governance.phase-scoped-implementation
title: Phase-scoped Implementation
type: skill
status: active
allowed_agents:
  - planner
  - coder
  - reviewer
forbidden_capabilities:
  - bypass_human_gate
  - bypass_quality_gate
  - disable_checks
  - modify_baselines
  - override_platform_policy
  - use_db_as_harness_source
  - expand_phase_scope
---

# Phase-scoped Implementation

Use this method when implementing a Harness sub-iteration.

1. Read the governing spec and current code before editing.
2. List the exact in-scope files and out-of-scope files.
3. Add a focused test, schema validation, or mechanical scan before writing the asset or behavior.
4. Keep the phase boundary intact. Do not implement a later phase to make the current report look complete.
5. Update the final report only with evidence produced in the current verification run.
