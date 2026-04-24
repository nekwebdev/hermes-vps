"""Wizard-specific step controller base.

Inherits the generic StepController from wizard_framework and adds the
two shortcuts every wizard step needs (`state` -> WizardState,
`orchestrator` -> ConfigureOrchestrator). Concrete step controllers
(review, server, telegram, ...) inherit from this class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.wizard_framework.step import StepController as _GenericStepController

if TYPE_CHECKING:
    from scripts.configure_services import ConfigureOrchestrator
    from scripts.configure_state import WizardState


class StepController(_GenericStepController):
    @property
    def state(self) -> "WizardState":
        return self.app.state

    @property
    def orchestrator(self) -> "ConfigureOrchestrator":
        return self.app.orchestrator
