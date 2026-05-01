# pyright: reportUnusedCallResult=false, reportImplicitOverride=false, reportAny=false
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from hermes_control_core import RunRequest, RunResult, Runner, SessionAuditLog
from hermes_control_core.interfaces import RunnerMode


@dataclass
class DestroyRunnerStub(Runner):
    mode: RunnerMode = "direnv_nix"
    seen: list[RunRequest] = field(default_factory=list)

    def run(self, request: RunRequest) -> RunResult:
        self.seen.append(request)
        command = request.command
        assert isinstance(command, list)
        if command[:3] == ["tofu", command[1], "output"]:
            values = {
                "public_ipv4": "203.0.113.10\n",
                "admin_username": "root\n",
                "server_id": "srv-123\n",
            }
            key = command[-1]
            return RunResult(
                exit_code=0 if key in values else 1,
                stdout=values.get(key, ""),
                stderr="" if key in values else "missing output",
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


def _destroy_fixture(root: Path) -> None:
    (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
    os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
    tf_dir = root / "opentofu/providers/hetzner"
    tf_dir.mkdir(parents=True)
    (tf_dir / "terraform.tfstate").write_text("{}", encoding="utf-8")


class Issue07MaintenanceMonitoringPanelWiringTests(unittest.TestCase):
    def test_destroy_down_are_maintenance_owned_and_deploy_owns_init_plan_apply_bootstrap_verify(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()

        maintenance = shell.maintenance_actions()
        deployment = shell.deployment_actions() + shell.deployment_advanced_actions()
        monitoring = shell.monitoring_actions()

        maintenance_workflows = {action.workflow for action in maintenance}
        deployment_workflows = {action.workflow for action in deployment}
        monitoring_ids = {action.action_id for action in monitoring}

        self.assertIn("destroy", maintenance_workflows)
        self.assertIn("down", maintenance_workflows)
        self.assertNotIn("init", maintenance_workflows)
        self.assertNotIn("up", maintenance_workflows)
        for workflow in ("init", "plan", "apply", "bootstrap", "verify"):
            self.assertIn(workflow, deployment_workflows)
        self.assertNotIn("destroy", deployment_workflows)
        self.assertNotIn("down", deployment_workflows)
        self.assertNotIn("up", deployment_workflows)
        self.assertTrue(all(action.panel == "maintenance" for action in maintenance if action.workflow in {"destroy", "down"}))
        self.assertTrue(all(action.state_change_label == "state-changing" for action in maintenance if action.workflow in {"destroy", "down"}))
        self.assertIn("logs_read_only", monitoring_ids)
        self.assertIn("hardening_audit_read_only", monitoring_ids)
        self.assertTrue(all(action.panel == "monitoring" for action in monitoring))
        self.assertTrue(all(action.side_effect_level == "none" for action in monitoring))

    def test_maintenance_destroy_preview_uses_existing_destructive_preview_metadata(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _destroy_fixture(root)

            payload = shell.preview_maintenance_action(
                action="destroy",
                runner=DestroyRunnerStub(),
                repo_root=root,
                provider_override="hetzner",
            )

        self.assertEqual(payload["workflow"], "destroy")
        actions = cast(list[dict[str, object]], payload["actions"])
        self.assertEqual([action["action_id"] for action in actions], ["tofu_destroy"])
        self.assertTrue(actions[0]["approval_required"])
        destroy_preview = cast(dict[str, object], payload["destroy_preview"])
        self.assertEqual(destroy_preview["provider"], "hetzner")
        self.assertEqual(destroy_preview["state_file_count"], 1)
        safe_outputs = cast(dict[str, object], destroy_preview["safe_outputs"])
        self.assertEqual(safe_outputs["public_ipv4"], "203.0.113.10")
        self.assertNotIn("DESTROY:hetzner", str(payload))

    def test_maintenance_down_alias_reuses_destroy_confirmation_and_audit_gate(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _destroy_fixture(root)
            runner = DestroyRunnerStub()
            audit = SessionAuditLog(session_id="panel-down", repo_root=root)

            with self.assertRaises(PermissionError):
                _ = shell.run_maintenance_action(
                    action="down",
                    runner=runner,
                    repo_root=root,
                    provider_override="hetzner",
                    audit_log=audit,
                )
            self.assertNotIn(["tofu", "-chdir=opentofu/providers/hetzner", "destroy"], [req.command for req in runner.seen])

            payload = shell.run_maintenance_action(
                action="down",
                runner=runner,
                repo_root=root,
                provider_override="hetzner",
                approve_destructive="DESTROY:hetzner",
                audit_log=audit,
            )

        self.assertEqual(payload["workflow"], "down")
        action = cast(list[dict[str, object]], payload["actions"])[0]
        self.assertEqual(action["action_id"], "tofu_destroy")
        self.assertEqual(action["status"], "succeeded")
        self.assertEqual(len(audit.destructive_approvals), 2)
        self.assertFalse(audit.destructive_approvals[0].approved)
        self.assertTrue(audit.destructive_approvals[1].approved)
        self.assertEqual(audit.destructive_approvals[1].action_id, "tofu_destroy")

    def test_monitoring_health_probe_results_render_required_read_only_fields(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        shell = ControlPanelShell()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / ".env.example").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            payload = shell.run_monitoring_status(repo_root=root, provider_override="hetzner")

        self.assertEqual(payload["workflow"], "monitoring")
        actions = cast(list[dict[str, object]], payload["actions"])
        by_id = {str(action["action_id"]): action for action in actions}
        self.assertIn("health_probe", by_id)
        self.assertIn("logs_read_only", by_id)
        self.assertIn("hardening_audit_read_only", by_id)

        result = cast(dict[str, object], by_id["health_probe"]["result"])
        details = cast(dict[str, object], result["details"])
        for key in ("severity", "summary", "evidence", "observed_time", "runner_mode", "source_command"):
            self.assertIn(key, details)
        self.assertEqual(details["runner_mode"], "local")
        source_command = cast(dict[str, object], details["source_command"])
        self.assertTrue(source_command["redacted"])
        self.assertNotIn("HERMES_API_KEY", str(source_command))
        if details["severity"] != "ok":
            self.assertIn("remediation_hint", details)


if __name__ == "__main__":
    unittest.main()
