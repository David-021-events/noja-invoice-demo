"""runs/noja.py — wire the four-node NOJA network end to end (SRD §8.3).

node 1 (anomaly) -> node 2 (approval policy) -> node 3 (agent execution) -> node 4 (HITL, on escalate)

Each node's execution output becomes the next node's prediction input (NOJA §3), and every record
carries upstream_ref so the whole path is reconstructible (§3.2). PAY = a payment_authorized trail
event (§2.1). Onboarding signs nodes 1-3 into Active (Drafted->Active, human signatures); node 4
signs a per-instance decision for each escalation.

Run from the repo root:  python -m runs.noja
Then prove traceability with:  python verify.py
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from domain import agent, anomaly, approval_policy, escalation, fixtures
from engine import sign
from engine.node import JudgmentNode
from engine.signature import Fallback, Scope, Signature, State, TransitionRecord
from engine.trail import Trail, clear_trail, is_payment
from llm import client

_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS = _ROOT / "artifacts"
_TRAIL = _ROOT / "trail"
_LOCKFILE = _ROOT / "requirements.txt"

_FALLBACK_SET = (Fallback.SAFE_MODE, Fallback.HALT)


def _environmental_scope() -> dict:
    """The signed environmental scope condition (§4.3/§5.1): the dependency lockfile's content hash.
    Pinning the HASH (not just the filename) makes the condition genuinely enforceable — a changed
    lockfile lapses the composite, exactly as a model swap does. Computed fresh each run, identical
    at onboarding and at lapse-detection, so it never false-lapses within a run."""
    return {"lockfile_sha256": hashlib.sha256(_LOCKFILE.read_bytes()).hexdigest()}


def _observed_world(model: str) -> dict:
    """The observed values for every pinned composite condition (model + environment)."""
    return {"model_id": client.bare_id(model), **_environmental_scope()}


def _write_artifact(node: str, artifact_id: str, content: str) -> Path:
    path = _ARTIFACTS / node / f"{artifact_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _onboard(
    *, trail: Trail, node: str, artifact_id: str, content: str, role: str, scope: Scope, sig_id: str
) -> Signature:
    """Sign an artifact and bring its signature Drafted -> Active, recording the onboarding."""
    path = _write_artifact(node, artifact_id, content)
    ref = sign.sign_artifact(path, node=node, artifact_id=artifact_id,
                             message=f"onboard {node} artifact, signed by {role}")
    sig = Signature(signature_id=sig_id, accountable_role=role, artifact_ref=ref,
                    scope=scope, fallback_set=_FALLBACK_SET)
    sig.activate()
    trail.write(
        pipeline="noja", invoice_id="(onboarding)", node=node, function="accountability",
        output={"event": "signature_activated", "from_state": "Drafted", "to_state": "Active"},
        accountable_role=role, signed_artifact_ref=ref.to_dict(),
        scope=scope.to_dict(), signature_state=State.ACTIVE.value,
    )
    return sig


@dataclass
class Signatures:
    anomaly: Signature
    approval: Signature
    composite: Signature


def onboard_composite(
    trail: Trail, model: str, *, role: str = "AI Controls Lead", sig_id: str = "sig-composite",
    artifact_id: str = "composite",
) -> Signature:
    """Sign node 3's execution composite into Active, scoped to the pinned model id AND the pinned
    environment (the lapse axes). The ONE definition of the composite's artifact + scope, reused for
    both initial onboarding and post-swap re-authorization so the two can never drift."""
    bare_model = client.bare_id(model)
    system_prompt = agent.noja_system_prompt(approval_policy.POLICY)
    environmental = _environmental_scope()
    return _onboard(
        trail=trail, node="agent_composite", artifact_id=artifact_id,
        content=agent.composite_artifact_bytes(
            approval_policy.POLICY, system_prompt, bare_model, environmental),
        role=role, sig_id=sig_id,
        scope=Scope(
            domain="invoice-approval/execution", temporal="demo-run",
            environmental=environmental,                  # §4.3 condition: lockfile hash
            behavior_envelope={"model_id": bare_model},   # §4.3 condition the swap breaks
        ),
    )


def onboard_all(trail: Trail, model: str) -> Signatures:
    """Sign nodes 1-3 into Active. Node 3's composite is scoped to the pinned model id + environment."""
    sig1 = _onboard(
        trail=trail, node=anomaly.NODE, artifact_id=anomaly.ARTIFACT_ID,
        content=anomaly.artifact_bytes(), role=anomaly.ROLE, sig_id="sig-anomaly",
        scope=Scope(domain="invoice-approval/anomaly", temporal="demo-run"),
    )
    sig2 = _onboard(
        trail=trail, node=approval_policy.NODE, artifact_id=approval_policy.ARTIFACT_ID,
        content=approval_policy.artifact_bytes(), role=approval_policy.ROLE, sig_id="sig-approval",
        scope=Scope(domain="invoice-approval/approval-policy", temporal="demo-run"),
    )
    # detect_lapse now fails loud on a condition-less composite, so the old model_id-pin assertion
    # is no longer needed: onboard_composite always pins the lapse axes in one place.
    sig3 = onboard_composite(trail, model)
    return Signatures(anomaly=sig1, approval=sig2, composite=sig3)


def _build_nodes(trail: Trail, pos: list[dict], sigs: Signatures, model: str):
    n1 = JudgmentNode(
        name=anomaly.NODE, accountable_role=anomaly.ROLE, signature=sigs.anomaly, trail=trail,
        predict_fn=anomaly.predict, judge_fn=anomaly.judge, execute_fn=anomaly.execute,
    )
    p2, j2, e2 = approval_policy.make_fns(pos)
    n2 = JudgmentNode(
        name=approval_policy.NODE, accountable_role=approval_policy.ROLE, signature=sigs.approval,
        trail=trail, predict_fn=p2, judge_fn=j2, execute_fn=e2,
    )
    system_prompt = agent.noja_system_prompt(approval_policy.POLICY)
    p3, j3, e3 = agent.make_execution_fns(pos=pos, policy=approval_policy.POLICY,
                                          system_prompt=system_prompt, model=model)
    n3 = JudgmentNode(
        name="agent_execution", accountable_role="AI Controls Lead", signature=sigs.composite,
        trail=trail, predict_fn=p3, judge_fn=j3, execute_fn=e3,
        fallback_fn=agent.safe_mode_execution,
    )
    return n1, n2, n3


def _write_payment(trail: Trail, invoice: dict, upstream_ref: str, sig: Signature) -> None:
    """PAY = a payment_authorized trail event (§2.1). This event IS the money movement."""
    trail.write(
        pipeline="noja", invoice_id=invoice["invoice_id"], node="agent_execution",
        function="execution",
        output={"action": "payment_authorized", "amount": invoice["total_amount"],
                "vendor": invoice["vendor"]},
        accountable_role="AI Controls Lead", signed_artifact_ref=sig.artifact_ref.to_dict(),
        scope=sig.scope.to_dict(), signature_state=sig.state.value, upstream_ref=upstream_ref,
    )


def lapse_composite(trail: Trail, sig: Signature, observed_model_id: str) -> TransitionRecord | None:
    """Engine-detected Active->Lapsed transition (§4.5). Returns the transition, or None if scope
    still holds. The transition is drawn from the PRE-SIGNED scope+fallback and attested by the
    engine/detector key — no human signs at lapse time. Records and signs the transition.

    `observed_model_id` is the bare id of the now-pinned model; the environmental conditions are
    observed from the live world so any pinned axis (model OR lockfile) can drive the lapse."""
    observed = {"model_id": observed_model_id, **_environmental_scope()}
    if not sig.detect_lapse(observed):
        return None
    ts = datetime.now(timezone.utc).isoformat()
    transition = sig.lapse(observed, transition_id=str(uuid.uuid4()), timestamp=ts)
    path = _write_artifact("transitions", transition.transition_id,
                           json.dumps(transition.to_dict(), indent=2, sort_keys=True))
    ref = sign.sign_transition(path, signature_id=sig.signature_id, to_state="Lapsed",
                               timestamp=ts, message="engine-detected lapse: behavior-envelope "
                               f"model {transition.previous_scope_condition} no longer obtains")
    transition.transition_artifact_hash = ref.content_hash
    trail.write(
        pipeline="noja", invoice_id="(transition)", node="agent_composite", function="transition",
        output=transition.to_dict(), signed_artifact_ref=ref.to_dict(),
        signature_state=State.LAPSED.value,
    )
    return transition


def _run_hitl(trail: Trail, invoice: dict, upstream_ref: str) -> str:
    """Node 4: capture and sign a per-instance HITL decision (AP Manager)."""
    decision = escalation.resolve(invoice["invoice_id"])
    content = escalation.artifact_bytes(invoice["invoice_id"], decision, upstream_ref)
    path = _write_artifact("hitl_decisions", invoice["invoice_id"], content)
    ref = sign.sign_artifact(path, node="escalation", artifact_id=invoice["invoice_id"],
                             message=f"HITL decision for {invoice['invoice_id']} by {escalation.ROLE}")
    return trail.write(
        pipeline="noja", invoice_id=invoice["invoice_id"], node="escalation", function="judgment",
        output={"resolution": decision["resolution"], "note": decision["note"]},
        accountable_role=escalation.ROLE, signed_artifact_ref=ref.to_dict(),
        scope=Scope(domain="invoice-approval/escalation", temporal="per-instance").to_dict(),
        signature_state=State.ACTIVE.value, upstream_ref=upstream_ref,
    )


def run_invoices(trail: Trail, pos: list[dict], invoices: list[dict], sigs: Signatures,
                 model: str) -> dict:
    """Process every invoice through the network. Returns {invoice_id: decision}."""
    n1, n2, n3 = _build_nodes(trail, pos, sigs, model)
    seen: list[dict] = []
    outcomes: dict[str, str] = {}

    for inv in invoices:
        # Strip fixture-only labels (_expected/_case) ONCE at the boundary: the raw answer key must
        # never enter the node graph, so no node's recorded output (or the manifest/viewer) can leak
        # it. Every node downstream forwards the invoice it is given.
        public = agent.public_invoice(inv)
        r1 = n1.run(invoice_id=inv["invoice_id"], prediction_input={"invoice": public, "seen": seen})
        r2 = n2.run(invoice_id=inv["invoice_id"], prediction_input=r1.output, upstream_ref=r1.event_id)
        r3 = n3.run(invoice_id=inv["invoice_id"], prediction_input=r2.output, upstream_ref=r2.event_id)

        decision = r3.output["decision"]
        outcomes[inv["invoice_id"]] = decision
        # No redundant state check here: JudgmentNode.run routes a non-Active signature to its
        # pre-signed safe-mode fallback (which returns HOLD), so a PAY decision can only arise
        # under an Active composite. The no-pay-on-lapse rule lives in the node, not here.
        if decision == "PAY":
            _write_payment(trail, public, upstream_ref=r3.event_id, sig=sigs.composite)
        elif decision == "ESCALATE":
            _run_hitl(trail, public, upstream_ref=r3.event_id)

        seen.append({"vendor": inv["vendor"], "total": inv["total_amount"]})

    return outcomes


def main() -> None:
    sign.ensure_signing_key()      # fail loud if signing is unavailable (§4.4)
    client.require_api_key()       # fail loud before any work if the model key is missing
    clear_trail(_TRAIL)
    pos = fixtures.purchase_orders()
    invoices = fixtures.invoices()
    model = client.current_model()
    trail = Trail(_TRAIL)

    print(f"NOJA pipeline — model={client.model_id()}\n" + "=" * 60)
    sigs = onboard_all(trail, model)
    print(f"[ok] onboarded & signed nodes 1-3 (Active); composite scoped to {client.model_id()}")

    outcomes = run_invoices(trail, pos, invoices, sigs, model)
    for inv in invoices:
        exp = inv["_expected"]
        got = outcomes[inv["invoice_id"]]
        mark = "ok " if got == exp else "DIFF"
        print(f"[{mark}] {inv['invoice_id']}: {got:<9} (expected {exp})")

    records = trail.records()
    payments = sum(1 for r in records if is_payment(r))
    matched = sum(1 for inv in invoices if outcomes[inv["invoice_id"]] == inv["_expected"])
    print("=" * 60)
    print(f"NOJA run complete: {matched}/{len(invoices)} expected; "
          f"{payments} payment_authorized event(s); {len(records)} trail records.")
    print("Now run:  python verify.py")


if __name__ == "__main__":
    main()
