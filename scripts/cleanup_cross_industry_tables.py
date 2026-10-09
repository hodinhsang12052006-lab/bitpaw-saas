"""Dọn bàn ăn rác (db.dining_tables) mà /pos từng tự tạo 200 cái cho BẤT KỲ tiệm nào mở trang đó — kể cả
tiệm Nails, Spa, Khách sạn, Sản xuất... (đã chặn ở app.py + industry_access.py, xem FINDINGS_LOG Pha 14).

Chỉ xoá bàn của tiệm KHÔNG phải F&B (hoặc tiệm/tài khoản đã bị xoá), và chỉ bàn KHÔNG được tham chiếu ở
table_orders / reservations / orders.metadata.table_id. Mặc định chạy thử (không xoá gì).

    python scripts/cleanup_cross_industry_tables.py                      # chạy thử, in số bàn sẽ xoá
    python scripts/cleanup_cross_industry_tables.py --apply backup.json   # sao lưu ra backup.json rồi xoá
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mongo_client import db  # noqa: E402


def industry_of(business_id):
    doc = db.system_settings.find_one({'key': f'business_mode_{business_id}'}, {'value': 1, '_id': 0})
    return ((doc or {}).get('value') or '').strip().lower() or None


def main():
    apply = '--apply' in sys.argv
    backup_path = sys.argv[sys.argv.index('--apply') + 1] if apply else None
    by_business = defaultdict(list)
    for t in db.dining_tables.find({}, {'_id': 0}):
        by_business[t.get('business_id')].append(t)

    plan, keep = [], []
    for bid, tables in by_business.items():
        ind = industry_of(bid)
        owner_exists = db.users.count_documents({'$or': [{'id': bid}, {'business_id': bid}]}) > 0
        if ind == 'fnb' and owner_exists:
            keep.append((bid, ind, len(tables), 'F&B'))
            continue
        ids = [t['id'] for t in tables]
        used = set(db.table_orders.distinct('table_id', {'table_id': {'$in': ids}}))
        used |= set(db.reservations.distinct('table_id', {'table_id': {'$in': ids}}))
        used |= set(db.orders.distinct('metadata.table_id', {'metadata.table_id': {'$in': ids}}))
        junk = [t for t in tables if t['id'] not in used]
        plan.append({'business_id': bid, 'industry': ind or ('(tài khoản đã xoá)' if not owner_exists else None),
                     'tables': len(tables), 'delete': len(junk), 'kept_in_use': len(tables) - len(junk), 'docs': junk})

    for bid, ind, n, why in keep:
        print(f'GIỮ  {str(ind):12} {n:4} bàn  {bid}  ({why})')
    for p in plan:
        print(f"XOÁ  {str(p['industry']):12} {p['delete']:4}/{p['tables']} bàn  {p['business_id']}"
              + (f"  (giữ {p['kept_in_use']} bàn đang có đơn/đặt chỗ)" if p['kept_in_use'] else ''))
    total = sum(p['delete'] for p in plan)
    print(f'Tổng sẽ xoá: {total} bàn')
    if not apply:
        print('Chạy thử — chưa xoá gì. Thêm --apply <file sao lưu> để xoá.')
        return
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump([d for p in plan for d in p['docs']], f, ensure_ascii=False, default=str)
    deleted = 0
    for p in plan:
        ids = [d['id'] for d in p['docs']]
        if ids:
            deleted += db.dining_tables.delete_many({'business_id': p['business_id'], 'id': {'$in': ids}}).deleted_count
    print(f'Đã sao lưu {total} bàn vào {backup_path} và xoá {deleted} bàn.')


if __name__ == '__main__':
    main()
