# pyright: reportUnusedCallResult=false, reportImplicitOverride=false
from __future__ import annotations

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
class CompoundRunner(Runner):
    mode: RunnerMode = "direnv_nix"
    seen: list[RunRequest] = field(default_factory=list)
    fail_prefix: list[str] | None = None

    def run(self, request: RunRequest) -> RunResult:
        self.seen.append(request)
        command = request.command
        assert isinstance(command, list)
        if self.fail_prefix is not None and command[: len(self.fail_prefix)] == self.fail_prefix:
            return RunResult(
                exit_code=1,
                stdout="",
                stderr="failed",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                runner_mode=self.mode,
                redactions_applied=True,
            )
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
        return RunResult(
            exit_code=0,
            stdout="ok",
            stderr="",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            runner_mode=self.mode,
            redactions_applied=True,
        )


class CompoundCliTests(unittest.TestCase):
    def _write_bootstrap_fixture(self, root: Path) -> None:
        key_path = root / "id_rsa"
        key_path.write_text("PRIVATE", encoding="utf-8")
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
        (root / ".env").write_text(
            "\n".join(
                [
                    "TF_VAR_cloud_provider=hetzner",
                    f"BOOTSTRAP_SSH_PRIVATE_KEY_PATH={key_path}",
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
        tf_dir = root / "opentofu/providers/hetzner"
        tf_dir.mkdir(parents=True)
        (tf_dir / "tofuplan").write_text("saved", encoding="utf-8")
        (root / "bootstrap").mkdir(parents=True)
        (root / "templates").mkdir(parents=True)

    def test_headless_up_entrypoint_runs_init_plan_apply_sequence(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bootstrap_fixture(root)

            runner = CompoundRunner()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner):
                rc = main(["up", "--repo-root", str(root), "--provider", "hetzner"])

            self.assertEqual(rc, 0)
            self.assertEqual(
                [req.command for req in runner.seen],
                [
                    ["tofu", "-chdir=opentofu/providers/hetzner", "init"],
                    ["tofu", "-chdir=opentofu/providers/hetzner", "plan", "-out=tofuplan"],
                    ["tofu", "-chdir=opentofu/providers/hetzner", "apply", "tofuplan"],
                    ["tofu", "-chdir=opentofu/providers/hetzner", "output", "-raw", "public_ipv4"],
                    ["./scripts/update_ssh_alias.sh", ".ssh/config", "hermes-vps", "203.0.113.10"],
                ],
            )

    def test_headless_deploy_entrypoint_runs_full_sequence(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bootstrap_fixture(root)

            runner = CompoundRunner()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner):
                rc = main(["deploy", "--repo-root", str(root), "--provider", "hetzner"])

            self.assertEqual(rc, 0)
            commands = [req.command for req in runner.seen]
            self.assertEqual(commands[0], ["tofu", "-chdir=opentofu/providers/hetzner", "init"])
            self.assertEqual(commands[1], ["tofu", "-chdir=opentofu/providers/hetzner", "plan", "-out=tofuplan"])
            self.assertEqual(commands[2], ["tofu", "-chdir=opentofu/providers/hetzner", "apply", "tofuplan"])
            self.assertIn(["tofu", "-chdir=opentofu/providers/hetzner", "output", "-raw", "admin_username"], commands)
            self.assertTrue(any(isinstance(c, list) and c and c[0] == "rsync" for c in commands))
            self.assertTrue(
                any(isinstance(c, list) and c and c[0] == "ssh" and "90-verify.sh" in " ".join(c) for c in commands)
            )

    def test_up_fail_fast_skips_plan_and_apply_after_init_failure(self) -> None:
        from hermes_vps_app.operational import run_operational_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bootstrap_fixture(root)
            runner = CompoundRunner(fail_prefix=["tofu", "-chdir=opentofu/providers/hetzner", "init"])

            result = run_operational_graph(action="up", runner=runner, repo_root=root, provider_override="hetzner")

            self.assertTrue(result.failed)
            self.assertFalse(result.completed)
            self.assertEqual([req.command for req in runner.seen], [["tofu", "-chdir=opentofu/providers/hetzner", "init"]])

    def test_compound_graph_reuses_individual_action_ids(self) -> None:
        from hermes_vps_app.operational import build_graph

        up_graph = build_graph("up")
        deploy_graph = build_graph("deploy")
        init_graph = build_graph("init")
        plan_graph = build_graph("plan")
        apply_graph = build_graph("apply")
        bootstrap_graph = build_graph("bootstrap")
        verify_graph = build_graph("verify")

        self.assertIn("tofu_init", up_graph.actions)
        self.assertIn("tofu_plan", up_graph.actions)
        self.assertIn("tofu_apply", up_graph.actions)
        self.assertEqual(up_graph.actions["tofu_init"].action_id, next(iter(init_graph.actions.values())).action_id)
        self.assertEqual(up_graph.actions["tofu_plan"].action_id, next(iter(plan_graph.actions.values())).action_id)
        self.assertEqual(up_graph.actions["tofu_apply"].action_id, next(iter(apply_graph.actions.values())).action_id)
        self.assertEqual(set(deploy_graph.actions).intersection(set(bootstrap_graph.actions)), set(bootstrap_graph.actions))
        self.assertEqual(set(deploy_graph.actions).intersection(set(verify_graph.actions)), set(verify_graph.actions))


if __name__ == "__main__":
    unittest.main()
