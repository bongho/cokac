"""Main message handler — routes to Claude Code with streaming."""
from __future__ import annotations

import asyncio
import time

import claude
import session as session_store
from config_store import get_config
from handlers.file import pop_pending_files
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

EDIT_INTERVAL = 1.5   # Telegram edit_message 최소 간격 (초)
MAX_MSG_LEN = 4000    # Telegram 메시지 최대 길이


def _split_long(text: str) -> list[str]:
    """4000자 초과 시 분할."""
    parts = []
    while text:
        parts.append(text[:MAX_MSG_LEN])
        text = text[MAX_MSG_LEN:]
    return parts


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if not text:
        return
    await _run_claude_streaming(update, context, text)


async def _run_claude_streaming(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    extra_files: list[str] | None = None,
) -> None:
    chat_id = update.effective_chat.id
    cfg = get_config(chat_id)

    # 파일 컨텍스트 주입
    pending_files = pop_pending_files(chat_id, context) + (extra_files or [])
    if pending_files:
        file_lines = "\n".join(f"[첨부파일: {p}]" for p in pending_files)
        prompt = f"{file_lines}\n\n{text}"
    else:
        prompt = text

    # 세션 결정
    session_id: str | None = None
    if cfg["auto_resume"]:
        session_id = session_store.get_latest_session_id(chat_id)

    system_prompt: str | None = cfg["agent_hint"] or None
    work_dir: str | None = cfg["work_dir"] or None

    # 전송 중 메시지
    status_msg = await update.message.reply_text("⏳")
    buffer = ""
    last_edit = 0.0
    new_session_id: str | None = None

    try:
        async for delta, result_sid in claude.stream_response(
            prompt, session_id, system_prompt, work_dir
        ):
            if result_sid:
                new_session_id = result_sid
                break
            buffer += delta
            now = time.monotonic()
            if buffer and (now - last_edit) >= EDIT_INTERVAL:
                try:
                    await status_msg.edit_text(buffer[:MAX_MSG_LEN] + " ▌")
                    last_edit = now
                except Exception:
                    pass

        # 최종 출력
        if not buffer:
            buffer = "(응답 없음)"

        parts = _split_long(buffer)
        try:
            await status_msg.edit_text(parts[0])
        except Exception:
            await update.message.reply_text(parts[0])

        for part in parts[1:]:
            await update.message.reply_text(part)

    except Exception as e:
        await status_msg.edit_text(f"❌ 오류: {e}")
        return

    # 세션 저장
    if new_session_id:
        session_store.save_session(chat_id, new_session_id)
