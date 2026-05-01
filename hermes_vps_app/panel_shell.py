from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from hermes_control_core import ActionGraph, Runner, SessionAuditLog
from hermes_vps_app.operator_snapshot import OperatorSnapshot, build_operator_snapshot
from hermes_vps_app.panel_startup import PanelStartupResult

from hermes_vps_app import operational
from hermes_vps_app.status_presentation import (
    presentation_from_engine_result,
    presentation_from_monitoring_payload,
    preview_from_graph,
)


ConfigLauncher = Callable[[Path], object]
InitialPanel = Literal["configuration", "deployment", "maintenance", "monitoring"]
DeploymentAdvancedWorkflow = Literal["init", "plan", "apply", "bootstrap", "verify"]
MaintenanceWorkflow = Literal["destroy", "down"]
DEPLOYMENT_ADVANCED_WORKFLOWS: tuple[DeploymentAdvancedWorkflow, ...] = (
    "init",
    "plan",
    "apply",
    "bootstrap",
    "verify",
)
MAINTENANCE_WORKFLOWS: tuple[MaintenanceWorkflow, ...] = ("destroy", "down")


@dataclass(frozen=True)
class ShellAction:
    action_id: str
    label: str
    workflow: str
    panel: str
    side_effect_level: str
    state_change_label: str
    execution_mode: str = "bounded"


class HostOverrideError(RuntimeError):
    pass


class ControlPanelShell:
    _config_launcher: ConfigLauncher
    init_graph_builder: Callable[[], object]
    deploy_graph_builder: Callable[[], object]
    monitoring_graph_builder: Callable[[], object]
    startup_result: PanelStartupResult | None
    initial_panel: InitialPanel

    def __init__(
        self,
        config_launcher: ConfigLauncher | None = None,
        startup_result: PanelStartupResult | None = None,
        initial_panel: InitialPanel = "deployment",
    ) -> None:
        self._config_launcher = config_launcher or _default_config_launcher
        self.startup_result = startup_result
        self.initial_panel = initial_panel
        self._host_override_session: dict[str, object] | None = None
        self.init_graph_builder = operational.build_init_graph
        self.deploy_graph_builder = operational.build_deploy_graph
        self.monitoring_graph_builder = operational.build_monitoring_graph

    def initial_state_label(self) -> str:
        if self.startup_result is not None and self.startup_result.state.value == "configuration_required":
            return "configuration_required"
        if self.initial_panel == "configuration":
            return "configuration_reconfigure"
        if self.startup_result is not None:
            return self.startup_result.state.value
        return "dashboard_ready"

    def navigation(self) -> dict[str, str]:
        return {
            "config": "Configuration flow (read-only guidance; no infrastructure side effects)",
            "maintenance": "Maintenance flows (state-changing local OpenTofu actions)",
            "monitoring": "Monitoring v1 (read-only observability; on-demand checks only)",
            "deployment": "Deployment flows (aggregate init/plan/apply/bootstrap/verify plus advanced state-changing actions)",
        }

    def host_override_advanced_path(self) -> dict[str, object]:
        return {
            "visible_by_default": False,
            "label": "Advanced unsafe environment / host override",
            "summary": (
                "Session-only break-glass path for runner=host. Prefer direnv/nix/Docker remediation; "
                "host execution requires explicit enablement, a non-empty reason, and the central pre-run token."
            ),
            "requires_explicit_enablement": True,
            "requires_reason": True,
            "requires_token_before_run": True,
            "persistence": "per-launch only; never written to disk",
        }

    def request_host_override(self, *, enable: bool, reason: str) -> dict[str, object]:
        clean_reason = reason.strip()
        if not enable:
            self._host_override_session = None
            return {
                "approved": False,
                "message": "Host override is hidden behind the advanced unsafe environment path; explicitly enable it to continue.",
                "requires_token": True,
            }
        if not clean_reason:
            self._host_override_session = None
            return {
                "approved": False,
                "message": "Host override requires a non-empty audited reason before runner=host can be selected.",
                "requires_token": True,
            }
        self._host_override_session = {
            "approved": True,
            "runner_mode": "host",
            "override_reason": clean_reason,
            "scope": "per-launch",
            "requires_token": True,
        }
        return dict(self._host_override_session)

    def host_override_session(self) -> dict[str, object] | None:
        if self._host_override_session is None:
            return None
        return dict(self._host_override_session)

    def render_host_override_token(self, _token: str) -> str:
        raise HostOverrideError("Host override tokens are never rendered; enter the central pre-run token only at execution time.")

    def panel_cards(self) -> list[dict[str, str]]:
        return [
            {
                "title": "Configuration",
                "route": "configuration",
                "summary": "Review .env structure and provider selection without showing secrets.",
            },
            {
                "title": "Deployment",
                "route": "deployment",
                "summary": "Deploy infrastructure and run bootstrap/verify workflows on demand.",
            },
            {
                "title": "Maintenance",
                "route": "maintenance",
                "summary": "Run local OpenTofu maintenance workflows with explicit state-changing labels.",
            },
            {
                "title": "Monitoring",
                "route": "monitoring",
                "summary": "Run read-only health checks on demand; no remote checks run at startup.",
            },
        ]

    def dashboard_snapshot(self, *, repo_root: Path) -> OperatorSnapshot:
        if self.startup_result is None:
            raise ValueError("dashboard snapshot requires a startup_result")
        return build_operator_snapshot(repo_root=repo_root, startup_result=self.startup_result)

    def dashboard(self, *, repo_root: Path) -> dict[str, object]:
        snapshot = self.dashboard_snapshot(repo_root=repo_root)
        return {
            "environment": {
                "provider": snapshot.provider.selection,
                "runner_mode": snapshot.runner_mode,
                "env_present": snapshot.env_file.exists,
                "env_key_count": snapshot.env_file.key_count,
                "provider_directory": snapshot.provider_directory.detail,
                "opentofu_state_present": snapshot.opentofu.state_present,
                "opentofu_output_present": snapshot.opentofu.output_present,
            },
            "primary_action": snapshot.primary_action.value,
            "panel_cards": self.panel_cards(),
            "recent_status": {
                "bootstrap": snapshot.remote_status.bootstrap.detail,
                "verify": snapshot.remote_status.verify.detail,
                "monitoring": snapshot.remote_status.monitoring.detail,
            },
            "local_health": snapshot.local_health.detail,
            "safety_footer": _safety_footer(snapshot),
        }

    def dashboard_lines(self, *, repo_root: Path) -> list[str]:
        snapshot = self.dashboard_snapshot(repo_root=repo_root)
        card_titles = " | ".join(card["title"] for card in self.panel_cards())
        env_state = "present" if snapshot.env_file.exists else "missing"
        tofu_state = "present" if snapshot.opentofu.state_present else "missing"
        tofu_outputs = "present" if snapshot.opentofu.output_present else "missing"
        return [
            "Dashboard: Hermes VPS operator snapshot",
            (
                f"Environment: provider={snapshot.provider.selection}; runner={snapshot.runner_mode}; "
                f".env={env_state}; provider_dir={snapshot.provider_directory.detail}; "
                f"state={tofu_state}; outputs={tofu_outputs}"
            ),
            f"Primary action: {snapshot.primary_action.value}",
            f"Panel cards: {card_titles}",
            (
                "Recent status: "
                f"bootstrap={snapshot.remote_status.bootstrap.detail}; "
                f"verify={snapshot.remote_status.verify.detail}; "
                f"monitoring={snapshot.remote_status.monitoring.detail}"
            ),
            f"Local health: {snapshot.local_health.detail}",
            f"Safety: {_safety_footer(snapshot)}",
        ]

    def maintenance_actions(self) -> list[ShellAction]:
        actions: list[ShellAction] = []
        for workflow in MAINTENANCE_WORKFLOWS:
            actions.extend(
                _actions_for_graph(
                    graph=_maintenance_graph(workflow),
                    panel="maintenance",
                    workflow=workflow,
                    state_change_label="state-changing",
                )
            )
        return actions

    def deploy_bootstrap_actions(self) -> list[ShellAction]:
        return self.deployment_actions()

    def deployment_actions(self) -> list[ShellAction]:
        return _actions_for_graph(
            graph=operational.build_deploy_graph(),
            panel="deployment",
            workflow="deploy",
            state_change_label="state-changing",
        )

    def deployment_advanced_actions(self) -> list[ShellAction]:
        actions: list[ShellAction] = []
        for workflow in DEPLOYMENT_ADVANCED_WORKFLOWS:
            actions.extend(
                _actions_for_graph(
                    graph=operational.build_graph(workflow),
                    panel="deployment",
                    workflow=workflow,
                    state_change_label="state-changing",
                )
            )
        return actions

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

    def configuration_panel(self, *, repo_root: Path) -> dict[str, object]:
        from hermes_vps_app.panel_config_flow import PanelConfigFlow

        return PanelConfigFlow.for_repo(repo_root).to_screen()

    def preview_init(self, *, provider: str | None, runner: Runner | None = None) -> dict[str, object]:
        presentation = preview_from_graph(
            workflow="init",
            graph=operational.build_init_graph(),
            provider=provider,
            runner_mode=runner.mode if runner is not None else None,
        )
        return presentation.to_dict()

    def preview_deploy(self, *, provider: str | None, runner: Runner | None = None) -> dict[str, object]:
        return self.preview_deployment(provider=provider, runner=runner)

    def preview_deployment(self, *, provider: str | None, runner: Runner | None = None) -> dict[str, object]:
        presentation = preview_from_graph(
            workflow="deploy",
            graph=operational.build_deploy_graph(),
            provider=provider,
            runner_mode=runner.mode if runner is not None else None,
        )
        return presentation.to_dict()

    def preview_deployment_action(
        self,
        *,
        action: DeploymentAdvancedWorkflow,
        provider: str | None,
        runner: Runner | None = None,
    ) -> dict[str, object]:
        _validate_deployment_advanced_workflow(action)
        presentation = preview_from_graph(
            workflow=action,
            graph=operational.build_graph(action),
            provider=provider,
            runner_mode=runner.mode if runner is not None else None,
        )
        return presentation.to_dict()

    def preview_maintenance_action(
        self,
        *,
        action: MaintenanceWorkflow,
        provider_override: str | None,
        runner: Runner,
        repo_root: Path,
    ) -> dict[str, object]:
        _validate_maintenance_workflow(action)
        provider = operational.resolve_provider(provider_override=provider_override)
        selection = operational.validate_init_environment(repo_root=repo_root, provider=provider)
        destroy_preview = None
        if action in {"destroy", "down"}:
            preview = operational.build_destroy_preview(
                repo_root=repo_root,
                provider=provider,
                tf_dir=selection.tf_dir,
                runner=runner,
            )
            destroy_preview = _destroy_preview_payload(preview)
        presentation = preview_from_graph(
            workflow=action,
            graph=_maintenance_graph(action),
            provider=provider,
            runner_mode=runner.mode,
            destroy_preview=destroy_preview,
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
        return self.run_deployment(
            runner=runner,
            repo_root=repo_root,
            provider_override=provider_override,
            host_override_token=host_override_token,
        )

    def run_deployment(
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

    def run_deployment_action(
        self,
        *,
        action: DeploymentAdvancedWorkflow,
        runner: Runner,
        repo_root: Path,
        provider_override: str | None,
        host_override_token: str | None = None,
    ) -> dict[str, object]:
        _validate_deployment_advanced_workflow(action)
        result = operational.run_operational_graph(
            action=action,
            runner=runner,
            repo_root=repo_root,
            provider_override=provider_override,
            host_override_token=host_override_token,
        )
        presentation = presentation_from_engine_result(
            workflow=action,
            graph=operational.build_graph(action),
            result=result,
        )
        return presentation.to_dict()

    def run_maintenance_action(
        self,
        *,
        action: MaintenanceWorkflow,
        runner: Runner,
        repo_root: Path,
        provider_override: str | None,
        host_override_token: str | None = None,
        override_reason: str | None = None,
        approve_destructive: str | None = None,
        confirmation_mode: str = "headless",
        audit_log: SessionAuditLog | None = None,
    ) -> dict[str, object]:
        _validate_maintenance_workflow(action)
        operational_action = "destroy" if action == "down" else action
        result = operational.run_operational_graph(
            action=operational_action,
            runner=runner,
            repo_root=repo_root,
            provider_override=provider_override,
            host_override_token=host_override_token,
            override_reason=override_reason,
            approve_destructive=approve_destructive,
            confirmation_mode=confirmation_mode,
            audit_log=audit_log,
        )
        presentation = presentation_from_engine_result(
            workflow=action,
            graph=_maintenance_graph(action),
            result=result,
        )
        return presentation.to_dict()


def _validate_deployment_advanced_workflow(action: str) -> None:
    if action not in DEPLOYMENT_ADVANCED_WORKFLOWS:
        raise ValueError("deployment advanced action must be one of: init, plan, apply, bootstrap, verify")


def _validate_maintenance_workflow(action: str) -> None:
    if action not in MAINTENANCE_WORKFLOWS:
        raise ValueError("maintenance action must be one of: destroy, down")


def _maintenance_graph(action: str) -> ActionGraph:
    _validate_maintenance_workflow(action)
    if action == "down":
        return operational.build_graph("destroy")
    return operational.build_graph(action)


def _destroy_preview_payload(preview: operational.DestroyPreview) -> dict[str, object]:
    return {
        "provider": preview.provider,
        "tf_dir": str(preview.tf_dir),
        "backup_root": str(preview.backup_root),
        "backup_dir": str(preview.backup_dir),
        "state_files": [str(path) for path in preview.state_files],
        "state_file_count": len(preview.state_files),
        "safe_outputs": dict(preview.safe_outputs),
    }


def _safety_footer(snapshot: OperatorSnapshot) -> str:
    runner_mode = snapshot.runner_mode or "unknown"
    if runner_mode == "host":
        return "runner=host; host override requires explicit audited reason and token before state-changing execution"
    return f"runner={runner_mode}; host override disabled unless explicitly enabled with audited reason"


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
    from hermes_vps_app.panel_config_flow import PanelConfigFlow

    return PanelConfigFlow.for_repo(repo_root).to_screen()
