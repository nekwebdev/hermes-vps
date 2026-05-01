from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Self, final

from scripts import configure_logic as logic
from scripts.configure_services import EnvStore

CloudProvider = Literal["hetzner", "linode"]
SECRET_KEYS: frozenset[str] = frozenset(
    {
        "HCLOUD_TOKEN",
        "LINODE_TOKEN",
        "HERMES_API_KEY",
        "TELEGRAM_BOT_TOKEN",
    }
)
_PROVIDER_IMAGE: dict[CloudProvider, str] = {
    "hetzner": "debian-13",
    "linode": "linode/debian13",
}


@dataclass
class SecretDraft:
    """Panel-editable secret slot.

    Existing secrets are represented by presence only.  The secret value is only
    populated when the operator explicitly supplies a replacement.
    """

    present: bool = False
    replacement: str | None = None

    @classmethod
    def keep_existing(cls, present: bool) -> Self:
        return cls(present=present, replacement=None)

    @classmethod
    def replace(cls, value: str) -> Self:
        return cls(present=bool(value), replacement=value)

    def display(self) -> str:
        if self.replacement is not None:
            return "<replacement pending>"
        if self.present:
            return "<set: keep existing>"
        return "<unset>"


@dataclass
class ProviderConfigDraft:
    provider: CloudProvider = "hetzner"
    hcloud_token: SecretDraft = field(default_factory=SecretDraft)
    linode_token: SecretDraft = field(default_factory=SecretDraft)


@dataclass
class ServerConfigDraft:
    location: str = ""
    server_type: str = ""
    image: str = ""
    hostname: str = ""
    admin_username: str = ""
    admin_group: str = ""
    ssh_private_key_path: str = ""
    ssh_port: str = "22"


@dataclass
class HermesConfigDraft:
    provider: str = ""
    model: str = ""
    agent_version: str = ""
    agent_release_tag: str = ""
    api_key: SecretDraft = field(default_factory=SecretDraft)


@dataclass
class GatewayConfigDraft:
    telegram_bot_token: SecretDraft = field(default_factory=SecretDraft)
    telegram_allowlist_ids: str = ""
    telegram_poll_timeout: str = "30"


@dataclass
class ProjectConfigDraft:
    provider: ProviderConfigDraft = field(default_factory=ProviderConfigDraft)
    server: ServerConfigDraft = field(default_factory=ServerConfigDraft)
    hermes: HermesConfigDraft = field(default_factory=HermesConfigDraft)
    gateway: GatewayConfigDraft = field(default_factory=GatewayConfigDraft)
    review_required_fields: tuple[str, ...] = ()
    original_env: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def change_provider(self, provider: CloudProvider) -> None:
        if provider == self.provider.provider:
            return
        self.provider.provider = provider
        self.server.location = ""
        self.server.server_type = ""
        self.server.image = _PROVIDER_IMAGE[provider]
        self.review_required_fields = ("server.location", "server.server_type")

    def to_display_dict(self) -> dict[str, dict[str, str]]:
        return {
            "provider": {
                "provider": self.provider.provider,
                "hcloud_token": self.provider.hcloud_token.display(),
                "linode_token": self.provider.linode_token.display(),
            },
            "server": {
                "location": self.server.location,
                "server_type": self.server.server_type,
                "image": self.server.image,
                "hostname": self.server.hostname,
                "admin_username": self.server.admin_username,
                "admin_group": self.server.admin_group,
                "ssh_private_key_path": self.server.ssh_private_key_path,
                "ssh_port": self.server.ssh_port,
            },
            "hermes": {
                "provider": self.hermes.provider,
                "model": self.hermes.model,
                "agent_version": self.hermes.agent_version,
                "agent_release_tag": self.hermes.agent_release_tag,
                "api_key": self.hermes.api_key.display(),
            },
            "gateway": {
                "telegram_bot_token": self.gateway.telegram_bot_token.display(),
                "telegram_allowlist_ids": self.gateway.telegram_allowlist_ids,
                "telegram_poll_timeout": self.gateway.telegram_poll_timeout,
            },
        }


@dataclass(frozen=True)
class EnvChange:
    key: str
    old: str
    new: str
    secret: bool = False

    def redacted_line(self) -> str:
        if not self.secret:
            return f"{self.key}: {self.old} -> {self.new}"
        return f"{self.key}: {_secret_state(self.old)} -> {_secret_state(self.new, replacing=True)}"


@dataclass(frozen=True)
class EnvPatch:
    changes: tuple[EnvChange, ...]

    @property
    def values(self) -> dict[str, str]:
        return {change.key: change.new for change in self.changes}

    def redacted_diff(self) -> str:
        if not self.changes:
            return "No changes."
        return "\n".join(change.redacted_line() for change in self.changes)


@dataclass(frozen=True)
class ConfigValidationIssue:
    field: str
    message: str


def _secret_state(value: str, *, replacing: bool = False) -> str:
    if replacing and value:
        return "<replaced>"
    if value:
        return "<set>"
    return "<unset>"


def _env(path: Path, key: str) -> str:
    return logic.get_env_value(path, key)


def _present(value: str) -> bool:
    return bool(value) and value != "***"


@final
class ProjectConfigEnvService:
    """Maps between app-owned config drafts and the repository .env file."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)
        self.env_path = self.repo_root / ".env"

    def load(self) -> ProjectConfigDraft:
        values = self._read_known_values()
        raw_provider = values.get("TF_VAR_cloud_provider") or "hetzner"
        provider: CloudProvider = "linode" if raw_provider == "linode" else "hetzner"
        return ProjectConfigDraft(
            provider=ProviderConfigDraft(
                provider=provider,
                hcloud_token=SecretDraft.keep_existing(_present(values.get("HCLOUD_TOKEN", ""))),
                linode_token=SecretDraft.keep_existing(_present(values.get("LINODE_TOKEN", ""))),
            ),
            server=ServerConfigDraft(
                location=values.get("TF_VAR_server_location", ""),
                server_type=values.get("TF_VAR_server_type", ""),
                image=values.get("TF_VAR_server_image", ""),
                hostname=values.get("TF_VAR_hostname", ""),
                admin_username=values.get("TF_VAR_admin_username", ""),
                admin_group=values.get("TF_VAR_admin_group", ""),
                ssh_private_key_path=values.get("BOOTSTRAP_SSH_PRIVATE_KEY_PATH", ""),
                ssh_port=values.get("BOOTSTRAP_SSH_PORT", "22"),
            ),
            hermes=HermesConfigDraft(
                provider=values.get("TF_VAR_hermes_provider", ""),
                model=values.get("TF_VAR_hermes_model", ""),
                agent_version=values.get("HERMES_AGENT_VERSION", ""),
                agent_release_tag=values.get("HERMES_AGENT_RELEASE_TAG", ""),
                api_key=SecretDraft.keep_existing(_present(values.get("HERMES_API_KEY", ""))),
            ),
            gateway=GatewayConfigDraft(
                telegram_bot_token=SecretDraft.keep_existing(
                    _present(values.get("TELEGRAM_BOT_TOKEN", ""))
                ),
                telegram_allowlist_ids=values.get("TELEGRAM_ALLOWLIST_IDS", ""),
                telegram_poll_timeout=values.get("TELEGRAM_POLL_TIMEOUT", "30"),
            ),
            original_env=values,
        )

    def create_patch(self, draft: ProjectConfigDraft) -> EnvPatch:
        original = draft.original_env or self._read_known_values()
        desired = self._desired_env(draft)
        changes: list[EnvChange] = []
        for key, new in desired.items():
            old = original.get(key, "")
            if old != new:
                changes.append(EnvChange(key=key, old=old, new=new, secret=key in SECRET_KEYS))
        return EnvPatch(tuple(changes))

    def validate(self, draft: ProjectConfigDraft) -> list[ConfigValidationIssue]:
        issues: list[ConfigValidationIssue] = []
        if draft.provider.provider not in ("hetzner", "linode"):
            issues.append(ConfigValidationIssue("provider.provider", "provider must be hetzner or linode"))
        if not draft.server.location:
            issues.append(ConfigValidationIssue("server.location", "region/location requires review"))
        if not draft.server.server_type:
            issues.append(ConfigValidationIssue("server.server_type", "server type requires review"))
        expected_image = _PROVIDER_IMAGE.get(draft.provider.provider)
        if expected_image is not None and draft.server.image != expected_image:
            issues.append(ConfigValidationIssue("server.image", f"server image should be {expected_image}"))
        return issues

    def write_patch(self, patch: EnvPatch) -> None:
        store = EnvStore(self.repo_root)
        store.ensure()
        for key, value in patch.values.items():
            store.set(key, value)
        store.flush()

    def _read_known_values(self) -> dict[str, str]:
        keys = (
            "TF_VAR_cloud_provider",
            "HCLOUD_TOKEN",
            "LINODE_TOKEN",
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
            "HERMES_AGENT_RELEASE_TAG",
            "HERMES_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWLIST_IDS",
            "TELEGRAM_POLL_TIMEOUT",
        )
        return {key: _env(self.env_path, key) for key in keys}

    def _desired_env(self, draft: ProjectConfigDraft) -> dict[str, str]:
        desired = {
            "TF_VAR_cloud_provider": draft.provider.provider,
            "TF_VAR_server_location": draft.server.location,
            "TF_VAR_server_type": draft.server.server_type,
            "TF_VAR_server_image": draft.server.image,
            "TF_VAR_hostname": draft.server.hostname,
            "TF_VAR_admin_username": draft.server.admin_username,
            "TF_VAR_admin_group": draft.server.admin_group,
            "BOOTSTRAP_SSH_PRIVATE_KEY_PATH": draft.server.ssh_private_key_path,
            "BOOTSTRAP_SSH_PORT": draft.server.ssh_port,
            "TF_VAR_hermes_provider": draft.hermes.provider,
            "TF_VAR_hermes_model": draft.hermes.model,
            "HERMES_AGENT_VERSION": draft.hermes.agent_version,
            "HERMES_AGENT_RELEASE_TAG": draft.hermes.agent_release_tag,
            "TELEGRAM_ALLOWLIST_IDS": draft.gateway.telegram_allowlist_ids,
            "TELEGRAM_POLL_TIMEOUT": draft.gateway.telegram_poll_timeout,
        }
        self._add_secret_if_replaced(desired, "HCLOUD_TOKEN", draft.provider.hcloud_token)
        self._add_secret_if_replaced(desired, "LINODE_TOKEN", draft.provider.linode_token)
        self._add_secret_if_replaced(desired, "HERMES_API_KEY", draft.hermes.api_key)
        self._add_secret_if_replaced(desired, "TELEGRAM_BOT_TOKEN", draft.gateway.telegram_bot_token)
        return desired

    @staticmethod
    def _add_secret_if_replaced(desired: dict[str, str], key: str, secret: SecretDraft) -> None:
        if secret.replacement is not None:
            desired[key] = secret.replacement
