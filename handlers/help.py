# handlers/help.py

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from utils.permissions import get_level

router = Router()

# ══════════════════════════════════════════════
#  СТРУКТУРА КОМАНД
#  (min_level: 0 = все, 1/2/3 = только админ)
# ══════════════════════════════════════════════

SECTIONS = [
    {
        "id":    "user",
        "icon":  "👤",
        "label": "Для пользователей",
        "min_level": 0,
        "commands": [
            ("/start",      "Главное меню / открыть обращение в поддержку",  0),
            ("/mywarns",    "Посмотреть свои активные предупреждения",        0),
            ("/mywarns -a", "Полная история предупреждений",                  0),
            ("/check_gban", "Проверить статус глобальной блокировки (в ЛС)",  0),
            ("/radm",       "Запросить голосование о восстановлении в должности", 0),
        ],
    },
    {
        "id":    "mod",
        "icon":  "🛡",
        "label": "Модерация (ур. 2+)",
        "min_level": 2,
        "commands": [
            ("/warn @user [кол-во] [причина]",   "Выдать предупреждение",           2),
            ("/unwarn @user [кол-во]",            "Снять предупреждение",            2),
            ("/warns @user [-a]",                 "Посмотреть предупреждения игрока",2),
            ("/kick @user [причина]",             "Кикнуть из текущего чата",        2),
            ("/ban @user [причина]",              "Забанить в текущем чате",         2),
            ("/unban @user",                      "Разбанить в текущем чате",        2),
            ("/mute @user [30m|2h|7d] [причина]","Замутить в текущем чате",         2),
            ("/unmute @user",                     "Снять мут в текущем чате",        2),
            ("/point @user +/-N [причина]",       "Выдать / снять очки",             1),
        ],
    },
    {
        "id":    "senior",
        "icon":  "⚔️",
        "label": "Старший состав (ур. 3)",
        "min_level": 3,
        "commands": [
            ("/lkick @user [причина]",   "Кикнуть по всем чатам ветки",            3),
            ("/lban @user [причина]",    "Забанить по всем чатам ветки",            3),
            ("/lunban @user",            "Разбанить по всем чатам ветки",           3),
            ("/lmute @user [время]",     "Замутить по всем чатам ветки",            3),
            ("/lunmute @user",           "Снять мут по всем чатам ветки",           3),
            ("/gban @user [причина]",    "Глобальный бан (ОЧС) во всех чатах",      3),
            ("/getban @user",            "Посмотреть все блокировки пользователя",  3),
            ("/amnistiya @user +|-",     "Включить / выключить амнистию ОЧС",       3),
            ("/radm @user",              "Принудительно восстановить бывшего админа",3),
        ],
    },
    {
        "id":    "admin",
        "icon":  "👑",
        "label": "Администрация (ур. 3)",
        "min_level": 3,
        "commands": [
            ("/add_admin @user уровень", "Назначить администратора (1–3)",  3),
            ("/del_admin @user",         "Снять администратора",            3),
            ("/admins",                  "Список администрации",            0),
            ("/ex_admins",               "Список бывших администраторов",   3),
            ("/logs",                    "Панель логов (адм/команды/чат/система)", 3),
        ],
    },
    {
        "id":    "branches",
        "icon":  "🌿",
        "label": "Ветки (ур. 3)",
        "min_level": 3,
        "commands": [
            ("/bcreate <название>",         "Создать ветку",                    3),
            ("/bdelete <название>",         "Удалить ветку",                    3),
            ("/branches",                   "Список всех веток",                3),
            ("/binfo <название>",           "Группы в ветке",                   3),
            ("/badd <ветка> [chat_id]",     "Добавить группу в ветку",          3),
            ("/bremove <ветка> [chat_id]",  "Убрать группу из ветки",           3),
        ],
    },
    {
        "id":    "support_admin",
        "icon":  "🎧",
        "label": "Поддержка — настройка (ур. 3)",
        "min_level": 3,
        "commands": [
            ("/setrole developer|moderator @user", "Назначить роль поддержки",     3),
            ("/setstatus @user on|off",            "Выдать / снять статус поддержки", 3),
        ],
    },
]


# ══════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════

def main_help_kb(user_level: int) -> InlineKeyboardMarkup:
    """Показывает только разделы, доступные пользователю."""
    buttons = []
    for sec in SECTIONS:
        if user_level >= sec["min_level"]:
            buttons.append([
                InlineKeyboardButton(
                    text=f"{sec['icon']} {sec['label']}",
                    callback_data=f"help_sec:{sec['id']}"
                )
            ])
    buttons.append([
        InlineKeyboardButton(text="❌ Закрыть", callback_data="help_close")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад", callback_data="help_back")
    ]])


# ══════════════════════════════════════════════
#  ПОСТРОЕНИЕ ТЕКСТА РАЗДЕЛА
# ══════════════════════════════════════════════

def build_section_text(section: dict, user_level: int) -> str:
    lines = [
        f"{section['icon']} <b>{section['label']}</b>\n"
    ]
    for cmd, desc, lvl in section["commands"]:
        if user_level >= lvl:
            lines.append(f"<code>{cmd}</code>\n└ {desc}\n")
    return "\n".join(lines)


# ══════════════════════════════════════════════
#  /help
# ══════════════════════════════════════════════

@router.message(Command("help"))
async def help_cmd(message: Message):

    user_level = await get_level(message.from_user.id)

    await message.answer(
        "📖 <b>Справка по командам</b>\n\n"
        "Выбери раздел — покажу только доступные тебе команды:",
        parse_mode="HTML",
        reply_markup=main_help_kb(user_level)
    )


# ══════════════════════════════════════════════
#  CALLBACK: ОТКРЫТЬ РАЗДЕЛ
# ══════════════════════════════════════════════

@router.callback_query(F.data.startswith("help_sec:"))
async def help_section_callback(call: CallbackQuery):

    user_level  = await get_level(call.from_user.id)
    section_id  = call.data.split(":")[1]

    section = next((s for s in SECTIONS if s["id"] == section_id), None)

    if not section:
        return await call.answer("Раздел не найден.")

    # Скрытая проверка — не даём открыть раздел если нет прав
    if user_level < section["min_level"]:
        return await call.answer("❌ Недостаточно прав.", show_alert=True)

    text = build_section_text(section, user_level)

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_kb()
    )
    await call.answer()


# ══════════════════════════════════════════════
#  CALLBACK: НАЗАД В МЕНЮ
# ══════════════════════════════════════════════

@router.callback_query(F.data == "help_back")
async def help_back_callback(call: CallbackQuery):

    user_level = await get_level(call.from_user.id)

    await call.message.edit_text(
        "📖 <b>Справка по командам</b>\n\n"
        "Выбери раздел — покажу только доступные тебе команды:",
        parse_mode="HTML",
        reply_markup=main_help_kb(user_level)
    )
    await call.answer()


# ══════════════════════════════════════════════
#  CALLBACK: ЗАКРЫТЬ
# ══════════════════════════════════════════════

@router.callback_query(F.data == "help_close")
async def help_close_callback(call: CallbackQuery):
    await call.message.delete()
    await call.answer()