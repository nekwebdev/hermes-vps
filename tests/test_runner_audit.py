# pyright: reportAny=false, reportUnusedCallResult=false, reportUnknownArgumentType=false
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

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
        serialized = audit.to_dict()
        runner_selection = serialized["runner_selection"]
        self.assertIsInstance(runner_selection, dict)
        assert isinstance(runner_selection, dict)
        self.assertEqual(runner_selection["lock_scope"], "per-launch")
        self.assertTrue(bool(runner_selection["guidance"]))

    def test_host_override_requires_reason(self) -> None:
        with self.assertRaises(RunnerDetectionError):
            RunnerFactory(repo_root=Path("."), allow_host_override=True)

    def test_host_runner_is_not_selected_without_explicit_override(self) -> None:
        factory = RunnerFactory(repo_root=Path("."))
        with patch("hermes_control_core.runner.RunnerFactory._is_direnv_attached_nix_shell", return_value=False), patch(
            "hermes_control_core.runner.shutil.which", return_value=None
        ):
            with self.assertRaises(RunnerDetectionError):
                factory.get()

    def test_host_runner_selection_records_explicit_override_policy(self) -> None:
        factory = RunnerFactory(
            repo_root=Path("."),
            allow_host_override=True,
            override_reason="break-glass test",
        )
        with patch("hermes_control_core.runner.RunnerFactory._is_direnv_attached_nix_shell", return_value=False), patch(
            "hermes_control_core.runner.shutil.which", return_value=None
        ):
            runner = factory.get()

        self.assertEqual(runner.mode, "host")
        self.assertIsNotNone(factory.selection)
        assert factory.selection is not None
        self.assertIn("explicit host override", factory.selection.reason)
        self.assertIn("override token", factory.selection.guidance)


if __name__ == "__main__":
    unittest.main()
