# Aggregate command parity and docs cutover gate

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Add the final v2 regression/cutover gate. This slice should prove command parity, docs cutover readiness, metadata policy, redaction matrix, and cross-surface behavior are green before future HITL decisions about Justfile removal or plugin API stability.

## Acceptance criteria

- [ ] Aggregate tests cover migrated commands across graph definitions, headless CLI, panel shell, and Just shims where applicable.
- [ ] The gate verifies side-effect/timeout metadata policy for all operational and monitoring graphs.
- [ ] The gate includes the secret redaction regression matrix or depends on it explicitly in test selection.
- [ ] The docs cutover checklist is validated or referenced by a regression test/documentation check.
- [ ] The gate is documented as a prerequisite for future Justfile removal and stable public plugin API decisions.
- [ ] No Justfile removal or plugin API declaration is performed in this issue.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/05-side-effect-and-timeout-policy-gate-across-operational-graphs.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/09-secret-redaction-regression-matrix-across-all-public-result-surfaces.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/11-just-shim-parity-and-duplicated-preflight-reduction.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/12-operator-docs-cutover-guide-for-migrated-control-panel-workflows.md
