# pyright: reportUnusedCallResult=false, reportImplicitOverride=false, reportAny=false, reportUnusedParameter=false
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hermes_control_core import (
    ActionDescriptor,
    ActionGraph,
    Engine,
    RunRequest,
    RunResult,
    Runner,
    SessionAuditLog,
)
from hermes_control_core.interfaces import RunnerMode
from hermes_vps_app.cli import main
from hermes_vps_app.status_presentation import presentation_from_engine_result


@dataclass
class HostRunner(Runner):
    mode: RunnerMode = "host"

    def run(self, request: RunRequest) -> RunResult:
        return RunResult(
            exit_code=0,
            stdout="ok\n",
            stderr="",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            runner_mode=self.mode,
            redactions_applied=True,
        )


class NoopHandler:
    def run(self, action: ActionDescriptor, context: dict[str, Any], runner: Runner) -> dict[str, Any]:
        return {"ok": True, "runner_mode": runner.mode}


def _fixture(root: Path) -> None:
    (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
    (root / ".env").chmod(0o600)
    (root / "opentofu/providers/hetzner").mkdir(parents=True)


def _graph() -> ActionGraph:
    return ActionGraph(name="host-issue07", actions={"a": ActionDescriptor(action_id="a", label="a")})


class HostOverrideIssue07Tests(unittest.TestCase):
    def test_denied_bad_token_uses_taxonomy_and_never_echoes_secret_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            bad_token = "BAD-HOST-TOKEN-secret-value"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=HostRunner()), contextlib.redirect_stdout(
                stdout
            ), contextlib.redirect_stderr(stderr):
                rc = main(
                    [
                        "init",
                        "--repo-root",
                        str(root),
                        "--provider",
                        "hetzner",
                        "--allow-host-override",
                        "--override-reason",
                        "break glass maintenance",
                        "--host-override-token",
                        bad_token,
                        "--output",
                        "json",
                    ]
                )

            self.assertEqual(rc, 43)
            self.assertEqual(stderr.getvalue(), "")
            serialized = stdout.getvalue()
            payload = json.loads(serialized)
            self.assertEqual(payload["error"]["category"], "host_override_denied")
            self.assertIn("guidance", payload["error"])
            self.assertIn("host override", payload["error"]["repair_scope"])
            self.assertNotIn(bad_token, serialized)

            audit = SessionAuditLog(session_id="denied", repo_root=root)
            engine = Engine(
                graph=_graph(),
                runner=HostRunner(),
                handler=NoopHandler(),
                audit_log=audit,
                context={"override_reason": "break glass maintenance"},
                host_override_token=bad_token,
            )
            with self.assertRaises(PermissionError) as denied:
                engine.run()
            self.assertNotIn(bad_token, str(denied.exception))
            self.assertNotIn(bad_token, json.dumps(audit.to_dict(), sort_keys=True))

    def test_missing_reason_is_host_override_denial_with_guidance(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = main(["init", "--allow-host-override", "--output", "json"])

        self.assertEqual(rc, 43)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"]["category"], "host_override_denied")
        self.assertIn("override reason", payload["error"]["message"].lower())
        self.assertIn("audited host override", payload["error"]["repair_scope"])
        self.assertEqual(stderr.getvalue(), "")

    def test_approved_override_records_non_secret_audit_and_status_displays_host_reason(self) -> None:
        audit = SessionAuditLog(session_id="approved", repo_root=Path("."))
        reason = "break glass maintenance"
        result = Engine(
            graph=_graph(),
            runner=HostRunner(),
            handler=NoopHandler(),
            audit_log=audit,
            context={"override_reason": reason},
            host_override_token="I-ACK-HOST-OVERRIDE",
        ).run()

        self.assertTrue(result.completed)
        serialized_audit = json.dumps(audit.to_dict(), sort_keys=True)
        self.assertNotIn("I-ACK-HOST-OVERRIDE", serialized_audit)
        approval = audit.to_dict()["destructive_approvals"][0]
        self.assertTrue(approval["approved"])
        self.assertIsNone(approval["token_used"])
        self.assertEqual(approval["details"]["override_reason"], reason)
        self.assertEqual(approval["details"]["runner_mode"], "host")

        status = presentation_from_engine_result(workflow="init", graph=_graph(), result=result).to_dict()
        self.assertEqual(status["runner_mode"], "host")
        self.assertEqual(status["host_override"], {"approved": True, "runner_mode": "host", "override_reason": reason})

    def test_cli_approved_override_prints_host_mode_and_reason_before_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=HostRunner()), contextlib.redirect_stdout(
                stdout
            ), contextlib.redirect_stderr(stderr):
                rc = main(
                    [
                        "init",
                        "--repo-root",
                        str(root),
                        "--provider",
                        "hetzner",
                        "--allow-host-override",
                        "--override-reason",
                        "break glass maintenance",
                        "--host-override-token",
                        "I-ACK-HOST-OVERRIDE",
                    ]
                )

        self.assertEqual(rc, 0)
        lines = stdout.getvalue().splitlines()
        self.assertGreaterEqual(len(lines), 2)
        self.assertEqual(lines[0], "host_override: approved=true runner=host reason=break glass maintenance")
        self.assertIn("runner=host", lines[1])
        self.assertNotIn("I-ACK-HOST-OVERRIDE", stdout.getvalue() + stderr.getvalue())
    def test_panel_status_displays_host_override_mode_and_reason(self) -> None:
        from hermes_vps_app.panel_shell import ControlPanelShell

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            status = ControlPanelShell().run_init_status(
                runner=HostRunner(),
                repo_root=root,
                provider_override="hetzner",
                host_override_token="I-ACK-HOST-OVERRIDE",
                override_reason="break glass maintenance",
            )

        self.assertEqual(status["runner_mode"], "host")
        self.assertEqual(
            status["host_override"],
            {"approved": True, "runner_mode": "host", "override_reason": "break glass maintenance"},
        )


if __name__ == "__main__":
    unittest.main()
