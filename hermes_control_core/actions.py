from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from hermes_control_core.interfaces import SideEffectLevel


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


@dataclass(frozen=True)
class ActionGraph:
    name: str
    actions: dict[str, ActionDescriptor]

    def validate(self) -> None:
        _validate_graph(self.actions)


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
