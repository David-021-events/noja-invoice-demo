"""Node 4 — Escalation HITL (NOJA §2.2 human-in-the-loop; per-instance qualitative judgment).

Signed artifact: a per-instance signed decision (one per escalated invoice). Accountable role:
AP Manager. Unlike nodes 1-3 (one standing signature each), node 4 produces a fresh signed
artifact for each instance it decides — so the run loop signs these per invoice (NOJA §2.2:
"a live instance routed to a named human ... whose signature attaches to the instance").

For this automated demo the AP Manager's per-instance decisions are pre-authored data below. They
are real human signatures in the normal run (onboarding and HITL signatures are expected, SRD §9).
"""

from __future__ import annotations

import json

ROLE = "AP Manager"
NODE = "escalation"

# Pre-authored AP Manager resolutions, keyed by invoice id. Each is signed per-instance.
RESOLUTIONS: dict[str, dict] = {
    "INV-007": {
        "resolution": "approved",
        "note": "High value but a clean match to an active PO; approved by AP Manager.",
    },
    "INV-008": {
        "resolution": "rejected",
        "note": "Unexplained large 'miscellaneous' line; returned to vendor for itemisation.",
    },
}


def resolve(invoice_id: str) -> dict:
    """The AP Manager's per-instance decision for an escalated invoice."""
    return RESOLUTIONS.get(
        invoice_id,
        {"resolution": "hold_for_review", "note": "No pre-authored decision; held for manual review."},
    )


def artifact_bytes(invoice_id: str, decision: dict, upstream_event_id: str) -> str:
    """The signed bytes of a single per-instance HITL decision."""
    return json.dumps(
        {
            "artifact": "hitl-decision",
            "owner_role": ROLE,
            "invoice_id": invoice_id,
            "decision": decision["resolution"],
            "note": decision["note"],
            "decided_on_upstream_event": upstream_event_id,
        },
        indent=2,
        sort_keys=True,
    )
