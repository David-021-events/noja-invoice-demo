"""Step 1 proof (SRD §8.1): exercise engine/ against a trivial fake domain — no LLM, no invoices.

Run from the repo root:  python -m engine._smoke

Proves, in order:
  1. A node runs its four functions, signs an artifact via a real Git tag, and writes a
     traceable JSON trail record.
  2. git verify-tag passes on the produced tag; the exact signed bytes are recoverable.
  3. A signature transitions Active -> Lapsed as an engine-DETECTED transition, with the
     fallback selection drawn from the pre-signed set (§4.5), and the lapsed node applies
     safe-mode instead of executing.
  4. sign.py fails loud when no signing key is present (§4.4).

This isolates the novel network/signature design before any domain or model complexity.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from engine import sign
from engine.node import JudgmentNode
from engine.signature import Fallback, Scope, Signature, State
from engine.trail import Trail


# ── A trivial fake domain: a "parity gate". Accept even integers under ruleset v1. ──────────
def predict(n: int) -> dict:
    return {"value": n, "parity": "even" if n % 2 == 0 else "odd"}

def judge(prediction: dict, _n: int) -> str:
    return "ACCEPT" if prediction["parity"] == "even" else "REJECT"

def execute(decision: str, _n: int) -> str:
    return f"gate:{decision}"

def safe_mode(_prediction: dict, _n: int) -> str:
    # Pre-signed minimal action: hold everything for review (§4.3 safe-mode).
    return "gate:HOLD(safe-mode)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    print("NOJA engine smoke test (fake parity-gate domain)\n" + "=" * 52)

    # Gate: prove signing works at all before doing anything (§4.4 fail-loud).
    sign.ensure_signing_key()
    print("[ok] signing key present and a self-signed tag verifies")

    created_tags: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        trail = Trail(tmpdir / "trail")

        # 1. Sign the policy artifact bytes via a Git tag.
        policy_path = tmpdir / "parity_policy.txt"
        policy_path.write_text("RULESET v1: accept even integers, reject odd.\n")
        ref = sign.sign_artifact(policy_path, node="parity_gate", artifact_id="ruleset",
                                 message="parity ruleset v1")
        created_tags.append(ref.tag)
        print(f"[ok] artifact signed: tag={ref.tag} content_hash={ref.content_hash[:12]}")

        # 2. verify-tag passes; the signed bytes are recoverable (reconstruction-complete).
        assert sign.verify(ref.tag), "git verify-tag failed on the artifact tag"
        recovered = sign.read_signed_bytes(ref.content_hash)
        assert recovered == policy_path.read_bytes(), "recovered bytes != signed bytes"
        print("[ok] git verify-tag passes and exact signed bytes recovered")

        # Build the signature: scoped to ruleset_version=1, pre-signed fallback set incl. Safe-mode.
        sig = Signature(
            signature_id="sig-parity-1",
            accountable_role="Fake Domain Owner",
            artifact_ref=ref,
            scope=Scope(
                domain="parity-gate",
                temporal="demo-run",
                behavior_envelope={"ruleset_version": "1"},
            ),
            fallback_set=(Fallback.SAFE_MODE, Fallback.HALT),
        )
        sig.activate()
        assert sig.state is State.ACTIVE

        node = JudgmentNode(
            name="parity_gate",
            accountable_role="Fake Domain Owner",
            signature=sig,
            trail=trail,
            predict_fn=predict,
            judge_fn=judge,
            execute_fn=execute,
            fallback_fn=safe_mode,
        )

        # 1 (cont). Run the node; it writes a traceable record carrying role + artifact + scope.
        r1 = node.run(invoice_id="N-002", prediction_input=2)
        assert r1.output == "gate:ACCEPT"
        rec = trail.records()[-1]
        assert rec["accountable_role"] == "Fake Domain Owner"
        assert rec["signed_artifact_ref"]["tag"] == ref.tag
        assert rec["signature_state"] == "Active"
        print(f"[ok] node ran under Active signature -> {r1.output}; trail record traceable")

        # 3. Model/ruleset changes: engine DETECTS lapse from the pre-signed scope.
        observed = {"ruleset_version": "2"}
        assert sig.detect_lapse(observed) is True
        transition = sig.lapse(observed, transition_id=str(uuid.uuid4()), timestamp=_now())
        assert sig.state is State.LAPSED
        assert transition.transition_attestor == "engine-detector"   # not a human (§4.5)
        assert transition.fallback_selected == Fallback.SAFE_MODE.value  # from pre-signed set
        assert transition.prior_signature_ref["tag"] == ref.tag

        # Sign + record the transition with the engine/detector key.
        trans_path = tmpdir / "transition.json"
        import json
        trans_path.write_text(json.dumps(transition.to_dict(), indent=2))
        tref = sign.sign_transition(trans_path, signature_id=sig.signature_id,
                                    to_state="Lapsed", timestamp=transition.timestamp,
                                    message="engine-detected lapse: ruleset_version 1 -> 2")
        created_tags.append(tref.tag)
        transition.transition_artifact_hash = tref.content_hash
        trail.write(pipeline="noja", invoice_id="N-002", node="parity_gate",
                    function="transition", output=transition.to_dict(),
                    signed_artifact_ref=tref.to_dict())
        assert sign.verify(tref.tag)
        print(f"[ok] engine-detected Active->Lapsed; fallback={transition.fallback_selected} "
              f"(pre-signed); transition tag verifies")

        # 3 (cont). With the signature Lapsed, the node applies safe-mode, not the agent.
        r2 = node.run(invoice_id="N-004", prediction_input=4)
        assert r2.output == "gate:HOLD(safe-mode)", r2.output
        assert trail.records()[-1]["signature_state"] == "Lapsed"
        print(f"[ok] lapsed node holds in safe-mode -> {r2.output} (no live execution)")

        # 4. Fail-loud: a fresh repo with no signing key must raise (never downgrade to unsigned).
        with tempfile.TemporaryDirectory() as norepo:
            sign._git("init", "-q", cwd=norepo, check=False)
            try:
                sign.ensure_signing_key(cwd=norepo)
            except sign.SigningKeyError:
                print("[ok] fail-loud: ensure_signing_key raised with no signing key configured")
            else:
                raise AssertionError("ensure_signing_key did NOT fail loud without a key")

    # Clean up the throwaway tags this smoke test created in the repo.
    for tag in created_tags:
        sign._git("tag", "-d", tag, check=False)

    print("=" * 52)
    print("SMOKE PASSED — engine core proven (node, signing, trail, lapse, fallback, fail-loud).")


if __name__ == "__main__":
    main()
