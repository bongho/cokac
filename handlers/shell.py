"""Shell command execution handler."""
from __future__ import annotations

import asyncio
import os

from config_store import get_config
from telegram import Update
from telegram.ext import ContextTypes

MAX_OUTPUT = 3800  # Telegram 메시지 최대 길이 여유


async def handle_shell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    cmd = text[1:].strip()  # remove leading '!'

    if not cmd:
        await update.message.reply_text("사용법: `!<명령어>` (예: `!git status`)", parse_mode="Markdown")
        return

    cfg = get_config(chat_id)
    if cfg["shell_confirm"]:
        # 확인 버튼 (InlineKeyboard)
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ 실행", callback_data=f"shell_exec:{cmd}"),
            InlineKeyboardButton("❌ 취소", callback_data="shell_cancel"),
        ]])
        await update.message.reply_text(
            f"셸 명령 실행 확인:\n```\n{cmd}\n```", parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    await _execute_shell(update, cmd, cfg.get("work_dir") or os.path.expanduser("~"))


async def _execute_shell(update: Update, cmd: str, work_dir: str) -> None:
    msg = await update.message.reply_text(f"⏳ 실행 중: `{cmd[:60]}`", parse_mode="Markdown")
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=work_dir,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = stdout.decode("utf-8", errors="replace").strip()
        if not output:
            output = "(출력 없음)"
        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + "\n...(출력 잘림)"
        rc = proc.returncode
        status = "✅" if rc == 0 else f"❌ (rc={rc})"
        await msg.edit_text(f"{status} `{cmd[:60]}`\n```\n{output}\n```", parse_mode="Markdown")
    except asyncio.TimeoutError:
        await msg.edit_text(f"⏱ 타임아웃 (60s): `{cmd[:60]}`", parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ 오류: {e}", parse_mode="Markdown")
