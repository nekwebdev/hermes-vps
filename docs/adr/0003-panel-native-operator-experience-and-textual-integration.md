# ADR-0003: Panel-Native Operator Experience and Textual Integration

Status: Accepted
Date: 2026-04-30

## Context

The repository already has a solid core/app split and Just recipes can remain useful operator shortcuts, but the operator experience needs a single coherent control panel rather than a standalone configure wizard plus separate command recipes. The existing configure TUI has validated behavior worth preserving, but its old module/screen structure should not constrain the new design.

## Decision

Adopt a panel-native operator experience built as one Textual control panel app.

1. Operator entrypoints
- `just panel` is the canonical operator entrypoint and launches the control panel shell.
- `just configure` remains as an operator shortcut/deep link into the configuration panel/subflow.
- Both entrypoints launch the same panel app; there is no separate user-facing configure TUI app.

2. First-run and dashboard flow
- When `.env` is missing, the panel opens on a configuration-required screen inside the shell.
- The configuration wizard runs as a subflow inside the panel app.
- When `.env` exists and passes local structural validation, the panel opens on a dashboard with environment summary, primary next action, panel cards, recent non-secret status, and runner/host-override safety footer.

3. Panel taxonomy
- The top-level user-facing panels are Configuration, Deployment, Maintenance, and Monitoring.
- Configuration owns first-run and reconfiguration.
- Deployment owns provision/apply/bootstrap/verify workflows.
- Maintenance owns state-changing post-deploy operator workflows.
- Monitoring owns read-only observability, including logs and hardening audit views.
- Bootstrap is a workflow inside Deployment, not a top-level panel name.

4. Execution boundary
- Panel actions call `hermes_vps_app` services and action graphs directly.
- Just recipes remain thin compatibility/operator wrappers around the same Python entrypoints.
- The panel never shells out to Just recipes.

5. Startup gate
- Startup performs runner detection/lock before the main dashboard and renders visible progress for local validation steps.
- Blocking startup failures include unreadable or overly broad `.env`, missing/invalid provider, missing provider directory, and unavailable locked runner.
- Missing/invalid provider tokens, unavailable cloud metadata, unreachable remote host, stale/missing OpenTofu outputs, and Hermes/Telegram validation failures appear as dashboard warnings or action-specific remediation rather than startup blockers.
- Host override is available only as an advanced unsafe-environment remediation path and never persists.

6. Textual integration
- Textual is the locked-in UI framework for the control panel.
- Textual owns screen routing, widget state/focus, async worker lifecycle/correlation, progress rendering, view composition, and direct service calls.
- Application services own `.env` parsing/writing, provider auth classification, command construction, secret redaction, DAG semantics, and destructive gates.
- Boundary purity must not override good integration or code elegance.

7. Configure rewrite
- The new configuration experience is a fresh panel-native rewrite that preserves validated operator behavior without preserving old configure TUI module boundaries/classes/screens.
- The old standalone configure TUI may be used as source material during implementation, but is discarded after the panel-native implementation is complete and operator-validated.

## Consequences

Positive:
- Operators get one coherent TUI app for first-run, reconfiguration, deployment, maintenance, and monitoring.
- Existing Just commands remain useful without driving the UI architecture.
- Textual can be used idiomatically while safety-sensitive logic stays in services and action graphs.
- The configuration rewrite can aim for a cleaner design instead of preserving old seams.

Costs / trade-offs:
- `just panel` becomes a new primary recipe that must be documented and maintained.
- The panel app needs startup-gate and deep-link behavior in addition to normal dashboard navigation.
- Tests must cover Textual routing/integration as well as service-level behavior.
- The old configure implementation cannot simply be wrapped forever; deleting it requires operator validation and regression parity.

## Alternatives Considered

1) Keep `just configure` as standalone configure TUI and add a separate panel later
- Rejected: creates two user-facing apps and splits operator mental model.

2) Make panel actions invoke Just recipes
- Rejected: loses structured status/progress, introduces shell quoting/env drift, and reverses the intended Justfile shim direction.

3) Keep `deploy/bootstrap` as a user-facing panel name
- Rejected: reads like implementation vocabulary. Operators think in Configuration, Deployment, Maintenance, and Monitoring.

4) Treat Textual as provisional and preserve replaceability as a primary design goal
- Rejected: Textual is now locked in. Clean boundaries remain good practice, but not at the expense of integrated, elegant Textual code.
