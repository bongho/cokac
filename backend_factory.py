"""Backend factory — returns the configured backend for a chat."""
from __future__ import annotations

from config_store import get_config
from claude_backend import ClaudeCodeBackend

# 추후 추가 예정:
# from openai_backend import OpenAIBackend
# from anthropic_backend import AnthropicBackend

_BACKENDS = {
    "claude": ClaudeCodeBackend(),
    # "openai": OpenAIBackend(),
    # "anthropic": AnthropicBackend(),
}

_DEFAULT = "claude"


def get_backend(chat_id: int):
    """Return the backend configured for this chat_id."""
    cfg = get_config(chat_id)
    name = cfg.get("backend", _DEFAULT)
    return _BACKENDS.get(name, _BACKENDS[_DEFAULT])
