"""Named workspace store — per-chat project context presets."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TypedDict

DATA_FILE = Path.home() / ".cokac" / "data" / "workspaces.json"


class WorkspaceEntry(TypedDict):
    name: str
    work_dir: str
    agent_hint: str
    allowed_tools: str
    created_at: float


def _load() -> dict[str, list[WorkspaceEntry]]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def list_workspaces(chat_id: int | str) -> list[WorkspaceEntry]:
    return _load().get(str(chat_id), [])


def get_workspace(chat_id: int | str, name: str) -> WorkspaceEntry | None:
    return next(
        (w for w in list_workspaces(chat_id) if w["name"].lower() == name.lower()), None
    )


def save_workspace(
    chat_id: int | str,
    name: str,
    work_dir: str,
    agent_hint: str = "",
    allowed_tools: str = "",
) -> WorkspaceEntry:
    data = _load()
    key = str(chat_id)
    workspaces = [w for w in data.get(key, []) if w["name"].lower() != name.lower()]
    entry: WorkspaceEntry = {
        "name": name,
        "work_dir": work_dir,
        "agent_hint": agent_hint,
        "allowed_tools": allowed_tools,
        "created_at": time.time(),
    }
    workspaces.append(entry)
    data[key] = workspaces
    _save(data)
    return entry


def delete_workspace(chat_id: int | str, name: str) -> bool:
    data = _load()
    key = str(chat_id)
    before = data.get(key, [])
    after = [w for w in before if w["name"].lower() != name.lower()]
    if len(before) == len(after):
        return False
    data[key] = after
    _save(data)
    return True
