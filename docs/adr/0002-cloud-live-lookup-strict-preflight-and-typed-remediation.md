# ADR-0002: Cloud Live Lookup Strict Preflight and Typed Remediation

Status: Accepted
Date: 2026-04-30

## Context

The configuration flow supports live cloud metadata lookup for provider regions and instance types. In runtime mode, stale sample data or opaque provider failures can cause invalid infrastructure choices to be persisted.

The typed remediation contract has now been adopted across more than one surface: the config panel/live lookup path and the TUI cloud validation path. Both surfaces consume the same provider-owned failure taxonomy and central remediation renderer.

We need a durable architectural decision for the strict live lookup gate and typed remediation model while preserving the existing package boundary: cloud-provider behavior remains app-owned in `hermes_vps_app`, not framework-core public plugin API.

## Decision

Adopt the cloud live lookup strict preflight and typed remediation contract as an accepted project architecture decision.

1. Runtime lookup mode
- `live_cloud_lookup=false` may use deterministic sample options for non-live configuration flows.
- `live_cloud_lookup=true` performs provider-backed metadata discovery.
- Real runtime live lookup must hard-stop on preflight failure.
- Real runtime live lookup must not silently downgrade to sample options.

2. Strict preflight gate
- Live lookup requires provider token presence.
- Live lookup requires provider binary availability.
- Live lookup requires a read-only auth sanity probe.
- Live lookup requires a metadata probe, such as region/location list access, before instance-type retrieval.

3. Failure taxonomy
- Provider adapters own auth and metadata failure classification.
- App/UI layers consume typed reasons rather than parsing free-form command output.
- Supported typed reasons include:
  - `missing_binary`
  - `missing_token`
  - `token_invalid`
  - `token_insufficient_scope`
  - `auth_unknown`
  - `metadata_unavailable`
- Ambiguous provider diagnostics use `auth_unknown` rather than forcing false precision.

4. Typed remediation contract
- Remediation is produced through the central `hermes_vps_app` helper.
- Payloads include:
  - provider
  - typed failure reason
  - summary
  - checks
  - install hints
  - optional docs URL
  - optional redacted diagnostic detail
- Checks are a discriminated union with explicit kinds:
  - `binary_present`
  - `token_present`
  - `auth_probe`
  - `metadata_probe`
- Expected outcomes are machine-checkable predicates, for example `exit_code_eq=0`, `json_path_exists`, or `stdout_regex`, with optional human notes.

5. Secret-safety
- Remediation checks must be token-safe by construction.
- Rendered remediation must not echo provider tokens, secret-like detail values, OAuth artifacts, or raw environment contents.
- Diagnostics may include redacted detail and non-secret command guidance.

6. Ownership and API lifecycle
- The contract is stable for this repository’s app surfaces.
- The contract remains owned by `hermes_vps_app` provider/configuration code.
- This ADR does not freeze a public third-party plugin API and does not move provider-specific behavior into `hermes_control_core`.

## Consequences

Positive:
- Operators cannot accidentally persist invalid live cloud assumptions after preflight failure.
- Panel and TUI surfaces share the same remediation semantics and wording source.
- Tests can assert structured failure reasons and machine-checkable remediation checks.
- Secret-safety is enforced at the contract level instead of relying on per-surface wording discipline.

Costs / trade-offs:
- Live runtime mode is stricter: missing binaries, missing tokens, auth failures, or metadata failures block progress rather than allowing degraded sample data.
- Provider adapters must maintain typed classification logic close to provider command/API behavior.
- Adding a new provider requires remediation payload/check coverage, not only lookup commands.

## Alternatives Considered

1) Keep remediation in glossary/context only
- Rejected: the contract now spans multiple surfaces and is no longer just local implementation detail.

2) Let each UI surface render provider failures independently
- Rejected: creates wording drift, duplicated auth parsing, and higher secret-leak risk.

3) Fall back to sample options when live lookup fails
- Rejected for runtime mode: safer to hard-stop than persist invalid cloud choices.

4) Promote this to public framework/plugin API now
- Rejected: provider behavior remains app-specific, and stable public plugin API declaration is separately deferred.
