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

__all__ = ["ProjectInfo", "RequestUsage", "aggregate_project_usage", "list_projects"]


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


def _extract_pricing(metadata: dict[str, Any]) -> tuple[float, float, float | None]:
    """Extract (input_price, output_price, cached_input_price) from meta.json stats."""
    stats = metadata.get("stats")
    if not isinstance(stats, dict):
        return 0.0, 0.0, None
    return (
        stats.get("input_price_per_million", 0.0),
        stats.get("output_price_per_million", 0.0),
        stats.get("cached_input_price_per_million"),
    )


def _lookup_model_pricing(
    metadata: dict[str, Any], model_alias: str | None
) -> tuple[float, float, float | None]:
    """Look up pricing for a model from the config snapshot in meta.json.

    Falls back to the session-level stats pricing if the model is not found
    or no alias is provided.
    """
    default_pricing = _extract_pricing(metadata)
    if model_alias is None:
        return default_pricing

    config = metadata.get("config")
    if not isinstance(config, dict):
        return default_pricing

    models = config.get("models")
    if not isinstance(models, dict):
        return default_pricing

    model_entry = models.get(model_alias)
    if not isinstance(model_entry, dict):
        return default_pricing

    return (
        model_entry.get("input_price", default_pricing[0]),
        model_entry.get("output_price", default_pricing[1]),
        model_entry.get("cached_input_price", default_pricing[2]),
    )


def _parse_assistant_usage(
    session_dir: Path, session_id: str, start_time: str | None, metadata: dict[str, Any]
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
        input_price, output_price, cached_price = _lookup_model_pricing(
            metadata, model_alias
        )
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cached_tokens = usage.get("cached_tokens", 0)
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
        seeded = _seed_from_stats(session_id, start_time, metadata)
        if seeded is not None:
            requests.append(seeded)

    return requests


def _seed_from_stats(
    session_id: str, start_time: str | None, metadata: dict[str, Any]
) -> RequestUsage | None:
    """Synthesize a single request from meta.json cumulative stats.

    Used as a fallback for old sessions whose messages.jsonl predates the
    usage/model/timestamp schema change. The session's stats and stored
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
    input_price, output_price, cached_price = _lookup_model_pricing(
        metadata, model_alias
    )
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


def _collect_session_requests(session_dir: Path) -> list[RequestUsage]:
    """Collect per-request usage for a session directory, including child sessions."""
    metadata = _load_raw_metadata(session_dir)
    if metadata is None:
        return []

    session_id = metadata.get("session_id", session_dir.name)
    start_time = metadata.get("start_time")

    requests = _parse_assistant_usage(session_dir, session_id, start_time, metadata)

    for child_dir in _find_child_session_dirs(session_dir):
        child_metadata = _load_raw_metadata(child_dir)
        if child_metadata is None:
            continue
        child_id = child_metadata.get("session_id", child_dir.name)
        child_start = child_metadata.get("start_time")
        requests.extend(
            _parse_assistant_usage(child_dir, child_id, child_start, child_metadata)
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
    Returns requests sorted by datetime (oldest first).
    """
    index = SessionIndex(save_dir, session_prefix)
    project_sessions = index.list(cwd=cwd)

    results: list[RequestUsage] = []
    for info in project_sessions:
        session_id = info["session_id"]
        short_id = shorten_session_id(session_id)
        session_dirs = list(save_dir.glob(f"{session_prefix}_*_{short_id}"))
        for session_dir in session_dirs:
            results.extend(_collect_session_requests(session_dir))

    results.sort(key=lambda r: r.datetime or "")
    return results
