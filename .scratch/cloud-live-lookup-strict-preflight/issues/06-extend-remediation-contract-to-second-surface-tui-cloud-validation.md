# Extend same remediation contract to second surface (TUI cloud validation path)

Status: completed

## Parent

.scratch/cloud-live-lookup-strict-preflight/PRD.md

## What to build

Apply the same typed remediation and failure taxonomy contract to the TUI cloud validation surface so operator guidance and failure semantics stay consistent across panel and TUI paths.

## Acceptance criteria

- [ ] TUI cloud validation consumes the same typed remediation contract and failure reasons as panel flow.
- [ ] Provider-specific command guidance is consistent across both surfaces.
- [ ] Cross-surface behavior is verifiable and does not drift in wording or semantics.

## Blocked by

- 01-typed-cloud-remediation-contract-and-renderer.md
- 02-provider-owned-auth-probe-and-typed-auth-failure-taxonomy.md
- 04-map-preflight-failures-to-provider-specific-remediation-in-panel-flow.md
