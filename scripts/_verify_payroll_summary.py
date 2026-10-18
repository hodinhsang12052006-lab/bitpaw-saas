"""Đối chiếu /api/hr/payroll_summary với cách tính CŨ của bangluong.html (cộng từng dòng chấm công) cho MỌI nhân viên.
    python scripts/_verify_payroll_summary.py <email> <password> <tháng> <năm>     (server local)
"""
import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from mongo_client import db  # noqa: E402

B = 'http://127.0.0.1:5001'
email, pw, month, year = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
s = requests.Session()
r = s.get(B + '/login')
for c in s.cookies:
    c.secure = False
tok = re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)
s.post(B + '/login', data={'email': email, 'password': pw, 'csrf_token': tok}, allow_redirects=False)
for c in s.cookies:
    c.secure = False
api = s.get(B + f'/api/hr/payroll_summary?month={month}&year={year}').json()['data']
bid = db.users.find_one({'email': email})['business_id']
old = {}
suffix = f'/{month:02d}/{year}'
for r in db.chamcong.find({'business_id': bid}):
    if not str(r.get('ngay_cham') or '').endswith(suffix):
        continue
    d = old.setdefault(r['ma_nv'], {'gio_hop_le': 0, 'tang_ca': 0, 'hoa_hong': 0, 'tips': 0, 'phu_cap': 0, 'so_ngay_lam': 0, 'so_ban_ghi': 0})
    so_gio = float(r.get('so_gio') or 0)
    att = r.get('trang_thai') in ('Có mặt', 'Trọn Ngày')
    d['gio_hop_le'] += so_gio if so_gio > 0 else (8 if att else 0)
    d['tang_ca'] += float(r.get('tang_ca') or 0)
    d['hoa_hong'] += float(r.get('tien_tua') or 0)
    d['tips'] += float(r.get('tien_tips') or 0)
    d['phu_cap'] += float(r.get('phu_cap') or 0)
    d['so_ngay_lam'] += 1 if att else 0
    d['so_ban_ghi'] += 1
bad = []
for ma, d in old.items():
    a = api.get(ma) or {}
    for k, v in d.items():
        if abs(float(a.get(k, 0)) - round(v, 2)) > 0.02:
            bad.append((ma, k, round(v, 2), a.get(k)))
print(json.dumps({'nhan_vien': len(old), 'api_nhan_vien': len(api), 'lech': bad[:10], 'so_lech': len(bad)}, ensure_ascii=False))
