from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
from pathlib import Path

from hermes_vps_app.hermes_oauth import (
    HermesOAuthCancelToken,
    HermesOAuthCompletedEvent,
    HermesOAuthInstructionEvent,
    HermesOAuthOutputEvent,
    HermesOAuthRunner,
    cleanup_stale_oauth_drafts,
)


def _write_fake_hermes(cache_dir: Path, script: str) -> Path:
    hermes = cache_dir / "venv" / "bin" / "hermes"
    hermes.parent.mkdir(parents=True)
    hermes.write_text(script, encoding="utf-8")
    hermes.chmod(hermes.stat().st_mode | stat.S_IXUSR)
    return hermes


def test_oauth_runner_uses_selected_toolchain_home_and_captures_valid_auth_json(tmp_path: Path) -> None:
    cache_dir = tmp_path / ".cache" / "hermes-toolchain" / "0.12.0-v2026.4.30"
    auth_payload = {"providers": {"openai-codex": {"access_token": "secret-token"}}}
    fake_hermes = _write_fake_hermes(
        cache_dir,
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys
pathlib.Path(os.environ["HERMES_HOME"]).mkdir(parents=True, exist_ok=True)
print("Visit https://example.test/device and enter code ABCD-EFGH", flush=True)
pathlib.Path(os.environ["HERMES_HOME"], "auth.json").write_text(json.dumps({"providers": {"openai-codex": {"access_token": "secret-token"}}}))
pathlib.Path(os.environ["HERMES_HOME"], "argv.txt").write_text("\\n".join(sys.argv[1:]))
""",
    )
    events: list[object] = []

    result = HermesOAuthRunner(repo_root=tmp_path).run(
        cache_dir=cache_dir,
        provider="openai-codex",
        agent_version="0.12.0",
        agent_release_tag="v2026.4.30",
        request_id="req1",
        on_event=lambda event: events.append(event),
    )

    assert result.status == "succeeded"
    assert result.provider == "openai-codex"
    assert result.agent_version == "0.12.0"
    assert result.agent_release_tag == "v2026.4.30"
    assert result.auth_method == "oauth"
    assert result.auth_json_bytes == json.dumps(auth_payload).encode()
    assert result.auth_json_sha256 == hashlib.sha256(result.auth_json_bytes).hexdigest()
    assert result.exit_code == 0
    assert result.error_message is None
    assert any(instruction.value == "https://example.test/device" for instruction in result.instructions)
    assert any(instruction.value == "ABCD-EFGH" for instruction in result.instructions)
    assert "secret-token" not in result.output_tail
    assert any(
        isinstance(event, HermesOAuthOutputEvent) and "Visit https://example.test/device" in event.text
        for event in events
    )
    assert any(
        isinstance(event, HermesOAuthInstructionEvent) and event.instruction.value == "https://example.test/device"
        for event in events
    )
    assert any(
        isinstance(event, HermesOAuthInstructionEvent) and event.instruction.value == "ABCD-EFGH"
        for event in events
    )
    assert isinstance(events[-1], HermesOAuthCompletedEvent)
    assert events[-1].result.status == "succeeded"
    assert not (tmp_path / ".cache" / "hermes-oauth-drafts" / "req1").exists()
    assert fake_hermes.exists()


def test_oauth_runner_streams_prompt_output_without_trailing_newline(tmp_path: Path) -> None:
    cache_dir = tmp_path / ".cache" / "hermes-toolchain" / "0.12.0-v2026.4.30"
    _write_fake_hermes(
        cache_dir,
        """#!/usr/bin/env python3
import sys
import time
sys.stdout.write("Visit https://example.test/device and enter code ABCD-EFGH")
sys.stdout.flush()
time.sleep(30)
""",
    )
    cancel = HermesOAuthCancelToken()
    output_seen = threading.Event()
    events: list[object] = []
    holder: dict[str, object] = {}

    def on_event(event: object) -> None:
        events.append(event)
        if isinstance(event, HermesOAuthOutputEvent) and "https://example.test/device" in event.text:
            output_seen.set()

    def run() -> None:
        holder["result"] = HermesOAuthRunner(repo_root=tmp_path, cancel_grace_seconds=0.05).run(
            cache_dir=cache_dir,
            provider="openai-codex",
            agent_version="0.12.0",
            agent_release_tag="v2026.4.30",
            request_id="prompt-no-newline",
            cancel_token=cancel,
            on_event=on_event,
        )

    thread = threading.Thread(target=run)
    thread.start()
    assert output_seen.wait(timeout=2)
    cancel.cancel()
    thread.join(timeout=5)

    assert not thread.is_alive()
    result = holder["result"]
    assert result.status == "cancelled"  # type: ignore[attr-defined]
    assert "https://example.test/device" in result.output_tail  # type: ignore[attr-defined]
    assert any(
        isinstance(event, HermesOAuthInstructionEvent) and event.instruction.value == "ABCD-EFGH"
        for event in events
    )


def test_oauth_runner_fails_when_command_succeeds_without_valid_auth_json(tmp_path: Path) -> None:
    cache_dir = tmp_path / ".cache" / "hermes-toolchain" / "0.12.0-v2026.4.30"
    _write_fake_hermes(
        cache_dir,
        """#!/usr/bin/env python3
print("OAuth complete but no artifact", flush=True)
""",
    )

    result = HermesOAuthRunner(repo_root=tmp_path).run(
        cache_dir=cache_dir,
        provider="openai-codex",
        agent_version="0.12.0",
        agent_release_tag="v2026.4.30",
        request_id="missing-auth",
    )

    assert result.status == "failed"
    assert result.auth_json_bytes is None
    assert result.auth_json_sha256 is None
    assert result.exit_code == 0
    assert "auth.json" in (result.error_message or "")
    assert not (tmp_path / ".cache" / "hermes-oauth-drafts" / "missing-auth").exists()


def test_oauth_runner_cancellation_deletes_draft_without_reading_auth_json(tmp_path: Path) -> None:
    cache_dir = tmp_path / ".cache" / "hermes-toolchain" / "0.12.0-v2026.4.30"
    _write_fake_hermes(
        cache_dir,
        """#!/usr/bin/env python3
import json
import os
import pathlib
import time
home = pathlib.Path(os.environ["HERMES_HOME"])
home.mkdir(parents=True, exist_ok=True)
(home / "auth.json").write_text(json.dumps({"token": "must-not-be-read"}))
print("waiting for device flow", flush=True)
time.sleep(30)
""",
    )
    cancel = HermesOAuthCancelToken()
    holder: dict[str, object] = {}

    def run() -> None:
        holder["result"] = HermesOAuthRunner(repo_root=tmp_path, cancel_grace_seconds=0.05).run(
            cache_dir=cache_dir,
            provider="openai-codex",
            agent_version="0.12.0",
            agent_release_tag="v2026.4.30",
            request_id="cancelled",
            cancel_token=cancel,
        )

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.2)
    cancel.cancel()
    thread.join(timeout=5)

    assert not thread.is_alive()
    result = holder["result"]
    assert result.status == "cancelled"  # type: ignore[attr-defined]
    assert result.auth_json_bytes is None  # type: ignore[attr-defined]
    assert result.auth_json_sha256 is None  # type: ignore[attr-defined]
    assert "must-not-be-read" not in result.output_tail  # type: ignore[attr-defined]
    assert not (tmp_path / ".cache" / "hermes-oauth-drafts" / "cancelled").exists()


def test_cleanup_stale_oauth_drafts_removes_only_old_drafts(tmp_path: Path) -> None:
    drafts_root = tmp_path / ".cache" / "hermes-oauth-drafts"
    old = drafts_root / "old"
    fresh = drafts_root / "fresh"
    old.mkdir(parents=True)
    fresh.mkdir(parents=True)
    now = time.time()
    os.utime(old, (now - 49 * 60 * 60, now - 49 * 60 * 60))
    os.utime(fresh, (now, now))

    removed = cleanup_stale_oauth_drafts(repo_root=tmp_path, older_than_seconds=24 * 60 * 60, now=lambda: now)

    assert removed == (old,)
    assert not old.exists()
    assert fresh.exists()
