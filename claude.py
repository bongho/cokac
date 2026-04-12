"""Claude Code subprocess wrapper with streaming support."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path

CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or str(Path.home() / ".local/bin/claude")
WORK_DIR = os.environ.get("WORK_DIR") or str(Path.home())


class ClaudeResult:
    def __init__(
        self,
        text: str,
        session_id: str,
        cost_usd: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ):
        self.text = text
        self.session_id = session_id
        self.cost_usd = cost_usd
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_tokens = cache_read_tokens
        self.cache_creation_tokens = cache_creation_tokens


async def stream_response(
    prompt: str,
    session_id: str | None = None,
    system_prompt: str | None = None,
    work_dir: str | None = None,
) -> AsyncGenerator[tuple[str, str | None, dict | None], None]:
    """
    Yield (text_chunk, session_id_or_None, usage_or_None) tuples.
    usage is set only on the final 'result' event.
    """
    cmd = [
        CLAUDE_BIN,
        "--print",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--permission-mode", "auto",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]
    cmd.append(prompt)

    cwd = work_dir or WORK_DIR
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=cwd,
        limit=4 * 1024 * 1024,  # 4MB buffer (verbose output can be large)
    )

    seen_text = ""
    result_session_id = None

    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")

        if event_type == "assistant":
            content = event.get("message", {}).get("content", [])
            full_text = "".join(
                block.get("text", "") for block in content if block.get("type") == "text"
            )
            # yield only the new portion (delta)
            if full_text and full_text != seen_text:
                delta = full_text[len(seen_text):]
                seen_text = full_text
                yield delta, None, None

        elif event_type == "result":
            result_session_id = event.get("session_id")
            usage = event.get("usage", {})
            yield "", result_session_id, usage  # signal completion

    await proc.wait()


async def run(
    prompt: str,
    session_id: str | None = None,
    system_prompt: str | None = None,
    work_dir: str | None = None,
) -> ClaudeResult:
    """Run Claude and return full result (non-streaming)."""
    cmd = [
        CLAUDE_BIN,
        "--print",
        "--output-format", "json",
        "--permission-mode", "auto",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]
    cmd.append(prompt)

    cwd = work_dir or WORK_DIR
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=cwd,
    )
    stdout, _ = await proc.communicate()

    try:
        data = json.loads(stdout.decode("utf-8", errors="replace"))
        usage = data.get("usage", {})
        return ClaudeResult(
            text=data.get("result", ""),
            session_id=data.get("session_id", ""),
            cost_usd=data.get("total_cost_usd", 0.0),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        )
    except (json.JSONDecodeError, AttributeError):
        return ClaudeResult(
            text=stdout.decode("utf-8", errors="replace"),
            session_id="",
            cost_usd=0.0,
        )
