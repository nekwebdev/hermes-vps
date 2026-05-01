# pyright: reportAny=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
import re
from typing import Any, cast

from hermes_control_core.interfaces import SideEffectLevel

REDACTION_MARKER = "***"
ACTION_RESULT_SCHEMA = "hermes.action_result.v1"
ACTION_EVENT_SCHEMA = "hermes.action_event.v1"
OUTPUT_TAIL_BYTES = 4096
SIDE_EFFECT_LEVELS: set[str] = {"none", "low", "high", "destructive"}
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY|RUNTIME_ENV)[A-Z0-9_]*\s*=\s*)([^\s]+)"
)
_SECRET_JSON_FIELD_RE = re.compile(
    r'(?i)("[^"]*(?:token|secret|password|api[_-]?key|private[_-]?key|runtime[_-]?env)[^"]*"\s*:\s*")([^"]+)(")'
)
_STANDALONE_SECRET_REPLACEMENTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"I-ACK-HOST-OVERRIDE(?:-[A-Za-z0-9_.:-]+)?"),
    re.compile(r"DESTROY:[A-Za-z0-9_.:-]+"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9_.-]+\b"),
    re.compile(r"(?i)\bsuper-secret-[A-Za-z0-9_.:-]+\b"),
)


class ActionStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class RetryPolicyKind(str, Enum):
    NONE = "none"
    FIXED = "fixed"
    BACKOFF = "backoff"


@dataclass(frozen=True)
class RetryPolicy:
    kind: RetryPolicyKind = RetryPolicyKind.NONE
    max_attempts: int = 1
    delay_seconds: float = 0.0


@dataclass(frozen=True)
class ActionDescriptor:
    action_id: str
    label: str
    deps: list[str] = field(default_factory=list)
    side_effect_level: SideEffectLevel = "low"
    timeout_s: float | None = None
    allow_failure: bool = False
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    preconditions: list[str] = field(default_factory=list)
    rollback_hint: str | None = None
    repair_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionRuntimeState:
    action_id: str
    status: ActionStatus = ActionStatus.PENDING
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class ActionEvent:
    action_id: str
    status: ActionStatus
    at: datetime
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    action_label: str | None = None
    runner_mode: str | None = None
    redactions_applied: bool = True

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": ACTION_EVENT_SCHEMA,
            "action": {"id": self.action_id, "label": self.action_label or self.action_id},
            "status": self.status.value,
            "timestamp": self.at.isoformat(),
            "message": self.message,
            "details": sanitize_for_schema(self.details),
            "redactions": {"applied": self.redactions_applied, "marker": REDACTION_MARKER},
        }
        if self.runner_mode is not None:
            payload["runner_mode"] = self.runner_mode
        return payload


@dataclass(frozen=True)
class ActionGraph:
    name: str
    actions: dict[str, ActionDescriptor]
    policy_gate_enabled: bool = False

    def validate(self) -> None:
        _validate_graph(self.actions)
        if self.policy_gate_enabled:
            _validate_policy_gate(self.actions)


@dataclass(frozen=True)
class GraphSnapshot:
    graph_name: str
    states: dict[str, ActionRuntimeState]
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _validate_graph(actions: dict[str, ActionDescriptor]) -> None:
    for action_id, descriptor in actions.items():
        if descriptor.action_id != action_id:
            raise ValueError(
                f"action key {action_id!r} does not match descriptor.action_id {descriptor.action_id!r}"
            )

    for descriptor in actions.values():
        for dep in descriptor.deps:
            if dep not in actions:
                raise ValueError(
                    f"action {descriptor.action_id!r} depends on unknown action {dep!r}"
                )

    # cycle check (DFS coloring)
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise ValueError(f"cycle detected at action {node!r}")
        visiting.add(node)
        for dep in actions[node].deps:
            dfs(dep)
        visiting.remove(node)
        visited.add(node)

    for node in actions:
        dfs(node)


def _validate_policy_gate(actions: dict[str, ActionDescriptor]) -> None:
    for descriptor in actions.values():
        raw_policy = descriptor.metadata.get("policy")
        if not isinstance(raw_policy, dict):
            raise ValueError(
                f"action {descriptor.action_id!r} missing policy metadata: add metadata['policy'] with side_effect_level, command_backed, timeout, and approval fields"
            )
        policy = cast(dict[str, object], raw_policy)

        declared_side_effect = policy.get("side_effect_level")
        if declared_side_effect not in SIDE_EFFECT_LEVELS:
            raise ValueError(
                f"action {descriptor.action_id!r} has invalid policy side_effect_level {declared_side_effect!r}; expected one of {sorted(SIDE_EFFECT_LEVELS)!r}"
            )
        if declared_side_effect != descriptor.side_effect_level:
            raise ValueError(
                f"action {descriptor.action_id!r} policy side_effect_level {declared_side_effect!r} does not match descriptor side_effect_level {descriptor.side_effect_level!r}"
            )

        if descriptor.side_effect_level == "destructive" and policy.get("approval_required") is not True:
            raise ValueError(
                f"destructive action {descriptor.action_id!r} missing approval policy metadata: set metadata['policy']['approval_required']=True"
            )

        if policy.get("command_backed") is True and descriptor.side_effect_level != "none":
            timeout_policy = policy.get("timeout")
            if descriptor.timeout_s is not None:
                if timeout_policy != "bounded":
                    raise ValueError(
                        f"action {descriptor.action_id!r} has timeout_s but missing bounded timeout policy: set metadata['policy']['timeout']='bounded'"
                    )
                continue

            if timeout_policy == "no_timeout":
                if descriptor.side_effect_level == "destructive":
                    raise ValueError(
                        f"destructive action {descriptor.action_id!r} cannot opt out of timeout bounds"
                    )
                if policy.get("no_timeout_reason"):
                    continue
                raise ValueError(
                    f"action {descriptor.action_id!r} opts out of timeout bounds without a documented exception: set metadata['policy']['no_timeout_reason']"
                )

            raise ValueError(
                f"state-changing command-backed action {descriptor.action_id!r} missing timeout intent: set timeout_s with metadata['policy']['timeout']='bounded' or document a non-destructive no_timeout exception"
            )


def initial_runtime_states(graph: ActionGraph) -> dict[str, ActionRuntimeState]:
    graph.validate()
    return {aid: ActionRuntimeState(action_id=aid) for aid in graph.actions.keys()}


def is_terminal(status: ActionStatus) -> bool:
    return status in {
        ActionStatus.SUCCEEDED,
        ActionStatus.FAILED,
        ActionStatus.SKIPPED,
        ActionStatus.CANCELLED,
    }


def ready_actions(
    graph: ActionGraph,
    states: dict[str, ActionRuntimeState],
) -> list[ActionDescriptor]:
    ready: list[ActionDescriptor] = []
    for aid, action in graph.actions.items():
        state = states.get(aid)
        if state is None:
            continue
        if state.status not in {ActionStatus.PENDING, ActionStatus.READY}:
            continue

        dep_states = [states.get(dep) for dep in action.deps]
        if any(ds is None for ds in dep_states):
            continue

        if all(ds is not None and ds.status == ActionStatus.SUCCEEDED for ds in dep_states):
            ready.append(action)
            continue

        if any(ds is not None and ds.status in {ActionStatus.FAILED, ActionStatus.CANCELLED} for ds in dep_states):
            state.status = ActionStatus.BLOCKED

    return ready


def normalize_action_result(raw: dict[str, Any], *, default_kind: str = "preflight") -> dict[str, Any]:
    """Return the documented internal action result summary schema.

    Schema v1 is intentionally internal (not a plugin API) and small enough for graph
    execution, CLI JSON, and panel status renderers to share safely:
    schema/kind/ok/runner_mode/redactions plus bounded command output tails when present.
    """
    if raw.get("schema") == ACTION_RESULT_SCHEMA:
        return sanitize_for_schema(raw)

    kind = str(raw.get("kind") or default_kind)
    ok = bool(raw.get("ok", True))
    redactions_applied = bool(raw.get("redactions_applied", True))
    normalized: dict[str, Any] = {
        "schema": ACTION_RESULT_SCHEMA,
        "kind": kind,
        "ok": ok,
        "redactions": {"applied": redactions_applied, "marker": REDACTION_MARKER},
    }

    runner_mode = raw.get("runner_mode")
    if runner_mode is not None:
        normalized["runner_mode"] = str(runner_mode)
    if "exit_code" in raw:
        normalized["exit_code"] = int(raw.get("exit_code") or 0)
    if "command" in raw:
        command = raw.get("command")
        normalized["command"] = sanitize_for_schema([str(part) for part in command] if isinstance(command, list) else str(command))

    if kind == "command" or "stdout" in raw or "stderr" in raw:
        stdout_tail, stdout_truncated = bounded_output_tail(str(raw.get("stdout") or ""))
        stderr_tail, stderr_truncated = bounded_output_tail(str(raw.get("stderr") or ""))
        normalized["kind"] = "command"
        normalized["output"] = {
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "truncated": bool(raw.get("output_truncated", False)) or stdout_truncated or stderr_truncated,
            "tail_bytes": OUTPUT_TAIL_BYTES,
        }

    details = {
        key: value
        for key, value in raw.items()
        if key
        not in {
            "kind",
            "ok",
            "redactions_applied",
            "runner_mode",
            "exit_code",
            "command",
            "stdout",
            "stderr",
            "output_truncated",
            "schema",
        }
    }
    if details:
        safe_details = sanitize_for_schema(details)
        normalized["details"] = safe_details
        if isinstance(safe_details, dict):
            normalized.update(safe_details)
    return normalized


def bounded_output_tail(text: str, *, limit_bytes: int = OUTPUT_TAIL_BYTES) -> tuple[str, bool]:
    redacted = redact_text(text)
    encoded = redacted.encode("utf-8", errors="replace")
    if len(encoded) <= limit_bytes:
        return redacted, False
    tail = encoded[-limit_bytes:].decode("utf-8", errors="replace")
    return tail, True


def redact_text(text: str) -> str:
    redacted = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{REDACTION_MARKER}", text)
    redacted = _SECRET_JSON_FIELD_RE.sub(lambda match: f"{match.group(1)}{REDACTION_MARKER}{match.group(3)}", redacted)
    for pattern in _STANDALONE_SECRET_REPLACEMENTS:
        redacted = pattern.sub(REDACTION_MARKER, redacted)
    return redacted


def sanitize_for_schema(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(key): sanitize_for_schema(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_for_schema(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_schema(item) for item in value]
    return value
