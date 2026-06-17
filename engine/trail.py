"""Canonical JSON audit trail.

SRD §6 / §5.1: the JSON files in `trail/` ARE the §4.4 reconstruction-complete audit trail.
One JSON record per event. No SQLite here — for a ~dozen-record demo it would only add a sync
surface (SRD §5.1 says drop it unless it genuinely helps; it doesn't).

Domain-agnostic: records are plain dicts. The engine enforces only the base fields every event
needs; node/domain code supplies the rest (NOJA fields for the signed pipeline, thin fields for
the black-box pipeline).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

# §6 function vocabulary.
FUNCTIONS = {"prediction", "judgment", "execution", "accountability", "transition"}
PIPELINES = {"noja", "blackbox"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Trail:
    """Append-only writer of canonical JSON event records to a directory."""

    def __init__(self, trail_dir: str | Path):
        self.dir = Path(trail_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._seq = self._next_seq()

    def _next_seq(self) -> int:
        # Derive from the max existing seq prefix (not the count) so a gap or stray file can't
        # produce a colliding seq. Filenames are "{seq:04d}_{event_id}.json".
        max_seq = -1
        for p in self.dir.glob("*.json"):
            head = p.name.split("_", 1)[0]
            if head.isdigit():
                max_seq = max(max_seq, int(head))
        return max_seq + 1

    def write(
        self,
        *,
        pipeline: str,
        invoice_id: str,
        node: str,
        function: str,
        output: dict,
        # NOJA-only fields (omitted for the faithfully-thin black-box trail, SRD §6):
        accountable_role: str | None = None,
        signed_artifact_ref: dict | None = None,
        scope: dict | None = None,
        signature_state: str | None = None,
        upstream_ref: str | None = None,
        # passthrough for specialized records (e.g. transition payloads):
        extra: dict | None = None,
    ) -> str:
        if pipeline not in PIPELINES:
            raise ValueError(f"unknown pipeline {pipeline!r}")
        if function not in FUNCTIONS:
            raise ValueError(f"unknown function {function!r}")

        event_id = str(uuid.uuid4())
        record: dict = {
            "event_id": event_id,
            "seq": self._seq,
            "timestamp": _utc_now_iso(),
            "pipeline": pipeline,
            "invoice_id": invoice_id,
            "node": node,
            "function": function,
            "output": output,
        }
        # NOJA records carry the accountability chain; black-box records deliberately do not.
        if accountable_role is not None:
            record["accountable_role"] = accountable_role
        if signed_artifact_ref is not None:
            record["signed_artifact_ref"] = signed_artifact_ref
        if scope is not None:
            record["scope"] = scope
        if signature_state is not None:
            record["signature_state"] = signature_state
        if upstream_ref is not None:
            record["upstream_ref"] = upstream_ref  # the §3.2 edge: the event that produced our input
        if extra:
            record.update(extra)

        self._seq += 1
        self._persist(record)
        return event_id

    def _persist(self, record: dict) -> None:
        name = f"{record['seq']:04d}_{record['event_id']}.json"
        path = self.dir / name
        path.write_text(json.dumps(record, indent=2, sort_keys=False) + "\n")

    def records(self) -> list[dict]:
        """Read every record back, in sequence order (canonical source for verify/manifest)."""
        return read_trail(self.dir)


def read_trail(trail_dir: str | Path) -> list[dict]:
    """Read all canonical JSON records from a trail directory, in sequence order."""
    return [json.loads(p.read_text()) for p in sorted(Path(trail_dir).glob("*.json"))]
