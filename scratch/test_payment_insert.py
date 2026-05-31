import sys
import os
import uuid
import datetime

# Thêm thư mục gốc vào path để import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_client import supabase, SUPABASE_URL, SUPABASE_STATUS

print(f"[*] Testing connection with Supabase URL: {SUPABASE_URL}")
print(f"[*] Connection status: {SUPABASE_STATUS}")

if SUPABASE_STATUS != "CONNECTED" or not supabase:
    print("[!] Error: Supabase client is not connected!")
    sys.exit(1)

# Tạo một transaction ID ngẫu nhiên
test_txn_id = f"TXN_UAT_{uuid.uuid4().hex[:10].upper()}"
test_amount = 160000.0
test_currency = "VND"
test_method = "STRIPE (Credit Card)"
test_customer_name = "Nguyen Van A"
test_customer_email = "customer_uat@example.com"
test_status = "completed"  # Hoặc 'success' tùy thuộc vào CHECK constraint (CHECK constraint hiện tại là: pending, completed, failed, refunded)

print(f"[*] Attempting to insert test record into 'payment_transactions'...")
print(f"    - transaction_id: {test_txn_id}")
print(f"    - customer_name: {test_customer_name}")
print(f"    - customer_email: {test_customer_email}")
print(f"    - amount: {test_amount}")
print(f"    - currency: {test_currency}")
print(f"    - method: {test_method}")
print(f"    - status: {test_status}")

try:
    # Hãy thử insert đầy đủ tất cả các cột
    res = supabase.table('payment_transactions').insert({
        "transaction_id": test_txn_id,
        "customer_name": test_customer_name,
        "customer_email": test_customer_email,
        "amount": test_amount,
        "currency": test_currency,
        "method": test_method,
        "status": test_status,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }).execute()
    
    print("[+] INSERT SUCCESS!")
    print(f"[+] Server returned data: {res.data}")
    
    # Thử SELECT lại record vừa chèn để xác minh hoàn toàn
    print(f"[*] Double-checking by querying transaction_id: {test_txn_id}...")
    verify_res = supabase.table('payment_transactions').select('*').eq('transaction_id', test_txn_id).execute()
    if verify_res.data:
        print("[+] VERIFICATION SUCCESS! Found record:")
        print(verify_res.data[0])
    else:
        print("[!] Warning: Record inserted but not found in verify query!")
        
except Exception as e:
    print("[!] EXCEPTION ENCOUNTERED during insert/select:")
    print(str(e))
    sys.exit(1)
