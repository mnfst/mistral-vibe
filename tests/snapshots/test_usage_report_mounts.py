"""The report must actually mount at the bottom of the app.

Written after a KeyError got through: `_switch_from_input` looks the widget up in the
BottomApp enum by class name minus an "App" suffix, and a report class that is not
registered there crashes on mount. An earlier version of this test ran against an empty
session directory, so `_render_project_usage` returned before reaching that line and
the test passed while the feature was broken. The usage rows are injected here for
exactly that reason.
"""

from __future__ import annotations

import pytest

from tests.snapshots.base_snapshot_test_app import BaseSnapshotTestApp
from vibe.cli.textual_ui.app import BottomApp
from vibe.cli.textual_ui.screens.usage import UsageReport
from vibe.core.session.usage import RequestUsage

ROWS = [
    RequestUsage(
        session_id="s1",
        datetime="2026-08-22T10:00:00+00:00",
        model="mistral-medium-3.5",
        prompt_tokens=1000,
        completion_tokens=100,
        cached_tokens=10,
        cost=0.25,
    ),
    RequestUsage(
        session_id="s2",
        datetime="2026-08-21T10:00:00+00:00",
        model="glm-5-2",
        prompt_tokens=800,
        completion_tokens=80,
        cached_tokens=5,
        cost=0.10,
    ),
]


def test_usage_report_is_registered_as_a_bottom_app() -> None:
    assert BottomApp[UsageReport.__name__.removesuffix("App")]


@pytest.mark.asyncio
async def test_render_project_usage_mounts_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vibe.cli.textual_ui.app.aggregate_project_usage",
        lambda *_args, **_kwargs: ROWS,
    )
    app = BaseSnapshotTestApp()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.3)
        await app._render_project_usage("/tmp/demo-usage-ui")
        await pilot.pause(0.5)
        assert app.query_one(UsageReport)


@pytest.mark.asyncio
async def test_escape_closes_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vibe.cli.textual_ui.app.aggregate_project_usage",
        lambda *_args, **_kwargs: ROWS,
    )
    app = BaseSnapshotTestApp()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.3)
        await app._render_project_usage("/tmp/demo-usage-ui")
        await pilot.pause(0.5)
        assert app.query(UsageReport)
        await pilot.press("escape")
        await pilot.pause(0.5)
        assert not app.query(UsageReport)
