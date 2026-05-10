---
id: governance.scope.phase-boundary
title: Phase Boundary and Evidence
type: rule
severity: error
status: active
---

# Phase Boundary and Evidence

Harness work must be delivered by the approved phase boundary. A Phase 1 task can create governance skeletons and metadata contracts, but it must not implement Checks execution, Task Board behavior, or UI.

Every completion claim must point to fresh command output, file evidence, or scan evidence. If an in-scope item cannot be verified, the status is partial or blocked, not complete.

Out-of-phase changes require explicit human approval before editing files.
