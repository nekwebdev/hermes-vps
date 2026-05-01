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

from hermes_control_core import RunRequest, RunResult, Runner
from hermes_control_core.interfaces import RunnerMode


@dataclass
class VerifyRunner(Runner):
    mode: RunnerMode = "direnv_nix"
    seen: list[RunRequest] = field(default_factory=list)
    fail_public_ip: bool = False
    fail_verify_ssh: bool = False

    def run(self, request: RunRequest) -> RunResult:
        self.seen.append(request)
        command = request.command
        assert isinstance(command, list)

        if command[:3] == ["tofu", command[1], "output"] and command[-1] == "public_ipv4":
            return RunResult(
                exit_code=1 if self.fail_public_ip else 0,
                stdout="" if self.fail_public_ip else "203.0.113.10\n",
                stderr="tofu output failed" if self.fail_public_ip else "",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                runner_mode=self.mode,
                redactions_applied=True,
            )

        if command[:3] == ["tofu", command[1], "output"] and command[-1] == "admin_username":
            return RunResult(
                exit_code=0,
                stdout="root\n",
                stderr="",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                runner_mode=self.mode,
                redactions_applied=True,
            )

        if command and command[0] == "ssh" and self.fail_verify_ssh:
            return RunResult(
                exit_code=1,
                stdout="",
                stderr="verify script failed",
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


class VerifyCliTests(unittest.TestCase):
    def _write_fixture(self, root: Path, *, key_mode: int = stat.S_IRUSR | stat.S_IWUSR) -> Path:
        key_path = root / "id_rsa"
        key_path.write_text("PRIVATE", encoding="utf-8")
        os.chmod(key_path, key_mode)
        (root / ".env").write_text(
            "\n".join(
                [
                    "TF_VAR_cloud_provider=hetzner",
                    f"BOOTSTRAP_SSH_PRIVATE_KEY_PATH={key_path}",
                    "BOOTSTRAP_SSH_PORT=22",
                    "TF_VAR_hermes_provider=openrouter",
                    "HERMES_API_KEY=token-value",
                    "HERMES_AGENT_VERSION=1.2.3",
                    "TELEGRAM_BOT_TOKEN=telegram-value",
                    "TELEGRAM_ALLOWLIST_IDS=12345",
                    "TF_VAR_allowed_tcp_ports=[443,8443]",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
        (root / "opentofu/providers/hetzner").mkdir(parents=True)
        return key_path

    def test_headless_verify_entrypoint_runs_remote_verification(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key_path = self._write_fixture(root)
            runner = VerifyRunner()

            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner):
                rc = main(["verify", "--repo-root", str(root), "--provider", "hetzner"])

            self.assertEqual(rc, 0)
            commands = [req.command for req in runner.seen]
            self.assertEqual(commands[0], ["tofu", "-chdir=opentofu/providers/hetzner", "output", "-raw", "public_ipv4"])
            self.assertEqual(commands[1], ["tofu", "-chdir=opentofu/providers/hetzner", "output", "-raw", "admin_username"])
            self.assertEqual(
                commands[2],
                [
                    "ssh",
                    "-i",
                    str(key_path),
                    "-p",
                    "22",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "root@203.0.113.10",
                    "sudo bash /root/hermes-vps-stage/bootstrap/90-verify.sh",
                ],
            )
            self.assertFalse(runner.seen[2].shell)

    def test_verify_preflight_fails_on_insecure_key_permissions_before_runner_calls(self) -> None:
        from hermes_vps_app.operational import run_operational_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ = self._write_fixture(root, key_mode=0o644)
            runner = VerifyRunner()

            with self.assertRaisesRegex(ValueError, "permissions are too broad"):
                run_operational_graph(
                    action="verify",
                    runner=runner,
                    repo_root=root,
                    provider_override="hetzner",
                )
            self.assertEqual(runner.seen, [])

    def test_verify_fail_fast_skips_remote_ssh_when_target_resolution_fails(self) -> None:
        from hermes_vps_app.operational import run_operational_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ = self._write_fixture(root)
            runner = VerifyRunner(fail_public_ip=True)

            result = run_operational_graph(
                action="verify",
                runner=runner,
                repo_root=root,
                provider_override="hetzner",
            )

            self.assertTrue(result.failed)
            self.assertFalse(result.completed)
            commands = [req.command for req in runner.seen]
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][-1], "public_ipv4")

    def test_verify_failure_surfaces_structured_status_and_repair_scope(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ = self._write_fixture(root)
            runner = VerifyRunner(fail_verify_ssh=True)

            stderr = io.StringIO()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner), contextlib.redirect_stderr(stderr):
                rc = main(["verify", "--repo-root", str(root), "--provider", "hetzner"])

            message = stderr.getvalue()
            self.assertEqual(rc, 40)
            self.assertIn("category=command_failure", message)
            self.assertIn("action=verify_execute_remote", message)
            self.assertIn("repair_scope=failed subtree", message)

    def test_just_verify_recipe_delegates_to_python_entrypoint(self) -> None:
        justfile = Path(__file__).resolve().parents[1] / "Justfile"
        content = justfile.read_text(encoding="utf-8")
        self.assertIn("python3 -m hermes_vps_app.just_shim verify --repo-root . --provider", content)
        self.assertIn("hermes_vps_app.cli", content)


if __name__ == "__main__":
    unittest.main()
