# Side-effect and timeout policy gate across operational graphs

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Add graph-level policy validation for operational graphs so each action declares explicit side-effect metadata and timeout intent. The gate should be exercised via public graph construction and regression tests, keeping destructive and high-side-effect actions non-ambiguous.

## Acceptance criteria

- [x] Every action in migrated operational and monitoring graphs declares a side-effect level consistent with the panel taxonomy.
- [x] State-changing command-backed actions declare explicit timeout intent or an explicit documented exception.
- [x] Infinite/no-timeout exceptions are allowed only through an explicit non-destructive opt-in path.
- [x] Destructive actions cannot be built without destructive side-effect metadata and approval policy metadata.
- [x] Graph construction or validation fails fast with actionable messages when side-effect or timeout metadata is missing.
- [x] Public graph tests cover init, plan, apply, bootstrap, verify, destroy, up/deploy, and monitoring metadata policy.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/03-graph-preview-and-repair-scope-rendering-for-state-changing-workflows.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/04-action-result-and-event-stream-schema-hardening-with-bounded-output-tails.md
