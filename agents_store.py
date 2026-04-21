"""Named agent store — per-chat AI agent definitions."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TypedDict

DATA_FILE = Path.home() / ".cokac" / "data" / "agents.json"


class AgentEntry(TypedDict):
    name: str
    system_prompt: str
    allowed_tools: str   # comma-separated; "" = all tools
    session_id: str      # "" = start fresh on next call
    created_at: float


def _load() -> dict[str, list[AgentEntry]]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def list_agents(chat_id: int | str) -> list[AgentEntry]:
    return _load().get(str(chat_id), [])


def get_agent(chat_id: int | str, name: str) -> AgentEntry | None:
    return next(
        (a for a in list_agents(chat_id) if a["name"].lower() == name.lower()), None
    )


def create_agent(
    chat_id: int | str,
    name: str,
    system_prompt: str,
    allowed_tools: str = "",
) -> AgentEntry:
    data = _load()
    key = str(chat_id)
    agents = [a for a in data.get(key, []) if a["name"].lower() != name.lower()]
    entry: AgentEntry = {
        "name": name,
        "system_prompt": system_prompt,
        "allowed_tools": allowed_tools,
        "session_id": "",
        "created_at": time.time(),
    }
    agents.append(entry)
    data[key] = agents
    _save(data)
    return entry


def delete_agent(chat_id: int | str, name: str) -> bool:
    data = _load()
    key = str(chat_id)
    before = data.get(key, [])
    after = [a for a in before if a["name"].lower() != name.lower()]
    if len(before) == len(after):
        return False
    data[key] = after
    _save(data)
    return True


def update_agent_session(chat_id: int | str, name: str, session_id: str) -> None:
    data = _load()
    key = str(chat_id)
    for a in data.get(key, []):
        if a["name"].lower() == name.lower():
            a["session_id"] = session_id
            _save(data)
            return


def update_agent_tools(chat_id: int | str, name: str, allowed_tools: str) -> None:
    data = _load()
    key = str(chat_id)
    for a in data.get(key, []):
        if a["name"].lower() == name.lower():
            a["allowed_tools"] = allowed_tools
            _save(data)
            return


def reset_agent_session(chat_id: int | str, name: str) -> bool:
    agent = get_agent(chat_id, name)
    if not agent:
        return False
    update_agent_session(chat_id, name, "")
    return True
