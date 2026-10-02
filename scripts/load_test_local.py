"""Load test trên server LOCAL (http://127.0.0.1:5001) — KHÔNG bao giờ chạy vào production.

Mô phỏng N người dùng đồng thời (mỗi người 1 IP riêng qua X-Forwarded-For, giống khách thật sau
Cloudflare, để đo SERVER chứ không đo rate limiter theo IP). Mỗi người dùng đăng nhập rồi lặp lại các
thao tác thật của 1 tiệm Nails: mở POS, lịch hẹn, khách hàng, lương, gọi API danh sách, thanh toán đơn
(món tự do "QA LOAD" — ghi lại order_id để xoá sạch sau khi đo) và khách vãng lai mở trang đặt lịch.

Chạy:  python scripts/load_test_local.py <số người dùng> <số giây> <out.json>
"""
import json
import random
import re
import statistics
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

B = 'http://127.0.0.1:5001'
USERS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 60
OUT = sys.argv[3] if len(sys.argv) > 3 else 'load_test.json'
EMAIL, PASSWORD = 'demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!'
BOOKING_PATH = '/booking/nail/qr/000b2c16-ab4e-42bd-944a-29c925cad09b'

lock = threading.Lock()
lat = defaultdict(list)
status = defaultdict(lambda: defaultdict(int))
order_ids = []
stop_at = 0.0


def rec(name, t0, st):
    with lock:
        lat[name].append((time.time() - t0) * 1000)
        status[name][st] += 1


def call(s, name, method, path, **kw):
    t0 = time.time()
    try:
        r = s.request(method, B + path, timeout=30, **kw)
        for c in s.cookies:
            c.secure = False
        rec(name, t0, r.status_code)
        return r
    except requests.exceptions.Timeout:
        rec(name, t0, 'timeout')
    except Exception:
        rec(name, t0, 'conn_error')
    return None


def user(idx):
    s = requests.Session()
    s.headers['X-Forwarded-For'] = f'10.{idx // 250}.{idx % 250}.{random.randint(1, 250)}'
    r = call(s, 'GET /login', 'GET', '/login')
    if not r:
        return
    tok = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    r = call(s, 'POST /login', 'POST', '/login', data={'email': EMAIL, 'password': PASSWORD, 'csrf_token': tok.group(1) if tok else ''}, allow_redirects=False)
    if not r or r.status_code != 302:
        return
    page = call(s, 'GET /calendar', 'GET', '/calendar')
    m = re.search(r'var CSRF_TOKEN = ("[^"]+")', page.text) if page is not None else None
    if m:
        s.headers['X-CSRFToken'] = json.loads(m.group(1))
    today = time.strftime('%Y-%m-%d')

    def checkout_inner():
        r = call(s, 'POST /api/nail_pos/checkout', 'POST', '/api/nail_pos/checkout', json={
            'items': [{'product_id': None, 'quantity': 1, 'ma_nv': None, 'custom_name': 'QA LOAD', 'custom_price': 10}],
            'customer_phone': None, 'payment_method': 'cash', 'supply_percent': 0, 'tax_percent': 0, 'cash_tip': 0,
            'card_tip': 0, 'cc_fee_percent': 3, 'commission_rate': 40, 'currency': 'AUD'})
        if r is not None and r.status_code == 200:
            try:
                oid = r.json().get('order_id')
                if oid is not None:
                    with lock:
                        order_ids.append(oid)
            except Exception:
                pass

    actions = [
        (20, lambda: call(s, 'GET /sell (POS)', 'GET', '/sell')),
        (10, lambda: call(s, 'GET /calendar', 'GET', '/calendar')),
        (8, lambda: call(s, 'GET /customers', 'GET', '/customers')),
        (5, lambda: call(s, 'GET /bangluong', 'GET', '/bangluong')),
        (12, lambda: call(s, 'GET /api/customers', 'GET', '/api/customers')),
        (12, lambda: call(s, 'GET /api/nail_pos/orders', 'GET', f'/api/nail_pos/orders?date={today}')),
        (8, lambda: call(s, 'GET /api/hr/employees', 'GET', '/api/hr/employees')),
        (6, lambda: call(s, 'GET /api/nail_pos/checked_in', 'GET', '/api/nail_pos/checked_in')),
        (8, checkout_inner),
        (6, lambda: call(requests.Session(), 'GET booking public', 'GET', BOOKING_PATH)),
    ]
    weights = [w for w, _ in actions]

    while time.time() < stop_at:
        random.choices([a for _, a in actions], weights=weights)[0]()



def main():
    global stop_at
    t_start = time.time()
    stop_at = t_start + DURATION
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        for i in range(USERS):
            ex.submit(user, i)
            time.sleep(0.05)  # tăng dần người dùng trong ~USERS*0.05 giây
    elapsed = time.time() - t_start
    total = sum(len(v) for v in lat.values())
    rows = {}
    for name, v in sorted(lat.items()):
        v2 = sorted(v)
        rows[name] = {
            'count': len(v2), 'p50_ms': round(statistics.median(v2)), 'p95_ms': round(v2[int(len(v2) * 0.95) - 1]) if len(v2) > 1 else round(v2[0]),
            'max_ms': round(v2[-1]), 'status': dict(status[name]),
        }
    errors = sum(n for st in status.values() for k, n in st.items() if not isinstance(k, int) or k >= 500)
    rl = sum(n for st in status.values() for k, n in st.items() if k == 429)
    summary = {'users': USERS, 'duration_s': round(elapsed), 'requests': total, 'rps': round(total / elapsed, 1),
               'server_errors_or_timeouts': errors, 'rate_limited_429': rl, 'orders_created': len(order_ids)}
    json.dump({'summary': summary, 'endpoints': rows, 'order_ids': order_ids}, open(OUT, 'w'), indent=1)
    print(json.dumps(summary))
    for name, r in rows.items():
        print(f"{name:32s} n={r['count']:5d} p50={r['p50_ms']:6d}ms p95={r['p95_ms']:6d}ms max={r['max_ms']:6d}ms {r['status']}")


if __name__ == '__main__':
    main()
