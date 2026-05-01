# pyright: reportUnusedCallResult=false, reportImplicitOverride=false, reportAny=false
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from hermes_control_core import RunRequest, RunResult, Runner, SessionAuditLog
from hermes_control_core.interfaces import RunnerMode
from hermes_vps_app import operational
from hermes_vps_app.cli import build_parser, main
from hermes_vps_app.panel_shell import ControlPanelShell


@dataclass
class RegressionRunner(Runner):
    mode: RunnerMode = "direnv_nix"
    seen: list[RunRequest] = field(default_factory=list)
    fail_prefix: list[str] | None = None

    def run(self, request: RunRequest) -> RunResult:
        self.seen.append(request)
        cmd = request.command
        assert isinstance(cmd, list)
        if self.fail_prefix is not None and cmd[: len(self.fail_prefix)] == self.fail_prefix:
            return RunResult(
                exit_code=1,
                stdout="",
                stderr="failed",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                runner_mode=self.mode,
                redactions_applied=True,
            )
        if len(cmd) >= 4 and cmd[0] == "tofu" and cmd[2] == "output":
            outputs = {
                "public_ipv4": "203.0.113.10\n",
                "admin_username": "root\n",
                "server_id": "srv-123\n",
            }
            key = cmd[-1]
            if key in outputs:
                return RunResult(
                    exit_code=0,
                    stdout=outputs[key],
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


class Issue11RegressionGateTests(unittest.TestCase):
    def _fixture(self, root: Path, *, include_bootstrap: bool = True) -> None:
        (root / ".env").write_text(
            "\n".join(
                [
                    "TF_VAR_cloud_provider=hetzner",
                    f"BOOTSTRAP_SSH_PRIVATE_KEY_PATH={root / 'id_rsa'}",
                    "BOOTSTRAP_SSH_PORT=22",
                    "TF_VAR_hermes_provider=openrouter",
                    "HERMES_API_KEY=secret-hermes-api-key",
                    "HERMES_AGENT_VERSION=1.2.3",
                    "TELEGRAM_BOT_TOKEN=secret-telegram-token",
                    "TELEGRAM_ALLOWLIST_IDS=12345",
                    "TF_VAR_allowed_tcp_ports=[443,8443]",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
        (root / "id_rsa").write_text("PRIVATE", encoding="utf-8")
        os.chmod(root / "id_rsa", stat.S_IRUSR | stat.S_IWUSR)
        tf_dir = root / "opentofu/providers/hetzner"
        tf_dir.mkdir(parents=True)
        (tf_dir / "tofuplan").write_text("saved", encoding="utf-8")
        if include_bootstrap:
            (root / "bootstrap").mkdir(parents=True)
            (root / "templates").mkdir(parents=True)

    def test_issue11_suite_is_documented_as_cutover_precondition(self) -> None:
        doc = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("precondition for docs cutover and Justfile removal", doc)

    def test_cross_surface_graph_identity_for_migrated_workflows(self) -> None:
        shell = ControlPanelShell()
        parser = build_parser()

        migrated = {"init", "init-upgrade", "plan", "apply", "destroy", "bootstrap", "verify", "up", "deploy"}
        for action in migrated:
            parsed = parser.parse_args([action])
            self.assertEqual(parsed.action, action)
        self.assertIs(shell.init_graph_builder, operational.build_init_graph)
        self.assertIs(shell.deploy_graph_builder, operational.build_deploy_graph)
        self.assertIs(shell.monitoring_graph_builder, operational.build_monitoring_graph)

        self.assertEqual(tuple(operational.build_graph("init").actions), ("tofu_init",))
        self.assertEqual(
            tuple(operational.build_graph("up").actions),
            ("tofu_init", "tofu_plan", "tofu_apply"),
        )
        self.assertEqual(
            tuple(operational.build_graph("deploy").actions),
            (
                "tofu_init",
                "tofu_plan",
                "tofu_apply",
                "bootstrap_resolve_target",
                "bootstrap_execute_remote",
                "verify_resolve_target",
                "verify_execute_remote",
            ),
        )

    def test_fail_fast_for_individual_and_compound_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root)
            init_fail = RegressionRunner(fail_prefix=["tofu", "-chdir=opentofu/providers/hetzner", "init"])
            up_result = operational.run_operational_graph(
                action="up",
                runner=init_fail,
                repo_root=root,
                provider_override="hetzner",
            )
            self.assertTrue(up_result.failed)
            self.assertEqual(len(init_fail.seen), 1)

            verify_fail = RegressionRunner(
                fail_prefix=[
                    "ssh",
                    "-i",
                    str(root / "id_rsa"),
                    "-p",
                    "22",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "root@203.0.113.10",
                    "sudo bash /root/hermes-vps-stage/bootstrap/90-verify.sh",
                ]
            )
            deploy_result = operational.run_operational_graph(
                action="deploy",
                runner=verify_fail,
                repo_root=root,
                provider_override="hetzner",
            )
            self.assertTrue(deploy_result.failed)
            self.assertFalse(deploy_result.completed)

    def test_destroy_gate_audit_and_secret_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root, include_bootstrap=False)
            tf_dir = root / "opentofu/providers/hetzner"
            (tf_dir / "terraform.tfstate").write_text("{}", encoding="utf-8")
            audit = SessionAuditLog(session_id="issue11-destroy", repo_root=root)
            runner = RegressionRunner()

            with self.assertRaises(PermissionError) as denied:
                operational.run_operational_graph(
                    action="destroy",
                    runner=runner,
                    repo_root=root,
                    provider_override="hetzner",
                    approve_destructive="DESTROY:wrong",
                    audit_log=audit,
                )
            self.assertNotIn("DESTROY:wrong", str(denied.exception))
            self.assertNotIn("secret-hermes-api-key", str(denied.exception))
            self.assertEqual(audit.destructive_approvals[-1].token_used, None)

            ok = operational.run_operational_graph(
                action="destroy",
                runner=runner,
                repo_root=root,
                provider_override="hetzner",
                approve_destructive="DESTROY:hetzner",
                audit_log=audit,
            )
            self.assertTrue(ok.completed)
            latest = audit.destructive_approvals[-1]
            self.assertTrue(latest.approved)
            self.assertEqual(latest.token_used, "DESTROY:hetzner")
            self.assertIn("backup_status", latest.details)
            self.assertIn("target_summary", latest.details)
            serialized = repr(latest.details)
            self.assertNotIn("secret-hermes-api-key", serialized)
            self.assertNotIn("secret-telegram-token", serialized)

    def test_host_override_gate_requires_enablement_reason_and_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root)
            host_runner = RegressionRunner(mode="host")

            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=host_runner):
                with self.assertRaises(PermissionError) as denied:
                    main(
                        [
                            "init",
                            "--repo-root",
                            str(root),
                            "--provider",
                            "hetzner",
                            "--host-override-token",
                            "BAD-HOST-TOKEN",
                        ]
                    )
            self.assertNotIn("BAD-HOST-TOKEN", str(denied.exception))

        with self.assertRaisesRegex(Exception, "non-empty override_reason"):
            from hermes_control_core import RunnerFactory

            RunnerFactory(repo_root=Path("."), allow_host_override=True, override_reason="")

    def test_just_shim_parity_for_migrated_recipes_provider_override_and_exit_contract(self) -> None:
        justfile = (Path(__file__).resolve().parents[1] / "Justfile").read_text(encoding="utf-8")
        for recipe in ("init", "init-upgrade", "plan", "apply", "bootstrap", "verify", "up", "deploy"):
            self.assertIn(f"{recipe} PROVIDER_ARG=\"\"", justfile)
            self.assertIn(f"python3 -m hermes_vps_app.cli {recipe}", justfile)
        self.assertIn('destroy CONFIRM="NO" PROVIDER_ARG=""', justfile)
        self.assertIn("python3 -m hermes_vps_app.cli destroy", justfile)
        self.assertIn("invalid provider override", justfile)
        self.assertIn("exit 1", justfile)


if __name__ == "__main__":
    unittest.main()

# This regression suite is the precondition for docs cutover and Justfile removal.
