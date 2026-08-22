"""Snapshot matrix for the usage screen.

A terminal design fails on axes a single screenshot cannot show: theme class, terminal
width and terminal height. Those are this suite's parameters, run against a fixed
request list so the images never move on their own.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from textual.app import App
from textual.pilot import Pilot

from tests.snapshots.snap_compare import SnapCompare
from textual.containers import VerticalScroll

from vibe.cli.textual_ui.screens.usage import UsageReport
from vibe.core.session.usage import RequestUsage

TODAY = date(2026, 8, 22)
CWD = "/tmp/demo-usage-ui"

MODELS = [
    ("mistral-medium-3.5", 0.052, 41_000, 900, 14_000),
    ("glm-5-2", 0.031, 33_000, 640, 9_500),
]


def _fixture() -> list[RequestUsage]:
    """Thirty days, two models, one quiet weekend, one request with no timestamp."""
    rows: list[RequestUsage] = []
    for offset in range(30):
        day = TODAY - timedelta(days=offset)
        if day.weekday() >= 5:  # noqa: PLR2004
            continue
        for index, (model, unit, prompt, completion, cached) in enumerate(MODELS):
            for repeat in range(2 + (offset + index) % 3):
                rows.append(
                    RequestUsage(
                        session_id=f"{day:%Y%m%d}{index}{repeat}",
                        datetime=f"{day.isoformat()}T1{repeat}:00:00+00:00",
                        model=model,
                        prompt_tokens=prompt + repeat * 700,
                        completion_tokens=completion + repeat * 40,
                        cached_tokens=cached,
                        cost=unit * (1 + repeat * 0.4),
                    )
                )
    rows.append(
        RequestUsage(
            session_id="undated",
            datetime=None,
            model=MODELS[0][0],
            prompt_tokens=1_000,
            completion_tokens=50,
            cached_tokens=0,
            cost=0.01,
        )
    )
    return rows


class UsageScreenTestApp(App[None]):
    """Bare host: it paints nothing, so the screen is judged on its own."""

    CSS = "Screen { background: transparent; }"
    THEME = "textual-dark"

    def compose(self):
        with VerticalScroll():
            yield UsageReport(cwd=CWD, requests=_fixture(), today=TODAY)

    def on_mount(self) -> None:
        self.theme = self.THEME


class UsageScreenLightTestApp(UsageScreenTestApp):
    THEME = "textual-light"


class UsageScreenAnsiTestApp(UsageScreenTestApp):
    THEME = "ansi-dark"


class UsageScreenEmptyTestApp(UsageScreenTestApp):
    def compose(self):
        with VerticalScroll():
            yield UsageReport(cwd=CWD, requests=[], today=TODAY)


def _settle(presses: tuple[str, ...] = ()):
    async def run_before(pilot: Pilot) -> None:
        await pilot.pause(0.3)
        for key in presses:
            await pilot.press(key)
            await pilot.pause(0.3)
        # The chart is drawn after layout resolves, so give that pass time to land.
        await pilot.pause(0.3)

    return run_before


MODULE = "test_ui_snapshot_usage_screen.py"


@pytest.mark.parametrize(
    ("app", "size"),
    [
        (f"{MODULE}:UsageScreenTestApp", (80, 24)),
        (f"{MODULE}:UsageScreenTestApp", (100, 32)),
        (f"{MODULE}:UsageScreenTestApp", (120, 36)),
        (f"{MODULE}:UsageScreenLightTestApp", (100, 32)),
        (f"{MODULE}:UsageScreenAnsiTestApp", (100, 32)),
    ],
)
def test_snapshot_usage_matrix(
    snap_compare: SnapCompare, app: str, size: tuple[int, int]
) -> None:
    assert snap_compare(app, terminal_size=size, run_before=_settle())


def test_snapshot_usage_empty(snap_compare: SnapCompare) -> None:
    assert snap_compare(
        f"{MODULE}:UsageScreenEmptyTestApp",
        terminal_size=(100, 32),
        run_before=_settle(),
    )
