"""Schedule persistence — list of scheduled tasks."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import TypedDict

DATA_FILE = Path.home() / ".cokac" / "data" / "schedules.json"


class ScheduleEntry(TypedDict):
    id: str
    chat_id: str
    cron: str          # e.g. "0 9 * * *"
    prompt: str
    session_id: str    # "" = new session each run
    created_at: float
    name: str


def _load() -> list[ScheduleEntry]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save(data: list[ScheduleEntry]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def add_schedule(
    chat_id: int | str,
    cron: str,
    prompt: str,
    session_id: str = "",
    name: str = "",
) -> ScheduleEntry:
    data = _load()
    entry: ScheduleEntry = {
        "id": str(uuid.uuid4())[:8],
        "chat_id": str(chat_id),
        "cron": cron,
        "prompt": prompt,
        "session_id": session_id,
        "created_at": time.time(),
        "name": name or prompt[:20],
    }
    data.append(entry)
    _save(data)
    return entry


def get_schedules(chat_id: int | str | None = None) -> list[ScheduleEntry]:
    data = _load()
    if chat_id is None:
        return data
    return [s for s in data if s["chat_id"] == str(chat_id)]


def delete_schedule(schedule_id: str) -> bool:
    data = _load()
    before = len(data)
    data = [s for s in data if s["id"] != schedule_id]
    if len(data) == before:
        return False
    _save(data)
    return True


def parse_cron(cron_str: str) -> dict:
    """Convert '0 9 * * *' → APScheduler CronTrigger kwargs."""
    parts = cron_str.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron: '{cron_str}' (expected 5 fields)")
    minute, hour, day, month, day_of_week = parts
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }
