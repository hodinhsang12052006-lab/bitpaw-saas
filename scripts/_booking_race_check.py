"""Đua đặt lịch: N khách mở sẵn trang đặt lịch, rồi CÙNG 1 khoảnh khắc bấm đặt đúng 1 thợ + 1 giờ (Barrier).
Đúng: chỉ 1 người được nhận lịch. Chạy N_ROUNDS khung giờ khác nhau để lộ lỗi kiểm-tra-rồi-ghi (race).
    python scripts/_booking_race_check.py <email_tiệm_thử> [số_khách=30] [số_vòng=10]     (CHỈ server local)
"""
import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from mongo_client import db  # noqa: E402

B = 'http://127.0.0.1:5001'
EMAIL = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 30
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 10
assert EMAIL.startswith('qa.nailscale.')
BID = db.users.find_one({'email': EMAIL})['business_id']
svc = db.products.find_one({'business_id': BID, 'is_active': 1, 'price': {'$gt': 0}}, {'id': 1})['id']
tech = db.employees.find_one({'business_id': BID, 'linh_vuc': 'Nails'}, {'ma_nv': 1}, sort=[('ma_nv', -1)])['ma_nv']
base = (datetime.now() + timedelta(days=3)).replace(hour=7, minute=0, second=0, microsecond=0)
tag = f'[RACE {datetime.now():%H%M%S}]'
rounds = []
for k in range(ROUNDS):
    bt = (base + timedelta(minutes=7 * k)).strftime('%Y-%m-%dT%H:%M')
    sessions, toks = [], []
    for i in range(N):
        s = requests.Session()
        h = {'X-Forwarded-For': f'172.16.{k}.{i + 1}'}
        html = s.get(f'{B}/booking/nail/qr/{BID}', headers=h, timeout=60).text
        for c in s.cookies:
            c.secure = False
        toks.append((s, h, re.search(r"CSRF_TOKEN\s*=\s*['\"]([^'\"]+)", html).group(1)))
    gate = threading.Barrier(N)
    codes = [None] * N

    def go(i):
        s, h, tok = toks[i]
        body = json.dumps({'name': f'Race {k}-{i}', 'phone': f'0477{k:02d}{i:04d}', 'service_id': str(svc), 'staff_id': tech,
                           'book_time': bt, 'note': tag})
        gate.wait()
        codes[i] = s.post(f'{B}/create_appointment', data=body, timeout=60,
                          headers={**h, 'X-CSRFToken': tok, 'Content-Type': 'application/json'}).status_code

    ts = [threading.Thread(target=go, args=(i,)) for i in range(N)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    in_db = db.appointments.count_documents({'business_id': BID, 'staff_id': tech, 'book_time': bt, 'status': {'$ne': 'cancelled'}})
    rounds.append({'gio': bt, 'http_200': codes.count(200), 'http_409': codes.count(409), 'khac': [c for c in codes if c not in (200, 409)], 'lich_trong_db': in_db})
    print(rounds[-1], flush=True)
bad = [r for r in rounds if r['lich_trong_db'] != 1]
print(json.dumps({'so_vong': ROUNDS, 'khach_moi_vong': N, 'vong_bi_dat_trung': len(bad),
                  'tong_lich_thua': sum(r['lich_trong_db'] - 1 for r in bad), 'ket_qua': 'PASS' if not bad else 'FAIL'}, ensure_ascii=False))
print('dọn:', db.appointments.delete_many({'business_id': BID, 'note': tag}).deleted_count, 'lịch thử')
