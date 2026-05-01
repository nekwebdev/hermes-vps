# pyright: reportUnusedCallResult=false, reportImplicitOverride=false
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

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


class StatusPresentationV2Tests(unittest.TestCase):
    def test_init_cli_json_and_panel_status_share_presentation_contract(self) -> None:
        from hermes_vps_app.cli import main
        from hermes_vps_app.panel_shell import ControlPanelShell

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            stdout = io.StringIO()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=RunnerStub()), contextlib.redirect_stdout(stdout):
                rc = main(["init", "--repo-root", str(root), "--provider", "hetzner", "--output", "json"])

            shell_payload = ControlPanelShell().run_init_status(
                runner=RunnerStub(),
                repo_root=root,
                provider_override="hetzner",
            )

        cli_payload = cast(dict[str, Any], json.loads(stdout.getvalue()))
        self.assertEqual(rc, 0)
        self.assertEqual(cli_payload["graph"]["id"], "init")
        self.assertEqual(cli_payload["workflow"], "init")
        self.assertEqual(cli_payload["runner_mode"], "direnv_nix")
        self.assertEqual(cli_payload["redactions"], {"applied": True, "marker": "***"})
        self.assertEqual(cli_payload["actions"][0]["action_id"], "tofu_init")
        self.assertEqual(cli_payload["actions"][0]["status"], "succeeded")
        self.assertEqual(cli_payload, shell_payload)

    def test_monitoring_cli_json_and_panel_status_share_presentation_contract(self) -> None:
        from hermes_vps_app.cli import main
        from hermes_vps_app.panel_shell import ControlPanelShell

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / ".env.example").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["monitoring", "--repo-root", str(root), "--provider", "hetzner", "--output", "json"])

            shell_payload = ControlPanelShell().run_monitoring_status(
                repo_root=root,
                provider_override="hetzner",
            )

        cli_payload = cast(dict[str, Any], json.loads(stdout.getvalue()))
        self.assertEqual(rc, 0)
        self.assertEqual(cli_payload["graph"]["id"], "monitoring-local-readiness")
        self.assertEqual(cli_payload["workflow"], "monitoring")
        self.assertEqual(cli_payload["runner_mode"], "local")
        self.assertEqual(cli_payload["redactions"], {"applied": True, "marker": "***"})
        actions = cast(list[dict[str, object]], cli_payload["actions"])
        action_ids = {str(action["action_id"]) for action in actions}
        self.assertIn("runner_toolchain_readiness", action_ids)
        self.assertIn("provider_resolution", action_ids)
        self.assertEqual(cli_payload, shell_payload)

    def test_cli_human_output_renders_status_lines_from_same_contract(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            stdout = io.StringIO()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=RunnerStub()), contextlib.redirect_stdout(stdout):
                rc = main(["init", "--repo-root", str(root), "--provider", "hetzner"])

        self.assertEqual(rc, 0)
        rendered = stdout.getvalue()
        self.assertIn("init: graph=init completed=true runner=direnv_nix", rendered)
        self.assertIn("tofu_init: succeeded runner=direnv_nix", rendered)
        self.assertIn("redaction_marker=***", rendered)


if __name__ == "__main__":
    unittest.main()
