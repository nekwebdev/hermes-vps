# pyright: reportAny=false, reportUnusedCallResult=false
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch


class RunnerDiagnosticsIssue06Tests(unittest.TestCase):
    def test_docker_fallback_preflight_failure_blocks_graph_execution(self) -> None:
        from hermes_vps_app.cli import main
        from hermes_vps_app import operational

        def which_stub(name: str) -> str | None:
            return "/usr/bin/docker" if name == "docker" else None

        def subprocess_stub(
            argv: list[str] | str,
            **_kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            if isinstance(argv, list) and argv[:2] == ["docker", "info"]:
                return subprocess.CompletedProcess(argv, 1, "", "Cannot connect to Docker daemon")
            return subprocess.CompletedProcess(argv, 0, "ok", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            stdout = io.StringIO()
            with (
                patch("hermes_control_core.runner.RunnerFactory._is_direnv_attached_nix_shell", return_value=False),
                patch("hermes_control_core.runner.shutil.which", side_effect=which_stub),
                patch("hermes_control_core.runner.subprocess.run", side_effect=subprocess_stub),
                patch.object(operational.OperationalActionHandler, "run", wraps=operational.OperationalActionHandler().run) as action_spy,
                contextlib.redirect_stdout(stdout),
            ):
                rc = main(["init", "--repo-root", str(root), "--provider", "hetzner", "--output", "json"])

        payload = cast(dict[str, Any], json.loads(stdout.getvalue()))
        error = cast(dict[str, Any], payload["error"])
        runner = cast(dict[str, Any], error["runner_selection"])

        self.assertNotEqual(rc, 0)
        self.assertEqual(error["category"], "runner_unavailable")
        self.assertEqual(runner["mode"], "docker_nix")
        self.assertIn("docker", str(runner["reason"]).lower())
        self.assertEqual(runner["lock_scope"], "per-launch")
        self.assertIn("docker", str(runner["guidance"]).lower())
        self.assertEqual(action_spy.call_count, 0)


if __name__ == "__main__":
    unittest.main()
