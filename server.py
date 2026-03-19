import google.generativeai as genai
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from contextlib import asynccontextmanager
import os
import uuid
import json
import asyncio
import queue
import threading
from dotenv import load_dotenv
from datetime import datetime
import logging

# Set up logging for Render debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("server")
logger.info("Initializing server...")

from google.cloud import speech
from google.oauth2 import service_account

import database as db
from models import (
    MessageCreate, ChatRequest, ManualConversation, 
    RepairRequestCreate, RepairRequestUpdate, MessageUpdate
)

logger.info("Environment and models loaded.")

load_dotenv()

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY # Explicit env overwrite
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-flash-latest')
else:
    print("WARNING: GEMINI_API_KEY not found in .env. Using mock fallback.")
    model = None

# Configure Google Speech-to-Text
try:
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        # Load credentials from JSON string (Ideal for Render/Cloud)
        creds_info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(creds_info)
        speech_client = speech.SpeechClient(credentials=credentials)
        print("[OK] Google Speech-to-Text initialized via Environment Variable.")
    else:
        # Fallback to local file path
        speech_client = speech.SpeechClient()
        print("[OK] Google Speech-to-Text initialized via default credentials (file).")
except Exception as e:
    print(f"WARNING: Google Speech-to-Text client failed to initialize: {e}")
    speech_client = None


# --- App Lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup, close pool on shutdown."""
    logger.info("Lifespan starting: Initializing DB...")
    try:
        await asyncio.wait_for(db.init_db(), timeout=20.0) # 20s timeout
        logger.info("Lifespan: DB initialized.")
    except Exception as e:
        logger.error(f"Lifespan: DB initialization FAILED: {e}")
        # We don't raise here so the server can at least start and serve a 500 error later
    yield
    logger.info("Lifespan: Closing DB pool...")
    await db.close_pool()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": str(asyncio.get_event_loop().time())}

@app.get("/config")
async def get_config():
    """Returns safe configuration variables to the frontend."""
    return {
        "elevenlabs_api_key": os.getenv("ELEVENLABS_API_KEY", "")
    }



# --- Chat Models (Inherited from models.py) ---
# Removed local definitions to avoid NameError and inconsistency


# SYSTEM PROMPT
import os
SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "system_prompt.md")

def get_system_instructions():
    try:
        with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "You are a helpful AI assistant."
def mock_llm_logic(user_input, history: List[MessageCreate]):
    if not history:
        return "Καλησπέρα σας, καλέσατε την Γιαννάκης Σκεμπετζής και Υιοί. Πώς μπορώ να σας εξυπηρετήσω;"
    normalized_text = user_input.lower()
    if "part" in normalized_text or "ανταλλακ" in normalized_text:
        return "Μάλιστα, θα σας συνδέσω με το τμήμα ανταλλακτικών. TRANSFER: SPARE_PARTS"
    return "Συγγνώμη, δεν κατάλαβα. Θέλετε ανταλλακτικά, σέρβις ή λογιστήριο;"


# --- Helper: Extract Transfer & Data ---

def parse_response(response_text: str):
    """Parse AI response for TRANSFER label and DATA payload."""
    department = None
    repair_data = None

    if "TRANSFER:" in response_text:
        parts = response_text.split("TRANSFER:")
        transfer_part = parts[1].strip()

        if "|" in transfer_part:
            department = transfer_part.split("|")[0].strip()
        else:
            department = transfer_part.strip().split()[0] if transfer_part.strip() else None

    if "DATA:" in response_text:
        try:
            import ast
            data_part = response_text.split("DATA:")[1].strip()
            # Remove any trailing text after the dict
            # Find the closing brace
            brace_count = 0
            end_idx = 0
            for i, char in enumerate(data_part):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break
            data_part = data_part[:end_idx]
            repair_data = ast.literal_eval(data_part)
        except Exception as e:
            print(f"⚠️ Failed to parse DATA: {e}")

    return department, repair_data


# --- Chat Endpoint (Streaming JS-compatible SSE) ---

async def get_gemini_response(message: str, history: List[MessageCreate], session_id: str):
    """Core logic to get a response from Gemini and log/parse it."""
    # Get or create conversation in DB
    conversation_id = await db.get_or_create_conversation(session_id)

    # Log the user message
    await db.add_message(conversation_id, "user", message)

    if not model:
        response_text = mock_llm_logic(message, history)
        await db.add_message(conversation_id, "model", response_text)
        return response_text, None, None

    # Safety Settings
    safety_settings = {
        "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
        "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
        "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
    }

    # Keep LLM context short to optimize latency (keep last 4 turns)
    chat_history = []
    recent_history = history[-4:] if len(history) > 4 else history
    for msg in recent_history:
        role = "user" if msg.role == "user" else "model"
        chat_history.append({"role": role, "parts": [msg.content]})

    sys_instr = get_system_instructions()
    full_prompt = sys_instr + "\n\nConversation History:\n"
    for msg in chat_history:
        full_prompt += f"{msg['role'].upper()}: {msg['parts'][0]}\n"

    full_prompt += f"USER: {message}\nAI:"

    full_response_text = ""
    try:
        # Call Gemini (non-streaming for this utility, or we can use the stream logic if needed)
        # For simplicity in Vapi/Backend reuse, we'll provide a way to get the full text
        response = await model.generate_content_async(
            full_prompt, 
            safety_settings=safety_settings
        )
        full_response_text = response.text if response.text else "Σφάλμα. Δεν μπορώ να απαντήσω."
    except Exception as e:
        logger.error(f"Gemini API Error: {e}")
        full_response_text = f"System Error: {str(e)}"

    # AFTER GENERATION: Log to Database and Parse Routing
    try:
        # 1. Log AI Response
        await db.add_message(conversation_id, "model", full_response_text.strip())

        # 2. Parse Routing & Repair Data
        department, repair_data = parse_response(full_response_text)

        if department:
            await db.update_conversation_routing(conversation_id, department)

        if repair_data:
            await db.save_repair_request(
                name=repair_data.get("name", ""),
                serial=repair_data.get("serial", ""),
                issue=repair_data.get("issue"),
                conversation_id=conversation_id
            )
            print(f"[OK] Saved Repair Request to DB: {repair_data}")

        return full_response_text, department, repair_data

    except Exception as db_err:
        print(f"[WARN] Failed post-processing routing/DB save: {db_err}")
        return full_response_text, None, None

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # Generate or use provided session ID
    session_id = request.session_id or str(uuid.uuid4())

    # Get or create conversation in DB
    conversation_id = await db.get_or_create_conversation(session_id)

    # Log the user message
    await db.add_message(conversation_id, "user", request.message)

    if not model:
        response_text = mock_llm_logic(request.message, request.history)
        await db.add_message(conversation_id, "model", response_text)
        
        async def mock_generator():
            yield f"data: {json.dumps({'chunk': response_text, 'session_id': session_id})}\n\n"
            yield "data: [DONE]\n\n"
            
        return StreamingResponse(mock_generator(), media_type="text/event-stream")

    # Safety Settings
    safety_settings = {
        "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
        "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
        "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
    }

    # Keep LLM context short to optimize latency (keep last 4 turns)
    chat_history = []
    recent_history = request.history[-4:] if len(request.history) > 4 else request.history
    for msg in recent_history:
        role = "user" if msg.role == "user" else "model"
        chat_history.append({"role": role, "parts": [msg.content]})

    sys_instr = get_system_instructions()
    full_prompt = sys_instr + "\n\nConversation History:\n"
    for msg in chat_history:
        full_prompt += f"{msg['role'].upper()}: {msg['parts'][0]}\n"

    full_prompt += f"USER: {request.message}\nAI:"

    async def generate_and_log():
        full_response_text = ""
        try:
            # Call Gemini natively ASYNC with stream=True
            response_stream = await model.generate_content_async(
                full_prompt, 
                safety_settings=safety_settings,
                stream=True
            )
            
            chunk_count = 0
            async for chunk in response_stream:
                chunk_count += 1
                if chunk.text:
                    full_response_text += chunk.text
                    # Yield SSE formatted json string
                    payload = json.dumps({"chunk": chunk.text, "session_id": session_id})
                    yield f"data: {payload}\n\n"
                    
            if chunk_count == 0 or not full_response_text:
                print(f"[{session_id}] Gemini returned an EMPTY stream (safety filter?)")
                err = "Σφάλμα. Δεν μπορώ να απαντήσω (Κενή απάντηση)."
                yield f"data: {json.dumps({'chunk': err, 'session_id': session_id})}\n\n"
                full_response_text = err

            # Signal end of stream
            yield "data: [DONE]\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Gemini API Error: {e}")
            error_msg = f"System Error: {str(e)}"
            full_response_text = error_msg
            yield f"data: {json.dumps({'chunk': error_msg, 'session_id': session_id})}\n\n"
            yield "data: [DONE]\n\n"

        # AFTER STREAMING: Log to Database and Parse Routing
        try:
            # 1. Log AI Response
            await db.add_message(conversation_id, "model", full_response_text.strip())

            # 2. Parse Routing & Repair Data
            department, repair_data = parse_response(full_response_text)

            if department:
                await db.update_conversation_routing(conversation_id, department)

            if repair_data:
                await db.save_repair_request(
                    name=repair_data.get("name", ""),
                    serial=repair_data.get("serial", ""),
                    issue=repair_data.get("issue"),
                    conversation_id=conversation_id
                )
                print(f"[OK] Saved Repair Request to DB: {repair_data}")

        except Exception as db_err:
            print(f"[WARN] Failed post-processing routing/DB save: {db_err}")

    return StreamingResponse(generate_and_log(), media_type="text/event-stream")


# --- Vapi / OpenAI-Compatible Endpoints ---

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible endpoint for Vapi's Custom LLM provider. Supports Streaming."""
    data = await request.json()
    messages = data.get("messages", [])
    stream_requested = data.get("stream", False)
    
    if not messages:
        return {"choices": [{"message": {"role": "assistant", "content": "No message provided."}}]}
    
    user_message = messages[-1].get("content", "")
    # Note: Vapi sends full history. We map roles to Gemini equivalents.
    history = []
    for m in messages[:-1]:
        role = "user" if m.get("role") == "user" else "model"
        history.append(MessageCreate(role=role, content=m.get("content", "")))
    
    vapi_session_id = data.get("user", f"vapi-{uuid.uuid4()}")
    
    if not stream_requested:
        # Non-streaming implementation
        response_text, department, repair_data = await get_gemini_response(user_message, history, vapi_session_id)
        return {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(datetime.now().timestamp()),
            "model": "gemini-flash-latest",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}]
        }

    # Streaming implementation for Vapi/OpenAI
    async def openai_stream_generator():
        # Get or create conversation in DB for tracking
        conversation_id = await db.get_or_create_conversation(vapi_session_id)
        await db.add_message(conversation_id, "user", user_message)

        full_response_text = ""
        cmpl_id = f"chatcmpl-{uuid.uuid4()}"
        created_time = int(datetime.now().timestamp())

        # Construct Gemini Prompt (Short context)
        sys_instr = get_system_instructions()
        full_prompt = sys_instr + "\n\nConversation History:\n"
        for msg in history[-4:]:
            full_prompt += f"{msg.role.upper()}: {msg.content}\n"
        full_prompt += f"USER: {user_message}\nAI:"

        try:
            response_stream = await model.generate_content_async(full_prompt, stream=True)
            async for chunk in response_stream:
                if chunk.text:
                    full_response_text += chunk.text
                    chunk_payload = {
                        "id": cmpl_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": "gemini-flash-latest",
                        "choices": [{"index": 0, "delta": {"content": chunk.text}, "finish_reason": None}]
                    }
                    yield f"data: {json.dumps(chunk_payload)}\n\n"
            
            # Final chunk
            yield f"data: {json.dumps({'id': cmpl_id, 'object': 'chat.completion.chunk', 'created': created_time, 'model': 'gemini-flash-latest', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
            yield "data: [DONE]\n\n"

            # Post-processing (Logging & Routing)
            await db.add_message(conversation_id, "model", full_response_text.strip())
            department, repair_data = parse_response(full_response_text)
            if department: await db.update_conversation_routing(conversation_id, department)
            if repair_data:
                await db.save_repair_request(
                    name=repair_data.get("name", ""),
                    serial=repair_data.get("serial", ""),
                    issue=repair_data.get("issue"),
                    conversation_id=conversation_id
                )

        except Exception as e:
            logger.error(f"Vapi Stream Error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(openai_stream_generator(), media_type="text/event-stream")

@app.post("/vapi")
async def vapi_webhook(request: Request):
    """
    Unified webhook for Vapi.ai.
    Handles 'assistant-request' to configure the agent and other hooks.
    """
    try:
        data = await request.json()
        message = data.get("message", {})
        msg_type = message.get("type")
        
        logger.info(f"Vapi Webhook: Received {msg_type}")

        if msg_type == "assistant-request":
            # When Vapi requires the assistant configuration
            client_base_url = str(request.base_url).rstrip("/")
            # Use Render URL if available, otherwise fallback to request base_url
            host = request.headers.get("host", client_base_url)
            proto = request.headers.get("x-forwarded-proto", "https")
            base_url = f"{proto}://{host}"
            
            logger.info(f"Vapi Webhook: Providing configuration with base_url: {base_url}")
            
            return {
                "assistant": {
                    "name": "Giannakis Call Center AI",
                    "firstMessage": "Καλησπέρα σας, καλέσατε την Γιαννάκης Σκεμπετζής και Υιοί. Πώς μπορώ να σας εξυπηρετήσω;",
                    "model": {
                        "provider": "custom-llm",
                        "url": f"{base_url}/v1", 
                        "model": "gemini-flash-latest",
                        "systemPrompt": get_system_instructions(),
                        "temperature": 0.7
                    },
                    "voice": {
                        "provider": "elevenlabs",
                        "voiceId": os.getenv("ELEVENLABS_VOICE_ID", "JrrE7QTGDmQKQuUnqk7H"),
                        "model": "eleven_multilingual_v2",
                        "stability": 0.5,
                        "similarityBoost": 0.75
                    },
                    "transcriber": {
                        "provider": "deepgram",
                        "model": "nova-2",
                        "language": "el",
                        "smartFormat": True
                    }
                }
            }
        
        if msg_type == "end-of-call-report":
            # Save the full transcript and metadata to the DB
            call_data = message.get("call", {})
            vapi_id = call_data.get("id", "unknown")
            transcript = call_data.get("transcript", "")
            summary = call_data.get("summary", "")
            
            logger.info(f"Vapi Webhook: Processing end-of-call for {vapi_id}")
            
            if transcript:
                # Create a conversation entry for this Vapi call if it doesn't exist
                conversation_id = await db.get_or_create_conversation(f"vapi-call-{vapi_id}", language="el-VAPI")
                
                # If the DB doesn't have messages yet (e.g. if /v1 wasn't used), save it as one bulk message or parse it
                # For simplicity and robustness, we'll save the summary and a marker
                await db.add_message(conversation_id, "model", f"VOICE CALL SUMMARY: {summary}\n\nFULL TRANSCRIPT:\n{transcript}")
            
            return {"status": "ok", "processed": "end-of-call"}

        # Handle other Vapi messages (assistant.started, status-update, etc.)
        return {"status": "ok", "received": msg_type}
        
    except Exception as e:
        logger.error(f"Vapi Webhook Error: {e}")
        return {"error": str(e)}, 500





# --- Google Cloud Speech-to-Text Streaming ---

def generate_stt_requests(audio_queue: queue.Queue):
    while True:
        chunk = audio_queue.get()
        if chunk is None:
            break
        yield speech.StreamingRecognizeRequest(audio_content=chunk)

def recognize_stream(audio_queue: queue.Queue, websocket: WebSocket, language_code: str, loop: asyncio.AbstractEventLoop):
    if not speech_client:
        asyncio.run_coroutine_threadsafe(websocket.send_json({"error": "Google STT not configured (Service Account JSON missing?)"}), loop)
        return
        
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
        sample_rate_hertz=48000,
        language_code=language_code,
        enable_automatic_punctuation=True
    )
    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=True
    )

    requests = generate_stt_requests(audio_queue)
    try:
        responses = speech_client.streaming_recognize(streaming_config, requests)
        
        for response in responses:
            if not response.results:
                continue

            result = response.results[0]
            if not result.alternatives:
                continue
                
            transcript = result.alternatives[0].transcript
            is_final = result.is_final
            
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({
                    "transcript": transcript,
                    "is_final": is_final
                }), 
                loop
            )
            
    except Exception as e:
        print(f"Google STT Stream Error: {e}")
        try:
            asyncio.run_coroutine_threadsafe(websocket.send_json({"error": f"STT Stream Error: {str(e)}"}), loop)
        except Exception:
            pass

@app.websocket("/listen")
async def websocket_listen(websocket: WebSocket, language: str = "el-GR"):
    await websocket.accept()
    audio_queue = queue.Queue()
    loop = asyncio.get_running_loop()
    
    stt_thread = threading.Thread(target=recognize_stream, args=(audio_queue, websocket, language, loop))
    stt_thread.start()
    
    try:
        while True:
            data = await websocket.receive_bytes()
            audio_queue.put(data)
    except WebSocketDisconnect:
        print("WebSocket STT client disconnected")
    except Exception as e:
        print(f"WebSocket STT exception: {e}")
    finally:
        audio_queue.put(None)
        stt_thread.join(timeout=2)


# --- API: Retrieve Conversations ---

@app.get("/conversations")
async def list_conversations(limit: int = 50, offset: int = 0):
    """List all conversations with message counts."""
    conversations = await db.get_all_conversations(limit=limit, offset=offset)
    total = await db.get_conversation_count()
    return {"conversations": conversations, "total": total}


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: int):
    """Get a full conversation with messages."""
    conv = await db.get_conversation_with_messages(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@app.get("/repair-requests")
async def list_repair_requests():
    """List all repair requests."""
    requests = await db.get_all_repair_requests()
    return {"repair_requests": requests}


@app.get("/stats")
async def get_stats():
    """Get database statistics."""
    return {
        "total_conversations": await db.get_conversation_count(),
        "total_messages": await db.get_message_count(),
        "total_repair_requests": len(await db.get_all_repair_requests()),
    }


# --- Manual Training Data API ---

@app.get("/")
async def get_voice_ui():
    """Serve the main voice receptionist UI."""
    return FileResponse(os.path.join(os.path.dirname(__file__), "voice_simulation.html"))

@app.get("/training")
async def get_training_ui():
    """Serve the manual training data entry UI."""
    return FileResponse(os.path.join(os.path.dirname(__file__), "training_entry.html"))

@app.post("/api/training-conversation")
async def save_training_conversation(data: ManualConversation):
    """Save a manually entered conversation to the database."""
    # Generate a unique session ID for this manual entry
    session_id = f"manual-training-{uuid.uuid4()}"
    
    # Mark it with a special language flag to identify manual cypriot data
    conversation_id = await db.create_conversation(session_id, language="el-CY-manual")
    
    if data.department:
        await db.update_conversation_routing(conversation_id, data.department)
        
    for msg in data.messages:
        await db.add_message(conversation_id, msg.role, msg.content)
        
    return {"status": "success", "conversation_id": conversation_id}


# --- Database Correction API (for Correction UI) ---

@app.get("/admin")
async def get_admin_ui():
    """Serve the admin database correction UI."""
    return FileResponse(os.path.join(os.path.dirname(__file__), "admin.html"))

@app.patch("/api/repair-requests/{request_id}")
async def update_repair_request_endpoint(request_id: int, data: RepairRequestUpdate):
    """Update a repair request."""
    await db.update_repair_request(request_id, data.name, data.serial, data.issue)
    return {"status": "success"}

@app.get("/api/export-training-data")
async def export_training_data():
    """Export all conversations in Gemini's JSONL fine-tuning format."""
    conversations = await db.get_complete_conversations(min_turns=2)
    
    export_lines = []
    for conv in conversations:
        # Format for Gemini 1.5 Fine-tuning
        # {"contents": [{"role": "user", "parts": [{"text": "..."}]}, ...]}
        contents = []
        for msg in conv.get("messages", []):
            role_map = {"user": "user", "model": "model"}
            contents.append({
                "role": role_map.get(msg["role"], "user"),
                "parts": [{"text": msg["content"]}]
            })
        
        if contents:
            export_lines.append(json.dumps({"contents": contents}, ensure_ascii=False))
            
    content = "\n".join(export_lines)
    
    # Return as a downloadable file
    filename = f"training_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    temp_path = os.path.join(os.path.dirname(__file__), filename)
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    return FileResponse(
        temp_path, 
        media_type="application/x-jsonlines", 
        filename=filename,
        background=asyncio.create_task(asyncio.sleep(10)).add_done_callback(lambda _: os.remove(temp_path) if os.path.exists(temp_path) else None)
    )

@app.patch("/api/messages/{message_id}")
async def update_message_endpoint(message_id: int, data: MessageUpdate):
    """Update a message transcript."""
    await db.update_message(message_id, data.content)
    return {"status": "success"}

@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: int):
    """Delete a conversation and all its messages."""
    await db.delete_conversation(conversation_id)
    return {"status": "success"}

@app.post("/api/repair-requests")
async def create_manual_repair_request_endpoint(data: RepairRequestCreate):
    """Manually create a repair request for a conversation."""
    request_id = await db.save_repair_request(
        name=data.name,
        serial=data.serial,
        issue=data.issue,
        conversation_id=data.conversation_id
    )
    return {"status": "success", "id": request_id}

@app.delete("/api/repair-requests/{request_id}")
async def delete_repair_request_endpoint(request_id: int):
    """Delete a specific repair request entry."""
    await db.delete_repair_request(request_id)
    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
