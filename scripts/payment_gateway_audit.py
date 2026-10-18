"""Kiểm thử cổng thanh toán (CHỈ server local 127.0.0.1:5001, tiệm demo) — đóng vai người dùng xấu/nhập sai để chắc
chắn tiền không bao giờ bị ghi sai, rồi chạy lại luồng đúng để chắc không chặn nhầm khách thật.

    python scripts/payment_gateway_audit.py

Mỗi mục: gửi dữ liệu xấu -> phải bị từ chối VÀ dữ liệu trong DB không đổi. Mọi bản ghi test được dọn ở cuối; cấu
hình nhận tiền của tiệm demo được sao lưu rồi trả lại nguyên trạng.
"""
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from mongo_client import db  # noqa: E402

B = 'http://127.0.0.1:5001'
assert B.startswith('http://127.0.0.1'), 'chỉ chạy trên server local'
NAIL = ('demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!')
FNB = ('demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!')
RETAIL = ('demo.retail.596348@bitpawdemo.com', 'DemoBitPaw2026!')
MARK = f"PAYAUDIT{int(time.time()) % 1000000}"
results, created = [], {'orders': set(), 'payment_transactions': set(), 'table_orders': [], 'saas_signups': set()}


def rec(name, ok, note=''):
    results.append({'name': name, 'ok': bool(ok), 'note': note})
    print(f"{'✅' if ok else '❌'} {name}" + (f" — {note}" if note else ''))


def unsecure(s):
    # cookie phiên có cờ Secure (production https) -> requests không gửi lại qua http local nếu không gỡ
    for c in s.cookies:
        c.secure = False


def login(email, password):
    s = requests.Session()
    r = s.get(B + '/login'); unsecure(s)
    tok = re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)
    r = s.post(B + '/login', data={'email': email, 'password': password, 'csrf_token': tok}, allow_redirects=False); unsecure(s)
    assert r.status_code == 302 and '/login' not in (r.headers.get('Location') or ''), f'login failed {email}'
    page = s.get(B + '/calendar'); unsecure(s)
    m = re.search(r'var CSRF_TOKEN = ("[^"]+")', page.text)
    s.headers['X-CSRFToken'] = json.loads(m.group(1)) if m else ''
    return s


def bid_of(email):
    u = db.users.find_one({'email': email}, {'business_id': 1, 'id': 1, '_id': 0})
    return u.get('business_id') or u.get('id')


def post(s, path, body=None, raw=None):
    if raw is not None:
        return s.post(B + path, data=raw, headers={'Content-Type': 'application/json'}, allow_redirects=False)
    return s.post(B + path, json=body, allow_redirects=False)


def j(r):
    try:
        return r.json()
    except Exception:
        return {}


nail, fnb, retail = login(*NAIL), login(*FNB), login(*RETAIL)
NB, FB, RB = bid_of(NAIL[0]), bid_of(FNB[0]), bid_of(RETAIL[0])
nail_svc = db.products.find_one({'business_id': NB, 'is_active': 1, 'price': {'$gt': 0}}, {'id': 1, 'price': 1, '_id': 0})
retail_prod = db.products.find_one({'business_id': RB, 'price': {'$gt': 0}, 'stock': {'$gte': 5}}, {'id': 1, 'price': 1, '_id': 0})
# Bàn TRỐNG (không có món nào đang treo): thanh toán thử gom MỌI món trên bàn rồi xoá — lần chạy đầu đã gom nhầm 1 món
# có sẵn trên Bàn 1 của tiệm demo (đã khôi phục). Không có bàn trống thì bỏ qua phần F&B, không đụng dữ liệu đang dùng.
from mongo_client import next_mongo_id  # noqa: E402
fnb_table = next_mongo_id('dining_tables')
db.dining_tables.insert_one({'id': fnb_table, 'business_id': FB, 'name': 'QA ' + MARK, 'status': 'Còn trống'})
fnb_prod = db.products.find_one({'business_id': FB, 'price': {'$gt': 0}}, {'id': 1, 'price': 1, '_id': 0})
today = time.strftime('%d/%m/%Y')

try:
    # ---------------- 1. JSON chứa NaN/Infinity ----------------
    r = post(nail, '/api/nail_pos/refund', raw='{"order_id": 1, "amount": NaN}')
    rec('JSON chứa NaN bị từ chối ngay khi đọc', r.status_code == 400, f"HTTP {r.status_code}")
    r = post(nail, '/api/payment/local_checkout', raw='{"items":[{"name":"x","quantity":1,"price":Infinity}]}')
    rec('JSON chứa Infinity bị từ chối', r.status_code == 400, f"HTTP {r.status_code}")

    # ---------------- 2. POS Nails: số liệu xấu ----------------
    base = {'items': [{'product_id': nail_svc['id'], 'quantity': 1}], 'payment_method': 'card', 'currency': 'AUD',
            'client_local_date': today}
    for label, extra in [('phí thẻ âm (-50%)', {'cc_fee_percent': -50, 'card_tip': 10}),
                         ('phí thẻ 500%', {'cc_fee_percent': 500, 'card_tip': 10}),
                         ('tip thẻ "Infinity"', {'card_tip': 'Infinity'}),
                         ('thuế "NaN"', {'tax_percent': 'NaN'}),
                         ('giảm giá "inf"', {'discount_type': 'fixed', 'discount_value': 'inf'})]:
        before = db.orders.count_documents({'business_id': NB})
        r = post(nail, '/api/nail_pos/checkout', dict(base, **extra))
        after = db.orders.count_documents({'business_id': NB})
        rec(f'POS Nails: {label} -> từ chối, không tạo bill', r.status_code == 400 and before == after, f"HTTP {r.status_code}")
    r = post(nail, '/api/nail_pos/checkout', {'items': [{'product_id': None, 'quantity': 1, 'custom_name': 'X', 'custom_price': 'inf'}],
                                               'payment_method': 'cash'})
    rec('POS Nails: dòng tự nhập giá "inf" -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")
    r = post(nail, '/api/nail_pos/checkout', dict(base, card_tip=5, cc_fee_percent=3))
    ok_sale = r.status_code == 200 and j(r).get('success')
    order_id = j(r).get('order_id')
    if order_id:
        created['orders'].add(order_id)
    rec('POS Nails: bill hợp lệ vẫn thanh toán bình thường', ok_sale, f"order #{order_id}")

    # ---------------- 3. Hoàn tiền Nails ----------------
    if order_id:
        def status():
            return (db.orders.find_one({'id': order_id}, {'status': 1, 'metadata.refunded_amount': 1, '_id': 0}) or {})
        for label, body in [('số tiền "NaN"', {'order_id': order_id, 'amount': 'NaN'}),
                            ('số tiền "Infinity"', {'order_id': order_id, 'amount': 'Infinity'}),
                            ('số tiền âm', {'order_id': order_id, 'amount': -5}),
                            ('lý do là số (từng làm hoá đơn "đã hoàn" mà không có bản ghi hoàn)', {'order_id': order_id, 'amount': 1, 'reason': 123})]:
            st0 = status()
            r = post(nail, '/api/nail_pos/refund', body)
            rec(f'Hoàn tiền Nails: {label} -> từ chối, hoá đơn không đổi', r.status_code == 400 and status() == st0, f"HTTP {r.status_code}")
        r = post(nail, '/api/nail_pos/refund', {'order_id': order_id, 'amount': 1, 'reason': MARK})
        rid = j(r).get('refund_id') or j(r).get('refund_order_id')
        if rid:
            created['orders'].add(rid)
        rec('Hoàn tiền Nails hợp lệ $1 vẫn chạy', r.status_code == 200, f"{status()}")
        r = post(nail, '/api/nail_pos/refund', {'order_id': order_id, 'amount': 99999})
        rec('Hoàn vượt số dư -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")
        r = post(fnb, '/api/nail_pos/refund', {'order_id': order_id, 'amount': 1})
        rec('Tiệm khác hoàn bill của tiệm Nails -> không tìm thấy', r.status_code in (403, 404), f"HTTP {r.status_code}")

    # ---------------- 4. Giỏ hàng dùng chung (Bán lẻ, VND) ----------------
    if retail_prod:
        rb = {'items': [{'product_id': retail_prod['id'], 'quantity': 1}], 'payment_method': 'cash'}
        r = post(retail, '/api/sales/checkout', dict(rb, tip_amount='Infinity'))
        rec('Bán lẻ: tip "Infinity" -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")
        r = post(retail, '/api/sales/checkout', dict(rb, payment_method=123))
        rec('Bán lẻ: phương thức thanh toán không phải chữ -> từ chối (trước đây lỗi 500)', r.status_code == 400, f"HTTP {r.status_code}")
        r = post(retail, '/api/sales/checkout', dict(rb, currency='USD', customer_phone={'$ne': None}))
        oid = j(r).get('order_id') or (j(r).get('data') or {}).get('order_id')
        if oid:
            created['orders'].add(oid)
        od = db.orders.find_one({'id': oid, 'business_id': RB}, {'metadata': 1, '_id': 0}) if oid else None
        meta = (od or {}).get('metadata') or {}
        rec('Bán lẻ: client gửi currency "USD" -> đơn vẫn ghi đúng VND của tiệm (chặn thổi điểm thưởng)',
            r.status_code == 200 and meta.get('currency') == 'VND' and not isinstance(meta.get('customer_phone'), dict),
            f"HTTP {r.status_code} currency={meta.get('currency')} phone={meta.get('customer_phone')!r}")

    # ---------------- 5. Thanh toán bàn F&B: start / confirm / cancel ----------------
    r = post(fnb, '/api/payment/start', {'table_id': fnb_table, 'amount': 'NaN', 'method': 'cash'})
    rec('F&B start: số tiền "NaN" -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")
    r = post(fnb, '/api/payment/start', {'table_id': fnb_table, 'amount': 1000, 'method': '<script>x</script>'})
    rec('F&B start: phương thức lạ -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")
    r = post(nail, '/api/payment/start', {'table_id': fnb_table, 'amount': 1000, 'method': 'cash'})
    rec('Tiệm khác khởi tạo thanh toán trên bàn F&B -> chặn', r.status_code == 403, f"HTTP {r.status_code}")
    # đặt 1 món lên bàn (dữ liệu test) rồi đi hết luồng thật
    to_id = int(time.time() * 1000) % 2_000_000_000
    db.table_orders.insert_one({'id': to_id, 'business_id': FB, 'table_id': fnb_table, 'product_id': fnb_prod['id'],
                                'quantity': 1, 'note': MARK})
    created['table_orders'].append(to_id)
    r = post(fnb, '/api/payment/confirm', {'table_id': fnb_table, 'txn_id': 'FAKE-' + MARK, 'method': 'cash'})
    rec('F&B confirm với mã giao dịch bịa -> từ chối (trước đây vẫn tạo đơn, không chống bấm 2 lần)', r.status_code == 404, f"HTTP {r.status_code}")
    r = post(fnb, '/api/payment/start', {'table_id': fnb_table, 'amount': fnb_prod['price'], 'method': 'cash',
                                          'industry': '<b>x</b>', 'tip_amount': 0})
    txn = j(r).get('txn_id')
    if txn:
        created['payment_transactions'].add(txn)
    rec('F&B start hợp lệ -> có mã giao dịch, link chờ thanh toán đã mã hoá', r.status_code == 200 and txn and '<' not in j(r).get('redirect_url', ''),
        j(r).get('redirect_url', '')[:110])
    r = post(fnb, '/api/payment/confirm', {'table_id': fnb_table, 'txn_id': txn, 'method': 'cash'})
    rec('F&B confirm hợp lệ -> đơn hoàn tất', r.status_code == 200 and j(r).get('success'), j(r).get('redirect_url', '')[:110])
    fo = db.orders.find_one({'business_id': FB, 'metadata.order_code': txn}, {'id': 1, '_id': 0})
    if fo:
        created['orders'].add(fo['id'])
    r = post(fnb, '/api/payment/confirm', {'table_id': fnb_table, 'txn_id': txn, 'method': 'cash'})
    rec('F&B confirm lần 2 cùng giao dịch -> không tạo đơn thứ 2', r.status_code in (400, 409), f"HTTP {r.status_code}")
    r = post(fnb, '/api/payment/cancel', {'txn_id': txn})
    st = (db.payment_transactions.find_one({'transaction_id': txn}, {'status': 1, '_id': 0}) or {}).get('status')
    rec('Huỷ giao dịch ĐÃ thu tiền -> từ chối (phải dùng Hoàn tiền)', r.status_code == 409 and st == 'completed', f"HTTP {r.status_code} status={st}")

    # ---------------- 6. Trang chờ thanh toán: không lộ tài khoản nhận tiền của tiệm khác ----------------
    r = nail.get(B + f'/payment_pending?table_id={fnb_table}&txn_id=x&amount=1', allow_redirects=False)
    fnb_cfg = db.system_settings.find_one({'key': 'payment_config', 'business_id': FB}, {'value': 1, '_id': 0})
    acct = ''
    if fnb_cfg:
        try:
            acct = str(json.loads(fnb_cfg['value']).get('account_number') or '')
        except Exception:
            acct = ''
    leaked = bool(acct) and acct in r.text
    rec('Tiệm Nails mở /payment_pending bằng bàn của tiệm F&B -> không thấy tài khoản nhận tiền F&B', not leaked and r.status_code in (302, 303),
        f"HTTP {r.status_code}")

    # ---------------- 7. Lưu cấu hình nhận tiền ----------------
    orig = db.system_settings.find_one({'key': 'payment_config', 'business_id': NB}, {'_id': 0})
    try:
        r = post(nail, '/api/payment/save_config', {'type': 'hacker_gateway', 'active': True})
        rec('Lưu cấu hình: loại cổng lạ -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")
        r = post(nail, '/api/payment/save_config', {'type': 'square_terminal', 'active': True, 'device_name': 'X' * 5000,
                                                     'nested': {'$where': '1'}, 'list': [1, 2]})
        saved = json.loads((db.system_settings.find_one({'key': 'payment_config', 'business_id': NB}) or {}).get('value') or '{}')
        rec('Lưu cấu hình: bỏ trường lồng nhau/mảng, cắt chuỗi quá dài', r.status_code == 200 and 'nested' not in saved and 'list' not in saved
            and len(saved.get('device_name', '')) <= 300, f"keys={sorted(saved)}")
        # đủ 12 loại cổng mà trang payment_gateway.html cho chọn — không loại nào được bị chặn oan
        bad = []
        for t in ('vietqr', 'square_terminal', 'clover_terminal', 'stripe_terminal', 'zelle', 'ach', 'cash_app', 'paypal_venmo',
                  'external_terminal', 'wise', 'paypal_intl', 'stripe_intl'):
            r = post(nail, '/api/payment/save_config', {'type': t, 'active': True, 'bank_code': 'VCB', 'account_number': '0123',
                                                         'account_holder': 'QA', 'transfer_prefix': 'BITPAW'})
            if r.status_code != 200:
                bad.append(f"{t}:{r.status_code}")
        rec('Lưu cấu hình: cả 12 loại cổng trên giao diện đều lưu được', not bad, ', '.join(bad))
    finally:
        if orig:
            db.system_settings.update_one({'key': 'payment_config', 'business_id': NB}, {'$set': {'value': orig['value']}})
        else:
            db.system_settings.delete_one({'key': 'payment_config', 'business_id': NB})

    # ---------------- 8. Trạng thái giao dịch ----------------
    t = db.payment_transactions.find_one({'business_id': FB, 'transaction_id': txn}, {'id': 1, '_id': 0})
    if t:
        r = post(fnb, f"/update_payment_status/{t['id']}", {'status': 'HACKED' * 50})
        rec('Đổi trạng thái giao dịch thành chuỗi lạ -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")

    # ---------------- 9. Bán lẻ local checkout ----------------
    r = post(fnb, '/api/payment/local_checkout', {'items': [{'name': 'x', 'quantity': 1, 'price': 'inf'}]})
    rec('Local checkout: giá "inf" -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")
    r = post(fnb, '/api/payment/local_checkout', {'items': [{'name': 'x', 'quantity': 10 ** 9, 'price': 1}]})
    rec('Local checkout: số lượng 1 tỷ -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")

    # ---------------- 10. Square chưa cấu hình: không lộ chi tiết biến môi trường ----------------
    if retail_prod:
        r = post(retail, '/api/payments/square/checkout', {'items': [{'product_id': retail_prod['id'], 'quantity': 1}]})
        body = r.text
        rec('Square chưa cấu hình -> không lộ độ dài Device ID / môi trường', 'SQUARE_DEVICE_ID_len' not in body and 'SQUARE_ENV' not in body,
            f"HTTP {r.status_code}")

    # ---------------- 11. Khách mua gói BitPaw (công khai) ----------------
    pub = requests.Session()
    base_signup = {'customer_name': 'QA ' + MARK, 'phone': '0400000000', 'shop_name': 'QA Shop', 'email': 'qa@example.com',
                   'memo_code': MARK}
    r = pub.post(B + '/api/checkout/signup', json=dict(base_signup, module_plan='pos', total_price=1))
    doc = db.saas_signups.find_one({'memo_code': MARK, 'module_plan': 'pos'}, {'_id': 0, 'id': 1, 'total_price': 1})
    if doc:
        created['saas_signups'].add(doc['id'])
    rec('Mua gói: sửa giá thành 1đ -> server vẫn ghi đúng giá gói 1.200.000', r.status_code == 200 and doc and doc['total_price'] == 1200000,
        f"HTTP {r.status_code} giá lưu={doc and doc['total_price']}")
    r = pub.post(B + '/api/checkout/signup', json=dict(base_signup, module_plan='agency', total_price=0))
    d2 = db.saas_signups.find_one({'memo_code': MARK, 'module_plan': 'agency'}, {'_id': 0, 'id': 1})
    if d2:
        created['saas_signups'].add(d2['id'])
    rec('Mua gói Agency (giá 0 = liên hệ) gửi được (trước đây luôn lỗi 400)', r.status_code == 200, f"HTTP {r.status_code}")
    r = pub.post(B + '/api/checkout/signup', json=dict(base_signup, module_plan='vip_free'))
    rec('Mua gói: gói không tồn tại -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")
    r = pub.post(B + '/api/checkout/signup', json=dict(base_signup, module_plan='pos', customer_name={'$gt': ''}))
    rec('Mua gói: tên là object -> từ chối', r.status_code == 400, f"HTTP {r.status_code}")
finally:
    # trả lại tồn kho các sản phẩm đã bán thử (bán lẻ + món F&B)
    for oid in created['orders']:
        o = db.orders.find_one({'id': oid}, {'business_id': 1, 'total_amount': 1, '_id': 0}) or {}
        if (o.get('total_amount') or 0) > 0:
            for it in db.order_items.find({'order_id': oid}, {'product_id': 1, 'quantity': 1, '_id': 0}):
                if it.get('product_id') is not None:
                    db.products.update_one({'id': it['product_id'], 'business_id': o.get('business_id'), 'stock': {'$exists': True}},
                                           {'$inc': {'stock': it.get('quantity') or 0}})
    for oid in created['orders']:
        db.order_items.delete_many({'order_id': oid})
        db.chamcong.delete_many({'ghi_chu': {'$regex': rf'Order #{oid}(?!\d)'}})
        db.transactions.delete_many({'order_id': oid})
    if created['orders']:
        db.orders.delete_many({'id': {'$in': list(created['orders'])}})
    if created['payment_transactions']:
        db.payment_transactions.delete_many({'transaction_id': {'$in': list(created['payment_transactions'])}})
    db.table_orders.delete_many({'id': {'$in': created['table_orders']}})
    db.table_orders.delete_many({'business_id': FB, 'table_id': fnb_table})
    db.dining_tables.delete_one({'id': fnb_table, 'business_id': FB})
    db.saas_signups.delete_many({'memo_code': MARK})
    print('Dọn dữ liệu test:', {k: len(v) for k, v in created.items()})

fail = sum(1 for r in results if not r['ok'])
print(f"\nTổng: {len(results) - fail} PASS · {fail} FAIL")
json.dump({'ranAt': time.strftime('%Y-%m-%dT%H:%M:%S'), 'results': results},
          open('audit-results/payment_gateway_audit.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
sys.exit(1 if fail else 0)
