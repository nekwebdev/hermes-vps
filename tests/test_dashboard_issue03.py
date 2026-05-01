# pyright: reportAny=false
from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from hermes_vps_app.operator_snapshot import (
    EnvFileSnapshot,
    EnvKeySnapshot,
    LocalHealthSummary,
    OperatorSnapshot,
    OpenTofuSnapshot,
    PrimaryAction,
    ProviderDirectorySnapshot,
    ProviderSnapshot,
    RemoteKnownStatus,
    RemoteStatusSnapshot,
    RemoteStatusState,
)
from hermes_vps_app.panel_startup import PanelStartupResult, PanelStartupState, StartupStep


def _startup(state: PanelStartupState) -> PanelStartupResult:
    return PanelStartupResult(
        state=state,
        steps=(StartupStep(name="runner_detection", label="runner", status="ok", detail="runner locked"),),
        runner_mode="host",
        remediation="ready",
        provider="hetzner" if state is PanelStartupState.DASHBOARD_READY else None,
    )


def _snapshot(primary_action: PrimaryAction = PrimaryAction.MONITOR) -> OperatorSnapshot:
    unknown = RemoteKnownStatus(state=RemoteStatusState.UNKNOWN, status=None, recorded_at=None, detail="not checked locally")
    return OperatorSnapshot(
        repo_root=Path("/tmp/repo"),
        env_file=EnvFileSnapshot(exists=True, readable=True, mode="600", key_count=1, keys={"TF_VAR_cloud_provider": EnvKeySnapshot(True, False)}),
        provider=ProviderSnapshot(selection="hetzner", valid=True, detail="provider selected"),
        runner_mode="host",
        provider_directory=ProviderDirectorySnapshot(path="opentofu/providers/hetzner", exists=True, detail="present"),
        opentofu=OpenTofuSnapshot(state_present=True, output_present=True, plan_present=False, state_files=("opentofu/providers/hetzner/terraform.tfstate",), output_keys=("public_ipv4",)),
        remote_status=RemoteStatusSnapshot(bootstrap=unknown, verify=unknown, monitoring=unknown),
        local_health=LocalHealthSummary(status="ok", checks=(".env present",), detail="local checks ok"),
        primary_action=primary_action,
    )


def test_dashboard_shell_routes_startup_to_snapshot_without_remote_monitoring_checks() -> None:
    from hermes_vps_app.panel_shell import ControlPanelShell

    shell = ControlPanelShell(startup_result=_startup(PanelStartupState.DASHBOARD_READY))
    with (
        patch("hermes_vps_app.panel_shell.build_operator_snapshot", return_value=_snapshot()) as snapshot_builder,
        patch("hermes_vps_app.operational.run_monitoring_graph") as remote_monitoring,
    ):
        dashboard = shell.dashboard(repo_root=Path("/tmp/repo"))

    snapshot_builder.assert_called_once()
    remote_monitoring.assert_not_called()
    assert dashboard["primary_action"] == "Monitor"
    panel_cards = cast(list[dict[str, str]], dashboard["panel_cards"])
    assert [card["title"] for card in panel_cards] == [
        "Configuration",
        "Deployment",
        "Maintenance",
        "Monitoring",
    ]
    assert "host override" in str(dashboard["safety_footer"]).lower()
    assert "not checked locally" in str(dashboard["recent_status"])


def test_panel_entrypoint_defaults_to_deployment_panel_not_dashboard() -> None:
    from hermes_vps_app import panel_entrypoint

    class ShellSpy:
        startup_result: PanelStartupResult
        initial_panel: str

        def __init__(self, **kwargs: Any) -> None:
            self.startup_result = cast(PanelStartupResult, kwargs["startup_result"])
            self.initial_panel = str(kwargs["initial_panel"])

        def initial_state_label(self) -> str:
            return "dashboard_ready"

        def deployment_actions(self) -> list[Any]:
            return []

        def deployment_advanced_actions(self) -> list[Any]:
            return []

    stdout = io.StringIO()
    with (
        patch.object(panel_entrypoint, "evaluate_panel_startup", return_value=_startup(PanelStartupState.DASHBOARD_READY)),
        patch.object(panel_entrypoint, "ControlPanelShell", ShellSpy),
        contextlib.redirect_stdout(stdout),
    ):
        code = panel_entrypoint.main(["--repo-root", ".", "--headless-render"])

    output = stdout.getvalue()
    assert code == 0
    assert "Initial panel: deployment" in output
    assert "Primary workflow: deploy = init -> plan -> apply -> bootstrap -> verify" in output
    assert "Dashboard:" not in output
