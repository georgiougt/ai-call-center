"""
One-time migration script to copy data from local SQLite (call_center.db) 
to the new Supabase PostgreSQL database.

Usage:
    1. Make sure DATABASE_URL is set in your .env file.
    2. Run: python migrate_sqlite_to_supabase.py
"""

import asyncio
import aiosqlite
import asyncpg
import os
import sys
import io
from dotenv import load_dotenv

# Force UTF-8 output for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "call_center.db")


async def migrate():
    if not DATABASE_URL:
        print("[ERR] DATABASE_URL not set in .env. Cannot migrate.")
        sys.exit(1)

    if not os.path.exists(SQLITE_PATH):
        print(f"[ERR] SQLite database not found: {SQLITE_PATH}")
        sys.exit(1)

    print("=" * 50)
    print("Migrating SQLite → Supabase PostgreSQL")
    print("=" * 50)

    # Connect to both databases
    pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    sqlite_db = await aiosqlite.connect(SQLITE_PATH)
    sqlite_db.row_factory = aiosqlite.Row

    try:
        # --- Create tables in PostgreSQL (same as database.py init_db) ---
        async with pg_pool.acquire() as pg:
            await pg.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT (NOW()::TEXT),
                    language TEXT DEFAULT 'el',
                    department_routed TEXT,
                    has_repair_data INTEGER DEFAULT 0
                )
            """)
            await pg.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'model')),
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL DEFAULT (NOW()::TEXT)
                )
            """)
            await pg.execute("""
                CREATE TABLE IF NOT EXISTS repair_requests (
                    id SERIAL PRIMARY KEY,
                    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
                    name TEXT NOT NULL,
                    serial TEXT NOT NULL,
                    issue TEXT,
                    timestamp TEXT NOT NULL DEFAULT (NOW()::TEXT)
                )
            """)
            await pg.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)")
            await pg.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)")

        print("[OK] Tables created in Supabase.")

        # --- Migrate conversations ---
        cursor = await sqlite_db.execute("SELECT id, session_id, created_at, language, department_routed, has_repair_data FROM conversations ORDER BY id")
        conversations = await cursor.fetchall()
        print(f"\n[...] Migrating {len(conversations)} conversations...")

        # Keep track of old_id -> new_id mapping (IDs may differ in PostgreSQL)
        id_map = {}

        async with pg_pool.acquire() as pg:
            for conv in conversations:
                try:
                    row = await pg.fetchrow(
                        """INSERT INTO conversations (session_id, created_at, language, department_routed, has_repair_data)
                           VALUES ($1, $2, $3, $4, $5) 
                           ON CONFLICT (session_id) DO NOTHING
                           RETURNING id""",
                        conv["session_id"], conv["created_at"], conv["language"],
                        conv["department_routed"], conv["has_repair_data"]
                    )
                    if row:
                        id_map[conv["id"]] = row["id"]
                    else:
                        # Already exists, get its ID
                        existing = await pg.fetchrow("SELECT id FROM conversations WHERE session_id = $1", conv["session_id"])
                        if existing:
                            id_map[conv["id"]] = existing["id"]
                except Exception as e:
                    print(f"  [WARN] Skipping conversation {conv['id']}: {e}")

        print(f"  [OK] Migrated {len(id_map)} conversations.")

        # --- Migrate messages ---
        cursor = await sqlite_db.execute("SELECT id, conversation_id, role, content, timestamp FROM messages ORDER BY id")
        messages = await cursor.fetchall()
        print(f"\n[...] Migrating {len(messages)} messages...")

        msg_count = 0
        async with pg_pool.acquire() as pg:
            for msg in messages:
                new_conv_id = id_map.get(msg["conversation_id"])
                if not new_conv_id:
                    continue
                try:
                    await pg.execute(
                        "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES ($1, $2, $3, $4)",
                        new_conv_id, msg["role"], msg["content"], msg["timestamp"]
                    )
                    msg_count += 1
                except Exception as e:
                    print(f"  [WARN] Skipping message {msg['id']}: {e}")

        print(f"  [OK] Migrated {msg_count} messages.")

        # --- Migrate repair requests ---
        cursor = await sqlite_db.execute("SELECT id, conversation_id, name, serial, issue, timestamp FROM repair_requests ORDER BY id")
        repairs = await cursor.fetchall()
        print(f"\n[...] Migrating {len(repairs)} repair requests...")

        repair_count = 0
        async with pg_pool.acquire() as pg:
            for rep in repairs:
                new_conv_id = id_map.get(rep["conversation_id"]) if rep["conversation_id"] else None
                try:
                    await pg.execute(
                        "INSERT INTO repair_requests (conversation_id, name, serial, issue, timestamp) VALUES ($1, $2, $3, $4, $5)",
                        new_conv_id, rep["name"], rep["serial"], rep["issue"], rep["timestamp"]
                    )
                    repair_count += 1
                except Exception as e:
                    print(f"  [WARN] Skipping repair request {rep['id']}: {e}")

        print(f"  [OK] Migrated {repair_count} repair requests.")

        # --- Summary ---
        print("\n" + "=" * 50)
        print("MIGRATION COMPLETE!")
        print(f"  Conversations:    {len(id_map)}")
        print(f"  Messages:         {msg_count}")
        print(f"  Repair Requests:  {repair_count}")
        print("=" * 50)

    finally:
        await sqlite_db.close()
        await pg_pool.close()


if __name__ == "__main__":
    asyncio.run(migrate())
