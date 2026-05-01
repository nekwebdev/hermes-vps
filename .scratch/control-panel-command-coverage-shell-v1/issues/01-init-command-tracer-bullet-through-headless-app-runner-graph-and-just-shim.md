# Init command tracer bullet through headless app, runner lock, graph, and Just shim

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Build the first complete migrated operational command path for `init`: provider/env preflight, per-launch runner detection and lock, static action graph execution, headless Python entrypoint, and Just shim delegation. This is the tracer bullet that proves the new control panel command coverage path works end-to-end without moving every command at once.

## Acceptance criteria

- [ ] A public headless Python entrypoint can run the `init` action graph for the selected provider.
- [ ] Provider resolution preserves current semantics: default from `TF_VAR_cloud_provider`, optional valid provider override, invalid provider override fails before side effects.
- [ ] Environment preflight validates `.env` presence/mode and provider directory existence before OpenTofu execution.
- [ ] Runner detection follows the accepted order and locks one runner for the launch.
- [ ] Host runner remains disabled by default and still requires explicit enablement, non-empty reason, and escalation token before engine execution.
- [ ] The OpenTofu init command is constructed as argv, not an implicit shell string.
- [ ] The migrated `just init` path delegates to the Python entrypoint where feasible while keeping compatible exit behavior.
- [ ] Behavioral tests cover success, invalid provider, missing/unsafe `.env`, command construction, runner lock, host override denial, and Just shim parity.
- [ ] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

None - can start immediately
