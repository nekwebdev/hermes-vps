# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
"""Pure unit tests for FlowCoordinator (no Textual).

The coordinator owns the wizard step index and step-complete bookkeeping.
It is the navigation core that ConfigureTUI delegates to from
action_next/action_back and from the watch_current_step bootstrap path.
These tests pin down the navigation invariants so future controller
extraction (Batch 3) and async-correlation rework (Batch 4) cannot move
the navigation rules around silently.
"""

from __future__ import annotations

import unittest

from scripts.configure_flow import FlowCoordinator, TransitionResult


class FlowCoordinatorConstructionTests(unittest.TestCase):
    def test_starts_at_zero_with_no_completions(self) -> None:
        coord = FlowCoordinator(step_count=5)
        self.assertEqual(coord.current_step, 0)
        self.assertEqual(coord.step_complete, {})
        self.assertTrue(coord.at_first_step())
        self.assertFalse(coord.at_last_step())

    def test_can_start_at_arbitrary_in_range_step(self) -> None:
        coord = FlowCoordinator(step_count=5, current=2)
        self.assertEqual(coord.current_step, 2)

    def test_rejects_invalid_construction_arguments(self) -> None:
        with self.assertRaises(ValueError):
            _ = FlowCoordinator(step_count=0)
        with self.assertRaises(ValueError):
            FlowCoordinator(step_count=5, current=-1)
        with self.assertRaises(ValueError):
            FlowCoordinator(step_count=5, current=5)


class FlowCoordinatorAdvanceTests(unittest.TestCase):
    def test_advance_increments_and_marks_previous_complete(self) -> None:
        coord = FlowCoordinator(step_count=5)
        result = coord.advance()
        self.assertEqual(
            result, TransitionResult(next_step=1, step_complete=True, finished=False)
        )
        self.assertEqual(coord.current_step, 1)
        self.assertTrue(coord.step_complete[0])

    def test_advance_at_last_step_signals_finished_without_increment(self) -> None:
        coord = FlowCoordinator(step_count=5, current=4)
        result = coord.advance()
        self.assertTrue(result.finished)
        self.assertEqual(result.next_step, 4)
        self.assertEqual(coord.current_step, 4)
        self.assertTrue(coord.step_complete[4])


class FlowCoordinatorBackTests(unittest.TestCase):
    def test_back_decrements_and_does_not_change_completions(self) -> None:
        coord = FlowCoordinator(step_count=5, current=2)
        coord.advance()  # at 3, step 2 complete
        snapshot = coord.step_complete
        result = coord.back()
        self.assertEqual(result.next_step, 2)
        self.assertFalse(result.step_complete)
        self.assertEqual(coord.current_step, 2)
        self.assertEqual(coord.step_complete, snapshot)

    def test_back_from_first_step_is_a_noop(self) -> None:
        coord = FlowCoordinator(step_count=5)
        result = coord.back()
        self.assertEqual(
            result, TransitionResult(next_step=0, step_complete=False, finished=False)
        )
        self.assertEqual(coord.current_step, 0)


class FlowCoordinatorJumpTests(unittest.TestCase):
    def test_jump_to_changes_step_without_marking_complete(self) -> None:
        coord = FlowCoordinator(step_count=5)
        result = coord.jump_to(3)
        self.assertEqual(result.next_step, 3)
        self.assertFalse(result.step_complete)
        self.assertFalse(result.finished)
        self.assertEqual(coord.current_step, 3)
        self.assertEqual(coord.step_complete, {})

    def test_jump_to_out_of_range_raises(self) -> None:
        coord = FlowCoordinator(step_count=5)
        with self.assertRaises(ValueError):
            coord.jump_to(-1)
        with self.assertRaises(ValueError):
            coord.jump_to(5)

    def test_jump_to_same_step_is_idempotent(self) -> None:
        coord = FlowCoordinator(step_count=5, current=2)
        coord.jump_to(2)
        self.assertEqual(coord.current_step, 2)

    def test_jump_to_keeps_existing_completion_state(self) -> None:
        coord = FlowCoordinator(step_count=5)
        coord.advance()
        coord.jump_to(3)
        self.assertEqual(coord.current_step, 3)
        self.assertTrue(coord.step_complete[0])


class FlowCoordinatorCompletionViewTests(unittest.TestCase):
    def test_step_complete_property_returns_snapshot_copy(self) -> None:
        coord = FlowCoordinator(step_count=5)
        coord.advance()
        snap = coord.step_complete
        snap[99] = True
        self.assertNotIn(99, coord.step_complete)

    def test_completed_steps_view_is_live_for_internal_consumers(self) -> None:
        coord = FlowCoordinator(step_count=5)
        view = coord.completed_steps
        self.assertEqual(view, {})
        coord.advance()
        self.assertTrue(view[0])


if __name__ == "__main__":
    unittest.main()
