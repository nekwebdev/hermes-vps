# pyright: reportUnusedCallResult=false, reportImplicitOverride=false
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from hermes_control_core import RunRequest, RunResult, Runner
from hermes_control_core.interfaces import RunnerMode


@dataclass
class RunnerStub(Runner):
    mode: RunnerMode = "direnv_nix"
    seen: list[RunRequest] | None = None

    def run(self, request: RunRequest) -> RunResult:
        if self.seen is not None:
            self.seen.append(request)
        return RunResult(
            exit_code=0,
            stdout="ok",
            stderr="",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            runner_mode="direnv_nix",
            redactions_applied=True,
        )


class InitCliTests(unittest.TestCase):
    def test_headless_init_upgrade_entrypoint_runs_graph_for_selected_provider(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=RunnerStub()):
                rc = main([
                    "init-upgrade",
                    "--repo-root",
                    str(root),
                    "--provider",
                    "hetzner",
                ])

            self.assertEqual(rc, 0)

    def test_headless_init_entrypoint_runs_graph_for_selected_provider(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=RunnerStub()):
                rc = main([
                    "init",
                    "--repo-root",
                    str(root),
                    "--provider",
                    "hetzner",
                ])

            self.assertEqual(rc, 0)

    def test_init_constructs_tofu_command_as_argv(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=linode\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/linode").mkdir(parents=True)

            seen: list[RunRequest] = []
            stub = RunnerStub(seen=seen)
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=stub):
                rc = main(["init", "--repo-root", str(root), "--provider", "linode"])

            self.assertEqual(rc, 0)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0].command, ["tofu", "-chdir=opentofu/providers/linode", "init"])
            self.assertFalse(seen[0].shell)

    def test_init_upgrade_constructs_tofu_upgrade_command_as_argv(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=linode\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/linode").mkdir(parents=True)

            seen: list[RunRequest] = []
            stub = RunnerStub(seen=seen)
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=stub):
                rc = main(["init-upgrade", "--repo-root", str(root), "--provider", "linode"])

            self.assertEqual(rc, 0)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0].command, ["tofu", "-chdir=opentofu/providers/linode", "init", "-upgrade"])
            self.assertFalse(seen[0].shell)

    def test_plan_constructs_saved_artifact_command_as_argv(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            seen: list[RunRequest] = []
            stub = RunnerStub(seen=seen)
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=stub):
                rc = main(["plan", "--repo-root", str(root), "--provider", "hetzner"])

            self.assertEqual(rc, 0)
            self.assertEqual(len(seen), 1)
            self.assertEqual(
                seen[0].command,
                ["tofu", "-chdir=opentofu/providers/hetzner", "plan", "-out=tofuplan"],
            )
            self.assertFalse(seen[0].shell)

    def test_provider_defaults_from_tf_var_cloud_provider(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=linode\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/linode").mkdir(parents=True)

            seen: list[RunRequest] = []
            stub = RunnerStub(seen=seen)
            with patch.dict(os.environ, {"TF_VAR_cloud_provider": "linode"}, clear=False), patch(
                "hermes_vps_app.cli.RunnerFactory.get", return_value=stub
            ):
                rc = main(["init", "--repo-root", str(root)])

            self.assertEqual(rc, 0)
            self.assertEqual(seen[0].command, ["tofu", "-chdir=opentofu/providers/linode", "init"])

    def test_invalid_provider_override_fails_before_runner_side_effects(self) -> None:
        from hermes_vps_app.operational import run_operational_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            seen: list[RunRequest] = []
            with self.assertRaises(ValueError):
                run_operational_graph(
                    action="plan",
                    runner=RunnerStub(seen=seen),
                    repo_root=root,
                    provider_override="aws",
                )
            self.assertEqual(seen, [])

    def test_preflight_denies_missing_or_unsafe_env_before_tofu(self) -> None:
        from hermes_vps_app.operational import run_operational_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            seen_missing: list[RunRequest] = []
            with self.assertRaisesRegex(ValueError, ".env is missing"):
                run_operational_graph(
                    action="plan",
                    runner=RunnerStub(seen=seen_missing),
                    repo_root=root,
                    provider_override="hetzner",
                )
            self.assertEqual(seen_missing, [])

            env_path = root / ".env"
            env_path.write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(env_path, 0o644)

            seen_unsafe: list[RunRequest] = []
            with self.assertRaisesRegex(ValueError, "permissions are too broad"):
                run_operational_graph(
                    action="plan",
                    runner=RunnerStub(seen=seen_unsafe),
                    repo_root=root,
                    provider_override="hetzner",
                )
            self.assertEqual(seen_unsafe, [])

    def test_preflight_requires_provider_directory(self) -> None:
        from hermes_vps_app.operational import run_init_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=linode\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)

            seen: list[RunRequest] = []
            with self.assertRaisesRegex(ValueError, "provider directory not found"):
                run_init_graph(
                    runner=RunnerStub(seen=seen),
                    repo_root=root,
                    provider_override="linode",
                )
            self.assertEqual(seen, [])

    def test_host_runner_requires_escalation_token(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            host_stub = RunnerStub(mode="host")
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=host_stub):
                with self.assertRaises(PermissionError):
                    _ = main(
                        [
                            "init",
                            "--repo-root",
                            str(root),
                            "--provider",
                            "hetzner",
                            "--allow-host-override",
                            "--override-reason",
                            "break-glass",
                        ]
                    )

    def test_host_runner_succeeds_with_required_override_fields_and_token(self) -> None:
        from hermes_vps_app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            host_stub = RunnerStub(mode="host")
            with patch("hermes_vps_app.cli.RunnerFactory.get", return_value=host_stub):
                rc = main(
                    [
                        "init",
                        "--repo-root",
                        str(root),
                        "--provider",
                        "hetzner",
                        "--allow-host-override",
                        "--override-reason",
                        "break-glass",
                        "--host-override-token",
                        "I-ACK-HOST-OVERRIDE",
                    ]
                )

            self.assertEqual(rc, 0)

    def test_host_runner_disabled_by_default_without_explicit_enablement(self) -> None:
        from hermes_vps_app.cli import main
        from hermes_control_core import RunnerDetectionError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TF_VAR_cloud_provider=hetzner\n", encoding="utf-8")
            os.chmod(root / ".env", stat.S_IRUSR | stat.S_IWUSR)
            (root / "opentofu/providers/hetzner").mkdir(parents=True)

            with patch("hermes_control_core.runner.RunnerFactory._is_direnv_attached_nix_shell", return_value=False), patch(
                "hermes_control_core.runner.shutil.which", return_value=None
            ):
                with self.assertRaises(RunnerDetectionError):
                    _ = main(["init", "--repo-root", str(root), "--provider", "hetzner"])


if __name__ == "__main__":
    unittest.main()
