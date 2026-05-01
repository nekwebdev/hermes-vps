from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_control_core.actions import sanitize_for_schema
from hermes_control_core.interfaces import RunnerMode


@dataclass(frozen=True)
class RunnerSelectionAudit:
    mode: RunnerMode
    reason: str
    lock_scope: str = "per-launch"
    guidance: str = "Runner is locked for this process launch."
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class DestructiveApprovalAudit:
    action_id: str
    approved: bool
    approved_by: str
    token_used: str | None = None
    flag_used: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    approved_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class RedactionAudit:
    action_id: str
    redactions_applied: bool
    redaction_errors: list[str] = field(default_factory=list)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SessionAuditLog:
    session_id: str
    repo_root: Path
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    runner_selection: RunnerSelectionAudit | None = None
    destructive_approvals: list[DestructiveApprovalAudit] = field(default_factory=list)
    redactions: list[RedactionAudit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def set_runner_selection(
        self,
        mode: RunnerMode,
        reason: str,
        lock_scope: str = "per-launch",
        guidance: str = "Runner is locked for this process launch.",
    ) -> None:
        self.runner_selection = RunnerSelectionAudit(
            mode=mode,
            reason=reason,
            lock_scope=lock_scope,
            guidance=guidance,
        )

    def add_destructive_approval(
        self,
        action_id: str,
        approved: bool,
        approved_by: str,
        token_used: str | None = None,
        flag_used: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.destructive_approvals.append(
            DestructiveApprovalAudit(
                action_id=action_id,
                approved=approved,
                approved_by=approved_by,
                token_used=token_used,
                flag_used=flag_used,
                details=details or {},
            )
        )

    def add_redaction_record(
        self,
        action_id: str,
        redactions_applied: bool,
        redaction_errors: list[str] | None = None,
    ) -> None:
        self.redactions.append(
            RedactionAudit(
                action_id=action_id,
                redactions_applied=redactions_applied,
                redaction_errors=redaction_errors or [],
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "repo_root": str(self.repo_root),
            "created_at": self.created_at.isoformat(),
            "runner_selection": None
            if self.runner_selection is None
            else {
                "mode": self.runner_selection.mode,
                "reason": sanitize_for_schema(self.runner_selection.reason),
                "lock_scope": self.runner_selection.lock_scope,
                "guidance": self.runner_selection.guidance,
                "detected_at": self.runner_selection.detected_at.isoformat(),
            },
            "destructive_approvals": [
                {
                    "action_id": item.action_id,
                    "approved": item.approved,
                    "approved_by": sanitize_for_schema(item.approved_by),
                    "token_used": sanitize_for_schema(item.token_used),
                    "flag_used": item.flag_used,
                    "details": sanitize_for_schema(item.details),
                    "approved_at": item.approved_at.isoformat(),
                }
                for item in self.destructive_approvals
            ],
            "redactions": [
                {
                    "action_id": item.action_id,
                    "redactions_applied": item.redactions_applied,
                    "redaction_errors": sanitize_for_schema(item.redaction_errors),
                    "recorded_at": item.recorded_at.isoformat(),
                }
                for item in self.redactions
            ],
            "metadata": sanitize_for_schema(self.metadata),
        }
