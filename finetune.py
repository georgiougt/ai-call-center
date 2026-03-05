"""
Automated Fine-Tuning Script for the AI Call Center Receptionist.

Uses the google-generativeai SDK to launch a supervised fine-tuning job
on Gemini, using conversations exported by generate_training_data.py.

Usage:
    python finetune.py                    # Run the fine-tuning job
    python finetune.py --dry-run          # Validate data without starting a job
    python finetune.py --status JOB_NAME  # Check status of an existing job

Environment variables (.env):
    GEMINI_API_KEY           - Your Gemini API key (required)
    GEMINI_BASE_MODEL        - Base model to fine-tune (default: models/gemini-2.0-flash-001)
    FINETUNE_EPOCHS          - Number of training epochs (default: 5)
    FINETUNE_DISPLAY_NAME    - Display name for the tuned model
"""

import google.generativeai as genai
import json
import os
import sys
import time
import argparse
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BASE_MODEL = os.getenv("GEMINI_BASE_MODEL", "models/gemini-2.0-flash-001")
EPOCHS = int(os.getenv("FINETUNE_EPOCHS", "5"))
DISPLAY_NAME = os.getenv("FINETUNE_DISPLAY_NAME", "ai-call-center-receptionist")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRAINING_FILE = os.path.join(SCRIPT_DIR, "training_data.jsonl")
VALIDATION_FILE = os.path.join(SCRIPT_DIR, "validation_data.jsonl")


def validate_jsonl(filepath: str) -> tuple[bool, int, list[str]]:
    """
    Validate a JSONL file for Gemini fine-tuning format.
    Returns: (is_valid, line_count, error_messages)
    """
    errors = []
    line_count = 0

    if not os.path.exists(filepath):
        return False, 0, [f"File not found: {filepath}"]

    with open(filepath, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            line_count += 1

            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"Line {i}: Invalid JSON - {e}")
                continue

            # Check required fields
            if "contents" not in entry:
                errors.append(f"Line {i}: Missing 'contents' field")
                continue

            contents = entry["contents"]
            if not isinstance(contents, list) or len(contents) < 2:
                errors.append(f"Line {i}: 'contents' must be a list with at least 2 messages")
                continue

            # Check message structure
            for j, msg in enumerate(contents):
                if "role" not in msg:
                    errors.append(f"Line {i}, message {j}: Missing 'role'")
                elif msg["role"] not in ("user", "model"):
                    errors.append(f"Line {i}, message {j}: Invalid role '{msg['role']}' (must be 'user' or 'model')")

                if "parts" not in msg:
                    errors.append(f"Line {i}, message {j}: Missing 'parts'")
                elif not isinstance(msg["parts"], list) or not msg["parts"]:
                    errors.append(f"Line {i}, message {j}: 'parts' must be a non-empty list")
                elif "text" not in msg["parts"][0]:
                    errors.append(f"Line {i}, message {j}: First part missing 'text'")

    return len(errors) == 0, line_count, errors


def dry_run():
    """Validate training data without starting a fine-tuning job."""
    print("=" * 50)
    print("DRY RUN - Validating Training Data")
    print("=" * 50)

    # Check API key
    if not GEMINI_API_KEY:
        print("[WARN] GEMINI_API_KEY not set in .env")
    else:
        print(f"[OK] API Key: {'*' * 8}...{GEMINI_API_KEY[-4:]}")

    print(f"   Base Model:    {BASE_MODEL}")
    print(f"   Epochs:        {EPOCHS}")
    print(f"   Display Name:  {DISPLAY_NAME}")
    print()

    # Validate training file
    print(f"   Training file: {TRAINING_FILE}")
    valid, count, errors = validate_jsonl(TRAINING_FILE)
    if valid:
        print(f"   [OK] Valid - {count} examples")
    else:
        print(f"   [ERR] Invalid - {count} examples, {len(errors)} errors:")
        for err in errors[:10]:
            print(f"      • {err}")
        if len(errors) > 10:
            print(f"      ... and {len(errors) - 10} more errors")

    # Validate validation file
    print(f"\n   Validation file: {VALIDATION_FILE}")
    if os.path.exists(VALIDATION_FILE):
        valid_v, count_v, errors_v = validate_jsonl(VALIDATION_FILE)
        if valid_v:
            print(f"   [OK] Valid - {count_v} examples")
        else:
            print(f"   [ERR] Invalid - {count_v} examples, {len(errors_v)} errors:")
            for err in errors_v[:5]:
                print(f"      • {err}")
    else:
        print(f"   [WARN] Not found (optional)")

    # Recommendations
    print("\n" + "=" * 50)
    if valid and count >= 20:
        print("[OK] Ready for fine-tuning! Run without --dry-run to start.")
    elif valid and count < 20:
        print(f"[WARN] Data is valid but only {count} examples. Gemini needs at least 20.")
        print("   Keep collecting conversations, then re-export training data.")
    else:
        print("[ERR] Training data has errors. Fix them before fine-tuning.")
    print("=" * 50)

    return valid and count >= 20


def check_status(job_name: str):
    """Check the status of an existing fine-tuning job."""
    if not GEMINI_API_KEY:
        print("[ERR] GEMINI_API_KEY required. Set it in .env")
        sys.exit(1)

    genai.configure(api_key=GEMINI_API_KEY)

    try:
        tuned_model = genai.get_tuned_model(job_name)
        print("=" * 50)
        print(f"Tuning Job Status: {job_name}")
        print("=" * 50)
        print(f"  Name:          {tuned_model.name}")
        print(f"  Display Name:  {tuned_model.display_name}")
        print(f"  State:         {tuned_model.state}")
        print(f"  Base Model:    {tuned_model.base_model}")
        print(f"  Created:       {tuned_model.create_time}")
        print(f"  Updated:       {tuned_model.update_time}")

        if hasattr(tuned_model, 'tuning_task') and tuned_model.tuning_task:
            task = tuned_model.tuning_task
            if hasattr(task, 'snapshots') and task.snapshots:
                print(f"\n  Training Metrics (Latest Snapshot):")
                latest = task.snapshots[-1]
                print(f"     Epoch:        {latest.epoch}")
                print(f"     Mean Loss:    {latest.mean_loss}")
        print("=" * 50)

    except Exception as e:
        print(f"[ERR] Failed to get status: {e}")
        sys.exit(1)


def run_finetuning():
    """Launch a supervised fine-tuning job."""
    print("=" * 50)
    print("STARTING FINE-TUNING JOB")
    print("=" * 50)

    # Validate prerequisites
    if not GEMINI_API_KEY:
        print("[ERR] GEMINI_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    if not os.path.exists(TRAINING_FILE):
        print(f"[ERR] Training file not found: {TRAINING_FILE}")
        print("   Run 'python generate_training_data.py' first.")
        sys.exit(1)

    # Validate data
    valid, count, errors = validate_jsonl(TRAINING_FILE)
    if not valid:
        print(f"[ERR] Training data invalid. Run 'python finetune.py --dry-run' for details.")
        sys.exit(1)

    if count < 20:
        print(f"[ERR] Only {count} training examples. Gemini requires at least 20.")
        print("   Collect more conversations and re-export training data.")
        sys.exit(1)

    print(f"  Base Model:    {BASE_MODEL}")
    print(f"  Training Data: {count} examples")
    print(f"  Epochs:        {EPOCHS}")
    print(f"  Display Name:  {DISPLAY_NAME}")
    print()

    # Configure Gemini
    genai.configure(api_key=GEMINI_API_KEY)

    # Load training data
    training_data = []
    with open(TRAINING_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                training_data.append(json.loads(line))

    # Load validation data (optional)
    validation_data = None
    if os.path.exists(VALIDATION_FILE):
        validation_data = []
        with open(VALIDATION_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    validation_data.append(json.loads(line))
        print(f"  Validation:    {len(validation_data)} examples")

    print("\n[...] Creating tuning job...")

    try:
        # Create the tuning operation
        operation = genai.create_tuned_model(
            source_model=BASE_MODEL,
            training_data=training_data,
            display_name=DISPLAY_NAME,
            epoch_count=EPOCHS,
        )

        print(f"[OK] Tuning job created!")
        print(f"   Tuned Model Name: {operation.metadata.tuned_model}")
        print(f"\n[...] Training in progress... (this can take minutes to hours)")
        print(f"   You can check status with: python finetune.py --status {operation.metadata.tuned_model}")

        # Poll for completion
        print("\n   Polling for completion (Ctrl+C to stop watching)...\n")
        try:
            for status in operation.wait_bar():
                time.sleep(30)
        except KeyboardInterrupt:
            print(f"\n\n[PAUSED] Stopped watching. Job continues in the background.")
            print(f"   Check status: python finetune.py --status {operation.metadata.tuned_model}")
            return

        # Job completed
        result = operation.result()
        print("\n" + "=" * 50)
        print("FINE-TUNING COMPLETE!")
        print("=" * 50)
        print(f"  Tuned Model Name: {result.name}")
        print(f"  State:            {result.state}")

        # Print how to use the tuned model
        print(f"\nTo use your tuned model, update server.py:")
        print(f"   model = genai.GenerativeModel('{result.name}')")
        print("=" * 50)

        # Save model name to a file for easy reference
        model_info_path = os.path.join(SCRIPT_DIR, "tuned_model_info.json")
        with open(model_info_path, "w", encoding="utf-8") as f:
            json.dump({
                "tuned_model_name": result.name,
                "base_model": BASE_MODEL,
                "display_name": DISPLAY_NAME,
                "epochs": EPOCHS,
                "training_examples": count,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
            }, f, indent=2)
        print(f"\n[OK] Model info saved to: {model_info_path}")

    except Exception as e:
        print(f"\n[ERR] Fine-tuning failed: {e}")
        print(f"\n   Common issues:")
        print(f"   - API key may not have tuning permissions")
        print(f"   - Base model '{BASE_MODEL}' may not support tuning")
        print(f"   - Training data format may be incorrect")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune a Gemini model for the AI Call Center Receptionist."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate training data without starting a tuning job"
    )
    parser.add_argument(
        "--status", type=str, metavar="JOB_NAME",
        help="Check status of an existing tuning job"
    )

    args = parser.parse_args()

    if args.status:
        check_status(args.status)
    elif args.dry_run:
        dry_run()
    else:
        run_finetuning()


if __name__ == "__main__":
    main()
