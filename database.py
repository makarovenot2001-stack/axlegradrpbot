# database.py

import os
import aiosqlite
from datetime import datetime

DB_PATH = "data/bot.db"


async def init_db():
    os.makedirs("data", exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:

        # =========================
        # USERS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            last_seen TIMESTAMP
        )
        """)

        # =========================
        # ADMINS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY,
            level INTEGER NOT NULL,
            added_by INTEGER,
            added_at TIMESTAMP
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS ex_admins(
            user_id INTEGER PRIMARY KEY,
            old_level INTEGER,
            reason TEXT,
            removed_at TIMESTAMP
        )
        """)

        # =========================
        # WARNS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warns(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # POINTS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS points(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            reason TEXT,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # BANS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS bans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            reason TEXT,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # MUTES
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS mutes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            reason TEXT,
            until_date TIMESTAMP,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # GLOBAL BANS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS gbans(
            user_id INTEGER PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            reason TEXT,
            amnesty INTEGER DEFAULT 0,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # BRANCHES
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS branches(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS branch_chats(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL
        )
        """)

        # =========================
        # CHATS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS chats(
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            branch_id INTEGER
        )
        """)

        # =========================
        # RADM VOTES
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS votes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id INTEGER NOT NULL,
            requester_id INTEGER NOT NULL,
            created_at TIMESTAMP,
            expires_at TIMESTAMP,
            status TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS vote_members(
            vote_id INTEGER,
            voter_id INTEGER,
            vote TEXT,
            UNIQUE(vote_id, voter_id)
        )
        """)

        # =========================
        # ANTI DRAIN
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS anti_drain(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # CHAT LOGS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            message TEXT,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # ADMIN LOGS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            target_id INTEGER,
            details TEXT,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # COMMAND LOGS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS command_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            command TEXT,
            args TEXT,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # SYSTEM LOGS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS system_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            message TEXT,
            created_at TIMESTAMP
        )
        """)

        # =========================
        # SETTINGS
        # =========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        await db.commit()

        await db.execute("""
        CREATE TABLE IF NOT EXISTS comments(
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        admin_id   INTEGER NOT NULL,
        text       TEXT    NOT NULL,
        created_at TIMESTAMP
        )
        """)


        await db.execute("""
        CREATE TABLE IF NOT EXISTS chat_members(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TIMESTAMP,
            UNIQUE(chat_id, user_id)
        )
        """)

    print("[DB] Database initialized successfully")


# ==================================================
# USERS
# ==================================================

async def save_user(
    user_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None
):
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
        INSERT INTO users(
            user_id,
            username,
            first_name,
            last_name,
            last_seen
        )
        VALUES(?,?,?,?,?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            last_seen=excluded.last_seen
        """, (
            user_id,
            username,
            first_name,
            last_name,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT *
        FROM users
        WHERE user_id = ?
        """, (user_id,))

        return await cursor.fetchone()


async def get_user_by_username(username: str):
    username = username.replace("@", "").lower()
    print(f"DEBUG searching username: '{username}'")
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
        SELECT * FROM users WHERE LOWER(username) = ?
        """, (username,))
        row = await cursor.fetchone()
        print(f"DEBUG result: {row}")
        return row


# ==================================================
# ADMINS
# ==================================================

async def get_admin_level(user_id: int) -> int:

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT level
        FROM admins
        WHERE user_id = ?
        """, (user_id,))

        row = await cursor.fetchone()

        if not row:
            return 0

        return row[0]


async def add_admin(
    user_id: int,
    level: int,
    added_by: int
):

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
        INSERT OR REPLACE INTO admins(
            user_id,
            level,
            added_by,
            added_at
        )
        VALUES(?,?,?,?)
        """, (
            user_id,
            level,
            added_by,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        await db.commit()


async def remove_admin(
    user_id: int,
    reason: str
):

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT level
        FROM admins
        WHERE user_id = ?
        """, (user_id,))

        row = await cursor.fetchone()

        if not row:
            return

        level = row[0]

        await db.execute("""
        DELETE FROM admins
        WHERE user_id = ?
        """, (user_id,))

        await db.execute("""
        INSERT OR REPLACE INTO ex_admins(
            user_id,
            old_level,
            reason,
            removed_at
        )
        VALUES(?,?,?,?)
        """, (
            user_id,
            level,
            reason,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        await db.commit()


# ==================================================
# ADMIN LISTS
# ==================================================

async def get_admin(user_id: int):

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT *
        FROM admins
        WHERE user_id = ?
        """, (user_id,))

        return await cursor.fetchone()


async def get_all_admins():

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT *
        FROM admins
        ORDER BY level DESC
        """)

        return await cursor.fetchall()


async def get_all_ex_admins():

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT *
        FROM ex_admins
        ORDER BY removed_at DESC
        """)

        return await cursor.fetchall()

async def get_active_warns(user_id: int):

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT *
        FROM warns
        WHERE user_id = ?
        AND active = 1
        """, (user_id,))

        return await cursor.fetchall()

async def get_all_warns(user_id: int):

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT *
        FROM warns
        WHERE user_id = ?
        ORDER BY id DESC
        """, (user_id,))

        return await cursor.fetchall()

# -------------------------------------------------------
# Заменить функцию add_warn в database.py на эту версию
# -------------------------------------------------------

async def add_warn(
    user_id: int,
    admin_id: int,
    amount: int,
    reason: str
):
    """
    Вставляет `amount` отдельных строк (1 строка = 1 ПРЕД).
    amount всегда сохраняется как 1 — для единообразия.
    Так каждый ПРЕД можно снять отдельно, история прозрачна.
    """
    async with aiosqlite.connect(DB_PATH) as db:

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for _ in range(amount):
            await db.execute("""
            INSERT INTO warns(
                user_id,
                admin_id,
                amount,
                reason,
                active,
                created_at
            )
            VALUES(?, ?, 1, ?, 1, ?)
            """, (user_id, admin_id, reason, now))

        await db.commit()

# -------------------------------------------------------
# Добавить функцию remove_warn в database.py
# (после функции add_warn)
# -------------------------------------------------------

async def remove_warn(user_id: int, amount: int = 1) -> int:
    """
    Деактивирует `amount` последних активных предупреждений пользователя.
    Возвращает фактическое количество снятых предупреждений.
    """
    async with aiosqlite.connect(DB_PATH) as db:

        # Берём id последних активных варнов (от новых к старым)
        cursor = await db.execute("""
        SELECT id
        FROM warns
        WHERE user_id = ?
          AND active = 1
        ORDER BY id DESC
        LIMIT ?
        """, (user_id, amount))

        rows = await cursor.fetchall()

        if not rows:
            return 0

        ids = [r[0] for r in rows]

        # Деактивируем найденные записи
        placeholders = ",".join("?" * len(ids))
        await db.execute(f"""
        UPDATE warns
        SET active = 0
        WHERE id IN ({placeholders})
        """, ids)

        await db.commit()

        return len(ids)

# -------------------------------------------------------
# Добавить в database.py — функции для веток
# (после существующих функций admin lists)
# -------------------------------------------------------

# ==================================================
# BRANCHES
# ==================================================

async def create_branch(name: str) -> int:
    """Создаёт ветку. Возвращает id новой ветки."""
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        INSERT INTO branches(name)
        VALUES(?)
        """, (name,))

        await db.commit()
        return cursor.lastrowid


async def delete_branch(branch_id: int):
    """Удаляет ветку и все привязанные к ней чаты."""
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
        DELETE FROM branch_chats
        WHERE branch_id = ?
        """, (branch_id,))

        await db.execute("""
        DELETE FROM branches
        WHERE id = ?
        """, (branch_id,))

        await db.commit()


async def get_branch_by_name(name: str):
    """Возвращает строку ветки по названию (id, name) или None."""
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT id, name
        FROM branches
        WHERE name = ?
        """, (name,))

        return await cursor.fetchone()


async def get_branch_by_id(branch_id: int):
    """Возвращает строку ветки по id (id, name) или None."""
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT id, name
        FROM branches
        WHERE id = ?
        """, (branch_id,))

        return await cursor.fetchone()


async def get_all_branches():
    """Возвращает список всех веток [(id, name), ...]."""
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT id, name
        FROM branches
        ORDER BY name ASC
        """)

        return await cursor.fetchall()


# ==================================================
# BRANCH CHATS
# ==================================================

async def add_chat_to_branch(branch_id: int, chat_id: int):
    """Добавляет чат в ветку."""
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
        INSERT OR IGNORE INTO branch_chats(branch_id, chat_id)
        VALUES(?, ?)
        """, (branch_id, chat_id))

        await db.commit()


async def remove_chat_from_branch(branch_id: int, chat_id: int):
    """Убирает чат из ветки."""
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
        DELETE FROM branch_chats
        WHERE branch_id = ? AND chat_id = ?
        """, (branch_id, chat_id))

        await db.commit()


async def get_branch_chats(branch_id: int):
    """Возвращает все чаты ветки [(id, branch_id, chat_id), ...]."""
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT id, branch_id, chat_id
        FROM branch_chats
        WHERE branch_id = ?
        """, (branch_id,))

        return await cursor.fetchall()


async def get_chat_branch(chat_id: int):
    """Возвращает ветку чата (id, name) или None."""
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT b.id, b.name
        FROM branches b
        JOIN branch_chats bc ON bc.branch_id = b.id
        WHERE bc.chat_id = ?
        """, (chat_id,))

        return await cursor.fetchone()


async def get_chat(chat_id: int):
    """Возвращает запись чата из таблицы chats или None."""
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT chat_id, title, branch_id
        FROM chats
        WHERE chat_id = ?
        """, (chat_id,))

        return await cursor.fetchone()


async def add_comment(
    user_id: int,
    admin_id: int,
    comment_type: str,
    comment: str
):

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
        INSERT INTO comments(
            user_id,
            admin_id,
            comment_type,
            comment,
            created_at
        )
        VALUES(?,?,?,?,?)
        """, (
            user_id,
            admin_id,
            comment_type,
            comment,
            datetime.now().strftime(
                "%d.%m.%Y %H:%M"
            )
        ))

        await db.commit()

async def get_comments(
    user_id: int
):

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute("""
        SELECT *
        FROM comments
        WHERE user_id = ?
        ORDER BY id DESC
        """, (
            user_id,
        ))

        return await cursor.fetchall()

async def get_gban(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT user_id, admin_id, reason, amnesty, created_at
            FROM gbans WHERE user_id = ?
        """, (user_id,))
        return await cursor.fetchone()
        
