import requests
import json
import time

def run_full_suite():
    base_url = "http://127.0.0.1:5001"
    session = requests.Session()
    
    print("==================================================")
    # 0. Đăng nhập bypass
    print("[*] Logging in with bypass test account...")
    login_payload = {"email": "admin@test.com", "password": "anypassword"}
    try:
        r_login = session.post(f"{base_url}/login", data=login_payload, timeout=5)
        print(f"    -> Login status: {r_login.status_code}")
    except Exception as e:
        print(f"    -> Connection failed: {e}. Ensure Flask is active on port 5001!")
        return

    # 1. CORE / SOLUTIONS ROUTE LIST
    core_urls = [
        '/', '/landing', '/login', '/register', '/setup', '/dashboard', '/portal',
        '/solutions/nail', '/solutions/fnb', '/solutions/spa', '/solutions/hotel',
        '/solutions/karaoke', '/solutions/office', '/solutions/retail', '/solutions/production',
        '/solutions/technical', '/solutions/hr'
    ]
    
    print("\n[1] TESTING CORE & SOLUTIONS ROUTES (GET)...")
    for url in core_urls:
        try:
            r = session.get(f"{base_url}{url}", timeout=5)
            print(f"    GET {url:30} | Status: {r.status_code}")
        except Exception as e:
            print(f"    GET {url:30} | EXCEPTION: {e}")

    # 2. POS / Dining QR
    pos_urls = [
        '/pos', '/sell', '/table_order', '/kitchen_display', '/qr_menu/test'
    ]
    print("\n[2] TESTING POS & DINING QR (GET)...")
    for url in pos_urls:
        try:
            r = session.get(f"{base_url}{url}", timeout=5)
            print(f"    GET {url:30} | Status: {r.status_code}")
        except Exception as e:
            print(f"    GET {url:30} | EXCEPTION: {e}")

    # Test POST /api/submit_qr_order
    print("\n[*] Testing POST /api/submit_qr_order...")
    order_payload = {
        "table_id": 1,
        "items": [
            {"product_id": 1, "qty": 2}
        ]
    }
    try:
        r = session.post(f"{base_url}/api/submit_qr_order", json=order_payload, timeout=5)
        print(f"    POST /api/submit_qr_order | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /api/submit_qr_order | EXCEPTION: {e}")

    # 3. AI / CRM
    ai_urls = [
        '/ai_bot', '/ai-studio', '/ad-assistant', '/campaign_builder',
        '/customer_nurturing', '/crm_automation'
    ]
    print("\n[3] TESTING AI & CRM PORTAL (GET)...")
    for url in ai_urls:
        try:
            r = session.get(f"{base_url}{url}", timeout=5)
            print(f"    GET {url:30} | Status: {r.status_code}")
        except Exception as e:
            print(f"    GET {url:30} | EXCEPTION: {e}")

    # Test POST /api/ai/studio/generate
    print("\n[*] Testing POST /api/ai/studio/generate...")
    gen_payload = {
        "systemPrompt": "Bypass validation.",
        "userPrompt": "Hello BitPaw!"
    }
    try:
        r = session.post(f"{base_url}/api/ai/studio/generate", json=gen_payload, timeout=5)
        print(f"    POST /api/ai/studio/generate | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /api/ai/studio/generate | EXCEPTION: {e}")

    # Test Ad-Assistant APIs
    print("\n[*] Testing POST /ad-assistant/api/suggest...")
    suggest_payload = {
        "product_name": "Combo Test",
        "product_desc": "Test description",
        "target_audience": {"age_min": 18, "age_max": 60, "interests": ["test"]},
        "budget": 1000000,
        "platform": "google"
    }
    try:
        r = session.post(f"{base_url}/ad-assistant/api/suggest", json=suggest_payload, timeout=5)
        print(f"    POST /ad-assistant/api/suggest | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /ad-assistant/api/suggest | EXCEPTION: {e}")

    # Test Ad-Assistant campaigns APIs
    print("\n[*] Testing POST /ad-assistant/api/create-campaign...")
    camp_payload = {
        "platform": "google",
        "name": "Test Campaign",
        "objective": "OUTCOME_TRAFFIC",
        "budget": 1000000
    }
    try:
        r = session.post(f"{base_url}/ad-assistant/api/create-campaign", json=camp_payload, timeout=5)
        print(f"    POST /ad-assistant/api/create-campaign | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /ad-assistant/api/create-campaign | EXCEPTION: {e}")

    print("\n[*] Testing GET /ad-assistant/api/campaigns...")
    try:
        r = session.get(f"{base_url}/ad-assistant/api/campaigns", timeout=5)
        print(f"    GET /ad-assistant/api/campaigns | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    GET /ad-assistant/api/campaigns | EXCEPTION: {e}")

    # 4. CSKH / Mascot
    print("\n[4] TESTING CSKH / MASCOT APIS...")
    cskh_payload = {
        "name": "Nguyễn Văn Test",
        "phone": "0987654321",
        "email": "test@gmail.com",
        "message": "Cần tư vấn giải pháp quản lý bán hàng."
    }
    try:
        r = session.post(f"{base_url}/api/cskh/request", json=cskh_payload, timeout=5)
        print(f"    POST /api/cskh/request | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /api/cskh/request | EXCEPTION: {e}")

    try:
        r = session.post(f"{base_url}/api/cskh/click", json={"channel": "zalo", "user_id": "test_user"}, timeout=5)
        print(f"    POST /api/cskh/click | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /api/cskh/click | EXCEPTION: {e}")

    try:
        r = session.post(f"{base_url}/api/cskh/feedback", json={"order_id": 1, "rating": 5, "comment": "Tuyệt vời!"}, timeout=5)
        print(f"    POST /api/cskh/feedback | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /api/cskh/feedback | EXCEPTION: {e}")

    try:
        r = session.post(f"{base_url}/api/cskh/lead-submit", json={"name": "Lead", "phone": "0123", "message": "hello"}, timeout=5)
        print(f"    POST /api/cskh/lead-submit | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /api/cskh/lead-submit | EXCEPTION: {e}")

    # 5. HRM / Payroll
    hrm_urls = [
        '/staff', '/nhanvien', '/bangluong', '/cauhinh_luong', '/chamcong',
        '/chamcong/nail', '/chamcong/spa', '/chamcong/fnb', '/chamcong/vanphong', '/diemdanh'
    ]
    print("\n[5] TESTING HRM & PAYROLL PAGES (GET)...")
    for url in hrm_urls:
        try:
            r = session.get(f"{base_url}{url}", timeout=5)
            print(f"    GET {url:30} | Status: {r.status_code}")
        except Exception as e:
            print(f"    GET {url:30} | EXCEPTION: {e}")

    print("\n[*] Testing POST /api/chamcong/checkin...")
    cc_payload = {"staff_id": 1, "latitude": 10.8231, "longitude": 106.6297}
    try:
        r = session.post(f"{base_url}/api/chamcong/checkin", json=cc_payload, timeout=5)
        print(f"    POST /api/chamcong/checkin | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /api/chamcong/checkin | EXCEPTION: {e}")

    print("\n[*] Testing POST /api/chamcong/checkout...")
    try:
        r = session.post(f"{base_url}/api/chamcong/checkout", json={"staff_id": 1}, timeout=5)
        print(f"    POST /api/chamcong/checkout | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /api/chamcong/checkout | EXCEPTION: {e}")

    print("\n[*] Testing GET /api/chamcong/status...")
    try:
        r = session.get(f"{base_url}/api/chamcong/status?staff_id=1", timeout=5)
        print(f"    GET /api/chamcong/status | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    GET /api/chamcong/status | EXCEPTION: {e}")

    print("\n[*] Testing POST /api/payroll/calculate...")
    try:
        r = session.post(f"{base_url}/api/payroll/calculate", json={"month_year": "05/2026"}, timeout=5)
        print(f"    POST /api/payroll/calculate | Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"    POST /api/payroll/calculate | EXCEPTION: {e}")

    # 6. Finance / Inventory
    finance_urls = [
        '/report', '/profit_report', '/baocao_loinhuan', '/expense',
        '/add_expense', '/quanly_kho', '/payment_gateway', '/payment_history'
    ]
    print("\n[6] TESTING FINANCE & INVENTORY (GET)...")
    for url in finance_urls:
        try:
            r = session.get(f"{base_url}{url}", timeout=5)
            print(f"    GET {url:30} | Status: {r.status_code}")
        except Exception as e:
            print(f"    GET {url:30} | EXCEPTION: {e}")

    # 7. Utility / Admin
    util_urls = [
        '/omnichannel', '/backup_restore', '/user_logs', '/super_admin',
        '/map_dashboard', '/ecommerce_sync'
    ]
    print("\n[7] TESTING UTILITIES & ADMIN PORTALS (GET)...")
    for url in util_urls:
        try:
            r = session.get(f"{base_url}{url}", timeout=5)
            print(f"    GET {url:30} | Status: {r.status_code}")
        except Exception as e:
            print(f"    GET {url:30} | EXCEPTION: {e}")
            
    print("==================================================")
    print("FULL TEST RUN COMPLETED!")

if __name__ == "__main__":
    run_full_suite()
