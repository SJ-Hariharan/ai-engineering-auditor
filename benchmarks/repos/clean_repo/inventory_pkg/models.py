"""Data models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    sku: str
    name: str
    quantity: int
    price_cents: int

    def total_cents(self) -> int:
        return self.quantity * self.price_cents
