# Wire Maintenance and Monitoring panels

Status: completed

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Wire the Maintenance and Monitoring panels according to the accepted panel taxonomy. Maintenance owns state-changing post-deploy lifecycle actions, including destroy/down. Monitoring owns read-only logs, hardening audit views, and on-demand health checks.

## Acceptance criteria

- [x] Destroy/down appears in Maintenance, not Deployment.
- [x] Destroy/down uses existing destructive preview and confirmation/audit gates.
- [x] Read-only logs appear under Monitoring.
- [x] Hardening audit appears under Monitoring when it remains read-only.
- [x] HealthProbe results render severity, summary, evidence, observed time, runner mode, optional remediation hint, and redacted source command.
- [x] State-changing composites that include read-only output are owned by Maintenance.
- [x] Tests cover panel ownership boundaries and destructive/read-only behavior.

## Blocked by

- 03-operator-snapshot-dashboard-skeleton.md
- 06-deployment-panel-aggregate-and-advanced-progress.md
