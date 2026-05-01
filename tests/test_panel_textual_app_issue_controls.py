# pyright: reportAny=false, reportImplicitOverride=false
from __future__ import annotations

import unittest
from pathlib import Path

from textual.widgets import Button, Static, TabbedContent

from hermes_vps_app.panel_shell import ControlPanelShell
from hermes_vps_app.panel_startup import PanelStartupResult, PanelStartupState, StartupStep
from hermes_vps_app.panel_textual_app import HermesControlPanelApp


def _startup() -> PanelStartupResult:
    return PanelStartupResult(
        state=PanelStartupState.DASHBOARD_READY,
        steps=(StartupStep(name="runner_detection", label="Detect runner", status="ok", detail="runner locked"),),
        runner_mode="direnv_nix",
        remediation="ready",
        provider="linode",
    )


class PanelTextualControlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_panel_app_exposes_actionable_controls_not_only_static_text(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ = (root / ".env").write_text("TF_VAR_cloud_provider=linode\n", encoding="utf-8")
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


if __name__ == "__main__":
    _ = unittest.main()
