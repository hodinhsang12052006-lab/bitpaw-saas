"""Chụp / khôi phục trạng thái bàn của 1 tiệm F&B demo quanh 1 lượt test (đơn QR, gọi món tạo đơn bàn + phiếu bếp mà test
không tự dọn -> tiệm demo hiện bàn "Đang phục vụ" và phiếu bếp OVERDUE cho khách xem demo).
    python scripts/_fnb_test_snapshot.py snapshot <email>                 -> in JSON {"ko": id lớn nhất phiếu bếp, "to": ..., "tables": {...}}
    python scripts/_fnb_test_snapshot.py restore <email> '<json snapshot>' -> xoá phiếu bếp/đơn bàn tạo sau snapshot, trả trạng thái bàn
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from mongo_client import db  # noqa: E402

cmd, email = sys.argv[1], sys.argv[2]
assert email.endswith('@bitpawdemo.com'), 'chỉ dùng cho tiệm demo'
bid = db.users.find_one({'email': email})['business_id']


def max_id(coll):
    d = db[coll].find_one({'business_id': bid}, {'id': 1}, sort=[('id', -1)])
    return (d or {}).get('id') or 0


if cmd == 'snapshot':
    print(json.dumps({'ko': max_id('kitchen_orders'), 'to': max_id('table_orders'),
                      'tables': {str(t['id']): t.get('status') for t in db.dining_tables.find({'business_id': bid}, {'id': 1, 'status': 1})},
                      # tồn kho món: mỗi lượt test bán món thật -> trước đây kho demo cạn dần tới khi thanh toán bị chặn "không đủ hàng"
                      'stock': {str(p['id']): p['stock'] for p in db.products.find({'business_id': bid, 'stock': {'$exists': True}}, {'id': 1, 'stock': 1})}}))
else:
    snap = json.loads(sys.argv[3])
    ko = db.kitchen_orders.delete_many({'business_id': bid, 'id': {'$gt': snap['ko']}}).deleted_count
    to = db.table_orders.delete_many({'business_id': bid, 'id': {'$gt': snap['to']}}).deleted_count
    reset = 0
    for tid, st in snap['tables'].items():
        reset += db.dining_tables.update_one({'business_id': bid, 'id': int(tid), 'status': {'$ne': st}}, {'$set': {'status': st}}).modified_count
    stock = 0
    for pid, st in (snap.get('stock') or {}).items():
        stock += db.products.update_one({'business_id': bid, 'id': int(pid), 'stock': {'$ne': st}}, {'$set': {'stock': st}}).modified_count
    print(json.dumps({'xoa_phieu_bep': ko, 'xoa_don_ban': to, 'tra_trang_thai_ban': reset, 'tra_ton_kho': stock}))
