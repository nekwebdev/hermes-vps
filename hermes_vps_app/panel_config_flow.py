from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Any, Literal, cast, final

from scripts.configure_services import CommandRunner, ConfigureServiceError, ProviderAuthError, ProviderService

from hermes_vps_app.cloud_remediation import CloudRemediationPayload, FailureReason, ProviderId, remediation_for
from hermes_vps_app.config_model import (
    EnvPatch,
    ProjectConfigDraft,
    ProjectConfigEnvService,
    SecretDraft,
)
from scripts.configure_state import LabeledValue
from scripts import configure_logic as logic
from hermes_vps_app.hermes_live_metadata import HermesRelease, HermesRuntimeMetadata, ToolchainCacheResult
from hermes_vps_app.hermes_oauth import HermesOAuthRunResult

ConfigMode = Literal["first_run", "reconfigure"]
ConfigStep = Literal["cloud", "server", "hermes", "telegram", "review_apply"]
ConfigSection = Literal["cloud", "server", "hermes", "telegram"]
CloudLookupMode = Literal["sample", "live"]
HermesAuthMode = Literal["api_key", "oauth"]

FIRST_RUN_STEPS: tuple[ConfigStep, ...] = ("cloud", "server", "hermes", "telegram", "review_apply")
RECONFIGURE_SECTIONS: tuple[ConfigSection, ...] = ("cloud", "server", "hermes", "telegram")

_SAMPLE_OPTIONS: dict[ProviderId, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "hetzner": (("fsn1", "nbg1"), ("cx22", "cx32")),
    "linode": (("us-east", "eu-central"), ("g6-standard-1", "g6-standard-2")),
}
_HERMES_VERSION_TAGS: dict[str, str] = {"0.10.0": "v2026.4.16"}
_HERMES_PROVIDER_MODELS: dict[str, tuple[str, ...]] = {
    "openai-codex": ("gpt-5.4-mini", "gpt-5.4"),
    "anthropic": ("anthropic/claude-sonnet-4", "anthropic/claude-opus-4"),
}
_HERMES_AUTH_METHODS: tuple[HermesAuthMode, ...] = ("oauth", "api_key")

LiveLookup = Callable[[ProviderId, str], tuple[list[str] | tuple[str, ...], list[str] | tuple[str, ...]]]


@dataclass(frozen=True)
class CloudOptions:
    provider: ProviderId
    lookup_mode: CloudLookupMode
    regions: tuple[str, ...]
    server_types: tuple[str, ...]


@dataclass(frozen=True)
class CloudMetadataSyncResult:
    provider: ProviderId
    token_fingerprint: str
    regions: tuple[LabeledValue, ...]
    server_types: tuple[LabeledValue, ...]
    selected_region: str
    passed: bool
    summary: str
    remediation: CloudRemediationPayload | None = None

    @classmethod
    def success(
        cls,
        *,
        provider: ProviderId,
        token_fingerprint: str,
        regions: tuple[LabeledValue, ...],
        server_types: tuple[LabeledValue, ...],
        selected_region: str,
        summary: str = "Live cloud metadata synced.",
    ) -> CloudMetadataSyncResult:
        return cls(
            provider=provider,
            token_fingerprint=token_fingerprint,
            regions=regions,
            server_types=server_types,
            selected_region=selected_region,
            passed=True,
            summary=summary,
        )

    @classmethod
    def failure(
        cls,
        *,
        provider: ProviderId,
        token_fingerprint: str,
        selected_region: str,
        summary: str,
        remediation: CloudRemediationPayload,
    ) -> CloudMetadataSyncResult:
        return cls(
            provider=provider,
            token_fingerprint=token_fingerprint,
            regions=(),
            server_types=(),
            selected_region=selected_region,
            passed=False,
            summary=summary,
            remediation=remediation,
        )


CloudMetadataSyncRunner = Callable[[ProviderId, str, str | None], CloudMetadataSyncResult]


@dataclass(frozen=True)
class HostSshDefaults:
    hostname: str
    admin_username: str
    admin_group: str
    ssh_private_key_path: str
    add_ssh_alias: bool
    ssh_alias_name: str = "hermes-vps"


@dataclass(frozen=True)
class HostSshStepResult:
    ok: bool
    message: str
    next_step: ConfigStep


@dataclass(frozen=True)
class HermesDefaults:
    version_options: tuple[tuple[str, str], ...]
    agent_version: str
    agent_release_tag: str
    provider_options: tuple[str, ...]
    provider: str
    model_options: tuple[str, ...]
    model: str
    auth_methods: tuple[HermesAuthMode, ...]
    auth_method: HermesAuthMode


@dataclass(frozen=True)
class HermesStepResult:
    ok: bool
    message: str
    next_step: ConfigStep


@dataclass(frozen=True)
class HermesOAuthArtifact:
    provider: str
    agent_version: str
    agent_release_tag: str
    auth_method: Literal["oauth"]
    auth_json_bytes: bytes
    auth_json_sha256: str


@dataclass(frozen=True)
class CloudLiveCheckResult:
    provider: ProviderId
    passed: bool
    summary: str
    remediation: CloudRemediationPayload | None = None

    @classmethod
    def success(cls, *, provider: ProviderId, summary: str = "Live provider checks passed.") -> CloudLiveCheckResult:
        return cls(provider=provider, passed=True, summary=summary)

    @classmethod
    def failure(
        cls,
        *,
        provider: ProviderId,
        summary: str,
        remediation: CloudRemediationPayload,
    ) -> CloudLiveCheckResult:
        return cls(provider=provider, passed=False, summary=summary, remediation=remediation)


CloudLiveCheckRunner = Callable[[ProviderId, str], CloudLiveCheckResult]


@dataclass(frozen=True)
class ProviderLookupFailureDetail:
    provider: ProviderId
    reason: FailureReason
    title: str
    detail: str
    remediation: CloudRemediationPayload


@final
class ProviderLookupFailure(RuntimeError):
    failure: ProviderLookupFailureDetail

    def __init__(self, failure: ProviderLookupFailureDetail) -> None:
        super().__init__(failure.detail)
        self.failure = failure


@dataclass(frozen=True)
class AsyncValidationRequest:
    request_id: int
    fingerprint: str


@dataclass(frozen=True)
class AsyncValidationResult:
    request_id: int
    fingerprint: str
    ok: bool
    detail: str

    @classmethod
    def success(cls, *, request_id: int, fingerprint: str, detail: str) -> AsyncValidationResult:
        return cls(request_id=request_id, fingerprint=fingerprint, ok=True, detail=detail)

    @classmethod
    def failure(cls, *, request_id: int, fingerprint: str, detail: str) -> AsyncValidationResult:
        return cls(request_id=request_id, fingerprint=fingerprint, ok=False, detail=detail)


@dataclass(frozen=True)
class ValidationAcceptance:
    accepted: bool
    stale: bool
    ok: bool
    detail: str


@dataclass(frozen=True)
class ConfigReview:
    patch: EnvPatch
    redacted_diff: str
    can_apply: bool
    blocking_issues: tuple[str, ...]


@final
class PanelConfigFlow:
    def __init__(self, repo_root: Path, *, mode: ConfigMode, draft: ProjectConfigDraft | None = None) -> None:
        self.repo_root: Path = Path(repo_root)
        self.env_service: ProjectConfigEnvService = ProjectConfigEnvService(self.repo_root)
        self.mode: ConfigMode = mode
        self.steps: tuple[ConfigStep, ...] = FIRST_RUN_STEPS if mode == "first_run" else ()
        self.sections: tuple[ConfigSection, ...] = RECONFIGURE_SECTIONS if mode == "reconfigure" else ()
        self.current_step: ConfigStep | None = "cloud" if mode == "first_run" else None
        self.draft: ProjectConfigDraft = draft if draft is not None else self.env_service.load()
        self.hermes_auth_mode: HermesAuthMode = "api_key" if self.draft.hermes.api_key.present else "oauth"
        self._telegram_request_counter: int = 0
        self._telegram_pending: AsyncValidationRequest | None = None
        self._telegram_validated_fingerprint: str | None = None
        self._telegram_validation_ok: bool = False
        self._telegram_validation_detail: str = ""
        self.cloud_live_check_runner: CloudLiveCheckRunner = _default_cloud_live_check
        self._cloud_live_check_result: CloudLiveCheckResult | None = None
        self._cloud_live_check_fingerprint: str | None = None
        self.cloud_metadata_sync_runner: CloudMetadataSyncRunner = _default_cloud_metadata_sync
        self._cloud_metadata_sync_result: CloudMetadataSyncResult | None = None
        self._hermes_version_tags: dict[str, str] = dict(_HERMES_VERSION_TAGS)
        self._hermes_provider_models: dict[str, tuple[str, ...]] = dict(_HERMES_PROVIDER_MODELS)
        self._hermes_auth_methods: tuple[HermesAuthMode, ...] = _HERMES_AUTH_METHODS
        self._hermes_oauth_artifact: HermesOAuthArtifact | None = None

    @classmethod
    def for_repo(cls, repo_root: Path) -> PanelConfigFlow:
        env_path = Path(repo_root) / ".env"
        if env_path.exists():
            return cls.reconfigure(repo_root)
        return cls.first_run(repo_root)

    @classmethod
    def first_run(cls, repo_root: Path) -> PanelConfigFlow:
        flow = cls(repo_root, mode="first_run")
        flow.draft.original_env = {}
        flow.hermes_auth_mode = "oauth"
        return flow

    @classmethod
    def reconfigure(cls, repo_root: Path) -> PanelConfigFlow:
        service = ProjectConfigEnvService(repo_root)
        return cls(repo_root, mode="reconfigure", draft=service.load())

    def to_screen(self) -> dict[str, object]:
        title = "Configuration required" if self.mode == "first_run" else "Configuration reconfigure"
        payload: dict[str, object] = {
            "title": title,
            "mode": self.mode,
            "state": "configuration_required" if self.mode == "first_run" else "configuration_reconfigure",
            "display": self._display(),
        }
        if self.mode == "first_run":
            payload["steps"] = list(self.steps)
            payload["current_step"] = self.current_step
        else:
            payload["sections"] = list(self.sections)
        return payload

    def cloud_options(
        self,
        *,
        provider: ProviderId,
        lookup_mode: CloudLookupMode,
        live_lookup: LiveLookup | None = None,
    ) -> CloudOptions:
        if lookup_mode == "sample":
            regions, server_types = _SAMPLE_OPTIONS[provider]
            return CloudOptions(provider=provider, lookup_mode="sample", regions=regions, server_types=server_types)
        if live_lookup is None:
            failure = _provider_failure(provider, "metadata_unavailable", "live lookup service is unavailable")
            raise ProviderLookupFailure(failure)
        try:
            regions_raw, types_raw = live_lookup(provider, self.draft.server.location)
        except Exception as exc:
            failure = _provider_failure(provider, "metadata_unavailable", str(exc))
            raise ProviderLookupFailure(failure) from exc
        return CloudOptions(
            provider=provider,
            lookup_mode="live",
            regions=tuple(regions_raw),
            server_types=tuple(types_raw),
        )

    def set_cloud(self, *, provider: ProviderId, lookup_mode: CloudLookupMode) -> None:
        del lookup_mode
        previous_provider = self.draft.provider.provider
        self.draft.change_provider(provider)
        if previous_provider != provider:
            self.invalidate_cloud_live_check()
            self.invalidate_cloud_metadata_sync()
        if not self.draft.server.image:
            self.draft.server.image = logic.server_image_for_provider(provider)

    def run_cloud_live_checks(self, *, provider: ProviderId, token: str) -> CloudLiveCheckResult:
        fingerprint = _cloud_live_check_fingerprint(provider, token)
        result = self.cloud_live_check_runner(provider, token)
        self._cloud_live_check_result = result
        self._cloud_live_check_fingerprint = fingerprint
        return result

    def sync_cloud_metadata(
        self,
        *,
        provider: ProviderId,
        token: str,
        selected_region: str | None = None,
    ) -> CloudMetadataSyncResult:
        result = self.cloud_metadata_sync_runner(provider, token, selected_region)
        self.record_cloud_metadata_sync_result(result)
        return result

    def record_cloud_metadata_sync_result(self, result: CloudMetadataSyncResult) -> None:
        self._cloud_metadata_sync_result = result
        if result.passed:
            self.draft.server.location = result.selected_region
            recommended = next((item.value for item in result.server_types if item.recommended), None)
            self.draft.server.server_type = recommended or (result.server_types[0].value if result.server_types else "")

    def invalidate_cloud_metadata_sync(self) -> None:
        self._cloud_metadata_sync_result = None
        self.draft.server.location = ""
        self.draft.server.server_type = ""

    def cloud_metadata_sync_result(self) -> CloudMetadataSyncResult | None:
        return self._cloud_metadata_sync_result

    @property
    def cloud_metadata_synced(self) -> bool:
        result = self._cloud_metadata_sync_result
        return bool(result and result.passed)

    def has_valid_cloud_metadata_sync(self, *, provider: ProviderId, token: str, region: str, server_type: str) -> bool:
        result = self._cloud_metadata_sync_result
        if not result or not result.passed:
            return False
        if result.provider != provider or result.token_fingerprint != _cloud_live_check_fingerprint(provider, token):
            return False
        if result.selected_region != region:
            return False
        return server_type in {item.value for item in result.server_types}

    def invalidate_cloud_live_check(self) -> None:
        self._cloud_live_check_result = None
        self._cloud_live_check_fingerprint = None

    def cloud_live_check_result(self) -> CloudLiveCheckResult | None:
        return self._cloud_live_check_result

    @property
    def cloud_live_check_passed(self) -> bool:
        result = self._cloud_live_check_result
        return bool(result and result.passed)

    def has_valid_cloud_live_check(self, *, provider: ProviderId, token: str) -> bool:
        result = self._cloud_live_check_result
        return bool(
            result
            and result.passed
            and result.provider == provider
            and self._cloud_live_check_fingerprint == _cloud_live_check_fingerprint(provider, token)
        )

    def set_server(
        self,
        *,
        location: str,
        server_type: str,
        hostname: str,
        admin_username: str,
        admin_group: str,
        ssh_private_key_path: str,
        ssh_port: str = "22",
    ) -> None:
        self.draft.server.location = location
        self.draft.server.server_type = server_type
        self.draft.server.hostname = hostname
        self.draft.server.admin_username = admin_username
        self.draft.server.admin_group = admin_group
        self.draft.server.ssh_private_key_path = ssh_private_key_path
        self.draft.server.ssh_port = ssh_port
        if not self.draft.server.image:
            self.draft.server.image = logic.server_image_for_provider(self.draft.provider.provider)

    def host_ssh_defaults(self) -> HostSshDefaults:
        server = self.draft.server
        return HostSshDefaults(
            hostname=server.hostname or "hermes-vps",
            admin_username=server.admin_username or "hermes",
            admin_group=server.admin_group or "hermes-admins",
            ssh_private_key_path=server.ssh_private_key_path or "~/.ssh/hermes-vps",
            add_ssh_alias=server.add_ssh_alias,
        )

    def set_host_ssh(
        self,
        *,
        hostname: str,
        admin_username: str,
        admin_group: str,
        ssh_private_key_path: str,
        add_ssh_alias: bool,
    ) -> HostSshStepResult:
        errors = self.validate_host_ssh(
            hostname=hostname,
            admin_username=admin_username,
            admin_group=admin_group,
            ssh_private_key_path=ssh_private_key_path,
        )
        if errors:
            return HostSshStepResult(ok=False, message="; ".join(errors), next_step="server")
        self.draft.server.hostname = hostname.strip()
        self.draft.server.admin_username = admin_username.strip()
        self.draft.server.admin_group = admin_group.strip()
        self.draft.server.ssh_private_key_path = ssh_private_key_path.strip()
        self.draft.server.add_ssh_alias = add_ssh_alias
        self.current_step = "hermes"
        return HostSshStepResult(ok=True, message="Host & SSH draft saved.", next_step="hermes")

    def validate_host_ssh(
        self,
        *,
        hostname: str,
        admin_username: str,
        admin_group: str,
        ssh_private_key_path: str,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        hostname_value = hostname.strip()
        username_value = admin_username.strip()
        group_value = admin_group.strip()
        key_path_value = ssh_private_key_path.strip()
        if not hostname_value:
            errors.append("hostname is required")
        elif not _is_valid_hostname(hostname_value):
            errors.append("hostname must be RFC-1123 compatible")
        if not username_value:
            errors.append("admin username is required")
        elif not _is_valid_unix_name(username_value):
            errors.append("admin username must be a valid UNIX username")
        if not group_value:
            errors.append("admin group is required")
        elif not _is_valid_unix_name(group_value):
            errors.append("admin group must be a valid UNIX group name")
        if not key_path_value:
            errors.append("SSH private key path is required")
        elif _is_repo_relative_or_contained(key_path_value, self.repo_root):
            errors.append("SSH private key path must be outside the repository")
        return tuple(errors)

    def set_hermes_api_key(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        agent_version: str = "",
        agent_release_tag: str = "",
    ) -> None:
        self.hermes_auth_mode = "api_key"
        self.draft.hermes.provider = provider
        self.draft.hermes.model = model
        self.draft.hermes.agent_version = agent_version
        self.draft.hermes.agent_release_tag = agent_release_tag
        self.draft.hermes.api_key = SecretDraft.replace(api_key)

    def hermes_defaults(self, *, provider: str | None = None, model: str | None = None) -> HermesDefaults:
        hermes = self.draft.hermes
        version = hermes.agent_version if hermes.agent_version in self._hermes_version_tags else "0.10.0"
        provider_value = provider or hermes.provider or "openai-codex"
        if provider_value not in self._hermes_provider_models:
            provider_value = "openai-codex"
        model_options = self._hermes_provider_models[provider_value]
        model_value = model or hermes.model
        if not model_options:
            model_value = ""
        elif model_value not in model_options:
            model_value = model_options[0]
        auth_method = self.hermes_auth_mode if self.hermes_auth_mode in self._hermes_auth_methods else "oauth"
        return HermesDefaults(
            version_options=tuple(self._hermes_version_tags.items()),
            agent_version=version,
            agent_release_tag=self._hermes_version_tags[version],
            provider_options=tuple(self._hermes_provider_models),
            provider=provider_value,
            model_options=model_options,
            model=model_value,
            auth_methods=self._hermes_auth_methods,
            auth_method=auth_method,
        )

    def sync_hermes_live_metadata(
        self,
        *,
        release_service: Any,
        cache_service: Any,
        runtime_metadata_service: Any,
        request_id: str,
        force_refresh: bool = False,
    ) -> HermesDefaults:
        releases: tuple[HermesRelease, ...] = tuple(
            release_service.latest_releases(force_refresh=force_refresh)
        )
        if not releases:
            raise RuntimeError("Could not load Hermes Agent releases from GitHub. Check network/GitHub access, then retry.")
        version_options = tuple((release.semantic_version, release.release_tag) for release in releases)
        releases_by_version = {release.semantic_version: release for release in releases}
        existing_version = self.draft.hermes.agent_version.strip()
        if existing_version and existing_version not in releases_by_version:
            raise RuntimeError(
                f"Configured Hermes Agent version {existing_version} is outside the current live Hermes Agent release list. Choose a listed version before continuing."
            )
        selected_release = releases_by_version[existing_version] if existing_version else releases[0]
        cache_result: ToolchainCacheResult = cache_service.prepare(
            selected_release.semantic_version,
            selected_release.release_tag,
            request_id=request_id,
        )
        current_provider = self.draft.hermes.provider or "openai-codex"
        metadata: HermesRuntimeMetadata = runtime_metadata_service.load(
            cache_dir=cache_result.cache_dir,
            provider=current_provider,
        )
        provider_options = metadata.providers
        if not provider_options:
            raise RuntimeError(
                "Selected Hermes returned no provider metadata. Rebuild the selected Hermes toolchain cache, then retry."
            )
        provider_value = current_provider if current_provider in provider_options else (
            "openai-codex" if "openai-codex" in provider_options else provider_options[0]
        )
        if provider_value != current_provider:
            metadata = runtime_metadata_service.load(cache_dir=cache_result.cache_dir, provider=provider_value)
        if not metadata.auth_methods:
            raise RuntimeError(
                f"Selected Hermes returned no auth metadata for provider {provider_value}. Choose another provider or retry."
            )
        live_auth_methods = tuple(
            cast(HermesAuthMode, item) for item in metadata.auth_methods if item in ("oauth", "api_key")
        )
        if not live_auth_methods:
            raise RuntimeError(
                f"Selected Hermes returned no supported auth metadata for provider {provider_value}. Choose another provider or retry."
            )
        self._hermes_version_tags = dict(version_options)
        self._hermes_provider_models = {provider: () for provider in provider_options}
        self._hermes_provider_models[provider_value] = metadata.models
        self._hermes_auth_methods = live_auth_methods
        if not metadata.models:
            model_value = ""
        else:
            model_value = self.draft.hermes.model if self.draft.hermes.model in metadata.models else (
                "gpt-5.4-mini" if "gpt-5.4-mini" in metadata.models else metadata.models[0]
            )
        auth_method = self.hermes_auth_mode if self.hermes_auth_mode in live_auth_methods else (
            "oauth" if "oauth" in live_auth_methods else live_auth_methods[0]
        )
        return HermesDefaults(
            version_options=version_options,
            agent_version=selected_release.semantic_version,
            agent_release_tag=selected_release.release_tag,
            provider_options=provider_options,
            provider=provider_value,
            model_options=metadata.models,
            model=model_value,
            auth_methods=live_auth_methods,
            auth_method=cast(HermesAuthMode, auth_method),
        )

    def set_hermes(
        self,
        *,
        agent_version: str,
        provider: str,
        model: str,
        auth_method: HermesAuthMode,
        api_key: str,
    ) -> HermesStepResult:
        errors = list(
            self.validate_hermes(
                agent_version=agent_version,
                provider=provider,
                model=model,
                auth_method=auth_method,
                api_key=api_key,
            )
        )
        if errors:
            return HermesStepResult(ok=False, message="; ".join(errors), next_step="hermes")
        release_tag = self._hermes_version_tags[agent_version.strip()]
        self.draft.hermes.agent_version = agent_version.strip()
        self.draft.hermes.agent_release_tag = release_tag
        self.draft.hermes.provider = provider.strip()
        self.draft.hermes.model = model.strip()
        self.hermes_auth_mode = auth_method
        if auth_method == "api_key":
            replacement = api_key.strip()
            if replacement:
                self.draft.hermes.api_key = SecretDraft.replace(replacement)
        else:
            self.draft.hermes.api_key = SecretDraft.keep_existing(False)
        self.current_step = "telegram"
        return HermesStepResult(ok=True, message="Hermes draft saved.", next_step="telegram")

    def validate_hermes(
        self,
        *,
        agent_version: str,
        provider: str,
        model: str,
        auth_method: str,
        api_key: str,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        version_value = agent_version.strip()
        provider_value = provider.strip()
        model_value = model.strip()
        if not _SEMVER_RE.fullmatch(version_value):
            errors.append("Hermes Agent version must be MAJOR.MINOR.PATCH")
        elif version_value not in self._hermes_version_tags:
            errors.append("Unknown Hermes Agent version in live version map")
        if provider_value not in self._hermes_provider_models:
            errors.append("Hermes provider is required")
        elif self._hermes_provider_models[provider_value] and model_value not in self._hermes_provider_models[provider_value]:
            errors.append("Hermes model is required")
        if auth_method not in self._hermes_auth_methods:
            errors.append("Hermes auth method is required")
        elif auth_method == "api_key" and not (api_key.strip() or self.draft.hermes.api_key.present):
            provider_label = provider_value or "Selected provider"
            errors.append(f"{provider_label} API key is required")
        return tuple(errors)

    def set_hermes_oauth(
        self,
        *,
        provider: str,
        model: str,
        agent_version: str = "",
        agent_release_tag: str = "",
    ) -> None:
        self.hermes_auth_mode = "oauth"
        self.draft.hermes.provider = provider
        self.draft.hermes.model = model
        self.draft.hermes.agent_version = agent_version
        self.draft.hermes.agent_release_tag = agent_release_tag
        self.draft.hermes.api_key = SecretDraft.keep_existing(False)

    def record_hermes_oauth_result(self, result: HermesOAuthRunResult) -> None:
        if result.status != "succeeded" or result.auth_json_bytes is None or result.auth_json_sha256 is None:
            self._hermes_oauth_artifact = None
            return
        self._hermes_oauth_artifact = HermesOAuthArtifact(
            provider=result.provider,
            agent_version=result.agent_version,
            agent_release_tag=result.agent_release_tag,
            auth_method="oauth",
            auth_json_bytes=result.auth_json_bytes,
            auth_json_sha256=result.auth_json_sha256,
        )

    def clear_hermes_oauth_artifact(self) -> None:
        self._hermes_oauth_artifact = None

    def has_current_hermes_oauth_artifact(
        self,
        *,
        agent_version: str,
        agent_release_tag: str,
        provider: str,
        auth_method: str,
    ) -> bool:
        artifact = self._hermes_oauth_artifact
        return bool(
            artifact is not None
            and artifact.agent_version == agent_version.strip()
            and artifact.agent_release_tag == agent_release_tag.strip()
            and artifact.provider == provider.strip()
            and artifact.auth_method == auth_method
            and artifact.auth_json_bytes
        )

    def begin_telegram_validation(self, *, token: str, allowlist_ids: str) -> AsyncValidationRequest:
        self.draft.gateway.telegram_bot_token = SecretDraft.replace(token)
        self.draft.gateway.telegram_allowlist_ids = allowlist_ids
        self._telegram_request_counter += 1
        request = AsyncValidationRequest(
            request_id=self._telegram_request_counter,
            fingerprint=_telegram_fingerprint(token, allowlist_ids),
        )
        self._telegram_pending = request
        self._telegram_validated_fingerprint = None
        self._telegram_validation_ok = False
        self._telegram_validation_detail = ""
        return request

    def complete_telegram_validation(self, result: AsyncValidationResult) -> ValidationAcceptance:
        pending = self._telegram_pending
        if pending is None or pending.request_id != result.request_id or pending.fingerprint != result.fingerprint:
            return ValidationAcceptance(accepted=False, stale=True, ok=False, detail=result.detail)
        self._telegram_validated_fingerprint = result.fingerprint
        self._telegram_validation_ok = result.ok
        self._telegram_validation_detail = result.detail
        self._telegram_pending = None
        return ValidationAcceptance(accepted=True, stale=False, ok=result.ok, detail=result.detail)

    def review(self) -> ConfigReview:
        patch = self.env_service.create_patch(self.draft)
        issues = list(self._blocking_issues())
        return ConfigReview(
            patch=patch,
            redacted_diff=patch.redacted_diff(),
            can_apply=not issues,
            blocking_issues=tuple(issues),
        )

    def apply_review(self, review: ConfigReview) -> None:
        if not review.can_apply:
            joined = "; ".join(review.blocking_issues)
            raise ValueError(f"configuration review cannot be applied: {joined}")
        self.env_service.write_patch(review.patch)

    def _display(self) -> dict[str, dict[str, str]]:
        display = self.draft.to_display_dict()
        hermes = dict(display["hermes"])
        hermes["auth_mode"] = self.hermes_auth_mode
        if self.hermes_auth_mode == "oauth":
            hermes["api_key"] = "<not used: oauth>"
        display["hermes"] = hermes
        return display

    def _blocking_issues(self) -> tuple[str, ...]:
        issues: list[str] = []
        issues.extend(issue.message for issue in self.env_service.validate(self.draft))
        issues.extend(
            self.validate_host_ssh(
                hostname=self.draft.server.hostname,
                admin_username=self.draft.server.admin_username,
                admin_group=self.draft.server.admin_group,
                ssh_private_key_path=self.draft.server.ssh_private_key_path,
            )
        )
        if not self.draft.hermes.provider:
            issues.append("Hermes provider is required")
        if not self.draft.hermes.model and self._hermes_provider_models.get(self.draft.hermes.provider, ("__requires_model__",)):
            issues.append("Hermes model is required")
        if self.hermes_auth_mode == "api_key" and not (
            self.draft.hermes.api_key.present or self.draft.hermes.api_key.replacement
        ):
            issues.append("Hermes API key is required for API-key auth")
        allowlist = self.draft.gateway.telegram_allowlist_ids
        if not allowlist or not logic.is_valid_telegram_allowlist(allowlist):
            issues.append("Telegram allowlist must contain comma-separated integer chat IDs")
        if self._telegram_requires_validation():
            token = self.draft.gateway.telegram_bot_token.replacement or ""
            current_fingerprint = _telegram_fingerprint(token, allowlist)
            if self._telegram_validated_fingerprint != current_fingerprint:
                issues.append("telegram validation is required")
            elif not self._telegram_validation_ok:
                issues.append(f"telegram validation failed: {self._telegram_validation_detail}")
        return tuple(dict.fromkeys(issues))

    def _telegram_requires_validation(self) -> bool:
        if self.mode == "first_run":
            return True
        if self.draft.gateway.telegram_bot_token.replacement is not None:
            return True
        original = self.draft.original_env
        if original.get("TELEGRAM_ALLOWLIST_IDS", "") != self.draft.gateway.telegram_allowlist_ids:
            return True
        return not self.draft.gateway.telegram_bot_token.present


def _provider_failure(provider: ProviderId, reason: FailureReason, detail: str) -> ProviderLookupFailureDetail:
    remediation = remediation_for(provider, reason, detail)
    provider_label = "Hetzner" if provider == "hetzner" else "Linode"
    return ProviderLookupFailureDetail(
        provider=provider,
        reason=reason,
        title=f"{provider_label} live lookup failed",
        detail=remediation.summary,
        remediation=remediation,
    )


def _cloud_live_check_fingerprint(provider: ProviderId, token: str) -> str:
    return f"provider={provider};token_present={bool(token.strip())};token_len={len(token.strip())}"


_HOSTNAME_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_UNIX_NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _is_valid_hostname(value: str) -> bool:
    if len(value) > 253:
        return False
    return all(_HOSTNAME_LABEL_RE.fullmatch(label) for label in value.split(".") if label) and ".." not in value


def _is_valid_unix_name(value: str) -> bool:
    return bool(_UNIX_NAME_RE.fullmatch(value))


def _is_repo_relative_or_contained(value: str, repo_root: Path) -> bool:
    if value.startswith("~/") or value == "~":
        return False
    path = Path(value)
    if not path.is_absolute():
        return True
    try:
        path.resolve(strict=False).relative_to(repo_root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _default_cloud_metadata_sync(provider: ProviderId, token: str, selected_region: str | None) -> CloudMetadataSyncResult:
    fingerprint = _cloud_live_check_fingerprint(provider, token)
    if not token.strip():
        remediation = remediation_for(provider, "missing_token")
        return CloudMetadataSyncResult.failure(
            provider=provider,
            token_fingerprint=fingerprint,
            selected_region=selected_region or "",
            summary=remediation.summary,
            remediation=remediation,
        )

    required_binary = "hcloud" if provider == "hetzner" else "linode-cli"
    if shutil.which(required_binary) is None:
        remediation = remediation_for(provider, "missing_binary")
        return CloudMetadataSyncResult.failure(
            provider=provider,
            token_fingerprint=fingerprint,
            selected_region=selected_region or "",
            summary=remediation.summary,
            remediation=remediation,
        )

    service = ProviderService(CommandRunner())
    try:
        service.auth_probe(provider, token)
    except ProviderAuthError as exc:
        remediation = remediation_for(provider, exc.reason, str(exc))
        return CloudMetadataSyncResult.failure(
            provider=provider,
            token_fingerprint=fingerprint,
            selected_region=selected_region or "",
            summary=remediation.summary,
            remediation=remediation,
        )

    try:
        regions = tuple(service.location_options(provider, token))
    except ConfigureServiceError as exc:
        remediation = remediation_for(provider, "metadata_unavailable", str(exc))
        return CloudMetadataSyncResult.failure(
            provider=provider,
            token_fingerprint=fingerprint,
            selected_region=selected_region or "",
            summary=remediation.summary,
            remediation=remediation,
        )
    if not regions:
        remediation = remediation_for(provider, "metadata_unavailable", "provider returned no regions")
        return CloudMetadataSyncResult.failure(
            provider=provider,
            token_fingerprint=fingerprint,
            selected_region=selected_region or "",
            summary=remediation.summary,
            remediation=remediation,
        )

    region_values = {item.value for item in regions}
    region = selected_region if selected_region in region_values else regions[0].value
    try:
        server_types = tuple(service.server_type_options(provider, region, token))
    except ConfigureServiceError as exc:
        remediation = remediation_for(provider, "metadata_unavailable", str(exc))
        return CloudMetadataSyncResult.failure(
            provider=provider,
            token_fingerprint=fingerprint,
            selected_region=region,
            summary=remediation.summary,
            remediation=remediation,
        )
    if not server_types:
        remediation = remediation_for(provider, "metadata_unavailable", f"provider returned no server types for region {region}")
        return CloudMetadataSyncResult.failure(
            provider=provider,
            token_fingerprint=fingerprint,
            selected_region=region,
            summary=remediation.summary,
            remediation=remediation,
        )

    return CloudMetadataSyncResult.success(
        provider=provider,
        token_fingerprint=fingerprint,
        regions=regions,
        server_types=server_types,
        selected_region=region,
    )


def _default_cloud_live_check(provider: ProviderId, token: str) -> CloudLiveCheckResult:
    if not token.strip():
        remediation = remediation_for(provider, "missing_token")
        return CloudLiveCheckResult.failure(provider=provider, summary=remediation.summary, remediation=remediation)

    required_binary = "hcloud" if provider == "hetzner" else "linode-cli"
    if shutil.which(required_binary) is None:
        remediation = remediation_for(provider, "missing_binary")
        return CloudLiveCheckResult.failure(provider=provider, summary=remediation.summary, remediation=remediation)

    service = ProviderService(CommandRunner())
    try:
        service.auth_probe(provider, token)
    except ProviderAuthError as exc:
        remediation = remediation_for(provider, exc.reason, str(exc))
        return CloudLiveCheckResult.failure(provider=provider, summary=remediation.summary, remediation=remediation)

    try:
        locations = service.location_options(provider, token)
    except ConfigureServiceError as exc:
        remediation = remediation_for(provider, "metadata_unavailable", str(exc))
        return CloudLiveCheckResult.failure(provider=provider, summary=remediation.summary, remediation=remediation)
    if not locations:
        remediation = remediation_for(provider, "metadata_unavailable", "provider returned no locations")
        return CloudLiveCheckResult.failure(provider=provider, summary=remediation.summary, remediation=remediation)

    return CloudLiveCheckResult.success(provider=provider)


def _telegram_fingerprint(token: str, allowlist_ids: str) -> str:
    return f"token_present={bool(token.strip())};allowlist={allowlist_ids.strip()}"
