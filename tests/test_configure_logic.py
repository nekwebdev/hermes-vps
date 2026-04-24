import pathlib
import tempfile
import unittest

from scripts import configure_logic as logic


class ConfigureLogicTests(unittest.TestCase):
    def _tmp_env(self, content: str) -> pathlib.Path:
        fd, path = tempfile.mkstemp(prefix="configure-logic-", suffix=".env")
        pathlib.Path(path).write_text(content)
        pathlib.Path(path).chmod(0o600)
        return pathlib.Path(path)

    def test_set_env_value_replaces_existing_key_once(self):
        path = self._tmp_env("A=1\nB=2\nA=stale\n")
        logic.set_env_value(path, "A", "42")
        self.assertEqual(path.read_text(), "A=42\nB=2\nA=stale\n")

    def test_set_env_value_appends_missing_key(self):
        path = self._tmp_env("A=1\n")
        logic.set_env_value(path, "B", "2")
        self.assertEqual(path.read_text(), "A=1\nB=2\n")

    def test_get_env_value_returns_empty_when_missing(self):
        path = self._tmp_env("A=1\n")
        self.assertEqual(logic.get_env_value(path, "MISSING"), "")

    def test_server_image_for_provider(self):
        self.assertEqual(logic.server_image_for_provider("linode"), "linode/debian13")
        self.assertEqual(logic.server_image_for_provider("hetzner"), "debian-13")

    def test_semver_validation(self):
        self.assertTrue(logic.is_valid_semver("1.2.3"))
        self.assertTrue(logic.is_valid_semver("1.2.3-rc1"))
        self.assertFalse(logic.is_valid_semver("v1.2.3"))

    def test_release_tag_validation(self):
        self.assertTrue(logic.is_valid_release_tag("v1.2.3"))
        self.assertFalse(logic.is_valid_release_tag("1.2.3"))

    def test_release_tag_for_version(self):
        self.assertEqual(logic.release_tag_for_version("1.2.3"), "v1.2.3")
        self.assertEqual(logic.release_tag_for_version("not-semver"), "")

    def test_telegram_allowlist_validation(self):
        self.assertTrue(logic.is_valid_telegram_allowlist("12345,-100123456"))
        self.assertFalse(logic.is_valid_telegram_allowlist("123,abc"))

    def test_choose_seed_prefers_existing_then_preferred_then_first(self):
        options = ["a", "b", "c"]
        self.assertEqual(logic.choose_seed(options, existing="b", preferred="c"), "b")
        self.assertEqual(logic.choose_seed(options, existing="x", preferred="c"), "c")
        self.assertEqual(logic.choose_seed(options, existing="x", preferred="y"), "a")

    def test_rotate_to_seed(self):
        self.assertEqual(logic.rotate_to_seed(["a", "b", "c"], "b"), ["b", "c", "a"])
        self.assertEqual(logic.rotate_to_seed(["a", "b"], "x"), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
