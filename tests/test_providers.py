"""Offline tests for provider selection and the Gemini adapter (HTTP is mocked)."""
import io
import json

import pytest

import extractor


@pytest.fixture(autouse=True)
def restore_provider():
    saved = (extractor.PROVIDER, extractor.MODEL)
    yield
    extractor.PROVIDER, extractor.MODEL = saved


def test_configure_picks_default_model(monkeypatch):
    monkeypatch.delenv("CO_EXTRACTOR_MODEL", raising=False)
    extractor.configure("gemini")
    assert extractor.MODEL == extractor.DEFAULT_MODELS["gemini"]
    extractor.configure("claude", "custom-model")
    assert extractor.MODEL == "custom-model"


def test_configure_rejects_unknown_provider():
    with pytest.raises(ValueError):
        extractor.configure("gpt")


def test_gemini_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    extractor.configure("gemini")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        extractor._call_gemini([{"role": "user", "content": "hi"}])


def test_gemini_request_and_reprompt(monkeypatch):
    """First reply is broken JSON -> pipeline re-prompts -> second reply parses."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    extractor.configure("gemini")
    replies = ['{"change_order_number": ', '{"change_order_number": {"value": "CO-9", "confidence": 0.9}}']
    sent = []

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data)
        sent.append(body)
        assert req.headers["X-goog-api-key"] == "test-key"
        text = replies[len(sent) - 1]
        return io.BytesIO(json.dumps(
            {"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode())

    monkeypatch.setattr(extractor.urllib.request, "urlopen", fake_urlopen)
    result = extractor.extract_change_order("CO-9 text")

    assert result["change_order_number"]["value"] == "CO-9"
    assert len(sent) == 2
    # The retry carries the model's bad answer back with role "model"
    assert [c["role"] for c in sent[1]["contents"]] == ["user", "model", "user"]
    assert sent[0]["generationConfig"]["responseMimeType"] == "application/json"
