# Panel shell v1 hosts config flow and first operational command

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Add a minimal multi-panel control panel shell, or equivalent navigation model, that hosts the existing config flow and exposes the migrated `init` operational command using the same action graph as the headless path. The slice should prove that TUI and headless execution can share graph definitions without rewriting the full config wizard internals.

## Acceptance criteria

- [x] A control panel shell presents separate navigation for config and operational workflows.
- [x] The existing config wizard remains reachable from the shell, either embedded or launched shallowly.
- [x] The `init` command can be launched or previewed from the operational panel using the same graph definition as the headless entrypoint.
- [x] Maintenance/state-changing actions are visually distinguished from read-only surfaces in shell vocabulary.
- [x] The shell displays structured action status from the engine rather than duplicating execution logic in UI code.
- [x] Tests verify config flow reachability, `init` graph reachability, and shared graph identity between shell/headless paths.
- [x] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/01-init-command-tracer-bullet-through-headless-app-runner-graph-and-just-shim.md
