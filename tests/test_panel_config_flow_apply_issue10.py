from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hermes_vps_app.config_model import SecretDraft
from hermes_vps_app.hermes_oauth import HermesOAuthRunResult
from hermes_vps_app.panel_config_flow import AsyncValidationResult, PanelConfigFlow


def _template() -> str:
    return """# keep me
TF_VAR_cloud_provider=
HCLOUD_TOKEN=
TF_VAR_server_location=
TF_VAR_server_type=
TF_VAR_server_image=
TF_VAR_hostname=
TF_VAR_admin_username=
TF_VAR_admin_group=
BOOTSTRAP_SSH_PRIVATE_KEY_PATH=
BOOTSTRAP_SSH_PORT=22
TF_VAR_admin_ssh_public_key=
TF_VAR_hermes_provider=
TF_VAR_hermes_model=
HERMES_AGENT_VERSION=
HERMES_AGENT_RELEASE_TAG=
HERMES_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWLIST_IDS=
TELEGRAM_POLL_TIMEOUT=30
"""


def _make_applyable_flow(tmp_path: Path, *, key_path: Path, oauth: bool = False, alias: bool = True) -> PanelConfigFlow:
    (tmp_path / ".env.example").write_text(_template(), encoding="utf-8")
    flow = PanelConfigFlow.first_run(tmp_path)
    flow.draft.provider.hcloud_token = SecretDraft.replace("hcloud-secret")
    flow.set_cloud(provider="hetzner", lookup_mode="sample")
    flow.draft.server.location = "nbg1"
    flow.draft.server.server_type = "cx22"
    flow.draft.server.image = "debian-13"
    flow.set_host_ssh(
        hostname="hermes.example.test",
        admin_username="opsadmin",
        admin_group="sshadmins",
        ssh_private_key_path=str(key_path),
        add_ssh_alias=alias,
    )
    if oauth:
        flow.set_hermes_oauth(
            provider="openai-codex",
            model="gpt-5.4-mini",
            agent_version="0.10.0",
            agent_release_tag="v2026.4.16",
        )
        result = HermesOAuthRunResult(
            status="succeeded",
            provider="openai-codex",
            agent_version="0.10.0",
            agent_release_tag="v2026.4.16",
            auth_method="oauth",
            auth_json_bytes=json.dumps({"token": "oauth-secret"}).encode(),
            auth_json_sha256="1" * 64,
            instructions=(),
            output_tail="",
            exit_code=0,
            error_message=None,
        )
        flow.record_hermes_oauth_result(result)
    else:
        flow.set_hermes_api_key(
            provider="openai-codex",
            model="gpt-5.4-mini",
            api_key="hermes-secret",
            agent_version="0.10.0",
            agent_release_tag="v2026.4.16",
        )
    req = flow.begin_telegram_validation(token="telegram-secret", allowlist_ids="12345")
    flow.complete_telegram_validation(
        AsyncValidationResult.success(request_id=req.request_id, fingerprint=req.fingerprint, detail="Telegram gateway is valid: @bot.")
    )
    return flow


def test_api_key_apply_writes_env_preserves_template_and_ensures_host_ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path.parent / f"{tmp_path.name}-home"
    monkeypatch.setenv("HOME", str(home))
    key_path = home / ".ssh" / "hermes-vps"
    flow = _make_applyable_flow(tmp_path, key_path=key_path, oauth=False, alias=True)

    result = flow.apply_review(flow.review())

    env_path = tmp_path / ".env"
    written = env_path.read_text(encoding="utf-8")
    assert result.ok is True
    assert result.message == "Configuration applied."
    assert "# keep me" in written
    assert "TF_VAR_admin_ssh_public_key=ssh-ed25519" in written
    assert f"BOOTSTRAP_SSH_PRIVATE_KEY_PATH={key_path}" in written
    assert oct(env_path.stat().st_mode & 0o777) == "0o600"
    assert key_path.exists()
    assert Path(str(key_path) + ".pub").exists()
    assert oct(key_path.stat().st_mode & 0o777) == "0o600"
    assert oct(Path(str(key_path) + ".pub").stat().st_mode & 0o777) == "0o644"
    assert (tmp_path / ".ssh" / "config").read_text(encoding="utf-8").count("Host hermes-vps") == 1
    assert (home / ".ssh" / "config").read_text(encoding="utf-8").count(f"Include {tmp_path / '.ssh' / 'config'}") == 1
    assert not (tmp_path / ".hermes-home" / "auth.json").exists()


def test_oauth_apply_writes_auth_json_mode_0600_and_clears_raw_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path.parent / f"{tmp_path.name}-home"
    monkeypatch.setenv("HOME", str(home))
    flow = _make_applyable_flow(tmp_path, key_path=home / ".ssh" / "hermes-vps", oauth=True)

    result = flow.apply_review(flow.review())

    auth_path = tmp_path / ".hermes-home" / "auth.json"
    assert result.ok is True
    assert auth_path.read_text(encoding="utf-8") == '{"token": "oauth-secret"}'
    assert oct(auth_path.stat().st_mode & 0o777) == "0o600"
    assert not (tmp_path / ".hermes-home" / ".auth.json.tmp").exists()
    assert flow.hermes_oauth_artifact_for_review() is None


def test_ssh_alias_idempotent_and_removal_preserves_unrelated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path.parent / f"{tmp_path.name}-home"
    monkeypatch.setenv("HOME", str(home))
    key_path = home / ".ssh" / "hermes-vps"
    flow = _make_applyable_flow(tmp_path, key_path=key_path, oauth=False, alias=True)
    flow.apply_review(flow.review())
    flow.apply_review(flow.review())

    home_config = home / ".ssh" / "config"
    repo_config = tmp_path / ".ssh" / "config"
    assert home_config.read_text(encoding="utf-8").count(f"Include {repo_config}") == 1
    assert repo_config.read_text(encoding="utf-8").count("Host hermes-vps") == 1
    home_config.write_text("Host github.com\n  User git\n" + home_config.read_text(encoding="utf-8"), encoding="utf-8")

    remove_flow = _make_applyable_flow(tmp_path, key_path=key_path, oauth=False, alias=False)
    remove_flow.apply_review(remove_flow.review())

    assert "Host github.com" in home_config.read_text(encoding="utf-8")
    assert f"Include {repo_config}" not in home_config.read_text(encoding="utf-8")
    assert "Host hermes-vps" not in repo_config.read_text(encoding="utf-8")


def test_env_write_failure_deletes_oauth_temp_and_keeps_config_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path.parent / f"{tmp_path.name}-home"
    monkeypatch.setenv("HOME", str(home))
    flow = _make_applyable_flow(tmp_path, key_path=home / ".ssh" / "hermes-vps", oauth=True)

    def fail_write(_patch: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(flow.env_service, "write_patch", fail_write)
    result = flow.apply_review(flow.review())

    assert result.ok is False
    assert result.message == "Configuration apply failed. No OAuth artifact was written."
    assert not (tmp_path / ".hermes-home" / ".auth.json.tmp").exists()
    assert flow.hermes_oauth_artifact_for_review() is not None


def test_ssh_alias_failure_after_env_keeps_oauth_artifact_for_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path.parent / f"{tmp_path.name}-home"
    monkeypatch.setenv("HOME", str(home))
    flow = _make_applyable_flow(tmp_path, key_path=home / ".ssh" / "hermes-vps", oauth=True)
    monkeypatch.setattr(flow, "_reconcile_ssh_alias", lambda: (_ for _ in ()).throw(OSError("alias boom")))

    result = flow.apply_review(flow.review())

    assert result.ok is False
    assert result.message == "Configuration apply incomplete: .env was written but SSH alias was not reconciled. Retry Apply."
    assert (tmp_path / ".env").exists()
    assert not (tmp_path / ".hermes-home" / "auth.json").exists()
    assert flow.hermes_oauth_artifact_for_review() is not None


def test_oauth_rename_failure_keeps_oauth_artifact_for_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path.parent / f"{tmp_path.name}-home"
    monkeypatch.setenv("HOME", str(home))
    flow = _make_applyable_flow(tmp_path, key_path=home / ".ssh" / "hermes-vps", oauth=True)
    real_replace = os.replace

    def fail_auth_replace(src: str | bytes | os.PathLike[str] | os.PathLike[bytes], dst: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> None:
        if str(dst).endswith(".hermes-home/auth.json"):
            raise OSError("rename boom")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_auth_replace)
    result = flow.apply_review(flow.review())

    assert result.ok is False
    assert result.message == "Configuration apply incomplete: .env was written but Hermes OAuth artifact was not finalized. Retry Apply."
    assert (tmp_path / ".env").exists()
    assert flow.hermes_oauth_artifact_for_review() is not None
