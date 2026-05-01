# Add regression test slices for typed remediation, auth taxonomy, and strict gate behavior

Status: completed

## Parent

.scratch/cloud-live-lookup-strict-preflight/PRD.md

## What to build

Add behavior-first regression coverage for typed remediation payload/rendering, provider auth failure classification, strict gate preflight sequencing, and failure-to-remediation mapping in cloud flows.

## Acceptance criteria

- [ ] Tests assert external behavior and contracts rather than implementation details.
- [ ] Coverage exists for token-safe remediation guidance and machine-checkable predicate formatting.
- [ ] Strict preflight and failure mapping regressions are detectable via automated tests.

## Blocked by

- 01-typed-cloud-remediation-contract-and-renderer.md
- 02-provider-owned-auth-probe-and-typed-auth-failure-taxonomy.md
- 03-strict-live-preflight-gate-in-config-panel-cloud-step.md
- 04-map-preflight-failures-to-provider-specific-remediation-in-panel-flow.md
