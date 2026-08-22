"""Unit tests for the usage adapter.

Pure functions, no terminal. Each test covers a shape that real data produces and that
a screen built against typical data only would get wrong.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from vibe.cli.textual_ui.screens.usage.view_model import (
    Period,
    bucket,
    request_day,
)
from vibe.core.session.usage import RequestUsage

TODAY = date(2026, 8, 22)


def _request(
    day: str | None,
    model: str = "mistral-medium-3.5",
    cost: float = 1.0,
    session: str = "s1",
) -> RequestUsage:
    return RequestUsage(
        session_id=session,
        datetime=None if day is None else f"{day}T12:00:00+00:00",
        model=model,
        prompt_tokens=100,
        completion_tokens=10,
        cached_tokens=5,
        cost=cost,
    )


def test_cost_is_decimal_not_float() -> None:
    """Costs are summed as Decimal, so a total reconciles with its parts."""
    usage = bucket([_request("2026-08-22", cost=0.1)] * 3, Period.ALL_TIME, TODAY)
    assert usage.total == Decimal("0.3")
    assert isinstance(usage.total, Decimal)


def test_undated_requests_count_but_do_not_plot() -> None:
    """A request without a timestamp still cost money."""
    usage = bucket(
        [_request("2026-08-22", cost=1.0), _request(None, cost=2.0)],
        Period.ALL_TIME,
        TODAY,
    )
    assert usage.undated == 1
    assert usage.total == Decimal("3")
    assert usage.days == [date(2026, 8, 22)]
    (_model, values), = usage.series()
    assert values == [Decimal("1")]


def test_period_window_excludes_older_requests() -> None:
    usage = bucket(
        [_request("2026-08-01", cost=5.0), _request("2026-08-20", cost=1.0)],
        Period.LAST_7_DAYS,
        TODAY,
    )
    assert usage.requests == 1
    assert usage.total == Decimal("1")


def test_period_window_spans_the_full_range_even_when_empty_at_the_edges() -> None:
    """Seven days means seven columns, whatever days happen to carry data."""
    usage = bucket([_request("2026-08-20", cost=1.0)], Period.LAST_7_DAYS, TODAY)
    assert len(usage.days) == 7
    assert usage.days[0] == date(2026, 8, 16)
    assert usage.days[-1] == TODAY


def test_calendar_gaps_render_as_zero_not_as_a_missing_column() -> None:
    """A quiet weekend must dip to zero, not be compressed out of the chart."""
    usage = bucket(
        [_request("2026-08-01", cost=1.0), _request("2026-08-04", cost=2.0)],
        Period.ALL_TIME,
        TODAY,
    )
    assert usage.days == [date(2026, 8, d) for d in (1, 2, 3, 4)]
    (_model, values), = usage.series()
    assert values == [Decimal("1"), Decimal(0), Decimal(0), Decimal("2")]


def test_models_are_ranked_by_cost_and_series_follow_that_order() -> None:
    """The colour of a chart line is the colour of the dot beside its name."""
    usage = bucket(
        [
            _request("2026-08-22", model="cheap", cost=1.0),
            _request("2026-08-22", model="dear", cost=9.0),
        ],
        Period.ALL_TIME,
        TODAY,
    )
    assert [m.model for m in usage.models] == ["dear", "cheap"]
    assert [label for label, _values in usage.series()] == ["dear", "cheap"]


def test_sessions_are_aggregated_and_dated_by_their_first_request() -> None:
    usage = bucket(
        [
            _request("2026-08-21", session="a", cost=1.0),
            _request("2026-08-22", session="a", cost=2.0),
            _request("2026-08-22", session="b", cost=4.0),
        ],
        Period.ALL_TIME,
        TODAY,
    )
    by_id = {s.session_id: s for s in usage.sessions}
    assert by_id["a"].requests == 2
    assert by_id["a"].cost == Decimal("3")
    assert by_id["a"].started == date(2026, 8, 21)


def test_empty_input_is_empty_not_a_crash() -> None:
    usage = bucket([], Period.LAST_7_DAYS, TODAY)
    assert usage.is_empty
    assert usage.days == []
    assert usage.total == Decimal(0)


def test_request_day_tolerates_a_missing_or_broken_timestamp() -> None:
    assert request_day(_request(None)) is None
    broken = RequestUsage(
        session_id="s",
        datetime="not a date",
        model="m",
        prompt_tokens=0,
        completion_tokens=0,
        cached_tokens=0,
        cost=0.0,
    )
    assert request_day(broken) is None
