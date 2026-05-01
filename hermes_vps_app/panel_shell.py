from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from hermes_control_core import ActionGraph, Runner

from hermes_vps_app import operational
from hermes_vps_app.status_presentation import (
    presentation_from_engine_result,
    presentation_from_monitoring_payload,
    preview_from_graph,
)


ConfigLauncher = Callable[[Path], object]


@dataclass(frozen=True)
class ShellAction:
    action_id: str
    label: str
    workflow: str
    panel: str
    side_effect_level: str
    state_change_label: str
    execution_mode: str = "bounded"


class ControlPanelShell:
    _config_launcher: ConfigLauncher
    init_graph_builder: Callable[[], object]
    deploy_graph_builder: Callable[[], object]
    monitoring_graph_builder: Callable[[], object]

    def __init__(self, config_launcher: ConfigLauncher | None = None) -> None:
        self._config_launcher = config_launcher or _default_config_launcher
        self.init_graph_builder = operational.build_init_graph
        self.deploy_graph_builder = operational.build_deploy_graph
        self.monitoring_graph_builder = operational.build_monitoring_graph

    def navigation(self) -> dict[str, str]:
        return {
            "config": "Configuration flow (read-only guidance; no infrastructure side effects)",
            "maintenance": "Maintenance flows (state-changing local OpenTofu actions)",
            "monitoring": "Monitoring v1 (read-only observability; on-demand checks only)",
            "deploy/bootstrap": "Deploy/bootstrap flows (state-changing infrastructure and remote bootstrap actions)",
        }

    def maintenance_actions(self) -> list[ShellAction]:
        return _actions_for_graph(
            graph=operational.build_init_graph(),
            panel="maintenance",
            workflow="init",
            state_change_label="state-changing",
        )

    def deploy_bootstrap_actions(self) -> list[ShellAction]:
        return _actions_for_graph(
            graph=operational.build_deploy_graph(),
            panel="deploy/bootstrap",
            workflow="deploy",
            state_change_label="state-changing",
        )

    def monitoring_actions(self) -> list[ShellAction]:
        return _actions_for_graph(
            graph=operational.build_monitoring_graph(),
            panel="monitoring",
            workflow="monitoring",
            state_change_label="read-only",
            execution_mode="on-demand",
        )

    def operational_actions(self) -> list[ShellAction]:
        return self.maintenance_actions()

    def launch_config(self, *, repo_root: Path) -> object:
        return self._config_launcher(repo_root)

    def preview_init(self, *, provider: str | None, runner: Runner | None = None) -> dict[str, object]:
        presentation = preview_from_graph(
            workflow="init",
            graph=operational.build_init_graph(),
            provider=provider,
            runner_mode=runner.mode if runner is not None else None,
        )
        return presentation.to_dict()

    def preview_deploy(self, *, provider: str | None, runner: Runner | None = None) -> dict[str, object]:
        presentation = preview_from_graph(
            workflow="deploy",
            graph=operational.build_deploy_graph(),
            provider=provider,
            runner_mode=runner.mode if runner is not None else None,
        )
        return presentation.to_dict()

    def run_init(
        self,
        *,
        runner: Runner,
        repo_root: Path,
        provider_override: str | None,
        host_override_token: str | None = None,
        override_reason: str | None = None,
    ) -> list[str]:
        result = operational.execute_init_graph(
            runner=runner,
            repo_root=repo_root,
            provider_override=provider_override,
            host_override_token=host_override_token,
            override_reason=override_reason,
        )
        presentation = presentation_from_engine_result(
            workflow="init",
            graph=operational.build_init_graph(),
            result=result,
        )
        return presentation.to_human_lines()

    def run_init_status(
        self,
        *,
        runner: Runner,
        repo_root: Path,
        provider_override: str | None,
        host_override_token: str | None = None,
        override_reason: str | None = None,
    ) -> dict[str, object]:
        result = operational.execute_init_graph(
            runner=runner,
            repo_root=repo_root,
            provider_override=provider_override,
            host_override_token=host_override_token,
            override_reason=override_reason,
        )
        presentation = presentation_from_engine_result(
            workflow="init",
            graph=operational.build_init_graph(),
            result=result,
        )
        return presentation.to_dict()

    def run_monitoring_status(
        self,
        *,
        repo_root: Path,
        provider_override: str | None,
    ) -> dict[str, object]:
        payload = operational.run_monitoring_graph(repo_root=repo_root, provider_override=provider_override)
        presentation = presentation_from_monitoring_payload(
            graph=operational.build_monitoring_graph(),
            payload=payload,
        )
        return presentation.to_dict()

    def run_deploy(
        self,
        *,
        runner: Runner,
        repo_root: Path,
        provider_override: str | None,
        host_override_token: str | None = None,
    ) -> dict[str, object]:
        result = operational.run_operational_graph(
            action="deploy",
            runner=runner,
            repo_root=repo_root,
            provider_override=provider_override,
            host_override_token=host_override_token,
        )
        presentation = presentation_from_engine_result(
            workflow="deploy",
            graph=operational.build_deploy_graph(),
            result=result,
        )
        return presentation.to_dict()


def _actions_for_graph(
    *,
    graph: ActionGraph,
    panel: str,
    workflow: str,
    state_change_label: str,
    execution_mode: str = "bounded",
) -> list[ShellAction]:
    graph.validate()
    return [
        ShellAction(
            action_id=descriptor.action_id,
            label=descriptor.label,
            workflow=workflow,
            panel=panel,
            side_effect_level=str(descriptor.side_effect_level),
            state_change_label=state_change_label,
            execution_mode=execution_mode,
        )
        for descriptor in (graph.actions[action_id] for action_id in sorted(graph.actions))
    ]


def _default_config_launcher(repo_root: Path) -> object:
    from scripts.configure_tui import run_configure_app

    return run_configure_app(repo_root)
