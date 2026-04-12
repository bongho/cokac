"""Entry point — Telegram bot for Claude Code."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# .env 로드 (python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv(Path.home() / ".cokac" / ".env")
except ImportError:
    pass

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from handlers.commands import (
    callback_query,
    cmd_config,
    cmd_delegate,
    cmd_new,
    cmd_resume,
    cmd_schedule,
    cmd_sessions,
    cmd_start,
    cmd_usage,
)
from handlers.file import handle_file
from handlers.message import handle_message
from handlers.shell import handle_shell
from scheduler import get_schedules, parse_cron

class _TokenRedactor(logging.Filter):
    """로그에서 봇 토큰을 마스킹합니다."""
    def __init__(self):
        super().__init__()
        self._token: str | None = None

    def _get_token(self) -> str | None:
        if self._token is None:
            self._token = os.environ.get("TELEGRAM_BOT_TOKEN")
        return self._token

    def filter(self, record: logging.LogRecord) -> bool:
        token = self._get_token()
        if not token:
            return True
        # args가 있으면 먼저 포맷팅 후 치환
        if record.args:
            try:
                record.msg = record.getMessage().replace(token, "***")
            except Exception:
                record.msg = str(record.msg).replace(token, "***")
            record.args = None
        else:
            record.msg = str(record.msg).replace(token, "***")
        # 예외 정보(traceback)에서도 토큰 제거
        if record.exc_info and record.exc_info[1]:
            exc_msg = str(record.exc_info[1])
            if token in exc_msg:
                record.exc_info = None
                record.exc_text = exc_msg.replace(token, "***")
        return True


_redactor = _TokenRedactor()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path.home() / ".cokac" / "bot.log"),
    ],
)
# 모든 핸들러에 토큰 마스킹 필터 적용
for _h in logging.root.handlers:
    _h.addFilter(_redactor)

# httpx URL 로그도 마스킹 적용
logging.getLogger("httpx").addFilter(_redactor)

logger = logging.getLogger(__name__)


def _get_allowed_chat_ids() -> set[int]:
    raw = os.environ.get("ALLOWED_CHAT_IDS", "").strip()
    if not raw:
        return set()
    return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}


ALLOWED_CHAT_IDS = _get_allowed_chat_ids()


async def _auth_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id not in ALLOWED_CHAT_IDS:
        logger.warning("Unauthorized access attempt from chat_id=%s", chat_id)
        await update.message.reply_text("⛔ 접근 권한이 없습니다.")
        return False
    return True


def _wrap_auth(handler):
    """Decorator: 인증 통과한 업데이트만 핸들러에 전달."""
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await _auth_check(update, context):
            await handler(update, context)
    return wrapped


def _restore_schedules(app: Application) -> None:
    """봇 재시작 시 저장된 스케줄 복원."""
    schedules = get_schedules()
    restored = 0
    for s in schedules:
        try:
            cron_kwargs = parse_cron(s["cron"])
        except ValueError:
            logger.warning("Invalid cron for schedule %s: %s", s["id"], s["cron"])
            continue

        from handlers.commands import _scheduled_job
        app.job_queue.run_custom(
            _scheduled_job,
            job_kwargs={"trigger": "cron", **cron_kwargs},
            data={
                "chat_id": int(s["chat_id"]),
                "prompt": s["prompt"],
                "session_id": s.get("session_id", ""),
                "sched_id": s["id"],
            },
            name=f"sched_{s['id']}",
        )
        restored += 1
    if restored:
        logger.info("Restored %d scheduled job(s).", restored)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Create ~/.cokac/.env with the token.")
        sys.exit(1)

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", _wrap_auth(cmd_start)))
    app.add_handler(CommandHandler("new", _wrap_auth(cmd_new)))
    app.add_handler(CommandHandler("sessions", _wrap_auth(cmd_sessions)))
    app.add_handler(CommandHandler("resume", _wrap_auth(cmd_resume)))
    app.add_handler(CommandHandler("schedule", _wrap_auth(cmd_schedule)))
    app.add_handler(CommandHandler("schedules", _wrap_auth(cmd_schedule)))  # alias
    app.add_handler(CommandHandler("delegate", _wrap_auth(cmd_delegate)))
    app.add_handler(CommandHandler("config", _wrap_auth(cmd_config)))
    app.add_handler(CommandHandler("usage", _wrap_auth(cmd_usage)))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(callback_query))

    # Shell commands (! prefix)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^!") & ~filters.COMMAND,
        _wrap_auth(handle_shell),
    ))

    # File uploads
    app.add_handler(MessageHandler(
        (filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND,
        _wrap_auth(handle_file),
    ))

    # Regular messages → Claude
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        _wrap_auth(handle_message),
    ))

    # 스케줄 복원
    _restore_schedules(app)

    logger.info("Bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
