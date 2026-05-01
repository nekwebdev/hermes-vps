from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, final

from hermes_vps_app.cloud_remediation import CloudRemediationPayload, FailureReason, ProviderId, remediation_for
from hermes_vps_app.config_model import (
    EnvPatch,
    ProjectConfigDraft,
    ProjectConfigEnvService,
    SecretDraft,
)
from scripts import configure_logic as logic

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

LiveLookup = Callable[[ProviderId, str], tuple[list[str] | tuple[str, ...], list[str] | tuple[str, ...]]]


@dataclass(frozen=True)
class CloudOptions:
    provider: ProviderId
    lookup_mode: CloudLookupMode
    regions: tuple[str, ...]
    server_types: tuple[str, ...]


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
        flow.hermes_auth_mode = "api_key"
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
        self.draft.change_provider(provider)
        if not self.draft.server.image:
            self.draft.server.image = logic.server_image_for_provider(provider)

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
        if not self.draft.server.hostname:
            issues.append("hostname is required")
        if not self.draft.server.admin_username:
            issues.append("admin username is required")
        if not self.draft.server.admin_group:
            issues.append("admin group is required")
        if not self.draft.server.ssh_private_key_path:
            issues.append("SSH private key path is required")
        if not self.draft.hermes.provider:
            issues.append("Hermes provider is required")
        if not self.draft.hermes.model:
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


def _telegram_fingerprint(token: str, allowlist_ids: str) -> str:
    return f"token_present={bool(token.strip())};allowlist={allowlist_ids.strip()}"
