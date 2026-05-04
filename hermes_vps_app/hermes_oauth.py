from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import errno
import json
import os
from pathlib import Path
import pty
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Literal

HermesOAuthStatus = Literal["succeeded", "failed", "cancelled"]
HermesOAuthStream = Literal["stdout", "stderr"]


@dataclass(frozen=True)
class HermesOAuthInstruction:
    kind: Literal["url", "code"]
    value: str


@dataclass(frozen=True)
class HermesOAuthOutputEvent:
    stream: HermesOAuthStream
    text: str


@dataclass(frozen=True)
class HermesOAuthInstructionEvent:
    instruction: HermesOAuthInstruction
    text: str
    stream: HermesOAuthStream


@dataclass(frozen=True)
class HermesOAuthRunResult:
    status: HermesOAuthStatus
    provider: str
    agent_version: str
    agent_release_tag: str
    auth_method: Literal["oauth"]
    auth_json_bytes: bytes | None
    auth_json_sha256: str | None
    instructions: tuple[HermesOAuthInstruction, ...]
    output_tail: str
    exit_code: int | None
    error_message: str | None


@dataclass(frozen=True)
class HermesOAuthCompletedEvent:
    result: HermesOAuthRunResult


HermesOAuthEvent = HermesOAuthOutputEvent | HermesOAuthInstructionEvent | HermesOAuthCompletedEvent


class HermesOAuthCancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class HermesOAuthRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        drafts_root: Path | None = None,
        output_tail_chars: int = 8000,
        cancel_grace_seconds: float = 2.0,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.drafts_root = drafts_root or self.repo_root / ".cache" / "hermes-oauth-drafts"
        self.output_tail_chars = output_tail_chars
        self.cancel_grace_seconds = cancel_grace_seconds

    def run(
        self,
        *,
        cache_dir: Path,
        provider: str,
        agent_version: str,
        agent_release_tag: str,
        request_id: str,
        cancel_token: HermesOAuthCancelToken | None = None,
        on_event: Callable[[HermesOAuthEvent], None] | None = None,
    ) -> HermesOAuthRunResult:
        cache_dir = Path(cache_dir)
        draft_dir = self.drafts_root / _safe_request_id(request_id)
        home = draft_dir / "home"
        hermes_cli = cache_dir / "venv" / "bin" / "hermes"
        output = _BoundedOutputTail(self.output_tail_chars)
        instructions: list[HermesOAuthInstruction] = []
        cancel = cancel_token or HermesOAuthCancelToken()
        exit_code: int | None = None
        cancelled = False

        if draft_dir.exists():
            shutil.rmtree(draft_dir)
        home.mkdir(parents=True, exist_ok=True)

        argv = [str(hermes_cli), "auth", "add", provider, "--type", "oauth", "--no-browser"]
        env = os.environ.copy()
        env["HERMES_HOME"] = str(home)

        master_fd: int | None = None
        slave_fd: int | None = None
        try:
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(
                argv,
                cwd=cache_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=slave_fd,
                stderr=slave_fd,
                text=False,
                close_fds=True,
            )
            os.close(slave_fd)
            slave_fd = None
        except FileNotFoundError:
            if master_fd is not None:
                os.close(master_fd)
            if slave_fd is not None:
                os.close(slave_fd)
            shutil.rmtree(draft_dir, ignore_errors=True)
            result = _result(
                status="failed",
                provider=provider,
                agent_version=agent_version,
                agent_release_tag=agent_release_tag,
                auth_json_bytes=None,
                instructions=(),
                output_tail="",
                exit_code=127,
                error_message=f"Selected Hermes CLI not found: {hermes_cli}",
            )
            _emit_completed(on_event, result)
            return result

        event_queue: queue.Queue[HermesOAuthOutputEvent] = queue.Queue()
        reader_threads = (
            threading.Thread(target=_read_pty_stream, args=(master_fd, event_queue), daemon=True),
        )
        for thread in reader_threads:
            thread.start()

        try:
            while True:
                _drain_events(event_queue, output, instructions, on_event)
                exit_code = process.poll()
                if exit_code is not None:
                    break
                if cancel.cancelled:
                    cancelled = True
                    process.terminate()
                    try:
                        exit_code = process.wait(timeout=self.cancel_grace_seconds)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        exit_code = process.wait()
                    break
                time.sleep(0.02)

            for thread in reader_threads:
                thread.join(timeout=1.0)
            _drain_events(event_queue, output, instructions, on_event)

            if cancelled:
                result = _result(
                    status="cancelled",
                    provider=provider,
                    agent_version=agent_version,
                    agent_release_tag=agent_release_tag,
                    auth_json_bytes=None,
                    instructions=tuple(_dedupe_instructions(instructions)),
                    output_tail=output.text,
                    exit_code=exit_code,
                    error_message="OAuth cancelled. No artifact captured.",
                )
                _emit_completed(on_event, result)
                return result

            if exit_code != 0:
                result = _result(
                    status="failed",
                    provider=provider,
                    agent_version=agent_version,
                    agent_release_tag=agent_release_tag,
                    auth_json_bytes=None,
                    instructions=tuple(_dedupe_instructions(instructions)),
                    output_tail=output.text,
                    exit_code=exit_code,
                    error_message=f"Hermes OAuth command failed with exit code {exit_code}.",
                )
                _emit_completed(on_event, result)
                return result

            auth_json_path = home / "auth.json"
            auth_json_result = _read_valid_auth_json(auth_json_path)
            if isinstance(auth_json_result, str):
                result = _result(
                    status="failed",
                    provider=provider,
                    agent_version=agent_version,
                    agent_release_tag=agent_release_tag,
                    auth_json_bytes=None,
                    instructions=tuple(_dedupe_instructions(instructions)),
                    output_tail=output.text,
                    exit_code=exit_code,
                    error_message=auth_json_result,
                )
                _emit_completed(on_event, result)
                return result
            auth_json_bytes = auth_json_result
            result = _result(
                status="succeeded",
                provider=provider,
                agent_version=agent_version,
                agent_release_tag=agent_release_tag,
                auth_json_bytes=auth_json_bytes,
                instructions=tuple(_dedupe_instructions(instructions)),
                output_tail=output.text,
                exit_code=exit_code,
                error_message=None,
            )
            _emit_completed(on_event, result)
            return result
        finally:
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass
            shutil.rmtree(draft_dir, ignore_errors=True)


def cleanup_stale_oauth_drafts(
    *,
    repo_root: Path,
    older_than_seconds: float = 24 * 60 * 60,
    now: Callable[[], float] = time.time,
) -> tuple[Path, ...]:
    drafts_root = Path(repo_root) / ".cache" / "hermes-oauth-drafts"
    if not drafts_root.exists():
        return ()
    removed: list[Path] = []
    cutoff = now() - older_than_seconds
    for child in drafts_root.iterdir():
        try:
            if child.stat().st_mtime > cutoff:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed.append(child)
        except OSError:
            continue
    return tuple(removed)


def _result(
    *,
    status: HermesOAuthStatus,
    provider: str,
    agent_version: str,
    agent_release_tag: str,
    auth_json_bytes: bytes | None,
    instructions: tuple[HermesOAuthInstruction, ...],
    output_tail: str,
    exit_code: int | None,
    error_message: str | None,
) -> HermesOAuthRunResult:
    return HermesOAuthRunResult(
        status=status,
        provider=provider,
        agent_version=agent_version,
        agent_release_tag=agent_release_tag,
        auth_method="oauth",
        auth_json_bytes=auth_json_bytes,
        auth_json_sha256=hashlib.sha256(auth_json_bytes).hexdigest() if auth_json_bytes is not None else None,
        instructions=instructions,
        output_tail=output_tail,
        exit_code=exit_code,
        error_message=error_message,
    )


def _read_pty_stream(master_fd: int | None, event_queue: queue.Queue[HermesOAuthOutputEvent]) -> None:
    if master_fd is None:
        return
    while True:
        try:
            data = os.read(master_fd, 4096)
        except OSError as exc:
            if exc.errno in (errno.EIO, errno.EBADF):
                return
            raise
        if not data:
            return
        event_queue.put(
            HermesOAuthOutputEvent(
                stream="stdout",
                text=data.decode("utf-8", errors="replace"),
            )
        )


def _drain_events(
    event_queue: queue.Queue[HermesOAuthOutputEvent],
    output: _BoundedOutputTail,
    instructions: list[HermesOAuthInstruction],
    on_event: Callable[[HermesOAuthEvent], None] | None,
) -> None:
    while True:
        try:
            event = event_queue.get_nowait()
        except queue.Empty:
            return
        redacted_text = _redact_sensitive_output(event.text)
        redacted_event = HermesOAuthOutputEvent(stream=event.stream, text=redacted_text)
        output.append(redacted_text)
        extracted = _extract_instructions(redacted_text)
        instructions.extend(extracted)
        if on_event is not None:
            on_event(redacted_event)
            for instruction in extracted:
                on_event(HermesOAuthInstructionEvent(instruction=instruction, text=redacted_text, stream=event.stream))


def _emit_completed(
    on_event: Callable[[HermesOAuthEvent], None] | None,
    result: HermesOAuthRunResult,
) -> None:
    if on_event is not None:
        on_event(HermesOAuthCompletedEvent(result=result))


class _BoundedOutputTail:
    def __init__(self, limit: int) -> None:
        self.limit = max(0, limit)
        self._text = ""

    def append(self, text: str) -> None:
        if self.limit == 0:
            self._text = ""
            return
        self._text = (self._text + text)[-self.limit :]

    @property
    def text(self) -> str:
        return self._text


def _extract_instructions(text: str) -> tuple[HermesOAuthInstruction, ...]:
    instructions: list[HermesOAuthInstruction] = []
    for match in re.finditer(r"https?://[^\s)>,;]+", text):
        instructions.append(HermesOAuthInstruction(kind="url", value=match.group(0).rstrip(".")))
    for match in re.finditer(r"\b[A-Z0-9]{4}(?:-[A-Z0-9]{4})+\b", text):
        instructions.append(HermesOAuthInstruction(kind="code", value=match.group(0)))
    return tuple(instructions)


def _dedupe_instructions(instructions: list[HermesOAuthInstruction]) -> list[HermesOAuthInstruction]:
    seen: set[tuple[str, str]] = set()
    deduped: list[HermesOAuthInstruction] = []
    for instruction in instructions:
        key = (instruction.kind, instruction.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(instruction)
    return deduped


def _read_valid_auth_json(path: Path) -> bytes | str:
    if not path.exists():
        return f"Hermes OAuth command completed but {path.name} was not created."
    try:
        auth_json_bytes = path.read_bytes()
    except OSError as exc:
        return f"Hermes OAuth command completed but {path.name} could not be read: {exc}"
    if not auth_json_bytes.strip():
        return f"Hermes OAuth command completed but {path.name} was empty."
    try:
        json.loads(auth_json_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"Hermes OAuth command completed but {path.name} was not valid JSON: {exc}"
    return auth_json_bytes


def _safe_request_id(request_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", request_id.strip())
    return safe or "oauth"


def _redact_sensitive_output(text: str) -> str:
    redacted = re.sub(
        r'("(?:access_token|refresh_token|id_token|client_secret|token)"\s*:\s*")([^"]+)(")',
        r'\1***\3',
        text,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"('(?:access_token|refresh_token|id_token|client_secret|token)'\s*:\s*')([^']+)(')",
        r"\1***\3",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted
