# pyright: reportAny=false
from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast, final, override

from hermes_vps_app.panel_shell import ControlPanelShell, InitialPanel
from hermes_vps_app.panel_startup import PanelStartupResult

try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Vertical
    from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Static, TabPane, TabbedContent
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only in stripped runtime environments
    raise RuntimeError(
        "The Hermes native control panel requires Textual. Run through the project toolchain or install textual."
    ) from exc


def render_panel_text(
    *,
    shell: ControlPanelShell,
    repo_root: Path,
    startup_result: PanelStartupResult,
    initial_panel: InitialPanel,
    host_override_reason: str | None = None,
) -> str:
    """Render deterministic startup/panel text for tests and headless previews."""
    lines = [
        "Hermes VPS Control Panel",
        f"Initial panel: {initial_panel}",
        f"Initial panel state: {shell.initial_state_label()}",
    ]
    if host_override_reason and startup_result.runner_mode == "host":
        lines.append(f"Host override: enabled for this launch only; reason={host_override_reason}")
        lines.append("Host override token: required only at central pre-run execution; token is never rendered or stored.")
    lines.extend(startup_result.to_human_lines())
    if initial_panel == "configuration" or startup_result.state.value == "configuration_required":
        lines.extend(_configuration_lines(shell=shell, repo_root=repo_root))
    elif initial_panel == "maintenance":
        lines.extend(_maintenance_lines(shell=shell))
    elif initial_panel == "monitoring":
        lines.extend(_monitoring_lines(shell=shell))
    else:
        lines.extend(_deployment_lines(shell=shell))
    return "\n".join(lines)


@final
class HermesControlPanelApp(App[None]):
    """Panel-native Textual application backed by ControlPanelShell services."""

    TITLE = "Hermes VPS Control Panel"
    BINDINGS = [("q", "quit", "Quit")]
    CSS = """
    Screen { layout: vertical; }
    #summary { padding: 1 2; background: $surface; }
    #action-status { padding: 0 2 1 2; background: $surface; border-bottom: solid $accent; }
    #main-tabs { height: 1fr; }
    .panel-body { padding: 1 2; }
    .panel-title { text-style: bold; color: $accent; margin-bottom: 1; }
    .button-row { height: auto; margin: 0 0 1 0; }
    .button-row Button { margin-right: 1; }
    .line-list { height: auto; margin-top: 1; }
    ListItem { padding: 0 1; }
    """

    def __init__(
        self,
        *,
        shell: ControlPanelShell,
        repo_root: Path,
        startup_result: PanelStartupResult,
        initial_panel: InitialPanel,
    ) -> None:
        super().__init__()
        self.shell = shell
        self.repo_root = Path(repo_root)
        self.startup_result = startup_result
        self.panel_target: InitialPanel = initial_panel

    @override
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._summary_text(), id="summary")
        yield Static("Ready. Choose an action.", id="action-status")
        active = "configuration" if self.startup_result.state.value == "configuration_required" else self.panel_target
        with TabbedContent(initial=active, id="main-tabs"):
            with TabPane("Configuration", id="configuration"):
                yield self._line_panel(
                    "Configuration",
                    _configuration_lines(shell=self.shell, repo_root=self.repo_root),
                    buttons=self._configuration_buttons(),
                )
            with TabPane("Deployment", id="deployment"):
                yield self._line_panel("Deployment", self._deployment_lines(), buttons=self._deployment_buttons())
            with TabPane("Maintenance", id="maintenance"):
                yield self._line_panel("Maintenance", self._maintenance_lines(), buttons=self._maintenance_buttons())
            with TabPane("Monitoring", id="monitoring"):
                yield self._line_panel("Monitoring", self._monitoring_lines(), buttons=self._monitoring_buttons())
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id is None:
            return
        if button_id.startswith("configuration-section-"):
            section = button_id.removeprefix("configuration-section-")
            self._set_status(f"Configuration section selected: {section}.")
            return
        if button_id == "configuration-review-apply":
            self._set_status("Configuration review selected. Launch full configure flow from just configure.")
            return
        if button_id.startswith("deployment-"):
            self._set_status(f"Deployment action selected: {button_id.removeprefix('deployment-')}.")
            return
        if button_id.startswith("maintenance-"):
            self._set_status(f"Maintenance action selected: {button_id.removeprefix('maintenance-')}.")
            return
        if button_id.startswith("monitoring-"):
            self._set_status(f"Monitoring action selected: {button_id.removeprefix('monitoring-')}.")
            return

    def _switch_tab(self, tab_id: str) -> None:
        self.query_one("#main-tabs", TabbedContent).active = tab_id
        self._set_status(f"Opened {tab_id} panel.")

    def _set_status(self, message: str) -> None:
        self.query_one("#action-status", Static).update(message)

    def _summary_text(self) -> str:
        return (
            f"state={self.shell.initial_state_label()}  "
            f"runner={self.startup_result.runner_mode or 'unknown'}  "
            f"provider={self.startup_result.provider or 'not configured'}"
        )

    def _line_panel(self, title: str, lines: Iterable[str], *, buttons: Iterable[Button] = ()) -> Container:
        items = [ListItem(Label(line)) for line in lines]
        return Container(
            Vertical(
                Static(title, classes="panel-title"),
                Container(*buttons, classes="button-row"),
                ListView(*items, classes="line-list"),
                classes="panel-body",
            )
        )

    def _configuration_buttons(self) -> list[Button]:
        return [
            Button("Cloud", id="configuration-section-cloud"),
            Button("Server", id="configuration-section-server"),
            Button("Hermes", id="configuration-section-hermes"),
            Button("Telegram", id="configuration-section-telegram"),
            Button("Review / Apply", id="configuration-review-apply", variant="primary"),
        ]

    def _deployment_buttons(self) -> list[Button]:
        return [
            Button("Run Deploy", id="deployment-run-deploy", variant="primary"),
            Button("Preview Deploy", id="deployment-preview-deploy"),
            Button("Init", id="deployment-run-init"),
            Button("Plan", id="deployment-run-plan"),
            Button("Apply", id="deployment-run-apply"),
            Button("Bootstrap", id="deployment-run-bootstrap"),
            Button("Verify", id="deployment-run-verify"),
        ]

    def _maintenance_buttons(self) -> list[Button]:
        return [
            Button("Preview Destroy", id="maintenance-preview-destroy", variant="warning"),
            Button("Run Destroy", id="maintenance-run-destroy", variant="error"),
            Button("Down", id="maintenance-run-down", variant="error"),
        ]

    def _monitoring_buttons(self) -> list[Button]:
        return [
            Button("Run Health Probe", id="monitoring-run-health", variant="primary"),
            Button("View Logs", id="monitoring-view-logs"),
            Button("Hardening Audit", id="monitoring-hardening-audit"),
        ]

    def _deployment_lines(self) -> list[str]:
        return _deployment_lines(shell=self.shell)

    def _maintenance_lines(self) -> list[str]:
        return _maintenance_lines(shell=self.shell)

    def _monitoring_lines(self) -> list[str]:
        return _monitoring_lines(shell=self.shell)


def _deployment_lines(*, shell: ControlPanelShell) -> list[str]:
    actions = shell.deployment_actions()
    advanced = shell.deployment_advanced_actions()
    return [
        "Primary workflow: deploy = init -> plan -> apply -> bootstrap -> verify",
        "Advanced actions: " + ", ".join(sorted({action.workflow for action in advanced})),
        "Aggregate nodes: " + ", ".join(action.action_id for action in actions),
        "Destroy/down are intentionally absent from Deployment.",
    ]


def _maintenance_lines(*, shell: ControlPanelShell) -> list[str]:
    actions = shell.maintenance_actions()
    return [
        "Maintenance owns destructive lifecycle only.",
        "Workflows: " + ", ".join(sorted({action.workflow for action in actions})),
        "Destroy/down use preview, confirmation, backup, and audit gates.",
    ]


def _monitoring_lines(*, shell: ControlPanelShell) -> list[str]:
    actions = shell.monitoring_actions()
    return [
        "Monitoring is read-only and on-demand.",
        "Surfaces: " + ", ".join(action.action_id for action in actions),
        "No remote checks run at startup.",
    ]


def _configuration_lines(*, shell: ControlPanelShell, repo_root: Path) -> list[str]:
    screen = shell.configuration_panel(repo_root=repo_root)
    lines = [f"State: {screen['state']}", f"Mode: {screen['mode']}"]
    if "steps" in screen:
        steps = cast(Sequence[object], screen["steps"])
        lines.append("First-run steps: " + " -> ".join(str(step) for step in steps))
    if "sections" in screen:
        sections = cast(Sequence[object], screen["sections"])
        lines.append("Reconfigure sections: " + ", ".join(str(section) for section in sections))
    return lines
