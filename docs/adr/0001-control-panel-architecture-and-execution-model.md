# ADR-0001: Control Panel Architecture and Execution Model

Status: Accepted
Date: 2026-04-29

## Context

This repository currently uses a Justfile-centric operational interface with growing Python TUI capabilities.
We want to replace recipe-centric orchestration with a reusable Python control panel framework while preserving strict portability:
- do not rely on host-installed toolchains by default
- prioritize Nix/flake workflows
- support Docker-based fallback for systems where Nix is unavailable

The solution must be reusable across projects, support both interactive and non-interactive execution, and provide safe handling of side effects and secrets.

## Decision

Adopt the following architecture and policies.

1. Package boundary
- Immediate split into two packages in the same repository:
  - `hermes_control_core`: reusable framework primitives and standard panels
  - `hermes_vps_app`: repository-specific nodes, adapters, assets

2. Framework model
- Core exposes stable primitives (state machine, step registry, async correlation, validation/error contracts, rendering primitives).
- Standard library-shipped panels are included: `config`, `bootstrap`, `maintenance`, `monitoring`.
- Panel taxonomy is explicit:
  - `maintenance`: state-changing operator workflows
  - `monitoring`: read-only observability workflows

3. Execution model
- Panels execute via a DAG action engine (acyclic graph of typed actions).
- V1 topology policy: static graphs with small conditional branches (no general runtime graph expansion).
- Node contract includes typed inputs/outputs, preconditions, side-effect level, timeout/retry policy, and repair/rollback hints.

4. Failure and recovery
- Critical path is fail-fast by default.
- Optional nodes may declare `allow_failure=true`.
- Engine emits rerun scopes: failed node only, failed subtree, or full panel.
- Successful node results are cacheable by deterministic hash of typed inputs + node version.

5. Runner policy and portability
- `HostRunner` is disabled by default.
- Runner detection order:
  1) direnv-attached flake shell
  2) `nix develop` mode when Nix exists but direnv is not active
  3) Dockerized Nix fallback when Nix is unavailable/non-viable
  4) host runner only via explicit override
- Runner is detected once at app startup and locked for the session.

6. Secrets policy
- No secret persistence in framework state/logs by default.
- Secrets are handled as references/handles and materialized only at execution boundaries when required.
- Any persistence of secret material requires an audited per-node escape hatch.

7. Destructive action safety
- Nodes marked destructive require explicit confirmation token in interactive mode.
- Non-interactive destructive execution requires explicit override flag (e.g. `--approve-destructive`) and emits audit log entries.
- UI must show precise target scope before confirmation (provider/resource IDs/hostnames).

8. Migration strategy
- Use staged cutover from Justfile to panel commands.
- Keep Justfile as thin compatibility shim delegating to app entrypoints.
- Remove Justfile only after command-coverage parity and docs cutover.

9. Plugin API lifecycle
- Plugin API remains provisional during v1 iteration.
- Plugins declare supported core version ranges.
- Incompatible core/plugin combinations fail fast at load.

## Consequences

Positive:
- Reusable framework with clear separation between core and repo-specific logic.
- Improved safety, observability, and deterministic execution.
- Portable execution model aligned with Nix-first policy and Docker fallback.
- Enables headless and CI execution using the same action graphs as TUI.

Costs / trade-offs:
- Additional upfront architecture and packaging complexity.
- Need to maintain compatibility layer during migration.
- Provisional plugin API may introduce short-term churn before freeze.

## Alternatives Considered

1) Keep Justfile-centric orchestration and incrementally enhance scripts
- Rejected: harder to generalize and reuse; weaker typed contracts and execution model.

2) Build monolithic app package with no core/app split
- Rejected: creates coupling debt and undermines reuse goals.

3) Dynamic runtime graph expansion in v1
- Rejected for v1: higher complexity and lower predictability. Static DAG + small conditionals is sufficient initially.
