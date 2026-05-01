# pyright: reportUnusedCallResult=false, reportImplicitOverride=false, reportAny=false
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hermes_control_core import RunRequest, RunResult, Runner
from hermes_control_core.interfaces import RunnerMode


@dataclass
class FailingRunner(Runner):
    mode: RunnerMode = "direnv_nix"

    def run(self, request: RunRequest) -> RunResult:
        return RunResult(
            exit_code=1,
            stdout="",
            stderr="provider token=secret-value failed",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            runner_mode=self.mode,
            redactions_applied=True,
        )


class CliErrorTaxonomyTests(unittest.TestCase):
    def test_json_preflight_error_is_classified_with_exit_code_and_repair_scope(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)
            secret = "super-secret-token-123"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = main(
                    [
                        "plan",
                        "--repo-root",
                        str(root),
                        "--provider",
                        "hetzner",
                        "--output",
                        "json",
                        "--host-override-token",
                        secret,
                    ]
                )

            self.assertEqual(rc, 20)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["error"]["category"], "preflight_failure")
            self.assertEqual(payload["error"]["exit_code"], 20)
            self.assertEqual(payload["error"]["workflow"], "plan")
            self.assertEqual(payload["error"]["repair_scope"], "fix local preflight inputs and rerun plan")
            self.assertTrue(payload["redactions"]["applied"])
            self.assertNotIn(secret, stdout.getvalue())

    def test_json_usage_config_error_for_invalid_provider_uses_taxonomy(self) -> None:
        from hermes_vps_app.cli import main

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = main(["plan", "--provider", "aws", "--output", "json"])

        self.assertEqual(rc, 10)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"]["category"], "usage_config_error")
        self.assertEqual(payload["error"]["exit_code"], 10)

    def test_json_command_failure_includes_graph_action_context_and_redacts_detail(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            (root / ".env").chmod(0o600)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)
            stdout = io.StringIO()
            stderr = io.StringIO()

            from unittest.mock import patch

            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=FailingRunner()), contextlib.redirect_stdout(
                stdout
            ), contextlib.redirect_stderr(stderr):
                rc = main(["plan", "--repo-root", str(root), "--provider", "hetzner", "--output", "json"])

            self.assertEqual(rc, 40)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["error"]["category"], "command_failure")
            self.assertEqual(payload["error"]["graph"], {"id": "plan"})
            self.assertEqual(payload["error"]["action"], {"id": "tofu_plan", "status": "failed"})
            self.assertEqual(payload["error"]["repair_scope"], "failed node")
            self.assertNotIn("secret-value", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
