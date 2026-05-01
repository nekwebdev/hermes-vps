# pyright: reportImplicitOverride=false, reportUnnecessaryCast=false
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from hermes_control_core import (
    ActionDescriptor,
    ActionGraph,
    CommandFailed,
    Engine,
    RunRequest,
    RunResult,
    Runner,
)
from hermes_control_core.actions import ActionEvent
from hermes_control_core.interfaces import RunnerMode
from hermes_vps_app.status_presentation import events_to_dicts, presentation_from_engine_result


@dataclass
class FakeRunner(Runner):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    mode: RunnerMode = "direnv_nix"
    redactions_applied: bool = True

    def run(self, request: RunRequest) -> RunResult:
        result = RunResult(
            exit_code=self.exit_code,
            stdout=self.stdout,
            stderr=self.stderr,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            runner_mode="direnv_nix",
            redactions_applied=self.redactions_applied,
        )
        if self.exit_code != 0:
            raise CommandFailed("command failed", result)
        return result


class CommandHandler:
    def run(self, action: ActionDescriptor, context: dict[str, Any], runner: Runner) -> dict[str, Any]:
        _ = action
        _ = context
        result = runner.run(RunRequest(command=["fake"], cwd=Path("."), shell=False))
        return {
            "kind": "command",
            "command": ["fake"],
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "runner_mode": result.runner_mode,
            "redactions_applied": result.redactions_applied,
        }


class EventCollector:
    def __init__(self) -> None:
        self.events: list[ActionEvent] = []

    def emit(self, event: ActionEvent) -> None:
        self.events.append(event)


def _graph() -> ActionGraph:
    return ActionGraph(
        name="schema-demo",
        actions={"cmd": ActionDescriptor(action_id="cmd", label="command action")},
    )


def test_failed_command_action_result_retains_bounded_stderr_tail() -> None:
    stderr = "error-start\n" + ("y" * 5000) + "\nTOKEN=failed-secret\nfinal-error\n"
    events = EventCollector()

    result = Engine(
        graph=_graph(),
        runner=FakeRunner(stderr=stderr, exit_code=9),
        handler=CommandHandler(),
        event_sink=events,
    ).run()

    assert result.failed is True
    action_result = cast(dict[str, Any], result.states["cmd"].result or {})
    output = cast(dict[str, Any], action_result["output"])
    assert action_result["schema"] == "hermes.action_result.v1"
    assert action_result["kind"] == "command"
    assert action_result["ok"] is False
    assert action_result["exit_code"] == 9
    assert output["truncated"] is True
    assert "final-error" in output["stderr_tail"]
    assert "failed-secret" not in output["stderr_tail"]
    assert "***" in output["stderr_tail"]
    event_payloads = cast(list[dict[str, Any]], events_to_dicts(events.events))
    assert event_payloads[-1]["status"] == "failed"
    failed_event_details = cast(dict[str, Any], event_payloads[-1]["details"])
    failed_event_result = cast(dict[str, Any], failed_event_details["result"])
    assert failed_event_result["ok"] is False
    assert "failed-secret" not in str(event_payloads)


def test_command_action_result_and_event_schema_bounds_output_and_redacts_secrets() -> None:
    secret = "HERMES_API_KEY=super-secret-value"
    stdout = "start\n" + ("x" * 5000) + "\n" + secret + "\ndone\n"
    events = EventCollector()

    result = Engine(
        graph=_graph(),
        runner=FakeRunner(stdout=stdout),
        handler=CommandHandler(),
        event_sink=events,
    ).run()

    action_result = cast(dict[str, Any], result.states["cmd"].result or {})
    output = cast(dict[str, Any], action_result["output"])
    assert action_result["schema"] == "hermes.action_result.v1"
    assert action_result["kind"] == "command"
    assert action_result["ok"] is True
    assert action_result["runner_mode"] == "direnv_nix"
    assert action_result["redactions"] == {"applied": True, "marker": "***"}
    assert output["truncated"] is True
    assert output["tail_bytes"] <= 4096
    assert "done" in output["stdout_tail"]
    assert "super-secret-value" not in output["stdout_tail"]
    assert "***" in output["stdout_tail"]

    payload = cast(dict[str, Any], presentation_from_engine_result(workflow="demo", graph=_graph(), result=result).to_dict())
    actions = cast(list[dict[str, Any]], payload["actions"])
    rendered_action = actions[0]
    rendered_result = cast(dict[str, Any], rendered_action["result"])
    graph_result = cast(dict[str, Any], payload["result"])
    assert rendered_result["schema"] == "hermes.action_result.v1"
    assert graph_result["schema"] == "hermes.graph_result.v1"
    assert "super-secret-value" not in str(payload)

    event_payloads = cast(list[dict[str, Any]], events_to_dicts(events.events))
    assert event_payloads[0]["schema"] == "hermes.action_event.v1"
    assert event_payloads[0]["action"] == {"id": "cmd", "label": "command action"}
    assert event_payloads[0]["runner_mode"] == "direnv_nix"
    assert event_payloads[0]["redactions"] == {"applied": True, "marker": "***"}
    succeeded_event_details = cast(dict[str, Any], event_payloads[-1]["details"])
    succeeded_event_result = cast(dict[str, Any], succeeded_event_details["result"])
    succeeded_event_output = cast(dict[str, Any], succeeded_event_result["output"])
    assert succeeded_event_output["truncated"] is True
    assert "super-secret-value" not in str(event_payloads)
