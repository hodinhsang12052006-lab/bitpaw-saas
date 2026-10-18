"""Tạo index MongoDB cho các truy vấn nóng (idempotent — chạy lại bao nhiêu lần cũng được, chỉ thêm
index còn thiếu, KHÔNG xoá/đổi dữ liệu).

Trước đây code KHÔNG tạo index ở đâu cả (vài index hiện có được tạo tay 1 lần) -> DB mới/khôi phục
backup/collection mới đều chạy collection scan; khi số tenant/dữ liệu tăng, mọi truy vấn theo
business_id chậm tuyến tính và là nguyên nhân phổ biến nhất khiến SaaS "sập" khi đông người dùng.
Danh sách dưới đây lập từ chính các mẫu truy vấn trong app.py/blueprints (db.<coll>.find({...})).

Chạy:  python scripts/ensure_indexes.py      (dùng MONGO_URI trong .env giống app)
Không gắn vào lúc khởi động app: trên Vercel mỗi cold start sẽ tốn thêm ~30 round-trip DB.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mongo_client import db  # noqa: E402

BID = ('business_id', 1)
INDEXES = {
    # ngay_cham: Bảng lương / phiếu lương lọc theo tháng bằng $in các ngày DD/MM/YYYY (đo thật tiệm 60 thợ)
    'chamcong': [[BID, ('ma_nv', 1)], [BID, ('id', 1)], [BID, ('ngay_cham', 1)]],
    # webhook Square tra đơn theo metadata.square_checkout_id (index cũ đặt nhầm ở square_checkout_id)
    'orders': [[('metadata.square_checkout_id', 1)]],
    'transactions': [[BID, ('id', 1)]],
    'user_logs': [[BID]],
    'table_orders': [[BID, ('table_id', 1)], [BID, ('id', 1)]],
    'kitchen_orders': [[BID]],
    'expenses': [[BID, ('id', 1)]],
    'dining_tables': [[('qr_token', 1)]],
    'users': [[('id', 1)]],
    'businesses': [[('id', 1)]],
    'system_settings': [[('key', 1)]],
    'business_memberships': [[('owner_user_id', 1), BID]],
    'bot_customers': [[('id', 1)]],
    'expense_requests': [[BID, ('status', 1)]],
    'leave_requests': [[BID, ('status', 1)]],
    'production_output': [[BID, ('id', 1)]],
    'karaoke_rooms': [[BID, ('id', 1)]],
    'hotel_rooms': [[BID, ('id', 1)]],
    'hotel_reservations': [[BID, ('id', 1)]],
    'hotel_room_charges': [[BID, ('id', 1)]],
    'promotions': [[BID, ('id', 1)]],
    'tasks': [[BID, ('trang_thai', 1)], [BID, ('id', 1)]],
    'appointments': [[BID, ('id', 1)]],
    'employees': [[BID, ('ma_nv', 1)]],
    'chat_presence': [[BID, ('room', 1)]],
    'chat_messages': [[BID, ('room', 1)]],
    'table_reservations': [[BID]],
    'cskh_requests': [[('status', 1)]],
}

# Index UNIQUE (chặn ghi trùng ngay trong DB — kiểm thử tải 18/10/2026: kiểm tra-rồi-ghi trong code không đủ khi nhiều
# request tới cùng lúc). Partial: chỉ áp cho bản ghi có trường đó, dữ liệu cũ không bị ảnh hưởng.
UNIQUE_INDEXES = [
    # 1 thợ + 1 giờ = 1 lịch còn hiệu lực (booking_engine.slot_key; huỷ lịch thì gỡ slot_key)
    ('appointments', [BID, ('slot_key', 1)], {'slot_key': {'$type': 'string'}}),
    # 1 SĐT = 1 hồ sơ khách mỗi tiệm (2 bill cùng lúc của khách mới từng tạo 2 hồ sơ)
    ('customers', [BID, ('phone', 1)], {'phone': {'$gt': ''}}),
    # 1 lần bấm thanh toán = 1 đơn, kể cả khi mạng chập chờn và POS gửi lại
    ('orders', [BID, ('metadata.client_request_id', 1)], {'metadata.client_request_id': {'$type': 'string'}}),
]


def main():
    created = 0
    for coll, specs in INDEXES.items():
        existing = {tuple(v['key']) for v in db[coll].index_information().values()}
        for keys in specs:
            if tuple(keys) in existing:
                continue
            name = db[coll].create_index(keys, background=True)
            created += 1
            print(f'+ {coll}: {name}')
    for coll, keys, partial in UNIQUE_INDEXES:
        info = db[coll].index_information().values()
        if any(tuple(v['key']) == tuple(keys) and v.get('unique') for v in info):
            continue
        for v in list(db[coll].index_information().items()):
            if tuple(v[1]['key']) == tuple(keys):  # index thường cùng khoá -> thay bằng bản unique
                db[coll].drop_index(v[0])
        name = db[coll].create_index(keys, unique=True, partialFilterExpression=partial, background=True)
        created += 1
        print(f'+ {coll}: {name} (unique)')
    print(f'Xong — tạo mới {created} index.')


if __name__ == '__main__':
    main()
