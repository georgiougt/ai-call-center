import asyncio
import sys
import io
import json

import database as db

# Force UTF-8 output for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    print("=== AI Call Center Database Logs ===")
    
    # 1. Show summary stats
    total_convs = await db.get_conversation_count()
    total_msgs = await db.get_message_count()
    print(f"\nTotal Conversations: {total_convs}")
    print(f"Total Messages: {total_msgs}\n")

    # 2. Show recent repair requests
    print("--- Recent Repair Requests ---")
    repairs = await db.get_all_repair_requests()
    if not repairs:
        print("No repair requests logged yet.")
    else:
        for r in repairs[:5]: # Show top 5
            print(f"ID: {r['id']} | Time: {r['timestamp']} | Name: {r['name']} | Serial: {r['serial']} | Issue: {r['issue']}")

    # 3. Show recent conversations
    print("\n--- Last 5 Conversations ---")
    convs = await db.get_all_conversations(limit=5)
    if not convs:
        print("No conversations logged yet.")
    else:
        for c in convs:
            print(f"\nSession ID: {c['session_id']}")
            print(f"Time: {c['created_at']} | Dept: {c['department_routed'] or 'None'} | Msgs: {c['message_count']}")
            
            # Fetch and print actual messages for this conversation
            full_conv = await db.get_conversation_with_messages(c['id'])
            if full_conv and 'messages' in full_conv:
                for msg in full_conv['messages']:
                    role_prefix = "🧑 You" if msg['role'] == 'user' else "🤖 AI "
                    print(f"  {role_prefix}: {msg['content']}")
            print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())
