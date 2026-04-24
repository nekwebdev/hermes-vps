"""Wizard navigation core.

FlowCoordinator owns the step index and the per-step completion map.
It is intentionally framework-free so it can be unit-tested without
Textual and reused by future control-panel surfaces.

Design rules:
* All step transitions return a TransitionResult so callers don't have
  to reach back into the coordinator to learn what changed.
* advance() implicitly marks the previous step complete; that pairing
  reflects the wizard's existing semantics (a step is "done" exactly
  when the user successfully navigates forward off it).
* back() never alters completion state.
* jump_to() is the imperative escape hatch used by the App's reactive
  watcher when external code (tests, future deep-links) sets
  current_step directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransitionResult:
    next_step: int
    step_complete: bool
    finished: bool = False


class FlowCoordinator:
    def __init__(self, step_count: int, current: int = 0) -> None:
        if step_count <= 0:
            raise ValueError("step_count must be positive")
        if current < 0 or current >= step_count:
            raise ValueError(
                f"current step {current} out of range [0, {step_count})"
            )
        self._step_count = step_count
        self._current = current
        self._complete: dict[int, bool] = {}

    @property
    def current_step(self) -> int:
        return self._current

    @property
    def step_complete(self) -> dict[int, bool]:
        return dict(self._complete)

    @property
    def completed_steps(self) -> dict[int, bool]:
        return self._complete

    def at_first_step(self) -> bool:
        return self._current == 0

    def at_last_step(self) -> bool:
        return self._current == self._step_count - 1

    def advance(self) -> TransitionResult:
        self._complete[self._current] = True
        if self.at_last_step():
            return TransitionResult(
                next_step=self._current, step_complete=True, finished=True
            )
        self._current += 1
        return TransitionResult(next_step=self._current, step_complete=True)

    def back(self) -> TransitionResult:
        if self.at_first_step():
            return TransitionResult(next_step=self._current, step_complete=False)
        self._current -= 1
        return TransitionResult(next_step=self._current, step_complete=False)

    def jump_to(self, step: int) -> TransitionResult:
        if step < 0 or step >= self._step_count:
            raise ValueError(
                f"step {step} out of range [0, {self._step_count})"
            )
        self._current = step
        return TransitionResult(next_step=step, step_complete=False)
