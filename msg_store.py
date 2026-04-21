"""Track message IDs per chat for /clear batch delete."""
from __future__ import annotations

import json
from pathlib import Path

_DATA_FILE = Path.home() / ".cokac" / "data" / "msg_ids.json"
_cache: dict[str, list[int]] = {}
_loaded = False


def _load() -> None:
    global _cache, _loaded
    if _loaded:
        return
    if _DATA_FILE.exists():
        try:
            _cache = json.loads(_DATA_FILE.read_text())
        except Exception:
            _cache = {}
    _loaded = True


def _save() -> None:
    _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DATA_FILE.write_text(json.dumps(_cache))


def log(chat_id: int | str, message_id: int) -> None:
    _load()
    key = str(chat_id)
    ids = _cache.setdefault(key, [])
    if message_id not in ids:
        ids.append(message_id)
    _save()


def get_ids(chat_id: int | str) -> list[int]:
    _load()
    return list(_cache.get(str(chat_id), []))


def clear(chat_id: int | str) -> None:
    _load()
    _cache.pop(str(chat_id), None)
    _save()
