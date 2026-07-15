from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database import (
    add_admin,
    remove_admin,
    get_admin,
    get_all_admins,
    get_all_ex_admins
)

from utils.permissions import (
    check_lvl3,
    level_name
)

from utils.resolver import (
    resolve_user,
    get_display_name
)

from utils.logger import (
    log_admin_action,
    log_command
)

router = Router()

@router.message(Command("add_admin"))
async def add_admin_cmd(
    message: Message
):

    if not await check_lvl3(message):
        return

    args = message.text.split()

    if len(args) < 3:

        return await message.answer(
            "Использование:\n"
            "/add_admin user level"
        )

    target = args[1]

    try:
        level = int(args[2])

    except:

        return await message.answer(
            "Укажите уровень 1-3"
        )

    if level < 1 or level > 3:

        return await message.answer(
            "Уровень должен быть от 1 до 3."
        )

    user = await resolve_user(
        message,
        target
    )

    if not user.success:
        return await message.answer(
            user.error
        )

    await add_admin(
        user.user_id,
        level,
        message.from_user.id
    )

    await log_command(
        message.from_user.id,
        message.from_user.username or "",
        "/add_admin",
        message.text
    )

    await log_admin_action(
        message.from_user.id,
        message.from_user.username or "",
        "ADD_ADMIN",
        user.user_id,
        user.username or user.first_name,
        f"LEVEL={level}"
    )

    await message.answer(
        f"✅ Администратор назначен.\n"
        f"Уровень: {level}"
    )

@router.message(Command("del_admin"))
async def del_admin_cmd(
    message: Message
):

    if not await check_lvl3(message):
        return

    args = message.text.split()

    if len(args) < 2:

        return await message.answer(
            "Использование:\n"
            "/del_admin user"
        )

    target = args[1]

    user = await resolve_user(
        message,
        target
    )

    if not user.success:
        return await message.answer(
            user.error
        )

    admin = await get_admin(
        user.user_id
    )

    if not admin:

        return await message.answer(
            "Пользователь не является администратором."
        )

    await remove_admin(
        user.user_id,
        "Снят администратором"
    )

    await log_admin_action(
        message.from_user.id,
        message.from_user.username or "",
        "DEL_ADMIN",
        user.user_id,
        user.username or user.first_name
    )

    await message.answer(
        "✅ Администратор снят."
    )

@router.message(Command("admins"))
async def admins_cmd(
    message: Message
):

    admins = await get_all_admins()

    if not admins:

        return await message.answer(
            "Список администраторов пуст."
        )

    text = "👮 Администрация\n\n"

    for admin in admins:

        uid = admin[0]
        level = admin[1]

        name = await get_display_name(
            uid
        )

        text += (
            f"{name}\n"
            f"Уровень: {level}\n\n"
        )

    await message.answer(text)

@router.message(Command("ex_admins"))
async def ex_admins_cmd(
    message: Message
):

    if not await check_lvl3(message):
        return

    ex_admins = await get_all_ex_admins()

    if not ex_admins:

        return await message.answer(
            "Бывших администраторов нет."
        )

    text = "📄 Бывшие администраторы\n\n"

    for row in ex_admins:

        uid = row[0]
        level = row[1]
        reason = row[2]

        name = await get_display_name(
            uid
        )

        text += (
            f"{name}\n"
            f"Был уровень: {level}\n"
            f"Причина: {reason}\n\n"
        )

    await message.answer(text)