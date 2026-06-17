"""The judgment node: NOJA v0.6 §2.

Every node contains four distinguishable functions — prediction, judgment, execution,
accountability — bounded by exactly one accountable role (§2.4). This class is the engine's
reusable unit; the domain supplies the actual functions as callables, so the engine stays
invoice-agnostic (SRD §5.2: engine/ imports nothing from domain/).

Edge traceability (§3.2): each node run records the `upstream_ref` — the trail event_id of the
node whose execution produced this node's prediction input — and returns its own execution
event_id so the next node can chain to it. From any final outcome the whole path is replayable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from engine.signature import Signature, State
from engine.trail import Trail


@dataclass
class NodeResult:
    """A node's outcome plus the trail event that recorded it (the next node's upstream_ref)."""

    decision: Any
    output: Any
    event_id: str
    prediction: Any


class JudgmentNode:
    """One accountable judgment node wired from domain-supplied functions.

    predict_fn(prediction_input)          -> prediction      (§2.1: describes, MUST NOT prescribe)
    judge_fn(prediction, prediction_input)-> decision        (§2.2: applies signed policy)
    execute_fn(decision, prediction_input)-> execution_output(§2.3: carries out the decision)

    The signature (§4) carries the accountable role's authority; if it is not Active, the node
    applies its fallback instead of executing (used by the safe-mode hold after lapse).
    """

    def __init__(
        self,
        *,
        name: str,
        accountable_role: str,
        signature: Signature,
        trail: Trail,
        predict_fn: Callable[[Any], Any],
        judge_fn: Callable[[Any, Any], Any],
        execute_fn: Callable[[Any, Any], Any],
        fallback_fn: Callable[[Any, Any], Any] | None = None,
    ):
        self.name = name
        self.accountable_role = accountable_role
        self.signature = signature
        self.trail = trail
        self._predict = predict_fn
        self._judge = judge_fn
        self._execute = execute_fn
        # Safe-mode behavior when the signature is not Active (drawn from the pre-signed fallback).
        self._fallback = fallback_fn

    def run(
        self,
        *,
        invoice_id: str,
        prediction_input: Any,
        upstream_ref: str | None = None,
    ) -> NodeResult:
        """Run the four functions and write one traceable NOJA trail record for this node."""
        prediction = self._predict(prediction_input)

        if self.signature.state is State.ACTIVE:
            decision = self._judge(prediction, prediction_input)
            output = self._execute(decision, prediction_input)
            signature_state = State.ACTIVE.value
        else:
            # Signature not Active (e.g. Lapsed): the pre-signed fallback governs, not the agent.
            if self._fallback is None:
                raise RuntimeError(
                    f"Node {self.name!r} signature is {self.signature.state.value} and has no "
                    f"pre-signed fallback behavior to apply."
                )
            decision = self._fallback(prediction, prediction_input)
            output = decision
            signature_state = self.signature.state.value

        event_id = self.trail.write(
            pipeline="noja",
            invoice_id=invoice_id,
            node=self.name,
            function="execution",
            output={
                "prediction": prediction,
                "judgment": decision,
                "execution": output,
            },
            accountable_role=self.accountable_role,
            signed_artifact_ref=self.signature.artifact_ref.to_dict(),
            scope=self.signature.scope.to_dict(),
            signature_state=signature_state,
            upstream_ref=upstream_ref,
        )
        return NodeResult(decision=decision, output=output, event_id=event_id, prediction=prediction)
