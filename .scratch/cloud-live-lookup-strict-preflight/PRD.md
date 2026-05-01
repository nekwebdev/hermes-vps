# PRD: Cloud Live Lookup Strict Preflight and Typed Remediation

Status: completed

## Problem Statement

As an operator using the config panel wizard, I need cloud region and instance-type options to be trustworthy and actionable. Today, live lookup failures can be opaque, provider diagnostics can be inconsistent, and remediation guidance can drift across UI surfaces. This creates risk of invalid infrastructure choices, slower recovery, and inconsistent behavior between panel flows.

## Solution

Introduce a strict preflight contract for live cloud metadata lookup and a reusable typed remediation model. In real runtime mode, live lookup should only proceed when token presence, provider binary availability, auth sanity, and metadata access checks pass. On failure, the system should hard-stop the cloud step and return provider-specific, command-specific remediation with machine-checkable expected outcomes. Auth failure classification should be owned by provider adapters and surfaced as typed reasons to app/UI layers.

## User Stories

1. As an operator, I want live cloud lookup to fail fast when credentials are missing, so that I don’t continue with invalid assumptions.
2. As an operator, I want missing provider binaries to be detected immediately, so that I can install prerequisites before proceeding.
3. As an operator, I want explicit auth sanity probes before metadata fetch, so that token issues are caught at the right stage.
4. As an operator, I want region list validation before instance-type retrieval, so that downstream options are always location-grounded.
5. As an operator, I want strict runtime gating for live lookup, so that no stale/sample data leaks into real runs.
6. As an operator, I want provider-specific remediation text, so that I can follow exact recovery steps quickly.
7. As an operator, I want command-specific remediation checks, so that I can verify readiness deterministically.
8. As an operator, I want machine-checkable expected outcomes, so that checks are automatable in future flows.
9. As a security-conscious operator, I want token-safe remediation checks, so that diagnostics never expose secret values.
10. As an app maintainer, I want a central remediation helper, so that panel/TUI/API surfaces reuse the same guidance.
11. As an app maintainer, I want a typed remediation payload, so that UI branching does not parse free-form strings.
12. As an app maintainer, I want discriminated check kinds, so that each check has clear semantics and schema.
13. As an app maintainer, I want typed failure reasons, so that behavior remains stable across refactors.
14. As an app maintainer, I want auth subtype granularity, so that invalid-token and insufficient-scope paths can diverge correctly.
15. As an app maintainer, I want an auth_unknown fallback, so that diagnostics remain honest when provider messages are ambiguous.
16. As a framework maintainer, I want provider adapter ownership of auth classification, so that domain parsing logic stays close to provider implementations.
17. As a panel developer, I want app/UI layers to consume typed auth errors, so that they focus on presentation and policy.
18. As a tester, I want dedicated tests for remediation rendering and classification behavior, so that regressions are caught early.
19. As a release owner, I want CONTEXT vocabulary and ADR constraints reflected in this behavior, so that architectural consistency is preserved.
20. As an operator, I want deterministic fallback to sample options only when explicitly configured for non-live mode, so that runtime intent is clear.
21. As an operator, I want failure messages to include install hints and docs links, so that recovery can be completed without external guesswork.
22. As a future automation author, I want predicate-based check contracts (`exit_code_eq`, `json_path_exists`, `stdout_regex`), so that preflight can be reused in scripted validations.
23. As a maintainer, I want cloud preflight semantics documented in the project glossary, so that future contributors use consistent language.
24. As a maintainer, I want no automatic downgrade from strict runtime mode to sample mode, so that safety policy is enforced uniformly.

## Implementation Decisions

- Keep the panel execution model aligned with the DAG action engine and fail-fast critical path policy.
- Preserve lookup mode split:
  - non-live mode returns deterministic sample options,
  - live mode performs provider-backed discovery.
- Enforce strict live preflight in real runtime mode:
  - token presence,
  - provider binary presence,
  - read-only auth probe,
  - metadata probe (regions/locations) before instance-type loading.
- On preflight failure, hard-stop the cloud step in real runtime mode; do not auto-downgrade to sample options.
- Use a central remediation helper with a stable typed payload contract containing:
  - summary,
  - typed checks,
  - install hints,
  - optional docs URL,
  - typed failure reason.
- Model checks as a discriminated union with explicit kinds:
  - binary_present,
  - token_present,
  - auth_probe,
  - metadata_probe.
- Model expected outcomes as machine-checkable predicates with optional human notes.
- Require token-safe remediation checks by construction (no secret echo/output paths).
- Adopt failure taxonomy for UI branching:
  - missing_binary,
  - missing_token,
  - metadata_unavailable,
  - auth subtypes.
- Split auth subtype handling when detectable:
  - token_invalid,
  - token_insufficient_scope,
  - auth_unknown fallback when inconclusive.
- Place auth subtype classification in provider service/adapters and raise typed auth errors; app/UI layers consume typed reasons.
- Keep ADR creation deferred for this taxonomy/remediation contract until it is reused across at least two surfaces and still appears hard to reverse.

## Testing Decisions

- Good tests validate external behavior and contracts, not internal implementation details.
- Test target modules:
  - provider adapter auth classification and typed auth error behavior,
  - remediation payload and rendering contract,
  - config panel live preflight gating and failure mapping,
  - existing engine smoke path stability.
- Behavioral assertions should cover:
  - strict gating outcomes,
  - provider-specific remediation content,
  - token-safe check content,
  - typed reason propagation,
  - predicate contract formatting.
- Prior art:
  - existing control-core engine smoke tests,
  - configure services tests for provider/token workflows,
  - configure TUI tests for validation/recovery interactions.

## Out of Scope

- Freezing a public cross-project plugin API for remediation payloads.
- Background collectors or asynchronous monitoring daemons.
- Dynamic runtime graph expansion beyond current static DAG with small conditionals.
- Broad provider expansion beyond currently supported providers in this workflow.
- Automatic auth scope escalation or token provisioning flows.
- Any change to unrelated Hermes agent version pinning workflows.

## Further Notes

- This PRD uses glossary terms from the project context and remains consistent with accepted control-panel architecture ADR constraints.
- The strict preflight and typed remediation path is intentionally conservative to prevent invalid persistence and unsafe progression in runtime configuration flows.
- If/when the same remediation contract is consumed by multiple surfaces (panel + TUI + API), reassess ADR promotion for long-term governance.
