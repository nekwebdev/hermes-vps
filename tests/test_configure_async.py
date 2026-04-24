"""Pure unit tests for CorrelatedTask.

CorrelatedTask is the central stale-drop primitive used across cloud,
hermes-metadata, hermes-api-key and telegram async dispatches. Each
dispatch begins() to claim a fresh sequence number; replies that don't
carry that id are dropped at the handler boundary.
"""

from __future__ import annotations

import unittest

from scripts.configure_async import CorrelatedTask


class CorrelatedTaskTests(unittest.TestCase):
    def test_initial_state_is_inactive_with_zero_active_id(self) -> None:
        task = CorrelatedTask()
        self.assertEqual(task.active_id, 0)

    def test_begin_increments_and_returns_new_id(self) -> None:
        task = CorrelatedTask()
        first = task.begin()
        second = task.begin()
        self.assertEqual(first, 1)
        self.assertEqual(second, 2)
        self.assertEqual(task.active_id, 2)

    def test_is_current_only_matches_latest_begin(self) -> None:
        task = CorrelatedTask()
        first = task.begin()
        second = task.begin()
        self.assertFalse(task.is_current(first))
        self.assertTrue(task.is_current(second))

    def test_is_current_rejects_zero_when_active_is_set(self) -> None:
        task = CorrelatedTask()
        task.begin()
        self.assertFalse(task.is_current(0))

    def test_is_current_accepts_zero_at_initial_state(self) -> None:
        task = CorrelatedTask()
        self.assertTrue(task.is_current(0))

    def test_force_active_pins_active_id_without_bumping_sequence(self) -> None:
        task = CorrelatedTask()
        task.force_active(7)
        self.assertEqual(task.active_id, 7)
        next_id = task.begin()
        # begin still continues from sequence, not from forced id
        self.assertEqual(next_id, 1)
        self.assertEqual(task.active_id, 1)

    def test_cancel_clears_active_so_no_id_matches_the_active_load(self) -> None:
        task = CorrelatedTask()
        request_id = task.begin()
        task.cancel()
        self.assertEqual(task.active_id, 0)
        self.assertFalse(task.is_current(request_id))


if __name__ == "__main__":
    unittest.main()
