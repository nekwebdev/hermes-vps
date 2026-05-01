# pyright: reportAny=false
from __future__ import annotations

from pathlib import Path
from typing import cast

from hermes_control_core import ActionGraph
from hermes_vps_app import operational
from hermes_vps_app.cli import build_parser as build_cli_parser
from hermes_vps_app.just_shim import build_parser as build_just_shim_parser
from hermes_vps_app.panel_shell import ControlPanelShell

REPO_ROOT = Path(__file__).resolve().parents[1]
ISSUE_PATH = (
    REPO_ROOT
    / ".scratch"
    / "control-panel-v2-hardening-docs-cutover"
    / "issues"
    / "13-aggregate-command-parity-and-docs-cutover-gate.md"
)
GUIDE_PATH = REPO_ROOT / "docs" / "control-panel-operator-guide.md"
JUSTFILE_PATH = REPO_ROOT / "Justfile"

MIGRATED_WORKFLOWS = ("init", "init-upgrade", "plan", "apply", "destroy", "bootstrap", "verify", "up", "deploy")
AGGREGATE_GATE_TEST_SELECTION = (
    "tests/test_v2_cutover_gate_issue13.py "
    "tests/test_issue11_regression_gate.py "
    "tests/test_secret_redaction_issue09.py "
    "tests/test_operator_docs_issue12.py"
)


def test_issue13_aggregate_v2_cutover_gate_covers_public_surfaces_and_prerequisite_slices() -> None:
    cli_parser = build_cli_parser()
    just_parser = build_just_shim_parser()
    shell = ControlPanelShell()

    for workflow in MIGRATED_WORKFLOWS:
        graph = operational.build_graph(workflow)
        graph.validate()
        _assert_policy_metadata(graph)
        assert cli_parser.parse_args([workflow]).action == workflow
        assert just_parser.parse_args([workflow]).workflow == workflow

    assert cli_parser.parse_args(["monitoring"]).action == "monitoring"
    monitoring_graph = operational.build_monitoring_graph()
    monitoring_graph.validate()
    _assert_policy_metadata(monitoring_graph)

    assert shell.init_graph_builder is operational.build_init_graph
    assert shell.deploy_graph_builder is operational.build_deploy_graph
    assert shell.monitoring_graph_builder is operational.build_monitoring_graph
    assert {action.workflow for action in shell.maintenance_actions()} == {"init"}
    assert {action.workflow for action in shell.deploy_bootstrap_actions()} == {"deploy"}
    assert {action.workflow for action in shell.monitoring_actions()} == {"monitoring"}

    justfile = JUSTFILE_PATH.read_text(encoding="utf-8")
    for workflow in MIGRATED_WORKFLOWS:
        assert f"python3 -m hermes_vps_app.just_shim {workflow}" in justfile

    guide = GUIDE_PATH.read_text(encoding="utf-8")
    issue = ISSUE_PATH.read_text(encoding="utf-8")
    aggregate_command = f'./scripts/toolchain.sh "python3 -m pytest {AGGREGATE_GATE_TEST_SELECTION} -q"'
    assert aggregate_command in guide
    assert "prerequisite for any future Justfile removal" in guide
    assert "prerequisite for any future stable public plugin API decision" in guide
    assert "Status: completed" in issue


def _assert_policy_metadata(graph: ActionGraph) -> None:
    for action in graph.actions.values():
        raw_policy = action.metadata.get("policy")
        assert isinstance(raw_policy, dict), f"{graph.name}.{action.action_id} missing policy metadata"
        policy = cast(dict[str, object], raw_policy)
        assert policy.get("side_effect_level") == action.side_effect_level
        if policy.get("command_backed") and action.side_effect_level != "none":
            assert action.timeout_s is not None
            assert policy.get("timeout") == "bounded"
        if action.side_effect_level == "destructive":
            assert policy.get("approval_required") is True
