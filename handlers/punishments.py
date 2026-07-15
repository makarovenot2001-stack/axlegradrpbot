# handlers/punishments.py

"""
/kick   — кик (lvl 2+)
/ban    — бан в текущем чате (lvl 2+)
/unban  — разбан в текущем чате (lvl 2+)
/mute   — мут в текущем чате (lvl 2+)
/unmute — снять мут в текущем чате (lvl 2+)

/lkick  — кик во всех чатах ветки (lvl 3)
/lban   — бан во всех чатах ветки (lvl 3)
/lunban — разбан во всех чатах ветки (lvl 3)
/lmute  — мут во всех чатах ветки (lvl 3)
/lunmute— снять мут во всех чатах ветки (lvl 3)

Логирование: admin.log | chat.log | commands.log | БД (admin_logs, bans, mutes)
Анти-слив:   register_action после каждого успешного действия
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message, ChatPermissions
from handlers.gban import get_gban

from database import get_admin_level
from utils.antidrain import register_action
from utils.resolver import resolve_user
from utils.logger import (
    log_admin_action,
    log_command,
    log_system,
)

DB_PATH = "data/bot.db"

router = Router()


# ═══════════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════

# ── Проверка уровня ─────────────────────────────────────────────

async def _check_level(message: Message, required: int) -> bool:
    """
    Проверяет уровень администратора.
    Отвечает и возвращает False если прав недостаточно.
    """
    level = await get_admin_level(message.from_user.id)

    if level < required:
        await message.reply(
            f"❌ Недостаточно прав. "
            f"Требуется уровень <b>{required}+</b>, "
            f"у вас <b>{level}</b>.",
            parse_mode="HTML"
        )
        return False

    return True


# ── Разбор цели ─────────────────────────────────────────────────

async def _resolve_target(
    message: Message
) -> tuple[int | None, str]:
    """
    Возвращает (user_id, display_name) цели.
    Порядок: reply → аргумент (@username / числовой id).
    """

    # 1. Reply
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.full_name

    # 2. Аргумент
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        return None, ""

    arg = parts[1].lstrip("@")

    # числовой id
    if arg.isdigit():
        uid = int(arg)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT first_name FROM users WHERE user_id=?", (uid,)
            ) as cur:
                row = await cur.fetchone()
        name = row["first_name"] if row else str(uid)
        return uid, name

    # @username
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, first_name FROM users WHERE username=?",
            (arg,)
        ) as cur:
            row = await cur.fetchone()

    if row:
        return row["user_id"], row["first_name"]

    return None, arg


# ── Парсер длительности мута ─────────────────────────────────────

_DURATION_RE = re.compile(
    r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$",
    re.IGNORECASE
)


def _parse_duration(token: str | None) -> timedelta | None:
    """
    '30m' → timedelta(minutes=30)
    '2h'  → timedelta(hours=2)
    '1d'  → timedelta(days=1)
    '1h30m' → timedelta(hours=1, minutes=30)
    Возвращает None если не распознано.
    """
    if not token:
        return None

    m = _DURATION_RE.match(token.strip())
    if not m or not any(m.groups()):
        return None

    days    = int(m.group(1)) if m.group(1) else 0
    hours   = int(m.group(2)) if m.group(2) else 0
    minutes = int(m.group(3)) if m.group(3) else 0

    delta = timedelta(days=days, hours=hours, minutes=minutes)
    return delta if delta.total_seconds() > 0 else None


# ── Причина и длительность из хвоста команды ────────────────────

def _parse_tail(
    message: Message,
    has_target_arg: bool
) -> tuple[timedelta | None, str | None]:
    """
    Разбирает хвост команды после команды [+ цели если not reply].
    Возвращает (duration | None, reason | None).
    """
    parts = message.text.split()

    # сдвиг: 1 (команда) + 1 (цель-аргумент если не reply)
    offset = 1 + (1 if has_target_arg else 0)
    tail   = parts[offset:]  # всё после команды [+ цели]

    if not tail:
        return None, None

    duration = _parse_duration(tail[0])

    if duration:
        reason = " ".join(tail[1:]) or None
    else:
        reason = " ".join(tail) or None

    return duration, reason


# ── Запись в таблицу bans ────────────────────────────────────────

async def _db_ban(
    chat_id:  int,
    user_id:  int,
    admin_id: int,
    reason:   str | None
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO bans(chat_id, user_id, admin_id, reason, created_at)
            VALUES(?,?,?,?,?)
            """,
            (chat_id, user_id, admin_id, reason, datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
        )
        await db.commit()
        return cur.lastrowid


# ── Запись в таблицу mutes ───────────────────────────────────────

async def _db_mute(
    chat_id:    int,
    user_id:    int,
    admin_id:   int,
    reason:     str | None,
    until_date: datetime | None
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO mutes(chat_id, user_id, admin_id, reason, until_date, created_at)
            VALUES(?,?,?,?,?,?)
            """,
            (
                chat_id, user_id, admin_id, reason,
                until_date.strftime("%d.%m.%Y %H:%M:%S") if until_date else None,
                datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            )
        )
        await db.commit()
        return cur.lastrowid


# ── Список chat_id ветки текущего чата ──────────────────────────

async def _get_branch_chat_ids(
    chat_id: int
) -> tuple[list[int], str] | tuple[None, None]:
    """
    Возвращает ([chat_ids], branch_name) или (None, None).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT b.id, b.name
            FROM branch_chats bc
            JOIN branches b ON b.id = bc.branch_id
            WHERE bc.chat_id = ?
            """,
            (chat_id,)
        ) as cur:
            branch = await cur.fetchone()

        if not branch:
            return None, None

        async with db.execute(
            "SELECT chat_id FROM branch_chats WHERE branch_id = ?",
            (branch["id"],)
        ) as cur:
            rows = await cur.fetchall()

    return [r["chat_id"] for r in rows], branch["name"]


async def _db_add_comment(user_id: int, admin_id: int, text: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO comments(user_id, admin_id, text, created_at)
            VALUES(?,?,?,?)
        """, (user_id, admin_id, text,
              datetime.now().strftime("%d.%m.%Y %H:%M:%S")))
        await db.commit()
        return cur.lastrowid
 
 
async def _db_delete_comment(comment_id: int, admin_id: int) -> bool:
    """Удаляет пометку по ID. Возвращает True если строка найдена."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM comments WHERE id = ?", (comment_id,)
        )
        row = await cur.fetchone()
        if not row:
            return False
        await db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        await db.commit()
    return True
 
 
async def _db_get_comments(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, admin_id, text, created_at
            FROM comments WHERE user_id = ?
            ORDER BY id DESC
        """, (user_id,))
        return await cur.fetchall()


async def get_user_display(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT first_name, last_name, username FROM users WHERE user_id = ?
        """, (user_id,))
        row = await cur.fetchone()
    if not row:
        return str(user_id)
    full = " ".join(x for x in [row[0], row[1]] if x).strip()
    return full or (f"@{row[2]}" if row[2] else str(user_id))
 
 
def fmt_date(raw) -> str:
    if not raw:
        return "—"
    for fmt in ("%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(raw), fmt).strftime("%d.%m.%y %H:%M")
        except Exception:
            continue
    return str(raw)[:16]

# ═══════════════════════════════════════════════════════════════
#  ГЛОБАЛЬНЫЕ КОМАНДЫ (lvl 2+)
# ═══════════════════════════════════════════════════════════════

# ── /kick ────────────────────────────────────────────────────────

@router.message(Command("kick"))
async def cmd_kick(message: Message, bot: Bot):

    if not await _check_level(message, 2):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /kick <reply | @username | id> [причина]"
        )
        return

    has_arg   = not bool(message.reply_to_message)
    _, reason = _parse_tail(message, has_arg)

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)
    chat_id    = message.chat.id

    await log_command(
        admin_id, admin_name,
        "kick",
        f"target={target_name}({target_id}) reason={reason or '—'}"
    )

    try:
        await bot.ban_chat_member(chat_id, target_id)
        await bot.unban_chat_member(chat_id, target_id)
    except Exception as e:
        await message.reply(f"❌ Не удалось кикнуть: {e}")
        await log_system("ERROR", f"kick failed chat={chat_id} target={target_id} err={e}")
        return

    details = f"chat={chat_id} reason={reason or '—'}"
    await log_admin_action(admin_id, admin_name, "KICK", target_id, target_name, details)

    await register_action(bot, chat_id, admin_id, admin_name, "KICK")

    reason_str = f"\n📝 Причина: {reason}" if reason else ""
    await message.reply(
        f"👢 <b>{target_name}</b> кикнут.{reason_str}",
        parse_mode="HTML"
    )


# ── /ban ─────────────────────────────────────────────────────────

@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot):

    if not await _check_level(message, 2):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /ban <reply | @username | id> [причина]"
        )
        return

    has_arg   = not bool(message.reply_to_message)
    _, reason = _parse_tail(message, has_arg)

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)
    chat_id    = message.chat.id

    await log_command(
        admin_id, admin_name,
        "ban",
        f"target={target_name}({target_id}) reason={reason or '—'}"
    )

    try:
        await bot.ban_chat_member(chat_id, target_id)
    except Exception as e:
        await message.reply(f"❌ Не удалось забанить: {e}")
        await log_system("ERROR", f"ban failed chat={chat_id} target={target_id} err={e}")
        return

    ban_id  = await _db_ban(chat_id, target_id, admin_id, reason)
    details = f"chat={chat_id} ban_id={ban_id} reason={reason or '—'}"
    await log_admin_action(admin_id, admin_name, "BAN", target_id, target_name, details)

    await register_action(bot, chat_id, admin_id, admin_name, "BAN")

    reason_str = f"\n📝 Причина: {reason}" if reason else ""
    await message.reply(
        f"🔨 <b>{target_name}</b> заблокирован.{reason_str}",
        parse_mode="HTML"
    )


# ── /unban ───────────────────────────────────────────────────────

@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot):

    if not await _check_level(message, 2):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /unban <reply | @username | id> [причина]"
        )
        return

    has_arg   = not bool(message.reply_to_message)
    _, reason = _parse_tail(message, has_arg)

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)
    chat_id    = message.chat.id

    await log_command(
        admin_id, admin_name,
        "unban",
        f"target={target_name}({target_id}) reason={reason or '—'}"
    )

    try:
        await bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
    except Exception as e:
        await message.reply(f"❌ Не удалось разбанить: {e}")
        await log_system("ERROR", f"unban failed chat={chat_id} target={target_id} err={e}")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM bans WHERE chat_id = ? AND user_id = ?
        """, (chat_id, target_id))
        await db.commit()

    details = f"chat={chat_id} reason={reason or '—'}"
    await log_admin_action(admin_id, admin_name, "UNBAN", target_id, target_name, details)

    await register_action(bot, chat_id, admin_id, admin_name, "UNBAN")

    await message.reply(
        f"✅ <b>{target_name}</b> разблокирован.",
        parse_mode="HTML"
    )


# ── /mute ────────────────────────────────────────────────────────

@router.message(Command("mute"))
async def cmd_mute(message: Message, bot: Bot):

    if not await _check_level(message, 2):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /mute <reply | @username | id> [30m|2h|7d] [причина]"
        )
        return

    has_arg          = not bool(message.reply_to_message)
    duration, reason = _parse_tail(message, has_arg)

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)
    chat_id    = message.chat.id

    until_date = None
    until_ts   = None
    if duration:
        until_date = datetime.now(tz=timezone.utc) + duration
        until_ts   = int(until_date.timestamp())

    await log_command(
        admin_id, admin_name,
        "mute",
        f"target={target_name}({target_id}) duration={duration} reason={reason or '—'}"
    )

    try:
        await bot.restrict_chat_member(
            chat_id,
            target_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            ),
            until_date=until_ts,
        )
    except Exception as e:
        await message.reply(f"❌ Не удалось замутить: {e}")
        await log_system("ERROR", f"mute failed chat={chat_id} target={target_id} err={e}")
        return

    mute_id = await _db_mute(chat_id, target_id, admin_id, reason, until_date)
    details = (
        f"chat={chat_id} mute_id={mute_id} "
        f"until={until_date} reason={reason or '—'}"
    )
    await log_admin_action(admin_id, admin_name, "MUTE", target_id, target_name, details)

    await register_action(bot, chat_id, admin_id, admin_name, "MUTE")

    dur_str    = f" на {duration}" if duration else " навсегда"
    reason_str = f"\n📝 Причина: {reason}" if reason else ""
    await message.reply(
        f"🔇 <b>{target_name}</b> замолчан{dur_str}.{reason_str}",
        parse_mode="HTML"
    )


# ── /unmute ──────────────────────────────────────────────────────

@router.message(Command("unmute"))
async def cmd_unmute(message: Message, bot: Bot):

    if not await _check_level(message, 2):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /unmute <reply | @username | id>"
        )
        return

    has_arg   = not bool(message.reply_to_message)
    _, reason = _parse_tail(message, has_arg)

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)
    chat_id    = message.chat.id

    await log_command(
        admin_id, admin_name,
        "unmute",
        f"target={target_name}({target_id})"
    )

    try:
        await bot.restrict_chat_member(
            chat_id,
            target_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
    except Exception as e:
        await message.reply(f"❌ Не удалось снять мут: {e}")
        await log_system("ERROR", f"unmute failed chat={chat_id} target={target_id} err={e}")
        return

    details = f"chat={chat_id} reason={reason or '—'}"
    await log_admin_action(admin_id, admin_name, "UNMUTE", target_id, target_name, details)

    await register_action(bot, chat_id, admin_id, admin_name, "UNMUTE")

    await message.reply(
        f"🔊 Мут снят с <b>{target_name}</b>.",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════════════
#  ЛОКАЛЬНЫЕ КОМАНДЫ — ПО ВЕТКЕ (lvl 3)
# ═══════════════════════════════════════════════════════════════

# ── /lkick ───────────────────────────────────────────────────────

@router.message(Command("lkick"))
async def cmd_lkick(message: Message, bot: Bot):

    if not await _check_level(message, 2):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /lkick <reply | @username | id> [причина]"
        )
        return

    chat_ids, branch_name = await _get_branch_chat_ids(message.chat.id)
    if chat_ids is None:
        await message.reply(
            "⚠️ Этот чат не привязан к ветке. Используйте /branch_add <название>."
        )
        return

    has_arg   = not bool(message.reply_to_message)
    _, reason = _parse_tail(message, has_arg)

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)

    await log_command(
        admin_id, admin_name,
        "lkick",
        f"branch={branch_name} target={target_name}({target_id}) reason={reason or '—'}"
    )

    ok, fail = [], []

    for cid in chat_ids:
        try:
            await bot.ban_chat_member(cid, target_id)
            await bot.unban_chat_member(cid, target_id)
            ok.append(cid)
        except Exception as e:
            fail.append(cid)
            await log_system("ERROR", f"lkick failed chat={cid} target={target_id} err={e}")

    details = (
        f"branch={branch_name} ok={len(ok)} fail={len(fail)} "
        f"reason={reason or '—'}"
    )
    await log_admin_action(admin_id, admin_name, "LKICK", target_id, target_name, details)

    await register_action(bot, message.chat.id, admin_id, admin_name, "LKICK")

    reason_str = f"\n📝 Причина: {reason}" if reason else ""
    await message.reply(
        f"👢 <b>{target_name}</b> кикнут из <b>{len(ok)}</b> чатов ветки "
        f"<b>{branch_name}</b>"
        + (f" (не удалось: {len(fail)})" if fail else "")
        + f".{reason_str}",
        parse_mode="HTML"
    )


# ── /lban ────────────────────────────────────────────────────────

@router.message(Command("lban"))
async def cmd_lban(message: Message, bot: Bot):

    if not await _check_level(message, 3):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /lban <reply | @username | id> [причина]"
        )
        return

    chat_ids, branch_name = await _get_branch_chat_ids(message.chat.id)
    if chat_ids is None:
        await message.reply(
            "⚠️ Этот чат не привязан к ветке. Используйте /branch_add <название>."
        )
        return

    has_arg   = not bool(message.reply_to_message)
    _, reason = _parse_tail(message, has_arg)

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)

    await log_command(
        admin_id, admin_name,
        "lban",
        f"branch={branch_name} target={target_name}({target_id}) reason={reason or '—'}"
    )

    ok, fail = [], []

    for cid in chat_ids:
        try:
            await bot.ban_chat_member(cid, target_id)
            ban_id = await _db_ban(cid, target_id, admin_id, reason)
            ok.append(cid)
            await log_admin_action(
                admin_id, admin_name, "LBAN", target_id, target_name,
                f"branch={branch_name} chat={cid} ban_id={ban_id} reason={reason or '—'}"
            )
        except Exception as e:
            fail.append(cid)
            await log_system("ERROR", f"lban failed chat={cid} target={target_id} err={e}")

    await register_action(bot, message.chat.id, admin_id, admin_name, "LBAN")

    reason_str = f"\n📝 Причина: {reason}" if reason else ""
    await message.reply(
        f"🔨 <b>{target_name}</b> забанен в <b>{len(ok)}</b> чатах ветки "
        f"<b>{branch_name}</b>"
        + (f" (не удалось: {len(fail)})" if fail else "")
        + f".{reason_str}",
        parse_mode="HTML"
    )


# ── /lunban ──────────────────────────────────────────────────────

@router.message(Command("lunban"))
async def cmd_lunban(message: Message, bot: Bot):

    if not await _check_level(message, 3):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /lunban <reply | @username | id>"
        )
        return

    chat_ids, branch_name = await _get_branch_chat_ids(message.chat.id)
    if chat_ids is None:
        await message.reply(
            "⚠️ Этот чат не привязан к ветке. Используйте /branch_add <название>."
        )
        return

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)

    await log_command(
        admin_id, admin_name,
        "lunban",
        f"branch={branch_name} target={target_name}({target_id})"
    )

    ok, fail = [], []

    for cid in chat_ids:
        try:
            await bot.unban_chat_member(cid, target_id, only_if_banned=True)
            ok.append(cid)
            await log_admin_action(
                admin_id, admin_name, "LUNBAN", target_id, target_name,
                f"branch={branch_name} chat={cid}"
            )
        except Exception as e:
            fail.append(cid)
            await log_system("ERROR", f"lunban failed chat={cid} target={target_id} err={e}")

    await register_action(bot, message.chat.id, admin_id, admin_name, "LUNBAN")

    await message.reply(
        f"✅ <b>{target_name}</b> разблокирован в <b>{len(ok)}</b> чатах ветки "
        f"<b>{branch_name}</b>"
        + (f" (не удалось: {len(fail)})" if fail else "")
        + ".",
        parse_mode="HTML"
    )


# ── /lmute ───────────────────────────────────────────────────────

@router.message(Command("lmute"))
async def cmd_lmute(message: Message, bot: Bot):

    if not await _check_level(message, 2):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /lmute <reply | @username | id> [30m|2h|7d] [причина]"
        )
        return

    chat_ids, branch_name = await _get_branch_chat_ids(message.chat.id)
    if chat_ids is None:
        await message.reply(
            "⚠️ Этот чат не привязан к ветке. Используйте /branch_add <название>."
        )
        return

    has_arg          = not bool(message.reply_to_message)
    duration, reason = _parse_tail(message, has_arg)

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)

    until_date = None
    until_ts   = None
    if duration:
        until_date = datetime.now(tz=timezone.utc) + duration
        until_ts   = int(until_date.timestamp())

    await log_command(
        admin_id, admin_name,
        "lmute",
        f"branch={branch_name} target={target_name}({target_id}) "
        f"duration={duration} reason={reason or '—'}"
    )

    ok, fail = [], []

    for cid in chat_ids:
        try:
            await bot.restrict_chat_member(
                cid,
                target_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                ),
                until_date=until_ts,
            )
            mute_id = await _db_mute(cid, target_id, admin_id, reason, until_date)
            ok.append(cid)
            await log_admin_action(
                admin_id, admin_name, "LMUTE", target_id, target_name,
                f"branch={branch_name} chat={cid} mute_id={mute_id} "
                f"until={until_date} reason={reason or '—'}"
            )
        except Exception as e:
            fail.append(cid)
            await log_system("ERROR", f"lmute failed chat={cid} target={target_id} err={e}")

    await register_action(bot, message.chat.id, admin_id, admin_name, "LMUTE")

    dur_str    = f" на {duration}" if duration else " навсегда"
    reason_str = f"\n📝 Причина: {reason}" if reason else ""
    await message.reply(
        f"🔇 <b>{target_name}</b> замолчан{dur_str} в <b>{len(ok)}</b> чатах ветки "
        f"<b>{branch_name}</b>"
        + (f" (не удалось: {len(fail)})" if fail else "")
        + f".{reason_str}",
        parse_mode="HTML"
    )


# ── /lunmute ─────────────────────────────────────────────────────

@router.message(Command("lunmute"))
async def cmd_lunmute(message: Message, bot: Bot):

    if not await _check_level(message, 2):
        return

    target_id, target_name = await _resolve_target(message)
    if not target_id:
        await message.reply(
            "Использование: /lunmute <reply | @username | id>"
        )
        return

    chat_ids, branch_name = await _get_branch_chat_ids(message.chat.id)
    if chat_ids is None:
        await message.reply(
            "⚠️ Этот чат не привязан к ветке. Используйте /branch_add <название>."
        )
        return

    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)

    await log_command(
        admin_id, admin_name,
        "lunmute",
        f"branch={branch_name} target={target_name}({target_id})"
    )

    ok, fail = [], []

    for cid in chat_ids:
        try:
            await bot.restrict_chat_member(
                cid,
                target_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
            ok.append(cid)
            await log_admin_action(
                admin_id, admin_name, "LUNMUTE", target_id, target_name,
                f"branch={branch_name} chat={cid}"
            )
        except Exception as e:
            fail.append(cid)
            await log_system("ERROR", f"lunmute failed chat={cid} target={target_id} err={e}")

    await register_action(bot, message.chat.id, admin_id, admin_name, "LUNMUTE")

    await message.reply(
        f"🔊 Мут снят с <b>{target_name}</b> в <b>{len(ok)}</b> чатах ветки "
        f"<b>{branch_name}</b>"
        + (f" (не удалось: {len(fail)})" if fail else "")
        + ".",
        parse_mode="HTML"
    )


@router.message(Command("comment"))
async def cmd_comment(message: Message):
 
    if not await _check_level(message, 2):
        return
 
    args = message.text.split(None, 3)
 
    # /comment + @user текст   → args = ['/comment', '+', '@user', 'текст']
    # /comment - 42            → args = ['/comment', '-', '42']
 
    if len(args) < 3:
        return await message.reply(
            "Использование:\n"
            "/comment + @username|id текст\n"
            "/comment - ID_пометки"
        )
 
    flag = args[1]
 
    if flag not in ("+", "-"):
        return await message.reply("❌ Укажите + (добавить) или - (удалить).")
 
    admin_id   = message.from_user.id
    admin_name = message.from_user.username or str(admin_id)
 
    # ── Добавить пометку ──────────────────────────────────────
    if flag == "+":
        if len(args) < 4:
            return await message.reply(
                "❌ Укажите текст пометки: /comment + @username текст"
            )
 
        target_token = args[2]
        text         = args[3].strip()
 
        if not text:
            return await message.reply("❌ Текст пометки не может быть пустым.")
 
        result = await resolve_user(message, target_token)
        if not result.success:
            return await message.reply(f"❌ {result.error}")
 
        comment_id = await _db_add_comment(result.user_id, admin_id, text)
 
        await log_admin_action(
            admin_id, admin_name, "COMMENT_ADD",
            result.user_id,
            result.username or result.first_name or str(result.user_id),
            f"#{comment_id}: {text}"
        )
 
        target_handle = f"@{result.username}" if result.username else (result.first_name or str(result.user_id))
 
        await message.reply(
            f"📝 Пометка <b>#{comment_id}</b> добавлена для {target_handle}.\n"
            f"💬 {text}",
            parse_mode="HTML"
        )
 
    # ── Удалить пометку ───────────────────────────────────────
    elif flag == "-":
        raw_id = args[2]
        if not raw_id.isdigit():
            return await message.reply("❌ Укажите числовой ID пометки.")
 
        comment_id = int(raw_id)
        deleted    = await _db_delete_comment(comment_id, admin_id)
 
        if not deleted:
            return await message.reply(f"❌ Пометка #{comment_id} не найдена.")
 
        await log_admin_action(
            admin_id, admin_name, "COMMENT_DEL",
            0, "—", f"#{comment_id}"
        )
 
        await message.reply(f"🗑 Пометка #{comment_id} удалена.")