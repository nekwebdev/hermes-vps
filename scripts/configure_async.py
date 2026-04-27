"""Async correlation primitives for the configure wizard.

Each long-running dispatch (cloud metadata fetch, hermes provider/model
load, hermes API-key validation, telegram getMe call) gets its own
CorrelatedTask instance. The dispatcher calls begin() to claim the next
sequence number and threads it through the worker into the reply
message; the handler drops the message at the boundary if it doesn't
match the latest active id.

This collapses ad-hoc per-task flags (`_pending_*`, manual sequence
counters, provider-name comparisons) into one uniform staleness rule.
"""

from __future__ import annotations

from typing import final


@final
class CorrelatedTask:
    def __init__(self) -> None:
        self._seq = 0
        self._active_id = 0

    @property
    def active_id(self) -> int:
        return self._active_id

    def begin(self) -> int:
        self._seq += 1
        self._active_id = self._seq
        return self._seq

    def is_current(self, request_id: int) -> bool:
        return request_id == self._active_id

    def cancel(self) -> None:
        self._active_id = 0

    def force_active(self, request_id: int) -> None:
        """Test hook: pin active_id without bumping the sequence counter."""
        self._active_id = request_id
