from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from hermes_control_core import ActionRuntimeState, ActionStatus, Runner

from hermes_vps_app import operational


ConfigLauncher = Callable[[Path], object]


@dataclass(frozen=True)
class ShellAction:
    action_id: str
    label: str
    workflow: str


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
            "config": "Config flow (read-only guidance; no infrastructure side effects)",
            "operational": "Operational maintenance (state-changing actions)",
            "monitoring": "Monitoring (read-only observability; on-demand checks)",
        }

    def operational_actions(self) -> list[ShellAction]:
        return [
            ShellAction(
                action_id="init",
                label="Initialize OpenTofu provider directory",
                workflow="maintenance/state-changing",
            )
        ]

    def launch_config(self, *, repo_root: Path) -> object:
        return self._config_launcher(repo_root)

    def run_init(
        self,
        *,
        runner: Runner,
        repo_root: Path,
        provider_override: str | None,
        host_override_token: str | None = None,
    ) -> list[str]:
        result = operational.execute_init_graph(
            runner=runner,
            repo_root=repo_root,
            provider_override=provider_override,
            host_override_token=host_override_token,
        )
        return _format_engine_states(result.states)

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
        actions: list[dict[str, str]] = []
        for action_id, state in sorted(result.states.items(), key=lambda item: item[0]):
            actions.append(
                {
                    "action_id": action_id,
                    "status": state.status.value,
                    "error": state.last_error or "",
                }
            )
        return {
            "workflow": "deploy",
            "completed": result.completed,
            "failed": result.failed,
            "actions": actions,
        }


def _format_engine_states(states: dict[str, ActionRuntimeState]) -> list[str]:
    ordered = sorted(states.items(), key=lambda item: item[0])
    return [f"{action_id}: {_status_text(state.status)}" for action_id, state in ordered]


def _status_text(status: ActionStatus) -> str:
    return status.value


def _default_config_launcher(repo_root: Path) -> object:
    from scripts.configure_tui import run_configure_app

    return run_configure_app(repo_root)
