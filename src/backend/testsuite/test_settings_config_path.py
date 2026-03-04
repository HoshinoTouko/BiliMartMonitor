import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


class SettingsConfigPathTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root_config_path = os.path.join(PROJECT_ROOT, "config.yaml")
        self.legacy_config_path = os.path.join(PROJECT_ROOT, "src", "data", "config.yaml")
        os.environ.pop("BSM_CONFIG_PATH", None)

    def tearDown(self) -> None:
        os.environ.pop("BSM_CONFIG_PATH", None)

    def test_defaults_to_root_config_when_present(self) -> None:
        from bsm.settings import _yaml_config_path

        self.assertEqual(_yaml_config_path(), self.root_config_path)

    def test_falls_back_to_legacy_path_when_root_missing(self) -> None:
        from unittest.mock import patch
        from bsm.settings import _yaml_config_path

        with patch("os.path.exists", return_value=False):
            self.assertEqual(_yaml_config_path(), self.legacy_config_path)

    def test_generates_initial_env_and_config_from_examples(self) -> None:
        from unittest.mock import patch
        from bsm import env

        with tempfile.TemporaryDirectory(prefix="bsm-init-config-") as temp_root:
            temp_data_dir = os.path.join(temp_root, "src", "data")
            os.makedirs(temp_data_dir, exist_ok=True)
            env_example_path = os.path.join(temp_root, ".env.example")
            config_example_path = os.path.join(temp_root, "config.yaml.example")
            with open(env_example_path, "w", encoding="utf-8") as f:
                f.write("BSM_DB_BACKEND=sqlite\n")
            with open(config_example_path, "w", encoding="utf-8") as f:
                f.write("scan_mode: latest\n")

            original_flag = env._INITIAL_PROJECT_CONFIG_ENSURED
            env._INITIAL_PROJECT_CONFIG_ENSURED = False
            try:
                with patch("bsm.env.project_root", return_value=temp_root), patch(
                    "bsm.env.data_dir",
                    return_value=temp_data_dir,
                ):
                    env.ensure_initial_project_config()
            finally:
                env._INITIAL_PROJECT_CONFIG_ENSURED = original_flag

            with open(os.path.join(temp_root, ".env"), "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "BSM_DB_BACKEND=sqlite\n")
            with open(os.path.join(temp_root, "config.yaml"), "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "scan_mode: latest\n")

    def test_does_not_generate_initial_pair_when_one_file_already_exists(self) -> None:
        from unittest.mock import patch
        from bsm import env

        with tempfile.TemporaryDirectory(prefix="bsm-init-config-skip-") as temp_root:
            temp_data_dir = os.path.join(temp_root, "src", "data")
            os.makedirs(temp_data_dir, exist_ok=True)
            with open(os.path.join(temp_root, ".env"), "w", encoding="utf-8") as f:
                f.write("BSM_DB_BACKEND=sqlite\n")
            with open(os.path.join(temp_root, ".env.example"), "w", encoding="utf-8") as f:
                f.write("BSM_DB_BACKEND=cloudflare\n")
            with open(os.path.join(temp_root, "config.yaml.example"), "w", encoding="utf-8") as f:
                f.write("scan_mode: continue\n")

            original_flag = env._INITIAL_PROJECT_CONFIG_ENSURED
            env._INITIAL_PROJECT_CONFIG_ENSURED = False
            try:
                with patch("bsm.env.project_root", return_value=temp_root), patch(
                    "bsm.env.data_dir",
                    return_value=temp_data_dir,
                ):
                    env.ensure_initial_project_config()
            finally:
                env._INITIAL_PROJECT_CONFIG_ENSURED = original_flag

            self.assertFalse(os.path.exists(os.path.join(temp_root, "config.yaml")))
