"""evals/suite.py — the fixed eval suite (SRD §7.1).

A small, intentionally narrow suite of unambiguous cases spanning the documented coverage
categories (clean match, near match, mismatch, no PO, duplicate, high-value escalation). It runs
them against whatever model is currently pinned and returns pass/fail per case plus an aggregate
green/red.

This is NOT a benchmark and must not be presented as one. The point of the demo is *authorization*,
not eval coverage: the suite exists to be green on BOTH the original and the swapped model, so the
green-but-unsigned window is genuinely green (§7.1 honesty requirement). If a case ever fails on
model variance, replace it only with another case in the SAME coverage category — never tune a case
to a result.

Run from the repo root:  python -m evals.suite
"""

from __future__ import annotations

import json
from pathlib import Path

from domain import fixtures
from domain.decision import classify_noja
from llm import client

_CASES = Path(__file__).resolve().parent / "cases.json"


def run_suite(model: str | None = None) -> dict:
    """Run every case under `model` (default: the currently pinned model). Returns a result dict."""
    model = model or client.current_model()
    cases = json.loads(_CASES.read_text())
    invoices = {inv["invoice_id"]: inv for inv in fixtures.invoices()}
    pos = fixtures.purchase_orders()

    results = []
    for case in cases:
        if case["invoice_id"] not in invoices:
            raise KeyError(f"eval case {case['id']!r} references unknown invoice_id "
                           f"{case['invoice_id']!r} (not in fixtures/invoices.json)")
        invoice = invoices[case["invoice_id"]]
        # Build the 'seen' history from referenced fixtures so it can't drift from invoices.json.
        seen = [{"vendor": invoices[i]["vendor"], "total": invoices[i]["total_amount"]}
                for i in case.get("seen_invoice_ids", [])]
        decision, cached = classify_noja(invoice, pos, model, seen=seen)
        results.append({
            "id": case["id"],
            "category": case["category"],
            "invoice_id": case["invoice_id"],
            "expected": case["expected"],
            "got": decision,
            "pass": decision == case["expected"],
            "cached": cached,
        })

    return {
        "model_id": client.bare_id(model),
        "green": all(r["pass"] for r in results),
        "passed": sum(r["pass"] for r in results),
        "total": len(results),
        "results": results,
    }


def print_report(report: dict) -> None:
    print(f"Eval suite — model={report['model_id']}\n" + "=" * 56)
    for r in report["results"]:
        mark = "ok " if r["pass"] else "FAIL"
        src = "cache" if r["cached"] else "live "
        print(f"[{mark}|{src}] {r['id']:<16} {r['category']:<22} "
              f"{r['got']:<9} (expected {r['expected']})")
    print("=" * 56)
    status = "GREEN" if report["green"] else "RED"
    print(f"{status}: {report['passed']}/{report['total']} cases pass under {report['model_id']}")


def main() -> None:
    client.require_api_key()
    print_report(run_suite())


if __name__ == "__main__":
    main()
