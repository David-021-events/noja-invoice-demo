"""Signature lifecycle: states, scope, automatic lapse, and fallback selection.

Implements NOJA v0.6 §4. Scoped to exactly what the demo exercises (SRD §4): the full
state/fallback/scope enums exist so the spec mapping reads correctly, but only the
Drafted→Active and Active→Lapsed transitions carry real machinery.

Domain-agnostic: this module never mentions invoices. Scope conditions are opaque
key/value facts; lapse is "a pinned condition no longer matches the observed world."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.sign import SignedRef


class State(str, Enum):
    """The §4.1 signature states. Demo exercises Drafted, Active, Lapsed (others defined for
    spec fidelity, not built out — SRD §4.1)."""

    DRAFTED = "Drafted"
    PROVISIONAL = "Provisional"
    ACTIVE = "Active"
    SUSPENDED = "Suspended"
    LAPSED = "Lapsed"
    REVOKED = "Revoked"
    SUPERSEDED = "Superseded"
    ARCHIVED = "Archived"


class Fallback(str, Enum):
    """The §4.2 fallback set. Demo selects SAFE_MODE on lapse."""

    HALT = "Halt"
    SAFE_MODE = "Safe-mode"
    DRAIN_THEN_HALT = "Drain-then-halt"
    CUT_OVER = "Cut-over"


@dataclass(frozen=True)
class Scope:
    """The four §4.3 scope axes. The behavior-envelope condition (e.g. pinned model id) is the
    one the demo turns on; the rest are declared but not elaborately monitored (SRD §4.2)."""

    domain: str
    temporal: str
    environmental: dict = field(default_factory=dict)      # condition sub-axis: world facts (e.g. lockfile)
    behavior_envelope: dict = field(default_factory=dict)  # condition sub-axis: own-behavior facts (e.g. model_id)
    volume: str = "unbounded-for-demo"

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "temporal": self.temporal,
            "condition": {
                "environmental": dict(self.environmental),
                "behavior_envelope": dict(self.behavior_envelope),
            },
            "volume": self.volume,
        }


@dataclass
class TransitionRecord:
    """A §4.1 state transition. For the automatic lapse the attestor is the engine/detector, not
    a human — the human authority was pre-signed in prior_signature_ref (§4.5). Matches the SRD §6
    transition record format."""

    transition_id: str
    signature_id: str
    from_state: str
    to_state: str
    trigger: str
    previous_scope_condition: dict
    observed_condition: dict
    fallback_selected: str
    transition_attestor: str
    prior_signature_ref: dict
    timestamp: str
    transition_artifact_hash: str | None = None  # filled in after the record is signed

    def to_dict(self) -> dict:
        return {
            "transition_id": self.transition_id,
            "signature_id": self.signature_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "trigger": self.trigger,
            "previous_scope_condition": self.previous_scope_condition,
            "observed_condition": self.observed_condition,
            "fallback_selected": self.fallback_selected,
            "transition_attestor": self.transition_attestor,
            "prior_signature_ref": self.prior_signature_ref,
            "timestamp": self.timestamp,
            "transition_artifact_hash": self.transition_artifact_hash,
        }


class FallbackError(RuntimeError):
    """Raised when a requested fallback was not in the pre-signed set (§4.2)."""


@dataclass
class Signature:
    """A signature over a signed artifact, with scope, a pre-signed fallback set, and state.

    The §4.5 reconciliation lives here: when this signature is made Active, the owner pre-signs
    both the scope conditions AND the fallback set. So at lapse time the engine *detects and
    records* from that pre-signed authority; no human signs in the moment. The only live human
    signature is the later re-authorization (a fresh Signature), which the engine never fabricates.
    """

    signature_id: str
    accountable_role: str
    artifact_ref: SignedRef
    scope: Scope
    fallback_set: tuple[Fallback, ...]
    state: State = State.DRAFTED
    prior_signature_ref: dict | None = None

    def __post_init__(self) -> None:
        if not self.fallback_set:
            # §4.2: an Active signature without a named fallback set is non-conformant.
            raise FallbackError("A signature must declare a non-empty pre-signed fallback set (§4.2).")

    def activate(self) -> None:
        """Drafted → Active. The owner's signature already binds scope + fallback (§4.5)."""
        self.state = State.ACTIVE

    def detect_lapse(self, observed: dict) -> bool:
        """True iff any pinned behavior-envelope condition no longer matches the observed world.

        `observed` is a flat dict of the same keys the behavior envelope pins (e.g. {"model_id": ...}).
        This is the §4.3 lapse condition; the demo turns it on via model_id (SRD §4.2)."""
        for key, pinned in self.scope.behavior_envelope.items():
            if observed.get(key) != pinned:
                return True
        return False

    def _select_fallback(self, preferred: Fallback = Fallback.SAFE_MODE) -> Fallback:
        """Select a fallback from the *pre-signed set* (§4.2/§4.5). Demo prefers Safe-mode."""
        if preferred in self.fallback_set:
            return preferred
        return self.fallback_set[0]

    def lapse(
        self,
        observed: dict,
        transition_id: str,
        timestamp: str,
        trigger: str = "model_version_changed",
        attestor: str = "engine-detector",
    ) -> TransitionRecord:
        """Generate the Active → Lapsed transition from the pre-signed scope + fallback (§4.5).

        The engine detects and records; it does not pretend a human signs now. The returned
        record must then be written to the trail and signed with the engine/detector key by the
        caller (sign.sign_transition). Sets state to Lapsed.
        """
        if self.state is not State.ACTIVE:
            raise RuntimeError(f"Only an Active signature can lapse; state is {self.state.value}.")

        fallback = self._select_fallback()
        # Record only the pinned conditions that actually broke, against what was observed.
        previous = dict(self.scope.behavior_envelope)
        observed_subset = {k: observed.get(k) for k in self.scope.behavior_envelope}

        self.state = State.LAPSED
        return TransitionRecord(
            transition_id=transition_id,
            signature_id=self.signature_id,
            from_state=State.ACTIVE.value,
            to_state=State.LAPSED.value,
            trigger=trigger,
            previous_scope_condition=previous,
            observed_condition=observed_subset,
            fallback_selected=fallback.value,
            transition_attestor=attestor,
            prior_signature_ref=self.artifact_ref.to_dict(),
            timestamp=timestamp,
        )
