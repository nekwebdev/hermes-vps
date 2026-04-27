# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
"""Apply-plan boundary tests.

These tests lock the new plan/execute split for ConfigureOrchestrator.
Batch 2 must make planning pure and keep execution order explicit.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts import configure_services as services
from scripts.configure_state import WizardState


class ApplyPlanBoundaryTests(unittest.TestCase):
    def _make_orchestrator(self, root: pathlib.Path) -> services.ConfigureOrchestrator:
        (root / ".env.example").write_text("HERMES_API_KEY=\n")
        (root / ".env").write_text("HERMES_API_KEY=\n")
        return services.ConfigureOrchestrator(root)

    @staticmethod
    def _base_state() -> WizardState:
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
            hermes_agent_release_tag="stale-tag",
            hermes_provider="openai-codex",
            hermes_model="gpt-5.4-mini",
            telegram_allowlist_ids="12345",
            telegram_bot_token_replace=False,
            telegram_bot_token_input="",
            original_values={"HERMES_AGENT_RELEASE_TAG": "old-tag"},
        )

    def test_build_apply_plan_is_pure_and_returns_typed_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            state = self._base_state()

            orchestrator.env.set = MagicMock()
            orchestrator.env.flush = MagicMock()
            orchestrator.persist_cloud_step = MagicMock()
            orchestrator.persist_server_step = MagicMock()
            orchestrator.persist_hermes_step = MagicMock()
            orchestrator.persist_telegram_step = MagicMock()
            orchestrator.ensure_ssh_key_material = MagicMock()
            orchestrator.ensure_repo_ssh_alias = MagicMock()
            orchestrator.remove_repo_ssh_alias = MagicMock()

            plan = orchestrator.build_apply_plan(state)

            self.assertIsInstance(plan, services.ApplyPlan)
            self.assertEqual(plan.effects, services.APPLY_EFFECT_ORDER)
            self.assertEqual(state.hermes_agent_release_tag, "stale-tag")
            orchestrator.env.set.assert_not_called()
            orchestrator.env.flush.assert_not_called()
            orchestrator.persist_cloud_step.assert_not_called()
            orchestrator.persist_server_step.assert_not_called()
            orchestrator.persist_hermes_step.assert_not_called()
            orchestrator.persist_telegram_step.assert_not_called()

    def test_execute_apply_plan_runs_effects_in_order_and_returns_recap_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            state = self._base_state()
            plan = services.ApplyPlan(
                state=state,
                effects=("persist_cloud", "persist_server", "flush_env"),
            )
            calls: list[str] = []

            def _persist_cloud_step(_state: object) -> None:
                calls.append("persist_cloud")

            def _persist_server_step(_state: object) -> None:
                calls.append("persist_server")

            with patch.object(
                orchestrator,
                "persist_cloud_step",
                side_effect=_persist_cloud_step,
            ), patch.object(
                orchestrator,
                "persist_server_step",
                side_effect=_persist_server_step,
            ), patch.object(
                orchestrator.env,
                "flush",
                side_effect=lambda: calls.append("flush_env"),
            ):
                rows = orchestrator.execute_apply_plan(plan)

            self.assertEqual(calls, ["persist_cloud", "persist_server", "flush_env"])
            self.assertEqual(rows, state.recap_rows())


if __name__ == "__main__":
    unittest.main()
