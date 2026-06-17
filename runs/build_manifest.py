"""runs/build_manifest.py — collect the canonical trail into one file the viewer reads (SRD §5.1).

The viewer is a static page that renders ONE file: viewer/trail_manifest.json. This script produces
it by gathering the per-event JSON records from trail/. The manifest is render-ready data only — all
decision/verification/reconstruction logic stays in the engine and verify.py, never in the viewer.

Run after a run (e.g. python -m runs.swap_demo), then:
  python -m runs.build_manifest
  python -m http.server 8000   # then open http://localhost:8000/viewer/
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from engine.trail import read_trail

_ROOT = Path(__file__).resolve().parent.parent
_TRAIL = _ROOT / "trail"
_MANIFEST = _ROOT / "viewer" / "trail_manifest.json"


def build() -> dict:
    records = read_trail(_TRAIL)
    # Phase order = order of first appearance (so the viewer can lay phases out left-to-right).
    phases: list[str] = []
    for r in records:
        ph = r.get("phase")
        if ph and ph not in phases:
            phases.append(ph)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phases": phases,
        "record_count": len(records),
        "records": records,
    }
    _MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    manifest = build()
    print(f"Wrote {_MANIFEST.relative_to(_ROOT)} — {manifest['record_count']} records, "
          f"{len(manifest['phases'])} phases.")
    print("Serve with:  python -m http.server 8000   then open  http://localhost:8000/viewer/")


if __name__ == "__main__":
    main()
