# Deterministic exit codes and error taxonomy for headless commands

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Add a shared error classification and exit-code contract for migrated headless commands. Representative success and failure paths should render consistent human and JSON errors, then the same taxonomy should be reachable by all migrated CLI actions.

## Acceptance criteria

- [x] Headless commands expose documented deterministic exit codes for success, usage/config error, preflight failure, runner unavailable, command failure, command timeout, destructive approval denied, host override denied, output limit exceeded, redaction error, and unexpected internal error.
- [x] Human error output includes the taxonomy category and concise recovery guidance without leaking tokens or secrets.
- [x] JSON error output includes the taxonomy category, exit code, graph/action context when available, and repair/rerun scope when known.
- [x] Representative migrated commands are covered by public CLI tests for success and classified failure behavior.
- [x] All migrated command entrypoints route failures through the shared classifier rather than one-off RuntimeError rendering.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/01-shared-status-presentation-spine-for-init-and-monitoring.md
