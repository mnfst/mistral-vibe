"""Adapter over ``vibe.core.session.usage``.

The only module in this package that knows about ``RequestUsage``. It is pure, so the
money arithmetic and the period logic are unit tested without a terminal.

Four rules, each for a reason visible in real data:

1. ``cost`` becomes ``Decimal`` at the boundary. The storage layer reports a float, and
   summing a thousand floats into a figure someone will treat as a bill produces a number
   that does not reconcile.
2. ``datetime`` may be ``None``. Those requests cannot be placed on a day, so they are
   absent from the chart, but they still cost money, so they stay in the totals. The
   count is reported and the screen states it.
3. Days with no request are still days. The chart walks the calendar range rather than
   the set of days present, so a quiet weekend dips to zero instead of being compressed
   out of existence.
4. ``today`` is injected. A view that reads the wall clock cannot be snapshotted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol



class RequestLike(Protocol):
    """The shape of one recorded request.

    Declared structurally rather than imported, so the terminal layer keeps no
    dependency on vibe.core. `RequestUsage` satisfies it as it stands.
    """

    session_id: str
    datetime: str | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cost: float


class Period(StrEnum):
    LAST_7_DAYS = "Last 7 days"
    LAST_30_DAYS = "Last 30 days"
    ALL_TIME = "All time"


PERIODS: list[Period] = [Period.LAST_7_DAYS, Period.LAST_30_DAYS, Period.ALL_TIME]

_PERIOD_SPAN = {Period.LAST_7_DAYS: 7, Period.LAST_30_DAYS: 30}


@dataclass(frozen=True)
class ModelBucket:
    model: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cost: Decimal


@dataclass(frozen=True)
class SessionBucket:
    session_id: str
    started: date | None
    requests: int
    cost: Decimal


@dataclass(frozen=True)
class ProjectUsage:
    period: Period
    days: list[date]
    models: list[ModelBucket]
    sessions: list[SessionBucket]
    total: Decimal
    requests: int
    undated: int
    _by_day: dict[tuple[date, str], Decimal]

    @property
    def is_empty(self) -> bool:
        return self.requests == 0

    def series(self) -> list[tuple[str, list[Decimal]]]:
        """One entry per model, cost per day, aligned on ``self.days``.

        Ordered like ``self.models``, so the colour a model gets in the chart is the
        colour of the dot next to its name in the list below.
        """
        return [
            (
                bucket.model,
                [self._by_day.get((day, bucket.model), Decimal(0)) for day in self.days],
            )
            for bucket in self.models
        ]


def request_day(request: RequestLike) -> date | None:
    """Local calendar day of a request, or ``None`` when it carries no timestamp.

    Timestamps are stored as UTC ISO strings with an offset. Converting to local time
    before taking the date keeps a 23:30 request off tomorrow's column.
    """
    if not request.datetime:
        return None
    try:
        parsed = datetime.fromisoformat(request.datetime)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.date()


def _calendar(period: Period, dated: list[date], today: date) -> list[date]:
    if not dated:
        return []
    span = _PERIOD_SPAN.get(period)
    if span is None:
        start, end = min(dated), max(dated)
    else:
        start, end = today - timedelta(days=span - 1), today
    if end < start:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def bucket(
    requests: list[RequestLike], period: Period, today: date
) -> ProjectUsage:
    """Fold a flat request list into everything the screen renders."""
    span = _PERIOD_SPAN.get(period)
    cutoff = None if span is None else today - timedelta(days=span - 1)

    kept: list[tuple[RequestLike, date | None, Decimal]] = []
    for request in requests:
        day = request_day(request)
        if cutoff is not None and (day is None or day < cutoff or day > today):
            continue
        kept.append((request, day, Decimal(str(request.cost))))

    models: dict[str, dict] = {}
    sessions: dict[str, dict] = {}
    by_day: dict[tuple[date, str], Decimal] = defaultdict(Decimal)
    total = Decimal(0)
    undated = 0

    for request, day, cost in kept:
        total += cost
        entry = models.setdefault(
            request.model,
            {"requests": 0, "prompt": 0, "completion": 0, "cached": 0, "cost": Decimal(0)},
        )
        entry["requests"] += 1
        entry["prompt"] += request.prompt_tokens
        entry["completion"] += request.completion_tokens
        entry["cached"] += request.cached_tokens
        entry["cost"] += cost

        session = sessions.setdefault(
            request.session_id, {"requests": 0, "cost": Decimal(0), "started": day}
        )
        session["requests"] += 1
        session["cost"] += cost
        if day is not None and (
            session["started"] is None or day < session["started"]
        ):
            session["started"] = day

        if day is None:
            undated += 1
        else:
            by_day[(day, request.model)] += cost

    model_buckets = sorted(
        (
            ModelBucket(
                model=name,
                requests=v["requests"],
                prompt_tokens=v["prompt"],
                completion_tokens=v["completion"],
                cached_tokens=v["cached"],
                cost=v["cost"],
            )
            for name, v in models.items()
        ),
        key=lambda b: b.cost,
        reverse=True,
    )
    session_buckets = sorted(
        (
            SessionBucket(
                session_id=sid,
                started=v["started"],
                requests=v["requests"],
                cost=v["cost"],
            )
            for sid, v in sessions.items()
        ),
        key=lambda b: (b.started or date.min, b.cost),
        reverse=True,
    )

    return ProjectUsage(
        period=period,
        days=_calendar(period, [d for _r, d, _c in kept if d is not None], today),
        models=model_buckets,
        sessions=session_buckets,
        total=total,
        requests=len(kept),
        undated=undated,
        _by_day=dict(by_day),
    )
