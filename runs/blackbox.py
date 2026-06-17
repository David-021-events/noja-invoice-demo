"""runs/blackbox.py — the single-loop black-box counterpart (SRD §8.4 / §3.4).

One Pydantic AI agent, same model, same tools, same invoices, performing all four functions in one
loop. It writes a deliberately THIN trail: the decision and a free-text rationale, and a thin
payment_authorized event on PAY — but NO signed artifacts, NO named roles, NO scope, NO fallback,
NO upstream chain. The thinness is the demonstration, not a bug: run `python verify.py` after this
and there is nothing to reconstruct on the black-box side.

The tolerance policy it uses is identical to the NOJA approval node's — but it lives latent in the
system prompt, signed by no one (§3.4). Same policy, same outcomes; only the accountability differs.

Writes into the shared trail/ (alongside any NOJA records) so the Step-7 viewer can show both
pipelines side by side. Re-running replaces only the black-box records.

Run from the repo root:  python -m runs.blackbox
"""

from __future__ import annotations

from pathlib import Path

from domain import agent, approval_policy, fixtures
from engine.trail import Trail, clear_trail, is_payment, read_trail
from llm import client

_ROOT = Path(__file__).resolve().parent.parent
_TRAIL = _ROOT / "trail"


def _write_decision(trail: Trail, invoice: dict, decision: str, rationale: str) -> None:
    """A faithfully thin record: decision + rationale only. No role, signature, scope, or upstream."""
    trail.write(
        pipeline="blackbox", invoice_id=invoice["invoice_id"], node="blackbox-loop",
        function="execution", output={"decision": decision, "rationale": rationale},
    )


def _write_payment(trail: Trail, invoice: dict) -> None:
    """PAY = a thin payment_authorized event (§2.1). No signature backs it — that is the point."""
    trail.write(
        pipeline="blackbox", invoice_id=invoice["invoice_id"], node="blackbox-loop",
        function="execution",
        output={"action": "payment_authorized", "amount": invoice["total_amount"],
                "vendor": invoice["vendor"]},
    )


def run_blackbox(trail: Trail, pos: list[dict], invoices: list[dict], model: str) -> dict:
    """Process every invoice through the single black-box loop. Returns {invoice_id: decision}."""
    policy = approval_policy.POLICY  # identical policy numbers as NOJA — but latent in the prompt
    prompt = agent.blackbox_system_prompt(policy)
    seen: list[dict] = []
    outcomes: dict[str, str] = {}

    for inv in invoices:
        # The agent's only "memory" of prior invoices (so it can spot duplicates) — passed as
        # context, not as a signed upstream artifact.
        context = {"previously_processed": list(seen)}
        agent_decision, _cached = agent.decide(
            invoice=inv, pos=pos, policy=policy, system_prompt=prompt, model=model,
            extra_signals=context, signals_label="Context (invoices you have already processed)",
        )
        decision = agent_decision.decision
        outcomes[inv["invoice_id"]] = decision

        _write_decision(trail, inv, decision, agent_decision.rationale)
        if decision == "PAY":
            _write_payment(trail, inv)

        seen.append({"invoice_id": inv["invoice_id"], "vendor": inv["vendor"],
                     "total": inv["total_amount"]})

    return outcomes


def main() -> None:
    client.require_api_key()
    clear_trail(_TRAIL, pipeline="blackbox")  # remove only black-box records; keep NOJA intact
    pos = fixtures.purchase_orders()
    invoices = fixtures.invoices()
    model = client.current_model()
    trail = Trail(_TRAIL)

    print(f"Black-box pipeline — model={client.model_id()}\n" + "=" * 60)
    outcomes = run_blackbox(trail, pos, invoices, model)
    for inv in invoices:
        exp = inv["_expected"]
        got = outcomes[inv["invoice_id"]]
        mark = "ok " if got == exp else "DIFF"
        print(f"[{mark}] {inv['invoice_id']}: {got:<9} (expected {exp})")

    bb = [r for r in read_trail(_TRAIL) if r.get("pipeline") == "blackbox"]
    payments = sum(1 for r in bb if is_payment(r))
    signed = sum(1 for r in bb if "signed_artifact_ref" in r)
    matched = sum(1 for inv in invoices if outcomes[inv["invoice_id"]] == inv["_expected"])
    print("=" * 60)
    print(f"Black-box run complete: {matched}/{len(invoices)} expected; {payments} payment(s); "
          f"{len(bb)} thin records; {signed} signed artifacts (0 by design — nothing to trace).")


if __name__ == "__main__":
    main()
