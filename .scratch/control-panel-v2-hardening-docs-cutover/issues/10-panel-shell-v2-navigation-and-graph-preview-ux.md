# Panel shell v2 navigation and graph preview UX

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Polish the control panel shell around the standard panel taxonomy. Config, maintenance, monitoring, and deploy/bootstrap flows should be easier to navigate, state-changing workflows should show graph previews, and monitoring v1 must remain read-only/on-demand.

## Acceptance criteria

- [x] Panel shell navigation clearly separates config, maintenance, monitoring, and deploy/bootstrap flows using glossary vocabulary.
- [x] Maintenance and deploy/bootstrap actions are visibly marked as state-changing where appropriate.
- [x] Monitoring v1 remains read-only, side_effect_level=none, and on-demand only; no daemon or remote probe suite is introduced.
- [x] State-changing panel flows show graph preview before execution using the shared preview renderer.
- [x] Panel status uses the shared presentation model for covered workflows.
- [x] Behavior-first panel tests cover navigation, preview, state-changing/read-only labels, and monitoring v1 constraints.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/01-shared-status-presentation-spine-for-init-and-monitoring.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/03-graph-preview-and-repair-scope-rendering-for-state-changing-workflows.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/06-runner-diagnostics-lock-visibility-and-docker-fallback-preflight.md
