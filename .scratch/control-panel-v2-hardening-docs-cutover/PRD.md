# PRD: Control Panel v2 Hardening, Docs Cutover, and Operational UX Polish

Status: needs-triage

## Problem Statement

The command coverage migration moved the core hermes-vps lifecycle into the Python control panel, but the implementation is still a provisional v1 cutover surface. Operators now have migrated action graphs for init, init-upgrade, plan, apply, bootstrap, verify, destroy, up/deploy, and monitoring v1, while the Justfile remains as a compatibility shim. This creates the right foundation, but not yet a polished operator-ready control panel.

The current state still risks drift between Just shims, headless CLI behavior, panel shell presentation, operational graph adapters, audit/session output, and documentation. Some contracts exist as typed primitives but are not yet stable-enough internal contracts: action results, runner diagnostics, event streams, error taxonomy rendering, output tail handling, side-effect metadata, repair/rerun scopes, and non-secret audit persistence. The repo also lacks a full documentation cutover path for real operator use after command coverage migration.

The next step is to harden the control panel into a maintainable v2 internal platform without freezing a public third-party plugin API prematurely, while preparing the repo for real operator use and preserving Justfile compatibility until a separate HITL removal decision approves final cutover.

## Solution

Build a v2 hardening pass around the existing framework core and hermes-vps app layer. The solution should keep the accepted control-panel architecture intact: a reusable framework core, repo-specific app adapters, static DAG action graphs with small conditionals, a locked runner per launch, secret-safe execution boundaries, and a staged Justfile shim cutover.

The v2 hardening pass should focus on these outcomes:

- CLI UX polish for migrated actions: consistent help, consistent human output, structured JSON output for CI/headless use, deterministic exit codes, and clear error taxonomy rendering.
- Docs cutover preparation for real operator workflows: configuring, planning, applying, bootstrapping, verifying, destroying, monitoring, and migration notes from Just recipes to Python entrypoints.
- Operational graph hardening: clearer action result schemas, bounded output tails everywhere, explicit repair/rerun scope rendering, consistent action event stream shape, timeout policy coverage, and stricter side-effect metadata checks.
- Secret and audit hardening: broad regression coverage for redaction across graph results, audit logs, errors, and event streams; non-secret audit persistence strategy where appropriate; and explicit destructive/host override audit docs.
- Runner and environment hardening: actionable runner selection diagnostics, Docker fallback prerequisite guidance before graph execution, no silent host fallback, runner lock reuse visibility, and consistent mode display.
- Panel shell UX polish: clearer navigation across config, maintenance, monitoring, and deploy flows; graph preview before state-changing workflows; consistent structured status presentation; and monitoring v1 kept read-only/on-demand with no daemon.
- Regression and cutover gates: aggregate command parity suite, docs cutover checklist, future HITL issue for final Justfile removal, and future HITL issue for any stable plugin API declaration.

The PRD should stabilize internal contracts where the v1 implementation has already shown repeated use, but it must not declare a stable public plugin API. OpenTofu remains the infrastructure authority, local Terraform/OpenTofu state strategy stays unchanged, and the Justfile is not removed in this PRD.

## User Stories

1. As an operator, I want every migrated headless command to expose consistent help text, so that I can discover provider, approval, dry-run, JSON, and host override options without reading source.
2. As an operator, I want migrated commands to use consistent success output, so that init, plan, apply, bootstrap, verify, destroy, up/deploy, and monitoring feel like one control panel rather than separate scripts.
3. As an operator, I want command failures rendered through a shared error taxonomy, so that I can distinguish preflight failures, runner failures, command failures, timeouts, denied approvals, and redaction failures.
4. As an operator, I want non-zero exit codes to be stable and documented, so that shell automation can branch safely.
5. As a CI user, I want a structured JSON output option for headless commands, so that pipelines can parse graph status without scraping human text.
6. As a CI user, I want JSON output to contain graph name, action statuses, runner mode, redaction marker, repair scope, and bounded output tails, so that failures are machine-readable.
7. As a CI user, I want JSON output to avoid raw secrets by construction, so that CI logs remain safe.
8. As an operator, I want human output and JSON output to come from the same presentation model, so that surfaces cannot drift.
9. As an operator, I want safe dry-run or preview behavior where possible, so that I can inspect graph scope before state-changing workflows.
10. As an operator, I want state-changing workflows to show graph preview before execution, so that I understand planned action order and side-effect levels.
11. As an operator, I want destructive workflows to continue showing explicit destructive preview and requiring approval, so that v2 polish does not weaken destroy safety.
12. As an operator, I want destroy denial messages to be concise and token-safe, so that mistyped approval tokens do not leak.
13. As an operator, I want host override denial messages to be actionable and token-safe, so that I know how to recover without exposing escalation input.
14. As an operator, I want host override runs to show that host mode is active before graph execution, so that no run silently falls back to the host.
15. As an operator, I want runner selection diagnostics to show selected mode, detection reason, and remediation when detection fails, so that environment setup issues are obvious.
16. As an operator, I want Docker fallback missing prerequisites to produce setup guidance and exit before graph execution, so that a half-prepared fallback does not fail mid-graph.
17. As an operator, I want runner lock reuse displayed consistently for a launch, so that I know all panels and graphs use the same execution mode.
18. As an operator, I want no silent host fallback, so that portability and isolation policy remain enforced.
19. As an operator, I want monitoring v1 to stay read-only and on-demand, so that opening the control panel never starts a daemon or remote probe suite.
20. As an operator, I want monitoring status to use the same structured status presentation model as operational graphs, so that readiness and lifecycle output are consistent.
21. As an operator, I want config, maintenance, monitoring, and deploy navigation to be clearer, so that I can find configuration, lifecycle, and observability flows quickly.
22. As an operator, I want maintenance actions visibly labeled as state-changing, so that I do not confuse them with monitoring checks.
23. As an operator, I want deploy/up compound workflows to show ordered action previews, so that I understand where provisioning ends and bootstrap/verify begins.
24. As an operator, I want apply failure output to include whether rerun scope is failed node, failed subtree, or full panel, so that recovery is clear.
25. As an operator, I want verify failure output to include explicit repair/rerun scope, so that I know whether to retry verification only or rerun a broader workflow.
26. As an operator, I want bootstrap failures to expose non-secret target and stage context, so that I can recover without revealing secret material.
27. As an operator, I want bounded output tails from all command-backed actions, so that long logs remain useful without unbounded memory or audit growth.
28. As an operator, I want timeout failures to state which action timed out and what timeout policy applied, so that hung infrastructure or SSH commands are diagnosable.
29. As an operator, I want docs for configure, plan, apply, bootstrap, verify, destroy, deploy/up, and monitoring, so that I can operate the repo without reading implementation code.
30. As an operator, I want migration notes from Just recipes to Python entrypoints, so that existing muscle memory can transition gradually.
31. As an operator, I want docs to state that the Justfile remains a compatibility shim, so that I know it is still supported during v2.
32. As a release owner, I want documented Justfile removal criteria, so that final cutover is an explicit HITL decision rather than an incidental cleanup.
33. As a release owner, I want final Justfile removal tracked as a future HITL issue, so that compatibility is not removed without approval.
34. As a release owner, I want stable public plugin API declaration tracked as a future HITL issue, so that internal hardening does not accidentally freeze third-party contracts.
35. As a maintainer, I want action result schemas to be clearer and internally stable, so that CLI, panel shell, tests, and audit code share one contract.
36. As a maintainer, I want action event streams to have consistent fields and redaction behavior, so that live UI and headless logging can share event handling.
37. As a maintainer, I want action descriptors to require explicit side-effect metadata, so that state-changing and destructive workflows cannot be ambiguous.
38. As a maintainer, I want action descriptors to require explicit timeout intent or an explicit allowed exception, so that timeout coverage is visible in review.
39. As a maintainer, I want infinite-timeout usage to remain limited to explicit non-destructive opt-in, so that destructive or high side-effect actions cannot hang forever.
40. As a maintainer, I want retry policies to match typed runner errors rather than free-form stderr text, so that retry behavior is stable.
41. As a maintainer, I want graph previews to be generated from action descriptors, so that previews remain aligned with actual execution.
42. As a maintainer, I want repair/rerun scopes to be generated from graph and descriptor metadata, so that every surface reports the same recovery guidance.
43. As a maintainer, I want operational adapters to return typed internal summaries rather than ad hoc dicts, so that presentation and tests can rely on stable-enough internal contracts.
44. As a maintainer, I want the framework core to own reusable status, event, runner, audit, and presentation primitives, so that repo-specific adapters stay thin.
45. As a maintainer, I want the hermes-vps app layer to own provider/OpenTofu/bootstrap-specific decisions, so that the framework core does not absorb repo-specific behavior.
46. As a maintainer, I want the Just shims to delegate without duplicating provider validation and workflow logic where practical, so that compatibility does not become a second implementation.
47. As a maintainer, I want duplicated provider override parsing between Just shims and Python entrypoints reduced or explicitly documented, so that behavior stays aligned.
48. As a maintainer, I want a command parity regression suite covering all migrated commands, so that v2 polish does not regress v1 command coverage.
49. As a maintainer, I want parity tests to cover Just shim, headless CLI, panel shell, and graph definitions, so that cross-surface drift is caught.
50. As a maintainer, I want fake-runner tests for graph execution, so that tests do not require live cloud providers or remote VPS access.
51. As a maintainer, I want tests to assert public behavior rather than private helper internals, so that refactors remain possible.
52. As a maintainer, I want secret redaction tests across graph results, event streams, audit logs, error rendering, and JSON output, so that no surface becomes the weak link.
53. As a maintainer, I want audit persistence to be non-secret and intentionally scoped, so that operator sessions can be inspected without storing secret material.
54. As a maintainer, I want destructive and host override audit docs to match implemented audit fields, so that operators know what is recorded.
55. As a maintainer, I want denied approvals recorded safely where policy requires it, so that attempted unsafe paths are auditable without token leakage.
56. As a maintainer, I want cloud live lookup strict preflight remediation to remain centralized and typed, so that config surfaces do not fork remediation wording.
57. As a maintainer, I want cloud remediation reused across a second surface only when the same typed contract fits, so that ADR promotion can be evaluated honestly.
58. As a maintainer, I want no new cloud providers in this PRD, so that hardening remains focused on operator readiness.
59. As a maintainer, I want OpenTofu to remain the planning/apply/destroy authority, so that advisory provider previews do not replace the infrastructure source of truth.
60. As a maintainer, I want local state strategy unchanged, so that v2 UX polish does not create hidden state migration risk.
61. As a future contributor, I want internal contracts documented as stable-enough but not public API, so that I can build safely without promising third-party compatibility.
62. As a future contributor, I want provisional plugin API language preserved, so that core/app boundaries can still evolve.
63. As a future contributor, I want docs and tests to use glossary terms consistently, so that framework core, standard panels, monitoring v1, maintenance, runner policy, and DAG node contract language stays aligned.
64. As a future monitoring implementer, I want monitoring v1 output to remain compatible with HealthProbe vocabulary, so that future remote probe work can extend rather than replace it.
65. As an operator, I want tiny read-only remote VPS probes excluded unless separately approved, so that v2 does not quietly become a health probe project.
66. As an operator, I want the docs cutover checklist to show what remains before Justfile removal, so that the transition has visible finish criteria.

## Implementation Decisions

- Keep the accepted package boundary intact: the framework core owns reusable primitives and standard panel concepts; the hermes-vps app layer owns repo-specific operational graphs, provider/OpenTofu behavior, cloud remediation, bootstrap, and presentation assets.
- Treat v2 as internal hardening, not a public plugin API freeze. Existing typed contracts may become stable-enough internal contracts, but third-party compatibility remains explicitly provisional.
- Define a shared internal presentation model for human CLI output, structured JSON output, panel shell status, and event summaries. This model should be produced from action graph results and non-secret context rather than reimplemented per surface.
- Add a structured JSON output mode for headless commands. JSON output should include graph identity, action identity, status, side-effect level, runner mode, timing where available, repair/rerun scope, bounded output tails, and redaction markers.
- Define a deterministic exit code taxonomy for public headless commands. At minimum, distinguish success, usage/config errors, preflight failures, runner unavailable, command failures, timeouts, approval denials, host override denials, and unexpected internal errors.
- Keep human CLI output concise but consistent. Every migrated action should report selected provider, runner mode, graph name, action status summary, and recovery guidance on failure.
- Introduce safe preview behavior for state-changing workflows where the action graph can be described without side effects. Destructive preview remains a stricter destroy-specific contract.
- Generate graph previews from action descriptors and graph topology so that preview output cannot drift from actual execution ordering.
- Make repair/rerun scope explicit in result rendering. Use DAG failure semantics and action metadata to render failed node, failed subtree, or full panel guidance.
- Clarify action result schemas. Avoid ad hoc action result dict drift by defining stable-enough internal summaries for common outcomes: command-backed actions, preflight actions, destroy preview/approval, bootstrap target resolution, monitoring checks, and graph-level results.
- Clarify action event stream shape. Events should consistently include action identity, status, timestamp, message, non-secret details, runner mode when known, and redaction marker when applicable.
- Ensure bounded output tails are used everywhere command output can be retained or rendered. Full command output should not be persisted by default.
- Make timeout policy explicit on state-changing command-backed actions. Actions with no timeout must either opt into the documented exception path or be updated with an explicit timeout intent.
- Keep retry behavior tied to typed runner errors and explicit retry policy metadata, not brittle stderr substring parsing where a typed alternative is available.
- Strengthen side-effect metadata checks so every action in every operational graph declares a side-effect level and destructive nodes cannot bypass approval policy.
- Preserve HostRunner policy: disabled by default, explicit enable flag, non-empty override reason, pre-run escalation token, central engine preflight enforcement, and token-safe denial behavior.
- Improve runner selection diagnostics without changing runner detection order. Diagnostics should explain selected mode, detection reason, lock scope, and actionable setup guidance on failure.
- Dockerized nix fallback should fail before graph execution if Docker prerequisites are missing or unusable. The failure should include guided setup text rather than entering a partial graph run.
- Keep runner lock scope per launch only. Display and audit the selected mode for that launch; do not persist runner lock between launches.
- Reduce duplicated behavior between Just shims and Python entrypoints. Where Just remains, keep it thin and ensure duplicated preflight/provider parsing is either delegated or covered by parity tests.
- Do not remove the Justfile in this PRD. Document removal criteria and create a future HITL cutover issue instead.
- Keep monitoring v1 read-only and on-demand. Do not introduce a background monitoring daemon or broad remote VPS health probe suite.
- Update panel shell UX around the existing standard panel taxonomy: config, maintenance, monitoring, and deploy/bootstrap flows. Maintenance remains state-changing; monitoring remains read-only observability.
- Show graph previews before state-changing workflows in the panel shell, including action order, side-effect level, provider, runner mode, and approval requirements when relevant.
- Reuse the same graph definitions across panel shell, headless CLI, and Just shim paths. No surface should define its own command ordering.
- Expand audit/session handling only for non-secret data. If audit persistence is added, it should persist selected runner mode, graph/action IDs, status summaries, approval metadata, target summaries, redaction records, and timestamps, but never raw provider tokens, API keys, bot tokens, OAuth artifact contents, generated env file contents, or bad approval tokens.
- Document destructive and host override audit behavior using the existing audit vocabulary, including denied and approved paths.
- Keep cloud strict preflight and typed remediation as the current source of truth for live lookup. Reuse typed remediation in additional surfaces only through the existing app-owned contract.
- Defer ADR promotion for cloud preflight/remediation until the already-planned human checkpoint evaluates cross-surface adoption.
- Do not change cloud provider support, local state strategy, OpenTofu authority, or gateway/session-routing policy in this PRD.

## Testing Decisions

- Tests remain behavior-first, public-interface-first, and fake-runner based. Prefer testing graph execution, headless CLI output, panel shell presentation, Just shim parity, and audit/session serialization over private helper implementation.
- Add an aggregate command parity regression suite covering migrated workflows: init, init-upgrade, plan, apply, bootstrap, verify, destroy, up/deploy, and monitoring.
- Parity tests should verify that headless CLI, panel shell, and compatibility shim surfaces use the same action graph definitions and command ordering.
- CLI UX tests should cover help text, human output shape, structured JSON output shape, exit code taxonomy, and failure rendering for representative success and failure paths.
- JSON output tests should assert schema-level behavior: graph name, action IDs, statuses, side-effect levels, runner mode, repair/rerun scope, bounded output tail markers, and redaction markers.
- Error taxonomy tests should cover preflight failure, runner unavailable, command not found, command failed, command timeout, destructive approval denied, host override denied, output limit exceeded, and redaction error paths.
- Graph preview tests should verify that previews are generated from action descriptors and include action order, side-effect levels, provider, runner mode, and approval requirements without executing side effects.
- Operational graph hardening tests should verify explicit side-effect metadata, timeout policy coverage, fail-fast critical path behavior, optional failure policy, and repair/rerun scope rendering.
- Runner tests should verify detection diagnostics, per-launch lock reuse, mode display, no silent host fallback, host override reason requirement, host override token gate, and Docker fallback prerequisite failure before graph execution.
- Secret redaction tests should cover graph results, event streams, audit logs, error messages, human output, JSON output, and bounded output tails.
- Audit tests should cover approved and denied destructive actions, approved and denied host override attempts, non-secret target summaries, backup metadata, runner selection metadata, and token-safe serialization.
- Panel shell tests should cover clearer navigation, state-changing vs read-only labeling, graph preview before state-changing workflows, deploy/up status presentation, and monitoring v1 remaining on-demand/read-only.
- Documentation tests or checklist validation should ensure operator docs mention migrated entrypoints, Just shim compatibility, removal criteria, destructive approval, host override policy, runner modes, JSON output, and docs cutover status.
- Cloud remediation regression tests should ensure strict live lookup preflight behavior remains centralized and token-safe while v2 output/presentation changes are added.
- Prior art includes the existing control-core engine smoke tests, runner audit tests, init runner lock tests, migrated command CLI tests, destroy CLI tests, panel shell v1 tests, monitoring v1 tests, Just shim tests, command coverage regression gate, configure services tests, and cloud remediation tests.
- Changed Python should continue to pass the repo validation gate: pytest, ruff, and basedpyright through the project toolchain wrapper.

## Out of Scope

- Adding new cloud providers.
- Replacing OpenTofu as the infrastructure planning/apply/destroy authority.
- Adding a background monitoring daemon or scheduled collector.
- Freezing or declaring a stable third-party plugin API.
- Removing the Justfile without separate HITL approval.
- Changing the local Terraform/OpenTofu state strategy.
- Building a broad real remote VPS HealthProbe suite.
- Adding remote VPS health probes beyond a tiny read-only check explicitly approved in a follow-up issue.
- Rewriting the entire config wizard internals unless required for shared presentation or cutover readiness.
- Changing gateway runtime ownership, GatewayManager scope, or future SessionRouter policy.
- Persisting raw secret material in framework state, audit logs, event streams, command output, or docs examples.
- Promoting cloud preflight/remediation to an ADR inside this PRD unless the separate human checkpoint approves it.

## Further Notes

- This PRD follows the local Markdown issue tracker convention: one feature directory with this PRD at the root and future implementation issues under an issues directory.
- This PRD intentionally uses project glossary terms: control panel, wizard, framework core, standard panels, panel taxonomy, maintenance, monitoring, monitoring v1, HealthProbe, CloudProvider, InfraPlanner, RemoteExecutor, GatewayManager, panel execution model, DAG node contract, runner policy, host override policy, secrets policy, destructive-action gate, destructive preview contract, shim policy, and removal criteria.
- The accepted control-panel architecture ADR remains in force. This PRD hardens the v1 implementation and docs cutover path; it does not reopen the package boundary, runner policy, static DAG policy, secrets policy, or staged shim cutover decision.
- Future implementation issues should be thin vertical slices, likely including: shared CLI presentation/JSON contract, exit code and error taxonomy rendering, graph preview and repair scope rendering, action result/event schema hardening, timeout and side-effect metadata gate, runner diagnostics and Docker fallback guidance, redaction/audit persistence hardening, panel shell UX polish, operator docs cutover, command parity aggregate gate, HITL Justfile removal decision, and HITL plugin API freeze decision.
- HITL checkpoint: final Justfile removal must be a separate issue after command parity and docs cutover are accepted.
- HITL checkpoint: declaring any stable public plugin API must be a separate issue after internal v2 contracts prove stable across real use.
