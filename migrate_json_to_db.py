"""
One-time migration script to import existing repair_requests.json into the SQLite database.
Run: python migrate_json_to_db.py
"""

import asyncio
import json
import os
import database as db


async def migrate():
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repair_requests.json")

    if not os.path.exists(json_path):
        print("[ERR] repair_requests.json not found. Nothing to migrate.")
        return

    # Initialize DB
    await db.init_db()

    with open(json_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("[ERR] Failed to parse repair_requests.json.")
            return

    if not isinstance(data, list):
        print("[ERR] Expected a JSON array in repair_requests.json.")
        return

    migrated = 0
    for entry in data:
        name = entry.get("name", "Unknown")
        serial = entry.get("serial", "Unknown")
        issue = entry.get("issue")

        await db.save_repair_request(
            name=name,
            serial=serial,
            issue=issue,
            conversation_id=None  # No conversation link for legacy data
        )
        migrated += 1

    print(f"[OK] Migrated {migrated} repair requests from JSON to database.")
    print(f"   Database location: {db.DB_PATH}")


if __name__ == "__main__":
    asyncio.run(migrate())
