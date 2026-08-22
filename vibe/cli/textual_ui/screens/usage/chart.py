"""Stacked bar chart for daily cost, one colour per model.

Cost is a quantity that accumulates, so a stacked bar reads it correctly: the height of
a column is what the day cost, and each band is a model's share of it. A line chart
implies a rate between two points, which spend does not have.

Bars are drawn with block characters at eighth-row resolution, so a small day still
shows a sliver rather than rounding away to nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from vibe.cli.textual_ui.constants import MistralColors

# Partial fills, from one eighth to seven eighths of a row.
EIGHTHS = ["", "▁", "▂", "▃", "▄", "▅", "▆", "▇"]
FULL = "█"
SUBROWS = 8

# RED is deliberately absent: DESIGN.md reserves red for $error, and a band that looks
# like an error reads as one.
SERIES_COLOURS = [
    MistralColors.ORANGE,
    MistralColors.YELLOW,
    MistralColors.ORANGE_DARK,
    MistralColors.ORANGE_LIGHT,
]

# On a light surface the brand ramp is unreadable: #FFD800 on #F5F5F5 has almost no
# contrast. The enum has no light variant, so the light ramp is the dark one darkened by
# a fixed factor. One rule, not four invented hex values.
LIGHT_FACTOR = 0.58


@dataclass(frozen=True)
class Series:
    label: str
    values: list[Decimal]


def _darken(hex_colour: str, factor: float) -> str:
    raw = hex_colour.lstrip("#")
    channels = [int(raw[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{int(v * factor):02x}" for v in channels)


def colour_for(index: int, dark: bool = True) -> str:
    base = str(SERIES_COLOURS[index % len(SERIES_COLOURS)])
    return base if dark else _darken(base, LIGHT_FACTOR)


def group_size(days: int, width: int) -> int:
    """Days per bar, so every bar keeps at least one cell of gap beside it.

    Forty-five daily bars do not fit in eighty cells with gaps, and bars that touch
    read as one filled area rather than as separate days. Grouping adjacent days is
    the honest way to keep them apart.
    """
    if days <= 0:
        return 1
    size = 1
    while size < days and days // size * 2 - 1 > width:
        size += 1
    return size


def bar_layout(bars: int, width: int) -> tuple[int, int]:
    """Bar width and gap for `bars` columns inside `width` cells.

    Every option keeps a gap: bars that touch stop reading as separate days.
    """
    if bars <= 0:
        return 1, 1
    for bar, gap in ((6, 2), (4, 2), (3, 1), (2, 1), (1, 1)):
        if bars * (bar + gap) - gap <= width:
            return bar, gap
    return 1, 1


def _column_bands(
    values: list[Decimal], vmax: Decimal, rows: int
) -> list[tuple[int, int]]:
    """(series index, sub-rows) from the bottom up, for one day."""
    if vmax <= 0:
        return []
    total = rows * SUBROWS
    bands: list[tuple[int, int]] = []
    used = 0
    for index, value in enumerate(values):
        if value <= 0:
            continue
        units = int(Decimal(total) * value / vmax)
        # A day that cost something must show something.
        if units == 0:
            units = 1
        units = min(units, total - used)
        if units <= 0:
            break
        bands.append((index, units))
        used += units
    return bands


def render_chart(
    series: list[Series], cells_w: int, cells_h: int, dark: bool = True
) -> list[str]:
    """Return `cells_h` lines of Textual markup, top row first."""
    if not series or not series[0].values:
        return [""] * cells_h

    grouped = [
        Series(label=s.label, values=_group(s.values, group_size(len(s.values), cells_w)))
        for s in series
    ]
    series = grouped
    days = len(series[0].values)
    vmax = max((v for s in series for v in s.values), default=Decimal(0))
    bar, gap = bar_layout(days, cells_w)

    # Per day, which series owns each sub-row, bottom up.
    columns: list[list[int | None]] = []
    for day in range(days):
        stack: list[int | None] = []
        for index, units in _column_bands(
            [s.values[day] for s in series], vmax, cells_h
        ):
            stack.extend([index] * units)
        stack.extend([None] * (cells_h * SUBROWS - len(stack)))
        columns.append(stack)

    lines: list[str] = []
    for row in range(cells_h):
        # Row 0 is the top, so it covers the highest sub-rows.
        base = (cells_h - 1 - row) * SUBROWS
        parts: list[str] = []
        for day, stack in enumerate(columns):
            if day:
                parts.append(" " * gap)
            cell = stack[base : base + SUBROWS]
            filled = [index for index in cell if index is not None]
            if not filled:
                parts.append(" " * bar)
                continue
            owner = filled[0]
            glyph = FULL if len(filled) == SUBROWS else EIGHTHS[len(filled)]
            parts.append(f"[{colour_for(owner, dark)}]{glyph * bar}[/]")
        lines.append("".join(parts))
    return lines


def _group(values: list[Decimal], size: int) -> list[Decimal]:
    if size <= 1:
        return values
    return [
        sum(values[i : i + size], Decimal(0)) for i in range(0, len(values), size)
    ]


def chart_width(days: int, cells_w: int) -> int:
    """Cells the bars actually occupy, so the axis labels line up with them."""
    bars = -(-days // group_size(days, cells_w))
    bar, gap = bar_layout(bars, cells_w)
    return max(0, bars * (bar + gap) - gap)


def axis_labels(vmax: Decimal, rows: int) -> list[str]:
    """Right-aligned y labels: max at the top, zero at the bottom, midpoint between."""
    from vibe.cli.textual_ui.screens.usage.formatting import money

    if rows < 2:  # noqa: PLR2004
        return [money(vmax)]
    labels = [""] * rows
    labels[0] = money(vmax)
    labels[-1] = money(Decimal(0))
    if rows >= 3:  # noqa: PLR2004
        labels[rows // 2] = money(vmax / 2)
    width = max(len(label) for label in labels)
    return [label.rjust(width) for label in labels]
