"""runs/swap_demo.py — the primary punchline (SRD §7.2 / §8.6).

Orchestrates the green-but-unsigned demonstration into one trail:

  Phase A (model A, authorized):
    - eval green on both pipelines; NOJA composite Active, scoped to model A
    - both pipelines process the invoices; PAYs write payment_authorized events
  SWAP: the pinned model changes A -> B (one line: client.set_model)
  Phase B (model B, GREEN BUT UNSIGNED window):
    - eval re-runs under B and is GREEN on both sides (surfaced, not hidden)
    - BLACK-BOX keeps paying — green ⇒ fine. Every payment here is the demonstrated harm:
      money moved while the new model was green but unauthorized.
    - NOJA lapse fires: the composite's behavior-envelope scope (model A) no longer obtains,
      so it transitions Active -> Lapsed via an engine-attested transition drawn from the
      pre-signed scope+fallback (§4.5). Safe-mode holds everything; NO payment_authorized events.
  Phase C (model B, re-authorized):
    - the fresh green model-B eval is presented to the AI Controls Lead, who SIGNS a new
      composite authorizing model B (the only live human signature in the swap). Execution resumes.

Run from the repo root:  python -m runs.swap_demo
Then:                     python verify.py

Mostly served from the record/replay cache, so it is reproducible.
"""

from __future__ import annotations

from pathlib import Path

from domain import agent, approval_policy, fixtures
from engine.signature import Scope
from engine.trail import Trail, read_trail
from evals.suite import run_suite
from llm import client
from runs import blackbox as bb_run
from runs import noja as noja_run

_ROOT = Path(__file__).resolve().parent.parent
_TRAIL = _ROOT / "trail"

PHASE_A = "A: model A — authorized"
PHASE_B = "B: model B — green but unsigned"
PHASE_C = "C: model B — re-authorized"


def _clear_trail() -> None:
    _TRAIL.mkdir(parents=True, exist_ok=True)
    for p in _TRAIL.glob("*.json"):
        p.unlink()


def _surface_eval(trail: Trail, report: dict) -> None:
    """Write the eval result as a badge on BOTH pipelines (§7.3: same green eval on both sides)."""
    for pipeline in ("noja", "blackbox"):
        trail.write(
            pipeline=pipeline, invoice_id="(eval)", node="eval", function="execution",
            output={"event": "eval_result", "green": report["green"],
                    "model_id": report["model_id"], "passed": report["passed"],
                    "total": report["total"]},
        )


def _payments(records: list[dict], pipeline: str, phase: str) -> int:
    return sum(1 for r in records
               if r.get("pipeline") == pipeline and r.get("phase") == phase
               and r.get("output", {}).get("action") == "payment_authorized")


def main() -> None:
    noja_run.sign.ensure_signing_key()
    client.require_api_key()
    _clear_trail()
    pos = fixtures.purchase_orders()
    invoices = fixtures.invoices()
    trail = Trail(_TRAIL)

    bare_a = client.bare_id(client.MODEL_A)
    bare_b = client.bare_id(client.MODEL_B)
    print("NOJA swap demo — the green-but-unsigned window\n" + "=" * 64)

    # ── Phase A: model A, authorized ─────────────────────────────────────────
    client.set_model(client.MODEL_A)
    trail.set_phase(PHASE_A)
    report_a = run_suite(client.MODEL_A)
    _surface_eval(trail, report_a)
    print(f"[A] eval under {bare_a}: {'GREEN' if report_a['green'] else 'RED'} "
          f"({report_a['passed']}/{report_a['total']})")
    sigs = noja_run.onboard_all(trail, client.MODEL_A)
    noja_run.run_invoices(trail, pos, invoices, sigs, client.MODEL_A)
    bb_run.run_blackbox(trail, pos, invoices, client.MODEL_A)
    print(f"[A] NOJA composite Active, scoped to {bare_a}; both pipelines processed invoices")

    # ── SWAP: the pinned model changes (one line) ────────────────────────────
    client.set_model(client.MODEL_B)
    print(f"\n>>> MODEL SWAP: {bare_a}  ->  {bare_b}\n")

    # ── Phase B: model B, green but UNSIGNED ─────────────────────────────────
    trail.set_phase(PHASE_B)
    report_b = run_suite(client.MODEL_B)
    _surface_eval(trail, report_b)
    print(f"[B] eval under {bare_b}: {'GREEN' if report_b['green'] else 'RED'} "
          f"({report_b['passed']}/{report_b['total']}) — green on BOTH sides")

    # Black-box: green ⇒ keep paying. These payments are the harm.
    bb_run.run_blackbox(trail, pos, invoices, client.MODEL_B)
    # NOJA: engine-detected lapse; then run under the lapsed composite -> safe-mode HOLD.
    transition = noja_run.lapse_composite(trail, sigs.composite, bare_b)
    assert transition is not None, "expected the composite to lapse on the model swap"
    print(f"[B] NOJA lapse: composite Active -> Lapsed (attestor={transition.transition_attestor}, "
          f"fallback={transition.fallback_selected}); halting money movement")
    noja_run.run_invoices(trail, pos, invoices, sigs, client.MODEL_B)

    # ── Phase C: re-authorization (the only live human signature in the swap) ──
    trail.set_phase(PHASE_C)
    system_prompt = agent.noja_system_prompt(approval_policy.POLICY)
    sigs.composite = noja_run._onboard(
        trail=trail, node="agent_composite", artifact_id="composite-modelB",
        content=agent.composite_artifact_bytes(approval_policy.POLICY, system_prompt, bare_b),
        role="AI Controls Lead", sig_id="sig-composite-B",
        scope=Scope(domain="invoice-approval/execution", temporal="demo-run",
                    environmental={"lockfile": "requirements.txt"},
                    behavior_envelope={"model_id": bare_b}),
    )
    print(f"[C] AI Controls Lead SIGNED a new composite authorizing {bare_b} (live human signature)")
    noja_run.run_invoices(trail, pos, invoices, sigs, client.MODEL_B)

    # ── The punchline, in numbers ────────────────────────────────────────────
    records = read_trail(_TRAIL)
    bb_window = _payments(records, "blackbox", PHASE_B)
    noja_window = _payments(records, "noja", PHASE_B)
    noja_resumed = _payments(records, "noja", PHASE_C)
    print("=" * 64)
    print(f"GREEN-BUT-UNSIGNED WINDOW (model {bare_b}, eval green, not yet authorized):")
    print(f"  black-box payment_authorized events: {bb_window}  <- HARM: paid while unauthorized")
    print(f"  NOJA      payment_authorized events: {noja_window}  <- halted on lapse, awaited a human")
    print(f"After re-authorization, NOJA resumed: {noja_resumed} payment_authorized event(s).")
    print("Now run:  python verify.py")


if __name__ == "__main__":
    main()
