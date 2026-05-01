# Cross-surface migrated-command regression gate

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Add the final PRD-level regression gate that proves migrated command coverage behaves consistently across public action graphs, headless entrypoints, panel shell wiring, and Just shims. This issue does not add new product workflows; it hardens parity, safety, and test coverage after the command slices land.

## Acceptance criteria

- [ ] Regression tests exercise all migrated command graphs through public interfaces with fake runners/adapters where possible.
- [ ] Tests verify TUI/shell, headless, CI-facing, and Just shim paths select the same graph definitions for migrated workflows.
- [ ] Tests verify graph ordering and fail-fast behavior for individual and compound workflows.
- [ ] Tests verify destructive confirmation gates and audit metadata for destroy.
- [ ] Tests verify HostRunner override remains denied by default and approved only with explicit enablement, non-empty reason, and escalation token.
- [ ] Tests verify denied host override attempts do not echo provided token values.
- [ ] Tests verify no raw provider tokens, Hermes API keys, Telegram bot tokens, OAuth artifact contents, generated runtime env values, or host override denial token values appear in logs/results/events/audit output.
- [ ] Tests verify Just shim parity for migrated recipe names, provider override behavior, and exit status behavior.
- [ ] The suite is documented as the precondition for future docs cutover and eventual Justfile removal, without removing the Justfile in this PRD.
- [ ] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/08-destroy-command-coverage-with-preview-confirmation-gate-and-state-backup.md
- .scratch/control-panel-command-coverage-shell-v1/issues/09-deploy-up-compound-graph-and-shell-integration.md
- .scratch/control-panel-command-coverage-shell-v1/issues/10-monitoring-v1-local-readiness-panel-with-on-demand-read-only-checks.md
