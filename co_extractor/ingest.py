"""
Document ingestion: turn a file into something the LLM can read.

  .txt / .md / .eml         -> plain text
  .pdf with a text layer    -> extracted text (cheap, and lets us run
                               grounding checks against the source)
  .pdf without text layer   -> raw PDF bytes sent to the model's native
  (scanned / photographed)     document/vision input (no local OCR needed)
  .png / .jpg               -> image bytes, same vision path
"""

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SUPPORTED = {".txt", ".md", ".eml", ".pdf", ".png", ".jpg", ".jpeg"}
MIN_CHARS_PER_PAGE = 40  # below this a PDF page is treated as scanned
_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


@dataclass
class Document:
    source: str
    mode: str                       # text | pdf_text | pdf_vision | image_vision
    text: Optional[str] = None      # set for text modes
    file_b64: Optional[str] = None  # set for vision modes
    mime: Optional[str] = None


def load_document(path) -> Document:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type {ext!r} ({path.name})")

    if ext in {".txt", ".md", ".eml"}:
        return Document(path.name, "text", text=path.read_text(encoding="utf-8", errors="replace"))

    if ext in _IMAGE_MIME:
        return Document(path.name, "image_vision", file_b64=_b64(path), mime=_IMAGE_MIME[ext])

    text, pages = _pdf_text(path)
    if pages and len(text.strip()) >= MIN_CHARS_PER_PAGE * pages:
        return Document(path.name, "pdf_text", text=text)
    return Document(path.name, "pdf_vision", file_b64=_b64(path), mime="application/pdf")


def collect_paths(inputs) -> list:
    """Expand files and folders into a sorted list of supported files."""
    paths = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            paths += sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED)
        elif p.exists():
            paths.append(p)
        else:
            raise FileNotFoundError(item)
    return paths


def _pdf_text(path: Path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n\n".join(pages), len(pages)


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")
