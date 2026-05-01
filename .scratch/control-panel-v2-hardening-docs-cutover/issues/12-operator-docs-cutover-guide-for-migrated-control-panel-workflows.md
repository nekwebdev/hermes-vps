# Operator docs cutover guide for migrated control-panel workflows

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Publish operator-facing docs for real use after command coverage migration. Docs should cover configuring, planning, applying, bootstrapping, verifying, destroying, deploy/up, monitoring, runner modes, JSON output, audit behavior, and migrating from Just recipes to Python entrypoints.

## Acceptance criteria

- [ ] Operator docs cover configure, init, init-upgrade, plan, apply, bootstrap, verify, destroy, up/deploy, and monitoring workflows.
- [ ] Docs explain Python entrypoints, Just shim compatibility, provider override behavior, JSON output, graph preview, and exit code taxonomy.
- [ ] Docs explain runner modes, runner lock scope, Docker fallback guidance, no silent host fallback, and host override policy.
- [ ] Docs explain destructive destroy approval, preview, backup behavior, and audit metadata using non-secret examples.
- [ ] Docs include migration notes from Just recipes to Python entrypoints and a docs cutover checklist.
- [ ] Docs state that Justfile removal requires a separate HITL issue and is not performed here.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/02-deterministic-exit-codes-and-error-taxonomy-for-headless-commands.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/03-graph-preview-and-repair-scope-rendering-for-state-changing-workflows.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/06-runner-diagnostics-lock-visibility-and-docker-fallback-preflight.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/08-destructive-destroy-ux-and-audit-hardening-v2.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/10-panel-shell-v2-navigation-and-graph-preview-ux.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/11-just-shim-parity-and-duplicated-preflight-reduction.md
