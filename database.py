"""
PostgreSQL Database module for the AI Call Center (Supabase).
Handles conversation logging, message storage, and repair request persistence.
Migrated from SQLite (aiosqlite) to PostgreSQL (asyncpg).
"""

import asyncpg
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Connection pool (initialized once on startup)
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Get or create connection pool."""
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set in .env file.")
        
        # Add SSL=require for Supabase if not in the URL
        # Increase max size for higher concurrency
        _pool = await asyncpg.create_pool(
            DATABASE_URL, 
            min_size=1, 
            max_size=10,
            command_timeout=60
        )
    return _pool


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def init_db():
    """Initialize the database and create tables if they don't exist."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (NOW()::TEXT),
                language TEXT DEFAULT 'el',
                department_routed TEXT,
                has_repair_data INTEGER DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'model')),
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT (NOW()::TEXT)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS repair_requests (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                serial TEXT NOT NULL,
                issue TEXT,
                timestamp TEXT NOT NULL DEFAULT (NOW()::TEXT)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_leads (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                phone TEXT,
                company TEXT,
                timestamp TEXT NOT NULL DEFAULT (NOW()::TEXT)
            )
        """)

        # Indexes for common queries
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation 
            ON messages(conversation_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_session 
            ON conversations(session_id)
        """)

        print("[OK] Database initialized successfully (Supabase PostgreSQL).")


# --- Conversation Operations ---

async def create_conversation(session_id: str, language: str = "el") -> int:
    """Create a new conversation and return its ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO conversations (session_id, language, created_at) VALUES ($1, $2, $3) RETURNING id",
            session_id, language, datetime.now().isoformat()
        )
        return row["id"]


async def get_or_create_conversation(session_id: str, language: str = "el") -> int:
    """Get existing conversation by session_id, or create a new one."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM conversations WHERE session_id = $1",
            session_id
        )
        if row:
            return row["id"]

    # Create new if not found
    return await create_conversation(session_id, language)


async def update_conversation_routing(conversation_id: int, department: str):
    """Update the department a conversation was routed to."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversations SET department_routed = $1 WHERE id = $2",
            department, conversation_id
        )


async def mark_conversation_has_repair(conversation_id: int):
    """Flag a conversation as having repair data."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversations SET has_repair_data = 1 WHERE id = $1",
            conversation_id
        )


# --- Message Operations ---

async def add_message(conversation_id: int, role: str, content: str) -> int:
    """Add a message to a conversation. Role must be 'user' or 'model'."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES ($1, $2, $3, $4) RETURNING id",
            conversation_id, role, content, datetime.now().isoformat()
        )
        return row["id"]


async def get_conversation_messages(conversation_id: int) -> List[Dict[str, Any]]:
    """Get all messages for a conversation, ordered by timestamp."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, conversation_id, role, content, timestamp FROM messages WHERE conversation_id = $1 ORDER BY id ASC",
            conversation_id
        )
        return [dict(row) for row in rows]


# --- Repair Request Operations ---

async def save_repair_request(name: str, serial: str, issue: Optional[str] = None,
                               conversation_id: Optional[int] = None) -> int:
    """Save a repair request to the database."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO repair_requests (conversation_id, name, serial, issue, timestamp) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            conversation_id, name, serial, issue, datetime.now().isoformat()
        )

        # Flag the conversation 
        if conversation_id:
            await mark_conversation_has_repair(conversation_id)

        return row["id"]


async def save_sales_lead(name: str, phone: Optional[str] = None, company: Optional[str] = None,
                          conversation_id: Optional[int] = None) -> int:
    """Save a sales lead to the database."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO sales_leads (conversation_id, name, phone, company, timestamp) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            conversation_id, name, phone, company, datetime.now().isoformat()
        )
        return row["id"]


# --- Query Operations (for training data export & review) ---

async def get_all_conversations(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Get all conversations with message counts."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT 
                c.id, c.session_id, c.created_at, c.language, 
                c.department_routed, c.has_repair_data,
                COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
            LIMIT $1 OFFSET $2
        """, limit, offset)
        return [dict(row) for row in rows]


async def get_conversation_with_messages(conversation_id: int) -> Optional[Dict[str, Any]]:
    """Get a full conversation with all its messages."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Get conversation
        conv = await conn.fetchrow(
            "SELECT id, session_id, created_at, language, department_routed, has_repair_data FROM conversations WHERE id = $1",
            conversation_id
        )
        if not conv:
            return None

        conv_dict = dict(conv)

        # Get messages
        messages = await conn.fetch(
            "SELECT id, conversation_id, role, content, timestamp FROM messages WHERE conversation_id = $1 ORDER BY id ASC",
            conversation_id
        )
        conv_dict["messages"] = [dict(m) for m in messages]

        return conv_dict


async def get_complete_conversations(min_turns: int = 2) -> List[Dict[str, Any]]:
    """
    Get all conversations that have at least `min_turns` messages.
    Used for training data export.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Get qualifying conversation IDs
        rows = await conn.fetch("""
            SELECT c.id
            FROM conversations c
            JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            HAVING COUNT(m.id) >= $1
            ORDER BY c.created_at ASC
        """, min_turns)
        conv_ids = [row["id"] for row in rows]

    # Fetch full data for each
    conversations = []
    for conv_id in conv_ids:
        conv = await get_conversation_with_messages(conv_id)
        if conv:
            conversations.append(conv)

    return conversations


async def get_all_repair_requests() -> List[Dict[str, Any]]:
    """Get all repair requests."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, conversation_id, name, serial, issue, timestamp FROM repair_requests ORDER BY timestamp DESC"
        )
        return [dict(row) for row in rows]


async def get_conversation_count() -> int:
    """Get total number of conversations."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) FROM conversations")
        return row[0]


async def get_message_count() -> int:
    """Get total number of messages."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) FROM messages")
        return row[0]


# --- Update & Delete Operations (for Correction UI) ---

async def update_repair_request(request_id: int, name: str, serial: str, issue: Optional[str] = None):
    """Update an existing repair request."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE repair_requests SET name = $1, serial = $2, issue = $3 WHERE id = $4",
            name, serial, issue, request_id
        )


async def update_message(message_id: int, content: str):
    """Update the content of a message (e.g., if AI misheard STT)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE messages SET content = $1 WHERE id = $2",
            content, message_id
        )


async def delete_conversation(conversation_id: int):
    """Delete a conversation and all its messages (via CASCADE)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM conversations WHERE id = $1", conversation_id)


async def delete_repair_request(request_id: int):
    """Delete a specific repair request entry."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM repair_requests WHERE id = $1", request_id)
