# pyright: reportUnusedCallResult=false, reportImplicitOverride=false
from __future__ import annotations

import os
import stat
import tarfile
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from hermes_control_core import RunRequest, RunResult, Runner, SessionAuditLog
from hermes_control_core.interfaces import RunnerMode
from hermes_vps_app.operational import run_operational_graph


@dataclass
class DestroyRunner(Runner):
    mode: RunnerMode = "direnv_nix"
    seen: list[RunRequest] = field(default_factory=list)

    def run(self, request: RunRequest) -> RunResult:
        self.seen.append(request)
        cmd = request.command
        assert isinstance(cmd, list)
        if cmd[:3] == ["tofu", cmd[1], "output"]:
            key = cmd[-1]
            values = {
                "public_ipv4": "203.0.113.10\n",
                "admin_username": "root\n",
                "server_id": "srv-123\n",
            }
            if key in values:
                return RunResult(
                    exit_code=0,
                    stdout=values[key],
                    stderr="",
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                    runner_mode=self.mode,
                    redactions_applied=True,
                )
            return RunResult(
                exit_code=1,
                stdout="",
                stderr="missing output",
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


class DestroyCliTests(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
        os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
        tf_dir = root / "opentofu/providers/hetzner"
        tf_dir.mkdir(parents=True)
        (tf_dir / "terraform.tfstate").write_text("{}", encoding="utf-8")
        (tf_dir / "terraform.tfstate.backup").write_text("{}", encoding="utf-8")

    def test_non_interactive_destroy_without_approval_is_denied_before_backup_and_destroy(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root)

            runner = DestroyRunner()
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner):
                with self.assertRaises(PermissionError):
                    _ = main(["destroy", "--repo-root", str(root), "--provider", "hetzner"])

            commands = [req.command for req in runner.seen]
            self.assertNotIn(["tofu", "-chdir=opentofu/providers/hetzner", "destroy"], commands)
            self.assertFalse((root / ".state-backups").exists())

    def test_headless_destroy_with_approval_runs_backup_and_destroy(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root)
            runner = DestroyRunner()

            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=runner):
                rc = main(
                    [
                        "destroy",
                        "--repo-root",
                        str(root),
                        "--provider",
                        "hetzner",
                        "--approve-destructive",
                        "DESTROY:hetzner",
                    ]
                )

            self.assertEqual(rc, 0)
            backup_dir = root / ".state-backups" / "hetzner"
            archives = list(backup_dir.glob("tfstate-*.tar.gz"))
            self.assertEqual(len(archives), 1)
            mode = stat.S_IMODE(archives[0].stat().st_mode)
            self.assertEqual(mode, 0o600)
            with tarfile.open(archives[0], "r:gz") as tar:
                names = sorted(tar.getnames())
            self.assertEqual(names, ["terraform.tfstate", "terraform.tfstate.backup"])
            self.assertIn(
                ["tofu", "-chdir=opentofu/providers/hetzner", "destroy"],
                [req.command for req in runner.seen],
            )

    def test_approval_audit_has_required_metadata_and_canonical_token_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root)
            runner = DestroyRunner()
            audit = SessionAuditLog(session_id="destroy-audit", repo_root=root)

            _ = run_operational_graph(
                action="destroy",
                runner=runner,
                repo_root=root,
                provider_override="hetzner",
                approve_destructive="DESTROY:hetzner",
                confirmation_mode="headless",
                audit_log=audit,
            )

            self.assertEqual(len(audit.destructive_approvals), 1)
            item = audit.destructive_approvals[0]
            self.assertEqual(item.action_id, "tofu_destroy")
            self.assertTrue(item.approved)
            self.assertEqual(item.token_used, "DESTROY:hetzner")
            self.assertEqual(item.details["provider"], "hetzner")
            self.assertEqual(item.details["confirmation_mode"], "headless")
            self.assertIn("backup_status", item.details)
            self.assertIn("backup_path", item.details)
            self.assertIn("target_summary", item.details)

    def test_bad_approval_token_never_persisted_or_echoed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root)
            runner = DestroyRunner()
            audit = SessionAuditLog(session_id="destroy-audit-bad", repo_root=root)

            with self.assertRaises(PermissionError) as excinfo:
                _ = run_operational_graph(
                    action="destroy",
                    runner=runner,
                    repo_root=root,
                    provider_override="hetzner",
                    approve_destructive="DESTROY:nope",
                    confirmation_mode="headless",
                    audit_log=audit,
                )

            self.assertNotIn("DESTROY:nope", str(excinfo.exception))
            self.assertEqual(audit.destructive_approvals[0].token_used, None)
            self.assertFalse(audit.destructive_approvals[0].approved)


if __name__ == "__main__":
    unittest.main()
