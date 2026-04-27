# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
"""Generic step-controller base.

Application-agnostic. Subclasses declare a unique `key`, build the UI
in `mount(form)`, and (optionally) read user input via `capture() -> bool`
and report local errors via `validate() -> dict[str, str]`.

The framework holds the `app` reference opaquely: the controller knows
which app-specific fields/services it needs and reaches into them
directly. Wizard-specific shortcuts (e.g. `state`, `orchestrator`)
belong in the per-application subclass, not here.
"""

from __future__ import annotations

class StepController:
    key: str = ""

    def __init__(self, app: object) -> None:
        self.app = app

    def mount(self, _form: object) -> None:
        raise NotImplementedError

    def capture(self) -> bool:
        return True

    def validate(self) -> dict[str, str]:
        return {}
