"""Kiểm tra khoá tính năng theo gói (plans.py + app._plan_gate) bằng Flask test client — KHÔNG ghi database:
gói của tiệm được giả lập trong tiến trình test (plans.business_plan), yêu cầu nâng cấp bị chặn ghi (insert giả).
    python scripts/plan_gate_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod  # noqa: E402
import plans  # noqa: E402

app = appmod.app
app.config['WTF_CSRF_ENABLED'] = False
app.config['TESTING'] = True
appmod.limiter.enabled = False
appmod.csrf.protect = lambda: None   # app gọi csrf.protect() thủ công trong before_request; test client không có mã CSRF
db = appmod.db

EMAIL = 'demo.nails.au.006758@bitpawdemo.com'
user = db.users.find_one({'email': EMAIL}, {'_id': 0, 'id': 1, 'business_id': 1, 'session_ver': 1})
BID = user.get('business_id') or user['id']
CURRENT = {'plan': 'essential'}
plans.business_plan = lambda _db, bid, ttl=60: CURRENT['plan']
captured = []
# KHÔNG ghi DB thật: pymongo tạo Collection mới mỗi lần db.<tên>, nên phải chặn ở lớp Collection (chỉ saas_signups)
# và cả bộ đếm id (next_mongo_id ghi db.counters).
from pymongo.collection import Collection  # noqa: E402
_orig_insert = Collection.insert_one


def _fake_insert(self, doc, *a, **k):
    if self.name == 'saas_signups':
        captured.append(dict(doc))
        return None
    return _orig_insert(self, doc, *a, **k)


Collection.insert_one = _fake_insert
appmod.next_mongo_id = lambda name: -1
if hasattr(appmod, 'EmailService'):
    appmod.EmailService.send_email = staticmethod(lambda *a, **k: True)

results = []


def check(name, ok, note=''):
    results.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {note}' if note else ''))


def client():
    c = app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = user['id']; s['business_id'] = BID; s['role'] = 'admin'; s['business_mode'] = 'nail'
        s['user_email'] = EMAIL; s['sv'] = int(user.get('session_ver') or 0)
    return c


c = client()
CURRENT['plan'] = 'essential'
r = c.get('/roster')
check('Essential: /roster (Pro) -> chuyển tới /plan', r.status_code == 302 and '/plan?feature=roster' in r.headers.get('Location', ''), r.headers.get('Location'))
r = c.get('/api/roster/week', headers={'Accept': 'application/json'})
check('Essential: API lịch ca -> 403 upgrade_required', r.status_code == 403 and (r.get_json() or {}).get('upgrade_required') is True, str(r.status_code))
r = c.get('/ai_bot')
check('Essential: AI Copilot (Empire) -> /plan', r.status_code == 302 and 'feature=ai_copilot' in r.headers.get('Location', ''))
r = c.get('/pos')
check('Essential: POS không bị khoá', r.status_code in (200, 302) and '/plan' not in r.headers.get('Location', ''), str(r.status_code))
r = c.get('/calendar')
html = r.get_data(as_text=True)
check('Menu hiện nhãn khoá cho mục thuộc gói cao hơn', r.status_code == 200 and 'plan-lock' in html, str(html.count('plan-lock')))
r = c.get('/plan?feature=roster')
html = r.get_data(as_text=True)
check('Trang /plan: gói hiện tại + gói cần + nút nâng cấp', r.status_code == 200 and 'Pro Partner' in html and 'data-plan="pro"' in html and 'data-plan="empire"' in html)
r = c.post('/api/plan/request', json={'plan': 'pro'})
body = r.get_json() or {}
exp = plans.price('nail', 'pro', body.get('data', {}).get('currency', 'USD'))
check('Yêu cầu nâng cấp Pro: giá đúng ngành Nails', r.status_code == 200 and captured and captured[-1]['monthly_fee'] == exp[0] and captured[-1]['setup_fee'] == exp[1],
      f"{body.get('data')}")
r = c.post('/api/plan/request', json={'plan': 'essential'})
check('Không cho "nâng cấp" xuống gói thấp hơn/bằng', r.status_code == 400)

CURRENT['plan'] = 'pro'
check('Pro: /roster mở', c.get('/roster').status_code == 200)
r = c.get('/ai_bot')
check('Pro: AI Copilot vẫn khoá (Empire)', r.status_code == 302 and 'feature=ai_copilot' in r.headers.get('Location', ''))
CURRENT['plan'] = 'empire'
check('Empire: AI Copilot mở', c.get('/ai_bot').status_code == 200)
html = c.get('/calendar').get_data(as_text=True)
check('Empire: menu không còn nhãn khoá', 'plan-lock' not in html)

# Trang công khai của khách không bao giờ bị khoá (kể cả gói Essential)
CURRENT['plan'] = 'essential'
anon = app.test_client()
check('Khách vào /qr_menu/<mã bàn> không bị khoá', '/plan' not in (anon.get('/qr_menu/not-a-real-token').headers.get('Location') or ''))
check('plans.feature_for_path: trang khách không thuộc tính năng nào',
      all(plans.feature_for_path(p) is None for p in ('/reserve/x', '/hotel/reserve/x', '/booking/nail/qr/x', '/qr_menu/abc', '/portal')))
check('Giá AUD làm tròn ...9', plans.price('nail', 'pro', 'AUD') == (199, 749) and plans.price('fnb', 'empire', 'AUD') == (449, 2999))

print(f'\n{sum(results)}/{len(results)} PASS')
sys.exit(0 if all(results) else 1)
