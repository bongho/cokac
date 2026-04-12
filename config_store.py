"""Per-chat configuration store."""
from __future__ import annotations

import json
from pathlib import Path

DATA_FILE = Path.home() / ".cokac" / "data" / "configs.json"

DEFAULTS: dict[str, object] = {
    "agent_hint": "",          # system prompt prefix
    "shell_confirm": False,    # confirm before shell exec
    "auto_resume": True,       # auto-resume last session
    "work_dir": "",            # per-chat working directory
    "backend": "claude",       # backend: claude | openai | anthropic
    "openai_model": "gpt-4o",
    "anthropic_model": "claude-opus-4-6",
}


def _load() -> dict[str, dict]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def get_config(chat_id: int | str) -> dict:
    data = _load()
    stored = data.get(str(chat_id), {})
    return {**DEFAULTS, **stored}


def set_config(chat_id: int | str, key: str, value: str) -> str:
    """Set a config value. Returns error message or empty string on success."""
    if key not in DEFAULTS:
        return f"알 수 없는 키: `{key}`\n사용 가능: {', '.join(DEFAULTS.keys())}"
    data = _load()
    key_str = str(chat_id)
    cfg = data.get(key_str, {})

    # 타입 변환
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if value.lower() in ("true", "1", "yes", "on"):
            cfg[key] = True
        elif value.lower() in ("false", "0", "no", "off"):
            cfg[key] = False
        else:
            return f"`{key}`은 true/false 값이어야 합니다"
    else:
        cfg[key] = value

    data[key_str] = cfg
    _save(data)
    return ""
