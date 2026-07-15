# main.py

import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN, OWNER_ID
from database import init_db, add_admin
from middlewares.user_middleware import UserMiddleware
from utils.logger import log_system, log_exception

from handlers.admin import router as admin_router
from handlers.warns import router as warns_router
from handlers.chat_members import router as chat_members_router
from handlers.points import router as point_router
from handlers.chat_logger import router as chat_logger_router
from handlers.radm import router as radm_router
from handlers.branches import router as branch_router
from handlers.punishments import router as punishments_router
from handlers.gban import router as gban_router
from handlers.bot_chats import router as bot_chats_router
from handlers.logs import router as logs_router
from handlers.support import router as support_router
from handlers.help import router as help_router
from handlers.get import router as get_router
from handlers.mt import router as mt_router
from handlers.info import router as info_router
from handlers.userlog import router as userlog_router

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

_start_time: datetime = None


# ==========================================
# STARTUP
# ==========================================

async def startup():
    global _start_time
    _start_time = datetime.now()

    await init_db()
    await add_admin(OWNER_ID, 3, OWNER_ID)
    await log_system("INFO", "Bot started")

    print("\033[92m" + """
╔══════════════════════════════════════╗
║           БОТ ЗАПУЩЕН  ✓             ║
╚══════════════════════════════════════╝
""" + "\033[0m")


# ==========================================
# SHUTDOWN
# ==========================================

async def shutdown():
    now      = datetime.now()
    uptime   = now - _start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    started_str = _start_time.strftime("%d.%m.%Y %H:%M:%S")
    stopped_str = now.strftime("%d.%m.%Y %H:%M:%S")

    report = (
        f"Запуск: {started_str} | "
        f"Остановка: {stopped_str} | "
        f"Время работы: {uptime_str}"
    )

    await log_system("SHUTDOWN", report)

    print("\033[91m" + f"""
╔══════════════════════════════════════╗
║           БОТ ОСТАНОВЛЕН  ✗          ║
╠══════════════════════════════════════╣
║  Запуск:     {started_str}  ║
║  Остановка:  {stopped_str}  ║
║  Аптайм:     {uptime_str:<27} ║
╚══════════════════════════════════════╝
""" + "\033[0m")


# ==========================================
# ERROR HANDLER
# ==========================================

async def on_error(update, exception):
    await log_exception(exception)
    return True


# ==========================================
# MAIN
# ==========================================

async def main():

    await startup()

    dp.errors.register(on_error)
    dp.message.middleware(UserMiddleware())

    dp.include_router(admin_router)
    dp.include_router(warns_router)
    dp.include_router(chat_members_router)
    dp.include_router(point_router)
    dp.include_router(radm_router)
    dp.include_router(branch_router)
    dp.include_router(punishments_router)
    dp.include_router(gban_router)
    dp.include_router(bot_chats_router)
    dp.include_router(logs_router)
    dp.include_router(support_router)
    dp.include_router(help_router)
    dp.include_router(get_router)
    dp.include_router(mt_router)
    dp.include_router(info_router)
    dp.include_router(userlog_router)
    dp.include_router(chat_logger_router)  # всегда последним

    try:
        await dp.start_polling(bot, allowed_updates=["message", "chat_member", "my_chat_member", "callback_query"])
    finally:
        await shutdown()
        await bot.session.close()


if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    asyncio.run(main())