"""Kiểm thử bảo mật toàn bộ route trên server LOCAL (http://127.0.0.1:5001) — không chạy vào production.

A. Truy cập KHÔNG đăng nhập vào MỌI route (GET + POST/PUT/PATCH/DELETE): không route riêng tư nào được
   trả dữ liệu (200) hay sập (5xx).
B. IDOR chéo tenant: đăng nhập tenant Nails, dùng ID bản ghi THẬT của tenant F&B (tạo tạm bản ghi mồi)
   gọi mọi route có tham số <id>: GET không được lộ dữ liệu; POST/PUT/PATCH/DELETE không được làm đổi
   bản ghi (đối chiếu trực tiếp trong MongoDB trước/sau).
C. CSRF: POST/PUT/DELETE có session nhưng thiếu X-CSRFToken phải bị chặn (400).
D. Header bảo mật + cờ cookie phiên.
E. Open redirect sau đăng nhập (?next=//evil.example).
F. Reflected XSS qua query string.

Chạy (server local đang chạy, từ thư mục gốc):  python scripts/security_full_audit.py <out.json>
Bản ghi mồi tạo trong tenant F&B có tên "QA IDOR bait" và được xoá khi kết thúc.
"""
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from app import app  # noqa: E402
from mongo_client import db, next_mongo_id  # noqa: E402

B = 'http://127.0.0.1:5001'
OUT = sys.argv[1] if len(sys.argv) > 1 else 'security_full_audit.json'
NAIL = ('demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!')
FNB_EMAIL = 'demo.fnb.343602@bitpawdemo.com'
report = {'unauth': [], 'idor': [], 'csrf': [], 'headers': {}, 'open_redirect': None, 'xss': [], 'summary': {}}

PUBLIC_PAGE = re.compile(r'^/($|login|register|landing|landingpage|landing_nail|solutions/|privacy|terms|payment-policy|account/delete|checkout|favicon|sitemap|booking/|qr_menu|table_order|table_reservation|karaoke/book|hotel/book|portal|static/|index)')
SAFE_SKIP = {'/logout', '/api/cron/daily', '/cron/daily'}


def unsecure(s):
    for c in s.cookies:
        c.secure = False


def login(email, password):
    s = requests.Session()
    r = s.get(B + '/login'); unsecure(s)
    tok = re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)
    r = s.post(B + '/login', data={'email': email, 'password': password, 'csrf_token': tok}, allow_redirects=False); unsecure(s)
    if r.status_code != 302 or '/login' in (r.headers.get('Location') or ''):
        raise SystemExit(f'LOGIN FAILED {email}')
    page = s.get(B + '/calendar'); unsecure(s)
    m = re.search(r'var CSRF_TOKEN = ("[^"]+")', page.text)
    s.headers['X-CSRFToken'] = json.loads(m.group(1)) if m else ''
    return s


rules = [r for r in app.url_map.iter_rules() if r.endpoint != 'static']

# ---------- A. Không đăng nhập ----------
anon = requests.Session()
for r in rules:
    if r.rule in SAFE_SKIP:
        continue
    path = re.sub(r'<(?:int:)?[^>]+>', '1', r.rule)
    for m in sorted(x for x in r.methods if x not in ('HEAD', 'OPTIONS')):
        try:
            resp = anon.request(m, B + path, allow_redirects=False, timeout=20,
                                json={} if m != 'GET' else None)
            st = resp.status_code
            body = resp.text[:300]
        except Exception as e:
            st, body = 'ERR', str(e)[:120]
        public = bool(PUBLIC_PAGE.match(path)) or '/public/' in path or path.startswith('/api/portal') or path.startswith('/api/cskh') or path.startswith('/api/booking') or path.startswith('/api/webhook') or path == '/api/checkout/payment_methods'
        leak = st == 200 and not public and m == 'GET' and ('"success": true' in body.replace("'", '"') or '"data"' in body)
        bad = (isinstance(st, int) and st >= 500) or leak or (st == 200 and m != 'GET' and not public)
        report['unauth'].append({'method': m, 'path': path, 'status': st, 'public': public, 'flag': bad, 'body': body[:160] if bad else ''})

# ---------- B. IDOR chéo tenant ----------
fnb = db.users.find_one({'email': FNB_EMAIL})
fnb_bid = fnb.get('business_id') or fnb['id']
now = datetime.now().isoformat()
bait = {}


def mk(coll, doc):
    doc = {'id': next_mongo_id(coll), 'business_id': fnb_bid, 'created_at': now, **doc}
    db[coll].insert_one(dict(doc))
    bait[coll] = doc['id']


mk('products', {'name': 'QA IDOR bait', 'price': 1, 'stock': 5, 'is_active': 1, 'channel_type': 'fnb', 'category': 'QA'})
mk('customers', {'name': 'QA IDOR bait', 'phone': '0900000999', 'tier': 'Normal'})
mk('appointments', {'customer_name': 'QA IDOR bait', 'customer_phone': '0900000999', 'status': 'pending', 'book_time': now})
mk('employees', {'ho_ten': 'QA IDOR bait', 'ma_nv': 'QAIDOR1', 'linh_vuc': 'F&B'})
mk('expenses', {'description': 'QA IDOR bait', 'amount': 1})
mk('promotions', {'code': 'QAIDOR', 'name': 'QA IDOR bait', 'is_active': True})
mk('staff', {'name': 'QA IDOR bait', 'phone': '0900000998'})
mk('orders', {'total_amount': 1, 'status': 'completed', 'customer_name': 'QA IDOR bait'})
mk('dining_tables', {'name': 'QA IDOR bait', 'qr_token': 'qaidor' + uuid.uuid4().hex[:6], 'status': 'empty'})
mk('karaoke_rooms', {'name': 'QA IDOR bait', 'status': 'empty'})
mk('hotel_rooms', {'room_number': 'QAIDOR', 'status': 'available'})
mk('tasks', {'tieu_de': 'QA IDOR bait', 'trang_thai': 'pending'})
KEYWORD = [('product', 'products'), ('customer', 'customers'), ('appointment', 'appointments'), ('appt', 'appointments'),
           ('employee', 'employees'), ('nhanvien', 'employees'), ('expense', 'expenses'), ('promotion', 'promotions'),
           ('staff', 'staff'), ('order', 'orders'), ('table', 'dining_tables'), ('karaoke', 'karaoke_rooms'),
           ('room', 'hotel_rooms'), ('hotel', 'hotel_rooms'), ('task', 'tasks'), ('job', 'tasks'), ('/delete/', 'products'),
           ('/edit/', 'products'), ('/update/', 'products')]


def snap(coll, _id):
    d = db[coll].find_one({'id': _id}, {'_id': 0})
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest() if d else None


nail = login(*NAIL)
before = {c: snap(c, i) for c, i in bait.items()}
for r in rules:
    int_args = [a for a in r.arguments if str(r._converters.get(a).__class__.__name__) in ('IntegerConverter',)]
    if len(r.arguments) != 1 or not int_args:
        continue
    low = r.rule.lower()
    coll = next((c for k, c in KEYWORD if k in low), None)
    if not coll:
        continue
    path = re.sub(r'<int:[^>]+>', str(bait[coll]), r.rule)
    for m in sorted(x for x in r.methods if x not in ('HEAD', 'OPTIONS')):
        try:
            resp = nail.request(m, B + path, allow_redirects=False, timeout=20, json={'status': 'cancelled', 'name': 'HACKED', 'price': 999} if m != 'GET' else None)
            unsecure(nail)
            st, body = resp.status_code, resp.text
        except Exception as e:
            st, body = 'ERR', str(e)
        changed = snap(coll, bait[coll]) != before[coll]
        leaked = m == 'GET' and st == 200 and 'QA IDOR bait' in body
        report['idor'].append({'method': m, 'path': path, 'collection': coll, 'status': st, 'leaked': leaked, 'changed': changed,
                               'flag': leaked or changed or (isinstance(st, int) and st >= 500)})
        if changed:
            before[coll] = snap(coll, bait[coll])

# ---------- C. CSRF ----------
no_csrf = login(*NAIL)
no_csrf.headers.pop('X-CSRFToken', None)
for m, path, body in [('POST', '/api/users/delete-account', {'password': 'x'}), ('POST', '/create_appointment', {'name': 'QA CSRF', 'phone': '0900000997'}),
                      ('POST', '/api/products', {'name': 'QA CSRF', 'price': 1}), ('POST', '/api/chat/presence/ping', {'room': 'x'}),
                      ('POST', '/api/leave_requests', {'reason': 'QA CSRF'})]:
    resp = no_csrf.request(m, B + path, json=body, allow_redirects=False, timeout=20)
    report['csrf'].append({'method': m, 'path': path, 'status': resp.status_code, 'flag': resp.status_code not in (400, 403, 404, 405)})

# ---------- D. Header + cookie ----------
r = requests.get(B + '/login')
h = {k.lower(): v for k, v in r.headers.items()}
report['headers'] = {k: h.get(k) for k in ('x-content-type-options', 'x-frame-options', 'content-security-policy', 'referrer-policy', 'strict-transport-security', 'permissions-policy')}
report['headers']['set-cookie'] = r.headers.get('Set-Cookie', '')[:200]

# ---------- E. Open redirect ----------
s = requests.Session()
page = s.get(B + '/login?next=//evil.example/x'); unsecure(s)
tok = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
resp = s.post(B + '/login?next=//evil.example/x', data={'email': NAIL[0], 'password': NAIL[1], 'csrf_token': tok}, allow_redirects=False)
loc = resp.headers.get('Location', '')
report['open_redirect'] = {'location': loc, 'flag': 'evil.example' in loc}

# ---------- F. Reflected XSS ----------
payload = '<script>alert(1337)</script>'
for path in ['/login', '/customers', '/calendar', '/staff', '/booking/nail', '/privacy-policy', '/account/delete', '/checkout', '/solutions/nail']:
    resp = nail.get(B + path, params={'q': payload, 'search': payload, 'next': payload, 'lang': payload, 'date': payload}, timeout=20)
    report['xss'].append({'path': path, 'status': resp.status_code, 'flag': payload in resp.text})

# ---------- Dọn bản ghi mồi ----------
for coll, _id in bait.items():
    db[coll].delete_one({'id': _id, 'business_id': fnb_bid})
db.appointments.delete_many({'customer_name': 'QA CSRF'})
db.products.delete_many({'name': 'QA CSRF'})

for k in ('unauth', 'idor', 'csrf', 'xss'):
    report['summary'][k] = {'tested': len(report[k]), 'flagged': sum(1 for x in report[k] if x.get('flag'))}
report['summary']['open_redirect_flag'] = report['open_redirect']['flag']
json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(report['summary'], ensure_ascii=False))
print('headers', report['headers'])
for k in ('unauth', 'idor', 'csrf', 'xss'):
    for x in report[k]:
        if x.get('flag'):
            print('FLAG', k, x)
