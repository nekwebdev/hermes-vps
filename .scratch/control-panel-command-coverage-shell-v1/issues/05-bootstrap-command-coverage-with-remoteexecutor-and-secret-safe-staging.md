# Bootstrap command coverage with RemoteExecutor and secret-safe staging

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Migrate `bootstrap` into the Python control panel command coverage path using a runner-backed RemoteExecutor adapter. The graph should preserve current target resolution, validation, runtime secret staging, rsync/SSH execution, idempotent remote bootstrap behavior, cleanup, and secret-safety guarantees.

## Acceptance criteria

- [ ] A public headless Python entrypoint can run the `bootstrap` action graph for the selected provider.
- [ ] The graph resolves server IP and admin username from OpenTofu outputs through the runner.
- [ ] Bootstrap preflight validates SSH key path expansion, existence, readability, and restrictive permissions before remote execution.
- [ ] Bootstrap preflight validates required Hermes/Telegram/provider values, allowed TCP port syntax, pinned Hermes version shape, and Telegram allowlist shape before remote execution.
- [ ] Runtime env files and OAuth artifacts are materialized only at execution boundaries and cleaned up after execution.
- [ ] Action events, graph results, audit records, and error messages do not contain raw provider tokens, Hermes API keys, Telegram bot tokens, OAuth artifact contents, or generated runtime env values.
- [ ] Remote staging, rsync, SSH bootstrap script execution, verification script invocation, and cleanup preserve current behavior.
- [ ] Migrated `just bootstrap` delegates to the Python entrypoint where feasible while preserving compatible exit behavior.
- [ ] Behavioral tests cover validation failures, command ordering, remote command construction, cleanup, redaction, fail-fast behavior, and Just shim parity.
- [ ] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/01-init-command-tracer-bullet-through-headless-app-runner-graph-and-just-shim.md
