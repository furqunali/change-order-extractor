"""End-to-end pipeline with the LLM mocked out (no network, no key)."""
import io
import json
from pathlib import Path

import pytest

from co_extractor import Extractor, pipeline, providers

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

GOOD = {
    "change_order_number": {"value": "118", "confidence": 0.95},
    "project_name": {"value": "Oak Hollow Retail Center", "confidence": 0.95},
    "date_issued": {"value": "2025-01-21", "confidence": 0.95},
    "contractor_name": {"value": "Keystone Commercial Builders", "confidence": 0.95},
    "cost_breakdown": {"labor": {"value": 4000, "confidence": 0.9}, "materials": {"value": 6000, "confidence": 0.9},
                       "overhead_markup": {"value": 1000, "confidence": 0.9}, "total": {"value": 13500, "confidence": 0.9}},
}


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def install(replies):
        def fake(messages, model):
            calls.append([dict(m) for m in messages])
            return replies[len(calls) - 1]
        monkeypatch.setitem(pipeline.PROVIDERS, "claude", fake)
        return calls
    return install


def test_end_to_end_catches_planted_math_error(fake_llm):
    fake_llm([json.dumps(GOOD)])
    [r] = Extractor("claude").run([SAMPLES / "co_118_math_error.txt"])
    v = r["data"]["_validation"]
    assert r["status"] == "success" and r["input_mode"] == "text"
    assert not v["passed"] and "Cost math mismatch" in v["errors"][0]
    assert v["grounded"] is True


def test_invalid_json_triggers_one_corrective_reprompt(fake_llm):
    calls = fake_llm(["here you go: {broken", "```json\n" + json.dumps(GOOD) + "\n```"])
    [r] = Extractor("claude").run([SAMPLES / "co_118_math_error.txt"])
    assert r["status"] == "success" and len(calls) == 2
    assert [m["role"] for m in calls[1]] == ["user", "assistant", "user"]


def test_parse_error_after_retries_does_not_stop_batch(fake_llm):
    fake_llm(["nope", "still nope", json.dumps(GOOD)])
    results = Extractor("claude").run([SAMPLES / "co_118_math_error.txt",
                                       SAMPLES / "co_047_riverside_sewer_reroute.txt"])
    assert [r["status"] for r in results] == ["parse_error", "success"]


def test_scanned_pdf_is_sent_as_file_part(fake_llm):
    calls = fake_llm([json.dumps(GOOD)])
    Extractor("claude").run([SAMPLES / "co_031_scanned.pdf"])
    parts = calls[0][0]["content"]
    assert parts[0]["type"] == "file" and parts[0]["mime"] == "application/pdf"


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        Extractor("gpt")


def test_gemini_adapter_request_shape(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append((req, json.loads(req.data)))
        return io.BytesIO(json.dumps({"candidates": [{"content": {"parts": [
            {"text": "thinking...", "thought": True}, {"text": "{}"}]}}]}).encode())

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    out = providers.call_gemini([{"role": "user", "content": [
        {"type": "file", "mime": "application/pdf", "data": "QUJD"},
        {"type": "text", "text": "hi"}]}], "gemini-x")
    req, body = sent[0]
    assert out == "{}"  # thought parts are dropped
    assert req.headers["X-goog-api-key"] == "test-key" and "gemini-x" in req.full_url
    assert body["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "application/pdf"
    assert body["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        providers.call_gemini([{"role": "user", "content": [{"type": "text", "text": "x"}]}], "m")


def test_retry_delay_uses_server_hint():
    assert providers._retry_delay('{"retryDelay": "37s"}', 0) == 38
    assert providers._retry_delay("no hint", 2) == 20
