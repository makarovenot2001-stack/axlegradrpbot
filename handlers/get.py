# handlers/get.py

import aiosqlite
from datetime import datetime

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import get_user, save_user
from utils.resolver import resolve_user

DB_PATH = "data/bot.db"

router = Router()


# ==========================================
# МИГРАЦИЯ — добавить колонку added_at
# Вызывается при старте один раз
# ==========================================

async def migrate_users_table():
    async with aiosqlite.connect(DB_PATH) as db:
        # added_at — дата первого появления в БД
        try:
            await db.execute("ALTER TABLE users ADD COLUMN added_at TIMESTAMP")
            await db.commit()
        except Exception:
            pass  # колонка уже есть

        # chat_members — дата вступления в конкретный чат
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_members(
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id   INTEGER NOT NULL,
                user_id   INTEGER NOT NULL,
                joined_at TIMESTAMP,
                UNIQUE(chat_id, user_id)
            )
        """)
        await db.commit()


# ==========================================
# ЗАПИСЬ ПЕРВОГО ПОЯВЛЕНИЯ
# Вызывать вместо/после save_user
# ==========================================

async def save_user_first_seen(
    user_id:    int,
    username:   str | None,
    first_name: str | None,
    last_name:  str | None
):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users(user_id, username, first_name, last_name, last_seen, added_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                last_name  = excluded.last_name,
                last_seen  = excluded.last_seen,
                added_at   = COALESCE(users.added_at, excluded.added_at)
        """, (user_id, username, first_name, last_name, now, now))
        await db.commit()


# ==========================================
# ЗАПИСЬ ВСТУПЛЕНИЯ В ЧАТ
# ==========================================

async def record_join(chat_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO chat_members(chat_id, user_id, joined_at)
            VALUES(?,?,?)
        """, (chat_id, user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await db.commit()


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def fmt_date(raw) -> str:
    if not raw:
        return "нет данных"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(str(raw), fmt).strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            continue
    return str(raw)


def fmt_duration(seconds: int) -> str:
    days    = seconds // 86400
    hours   = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs    = seconds % 60
    parts   = []
    if days:    parts.append(f"{days} дн.")
    if hours:   parts.append(f"{hours} ч.")
    if minutes: parts.append(f"{minutes} мин.")
    parts.append(f"{secs} сек.")
    return " ".join(parts)


async def get_message_count(user_id: int, chat_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT COUNT(*) FROM chat_logs
            WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        row = await cur.fetchone()
    return row[0] if row else 0


async def get_joined_at(user_id: int, chat_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        # Сначала chat_members
        cur = await db.execute("""
            SELECT joined_at FROM chat_members
            WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        row = await cur.fetchone()
        if row and row[0]:
            return row[0]

        # Fallback — первое сообщение в этом чате из chat_logs
        cur = await db.execute("""
            SELECT MIN(created_at) FROM chat_logs
            WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        row = await cur.fetchone()
        if row and row[0]:
            # Пишем в chat_members чтобы не считать повторно
            await db.execute("""
                INSERT OR IGNORE INTO chat_members(chat_id, user_id, joined_at)
                VALUES(?,?,?)
            """, (chat_id, user_id, row[0]))
            await db.commit()
            return row[0]

    return None


async def get_last_message(user_id: int, chat_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT MAX(created_at) FROM chat_logs
            WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        row = await cur.fetchone()
    return row[0] if row and row[0] else None


async def try_fetch_from_tg(bot: Bot, user_id: int) -> dict | None:
    try:
        chat = await bot.get_chat(user_id)
        await save_user_first_seen(
            chat.id, chat.username,
            chat.first_name, chat.last_name
        )
        return {
            "user_id":    chat.id,
            "username":   chat.username,
            "first_name": chat.first_name,
            "last_name":  chat.last_name,
        }
    except Exception:
        return None


# ==========================================
# /get
# ==========================================

@router.message(Command("get"))
async def get_handler(message: Message, bot: Bot):

    await migrate_users_table()

    args_raw  = message.text.partition(" ")[2].strip()
    chat_id   = message.chat.id
    chat_name = message.chat.title or "Личка"
    from_tg   = False

    # ── Определяем цель ───────────────────────────────────────
    if args_raw == "+" or (not args_raw and not message.reply_to_message):
        u          = message.from_user
        target_id  = u.id
        username   = u.username
        first_name = u.first_name
        last_name  = u.last_name

    elif args_raw == "-" or message.reply_to_message:
        result = await resolve_user(message)
        if not result.success:
            return await message.reply(f"❌ {result.error}")
        target_id  = result.user_id
        username   = result.username
        first_name = result.first_name
        row        = await get_user(target_id)
        last_name  = row[3] if row else None

    else:
        token  = args_raw.split()[0]
        result = await resolve_user(message, token)

        if result.success:
            target_id  = result.user_id
            username   = result.username
            first_name = result.first_name
            row        = await get_user(target_id)
            last_name  = row[3] if row else None
        elif token.lstrip("-").isdigit():
            data = await try_fetch_from_tg(bot, int(token))
            if not data:
                return await message.reply(
                    "❌ Пользователь не найден ни в базе, ни в Telegram."
                )
            target_id  = data["user_id"]
            username   = data["username"]
            first_name = data["first_name"]
            last_name  = data["last_name"]
            from_tg    = True
        else:
            return await message.reply(
                f"❌ {result.error}\n"
                f"Поиск по username доступен только для пользователей которых бот встречал в чатах.\n"
                f"Попробуйте указать числовой ID."
            )

    # ── Если найден только через TG API ──────────────────────
    full_name = " ".join(x for x in [first_name, last_name] if x).strip()
    handle    = f"@{username}" if username else full_name or str(target_id)

    if from_tg:
        return await message.reply(
            f"┏ Краткая информация о {full_name or handle}\n"
            f"┗ Пользователь не найден в конференциях бота\n\n"
            f"ID: <code>{target_id}</code>\n"
            f"Имя: {full_name or '—'}\n"
            f"Username: {handle}\n\n"
            f"✅ Добавлен в базу данных.",
            parse_mode="HTML"
        )

    # ── Собираем данные ───────────────────────────────────────
    row        = await get_user(target_id)
    added_at   = fmt_date(row[5] if row and len(row) > 5 else None)
    joined_at  = await get_joined_at(target_id, chat_id)
    last_msg   = await get_last_message(target_id, chat_id)
    msg_count  = await get_message_count(target_id, chat_id)

    joined_str = fmt_date(joined_at)
    last_str   = fmt_date(last_msg)

    if joined_at:
        try:
            jdt      = datetime.strptime(joined_at, "%Y-%m-%d %H:%M:%S")
            duration = fmt_duration(int((datetime.now() - jdt).total_seconds()))
        except Exception:
            duration = "нет данных"
    else:
        duration = "нет данных"

    # ── Вывод ────────────────────────────────────────────────
    lines = [
        f"┏ Информация о {full_name or handle}",
        f"┗ Беседа: {chat_name} [ID: <code>{chat_id}</code>]\n",
        f"Пользователь: <a href='tg://user?id={target_id}'>{full_name or handle}</a>",
        f"Количество сообщений: {msg_count}",
        f"Добавлен в БД: {added_at}",
        f"Последнее сообщение: {last_str}",
        f"Добавлен в конференцию: {joined_str}",
        f"Время нахождения: {duration}",
    ]

    await message.reply(
        "\n".join(lines),
        parse_mode               = "HTML",
        disable_web_page_preview = True
    )