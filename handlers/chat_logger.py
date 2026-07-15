# handlers/chat_logger.py

import aiosqlite
from datetime import datetime

from aiogram import Router
from aiogram.types import Message

from utils.logger import log_chat
from handlers.get import save_user_first_seen, record_join
from handlers.mt import upsert_member

DB_PATH = "data/bot.db"

router = Router()


def get_username(user) -> str:
    if user is None:
        return "unknown"
    return f"@{user.username}" if user.username else user.full_name


def get_full_name(user) -> str:
    return " ".join(x for x in [user.first_name, user.last_name] if x).strip() or str(user.id)


def get_message_text(message: Message) -> str:

    if message.text:
        return message.text

    caption = message.caption or ""

    if message.photo:       return f"[photo] {caption}".strip()
    if message.video:       return f"[video] {caption}".strip()
    if message.video_note:  return "[video_note]"
    if message.voice:       return "[voice]"
    if message.audio:       return f"[audio] {caption}".strip()
    if message.document:
        return f"[document] {message.document.file_name or ''} {caption}".strip()
    if message.sticker:     return f"[sticker] {message.sticker.emoji or ''}".strip()
    if message.animation:   return f"[animation] {caption}".strip()
    if message.contact:
        c = message.contact
        return f"[contact] {c.first_name} {c.phone_number}".strip()
    if message.location:
        loc = message.location
        return f"[location] lat={loc.latitude} lon={loc.longitude}"
    if message.poll:        return f"[poll] {message.poll.question}"
    if message.dice:        return f"[dice] {message.dice.emoji}={message.dice.value}"

    if message.new_chat_members:
        names = ", ".join(get_username(u) for u in message.new_chat_members)
        return f"[joined] {names}"
    if message.left_chat_member:
        return f"[left] {get_username(message.left_chat_member)}"
    if message.pinned_message:
        return f"[pinned] {(message.pinned_message.text or '')[:60]}".strip()
    if message.new_chat_title:      return f"[new_title] {message.new_chat_title}"
    if message.new_chat_photo:      return "[new_chat_photo]"
    if message.delete_chat_photo:   return "[deleted_chat_photo]"
    if message.group_chat_created:  return "[group_created]"
    if message.migrate_to_chat_id:  return f"[migrated_to] {message.migrate_to_chat_id}"
    if message.migrate_from_chat_id: return f"[migrated_from] {message.migrate_from_chat_id}"

    return "[unknown]"


@router.message()
async def log_any_message(message: Message):

    user = message.from_user
    if not user:
        return

    chat_id = message.chat.id
    text    = get_message_text(message)

    # Сохраняем пользователя с датой первого появления
    await save_user_first_seen(
        user.id, user.username,
        user.first_name, user.last_name
    )

    # Обновляем список участников для /mt
    await upsert_member(chat_id, user.id, get_full_name(user), user.username)

    # Вступление участников
    if message.new_chat_members:
        for member in message.new_chat_members:
            await save_user_first_seen(
                member.id, member.username,
                member.first_name, member.last_name
            )
            await record_join(chat_id, member.id)
            await upsert_member(
                chat_id, member.id,
                get_full_name(member), member.username
            )

    # Выход участника — убираем из списка /mt
    if message.left_chat_member:
        member = message.left_chat_member
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                DELETE FROM chat_members_list
                WHERE chat_id = ? AND user_id = ?
            """, (chat_id, member.id))
            await db.commit()

    await log_chat(
        chat_id      = chat_id,
        user_id      = user.id,
        user_name    = get_username(user),
        message_text = text
    )


@router.edited_message()
async def log_edited_message(message: Message):

    user = message.from_user
    if not user:
        return

    await log_chat(
        chat_id      = message.chat.id,
        user_id      = user.id,
        user_name    = get_username(user),
        message_text = f"[edited] {get_message_text(message)}"
    )