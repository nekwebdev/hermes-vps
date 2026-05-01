# pyright: reportImplicitOverride=false, reportAny=false
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from hermes_control_core import (
    ActionDescriptor,
    ActionGraph,
    CommandFailed,
    Engine,
    RedactionError,
    RunRequest,
    RunResult,
    Runner,
    SessionAuditLog,
)
from hermes_control_core.actions import ActionEvent, bounded_output_tail
from hermes_control_core.interfaces import RunnerMode
from hermes_vps_app.error_taxonomy import ErrorCategory, classify_exception, graph_failure_from_result
from hermes_vps_app.status_presentation import events_to_dicts, presentation_from_engine_result

SECRET_VALUES = [
    "hcloud_provider_token_issue09_value",
    "hermes_api_key_issue09_value",
    "123456789:telegram_bot_token_issue09_VALUE-abcdefghijklmnopqrstuvwxyz",
    "ya29.oauth_artifact_issue09_value",
    "runtime_env_issue09_value",
    "DESTROY:issue09:bad-token-value",
    "I-ACK-HOST-OVERRIDE-issue09-bad-token",
]

SECRET_BEARING_TEXT = "\n".join(
    [
        f"HCLOUD_TOKEN={SECRET_VALUES[0]}",
        f"HERMES_API_KEY={SECRET_VALUES[1]}",
        f"TELEGRAM_BOT_TOKEN={SECRET_VALUES[2]}",
        f'{{"access_token":"{SECRET_VALUES[3]}","refresh_token":"oauth-refresh-issue09"}}',
        f"HERMES_RUNTIME_ENV={SECRET_VALUES[4]}",
        f"destroy approval was {SECRET_VALUES[5]}",
        f"host override was {SECRET_VALUES[6]}",
    ]
)


@dataclass
class SecretRunner(Runner):
    mode: RunnerMode = "direnv_nix"
    exit_code: int = 0

    def run(self, request: RunRequest) -> RunResult:
        _ = request
        result = RunResult(
            exit_code=self.exit_code,
            stdout="prefix\n" + ("x" * 5000) + "\n" + SECRET_BEARING_TEXT + "\nstdout-end",
            stderr="stderr-start\n" + SECRET_BEARING_TEXT + "\nstderr-end",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            runner_mode=self.mode,
            redactions_applied=True,
        )
        if self.exit_code != 0:
            raise CommandFailed(f"command failed with {SECRET_BEARING_TEXT}", result)
        return result


class SecretHandler:
    def run(self, action: ActionDescriptor, context: dict[str, Any], runner: Runner) -> dict[str, Any]:
        _ = action
        _ = context
        result = runner.run(RunRequest(command=["fake"], cwd=Path("."), shell=False))
        return {
            "kind": "command",
            "ok": result.exit_code == 0,
            "command": ["fake", SECRET_VALUES[6]],
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "runner_mode": result.runner_mode,
            "redactions_applied": result.redactions_applied,
            "terraform_outputs": {"server_password": SECRET_VALUES[0]},
            "oauth_artifact": {"access_token": SECRET_VALUES[3]},
        }


class EventCollector:
    def __init__(self) -> None:
        self.events: list[ActionEvent] = []

    def emit(self, event: ActionEvent) -> None:
        self.events.append(event)


def _graph() -> ActionGraph:
    return ActionGraph(
        name="issue09-redaction-matrix",
        actions={"cmd": ActionDescriptor(action_id="cmd", label="redaction matrix command")},
    )


def _assert_public_payload_is_redacted(rendered: str) -> None:
    for secret in SECRET_VALUES:
        assert secret not in rendered
    assert "oauth-refresh-issue09" not in rendered
    assert "***" in rendered


def test_issue09_redacts_secret_matrix_across_public_result_surfaces() -> None:
    events = EventCollector()
    audit = SessionAuditLog(session_id="issue09", repo_root=Path("/tmp/repo"))
    audit.metadata["captured_env"] = SECRET_BEARING_TEXT
    audit.add_destructive_approval(
        action_id="destroy",
        approved=False,
        approved_by="tester",
        token_used=SECRET_VALUES[5],
        flag_used="--i-understand-this-destroys-resources",
        details={"host_override_token": SECRET_VALUES[6], "provider_output": SECRET_BEARING_TEXT},
    )

    result = Engine(
        graph=_graph(),
        runner=SecretRunner(mode="host", exit_code=1),
        handler=SecretHandler(),
        event_sink=events,
        audit_log=audit,
        context={"override_reason": SECRET_BEARING_TEXT},
        require_host_override_token=False,
    ).run()

    status = presentation_from_engine_result(workflow="issue09", graph=_graph(), result=result)
    cli_error = graph_failure_from_result(workflow="issue09", graph=_graph(), result=result)
    public_surfaces = {
        "graph_result": json.dumps(result.to_summary(), sort_keys=True, default=str) + json.dumps(
            {action_id: state.result for action_id, state in result.states.items()}, sort_keys=True, default=str
        ),
        "action_events": json.dumps(events_to_dicts(events.events), sort_keys=True, default=str),
        "audit_session": json.dumps(audit.to_dict(), sort_keys=True, default=str),
        "error_json": cli_error.to_json(),
        "error_human": "\n".join(cli_error.to_human_lines()),
        "status_json": status.to_json(),
        "status_human": "\n".join(status.to_human_lines()),
        "bounded_tail": "\n".join(bounded_output_tail("z" * 5000 + SECRET_BEARING_TEXT)[0:1]),
    }

    for surface, rendered in public_surfaces.items():
        _assert_public_payload_is_redacted(f"{surface}: {rendered}")

    event_payloads = cast(list[dict[str, Any]], events_to_dicts(events.events))
    failed_event = event_payloads[-1]
    assert failed_event["redactions"] == {"applied": True, "marker": "***"}
    status_payload = status.to_dict()
    assert status_payload["redactions"] == {"applied": True, "marker": "***"}
    assert cli_error.to_dict()["redactions"] == {"applied": True, "marker": "***"}


def test_issue09_redaction_failures_use_shared_error_taxonomy() -> None:
    classified = classify_exception(RedactionError(f"redaction failed for {SECRET_BEARING_TEXT}"), workflow="issue09")

    assert classified.category is ErrorCategory.REDACTION_ERROR
    assert classified.exit_code == 60
    _assert_public_payload_is_redacted(classified.to_json())
    _assert_public_payload_is_redacted("\n".join(classified.to_human_lines()))
