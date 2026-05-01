# Control panel operator cutover guide

This guide is the operator-facing cutover document for the migrated control-panel workflows. It assumes commands are run from the repository root and through the project toolchain wrapper unless noted otherwise.

Use this form for direct Python entrypoints:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli <workflow> --repo-root ."
```

Use `./scripts/toolchain.sh "python3 -m scripts.configure_tui"` for the configuration wizard. The Just recipes remain compatibility shims for migrated workflows, but the Python entrypoints are the canonical surface for automation and JSON output.

## Workflow quick reference

Configure:

```bash
./scripts/toolchain.sh "python3 -m scripts.configure_tui"
```

The wizard creates `.env` from `.env.example` when needed, enforces mode `0600`, guides provider selection, and writes provider/Hermes/Telegram settings. Do not paste secrets into tickets or logs.

Initialize provider plugins and local OpenTofu metadata:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli init --repo-root ."
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli init-upgrade --repo-root ."
```

Plan and apply infrastructure:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli plan --repo-root ."
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli apply --repo-root ."
```

Bootstrap and verify the host:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli bootstrap --repo-root ."
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli verify --repo-root ."
```

Deploy/up aliases:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli up --repo-root ."
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli deploy --repo-root ."
```

`up` and `deploy` run the migrated compound flow for normal provisioning after configuration. Prefer these once provider state and `.env` are ready.

Monitoring/readiness:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli monitoring --repo-root ."
```

Monitoring reports local readiness, graph/action context, repair scope, and redacted details without mutating infrastructure.

Destroy preview and execution:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli destroy --repo-root . --preview"
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli destroy --repo-root . --approve-destructive DESTROY:<provider>"
```

Interactive terminals may prompt for `DESTROY <provider>` when no approval token is supplied. Headless automation must pass `--approve-destructive DESTROY:<provider>` after reviewing the preview.

## Provider override behavior

By default, workflows resolve the provider from `TF_VAR_cloud_provider` in `.env`. Override a single command with `--provider hetzner` or `--provider linode`:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli plan --repo-root . --provider linode"
```

The override selects the OpenTofu directory under `opentofu/providers/<provider>` and sets the provider environment for the command. Provider API tokens still come from `.env` (`HCLOUD_TOKEN` or `LINODE_TOKEN`). Invalid providers fail as usage/config errors rather than falling back to another provider.

## JSON output, graph preview, and exit code taxonomy

Migrated workflows support human output by default and JSON output with `--output json`:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli plan --repo-root . --output json"
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli apply --repo-root . --preview --output json"
```

Use `--preview` for graph preview before state-changing commands. Preview output includes workflow name, graph id, ordered actions, dependencies, side-effect levels, approval requirements, repair scope, runner mode, provider, and redaction metadata. Destroy preview also includes local state backup destination and non-secret outputs when available.

The exit code taxonomy is deterministic for direct CLI callers:

- `0`: success
- `10`: usage/config error
- `20`: preflight failure
- `30`: runner unavailable
- `40`: command failure
- `41`: command timeout
- `42`: destructive approval denied
- `43`: host override denied
- `50`: output limit exceeded
- `60`: redaction error
- `99`: unexpected internal error

JSON failures include `error.category`, `error.exit_code`, workflow, and graph/action context when available.

## Runner modes and isolation policy

The control panel chooses exactly one runner for each process launch and locks that choice for the rest of the launch. The runner lock scope is `per-launch`; restart the command after changing Nix, direnv, Docker, or host override setup.

Detection order:

1. `direnv_nix`: an already-attached direnv/Nix shell with `/nix/store` Python/tooling in PATH.
2. `nix_develop`: local `nix` is available, so commands run through `nix develop`.
3. `docker_nix`: local `nix` is unavailable but Docker exists; commands run through the pinned Nix container fallback.
4. `host`: break-glass host execution only when explicitly enabled.

Docker fallback guidance: start the Docker daemon, ensure the current user can run `docker info`, and rerun the command. Docker fallback preflight fails before graph execution if Docker cannot run.

There is no silent host fallback. Host mode is not selected just because Nix and Docker are missing. The host override policy requires all of the following:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli verify --repo-root . \
  --allow-host-override \
  --override-reason 'break-glass: verifying existing host during Nix outage' \
  --host-override-token I-ACK-HOST-OVERRIDE"
```

The override reason is required for auditability. The token `I-ACK-HOST-OVERRIDE` is required before graph execution. If approval is absent or invalid, host override is denied with the host override exit code.

## Destructive destroy approval, backup, preview, and audit behavior

Always run destroy preview first:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli destroy --repo-root . --provider linode --preview"
```

Preview shows the graph preview and a destroy preview payload with fields such as provider, `tf_dir`, `backup_root`, `backup_dir`, `state_file_count`, local state file paths, and safe non-secret outputs. Example non-secret safe output:

```text
server_ipv4=203.0.113.10
```

Before destroy execution, local state files are copied into `.state-backups/<provider>/tfstate-<UTC_TIMESTAMP>.tar.gz` when state exists. The backup is local, mode `0600`, and unencrypted by default; encrypt it before off-host storage.

Destroy execution requires approval:

```bash
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli destroy --repo-root . --provider linode --approve-destructive DESTROY:<provider>"
```

Use the literal selected provider in real commands, for example `DESTROY:linode`. Do not use the placeholder as an actual approval token.

audit metadata example, using non-secret values only:

```json
{
  "workflow": "destroy",
  "provider": "linode",
  "runner_selection": {
    "mode": "nix_develop",
    "reason": "nix command available; use nix develop wrapper mode",
    "lock_scope": "per-launch"
  },
  "destructive_approval": {
    "approved": true,
    "mode": "headless",
    "token_shape": "DESTROY:<provider>"
  },
  "backup": {
    "status": "created",
    "path": ".state-backups/linode/tfstate-20260430T205500Z.tar.gz"
  },
  "redactions": {"applied": true, "marker": "***"}
}
```

The audit log should record runner selection, approval mode, backup status/path, graph/action events, repair scope, and redaction status. Never include API tokens, SSH private keys, Telegram tokens, OAuth artifacts, or raw `.env` contents in audit examples.

## Just shim compatibility and migration notes

Just remains available as a compatibility layer for migrated recipes. These are equivalent operator intents:

```bash
just plan PROVIDER=linode
./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim plan --repo-root . --provider-arg PROVIDER=linode"
./scripts/toolchain.sh "python3 -m hermes_vps_app.cli plan --repo-root . --provider linode"
```

The shim preserves historical Just provider forms such as `just PROVIDER=linode plan` and `just plan PROVIDER=linode`, then delegates to the Python CLI. Destroy keeps a Just-only compatibility guard:

```bash
just destroy CONFIRM=YES PROVIDER=linode
```

For new automation, prefer the Python CLI directly because it exposes `--output json`, `--preview`, host override controls, deterministic exit codes, and graph-aware error payloads without shell parsing.

Migration mapping:

- `just configure` -> `./scripts/toolchain.sh "python3 -m scripts.configure_tui"`
- `just init` -> `./scripts/toolchain.sh "python3 -m hermes_vps_app.cli init --repo-root ."`
- `just init-upgrade` -> `./scripts/toolchain.sh "python3 -m hermes_vps_app.cli init-upgrade --repo-root ."`
- `just plan` -> `./scripts/toolchain.sh "python3 -m hermes_vps_app.cli plan --repo-root ."`
- `just apply` -> `./scripts/toolchain.sh "python3 -m hermes_vps_app.cli apply --repo-root ."`
- `just bootstrap` -> `./scripts/toolchain.sh "python3 -m hermes_vps_app.cli bootstrap --repo-root ."`
- `just verify` -> `./scripts/toolchain.sh "python3 -m hermes_vps_app.cli verify --repo-root ."`
- `just up` -> `./scripts/toolchain.sh "python3 -m hermes_vps_app.cli up --repo-root ."`
- `just deploy` -> `./scripts/toolchain.sh "python3 -m hermes_vps_app.cli deploy --repo-root ."`
- `just destroy CONFIRM=YES` -> `./scripts/toolchain.sh "python3 -m hermes_vps_app.cli destroy --repo-root . --approve-destructive DESTROY:<provider>"`
- `just logs` and `just hardening-audit` remain legacy Just recipes until separately migrated.

## Docs cutover checklist

Use this docs cutover checklist before directing operators to the migrated control panel:

- Confirm `.env` exists, is mode `0600`, and contains the intended `TF_VAR_cloud_provider`.
- Confirm provider tokens exist only in `.env` and are not pasted into command lines or tickets.
- Run `init` or `init-upgrade` for the selected provider.
- Run `plan --preview` or a normal plan and inspect graph/action context.
- Run `apply`, then `bootstrap`, then `verify`.
- Run `monitoring` and capture JSON if automation needs machine-readable readiness.
- For provider overrides, use `--provider <provider>` in direct CLI or `PROVIDER=<provider>` in Just compatibility mode.
- For destructive changes, run `destroy --preview`, verify backup path under `.state-backups/<provider>/`, then approve with `DESTROY:<provider>` only when intentional.
- If Nix is unavailable, prefer Docker fallback. Use host override only as audited break-glass with reason and token.
- Update runbooks and CI jobs from Just recipes to direct Python entrypoints where JSON, preview, or deterministic exit handling is required.

Justfile removal requires a separate HITL issue and is not performed here. This issue publishes operator docs only; it does not remove `Justfile` or change Just shim behavior.

## V2 aggregate cutover gate

Before any future HITL decision to remove `Justfile` or declare a stable public plugin API, run the aggregate v2 cutover gate from the repository root:

```bash
./scripts/toolchain.sh "python3 -m pytest tests/test_v2_cutover_gate_issue13.py tests/test_issue11_regression_gate.py tests/test_secret_redaction_issue09.py tests/test_operator_docs_issue12.py -q"
```

This gate is a prerequisite for any future Justfile removal and a prerequisite for any future stable public plugin API decision. It proves migrated command parity across graph definitions, the headless CLI, the panel shell, and Just compatibility shims; validates the side-effect/timeout metadata policy for operational and monitoring graphs; explicitly includes the secret redaction regression matrix; and re-runs the docs cutover checklist regression. It is a regression/cutover readiness check only: it does not remove `Justfile` and does not declare a plugin API stable.
