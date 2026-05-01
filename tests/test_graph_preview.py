# pyright: reportUnusedCallResult=false, reportImplicitOverride=false
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from hermes_control_core import RunRequest, RunResult, Runner
from hermes_control_core.interfaces import RunnerMode


@dataclass
class PreviewRunner(Runner):
    mode: RunnerMode = "direnv_nix"
    seen: list[RunRequest] = field(default_factory=list)

    def run(self, request: RunRequest) -> RunResult:
        self.seen.append(request)
        raise AssertionError("preview must not execute runner commands")


class GraphPreviewTests(unittest.TestCase):
    def test_headless_apply_preview_is_generated_from_graph_without_runner_side_effects(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            runner = PreviewRunner()
            stdout = io.StringIO()
            with (
                patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner),
                contextlib.redirect_stdout(stdout),
            ):
                rc = main(["apply", "--repo-root", str(root), "--provider", "hetzner", "--preview", "--output", "json"])

        self.assertEqual(rc, 0)
        self.assertEqual(runner.seen, [])
        payload = cast(dict[str, Any], json.loads(stdout.getvalue()))
        self.assertEqual(payload["workflow"], "apply")
        self.assertEqual(payload["graph"]["id"], "apply")
        self.assertEqual(payload["provider"], "hetzner")
        self.assertEqual(payload["runner_mode"], "direnv_nix")
        self.assertEqual(
            payload["actions"],
            [
                {
                    "action_id": "tofu_apply",
                    "label": "tofu apply",
                    "order": 1,
                    "side_effect_level": "high",
                    "deps": [],
                    "approval_required": False,
                    "repair_scope": "failed node",
                }
            ],
        )

    def test_headless_deploy_preview_covers_compound_graph_without_bootstrap_side_effects(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            runner = PreviewRunner()
            stdout = io.StringIO()
            with (
                patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner),
                contextlib.redirect_stdout(stdout),
            ):
                rc = main(["deploy", "--repo-root", str(root), "--provider", "hetzner", "--preview", "--output", "json"])

        self.assertEqual(rc, 0)
        self.assertEqual(runner.seen, [])
        payload = cast(dict[str, Any], json.loads(stdout.getvalue()))
        actions = cast(list[dict[str, object]], payload["actions"])
        self.assertEqual([action["action_id"] for action in actions], [
            "tofu_init",
            "tofu_plan",
            "tofu_apply",
            "bootstrap_resolve_target",
            "bootstrap_execute_remote",
            "verify_resolve_target",
            "verify_execute_remote",
        ])
        self.assertEqual(actions[1]["deps"], ["tofu_init"])
        self.assertEqual(actions[4]["side_effect_level"], "high")

    def test_panel_deploy_preview_uses_same_compound_graph_order_without_running_runner(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        runner = PreviewRunner(mode="docker_nix")
        shell = ControlPanelShell()

        preview = shell.preview_deploy(provider="linode", runner=runner)

        self.assertEqual(runner.seen, [])
        self.assertEqual(preview["workflow"], "deploy")
        self.assertEqual(preview["graph"], {"id": "deploy"})
        self.assertEqual(preview["provider"], "linode")
        self.assertEqual(preview["runner_mode"], "docker_nix")
        preview_actions = cast(list[dict[str, object]], preview["actions"])
        action_ids = [action["action_id"] for action in preview_actions]
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
        repair_scopes = {action["action_id"]: action["repair_scope"] for action in preview_actions}
        self.assertEqual(repair_scopes["verify_execute_remote"], "failed subtree")

    def test_panel_state_changing_previews_use_shared_graph_renderer_without_running_runner(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        runner = PreviewRunner(mode="docker_nix")
        shell = ControlPanelShell()

        init_preview = shell.preview_init(provider="hetzner", runner=runner)
        deploy_preview = shell.preview_deploy(provider="hetzner", runner=runner)

        self.assertEqual(runner.seen, [])
        self.assertEqual(init_preview["workflow"], "init")
        self.assertEqual(init_preview["graph"], {"id": "init"})
        self.assertIn("redactions", init_preview)
        init_actions = cast(list[dict[str, object]], init_preview["actions"])
        self.assertTrue(all("side_effect_level" in action for action in init_actions))
        self.assertEqual(deploy_preview["workflow"], "deploy")
        self.assertEqual(deploy_preview["graph"], {"id": "deploy"})
        self.assertIn("redactions", deploy_preview)

    def test_apply_failure_renders_canonical_failed_node_repair_scope(self) -> None:
        from hermes_vps_app.cli import main

        class FailingRunner(PreviewRunner):
            def run(self, request: RunRequest) -> RunResult:
                self.seen.append(request)
                return RunResult(
                    exit_code=1,
                    stdout="",
                    stderr="permission denied",
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                    runner_mode=self.mode,
                    redactions_applied=True,
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            tf_dir = root / "opentofu/providers/hetzner"
            tf_dir.mkdir(parents=True)
            (tf_dir / "tofuplan").write_text("saved", encoding="utf-8")

            runner = FailingRunner()
            stderr = io.StringIO()
            with (
                patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner),
                contextlib.redirect_stderr(stderr),
            ):
                rc = main(["apply", "--repo-root", str(root), "--provider", "hetzner"])

        self.assertEqual(rc, 40)
        self.assertIn("repair_scope=failed node", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
