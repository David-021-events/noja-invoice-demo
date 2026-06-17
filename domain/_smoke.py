"""Step 2 proof (SRD §8.2): real Pydantic AI agent reads a fixture invoice, checks the PO,
returns a decision; the record/replay cache replays deterministically.

Run from the repo root:  python -m domain._smoke
First run makes real Claude calls (needs ANTHROPIC_API_KEY); subsequent runs replay from cache.
"""

from __future__ import annotations

import json
from pathlib import Path

from domain.agent import PolicyParams, decide, noja_system_prompt
from llm import client

_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    return json.loads((_ROOT / "fixtures" / name).read_text())


def main() -> None:
    client.require_api_key()
    invoices = {inv["invoice_id"]: inv for inv in _load("invoices.json")}
    pos = _load("purchase_orders.json")
    policy = PolicyParams()
    prompt = noja_system_prompt(policy)
    model = client.current_model()

    print(f"Step 2 smoke — model={client.model_id()}\n" + "=" * 52)

    # A few PO-check cases the single-invoice agent can decide on its own.
    expect = {"INV-001": "PAY", "INV-002": "PAY", "INV-004": "HOLD", "INV-006": "HOLD",
              "INV-007": "ESCALATE"}
    results = {}
    for inv_id, want in expect.items():
        d, cached = decide(invoice=invoices[inv_id], pos=pos, policy=policy,
                           system_prompt=prompt, model=model)
        flag = "cache" if cached else "live "
        ok = "ok " if d.decision == want else "DIFF"
        print(f"[{ok}|{flag}] {inv_id}: {d.decision:<9} (expected {want}) — {d.rationale[:70]}")
        results[inv_id] = d.decision

    # Determinism: a second pass must be fully cached and identical.
    print("-" * 52)
    all_cached = True
    for inv_id in expect:
        d, cached = decide(invoice=invoices[inv_id], pos=pos, policy=policy,
                           system_prompt=prompt, model=model)
        all_cached &= cached
        assert d.decision == results[inv_id], f"{inv_id} not deterministic on replay"
    assert all_cached, "second pass was not fully served from cache"
    print("[ok] second pass fully cached and identical — replay is deterministic")

    print("=" * 52)
    matches = sum(1 for k, v in expect.items() if results[k] == v)
    print(f"STEP 2 SMOKE: {matches}/{len(expect)} expected decisions; cache replay deterministic.")


if __name__ == "__main__":
    main()
