"""Background task manager — one Claude task per chat_id."""
from __future__ import annotations

import asyncio
import time

_tasks: dict[int, asyncio.Task] = {}
_start_times: dict[int, float] = {}


def start_task(chat_id: int, coro) -> bool:
    """Create and register a background task. Returns False if already running."""
    existing = _tasks.get(chat_id)
    if existing and not existing.done():
        return False
    task = asyncio.get_event_loop().create_task(coro)
    _tasks[chat_id] = task
    _start_times[chat_id] = time.monotonic()
    return True


def cancel_task(chat_id: int) -> bool:
    """Cancel the running task. Returns True if a task was cancelled."""
    task = _tasks.get(chat_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def is_running(chat_id: int) -> bool:
    task = _tasks.get(chat_id)
    return task is not None and not task.done()


def elapsed_seconds(chat_id: int) -> float | None:
    if not is_running(chat_id):
        return None
    return time.monotonic() - _start_times.get(chat_id, time.monotonic())
