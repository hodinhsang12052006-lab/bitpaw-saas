import requests
import json
import time

base_url = "http://127.0.0.1:5001"
session = requests.Session()

# 1. Login with a test.com email to trigger bypass
print("=== LOGGING IN WITH BYPASS EMAIL ===")
login_data = {
    "email": "admin@test.com",
    "password": "anypassword"
}
try:
    res = session.post(f"{base_url}/login", data=login_data, timeout=5)
    print(f"Login request status: {res.status_code}")
    print(f"Cookies after login: {session.cookies.get_dict()}")
except Exception as e:
    print(f"Failed to connect to local server: {e}")
    print("Please make sure Flask server is running on port 5001!")
    exit(1)

urls = [
    # Core
    '/',
    '/landing',
    '/login',
    '/register',
    '/dashboard',
    '/portal',
    '/setup',
    
    # Landing ngành
    '/solutions/nail',
    '/solutions/fnb',
    '/solutions/spa',
    '/solutions/hotel',
    '/solutions/karaoke',
    '/solutions/office',
    '/solutions/retail',
    '/solutions/production',
    '/solutions/technical',
    
    # AI
    '/ai_bot',
    '/ai-studio',
    '/ad_assistant',
    '/campaign_builder',
    '/customer_nurturing',
    '/crm_automation',
    '/chat',
    '/app_chat',
    
    # POS / QR
    '/pos',
    '/sell',
    '/qr_menu',
    '/table_order',
    '/kitchen_display',
    
    # CRM / Report
    '/crm',
    '/report',
    '/profit_report',
    '/payment_gateway',
    '/payment_history',
    
    # HRM
    '/staff_management',
    '/diemdanh',
    '/map_dashboard',
    '/chamcong',
    '/chamcong/nail',
    '/chamcong/spa',
    '/chamcong/fnb',
    '/chamcong/khachsan',
    '/chamcong/kythuat',
    '/chamcong/congnhan',
    '/chamcong/vanphong'
]

print("\n=== STARTING FLASK ENDPOINT HTTP SCAN ===")
results = []

for url in urls:
    full_url = f"{base_url}{url}"
    try:
        t0 = time.time()
        res = session.get(full_url, timeout=5, allow_redirects=True)
        t_elapsed = time.time() - t0
        
        status = res.status_code
        # Check if we were redirected to login (which means authenticated session failed or is missing)
        was_login_redirect = False
        if res.history:
            # If any of the redirects went to /login, and final URL has active_tab=login or contains login
            final_url = res.url
            if "/login" in final_url or "active_tab=login" in final_url:
                was_login_redirect = True
                
        error_snippet = ""
        if status >= 400:
            error_snippet = res.text[:800]
            
        results.append({
            "url": url,
            "status_code": status,
            "time_taken_sec": round(t_elapsed, 3),
            "redirected_to_login": was_login_redirect,
            "history_urls": [r.url for r in res.history],
            "final_url": res.url,
            "content_length": len(res.content),
            "error_snippet": error_snippet
        })
        print(f"GET {url} | Status: {status} | Login Redirect: {was_login_redirect} | Time: {round(t_elapsed, 2)}s")
    except Exception as e:
        results.append({
            "url": url,
            "status_code": "EXCEPTION",
            "error_snippet": str(e)
        })
        print(f"GET {url} | EXCEPTION: {e}")

# Test AI Studio generate API
print("\n=== TESTING AI GENERATE API ===")
payload = {
    "systemPrompt": "Bạn là Mascot AI BitPaw tư vấn SaaS cho SME Việt Nam.",
    "userPrompt": "Tiệm nail của tôi có 12 thợ, hay tranh tua và tính hoa hồng rất mệt. BitPaw giúp gì?"
}

try:
    t0 = time.time()
    res_api = session.post(f"{base_url}/api/ai/studio/generate", 
                           json=payload, 
                           timeout=10)
    t_elapsed = time.time() - t0
    api_status = res_api.status_code
    api_data = None
    try:
        api_data = res_api.json()
    except Exception:
        api_data = res_api.text[:800]
        
    print(f"POST /api/ai/studio/generate | Status: {api_status} | Time: {round(t_elapsed, 2)}s")
except Exception as e:
    api_status = "EXCEPTION"
    api_data = str(e)
    print(f"POST /api/ai/studio/generate | EXCEPTION: {e}")

# Save report
report_data = {
    "endpoints": results,
    "ai_api_test": {
        "status": api_status,
        "response": api_data
    }
}

with open("scratch/test_report.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, indent=4, ensure_ascii=False)

print(f"\nReport written to: scratch/test_report.json")
