"""In-memory store."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from inventory_pkg.models import Item
from inventory_pkg.pricing import apply_discount

log = logging.getLogger(__name__)


class Store:
    def __init__(self) -> None:
        self._items: dict[str, Item] = {}

    def add(self, item: Item) -> None:
        if item.quantity < 0:
            raise ValueError("quantity must be non-negative")
        self._items[item.sku] = item

    def get(self, sku: str) -> Item | None:
        return self._items.get(sku)

    def total_value(self, discount_pct: int = 0) -> int:
        total = sum(i.total_cents() for i in self._items.values())
        return apply_discount(total, discount_pct)

    def save(self, path: Path) -> None:
        data = [vars(i) for i in self._items.values()]
        path.write_text(json.dumps(data), encoding="utf-8")

    def load(self, path: Path) -> None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("could not load %s: %s", path, exc)
            raise
        for row in raw:
            self.add(Item(**row))


def find_by_name(conn: sqlite3.Connection, name: str) -> list[tuple]:
    cur = conn.execute("SELECT sku, name FROM items WHERE name = ?", (name,))
    return cur.fetchall()
