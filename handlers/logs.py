# handlers/logs.py

import aiosqlite
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from utils.permissions import check_adm_lvl, get_level

DB_PATH   = "data/bot.db"
PAGE_SIZE = 10

router = Router()


# ==========================================
# ТИПЫ ЛОГОВ
# ==========================================

LOGS = {
    "admin":   {"label": "🛡 Админ-лог",     "table": "admin_logs",   "icon": "🛡"},
    "command": {"label": "⌨️ Команды",        "table": "command_logs", "icon": "⌨️"},
    "system":  {"label": "⚙️ Система",        "table": "system_logs",  "icon": "⚙️"},
    "chat":    {"label": "💬 Чат",            "table": "chat_logs",    "icon": "💬"},
}


# ==========================================
# КЛАВИАТУРА ГЛАВНОГО МЕНЮ
# ==========================================

def main_menu_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=v["label"], callback_data=f"logs_view:{k}:0")]
        for k, v in LOGS.items()
    ]
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="logs_close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==========================================
# КЛАВИАТУРА НАВИГАЦИИ
# ==========================================

def nav_kb(log_type: str, page: int, total: int) -> InlineKeyboardMarkup:
    max_page = max(0, (total - 1) // PAGE_SIZE)
    row = []

    if page > 0:
        row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"logs_view:{log_type}:{page - 1}"))

    row.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{max_page + 1}",
        callback_data="logs_noop"
    ))

    if page < max_page:
        row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"logs_view:{log_type}:{page + 1}"))

    return InlineKeyboardMarkup(inline_keyboard=[
        row,
        [InlineKeyboardButton(text="🔙 Меню", callback_data="logs_menu")],
    ])


# ==========================================
# ФОРМАТИРОВАНИЕ СТРОК
# ==========================================

def fmt_date(raw) -> str:
    if not raw:
        return "—"
    try:
        dt = datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m.%y %H:%M")
    except Exception:
        return str(raw)[:16]


def fmt_admin_row(row) -> str:
    # id, admin_id, action, target_id, details, created_at
    return (
        f"┌ 🕐 <code>{fmt_date(row[5])}</code>\n"
        f"├ 👤 Админ: <code>{row[1]}</code>\n"
        f"├ ⚡ Действие: <b>{row[2]}</b>\n"
        f"├ 🎯 Цель: <code>{row[3]}</code>\n"
        f"└ 📋 {row[4] or '—'}"
    )


def fmt_command_row(row) -> str:
    # id, user_id, command, args, created_at
    return (
        f"┌ 🕐 <code>{fmt_date(row[4])}</code>\n"
        f"├ 👤 Пользователь: <code>{row[1]}</code>\n"
        f"├ ⌨️ Команда: <b>{row[2]}</b>\n"
        f"└ 📝 Аргументы: {row[3] or '—'}"
    )


def fmt_system_row(row) -> str:
    # id, level, message, created_at
    level_icons = {"INFO": "ℹ️", "ERROR": "❗", "SHUTDOWN": "🔴", "ANTI_DRAIN": "🚨"}
    icon = level_icons.get(str(row[1]), "⚙️")
    return (
        f"┌ 🕐 <code>{fmt_date(row[3])}</code>\n"
        f"├ {icon} Уровень: <b>{row[1]}</b>\n"
        f"└ 💬 {str(row[2])[:200]}"
    )


def fmt_chat_row(row) -> str:
    # id, chat_id, user_id, message, created_at
    msg = str(row[3] or "").replace("<", "&lt;").replace(">", "&gt;")[:120]
    return (
        f"┌ 🕐 <code>{fmt_date(row[4])}</code>\n"
        f"├ 💬 Чат: <code>{row[1]}</code>\n"
        f"├ 👤 Пользователь: <code>{row[2]}</code>\n"
        f"└ 📝 {msg}"
    )


FORMATTERS = {
    "admin":   fmt_admin_row,
    "command": fmt_command_row,
    "system":  fmt_system_row,
    "chat":    fmt_chat_row,
}

QUERIES = {
    "admin":   "SELECT * FROM admin_logs   ORDER BY id DESC LIMIT ? OFFSET ?",
    "command": "SELECT * FROM command_logs ORDER BY id DESC LIMIT ? OFFSET ?",
    "system":  "SELECT * FROM system_logs  ORDER BY id DESC LIMIT ? OFFSET ?",
    "chat":    "SELECT * FROM chat_logs    ORDER BY id DESC LIMIT ? OFFSET ?",
}

COUNT_QUERIES = {
    k: f"SELECT COUNT(*) FROM {v['table']}"
    for k, v in LOGS.items()
}


# ==========================================
# ПОЛУЧЕНИЕ ДАННЫХ
# ==========================================

async def fetch_logs(log_type: str, page: int):
    offset = page * PAGE_SIZE
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(QUERIES[log_type], (PAGE_SIZE, offset))
        rows   = await cursor.fetchall()
        cursor = await db.execute(COUNT_QUERIES[log_type])
        total  = (await cursor.fetchone())[0]
    return rows, total


# ==========================================
# ПОСТРОЕНИЕ СООБЩЕНИЯ С ЛОГАМИ
# ==========================================

async def build_log_page(log_type: str, page: int) -> tuple[str, InlineKeyboardMarkup]:
    rows, total = await fetch_logs(log_type, page)
    meta        = LOGS[log_type]
    formatter   = FORMATTERS[log_type]
    max_page    = max(0, (total - 1) // PAGE_SIZE)

    header = (
        f"{meta['icon']} <b>{meta['label']}</b>\n"
        f"📊 Всего записей: <b>{total}</b> | "
        f"Страница <b>{page + 1}</b> из <b>{max_page + 1}</b>\n"
        f"{'─' * 30}\n\n"
    )

    if not rows:
        body = "📭 <i>Записей нет.</i>"
    else:
        body = ("\n\n" + "─" * 28 + "\n\n").join(formatter(r) for r in rows)

    return header + body, nav_kb(log_type, page, total)


# ==========================================
# /logs
# ==========================================

@router.message(Command("logs"))
async def logs_handler(message: Message):

    if not await check_adm_lvl(message, required_level=3):
        return

    await message.answer(
        "📂 <b>Панель логов</b>\n\n"
        "Выберите тип лога для просмотра:",
        parse_mode = "HTML",
        reply_markup = main_menu_kb()
    )


# ==========================================
# CALLBACK: ПРОСМОТР СТРАНИЦЫ
# ==========================================

@router.callback_query(F.data.startswith("logs_view:"))
async def logs_view_callback(call: CallbackQuery):

    level = await get_level(call.from_user.id)
    if level < 3:
        return await call.answer("❌ Недостаточно прав.", show_alert=True)

    _, log_type, page_str = call.data.split(":")
    page = int(page_str)

    if log_type not in LOGS:
        return await call.answer("Неизвестный тип лога.")

    text, kb = await build_log_page(log_type, page)

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()


# ==========================================
# CALLBACK: ВЕРНУТЬСЯ В МЕНЮ
# ==========================================

@router.callback_query(F.data == "logs_menu")
async def logs_menu_callback(call: CallbackQuery):

    level = await get_level(call.from_user.id)
    if level < 3:
        return await call.answer("❌ Недостаточно прав.", show_alert=True)

    await call.message.edit_text(
        "📂 <b>Панель логов</b>\n\n"
        "Выберите тип лога для просмотра:",
        parse_mode   = "HTML",
        reply_markup = main_menu_kb()
    )
    await call.answer()


# ==========================================
# CALLBACK: ЗАКРЫТЬ
# ==========================================

@router.callback_query(F.data == "logs_close")
async def logs_close_callback(call: CallbackQuery):
    await call.message.delete()
    await call.answer()


# ==========================================
# CALLBACK: ЗАГЛУШКА (номер страницы)
# ==========================================

@router.callback_query(F.data == "logs_noop")
async def logs_noop_callback(call: CallbackQuery):
    await call.answer()