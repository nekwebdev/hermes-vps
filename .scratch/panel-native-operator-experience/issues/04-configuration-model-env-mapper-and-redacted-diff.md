# Add panel-native configuration model and env mapper

Status: completed

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Introduce app-owned typed configuration drafts and `.env` mapping services for the panel-native Configuration flow. The UI should edit typed config drafts, while services own load, validation, redacted diff generation, and atomic write behavior.

## Acceptance criteria

- [x] `hermes_vps_app` owns typed config structures for provider/server/Hermes/gateway configuration.
- [x] Services can load existing `.env` into a typed project config without exposing secret values in display output.
- [x] Services can produce an env patch from a config draft.
- [x] Redacted diffs show operator-meaningful changes without leaking secrets.
- [x] Existing secret values default to keep-existing unless explicitly replaced.
- [x] Provider changes trigger dependent region/type review/reset/validation.
- [x] Atomic `.env` write behavior is preserved.
- [x] Service tests cover mapping, redaction, keep-existing, dependency handling, and atomic write behavior.

## Blocked by

None - can start immediately
