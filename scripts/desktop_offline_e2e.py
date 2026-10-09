"""E2E bản Desktop mất mạng (in-process bằng Flask test client, không cần chạy server).
Chạy từ thư mục gốc: python scripts/desktop_offline_e2e.py  (cần: pip install montydb==2.5.6)
Ghi đơn test lên MongoDB trong .env rồi tự xoá sạch ở cuối.

Luồng:
online mở POS -> cache bảng giá -> giả lập mất mạng Atlas -> bán 2 bill -> mở lại POS offline ->
sync_status -> có mạng lại -> sync_worker đẩy lên Atlas -> kiểm tra orders/order_items/chamcong/
transactions -> dọn sạch dữ liệu test."""
import os
import re
import sys
import shutil
import tempfile
import time

FAKE_APPDATA = tempfile.mkdtemp(prefix='bitpaw_desktop_e2e_')
os.environ['APPDATA'] = FAKE_APPDATA   # local_db ghi vào thư mục tạm, không đụng dữ liệu Desktop thật trên máy
os.environ['BITPAW_DESKTOP_MODE'] = '1'
sys.path.insert(0, os.getcwd())

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

import app as app_module  # noqa: E402
import sync_worker  # noqa: E402
from mongo_client import db as cloud_db  # noqa: E402

app = app_module.app
EMAIL = 'demo.nails.au.006758@bitpawdemo.com'
user = cloud_db.users.find_one({'email': EMAIL}, {'_id': 0, 'id': 1, 'business_id': 1})
BID = user.get('business_id') or user['id']
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail else ''))


class _DeadCollection:
    def __getattr__(self, name):
        def _boom(*a, **k):
            time.sleep(0.05)
            raise ServerSelectionTimeoutError('simulated: no network to Atlas')
        return _boom


class _DeadDB:
    def __getattr__(self, name):
        return _DeadCollection()

    def __getitem__(self, name):
        return _DeadCollection()


c = app.test_client()
with c.session_transaction() as s:
    s['user_id'] = user['id']
    s['business_id'] = BID
    s['business_mode'] = 'nail'
    s['user_email'] = EMAIL

# 1) Online: mở POS -> bảng giá được lưu xuống máy
r = c.get('/sell')
html = r.get_data(as_text=True)
check('Online /sell 200', r.status_code == 200)
check('Online: không hiện badge offline', 'id="offlineSyncBadge"' in html and 'display:none' in html.split('id="offlineSyncBadge"')[1][:400])
cache = sync_worker.get_cached_catalog(BID)
check('Bảng giá đã lưu trên máy', bool(cache and cache.get('services')), f"{len((cache or {}).get('services') or [])} dịch vụ, {len((cache or {}).get('technicians') or [])} thợ")
token = re.search(r'var CSRF_TOKEN = "([^"]+)"', html).group(1)
svc = [x for x in cache['services'] if x.get('price')][:2]
tech = (cache.get('technicians') or [{}])[0].get('ma_nv')
payload = {
    'items': [{'product_id': svc[0]['id'], 'quantity': 1, 'ma_nv': tech},
              {'product_id': svc[1]['id'], 'quantity': 1, 'ma_nv': tech},
              {'custom_name': 'QA offline custom', 'custom_price': 5, 'quantity': 1}],
    'payment_method': 'cash', 'tips': [], 'currency': 'AUD',
}
expected_sub = round(svc[0]['price'] + svc[1]['price'] + 5, 2)

# 2) Mất mạng
real_db = app_module.db
app_module.db = _DeadDB()
sync_worker.mark_online()
uuids = []
try:
    t0 = time.time()
    r = c.post('/api/nail_pos/checkout', json=payload, headers={'X-CSRFToken': token})
    j = r.get_json()
    check('Mất mạng hẳn: bill 1 vẫn thanh toán được', r.status_code == 200 and j.get('success') and j.get('pending_sync'), f"HTTP {r.status_code} {j.get('message')}")
    check('Bill 1 tính đúng tiền từ bảng giá trên máy', abs(j.get('subtotal', 0) - expected_sub) < 0.01, f"{j.get('subtotal')} vs {expected_sub}")
    uuids.append(j.get('client_uuid'))
    t1 = time.time()
    r = c.post('/api/nail_pos/checkout', json=payload, headers={'X-CSRFToken': token})
    j = r.get_json()
    dt = time.time() - t1
    check('Bill 2 lưu ngay (không thử Atlas lại)', j.get('pending_sync') and dt < 1.0, f'{dt:.2f}s')
    uuids.append(j.get('client_uuid'))
    r = c.get('/sell')
    h = r.get_data(as_text=True)
    check('Mở lại POS khi mất mạng: có lưới dịch vụ từ máy', r.status_code == 200 and svc[0]['name'] in h)
    check('Badge offline hiện', 'display:flex' in h.split('id="offlineSyncBadge"')[1][:400])
    st = c.get('/api/desktop/sync_status').get_json()
    check('sync_status: offline + 2 bill chờ', st.get('offline') and st.get('pending') == 2, str(st))
finally:
    app_module.db = real_db

# 3) Có mạng lại -> đồng bộ
synced = sync_worker.sync_pending_orders_once()
check('Đồng bộ 2 bill lên Atlas', synced == 2, f'synced={synced}')
orders = list(cloud_db.orders.find({'metadata.client_uuid': {'$in': uuids}}, {'_id': 0}))
check('2 đơn có trên Atlas, đúng tổng tiền', len(orders) == 2 and all(abs(o['metadata']['subtotal'] - expected_sub) < 0.01 for o in orders))
oids = [o['id'] for o in orders]
n_items = cloud_db.order_items.count_documents({'order_id': {'$in': oids}})
cc_q = {'business_id': BID, 'ghi_chu': {'$regex': r'^\[NAILS POS - Offline Sync\] Order #(' + '|'.join(map(str, oids)) + r') '}}
n_cc = cloud_db.chamcong.count_documents(cc_q) if tech else -1
n_tx = cloud_db.transactions.count_documents({'order_id': {'$in': oids}, 'business_id': BID})
check('order_items đủ 3 dòng/bill', n_items == 6, str(n_items))
check('Hoa hồng thợ (chamcong) ghi đủ', n_cc == 2 or not tech, str(n_cc))
check('Sổ cái transactions có 2 bản ghi', n_tx == 2, str(n_tx))
st = c.get('/api/desktop/sync_status').get_json()
check('sync_status sau đồng bộ: 0 bill chờ, hết offline', st.get('pending') == 0 and not st.get('offline'), str(st))

# 4) Dọn dữ liệu test
for x in svc:
    if 'stock' in x:
        cloud_db.products.update_one({'id': x['id'], 'business_id': BID}, {'$inc': {'stock': 2}})
        print('restored stock', x['id'])
cloud_db.order_items.delete_many({'order_id': {'$in': oids}, 'business_id': BID})
cloud_db.chamcong.delete_many(cc_q)
cloud_db.transactions.delete_many({'order_id': {'$in': oids}, 'business_id': BID})
cloud_db.orders.delete_many({'id': {'$in': oids}, 'business_id': BID})
left = cloud_db.orders.count_documents({'metadata.client_uuid': {'$in': uuids}})
print(f'cleanup: còn {left} đơn test, {cloud_db.chamcong.count_documents(cc_q)} chamcong test')
print(f'\nTổng: {sum(results)}/{len(results)} PASS')
shutil.rmtree(FAKE_APPDATA, ignore_errors=True)
sys.exit(0 if all(results) else 1)
