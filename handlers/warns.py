from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message
import math

from utils.permissions import check_adm_lvl
from utils.resolver import resolve_user, get_display_name
from utils.logger import log_admin_action
from utils.antidrain import register_action
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram import F

from database import (
    add_warn,
    remove_warn,
    get_active_warns,
    get_all_warns,
    remove_admin,
    get_admin,
    get_user
)

router = Router()

MAX_WARNS = 6


def get_warn_status(warn_count: int) -> tuple[int, int]:
    return warn_count // 2, warn_count % 2


def format_warn_status(warn_count: int) -> str:
    vyg, pred = get_warn_status(warn_count)
    return f"{vyg}/3 выг  {pred}/2 пред"


def issuer_link(admin_id: int, admin_row) -> str:
    if admin_row:
        display = admin_row[2] or admin_row[1] or str(admin_id)
    else:
        display = str(admin_id)
    return f'<a href="tg://user?id={admin_id}">{display}</a>'


@router.message(Command("warn"))
async def warn_cmd(message: Message, bot: Bot):

    if not await check_adm_lvl(message, 2):
        return

    args = message.text.split()

    if len(args) < 2:
        return await message.answer(
            "Использование:\n"
            "/warn @user [количество] [причина]\n\n"
            "<i>Количество по умолчанию: 1</i>",
            parse_mode="HTML"
        )

    target = args[1]

    amount = 1
    reason_start = 2

    if len(args) >= 3:
        try:
            amount = int(args[2])
            reason_start = 3
            if amount < 1 or amount > MAX_WARNS:
                return await message.answer(
                    f"Количество должно быть от 1 до {MAX_WARNS}."
                )
        except ValueError:
            reason_start = 2

    reason = (
        "Причина не указана"
        if len(args) <= reason_start
        else " ".join(args[reason_start:])
    )

    user = await resolve_user(message, target)

    if not user.success:
        return await message.answer(user.error)

    if not await check_adm_lvl(message, 2, user.user_id):
        return

    warns_before = await get_active_warns(user.user_id)
    count_before = len(warns_before)

    await add_warn(user.user_id, message.from_user.id, amount, reason)

    warns_after  = await get_active_warns(user.user_id)
    count_after  = len(warns_after)

    vyg_before, _ = get_warn_status(count_before)
    vyg_after, _  = get_warn_status(count_after)
    new_vyg = vyg_after - vyg_before

    issuer_name = (
        message.from_user.first_name
        or message.from_user.username
        or str(message.from_user.id)
    )
    target_name = await get_display_name(user.user_id)

    text = (
        f"⚠️ <b>Предупреждение выдано</b>\n\n"
        f"👤 Пользователь: {target_name}\n"
        f"✍️ Выдал: {issuer_name}\n"
        f"📋 Причина: {reason}\n"
        f"📊 Статус: <b>{format_warn_status(count_after)}</b>"
    )

    if new_vyg > 0:
        ending = "а" if new_vyg > 1 else ""
        text += (
            f"\n\n🔴 <b>+{new_vyg} выговор{ending}!</b>\n"
            f"Выговоров всего: {vyg_after}/3"
        )

    await log_admin_action(
        message.from_user.id,
        message.from_user.username or "",
        "WARN",
        user.user_id,
        user.username or user.first_name,
        reason
    )

    # ── Анти-слив ─────────────────────────────────────────────
    await register_action(
        bot,
        message.chat.id,
        message.from_user.id,
        message.from_user.username or str(message.from_user.id),
        "WARN"
    )

    if count_after >= MAX_WARNS:

        admin = await get_admin(user.user_id)

        if admin:
            await remove_admin(
                user.user_id,
                "Достигнут лимит предупреждений (6 пред / 3 выг)"
            )
            text += "\n\n🚫 <b>Администратор снят с должности.</b>"

        try:
            await message.bot.ban_chat_member(
                chat_id=message.chat.id,
                user_id=user.user_id
            )
            text += "\n🚫 <b>Пользователь заблокирован.</b>"
        except Exception as e:
            text += f"\n⚠️ Не удалось заблокировать: {e}"

        await log_admin_action(
            message.from_user.id,
            message.from_user.username or "",
            "AUTO_BAN_BY_WARNS",
            user.user_id,
            user.username or user.first_name,
            "6 активных предупреждений (3 выговора)"
        )

    await message.answer(text, parse_mode="HTML")


@router.message(Command("unwarn"))
async def unwarn_cmd(message: Message):

    if not await check_adm_lvl(message, 2):
        return

    args = message.text.split()

    if len(args) < 2:
        return await message.answer(
            "Использование:\n"
            "/unwarn @user [количество]\n\n"
            "<i>Количество по умолчанию: 1</i>",
            parse_mode="HTML"
        )

    target = args[1]
    amount = 1

    if len(args) >= 3:
        try:
            amount = int(args[2])
            if amount < 1:
                return await message.answer("Количество должно быть больше 0.")
        except ValueError:
            return await message.answer("Количество должно быть числом.")

    user = await resolve_user(message, target)

    if not user.success:
        return await message.answer(user.error)

    if not await check_adm_lvl(message, 2, user.user_id):
        return

    warns_before = await get_active_warns(user.user_id)
    count_before = len(warns_before)

    if count_before == 0:
        return await message.answer("У пользователя нет активных предупреждений.")

    to_remove = min(amount, count_before)
    removed   = await remove_warn(user.user_id, to_remove)

    warns_after = await get_active_warns(user.user_id)
    count_after = len(warns_after)

    vyg_before, _ = get_warn_status(count_before)
    vyg_after, _  = get_warn_status(count_after)
    removed_vyg   = vyg_before - vyg_after

    target_name = await get_display_name(user.user_id)
    issuer_name = (
        message.from_user.first_name
        or message.from_user.username
        or str(message.from_user.id)
    )

    text = (
        f"✅ <b>Предупреждение снято</b>\n\n"
        f"👤 Пользователь: {target_name}\n"
        f"✍️ Снял: {issuer_name}\n"
        f"🗑 Снято предупреждений: {removed}\n"
        f"📊 Статус: <b>{format_warn_status(count_after)}</b>"
    )

    if removed_vyg > 0:
        ending = "а" if removed_vyg > 1 else ""
        text += (
            f"\n\n🟢 <b>-{removed_vyg} выговор{ending}</b>\n"
            f"Выговоров осталось: {vyg_after}/3"
        )

    if to_remove < amount:
        text += (
            f"\n\n<i>⚠️ Запрошено {amount}, но активных было только "
            f"{count_before} — снято {to_remove}.</i>"
        )

    await log_admin_action(
        message.from_user.id,
        message.from_user.username or "",
        "UNWARN",
        user.user_id,
        user.username or user.first_name,
        f"Снято предупреждений: {removed}"
    )

    await message.answer(text, parse_mode="HTML")


@router.message(Command("mywarns"))
async def mywarns_cmd(message: Message):

    show_all = "-a" in (message.text or "")

    if show_all:
        warns = await get_all_warns(message.from_user.id)
    else:
        warns = await get_active_warns(message.from_user.id)

    if not warns:
        msg = (
            "📭 История варнов пуста."
            if show_all
            else "✅ Активных предупреждений нет."
        )
        return await message.answer(msg)

    unique_admin_ids = {w[2] for w in warns}
    admin_cache = {}
    for aid in unique_admin_ids:
        admin_cache[aid] = await get_user(aid)

    if show_all:
        active_count = sum(1 for w in warns if w[5])

        text = (
            f"📜 <b>История предупреждений</b>\n"
            f"Активных: <b>{format_warn_status(active_count)}</b>\n"
            f"Всего записей: {len(warns)}\n\n"
        )

        for i, warn in enumerate(warns, 1):
            is_active = warn[5]
            icon  = "🔴" if is_active else "⚫"
            label = "активен" if is_active else "снят"
            date_str = str(warn[6])[:10] if warn[6] else "—"
            link = issuer_link(warn[2], admin_cache.get(warn[2]))

            text += (
                f"{icon} <b>#{i}</b> <i>[{label}]</i>\n"
                f"📋 Причина: {warn[4]}\n"
                f"✍️ Выдал: {link}\n"
                f"📅 Дата: {date_str}\n\n"
            )

    else:
        warn_count = len(warns)

        text = (
            f"⚠️ <b>Активные предупреждения</b>\n"
            f"Статус: <b>{format_warn_status(warn_count)}</b>\n\n"
        )

        for i, warn in enumerate(warns, 1):
            date_str = str(warn[6])[:10] if warn[6] else "—"
            link = issuer_link(warn[2], admin_cache.get(warn[2]))

            text += (
                f"🔴 <b>#{i}</b>\n"
                f"📋 Причина: {warn[4]}\n"
                f"✍️ Выдал: {link}\n"
                f"📅 Дата: {date_str}\n\n"
            )

        text += "<i>Полная история: /mywarns -a</i>"

    await message.answer(text, parse_mode="HTML")

PAGE_SIZE = 5


def warns_keyboard(
    user_id: int,
    page: int,
    total_pages: int,
    show_all: bool
):

    buttons = []

    mode = "all" if show_all else "active"

    if page > 1:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"warns:{user_id}:{page-1}:{mode}"
            )
        )

    buttons.append(
        InlineKeyboardButton(
            text=f"{page}/{total_pages}",
            callback_data="ignore"
        )
    )

    if page < total_pages:
        buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"warns:{user_id}:{page+1}:{mode}"
            )
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[buttons]
    )


async def build_warns_page(
    user_id: int,
    page: int,
    show_all: bool
):

    warns = (
        await get_all_warns(user_id)
        if show_all
        else await get_active_warns(user_id)
    )

    if not warns:
        return "Записей нет.", None

    total_pages = max(
        1,
        math.ceil(len(warns) / PAGE_SIZE)
    )

    page = max(
        1,
        min(page, total_pages)
    )

    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE

    warns_page = warns[start:end]

    target_name = await get_display_name(
        user_id
    )

    title = (
        "📜 История предупреждений"
        if show_all
        else "⚠️ Активные предупреждения"
    )

    text = (
        f"{title}\n\n"
        f"👤 {target_name}\n"
        f"📄 Страница {page}/{total_pages}\n\n"
    )

    for idx, warn in enumerate(
        warns_page,
        start + 1
    ):

        admin = await get_user(
            warn[2]
        )

        admin_name = (
            admin[2]
            if admin
            else str(warn[2])
        )

        text += (
            f"#{idx}\n"
            f"📋 {warn[4]}\n"
            f"👮 {admin_name}\n"
            f"📅 {str(warn[6])[:10]}\n\n"
        )

    keyboard = warns_keyboard(
        user_id,
        page,
        total_pages,
        show_all
    )

    return text, keyboard


@router.message(Command("warns"))
async def warns_view_cmd(message: Message):

    args = message.text.split()

    if len(args) < 2:
        return await message.answer(
            "/warns @user [-a]"
        )

    target = args[1]

    show_all = "-a" in args

    user = await resolve_user(
        message,
        target
    )

    if not user.success:
        return await message.answer(
            user.error
        )

    text, keyboard = await build_warns_page(
        user.user_id,
        1,
        show_all
    )

    await message.answer(
        text,
        reply_markup=keyboard
    )


@router.callback_query(
    F.data.startswith("warns:")
)
async def warns_page_callback(
    callback: CallbackQuery
):

    _, user_id, page, mode = (
        callback.data.split(":")
    )

    text, keyboard = await build_warns_page(
        int(user_id),
        int(page),
        mode == "all"
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()