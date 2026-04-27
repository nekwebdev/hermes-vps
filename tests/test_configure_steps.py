# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
"""Wiring tests for extracted step controllers.

These tests pin the StepController contract (every extracted controller
exposes a canonical step `key` matching ConfigureTUI.steps and a mount /
capture / validate triplet) so the dispatcher in ConfigureTUI._render_step
and ConfigureTUI._capture_state_from_widgets stays in sync as more steps
get extracted.
"""

from __future__ import annotations

import inspect
import unittest

from scripts.configure_steps import EXTRACTED_CONTROLLERS
from scripts.configure_steps._base import StepController
from scripts.configure_tui import ConfigureTUI


class StepControllerProtocolTests(unittest.TestCase):
    def test_every_extracted_controller_has_a_canonical_step_key(self) -> None:
        canonical = {step.key for step in ConfigureTUI.steps}
        for controller in EXTRACTED_CONTROLLERS:
            self.assertIn(
                controller.key,
                canonical,
                f"{controller.__name__}.key={controller.key!r} is not in canonical step list",
            )

    def test_extracted_controllers_subclass_step_controller(self) -> None:
        for controller in EXTRACTED_CONTROLLERS:
            self.assertIn(StepController, controller.__mro__[1:], f"{controller.__name__} must inherit from StepController")

    def test_extracted_controllers_have_no_duplicate_keys(self) -> None:
        keys = [c.key for c in EXTRACTED_CONTROLLERS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_extracted_controllers_implement_required_methods(self) -> None:
        for controller in EXTRACTED_CONTROLLERS:
            for method in ("mount", "capture", "validate"):
                self.assertTrue(
                    callable(getattr(controller, method, None)),
                    f"{controller.__name__} is missing method {method}",
                )
            mount_sig = inspect.signature(controller.mount)
            self.assertIn(
                "form",
                mount_sig.parameters,
                f"{controller.__name__}.mount must accept a form parameter",
            )


if __name__ == "__main__":
    unittest.main()
