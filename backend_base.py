"""Backend abstraction — Protocol + shared result type."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class BackendResult:
    text: str
    session_id: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class Backend(Protocol):
    async def stream(
        self,
        chat_id: int,
        prompt: str,
        session_id: str | None,
        system_prompt: str | None,
        work_dir: str | None,
    ) -> AsyncGenerator[tuple[str, str | None, dict | None], None]: ...

    async def run(
        self,
        chat_id: int,
        prompt: str,
        session_id: str | None,
        system_prompt: str | None,
        work_dir: str | None,
    ) -> BackendResult: ...
