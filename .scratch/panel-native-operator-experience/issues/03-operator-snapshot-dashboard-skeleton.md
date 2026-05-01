# Build operator snapshot and dashboard skeleton

Status: completed

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Build the non-secret operator snapshot service and a dashboard skeleton that uses it to show environment summary, primary next action, panel cards, recent non-secret status, and runner/host-override safety footer.

## Acceptance criteria

- [x] Operator snapshot includes `.env` structure, provider selection, runner mode, provider directory status, OpenTofu state/output presence, known bootstrap/verify status, and cheap local health summary.
- [x] Dashboard primary action follows the accepted rules: Configure, Fix configuration, Deploy, Bootstrap/Verify, Monitor/Fix, or Monitor.
- [x] Dashboard startup does not run expensive remote checks automatically.
- [x] Unknown/stale remote status is represented explicitly.
- [x] Panel cards exist for Configuration, Deployment, Maintenance, and Monitoring.
- [x] Service tests cover primary-action selection rules.
- [x] Focused Textual tests cover dashboard routing from startup.

## Blocked by

- 01-panel-entrypoint-and-startup-gate.md
