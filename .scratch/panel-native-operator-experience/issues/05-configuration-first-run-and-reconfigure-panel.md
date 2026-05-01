# Build panel-native Configuration first-run and reconfigure flows

Status: completed

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Build the Configuration panel experience on top of the typed config model. Missing `.env` uses a guided first-run wizard. Existing `.env` uses section-based targeted reconfiguration with review/diff before atomic write.

## Acceptance criteria

- [x] Missing `.env` shows a configuration-required screen inside the panel shell.
- [x] First-run flow covers Cloud, Server, Hermes, Telegram, and Review/Apply.
- [x] Existing `.env` opens section-based reconfigure mode rather than forcing the full wizard.
- [x] Cloud sample mode and live lookup mode are both supported.
- [x] Live lookup failures use typed provider-specific remediation.
- [x] Hermes OAuth/API-key distinction is preserved.
- [x] Telegram validation is explicit and stale-safe.
- [x] Stale or failed async validation results cannot be persisted.
- [x] Review shows a redacted diff before write.
- [x] Focused Textual/panel tests cover first-run, reconfigure, and stale async behavior.

## Blocked by

- 02-configure-deep-link-same-panel-app.md
- 04-configuration-model-env-mapper-and-redacted-diff.md
