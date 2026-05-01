# pyright: reportUnusedCallResult=false, reportImplicitOverride=false, reportAny=false
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class MonitoringPanelV1Tests(unittest.TestCase):
    def test_shell_navigation_exposes_monitoring_as_read_only_observability(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        navigation = shell.navigation()

        self.assertIn("monitoring", navigation)
        self.assertIn("read-only", navigation["monitoring"].lower())
        self.assertIn("observability", navigation["monitoring"].lower())

    def test_shell_and_headless_share_same_local_readiness_graph_definition_identity(self) -> None:
        from hermes_vps_app import operational
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        self.assertIs(shell.monitoring_graph_builder, operational.build_monitoring_graph)

    def test_monitoring_graph_actions_are_all_read_only(self) -> None:
        from hermes_vps_app.operational import build_monitoring_graph

        graph = build_monitoring_graph()
        self.assertGreater(len(graph.actions), 0)
        for descriptor in graph.actions.values():
            self.assertEqual(descriptor.side_effect_level, "none")

    def test_headless_monitoring_entrypoint_returns_structured_local_readiness_without_remote_execution(self) -> None:
        from hermes_vps_app.operational import run_monitoring_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            env_path.write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
            (root / ".env.example").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            (root / "opentofu/providers/hetzner").mkdir(parents=True)
            (root / "opentofu/providers/hetzner/tofuplan").write_text("plan", encoding="utf-8")

            result = run_monitoring_graph(repo_root=root, provider_override="hetzner")

        self.assertTrue(result["completed"])
        self.assertEqual(result["panel"], "monitoring")
        self.assertEqual(result["mode"], "on-demand")
        self.assertIn("local_readiness", result)
        self.assertIn("checks", result["local_readiness"])
        check_ids = {item["probe_id"] for item in result["local_readiness"]["checks"]}
        self.assertIn("runner_toolchain_readiness", check_ids)
        self.assertIn("env_file_posture", check_ids)
        self.assertIn("provider_resolution", check_ids)
        self.assertIn("provider_directory", check_ids)
        self.assertIn("local_command_availability", check_ids)
        self.assertIn("saved_plan_summary", check_ids)

        remote = result["remote_vps_probes"]
        self.assertEqual(remote["status"], "follow-up")
        self.assertIn("not run", remote["summary"].lower())

    def test_cli_monitoring_entrypoint_runs_without_runner_factory_or_remote_execution(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / ".env.example").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            with patch("hermes_vps_app.cli.RunnerFactory.get", side_effect=AssertionError("should not be called")):
                rc = main(["monitoring", "--repo-root", str(root), "--provider", "hetzner"])

        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
