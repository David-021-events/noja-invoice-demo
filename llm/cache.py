"""Record/replay cache (SRD §5.1, rip-out-able).

Hash(model id + prompt) -> stored response JSON. Real call on miss, replay on hit. Real calls
during development; cached replay for reproducible demos. Deliberately thin and disposable —
it touches nothing in engine/.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

_CACHE_DIR = Path(__file__).resolve().parent / "_cache"


def _key(model_id: str, prompt: str) -> str:
    return hashlib.sha256(f"{model_id}\x00{prompt}".encode("utf-8")).hexdigest()


def _path(model_id: str, prompt: str) -> Path:
    return _CACHE_DIR / f"{_key(model_id, prompt)}.json"


def get(model_id: str, prompt: str) -> dict | None:
    p = _path(model_id, prompt)
    if p.exists():
        return json.loads(p.read_text())
    return None


def put(model_id: str, prompt: str, response: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _path(model_id, prompt).write_text(json.dumps(response, indent=2) + "\n")


def cached_call(model_id: str, prompt: str, fn: Callable[[], dict]) -> tuple[dict, bool]:
    """Return (response, was_cached). On miss, run fn() (the real model call) and store it."""
    hit = get(model_id, prompt)
    if hit is not None:
        return hit, True
    response = fn()
    put(model_id, prompt, response)
    return response, False
