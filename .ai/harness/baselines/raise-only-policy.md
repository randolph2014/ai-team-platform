---
id: baseline.policy.raise-only
title: Baseline Raise-only Policy
type: baseline-policy
severity: error
status: active
mode: raise_only
update_policy: human_approval_required
allow_auto_update: false
---

# Baseline Raise-only Policy

Baselines default to raise-only.

Allowed:

- raising a baseline after fresh evidence proves the project now exceeds it
- proposing a baseline change in a report with command evidence

Forbidden:

- silently lowering a baseline
- allowing a developer agent to lower a baseline and continue as if checks passed
- hiding baseline changes from review or final reports
