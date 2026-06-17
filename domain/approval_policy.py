"""Node 2 — Approval policy (NOJA §2: design-time judgment; quantitative + tolerance).

Signed artifact: the approval policy. **The tolerance band lives here** — this is the latent-policy
contrast: on the NOJA side the tolerance is a signed artifact owned by a named role (Head of AP);
on the black-box side the identical tolerance is buried in a prompt nobody signed (SRD §3.4).

Its execution output (the deterministic policy evaluation) becomes node 3's prediction input.
"""

from __future__ import annotations

import json

from domain.agent import PolicyParams

ROLE = "Head of AP"
NODE = "approval_policy"
ARTIFACT_ID = "approval-policy"

# The single source of the policy numbers, shared by both pipelines (identical policy, §3.4).
POLICY = PolicyParams(tolerance_pct=5.0, escalation_threshold=10000.0)


def artifact_bytes() -> str:
    """The signed bytes of the approval policy (the tolerance band is the contested judgment)."""
    return json.dumps(
        {
            "artifact": "approval-policy",
            "owner_role": ROLE,
            "tolerance_pct": POLICY.tolerance_pct,
            "escalation_threshold": POLICY.escalation_threshold,
            "statement": (
                f"An invoice may be paid if its total is within {POLICY.tolerance_pct:.0f}% of the "
                "referenced PO's authorized amount, the PO is active, and the vendor matches. "
                f"Invoices at or above ${POLICY.escalation_threshold:,.0f} escalate to a human."
            ),
        },
        indent=2,
        sort_keys=True,
    )


def make_fns(pos: list[dict]):
    """Build (predict, judge, execute) closed over the purchase-order set."""

    def predict(inp: dict) -> dict:
        """inp = node-1 output {'invoice', 'anomaly'}. Compute the PO-match facts."""
        inv = inp["invoice"]
        po = next((p for p in pos if p.get("po_number") == inv.get("po_number")), None)
        po_present = po is not None
        po_active = bool(po) and po.get("status") == "active"
        vendor_match = bool(po) and po.get("vendor") == inv["vendor"]
        within_tolerance = False
        if po:
            auth = po.get("authorized_amount")
            if auth is None:
                within_tolerance = False  # malformed PO: no authorized amount to compare against
            elif auth == 0:
                within_tolerance = inv["total_amount"] == 0  # only a $0 invoice matches a $0 PO
            else:
                diff_pct = abs(inv["total_amount"] - auth) / auth * 100.0
                within_tolerance = diff_pct <= POLICY.tolerance_pct
        return {
            "po_present": po_present,
            "po_active": po_active,
            "vendor_match": vendor_match,
            "within_tolerance": within_tolerance,
        }

    def judge(prediction: dict, inp: dict) -> dict:
        """Apply the signed policy to produce the deterministic policy evaluation."""
        inv = inp["invoice"]
        return {
            **prediction,
            "exceeds_escalation": inv["total_amount"] >= POLICY.escalation_threshold,
            "tolerance_pct": POLICY.tolerance_pct,
            "escalation_threshold": POLICY.escalation_threshold,
        }

    def execute(decision: dict, inp: dict) -> dict:
        """Forward invoice + anomaly verdict + policy evaluation to node 3."""
        return {
            "invoice": inp["invoice"],
            "anomaly": inp["anomaly"],
            "policy_eval": decision,
        }

    return predict, judge, execute
