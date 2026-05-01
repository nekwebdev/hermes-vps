# pyright: reportUnusedCallResult=false
import pathlib
import unittest


class JustfileInitShimTests(unittest.TestCase):
    def test_init_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("init PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.cli init',
            justfile,
        )

    def test_init_upgrade_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("init-upgrade PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.cli init-upgrade',
            justfile,
        )

    def test_plan_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("plan PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.cli plan',
            justfile,
        )
    def test_apply_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("apply PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.cli apply',
            justfile,
        )

    def test_bootstrap_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("bootstrap PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.cli bootstrap',
            justfile,
        )

    def test_up_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("up PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.cli up --repo-root . --provider ${P}"',
            justfile,
        )

    def test_deploy_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("deploy PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.cli deploy --repo-root . --provider ${P}"',
            justfile,
        )
    def test_destroy_target_delegates_to_python_entrypoint(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("destroy CONFIRM=\"NO\" PROVIDER_ARG=\"\":", justfile)
        self.assertIn(
            './scripts/toolchain.sh "python3 -m hermes_vps_app.cli destroy --repo-root . --provider ${P} --approve-destructive DESTROY:${P}"',
            justfile,
        )

    def test_down_alias_delegates_to_destroy(self) -> None:
        justfile = pathlib.Path("Justfile").read_text(encoding="utf-8")
        self.assertIn("down CONFIRM=\"NO\" PROVIDER_ARG=\"\":", justfile)
        self.assertIn("@just destroy CONFIRM={{ CONFIRM }} PROVIDER_ARG={{ PROVIDER_ARG }}", justfile)


if __name__ == "__main__":
    unittest.main()
