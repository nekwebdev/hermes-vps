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
    def test_shell_navigation_separates_config_and_operational_with_state_change_label(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        navigation = shell.navigation()

        self.assertIn("config", navigation)
        self.assertIn("operational", navigation)
        self.assertIn("read-only", navigation["config"].lower())
        self.assertIn("state-changing", navigation["operational"].lower())

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
        self.assertTrue(payload["completed"])
        self.assertIn("actions", payload)
        actions = cast(list[dict[str, str]], payload["actions"])
        self.assertTrue(any(action["action_id"] == "bootstrap_execute_remote" for action in actions))


if __name__ == "__main__":
    unittest.main()
