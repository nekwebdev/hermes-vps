# Verify command coverage with structured action status and repair scope

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Migrate `verify` into the Python control panel command coverage path. The graph should resolve the remote target, validate SSH key readiness, run the remote verification script through the runner-backed RemoteExecutor, and expose structured action status and repair/rerun scope.

## Acceptance criteria

- [ ] A public headless Python entrypoint can run the `verify` action graph for the selected provider.
- [ ] The graph resolves server IP and admin username from OpenTofu outputs through the runner.
- [ ] Verify preflight validates readable SSH private key path and restrictive key permissions before remote execution.
- [ ] Remote verification command construction preserves current behavior and uses validated target data.
- [ ] Verification failures surface structured action status and repair/rerun scope rather than only raw stderr.
- [ ] Migrated `just verify` delegates to the Python entrypoint where feasible while preserving compatible exit behavior.
- [ ] Behavioral tests cover target resolution, key validation, remote command construction, fail-fast behavior, structured failure output, and Just shim parity.
- [ ] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/05-bootstrap-command-coverage-with-remoteexecutor-and-secret-safe-staging.md
