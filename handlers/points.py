# handlers/points.py

import re
import aiosqlite

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from utils.logger import log_admin_action, log_command
from utils.permissions import check_adm_lvl
from utils.resolver import resolve_user
from utils.antidrain import register_action
import math

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

from aiogram import F

PAGE_SIZE = 5

DB_PATH = "data/bot.db"

router = Router()


# ==========================================
# /point
# ==========================================

@router.message(Command("point"))
async def point_handler(message: Message, bot: Bot):
    """
    /point @username|id|reply +/-N [причина]
    """

    admin    = message.from_user
    args_raw = message.text.partition(" ")[2].strip()

    if not await check_adm_lvl(message, required_level=1):
        return

    await log_command(
        user_id  = admin.id,
        username = admin.username or str(admin.id),
        command  = "/point",
        args     = args_raw
    )

    # ── Resolve target ────────────────────────────────────────
    if message.reply_to_message:
        result    = await resolve_user(message)
        remaining = args_raw
    else:
        parts = args_raw.split(None, 1)
        if not parts:
            return await message.reply(
                "❌ Использование: /point @username|id|reply +/-N [причина]"
            )
        result    = await resolve_user(message, parts[0])
        remaining = parts[1] if len(parts) > 1 else ""

    if not result.success:
        return await message.reply(f"❌ {result.error}")

    target_id     = result.user_id
    target_name   = result.username or str(target_id)
    target_handle = f"@{result.username}" if result.username else result.first_name or str(target_id)

    if not await check_adm_lvl(message, required_level=1, target_id=target_id):
        return

    # ── Parse delta + reason ──────────────────────────────────
    parts = remaining.split(None, 1)
    if not parts:
        return await message.reply("❌ Укажите количество очков: +5 или -3")

    match = re.fullmatch(r"([+-])(\d+)", parts[0])
    if not match:
        return await message.reply("❌ Формат очков: +5 или -3")

    delta  = int(parts[0])
    reason = parts[1].strip() if len(parts) > 1 else "Причина не указана"

    if delta == 0:
        return await message.reply("❌ Изменение не может быть нулевым.")

    action = "POINT_ADD" if delta > 0 else "POINT_SUB"

    # ── Database ──────────────────────────────────────────────
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
            INSERT INTO points(user_id, admin_id, points, reason)
            VALUES(?,?,?,?)
        """, (target_id, admin.id, delta, reason))

        cursor = await db.execute("""
            SELECT COALESCE(SUM(points), 0) FROM points WHERE user_id = ?
        """, (target_id,))
        row       = await cursor.fetchone()
        new_total = row[0] if row else delta

        await db.commit()

    # ── Log ───────────────────────────────────────────────────
    await log_admin_action(
        admin_id    = admin.id,
        admin_name  = admin.username or str(admin.id),
        action      = action,
        target_id   = target_id,
        target_name = target_name,
        details     = reason
    )

    # ── Анти-слив ─────────────────────────────────────────────
    await register_action(
        bot,
        message.chat.id,
        admin.id,
        admin.username or str(admin.id),
        action
    )

    # ── Reply ─────────────────────────────────────────────────
    sign = f"+{delta}" if delta > 0 else str(delta)
    icon = "📈" if delta > 0 else "📉"

    await message.reply(
        f"{icon} {target_handle} {sign} pts\n"
        f"Итого: {new_total}\n"
        f"Причина: {reason}"
    )

