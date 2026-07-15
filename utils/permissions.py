from aiogram.types import Message

from database import get_admin_level


# ==========================================
# MESSAGES
# ==========================================

NO_ACCESS = "❌ Недостаточно прав для выполнения команды."

NOT_ADMIN = "❌ Вы не являетесь администратором."

ONLY_EX_ADMIN = (
    "❌ Команда доступна только бывшим администраторам."
)

SELF_ACTION = (
    "❌ Нельзя применять команду к самому себе."
)

HIGHER_ADMIN = (
    "❌ Нельзя управлять администратором "
    "равного или более высокого уровня."
)


# ==========================================
# BASIC LEVELS
# ==========================================

async def get_level(user_id: int) -> int:
    level = await get_admin_level(user_id)
    return level or 0


async def is_admin(user_id: int) -> bool:
    return (await get_level(user_id)) > 0


async def is_lvl1(user_id: int) -> bool:
    return (await get_level(user_id)) >= 1


async def is_lvl2(user_id: int) -> bool:
    return (await get_level(user_id)) >= 2


async def is_lvl3(user_id: int) -> bool:
    return (await get_level(user_id)) >= 3


# ==========================================
# UNIVERSAL CHECK
# ==========================================

async def check_adm_lvl(
    message: Message,
    required_level: int,
    target_id: int = None
) -> bool:

    issuer_id = message.from_user.id

    issuer_level = await get_level(
        issuer_id
    )

    if issuer_level < required_level:

        await message.answer(
            NO_ACCESS
        )

        return False

    if target_id is None:
        return True

    if issuer_id == target_id:

        await message.answer(
            SELF_ACTION
        )

        return False

    target_level = await get_level(
        target_id
    )

    if (
        target_level > 0
        and target_level >= issuer_level
    ):

        await message.answer(
            HIGHER_ADMIN
        )

        return False

    return True


# ==========================================
# OLD CHECKS
# ==========================================

async def check_admin(
    message: Message
) -> bool:

    return await check_adm_lvl(
        message,
        1
    )


async def check_lvl1(
    message: Message
) -> bool:

    return await check_adm_lvl(
        message,
        1
    )


async def check_lvl2(
    message: Message
) -> bool:

    return await check_adm_lvl(
        message,
        2
    )


async def check_lvl3(
    message: Message
) -> bool:

    return await check_adm_lvl(
        message,
        3
    )


# ==========================================
# LEVEL COMPARISON
# ==========================================

async def can_manage(
    issuer_id: int,
    target_id: int
) -> bool:

    issuer_level = await get_level(
        issuer_id
    )

    target_level = await get_level(
        target_id
    )

    return issuer_level > target_level


# ==========================================
# LEVEL NAMES
# ==========================================

def level_name(
    level: int
) -> str:

    levels = {
        0: "Пользователь",
        1: "Администратор 1 уровня",
        2: "Администратор 2 уровня",
        3: "Администратор 3 уровня"
    }

    return levels.get(
        level,
        f"Неизвестный уровень ({level})"
    )


# ==========================================
# COMMAND ACCESS
# ==========================================

COMMAND_LEVELS = {

    # lvl1

    "point": 1,
    "mypoints": 1,
    "mywarns": 1,

    # lvl2

    "warn": 2,
    "kick": 2,
    "ban": 2,
    "mute": 2,

    "lkick": 2,
    "lban": 2,
    "lmute": 2,

    "radm": 2,

    # lvl3

    "gban": 3,
    "amnistiya": 3,

    "add_admin": 3,
    "del_admin": 3,

    "full_logs": 3,
    "alog": 3,
    "tlog": 3,
    "export_logs": 3
}


async def has_command_access(
    user_id: int,
    command: str
) -> bool:

    command = command.lower()

    required_level = COMMAND_LEVELS.get(
        command
    )

    if required_level is None:
        return True

    return (
        await get_level(user_id)
    ) >= required_level


# ==========================================
# PROTECTED ADMINS
# ==========================================

async def is_protected_admin(
    target_id: int
) -> bool:

    level = await get_level(
        target_id
    )

    return level >= 3