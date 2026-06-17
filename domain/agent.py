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

from llm import cache


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
    """Node-3 prompt: the policy is supplied as signed parameters from node 2, not invented here."""
    return (
        "You are the execution agent in an accounts-payable approval network. You apply a "
        "signed approval policy owned by the Head of AP; you do not invent policy.\n\n"
        "Signed policy parameters (from the approval-policy node):\n"
        f"- Tolerance band: an invoice may be paid if its total is within {policy.tolerance_pct:.0f}% "
        "of the referenced PO's authorized amount.\n"
        f"- Escalation threshold: any invoice at or above ${policy.escalation_threshold:,.0f} must be "
        "ESCALATEd to a human regardless of PO match.\n\n"
        "Procedure: look up the referenced PO with the lookup_po tool. Then decide:\n"
        "- ESCALATE if the total is at or above the escalation threshold, or if the invoice is "
        "flagged anomalous.\n"
        "- HOLD if there is no PO, the PO is not active (e.g. closed), the vendor does not match, "
        "or the total exceeds the tolerance band.\n"
        "- PAY only for an active, matching PO within the tolerance band and below the escalation "
        "threshold.\n"
        "Return the decision and a brief rationale."
    )


def blackbox_system_prompt(policy: PolicyParams) -> str:
    """Black-box prompt: the SAME tolerance, but as latent natural language no role signed (§3.4)."""
    return (
        "You are an accounts-payable agent. Decide whether to pay, hold, or escalate each invoice. "
        f"Invoices within {policy.tolerance_pct:.0f}% of an approved PO may be paid unless anomalous. "
        f"Escalate anything at or above ${policy.escalation_threshold:,.0f} to a human. "
        "Hold anything with no PO, a non-active PO, a vendor mismatch, or an amount over tolerance. "
        "Use the lookup_po tool to check the PO. Return a decision and a brief rationale."
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
) -> tuple[AgentDecision, bool]:
    """Run the execution agent on one invoice through the record/replay cache.

    `extra_signals` carries upstream node outputs (e.g. {"anomalous": True, "duplicate": True})
    so node 3 can act on what nodes 1/2 produced — this is how the network edges feed forward.
    Returns (decision, was_cached).
    """
    model_id = model.split(":", 1)[-1]
    signals = extra_signals or {}

    # The cache key must capture everything that determines the answer.
    cache_payload = json.dumps(
        {"system": system_prompt, "invoice": invoice, "pos": pos, "signals": signals},
        sort_keys=True,
    )

    user_message = "Decide this invoice:\n" + json.dumps(invoice, indent=2)
    if signals:
        user_message += "\n\nUpstream signals:\n" + json.dumps(signals, indent=2)

    def _real_call() -> dict:
        agent = _build_agent(model, system_prompt, pos)
        result = agent.run_sync(user_message)
        return result.output.model_dump()

    response, was_cached = cache.cached_call(model_id, cache_payload, _real_call)
    return AgentDecision(**response), was_cached
