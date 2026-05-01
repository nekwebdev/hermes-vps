# Enforce strict live preflight gate in config panel cloud step

Status: completed

## Parent

.scratch/cloud-live-lookup-strict-preflight/PRD.md

## What to build

Enforce strict preflight policy for live cloud lookup in the config panel cloud step: require token presence, provider binary availability, successful auth probe, and successful metadata probe before loading instance types. In strict runtime mode, do not auto-downgrade to sample mode on failure.

## Acceptance criteria

- [ ] Live cloud lookup in strict runtime mode hard-stops when any preflight check fails.
- [ ] Preflight sequence verifies token, binary, auth, then metadata before instance-type loading.
- [ ] Sample option mode remains available only when explicitly running non-live lookup mode.

## Blocked by

- 01-typed-cloud-remediation-contract-and-renderer.md
- 02-provider-owned-auth-probe-and-typed-auth-failure-taxonomy.md
