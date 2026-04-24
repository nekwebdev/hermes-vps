"""Per-step controllers for the configure wizard.

Cloud and Hermes are intentionally not yet extracted: their UI/state
mutations are entangled with async loading state and will be folded out
together with the request-id correlation rework in Batch 4.
"""

from __future__ import annotations

from scripts.configure_steps._base import StepController
from scripts.configure_steps.review import ReviewStepController
from scripts.configure_steps.server import ServerStepController
from scripts.configure_steps.telegram import TelegramStepController

EXTRACTED_CONTROLLERS: tuple[type[StepController], ...] = (
    ReviewStepController,
    ServerStepController,
    TelegramStepController,
)

__all__ = [
    "EXTRACTED_CONTROLLERS",
    "ReviewStepController",
    "ServerStepController",
    "StepController",
    "TelegramStepController",
]
