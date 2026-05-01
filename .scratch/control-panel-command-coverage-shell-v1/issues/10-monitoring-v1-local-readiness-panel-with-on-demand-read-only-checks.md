# Monitoring v1 local readiness panel with on-demand read-only checks

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Add the first monitoring v1 slice: an on-demand, read-only local readiness panel and headless graph. This should cover small local checks only and explicitly defer remote VPS health probes unless a later PRD includes them.

## Acceptance criteria

- [x] A monitoring panel is reachable from the control panel shell and is labeled as read-only observability.
- [x] A public headless Python entrypoint can run the same local readiness graph used by the monitoring panel.
- [x] All monitoring v1 actions in this slice use `side_effect_level=none` and are on-demand only.
- [x] Checks include local runner/toolchain readiness, `.env`/`.env.example` presence and mode, provider selection resolution, provider directory existence, relevant local command availability, and optional saved plan presence/staleness summary if implemented non-mutatingly.
- [x] Results use structured readiness/severity vocabulary compatible with future HealthProbe-style output.
- [x] Remote VPS health probes are absent, disabled, or explicitly marked as follow-up in UI/headless output.
- [x] Tests verify read-only side-effect metadata, shell/headless graph alignment, structured output, and no remote execution.
- [x] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/02-panel-shell-v1-hosts-config-flow-and-first-operational-command.md
