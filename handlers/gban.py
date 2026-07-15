# handlers/gban.py

import aiosqlite
from datetime import datetime

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import get_admin_level
from utils.logger import log_admin_action, log_command
from utils.permissions import check_adm_lvl
from utils.resolver import resolve_user
from utils.antidrain import register_action
from database import get_gban
from database import get_comments

DB_PATH = "data/bot.db"

router = Router()


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================


async def get_all_chats() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT chat_id FROM chats")
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_user_display(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT first_name, last_name, username FROM users WHERE user_id = ?
        """, (user_id,))
        row = await cursor.fetchone()
    if not row:
        return str(user_id)
    full = " ".join(x for x in [row[0], row[1]] if x).strip()
    if full:
        return full
    return f"@{row[2]}" if row[2] else str(user_id)


def fmt_date(raw: str) -> str:
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m.%y %H:%M")
    except Exception:
        return str(raw)


# ==========================================
# /gban
# ==========================================

@router.message(Command("gban"))
async def gban_handler(message: Message, bot: Bot):

    admin    = message.from_user
    args_raw = message.text.partition(" ")[2].strip()

    if not await check_adm_lvl(message, required_level=3):
        return

    await log_command(
        user_id  = admin.id,
        username = admin.username or str(admin.id),
        command  = "/gban",
        args     = args_raw
    )

    if message.reply_to_message:
        result = await resolve_user(message)
        reason = args_raw or "Причина не указана"
    else:
        parts  = args_raw.split(None, 1)
        if not parts:
            return await message.reply("❌ Использование: /gban @username|id [причина]")
        result = await resolve_user(message, parts[0])
        reason = parts[1].strip() if len(parts) > 1 else "Причина не указана"

    if not result.success:
        return await message.reply(f"❌ {result.error}")

    target_id   = result.user_id
    target_name = result.username or result.first_name or str(target_id)

    if not await check_adm_lvl(message, required_level=3, target_id=target_id):
        return

    existing = await get_gban(target_id)
    if existing:
        return await message.reply(f"❌ @{target_name} уже находится в глобальном бане.")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO gbans(user_id, admin_id, reason, amnesty, created_at)
            VALUES(?,?,?,0,?)
        """, (target_id, admin.id, reason, now))
        await db.commit()

    chats     = await get_all_chats()
    banned_in = 0
    for chat_id in chats:
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
            banned_in += 1
        except Exception:
            pass

    await log_admin_action(
        admin_id    = admin.id,
        admin_name  = admin.username or str(admin.id),
        action      = "GBAN",
        target_id   = target_id,
        target_name = target_name,
        details     = f"{reason} | чатов: {banned_in}/{len(chats)}"
    )

    await register_action(
        bot, message.chat.id,
        admin.id, admin.username or str(admin.id),
        "GBAN"
    )

    await message.reply(
        f"🚫 <b>Глобальный бан выдан</b>\n\n"
        f"👤 Пользователь: @{target_name} [ID: {target_id}]\n"
        f"📋 Причина: {reason}\n"
        f"🔇 Исключён из чатов: {banned_in}/{len(chats)}",
        parse_mode="HTML"
    )


# ==========================================
# /check_gban — пользователь смотрит свой статус
# ==========================================

@router.message(Command("check_gban"))
async def check_gban_handler(message: Message):

    if message.chat.type != "private":
        return await message.reply("❌ Команда доступна только в личных сообщениях с ботом.")

    user_id = message.from_user.id
    row     = await get_gban(user_id)

    if not row:
        return await message.reply(
            "✅ <b>Глобальная блокировка отсутствует</b>\n\n"
            "У вас нет активного ОЧС.",
            parse_mode="HTML"
        )

    _, admin_id, reason, amnesty, created_at = row

    user_display  = await get_user_display(user_id)
    admin_display = await get_user_display(admin_id)

    amnesty_str = (
        "\n\n⚠️ <b>Амнистия активна</b> — вы не исключаетесь из конференций, но ОЧС сохранён."
        if amnesty else ""
    )

    await message.reply(
        f"🚫 <b>Информация о блокировке</b>\n\n"
        f"Пользователь: {user_display}\n"
        f"Выдал: {admin_display}\n"
        f"Причина: {reason}\n"
        f"Дата и время: {fmt_date(created_at)}"
        f"{amnesty_str}",
        parse_mode="HTML"
    )


# ==========================================
# /getban — полная информация (только lvl3)
# ==========================================

@router.message(Command("getban"))
async def getban_handler(message: Message):
 
    if not await check_adm_lvl(message, required_level=2):
        return
 
    args_raw = message.text.partition(" ")[2].strip()
 
    if message.reply_to_message:
        result = await resolve_user(message)
    else:
        if not args_raw:
            return await message.reply("❌ Использование: /getban @username|id|reply")
        result = await resolve_user(message, args_raw.split()[0])
 
    if not result.success:
        return await message.reply(f"❌ {result.error}")
 
    target_id      = result.user_id
    target_display = await get_user_display(target_id)
 
    lines = [f"📋 <b>Досье: {target_display} [ID: <code>{target_id}</code>]</b>\n"]
    found = False
 
    # ── Глобальный бан ────────────────────────────────────────
    gban = await get_gban(target_id)
    if gban:
        found = True
        _, admin_id, reason, amnesty, created_at = gban
        admin_display = await get_user_display(admin_id)
        amnesty_label = " | ⚠️ амнистия активна" if amnesty else ""
        lines.append(
            f"🌐 <b>ОЧС (Глобальный бан)</b>{amnesty_label}\n"
            f"   👤 Выдал: {admin_display}\n"
            f"   📋 Причина: {reason or '—'}\n"
            f"   🕐 Дата: {fmt_date(created_at)}\n"
        )
 
    # ── Локальные баны ────────────────────────────────────────
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT chat_id, admin_id, reason, created_at
            FROM bans WHERE user_id = ?
            ORDER BY created_at DESC
        """, (target_id,))
        bans = await cur.fetchall()
 
    if bans:
        found = True
        lines.append(f"🔒 <b>Локальные баны ({len(bans)})</b>")
        for chat_id, admin_id, reason, created_at in bans:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT title FROM chats WHERE chat_id = ?", (chat_id,)
                )
                chat_row  = await cur.fetchone()
            chat_title    = chat_row[0] if chat_row and chat_row[0] else str(chat_id)
            admin_display = await get_user_display(admin_id)
            lines.append(
                f"   📍 {chat_title}\n"
                f"   👤 Выдал: {admin_display}\n"
                f"   📋 Причина: {reason or '—'}\n"
                f"   🕐 Дата: {fmt_date(created_at)}\n"
            )
 
    # ── Муты ─────────────────────────────────────────────────
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT chat_id, admin_id, reason, until_date, created_at
            FROM mutes WHERE user_id = ?
            ORDER BY created_at DESC
        """, (target_id,))
        mutes = await cur.fetchall()
 
    if mutes:
        found = True
        lines.append(f"🔇 <b>Муты ({len(mutes)})</b>")
        for chat_id, admin_id, reason, until_date, created_at in mutes:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT title FROM chats WHERE chat_id = ?", (chat_id,)
                )
                chat_row  = await cur.fetchone()
            chat_title    = chat_row[0] if chat_row and chat_row[0] else str(chat_id)
            admin_display = await get_user_display(admin_id)
            until_str     = fmt_date(until_date) if until_date else "навсегда"
            lines.append(
                f"   📍 {chat_title}\n"
                f"   👤 Выдал: {admin_display}\n"
                f"   📋 Причина: {reason or '—'}\n"
                f"   ⏳ До: {until_str}\n"
                f"   🕐 Дата: {fmt_date(created_at)}\n"
            )
 
    # ── Варны ────────────────────────────────────────────────
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT amount, reason, active, created_at, admin_id
            FROM warns WHERE user_id = ?
            ORDER BY created_at DESC
        """, (target_id,))
        warns = await cur.fetchall()
 
    if warns:
        found = True
        active_count = sum(w[2] for w in warns)
        lines.append(f"⚠️ <b>Предупреждения</b> (активных: {active_count})")
        for amount, reason, active, created_at, admin_id in warns:
            admin_display = await get_user_display(admin_id)
            status = "🔴 активен" if active else "⚫ снят"
            lines.append(
                f"   {status} | кол-во: {amount}\n"
                f"   👤 Выдал: {admin_display}\n"
                f"   📋 Причина: {reason or '—'}\n"
                f"   🕐 Дата: {fmt_date(created_at)}\n"
            )
 
    # ── Пометки ───────────────────────────────────────────────
    comments = await get_comments(target_id)
    if comments:
        found = True
        lines.append(f"📝 <b>Пометки ({len(comments)})</b>")
        for cid, _, admin_id, text, created_at in comments:
            admin_display = await get_user_display(admin_id)
            lines.append(
                f"   <b>#{cid}</b> | 👤 {admin_display} | 🕐 {fmt_date(created_at)}\n"
                f"   💬 {text}\n"
            )
 
    if not found:
        lines.append("✅ Записей не найдено.")
 
    await message.reply("\n".join(lines), parse_mode="HTML")


# ==========================================
# /amnistiya
# ==========================================

@router.message(Command("amnistiya"))
async def amnistiya_handler(message: Message, bot: Bot):

    admin    = message.from_user
    args_raw = message.text.partition(" ")[2].strip()

    if not await check_adm_lvl(message, required_level=3):
        return

    await log_command(
        user_id  = admin.id,
        username = admin.username or str(admin.id),
        command  = "/amnistiya",
        args     = args_raw
    )

    if message.reply_to_message:
        result   = await resolve_user(message)
        flag_str = args_raw.strip()
    else:
        parts = args_raw.split(None, 1)
        if len(parts) < 2:
            return await message.reply("❌ Использование: /amnistiya @username|id +|-")
        result   = await resolve_user(message, parts[0])
        flag_str = parts[1].strip()

    if not result.success:
        return await message.reply(f"❌ {result.error}")

    if flag_str not in ("+", "-"):
        return await message.reply("❌ Укажите + (включить) или - (выключить) амнистию.")

    target_id   = result.user_id
    target_name = result.username or result.first_name or str(target_id)

    row = await get_gban(target_id)
    if not row:
        return await message.reply(f"❌ @{target_name} не находится в глобальном бане.")

    amnesty     = 1 if flag_str == "+" else 0
    amnesty_now = row[3]

    if amnesty == amnesty_now:
        state = "уже активна" if amnesty else "уже неактивна"
        return await message.reply(f"❌ Амнистия {state} для @{target_name}.")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE gbans SET amnesty = ? WHERE user_id = ?
        """, (amnesty, target_id))
        await db.commit()

    chats = await get_all_chats()

    if amnesty == 1:
        # Разбаниваем — пользователь может зайти, но ОЧС висит
        count = 0
        for chat_id in chats:
            try:
                await bot.unban_chat_member(chat_id=chat_id, user_id=target_id, only_if_banned=True)
                count += 1
            except Exception:
                pass
        extra = f"\n✅ Разбанен в чатах: {count}/{len(chats)} (ОЧС сохранён)"
    else:
        # Снова баним
        count = 0
        for chat_id in chats:
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
                count += 1
            except Exception:
                pass
        extra = f"\n🔇 Снова исключён из чатов: {count}/{len(chats)}"

    await log_admin_action(
        admin_id    = admin.id,
        admin_name  = admin.username or str(admin.id),
        action      = "AMNESTY_ON" if amnesty else "AMNESTY_OFF",
        target_id   = target_id,
        target_name = target_name,
        details     = f"Амнистия {'включена' if amnesty else 'выключена'}"
    )

    icon  = "🕊" if amnesty else "🔒"
    state = "включена" if amnesty else "выключена"

    await message.reply(
        f"{icon} <b>Амнистия {state}</b>\n\n"
        f"👤 Пользователь: @{target_name} [ID: {target_id}]\n"
        f"📋 ОЧС сохранён — статус: «{'амнистирован' if amnesty else 'активный бан'}»."
        f"{extra}",
        parse_mode="HTML"
    )