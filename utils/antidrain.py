# utils/antidrain.py

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta

from aiogram import Bot

from database import remove_admin, get_admin_level
from utils.logger import log_antidrain

# ==========================================
# ХРАНИЛИЩЕ ДЕЙСТВИЙ В ПАМЯТИ
# window: 60 секунд, порог: 3 действия
# ==========================================

WINDOW_SECONDS = 60
THRESHOLD      = 3

# admin_id -> list of datetime
_action_log: dict[int, list[datetime]] = defaultdict(list)


# ==========================================
# РЕГИСТРАЦИЯ ДЕЙСТВИЯ
# Вызывать из каждого хендлера после действия
# ==========================================

async def register_action(
    bot:        Bot,
    chat_id:    int,
    admin_id:   int,
    admin_name: str,
    action:     str
) -> bool:
    """
    Записывает действие администратора.
    Возвращает True если анти-слив сработал.
    """

    now    = datetime.now()
    cutoff = now - timedelta(seconds=WINDOW_SECONDS)

    # Чистим старые записи
    _action_log[admin_id] = [
        t for t in _action_log[admin_id]
        if t > cutoff
    ]

    _action_log[admin_id].append(now)

    count = len(_action_log[admin_id])

    if count < THRESHOLD:
        return False

    # ── Порог достигнут ───────────────────────────────────────
    level = await get_admin_level(admin_id)

    # lvl3 не трогаем
    if level >= 3:
        return False

    # Сбрасываем счётчик чтобы не срабатывало повторно
    _action_log[admin_id] = []

    reason = (
        f"Анти-слив: {count} действий за {WINDOW_SECONDS} сек "
        f"(последнее: {action})"
    )

    await remove_admin(admin_id, reason)

    await log_antidrain(admin_name, reason)

    await bot.send_message(
        chat_id,
        f"🚨 <b>Анти-слив сработал</b>\n\n"
        f"Администратор <b>@{admin_name}</b> выдал {count} наказания "
        f"за {WINDOW_SECONDS} секунд.\n"
        f"Административные права <b>сняты</b>.\n\n"
        f"Для восстановления — /radm",
        parse_mode="HTML"
    )

    return True