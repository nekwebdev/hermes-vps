# pyright: reportImplicitOverride=false, reportUnannotatedClassAttribute=false, reportUnusedCallResult=false
from __future__ import annotations

import contextlib
import io
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hermes_control_core import RunRequest, RunResult, Runner
from hermes_control_core.interfaces import RunnerMode


@dataclass
class RunnerStub(Runner):
    mode: RunnerMode = "direnv_nix"

    def run(self, request: RunRequest) -> RunResult:
        return RunResult(
            exit_code=0,
            stdout="ok",
            stderr="",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            runner_mode=self.mode,
            redactions_applied=True,
        )


class CountingRunnerFactory:
    def __init__(self, runner: Runner | None = None, exc: BaseException | None = None) -> None:
        self.runner = runner or RunnerStub()
        self.exc = exc
        self.calls = 0

    def get(self) -> Runner:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.runner


def test_startup_missing_env_is_configuration_required_after_single_runner_detection() -> None:
    from hermes_vps_app.panel_startup import PanelStartupState, evaluate_panel_startup

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        factory = CountingRunnerFactory(RunnerStub(mode="nix_develop"))

        result = evaluate_panel_startup(repo_root=root, runner_factory=factory)

    assert factory.calls == 1
    assert result.state is PanelStartupState.CONFIGURATION_REQUIRED
    assert result.runner_mode == "nix_develop"
    assert [step.name for step in result.steps] == ["runner_detection", "local_validation"]
    assert result.steps[0].status == "ok"
    assert result.steps[1].status == "configuration_required"
    assert ".env" in result.remediation


def test_startup_dashboard_ready_when_env_provider_directory_and_runner_are_valid() -> None:
    from hermes_vps_app.panel_startup import PanelStartupState, evaluate_panel_startup

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\nHERMES_API_KEY=super-secret\n", encoding="utf-8")
        os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
        (root / "opentofu/providers/hetzner").mkdir(parents=True)
        factory = CountingRunnerFactory(RunnerStub(mode="direnv_nix"))

        result = evaluate_panel_startup(repo_root=root, runner_factory=factory)

    assert factory.calls == 1
    assert result.state is PanelStartupState.DASHBOARD_READY
    assert result.runner_mode == "direnv_nix"
    assert all(step.status == "ok" for step in result.steps)
    rendered = "\n".join(result.to_human_lines())
    assert "super-secret" not in rendered
    assert "***" in rendered


def test_startup_blocks_on_unsafe_env_invalid_provider_missing_provider_dir_and_runner_failure() -> None:
    from hermes_control_core import RunnerDetectionError
    from hermes_vps_app.panel_startup import PanelStartupState, evaluate_panel_startup

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
        os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        unsafe = evaluate_panel_startup(repo_root=root, runner_factory=CountingRunnerFactory())

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
        os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
        with patch("hermes_vps_app.panel_startup.os.access", return_value=False):
            unreadable = evaluate_panel_startup(repo_root=root, runner_factory=CountingRunnerFactory())

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("TF_VAR_cloud_provider=digitalocean\n", encoding="utf-8")
        os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
        invalid_provider = evaluate_panel_startup(repo_root=root, runner_factory=CountingRunnerFactory())

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("TF_VAR_cloud_provider=linode\n", encoding="utf-8")
        os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
        missing_dir = evaluate_panel_startup(repo_root=root, runner_factory=CountingRunnerFactory())

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runner_failure = evaluate_panel_startup(
            repo_root=root,
            runner_factory=CountingRunnerFactory(exc=RunnerDetectionError("no runner for token abc123")),
        )

    assert unsafe.state is PanelStartupState.BLOCKED
    assert "chmod 600 .env" in unsafe.remediation
    assert unreadable.state is PanelStartupState.BLOCKED
    assert "readable" in unreadable.remediation
    assert invalid_provider.state is PanelStartupState.BLOCKED
    assert "hetzner or linode" in invalid_provider.remediation
    assert missing_dir.state is PanelStartupState.BLOCKED
    assert "opentofu/providers/linode" in missing_dir.remediation
    assert runner_failure.state is PanelStartupState.BLOCKED
    assert runner_failure.runner_mode is None
    assert "runner" in runner_failure.remediation.lower()
    assert "abc123" not in "\n".join(runner_failure.to_human_lines())


def test_panel_entrypoint_renders_visible_startup_gate_and_exit_codes() -> None:
    from hermes_vps_app import panel_entrypoint
    from hermes_vps_app.panel_startup import PanelStartupResult, PanelStartupState, StartupStep

    def fake_evaluate(**_: Any) -> PanelStartupResult:
        return PanelStartupResult(
            state=PanelStartupState.CONFIGURATION_REQUIRED,
            steps=(
                StartupStep(name="runner_detection", label="Detect runner and lock mode", status="ok", detail="runner locked: host"),
                StartupStep(
                    name="local_validation",
                    label="Validate local configuration",
                    status="configuration_required",
                    detail=".env missing",
                ),
            ),
            runner_mode="host",
            remediation="Create .env from .env.example and run chmod 600 .env.",
        )

    stdout = io.StringIO()
    with patch.object(panel_entrypoint, "evaluate_panel_startup", side_effect=fake_evaluate), contextlib.redirect_stdout(stdout):
        code = panel_entrypoint.main(["--repo-root", ".", "--headless-render"])

    output = stdout.getvalue()
    assert code == 0
    assert "Panel startup" in output
    assert "runner_detection" in output
    assert "local_validation" in output
    assert "configuration_required" in output
    assert "host" in output


def test_panel_entrypoint_launches_textual_app_by_default() -> None:
    from hermes_vps_app import panel_entrypoint
    from hermes_vps_app.panel_startup import PanelStartupResult, PanelStartupState, StartupStep

    result = PanelStartupResult(
        state=PanelStartupState.CONFIGURATION_REQUIRED,
        steps=(StartupStep(name="runner_detection", label="Detect runner and lock mode", status="ok", detail="runner locked: host"),),
        runner_mode="host",
        remediation="Create .env.",
    )

    with (
        patch.object(panel_entrypoint, "evaluate_panel_startup", return_value=result),
        patch.object(panel_entrypoint.HermesControlPanelApp, "run", return_value=None) as app_run,
    ):
        code = panel_entrypoint.main(["--repo-root", "."])

    assert code == 0
    app_run.assert_called_once_with()


def test_cli_panel_subcommand_delegates_to_panel_entrypoint() -> None:
    from hermes_vps_app import cli

    stdout = io.StringIO()
    with patch("hermes_vps_app.panel_entrypoint.main", return_value=0) as panel_main, contextlib.redirect_stdout(stdout):
        code = cli.main(["panel", "--repo-root", "."])

    assert code == 0
    panel_main.assert_called_once_with(["--repo-root", "."])


def test_just_panel_wires_to_python_panel_entrypoint_not_configure_tui() -> None:
    justfile = (Path(__file__).resolve().parents[1] / "Justfile").read_text(encoding="utf-8")

    assert "panel:" in justfile
    panel_recipe = justfile.split("panel:", 1)[1].split("\n#", 1)[0]
    assert "python3 -m hermes_vps_app.panel_entrypoint" in panel_recipe
    assert "scripts.configure_tui" not in panel_recipe
