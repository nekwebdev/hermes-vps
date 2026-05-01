from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from hermes_control_core import Runner, RunnerSelection
from hermes_vps_app.operational import VALID_PROVIDERS

REDACTION_MARKER = "***"


class PanelStartupState(str, Enum):
    DASHBOARD_READY = "dashboard_ready"
    CONFIGURATION_REQUIRED = "configuration_required"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StartupStep:
    name: str
    label: str
    status: str
    detail: str


@dataclass(frozen=True)
class RemediationScreen:
    title: str
    summary: str
    fix_steps: tuple[str, ...]
    execution_enabled: bool
    advanced_escape_hatch: str = (
        "Advanced unsafe environment: host override is a session-only break-glass escape hatch. "
        "Use it only after attempting the hermetic runner/local configuration fixes; every host run still "
        "requires the central host override token before execution."
    )

    def to_human_lines(self) -> list[str]:
        status = "enabled" if self.execution_enabled else "disabled"
        lines = [self.title, self.summary, f"Panel execution is {status}.", "Fix guidance:"]
        lines.extend(f"- {_redact(step)}" for step in self.fix_steps)
        lines.append(_redact(self.advanced_escape_hatch))
        return lines


@dataclass(frozen=True)
class PanelStartupResult:
    state: PanelStartupState
    steps: tuple[StartupStep, ...]
    runner_mode: str | None
    remediation: str
    provider: str | None = None
    remediation_screen: RemediationScreen | None = None

    def to_human_lines(self) -> list[str]:
        lines = [f"Panel startup: state={self.state.value}"]
        if self.runner_mode is not None:
            lines.append(f"Locked runner mode: {self.runner_mode}")
        if self.provider is not None:
            lines.append(f"Provider: {self.provider}")
        lines.append("Startup checks:")
        for step in self.steps:
            lines.append(f"- {step.name}: {step.status} - {_redact(step.detail)}")
        if self.remediation:
            lines.append(f"Remediation: {_redact(self.remediation)}")
        if self.remediation_screen is not None and self.state is PanelStartupState.BLOCKED:
            lines.append("Remediation screen:")
            lines.extend(self.remediation_screen.to_human_lines())
        return lines


class RunnerFactoryLike(Protocol):
    def get(self) -> Runner: ...


def evaluate_panel_startup(*, repo_root: Path, runner_factory: RunnerFactoryLike) -> PanelStartupResult:
    """Run the panel's launch-time gate exactly once.

    The panel startup path intentionally detects and locks the runner before local
    validation so the rendered app can always show the runner mode or an
    actionable runner remediation.
    """
    steps: list[StartupStep] = []
    runner_mode: str | None = None

    try:
        runner = runner_factory.get()
        runner_mode = runner.mode
    except Exception as exc:
        selection = getattr(exc, "selection", None)
        if isinstance(selection, RunnerSelection):
            runner_mode = selection.mode.value
        steps.append(
            StartupStep(
                name="runner_detection",
                label="Detect runner and lock mode",
                status="blocked",
                detail="Runner unavailable before panel startup.",
            )
        )
        return PanelStartupResult(
            state=PanelStartupState.BLOCKED,
            steps=tuple(steps),
            runner_mode=runner_mode,
            remediation=_runner_remediation(exc),
            remediation_screen=_runner_remediation_screen(exc),
        )

    steps.append(
        StartupStep(
            name="runner_detection",
            label="Detect runner and lock mode",
            status="ok",
            detail=f"runner locked: {runner_mode}",
        )
    )

    env_path = repo_root / ".env"
    if not env_path.exists():
        steps.append(
            StartupStep(
                name="local_validation",
                label="Validate local configuration",
                status="configuration_required",
                detail=".env is missing; configuration is required before operational workflows are enabled.",
            )
        )
        return PanelStartupResult(
            state=PanelStartupState.CONFIGURATION_REQUIRED,
            steps=tuple(steps),
            runner_mode=runner_mode,
            remediation="Create .env from .env.example, edit required values, then run chmod 600 .env.",
        )

    try:
        env_values = _read_env_values(env_path)
        provider = env_values.get("TF_VAR_cloud_provider", "").strip()
        if provider not in VALID_PROVIDERS:
            raise PanelStartupBlocked("provider must be hetzner or linode")
        tf_dir = repo_root / "opentofu" / "providers" / provider
        if not tf_dir.is_dir():
            raise PanelStartupBlocked(f"OpenTofu provider directory not found: opentofu/providers/{provider}")
    except PanelStartupBlocked as exc:
        steps.append(
            StartupStep(
                name="local_validation",
                label="Validate local configuration",
                status="blocked",
                detail=str(exc),
            )
        )
        return PanelStartupResult(
            state=PanelStartupState.BLOCKED,
            steps=tuple(steps),
            runner_mode=runner_mode,
            remediation=_local_remediation(str(exc)),
            remediation_screen=_local_remediation_screen(str(exc)),
        )

    steps.append(
        StartupStep(
            name="local_validation",
            label="Validate local configuration",
            status="ok",
            detail=f"provider={provider}; {REDACTION_MARKER} secrets redacted; provider directory present",
        )
    )
    return PanelStartupResult(
        state=PanelStartupState.DASHBOARD_READY,
        steps=tuple(steps),
        runner_mode=runner_mode,
        remediation="Panel is ready.",
        provider=provider,
    )


class PanelStartupBlocked(ValueError):
    pass


def _read_env_values(env_path: Path) -> dict[str, str]:
    try:
        if not env_path.is_file():
            raise PanelStartupBlocked(".env is not a regular file")
        env_mode = stat.S_IMODE(env_path.stat().st_mode)
        if env_mode & 0o077:
            raise PanelStartupBlocked(".env permissions are too broad; expected mode 600")
        if not os.access(env_path, os.R_OK):
            raise PanelStartupBlocked(".env is not readable")
        values: dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
        return values
    except OSError as exc:
        raise PanelStartupBlocked(".env is not readable") from exc


def _runner_remediation(exc: BaseException) -> str:
    message = str(exc).lower()
    if "docker" in message:
        return "Docker fallback unavailable. Start Docker or activate/install nix/direnv, then restart just panel."
    return "Runner unavailable. Activate direnv+nix shell, install nix, or install Docker fallback, then restart just panel."


def _runner_remediation_screen(exc: BaseException) -> RemediationScreen:
    message = str(exc).lower()
    if "docker" in message:
        return RemediationScreen(
            title="Docker fallback unavailable",
            summary="The panel detected Docker fallback mode, but Docker cannot execute the hermetic nix runner.",
            execution_enabled=False,
            fix_steps=(
                "Run `docker info` and start Docker if the daemon is stopped.",
                "Ensure the current user can run Docker without a permission error.",
                "Preferred fix: run `direnv allow` or `nix develop --impure` so the panel uses a hermetic nix runner without Docker fallback.",
                "If Docker is missing, install Docker or install/activate nix+direnv, then restart `just panel`.",
            ),
        )
    return RemediationScreen(
        title="Runner unavailable",
        summary="No hermetic runner is available, so panel execution is blocked before any workflow can run.",
        execution_enabled=False,
        fix_steps=(
            "Preferred fix: run `direnv allow` in the repository and restart `just panel`.",
            "Alternative fix: run `nix develop --impure` and launch the panel from that shell.",
            "Fallback fix: install Docker and ensure `docker info` succeeds, then restart `just panel`.",
        ),
    )


def _local_remediation(message: str) -> str:
    lowered = message.lower()
    if "permissions" in lowered:
        return "Fix .env permissions with: chmod 600 .env"
    if "not readable" in lowered:
        return "Make .env readable by the current user and keep permissions at mode 600."
    if "provider must" in lowered:
        return "Set TF_VAR_cloud_provider in .env to hetzner or linode."
    if "provider directory" in lowered:
        suffix = message.split(":", 1)[-1].strip()
        return f"Create or restore the provider directory: {suffix}"
    return "Fix local panel startup validation and restart just panel."


def _local_remediation_screen(message: str) -> RemediationScreen:
    lowered = message.lower()
    if "permissions" in lowered:
        return RemediationScreen(
            title="Unsafe .env permissions",
            summary="The .env file is readable by users other than the current owner.",
            execution_enabled=False,
            fix_steps=(
                "Run `chmod 600 .env` from the repository root.",
                "Restart `just panel` after correcting permissions.",
            ),
        )
    if "not readable" in lowered:
        return RemediationScreen(
            title="Unreadable .env",
            summary="The current user cannot read .env safely.",
            execution_enabled=False,
            fix_steps=(
                "Make .env readable by the current user only.",
                "Run `chmod 600 .env` and restart `just panel`.",
            ),
        )
    if "provider must" in lowered:
        return RemediationScreen(
            title="Invalid provider",
            summary="TF_VAR_cloud_provider must select a supported local provider before workflows are enabled.",
            execution_enabled=False,
            fix_steps=(
                "Set `TF_VAR_cloud_provider=hetzner` or `TF_VAR_cloud_provider=linode` in .env.",
                "Ensure the matching opentofu/providers/<provider> directory exists.",
                "Restart `just panel` after saving .env.",
            ),
        )
    if "provider directory" in lowered:
        suffix = message.split(":", 1)[-1].strip()
        return RemediationScreen(
            title="Missing provider directory",
            summary=f"The selected provider directory is missing: {suffix}",
            execution_enabled=False,
            fix_steps=(
                f"Restore the provider files or run `mkdir -p {suffix}` if scaffolding a new provider directory.",
                "Confirm .env selects the intended provider, then restart `just panel`.",
            ),
        )
    return RemediationScreen(
        title="Startup validation blocked",
        summary="Local startup validation failed.",
        execution_enabled=False,
        fix_steps=("Fix the reported local validation issue and restart `just panel`.",),
    )


def _redact(value: str) -> str:
    # Startup rendering should never echo .env values or runner exception details.
    return value.replace("super-secret", REDACTION_MARKER)
