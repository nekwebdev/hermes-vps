# pyright: reportAny=false
from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hermes_vps_app.panel_startup import PanelStartupResult, PanelStartupState, StartupStep


def _startup_result(state: PanelStartupState) -> PanelStartupResult:
    return PanelStartupResult(
        state=state,
        steps=(
            StartupStep(
                name="runner_detection",
                label="Detect runner and lock mode",
                status="ok",
                detail="runner locked: host",
            ),
        ),
        runner_mode="host",
        remediation="ready" if state is PanelStartupState.DASHBOARD_READY else "configure .env",
        provider="hetzner" if state is PanelStartupState.DASHBOARD_READY else None,
    )


def test_panel_entrypoint_accepts_configuration_initial_panel_and_passes_it_to_shell() -> None:
    from hermes_vps_app import panel_entrypoint

    created_shells: list[Any] = []
    created_apps: list[Any] = []

    class ShellSpy:
        def __init__(self, **kwargs: Any) -> None:
            created_shells.append(kwargs)

        def initial_state_label(self) -> str:
            return "configuration_reconfigure"

    class AppSpy:
        def __init__(self, **kwargs: Any) -> None:
            created_apps.append(kwargs)

        def run(self) -> None:
            return None

    stdout = io.StringIO()
    with (
        patch.object(panel_entrypoint, "evaluate_panel_startup", return_value=_startup_result(PanelStartupState.DASHBOARD_READY)),
        patch.object(panel_entrypoint, "ControlPanelShell", ShellSpy),
        patch.object(panel_entrypoint, "HermesControlPanelApp", AppSpy),
        contextlib.redirect_stdout(stdout),
    ):
        code = panel_entrypoint.main(["--repo-root", ".", "--initial-panel", "configuration"])

    assert code == 0
    assert created_shells == [
        {
            "startup_result": _startup_result(PanelStartupState.DASHBOARD_READY),
            "initial_panel": "configuration",
        }
    ]
    assert created_apps == [
        {
            "shell": created_apps[0]["shell"],
            "repo_root": Path(".").resolve(),
            "startup_result": _startup_result(PanelStartupState.DASHBOARD_READY),
            "initial_panel": "configuration",
        }
    ]
    assert created_apps[0]["shell"].initial_state_label() == "configuration_reconfigure"
    output = stdout.getvalue()
    assert output == ""


def test_configuration_deep_link_missing_env_keeps_configuration_required_state() -> None:
    from hermes_vps_app.panel_shell import ControlPanelShell

    shell = ControlPanelShell(
        startup_result=_startup_result(PanelStartupState.CONFIGURATION_REQUIRED),
        initial_panel="configuration",
    )

    assert shell.initial_panel == "configuration"
    assert shell.initial_state_label() == "configuration_required"


def test_configuration_deep_link_valid_env_lands_on_reconfigure_state() -> None:
    from hermes_vps_app.panel_shell import ControlPanelShell

    shell = ControlPanelShell(
        startup_result=_startup_result(PanelStartupState.DASHBOARD_READY),
        initial_panel="configuration",
    )

    assert shell.initial_panel == "configuration"
    assert shell.initial_state_label() == "configuration_reconfigure"


def test_just_panel_and_configure_use_same_panel_entrypoint_with_different_initial_targets() -> None:
    justfile = (Path(__file__).resolve().parents[1] / "Justfile").read_text(encoding="utf-8")

    panel_recipe = justfile.split("panel:", 1)[1].split("\n#", 1)[0]
    configure_recipe = justfile.split("configure:", 1)[1].split("\n#", 1)[0]

    assert "python3 -m hermes_vps_app.panel_entrypoint" in panel_recipe
    assert "python3 -m hermes_vps_app.panel_entrypoint" in configure_recipe
    assert "--initial-panel configuration" not in panel_recipe
    assert "--initial-panel configuration" in configure_recipe
    assert "scripts.configure_tui" not in configure_recipe


def test_panel_entrypoint_initial_panel_choices_exclude_dashboard() -> None:
    from hermes_vps_app import panel_entrypoint

    parser = panel_entrypoint.build_parser()
    args = parser.parse_args([])
    assert args.initial_panel == "deployment"

    with contextlib.redirect_stderr(io.StringIO()):
        try:
            _ = parser.parse_args(["--initial-panel", "dashboard"])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError("dashboard should not be an accepted initial panel")
