"""
Bulk Transcription and Training Data Ingestion Utility.
This script scans a folder for audio recordings, transcribes them using Google Cloud STT
with speaker diarization (Speaker 1 vs Speaker 2), and uploads them to the AI Call Center database.
"""

import os
import io
import json
import asyncio
from google.cloud import speech_v1p1beta1 as speech
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

# A-law to 16-bit PCM lookup table
ALAW_TO_PCM = []
for i in range(256):
    a = i ^ 0x55
    sign = a & 0x80
    exponent = (a >> 4) & 0x07
    mantissa = a & 0x0F
    sample = (mantissa << 4) + 8
    if exponent > 0:
        sample = (sample + 0x100) << (exponent - 1)
    ALAW_TO_PCM.append(-sample if sign else sample)

async def transcribe_file(file_path: str):
    print(f"Processing: {file_path}...", flush=True)
    
    with io.open(file_path, "rb") as audio_file:
        header = audio_file.read(44)
        data_in = audio_file.read()

    # Detect if it's stereo ALAW and convert to mono LINEAR16
    channels = int.from_bytes(header[22:24], 'little')
    format_tag = int.from_bytes(header[20:22], 'little')
    sample_rate = int.from_bytes(header[24:28], 'little')
    
    if format_tag == 6 and channels == 2:
        print(f"Detected stereo ALAW. Mixing to mono LINEAR16...", flush=True)
        # Mix both channels
        data_out = bytearray()
        for i in range(0, len(data_in) - 1, 2):
            s1 = ALAW_TO_PCM[data_in[i]]
            s2 = ALAW_TO_PCM[data_in[i+1]]
            mixed = (s1 + s2) // 2
            data_out.extend(mixed.to_bytes(2, 'little', signed=True))
        content = bytes(data_out)
        encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
        actual_sample_rate = sample_rate
    elif format_tag == 6 and channels == 1:
        print(f"Detected mono ALAW. Converting to LINEAR16...", flush=True)
        data_out = bytearray()
        for b in data_in:
            s = ALAW_TO_PCM[b]
            data_out.extend(s.to_bytes(2, 'little', signed=True))
        content = bytes(data_out)
        encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
        actual_sample_rate = sample_rate
    else:
        # Fallback to original content
        content = data_in
        encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16 # Default
        actual_sample_rate = 16000 # Default

    audio = speech.RecognitionAudio(content=content)
    
    # Configure for Greek with Speaker Diarization
    config = speech.RecognitionConfig(
        encoding=encoding,
        sample_rate_hertz=actual_sample_rate,
        language_code="el-GR",
        diarization_config=speech.SpeakerDiarizationConfig(
            enable_speaker_diarization=True,
            min_speaker_count=2,
            max_speaker_count=2,
        ),
    )

    print("Sending to Google Cloud STT...", flush=True)
    operation = client.long_running_recognize(config=config, audio=audio)
    response = operation.result(timeout=600)
    print(f"Received response with {len(response.results)} results.", flush=True)

    # Process results with speaker tags
    transcript_messages = []
    
    # The last result usually contains the full diarization info
    if response.results:
        result = response.results[-1]
        
        # In multi-result long_running_recognize, sometimes diarization is in alternatives of the last result
        if result.alternatives and result.alternatives[0].words:
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
        print(f"Error: Directory '{RECORDINGS_DIR}' not found. Please create it and add your audio files.", flush=True)
        return

    await db.init_db()
    
    files = [f for f in os.listdir(RECORDINGS_DIR) if f.lower().endswith(('.wav', '.mp3', '.m4a'))]
    print(f"Found {len(files)} recordings.", flush=True)

    for file_name in files:
        file_path = os.path.join(RECORDINGS_DIR, file_name)
        try:
            messages = await transcribe_file(file_path)
            
            if messages:
                session_id = f"training-import-{file_name}"
                conv_id = await db.create_conversation(session_id, language="el-GR-training")
                
                for msg in messages:
                    await db.add_message(conv_id, msg["role"], msg["content"])
                
                print(f"SUCCESS: Imported {len(messages)} turns from {file_name}", flush=True)
            else:
                print(f"WARNING: No transcript generated for {file_name}", flush=True)
                
        except Exception as e:
            print(f"ERROR processing {file_name}: {e}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
