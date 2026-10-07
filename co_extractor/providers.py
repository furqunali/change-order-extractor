"""
LLM providers behind one interface.

A conversation is a list of {"role": "user"|"assistant", "content": [part...]}
where a part is {"type": "text", "text": ...} or
{"type": "file", "mime": ..., "data": <base64>}. Each adapter translates that
into its own API format and returns the model's text reply.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_MODELS = {"claude": "claude-opus-5-5", "gemini": "gemini-2.5-flash"}
RETRYABLE_HTTP = {429, 500, 502, 503, 504}

_anthropic_client = None


def call_claude(messages: list, model: str) -> str:
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic  # imported lazily so Gemini-only users don't need a key
        _anthropic_client = anthropic.Anthropic()  # SDK retries 429/5xx itself

    def part(p):
        if p["type"] == "text":
            return {"type": "text", "text": p["text"]}
        kind = "document" if p["mime"] == "application/pdf" else "image"
        return {"type": kind, "source": {"type": "base64", "media_type": p["mime"], "data": p["data"]}}

    response = _anthropic_client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": m["role"], "content": [part(p) for p in m["content"]]} for m in messages],
    )
    return response.content[0].text


def call_gemini(messages: list, model: str, retries: int = 4) -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set (free key: https://aistudio.google.com/apikey)")

    def part(p):
        if p["type"] == "text":
            return {"text": p["text"]}
        return {"inline_data": {"mime_type": p["mime"], "data": p["data"]}}

    body = {
        "contents": [
            {"role": "model" if m["role"] == "assistant" else "user",
             "parts": [part(p) for p in m["content"]]}
            for m in messages
        ],
        # JSON mode; generous budget because thinking tokens count against it
        "generationConfig": {"responseMimeType": "application/json",
                             "maxOutputTokens": 8192, "temperature": 0},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code in RETRYABLE_HTTP and attempt < retries:
                time.sleep(_retry_delay(detail, attempt))  # free tier: back off on rate limits
                continue
            raise RuntimeError(f"Gemini API error {e.code}: {detail[:300]}") from None
    candidate = data["candidates"][0]
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        raise RuntimeError(f"Gemini returned no text (finishReason={candidate.get('finishReason')})")
    return text


def _retry_delay(detail: str, attempt: int) -> float:
    """Use the server's RetryInfo hint ("retryDelay": "37s") when given."""
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', detail)
    return min(float(m.group(1)) + 1, 90) if m else min(2 ** attempt * 5, 60)


PROVIDERS = {"claude": call_claude, "gemini": call_gemini}
