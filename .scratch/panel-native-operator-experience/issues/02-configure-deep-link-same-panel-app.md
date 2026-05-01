# Route `just configure` into the same panel app

Status: completed

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Convert `just configure` from a standalone configure TUI launcher into a shortcut/deep link that opens the same Textual panel app directly in the Configuration panel or configuration-required subflow.

## Acceptance criteria

- [x] `just configure` launches the same panel app entrypoint used by `just panel`.
- [x] With missing `.env`, `just configure` lands on the configuration-required panel state.
- [x] With valid `.env`, `just configure` lands in the Configuration panel/reconfigure entry state.
- [x] The old standalone configure TUI is not the user-facing process for `just configure`.
- [x] Just/CLI tests verify `just panel` and `just configure` use the same app with different initial targets.

## Validation

- `./scripts/toolchain.sh "python3 -m pytest tests/test_panel_configure_deeplink_issue02.py tests/test_justfile_configure.py -q"`
- `./scripts/toolchain.sh "python3 -m pytest tests/test_panel_startup_issue01.py tests/test_panel_configure_deeplink_issue02.py tests/test_justfile_configure.py -q"`
- `./scripts/toolchain.sh "python3 -m ruff check hermes_vps_app/panel_entrypoint.py hermes_vps_app/panel_shell.py tests/test_panel_configure_deeplink_issue02.py tests/test_justfile_configure.py"`
- `./scripts/toolchain.sh "basedpyright hermes_vps_app/panel_entrypoint.py hermes_vps_app/panel_shell.py tests/test_panel_configure_deeplink_issue02.py tests/test_justfile_configure.py"`

## Blocked by

- 01-panel-entrypoint-and-startup-gate.md
