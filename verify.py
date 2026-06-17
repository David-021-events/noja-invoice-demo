"""verify.py — the proof artifact for skeptics (SRD §6).

Reads the canonical JSON trail ONLY (never SQLite, never the viewer manifest) and proves:

  1. BINDING + SIGNATURE — every signed_artifact_ref in the trail names a tag that (a) passes
     `git verify-tag` and (b) actually points at the content_hash the trail claims. This binds the
     unsigned trail JSON to the signed bytes: editing a record's claimed hash, or pointing it at a
     different blob, is detected. Covers onboarding, node, payment, HITL, and transition records.
  2. NO GAPS — every terminal outcome (each leaf event: a payment, a HITL decision, a HOLD)
     reconstructs back to a root node with no broken upstream_ref edges.
  3. MONEY-MOVEMENT INTEGRITY — every PAY decision has exactly one matching payment_authorized
     event and vice versa, and every payment was made under an Active signature (no pay-after-lapse).

Run:  python verify.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from engine import sign
from engine.trail import is_payment, read_trail

_TRAIL = Path(__file__).resolve().parent / "trail"


class Gap(Exception):
    """A break in the audit chain: a missing/unverifiable signature or a broken edge."""


def _verify_all_signed_tags(records: list[dict]) -> int:
    """Phase 1: verify-tag + content-hash binding for every signed ref. Returns #unique tags."""
    seen: dict[str, str] = {}  # tag -> content_hash (to catch a tag claimed with two hashes)
    for r in records:
        ref = r.get("signed_artifact_ref")
        if ref is None:
            continue
        if not isinstance(ref, dict) or "tag" not in ref or "content_hash" not in ref:
            raise Gap(f"record {r.get('event_id')} has a malformed signed_artifact_ref: {ref!r}")
        tag, content_hash = ref["tag"], ref["content_hash"]
        if tag in seen:
            if seen[tag] != content_hash:
                raise Gap(f"tag {tag} is claimed with two different content hashes")
            continue
        if not sign.verify(tag):
            raise Gap(f"git verify-tag FAILED for {tag}")
        target = sign.tag_target_hash(tag)
        if target != content_hash:
            raise Gap(f"tag {tag} points at {target}, but the trail claims {content_hash} "
                      f"(trail tampered or ref repointed)")
        seen[tag] = content_hash
    return len(seen)


def _reconstruct(terminal: dict, by_id: dict[str, dict]) -> list[dict]:
    """Walk terminal -> root via upstream_ref. Raises Gap on a broken edge. Tags already verified."""
    chain: list[dict] = []
    visited: set[str] = set()  # a tampered trail could form an upstream_ref cycle; don't loop forever
    cur: dict | None = terminal
    while cur is not None:
        if cur.get("signed_artifact_ref") is None:
            raise Gap(f"{cur.get('invoice_id')}: chain record {cur.get('event_id')} has no signed artifact")
        eid = cur.get("event_id")
        if eid in visited:
            raise Gap(f"{cur.get('invoice_id')}: upstream_ref cycle through event {eid}")
        visited.add(eid)
        chain.append(cur)
        upstream = cur.get("upstream_ref")
        if upstream is None:
            break  # reached a root node (no upstream)
        nxt = by_id.get(upstream)
        if nxt is None:
            raise Gap(f"{cur.get('invoice_id')}: upstream_ref {upstream} points to a missing event")
        cur = nxt
    return chain


def _is_pay_decision(r: dict) -> bool:
    execution = (r.get("output") or {}).get("execution")
    return isinstance(execution, dict) and execution.get("decision") == "PAY"


def _terminal_kind(r: dict) -> str:
    out = r.get("output") or {}
    execution = out.get("execution")
    exec_decision = execution.get("decision") if isinstance(execution, dict) else None
    return out.get("action") or out.get("resolution") or exec_decision or "outcome"


def _lapse_seq_by_tag(transitions: list[dict]) -> dict[str, int]:
    """Map each composite's signed artifact tag -> the seq at which it lapsed (earliest, if many).

    The lapse transition is itself a signed, verified record; its prior_signature_ref is the very
    tag a later payment would cite. So pay-after-lapse is derived from signed evidence + ordering,
    not from the payment's own (unsigned) signature_state field."""
    lapse_seq: dict[str, int] = {}
    for t in transitions:
        out = t.get("output") or {}
        if out.get("to_state") != "Lapsed":
            continue
        tag = (out.get("prior_signature_ref") or {}).get("tag")
        seq = t.get("seq")
        if tag is not None and seq is not None:
            lapse_seq[tag] = min(lapse_seq.get(tag, seq), seq)
    return lapse_seq


def _check_money_movement(noja: list[dict], by_id: dict[str, dict],
                          transitions: list[dict]) -> list[str]:
    """Every PAY decision <-> exactly one payment event; no payment cites a composite after it lapsed."""
    errors: list[str] = []
    pay_decisions = {r["event_id"] for r in noja if _is_pay_decision(r)}
    payments = [r for r in noja if is_payment(r)]
    lapse_seq = _lapse_seq_by_tag(transitions)

    paid_for = defaultdict(int)
    for p in payments:
        up = p.get("upstream_ref")
        if up not in pay_decisions:
            errors.append(f"{p.get('invoice_id')}: payment_authorized not backed by a PAY decision")
        else:
            paid_for[up] += 1
        # Primary check, derived from signed evidence: a payment must not cite a composite tag at or
        # after the seq where a signed transition lapsed that tag.
        tag = (p.get("signed_artifact_ref") or {}).get("tag")
        if tag in lapse_seq and (p.get("seq") or -1) > lapse_seq[tag]:
            errors.append(f"{p.get('invoice_id')}: payment cites composite {tag} AFTER its signed "
                          f"lapse (payment seq {p.get('seq')} > lapse seq {lapse_seq[tag]})")
        # Secondary, defence-in-depth: the record's self-reported state must also say Active.
        if p.get("signature_state") != "Active":
            errors.append(f"{p.get('invoice_id')}: payment made under signature_state="
                          f"{p.get('signature_state')!r} (must be Active — no pay after lapse)")
    for d in pay_decisions:
        if paid_for[d] != 1:
            errors.append(f"{by_id[d].get('invoice_id')}: PAY decision has {paid_for[d]} matching "
                          f"payment events (expected exactly 1)")
    return errors


def main() -> int:
    records = read_trail(_TRAIL)
    if not records:
        print("No trail records found. Run:  python -m runs.noja")
        return 1

    by_id = {r["event_id"]: r for r in records}
    # Per-invoice reconstruction excludes non-invoice markers like "(onboarding)" / "(transition)";
    # their signed tags are still checked by the Phase-1 binding pass over ALL records.
    noja = [r for r in records
            if r.get("pipeline") == "noja"
            and r.get("invoice_id") and not str(r["invoice_id"]).startswith("(")]

    print("NOJA trail verification (reads JSON only)\n" + "=" * 64)

    try:
        n_tags = _verify_all_signed_tags(records)
    except Gap as gap:
        print(f"[FAIL] binding: {gap}")
        return 1
    print(f"[ok] binding: {n_tags} signed tags verify AND point at the exact bytes the trail claims")

    # Reconstruct every terminal (leaf = an event nobody else lists as upstream). This generically
    # covers payments, HITL decisions, and HOLDs — including multiple payments in a swap window.
    referenced = {r.get("upstream_ref") for r in noja if r.get("upstream_ref")}
    by_invoice: dict[str, list[dict]] = defaultdict(list)
    for r in noja:
        by_invoice[r["invoice_id"]].append(r)

    ok = True
    for inv in sorted(by_invoice):
        leaves = [r for r in by_invoice[inv] if r["event_id"] not in referenced]
        for leaf in leaves:
            try:
                chain = _reconstruct(leaf, by_id)
            except Gap as gap:
                print(f"[GAP] {gap}")
                ok = False
                continue
            roles = " <- ".join(f"{r['node']}({r['accountable_role']})" for r in chain)
            print(f"[ok] {inv}: {_terminal_kind(leaf):<18} {roles}")

    transitions = [r for r in records if r.get("function") == "transition"]
    money_errors = _check_money_movement(noja, by_id, transitions)
    for err in money_errors:
        print(f"[FAIL] money: {err}")
    ok = ok and not money_errors
    if not money_errors:
        n_pay = sum(1 for r in noja if is_payment(r))
        print(f"[ok] money-movement integrity: {n_pay} payment(s), each backed by a PAY decision "
              f"and none citing a composite after its signed lapse")

    print("=" * 64)
    if ok:
        print(f"VERIFIED: {len(by_invoice)} invoices reconstructed, no gaps; signatures bound to bytes; "
              f"money movement consistent.")
        return 0
    print("FAILED: see [GAP]/[FAIL] above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
