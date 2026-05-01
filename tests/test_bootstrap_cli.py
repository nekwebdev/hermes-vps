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
class BootstrapRunner(Runner):
    mode: RunnerMode = "direnv_nix"
    seen: list[RunRequest] = field(default_factory=list)
    fail_on: str | None = None

    def run(self, request: RunRequest) -> RunResult:
        self.seen.append(request)
        command = request.command
        assert isinstance(command, list)

        if command[:3] == ["tofu", command[1], "output"] and command[-1] == "public_ipv4":
            return RunResult(
                exit_code=0,
                stdout="203.0.113.10\n",
                stderr="",
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

        if self.fail_on is not None and command and command[0] == self.fail_on:
            return RunResult(
                exit_code=1,
                stdout="",
                stderr="super-secret-hermes-key",
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


class BootstrapCliTests(unittest.TestCase):
    def _write_valid_bootstrap_fixture(self, root: Path, *, key_mode: int = stat.S_IRUSR | stat.S_IWUSR) -> Path:
        key_path = root / "id_rsa"
        key_path.write_text("PRIVATE", encoding="utf-8")
        os.chmod(key_path, key_mode)

        env_text = "\n".join(
            [
                "TF_VAR_cloud_provider=hetzner",
                "BOOTSTRAP_SSH_PRIVATE_KEY_PATH=" + str(key_path),
                "BOOTSTRAP_SSH_PORT=22",
                "TF_VAR_hermes_provider=openrouter",
                "HERMES_API_KEY=super-secret-hermes-key",
                "HERMES_AGENT_VERSION=1.2.3",
                "TELEGRAM_BOT_TOKEN=super-secret-telegram-token",
                "TELEGRAM_ALLOWLIST_IDS=12345,-100999",
                "TF_VAR_allowed_tcp_ports=[443,8443]",
                "",
            ]
        )
        (root / ".env").write_text(env_text, encoding="utf-8")
        os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
        (root / "opentofu/providers/hetzner").mkdir(parents=True)
        (root / "bootstrap").mkdir(parents=True)
        (root / "templates").mkdir(parents=True)
        return key_path

    def test_headless_bootstrap_entrypoint_runs_remote_sequence(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ = self._write_valid_bootstrap_fixture(root)

            runner = BootstrapRunner()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner):
                rc = main(["bootstrap", "--repo-root", str(root), "--provider", "hetzner"])

            self.assertEqual(rc, 0)
            commands = [req.command for req in runner.seen]
            self.assertEqual(commands[0], ["tofu", "-chdir=opentofu/providers/hetzner", "output", "-raw", "public_ipv4"])
            self.assertEqual(commands[1], ["tofu", "-chdir=opentofu/providers/hetzner", "output", "-raw", "admin_username"])
            self.assertEqual(commands[2][0], "ssh")
            self.assertEqual(commands[3][0], "rsync")
            self.assertEqual(commands[4][0], "ssh")

    def test_bootstrap_preflight_fails_on_insecure_key_permissions_before_runner_calls(self) -> None:
        from hermes_vps_app.operational import run_operational_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ = self._write_valid_bootstrap_fixture(root, key_mode=0o644)

            runner = BootstrapRunner()
            with self.assertRaisesRegex(ValueError, "permissions are too broad"):
                run_operational_graph(
                    action="bootstrap",
                    runner=runner,
                    repo_root=root,
                    provider_override="hetzner",
                )
            self.assertEqual(runner.seen, [])

    def test_bootstrap_runtime_cleanup_and_secret_safe_error_on_remote_failure(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ = self._write_valid_bootstrap_fixture(root)

            runner = BootstrapRunner(fail_on="rsync")
            stderr = io.StringIO()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner), contextlib.redirect_stderr(stderr):
                rc = main(["bootstrap", "--repo-root", str(root), "--provider", "hetzner"])

            message = stderr.getvalue()
            self.assertEqual(rc, 40)
            self.assertIn("category=command_failure", message)
            self.assertIn("action=bootstrap_execute_remote", message)
            self.assertNotIn("super-secret-hermes-key", message)
            self.assertNotIn("super-secret-telegram-token", message)
            self.assertFalse((root / "bootstrap" / "runtime").exists())


if __name__ == "__main__":
    unittest.main()
