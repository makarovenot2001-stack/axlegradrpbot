# handlers/info.py

import aiosqlite
from datetime import datetime

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import get_admin_level
from utils.resolver import resolve_user

DB_PATH = "data/bot.db"

router = Router()


# ==========================================
# /getid — узнать свой ID или ID пользователя
# ==========================================

@router.message(Command("getid"))
async def getid_handler(message: Message):

    # Если реплай — возвращаем ID того на кого ответили
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        name = user.full_name
        lines = [
            f"👤 <b>{name}</b>",
            f"ID: <code>{user.id}</code>",
        ]
        if user.username:
            lines.append(f"Username: @{user.username}")
        return await message.reply("\n".join(lines), parse_mode="HTML")

    args = message.text.partition(" ")[2].strip()

    # Если передан аргумент — ищем пользователя
    if args:
        result = await resolve_user(message, args)
        if not result.success:
            return await message.reply(f"❌ {result.error}")
        handle = f"@{result.username}" if result.username else result.first_name or str(result.user_id)
        return await message.reply(
            f"👤 <b>{handle}</b>\n"
            f"ID: <code>{result.user_id}</code>",
            parse_mode="HTML"
        )

    # Без аргументов — о себе
    user = message.from_user
    lines = [
        f"👤 <b>{user.full_name}</b>",
        f"ID: <code>{user.id}</code>",
    ]
    if user.username:
        lines.append(f"Username: @{user.username}")

    await message.reply("\n".join(lines), parse_mode="HTML")


# ==========================================
# /getidgroup /getidgp — ID текущего чата
# ==========================================

@router.message(Command("getidgroup", "getidgp"))
async def getidgroup_handler(message: Message, bot: Bot):

    chat    = message.chat
    chat_id = chat.id

    lines = [
        f"💬 <b>{chat.title or 'Личка'}</b>",
        f"ID: <code>{chat_id}</code>",
        f"Тип: {chat.type}",
    ]

    # Если супергруппа — показываем username чата если есть
    if chat.username:
        lines.append(f"Username: @{chat.username}")

    # Invite link если есть
    try:
        full_chat = await bot.get_chat(chat_id)
        if full_chat.invite_link:
            lines.append(f"Ссылка: {full_chat.invite_link}")
    except Exception:
        pass

    await message.reply("\n".join(lines), parse_mode="HTML")


# ==========================================
# /chatinfo — подробная информация о чате
# ==========================================

@router.message(Command("chatinfo"))
async def chatinfo_handler(message: Message, bot: Bot):

    level = await get_admin_level(message.from_user.id)
    if level < 1:
        return await message.reply("❌ Недостаточно прав.")

    chat    = message.chat
    chat_id = chat.id

    try:
        full_chat    = await bot.get_chat(chat_id)
        members_count = await bot.get_chat_member_count(chat_id)
    except Exception as e:
        return await message.reply(f"❌ Не удалось получить данные: {e}")

    # Данные из нашей БД
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM chat_logs WHERE chat_id = ?",
            (chat_id,)
        )
        active_users = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM chat_logs WHERE chat_id = ?",
            (chat_id,)
        )
        total_msgs = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM bans WHERE chat_id = ?",
            (chat_id,)
        )
        total_bans = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM mutes WHERE chat_id = ?",
            (chat_id,)
        )
        total_mutes = (await cur.fetchone())[0]

        # Ветка чата
        cur = await db.execute("""
            SELECT b.name FROM branches b
            INNER JOIN branch_chats bc ON bc.branch_id = b.id
            WHERE bc.chat_id = ?
        """, (chat_id,))
        branch_row = await cur.fetchone()
        branch     = branch_row[0] if branch_row else "—"

    lines = [
        f"💬 <b>Информация о чате</b>\n",
        f"Название: <b>{full_chat.title or '—'}</b>",
        f"ID: <code>{chat_id}</code>",
        f"Тип: {chat.type}",
        f"Ветка: {branch}",
    ]
    if full_chat.username:
        lines.append(f"Username: @{full_chat.username}")
    if full_chat.invite_link:
        lines.append(f"Ссылка: {full_chat.invite_link}")
    if full_chat.description:
        lines.append(f"Описание: {full_chat.description[:100]}")

    lines += [
        f"\n👥 Участников (Telegram): {members_count}",
        f"📊 Сообщений в БД: {total_msgs}",
        f"👤 Уникальных авторов: {active_users}",
        f"🔨 Банов выдано: {total_bans}",
        f"🔇 Мутов выдано: {total_mutes}",
    ]

    await message.reply("\n".join(lines), parse_mode="HTML")


# ==========================================
# /whois — краткая справка о пользователе
# (для всех, без детальных логов)
# ==========================================

@router.message(Command("whois"))
async def whois_handler(message: Message):

    args = message.text.partition(" ")[2].strip()

    if message.reply_to_message:
        result = await resolve_user(message)
    elif args:
        result = await resolve_user(message, args.split()[0])
    else:
        return await message.reply(
            "❌ Использование: /whois @username|id|reply"
        )

    if not result.success:
        return await message.reply(f"❌ {result.error}")

    target_id = result.user_id

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT username, first_name, last_name, last_seen, added_at
            FROM users WHERE user_id = ?
        """, (target_id,))
        row = await cur.fetchone()

    if not row:
        return await message.reply("❌ Пользователь не найден в базе.")

    username, first_name, last_name, last_seen, added_at = row
    full_name = " ".join(x for x in [first_name, last_name] if x).strip()
    handle    = f"@{username}" if username else full_name or str(target_id)

    def fd(raw):
        if not raw:
            return "—"
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
            try:
                return datetime.strptime(str(raw), fmt).strftime("%d.%m.%y %H:%M")
            except Exception:
                continue
        return str(raw)

    # Уровень администратора
    level     = await get_admin_level(target_id)
    level_str = f"Администратор {level} уровня" if level > 0 else "Пользователь"

    lines = [
        f"👤 <b>{full_name or handle}</b>",
        f"ID: <code>{target_id}</code>",
    ]
    if username:
        lines.append(f"Username: @{username}")
    lines += [
        f"Роль: {level_str}",
        f"Добавлен в БД: {fd(added_at)}",
        f"Последняя активность: {fd(last_seen)}",
    ]

    await message.reply("\n".join(lines), parse_mode="HTML")


# ==========================================
# /myid — быстро узнать свой ID (для всех)
# ==========================================

@router.message(Command("myid"))
async def myid_handler(message: Message):
    user = message.from_user
    await message.reply(
        f"🆔 Ваш ID: <code>{user.id}</code>",
        parse_mode="HTML"
    )


# ==========================================
# /ping — проверка работы бота
# ==========================================

@router.message(Command("ping"))
async def ping_handler(message: Message, bot: Bot):
    sent = await message.reply("⏳")
    delta = (sent.date - message.date).total_seconds()
    await sent.edit_text(f"🏓 Pong! <code>{abs(delta * 1000):.0f}ms</code>", parse_mode="HTML")