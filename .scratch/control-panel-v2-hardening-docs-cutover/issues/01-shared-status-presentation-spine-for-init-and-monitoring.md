# Shared status presentation spine for init and monitoring

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Build the first reusable vertical path for control-panel v2 status rendering. Init and monitoring should both render through the same internal presentation model across headless CLI human output, structured JSON output, panel shell status, and behavior-first tests. This establishes the shared spine for later migrated workflows without freezing a public plugin API.

## Acceptance criteria

- [ ] Init and monitoring can be rendered through one shared internal presentation model rather than separate ad hoc formatters.
- [ ] Headless CLI exposes human-readable output and structured JSON output for the covered workflows.
- [ ] Panel shell status consumes the same presentation model for the covered workflows.
- [ ] JSON output includes graph identity, action identity/status, runner mode when known, repair scope when present, and redaction marker fields.
- [ ] Behavior-first tests use fake runners or fake status payloads and exercise public CLI/panel-facing interfaces.
- [ ] No public third-party plugin API is declared or frozen as part of this slice.

## Blocked by

None - can start immediately
