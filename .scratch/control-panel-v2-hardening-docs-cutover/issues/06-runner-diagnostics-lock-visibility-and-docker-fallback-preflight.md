# Runner diagnostics, lock visibility, and Docker fallback preflight

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Make runner selection and environment readiness visible and actionable across CLI, panel shell, and audit/session output. Docker fallback prerequisite failures must occur before graph execution, and HostRunner must never be silently selected.

## Acceptance criteria

- [ ] Runner selection diagnostics include selected mode, detection reason, per-launch lock scope, and setup/remediation guidance on failure.
- [ ] CLI and panel shell status show the locked runner mode for the current launch.
- [ ] Runner selection metadata is available to audit/session serialization without secrets.
- [ ] Dockerized nix fallback validates Docker prerequisites before action graph execution starts and returns setup guidance if unusable.
- [ ] Tests prove Docker fallback prerequisite failure does not execute graph actions.
- [ ] Tests prove HostRunner is never selected silently and still requires explicit override policy.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/01-shared-status-presentation-spine-for-init-and-monitoring.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/02-deterministic-exit-codes-and-error-taxonomy-for-headless-commands.md
