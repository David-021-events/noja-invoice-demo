"""Node 1 — Anomaly (NOJA §2: prediction-dominant; quantitative judgment).

Signed artifact: the anomaly threshold policy. Accountable role: Finance Controls Lead.
Flags duplicate submissions and anomalous line-item patterns. Its execution output (the anomaly
verdict) becomes the prediction input of node 2 (§3: one node's execution feeds the next).
"""

from __future__ import annotations

import json

ROLE = "Finance Controls Lead"
NODE = "anomaly"
ARTIFACT_ID = "threshold-policy"

MISC_LINE_THRESHOLD = 5000.0
_MISC_WORDS = ("miscellaneous", "misc", "adjustment", "sundry")


def artifact_bytes() -> str:
    """The signed bytes of the anomaly threshold policy."""
    return json.dumps(
        {
            "artifact": "anomaly-threshold-policy",
            "owner_role": ROLE,
            "rules": [
                "duplicate: same vendor and total amount as a previously processed invoice",
                f"line-item anomaly: any line described as miscellaneous/adjustment/sundry "
                f"exceeding ${MISC_LINE_THRESHOLD:,.0f}",
            ],
            "misc_line_threshold": MISC_LINE_THRESHOLD,
        },
        indent=2,
        sort_keys=True,
    )


def predict(inp: dict) -> dict:
    """inp = {'invoice': ..., 'seen': [{'vendor','total'}, ...]} (seen = prior invoices this run)."""
    inv = inp["invoice"]
    seen = inp.get("seen", [])
    # .get (not []) so a caller's seen-entry shape can't KeyError mid-run; money compared with a
    # half-cent tolerance rather than exact float equality (880.0 vs 880.00 from differing sources).
    duplicate = any(
        s.get("vendor") == inv["vendor"]
        and abs((s.get("total") or 0.0) - inv["total_amount"]) < 0.005
        for s in seen
    )
    misc_lines = [
        li["description"]
        for li in inv["line_items"]
        if any(w in li["description"].lower() for w in _MISC_WORDS)
        and li["qty"] * li["unit_price"] > MISC_LINE_THRESHOLD
    ]
    return {"duplicate": duplicate, "misc_lines": misc_lines}


def judge(prediction: dict, _inp: dict) -> dict:
    """Apply the signed threshold: anomalous if duplicate or any large unexplained line item."""
    reasons = []
    if prediction["duplicate"]:
        reasons.append("duplicate of a previously processed invoice")
    if prediction["misc_lines"]:
        reasons.append("large unexplained line item(s): " + ", ".join(prediction["misc_lines"]))
    return {
        "anomalous": prediction["duplicate"] or bool(prediction["misc_lines"]),
        "duplicate": prediction["duplicate"],
        "reasons": reasons,
    }


def execute(decision: dict, inp: dict) -> dict:
    """Forward the invoice plus the anomaly verdict to node 2."""
    return {"invoice": inp["invoice"], "anomaly": decision}
