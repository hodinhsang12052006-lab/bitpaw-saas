"""Kiểm tra /api/stream/payroll?ma_nv=: chỉ máy của ĐÚNG thợ nhận tín hiệu khi có dòng chấm công mới.
    python scripts/_verify_earnings_stream.py <email> <password>      (CHỈ server local; tự xoá dòng thử)
"""
import json
import os
import re
import sys
import threading
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from mongo_client import db  # noqa: E402

B = 'http://127.0.0.1:5001'
email, pw = sys.argv[1], sys.argv[2]
s = requests.Session()
r = s.get(B + '/login')
for c in s.cookies:
    c.secure = False
tok = re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)
s.post(B + '/login', data={'email': email, 'password': pw, 'csrf_token': tok}, allow_redirects=False)
for c in s.cookies:
    c.secure = False
page = s.get(B + '/chamcong_nail').text
csrf = re.search(r"CSRF_TOKEN\s*=\s*['\"]([^'\"]+)", page).group(1)

got = {'QS001': 0, 'QS002': 0, 'ALL': 0}


def listen(key, url):
    with s.get(url, stream=True, timeout=30) as resp:
        t_end = time.time() + 14
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith('data:') and 'changed' in line:
                got[key] += 1
            if time.time() > t_end:
                break


threads = [threading.Thread(target=listen, args=('QS001', B + '/api/stream/payroll?ma_nv=QS001')),
           threading.Thread(target=listen, args=('QS002', B + '/api/stream/payroll?ma_nv=QS002')),
           threading.Thread(target=listen, args=('ALL', B + '/api/stream/payroll'))]
for t in threads:
    t.start()
time.sleep(4)
today = datetime.now().strftime('%d/%m/%Y')
res = s.post(B + '/api/hr/chamcong', headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
             data=json.dumps({'ma_nv': 'QS001', 'ho_ten': 'Stream test', 'ngay_cham': today, 'trang_thai': 'Có mặt',
                              'nganh_nghe': 'Nails', 'ghi_chu': '[STREAM TEST]'}))
print('POST', res.status_code)
for t in threads:
    t.join()
bid = db.users.find_one({'email': email})['business_id']
deleted = db.chamcong.delete_many({'business_id': bid, 'ghi_chu': '[STREAM TEST]'}).deleted_count
ok = got['QS001'] >= 1 and got['QS002'] == 0 and got['ALL'] >= 1
print(json.dumps({'tin_hieu': got, 'xoa_dong_thu': deleted, 'ket_qua': 'PASS' if ok else 'FAIL'}, ensure_ascii=False))
