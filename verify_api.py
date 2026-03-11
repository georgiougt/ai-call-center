import requests
import sys

def verify():
    url = "http://localhost:8001"
    
    print("--- Fetching repair requests ---")
    try:
        resp = requests.get(f"{url}/repair-requests")
        if resp.status_code != 200:
            print(f"FAILED: /repair-requests returned {resp.status_code}")
            return
        data = resp.json()
        reqs = data.get("repair_requests", [])
        if not reqs:
            print("No repair requests found to test with.")
            return
        
        target_req = reqs[0]
        req_id = target_req["id"]
        conv_id = target_req["conversation_id"]
        print(f"Testing with Request ID: {req_id}, Conv ID: {conv_id}")

        # 2. Test PATCH /api/repair-requests/{id}
        print(f"--- Testing Update Repair Request {req_id} ---")
        payload = {
            "name": target_req["name"] + " (Verified)",
            "serial": target_req["serial"],
            "issue": (target_req["issue"] or "") + " [Verified]"
        }
        patch_resp = requests.patch(f"{url}/api/repair-requests/{req_id}", json=payload)
        print(f"PATCH status: {patch_resp.status_code}")
        if patch_resp.status_code == 200:
            print("SUCCESS: Repair request updated.")

        # 3. Test GET /conversations/{id} and PATCH /api/messages/{id}
        print(f"--- Testing Message Correction for Conv {conv_id} ---")
        conv_resp = requests.get(f"{url}/conversations/{conv_id}")
        conv_data = conv_resp.json()
        messages = conv_data.get("messages", [])
        if messages:
            msg_id = messages[0]["id"]
            msg_payload = {"content": messages[0]["content"] + " (Fixed)"}
            msg_patch_resp = requests.patch(f"{url}/api/messages/{msg_id}", json=msg_payload)
            print(f"PATCH message status: {msg_patch_resp.status_code}")
            if msg_patch_resp.status_code == 200:
                print("SUCCESS: Message transcript corrected.")

        # 4. Test DELETE /api/repair-requests/{id}
        print(f"--- Testing Delete Repair Request {req_id} ---")
        del_req_resp = requests.delete(f"{url}/api/repair-requests/{req_id}")
        print(f"DELETE repair status: {del_req_resp.status_code}")
        if del_req_resp.status_code == 200:
            print("SUCCESS: Repair request deleted.")

        # 5. Test DELETE /api/conversations/{id}
        print(f"--- Testing Delete Conversation {conv_id} ---")
        del_conv_resp = requests.delete(f"{url}/api/conversations/{conv_id}")
        print(f"DELETE conv status: {del_conv_resp.status_code}")
        if del_conv_resp.status_code == 200:
            print("SUCCESS: Conversation deleted.")

        print("\nVerification script finished. If status codes were 200, the backend is working.")

    except Exception as e:
        print(f"ERROR connecting to server: {e}")

if __name__ == "__main__":
    verify()
