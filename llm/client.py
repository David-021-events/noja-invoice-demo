"""The single place the pinned model identity lives (SRD §5.1).

Pydantic AI's model-agnostic property is load-bearing: swapping the model to trigger the §4.5
lapse must be a one-line change. That one line is `set_model(MODEL_B)` in the swap demo; here we
hold the current pin and expose the bare model id used in (a) the node-3 composite scope and
(b) the record/replay cache key.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency). Real ANTHROPIC_API_KEY in the env still wins."""
    env = _REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip()
        # Strip surrounding quotes; only strip a trailing inline comment on unquoted values.
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].strip()
        # Only fill from .env when the env has no usable (non-empty) value. setdefault would let an
        # empty exported var (common in Codespaces/CI: `export ANTHROPIC_API_KEY=`) shadow a good
        # .env value; a real non-empty env value still wins.
        if not os.environ.get(key.strip()):
            os.environ[key.strip()] = val


_load_dotenv()

# The two version-pinned model identities the demo swaps between. Both must keep the eval green
# (SRD §7.1). The provider's version-pin attestation is itself a scope condition (NOJA §4.5);
# we treat the id string as that contract.
MODEL_A = "anthropic:claude-haiku-4-5-20251001"
MODEL_B = "anthropic:claude-sonnet-4-6"

_state = {"model": MODEL_A}


def current_model() -> str:
    """The currently pinned Pydantic AI model string (provider:id)."""
    return _state["model"]


def set_model(model: str) -> None:
    """Swap the pinned model. This is the one-line change that triggers the §4.5 lapse."""
    _state["model"] = model


def bare_id(model: str) -> str:
    """Strip the provider prefix from a Pydantic AI model string ('anthropic:claude-x' -> 'claude-x').

    This single definition is the contract used by the cache key AND the node-3 composite scope
    condition, so the lapse axis and the cache stay in lockstep if the prefix convention changes."""
    return model.split(":", 1)[-1]


def model_id() -> str:
    """The bare id of the currently pinned model — used in composite scope and cache keys."""
    return bare_id(current_model())


def require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env or the environment:\n"
            "  echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env"
        )
