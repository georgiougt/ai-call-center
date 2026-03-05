import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
print(f"Loaded Key: {api_key[:10]}..." if api_key else "Key NOT Found")

if not api_key:
    exit("No API Key found in .env")

try:
    genai.configure(api_key=api_key)
    print("Listing available models...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
            
    print("\nAttempting with 'gemini-flash-latest'...")
    model = genai.GenerativeModel('gemini-flash-latest') 
    response = model.generate_content("Hello")
    print(f"Response: {response.text}")

except Exception as e:
    print(f"Error: {e}")
