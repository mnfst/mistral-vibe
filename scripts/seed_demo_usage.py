#!/usr/bin/env python3
"""Seed a demo project with ~45 days of fake sessions for /projects UI development.

Run: uv run python scripts/seed_demo_usage.py

Creates sessions under ~/.vibe/logs/session/ for a fake project
"seeded-project" with realistic assistant messages carrying usage/model/timestamp.
After running, /projects will show "seeded-project" with real-looking data.

All data is fake and anonymized — safe to push to public repos.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import random
from uuid import uuid4

from vibe.core.paths._vibe_home import SESSION_LOG_DIR

DEMO_CWD = "/tmp/seeded-project"
SESSION_PREFIX = "session"
DAYS = 45
SEED = 42

MODELS = [
    {"alias": "glm-5-2", "input_price": 1.4, "output_price": 4.4, "cached_price": 0.14},
    {
        "alias": "mistral-medium-3.5",
        "input_price": 1.5,
        "output_price": 7.5,
        "cached_price": 0.15,
    },
]


def _make_meta(
    session_id: str,
    start_time: str,
    end_time: str,
    cwd: str,
    model_alias: str,
    stats: dict,
    child_sessions: list[dict] | None = None,
    parent_session_id: str | None = None,
) -> dict:
    return {
        "session_id": session_id,
        "parent_session_id": parent_session_id,
        "start_time": start_time,
        "end_time": end_time,
        "git_commit": None,
        "git_branch": "main",
        "environment": {"working_directory": cwd},
        "username": "demo",
        "child_sessions": child_sessions or [],
        "loops": [],
        "title": f"Session {session_id[:8]}",
        "title_source": "auto",
        "experiments": None,
        "created_worktree": None,
        "total_messages": 0,
        "last_message_fingerprint": None,
        "tools_available": [],
        "config": {
            "active_model": model_alias,
            "models": {
                m["alias"]: {
                    "name": f"{m['alias']}-latest",
                    "provider": "mistral",
                    "alias": m["alias"],
                    "display_name": m["alias"],
                    "input_price": m["input_price"],
                    "output_price": m["output_price"],
                    "cached_input_price": m["cached_price"],
                }
                for m in MODELS
            },
        },
        "agent_profile": {"name": "default", "overrides": {}},
        "system_prompt": "",
        "stats": stats,
    }


def _make_assistant_message(
    model: str,
    timestamp: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
) -> dict:
    model_cfg = next(m for m in MODELS if m["alias"] == model)
    cached = min(cached_tokens, prompt_tokens)
    cost = (
        (prompt_tokens - cached) * model_cfg["input_price"]
        + cached * model_cfg["cached_price"]
        + completion_tokens * model_cfg["output_price"]
    ) / 1_000_000
    return {
        "role": "assistant",
        "content": "Here is the response.",
        "injected": False,
        "message_id": str(uuid4()),
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
        },
        "model": model,
        "timestamp": timestamp,
        "cost": round(cost, 6),
    }


def _make_user_message() -> dict:
    return {
        "role": "user",
        "content": "Can you help me with this?",
        "injected": False,
        "message_id": str(uuid4()),
    }


def _build_stats(requests: list[tuple[int, int, int]], model: dict) -> dict:
    total_prompt = sum(r[0] for r in requests)
    total_cached = sum(r[1] for r in requests)
    total_completion = sum(r[2] for r in requests)
    last = requests[-1] if requests else (0, 0, 0)
    return {
        "steps": len(requests),
        "session_prompt_tokens": total_prompt,
        "session_completion_tokens": total_completion,
        "session_cached_tokens": total_cached,
        "tool_calls_agreed": 0,
        "tool_calls_rejected": 0,
        "tool_calls_hook_denied": 0,
        "tool_calls_failed": 0,
        "tool_calls_succeeded": 0,
        "context_tokens": 0,
        "last_turn_prompt_tokens": last[0],
        "last_turn_completion_tokens": last[2],
        "last_turn_cached_tokens": last[1],
        "last_turn_duration": 1.5,
        "tokens_per_second": 50.0,
        "input_price_per_million": model["input_price"],
        "output_price_per_million": model["output_price"],
        "cached_input_price_per_million": model["cached_price"],
        "session_total_llm_tokens": total_prompt + total_completion,
        "last_turn_total_tokens": last[0] + last[2],
        "session_cost": 0.0,
    }


def _gen_requests(
    rng: random.Random, model: dict, num_requests: int
) -> list[tuple[int, int, int]]:
    """Generate fake request tuples: (prompt, cached, completion)."""
    requests: list[tuple[int, int, int]] = []
    for _ in range(num_requests):
        prompt = rng.randint(2000, 80000)
        cached_ratio = rng.uniform(0.0, 0.85)
        cached = int(prompt * cached_ratio)
        completion = rng.randint(50, 3000)
        requests.append((prompt, cached, completion))
    return requests


def _write_session(
    save_dir: Path,
    session_id: str,
    start: datetime,
    cwd: str,
    model: dict,
    requests: list[tuple[int, int, int]],
    child_sessions: list[dict] | None = None,
    parent_session_id: str | None = None,
) -> Path:
    timestamp_str = start.strftime("%Y%m%d_%H%M%S")
    short_id = session_id[:8]
    session_dir = save_dir / f"{SESSION_PREFIX}_{timestamp_str}_{short_id}"
    session_dir.mkdir(parents=True, exist_ok=True)

    messages: list[dict] = []
    for i, (prompt, cached, completion) in enumerate(requests):
        ts = (start + timedelta(seconds=i * 30)).isoformat()
        messages.append(_make_user_message())
        messages.append(
            _make_assistant_message(model["alias"], ts, prompt, completion, cached)
        )

    end_time = (start + timedelta(seconds=len(requests) * 30)).isoformat()
    stats = _build_stats(requests, model)
    meta = _make_meta(
        session_id=session_id,
        start_time=start.isoformat(),
        end_time=end_time,
        cwd=cwd,
        model_alias=model["alias"],
        stats=stats,
        child_sessions=child_sessions,
        parent_session_id=parent_session_id,
    )
    meta["total_messages"] = len(messages)

    (session_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    with (session_dir / "messages.jsonl").open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

    return session_dir


def _write_child_session(
    parent_dir: Path,
    child_id: str,
    child_start: datetime,
    cwd: str,
    model: dict,
    requests: list[tuple[int, int, int]],
    parent_session_id: str,
) -> None:
    child_dir_name = f"explore_{child_start.strftime('%Y%m%d_%H%M%S')}_{child_id[:8]}"
    agents_dir = parent_dir / "agents"
    agents_dir.mkdir(exist_ok=True)
    child_session_dir = agents_dir / child_dir_name
    child_session_dir.mkdir(exist_ok=True)

    messages: list[dict] = []
    for i, (prompt, cached, completion) in enumerate(requests):
        ts = (child_start + timedelta(seconds=i * 60)).isoformat()
        messages.append(_make_user_message())
        messages.append(
            _make_assistant_message(model["alias"], ts, prompt, completion, cached)
        )

    child_end = child_start + timedelta(minutes=len(requests))
    stats = _build_stats(requests, model)
    meta = _make_meta(
        session_id=child_id,
        start_time=child_start.isoformat(),
        end_time=child_end.isoformat(),
        cwd=cwd,
        model_alias=model["alias"],
        stats=stats,
        parent_session_id=parent_session_id,
    )
    meta["total_messages"] = len(messages)

    (child_session_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    with (child_session_dir / "messages.jsonl").open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def main() -> None:
    rng = random.Random(SEED)
    save_dir = SESSION_LOG_DIR.path
    save_dir.mkdir(parents=True, exist_ok=True)

    now = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
    total_sessions = 0
    total_subagents = 0
    total_requests = 0

    for day_offset in range(DAYS):
        day = now - timedelta(days=day_offset)

        # 0-3 sessions per day, weighted toward 1-2
        num_sessions = rng.choices([0, 1, 2, 3], weights=[3, 5, 3, 1])[0]
        if num_sessions == 0:
            continue

        for _ in range(num_sessions):
            session_id = str(uuid4())
            # Random time during the day
            hour = rng.randint(8, 20)
            minute = rng.randint(0, 59)
            start = day.replace(hour=hour, minute=minute, second=0, microsecond=0)

            model = rng.choice(MODELS)
            num_requests = rng.randint(1, 15)
            requests = _gen_requests(rng, model, num_requests)
            total_requests += num_requests

            # ~20% chance of spawning a subagent
            has_subagent = rng.random() < 0.2
            child_links: list[dict] = []
            if has_subagent:
                child_id = str(uuid4())
                child_start = start + timedelta(minutes=rng.randint(2, 10))
                child_dir_name = (
                    f"explore_{child_start.strftime('%Y%m%d_%H%M%S')}_{child_id[:8]}"
                )
                child_links.append({
                    "session_id": child_id,
                    "tool_call_id": f"chatcmpl-tool-{uuid4().hex[:12]}",
                    "agent": "explore",
                    "relative_path": f"agents/{child_dir_name}",
                })

            parent_dir = _write_session(
                save_dir,
                session_id,
                start,
                DEMO_CWD,
                model,
                requests,
                child_sessions=child_links,
            )
            total_sessions += 1

            if has_subagent:
                child_model = rng.choice(MODELS)
                child_requests = _gen_requests(rng, child_model, rng.randint(1, 5))
                total_requests += len(child_requests)
                _write_child_session(
                    parent_dir,
                    child_id,
                    child_start,
                    DEMO_CWD,
                    child_model,
                    child_requests,
                    session_id,
                )
                total_subagents += 1

    print(
        f"Seeded {total_sessions} sessions (+{total_subagents} subagents) "
        f"with {total_requests} requests over {DAYS} days"
    )
    print(f"Project: {DEMO_CWD}")
    print(f"Sessions written to: {save_dir}")
    print("Run /projects in vibe to see the demo data.")


if __name__ == "__main__":
    main()
