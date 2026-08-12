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

# Giai đoạn 4 audit — Event Hook cho AI CRM/Nurture: đẩy sự kiện ORDER_COMPLETED sau mỗi lần
# thanh toán thành công, để 1 worker riêng (vd nurture_scheduler.py mở rộng sau này qua
# XREADGROUP, cùng mẫu consumer.py đang dùng cho ATTENDANCE_STREAM) LISTEN và xử lý bất đồng bộ
# (tính điểm loyalty real-time hơn, gửi tin nhắn cảm ơn/upsell...). Stream RIÊNG với
# ATTENDANCE_STREAM — 2 loại sự kiện có tốc độ phát sinh, người tiêu thụ, và yêu cầu độ tin cậy
# khác nhau, gộp chung sẽ buộc mọi consumer phải lọc bỏ event không liên quan tới mình.
ORDER_EVENTS_STREAM = 'bitpaw:order:events'

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


def push_order_completed_event(event):
    """XADD 1 sự kiện ORDER_COMPLETED vào ORDER_EVENTS_STREAM — dùng cho AI CRM/Nurture phản
    ứng real-time (Giai đoạn 4 audit) sau khi 1 đơn hàng thanh toán thành công.

    KHÔNG gọi API AI/CRM đồng bộ ở đây — chỉ XADD rồi trả về NGAY, một worker riêng (chạy tách
    biệt khỏi luồng checkout, tương tự consumer.py cho ATTENDANCE_STREAM) sẽ tự đọc và xử lý sau.
    maxlen=100000/approximate=True: cùng lý do an toàn vận hành như push_attendance_event() —
    chặn Redis phình vô hạn nếu chưa có worker nào tiêu thụ stream này."""
    r = get_redis_client()
    safe_event = {k: ('' if v is None else v) for k, v in event.items()}
    return r.xadd(ORDER_EVENTS_STREAM, safe_event, maxlen=100000, approximate=True)
