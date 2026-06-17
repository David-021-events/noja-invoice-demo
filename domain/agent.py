"""Node 3 — Agent execution (NOJA §2.3 agentic execution).

A Pydantic AI agent that reads an invoice, checks its PO via a tool, and returns a structured
PAY/HOLD/ESCALATE decision. The agent executes *within* the signed approval policy (node 2) and
under the execution envelope signed by the AI Controls Lead (node 3 composite); it does not
invent policy. The policy parameters are passed in, so the SAME agent serves:

  - the NOJA pipeline, where the tolerance is a signed artifact owned by Head of AP (node 2), and
  - the black-box pipeline, where the identical tolerance is latent natural language in the prompt
    that no named role signed (SRD §3.4).

All model calls route through the record/replay cache (SRD §5.1) keyed on (model id + prompt), so
demos are reproducible. Real calls happen on a cache miss during development.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from llm import cache, client


class AgentDecision(BaseModel):
    """Structured output of the execution agent."""

    decision: Literal["PAY", "HOLD", "ESCALATE"]
    rationale: str = Field(description="Brief reason, referencing the PO check and policy.")


@dataclass(frozen=True)
class PolicyParams:
    """The approval-policy parameters the agent executes under. In NOJA these come from node 2's
    signed artifact; in the black-box they are baked into the latent prompt. Same numbers either
    way (SRD §3.4 — identical policy, one signed and one latent)."""

    tolerance_pct: float = 5.0          # near-match tolerance band (the contested signed judgment)
    escalation_threshold: float = 10000.0  # high-value cases go to the HITL node


def noja_system_prompt(policy: PolicyParams) -> str:
    """Node-3 prompt: the policy is supplied as signed parameters from node 2 and the upstream
    signals come from nodes 1 and 2. The agent executes within them; it does not invent policy."""
    return (
        "You are the execution agent (node 3) in a NOJA invoice-approval network. You are "
        "authorized to execute a signed approval policy (owned by the Head of AP) under a pinned "
        "model version. Apply the policy and the upstream signals; do not invent policy.\n\n"
        "Signed policy parameters (from the approval-policy node):\n"
        f"- Tolerance band: pay only if the total is within {policy.tolerance_pct:.0f}% of the PO's "
        "authorized amount.\n"
        f"- Escalation threshold: ${policy.escalation_threshold:,.0f}.\n\n"
        "You also receive upstream signals:\n"
        "- anomaly: {anomalous, duplicate, reasons} from the Anomaly node.\n"
        "- policy_eval: {po_present, po_active, vendor_match, within_tolerance, exceeds_escalation} "
        "from the Approval-policy node.\n\n"
        "Decision rules, applied in order:\n"
        "1. If anomaly.duplicate is true -> HOLD (suspected duplicate submission).\n"
        "2. Else if anomaly.anomalous is true -> ESCALATE (anomalous pattern needs human review).\n"
        "3. Else if policy_eval.exceeds_escalation is true -> ESCALATE (high value).\n"
        "4. Else if policy_eval says no PO, PO not active, vendor mismatch, or not within tolerance "
        "-> HOLD.\n"
        "5. Else -> PAY.\n"
        "You may call lookup_po to confirm PO details. Return the decision and a brief rationale."
    )


def composite_artifact_bytes(policy: PolicyParams, system_prompt: str, model_id: str) -> str:
    """Node-3 composite artifact (NOJA §4.5): the bytes the AI Controls Lead signs. Bundles the
    policy text, system prompt, tool definitions, the version-pinned model id, and the behavior
    envelope. Re-pinning to a new model is a re-signing event — this is what lapses on the swap."""
    return json.dumps(
        {
            "artifact": "agent-execution-composite",
            "owner_role": "AI Controls Lead",
            "policy_text": (
                f"Pay within {policy.tolerance_pct:.0f}% of an active matching PO; escalate at or "
                f"above ${policy.escalation_threshold:,.0f}; hold otherwise."
            ),
            "system_prompt": system_prompt,
            "tool_definitions": [
                {"name": "lookup_po", "signature": "lookup_po(po_number: str) -> dict"}
            ],
            "model_id": model_id,  # version-pinned execution identity (the lapse axis)
            "behavior_envelope": {
                "coverage": [
                    "clean match", "near match", "over tolerance", "no PO", "duplicate",
                    "closed PO", "high-value escalation", "anomaly",
                ],
                "lockfile": "requirements.txt",  # environmental scope condition (§4.3/§5.1)
                "note": "eval suite green under this pinned model id",
            },
        },
        indent=2,
        sort_keys=True,
    )


def make_execution_fns(*, pos: list[dict], policy: PolicyParams, system_prompt: str, model: str):
    """Build node-3's (predict, judge, execute) functions for a JudgmentNode.

    - prediction : assemble the execution context (does not prescribe action, NOJA §2.1).
    - judgment   : node 3's real judgment is the OPERATIONAL AUTHORIZATION (§3.1) — the standing
                   attestation that this composite is authorized to execute under the pinned model.
                   (When the signature has lapsed the node never reaches here; the fallback runs.)
    - execution  : run the Pydantic AI agent (the agentic executor) through the cache.
    """
    bare_model = client.bare_id(model)

    def predict(inp: dict) -> dict:
        # Records which pinned model assessed this invoice (the audit cares about this).
        return {"assessed_under_model_id": bare_model}

    def judge(prediction: dict, _inp: dict) -> dict:
        return {"authorized": True, "judgment_type": "operational/execution-envelope authorization",
                "model_id": prediction["assessed_under_model_id"]}

    def execute(_decision: dict, inp: dict) -> dict:
        invoice = inp["invoice"]
        signals = {"anomaly": inp.get("anomaly"), "policy_eval": inp.get("policy_eval")}
        agent_decision, cached = decide(
            invoice=invoice, pos=pos, policy=policy,
            system_prompt=system_prompt, model=model, extra_signals=signals,
        )
        return {
            "invoice": invoice,
            "decision": agent_decision.decision,
            "rationale": agent_decision.rationale,
            "cached": cached,
        }

    return predict, judge, execute


def safe_mode_execution(_prediction: dict, inp: dict) -> dict:
    """Pre-signed safe-mode behavior when the node-3 composite has lapsed (§4.3). Hold for review;
    crucially, no PAY (no money movement) until a human re-authorizes."""
    return {
        "invoice": inp["invoice"],
        "decision": "HOLD",
        "rationale": "safe-mode: composite signature lapsed (model version unauthorized); "
                     "holding for human re-authorization.",
        "cached": False,
    }


def blackbox_system_prompt(policy: PolicyParams) -> str:
    """Black-box prompt: the SAME policy as the NOJA nodes, but as latent natural language that no
    named role signed, scoped, or can be held accountable for (§3.4). This is the crux of the
    latent-policy contrast — identical behavior, one signed and one buried in a prompt. The
    required line ("within 5% of an approved PO may be paid unless anomalous") appears verbatim."""
    return (
        "You are an autonomous accounts-payable agent. For each invoice decide PAY, HOLD, or "
        "ESCALATE, observing, interpreting, deciding, and acting in one loop.\n"
        f"Invoices within {policy.tolerance_pct:.0f}% of an approved PO may be paid unless anomalous. "
        f"Escalate anything at or above ${policy.escalation_threshold:,.0f} to a human. "
        "Hold anything with no PO, a non-active PO (e.g. closed), a vendor mismatch, or an amount "
        "over tolerance. Hold suspected duplicate submissions — the same vendor and amount as an "
        "invoice you have already processed (see the context provided). Escalate invoices with an "
        "anomalous line-item pattern, such as a large unexplained 'miscellaneous' or 'adjustment' "
        "charge. Use the lookup_po tool to check the PO. Return a decision and a brief rationale."
    )


def _build_agent(model: str, system_prompt: str, pos: list[dict]) -> Agent:
    agent = Agent(model, output_type=AgentDecision, system_prompt=system_prompt)

    @agent.tool_plain
    def lookup_po(po_number: str) -> dict:
        """Look up a purchase order by number. Returns vendor, authorized_amount, status."""
        for po in pos:
            if po.get("po_number") == po_number:
                return po
        return {"error": "not_found", "po_number": po_number}

    return agent


def decide(
    *,
    invoice: dict,
    pos: list[dict],
    policy: PolicyParams,
    system_prompt: str,
    model: str,
    extra_signals: dict | None = None,
    signals_label: str = "Upstream signals",
) -> tuple[AgentDecision, bool]:
    """Run the execution agent on one invoice through the record/replay cache.

    `extra_signals` carries upstream node outputs verbatim — the anomaly verdict and the policy
    evaluation dicts, e.g. {"anomaly": {...}, "policy_eval": {...}} — so node 3 can act on what
    nodes 1/2 produced (this is how the network edges feed forward). Note the whole dicts are
    folded into the cache key, so a change to an upstream output shape invalidates cached replays.
    Returns (decision, was_cached).
    """
    model_id = client.bare_id(model)
    signals = extra_signals or {}

    # The cache key must capture everything that determines the answer.
    cache_payload = json.dumps(
        {"system": system_prompt, "invoice": invoice, "pos": pos, "signals": signals},
        sort_keys=True,
    )

    user_message = "Decide this invoice:\n" + json.dumps(invoice, indent=2)
    if signals:
        user_message += f"\n\n{signals_label}:\n" + json.dumps(signals, indent=2)

    def _real_call() -> dict:
        agent = _build_agent(model, system_prompt, pos)
        result = agent.run_sync(user_message)
        return result.output.model_dump()

    response, was_cached = cache.cached_call(model_id, cache_payload, _real_call)
    return AgentDecision(**response), was_cached
