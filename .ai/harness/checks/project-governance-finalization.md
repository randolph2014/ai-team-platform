---
id: checks.governance.project-finalization
title: Project Governance Finalization Check
type: command-check
severity: error
status: active
phase: finalization
---

# Project Governance Finalization Check

This check enforces ai-team-platform project-specific governance invariants.

It verifies:

- repository Harness assets exist and remain the source of truth
- deprecated legacy project team entry wording does not reappear as a fact source
- Harness and Task Board public APIs stay project-scoped
- Harness checks reuse the shared quality gate runner boundary
- Harness UI editing remains limited to Harness assets
- governance reports contain fresh verification evidence

The check intentionally lives as a project script instead of a bespoke project skill. The generic delivery workflow stays in the shared requirement delivery skill; this repository owns only its local invariants and mechanical enforcement.
