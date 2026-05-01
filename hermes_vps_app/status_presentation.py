# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from hermes_control_core.actions import sanitize_for_schema
from hermes_control_core import ActionEvent, ActionGraph, EngineResult

REDACTION_MARKER = "***"


@dataclass(frozen=True)
class GraphPreviewActionPresentation:
    action_id: str
    label: str
    order: int
    side_effect_level: str
    deps: list[str]
    approval_required: bool
    repair_scope: str

    def to_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "label": self.label,
            "order": self.order,
            "side_effect_level": self.side_effect_level,
            "deps": self.deps,
            "approval_required": self.approval_required,
            "repair_scope": self.repair_scope,
        }


@dataclass(frozen=True)
class GraphPreviewPresentation:
    workflow: str
    graph_id: str
    actions: list[GraphPreviewActionPresentation]
    provider: str | None = None
    runner_mode: str | None = None
    destroy_preview: dict[str, object] | None = None
    redactions_applied: bool = True

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "workflow": self.workflow,
            "graph": {"id": self.graph_id},
            "redactions": {"applied": self.redactions_applied, "marker": REDACTION_MARKER},
            "actions": [action.to_dict() for action in self.actions],
        }
        if self.provider is not None:
            payload["provider"] = self.provider
        if self.runner_mode is not None:
            payload["runner_mode"] = self.runner_mode
        if self.destroy_preview is not None:
            payload["destroy_preview"] = sanitize_for_schema(self.destroy_preview)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def to_human_lines(self) -> list[str]:
        provider = f" provider={self.provider}" if self.provider else ""
        runner = f" runner={self.runner_mode}" if self.runner_mode else ""
        lines = [f"preview: workflow={self.workflow} graph={self.graph_id}{provider}{runner}"]
        for action in self.actions:
            deps = ",".join(action.deps) if action.deps else "none"
            approval = "yes" if action.approval_required else "no"
            line = (
                f"{action.order}. {action.action_id}: {action.label} "
                f"side_effect={action.side_effect_level} deps={deps} "
                f"approval_required={approval} repair_scope={action.repair_scope}"
            )
            lines.append(line)
        if self.destroy_preview is not None:
            preview = self.destroy_preview
            lines.append(
                "destroy_preview: "
                + f"provider={preview.get('provider')} tf_dir={preview.get('tf_dir')} "
                + f"backup_root={preview.get('backup_root')} backup_dir={preview.get('backup_dir')} "
                + f"state_files={preview.get('state_file_count')}"
            )
            state_files = preview.get("state_files", [])
            if isinstance(state_files, list):
                for state_file in cast(list[object], state_files):
                    lines.append(f"  - {state_file}")
            safe_outputs = preview.get("safe_outputs", {})
            if isinstance(safe_outputs, dict) and safe_outputs:
                lines.append("destroy_preview: safe_outputs")
                for key, value in sorted(cast(dict[str, object], safe_outputs).items()):
                    lines.append(f"  - {key}={value}")
        return lines


@dataclass(frozen=True)
class StatusActionPresentation:
    action_id: str
    label: str
    status: str
    runner_mode: str | None = None
    repair_scope: str | None = None
    error: str | None = None
    result: dict[str, object] | None = None
    redactions_applied: bool = True

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "action_id": self.action_id,
            "label": self.label,
            "status": self.status,
            "redactions_applied": self.redactions_applied,
        }
        if self.runner_mode is not None:
            payload["runner_mode"] = self.runner_mode
        if self.repair_scope is not None:
            payload["repair_scope"] = self.repair_scope
        if self.error is not None:
            payload["error"] = sanitize_for_schema(self.error)
        if self.result is not None:
            payload["result"] = sanitize_for_schema(self.result)
        return payload


@dataclass(frozen=True)
class StatusPresentation:
    workflow: str
    graph_id: str
    completed: bool
    actions: list[StatusActionPresentation]
    runner_mode: str | None = None
    redactions_applied: bool = True
    result_summary: dict[str, object] | None = None
    host_override: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "workflow": self.workflow,
            "graph": {"id": self.graph_id},
            "completed": self.completed,
            "redactions": {"applied": self.redactions_applied, "marker": REDACTION_MARKER},
            "actions": [action.to_dict() for action in self.actions],
        }
        if self.result_summary is not None:
            payload["result"] = sanitize_for_schema(self.result_summary)
        if self.runner_mode is not None:
            payload["runner_mode"] = self.runner_mode
        if self.host_override is not None:
            payload["host_override"] = sanitize_for_schema(self.host_override)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def to_human_lines(self) -> list[str]:
        runner = f" runner={self.runner_mode}" if self.runner_mode else ""
        lines = [f"{self.workflow}: graph={self.graph_id} completed={str(self.completed).lower()}{runner}"]
        for action in self.actions:
            action_runner = f" runner={action.runner_mode}" if action.runner_mode else ""
            repair = f" repair_scope={action.repair_scope}" if action.repair_scope else ""
            error = f" error={sanitize_for_schema(action.error)}" if action.error else ""
            backup = ""
            if action.result is not None:
                backup_payload = action.result.get("backup")
                if isinstance(backup_payload, dict):
                    typed_backup = cast(dict[str, object], backup_payload)
                    status = typed_backup.get("status")
                    path = typed_backup.get("path")
                    if status is not None:
                        backup += f" backup_status={str(status)}"
                    if path is not None:
                        backup += f" backup_path={str(path)}"
            lines.append(
                f"{action.action_id}: {action.status}{action_runner}{repair}{backup} redaction_marker={REDACTION_MARKER}{error}"
            )
        return lines


def presentation_from_engine_result(*, workflow: str, graph: ActionGraph, result: EngineResult) -> StatusPresentation:
    actions: list[StatusActionPresentation] = []
    runner_modes: list[str] = []
    redactions = True
    for action_id, state in sorted(result.states.items(), key=lambda item: item[0]):
        descriptor = graph.actions[action_id]
        state_result = cast(dict[str, object], state.result or {})
        runner_mode = _string_or_none(state_result.get("runner_mode"))
        if runner_mode is not None:
            runner_modes.append(runner_mode)
        redactions_payload = state_result.get("redactions")
        if isinstance(redactions_payload, dict):
            action_redactions = bool(redactions_payload.get("applied", True))
        else:
            action_redactions = bool(state_result.get("redactions_applied", True))
        redactions = redactions and action_redactions
        repair_scope = _repair_scope_for_descriptor(descriptor.repair_hint) if state.last_error or descriptor.repair_hint else None
        actions.append(
            StatusActionPresentation(
                action_id=action_id,
                label=descriptor.label,
                status=state.status.value,
                runner_mode=runner_mode,
                repair_scope=repair_scope,
                error=state.last_error,
                result=state_result,
                redactions_applied=action_redactions,
            )
        )
    return StatusPresentation(
        workflow=workflow,
        graph_id=result.graph_name,
        completed=result.completed,
        actions=actions,
        runner_mode=runner_modes[0] if runner_modes else None,
        redactions_applied=redactions,
        result_summary=result.to_summary(),
        host_override=result.host_override,
    )


def presentation_from_monitoring_payload(*, graph: ActionGraph, payload: dict[str, Any]) -> StatusPresentation:
    local_readiness = cast(dict[str, object], payload.get("local_readiness", {}))
    checks = cast(list[dict[str, object]], local_readiness.get("checks", []))
    by_id = {str(check.get("probe_id")): check for check in checks}
    actions: list[StatusActionPresentation] = []
    runner_modes: list[str] = []
    for action_id, descriptor in sorted(graph.actions.items(), key=lambda item: item[0]):
        check = by_id.get(action_id, {})
        severity = str(check.get("severity", "warn"))
        status = "succeeded" if severity == "ok" else "failed"
        runner_mode = _string_or_none(check.get("runner_mode"))
        if runner_mode is not None:
            runner_modes.append(runner_mode)
        repair_scope = _repair_scope_for_descriptor(descriptor.repair_hint) if status == "failed" else None
        actions.append(
            StatusActionPresentation(
                action_id=action_id,
                label=descriptor.label,
                status=status,
                runner_mode=runner_mode,
                repair_scope=repair_scope,
                error=None if status == "succeeded" else str(check.get("summary", "monitoring check reported warning")),
                result={
                    "schema": "hermes.action_result.v1",
                    "kind": "monitoring_check",
                    "ok": status == "succeeded",
                    "runner_mode": runner_mode or "",
                    "redactions": {"applied": True, "marker": REDACTION_MARKER},
                    "details": check,
                },
                redactions_applied=True,
            )
        )
    return StatusPresentation(
        workflow="monitoring",
        graph_id=graph.name,
        completed=bool(cast(object, payload.get("completed", False))),
        actions=actions,
        runner_mode=runner_modes[0] if runner_modes else None,
        redactions_applied=True,
        result_summary={
            "schema": "hermes.graph_result.v1",
            "graph": {"id": graph.name},
            "completed": bool(cast(object, payload.get("completed", False))),
            "failed": not bool(cast(object, payload.get("completed", False))),
            "cancelled": False,
        },
    )


def events_to_dicts(events: list[ActionEvent]) -> list[dict[str, object]]:
    return [event.to_dict() for event in events]


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def preview_from_graph(
    *,
    workflow: str,
    graph: ActionGraph,
    provider: str | None = None,
    runner_mode: str | None = None,
    destroy_preview: dict[str, object] | None = None,
) -> GraphPreviewPresentation:
    graph.validate()
    ordered_ids = _topological_action_order(graph)
    actions: list[GraphPreviewActionPresentation] = []
    for index, action_id in enumerate(ordered_ids, start=1):
        descriptor = graph.actions[action_id]
        approval_required = bool(cast(object, descriptor.metadata.get("approval_required", False)))
        actions.append(
            GraphPreviewActionPresentation(
                action_id=descriptor.action_id,
                label=descriptor.label,
                order=index,
                side_effect_level=str(descriptor.side_effect_level),
                deps=list(descriptor.deps),
                approval_required=approval_required,
                repair_scope=_repair_scope_for_descriptor(descriptor.repair_hint),
            )
        )
    return GraphPreviewPresentation(
        workflow=workflow,
        graph_id=graph.name,
        provider=provider,
        runner_mode=runner_mode,
        destroy_preview=destroy_preview,
        actions=actions,
    )


def _topological_action_order(graph: ActionGraph) -> list[str]:
    ordered: list[str] = []
    remaining = set(graph.actions.keys())
    while remaining:
        ready = [
            action_id
            for action_id, descriptor in graph.actions.items()
            if action_id in remaining and all(dep in ordered for dep in descriptor.deps)
        ]
        if not ready:
            raise ValueError(f"cycle detected in graph {graph.name!r}")
        for action_id in ready:
            ordered.append(action_id)
            remaining.remove(action_id)
    return ordered


def _repair_scope_for_descriptor(repair_hint: str | None) -> str:
    if repair_hint is None:
        return "failed node"
    normalized = repair_hint.strip().lower()
    if "subtree" in normalized:
        return "failed subtree"
    if "full panel" in normalized or "full" in normalized:
        return "full panel"
    if "node" in normalized:
        return "failed node"
    return repair_hint
