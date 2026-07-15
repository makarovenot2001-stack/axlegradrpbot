# utils/resolver.py

from aiogram.types import Message

from database import (
    get_user,
    get_user_by_username,
    save_user
)


class ResolveResult:
    def __init__(
        self,
        success: bool,
        user_id: int = None,
        username: str = None,
        first_name: str = None,
        error: str = None
    ):
        self.success    = success
        self.user_id    = user_id
        self.username   = username
        self.first_name = first_name
        self.error      = error


async def resolve_user(
    message: Message,
    target:  str | None = None
) -> ResolveResult:

    bot = message.bot

    # ====================================
    # REPLY
    # ====================================

    if message.reply_to_message:
        user = message.reply_to_message.from_user
        return ResolveResult(
            success    = True,
            user_id    = user.id,
            username   = user.username,
            first_name = user.first_name
        )

    # ====================================
    # NO TARGET
    # ====================================

    if not target:
        return ResolveResult(
            success = False,
            error   = "Пользователь не указан."
        )

    target = target.strip()

    # ====================================
    # ID
    # ====================================

    if target.lstrip("-").isdigit():
        user_id = int(target)
        row     = await get_user(user_id)

        if row:
            return ResolveResult(
                success    = True,
                user_id    = row[0],
                username   = row[1],
                first_name = row[2]
            )

        # Не в БД — пробуем через Telegram API
        try:
            chat = await bot.get_chat(user_id)
            await save_user(
                chat.id,
                chat.username,
                chat.first_name,
                chat.last_name
            )
            return ResolveResult(
                success    = True,
                user_id    = chat.id,
                username   = chat.username,
                first_name = chat.first_name
            )
        except Exception:
            pass

        return ResolveResult(
            success = False,
            error   = "Пользователь не найден."
        )

    # ====================================
    # USERNAME
    # ====================================

    if target.startswith("@"):
        row = await get_user_by_username(target)

        if row:
            return ResolveResult(
                success    = True,
                user_id    = row[0],
                username   = row[1],
                first_name = row[2]
            )

        # Не в БД — пробуем через Telegram API
        # Не в БД — пробуем через Telegram API
        try:
            chat = await bot.get_chat(target)
            await save_user(
                chat.id,
                chat.username,
                chat.first_name,
                chat.last_name
            )
            return ResolveResult(
                success    = True,
                user_id    = chat.id,
                username   = chat.username,
                first_name = chat.first_name
            )
        except Exception:
            pass

        return ResolveResult(
            success = False,
            error   = (
                f"Пользователь {target} не найден в базе.\n"
                f"Бот не встречал его ни в одном чате — попробуйте указать числовой ID."
            )
        )

    return ResolveResult(
        success = False,
        error   = "Неверный формат пользователя."
    )


# ====================================
# GET DISPLAY NAME
# ====================================

async def get_display_name(user_id: int) -> str:

    row = await get_user(user_id)

    if not row:
        return f"ID:{user_id}"

    username   = row[1]
    first_name = row[2]
    last_name  = row[3]

    if username:
        return f"@{username}"

    full_name = " ".join(
        x for x in [first_name, last_name] if x
    ).strip()

    if full_name:
        return full_name

    return f"ID:{user_id}"