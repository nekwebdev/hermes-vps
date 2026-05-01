from __future__ import annotations

import unittest
from pathlib import Path

from hermes_control_core import RunnerDetectionError, RunnerFactory, SessionAuditLog


class RunnerAuditTests(unittest.TestCase):
    def test_runner_factory_records_selection_in_audit_log(self) -> None:
        audit = SessionAuditLog(session_id="test-runner-audit", repo_root=Path("."))
        factory = RunnerFactory(repo_root=Path("."), audit_log=audit)

        _ = factory.get()

        self.assertIsNotNone(audit.runner_selection)
        assert audit.runner_selection is not None
        self.assertIn(
            audit.runner_selection.mode,
            {"direnv_nix", "nix_develop", "docker_nix", "host"},
        )
        self.assertTrue(bool(audit.runner_selection.reason))

    def test_host_override_requires_reason(self) -> None:
        with self.assertRaises(RunnerDetectionError):
            RunnerFactory(repo_root=Path("."), allow_host_override=True)


if __name__ == "__main__":
    unittest.main()
