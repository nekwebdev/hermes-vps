# Graph preview and repair scope rendering for state-changing workflows

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Generate graph previews from action descriptors and render repair/rerun scopes consistently before and after state-changing workflows. The slice should cover at least one simple state-changing workflow and one compound workflow end-to-end through CLI, panel shell, and tests.

## Acceptance criteria

- [ ] Graph previews are generated from action graph topology and action descriptors, not hand-maintained per-surface lists.
- [ ] Preview output includes graph name, ordered actions, side-effect levels, provider where relevant, runner mode where known, and approval requirements where relevant.
- [ ] Headless CLI can preview covered state-changing workflows without executing graph side effects.
- [ ] Panel shell exposes the same graph preview before covered state-changing workflows.
- [ ] Failure output renders repair/rerun scope consistently as failed node, failed subtree, or full panel where metadata allows.
- [ ] Behavior-first tests prove preview does not call the runner and remains aligned with actual graph definitions.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/01-shared-status-presentation-spine-for-init-and-monitoring.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/02-deterministic-exit-codes-and-error-taxonomy-for-headless-commands.md
