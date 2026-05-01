# pyright: reportImplicitOverride=false, reportUnusedCallResult=false, reportAny=false
from __future__ import annotations

import contextlib
import io
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, final
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


@final
class FactoryStub:
    def __init__(self, runner: Runner | None = None, exc: BaseException | None = None) -> None:
        self.runner = runner or RunnerStub()
        self.exc = exc

    def get(self) -> Runner:
        if self.exc is not None:
            raise self.exc
        return self.runner


def _write_env(root: Path, provider: str = "hetzner", mode: int = 0o600) -> None:
    (root / ".env").write_text(f"TF_VAR_cloud_provider={provider}\nSECRET_TOKEN=super-secret\n", encoding="utf-8")
    os.chmod(root / ".env", mode)


def test_blocking_remediation_screen_has_exact_local_fix_guidance_for_all_blockers() -> None:
    from hermes_control_core import RunnerDetectionError
    from hermes_vps_app.panel_startup import PanelStartupState, evaluate_panel_startup

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_env(root, mode=0o640)
        unsafe = evaluate_panel_startup(repo_root=root, runner_factory=FactoryStub())

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_env(root, provider="digitalocean")
        invalid_provider = evaluate_panel_startup(repo_root=root, runner_factory=FactoryStub())

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_env(root, provider="linode")
        missing_dir = evaluate_panel_startup(repo_root=root, runner_factory=FactoryStub())

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runner_failure = evaluate_panel_startup(
            repo_root=root,
            runner_factory=FactoryStub(exc=RunnerDetectionError("No valid runner detected; secret=super-secret")),
        )

    for result in (unsafe, invalid_provider, missing_dir, runner_failure):
        assert result.state is PanelStartupState.BLOCKED
        screen = result.remediation_screen
        assert screen is not None
        assert screen.execution_enabled is False
        rendered = "\n".join(screen.to_human_lines())
        assert "super-secret" not in rendered
        assert "advanced unsafe environment" in rendered.lower()
        assert "host override" in rendered.lower()

    unsafe_screen = unsafe.remediation_screen
    invalid_provider_screen = invalid_provider.remediation_screen
    missing_dir_screen = missing_dir.remediation_screen
    runner_failure_screen = runner_failure.remediation_screen
    assert unsafe_screen is not None
    assert invalid_provider_screen is not None
    assert missing_dir_screen is not None
    assert runner_failure_screen is not None
    assert "chmod 600 .env" in "\n".join(unsafe_screen.to_human_lines())
    assert "TF_VAR_cloud_provider=hetzner" in "\n".join(invalid_provider_screen.to_human_lines())
    assert "TF_VAR_cloud_provider=linode" in "\n".join(invalid_provider_screen.to_human_lines())
    assert "mkdir -p opentofu/providers/linode" in "\n".join(missing_dir_screen.to_human_lines())
    runner_screen = "\n".join(runner_failure_screen.to_human_lines())
    assert "direnv allow" in runner_screen
    assert "nix develop" in runner_screen
    assert "install Docker" in runner_screen


def test_docker_fallback_unavailable_screen_guides_install_and_prevents_execution() -> None:
    from hermes_control_core import RunnerDetectionError, RunnerSelection, DetectionMode
    from hermes_vps_app.panel_startup import evaluate_panel_startup

    selection = RunnerSelection(
        mode=DetectionMode.DOCKER_NIX,
        reason="docker command exists but daemon is stopped",
        guidance="Start Docker daemon or install/activate nix/direnv.",
    )
    result = evaluate_panel_startup(
        repo_root=Path("/tmp/nonexistent-hermes-test"),
        runner_factory=FactoryStub(
            exc=RunnerDetectionError("Docker nix fallback is unavailable before graph execution", selection=selection)
        ),
    )

    assert result.runner_mode == "docker_nix"
    screen = result.remediation_screen
    assert screen is not None
    assert screen.execution_enabled is False
    rendered = "\n".join(screen.to_human_lines())
    assert "Docker fallback unavailable" in rendered
    assert "docker info" in rendered
    assert "start Docker" in rendered or "Start Docker" in rendered
    assert "panel execution is disabled" in rendered.lower()


def test_host_override_ux_is_advanced_explicit_session_only_and_redacts_token() -> None:
    from hermes_vps_app.panel_shell import ControlPanelShell, HostOverrideError

    shell = ControlPanelShell()
    closed = shell.host_override_advanced_path()
    assert closed["visible_by_default"] is False
    assert "unsafe" in str(closed["label"]).lower()

    denied_disabled = shell.request_host_override(enable=False, reason="break glass")
    assert denied_disabled["approved"] is False
    assert "explicitly enable" in str(denied_disabled["message"])

    denied_reason = shell.request_host_override(enable=True, reason="   ")
    assert denied_reason["approved"] is False
    assert "reason" in str(denied_reason["message"]).lower()

    session = shell.request_host_override(enable=True, reason="break glass maintenance")
    assert session == {
        "approved": True,
        "runner_mode": "host",
        "override_reason": "break glass maintenance",
        "scope": "per-launch",
        "requires_token": True,
    }
    assert "I-ACK-HOST-OVERRIDE" not in str(session)

    fresh_shell = ControlPanelShell()
    assert fresh_shell.host_override_session() is None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_env(root)
        (root / "opentofu/providers/hetzner").mkdir(parents=True)
        with patch("hermes_vps_app.panel_shell.operational.execute_init_graph") as execute_init:
            execute_init.side_effect = PermissionError("host override token denied")
            try:
                shell.run_init_status(
                    runner=RunnerStub(mode="host"),
                    repo_root=root,
                    provider_override="hetzner",
                    host_override_token=None,
                    override_reason="break glass maintenance",
                )
            except PermissionError:
                pass
            else:  # pragma: no cover - defensive
                raise AssertionError("host override run without token must be rejected by central pre-run gate")

    execute_init.assert_called_once()
    assert execute_init.call_args.kwargs["host_override_token"] is None
    assert execute_init.call_args.kwargs["override_reason"] == "break glass maintenance"

    try:
        shell.render_host_override_token("BAD-TOKEN-secret-value")
    except HostOverrideError as exc:
        assert "BAD-TOKEN-secret-value" not in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("rendering host override token should be forbidden")


def test_panel_entrypoint_requires_advanced_unsafe_path_for_host_override_flags() -> None:
    from hermes_vps_app import panel_entrypoint

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        rc = panel_entrypoint.main(["--repo-root", ".", "--allow-host-override", "--override-reason", "debug"])

    assert rc == 2
    combined = stdout.getvalue() + stderr.getvalue()
    assert "--advanced-unsafe-environment" in combined
    assert "host override" in combined.lower()

    class ShellSpy:
        def __init__(self, **_: Any) -> None:
            pass

        def initial_state_label(self) -> str:
            return "dashboard_ready"

        def deployment_actions(self) -> list[Any]:
            return []

        def deployment_advanced_actions(self) -> list[Any]:
            return []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_env(root)
        (root / "opentofu/providers/hetzner").mkdir(parents=True)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(panel_entrypoint, "ControlPanelShell", ShellSpy),
            patch("hermes_vps_app.panel_entrypoint.RunnerFactory.get", return_value=RunnerStub(mode="host")),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            rc = panel_entrypoint.main(
                [
                    "--repo-root",
                    str(root),
                    "--headless-render",
                    "--advanced-unsafe-environment",
                    "--allow-host-override",
                    "--override-reason",
                    "debug",
                ]
            )

    assert rc == 0
    assert "Host override: enabled for this launch only" in stdout.getvalue()
    assert "debug" in stdout.getvalue()
