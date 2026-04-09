"""File upload handler — downloads file and injects path into next message context."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

UPLOAD_DIR = Path.home() / ".cokac" / "uploads"
UPLOAD_TTL = 1800  # 30분


def _pending_key(chat_id: int) -> str:
    return f"pending_files_{chat_id}"


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download the uploaded file and store the path for next message."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    doc = update.message.document
    photo = update.message.photo
    caption = update.message.caption or ""

    if doc:
        tg_file = await doc.get_file()
        filename = doc.file_name or f"file_{int(time.time())}"
    elif photo:
        tg_file = await photo[-1].get_file()  # largest size
        filename = f"photo_{int(time.time())}.jpg"
    else:
        await update.message.reply_text("지원하지 않는 파일 형식입니다.")
        return

    dest = UPLOAD_DIR / filename
    await tg_file.download_to_drive(str(dest))

    # 파일 경로를 chat context에 저장
    chat_id = update.effective_chat.id
    key = _pending_key(chat_id)
    pending: list[dict] = context.chat_data.get(key, [])
    pending.append({"path": str(dest), "expires_at": time.time() + UPLOAD_TTL})
    context.chat_data[key] = pending

    # 30분 후 파일 자동 삭제
    context.job_queue.run_once(
        _cleanup_file,
        UPLOAD_TTL,
        data={"path": str(dest), "chat_id": chat_id, "key": key},
        name=f"cleanup_{dest.name}",
    )

    ack = f"📎 `{filename}` 업로드 완료."
    if caption:
        ack += f"\n다음 메시지에서 자동으로 컨텍스트에 포함됩니다."
        # 캡션이 있으면 즉시 메시지로 처리
        from handlers.message import _run_claude_streaming
        await _run_claude_streaming(update, context, caption, extra_files=[str(dest)])
        # pending에서 제거
        context.chat_data[key] = [p for p in pending if p["path"] != str(dest)]
    else:
        await update.message.reply_text(ack + "\n다음 메시지에서 자동으로 컨텍스트에 포함됩니다.", parse_mode="Markdown")


def pop_pending_files(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    """Return and clear pending file paths for this chat."""
    key = _pending_key(chat_id)
    now = time.time()
    pending: list[dict] = context.chat_data.get(key, [])
    valid = [p for p in pending if p["expires_at"] > now]
    context.chat_data[key] = []
    return [p["path"] for p in valid]


async def _cleanup_file(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    path = Path(data["path"])
    if path.exists():
        path.unlink()
