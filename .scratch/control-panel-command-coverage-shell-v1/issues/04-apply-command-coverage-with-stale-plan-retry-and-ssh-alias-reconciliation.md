# Apply command coverage with stale-plan retry and SSH alias reconciliation

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Migrate `apply` into the Python control panel command coverage path. The action graph should apply the saved plan, regenerate and retry on missing/stale plan cases, surface structured status, and reconcile the SSH alias only after successful infrastructure apply.

## Acceptance criteria

- [ ] A public headless Python entrypoint can run the `apply` action graph for the selected provider.
- [ ] The graph applies the expected saved `tofuplan` artifact for the validated provider directory.
- [ ] Missing or stale saved plan behavior matches current workflow: regenerate plan and retry apply.
- [ ] Non-stale apply failures fail fast and do not run SSH alias reconciliation.
- [ ] Successful apply resolves the public IPv4 output and reconciles the repo SSH alias.
- [ ] Command construction uses argv and validated provider paths.
- [ ] Migrated `just apply` delegates to the Python entrypoint where feasible while preserving compatible exit behavior.
- [ ] Behavioral tests cover success, stale/missing plan retry, non-stale failure, alias-on-success-only, provider override, action ordering, fail-fast behavior, and Just shim parity.
- [ ] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/03-init-upgrade-and-plan-command-coverage-with-saved-plan-artifact.md
