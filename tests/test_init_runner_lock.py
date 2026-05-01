# pyright: reportUnusedCallResult=false, reportUnknownLambdaType=false
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_control_core import DetectionMode, RunnerFactory


class InitRunnerLockTests(unittest.TestCase):
    def test_runner_detection_order_prefers_direnv_then_locks_single_runner(self) -> None:
        factory = RunnerFactory(repo_root=Path("."))

        with patch("hermes_control_core.runner.RunnerFactory._is_direnv_attached_nix_shell", return_value=True), patch(
            "hermes_control_core.runner.shutil.which", side_effect=lambda name: "/usr/bin/" + name
        ), patch.object(factory, "detect", wraps=factory.detect) as detect_spy:
            first = factory.get()
            second = factory.get()

        self.assertIs(first, second)
        self.assertIsNotNone(factory.selection)
        assert factory.selection is not None
        self.assertEqual(factory.selection.mode, DetectionMode.DIRENV_NIX)
        self.assertEqual(detect_spy.call_count, 1)


if __name__ == "__main__":
    unittest.main()
