# utils/logger.py

import os
import traceback
from datetime import datetime

import aiosqlite

DB_PATH = "data/bot.db"

LOG_DIR = "logs"

os.makedirs(LOG_DIR, exist_ok=True)


# ==========================================
# FILE WRITER
# ==========================================

async def write_file(
    filename: str,
    text: str
):
    path = f"{LOG_DIR}/{filename}"

    with open(
        path,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(text + "\n")


# ==========================================
# TIME
# ==========================================

def now():

    return datetime.now().strftime(
        "%d.%m.%Y %H:%M:%S"
    )


# ==========================================
# CHAT LOG
# ==========================================

async def log_chat(
    chat_id:      int,
    user_id:      int,
    user_name:    str,
    message_text: str
):
 
    text = (
        f"[{now()}] "
        f"CHAT:{chat_id} "
        f"USER:{user_name} "
        f"TEXT:{message_text}"
    )
 
    await write_file("chat.log", text)
 
    async with aiosqlite.connect(DB_PATH) as db:
 
        await db.execute("""
        INSERT INTO chat_logs(
            chat_id,
            user_id,
            message,
            created_at
        )
        VALUES(?,?,?,?)
        """, (
            chat_id,
            user_id,
            message_text,
            now()
        ))
 
        await db.commit()


# ==========================================
# COMMAND LOG
# ==========================================

async def log_command(
    user_id: int,
    username: str,
    command: str,
    args: str = ""
):

    text = (
        f"[{now()}] "
        f"USER:{username} "
        f"COMMAND:{command} "
        f"ARGS:{args}"
    )

    await write_file(
        "commands.log",
        text
    )

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
        INSERT INTO command_logs(
            user_id,
            command,
            args,
            created_at
        )
        VALUES(?,?,?,?)
        """, (
            user_id,
            command,
            args,
            now()
        ))

        await db.commit()


# ==========================================
# ADMIN LOG
# ==========================================

async def log_admin_action(
    admin_id: int,
    admin_name: str,
    action: str,
    target_id: int,
    target_name: str,
    details: str = ""
):

    text = (
        f"[{now()}] "
        f"ADMIN:{admin_name} "
        f"ACTION:{action} "
        f"TARGET:{target_name} "
        f"DETAILS:{details}"
    )

    await write_file(
        "admin.log",
        text
    )

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
        INSERT INTO admin_logs(
            admin_id,
            action,
            target_id,
            details,
            created_at
        )
        VALUES(?,?,?,?,?)
        """, (
            admin_id,
            action,
            target_id,
            details,
            now()
        ))

        await db.commit()


# ==========================================
# SYSTEM LOG
# ==========================================

async def log_system(
    level: str,
    message: str
):

    text = (
        f"[{now()}] "
        f"[{level}] "
        f"{message}"
    )

    await write_file(
        "system.log",
        text
    )

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
        INSERT INTO system_logs(
            level,
            message,
            created_at
        )
        VALUES(?,?,?)
        """, (
            level,
            message,
            now()
        ))

        await db.commit()

async def log_antidrain(
    admin_name: str,
    reason: str
):

    text = (
        f"[{now()}] "
        f"[ANTI_DRAIN] "
        f"{admin_name} "
        f"{reason}"
    )

    await write_file(
        "admin.log",
        text
    )

    await log_system(
        "ANTI_DRAIN",
        text
    )

async def log_exception(
    error: Exception
):

    trace = traceback.format_exc()

    await log_system(
        "ERROR",
        trace
    )