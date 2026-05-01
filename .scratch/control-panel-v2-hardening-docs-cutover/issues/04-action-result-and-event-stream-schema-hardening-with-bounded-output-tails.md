# Action result and event stream schema hardening with bounded output tails

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Harden action result and action event payloads into stable-enough internal contracts used by graph execution, CLI JSON output, panel shell presentation, and tests. Command-backed actions must retain only bounded output tails and expose redaction markers.

## Acceptance criteria

- [ ] Action result summaries use a documented internal schema for command-backed actions, preflight actions, monitoring checks, and graph-level results.
- [ ] Action events have consistent fields for action identity, status, timestamp, message, non-secret details, runner mode when known, and redaction markers.
- [ ] Command output retained in results/events is bounded and marked when truncated.
- [ ] Human and JSON renderers consume the hardened schemas rather than action-specific ad hoc dict shapes.
- [ ] Fake-runner tests cover successful output, failed output, truncated output, and event stream rendering without live infrastructure.
- [ ] No raw secret material is introduced into the new schemas.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/01-shared-status-presentation-spine-for-init-and-monitoring.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/02-deterministic-exit-codes-and-error-taxonomy-for-headless-commands.md
