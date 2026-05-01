# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnusedParameter=false, reportImplicitOverride=false, reportAttributeAccessIssue=false, reportIncompatibleMethodOverride=false, reportUnusedCallResult=false, reportPrivateUsage=false
import pathlib
import unittest

from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from hermes_vps_app.cloud_remediation import remediation_for, render_remediation
from scripts.configure_services import (
    EnvStoreLike,
    HermesServiceLike,
    ProviderAuthError,
    ProviderServiceLike,
)
from scripts.configure_state import LabeledValue, WizardState
from scripts.configure_tui import (
    CloudLoaded,
    ConfigureTUI,
    HermesLoaded,
    HermesOAuthFinished,
    HermesOAuthProgress,
)


class _FakeEnv:
    store: dict[str, str]

    def __init__(self) -> None:
        self.store = {
            "TF_VAR_server_image": "debian-13",
            "HCLOUD_TOKEN": "***",
            "LINODE_TOKEN": "***",
            "HERMES_API_KEY": "[REDACTED]",
            "TELEGRAM_BOT_TOKEN": "[REDACTED]",
        }

    def get(self, key: str) -> str:
        return self.store.get(key, "")

    def set(self, key: str, value: str) -> None:
        self.store[key] = value


class _FakeProviderService:
    def auth_probe(self, provider: str, token: str) -> None:
        _ = provider
        _ = token

    def location_options(self, provider: str, token: str) -> list[LabeledValue]:
        return [LabeledValue("DE, Nuremberg (nbg1)", "nbg1")]

    def server_type_options(
        self, provider: str, location: str, token: str
    ) -> list[LabeledValue]:
        return [LabeledValue("cx22 • 2 vCPU", "cx22", recommended=True)]


class _FakeHermesService:
    def provider_ids(self) -> list[str]:
        return ["openai-codex"]

    def model_ids(self, _provider: str) -> list[str]:
        return ["gpt-5.4-mini"]

    def provider_auth_metadata(self, _provider: str) -> tuple[str, list[str]]:
        return "api_key", ["HERMES_API_KEY"]


class _FakeOrchestrator:
    env: EnvStoreLike
    provider: ProviderServiceLike
    hermes: HermesServiceLike
    applied: bool
    cloud_persisted: bool
    server_persisted: bool
    hermes_persisted: bool
    hermes_api_validated: bool
    telegram_persisted: bool
    telegram_validated: bool
    _hermes_artifact_present: bool

    def __init__(self) -> None:
        self.env = _FakeEnv()
        self.provider = _FakeProviderService()
        self.hermes = _FakeHermesService()
        self.applied = False
        self.cloud_persisted = False
        self.server_persisted = False
        self.hermes_persisted = False
        self.hermes_api_validated = False
        self.telegram_persisted = False
        self.telegram_validated = False
        self._hermes_artifact_present = False

    def load_initial_state(self) -> WizardState:
        return WizardState(
            provider="hetzner",
            server_image="debian-13",
            location="nbg1",
            server_type="cx22",
            hostname="hermes-prod-01",
            admin_username="opsadmin",
            admin_group="sshadmins",
            ssh_private_key_path="/tmp/hermes-test-key",
            hermes_agent_version="0.10.0",
            hermes_agent_release_tag="v0.10.0",
            hermes_provider="openai-codex",
            hermes_model="gpt-5.4-mini",
            hermes_auth_type="oauth_external+api_key",
            hermes_auth_method="api_key",
            telegram_allowlist_ids="12345",
            original_values={
                "TF_VAR_hermes_provider": "openai-codex",
                "TF_VAR_hermes_model": "gpt-5.4-mini",
            },
        )

    def provider_token_present(self, state: WizardState) -> bool:
        return True

    def telegram_token_present(self) -> bool:
        token = self.env.get("TELEGRAM_BOT_TOKEN")
        return bool(token and token != "***")

    def hermes_api_key_present(self) -> bool:
        return bool(self.env.get("HERMES_API_KEY"))

    def hermes_auth_artifact_present(self) -> bool:
        return self._hermes_artifact_present

    @staticmethod
    def hermes_available_auth_methods(auth_type: str) -> list[str]:
        methods = []
        mode = (auth_type or "").lower()
        if "api_key" in mode:
            methods.append("api_key")
        if "oauth" in mode:
            methods.append("oauth")
        return methods or ["api_key"]

    def hermes_existing_auth_method_for_combo(self, state: WizardState) -> str:
        same_provider = state.hermes_provider == state.original_values.get(
            "TF_VAR_hermes_provider", ""
        )
        if not same_provider:
            return ""
        if self._hermes_artifact_present:
            return "oauth"
        if self.hermes_api_key_present():
            return "api_key"
        return ""

    def persist_cloud_step(self, state: WizardState) -> None:
        self.cloud_persisted = True
        self.env.set("TF_VAR_cloud_provider", state.provider)
        self.env.set("TF_VAR_server_image", state.server_image)

    def persist_server_step(self, state: WizardState) -> None:
        self.server_persisted = True
        self.env.set("TF_VAR_server_location", state.location)
        self.env.set("TF_VAR_server_type", state.server_type)
        self.env.set("TF_VAR_hostname", state.hostname)
        self.env.set("TF_VAR_admin_username", state.admin_username)
        self.env.set("TF_VAR_admin_group", state.admin_group)
        self.env.set("BOOTSTRAP_SSH_PRIVATE_KEY_PATH", state.ssh_private_key_path)

    def resolve_release_tag_for_version(self, version: str) -> str:
        if version == "0.10.0":
            return "v0.10.0"
        return f"v{version}" if version else ""

    def persist_hermes_step(self, state: WizardState) -> None:
        self.hermes_persisted = True
        state.hermes_agent_release_tag = self.resolve_release_tag_for_version(
            state.hermes_agent_version
        )
        self.env.set("HERMES_AGENT_RELEASE_TAG", state.hermes_agent_release_tag)
        if state.hermes_auth_method == "api_key":
            if state.hermes_api_key_input:
                self.env.set("HERMES_API_KEY", state.hermes_api_key_input)
            self._hermes_artifact_present = False
        else:
            self.env.set("HERMES_API_KEY", "")
            self._hermes_artifact_present = True

    def validate_hermes_api_key_setup(self, state: WizardState) -> str:
        self.hermes_api_validated = True
        if state.hermes_auth_method != "api_key":
            return ""
        key = state.hermes_api_key_input.strip() or self.env.get("HERMES_API_KEY")
        if not key:
            raise RuntimeError("API key auth selected, but no HERMES_API_KEY is set.")
        if key == "bad":
            raise RuntimeError("Invalid Hermes API key for openai-codex.")
        return "Hermes API key valid for openai-codex."

    def persist_telegram_step(self, state: WizardState) -> None:
        self.telegram_persisted = True
        self.env.set("TELEGRAM_ALLOWLIST_IDS", state.telegram_allowlist_ids)
        if state.telegram_bot_token_replace or not self.telegram_token_present():
            self.env.set("TELEGRAM_BOT_TOKEN", state.telegram_bot_token_input)

    def validate_telegram_setup(self, state: WizardState) -> str:
        self.telegram_validated = True
        if not state.telegram_allowlist_ids:
            raise RuntimeError("Allowlist required.")
        if state.telegram_bot_token_replace and not state.telegram_bot_token_input:
            raise RuntimeError("Telegram bot token cannot be empty.")
        return "Telegram token valid (@testbot) • allowlist format valid."

    def apply(self, state: WizardState) -> list[tuple[str, str, str]]:
        self.applied = True
        return state.recap_rows()


class _DeterministicConfigureTUI(ConfigureTUI):
    def _load_cloud_options(
        self,
        server_types_only: bool = False,
        quiet: bool = False,
        validate_for_next: bool = False,
    ) -> None:
        _ = server_types_only
        _ = quiet
        _ = validate_for_next
        self.post_message(
            CloudLoaded(
                locations=[LabeledValue("DE, Nuremberg (nbg1)", "nbg1")],
                server_types=[LabeledValue("cx22 • 2 vCPU", "cx22", recommended=True)],
                request_id=self._active_cloud_request_id,
            )
        )

    def _load_hermes_options(
        self, models_only: bool = False, provider_override: str | None = None
    ) -> None:
        _ = models_only
        provider = provider_override or self.state.hermes_provider or "openai-codex"
        models = ["gpt-5.4-mini", "gpt-5.4"]
        auth_type = "oauth_external+api_key"
        if provider == "anthropic":
            models = ["claude-sonnet-4"]
            auth_type = "oauth"
        self.post_message(
            HermesLoaded(
                providers=["openai-codex", "anthropic"],
                models=models,
                resolved_provider=provider,
                auth_type=auth_type,
                auth_env_vars=["HERMES_API_KEY"] if "api_key" in auth_type else [],
            )
        )

    def _run_hermes_oauth_worker(self, provider: str) -> None:
        self.post_message(HermesOAuthProgress(chunk=f"Open browser for {provider}\n"))
        self.post_message(
            HermesOAuthFinished(success=True, output=f"oauth started for {provider}")
        )


class ConfigureTUITests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_telegram_allowlist_blocks_progress(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 3
            await pilot.pause()
            allow = app.query_one("#telegram-allowlist-input")
            allow.value = "bad-value"
            await pilot.press("enter")
            await pilot.pause()
            error = app.query_one("#error").renderable
            self.assertIn("comma-separated integers", str(error))

    async def test_review_apply_exits_with_recap(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 4
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(app.orchestrator.applied)

    async def test_review_renders_ssh_alias_status_label(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 4
            await pilot.pause()
            review_text = str(app.query_one("#review-diff", Static).renderable)
            self.assertIn("SSH alias: active", review_text)
            self.assertIn("HERMES_AGENT_RELEASE_TAG:", review_text)
            self.assertIn("v0.10.0", review_text)
            self.assertNotIn("HERMES_AUTH_TYPE:", review_text)
            self.assertNotIn("HERMES_AUTH_ARTIFACT:", review_text)

    async def test_review_shows_new_auth_artifact_and_api_key_cleared_on_oauth(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.state.hermes_auth_method = "oauth"
            app.state.original_values["HERMES_API_KEY"] = "[REDACTED]"
            app.state.original_values["HERMES_AUTH_ARTIFACT"] = ""
            app.current_step = 4
            await pilot.pause()
            review_text = str(app.query_one("#review-diff", Static).renderable)
            self.assertIn("HERMES_API_KEY: *** -> <empty>", review_text)
            self.assertIn("New Hermes authentication artifact:", review_text)

    async def test_review_shows_artifact_delete_and_api_key_set_on_api_key_auth(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.state.hermes_auth_method = "api_key"
            app.state.hermes_api_key_input = "new-key"
            app.state.original_values["HERMES_API_KEY"] = ""
            app.state.original_values["HERMES_AUTH_ARTIFACT"] = "/tmp/hermes-auth.json"
            app.current_step = 4
            await pilot.pause()
            review_text = str(app.query_one("#review-diff", Static).renderable)
            self.assertIn("HERMES_API_KEY: <empty> -> ***", review_text)
            self.assertIn(
                "Delete Hermes authentication artifact: /tmp/hermes-auth.json",
                review_text,
            )

    async def test_review_shows_no_changes_message_when_everything_matches(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.state.original_values.update(
                {
                    "TF_VAR_cloud_provider": app.state.provider,
                    "TF_VAR_server_image": app.state.server_image,
                    "TF_VAR_server_location": app.state.location,
                    "TF_VAR_server_type": app.state.server_type,
                    "TF_VAR_hostname": app.state.hostname,
                    "TF_VAR_admin_username": app.state.admin_username,
                    "TF_VAR_admin_group": app.state.admin_group,
                    "BOOTSTRAP_SSH_PRIVATE_KEY_PATH": app.state.ssh_private_key_path,
                    "HERMES_AGENT_VERSION": app.state.hermes_agent_version,
                    "HERMES_AGENT_RELEASE_TAG": app.state.hermes_agent_release_tag,
                    "TF_VAR_hermes_provider": app.state.hermes_provider,
                    "TF_VAR_hermes_model": app.state.hermes_model,
                    "TELEGRAM_ALLOWLIST_IDS": app.state.telegram_allowlist_ids,
                    "SSH_ALIAS": "active" if app.state.add_ssh_alias else "inactive",
                    "HERMES_API_KEY": app.state.hermes_api_key_input,
                    "HERMES_AUTH_ARTIFACT": "",
                }
            )
            app.current_step = 4
            await pilot.pause()
            review_text = str(app.query_one("#review-diff", Static).renderable)
            self.assertEqual(review_text.strip(), "No changes to apply.")

    async def test_cloud_stale_validation_result_does_not_advance_or_persist(self):
        orchestrator = _FakeOrchestrator()
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 0
            await pilot.pause()

            app._cloud_loading = True
            app._active_cloud_request_id = 2
            app._pending_cloud_validation_next = True
            app._pending_cloud_validation_request_id = 2

            app.post_message(
                CloudLoaded(
                    locations=[LabeledValue("DE, Nuremberg (nbg1)", "nbg1")],
                    server_types=[LabeledValue("cx22 • 2 vCPU", "cx22", recommended=True)],
                    request_id=1,
                )
            )
            await pilot.pause()

            self.assertEqual(app.current_step, 0)
            self.assertFalse(orchestrator.cloud_persisted)

    async def test_provider_switch_updates_cloud_help_without_duplicate_ids(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 0
            await pilot.pause()

            rail_help = str(app.query_one("#rail-help", Static).renderable)
            self.assertIn("Hold Shift to select using the mouse", rail_help)
            self.assertIn("Hold Shift and Ctrl to open links with the mouse", rail_help)

            provider = app.query_one("#provider-select")
            provider.value = "linode"
            await pilot.pause()
            help_title = app.query_one("#provider-token-help-title", Label).renderable
            self.assertIn("Linode", str(help_title))

            provider.value = "hetzner"
            await pilot.pause()
            help_title = app.query_one("#provider-token-help-title", Label).renderable
            self.assertIn("Hetzner", str(help_title))

            with self.assertRaises(Exception):
                app.query_one("#provider-token-link-input", Input)

    async def test_cloud_next_persists_step1_values_to_env(self):
        orchestrator = _FakeOrchestrator()
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.current_step, 1)
            self.assertTrue(orchestrator.cloud_persisted)
            self.assertEqual(orchestrator.env.get("TF_VAR_cloud_provider"), "hetzner")
            self.assertEqual(orchestrator.env.get("TF_VAR_server_image"), "debian-13")

    def test_cloud_lookup_error_message_uses_typed_remediation_contract(self):
        typed_error = ProviderAuthError(
            "token_insufficient_scope",
            "command failed: hcloud context list -o json (authorization bearer sk_live_ABC123XYZ)",
        )

        msg = ConfigureTUI._describe_cloud_lookup_error("hetzner", typed_error)

        expected = render_remediation(
            remediation_for("hetzner", "token_insufficient_scope", str(typed_error))
        )
        self.assertEqual(msg, expected)
        self.assertIn("[REDACTED]", msg)
        self.assertIn("[auth_probe] hcloud context list -o json", msg)

    async def test_server_step_keeps_env_values_when_inputs_left_blank(self):
        orchestrator = _FakeOrchestrator()
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 1
            await pilot.pause()
            self.assertEqual(str(app.query_one("#status").renderable).strip(), "")

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.current_step, 2)
            self.assertEqual(app.state.hostname, "hermes-prod-01")
            self.assertEqual(app.state.admin_username, "opsadmin")
            self.assertEqual(app.state.admin_group, "sshadmins")
            self.assertTrue(orchestrator.server_persisted)
            self.assertEqual(orchestrator.env.get("TF_VAR_server_location"), "nbg1")
            self.assertEqual(orchestrator.env.get("TF_VAR_server_type"), "cx22")
            self.assertEqual(orchestrator.env.get("TF_VAR_hostname"), "hermes-prod-01")

    async def test_server_step_edit_field_advances_without_hermes_select_crash(self):
        orchestrator = _FakeOrchestrator()
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 1
            await pilot.pause()

            hostname = app.query_one("#hostname-input")
            hostname.value = "new-hostname"

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.current_step, 2)
            self.assertEqual(app.state.hostname, "new-hostname")
            self.assertTrue(orchestrator.server_persisted)
            self.assertEqual(orchestrator.env.get("TF_VAR_hostname"), "new-hostname")

    async def test_server_step_provider_labels_and_ssh_alias_checkbox(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.state.provider = "linode"
            app.current_step = 1
            await pilot.pause()

            labels = [str(widget.renderable) for widget in app.query("Label").results()]
            self.assertIn("Linode region", labels)
            self.assertIn("Linode server type", labels)

            toggle = app.query_one("#ssh-alias-toggle", Checkbox)
            self.assertTrue(toggle.value)

            app.current_step = 3
            await pilot.pause()
            with self.assertRaises(Exception):
                app.query_one("#ssh-alias-toggle", Checkbox)

    async def test_hermes_step_provider_change_clears_model_and_updates_auth_method(
        self,
    ):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            self.assertEqual(app.state.hermes_model, "gpt-5.4-mini")
            provider = app.query_one("#hermes-provider-select")
            provider.value = "anthropic"

            await pilot.pause()
            await pilot.pause()

            self.assertNotEqual(app.state.hermes_model, "gpt-5.4-mini")
            self.assertEqual(app.state.hermes_model, "claude-sonnet-4")
            self.assertEqual(app.state.hermes_auth_type, "oauth")
            auth_select = app.query_one("#hermes-auth-method-select")
            self.assertEqual(auth_select.value, "oauth")

    async def test_hermes_model_change_updates_auth_method_options(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            model = app.query_one("#hermes-model-select")
            model.value = "gpt-5.4"
            await pilot.pause()

            self.assertEqual(app.state.hermes_model, "gpt-5.4")
            auth_select = app.query_one("#hermes-auth-method-select")
            self.assertEqual(auth_select.value, "api_key")
            with self.assertRaises(Exception):
                app.query_one("#hermes-auth-hint", Static)
            with self.assertRaises(Exception):
                app.query_one("#hermes-auth-debug", Static)

    async def test_hermes_auth_section_preselects_api_key_and_replacement_placeholder(
        self,
    ):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            auth_select = app.query_one("#hermes-auth-method-select")
            self.assertEqual(auth_select.value, "api_key")
            api_input = app.query_one("#hermes-api-key-input", Input)
            self.assertIn("replace the current one", api_input.placeholder)
            auth_title = app.query_one("#hermes-auth-choice-title", Label)
            self.assertEqual(str(auth_title.renderable), "API key")

    async def test_hermes_auth_section_oauth_button_renew_and_output(self):
        orchestrator = _FakeOrchestrator()
        orchestrator._hermes_artifact_present = True
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            auth_select = app.query_one("#hermes-auth-method-select")
            auth_select.value = "oauth"
            await pilot.pause()

            oauth_button = app.query_one("#hermes-oauth-button", Button)
            self.assertIn("Renew current OAuth token", oauth_button.label)
            auth_title = app.query_one("#hermes-auth-choice-title", Label)
            self.assertEqual(str(auth_title.renderable), "OAuth")

            app._hermes_oauth_button_pressed()
            await pilot.pause()

            output = str(app.query_one("#hermes-oauth-output").renderable)
            self.assertIn("oauth started for openai-codex", output)

    async def test_hermes_oauth_start_blocks_next_until_oauth_is_run(self):
        orchestrator = _FakeOrchestrator()
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            auth_select = app.query_one("#hermes-auth-method-select", Select)
            auth_select.value = "oauth"
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.current_step, 2)
            self.assertFalse(orchestrator.hermes_persisted)
            error = str(app.query_one("#error", Static).renderable)
            self.assertIn("Run OAuth authentication before continuing", error)

    async def test_hermes_oauth_renew_allows_next(self):
        orchestrator = _FakeOrchestrator()
        orchestrator._hermes_artifact_present = True
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            auth_select = app.query_one("#hermes-auth-method-select", Select)
            auth_select.value = "oauth"
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.current_step, 3)
            self.assertTrue(orchestrator.hermes_persisted)

    async def test_hermes_reentry_keeps_provider_and_model_selected(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            provider_select = app.query_one("#hermes-provider-select", Select)
            model_select = app.query_one("#hermes-model-select", Select)
            self.assertNotEqual(provider_select.value, Select.BLANK)
            self.assertNotEqual(model_select.value, Select.BLANK)
            chosen_provider = provider_select.value
            chosen_model = model_select.value

            app.current_step = 3
            await pilot.pause()
            app.current_step = 2
            await pilot.pause()

            provider_select = app.query_one("#hermes-provider-select", Select)
            model_select = app.query_one("#hermes-model-select", Select)
            self.assertEqual(provider_select.value, chosen_provider)
            self.assertEqual(model_select.value, chosen_model)
            self.assertNotEqual(provider_select.value, Select.BLANK)
            self.assertNotEqual(model_select.value, Select.BLANK)

    async def test_hermes_reentry_recovers_provider_when_state_was_blank(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            model_select = app.query_one("#hermes-model-select", Select)
            self.assertNotEqual(model_select.value, Select.BLANK)
            app.state.hermes_provider = ""

            app.current_step = 3
            await pilot.pause()
            app.current_step = 2
            await pilot.pause()

            provider_select = app.query_one("#hermes-provider-select", Select)
            model_select = app.query_one("#hermes-model-select", Select)
            self.assertNotEqual(provider_select.value, Select.BLANK)
            self.assertEqual(provider_select.value, app.state.hermes_provider)
            self.assertNotEqual(model_select.value, Select.BLANK)

    async def test_hermes_reentry_via_navigation_keeps_provider_selected(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            provider_select = app.query_one("#hermes-provider-select", Select)
            chosen_provider = provider_select.value
            self.assertNotEqual(chosen_provider, Select.BLANK)

            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            self.assertEqual(app.steps[app.current_step].key, "telegram")

            await pilot.press("ctrl+b")
            await pilot.pause()
            self.assertEqual(app.steps[app.current_step].key, "hermes")

            provider_select = app.query_one("#hermes-provider-select", Select)
            self.assertEqual(provider_select.value, chosen_provider)
            self.assertNotEqual(provider_select.value, Select.BLANK)

    async def test_hermes_reentry_navigation_repeat_keeps_provider_selected(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            chosen_provider = app.query_one("#hermes-provider-select", Select).value
            self.assertNotEqual(chosen_provider, Select.BLANK)

            for _ in range(4):
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
                self.assertEqual(app.steps[app.current_step].key, "telegram")

                await pilot.press("ctrl+b")
                await pilot.pause()
                await pilot.pause()
                self.assertEqual(app.steps[app.current_step].key, "hermes")

                provider_select = app.query_one("#hermes-provider-select", Select)
                self.assertEqual(provider_select.value, chosen_provider)
                self.assertNotEqual(provider_select.value, Select.BLANK)

    async def test_hermes_api_key_validation_blocks_invalid_key(self):
        orchestrator = _FakeOrchestrator()
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            key_input = app.query_one("#hermes-api-key-input", Input)
            key_input.value = "bad"

            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.current_step, 2)
            self.assertTrue(orchestrator.hermes_api_validated)
            self.assertFalse(orchestrator.hermes_persisted)
            error = str(app.query_one("#error", Static).renderable)
            self.assertIn("Invalid Hermes API key", error)

    async def test_hermes_oauth_progress_updates_output_live(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            app.post_message(
                HermesOAuthProgress(
                    "Open this URL: https://example.test/auth\nCode: ABC-123\n"
                )
            )
            await pilot.pause()

            output = str(app.query_one("#hermes-oauth-output").renderable)
            self.assertIn("https://example.test/auth", output)
            self.assertIn("ABC-123", output)

    async def test_hermes_stale_provider_result_is_discarded_and_reloaded(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            app.state.hermes_provider = "anthropic"
            app._pending_hermes_provider = "anthropic"
            app.post_message(
                HermesLoaded(
                    providers=["openai-codex", "anthropic"],
                    models=["gpt-5.4-mini"],
                    resolved_provider="openai-codex",
                    auth_type="api_key",
                    auth_env_vars=["HERMES_API_KEY"],
                )
            )
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.state.hermes_provider, "anthropic")
            self.assertEqual(app.state.hermes_model, "claude-sonnet-4")
            self.assertEqual(app.state.hermes_auth_type, "oauth")

    async def test_hermes_step_persists_release_tag_and_has_no_advanced_toggle(self):
        orchestrator = _FakeOrchestrator()
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            with self.assertRaises(Exception):
                app.query_one("#toggle-advanced", Checkbox)
            with self.assertRaises(Exception):
                app.query_one("#hermes-release-input")
            with self.assertRaises(Exception):
                app.query_one("#hermes-release-hint")

            labels = [str(widget.renderable) for widget in app.query("Label").results()]
            self.assertIn("Hermes agent version", labels)
            self.assertIn("Provider", labels)
            self.assertIn("Model", labels)
            self.assertIn("Athentification", labels)
            self.assertIn("API key", labels)

            version = app.query_one("#hermes-version-input", Input)
            version.value = "0.10.1"

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.current_step, 3)
            self.assertTrue(orchestrator.hermes_api_validated)
            self.assertTrue(orchestrator.hermes_persisted)
            self.assertEqual(
                orchestrator.env.get("HERMES_AGENT_RELEASE_TAG"), "v0.10.1"
            )

    async def test_telegram_step_missing_token_requires_input(self):
        orchestrator = _FakeOrchestrator()
        orchestrator.env.set("TELEGRAM_BOT_TOKEN", "")
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 3
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.current_step, 3)
            error = str(app.query_one("#error", Static).renderable)
            self.assertIn("Telegram bot token cannot be empty", error)

    async def test_telegram_step_next_persists_values(self):
        orchestrator = _FakeOrchestrator()
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=orchestrator
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 3
            await pilot.pause()

            token_input = app.query_one("#telegram-token-input", Input)
            token_input.value = "[REDACTED]"
            allowlist = app.query_one("#telegram-allowlist-input", Input)
            allowlist.value = "12345,-100987654321"

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.current_step, 4)
            self.assertTrue(orchestrator.telegram_validated)
            self.assertTrue(orchestrator.telegram_persisted)
            self.assertEqual(
                orchestrator.env.get("TELEGRAM_ALLOWLIST_IDS"), "12345,-100987654321"
            )

    async def test_telegram_step_titles_and_instructions(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 3
            await pilot.pause()

            labels = [str(widget.renderable) for widget in app.query("Label").results()]
            self.assertIn("How to get telegram token", labels)
            self.assertIn("How to get Telegram ID", labels)
            self.assertNotIn("Telegram gateway", labels)

            hints = [
                str(widget.renderable) for widget in app.query("Static.hint").results()
            ]
            self.assertTrue(
                any("multiple comma-separated IDs" in hint for hint in hints)
            )

    async def test_next_button_disabled_during_loading_states(self):
        app = _DeterministicConfigureTUI(
            root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 0
            await pilot.pause()

            next_button = app.query_one("#next", Button)
            cancel_button = app.query_one("#cancel", Button)
            app.set_focus(next_button)
            await pilot.pause()
            self.assertIs(app.focused, next_button)

            app._cloud_loading = True
            app._refresh_next_button_state()
            await pilot.pause()
            self.assertTrue(next_button.disabled)
            self.assertIsNot(app.focused, next_button)
            self.assertNotEqual(getattr(app.focused, "id", None), "cancel")

            app._cloud_loading = False
            app._refresh_next_button_state()
            await pilot.pause()
            self.assertFalse(next_button.disabled)
            self.assertIs(app.focused, next_button)

            app.set_focus(cancel_button)
            await pilot.pause()
            self.assertIs(app.focused, cancel_button)
            app._cloud_loading = True
            app._refresh_next_button_state()
            await pilot.pause()
            self.assertNotEqual(getattr(app.focused, "id", None), "cancel")
            app._cloud_loading = False
            app._refresh_next_button_state()
            await pilot.pause()
            self.assertIs(app.focused, next_button)

            app.current_step = 2
            await pilot.pause()
            app._hermes_loading = True
            app._refresh_next_button_state()
            self.assertTrue(app.query_one("#next", Button).disabled)
            app._hermes_loading = False
            app._hermes_oauth_running = True
            app._refresh_next_button_state()
            self.assertTrue(app.query_one("#next", Button).disabled)
            app._hermes_oauth_running = False
            app._hermes_api_key_validating = True
            app._refresh_next_button_state()
            self.assertTrue(app.query_one("#next", Button).disabled)
            app._hermes_api_key_validating = False
            app._refresh_next_button_state()
            self.assertFalse(app.query_one("#next", Button).disabled)

            app.current_step = 3
            await pilot.pause()
            app._telegram_loading = True
            app._refresh_next_button_state()
            self.assertTrue(app.query_one("#next", Button).disabled)
            app._telegram_loading = False
            app._refresh_next_button_state()
            self.assertFalse(app.query_one("#next", Button).disabled)


if __name__ == "__main__":
    unittest.main()
