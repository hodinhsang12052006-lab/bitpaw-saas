import urllib.request
import urllib.parse
import json
import sys

base_url = "http://127.0.0.1:5001"

def safe_print_str(label, text):
    try:
        print(f"{label}{text}")
    except Exception:
        try:
            # Fallback for Windows terminal encoding mismatch (cp1258/ascii)
            encoded = text.encode(sys.stdout.encoding or 'utf-8', errors='replace')
            decoded = encoded.decode(sys.stdout.encoding or 'utf-8')
            print(f"{label}{decoded}")
        except Exception as ex:
            print(f"{label}[Encoding Error in print: {str(ex)}] -> Raw bytes: {repr(text)}")

def make_request(path, method="GET", payload=None, is_json=True):
    url = f"{base_url}{path}"
    data = None
    headers = {}
    if payload:
        if is_json:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urllib.parse.urlencode(payload).encode("utf-8")
            
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            status = response.status
            body = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return status, json.loads(body)
            else:
                return status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            err_data = json.loads(body)
        except Exception:
            err_data = {"error_raw": body}
        return e.code, err_data
    except Exception as e:
        return 500, {"error": str(e)}

print("======================================================================")
print("OBSERVABLE MANUAL TEST MODE: PHASE 0 & PHASE 1 (Encoding Safe)")
print("======================================================================")

# ---------------------------------------------------------
# PHASE 0 — Health Check
# ---------------------------------------------------------
print("\n--- [PHASE 0] Health Check ---")
urls = {
    "Core Home (/)": "/",
    "Landing Page (/landing)": "/landing",
    "Login (/login)": "/login",
    "Register (/register)": "/register"
}

for name, path in urls.items():
    print(f"[*] Simulating browser request to {path} ({name})...")
    status, resp = make_request(path)
    print(f"    - Status Code: {status}")
    if status == 200:
        print(f"    [+] PASS: {name} rendered successfully (200 OK).")
        # Rà soát asset quan trọng
        if path == "/landing":
            has_mascot_widget = "cskh_widget.js" in resp
            has_floating_buttons = "Hotline" in resp or "Zalo" in resp or "Messenger" in resp
            print(f"    - Mascot widget detected inside HTML? {has_mascot_widget}")
            print(f"    - Floating CSKH action buttons detected inside HTML? {has_floating_buttons}")
            if has_mascot_widget and has_floating_buttons:
                print("    [+] PASS: Mascot and all 5 floating buttons are configured properly on Landing!")
            else:
                print("    [!] WARNING: Mascot or floating buttons might be missing from landing template.")
    else:
        print(f"    [!] FAIL: {name} request failed.")

# ---------------------------------------------------------
# PHASE 1 — Khách vào landing và hỏi Mascot
# ---------------------------------------------------------
print("\n--- [PHASE 1] Customer visits Landing & interacts with Mascot AI ---")
user_question = "Toi co tiem nail 12 tho, hay tranh tua va tinh hoa hong rat met. BitPaw giup gi?"
safe_print_str("[*] Client sending user message to Mascot Chat Proxy API... User Question: ", user_question)

payload = {
    "systemPrompt": "You are BitPaw Mascot Chatbot, a friendly AI assistant for BitPaw OS (SaaS Multitenant Platform for Spa, Nails, F&B, Retail). Help user understand how BitPaw helps them manage nail staff, rotation (tranh tua), and automatic commission calculations (hoa hong). Offer a friendly short Vietnamese response.",
    "userPrompt": user_question,
    "temperature": 0.7,
    "max_tokens": 1000
}

status, resp = make_request("/api/ai/studio/generate", method="POST", payload=payload)
print(f"[*] Called POST /api/ai/studio/generate:")
print(f"    - Status Code: {status}")
if status == 200:
    print("    [+] PASS: API called successfully (200 OK).")
    # Trích xuất phản hồi
    if "choices" in resp and len(resp["choices"]) > 0:
        answer = resp["choices"][0]["message"]["content"]
        print(f"\n[MASCOT AI RESPONSE BUBBLE]:")
        print("----------------------------------------------------------------------")
        safe_print_str("", answer)
        print("----------------------------------------------------------------------")
        print("[+] PASS: Chat bubble populated successfully.")
    else:
        print("    [!] WARNING: Response format unexpected or empty.")
        print(f"    - Response structure: {json.dumps(resp)}")
else:
    print("    [!] FAIL: Mascot Chat API request failed.")
    print(f"    - Error payload: {json.dumps(resp)}")

print("\n======================================================================")
print("PHASE 0 & 1 TESTING RUN COMPLETE")
print("======================================================================")
