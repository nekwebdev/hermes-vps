from __future__ import annotations

import json
import time
import urllib.request
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace

from hermes_vps_app.hermes_live_metadata import (
    HermesReleaseService,
    HermesToolchainCache,
    ToolchainCommandResult,
    HermesRuntimeMetadataService,
    _runtime_metadata_script,
)


@dataclass
class _FakeResponse:
    payload: bytes
    status: int = 200

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class _FakeUrlOpen:
    def __init__(self, payloads: list[list[dict[str, object]]]) -> None:
        self.payloads = payloads
        self.requests: list[urllib.request.Request] = []
        self.data_args: list[object] = []
        self.timeout_args: list[float | None] = []

    def __call__(
        self,
        request: urllib.request.Request,
        data: object = None,
        timeout: float | None = None,
    ) -> _FakeResponse:
        assert timeout == 15
        self.requests.append(request)
        self.data_args.append(data)
        self.timeout_args.append(timeout)
        if not self.payloads:
            raise AssertionError("urlopen called more times than expected")
        return _FakeResponse(json.dumps(self.payloads.pop(0)).encode())


def test_release_service_fetches_exactly_five_unauthenticated_releases_and_parses_semver_tag() -> None:
    urlopen = _FakeUrlOpen(
        [
            [
                {
                    "name": "Hermes Agent v0.12.0 (2026.4.30)",
                    "tag_name": "v2026.4.30",
                    "html_url": "https://github.com/NousResearch/hermes-agent/releases/tag/v2026.4.30",
                    "body": "# Hermes Agent v0.12.0 (v2026.4.30)",
                },
                {
                    "name": "Hermes Agent v0.11.0 (2026.4.23)",
                    "tag_name": "v2026.4.23",
                    "html_url": "https://github.com/NousResearch/hermes-agent/releases/tag/v2026.4.23",
                    "body": "",
                },
            ]
        ]
    )
    service = HermesReleaseService(urlopen=urlopen, now=lambda: 1000.0)

    releases = service.latest_releases()

    assert [release.semantic_version for release in releases] == ["0.12.0", "0.11.0"]
    assert releases[0].release_tag == "v2026.4.30"
    assert releases[0].source_url.endswith("/v2026.4.30")
    request = urlopen.requests[0]
    assert request.full_url == "https://api.github.com/repos/NousResearch/hermes-agent/releases?per_page=5"
    assert request.get_header("Authorization") is None
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert urlopen.data_args == [None]
    assert urlopen.timeout_args == [15]


def test_release_service_uses_five_minute_ttl_and_retry_bypasses_cache() -> None:
    clock = [1000.0]
    urlopen = _FakeUrlOpen(
        [
            [
                {"name": "Hermes Agent v0.12.0", "tag_name": "v2026.4.30", "html_url": "first"},
            ],
            [
                {"name": "Hermes Agent v0.13.0", "tag_name": "v2026.5.7", "html_url": "second"},
            ],
        ]
    )
    service = HermesReleaseService(urlopen=urlopen, now=lambda: clock[0])

    assert service.latest_releases()[0].semantic_version == "0.12.0"
    clock[0] += 299
    assert service.latest_releases()[0].semantic_version == "0.12.0"
    assert len(urlopen.requests) == 1

    assert service.latest_releases(force_refresh=True)[0].semantic_version == "0.13.0"
    assert len(urlopen.requests) == 2


def test_release_service_raises_actionable_error_when_no_semver_can_be_parsed() -> None:
    urlopen = _FakeUrlOpen(
        [[{"name": "Release without package version", "tag_name": "v2026.4.30", "html_url": "bad"}]]
    )
    service = HermesReleaseService(urlopen=urlopen, now=time.monotonic)

    try:
        service.latest_releases()
    except RuntimeError as exc:
        assert "Could not parse Hermes Agent semantic version" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


class _ScriptedToolchainRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str, dict[str, str]]] = []

    def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str]) -> ToolchainCommandResult:
        self.calls.append((tuple(argv), str(cwd), dict(env)))
        if argv[:2] == ["git", "clone"]:
            destination = Path(argv[-1])
            destination.mkdir(parents=True)
            (destination / ".git").mkdir()
            (destination / "pyproject.toml").write_text('[project]\nname = "hermes-agent"\nversion = "0.12.0"\n')
        elif argv[:2] == ["git", "rev-parse"]:
            return ToolchainCommandResult(stdout="abc123\n", stderr="", returncode=0)
        elif argv[:2] == ["uv", "venv"]:
            venv = cwd / "venv"
            (venv / "bin").mkdir(parents=True)
            hermes = venv / "bin" / "hermes"
            hermes.write_text("#!/bin/sh\necho hermes\n")
            hermes.chmod(0o755)
        elif argv[:3] == ["uv", "pip", "install"]:
            assert argv[-1] == ".[all]"
            venv = Path(env["VIRTUAL_ENV"])
            site_packages = venv / "lib" / "python3.11" / "site-packages"
            site_packages.mkdir(parents=True, exist_ok=True)
            (site_packages / "__editable___hermes_agent_0_12_0_finder.py").write_text(
                f"MAPPING = {{'hermes_cli': '{cwd / 'hermes_cli'}'}}\n"
            )
        elif argv and argv[0].endswith("/hermes"):
            return ToolchainCommandResult(stdout="Hermes Agent 0.12.0\n", stderr="", returncode=0)
        elif argv[:2] == ["venv/bin/python", "-c"]:
            return ToolchainCommandResult(stdout="metadata ok\n", stderr="", returncode=0)
        return ToolchainCommandResult(stdout="", stderr="", returncode=0)


def _write_editable_finder(cache_dir: Path, *, target_src: Path | None = None) -> None:
    site_packages = cache_dir / "venv" / "lib" / "python3.11" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    source = target_src or (cache_dir / "src")
    (site_packages / "__editable___hermes_agent_0_12_0_finder.py").write_text(
        f"MAPPING = {{'hermes_cli': '{source / 'hermes_cli'}'}}\n"
    )


def test_default_toolchain_runner_reports_missing_binary_without_crashing(tmp_path: Path) -> None:
    result = HermesToolchainCache._default_runner(
        ["hermes-vps-command-that-should-not-exist-xyz"],
        cwd=tmp_path,
        env={},
    )

    assert result.returncode == 127
    assert result.stdout == ""
    assert "Required command not found in panel toolchain" in result.stderr
    assert "hermes-vps-command-that-should-not-exist-xyz" in result.stderr


def test_toolchain_cache_surfaces_missing_binary_as_actionable_error(tmp_path: Path) -> None:
    cache = HermesToolchainCache(
        root=tmp_path,
        runner=lambda argv, cwd, env: ToolchainCommandResult("", "Required command not found in panel toolchain: git.", 127),
    )

    try:
        cache.prepare("0.12.0", "v2026.4.30", request_id="req-missing-git")
    except RuntimeError as exc:
        message = str(exc)
        assert "Command failed: git clone" in message
        assert "Required command not found in panel toolchain: git." in message
    else:
        raise AssertionError("expected RuntimeError")


def test_toolchain_cache_builds_full_selected_version_and_writes_ready_sentinel(tmp_path: Path) -> None:
    runner = _ScriptedToolchainRunner()
    cache = HermesToolchainCache(root=tmp_path, runner=runner, now=lambda: "2026-05-02T00:00:00Z")

    result = cache.prepare("0.12.0", "v2026.4.30", request_id="req1")

    assert result.ready is True
    assert (tmp_path / ".locks" / "0.12.0-v2026.4.30.lock").exists()
    assert result.cache_dir == tmp_path / "0.12.0-v2026.4.30"
    assert result.hermes_cli == tmp_path / "0.12.0-v2026.4.30" / "venv" / "bin" / "hermes"
    ready = json.loads((result.cache_dir / ".ready.json").read_text())
    assert ready["semantic_version"] == "0.12.0"
    assert ready["release_tag"] == "v2026.4.30"
    assert ready["git_commit"] == "abc123"
    assert ready["install_mode"] == "editable-all"
    assert ready["hermes_cli_path"] == str(result.hermes_cli)
    assert any(call[0] == ("git", "clone", "--depth", "1", "--branch", "v2026.4.30", "https://github.com/NousResearch/hermes-agent.git", str(tmp_path / ".building" / "0.12.0-v2026.4.30-req1" / "src")) for call in runner.calls)
    assert any(call[0] == ("uv", "venv", "venv", "--python", "3.11") for call in runner.calls)
    assert sum(1 for call in runner.calls if call[0] == ("uv", "pip", "install", "-e", ".[all]")) == 2
    final_install_call = [call for call in runner.calls if call[0] == ("uv", "pip", "install", "-e", ".[all]")][-1]
    assert final_install_call[1] == str(tmp_path / "0.12.0-v2026.4.30" / "src")
    smoke_call = next(call for call in runner.calls if call[0] and call[0][0].endswith("/hermes"))
    assert smoke_call[2]["HERMES_HOME"] == str(tmp_path / "0.12.0-v2026.4.30" / "home")


def test_toolchain_cache_reuses_ready_cache_without_running_commands(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0.12.0-v2026.4.30"
    hermes = cache_dir / "venv" / "bin" / "hermes"
    hermes.parent.mkdir(parents=True)
    hermes.write_text("#!/bin/sh\n")
    hermes.chmod(0o755)
    (cache_dir / ".ready.json").write_text(json.dumps({
        "semantic_version": "0.12.0",
        "release_tag": "v2026.4.30",
        "git_commit": "abc123",
        "install_mode": "editable-all",
        "python_version": "Python 3.11.9",
        "hermes_cli_path": str(hermes),
        "created_at": "2026-05-02T00:00:00Z",
        "smoke_test": {"ok": True},
    }))
    _write_editable_finder(cache_dir)
    calls: list[object] = []
    cache = HermesToolchainCache(
        root=tmp_path,
        runner=lambda argv, cwd, env: calls.append((argv, cwd, env)) or ToolchainCommandResult("", "", 0),
        commit_resolver=lambda tag: "abc123",
    )

    result = cache.prepare("0.12.0", "v2026.4.30", request_id="req2")

    assert result.ready is True
    assert result.cache_dir == cache_dir
    assert calls == []


def test_toolchain_cache_rebuilds_when_editable_finder_points_at_build_dir(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0.12.0-v2026.4.30"
    hermes = cache_dir / "venv" / "bin" / "hermes"
    hermes.parent.mkdir(parents=True)
    hermes.write_text("#!/bin/sh\n")
    hermes.chmod(0o755)
    (cache_dir / ".ready.json").write_text(json.dumps({
        "semantic_version": "0.12.0",
        "release_tag": "v2026.4.30",
        "git_commit": "abc123",
        "install_mode": "editable-all",
        "python_version": "Python 3.11.9",
        "hermes_cli_path": str(hermes),
        "created_at": "2026-05-02T00:00:00Z",
        "smoke_test": {"ok": True},
    }))
    _write_editable_finder(cache_dir, target_src=tmp_path / ".building" / "old-build" / "src")
    runner = _ScriptedToolchainRunner()
    cache = HermesToolchainCache(
        root=tmp_path,
        runner=runner,
        commit_resolver=lambda tag: "abc123",
        now=lambda: "2026-05-02T00:00:00Z",
    )

    result = cache.prepare("0.12.0", "v2026.4.30", request_id="req-stale-finder")

    assert result.ready is True
    assert any(call[0][:2] == ("git", "clone") for call in runner.calls)
    finder = next((result.cache_dir / "venv" / "lib" / "python3.11" / "site-packages").glob("__editable___hermes_agent_*_finder.py"))
    assert str(result.cache_dir / "src") in finder.read_text()
    assert "/.building/" not in finder.read_text()


def test_toolchain_cache_rebuilds_when_ready_commit_mismatches_release_tag(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0.12.0-v2026.4.30"
    hermes = cache_dir / "venv" / "bin" / "hermes"
    hermes.parent.mkdir(parents=True)
    hermes.write_text("#!/bin/sh\n")
    hermes.chmod(0o755)
    (cache_dir / ".ready.json").write_text(json.dumps({
        "semantic_version": "0.12.0",
        "release_tag": "v2026.4.30",
        "git_commit": "oldcommit",
        "install_mode": "editable-all",
        "python_version": "Python 3.11.9",
        "hermes_cli_path": str(hermes),
        "created_at": "2026-05-02T00:00:00Z",
        "smoke_test": {"ok": True},
    }))
    runner = _ScriptedToolchainRunner()
    cache = HermesToolchainCache(
        root=tmp_path,
        runner=runner,
        commit_resolver=lambda tag: "abc123",
        now=lambda: "2026-05-02T00:00:00Z",
    )

    result = cache.prepare("0.12.0", "v2026.4.30", request_id="req3")

    assert result.ready is True
    assert json.loads((result.cache_dir / ".ready.json").read_text())["git_commit"] == "abc123"
    assert any(call[0][:2] == ("git", "clone") for call in runner.calls)


class _RuntimeRunner:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.calls: list[tuple[tuple[str, ...], str, dict[str, str]]] = []

    def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str]) -> ToolchainCommandResult:
        self.calls.append((tuple(argv), str(cwd), dict(env)))
        return ToolchainCommandResult(stdout=self.stdout, stderr="", returncode=0)


def test_runtime_metadata_service_runs_selected_version_with_isolated_home(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0.12.0-v2026.4.30"
    python = cache_dir / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    runner = _RuntimeRunner(json.dumps({
        "providers": ["anthropic", "openai-codex"],
        "models": {"openai-codex": ["gpt-5.4", "gpt-5.4-mini"]},
        "auth_methods": {"openai-codex": ["oauth", "api_key"]},
    }))
    service = HermesRuntimeMetadataService(runner=runner)

    metadata = service.load(cache_dir=cache_dir, provider="openai-codex")

    assert metadata.providers == ("anthropic", "openai-codex")
    assert metadata.models == ("gpt-5.4", "gpt-5.4-mini")
    assert metadata.auth_methods == ("oauth", "api_key")
    call = runner.calls[0]
    assert call[0][0] == str(python)
    assert call[0][1] == "-c"
    assert call[2]["HERMES_HOME"] == str(cache_dir / "home")


def test_runtime_metadata_script_derives_provider_scoped_auth_methods(monkeypatch) -> None:
    package = ModuleType("hermes_cli")
    models_module = ModuleType("hermes_cli.models")
    providers_module = ModuleType("hermes_cli.providers")
    auth_module = ModuleType("hermes_cli.auth_commands")

    models_module.list_available_providers = lambda: [  # type: ignore[attr-defined]
        {"id": "anthropic"},
        {"id": "openrouter"},
        {"id": "openai-codex"},
    ]
    models_module.provider_model_ids = lambda provider: {  # type: ignore[attr-defined]
        "anthropic": ["claude-sonnet"],
        "openrouter": ["anthropic/claude-sonnet"],
        "openai-codex": ["gpt-5.4"],
    }[provider]
    providers_module.get_provider = lambda provider: {  # type: ignore[attr-defined]
        "anthropic": SimpleNamespace(auth_type="api_key", api_key_env_vars=("ANTHROPIC_API_KEY",)),
        "openrouter": SimpleNamespace(auth_type="api_key", api_key_env_vars=("OPENROUTER_API_KEY",)),
        "openai-codex": SimpleNamespace(auth_type="oauth_external", api_key_env_vars=()),
    }[provider]
    auth_module._OAUTH_CAPABLE_PROVIDERS = {"anthropic", "openai-codex"}  # type: ignore[attr-defined]

    monkeypatch.setitem(__import__("sys").modules, "hermes_cli", package)
    monkeypatch.setitem(__import__("sys").modules, "hermes_cli.models", models_module)
    monkeypatch.setitem(__import__("sys").modules, "hermes_cli.providers", providers_module)
    monkeypatch.setitem(__import__("sys").modules, "hermes_cli.auth_commands", auth_module)

    stdout = StringIO()
    with redirect_stdout(stdout):
        exec(_runtime_metadata_script("openrouter"), {})

    payload = json.loads(stdout.getvalue())
    assert payload["auth_methods"] == {
        "anthropic": ["oauth", "api_key"],
        "openrouter": ["api_key"],
        "openai-codex": ["oauth", "api_key"],
    }


def test_runtime_metadata_service_rejects_malformed_json(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0.12.0-v2026.4.30"
    python = cache_dir / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    service = HermesRuntimeMetadataService(runner=_RuntimeRunner("not json"))

    try:
        service.load(cache_dir=cache_dir, provider="openai-codex")
    except RuntimeError as exc:
        assert "invalid Hermes metadata JSON" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
