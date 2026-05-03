# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
import unittest

from scripts.toolchain_guard import ToolchainRuntime, ensure_expected_toolchain_runtime, is_expected_toolchain_runtime


class ToolchainGuardTests(unittest.TestCase):
    def test_flake_dev_shell_includes_uv_for_hermes_toolchain_cache(self):
        from pathlib import Path

        flake = Path(__file__).resolve().parents[1] / "flake.nix"
        self.assertIn("uv", flake.read_text())

    def test_expected_runtime_accepts_nix_store_python(self):
        runtime = ToolchainRuntime(
            python_executable="/nix/store/abc-python3-3.12.0/bin/python3",
            python_path="/nix/store/abc-python3-3.12.0/bin:/nix/store/def-coreutils/bin",
            shell_path="/nix/store/abc-python3-3.12.0/bin/python3",
        )
        self.assertTrue(is_expected_toolchain_runtime(runtime))

    def test_expected_runtime_rejects_host_python(self):
        runtime = ToolchainRuntime(
            python_executable="/usr/bin/python3",
            python_path="/usr/bin:/bin",
            shell_path="/usr/bin/python3",
        )
        self.assertFalse(is_expected_toolchain_runtime(runtime))

    def test_guard_raises_for_invalid_runtime(self):
        from scripts import toolchain_guard

        original_current_runtime = toolchain_guard.current_runtime
        try:
            toolchain_guard.current_runtime = lambda: ToolchainRuntime(
                python_executable="/usr/bin/python3",
                python_path="/usr/bin:/bin",
                shell_path="/usr/bin/python3",
            )
            with self.assertRaises(RuntimeError):
                ensure_expected_toolchain_runtime()
        finally:
            toolchain_guard.current_runtime = original_current_runtime


if __name__ == "__main__":
    unittest.main()
