from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

HERMES_RELEASE_LIST_LIMIT = 5
HERMES_RELEASES_URL = (
    "https://api.github.com/repos/NousResearch/hermes-agent/releases"
    f"?per_page={HERMES_RELEASE_LIST_LIMIT}"
)


@dataclass(frozen=True)
class HermesRelease:
    semantic_version: str
    release_tag: str
    source_url: str


class HermesReleaseService:
    """Fetch and parse Hermes Agent release metadata for the panel."""

    def __init__(
        self,
        *,
        urlopen: Callable[..., object] | None = None,
        now: Callable[[], float] = time.monotonic,
        ttl_seconds: float = 300.0,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._urlopen = urlopen or urllib.request.urlopen
        self._now = now
        self._ttl_seconds = ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._cached_at: float | None = None
        self._cached_releases: tuple[HermesRelease, ...] | None = None

    def latest_releases(self, *, force_refresh: bool = False) -> tuple[HermesRelease, ...]:
        if not force_refresh and self._cached_releases is not None and self._cached_at is not None:
            if self._now() - self._cached_at < self._ttl_seconds:
                return self._cached_releases

        request = urllib.request.Request(
            HERMES_RELEASES_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "hermes-vps-panel",
            },
        )
        try:
            with self._urlopen(request, timeout=self._timeout_seconds) as response:  # type: ignore[attr-defined]
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                raise RuntimeError(
                    "GitHub release lookup failed: rate limited or forbidden. Retry later."
                ) from exc
            raise RuntimeError(f"GitHub release lookup failed: HTTP {exc.code}.") from exc
        except OSError as exc:
            raise RuntimeError(
                "GitHub release lookup failed. Check network/GitHub access, then retry."
            ) from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("GitHub release lookup returned invalid JSON.") from exc
        if not isinstance(payload, list):
            raise RuntimeError("GitHub release lookup returned an unexpected response.")

        releases = tuple(self._parse_release(item) for item in payload[:HERMES_RELEASE_LIST_LIMIT])
        self._cached_at = self._now()
        self._cached_releases = releases
        return releases

    @staticmethod
    def _parse_release(item: object) -> HermesRelease:
        if not isinstance(item, dict):
            raise RuntimeError("GitHub release lookup returned a malformed release entry.")
        name = str(item.get("name") or "")
        body = str(item.get("body") or "")
        release_tag = str(item.get("tag_name") or "")
        source_url = str(item.get("html_url") or "")
        version = _extract_semver(f"{name}\n{body}")
        if not version:
            raise RuntimeError(
                f"Could not parse Hermes Agent semantic version for release tag {release_tag or '<missing>'}."
            )
        if not release_tag:
            raise RuntimeError(f"Hermes Agent release {version} is missing a release tag.")
        return HermesRelease(
            semantic_version=version,
            release_tag=release_tag,
            source_url=source_url,
        )


def _extract_semver(text: str) -> str | None:
    match = re.search(r"\bv(\d+\.\d+\.\d+)\b", text)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", text)
    return match.group(1) if match else None


@dataclass(frozen=True)
class ToolchainCommandResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True)
class ToolchainCacheResult:
    ready: bool
    cache_dir: "Path"
    hermes_cli: "Path"
    semantic_version: str
    release_tag: str
    git_commit: str


class HermesToolchainCache:
    def __init__(
        self,
        *,
        root: "Path",
        runner: Callable[[list[str]], ToolchainCommandResult] | None = None,
        commit_resolver: Callable[[str], str] | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        from pathlib import Path

        self.root = Path(root)
        self._runner = runner or self._default_runner
        self._commit_resolver = commit_resolver
        self._now = now or (lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def prepare(self, semantic_version: str, release_tag: str, *, request_id: str) -> ToolchainCacheResult:
        cache_key = f"{semantic_version}-{release_tag}"
        lock_handle = self._acquire_lock(cache_key)
        try:
            return self._prepare_locked(semantic_version, release_tag, request_id=request_id)
        finally:
            self._release_lock(lock_handle)

    def _prepare_locked(self, semantic_version: str, release_tag: str, *, request_id: str) -> ToolchainCacheResult:
        import shutil

        cache_key = f"{semantic_version}-{release_tag}"
        final_dir = self.root / cache_key
        hermes_cli = final_dir / "venv" / "bin" / "hermes"
        resolved_commit = self._resolve_commit_for_ready_check(release_tag)
        if self._ready(final_dir, semantic_version, release_tag, resolved_commit):
            ready = json.loads((final_dir / ".ready.json").read_text())
            return ToolchainCacheResult(
                ready=True,
                cache_dir=final_dir,
                hermes_cli=hermes_cli,
                semantic_version=semantic_version,
                release_tag=release_tag,
                git_commit=str(ready.get("git_commit") or resolved_commit or ""),
            )

        build_dir = self.root / ".building" / f"{cache_key}-{request_id}"
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        src_dir = build_dir / "src"
        home_dir = build_dir / "home"
        home_dir.mkdir(parents=True, exist_ok=True)

        self._run(["git", "clone", "--depth", "1", "--branch", release_tag, "https://github.com/NousResearch/hermes-agent.git", str(src_dir)], cwd=build_dir)
        commit_result = self._run(["git", "rev-parse", "HEAD"], cwd=src_dir)
        git_commit = commit_result.stdout.strip() or resolved_commit or "unknown"
        self._run(["uv", "venv", "venv", "--python", "3.11"], cwd=build_dir)
        self._run(["uv", "pip", "install", "-e", ".[all]"], cwd=src_dir, env={"VIRTUAL_ENV": str(build_dir / "venv")})

        if final_dir.exists():
            shutil.rmtree(final_dir)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        build_dir.replace(final_dir)

        final_src_dir = final_dir / "src"
        final_home_dir = final_dir / "home"
        final_venv = final_dir / "venv"
        self._run(["uv", "pip", "install", "-e", ".[all]"], cwd=final_src_dir, env={"VIRTUAL_ENV": str(final_venv)})
        smoke_env = {"HERMES_HOME": str(final_home_dir)}
        smoke_result = self._run([str(final_venv / "bin" / "hermes"), "--version"], cwd=final_dir, env=smoke_env)
        self._run(["venv/bin/python", "-c", "import hermes_cli.models; import hermes_cli.auth; print('metadata ok')"], cwd=final_dir, env=smoke_env)

        ready_payload = {
            "semantic_version": semantic_version,
            "release_tag": release_tag,
            "git_commit": git_commit,
            "install_mode": "editable-all",
            "python_version": "Python 3.11",
            "hermes_cli_path": str(final_dir / "venv" / "bin" / "hermes"),
            "created_at": self._now(),
            "smoke_test": {"ok": True, "hermes_version": smoke_result.stdout.strip()},
        }
        (final_dir / ".ready.json").write_text(json.dumps(ready_payload, indent=2, sort_keys=True))

        return ToolchainCacheResult(
            ready=True,
            cache_dir=final_dir,
            hermes_cli=final_dir / "venv" / "bin" / "hermes",
            semantic_version=semantic_version,
            release_tag=release_tag,
            git_commit=git_commit,
        )

    def _ready(self, cache_dir: "Path", semantic_version: str, release_tag: str, resolved_commit: str | None) -> bool:
        ready_path = cache_dir / ".ready.json"
        hermes_cli = cache_dir / "venv" / "bin" / "hermes"
        if not ready_path.exists() or not hermes_cli.exists() or not hermes_cli.is_file():
            return False
        try:
            ready = json.loads(ready_path.read_text())
        except json.JSONDecodeError:
            return False
        if ready.get("semantic_version") != semantic_version:
            return False
        if ready.get("release_tag") != release_tag:
            return False
        if ready.get("install_mode") != "editable-all":
            return False
        if str(ready.get("hermes_cli_path")) != str(hermes_cli):
            return False
        if resolved_commit and ready.get("git_commit") != resolved_commit:
            return False
        return self._editable_install_points_at_cache(cache_dir)

    @staticmethod
    def _editable_install_points_at_cache(cache_dir: "Path") -> bool:
        site_packages = cache_dir / "venv" / "lib" / "python3.11" / "site-packages"
        finder_files = tuple(site_packages.glob("__editable___hermes_agent_*_finder.py"))
        if not finder_files:
            return False
        expected_src = str(cache_dir / "src")
        for finder_file in finder_files:
            try:
                content = finder_file.read_text()
            except OSError:
                return False
            if expected_src in content and "/.building/" not in content:
                return True
        return False

    def _resolve_commit_for_ready_check(self, release_tag: str) -> str | None:
        if self._commit_resolver is None:
            return None
        return self._commit_resolver(release_tag)

    def _acquire_lock(self, cache_key: str):
        import fcntl

        lock_dir = self.root / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        handle = (lock_dir / f"{cache_key}.lock").open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    @staticmethod
    def _release_lock(handle: object) -> None:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        handle.close()  # type: ignore[attr-defined]

    def _run(self, argv: list[str], *, cwd: "Path", env: dict[str, str] | None = None) -> ToolchainCommandResult:
        result = self._runner(argv, cwd=cwd, env=env or {})  # type: ignore[misc]
        if result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(argv)}\n{result.stderr}")
        return result

    @staticmethod
    def _default_runner(argv: list[str], *, cwd: "Path", env: dict[str, str]) -> ToolchainCommandResult:
        import os
        import subprocess

        merged_env = os.environ.copy()
        merged_env.update(env)
        try:
            completed = subprocess.run(argv, cwd=cwd, env=merged_env, text=True, capture_output=True, check=False)
        except FileNotFoundError:
            missing = str(argv[0]) if argv else "<empty command>"
            return ToolchainCommandResult(
                stdout="",
                stderr=f"Required command not found in panel toolchain: {missing}. Re-enter the Nix dev shell after updating flake.nix.",
                returncode=127,
            )
        return ToolchainCommandResult(completed.stdout, completed.stderr, completed.returncode)


@dataclass(frozen=True)
class HermesRuntimeMetadata:
    providers: tuple[str, ...]
    models: tuple[str, ...]
    auth_methods: tuple[str, ...]


class HermesRuntimeMetadataService:
    def __init__(
        self,
        *,
        runner: Callable[[list[str]], ToolchainCommandResult] | None = None,
    ) -> None:
        self._runner = runner or HermesToolchainCache._default_runner

    def load(self, *, cache_dir: Path, provider: str) -> HermesRuntimeMetadata:
        cache_dir = cache_dir.resolve()
        python = cache_dir / "venv" / "bin" / "python"
        home = cache_dir / "home"
        home.mkdir(parents=True, exist_ok=True)
        script = _runtime_metadata_script(provider)
        result = self._runner([str(python), "-c", script], cwd=cache_dir, env={"HERMES_HOME": str(home)})  # type: ignore[misc]
        if result.returncode != 0:
            raise RuntimeError(f"Hermes runtime metadata command failed: {result.stderr}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Selected Hermes returned invalid Hermes metadata JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Selected Hermes returned invalid Hermes metadata JSON.")
        error = payload.get("error")
        if isinstance(error, str) and error:
            raise RuntimeError(error)
        providers = _string_tuple(payload.get("providers"))
        models_by_provider = payload.get("models")
        auth_by_provider = payload.get("auth_methods")
        models = _string_tuple(models_by_provider.get(provider) if isinstance(models_by_provider, dict) else None)
        auth_methods = _string_tuple(auth_by_provider.get(provider) if isinstance(auth_by_provider, dict) else None)
        return HermesRuntimeMetadata(providers=providers, models=models, auth_methods=auth_methods)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _runtime_metadata_script(provider: str) -> str:
    provider_literal = json.dumps(provider)
    return """
import json
provider = {provider_literal}
try:
    from hermes_cli.models import list_available_providers, provider_model_ids
    from hermes_cli.providers import get_provider
except Exception as exc:
    print(json.dumps({{"error": f"Could not import Hermes model metadata: {{exc}}"}}))
    raise SystemExit(0)
try:
    from hermes_cli.auth_commands import _OAUTH_CAPABLE_PROVIDERS
except Exception:
    _OAUTH_CAPABLE_PROVIDERS = set()
providers = []
models = {{}}
auth_methods = {{}}

def provider_auth_methods(provider_id):
    methods = []
    pdef = get_provider(provider_id)
    auth_type = getattr(pdef, "auth_type", "api_key") if pdef is not None else "api_key"
    api_key_env_vars = tuple(getattr(pdef, "api_key_env_vars", ()) or ()) if pdef is not None else ()
    if provider_id in _OAUTH_CAPABLE_PROVIDERS or str(auth_type).startswith("oauth") or auth_type == "external_process":
        methods.append("oauth")
    if auth_type == "api_key" or api_key_env_vars or provider_id in _OAUTH_CAPABLE_PROVIDERS:
        methods.append("api_key")
    if not methods:
        methods.append("api_key")
    return methods

for item in list(list_available_providers()):
    if isinstance(item, dict):
        provider_id = item.get("id") or item.get("name") or item.get("provider")
    else:
        provider_id = item
    if not isinstance(provider_id, str) or not provider_id:
        continue
    providers.append(provider_id)
    try:
        raw_models = provider_model_ids(provider_id) if provider_model_ids is not None else []
        models[provider_id] = [model for model in raw_models if isinstance(model, str)]
    except Exception:
        models[provider_id] = []
    auth_methods[provider_id] = provider_auth_methods(provider_id)
print(json.dumps({{"providers": providers, "models": models, "auth_methods": auth_methods}}))
""".format(provider_literal=provider_literal)
