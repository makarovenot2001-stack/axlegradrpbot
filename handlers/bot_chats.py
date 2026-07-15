# handlers/bot_chats.py

import aiosqlite

from aiogram import Router, Bot
from aiogram.types import ChatMemberUpdated
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter

DB_PATH = "data/bot.db"

router = Router()


# ==========================================
# БОТ ДОБАВЛЕН В ЧАТ
# ==========================================

@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def bot_added(event: ChatMemberUpdated, bot: Bot):

    chat = event.chat

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO chats(chat_id, title, branch_id)
            VALUES(?,?,NULL)
            ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title
        """, (chat.id, chat.title or ""))
        await db.commit()


# ==========================================
# БОТ УДАЛЁН / ПОКИНУЛ ЧАТ
# ==========================================a

@router.my_chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def bot_removed(event: ChatMemberUpdated):

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM chats WHERE chat_id = ?
        """, (event.chat.id,))
        await db.commit()