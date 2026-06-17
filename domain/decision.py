"""Pure NOJA decision composition (no signing, no signature gating, no trail).

Runs the same upstream domain functions the signed pipeline uses (anomaly -> approval policy) and
then the SAME node-3 execution composition (agent.execute_decision) that runs/noja.py wires into
node 3. Because both the eval and the pipeline call execute_decision over the same predict/judge
functions, the *model decision under the policy* they compute for a given invoice is identical
(same agent.decide cache key, so model-A cases replay from cache).

What this deliberately does NOT model is signature-state gating. runs/noja.py routes node 3 through
a JudgmentNode that substitutes safe-mode HOLD when the composite signature is not Active (the lapse
path). The eval skips that on purpose: it measures whether the *model* is green, which the demo
treats as evidence that is distinct from authorization (SRD §1.4). A green eval under a lapsed
signature is precisely the situation the demo highlights — the measurement is green, but the
pipeline still halts because no one re-authorized the new model.
"""

from __future__ import annotations

from domain import agent, anomaly, approval_policy


def classify_noja(
    invoice: dict, pos: list[dict], model: str, seen: list[dict] | None = None
) -> tuple[str, bool]:
    """Return (decision, was_cached) for one invoice under the NOJA decision path (model behavior)."""
    n1_in = {"invoice": invoice, "seen": seen or []}
    a_pred = anomaly.predict(n1_in)
    a_dec = anomaly.judge(a_pred, n1_in)
    n1_out = anomaly.execute(a_dec, n1_in)                       # {"invoice", "anomaly"}

    p_predict, p_judge, p_execute = approval_policy.make_fns(pos)
    p_pred = p_predict(n1_out)
    p_dec = p_judge(p_pred, n1_out)
    n2_out = p_execute(p_dec, n1_out)                            # {"invoice", "anomaly", "policy_eval"}

    decision, cached = agent.execute_decision(
        invoice=invoice, pos=pos, policy=approval_policy.POLICY,
        system_prompt=agent.noja_system_prompt(approval_policy.POLICY), model=model,
        anomaly=n2_out["anomaly"], policy_eval=n2_out["policy_eval"],
    )
    return decision.decision, cached
