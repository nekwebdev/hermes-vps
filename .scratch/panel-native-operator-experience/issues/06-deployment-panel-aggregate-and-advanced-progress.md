# Wire Deployment panel aggregate and advanced workflows

Status: completed

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Wire the Deployment panel to existing Python action graphs/services directly. Provide a primary aggregate Deploy workflow and advanced individual init/plan/apply/bootstrap/verify actions with structured progress and expandable redacted details.

## Acceptance criteria

- [x] Deployment primary action previews and runs aggregate init -> plan -> apply -> bootstrap -> verify.
- [x] Individual init, plan, apply, bootstrap, and verify actions are available in advanced mode.
- [x] The panel calls `hermes_vps_app` services/action graphs directly and never invokes Just recipes.
- [x] Progress defaults to structured graph/node status with summary and elapsed time.
- [x] Per-node details expose bounded redacted stdout/stderr tails, source command, and remediation hints.
- [x] Failures pin the failed node and show repair/rerun scope.
- [x] Destroy/down is not reachable from Deployment aggregate flow.
- [x] Tests cover progress rendering and direct-service execution boundary.

## Blocked by

- 03-operator-snapshot-dashboard-skeleton.md
