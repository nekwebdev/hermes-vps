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
    ConfigApplyResult,
    HermesAuthMode,
    HermesDefaults,
    PanelConfigFlow,
    AsyncValidationResult,
)
from hermes_vps_app.telegram_gateway import (
    TelegramGatewayValidationResult,
    TelegramGatewayValidator,
)
from hermes_vps_app.hermes_live_metadata import (
    HermesReleaseService,
    HermesRuntimeMetadataService,
    HermesToolchainCache,
)
from hermes_vps_app.hermes_oauth import (
    HermesOAuthCancelToken,
    HermesOAuthEvent,
    HermesOAuthInstructionEvent,
    HermesOAuthOutputEvent,
    HermesOAuthRunResult,
    HermesOAuthRunner,
)
from hermes_vps_app.panel_shell import ControlPanelShell, InitialPanel
from hermes_vps_app.panel_startup import PanelStartupResult
from scripts import configure_logic as logic

try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical, VerticalScroll
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
    TabPane { height: 1fr; }
    .panel-body { padding: 1 2; height: 1fr; overflow-y: auto; }
    .panel-scroll { height: 1fr; overflow-y: auto; }
    .panel-title { text-style: bold; color: $accent; margin-bottom: 1; }
    .button-row { height: auto; margin: 0 0 1 0; }
    .button-row Button { margin-right: 1; }
    .line-list { height: auto; margin-top: 1; }
    #first-run-config-layout { height: 1fr; }
    #first-run-config-body { height: 1fr; }
    #first-run-step-sidebar { width: 22; padding: 1; border: solid $accent; margin-right: 1; }
    #first-run-step-main { width: 1fr; }
    .first-run-spacer { height: 1; }
    #first-run-cloud-token-label-row { height: auto; margin-top: 1; }
    #first-run-cloud-token-help { min-width: 1; width: 2; margin-left: 1; }
    #first-run-cloud-provider { margin-bottom: 1; }
    #first-run-cloud-token { margin-bottom: 1; }
    #first-run-cloud-sync { margin-bottom: 1; }
    #first-run-cloud-region-section { display: none; height: auto; margin-top: 1; margin-bottom: 1; }
    #first-run-cloud-server-type-section { display: none; height: auto; margin-bottom: 1; }
    #first-run-cloud-step-status { margin-top: 1; color: white; }
    #first-run-cloud-token-help-dialog { width: 72; height: auto; padding: 1 2; border: solid $accent; background: $surface; }
    #first-run-hermes-retry { display: none; }
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
        self._hermes_status_timer: Timer | None = None
        self._hermes_status_animation_index = 0
        self._hermes_status_loading_message = ""
        self._hermes_live_metadata_request_id = 0
        self._hermes_live_metadata_loading = False
        self._hermes_live_metadata_synced = False
        self._applying_hermes_live_metadata = False
        self._hermes_live_version_tags: dict[str, str] = {}
        self._hermes_oauth_running = False
        self._hermes_oauth_request_id = 0
        self._hermes_oauth_cancel_token: HermesOAuthCancelToken | None = None
        self.hermes_release_service = HermesReleaseService()
        self.hermes_toolchain_cache = HermesToolchainCache(
            root=self.repo_root / ".cache" / "hermes-toolchain"
        )
        self.hermes_runtime_metadata_service = HermesRuntimeMetadataService()
        self.hermes_oauth_runner = HermesOAuthRunner(repo_root=self.repo_root)
        self.telegram_gateway_validator = TelegramGatewayValidator()
        self._telegram_validation_loading = False
        self._telegram_status_timer: Timer | None = None
        self._telegram_status_animation_index = 0
        self._telegram_status_loading_message = ""
        self._first_run_apply_loading = False

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
        if button_id == "first-run-hermes-oauth-button":
            if self._hermes_oauth_running:
                self._cancel_first_run_hermes_oauth()
            else:
                self._start_first_run_hermes_oauth()
            return
        if button_id == "first-run-hermes-retry":
            self._sync_first_run_hermes_live_metadata(force_refresh=True)
            return
        if button_id == "first-run-hermes-next":
            self._advance_first_run_hermes_step()
            return
        if button_id == "first-run-gateways-next":
            self._advance_first_run_gateways_step()
            return
        if button_id == "first-run-review-apply":
            self._apply_first_run_review_configuration()
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
            "first-run-hermes-live-metadata",
            "first-run-hermes-oauth",
            "first-run-telegram-validation",
            "first-run-config-apply",
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
        if event.state == WorkerState.SUCCESS and worker.name == "first-run-hermes-live-metadata":
            request_id, result = cast(tuple[int, HermesDefaults | str], worker.result)
            if request_id != self._hermes_live_metadata_request_id:
                return
            self._finish_hermes_live_metadata_progress()
            if isinstance(result, str):
                self._hermes_live_metadata_synced = False
                self._set_first_run_hermes_step_status(result, color="red")
                self._set_first_run_hermes_retry_visible(True)
                self._refresh_first_run_hermes_next_state()
            else:
                self._apply_hermes_live_metadata_defaults(result)
                self._set_first_run_hermes_step_status("Hermes live metadata synced.")
            self._refresh_first_run_sidebar()
            return
        if event.state == WorkerState.SUCCESS and worker.name == "first-run-hermes-oauth":
            request_id, result = cast(tuple[int, HermesOAuthRunResult], worker.result)
            if request_id != self._hermes_oauth_request_id:
                return
            self._finish_first_run_hermes_oauth(result)
            return
        if event.state == WorkerState.SUCCESS and worker.name == "first-run-telegram-validation":
            validation_result, async_result = cast(
                tuple[TelegramGatewayValidationResult, AsyncValidationResult], worker.result
            )
            acceptance = self.config_flow.complete_telegram_validation(async_result)
            self._telegram_validation_loading = False
            self._stop_telegram_status_animation()
            if acceptance.stale:
                self._set_first_run_gateways_step_status(
                    "Gateway inputs changed. Run Telegram check again."
                )
                self._refresh_first_run_gateways_next_state()
                self._refresh_first_run_sidebar()
                return
            if acceptance.ok and validation_result.ok:
                self._set_first_run_gateways_step_status(validation_result.summary)
                self._render_first_run_review_step()
            else:
                self._set_first_run_gateways_step_status(acceptance.detail, color="red")
                self._refresh_first_run_gateways_next_state()
            self._refresh_first_run_sidebar()
            return
        if event.state == WorkerState.SUCCESS and worker.name == "first-run-config-apply":
            result = cast(ConfigApplyResult, worker.result)
            self._finish_first_run_config_apply(result)
            return
        if event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            if worker.name == "first-run-hermes-oauth":
                request_id = self._hermes_oauth_request_id
                if worker.result is not None:
                    request_id, result = cast(tuple[int, HermesOAuthRunResult], worker.result)
                    if request_id == self._hermes_oauth_request_id:
                        self._finish_first_run_hermes_oauth(result)
                        return
                self._hermes_oauth_running = False
                self._hermes_oauth_cancel_token = None
                self.config_flow.clear_hermes_oauth_artifact()
                self._set_first_run_hermes_oauth_button_label("Start OAuth")
                self._set_hermes_controls_disabled(False)
                self._append_first_run_hermes_oauth_output("OAuth cancelled. No artifact captured.")
                self._refresh_first_run_hermes_next_state()
                return
            if worker.name == "first-run-hermes-live-metadata":
                self._finish_hermes_live_metadata_progress()
                self._hermes_live_metadata_synced = False
                message = "Hermes live metadata sync failed. Retry."
                if worker.error is not None:
                    message = str(worker.error)
                self._set_first_run_hermes_step_status(message, color="red")
                self._set_first_run_hermes_retry_visible(True)
                self._refresh_first_run_hermes_next_state()
                self._refresh_first_run_sidebar()
                return
            if self._cloud_metadata_sync_loading:
                self._finish_cloud_sync_progress()
                self._set_first_run_cloud_step_status(
                    "Live cloud metadata sync failed. Retry Sync.", color="red"
                )
            if worker.name == "first-run-telegram-validation":
                self._telegram_validation_loading = False
                self._stop_telegram_status_animation()
                self._set_first_run_gateways_step_status(
                    "Unable to reach Telegram API. Please retry.", color="red"
                )
                self._refresh_first_run_gateways_next_state()
                return
            if worker.name == "first-run-config-apply":
                self._finish_first_run_config_apply(
                    ConfigApplyResult(
                        ok=False,
                        message="Configuration apply failed. No OAuth artifact was written.",
                        status_lines=("Configuration apply failed. No OAuth artifact was written.",),
                    )
                )
                return

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "first-run-hermes-provider":
            if (
                not self._hermes_live_metadata_synced
                and not self.config_flow.draft.hermes.provider
                and event.value == self.config_flow.hermes_defaults().provider
            ):
                return
            if (
                isinstance(event.value, str)
                and not self._applying_hermes_live_metadata
                and event.value != self.config_flow.draft.hermes.provider
            ):
                self.config_flow.draft.hermes.provider = event.value
                self.config_flow.clear_hermes_oauth_artifact()
                self._set_first_run_hermes_oauth_output("Run OAuth again for current Hermes selection.")
                self._sync_first_run_hermes_live_metadata(show_version_placeholder=False)
            return
        if event.select.id == "first-run-hermes-version":
            if isinstance(event.value, str):
                if event.value == "__syncing__":
                    return
                self._refresh_first_run_hermes_release_tag(event.value)
                if (
                    not self._hermes_live_metadata_synced
                    and not self.config_flow.draft.hermes.agent_version
                    and event.value == self.config_flow.hermes_defaults().agent_version
                ):
                    return
                if (
                    not self._applying_hermes_live_metadata
                    and event.value != self.config_flow.draft.hermes.agent_version
                ):
                    self.config_flow.draft.hermes.agent_version = event.value
                    self.config_flow.draft.hermes.agent_release_tag = self._hermes_live_version_tags.get(event.value, "")
                    self.config_flow.clear_hermes_oauth_artifact()
                    self._set_first_run_hermes_oauth_output("Run OAuth again for current Hermes selection.")
                    self._sync_first_run_hermes_live_metadata()
            return
        if event.select.id == "first-run-hermes-model":
            self.config_flow.clear_hermes_oauth_artifact()
            self._set_first_run_hermes_oauth_output("Run OAuth again for current Hermes selection.")
            self._refresh_first_run_hermes_next_state()
            return
        if event.select.id == "first-run-hermes-auth-method":
            self.config_flow.clear_hermes_oauth_artifact()
            self._refresh_first_run_hermes_auth_section()
            self._refresh_first_run_hermes_next_state()
            return
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
        if event.input.id == "first-run-telegram-token" or event.input.id == "first-run-telegram-allowlist":
            self.config_flow.invalidate_telegram_validation()
            self._refresh_first_run_sidebar()
            self._refresh_first_run_gateways_next_state()
            return
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

    def _start_telegram_status_animation(self, message: str) -> None:
        self._telegram_status_loading_message = message
        self._telegram_status_animation_index = 1
        self._tick_telegram_status_animation()
        if self._telegram_status_timer is None:
            self._telegram_status_timer = self.set_interval(
                0.12, self._tick_telegram_status_animation
            )
            return
        self._telegram_status_timer.resume()

    def _stop_telegram_status_animation(self) -> None:
        if self._telegram_status_timer is not None:
            self._telegram_status_timer.pause()

    def _telegram_loading_wave(self) -> str:
        frames = self.CLOUD_LOADING_FRAMES
        start = self._telegram_status_animation_index % len(frames)
        return "".join(frames[(start + offset) % len(frames)] for offset in range(3))

    def _tick_telegram_status_animation(self) -> None:
        if (
            not self._telegram_validation_loading
            or not self._telegram_status_loading_message
        ):
            return
        wave = self._telegram_loading_wave()
        self._telegram_status_animation_index += 1
        self._set_first_run_gateways_step_status(
            f"{wave} {self._telegram_status_loading_message}", color="rgb(1,120,212)"
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
            VerticalScroll(
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
                VerticalScroll(
                    Static(
                        "First-run configuration wizard: Cloud",
                        id="first-run-step-title",
                        classes="panel-title",
                    ),
                    Label("Cloud provider"),
                    self._first_run_spacer("first-run-cloud-provider-spacer"),
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
                    self._first_run_spacer("first-run-cloud-token-spacer"),
                    Input(
                        placeholder=f"Paste {self._provider_label(provider)} token",
                        password=True,
                        id="first-run-cloud-token",
                    ),
                    Button("Sync", id="first-run-cloud-sync"),
                    Vertical(
                        Label("Region"),
                        self._first_run_spacer("first-run-cloud-region-spacer"),
                        Select((), id="first-run-cloud-region", prompt="Sync required"),
                        id="first-run-cloud-region-section",
                    ),
                    Vertical(
                        Label("Server type"),
                        self._first_run_spacer("first-run-cloud-server-type-spacer"),
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
        self._refresh_first_run_sidebar()
        self._render_first_run_host_ssh_step()

    def _first_run_step_main(self) -> VerticalScroll:
        return self.query_one("#first-run-step-main", VerticalScroll)

    @staticmethod
    def _first_run_spacer(widget_id: str) -> Static:
        return Static("", id=widget_id, classes="first-run-spacer")

    def _hide_first_run_step_body(self) -> None:
        main = self._first_run_step_main()
        for child in main.children:
            if child.id == "first-run-step-title":
                continue
            child.styles.display = "none"

    def _render_first_run_host_ssh_step(self) -> None:
        defaults = self.config_flow.host_ssh_defaults()
        main = self._first_run_step_main()
        self.query_one("#first-run-step-title", Static).update(
            "First-run configuration wizard: Host & SSH"
        )
        if self.query("#first-run-hostname"):
            return
        self._hide_first_run_step_body()
        for widget_id in (
            "first-run-cloud-provider",
            "first-run-cloud-token-label-row",
            "first-run-cloud-token",
            "first-run-cloud-sync",
            "first-run-cloud-region-section",
            "first-run-cloud-server-type-section",
            "first-run-cloud-next",
            "first-run-cloud-step-status",
            "first-run-cloud-summary",
        ):
            try:
                self.query_one(f"#{widget_id}").styles.display = "none"
            except Exception:
                pass
        main.mount(
            Label("Hostname"),
            self._first_run_spacer("first-run-hostname-spacer"),
            Input(value=defaults.hostname, id="first-run-hostname"),
            self._first_run_spacer("first-run-hostname-after-spacer"),
            Label("Admin username"),
            self._first_run_spacer("first-run-admin-username-spacer"),
            Input(value=defaults.admin_username, id="first-run-admin-username"),
            self._first_run_spacer("first-run-admin-username-after-spacer"),
            Label("Admin group"),
            self._first_run_spacer("first-run-admin-group-spacer"),
            Input(value=defaults.admin_group, id="first-run-admin-group"),
            self._first_run_spacer("first-run-admin-group-after-spacer"),
            Label("SSH private key path"),
            self._first_run_spacer("first-run-ssh-key-path-spacer"),
            Input(value=defaults.ssh_private_key_path, id="first-run-ssh-key-path"),
            self._first_run_spacer("first-run-ssh-key-path-after-spacer"),
            Checkbox(
                "Configure local SSH alias “hermes-vps” at Apply",
                value=defaults.add_ssh_alias,
                id="first-run-ssh-alias",
            ),
            self._first_run_spacer("first-run-ssh-alias-after-spacer"),
            Static(
                "No SSH config changes are made until Review/Apply.",
                id="first-run-ssh-alias-helper",
            ),
            self._first_run_spacer("first-run-ssh-alias-helper-after-spacer"),
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
        self._render_first_run_hermes_step()

    def _render_first_run_hermes_step(self) -> None:
        defaults = self.config_flow.hermes_defaults()
        main = self._first_run_step_main()
        if self.query("#first-run-hermes-version"):
            return
        self._hide_first_run_step_body()
        for widget_id in (
            "first-run-hostname",
            "first-run-admin-username",
            "first-run-admin-group",
            "first-run-ssh-key-path",
            "first-run-ssh-alias",
            "first-run-ssh-alias-helper",
            "first-run-host-ssh-next",
            "first-run-host-ssh-step-status",
        ):
            try:
                self.query_one(f"#{widget_id}").styles.display = "none"
            except Exception:
                pass
        main.mount(
            Label("Hermes Agent version"),
            self._first_run_spacer("first-run-hermes-version-spacer"),
            Select(
                (("Syncing Hermes...", "__syncing__"),),
                value="__syncing__",
                id="first-run-hermes-version",
            ),
            self._first_run_spacer("first-run-hermes-version-after-spacer"),
            Static(
                "Release tag: syncing...",
                id="first-run-hermes-release-tag",
            ),
            self._first_run_spacer("first-run-hermes-release-tag-after-spacer"),
            Label("Hermes provider"),
            self._first_run_spacer("first-run-hermes-provider-spacer"),
            Select(
                tuple((provider, provider) for provider in defaults.provider_options),
                value=defaults.provider,
                id="first-run-hermes-provider",
            ),
            self._first_run_spacer("first-run-hermes-provider-after-spacer"),
            Label("Hermes model"),
            self._first_run_spacer("first-run-hermes-model-spacer"),
            Select(
                tuple((model, model) for model in defaults.model_options),
                value=defaults.model,
                id="first-run-hermes-model",
            ),
            self._first_run_spacer("first-run-hermes-model-after-spacer"),
            Label("Auth method"),
            self._first_run_spacer("first-run-hermes-auth-method-spacer"),
            Select(
                (("OAuth", "oauth"), ("API key", "api_key")),
                value=defaults.auth_method,
                id="first-run-hermes-auth-method",
            ),
            self._first_run_spacer("first-run-hermes-auth-method-after-spacer"),
            Button("Start OAuth", id="first-run-hermes-oauth-button"),
            self._first_run_spacer("first-run-hermes-oauth-button-after-spacer"),
            Static("", id="first-run-hermes-oauth-output"),
            Input(
                placeholder=f"{defaults.provider} API key",
                password=True,
                id="first-run-hermes-api-key",
            ),
            self._first_run_spacer("first-run-hermes-api-key-after-spacer"),
            Button("Retry Hermes metadata", id="first-run-hermes-retry"),
            self._first_run_spacer("first-run-hermes-retry-after-spacer"),
            Button("Next: Gateways", id="first-run-hermes-next", variant="primary", disabled=True),
            self._first_run_spacer("first-run-hermes-next-after-spacer"),
            Static("", id="first-run-hermes-step-status"),
        )
        self._refresh_first_run_hermes_auth_section()
        self._sync_first_run_hermes_live_metadata()

    def _sync_first_run_hermes_live_metadata(
        self, *, force_refresh: bool = False, show_version_placeholder: bool = True
    ) -> None:
        self._hermes_live_metadata_request_id += 1
        request_id = self._hermes_live_metadata_request_id
        request_token = f"hermes-{request_id}"
        self._start_hermes_live_metadata_progress(
            show_version_placeholder=show_version_placeholder
        )

        def run_sync() -> tuple[int, HermesDefaults | str]:
            try:
                defaults = self.config_flow.sync_hermes_live_metadata(
                    release_service=self.hermes_release_service,
                    cache_service=self.hermes_toolchain_cache,
                    runtime_metadata_service=self.hermes_runtime_metadata_service,
                    request_id=request_token,
                    force_refresh=force_refresh,
                )
            except Exception as exc:
                return request_id, str(exc)
            return request_id, defaults

        self.run_worker(
            run_sync,
            name="first-run-hermes-live-metadata",
            group="first-run-hermes-live-metadata",
            thread=True,
            exclusive=True,
        )

    def _start_hermes_live_metadata_progress(
        self, *, show_version_placeholder: bool = True
    ) -> None:
        self._hermes_live_metadata_loading = True
        self._hermes_live_metadata_synced = False
        if show_version_placeholder:
            self._show_hermes_version_syncing_placeholder()
        self._set_hermes_controls_disabled(True)
        self._set_first_run_hermes_retry_visible(False)
        self._start_hermes_status_animation("Syncing Hermes...")
        self._refresh_first_run_hermes_next_state()

    def _show_hermes_version_syncing_placeholder(self) -> None:
        self._applying_hermes_live_metadata = True
        try:
            version_select = self.query_one("#first-run-hermes-version", Select)
            version_select.set_options((("Syncing Hermes...", "__syncing__"),))
            version_select.value = "__syncing__"
            self.query_one("#first-run-hermes-release-tag", Static).update("Release tag: syncing...")
        except Exception:
            return
        finally:
            self._applying_hermes_live_metadata = False

    def _finish_hermes_live_metadata_progress(self) -> None:
        self._hermes_live_metadata_loading = False
        self._stop_hermes_status_animation()
        self._set_hermes_controls_disabled(False)
        self._refresh_first_run_hermes_next_state()

    def _start_hermes_status_animation(self, message: str) -> None:
        self._hermes_status_loading_message = message
        self._hermes_status_animation_index = 1
        self._tick_hermes_status_animation()
        if self._hermes_status_timer is None:
            self._hermes_status_timer = self.set_interval(
                0.12, self._tick_hermes_status_animation
            )
            return
        self._hermes_status_timer.resume()

    def _stop_hermes_status_animation(self) -> None:
        if self._hermes_status_timer is not None:
            self._hermes_status_timer.pause()

    def _hermes_loading_wave(self) -> str:
        frames = self.CLOUD_LOADING_FRAMES
        start = self._hermes_status_animation_index % len(frames)
        return "".join(frames[(start + offset) % len(frames)] for offset in range(3))

    def _tick_hermes_status_animation(self) -> None:
        if (
            not self._hermes_live_metadata_loading
            or not self._hermes_status_loading_message
        ):
            return
        wave = self._hermes_loading_wave()
        self._hermes_status_animation_index += 1
        self._set_first_run_hermes_step_status(
            f"{wave} {self._hermes_status_loading_message}", color="rgb(1,120,212)"
        )

    def _set_hermes_controls_disabled(self, disabled: bool) -> None:
        for selector in (
            "#first-run-hermes-version",
            "#first-run-hermes-provider",
            "#first-run-hermes-model",
            "#first-run-hermes-auth-method",
            "#first-run-hermes-oauth-button",
            "#first-run-hermes-api-key",
        ):
            try:
                widget = self.query_one(selector)
                widget.disabled = disabled  # type: ignore[attr-defined]
            except Exception:
                continue
        try:
            retry = self.query_one("#first-run-hermes-retry", Button)
            retry.disabled = disabled
            retry.styles.display = "none"
        except Exception:
            pass

    def _refresh_first_run_hermes_next_state(self) -> None:
        try:
            next_button = self.query_one("#first-run-hermes-next", Button)
            disabled = self._hermes_live_metadata_loading or not self._hermes_live_metadata_synced or self._hermes_oauth_running
            auth_method = self.query_one("#first-run-hermes-auth-method", Select).value
            if auth_method == "oauth" and not disabled:
                version = self.query_one("#first-run-hermes-version", Select).value
                provider = self.query_one("#first-run-hermes-provider", Select).value
                release_tag = self._hermes_live_version_tags.get(version) if isinstance(version, str) else ""
                disabled = not (
                    isinstance(version, str)
                    and isinstance(provider, str)
                    and release_tag
                    and self.config_flow.has_current_hermes_oauth_artifact(
                        agent_version=version,
                        agent_release_tag=release_tag,
                        provider=provider,
                        auth_method="oauth",
                    )
                )
            next_button.disabled = disabled
        except Exception:
            return

    def _apply_hermes_live_metadata_defaults(self, defaults: HermesDefaults) -> None:
        self._applying_hermes_live_metadata = True
        try:
            version_select = self.query_one("#first-run-hermes-version", Select)
            provider_select = self.query_one("#first-run-hermes-provider", Select)
            model_select = self.query_one("#first-run-hermes-model", Select)
            auth_select = self.query_one("#first-run-hermes-auth-method", Select)
            self._hermes_live_version_tags = dict(defaults.version_options)
            self.config_flow.draft.hermes.agent_version = defaults.agent_version
            self.config_flow.draft.hermes.agent_release_tag = defaults.agent_release_tag
            self.config_flow.draft.hermes.provider = defaults.provider
            self.config_flow.draft.hermes.model = defaults.model
            self.config_flow.hermes_auth_mode = defaults.auth_method
            version_select.set_options(tuple((version, version) for version, _tag in defaults.version_options))
            version_select.value = defaults.agent_version
            provider_select.set_options(tuple((provider, provider) for provider in defaults.provider_options))
            provider_select.value = defaults.provider
            model_select.set_options(tuple((model, model) for model in defaults.model_options))
            model_select.value = defaults.model if defaults.model else Select.BLANK
            auth_select.set_options(
                tuple(("OAuth" if method == "oauth" else "API key", method) for method in defaults.auth_methods)
            )
            auth_select.value = defaults.auth_method
            self.query_one("#first-run-hermes-release-tag", Static).update(
                f"Release tag: {defaults.agent_release_tag}"
            )
            self._hermes_live_metadata_synced = True
        finally:
            self._applying_hermes_live_metadata = False
        self._refresh_first_run_hermes_auth_section()
        self._set_first_run_hermes_retry_visible(False)
        self._refresh_first_run_hermes_next_state()

    def _set_first_run_hermes_retry_visible(self, visible: bool) -> None:
        try:
            retry = self.query_one("#first-run-hermes-retry", Button)
            retry.styles.display = "block" if visible else "none"
            retry.disabled = not visible or self._hermes_live_metadata_loading
        except Exception:
            return

    def _refresh_first_run_hermes_release_tag(self, version: str) -> None:
        defaults = self.config_flow.hermes_defaults()
        tag = self._hermes_live_version_tags.get(version) or dict(defaults.version_options).get(version, "unknown")
        try:
            self.query_one("#first-run-hermes-release-tag", Static).update(
                f"Release tag: {tag}"
            )
        except Exception:
            return

    def _refresh_first_run_hermes_model_options(self, provider: str) -> None:
        defaults = self.config_flow.hermes_defaults(provider=provider)
        try:
            model_select = self.query_one("#first-run-hermes-model", Select)
            model_select.set_options(
                tuple((model, model) for model in defaults.model_options)
            )
            model_select.value = defaults.model if defaults.model else Select.BLANK
        except Exception:
            return
        self._refresh_first_run_hermes_auth_section()

    def _refresh_first_run_hermes_auth_section(self) -> None:
        try:
            auth_method = self.query_one("#first-run-hermes-auth-method", Select).value
            oauth_button = self.query_one("#first-run-hermes-oauth-button", Button)
            oauth_output = self.query_one("#first-run-hermes-oauth-output", Static)
            api_key = self.query_one("#first-run-hermes-api-key", Input)
            provider = self.query_one("#first-run-hermes-provider", Select).value
        except Exception:
            return
        if isinstance(provider, str) and provider:
            api_key.placeholder = f"{provider} API key"
        if auth_method == "api_key":
            oauth_button.styles.display = "none"
            oauth_output.styles.display = "none"
            api_key.styles.display = "block"
            return
        oauth_button.styles.display = "block"
        oauth_output.styles.display = "block"
        api_key.styles.display = "none"

    def _set_first_run_hermes_step_status(
        self, message: str, *, color: str = "white"
    ) -> None:
        try:
            status = self.query_one("#first-run-hermes-step-status", Static)
            status.update(message)
            status.styles.color = color
        except Exception:
            return

    def _set_first_run_hermes_oauth_output(self, message: str) -> None:
        try:
            self.query_one("#first-run-hermes-oauth-output", Static).update(message)
        except Exception:
            return

    def _append_first_run_hermes_oauth_output(self, message: str) -> None:
        try:
            widget = self.query_one("#first-run-hermes-oauth-output", Static)
            current = str(widget.renderable or "")
            if current:
                widget.update(f"{current}\n{message}")
            else:
                widget.update(message)
        except Exception:
            return

    def _set_first_run_hermes_oauth_button_label(self, label: str) -> None:
        try:
            self.query_one("#first-run-hermes-oauth-button", Button).label = label
        except Exception:
            return

    def _start_first_run_hermes_oauth(self) -> None:
        if self._hermes_oauth_running or not self._hermes_live_metadata_synced:
            return
        version_value = self.query_one("#first-run-hermes-version", Select).value
        provider_value = self.query_one("#first-run-hermes-provider", Select).value
        auth_method_value = self.query_one("#first-run-hermes-auth-method", Select).value
        if not isinstance(version_value, str) or not isinstance(provider_value, str) or auth_method_value != "oauth":
            self._set_first_run_hermes_step_status("OAuth requires current Hermes version, provider, and OAuth auth method.", color="red")
            return
        agent_release_tag = self._hermes_live_version_tags.get(version_value) or dict(self.config_flow.hermes_defaults().version_options).get(version_value, "")
        if not agent_release_tag:
            self._set_first_run_hermes_step_status("Hermes release tag is required before OAuth.", color="red")
            return
        self.config_flow.clear_hermes_oauth_artifact()
        self._hermes_oauth_running = True
        self._hermes_oauth_request_id += 1
        request_id = self._hermes_oauth_request_id
        cancel_token = HermesOAuthCancelToken()
        self._hermes_oauth_cancel_token = cancel_token
        self._set_first_run_hermes_oauth_button_label("Cancel OAuth")
        self._set_first_run_hermes_oauth_output(
            "Starting OAuth authentication...\n"
            "Hold Shift+Ctrl and click to open a link in the browser.\n"
            "Hold Shift to select text with the mouse.\n"
            "Waiting for Hermes CLI output..."
        )
        self._set_hermes_oauth_running_controls(True)
        self._refresh_first_run_hermes_next_state()
        cache_dir = self.repo_root / ".cache" / "hermes-toolchain" / f"{version_value}-{agent_release_tag}"

        def on_oauth_event(event: HermesOAuthEvent) -> None:
            _ = self.call_from_thread(self._handle_first_run_hermes_oauth_event, event)

        def run_oauth() -> tuple[int, HermesOAuthRunResult]:
            result = self.hermes_oauth_runner.run(
                cache_dir=cache_dir,
                provider=provider_value,
                agent_version=version_value,
                agent_release_tag=agent_release_tag,
                request_id=f"hermes-oauth-{request_id}",
                cancel_token=cancel_token,
                on_event=on_oauth_event,
            )
            return request_id, result

        self.run_worker(
            run_oauth,
            name="first-run-hermes-oauth",
            group="first-run-hermes-oauth",
            thread=True,
            exclusive=True,
        )

    def _cancel_first_run_hermes_oauth(self) -> None:
        if self._hermes_oauth_cancel_token is not None:
            self._hermes_oauth_cancel_token.cancel()
        self._append_first_run_hermes_oauth_output("Cancelling OAuth...")

    def _handle_first_run_hermes_oauth_event(self, event: HermesOAuthEvent) -> None:
        if isinstance(event, HermesOAuthOutputEvent):
            self._append_first_run_hermes_oauth_output(event.text.rstrip("\n"))
            return
        if isinstance(event, HermesOAuthInstructionEvent):
            label = "URL" if event.instruction.kind == "url" else "Code"
            self._append_first_run_hermes_oauth_output(f"{label}: {event.instruction.value}")
            return

    def _finish_first_run_hermes_oauth(self, result: HermesOAuthRunResult) -> None:
        self._hermes_oauth_running = False
        self._hermes_oauth_cancel_token = None
        self._set_first_run_hermes_oauth_button_label("Start OAuth")
        self._set_hermes_oauth_running_controls(False)
        self._render_first_run_hermes_oauth_result(result)
        self._refresh_first_run_hermes_next_state()

    def _render_first_run_hermes_oauth_result(self, result: HermesOAuthRunResult) -> None:
        if result.status == "succeeded" and result.auth_json_bytes is not None:
            self.config_flow.record_hermes_oauth_result(result)
            self._append_first_run_hermes_oauth_output("OAuth artifact captured. It will be written at Review/Apply.")
            self._set_first_run_hermes_step_status("OAuth artifact captured.")
            return
        self.config_flow.clear_hermes_oauth_artifact()
        if result.status == "cancelled":
            self._append_first_run_hermes_oauth_output("OAuth cancelled. No artifact captured.")
            self._set_first_run_hermes_step_status("OAuth cancelled. No artifact captured.", color="red")
            return
        message = result.error_message or "OAuth failed. No artifact captured."
        self._append_first_run_hermes_oauth_output(message)
        self._set_first_run_hermes_step_status(message, color="red")

    def _set_hermes_oauth_running_controls(self, running: bool) -> None:
        for selector in (
            "#first-run-hermes-version",
            "#first-run-hermes-provider",
            "#first-run-hermes-model",
            "#first-run-hermes-auth-method",
            "#first-run-hermes-api-key",
            "#first-run-hermes-retry",
            "#first-run-hermes-next",
        ):
            try:
                widget = self.query_one(selector)
                widget.disabled = running  # type: ignore[attr-defined]
            except Exception:
                continue
        try:
            self.query_one("#first-run-hermes-oauth-button", Button).disabled = False
        except Exception:
            pass

    def _advance_first_run_hermes_step(self) -> None:
        if not self._hermes_live_metadata_synced:
            self._set_first_run_hermes_step_status(
                "Sync Hermes live metadata successfully before continuing.", color="red"
            )
            self._refresh_first_run_sidebar()
            return
        version = self.query_one("#first-run-hermes-version", Select).value
        provider = self.query_one("#first-run-hermes-provider", Select).value
        model = self.query_one("#first-run-hermes-model", Select).value
        auth_method = self.query_one("#first-run-hermes-auth-method", Select).value
        api_key = self.query_one("#first-run-hermes-api-key", Input).value
        release_tag = self._hermes_live_version_tags.get(version) if isinstance(version, str) else ""
        if auth_method == "oauth" and not (
            isinstance(version, str)
            and isinstance(provider, str)
            and release_tag
            and self.config_flow.has_current_hermes_oauth_artifact(
                agent_version=version,
                agent_release_tag=release_tag,
                provider=provider,
                auth_method="oauth",
            )
        ):
            self._set_first_run_hermes_step_status("Run OAuth again for current Hermes selection.", color="red")
            self._refresh_first_run_sidebar()
            self._refresh_first_run_hermes_next_state()
            return
        result = self.config_flow.set_hermes(
            agent_version=version if isinstance(version, str) else "",
            provider=provider if isinstance(provider, str) else "",
            model=model if isinstance(model, str) else "",
            auth_method=cast("HermesAuthMode", auth_method)
            if auth_method in ("oauth", "api_key")
            else "oauth",
            api_key=api_key,
        )
        if not result.ok:
            self._set_first_run_hermes_step_status(result.message, color="red")
            self._refresh_first_run_sidebar()
            return
        self._set_first_run_hermes_step_status(result.message)
        self._render_first_run_gateways_step()

    def _render_first_run_gateways_step(self) -> None:
        self._hide_first_run_step_body()
        self.config_flow.current_step = "telegram"
        main = self._first_run_step_main()
        self.query_one("#first-run-step-title", Static).update(
            "First-run configuration wizard: Gateways"
        )
        token_present = self.config_flow.draft.gateway.telegram_bot_token.present
        token_label = "Existing Telegram bot token" if token_present else "Enter Telegram bot token"
        token_placeholder = (
            "Paste Telegram bot token to replace existing one"
            if token_present
            else "Paste Telegram bot token"
        )
        main.mount(
            Static("Telegram gateway", classes="panel-title", id="first-run-gateways-kind-title"),
            Static(
                "How to get Telegram token\n"
                "1) Message @BotFather in Telegram.\n"
                "2) Create or choose a bot.\n"
                "3) Paste the bot token below.",
                id="first-run-telegram-token-help",
            ),
            self._first_run_spacer("first-run-telegram-token-help-spacer"),
            Label(token_label, id="first-run-telegram-token-label"),
            self._first_run_spacer("first-run-telegram-token-spacer"),
            Input(
                placeholder=token_placeholder,
                password=True,
                id="first-run-telegram-token",
            ),
            self._first_run_spacer("first-run-telegram-token-after-spacer"),
            Static(
                "How to get Telegram ID\n"
                "Message @userinfobot for your user ID or @rawdatabot for a group/chat ID.\n"
                "Multiple IDs are supported as comma-separated numeric IDs.",
                id="first-run-telegram-id-help",
            ),
            Label("Telegram allowed chat/user IDs"),
            Static(
                "Use comma-separated numeric IDs. Groups/channels often start with -100.",
                id="first-run-telegram-allowlist-helper",
            ),
            self._first_run_spacer("first-run-telegram-allowlist-spacer"),
            Input(
                value=self.config_flow.draft.gateway.telegram_allowlist_ids,
                placeholder="123456789,-1001234567890",
                id="first-run-telegram-allowlist",
            ),
            self._first_run_spacer("first-run-telegram-allowlist-after-spacer"),
            Button(
                "Next: Review",
                id="first-run-gateways-next",
                variant="primary",
                disabled=True,
            ),
            self._first_run_spacer("first-run-gateways-next-after-spacer"),
            Static("", id="first-run-gateways-step-status"),
        )
        self._refresh_first_run_gateways_next_state()
        self._refresh_first_run_sidebar()

    def _effective_telegram_token(self) -> str:
        try:
            token = self.query_one("#first-run-telegram-token", Input).value.strip()
        except Exception:
            token = ""
        if token:
            return token
        if not self.config_flow.draft.gateway.telegram_bot_token.present:
            return ""
        return self.config_flow.draft.original_env.get("TELEGRAM_BOT_TOKEN", "").strip()

    def _refresh_first_run_gateways_next_state(self) -> None:
        try:
            button = self.query_one("#first-run-gateways-next", Button)
            token_present = bool(self._effective_telegram_token())
            allowlist = self.query_one("#first-run-telegram-allowlist", Input).value.strip()
            button.disabled = self._telegram_validation_loading or not (
                token_present and bool(allowlist) and logic.is_valid_telegram_allowlist(allowlist)
            )
        except Exception:
            return

    def _set_first_run_gateways_step_status(self, message: str, *, color: str = "white") -> None:
        try:
            status = self.query_one("#first-run-gateways-step-status", Static)
            status.update(message)
            status.styles.color = color
        except Exception:
            return

    def _advance_first_run_gateways_step(self) -> None:
        if self._telegram_validation_loading:
            return
        token = self.query_one("#first-run-telegram-token", Input).value.strip()
        allowlist = self.query_one("#first-run-telegram-allowlist", Input).value.strip()
        effective_token = self._effective_telegram_token()
        if not effective_token:
            self._set_first_run_gateways_step_status("Missing Telegram bot token.", color="red")
            self._refresh_first_run_gateways_next_state()
            return
        if not allowlist or not logic.is_valid_telegram_allowlist(allowlist):
            self._set_first_run_gateways_step_status(
                "Telegram allowlist must contain comma-separated numeric IDs.", color="red"
            )
            self._refresh_first_run_gateways_next_state()
            return
        request = self.config_flow.begin_telegram_validation(
            token=effective_token,
            allowlist_ids=allowlist,
            replacement_token=token or None,
        )
        self._telegram_validation_loading = True
        self._start_telegram_status_animation("Checking Telegram gateway...")
        self._refresh_first_run_gateways_next_state()

        def validate() -> tuple[TelegramGatewayValidationResult, AsyncValidationResult]:
            result = self.telegram_gateway_validator.validate_bot_token(effective_token)
            async_result = (
                AsyncValidationResult.success(
                    request_id=request.request_id,
                    fingerprint=request.fingerprint,
                    detail=result.summary,
                )
                if result.ok
                else AsyncValidationResult.failure(
                    request_id=request.request_id,
                    fingerprint=request.fingerprint,
                    detail=result.summary,
                )
            )
            return result, async_result

        _ = self.run_worker(validate, name="first-run-telegram-validation", thread=True)

    def _render_first_run_review_step(self) -> None:
        self._hide_first_run_step_body()
        self.config_flow.current_step = "review_apply"
        review = self.config_flow.review()
        self.query_one("#first-run-step-title", Static).update(
            "First-run configuration wizard: Review"
        )
        action_lines = "\n".join(self.config_flow.review_action_lines())
        self._first_run_step_main().mount(
            Static("Review / Apply", classes="panel-title", id="first-run-review-title"),
            Static(review.redacted_diff, id="first-run-review-diff"),
            Static(action_lines, id="first-run-review-action-lines"),
            Static("No .env changes are written until Apply.", id="first-run-review-helper"),
            Static("No Deployment runs automatically.", id="first-run-review-deploy-helper"),
            Button(
                "Apply configuration",
                id="first-run-review-apply",
                variant="primary",
                disabled=not review.can_apply,
            ),
            Static("", id="first-run-apply-status"),
        )
        if not review.can_apply:
            self._set_first_run_apply_status("\n".join(review.blocking_issues), color="red")
        self._refresh_first_run_sidebar()

    def _set_first_run_apply_status(self, message: str, *, color: str = "white") -> None:
        try:
            status = self.query_one("#first-run-apply-status", Static)
            status.update(message)
            status.styles.color = color
        except Exception:
            return

    def _apply_first_run_review_configuration(self) -> None:
        if self._first_run_apply_loading:
            return
        review = self.config_flow.review()
        if not review.can_apply:
            self._set_first_run_apply_status("\n".join(review.blocking_issues), color="red")
            return
        self._first_run_apply_loading = True
        try:
            self.query_one("#first-run-review-apply", Button).disabled = True
        except Exception:
            pass
        self._set_first_run_apply_status("Applying configuration...")

        def progress(message: str) -> None:
            _ = self.call_from_thread(self._set_first_run_apply_status, message)

        def run_apply() -> ConfigApplyResult:
            return self.config_flow.apply_review(review, progress=progress)

        self.run_worker(
            run_apply,
            name="first-run-config-apply",
            group="first-run-config-apply",
            thread=True,
            exclusive=True,
        )

    def _finish_first_run_config_apply(self, result: ConfigApplyResult) -> None:
        self._first_run_apply_loading = False
        if not result.ok:
            try:
                self.query_one("#first-run-review-apply", Button).disabled = False
            except Exception:
                pass
            self._set_first_run_apply_status(result.message, color="red")
            return
        self._set_first_run_apply_status("\n".join(result.status_lines))

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
