"""Tạo / xoá 1 tiệm Nails THỬ TẢI quy mô lớn (mặc định 60 thợ, 30 ngày, ~360 bill/ngày) để đo độ ổn định.

    python scripts/nail_scale_seed.py create [số_thợ] [số_ngày] [bill_mỗi_ngày]
    python scripts/nail_scale_seed.py delete <business_id>
    python scripts/nail_scale_seed.py delete-all          # xoá mọi tiệm thử tải (email qa.nailscale.*)

Mọi tài liệu mang business_id riêng của tiệm thử -> xoá sạch bằng business_id. Định dạng bản ghi giống hệt
POS Nails thật (orders/order_items/chamcong hoa hồng/transactions), lịch hẹn, khách, chấm công check-in.
In ra dòng JSON cuối: {business_id, email, password, counts}.
"""
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from werkzeug.security import generate_password_hash  # noqa: E402

from mongo_client import db, next_mongo_id_batch  # noqa: E402

PASSWORD = 'QaNailScale2026!'
COLLECTIONS = ['orders', 'order_items', 'chamcong', 'transactions', 'customers', 'appointments', 'employees', 'staff',
               'products', 'payment_transactions', 'bot_customers', 'bot_messages', 'leave_requests', 'expense_requests',
               'system_settings', 'download_events', 'kitchen_orders', 'audit_logs', 'user_logs', 'tasks', 'security_events', 'business_memberships']
SERVICES = [  # (tên, nhóm, giá, giá vốn)
    ('Gel Manicure & Cuticle Care', 'Gel', 45, 9), ('Shellac Hand Treatment', 'Gel', 50, 10),
    ('Acrylic Full Set (Ombre/Design)', 'Acrylic', 95, 28.5), ('Acrylic Refill', 'Acrylic', 60, 15),
    ('Gel-X Extensions', 'Extensions', 85, 22), ('SNS Dipping Powder Full Set', 'Dipping', 70, 16),
    ('Signature Spa Pedicure', 'Pedicure', 65, 12), ('Deluxe Volcano Spa Pedi', 'Pedicure', 80, 18),
    ('Callus Treatment & Heel Scrub', 'Pedicure', 25, 4), ('Custom Nail Art (Per Finger)', 'Design', 5, 0.5),
    ('Custom 3D Chrome Nail Art', 'Design', 25, 4), ('Diamond Gem Encapsulation', 'Add-on', 30, 6),
    ('Eyebrow & Lip Waxing', 'Waxing', 25, 3), ('Mani & Pedi Royalty Combo', 'Packages', 115, 34.5),
]
FIRST = ['Ava', 'Chloe', 'Emily', 'Grace', 'Isabella', 'Sophia', 'Mia', 'Olivia', 'Lily', 'Zoe', 'Ruby', 'Ella', 'Amelia', 'Harper',
         'Linh', 'Mai', 'Thu', 'Ngoc', 'Trang', 'Hanh']
LAST = ['Nguyen', 'Tran', 'Le', 'Pham', 'Smith', 'Brown', 'Wilson', 'Taylor', 'Lee', 'Walker', 'Hall', 'Young']


def create(n_tech=60, days=30, bills_per_day=360):
    rnd = random.Random(60)
    bid = str(uuid.uuid4())
    stamp = datetime.now().strftime('%m%d%H%M')
    email = f'qa.nailscale.{stamp}@bitpawdemo.com'
    now = datetime.now()
    db.users.insert_one({'id': bid, 'email': email, 'password_hash': generate_password_hash(PASSWORD), 'business_id': bid,
                         'role': 'admin', 'created_at': now.isoformat()})
    db.businesses.insert_one({'id': bid, 'name': f'QA Scale Nails {n_tech} Techs', 'owner_name': 'QA Scale', 'industry_code': 'nail',
                              'created_at': now.isoformat(), 'country': 'AU', 'currency': 'AUD', 'mode': 'nail'})
    # ngành của tài khoản (login đọc khoá này; thiếu thì bị đưa sang màn chọn ngành /setup)
    db.system_settings.insert_one({'key': f'business_mode_{bid}', 'value': 'nail'})
    prod_ids = list(next_mongo_id_batch('products', len(SERVICES)))
    products = [{'id': pid, 'business_id': bid, 'name': n, 'category': c, 'price': float(p), 'cost_price': float(cp),
                 'is_active': 1, 'stock': 100000, 'channel_type': 'retail', 'image': ''}
                for pid, (n, c, p, cp) in zip(prod_ids, SERVICES)]
    db.products.insert_many(products)

    emp_ids = list(next_mongo_id_batch('employees', n_tech))
    staff_ids = list(next_mongo_id_batch('staff', n_tech))
    techs, staff = [], []
    for i in range(n_tech):
        name = f'{FIRST[i % len(FIRST)]} {LAST[(i // len(FIRST) + i) % len(LAST)]} {i + 1:02d}'
        ma_nv = f'QS{i + 1:03d}'
        techs.append({'id': emp_ids[i], 'business_id': bid, 'ma_nv': ma_nv, 'ho_ten': name, 'linh_vuc': 'Nails',
                      'chuc_vu': 'Nail Technician', 'luong_cb': 0, 'luong_gio': 22 + (i % 5), 'phu_cap': 0, 'diem_kudo': 0,
                      'thu_tu_tua': i + 1, 'staff_id': staff_ids[i]})
        staff.append({'id': staff_ids[i], 'business_id': bid, 'name': name, 'phone': f'04{10000000 + i:08d}',
                      'role': 'Nail Technician', 'commission_rate': 40 + (i % 3) * 5, 'is_active': True})
    db.employees.insert_many(techs)
    db.staff.insert_many(staff)

    cust_ids = list(next_mongo_id_batch('customers', 1500))
    customers = [{'id': cid, 'business_id': bid, 'name': f'QA Client {k + 1:04d}', 'phone': f'0499{k:06d}',
                  'email': f'client{k}@example.com', 'tier': rnd.choice(['Normal'] * 6 + ['Gold', 'Platinum']),
                  'loyalty_points': rnd.randint(0, 3000), 'total_spent': float(rnd.randint(50, 4000)),
                  'join_date': (now - timedelta(days=rnd.randint(30, 700))).isoformat(),
                  'last_purchase_at': (now - timedelta(days=rnd.randint(0, 120))).isoformat(), 'source_platform': 'pos'}
                 for k, cid in enumerate(cust_ids)]
    db.customers.insert_many(customers)

    total_bills = days * bills_per_day
    order_ids = iter(next_mongo_id_batch('orders', total_bills))
    n_items_est = total_bills * 2 + 10
    item_ids = iter(next_mongo_id_batch('order_items', n_items_est))
    cc_ids = iter(next_mongo_id_batch('chamcong', total_bills * 2 + n_tech * days + 10))
    tx_ids = iter(next_mongo_id_batch('transactions', total_bills))
    counts = {'orders': 0, 'order_items': 0, 'chamcong': 0, 'transactions': 0}
    for d in range(days, 0, -1):
        day = (now - timedelta(days=d)).replace(hour=9, minute=0, second=0, microsecond=0)
        orders, items, ccs, txs = [], [], [], []
        working = rnd.sample(techs, int(n_tech * 0.85))
        for t in working:  # check-in camera mỗi ngày làm
            ccs.append({'id': next(cc_ids), 'business_id': bid, 'ma_nv': t['ma_nv'], 'ngay_cham': day.strftime('%d/%m/%Y'),
                        'nganh_nghe': 'Nails', 'trang_thai': 'Có mặt', 'gio_den': '09:0' + str(rnd.randint(0, 9)),
                        'so_gio': 8, 'tien_tua': 0, 'tien_tips': 0, 'phu_cap': 0, 'tang_ca': 0})
        for b in range(bills_per_day):
            ts = day + timedelta(minutes=rnd.randint(0, 600))
            oid = next(order_ids)
            n_lines = 1 if rnd.random() < 0.6 else 2
            lines = []
            for _ in range(n_lines):
                prod = rnd.choice(products)
                tech = rnd.choice(working)
                lines.append((prod, tech))
            subtotal = round(sum(p['price'] for p, _ in lines), 2)
            card = rnd.random() < 0.65
            tip = round(rnd.choice([0, 0, 5, 8, 10, 15]), 2)
            total = round(subtotal + tip + (round(subtotal * 0.03, 2) if card else 0), 2)
            pm = 'card' if card else 'cash'
            orders.append({'id': oid, 'business_id': bid, 'created_at': ts.isoformat(), 'status': 'completed',
                           'total_amount': total, 'payment_method': pm,
                           'metadata': {'channel': 'nail_pos', 'subtotal': subtotal, 'supply_amount': round(subtotal * 0.05, 2),
                                        'discount_amount': 0.0, 'tax_amount': 0.0, 'tip_amount': tip, 'payment_bucket': pm,
                                        'currency': 'AUD', 'commission_rate': 40.0,
                                        'customer_phone': rnd.choice(customers)['phone'] if rnd.random() < 0.5 else None}})
            per_tech = {}
            for prod, tech in lines:
                items.append({'id': next(item_ids), 'order_id': oid, 'product_id': prod['id'], 'quantity': 1, 'price': prod['price'],
                              'total_price': prod['price'], 'ma_nv': tech['ma_nv'], 'business_id': bid})
                per_tech[tech['ma_nv']] = per_tech.get(tech['ma_nv'], 0) + prod['price']
            for ma_nv, rev in per_tech.items():
                ccs.append({'id': next(cc_ids), 'business_id': bid, 'ma_nv': ma_nv, 'ngay_cham': ts.strftime('%d/%m/%Y'),
                            'nganh_nghe': 'Nails', 'trang_thai': 'Đã chốt',
                            'ghi_chu': f'[NAILS POS] Order #{oid} — 40.0% hoa hồng',
                            'tien_tua': round(rev * 0.95 * 0.4, 2), 'tien_tips': round(tip / len(per_tech), 2),
                            'tien_tips_cash': 0.0 if card else round(tip / len(per_tech), 2),
                            'tien_tips_card': round(tip / len(per_tech), 2) if card else 0.0,
                            'phu_cap': 0, 'so_gio': 0, 'tang_ca': 0})
            txs.append({'id': next(tx_ids), 'business_id': bid, 'order_id': oid, 'amount': total, 'type': 'income',
                        'category': 'sales', 'payment_method': pm, 'timestamp': ts.isoformat(),
                        'transaction_date': ts.strftime('%Y-%m-%d'), 'created_by': email})
        db.orders.insert_many(orders)
        db.order_items.insert_many(items)
        db.chamcong.insert_many(ccs)
        db.transactions.insert_many(txs)
        for k, v in (('orders', orders), ('order_items', items), ('chamcong', ccs), ('transactions', txs)):
            counts[k] += len(v)
    appt_ids = iter(next_mongo_id_batch('appointments', (days + 8) * 70))
    appts = []
    for d in range(-days, 8):
        day = (now + timedelta(days=d)).replace(hour=9, minute=0, second=0, microsecond=0)
        for _ in range(60 if d < 0 else 70):
            t = rnd.choice(techs)
            c = rnd.choice(customers)
            bt = day + timedelta(minutes=15 * rnd.randint(0, 40))
            appts.append({'id': next(appt_ids), 'business_id': bid, 'customer_name': c['name'], 'customer_phone': c['phone'],
                          'service_id': rnd.choice(products)['id'], 'staff_id': t['ma_nv'], 'book_time': bt.strftime('%Y-%m-%dT%H:%M'),
                          'note': '', 'status': 'completed' if d < 0 else 'pending', 'source': rnd.choice(['web', 'ai_bot', 'phone']),
                          'created_at': (bt - timedelta(days=2)).isoformat()})
    db.appointments.insert_many(appts)
    counts.update({'employees': len(techs), 'customers': len(customers), 'appointments': len(appts), 'products': len(products)})
    return {'business_id': bid, 'email': email, 'password': PASSWORD, 'counts': counts}


def delete(bid):
    out = {}
    for c in COLLECTIONS:
        r = db[c].delete_many({'business_id': bid})
        if r.deleted_count:
            out[c] = r.deleted_count
    out['business_mode'] = db.system_settings.delete_many({'key': f'business_mode_{bid}'}).deleted_count
    out['users'] = db.users.delete_many({'business_id': bid, 'email': {'$regex': r'^qa\.nailscale\.'}}).deleted_count
    out['businesses'] = db.businesses.delete_many({'id': bid, 'name': {'$regex': '^QA Scale Nails'}}).deleted_count
    return out


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'create':
        args = [int(a) for a in sys.argv[2:5]]
        res = create(*args)
    elif cmd == 'delete':
        res = delete(sys.argv[2])
    elif cmd == 'delete-all':
        res = {u['business_id']: delete(u['business_id']) for u in db.users.find({'email': {'$regex': r'^qa\.nailscale\.'}}, {'business_id': 1})}
    else:
        res = {'error': 'cmd'}
    print(json.dumps(res, ensure_ascii=False))
