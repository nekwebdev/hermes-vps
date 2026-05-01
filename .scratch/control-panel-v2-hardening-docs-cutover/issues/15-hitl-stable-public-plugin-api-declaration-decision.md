# HITL stable public plugin API declaration decision

Status: completed

## Decision notes

Decision: deferred.

Human review outcome: do not declare any stable public plugin API now. Keep v2 contracts internal/provisional.

Rationale: hardened internal contracts are now used across CLI, panel shell, graph execution, result schemas, event streams, audit/session output, redaction, and docs. However, declaring a stable public plugin API would create a compatibility burden before real external plugin users exist and before reversibility has been proven across more hardening cycles.

Future reconsideration criteria:
- at least one real external plugin user or concrete plugin integration need exists,
- internal contracts survive another hardening cycle without breaking churn,
- compatibility burden and supported core/plugin version ranges are explicitly designed,
- a separate API design/implementation issue is created before publishing or freezing any API.

No stable public plugin API is approved, frozen, or published by this issue.

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Human checkpoint only. Decide whether internal v2 contracts are mature enough to declare any stable public plugin API. The default acceptable outcome is to defer and keep the plugin API provisional.

## Acceptance criteria

- [ ] A human reviews the hardened internal contracts and their cross-surface usage.
- [ ] The decision records whether any stable public plugin API is approved, deferred, or rejected.
- [ ] The decision explicitly references reversibility, compatibility burden, and whether real external plugin users exist.
- [ ] If a stable API is approved, a separate implementation/design issue is proposed; this issue itself does not freeze or publish the API.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/13-aggregate-command-parity-and-docs-cutover-gate.md
