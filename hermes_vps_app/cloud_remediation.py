from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

ProviderId = Literal["hetzner", "linode"]
FailureReason = Literal[
    "missing_binary",
    "missing_token",
    "token_invalid",
    "token_insufficient_scope",
    "auth_unknown",
    "metadata_unavailable",
]
PredicateType = Literal["exit_code_eq", "json_path_exists", "stdout_regex"]
CheckKind = Literal["binary_present", "token_present", "auth_probe", "metadata_probe"]


@dataclass(frozen=True)
class OutcomePredicate:
    predicate: PredicateType
    value: str


@dataclass(frozen=True)
class RemediationCheck:
    kind: CheckKind
    command: list[str]
    expected: OutcomePredicate
    note: str | None = None


@dataclass(frozen=True)
class CloudRemediationPayload:
    provider: ProviderId
    reason: FailureReason
    summary: str
    checks: list[RemediationCheck]
    install_hints: list[str]
    docs_url: str | None = None


def remediation_for(provider: str, reason: FailureReason, detail: str | None = None) -> CloudRemediationPayload:
    if provider not in ("hetzner", "linode"):
        raise ValueError(f"Unsupported provider for cloud remediation: {provider}")

    normalized: ProviderId = provider
    safe_detail = _sanitize_detail(detail)

    if normalized == "hetzner":
        return _hetzner(reason, safe_detail)
    return _linode(reason, safe_detail)


def render_remediation(payload: CloudRemediationPayload) -> str:
    lines: list[str] = [
        f"Provider: {payload.provider}",
        f"Reason: {payload.reason}",
        payload.summary,
    ]
    if payload.checks:
        lines.append("Checks:")
        for check in payload.checks:
            cmd = " ".join(check.command)
            lines.append(f"- [{check.kind}] {cmd}")
            lines.append(f"  expect: {check.expected.predicate}={check.expected.value}")
            if check.note:
                lines.append(f"  note: {check.note}")
    if payload.install_hints:
        lines.append("Install hints:")
        for hint in payload.install_hints:
            lines.append(f"- {hint}")
    if payload.docs_url:
        lines.append(f"Docs: {payload.docs_url}")
    return "\n".join(lines)


def _sanitize_detail(detail: str | None) -> str | None:
    if not detail:
        return None
    sanitized = detail
    sanitized = re.sub(r"(?i)(token\s*[=:]?\s*)([A-Za-z0-9_\-]{8,})", r"\1[REDACTED]", sanitized)
    sanitized = re.sub(r"(?i)(authorization\s*[=:]?\s*bearer\s+)([^\s]+)", r"\1[REDACTED]", sanitized)
    sanitized = re.sub(r"\b(sk_(?:live|test)_[A-Za-z0-9]+)\b", "[REDACTED]", sanitized)
    return sanitized


def _hetzner(reason: FailureReason, detail: str | None) -> CloudRemediationPayload:
    docs = "https://github.com/hetznercloud/cli"
    install = [
        "Install hcloud CLI in the active toolchain.",
        "Set HCLOUD_TOKEN with a token that can read account/context/location/server-type metadata.",
    ]
    checks = [
        RemediationCheck(
            kind="binary_present",
            command=["hcloud", "version"],
            expected=OutcomePredicate("exit_code_eq", "0"),
        ),
        RemediationCheck(
            kind="token_present",
            command=["bash", "-lc", "test -n \"${HCLOUD_TOKEN:-}\""],
            expected=OutcomePredicate("exit_code_eq", "0"),
            note="Token-safe presence check only; never echo token.",
        ),
        RemediationCheck(
            kind="auth_probe",
            command=["hcloud", "context", "list", "-o", "json"],
            expected=OutcomePredicate("exit_code_eq", "0"),
        ),
        RemediationCheck(
            kind="metadata_probe",
            command=["hcloud", "location", "list", "-o", "json"],
            expected=OutcomePredicate("json_path_exists", "$[0].name"),
        ),
    ]

    summary = "Live cloud lookup blocked for Hetzner."
    if reason == "missing_binary":
        summary = "Live cloud lookup blocked: hcloud binary not found."
    elif reason == "missing_token":
        summary = "Live cloud lookup blocked: HCLOUD_TOKEN is missing."
    elif reason == "token_invalid":
        summary = "Hetzner authentication failed: token appears invalid."
    elif reason == "token_insufficient_scope":
        summary = "Hetzner authentication failed: token appears to lack required read scope."
    elif reason == "auth_unknown":
        summary = "Hetzner authentication failed with inconclusive diagnostics."
    elif reason == "metadata_unavailable":
        summary = "Hetzner metadata lookup failed (locations/server types unavailable)."
    if detail:
        summary = f"{summary} Detail: {detail}"

    return CloudRemediationPayload(
        provider="hetzner",
        reason=reason,
        summary=summary,
        checks=checks,
        install_hints=install,
        docs_url=docs,
    )


def _linode(reason: FailureReason, detail: str | None) -> CloudRemediationPayload:
    docs = "https://www.linode.com/docs/products/tools/cli/guides/install/"
    install = [
        "Install linode-cli in the active toolchain.",
        "Set LINODE_TOKEN with a token that can read profile/regions/instance types.",
    ]
    checks = [
        RemediationCheck(
            kind="binary_present",
            command=["linode-cli", "--version"],
            expected=OutcomePredicate("exit_code_eq", "0"),
        ),
        RemediationCheck(
            kind="token_present",
            command=["bash", "-lc", "test -n \"${LINODE_TOKEN:-}\""],
            expected=OutcomePredicate("exit_code_eq", "0"),
            note="Token-safe presence check only; never echo token.",
        ),
        RemediationCheck(
            kind="auth_probe",
            command=[
                "linode-cli",
                "profile",
                "view",
                "--json",
                "--no-defaults",
                "--suppress-warnings",
            ],
            expected=OutcomePredicate("json_path_exists", "$[0].email"),
        ),
        RemediationCheck(
            kind="metadata_probe",
            command=[
                "linode-cli",
                "regions",
                "list",
                "--json",
                "--no-defaults",
                "--suppress-warnings",
            ],
            expected=OutcomePredicate("json_path_exists", "$[0].id"),
        ),
    ]

    summary = "Live cloud lookup blocked for Linode."
    if reason == "missing_binary":
        summary = "Live cloud lookup blocked: linode-cli binary not found."
    elif reason == "missing_token":
        summary = "Live cloud lookup blocked: LINODE_TOKEN is missing."
    elif reason == "token_invalid":
        summary = "Linode authentication failed: token appears invalid."
    elif reason == "token_insufficient_scope":
        summary = "Linode authentication failed: token appears to lack required read scope."
    elif reason == "auth_unknown":
        summary = "Linode authentication failed with inconclusive diagnostics."
    elif reason == "metadata_unavailable":
        summary = "Linode metadata lookup failed (regions/instance types unavailable)."
    if detail:
        summary = f"{summary} Detail: {detail}"

    return CloudRemediationPayload(
        provider="linode",
        reason=reason,
        summary=summary,
        checks=checks,
        install_hints=install,
        docs_url=docs,
    )
