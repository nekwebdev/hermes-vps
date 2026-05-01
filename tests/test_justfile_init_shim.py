# pyright: reportUnusedCallResult=false
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _copy_just_fixture(root: pathlib.Path) -> None:
    shutil.copy2(REPO_ROOT / "Justfile", root / "Justfile")
    scripts = root / "scripts"
    scripts.mkdir()
    toolchain = scripts / "toolchain.sh"
    toolchain.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nexec bash -lc \"$1\"\n",
        encoding="utf-8",
    )
    toolchain.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def _base_env(root: pathlib.Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PATH"] = f"{root / 'bin'}:{env['PATH']}"
    return env


def _write_fake_tofu(root: pathlib.Path) -> None:
    bin_dir = root / "bin"
    bin_dir.mkdir()
    tofu = bin_dir / "tofu"
    tofu.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "$*" == *"output -raw public_ipv4"* ]]; then
              printf '203.0.113.10\n'
              exit 0
            fi
            printf 'fake tofu %s\n' "$*"
            """
        ),
        encoding="utf-8",
    )
    tofu.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def _write_minimal_repo(root: pathlib.Path, provider: str = "hetzner") -> None:
    (root / ".env").write_text(f"TF_VAR_cloud_provider={provider}\n", encoding="utf-8")
    (root / ".env").chmod(stat.S_IRUSR | stat.S_IWUSR)
    (root / "opentofu" / "providers" / provider).mkdir(parents=True)


class JustfileInitShimTests(unittest.TestCase):
    def test_init_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("init PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim init',
            justfile,
        )

    def test_init_upgrade_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("init-upgrade PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim init-upgrade',
            justfile,
        )

    def test_plan_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("plan PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim plan',
            justfile,
        )
    def test_apply_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("apply PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim apply',
            justfile,
        )

    def test_bootstrap_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("bootstrap PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim bootstrap',
            justfile,
        )

    def test_up_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("up PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim up --repo-root . --provider',
            justfile,
        )

    def test_deploy_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("deploy PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim deploy --repo-root . --provider',
            justfile,
        )
    def test_destroy_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("destroy CONFIRM=\"NO\" PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim destroy --repo-root . --provider',
            justfile,
        )

    def test_down_alias_delegates_to_destroy(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("down CONFIRM=\"NO\" PROVIDER_ARG=\"\":", justfile)
        self.assertIn("@just destroy CONFIRM={{ CONFIRM }} PROVIDER_ARG={{ PROVIDER_ARG }}", justfile)

    def test_invalid_provider_override_uses_python_cli_validation_and_exit_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _copy_just_fixture(root)
            _write_fake_tofu(root)
            _write_minimal_repo(root)

            completed = subprocess.run(
                ["just", "init", "PROVIDER=bogus"],
                cwd=root,
                env=_base_env(root),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(completed.returncode, 10)
        self.assertEqual(completed.stdout, "")
        self.assertIn("category=usage_config_error", completed.stderr)
        self.assertIn("provider must be one of: hetzner, linode", completed.stderr)
        self.assertNotIn("invalid provider override", completed.stderr)

    def test_successful_just_init_runs_python_entrypoint_and_preserves_output_contract(self) -> None:
        for argv in (["just", "PROVIDER=hetzner", "init"], ["just", "init", "PROVIDER=hetzner"]):
            with tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                _copy_just_fixture(root)
                _write_fake_tofu(root)
                _write_minimal_repo(root)

                completed = subprocess.run(
                    argv,
                    cwd=root,
                    env=_base_env(root),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stderr, "")
            self.assertIn("init: graph=init", completed.stdout)
            self.assertIn("completed=true", completed.stdout)
            self.assertIn("tofu_init: succeeded", completed.stdout)


if __name__ == "__main__":
    unittest.main()
