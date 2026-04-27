#!/usr/bin/env python3
# pyright: reportAny=false, reportUnusedCallResult=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportUnannotatedClassAttribute=false, reportUnusedImport=false, reportRedeclaration=false, reportPrivateUsage=false
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import ClassVar, cast, final

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Select,
    Static,
)
from scripts.configure_async import CorrelatedTask
from scripts.configure_flow import FlowCoordinator
from scripts.configure_services import (
    ConfigureOrchestrator,
    ConfigureOrchestratorLike,
    ConfigureServiceError,
)
from scripts.configure_state import (
    LabeledValue,
    WizardState,
    choose_seed,
    rotate_to_seed,
)
from scripts.configure_steps import EXTRACTED_CONTROLLERS
from scripts.toolchain_guard import ensure_expected_toolchain_runtime
from scripts.wizard_framework import StepRegistry

_HERMES_LOADING_MODEL_SENTINEL = "__loading__"


class ConfirmExitScreen(ModalScreen[bool]):
    CSS: ClassVar[str] = """
    ConfirmExitScreen { align: center middle; }
    #confirm-exit { width: 56; height: auto; max-height: 9; border: round #8a70ff; background: #0e1019 70%; padding: 1 2; }
    #confirm-exit-buttons { height: auto; align: center middle; margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-exit"):
            yield Label("Exit configuration wizard? Unsaved changes will be lost.")
            with Horizontal(id="confirm-exit-buttons"):
                yield Button("Stay", id="stay", variant="primary")
                yield Button("Exit", id="exit", variant="error")

    @on(Button.Pressed, "#stay")
    def _stay(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#exit")
    def _exit(self) -> None:
        self.dismiss(True)


@final
class CloudLoaded(Message):
    def __init__(
        self,
        locations: list[LabeledValue],
        server_types: list[LabeledValue],
        error: str = "",
        request_id: int = 0,
    ) -> None:
        super().__init__()
        self.locations = locations
        self.server_types = server_types
        self.error = error
        self.request_id = request_id


@final
class HermesLoaded(Message):
    def __init__(
        self,
        providers: list[str],
        models: list[str],
        resolved_provider: str,
        auth_type: str,
        auth_env_vars: list[str],
        request_id: int = 0,
        error: str = "",
    ) -> None:
        super().__init__()
        self.providers = providers
        self.models = models
        self.resolved_provider = resolved_provider
        self.auth_type = auth_type
        self.auth_env_vars = auth_env_vars
        self.request_id = request_id
        self.error = error


@final
class HermesOAuthProgress(Message):
    def __init__(self, chunk: str) -> None:
        super().__init__()
        self.chunk = chunk


@final
class HermesOAuthFinished(Message):
    def __init__(self, success: bool, output: str) -> None:
        super().__init__()
        self.success = success
        self.output = output


@final
class HermesApiKeyValidated(Message):
    def __init__(self, status: str = "", error: str = "", request_id: int = 0) -> None:
        super().__init__()
        self.status = status
        self.error = error
        self.request_id = request_id


@final
class TelegramValidated(Message):
    def __init__(self, status: str = "", error: str = "", request_id: int = 0) -> None:
        super().__init__()
        self.status = status
        self.error = error
        self.request_id = request_id


def _selected_text(value: object) -> str:
    return value if isinstance(value, str) else ""


@dataclass(frozen=True)
class StepMeta:
    key: str
    title: str


class ConfigureTUI(App[list[tuple[str, str, str]] | None]):
    TITLE = "hermes-vps configuration"
    SUB_TITLE = "Textual wizard"
    root_dir: pathlib.Path
    orchestrator: ConfigureOrchestratorLike
    state: WizardState
    _coordinator: FlowCoordinator
    _step_registry: StepRegistry
    location_options: list[LabeledValue]
    server_type_options: list[LabeledValue]
    hermes_provider_options: list[str]
    hermes_model_options: list[str]
    _cloud_loading: bool
    _hermes_loading: bool
    _telegram_loading: bool
    _ui_ready: bool
    _pending_cloud_validation_next: bool
    _pending_telegram_validation_next: bool
    _pending_cloud_validation_request_id: int | None
    _cloud_task: CorrelatedTask
    _hermes_metadata_task: CorrelatedTask
    _telegram_task: CorrelatedTask
    _hermes_api_key_task: CorrelatedTask
    _hermes_api_key_validating: bool
    _pending_hermes_api_key_validation_next: bool
    _suppress_hermes_provider_change: bool
    _pending_hermes_provider: str | None
    _hermes_provider_select_initialized: bool
    _hermes_oauth_running: bool
    _hermes_oauth_output: str
    _rendering_step: bool
    _pending_step_render: bool
    _restore_next_focus_when_enabled: bool
    CSS = """
    Screen { background: #090b12; color: #f4f7ff; }
    #root { height: 1fr; }
    #rail { width: 34; border: round #2f4cff 40%; background: #0e1326; padding: 1 1; margin-right: 1; }
    .step-item { padding: 0 1; color: #9ca6c9; margin-bottom: 1; }
    .step-current { color: #d8d7ff; background: #293363 45%; text-style: bold; }
    .step-complete { color: #7be8bd; }
    #content { border: round #8a70ff 50%; background: #11162b; padding: 1 2; }
    .section-title { color: #82a5ff; text-style: bold; margin-bottom: 1; }
    .hint { color: #8ca3cb; margin-bottom: 1; }
    .success-note { color: #87f7c7; }
    .error-text { color: #ff8fa3; margin: 0 0 1 0; }
    #action-bar { height: auto; margin-top: 1; align: right middle; }
    #status { color: #87f7c7; margin-top: 1; }
    Input, Select, Checkbox { margin-bottom: 1; }
    """

    BINDINGS = [
        ("enter", "next", "Next"),
        ("ctrl+b", "back", "Back"),
        ("escape", "cancel", "Cancel"),
    ]

    steps = [
        StepMeta("cloud", "Cloud"),
        StepMeta("server", "Server"),
        StepMeta("hermes", "Hermes"),
        StepMeta("telegram", "Telegram"),
        StepMeta("review", "Review"),
    ]

    current_step = reactive(0)

    def __init__(
        self, root_dir: pathlib.Path, orchestrator: ConfigureOrchestratorLike | None = None
    ) -> None:
        super().__init__()
        self.root_dir = root_dir
        self.orchestrator: ConfigureOrchestratorLike = (
            orchestrator
            if orchestrator is not None
            else cast(ConfigureOrchestratorLike, cast(object, ConfigureOrchestrator(root_dir)))
        )
        self.state: WizardState = self.orchestrator.load_initial_state()
        self._coordinator = FlowCoordinator(step_count=len(self.steps))
        self._step_registry = StepRegistry()
        for controller_cls in EXTRACTED_CONTROLLERS:
            _ = self._step_registry.register(controller_cls(self))

        self.location_options: list[LabeledValue] = []
        self.server_type_options: list[LabeledValue] = []
        self.hermes_provider_options: list[str] = []
        self.hermes_model_options: list[str] = []

        self._cloud_loading = False
        self._hermes_loading = False
        self._telegram_loading = False
        self._ui_ready = False
        self._pending_cloud_validation_next = False
        self._pending_telegram_validation_next = False
        self._pending_cloud_validation_request_id: int | None = None
        self._cloud_task = CorrelatedTask()
        self._hermes_metadata_task = CorrelatedTask()
        self._telegram_task = CorrelatedTask()
        self._hermes_api_key_task = CorrelatedTask()
        self._hermes_api_key_validating = False
        self._pending_hermes_api_key_validation_next = False
        self._suppress_hermes_provider_change = False
        self._pending_hermes_provider: str | None = None
        self._hermes_provider_select_initialized = False
        self._hermes_oauth_running = False
        self._hermes_oauth_output = ""
        self._rendering_step = False
        self._pending_step_render = False
        self._restore_next_focus_when_enabled = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="root"):
            with Vertical(id="rail"):
                yield Label("wizard progress", classes="section-title")
                yield ProgressBar(total=len(self.steps), show_eta=False, id="progress")
                for idx, step in enumerate(self.steps):
                    yield Static(
                        f"{idx + 1}. {step.title}",
                        id=f"step-{idx}",
                        classes="step-item",
                    )
                yield Static(
                    "Tab/Shift+Tab navigate • Enter next • Ctrl+B back • Esc cancel\n"
                    "Hold Shift to select using the mouse, Hold Shift and Ctrl to open links with the mouse",
                    classes="hint",
                    id="rail-help",
                )
            with Vertical(id="content"):
                yield Static("", id="step-title", classes="section-title")
                yield Vertical(id="step-form")
                yield Static("", id="error", classes="error-text")
                yield Static("", id="status")
                with Horizontal(id="action-bar"):
                    yield Button("Back", id="back", variant="default")
                    yield Button("Next", id="next", variant="primary")
                    yield Button("Cancel", id="cancel", variant="error")
        yield Footer()

    @property
    def step_complete(self) -> dict[int, bool]:
        return self._coordinator.completed_steps

    @property
    def _active_cloud_request_id(self) -> int:
        return self._cloud_task.active_id

    @_active_cloud_request_id.setter
    def _active_cloud_request_id(self, value: int) -> None:
        self._cloud_task.force_active(value)

    def on_mount(self) -> None:
        return

    def on_ready(self) -> None:
        self._ui_ready = True
        if self._coordinator.current_step != self.current_step:
            self._coordinator.jump_to(self.current_step)
        self._refresh_rail()
        self._render_step()

    def watch_current_step(self, _old: int, new: int) -> None:
        if not self._ui_ready:
            return
        if self._coordinator.current_step != new:
            self._coordinator.jump_to(new)
        self.query_one("#progress", ProgressBar).update(progress=new + 1)
        self._refresh_rail()
        self._render_step()

    def _refresh_rail(self) -> None:
        for idx, _ in enumerate(self.steps):
            item = self.query_one(f"#step-{idx}", Static)
            _ = item.set_class(False, "step-current")
            _ = item.set_class(False, "step-complete")
            if idx < self.current_step or self.step_complete.get(idx):
                _ = item.set_class(True, "step-complete")
            if idx == self.current_step:
                _ = item.set_class(True, "step-current")

    def _is_next_blocked_by_loading(self) -> bool:
        step = self.steps[self.current_step].key
        if step == "cloud":
            return self._cloud_loading
        if step == "hermes":
            return (
                self._hermes_loading
                or self._hermes_oauth_running
                or self._hermes_api_key_validating
            )
        if step == "telegram":
            return self._telegram_loading
        return False

    def _refresh_next_button_state(self) -> None:
        next_button = self.query_one("#next", Button)
        was_disabled = next_button.disabled
        should_disable = self._is_next_blocked_by_loading()
        focused_id = getattr(self.focused, "id", None)

        if should_disable and not was_disabled and (
            self.focused is next_button or focused_id == "cancel"
        ):
            self._restore_next_focus_when_enabled = True

        next_button.disabled = should_disable

        if should_disable and (
            self.focused is next_button or getattr(self.focused, "id", None) == "cancel"
        ):
            self._focus_fallback_when_next_disabled()

        if not should_disable and was_disabled and self._restore_next_focus_when_enabled:
            self._restore_next_focus_when_enabled = False
            self.set_focus(next_button)

    def _focus_fallback_when_next_disabled(self) -> None:
        step = self.steps[self.current_step].key
        fallback_focus_id = {
            "cloud": "provider-select",
            "server": "location-select",
            "hermes": "hermes-version-input",
            "telegram": "telegram-token-input",
        }.get(step)
        if not fallback_focus_id:
            return
        try:
            target = self.query_one(f"#{fallback_focus_id}")
        except NoMatches:
            return
        if getattr(target, "disabled", False):
            return
        self.set_focus(target)

    def _render_step(self) -> None:
        if self._rendering_step:
            self._pending_step_render = True
            return

        self._rendering_step = True
        try:
            self.query_one("#step-title", Static).update(
                f"Step {self.current_step + 1}/{len(self.steps)} • {self.steps[self.current_step].title}"
            )
            self.query_one("#error", Static).update("")
            self.query_one("#status", Static).update("")

            form = self.query_one("#step-form", Vertical)
            form.remove_children()

            step = self.steps[self.current_step].key
            controller = self._step_registry.get(step)
            if controller is not None:
                _ = controller.mount(form)
            elif step == "cloud":
                self._mount_cloud(form)
                if not self._cloud_loading:
                    _ = self._load_cloud_options()
            elif step == "hermes":
                self._mount_hermes(form)
                _ = self.call_after_refresh(self._refresh_hermes_provider_model_ui)
                if not self._hermes_loading and (
                    not self.hermes_provider_options or not self.hermes_model_options
                ):
                    _ = self._load_hermes_options()

            self.query_one("#back", Button).disabled = self.current_step == 0
            self.query_one("#next", Button).label = (
                "Apply" if self.current_step == len(self.steps) - 1 else "Next"
            )
            self._refresh_next_button_state()
        finally:
            self._rendering_step = False

        if self._pending_step_render:
            self._pending_step_render = False
            self.call_after_refresh(self._render_step)

    def _mount_cloud(self, form: Vertical) -> None:
        present = self.orchestrator.provider_token_present(self.state)
        provider_name = "Hetzner" if self.state.provider == "hetzner" else "Linode"
        token_title = "Existing provider token" if present else "Enter provider token"
        token_placeholder = (
            "Paste provider token to replace existing one"
            if present
            else "Paste provider token"
        )

        form.mount(Label("Choose a cloud provider", classes="section-title"))
        form.mount(
            Select[str](
                options=[("hetzner", "hetzner"), ("linode", "linode")],
                allow_blank=False,
                value=self.state.provider,
                id="provider-select",
            )
        )

        form.mount(
            Label(
                f"How to get your {provider_name} token",
                classes="section-title",
                id="provider-token-help-title",
            )
        )
        form.mount(
            Static(
                self._provider_token_help_text(self.state.provider),
                classes="hint",
                id="provider-token-help-text",
            )
        )

        form.mount(
            Label(token_title, classes="section-title", id="provider-token-title")
        )
        form.mount(
            Input(
                password=True,
                value=self.state.provider_token_input,
                placeholder=token_placeholder,
                id="provider-token-input",
            )
        )
        form.mount(
            Static(
                f"Server image mapping: {self.state.server_image}",
                classes="hint",
                id="server-image-hint",
            )
        )

    @staticmethod
    def _provider_token_help_text(provider: str) -> str:
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

    def _refresh_cloud_provider_dependent_ui(self) -> None:
        present = self.orchestrator.provider_token_present(self.state)
        provider_name = "Hetzner" if self.state.provider == "hetzner" else "Linode"
        token_title = "Existing provider token" if present else "Enter provider token"
        token_placeholder = (
            "Paste provider token to replace existing one"
            if present
            else "Paste provider token"
        )

        self.query_one("#provider-token-help-title", Label).update(
            f"How to get your {provider_name} token"
        )
        self.query_one("#provider-token-help-text", Static).update(
            self._provider_token_help_text(self.state.provider)
        )
        token_title_widget = self.query_one("#provider-token-title", Label)
        token_title_widget.update(token_title)
        token_input = self.query_one("#provider-token-input", Input)
        token_input.value = self.state.provider_token_input
        token_input.placeholder = token_placeholder
        self.query_one("#server-image-hint", Static).update(
            f"Server image mapping: {self.state.server_image}"
        )
        self.query_one("#error", Static).update("")

    def _mount_hermes(self, form: Vertical) -> None:
        form.mount(Label("Hermes agent version", classes="section-title"))
        form.mount(
            Input(
                value=self.state.hermes_agent_version,
                placeholder="Hermes Agent version",
                id="hermes-version-input",
            )
        )

        form.mount(Label("Provider", classes="section-title"))
        provider_values = list(self.hermes_provider_options)
        if not provider_values and self.state.hermes_provider:
            provider_values = [self.state.hermes_provider]
        provider_options = [(item, item) for item in provider_values]
        provider_seed = (
            self.state.hermes_provider
            if self.state.hermes_provider in provider_values
            else Select.BLANK
        )
        provider_select = Select[str](
            options=provider_options,
            allow_blank=not bool(provider_options),
            id="hermes-provider-select",
            value=provider_seed,
        )
        if provider_values:
            seed_provider = choose_seed(
                provider_values,
                existing=self.state.hermes_provider,
                preferred="openai-codex",
            )
            self._suppress_hermes_provider_change = True
            try:
                provider_select.value = seed_provider
                self.state.hermes_provider = seed_provider
            finally:
                self._suppress_hermes_provider_change = False
        form.mount(provider_select)
        # New Select instance is mounted on each step render; force one post-mount
        # sync pass so provider options/value are always re-applied to this widget.
        self._hermes_provider_select_initialized = False

        form.mount(Label("Model", classes="section-title"))
        model_values = list(self.hermes_model_options)
        if model_values:
            seed_model = choose_seed(
                model_values, existing=self.state.hermes_model, preferred="gpt-5.4-mini"
            )
            ordered_models = rotate_to_seed(model_values, seed_model)
            model_options = [(item, item) for item in ordered_models]
            self.state.hermes_model = ordered_models[0]
        else:
            model_options = []

        model_seed = (
            self.state.hermes_model
            if self.state.hermes_model in [item for item in model_values]
            else Select.BLANK
        )
        model_select = Select[str](
            options=model_options,
            allow_blank=not bool(model_options),
            id="hermes-model-select",
            value=model_seed,
        )
        form.mount(model_select)

        form.mount(Label("Athentification", classes="section-title"))
        auth_methods = self.orchestrator.hermes_available_auth_methods(
            self.state.hermes_auth_type
        )
        selected = self._seed_hermes_auth_method(auth_methods)
        auth_options = [("API key", "api_key"), ("OAuth", "oauth")]
        auth_options = [pair for pair in auth_options if pair[1] in auth_methods]
        auth_select = Select[str](
            options=auth_options,
            allow_blank=False,
            id="hermes-auth-method-select",
            value=selected,
        )
        form.mount(auth_select)

        auth_section = Vertical(
            Label("", classes="section-title", id="hermes-auth-choice-title"),
            Input(
                password=True,
                value=self.state.hermes_api_key_input,
                id="hermes-api-key-input",
            ),
            Button(
                "Start OAuth authentication",
                id="hermes-oauth-button",
                variant="primary",
            ),
            id="hermes-auth-section",
        )
        form.mount(auth_section)
        self._refresh_hermes_auth_section()

        form.mount(
            Static(self._hermes_oauth_output, classes="hint", id="hermes-oauth-output")
        )

    def _seed_hermes_auth_method(self, auth_methods: list[str]) -> str:
        existing_for_combo = self.orchestrator.hermes_existing_auth_method_for_combo(
            self.state
        )
        if existing_for_combo and existing_for_combo in auth_methods:
            self.state.hermes_auth_method = existing_for_combo
            return existing_for_combo
        if self.state.hermes_auth_method in auth_methods:
            return self.state.hermes_auth_method
        if "api_key" in auth_methods:
            self.state.hermes_auth_method = "api_key"
            return "api_key"
        self.state.hermes_auth_method = auth_methods[0]
        return auth_methods[0]

    def _provider_title_name(self) -> str:
        return self.state.hermes_provider or "provider"

    def _refresh_hermes_auth_section(self) -> None:
        if self.steps[self.current_step].key != "hermes":
            return
        try:
            method = self.state.hermes_auth_method
            provider_name = self._provider_title_name()
            existing_for_combo = (
                self.orchestrator.hermes_existing_auth_method_for_combo(self.state)
            )

            title = self.query_one("#hermes-auth-choice-title", Label)
            api_input = self.query_one("#hermes-api-key-input", Input)
            oauth_button = self.query_one("#hermes-oauth-button", Button)

            if method == "api_key":
                title.update("API key")
                if existing_for_combo == "api_key":
                    placeholder = (
                        f"Paste new '{provider_name}' token to replace the current one"
                    )
                else:
                    placeholder = f"Paste '{provider_name}' API key"
                api_input.placeholder = placeholder
                api_input.value = self.state.hermes_api_key_input
                api_input.display = True
                oauth_button.display = False
            else:
                title.update("OAuth")
                button_label = (
                    "Renew current OAuth token"
                    if existing_for_combo == "oauth"
                    else "Start OAuth authentication"
                )
                oauth_button.label = button_label
                oauth_button.disabled = self._hermes_oauth_running
                oauth_button.display = True
                api_input.display = False
        except NoMatches:
            self.set_timer(0.05, self._refresh_hermes_auth_section)

    def _refresh_hermes_provider_model_ui(self) -> None:
        if self.steps[self.current_step].key != "hermes":
            return

        try:
            provider_select = cast(Select[str], self.query_one("#hermes-provider-select", Select))
            model_select = cast(Select[str], self.query_one("#hermes-model-select", Select))

            provider_values = list(self.hermes_provider_options)
            if not provider_values:
                staged_provider = self.state.hermes_provider.strip()
                if staged_provider:
                    provider_values = [staged_provider]
            provider_options = [(item, item) for item in provider_values]
            if provider_options:
                existing_provider = self.state.hermes_provider
                if not existing_provider and provider_select.value not in ("", Select.BLANK):
                    existing_provider = _selected_text(provider_select.value)
                seed_provider = choose_seed(
                    provider_values,
                    existing=existing_provider,
                    preferred="openai-codex",
                )
                self._suppress_hermes_provider_change = True
                try:
                    if not self._hermes_provider_select_initialized:
                        provider_select.set_options(provider_options)
                        self._hermes_provider_select_initialized = True
                    if provider_select.value != seed_provider:
                        provider_select.value = seed_provider
                    self.state.hermes_provider = seed_provider
                finally:
                    self._suppress_hermes_provider_change = False

            model_values = list(self.hermes_model_options)
            if model_values:
                seed_model = choose_seed(
                    model_values,
                    existing=self.state.hermes_model,
                    preferred="gpt-5.4-mini",
                )
                ordered_models = rotate_to_seed(model_values, seed_model)
                model_select.set_options([(item, item) for item in ordered_models])
                model_select.value = ordered_models[0]
                self.state.hermes_model = ordered_models[0]

            auth_methods = self.orchestrator.hermes_available_auth_methods(
                self.state.hermes_auth_type
            )
            auth_select = cast(Select[str], self.query_one("#hermes-auth-method-select", Select))
            auth_options = [("API key", "api_key"), ("OAuth", "oauth")]
            auth_options = [pair for pair in auth_options if pair[1] in auth_methods]
            auth_select.set_options(auth_options)
            self.state.hermes_auth_method = self._seed_hermes_auth_method(auth_methods)
            auth_select.value = self.state.hermes_auth_method
            self._refresh_hermes_auth_section()
            self.query_one("#hermes-oauth-output", Static).update(
                self._hermes_oauth_output
            )

            self.query_one("#status", Static).update("Hermes metadata loaded.")
        except NoMatches:
            self.set_timer(0.05, self._refresh_hermes_provider_model_ui)

    @on(Button.Pressed, "#next")
    def _next_btn(self) -> None:
        self.action_next()

    @on(Button.Pressed, "#back")
    def _back_btn(self) -> None:
        self.action_back()

    @on(Button.Pressed, "#cancel")
    def _cancel_btn(self) -> None:
        self.action_cancel()

    def action_next(self) -> None:
        if self._cloud_loading:
            return
        if self._hermes_loading and self.steps[self.current_step].key == "hermes":
            self.query_one("#status", Static).update("Loading Hermes metadata...")
            return
        if self._hermes_oauth_running and self.steps[self.current_step].key == "hermes":
            self.query_one("#status", Static).update("OAuth flow is running...")
            return
        if self._hermes_api_key_validating and self.steps[self.current_step].key == "hermes":
            self.query_one("#status", Static).update("Validating Hermes API key...")
            return
        if self._telegram_loading and self.steps[self.current_step].key == "telegram":
            self.query_one("#status", Static).update(
                "Validating Telegram token and allowlist..."
            )
            return

        if not self._capture_state_from_widgets():
            return

        errors = self._step_errors()
        if errors:
            self.query_one("#error", Static).update("; ".join(errors.values()))
            return

        current_step_key = self.steps[self.current_step].key

        if current_step_key == "cloud":
            if self._cloud_next_requires_live_token_validation():
                self.query_one("#error", Static).update("")
                self._load_cloud_options(validate_for_next=True)
                return
            self._persist_cloud_step_and_advance()
            return

        if current_step_key == "server":
            try:
                self.orchestrator.persist_server_step(self.state)
            except ConfigureServiceError as exc:
                self.query_one("#error", Static).update(str(exc))
                return

        if current_step_key == "hermes":
            if self.state.hermes_auth_method == "api_key":
                self._pending_hermes_api_key_validation_next = True
                self.query_one("#error", Static).update("")
                self._validate_hermes_api_key_step()
                return
            existing_auth = self.orchestrator.hermes_existing_auth_method_for_combo(
                self.state
            )
            if existing_auth != "oauth":
                self.query_one("#error", Static).update(
                    "Run OAuth authentication before continuing."
                )
                return
            try:
                self.orchestrator.persist_hermes_step(self.state)
            except ConfigureServiceError as exc:
                self.query_one("#error", Static).update(str(exc))
                return

        if current_step_key == "telegram":
            self._pending_telegram_validation_next = True
            self.query_one("#error", Static).update("")
            self._validate_telegram_step()
            return

        self._advance_and_render()

    def _advance_and_render(self) -> None:
        result = self._coordinator.advance()
        if result.finished:
            self._apply_and_exit()
            return
        self.current_step = result.next_step

    def _cloud_next_requires_live_token_validation(self) -> bool:
        token_present = self.orchestrator.provider_token_present(self.state)
        return (not token_present) or bool(self.state.provider_token_input)

    def _persist_cloud_step_and_advance(self) -> None:
        try:
            self.orchestrator.persist_cloud_step(self.state)
        except ConfigureServiceError as exc:
            self.query_one("#error", Static).update(str(exc))
            self._pending_cloud_validation_next = False
            return

        self._advance_and_render()

    def _persist_telegram_step_and_advance(self) -> None:
        try:
            self.orchestrator.persist_telegram_step(self.state)
        except ConfigureServiceError as exc:
            self.query_one("#error", Static).update(str(exc))
            self._pending_telegram_validation_next = False
            return

        self._advance_and_render()

    def action_back(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        result = self._coordinator.back()
        if result.next_step != self.current_step:
            self.current_step = result.next_step

    def action_cancel(self) -> None:
        self.push_screen(
            ConfirmExitScreen(),
            lambda should_exit: self.exit(None) if should_exit else None,
        )

    def _capture_state_from_widgets(self) -> bool:
        step = self.steps[self.current_step].key
        controller = self._step_registry.get(step)
        if controller is not None:
            return controller.capture()
        try:
            if step == "cloud":
                provider_select = cast(Select[str], self.query_one("#provider-select", Select))
                self.state.provider = _selected_text(provider_select.value)
                self.state.server_image = (
                    "debian-13"
                    if self.state.provider == "hetzner"
                    else "linode/debian13"
                )
                self.state.provider_token_input = self.query_one(
                    "#provider-token-input", Input
                ).value.strip()
                token_present = self.orchestrator.provider_token_present(self.state)
                self.state.provider_token_replace = not token_present or bool(
                    self.state.provider_token_input
                )
            elif step == "hermes":
                self.state.hermes_agent_version = self.query_one(
                    "#hermes-version-input", Input
                ).value.strip()
                self.state.hermes_agent_release_tag = (
                    self.orchestrator.resolve_release_tag_for_version(
                        self.state.hermes_agent_version
                    )
                )
                provider_select = cast(Select[str], self.query_one("#hermes-provider-select", Select))
                self.state.hermes_provider = _selected_text(provider_select.value)
                model_select = cast(Select[str], self.query_one("#hermes-model-select", Select))
                model_value = _selected_text(model_select.value)
                self.state.hermes_model = (
                    "" if model_value == _HERMES_LOADING_MODEL_SENTINEL else model_value
                )
                auth_select = cast(Select[str], self.query_one("#hermes-auth-method-select", Select))
                self.state.hermes_auth_method = _selected_text(auth_select.value) or "api_key"
                if self.state.hermes_auth_method == "api_key":
                    self.state.hermes_api_key_input = self.query_one(
                        "#hermes-api-key-input", Input
                    ).value.strip()
                    self.state.hermes_api_key_replace = bool(
                        self.state.hermes_api_key_input
                    )
                else:
                    self.state.hermes_api_key_replace = False
        except Exception as exc:
            self.query_one("#error", Static).update(str(exc))
            return False
        return True

    def _step_errors(self) -> dict[str, str]:
        key = self.steps[self.current_step].key
        controller = self._step_registry.get(key)
        if controller is not None:
            return controller.validate()
        if key == "cloud":
            return self.state.validate_cloud()
        if key == "hermes":
            return self.state.validate_hermes()
        return {}

    def _apply_and_exit(self) -> None:
        try:
            rows = self.orchestrator.apply(self.state)
        except ConfigureServiceError as exc:
            self.query_one("#error", Static).update(str(exc))
            return
        self.exit(rows)

    @on(Select.Changed, "#provider-select")
    def _provider_changed(self, event: Select.Changed) -> None:
        new_provider = _selected_text(event.value)
        if not new_provider:
            return

        self.state.provider = _selected_text(event.value)
        self.state.server_image = (
            "debian-13" if self.state.provider == "hetzner" else "linode/debian13"
        )
        self.state.provider_token_input = ""
        self.state.provider_token_replace = False
        if self.steps[self.current_step].key == "cloud":
            self._refresh_cloud_provider_dependent_ui()
            self._load_cloud_options()

    @on(Select.Changed, "#location-select")
    def _location_changed(self, event: Select.Changed) -> None:
        self.state.location = _selected_text(event.value)
        self._load_cloud_options(server_types_only=True, quiet=True)

    @on(Select.Changed, "#hermes-provider-select")
    def _hermes_provider_changed(self, event: Select.Changed) -> None:
        if self._suppress_hermes_provider_change:
            return
        new_provider_value = event.value
        if not isinstance(new_provider_value, str) or not new_provider_value:
            return
        if new_provider_value == self.state.hermes_provider:
            return
        self.state.hermes_provider = new_provider_value
        self._pending_hermes_provider = new_provider_value
        self.state.hermes_model = ""
        self._hermes_oauth_output = ""
        self.hermes_model_options = []
        self.query_one("#status", Static).update("Loading Hermes metadata...")
        self.query_one("#hermes-oauth-output", Static).update("")
        model_select = cast(Select[str], self.query_one("#hermes-model-select", Select))
        model_select.set_options(
            [("Loading models...", _HERMES_LOADING_MODEL_SENTINEL)]
        )
        model_select.value = _HERMES_LOADING_MODEL_SENTINEL
        self._load_hermes_options(models_only=True, provider_override=new_provider_value)

    @on(Select.Changed, "#hermes-model-select")
    def _hermes_model_changed(self, event: Select.Changed) -> None:
        model_value = _selected_text(event.value)
        if not model_value or model_value == _HERMES_LOADING_MODEL_SENTINEL:
            return
        self.state.hermes_model = model_value
        self.state.hermes_auth_method = self._seed_hermes_auth_method(
            self.orchestrator.hermes_available_auth_methods(self.state.hermes_auth_type)
        )
        self._refresh_hermes_auth_section()

    @on(Select.Changed, "#hermes-auth-method-select")
    def _hermes_auth_method_changed(self, event: Select.Changed) -> None:
        method = _selected_text(event.value) or "api_key"
        if method not in {"api_key", "oauth"}:
            return
        self.state.hermes_auth_method = method
        self._refresh_hermes_auth_section()

    @on(Button.Pressed, "#hermes-oauth-button")
    def _hermes_oauth_button_pressed(self) -> None:
        if self._hermes_oauth_running:
            return
        provider = self.state.hermes_provider
        if not provider:
            self.query_one("#error", Static).update(
                "Choose Hermes provider before OAuth."
            )
            return
        self._hermes_oauth_running = True
        self._refresh_next_button_state()
        self.query_one("#error", Static).update("")
        self.query_one("#status", Static).update("Running Hermes OAuth flow...")
        self._hermes_oauth_output = (
            "Starting OAuth authentication...\nWaiting for Hermes CLI output...\n"
        )
        self._refresh_hermes_auth_section()
        self.query_one("#hermes-oauth-output", Static).update(self._hermes_oauth_output)
        self._run_hermes_oauth_worker(provider)

    @on(CloudLoaded)
    def _cloud_loaded(self, message: CloudLoaded) -> None:
        if not self._cloud_task.is_current(message.request_id):
            return

        self._cloud_loading = False
        self._refresh_next_button_state()
        if message.error:
            if (
                self.steps[self.current_step].key == "cloud"
                or self._pending_cloud_validation_next
            ):
                self.query_one("#error", Static).update(message.error)
            self._pending_cloud_validation_next = False
            self._pending_cloud_validation_request_id = None
            return
        self.location_options = message.locations
        self.server_type_options = message.server_types
        if (
            self._pending_cloud_validation_next
            and self._pending_cloud_validation_request_id == message.request_id
            and self.steps[self.current_step].key == "cloud"
        ):
            self._pending_cloud_validation_next = False
            self._pending_cloud_validation_request_id = None
            self._persist_cloud_step_and_advance()
            return
        if self.steps[self.current_step].key == "cloud":
            provider_name = "Hetzner" if self.state.provider == "hetzner" else "Linode"
            self.query_one("#status", Static).update(f"{provider_name} token is valid.")

    @on(HermesLoaded)
    def _hermes_loaded(self, message: HermesLoaded) -> None:
        if message.request_id and not self._hermes_metadata_task.is_current(message.request_id):
            return
        self._hermes_loading = False
        self._refresh_next_button_state()
        if message.error:
            self.query_one("#error", Static).update(message.error)
            return

        requested_provider = self._pending_hermes_provider
        if requested_provider and requested_provider != message.resolved_provider:
            self._load_hermes_options(
                models_only=True, provider_override=requested_provider
            )
            return

        previous_providers = list(self.hermes_provider_options)
        self.hermes_provider_options = message.providers
        if previous_providers != message.providers:
            self._hermes_provider_select_initialized = False
        current_provider = self.state.hermes_provider
        if (
            current_provider
            and current_provider in message.providers
            and message.resolved_provider != current_provider
        ):
            self._load_hermes_options(
                models_only=True, provider_override=current_provider
            )
            return

        self.hermes_model_options = message.models
        self.state.hermes_provider = message.resolved_provider
        self.state.hermes_auth_type = message.auth_type
        if message.models:
            self.state.hermes_model = choose_seed(
                message.models,
                existing=self.state.hermes_model,
                preferred="gpt-5.4-mini",
            )
        self.state.hermes_auth_method = self._seed_hermes_auth_method(
            self.orchestrator.hermes_available_auth_methods(self.state.hermes_auth_type)
        )
        if self.steps[self.current_step].key == "hermes":
            self.call_after_refresh(self._refresh_hermes_provider_model_ui)

    @on(HermesOAuthProgress)
    def _hermes_oauth_progress(self, message: HermesOAuthProgress) -> None:
        self._hermes_oauth_output = f"{self._hermes_oauth_output}{message.chunk}"
        self.query_one("#hermes-oauth-output", Static).update(self._hermes_oauth_output)

    @on(HermesOAuthFinished)
    def _hermes_oauth_finished(self, message: HermesOAuthFinished) -> None:
        self._hermes_oauth_running = False
        self._refresh_next_button_state()
        self._hermes_oauth_output = message.output
        self.query_one("#hermes-oauth-output", Static).update(message.output)
        if message.success:
            self.query_one("#status", Static).update("OAuth completed.")
            self.state.hermes_auth_method = "oauth"
            try:
                self.query_one("#hermes-auth-method-select", Select).value = "oauth"
            except NoMatches:
                pass
        else:
            self.query_one("#error", Static).update(
                "OAuth failed. Review output below."
            )
        self._refresh_hermes_auth_section()

    @on(HermesApiKeyValidated)
    def _hermes_api_key_validated(self, message: HermesApiKeyValidated) -> None:
        if not self._hermes_api_key_task.is_current(message.request_id):
            return
        self._hermes_api_key_validating = False
        self._refresh_next_button_state()
        if message.error:
            self.query_one("#error", Static).update(message.error)
            self._pending_hermes_api_key_validation_next = False
            return

        self.query_one("#status", Static).update(message.status)
        if (
            self._pending_hermes_api_key_validation_next
            and self.steps[self.current_step].key == "hermes"
        ):
            self._pending_hermes_api_key_validation_next = False
            try:
                self.orchestrator.persist_hermes_step(self.state)
            except ConfigureServiceError as exc:
                self.query_one("#error", Static).update(str(exc))
                return
            self._advance_and_render()

    @on(TelegramValidated)
    def _telegram_validated(self, message: TelegramValidated) -> None:
        if not self._telegram_task.is_current(message.request_id):
            return
        self._telegram_loading = False
        self._refresh_next_button_state()
        if message.error:
            self.query_one("#error", Static).update(message.error)
            self._pending_telegram_validation_next = False
            return

        self.query_one("#status", Static).update(message.status)
        if (
            self._pending_telegram_validation_next
            and self.steps[self.current_step].key == "telegram"
        ):
            self._pending_telegram_validation_next = False
            self._persist_telegram_step_and_advance()

    @work(thread=True, exclusive=True)
    def _run_hermes_oauth_worker(self, provider: str) -> None:
        def emit_progress(chunk: str) -> None:
            self.post_message(HermesOAuthProgress(chunk))

        try:
            success, output = self.orchestrator.hermes.run_oauth_add(
                provider,
                on_output=emit_progress,
            )
            self.post_message(HermesOAuthFinished(success=success, output=output))
        except Exception as exc:
            self.post_message(HermesOAuthFinished(success=False, output=str(exc)))

    def _validate_hermes_api_key_step(self) -> None:
        request_id = self._hermes_api_key_task.begin()
        self._hermes_api_key_validating = True
        self._refresh_next_button_state()
        self.query_one("#status", Static).update("Validating Hermes API key...")
        self._validate_hermes_api_key_step_worker(request_id)

    @work(thread=True, exclusive=True)
    def _validate_hermes_api_key_step_worker(self, request_id: int) -> None:
        try:
            status = self.orchestrator.validate_hermes_api_key_setup(self.state)
            self.post_message(HermesApiKeyValidated(status=status, request_id=request_id))
        except Exception as exc:
            self.post_message(HermesApiKeyValidated(error=str(exc), request_id=request_id))

    def _validate_telegram_step(self) -> None:
        request_id = self._telegram_task.begin()
        self._telegram_loading = True
        self._refresh_next_button_state()
        self.query_one("#status", Static).update(
            "Validating Telegram token and allowlist..."
        )
        self._validate_telegram_step_worker(request_id)

    @work(thread=True, exclusive=True)
    def _validate_telegram_step_worker(self, request_id: int) -> None:
        try:
            status = self.orchestrator.validate_telegram_setup(self.state)
            self.post_message(TelegramValidated(status=status, request_id=request_id))
        except Exception as exc:
            self.post_message(TelegramValidated(error=str(exc), request_id=request_id))

    def _load_cloud_options(
        self,
        server_types_only: bool = False,
        quiet: bool = False,
        validate_for_next: bool = False,
    ) -> None:
        request_id = self._cloud_task.begin()
        self._pending_cloud_validation_next = validate_for_next
        self._pending_cloud_validation_request_id = request_id if validate_for_next else None

        self._cloud_loading = True
        self._refresh_next_button_state()
        key = self.state.provider_token_env_key()
        token = self.orchestrator.env.get(key)
        if self.state.provider_token_replace and self.state.provider_token_input:
            token = self.state.provider_token_input
        if not token or token == "***":
            self._cloud_loading = False
            self._refresh_next_button_state()
            self._pending_cloud_validation_next = False
            self._pending_cloud_validation_request_id = None
            if not quiet and self.steps[self.current_step].key == "cloud":
                self.query_one("#error", Static).update("")
                self.query_one("#status", Static).update(
                    "Set cloud provider token for automation. Follow the instructions above."
                )
            return
        if not quiet and self.steps[self.current_step].key == "cloud":
            self.query_one("#status", Static).update("Loading cloud metadata...")
        self._load_cloud_worker(
            request_id,
            self.state.provider,
            token,
            self.state.location,
            server_types_only,
        )

    @work(thread=True, exclusive=True)
    def _load_cloud_worker(
        self,
        request_id: int,
        provider: str,
        token: str,
        location: str,
        server_types_only: bool,
    ) -> None:
        try:
            locations = self.location_options
            if not server_types_only or not locations:
                locations = self.orchestrator.provider.location_options(provider, token)
            seed = choose_seed([item.value for item in locations], existing=location)
            server_types = self.orchestrator.provider.server_type_options(
                provider, seed, token
            )
            self.post_message(CloudLoaded(locations, server_types, request_id=request_id))
        except Exception as exc:
            self.post_message(
                CloudLoaded(
                    [],
                    [],
                    self._describe_cloud_lookup_error(provider, str(exc)),
                    request_id=request_id,
                )
            )

    @staticmethod
    def _describe_cloud_lookup_error(provider: str, detail: str) -> str:
        provider_name = "Hetzner" if provider == "hetzner" else "Linode"
        compact = " ".join(detail.split())[:220]
        lower = detail.lower()

        if "not found in toolchain" in lower:
            return f"{provider_name} CLI not found in toolchain."
        if "timed out" in lower or "timeout" in lower:
            return (
                f"Unable to validate {provider_name} API token right now (timeout). "
                f"Please retry. ({compact})"
            )
        return (
            f"Invalid {provider_name} API token. The token is invalid, expired, or missing required scope. "
            f"Follow the token instructions above and paste a valid token. ({compact})"
        )

    def _load_hermes_options(
        self, models_only: bool = False, provider_override: str | None = None
    ) -> None:
        request_provider = provider_override or self.state.hermes_provider
        if self._hermes_loading:
            if request_provider:
                self._pending_hermes_provider = request_provider
            return
        self._hermes_loading = True
        self._refresh_next_button_state()
        self._pending_hermes_provider = None
        request_id = self._hermes_metadata_task.begin()
        if self.steps[self.current_step].key == "hermes":
            self.query_one("#status", Static).update("Loading Hermes metadata...")
        self._load_hermes_worker(request_provider, models_only, request_id)

    @work(thread=True, exclusive=True)
    def _load_hermes_worker(self, provider: str, models_only: bool, request_id: int) -> None:
        try:
            providers = self.hermes_provider_options
            if not models_only or not providers:
                providers = self.orchestrator.hermes.provider_ids()
            if not providers:
                raise ConfigureServiceError("no Hermes providers discovered at runtime")
            seed_provider = choose_seed(
                providers, existing=provider, preferred="openai-codex"
            )
            models = self.orchestrator.hermes.model_ids(seed_provider)
            if not models:
                raise ConfigureServiceError(
                    f"no Hermes models discovered for provider {seed_provider}"
                )
            auth_type, env_vars = self.orchestrator.hermes.provider_auth_metadata(
                seed_provider
            )
            self.post_message(
                HermesLoaded(providers, models, seed_provider, auth_type, env_vars, request_id=request_id)
            )
        except Exception as exc:
            self.post_message(HermesLoaded([], [], provider, "api_key", [], request_id=request_id, error=str(exc)))


def run_configure_app(root_dir: pathlib.Path) -> list[tuple[str, str, str]] | None:
    ensure_expected_toolchain_runtime()
    return ConfigureTUI(root_dir=root_dir).run()


def print_post_exit_recap(rows: list[tuple[str, str, str]]) -> None:
    print("hermes-vps configuration")
    print("========================")
    for key, old, new in rows:
        print(f"{key}: {old or '<empty>'} -> {new or '<empty>'}")
    print("Configuration complete.")
    print("Next: run 'just init && just plan'.")
    print("If all green: run 'just apply' then 'just bootstrap'.")


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    try:
        rows = run_configure_app(root)
    except KeyboardInterrupt:
        print("Configuration cancelled.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if rows is None:
        print("Configuration cancelled.")
        return 0
    print_post_exit_recap(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
