"""Đếm CHÍNH XÁC số lệnh gửi tới MongoDB cho 1 lượt đặt lịch công khai và 1 bill POS Nails (Flask test_client, cùng tiến trình).
Trên Atlas gói chia sẻ (giới hạn ~100 lệnh/giây cho CẢ cụm) đây là thước đo quyết định hệ thống chịu được bao nhiêu khách.
    EMAIL_DISABLED=1 python scripts/_count_db_ops.py <email_tiệm_thử> <mật_khẩu>
"""
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

from pymongo import monitoring

sys.stdout.reconfigure(encoding='utf-8')


class _L(monitoring.CommandListener):
    def __init__(self):
        self.on = False
        self.c = Counter()

    def started(self, e):
        if self.on and e.command_name not in ('hello', 'isMaster', 'ping', 'endSessions'):
            coll = e.command.get(e.command_name) if isinstance(e.command.get(e.command_name), str) else ''
            self.c[f'{e.command_name}:{coll}'] += 1

    def succeeded(self, e):
        pass

    def failed(self, e):
        pass


L = _L()
monitoring.register(L)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
assert os.environ.get('EMAIL_DISABLED') == '1'
import app as appmod  # noqa: E402
from mongo_client import db  # noqa: E402

EMAIL, PW = sys.argv[1], sys.argv[2]
assert EMAIL.startswith('qa.nailscale.')
BID = db.users.find_one({'email': EMAIL})['business_id']
svcs = list(db.products.find({'business_id': BID, 'is_active': 1, 'price': {'$gt': 0}}, {'id': 1, '_id': 0}).limit(3))
techs = [e['ma_nv'] for e in db.employees.find({'business_id': BID}, {'ma_nv': 1, '_id': 0}).limit(3)]
c = appmod.app.test_client()
out = {}


def measure(label, fn):
    L.c.clear(); L.on = True
    r = fn()
    L.on = False
    out[label] = {'http': r.status_code, 'tong_lenh_db': sum(L.c.values()), 'chi_tiet': dict(L.c.most_common())}


page = c.get(f'/booking/nail/qr/{BID}', headers={'X-Forwarded-For': '198.51.100.7'})
tok = re.search(r"CSRF_TOKEN\s*=\s*['\"]([^'\"]+)", page.get_data(as_text=True)).group(1)
measure('mo_trang_dat_lich', lambda: c.get(f'/booking/nail/qr/{BID}', headers={'X-Forwarded-For': '198.51.100.7'}))
bt = (datetime.now() + timedelta(days=4)).replace(hour=6, minute=11).strftime('%Y-%m-%dT%H:%M')
measure('gui_dat_lich', lambda: c.post('/create_appointment', headers={'X-CSRFToken': tok, 'X-Forwarded-For': '198.51.100.7'},
                                       json={'name': 'Ops count', 'phone': '0488000001', 'service_id': str(svcs[0]['id']), 'staff_id': techs[0],
                                             'book_time': bt, 'note': '[OPSCOUNT]'}))
c2 = appmod.app.test_client()
lp = c2.get('/login').get_data(as_text=True)
c2.post('/login', data={'email': EMAIL, 'password': PW, 'csrf_token': re.search(r'name="csrf_token" value="([^"]+)"', lp).group(1)})
tok2 = re.search(r"CSRF_TOKEN\s*=\s*['\"]([^'\"]+)", c2.get('/sell').get_data(as_text=True)).group(1)
today = datetime.now().strftime('%d/%m/%Y')
for n in (1, 3):
    measure(f'bill_{n}_dich_vu_{n}_tho_co_khach_quen', lambda n=n: c2.post('/api/nail_pos/checkout', headers={'X-CSRFToken': tok2}, json={
        'items': [{'product_id': svcs[i]['id'], 'quantity': 1, 'ma_nv': techs[i]} for i in range(n)], 'payment_method': 'card', 'card_tip': 10,
        'cc_fee_percent': 3, 'currency': 'AUD', 'client_local_date': today, 'customer_phone': '0466000001',
        'client_request_id': f'opscount{n}{datetime.now():%H%M%S%f}'}))
db.appointments.delete_many({'business_id': BID, 'note': '[OPSCOUNT]'})
print(json.dumps(out, ensure_ascii=False, indent=1))
