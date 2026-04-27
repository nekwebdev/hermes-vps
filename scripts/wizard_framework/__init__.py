"""Reusable wizard primitives.

Seed for the future control-panel TUI surface. The underlying
implementations currently live in scripts/configure_flow.py,
scripts/configure_async.py, and scripts/configure_steps/_base.py
for backwards compatibility with existing imports — those modules
are slim and stable. New consumers should import from this package.
"""

from __future__ import annotations

from scripts.configure_async import CorrelatedTask
from scripts.configure_flow import FlowCoordinator, TransitionResult
from scripts.wizard_framework.registry import StepRegistry
from scripts.wizard_framework.step import StepController

__all__ = [
    "CorrelatedTask",
    "FlowCoordinator",
    "StepController",
    "StepRegistry",
    "TransitionResult",
]
