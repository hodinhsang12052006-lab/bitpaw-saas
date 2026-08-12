"""
Nguồn chân lý DUY NHẤT cho việc tạo lịch hẹn (Mã Giai đoạn 4 audit) — trước đây UI đặt lịch công
khai (blueprints/spa_bp.py::create_appointment) VÀ AI Chatbot (ai_function_tools.py::book_appointment)
mỗi bên tự ghi thẳng vào db.appointments theo cách riêng, không bên nào chặn trùng lịch theo đúng
staff_id, dẫn tới 2 khách có thể đặt cùng 1 thợ cùng 1 giờ. Module này KHÔNG import từ app.py (chỉ
phụ thuộc mongo_client.py, giống ai_context_engine.py/tenant_engine.py) để cả app.py (qua
blueprints/spa_bp.py) LẪN ai_function_tools.py đều import được thẳng, không có nguy cơ circular
import.
"""
from datetime import datetime

from mongo_client import db, next_mongo_id


class SlotAlreadyBookedError(Exception):
    """Raise khi staff_id được chỉ định đã có 1 lịch hẹn khác (status != 'cancelled') trùng đúng
    book_time — caller (route Flask/tool AI) bắt exception này để báo khách chọn giờ/thợ khác,
    KHÔNG BAO GIỜ được âm thầm ghi đè hoặc bỏ qua."""


def book_appointment(business_id, customer_info, staff_id, book_time, service_id=None,
                      note=None, source='web', status='pending'):
    """Tạo 1 lịch hẹn — DÙNG CHUNG cho mọi nơi ghi vào db.appointments trong hệ thống.

    Check trùng lịch CHỈ áp dụng khi có staff_id cụ thể (khách chỉ định đúng thợ) — 2 khách đặt
    CÙNG giờ nhưng KHÁC thợ (hoặc chưa chỉ định thợ, staff_id=None) không xung đột với nhau,
    không nên bị chặn oan.

    Tham số:
      - customer_info: dict {'name': str, 'phone': str}
      - book_time: chuỗi ISO 8601 đại diện đúng 1 thời điểm (date+time đã gộp sẵn) — khớp với
        format 'book_time' hiện có trong db.appointments, để /calendar và mọi màn hình đang đọc
        collection này không cần đổi gì.
      - source: 'web' (UI đặt lịch công khai) | 'ai_bot' (AI Chatbot) — để phân biệt nguồn gốc
        khi tra soát/báo cáo, không đổi hành vi ghi.

    Raise SlotAlreadyBookedError nếu trùng lịch. Trả về document lịch hẹn vừa tạo (dict, đã có id).
    """
    if db is None:
        raise RuntimeError("Không có kết nối Database — không thể đặt lịch lúc này.")
    if not book_time:
        raise ValueError("Thiếu book_time — không thể đặt lịch.")

    if staff_id is not None:
        # $ne 'cancelled': lịch đã huỷ không còn chiếm chỗ, thợ được đặt lại đúng khung giờ đó.
        clash = db.appointments.find_one({
            'business_id': business_id,
            'staff_id': staff_id,
            'book_time': book_time,
            'status': {'$ne': 'cancelled'},
        })
        if clash:
            raise SlotAlreadyBookedError(
                f"Nhân viên đã có lịch hẹn khác vào lúc {book_time} — vui lòng chọn giờ khác hoặc thợ khác."
            )

    customer_info = customer_info or {}
    appointment_doc = {
        'id': next_mongo_id('appointments'),
        'business_id': business_id,
        'customer_name': customer_info.get('name') or '',
        'customer_phone': customer_info.get('phone') or '',
        'service_id': service_id,
        'staff_id': staff_id,
        'book_time': book_time,
        'note': note,
        'status': status,
        'source': source,
        'created_at': datetime.now().isoformat(),
    }
    db.appointments.insert_one(appointment_doc)
    return appointment_doc
