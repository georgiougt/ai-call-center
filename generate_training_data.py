"""
Generate training data in Gemini JSONL format from logged conversations.

Exports conversations from the SQLite database into JSONL files suitable
for Gemini supervised fine-tuning.

Usage:
    python generate_training_data.py
    python generate_training_data.py --min-turns 4 --split 0.85
    python generate_training_data.py --completed-only
"""

import asyncio
import json
import os
import random
import argparse
from typing import List, Dict, Any

import database as db

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_PATH = os.path.join(OUTPUT_DIR, "system_prompt.md")


def load_system_prompt() -> str:
    """Load the system prompt from system_prompt.md."""
    if os.path.exists(SYSTEM_PROMPT_PATH):
        with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    else:
        print("[WARN] system_prompt.md not found. Using empty system instruction.")
        return ""


def conversation_to_jsonl_entry(conversation: Dict[str, Any], system_prompt: str) -> Dict[str, Any]:
    """
    Convert a database conversation into the Gemini fine-tuning JSONL format.

    Format:
    {
        "systemInstruction": {"role": "system", "parts": [{"text": "..."}]},
        "contents": [
            {"role": "user", "parts": [{"text": "..."}]},
            {"role": "model", "parts": [{"text": "..."}]}
        ]
    }
    """
    entry = {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": system_prompt}]
        },
        "contents": []
    }

    for msg in conversation.get("messages", []):
        role = msg["role"]  # Already 'user' or 'model' in our DB
        content = msg["content"]

        entry["contents"].append({
            "role": role,
            "parts": [{"text": content}]
        })

    return entry


def validate_entry(entry: Dict[str, Any]) -> bool:
    """Validate that a JSONL entry has the correct structure."""
    if "contents" not in entry:
        return False
    if len(entry["contents"]) < 2:
        return False
    # Ensure alternating roles
    for i, msg in enumerate(entry["contents"]):
        if "role" not in msg or "parts" not in msg:
            return False
        if not msg["parts"] or "text" not in msg["parts"][0]:
            return False
    return True


async def generate(
    min_turns: int = 2,
    split_ratio: float = 0.9,
    completed_only: bool = False,
    seed: int = 42
):
    """Generate training and validation JSONL files."""

    # Initialize DB
    await db.init_db()

    # Load system prompt
    system_prompt = load_system_prompt()
    if not system_prompt:
        print("[WARN] Empty system prompt. Training data will have no system instruction.")

    # Fetch conversations
    conversations = await db.get_complete_conversations(min_turns=min_turns)

    if completed_only:
        # Filter to only conversations that reached a TRANSFER
        conversations = [
            c for c in conversations
            if c.get("department_routed")
        ]

    if not conversations:
        print("[ERR] No qualifying conversations found in the database.")
        print(f"   Minimum turns required: {min_turns}")
        print(f"   Completed only: {completed_only}")
        print("\n[TIP] Use the voice simulation or /chat endpoint to create conversations first.")
        return

    # Convert to JSONL entries
    entries = []
    skipped = 0
    for conv in conversations:
        entry = conversation_to_jsonl_entry(conv, system_prompt)
        if validate_entry(entry):
            entries.append(entry)
        else:
            skipped += 1

    if not entries:
        print("[ERR] No valid training entries could be generated.")
        return

    # Shuffle and split
    random.seed(seed)
    random.shuffle(entries)

    split_idx = max(1, int(len(entries) * split_ratio))
    training_data = entries[:split_idx]
    validation_data = entries[split_idx:] if split_idx < len(entries) else []

    # Write training data
    training_path = os.path.join(OUTPUT_DIR, "training_data.jsonl")
    with open(training_path, "w", encoding="utf-8") as f:
        for entry in training_data:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Write validation data
    validation_path = os.path.join(OUTPUT_DIR, "validation_data.jsonl")
    if validation_data:
        with open(validation_path, "w", encoding="utf-8") as f:
            for entry in validation_data:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Summary
    print("=" * 50)
    print("TRAINING DATA GENERATION COMPLETE")
    print("=" * 50)
    print(f"  Total conversations in DB:    {await db.get_conversation_count()}")
    print(f"  Qualifying conversations:     {len(conversations)}")
    print(f"  Valid training entries:        {len(entries)}")
    print(f"  Skipped (invalid):            {skipped}")
    print(f"  ------------------------------")
    print(f"  Training set:                 {len(training_data)} examples")
    print(f"  Validation set:               {len(validation_data)} examples")
    print(f"  ------------------------------")
    print(f"  Training file:   {training_path}")
    if validation_data:
        print(f"  Validation file: {validation_path}")
    else:
        print(f"  Validation file: (none - need more data)")
    print("=" * 50)

    # Recommendations
    if len(training_data) < 100:
        print(f"\n[TIP] Recommendation: For best results, aim for 100-500 training examples.")
        print(f"   You currently have {len(training_data)}. Keep collecting conversations!")

    if len(training_data) < 20:
        print(f"\n[WARN] Gemini requires at least 20 examples for fine-tuning.")
        print(f"   You have {len(training_data)}. Keep using the call center to build up data.")


def main():
    parser = argparse.ArgumentParser(
        description="Generate Gemini fine-tuning JSONL from logged conversations."
    )
    parser.add_argument(
        "--min-turns", type=int, default=2,
        help="Minimum number of messages in a conversation to include (default: 2)"
    )
    parser.add_argument(
        "--split", type=float, default=0.9,
        help="Training/validation split ratio (default: 0.9)"
    )
    parser.add_argument(
        "--completed-only", action="store_true",
        help="Only include conversations that reached a TRANSFER"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducible splits (default: 42)"
    )

    args = parser.parse_args()

    asyncio.run(generate(
        min_turns=args.min_turns,
        split_ratio=args.split,
        completed_only=args.completed_only,
        seed=args.seed
    ))


if __name__ == "__main__":
    main()
