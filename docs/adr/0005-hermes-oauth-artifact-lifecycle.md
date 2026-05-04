# ADR-0005: Hermes OAuth Artifact Lifecycle

Status: Accepted
Date: 2026-05-03

## Context

The panel Hermes configuration step needs to support provider OAuth credentials without leaking durable auth state during ordinary configuration navigation.

Hermes metadata is loaded through a selected-version toolchain cache so provider/model/auth behavior matches the Hermes version that Review/Apply will persist and the VPS will later install. OAuth must use the same selected-version Hermes CLI rather than a global `hermes` command.

OAuth is user-driven and long-running: the operator may need to copy a device URL/code into a browser and wait for the provider flow to complete. At the same time, the panel's configuration model uses draft semantics: controls can be changed before Review/Apply, and durable local state should not be written just because the operator clicked through an intermediate step.

The auth artifact produced by Hermes OAuth is a secret-bearing `auth.json`. It is durable operator state, not rebuildable cache. It must therefore not live under `.cache/` after Apply, must not be displayed in UI/logs, and must not be staged into bootstrap runtime directories until the later deploy/bootstrap workflow runs.

## Decision

Use a draft-then-apply OAuth artifact lifecycle for Hermes provider OAuth.

1. Selected-version OAuth execution
- `Start OAuth` runs the selected-version Hermes CLI, not a global command.
- The command is:
  `HERMES_HOME=<draft_home> <toolchain>/venv/bin/hermes auth add <provider> --type oauth --no-browser`
- The draft home is `.cache/hermes-oauth-drafts/<request_id>/home`.
- `--no-browser` is the default so the panel can render deterministic URL/code instructions in local, SSH, or tmux contexts.

2. Draft home lifecycle
- Each OAuth run uses an isolated draft home.
- On success, the panel reads the generated `auth.json` into memory, then deletes the draft directory.
- On failure or cancellation, the panel deletes the draft directory and stores no artifact.
- Panel startup performs best-effort cleanup of stale `.cache/hermes-oauth-drafts/*` directories older than 24 hours.
- Draft homes are never durable fallbacks.

3. Service contract
- Implement OAuth as a service-layer runner before Textual UI wiring.
- The service streams stdout/stderr events, extracts URL/code hints as best-effort display instructions, waits for process exit, validates success strictly, and returns a typed result.
- `HermesOAuthRunResult` includes status (`succeeded`, `failed`, or `cancelled`), provider, agent version, agent release tag, `auth_method = "oauth"`, `auth_json_bytes` only on success, `auth_json_sha256`, extracted instructions, bounded output tail, exit code, and error message.
- Raw auth JSON must not be rendered in UI or logs.
- URL/code extraction is best-effort and does not determine success. Success requires exit code 0 plus a non-empty, valid JSON `auth.json` in the draft home.

4. Cancellation
- The service exposes a cancellation handle/event.
- Cancellation sends SIGTERM, escalates to SIGKILL after a short grace period, returns status `cancelled`, deletes the draft home, and never reads or stores `auth.json`, even if the process wrote one before cancellation.
- The Textual button changes from `Start OAuth` to `Cancel OAuth` while OAuth is running.

5. Textual Hermes-step behavior
- While OAuth is running, disable conflicting Hermes controls: version, provider, auth method, model if present, and `Next: Gateways`.
- Stream bounded output into the Hermes OAuth/status area.
- Render extracted URL/code instructions prominently.
- On success, store the in-memory artifact in draft state bound to `(agent_version, agent_release_tag, provider, auth_method)` and show `OAuth artifact captured. It will be written at Review/Apply.`
- On failure, store no artifact and show the bounded output tail plus actionable error.
- On cancellation, store no artifact and show `OAuth cancelled. No artifact captured.`
- If version, provider, or auth method changes after capture, clear the captured result and show `Run OAuth again for current Hermes selection.`

6. Validation before leaving Hermes step
- First-run OAuth requires a fresh captured artifact for the current `(agent_version, agent_release_tag, provider, auth_method)` before `Next: Gateways`.
- Reconfigure mode may offer `Keep existing OAuth artifact` when existing `.env` already uses OAuth and `.hermes-home/auth.json` exists.
- Keep-existing represents existing-secret presence only; the panel does not parse or validate artifact contents for provider matching.
- Keep-existing is valid only when Hermes version/release tag, provider, and auth method are unchanged from existing `.env`.
- Changing provider, auth method, Hermes version, or release tag makes the existing artifact stale and requires `Start OAuth` again.

7. Durable local artifact path
- Apply writes durable OAuth state to root-level `.hermes-home/auth.json`.
- `.hermes-home/` is gitignored.
- `.hermes-home/auth.json` is the only durable local OAuth source of truth.
- OAuth artifacts must not live under `.cache/` after Apply and must not be treated as bootstrap runtime staging state.

8. Apply transaction
- API-key auth mode remains unchanged.
- For fresh OAuth artifacts, Review/Apply validates that the captured artifact matches the current Hermes selection, creates `.hermes-home/`, writes `.hermes-home/.auth.json.tmp` with owner-only permissions, writes `.env` through the existing atomic env path, then renames the temp artifact to `.hermes-home/auth.json`.
- When OAuth mode has a fresh matching captured artifact, Apply overwrites any existing `.hermes-home/auth.json` without a second replace prompt; completing `Start OAuth` is the operator's replacement intent.
- If `.env` writing fails, Apply deletes the temp artifact and does not leave durable OAuth state.
- If final auth rename fails after `.env` is written, Apply reports failure and a retry may complete the auth write from the still-open draft.
- For keep-existing OAuth, Apply writes `.env` only and does not rewrite `.hermes-home/auth.json`.

9. Future bootstrap contract
- Deploy/bootstrap artifact staging is deferred until after configuration steps are complete.
- The later deploy/bootstrap workflow will read `.hermes-home/auth.json` as the local durable source, stage it to `bootstrap/runtime/hermes-auth.json` during execution, deploy it to `/var/lib/hermes/.hermes/auth.json`, and clean `bootstrap/runtime/`.
- `bootstrap/runtime/hermes-auth.json` must not be accepted as an operator-provided durable source.
- No bootstrap TODO tests or placeholder implementation are added as part of the current config-panel OAuth work.

## Consequences

Positive:
- OAuth uses the same selected Hermes version as metadata, Apply, and eventual VPS install.
- The operator can complete OAuth in the panel without immediately writing durable auth state.
- `Next: Gateways` reflects real OAuth capture rather than placeholder success.
- Draft state stays reversible until Review/Apply.
- `.hermes-home/auth.json` gives a clear durable local source of truth.
- Bootstrap runtime staging remains a later execution concern and cannot accidentally become the operator source.

Costs / trade-offs:
- OAuth implementation needs subprocess streaming, cancellation, temporary home cleanup, and careful secret handling.
- Reconfigure keep-existing relies on `.env` selection matching and artifact presence rather than introspecting `auth.json`.
- Apply has a multi-file transaction boundary: `.env` and `auth.json` cannot be atomically committed together as one filesystem operation.
- The later bootstrap workflow still needs its own implementation and tests for staging, permissions, and remote install.

## Alternatives Considered

1) Run OAuth directly against `.hermes-home/`
- Rejected: writes durable auth state before Review/Apply and breaks panel draft semantics.

2) Store OAuth artifacts under `.cache/`
- Rejected: OAuth credentials are durable operator state, not rebuildable cache.

3) Use global `hermes auth add`
- Rejected: risks provider/auth behavior drifting from the selected Hermes version.

4) Use `hermes login`
- Rejected: the panel configures provider-scoped pooled credentials, so `hermes auth add <provider> --type oauth` matches the domain better.

5) Require a second replace confirmation before overwriting `.hermes-home/auth.json`
- Rejected: completing `Start OAuth` for the current draft is already explicit replacement intent, and a second prompt would add redundant operator friction.

6) Parse existing `.hermes-home/auth.json` to validate provider/version in reconfigure mode
- Rejected for now: provider/version binding comes from existing `.env` plus unchanged selection. The artifact is treated as secret presence unless the operator runs OAuth again.

7) Implement bootstrap staging in the current OAuth slice
- Rejected: bootstrap happens after configuration is complete and belongs to a later deploy/bootstrap workflow.
