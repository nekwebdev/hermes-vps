# pyright: reportUnusedCallResult=false, reportImplicitOverride=false
from __future__ import annotations

import contextlib
import io
import os
import stat
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from hermes_control_core import CommandFailed, RunRequest, RunResult, Runner
from hermes_control_core.interfaces import RunnerMode


@dataclass
class ScriptedRunner(Runner):
    mode: RunnerMode = "direnv_nix"
    seen: list[RunRequest] = field(default_factory=list)
    apply_failures: list[str] = field(default_factory=list)

    def run(self, request: RunRequest) -> RunResult:
        self.seen.append(request)
        cmd = request.command
        assert isinstance(cmd, list)
        if cmd[:3] == ["tofu", cmd[1], "apply"]:
            if self.apply_failures:
                message = self.apply_failures.pop(0)
                raise CommandFailed(message)
        if cmd[:3] == ["tofu", cmd[1], "output"]:
            return RunResult(
                exit_code=0,
                stdout="203.0.113.10\n",
                stderr="",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                runner_mode=self.mode,
                redactions_applied=True,
            )
        return RunResult(
            exit_code=0,
            stdout="ok",
            stderr="",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            runner_mode=self.mode,
            redactions_applied=True,
        )


class ApplyCliTests(unittest.TestCase):
    def test_apply_non_stale_failure_fails_fast_and_skips_alias_reconcile(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            tf_dir = root / "opentofu/providers/hetzner"
            tf_dir.mkdir(parents=True)
            (tf_dir / "tofuplan").write_text("saved", encoding="utf-8")

            runner = ScriptedRunner(apply_failures=["permission denied"])
            stderr = io.StringIO()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner), contextlib.redirect_stderr(stderr):
                rc = main(["apply", "--repo-root", str(root), "--provider", "hetzner"])

            self.assertEqual(rc, 40)
            self.assertIn("category=command_failure", stderr.getvalue())
            self.assertIn("action=tofu_apply", stderr.getvalue())

            commands = [r.command for r in runner.seen]
            self.assertEqual(commands, [["tofu", "-chdir=opentofu/providers/hetzner", "apply", "tofuplan"]])

    def test_apply_missing_plan_generates_then_applies(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            runner = ScriptedRunner()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner):
                rc = main(["apply", "--repo-root", str(root), "--provider", "hetzner"])

            self.assertEqual(rc, 0)
            commands = [r.command for r in runner.seen]
            self.assertEqual(
                commands,
                [
                    ["tofu", "-chdir=opentofu/providers/hetzner", "plan", "-out=tofuplan"],
                    ["tofu", "-chdir=opentofu/providers/hetzner", "apply", "tofuplan"],
                    ["tofu", "-chdir=opentofu/providers/hetzner", "output", "-raw", "public_ipv4"],
                    ["./scripts/update_ssh_alias.sh", ".ssh/config", "hermes-vps", "203.0.113.10"],
                ],
            )

    def test_apply_uses_provider_override_for_validated_provider_path(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/linode").mkdir(parents=True)

            runner = ScriptedRunner()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner):
                rc = main(["apply", "--repo-root", str(root), "--provider", "linode"])

            self.assertEqual(rc, 0)
            self.assertEqual(
                runner.seen[0].command,
                ["tofu", "-chdir=opentofu/providers/linode", "plan", "-out=tofuplan"],
            )

    def test_apply_regenerates_stale_plan_and_retries_before_alias_reconcile(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            tf_dir = root / "opentofu/providers/hetzner"
            tf_dir.mkdir(parents=True)
            (tf_dir / "tofuplan").write_text("saved", encoding="utf-8")

            runner = ScriptedRunner(apply_failures=["Saved plan is stale"])
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner):
                rc = main(["apply", "--repo-root", str(root), "--provider", "hetzner"])

            self.assertEqual(rc, 0)
            commands = [r.command for r in runner.seen]
            self.assertEqual(
                commands,
                [
                    ["tofu", "-chdir=opentofu/providers/hetzner", "apply", "tofuplan"],
                    ["tofu", "-chdir=opentofu/providers/hetzner", "plan", "-out=tofuplan"],
                    ["tofu", "-chdir=opentofu/providers/hetzner", "apply", "tofuplan"],
                    ["tofu", "-chdir=opentofu/providers/hetzner", "output", "-raw", "public_ipv4"],
                    ["./scripts/update_ssh_alias.sh", ".ssh/config", "hermes-vps", "203.0.113.10"],
                ],
            )


if __name__ == "__main__":
    unittest.main()
