"""Single loader for the synthetic invoice/PO fixtures (shared by runs and smoke tests)."""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load(name: str) -> list[dict]:
    """Load a fixture JSON file by name, e.g. load('invoices.json')."""
    return json.loads((_FIXTURES / name).read_text())


def invoices() -> list[dict]:
    return load("invoices.json")


def purchase_orders() -> list[dict]:
    return load("purchase_orders.json")
