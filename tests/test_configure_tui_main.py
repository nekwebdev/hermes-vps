# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
import unittest
from unittest.mock import patch

from scripts import configure_tui


class ConfigureTUIMainTests(unittest.TestCase):
    def test_main_returns_zero_when_cancelled_via_none_rows(self) -> None:
        with patch.object(configure_tui, "run_configure_app", return_value=None), patch(
            "builtins.print"
        ) as mock_print:
            rc = configure_tui.main()

        self.assertEqual(rc, 0)
        mock_print.assert_any_call("Configuration cancelled.")

    def test_main_returns_zero_on_keyboard_interrupt(self) -> None:
        with patch.object(configure_tui, "run_configure_app", side_effect=KeyboardInterrupt), patch(
            "builtins.print"
        ) as mock_print:
            rc = configure_tui.main()

        self.assertEqual(rc, 0)
        mock_print.assert_any_call("Configuration cancelled.")


if __name__ == "__main__":
    unittest.main()
