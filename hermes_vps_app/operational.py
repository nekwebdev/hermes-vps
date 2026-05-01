# pyright: reportAny=false
from __future__ import annotations

import os
import re
import shutil
import stat
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_control_core import (
    ActionDescriptor,
    ActionGraph,
    CommandFailed,
    Engine,
    EngineResult,
    RunRequest,
    Runner,
    SessionAuditLog,
)

VALID_PROVIDERS = {"hetzner", "linode"}
OAUTH_PROVIDERS = {"openai-codex", "nous", "qwen-oauth", "google-gemini-cli"}


@dataclass(frozen=True)
class InitSelection:
    provider: str
    tf_dir: Path


@dataclass(frozen=True)
class BootstrapSelection:
    provider: str
    tf_dir: Path
    key_path: Path
    ssh_port: int
    raw_allowed_ports: str
    hermes_provider: str
    hermes_api_key: str
    hermes_agent_version: str
    telegram_bot_token: str
    telegram_allowlist_ids: str
    telegram_poll_timeout: str
    hermes_model: str
    hermes_agent_release_tag: str
    hermes_auth_json_path: Path


def resolve_provider(*, provider_override: str | None) -> str:
    if provider_override is not None:
        candidate = provider_override.strip()
    else:
        candidate = os.environ.get("TF_VAR_cloud_provider", "").strip()

    if candidate not in VALID_PROVIDERS:
        raise ValueError("provider must be one of: hetzner, linode")
    return candidate


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate_init_environment(*, repo_root: Path, provider: str) -> InitSelection:
    env_path = repo_root / ".env"
    if not env_path.is_file():
        raise ValueError(".env is missing")

    env_mode = stat.S_IMODE(env_path.stat().st_mode)
    if env_mode & 0o077:
        raise ValueError(".env permissions are too broad; expected mode 600")

    tf_dir = repo_root / "opentofu" / "providers" / provider
    if not tf_dir.is_dir():
        raise ValueError(f"OpenTofu provider directory not found: {tf_dir}")

    return InitSelection(provider=provider, tf_dir=tf_dir)


def _parse_bootstrap_port(port_raw: str) -> int:
    if not re.fullmatch(r"[0-9]+", port_raw):
        raise ValueError("BOOTSTRAP_SSH_PORT must be numeric")
    port = int(port_raw)
    if port < 1 or port > 65535:
        raise ValueError("BOOTSTRAP_SSH_PORT must be between 1 and 65535")
    return port


def _validate_allowed_tcp_ports(raw: str) -> None:
    if any(char in raw for char in ['"', "'", "\\", "`", "$"]):
        raise ValueError("TF_VAR_allowed_tcp_ports contains unsupported characters")
    if not re.fullmatch(r"\[\s*-?[0-9]+(\s*,\s*-?[0-9]+)*\s*\]|\[\s*\]", raw):
        raise ValueError("TF_VAR_allowed_tcp_ports must be JSON-like numeric array syntax")


def validate_bootstrap_environment(*, repo_root: Path, provider: str) -> BootstrapSelection:
    init = validate_init_environment(repo_root=repo_root, provider=provider)
    env_values = _parse_env_file(repo_root / ".env")

    key_path_raw = env_values.get("BOOTSTRAP_SSH_PRIVATE_KEY_PATH", "").strip()
    if not key_path_raw:
        raise ValueError("BOOTSTRAP_SSH_PRIVATE_KEY_PATH is required")
    key_path = Path(os.path.expanduser(key_path_raw))
    if not key_path.is_file():
        raise ValueError("SSH private key not found")
    if not os.access(key_path, os.R_OK):
        raise ValueError("SSH private key is not readable")
    key_mode = stat.S_IMODE(key_path.stat().st_mode)
    if key_mode & 0o077:
        raise ValueError("SSH private key permissions are too broad; expected mode 600")

    ssh_port = _parse_bootstrap_port(env_values.get("BOOTSTRAP_SSH_PORT", "22").strip() or "22")

    hermes_provider = env_values.get("TF_VAR_hermes_provider", "openrouter").strip() or "openrouter"
    hermes_api_key = env_values.get("HERMES_API_KEY", "")
    hermes_auth_json_path = repo_root / "bootstrap" / "runtime" / "hermes-auth.json"
    if hermes_provider in OAUTH_PROVIDERS:
        if not hermes_auth_json_path.is_file() and not hermes_api_key:
            raise ValueError("OAuth provider selected but no auth artifact found")
    elif not hermes_api_key:
        raise ValueError("HERMES_API_KEY must be set")

    hermes_agent_version = env_values.get("HERMES_AGENT_VERSION", "")
    if not hermes_agent_version:
        raise ValueError("HERMES_AGENT_VERSION must be set")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*", hermes_agent_version):
        raise ValueError("HERMES_AGENT_VERSION must be a pinned semantic version")

    telegram_bot_token = env_values.get("TELEGRAM_BOT_TOKEN", "")
    if not telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN must be set")

    telegram_allowlist_ids = env_values.get("TELEGRAM_ALLOWLIST_IDS", "")
    if not telegram_allowlist_ids:
        raise ValueError("TELEGRAM_ALLOWLIST_IDS must be set")
    if not re.fullmatch(r"-?[0-9]+(,-?[0-9]+)*", telegram_allowlist_ids):
        raise ValueError("TELEGRAM_ALLOWLIST_IDS must be comma-separated integers")

    raw_allowed_ports = env_values.get("TF_VAR_allowed_tcp_ports", "[]")
    _validate_allowed_tcp_ports(raw_allowed_ports)

    return BootstrapSelection(
        provider=provider,
        tf_dir=init.tf_dir,
        key_path=key_path,
        ssh_port=ssh_port,
        raw_allowed_ports=raw_allowed_ports,
        hermes_provider=hermes_provider,
        hermes_api_key=hermes_api_key,
        hermes_agent_version=hermes_agent_version,
        telegram_bot_token=telegram_bot_token,
        telegram_allowlist_ids=telegram_allowlist_ids,
        telegram_poll_timeout=env_values.get("TELEGRAM_POLL_TIMEOUT", "30"),
        hermes_model=env_values.get("TF_VAR_hermes_model", "anthropic/claude-sonnet-4"),
        hermes_agent_release_tag=env_values.get("HERMES_AGENT_RELEASE_TAG", ""),
        hermes_auth_json_path=hermes_auth_json_path,
    )


@dataclass(frozen=True)
class DestroyPreview:
    provider: str
    tf_dir: Path
    backup_root: Path
    backup_dir: Path
    state_files: list[Path]
    safe_outputs: dict[str, str]


def _list_local_state_files(tf_dir: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.tfstate", "*.tfstate.backup"):
        files.extend(tf_dir.rglob(pattern))
    return sorted({f.resolve() for f in files if f.is_file()})


def _read_safe_output(runner: Runner, *, repo_root: Path, provider: str, output_name: str) -> str | None:
    req = RunRequest(
        command=["tofu", f"-chdir=opentofu/providers/{provider}", "output", "-raw", output_name],
        cwd=repo_root,
        env={"TF_VAR_cloud_provider": provider},
        shell=False,
    )
    result = runner.run(req)
    if result.exit_code != 0:
        return None
    value = result.stdout.strip()
    return value if value else None


def build_destroy_preview(*, repo_root: Path, provider: str, tf_dir: Path, runner: Runner) -> DestroyPreview:
    backup_root = repo_root / ".state-backups"
    backup_dir = backup_root / provider
    state_files = _list_local_state_files(tf_dir)
    safe_outputs: dict[str, str] = {}
    for name in ("public_ipv4", "admin_username", "server_id", "resource_id", "instance_id"):
        value = _read_safe_output(runner, repo_root=repo_root, provider=provider, output_name=name)
        if value is not None:
            safe_outputs[name] = value
    return DestroyPreview(
        provider=provider,
        tf_dir=tf_dir,
        backup_root=backup_root,
        backup_dir=backup_dir,
        state_files=state_files,
        safe_outputs=safe_outputs,
    )


def _backup_state_files(*, preview: DestroyPreview) -> tuple[str | None, str]:
    _ = preview.backup_root.mkdir(parents=True, exist_ok=True)
    _ = preview.backup_dir.mkdir(parents=True, exist_ok=True)
    _ = os.chmod(preview.backup_root, stat.S_IRWXU)
    _ = os.chmod(preview.backup_dir, stat.S_IRWXU)

    if not preview.state_files:
        return None, "skipped_no_state"

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = preview.backup_dir / f"tfstate-{timestamp}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for state_file in preview.state_files:
            arcname = state_file.relative_to(preview.tf_dir)
            archive.add(state_file, arcname=str(arcname))
    _ = os.chmod(archive_path, stat.S_IRUSR | stat.S_IWUSR)
    return str(archive_path), "created"


class OperationalActionHandler:
    def run(self, action: ActionDescriptor, context: dict[str, Any], runner: Runner) -> dict[str, Any]:
        provider = str(context["provider"])
        repo_root = Path(str(context["repo_root"]))
        if action.action_id == "tofu_init":
            return self._run_checked(
                runner,
                repo_root=repo_root,
                provider=provider,
                command=["tofu", f"-chdir=opentofu/providers/{provider}", "init"],
            )
        if action.action_id == "tofu_init_upgrade":
            return self._run_checked(
                runner,
                repo_root=repo_root,
                provider=provider,
                command=["tofu", f"-chdir=opentofu/providers/{provider}", "init", "-upgrade"],
            )
        if action.action_id == "tofu_plan":
            return self._run_checked(
                runner,
                repo_root=repo_root,
                provider=provider,
                command=["tofu", f"-chdir=opentofu/providers/{provider}", "plan", "-out=tofuplan"],
            )
        if action.action_id == "tofu_apply":
            return self._run_apply(runner, repo_root=repo_root, provider=provider)
        if action.action_id == "tofu_destroy":
            return self._run_checked(
                runner,
                repo_root=repo_root,
                provider=provider,
                command=["tofu", f"-chdir=opentofu/providers/{provider}", "destroy"],
            )
        if action.action_id == "bootstrap_resolve_target":
            return self._resolve_bootstrap_target(runner, context=context)
        if action.action_id == "bootstrap_execute_remote":
            return self._execute_bootstrap_remote(runner, context=context)
        if action.action_id == "verify_resolve_target":
            return self._resolve_bootstrap_target(runner, context=context)
        if action.action_id == "verify_execute_remote":
            return self._execute_verify_remote(runner, context=context)
        return {"ok": True}

    def _run_checked(self, runner: Runner, *, repo_root: Path, provider: str, command: list[str]) -> dict[str, Any]:
        req = RunRequest(
            command=command,
            cwd=repo_root,
            env={"TF_VAR_cloud_provider": provider},
            shell=False,
        )
        result = runner.run(req)
        if result.exit_code != 0:
            raise CommandFailed(f"command failed with exit code {result.exit_code}: {' '.join(command)}")
        return {"exit_code": result.exit_code, "runner_mode": result.runner_mode}

    def _run_apply(self, runner: Runner, *, repo_root: Path, provider: str) -> dict[str, Any]:
        plan_path = repo_root / "opentofu" / "providers" / provider / "tofuplan"
        if not plan_path.is_file():
            _ = self._run_checked(
                runner,
                repo_root=repo_root,
                provider=provider,
                command=["tofu", f"-chdir=opentofu/providers/{provider}", "plan", "-out=tofuplan"],
            )

        apply_command = ["tofu", f"-chdir=opentofu/providers/{provider}", "apply", "tofuplan"]
        try:
            apply_result = self._run_checked(
                runner,
                repo_root=repo_root,
                provider=provider,
                command=apply_command,
            )
        except CommandFailed as exc:
            message = str(exc)
            if (
                "Saved plan is stale" in message
                or "Failed to load" in message and "tofuplan" in message
                or "No such file or directory" in message
            ):
                _ = self._run_checked(
                    runner,
                    repo_root=repo_root,
                    provider=provider,
                    command=["tofu", f"-chdir=opentofu/providers/{provider}", "plan", "-out=tofuplan"],
                )
                apply_result = self._run_checked(
                    runner,
                    repo_root=repo_root,
                    provider=provider,
                    command=apply_command,
                )
            else:
                raise

        output_req = RunRequest(
            command=["tofu", f"-chdir=opentofu/providers/{provider}", "output", "-raw", "public_ipv4"],
            cwd=repo_root,
            env={"TF_VAR_cloud_provider": provider},
            shell=False,
        )
        output = runner.run(output_req)
        if output.exit_code != 0:
            raise CommandFailed("failed to resolve public_ipv4 output")
        server_ip = output.stdout.strip()

        alias_req = RunRequest(
            command=["./scripts/update_ssh_alias.sh", ".ssh/config", "hermes-vps", server_ip],
            cwd=repo_root,
            env=None,
            shell=False,
        )
        alias = runner.run(alias_req)
        if alias.exit_code != 0:
            raise CommandFailed("ssh alias reconciliation failed")

        apply_result["public_ipv4"] = server_ip
        return apply_result

    def _resolve_bootstrap_target(self, runner: Runner, *, context: dict[str, Any]) -> dict[str, Any]:
        repo_root = Path(str(context["repo_root"]))
        provider = str(context["provider"])

        ip_out = runner.run(
            RunRequest(
                command=["tofu", f"-chdir=opentofu/providers/{provider}", "output", "-raw", "public_ipv4"],
                cwd=repo_root,
                env={"TF_VAR_cloud_provider": provider},
                shell=False,
            )
        )
        if ip_out.exit_code != 0:
            raise CommandFailed("failed to resolve public_ipv4 output")

        admin_out = runner.run(
            RunRequest(
                command=["tofu", f"-chdir=opentofu/providers/{provider}", "output", "-raw", "admin_username"],
                cwd=repo_root,
                env={"TF_VAR_cloud_provider": provider},
                shell=False,
            )
        )
        if admin_out.exit_code != 0:
            raise CommandFailed("failed to resolve admin_username output")

        context["bootstrap_target_ip"] = ip_out.stdout.strip()
        context["bootstrap_target_user"] = admin_out.stdout.strip()
        return {"public_ipv4": context["bootstrap_target_ip"], "admin_username": context["bootstrap_target_user"]}

    def _execute_verify_remote(self, runner: Runner, *, context: dict[str, Any]) -> dict[str, Any]:
        repo_root = Path(str(context["repo_root"]))
        config = context["bootstrap_config"]
        assert isinstance(config, BootstrapSelection)

        ip = str(context["bootstrap_target_ip"])
        user = str(context["bootstrap_target_user"])
        key_path = str(config.key_path)
        port = str(config.ssh_port)

        command = [
            "ssh",
            "-i",
            key_path,
            "-p",
            port,
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"{user}@{ip}",
            "sudo bash /root/hermes-vps-stage/bootstrap/90-verify.sh",
        ]
        verify = runner.run(RunRequest(command=command, cwd=repo_root, env=None, shell=False))
        if verify.exit_code != 0:
            raise CommandFailed("remote verification failed")
        return {"ok": True, "target": f"{user}@{ip}"}

    def _cleanup_runtime(self, runtime_dir: Path) -> None:
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir, ignore_errors=True)

    def _execute_bootstrap_remote(self, runner: Runner, *, context: dict[str, Any]) -> dict[str, Any]:
        repo_root = Path(str(context["repo_root"]))
        config = context["bootstrap_config"]
        assert isinstance(config, BootstrapSelection)

        ip = str(context["bootstrap_target_ip"])
        user = str(context["bootstrap_target_user"])
        key_path = str(config.key_path)
        port = str(config.ssh_port)

        runtime_dir = repo_root / "bootstrap" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        hermes_env = runtime_dir / "hermes.env"
        telegram_env = runtime_dir / "telegram-gateway.env"
        try:
            _ = hermes_env.write_text(
                "\n".join(
                    [
                        f"HERMES_MODEL={config.hermes_model}",
                        f"HERMES_PROVIDER={config.hermes_provider}",
                        f"HERMES_API_KEY={config.hermes_api_key}",
                        f"HERMES_AGENT_VERSION={config.hermes_agent_version}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            _ = telegram_env.write_text(
                "\n".join(
                    [
                        f"TELEGRAM_BOT_TOKEN={config.telegram_bot_token}",
                        f"TELEGRAM_ALLOWLIST_IDS={config.telegram_allowlist_ids}",
                        f"TELEGRAM_POLL_TIMEOUT={config.telegram_poll_timeout}",
                        "HERMES_COMMAND=/usr/local/bin/hermes",
                        "HERMES_SYSTEM_PROMPT=You are Hermes Agent running on a personal production VPS.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            _ = os.chmod(hermes_env, stat.S_IRUSR | stat.S_IWUSR)
            _ = os.chmod(telegram_env, stat.S_IRUSR | stat.S_IWUSR)

            if config.hermes_auth_json_path.is_file():
                shutil.copy2(config.hermes_auth_json_path, runtime_dir / "hermes-auth.json")
                os.chmod(runtime_dir / "hermes-auth.json", stat.S_IRUSR | stat.S_IWUSR)

            ssh_base = ["ssh", "-i", key_path, "-p", port, "-o", "StrictHostKeyChecking=accept-new", f"{user}@{ip}"]
            rsync_ssh = f"ssh -i {key_path} -p {port} -o StrictHostKeyChecking=accept-new"

            create_stage = runner.run(
                RunRequest(
                    command=ssh_base + ["sudo install -d -m 0700 -o root -g root /root/hermes-vps-stage"],
                    cwd=repo_root,
                    env=None,
                    shell=False,
                )
            )
            if create_stage.exit_code != 0:
                raise CommandFailed("remote staging directory creation failed")

            rsync = runner.run(
                RunRequest(
                    command=[
                        "rsync",
                        "-az",
                        "--delete",
                        "--rsync-path=sudo rsync",
                        "--chmod=D0700,F0600",
                        "-e",
                        rsync_ssh,
                        "bootstrap",
                        "templates",
                        f"{user}@{ip}:/root/hermes-vps-stage/",
                    ],
                    cwd=repo_root,
                    env=None,
                    shell=False,
                )
            )
            if rsync.exit_code != 0:
                raise CommandFailed("remote rsync failed")

            remote_script = (
                "sudo bash -c 'set -euo pipefail; "
                "install -d -m 0750 /etc/hermes /etc/telegram-gateway; "
                "install -m 0600 -o root -g root /root/hermes-vps-stage/bootstrap/runtime/hermes.env /etc/hermes/hermes.env; "
                "install -m 0600 -o root -g root /root/hermes-vps-stage/bootstrap/runtime/telegram-gateway.env /etc/telegram-gateway/gateway.env; "
                "bash /root/hermes-vps-stage/bootstrap/10-base.sh; "
                f"TF_VAR_allowed_tcp_ports=\"{config.raw_allowed_ports}\" bash /root/hermes-vps-stage/bootstrap/20-hardening.sh; "
                "if [[ -f /root/hermes-vps-stage/bootstrap/runtime/hermes-auth.json ]]; then "
                "id -u hermes >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/hermes --shell /usr/sbin/nologin hermes; "
                "install -d -m 0700 -o hermes -g hermes /var/lib/hermes/.hermes; "
                "install -m 0600 -o hermes -g hermes /root/hermes-vps-stage/bootstrap/runtime/hermes-auth.json /var/lib/hermes/.hermes/auth.json; "
                "fi; "
                f"HERMES_AGENT_VERSION=\"{config.hermes_agent_version}\" HERMES_AGENT_RELEASE_TAG=\"{config.hermes_agent_release_tag}\" bash /root/hermes-vps-stage/bootstrap/30-hermes.sh; "
                "bash /root/hermes-vps-stage/bootstrap/40-telegram-gateway.sh; "
                "bash /root/hermes-vps-stage/bootstrap/90-verify.sh; "
                "find /root/hermes-vps-stage/bootstrap/runtime -maxdepth 1 -type f \\( -name \"*.env\" -o -name \"hermes-auth.json\" \\) -exec rm -f {} + 2>/dev/null || true; "
                "rm -rf /root/hermes-vps-stage/bootstrap/runtime'"
            )
            execute = runner.run(RunRequest(command=ssh_base + [remote_script], cwd=repo_root, env=None, shell=False))
            if execute.exit_code != 0:
                raise CommandFailed("remote bootstrap execution failed")

            return {"ok": True, "target": f"{user}@{ip}"}
        finally:
            self._cleanup_runtime(runtime_dir)


def _action_definitions() -> dict[str, ActionDescriptor]:
    return {
        "tofu_init": ActionDescriptor(action_id="tofu_init", label="tofu init", side_effect_level="low"),
        "tofu_init_upgrade": ActionDescriptor(
            action_id="tofu_init_upgrade", label="tofu init -upgrade", side_effect_level="low"
        ),
        "tofu_plan": ActionDescriptor(action_id="tofu_plan", label="tofu plan", side_effect_level="low"),
        "tofu_apply": ActionDescriptor(action_id="tofu_apply", label="tofu apply", side_effect_level="low"),
        "tofu_destroy": ActionDescriptor(action_id="tofu_destroy", label="tofu destroy", side_effect_level="destructive"),
        "bootstrap_resolve_target": ActionDescriptor(
            action_id="bootstrap_resolve_target",
            label="resolve bootstrap target",
            side_effect_level="low",
        ),
        "bootstrap_execute_remote": ActionDescriptor(
            action_id="bootstrap_execute_remote",
            label="execute bootstrap remote",
            side_effect_level="high",
            deps=["bootstrap_resolve_target"],
        ),
        "verify_resolve_target": ActionDescriptor(
            action_id="verify_resolve_target",
            label="resolve verify target",
            side_effect_level="low",
            repair_hint="rerun failed node",
        ),
        "verify_execute_remote": ActionDescriptor(
            action_id="verify_execute_remote",
            label="execute verify remote",
            side_effect_level="high",
            deps=["verify_resolve_target"],
            repair_hint="rerun failed subtree",
        ),
    }


def build_graph(action: str) -> ActionGraph:
    definitions = _action_definitions()
    graph_specs: dict[str, tuple[str, ...]] = {
        "init": ("tofu_init",),
        "init-upgrade": ("tofu_init_upgrade",),
        "plan": ("tofu_plan",),
        "apply": ("tofu_apply",),
        "destroy": ("tofu_destroy",),
        "bootstrap": ("bootstrap_resolve_target", "bootstrap_execute_remote"),
        "verify": ("verify_resolve_target", "verify_execute_remote"),
        "up": ("tofu_init", "tofu_plan", "tofu_apply"),
        "deploy": (
            "tofu_init",
            "tofu_plan",
            "tofu_apply",
            "bootstrap_resolve_target",
            "bootstrap_execute_remote",
            "verify_resolve_target",
            "verify_execute_remote",
        ),
    }
    if action not in graph_specs:
        raise ValueError(f"unsupported action: {action}")

    actions: dict[str, ActionDescriptor] = {}
    for aid in graph_specs[action]:
        actions[aid] = definitions[aid]

    if action == "up":
        actions["tofu_plan"] = ActionDescriptor(
            action_id="tofu_plan", label="tofu plan", side_effect_level="low", deps=["tofu_init"]
        )
        actions["tofu_apply"] = ActionDescriptor(
            action_id="tofu_apply", label="tofu apply", side_effect_level="low", deps=["tofu_plan"]
        )

    if action == "deploy":
        actions["tofu_plan"] = ActionDescriptor(
            action_id="tofu_plan", label="tofu plan", side_effect_level="low", deps=["tofu_init"]
        )
        actions["tofu_apply"] = ActionDescriptor(
            action_id="tofu_apply", label="tofu apply", side_effect_level="low", deps=["tofu_plan"]
        )
        actions["bootstrap_resolve_target"] = ActionDescriptor(
            action_id="bootstrap_resolve_target",
            label="resolve bootstrap target",
            side_effect_level="low",
            deps=["tofu_apply"],
        )
        actions["bootstrap_execute_remote"] = ActionDescriptor(
            action_id="bootstrap_execute_remote",
            label="execute bootstrap remote",
            side_effect_level="high",
            deps=["bootstrap_resolve_target"],
        )
        actions["verify_resolve_target"] = ActionDescriptor(
            action_id="verify_resolve_target",
            label="resolve verify target",
            side_effect_level="low",
            deps=["bootstrap_execute_remote"],
            repair_hint="rerun failed node",
        )
        actions["verify_execute_remote"] = ActionDescriptor(
            action_id="verify_execute_remote",
            label="execute verify remote",
            side_effect_level="high",
            deps=["verify_resolve_target"],
            repair_hint="rerun failed subtree",
        )

    return ActionGraph(name=action, actions=actions)


def build_init_graph() -> ActionGraph:
    return build_graph("init")


def build_up_graph() -> ActionGraph:
    return build_graph("up")


def build_deploy_graph() -> ActionGraph:
    return build_graph("deploy")


def run_operational_graph(
    *,
    action: str,
    runner: Runner,
    repo_root: Path,
    provider_override: str | None,
    host_override_token: str | None = None,
    approve_destructive: str | None = None,
    confirmation_mode: str = "headless",
    audit_log: SessionAuditLog | None = None,
) -> EngineResult:
    provider = resolve_provider(provider_override=provider_override)
    selection = validate_init_environment(repo_root=repo_root, provider=provider)

    context: dict[str, Any] = {"provider": provider, "tf_dir": str(selection.tf_dir), "repo_root": str(repo_root)}
    if action in {"bootstrap", "verify", "deploy"}:
        context["bootstrap_config"] = validate_bootstrap_environment(repo_root=repo_root, provider=provider)

    if action == "destroy":
        preview = build_destroy_preview(repo_root=repo_root, provider=provider, tf_dir=selection.tf_dir, runner=runner)
        context["destroy_preview"] = {
            "provider": preview.provider,
            "tf_dir": str(preview.tf_dir),
            "backup_root": str(preview.backup_root),
            "backup_dir": str(preview.backup_dir),
            "state_files": [str(path) for path in preview.state_files],
            "state_file_count": len(preview.state_files),
            "safe_outputs": dict(preview.safe_outputs),
        }
        expected = f"DESTROY:{provider}"
        approved = approve_destructive == expected
        if audit_log is not None:
            audit_log.add_destructive_approval(
                action_id="tofu_destroy",
                approved=approved,
                approved_by="cli_flag" if confirmation_mode == "headless" else "operator",
                token_used=(expected if approved else None),
                flag_used="approve_destructive",
                details={
                    "provider": provider,
                    "tf_dir": str(selection.tf_dir),
                    "confirmation_mode": confirmation_mode,
                    "target_summary": {
                        "state_file_count": len(preview.state_files),
                        "state_files": [str(path) for path in preview.state_files],
                        "safe_outputs": dict(preview.safe_outputs),
                    },
                    "host_override_required": runner.mode == "host",
                    "host_override_approved": bool(
                        host_override_token and host_override_token.strip() == "I-ACK-HOST-OVERRIDE"
                    ),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        if not approved:
            raise PermissionError("destructive approval required: pass --approve-destructive DESTROY:<provider>")
        backup_path, backup_status = _backup_state_files(preview=preview)
        if audit_log is not None and audit_log.destructive_approvals:
            latest = audit_log.destructive_approvals[-1]
            latest.details["backup_path"] = backup_path
            latest.details["backup_status"] = backup_status

    graph = build_graph(action)
    engine = Engine(
        graph=graph,
        runner=runner,
        handler=OperationalActionHandler(),
        context=context,
        host_override_token=host_override_token,
        audit_log=audit_log,
    )
    return engine.run()


def execute_init_graph(
    *,
    runner: Runner,
    repo_root: Path,
    provider_override: str | None,
    host_override_token: str | None = None,
) -> EngineResult:
    return run_operational_graph(
        action="init",
        runner=runner,
        repo_root=repo_root,
        provider_override=provider_override,
        host_override_token=host_override_token,
    )


def run_init_graph(
    *,
    runner: Runner,
    repo_root: Path,
    provider_override: str | None,
    host_override_token: str | None = None,
) -> None:
    result = execute_init_graph(
        runner=runner,
        repo_root=repo_root,
        provider_override=provider_override,
        host_override_token=host_override_token,
    )
    if not result.completed:
        raise RuntimeError("init graph failed")


def build_monitoring_graph() -> ActionGraph:
    return ActionGraph(
        name="monitoring-local-readiness",
        actions={
            "runner_toolchain_readiness": ActionDescriptor(
                action_id="runner_toolchain_readiness",
                label="local runner/toolchain readiness",
                side_effect_level="none",
            ),
            "env_file_posture": ActionDescriptor(
                action_id="env_file_posture",
                label=".env/.env.example posture",
                side_effect_level="none",
            ),
            "provider_resolution": ActionDescriptor(
                action_id="provider_resolution",
                label="provider selection resolution",
                side_effect_level="none",
            ),
            "provider_directory": ActionDescriptor(
                action_id="provider_directory",
                label="provider directory existence",
                side_effect_level="none",
                deps=["provider_resolution"],
            ),
            "local_command_availability": ActionDescriptor(
                action_id="local_command_availability",
                label="local command availability",
                side_effect_level="none",
            ),
            "saved_plan_summary": ActionDescriptor(
                action_id="saved_plan_summary",
                label="saved plan presence/staleness summary",
                side_effect_level="none",
                deps=["provider_resolution"],
            ),
        },
    )


def _monitoring_check(probe_id: str, severity: str, summary: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "probe_id": probe_id,
        "severity": severity,
        "summary": summary,
        "evidence": evidence,
        "runner_mode": "local",
    }


def run_monitoring_graph(*, repo_root: Path, provider_override: str | None) -> dict[str, Any]:
    _ = build_monitoring_graph()
    checks: list[dict[str, Any]] = []

    python_path = shutil.which("python3")
    tofu_path = shutil.which("tofu")
    checks.append(
        _monitoring_check(
            "runner_toolchain_readiness",
            "ok" if python_path and tofu_path else "warn",
            "Local toolchain probes completed",
            {"python3": bool(python_path), "tofu": bool(tofu_path)},
        )
    )

    env_path = repo_root / ".env"
    env_example_path = repo_root / ".env.example"
    env_exists = env_path.is_file()
    env_example_exists = env_example_path.is_file()
    env_mode = stat.S_IMODE(env_path.stat().st_mode) if env_exists else None
    env_secure = env_mode is not None and (env_mode & 0o077) == 0
    checks.append(
        _monitoring_check(
            "env_file_posture",
            "ok" if env_exists and env_example_exists and env_secure else "warn",
            "Environment file posture evaluated",
            {
                ".env_present": env_exists,
                ".env_example_present": env_example_exists,
                ".env_mode": oct(env_mode) if env_mode is not None else None,
                ".env_secure": env_secure,
            },
        )
    )

    resolved_provider: str | None
    try:
        resolved_provider = resolve_provider(provider_override=provider_override)
        checks.append(
            _monitoring_check(
                "provider_resolution",
                "ok",
                "Provider resolved",
                {"provider": resolved_provider},
            )
        )
    except ValueError as exc:
        resolved_provider = None
        checks.append(
            _monitoring_check(
                "provider_resolution",
                "warn",
                "Provider resolution failed",
                {"error": str(exc)},
            )
        )

    provider_dir = repo_root / "opentofu" / "providers" / (resolved_provider or "")
    provider_dir_exists = provider_dir.is_dir() if resolved_provider else False
    checks.append(
        _monitoring_check(
            "provider_directory",
            "ok" if provider_dir_exists else "warn",
            "Provider directory checked",
            {
                "provider": resolved_provider,
                "path": str(provider_dir) if resolved_provider else None,
                "exists": provider_dir_exists,
            },
        )
    )

    commands = ["tofu", "ssh", "rsync"]
    command_paths = {command: shutil.which(command) for command in commands}
    checks.append(
        _monitoring_check(
            "local_command_availability",
            "ok" if all(command_paths.values()) else "warn",
            "Local command availability checked",
            {command: bool(path) for command, path in command_paths.items()},
        )
    )

    saved_plan_path = provider_dir / "tofuplan" if resolved_provider else None
    saved_plan_exists = bool(saved_plan_path and saved_plan_path.is_file())
    saved_plan_stale = False
    if saved_plan_exists and saved_plan_path is not None:
        age_s = max(0.0, datetime.now().timestamp() - saved_plan_path.stat().st_mtime)
        saved_plan_stale = age_s > (24 * 60 * 60)
    checks.append(
        _monitoring_check(
            "saved_plan_summary",
            "warn" if saved_plan_stale else "ok",
            "Saved plan checked without mutation",
            {
                "path": str(saved_plan_path) if saved_plan_path else None,
                "present": saved_plan_exists,
                "stale": saved_plan_stale,
            },
        )
    )

    return {
        "panel": "monitoring",
        "mode": "on-demand",
        "completed": True,
        "local_readiness": {"checks": checks},
        "remote_vps_probes": {
            "status": "follow-up",
            "summary": "Remote VPS probes not run in monitoring v1 local readiness slice.",
        },
    }
