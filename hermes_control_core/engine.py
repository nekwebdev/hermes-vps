# pyright: reportAny=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from hermes_control_core.actions import (
    ActionDescriptor,
    ActionEvent,
    ActionGraph,
    ActionRuntimeState,
    ActionStatus,
    GraphSnapshot,
    RetryPolicyKind,
    initial_runtime_states,
    normalize_action_result,
    ready_actions,
    redact_text,
    sanitize_for_schema,
)
from hermes_control_core.interfaces import CommandFailed, Runner
from hermes_control_core.session import SessionAuditLog


class ActionHandler(Protocol):
    def run(
        self,
        action: ActionDescriptor,
        context: dict[str, Any],
        runner: Runner,
    ) -> dict[str, Any]:
        ...


class EventSink(Protocol):
    def emit(self, event: ActionEvent) -> None:
        ...


@dataclass(frozen=True)
class EngineResult:
    graph_name: str
    states: dict[str, ActionRuntimeState]
    completed: bool
    failed: bool
    cancelled: bool
    host_override: dict[str, object] | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_summary(self) -> dict[str, object]:
        summary: dict[str, object] = {
            "schema": "hermes.graph_result.v1",
            "graph": {"id": self.graph_name},
            "completed": self.completed,
            "failed": self.failed,
            "cancelled": self.cancelled,
        }
        if self.host_override is not None:
            summary["host_override"] = sanitize_for_schema(self.host_override)
        return summary


@dataclass
class Engine:
    graph: ActionGraph
    runner: Runner
    handler: ActionHandler
    event_sink: EventSink | None = None
    context: dict[str, Any] = field(default_factory=dict)
    audit_log: SessionAuditLog | None = None
    require_host_override_token: bool = True
    host_override_token: str | None = None

    def run(self) -> EngineResult:
        self.graph.validate()
        self._enforce_host_override_gate()
        states = initial_runtime_states(self.graph)

        while True:
            pending_or_ready = [
                st
                for st in states.values()
                if st.status in {ActionStatus.PENDING, ActionStatus.READY}
            ]
            running = [st for st in states.values() if st.status == ActionStatus.RUNNING]

            if not pending_or_ready and not running:
                break

            if running:
                # v1 executor is synchronous; RUNNING should not persist across loop turns.
                raise RuntimeError("unexpected RUNNING state in synchronous engine")

            current_ready = ready_actions(self.graph, states)
            if not current_ready:
                # nothing ready while unresolved states remain => blocked frontier
                break

            for action in current_ready:
                st = states[action.action_id]
                if st.status == ActionStatus.BLOCKED:
                    continue
                self._execute_one(action, states)

                if self._should_fail_fast(states):
                    return EngineResult(
                        graph_name=self.graph.name,
                        states=states,
                        completed=False,
                        failed=True,
                        cancelled=False,
                        host_override=self._host_override_summary(),
                    )

        failed = any(st.status == ActionStatus.FAILED for st in states.values())
        blocked = any(st.status == ActionStatus.BLOCKED for st in states.values())
        completed = not failed and not blocked and all(
            st.status
            in {
                ActionStatus.SUCCEEDED,
                ActionStatus.SKIPPED,
                ActionStatus.CANCELLED,
            }
            for st in states.values()
        )

        return EngineResult(
            graph_name=self.graph.name,
            states=states,
            completed=completed,
            failed=failed,
            cancelled=False,
            host_override=self._host_override_summary(),
        )

    def snapshot(self, states: dict[str, ActionRuntimeState]) -> GraphSnapshot:
        return GraphSnapshot(graph_name=self.graph.name, states=states)

    def _enforce_host_override_gate(self) -> None:
        if self.runner.mode != "host":
            return
        if not self.require_host_override_token:
            self._record_host_override_approval(True)
            return

        token = (self.host_override_token or "").strip()
        approved = token == "I-ACK-HOST-OVERRIDE"
        self._record_host_override_approval(approved)
        if not approved:
            raise PermissionError(
                "Host override denied before engine execution: provide the audited host override token and non-secret override reason."
            )

    def _record_host_override_approval(self, approved: bool) -> None:
        if self.audit_log is None:
            return
        override_reason = str(self.context.get("override_reason") or "").strip()
        details: dict[str, object] = {
            "runner_mode": "host",
            "token_provided": bool((self.host_override_token or "").strip()),
        }
        if override_reason:
            details["override_reason"] = override_reason
        if not approved:
            details["denial_reason"] = "missing_or_invalid_host_override_token"
        self.audit_log.add_destructive_approval(
            action_id="host_override_preflight",
            approved=approved,
            approved_by="engine_preflight",
            token_used=None,
            flag_used="allow_host_override",
            details=details,
        )

    def _host_override_summary(self) -> dict[str, object] | None:
        if self.runner.mode != "host":
            return None
        summary: dict[str, object] = {"approved": True, "runner_mode": "host"}
        override_reason = str(self.context.get("override_reason") or "").strip()
        if override_reason:
            summary["override_reason"] = override_reason
        return summary

    def _execute_one(
        self,
        action: ActionDescriptor,
        states: dict[str, ActionRuntimeState],
    ) -> None:
        st = states[action.action_id]

        max_attempts = max(1, action.retry_policy.max_attempts)
        st.status = ActionStatus.RUNNING
        st.started_at = datetime.now(UTC)
        self._emit(action, ActionStatus.RUNNING, "action started")

        attempts = 0
        last_error: Exception | None = None

        while attempts < max_attempts:
            attempts += 1
            st.attempts = attempts
            try:
                result = self.handler.run(action, self.context, self.runner)
                normalized_result = normalize_action_result(result)
                st.result = normalized_result
                st.status = ActionStatus.SUCCEEDED
                st.finished_at = datetime.now(UTC)
                st.last_error = None
                self._emit(action, ActionStatus.SUCCEEDED, "action succeeded", {"result": normalized_result})
                return
            except Exception as exc:  # typed handling can be refined incrementally
                last_error = exc
                st.last_error = self._exception_message(exc)
                failure_result = self._result_from_exception(exc)
                if failure_result is not None:
                    st.result = failure_result
                if not self._can_retry(action, attempts, exc):
                    break

        st.status = ActionStatus.FAILED
        st.finished_at = datetime.now(UTC)
        if last_error is not None:
            st.last_error = self._exception_message(last_error)
        self._emit(action, ActionStatus.FAILED, "action failed", {"error": st.last_error or "", "result": st.result or {}})

        if action.allow_failure:
            st.status = ActionStatus.SKIPPED
            self._emit(action, ActionStatus.SKIPPED, "failure tolerated by allow_failure")

    def _can_retry(self, action: ActionDescriptor, attempts: int, exc: Exception) -> bool:
        if attempts >= max(1, action.retry_policy.max_attempts):
            return False
        if action.retry_policy.kind == RetryPolicyKind.NONE:
            return False

        # v1 baseline: retry command failures and generic transient exceptions.
        if isinstance(exc, CommandFailed):
            return True
        return True

    def _should_fail_fast(self, states: dict[str, ActionRuntimeState]) -> bool:
        for aid, st in states.items():
            if st.status != ActionStatus.FAILED:
                continue
            descriptor = self.graph.actions[aid]
            if descriptor.allow_failure:
                continue
            return True
        return False

    def _emit(
        self,
        action: ActionDescriptor,
        status: ActionStatus,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self.event_sink is None:
            return
        result_details = details or {}
        event_result = result_details.get("result")
        redactions_applied = True
        if isinstance(event_result, dict):
            redactions = event_result.get("redactions")
            if isinstance(redactions, dict):
                redactions_applied = bool(redactions.get("applied", True))
        self.event_sink.emit(
            ActionEvent(
                action_id=action.action_id,
                status=status,
                at=datetime.now(UTC),
                message=message,
                details=result_details,
                action_label=action.label,
                runner_mode=self.runner.mode,
                redactions_applied=redactions_applied,
            )
        )

    def _exception_message(self, exc: Exception) -> str:
        if isinstance(exc, CommandFailed) and exc.args:
            first = exc.args[0]
            if isinstance(first, str) and first:
                return redact_text(first)
        return redact_text(str(exc))

    def _result_from_exception(self, exc: Exception) -> dict[str, Any] | None:
        if not isinstance(exc, CommandFailed):
            return None
        for arg in exc.args:
            exit_code = getattr(arg, "exit_code", None)
            stdout = getattr(arg, "stdout", None)
            stderr = getattr(arg, "stderr", None)
            runner_mode = getattr(arg, "runner_mode", None)
            output_truncated = getattr(arg, "output_truncated", False)
            redactions_applied = getattr(arg, "redactions_applied", True)
            if exit_code is None or stdout is None or stderr is None:
                continue
            return normalize_action_result(
                {
                    "kind": "command",
                    "ok": False,
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "output_truncated": output_truncated,
                    "runner_mode": runner_mode,
                    "redactions_applied": redactions_applied,
                }
            )
        return None
