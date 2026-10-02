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
    'chamcong': [[BID, ('ma_nv', 1)], [BID, ('id', 1)]],
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
    print(f'Xong — tạo mới {created} index.')


if __name__ == '__main__':
    main()
