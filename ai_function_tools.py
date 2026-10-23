"""
Function Calling cho AI Bot (DeepSeek). Trước đây bot chỉ SINH VĂN BẢN ("Dạ em đã đặt lịch
cho chị rồi ạ") mà không ghi gì vào Database thật — khách tưởng đã đặt lịch nhưng thực tế
không có gì được lưu ("ảo giác"). Module này định nghĩa các tool THẬT mà DeepSeek được phép
gọi, được thực thi thật trong Python, và trả kết quả THẬT về cho AI để nó trả lời khách đúng
với những gì thực sự đã xảy ra — không còn tự bịa.

2 bộ công cụ (Pha 27 — theo cách các trợ lý AI đang hiệu quả nhất như Intercom Fin / Fresha làm: AI chỉ nói điều
công cụ xác nhận):
  - BOOKING_TOOLS (trợ lý đặt lịch, khách CUỐI của tiệm): xem giờ trống, đặt lịch (chọn thợ, nhiều người),
    xem/huỷ/dời lịch của chính khách, xem gói liệu trình, chuyển nhân viên thật.
  - SALES_TOOLS (tư vấn phần mềm BitPaw cho chủ tiệm): lưu thông tin liên hệ để đội BitPaw gọi lại, báo giá đúng
    bảng giá.

LỊCH SỬ: book_appointment() từng ghi vào SQLite riêng của Desktop App — nay ghi thẳng MongoDB `db.appointments`
qua booking_engine (nguồn chân lý duy nhất, áp luật đặt lịch của tiệm — booking_rules.py).
"""
import json
import re
from datetime import date, datetime, timedelta

from mongo_client import db, next_mongo_id
from booking_engine import book_appointment as _book_appointment_shared, SlotAlreadyBookedError
import booking_rules


def _fn(name, desc, props, required=()):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props, "required": list(required)}}}


BOOKING_TOOLS = [
    _fn("check_availability",
        "Xem các giờ CÒN TRỐNG thật của tiệm trong 1 ngày (theo giờ mở cửa, thời lượng dịch vụ, số thợ có ca, lịch đã kín). "
        "LUÔN gọi trước khi đề xuất hoặc hứa 1 giờ cụ thể. Nếu ngày đó hết chỗ, kết quả kèm vài ngày gần nhất còn chỗ.",
        {"date": {"type": "string", "description": "Ngày YYYY-MM-DD (giờ địa phương của tiệm)."},
         "time": {"type": "string", "description": "Giờ khách muốn HH:MM (nếu khách nói giờ cụ thể) — kết quả cho biết ĐÚNG giờ đó còn trống không + các giờ gần nhất."},
         "service_id": {"type": "string", "description": "service_id khách muốn (nếu đã biết) — để tính đúng thời lượng."},
         "staff_name": {"type": "string", "description": "Tên thợ khách muốn (nếu khách chỉ định)."},
         "guests": {"type": "integer", "description": "Số người đi cùng lúc (mặc định 1)."}},
        ["date"]),
    _fn("book_appointment",
        "Đặt lịch hẹn THẬT. CHỈ gọi khi khách đã xác nhận rõ ràng dịch vụ + ngày giờ (và tên). Không tự bịa service_id/giờ. "
        "Nếu giờ không còn, kết quả báo lý do + giờ gợi ý — hãy đưa khách chọn lại.",
        {"service_id": {"type": "string", "description": "ID dịch vụ (đúng danh sách BOOKABLE SERVICES)."},
         "appointment_time": {"type": "string", "description": "Giờ hẹn ISO 8601 giờ địa phương, vd 2026-08-01T14:00:00."},
         "customer_name": {"type": "string", "description": "Tên khách."},
         "staff_name": {"type": "string", "description": "Tên thợ khách chỉ định (bỏ trống = thợ nào cũng được)."},
         "guests": {"type": "integer", "description": "Tổng số người cùng làm cùng giờ (1-6), mặc định 1."}},
        ["service_id", "appointment_time"]),
    _fn("my_appointments", "Liệt kê lịch hẹn sắp tới của CHÍNH khách đang chat (theo số điện thoại của cuộc chat).", {}),
    _fn("cancel_appointment", "Huỷ 1 lịch hẹn của CHÍNH khách đang chat. Lấy appointment_id từ my_appointments; hỏi khách xác nhận trước khi huỷ.",
        {"appointment_id": {"type": "integer"}}, ["appointment_id"]),
    _fn("reschedule_appointment", "Dời 1 lịch hẹn của CHÍNH khách sang giờ mới (kiểm tra giờ trống tự động). Hỏi khách xác nhận giờ mới trước.",
        {"appointment_id": {"type": "integer"}, "new_time": {"type": "string", "description": "ISO 8601 giờ địa phương."}},
        ["appointment_id", "new_time"]),
    _fn("my_packages", "Xem gói liệu trình nhiều buổi khách đang có (còn bao nhiêu buổi, hạn dùng).", {}),
    _fn("ask_team",
        "Gửi 1 câu hỏi khách hỏi mà dữ liệu không có (giảm giá/ưu đãi, voucher chưa ghi, bãi đỗ, dị ứng, yêu cầu đặc biệt) cho nhân viên "
        "trả lời SAU trong khung chat này. AI VẪN tiếp tục giúp khách (đặt lịch, hỏi giá...). Dùng thay cho handoff khi khách không đòi gặp người.",
        {"question": {"type": "string", "description": "Câu hỏi của khách, 1 câu, cho nhân viên đọc."}},
        ["question"]),
    _fn("handoff_to_staff",
        "Chuyển hẳn cuộc chat cho NHÂN VIÊN THẬT và tạm dừng AI: CHỈ khi khách phàn nàn về dịch vụ đã làm, đòi gặp quản lý/người thật, "
        "đòi hoàn tiền/làm lại miễn phí, hoặc đang bức xúc. Câu hỏi thông tin thiếu dữ liệu -> dùng ask_team, KHÔNG dùng hàm này.",
        {"reason": {"type": "string", "description": "Tóm tắt 1 câu khách cần gì (cho nhân viên đọc)."},
         "urgent": {"type": "boolean"}},
        ["reason"]),
]

SALES_TOOLS = [
    _fn("capture_lead",
        "Lưu thông tin liên hệ để đội BitPaw gọi lại / demo. Gọi khi khách đồng ý để lại SĐT hoặc email. "
        "Cần ít nhất 1 cách liên hệ (phone hoặc email).",
        {"name": {"type": "string"}, "phone": {"type": "string"}, "email": {"type": "string"},
         "industry": {"type": "string", "description": "nail, spa, fnb, retail, hotel, karaoke, production, technical, office"},
         "team_size": {"type": "integer"}, "country": {"type": "string"},
         "notes": {"type": "string", "description": "Khách cần gì / đang dùng gì / khi nào muốn bắt đầu."}}),
]

# Giữ tên cũ cho code cũ còn import TOOL_SCHEMAS (= bộ đặt lịch)
TOOL_SCHEMAS = BOOKING_TOOLS


class ToolExecutionError(Exception):
    """Luôn được bắt ở execute_tool_call() và biến thành 1 tool-result báo lỗi rõ ràng gửi lại cho DeepSeek — KHÔNG
    nuốt lỗi, để AI không bịa với khách là đã thành công."""


def _phone_of(customer_id):
    return customer_id.split(':', 1)[1] if customer_id and ':' in str(customer_id) else str(customer_id or '')


def _require_customer(customer_id):
    if not customer_id or not _phone_of(customer_id):
        raise ToolExecutionError("Chưa có số điện thoại của khách trong cuộc chat — hãy xin số điện thoại trước.")


def _service(business_id, service_id):
    cands = []
    if isinstance(service_id, (int, str)) and str(service_id).strip().isdigit():
        cands.append(int(str(service_id).strip()))
    if isinstance(service_id, (int, str)):
        cands.append(service_id)
    for c in cands:
        doc = db.products.find_one({'id': c, 'business_id': business_id}, {'_id': 0})
        if doc:
            return doc
    if isinstance(service_id, str) and service_id.strip():
        return db.products.find_one({'business_id': business_id,
                                     'name': {'$regex': f"^{re.escape(service_id.strip())}$", '$options': 'i'}}, {'_id': 0})
    return None


def _parse_day(s):
    try:
        return datetime.strptime(str(s)[:10], '%Y-%m-%d').date()
    except ValueError:
        raise ToolExecutionError(f"Ngày '{s}' không đúng định dạng YYYY-MM-DD.")


def check_availability(business_id, customer_id, date=None, service_id=None, staff_name=None, guests=1, time=None):
    day = _parse_day(date)
    svc = _service(business_id, service_id) if service_id else None
    staff = booking_rules.find_staff(business_id, staff_name) if staff_name else None
    if staff_name and not staff:
        names = sorted(booking_rules._staff_names(business_id).values())
        return {"success": False, "error": f"Không tìm thấy thợ tên '{staff_name}'.", "team": names[:20]}
    guests = max(1, min(int(guests or 1), 6))
    rules = booking_rules.get_rules(business_id)
    hrs = booking_rules.hours_on(rules, day)
    want = None
    if time and re.match(r'^\d{1,2}:\d{2}', str(time).strip()):
        hh, mm = str(time).strip()[:5].split(':')
        want = int(hh) * 60 + int(mm[:2])
    if want is None:
        slots = booking_rules.available_slots(business_id, day, svc and svc['id'], staff and staff[0], guests=guests)
    else:  # khách hỏi đúng 1 giờ: trả lời đúng giờ đó + các giờ GẦN NHẤT (danh sách rải đều cả ngày từng bỏ sót đúng giờ khách hỏi)
        full = booking_rules.available_slots(business_id, day, svc and svc['id'], staff and staff[0], limit=200, guests=guests)
        mins = lambda t: int(t[:2]) * 60 + int(t[3:5])  # noqa: E731
        slots = sorted(sorted(full, key=lambda t: abs(mins(t) - want))[:6])
    out = {"success": True, "date": day.isoformat(), "weekday": day.strftime('%A'),
           "open": bool(hrs), "opening_hours": (f"{hrs[0] // 60:02d}:{hrs[0] % 60:02d}-{hrs[1] // 60:02d}:{hrs[1] % 60:02d}" if hrs else "closed"),
           "service": svc and svc['name'], "duration_minutes": booking_rules.duration_of(rules, svc and svc['id']),
           "staff": staff and staff[1], "available_start_times": slots}
    if want is not None:
        t = f"{want // 60:02d}:{want % 60:02d}"
        try:
            booking_rules.check_slot(business_id, datetime.combine(day, datetime.min.time()) + timedelta(minutes=want),
                                     svc and svc['id'], staff and staff[0], rules=rules, guests=guests)
            out["requested_time"] = {"time": t, "free": True}
        except booking_rules.SlotUnavailable as e:
            out["requested_time"] = {"time": t, "free": False, "why": booking_rules.REASON_TEXT.get(e.reason, (e.reason,))[0]}
    if not slots:
        nxt = []
        for k in range(1, 15):
            d = day + timedelta(days=k)
            s = booking_rules.available_slots(business_id, d, svc and svc['id'], staff and staff[0], limit=4, guests=guests)
            if s:
                nxt.append({"date": d.isoformat(), "weekday": d.strftime('%A'), "first_times": s})
            if len(nxt) >= 3:
                break
        out["next_available"] = nxt
    return out


def book_appointment(business_id, customer_id, service_id=None, appointment_time=None, customer_name=None, staff_name=None, guests=1):
    """Ghi lịch hẹn THẬT (qua booking_engine — áp luật đặt lịch của tiệm). Không bao giờ trả "thành công" khi DB không ghi."""
    if not all([business_id, service_id, appointment_time]):
        raise ToolExecutionError("Thiếu service_id hoặc appointment_time — không thể đặt lịch.")
    _require_customer(customer_id)
    try:
        when = datetime.fromisoformat(str(appointment_time)[:19])
    except ValueError as e:
        raise ToolExecutionError(f"appointment_time '{appointment_time}' không đúng ISO 8601.") from e
    svc = _service(business_id, service_id)
    if not svc:
        raise ToolExecutionError(f"Không tìm thấy dịch vụ '{service_id}' của tiệm này — dùng đúng service_id trong danh sách.")
    staff = None
    if staff_name:
        staff = booking_rules.find_staff(business_id, staff_name)
        if not staff:
            raise ToolExecutionError(f"Không tìm thấy thợ tên '{staff_name}' — hỏi lại khách hoặc đặt 'thợ nào cũng được'.")
    guests = max(1, min(int(guests or 1), 6))
    phone = _phone_of(customer_id)
    book_time = when.strftime('%Y-%m-%dT%H:%M')
    cust = db.bot_customers.find_one({'id': customer_id}, {'full_name': 1, '_id': 0}) or {}
    given = customer_name.strip()[:80] if isinstance(customer_name, str) and customer_name.strip() else ''
    name = given or cust.get('full_name') or f"Customer {phone[-4:]}"

    # Chống đặt TRÙNG (khách nói "ok đặt giúp em" 2 lần): cùng khách + dịch vụ + giờ còn hiệu lực -> trả lại lịch cũ
    existing = db.appointments.find_one({'business_id': business_id, 'customer_phone': phone, 'service_id': svc['id'],
                                         'book_time': book_time, 'status': {'$nin': ['cancelled', 'canceled']}}, {'_id': 0, 'id': 1})
    if existing:
        if given:
            db.appointments.update_one({'id': existing['id'], 'business_id': business_id}, {'$set': {'customer_name': given}})
        st = (db.appointments.find_one({'id': existing['id']}, {'_id': 0, 'status': 1}) or {}).get('status') or 'pending'
        return {"success": True, "already_booked": True, "appointment_id": existing['id'], "service_name": svc['name'],
                "appointment_time": book_time, "status": st}
    # 1 người không thể ngồi 2 dịch vụ CÙNG LÚC (đo thật: khách gọi thêm pedi, AI đặt trùng 15:00 với mani). Cùng khách,
    # khác dịch vụ, chồng giờ -> trả về giờ nối tiếp ngay sau lịch trước (trừ đặt nhóm: guests > 1 là người khác nhau).
    if guests == 1:
        rules = booking_rules.get_rules(business_id)
        start = when
        end = when + timedelta(minutes=booking_rules.duration_of(rules, svc['id']))
        for other in db.appointments.find({'business_id': business_id, 'customer_phone': phone, 'status': {'$nin': ['cancelled', 'canceled']},
                                           'book_time': {'$gte': when.strftime('%Y-%m-%d'), '$lt': (when + timedelta(days=1)).strftime('%Y-%m-%d')}},
                                          {'_id': 0, 'book_time': 1, 'service_id': 1}):
            o_start = datetime.fromisoformat(str(other['book_time'])[:16])
            o_end = o_start + timedelta(minutes=booking_rules.duration_of(rules, other.get('service_id')))
            if o_start < end and start < o_end:
                return {"success": False, "reason": "customer_overlap",
                        "message": "This customer already has a service at that time — one person can't have two services at once.",
                        "suggest_back_to_back_start": o_end.strftime('%Y-%m-%dT%H:%M')}
    try:  # kiểm cả nhóm trước khi ghi (1 lệnh check cho đủ số người)
        booking_rules.check_slot(business_id, when, svc['id'], staff and staff[0], guests=guests)
    except booking_rules.SlotUnavailable as e:
        alt = booking_rules.available_slots(business_id, when.date(), svc['id'], staff and staff[0], limit=6, guests=guests)
        return {"success": False, "reason": e.reason, "message": booking_rules.REASON_TEXT.get(e.reason, (e.reason,))[0],
                "other_times_same_day": alt}
    ids, status = [], 'pending'
    try:
        for g in range(guests):
            appt = _book_appointment_shared(
                business_id=business_id,
                customer_info={'name': name if g == 0 else f"{name} (guest {g + 1})", 'phone': phone},
                staff_id=staff[0] if (staff and g == 0) else None, book_time=book_time, service_id=svc['id'],
                note=(f"Group of {guests}" if guests > 1 else None), source='ai_bot', enforce_rules=False)
            ids.append(appt['id'])
            status = appt.get('status') or status
    except SlotAlreadyBookedError as e:
        if ids:
            db.appointments.update_many({'id': {'$in': ids}, 'business_id': business_id}, {'$set': {'status': 'cancelled'}, '$unset': {'slot_key': ''}})
        return {"success": False, "reason": getattr(e, 'reason', 'unavailable'), "message": str(e)}
    except Exception as e:
        raise ToolExecutionError(f"Lỗi ghi Database khi đặt lịch: {e}") from e
    return {"success": True, "appointment_ids": ids, "appointment_id": ids[0], "service_name": svc['name'],
            "appointment_time": book_time, "staff": staff and staff[1], "guests": guests, "status": status,
            "say": ("Booked and confirmed." if status == 'confirmed' else
                    "Request received — the business confirms it (do NOT say confirmed).")}


def _own_appt(business_id, customer_id, appointment_id):
    _require_customer(customer_id)
    try:
        aid = int(appointment_id)
    except (TypeError, ValueError):
        raise ToolExecutionError("appointment_id không hợp lệ.")
    a = db.appointments.find_one({'id': aid, 'business_id': business_id, 'customer_phone': _phone_of(customer_id)}, {'_id': 0})
    if not a:
        raise ToolExecutionError("Không tìm thấy lịch này trong các lịch của khách (chỉ xem/sửa được lịch của chính số điện thoại đang chat).")
    return a


def my_appointments(business_id, customer_id):
    _require_customer(customer_id)
    now = booking_rules.local_now(business_id).strftime('%Y-%m-%dT%H:%M')
    names = booking_rules._staff_names(business_id)
    out = []
    for a in db.appointments.find({'business_id': business_id, 'customer_phone': _phone_of(customer_id), 'book_time': {'$gte': now},
                                   'status': {'$nin': ['cancelled', 'canceled']}}, {'_id': 0}).sort('book_time', 1).limit(10):
        svc = db.products.find_one({'id': a.get('service_id'), 'business_id': business_id}, {'_id': 0, 'name': 1}) or {}
        out.append({"appointment_id": a['id'], "service": svc.get('name') or a.get('service_name'), "time": str(a['book_time'])[:16],
                    "staff": names.get(str(a.get('staff_id'))), "status": a.get('status')})
    return {"success": True, "upcoming": out}


def cancel_appointment(business_id, customer_id, appointment_id=None):
    a = _own_appt(business_id, customer_id, appointment_id)
    if a.get('status') in ('cancelled', 'canceled'):
        return {"success": True, "already_cancelled": True, "appointment_id": a['id']}
    db.appointments.update_one({'id': a['id'], 'business_id': business_id},
                               {'$set': {'status': 'cancelled', 'cancelled_by': 'customer_ai_chat', 'cancelled_at': datetime.now().isoformat()},
                                '$unset': {'slot_key': ''}})
    _note_for_staff(business_id, customer_id, f"Khách tự huỷ lịch #{a['id']} ({str(a['book_time'])[:16]}) qua chat AI.")
    return {"success": True, "appointment_id": a['id'], "cancelled_time": str(a['book_time'])[:16]}


def reschedule_appointment(business_id, customer_id, appointment_id=None, new_time=None):
    a = _own_appt(business_id, customer_id, appointment_id)
    try:
        when = datetime.fromisoformat(str(new_time)[:19])
    except (ValueError, TypeError):
        raise ToolExecutionError("new_time không đúng ISO 8601.")
    try:
        booking_rules.check_slot(business_id, when, a.get('service_id'), a.get('staff_id'), exclude_id=a['id'])
    except booking_rules.SlotUnavailable as e:
        alt = booking_rules.available_slots(business_id, when.date(), a.get('service_id'), a.get('staff_id'), limit=6, exclude_id=a['id'])
        return {"success": False, "reason": e.reason, "message": booking_rules.REASON_TEXT.get(e.reason, (e.reason,))[0], "other_times_same_day": alt}
    new_bt = when.strftime('%Y-%m-%dT%H:%M')
    upd = {'book_time': new_bt, 'rescheduled_from': a['book_time'], 'rescheduled_at': datetime.now().isoformat()}
    unset = {}
    if a.get('staff_id'):
        upd['slot_key'] = f"{a['staff_id']}|{new_bt}"
    else:
        unset['slot_key'] = ''
    db.appointments.update_one({'id': a['id'], 'business_id': business_id}, {'$set': upd, **({'$unset': unset} if unset else {})})
    _note_for_staff(business_id, customer_id, f"Khách dời lịch #{a['id']} từ {str(a['book_time'])[:16]} sang {new_bt} qua chat AI.")
    return {"success": True, "appointment_id": a['id'], "old_time": str(a['book_time'])[:16], "new_time": new_bt}


def my_packages(business_id, customer_id):
    _require_customer(customer_id)
    import service_packages
    rows = service_packages.active_for(business_id, _phone_of(customer_id))
    return {"success": True, "packages": [{"name": r['name'], "sessions_left": r['sessions_left'], "sessions_total": r['sessions_total'],
                                           "expires": (r.get('expires_at') or '')[:10] or None} for r in rows]}


def _note_for_staff(business_id, customer_id, text, sender='system'):
    """Ghi 1 dòng vào hộp thư AI Bot của chủ tiệm (hiện ngay trong /ai_bot qua luồng realtime)."""
    try:
        db.bot_messages.insert_one({'id': next_mongo_id('bot_messages'), 'customer_id': customer_id, 'business_id': business_id,
                                    'sender_type': sender, 'content': text[:1000], 'created_at': datetime.now().isoformat()})
    except Exception:
        pass


def reply_expectation(business_id, vi=False):
    """Câu hẹn giờ nhân viên trả lời — THẬT theo giờ mở cửa (như Intercom báo "team thường trả lời trong..."), kèm SĐT tiệm nếu có."""
    try:
        st = booking_rules.open_status(business_id)
        phone = booking_rules.business_phone(business_id)
    except Exception:
        st, phone = {'open_now': True}, ''
    if st.get('open_now'):
        en, v = "The team is in today and will reply right here in this chat.", "Tiệm đang mở cửa, nhân viên sẽ trả lời ngay trong khung chat này."
    elif st.get('next_open'):
        nxt = st['next_open']
        nxt_vi = nxt.replace('today', 'hôm nay').replace('tomorrow', 'ngày mai')
        en, v = (f"We're closed right now — the team will reply here when we open ({nxt}).",
                 f"Tiệm đang đóng cửa — nhân viên sẽ trả lời tại đây khi tiệm mở cửa ({nxt_vi}).")
    else:
        en, v = "The team will reply right here in this chat.", "Nhân viên sẽ trả lời ngay trong khung chat này."
    if phone:
        en += f" If it's urgent, call {phone}."
        v += f" Nếu gấp, gọi {phone}."
    return v if vi else en


def _alert_owner(business_id, customer_id, text, kind_key):
    """Báo chủ tiệm qua email (+ hộp thư AI Bot đã có) để có NGƯỜI thật trả lời — trước đây chỉ ghi 1 dòng trong
    /ai_bot, chủ không mở trang đó thì khách chờ mãi. Tối đa 1 thư / khách / giờ."""
    try:
        import messaging
        owner = db.users.find_one({'business_id': business_id, 'role': {'$in': ['admin', 'owner']}}, {'_id': 0, 'email': 1}) or {}
        if not owner.get('email'):
            return False
        st = messaging.get_settings(business_id)
        hour = datetime.now().strftime('%Y%m%d%H')
        body = (f"{text}\n\nCustomer: {_phone_of(customer_id)}\nReply in BitPaw → AI Bot inbox."
                if st.get('language') != 'vi' else
                f"{text}\n\nKhách: {_phone_of(customer_id)}\nTrả lời trong BitPaw → mục AI Bot.")
        subject = ('Khách cần nhân viên trả lời' if st.get('language') == 'vi' else 'A customer is waiting for a reply')
        mid = messaging.queue(business_id, 'email', owner['email'], body, 'staff_alert', subject=subject,
                              dedupe_key=f"staffalert:{customer_id}:{kind_key}:{hour}")
        if mid:
            messaging.deliver(mid)
        return bool(mid)
    except Exception as e:
        print(f"[ai tools] alert owner: {e}")
        return False


def _is_vi_chat(customer_id):
    last = db.bot_messages.find_one({'customer_id': customer_id, 'sender_type': 'customer'}, {'_id': 0, 'content': 1}, sort=[('_id', -1)]) or {}
    return bool(re.search(r'[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]', last.get('content') or '', re.I))


def ask_team(business_id, customer_id, question=None):
    _require_customer(customer_id)
    q = str(question or '').strip()[:300]
    if not q:
        raise ToolExecutionError("Thiếu câu hỏi cho nhân viên.")
    prev = db.bot_customers.find_one({'id': customer_id}, {'_id': 0, 'asked_team_at': 1}) or {}
    if prev.get('asked_team_at') and prev['asked_team_at'] >= (datetime.now() - timedelta(minutes=30)).isoformat():
        _note_for_staff(business_id, customer_id, f"❓ Khách hỏi thêm: {q}")
        return {"success": True, "asked_team": True, "already_told_customer": True,
                "tell_customer": "Added to the same note for the team. Don't repeat the reply-time message — just say it's noted."}
    db.bot_customers.update_one({'id': customer_id}, {'$set': {'needs_human': True, 'handoff_reason': q,
                                                               'asked_team_at': datetime.now().isoformat()}})
    _note_for_staff(business_id, customer_id, f"❓ Khách hỏi (AI chưa có dữ liệu): {q}")
    _alert_owner(business_id, customer_id, f"Question from a chat customer: {q}", 'ask')
    return {"success": True, "asked_team": True, "ai_keeps_helping": True,
            "tell_customer": reply_expectation(business_id, _is_vi_chat(customer_id)) +
            " Meanwhile you can keep chatting with me (booking, prices, times)."}


def handoff_to_staff(business_id, customer_id, reason=None, urgent=False):
    _require_customer(customer_id)
    db.bot_customers.update_one({'id': customer_id}, {'$set': {'ai_paused': True, 'needs_human': True, 'handoff_reason': str(reason or '')[:300],
                                                               'handoff_at': datetime.now().isoformat(), 'handoff_urgent': bool(urgent),
                                                               'handoff_by_ai': True, 'hold_notice_at': datetime.now().isoformat()}},
                                upsert=False)
    _note_for_staff(business_id, customer_id, f"{'🔴 ' if urgent else ''}Khách cần nhân viên: {str(reason or '')[:300]}")
    _alert_owner(business_id, customer_id, f"{'URGENT — ' if urgent else ''}A chat customer needs a person: {str(reason or '')[:300]}", 'handoff')
    return {"success": True, "handed_off": True,
            "tell_customer": reply_expectation(business_id, _is_vi_chat(customer_id)),
            "note": "The team now owns this issue. Until a person replies you may still answer simple factual questions, but never decide the issue."}


def capture_lead(business_id, customer_id, name=None, phone=None, email=None, industry=None, team_size=None, country=None, notes=None):
    phone = re.sub(r'[^\d+]', '', str(phone or ''))[:20]
    email = str(email or '').strip()[:120]
    if len(re.sub(r'\D', '', phone)) < 8 and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        raise ToolExecutionError("Cần số điện thoại (ít nhất 8 số) hoặc email hợp lệ để đội BitPaw liên hệ lại.")
    msg = '; '.join(x for x in [f"Industry: {industry}" if industry else '', f"Team: {team_size}" if team_size else '',
                                f"Country: {country}" if country else '', f"Email: {email}" if email else '',
                                f"Notes: {str(notes)[:600]}" if notes else '', 'Source: AI sales chat'] if x)
    since = (datetime.now() - timedelta(hours=24)).isoformat()
    ors = ([{'email': email}] if email else []) + ([{'phone': phone}] if len(re.sub(r'\D', '', phone)) >= 8 else [])
    dup = db.cskh_requests.find_one({'source': 'ai_sales_chat', 'created_at': {'$gte': since}, '$or': ors}, {'_id': 0, 'id': 1}) if ors else None
    if dup:
        upd = {'message': msg, 'updated_at': datetime.now().isoformat()}
        for k, v in (('name', str(name or '').strip()[:100]), ('phone', phone), ('email', email), ('industry', industry),
                     ('team_size', team_size), ('country', country)):
            if v:
                upd[k] = v
        db.cskh_requests.update_one({'id': dup['id']}, {'$set': upd})
        return {"success": True, "lead_id": dup['id'], "updated_existing": True,
                "next_step": "Already saved — details updated. The BitPaw team will contact them within 1 business day."}
    lead_id = next_mongo_id('cskh_requests')
    db.cskh_requests.insert_one({'id': lead_id, 'name': str(name or '').strip()[:100] or 'Website visitor', 'phone': phone,
                                 'email': email, 'message': msg, 'status': 'pending', 'source': 'ai_sales_chat',
                                 'industry': industry, 'team_size': team_size, 'country': country,
                                 'created_at': datetime.now().isoformat()})
    return {"success": True, "lead_id": lead_id, "next_step": "The BitPaw team will contact them within 1 business day."}


TOOL_DISPATCH = {
    "check_availability": check_availability, "book_appointment": book_appointment, "my_appointments": my_appointments,
    "cancel_appointment": cancel_appointment, "reschedule_appointment": reschedule_appointment, "my_packages": my_packages,
    "handoff_to_staff": handoff_to_staff, "capture_lead": capture_lead, "ask_team": ask_team,
}


def execute_tool_call(tool_call, business_id, customer_id, allowed=None):
    """Thực thi 1 tool_call thô của DeepSeek -> (tool_call_id, json). Bắt TOÀN BỘ lỗi: 1 tool lỗi không được làm sập
    cả luồng chat; AI nhận lỗi trung thực để nói thật với khách. `allowed`: chỉ cho gọi tool thuộc bộ của persona."""
    function_name = tool_call.get("function", {}).get("name")
    raw_args = tool_call.get("function", {}).get("arguments") or "{}"
    tool_call_id = tool_call.get("id")
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        return tool_call_id, json.dumps({"success": False, "error": f"Tham số không phải JSON hợp lệ: {e}"}, ensure_ascii=False)
    handler = TOOL_DISPATCH.get(function_name)
    if handler is None or (allowed is not None and function_name not in allowed):
        return tool_call_id, json.dumps({"success": False, "error": f"Công cụ '{function_name}' không dùng được ở đây."}, ensure_ascii=False)
    try:
        result = handler(business_id=business_id, customer_id=customer_id, **args)
        return tool_call_id, json.dumps(result, ensure_ascii=False, default=str)
    except ToolExecutionError as e:
        return tool_call_id, json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except TypeError as e:
        return tool_call_id, json.dumps({"success": False, "error": f"Tham số không hợp lệ cho '{function_name}': {e}"}, ensure_ascii=False)
    except Exception as e:  # lỗi bất ngờ: báo thật cho AI, không làm gãy phản hồi
        return tool_call_id, json.dumps({"success": False, "error": f"Lỗi hệ thống khi chạy '{function_name}': {str(e)[:200]}"}, ensure_ascii=False)
