# Implement provider-owned auth probe and typed auth failure taxonomy

Status: completed

## Parent

.scratch/cloud-live-lookup-strict-preflight/PRD.md

## What to build

Implement provider-layer auth probing that validates credentials in a read-only way and returns typed auth failure classifications. The provider layer should become the source of truth for auth subtype mapping so app/UI layers consume typed outcomes rather than parsing strings.

## Acceptance criteria

- [ ] Provider auth probe is available for supported providers and performs read-only validation.
- [ ] Auth failures classify to token_invalid, token_insufficient_scope, or auth_unknown as appropriate.
- [ ] Provider layer surfaces typed auth errors consumable by upper layers.

## Blocked by

None - can start immediately
