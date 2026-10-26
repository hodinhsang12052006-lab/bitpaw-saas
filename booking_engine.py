"""
Nguồn chân lý DUY NHẤT cho việc tạo lịch hẹn (Mã Giai đoạn 4 audit) — trước đây UI đặt lịch công
khai (blueprints/spa_bp.py::create_appointment) VÀ AI Chatbot (ai_function_tools.py::book_appointment)
mỗi bên tự ghi thẳng vào db.appointments theo cách riêng, không bên nào chặn trùng lịch theo đúng
staff_id, dẫn tới 2 khách có thể đặt cùng 1 thợ cùng 1 giờ. Module này KHÔNG import từ app.py (chỉ
phụ thuộc mongo_client.py/email_service.py, giống ai_context_engine.py/tenant_engine.py) để cả
app.py (qua blueprints/spa_bp.py) LẪN ai_function_tools.py đều import được thẳng, không có nguy cơ
circular import.

BUG THẬT đã vá (audit sau khi thêm tính năng "báo chủ tiệm qua email khi có lịch hẹn mới"): logic
báo email từng đặt trong blueprints/spa_bp.py::create_appointment() — CHỈ chạy khi khách đặt qua
form QR công khai, KHÔNG chạy khi khách đặt qua AI Bot chat (ai_function_tools.py gọi THẲNG
book_appointment() ở đây, không đi qua create_appointment()). Kết quả: lịch hẹn AI Bot tạo ra rơi
vào im lặng, chủ tiệm không hề biết — đúng loại lỗi "2 nơi làm giống nhau nhưng lệch nhau" mà
chính module này được tạo ra để tránh (xem đoạn trên). Dời logic báo email vào NGAY TRONG
book_appointment() — nguồn chân lý duy nhất — để MỌI caller (hiện tại và tương lai) đều tự động
có, không cần từng nơi tự nhớ gọi thêm.
"""
from datetime import datetime
from html import escape as _html_escape

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from mongo_client import db, next_mongo_id
from email_service import EmailService

# Email báo chủ tiệm: tối đa bấy nhiêu thư/tiệm/ngày. Cả hệ thống gửi qua 1 tài khoản Gmail (~500 thư/ngày cho MỌI
# tiệm); kiểm thử tải: 1 tiệm nhận 1.000 lượt đặt = 1.000 thư -> hết hạn mức của cả hệ thống, thư quên mật khẩu/
# thông báo của các tiệm khác cũng không đi được. Quá mức thì lịch vẫn lưu bình thường, chủ tiệm xem trên Lịch.
OWNER_BOOKING_EMAILS_PER_DAY = 30


class SlotAlreadyBookedError(Exception):
    """Raise khi staff_id được chỉ định đã có 1 lịch hẹn khác (status != 'cancelled') trùng đúng
    book_time — caller (route Flask/tool AI) bắt exception này để báo khách chọn giờ/thợ khác,
    KHÔNG BAO GIỜ được âm thầm ghi đè hoặc bỏ qua."""


def book_appointment(business_id, customer_info, staff_id, book_time, service_id=None,
                      note=None, source='web', status=None, enforce_rules=None):
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
    book_time = normalize_book_time(book_time)
    if staff_id in ('', None):
        staff_id = None  # "thợ nào cũng được" — không giữ chỗ riêng thợ nào
    else:
        staff_id = str(staff_id)[:64]

    # Luật đặt lịch của tiệm (booking_rules.py): giờ mở cửa, đặt trước tối thiểu/tối đa, sức chứa theo số thợ có
    # ca, thợ có ca/đang rảnh. Áp cho khách tự đặt (form công khai + trợ lý AI); chủ tiệm tự xếp tay thì không chặn.
    if enforce_rules is None:
        enforce_rules = source in ('web', 'ai_bot')
    if status is None:  # khách tự đặt: xác nhận ngay nếu tiệm bật "tự xác nhận" (mặc định), không thì chờ duyệt
        status = 'pending'
        if source in ('web', 'ai_bot'):
            import booking_rules
            status = 'confirmed' if booking_rules.get_rules(business_id).get('auto_confirm', True) else 'pending'
    if enforce_rules:
        import booking_rules
        try:
            booking_rules.check_slot(business_id, datetime.fromisoformat(book_time), service_id, staff_id)
        except booking_rules.SlotUnavailable as e:
            err = SlotAlreadyBookedError(' / '.join(booking_rules.REASON_TEXT.get(e.reason, (e.reason, e.reason))))
            err.reason = e.reason
            raise err from e

    if staff_id is not None:
        # $ne 'cancelled': lịch đã huỷ không còn chiếm chỗ, thợ được đặt lại đúng khung giờ đó.
        clash = db.appointments.find_one({
            'business_id': business_id,
            'staff_id': staff_id,
            'book_time': book_time,
            'status': {'$ne': 'cancelled'},
        })
        if clash:
            raise _staff_busy_error(book_time)

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
    if staff_id is not None:
        # Khoá chỗ NGUYÊN TỬ: index unique (business_id, slot_key). Bước find_one ở trên KHÔNG đủ — kiểm thử tải: 50 khách
        # cùng bấm đặt 1 thợ 1 giờ thì nhiều người cùng thấy "còn trống" trước khi ai kịp ghi, và cùng được nhận lịch.
        # Huỷ lịch thì gỡ slot_key (api_appointment_update_status) để giờ đó mở lại.
        appointment_doc['slot_key'] = slot_key(staff_id, book_time)
    try:
        db.appointments.insert_one(appointment_doc)
    except DuplicateKeyError:
        raise _staff_busy_error(book_time)
    appointment_doc.pop('_id', None)
    _notify_owner_new_appointment(appointment_doc)
    return appointment_doc


def _staff_busy_error(book_time):
    """Thợ đã có lịch đúng giờ này (khách khác vừa giữ chỗ trước, kể cả khi 2 người bấm cùng lúc). Câu 'EN / VI' giống
    booking_rules.REASON_TEXT -> /create_appointment tách theo ngôn ngữ của tiệm; trước đây chỉ có tiếng Việt nên khách
    tiệm AU/US đặt trùng đúng lúc người khác vừa đặt thấy thông báo tiếng Việt."""
    t, d = book_time[11:16], book_time[:10]
    err = SlotAlreadyBookedError(
        f"That team member is already booked at {t} on {d} — please pick another time or team member. / "
        f"Nhân viên đã có lịch hẹn khác lúc {t} ngày {d[8:10]}/{d[5:7]}/{d[:4]} — vui lòng chọn giờ khác hoặc thợ khác.")
    err.reason = 'staff_busy'
    return err


def slot_key(staff_id, book_time):
    return f"{staff_id}|{book_time}"


def normalize_book_time(book_time):
    """1 thời điểm = 1 chuỗi duy nhất 'YYYY-MM-DDTHH:MM' — '2026-10-20T10:00', '2026-10-20T10:00:00' hay
    '2026-10-20 10:00' trước đây là 3 chuỗi khác nhau nên chặn trùng (so khớp chuỗi) không bắt được nhau."""
    try:
        return datetime.fromisoformat(str(book_time).strip().replace('Z', '')).strftime('%Y-%m-%dT%H:%M')
    except ValueError:
        raise ValueError("Giờ hẹn không hợp lệ.")


def _owner_email_quota_ok(business_id):
    """Đếm thư báo lịch hẹn đã gửi hôm nay cho tiệm này (1 lệnh $inc nguyên tử) — False khi vượt mức/ngày."""
    try:
        doc = db.email_quota.find_one_and_update(
            {'_id': f"booking_owner|{business_id}|{datetime.now().strftime('%Y-%m-%d')}"},
            {'$inc': {'n': 1}, '$setOnInsert': {'business_id': business_id, 'created_at': datetime.now().isoformat()}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        return (doc or {}).get('n', 1) <= OWNER_BOOKING_EMAILS_PER_DAY
    except Exception:
        return True


def _notify_owner_new_appointment(appointment):
    """Báo NGƯỜI TIỆM qua email ngay khi có lịch hẹn mới — bất kể tạo qua form QR công khai hay
    AI Bot chat (gọi ngay trong book_appointment() để KHÔNG bên caller nào cần tự nhớ gọi thêm,
    xem giải thích đầy đủ ở đầu file). Zalo OA không gửi được cho khách lần đầu chưa từng chat với
    OA, và hệ thống chưa tích hợp nhà cung cấp SMS nào, nên báo chủ tiệm (đã có địa chỉ email xác
    thực lúc đăng ký) là kênh duy nhất THẬT SỰ gửi được. Best-effort tuyệt đối: lỗi gửi email
    KHÔNG BAO GIỜ được làm hỏng việc đặt lịch đã ghi DB thành công — gọi SAU insert_one()."""
    try:
        if not _owner_email_quota_ok(appointment['business_id']):
            return
        owner = db.users.find_one(
            {'business_id': appointment['business_id'], 'role': 'admin'}, {'email': 1, '_id': 0}
        )
        owner_email = (owner or {}).get('email')
        if not owner_email:
            return
        service_name = ''
        if appointment.get('service_id'):
            try:
                svc = db.products.find_one({'id': appointment['service_id']}, {'name': 1, '_id': 0})
                service_name = (svc or {}).get('name') or ''
            except Exception:
                service_name = ''
        try:
            book_time_display = datetime.fromisoformat(appointment['book_time']).strftime('%H:%M, %d/%m/%Y')
        except (TypeError, ValueError):
            book_time_display = appointment['book_time']
        # Escape TOÀN BỘ dữ liệu khách tự nhập (tên/SĐT/ghi chú) trước khi nhét vào HTML email —
        # input công khai không xác thực, thiếu escape thì 1 khách gõ tên/ghi chú chứa thẻ HTML sẽ
        # chèn được HTML tuỳ ý vào email thật của chủ tiệm.
        safe_name = _html_escape(appointment['customer_name'] or '')
        safe_phone = _html_escape(appointment['customer_phone'] or '')
        safe_service = _html_escape(service_name)
        safe_note = _html_escape(appointment.get('note') or '') or '(không có)'
        body = f"""
            <div style="font-family:sans-serif;max-width:480px;margin:0 auto;">
                <h2 style="color:#06b6d4;">🔔 Lịch hẹn mới{' qua AI Bot' if appointment.get('source') == 'ai_bot' else ' qua cổng đặt lịch online'}</h2>
                <table style="width:100%;border-collapse:collapse;font-size:14px;">
                    <tr><td style="padding:6px 0;color:#666;">Khách hàng</td><td style="padding:6px 0;font-weight:bold;">{safe_name}</td></tr>
                    <tr><td style="padding:6px 0;color:#666;">Số điện thoại</td><td style="padding:6px 0;font-weight:bold;">{safe_phone}</td></tr>
                    <tr><td style="padding:6px 0;color:#666;">Dịch vụ</td><td style="padding:6px 0;font-weight:bold;">{safe_service}</td></tr>
                    <tr><td style="padding:6px 0;color:#666;">Giờ hẹn</td><td style="padding:6px 0;font-weight:bold;color:#06b6d4;">{book_time_display}</td></tr>
                    <tr><td style="padding:6px 0;color:#666;vertical-align:top;">Ghi chú</td><td style="padding:6px 0;">{safe_note}</td></tr>
                </table>
                <p style="color:#999;font-size:12px;margin-top:16px;">Vui lòng gọi lại xác nhận với khách sớm nhất có thể — lịch hẹn đang ở trạng thái "pending" chờ tiệm duyệt trên Lịch (Calendar).</p>
            </div>
        """
        ok, msg = EmailService.send_email(
            owner_email, f"🔔 Lịch hẹn mới: {safe_name} — {book_time_display}", body
        )
        if not ok:
            print(f"[book_appointment] Gửi email báo lịch hẹn mới thất bại (business_id={appointment['business_id']}): {msg}")
    except Exception as e:
        print(f"[book_appointment] Lỗi báo lịch hẹn mới qua email (không ảnh hưởng lịch hẹn đã tạo): {str(e)}")
