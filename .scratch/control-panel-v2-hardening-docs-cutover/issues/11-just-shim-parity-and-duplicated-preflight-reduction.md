# Just shim parity and duplicated preflight reduction

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Tighten the Just compatibility shim so migrated recipes stay aligned with Python entrypoints while the Justfile remains in place. Reduce duplicated preflight/provider behavior where practical and cover remaining duplication with parity tests.

## Acceptance criteria

- [ ] Just recipes for migrated workflows continue to work and delegate to Python entrypoints for operational execution.
- [ ] Provider override behavior remains compatible with existing forms while matching Python validation semantics.
- [ ] Just shim output and exit status behavior are covered for success and representative failure paths.
- [ ] Duplicated preflight/provider parsing is reduced where practical, or explicitly documented as compatibility glue when it must remain.
- [ ] Tests verify Just shim, headless CLI, panel shell, and graph definitions stay aligned for migrated workflows.
- [ ] The Justfile is not removed in this issue.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/02-deterministic-exit-codes-and-error-taxonomy-for-headless-commands.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/03-graph-preview-and-repair-scope-rendering-for-state-changing-workflows.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/06-runner-diagnostics-lock-visibility-and-docker-fallback-preflight.md
