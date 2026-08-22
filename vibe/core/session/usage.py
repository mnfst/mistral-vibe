from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from vibe.core.session.session_index import (
    MESSAGES_FILENAME,
    METADATA_FILENAME,
    SessionIndex,
    SessionInfo,
)
from vibe.utils.io import read_safe
from vibe.utils.pricing import session_token_cost
from vibe.utils.session_id import shorten_session_id

__all__ = [
    "ProjectInfo",
    "RequestUsage",
    "aggregate_project_usage",
    "list_projects",
    "model_pricing_map",
]

# (input_price, output_price, cached_input_price) per million tokens, keyed by alias.
PricingMap = dict[str, tuple[float, float, float | None]]


@dataclass(frozen=True)
class ProjectInfo:
    """A unique project path discovered across sessions."""

    cwd: str
    session_count: int


@dataclass(frozen=True)
class RequestUsage:
    """Per-LLM-request usage data extracted from a single assistant message."""

    session_id: str
    datetime: str | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cost: float


def _load_raw_metadata(session_dir: Path) -> dict[str, Any] | None:
    try:
        metadata = json.loads(read_safe(session_dir / METADATA_FILENAME).text)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    return metadata


def _extract_model_alias(metadata: dict[str, Any]) -> str | None:
    """Extract the model alias from a session's meta.json config snapshot."""
    config = metadata.get("config")
    if not isinstance(config, dict):
        return None
    active_model = config.get("active_model")
    if isinstance(active_model, str):
        return active_model
    if isinstance(active_model, dict):
        return active_model.get("alias")
    return None


def model_pricing_map() -> PricingMap:
    """Build a model-alias → pricing map from the live config.

    Single source of truth: reads the current ``config.toml`` plus built-in
    default models via the standard config orchestrator.
    """
    import asyncio

    from vibe.core.config.default_orchestrator import build_default_orchestrator

    async def _build() -> PricingMap:
        orchestrator = await build_default_orchestrator(require_api_key=False)
        return {
            alias: (model.input_price, model.output_price, model.cached_input_price)
            for alias, model in orchestrator.config.models.items()
        }

    try:
        return asyncio.run(_build())
    except Exception:
        return {}


def _lookup_pricing(
    pricing_map: PricingMap, model_alias: str | None
) -> tuple[float, float, float | None]:
    """Look up pricing for a model alias from the live config pricing map."""
    if model_alias and model_alias in pricing_map:
        return pricing_map[model_alias]
    return 0.0, 0.0, None


def _parse_assistant_usage(
    session_dir: Path,
    session_id: str,
    start_time: str | None,
    metadata: dict[str, Any],
    pricing_map: PricingMap,
) -> list[RequestUsage]:
    """Parse messages.jsonl and extract per-request usage from assistant messages.

    Falls back to a single synthetic request from meta.json stats when no
    assistant messages carry usage data (old sessions predating the schema change).
    """
    messages_path = session_dir / MESSAGES_FILENAME
    try:
        content = read_safe(messages_path).text
    except OSError:
        return []

    requests: list[RequestUsage] = []
    for line in content.split("\n"):
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue

        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue

        model_alias = msg.get("model") or _extract_model_alias(metadata)
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cached_tokens = usage.get("cached_tokens", 0)
        stored_cost = msg.get("cost")
        if stored_cost is not None:
            cost = stored_cost
        else:
            input_price, output_price, cached_price = _lookup_pricing(
                pricing_map, model_alias
            )
            cost = session_token_cost(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                input_price_per_million=input_price,
                output_price_per_million=output_price,
                cached_input_price_per_million=cached_price,
            )
        requests.append(
            RequestUsage(
                session_id=session_id,
                datetime=msg.get("timestamp") or start_time,
                model=model_alias or "unknown",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                cost=cost,
            )
        )

    if not requests:
        seeded = _seed_from_stats(session_id, start_time, metadata, pricing_map)
        if seeded is not None:
            requests.append(seeded)

    return requests


def _seed_from_stats(
    session_id: str,
    start_time: str | None,
    metadata: dict[str, Any],
    pricing_map: PricingMap,
) -> RequestUsage | None:
    """Synthesize a single request from meta.json cumulative stats.

    Used as a fallback for old sessions whose messages.jsonl predates the
    usage/model/timestamp schema change. The session's stats and live config
    pricing produce one aggregate request row.
    """
    stats = metadata.get("stats")
    if not isinstance(stats, dict):
        return None

    prompt_tokens = stats.get("session_prompt_tokens", 0)
    completion_tokens = stats.get("session_completion_tokens", 0)
    cached_tokens = stats.get("session_cached_tokens", 0)
    if prompt_tokens == 0 and completion_tokens == 0:
        return None

    model_alias = _extract_model_alias(metadata)
    input_price, output_price, cached_price = _lookup_pricing(pricing_map, model_alias)
    cost = session_token_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        input_price_per_million=input_price,
        output_price_per_million=output_price,
        cached_input_price_per_million=cached_price,
    )
    return RequestUsage(
        session_id=session_id,
        datetime=start_time,
        model=model_alias or "unknown",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        cost=cost,
    )


def _find_child_session_dirs(session_dir: Path) -> list[Path]:
    """Find child session directories under agents/."""
    agents_dir = session_dir / "agents"
    if not agents_dir.is_dir():
        return []
    return [
        d
        for d in agents_dir.iterdir()
        if d.is_dir() and (d / METADATA_FILENAME).is_file()
    ]


def _collect_session_requests(
    session_dir: Path, pricing_map: PricingMap
) -> list[RequestUsage]:
    """Collect per-request usage for a session directory, including child sessions."""
    metadata = _load_raw_metadata(session_dir)
    if metadata is None:
        return []

    session_id = metadata.get("session_id", session_dir.name)
    start_time = metadata.get("start_time")

    requests = _parse_assistant_usage(
        session_dir, session_id, start_time, metadata, pricing_map
    )

    for child_dir in _find_child_session_dirs(session_dir):
        child_metadata = _load_raw_metadata(child_dir)
        if child_metadata is None:
            continue
        child_id = child_metadata.get("session_id", child_dir.name)
        child_start = child_metadata.get("start_time")
        requests.extend(
            _parse_assistant_usage(
                child_dir, child_id, child_start, child_metadata, pricing_map
            )
        )

    return requests


def list_projects(save_dir: Path, session_prefix: str = "session") -> list[ProjectInfo]:
    """List all unique project paths across all sessions in the save directory.

    Returns projects sorted by session count (most sessions first).
    """
    index = SessionIndex(save_dir, session_prefix)
    all_sessions: list[SessionInfo] = index.list()
    cwd_counts: dict[str, int] = {}
    for info in all_sessions:
        cwd = info["cwd"]
        if not cwd:
            continue
        cwd_counts[cwd] = cwd_counts.get(cwd, 0) + 1
    return [
        ProjectInfo(cwd=cwd, session_count=count)
        for cwd, count in sorted(
            cwd_counts.items(), key=lambda item: item[1], reverse=True
        )
    ]


def aggregate_project_usage(
    save_dir: Path, cwd: str, session_prefix: str = "session"
) -> list[RequestUsage]:
    """Aggregate per-request usage for all sessions belonging to a project (cwd).

    Includes child sessions (subagents) under each session's agents/ directory.
    Pricing is resolved from the live config (config.toml + built-in defaults).
    Returns requests sorted by datetime (oldest first).
    """
    pricing_map = model_pricing_map()
    index = SessionIndex(save_dir, session_prefix)
    project_sessions = index.list(cwd=cwd)

    results: list[RequestUsage] = []
    for info in project_sessions:
        session_id = info["session_id"]
        short_id = shorten_session_id(session_id)
        session_dirs = list(save_dir.glob(f"{session_prefix}_*_{short_id}"))
        for session_dir in session_dirs:
            results.extend(_collect_session_requests(session_dir, pricing_map))

    results.sort(key=lambda r: r.datetime or "")
    return results
