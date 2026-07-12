import os
import sys
import json

# Add parent directory to sys.path so we can import app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock custom DB initialization if needed or just import app
# We import app, it will trigger init_db() automatically on SQLite
from app import app

# Set testing mode
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False
app.config['SECRET_KEY'] = 'test-secret-key'

client = app.test_client()

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

print("=== STARTING FLASK ENDPOINT TEST ===")
results = []

for url in urls:
    # We will test two scenarios: anonymous and logged in
    # 1. Anonymous test
    res_anon = client.get(url)
    anon_status = res_anon.status_code
    anon_redirect = res_anon.location if anon_status in [301, 302] else None
    
    # 2. Logged in test
    with client.session_transaction() as sess:
        sess['user_id'] = 'mock-user-123'
        sess['business_id'] = 'mock-business-123'
        sess['business_mode'] = 'retail'
        sess['role'] = 'admin'
    
    res_auth = client.get(url)
    auth_status = res_auth.status_code
    auth_redirect = res_auth.location if auth_status in [301, 302] else None
    
    # Dump small chunk of HTML if 500 error occurs
    error_msg = ""
    if auth_status == 500:
        error_msg = res_auth.data.decode('utf-8', errors='ignore')[:1000]
    
    results.append({
        "url": url,
        "anonymous_status": anon_status,
        "anonymous_redirect": anon_redirect,
        "authenticated_status": auth_status,
        "authenticated_redirect": auth_redirect,
        "error_snippet": error_msg
    })
    print(f"Tested {url} | Anon: {anon_status} | Auth: {auth_status}")

# Test AI Studio generate API
print("\n=== TESTING AI GENERATE API ===")
payload = {
    "systemPrompt": "Bạn là Mascot AI BitPaw tư vấn SaaS cho SME Việt Nam.",
    "userPrompt": "Tiệm nail của tôi có 12 thợ, hay tranh tua và tính hoa hồng rất mệt. BitPaw giúp gì?"
}

res_api = client.post('/api/ai/studio/generate', 
                      data=json.dumps(payload), 
                      content_type='application/json')

api_status = res_api.status_code
api_data = None
try:
    api_data = json.loads(res_api.data.decode('utf-8'))
except Exception as e:
    api_data = res_api.data.decode('utf-8', errors='ignore')[:500]

print(f"POST /api/ai/studio/generate | Status: {api_status}")

# Save report
report_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'test_report.json'))
with open(report_path, 'w', encoding='utf-8') as f:
    json.dump({
        "endpoints": results,
        "ai_api_test": {
            "status": api_status,
            "response": api_data
        }
    }, f, indent=4, ensure_ascii=False)

print(f"\nReport written to: {report_path}")
