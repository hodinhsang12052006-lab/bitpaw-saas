"""A/B: 20 bill cùng lúc đều chứa CÙNG 1 dịch vụ (có trường stock -> bị trừ kho trong transaction) so với bill không trừ kho.
Lộ ra việc các transaction tranh nhau 1 bản ghi products (WriteConflict -> tự thử lại -> chậm dần).
    python scripts/_checkout_contention_check.py <email_tiệm_thử> <mật_khẩu> [số_bill=100]     (CHỈ server local)
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from mongo_client import db  # noqa: E402

B = 'http://127.0.0.1:5001'
EMAIL, PW = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 100
assert EMAIL.startswith('qa.nailscale.')
BID = db.users.find_one({'email': EMAIL})['business_id']
svc = db.products.find_one({'business_id': BID, 'is_active': 1, 'price': {'$gt': 0}, 'stock': {'$exists': True}}, {'_id': 0, 'id': 1, 'price': 1, 'stock': 1})
tech = db.employees.find_one({'business_id': BID}, {'ma_nv': 1})['ma_nv']
s = requests.Session()
r = s.get(B + '/login')
for c in s.cookies:
    c.secure = False
s.post(B + '/login', data={'email': EMAIL, 'password': PW, 'csrf_token': re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)}, allow_redirects=False)
for c in s.cookies:
    c.secure = False
tok = re.search(r"CSRF_TOKEN\s*=\s*['\"]([^'\"]+)", s.get(B + '/sell').text).group(1)
today = datetime.now().strftime('%d/%m/%Y')


def run(label, item):
    def one(_):
        t0 = time.perf_counter()
        rr = s.post(B + '/api/nail_pos/checkout', headers={'X-CSRFToken': tok}, timeout=120,
                    json={'items': [item], 'payment_method': 'cash', 'currency': 'AUD', 'client_local_date': today})
        return rr.status_code, (time.perf_counter() - t0) * 1000
    t0 = time.time()
    with ThreadPoolExecutor(20) as ex:
        res = list(ex.map(one, range(N)))
    dt = time.time() - t0
    ms = sorted(x[1] for x in res)
    out = {'bill': N, 'giay': round(dt, 1), 'bill_moi_giay': round(N / dt, 1), 'p50_ms': round(ms[len(ms) // 2]), 'p95_ms': round(ms[int(len(ms) * .95)]),
           'http': {str(k): [x[0] for x in res].count(k) for k in {x[0] for x in res}}}
    print(label, json.dumps(out, ensure_ascii=False), flush=True)
    return out


stock0 = db.products.find_one({'id': svc['id']}, {'stock': 1})['stock']
a = run('A_cung_1_dich_vu_co_tru_kho', {'product_id': svc['id'], 'quantity': 1, 'ma_nv': tech})
b = run('B_mon_tu_nhap_khong_tru_kho', {'product_id': None, 'quantity': 1, 'ma_nv': tech, 'custom_name': 'Contention test', 'custom_price': svc['price']})
print('kho dịch vụ trước/sau:', stock0, '->', db.products.find_one({'id': svc['id']}, {'stock': 1})['stock'])
