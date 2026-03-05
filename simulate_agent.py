import os
import sys
import time
import io

import unicodedata

# Force UTF-8 output for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def normalize_text(text):
    """
    Removes accents and converts to lowercase.
    Example: "Καλησπέρα" -> "καλησπερα"
    """
    if not text:
        return ""
    # Normalize unicode characters to NFD (decomposed) form
    text = unicodedata.normalize('NFD', text)
    # Filter out non-spacing mark characters (accents)
    text = "".join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.lower()

# Mock Logic for "Fake LLM"
def mock_llm_response(history):
    """
    Simple keyword-based logic to simulate the AI Recepionist.
    """
    last_user_message_raw = history[-1]["content"] if history else ""
    last_user_message = normalize_text(last_user_message_raw)
    
    # 1. Greeting (if history is empty or just system prompt)
    if len(history) <= 1:
        return "Καλησπέρα σας, καλέσατε την Γιαννάκης Σκεμπετζής και Υἱοί. Πώς μπορώ να σας εξυπηρετήσω?"

    # 2. Language Detection & Switching
    is_english = any(word in last_user_message for word in ["hello", "hi", "english", "speak", "need", "want", "help"])
    
    # 3. Intent Classification (Keywords)
    # We check against normalized (accent-free) keywords
    
    # SPARE_PARTS
    # Keywords: part, filter, motor, replacement, ανταλλακτικ, φιλτρ, μοτερ
    if any(k in last_user_message for k in ["part", "filter", "motor", "replacement", "ανταλλακτικ", "φιλτρ", "μοτερ"]):
        if is_english:
            return "I will transfer you to the Spare Parts department. Please hold.\nTRANSFER: SPARE_PARTS"
        else:
            return "Μάλιστα, θα σας συνδέσω με το τμήμα ανταλλακτικών. Παρακαλώ περιμένετε.\nTRANSFER: SPARE_PARTS"

    # REPAIRS
    # Keywords: broken, fix, repair, stopped working, damage, βλαβ, χαλασ, επισκευ, φτιαξ, service, σερβις, τεχνικ, επιδιορθ, διορθ, συντηρησ
    if any(k in last_user_message for k in ["broken", "fix", "repair", "stopped working", "damage", "βλαβ", "χαλασ", "επισκευ", "φτιαξ", "service", "σερβις", "τεχνικ", "επιδιορθ", "διορθ", "συντηρησ"]):
        if is_english:
            return "I will transfer you to the Service department. Please hold.\nTRANSFER: REPAIRS"
        else:
            return "Μάλιστα, θα σας συνδέσω με το τεχνικό τμήμα. Παρακαλώ περιμένετε.\nTRANSFER: REPAIRS"

    # ACCOUNTING
    # Keywords: invoice, bill, pay, cost, money, τιμολογ, πληρωμ, λογιστηρ, λεφτα, charge, χρεωσ
    if any(k in last_user_message for k in ["invoice", "bill", "pay", "cost", "money", "τιμολογ", "πληρωμ", "λογιστηρ", "λεφτα", "charge", "χρεωσ"]):
        if is_english:
            return "I will transfer you to Accounting. Please hold.\nTRANSFER: ACCOUNTING"
        else:
            return "Μάλιστα, θα σας συνδέσω με το λογιστήριο. Παρακαλώ περιμένετε.\nTRANSFER: ACCOUNTING"

    # SALES
    # Keywords: buy, purchase, price, offer, new, αγορ, τιμη, προσφορ, νεο, πωλησ
    if any(k in last_user_message for k in ["buy", "purchase", "price", "offer", "new", "αγορ", "τιμη", "προσφορ", "νεο", "πωλησ"]):
        if is_english:
            return "I will transfer you to the Sales department. Please hold.\nTRANSFER: SALES"
        else:
            return "Μάλιστα, θα σας συνδέσω με τις πωλήσεις. Παρακαλώ περιμένετε.\nTRANSFER: SALES"

    # 4. Fallback / Clarification
    
    # Simple check to see if we already asked for clarification
    has_asked_clarification = False
    for msg in history:
        # Check if the AI has already asked the specific clarification question
        if msg["role"] == "assistant" and ("support" in msg["content"] or "λογιστήριο" in msg["content"]):
             has_asked_clarification = True

    if not has_asked_clarification:
        if is_english:
            return "Do you need spare parts, technical support, sales, or accounting?"
        else:
            return "Χρειάζεστε ανταλλακτικά, τεχνική υποστήριξη, πωλήσεις ή λογιστήριο;"
    
    # If we already clarified and still don't know
    if is_english:
         return "I will transfer you to the Secretary.\nTRANSFER: GENERAL_INFORMATION"
    else:
         return "Θα σας συνδέσω με τη γραμματεία.\nTRANSFER: GENERAL_INFORMATION"


def simulate_conversation():
    print("--- AI Call Center Simulation (MOCK MODE) ---")
    print("Type 'quit' or 'exit' to end the call.\n")

    history = [{"role": "system", "content": "SYSTEM PROMPT LOADED"}]

    # Initial Greeting
    ai_response = mock_llm_response(history)
    print(f"AI: {ai_response}")
    history.append({"role": "assistant", "content": ai_response})

    while True:
        user_input = input("\nYou (Caller): ")
        if user_input.lower() in ["quit", "exit"]:
            print("Call ended by user.")
            break

        history.append({"role": "user", "content": user_input})
        
        # Simulate think time
        time.sleep(0.5)

        ai_response = mock_llm_response(history)
        print(f"AI: {ai_response}")
        history.append({"role": "assistant", "content": ai_response})

        # Check for Transfer signal
        if "TRANSFER:" in ai_response:
            print("\n--- TRANSFER INITIATED ---")
            print(f"Routing confirmed. Ending simulation.")
            break

if __name__ == "__main__":
    simulate_conversation()
