# Add `just panel` and panel startup gate

Status: completed

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Create the canonical panel entrypoint and the first real startup path for the Textual control panel. `just panel` should launch the panel app, perform visible runner detection/lock and local startup validation, then route to either a dashboard-ready state, a configuration-required state, or a blocking remediation state.

## Acceptance criteria

- [x] `just panel` exists and delegates to a Python panel entrypoint rather than shelling into old configure TUI code.
- [x] The panel startup path visibly reports local validation steps.
- [x] Runner detection is performed once at startup and exposes the locked runner mode to the app.
- [x] Startup classifies missing `.env` as configuration-required, not fatal.
- [x] Startup blocks on unreadable/unsafe `.env`, invalid provider, missing provider directory, or unavailable runner.
- [x] Blocking failures render actionable remediation without leaking secrets.
- [x] Service tests cover startup classification outcomes.
- [x] Thin Just/CLI tests cover `just panel` entrypoint wiring.

## Blocked by

None - can start immediately
