---
id: tasks.task-memory-contract
title: Task Memory Contract
type: task-memory-spec
status: draft
phase: phase-1
---

# Task Memory Contract

Task memory can influence future context only when its state and evidence are clear.

## Accepted Write Boundary

Write `accepted` only after final human acceptance passes. QA failure, review rejection, acceptance rejection, and cancellation may be recorded as history, but they must not update accepted state.

## Event and Snapshot Relationship

The durable model should be task records plus task events. A task-board snapshot can be generated for UI or read performance, but it cannot be the only authoritative state when concurrent writes are possible.

Each future event must be traceable to run ID, artifact directory, decision IDs, and touched files when available.
