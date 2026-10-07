"""Pipeline: ingest -> LLM extraction -> schema normalization -> validation."""

import json
import re

from .ingest import Document, load_document
from .prompt import build_prompt
from .providers import DEFAULT_MODELS, PROVIDERS
from .schema import normalize
from .validate import flag_duplicates, validate_extraction

MAX_ATTEMPTS = 2  # first try + one corrective re-prompt on invalid JSON


class Extractor:
    def __init__(self, provider: str = "claude", model: str = None):
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider {provider!r}; use one of {sorted(PROVIDERS)}")
        self.provider = provider
        self.model = model or DEFAULT_MODELS[provider]

    def extract(self, doc: Document) -> dict:
        """Return the raw JSON dict from the model for one document."""
        if doc.text is not None:
            content = [{"type": "text", "text": build_prompt(doc.text)}]
        else:
            content = [{"type": "file", "mime": doc.mime, "data": doc.file_b64},
                       {"type": "text", "text": build_prompt()}]
        messages = [{"role": "user", "content": content}]

        for attempt in range(1, MAX_ATTEMPTS + 1):
            raw = strip_fences(PROVIDERS[self.provider](messages, self.model))
            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                if attempt == MAX_ATTEMPTS:
                    raise
                # Fallback re-prompt: show the model its output and the parse error
                messages += [
                    {"role": "assistant", "content": [{"type": "text", "text": raw}]},
                    {"role": "user", "content": [{"type": "text", "text":
                        f"That was not valid JSON ({e}). Return ONLY the corrected JSON object."}]},
                ]

    def process(self, doc: Document) -> dict:
        try:
            data = validate_extraction(normalize(self.extract(doc)), source_text=doc.text)
            return {"source": doc.source, "input_mode": doc.mode, "status": "success", "data": data}
        except json.JSONDecodeError as e:
            return {"source": doc.source, "input_mode": doc.mode, "status": "parse_error", "error": str(e)}
        except Exception as e:  # one bad document must not stop the batch
            return {"source": doc.source, "input_mode": doc.mode, "status": "error", "error": str(e)}

    def run(self, paths, on_result=None) -> list:
        results = []
        for path in paths:
            try:
                doc = load_document(path)
            except Exception as e:
                result = {"source": str(path), "input_mode": None, "status": "error", "error": str(e)}
            else:
                result = self.process(doc)
            results.append(result)
            if on_result:
                on_result(result, len(results), len(paths))
        flag_duplicates(results)
        return results


def strip_fences(text: str) -> str:
    """Remove markdown code fences if the model wraps its JSON in them."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text
