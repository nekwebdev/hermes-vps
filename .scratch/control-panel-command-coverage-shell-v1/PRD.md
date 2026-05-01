# PRD: Python Control Panel Command Coverage and Panel Shell v1

Status: needs-triage

## Problem Statement

The hermes-vps operator still depends on a Justfile-centric operational interface for the core VPS lifecycle even though the control panel scaffold and DAG action engine now exist. This creates a split-brain workflow: configuration is moving toward a reusable Python control panel, while provisioning, bootstrap, verification, and destructive teardown remain shell recipes with duplicated preflight, confirmation, runner, and secret-safety logic.

The next step is to turn the scaffold into real, runner-backed command coverage for the operational workflows without over-expanding scope. The operator needs one coherent control panel shell that can host the existing config wizard, bootstrap/deploy workflows, state-changing maintenance actions, and small on-demand monitoring checks, while preserving the Justfile as a compatibility shim until command coverage parity and documentation cutover are complete.

## Solution

Build a vertical slice of the Python control panel that covers the existing operational workflows represented by the current Just recipes:

- init
- init-upgrade
- plan
- apply
- destroy
- bootstrap
- verify

The solution should add concrete repo-specific action adapters that execute through the locked runner and shared static DAG action engine. It should introduce a multi-panel app shell, or equivalent navigation model, that can host the current config flow plus operational panels:

- config panel: existing configuration wizard integration point.
- bootstrap/deploy panel: guided provisioning and bootstrap workflows.
- maintenance panel: state-changing operator workflows already represented by existing recipes.
- monitoring panel: small on-demand read-only local readiness/status checks where cheap and useful.

The Justfile remains during this PRD as a compatibility shim. Where feasible, migrated recipes should delegate to Python app entrypoints rather than duplicate orchestration. Final Justfile removal is explicitly a later human-in-the-loop cutover decision after full parity and docs migration.

TUI, headless, and CI flows must share action graph definitions so behavior does not diverge by interface. The implementation should avoid broad API freeze work, dynamic runtime graph expansion, background monitoring, or comprehensive health probes.

## User Stories

1. As an operator, I want to run init from the Python control panel, so that OpenTofu initialization uses the same runner, preflight, and status model as other panel actions.
2. As an operator, I want to run init-upgrade from the Python control panel, so that provider/plugin refresh remains available without dropping to raw Just recipes.
3. As an operator, I want to run plan from the Python control panel, so that infrastructure changes can be previewed from the new operational surface.
4. As an operator, I want the plan action to save the expected tofuplan artifact, so that apply can consume the same workflow artifact as today.
5. As an operator, I want to run apply from the Python control panel, so that provisioning can move into the DAG execution model.
6. As an operator, I want apply to handle missing or stale saved plans consistently with current behavior, so that migration does not regress the existing workflow.
7. As an operator, I want apply to update the SSH alias after a successful provision when applicable, so that existing connection convenience remains intact.
8. As an operator, I want to run bootstrap from the Python control panel, so that post-provision host configuration is part of the same guided operational flow.
9. As an operator, I want bootstrap to validate SSH key path, permissions, provider outputs, and required Hermes/Telegram values before remote execution, so that failures are early and actionable.
10. As an operator, I want bootstrap runtime secret material to stay ephemeral, so that raw secrets are not persisted in framework state or logs by default.
11. As an operator, I want remote bootstrap staging and cleanup to remain deterministic, so that reruns are idempotent and safe.
12. As an operator, I want to run verify from the Python control panel, so that post-bootstrap validation is available from the same panel shell.
13. As an operator, I want verify failures to surface structured action status and repair scope, so that I know whether to rerun a failed node, failed subtree, or full panel.
14. As an operator, I want destroy in the Python control panel to show the exact destructive scope, so that I can see provider, OpenTofu directory, local state backup behavior, and target resource context before approving.
15. As an operator, I want destroy to require explicit confirmation in interactive mode, so that accidental infrastructure teardown is blocked.
16. As an operator, I want non-interactive destroy to require an explicit approval flag and emit audit metadata, so that CI/headless use is possible but never implicit.
17. As an operator, I want local state backup behavior to be preserved before destroy, so that migration does not weaken recovery posture.
18. As an operator, I want provider selection to continue defaulting from the environment with explicit per-command overrides, so that existing workflow muscle memory still works.
19. As an operator, I want invalid provider overrides to fail before any side effect, so that commands cannot run against an ambiguous provider.
20. As an operator, I want missing or unsafe environment files to fail before operational actions, so that state-changing work does not start from a bad repo state.
21. As an operator, I want a multi-panel shell that clearly separates config, bootstrap/deploy, maintenance, and monitoring, so that I can find the right workflow quickly.
22. As an operator, I want the existing configuration wizard to remain available inside or alongside the new shell, so that configuration is not blocked by operational migration.
23. As an operator, I want a bootstrap/deploy flow that can run init, plan, apply, bootstrap, and verify as one ordered graph, so that first deploy becomes guided and repeatable.
24. As an operator, I want maintenance actions to be labeled as state-changing, so that I can distinguish them from monitoring checks.
25. As an operator, I want monitoring actions to be read-only and on-demand only, so that the control panel does not introduce a background daemon.
26. As an operator, I want small local readiness/status checks in monitoring v1 if they fit the slice, so that I can inspect repo/toolchain/environment readiness without side effects.
27. As an operator, I want remote VPS health probes deferred if they make the slice too large, so that command coverage lands first.
28. As a CLI user, I want migrated Just recipes to keep working, so that existing scripts and habits do not break during transition.
29. As a CLI user, I want Just shim output and exit behavior to remain close to today for migrated commands, so that automation does not get surprising results.
30. As a CI user, I want headless command entrypoints for the same action graphs used by the TUI, so that tests and automation exercise the same behavior.
31. As a maintainer, I want operational workflows expressed as static DAGs with small conditionals only, so that execution order is testable and predictable.
32. As a maintainer, I want command construction represented as argv lists by default, so that shell injection risk stays low.
33. As a maintainer, I want shell-string execution to require explicit opt-in, so that unsafe command construction is visible in code review.
34. As a maintainer, I want runner detection to happen once per launch and then lock, so that a session cannot silently switch execution environments mid-flow.
35. As a maintainer, I want HostRunner override to remain disabled by default, so that portability and isolation policy stay enforced.
36. As a maintainer, I want HostRunner override to require a reason and escalation token before engine execution, so that bypasses are intentional and auditable.
37. As a maintainer, I want denied host override attempts not to echo token values, so that logs do not leak escalation input.
38. As a maintainer, I want operational adapters to return structured summaries and bounded output tails, so that UI and CI can render useful results without storing unbounded logs.
39. As a maintainer, I want raw secrets redacted from run results, events, audit records, and error messages, so that framework state remains safe by default.
40. As a maintainer, I want timeout intent declared per action, so that hung infrastructure or SSH commands fail deterministically.
41. As a maintainer, I want fail-fast behavior on critical path failures, so that dependent operational actions do not continue after unsafe prerequisites fail.
42. As a maintainer, I want optional read-only checks to be allowed to fail without blocking state-changing workflows only when explicitly marked optional, so that failures have clear policy.
43. As a maintainer, I want action graph ordering covered by tests, so that deploy and destroy sequences do not drift from intended order.
44. As a maintainer, I want migrated command parity tests against Just shim behavior, so that compatibility remains measurable during staged cutover.
45. As a maintainer, I want public interfaces/action graphs tested rather than private helper internals, so that refactors remain possible.
46. As a release owner, I want final Justfile cutover/removal to be a separate HITL checkpoint, so that compatibility is not removed before documentation and parity are accepted.
47. As a release owner, I want destructive operation UX reviewed before implementation is considered complete, so that the control panel cannot hide teardown risk.
48. As a future contributor, I want package boundaries to remain clear between framework core and repo-specific adapters, so that hermes_control_core stays reusable.
49. As a future contributor, I want plugin API freeze deferred, so that command coverage can iterate without pretending the framework API is stable.
50. As a future monitoring implementer, I want any monitoring v1 additions to align with the HealthProbe vocabulary, so that later probe work has a compatible path.

## Implementation Decisions

- Keep the package split intact:
  - hermes_control_core owns reusable action engine, runner, audit, side-effect, panel-shell, confirmation, and result primitives.
  - hermes_vps_app owns hermes-vps operational graphs, adapters, provider/OpenTofu path resolution, SSH/bootstrap orchestration, and repo-specific presentation assets.
- Add concrete runner-backed action adapters for current operational lifecycle commands instead of calling Just as the primary implementation path.
- Use the existing runner contract as the execution boundary: canonical command form is argv list; shell-string execution is exceptional and must be explicit.
- Preserve runner detection order exactly: direnv-attached flake shell, nix develop, Dockerized nix fallback, then HostRunner only by audited override.
- Detect and lock the runner once per app launch. All panels and graphs in that launch reuse the same runner selection.
- Keep HostRunner override enforcement centralized at engine preflight and not delegated to individual actions.
- Keep host override approval token separate from destructive-action confirmation. Host override applies to every engine run using host mode; destructive confirmation applies to destructive nodes.
- Define a small command model for operational action inputs: provider selection, provider override, confirmation/approval metadata, plan path, target scope, and non-secret execution options.
- Provider resolution must preserve current semantics: default from TF_VAR_cloud_provider, optional per-command override, allowed providers limited to current supported set.
- Preflight graph nodes should validate environment presence, file permissions, provider directory existence, runner availability, and required per-command inputs before side effects.
- Implement an InfraPlanner adapter over the runner for OpenTofu actions: init, init-upgrade, plan, apply, destroy, show plan where needed, and stale/missing plan detection where feasible.
- Treat OpenTofu as the source of truth for infrastructure changes. Provider plan previews remain advisory and are not part of command coverage parity.
- Implement a RemoteExecutor adapter over the runner for SSH/rsync/bootstrap/verify behavior needed by bootstrap and verify workflows.
- Preserve existing bootstrap validations: SSH key path expansion, readability, restrictive mode, server output lookup, admin user lookup, required Hermes/Telegram values, allowed port syntax, pinned Hermes version shape, and allowlist shape.
- Preserve bootstrap secret handling through secret handles or execution-boundary materialization. Framework state, graph results, action events, and logs must not contain raw provider tokens, Hermes API keys, Telegram bot tokens, OAuth artifacts, or generated runtime env contents.
- Preserve local runtime cleanup semantics for bootstrap secret staging, including best-effort secure deletion where available.
- Preserve apply behavior that regenerates and retries when a saved plan is missing or stale, but express this as a static graph with a small conditional branch rather than dynamic graph expansion.
- Preserve apply SSH alias reconciliation after successful infrastructure apply, with tests ensuring it does not run after failed apply.
- Preserve destroy state backup behavior before destructive teardown when local state files exist. The backup path and mode should be included in the action summary without exposing secret data.
- Destructive preview for destroy must show exact scope before confirmation: provider, OpenTofu provider directory, state backup root, and any known resource/server identifiers available from safe plan/show/output calls.
- Interactive destructive confirmation must require a specific confirmation token or equivalent explicit UX action after previewing scope.
- Non-interactive destructive confirmation must require an explicit approval flag and must record audit metadata.
- Introduce a panel shell/navigation model that can host config, bootstrap/deploy, maintenance, and monitoring surfaces without rewriting the full existing config wizard internals.
- Existing config flow integration can be shallow in this PRD: launch or embed the existing flow from the shell, while future PRDs can consolidate internals if needed.
- Define bootstrap/deploy graph as the first compound operational graph: init -> plan -> apply -> bootstrap -> verify, with critical-path fail-fast.
- Define maintenance v1 scope as state-changing actions already represented by current recipes: init-upgrade, apply, destroy, bootstrap, and any deploy/up aliases that can be expressed as graph compositions.
- Define monitoring v1 scope only for small on-demand read-only checks that fit the slice: runner/toolchain readiness, env/template presence and mode, provider selection resolution, provider directory existence, saved plan presence/staleness summary if non-mutating, and local command availability. Remote VPS health probes are a follow-up unless implementation remains small.
- Keep HealthProbe result vocabulary in mind for monitoring outputs, but do not require full remote health probe implementation in this PRD.
- Keep Justfile as a shim. Migrated recipes may delegate to Python app entrypoints through the existing toolchain wrapper where feasible.
- Keep Justfile removal out of scope. Add explicit notes or TODOs for final cutover only after parity and docs migration.
- CLI/headless entrypoints should expose the same command graphs used by TUI panels so CI can run and assert behavior without Textual.
- Public execution surfaces should return structured action results with statuses, summaries, runner mode, bounded stdout/stderr tails where appropriate, and redaction markers.
- Error taxonomy should distinguish preflight failures, runner unavailable, command not found, command failed, timeout, destructive confirmation denied, host override denied, and redaction failure.
- Do not freeze a stable plugin API as part of this PRD; keep framework/app contracts provisional and concrete enough for vertical slices.

## Testing Decisions

- Use TDD vertical slices: write failing behavioral tests for one command graph or panel entrypoint, implement the minimum adapter/shell behavior, then refactor.
- Good tests should exercise public interfaces, action graphs, app/headless entrypoints, and observable summaries rather than private helper implementation.
- Test runner command construction and safety:
  - commands use argv lists by default,
  - shell strings require explicit opt-in,
  - provider paths and plan paths are constructed from validated provider inputs,
  - environment overlays redact values in logs/results.
- Test runner selection/lock behavior through public factory/session behavior:
  - detection order is preserved,
  - selected runner is reused for the launch,
  - Docker fallback missing prerequisites fail before panel execution,
  - HostRunner override remains denied without explicit enablement, reason, and escalation token.
- Test operational graph behavior:
  - init graph constructs the expected OpenTofu init command,
  - init-upgrade graph adds upgrade semantics,
  - plan graph writes the expected plan artifact path,
  - apply graph regenerates/retries on missing/stale plan and fails fast on other apply failures,
  - bootstrap graph orders output lookup, validation, staging, remote execution, and cleanup,
  - verify graph executes remote verification only after target resolution succeeds,
  - destroy graph backs up local state before teardown and requires confirmation.
- Test action graph ordering and fail-fast behavior with fake runners/adapters, not real cloud providers.
- Test destructive confirmation gates:
  - interactive destroy without confirmation is denied,
  - non-interactive destroy without approval flag is denied,
  - approved destroy records audit metadata,
  - preview includes exact non-secret target scope.
- Test Just shim parity for migrated commands:
  - existing recipe names remain callable,
  - provider override forms remain accepted or fail with compatible messages,
  - migrated shim delegates to Python entrypoints where feasible,
  - exit status behavior remains compatible for success and preflight failures.
- Test no raw secrets in logs/results:
  - provider tokens,
  - Hermes API key,
  - Telegram bot token,
  - OAuth auth artifact contents,
  - generated runtime env values,
  - host override denial token values.
- Test panel shell behavior:
  - config flow is reachable,
  - bootstrap/deploy flow exposes ordered graph actions,
  - maintenance actions are visibly state-changing,
  - monitoring actions are read-only and on-demand only,
  - TUI/headless/CI entrypoints select the same graph definitions.
- Test monitoring v1 only if included:
  - local readiness/status checks are side_effect_level=none,
  - results use structured severity/readiness output,
  - remote VPS probes are absent or explicitly marked follow-up.
- Prior art includes existing control-core engine smoke tests, cloud remediation tests, configure services tests, and configure TUI behavioral tests.
- All changed Python should pass via the toolchain wrapper:
  - python3 -m pytest ...
  - python3 -m ruff check ...
  - basedpyright ...

## Out of Scope

- Full stable plugin API freeze.
- Removing the Justfile.
- Final Justfile cutover or documentation cutover.
- Background monitoring daemon or scheduled collector.
- Broad new provider support beyond current provider workflows.
- Rewriting all existing config wizard internals unless minimal integration requires it.
- Complex dynamic runtime graph expansion.
- Implementing every maintenance or monitoring probe in one pass.
- Remote VPS HealthProbe suite if it makes the command coverage slice too large.
- Gateway/session-routing work unless strictly required by existing bootstrap or verify parity.
- Replacing OpenTofu as the infrastructure source of truth.
- Changing the local-state strategy.
- Persisting raw secret material in framework state/logs by default.

## Further Notes

- This PRD follows the local Markdown issue tracker convention: one feature directory with this PRD at the root and future implementation issues under an issues directory.
- This PRD uses project glossary terms: control panel, framework core, standard panels, panel taxonomy, maintenance, monitoring, monitoring v1, HealthProbe, InfraPlanner, RemoteExecutor, GatewayManager, panel execution model, DAG node contract, runner policy, host override policy, secrets policy, destructive-action gate, destructive preview contract, shim policy, and removal criteria.
- HITL checkpoint: destructive operation UX must be reviewed before destroy is considered migrated. The review should confirm preview scope, confirmation wording/token, non-interactive approval flag, and audit output.
- HITL checkpoint: final Justfile cutover/removal must not happen in this PRD. It requires separate approval after command coverage parity, shim behavior, and documentation cutover are complete.
- HITL checkpoint: if monitoring scope starts pulling in real remote VPS health probes, split remote probes into a follow-up PRD and keep this PRD focused on command coverage and shell integration.
- Follow-up to-issues run should create vertical slices around command graph foundations, individual command adapters, shell navigation, Just shim parity, destructive safety, secret redaction, and test/CI coverage.
