from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from hermes_vps_app.config_model import SecretDraft
from hermes_vps_app.panel_config_flow import (
    AsyncValidationResult,
    PanelConfigFlow,
    ProviderLookupFailure,
)
from hermes_vps_app.panel_shell import ControlPanelShell
from hermes_vps_app.panel_startup import PanelStartupResult, PanelStartupState, StartupStep


def _startup_result(state: PanelStartupState) -> PanelStartupResult:
    return PanelStartupResult(
        state=state,
        steps=(
            StartupStep(
                name="runner_detection",
                label="Detect runner and lock mode",
                status="ok",
                detail="runner locked: docker",
            ),
        ),
        runner_mode="docker",
        remediation="configure .env" if state is PanelStartupState.CONFIGURATION_REQUIRED else "ready",
        provider="hetzner" if state is PanelStartupState.DASHBOARD_READY else None,
    )


def _env_text() -> str:
    return """
TF_VAR_cloud_provider=hetzner
HCLOUD_TOKEN=***
LINODE_TOKEN=***
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
HERMES_API_KEY=***
TELEGRAM_BOT_TOKEN=old-telegram-token
TELEGRAM_ALLOWLIST_IDS=12345
TELEGRAM_POLL_TIMEOUT=30
""".lstrip()


def test_missing_env_configuration_screen_is_shell_native_first_run(tmp_path: Path) -> None:
    shell = ControlPanelShell(
        startup_result=_startup_result(PanelStartupState.CONFIGURATION_REQUIRED),
        initial_panel="configuration",
    )

    screen = shell.configuration_panel(repo_root=tmp_path)

    assert screen["state"] == "configuration_required"
    assert screen["mode"] == "first_run"
    assert screen["steps"] == ["cloud", "server", "hermes", "telegram", "review_apply"]
    assert screen["current_step"] == "cloud"
    assert "Configuration required" in cast(str, screen["title"])


def test_existing_env_opens_targeted_reconfigure_sections_not_full_wizard(tmp_path: Path) -> None:
    _ = (tmp_path / ".env").write_text(_env_text(), encoding="utf-8")
    shell = ControlPanelShell(
        startup_result=_startup_result(PanelStartupState.DASHBOARD_READY),
        initial_panel="configuration",
    )

    screen = shell.configuration_panel(repo_root=tmp_path)

    assert screen["state"] == "configuration_reconfigure"
    assert screen["mode"] == "reconfigure"
    assert screen["sections"] == ["cloud", "server", "hermes", "telegram"]
    assert "steps" not in screen
    display = cast(dict[str, dict[str, str]], screen["display"])
    assert display["provider"]["hcloud_token"] == "<unset>"


def test_launch_config_returns_panel_native_configuration_payload_not_old_tui(tmp_path: Path) -> None:
    shell = ControlPanelShell()

    payload = shell.launch_config(repo_root=tmp_path)

    assert cast(dict[str, object], payload)["state"] == "configuration_required"
    assert cast(dict[str, object], payload)["mode"] == "first_run"


def test_reconfigure_can_apply_targeted_server_change_without_revalidating_kept_telegram(tmp_path: Path) -> None:
    _ = (tmp_path / ".env").write_text(_env_text(), encoding="utf-8")
    flow = PanelConfigFlow.reconfigure(tmp_path)
    flow.draft.server.hostname = "new-host"

    review = flow.review()

    assert review.can_apply is True
    assert review.blocking_issues == ()
    assert "TELEGRAM_BOT_TOKEN" not in review.redacted_diff
    assert "TF_VAR_hostname: old-host -> new-host" in review.redacted_diff


def test_first_run_covers_all_sections_and_review_redacts_before_atomic_apply(tmp_path: Path) -> None:
    _ = (tmp_path / ".env.example").write_text("", encoding="utf-8")
    flow = PanelConfigFlow.first_run(tmp_path)
    assert flow.mode == "first_run"
    assert flow.steps == ("cloud", "server", "hermes", "telegram", "review_apply")

    flow.draft.provider.hcloud_token = SecretDraft.replace("hcloud-secret")
    flow.set_cloud(provider="hetzner", lookup_mode="sample")
    flow.set_server(
        location="nbg1",
        server_type="cx22",
        hostname="hermes-prod-01",
        admin_username="opsadmin",
        admin_group="sshadmins",
        ssh_private_key_path="/home/me/.ssh/id_ed25519",
    )
    flow.set_hermes_api_key(
        provider="openai-codex",
        model="gpt-5.4-mini",
        api_key="hermes-secret",
        agent_version="0.10.0",
        agent_release_tag="v0.10.0",
    )
    request = flow.begin_telegram_validation(token="telegram-secret", allowlist_ids="12345,-100")
    _ = flow.complete_telegram_validation(
        AsyncValidationResult.success(request_id=request.request_id, fingerprint=request.fingerprint, detail="@bot ok")
    )

    review = flow.review()

    assert review.can_apply is True
    assert "HCLOUD_TOKEN: <unset> -> <replaced>" in review.redacted_diff
    assert "HERMES_API_KEY: <unset> -> <replaced>" in review.redacted_diff
    assert "TELEGRAM_BOT_TOKEN: <unset> -> <replaced>" in review.redacted_diff
    assert "hcloud-secret" not in review.redacted_diff
    assert "hermes-secret" not in review.redacted_diff
    assert "telegram-secret" not in review.redacted_diff

    flow.apply_review(review)
    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TF_VAR_hostname=hermes-prod-01" in written
    assert "HERMES_API_KEY=hermes-secret" in written


def test_first_run_host_ssh_defaults_seed_missing_env_without_expanding_tilde(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)

    host = flow.host_ssh_defaults()

    assert host.hostname == "hermes-vps"
    assert host.admin_username == "hermes"
    assert host.admin_group == "hermes-admins"
    assert host.ssh_private_key_path == "~/.ssh/hermes-vps"
    assert host.add_ssh_alias is True
    assert host.ssh_alias_name == "hermes-vps"


def test_host_ssh_validation_blocks_repo_relative_key_paths_without_filesystem_checks(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)
    repo_key = tmp_path / "keys" / "hermes-vps"

    for bad_path in ("id_ed25519", "./id_ed25519", "keys/hermes-vps", str(repo_key)):
        result = flow.set_host_ssh(
            hostname="hermes-vps",
            admin_username="hermes",
            admin_group="hermes-admins",
            ssh_private_key_path=bad_path,
            add_ssh_alias=True,
        )
        assert result.ok is False
        assert result.next_step == "server"
        assert "SSH private key path must be outside the repository" in result.message
        assert flow.current_step == "cloud"

    outside_absent = tmp_path.parent / "absent-hermes-vps-key"
    result = flow.set_host_ssh(
        hostname="hermes-vps",
        admin_username="hermes",
        admin_group="hermes-admins",
        ssh_private_key_path=str(outside_absent),
        add_ssh_alias=False,
    )
    assert result.ok is True
    assert flow.draft.server.ssh_private_key_path == str(outside_absent)
    assert flow.draft.server.add_ssh_alias is False
    assert flow.current_step == "hermes"
    assert not outside_absent.exists()


def _complete_first_run_flow(tmp_path: Path) -> PanelConfigFlow:
    flow = PanelConfigFlow.first_run(tmp_path)
    flow.draft.provider.hcloud_token = SecretDraft.replace("hcloud-secret")
    flow.set_cloud(provider="hetzner", lookup_mode="sample")
    flow.set_server(
        location="nbg1",
        server_type="cx22",
        hostname="hermes-prod-01",
        admin_username="opsadmin",
        admin_group="sshadmins",
        ssh_private_key_path="/home/me/.ssh/id_ed25519",
    )
    flow.set_hermes_api_key(
        provider="openai-codex",
        model="gpt-5.4-mini",
        api_key="hermes-secret",
        agent_version="0.10.0",
        agent_release_tag="v0.10.0",
    )
    request = flow.begin_telegram_validation(token="telegram-secret", allowlist_ids="12345,-100")
    _ = flow.complete_telegram_validation(
        AsyncValidationResult.success(request_id=request.request_id, fingerprint=request.fingerprint, detail="@bot ok")
    )
    return flow


def test_apply_review_without_env_example_does_not_create_or_modify_template(tmp_path: Path) -> None:
    from scripts.configure_services import ConfigureServiceError

    flow = _complete_first_run_flow(tmp_path)
    review = flow.review()

    assert review.can_apply is True
    with pytest.raises(ConfigureServiceError, match="missing env template"):
        flow.apply_review(review)

    assert not (tmp_path / ".env.example").exists()
    assert not (tmp_path / ".env").exists()


def test_cloud_sample_and_live_lookup_success_and_provider_remediation(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)

    sample = flow.cloud_options(provider="linode", lookup_mode="sample")
    assert sample.lookup_mode == "sample"
    assert sample.regions
    assert sample.server_types

    live = flow.cloud_options(
        provider="hetzner",
        lookup_mode="live",
        live_lookup=lambda provider, location: ([f"{provider}-region"], [f"{location or 'default'}-type"]),
    )
    assert live.lookup_mode == "live"
    assert live.regions == ("hetzner-region",)
    assert live.server_types == ("default-type",)

    with pytest.raises(ProviderLookupFailure) as exc_info:
        _ = flow.cloud_options(
            provider="linode",
            lookup_mode="live",
            live_lookup=lambda _provider, _location: (_ for _ in ()).throw(RuntimeError("bad token")),
        )
    failure = exc_info.value.failure
    assert failure.provider == "linode"
    assert failure.reason == "metadata_unavailable"
    assert "Linode" in failure.title
    assert "bad token" in failure.detail


def test_hermes_oauth_api_key_distinction_is_preserved(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)

    flow.set_hermes_oauth(provider="anthropic-oauth", model="claude-sonnet", agent_version="0.10.0")
    display = cast(dict[str, dict[str, str]], flow.to_screen()["display"])["hermes"]
    assert display["auth_mode"] == "oauth"
    assert display["api_key"] == "<not used: oauth>"
    assert flow.review().can_apply is False
    assert "HERMES_API_KEY" not in flow.review().redacted_diff

    flow.set_hermes_api_key(provider="openai-codex", model="gpt-5.4-mini", api_key="secret")
    display = cast(dict[str, dict[str, str]], flow.to_screen()["display"])["hermes"]
    assert display["auth_mode"] == "api_key"
    assert display["api_key"] == "<replacement pending>"


def test_telegram_validation_is_explicit_and_stale_or_failed_results_cannot_be_persisted(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)
    flow.set_cloud(provider="hetzner", lookup_mode="sample")
    flow.set_server(location="nbg1", server_type="cx22", hostname="h", admin_username="u", admin_group="g", ssh_private_key_path="/k")
    flow.set_hermes_oauth(provider="anthropic-oauth", model="claude", agent_version="0.10.0")

    first = flow.begin_telegram_validation(token="old-token", allowlist_ids="12345")
    second = flow.begin_telegram_validation(token="new-token", allowlist_ids="67890")

    stale = flow.complete_telegram_validation(
        AsyncValidationResult.success(request_id=first.request_id, fingerprint=first.fingerprint, detail="old ok")
    )
    assert stale.accepted is False
    assert stale.stale is True
    assert flow.review().can_apply is False
    assert "telegram validation is required" in flow.review().blocking_issues

    failed = flow.complete_telegram_validation(
        AsyncValidationResult.failure(request_id=second.request_id, fingerprint=second.fingerprint, detail="getMe failed")
    )
    assert failed.accepted is True
    assert failed.ok is False
    assert flow.review().can_apply is False
    assert "telegram validation failed: getMe failed" in flow.review().blocking_issues

    third = flow.begin_telegram_validation(token="new-token", allowlist_ids="67890")
    accepted = flow.complete_telegram_validation(
        AsyncValidationResult.success(request_id=third.request_id, fingerprint=third.fingerprint, detail="@bot ok")
    )
    assert accepted.accepted is True
    assert accepted.ok is True
    assert flow.review().can_apply is True
