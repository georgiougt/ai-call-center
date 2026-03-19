"""
Bulk Transcription and Training Data Ingestion Utility.
This script scans a folder for audio recordings, transcribes them using Google Cloud STT
with speaker diarization (Speaker 1 vs Speaker 2), and uploads them to the AI Call Center database.
"""

import os
import io
import json
import asyncio
from google.cloud import speech
from google.oauth2 import service_account
from dotenv import load_dotenv
import database as db

load_dotenv()

# --- Configuration ---
RECORDINGS_DIR = "recordings_to_train" # Create this folder and put your audio files here
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

# Initialize Speech Client
if GOOGLE_CREDENTIALS_JSON:
    creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    client = speech.SpeechClient(credentials=credentials)
else:
    client = speech.SpeechClient() # Fallback to ADC

async def transcribe_file(file_path: str):
    print(f"Processing: {file_path}...")
    
    with io.open(file_path, "rb") as audio_file:
        content = audio_file.read()

    audio = speech.RecognitionAudio(content=content)
    
    # Configure for Greek with Speaker Diarization
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16, # Adjust if files are different (MP3/OGG)
        sample_rate_hertz=16000, # Common for phone recordings, adjust if needed
        language_code="el-GR",
        diarization_config=speech.SpeakerDiarizationConfig(
            enable_speaker_diarization=True,
            min_speaker_count=2,
            max_speaker_count=2,
        ),
    )

    print("Sending to Google Cloud STT...")
    operation = client.long_running_recognize(config=config, audio=audio)
    response = operation.result(timeout=600)

    # Process results with speaker tags
    transcript_messages = []
    
    # The last result usually contains the full diarization info
    if response.results:
        result = response.results[-1]
        words_info = result.alternatives[0].words

        current_speaker = None
        current_sentence = []

        for word_info in words_info:
            speaker_tag = word_info.speaker_tag
            
            if speaker_tag != current_speaker:
                if current_sentence:
                    role = "user" if current_speaker == 1 else "model" # Map speakers
                    transcript_messages.append({"role": role, "content": " ".join(current_sentence)})
                current_speaker = speaker_tag
                current_sentence = [word_info.word]
            else:
                current_sentence.append(word_info.word)

        # Catch the last one
        if current_sentence:
            role = "user" if current_speaker == 1 else "model"
            transcript_messages.append({"role": role, "content": " ".join(current_sentence)})

    return transcript_messages

async def main():
    if not os.path.exists(RECORDINGS_DIR):
        print(f"Error: Directory '{RECORDINGS_DIR}' not found. Please create it and add your audio files.")
        return

    await db.init_db()
    
    files = [f for f in os.listdir(RECORDINGS_DIR) if f.lower().endswith(('.wav', '.mp3', '.m4a'))]
    print(f"Found {len(files)} recordings.")

    for file_name in files:
        file_path = os.path.join(RECORDINGS_DIR, file_name)
        try:
            messages = await transcribe_file(file_path)
            
            if messages:
                session_id = f"training-import-{file_name}"
                conv_id = await db.create_conversation(session_id, language="el-GR-training")
                
                for msg in messages:
                    await db.add_message(conv_id, msg["role"], msg["content"])
                
                print(f"SUCCESS: Imported {len(messages)} turns from {file_name}")
            else:
                print(f"WARNING: No transcript generated for {file_name}")
                
        except Exception as e:
            print(f"ERROR processing {file_name}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
