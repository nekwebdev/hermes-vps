from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from hermes_vps_app.config_model import (
    ProjectConfigEnvService,
    SecretDraft,
)


def _write_repo(tmp_path: Path, env_text: str) -> Path:
    _ = (tmp_path / ".env.example").write_text(env_text)
    _ = (tmp_path / ".env").write_text(env_text)
    return tmp_path


def test_load_env_returns_typed_config_and_redacted_display_without_secret_values(tmp_path: Path) -> None:
    service = ProjectConfigEnvService(_write_repo(tmp_path, """
TF_VAR_cloud_provider=hetzner
HCLOUD_TOKEN=hcloud-secret-value
LINODE_TOKEN=linode-secret-value
TF_VAR_server_location=nbg1
TF_VAR_server_type=cx22
TF_VAR_server_image=debian-13
TF_VAR_hostname=hermes-prod-01
TF_VAR_admin_username=opsadmin
TF_VAR_admin_group=sshadmins
BOOTSTRAP_SSH_PRIVATE_KEY_PATH=/home/me/.ssh/id_ed25519
BOOTSTRAP_SSH_PORT=22
TF_VAR_hermes_provider=openai-codex
TF_VAR_hermes_model=gpt-5.4-mini
HERMES_AGENT_VERSION=0.10.0
HERMES_AGENT_RELEASE_TAG=v0.10.0
HERMES_API_KEY=hermes-secret-value
TELEGRAM_BOT_TOKEN=telegram-secret-value
TELEGRAM_ALLOWLIST_IDS=12345,-100
TELEGRAM_POLL_TIMEOUT=30
""".lstrip()))

    config = service.load()

    assert config.provider.provider == "hetzner"
    assert config.server.location == "nbg1"
    assert config.hermes.provider == "openai-codex"
    display = config.to_display_dict()
    rendered = repr(display)
    assert "hcloud-secret-value" not in rendered
    assert "linode-secret-value" not in rendered
    assert "hermes-secret-value" not in rendered
    assert "telegram-secret-value" not in rendered
    assert display["provider"]["hcloud_token"] == "<set: keep existing>"
    assert display["gateway"]["telegram_bot_token"] == "<set: keep existing>"


def test_env_patch_keeps_existing_secrets_unless_replaced_and_diff_redacts(tmp_path: Path) -> None:
    service = ProjectConfigEnvService(_write_repo(tmp_path, """
TF_VAR_cloud_provider=hetzner
HCLOUD_TOKEN=old-hcloud-secret
LINODE_TOKEN=old-linode-secret
TF_VAR_server_location=nbg1
TF_VAR_server_type=cx22
TF_VAR_server_image=debian-13
TF_VAR_hostname=old-host
TF_VAR_admin_username=opsadmin
TF_VAR_admin_group=sshadmins
BOOTSTRAP_SSH_PRIVATE_KEY_PATH=/home/me/.ssh/id_ed25519
BOOTSTRAP_SSH_PORT=22
TF_VAR_hermes_provider=openai-codex
TF_VAR_hermes_model=gpt-5.4-mini
HERMES_AGENT_VERSION=0.10.0
HERMES_AGENT_RELEASE_TAG=v0.10.0
HERMES_API_KEY=old-hermes-secret
TELEGRAM_BOT_TOKEN=old-telegram-secret
TELEGRAM_ALLOWLIST_IDS=12345
TELEGRAM_POLL_TIMEOUT=30
""".lstrip()))
    draft = service.load()
    draft.server.hostname = "new-host"
    draft.hermes.api_key = SecretDraft.replace("new-hermes-secret")

    patch = service.create_patch(draft)

    assert patch.values == {
        "TF_VAR_hostname": "new-host",
        "HERMES_API_KEY": "new-hermes-secret",
    }
    diff = patch.redacted_diff()
    assert "TF_VAR_hostname: old-host -> new-host" in diff
    assert "HERMES_API_KEY: <set> -> <replaced>" in diff
    assert "old-hermes-secret" not in diff
    assert "new-hermes-secret" not in diff
    assert "old-hcloud-secret" not in diff


def test_provider_change_resets_dependent_region_type_and_requires_review(tmp_path: Path) -> None:
    service = ProjectConfigEnvService(_write_repo(tmp_path, """
TF_VAR_cloud_provider=hetzner
HCLOUD_TOKEN=old-hcloud-secret
LINODE_TOKEN=old-linode-secret
TF_VAR_server_location=nbg1
TF_VAR_server_type=cx22
TF_VAR_server_image=debian-13
TF_VAR_hostname=hermes-prod-01
TF_VAR_admin_username=opsadmin
TF_VAR_admin_group=sshadmins
BOOTSTRAP_SSH_PRIVATE_KEY_PATH=/home/me/.ssh/id_ed25519
BOOTSTRAP_SSH_PORT=22
TF_VAR_hermes_provider=openai-codex
TF_VAR_hermes_model=gpt-5.4-mini
HERMES_AGENT_VERSION=0.10.0
HERMES_AGENT_RELEASE_TAG=v0.10.0
HERMES_API_KEY=old-hermes-secret
TELEGRAM_BOT_TOKEN=old-telegram-secret
TELEGRAM_ALLOWLIST_IDS=12345
TELEGRAM_POLL_TIMEOUT=30
""".lstrip()))
    draft = service.load()

    draft.change_provider("linode")

    assert draft.provider.provider == "linode"
    assert draft.server.location == ""
    assert draft.server.server_type == ""
    assert draft.server.image == "linode/debian13"
    assert draft.review_required_fields == ("server.location", "server.server_type")
    issues = service.validate(draft)
    assert [issue.field for issue in issues] == ["server.location", "server.server_type"]
    patch = service.create_patch(draft)
    assert patch.values["TF_VAR_cloud_provider"] == "linode"
    assert patch.values["TF_VAR_server_location"] == ""
    assert patch.values["TF_VAR_server_type"] == ""


def test_write_patch_uses_existing_atomic_env_store_behavior(tmp_path: Path) -> None:
    service = ProjectConfigEnvService(_write_repo(tmp_path, """
TF_VAR_cloud_provider=hetzner
HCLOUD_TOKEN=old-hcloud-secret
TF_VAR_server_location=nbg1
TF_VAR_server_type=cx22
TF_VAR_server_image=debian-13
TF_VAR_hostname=old-host
HERMES_API_KEY=old-hermes-secret
TELEGRAM_BOT_TOKEN=old-telegram-secret
""".lstrip()))
    draft = service.load()
    draft.server.hostname = "atomic-host"
    patch_obj = service.create_patch(draft)
    captured: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src: str, dst: str) -> None:
        captured.append((str(src), str(dst)))
        real_replace(src, dst)

    with patch("scripts.configure_services.os.replace", spy_replace):
        service.write_patch(patch_obj)

    assert len(captured) == 1
    assert captured[0][1] == str(tmp_path / ".env")
    assert captured[0][0] != captured[0][1]
    assert "TF_VAR_hostname=atomic-host" in (tmp_path / ".env").read_text()
