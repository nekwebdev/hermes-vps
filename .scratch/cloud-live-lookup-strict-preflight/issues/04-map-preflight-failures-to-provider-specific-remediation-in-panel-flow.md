# Map preflight failures to provider-specific command remediation in panel flow

Status: completed

## Parent

.scratch/cloud-live-lookup-strict-preflight/PRD.md

## What to build

Wire strict preflight failures in the panel cloud flow to typed remediation payloads so operators get provider-specific, command-specific recovery steps with machine-checkable expectations and token-safe guidance.

## Acceptance criteria

- [ ] Each preflight failure reason maps to the correct typed remediation payload and rendered guidance.
- [ ] Auth subtype failures use provider-owned typed reasons without UI string parsing.
- [ ] Operator-facing failure output remains token-safe and actionable.

## Blocked by

- 01-typed-cloud-remediation-contract-and-renderer.md
- 02-provider-owned-auth-probe-and-typed-auth-failure-taxonomy.md
- 03-strict-live-preflight-gate-in-config-panel-cloud-step.md
