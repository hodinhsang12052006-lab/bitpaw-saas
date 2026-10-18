"""Kiểm tra các góc cạnh của bản sửa sau kiểm thử tải (CHỈ server local + tiệm thử qa.nailscale.*; tự dọn dữ liệu thử):
  1. Huỷ lịch -> khung giờ mở lại; mở lại lịch đã huỷ khi giờ đó đã có người khác -> 409
  2. Món còn ĐÚNG 1 trong kho, 10 bill cùng lúc -> đúng 1 bill bán được, kho = 0
  3. Bill có 1 món đủ hàng + 1 món hết hàng -> từ chối, món đủ hàng được cộng trả kho
  4. 10 bill cùng lúc của 1 khách MỚI -> đúng 1 hồ sơ khách, tổng chi tiêu = tổng 10 bill, điểm = $1/điểm (AUD)
  5. Thêm khách trùng SĐT ở CRM -> 409 rõ ràng (không còn tạo 2 hồ sơ)
    python scripts/_verify_load_fixes.py <email> <mật_khẩu>
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from mongo_client import db, next_mongo_id  # noqa: E402

B = 'http://127.0.0.1:5001'
EMAIL, PW = sys.argv[1], sys.argv[2]
assert EMAIL.startswith('qa.nailscale.')
BID = db.users.find_one({'email': EMAIL})['business_id']
TECH = db.employees.find_one({'business_id': BID}, {'ma_nv': 1})['ma_nv']
SVC = db.products.find_one({'business_id': BID, 'is_active': 1, 'price': {'$gt': 0}}, {'_id': 0, 'id': 1})['id']
results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print(('✅' if ok else '❌'), name, '—', detail, flush=True)


def login():
    s = requests.Session()
    r = s.get(B + '/login')
    for c in s.cookies:
        c.secure = False
    s.post(B + '/login', data={'email': EMAIL, 'password': PW, 'csrf_token': re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)}, allow_redirects=False)
    for c in s.cookies:
        c.secure = False
    tok = re.search(r"CSRF_TOKEN\s*=\s*['\"]([^'\"]+)", s.get(B + '/sell').text).group(1)
    return s, {'X-CSRFToken': tok}


def public_book(i, bt, staff=TECH):
    s = requests.Session()
    h = {'X-Forwarded-For': f'192.0.2.{i}'}
    tok = re.search(r"CSRF_TOKEN\s*=\s*['\"]([^'\"]+)", s.get(f'{B}/booking/nail/qr/{BID}', headers=h).text).group(1)
    for c in s.cookies:
        c.secure = False
    r = s.post(B + '/create_appointment', headers={**h, 'X-CSRFToken': tok},
               json={'name': f'Fixcheck {i}', 'phone': f'04880{i:05d}', 'service_id': str(SVC), 'staff_id': staff, 'book_time': bt, 'note': '[FIXCHECK]'})
    return r.status_code, r.json()


owner, H = login()
today = datetime.now().strftime('%d/%m/%Y')
tmp_products = []
try:
    # 1) huỷ -> mở lại
    bt = (datetime.now() + timedelta(days=5)).replace(hour=6, minute=33).strftime('%Y-%m-%dT%H:%M')
    c1, j1 = public_book(1, bt)
    c2, _ = public_book(2, bt)
    owner.patch(f"{B}/api/appointments/{j1['id']}/status", headers=H, json={'status': 'cancelled'})
    c3, j3 = public_book(3, bt)
    reopen = owner.patch(f"{B}/api/appointments/{j1['id']}/status", headers=H, json={'status': 'pending'})
    check('Huỷ lịch thì khung giờ mở lại cho khách khác; mở lại lịch đã huỷ khi giờ đã có người -> 409',
          c1 == 200 and c2 == 409 and c3 == 200 and reopen.status_code == 409,
          f'đặt={c1}, người 2 cùng giờ={c2}, sau huỷ đặt lại={c3}, mở lại lịch cũ={reopen.status_code}')
    bt2 = (datetime.now() + timedelta(days=5)).replace(hour=6, minute=39).strftime('%Y-%m-%dT%H:%M')
    bt2_sec = bt2 + ':00'
    ca, _ = public_book(4, bt2)
    cb, _ = public_book(5, bt2_sec)
    check('Cùng giờ viết khác dạng (10:00 vs 10:00:00) vẫn bị chặn trùng', ca == 200 and cb == 409, f'{ca} / {cb}')

    # 2) kho còn 1, 10 bill cùng lúc
    pid = next_mongo_id('products')
    db.products.insert_one({'id': pid, 'business_id': BID, 'name': 'Fixcheck Polish (stock 1)', 'price': 12.0, 'stock': 1, 'is_active': 1, 'category': 'Retail'})
    tmp_products.append(pid)
    pay = lambda _: owner.post(B + '/api/nail_pos/checkout', headers=H, json={'items': [{'product_id': pid, 'quantity': 1, 'ma_nv': TECH}],
                                                                              'payment_method': 'cash', 'currency': 'AUD', 'client_local_date': today})
    with ThreadPoolExecutor(10) as ex:
        codes = [r.status_code for r in ex.map(pay, range(10))]
    n_orders = db.order_items.count_documents({'business_id': BID, 'product_id': pid})
    stock = db.products.find_one({'id': pid}, {'stock': 1})['stock']
    check('Kho còn 1, 10 bill cùng lúc: đúng 1 bill bán được, kho về 0 (không bán âm)', codes.count(200) == 1 and n_orders == 1 and stock == 0,
          f'200={codes.count(200)}, 400={codes.count(400)}, dòng bán={n_orders}, kho={stock}')

    # 3) bill 2 món: 1 đủ, 1 hết -> từ chối + cộng trả
    pid2 = next_mongo_id('products')
    db.products.insert_one({'id': pid2, 'business_id': BID, 'name': 'Fixcheck Oil (stock 5)', 'price': 8.0, 'stock': 5, 'is_active': 1, 'category': 'Retail'})
    tmp_products.append(pid2)
    r = owner.post(B + '/api/nail_pos/checkout', headers=H, json={'items': [{'product_id': pid2, 'quantity': 2, 'ma_nv': TECH}, {'product_id': pid, 'quantity': 1, 'ma_nv': TECH}],
                                                                  'payment_method': 'cash', 'currency': 'AUD', 'client_local_date': today})
    st2 = db.products.find_one({'id': pid2}, {'stock': 1})['stock']
    check('Bill có món hết hàng bị từ chối, món còn hàng được cộng trả đủ', r.status_code == 400 and st2 == 5, f'HTTP {r.status_code}, kho món kia={st2}')

    # 4) khách MỚI trả 10 bill cùng lúc
    phone = '0488' + datetime.now().strftime('%H%M%S')
    payn = lambda _: owner.post(B + '/api/nail_pos/checkout', headers=H, json={'items': [{'product_id': SVC, 'quantity': 1, 'ma_nv': TECH}], 'payment_method': 'cash',
                                                                               'currency': 'AUD', 'client_local_date': today, 'customer_phone': phone}).json()
    with ThreadPoolExecutor(10) as ex:
        bills = list(ex.map(payn, range(10)))
    paid = round(sum(b['total_amount'] for b in bills if b.get('success')), 2)
    profiles = list(db.customers.find({'business_id': BID, 'phone': phone}, {'_id': 0}))
    sp = round(sum(p.get('total_spent') or 0 for p in profiles), 2)
    pts = sum(p.get('loyalty_points') or 0 for p in profiles)
    exp_pts = sum(int(b['total_amount']) for b in bills if b.get('success'))
    check('Khách mới trả 10 bill cùng lúc: 1 hồ sơ, chi tiêu + điểm cộng đủ (AUD $1 = 1 điểm)', len(profiles) == 1 and abs(sp - paid) < 0.01 and pts == exp_pts,
          f'hồ sơ={len(profiles)}, đã trả ${paid}, CRM ${sp}, điểm {pts}/{exp_pts}, hạng {profiles[0].get("tier") if profiles else None}')

    # 5) CRM thêm trùng SĐT
    r = owner.post(B + '/add_customer', headers=H, json={'name': 'Dup', 'phone': phone})
    check('CRM thêm khách trùng SĐT -> 409 rõ ràng', r.status_code == 409, f"HTTP {r.status_code} {r.json().get('message')}")
finally:
    db.appointments.delete_many({'business_id': BID, 'note': '[FIXCHECK]'})
    db.products.delete_many({'id': {'$in': tmp_products}, 'business_id': BID})
print(json.dumps({'pass': sum(r[1] for r in results), 'fail': sum(not r[1] for r in results)}))
