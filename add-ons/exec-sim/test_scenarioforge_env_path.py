import os
import tempfile
import unittest
from unittest.mock import patch

import config
import dashboard
import main


class ScenarioForgeEnvPathTests(unittest.TestCase):
    def test_default_environment_path_is_in_the_project_root(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(config.__file__))))
        self.assertEqual(
            config.SCENARIOFORGE_ENV_PATH,
            os.path.join(project_root, ".scenarioforge", ".scenarioforge.env"),
        )

    def test_loader_reads_the_selected_environment_file(self):
        key = "SCENARIOFORGE_DA_TEST_VALUE"
        old_value = os.environ.get(key)
        try:
            with tempfile.NamedTemporaryFile("w", delete=False) as handle:
                handle.write(f"{key}=loaded-value\n")
                env_path = handle.name
            main.load_scenarioforge_env(env_path)
            self.assertEqual(os.environ[key], "loaded-value")
        finally:
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
            os.unlink(env_path)

    def test_dashboard_uses_configured_environment_path(self):
        with patch.object(config, "SCENARIOFORGE_ENV_PATH", "custom-settings.env"):
            self.assertEqual(
                dashboard._scenarioforge_env_path(),
                os.path.abspath("custom-settings.env"),
            )

    def test_solver_settings_round_trip_through_yaml_with_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = os.path.join(temp_dir, "scenarioforge.env")
            with patch.object(config, "SCENARIOFORGE_ENV_PATH", env_path):
                solver_path = dashboard._write_solver_settings([{
                    "label": "Local Llama",
                    "provider": "ollama",
                    "model_id": "llama3",
                    "url": "http://localhost:11434/v1",
                    "api_key": "",
                    "enforce_ssl": True,
                }])
                self.assertEqual(solver_path, os.path.join(temp_dir, "scenarioforge.solvers.yaml"))
                self.assertEqual(dashboard._load_solver_settings(), [{
                    "label": "Local Llama",
                    "provider": "ollama",
                    "model_id": "llama3",
                    "url": "http://localhost:11434/v1",
                    "api_key": "",
                    "enforce_ssl": True,
                }])
                self.assertEqual(os.stat(solver_path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
