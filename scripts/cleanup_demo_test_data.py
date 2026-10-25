"""Dọn mọi bản ghi do BÀI TEST để lại trong 9 tiệm demo (chạy sau các bài *_industry_master_audit) — nhận diện bằng chữ
đánh dấu của bài test ("QA Audit", "QAAUDIT", "QA Pricing"...). Bill: xoá cả bill gốc của bill hoàn tiền test + dòng hàng
+ sổ cái + hoa hồng. Sao lưu trước khi xoá.
    python scripts/cleanup_demo_test_data.py                      # chạy thử: in ra sẽ xoá gì
    python scripts/cleanup_demo_test_data.py --apply backup.json  # sao lưu vào backup.json rồi xoá
Chỉ đụng các tài khoản @bitpawdemo.com liệt kê trong DEMOS."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mongo_client import db  # noqa: E402

DEMOS = ['demo.fnb.343602', 'demo.karaoke.071443', 'demo.hotel.071443', 'demo.retail.596348', 'demo.production.393328',
         'demo.technical.393328', 'demo.office.784966', 'demo.nails.au.006758', 'demo.spa.596348']
RX = re.compile(r'QA Audit|QAAUDIT|QA Pricing|QA Spa|Debug SSE|latency-probe|E2E Test|Test Product|qa\.audit', re.I)
DIRECT = ['promotions', 'hotel_room_charges', 'product_recipes', 'production_output', 'chamcong', 'hotel_reservations',
          'table_reservations', 'karaoke_room_reservations', 'appointments', 'customers', 'expenses', 'tasks', 'raw_materials']
apply = '--apply' in sys.argv
backup, ops, plan = {}, [], {}


def hit(d):
    return bool(RX.search(json.dumps(d, default=str, ensure_ascii=False)))


for email in DEMOS:
    u = db.users.find_one({'email': email + '@bitpawdemo.com'}, {'id': 1, 'business_id': 1})
    bid = u.get('business_id') or u['id']
    key = email.split('.')[1]
    # bill test + bill gốc của bill hoàn tiền test + bill hoàn tiền của bill test
    ids = set()
    for o in db.orders.find({'business_id': bid}, {'_id': 0}):
        if hit(o):
            ids.add(o['id'])
            orig = (o.get('metadata') or {}).get('original_order_id')
            if orig:
                ids.add(orig)
    for oi in db.order_items.find({'business_id': bid}, {'_id': 0, 'order_id': 1, 'custom_name': 1}):
        if hit(oi):
            ids.add(oi['order_id'])
    if ids:
        ids |= {o['id'] for o in db.orders.find({'business_id': bid, 'metadata.original_order_id': {'$in': list(ids)}}, {'id': 1})}
        ids = sorted(ids)
        rx = '#(' + '|'.join(str(i) for i in ids) + r')(?!\d)'
        for coll, flt in [('orders', {'business_id': bid, 'id': {'$in': ids}}), ('order_items', {'order_id': {'$in': ids}}),
                          ('transactions', {'business_id': bid, 'order_id': {'$in': ids}}),
                          ('payment_transactions', {'business_id': bid, 'order_id': {'$in': ids}}),
                          ('chamcong', {'business_id': bid, 'ghi_chu': {'$regex': rx}})]:
            docs = list(db[coll].find(flt, {'_id': 0}))
            if docs:
                backup.setdefault(key, {}).setdefault(coll, []).extend(docs)
                ops.append((coll, flt))
                plan[f'{key}.{coll}(bill)'] = len(docs)
    for coll in DIRECT:
        docs = [d for d in db[coll].find({'business_id': bid}, {'_id': 0}) if hit(d)]
        if not docs:
            continue
        keyf = 'id' if all('id' in d for d in docs) else None
        if keyf:
            flt = {'business_id': bid, 'id': {'$in': [d['id'] for d in docs]}}
        else:
            print('  skip (no id)', key, coll, len(docs))
            continue
        backup.setdefault(key, {}).setdefault(coll, []).extend(docs)
        ops.append((coll, flt))
        plan[f'{key}.{coll}'] = len(docs)

for k, v in sorted(plan.items()):
    print(f'  {k}: {v}')
if apply:
    path = sys.argv[sys.argv.index('--apply') + 1]
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(backup, fh, ensure_ascii=False, default=str)
    print('backup ->', path)
    total = 0
    for coll, flt in ops:
        total += db[coll].delete_many(flt).deleted_count
    print('deleted', total, 'APPLIED')
else:
    print('DRY RUN')
