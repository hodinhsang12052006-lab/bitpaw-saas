"""Tìm (và tuỳ chọn xoá) dữ liệu do các script kiểm thử để lại trong các TIỆM DEMO (@bitpawdemo.com) —
khách tiềm năng nhìn thấy tiệm demo nên không được lẫn "QA Test Tech 1660", "QA IDOR bait", "E2E Business
Cycle Khách"... Chỉ đụng tới business_id của tài khoản @bitpawdemo.com và chỉ bản ghi có tên theo mẫu test.

    python scripts/cleanup_demo_test_leftovers.py                     # chạy thử: liệt kê
    python scripts/cleanup_demo_test_leftovers.py --apply backup.json # sao lưu rồi xoá
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mongo_client import db  # noqa: E402

# Tiền tố tên do script test tạo ra (scripts/*.mjs, scripts/*.py) — KHÔNG khớp tên thật của dữ liệu demo
TEST_NAME = re.compile(r'^\s*(QA[\s_-]|E2E[\s_-]|SSE Test|Audit Test|Test Sweep|QA$)', re.IGNORECASE)
# collection -> các trường chứa tên hiển thị
FIELDS = {
    'employees': ['ho_ten', 'ma_nv'], 'staff': ['name'], 'customers': ['name', 'full_name'],
    'bot_customers': ['name'], 'appointments': ['customer_name'], 'products': ['name'],
    'raw_materials': ['name'], 'production_recipes': ['product', 'name', 'cong_doan'], 'production_output': ['cong_doan', 'ghi_chu'],
    'product_recipes': ['output_name'], 'material_recipes': ['cong_doan', 'product'],
    'hotel_reservations': ['guest_name', 'customer_name'], 'karaoke_reservations': ['customer_name', 'guest_name'],
    'reservations': ['customer_name', 'guest_name'], 'tasks': ['ten_khach'], 'tech_parts': ['name'],
    'promotions': ['name', 'code'], 'expenses': ['description'], 'leave_requests': ['ho_ten'],
    'expense_requests': ['ho_ten'], 'karaoke_rooms': ['name'], 'hotel_rooms': ['name'],
}


def demo_business_ids():
    ids = set()
    for u in db.users.find({'email': {'$regex': r'@bitpawdemo\.com$'}}, {'id': 1, 'business_id': 1, '_id': 0}):
        ids.add(u.get('business_id') or u.get('id'))
    return [i for i in ids if i]


def main():
    apply = '--apply' in sys.argv
    bids = demo_business_ids()
    found = {}
    names = set(db.list_collection_names())
    for coll, fields in FIELDS.items():
        if coll not in names:
            continue
        q = {'business_id': {'$in': bids}, '$or': [{f: {'$regex': TEST_NAME.pattern, '$options': 'i'}} for f in fields]}
        docs = list(db[coll].find(q))
        if docs:
            found[coll] = docs
            sample = ', '.join(sorted({str(next((d.get(f) for f in fields if d.get(f)), '?'))[:40] for d in docs})[:8])
            print(f'{coll:22} {len(docs):4}  {sample}')
    total = sum(len(v) for v in found.values())
    print(f'Tổng: {total} bản ghi test trong {len(bids)} tiệm demo')
    if not apply:
        print('Chạy thử — chưa xoá gì. Thêm --apply <file sao lưu> để xoá.')
        return
    backup = sys.argv[sys.argv.index('--apply') + 1]
    with open(backup, 'w', encoding='utf-8') as f:
        json.dump({c: docs for c, docs in found.items()}, f, ensure_ascii=False, default=str)
    deleted = 0
    for coll, docs in found.items():
        deleted += db[coll].delete_many({'_id': {'$in': [d['_id'] for d in docs]}}).deleted_count
    print(f'Đã sao lưu vào {backup} và xoá {deleted} bản ghi.')


if __name__ == '__main__':
    main()
