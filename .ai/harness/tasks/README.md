# Harness Task Memory

Task memory records project delivery history and decisions. Phase 1 defines the state and write-boundary contract only; it does not implement Task Board behavior.

## Files

- `state-model.md`: allowed task states.
- `task-memory-contract.md`: accepted-state write boundary and event/snapshot relationship.

Task memory documents are included in the Harness manifest because they live under `.ai/harness/**`, but the current Harness config schema does not expose a top-level `tasks` list.
