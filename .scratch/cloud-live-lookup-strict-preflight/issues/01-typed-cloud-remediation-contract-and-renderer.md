# Define typed cloud remediation contract and renderer

Status: completed

## Parent

.scratch/cloud-live-lookup-strict-preflight/PRD.md

## What to build

Build a deep-module remediation contract for cloud preflight failures that returns a typed payload with provider, typed reason, structured checks, install hints, and optional docs reference. Include a renderer that produces operator-facing, provider-specific, command-specific guidance while preserving token-safe output behavior.

## Acceptance criteria

- [ ] A stable typed remediation payload exists and can represent all agreed cloud preflight failure reasons.
- [ ] Checks are modeled as discriminated kinds with machine-checkable expected predicates and optional human notes.
- [ ] Rendered remediation output includes provider-specific command guidance and install hints without exposing secrets.

## Blocked by

None - can start immediately
