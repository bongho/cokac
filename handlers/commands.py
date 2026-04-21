"""Bot command handlers."""
from __future__ import annotations

import asyncio
import re
import subprocess
import time

import config_store
import scheduler as sched_store
import session as session_store
import task_manager
from backend_factory import get_backend
from scheduler import parse_cron
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


# ──────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *Claude Code Bot*\n\n"
        "메시지를 보내면 Claude Code가 응답합니다.\n\n"
        "*세션*\n"
        "`/new [이름]` — 새 세션 시작\n"
        "`/fork [이름]` — 현재 세션 분기 (새 브랜치)\n"
        "`/resume [id]` — 세션 이어받기\n"
        "`/sessions` — 세션 목록 (🗑 버튼으로 삭제)\n"
        "`/delegate <세션이름> <작업>` — 작업 위임\n"
        "\n*설정*\n"
        "`/instruction [텍스트|clear]` — 커스텀 지침 설정\n"
        "`/allowedtools [툴목록|all]` — 허용 툴 설정\n"
        "`/wd [경로]` — 작업 디렉토리 확인/변경\n"
        "`/config set <키> <값>` — 고급 설정\n"
        "`/config list` — 현재 설정 보기\n"
        "\n*파일*\n"
        "파일 첨부 — Claude 컨텍스트에 주입\n"
        "`/download <경로>` — 파일을 텔레그램으로 전송\n"
        "\n*실행*\n"
        "`!<명령>` — 셸 명령 실행 (동기, 60s)\n"
        "`!&<명령>` — 백그라운드 실행 (완료 시 알림)\n"
        "`/status` — 현재 작업 실행 상태 확인\n"
        "`/cancel` — 실행 중인 작업 취소\n"
        "`/procs` — 로컬 Claude 터미널 세션 목록\n"
        "\n*스케줄*\n"
        "`/schedule add <cron> <프롬프트>` — 스케줄 추가\n"
        "`/schedules` — 스케줄 목록\n"
        "\n*현황*\n"
        "`/usage` — 작업 디렉토리 · 토큰 · 비용 현황",
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────────
# /new [name]
# ──────────────────────────────────────────────
async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    name = " ".join(context.args) if context.args else ""
    cfg = config_store.get_config(chat_id)
    system_prompt = cfg["agent_hint"] or None
    work_dir = cfg["work_dir"] or None

    msg = await update.message.reply_text("⏳ 새 세션 시작 중...")
    result = await get_backend(chat_id).run(
        chat_id,
        "새 세션을 시작합니다. 준비 완료 메시지를 한 줄로 보내주세요.",
        session_id=None,
        system_prompt=system_prompt,
        work_dir=work_dir,
    )
    if result.session_id:
        session_store.save_session(chat_id, result.session_id, name)
        await msg.edit_text(
            f"✅ 새 세션 생성됨\n"
            f"ID: `{result.session_id[:12]}...`\n"
            f"이름: {name or '(없음)'}",
            parse_mode="Markdown",
        )
    else:
        await msg.edit_text(f"❌ 세션 ID를 받지 못했습니다.\n{result.text}")


# ──────────────────────────────────────────────
# /sessions
# ──────────────────────────────────────────────
async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    sessions = session_store.get_sessions(chat_id)
    if not sessions:
        await update.message.reply_text("저장된 세션이 없습니다. `/new`로 시작하세요.", parse_mode="Markdown")
        return

    latest_id = session_store.get_latest_session_id(chat_id)
    lines = []
    buttons = []
    for s in reversed(sessions):
        marker = "▶" if s["id"] == latest_id else " "
        dt = time.strftime("%m/%d %H:%M", time.localtime(s["created_at"]))
        lines.append(f"{marker} `{s['id'][:12]}` {s['name']} ({dt})")
        buttons.append([
            InlineKeyboardButton(
                f"{'▶ ' if s['id'] == latest_id else ''}{s['name']} ({s['id'][:8]})",
                callback_data=f"resume:{s['id']}",
            ),
            InlineKeyboardButton("🗑", callback_data=f"session_del:{s['id']}"),
        ])

    await update.message.reply_text(
        "📋 *세션 목록*\n" + "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ──────────────────────────────────────────────
# /resume [id]
# ──────────────────────────────────────────────
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if context.args:
        session_id = context.args[0]
    else:
        session_id = session_store.get_latest_session_id(chat_id)
        if not session_id:
            await update.message.reply_text("이어받을 세션이 없습니다.")
            return

    session_store.set_active_session(chat_id, session_id)
    await update.message.reply_text(
        f"✅ 세션 `{session_id[:12]}...` 활성화됨. 다음 메시지부터 이 세션을 사용합니다.",
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────────
# /schedule add <cron> <prompt>  /  /schedules
# ──────────────────────────────────────────────
async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []

    if not args or args[0] == "list":
        return await _list_schedules(update, chat_id)

    if args[0] == "add":
        # /schedule add "0 9 * * *" 오늘 할 일 정리해줘
        rest = args[1:]
        if len(rest) < 6:
            await update.message.reply_text(
                "사용법: `/schedule add <분> <시> <일> <월> <요일> <프롬프트>`\n"
                "예: `/schedule add 0 9 * * * 오늘 할 일 정리해줘`",
                parse_mode="Markdown",
            )
            return
        cron = " ".join(rest[:5])
        prompt = " ".join(rest[5:])
        tz = config_store.get_config(chat_id).get("timezone") or "Asia/Seoul"
        try:
            cron_kwargs = parse_cron(cron, tz)
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}")
            return

        session_id = session_store.get_latest_session_id(chat_id) or ""
        entry = sched_store.add_schedule(chat_id, cron, prompt, session_id)

        # Job 등록
        context.job_queue.run_custom(
            _scheduled_job,
            job_kwargs={"trigger": "cron", **cron_kwargs},
            data={"chat_id": chat_id, "prompt": prompt, "session_id": session_id, "sched_id": entry["id"]},
            name=f"sched_{entry['id']}",
        )
        await update.message.reply_text(
            f"✅ 스케줄 등록: `{entry['id']}`\n"
            f"주기: `{cron}`\n"
            f"프롬프트: {prompt}",
            parse_mode="Markdown",
        )
        return

    if args[0] == "del":
        if len(args) < 2:
            await update.message.reply_text("사용법: `/schedule del <id>`", parse_mode="Markdown")
            return
        sched_id = args[1]
        if sched_store.delete_schedule(sched_id):
            # Job 취소
            jobs = context.job_queue.get_jobs_by_name(f"sched_{sched_id}")
            for job in jobs:
                job.schedule_removal()
            await update.message.reply_text(f"✅ 스케줄 `{sched_id}` 삭제됨.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ 스케줄 `{sched_id}`을 찾을 수 없습니다.", parse_mode="Markdown")
        return

    await update.message.reply_text("사용법: `/schedule add|del|list`", parse_mode="Markdown")


async def _list_schedules(update: Update, chat_id: int) -> None:
    schedules = sched_store.get_schedules(chat_id)
    if not schedules:
        await update.message.reply_text("등록된 스케줄이 없습니다.")
        return
    lines = []
    buttons = []
    for s in schedules:
        lines.append(f"• `{s['id']}` `{s['cron']}` — {s['name']}")
        buttons.append([InlineKeyboardButton(f"🗑 {s['id']} 삭제", callback_data=f"sched_del:{s['id']}")])
    await update.message.reply_text(
        "⏰ *스케줄 목록*\n" + "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _scheduled_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    chat_id = data["chat_id"]
    prompt = data["prompt"]
    session_id = data.get("session_id") or session_store.get_latest_session_id(chat_id)

    await context.bot.send_message(chat_id, f"⏰ 스케줄 실행: _{prompt[:50]}_", parse_mode="Markdown")
    result = await get_backend(chat_id).run(chat_id, prompt, session_id, None, None)
    if result.session_id:
        session_store.save_session(chat_id, result.session_id)
        session_store.update_session_stats(
            chat_id, result.session_id,
            cost_usd=result.cost_usd,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_creation_tokens=result.cache_creation_tokens,
        )
    text = result.text or "(응답 없음)"
    await context.bot.send_message(chat_id, text[:4000])


# ──────────────────────────────────────────────
# /delegate <session-name> <task>
# ──────────────────────────────────────────────
async def cmd_delegate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "사용법: `/delegate <세션이름> <작업>`\n"
            "현재 세션의 마지막 출력을 컨텍스트로 붙여서 대상 세션에 위임합니다.",
            parse_mode="Markdown",
        )
        return

    target_name = args[0]
    task = " ".join(args[1:])

    sessions = session_store.get_sessions(chat_id)
    target = next((s for s in sessions if s["name"] == target_name), None)
    if not target:
        await update.message.reply_text(f"❌ 세션 이름 `{target_name}`을 찾을 수 없습니다.", parse_mode="Markdown")
        return

    msg = await update.message.reply_text(f"🔀 `{target_name}` 세션에 위임 중...", parse_mode="Markdown")
    result = await get_backend(chat_id).run(chat_id, task, target["id"], None, None)
    if result.session_id:
        session_store.save_session(chat_id, result.session_id, target_name)
    await msg.edit_text(result.text[:4000] or "(응답 없음)")


# ──────────────────────────────────────────────
# /config set <key> <value>  /  /config list
# ──────────────────────────────────────────────
async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []

    if not args or args[0] == "list":
        cfg = config_store.get_config(chat_id)
        lines = [f"`{k}` = `{v}`" for k, v in cfg.items()]
        await update.message.reply_text(
            "⚙️ *현재 설정*\n" + "\n".join(lines), parse_mode="Markdown"
        )
        return

    if args[0] == "set":
        if len(args) < 3:
            await update.message.reply_text("사용법: `/config set <키> <값>`", parse_mode="Markdown")
            return
        key = args[1]
        value = " ".join(args[2:])
        err = config_store.set_config(chat_id, key, value)
        if err:
            await update.message.reply_text(f"❌ {err}", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"✅ `{key}` = `{value}` 저장됨.", parse_mode="Markdown")
        return

    await update.message.reply_text("사용법: `/config set|list`", parse_mode="Markdown")


# ──────────────────────────────────────────────
# /usage
# ──────────────────────────────────────────────
async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import os
    chat_id = update.effective_chat.id
    cfg = config_store.get_config(chat_id)

    # 현재 세션 정보
    sessions = session_store.get_sessions(chat_id)
    latest_id = session_store.get_latest_session_id(chat_id)
    current = next((s for s in sessions if s["id"] == latest_id), None)

    # 작업 디렉토리
    work_dir = cfg.get("work_dir") or os.environ.get("WORK_DIR") or os.path.expanduser("~")

    # 현재 세션 stats
    if current:
        sess_cost = current.get("total_cost_usd", 0.0)
        sess_in = current.get("total_input_tokens", 0)
        sess_out = current.get("total_output_tokens", 0)
        sess_cache = current.get("total_cache_read_tokens", 0)
        sess_turns = current.get("turn_count", 0)
        sess_name = current.get("name", "")
        sess_id_short = current["id"][:12]
        session_block = (
            f"\n📈 *현재 세션* — {sess_name} (`{sess_id_short}...`)\n"
            f"  요청: {sess_turns}회\n"
            f"  입력: {sess_in:,} tok\n"
            f"  출력: {sess_out:,} tok\n"
            f"  캐시: {sess_cache:,} tok\n"
            f"  비용: ${sess_cost:.4f}"
        )
    else:
        session_block = "\n_활성 세션 없음_"

    # 전체 합산
    total = session_store.get_all_stats(chat_id)
    total_block = (
        f"\n💰 *전체 합산*\n"
        f"  세션: {total['session_count']}개\n"
        f"  요청: {total['turn_count']}회\n"
        f"  입력: {total['total_input_tokens']:,} tok\n"
        f"  출력: {total['total_output_tokens']:,} tok\n"
        f"  비용: ${total['total_cost_usd']:.4f}"
    )

    text = (
        "📊 *사용량 현황*\n"
        f"📁 작업 디렉토리: `{work_dir}`"
        f"{session_block}"
        f"{total_block}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ──────────────────────────────────────────────
# /procs — 로컬 실행 중인 Claude 터미널 세션
# ──────────────────────────────────────────────
def _get_local_claude_procs() -> list[dict]:
    """Return list of {pid, session_id, cwd} for running claude --session-id processes."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,args"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []

    procs = []
    for line in result.stdout.splitlines():
        if "--session-id" not in line:
            continue
        m = re.search(r"claude\b", line)
        if not m:
            continue
        pid_m = re.match(r"\s*(\d+)\s+", line)
        sid_m = re.search(r"--session-id\s+([0-9a-f-]{36})", line)
        if not pid_m or not sid_m:
            continue
        pid = pid_m.group(1)
        session_id = sid_m.group(1)
        try:
            cwd_result = subprocess.run(
                ["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
                capture_output=True, text=True, timeout=3,
            )
            cwd = next(
                (l[1:] for l in cwd_result.stdout.splitlines() if l.startswith("n")),
                "?",
            )
        except Exception:
            cwd = "?"
        procs.append({"pid": pid, "session_id": session_id, "cwd": cwd})
    return procs


async def cmd_procs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List locally running Claude terminal sessions with resume buttons."""
    chat_id = update.effective_chat.id
    procs = await asyncio.get_event_loop().run_in_executor(None, _get_local_claude_procs)

    if not procs:
        await update.message.reply_text("실행 중인 로컬 Claude 세션이 없습니다.")
        return

    lines = []
    buttons = []
    for p in procs:
        sid_short = p["session_id"][:12]
        cwd_short = p["cwd"].replace("/Users/bono", "~")
        lines.append(f"• PID `{p['pid']}` — `{sid_short}...`\n  📁 `{cwd_short}`")
        buttons.append([InlineKeyboardButton(
            f"▶ Resume {sid_short}",
            callback_data=f"resume:{p['session_id']}",
        )])

    await update.message.reply_text(
        "🖥 *로컬 Claude 세션*\n\n" + "\n\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ──────────────────────────────────────────────
# /wd [path] — 작업 디렉토리 확인/변경
# ──────────────────────────────────────────────
async def cmd_wd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import os
    chat_id = update.effective_chat.id
    cfg = config_store.get_config(chat_id)

    if not context.args:
        wd = cfg.get("work_dir") or os.environ.get("WORK_DIR") or os.path.expanduser("~")
        await update.message.reply_text(
            f"📁 현재 작업 디렉토리: `{wd}`\n\n변경: `/wd <경로>`",
            parse_mode="Markdown",
        )
        return

    new_path = " ".join(context.args)
    expanded = os.path.expanduser(new_path)
    if not os.path.isdir(expanded):
        await update.message.reply_text(f"❌ 존재하지 않는 디렉토리: `{expanded}`", parse_mode="Markdown")
        return

    err = config_store.set_config(chat_id, "work_dir", expanded)
    if err:
        await update.message.reply_text(f"❌ {err}")
    else:
        await update.message.reply_text(f"✅ 작업 디렉토리 변경: `{expanded}`", parse_mode="Markdown")


# ──────────────────────────────────────────────
# /cancel
# ──────────────────────────────────────────────
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if task_manager.cancel_task(chat_id):
        await update.message.reply_text("🛑 작업을 취소했습니다.")
    else:
        await update.message.reply_text("실행 중인 작업이 없습니다.")


# ──────────────────────────────────────────────
# /status
# ──────────────────────────────────────────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    elapsed = task_manager.elapsed_seconds(chat_id)
    if elapsed is not None:
        await update.message.reply_text(f"⚙️ 작업 실행 중 — 경과 {int(elapsed)}초")
    else:
        await update.message.reply_text("✅ 실행 중인 작업 없음")


# ──────────────────────────────────────────────
# Callback query handler (인라인 버튼)
# ──────────────────────────────────────────────
async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data or ""

    if data.startswith("resume:"):
        session_id = data.split(":", 1)[1]
        session_store.set_active_session(chat_id, session_id)
        await query.edit_message_text(f"✅ 세션 `{session_id[:12]}...` 활성화됨.", parse_mode="Markdown")

    elif data.startswith("session_del:"):
        session_id = data.split(":", 1)[1]
        if session_store.delete_session(chat_id, session_id):
            await query.answer(f"세션 {session_id[:8]} 삭제됨.")
            # 목록 갱신
            sessions = session_store.get_sessions(chat_id)
            if not sessions:
                await query.edit_message_text("세션이 없습니다. `/new`로 시작하세요.", parse_mode="Markdown")
            else:
                latest_id = session_store.get_latest_session_id(chat_id)
                lines = []
                buttons = []
                for s in reversed(sessions):
                    marker = "▶" if s["id"] == latest_id else " "
                    dt = time.strftime("%m/%d %H:%M", time.localtime(s["created_at"]))
                    lines.append(f"{marker} `{s['id'][:12]}` {s['name']} ({dt})")
                    buttons.append([
                        InlineKeyboardButton(
                            f"{'▶ ' if s['id'] == latest_id else ''}{s['name']} ({s['id'][:8]})",
                            callback_data=f"resume:{s['id']}",
                        ),
                        InlineKeyboardButton("🗑", callback_data=f"session_del:{s['id']}"),
                    ])
                await query.edit_message_text(
                    "📋 *세션 목록*\n" + "\n".join(lines),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
        else:
            await query.answer("세션을 찾을 수 없습니다.")

    elif data.startswith("sched_del:"):
        sched_id = data.split(":", 1)[1]
        if sched_store.delete_schedule(sched_id):
            jobs = context.job_queue.get_jobs_by_name(f"sched_{sched_id}")
            for job in jobs:
                job.schedule_removal()
            await query.edit_message_text(f"✅ 스케줄 `{sched_id}` 삭제됨.", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"❌ 스케줄 `{sched_id}`을 찾을 수 없습니다.", parse_mode="Markdown")

    elif data.startswith("shell_exec:"):
        from handlers.shell import _execute_shell
        import os
        cmd = data.split(":", 1)[1]
        cfg = config_store.get_config(chat_id)
        work_dir = cfg.get("work_dir") or os.path.expanduser("~")
        # callback_query에서는 update.message가 없으므로 query.message 활용
        await query.edit_message_text(f"⏳ 실행 중: `{cmd[:60]}`", parse_mode="Markdown")

        import asyncio
        from telegram import Update as TgUpdate
        # 임시 update-like 객체 없이 직접 실행
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=work_dir,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            output = stdout.decode("utf-8", errors="replace").strip() or "(출력 없음)"
            if len(output) > 3800:
                output = output[:3800] + "\n...(출력 잘림)"
            rc = proc.returncode
            status = "✅" if rc == 0 else f"❌ (rc={rc})"
            await query.edit_message_text(f"{status} `{cmd[:60]}`\n```\n{output}\n```", parse_mode="Markdown")
        except asyncio.TimeoutError:
            await query.edit_message_text(f"⏱ 타임아웃 (60s): `{cmd[:60]}`", parse_mode="Markdown")

    elif data == "shell_cancel":
        await query.edit_message_text("❌ 취소됨.")


# ──────────────────────────────────────────────
# /fork [이름] — 현재 세션 분기
# ──────────────────────────────────────────────
async def cmd_fork(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session_id = session_store.get_latest_session_id(chat_id)
    if not session_id:
        await update.message.reply_text(
            "⚠️ 활성 세션이 없습니다. `/new`로 먼저 세션을 시작하세요.", parse_mode="Markdown"
        )
        return

    name = " ".join(context.args) if context.args else ""
    cfg = config_store.get_config(chat_id)

    msg = await update.message.reply_text("🌿 세션 분기 중...")
    result = await get_backend(chat_id).run(
        chat_id,
        "세션이 분기됩니다. 준비 완료를 한 줄로 알려주세요.",
        session_id=session_id,
        system_prompt=cfg["agent_hint"] or None,
        work_dir=cfg["work_dir"] or None,
        fork=True,
    )
    if result.session_id and result.session_id != session_id:
        fork_name = name or f"fork-{result.session_id[:6]}"
        session_store.save_session(chat_id, result.session_id, fork_name)
        session_store.set_active_session(chat_id, result.session_id)
        await msg.edit_text(
            f"🌿 *세션 분기 완료*\n"
            f"원본: `{session_id[:12]}...`\n"
            f"새 세션: `{result.session_id[:12]}...` ({fork_name})\n"
            f"이제 새 세션에서 작업합니다.",
            parse_mode="Markdown",
        )
    else:
        await msg.edit_text(
            f"⚠️ 분기된 세션 ID를 확인할 수 없습니다.\n응답: {result.text[:200]}"
        )


# ──────────────────────────────────────────────
# /instruction [text|clear]
# ──────────────────────────────────────────────
async def cmd_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []

    if not args:
        cfg = config_store.get_config(chat_id)
        hint = cfg.get("agent_hint") or "(없음)"
        await update.message.reply_text(
            f"📋 *현재 커스텀 지침*\n{hint}\n\n"
            "변경: `/instruction <텍스트>`\n초기화: `/instruction clear`",
            parse_mode="Markdown",
        )
        return

    if args[0] == "clear":
        config_store.set_config(chat_id, "agent_hint", "")
        await update.message.reply_text("✅ 커스텀 지침 초기화됨.", parse_mode="Markdown")
        return

    text = " ".join(args)
    err = config_store.set_config(chat_id, "agent_hint", text)
    if err:
        await update.message.reply_text(f"❌ {err}")
    else:
        await update.message.reply_text(
            f"✅ 커스텀 지침 저장됨:\n_{text[:200]}_", parse_mode="Markdown"
        )


# ──────────────────────────────────────────────
# /allowedtools [툴목록|all]
# ──────────────────────────────────────────────

_KNOWN_TOOLS = {
    "Bash", "Read", "Write", "Edit", "Glob", "Grep",
    "WebFetch", "WebSearch", "Agent", "TodoWrite",
}


async def cmd_allowedtools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []

    if not args:
        cfg = config_store.get_config(chat_id)
        current = cfg.get("allowed_tools") or "(제한 없음 — 모든 툴 허용)"
        await update.message.reply_text(
            f"🔧 *현재 허용 툴*\n`{current}`\n\n"
            "변경: `/allowedtools Read,Grep,Glob`\n"
            "전체 허용: `/allowedtools all`\n"
            f"사용 가능 툴: `{', '.join(sorted(_KNOWN_TOOLS))}`",
            parse_mode="Markdown",
        )
        return

    if args[0].lower() == "all":
        config_store.set_config(chat_id, "allowed_tools", "")
        await update.message.reply_text("✅ 툴 제한 해제 — 모든 툴 허용.", parse_mode="Markdown")
        return

    raw = " ".join(args)
    tools = [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
    unknown = [t for t in tools if t not in _KNOWN_TOOLS]
    if unknown:
        await update.message.reply_text(
            f"⚠️ 알 수 없는 툴: `{', '.join(unknown)}`\n"
            f"사용 가능: `{', '.join(sorted(_KNOWN_TOOLS))}`",
            parse_mode="Markdown",
        )
        return

    value = ",".join(tools)
    err = config_store.set_config(chat_id, "allowed_tools", value)
    if err:
        await update.message.reply_text(f"❌ {err}")
    else:
        await update.message.reply_text(
            f"✅ 허용 툴 설정됨: `{value}`", parse_mode="Markdown"
        )


# ──────────────────────────────────────────────
# /download <경로>
# ──────────────────────────────────────────────

_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50MB (Telegram 제한)


async def cmd_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import os
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "사용법: `/download <파일경로>`\n예: `/download ~/project/result.csv`",
            parse_mode="Markdown",
        )
        return

    raw_path = " ".join(context.args)
    path = os.path.realpath(os.path.expanduser(os.path.expandvars(raw_path)))

    if not os.path.exists(path):
        await update.message.reply_text(f"❌ 파일을 찾을 수 없습니다: `{path}`", parse_mode="Markdown")
        return

    if not os.path.isfile(path):
        await update.message.reply_text(f"❌ 디렉토리는 전송할 수 없습니다: `{path}`", parse_mode="Markdown")
        return

    size = os.path.getsize(path)
    if size > _MAX_DOWNLOAD_BYTES:
        mb = size / 1024 / 1024
        await update.message.reply_text(
            f"❌ 파일이 너무 큽니다: {mb:.1f}MB (최대 50MB)", parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text(f"📤 전송 중: `{os.path.basename(path)}`", parse_mode="Markdown")
    try:
        with open(path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=os.path.basename(path),
                caption=f"`{path}`",
                parse_mode="Markdown",
            )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ 전송 실패: {e}")
