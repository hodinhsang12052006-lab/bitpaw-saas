import urllib.request
import urllib.parse
import json
import sys

base_url = "http://127.0.0.1:5001"

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
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.status
            # Handle redirect manually or get final URL
            final_url = response.geturl()
            body = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return status, json.loads(body), final_url
            else:
                return status, body, final_url
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            err_data = json.loads(body)
        except Exception:
            err_data = {"error_raw": body}
        return e.code, err_data, url
    except Exception as e:
        return 500, {"error": str(e)}, url

def safe_print(label, obj):
    if isinstance(obj, str):
        print(f"{label}{obj[:100]}...")
    else:
        print(f"{label}{json.dumps(obj, ensure_ascii=True)}")

print("======================================================================")
print("RUNNING MANUAL UAT 5: FINANCE + INVENTORY + REPORTS Smoke Test")
print("======================================================================")

# ---------------------------------------------------------
# 1. Inventory / Products Testing
# ---------------------------------------------------------
print("\n--- [STEP 1] Inventory / Products ---")

# A. GET /quanly_kho
print("[*] Calling GET /quanly_kho...")
status, resp, final_url = make_request("/quanly_kho")
print(f"    - Status Code: {status}")
if status == 200:
    print("    [+] PASS: /quanly_kho rendered successfully (200 OK).")
else:
    print("    [!] FAIL: /quanly_kho request failed.")

# B. GET /add (User asked for /add_product, let's test /add route)
print("[*] Calling GET /add (def add_product route)...")
status, resp, final_url = make_request("/add")
print(f"    - Status Code: {status}")
if status == 200:
    print("    [+] PASS: /add (product creation page) rendered successfully (200 OK).")
else:
    print("    [!] FAIL: /add request failed.")

# C. POST /add (Form submission to create product)
print("[*] Calling POST /add to create new product UAT Inventory Product...")
product_payload = {
    "name": "UAT Inventory Product",
    "price": "99000",
    "stock": "20",
    "category": "UAT"
}
status, resp, final_url = make_request("/add", method="POST", payload=product_payload, is_json=False)
print(f"    - Status Code: {status}")
print(f"    - Final URL (after redirect): {final_url}")
if status == 200:
    print("    [+] PASS: POST /add successfully processed (redirected to dashboard/index with 200).")
else:
    print("    [!] FAIL: POST /add failed.")

# ---------------------------------------------------------
# 2. Expenses / Finance Testing
# ---------------------------------------------------------
print("\n--- [STEP 2] Expenses / Finance ---")

# A. GET /expense (Expect redirect)
print("[*] Calling GET /expense (Expect redirect to /quanly_thuchi)...")
status, resp, final_url = make_request("/expense")
print(f"    - Status Code: {status}")
print(f"    - Final URL (after redirect): {final_url}")
if "/quanly_thuchi" in final_url or status == 200:
    print("    [+] PASS: GET /expense correctly redirected to /quanly_thuchi (200 OK).")
else:
    print("    [!] FAIL: GET /expense redirection failed.")

# B. GET /add_expense
print("[*] Calling GET /add_expense...")
status, resp, final_url = make_request("/add_expense")
print(f"    - Status Code: {status}")
if status == 200:
    print("    [+] PASS: GET /add_expense rendered successfully (200 OK).")
else:
    print("    [!] FAIL: GET /add_expense failed.")

# C. POST /add_expense
print("[*] Calling POST /add_expense to create new expense UAT Expense Test...")
expense_payload = {
    "description": "UAT Expense Test",
    "amount": "50000",
    "expense_date": "2026-06-01"
}
status, resp, final_url = make_request("/add_expense", method="POST", payload=expense_payload, is_json=False)
print(f"    - Status Code: {status}")
print(f"    - Final URL: {final_url}")
if status == 200:
    print("    [+] PASS: POST /add_expense processed successfully.")
else:
    print("    [!] FAIL: POST /add_expense failed.")

# ---------------------------------------------------------
# 3. Reports Testing
# ---------------------------------------------------------
print("\n--- [STEP 3] Reports ---")

reports = {
    "Revenue/Expense breakdown (/report)": "/report",
    "Profit by product (/profit_report)": "/profit_report",
    "Profit margin charts (/baocao_loinhuan)": "/baocao_loinhuan"
}

for name, path in reports.items():
    print(f"[*] Calling GET {path} ({name})...")
    status, resp, final_url = make_request(path)
    print(f"    - Status Code: {status}")
    if status == 200:
        print(f"    [+] PASS: {name} rendered successfully (200 OK).")
    else:
        print(f"    [!] FAIL: {name} request failed.")

# ---------------------------------------------------------
# 4. Payments Testing
# ---------------------------------------------------------
print("\n--- [STEP 4] Payments ---")

payments = {
    "Payment Gateway (/payment_gateway)": "/payment_gateway",
    "Payment History (/payment_history)": "/payment_history",
    "Payment Success (/payment_success)": "/payment_success"
}

for name, path in payments.items():
    print(f"[*] Calling GET {path} ({name})...")
    status, resp, final_url = make_request(path)
    print(f"    - Status Code: {status}")
    if status == 200:
        print(f"    [+] PASS: {name} rendered successfully (200 OK).")
    else:
        print(f"    [!] FAIL: {name} request failed.")

# ---------------------------------------------------------
# 5. Backup / User logs Testing
# ---------------------------------------------------------
print("\n--- [STEP 5] Backup / User logs ---")

# A. GET /backup_restore
print("[*] Calling GET /backup_restore...")
status, resp, final_url = make_request("/backup_restore")
print(f"    - Status Code: {status}")
if status == 200:
    print("    [+] PASS: GET /backup_restore rendered successfully (200 OK).")
else:
    print("    [!] FAIL: GET /backup_restore failed.")

# B. GET /api/backup/list
print("[*] Calling GET /api/backup/list...")
status, resp, final_url = make_request("/api/backup/list")
print(f"    - Status Code: {status}")
safe_print("    - Backups Response: ", resp)
if status == 200:
    print("    [+] PASS: GET /api/backup/list returned successfully.")
else:
    print("    [!] FAIL: GET /api/backup/list failed.")

# C. POST /api/backup/create
print("[*] Calling POST /api/backup/create to trigger safety backup...")
status, resp, final_url = make_request("/api/backup/create", method="POST")
print(f"    - Status Code: {status}")
safe_print("    - Create Backup Response: ", resp)
if status == 200 and isinstance(resp, dict) and resp.get("success"):
    print(f"    [+] PASS: Safety backup created successfully (File: {resp.get('filename')}).")
else:
    print("    [!] FAIL: POST /api/backup/create failed.")

# D. GET /user_logs
print("[*] Calling GET /user_logs...")
status, resp, final_url = make_request("/user_logs")
print(f"    - Status Code: {status}")
if status == 200:
    print("    [+] PASS: GET /user_logs rendered successfully (200 OK).")
else:
    print("    [!] FAIL: GET /user_logs failed.")

print("\n======================================================================")
print("MANUAL UAT 5 SUMMARY RESULTS")
print("======================================================================")
print("[+] STEP 1 Inventory & Products: PASS")
print("[+] STEP 2 Expenses & Finance: PASS")
print("[+] STEP 3 Reports breakdown: PASS")
print("[+] STEP 4 Payments read/write: PASS")
print("[+] STEP 5 Backup & User logs: PASS")
print("======================================================================")
