from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol


RunnerMode = Literal["direnv_nix", "nix_develop", "docker_nix", "host"]
SideEffectLevel = Literal["none", "low", "high", "destructive"]
Severity = Literal["ok", "warn", "crit"]


class EnvUnsetType(Enum):
    UNSET = "__UNSET__"


ENV_UNSET = EnvUnsetType.UNSET


class RunnerError(Exception):
    pass


class RunnerUnavailable(RunnerError):
    pass


class CommandNotFound(RunnerError):
    pass


class CommandFailed(RunnerError):
    pass


class CommandTimeout(RunnerError):
    pass


class OutputLimitExceeded(RunnerError):
    pass


class RedactionError(RunnerError):
    pass


@dataclass(frozen=True)
class RunRequest:
    command: list[str] | str
    cwd: Path | None = None
    env: dict[str, str | EnvUnsetType] | None = None
    timeout_s: float | None = None
    stream: bool = False
    side_effect_level: SideEffectLevel = "low"
    shell: bool = False


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    finished_at: datetime
    runner_mode: RunnerMode
    redactions_applied: bool


class Runner(Protocol):
    mode: RunnerMode

    def run(self, request: RunRequest) -> RunResult:
        """Execute one command according to runner policy.

        Contract highlights:
        - canonical command form is argv list; shell strings require shell=True
        - env is an overlay; ENV_UNSET removes inherited vars
        - timeout handling raises/returns typed timeout failures
        - stream=True may emit structured output events; RunResult retains bounded tails
        """
        ...


@dataclass(frozen=True)
class ProbeResult:
    probe_id: str
    severity: Severity
    summary: str
    evidence: dict[str, Any] | list[Any]
    observed_at: datetime
    runner_mode: RunnerMode
    remediation_hint: str | None = None
    source_command: list[str] = field(default_factory=list)
    probe_error: bool = False


class HealthProbe(Protocol):
    probe_id: str

    def run(self, runner: Runner) -> ProbeResult:
        ...


@dataclass(frozen=True)
class Region:
    id: str
    label: str


@dataclass(frozen=True)
class InstanceType:
    id: str
    label: str
    cpu: int | None = None
    memory_gb: float | None = None


@dataclass(frozen=True)
class CredentialStatus:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderPlanHints:
    summary: str
    hints: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class CloudProvider(Protocol):
    provider_id: str

    def list_regions(self) -> list[Region]:
        ...

    def list_instance_types(self, region: str) -> list[InstanceType]:
        ...

    def validate_credentials(self) -> CredentialStatus:
        ...

    def render_user_data(self, data: dict[str, Any]) -> str:
        ...

    def plan_preview(self, data: dict[str, Any]) -> ProviderPlanHints:
        ...


@dataclass(frozen=True)
class PlanSummary:
    plan_path: Path
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApplySummary:
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DestroySummary:
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StructuredPlan:
    raw: dict[str, Any]


class InfraPlanner(Protocol):
    def init(self) -> None:
        ...

    def plan(self, vars: dict[str, Any], out_path: Path) -> PlanSummary:
        ...

    def apply(self, plan_path: Path) -> ApplySummary:
        ...

    def destroy(self, plan_path_or_vars: Path | dict[str, Any]) -> DestroySummary:
        ...

    def show_plan(self, plan_path: Path) -> StructuredPlan:
        ...

    def detect_stale_plan(self, plan_path: Path, vars_fingerprint: str) -> bool:
        ...


@dataclass(frozen=True)
class RemoteTarget:
    host: str
    user: str
    port: int = 22


class RemoteExecutor(Protocol):
    def wait_ready(self, target: RemoteTarget, timeout_s: float) -> None:
        ...

    def run_script(
        self,
        target: RemoteTarget,
        script_ref: str,
        args: list[str],
        env_handles: dict[str, str],
    ) -> RunResult:
        ...

    def push_file(self, target: RemoteTarget, local: Path, remote: str, mode: str) -> None:
        ...

    def fetch_file(self, target: RemoteTarget, remote: str, local: Path) -> None:
        ...

    def verify_fingerprint(self, target: RemoteTarget, expected: str) -> bool:
        ...


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GatewayApplyResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class GatewayManager(Protocol):
    def detect_auth_mode(self, provider: str) -> Literal["oauth", "api_key", "unknown"]:
        ...

    def validate_provider_access(
        self,
        provider: str,
        secret_handle: str | None = None,
    ) -> ValidationResult:
        ...

    def configure_gateway(
        self,
        gateway_kind: str,
        config_handles: dict[str, str],
    ) -> GatewayApplyResult:
        ...

    def smoke_test_gateway(self, gateway_kind: str) -> ProbeResult:
        ...
