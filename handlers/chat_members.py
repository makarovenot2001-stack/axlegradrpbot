# handlers/chat_members.py

import aiosqlite

from aiogram import Router, Bot
from aiogram.types import ChatMemberUpdated

from database import save_user
from handlers.gban import get_gban
from handlers.get import migrate_users_table, record_join

DB_PATH = "data/bot.db"

router = Router()


async def get_local_ban(chat_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT reason FROM bans
            WHERE chat_id = ? AND user_id = ?
            ORDER BY id DESC LIMIT 1
        """, (chat_id, user_id))
        return await cur.fetchone()


@router.chat_member()
async def member_update(event: ChatMemberUpdated, bot: Bot):

    await migrate_users_table()

    user   = event.new_chat_member.user
    status = event.new_chat_member.status
    chat_id = event.chat.id

    await save_user(
        user.id,
        user.username,
        user.first_name,
        user.last_name
    )

    # Только при входе в чат
    if status not in ("member", "restricted"):
        return

    # Записываем дату вступления
    await record_join(chat_id, user.id)

    # ── Проверка глобального бана ─────────────────────────────
    gban = await get_gban(user.id)
    if gban:
        _, _, reason, amnesty, _ = gban
        if not amnesty:
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
                await bot.send_message(
                    chat_id,
                    f"🚫 <b>{user.full_name}</b> исключён — глобальный бан (ОЧС).\n"
                    f"📋 Причина: {reason or '—'}",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return

    # ── Проверка локального бана ──────────────────────────────
    local = await get_local_ban(chat_id, user.id)
    if local:
        reason = local[0]
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            await bot.send_message(
                chat_id,
                f"🔨 <b>{user.full_name}</b> исключён — действует бан в этом чате.\n"
                f"📋 Причина: {reason or '—'}",
                parse_mode="HTML"
            )
        except Exception:
            pass