---
id: tasks.state-model
title: Task Memory State Model
type: task-memory-spec
status: draft
phase: phase-1
---

# Task Memory State Model

Allowed task states:

- proposed
- planned
- in_progress
- blocked
- qa_failed
- review_changes_requested
- accepted
- rejected
- cancelled
- archived

Only `accepted` means final human acceptance passed. Failed QA, requested review changes, rejected acceptance, and cancelled runs must stay distinguishable from accepted work.
