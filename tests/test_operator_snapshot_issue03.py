# pyright: reportUnknownMemberType=false, reportUnusedCallResult=false
from __future__ import annotations

import os
import stat
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hermes_vps_app.operator_snapshot import (
    PrimaryAction,
    RemoteStatusState,
    build_operator_snapshot,
    select_primary_action,
)
from hermes_vps_app.panel_startup import PanelStartupResult, PanelStartupState, StartupStep


def _startup(
    state: PanelStartupState,
    *,
    provider: str | None = "hetzner",
    runner_mode: str | None = "direnv_nix",
) -> PanelStartupResult:
    return PanelStartupResult(
        state=state,
        steps=(StartupStep(name="runner_detection", label="runner", status="ok", detail="runner locked"),),
        runner_mode=runner_mode,
        remediation="ready" if state is PanelStartupState.DASHBOARD_READY else "fix config",
        provider=provider if state is PanelStartupState.DASHBOARD_READY else None,
    )


def _ready_repo(root: Path) -> Path:
    env = root / ".env"
    env.write_text(
        "\n".join(
            [
                "TF_VAR_cloud_provider=hetzner",
                "TF_VAR_server_location=fsn1",
                "TF_VAR_server_type=cpx11",
                "TF_VAR_server_image=debian-13",
                "TF_VAR_hostname=hermes",
                "TF_VAR_admin_username=admin",
                "TF_VAR_admin_group=admin",
                "BOOTSTRAP_SSH_PRIVATE_KEY_PATH=/tmp/hermes-key",
                "BOOTSTRAP_SSH_PORT=22",
                "TF_VAR_hermes_provider=openrouter",
                "TF_VAR_hermes_model=anthropic/claude-sonnet-4",
                "HERMES_AGENT_VERSION=1.2.3",
                "HERMES_API_KEY=super-secret",
                "TELEGRAM_BOT_TOKEN=bot-secret",
                "TELEGRAM_ALLOWLIST_IDS=123",
                "",
            ]
        ),
        encoding="utf-8",
    )
    os.chmod(env, stat.S_IRUSR | stat.S_IWUSR)
    tf_dir = root / "opentofu" / "providers" / "hetzner"
    tf_dir.mkdir(parents=True)
    return tf_dir


def _write_state(tf_dir: Path) -> None:
    (tf_dir / "terraform.tfstate").write_text(
        '{"version": 4, "outputs": {"public_ipv4": {"value": "203.0.113.10"}}}\n',
        encoding="utf-8",
    )


def _write_status(root: Path, *, status: str, recorded_at: datetime | None = None) -> None:
    when = recorded_at or datetime.now(UTC)
    status_dir = root / ".hermes-vps"
    status_dir.mkdir()
    status_json = (
        "{"
        f'"bootstrap": {{"status": "{status}", "recorded_at": "{when.isoformat()}"}}, '
        f'"verify": {{"status": "{status}", "recorded_at": "{when.isoformat()}"}}, '
        f'"monitoring": {{"status": "{status}", "recorded_at": "{when.isoformat()}"}}'
        "}\n"
    )
    (status_dir / "operator-status.json").write_text(status_json, encoding="utf-8")


def test_snapshot_is_non_secret_and_reports_local_structure_state_outputs_and_unknown_remote_status() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tf_dir = _ready_repo(root)
        _write_state(tf_dir)

        snapshot = build_operator_snapshot(repo_root=root, startup_result=_startup(PanelStartupState.DASHBOARD_READY))

    assert snapshot.env_file.exists is True
    assert snapshot.env_file.mode == "600"
    assert snapshot.env_file.keys["HERMES_API_KEY"].present is True
    assert snapshot.env_file.keys["HERMES_API_KEY"].secret is True
    assert "super-secret" not in str(snapshot.to_dict())
    assert snapshot.provider.selection == "hetzner"
    assert snapshot.provider_directory.exists is True
    assert snapshot.opentofu.state_present is True
    assert snapshot.opentofu.output_present is True
    assert snapshot.remote_status.bootstrap.state is RemoteStatusState.UNKNOWN
    assert snapshot.remote_status.verify.state is RemoteStatusState.UNKNOWN
    assert "not checked locally" in snapshot.remote_status.verify.detail
    assert snapshot.local_health.status == "ok"


def test_primary_action_selection_rules_cover_configure_fix_deploy_bootstrap_monitor_fix_and_monitor() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        missing_env = build_operator_snapshot(
            repo_root=Path(tmp),
            startup_result=_startup(PanelStartupState.CONFIGURATION_REQUIRED, provider=None),
        )
    assert select_primary_action(missing_env) is PrimaryAction.CONFIGURE

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _ready_repo(root)
        blocked = build_operator_snapshot(repo_root=root, startup_result=_startup(PanelStartupState.BLOCKED, provider=None))
    assert select_primary_action(blocked) is PrimaryAction.FIX_CONFIGURATION

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _ready_repo(root)
        deploy = build_operator_snapshot(repo_root=root, startup_result=_startup(PanelStartupState.DASHBOARD_READY))
    assert select_primary_action(deploy) is PrimaryAction.DEPLOY

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tf_dir = _ready_repo(root)
        _write_state(tf_dir)
        bootstrap = build_operator_snapshot(repo_root=root, startup_result=_startup(PanelStartupState.DASHBOARD_READY))
    assert select_primary_action(bootstrap) is PrimaryAction.BOOTSTRAP_VERIFY

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tf_dir = _ready_repo(root)
        _write_state(tf_dir)
        _write_status(root, status="failed")
        monitor_fix = build_operator_snapshot(repo_root=root, startup_result=_startup(PanelStartupState.DASHBOARD_READY))
    assert select_primary_action(monitor_fix) is PrimaryAction.MONITOR_FIX

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tf_dir = _ready_repo(root)
        _write_state(tf_dir)
        _write_status(root, status="ok")
        monitor = build_operator_snapshot(repo_root=root, startup_result=_startup(PanelStartupState.DASHBOARD_READY))
    assert select_primary_action(monitor) is PrimaryAction.MONITOR


def test_stale_remote_status_is_explicit_and_routes_to_monitor_fix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tf_dir = _ready_repo(root)
        _write_state(tf_dir)
        _write_status(root, status="ok", recorded_at=datetime.now(UTC) - timedelta(days=3))

        snapshot = build_operator_snapshot(repo_root=root, startup_result=_startup(PanelStartupState.DASHBOARD_READY))

    assert snapshot.remote_status.verify.state is RemoteStatusState.STALE
    assert snapshot.primary_action is PrimaryAction.MONITOR_FIX
