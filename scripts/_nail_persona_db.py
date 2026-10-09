"""stdout-JSON helper cho scripts/nail_persona_e2e.mjs — đối soát DB thật (không chỉ tin response API)
và dọn sạch dữ liệu của thợ test sau khi chạy. Dòng JSON luôn là dòng CUỐI của stdout.

    python scripts/_nail_persona_db.py business <email>
    python scripts/_nail_persona_db.py state <business_id> <ma_nv>
    python scripts/_nail_persona_db.py kudo <business_id> <ma_nv>
    python scripts/_nail_persona_db.py cleanup <business_id> <ma_nv> <ho_ten>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mongo_client import db  # noqa: E402


def business(email):
    u = db.users.find_one({'email': email}, {'_id': 0, 'id': 1, 'business_id': 1})
    return {'business_id': (u or {}).get('business_id') or (u or {}).get('id')}


def state(bid, ma_nv):
    cc = list(db.chamcong.find({'business_id': bid, 'ma_nv': ma_nv}, {'_id': 0}))
    return {
        'employee': db.employees.find_one({'business_id': bid, 'ma_nv': ma_nv}, {'_id': 0}),
        'chamcong': [{k: r.get(k) for k in ('id', 'trang_thai', 'ngay_cham', 'so_gio', 'tien_tua', 'tien_tips',
                                            'toa_do', 'anh_checkin', 'ghi_chu')} for r in cc],
        'leave': list(db.leave_requests.find({'business_id': bid, 'ma_nv': ma_nv}, {'_id': 0})),
        'expense': list(db.expense_requests.find({'business_id': bid, 'ma_nv': ma_nv}, {'_id': 0})),
    }


def kudo(bid, ma_nv):
    e = db.employees.find_one({'business_id': bid, 'ma_nv': ma_nv}, {'_id': 0, 'diem_kudo': 1})
    return {'diem_kudo': (e or {}).get('diem_kudo', 0)}


def appts(bid, name):
    items = list(db.appointments.find({'business_id': bid, 'customer_name': name}, {'_id': 0, 'staff_id': 1, 'book_time': 1, 'status': 1}))
    return {'count': len(items), 'items': items}


def cleanup(bid, ma_nv, ho_ten):
    out = {}
    out['chamcong'] = db.chamcong.delete_many({'business_id': bid, 'ma_nv': ma_nv}).deleted_count
    out['leave'] = db.leave_requests.delete_many({'business_id': bid, 'ma_nv': ma_nv}).deleted_count
    out['expense_requests'] = db.expense_requests.delete_many({'business_id': bid, 'ma_nv': ma_nv}).deleted_count
    out['expenses'] = db.expenses.delete_many({'business_id': bid, 'description': {'$regex': f'^\\[Hoàn ứng {ho_ten}\\]'}}).deleted_count
    out['shift_swaps'] = db.shift_swaps.delete_many({'business_id': bid, '$or': [{'ma_nv_xin': ma_nv}, {'ma_nv_nhan': ma_nv}]}).deleted_count
    # Đơn POS gán cho thợ test (bước chủ tiệm bán hàng) — xoá cả order/order_items/transactions
    order_ids = sorted({oi['order_id'] for oi in db.order_items.find({'business_id': bid, 'ma_nv': ma_nv}, {'order_id': 1})})
    out['orders'] = db.orders.delete_many({'business_id': bid, 'id': {'$in': order_ids}}).deleted_count
    out['order_items'] = db.order_items.delete_many({'business_id': bid, 'order_id': {'$in': order_ids}}).deleted_count
    out['transactions'] = db.transactions.delete_many({'business_id': bid, 'order_id': {'$in': order_ids}}).deleted_count
    out['appointments'] = db.appointments.delete_many({'business_id': bid, 'customer_name': {'$regex': f'^QA Persona Khách.*{ma_nv}$'}}).deleted_count
    out['bot_customers'] = db.bot_customers.delete_many({'business_id': bid, 'name': {'$regex': f'^QA Persona Khách.*{ma_nv}$'}}).deleted_count
    out['employee'] = db.employees.delete_many({'business_id': bid, 'ma_nv': ma_nv}).deleted_count
    # Ảnh check-in / báo cáo công việc (GridFS 'media', tên file chứa mã NV)
    files = list(db['media.files'].find({'business_id': bid, 'filename': {'$regex': f'_{ma_nv}_'}}, {'_id': 1}))
    ids = [f['_id'] for f in files]
    db['media.chunks'].delete_many({'files_id': {'$in': ids}})
    out['media_files'] = db['media.files'].delete_many({'_id': {'$in': ids}}).deleted_count
    return out


if __name__ == '__main__':
    mode, args = sys.argv[1], sys.argv[2:]
    fn = {'business': business, 'state': state, 'kudo': kudo, 'appts': appts, 'cleanup': cleanup}[mode]
    print(json.dumps(fn(*args), ensure_ascii=False, default=str))
