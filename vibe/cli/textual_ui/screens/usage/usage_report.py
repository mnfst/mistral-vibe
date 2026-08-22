"""Per-project inference cost, rendered inline in the conversation.

It is a block in the stream rather than a modal, so the report stays in the transcript
and can be scrolled back to, and so the terminal never has a window laid over it.

The period is switched by clicking a label instead of by a key binding: the chat input
keeps keyboard focus, so a keystroke here would land in the prompt.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.widgets import Static

from vibe.cli.textual_ui.constants import MistralColors

from vibe.cli.textual_ui.screens.usage.chart import (
    Series,
    axis_labels,
    colour_for,
    render_chart,
)
from vibe.cli.textual_ui.screens.usage.formatting import (
    compact_int,
    money,
    percent,
    short_day,
)
from vibe.cli.textual_ui.screens.usage.view_model import (
    PERIODS,
    ModelBucket,
    Period,
    ProjectUsage,
    RequestLike,
    SessionBucket,
    bucket,
)

CHART_ROWS = 5
CHART_MIN_COLS = 24
SESSION_ID_WIDTH = 8
# An inline block must not run for pages. Beyond this the tail is summarised.
MAX_SESSION_ROWS = 8

_STYLES = (Path(__file__).parent / "usage_report.tcss").read_text()


class PeriodTab(Static):
    """One clickable period label."""

    def __init__(self, period: Period, active: bool) -> None:
        markup = (
            f"[b {MistralColors.ORANGE}]{period.value}[/]"
            if active
            else f"[$text-muted]{period.value}[/]"
        )
        super().__init__(Content.from_markup(markup), classes="period-tab")
        self.period = period

    def on_click(self) -> None:
        report = self.ancestors_with_self
        for node in report:
            if isinstance(node, UsageReport):
                node.set_period(self.period)
                return


class UsageReport(Vertical):
    """The report block. Mounted in the chat stream like any other message."""

    DEFAULT_CSS = _STYLES

    def __init__(
        self,
        cwd: str,
        requests: list[RequestLike],
        today: date | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._cwd = cwd
        self._requests = requests
        self._today = today or date.today()
        self._period = Period.LAST_7_DAYS
        self._usage = bucket(self._requests, self._period, self._today)

    # -- state ---------------------------------------------------------------

    @property
    def _dark(self) -> bool:
        theme = self.app.current_theme
        return True if theme is None else theme.dark

    def set_period(self, period: Period) -> None:
        if period is self._period:
            return
        self._period = period
        self._usage = bucket(self._requests, period, self._today)
        self.call_next(self._rerender)

    async def _rerender(self) -> None:
        await self.recompose()
        # recompose does not re-fire on_mount, and the chart needs a resolved width.
        self.call_after_refresh(self._draw_chart)

    # -- layout ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        usage = self._usage
        name = Path(self._cwd).name or self._cwd

        with Horizontal(classes="usage-header"):
            yield Static(
                Content.from_markup(f"[b {MistralColors.ORANGE}]{name}[/]"),
                classes="usage-title",
            )
            yield Static("", classes="usage-spacer")
            yield Static(
                Content.from_markup(
                    f"[$foreground]{money(usage.total)}[/] "
                    f"[$text-muted]· {usage.period.value}[/]"
                ),
                classes="usage-total",
            )
        yield Static(
            Content.from_markup(f"[$text-muted]{self._cwd}[/]"), classes="usage-path"
        )

        with Horizontal(classes="period-row"):
            for index, period in enumerate(PERIODS):
                if index:
                    yield Static(
                        Content.from_markup("[$text-muted] · [/]"), classes="period-sep"
                    )
                yield PeriodTab(period, period is self._period)

        if usage.is_empty:
            yield Static(
                Content.from_markup("[$text-muted]No request in this period.[/]"),
                classes="usage-empty",
            )
            return

        if usage.days:
            yield Static(
                Content.from_markup("[$text-muted]Cost per day[/]"),
                classes="usage-section",
            )
            with Horizontal(classes="chart-row") as row:
                row.styles.height = CHART_ROWS
                yield Static(id="chart-axis", classes="chart-axis")
                yield Static(id="chart-plot", classes="chart-plot")
            with Horizontal(classes="chart-xaxis"):
                yield Static("", id="chart-xaxis-gutter")
                yield Static(id="chart-x-first", classes="chart-x-label")
                yield Static("", classes="usage-spacer")
                yield Static(id="chart-x-mid", classes="chart-x-label")
                yield Static("", classes="usage-spacer")
                yield Static(id="chart-x-last", classes="chart-x-label")

        if usage.undated:
            yield Static(
                Content.from_markup(
                    f"[$text-muted]{usage.undated} "
                    f"request{'s' if usage.undated != 1 else ''} without a date are "
                    "counted in the totals but not on the chart.[/]"
                ),
                classes="usage-note",
            )

        yield Static(
            Content.from_markup(f"[$text-muted]{_plural(len(usage.models), 'model')}[/]"),
            classes="usage-section",
        )
        for index, model in enumerate(usage.models):
            yield from self._model_rows(model, usage.total, index)

        shown = usage.sessions[:MAX_SESSION_ROWS]
        yield Static(
            Content.from_markup(
                f"[$text-muted]{_plural(len(usage.sessions), 'session')}[/]"
            ),
            classes="usage-section",
        )
        for session in shown:
            yield self._session_row(session)
        hidden = len(usage.sessions) - len(shown)
        if hidden > 0:
            yield Static(
                Content.from_markup(f"[$text-muted]and {hidden} more[/]"),
                classes="session-row",
            )

    def _model_rows(
        self, model: ModelBucket, total: Decimal, index: int
    ) -> ComposeResult:
        with Horizontal(classes="model-row"):
            yield Static(
                Content.from_markup(
                    f"[{colour_for(index, self._dark)}]●[/] "
                    f"[$foreground]{model.model}[/]"
                ),
                classes="model-name",
            )
            yield Static("", classes="usage-spacer")
            yield Static(
                Content.from_markup(
                    f"[$foreground]{money(model.cost)}[/]   "
                    f"[$text-muted]{percent(model.cost, total):>6}[/]"
                ),
                classes="model-cost",
            )
        yield Static(
            Content.from_markup(
                f"[$text-muted]{model.requests} requests · "
                f"in {compact_int(model.prompt_tokens)} · "
                f"out {compact_int(model.completion_tokens)} · "
                f"cached {compact_int(model.cached_tokens)}[/]"
            ),
            classes="model-meta",
        )

    def _session_row(self, session: SessionBucket) -> Static:
        started = short_day(session.started) if session.started else "—"
        return Static(
            Content.from_markup(
                f"[$text-muted]{session.session_id[:SESSION_ID_WIDTH]}  "
                f"{started:>7}  {session.requests:>4} req[/]  "
                f"[$foreground]{money(session.cost):>9}[/]"
            ),
            classes="session-row",
        )

    # -- chart -----------------------------------------------------------------

    def on_mount(self) -> None:
        self.call_after_refresh(self._draw_chart)

    def on_resize(self) -> None:
        self._draw_chart()

    def _draw_chart(self) -> None:
        try:
            plot = self.query_one("#chart-plot", Static)
            axis = self.query_one("#chart-axis", Static)
            gutter_widget = self.query_one("#chart-xaxis-gutter", Static)
            x_first = self.query_one("#chart-x-first", Static)
            x_mid = self.query_one("#chart-x-mid", Static)
            x_last = self.query_one("#chart-x-last", Static)
        except Exception:
            return

        usage = self._usage
        if not usage.days:
            return
        # A zero width means layout has not settled: retry rather than guess, because
        # estimating from the terminal width overran the plot and clipped the axis.
        if not plot.size.width:
            self.call_after_refresh(self._draw_chart)
            return

        series = [Series(label=name, values=values) for name, values in usage.series()]
        cols = max(CHART_MIN_COLS, plot.size.width)
        vmax = max((v for s in series for v in s.values), default=Decimal(0))

        labels = axis_labels(vmax, CHART_ROWS)
        axis.update(Content("\n".join(labels)))
        gutter_widget.styles.width = len(labels[0]) + 1
        plot.update(
            Content.from_markup(
                "\n".join(render_chart(series, cols, CHART_ROWS, self._dark))
            )
        )
        first, middle, last = _x_labels(usage.days)
        x_first.update(Content.from_markup(f"[$text-muted]{first}[/]"))
        x_mid.update(Content.from_markup(f"[$text-muted]{middle}[/]"))
        x_last.update(Content.from_markup(f"[$text-muted]{last}[/]"))


def _x_labels(days: list[date]) -> tuple[str, str, str]:
    """First, middle and last date, placed by flexible spacers rather than by counting
    characters, which is what previously pushed the last date onto a clipped line."""
    if len(days) == 1:
        return "", short_day(days[0]), ""
    if len(days) == 2:  # noqa: PLR2004
        return short_day(days[0]), "", short_day(days[-1])
    return short_day(days[0]), short_day(days[len(days) // 2]), short_day(days[-1])


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


__all__ = ["UsageReport"]
