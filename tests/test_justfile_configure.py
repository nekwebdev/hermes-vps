# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
import pathlib
import unittest


class JustfileConfigureTests(unittest.TestCase):
    def test_configure_target_uses_toolchain_wrapper(self):
        justfile = pathlib.Path("Justfile").read_text()
        self.assertIn("configure:", justfile)
        self.assertIn(
            'TOOLCHAIN_QUIET=1 ./scripts/toolchain.sh "python3 -m hermes_vps_app.panel_entrypoint --repo-root . --initial-panel configuration"',
            justfile,
        )
        configure_recipe = justfile.split("configure:", 1)[1].split("\n#", 1)[0]
        self.assertNotIn("scripts.configure_tui", configure_recipe)


if __name__ == "__main__":
    unittest.main()
