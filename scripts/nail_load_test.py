"""Kiểm thử TẢI ngành Nails — hàng trăm/nghìn khách đặt lịch + tính tiền cùng lúc, rồi ĐỐI SOÁT database.

CHỈ chạy với server local 127.0.0.1:5001 khởi động bằng EMAIL_DISABLED=1 (không gửi email thật) và 1 tiệm thử
tạo bằng scripts/nail_scale_seed.py (xoá bằng `nail_scale_seed.py delete-all` sau khi đo).

    python scripts/nail_load_test.py <email_tiệm_thử> <mật_khẩu> [số_khách_đặt_lịch=1000] [số_bill=1000]

Mỗi "khách" là 1 phiên riêng + 1 IP riêng (X-Forwarded-For, đúng cách server nhận IP thật sau proxy): mở trang
đặt lịch công khai (lấy CSRF + cookie như trình duyệt thật) rồi gửi lịch. Không chỉ đếm HTTP 200 — sau mỗi pha
đọc lại DB để tìm: lịch trùng thợ/giờ, đơn/giao dịch/hoa hồng lệch nhau, điểm thưởng/tổng chi tiêu của khách bị mất.
"""
import json
import os
import random
import re
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from mongo_client import db  # noqa: E402

B = 'http://127.0.0.1:5001'
EMAIL, PW = sys.argv[1], sys.argv[2]
N_BOOK = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
N_BILL = int(sys.argv[4]) if len(sys.argv) > 4 else 1000
RUN = datetime.now().strftime('%H%M%S')
rnd = random.Random(int(RUN))  # mỗi lượt chạy 1 kịch bản ngẫu nhiên riêng (không đặt lại đúng các khung của lượt trước)
report = {'run': RUN, 'phases': {}}

user = db.users.find_one({'email': EMAIL})
assert user and EMAIL.startswith('qa.nailscale.'), 'Chỉ chạy trên tiệm thử qa.nailscale.*'
BID = user['business_id']
SERVICES = list(db.products.find({'business_id': BID, 'is_active': 1, 'price': {'$gt': 0}}, {'_id': 0, 'id': 1, 'price': 1}))
TECHS = [e['ma_nv'] for e in db.employees.find({'business_id': BID, 'linh_vuc': 'Nails'}, {'ma_nv': 1, '_id': 0})]
assert SERVICES and len(TECHS) >= 10


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 0) if xs else None


def lat_summary(lats):
    return {'p50_ms': pct(lats, 0.5), 'p95_ms': pct(lats, 0.95), 'p99_ms': pct(lats, 0.99), 'max_ms': round(max(lats), 0) if lats else None}


def csrf_of(html):
    m = re.search(r"CSRF_TOKEN\s*=\s*['\"]([^'\"]+)", html) or re.search(r'name="csrf-token" content="([^"]+)"', html) \
        or re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ''


def insecure(s):
    for c in s.cookies:
        c.secure = False


# ---------------- theo dõi máy chủ (RAM/CPU/luồng của tiến trình python đang nghe cổng 5001) ----------------
def server_pid():
    out = subprocess.run(['powershell', '-NoProfile', '-Command',
                          '(Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue).OwningProcess'],
                         capture_output=True, text=True).stdout.strip()
    return int(out.split()[0]) if out else None


samples = []
_stop = threading.Event()


def sampler(pid):
    while not _stop.is_set():
        out = subprocess.run(['powershell', '-NoProfile', '-Command',
                              f'$p=Get-Process -Id {pid}; "$($p.WorkingSet64) $($p.CPU) $($p.Threads.Count) $($p.HandleCount)"'],
                             capture_output=True, text=True).stdout.split()
        if len(out) == 4:
            samples.append({'t': time.time(), 'rss_mb': int(out[0]) / 1048576, 'cpu_s': float(out[1]), 'threads': int(out[2]), 'handles': int(out[3])})
        _stop.wait(2)


def phase_machine(t0, t1):
    win = [s for s in samples if t0 <= s['t'] <= t1]
    if len(win) < 2:
        return {}
    cpu = (win[-1]['cpu_s'] - win[0]['cpu_s']) / max(0.1, win[-1]['t'] - win[0]['t'])
    return {'rss_mb_start': round(win[0]['rss_mb']), 'rss_mb_max': round(max(s['rss_mb'] for s in win)), 'rss_mb_end': round(win[-1]['rss_mb']),
            'cpu_cores_avg': round(cpu, 2), 'threads_max': max(s['threads'] for s in win), 'handles_max': max(s['handles'] for s in win)}


# ---------------- 1 khách đặt lịch qua trang công khai ----------------
def book(i, staff_id, book_time, phone=None, ip=None, sess=None):
    s = sess or requests.Session()
    hdr = {'X-Forwarded-For': ip or f'10.{(i >> 16) & 255}.{(i >> 8) & 255}.{i & 255}'}
    t0 = time.perf_counter()
    try:
        page = s.get(f'{B}/booking/nail/qr/{BID}', headers=hdr, timeout=60)
        insecure(s)
        tok = csrf_of(page.text)
        r = s.post(f'{B}/create_appointment', timeout=60, headers={**hdr, 'X-CSRFToken': tok, 'Content-Type': 'application/json'},
                   data=json.dumps({'name': f'LoadTest {RUN} #{i}', 'phone': phone or f'0455{i:06d}', 'service_id': str(rnd.choice(SERVICES)['id']),
                                    'staff_id': staff_id, 'book_time': book_time, 'note': f'[LOADTEST {RUN}]'}))
        body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
        return {'status': r.status_code, 'ok': bool(body.get('success')), 'ms': (time.perf_counter() - t0) * 1000, 'msg': body.get('message', '')[:80]}
    except Exception as e:
        return {'status': 0, 'ok': False, 'ms': (time.perf_counter() - t0) * 1000, 'msg': str(e)[:80]}


def slot_conflicts():
    """Thợ bị đặt TRÙNG: cùng thợ + cùng giờ có >1 lịch còn hiệu lực, trong các khung có lịch của lượt test này."""
    mine = db.appointments.find({'business_id': BID, 'note': f'[LOADTEST {RUN}]', 'staff_id': {'$nin': [None, '']}}, {'staff_id': 1, 'book_time': 1, '_id': 0})
    keys = {(a['staff_id'], a['book_time']) for a in mine}
    bad = 0
    examples = []
    for st, bt in keys:
        n = db.appointments.count_documents({'business_id': BID, 'staff_id': st, 'book_time': bt, 'status': {'$nin': ['cancelled', 'canceled']}})
        if n > 1:
            bad += 1
            if len(examples) < 5:
                examples.append(f'{st} {bt} x{n}')
    return bad, examples


def summarize(label, res, t0, t1, extra=None):
    st = Counter(r['status'] for r in res)
    out = {'requests': len(res), 'seconds': round(t1 - t0, 1), 'req_per_s': round(len(res) / max(0.1, t1 - t0), 1),
           'status': dict(st), 'ok': sum(r['ok'] for r in res), **lat_summary([r['ms'] for r in res]),
           'errors_sample': list({r['msg'] for r in res if r['status'] not in (200, 409)})[:5], 'machine': phase_machine(t0, t1)}
    out.update(extra or {})
    report['phases'][label] = out
    print(f'\n=== {label} ===\n' + json.dumps(out, ensure_ascii=False, indent=1))
    return out


tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
pid = server_pid()
threading.Thread(target=sampler, args=(pid,), daemon=True).start()
time.sleep(3)

# PHA 1 — 50 khách cùng bấm đặt ĐÚNG 1 thợ, ĐÚNG 1 giờ (khung đẹp ngày mai 10:00) -> chỉ được đúng 1 người có chỗ
hot_staff, hot_time = TECHS[0], (tomorrow + timedelta(hours=10, minutes=5)).strftime('%Y-%m-%dT%H:%M')
db.appointments.delete_many({'business_id': BID, 'staff_id': hot_staff, 'book_time': hot_time})
t0 = time.time()
with ThreadPoolExecutor(50) as ex:
    res = list(ex.map(lambda i: book(900000 + i, hot_staff, hot_time), range(50)))
t1 = time.time()
n_db = db.appointments.count_documents({'business_id': BID, 'staff_id': hot_staff, 'book_time': hot_time, 'status': {'$nin': ['cancelled', 'canceled']}})
summarize('1_50_khach_cung_1_tho_cung_1_gio', res, t0, t1,
          {'lich_trong_db_cho_khung_do': n_db, 'ket_qua': 'PASS' if n_db == 1 else f'FAIL — {n_db} khách cùng giữ 1 chỗ'})

# PHA 2 — bão đặt lịch: N khách, 100 người cùng lúc, 7 ngày tới, 40% dồn vào khung đẹp (thứ 7 10h-12h, 5 thợ hot)
def pick(i):
    if rnd.random() < 0.4:
        day = tomorrow + timedelta(days=(5 - tomorrow.weekday()) % 7)
        return rnd.choice(TECHS[:5]), (day + timedelta(hours=10, minutes=30 * rnd.randint(0, 4))).strftime('%Y-%m-%dT%H:%M')
    staff = None if rnd.random() < 0.25 else rnd.choice(TECHS)  # trang đặt lịch gửi null khi khách chọn "thợ nào cũng được"
    day = tomorrow + timedelta(days=rnd.randint(0, 6))
    return staff, (day + timedelta(hours=9, minutes=30 * rnd.randint(0, 19))).strftime('%Y-%m-%dT%H:%M')


plan = [pick(i) for i in range(N_BOOK)]
t0 = time.time()
with ThreadPoolExecutor(100) as ex:
    res = list(ex.map(lambda i: book(i, *plan[i]), range(N_BOOK)))
t1 = time.time()
created = db.appointments.count_documents({'business_id': BID, 'note': f'[LOADTEST {RUN}]', 'customer_name': {'$not': re.compile(r'#9\d{5}$')}})
bad, ex_bad = slot_conflicts()
summarize(f'2_bao_dat_lich_{N_BOOK}_khach_100_cung_luc', res, t0, t1, {
    'lich_tao_trong_db': created, 'bao_thanh_cong': sum(r['ok'] for r in res),
    'khop_db': created == sum(r['ok'] for r in res),
    'khung_bi_dat_trung_tho': bad, 'vi_du_trung': ex_bad})

# PHA 3 — 1 kẻ phá (1 IP, 1 SĐT) gửi 300 lịch giả liên tục
spam_s = requests.Session()
t0 = time.time()
with ThreadPoolExecutor(10) as ex:
    res = list(ex.map(lambda i: book(800000 + i, None, (tomorrow + timedelta(days=2, hours=9, minutes=i % 600)).strftime('%Y-%m-%dT%H:%M'),
                                     phone='0499999999', ip='203.0.113.66'), range(300)))
t1 = time.time()
summarize('3_spam_1_ip_1_sdt_300_lich', res, t0, t1, {'lich_spam_vao_duoc_db': sum(r['ok'] for r in res)})

# ---------------- chủ tiệm ----------------
owner = requests.Session()
r = owner.get(B + '/login'); insecure(owner)
owner.post(B + '/login', data={'email': EMAIL, 'password': PW, 'csrf_token': csrf_of(r.text)}, allow_redirects=False); insecure(owner)
OWNER_CSRF = csrf_of(owner.get(B + '/sell').text)
busiest = Counter(bt[:10] for _, bt in plan).most_common(1)[0][0]
t0 = time.perf_counter(); cal = owner.get(f'{B}/calendar?date={busiest}'); cal_ms = (time.perf_counter() - t0) * 1000
n_day = db.appointments.count_documents({'business_id': BID, 'book_time': {'$gte': busiest + 'T00:00', '$lte': busiest + 'T23:59:59'}})
report['phases']['4_chu_tiem_mo_lich_ngay_dong_nhat'] = {'ngay': busiest, 'lich_trong_ngay': n_day, 'http': cal.status_code,
                                                       'kb': round(len(cal.content) / 1024), 'ms': round(cal_ms)}
print('\n=== 4_chu_tiem_mo_lich ===', report['phases']['4_chu_tiem_mo_lich_ngay_dong_nhat'])

# PHA 5 — bão tính tiền: N bill, 20 lượt cùng lúc (nhiều máy POS/điện thoại), 30 khách quen quay lại nhiều lần
REG = [f'0466{k:06d}' for k in range(30)]
before = {c['phone']: c for c in db.customers.find({'business_id': BID, 'phone': {'$in': REG}}, {'_id': 0})}
today = datetime.now().strftime('%d/%m/%Y')


def checkout(i, payload=None):
    if payload is None:
        items = [{'product_id': s['id'], 'quantity': 1, 'ma_nv': rnd.choice(TECHS)} for s in rnd.sample(SERVICES, rnd.randint(1, 3))]
        method = rnd.choice(['cash', 'card', 'card', 'split'])
        payload = {'items': items, 'payment_method': method, 'currency': 'AUD', 'client_local_date': today,
                   'customer_phone': rnd.choice(REG) if rnd.random() < 0.7 else '', 'customer_name': ''}
        if method in ('card', 'split'):
            payload.update({'card_tip': rnd.choice([0, 5, 10]), 'cc_fee_percent': 3})
        if method in ('cash', 'split'):
            payload['cash_tip'] = rnd.choice([0, 5])
        if method == 'split':
            payload['cash_amount'] = 20
            payload['card_amount'] = 9999  # server tự cân lại phần thẻ; nếu bị từ chối sẽ thấy trong lỗi
    t0 = time.perf_counter()
    try:
        r = owner.post(f'{B}/api/nail_pos/checkout', headers={'X-CSRFToken': OWNER_CSRF, 'Content-Type': 'application/json'},
                       data=json.dumps(payload), timeout=120)
        j = r.json()
        return {'status': r.status_code, 'ok': bool(j.get('success')), 'ms': (time.perf_counter() - t0) * 1000, 'msg': str(j.get('message', ''))[:80],
                'order_id': j.get('order_id'), 'total': j.get('total_amount'), 'techs_paid': j.get('techs_paid') or [], 'phone': payload.get('customer_phone')}
    except Exception as e:
        return {'status': 0, 'ok': False, 'ms': (time.perf_counter() - t0) * 1000, 'msg': str(e)[:80]}


t0 = time.time()
with ThreadPoolExecutor(20) as ex:
    res = list(ex.map(checkout, range(N_BILL)))
t1 = time.time()
okr = [r for r in res if r['ok']]
oids = [r['order_id'] for r in okr]
exp_total = round(sum(r['total'] for r in okr), 2)
db_orders = list(db.orders.find({'business_id': BID, 'id': {'$in': oids}}, {'_id': 0, 'id': 1, 'total_amount': 1}))
db_tx = list(db.transactions.find({'business_id': BID, 'order_id': {'$in': oids}}, {'_id': 0, 'amount': 1, 'order_id': 1}))
exp_comm = round(sum(t['commission'] + t['tip'] for r in okr for t in r['techs_paid']), 2)
db_cc = list(db.chamcong.aggregate([{'$match': {'business_id': BID, 'ghi_chu': {'$regex': r'^\[NAILS POS\] Order #'}, 'ngay_cham': today}},
                                    {'$addFields': {'oid': {'$toInt': {'$arrayElemAt': [{'$split': [{'$arrayElemAt': [{'$split': ['$ghi_chu', '#']}, 1]}, ' ']}, 0]}}}},
                                    {'$match': {'oid': {'$in': oids}}},
                                    {'$group': {'_id': None, 's': {'$sum': {'$add': ['$tien_tua', '$tien_tips']}}, 'n': {'$sum': 1}}}]))
spent = defaultdict(float)
exp_pts = defaultdict(int)
for r in okr:
    if r['phone']:
        spent[r['phone']] += r['total']
        exp_pts[r['phone']] += int(r['total'])  # tiền đô: 1 điểm / $1, làm tròn xuống THEO TỪNG BILL
after = {c['phone']: c for c in db.customers.find({'business_id': BID, 'phone': {'$in': REG}}, {'_id': 0})}
dup_phones = list(db.customers.aggregate([{'$match': {'business_id': BID, 'phone': {'$in': REG}}}, {'$group': {'_id': '$phone', 'n': {'$sum': 1}}}, {'$match': {'n': {'$gt': 1}}}]))
lost_spent, lost_points, worst = 0.0, 0, []
for ph, s in spent.items():
    got = sum(c.get('total_spent') or 0 for c in db.customers.find({'business_id': BID, 'phone': ph}, {'_id': 0, 'total_spent': 1})) - (before.get(ph, {}).get('total_spent') or 0)
    pts = sum(c.get('loyalty_points') or 0 for c in db.customers.find({'business_id': BID, 'phone': ph}, {'_id': 0, 'loyalty_points': 1})) - (before.get(ph, {}).get('loyalty_points') or 0)
    miss = round(s - got, 2)
    lost_spent += miss
    lost_points += exp_pts[ph] - pts
    if miss > 0.01 and len(worst) < 3:
        worst.append(f'{ph}: thanh toán ${s:.2f}, CRM chỉ cộng ${got:.2f}, điểm +{pts}')
tiers = Counter((after.get(ph) or {}).get('tier') for ph in spent)
summarize(f'5_bao_tinh_tien_{N_BILL}_bill_20_cung_luc', res, t0, t1, {
    'tong_tien_bao_ve': exp_total, 'tong_tien_orders_db': round(sum(o['total_amount'] for o in db_orders), 2),
    'so_order_db': len(db_orders), 'so_giao_dich_db': len(db_tx), 'tong_giao_dich_db': round(sum(t.get('amount') or 0 for t in db_tx), 2),
    'hoa_hong_tip_bao_ve': exp_comm, 'hoa_hong_tip_db': round(db_cc[0]['s'], 2) if db_cc else 0, 'so_dong_cham_cong': db_cc[0]['n'] if db_cc else 0,
    'khach_quen_trung_ho_so': len(dup_phones), 'chi_tieu_bi_mat_tren_crm': round(lost_spent, 2), 'diem_bi_mat_hoac_khong_cong': lost_points,
    'hang_khach_quen_sau_test': dict(tiers), 'vi_du_lech_crm': worst})

# PHA 6 — mạng chập chờn: cùng 1 bill gửi lại 2 lần (thu ngân bấm lại khi chưa thấy phản hồi)
pay = {'items': [{'product_id': SERVICES[0]['id'], 'quantity': 1, 'ma_nv': TECHS[1]}], 'payment_method': 'cash', 'currency': 'AUD',
       'client_local_date': today, 'client_request_id': f'retry-{RUN}'}
with ThreadPoolExecutor(2) as ex:
    rr = list(ex.map(lambda _: checkout(0, dict(pay)), range(2)))
ids = {r.get('order_id') for r in rr if r['ok']}
report['phases']['6_gui_lai_cung_1_bill'] = {'phan_hoi': [r['status'] for r in rr], 'so_order_khac_nhau_tao_ra': len(ids),
                                            'ket_qua': 'PASS' if len(ids) == 1 else f'FAIL — 1 bill thành {len(ids)} đơn (thu tiền 2 lần, trả hoa hồng 2 lần)'}
print('\n=== 6_gui_lai ===', report['phases']['6_gui_lai_cung_1_bill'])

# PHA 7 — chủ tiệm xem số trong lúc vừa bão xong: lương tháng + báo cáo + dashboard
for label, url in [('payroll_summary', f'/api/hr/payroll_summary?month={datetime.now().month}&year={datetime.now().year}'),
                   ('report_consolidated', '/report_consolidated'), ('dashboard', '/dashboard'), ('nail_pos_orders', '/api/nail_pos/orders')]:
    t0 = time.perf_counter(); r = owner.get(B + url); ms = (time.perf_counter() - t0) * 1000
    report['phases'].setdefault('7_chu_tiem_xem_so', {})[label] = {'http': r.status_code, 'kb': round(len(r.content) / 1024), 'ms': round(ms)}
print('\n=== 7_chu_tiem_xem_so ===', report['phases']['7_chu_tiem_xem_so'])

_stop.set()
report['machine_overall'] = phase_machine(samples[0]['t'], samples[-1]['t']) if samples else {}
out = f'audit-results/nail_load_test_{os.environ.get("LOADTEST_TAG", "run")}.json'
os.makedirs('audit-results', exist_ok=True)
json.dump(report, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('\nĐã lưu', out, '· máy chủ:', report['machine_overall'])
