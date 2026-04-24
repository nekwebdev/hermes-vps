"""Contract-freeze tests for the wizard step/transition matrix.

These tests pin down the canonical step list, navigation semantics
(forward/back/cancel), and step-completion bookkeeping so that the
upcoming FlowCoordinator refactor (Batch 2) cannot regress visible
behavior. They run against the current ConfigureTUI implementation.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_configure_tui import _DeterministicConfigureTUI, _FakeOrchestrator

from scripts.configure_tui import ConfigureTUI, StepMeta


class StepCanonTests(unittest.TestCase):
    def test_step_list_is_canonical_keys_titles_and_count(self) -> None:
        keys = [s.key for s in ConfigureTUI.steps]
        titles = [s.title for s in ConfigureTUI.steps]
        self.assertEqual(keys, ["cloud", "server", "hermes", "telegram", "review"])
        self.assertEqual(titles, ["Cloud", "Server", "Hermes", "Telegram", "Review"])
        self.assertEqual(len(ConfigureTUI.steps), 5)
        self.assertTrue(all(isinstance(s, StepMeta) for s in ConfigureTUI.steps))


class _AppMixin:
    def _new_app(self) -> _DeterministicConfigureTUI:
        return _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )


class TransitionMatrixTests(unittest.IsolatedAsyncioTestCase, _AppMixin):
    async def test_back_from_first_step_is_noop(self) -> None:
        app = self._new_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            self.assertEqual(app.current_step, 0)
            await pilot.press("ctrl+b")
            await pilot.pause()
            self.assertEqual(app.current_step, 0)

    async def test_back_navigation_from_each_inner_step_lands_on_previous(self) -> None:
        app = self._new_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for step in range(1, len(ConfigureTUI.steps)):
                app.current_step = step
                await pilot.pause()
                await pilot.press("ctrl+b")
                await pilot.pause()
                self.assertEqual(app.current_step, step - 1)

    async def test_forward_progression_through_every_step_then_apply(self) -> None:
        app = self._new_app()
        orchestrator = app.orchestrator

        async def settle() -> None:
            # Two pumps after each Enter so the form remount + focus
            # settle before the next key event is dispatched. One pump
            # is enough for the navigation but flakes when chained
            # back-to-back through multiple step renders.
            await pilot.pause()
            await pilot.pause()

        async with app.run_test(size=(120, 40)) as pilot:
            await settle()
            # cloud -> server
            self.assertEqual(app.current_step, 0)
            await pilot.press("enter")
            await settle()
            self.assertEqual(app.current_step, 1)
            self.assertTrue(orchestrator.cloud_persisted)
            self.assertTrue(app.step_complete.get(0, False))

            # server -> hermes (defaults filled by initial state)
            await pilot.press("enter")
            await settle()
            self.assertEqual(app.current_step, 2)
            self.assertTrue(orchestrator.server_persisted)
            self.assertTrue(app.step_complete.get(1, False))

            # hermes -> telegram (api_key path goes through validation worker)
            await pilot.press("enter")
            await settle()
            self.assertEqual(app.current_step, 3)
            self.assertTrue(orchestrator.hermes_api_validated)
            self.assertTrue(orchestrator.hermes_persisted)
            self.assertTrue(app.step_complete.get(2, False))

            # telegram -> review (validation worker)
            await pilot.press("enter")
            await settle()
            self.assertEqual(app.current_step, 4)
            self.assertTrue(orchestrator.telegram_validated)
            self.assertTrue(orchestrator.telegram_persisted)
            self.assertTrue(app.step_complete.get(3, False))

            # review -> apply (exit with recap). Click the Next button
            # directly: pilot.press("enter") at the apply step races with
            # focus settling in run_test; pilot.click is deterministic and
            # exercises the same _next_btn -> action_next path.
            await pilot.click("#next")
            await settle()
            self.assertTrue(orchestrator.applied)

    async def test_step_marked_complete_after_forward_advance(self) -> None:
        app = self._new_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            self.assertFalse(app.step_complete.get(0, False))
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(app.step_complete.get(0, False))

    async def test_back_then_forward_preserves_user_typed_state_for_server(self) -> None:
        app = self._new_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 1
            await pilot.pause()
            hostname = app.query_one("#hostname-input")
            hostname.value = "edited-host"
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.state.hostname, "edited-host")
            self.assertEqual(app.current_step, 2)

            await pilot.press("ctrl+b")
            await pilot.pause()
            self.assertEqual(app.current_step, 1)
            # Re-rendering server step must not wipe the captured hostname.
            self.assertEqual(app.state.hostname, "edited-host")


if __name__ == "__main__":
    unittest.main()
