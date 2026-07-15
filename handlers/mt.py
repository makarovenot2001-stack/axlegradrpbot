# handlers/mt.py

import aiosqlite
from datetime import datetime

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import get_admin_level, get_all_admins
from utils.logger import log_command, log_system
from utils.permissions import check_adm_lvl

DB_PATH = "data/bot.db"

router = Router()


# ==========================================
# ИНИЦИАЛИЗАЦИЯ ТАБЛИЦЫ
# ==========================================

async def init_mt_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_members_list(
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                full_name  TEXT,
                username   TEXT,
                added_at   TIMESTAMP,
                UNIQUE(chat_id, user_id)
            )
        """)
        await db.commit()


async def upsert_member(chat_id: int, user_id: int, full_name: str, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO chat_members_list(chat_id, user_id, full_name, username, added_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                full_name = excluded.full_name,
                username  = excluded.username
        """, (chat_id, user_id, full_name, username,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await db.commit()


async def get_chat_members(chat_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id, full_name, username
            FROM chat_members_list WHERE chat_id = ?
        """, (chat_id,))
        return await cur.fetchall()


# ==========================================
# /sync — заполнить участников чата
# ==========================================

@router.message(Command("sync"))
async def sync_handler(message: Message, bot: Bot):

    if not await check_adm_lvl(message, required_level=2):
        return

    await init_mt_table()

    chat_id = message.chat.id
    msg     = await message.reply("⏳ Синхронизирую участников...")

    count  = 0
    failed = 0

    # Берём всех из users которые писали в этом чате
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT DISTINCT u.user_id, u.first_name, u.last_name, u.username
            FROM users u
            INNER JOIN chat_logs cl ON cl.user_id = u.user_id
            WHERE cl.chat_id = ?
        """, (chat_id,))
        rows = await cur.fetchall()

    for user_id, first_name, last_name, username in rows:
        # Проверяем что пользователь ещё в чате
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in ("left", "kicked", "banned"):
                continue
            full_name = " ".join(x for x in [first_name, last_name] if x).strip() or str(user_id)
            await upsert_member(chat_id, user_id, full_name, username)
            count += 1
        except Exception:
            failed += 1

    await msg.edit_text(
        f"✅ Синхронизация завершена.\n\n"
        f"👥 Добавлено участников: {count}\n"
        f"⚠️ Не удалось проверить: {failed}"
    )

    await log_command(
        message.from_user.id,
        message.from_user.username or str(message.from_user.id),
        "/sync",
        f"chat={chat_id} synced={count}"
    )


# ==========================================
# /mt — упоминание участников
# Использование:
#   /mt =0 [текст] [-m]   — все участники
#   /mt =1 [текст] [-m]   — админы уровня 1
#   /mt =2 [текст] [-m]   — админы уровня 2
#   /mt =3 [текст] [-m]   — админы уровня 3
#   -m — отправить в ЛС
# ==========================================

@router.message(Command("mt"))
async def mt_handler(message: Message, bot: Bot):

    if not await check_adm_lvl(message, required_level=2):
        return

    await init_mt_table()

    args = message.text.split(None, 2)

    if len(args) < 2 or args[1] not in ("=0", "=1", "=2", "=3"):
        return await message.reply(
            "❌ Использование:\n"
            "/mt =0 [текст] [-m] — все участники\n"
            "/mt =1|=2|=3 [текст] [-m] — админы уровня N\n\n"
            "<i>-m в конце — отправить в личные сообщения</i>",
            parse_mode="HTML"
        )

    mode     = args[1]
    raw_text = args[2].strip() if len(args) > 2 else ""

    # Флаг -m
    send_pm = raw_text.endswith("-m")
    if send_pm:
        raw_text = raw_text[:-2].strip()

    # Текст из реплая если не указан
    media_msg = message.reply_to_message
    if not raw_text and media_msg and media_msg.text:
        raw_text = media_msg.text

    chat_id    = message.chat.id
    admin      = message.from_user
    chat_title = message.chat.title or "Чат"
    bot_id     = (await bot.get_me()).id

    # ── Собираем список целей ─────────────────────────────────
    if mode == "=0":
        # Все участники кроме бота и админов 3 уровня
        all_members = await get_chat_members(chat_id)
        all_admins  = await get_all_admins()
        high_ids    = {a[0] for a in all_admins if a[1] >= 3}
        targets     = [
            (uid, fname, uname)
            for uid, fname, uname in all_members
            if uid != bot_id and uid not in high_ids
        ]
    else:
        level      = int(mode[1:])
        all_admins = await get_all_admins()
        admin_ids  = {a[0] for a in all_admins if a[1] == level}

        all_members = await get_chat_members(chat_id)
        targets     = [
            (uid, fname, uname)
            for uid, fname, uname in all_members
            if uid in admin_ids
        ]

    if not targets:
        return await message.reply(
            "❌ Нет подходящих участников.\n"
            "Используй /sync чтобы загрузить список участников чата."
        )

    # ── Рассылка ─────────────────────────────────────────────
    mentioned = []
    failed    = []
    now_str   = datetime.now().strftime("%d.%m.%Y %H:%M")

    for user_id, full_name, username in targets:
        name_link = f'<a href="tg://user?id={user_id}">{full_name}</a>'
        try:
            if send_pm:
                notify = (
                    f"🔔 <b>Уведомление</b>\n\n"
                    f"Беседа: «{chat_title}»\n"
                    f"Время: {now_str}\n"
                    f"Отправитель: "
                    f'<a href="tg://user?id={admin.id}">{admin.full_name}</a>\n\n'
                    f"Сообщение: {raw_text or '(без текста)'}"
                )
                await bot.send_message(user_id, notify, parse_mode="HTML")

                # Пересылаем медиа если есть
                if media_msg:
                    if media_msg.photo:
                        await bot.send_photo(
                            user_id, media_msg.photo[-1].file_id,
                            caption=raw_text or None
                        )
                    elif media_msg.video:
                        await bot.send_video(
                            user_id, media_msg.video.file_id,
                            caption=raw_text or None
                        )
                    elif media_msg.document:
                        await bot.send_document(
                            user_id, media_msg.document.file_id,
                            caption=raw_text or None
                        )
                    elif media_msg.voice:
                        await bot.send_voice(user_id, media_msg.voice.file_id)
                    elif media_msg.audio:
                        await bot.send_audio(
                            user_id, media_msg.audio.file_id,
                            caption=raw_text or None
                        )
                    elif media_msg.animation:
                        await bot.send_animation(
                            user_id, media_msg.animation.file_id,
                            caption=raw_text or None
                        )
                    elif media_msg.sticker:
                        await bot.send_sticker(user_id, media_msg.sticker.file_id)

            mentioned.append(name_link)

        except Exception:
            failed.append(name_link)

    # ── Ответ в чат ───────────────────────────────────────────
    mentions_str = " ".join(mentioned) if mentioned else "—"

    response = (
        f"📢 <b>Упомянуты:</b>\n\n"
        f"{mentions_str}\n\n"
        f'Отправитель: <a href="tg://user?id={admin.id}">{admin.full_name}</a>\n'
        f"Сообщение: {raw_text or '(без текста)'}"
    )

    if send_pm and failed:
        response += f"\n\n❗ Не доставлено ({len(failed)}): {' '.join(failed)}"

    await message.reply(response, parse_mode="HTML")

    await log_command(
        admin.id,
        admin.username or str(admin.id),
        "/mt",
        f"mode={mode} pm={send_pm} targets={len(mentioned)} failed={len(failed)}"
    )