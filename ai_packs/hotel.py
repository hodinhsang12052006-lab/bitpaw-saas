"""
Gói đặt phòng KHÁCH SẠN (room-night) cho trợ lý AI lễ tân — xem phòng trống theo loại phòng + ngày nhận/trả, báo giá
thật (giá/đêm × số đêm, tiền của khách sạn), tạo yêu cầu đặt phòng (giữ phòng thật, 'pending' trừ khi chủ bật tự xác
nhận), xem / huỷ (theo chính sách) / đổi ngày đặt phòng của CHÍNH khách đang chat.

Logic dùng chung với form công khai /hotel/reserve và màn nhân viên /hotel/reservations: reservations_hotel.py
(db.hotel_rooms + db.hotel_reservations; giữ phòng-đêm nguyên tử qua db.hotel_room_nights).

Hợp đồng gói (ai_packs/__init__.py): INDUSTRIES, RESOURCE, TOOLS, MANAGE_TOOLS, PROMPT_RULES, facts(), execute();
lỗi / từ chối -> ai_packs.PackError(câu cho AI nói lại với khách).
"""
import re
from datetime import datetime, timedelta

import ai_packs
import reservations_hotel as rh
from mongo_client import db

INDUSTRIES = ('hotel',)
RESOURCE = 'room_night'

MAX_LIVE_AI_BOOKINGS_PER_GUEST = 3   # quá số phòng này -> đặt đoàn, nhân viên xử lý (chặn 1 chat giữ hết phòng)
# Cùng 1 MẠNG (IP băm của chat web, ctx.client_key): khách xoá mã trình duyệt + gõ SĐT mới mỗi lần thì giới hạn theo khách ở trên
# luôn = 0 -> 1 người giữ được gần hết phòng. Mạng nội bộ / máy dev không có khoá (không áp).
MAX_LIVE_AI_BOOKINGS_PER_NETWORK = 6
MAX_AI_BOOKINGS_PER_HOUR = 30        # mỗi khách sạn; quá mức -> dừng đặt qua chat, chuyển nhân viên
_PLATFORM_CHANNELS = ('messenger', 'instagram', 'whatsapp', 'zalo', 'viber', 'sms')
_EMAIL_RE = re.compile(r'^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$')


def _fn(name, desc, props, required=()):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props,
                                                            "required": list(required)}}}


_DATE = {"type": "string", "description": "YYYY-MM-DD, the hotel's local date."}

TOOLS = [
    _fn("hotel_check_availability",
        "Live room availability and price for a stay. ALWAYS call before quoting a rate or promising a room. Returns each "
        "room type with rooms left, max guests per room, the nightly rate and the total for all nights (hotel currency). "
        "If the dates are full it also returns nearby dates that are free.",
        {"checkin_date": _DATE, "checkout_date": _DATE,
         "guests": {"type": "integer", "description": "Guests staying in ONE room (default 1)."},
         "room_type": {"type": "string", "description": "Room type the guest asked for (optional; omit to see all types)."}},
        ["checkin_date", "checkout_date"]),
    _fn("hotel_create_booking",
        "Create the real booking for ONE room after the guest agreed to the room type, dates and total. Needs the guest's "
        "full name and mobile number. Status 'pending' = request the hotel still confirms; 'confirmed' = booked.",
        {"checkin_date": _DATE, "checkout_date": _DATE,
         "guests": {"type": "integer", "description": "Guests in this room."},
         "room_type": {"type": "string", "description": "Exact room type from hotel_check_availability."},
         "guest_name": {"type": "string", "description": "Guest's full name."},
         "phone": {"type": "string", "description": "Guest's mobile number (may be omitted on SMS/WhatsApp)."},
         "email": {"type": "string", "description": "Optional email."},
         "arrival_time": {"type": "string", "description": "Optional estimated arrival time HH:MM (24h, local)."},
         "special_requests": {"type": "string", "description": "Optional requests (late arrival, high floor, cot...). Passed to the hotel, not guaranteed."},
         "another_room": {"type": "boolean", "description": "true only when the guest wants an ADDITIONAL room on top of one already booked in this chat."}},
        ["checkin_date", "checkout_date", "guests", "room_type", "guest_name"]),
    _fn("hotel_my_bookings",
        "List upcoming bookings that belong to this chat (made in this chat, or under the verified phone on SMS/WhatsApp). "
        "If it refuses for security, relay its message and reveal nothing about any booking.", {}),
    _fn("hotel_cancel_booking",
        "Cancel one of this guest's bookings per the hotel's policy. Read back the booking and get a clear yes first, "
        "then call with customer_confirmed=true.",
        {"booking_id": {"type": "integer"},
         "customer_confirmed": {"type": "boolean", "description": "true only after the guest clearly confirmed cancelling this booking."}},
        ["booking_id", "customer_confirmed"]),
    _fn("hotel_change_dates",
        "Move one of this guest's bookings to new dates or change the number of guests. Call FIRST without "
        "customer_confirmed: it checks live availability for the new dates (the guest's own booking does not count as "
        "taken) and returns the exact new total. Tell the guest, get a clear yes, then call again with "
        "customer_confirmed=true and quoted_total. Keeps the room if free, otherwise another room of the same type.",
        {"booking_id": {"type": "integer"}, "new_checkin_date": _DATE, "new_checkout_date": _DATE,
         "guests": {"type": "integer", "description": "New number of guests (optional)."},
         "customer_confirmed": {"type": "boolean", "description": "true only after the guest clearly confirmed the change."},
         "quoted_total": {"type": "string", "description": "REQUIRED with customer_confirmed=true: the new_total the first "
                                                          "call returned, which the guest agreed to."}},
        ["booking_id", "new_checkin_date", "new_checkout_date", "customer_confirmed"]),
]

MANAGE_TOOLS = {'hotel_my_bookings', 'hotel_cancel_booking', 'hotel_change_dates'}

PROMPT_RULES = {
    'en': (
        "HOTEL STAYS (rooms by the night):\n"
        "- Before quoting a rate or promising a room, call hotel_check_availability with check-in and check-out dates "
        "(YYYY-MM-DD, hotel local) and the number of guests. Quote only the room types, nightly rates and totals it returns. "
        "Never invent rooms, views, breakfast, discounts, upgrades or availability.\n"
        "- To book: agree the room type, dates, guests and total; get the guest's full name and mobile number (email, arrival "
        "time and special requests are optional); then call hotel_create_booking. One booking = one room; for a bigger party "
        "book extra rooms with another_room=true (up to 3 rooms per chat) or pass a group request to the team with ask_team.\n"
        "- Status 'pending' means the request is in and the hotel will confirm it — never call it confirmed. 'confirmed' means "
        "booked. Special requests are passed to the hotel, never guaranteed.\n"
        "- Deposits, payment, invoices, refunds, discounts, early check-in or late check-out: use ask_team, never promise them.\n"
        "- Existing bookings only through hotel_my_bookings / hotel_change_dates / hotel_cancel_booking. Read the booking back "
        "and get a clear yes before changing or cancelling. For a change, first call hotel_change_dates without "
        "customer_confirmed: it checks the new dates (the guest's own booking is not counted as taken) and returns the exact "
        "new total to quote; after the guest's yes, call it again with customer_confirmed=true and quoted_total = that total. "
        "If a tool refuses, say what it says and reveal nothing else."),
    'vi': (
        "LƯU TRÚ KHÁCH SẠN (phòng tính theo đêm):\n"
        "- Trước khi báo giá hay hứa phòng, gọi hotel_check_availability với ngày nhận phòng, ngày trả phòng (YYYY-MM-DD, "
        "giờ địa phương của khách sạn) và số khách. Chỉ báo đúng loại phòng, giá/đêm và tổng tiền công cụ trả về. Không tự bịa "
        "phòng, view, bữa sáng, giảm giá, nâng hạng hay phòng trống.\n"
        "- Đặt phòng: thống nhất loại phòng, ngày, số khách và tổng tiền; xin họ tên đầy đủ và số điện thoại của khách (email, "
        "giờ đến dự kiến, yêu cầu đặc biệt là tuỳ chọn); rồi gọi hotel_create_booking. 1 lần đặt = 1 phòng; đoàn đông hơn thì "
        "đặt thêm phòng với another_room=true (tối đa 3 phòng mỗi cuộc chat) hoặc chuyển yêu cầu đặt đoàn cho nhân viên bằng ask_team.\n"
        "- Trạng thái 'pending' = đã nhận yêu cầu, khách sạn sẽ xác nhận — không bao giờ nói là đã xác nhận. 'confirmed' = đã "
        "đặt xong. Yêu cầu đặc biệt chỉ chuyển cho khách sạn, không hứa chắc.\n"
        "- Đặt cọc, thanh toán, hoá đơn, hoàn tiền, giảm giá, nhận phòng sớm/trả phòng muộn: dùng ask_team, không tự hứa.\n"
        "- Đặt phòng đã có chỉ xem/sửa qua hotel_my_bookings / hotel_change_dates / hotel_cancel_booking. Đọc lại đặt phòng và "
        "chờ khách đồng ý rõ ràng trước khi đổi hoặc huỷ. Muốn đổi: gọi hotel_change_dates trước, không kèm "
        "customer_confirmed — công cụ tự kiểm ngày mới (không tính đặt phòng của chính khách là bận) và trả đúng tổng tiền mới "
        "để báo khách; khách đồng ý rồi thì gọi lại với customer_confirmed=true và quoted_total = đúng tổng tiền đó. Công cụ "
        "từ chối thì nói đúng ý nó, không tiết lộ gì thêm."),
}


# ---------------------------------------------------------------- tiện ích
def _refuse(message):
    err = getattr(ai_packs, 'PackError', None)
    if err is None:  # chưa có registry (không xảy ra khi đã tích hợp)
        raise RuntimeError(message)
    raise err(message)


def _local_now(business_id, now_local=None):
    if isinstance(now_local, datetime):
        return now_local.replace(tzinfo=None) if now_local.tzinfo else now_local
    try:
        import booking_rules
        return booking_rules.local_now(business_id)
    except Exception:
        return datetime.now()


class _Ctx:
    def __init__(self, ctx):
        c = ctx if isinstance(ctx, dict) else {}
        self.business_id = c.get('business_id')
        self.customer_id = c.get('customer_id') or None
        self.channel = str(c.get('channel') or '').strip().lower()
        self.phone = rh.clean_phone(c.get('phone')) or None
        if self.phone and not rh.phone_ok(self.phone):
            self.phone = None
        self.token_hash = c.get('chat_token_hash') or None
        self.contact_phone = c.get('contact_phone') or None   # SĐT khách gõ (chưa xác minh): chỉ gắn mã trình duyệt với chat này
        self.client_key = c.get('client_key') or None          # mạng của chat web: chỉ để giới hạn, không là bằng chứng
        self.country = str(c.get('country') or '').upper() or None   # thiếu thì lấy theo hồ sơ khách sạn (_country)
        self.lang = 'vi' if c.get('lang') == 'vi' else 'en'
        self.now = _local_now(self.business_id, c.get('now_local'))
        self.today = self.now.date()
        self.customer_name = c.get('customer_name')
        # Hội thoại nền tảng ("<tiệm>:<kênh>:<id do nền tảng ký>") mới là bằng chứng; chat web "<tiệm>:<SĐT tự gõ>" thì không.
        self.platform = (self.channel in _PLATFORM_CHANNELS and bool(self.customer_id)
                         and str(self.customer_id).startswith(f"{self.business_id}:{self.channel}:"))

    def t(self, en, vi):
        return vi if self.lang == 'vi' else en


def _digits(p):
    return re.sub(r'\D', '', str(p or ''))


def _same_phone(a, b, country=None):
    """Cùng 1 số: trùng NGUYÊN số (E.164 sau khi chuẩn hoá theo nước của khách sạn, hoặc đủ mọi chữ số) — không bao giờ so
    'mấy số cuối' (ở Mỹ (212) 555-0123 và (312) 555-0123 trùng 9 số cuối nhưng là 2 người). Hàm chung ai_packs.same_phone;
    gói được nạp riêng (registry chưa có hàm đó) thì reservations_core.same_phone — cùng luật."""
    if len(_digits(a)) < 6 or len(_digits(b)) < 6:
        return False
    fn = getattr(ai_packs, 'same_phone', None)
    if not callable(fn):
        import reservations_core
        fn = reservations_core.same_phone
    return bool(fn(a, b, country))


def _country(c):
    """Nước của khách sạn để chuẩn hoá SĐT: ctx.country (customer_context), không thì ai_packs.shop_country — CÙNG 1 nguồn với
    mọi chỗ chuẩn hoá SĐT (hồ sơ -> múi giờ trang Nhắn tin -> tiền tệ). Nước BitPaw chưa có luật ('SG', 'OTHER') hay lỗi ->
    None: số nội địa không bị đoán. Gói nạp riêng (registry chưa có shop_country): hồ sơ khách sạn (nước, thiếu thì theo
    tiền tệ)."""
    if c.country is None:
        fn = getattr(ai_packs, 'shop_country', None)
        try:
            if callable(fn):
                c.country = fn(c.business_id) or ''
            else:
                shop = _shop(c.business_id)
                cur = str(shop.get('currency') or '').strip().upper()
                c.country = (str(shop.get('country') or '').strip().upper()
                             or next((k for k, v in _COUNTRY_CURRENCY.items() if v == cur), ''))
        except Exception as e:
            print(f"[hotel] shop country: {e}")
            c.country = ''
    country = {'UK': 'GB'}.get(c.country, c.country)
    return country if country in _COUNTRY_CURRENCY else None   # = ai_packs.SHOP_COUNTRIES


def _typed_phone(c):
    """SĐT khách gõ trong CHÍNH chat web này (ctx.contact_phone, không thì id hội thoại web '<tiệm>:<SĐT>')."""
    if c.contact_phone:
        return str(c.contact_phone)
    if c.channel in ('', 'web') and c.customer_id and ':' in str(c.customer_id):
        rest = str(c.customer_id).split(':', 1)[1].split('~', 1)[0].strip()
        return rest if re.fullmatch(r'\+?[0-9(][0-9 ().-]{5,31}', rest) else None
    return None


def _token_owns(doc, c):
    """Mã chat khớp VÀ (chat web) đúng chat này: đặt trong cùng hội thoại web, hoặc đứng tên đúng SĐT khách gõ ở đây. 1 máy
    tính bảng quầy dùng chung 1 mã trình duyệt: khách kế tiếp gõ SĐT khác không thấy / đổi / huỷ được phòng của người trước."""
    if not c.token_hash or doc.get('chat_token_hash') != c.token_hash:
        return False
    if c.channel not in ('', 'web'):
        return True
    if c.customer_id and doc.get('ai_conversation_id') == c.customer_id:
        return True
    typed = _typed_phone(c)
    return bool(typed) and _same_phone(doc.get('guest_phone'), typed, _country(c))


def _owned(doc, c):
    """Đặt phòng CHỨNG MINH được là của cuộc chat này: SĐT đã xác minh (SMS/WhatsApp, mã SMS 1 lần) trùng NGUYÊN số, mã chat
    web của đúng trình duyệt kèm đúng chat này, hoặc hội thoại nền tảng đã ký (Messenger/Instagram/Zalo/Viber...)."""
    if c.phone and _same_phone(doc.get('guest_phone'), c.phone, _country(c)):
        return True
    if _token_owns(doc, c):
        return True
    return bool(c.platform and doc.get('ai_conversation_id') == c.customer_id)


def _can_verify(c):
    return bool(c.phone or c.token_hash or c.platform)


def _unverified(c):
    """Chat CHƯA xác minh danh tính: không SĐT đã xác minh (SMS/WhatsApp, mã SMS 1 lần), không hội thoại nền tảng đã ký —
    tức chat web thường (mã trình duyệt chỉ để quản lý đặt phòng của chính chat đó, không phải danh tính). Phòng loại này giữ
    bị giới hạn theo khách sạn (reservations_hotel.web_holds_full)."""
    return not (c.phone or c.platform)


def _shop(business_id):
    try:
        return db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'phone': 1, 'hotline': 1, 'address': 1,
                                                            'currency': 1, 'country': 1}) or {}
    except Exception:
        return {}


_COUNTRY_CURRENCY = {'US': 'USD', 'AU': 'AUD', 'VN': 'VND', 'CA': 'CAD', 'NZ': 'NZD', 'GB': 'GBP'}


def _currency(shop):
    """Tiền của khách sạn: trường currency; thiếu thì theo quốc gia; không có gì thì USD — KHÔNG mặc định VND cho khách
    sạn ngoài Việt Nam (cùng quy ước ai_copilot_tools.business_currency / nail_turns.shop_currency)."""
    cur = str(shop.get('currency') or '').strip().upper()
    if re.fullmatch(r'[A-Z]{3}', cur):
        return cur
    return _COUNTRY_CURRENCY.get(str(shop.get('country') or '').strip().upper(), 'USD')


def _money(amount, cur):
    cur = (cur or 'USD').upper()
    if cur in ('VND', 'USD', 'AUD'):
        from currency_utils import format_money
        return format_money(amount, cur)
    try:  # currency_utils.format_money chỉ biết VND/USD/AUD — tiền khác in kèm mã, không bao giờ 'đ'
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    return f"{value:,.2f} {cur}"


def _shop_phone(business_id, shop=None):
    try:
        import booking_rules
        return booking_rules.business_phone(business_id)
    except Exception:
        shop = shop if shop is not None else _shop(business_id)
        return str(shop.get('phone') or shop.get('hotline') or '').strip()


def _call_hotel(c):
    phone = _shop_phone(c.business_id)
    return c.t(f"Please call the hotel on {phone}." if phone else "Please call the hotel directly.",
               f"Mình vui lòng gọi khách sạn số {phone} nhé." if phone else "Mình vui lòng gọi trực tiếp cho khách sạn nhé.")


def _not_verified(c):
    _refuse(c.t("For your security I can't look up or change existing bookings from this chat. ",
                "Vì bảo mật, em không xem hay thay đổi được đặt phòng đã có từ khung chat này. ") + _call_hotel(c))


def _int_arg(value, c, field, default=None, lo=1, hi=None):
    if value in (None, ''):
        if default is None:
            _refuse(c.t(f"Missing {field}.", f"Thiếu {field}."))
        return default
    try:
        n = int(float(value)) if isinstance(value, (int, float, str)) and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        n = None
    if n is None or n < lo or (hi is not None and n > hi):
        _refuse(c.t(f"{field} must be a whole number" + (f" from {lo} to {hi}." if hi else f" of at least {lo}."),
                    f"{field} phải là số nguyên" + (f" từ {lo} đến {hi}." if hi else f" từ {lo} trở lên.")))
    return n


def _yes(value):
    return value is True or str(value).strip().lower() in ('true', 'yes', '1')


def _hotel_error(c, e):
    _refuse(e.text(c.lang))


def _tell_staff(c, staff_vi, staff_en, kind):
    """Ghi 1 dòng vào hộp thư AI của khách sạn + email chủ, theo ngôn ngữ của khách sạn (VN -> tiếng Việt) — best-effort,
    không bao giờ làm hỏng đặt phòng đã ghi."""
    if not c.customer_id:
        return
    try:
        text = staff_vi if _staff_note_language(_shop(c.business_id)) == 'vi' else staff_en
        import ai_function_tools as aft
        aft._note_for_staff(c.business_id, c.customer_id, text)
        aft._alert_owner(c.business_id, c.customer_id, text, kind)
    except Exception as e:
        print(f"[hotel pack] staff notice failed: {e}")


def _flag_for_staff(c, reason):
    """Như ask_team / request_booking (ai_function_tools): hội thoại có needs_human + handoff_reason -> huy hiệu và nổi lên đầu
    hộp thư /ai_bot (không chỉ 1 dòng ghi chú + email chủ: email gộp theo giờ và bỏ qua nếu chủ chưa có email). Đang chờ người
    vì việc khác (AI tạm dừng kèm lý do) thì giữ lý do cũ. AI không tạm dừng. Best-effort."""
    if not c.customer_id:
        return
    try:
        prev = db.bot_customers.find_one({'id': c.customer_id}, {'_id': 0, 'ai_paused': 1, 'handoff_reason': 1}) or {}
        upd = {'needs_human': True, 'booking_request_at': datetime.now().isoformat()}
        if not (prev.get('ai_paused') and prev.get('handoff_reason')):
            upd['handoff_reason'] = str(reason or '')[:300]
        db.bot_customers.update_one({'id': c.customer_id}, {'$set': upd})
    except Exception as e:
        print(f"[hotel pack] needs_human flag failed: {e}")


def _status_say(status, c):
    if status == 'confirmed':
        return c.t("Booked and confirmed.", "Đã đặt và xác nhận.")
    return c.t("Request received — the hotel will confirm it. Do NOT say it is confirmed.",
               "Đã nhận yêu cầu — khách sạn sẽ xác nhận. KHÔNG nói là đã xác nhận.")


def _type_public(t, cur, c):
    out = {"room_type": t['room_type'], "available": t['available'], "max_guests_per_room": t['max_guests']}
    if t['available']:
        out["rooms_left"] = t['rooms_left']
        if t['rate_per_night']:
            out["rate_per_night"] = _money(t['rate_per_night'], cur)
            out["total"] = _money(t['total'], cur)
        else:
            out["rate"] = c.t("not published — the hotel confirms the price", "chưa công bố — khách sạn sẽ báo giá")
    else:
        out["why"] = {'too_many_guests': c.t(f"fits up to {t['max_guests']} guests per room",
                                             f"mỗi phòng tối đa {t['max_guests']} khách"),
                      'sold_out': c.t("fully booked for these dates", "đã kín phòng những ngày này")}.get(t['reason'], t['reason'])
    return out


def _nearby(c, ci, nights, guests, key, min_nights, cur, ignore_id=None, skip=None):
    """Vài khoảng ngày GẦN (cùng số đêm, lệch ±1..3 ngày) còn phòng — để gợi ý thật thay vì chỉ nói 'hết phòng'.
    Đổi ngày 1 đặt phòng: ignore_id = chính nó (đêm của nó không tính là bận), skip = (nhận, trả) hiện tại (không phải 'đổi')."""
    found = []
    for shift in (1, -1, 2, -2, 3, -3):
        start = ci + timedelta(days=shift)
        if start < c.today:
            continue
        end = start + timedelta(days=nights)
        if skip and (start.isoformat(), end.isoformat()) == tuple(skip):
            continue
        try:
            av = rh.availability(c.business_id, start, end, guests=guests, today=c.today, min_nights=min_nights,
                                 ignore_id=ignore_id)
        except rh.HotelRequestError:
            continue
        ok = [t for t in av['types'] if t['available'] and (key is None or t['key'] == key)]
        if ok:
            found.append({"checkin_date": start.isoformat(), "checkout_date": end.isoformat(),
                          "room_types": [{"room_type": t['room_type'],
                                          "total": _money(t['total'], cur) if t['total'] else None} for t in ok[:3]]})
        if len(found) >= 2:
            break
    return found


_WHOLE_UNIT_CURRENCIES = ('VND',)   # tiền không có số lẻ: _money in số đã làm tròn ('1.234đ' cho 1234.5)


def _same_total(given, total, cur):
    """quoted_total AI gửi lại ('$450.00' / '450' / '450.000đ' / số) có đúng tổng tiền hiện tại không. total None (giá chưa
    công bố): không có gì để so. Không bao giờ bỏ hết dấu rồi so chữ số trần ('450000' khớp nhầm $4,500.00, '4500' khớp
    nhầm $45.00) — dấu chấm / phẩy chỉ là dấu nghìn khi đúng nhóm 3 chữ số (_amounts). Tiền không có số lẻ (VND): số khách
    nghe là số làm tròn _money đã in, nên '1.234 VND' / '1234' khớp tổng 1234.5 ('1.234đ')."""
    if total is None:
        return True
    if isinstance(given, bool):
        return False
    heard = {float(total)}
    if str(cur or '').upper() in _WHOLE_UNIT_CURRENCIES:
        heard.add(float(int(round(float(total)))))
    if isinstance(given, (int, float)):
        return any(abs(float(given) - t) < 0.005 for t in heard)
    s = str(given).strip()
    if s == _money(total, cur):
        return True
    return any(abs(v - t) < 0.005 for v in _amounts(s, cur) for t in heard)


def _amounts(s, cur=None):
    """Các cách đọc HỢP LỆ của SỐ ĐẦU TIÊN trong chuỗi ('$1,350.00 for 3 nights' -> 1350, không phải 1350.003; '$450.00.' ->
    450): '1,200.50' / '1200.5' / '450' (chấm thập phân), '1.200.000' / '450,000' / '1 200 000' (dấu nghìn đúng nhóm 3 chữ
    số), '1.200,50' / '1350,00' (phẩy thập phân). '450.000' (đúng 1 nhóm sau 1 dấu chấm) là 450 nghìn với tiền không có số
    lẻ (VND) và là 450 với tiền khác — không bao giờ cả 2 cách (lệch 1000 lần)."""
    m = re.search(r'\d[\d.,]*', re.sub(r'(?<=\d)[ \u00a0\u202f](?=\d{3}(?!\d))', '', str(s)))
    if not m:
        return []
    num = m.group(0).rstrip('.,')
    whole = str(cur or '').upper() in _WHOLE_UNIT_CURRENCIES
    one_dot_group = re.fullmatch(r'\d{1,3}\.\d{3}', num) is not None
    out = []
    if re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?', num) and not (whole and one_dot_group):
        out.append(float(num.replace(',', '')))
    if re.fullmatch(r'\d{1,3}([.,])\d{3}(?:\1\d{3})*', num) and (whole or not one_dot_group):
        out.append(float(re.sub(r'[.,]', '', num)))
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})*,\d{1,2}|\d+,\d{1,2}', num):
        out.append(float(num.replace('.', '').replace(',', '.')))
    return out


def _walkin_note(doc, av):
    """(VI, EN) cho NHÂN VIÊN khi phòng vừa giữ đang có khách vãng lai chưa có ngày trả phòng (không bao giờ nói với khách
    đang chat) — đặt phòng đó luôn 'pending' (reservations_hotel.open_walkins)."""
    rid = doc.get('room_id')
    if rid is None or rid not in (av.get('_walkins') or ()):
        return '', ''
    num = next((r.get('room_number') for r in av.get('_rooms') or () if r.get('id') == rid), None) or rid
    return (f" Lưu ý: phòng {num} đang có khách vãng lai chưa có ngày trả phòng dự kiến (hoặc đã quá ngày đó) — kiểm tra "
            f"khách đó trả phòng trước {doc.get('checkin_date')} rồi mới xác nhận (nhập ngày trả phòng dự kiến ở trang Quản "
            f"Lý Phòng).",
            f" Note: room {num} has a walk-in guest with no expected check-out date (or it has passed) — check they leave "
            f"before {doc.get('checkin_date')} before confirming (set their expected check-out date on the Room Management "
            f"page).")


def _booking_public(r, cur, c):
    out = {"booking_id": r.get('id'), "checkin_date": r.get('checkin_date'), "checkout_date": r.get('checkout_date'),
           "room_type": r.get('room_type') or c.t('not chosen', 'chưa chọn'), "guests": r.get('party_size'),
           "status": r.get('status'), "guest_name": r.get('guest_name')}
    try:
        out["nights"] = (rh.parse_day(r.get('checkout_date')) - rh.parse_day(r.get('checkin_date'))).days
    except rh.HotelRequestError:
        pass
    if r.get('quoted_total'):
        out["total"] = _money(r['quoted_total'], r.get('currency') or cur)
    for k in ('arrival_time', 'special_requests'):
        if r.get(k):
            out[k] = r[k]
    return out


def _find_owned(c, booking_id):
    """Đặt phòng của chính chat này, hoặc từ chối CÙNG 1 câu dù số đặt phòng có tồn tại hay không (không lộ gì)."""
    if not _can_verify(c):
        _not_verified(c)
    res = db.hotel_reservations.find_one({'business_id': c.business_id, 'id': booking_id}, {'_id': 0})
    if not res or not _owned(res, c):
        _refuse(c.t(f"I can't find booking #{booking_id} among the bookings that belong to this chat. Bookings made another "
                    f"way can be changed by the hotel. ", f"Em không thấy đặt phòng #{booking_id} trong các đặt phòng của khung chat "
                    f"này. Đặt phòng làm cách khác thì khách sạn hỗ trợ thay đổi. ") + _call_hotel(c))
    if res.get('status') == rh.STAFF_REQUEST:
        # Yêu cầu AI chuyển cho nhân viên mà KHÔNG giữ phòng (vượt trần chat web chưa xác minh): chưa phải đặt phòng.
        _refuse(c.t(f"#{booking_id} is a request the hotel team is still handling — no room is held, so there is nothing to "
                    "change or cancel in this chat yet. Pass the change to the team with ask_team.",
                    f"#{booking_id} là yêu cầu nhân viên khách sạn đang xử lý — chưa giữ phòng nào, nên chưa có gì để đổi hay "
                    "huỷ trong khung chat này. Chuyển thay đổi cho nhân viên bằng ask_team."))
    return res


def _staff_note_language(shop):
    return 'vi' if str(shop.get('country') or '').upper() == 'VN' else 'en'


# ---------------------------------------------------------------- công cụ
def _check_availability(args, c):
    settings = rh.hotel_settings(c.business_id)
    guests = _int_arg(args.get('guests'), c, 'guests', default=1, hi=rh.MAX_GUESTS)
    try:
        av = rh.availability(c.business_id, args.get('checkin_date'), args.get('checkout_date'), guests=guests,
                             today=c.today, min_nights=settings['min_nights'])
    except rh.HotelRequestError as e:
        _hotel_error(c, e)
    if not av['rooms_total']:
        _refuse(c.t("This hotel hasn't listed its rooms for online booking yet, so I can't check rooms or prices here. "
                    "Offer to pass the request to the team (ask_team).",
                    "Khách sạn chưa đưa danh sách phòng lên đặt online nên em chưa xem được phòng/giá ở đây. "
                    "Đề nghị chuyển yêu cầu cho nhân viên (ask_team)."))
    key = None
    if str(args.get('room_type') or '').strip():
        key = rh.match_type(av['_types'], args['room_type'])
        if key is None:
            names = ', '.join(t['name'] for t in av['_types'].values())
            _refuse(c.t(f"There is no room type called '{str(args['room_type'])[:40]}'. Room types: {names}.",
                        f"Khách sạn không có loại phòng '{str(args['room_type'])[:40]}'. Các loại phòng: {names}."))
    cur = _currency(_shop(c.business_id))
    shown = [t for t in av['types'] if key is None or t['key'] == key]
    out = {"success": True, "checkin_date": av['checkin'].isoformat(), "checkout_date": av['checkout'].isoformat(),
           "nights": av['nights'], "guests_per_room": guests, "currency": cur,
           "room_types": [_type_public(t, cur, c) for t in shown],
           "booking_is": ('confirmed instantly when a room is free' if settings['auto_confirm'] else
                          'a request the hotel confirms (status pending)')}
    if settings['auto_confirm']:
        for pub, t in zip(out["room_types"], shown):
            if t['_room'] is not None and t['_room']['id'] in av['_walkins']:
                # phòng duy nhất còn lại đang có khách vãng lai chưa rõ ngày đi -> đặt sẽ là yêu cầu chờ khách sạn xác nhận
                pub["booking_is"] = 'a request the hotel confirms (status pending)'
    if _unverified(c):
        for pub, t in zip(out["room_types"], shown):
            if t['available'] and rh.web_holds_full(c.business_id, av['_rooms'], av['_types'], t['key'], av['checkin'],
                                                    av['checkout']):
                pub["booking_is"] = ('a request passed to the hotel team, which calls the guest to confirm — no room can be '
                                     'held online for these dates right now')
    if key is not None and not shown[0]['available']:
        others = [_type_public(t, cur, c) for t in av['types'] if t['key'] != key and t['available']]
        if others:
            out["other_room_types_free"] = others
    if not any(t['available'] for t in shown) and any(t['reason'] != 'too_many_guests' for t in shown):
        near = _nearby(c, av['checkin'], av['nights'], guests, key, settings['min_nights'], cur)
        if near:
            out["nearby_dates_free"] = near
    biggest = max(t['max_guests'] for t in av['_types'].values())
    if guests > biggest:
        out["note"] = (f"One booking = one room and the largest room fits {biggest} guests: split the party across rooms "
                       f"(check with guests per room) or pass a group request to the team.")
    return out


def _caps(c, phone):
    since = (datetime.now() - timedelta(hours=1)).isoformat()
    if db.hotel_reservations.count_documents({'business_id': c.business_id, 'source': 'ai_bot',
                                              'created_at': {'$gte': since}}) >= MAX_AI_BOOKINGS_PER_HOUR:
        _refuse(c.t("Online booking in this chat is paused for a moment because of high demand. Pass the request to the "
                    "team with ask_team — nothing is booked yet.",
                    "Đặt phòng qua chat đang tạm dừng vì quá nhiều yêu cầu. Chuyển yêu cầu cho nhân viên bằng ask_team — "
                    "hiện CHƯA đặt được gì."))
    mine = from_network = 0
    country = _country(c)
    for r in db.hotel_reservations.find({'business_id': c.business_id, 'source': 'ai_bot',
                                         'status': {'$in': list(rh.LIVE_STATUSES)},
                                         'checkout_date': {'$gte': c.today.isoformat()}},
                                        {'_id': 0, 'ai_conversation_id': 1, 'chat_token_hash': 1, 'guest_phone': 1,
                                         'client_key': 1}).limit(5000):
        if ((c.customer_id and r.get('ai_conversation_id') == c.customer_id)
                or (c.token_hash and r.get('chat_token_hash') == c.token_hash) or _same_phone(r.get('guest_phone'), phone, country)):
            mine += 1
        if c.client_key and r.get('client_key') == c.client_key:
            from_network += 1
    if mine >= MAX_LIVE_AI_BOOKINGS_PER_GUEST:
        _refuse(c.t(f"This guest already has {mine} rooms booked through chat — more rooms are a group booking the team "
                    "handles. Use ask_team; nothing new is booked.",
                    f"Khách đã đặt {mine} phòng qua chat — đặt thêm là đặt đoàn, nhân viên sẽ xử lý. Dùng ask_team; "
                    "chưa đặt thêm gì."))
    if from_network >= MAX_LIVE_AI_BOOKINGS_PER_NETWORK:
        _refuse(c.t("Several rooms have already been booked through chat from this same connection — more rooms go through "
                    "the team (as a group booking). Use ask_team; nothing new is booked.",
                    "Đã có nhiều phòng được đặt qua chat từ cùng kết nối mạng này — đặt thêm do nhân viên xử lý (đặt đoàn). "
                    "Dùng ask_team; chưa đặt thêm gì."))


def _create_booking(args, c):
    settings = rh.hotel_settings(c.business_id)
    name = rh.clean_name(args.get('guest_name'))
    if len(name) < 2:
        _refuse(c.t("Ask for the guest's full name before booking.", "Hãy hỏi họ tên đầy đủ của khách trước khi đặt phòng."))
    phone = rh.clean_phone(args.get('phone')) or (c.phone or '')
    if not rh.phone_ok(phone):
        _refuse(c.t("Ask for the guest's mobile number before booking.", "Hãy hỏi số điện thoại của khách trước khi đặt phòng."))
    email = str(args.get('email') or '').strip()[:120]
    if email and not _EMAIL_RE.match(email):
        _refuse(c.t(f"'{email[:60]}' doesn't look like an email address — ask again or leave it out.",
                    f"'{email[:60]}' không giống địa chỉ email — hỏi lại hoặc bỏ qua email."))
    arrival = None
    if str(args.get('arrival_time') or '').strip():
        try:
            arrival = rh.parse_hhmm(args['arrival_time'])
        except rh.HotelRequestError as e:
            _hotel_error(c, e)
    requests_ = re.sub(r'\s+', ' ', str(args.get('special_requests') or '')).strip()[:300] or None
    guests = _int_arg(args.get('guests'), c, 'guests', hi=rh.MAX_GUESTS)
    rooms = rh.list_rooms(c.business_id)
    if not rooms:
        _refuse(c.t("This hotel hasn't listed its rooms for online booking yet — nothing can be booked here. Use ask_team.",
                    "Khách sạn chưa đưa danh sách phòng lên đặt online — không đặt được ở đây. Dùng ask_team."))
    types = rh.room_types(rooms)
    key = rh.match_type(types, args.get('room_type')) if str(args.get('room_type') or '').strip() else (
        next(iter(types)) if len(types) == 1 else None)
    if key is None:
        names = ', '.join(t['name'] for t in types.values())
        _refuse(c.t(f"Ask which room type the guest wants: {names}.", f"Hỏi khách muốn loại phòng nào: {names}."))
    try:
        ci, co, _n = rh.check_stay(args.get('checkin_date'), args.get('checkout_date'), today=c.today,
                                   min_nights=settings['min_nights'])
    except rh.HotelRequestError as e:
        _hotel_error(c, e)
    shop = _shop(c.business_id)
    cur = _currency(shop)

    # "đặt giúp em" nói 2 lần không được ra 2 phòng: cùng chat + cùng ngày + cùng loại + cùng tên -> trả lại đặt phòng cũ
    if not _yes(args.get('another_room')):
        for r in db.hotel_reservations.find({'business_id': c.business_id, 'status': {'$in': list(rh.LIVE_STATUSES)},
                                             'checkin_date': ci.isoformat(), 'checkout_date': co.isoformat()},
                                            {'_id': 0}).limit(200):
            same = rh.type_key(r.get('room_type')) == key and rh.clean_name(r.get('guest_name')).casefold() == name.casefold()
            if not same:
                continue
            if _owned(r, c):
                return {"success": True, "already_booked": True, **_booking_public(r, cur, c),
                        "note": "This exact booking already exists in this chat — don't create another. If the guest wants "
                                "an ADDITIONAL room, call again with another_room=true."}
            if c.customer_id and r.get('ai_conversation_id') == c.customer_id:
                if c.platform:   # hội thoại nền tảng đã ký (thực tế _owned đã nhận ở trên)
                    return {"success": True, "already_booked": True,
                            "note": "Exactly this booking was already made a moment ago in this conversation — don't create another."}
                # Chat web '<khách sạn>:<SĐT tự gõ>': ai gõ cùng SĐT + tên + ngày + loại phòng cũng tới đây (trình duyệt khác, không
                # mã). KHÔNG nói "đặt phòng này đã có" (dò được ai ở đâu, ngày nào), không mã / tên / ngày / ghi chú của đặt phòng
                # đã có, không tạo thêm: trả lời như 1 yêu cầu chờ khách sạn xác nhận; khách sạn nhận ghi chú để tự liên hệ khách.
                _tell_staff(c, f"🛏️ Chat AI xin đặt phòng {types[key]['name']} {ci.isoformat()} → {co.isoformat()} cho {name} — trùng "
                               f"đặt phòng #{r.get('id')} (cùng SĐT, tên, ngày, loại phòng) nên AI KHÔNG tạo thêm (chat chưa xác "
                               "minh là chủ). Khách sạn liên hệ khách để xác nhận.",
                            f"🛏️ The AI chat asked for a {types[key]['name']} room {ci.isoformat()} to {co.isoformat()} for {name} — "
                            f"it matches booking #{r.get('id')} (same phone, name, dates and room type), so nothing new was created "
                            "(the chat isn't verified as its owner). Please confirm with the guest.",
                            f"hotel_dup_{r.get('id')}")
                return {"success": True, "request_sent_to_team": True, "confirmed": False, "status": "pending",
                        "say": _status_say('pending', c),
                        "note": "Passed to the hotel, which confirms it with the guest by phone. Nothing new was booked in this "
                                "chat: give no booking number and never say it is confirmed."}
    _caps(c, phone)

    whole_type_priced = all(r['_rate'] for r in types[key]['rooms'])
    status = 'confirmed' if (settings['auto_confirm'] and whole_type_priced) else 'pending'
    staff_vi = _staff_note_language(shop) == 'vi'
    note_bits = []
    if arrival:
        note_bits.append(("Giờ đến dự kiến " if staff_vi else "Arrival ") + arrival)
    if requests_:
        note_bits.append(("Yêu cầu: " if staff_vi else "Requests: ") + requests_)
    if email:
        note_bits.append("Email: " + email)
    unverified = _unverified(c)
    extra = {'source': 'ai_bot', 'ai_conversation_id': c.customer_id, 'ai_channel': c.channel or 'web',
             'chat_token_hash': c.token_hash, 'guest_email': email or None, 'arrival_time': arrival,
             'special_requests': requests_, 'currency': cur,
             'note': ('; '.join(note_bits) or None), 'ai_verified': not unverified}
    if c.client_key:
        extra['client_key'] = c.client_key   # giới hạn số phòng theo mạng (_caps)
    try:
        doc, av = rh.create_hold(c.business_id, checkin=ci, checkout=co, guests=guests, room_type_key=key, guest_name=name,
                                 guest_phone=phone, status=status, today=c.today, min_nights=settings['min_nights'],
                                 extra=extra, unverified=unverified)
    except rh.HotelRequestError as e:
        if e.code == 'web_hold_cap':
            return _web_cap_request(c, types[key]['name'], ci, co, guests, name, phone, note_bits, extra)
        _hotel_error(c, e)
    if doc is None:
        t = next((x for x in av['types'] if x['key'] == key), None)
        reason = (t or {}).get('reason') or 'sold_out'
        if reason == 'too_many_guests':
            cap = types[key]['max_guests']
            message = c.t(f"A {types[key]['name']} room fits up to {cap} guests — nothing was booked. Split the party across "
                          "rooms (another_room=true) or offer a bigger room type.",
                          f"Phòng {types[key]['name']} tối đa {cap} khách — chưa đặt được gì. Chia khách ra nhiều phòng "
                          "(another_room=true) hoặc gợi ý loại phòng lớn hơn.")
        else:
            message = c.t(f"No {types[key]['name']} room is free for those dates — nothing was booked.",
                          f"Không còn phòng {types[key]['name']} trống những ngày này — chưa đặt được gì.")
        out = {"success": False, "reason": reason, "message": message,
               "other_room_types_free": [_type_public(x, cur, c) for x in av['types'] if x['available']]}
        if not out["other_room_types_free"] and reason != 'too_many_guests':
            near = _nearby(c, ci, (co - ci).days, guests, key, settings['min_nights'], cur)
            if near:
                out["nearby_dates_free"] = near
        return out

    status = doc.get('status') or status   # phòng có khách vãng lai chưa rõ ngày đi -> create_hold để 'pending'
    walkin_vi, walkin_en = _walkin_note(doc, av)
    _tell_staff(c, f"🛏️ AI {'xác nhận' if status == 'confirmed' else 'nhận yêu cầu'} đặt phòng #{doc['id']}: {name} — "
                   f"{doc['room_type']}, {doc['checkin_date']} → {doc['checkout_date']} ({doc['nights']} đêm), {guests} khách"
                   + ("" if status == 'confirmed' else " — cần xác nhận hoặc từ chối") + ". Xem tại Khách sạn > Đặt phòng."
                   + walkin_vi,
                f"🛏️ New {'confirmed booking' if status == 'confirmed' else 'booking request'} #{doc['id']} from the chat: "
                f"{name}, {doc['room_type']}, {doc['checkin_date']} to {doc['checkout_date']}, {guests} guest(s)"
                + ("" if status == 'confirmed' else " — please confirm or decline on Hotel > Reservations.") + walkin_en,
                f"hotel_new_{doc['id']}")
    out = {"success": True, **_booking_public(doc, cur, c), "currency": cur, "say": _status_say(status, c)}
    if doc.get('rate_per_night'):
        out["rate_per_night"] = _money(doc['rate_per_night'], cur)
    else:
        out["price"] = c.t("rate not published — the hotel confirms the price", "chưa công bố giá — khách sạn sẽ báo giá")
    out["manage_hint"] = ("The guest can message in this chat to see, change or cancel it." if _can_verify(c) else
                          "To change it later the guest should call the hotel.")
    return out


def _web_cap_request(c, type_name, ci, co, guests, name, phone, note_bits, extra=None):
    """Đã chạm trần giữ phòng của chat web chưa xác minh (reservations_hotel.web_holds_full — theo loại phòng hoặc cả khách
    sạn): KHÔNG giữ phòng nào. Yêu cầu (tên, SĐT khách gõ, ngày, loại phòng, số khách, ghi chú) không bị lạc:
    - 1 dòng 'requested' (reservations_hotel.create_staff_request) hiện trên Khách sạn > Đặt phòng để nhân viên Duyệt (kiểm
      lại phòng trống) / Từ chối — không chiếm phòng, không số đặt phòng cho khách;
    - hội thoại được gắn needs_human + handoff_reason như ask_team / request_booking (huy hiệu, nổi lên đầu hộp thư /ai_bot);
    - ghi chú hộp thư AI + email chủ chỉ nhân viên tới trang Đặt phòng của nhân viên (link đặt phòng công khai bị giới hạn
      theo IP — quầy lễ tân nhập nhiều yêu cầu từ cùng mạng sẽ bị chặn).
    Không nói đã đặt / đã xác nhận."""
    if not c.customer_id:   # không có hội thoại để ghi chú cho nhân viên -> không hứa "đã chuyển"
        _refuse(c.t("Online booking isn't available for these dates right now — nothing was booked. ",
                    "Hiện chưa đặt online được những ngày này — chưa đặt gì. ") + _call_hotel(c))
    nights = (co - ci).days
    bits = ('; ' + '; '.join(note_bits)) if note_bits else ''
    doc, created = rh.create_staff_request(c.business_id, checkin=ci, checkout=co, guests=guests, room_type=type_name,
                                           guest_name=name, guest_phone=phone,
                                           extra=dict(extra or {}, request_reason='web_hold_cap'))
    staff_vi = _staff_note_language(_shop(c.business_id)) == 'vi'
    if created:
        _tell_staff(c, f"🛏️ Yêu cầu đặt phòng #{doc['id']} qua chat AI — CHƯA giữ phòng: {name}, SĐT khách gõ {phone} (chưa xác "
                       f"minh) — {type_name}, {ci.isoformat()} → {co.isoformat()} ({nights} đêm), {guests} khách{bits}. Đã có "
                       "nhiều phòng (của loại này hoặc của cả khách sạn) được giữ qua chat online chưa xác minh những đêm đó nên "
                       "AI không giữ thêm: gọi khách xác nhận. Yêu cầu đã nằm ở Khách sạn > Đặt phòng (trạng thái 'Yêu cầu — "
                       "chưa giữ phòng'): nhận khách thì bấm Duyệt ở đó (kiểm lại phòng trống) rồi xếp phòng, không thì Từ chối.",
                    f"🛏️ Booking request #{doc['id']} from the AI chat — NO room held: {name}, phone typed {phone} (not verified) "
                    f"— {type_name}, {ci.isoformat()} to {co.isoformat()} ({nights} night(s)), {guests} guest(s){bits}. Many "
                    "rooms (of this type or across the hotel) are already held by unverified online chats for those nights, so "
                    "the AI did not hold another: call the guest to confirm. The request is listed on Hotel > Reservations as "
                    "'Request — no room held': to take it, click Approve there (availability is re-checked), then assign a "
                    "room; otherwise Decline it.",
                    "hotel_webcap")
    _flag_for_staff(c, (f"Yêu cầu đặt phòng #{doc['id']} — CHƯA giữ phòng (chat chưa xác minh, vượt giới hạn giữ phòng online): "
                        f"{type_name} {ci.isoformat()} → {co.isoformat()}, {guests} khách — {name}. Duyệt / từ chối ở Khách sạn "
                        "> Đặt phòng.") if staff_vi else
                    (f"Booking request #{doc['id']} — no room held (unverified chat over the online hold limit): {type_name} "
                     f"{ci.isoformat()} to {co.isoformat()}, {guests} guest(s) — {name}. Approve or decline it on Hotel > "
                     "Reservations."))
    return {"success": True, "request_sent_to_team": True, "room_held": False, "confirmed": False, "status": "pending",
            "say": _status_say('pending', c),
            "note": "No room was held online: the request went to the hotel team, who will call the guest to confirm. Give "
                    "no booking number and never say it is booked or confirmed."}


def _my_bookings(args, c):
    if not _can_verify(c):
        _not_verified(c)
    shop = _shop(c.business_id)
    cur = _currency(shop)
    rows = [r for r in db.hotel_reservations.find({'business_id': c.business_id, 'status': {'$in': list(rh.LIVE_STATUSES)},
                                                   'checkout_date': {'$gte': c.today.isoformat()}},
                                                  {'_id': 0}).sort('checkin_date', 1).limit(3000) if _owned(r, c)]
    out = {"success": True, "bookings": [_booking_public(r, cur, c) for r in rows[:10]]}
    settings = rh.hotel_settings(c.business_id)
    if settings['checkin_time'] or settings['checkout_time']:
        out["stay_times"] = {k: v for k, v in (("check_in_from", settings['checkin_time']),
                                                ("check_out_by", settings['checkout_time'])) if v}
    if not c.phone:
        out["scope"] = "Only bookings made in this chat are listed."
        if not rows:
            out["tell_customer"] = c.t("I can only see bookings made in this chat. ", "Em chỉ xem được đặt phòng làm trong "
                                       "khung chat này. ") + _call_hotel(c)
    return out


def _cancel_booking(args, c):
    booking_id = _int_arg(args.get('booking_id'), c, 'booking_id')
    res = _find_owned(c, booking_id)
    cur = _currency(_shop(c.business_id))
    if res.get('status') not in rh.LIVE_STATUSES:
        return {"success": True, "already_cancelled": True, "booking_id": booking_id}
    if str(res.get('checkout_date') or '') <= c.today.isoformat():
        _refuse(c.t("This stay has already ended — the hotel handles it. ", "Kỳ lưu trú này đã kết thúc — khách sạn sẽ xử lý. ")
                + _call_hotel(c))
    if str(res.get('checkin_date') or '') <= c.today.isoformat():
        # Giữa kỳ lưu trú (khách có thể đang ở phòng): huỷ qua chat sẽ trả các đêm còn lại để bán cho người khác.
        _refuse(c.t("From the check-in day on, cancellations go through the front desk — the booking is NOT cancelled. ",
                    "Từ ngày nhận phòng trở đi, huỷ phòng do quầy lễ tân xử lý — đặt phòng CHƯA bị huỷ. ") + _call_hotel(c))
    if not _yes(args.get('customer_confirmed')):
        return {"success": False, "needs_confirmation": True, "booking": _booking_public(res, cur, c),
                "ask_customer": c.t("Read this booking back and ask the guest to confirm the cancellation.",
                                    "Đọc lại đặt phòng này và hỏi khách xác nhận huỷ.")}
    settings = rh.hotel_settings(c.business_id)
    ok, why = rh.cancel_allowed(res, settings, c.now)
    if not ok:
        _refuse(c.t("This confirmed booking is inside the hotel's cancellation window, so only the hotel can cancel it now "
                    "(fees may apply). Pass the request with ask_team — it is NOT cancelled, and don't promise a refund.",
                    "Đặt phòng đã xác nhận này đã quá hạn huỷ qua chat — chỉ khách sạn huỷ được (có thể mất phí). Chuyển "
                    "yêu cầu bằng ask_team — đặt phòng CHƯA bị huỷ, không hứa hoàn tiền."))
    doc = rh.cancel(c.business_id, booking_id, 'customer_ai_chat')
    if not doc:
        return {"success": True, "already_cancelled": True, "booking_id": booking_id}
    _tell_staff(c, f"🛏️ Khách tự huỷ đặt phòng #{booking_id} ({res.get('checkin_date')} → {res.get('checkout_date')}) qua chat AI.",
                f"🛏️ A guest cancelled booking #{booking_id} ({res.get('checkin_date')} to {res.get('checkout_date')}) in the chat.",
                f"hotel_cancel_{booking_id}")
    out = {"success": True, "cancelled": True, "booking_id": booking_id, "checkin_date": res.get('checkin_date'),
           "checkout_date": res.get('checkout_date'), "was": res.get('status')}
    try:
        import booking_rules
        policy = (booking_rules.get_rules(c.business_id).get('info') or {}).get('cancellation_policy')
    except Exception:
        policy = None
    if policy and (res.get('status') == 'confirmed' or res.get('was_confirmed')):
        out["hotel_policy"] = policy
        out["note"] = "Mention the hotel's written policy; don't say anything about refunds or fees beyond it."
    return out


def _change_dates(args, c):
    booking_id = _int_arg(args.get('booking_id'), c, 'booking_id')
    res = _find_owned(c, booking_id)
    cur = _currency(_shop(c.business_id))
    if res.get('status') not in rh.LIVE_STATUSES:
        _refuse(c.t(f"Booking #{booking_id} is cancelled — make a new booking instead.",
                    f"Đặt phòng #{booking_id} đã huỷ — hãy đặt phòng mới."))
    if str(res.get('checkin_date') or '') <= c.today.isoformat():
        _refuse(c.t("Changes on or after the check-in day go through the front desk. ",
                    "Thay đổi từ ngày nhận phòng trở đi do quầy lễ tân xử lý. ") + _call_hotel(c))
    settings = rh.hotel_settings(c.business_id)
    if res.get('status') == 'confirmed' or res.get('was_confirmed'):
        # Đổi ngày / số khách đưa đặt phòng đã xác nhận về 'pending' (hoặc dời xa hơn): trong hạn huỷ mà vẫn cho đổi qua chat
        # thì khách "đổi rồi huỷ" là thoát được hạn huỷ của khách sạn.
        allowed, _why = rh.cancel_allowed(res, settings, c.now)
        if not allowed:
            _refuse(c.t("This booking was confirmed by the hotel and is now inside its cancellation window, so changes go "
                        "through the hotel (fees may apply). Pass the request with ask_team — the booking is NOT changed.",
                        "Đặt phòng này đã được khách sạn xác nhận và đã vào hạn huỷ, nên thay đổi lúc này do khách sạn xử lý "
                        "(có thể mất phí). Chuyển yêu cầu bằng ask_team — đặt phòng CHƯA được đổi."))
    guests = _int_arg(args.get('guests'), c, 'guests', default=res.get('party_size') or 1, hi=rh.MAX_GUESTS)
    try:
        ci, co, nights = rh.check_stay(args.get('new_checkin_date'), args.get('new_checkout_date'), today=c.today,
                                       min_nights=settings['min_nights'])
    except rh.HotelRequestError as e:
        _hotel_error(c, e)
    if ci.isoformat() == res.get('checkin_date') and co.isoformat() == res.get('checkout_date') and guests == res.get('party_size'):
        return {"success": True, "unchanged": True, **_booking_public(res, cur, c)}
    # Báo giá bằng CHÍNH phương án change_dates sẽ ghi (không tính đặt phòng này là bận, giữ phòng hiện tại nếu còn trống):
    # hotel_check_availability tính cả đêm của chính khách là đã bán và báo giá phòng rẻ nhất — sai cho việc đổi ngày.
    try:
        q = rh.quote_change(c.business_id, res, ci, co, guests=guests, today=c.today, min_nights=settings['min_nights'])
    except rh.HotelRequestError as e:
        _hotel_error(c, e)
    if not q['available']:
        return _change_unavailable(c, res, ci, nights, guests, q['key'], settings, cur, q['av'])
    # Giữ nhiều đêm lẻ dưới trần rồi dời hết vào 1 đêm cũng không vượt được trần (ngày mới chưa ai ở khách sạn duyệt / xem —
    # change_dates xoá các dấu nhân viên đã duyệt / đã xem của ngày cũ).
    unreviewed = dict(res, staff_confirmed_at=None, staff_reviewed_at=None, checked_in_at=None)
    if rh.unverified_web_hold(unreviewed) and rh.web_holds_full(
            c.business_id, q['av']['_rooms'], q['av']['_types'], q['key'], ci, co, ignore_id=res['id']):
        _refuse(c.t("Many rooms (of this type or across the hotel) are already held by unverified online chats for the new "
                    "dates, so this change goes through the hotel team. Pass the request with ask_team — the booking is NOT "
                    "changed.",
                    "Đã có nhiều phòng (của loại này hoặc của cả khách sạn) được giữ qua chat online chưa xác minh vào ngày "
                    "mới, nên thay đổi này do nhân viên khách sạn xử lý. Chuyển yêu cầu bằng ask_team — đặt phòng CHƯA được đổi."))
    keep_confirmed = settings['auto_confirm'] and res.get('status') == 'confirmed'
    new_total = _money(q['total'], cur) if q['total'] else None
    quoted = args.get('quoted_total')
    confirmed = _yes(args.get('customer_confirmed'))
    # Xác nhận mà không kèm số đã báo khách: giá có thể đã đổi giữa lượt báo giá và lượt này -> báo lại, không ghi im lặng.
    no_quote = confirmed and quoted in (None, '') and q['total'] is not None
    if not confirmed or no_quote:
        out = {"success": False, "needs_confirmation": True, "booking": _booking_public(res, cur, c),
               "new_dates": {"checkin_date": ci.isoformat(), "checkout_date": co.isoformat(), "nights": nights},
               "guests": guests, "available": True,
               "new_total": new_total or c.t("rate not published — the hotel confirms the price",
                                             "chưa công bố giá — khách sạn sẽ báo giá"),
               "ask_customer": c.t("These dates are free (the guest's own booking is not counted as taken). Tell the guest "
                                   "new_total, get a clear yes, then call again with customer_confirmed=true and quoted_total "
                                   "= new_total. No other availability check is needed.",
                                   "Ngày mới còn phòng (không tính đặt phòng của chính khách là bận). Báo khách new_total, chờ "
                                   "khách đồng ý rõ ràng, rồi gọi lại với customer_confirmed=true và quoted_total = new_total. "
                                   "Không cần kiểm phòng trống thêm.")}
        if no_quote:
            out["quoted_total_missing"] = True
            out["ask_customer"] = c.t(
                f"The booking is NOT changed: confirming needs quoted_total. The total for the new dates is {new_total}. "
                f"Unless the guest already agreed to exactly {new_total}, tell them and get a clear yes; then call again "
                f"with customer_confirmed=true and quoted_total={new_total}.",
                f"Đặt phòng CHƯA được đổi: xác nhận phải kèm quoted_total. Tổng tiền ngày mới là {new_total}. Nếu khách chưa "
                f"đồng ý đúng số {new_total} thì báo khách và chờ khách đồng ý rõ ràng; rồi gọi lại với "
                f"customer_confirmed=true và quoted_total={new_total}.")
        walkin_room = q['room'] is not None and q['room']['id'] in q['av']['_walkins']
        if res.get('status') == 'confirmed' and (not keep_confirmed or walkin_room or not q['rate']):
            out["after_change"] = c.t("The hotel re-confirms the new dates (status pending); the cancellation rules of a "
                                      "confirmed booking still apply.",
                                      "Khách sạn sẽ xác nhận lại ngày mới (status pending); luật huỷ của đặt phòng đã xác "
                                      "nhận vẫn áp dụng.")
        return out
    if quoted not in (None, '') and not _same_total(quoted, q['total'], cur):
        return {"success": False, "price_changed": True, "new_total": new_total,
                "booking_unchanged": _booking_public(res, cur, c),
                "ask_customer": c.t(f"The total for these dates is now {new_total}, not the amount quoted — the booking is "
                                    f"NOT changed. Tell the guest, get a clear yes, then call again with "
                                    f"customer_confirmed=true and quoted_total={new_total}.",
                                    f"Tổng tiền những ngày này giờ là {new_total}, khác số đã báo — đặt phòng CHƯA được đổi. "
                                    f"Báo khách, chờ khách đồng ý rõ ràng, rồi gọi lại với customer_confirmed=true và "
                                    f"quoted_total={new_total}.")}
    try:
        doc, av = rh.change_dates(c.business_id, res, ci, co, guests=guests, today=c.today,
                                  min_nights=settings['min_nights'], new_status=None if keep_confirmed else 'pending',
                                  expect_rate=q['rate'])
    except rh.HotelRequestError as e:
        if e.code == 'price_changed':
            _refuse(c.t("The price for these dates changed a moment ago (a room was just taken), so the booking was NOT "
                        "changed. Call hotel_change_dates again without customer_confirmed to get the new total and check "
                        "it with the guest.",
                        "Giá những ngày này vừa thay đổi (1 phòng vừa có người giữ) nên đặt phòng CHƯA được đổi. Gọi lại "
                        "hotel_change_dates không kèm customer_confirmed để lấy tổng tiền mới và hỏi lại khách."))
        _hotel_error(c, e)
    if doc is None:
        return _change_unavailable(c, res, ci, nights, guests, q['key'], settings, cur, av)
    if keep_confirmed and not doc.get('rate_per_night'):
        db.hotel_reservations.update_one({'id': booking_id, 'business_id': c.business_id}, {'$set': {'status': 'pending'}})
        doc['status'] = 'pending'
    status = doc.get('status')
    walkin_vi, walkin_en = _walkin_note(doc, av)
    _tell_staff(c, f"🛏️ Khách đổi ngày đặt phòng #{booking_id}: {res.get('checkin_date')} → {res.get('checkout_date')} thành "
                   f"{doc['checkin_date']} → {doc['checkout_date']} qua chat AI"
                   + ("" if status == 'confirmed' else " — cần duyệt lại") + "." + walkin_vi,
                f"🛏️ A guest moved booking #{booking_id} to {doc['checkin_date']} – {doc['checkout_date']} in the chat"
                + ("." if status == 'confirmed' else " — please confirm the new dates on Hotel > Reservations.") + walkin_en,
                f"hotel_change_{booking_id}_{doc['checkin_date']}")
    out = {"success": True, "changed": True, **_booking_public(doc, cur, c),
           "old_dates": {"checkin_date": res.get('checkin_date'), "checkout_date": res.get('checkout_date')},
           "say": _status_say(status, c)}
    if res.get('quoted_total') and doc.get('quoted_total') and res['quoted_total'] != doc['quoted_total']:
        out["old_total"] = _money(res['quoted_total'], res.get('currency') or cur)
    return out


def _change_unavailable(c, res, ci, nights, guests, key, settings, cur, av):
    """Ngày mới không còn phòng: nói thật (đặt phòng CHƯA đổi) + vài khoảng ngày gần còn phòng — đêm của CHÍNH đặt phòng
    này không tính là bận (dời / kéo dài trùng đêm cũ vẫn được)."""
    out = {"success": False, "reason": "no_rooms",
           "message": c.t("No room of this type is free for the new dates — the booking was NOT changed.",
                          "Không còn phòng loại này trống ngày mới — đặt phòng CHƯA được đổi."),
           "booking_unchanged": _booking_public(res, cur, c)}
    near = _nearby(c, ci, nights, guests, key if key in av['_types'] else None, settings['min_nights'], cur,
                   ignore_id=res['id'], skip=(res.get('checkin_date'), res.get('checkout_date')))
    if near:
        out["nearby_dates_free"] = near
    return out


HANDLERS = {
    'hotel_check_availability': _check_availability,
    'hotel_create_booking': _create_booking,
    'hotel_my_bookings': _my_bookings,
    'hotel_cancel_booking': _cancel_booking,
    'hotel_change_dates': _change_dates,
}


def execute(name, args, ctx):
    """Chạy 1 công cụ của gói. Trả dict kết quả THẬT; từ chối / dữ liệu sai -> ai_packs.PackError."""
    handler = HANDLERS.get(name)
    c = _Ctx(ctx)
    if handler is None:
        _refuse(c.t(f"Unknown hotel tool '{name}'.", f"Không có công cụ khách sạn '{name}'."))
    if not c.business_id:
        _refuse(c.t("No hotel is linked to this chat.", "Khung chat chưa gắn với khách sạn nào."))
    if isinstance(args, str):  # một số model trả arguments dạng chuỗi JSON
        try:
            import json
            args = json.loads(args or '{}')
        except ValueError:
            args = {}
    return handler(args if isinstance(args, dict) else {}, c)


# ---------------------------------------------------------------- dữ kiện công khai cho prompt
def facts(business_id, lang, now_local):
    """Dữ kiện THẬT cho prompt: loại phòng + giá/đêm (tiền của khách sạn), luật lưu trú, giờ nhận/trả phòng nếu chủ đã
    đặt, cách xác nhận, chính sách huỷ, thông tin khách sạn chủ đã nhập. Phòng trống thì chỉ qua công cụ (không ở đây).
    Giờ mở cửa KHÔNG ở đây: customer_context.hours_lines thêm OPENING HOURS + RIGHT NOW cho mọi gói theo 1 kiểu giờ chung
    (trước: dòng riêng 'Fri 18:00-02:00 (closes at 02:00 Sat, after midnight)' nằm cạnh dòng đó — 1 prompt nói 2 lần 2 kiểu)."""
    vi = lang == 'vi'
    T = (lambda en, v: v if vi else en)  # noqa: E731
    now = _local_now(business_id, now_local)
    shop = _shop(business_id)
    cur = _currency(shop)
    try:
        settings = rh.hotel_settings(business_id)
        rooms = rh.list_rooms(business_id)
    except Exception as e:
        print(f"[hotel pack facts] {e}")
        return T("HOTEL ROOMS: room data is unavailable right now — don't quote rooms or rates; use ask_team.",
                 "PHÒNG KHÁCH SẠN: chưa tải được dữ liệu phòng — không báo phòng/giá; dùng ask_team.")
    types = rh.room_types(rooms)
    day_en = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')[now.weekday()]
    day_vi = ('Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật')[now.weekday()]
    lines = [T(f"TODAY AT THE HOTEL: {now.strftime('%Y-%m-%d')} ({day_en}), {now.strftime('%H:%M')} local time. "
               "All dates are the hotel's local dates.",
               f"HÔM NAY TẠI KHÁCH SẠN: {now.strftime('%Y-%m-%d')} ({day_vi}), {now.strftime('%H:%M')} giờ địa phương. "
               "Mọi ngày tính theo giờ của khách sạn.")]
    if not rooms:
        lines.append(T("ROOMS: none listed for online booking yet — don't quote rooms or rates; offer to pass the request "
                       "to the team (ask_team).",
                       "PHÒNG: khách sạn chưa đưa phòng lên đặt online — không báo phòng/giá; đề nghị chuyển yêu cầu cho "
                       "nhân viên (ask_team)."))
    else:
        rows = []
        for t in sorted(types.values(), key=lambda t: (t['rate_min'] is None, t['rate_min'] or 0, t['name'])):
            if t['rate_min'] is None:
                rate = T("rate not published", "chưa công bố giá")
            elif t['rate_min'] == t['rate_max']:
                rate = T(f"{_money(t['rate_min'], cur)} per night", f"{_money(t['rate_min'], cur)}/đêm")
            else:
                rate = T(f"{_money(t['rate_min'], cur)}–{_money(t['rate_max'], cur)} per night depending on the room",
                         f"{_money(t['rate_min'], cur)}–{_money(t['rate_max'], cur)}/đêm tuỳ phòng")
            rows.append(T(f"- {t['name']}: {len(t['rooms'])} room(s), up to {t['max_guests']} guests per room, {rate}",
                          f"- {t['name']}: {len(t['rooms'])} phòng, tối đa {t['max_guests']} khách/phòng, {rate}"))
        lines.append(T(f"ROOM TYPES & NIGHTLY RATES ({cur}, from the hotel's room list — check live availability and the "
                       "exact total with hotel_check_availability):\n",
                       f"LOẠI PHÒNG & GIÁ/ĐÊM ({cur}, theo danh sách phòng của khách sạn — phòng trống và tổng tiền "
                       "chính xác phải kiểm bằng hotel_check_availability):\n") + "\n".join(rows))
    mn = settings['min_nights']
    lines.append(T(f"STAY RULES: {mn}–{rh.MAX_NIGHTS} nights per booking"
                   + (f" (minimum stay {mn} nights)" if mn > 1 else "") + "; check-in from today up to one year ahead; "
                   "one booking = one room.",
                   f"LUẬT LƯU TRÚ: {mn}–{rh.MAX_NIGHTS} đêm mỗi lần đặt" + (f" (tối thiểu {mn} đêm)" if mn > 1 else "")
                   + "; nhận phòng từ hôm nay tới tối đa 1 năm tới; 1 lần đặt = 1 phòng."))
    if settings['checkin_time'] or settings['checkout_time']:
        bits = []
        if settings['checkin_time']:
            bits.append(T(f"check-in from {settings['checkin_time']}", f"nhận phòng từ {settings['checkin_time']}"))
        if settings['checkout_time']:
            bits.append(T(f"check-out by {settings['checkout_time']}", f"trả phòng trước {settings['checkout_time']}"))
        lines.append(T("CHECK-IN / CHECK-OUT: ", "GIỜ NHẬN / TRẢ PHÒNG: ") + ", ".join(bits) + ".")
    else:
        lines.append(T("CHECK-IN / CHECK-OUT TIMES: not published — use ask_team if asked.",
                       "GIỜ NHẬN / TRẢ PHÒNG: khách sạn chưa công bố — khách hỏi thì dùng ask_team."))
    lines.append(T("CONFIRMATION: bookings made in this chat are " + (
        "confirmed instantly when a room is free (the tool returns status 'confirmed')." if settings['auto_confirm'] else
        "REQUESTS the hotel confirms (status 'pending') — say the request is in and the hotel will confirm; never say confirmed."),
        "XÁC NHẬN: đặt phòng qua chat " + (
        "được xác nhận ngay khi còn phòng (công cụ trả status 'confirmed')." if settings['auto_confirm'] else
        "là YÊU CẦU khách sạn sẽ xác nhận (status 'pending') — nói đã nhận yêu cầu, khách sạn sẽ xác nhận; không nói đã xác nhận.")))
    if settings['free_cancel_hours'] is not None:
        h = settings['free_cancel_hours']
        # cancel_allowed tính từ 00:00 ngày nhận phòng khi chủ chưa đặt giờ nhận phòng — nói đúng mốc đó
        when = (T(f"{h} hours before check-in ({settings['checkin_time']})",
                  f"{h} giờ trước giờ nhận phòng ({settings['checkin_time']})") if settings['checkin_time'] else
                T(f"{h} hours before the start (00:00) of the check-in day", f"{h} giờ trước 0:00 (đầu ngày) của ngày nhận phòng"))
        cancel = T(f"confirmed bookings can be cancelled in this chat until {when}; after that only the hotel can cancel "
                   "(fees may apply).",
                   f"đặt phòng đã xác nhận huỷ qua chat được tới {when}; sau đó chỉ khách sạn huỷ được (có thể mất phí).")
    else:
        cancel = T("confirmed bookings can be cancelled in this chat until the day before check-in; on or after the "
                   "check-in day only the hotel can cancel.",
                   "đặt phòng đã xác nhận huỷ qua chat được tới trước ngày nhận phòng; từ ngày nhận phòng trở đi chỉ khách "
                   "sạn huỷ được.")
    lines.append(T("CANCELLATION: pending requests can be cancelled in this chat until the day before check-in; ",
                   "HUỶ PHÒNG: yêu cầu còn chờ xác nhận huỷ qua chat được tới trước ngày nhận phòng; ") + cancel
                 + T(" A confirmed booking moved to new dates keeps these confirmed-booking rules while the hotel re-confirms "
                     "it; inside the cancellation window, changes to a confirmed booking go through the hotel (ask_team).",
                     " Đặt phòng đã xác nhận rồi đổi ngày vẫn theo luật của đặt phòng đã xác nhận trong lúc chờ khách sạn xác "
                     "nhận lại; đã vào hạn huỷ thì thay đổi đặt phòng đã xác nhận do khách sạn xử lý (ask_team)."))
    try:
        import booking_rules
        rules = booking_rules.get_rules(business_id)
        info = dict(rules.get('info') or {})
        phone = _shop_phone(business_id, shop)
    except Exception:
        rules, info, phone = {}, {}, _shop_phone(business_id, shop)
    if not info.get('address') and shop.get('address'):
        info['address'] = shop['address']
    labels = {'address': T('Address', 'Địa chỉ'), 'parking': T('Parking', 'Gửi xe'),
              'payments': T('Payment methods', 'Thanh toán'), 'gift_cards': T('Gift cards / vouchers', 'Thẻ quà tặng / voucher'),
              'cancellation_policy': T("Hotel's written cancellation policy", 'Chính sách huỷ của khách sạn'),
              'other': T('Other notes', 'Ghi chú khác')}
    facts_ = [f"{labels.get(k, k)}: {v}" for k, v in info.items() if v and k in labels]
    if phone:
        facts_.insert(0, T(f"Phone: {phone}", f"Điện thoại: {phone}"))
    lines.append(T("HOTEL INFO (only these facts are confirmed — anything else: ask_team): ",
                   "THÔNG TIN KHÁCH SẠN (chỉ những điều này là chắc chắn — điều khác: ask_team): ")
                 + ('; '.join(facts_) if facts_ else T('none published yet.', 'chưa có.')))
    return "\n".join(lines)
