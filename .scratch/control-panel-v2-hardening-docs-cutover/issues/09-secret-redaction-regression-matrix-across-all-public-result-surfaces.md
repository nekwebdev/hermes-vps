# Secret redaction regression matrix across all public result surfaces

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Add the v2 redaction regression matrix across every public result surface that can carry execution data. The matrix should use fake runners and representative secret values to prove graph results, events, audit logs, errors, human output, JSON output, and bounded output tails are safe.

## Acceptance criteria

- [x] Regression fixtures include provider tokens, Hermes API keys, Telegram bot tokens, OAuth artifact-like content, generated runtime env values, destructive bad tokens, and host override bad tokens.
- [x] Tests assert those values are absent from graph results, action events, audit/session serialization, error messages, human output, JSON output, and bounded output tails.
- [x] Redaction markers remain present so operators know redaction was applied.
- [x] Redaction failures are classified through the shared error taxonomy.
- [x] The test suite uses fake runners/adapters and does not require live providers or remote VPS access.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/04-action-result-and-event-stream-schema-hardening-with-bounded-output-tails.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/07-host-override-ux-and-audit-hardening.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/08-destructive-destroy-ux-and-audit-hardening-v2.md
