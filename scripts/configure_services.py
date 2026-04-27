# pyright: reportAny=false, reportUnusedCallResult=false, reportUnusedImport=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportImplicitStringConcatenation=false, reportUnnecessaryIsInstance=false
from __future__ import annotations

import json
import os
import pathlib
import pty
import re
import select
import shutil
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Protocol, final

from scripts import configure_logic as logic
from scripts.configure_state import LabeledValue, WizardState


_SECRET_PLACEHOLDER = "***"


APPLY_EFFECT_ORDER: tuple[str, ...] = (
    "persist_cloud",
    "persist_server",
    "persist_hermes",
    "persist_telegram",
    "stage_extras",
    "ensure_ssh_key",
    "reconcile_ssh_alias",
    "flush_env",
)


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str


class CommandRunnerLike(Protocol):
    def run(self, argv: list[str], env: dict[str, str] | None = None) -> CommandResult: ...


class EnvStoreLike(Protocol):
    def get(self, key: str) -> str: ...

    def set(self, key: str, value: str) -> None: ...


class ProviderServiceLike(Protocol):
    def location_options(self, provider: str, token: str) -> list[LabeledValue]: ...

    def server_type_options(self, provider: str, location: str, token: str) -> list[LabeledValue]: ...


class HermesServiceLike(Protocol):
    def provider_ids(self) -> list[str]: ...

    def model_ids(self, provider: str) -> list[str]: ...

    def provider_auth_metadata(self, provider: str) -> tuple[str, list[str]]: ...

    def run_oauth_add(self, provider: str, on_output: Callable[[str], None] | None = None) -> tuple[bool, str]: ...

    def validate_api_key(self, provider: str, token: str) -> str: ...


class ConfigureOrchestratorLike(Protocol):
    env: EnvStoreLike
    provider: ProviderServiceLike
    hermes: HermesServiceLike
    applied: bool
    cloud_persisted: bool
    server_persisted: bool
    hermes_persisted: bool
    hermes_api_validated: bool
    telegram_persisted: bool
    telegram_validated: bool

    def load_initial_state(self) -> WizardState: ...

    def provider_token_present(self, state: WizardState) -> bool: ...

    def hermes_available_auth_methods(self, auth_type: str) -> list[str]: ...

    def hermes_existing_auth_method_for_combo(self, state: WizardState) -> str: ...

    def persist_cloud_step(self, state: WizardState) -> None: ...

    def persist_server_step(self, state: WizardState) -> None: ...

    def persist_hermes_step(self, state: WizardState) -> None: ...

    def persist_telegram_step(self, state: WizardState) -> None: ...

    def resolve_release_tag_for_version(self, version: str) -> str: ...

    def validate_hermes_api_key_setup(self, state: WizardState) -> str: ...

    def validate_telegram_setup(self, state: WizardState) -> str: ...

    def apply(self, state: WizardState) -> list[tuple[str, str, str]]: ...


@dataclass(frozen=True)
class ApplyPlan:
    state: WizardState
    effects: tuple[str, ...]


class ConfigureServiceError(RuntimeError):
    pass


@final
class CommandRunner:
    def __init__(self, timeout_seconds: int = 12, retries: int = 0) -> None:
        self.timeout_seconds = timeout_seconds
        self.retries = retries

    def run(self, argv: list[str], env: dict[str, str] | None = None) -> CommandResult:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=True,
                    env=env,
                )
                return CommandResult(stdout=proc.stdout, stderr=proc.stderr)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                last_error = exc
                if attempt < self.retries:
                    continue
                raise ConfigureServiceError(f"command failed: {' '.join(argv)} ({exc})") from exc
        raise ConfigureServiceError(f"command failed: {' '.join(argv)} ({last_error})")


@final
class EnvStore:
    def __init__(self, root_dir: pathlib.Path) -> None:
        self.root_dir = root_dir
        self.env_file = root_dir / ".env"
        self.template = root_dir / ".env.example"
        self._staged: dict[str, str] = {}

    def ensure(self) -> None:
        if not self.template.exists():
            raise ConfigureServiceError(f"missing env template: {self.template}")
        if not self.env_file.exists():
            shutil.copy2(self.template, self.env_file)
        self.env_file.chmod(0o600)

    def get(self, key: str) -> str:
        if key in self._staged:
            return self._staged[key]
        return logic.get_env_value(self.env_file, key)

    def set(self, key: str, value: str) -> None:
        if key in self._staged:
            if self._staged[key] == value:
                return
            self._staged[key] = value
            return

        if logic.get_env_value(self.env_file, key) == value:
            return
        self._staged[key] = value

    def values(self, keys: list[str]) -> dict[str, str]:
        return {key: self.get(key) for key in keys}

    def flush(self) -> None:
        if not self._staged:
            return
        # Build the new file contents in memory then commit atomically via
        # temp + os.replace, so a crash cannot leave a half-written .env.
        content = self.env_file.read_text() if self.env_file.exists() else ""
        for key, value in self._staged.items():
            content = self._upsert_env_line(content, key, value)

        tmp_path = self.env_file.with_name(self.env_file.name + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as tmp_file:
                tmp_file.write(content)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            tmp_path.chmod(0o600)
            os.replace(str(tmp_path), str(self.env_file))
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        self._staged.clear()
        self.env_file.chmod(0o600)

    @staticmethod
    def _upsert_env_line(content: str, key: str, value: str) -> str:
        line = f"{key}={value}"
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pattern.search(content):
            return pattern.sub(line, content, count=1)
        if content and not content.endswith("\n"):
            content += "\n"
        return content + line + "\n"


@final
class ProviderService:
    def __init__(self, runner: CommandRunnerLike) -> None:
        self.runner = runner

    def location_options(self, provider: str, token: str) -> list[LabeledValue]:
        if provider == "hetzner":
            self._require_binary("hcloud")
            result = self.runner.run(["hcloud", "location", "list", "-o", "json"], env=self._env_with_secret("HCLOUD_TOKEN", token))
            payload = json.loads(result.stdout)
            options = [
                LabeledValue(
                    label=f"{item['country'].upper()}, {item['city']} ({item['name']})",
                    value=item["name"],
                )
                for item in payload
            ]
            return sorted(options, key=lambda x: x.label.lower())

        self._require_binary("linode-cli")
        env = self._env_with_secret("LINODE_CLI_TOKEN", token)
        self._validate_linode_token(env)
        result = self.runner.run(["linode-cli", "regions", "list", "--json", "--no-defaults", "--suppress-warnings"], env=env)
        payload = json.loads(result.stdout)
        options = [
            LabeledValue(
                label=f"{item['country'].upper()}, {item['label']} ({item['id']})",
                value=item["id"],
            )
            for item in payload
        ]
        return sorted(options, key=lambda x: x.label.lower())

    def server_type_options(self, provider: str, location: str, token: str) -> list[LabeledValue]:
        if provider == "hetzner":
            self._require_binary("hcloud")
            payload = json.loads(
                self.runner.run(["hcloud", "server-type", "list", "-o", "json"], env=self._env_with_secret("HCLOUD_TOKEN", token)).stdout
            )
            rows: list[tuple[float, LabeledValue]] = []
            for item in payload:
                if item.get("deprecated"):
                    continue
                prices = [
                    float(price["price_monthly"].get("gross") or price["price_monthly"].get("net"))
                    for price in item.get("prices", [])
                    if price.get("location") == location and price.get("price_monthly")
                ]
                if not prices:
                    continue
                monthly = min(prices)
                label = (
                    f"{item['name']} • {item.get('cores')} vCPU • {item.get('memory')} GB RAM • "
                    f"{item.get('disk')} GB disk • ${monthly:.2f}/mo"
                )
                rows.append((monthly, LabeledValue(label=label, value=item["name"])))
        else:
            self._require_binary("linode-cli")
            env = self._env_with_secret("LINODE_CLI_TOKEN", token)
            self._validate_linode_token(env)
            payload = json.loads(
                self.runner.run(
                    ["linode-cli", "linodes", "types", "--json", "--no-defaults", "--suppress-warnings"],
                    env=env,
                ).stdout
            )
            rows = []
            for item in payload:
                if item.get("deprecated"):
                    continue
                regions = item.get("regions")
                if regions and location not in regions:
                    continue
                monthly = float(item.get("price", {}).get("monthly") or 999999)
                disk_gb = int(item.get("disk", 0) / 1024)
                label = (
                    f"{item['id']} • {item.get('vcpus')} vCPU • {item.get('memory')} MB RAM • "
                    f"{disk_gb} GB disk • ${monthly:.2f}/mo"
                )
                rows.append((monthly, LabeledValue(label=label, value=item["id"])))

        rows.sort(key=lambda pair: pair[0])
        if not rows:
            raise ConfigureServiceError(f"no server types returned by provider API for location {location}")

        best_price = rows[0][0]
        output: list[LabeledValue] = []
        for price, item in rows:
            output.append(LabeledValue(label=item.label, value=item.value, recommended=(price == best_price)))
        output.sort(key=lambda x: x.label.lower())
        return output

    @staticmethod
    def _env_with_secret(key: str, value: str) -> dict[str, str]:
        env = dict(os.environ)
        env[key] = value
        return env

    def _validate_linode_token(self, env: dict[str, str]) -> None:
        try:
            output = self.runner.run(
                [
                    "linode-cli",
                    "profile",
                    "view",
                    "--json",
                    "--no-defaults",
                    "--suppress-warnings",
                ],
                env=env,
            ).stdout
            payload = json.loads(output)
            if isinstance(payload, list):
                payload = payload[0] if payload else {}
            if not isinstance(payload, dict) or not payload:
                raise ConfigureServiceError(
                    "Linode token validation failed: unexpected profile response."
                )
        except ConfigureServiceError as exc:
            raise ConfigureServiceError(
                "Linode token validation failed. The token is invalid, expired, or missing required scope."
            ) from exc

    @staticmethod
    def _require_binary(binary: str) -> None:
        if not shutil.which(binary):
            raise ConfigureServiceError(f"{binary} not found in toolchain")


@final
class HermesService:
    def __init__(self, runner: CommandRunnerLike, root_dir: pathlib.Path) -> None:
        self.runner = runner
        self.root_dir = root_dir
        self.runtime_dir = root_dir / "bootstrap" / "runtime"
        self.auth_home = self.runtime_dir / "hermes-home"
        self.auth_artifact = self.runtime_dir / "hermes-auth.json"

    def bundled_version(self) -> str:
        try:
            out = self.runner.run(["hermes", "--version"]).stdout
        except FileNotFoundError:
            return "0.10.0"
        version_match = re.search(r"\bv([0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z]+)?)\b", out)
        if version_match:
            return version_match.group(1)
        return "0.10.0"

    def bundled_release_tag(self) -> str:
        try:
            out = self.runner.run(["hermes", "--version"]).stdout
        except FileNotFoundError:
            return "v2026.4.16"
        release_match = re.search(r"\(([0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z]+)?)\)", out)
        if release_match:
            return f"v{release_match.group(1)}"
        return "v2026.4.16"

    def provider_ids(self) -> list[str]:
        values = self._run_python_snippet(
            "from hermes_cli.models import list_available_providers\n"
            "ids=[]\n"
            "for provider in list_available_providers():\n"
            "    value = provider.get('id') if isinstance(provider, dict) else getattr(provider, 'id', None)\n"
            "    if value: ids.append(value)\n"
            "print('\\n'.join(sorted(set(ids), key=str.lower)))"
        )
        return [line for line in values.splitlines() if line]

    def model_ids(self, provider: str) -> list[str]:
        values = self._run_python_snippet(
            "import sys\n"
            "from hermes_cli.models import provider_model_ids\n"
            "seen=set()\n"
            "rows=[]\n"
            "for model_id in provider_model_ids(sys.argv[1]):\n"
            "    if model_id in seen: continue\n"
            "    seen.add(model_id)\n"
            "    rows.append(model_id)\n"
            "print('\\n'.join(rows))",
            [provider],
        )
        return [line for line in values.splitlines() if line]

    def provider_auth_metadata(self, provider: str) -> tuple[str, list[str]]:
        out = self._run_python_snippet(
            "import json,sys\n"
            "from hermes_cli.auth import PROVIDER_REGISTRY, get_auth_status\n"
            "provider=sys.argv[1]\n"
            "pc=PROVIDER_REGISTRY.get(provider)\n"
            "auth_type=(getattr(pc, 'auth_type', 'api_key') if pc else 'api_key') or 'api_key'\n"
            "env_vars=list(getattr(pc, 'api_key_env_vars', ()) or ()) if pc else []\n"
            "supports_api_key=(auth_type == 'api_key') or bool(env_vars)\n"
            "supports_oauth=auth_type.startswith('oauth')\n"
            "try:\n"
            "    status=get_auth_status(provider) or {}\n"
            "except Exception:\n"
            "    status={}\n"
            "if isinstance(status, dict):\n"
            "    if status.get('api_key'):\n"
            "        supports_api_key=True\n"
            "    mode=str(status.get('auth_mode') or '').lower()\n"
            "    if mode and mode != 'api_key':\n"
            "        supports_oauth=True\n"
            "if supports_oauth and supports_api_key:\n"
            "    display=f\"{auth_type if auth_type.startswith('oauth') else 'oauth'}+api_key\"\n"
            "elif supports_oauth:\n"
            "    display=auth_type\n"
            "elif supports_api_key:\n"
            "    display='api_key'\n"
            "else:\n"
            "    display=auth_type or 'api_key'\n"
            "if supports_api_key and not env_vars:\n"
            "    env_vars=['HERMES_API_KEY']\n"
            "print(json.dumps({'auth_type': display, 'env_vars': env_vars}))",
            [provider],
        ).strip()
        payload = json.loads(out) if out else {}
        auth_type = str(payload.get("auth_type") or "api_key")
        env_vars = [str(item) for item in payload.get("env_vars", []) if str(item)]
        return auth_type, env_vars

    def has_local_auth(self, provider: str) -> bool:
        status = self._run_python_snippet(
            "import sys\n"
            "from hermes_cli.auth import get_auth_status\n"
            "state = get_auth_status(sys.argv[1]) or {}\n"
            "print('yes' if bool(state.get('logged_in')) else 'no')",
            [provider],
            env=self._auth_env(),
        ).strip()
        return status == "yes"

    def validate_api_key(self, provider: str, api_key: str) -> str:
        key = (api_key or "").strip()
        if not key:
            raise ConfigureServiceError("Hermes API key cannot be empty.")

        provider_id = (provider or "").strip().lower()
        endpoints: dict[str, tuple[str, list[str]]] = {
            "openai": (
                "https://api.openai.com/v1/models",
                ["-H", f"Authorization: Bearer {key}"],
            ),
            "openai-codex": (
                "https://api.openai.com/v1/models",
                ["-H", f"Authorization: Bearer {key}"],
            ),
            "anthropic": (
                "https://api.anthropic.com/v1/models",
                [
                    "-H",
                    f"x-api-key: {key}",
                    "-H",
                    "anthropic-version: 2023-06-01",
                ],
            ),
            "groq": (
                "https://api.groq.com/openai/v1/models",
                ["-H", f"Authorization: Bearer {key}"],
            ),
            "xai": (
                "https://api.x.ai/v1/models",
                ["-H", f"Authorization: Bearer {key}"],
            ),
        }

        config = endpoints.get(provider_id)
        if not config:
            return f"Hermes API key presence verified for {provider_id or 'provider'}."

        url, headers = config
        argv = ["curl", "-fsS", "--max-time", "10", *headers, url]
        try:
            output = self.runner.run(argv).stdout
            payload = json.loads(output)
            if isinstance(payload, dict) and payload.get("error"):
                raise ConfigureServiceError(str(payload.get("error")))
        except Exception as exc:
            raise ConfigureServiceError(
                f"Invalid Hermes API key for {provider_id}."
            ) from exc

        return f"Hermes API key valid for {provider_id}."

    def auth_artifact_exists(self) -> bool:
        return self.auth_artifact.exists() and self.auth_artifact.stat().st_size > 0

    def run_oauth_add(
        self,
        provider: str,
        on_output: Callable[[str], None] | None = None,
    ) -> tuple[bool, str]:
        hermes_bin = shutil.which("hermes")
        if not hermes_bin:
            raise ConfigureServiceError("hermes CLI not found in toolchain")
        env = self._auth_env()
        argv = [hermes_bin, "auth", "add", provider, "--type", "oauth"]

        def emit(chunk: str) -> None:
            if on_output and chunk:
                on_output(chunk)

        master_fd, slave_fd = pty.openpty()
        proc = subprocess.Popen(
            argv,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
        os.close(slave_fd)

        chunks: list[str] = []
        started = time.monotonic()
        timed_out = False

        try:
            while True:
                if time.monotonic() - started > 300:
                    timed_out = True
                    proc.kill()
                    break

                readable, _, _ = select.select([master_fd], [], [], 0.2)
                if readable:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        data = b""
                    if data:
                        chunk = data.decode("utf-8", errors="replace")
                        chunks.append(chunk)
                        emit(chunk)

                if proc.poll() is not None:
                    while True:
                        try:
                            data = os.read(master_fd, 4096)
                        except OSError:
                            break
                        if not data:
                            break
                        chunk = data.decode("utf-8", errors="replace")
                        chunks.append(chunk)
                        emit(chunk)
                    break

            return_code = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            return_code = proc.wait(timeout=5)
        except Exception:
            proc.kill()
            raise
        finally:
            os.close(master_fd)

        output = "".join(chunks).strip()
        if timed_out:
            timeout_note = "OAuth command timed out after 300 seconds. Complete browser login and retry if needed."
            output = f"{output}\n\n{timeout_note}".strip()
            return False, output

        if return_code != 0:
            return False, output or f"hermes auth add failed with exit code {return_code}"

        staged = self.stage_local_auth_artifact()
        if staged:
            output = (output + "\n\nOAuth auth file captured.").strip()
        else:
            output = (output + "\n\nOAuth command succeeded, but no auth file was captured.").strip()
        return staged, output

    def stage_local_auth_artifact(self) -> bool:
        src = self.auth_home / "auth.json"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.auth_home.mkdir(parents=True, exist_ok=True)
        if src.exists() and src.stat().st_size > 0:
            self.auth_artifact.write_text(src.read_text())
            self.auth_artifact.chmod(0o600)
            return True
        if self.auth_artifact.exists():
            self.auth_artifact.unlink()
        return False

    def clear_auth_artifact(self) -> None:
        if self.auth_artifact.exists():
            self.auth_artifact.unlink()

    def _auth_env(self) -> dict[str, str]:
        env = dict(os.environ)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.auth_home.mkdir(parents=True, exist_ok=True)
        env["HERMES_HOME"] = str(self.auth_home)
        return env

    def _run_python_snippet(self, snippet: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> str:
        hermes_python = self.resolve_hermes_python()
        argv = [hermes_python, "-c", snippet]
        if args:
            argv.extend(args)
        run_env = dict(os.environ)
        if env:
            run_env.update(env)
        return self.runner.run(argv, env=run_env).stdout

    def resolve_hermes_python(self) -> str:
        hermes_bin = shutil.which("hermes")
        if not hermes_bin:
            raise ConfigureServiceError("hermes CLI not found in toolchain")
        text = pathlib.Path(hermes_bin).read_text(errors="ignore")
        match = re.search(r"^export HERMES_PYTHON='([^']+)'", text, re.MULTILINE)
        if not match:
            raise ConfigureServiceError("failed to resolve HERMES_PYTHON from hermes wrapper")
        candidate = match.group(1)
        if not os.access(candidate, os.X_OK):
            raise ConfigureServiceError(f"resolved HERMES_PYTHON is not executable: {candidate}")
        return candidate


@final
class ConfigureOrchestrator:
    def __init__(self, root_dir: pathlib.Path, runner: CommandRunnerLike | None = None) -> None:
        self.root_dir = root_dir
        self.runner = runner or CommandRunner()
        self.env = EnvStore(root_dir)
        self.provider = ProviderService(self.runner)
        self.hermes = HermesService(self.runner, root_dir)

    def load_initial_state(self) -> WizardState:
        self.env.ensure()
        keys = [
            "TF_VAR_cloud_provider",
            "TF_VAR_server_image",
            "TF_VAR_server_location",
            "TF_VAR_server_type",
            "TF_VAR_hostname",
            "TF_VAR_admin_username",
            "TF_VAR_admin_group",
            "BOOTSTRAP_SSH_PRIVATE_KEY_PATH",
            "HERMES_AGENT_VERSION",
            "HERMES_AGENT_RELEASE_TAG",
            "TF_VAR_hermes_provider",
            "TF_VAR_hermes_model",
            "HERMES_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWLIST_IDS",
            "HCLOUD_TOKEN",
            "LINODE_TOKEN",
        ]
        current = self.env.values(keys)
        current["HERMES_AUTH_ARTIFACT"] = (
            str(self.hermes.auth_artifact) if self.hermes_auth_artifact_present() else ""
        )
        current["SSH_ALIAS"] = "active" if self.is_repo_ssh_alias_active() else "inactive"

        provider = current.get("TF_VAR_cloud_provider", "")
        if provider not in {"hetzner", "linode"}:
            provider = "hetzner"

        version = current.get("HERMES_AGENT_VERSION") or ""
        if not logic.is_valid_semver(version):
            version = self.hermes.bundled_version()

        release_tag = current.get("HERMES_AGENT_RELEASE_TAG") or ""
        if not logic.is_valid_release_tag(release_tag):
            release_tag = self.hermes.bundled_release_tag()

        return WizardState(
            provider=provider,
            provider_token_key="HCLOUD_TOKEN" if provider == "hetzner" else "LINODE_TOKEN",
            server_image=logic.server_image_for_provider(provider),
            location=current.get("TF_VAR_server_location", ""),
            server_type=current.get("TF_VAR_server_type", ""),
            hostname=current.get("TF_VAR_hostname", ""),
            admin_username=current.get("TF_VAR_admin_username", ""),
            admin_group=current.get("TF_VAR_admin_group", ""),
            ssh_private_key_path=current.get("BOOTSTRAP_SSH_PRIVATE_KEY_PATH", ""),
            hermes_agent_version=version,
            hermes_agent_release_tag=release_tag,
            hermes_provider=current.get("TF_VAR_hermes_provider", ""),
            hermes_model=current.get("TF_VAR_hermes_model", ""),
            telegram_allowlist_ids=current.get("TELEGRAM_ALLOWLIST_IDS", ""),
            original_values=current,
        )

    def provider_token_present(self, state: WizardState) -> bool:
        key = state.provider_token_env_key()
        value = self.env.get(key)
        return bool(value and value != _SECRET_PLACEHOLDER)

    def telegram_token_present(self) -> bool:
        value = self.env.get("TELEGRAM_BOT_TOKEN")
        return bool(value and value != _SECRET_PLACEHOLDER)

    def validate_telegram_setup(self, state: WizardState) -> str:
        if not state.telegram_allowlist_ids:
            raise ConfigureServiceError("Allowlist required.")
        if not logic.is_valid_telegram_allowlist(state.telegram_allowlist_ids):
            raise ConfigureServiceError(
                "Use comma-separated integers: 12345,-100987654321"
            )

        token = self._effective_telegram_token(state)
        if not token:
            raise ConfigureServiceError("Telegram bot token cannot be empty.")

        token_encoded = urllib.parse.quote(token, safe="")
        url = f"https://api.telegram.org/bot{token_encoded}/getMe"
        try:
            out = self.runner.run(["curl", "-fsS", "--max-time", "10", url]).stdout
            payload = json.loads(out)
        except Exception as exc:
            raise ConfigureServiceError(
                "Invalid Telegram bot token."
            ) from exc

        if not isinstance(payload, dict) or not payload.get("ok"):
            raise ConfigureServiceError("Invalid Telegram bot token.")

        result = payload.get("result") if isinstance(payload, dict) else {}
        username = ""
        if isinstance(result, dict):
            username = str(result.get("username") or "").strip()
            if not username:
                username = str(result.get("id") or "").strip()

        if username:
            return f"Telegram token valid (@{username}) • allowlist format valid."
        return "Telegram token valid • allowlist format valid."

    def _effective_telegram_token(self, state: WizardState) -> str:
        if state.telegram_bot_token_replace:
            return state.telegram_bot_token_input.strip()
        existing = self.env.get("TELEGRAM_BOT_TOKEN")
        if not existing or existing == _SECRET_PLACEHOLDER:
            return ""
        return existing.strip()

    def hermes_api_key_present(self) -> bool:
        value = self.env.get("HERMES_API_KEY")
        return bool(value and value != _SECRET_PLACEHOLDER)

    def hermes_auth_artifact_present(self) -> bool:
        return self.hermes.auth_artifact_exists()

    @staticmethod
    def hermes_available_auth_methods(auth_type: str) -> list[str]:
        mode = (auth_type or "").lower()
        methods: list[str] = []
        if "api_key" in mode:
            methods.append("api_key")
        if "oauth" in mode:
            methods.append("oauth")
        if not methods:
            methods = ["api_key"]
        return methods

    def hermes_existing_auth_method_for_combo(self, state: WizardState) -> str:
        same_provider = (
            state.hermes_provider
            == (state.original_values.get("TF_VAR_hermes_provider", "") or "")
        )
        if not same_provider:
            return ""
        if self.hermes_auth_artifact_present():
            return "oauth"
        if self.hermes_api_key_present():
            return "api_key"
        return ""

    def resolve_release_tag_for_version(self, version: str) -> str:
        if not logic.is_valid_semver(version):
            return ""
        try:
            bundled_version = self.hermes.bundled_version()
            if version == bundled_version:
                bundled_tag = self.hermes.bundled_release_tag()
                if logic.is_valid_release_tag(bundled_tag):
                    return bundled_tag
        except ConfigureServiceError:
            pass
        return logic.release_tag_for_version(version)

    def validate_hermes_api_key_setup(self, state: WizardState) -> str:
        if state.hermes_auth_method != "api_key":
            return ""

        token = state.hermes_api_key_input.strip()
        if not token:
            existing = self.env.get("HERMES_API_KEY")
            if existing and existing != _SECRET_PLACEHOLDER:
                token = existing

        if not token:
            raise ConfigureServiceError("API key auth selected, but no HERMES_API_KEY is set.")

        return self.hermes.validate_api_key(state.hermes_provider, token)

    def persist_cloud_step(self, state: WizardState) -> None:
        state.server_image = logic.server_image_for_provider(state.provider)
        self.env.set("TF_VAR_cloud_provider", state.provider)
        self.env.set("TF_VAR_server_image", state.server_image)

        provider_token_key = state.provider_token_env_key()
        if state.provider_token_replace or not self.provider_token_present(state):
            self.env.set(provider_token_key, state.provider_token_input)

    def persist_server_step(self, state: WizardState) -> None:
        self.env.set("TF_VAR_server_location", state.location)
        self.env.set("TF_VAR_server_type", state.server_type)
        self.env.set("TF_VAR_hostname", state.hostname)
        self.env.set("TF_VAR_admin_username", state.admin_username)
        self.env.set("TF_VAR_admin_group", state.admin_group)
        self.env.set("BOOTSTRAP_SSH_PRIVATE_KEY_PATH", state.ssh_private_key_path)

    def persist_hermes_step(self, state: WizardState) -> None:
        state.hermes_agent_release_tag = self.resolve_release_tag_for_version(
            state.hermes_agent_version
        )
        self.env.set("HERMES_AGENT_RELEASE_TAG", state.hermes_agent_release_tag)

        if state.hermes_auth_method == "api_key":
            if state.hermes_api_key_input:
                self.env.set("HERMES_API_KEY", state.hermes_api_key_input)
            if not self.hermes_api_key_present():
                raise ConfigureServiceError("API key auth selected, but no HERMES_API_KEY is set.")
            if self.hermes_auth_artifact_present():
                self.hermes.clear_auth_artifact()
            state.recap_auth_artifact = "none"
        else:
            self.env.set("HERMES_API_KEY", "")
            if not self.hermes_auth_artifact_present():
                if self.hermes.has_local_auth(state.hermes_provider):
                    self.hermes.stage_local_auth_artifact()
            if not self.hermes_auth_artifact_present():
                raise ConfigureServiceError("OAuth selected, but no hermes-auth.json is available. Run OAuth first.")
            state.recap_auth_artifact = str(self.hermes.auth_artifact)

    def persist_telegram_step(self, state: WizardState) -> None:
        self.env.set("TELEGRAM_ALLOWLIST_IDS", state.telegram_allowlist_ids)

        if state.telegram_bot_token_replace or not self.telegram_token_present():
            self.env.set("TELEGRAM_BOT_TOKEN", state.telegram_bot_token_input)

    def build_apply_plan(self, state: WizardState) -> ApplyPlan:
        return ApplyPlan(state=state, effects=APPLY_EFFECT_ORDER)

    def execute_apply_plan(self, plan: ApplyPlan) -> list[tuple[str, str, str]]:
        for effect in plan.effects:
            self._run_apply_effect(effect, plan.state)
        return plan.state.recap_rows()

    def apply(self, state: WizardState) -> list[tuple[str, str, str]]:
        return self.execute_apply_plan(self.build_apply_plan(state))

    def _run_apply_effect(self, effect: str, state: WizardState) -> None:
        if effect == "persist_cloud":
            self.persist_cloud_step(state)
        elif effect == "persist_server":
            self.persist_server_step(state)
        elif effect == "persist_hermes":
            self.persist_hermes_step(state)
        elif effect == "persist_telegram":
            self.persist_telegram_step(state)
        elif effect == "stage_extras":
            self.env.set("HERMES_AGENT_VERSION", state.hermes_agent_version)
            self.env.set("TF_VAR_hermes_provider", state.hermes_provider)
            self.env.set("TF_VAR_hermes_model", state.hermes_model)
        elif effect == "ensure_ssh_key":
            ssh_private_path, public_key = self.ensure_ssh_key_material(
                state.ssh_private_key_path
            )
            state.ssh_private_key_path = ssh_private_path
            self.env.set("BOOTSTRAP_SSH_PRIVATE_KEY_PATH", ssh_private_path)
            self.env.set("TF_VAR_admin_ssh_public_key", f'"{public_key}"')
        elif effect == "reconcile_ssh_alias":
            if self._should_reconcile_ssh_alias(state):
                if state.add_ssh_alias:
                    self.ensure_repo_ssh_alias(
                        state.admin_username,
                        state.ssh_private_key_path,
                        "22",
                        state.hostname,
                    )
                else:
                    self.remove_repo_ssh_alias()
        elif effect == "flush_env":
            self.env.flush()
        else:
            raise ConfigureServiceError(f"unknown apply effect: {effect}")

    def _desired_ssh_alias_state(self, state: WizardState) -> str:
        return "active" if state.add_ssh_alias else "inactive"

    def _should_reconcile_ssh_alias(self, state: WizardState) -> bool:
        recorded = (state.original_values.get("SSH_ALIAS", "") or "").strip().lower()
        desired = self._desired_ssh_alias_state(state)
        if recorded in {"active", "inactive"}:
            return recorded != desired
        return self.is_repo_ssh_alias_active() != (desired == "active")

    def is_repo_ssh_alias_active(self) -> bool:
        repo_ssh_config = self.root_dir / ".ssh" / "config"
        home_ssh_config = pathlib.Path.home() / ".ssh" / "config"
        include_line = f"Include {repo_ssh_config}"

        if not repo_ssh_config.exists() or not home_ssh_config.exists():
            return False

        home_lines = home_ssh_config.read_text().splitlines()
        if include_line not in home_lines:
            return False

        repo_text = repo_ssh_config.read_text()
        return bool(self._ssh_host_block_pattern("hermes-vps").search(repo_text))

    def ensure_ssh_key_material(self, preferred_path: str) -> tuple[str, str]:
        key_path = pathlib.Path(preferred_path or pathlib.Path.home() / ".ssh" / "hermes-vps").expanduser()
        pub_path = pathlib.Path(str(key_path) + ".pub")

        if not key_path.exists() or not pub_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            self.runner.run(["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", "hermes-vps"])

        key_path.chmod(0o600)
        pub_path.chmod(0o644)

        public_key = pub_path.read_text().strip()
        if not public_key:
            raise ConfigureServiceError(f"SSH public key is empty: {pub_path}")

        return str(key_path), public_key

    def ensure_repo_ssh_alias(self, alias_user: str, alias_key_path: str, alias_port: str, selected_hostname: str) -> bool:
        repo_ssh_dir = self.root_dir / ".ssh"
        repo_ssh_config = repo_ssh_dir / "config"
        home_ssh_dir = pathlib.Path.home() / ".ssh"
        home_ssh_config = home_ssh_dir / "config"

        alias_hostname = selected_hostname if "." in selected_hostname else "REPLACE_WITH_PUBLIC_IP"

        repo_ssh_dir.mkdir(parents=True, exist_ok=True)
        home_ssh_dir.mkdir(parents=True, exist_ok=True)

        if not home_ssh_config.exists():
            home_ssh_config.touch()
        if not repo_ssh_config.exists():
            repo_ssh_config.touch()

        home_ssh_config.chmod(0o600)
        repo_ssh_config.chmod(0o600)

        include_line = f"Include {repo_ssh_config}"
        changed = False

        home_text = home_ssh_config.read_text()
        if include_line not in home_text.splitlines():
            home_ssh_config.write_text(home_text + ("\n" if home_text and not home_text.endswith("\n") else "") + include_line + "\n")
            changed = True

        repo_text = repo_ssh_config.read_text()
        block = (
            "Host hermes-vps\n"
            f"  HostName {alias_hostname}\n"
            f"  User {alias_user}\n"
            f"  Port {alias_port}\n"
            f"  IdentityFile {alias_key_path}\n"
            "  IdentitiesOnly yes\n"
        )
        updated_repo_text = self._upsert_ssh_host_block(repo_text, "hermes-vps", block)
        if updated_repo_text != repo_text:
            repo_ssh_config.write_text(updated_repo_text)
            changed = True

        return changed

    def remove_repo_ssh_alias(self) -> bool:
        repo_ssh_config = self.root_dir / ".ssh" / "config"
        home_ssh_config = pathlib.Path.home() / ".ssh" / "config"
        include_line = f"Include {repo_ssh_config}"
        changed = False

        if home_ssh_config.exists():
            home_text = home_ssh_config.read_text()
            filtered = [line for line in home_text.splitlines() if line.strip() != include_line]
            normalized = "\n".join(filtered)
            if filtered:
                normalized += "\n"
            if normalized != home_text:
                home_ssh_config.write_text(normalized)
                home_ssh_config.chmod(0o600)
                changed = True

        if repo_ssh_config.exists():
            repo_text = repo_ssh_config.read_text()
            updated_repo_text = self._remove_ssh_host_block(repo_text, "hermes-vps")
            if updated_repo_text != repo_text:
                repo_ssh_config.write_text(updated_repo_text)
                repo_ssh_config.chmod(0o600)
                changed = True

        return changed

    @staticmethod
    def _ssh_host_block_pattern(alias: str) -> re.Pattern[str]:
        return re.compile(
            rf"(?ms)^[ \t]*Host[ \t]+{re.escape(alias)}(?:[ \t].*)?\n(?:^(?![ \t]*Host[ \t]).*\n?)*"
        )

    @classmethod
    def _upsert_ssh_host_block(cls, config_text: str, alias: str, block: str) -> str:
        pattern = cls._ssh_host_block_pattern(alias)
        block_text = block.strip("\n")
        if pattern.search(config_text):
            return pattern.sub(block_text + "\n", config_text, count=1)

        base = config_text.rstrip("\n")
        if base:
            return base + "\n\n" + block_text + "\n"
        return block_text + "\n"

    @classmethod
    def _remove_ssh_host_block(cls, config_text: str, alias: str) -> str:
        pattern = cls._ssh_host_block_pattern(alias)
        text = pattern.sub("", config_text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text
