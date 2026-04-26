"""Apply-pipeline atomicity and ordering tests.

These tests pin three guarantees for the wizard's commit phase:

1. The apply pipeline runs effects in a deterministic, named order
   (so future controller extraction or framework moves cannot reorder
   silently — partial-commit semantics depend on the order).
2. The .env file is updated with a temp + os.replace pattern so a
   crash mid-write cannot leave a half-written .env.
3. If a side effect that runs *before* the env flush fails (e.g. SSH
   alias reconciliation), the .env file on disk is unchanged. This is
   the partial-commit floor: stages cannot leak past a failed step.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.configure_services import (
    APPLY_EFFECT_ORDER,
    ConfigureOrchestrator,
    ConfigureServiceError,
    EnvStore,
)


class _RepoFixture:
    def __init__(self) -> None:
        self.tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="hermes-apply-"))
        (self.tmpdir / ".env.example").write_text(
            "TF_VAR_cloud_provider=hetzner\n"
            "TF_VAR_server_image=debian-13\n"
            "HCLOUD_TOKEN=existing-token\n"
            "TELEGRAM_BOT_TOKEN=existing-bot\n"
            "HERMES_API_KEY=existing-key\n"
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class ApplyEffectOrderTests(unittest.TestCase):
    def test_apply_effect_order_is_deterministic_and_flush_is_last(self) -> None:
        # The order is the contract; downstream batches must update both
        # this list and APPLY_EFFECT_ORDER together if they reorder.
        self.assertEqual(
            APPLY_EFFECT_ORDER,
            (
                "persist_cloud",
                "persist_server",
                "persist_hermes",
                "persist_telegram",
                "stage_extras",
                "ensure_ssh_key",
                "reconcile_ssh_alias",
                "flush_env",
            ),
        )
        self.assertEqual(APPLY_EFFECT_ORDER[-1], "flush_env")


class EnvFlushAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _RepoFixture()
        self.addCleanup(self.fixture.cleanup)
        self.store = EnvStore(self.fixture.tmpdir)
        self.store.ensure()

    def test_env_flush_uses_atomic_temp_then_replace(self) -> None:
        self.store.set("HCLOUD_TOKEN", "new-token")
        captured: list[tuple[str, str]] = []

        real_replace = os.replace

        def spy_replace(src, dst):  # type: ignore[no-untyped-def]
            captured.append((str(src), str(dst)))
            real_replace(src, dst)

        with patch("scripts.configure_services.os.replace", spy_replace):
            self.store.flush()

        self.assertEqual(len(captured), 1, "env flush must perform exactly one atomic replace")
        src, dst = captured[0]
        env_path = str(self.fixture.tmpdir / ".env")
        self.assertEqual(dst, env_path)
        self.assertNotEqual(src, env_path, "temp path must be distinct from the final env file")
        self.assertEqual(pathlib.Path(env_path).read_text().count("HCLOUD_TOKEN=new-token"), 1)

    def test_env_flush_no_op_when_no_staged_changes(self) -> None:
        captured: list[tuple[str, str]] = []
        real_replace = os.replace

        def spy_replace(src, dst):  # type: ignore[no-untyped-def]
            captured.append((str(src), str(dst)))
            real_replace(src, dst)

        with patch("scripts.configure_services.os.replace", spy_replace):
            self.store.flush()

        self.assertEqual(captured, [])

    def test_env_flush_does_not_leave_temp_file_on_success(self) -> None:
        self.store.set("HCLOUD_TOKEN", "another-token")
        self.store.flush()
        leftovers = [p.name for p in self.fixture.tmpdir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_env_flush_clears_staged_values_after_success(self) -> None:
        self.store.set("HCLOUD_TOKEN", "fresh-token")
        self.store.flush()
        self.assertEqual(self.store._staged, {})

        captured: list[tuple[str, str]] = []
        real_replace = os.replace

        def spy_replace(src, dst):  # type: ignore[no-untyped-def]
            captured.append((str(src), str(dst)))
            real_replace(src, dst)

        with patch("scripts.configure_services.os.replace", spy_replace):
            self.store.flush()

        self.assertEqual(captured, [])

    def test_env_flush_fsyncs_temp_file_before_replace(self) -> None:
        self.store.set("HCLOUD_TOKEN", "durable-token")
        events: list[str] = []
        real_fsync = os.fsync
        real_replace = os.replace

        def spy_fsync(fd):  # type: ignore[no-untyped-def]
            events.append("fsync")
            return real_fsync(fd)

        def spy_replace(src, dst):  # type: ignore[no-untyped-def]
            events.append("replace")
            return real_replace(src, dst)

        with patch("scripts.configure_services.os.fsync", spy_fsync), patch(
            "scripts.configure_services.os.replace", spy_replace
        ):
            self.store.flush()

        self.assertIn("fsync", events)
        self.assertIn("replace", events)
        self.assertLess(events.index("fsync"), events.index("replace"))


class ApplyPartialCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _RepoFixture()
        self.addCleanup(self.fixture.cleanup)

    def test_apply_does_not_modify_env_file_when_ssh_alias_step_fails(self) -> None:
        orchestrator = ConfigureOrchestrator(self.fixture.tmpdir)
        orchestrator.env.ensure()
        env_path = self.fixture.tmpdir / ".env"
        original_contents = env_path.read_text()

        # Build a minimal valid state by hand so the test does not depend
        # on real cloud/hermes I/O.
        from scripts.configure_state import WizardState

        state = WizardState(
            provider="hetzner",
            server_image="debian-13",
            location="nbg1",
            server_type="cx22",
            hostname="hermes-prod-01",
            admin_username="opsadmin",
            admin_group="sshadmins",
            ssh_private_key_path=str(self.fixture.tmpdir / "ssh-key"),
            hermes_agent_version="0.10.0",
            hermes_agent_release_tag="v0.10.0",
            hermes_provider="openai-codex",
            hermes_model="gpt-5.4-mini",
            hermes_auth_type="api_key",
            hermes_auth_method="api_key",
            hermes_api_key_input="new-key",
            telegram_bot_token_replace=False,
            telegram_allowlist_ids="12345",
            add_ssh_alias=True,
            original_values={"SSH_ALIAS": "inactive"},  # forces reconcile
        )

        # Force ensure_ssh_key_material to be a no-op so it doesn't shell out.
        def fake_keygen(preferred_path: str) -> tuple[str, str]:
            return preferred_path, "ssh-ed25519 AAAA fake"

        # Make the SSH alias step blow up.
        def boom(*_args, **_kwargs):
            raise ConfigureServiceError("simulated SSH alias edit failure")

        with patch.object(orchestrator, "ensure_ssh_key_material", side_effect=fake_keygen), \
             patch.object(orchestrator, "ensure_repo_ssh_alias", side_effect=boom):
            with self.assertRaises(ConfigureServiceError):
                orchestrator.apply(state)

        # The env file on disk must be unchanged: the failed alias step ran
        # before flush_env, so nothing got persisted.
        self.assertEqual(env_path.read_text(), original_contents)


if __name__ == "__main__":
    unittest.main()
