# pyright: reportUnusedCallResult=false, reportImplicitStringConcatenation=false, reportUnannotatedClassAttribute=false
import pathlib
import tempfile
import unittest
from unittest import mock

from scripts.configure_services import (
    CommandResult,
    ConfigureOrchestrator,
    ConfigureServiceError,
    ProviderService,
)
from scripts.configure_state import WizardState


class ConfigureServicesTests(unittest.TestCase):
    class _ScriptedRunner:
        def __init__(self, script: list[CommandResult | Exception]) -> None:
            self.script = script
            self.calls: list[list[str]] = []

        def run(
            self, argv: list[str], env: dict[str, str] | None = None
        ) -> CommandResult:
            _ = env
            self.calls.append(argv)
            if not self.script:
                raise RuntimeError("runner script exhausted")
            next_item = self.script.pop(0)
            if isinstance(next_item, Exception):
                raise next_item
            return next_item

    def _make_orchestrator(self, root: pathlib.Path) -> ConfigureOrchestrator:
        (root / ".env.example").write_text("HERMES_API_KEY=\nTELEGRAM_BOT_TOKEN=\nTELEGRAM_ALLOWLIST_IDS=12345\n")
        (root / ".env").write_text("HERMES_API_KEY=\nTELEGRAM_BOT_TOKEN=\nTELEGRAM_ALLOWLIST_IDS=12345\n")
        return ConfigureOrchestrator(root)

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
            hermes_agent_release_tag="v0.10.0",
            hermes_provider="openai-codex",
            hermes_model="gpt-5.4-mini",
            telegram_allowlist_ids="12345",
            telegram_bot_token_replace=False,
            telegram_bot_token_input="",
            original_values={},
        )

    def test_load_initial_state_tracks_existing_auth_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".env.example").write_text(
                "TF_VAR_cloud_provider=hetzner\n"
                "HERMES_AGENT_VERSION=0.10.0\n"
                "HERMES_AGENT_RELEASE_TAG=v2026.4.16\n"
            )
            (root / ".env").write_text(
                "TF_VAR_cloud_provider=hetzner\n"
                "HERMES_AGENT_VERSION=0.10.0\n"
                "HERMES_AGENT_RELEASE_TAG=v2026.4.16\n"
            )
            orchestrator = ConfigureOrchestrator(root)
            orchestrator.hermes.auth_artifact = (
                root / "bootstrap" / "runtime" / "hermes-auth.json"
            )
            orchestrator.hermes.auth_artifact_exists = mock.MagicMock(return_value=True)

            state = orchestrator.load_initial_state()

            self.assertEqual(
                state.original_values.get("HERMES_AUTH_ARTIFACT"),
                str(orchestrator.hermes.auth_artifact),
            )

    def test_apply_hybrid_auth_uses_api_key_path_when_key_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            orchestrator.hermes.has_local_auth = mock.MagicMock(return_value=True)
            orchestrator.hermes.stage_local_auth_artifact = mock.MagicMock(return_value=True)
            orchestrator.hermes.clear_auth_artifact = mock.MagicMock()
            orchestrator.ensure_ssh_key_material = mock.MagicMock(return_value=("/tmp/hermes-test-key", "ssh-ed25519 AAAA test"))
            orchestrator.ensure_repo_ssh_alias = mock.MagicMock(return_value=True)
            orchestrator.remove_repo_ssh_alias = mock.MagicMock(return_value=True)
            orchestrator.telegram_token_present = mock.MagicMock(return_value=True)

            state = self._base_state()
            state.hermes_auth_type = "oauth_external+api_key"
            state.hermes_auth_method = "api_key"
            state.hermes_api_key_input = "[REDACTED]"
            state.add_ssh_alias = False

            orchestrator.apply(state)

            self.assertEqual(orchestrator.env.get("HERMES_API_KEY"), "[REDACTED]")
            orchestrator.hermes.clear_auth_artifact.assert_not_called()
            orchestrator.hermes.stage_local_auth_artifact.assert_not_called()
            self.assertEqual(state.recap_auth_artifact, "none")

    def test_apply_hybrid_auth_uses_oauth_artifact_when_no_key_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            orchestrator.hermes.auth_artifact = pathlib.Path(tmp) / "bootstrap" / "runtime" / "hermes-auth.json"
            orchestrator.hermes.has_local_auth = mock.MagicMock(return_value=True)
            orchestrator.hermes.auth_artifact_exists = mock.MagicMock(side_effect=[False, True])
            orchestrator.hermes.stage_local_auth_artifact = mock.MagicMock(return_value=True)
            orchestrator.hermes.clear_auth_artifact = mock.MagicMock()
            orchestrator.ensure_ssh_key_material = mock.MagicMock(return_value=("/tmp/hermes-test-key", "ssh-ed25519 AAAA test"))
            orchestrator.ensure_repo_ssh_alias = mock.MagicMock(return_value=True)
            orchestrator.remove_repo_ssh_alias = mock.MagicMock(return_value=True)
            orchestrator.telegram_token_present = mock.MagicMock(return_value=True)

            state = self._base_state()
            state.hermes_auth_type = "oauth_external+api_key"
            state.hermes_auth_method = "oauth"
            state.hermes_api_key_input = ""
            state.add_ssh_alias = False

            orchestrator.apply(state)

            orchestrator.hermes.stage_local_auth_artifact.assert_called_once()
            orchestrator.hermes.clear_auth_artifact.assert_not_called()
            self.assertEqual(state.recap_auth_artifact, str(orchestrator.hermes.auth_artifact))

    def test_validate_telegram_setup_accepts_valid_token_and_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            orchestrator.runner.run = mock.MagicMock(
                return_value=mock.MagicMock(
                    stdout='{"ok": true, "result": {"username": "my_test_bot"}}',
                    stderr="",
                )
            )

            state = self._base_state()
            state.telegram_bot_token_replace = True
            state.telegram_bot_token_input = "123456:[REDACTED]"
            state.telegram_allowlist_ids = "12345,-100987654321"

            status = orchestrator.validate_telegram_setup(state)

            self.assertIn("Telegram token valid", status)
            self.assertIn("allowlist format valid", status)

    def test_validate_telegram_setup_rejects_invalid_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            state = self._base_state()
            state.telegram_allowlist_ids = "bad"

            with self.assertRaises(ConfigureServiceError):
                orchestrator.validate_telegram_setup(state)

    def test_validate_telegram_setup_rejects_invalid_token_with_clean_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            orchestrator.runner.run = mock.MagicMock(
                side_effect=ConfigureServiceError("command failed: curl ...")
            )

            state = self._base_state()
            state.telegram_bot_token_replace = True
            state.telegram_bot_token_input = "asdasdasdasd"

            with self.assertRaises(ConfigureServiceError) as ctx:
                orchestrator.validate_telegram_setup(state)

            self.assertEqual(str(ctx.exception), "Invalid Telegram bot token.")

    def test_validate_hermes_api_key_setup_calls_provider_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            orchestrator.hermes.validate_api_key = mock.MagicMock(
                return_value="Hermes API key valid for openai-codex."
            )
            state = self._base_state()
            state.hermes_auth_method = "api_key"
            state.hermes_provider = "openai-codex"
            state.hermes_api_key_input = "[REDACTED]"

            status = orchestrator.validate_hermes_api_key_setup(state)

            self.assertIn("Hermes API key valid", status)
            orchestrator.hermes.validate_api_key.assert_called_once_with(
                "openai-codex", "[REDACTED]"
            )

    def test_persist_hermes_step_uses_bundled_release_tag_for_bundled_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            orchestrator.hermes.bundled_version = mock.MagicMock(return_value="0.10.0")
            orchestrator.hermes.bundled_release_tag = mock.MagicMock(return_value="v2026.4.16")
            orchestrator.hermes.clear_auth_artifact = mock.MagicMock()

            state = self._base_state()
            state.hermes_agent_version = "0.10.0"
            state.hermes_auth_method = "api_key"
            state.hermes_api_key_input = "new-key"

            orchestrator.persist_hermes_step(state)

            self.assertEqual(state.hermes_agent_release_tag, "v2026.4.16")
            self.assertEqual(orchestrator.env.get("HERMES_AGENT_RELEASE_TAG"), "v2026.4.16")

    def test_validate_hermes_api_key_setup_raises_when_no_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(pathlib.Path(tmp))
            orchestrator.env.set("HERMES_API_KEY", "")
            state = self._base_state()
            state.hermes_auth_method = "api_key"
            state.hermes_api_key_input = ""

            with self.assertRaises(ConfigureServiceError):
                orchestrator.validate_hermes_api_key_setup(state)

    def test_persist_steps_stage_values_without_writing_env_until_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".env.example").write_text(
                "TF_VAR_cloud_provider=hetzner\n"
                "TF_VAR_server_image=debian-13\n"
                "HERMES_API_KEY=old-key\n"
                "TELEGRAM_BOT_TOKEN=existing-telegram\n"
            )
            (root / ".env").write_text(
                "TF_VAR_cloud_provider=hetzner\n"
                "TF_VAR_server_image=debian-13\n"
                "HERMES_API_KEY=old-key\n"
                "TELEGRAM_BOT_TOKEN=existing-telegram\n"
            )
            orchestrator = ConfigureOrchestrator(root)
            orchestrator.ensure_ssh_key_material = mock.MagicMock(return_value=("/tmp/hermes-test-key", "ssh-ed25519 AAAA test"))
            orchestrator.ensure_repo_ssh_alias = mock.MagicMock(return_value=True)
            orchestrator.remove_repo_ssh_alias = mock.MagicMock(return_value=True)
            orchestrator.hermes.clear_auth_artifact = mock.MagicMock()
            orchestrator.telegram_token_present = mock.MagicMock(return_value=True)

            state = self._base_state()
            state.provider = "linode"
            state.server_image = "linode/debian13"
            state.hermes_auth_method = "api_key"
            state.hermes_api_key_input = "new-key"
            state.add_ssh_alias = False

            orchestrator.persist_cloud_step(state)
            orchestrator.persist_hermes_step(state)

            self.assertEqual(orchestrator.env.get("TF_VAR_cloud_provider"), "linode")
            self.assertEqual(orchestrator.env.get("HERMES_API_KEY"), "new-key")

            env_before_apply = (root / ".env").read_text()
            self.assertIn("TF_VAR_cloud_provider=hetzner", env_before_apply)
            self.assertIn("HERMES_API_KEY=old-key", env_before_apply)

            orchestrator.apply(state)

            env_after_apply = (root / ".env").read_text()
            self.assertIn("TF_VAR_cloud_provider=linode", env_after_apply)
            self.assertIn("TF_VAR_server_image=linode/debian13", env_after_apply)
            self.assertIn("HERMES_API_KEY=new-key", env_after_apply)

    def test_validate_hermes_api_key_prefers_staged_value_over_original_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".env.example").write_text("HERMES_API_KEY=old-key\n")
            (root / ".env").write_text("HERMES_API_KEY=old-key\n")
            orchestrator = ConfigureOrchestrator(root)
            orchestrator.hermes.validate_api_key = mock.MagicMock(
                return_value="Hermes API key valid for openai-codex."
            )

            state = self._base_state()
            state.hermes_auth_method = "api_key"
            state.hermes_provider = "openai-codex"
            state.hermes_api_key_input = "new-staged-key"

            orchestrator.persist_hermes_step(state)

            state.hermes_api_key_input = ""
            status = orchestrator.validate_hermes_api_key_setup(state)

            self.assertIn("Hermes API key valid", status)
            orchestrator.hermes.validate_api_key.assert_called_once_with(
                "openai-codex", "new-staged-key"
            )
            self.assertIn("HERMES_API_KEY=old-key", (root / ".env").read_text())

    def test_existing_auth_kept_when_provider_same_even_if_model_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".env.example").write_text("HERMES_API_KEY=existing-key\n")
            (root / ".env").write_text("HERMES_API_KEY=existing-key\n")
            orchestrator = ConfigureOrchestrator(root)

            state = self._base_state()
            state.hermes_provider = "openai-codex"
            state.hermes_model = "gpt-5.4"
            state.original_values = {
                "TF_VAR_hermes_provider": "openai-codex",
                "TF_VAR_hermes_model": "gpt-5.4-mini",
            }

            method = orchestrator.hermes_existing_auth_method_for_combo(state)

            self.assertEqual(method, "api_key")

    def test_existing_auth_cleared_when_provider_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".env.example").write_text("HERMES_API_KEY=existing-key\n")
            (root / ".env").write_text("HERMES_API_KEY=existing-key\n")
            orchestrator = ConfigureOrchestrator(root)

            state = self._base_state()
            state.hermes_provider = "anthropic"
            state.hermes_model = "claude-sonnet-4"
            state.original_values = {
                "TF_VAR_hermes_provider": "openai-codex",
                "TF_VAR_hermes_model": "gpt-5.4-mini",
            }

            method = orchestrator.hermes_existing_auth_method_for_combo(state)

            self.assertEqual(method, "")

    def test_linode_location_options_fail_when_profile_auth_fails(self) -> None:
        runner = self._ScriptedRunner(
            [ConfigureServiceError("command failed: linode-cli profile view")]
        )
        service = ProviderService(runner)

        with mock.patch.object(
            ProviderService, "_require_binary", return_value=None
        ):
            with self.assertRaises(ConfigureServiceError) as ctx:
                service.location_options("linode", "bad-token")

        self.assertIn("Linode token validation failed", str(ctx.exception))
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][:3], ["linode-cli", "profile", "view"])

    def test_linode_location_options_validate_profile_before_regions(self) -> None:
        runner = self._ScriptedRunner(
            [
                CommandResult(stdout='{"username":"test"}', stderr=""),
                CommandResult(
                    stdout='[{"country":"us","label":"Newark, NJ","id":"us-east"}]',
                    stderr="",
                ),
            ]
        )
        service = ProviderService(runner)

        with mock.patch.object(
            ProviderService, "_require_binary", return_value=None
        ):
            rows = service.location_options("linode", "good-token")

        self.assertEqual(rows[0].value, "us-east")
        self.assertEqual(runner.calls[0][:3], ["linode-cli", "profile", "view"])
        self.assertEqual(runner.calls[1][:3], ["linode-cli", "regions", "list"])

    def test_ensure_repo_ssh_alias_upserts_existing_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "repo"
            home = pathlib.Path(tmp) / "home"
            root.mkdir(parents=True, exist_ok=True)
            home.mkdir(parents=True, exist_ok=True)
            (root / ".env.example").write_text("HERMES_API_KEY=\n")
            (root / ".env").write_text("HERMES_API_KEY=\n")
            orchestrator = ConfigureOrchestrator(root)

            repo_ssh = root / ".ssh"
            repo_ssh.mkdir(parents=True, exist_ok=True)
            repo_cfg = repo_ssh / "config"
            repo_cfg.write_text(
                "Host other\n"
                "  HostName keep.example.com\n\n"
                "Host hermes-vps\n"
                "  HostName old.example.com\n"
                "  User old\n"
                "  Port 2222\n"
                "  IdentityFile /tmp/old\n"
                "  IdentitiesOnly yes\n"
            )
            home_ssh = home / ".ssh"
            home_ssh.mkdir(parents=True, exist_ok=True)
            (home_ssh / "config").write_text("Host keep\n  HostName keep\n")

            with mock.patch("pathlib.Path.home", return_value=home):
                changed = orchestrator.ensure_repo_ssh_alias(
                    alias_user="opsadmin",
                    alias_key_path="/tmp/new-key",
                    alias_port="22",
                    selected_hostname="prod.example.com",
                )

            self.assertTrue(changed)
            repo_text = repo_cfg.read_text()
            self.assertEqual(repo_text.count("Host hermes-vps\n"), 1)
            self.assertIn("Host other\n", repo_text)
            self.assertIn("HostName prod.example.com", repo_text)
            self.assertIn("User opsadmin", repo_text)
            self.assertIn("IdentityFile /tmp/new-key", repo_text)

            home_text = (home_ssh / "config").read_text()
            include_line = f"Include {repo_cfg}"
            self.assertEqual(home_text.count(include_line), 1)

    def test_remove_repo_ssh_alias_removes_include_and_alias_block_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "repo"
            home = pathlib.Path(tmp) / "home"
            root.mkdir(parents=True, exist_ok=True)
            home.mkdir(parents=True, exist_ok=True)
            (root / ".env.example").write_text("HERMES_API_KEY=\n")
            (root / ".env").write_text("HERMES_API_KEY=\n")
            orchestrator = ConfigureOrchestrator(root)

            repo_ssh = root / ".ssh"
            repo_ssh.mkdir(parents=True, exist_ok=True)
            repo_cfg = repo_ssh / "config"
            repo_cfg.write_text(
                "Host keep\n"
                "  HostName keep.example.com\n\n"
                "Host hermes-vps\n"
                "  HostName remove.example.com\n"
                "  User opsadmin\n"
                "  Port 22\n"
                "  IdentityFile /tmp/key\n"
                "  IdentitiesOnly yes\n"
            )

            home_ssh = home / ".ssh"
            home_ssh.mkdir(parents=True, exist_ok=True)
            include_line = f"Include {repo_cfg}"
            (home_ssh / "config").write_text(
                "Host local\n"
                "  HostName localhost\n"
                f"{include_line}\n"
            )

            with mock.patch("pathlib.Path.home", return_value=home):
                changed = orchestrator.remove_repo_ssh_alias()

            self.assertTrue(changed)
            repo_text = repo_cfg.read_text()
            self.assertIn("Host keep\n", repo_text)
            self.assertNotIn("Host hermes-vps\n", repo_text)

            home_text = (home_ssh / "config").read_text()
            self.assertIn("Host local\n", home_text)
            self.assertNotIn(include_line, home_text)


if __name__ == "__main__":
    unittest.main()
