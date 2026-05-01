from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_control_core import (
    ActionDescriptor,
    ActionGraph,
    Engine,
    Runner,
    RunRequest,
    RunResult,
    SessionAuditLog,
)
from hermes_control_core.interfaces import RunnerMode


@dataclass
class HostRunnerStub(Runner):
    mode: RunnerMode = "host"

    def run(self, request: RunRequest) -> RunResult:  # pragma: no cover - not used in this test
        raise NotImplementedError


class HandlerStub:
    def run(self, action: ActionDescriptor, context: dict[str, Any], runner: Runner) -> dict[str, Any]:
        return {"ok": True}


def _graph() -> ActionGraph:
    return ActionGraph(
        name="host_override_gate_test",
        actions={
            "a": ActionDescriptor(action_id="a", label="a"),
        },
    )


class EngineHostOverrideGateTests(unittest.TestCase):
    def test_host_mode_requires_token(self) -> None:
        audit = SessionAuditLog(session_id="host-gate-1", repo_root=Path("."))
        engine = Engine(
            graph=_graph(),
            runner=HostRunnerStub(),
            handler=HandlerStub(),
            audit_log=audit,
            context={"override_reason": "break-glass for local debug"},
            host_override_token=None,
            require_host_override_token=True,
        )
        with self.assertRaises(PermissionError):
            engine.run()
        self.assertEqual(len(audit.destructive_approvals), 1)
        self.assertFalse(audit.destructive_approvals[0].approved)
        self.assertIsNone(audit.destructive_approvals[0].token_used)
        self.assertEqual(
            audit.destructive_approvals[0].details.get("override_reason"),
            "break-glass for local debug",
        )

    def test_host_mode_with_valid_token_runs(self) -> None:
        audit = SessionAuditLog(session_id="host-gate-2", repo_root=Path("."))
        engine = Engine(
            graph=_graph(),
            runner=HostRunnerStub(),
            handler=HandlerStub(),
            audit_log=audit,
            host_override_token="I-ACK-HOST-OVERRIDE",
            require_host_override_token=True,
        )
        result = engine.run()
        self.assertTrue(result.completed)
        self.assertEqual(len(audit.destructive_approvals), 1)
        self.assertTrue(audit.destructive_approvals[0].approved)
        self.assertEqual(audit.destructive_approvals[0].token_used, "I-ACK-HOST-OVERRIDE")


if __name__ == "__main__":
    unittest.main()
