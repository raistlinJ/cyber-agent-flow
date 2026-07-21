import unittest
from unittest.mock import patch

import dashboard


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"data": [{"id": "claude-test-a"}, {"id": "claude-test-b"}]}


class _Client:
    def __init__(self):
        self.url = None
        self.headers = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get(self, url, headers):
        self.url = url
        self.headers = headers
        return _Response()


class AnthropicProviderTests(unittest.TestCase):
    def test_fetches_native_anthropic_model_list_with_required_headers(self):
        client = _Client()
        with patch("httpx.Client", return_value=client):
            models = dashboard._fetch_anthropic_models("sk-ant-test")

        self.assertEqual(models, ["claude-test-a", "claude-test-b"])
        self.assertEqual(client.url, "https://api.anthropic.com/v1/models")
        self.assertEqual(client.headers["x-api-key"], "sk-ant-test")
        self.assertEqual(client.headers["anthropic-version"], "2023-06-01")

    def test_rejects_missing_anthropic_api_key(self):
        with self.assertRaisesRegex(ValueError, "API key"):
            dashboard._fetch_anthropic_models("")


if __name__ == "__main__":
    unittest.main()
