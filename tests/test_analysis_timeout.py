import sys
import types

import pytest


def test_analysis_chat_request_uses_extended_default_timeout(monkeypatch):
    import app

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        return FakeResponse()

    monkeypatch.delenv("MCP_ANALYSIS_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("MCP_ANALYSIS_TIMEOUT", raising=False)
    monkeypatch.setattr(app.requests, "post", fake_post)

    app._analysis_chat_request(
        "openai",
        "http://provider.test/v1",
        "token",
        "model-a",
        [{"role": "user", "content": "Analyze this."}],
    )

    assert captured["url"] == "http://provider.test/v1/chat/completions"
    assert captured["timeout"] == app._DEFAULT_ANALYSIS_TIMEOUT_SECONDS


def test_analysis_chat_request_honors_timeout_env(monkeypatch):
    import app

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return FakeResponse()

    monkeypatch.setenv("MCP_ANALYSIS_TIMEOUT_SECONDS", "900")
    monkeypatch.setattr(app.requests, "post", fake_post)

    app._analysis_chat_request(
        "litellm",
        "http://provider.test",
        None,
        "model-a",
        [{"role": "user", "content": "Analyze this."}],
    )

    assert captured["timeout"] == 900


def test_analysis_chat_request_reports_actionable_timeout(monkeypatch):
    import app

    def fake_post(url, **kwargs):
        raise app.requests.exceptions.ReadTimeout("Read timeout: 120")

    monkeypatch.delenv("MCP_ANALYSIS_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("MCP_ANALYSIS_TIMEOUT", raising=False)
    monkeypatch.setattr(app.requests, "post", fake_post)

    with pytest.raises(TimeoutError, match="Analysis model request timed out after 600 seconds"):
        app._analysis_chat_request(
            "openai",
            "http://provider.test",
            None,
            "model-a",
            [{"role": "user", "content": "Analyze this."}],
        )


def test_analysis_chat_request_passes_timeout_to_ollama_client(monkeypatch):
    import app

    captured = {}

    class FakeOllamaClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def chat(self, **kwargs):
            return {"message": {"content": "ok"}}

    fake_ollama = types.SimpleNamespace(Client=FakeOllamaClient)
    monkeypatch.setitem(sys.modules, "ollama", fake_ollama)
    monkeypatch.setenv("MCP_ANALYSIS_TIMEOUT_SECONDS", "750")

    app._analysis_chat_request(
        "ollama_direct",
        "http://localhost:11434",
        None,
        "model-a",
        [{"role": "user", "content": "Analyze this."}],
        ssl_verify=False,
    )

    assert captured["host"] == "http://localhost:11434"
    assert captured["timeout"] == 750
    assert captured["verify"] is False
