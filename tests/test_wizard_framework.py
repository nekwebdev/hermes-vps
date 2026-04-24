"""Smoke tests for the wizard_framework seed.

The seed re-exports the reusable navigation/correlation/step-controller
primitives from one stable import location and adds a thin StepRegistry
so a future second consumer (control panel for additional commands) can
plug in step controllers without touching ConfigureTUI.

Tests assert that:
* Re-exports are reachable from scripts.wizard_framework.
* StepRegistry registers, looks up, rejects duplicates, and supports
  iteration / membership checks.
* A custom subclass of the generic StepController works through the
  registry without depending on ConfigureTUI or WizardState — proving
  the seed is reusable for non-configure flows.
"""

from __future__ import annotations

import unittest

from scripts.wizard_framework import (
    CorrelatedTask,
    FlowCoordinator,
    StepController,
    StepRegistry,
    TransitionResult,
)


class WizardFrameworkReexportTests(unittest.TestCase):
    def test_canonical_primitives_are_reexported(self) -> None:
        # All five reusable types must be reachable from the framework
        # package; second consumers should not need to know the legacy
        # module layout.
        self.assertTrue(callable(FlowCoordinator))
        self.assertTrue(callable(CorrelatedTask))
        self.assertTrue(callable(StepRegistry))
        self.assertTrue(callable(StepController))
        # TransitionResult is a dataclass — check via its __dataclass_fields__.
        self.assertIn("next_step", TransitionResult.__dataclass_fields__)
        self.assertIn("step_complete", TransitionResult.__dataclass_fields__)
        self.assertIn("finished", TransitionResult.__dataclass_fields__)

    def test_reexports_are_the_same_objects_as_legacy_module_paths(self) -> None:
        from scripts.configure_async import CorrelatedTask as LegacyTask
        from scripts.configure_flow import (
            FlowCoordinator as LegacyFlow,
            TransitionResult as LegacyTransition,
        )
        from scripts.configure_steps._base import StepController as WizardStepController

        self.assertIs(FlowCoordinator, LegacyFlow)
        self.assertIs(CorrelatedTask, LegacyTask)
        self.assertIs(TransitionResult, LegacyTransition)
        # Wizard-specific subclass must inherit from the framework base.
        self.assertTrue(issubclass(WizardStepController, StepController))


class StepRegistryTests(unittest.TestCase):
    def _controller(self, key: str) -> StepController:
        controller = StepController(app=None)
        # type: ignore[assignment] - test scaffolding
        type(controller).key = key  # noqa: B010
        return controller

    def test_register_and_lookup_round_trip(self) -> None:
        registry = StepRegistry()

        class _Foo(StepController):
            key = "foo"

        controller = _Foo(app=None)
        registry.register(controller)
        self.assertIs(registry.get("foo"), controller)
        self.assertIn("foo", registry)
        self.assertEqual(len(registry), 1)
        self.assertEqual(registry.keys(), ["foo"])

    def test_lookup_missing_returns_none(self) -> None:
        registry = StepRegistry()
        self.assertIsNone(registry.get("nope"))

    def test_register_rejects_duplicate_keys(self) -> None:
        registry = StepRegistry()

        class _Bar(StepController):
            key = "bar"

        registry.register(_Bar(app=None))
        with self.assertRaises(ValueError):
            registry.register(_Bar(app=None))


class GenericStepControllerSmokeTests(unittest.TestCase):
    def test_custom_command_can_use_step_controller_protocol(self) -> None:
        events: list[str] = []

        class _FakeApp:
            captured_value: str = ""

        class _CustomStep(StepController):
            key = "custom"

            def mount(self, form) -> None:  # type: ignore[override]
                events.append(f"mount:{form}")

            def capture(self) -> bool:  # type: ignore[override]
                self.app.captured_value = "ok"
                events.append("capture")
                return True

            def validate(self) -> dict[str, str]:  # type: ignore[override]
                events.append("validate")
                return {}

        app = _FakeApp()
        registry = StepRegistry()
        registry.register(_CustomStep(app=app))

        controller = registry.get("custom")
        assert controller is not None
        controller.mount("fake-form")
        captured = controller.capture()
        errors = controller.validate()

        self.assertTrue(captured)
        self.assertEqual(errors, {})
        self.assertEqual(events, ["mount:fake-form", "capture", "validate"])
        self.assertEqual(app.captured_value, "ok")


if __name__ == "__main__":
    unittest.main()
