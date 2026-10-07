"""
Change-Order Extraction Pipeline — command-line entry point
Author: Furqan Ali

  python extractor.py                                # every file in samples/
  python extractor.py path/to/co.pdf other_folder/   # your own files / folders
  python extractor.py --provider gemini              # free-tier alternative to Claude
  python extractor.py -o results.json                # choose the output file

Accepts .pdf (digital or scanned), .txt, .md, .eml, .png, .jpg.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from co_extractor import Extractor, collect_paths
from co_extractor.providers import DEFAULT_MODELS


def print_result(r: dict, i: int, n: int) -> None:
    print(f"\n[{i}/{n}] {r['source']}  ({r['input_mode']})")
    if r["status"] != "success":
        print(f"  ERROR ({r['status']}): {r['error']}")
        return
    d, v = r["data"], r["data"]["_validation"]
    total = d["cost_breakdown"]["total"]["value"]
    print(f"  CO Number  : {d['change_order_number']['value']}")
    print(f"  Project    : {d['project_name']['value']}")
    print(f"  Total Cost : {'N/A' if total is None else f'${total:,.2f}'}")
    print(f"  Confidence : {d['overall_confidence']:.0%}  (fields found: {d['field_coverage']:.0%})")
    print(f"  Validation : {'✓ PASSED' if v['passed'] else '✗ FAILED'}"
          f"{'  → needs human review' if v['needs_review'] else ''}")
    for e in v["errors"]:
        print(f"    ✗ {e}")
    for w in v["warnings"]:
        print(f"    ⚠ {w}")
    if v["review_fields"]:
        print(f"    review: {', '.join(v['review_fields'])}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252

    ap = argparse.ArgumentParser(description="Change-order extraction pipeline")
    ap.add_argument("inputs", nargs="*", default=[str(Path(__file__).parent / "samples")],
                    help="files or folders (default: samples/)")
    ap.add_argument("--provider", choices=sorted(DEFAULT_MODELS),
                    default=os.environ.get("CO_EXTRACTOR_PROVIDER", "claude"))
    ap.add_argument("--model", default=os.environ.get("CO_EXTRACTOR_MODEL"),
                    help="override the provider's default model")
    ap.add_argument("-o", "--output", default="change_orders_output.json")
    args = ap.parse_args(argv)

    extractor = Extractor(args.provider, args.model)
    paths = collect_paths(args.inputs)
    print("Change-Order Extraction Pipeline")
    print(f"Provider: {extractor.provider} | Model: {extractor.model} | Documents: {len(paths)}")

    results = extractor.run(paths, on_result=print_result)
    Path(args.output).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = [r for r in results if r["status"] == "success"]
    print(f"\n{'=' * 60}")
    print("PIPELINE COMPLETE")
    print(f"  Processed        : {len(results)}")
    print(f"  Extracted        : {len(ok)}   Errors: {len(results) - len(ok)}")
    print(f"  Validation pass  : {sum(r['data']['_validation']['passed'] for r in ok)}")
    print(f"  Needs review     : {sum(r['data']['_validation']['needs_review'] for r in ok)}")
    print(f"  Output saved to  : {args.output}")
    print("=" * 60)
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
