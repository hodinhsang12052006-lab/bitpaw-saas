# Dọn đơn đặt bàn / phòng karaoke / phòng khách sạn do các bài audit tạo ("QA Audit ..."), để tiệm demo không còn
# đơn thử khi chủ tiệm mở /reservations. Gọi từ finalize() của fnb/karaoke/hotel_industry_master_audit.mjs.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mongo_client import db  # noqa: E402

n = 0
for coll, field in (('table_reservations', 'customer_name'), ('karaoke_room_reservations', 'customer_name'), ('hotel_reservations', 'guest_name')):
    n += db[coll].delete_many({field: {'$regex': '^QA Audit '}}).deleted_count
print('removed audit reservations:', n)
