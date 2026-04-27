# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
"""Wizard-specific step controller base.

Inherits the generic StepController from wizard_framework and adds the
two shortcuts every wizard step needs (`state` -> WizardState,
`orchestrator` -> ConfigureOrchestrator). Concrete step controllers
(review, server, telegram, ...) inherit from this class.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Protocol, TypeVar

from scripts.wizard_framework.step import StepController as _GenericStepController

if TYPE_CHECKING:
    from scripts.configure_services import ConfigureOrchestrator
    from scripts.configure_state import LabeledValue, WizardState

T = TypeVar("T")


class ConfigureStepAppLike(Protocol):
    state: "WizardState"
    orchestrator: "ConfigureOrchestrator"
    root_dir: pathlib.Path
    location_options: list["LabeledValue"]
    server_type_options: list["LabeledValue"]

    def query_one(self, selector: str, expect_type: type[T]) -> T: ...


class StepController(_GenericStepController):
    app: ConfigureStepAppLike

    @property
    def state(self) -> "WizardState":
        return self.app.state

    @property
    def orchestrator(self) -> "ConfigureOrchestrator":
        return self.app.orchestrator
