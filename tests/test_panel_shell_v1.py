# pyright: reportUnusedCallResult=false, reportImplicitOverride=false
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from hermes_control_core import RunRequest, RunResult, Runner, SessionAuditLog
from hermes_control_core.interfaces import RunnerMode


@dataclass
class RunnerStub(Runner):
    mode: RunnerMode = "direnv_nix"

    def run(self, request: RunRequest) -> RunResult:
        return RunResult(
            exit_code=0,
            stdout="ok",
            stderr="",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            runner_mode=self.mode,
            redactions_applied=True,
        )


class PanelShellV1Tests(unittest.TestCase):
    def test_shell_navigation_separates_glossary_panel_flows(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        navigation = shell.navigation()

        self.assertEqual(
            set(navigation),
            {"config", "maintenance", "monitoring", "deployment"},
        )
        self.assertIn("configuration", navigation["config"].lower())
        self.assertIn("maintenance", navigation["maintenance"].lower())
        self.assertIn("monitoring", navigation["monitoring"].lower())
        self.assertIn("deployment", navigation["deployment"].lower())
        self.assertIn("state-changing", navigation["maintenance"].lower())
        self.assertIn("state-changing", navigation["deployment"].lower())
        self.assertIn("read-only", navigation["monitoring"].lower())
        self.assertIn("on-demand", navigation["monitoring"].lower())

    def test_shell_action_catalog_marks_state_changing_and_read_only_flows(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()

        maintenance = shell.maintenance_actions()
        deploy_bootstrap = shell.deploy_bootstrap_actions()
        monitoring = shell.monitoring_actions()

        self.assertTrue(maintenance)
        self.assertTrue(deploy_bootstrap)
        self.assertTrue(monitoring)
        self.assertTrue(all(action.panel == "maintenance" for action in maintenance))
        self.assertTrue(all(action.panel == "deployment" for action in deploy_bootstrap))
        self.assertTrue(all(action.state_change_label == "state-changing" for action in maintenance + deploy_bootstrap))
        self.assertTrue(any(action.side_effect_level == "high" for action in deploy_bootstrap))
        self.assertTrue(all(action.panel == "monitoring" for action in monitoring))
        self.assertTrue(all(action.state_change_label == "read-only" for action in monitoring))
        self.assertTrue(all(action.side_effect_level == "none" for action in monitoring))
        self.assertTrue(all(action.execution_mode == "on-demand" for action in monitoring))

    def test_shell_can_launch_config_flow_and_init_from_operational_panel(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        launched: list[Path] = []

        def launch_config(repo_root: Path) -> object:
            launched.append(repo_root)
            return None

        shell = ControlPanelShell(config_launcher=launch_config)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            shell.launch_config(repo_root=root)
            status_lines = shell.run_init(
                runner=RunnerStub(),
                repo_root=root,
                provider_override="hetzner",
            )

        self.assertEqual(launched, [root])
        self.assertTrue(any("tofu_init" in line and "succeeded" in line for line in status_lines))

    def test_shell_and_headless_share_same_init_graph_definition_identity(self) -> None:
        from hermes_vps_app import operational
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        self.assertIs(shell.init_graph_builder, operational.build_init_graph)

    def test_shell_and_headless_share_same_deploy_graph_definition_identity(self) -> None:
        from hermes_vps_app import operational
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        self.assertIs(shell.deploy_graph_builder, operational.build_deploy_graph)

    def test_shell_exposes_deploy_flow_structured_status(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "id_rsa").write_text("PRIVATE", encoding="utf-8")
            os.chmod(root / "id_rsa", stat.S_IRUSR | stat.S_IWUSR)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "TF_VAR_cloud_provider=hetzner",
                        f"BOOTSTRAP_SSH_PRIVATE_KEY_PATH={root / 'id_rsa'}",
                        "BOOTSTRAP_SSH_PORT=22",
                        "TF_VAR_hermes_provider=openrouter",
                        "HERMES_API_KEY=test-key",
                        "HERMES_AGENT_VERSION=1.2.3",
                        "TELEGRAM_BOT_TOKEN=test-token",
                        "TELEGRAM_ALLOWLIST_IDS=12345",
                        "TF_VAR_allowed_tcp_ports=[443,8443]",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)
            (root / "opentofu/providers/hetzner/tofuplan").write_text("saved", encoding="utf-8")
            (root / "bootstrap").mkdir(parents=True)
            (root / "templates").mkdir(parents=True)

            payload = shell.run_deploy(
                runner=RunnerStub(),
                repo_root=root,
                provider_override="hetzner",
            )

        self.assertEqual(payload["workflow"], "deploy")
        self.assertEqual(payload["graph"], {"id": "deploy"})
        self.assertTrue(payload["completed"])
        self.assertIn("redactions", payload)
        self.assertIn("actions", payload)
        actions = cast(list[dict[str, object]], payload["actions"])
        self.assertTrue(any(action["action_id"] == "bootstrap_execute_remote" for action in actions))
        bootstrap_action = next(action for action in actions if action["action_id"] == "bootstrap_execute_remote")
        self.assertIn("bootstrap", str(bootstrap_action["label"]).lower())
        self.assertEqual(bootstrap_action["status"], "succeeded")

    def test_deployment_panel_primary_preview_and_advanced_catalog_exclude_destroy(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()

        preview = shell.preview_deployment(provider="hetzner", runner=RunnerStub())
        action_ids = [action["action_id"] for action in cast(list[dict[str, object]], preview["actions"])]
        advanced = shell.deployment_advanced_actions()

        self.assertEqual(preview["workflow"], "deploy")
        self.assertEqual(
            action_ids,
            [
                "tofu_init",
                "tofu_plan",
                "tofu_apply",
                "bootstrap_resolve_target",
                "bootstrap_execute_remote",
                "verify_resolve_target",
                "verify_execute_remote",
            ],
        )
        self.assertNotIn("tofu_destroy", action_ids)
        self.assertNotIn("destroy", {action.workflow for action in advanced})
        self.assertEqual({action.workflow for action in advanced}, {"init", "plan", "apply", "bootstrap", "verify"})
        self.assertTrue(all(action.panel == "deployment" for action in advanced))

    def test_deployment_panel_runs_advanced_action_through_operational_service_boundary(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell
        from hermes_vps_app import operational

        calls: list[str] = []
        original = operational.run_operational_graph

        def fake_run_operational_graph(
            *,
            action: str,
            runner: Runner,
            repo_root: Path,
            provider_override: str | None,
            host_override_token: str | None = None,
            override_reason: str | None = None,
            approve_destructive: str | None = None,
            confirmation_mode: str = "headless",
            audit_log: SessionAuditLog | None = None,
        ) -> object:
            calls.append(action)
            return original(
                action=action,
                runner=runner,
                repo_root=repo_root,
                provider_override=provider_override,
                host_override_token=host_override_token,
                override_reason=override_reason,
                approve_destructive=approve_destructive,
                confirmation_mode=confirmation_mode,
                audit_log=audit_log,
            )

        shell = ControlPanelShell()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            operational.run_operational_graph = fake_run_operational_graph  # type: ignore[method-assign]
            try:
                payload = shell.run_deployment_action(
                    action="plan",
                    runner=RunnerStub(),
                    repo_root=root,
                    provider_override="hetzner",
                )
            finally:
                operational.run_operational_graph = original  # type: ignore[method-assign]

        self.assertEqual(calls, ["plan"])
        self.assertEqual(payload["workflow"], "plan")
        actions = cast(list[dict[str, object]], payload["actions"])
        self.assertEqual([action["action_id"] for action in actions], ["tofu_plan"])
        result = cast(dict[str, object], actions[0]["result"])
        self.assertEqual(cast(list[str], result["command"])[0], "tofu")
        self.assertNotIn("just", str(payload).lower())

    def test_deployment_progress_includes_elapsed_details_and_failure_pin(self) -> None:
        from hermes_control_core import CommandFailed
        from hermes_vps_app.panel_shell import ControlPanelShell

        @dataclass
        class FailingRunner(Runner):
            mode: RunnerMode = "direnv_nix"

            def run(self, request: RunRequest) -> RunResult:
                result = RunResult(
                    exit_code=2,
                    stdout="planning token=super-secret-value\n",
                    stderr="first\n" + ("x" * 5000) + "\nfinal HERMES_API_KEY=super-secret-value\n",
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                    runner_mode=self.mode,
                    redactions_applied=True,
                )
                raise CommandFailed("plan failed", result)

        shell = ControlPanelShell()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            payload = shell.run_deployment_action(
                action="plan",
                runner=FailingRunner(),
                repo_root=root,
                provider_override="hetzner",
            )

        self.assertFalse(payload["completed"])
        self.assertEqual(payload["failed_node"], "tofu_plan")
        repair = cast(dict[str, object], payload["repair"])
        self.assertEqual(repair["failed_node"], "tofu_plan")
        self.assertEqual(repair["rerun_scope"], "failed node")
        progress = cast(dict[str, object], payload["progress"])
        self.assertEqual(progress["total"], 1)
        self.assertEqual(progress["failed"], 1)
        self.assertIn("elapsed_seconds", progress)
        actions = cast(list[dict[str, object]], payload["actions"])
        node = actions[0]
        self.assertTrue(node["pinned"])
        self.assertIn("elapsed_seconds", node)
        details = cast(dict[str, object], node["details"])
        self.assertEqual(cast(list[str], details["source_command"])[0], "tofu")
        self.assertIn("stdout_tail", details)
        self.assertIn("stderr_tail", details)
        self.assertIn("final", str(details["stderr_tail"]))
        self.assertNotIn("super-secret-value", str(payload))
        self.assertIn("***", str(payload))
        self.assertIn("remediation_hints", details)


if __name__ == "__main__":
    unittest.main()
