import asyncio
import aiosqlite
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command

from database import (
    get_admin_level,
    get_all_admins,
    add_admin,
    get_user
)
from utils.logger import log_admin_action, log_command

DB_PATH   = "data/bot.db"
VOTE_TIME = 600  # 10 минут

router = Router()

# vote_id -> asyncio.Task
_vote_tasks: dict[int, asyncio.Task] = {}


# ==========================================
# КЛАВИАТУРА
# ==========================================

def vote_keyboard(vote_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ За",     callback_data=f"radm_yes:{vote_id}"),
        InlineKeyboardButton(text="❌ Против", callback_data=f"radm_no:{vote_id}"),
    ]])


# ==========================================
# ТЕКСТ ГОЛОСОВАНИЯ
# ==========================================

async def vote_text(
    vote_id:     int,
    target_id:   int,
    target_name: str,
    display_name: str,
    old_level:   int
) -> str:

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT voter_id, vote FROM vote_members WHERE vote_id = ?
        """, (vote_id,))
        votes = await cursor.fetchall()

    yes_votes = [v for v in votes if v[1] == "yes"]
    no_votes  = [v for v in votes if v[1] == "no"]

    async def fmt(voter_list):
        lines = []
        for voter_id, _ in voter_list:
            row = await get_user(voter_id)
            if row and row[2]:
                name = f"{row[2]} {row[3] or ''}".strip()
            else:
                name = str(voter_id)
            lines.append(f" – {name} [ID: {voter_id}]")
        return "\n".join(lines) if lines else " –"

    yes_str = await fmt(yes_votes)
    no_str  = await fmt(no_votes)

    return (
        f"<b>ExBot » ConferenceGuard</b>\n"
        f"ExBot » Запрос на выдачу прав\n\n"
        f"Пользователь: <b>{display_name}</b>\n"
        f"Игровой ник: {target_name} [ID: {target_id}]\n"
        f"Уровень администратора: {old_level}\n\n"
        f"Проголосовавшие за выдачу:\n{yes_str}\n\n"
        f"Проголосовавшие против:\n{no_str}"
    )


# ==========================================
# ЗАВЕРШЕНИЕ ГОЛОСОВАНИЯ
# ==========================================

async def finish_vote(
    bot:          Bot,
    chat_id:      int,
    msg_id:       int,
    vote_id:      int,
    target_id:    int,
    target_name:  str,
    display_name: str,
    old_level:    int,
    forced_by:    int = None  # если lvl3 принял решение
):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT voter_id, vote FROM vote_members WHERE vote_id = ?
        """, (vote_id,))
        votes = await cursor.fetchall()

        await db.execute("""
            UPDATE votes SET status = 'closed' WHERE id = ?
        """, (vote_id,))
        await db.commit()

    yes = sum(1 for v in votes if v[1] == "yes")
    no  = sum(1 for v in votes if v[1] == "no")

    # Если голос lvl3 — его решение закон
    if forced_by is not None:
        won = any(v[0] == forced_by and v[1] == "yes" for v in votes)
    else:
        won = yes > no

    base = await vote_text(vote_id, target_id, target_name, display_name, old_level)

    if won:
        await add_admin(target_id, old_level, forced_by or 0)

        await log_admin_action(
            admin_id    = forced_by or 0,
            admin_name  = "vote" if not forced_by else str(forced_by),
            action      = "RADM_GRANTED",
            target_id   = target_id,
            target_name = target_name,
            details     = f"Уровень восстановлен: {old_level}"
        )

        suffix = (
            "\n\nАдминистратор 3 уровня принял решение — права выданы."
            if forced_by else
            "\n\nБольшинство проголосовали за выдачу прав.\nПрава администратора были выданы пользователю. (ред.)"
        )
    else:
        await log_admin_action(
            admin_id    = forced_by or 0,
            admin_name  = "vote" if not forced_by else str(forced_by),
            action      = "RADM_DENIED",
            target_id   = target_id,
            target_name = target_name,
            details     = f"Отказано. За: {yes}, против: {no}"
        )

        suffix = (
            "\n\nАдминистратор 3 уровня принял решение — в правах отказано."
            if forced_by else
            "\n\nБольшинство проголосовали против.\nВ выдаче прав отказано."
        )

    await bot.edit_message_text(
        chat_id    = chat_id,
        message_id = msg_id,
        text       = base + suffix,
        parse_mode = "HTML"
    )

    _vote_tasks.pop(vote_id, None)


# ==========================================
# /radm — вызывает сам бывший админ
# ==========================================

@router.message(Command("radm"))
async def radm_handler(message: Message, bot: Bot):

    caller    = message.from_user
    args_raw  = message.text.partition(" ")[2].strip()
    caller_id = caller.id

    await log_command(
        user_id  = caller_id,
        username = caller.username or str(caller_id),
        command  = "/radm",
        args     = args_raw
    )

    current_level = await get_admin_level(caller_id)

    # ── Уровень 3: принудительная выдача другому ─────────────
    if current_level >= 3:

        if not args_raw:
            return await message.reply(
                "❌ Укажите пользователя: /radm @username|id|reply"
            )

        from utils.resolver import resolve_user
        result = await resolve_user(message, args_raw.split()[0])

        if not result.success:
            return await message.reply(f"❌ {result.error}")

        target_id   = result.user_id
        target_name = result.username or result.first_name or str(target_id)

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT old_level FROM ex_admins WHERE user_id = ?
            """, (target_id,))
            ex_row = await cursor.fetchone()

        if not ex_row:
            return await message.reply("❌ Пользователь не найден в бывших администраторах.")

        old_level = ex_row[0]
        await add_admin(target_id, old_level, caller_id)

        # Убираем из ex_admins
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM ex_admins WHERE user_id = ?", (target_id,))
            await db.commit()

        await log_admin_action(
            admin_id    = caller_id,
            admin_name  = caller.username or str(caller_id),
            action      = "RADM_FORCE",
            target_id   = target_id,
            target_name = target_name,
            details     = f"Принудительное восстановление, уровень {old_level}"
        )

        return await message.reply(
            f"✅ @{target_name} восстановлен в должности (уровень {old_level})."
        )

    # ── Бывший админ запрашивает голосование за себя ─────────
    # Проверяем что вызывающий есть в ex_admins
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT old_level FROM ex_admins WHERE user_id = ?
        """, (caller_id,))
        ex_row = await cursor.fetchone()

    if not ex_row:
        return await message.reply(
            "❌ Эта команда доступна только бывшим администраторам "
            "для запроса голосования о восстановлении."
        )

    old_level = ex_row[0]

    # Нет ли уже активного голосования
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id FROM votes WHERE target_id = ? AND status = 'active'
        """, (caller_id,))
        existing = await cursor.fetchone()

    if existing:
        return await message.reply("❌ Голосование по вашей кандидатуре уже идёт.")

    # Имя для отображения
    caller_row    = await get_user(caller_id)
    display_name  = caller.first_name or caller.username or str(caller_id)
    target_name   = caller.username or caller.first_name or str(caller_id)

    now     = datetime.now()
    expires = now + timedelta(seconds=VOTE_TIME)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO votes(target_id, requester_id, created_at, expires_at, status)
            VALUES(?,?,?,?,?)
        """, (
            caller_id,
            caller_id,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            expires.strftime("%Y-%m-%d %H:%M:%S"),
            "active"
        ))
        vote_id = cursor.lastrowid
        await db.commit()

    text = await vote_text(vote_id, caller_id, target_name, display_name, old_level)
    msg  = await message.answer(text, parse_mode="HTML", reply_markup=vote_keyboard(vote_id))

    async def timer():
        await asyncio.sleep(VOTE_TIME)
        await finish_vote(
            bot, message.chat.id, msg.message_id,
            vote_id, caller_id, target_name, display_name, old_level
        )

    task = asyncio.create_task(timer())
    _vote_tasks[vote_id] = task


# ==========================================
# CALLBACK: ГОЛОС
# ==========================================

@router.callback_query(F.data.startswith("radm_"))
async def radm_vote_callback(call: CallbackQuery, bot: Bot):

    voter_id    = call.from_user.id
    voter_level = await get_admin_level(voter_id)

    if voter_level == 0:
        return await call.answer(
            "❌ Только действующие администраторы могут голосовать.",
            show_alert=True
        )

    parts   = call.data.split(":")
    vote_id = int(parts[1])
    vote    = "yes" if parts[0] == "radm_yes" else "no"

    # Голосование активно?
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT target_id, status FROM votes WHERE id = ?
        """, (vote_id,))
        vote_row = await cursor.fetchone()

    if not vote_row or vote_row[1] != "active":
        return await call.answer("Голосование уже завершено.", show_alert=True)

    target_id = vote_row[0]

    # Нельзя голосовать за себя
    if voter_id == target_id:
        return await call.answer("❌ Нельзя голосовать за себя.", show_alert=True)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT old_level FROM ex_admins WHERE user_id = ?
        """, (target_id,))
        ex_row    = await cursor.fetchone()
        old_level = ex_row[0] if ex_row else 1

    target_row   = await get_user(target_id)
    target_name  = target_row[1] if target_row and target_row[1] else str(target_id)
    display_name = target_row[2] if target_row and target_row[2] else target_name

    # Сохраняем голос
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT vote FROM vote_members WHERE vote_id = ? AND voter_id = ?
        """, (vote_id, voter_id))
        old_vote = await cursor.fetchone()

        if old_vote:
            if old_vote[0] == vote:
                await call.answer("Вы уже проголосовали так.", show_alert=False)
                return
            await db.execute("""
                UPDATE vote_members SET vote = ?
                WHERE vote_id = ? AND voter_id = ?
            """, (vote, vote_id, voter_id))
        else:
            await db.execute("""
                INSERT INTO vote_members(vote_id, voter_id, vote)
                VALUES(?,?,?)
            """, (vote_id, voter_id, vote))

        await db.commit()

    await call.answer("Голос принят.")

    # ── Голос lvl3 — решающий ─────────────────────────────────
    if voter_level >= 3:
        task = _vote_tasks.pop(vote_id, None)
        if task:
            task.cancel()

        await finish_vote(
            bot, call.message.chat.id, call.message.message_id,
            vote_id, target_id, target_name, display_name, old_level,
            forced_by=voter_id
        )
        return

    # ── Обновляем сообщение ───────────────────────────────────
    new_text = await vote_text(vote_id, target_id, target_name, display_name, old_level)
    await call.message.edit_text(
        new_text,
        parse_mode   = "HTML",
        reply_markup = vote_keyboard(vote_id)
    )

    # ── Досрочная победа большинства ──────────────────────────
    all_admins = await get_all_admins()
    total      = len(all_admins)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT vote FROM vote_members WHERE vote_id = ?
        """, (vote_id,))
        all_votes = await cursor.fetchall()

    yes      = sum(1 for v in all_votes if v[0] == "yes")
    majority = total // 2 + 1

    if yes >= majority:
        task = _vote_tasks.pop(vote_id, None)
        if task:
            task.cancel()
        await finish_vote(
            bot, call.message.chat.id, call.message.message_id,
            vote_id, target_id, target_name, display_name, old_level
        )