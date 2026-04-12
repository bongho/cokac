"""ClaudeCodeBackend — wraps the Claude Code CLI subprocess (claude.py)."""
from __future__ import annotations

from collections.abc import AsyncGenerator

import claude as _claude
from backend_base import BackendResult


class ClaudeCodeBackend:
    """Delegates to the Claude Code CLI via subprocess."""

    async def stream(
        self,
        chat_id: int,
        prompt: str,
        session_id: str | None,
        system_prompt: str | None,
        work_dir: str | None,
    ) -> AsyncGenerator[tuple[str, str | None, dict | None], None]:
        async for delta, sid, usage in _claude.stream_response(
            prompt, session_id, system_prompt, work_dir
        ):
            yield delta, sid, usage

    async def run(
        self,
        chat_id: int,
        prompt: str,
        session_id: str | None,
        system_prompt: str | None,
        work_dir: str | None,
    ) -> BackendResult:
        r = await _claude.run(prompt, session_id, system_prompt, work_dir)
        return BackendResult(
            text=r.text,
            session_id=r.session_id,
            cost_usd=r.cost_usd,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cache_read_tokens=r.cache_read_tokens,
            cache_creation_tokens=r.cache_creation_tokens,
        )
