from __future__ import annotations

import unittest
from unittest.mock import patch

from hermes_vps_app.cloud_remediation import FailureReason, remediation_for, render_remediation
from scripts.configure_services import (
    CommandExecutionError,
    CommandResult,
    ProviderAuthError,
    ProviderService,
)


class CloudRemediationTests(unittest.TestCase):
    class _ScriptedRunner:
        def __init__(self, script: list[Exception]) -> None:
            self.script: list[Exception] = script

        def run(self, argv: list[str], env: dict[str, str] | None = None) -> CommandResult:
            _ = argv
            _ = env
            if not self.script:
                raise RuntimeError("runner script exhausted")
            raise self.script.pop(0)

    def test_auth_probe_classifies_invalid_token(self) -> None:
        runner = self._ScriptedRunner(
            [
                CommandExecutionError(
                    argv=["hcloud", "context", "list", "-o", "json"],
                    returncode=1,
                    stdout="",
                    stderr="authentication failed: token invalid (401)",
                )
            ]
        )
        service = ProviderService(runner)

        with patch.object(ProviderService, "_require_binary", return_value=None):
            with self.assertRaises(ProviderAuthError) as ctx:
                service.auth_probe("hetzner", "token")

        self.assertEqual(ctx.exception.reason, "token_invalid")

    def test_auth_probe_classifies_insufficient_scope(self) -> None:
        runner = self._ScriptedRunner(
            [
                CommandExecutionError(
                    argv=["linode-cli", "profile", "view", "--json", "--no-defaults", "--suppress-warnings"],
                    returncode=1,
                    stdout="",
                    stderr="token has insufficient scope for regions list",
                )
            ]
        )
        service = ProviderService(runner)

        with patch.object(ProviderService, "_require_binary", return_value=None):
            with self.assertRaises(ProviderAuthError) as ctx:
                service.auth_probe("linode", "token")

        self.assertEqual(ctx.exception.reason, "token_insufficient_scope")

    def test_auth_probe_classifies_unknown_auth_failure(self) -> None:
        runner = self._ScriptedRunner(
            [
                CommandExecutionError(
                    argv=["hcloud", "context", "list", "-o", "json"],
                    returncode=1,
                    stdout="",
                    stderr="transient provider error with no auth markers",
                )
            ]
        )
        service = ProviderService(runner)

        with patch.object(ProviderService, "_require_binary", return_value=None):
            with self.assertRaises(ProviderAuthError) as ctx:
                service.auth_probe("hetzner", "token")

        self.assertEqual(ctx.exception.reason, "auth_unknown")

    def test_render_payload_contains_command_specific_checks(self) -> None:
        payload = remediation_for("linode", "missing_binary")
        rendered = render_remediation(payload)
        self.assertIn("linode-cli --version", rendered)
        self.assertIn("expect: exit_code_eq=0", rendered)
        self.assertIn("Token-safe presence check", rendered)

    def test_render_redacts_secret_like_detail_values(self) -> None:
        payload = remediation_for(
            "hetzner",
            "auth_unknown",
            "request failed for token sk_live_ABC123SECRETXYZ",
        )
        rendered = render_remediation(payload)
        self.assertNotIn("sk_live_ABC123SECRETXYZ", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_render_includes_provider_and_typed_reason_header(self) -> None:
        payload = remediation_for("linode", "missing_token")
        rendered = render_remediation(payload)
        self.assertIn("Provider: linode", rendered)
        self.assertIn("Reason: missing_token", rendered)

    def test_payload_covers_all_typed_failure_reasons_with_discriminated_checks(self) -> None:
        reasons: tuple[FailureReason, ...] = (
            "missing_binary",
            "missing_token",
            "token_invalid",
            "token_insufficient_scope",
            "auth_unknown",
            "metadata_unavailable",
        )
        for reason in reasons:
            payload = remediation_for("hetzner", reason)
            self.assertEqual(payload.reason, reason)
            self.assertEqual(payload.provider, "hetzner")
            self.assertEqual(
                {check.kind for check in payload.checks},
                {"binary_present", "token_present", "auth_probe", "metadata_probe"},
            )
            self.assertTrue(payload.install_hints)

    def test_render_includes_docs_and_provider_specific_install_hints(self) -> None:
        payload = remediation_for("linode", "missing_binary")
        rendered = render_remediation(payload)
        self.assertIn("Install hints:", rendered)
        self.assertIn("Install linode-cli in the active toolchain.", rendered)
        self.assertIn("Docs: https://www.linode.com/docs/products/tools/cli/guides/install/", rendered)

    def test_payload_token_presence_check_is_token_safe(self) -> None:
        payload = remediation_for("hetzner", "missing_token")
        token_check = next(check for check in payload.checks if check.kind == "token_present")
        command_text = " ".join(token_check.command)
        self.assertIn('test -n "${HCLOUD_TOKEN:-}"', command_text)
        self.assertNotIn("echo $HCLOUD_TOKEN", command_text)

    def test_rendered_checks_use_machine_checkable_expect_predicate_contract(self) -> None:
        payload = remediation_for("linode", "metadata_unavailable")
        rendered = render_remediation(payload)

        for check in payload.checks:
            expected_line = f"expect: {check.expected.predicate}={check.expected.value}"
            self.assertIn(expected_line, rendered)

    def test_unknown_provider_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _ = remediation_for("digitalocean", "missing_token")


if __name__ == "__main__":
    _ = unittest.main()
