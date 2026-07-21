import unittest

import config
from main import OLLAMA_OPENAI_BASE_URL, solver_config


class CliProviderConfigTests(unittest.TestCase):
    def test_vllm_default_is_local_not_a_private_remote_host(self):
        self.assertEqual(config.VLLM_BASE_URL, "http://localhost:8000/v1")

    def test_ollama_defaults_to_its_openai_compatible_endpoint(self):
        cfg = solver_config("ollama", "llama3", "ignored", "Llama")

        self.assertEqual(cfg["url"], OLLAMA_OPENAI_BASE_URL)
        self.assertEqual(cfg["api_key"], "")
        self.assertTrue(cfg["enforce_ssl"])

    def test_openai_compatible_requires_an_endpoint(self):
        with self.assertRaisesRegex(ValueError, "solver-url"):
            solver_config("openai-compatible", "my-model", "key", "My model")

    def test_openai_compatible_preserves_endpoint_and_tls_choice(self):
        cfg = solver_config(
            "openai-compatible", "my-model", "key", "My model",
            "https://gateway.example/v1", enforce_ssl=False,
        )

        self.assertEqual(cfg["url"], "https://gateway.example/v1")
        self.assertEqual(cfg["api_key"], "key")
        self.assertFalse(cfg["enforce_ssl"])


if __name__ == "__main__":
    unittest.main()
