# handlers/userlog.py

import aiosqlite
from datetime import datetime

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import get_comments
from utils.permissions import check_adm_lvl
from utils.resolver import resolve_user
from database import get_gban

DB_PATH = "data/bot.db"

router = Router()


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ
# ==========================================

def fd(raw) -> str:
    """Форматирует дату."""
    if not raw:
        return "—"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(str(raw), fmt).strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            continue
    return str(raw)


async def get_display(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT first_name, last_name, username FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cur.fetchone()
    if not row:
        return str(user_id)
    full = " ".join(x for x in [row[0], row[1]] if x).strip()
    return full or (f"@{row[2]}" if row[2] else str(user_id))


def section(title: str) -> str:
    return f"\n{'━' * 30}\n{title}\n{'━' * 30}"


# ==========================================
# /log @username|id
# ==========================================

@router.message(Command("log"))
async def log_handler(message: Message, bot: Bot):

    if not await check_adm_lvl(message, required_level=3):
        return

    args = message.text.partition(" ")[2].strip()

    if message.reply_to_message:
        result = await resolve_user(message)
    elif args:
        result = await resolve_user(message, args.split()[0])
    else:
        return await message.reply(
            "❌ Использование: /log @username|id|reply"
        )

    if not result.success:
        return await message.reply(f"❌ {result.error}")

    target_id   = result.user_id
    target_name = await get_display(target_id)

    parts = []

    # ══════════════════════════════════════
    # 1. ПРОФИЛЬ
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id, username, first_name, last_name, last_seen, added_at
            FROM users WHERE user_id = ?
        """, (target_id,))
        user_row = await cur.fetchone()

    if user_row:
        uid, uname, fname, lname, last_seen, added_at = user_row
        full = " ".join(x for x in [fname, lname] if x).strip()
        parts.append(
            section("👤 ПРОФИЛЬ") + "\n"
            f"Имя:       {full or '—'}\n"
            f"Username:  {'@' + uname if uname else '—'}\n"
            f"ID:        {uid}\n"
            f"В БД с:    {fd(added_at)}\n"
            f"Последний онлайн: {fd(last_seen)}"
        )

    # ══════════════════════════════════════
    # 2. СТАТУС АДМИНИСТРАТОРА
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT level, added_by, added_at FROM admins WHERE user_id = ?
        """, (target_id,))
        adm = await cur.fetchone()

        cur = await db.execute("""
            SELECT old_level, reason, removed_at FROM ex_admins WHERE user_id = ?
        """, (target_id,))
        ex_adm = await cur.fetchone()

    adm_block = section("🛡 АДМИНИСТРАТОР")
    if adm:
        added_by = await get_display(adm[1])
        adm_block += (
            f"\nСтатус:    Активный администратор\n"
            f"Уровень:   {adm[0]}\n"
            f"Выдал:     {added_by}\n"
            f"Дата:      {fd(adm[2])}"
        )
    elif ex_adm:
        adm_block += (
            f"\nСтатус:    Бывший администратор\n"
            f"Уровень был: {ex_adm[0]}\n"
            f"Причина снятия: {ex_adm[1] or '—'}\n"
            f"Снят:      {fd(ex_adm[2])}"
        )
    else:
        adm_block += "\nСтатус:    Обычный пользователь"
    parts.append(adm_block)

    # ══════════════════════════════════════
    # 3. ГЛОБАЛЬНЫЙ БАН (ОЧС)
    # ══════════════════════════════════════
    gban = await get_gban(target_id)
    gban_block = section("🌐 ГЛОБАЛЬНЫЙ БАН (ОЧС)")
    if gban:
        _, admin_id, reason, amnesty, created_at = gban
        by = await get_display(admin_id)
        gban_block += (
            f"\nСтатус:    {'⚠️ Амнистия' if amnesty else '🚫 Активен'}\n"
            f"Причина:   {reason or '—'}\n"
            f"Выдал:     {by}\n"
            f"Дата:      {fd(created_at)}"
        )
    else:
        gban_block += "\nОтсутствует"
    parts.append(gban_block)

    # ══════════════════════════════════════
    # 4. ЛОКАЛЬНЫЕ БАНЫ
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT b.chat_id, c.title, b.admin_id, b.reason, b.created_at
            FROM bans b
            LEFT JOIN chats c ON c.chat_id = b.chat_id
            WHERE b.user_id = ?
            ORDER BY b.created_at DESC
        """, (target_id,))
        bans = await cur.fetchall()

    bans_block = section(f"🔒 ЛОКАЛЬНЫЕ БАНЫ ({len(bans)})")
    if bans:
        for i, (chat_id, chat_title, admin_id, reason, created_at) in enumerate(bans, 1):
            by = await get_display(admin_id)
            bans_block += (
                f"\n#{i} {chat_title or chat_id}\n"
                f"   Выдал:   {by}\n"
                f"   Причина: {reason or '—'}\n"
                f"   Дата:    {fd(created_at)}"
            )
    else:
        bans_block += "\nОтсутствуют"
    parts.append(bans_block)

    # ══════════════════════════════════════
    # 5. МУТЫ
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT m.chat_id, c.title, m.admin_id, m.reason, m.until_date, m.created_at
            FROM mutes m
            LEFT JOIN chats c ON c.chat_id = m.chat_id
            WHERE m.user_id = ?
            ORDER BY m.created_at DESC
        """, (target_id,))
        mutes = await cur.fetchall()

    mutes_block = section(f"🔇 МУТЫ ({len(mutes)})")
    if mutes:
        for i, (chat_id, chat_title, admin_id, reason, until_date, created_at) in enumerate(mutes, 1):
            by = await get_display(admin_id)
            mutes_block += (
                f"\n#{i} {chat_title or chat_id}\n"
                f"   Выдал:   {by}\n"
                f"   Причина: {reason or '—'}\n"
                f"   До:      {fd(until_date) if until_date else 'навсегда'}\n"
                f"   Дата:    {fd(created_at)}"
            )
    else:
        mutes_block += "\nОтсутствуют"
    parts.append(mutes_block)

    # ══════════════════════════════════════
    # 6. ПРЕДУПРЕЖДЕНИЯ
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT admin_id, amount, reason, active, created_at
            FROM warns WHERE user_id = ?
            ORDER BY created_at DESC
        """, (target_id,))
        warns = await cur.fetchall()

    active_warns = sum(w[3] for w in warns)
    warns_block  = section(f"⚠️ ПРЕДУПРЕЖДЕНИЯ ({len(warns)}, активных: {active_warns})")
    if warns:
        for i, (admin_id, amount, reason, active, created_at) in enumerate(warns, 1):
            by     = await get_display(admin_id)
            status = "🔴 активен" if active else "⚫ снят"
            warns_block += (
                f"\n#{i} {status} | кол-во: {amount}\n"
                f"   Выдал:   {by}\n"
                f"   Причина: {reason or '—'}\n"
                f"   Дата:    {fd(created_at)}"
            )
    else:
        warns_block += "\nОтсутствуют"
    parts.append(warns_block)

    # ══════════════════════════════════════
    # 7. ОЧКИ
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT COALESCE(SUM(points), 0) FROM points WHERE user_id = ?
        """, (target_id,))
        total_pts = (await cur.fetchone())[0]

        cur = await db.execute("""
            SELECT admin_id, points, reason, created_at
            FROM points WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 10
        """, (target_id,))
        pts_rows = await cur.fetchall()

    pts_block = section(f"🏅 ОЧКИ (итого: {total_pts})")
    if pts_rows:
        for admin_id, pts, reason, created_at in pts_rows:
            by   = await get_display(admin_id)
            sign = f"+{pts}" if pts > 0 else str(pts)
            pts_block += (
                f"\n{sign} | {by}\n"
                f"   Причина: {reason or '—'}\n"
                f"   Дата:    {fd(created_at)}"
            )
        if len(pts_rows) == 10:
            pts_block += "\n\n[показаны последние 10 записей]"
    else:
        pts_block += "\nЗаписей нет"
    parts.append(pts_block)

    # ══════════════════════════════════════
    # 8. ДЕЙСТВИЯ АДМИНИСТРАТОРА (если сам админ)
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT action, target_id, details, created_at
            FROM admin_logs WHERE admin_id = ?
            ORDER BY created_at DESC LIMIT 15
        """, (target_id,))
        admin_actions = await cur.fetchall()

    if admin_actions:
        aa_block = section(f"⚡ ДЕЙСТВИЯ КАК АДМИНИСТРАТОР (последние {len(admin_actions)})")
        for action, t_id, details, created_at in admin_actions:
            t_name = await get_display(t_id) if t_id else "—"
            aa_block += (
                f"\n{fd(created_at)}\n"
                f"   Действие: {action}\n"
                f"   Цель:     {t_name} [{t_id}]\n"
                f"   Детали:   {(details or '—')[:80]}"
            )
        parts.append(aa_block)

    # ══════════════════════════════════════
    # 9. ДЕЙСТВИЯ НАД ПОЛЬЗОВАТЕЛЕМ
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT admin_id, action, details, created_at
            FROM admin_logs WHERE target_id = ?
            ORDER BY created_at DESC LIMIT 15
        """, (target_id,))
        actions_on = await cur.fetchall()

    if actions_on:
        ao_block = section(f"🎯 ДЕЙСТВИЯ НАД ПОЛЬЗОВАТЕЛЕМ (последние {len(actions_on)})")
        for admin_id, action, details, created_at in actions_on:
            by = await get_display(admin_id)
            ao_block += (
                f"\n{fd(created_at)}\n"
                f"   Действие: {action}\n"
                f"   Выдал:    {by}\n"
                f"   Детали:   {(details or '—')[:80]}"
            )
        parts.append(ao_block)

    # ══════════════════════════════════════
    # 10. КОМАНДЫ ПОЛЬЗОВАТЕЛЯ
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT command, args, created_at
            FROM command_logs WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 15
        """, (target_id,))
        cmds = await cur.fetchall()

    if cmds:
        cmd_block = section(f"⌨️ КОМАНДЫ ПОЛЬЗОВАТЕЛЯ (последние {len(cmds)})")
        for command, args, created_at in cmds:
            cmd_block += (
                f"\n{fd(created_at)}  {command}\n"
                f"   Аргументы: {(args or '—')[:80]}"
            )
        parts.append(cmd_block)

    # ══════════════════════════════════════
    # 11. АКТИВНОСТЬ В ЧАТАХ
    # ══════════════════════════════════════
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT cl.chat_id, c.title,
                   COUNT(*) as msg_count,
                   MAX(cl.created_at) as last_msg
            FROM chat_logs cl
            LEFT JOIN chats c ON c.chat_id = cl.chat_id
            WHERE cl.user_id = ?
            GROUP BY cl.chat_id
            ORDER BY msg_count DESC
        """, (target_id,))
        activity = await cur.fetchall()

    act_block = section(f"📊 АКТИВНОСТЬ В ЧАТАХ ({len(activity)})")
    if activity:
        for chat_id, chat_title, msg_count, last_msg in activity:
            act_block += (
                f"\n{chat_title or chat_id}\n"
                f"   Сообщений:    {msg_count}\n"
                f"   Последнее:    {fd(last_msg)}"
            )
    else:
        act_block += "\nНет данных"
    parts.append(act_block)

    # ══════════════════════════════════════
    # 12. ПОМЕТКИ
    # ══════════════════════════════════════
    comments = await get_comments(target_id)
    com_block = section(f"📝 ПОМЕТКИ ({len(comments)})")
    if comments:
        for cid, user_id, admin_id, text, created_at in comments:
            by = await get_display(admin_id)
            com_block += (
                f"\n#{cid} | {fd(created_at)}\n"
                f"   Автор:   {by}\n"
                f"   Текст:   {text}"
            )
    else:
        com_block += "\nОтсутствуют"
    parts.append(com_block)

    # ══════════════════════════════════════
    # СБОРКА И ОТПРАВКА
    # ══════════════════════════════════════
    header = (
        f"📂 <b>ПОЛНОЕ ДОСЬЕ</b>\n"
        f"Пользователь: <b>{target_name}</b> [ID: <code>{target_id}</code>]\n"
        f"Сформировано: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )

    full_text = header + "\n" + "\n".join(parts)

    # Telegram лимит 4096 символов — разбиваем на части
    chunk_size = 4000
    chunks     = []
    current    = ""

    for line in full_text.split("\n"):
        if len(current) + len(line) + 1 > chunk_size:
            chunks.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        chunks.append(current)

    for i, chunk in enumerate(chunks):
        if i == 0:
            await message.reply(
                f"<pre>{chunk}</pre>",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"<pre>{chunk}</pre>",
                parse_mode="HTML"
            )