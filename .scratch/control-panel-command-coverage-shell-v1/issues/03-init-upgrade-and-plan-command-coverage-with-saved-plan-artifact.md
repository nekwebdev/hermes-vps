# Init-upgrade and plan command coverage with saved plan artifact

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Extend the migrated operational command path to cover `init-upgrade` and `plan`. These commands should use the same provider/env preflight, locked runner, static action graph model, headless entrypoints, and Just shim compatibility established by the `init` tracer bullet.

## Acceptance criteria

- [ ] A public headless Python entrypoint can run `init-upgrade` for the selected provider.
- [ ] A public headless Python entrypoint can run `plan` for the selected provider and save the expected `tofuplan` artifact in the provider directory.
- [ ] `init-upgrade` command construction preserves OpenTofu init upgrade semantics.
- [ ] `plan` command construction uses validated provider paths and argv command form.
- [ ] Provider override and preflight behavior match the `init` path.
- [ ] Migrated `just init-upgrade` and `just plan` delegate to Python entrypoints where feasible while preserving compatible exit behavior.
- [ ] Behavioral tests cover command construction, provider override validation, plan artifact path, fail-fast preflight, and Just shim parity.
- [ ] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/01-init-command-tracer-bullet-through-headless-app-runner-graph-and-just-shim.md
