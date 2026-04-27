"""Contract-freeze tests for async/worker stale-result and unlock semantics.

These tests pin down current behavior for the cloud/hermes/telegram
async flows so that Batch 4 (unify async correlation IDs) cannot drop
or weaken what the wizard already does:

* The Hermes step must discard a metadata reply that does not match
  the user's most recent provider choice.
* A telegram validation reply that arrives after the pending-advance
  gate has cleared must not auto-advance.
* When two provider switches happen in rapid succession, only the
  latest provider must end up in state.
* On any worker error path, the Next button must re-enable so the
  user can retry without restarting the wizard.
"""

# pyright: reportAttributeAccessIssue=false, reportPrivateUsage=false, reportUnusedCallResult=false

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from textual.widgets import Button, Static

from tests.test_configure_tui import _DeterministicConfigureTUI, _FakeOrchestrator

from scripts.configure_tui import (
    CloudLoaded,
    HermesApiKeyValidated,
    HermesLoaded,
    TelegramValidated,
)


def _make_app() -> _DeterministicConfigureTUI:
    return _DeterministicConfigureTUI(
        root_dir=pathlib.Path("."), orchestrator=_FakeOrchestrator()
    )


class HermesStaleResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_hermes_metadata_stale_result_is_dropped_when_provider_no_longer_matches(
        self,
    ) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            # Simulate the user having switched to "anthropic" while a
            # load for "openai-codex" is still in flight.
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

            # Stale result must not overwrite the user's current selection.
            self.assertEqual(app.state.hermes_provider, "anthropic")
            self.assertNotEqual(app.state.hermes_provider, "openai-codex")

    async def test_hermes_provider_rapid_switch_only_latest_provider_applies(
        self,
    ) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            provider_select = app.query_one("#hermes-provider-select")
            provider_select.value = "anthropic"
            await pilot.pause()
            provider_select.value = "openai-codex"
            await pilot.pause()
            await pilot.pause()

            self.assertEqual(app.state.hermes_provider, "openai-codex")


class TelegramStaleResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_telegram_validation_reply_does_not_advance_when_pending_gate_cleared(
        self,
    ) -> None:
        app = _make_app()
        orchestrator = app.orchestrator
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 3
            await pilot.pause()

            # Simulate a stale validation reply: the pending-advance flag is
            # already False (e.g. because the user pressed Back or another
            # validation cycle was started).
            app._pending_telegram_validation_next = False
            app._telegram_loading = True
            app.post_message(TelegramValidated(status="late but harmless"))
            await pilot.pause()

            self.assertEqual(app.current_step, 3)
            self.assertFalse(orchestrator.telegram_persisted)


class HermesMetadataCorrelationTests(unittest.IsolatedAsyncioTestCase):
    async def test_hermes_metadata_with_stale_request_id_is_dropped(self) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            baseline_models = list(app.hermes_model_options)

            app.state.hermes_provider = "anthropic"
            app._pending_hermes_provider = "anthropic"
            app._hermes_loading = True
            app._hermes_metadata_task.force_active(7)
            app.post_message(
                HermesLoaded(
                    providers=["openai-codex", "anthropic"],
                    models=["claude-sonnet-4"],
                    resolved_provider="openai-codex",
                    auth_type="api_key",
                    auth_env_vars=["HERMES_API_KEY"],
                    request_id=6,
                )
            )
            await pilot.pause()

            self.assertTrue(app._hermes_loading)
            self.assertEqual(app.state.hermes_provider, "anthropic")
            self.assertEqual(app.hermes_model_options, baseline_models)

    async def test_hermes_metadata_with_current_request_id_updates_state(self) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            request_id = app._hermes_metadata_task.begin()
            app._hermes_loading = True
            app.post_message(
                HermesLoaded(
                    providers=["openai-codex", "anthropic"],
                    models=["gpt-5.4-mini"],
                    resolved_provider="openai-codex",
                    auth_type="api_key",
                    auth_env_vars=["HERMES_API_KEY"],
                    request_id=request_id,
                )
            )
            await pilot.pause()

            self.assertFalse(app._hermes_loading)
            self.assertEqual(app.state.hermes_provider, "openai-codex")
            self.assertEqual(app.state.hermes_auth_type, "api_key")
            self.assertIn("gpt-5.4-mini", app.hermes_model_options)


class WorkerErrorUnlockTests(unittest.IsolatedAsyncioTestCase):
    async def test_next_button_reenabled_after_telegram_validation_error(self) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 3
            await pilot.pause()

            next_button = app.query_one("#next", Button)
            app._telegram_loading = True
            app._pending_telegram_validation_next = True
            app._refresh_next_button_state()
            self.assertTrue(next_button.disabled)

            app.post_message(TelegramValidated(error="Invalid Telegram bot token."))
            await pilot.pause()

            self.assertFalse(next_button.disabled)
            self.assertFalse(app._pending_telegram_validation_next)
            error_text = str(app.query_one("#error", Static).renderable)
            self.assertIn("Invalid Telegram bot token", error_text)

    async def test_next_button_reenabled_after_hermes_api_key_validation_error(
        self,
    ) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            next_button = app.query_one("#next", Button)
            app._hermes_api_key_validating = True
            app._pending_hermes_api_key_validation_next = True
            app._refresh_next_button_state()
            self.assertTrue(next_button.disabled)

            app.post_message(HermesApiKeyValidated(error="Invalid Hermes API key."))
            await pilot.pause()

            self.assertFalse(next_button.disabled)
            self.assertFalse(app._pending_hermes_api_key_validation_next)
            error_text = str(app.query_one("#error", Static).renderable)
            self.assertIn("Invalid Hermes API key", error_text)

    async def test_next_button_reenabled_after_cloud_lookup_error(self) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 0
            await pilot.pause()

            next_button = app.query_one("#next", Button)
            app._cloud_loading = True
            app._active_cloud_request_id = 7
            app._pending_cloud_validation_next = True
            app._pending_cloud_validation_request_id = 7
            app._refresh_next_button_state()
            self.assertTrue(next_button.disabled)

            app.post_message(
                CloudLoaded(
                    locations=[],
                    server_types=[],
                    error="Invalid Hetzner API token.",
                    request_id=7,
                )
            )
            await pilot.pause()

            self.assertFalse(next_button.disabled)
            self.assertFalse(app._pending_cloud_validation_next)
            self.assertIsNone(app._pending_cloud_validation_request_id)
            error_text = str(app.query_one("#error", Static).renderable)
            self.assertIn("Invalid Hetzner API token", error_text)


class CorrelationIdStaleDropTests(unittest.IsolatedAsyncioTestCase):
    async def test_telegram_validation_with_stale_request_id_is_dropped(self) -> None:
        app = _make_app()
        orchestrator = app.orchestrator
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 3
            await pilot.pause()

            # Latest task id is 7; arrival with id=6 must be dropped at the gate.
            app._telegram_task.force_active(7)
            app._telegram_loading = True
            app._pending_telegram_validation_next = True
            app.post_message(
                TelegramValidated(status="ignored", request_id=6)
            )
            await pilot.pause()

            self.assertTrue(
                app._telegram_loading,
                "stale telegram reply must not flip the loading flag",
            )
            self.assertTrue(app._pending_telegram_validation_next)
            self.assertEqual(app.current_step, 3)
            self.assertFalse(orchestrator.telegram_persisted)

    async def test_telegram_validation_with_current_request_id_is_processed(
        self,
    ) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 3
            await pilot.pause()

            request_id = app._telegram_task.begin()
            app._telegram_loading = True
            app.post_message(
                TelegramValidated(status="all good", request_id=request_id)
            )
            await pilot.pause()

            self.assertFalse(app._telegram_loading)
            status = str(app.query_one("#status", Static).renderable)
            self.assertIn("all good", status)

    async def test_hermes_api_key_validation_with_stale_request_id_is_dropped(
        self,
    ) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 2
            await pilot.pause()

            app._hermes_api_key_task.force_active(4)
            app._hermes_api_key_validating = True
            app._pending_hermes_api_key_validation_next = True
            app.post_message(
                HermesApiKeyValidated(status="ignored", request_id=3)
            )
            await pilot.pause()

            self.assertTrue(
                app._hermes_api_key_validating,
                "stale api-key reply must not flip the validating flag",
            )
            self.assertTrue(app._pending_hermes_api_key_validation_next)
            self.assertEqual(app.current_step, 2)

    async def test_cloud_load_with_stale_request_id_is_dropped(self) -> None:
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.current_step = 0
            await pilot.pause()

            app._cloud_task.force_active(11)
            app._cloud_loading = True
            app.post_message(
                CloudLoaded(
                    locations=[],
                    server_types=[],
                    error="ignored stale error",
                    request_id=10,
                )
            )
            await pilot.pause()

            # Stale error must not even surface to the user.
            self.assertTrue(app._cloud_loading)
            error_text = str(app.query_one("#error", Static).renderable)
            self.assertNotIn("ignored stale error", error_text)


if __name__ == "__main__":
    unittest.main()
