import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from utils.permissions import check_adm_lvl

from utils.logger import log_admin_action

from database import (
    create_branch,
    delete_branch,
    get_branch_by_name,
    get_all_branches,
    add_chat_to_branch,
    remove_chat_from_branch,
    get_branch_chats,
    get_chat,
)

router = Router()


# ══════════════════════════════════════════════
#  ВЕТКИ
# ══════════════════════════════════════════════

@router.message(Command("bcreate"))
async def bcreate_cmd(message: Message):
    """Создать ветку. /bcreate <название>"""

    if not await check_adm_lvl(message, 3):
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        return await message.answer(
            "Использование:\n"
            "/bcreate &lt;название&gt;"
        )

    name = args[1].strip()
    safe_name = html.escape(name)

    if len(name) > 64:
        return await message.answer(
            "Название ветки не должно превышать 64 символа."
        )

    existing = await get_branch_by_name(name)

    if existing:
        return await message.answer(
            f"Ветка <b>{safe_name}</b> уже существует.",
            parse_mode="HTML"
        )

    branch_id = await create_branch(name)

    await log_admin_action(
        message.from_user.id,
        message.from_user.username or "",
        "BRANCH_CREATE",
        0,
        name,
        f"branch_id={branch_id}"
    )

    await message.answer(
        f"✅ Ветка <b>{safe_name}</b> создана.\n"
        f"ID: <code>{branch_id}</code>",
        parse_mode="HTML"
    )


@router.message(Command("bdelete"))
async def bdelete_cmd(message: Message):
    """Удалить ветку. /bdelete <название>"""

    if not await check_adm_lvl(message, 3):
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        return await message.answer(
            "Использование:\n"
            "/bdelete &lt;название&gt;"
        )

    name = args[1].strip()
    safe_name = html.escape(name)
    branch = await get_branch_by_name(name)

    if not branch:
        return await message.answer(
            f"Ветка <b>{safe_name}</b> не найдена.",
            parse_mode="HTML"
        )

    # branch: id, name
    branch_id = branch[0]
    chats = await get_branch_chats(branch_id)

    await delete_branch(branch_id)

    await log_admin_action(
        message.from_user.id,
        message.from_user.username or "",
        "BRANCH_DELETE",
        0,
        name,
        f"branch_id={branch_id}, чатов было: {len(chats)}"
    )

    note = (
        f"\n<i>Все {len(chats)} групп откреплены.</i>"
        if chats else ""
    )

    await message.answer(
        f"🗑 Ветка <b>{safe_name}</b> удалена.{note}",
        parse_mode="HTML"
    )


@router.message(Command("branches"))
async def branches_cmd(message: Message):
    """Список всех веток с количеством групп."""

    if not await check_adm_lvl(message, 3):
        return

    branches = await get_all_branches()

    if not branches:
        return await message.answer("Веток пока нет.")

    text = "🌿 <b>Ветки</b>\n\n"

    for branch in branches:
        # branch: id, name
        chats = await get_branch_chats(branch[0])
        text += (
            f"• <b>{html.escape(branch[1])}</b> "
            f"<code>[id:{branch[0]}]</code> — "
            f"{len(chats)} гр.\n"
        )

    await message.answer(text, parse_mode="HTML")


# ══════════════════════════════════════════════
#  ГРУППЫ В ВЕТКАХ
# ══════════════════════════════════════════════

@router.message(Command("badd"))
async def badd_cmd(message: Message):
    """
    Добавить группу в ветку.
    /badd <название_ветки> <chat_id>
    Если команда вызвана из группы и chat_id не указан — берёт текущий чат.
    """

    if not await check_adm_lvl(message, 3):
        return

    args = message.text.split()

    if len(args) < 2:
        return await message.answer(
            "Использование:\n"
            "/badd &lt;ветка&gt; [chat_id]\n\n"
            "<i>Если chat_id не указан — добавляется текущая группа.</i>",
            parse_mode="HTML"
        )

    branch_name = args[1].strip()
    safe_branch = html.escape(branch_name)

    # Определяем chat_id
    if len(args) >= 3:
        try:
            target_chat_id = int(args[2])
        except ValueError:
            return await message.answer(
                "chat_id должен быть числом."
            )
    else:
        if message.chat.type == "private":
            return await message.answer(
                "Укажи chat_id или вызови команду из нужной группы."
            )
        target_chat_id = message.chat.id

    branch = await get_branch_by_name(branch_name)

    if not branch:
        return await message.answer(
            f"Ветка <b>{safe_branch}</b> не найдена.\n"
            f"Создай её через /bcreate {safe_branch}",
            parse_mode="HTML"
        )

    branch_id = branch[0]

    # Проверяем что бот имеет доступ к чату
    try:
        chat_info = await message.bot.get_chat(target_chat_id)
        chat_title = html.escape(chat_info.title or str(target_chat_id))
    except Exception:
        return await message.answer(
            f"Не удалось получить информацию о чате <code>{target_chat_id}</code>.\n"
            f"Убедись, что бот добавлен в эту группу.",
            parse_mode="HTML"
        )

    # Проверяем не добавлен ли чат уже в эту ветку
    existing_chats = await get_branch_chats(branch_id)
    already = any(c[2] == target_chat_id for c in existing_chats)

    if already:
        return await message.answer(
            f"Группа <b>{chat_title}</b> уже в ветке <b>{safe_branch}</b>.",
            parse_mode="HTML"
        )

    await add_chat_to_branch(branch_id, target_chat_id)

    await log_admin_action(
        message.from_user.id,
        message.from_user.username or "",
        "BRANCH_ADD_CHAT",
        0,
        branch_name,
        f"chat_id={target_chat_id} ({chat_title})"
    )

    await message.answer(
        f"✅ Группа <b>{chat_title}</b> добавлена в ветку <b>{safe_branch}</b>.",
        parse_mode="HTML"
    )


@router.message(Command("bremove"))
async def bremove_cmd(message: Message):
    """
    Удалить группу из ветки.
    /bremove <название_ветки> [chat_id]
    """

    if not await check_adm_lvl(message, 3):
        return

    args = message.text.split()

    if len(args) < 2:
        return await message.answer(
            "Использование:\n"
            "/bremove &lt;ветка&gt; [chat_id]\n\n"
            "<i>Если chat_id не указан — убирается текущая группа.</i>",
            parse_mode="HTML"
        )

    branch_name = args[1].strip()
    safe_branch = html.escape(branch_name)

    if len(args) >= 3:
        try:
            target_chat_id = int(args[2])
        except ValueError:
            return await message.answer(
                "chat_id должен быть числом."
            )
    else:
        if message.chat.type == "private":
            return await message.answer(
                "Укажи chat_id или вызови команду из нужной группы."
            )
        target_chat_id = message.chat.id

    branch = await get_branch_by_name(branch_name)

    if not branch:
        return await message.answer(
            f"Ветка <b>{safe_branch}</b> не найдена.",
            parse_mode="HTML"
        )

    branch_id = branch[0]
    existing_chats = await get_branch_chats(branch_id)
    match = next((c for c in existing_chats if c[2] == target_chat_id), None)

    if not match:
        return await message.answer(
            f"Группа <code>{target_chat_id}</code> не найдена в ветке "
            f"<b>{safe_branch}</b>.",
            parse_mode="HTML"
        )

    await remove_chat_from_branch(branch_id, target_chat_id)

    # Пробуем получить название чата для красивого ответа
    try:
        chat_info = await message.bot.get_chat(target_chat_id)
        chat_title = html.escape(chat_info.title or str(target_chat_id))
    except Exception:
        chat_title = str(target_chat_id)

    await log_admin_action(
        message.from_user.id,
        message.from_user.username or "",
        "BRANCH_REMOVE_CHAT",
        0,
        branch_name,
        f"chat_id={target_chat_id} ({chat_title})"
    )

    await message.answer(
        f"🗑 Группа <b>{chat_title}</b> удалена из ветки <b>{safe_branch}</b>.",
        parse_mode="HTML"
    )


@router.message(Command("binfo"))
async def binfo_cmd(message: Message):
    """Список групп в ветке. /binfo <название>"""

    if not await check_adm_lvl(message, 3):
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        return await message.answer(
            "Использование:\n"
            "/binfo <название>"
        )

    name = args[1].strip()
    branch = await get_branch_by_name(name)

    if not branch:
        return await message.answer(
            f"Ветка <b>{name}</b> не найдена.",
            parse_mode="HTML"
        )

    branch_id = branch[0]
    chats = await get_branch_chats(branch_id)

    if not chats:
        return await message.answer(
            f"Ветка <b>{name}</b> пуста — групп нет.",
            parse_mode="HTML"
        )

    text = f"🌿 <b>Ветка: {name}</b>\nГрупп: {len(chats)}\n\n"

    for i, chat_row in enumerate(chats, 1):
        # branch_chats: id, branch_id, chat_id
        chat_id = chat_row[2]

        # Достаём название из таблицы chats если есть
        chat_rec = await get_chat(chat_id)
        if chat_rec and chat_rec[1]:
            title = chat_rec[1]
        else:
            try:
                info = await message.bot.get_chat(chat_id)
                title = info.title or str(chat_id)
            except Exception:
                title = str(chat_id)

        text += f"{i}. <b>{title}</b> — <code>{chat_id}</code>\n"

    await message.answer(text, parse_mode="HTML")