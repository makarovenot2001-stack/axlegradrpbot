# handlers/support.py

"""
Два раздела в ЛС бота:

── 📞 Помощь ──────────────────────────────────────────────
  Тикеты: разработчики / гл. модератор / обжалование ОЧС
  Полная логика из оригинала без изменений.

── 🔐 Привязка 2FA ────────────────────────────────────────
  Кнопки:
    · 📛 Сменить ник
    · 🔗 Привязать аккаунт
    · 🔓 Отвязать аккаунт
    · 🔐 Привязать 2FA к аккаунту
    · 🔑 Сбросить пароль
    · 📛 Сменить ник           (дублируется для удобства)
  Все действия логируются в logs/private.log + system_logs.
"""

import secrets
import string
from datetime import datetime

import aiosqlite
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.filters import Command

from database import get_admin_level, get_user
from utils.logger import log_command, log_system

DB_PATH = "data/bot.db"
router  = Router()


# ═══════════════════════════════════════════════════════════════
#  ЛОГИРОВАНИЕ ЛИЧКИ
# ═══════════════════════════════════════════════════════════════

import os
os.makedirs("logs", exist_ok=True)

def _now() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


async def log_private(
    user_id:   int,
    username:  str,
    action:    str,
    details:   str = ""
):
    """Пишет в logs/private.log и в system_logs."""
    line = (
        f"[{_now()}] "
        f"USER:{username}({user_id}) "
        f"ACTION:{action} "
        f"DETAILS:{details}"
    )
    with open("logs/private.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")

    await log_system("PRIVATE", line)


# ═══════════════════════════════════════════════════════════════
#  FSM — состояния для 2FA-меню
# ═══════════════════════════════════════════════════════════════

class TwoFA(StatesGroup):
    # привязка аккаунта
    waiting_nickname    = State()  # ждём ник игрока

    # отвязка
    waiting_unlink_nick = State()

    # смена ника
    waiting_old_nick    = State()
    waiting_new_nick    = State()

    # привязка 2FA
    waiting_2fa_nick    = State()
    waiting_2fa_code    = State()

    # сброс пароля
    waiting_reset_nick  = State()


# ═══════════════════════════════════════════════════════════════
#  БД
# ═══════════════════════════════════════════════════════════════

async def init_support_tables():
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_roles(
                role    TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets(
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                ticket_type TEXT    NOT NULL,
                status      TEXT    DEFAULT 'open',
                created_at  TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_sessions(
                user_id      INTEGER PRIMARY KEY,
                ticket_id    INTEGER NOT NULL,
                session_type TEXT    NOT NULL,
                handler_id   INTEGER,
                started_at   TIMESTAMP
            )
        """)

        # Привязка TG → Minecraft ник
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mc_links(
                tg_id      INTEGER PRIMARY KEY,
                mc_nick    TEXT    NOT NULL,
                linked_at  TIMESTAMP
            )
        """)

        # Выданные 2FA коды (чтобы проверить позже)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS twofa_pending(
                tg_id      INTEGER PRIMARY KEY,
                mc_nick    TEXT    NOT NULL,
                code       TEXT    NOT NULL,
                expires_at TIMESTAMP
            )
        """)

        await db.commit()


# ─── helpers ────────────────────────────────────────────────────

async def get_role_user(role: str) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id FROM support_roles WHERE role = ?", (role,)
        )
        row = await cur.fetchone()
    return row[0] if row else None


async def get_session(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT ticket_id, session_type, handler_id "
            "FROM support_sessions WHERE user_id = ?",
            (user_id,)
        )
        return await cur.fetchone()


async def set_session(user_id: int, ticket_id: int,
                      session_type: str, handler_id: int | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO support_sessions(user_id, ticket_id, session_type, handler_id, started_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                ticket_id    = excluded.ticket_id,
                session_type = excluded.session_type,
                handler_id   = excluded.handler_id,
                started_at   = excluded.started_at
        """, (user_id, ticket_id, session_type, handler_id,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await db.commit()


async def close_session(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM support_sessions WHERE user_id = ?", (user_id,)
        )
        await db.commit()


async def create_ticket(user_id: int, ticket_type: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO support_tickets(user_id, ticket_type, status, created_at)
            VALUES(?,?,'open',?)
        """, (user_id, ticket_type,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await db.commit()
        return cur.lastrowid


async def close_ticket(ticket_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE support_tickets SET status = 'closed' WHERE id = ?",
            (ticket_id,)
        )
        await db.commit()


async def get_user_display(user_id: int) -> str:
    row = await get_user(user_id)
    if not row:
        return str(user_id)
    full = " ".join(x for x in [row[2], row[3]] if x).strip()
    return full or (f"@{row[1]}" if row[1] else str(user_id))


async def get_mc_link(tg_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT mc_nick FROM mc_links WHERE tg_id = ?", (tg_id,)
        )
        row = await cur.fetchone()
    return row[0] if row else None


def _gen_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ═══════════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════════════

TICKET_TYPES = {
    "dev":    {"label": "👨‍💻 Связь с разработчиками", "role": "developer"},
    "mod":    {"label": "🛡 Связь с гл. модератором",  "role": "moderator"},
    "appeal": {"label": "⚖️ Обжаловать ОЧС",           "role": "moderator"},
}


def main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню: два раздела."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Помощь",       callback_data="menu:support")],
        [InlineKeyboardButton(text="🔐 Привязка 2FA", callback_data="menu:twofa")],
    ])


def support_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=v["label"], callback_data=f"sup_open:{k}")]
        for k, v in TICKET_TYPES.items()
    ]
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def twofa_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📛 Сменить ник",            callback_data="2fa:rename")],
        [InlineKeyboardButton(text="🔗 Привязать аккаунт",      callback_data="2fa:link")],
        [InlineKeyboardButton(text="🔓 Отвязать аккаунт",       callback_data="2fa:unlink")],
        [InlineKeyboardButton(text="🔐 Привязать 2FA к аккаунту", callback_data="2fa:add2fa")],
        [InlineKeyboardButton(text="🔑 Сбросить пароль",        callback_data="2fa:resetpass")],
        [InlineKeyboardButton(text="◀️ Назад",                  callback_data="menu:main")],
    ])


def close_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Закрыть обращение")]],
        resize_keyboard=True
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚫 Отмена")]],
        resize_keyboard=True
    )


def handler_kb(user_id: int, ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Принять обращение",
            callback_data=f"sup_accept:{user_id}:{ticket_id}"
        ),
        InlineKeyboardButton(
            text="❌ Закрыть",
            callback_data=f"sup_force_close:{user_id}:{ticket_id}"
        ),
    ]])


def handler_close_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🔒 Закрыть диалог",
            callback_data=f"sup_force_close:{user_id}:0"
        )
    ]])


# ═══════════════════════════════════════════════════════════════
#  /start — главное меню
# ═══════════════════════════════════════════════════════════════

@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):

    if message.chat.type != "private":
        return

    await state.clear()
    await init_support_tables()

    user = message.from_user
    name = user.first_name or user.username or "пользователь"

    username = user.username or str(user.id)
    await log_private(user.id, username, "START", "открыл главное меню")
    await log_command(user.id, username, "start")

    await message.answer(
        f"👋 Привет, <b>{name}</b>!\n\n"
        f"Я — официальный бот поддержки.\n\n"
        f"Выберите раздел:",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )


# ═══════════════════════════════════════════════════════════════
#  НАВИГАЦИЯ ПО ГЛАВНОМУ МЕНЮ
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("menu:"))
async def menu_callback(call: CallbackQuery, state: FSMContext):

    section = call.data.split(":")[1]
    username = call.from_user.username or str(call.from_user.id)

    if section == "main":
        await state.clear()
        await log_private(call.from_user.id, username, "MENU", "вернулся в главное меню")
        await call.message.edit_text(
            "Выберите раздел:",
            reply_markup=main_menu_kb()
        )

    elif section == "support":
        await log_private(call.from_user.id, username, "MENU", "открыл раздел Помощь")
        await call.message.edit_text(
            "📞 <b>Помощь</b>\n\nВыберите тему обращения:",
            parse_mode="HTML",
            reply_markup=support_kb()
        )

    elif section == "twofa":
        await log_private(call.from_user.id, username, "MENU", "открыл раздел 2FA")
        mc_nick = await get_mc_link(call.from_user.id)
        linked  = f"\n🔗 Привязан аккаунт: <b>{mc_nick}</b>" if mc_nick else ""
        await call.message.edit_text(
            f"🔐 <b>Привязка 2FA</b>{linked}\n\nВыберите действие:",
            parse_mode="HTML",
            reply_markup=twofa_menu_kb()
        )

    await call.answer()


# ═══════════════════════════════════════════════════════════════
#  РАЗДЕЛ ПОМОЩЬ — оригинальная логика
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sup_open:"))
async def sup_open_callback(call: CallbackQuery, bot: Bot):

    await init_support_tables()

    user_id     = call.from_user.id
    ticket_type = call.data.split(":")[1]
    username    = call.from_user.username or str(user_id)

    if ticket_type not in TICKET_TYPES:
        return await call.answer("Неизвестный тип обращения.")

    existing = await get_session(user_id)
    if existing:
        return await call.answer(
            "У вас уже есть активное обращение. Закройте его прежде чем открыть новое.",
            show_alert=True
        )

    meta    = TICKET_TYPES[ticket_type]
    role    = meta["role"]
    handler = await get_role_user(role)

    if not handler:
        return await call.answer(
            "❌ Ответственный сотрудник не назначен. Попробуйте позже.",
            show_alert=True
        )

    ticket_id    = await create_ticket(user_id, ticket_type)
    await set_session(user_id, ticket_id, ticket_type, handler)

    await log_private(
        user_id, username,
        "TICKET_OPEN",
        f"ticket_id={ticket_id} type={ticket_type}"
    )

    user_display = await get_user_display(user_id)
    username_str = f"@{call.from_user.username}" if call.from_user.username else user_display

    notify_text = (
        f"📨 <b>Новое обращение #{ticket_id}</b>\n\n"
        f"👤 Пользователь: {username_str} [ID: <code>{user_id}</code>]\n"
        f"📋 Тема: {meta['label']}\n"
        f"🕐 {datetime.now().strftime('%d.%m.%y %H:%M')}"
    )

    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][0].file_id
            await bot.send_photo(
                handler, photo=file_id,
                caption=notify_text, parse_mode="HTML",
                reply_markup=handler_kb(user_id, ticket_id)
            )
        else:
            await bot.send_message(
                handler, notify_text,
                parse_mode="HTML",
                reply_markup=handler_kb(user_id, ticket_id)
            )
    except Exception:
        pass

    await call.message.edit_text(
        f"✅ <b>Обращение #{ticket_id} открыто</b>\n\n"
        f"Тема: {meta['label']}\n\n"
        f"Напишите ваш вопрос — я передам его ответственному сотруднику.\n"
        f"Для закрытия нажмите кнопку ниже.",
        parse_mode="HTML",
        reply_markup=None
    )

    await bot.send_message(
        user_id,
        "⌨️ Введите ваше сообщение:",
        reply_markup=close_kb()
    )

    await call.answer()


@router.callback_query(F.data.startswith("sup_accept:"))
async def sup_accept_callback(call: CallbackQuery, bot: Bot):

    parts     = call.data.split(":")
    target_id = int(parts[1])
    ticket_id = int(parts[2])
    username  = call.from_user.username or str(call.from_user.id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE support_sessions SET handler_id = ? WHERE user_id = ?",
            (call.from_user.id, target_id)
        )
        await db.commit()

    await log_private(
        call.from_user.id, username,
        "TICKET_ACCEPT",
        f"ticket_id={ticket_id} target={target_id}"
    )

    handler_display = await get_user_display(call.from_user.id)

    await call.message.edit_reply_markup(reply_markup=handler_close_kb(target_id))

    await bot.send_message(
        target_id,
        f"👤 <b>{handler_display}</b> принял ваше обращение.\n"
        f"Можете писать — я передам ваши сообщения.",
        parse_mode="HTML"
    )

    await call.answer("✅ Обращение принято.")


@router.callback_query(F.data.startswith("sup_force_close:"))
async def sup_force_close_callback(call: CallbackQuery, bot: Bot):

    parts     = call.data.split(":")
    target_id = int(parts[1])
    username  = call.from_user.username or str(call.from_user.id)

    session = await get_session(target_id)
    if session:
        ticket_id = session[0]
        await close_ticket(ticket_id)
        await close_session(target_id)
        await log_private(
            call.from_user.id, username,
            "TICKET_CLOSE",
            f"ticket_id={ticket_id} target={target_id}"
        )

    try:
        await bot.send_message(
            target_id,
            "🔒 Ваше обращение было закрыто сотрудником поддержки.",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception:
        pass

    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Обращение закрыто.")


# ═══════════════════════════════════════════════════════════════
#  РАЗДЕЛ 2FA — коллбэки кнопок
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("2fa:"))
async def twofa_action_callback(call: CallbackQuery, state: FSMContext, bot: Bot):

    action   = call.data.split(":")[1]
    user_id  = call.from_user.id
    username = call.from_user.username or str(user_id)

    # ── Привязать аккаунт ────────────────────────────────────
    if action == "link":
        mc_link = await get_mc_link(user_id)
        if mc_link:
            await call.answer(
                f"Аккаунт уже привязан: {mc_link}. Сначала отвяжите.",
                show_alert=True
            )
            return

        await state.set_state(TwoFA.waiting_nickname)
        await log_private(user_id, username, "2FA_LINK_START", "начал привязку аккаунта")
        await call.message.edit_text(
            "🔗 <b>Привязка аккаунта</b>\n\n"
            "Введите ваш <b>Minecraft-ник</b>:",
            parse_mode="HTML",
        )
        await bot.send_message(user_id, "Введите ник:", reply_markup=cancel_kb())

    # ── Отвязать аккаунт ─────────────────────────────────────
    elif action == "unlink":
        mc_link = await get_mc_link(user_id)
        if not mc_link:
            await call.answer("Аккаунт не привязан.", show_alert=True)
            return

        await state.set_state(TwoFA.waiting_unlink_nick)
        await log_private(user_id, username, "2FA_UNLINK_START",
                          f"начал отвязку аккаунта mc={mc_link}")
        await call.message.edit_text(
            f"🔓 <b>Отвязка аккаунта</b>\n\n"
            f"Сейчас привязан: <b>{mc_link}</b>\n\n"
            f"Введите ник ещё раз для подтверждения:",
            parse_mode="HTML",
        )
        await bot.send_message(user_id, "Подтвердите ник:", reply_markup=cancel_kb())

    # ── Привязать 2FA ─────────────────────────────────────────
    elif action == "add2fa":
        mc_link = await get_mc_link(user_id)
        if not mc_link:
            await call.answer(
                "Сначала привяжите Minecraft-аккаунт.", show_alert=True
            )
            return

        await state.set_state(TwoFA.waiting_2fa_code)
        code = _gen_code()

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO twofa_pending(tg_id, mc_nick, code, expires_at)
                VALUES(?,?,?,datetime('now','+10 minutes'))
                ON CONFLICT(tg_id) DO UPDATE SET
                    code=excluded.code, expires_at=excluded.expires_at
            """, (user_id, mc_link, code))
            await db.commit()

        await log_private(
            user_id, username,
            "2FA_ADD_CODE_SENT",
            f"mc={mc_link} code={code}"
        )

        await call.message.edit_text(
            f"🔐 <b>Привязка 2FA</b>\n\n"
            f"Ваш код: <code>{code}</code>\n\n"
            f"Введите в игре:\n"
            f"<code>/add2fa {code}</code>\n\n"
            f"⏳ Код действует <b>10 минут</b>.\n\n"
            f"После выполнения команды в игре отправьте код сюда для подтверждения:",
            parse_mode="HTML",
        )
        await bot.send_message(user_id, "Отправьте код после ввода в игре:",
                               reply_markup=cancel_kb())

    # ── Сбросить пароль ───────────────────────────────────────
    elif action == "resetpass":
        mc_link = await get_mc_link(user_id)
        if not mc_link:
            await call.answer(
                "Сначала привяжите Minecraft-аккаунт.", show_alert=True
            )
            return

        await state.set_state(TwoFA.waiting_reset_nick)
        await log_private(user_id, username, "2FA_RESETPASS_START",
                          f"запросил сброс пароля mc={mc_link}")
        await call.message.edit_text(
            f"🔑 <b>Сброс пароля</b>\n\n"
            f"Привязанный аккаунт: <b>{mc_link}</b>\n\n"
            f"Введите ник для подтверждения запроса на сброс пароля:",
            parse_mode="HTML",
        )
        await bot.send_message(user_id, "Введите ник:", reply_markup=cancel_kb())

    # ── Сменить ник ───────────────────────────────────────────
    elif action == "rename":
        mc_link = await get_mc_link(user_id)
        if not mc_link:
            await call.answer(
                "Сначала привяжите Minecraft-аккаунт.", show_alert=True
            )
            return

        await state.set_state(TwoFA.waiting_old_nick)
        await log_private(user_id, username, "2FA_RENAME_START",
                          f"начал смену ника mc={mc_link}")
        await call.message.edit_text(
            f"📛 <b>Смена ника</b>\n\n"
            f"Текущий ник: <b>{mc_link}</b>\n\n"
            f"Введите ваш <b>новый</b> Minecraft-ник:",
            parse_mode="HTML",
        )
        await bot.send_message(user_id, "Введите новый ник:", reply_markup=cancel_kb())

    await call.answer()


# ═══════════════════════════════════════════════════════════════
#  FSM — обработка состояний 2FA
# ═══════════════════════════════════════════════════════════════

# ── Отмена ──────────────────────────────────────────────────────

@router.message(F.chat.type == "private", F.text == "🚫 Отмена")
async def cancel_handler(message: Message, state: FSMContext):

    username = message.from_user.username or str(message.from_user.id)
    current  = await state.get_state()

    if current:
        await log_private(
            message.from_user.id, username,
            "2FA_CANCEL",
            f"отменил действие state={current}"
        )
        await state.clear()
        await message.answer(
            "❌ Действие отменено.",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer("Выберите раздел:", reply_markup=main_menu_kb())
    else:
        await message.answer(
            "Нет активного действия.",
            reply_markup=ReplyKeyboardRemove()
        )


# ── Привязка аккаунта: получаем ник ─────────────────────────────

@router.message(TwoFA.waiting_nickname, F.chat.type == "private")
async def process_link_nick(message: Message, state: FSMContext):

    nick     = message.text.strip()
    user_id  = message.from_user.id
    username = message.from_user.username or str(user_id)

    if not nick or len(nick) > 32:
        await message.answer("⚠️ Некорректный ник. Попробуйте снова:")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO mc_links(tg_id, mc_nick, linked_at)
            VALUES(?,?,?)
            ON CONFLICT(tg_id) DO UPDATE SET
                mc_nick=excluded.mc_nick, linked_at=excluded.linked_at
        """, (user_id, nick, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await db.commit()

    await log_private(
        user_id, username,
        "2FA_LINKED",
        f"привязал аккаунт mc={nick}"
    )

    await state.clear()
    await message.answer(
        f"✅ Аккаунт <b>{nick}</b> успешно привязан!",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Выберите действие:", reply_markup=twofa_menu_kb())


# ── Отвязка аккаунта: подтверждение ника ────────────────────────

@router.message(TwoFA.waiting_unlink_nick, F.chat.type == "private")
async def process_unlink_nick(message: Message, state: FSMContext):

    nick     = message.text.strip()
    user_id  = message.from_user.id
    username = message.from_user.username or str(user_id)
    mc_link  = await get_mc_link(user_id)

    if nick.lower() != (mc_link or "").lower():
        await message.answer(
            "⚠️ Ник не совпадает. Введите точный ник для подтверждения:"
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM mc_links WHERE tg_id = ?", (user_id,))
        await db.execute("DELETE FROM twofa_pending WHERE tg_id = ?", (user_id,))
        await db.commit()

    await log_private(
        user_id, username,
        "2FA_UNLINKED",
        f"отвязал аккаунт mc={mc_link}"
    )

    await state.clear()
    await message.answer(
        f"✅ Аккаунт <b>{mc_link}</b> отвязан.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Выберите раздел:", reply_markup=main_menu_kb())


# ── Привязка 2FA: пользователь вводит код подтверждения ─────────

@router.message(TwoFA.waiting_2fa_code, F.chat.type == "private")
async def process_2fa_code(message: Message, state: FSMContext):

    code     = message.text.strip().upper()
    user_id  = message.from_user.id
    username = message.from_user.username or str(user_id)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT mc_nick, code FROM twofa_pending
            WHERE tg_id = ? AND expires_at > datetime('now')
        """, (user_id,))
        row = await cur.fetchone()

    if not row:
        await log_private(
            user_id, username, "2FA_CODE_EXPIRED",
            "код устарел или не найден"
        )
        await state.clear()
        await message.answer(
            "❌ Код устарел. Попробуйте снова через меню.",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer("Выберите действие:", reply_markup=twofa_menu_kb())
        return

    if code != row["code"]:
        await log_private(
            user_id, username, "2FA_CODE_WRONG",
            f"неверный код mc={row['mc_nick']}"
        )
        await message.answer("❌ Неверный код. Попробуйте ещё раз:")
        return

    # Код верный — помечаем 2FA как активную
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM twofa_pending WHERE tg_id = ?", (user_id,))
        await db.commit()

    await log_private(
        user_id, username,
        "2FA_ACTIVATED",
        f"2FA привязана mc={row['mc_nick']}"
    )

    await state.clear()
    await message.answer(
        f"✅ <b>2FA успешно привязана</b> к аккаунту <b>{row['mc_nick']}</b>!\n\n"
        f"Теперь при входе вам потребуется подтверждение через Telegram.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Выберите действие:", reply_markup=twofa_menu_kb())


# ── Сброс пароля: подтверждение ника ────────────────────────────

@router.message(TwoFA.waiting_reset_nick, F.chat.type == "private")
async def process_reset_nick(message: Message, state: FSMContext, bot: Bot):

    nick     = message.text.strip()
    user_id  = message.from_user.id
    username = message.from_user.username or str(user_id)
    mc_link  = await get_mc_link(user_id)

    if nick.lower() != (mc_link or "").lower():
        await message.answer(
            "⚠️ Ник не совпадает с привязанным аккаунтом. Введите точный ник:"
        )
        return

    # Уведомляем модератора/разработчика о запросе
    handler_id = await get_role_user("moderator") or await get_role_user("developer")

    await log_private(
        user_id, username,
        "2FA_RESETPASS_REQUEST",
        f"запросил сброс пароля mc={mc_link}"
    )

    if handler_id:
        try:
            tg_link = f"@{username}" if message.from_user.username else f"ID: {user_id}"
            await bot.send_message(
                handler_id,
                f"🔑 <b>Запрос на сброс пароля</b>\n\n"
                f"👤 TG: {tg_link}\n"
                f"🎮 Ник: <b>{mc_link}</b>\n"
                f"🕐 {datetime.now().strftime('%d.%m.%y %H:%M')}",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await state.clear()
    await message.answer(
        f"✅ Запрос на сброс пароля для <b>{mc_link}</b> отправлен.\n\n"
        f"Администратор свяжется с вами в ближайшее время.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Выберите действие:", reply_markup=twofa_menu_kb())


# ── Смена ника: новый ник ────────────────────────────────────────

@router.message(TwoFA.waiting_old_nick, F.chat.type == "private")
async def process_rename_new(message: Message, state: FSMContext, bot: Bot):

    new_nick = message.text.strip()
    user_id  = message.from_user.id
    username = message.from_user.username or str(user_id)
    old_nick = await get_mc_link(user_id)

    if not new_nick or len(new_nick) > 32:
        await message.answer("⚠️ Некорректный ник. Попробуйте снова:")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE mc_links SET mc_nick = ?, linked_at = ? WHERE tg_id = ?",
            (new_nick, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id)
        )
        await db.commit()

    # Уведомляем модератора
    handler_id = await get_role_user("moderator") or await get_role_user("developer")

    await log_private(
        user_id, username,
        "2FA_RENAME",
        f"сменил ник mc={old_nick} → {new_nick}"
    )

    if handler_id:
        try:
            tg_link = f"@{username}" if message.from_user.username else f"ID: {user_id}"
            await bot.send_message(
                handler_id,
                f"📛 <b>Смена ника</b>\n\n"
                f"👤 TG: {tg_link}\n"
                f"🔄 {old_nick} → <b>{new_nick}</b>\n"
                f"🕐 {datetime.now().strftime('%d.%m.%y %H:%M')}",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await state.clear()
    await message.answer(
        f"✅ Ник изменён: <b>{old_nick}</b> → <b>{new_nick}</b>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Выберите действие:", reply_markup=twofa_menu_kb())


# ═══════════════════════════════════════════════════════════════
#  ПЕРЕСЫЛКА СООБЩЕНИЙ (активная тикет-сессия)
# ═══════════════════════════════════════════════════════════════

@router.message(F.chat.type == "private", F.text == "❌ Закрыть обращение")
async def close_support_handler(message: Message, bot: Bot, state: FSMContext):

    user_id  = message.from_user.id
    username = message.from_user.username or str(user_id)
    session  = await get_session(user_id)

    if not session:
        return await message.answer(
            "У вас нет активного обращения.",
            reply_markup=ReplyKeyboardRemove()
        )

    ticket_id, _, handler_id = session
    await close_ticket(ticket_id)
    await close_session(user_id)

    await log_private(
        user_id, username,
        "TICKET_CLOSE_USER",
        f"ticket_id={ticket_id}"
    )

    if handler_id:
        try:
            await bot.send_message(
                handler_id,
                f"🔒 Пользователь [ID: <code>{user_id}</code>] закрыл обращение #{ticket_id}.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await message.answer(
        "✅ Обращение закрыто. Спасибо!\n\nВы можете открыть новое через /start",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Выберите раздел:", reply_markup=main_menu_kb())


@router.message(F.chat.type == "private")
async def support_message_handler(message: Message, bot: Bot, state: FSMContext):

    user_id  = message.from_user.id
    username = message.from_user.username or str(user_id)

    # Если в FSM-состоянии — не перехватываем (обрабатывает FSM)
    current = await state.get_state()
    if current:
        return

    session = await get_session(user_id)

    # В активной тикет-сессии — пересылаем
    if session:
        ticket_id, session_type, handler_id = session

        if not handler_id:
            return await message.answer(
                "⏳ Ожидайте — ваше обращение ещё не принято сотрудником."
            )

        user_display = await get_user_display(user_id)
        username_str = (
            f"@{message.from_user.username}"
            if message.from_user.username else user_display
        )

        try:
            header = (
                f"💬 <b>#{ticket_id} | {username_str}</b>\n"
                f"─────────────────\n"
            )
            if message.text:
                await bot.send_message(
                    handler_id, header + message.text,
                    parse_mode="HTML",
                    reply_markup=handler_close_kb(user_id)
                )
            elif message.photo:
                await bot.send_photo(
                    handler_id, photo=message.photo[-1].file_id,
                    caption=header + (message.caption or ""),
                    parse_mode="HTML"
                )
            elif message.document:
                await bot.send_document(
                    handler_id, document=message.document.file_id,
                    caption=header + (message.caption or ""),
                    parse_mode="HTML"
                )
            elif message.voice:
                await bot.send_voice(
                    handler_id, voice=message.voice.file_id,
                    caption=header, parse_mode="HTML"
                )
            else:
                await message.forward(handler_id)
        except Exception as e:
            await message.answer(f"⚠️ Не удалось отправить сообщение: {e}")
        return

    # Обработчик отвечает пользователю
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id FROM support_sessions WHERE handler_id = ? LIMIT 1",
            (user_id,)
        )
        handled = await cur.fetchone()

    if handled:
        target_id = handled[0]
        try:
            reply_text = (
                f"💬 <b>Ответ от сотрудника поддержки:</b>\n"
                f"─────────────────\n"
                f"{message.text or '[медиа]'}"
            )
            await bot.send_message(target_id, reply_text, parse_mode="HTML")
        except Exception:
            pass
        return

    # Никакого контекста — показываем главное меню
    await message.answer("Выберите раздел:", reply_markup=main_menu_kb())


# ═══════════════════════════════════════════════════════════════
#  /setrole, /setstatus — без изменений
# ═══════════════════════════════════════════════════════════════

@router.message(Command("setrole"))
async def setrole_handler(message: Message):

    level = await get_admin_level(message.from_user.id)
    if level < 3:
        return await message.reply("❌ Недостаточно прав.")

    await init_support_tables()

    args = message.text.split()
    if len(args) < 3:
        return await message.reply(
            "❌ Использование: /setrole developer|moderator @username|id"
        )

    role   = args[1].lower()
    target = args[2]

    if role not in ("developer", "moderator"):
        return await message.reply("❌ Доступные роли: developer, moderator")

    from utils.resolver import resolve_user
    result = await resolve_user(message, target)
    if not result.success:
        return await message.reply(f"❌ {result.error}")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO support_roles(role, user_id) VALUES(?,?)
            ON CONFLICT(role) DO UPDATE SET user_id = excluded.user_id
        """, (role, result.user_id))
        await db.commit()

    role_labels = {"developer": "разработчик", "moderator": "гл. модератор"}
    name = result.username or result.first_name or str(result.user_id)
    await message.reply(
        f"✅ Роль <b>{role_labels[role]}</b> назначена: @{name} [ID: {result.user_id}]",
        parse_mode="HTML"
    )


@router.message(Command("setstatus"))
async def setstatus_handler(message: Message, bot: Bot):

    level = await get_admin_level(message.from_user.id)
    if level < 3:
        return await message.reply("❌ Недостаточно прав.")

    await init_support_tables()
    args = message.text.split()

    if len(args) < 3:
        return await message.reply("❌ Использование: /setstatus @username|id on|off")

    from utils.resolver import resolve_user
    result = await resolve_user(message, args[1])
    if not result.success:
        return await message.reply(f"❌ {result.error}")

    flag      = args[2].lower()
    target_id = result.user_id
    name      = result.username or result.first_name or str(target_id)

    if flag == "on":
        handler_id = await get_role_user("moderator")
        ticket_id  = await create_ticket(target_id, "status")
        await set_session(target_id, ticket_id, "status", handler_id)
        try:
            await bot.send_message(
                target_id,
                "🔔 Вам был выдан статус поддержки.\n"
                "Ваши сообщения будут перенаправляться модератору.",
                reply_markup=close_kb()
            )
        except Exception:
            pass
        await message.reply(f"✅ Статус поддержки выдан @{name}.")

    elif flag == "off":
        session = await get_session(target_id)
        if session:
            await close_ticket(session[0])
            await close_session(target_id)
        try:
            await bot.send_message(
                target_id, "✅ Статус поддержки снят.",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception:
            pass
        await message.reply(f"✅ Статус поддержки снят у @{name}.")
    else:
        await message.reply("❌ Укажите on или off.")