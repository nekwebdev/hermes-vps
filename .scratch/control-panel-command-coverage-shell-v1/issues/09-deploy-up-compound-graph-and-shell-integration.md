# Deploy/up compound graph and shell integration

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Compose the migrated operational actions into compound `up` and `deploy` workflows. The graph should reuse existing action definitions, preserve critical-path fail-fast behavior, expose progress through the panel shell and headless entrypoints, and keep Just aliases as compatibility shims.

## Acceptance criteria

- [ ] A public headless Python entrypoint can run the `up` graph as init -> plan -> apply.
- [ ] A public headless Python entrypoint can run the `deploy` graph as init -> plan -> apply -> bootstrap -> verify.
- [ ] Compound graphs reuse the same action definitions/adapters as individual command paths.
- [ ] Fail-fast behavior prevents downstream state-changing actions after critical failures.
- [ ] The panel shell exposes bootstrap/deploy flow status using structured action events/results.
- [ ] Migrated `just up` and `just deploy` delegate to Python entrypoints where feasible while preserving compatible exit behavior.
- [ ] Behavioral tests cover graph ordering, shared action definitions, failure short-circuiting, panel/headless graph alignment, and Just shim parity.
- [ ] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/03-init-upgrade-and-plan-command-coverage-with-saved-plan-artifact.md
- .scratch/control-panel-command-coverage-shell-v1/issues/04-apply-command-coverage-with-stale-plan-retry-and-ssh-alias-reconciliation.md
- .scratch/control-panel-command-coverage-shell-v1/issues/05-bootstrap-command-coverage-with-remoteexecutor-and-secret-safe-staging.md
- .scratch/control-panel-command-coverage-shell-v1/issues/06-verify-command-coverage-with-structured-action-status-and-repair-scope.md
