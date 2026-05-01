# Host override UX and audit hardening

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Polish HostRunner override denial and approval behavior end-to-end. CLI, panel shell status, and audit/session output should make host mode explicit while preserving the central engine preflight gate and token-safe denial semantics.

## Acceptance criteria

- [ ] Host override denial renders through the shared error taxonomy with actionable recovery guidance.
- [ ] Denied host override attempts do not echo provided escalation token values in human output, JSON output, exceptions, events, or audit serialization.
- [ ] Approved host override runs show host mode and non-secret override reason before graph execution.
- [ ] Audit/session output records approved and denied host override attempts using non-secret metadata only.
- [ ] Behavior-first tests cover denied bad token, missing reason, approved override, and host mode display through public surfaces.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/02-deterministic-exit-codes-and-error-taxonomy-for-headless-commands.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/06-runner-diagnostics-lock-visibility-and-docker-fallback-preflight.md
