from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from scripts import configure_logic as logic


@dataclass(frozen=True)
class LabeledValue:
    label: str
    value: str
    recommended: bool = False


@dataclass
class WizardState:
    provider: str = ""
    provider_token_key: str = ""
    provider_token_replace: bool = False
    provider_token_input: str = ""

    server_image: str = ""
    location: str = ""
    server_type: str = ""

    hostname: str = ""
    admin_username: str = ""
    admin_group: str = ""
    ssh_private_key_path: str = ""

    hermes_agent_version: str = ""
    hermes_agent_release_tag: str = ""
    hermes_provider: str = ""
    hermes_model: str = ""
    hermes_auth_type: str = "api_key"
    hermes_auth_method: str = "api_key"
    hermes_api_key_replace: bool = False
    hermes_api_key_input: str = ""

    telegram_bot_token_replace: bool = False
    telegram_bot_token_input: str = ""
    telegram_allowlist_ids: str = ""

    add_ssh_alias: bool = True

    recap_auth_artifact: str = "none"

    original_values: dict[str, str] = field(default_factory=dict)

    def provider_token_env_key(self) -> str:
        return "HCLOUD_TOKEN" if self.provider == "hetzner" else "LINODE_TOKEN"

    def validate_cloud(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        if self.provider not in {"hetzner", "linode"}:
            errors["provider"] = "Choose cloud provider."
        if self.provider_token_replace and not self.provider_token_input:
            errors["provider_token"] = "Token cannot be empty."
        return errors

    def validate_server(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        if not self.location:
            errors["location"] = "Choose region."
        if not self.server_type:
            errors["server_type"] = "Choose server type."
        if not self.hostname:
            errors["hostname"] = "Hostname required."
        if not self.admin_username:
            errors["admin_username"] = "Admin username required."
        if not self.admin_group:
            errors["admin_group"] = "SSH group required."
        return errors

    def validate_hermes(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        if not logic.is_valid_semver(self.hermes_agent_version):
            errors["hermes_agent_version"] = "Use pinned semantic version (example: 0.10.0)."
        else:
            self.hermes_agent_release_tag = logic.release_tag_for_version(self.hermes_agent_version)
        if not logic.is_valid_release_tag(self.hermes_agent_release_tag):
            errors["hermes_agent_release_tag"] = "Use release tag format vYYYY.M.D (or semver tag)."
        if not self.hermes_provider:
            errors["hermes_provider"] = "Choose Hermes provider."
        if not self.hermes_model:
            errors["hermes_model"] = "Choose Hermes model."
        if self.hermes_auth_method not in {"api_key", "oauth"}:
            errors["hermes_auth_method"] = "Choose authentication method."
        return errors

    def validate_telegram(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        if self.telegram_bot_token_replace and not self.telegram_bot_token_input:
            errors["telegram_bot_token"] = "Telegram bot token cannot be empty."
        if not self.telegram_allowlist_ids:
            errors["telegram_allowlist_ids"] = "Allowlist required."
        elif not logic.is_valid_telegram_allowlist(self.telegram_allowlist_ids):
            errors["telegram_allowlist_ids"] = "Use comma-separated integers: 12345,-100987654321"
        return errors

    def recap_rows(self) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []

        def add(key: str, new: str) -> None:
            old = self.original_values.get(key, "")
            if old != new:
                rows.append((key, old, new))

        add("TF_VAR_cloud_provider", self.provider)
        add("TF_VAR_server_image", self.server_image)
        add("TF_VAR_server_location", self.location)
        add("TF_VAR_server_type", self.server_type)
        add("TF_VAR_hostname", self.hostname)
        add("TF_VAR_admin_username", self.admin_username)
        add("TF_VAR_admin_group", self.admin_group)
        add("BOOTSTRAP_SSH_PRIVATE_KEY_PATH", self.ssh_private_key_path)
        add("HERMES_AGENT_VERSION", self.hermes_agent_version)
        add("HERMES_AGENT_RELEASE_TAG", self.hermes_agent_release_tag)
        add("TF_VAR_hermes_provider", self.hermes_provider)
        add("TF_VAR_hermes_model", self.hermes_model)
        add("TELEGRAM_ALLOWLIST_IDS", self.telegram_allowlist_ids)

        ssh_alias_new = "active" if self.add_ssh_alias else "inactive"
        ssh_alias_old = self.original_values.get("SSH_ALIAS", "")
        if ssh_alias_old != ssh_alias_new:
            rows.append(("SSH_ALIAS", ssh_alias_old, ssh_alias_new))
        return rows


def choose_seed(options: Iterable[str], existing: str = "", preferred: str = "") -> str:
    return logic.choose_seed(options=options, existing=existing, preferred=preferred)


def rotate_to_seed(options: Iterable[str], seed: str) -> list[str]:
    return logic.rotate_to_seed(options=options, seed=seed)
