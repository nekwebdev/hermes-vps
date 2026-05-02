# pyright: reportAny=false
from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast, final, override

from rich.text import Text

from hermes_vps_app.cloud_remediation import ProviderId, render_remediation
from hermes_vps_app.config_model import SecretDraft
from hermes_vps_app.panel_config_flow import (
    CloudLookupMode,
    CloudMetadataSyncResult,
    PanelConfigFlow,
)
from hermes_vps_app.panel_shell import ControlPanelShell, InitialPanel
from hermes_vps_app.panel_startup import PanelStartupResult

try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.timer import Timer
    from textual.widgets import (
        Button,
        Checkbox,
        Footer,
        Header,
        Input,
        Label,
        ListItem,
        ListView,
        Select,
        Static,
        TabbedContent,
        TabPane,
    )
    from textual.worker import Worker, WorkerState
except (
    ModuleNotFoundError
) as exc:  # pragma: no cover - exercised only in stripped runtime environments
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
        lines.append(
            f"Host override: enabled for this launch only; reason={host_override_reason}"
        )
        lines.append(
            "Host override token: required only at central pre-run execution; token is never rendered or stored."
        )
    lines.extend(startup_result.to_human_lines())
    if (
        initial_panel == "configuration"
        or startup_result.state.value == "configuration_required"
    ):
        lines.extend(_configuration_lines(shell=shell, repo_root=repo_root))
    elif initial_panel == "maintenance":
        lines.extend(_maintenance_lines(shell=shell))
    elif initial_panel == "monitoring":
        lines.extend(_monitoring_lines(shell=shell))
    else:
        lines.extend(_deployment_lines(shell=shell))
    return "\n".join(lines)


@final
class CloudTokenHelpScreen(ModalScreen[None]):
    """Provider-specific Cloud token setup help shown from the Token row."""

    provider_label: str
    help_text: str

    def __init__(self, *, provider_label: str, help_text: str) -> None:
        super().__init__()
        self.provider_label = provider_label
        self.help_text = help_text

    @override
    def compose(self) -> ComposeResult:
        yield Container(
            Static(
                f"How to create a {self.provider_label} token", classes="panel-title"
            ),
            Static(self.help_text, id="first-run-cloud-token-help-text"),
            Button("Close", id="first-run-cloud-token-help-close", variant="primary"),
            id="first-run-cloud-token-help-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "first-run-cloud-token-help-close":
            _ = event.stop()
            _ = self.dismiss(None)


@final
class HermesControlPanelApp(App[None]):
    """Panel-native Textual application backed by ControlPanelShell services."""

    TITLE = "Hermes VPS Control Panel"
    BINDINGS = [("q", "quit", "Quit")]
    CLOUD_LOADING_FRAMES = tuple("⣠⣴⣾⣿⣿⣿⣷⣦⣄")
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
    #first-run-config-layout { height: auto; }
    #first-run-step-sidebar { width: 22; padding: 1; border: solid $accent; margin-right: 1; }
    #first-run-step-main { width: 1fr; }
    #first-run-cloud-token-label-row { height: auto; margin-top: 1; }
    #first-run-cloud-token-help { min-width: 2; width: 3; margin-left: 1; }
    #first-run-cloud-provider { margin-bottom: 1; }
    #first-run-cloud-token { margin-bottom: 1; }
    #first-run-cloud-sync { margin-bottom: 1; }
    #first-run-cloud-region-section { display: none; height: auto; margin-top: 1; margin-bottom: 1; }
    #first-run-cloud-server-type-section { display: none; height: auto; margin-bottom: 1; }
    #first-run-cloud-step-status { margin-top: 1; color: white; }
    #first-run-cloud-token-help-dialog { width: 72; height: auto; padding: 1 2; border: solid $accent; background: $surface; }
    #first-run-cloud-token-help-text { margin: 1 0; }
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
        self.config_flow = PanelConfigFlow.for_repo(self.repo_root)
        self._cloud_metadata_sync_request_id = 0
        self._cloud_metadata_sync_loading = False
        self._cloud_status_timer: Timer | None = None
        self._cloud_status_animation_index = 0
        self._cloud_status_loading_message = ""

    @override
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._summary_text(), id="summary")
        yield Static("Ready. Choose an action.", id="action-status")
        active = (
            "configuration"
            if self.startup_result.state.value == "configuration_required"
            else self.panel_target
        )
        with TabbedContent(initial=active, id="main-tabs"):
            with TabPane("Configuration", id="configuration"):
                if self.config_flow.mode == "first_run":
                    yield self._first_run_configuration_panel()
                else:
                    yield self._line_panel(
                        "Configuration",
                        _configuration_lines(
                            shell=self.shell, repo_root=self.repo_root
                        ),
                        buttons=self._configuration_buttons(),
                    )
            with TabPane("Deployment", id="deployment"):
                yield self._line_panel(
                    "Deployment",
                    self._deployment_lines(),
                    buttons=self._deployment_buttons(),
                )
            with TabPane("Maintenance", id="maintenance"):
                yield self._line_panel(
                    "Maintenance",
                    self._maintenance_lines(),
                    buttons=self._maintenance_buttons(),
                )
            with TabPane("Monitoring", id="monitoring"):
                yield self._line_panel(
                    "Monitoring",
                    self._monitoring_lines(),
                    buttons=self._monitoring_buttons(),
                )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id is None:
            return
        if button_id == "first-run-cloud-next":
            self._advance_first_run_cloud_step()
            return
        if button_id == "first-run-host-ssh-next":
            self._advance_first_run_host_ssh_step()
            return
        if button_id == "first-run-cloud-sync":
            self._sync_first_run_cloud_metadata()
            return
        if button_id == "first-run-cloud-token-help":
            provider = self.config_flow.draft.provider.provider
            _ = self.push_screen(
                CloudTokenHelpScreen(
                    provider_label=self._provider_label(provider),
                    help_text=self._cloud_provider_help_text(provider),
                )
            )
            return
        if button_id.startswith("configuration-section-"):
            section = button_id.removeprefix("configuration-section-")
            self._set_status(f"Configuration section selected: {section}.")
            return
        if button_id == "configuration-review-apply":
            self._set_status(
                "Configuration review selected. Launch full configure flow from just configure."
            )
            return
        if button_id.startswith("deployment-"):
            self._set_status(
                f"Deployment action selected: {button_id.removeprefix('deployment-')}."
            )
            return
        if button_id.startswith("maintenance-"):
            self._set_status(
                f"Maintenance action selected: {button_id.removeprefix('maintenance-')}."
            )
            return
        if button_id.startswith("monitoring-"):
            self._set_status(
                f"Monitoring action selected: {button_id.removeprefix('monitoring-')}."
            )
            return

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.name not in (
            "first-run-cloud-sync",
            "first-run-cloud-check",
        ) or event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        if event.state == WorkerState.SUCCESS and worker.name == "first-run-cloud-sync":
            request_id, selected_region, result = cast(
                tuple[int, str | None, CloudMetadataSyncResult], worker.result
            )
            if request_id != self._cloud_metadata_sync_request_id:
                return
            self.config_flow.record_cloud_metadata_sync_result(result)
            if result.passed:
                self._apply_cloud_metadata_widgets(
                    result.regions, result.server_types, result.selected_region
                )
                self._set_first_run_cloud_step_status(
                    "Cloud metadata synced."
                    if selected_region
                    else "Cloud metadata synced."
                )
                self._finish_cloud_sync_progress()
            else:
                self._finish_cloud_sync_progress()
                self._render_cloud_sync_failure()
            self._refresh_first_run_sidebar()
            return
        if (
            event.state == WorkerState.SUCCESS
            and worker.name == "first-run-cloud-check"
        ):
            request_id, provider, token, region, server_type, result = cast(
                tuple[int, ProviderId, str, str, str, CloudMetadataSyncResult],
                worker.result,
            )
            if request_id != self._cloud_metadata_sync_request_id:
                return
            self.config_flow.record_cloud_metadata_sync_result(result)
            self._finish_cloud_sync_progress()
            if result.passed and self.config_flow.has_valid_cloud_metadata_sync(
                provider=provider,
                token=token,
                region=region,
                server_type=server_type,
            ):
                self._complete_first_run_cloud_step(
                    provider=provider,
                    region_value=region,
                    server_type_value=server_type,
                )
            else:
                if result.passed:
                    self._set_first_run_cloud_step_status(
                        "Selected region or server type is no longer available. Sync live cloud metadata again.",
                        color="red",
                    )
                else:
                    self._render_cloud_sync_failure()
            self._refresh_first_run_sidebar()
            return
        if event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            if self._cloud_metadata_sync_loading:
                self._finish_cloud_sync_progress()
                self._set_first_run_cloud_step_status(
                    "Live cloud metadata sync failed. Retry Sync.", color="red"
                )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "first-run-cloud-server-type":
            self._refresh_first_run_cloud_next_state()
            return
        if event.select.id == "first-run-cloud-region":
            if self._cloud_metadata_sync_loading or event.value == "__syncing__":
                self._refresh_first_run_cloud_next_state()
                return
            if isinstance(event.value, str) and event.value:
                self._refresh_live_server_types_for_region(event.value)
            self._refresh_first_run_cloud_next_state()
            return
        if event.select.id != "first-run-cloud-provider":
            return
        if not isinstance(event.value, str) or event.value not in ("hetzner", "linode"):
            return
        self._capture_cloud_token_input()
        self._cloud_metadata_sync_request_id += 1
        self._finish_cloud_sync_progress()
        provider = cast(ProviderId, event.value)
        self.config_flow.set_cloud(provider=provider, lookup_mode="live")
        self._clear_cloud_metadata_widgets()
        self._refresh_cloud_provider_help(provider)
        self._refresh_first_run_sidebar()
        self._set_first_run_cloud_step_status(
            f"Cloud provider set to {self._provider_label(provider)}. Sync live metadata before continuing."
        )
        self._refresh_first_run_cloud_next_state()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "first-run-cloud-token":
            return
        self.config_flow.invalidate_cloud_live_check()
        self.config_flow.invalidate_cloud_metadata_sync()
        self._cloud_metadata_sync_request_id += 1
        self._finish_cloud_sync_progress()
        self._clear_cloud_metadata_widgets()
        self._refresh_first_run_sidebar()
        self._refresh_first_run_cloud_next_state()

    def _switch_tab(self, tab_id: str) -> None:
        self.query_one("#main-tabs", TabbedContent).active = tab_id
        self._set_status(f"Opened {tab_id} panel.")

    def _set_status(self, message: str) -> None:
        self.query_one("#action-status", Static).update(message)

    def _set_first_run_cloud_step_status(
        self, message: str, *, color: str = "white"
    ) -> None:
        try:
            status = self.query_one("#first-run-cloud-step-status", Static)
            status.update(message)
            status.styles.color = color
        except Exception:
            return

    def _start_cloud_status_animation(self, message: str) -> None:
        self._cloud_status_loading_message = message
        self._cloud_status_animation_index = 1
        self._tick_cloud_status_animation()
        if self._cloud_status_timer is None:
            self._cloud_status_timer = self.set_interval(
                0.12, self._tick_cloud_status_animation
            )
            return
        self._cloud_status_timer.resume()

    def _stop_cloud_status_animation(self) -> None:
        if self._cloud_status_timer is not None:
            self._cloud_status_timer.pause()

    def _cloud_loading_wave(self) -> str:
        frames = self.CLOUD_LOADING_FRAMES
        start = self._cloud_status_animation_index % len(frames)
        return "".join(frames[(start + offset) % len(frames)] for offset in range(3))

    def _tick_cloud_status_animation(self) -> None:
        if (
            not self._cloud_metadata_sync_loading
            or not self._cloud_status_loading_message
        ):
            return
        wave = self._cloud_loading_wave()
        self._cloud_status_animation_index += 1
        self._set_first_run_cloud_step_status(
            f"{wave} {self._cloud_status_loading_message}", color="rgb(1,120,212)"
        )

    def _summary_text(self) -> str:
        return (
            f"state={self.shell.initial_state_label()}  "
            f"runner={self.startup_result.runner_mode or 'unknown'}  "
            f"provider={self.startup_result.provider or 'not configured'}"
        )

    def _line_panel(
        self, title: str, lines: Iterable[str], *, buttons: Iterable[Button] = ()
    ) -> Container:
        items = [ListItem(Label(line)) for line in lines]
        return Container(
            Vertical(
                Static(title, classes="panel-title"),
                Container(*buttons, classes="button-row"),
                ListView(*items, classes="line-list"),
                classes="panel-body",
            )
        )

    def _first_run_configuration_panel(self) -> Container:
        provider = self.config_flow.draft.provider.provider
        self.config_flow.set_cloud(provider=provider, lookup_mode="live")
        return Container(
            Horizontal(
                Static(
                    self._first_run_sidebar_renderable(), id="first-run-step-sidebar"
                ),
                Vertical(
                    Static(
                        "First-run configuration wizard: Cloud",
                        id="first-run-step-title",
                        classes="panel-title",
                    ),
                    Label("Cloud provider"),
                    Select(
                        (("Hetzner", "hetzner"), ("Linode", "linode")),
                        value=provider,
                        id="first-run-cloud-provider",
                    ),
                    Horizontal(
                        Label("Token", id="first-run-cloud-token-label"),
                        Button("ⓘ", id="first-run-cloud-token-help"),
                        id="first-run-cloud-token-label-row",
                    ),
                    Input(
                        placeholder=f"Paste {self._provider_label(provider)} token",
                        password=True,
                        id="first-run-cloud-token",
                    ),
                    Button("Sync", id="first-run-cloud-sync"),
                    Vertical(
                        Label("Region"),
                        Select((), id="first-run-cloud-region", prompt="Sync required"),
                        id="first-run-cloud-region-section",
                    ),
                    Vertical(
                        Label("Server type"),
                        Select(
                            (), id="first-run-cloud-server-type", prompt="Sync required"
                        ),
                        id="first-run-cloud-server-type-section",
                    ),
                    Button(
                        "Next: Host & SSH",
                        id="first-run-cloud-next",
                        variant="primary",
                        disabled=True,
                    ),
                    Static("", id="first-run-cloud-step-status"),
                    Static("", id="first-run-cloud-summary"),
                    classes="panel-body",
                    id="first-run-step-main",
                ),
                id="first-run-config-layout",
            ),
            id="first-run-config-body",
        )

    def _capture_cloud_token_input(self) -> None:
        try:
            token = self.query_one("#first-run-cloud-token", Input).value.strip()
        except Exception:
            return
        if not token:
            return
        provider = self.config_flow.draft.provider.provider
        if provider == "hetzner":
            self.config_flow.draft.provider.hcloud_token = SecretDraft.replace(token)
        else:
            self.config_flow.draft.provider.linode_token = SecretDraft.replace(token)

    def _cloud_lookup_mode(self) -> CloudLookupMode:
        try:
            value = self.query_one("#first-run-cloud-lookup-mode", Select).value
        except Exception:
            return "sample"
        return cast(CloudLookupMode, value) if value in ("sample", "live") else "sample"

    @staticmethod
    def _cloud_provider_help_text(provider: ProviderId) -> str:
        if provider == "hetzner":
            return (
                "1) Open https://console.hetzner.cloud/\n"
                "2) Select your project\n"
                "3) Security -> API Tokens\n"
                "4) Generate API token with Read & Write scope\n"
                "5) Paste token"
            )
        return (
            "1) Open https://cloud.linode.com/profile/tokens\n"
            "2) Create a Personal Access Token\n"
            "3) Give Read/Write scope for Linodes\n"
            "4) Set expiration per your policy\n"
            "5) Paste token"
        )

    def _refresh_cloud_provider_help(self, provider: ProviderId) -> None:
        try:
            self.query_one("#first-run-cloud-provider-help", Static).update(
                self._cloud_provider_help_text(provider)
            )
        except Exception:
            return

    def _first_run_sidebar_renderable(self) -> Text:
        labels: dict[str, str] = {
            "cloud": "Cloud",
            "server": "Host & SSH",
            "hermes": "Hermes",
            "telegram": "Gateways",
            "review_apply": "Review",
        }
        current = self.config_flow.current_step or "cloud"
        current_index = (
            self.config_flow.steps.index(current)
            if current in self.config_flow.steps
            else 0
        )
        failed_cloud = False
        result = self.config_flow.cloud_metadata_sync_result()
        if current == "cloud" and result is not None and not result.passed:
            failed_cloud = True
        text = Text("Steps")
        for index, step in enumerate(self.config_flow.steps):
            label = labels[step]
            if step == "cloud" and failed_cloud:
                marker = "!"
                style = "red"
            elif index < current_index:
                marker = "✓"
                style = "green"
            elif step == current:
                marker = "▶"
                style = "cyan"
            else:
                marker = "○"
                style = "dim"
            text.append("\n")
            text.append(f"{marker} {label}", style=style)
        return text

    def _first_run_sidebar_text(self) -> str:
        return self._first_run_sidebar_renderable().plain

    def _refresh_first_run_sidebar(self) -> None:
        try:
            self.query_one("#first-run-step-sidebar", Static).update(
                self._first_run_sidebar_renderable()
            )
        except Exception:
            return

    def _cloud_sync_result_text(self) -> str:
        result = self.config_flow.cloud_metadata_sync_result()
        if result is None or result.passed:
            return ""
        if result.remediation and result.remediation.reason in (
            "missing_token",
            "token_invalid",
        ):
            prefix = (
                "Missing" if result.remediation.reason == "missing_token" else "Wrong"
            )
            if result.remediation.provider == "linode":
                return f"{prefix} Linode token."
            if result.remediation.provider == "hetzner":
                return f"{prefix} Hetzner token."
        if result.remediation is None:
            return result.summary
        return f"{result.summary}\n{render_remediation(result.remediation)}"

    def _refresh_first_run_cloud_next_state(self) -> None:
        try:
            button = self.query_one("#first-run-cloud-next", Button)
            provider = self.config_flow.draft.provider.provider
            token = self.query_one("#first-run-cloud-token", Input).value.strip()
            selected_secret = (
                self.config_flow.draft.provider.hcloud_token
                if provider == "hetzner"
                else self.config_flow.draft.provider.linode_token
            )
            region_value = self.query_one("#first-run-cloud-region", Select).value
            server_type_value = self.query_one(
                "#first-run-cloud-server-type", Select
            ).value
            complete = (
                not self._cloud_metadata_sync_loading
                and (bool(token) or selected_secret.present)
                and isinstance(region_value, str)
                and bool(region_value)
                and isinstance(server_type_value, str)
                and bool(server_type_value)
                and self.config_flow.has_valid_cloud_metadata_sync(
                    provider=provider,
                    token=token,
                    region=region_value,
                    server_type=server_type_value,
                )
            )
            button.disabled = not complete
        except Exception:
            return

    def _sync_first_run_cloud_metadata(
        self, *, selected_region: str | None = None
    ) -> None:
        if self._cloud_metadata_sync_loading:
            return
        provider = self.config_flow.draft.provider.provider
        token = self.query_one("#first-run-cloud-token", Input).value.strip()
        if token:
            self._capture_cloud_token_input()
        self._cloud_metadata_sync_request_id += 1
        request_id = self._cloud_metadata_sync_request_id
        self._start_cloud_sync_progress(selected_region=selected_region)

        def run_sync() -> tuple[int, str | None, CloudMetadataSyncResult]:
            result = self.config_flow.cloud_metadata_sync_runner(
                provider, token, selected_region
            )
            return request_id, selected_region, result

        self.run_worker(
            run_sync,
            name="first-run-cloud-sync",
            group="first-run-cloud-sync",
            thread=True,
            exclusive=True,
        )

    def _start_cloud_sync_progress(self, *, selected_region: str | None) -> None:
        self._cloud_metadata_sync_loading = True
        if selected_region:
            try:
                region_label = self._cloud_region_label(selected_region)
            except Exception:
                region_label = selected_region
            message = f"Syncing server types for {region_label}..."
        else:
            message = "Syncing live cloud metadata..."
        try:
            self.query_one("#first-run-cloud-sync", Button).disabled = True
            self.query_one("#first-run-cloud-next", Button).disabled = True
            if selected_region:
                server_type_select = self.query_one(
                    "#first-run-cloud-server-type", Select
                )
                server_type_select.set_options((("Syncing...", "__syncing__"),))
                server_type_select.value = "__syncing__"
            else:
                region_select = self.query_one("#first-run-cloud-region", Select)
                server_type_select = self.query_one(
                    "#first-run-cloud-server-type", Select
                )
                region_select.set_options((("Syncing...", "__syncing__"),))
                server_type_select.set_options((("Syncing...", "__syncing__"),))
                region_select.value = "__syncing__"
                server_type_select.value = "__syncing__"
            self._start_cloud_status_animation(message)
        except Exception:
            return

    def _finish_cloud_sync_progress(self) -> None:
        self._cloud_metadata_sync_loading = False
        self._stop_cloud_status_animation()
        try:
            self.query_one("#first-run-cloud-sync", Button).disabled = False
            self._refresh_first_run_cloud_next_state()
        except Exception:
            return

    def _refresh_live_server_types_for_region(self, region: str) -> None:
        result = self.config_flow.cloud_metadata_sync_result()
        if not result or not result.passed or result.selected_region == region:
            return
        token = self.query_one("#first-run-cloud-token", Input).value.strip()
        if not token:
            return
        self._sync_first_run_cloud_metadata(selected_region=region)

    def _apply_cloud_metadata_widgets(
        self,
        regions: Sequence[object],
        server_types: Sequence[object],
        selected_region: str,
    ) -> None:
        try:
            region_select = self.query_one("#first-run-cloud-region", Select)
            server_type_select = self.query_one("#first-run-cloud-server-type", Select)
            region_options = tuple(
                (getattr(item, "label"), getattr(item, "value")) for item in regions
            )
            server_type_options = tuple(
                (getattr(item, "label"), getattr(item, "value"))
                for item in server_types
            )
            region_select.set_options(region_options)
            server_type_select.set_options(server_type_options)
            region_select.value = selected_region
            recommended = next(
                (
                    getattr(item, "value")
                    for item in server_types
                    if getattr(item, "recommended", False)
                ),
                None,
            )
            server_type_select.value = recommended or (
                getattr(server_types[0], "value") if server_types else Select.BLANK
            )
            self.query_one("#first-run-cloud-region-section").styles.display = "block"
            self.query_one(
                "#first-run-cloud-server-type-section"
            ).styles.display = "block"
            self._refresh_first_run_cloud_next_state()
        except Exception:
            return

    def _clear_cloud_metadata_widgets(self, *, result_text: str = "") -> None:
        try:
            region_select = self.query_one("#first-run-cloud-region", Select)
            server_type_select = self.query_one("#first-run-cloud-server-type", Select)
            region_select.set_options(())
            server_type_select.set_options(())
            region_select.value = Select.BLANK
            server_type_select.value = Select.BLANK
            self.query_one("#first-run-cloud-region-section").styles.display = "none"
            self.query_one(
                "#first-run-cloud-server-type-section"
            ).styles.display = "none"
            self._set_first_run_cloud_step_status(result_text)
            token_input = self.query_one("#first-run-cloud-token", Input)
            token_input.placeholder = f"Paste {self._provider_label(self.config_flow.draft.provider.provider)} token"
            self._refresh_first_run_cloud_next_state()
        except Exception:
            return

    def _render_cloud_sync_failure(self) -> None:
        self._set_first_run_cloud_step_status(
            self._cloud_sync_result_text(), color="red"
        )
        self._refresh_first_run_cloud_next_state()

    def _start_cloud_check_progress(self) -> None:
        self._cloud_metadata_sync_loading = True
        try:
            self.query_one("#first-run-cloud-sync", Button).disabled = True
            self.query_one("#first-run-cloud-next", Button).disabled = True
            self._start_cloud_status_animation("Checking Cloud configuration...")
            self._refresh_first_run_sidebar()
        except Exception:
            return

    def _advance_first_run_cloud_step(self) -> None:
        provider = self.config_flow.draft.provider.provider
        token = self.query_one("#first-run-cloud-token", Input).value.strip()
        if token:
            if provider == "hetzner":
                self.config_flow.draft.provider.hcloud_token = SecretDraft.replace(
                    token
                )
            else:
                self.config_flow.draft.provider.linode_token = SecretDraft.replace(
                    token
                )
        selected_secret = (
            self.config_flow.draft.provider.hcloud_token
            if provider == "hetzner"
            else self.config_flow.draft.provider.linode_token
        )
        if not (selected_secret.replacement or selected_secret.present):
            self._set_first_run_cloud_step_status(
                f"{self._provider_label(provider)} token is required before continuing."
            )
            return
        region_value = self.query_one("#first-run-cloud-region", Select).value
        server_type_value = self.query_one("#first-run-cloud-server-type", Select).value
        if not self.config_flow.cloud_metadata_synced:
            self._set_first_run_cloud_step_status(
                "Sync live cloud metadata successfully before continuing."
            )
            self._refresh_first_run_sidebar()
            return
        if not isinstance(region_value, str) or not region_value:
            self._set_first_run_cloud_step_status(
                "Region is required before continuing."
            )
            return
        if not isinstance(server_type_value, str) or not server_type_value:
            self._set_first_run_cloud_step_status(
                "Server type is required before continuing."
            )
            return
        if not self.config_flow.has_valid_cloud_metadata_sync(
            provider=provider,
            token=token,
            region=region_value,
            server_type=server_type_value,
        ):
            self._set_first_run_cloud_step_status(
                "Sync live cloud metadata successfully before continuing."
            )
            self._refresh_first_run_sidebar()
            return
        self._start_cloud_check_progress()
        self._cloud_metadata_sync_request_id += 1
        request_id = self._cloud_metadata_sync_request_id

        def run_check() -> (
            tuple[int, ProviderId, str, str, str, CloudMetadataSyncResult]
        ):
            result = self.config_flow.cloud_metadata_sync_runner(
                provider, token, region_value
            )
            return request_id, provider, token, region_value, server_type_value, result

        self.run_worker(
            run_check,
            name="first-run-cloud-check",
            group="first-run-cloud-sync",
            thread=True,
            exclusive=True,
        )

    def _complete_first_run_cloud_step(
        self, *, provider: ProviderId, region_value: str, server_type_value: str
    ) -> None:
        self.config_flow.set_cloud(provider=provider, lookup_mode="live")
        self.config_flow.draft.server.location = region_value
        self.config_flow.draft.server.server_type = server_type_value
        self.config_flow.current_step = "server"
        self.query_one("#first-run-cloud-summary", Static).update(
            f"Cloud complete: provider={provider}; region={region_value}; server_type={server_type_value}; server_image={self.config_flow.draft.server.image}; "
            "token=<redacted>."
        )
        self._refresh_first_run_sidebar()
        self._render_first_run_host_ssh_step()

    def _first_run_step_main(self) -> Vertical:
        return self.query_one("#first-run-step-main", Vertical)

    def _render_first_run_host_ssh_step(self) -> None:
        defaults = self.config_flow.host_ssh_defaults()
        main = self._first_run_step_main()
        self.query_one("#first-run-step-title", Static).update(
            "First-run configuration wizard: Host & SSH"
        )
        for widget_id in (
            "first-run-cloud-provider",
            "first-run-cloud-token-label-row",
            "first-run-cloud-token",
            "first-run-cloud-sync",
            "first-run-cloud-region-section",
            "first-run-cloud-server-type-section",
            "first-run-cloud-next",
            "first-run-cloud-step-status",
        ):
            try:
                self.query_one(f"#{widget_id}").styles.display = "none"
            except Exception:
                pass
        if self.query("#first-run-hostname"):
            return
        main.mount(
            Label("Hostname"),
            Input(value=defaults.hostname, id="first-run-hostname"),
            Label("Admin username"),
            Input(value=defaults.admin_username, id="first-run-admin-username"),
            Label("Admin group"),
            Input(value=defaults.admin_group, id="first-run-admin-group"),
            Label("SSH private key path"),
            Input(value=defaults.ssh_private_key_path, id="first-run-ssh-key-path"),
            Checkbox(
                "Configure local SSH alias “hermes-vps” at Apply",
                value=defaults.add_ssh_alias,
                id="first-run-ssh-alias",
            ),
            Static(
                "No SSH config changes are made until Review/Apply.",
                id="first-run-ssh-alias-helper",
            ),
            Button("Next: Hermes", id="first-run-host-ssh-next", variant="primary"),
            Static("", id="first-run-host-ssh-step-status"),
        )

    def _set_first_run_host_ssh_step_status(
        self, message: str, *, color: str = "white"
    ) -> None:
        try:
            status = self.query_one("#first-run-host-ssh-step-status", Static)
            status.update(message)
            status.styles.color = color
        except Exception:
            return

    def _advance_first_run_host_ssh_step(self) -> None:
        result = self.config_flow.set_host_ssh(
            hostname=self.query_one("#first-run-hostname", Input).value,
            admin_username=self.query_one("#first-run-admin-username", Input).value,
            admin_group=self.query_one("#first-run-admin-group", Input).value,
            ssh_private_key_path=self.query_one("#first-run-ssh-key-path", Input).value,
            add_ssh_alias=self.query_one("#first-run-ssh-alias", Checkbox).value,
        )
        if not result.ok:
            self._set_first_run_host_ssh_step_status(result.message, color="red")
            self._refresh_first_run_sidebar()
            return
        self.query_one("#first-run-step-title", Static).update(
            "First-run configuration wizard: Hermes"
        )
        self._set_first_run_host_ssh_step_status(result.message)
        self._refresh_first_run_sidebar()

    @staticmethod
    def _cloud_region_label(region_value: str) -> str:
        options = {
            "fsn1": "Falkenstein (fsn1)",
            "nbg1": "Nuremberg (nbg1)",
            "hel1": "Helsinki (hel1)",
        }
        return options.get(region_value, region_value)

    @staticmethod
    def _provider_label(provider: str) -> str:
        return "Hetzner" if provider == "hetzner" else "Linode"

    def _configuration_buttons(self) -> list[Button]:
        return [
            Button("Cloud", id="configuration-section-cloud"),
            Button("Host & SSH", id="configuration-section-server"),
            Button("Hermes", id="configuration-section-hermes"),
            Button("Gateways", id="configuration-section-telegram"),
            Button(
                "Review / Apply", id="configuration-review-apply", variant="primary"
            ),
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
            Button(
                "Preview Destroy", id="maintenance-preview-destroy", variant="warning"
            ),
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
        "Advanced actions: "
        + ", ".join(sorted({action.workflow for action in advanced})),
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
        labels = {
            "cloud": "Cloud",
            "server": "Host & SSH",
            "hermes": "Hermes",
            "telegram": "Gateways",
            "review_apply": "Review",
        }
        lines.append(
            "First-run steps: "
            + " -> ".join(labels.get(str(step), str(step)) for step in steps)
        )
    if "sections" in screen:
        sections = cast(Sequence[object], screen["sections"])
        lines.append(
            "Reconfigure sections: " + ", ".join(str(section) for section in sections)
        )
    return lines
