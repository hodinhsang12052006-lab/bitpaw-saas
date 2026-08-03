"""
Background Worker RIÊNG (Mã 1.2 audit) — không chạy chung process với Flask/gunicorn. Đọc
Redis Stream 'bitpaw:attendance:events' theo lô (batch) qua Consumer Group, ghi TUẦN TỰ vào
MongoDB db.attendance, rồi mới XACK. Nhờ ghi tuần tự (1 process, 1 vòng lặp) nên có thể an
toàn kiểm tra "thợ này đang có ca mở chưa" trước khi ghi — điều mà 10.000 request Flask đồng
thời ghi thẳng DB không đảm bảo được (race condition), đây chính là lý do tách API ra khỏi DB
bằng hàng đợi thay vì cố gắng làm DB ghi nhanh hơn.

CÁCH CHẠY (1 hoặc NHIỀU process song song đều an toàn — xem ghi chú Consumer Group bên dưới):
    python consumer.py

Production: chạy dưới supervisor/systemd/pm2 (hoặc container riêng) với restart=always, vì
đây là 1 script chạy vô hạn (vòng lặp while True), không phải request-response như Flask.
"""
import os
import sys
import time
import traceback
from datetime import datetime

import redis

from redis_queue import get_redis_client, ATTENDANCE_STREAM, ATTENDANCE_GROUP
from mongo_client import db, next_mongo_id

CONSUMER_NAME = f"consumer-{os.getpid()}"
BATCH_SIZE = 200          # đọc tối đa 200 event/lượt XREADGROUP
BLOCK_MS = 5000           # nếu stream rỗng, chờ tối đa 5s rồi mới lặp lại (không busy-loop CPU)
CLAIM_IDLE_MS = 60_000    # coi 1 message là "consumer cũ đã chết" nếu bị treo pending > 60s
MAX_DELIVERIES = 5        # quá số lần này vẫn lỗi -> đẩy sang dead-letter, ngưng retry vô hạn


def _ensure_group(r):
    """Tạo Consumer Group nếu chưa có. mkstream=True: tự tạo luôn Stream nếu API chưa XADD
    lần nào (vd consumer.py khởi động trước khi có bất kỳ lượt check-in nào)."""
    try:
        r.xgroup_create(ATTENDANCE_STREAM, ATTENDANCE_GROUP, id='0', mkstream=True)
    except redis.ResponseError as e:
        if 'BUSYGROUP' not in str(e):
            raise  # lỗi khác BUSYGROUP (group đã tồn tại) là lỗi thật, không được nuốt


def _to_float_or_none(v):
    if v in (None, '', 'None'):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _process_event(fields):
    """Ghi 1 sự kiện check-in/check-out vào db.attendance. Idempotent theo nghĩa nghiệp vụ:
    checkin khi đã có ca mở -> bỏ qua (không tạo ca trùng); checkout khi không có ca mở nào ->
    bỏ qua (không có gì để đóng). Nhờ vậy 1 message bị XCLAIM xử lý lại lần 2 (do consumer cũ
    chết trước khi kịp XACK) không tạo ra dữ liệu trùng."""
    event_type = fields.get('type')
    staff_id = int(fields['staff_id'])
    business_id = fields['business_id']
    ts = fields.get('timestamp') or datetime.now().isoformat()

    if event_type == 'checkin':
        already_open = db.attendance.find_one({
            'staff_id': staff_id, 'business_id': business_id, 'clock_out': None,
        })
        if already_open:
            print(f"[consumer] Bỏ qua checkin trùng (đã có ca mở) staff_id={staff_id} business_id={business_id}")
            return
        db.attendance.insert_one({
            'id': next_mongo_id('attendance'),
            'staff_id': staff_id,
            'business_id': business_id,
            'clock_in': ts,
            'created_at': ts,
            'clock_out': None,
            'latitude_in': _to_float_or_none(fields.get('latitude')),
            'longitude_in': _to_float_or_none(fields.get('longitude')),
            'status': 'Present',
            'note': fields.get('note') or '',
        })

    elif event_type == 'checkout':
        open_shift = db.attendance.find_one(
            {'staff_id': staff_id, 'business_id': business_id, 'clock_out': None},
            sort=[('id', -1)],
        )
        if not open_shift:
            print(f"[consumer] Bỏ qua checkout không khớp ca mở nào staff_id={staff_id} business_id={business_id}")
            return
        db.attendance.update_one(
            {'_id': open_shift['_id']},
            {'$set': {
                'clock_out': ts,
                'latitude_out': _to_float_or_none(fields.get('latitude')),
                'longitude_out': _to_float_or_none(fields.get('longitude')),
                'status': 'Completed',
            }},
        )
    else:
        print(f"[consumer] Bỏ qua event không rõ type={event_type!r}")


def _deliveries_of(r, msg_id):
    """Số lần message này đã được giao (XREADGROUP lần đầu + mỗi lần XCLAIM/XAUTOCLAIM đều
    cộng dồn) — Redis tự đếm sẵn, đọc qua XPENDING thay vì tự quản lý counter riêng."""
    pending = r.xpending_range(ATTENDANCE_STREAM, ATTENDANCE_GROUP, min=msg_id, max=msg_id, count=1)
    if not pending:
        return 1
    return pending[0]['times_delivered']


def _dead_letter(r, msg_id, fields, error):
    """Quá MAX_DELIVERIES lần vẫn lỗi -> ghi lại vào Mongo để người vận hành xem tay, rồi XACK
    để message không kẹt vĩnh viễn trong PEL (retry vô hạn 1 event luôn lỗi sẽ chặn cả batch
    phía sau nó tồn lại trong pending list mãi mãi)."""
    try:
        db.attendance_dead_letter.insert_one({
            'stream_msg_id': msg_id, 'fields': fields, 'error': str(error),
            'failed_at': datetime.now().isoformat(),
        })
    except Exception as e:
        print(f"[consumer] LỖI cả ghi dead-letter cho message {msg_id}: {e}")
    r.xack(ATTENDANCE_STREAM, ATTENDANCE_GROUP, msg_id)
    print(f"[consumer] Message {msg_id} vượt quá {MAX_DELIVERIES} lần retry -> chuyển dead-letter, đã XACK.")


def _handle_message(r, msg_id, fields):
    try:
        _process_event(fields)
        r.xack(ATTENDANCE_STREAM, ATTENDANCE_GROUP, msg_id)
    except Exception as e:
        print(f"[consumer] Lỗi xử lý message {msg_id}: {e}\n{traceback.format_exc()}")
        if _deliveries_of(r, msg_id) >= MAX_DELIVERIES:
            _dead_letter(r, msg_id, fields, e)
        # Chưa đủ MAX_DELIVERIES -> KHÔNG xack, để message ở lại PEL, sẽ được _reclaim_stale()
        # (hoặc chính consumer này ở vòng sau) nhận lại và thử ghi lần nữa.


def _reclaim_stale(r):
    """Nhận lại message của 1 consumer đã CHẾT (crash, mất mạng...) mà chưa kịp XACK, sau khi
    đã bị treo pending quá CLAIM_IDLE_MS. Chạy mỗi vòng loop chính -> nhiều process consumer.py
    chạy song song đều tự dọn hộ nhau, không cần biết consumer nào đã chết."""
    try:
        _next_start, claimed, _deleted = r.xautoclaim(
            ATTENDANCE_STREAM, ATTENDANCE_GROUP, CONSUMER_NAME,
            min_idle_time=CLAIM_IDLE_MS, start='0-0', count=BATCH_SIZE,
        )
        for msg_id, fields in claimed:
            _handle_message(r, msg_id, fields)
    except Exception as e:
        print(f"[consumer] Lỗi _reclaim_stale: {e}")


def run():
    r = get_redis_client()
    _ensure_group(r)
    print(f"[consumer] {CONSUMER_NAME} bắt đầu đọc stream '{ATTENDANCE_STREAM}' (group={ATTENDANCE_GROUP})...")

    while True:
        try:
            # '>' = chỉ lấy message CHƯA từng giao cho consumer nào trong group này (message
            # cũ bị treo/chưa ack được xử lý riêng ở _reclaim_stale, không lẫn vào đây).
            resp = r.xreadgroup(
                ATTENDANCE_GROUP, CONSUMER_NAME,
                {ATTENDANCE_STREAM: '>'}, count=BATCH_SIZE, block=BLOCK_MS,
            )
            if resp:
                for _stream_name, messages in resp:
                    for msg_id, fields in messages:
                        _handle_message(r, msg_id, fields)

            _reclaim_stale(r)

        except redis.exceptions.ConnectionError as e:
            print(f"[consumer] Mất kết nối Redis: {e} — thử lại sau 3s...")
            time.sleep(3)
        except Exception as e:
            print(f"[consumer] Lỗi vòng lặp chính (không crash worker): {e}\n{traceback.format_exc()}")
            time.sleep(2)


if __name__ == '__main__':
    run()
