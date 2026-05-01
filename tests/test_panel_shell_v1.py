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

from hermes_control_core import RunRequest, RunResult, Runner
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
            {"config", "maintenance", "monitoring", "deploy/bootstrap"},
        )
        self.assertIn("configuration", navigation["config"].lower())
        self.assertIn("maintenance", navigation["maintenance"].lower())
        self.assertIn("monitoring", navigation["monitoring"].lower())
        self.assertIn("deploy/bootstrap", navigation["deploy/bootstrap"].lower())
        self.assertIn("state-changing", navigation["maintenance"].lower())
        self.assertIn("state-changing", navigation["deploy/bootstrap"].lower())
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
        self.assertTrue(all(action.panel == "deploy/bootstrap" for action in deploy_bootstrap))
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


if __name__ == "__main__":
    unittest.main()
