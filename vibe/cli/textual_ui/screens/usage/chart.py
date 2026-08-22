"""Multi-series line chart in braille.

Reuses `vibe.cli.textual_ui.widgets.braille_renderer.render_braille`, the same primitive
the mascot is drawn with. One character cell holds a 2x4 dot grid, so a chart 46 cells wide
by 5 cells tall is a 92x20 dot canvas, which is plenty for 7 or 30 days.

Series are drawn back to front. Where two series land in the same cell, the dots merge and
the cell takes the colour of the earlier series, which is the more expensive one because
callers pass them sorted by cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from vibe.cli.textual_ui.constants import MistralColors
from vibe.cli.textual_ui.widgets.braille_renderer import render_braille

BRAILLE_BASE = 0x2800

# The brand ramp, ordered so adjacent series stay distinguishable on a dim terminal.
# RED is deliberately absent: DESIGN.md section 1 reserves red for $error, and a series
# that looks like an error reads as one.
SERIES_COLOURS = [
    MistralColors.ORANGE,
    MistralColors.YELLOW,
    MistralColors.ORANGE_DARK,
    MistralColors.ORANGE_LIGHT,
]


@dataclass(frozen=True)
class Series:
    label: str
    values: list[Decimal]


# On a light surface the brand ramp is unreadable: #FFD800 on #F5F5F5 has almost no
# contrast. The enum has no light variant, so the light ramp is derived from the dark one
# by a fixed darkening factor. One rule, not four invented hex values.
LIGHT_FACTOR = 0.58


def _darken(hex_colour: str, factor: float) -> str:
    raw = hex_colour.lstrip("#")
    channels = [int(raw[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{int(v * factor):02x}" for v in channels)


def colour_for(index: int, dark: bool = True) -> str:
    base = str(SERIES_COLOURS[index % len(SERIES_COLOURS)])
    return base if dark else _darken(base, LIGHT_FACTOR)


def _line(x0: int, y0: int, x1: int, y1: int) -> set[complex]:
    """Bresenham. A day-to-day change has to render as a continuous stroke.

    The first attempt filled only a vertical bar at the midpoint of each pair, which
    produced a field of dotted columns instead of a line. Seven days spread over ninety
    dot columns leaves too much empty space for anything less than a real rasteriser.
    """
    dots: set[complex] = set()
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        dots.add(complex(x0, y0))
        if x0 == x1 and y0 == y1:
            return dots
        err2 = 2 * err
        if err2 >= dy:
            err += dy
            x0 += sx
        if err2 <= dx:
            err += dx
            y0 += sy


def _dots_for(values: list[Decimal], vmax: Decimal, dots_w: int, dots_h: int) -> set[complex]:
    if not values or vmax <= 0:
        return set()
    n = len(values)
    if n == 1:
        # One measurement is not a line. Draw a short plateau at the centre so the value
        # is visible; a single dot at the left edge reads as an empty chart.
        ratio = float(values[0]) / float(vmax)
        y = max(0, min(dots_h - 1, (dots_h - 1) - round(ratio * (dots_h - 1))))
        mid = dots_w // 2
        span = max(2, dots_w // 12)
        return {complex(x, y) for x in range(mid - span, mid + span + 1)}

    points: list[tuple[int, int]] = []
    for i, value in enumerate(values):
        x = 0 if n == 1 else round(i * (dots_w - 1) / (n - 1))
        ratio = float(value) / float(vmax)
        y = (dots_h - 1) - round(ratio * (dots_h - 1))
        points.append((x, max(0, min(dots_h - 1, y))))

    dots: set[complex] = set()
    for index, (x, y) in enumerate(points):
        dots.add(complex(x, y))
        if index + 1 < len(points):
            nx, ny = points[index + 1]
            dots |= _line(x, y, nx, ny)
    return dots


def _bits(char: str) -> int:
    return 0 if char == " " else ord(char) - BRAILLE_BASE


def render_chart(
    series: list[Series], cells_w: int, cells_h: int, dark: bool = True
) -> list[str]:
    """Return `cells_h` lines of Textual markup, one per row of the plot area."""
    dots_w, dots_h = cells_w * 2, cells_h * 4
    vmax = max(
        (value for s in series for value in s.values),
        default=Decimal(0),
    )

    grids: list[list[str]] = []
    for s in series:
        raw = render_braille(_dots_for(s.values, vmax, dots_w, dots_h), dots_w, dots_h)
        grids.append([row.ljust(cells_w) for row in raw.split("\n")])

    lines: list[str] = []
    for row in range(cells_h):
        out: list[str] = []
        for col in range(cells_w):
            merged = 0
            owner = -1
            for index, grid in enumerate(grids):
                bits = _bits(grid[row][col]) if row < len(grid) else 0
                if bits:
                    merged |= bits
                    if owner < 0:
                        owner = index
            if not merged:
                out.append(" ")
                continue
            out.append(f"[{colour_for(owner, dark)}]{chr(BRAILLE_BASE + merged)}[/]")
        lines.append("".join(out))
    return lines


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
