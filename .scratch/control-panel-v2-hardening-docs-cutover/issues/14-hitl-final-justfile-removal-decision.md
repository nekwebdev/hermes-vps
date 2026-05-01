# HITL final Justfile removal decision

Status: completed

## Decision notes

Decision: deferred.

Human review outcome: do not approve Justfile removal yet. Keep the Justfile as a thin compatibility shim through at least one real operator cycle after the docs cutover and v2 aggregate gate.

Rationale: command parity and docs cutover are green, but compatibility risk remains for existing operator muscle memory and rollback expectations. Deferring keeps rollback simple: operators can continue using Just recipes while the Python entrypoints become the canonical automation surface.

Removal criteria for a future HITL checkpoint:
- one real operator cycle completes using the Python entrypoints and operator guide,
- no parity regressions are found in Just shim, CLI, panel shell, or graph definitions,
- rollback expectations are documented for operators who still use Just,
- a separate removal implementation issue is created and reviewed before deleting the Justfile.

No Justfile removal is approved by this issue.

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Human checkpoint only. Decide whether command parity and docs cutover are sufficient to approve a later implementation issue that removes the Justfile. This issue records the decision and criteria; it does not remove the Justfile.

## Acceptance criteria

- [ ] A human reviews the aggregate command parity gate and docs cutover checklist.
- [ ] The decision records whether Justfile removal is approved, deferred, or rejected.
- [ ] The decision explicitly references compatibility risk, operator docs readiness, and rollback expectations.
- [ ] If approved, a separate implementation issue is proposed for removal; this issue itself does not remove the Justfile.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/13-aggregate-command-parity-and-docs-cutover-gate.md
