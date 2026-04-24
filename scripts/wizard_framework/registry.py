"""Step controller registry.

Wraps the dispatcher's controller dict in a small typed API so a second
consumer can plug in step controllers without poking at the wizard's
private attributes.
"""

from __future__ import annotations

from scripts.wizard_framework.step import StepController


class StepRegistry:
    def __init__(self) -> None:
        self._controllers: dict[str, StepController] = {}

    def register(self, controller: StepController) -> None:
        if controller.key in self._controllers:
            raise ValueError(
                f"step controller already registered for key {controller.key!r}"
            )
        self._controllers[controller.key] = controller

    def get(self, key: str) -> StepController | None:
        return self._controllers.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self._controllers

    def __len__(self) -> int:
        return len(self._controllers)

    def keys(self) -> list[str]:
        return list(self._controllers.keys())
