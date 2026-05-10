---
id: governance.source-of-truth
title: Harness Source of Truth
type: rule
severity: error
status: active
---

# Harness Source of Truth

Harness governance assets live in repository files:

- `.ai/harness.yaml`
- `.ai/harness/rules/**`
- `.ai/harness/skills/**`
- `.ai/harness/checks/**`
- `.ai/harness/baselines/**`
- `.ai/harness/tasks/**`

DB state may store runtime settings, execution results, audit logs, and UI caches. DB state must not become the primary Harness configuration source.

Platform templates, prompt overrides, and run-scoped pipeline configs remain separate layers. A Harness asset can reference those layers as context, but cannot replace or silently override them.
