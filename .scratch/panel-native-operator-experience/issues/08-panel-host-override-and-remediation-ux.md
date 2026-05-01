# Add host override and blocking remediation UX

Status: completed

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Complete the panel UX for blocking startup remediation and advanced host override. The normal path should guide operators toward hermetic runner fixes; host override is available only as an explicit unsafe session-only escape hatch.

## Acceptance criteria

- [x] Blocking startup remediation screens show exact local fix guidance for unsafe `.env`, invalid provider, missing provider directory, and unavailable runner.
- [x] Docker fallback unavailable state shows guided install/remediation and prevents panel execution.
- [x] Host override is hidden behind an advanced unsafe-environment path.
- [x] Host override requires explicit enablement and non-empty reason.
- [x] Any host override run still requires the central pre-run escalation token.
- [x] Dashboard/footer visibly warns when `runner=host` is active.
- [x] Host override state is per-launch only and never persisted.
- [x] Tests cover denied/approved host override UX without token leakage.

## Blocked by

- 01-panel-entrypoint-and-startup-gate.md
- 03-operator-snapshot-dashboard-skeleton.md
