"""Main message handler — routes to Claude Code with streaming."""
from __future__ import annotations

import asyncio
import time

import session as session_store
import task_manager
from backend_factory import get_backend
from config_store import get_config
from handlers.file import pop_pending_files
from telegram import Bot, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

EDIT_INTERVAL = 1.5     # Telegram edit_message 최소 간격 (초)
MAX_MSG_LEN = 4000      # Telegram 메시지 최대 길이
HEARTBEAT_DELAY = 30    # 처리 중 메시지를 1회 표시할 대기 시간 (초)

TOOL_LABELS: dict[str, str] = {
    "Read": "📖 파일 읽는 중...",
    "Write": "✏️ 파일 작성 중...",
    "Edit": "✏️ 파일 수정 중...",
    "Bash": "💻 명령어 실행 중...",
    "Glob": "🔍 파일 검색 중...",
    "Grep": "🔍 코드 검색 중...",
    "WebFetch": "🌐 웹 요청 중...",
    "WebSearch": "🔍 웹 검색 중...",
    "Agent": "🤖 에이전트 실행 중...",
    "TodoWrite": "📝 할 일 정리 중...",
}


def _split_long(text: str) -> list[str]:
    """4000자 초과 시 분할."""
    parts = []
    while text:
        parts.append(text[:MAX_MSG_LEN])
        text = text[MAX_MSG_LEN:]
    return parts


async def _keep_typing(chat_id: int, bot: Bot, stop: asyncio.Event) -> None:
    """Telegram typing indicator를 stop 이벤트까지 4초마다 갱신."""
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        await asyncio.sleep(4)


async def _heartbeat(status_msg, stop: asyncio.Event) -> None:
    """첫 토큰이 늦을 때 30초 후 딱 1회만 안내 메시지 편집."""
    await asyncio.sleep(HEARTBEAT_DELAY)
    if not stop.is_set():
        try:
            await status_msg.edit_text("⏳ 처리 중입니다... 잠시 기다려주세요")
        except Exception:
            pass


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if not text:
        return

    chat_id = update.effective_chat.id

    if task_manager.is_running(chat_id):
        await update.message.reply_text(
            "⚠️ 이미 작업이 실행 중입니다. `/cancel` 로 취소하거나 완료를 기다려주세요.",
            parse_mode="Markdown",
        )
        return

    cfg = get_config(chat_id)
    pending_files = pop_pending_files(chat_id, context)
    if pending_files:
        file_lines = "\n".join(f"[첨부파일: {p}]" for p in pending_files)
        prompt = f"{file_lines}\n\n{text}"
    else:
        prompt = text

    session_id: str | None = None
    if cfg["auto_resume"]:
        session_id = session_store.get_latest_session_id(chat_id)

    system_prompt: str | None = cfg["agent_hint"] or None
    work_dir: str | None = cfg["work_dir"] or None
    allowed_tools: list[str] | None = (
        [t.strip() for t in cfg["allowed_tools"].split(",") if t.strip()]
        if cfg.get("allowed_tools") else None
    )

    status_msg = await update.message.reply_text("⚡ 작업 시작됨")

    started = task_manager.start_task(
        chat_id,
        _background_claude(
            bot=context.bot,
            chat_id=chat_id,
            prompt=prompt,
            session_id=session_id,
            system_prompt=system_prompt,
            work_dir=work_dir,
            allowed_tools=allowed_tools,
            status_msg=status_msg,
        ),
    )
    if not started:
        await status_msg.edit_text("⚠️ 이미 작업이 실행 중입니다.")


async def _background_claude(
    *,
    bot: Bot,
    chat_id: int,
    prompt: str,
    session_id: str | None,
    system_prompt: str | None,
    work_dir: str | None,
    allowed_tools: list[str] | None = None,
    status_msg,
) -> None:
    """Run Claude in background and send result as a new message when done."""
    start_time = time.monotonic()
    backend = get_backend(chat_id)

    stop_typing = asyncio.Event()
    stop_heartbeat = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(chat_id, bot, stop_typing))
    heartbeat_task = asyncio.create_task(_heartbeat(status_msg, stop_heartbeat))

    buffer = ""
    last_edit = 0.0
    first_token = True
    new_session_id: str | None = None
    final_usage: dict = {}

    try:
        async for delta, result_sid, usage in backend.stream(
            chat_id, prompt, session_id, system_prompt, work_dir, allowed_tools
        ):
            if result_sid:
                new_session_id = result_sid
                final_usage = usage or {}
                break

            if delta.startswith("__STATUS__:"):
                tool_name = delta.split(":", 1)[1]
                label = TOOL_LABELS.get(tool_name, f"🔧 {tool_name} 실행 중...")
                stop_heartbeat.set()
                heartbeat_task.cancel()
                try:
                    await status_msg.edit_text(label)
                    last_edit = time.monotonic()
                except Exception:
                    pass
                continue

            buffer += delta
            if first_token and buffer:
                first_token = False
                stop_heartbeat.set()
                heartbeat_task.cancel()
                try:
                    await status_msg.edit_text("💭 생성 중...")
                    last_edit = time.monotonic()
                except Exception:
                    pass

            now = time.monotonic()
            if buffer and (now - last_edit) >= EDIT_INTERVAL:
                elapsed = int(now - start_time)
                try:
                    await status_msg.edit_text(buffer[:MAX_MSG_LEN] + f"\n\n▌ _{elapsed}s_")
                    last_edit = now
                except Exception:
                    pass

    except asyncio.CancelledError:
        try:
            await status_msg.edit_text("🛑 작업이 취소되었습니다.")
        except Exception:
            pass
        return
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ 오류: {e}")
        except Exception:
            pass
        return
    finally:
        stop_typing.set()
        stop_heartbeat.set()
        typing_task.cancel()
        heartbeat_task.cancel()

    # 최종 출력
    if not buffer:
        buffer = "(응답 없음)"

    elapsed_total = int(time.monotonic() - start_time)
    parts = _split_long(buffer)
    try:
        await status_msg.edit_text(parts[0])
    except Exception:
        await bot.send_message(chat_id, parts[0])

    for part in parts[1:]:
        await bot.send_message(chat_id, part)

    # 세션 저장 + stats 누적
    if new_session_id:
        session_store.save_session(chat_id, new_session_id)
        session_store.update_session_stats(
            chat_id,
            new_session_id,
            cost_usd=final_usage.get("cost_usd", 0.0),
            input_tokens=final_usage.get("input_tokens", 0),
            output_tokens=final_usage.get("output_tokens", 0),
            cache_read_tokens=final_usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=final_usage.get("cache_creation_input_tokens", 0),
        )


async def trigger_claude(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    extra_files: list[str] | None = None,
) -> None:
    """Public entry point used by file handler to trigger Claude with injected files."""
    chat_id = update.effective_chat.id

    if task_manager.is_running(chat_id):
        await update.message.reply_text(
            "⚠️ 이미 작업이 실행 중입니다. `/cancel` 로 취소하거나 완료를 기다려주세요.",
            parse_mode="Markdown",
        )
        return

    cfg = get_config(chat_id)
    pending_files = extra_files or []
    if pending_files:
        file_lines = "\n".join(f"[첨부파일: {p}]" for p in pending_files)
        prompt = f"{file_lines}\n\n{text}"
    else:
        prompt = text

    session_id: str | None = None
    if cfg["auto_resume"]:
        session_id = session_store.get_latest_session_id(chat_id)

    allowed_tools: list[str] | None = (
        [t.strip() for t in cfg["allowed_tools"].split(",") if t.strip()]
        if cfg.get("allowed_tools") else None
    )
    status_msg = await update.message.reply_text("⚡ 작업 시작됨")
    task_manager.start_task(
        chat_id,
        _background_claude(
            bot=context.bot,
            chat_id=chat_id,
            prompt=prompt,
            session_id=session_id,
            system_prompt=cfg["agent_hint"] or None,
            work_dir=cfg["work_dir"] or None,
            allowed_tools=allowed_tools,
            status_msg=status_msg,
        ),
    )
