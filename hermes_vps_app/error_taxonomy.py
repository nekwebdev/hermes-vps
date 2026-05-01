# pyright: reportUnknownArgumentType=false, reportUnknownVariableType=false
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import NoReturn

from hermes_control_core import (
    ActionGraph,
    CommandFailed,
    CommandNotFound,
    CommandTimeout,
    EngineResult,
    OutputLimitExceeded,
    RedactionError,
    RunnerDetectionError,
    RunnerUnavailable,
)
from hermes_control_core.actions import redact_text


class ErrorCategory(Enum):
    SUCCESS = "success"
    USAGE_CONFIG_ERROR = "usage_config_error"
    PREFLIGHT_FAILURE = "preflight_failure"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    COMMAND_FAILURE = "command_failure"
    COMMAND_TIMEOUT = "command_timeout"
    DESTRUCTIVE_APPROVAL_DENIED = "destructive_approval_denied"
    HOST_OVERRIDE_DENIED = "host_override_denied"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    REDACTION_ERROR = "redaction_error"
    INTERNAL_ERROR = "internal_error"


EXIT_CODES: dict[ErrorCategory, int] = {
    ErrorCategory.SUCCESS: 0,
    ErrorCategory.USAGE_CONFIG_ERROR: 10,
    ErrorCategory.PREFLIGHT_FAILURE: 20,
    ErrorCategory.RUNNER_UNAVAILABLE: 30,
    ErrorCategory.COMMAND_FAILURE: 40,
    ErrorCategory.COMMAND_TIMEOUT: 41,
    ErrorCategory.DESTRUCTIVE_APPROVAL_DENIED: 42,
    ErrorCategory.HOST_OVERRIDE_DENIED: 43,
    ErrorCategory.OUTPUT_LIMIT_EXCEEDED: 50,
    ErrorCategory.REDACTION_ERROR: 60,
    ErrorCategory.INTERNAL_ERROR: 99,
}

RECOVERY_GUIDANCE: dict[ErrorCategory, str] = {
    ErrorCategory.SUCCESS: "No recovery needed.",
    ErrorCategory.USAGE_CONFIG_ERROR: "Fix CLI arguments or provider configuration, then rerun the command.",
    ErrorCategory.PREFLIGHT_FAILURE: "Fix local preflight inputs such as .env permissions and provider directories, then rerun.",
    ErrorCategory.RUNNER_UNAVAILABLE: "Activate the project toolchain or install nix/docker before rerunning.",
    ErrorCategory.COMMAND_FAILURE: "Inspect the failed action, fix the underlying tool error, then rerun the failed scope.",
    ErrorCategory.COMMAND_TIMEOUT: "Increase readiness or command timeout budget, then rerun the failed scope.",
    ErrorCategory.DESTRUCTIVE_APPROVAL_DENIED: "Review the destroy preview and pass the exact approval flag only if destruction is intended.",
    ErrorCategory.HOST_OVERRIDE_DENIED: "Use a hermetic runner, or provide the audited host override token and reason.",
    ErrorCategory.OUTPUT_LIMIT_EXCEEDED: "Reduce command output or raise the configured output cap before rerunning.",
    ErrorCategory.REDACTION_ERROR: "Stop and fix redaction configuration before rerunning to avoid leaking secrets.",
    ErrorCategory.INTERNAL_ERROR: "Rerun with logs; if it repeats, file an internal bug with sanitized context.",
}

_SECRET_PATTERNS = [
    re.compile(r"(I-ACK-HOST-OVERRIDE|DESTROY:[A-Za-z0-9_.:-]+)"),
    re.compile(r"(?i)(token|secret|api[_-]?key|password)=([^\s]+)"),
    re.compile(r"(?i)(super-secret-[A-Za-z0-9_.:-]+)"),
]


@dataclass(frozen=True)
class CliError:
    category: ErrorCategory
    message: str
    workflow: str | None = None
    graph_id: str | None = None
    action_id: str | None = None
    action_status: str | None = None
    repair_scope: str | None = None
    runner_selection: dict[str, str] | None = None

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.category]

    @property
    def guidance(self) -> str:
        return RECOVERY_GUIDANCE[self.category]

    def to_dict(self) -> dict[str, object]:
        error: dict[str, object] = {
            "category": self.category.value,
            "exit_code": self.exit_code,
            "message": sanitize_error_text(self.message),
            "guidance": self.guidance,
        }
        if self.workflow is not None:
            error["workflow"] = self.workflow
        if self.graph_id is not None:
            error["graph"] = {"id": self.graph_id}
        if self.action_id is not None:
            error["action"] = {"id": self.action_id, "status": self.action_status or "failed"}
        if self.repair_scope is not None:
            error["repair_scope"] = self.repair_scope
        if self.runner_selection is not None:
            error["runner_selection"] = dict(self.runner_selection)
        return {"error": error, "redactions": {"applied": True, "marker": "***"}}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def to_human_lines(self) -> list[str]:
        context: list[str] = []
        if self.workflow is not None:
            context.append(f"workflow={self.workflow}")
        if self.graph_id is not None:
            context.append(f"graph={self.graph_id}")
        if self.action_id is not None:
            context.append(f"action={self.action_id}")
        if self.repair_scope is not None:
            context.append(f"repair_scope={self.repair_scope}")
        if self.runner_selection is not None:
            context.append(f"runner={self.runner_selection.get('mode', '')}")
        suffix = " " + " ".join(context) if context else ""
        return [
            f"error: category={self.category.value} exit_code={self.exit_code}{suffix}",
            f"detail: {sanitize_error_text(self.message)}",
            f"recovery: {self.guidance}",
        ]


class CliGraphFailure(RuntimeError):
    result: EngineResult
    graph: ActionGraph
    workflow: str

    def __init__(self, result: EngineResult, graph: ActionGraph, workflow: str) -> None:
        super().__init__(f"{workflow} graph failed")
        self.result = result
        self.graph = graph
        self.workflow = workflow


def sanitize_error_text(text: str) -> str:
    sanitized = redact_text(text)
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)(token"):
            sanitized = pattern.sub(lambda match: f"{match.group(1)}=***", sanitized)
        else:
            sanitized = pattern.sub("***", sanitized)
    return sanitized


def graph_failure_from_result(*, workflow: str, graph: ActionGraph, result: EngineResult) -> CliError:
    failed_action_id = next((aid for aid, state in result.states.items() if state.last_error), None)
    if failed_action_id is None:
        return CliError(
            category=ErrorCategory.INTERNAL_ERROR,
            message=f"{workflow} graph failed without a classified action error",
            workflow=workflow,
            graph_id=result.graph_name,
            repair_scope="rerun full panel",
        )
    failed_state = result.states[failed_action_id]
    descriptor = graph.actions[failed_action_id]
    detail = failed_state.last_error or f"{workflow} graph failed"
    category = _category_from_message(detail)
    if category == ErrorCategory.INTERNAL_ERROR and failed_action_id:
        category = ErrorCategory.COMMAND_FAILURE
    return CliError(
        category=category,
        message=detail,
        workflow=workflow,
        graph_id=result.graph_name,
        action_id=failed_action_id,
        action_status=failed_state.status.value,
        repair_scope=_repair_scope_from_hint(descriptor.repair_hint) or _default_repair_scope(failed_action_id),
    )


def classify_exception(exc: BaseException, *, workflow: str | None = None) -> CliError:
    if isinstance(exc, CliGraphFailure):
        return graph_failure_from_result(workflow=exc.workflow, graph=exc.graph, result=exc.result)
    category = _category_from_exception(exc)
    return CliError(
        category=category,
        message=str(exc) or exc.__class__.__name__,
        workflow=workflow,
        repair_scope=_exception_repair_scope(category, workflow),
        runner_selection=_runner_selection_from_exception(exc),
    )


def _runner_selection_from_exception(exc: BaseException) -> dict[str, str] | None:
    selection = getattr(exc, "selection", None)
    to_dict = getattr(selection, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
        if isinstance(raw, dict):
            return {str(key): str(value) for key, value in raw.items()}
    if isinstance(selection, dict):
        return {str(key): str(value) for key, value in selection.items()}
    return None


def raise_graph_failure(*, result: EngineResult, graph: ActionGraph, workflow: str) -> NoReturn:
    raise CliGraphFailure(result=result, graph=graph, workflow=workflow)


def _category_from_exception(exc: BaseException) -> ErrorCategory:
    if isinstance(exc, RedactionError):
        return ErrorCategory.REDACTION_ERROR
    message = str(exc).lower()
    if "host override" in message or "host runner override" in message:
        return ErrorCategory.HOST_OVERRIDE_DENIED
    if isinstance(exc, PermissionError):
        if "destructive approval" in message:
            return ErrorCategory.DESTRUCTIVE_APPROVAL_DENIED
        return ErrorCategory.USAGE_CONFIG_ERROR
    if isinstance(exc, (RunnerDetectionError, RunnerUnavailable, CommandNotFound)):
        return ErrorCategory.RUNNER_UNAVAILABLE
    if isinstance(exc, CommandTimeout):
        return ErrorCategory.COMMAND_TIMEOUT
    if isinstance(exc, OutputLimitExceeded):
        return ErrorCategory.OUTPUT_LIMIT_EXCEEDED
    if isinstance(exc, RedactionError):
        return ErrorCategory.REDACTION_ERROR
    if isinstance(exc, CommandFailed):
        return ErrorCategory.COMMAND_FAILURE
    if isinstance(exc, ValueError):
        if "provider must be" in message or "unsupported action" in message:
            return ErrorCategory.USAGE_CONFIG_ERROR
        return ErrorCategory.PREFLIGHT_FAILURE
    return ErrorCategory.INTERNAL_ERROR


def _category_from_message(message: str) -> ErrorCategory:
    lowered = message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return ErrorCategory.COMMAND_TIMEOUT
    if "output exceeded" in lowered or "output limit" in lowered:
        return ErrorCategory.OUTPUT_LIMIT_EXCEEDED
    if "redaction" in lowered:
        return ErrorCategory.REDACTION_ERROR
    if "runner" in lowered and "unavailable" in lowered:
        return ErrorCategory.RUNNER_UNAVAILABLE
    if "command failed" in lowered or "command exited" in lowered or "failed to resolve" in lowered or "remote" in lowered:
        return ErrorCategory.COMMAND_FAILURE
    return ErrorCategory.INTERNAL_ERROR


def _exception_repair_scope(category: ErrorCategory, workflow: str | None) -> str | None:
    if workflow is None:
        return None
    if category == ErrorCategory.PREFLIGHT_FAILURE:
        return f"fix local preflight inputs and rerun {workflow}"
    if category == ErrorCategory.USAGE_CONFIG_ERROR:
        return f"fix invocation/configuration and rerun {workflow}"
    if category == ErrorCategory.RUNNER_UNAVAILABLE:
        return f"restore runner and rerun {workflow}"
    if category == ErrorCategory.DESTRUCTIVE_APPROVAL_DENIED:
        return "review destroy preview; rerun destroy with explicit approval if intended"
    if category == ErrorCategory.HOST_OVERRIDE_DENIED:
        return f"rerun {workflow} in hermetic runner or with audited host override"
    return f"rerun {workflow} after repair"


def _default_repair_scope(action_id: str) -> str:
    if action_id:
        return "failed node"
    return "full panel"


def _repair_scope_from_hint(repair_hint: str | None) -> str | None:
    if repair_hint is None:
        return None
    normalized = repair_hint.strip().lower()
    if "subtree" in normalized:
        return "failed subtree"
    if "full panel" in normalized or "full" in normalized:
        return "full panel"
    if "node" in normalized:
        return "failed node"
    return repair_hint
