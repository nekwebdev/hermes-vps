from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from hermes_vps_app.config_model import SecretDraft
from hermes_vps_app.hermes_live_metadata import HermesRelease, HermesRuntimeMetadata, ToolchainCacheResult
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




def test_hermes_live_metadata_sync_selects_newest_release_and_runtime_metadata(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)
    cache_calls: list[tuple[str, str, str]] = []

    class ReleaseService:
        def latest_releases(self, *, force_refresh: bool = False) -> tuple[HermesRelease, ...]:
            assert force_refresh is False
            return (
                HermesRelease("0.12.0", "v2026.4.30", "https://example/releases/v2026.4.30"),
                HermesRelease("0.11.0", "v2026.4.23", "https://example/releases/v2026.4.23"),
            )

    class CacheService:
        def prepare(self, semantic_version: str, release_tag: str, *, request_id: str) -> ToolchainCacheResult:
            cache_calls.append((semantic_version, release_tag, request_id))
            cache_dir = tmp_path / ".cache" / "hermes-toolchain" / f"{semantic_version}-{release_tag}"
            return ToolchainCacheResult(
                ready=True,
                cache_dir=cache_dir,
                hermes_cli=cache_dir / "venv" / "bin" / "hermes",
                semantic_version=semantic_version,
                release_tag=release_tag,
                git_commit="abc123",
            )

    class RuntimeService:
        def load(self, *, cache_dir: Path, provider: str) -> HermesRuntimeMetadata:
            assert cache_dir.name == "0.12.0-v2026.4.30"
            assert provider == "openai-codex"
            return HermesRuntimeMetadata(
                providers=("anthropic", "openai-codex"),
                models=("gpt-5.4", "gpt-5.4-mini"),
                auth_methods=("oauth", "api_key"),
            )

    defaults = flow.sync_hermes_live_metadata(
        release_service=ReleaseService(),
        cache_service=CacheService(),
        runtime_metadata_service=RuntimeService(),
        request_id="req1",
    )

    assert defaults.version_options == (("0.12.0", "v2026.4.30"), ("0.11.0", "v2026.4.23"))
    assert defaults.agent_version == "0.12.0"
    assert defaults.agent_release_tag == "v2026.4.30"
    assert defaults.provider_options == ("anthropic", "openai-codex")
    assert defaults.provider == "openai-codex"
    assert defaults.model_options == ("gpt-5.4", "gpt-5.4-mini")
    assert defaults.model == "gpt-5.4-mini"
    assert defaults.auth_methods == ("oauth", "api_key")
    assert cache_calls == [("0.12.0", "v2026.4.30", "req1")]

    result = flow.set_hermes(
        agent_version="0.12.0",
        provider="openai-codex",
        model="gpt-5.4-mini",
        auth_method="oauth",
        api_key="",
    )

    assert result.ok is True
    assert flow.draft.hermes.agent_release_tag == "v2026.4.30"


def test_hermes_live_metadata_sync_keeps_configured_env_version_when_present(tmp_path: Path) -> None:
    _ = (tmp_path / ".env").write_text(_env_text().replace("HERMES_AGENT_VERSION=0.10.0", "HERMES_AGENT_VERSION=0.11.0"), encoding="utf-8")
    flow = PanelConfigFlow.reconfigure(tmp_path)
    cache_calls: list[tuple[str, str, str]] = []

    class ReleaseService:
        def latest_releases(self, *, force_refresh: bool = False) -> tuple[HermesRelease, ...]:
            return (
                HermesRelease("0.12.0", "v2026.4.30", "https://example/releases/v2026.4.30"),
                HermesRelease("0.11.0", "v2026.4.23", "https://example/releases/v2026.4.23"),
            )

    class CacheService:
        def prepare(self, semantic_version: str, release_tag: str, *, request_id: str) -> ToolchainCacheResult:
            cache_calls.append((semantic_version, release_tag, request_id))
            cache_dir = tmp_path / ".cache" / "hermes-toolchain" / f"{semantic_version}-{release_tag}"
            return ToolchainCacheResult(True, cache_dir, cache_dir / "venv" / "bin" / "hermes", semantic_version, release_tag, "abc123")

    class RuntimeService:
        def load(self, *, cache_dir: Path, provider: str) -> HermesRuntimeMetadata:
            assert cache_dir.name == "0.11.0-v2026.4.23"
            return HermesRuntimeMetadata(("openai-codex",), ("gpt-5.4-mini",), ("oauth", "api_key"))

    defaults = flow.sync_hermes_live_metadata(
        release_service=ReleaseService(),
        cache_service=CacheService(),
        runtime_metadata_service=RuntimeService(),
        request_id="req-env-version",
    )

    assert defaults.agent_version == "0.11.0"
    assert defaults.agent_release_tag == "v2026.4.23"
    assert cache_calls == [("0.11.0", "v2026.4.23", "req-env-version")]


def test_hermes_live_metadata_sync_uses_selected_provider_for_model_metadata(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)
    flow.draft.hermes.provider = "xiaomi"
    requested_providers: list[str] = []

    class ReleaseService:
        def latest_releases(self, *, force_refresh: bool = False) -> tuple[HermesRelease, ...]:
            return (HermesRelease("0.12.0", "v2026.4.30", "https://example/releases/v2026.4.30"),)

    class CacheService:
        def prepare(self, semantic_version: str, release_tag: str, *, request_id: str) -> ToolchainCacheResult:
            cache_dir = tmp_path / ".cache" / "hermes-toolchain" / f"{semantic_version}-{release_tag}"
            return ToolchainCacheResult(True, cache_dir, cache_dir / "venv" / "bin" / "hermes", semantic_version, release_tag, "abc123")

    class RuntimeService:
        def load(self, *, cache_dir: Path, provider: str) -> HermesRuntimeMetadata:
            requested_providers.append(provider)
            return HermesRuntimeMetadata(
                providers=("openai-codex", "xiaomi"),
                models=("mimo-v2-pro", "mimo-v2-flash"),
                auth_methods=("api_key",),
            )

    defaults = flow.sync_hermes_live_metadata(
        release_service=ReleaseService(),
        cache_service=CacheService(),
        runtime_metadata_service=RuntimeService(),
        request_id="req-xiaomi",
    )

    assert requested_providers == ["xiaomi"]
    assert defaults.provider == "xiaomi"
    assert defaults.model_options == ("mimo-v2-pro", "mimo-v2-flash")
    assert defaults.model == "mimo-v2-pro"


def test_hermes_live_metadata_sync_blocks_existing_version_outside_live_list(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)
    flow.draft.hermes.agent_version = "0.1.0"

    class ReleaseService:
        def latest_releases(self, *, force_refresh: bool = False) -> tuple[HermesRelease, ...]:
            return (HermesRelease("0.12.0", "v2026.4.30", "https://example"),)

    try:
        flow.sync_hermes_live_metadata(
            release_service=ReleaseService(),
            cache_service=object(),
            runtime_metadata_service=object(),
            request_id="req1",
        )
    except RuntimeError as exc:
        assert "outside the current live Hermes Agent release list" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_hermes_live_metadata_sync_blocks_empty_runtime_provider_metadata(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)

    class ReleaseService:
        def latest_releases(self, *, force_refresh: bool = False) -> tuple[HermesRelease, ...]:
            return (HermesRelease("0.12.0", "v2026.4.30", "https://example"),)

    class CacheService:
        def prepare(self, semantic_version: str, release_tag: str, *, request_id: str) -> ToolchainCacheResult:
            cache_dir = tmp_path / ".cache" / "hermes-toolchain" / f"{semantic_version}-{release_tag}"
            return ToolchainCacheResult(
                ready=True,
                cache_dir=cache_dir,
                hermes_cli=cache_dir / "venv" / "bin" / "hermes",
                semantic_version=semantic_version,
                release_tag=release_tag,
                git_commit="abc123",
            )

    class RuntimeService:
        def load(self, *, cache_dir: Path, provider: str) -> HermesRuntimeMetadata:
            return HermesRuntimeMetadata(providers=(), models=(), auth_methods=())

    try:
        flow.sync_hermes_live_metadata(
            release_service=ReleaseService(),
            cache_service=CacheService(),
            runtime_metadata_service=RuntimeService(),
            request_id="req-empty-provider-metadata",
        )
    except RuntimeError as exc:
        assert "no provider metadata" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_hermes_live_metadata_sync_allows_provider_without_models(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)
    flow.draft.hermes.provider = "lmstudio"

    class ReleaseService:
        def latest_releases(self, *, force_refresh: bool = False) -> tuple[HermesRelease, ...]:
            return (HermesRelease("0.12.0", "v2026.4.30", "https://example"),)

    class CacheService:
        def prepare(self, semantic_version: str, release_tag: str, *, request_id: str) -> ToolchainCacheResult:
            cache_dir = tmp_path / ".cache" / "hermes-toolchain" / f"{semantic_version}-{release_tag}"
            return ToolchainCacheResult(True, cache_dir, cache_dir / "venv" / "bin" / "hermes", semantic_version, release_tag, "abc123")

    class RuntimeService:
        def load(self, *, cache_dir: Path, provider: str) -> HermesRuntimeMetadata:
            assert provider == "lmstudio"
            return HermesRuntimeMetadata(providers=("lmstudio",), models=(), auth_methods=("api_key",))

    defaults = flow.sync_hermes_live_metadata(
        release_service=ReleaseService(),
        cache_service=CacheService(),
        runtime_metadata_service=RuntimeService(),
        request_id="req-empty-models",
    )

    assert defaults.provider == "lmstudio"
    assert defaults.model_options == ()
    assert defaults.model == ""

    result = flow.set_hermes(
        agent_version="0.12.0",
        provider="lmstudio",
        model="",
        auth_method="api_key",
        api_key="local-key",
    )

    assert result.ok is True
    assert flow.draft.hermes.model == ""


def test_first_run_hermes_defaults_use_placeholder_version_provider_model_and_oauth(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)

    defaults = flow.hermes_defaults()

    assert defaults.version_options == (("0.10.0", "v2026.4.16"),)
    assert defaults.agent_version == "0.10.0"
    assert defaults.agent_release_tag == "v2026.4.16"
    assert defaults.provider_options == ("openai-codex", "anthropic")
    assert defaults.provider == "openai-codex"
    assert defaults.model_options == ("gpt-5.4-mini", "gpt-5.4")
    assert defaults.model == "gpt-5.4-mini"
    assert defaults.auth_methods == ("oauth", "api_key")
    assert defaults.auth_method == "oauth"


def test_hermes_next_oauth_captures_version_tag_and_advances_to_gateways_without_writes(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)
    flow.current_step = "hermes"

    result = flow.set_hermes(
        agent_version="0.10.0",
        provider="anthropic",
        model="anthropic/claude-opus-4",
        auth_method="oauth",
        api_key="",
    )

    assert result.ok is True
    assert result.message == "Hermes draft saved."
    assert result.next_step == "telegram"
    assert flow.current_step == "telegram"
    assert flow.draft.hermes.agent_version == "0.10.0"
    assert flow.draft.hermes.agent_release_tag == "v2026.4.16"
    assert flow.draft.hermes.provider == "anthropic"
    assert flow.draft.hermes.model == "anthropic/claude-opus-4"
    assert flow.hermes_auth_mode == "oauth"
    assert flow.draft.hermes.api_key.replacement is None
    assert not (tmp_path / ".env").exists()


def test_hermes_next_api_key_requires_key_when_missing_env_and_blocks_unknown_version(tmp_path: Path) -> None:
    flow = PanelConfigFlow.first_run(tmp_path)

    missing_key = flow.set_hermes(
        agent_version="0.10.0",
        provider="openai-codex",
        model="gpt-5.4-mini",
        auth_method="api_key",
        api_key="",
    )
    unknown_version = flow.set_hermes(
        agent_version="0.99.0",
        provider="openai-codex",
        model="gpt-5.4-mini",
        auth_method="oauth",
        api_key="",
    )

    assert missing_key.ok is False
    assert "openai-codex API key is required" in missing_key.message
    assert missing_key.next_step == "hermes"
    assert unknown_version.ok is False
    assert "Unknown Hermes Agent version" in unknown_version.message
    assert flow.current_step == "cloud"


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
