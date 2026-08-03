"""
Hàng đợi trung gian (Mã 1.2 audit) giữa API check-in/check-out chấm công GPS (ghi cực nhanh,
KHÔNG chờ Mongo) và consumer.py (worker riêng, ghi tuần tự vào MongoDB db.attendance).

Dùng Redis STREAMS (không phải Pub/Sub) vì Streams lưu message trên đĩa (persist) và có
Consumer Group (XREADGROUP/XACK/PEL) -> "at-least-once": consumer chết giữa chừng không làm
mất event, message chưa XACK vẫn nằm trong Pending Entries List chờ được xử lý lại. Pub/Sub thì
subscriber offline lúc bắn message là mất vĩnh viễn -> không dùng được cho dữ liệu chấm công
(ảnh hưởng lương thợ).
"""
import os

import redis

ATTENDANCE_STREAM = 'bitpaw:attendance:events'
ATTENDANCE_GROUP = 'attendance_writers'

_redis_client = None


def get_redis_client():
    """Tái sử dụng 1 connection pool duy nhất cho cả process (Flask request nào cũng gọi hàm
    này) thay vì redis.from_url() mỗi request -> tránh mở/đóng TCP connection liên tục lúc
    10.000 thợ check-in cùng lúc 9h sáng."""
    global _redis_client
    if _redis_client is None:
        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        _redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


def push_attendance_event(event):
    """XADD 1 sự kiện check-in/check-out, trả về NGAY (không chờ Mongo ghi xong).

    - maxlen=100000, approximate=True: chặn Redis phình vô hạn nếu consumer.py bị đứng lâu
      ngày không ai để ý (an toàn vận hành, không phải giới hạn nghiệp vụ) — Redis tự xoá bớt
      entry cũ nhất theo lô cho rẻ (approximate) thay vì trim chính xác từng entry (tốn CPU).
    - Field value của Redis Stream chỉ nhận str/bytes/int/float, không nhận None -> ép None
      thành chuỗi rỗng trước khi XADD, consumer.py sẽ tự diễn giải lại chuỗi rỗng = thiếu dữ liệu.
    """
    r = get_redis_client()
    safe_event = {k: ('' if v is None else v) for k, v in event.items()}
    return r.xadd(ATTENDANCE_STREAM, safe_event, maxlen=100000, approximate=True)
