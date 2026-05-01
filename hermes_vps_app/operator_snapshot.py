from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import cast

from hermes_vps_app.config_model import SECRET_KEYS
from hermes_vps_app.operational import VALID_PROVIDERS
from hermes_vps_app.panel_startup import PanelStartupResult, PanelStartupState

REMOTE_STATUS_STALE_AFTER = timedelta(hours=24)
STATUS_FILE = Path(".hermes-vps") / "operator-status.json"

REQUIRED_STRUCTURE_KEYS: tuple[str, ...] = (
    "TF_VAR_cloud_provider",
    "TF_VAR_server_location",
    "TF_VAR_server_type",
    "TF_VAR_server_image",
    "TF_VAR_hostname",
    "TF_VAR_admin_username",
    "TF_VAR_admin_group",
    "BOOTSTRAP_SSH_PRIVATE_KEY_PATH",
    "BOOTSTRAP_SSH_PORT",
    "TF_VAR_hermes_provider",
    "TF_VAR_hermes_model",
    "HERMES_AGENT_VERSION",
    "HERMES_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWLIST_IDS",
)


class PrimaryAction(str, Enum):
    CONFIGURE = "Configure"
    FIX_CONFIGURATION = "Fix configuration"
    DEPLOY = "Deploy"
    BOOTSTRAP_VERIFY = "Bootstrap/Verify"
    MONITOR_FIX = "Monitor/Fix"
    MONITOR = "Monitor"


class RemoteStatusState(str, Enum):
    UNKNOWN = "unknown"
    FRESH = "fresh"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True)
class EnvKeySnapshot:
    present: bool
    secret: bool


@dataclass(frozen=True)
class EnvFileSnapshot:
    exists: bool
    readable: bool
    mode: str | None
    key_count: int
    keys: dict[str, EnvKeySnapshot]


@dataclass(frozen=True)
class ProviderSnapshot:
    selection: str | None
    valid: bool
    detail: str


@dataclass(frozen=True)
class ProviderDirectorySnapshot:
    path: str | None
    exists: bool
    detail: str


@dataclass(frozen=True)
class OpenTofuSnapshot:
    state_present: bool
    output_present: bool
    plan_present: bool
    state_files: tuple[str, ...]
    output_keys: tuple[str, ...]


@dataclass(frozen=True)
class RemoteKnownStatus:
    state: RemoteStatusState
    status: str | None
    recorded_at: str | None
    detail: str


@dataclass(frozen=True)
class RemoteStatusSnapshot:
    bootstrap: RemoteKnownStatus
    verify: RemoteKnownStatus
    monitoring: RemoteKnownStatus


@dataclass(frozen=True)
class LocalHealthSummary:
    status: str
    checks: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class OperatorSnapshot:
    repo_root: Path
    env_file: EnvFileSnapshot
    provider: ProviderSnapshot
    runner_mode: str | None
    provider_directory: ProviderDirectorySnapshot
    opentofu: OpenTofuSnapshot
    remote_status: RemoteStatusSnapshot
    local_health: LocalHealthSummary
    primary_action: PrimaryAction

    def to_dict(self) -> dict[str, object]:
        return {
            "repo_root": str(self.repo_root),
            "env_file": {
                "exists": self.env_file.exists,
                "readable": self.env_file.readable,
                "mode": self.env_file.mode,
                "key_count": self.env_file.key_count,
                "keys": {
                    key: {"present": value.present, "secret": value.secret}
                    for key, value in sorted(self.env_file.keys.items())
                },
            },
            "provider": {
                "selection": self.provider.selection,
                "valid": self.provider.valid,
                "detail": self.provider.detail,
            },
            "runner_mode": self.runner_mode,
            "provider_directory": {
                "path": self.provider_directory.path,
                "exists": self.provider_directory.exists,
                "detail": self.provider_directory.detail,
            },
            "opentofu": {
                "state_present": self.opentofu.state_present,
                "output_present": self.opentofu.output_present,
                "plan_present": self.opentofu.plan_present,
                "state_files": list(self.opentofu.state_files),
                "output_keys": list(self.opentofu.output_keys),
            },
            "remote_status": {
                "bootstrap": _remote_status_to_dict(self.remote_status.bootstrap),
                "verify": _remote_status_to_dict(self.remote_status.verify),
                "monitoring": _remote_status_to_dict(self.remote_status.monitoring),
            },
            "local_health": {
                "status": self.local_health.status,
                "checks": list(self.local_health.checks),
                "detail": self.local_health.detail,
            },
            "primary_action": self.primary_action.value,
        }


def build_operator_snapshot(*, repo_root: Path, startup_result: PanelStartupResult) -> OperatorSnapshot:
    root = repo_root.resolve()
    env_values = _read_env_values(root / ".env")
    env_snapshot = _env_file_snapshot(root / ".env", env_values)
    provider = _provider_snapshot(startup_result, env_values)
    provider_dir = _provider_directory_snapshot(root, provider.selection)
    tofu = _opentofu_snapshot(root, provider.selection)
    remote_status = _remote_status_snapshot(root / STATUS_FILE)
    health = _local_health_summary(
        startup_result=startup_result,
        env_file=env_snapshot,
        provider=provider,
        provider_directory=provider_dir,
        opentofu=tofu,
    )
    incomplete = OperatorSnapshot(
        repo_root=root,
        env_file=env_snapshot,
        provider=provider,
        runner_mode=startup_result.runner_mode,
        provider_directory=provider_dir,
        opentofu=tofu,
        remote_status=remote_status,
        local_health=health,
        primary_action=PrimaryAction.CONFIGURE,
    )
    return OperatorSnapshot(
        repo_root=incomplete.repo_root,
        env_file=incomplete.env_file,
        provider=incomplete.provider,
        runner_mode=incomplete.runner_mode,
        provider_directory=incomplete.provider_directory,
        opentofu=incomplete.opentofu,
        remote_status=incomplete.remote_status,
        local_health=incomplete.local_health,
        primary_action=select_primary_action(incomplete),
    )


def select_primary_action(snapshot: OperatorSnapshot) -> PrimaryAction:
    if not snapshot.env_file.exists:
        return PrimaryAction.CONFIGURE
    if snapshot.local_health.status == "blocked" or not snapshot.provider.valid or not snapshot.provider_directory.exists:
        return PrimaryAction.FIX_CONFIGURATION
    if not snapshot.opentofu.state_present:
        return PrimaryAction.DEPLOY
    statuses = (
        snapshot.remote_status.bootstrap,
        snapshot.remote_status.verify,
        snapshot.remote_status.monitoring,
    )
    if any(status.state is RemoteStatusState.FAILED or status.state is RemoteStatusState.STALE for status in statuses):
        return PrimaryAction.MONITOR_FIX
    if snapshot.remote_status.bootstrap.state is RemoteStatusState.UNKNOWN or snapshot.remote_status.verify.state is RemoteStatusState.UNKNOWN:
        return PrimaryAction.BOOTSTRAP_VERIFY
    if snapshot.remote_status.monitoring.state is RemoteStatusState.UNKNOWN:
        return PrimaryAction.MONITOR_FIX
    return PrimaryAction.MONITOR


def _read_env_values(env_path: Path) -> dict[str, str]:
    if not env_path.is_file():
        return {}
    try:
        values: dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
        return values
    except OSError:
        return {}


def _env_file_snapshot(env_path: Path, values: dict[str, str]) -> EnvFileSnapshot:
    exists = env_path.exists()
    readable = exists and os.access(env_path, os.R_OK)
    mode = None
    if exists:
        try:
            mode = f"{stat.S_IMODE(env_path.stat().st_mode):03o}"
        except OSError:
            mode = None
    keys = {
        key: EnvKeySnapshot(present=bool(values.get(key)), secret=key in SECRET_KEYS)
        for key in REQUIRED_STRUCTURE_KEYS
    }
    for key in values:
        if key not in keys:
            keys[key] = EnvKeySnapshot(present=bool(values.get(key)), secret=key in SECRET_KEYS)
    return EnvFileSnapshot(exists=exists, readable=readable, mode=mode, key_count=len(values), keys=keys)


def _provider_snapshot(startup_result: PanelStartupResult, values: dict[str, str]) -> ProviderSnapshot:
    selection = startup_result.provider or values.get("TF_VAR_cloud_provider") or None
    valid = selection in VALID_PROVIDERS
    if selection is None:
        return ProviderSnapshot(selection=None, valid=False, detail="provider not selected")
    if not valid:
        return ProviderSnapshot(selection=selection, valid=False, detail="provider must be hetzner or linode")
    return ProviderSnapshot(selection=selection, valid=True, detail=f"provider selected: {selection}")


def _provider_directory_snapshot(repo_root: Path, provider: str | None) -> ProviderDirectorySnapshot:
    if provider is None:
        return ProviderDirectorySnapshot(path=None, exists=False, detail="provider directory unknown until provider is selected")
    rel = Path("opentofu") / "providers" / provider
    exists = (repo_root / rel).is_dir()
    return ProviderDirectorySnapshot(
        path=rel.as_posix(),
        exists=exists,
        detail="present" if exists else f"missing: {rel.as_posix()}",
    )


def _opentofu_snapshot(repo_root: Path, provider: str | None) -> OpenTofuSnapshot:
    if provider is None:
        return OpenTofuSnapshot(
            state_present=False,
            output_present=False,
            plan_present=False,
            state_files=(),
            output_keys=(),
        )
    tf_dir = repo_root / "opentofu" / "providers" / provider
    state_files = _local_state_files(tf_dir)
    output_keys: set[str] = set()
    for state_file in state_files:
        output_keys.update(_state_output_keys(state_file))
    return OpenTofuSnapshot(
        state_present=bool(state_files),
        output_present=bool(output_keys),
        plan_present=(tf_dir / "tofuplan").is_file(),
        state_files=tuple(_relative_or_name(repo_root, path) for path in state_files),
        output_keys=tuple(sorted(output_keys)),
    )


def _local_state_files(tf_dir: Path) -> tuple[Path, ...]:
    if not tf_dir.is_dir():
        return ()
    files: list[Path] = []
    for pattern in ("*.tfstate", "*.tfstate.backup"):
        files.extend(path for path in tf_dir.rglob(pattern) if path.is_file())
    return tuple(sorted(files))


def _state_output_keys(path: Path) -> tuple[str, ...]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(raw, dict):
        return ()
    payload = cast(dict[str, object], raw)
    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        return ()
    output_map = cast(dict[str, object], outputs)
    return tuple(str(key) for key in output_map)


def _remote_status_snapshot(status_path: Path) -> RemoteStatusSnapshot:
    payload = _read_status_payload(status_path)
    return RemoteStatusSnapshot(
        bootstrap=_known_status(payload, "bootstrap"),
        verify=_known_status(payload, "verify"),
        monitoring=_known_status(payload, "monitoring"),
    )


def _read_status_payload(status_path: Path) -> dict[str, object]:
    if not status_path.is_file():
        return {}
    try:
        raw: object = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return cast(dict[str, object], raw)


def _known_status(payload: dict[str, object], key: str) -> RemoteKnownStatus:
    item = payload.get(key)
    if not isinstance(item, dict):
        return RemoteKnownStatus(
            state=RemoteStatusState.UNKNOWN,
            status=None,
            recorded_at=None,
            detail=f"{key} not checked locally; remote status unknown until run on demand",
        )
    record = cast(dict[str, object], item)
    status = record.get("status")
    status_text = str(status) if status is not None else None
    recorded_at_raw = record.get("recorded_at")
    recorded_at = str(recorded_at_raw) if recorded_at_raw is not None else None
    if status_text not in {"ok", "succeeded", "healthy"}:
        return RemoteKnownStatus(
            state=RemoteStatusState.FAILED,
            status=status_text,
            recorded_at=recorded_at,
            detail=f"{key} last known status requires attention",
        )
    if _is_stale(recorded_at):
        return RemoteKnownStatus(
            state=RemoteStatusState.STALE,
            status=status_text,
            recorded_at=recorded_at,
            detail=f"{key} last known status is stale; rerun on-demand check",
        )
    return RemoteKnownStatus(
        state=RemoteStatusState.FRESH,
        status=status_text,
        recorded_at=recorded_at,
        detail=f"{key} last known status is fresh",
    )


def _is_stale(recorded_at: str | None) -> bool:
    if recorded_at is None:
        return True
    try:
        parsed = datetime.fromisoformat(recorded_at)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return datetime.now(UTC) - parsed.astimezone(UTC) > REMOTE_STATUS_STALE_AFTER


def _local_health_summary(
    *,
    startup_result: PanelStartupResult,
    env_file: EnvFileSnapshot,
    provider: ProviderSnapshot,
    provider_directory: ProviderDirectorySnapshot,
    opentofu: OpenTofuSnapshot,
) -> LocalHealthSummary:
    checks: list[str] = []
    problems: list[str] = []
    if env_file.exists:
        checks.append(".env present")
    else:
        problems.append(".env missing")
    if env_file.exists and env_file.mode != "600":
        problems.append(".env permissions are not 600")
    if provider.valid:
        checks.append("provider selected")
    else:
        problems.append(provider.detail)
    if provider_directory.exists:
        checks.append("provider directory present")
    elif provider.selection is not None:
        problems.append(provider_directory.detail)
    if opentofu.state_present:
        checks.append("OpenTofu state present")
    else:
        checks.append("OpenTofu state not present")
    if opentofu.output_present:
        checks.append("OpenTofu outputs present")
    else:
        checks.append("OpenTofu outputs not present")
    if startup_result.state is PanelStartupState.BLOCKED:
        problems.append(startup_result.remediation)
    status = "blocked" if problems else "ok"
    detail = "; ".join(problems) if problems else "local checks ok"
    return LocalHealthSummary(status=status, checks=tuple(checks), detail=detail)


def _remote_status_to_dict(status: RemoteKnownStatus) -> dict[str, object]:
    return {
        "state": status.state.value,
        "status": status.status,
        "recorded_at": status.recorded_at,
        "detail": status.detail,
    }


def _relative_or_name(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name
