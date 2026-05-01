from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Final

from hermes_control_core.interfaces import (
    CommandFailed,
    CommandNotFound,
    CommandTimeout,
    OutputLimitExceeded,
    RunRequest,
    RunResult,
    Runner,
    RunnerMode,
    RunnerUnavailable,
)
from hermes_control_core.session import SessionAuditLog


_DEFAULT_OUTPUT_CAP_BYTES: Final[int] = 512_000


class RunnerDetectionError(RunnerUnavailable):
    pass


class DetectionMode(str, Enum):
    DIRENV_NIX = "direnv_nix"
    NIX_DEVELOP = "nix_develop"
    DOCKER_NIX = "docker_nix"
    HOST = "host"


@dataclass(frozen=True)
class RunnerSelection:
    mode: DetectionMode
    reason: str


class BaseRunner(Runner):
    mode: RunnerMode

    def __init__(self, mode: RunnerMode, output_cap_bytes: int = _DEFAULT_OUTPUT_CAP_BYTES) -> None:
        self.mode = mode
        self._output_cap_bytes = output_cap_bytes

    def _checked_output(self, text: str) -> str:
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= self._output_cap_bytes:
            return text
        kept = encoded[: self._output_cap_bytes]
        return kept.decode("utf-8", errors="replace")

    def _assert_no_secrets_in_logs(self, _request: RunRequest) -> None:
        # Placeholder for future redaction marking + verification policy.
        # Fail-closed hook stays explicit in API contract.
        return


class SubprocessRunner(BaseRunner):
    def __init__(
        self,
        mode: RunnerMode,
        prefix_argv: list[str] | None = None,
        output_cap_bytes: int = _DEFAULT_OUTPUT_CAP_BYTES,
    ) -> None:
        super().__init__(mode=mode, output_cap_bytes=output_cap_bytes)
        self._prefix_argv = prefix_argv or []

    def run(self, request: RunRequest) -> RunResult:
        self._assert_no_secrets_in_logs(request)

        if isinstance(request.command, str):
            if not request.shell:
                raise CommandFailed(
                    "string command requires shell=True; canonical form is argv list"
                )
            argv: list[str] | str = request.command
        else:
            if request.shell:
                raise CommandFailed("shell=True incompatible with argv-list command")
            argv = [*self._prefix_argv, *request.command]

        env = os.environ.copy()
        if request.env is not None:
            for k, v in request.env.items():
                if isinstance(v, str):
                    env[k] = v
                else:
                    env.pop(k, None)

        started = datetime.now(UTC)
        try:
            completed = subprocess.run(
                argv,
                cwd=str(request.cwd) if request.cwd is not None else None,
                env=env,
                shell=request.shell,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=request.timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CommandNotFound(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise CommandTimeout(str(exc)) from exc
        except Exception as exc:  # pragma: no cover
            raise CommandFailed(str(exc)) from exc
        finished = datetime.now(UTC)

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        truncated = False
        if len(stdout.encode("utf-8", errors="replace")) > self._output_cap_bytes:
            stdout = self._checked_output(stdout)
            truncated = True
        if len(stderr.encode("utf-8", errors="replace")) > self._output_cap_bytes:
            stderr = self._checked_output(stderr)
            truncated = True
        if truncated:
            raise OutputLimitExceeded("command output exceeded configured retention cap")

        result = RunResult(
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            started_at=started,
            finished_at=finished,
            runner_mode=self.mode,
            redactions_applied=True,
        )
        if completed.returncode != 0:
            raise CommandFailed(
                f"command exited non-zero ({completed.returncode})",
                result,
            )
        return result


class RunnerFactory:
    """Per-launch runner detector and lock.

    Detection order:
    1) direnv-attached flake shell
    2) nix develop
    3) dockerized nix
    4) host only via explicit override
    """

    def __init__(
        self,
        repo_root: Path,
        allow_host_override: bool = False,
        override_reason: str | None = None,
        audit_log: SessionAuditLog | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.allow_host_override = allow_host_override
        self.override_reason = (override_reason or "").strip()
        if self.allow_host_override and not self.override_reason:
            raise RunnerDetectionError(
                "Host runner override requires non-empty override_reason for auditability."
            )
        self.audit_log = audit_log
        self._locked: Runner | None = None
        self._selection: RunnerSelection | None = None

    @property
    def selection(self) -> RunnerSelection | None:
        return self._selection

    def get(self) -> Runner:
        if self._locked is not None:
            return self._locked

        selection = self.detect()
        runner = self._build(selection)
        self._selection = selection
        self._locked = runner
        self._record_selection(selection)
        return runner

    def _record_selection(self, selection: RunnerSelection) -> None:
        if self.audit_log is None:
            return
        self.audit_log.set_runner_selection(mode=selection.mode.value, reason=selection.reason)

    def detect(self) -> RunnerSelection:
        if self._is_direnv_attached_nix_shell():
            return RunnerSelection(
                mode=DetectionMode.DIRENV_NIX,
                reason="PATH/sys.executable indicate active nix store toolchain (direnv-attached)",
            )

        if shutil.which("nix"):
            return RunnerSelection(
                mode=DetectionMode.NIX_DEVELOP,
                reason="nix command available; use nix develop wrapper mode",
            )

        if shutil.which("docker"):
            return RunnerSelection(
                mode=DetectionMode.DOCKER_NIX,
                reason="nix unavailable; docker present for nix container fallback",
            )

        if self.allow_host_override:
            return RunnerSelection(
                mode=DetectionMode.HOST,
                reason=f"explicit host override enabled: {self.override_reason}",
            )

        raise RunnerDetectionError(
            "No valid runner detected. Install/activate direnv+nix shell, or install nix, or install docker for nix fallback."
        )

    def _build(self, selection: RunnerSelection) -> Runner:
        if selection.mode == DetectionMode.DIRENV_NIX:
            return SubprocessRunner(mode="direnv_nix")

        if selection.mode == DetectionMode.NIX_DEVELOP:
            prefix = [
                "nix",
                "--extra-experimental-features",
                "nix-command flakes",
                "develop",
                "--impure",
                f"path:{self.repo_root}",
                "--command",
            ]
            # Runs: nix develop ... --command <argv...>
            return SubprocessRunner(mode="nix_develop", prefix_argv=prefix)

        if selection.mode == DetectionMode.DOCKER_NIX:
            prefix = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{self.repo_root}:/work",
                "-w",
                "/work",
                "nixos/nix:2.24.14",
                "sh",
                "-lc",
            ]
            return DockerNixRunner(mode="docker_nix", prefix_argv=prefix)

        if selection.mode == DetectionMode.HOST:
            return SubprocessRunner(mode="host")

        raise RunnerDetectionError(f"unsupported runner mode: {selection.mode}")

    @staticmethod
    def _is_direnv_attached_nix_shell() -> bool:
        exe = os.path.realpath(shutil.which("python3") or "")
        path = os.environ.get("PATH", "")
        in_store_python = exe.startswith("/nix/store/")
        in_store_path = "/nix/store/" in path
        return in_store_python and in_store_path


class DockerNixRunner(SubprocessRunner):
    """Docker fallback runner.

    We keep implementation simple here: run requested argv inside a nix container
    via sh -lc with properly quoted payload. For v1 scaffold, this is placeholder-
    ready and can be hardened when wired into concrete app flow.
    """

    def run(self, request: RunRequest) -> RunResult:
        if isinstance(request.command, str):
            if not request.shell:
                raise CommandFailed("string command requires shell=True")
            payload = request.command
        else:
            quoted = " ".join(subprocess.list2cmdline([arg]) for arg in request.command)
            payload = quoted

        docker_request = RunRequest(
            command=[*self._prefix_argv, payload],
            cwd=request.cwd,
            env=request.env,
            timeout_s=request.timeout_s,
            stream=request.stream,
            side_effect_level=request.side_effect_level,
            shell=False,
        )
        return super().run(docker_request)
