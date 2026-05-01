# Panel-Native Operator Experience PRD

Status: completed

## Problem Statement

The repo currently has useful Just recipes and a standalone configure TUI, but the operator experience is split. Operators need one coherent Textual control panel for first-run configuration, reconfiguration, deployment, maintenance, and monitoring, while keeping Just recipes as convenient wrappers. The existing configure TUI has valuable behavior, but its old module and screen structure should not constrain the fresh panel-native rewrite.

## Solution

Build a single Textual control panel app launched by the canonical `just panel` operator panel entrypoint. Keep `just configure` as a shortcut/deep link into the same app's Configuration panel. The app starts with a visible startup gate, locks the runner for the session, validates local `.env` structure, shows blocking remediation for unsafe local state, and opens either a configuration-required screen or an operator dashboard. The dashboard uses a non-secret operator snapshot to recommend the primary next action and expose Configuration, Deployment, Maintenance, and Monitoring panels.

The Configuration panel becomes a fresh panel-native rewrite backed by typed app-owned config drafts mapped to/from `.env`. Deployment exposes an aggregate deploy workflow plus advanced individual steps. Maintenance owns destructive lifecycle management, including destroy/down. Monitoring owns read-only logs, hardening audit views, and health probes.

## User Stories

1. As an operator, I want `just panel` to open the control panel, so that I have one obvious starting point for operating the repo.
2. As an operator, I want `just configure` to open the same app directly in configuration mode, so that my existing muscle memory remains useful without creating a second app.
3. As a first-time operator, I want missing `.env` to show a configuration-required screen inside the panel shell, so that I understand configuration is part of the control panel.
4. As an operator with existing config, I want startup to show visible validation progress, so that I know what the panel is checking before it opens.
5. As an operator, I want unsafe `.env` permissions to block the dashboard with exact remediation, so that secrets are not handled under unsafe local conditions.
6. As an operator, I want provider tokens and remote health problems to appear as warnings or action-specific remediation, so that the panel does not block on network/auth checks before I choose an action.
7. As an operator, I want the runner mode selected and locked at startup, so that all panel actions share the same execution environment.
8. As an advanced operator, I want host override only as an explicit unsafe remediation path, so that normal operation remains hermetic and safe.
9. As an operator, I want a dashboard with environment summary, primary next action, panel cards, recent non-secret status, and runner/host safety footer, so that I know what to do next.
10. As an operator, I want the dashboard primary action to use cheap local state by default, so that startup remains fast and remote checks are deliberate.
11. As an operator, I want Configuration, Deployment, Maintenance, and Monitoring as top-level panels, so that tasks are grouped by operator intent rather than implementation detail.
12. As an operator, I want first-run configuration as a guided wizard, so that I can create `.env` without knowing every field up front.
13. As an operator, I want reconfiguration as targeted section edits, so that I can change one area without walking the whole wizard.
14. As an operator, I want existing secrets to default to keep-existing, so that I do not accidentally erase or replace working credentials.
15. As an operator, I want a redacted diff before `.env` writes, so that I can verify what changes without leaking secrets.
16. As an operator, I want provider changes to force dependent region/type review, so that stale cloud choices are never persisted.
17. As an operator, I want stale async validation results ignored, so that slow background checks cannot overwrite newer input.
18. As an operator, I want live cloud lookup failures to show typed provider-specific remediation, so that I know whether the binary, token, scope, or metadata access is the problem.
19. As an operator, I want Deployment to offer one primary Deploy workflow, so that normal provisioning is one guided action.
20. As an advanced operator, I want individual init/plan/apply/bootstrap/verify actions, so that I can run surgical deployment steps.
21. As an operator, I want destructive destroy/down separated into Maintenance with explicit previews/gates, so that deploy workflows never destroy resources by surprise.
22. As an operator, I want Monitoring to contain read-only logs, hardening audit, and health checks, so that observability is clearly separate from state changes.
23. As an operator, I want action progress shown as structured graph/node status with expandable redacted output, so that I get confidence without log noise.
24. As an operator, I want failures to show the failed node and repair/rerun scope, so that recovery is targeted.
25. As a maintainer, I want panel actions to call Python services/action graphs directly, so that the UI does not parse Just output or duplicate shell behavior.
26. As a maintainer, I want typed config drafts and env mappers in `hermes_vps_app`, so that `.env` remains persistence format rather than widget state.
27. As a maintainer, I want Textual used idiomatically while services own effects and gates, so that the app is elegant without leaking business rules into widgets.
28. As a maintainer, I want old configure code deleted only after tests, manual validation, same-app routing checks, and explicit HITL approval, so that we keep a safety net until parity is proven.

## Implementation Decisions

- `just panel` is the canonical operator panel entrypoint.
- `just configure` is a deep link into the same panel app's Configuration panel/subflow.
- There is one user-facing Textual app; the old standalone configure TUI is source material only during the rewrite.
- Textual is locked in as the UI framework.
- Textual owns screen routing, widget state/focus, async worker lifecycle/correlation, progress rendering, view composition, and direct service calls.
- Application services own `.env` parsing/writing, provider auth classification, command construction, secret redaction, DAG semantics, destructive gates, and typed remediation.
- Panel actions call `hermes_vps_app` services/action graphs directly; the panel never shells out to Just recipes.
- Startup performs runner detection/lock and local structural validation with visible progress.
- Startup blockers are local structural/safety problems: unreadable or overly broad `.env`, missing/invalid provider, missing provider directory, and unavailable locked runner.
- Startup warnings are non-structural or remote/live problems: missing/invalid tokens, unavailable cloud metadata, unreachable remote host, stale/missing OpenTofu outputs, and Hermes/Telegram validation failures.
- Top-level panels are Configuration, Deployment, Maintenance, and Monitoring.
- Deployment primary workflow is aggregate init -> plan -> apply -> bootstrap -> verify, with advanced individual steps.
- Maintenance owns destroy/down as separately gated destructive lifecycle management.
- Monitoring owns read-only logs, hardening audit views, and on-demand health probes.
- Configuration uses app-owned typed config drafts mapped to/from `.env`; env keys are persistence format, not widget state.
- Existing secrets default to keep-existing unless the operator explicitly chooses replacement.
- The configuration rewrite preserves validated operator behavior but does not preserve old module/screen boundaries.

## Testing Decisions

- Prefer service tests for deep modules: config mapping, redacted diffs, atomic writes, startup gate classification, operator snapshot rules, and remediation classification.
- Add focused Textual app tests for routing, deep links, startup progress/remediation, config-required screen, stale async validation, and progress rendering.
- Add thin Just/CLI tests to verify `just panel` and `just configure` route to the same app with different initial targets.
- Reuse existing config, async, cloud remediation, panel shell, runner, and monitoring test patterns where applicable.
- Test external behavior and contracts rather than CSS/layout details.
- Avoid brittle screenshot goldens.

## Out of Scope

- Removing the Justfile entirely.
- Freezing a stable public plugin API.
- Adding a background monitoring collector daemon.
- Moving VPS-specific config types into `hermes_control_core`.
- Replacing Textual or designing a web UI.
- Editing `.env.example` unless explicitly requested by a separate template-sync task.
- Deleting old configure code before the operator validation gate.

## Further Notes

This PRD implements ADR-0003: Panel-Native Operator Experience and Textual Integration. It also respects ADR-0001's core/app split and execution model, and ADR-0002's strict live cloud lookup and typed remediation behavior. Issues are intentionally vertical slices in dependency order so each can be picked up independently.
