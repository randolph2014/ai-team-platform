---
id: governance.evidence-based-review
title: Evidence-based Review
type: skill
status: active
allowed_agents:
  - planner
  - reviewer
forbidden_capabilities:
  - bypass_human_gate
  - bypass_quality_gate
  - hide_failed_checks
  - lower_baseline_without_approval
  - mark_unverified_complete
---

# Evidence-based Review

Use this method when reviewing Harness governance changes.

1. Check that each conclusion maps to a file, test, command, or scan.
2. Separate current-phase evidence from future-phase plans.
3. Treat stale command output as missing evidence.
4. Treat silent baseline lowering, disabled checks, or hidden failures as blocking.
5. Confirm the final report names remaining risks instead of presenting them as finished work.
