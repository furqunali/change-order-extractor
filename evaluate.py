"""
Evaluate the pipeline against hand-labelled ground truth.

  python evaluate.py --provider gemini              # run extraction, then score
  python evaluate.py --results eval/results.json    # re-score a saved run (no API calls)

Writes eval/results.json (raw pipeline output) and eval/REPORT.md.

Metrics
  field accuracy   - per field and overall, against samples/ground_truth.json
  validation       - did the validator pass the good docs and catch the planted error?
  calibration      - accuracy of high- vs low-confidence fields (is confidence meaningful?)
  review routing   - share of wrong fields that the pipeline sent to human review
"""

import argparse
import difflib
import json
import re
import sys
from datetime import date
from pathlib import Path

from co_extractor import (Extractor, collect_paths, flag_duplicates, load_document,
                          normalize, validate_extraction)
from co_extractor.providers import DEFAULT_MODELS

ROOT = Path(__file__).parent
TRUTH_FILE = ROOT / "samples" / "ground_truth.json"
EVAL_DIR = ROOT / "eval"
HIGH_CONF = 0.9


def _tokens(s) -> list:
    return re.sub(r"[^a-z0-9 ]", " ", str(s).lower()).split()


def _co_key(s) -> str:
    key = re.sub(r"[^a-z0-9]", "", str(s).lower())
    return key.removeprefix("co").lstrip("0")


def match(field: str, pred, truth) -> bool:
    """Field-aware comparison: exact for numbers/dates, tolerant for names."""
    if isinstance(truth, list):
        return any(match(field, pred, t) for t in truth)
    if truth is None or pred is None:
        return truth is None and pred is None
    if field.startswith("cost_breakdown.") or field == "schedule_impact_days":
        return abs(float(pred) - float(truth)) < 0.01
    if field in ("date_issued", "new_completion_date", "reason_category"):
        return str(pred) == str(truth)
    if field == "change_order_number":
        return _co_key(pred) == _co_key(truth)
    p, t = _tokens(pred), _tokens(truth)
    if not t:
        return not p
    # names/projects: all expected tokens present, or near-identical strings
    return set(t) <= set(p) or difflib.SequenceMatcher(None, " ".join(p), " ".join(t)).ratio() >= 0.85


def _leaf(data: dict, path: str) -> dict:
    node = data
    for key in path.split("."):
        node = (node or {}).get(key) or {}
    return node


def score(results: list, truth: dict) -> dict:
    by_source = {r["source"]: r for r in results}
    fields, docs, rows = {}, [], []
    for source, expected in truth.items():
        if source.startswith("_"):
            continue
        r = by_source.get(source)
        doc = {"source": source, "tags": expected.get("tags", []), "status": r["status"] if r else "missing"}
        if not r or r["status"] != "success":
            docs.append(doc)
            continue
        data, v = r["data"], r["data"]["_validation"]
        correct = total = 0
        doc["wrong"] = []
        for field, want in expected.items():
            if field in ("tags", "expect_passed", "expect_error"):
                continue
            leaf = _leaf(data, field)
            got, conf = leaf.get("value"), leaf.get("confidence") or 0.0
            ok = match(field, got, want)
            fields.setdefault(field, []).append(ok)
            rows.append({"field": field, "ok": ok, "confidence": conf, "found": got is not None,
                         "flagged": v["needs_review"]})
            correct += ok
            total += 1
            if not ok:
                doc["wrong"].append({"field": field, "expected": want, "got": got, "confidence": conf})
        doc["accuracy"] = correct / total if total else None
        doc["passed"] = v["passed"]
        doc["validation_ok"] = (v["passed"] == expected.get("expect_passed", True)) and (
            not expected.get("expect_error") or any(expected["expect_error"] in e for e in v["errors"]))
        doc["errors"], doc["warnings"] = v["errors"], v["warnings"]
        doc["needs_review"], doc["mode"] = v["needs_review"], r["input_mode"]
        docs.append(doc)

    all_ok = [x["ok"] for x in rows]
    high = [x["ok"] for x in rows if x["found"] and x["confidence"] >= HIGH_CONF]
    low = [x["ok"] for x in rows if x["found"] and x["confidence"] < HIGH_CONF]
    wrong = [x for x in rows if not x["ok"]]
    return {
        "overall_accuracy": sum(all_ok) / len(all_ok) if all_ok else 0,
        "fields_scored": len(all_ok),
        "per_field": {f: sum(v) / len(v) for f, v in sorted(fields.items())},
        "docs": docs,
        "validation_correct": sum(1 for d in docs if d.get("validation_ok")),
        "calibration": {
            f"conf >= {HIGH_CONF}": {"n": len(high), "accuracy": sum(high) / len(high) if high else None},
            f"conf < {HIGH_CONF}": {"n": len(low), "accuracy": sum(low) / len(low) if low else None},
        },
        "wrong_fields": len(wrong),
        "wrong_fields_routed_to_review": sum(1 for x in wrong if x["flagged"]),
    }


def revalidate(results: list) -> list:
    """Re-run normalization + validation on saved outputs (no API calls)."""
    for r in results:
        if r["status"] == "success":
            raw = {k: v for k, v in r["data"].items() if not k.startswith("_")}
            doc = load_document(ROOT / "samples" / r["source"])
            r["data"] = validate_extraction(normalize(raw), source_text=doc.text)
    flag_duplicates(results)
    return results


def _pct(x):
    return "—" if x is None else f"{x:.0%}"


def report(s: dict, provider: str, model: str, revalidated: bool = False) -> str:
    lines = [
        "# Evaluation Report",
        "",
        f"*Generated {date.today().isoformat()} by `python evaluate.py --provider {provider}` "
        f"(model `{model}`) on the {len(s['docs'])} documents in `samples/`"
        + ("; saved model outputs re-validated with the current code (`--results`)" if revalidated else "") + ".*",
        "",
        "## Headline",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Field-level accuracy | **{_pct(s['overall_accuracy'])}** ({s['fields_scored']} labelled fields) |",
        f"| Documents processed successfully | {sum(d['status'] == 'success' for d in s['docs'])}/{len(s['docs'])} |",
        f"| Validation verdict correct (good docs pass, planted error caught) | {s['validation_correct']}/{len(s['docs'])} |",
        f"| Accuracy when confidence ≥ {HIGH_CONF} | {_pct(s['calibration'][f'conf >= {HIGH_CONF}']['accuracy'])} "
        f"(n={s['calibration'][f'conf >= {HIGH_CONF}']['n']}) |",
        f"| Accuracy when confidence < {HIGH_CONF} | {_pct(s['calibration'][f'conf < {HIGH_CONF}']['accuracy'])} "
        f"(n={s['calibration'][f'conf < {HIGH_CONF}']['n']}) |",
        f"| Wrong fields routed to human review | {s['wrong_fields_routed_to_review']}/{s['wrong_fields']} |",
        "",
        "## Per document",
        "",
        "| Document | Input mode | What makes it hard | Field accuracy | Validation | Review? |",
        "|---|---|---|---|---|---|",
    ]
    for d in s["docs"]:
        if d["status"] != "success":
            lines.append(f"| `{d['source']}` | — | {'; '.join(d['tags'])} | {d['status']} | — | — |")
            continue
        verdict = ("✓ passed" if d["passed"] else "✗ " + "; ".join(d["errors"]))
        verdict += "" if d["validation_ok"] else " **(unexpected)**"
        lines.append(f"| `{d['source']}` | {d['mode']} | {'; '.join(d['tags'])} | {_pct(d['accuracy'])} "
                     f"| {verdict} | {'yes' if d['needs_review'] else 'no'} |")
    lines += ["", "## Per field", "", "| Field | Accuracy |", "|---|---|"]
    lines += [f"| `{f}` | {_pct(a)} |" for f, a in s["per_field"].items()]
    misses = [(d["source"], w) for d in s["docs"] for w in d.get("wrong", [])]
    lines += ["", "## Every miss", ""]
    if misses:
        lines += ["| Document | Field | Expected | Got | Confidence |", "|---|---|---|---|---|"]
        lines += [f"| `{src}` | `{w['field']}` | {w['expected']} | {w['got']} | {w['confidence']} |" for src, w in misses]
    else:
        lines.append("None — every labelled field matched.")
    return "\n".join(lines) + "\n"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=sorted(DEFAULT_MODELS), default="claude")
    ap.add_argument("--model")
    ap.add_argument("--results", help="score an existing results.json instead of calling the API")
    args = ap.parse_args()

    truth = json.loads(TRUTH_FILE.read_text(encoding="utf-8"))
    EVAL_DIR.mkdir(exist_ok=True)
    if args.results:
        # Re-apply the CURRENT schema + validation code to the saved model outputs
        results = revalidate(json.loads(Path(args.results).read_text(encoding="utf-8")))
        provider, model = args.provider, args.model or "(from saved run)"
    else:
        ex = Extractor(args.provider, args.model)
        provider, model = ex.provider, ex.model
        paths = collect_paths([ROOT / "samples"])
        results = ex.run(paths, on_result=lambda r, i, n: print(f"  [{i}/{n}] {r['source']}: {r['status']}"))
    (EVAL_DIR / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    s = score(results, truth)
    (EVAL_DIR / "REPORT.md").write_text(report(s, provider, model, bool(args.results)), encoding="utf-8")
    print(f"\nField accuracy: {s['overall_accuracy']:.1%} over {s['fields_scored']} fields")
    print(f"Validation verdicts correct: {s['validation_correct']}/{len(s['docs'])}")
    print(f"Wrong fields routed to review: {s['wrong_fields_routed_to_review']}/{s['wrong_fields']}")
    print(f"Report: {EVAL_DIR / 'REPORT.md'}")


if __name__ == "__main__":
    main()
