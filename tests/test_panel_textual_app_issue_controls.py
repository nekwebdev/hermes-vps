# pyright: reportAny=false, reportImplicitOverride=false
from __future__ import annotations

import time
import unittest
from pathlib import Path
from typing import cast

from rich.text import Text
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
)

from hermes_vps_app.cloud_remediation import ProviderId, remediation_for
from hermes_vps_app.panel_config_flow import CloudMetadataSyncResult
from hermes_vps_app.panel_shell import ControlPanelShell
from hermes_vps_app.panel_startup import (
    PanelStartupResult,
    PanelStartupState,
    StartupStep,
)
from hermes_vps_app.panel_textual_app import HermesControlPanelApp
from scripts.configure_state import LabeledValue


def _startup() -> PanelStartupResult:
    return PanelStartupResult(
        state=PanelStartupState.DASHBOARD_READY,
        steps=(
            StartupStep(
                name="runner_detection",
                label="Detect runner",
                status="ok",
                detail="runner locked",
            ),
        ),
        runner_mode="direnv_nix",
        remediation="ready",
        provider="linode",
    )


def _configuration_required_startup() -> PanelStartupResult:
    return PanelStartupResult(
        state=PanelStartupState.CONFIGURATION_REQUIRED,
        steps=(
            StartupStep(
                name="runner_detection",
                label="Detect runner",
                status="ok",
                detail="runner locked",
            ),
        ),
        runner_mode="direnv_nix",
        remediation="configure .env",
        provider=None,
    )


class PanelTextualControlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_panel_app_exposes_actionable_controls_not_only_static_text(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ = (root / ".env").write_text(
                "TF_VAR_cloud_provider=linode\n", encoding="utf-8"
            )
            (root / "opentofu/providers/linode").mkdir(parents=True)
            startup = _startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(startup_result=startup),
                repo_root=root,
                startup_result=startup,
                initial_panel="deployment",
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                tabs = app.query_one("#main-tabs", TabbedContent)
                self.assertEqual(tabs.active, "deployment")
                self.assertFalse(app.query("#dashboard"))
                for button_id in (
                    "deployment-run-deploy",
                    "maintenance-preview-destroy",
                    "monitoring-run-health",
                ):
                    self.assertTrue(app.query_one(f"#{button_id}").can_focus)

                tabs.active = "configuration"
                await pilot.pause()
                self.assertEqual(tabs.active, "configuration")

                _ = app.query_one("#configuration-section-hermes", Button).press()
                await pilot.pause()
                status_text = str(app.query_one("#action-status", Static).renderable)
                self.assertIn("Configuration section selected: hermes.", status_text)

                app.query_one("#main-tabs", TabbedContent).active = "monitoring"
                await pilot.pause()
                _ = app.query_one("#monitoring-run-health", Button).press()
                await pilot.pause()
                status_text = str(app.query_one("#action-status", Static).renderable)
                self.assertIn("Monitoring action selected: run-health.", status_text)

    async def test_missing_env_renders_real_first_run_cloud_step_controls(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                tabs = app.query_one("#main-tabs", TabbedContent)
                self.assertEqual(tabs.active, "configuration")
                self.assertTrue(
                    app.query_one("#first-run-cloud-provider", Select).can_focus
                )
                self.assertTrue(
                    app.query_one("#first-run-cloud-token", Input).can_focus
                )
                sync_button = app.query_one("#first-run-cloud-sync", Button)
                self.assertTrue(sync_button.can_focus)
                next_button = app.query_one("#first-run-cloud-next", Button)
                self.assertTrue(next_button.disabled)
                token_label = app.query_one("#first-run-cloud-token-label", Label)
                self.assertEqual(str(token_label.renderable), "Token")
                token_help_button = app.query_one("#first-run-cloud-token-help", Button)
                self.assertEqual(str(token_help_button.label), "ⓘ")
                self.assertFalse(app.query("#first-run-cloud-lookup-mode"))
                self.assertFalse(app.query("#first-run-cloud-mode"))
                self.assertFalse(app.query("#first-run-cloud-progress-row"))
                self.assertEqual(
                    str(
                        app.query_one("#first-run-cloud-region-section").styles.display
                    ),
                    "none",
                )
                self.assertEqual(
                    str(
                        app.query_one(
                            "#first-run-cloud-server-type-section"
                        ).styles.display
                    ),
                    "none",
                )

    async def test_first_run_cloud_next_blocks_without_selected_provider_token(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                next_button = app.query_one("#first-run-cloud-next", Button)
                self.assertTrue(next_button.disabled)
                step_text = str(
                    app.query_one("#first-run-step-title", Static).renderable
                )
                self.assertIn("Cloud", step_text)

    async def test_first_run_cloud_next_enables_only_after_current_token_region_and_server_type_are_set(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.success(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    regions=(LabeledValue("Falkenstein (fsn1)", "fsn1"),),
                    server_types=(LabeledValue("cx22", "cx22"),),
                    selected_region="fsn1",
                    summary="Live cloud metadata synced.",
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                next_button = app.query_one("#first-run-cloud-next", Button)
                self.assertTrue(next_button.disabled)

                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                await pilot.pause()
                self.assertTrue(next_button.disabled)

                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                self.assertFalse(next_button.disabled)
                self.assertEqual(
                    app.query_one("#first-run-cloud-provider-spacer", Static).styles.display,
                    "block",
                )
                self.assertEqual(
                    app.query_one("#first-run-cloud-token-spacer", Static).styles.display,
                    "block",
                )
                self.assertEqual(
                    app.query_one("#first-run-cloud-region-spacer", Static).styles.display,
                    "block",
                )
                self.assertEqual(
                    app.query_one("#first-run-cloud-server-type-spacer", Static).styles.display,
                    "block",
                )
                self.assertLessEqual(
                    app.query_one("#first-run-cloud-token-help", Button).styles.width.value,
                    2,
                )

                app.query_one("#first-run-cloud-token", Input).value = "changed-token"
                await pilot.pause()
                self.assertTrue(next_button.disabled)

    async def test_first_run_cloud_provider_switch_clears_synced_options(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.success(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    regions=(LabeledValue("Falkenstein (fsn1)", "fsn1"),),
                    server_types=(LabeledValue("cx22", "cx22"),),
                    selected_region="fsn1",
                    summary="Live cloud metadata synced.",
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                self.assertEqual(
                    app.query_one("#first-run-cloud-region", Select).value, "fsn1"
                )

                provider_select = app.query_one("#first-run-cloud-provider", Select)
                provider_select.value = "linode"
                await pilot.pause()
                region_select = app.query_one("#first-run-cloud-region", Select)
                server_type_select = app.query_one(
                    "#first-run-cloud-server-type", Select
                )
                self.assertEqual(app.config_flow.draft.server.image, "linode/debian13")
                self.assertIs(region_select.value, Select.BLANK)
                self.assertIs(server_type_select.value, Select.BLANK)
                status_text = str(
                    app.query_one("#first-run-cloud-step-status", Static).renderable
                )
                self.assertIn("Cloud provider set to Linode", status_text)

    async def test_first_run_cloud_token_help_popup_updates_with_selected_provider(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                _ = app.query_one("#first-run-cloud-token-help", Button).press()
                await pilot.pause()
                help_text = str(
                    app.query_one("#first-run-cloud-token-help-text", Static).renderable
                )
                self.assertIn("https://console.hetzner.cloud/", help_text)
                self.assertIn("Security -> API Tokens", help_text)
                self.assertIn("Read & Write scope", help_text)
                _ = app.query_one("#first-run-cloud-token-help-close", Button).press()
                await pilot.pause()

                app.query_one("#first-run-cloud-provider", Select).value = "linode"
                await pilot.pause()
                _ = app.query_one("#first-run-cloud-token-help", Button).press()
                await pilot.pause()

                help_text = str(
                    app.query_one("#first-run-cloud-token-help-text", Static).renderable
                )
                self.assertIn("https://cloud.linode.com/profile/tokens", help_text)
                self.assertIn("Personal Access Token", help_text)
                self.assertIn("Read/Write scope for Linodes", help_text)
                self.assertNotIn("console.hetzner.cloud", help_text)

    async def test_first_run_cloud_provider_status_is_shown_below_next_not_header(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-provider", Select).value = "linode"
                await pilot.pause()

                local_status = str(
                    app.query_one("#first-run-cloud-step-status", Static).renderable
                )
                header_status = str(app.query_one("#action-status", Static).renderable)
                self.assertIn("Cloud provider set to Linode", local_status)
                self.assertNotIn("Cloud provider set to Linode", header_status)

    async def test_first_run_cloud_valid_next_checks_cloud_configuration_before_advancing(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        calls: list[str | None] = []

        def sync(
            provider: ProviderId, token: str, selected_region: str | None
        ) -> CloudMetadataSyncResult:
            calls.append(selected_region)
            if selected_region == "nbg1":
                time.sleep(0.2)
            return CloudMetadataSyncResult.success(
                provider=provider,
                token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                regions=(LabeledValue("Nuremberg (nbg1)", "nbg1"),),
                server_types=(LabeledValue("cx22", "cx22"),),
                selected_region="nbg1",
                summary="Live cloud metadata synced.",
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )

            app.config_flow.cloud_metadata_sync_runner = sync

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                app.query_one("#first-run-cloud-region", Select).value = "nbg1"
                app.query_one("#first-run-cloud-server-type", Select).value = "cx22"
                _ = app.query_one("#first-run-cloud-next", Button).press()
                await pilot.pause(0.05)

                progress_text = str(
                    app.query_one("#first-run-cloud-step-status", Static).renderable
                )
                self.assertIn("Checking Cloud configuration...", progress_text)
                self.assertTrue(any(frame in progress_text for frame in "⢀⣠⣴⣾⣿⣷⣦⣄"))
                sidebar_text = str(
                    app.query_one("#first-run-step-sidebar", Static).renderable
                )
                self.assertIn("▶ Cloud", sidebar_text)
                self.assertNotIn("✓ Cloud", sidebar_text)

                await pilot.pause(0.3)

                self.assertEqual(calls, [None, "nbg1"])
                step_text = str(
                    app.query_one("#first-run-step-title", Static).renderable
                )
                self.assertIn("Host & SSH", step_text)
                self.assertEqual(
                    app.query_one("#first-run-cloud-summary", Static).styles.display,
                    "none",
                )
                sidebar = app.query_one("#first-run-step-sidebar", Static)
                sidebar_text = str(sidebar.renderable)
                self.assertIn("✓ Cloud", sidebar_text)
                self.assertIn("▶ Host & SSH", sidebar_text)
                self.assertIsInstance(sidebar.renderable, Text)
                sidebar_renderable = cast(Text, sidebar.renderable)
                completed_span_styles = [
                    str(span.style)
                    for span in sidebar_renderable.spans
                    if "✓ Cloud" in sidebar_renderable.plain[span.start : span.end]
                ]
                self.assertIn("green", completed_span_styles)
                self.assertEqual(app.config_flow.draft.provider.provider, "hetzner")
                self.assertEqual(app.config_flow.draft.server.location, "nbg1")
                self.assertEqual(app.config_flow.draft.server.server_type, "cx22")
                self.assertEqual(
                    app.config_flow.draft.provider.hcloud_token.replacement,
                    "hcloud-secret",
                )

    async def test_first_run_cloud_next_check_blocks_when_server_type_no_longer_matches(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        calls: list[str | None] = []

        def sync(
            provider: ProviderId, token: str, selected_region: str | None
        ) -> CloudMetadataSyncResult:
            calls.append(selected_region)
            server_types = (
                (LabeledValue("cx22", "cx22"),)
                if len(calls) == 1
                else (LabeledValue("cx32", "cx32"),)
            )
            return CloudMetadataSyncResult.success(
                provider=provider,
                token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                regions=(LabeledValue("Nuremberg (nbg1)", "nbg1"),),
                server_types=server_types,
                selected_region="nbg1",
                summary="Live cloud metadata synced.",
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = sync

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                app.query_one("#first-run-cloud-region", Select).value = "nbg1"
                app.query_one("#first-run-cloud-server-type", Select).value = "cx22"
                _ = app.query_one("#first-run-cloud-next", Button).press()
                await pilot.pause()

                self.assertEqual(app.config_flow.current_step, "cloud")
                result_widget = app.query_one("#first-run-cloud-step-status", Static)
                self.assertIn(
                    "Selected region or server type is no longer available",
                    str(result_widget.renderable),
                )
                self.assertEqual(
                    str(getattr(result_widget.styles, "color", None)),
                    "Color(255, 0, 0, ansi=None)",
                )
                sidebar_text = str(
                    app.query_one("#first-run-step-sidebar", Static).renderable
                )
                self.assertIn("▶ Cloud", sidebar_text)
                self.assertNotIn("✓ Cloud", sidebar_text)

    async def test_first_run_wizard_renders_status_only_step_sidebar(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.success(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    regions=(LabeledValue("Falkenstein (fsn1)", "fsn1"),),
                    server_types=(LabeledValue("cx22", "cx22"),),
                    selected_region="fsn1",
                    summary="Live cloud metadata synced.",
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                sidebar_text = str(
                    app.query_one("#first-run-step-sidebar", Static).renderable
                )
                self.assertIn("▶ Cloud", sidebar_text)
                self.assertIn("○ Host & SSH", sidebar_text)
                self.assertIn("○ Hermes", sidebar_text)
                self.assertIn("○ Gateways", sidebar_text)
                self.assertIn("○ Review", sidebar_text)
                self.assertFalse(app.query("#first-run-step-sidebar Button"))

                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                _ = app.query_one("#first-run-cloud-next", Button).press()
                await pilot.pause()

                sidebar_text = str(
                    app.query_one("#first-run-step-sidebar", Static).renderable
                )
                self.assertIn("✓ Cloud", sidebar_text)
                self.assertIn("▶ Host & SSH", sidebar_text)

    async def test_first_run_cloud_sync_failure_blocks_next_and_marks_sidebar_error(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.failure(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    selected_region=selected_region or "",
                    summary="Hetzner authentication failed: token appears invalid.",
                    remediation=remediation_for(
                        provider, "token_invalid", "token rejected"
                    ),
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "bad-token"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()

                result_widget = app.query_one("#first-run-cloud-step-status", Static)
                self.assertEqual(str(result_widget.renderable), "Wrong Hetzner token.")
                self.assertEqual(
                    str(getattr(result_widget.styles, "color", None)),
                    "Color(255, 0, 0, ansi=None)",
                )
                sidebar_text = str(
                    app.query_one("#first-run-step-sidebar", Static).renderable
                )
                self.assertIn("! Cloud", sidebar_text)

                next_button = app.query_one("#first-run-cloud-next", Button)
                self.assertTrue(next_button.disabled)
                self.assertEqual(app.config_flow.current_step, "cloud")

    async def test_first_run_cloud_sync_shows_progress_while_live_call_is_running(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        def slow_sync(
            provider: ProviderId, token: str, selected_region: str | None
        ) -> CloudMetadataSyncResult:
            time.sleep(0.2)
            return CloudMetadataSyncResult.success(
                provider=provider,
                token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                regions=(LabeledValue("Falkenstein (fsn1)", "fsn1"),),
                server_types=(LabeledValue("cx22", "cx22"),),
                selected_region=selected_region or "fsn1",
                summary="Live cloud metadata synced.",
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = slow_sync

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause(0.05)

                status_widget = app.query_one("#first-run-cloud-step-status", Static)
                progress_text = str(status_widget.renderable)
                self.assertIn("Syncing", progress_text)
                wave = progress_text.removesuffix("Syncing live cloud metadata...")
                self.assertEqual(len(wave), 3)
                self.assertFalse(wave.endswith("⠀"))
                self.assertTrue(progress_text.startswith(wave + "Syncing"))
                self.assertTrue(any(frame in progress_text for frame in "⢀⣠⣴⣾⣿⣷⣦⣄"))
                title_color = str(
                    getattr(
                        app.query_one("#first-run-step-title", Static).styles,
                        "color",
                        None,
                    )
                )
                self.assertEqual(
                    str(getattr(status_widget.styles, "color", None)), title_color
                )
                self.assertTrue(app.query_one("#first-run-cloud-sync", Button).disabled)
                self.assertFalse(app.query("#first-run-cloud-progress-row"))

                await pilot.pause(0.3)
                progress_text = str(
                    app.query_one("#first-run-cloud-step-status", Static).renderable
                )
                self.assertEqual(progress_text, "Cloud metadata synced.")
                self.assertIn(
                    "Color(255, 255, 255",
                    str(
                        getattr(
                            app.query_one(
                                "#first-run-cloud-step-status", Static
                            ).styles,
                            "color",
                            None,
                        )
                    ),
                )
                region_section = app.query_one("#first-run-cloud-region-section")
                server_type_section = app.query_one(
                    "#first-run-cloud-server-type-section"
                )
                self.assertEqual(str(region_section.styles.display), "block")
                self.assertEqual(str(server_type_section.styles.display), "block")
                self.assertEqual(str(region_section.styles.height), "auto")
                self.assertEqual(str(server_type_section.styles.height), "auto")
                self.assertEqual(
                    app.query_one("#first-run-cloud-server-type", Select).value, "cx22"
                )

    async def test_first_run_cloud_sync_missing_hetzner_token_shows_short_red_error(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.failure(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=False;token_len={len(token)}",
                    selected_region=selected_region or "",
                    summary="Live cloud lookup blocked: HCLOUD_TOKEN is missing.",
                    remediation=remediation_for(provider, "missing_token"),
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()

                result_widget = app.query_one("#first-run-cloud-step-status", Static)
                self.assertEqual(
                    str(result_widget.renderable), "Missing Hetzner token."
                )
                self.assertEqual(
                    str(getattr(result_widget.styles, "color", None)),
                    "Color(255, 0, 0, ansi=None)",
                )

    async def test_first_run_cloud_sync_missing_linode_token_shows_short_red_error(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.failure(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=False;token_len={len(token)}",
                    selected_region=selected_region or "",
                    summary="Live cloud lookup blocked: LINODE_TOKEN is missing.",
                    remediation=remediation_for(provider, "missing_token"),
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-provider", Select).value = "linode"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()

                result_widget = app.query_one("#first-run-cloud-step-status", Static)
                self.assertEqual(str(result_widget.renderable), "Missing Linode token.")
                self.assertEqual(
                    str(getattr(result_widget.styles, "color", None)),
                    "Color(255, 0, 0, ansi=None)",
                )

    async def test_first_run_cloud_sync_regular_failure_shows_full_red_error(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.failure(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    selected_region=selected_region or "",
                    summary="Hetzner metadata lookup failed.",
                    remediation=remediation_for(
                        provider, "metadata_unavailable", "provider API unavailable"
                    ),
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()

                result_widget = app.query_one("#first-run-cloud-step-status", Static)
                result_text = str(result_widget.renderable)
                self.assertIn("Hetzner metadata lookup failed", result_text)
                self.assertIn("Reason: metadata_unavailable", result_text)
                self.assertEqual(
                    str(getattr(result_widget.styles, "color", None)),
                    "Color(255, 0, 0, ansi=None)",
                )

    async def test_first_run_cloud_sync_invalid_linode_token_shows_short_red_error(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.failure(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    selected_region=selected_region or "",
                    summary="Linode authentication failed: token rejected.",
                    remediation=remediation_for(
                        provider, "token_invalid", "token rejected"
                    ),
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-provider", Select).value = "linode"
                app.query_one("#first-run-cloud-token", Input).value = "bad-token"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()

                result_widget = app.query_one("#first-run-cloud-step-status", Static)
                self.assertEqual(str(result_widget.renderable), "Wrong Linode token.")
                self.assertEqual(
                    str(getattr(result_widget.styles, "color", None)),
                    "Color(255, 0, 0, ansi=None)",
                )

    async def test_first_run_cloud_region_change_shows_full_region_name_in_region_loading_text(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        calls: list[str] = []

        def sync(
            provider: ProviderId, token: str, selected_region: str | None
        ) -> CloudMetadataSyncResult:
            region = selected_region or "fsn1"
            calls.append(region)
            if region == "nbg1":
                time.sleep(0.2)
            server_types = (
                (LabeledValue("cx22", "cx22"),)
                if region == "fsn1"
                else (LabeledValue("cx32", "cx32"),)
            )
            return CloudMetadataSyncResult.success(
                provider=provider,
                token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                regions=(
                    LabeledValue("Falkenstein (fsn1)", "fsn1"),
                    LabeledValue("Nuremberg (nbg1)", "nbg1"),
                ),
                server_types=server_types,
                selected_region=region,
                summary="Live cloud metadata synced.",
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = sync

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause(0.05)
                app.query_one("#first-run-cloud-region", Select).value = "nbg1"
                await pilot.pause(0.05)

                sync_text = str(
                    app.query_one("#first-run-cloud-step-status", Static).renderable
                )
                self.assertIn("Nuremberg (nbg1)", sync_text)
                self.assertIn("Syncing server types", sync_text)

                await pilot.pause(0.3)
                self.assertEqual(calls, ["fsn1", "nbg1"])
                self.assertEqual(
                    app.query_one("#first-run-cloud-server-type", Select).value, "cx32"
                )

    async def test_first_run_cloud_sync_success_populates_live_region_and_server_type_options(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.success(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    regions=(
                        LabeledValue("Falkenstein (fsn1)", "fsn1"),
                        LabeledValue("Nuremberg (nbg1)", "nbg1"),
                    ),
                    server_types=(
                        LabeledValue("cx22 • 2 vCPU", "cx22"),
                        LabeledValue("cx32 • 4 vCPU", "cx32", recommended=True),
                    ),
                    selected_region=selected_region or "fsn1",
                    summary="Live cloud metadata synced.",
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()

                result_text = str(
                    app.query_one("#first-run-cloud-step-status", Static).renderable
                )
                self.assertEqual(result_text, "Cloud metadata synced.")
                self.assertNotIn("sample metadata", result_text)
                self.assertEqual(
                    app.query_one("#first-run-cloud-region", Select).value, "fsn1"
                )
                self.assertEqual(
                    app.query_one("#first-run-cloud-server-type", Select).value, "cx32"
                )

                _ = app.query_one("#first-run-cloud-next", Button).press()
                await pilot.pause()
                self.assertEqual(app.config_flow.current_step, "server")
                self.assertEqual(
                    app.query_one("#first-run-cloud-summary", Static).styles.display,
                    "none",
                )

    async def test_first_run_cloud_region_change_refreshes_live_server_types_for_selected_region(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        calls: list[str] = []

        def sync(
            provider: str, token: str, selected_region: str | None
        ) -> CloudMetadataSyncResult:
            region = selected_region or "fsn1"
            calls.append(region)
            server_types = (
                (LabeledValue("cx22", "cx22"),)
                if region == "fsn1"
                else (LabeledValue("cx32", "cx32"),)
            )
            return CloudMetadataSyncResult.success(
                provider=cast(ProviderId, provider),
                token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                regions=(
                    LabeledValue("Falkenstein (fsn1)", "fsn1"),
                    LabeledValue("Nuremberg (nbg1)", "nbg1"),
                ),
                server_types=server_types,
                selected_region=region,
                summary="Live cloud metadata synced.",
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = sync

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                app.query_one("#first-run-cloud-region", Select).value = "nbg1"
                await pilot.pause()

                self.assertEqual(calls, ["fsn1", "nbg1"])
                self.assertEqual(
                    app.query_one("#first-run-cloud-server-type", Select).value, "cx32"
                )

    async def test_first_run_cloud_synced_metadata_invalidates_on_token_change(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.success(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    regions=(LabeledValue("Falkenstein (fsn1)", "fsn1"),),
                    server_types=(LabeledValue("cx22", "cx22"),),
                    selected_region="fsn1",
                    summary="Live cloud metadata synced.",
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                token_input = app.query_one("#first-run-cloud-token", Input)
                token_input.value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                self.assertTrue(app.config_flow.cloud_metadata_synced)

                token_input.value = "new-hcloud-secret"
                await pilot.pause()
                self.assertFalse(app.config_flow.cloud_metadata_synced)
                self.assertIs(
                    app.query_one("#first-run-cloud-region", Select).value, Select.BLANK
                )

    async def test_host_ssh_defaults_render_after_cloud_completion_for_missing_env(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.success(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    regions=(LabeledValue("Nuremberg (nbg1)", "nbg1"),),
                    server_types=(LabeledValue("cx22", "cx22"),),
                    selected_region="nbg1",
                    summary="Live cloud metadata synced.",
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                _ = app.query_one("#first-run-cloud-next", Button).press()
                await pilot.pause()

                self.assertEqual(app.config_flow.current_step, "server")
                self.assertIn(
                    "Host & SSH",
                    str(app.query_one("#first-run-step-title", Static).renderable),
                )
                self.assertEqual(
                    app.query_one("#first-run-hostname", Input).value, "hermes-vps"
                )
                self.assertEqual(
                    app.query_one("#first-run-admin-username", Input).value, "hermes"
                )
                self.assertEqual(
                    app.query_one("#first-run-admin-group", Input).value,
                    "hermes-admins",
                )
                self.assertEqual(
                    app.query_one("#first-run-ssh-key-path", Input).value,
                    "~/.ssh/hermes-vps",
                )
                self.assertTrue(app.query_one("#first-run-ssh-alias", Checkbox).value)
                self.assertIn(
                    "No SSH config changes are made until Review/Apply.",
                    str(
                        app.query_one("#first-run-ssh-alias-helper", Static).renderable
                    ),
                )
                self.assertEqual(
                    str(app.query_one("#first-run-host-ssh-next", Button).label),
                    "Next: Hermes",
                )
                self.assertEqual(
                    app.query_one("#first-run-hostname-spacer", Static).styles.display,
                    "block",
                )
                self.assertEqual(
                    app.query_one("#first-run-ssh-key-path-spacer", Static).styles.display,
                    "block",
                )
                visible_text = self._visible_first_run_step_text(app)
                self.assertNotIn("Cloud provider", visible_text)
                self.assertNotIn("Token", visible_text)
                self.assertNotIn("Region", visible_text)
                self.assertNotIn("Server type", visible_text)

    async def test_host_ssh_editing_next_updates_draft_and_advances_without_writes(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.success(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    regions=(LabeledValue("Nuremberg (nbg1)", "nbg1"),),
                    server_types=(LabeledValue("cx22", "cx22"),),
                    selected_region="nbg1",
                    summary="Live cloud metadata synced.",
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                _ = app.query_one("#first-run-cloud-next", Button).press()
                await pilot.pause()

                app.query_one("#first-run-hostname", Input).value = "prod-vps-01"
                app.query_one("#first-run-admin-username", Input).value = "opsadmin"
                app.query_one("#first-run-admin-group", Input).value = "sshadmins"
                app.query_one(
                    "#first-run-ssh-key-path", Input
                ).value = "~/.ssh/prod-vps-01"
                app.query_one("#first-run-ssh-alias", Checkbox).value = False
                _ = app.query_one("#first-run-host-ssh-next", Button).press()
                await pilot.pause()

                self.assertEqual(app.config_flow.current_step, "hermes")
                self.assertEqual(app.config_flow.draft.server.hostname, "prod-vps-01")
                self.assertEqual(
                    app.config_flow.draft.server.admin_username, "opsadmin"
                )
                self.assertEqual(app.config_flow.draft.server.admin_group, "sshadmins")
                self.assertEqual(
                    app.config_flow.draft.server.ssh_private_key_path,
                    "~/.ssh/prod-vps-01",
                )
                self.assertFalse(app.config_flow.draft.server.add_ssh_alias)
                self.assertIn(
                    "Hermes",
                    str(app.query_one("#first-run-step-title", Static).renderable),
                )
                self.assertEqual(
                    app.query_one(
                        "#first-run-host-ssh-step-status", Static
                    ).styles.display,
                    "none",
                )
                self.assertFalse((root / ".env").exists())
                self.assertFalse((root / "keys").exists())

    async def test_host_ssh_invalid_repo_relative_key_blocks_with_local_status(
        self,
    ) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup = _configuration_required_startup()
            app = HermesControlPanelApp(
                shell=ControlPanelShell(
                    startup_result=startup, initial_panel="configuration"
                ),
                repo_root=root,
                startup_result=startup,
                initial_panel="configuration",
            )
            app.config_flow.cloud_metadata_sync_runner = (
                lambda provider,
                token,
                selected_region: CloudMetadataSyncResult.success(
                    provider=provider,
                    token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
                    regions=(LabeledValue("Nuremberg (nbg1)", "nbg1"),),
                    server_types=(LabeledValue("cx22", "cx22"),),
                    selected_region="nbg1",
                    summary="Live cloud metadata synced.",
                )
            )

            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
                _ = app.query_one("#first-run-cloud-sync", Button).press()
                await pilot.pause()
                _ = app.query_one("#first-run-cloud-next", Button).press()
                await pilot.pause()

                app.query_one(
                    "#first-run-ssh-key-path", Input
                ).value = "keys/hermes-vps"
                _ = app.query_one("#first-run-host-ssh-next", Button).press()
                await pilot.pause()

                self.assertEqual(app.config_flow.current_step, "server")
                local_status = str(
                    app.query_one("#first-run-host-ssh-step-status", Static).renderable
                )
                header_status = str(app.query_one("#action-status", Static).renderable)
                self.assertIn(
                    "SSH private key path must be outside the repository", local_status
                )
                self.assertNotIn("SSH private key path", header_status)
                self.assertFalse((root / ".env").exists())
                self.assertFalse((root / "keys").exists())

    async def test_hermes_defaults_render_after_host_ssh_completion(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self._first_run_app_at_tmp(root)
            app.config_flow.cloud_metadata_sync_runner = self._successful_cloud_sync

            async with app.run_test() as pilot:
                await self._advance_to_hermes(app, pilot)

                self.assertEqual(app.config_flow.current_step, "hermes")
                self.assertIn(
                    "Hermes",
                    str(app.query_one("#first-run-step-title", Static).renderable),
                )
                self.assertEqual(app.query_one("#first-run-hermes-version", Select).value, "0.10.0")
                self.assertEqual(
                    str(app.query_one("#first-run-hermes-release-tag", Static).renderable),
                    "Release tag: v2026.4.16",
                )
                self.assertEqual(app.query_one("#first-run-hermes-provider", Select).value, "openai-codex")
                self.assertEqual(app.query_one("#first-run-hermes-model", Select).value, "gpt-5.4-mini")
                self.assertEqual(app.query_one("#first-run-hermes-auth-method", Select).value, "oauth")
                self.assertEqual(str(app.query_one("#first-run-hermes-oauth-button", Button).label), "Start OAuth")
                self.assertEqual(
                    app.query_one("#first-run-hermes-version-spacer", Static).styles.display,
                    "block",
                )
                self.assertEqual(
                    app.query_one("#first-run-hermes-auth-method-spacer", Static).styles.display,
                    "block",
                )
                visible_text = self._visible_first_run_step_text(app)
                self.assertNotIn("Cloud provider", visible_text)
                self.assertNotIn("Hostname", visible_text)
                self.assertNotIn("Admin username", visible_text)
                self.assertNotIn("SSH private key path", visible_text)
                self.assertEqual(
                    app.query_one("#first-run-hermes-api-key", Input).placeholder,
                    "openai-codex API key",
                )
                app.query_one("#first-run-hermes-provider", Select).value = "anthropic"
                await pilot.pause()
                self.assertEqual(
                    app.query_one("#first-run-hermes-api-key", Input).placeholder,
                    "anthropic API key",
                )
                self.assertEqual(str(app.query_one("#first-run-hermes-next", Button).label), "Next: Gateways")

    async def test_hermes_oauth_placeholder_advances_to_gateways_without_writes(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self._first_run_app_at_tmp(root)
            app.config_flow.cloud_metadata_sync_runner = self._successful_cloud_sync

            async with app.run_test() as pilot:
                await self._advance_to_hermes(app, pilot)
                app.query_one("#first-run-hermes-provider", Select).value = "anthropic"
                await pilot.pause()
                app.query_one("#first-run-hermes-model", Select).value = "anthropic/claude-opus-4"
                _ = app.query_one("#first-run-hermes-oauth-button", Button).press()
                await pilot.pause()
                self.assertIn(
                    "OAuth flow will run in a later/apply-capable slice.",
                    str(app.query_one("#first-run-hermes-oauth-output", Static).renderable),
                )

                _ = app.query_one("#first-run-hermes-next", Button).press()
                await pilot.pause()

                self.assertEqual(app.config_flow.current_step, "telegram")
                self.assertEqual(app.config_flow.draft.hermes.provider, "anthropic")
                self.assertEqual(app.config_flow.draft.hermes.model, "anthropic/claude-opus-4")
                self.assertEqual(app.config_flow.draft.hermes.agent_version, "0.10.0")
                self.assertEqual(app.config_flow.draft.hermes.agent_release_tag, "v2026.4.16")
                self.assertIn(
                    "Gateways",
                    str(app.query_one("#first-run-step-title", Static).renderable),
                )
                self.assertFalse((root / ".env").exists())

    async def test_hermes_api_key_mode_blocks_until_key_then_advances_without_writes(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self._first_run_app_at_tmp(root)
            app.config_flow.cloud_metadata_sync_runner = self._successful_cloud_sync

            async with app.run_test() as pilot:
                await self._advance_to_hermes(app, pilot)
                app.query_one("#first-run-hermes-auth-method", Select).value = "api_key"
                await pilot.pause()

                _ = app.query_one("#first-run-hermes-next", Button).press()
                await pilot.pause()
                self.assertEqual(app.config_flow.current_step, "hermes")
                self.assertIn(
                    "openai-codex API key is required",
                    str(app.query_one("#first-run-hermes-step-status", Static).renderable),
                )

                app.query_one("#first-run-hermes-api-key", Input).value = "hermes-secret"
                _ = app.query_one("#first-run-hermes-next", Button).press()
                await pilot.pause()

                self.assertEqual(app.config_flow.current_step, "telegram")
                self.assertEqual(app.config_flow.draft.hermes.api_key.replacement, "hermes-secret")
                self.assertFalse((root / ".env").exists())

    @staticmethod
    def _successful_cloud_sync(provider: ProviderId, token: str, selected_region: str | None) -> CloudMetadataSyncResult:
        return CloudMetadataSyncResult.success(
            provider=provider,
            token_fingerprint=f"provider={provider};token_present=True;token_len={len(token)}",
            regions=(LabeledValue("Nuremberg (nbg1)", "nbg1"),),
            server_types=(LabeledValue("cx22", "cx22"),),
            selected_region="nbg1",
            summary="Live cloud metadata synced.",
        )

    @staticmethod
    def _first_run_app_at_tmp(root: Path) -> HermesControlPanelApp:
        startup = _configuration_required_startup()
        return HermesControlPanelApp(
            shell=ControlPanelShell(startup_result=startup, initial_panel="configuration"),
            repo_root=root,
            startup_result=startup,
            initial_panel="configuration",
        )

    async def _advance_to_hermes(self, app: HermesControlPanelApp, pilot: object) -> None:
        pause = getattr(pilot, "pause")
        await pause()
        app.query_one("#first-run-cloud-token", Input).value = "hcloud-secret"
        _ = app.query_one("#first-run-cloud-sync", Button).press()
        await pause()
        _ = app.query_one("#first-run-cloud-next", Button).press()
        await pause()
        _ = app.query_one("#first-run-host-ssh-next", Button).press()
        await pause()

    @staticmethod
    def _visible_first_run_step_text(app: HermesControlPanelApp) -> str:
        main = app.query_one("#first-run-step-main")
        parts: list[str] = []
        for widget in main.walk_children():
            current = widget
            hidden = False
            while current is not None and current is not main:
                if current.styles.display == "none":
                    hidden = True
                    break
                current = current.parent
            if hidden:
                continue
            renderable = getattr(widget, "renderable", None)
            if renderable is not None:
                parts.append(str(renderable))
        return "\n".join(parts)


if __name__ == "__main__":
    _ = unittest.main()
