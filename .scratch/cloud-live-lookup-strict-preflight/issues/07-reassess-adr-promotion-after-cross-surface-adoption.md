# Reassess ADR promotion after cross-surface adoption

Status: completed

## Decision notes

Decision: approved ADR promotion.

Human review outcome: promote the cloud live lookup strict preflight and typed remediation contract to an ADR now that it is used across the config panel/live lookup path and the TUI cloud validation path.

Rationale: the contract is now cross-surface, security-sensitive, and operator-visible. Keeping it only in glossary/context would make future changes too easy to miss. ADR scope is intentionally narrow: strict runtime live lookup preflight, provider-owned typed failure taxonomy, central token-safe remediation payloads/rendering, and app-layer ownership in `hermes_vps_app`.

Reversibility: moderate. We can still revise provider-specific checks or add reasons, but weakening strict runtime gating or splitting remediation per surface would be a visible architecture change and should require another ADR update.

Surprise factor: high enough for ADR. Operators might otherwise expect live lookup failures to fall back to sample values; this decision documents why runtime mode hard-stops instead.

Trade-off history: accepted stricter failures and extra provider-adapter typing in exchange for safer persisted configuration, cross-surface consistency, machine-checkable remediation, and lower secret-leak risk.

Promoted ADR: `docs/adr/0002-cloud-live-lookup-strict-preflight-and-typed-remediation.md`.

## Parent

.scratch/cloud-live-lookup-strict-preflight/PRD.md

## What to build

Perform a human architectural checkpoint to decide whether the cloud preflight taxonomy/remediation contract should be promoted from glossary context into an ADR after it is proven across at least two surfaces.

## Acceptance criteria

- [x] A decision is documented on whether ADR promotion is warranted now.
- [x] Decision explicitly references reversibility, surprise factor, and trade-off history.
- [x] If promoted, ADR scope and ownership boundaries are clearly captured.

## Blocked by

- 06-extend-remediation-contract-to-second-surface-tui-cloud-validation.md
