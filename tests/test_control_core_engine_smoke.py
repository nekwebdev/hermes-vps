from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_control_core import RunnerFactory
from hermes_vps_app import build_example_graph, run_example_config_panel
from hermes_vps_app.cloud_remediation import remediation_for, render_remediation
from scripts.configure_services import ConfigureServiceError, ProviderAuthError


class ControlCoreEngineSmokeTests(unittest.TestCase):
    def test_example_graph_is_acyclic_and_well_formed(self) -> None:
        graph = build_example_graph()
        graph.validate()
        self.assertEqual(graph.name, "config_panel_example")
        self.assertEqual(
            set(graph.actions.keys()),
            {
                "validate_env",
                "resolve_runner",
                "load_cloud_options",
                "render_review",
            },
        )

    def test_example_panel_engine_smoke(self) -> None:
        runner = RunnerFactory(repo_root=Path(".")).get()
        result = run_example_config_panel(runner)

        self.assertTrue(result.completed)
        self.assertFalse(result.failed)

        statuses = {action_id: state.status.value for action_id, state in result.states.items()}
        self.assertEqual(
            statuses,
            {
                "validate_env": "succeeded",
                "resolve_runner": "succeeded",
                "load_cloud_options": "succeeded",
                "render_review": "succeeded",
            },
        )

    def test_live_cloud_lookup_strict_preflight_uses_typed_provider_auth_reason(self) -> None:
        runner = RunnerFactory(repo_root=Path(".")).get()
        values = {"provider": "linode", "LINODE_TOKEN": "token"}
        typed_error = ProviderAuthError(
            "token_insufficient_scope",
            "provider denied profile: read scope missing for token abcdefghijkl",
        )

        with patch("hermes_vps_app.config_panel.ensure_expected_toolchain_runtime", return_value=None), patch(
            "hermes_vps_app.config_panel.shutil.which",
            return_value="/usr/bin/linode-cli",
        ), patch(
            "hermes_vps_app.config_panel.ProviderService.auth_probe",
            side_effect=typed_error,
        ), patch(
            "hermes_vps_app.config_panel.ProviderService.location_options"
        ) as location_options_mock, patch(
            "hermes_vps_app.config_panel.ProviderService.server_type_options"
        ) as server_type_options_mock:
            result = run_example_config_panel(
                runner,
                values=values,
                live_cloud_lookup=True,
            )

        self.assertTrue(result.failed)
        error_text = result.states["load_cloud_options"].last_error or ""
        expected = render_remediation(
            remediation_for("linode", "token_insufficient_scope", str(typed_error))
        )
        self.assertEqual(error_text, expected)
        self.assertIn("Reason: token_insufficient_scope", error_text)
        self.assertIn("linode-cli profile view --json --no-defaults --suppress-warnings", error_text)
        self.assertIn("[REDACTED]", error_text)
        self.assertNotIn("abcdefghijkl", error_text)
        location_options_mock.assert_not_called()
        server_type_options_mock.assert_not_called()

    def test_live_cloud_lookup_strict_preflight_gate_and_order(self) -> None:
        runner = RunnerFactory(repo_root=Path(".")).get()

        with self.subTest(case="missing_token"):
            with patch("hermes_vps_app.config_panel.ensure_expected_toolchain_runtime", return_value=None), patch(
                "hermes_vps_app.config_panel.shutil.which",
                return_value="/usr/bin/hcloud",
            ) as which_mock, patch(
                "hermes_vps_app.config_panel.ProviderService.auth_probe"
            ) as auth_probe_mock, patch(
                "hermes_vps_app.config_panel.ProviderService.location_options"
            ) as location_options_mock, patch(
                "hermes_vps_app.config_panel.ProviderService.server_type_options"
            ) as server_type_options_mock:
                result = run_example_config_panel(runner, values={"provider": "hetzner"}, live_cloud_lookup=True)

            self.assertTrue(result.failed)
            self.assertFalse(result.completed)
            self.assertEqual(result.states["load_cloud_options"].status.value, "failed")
            self.assertIn("Reason: missing_token", result.states["load_cloud_options"].last_error or "")
            self.assertIn(result.states["render_review"].status.value, {"pending", "blocked"})
            which_mock.assert_not_called()
            auth_probe_mock.assert_not_called()
            location_options_mock.assert_not_called()
            server_type_options_mock.assert_not_called()

        with self.subTest(case="missing_binary"):
            with patch("hermes_vps_app.config_panel.ensure_expected_toolchain_runtime", return_value=None), patch(
                "hermes_vps_app.config_panel.shutil.which",
                return_value=None,
            ), patch(
                "hermes_vps_app.config_panel.ProviderService.auth_probe"
            ) as auth_probe_mock, patch(
                "hermes_vps_app.config_panel.ProviderService.location_options"
            ) as location_options_mock, patch(
                "hermes_vps_app.config_panel.ProviderService.server_type_options"
            ) as server_type_options_mock:
                result = run_example_config_panel(
                    runner,
                    values={"provider": "hetzner", "HCLOUD_TOKEN": "token"},
                    live_cloud_lookup=True,
                )

            self.assertTrue(result.failed)
            self.assertFalse(result.completed)
            self.assertEqual(result.states["load_cloud_options"].status.value, "failed")
            self.assertIn("Reason: missing_binary", result.states["load_cloud_options"].last_error or "")
            auth_probe_mock.assert_not_called()
            location_options_mock.assert_not_called()
            server_type_options_mock.assert_not_called()

        with self.subTest(case="auth_failure"):
            with patch("hermes_vps_app.config_panel.ensure_expected_toolchain_runtime", return_value=None), patch(
                "hermes_vps_app.config_panel.shutil.which",
                return_value="/usr/bin/hcloud",
            ), patch(
                "hermes_vps_app.config_panel.ProviderService.auth_probe",
                side_effect=ProviderAuthError("auth_unknown", "auth failed"),
            ), patch(
                "hermes_vps_app.config_panel.ProviderService.location_options"
            ) as location_options_mock, patch(
                "hermes_vps_app.config_panel.ProviderService.server_type_options"
            ) as server_type_options_mock:
                result = run_example_config_panel(
                    runner,
                    values={"provider": "hetzner", "HCLOUD_TOKEN": "token"},
                    live_cloud_lookup=True,
                )

            self.assertTrue(result.failed)
            self.assertFalse(result.completed)
            self.assertEqual(result.states["load_cloud_options"].status.value, "failed")
            self.assertIn("Reason: auth_unknown", result.states["load_cloud_options"].last_error or "")
            location_options_mock.assert_not_called()
            server_type_options_mock.assert_not_called()

        with self.subTest(case="metadata_failure"):
            with patch("hermes_vps_app.config_panel.ensure_expected_toolchain_runtime", return_value=None), patch(
                "hermes_vps_app.config_panel.shutil.which",
                return_value="/usr/bin/hcloud",
            ), patch(
                "hermes_vps_app.config_panel.ProviderService.auth_probe",
                return_value=None,
            ), patch(
                "hermes_vps_app.config_panel.ProviderService.location_options",
                side_effect=ConfigureServiceError("metadata down"),
            ), patch(
                "hermes_vps_app.config_panel.ProviderService.server_type_options"
            ) as server_type_options_mock:
                result = run_example_config_panel(
                    runner,
                    values={"provider": "hetzner", "HCLOUD_TOKEN": "token"},
                    live_cloud_lookup=True,
                )

            self.assertTrue(result.failed)
            self.assertFalse(result.completed)
            self.assertEqual(result.states["load_cloud_options"].status.value, "failed")
            self.assertIn("Reason: metadata_unavailable", result.states["load_cloud_options"].last_error or "")
            server_type_options_mock.assert_not_called()

        with patch("hermes_vps_app.config_panel.ensure_expected_toolchain_runtime", return_value=None), patch(
            "hermes_vps_app.config_panel.shutil.which"
        ) as which_mock, patch(
            "hermes_vps_app.config_panel.ProviderService.auth_probe"
        ) as auth_probe_mock, patch(
            "hermes_vps_app.config_panel.ProviderService.location_options"
        ) as location_options_mock, patch(
            "hermes_vps_app.config_panel.ProviderService.server_type_options"
        ) as server_type_options_mock:
            non_live_result = run_example_config_panel(
                runner,
                values={"provider": "hetzner"},
                live_cloud_lookup=False,
            )

        self.assertTrue(non_live_result.completed)
        self.assertFalse(non_live_result.failed)
        load_result = non_live_result.states["load_cloud_options"].result or {}
        self.assertEqual(load_result.get("live_lookup"), False)
        self.assertEqual(load_result.get("types"), ["cx22", "cx32"])
        which_mock.assert_not_called()
        auth_probe_mock.assert_not_called()
        location_options_mock.assert_not_called()
        server_type_options_mock.assert_not_called()


if __name__ == "__main__":
    _ = unittest.main()
