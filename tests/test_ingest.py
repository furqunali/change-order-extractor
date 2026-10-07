"""Ingestion picks the right path for each file type."""
from pathlib import Path

import pytest

from co_extractor.ingest import collect_paths, load_document

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_text_and_email():
    assert load_document(SAMPLES / "co_118_math_error.txt").mode == "text"
    doc = load_document(SAMPLES / "co_052_email_thread.eml")
    assert doc.mode == "text" and "9,050" in doc.text


def test_digital_pdf_uses_text_layer():
    doc = load_document(SAMPLES / "co_215_digital_form.pdf")
    assert doc.mode == "pdf_text" and "18,849.60" in doc.text


def test_scanned_pdf_goes_to_vision():
    doc = load_document(SAMPLES / "co_031_scanned.pdf")
    assert doc.mode == "pdf_vision" and doc.text is None
    assert doc.mime == "application/pdf" and len(doc.file_b64) > 1000


def test_collect_paths_and_unsupported(tmp_path):
    assert len(collect_paths([SAMPLES])) == 8  # make_samples.py / ground_truth.json skipped
    bad = tmp_path / "co.docx"
    bad.write_text("x")
    with pytest.raises(ValueError):
        load_document(bad)
    with pytest.raises(FileNotFoundError):
        collect_paths([tmp_path / "missing.pdf"])
