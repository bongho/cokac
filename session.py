"""Session persistence — chat_id → [{id, name, created_at}]."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TypedDict

DATA_FILE = Path.home() / ".cokac" / "data" / "sessions.json"


class SessionEntry(TypedDict):
    id: str
    name: str
    created_at: float


def _load() -> dict[str, list[SessionEntry]]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict[str, list[SessionEntry]]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def save_session(chat_id: int | str, session_id: str, name: str = "") -> None:
    data = _load()
    key = str(chat_id)
    sessions = data.get(key, [])
    # 동일 id 업데이트
    for s in sessions:
        if s["id"] == session_id:
            if name:
                s["name"] = name
            return _save(data)
    sessions.append({"id": session_id, "name": name or session_id[:8], "created_at": time.time()})
    data[key] = sessions
    _save(data)


def get_sessions(chat_id: int | str) -> list[SessionEntry]:
    return _load().get(str(chat_id), [])


def get_latest_session_id(chat_id: int | str) -> str | None:
    sessions = get_sessions(chat_id)
    return sessions[-1]["id"] if sessions else None


def delete_session(chat_id: int | str, session_id: str) -> bool:
    data = _load()
    key = str(chat_id)
    before = data.get(key, [])
    after = [s for s in before if s["id"] != session_id]
    if len(before) == len(after):
        return False
    data[key] = after
    _save(data)
    return True


def set_active_session(chat_id: int | str, session_id: str) -> None:
    """Move session_id to the end (= latest)."""
    data = _load()
    key = str(chat_id)
    sessions = data.get(key, [])
    entry = next((s for s in sessions if s["id"] == session_id), None)
    if entry:
        sessions.remove(entry)
        sessions.append(entry)
        data[key] = sessions
        _save(data)
