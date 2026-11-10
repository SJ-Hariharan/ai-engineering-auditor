"""Pricing helpers."""


def apply_discount(total_cents: int, pct: int) -> int:
    if not 0 <= pct <= 100:
        raise ValueError("pct must be within 0..100")
    return total_cents * (100 - pct) // 100
