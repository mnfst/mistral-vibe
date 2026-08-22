"""Pure formatters. No Textual, no terminal. Unit testable on their own."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def money(value: Decimal) -> str:
    """Two decimals, always, so a column of costs aligns on the point."""
    return f"${value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def compact_int(value: int) -> str:
    """1400000 -> 1.4M. Terminal columns are scarce; full digits are not worth them."""
    for limit, suffix in ((1_000_000_000, "b"), (1_000_000, "M"), (1_000, "k")):
        if value >= limit:
            scaled = value / limit
            return f"{scaled:.1f}{suffix}" if scaled < 10 else f"{scaled:.0f}{suffix}"  # noqa: PLR2004
    return str(value)


def percent(part: Decimal, whole: Decimal) -> str:
    if whole == 0:
        return "0.0%"
    return f"{(part / whole * 100):.1f}%"


def short_day(value: date) -> str:
    return value.strftime("%b %-d")


def ellipsise(text: str, width: int) -> str:
    """Never let a project name push a column out of place."""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"
