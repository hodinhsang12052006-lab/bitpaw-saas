# -*- coding: utf-8 -*-
"""
Gói AI cho ngành VĂN PHÒNG (office) — RESOURCE 'consult': hỏi đáp (FAQ từ dữ liệu của văn phòng) + YÊU CẦU TƯ VẤN / hẹn gặp.

AI không xem được lịch của ai: khách nói chủ đề cần tư vấn + ngày giờ mong muốn + hình thức (gặp trực tiếp / điện thoại /
video) + tên + SĐT -> 1 dòng db.consultation_requests (status 'pending') mà văn phòng xem ở trang Yêu cầu tư vấn
(/requests/consultations — retail_holds_bp.py) + email báo chủ. Văn phòng gọi lại chốt giờ; AI luôn nói "chưa có lịch".
Giờ khách muốn được kiểm theo giờ làm việc chủ văn phòng đã nhập (Cài đặt đặt lịch) để không nhận giờ văn phòng đóng cửa.
AI không đưa tư vấn chuyên môn (pháp lý, thuế, kế toán, tài chính, di trú) — chỉ dữ kiện của văn phòng.
Dùng chung tiện ích SĐT / tiền tệ / giờ / chống trùng với ai_packs/retail.py.
"""
import re
from datetime import datetime, timedelta

import ai_packs
import booking_rules
from ai_packs import retail as _c
from mongo_client import db, next_mongo_id

INDUSTRIES = ('office',)
RESOURCE = 'consult'
STATUSES = ('pending', 'confirmed', 'done', 'declined', 'cancelled')
MODES = {'in_person': ('gặp trực tiếp', 'in person'), 'phone': ('gọi điện', 'phone call'), 'video': ('gọi video', 'video call')}
MAX_DAYS_AHEAD = 180


def _fn(name, desc, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': desc,
                                             'parameters': {'type': 'object', 'properties': props, 'required': list(required)}}}


TOOLS = [
    _fn('office_request_consultation',
        "Send a REAL consultation / meeting request to the office (it appears on the office's Consultation requests list). "
        "Collect first: the topic, preferred day and time if they have one, in person / phone / video, and the customer's "
        "name and phone number. The office calls back to confirm a time — nothing is booked until then.",
        {'topic': {'type': 'string', 'description': 'What they want to discuss, in a sentence.'},
         'preferred_date': {'type': 'string', 'description': 'Preferred day YYYY-MM-DD (office local date), optional.'},
         'preferred_time': {'type': 'string', 'description': 'Preferred time HH:MM (24h, office local time), optional.'},
         'mode': {'type': 'string', 'enum': list(MODES), 'description': 'How they want to meet (optional).'},
         'note': {'type': 'string', 'description': 'Anything else the office should know (optional).'},
         'customer_name': {'type': 'string', 'description': "Customer's name."},
         'phone': {'type': 'string', 'description': "Customer's phone number."},
         'email': {'type': 'string', 'description': "Customer's email (optional)."}},
        ['topic']),
]
MANAGE_TOOLS = set()

PROMPT_RULES = {
    'en': ("OFFICE RULES: Answer only from the office's facts below. You can't see anyone's calendar: a consultation is a "
           "REQUEST the office confirms by phone — never say a meeting is booked or confirmed. Before "
           "office_request_consultation get the topic, preferred day/time (within opening hours), in person / phone / video, "
           "name and phone number. Never give legal, tax, accounting, financial, immigration or other professional advice, "
           "and never quote fees that aren't in the facts — use ask_team."),
    'vi': ("LUẬT VĂN PHÒNG: Chỉ trả lời từ dữ kiện của văn phòng bên dưới. Em không xem được lịch của ai: hẹn tư vấn là YÊU "
           "CẦU, văn phòng gọi lại xác nhận — không bao giờ nói đã đặt lịch hay đã xác nhận. Trước khi gọi "
           "office_request_consultation cần chủ đề, ngày/giờ mong muốn (trong giờ làm việc), gặp trực tiếp / điện thoại / "
           "video, tên và SĐT. Không đưa tư vấn pháp lý, thuế, kế toán, tài chính, di trú hay chuyên môn khác, không báo phí "
           "không có trong dữ kiện — dùng ask_team."),
}


def _err(msg):
    return ai_packs.PackError(msg)


def _clean(v, n):
    return re.sub(r'\s+', ' ', str(v or '')).strip()[:n]


def _check_when(business_id, now, date_s, time_s, lang='en'):
    """(ngày, 'HH:MM' | None) đã kiểm: không ở quá khứ, không quá xa, trong giờ làm việc chủ văn phòng đã nhập. Giờ làm
    việc trong lời từ chối theo 1 kiểu giờ chung với prompt khách, theo ngôn ngữ chat (`lang`): 'Thu 9:00 am – 5:00 pm' /
    'T5 09:00 – 17:00' (trước: '09:00-17:00' 24 giờ cạnh prompt 12 giờ)."""
    if date_s in (None, ''):
        if time_s not in (None, ''):
            raise _err('Ask which day they want — a time alone is not enough. Nothing was sent.')
        return None, None
    try:
        day = datetime.strptime(str(date_s).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        raise _err(f"preferred_date '{str(date_s)[:20]}' must be YYYY-MM-DD. Nothing was sent.")
    if day < now.date():
        raise _err(f"{day.isoformat()} is in the past (today is {now.date().isoformat()} at the office). Ask for another day. Nothing was sent.")
    if day > now.date() + timedelta(days=MAX_DAYS_AHEAD):
        raise _err('That day is more than 6 months ahead — ask for a nearer day. Nothing was sent.')
    tm = None
    if time_s not in (None, ''):
        m = re.match(r'^\s*([01]?\d|2[0-3]):([0-5]\d)', str(time_s))
        if not m:
            raise _err(f"preferred_time '{str(time_s)[:10]}' must be HH:MM (24h). Nothing was sent.")
        tm = f"{int(m.group(1)):02d}:{m.group(2)}"
    rules = booking_rules.get_rules(business_id)
    if rules.get('configured'):
        hrs = booking_rules.hours_on(rules, day)
        if not hrs:
            raise _err(f"The office is closed on {day:%A} ({_c._hours_line(rules, lang)}). Ask for another day. Nothing was sent.")
        if tm:
            mins = int(tm[:2]) * 60 + int(tm[3:])
            if not hrs[0] <= mins < hrs[1]:
                import reservations_core
                span = reservations_core.span_text(reservations_core.DAY_KEYS[day.weekday()], hrs[0], hrs[1], lang)
                raise _err(f"{tm} is outside office hours on {day:%A} ({span}). Ask for a time within those hours. "
                           "Nothing was sent.")
    if tm and day == now.date() and tm <= now.strftime('%H:%M'):
        raise _err(f"{tm} today has already passed (it is {now:%H:%M} at the office). Ask for a later time. Nothing was sent.")
    return day, tm


def request_consultation(args, ctx):
    bid = _c._bid(ctx)
    topic = _clean(args.get('topic'), 300)
    if len(topic) < 3:
        raise _err('Ask what they want to discuss. Nothing was sent.')
    mode = str(args.get('mode') or '').strip().lower() or None
    if mode and mode not in MODES:
        raise _err(f"mode must be one of {', '.join(MODES)}. Nothing was sent.")
    now = _c._now(ctx)
    day, tm = _check_when(bid, now, args.get('preferred_date'), args.get('preferred_time'), 'vi' if _c._vi(ctx) else 'en')
    email = _c.clean_email(args.get('email'))
    shop = _c._shop(bid)
    name, phone, pkey = _c._contact(args, ctx, 'sending the consultation request', shop)
    note = _clean(args.get('note'), 500)
    _c.ensure_indexes('consultation_requests')
    vi = _c._vi(ctx)
    rid = next_mongo_id('consultation_requests')
    key = _c.request_key(ctx, phone, topic, str(day or ''), tm or '', now.date().isoformat())
    doc = {'id': rid, 'business_id': bid, 'topic': topic, 'preferred_date': day.isoformat() if day else None,
           'preferred_time': tm, 'mode': mode, 'note': note, 'customer_name': name, 'customer_phone': phone,
           'phone_key': pkey, 'email': email, 'status': 'pending', 'source': 'ai_bot',
           'ai_conversation_id': ctx.get('customer_id'), 'chat_token_hash': ctx.get('chat_token_hash') or None,
           'channel': ctx.get('channel') or 'web', 'created_at': datetime.now().isoformat(),
           'created_at_local': now.strftime('%Y-%m-%dT%H:%M')}
    saved, created = _c.insert_once(db.consultation_requests, bid, key, doc)
    if not created and not _c.owns_request(saved, ctx, phone):
        # cùng khoá nhưng chat chưa chứng minh là chủ (trình duyệt khác gõ cùng SĐT): không lộ mã yêu cầu đã có
        old = (saved or {}).get('id')
        return _c.passed_to_team(
            ctx, shop,
            f"Chat AI xin TƯ VẤN ({topic}) cho {name} {phone} — trùng yêu cầu tư vấn #{old} đã có hôm nay (cùng SĐT, cùng "
            "nội dung) nên AI KHÔNG tạo thêm (chat chưa xác minh là chủ yêu cầu đó). Văn phòng liên hệ khách để xác nhận.",
            f"The AI chat asked for a CONSULTATION ({topic}) for {name} {phone} — it matches consultation request #{old} "
            "from today (same phone and details), so nothing new was created (the chat isn't verified as its owner). "
            "Please confirm with the customer.",
            'Em đã chuyển yêu cầu tư vấn cho văn phòng — văn phòng sẽ gọi số điện thoại của mình để xác nhận giờ. Hiện CHƯA '
            'có lịch cho tới khi văn phòng xác nhận.',
            "I've passed your consultation request to the office — they'll call you on your phone number to confirm a "
            "time. Nothing is booked until they confirm.")
    if not created:
        return {'success': True, 'already_requested': True, 'consult_request_id': (saved or {}).get('id'), 'status': 'pending',
                'note': 'This consultation request was already sent today — do not send it again.'}
    when_vi = (f"{_c.VI_DOW[day.weekday()]} {day:%d/%m}" + (f" lúc {tm}" if tm else '')) if day else 'chưa chọn ngày'
    when_en = (day.strftime('%a %d %b') + (f" at {tm}" if tm else '')) if day else 'no day given'
    how_vi, how_en = (MODES[mode] if mode else ('', ''))
    _c._notify(ctx, shop,
               f"Yêu cầu TƯ VẤN mới #{rid} từ chat AI: {topic} — {name} {phone}. Muốn: {when_vi}" + (f", {how_vi}" if how_vi else '') + '.',
               f"New CONSULTATION request #{rid} from the AI chat: {topic} — {name} {phone}. Preferred: {when_en}"
               + (f", {how_en}" if how_en else '') + '.',
               f"New consultation request #{rid}: {topic}. Contact: {name} {phone}" + (f", {email}" if email else '')
               + f". Preferred: {when_en}" + (f", {how_en}" if how_en else '') + (f". Note: {note}" if note else '')
               + ". See Consultation requests in BitPaw and call the customer to confirm.", 'consult_request', phone)
    tell = (f"Em đã gửi yêu cầu tư vấn #{rid} ({when_vi}) cho văn phòng. Văn phòng sẽ gọi {phone} để xác nhận giờ — hiện CHƯA "
            "có lịch cho tới khi văn phòng xác nhận." if vi else
            f"I've sent your consultation request #{rid} ({when_en}) to the office. They'll call {phone} to confirm a time — "
            "nothing is booked until they confirm.")
    return {'success': True, 'consult_request_id': rid, 'status': 'pending', 'tell_customer': tell,
            'note': 'Pending: never say the meeting is booked or confirmed.'}


def facts(business_id, lang, now_local):
    """Dữ kiện riêng của gói. Giờ làm việc, thông tin văn phòng và câu hỏi thường gặp (kho câu hỏi chủ văn phòng nhập ở
    trang AI knowledge) do customer_context.facts thêm cho mọi gói — FAQ của văn phòng là phần đó."""
    lines = []
    lines.append("CONSULTATIONS: you can't see anyone's calendar. office_request_consultation sends a request; the office "
                 "calls the customer to confirm the time. Fees, services and advice beyond these facts: use ask_team.")
    return '\n'.join(lines)


_HANDLERS = {'office_request_consultation': request_consultation}


def execute(name, args, ctx):
    fn = _HANDLERS.get(name)
    if fn is None:
        raise _err(f"Unknown office tool '{name}'.")
    return fn(args if isinstance(args, dict) else {}, ctx or {})
