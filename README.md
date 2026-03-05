# AI Call Center - Γιαννάκης Σκεμπετζής και Υιοί

AI Voice Receptionist for **Γιαννάκης Σκεμπετζής και Υιοί** — a construction machinery company. Routes callers to: Spare Parts, Repairs, Accounting, Sales, or General Information.

## Features

- **Language Detection**: Greek (default) & English
- **Intent Recognition**: Semantic analysis + keyword matching
- **Call Routing**: 5 departments with TRANSFER protocol
- **Repair Data Collection**: Step-by-step (Name → Serial → Issue)
- **Conversation Database**: SQLite logging of all interactions
- **Fine-Tuning Pipeline**: Export conversations → JSONL → Gemini fine-tuning

## Project Structure

| File | Purpose |
|------|---------|
| `server.py` | FastAPI backend with Gemini integration & DB logging |
| `voice_simulation.html` | Browser-based voice UI (Speech Recognition + TTS) |
| `system_prompt.md` | Core LLM system instructions |
| `simulate_agent.py` | CLI mock simulation (no API needed) |
| `database.py` | SQLite schema & async CRUD operations |
| `models.py` | Pydantic data models |
| `generate_training_data.py` | Export DB conversations to Gemini JSONL format |
| `finetune.py` | Automated Gemini fine-tuning script |
| `migrate_json_to_db.py` | One-time migration from legacy JSON |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your GEMINI_API_KEY

# 3. Run server
python -m uvicorn server:app --reload

# 4. Open voice simulation
# Open voice_simulation.html in Chrome
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat` | Send a message, receive AI response |
| `GET` | `/conversations` | List all logged conversations |
| `GET` | `/conversations/{id}` | Get full conversation with messages |
| `GET` | `/repair-requests` | List all repair requests |
| `GET` | `/stats` | Database statistics |

## Fine-Tuning Workflow

```bash
# 1. Collect conversations by using the call center
# 2. Export training data
python generate_training_data.py

# 3. Validate before tuning
python finetune.py --dry-run

# 4. Launch fine-tuning job
python finetune.py

# 5. Check job status
python finetune.py --status tunedModels/your-model-name
```

### Training Data Options

```bash
python generate_training_data.py --min-turns 4        # Longer conversations only
python generate_training_data.py --completed-only      # Only successful transfers
python generate_training_data.py --split 0.85          # Custom train/val split
```
