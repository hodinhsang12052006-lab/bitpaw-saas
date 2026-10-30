# -*- coding: utf-8 -*-
"""
Gói AI cho ngành KỸ THUẬT / dịch vụ tại nhà (technical) — RESOURCE 'job': NHẬN VIỆC (job intake) + TRA TRẠNG THÁI.

Giống Jobber AI Receptionist / Housecall Pro CSR AI: khách nhắn "máy lạnh chảy nước ở 12 Lê Lợi" -> AI hỏi đủ tên, SĐT,
địa chỉ, mô tả hỏng hóc, ngày + buổi mong muốn, mức độ gấp -> tạo 1 việc THẬT trong db.tasks — đúng collection mà Bảng
điều phối (quanly_dichvu.html), Bản đồ điều phối (map_dashboard.html) và app nhân viên (app_nhanvien.html) đang đọc —
ở trạng thái 'Chờ Nhận' (chưa giao ai), cùng các trường như việc tạo tay (ten_khach, sdt, dia_chi, noi_dung, nguoi_nhan='',
lat/lng lấy bằng _geocode_address của app.py giống POST /api/tasks). AI KHÔNG hứa giờ tới, giá cuối hay người làm:
đội kỹ thuật gọi lại xác nhận.

Khẩn cấp (mùi gas, ngập nước, tia lửa / khói, điện giật): việc ghi mức 'emergency', cuộc chat chuyển người thật NGAY
(giống handoff_to_staff, urgent) + email chủ tiệm; câu trả lời bảo khách ra chỗ an toàn và gọi số khẩn cấp, không hẹn giờ.

Tra trạng thái: chỉ việc CHỨNG MINH được là của khách (SĐT đã xác minh khớp sdt của việc — kể cả việc nhân viên tạo tay;
hoặc việc AI tạo trong đúng cuộc chat này). Không bao giờ trả noi_dung của việc tạo tay (có thể chứa hoa hồng thợ).
Dùng chung tiện ích SĐT / quyền sở hữu / tiền tệ / giờ tiệm với ai_packs/retail.py (4 gói "yêu cầu" cùng 1 luật).
"""
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta

import ai_packs
from ai_packs import retail as _c
from mongo_client import db, next_mongo_id

INDUSTRIES = ('technical',)
RESOURCE = 'job'
# Việc lưu SĐT ở trường 'sdt' (đúng như bảng điều phối) — mã SMS 1 lần chỉ gửi cho SĐT từng có việc ở tiệm này
BOOKING_COLLECTIONS = (('tasks', 'sdt'),)

WINDOWS = {'morning': ('buổi sáng', 'morning'), 'afternoon': ('buổi chiều', 'afternoon'),
           'evening': ('buổi tối', 'evening'), 'any': ('giờ nào cũng được', 'any time')}
URGENCY = {'normal': ('bình thường', 'normal'), 'urgent': ('GẤP', 'URGENT'), 'emergency': ('KHẨN CẤP', 'EMERGENCY')}
WAITING, TAKEN, DONE = 'Chờ Nhận', 'Đã Nhận', 'Hoàn Thành'   # trạng thái thật của db.tasks (bảng điều phối)
EMERGENCY_NUMBER = {'AU': '000', 'US': '911', 'CA': '911', 'NZ': '111', 'GB': '999', 'VN': '114'}
MAX_DAYS_AHEAD = 90
# Từ khoá khẩn cấp. Tiếng Việt CÓ DẤU cho chữ dễ nhầm ("chảy nước", "bóng đèn bị cháy" không phải hoả hoạn -> chỉ
# "đang cháy / bốc cháy"), không dấu chỉ cho cụm không nhầm được ("dang chay" = "đang chạy" nên không dùng).
# Tiếng Anh tránh từ đơn dễ nhầm: "flood light", "spark plug", "fire alarm" không phải khẩn cấp.
_EMERGENCY_RE = re.compile(
    r"\b(gas leak|leaking gas|smell(s|ing)? (of )?gas|gas smell|carbon monoxide|co alarm|flooding|flooded|burst pipe|"
    r"water everywhere|sparks|sparking|electric(al)? shock|electrocut\w*|shock(ed)? me|burning smell|smell(s|ing)? (of )?burning|"
    r"smoke (is )?coming|smoking|on fire|caught fire|fire in)\b"
    r"|rò rỉ gas|rò gas|xì gas|mùi gas|ngập nước|nước ngập|bị ngập|đang ngập|ngập sàn|ngập nhà|ngập bếp|vỡ ống|chập điện|tia lửa|điện giật|giật điện|bốc khói|"
    r"có khói|mùi khét|đang cháy|bốc cháy|cháy nổ|hỏa hoạn|hoả hoạn"
    r"|\b(ro ri gas|xi gas|mui gas|chap dien|tia lua|dien giat|giat dien|vo ong nuoc|ngap nuoc|nuoc ngap|boc khoi|mui khet|boc chay)\b",
    re.I)
# Từ khoá bị PHỦ ĐỊNH trong cùng mệnh đề không phải khẩn cấp: AI hỏi sàng lọc nguy hiểm nên mô tả hay có "No burning smell
# or sparks" / "không có mùi khét". Chỉ tính là phủ định khi giữa từ phủ định và từ khoá CHỈ có từ đệm (có, bị, thấy, any,
# sign of...) hoặc 1 từ khoá khác nối bằng "or / hay"; mệnh đề cắt ở dấu câu và and / but / và / nhưng... — nên
# "not cooling, burning smell", "không chạy có mùi khét" vẫn là KHẨN CẤP. Không chắc thì coi là khẩn cấp.
_NEGATIONS = frozenset((
    "no", "not", "never", "without", "none", "nothing", "nor", "neither", "isn't", "aren't", "wasn't", "weren't", "don't",
    "doesn't", "didn't", "haven't", "hasn't", "hadn't", "can't", "cannot", "couldn't", "isnt", "arent", "wasnt", "dont",
    "doesnt", "didnt", "havent", "hasnt", "cant", "couldnt",
    "không", "chẳng", "chả", "chưa", "hông", "khong", "ko", "k", "kh", "hok", "chua"))
_NEG_FILLER = frozenset((
    "a", "an", "the", "any", "sign", "signs", "evidence", "trace", "traces", "hint", "of", "there", "there's", "theres",
    "is", "are", "was", "were", "be", "been", "it", "it's", "its", "i", "we", "they", "you", "do", "does", "did", "have",
    "has", "had", "see", "seen", "saw", "notice", "noticed", "smell", "smelled", "smelt", "detect", "detected", "feel",
    "felt", "hear", "heard", "seem", "seems", "seemed", "appear", "appears", "to", "look", "looks", "like", "real",
    "actual", "obvious", "visible", "more", "longer", "other", "also", "either", "even", "at", "all", "kind", "sort",
    "có", "bị", "thấy", "gì", "dấu", "hiệu", "hiện", "tượng", "nào", "hề", "còn", "cũng", "ngửi", "nghe", "là", "phải",
    "bất", "kỳ", "kì", "tí", "chút", "co", "bi", "thay", "gi", "dau", "hieu", "nao", "he", "con", "cung", "ngui"))
_NEG_JOIN = frozenset(("or", "nor", "hay", "hoặc", "hoac"))
_CLAUSE_BREAK = re.compile(r"[.,;:!?\n()\[\]]|\s[-–—]\s|\b(?:and|but|then|however|although|though|yet|now|và|nhưng|mà|"
                           r"rồi|thì|giờ|va|nhung|roi|thi|gio)\b", re.I)
_WORD = re.compile(r"\x00|[^\W_]+(?:'[^\W_]+)?")


def _fn(name, desc, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': desc,
                                             'parameters': {'type': 'object', 'properties': props, 'required': list(required)}}}


TOOLS = [
    _fn('technical_request_job',
        "Create a REAL job request on the business's dispatch board (status: waiting to be assigned). Collect first: the "
        "customer's name and phone number, the full service address, what is wrong, the preferred day and part of day, and "
        "how urgent it is. The team calls back to confirm a time — it is NOT scheduled. Never promise an arrival time or "
        "price. For gas smell, flooding, sparks, smoke or electric shock use urgency 'emergency'.",
        {'customer_name': {'type': 'string', 'description': "Customer's name."},
         'phone': {'type': 'string', 'description': "Customer's phone number."},
         'address': {'type': 'string', 'description': 'Full service address: street number + street, suburb/district, city.'},
         'problem': {'type': 'string', 'description': "What's wrong, in the customer's words (device, symptoms, since when)."},
         'preferred_date': {'type': 'string', 'description': 'Preferred day YYYY-MM-DD (business local date), if the customer has one.'},
         'preferred_window': {'type': 'string', 'enum': list(WINDOWS), 'description': 'Preferred part of the day.'},
         'urgency': {'type': 'string', 'enum': list(URGENCY), 'description': "normal, urgent (needs it soon) or emergency (danger now)."},
         'service_id': {'type': 'integer', 'description': 'Optional service_id from the SERVICE PRICE LIST if one clearly matches.'}},
        ['address', 'problem']),
    _fn('technical_job_status',
        "Check the status of THIS customer's own job requests (made in this chat, or under their verified phone number): "
        "waiting, assigned, on the way (with a live tracking link), or completed. If it fails with not_verified, say "
        "nothing about any job and pass on the message.",
        {'job_id': {'type': 'integer', 'description': 'Optional job number the customer mentions.'}}),
]
MANAGE_TOOLS = {'technical_job_status'}

PROMPT_RULES = {
    'en': ("FIELD SERVICE RULES: You take job requests; the team decides who goes and when. Before technical_request_job get "
           "the customer's name, phone number, full address (street number, street, suburb/city), what's wrong, preferred "
           "day + morning/afternoon/evening, and how urgent. Never promise an arrival time, a price for the repair, a "
           "specific person or that the job is booked — say the team will call to confirm. Don't diagnose faults or give "
           "repair instructions. DANGER (gas smell, flooding, sparks, smoke, electric shock): first tell them to get to a "
           "safe place and call the emergency number in the facts, then create the request with urgency 'emergency'."),
    'vi': ("LUẬT DỊCH VỤ KỸ THUẬT: Em chỉ NHẬN yêu cầu; đội kỹ thuật quyết định ai đi và lúc nào. Trước khi gọi "
           "technical_request_job cần: tên + SĐT khách, địa chỉ đầy đủ (số nhà, đường, phường/quận, thành phố), hỏng gì, ngày "
           "+ buổi mong muốn, mức độ gấp. Không hứa giờ tới, giá sửa, người làm hay \"đã đặt lịch\" — nói đội sẽ gọi xác nhận. "
           "Không chẩn đoán hay hướng dẫn tự sửa. NGUY HIỂM (mùi gas, ngập nước, tia lửa, khói, điện giật): trước hết bảo "
           "khách ra chỗ an toàn và gọi số khẩn cấp trong dữ kiện, rồi tạo yêu cầu với urgency 'emergency'."),
}


def _err(msg):
    return ai_packs.PackError(msg)


def _negated(text, start):
    """Từ khoá bắt đầu ở vị trí start có bị PHỦ ĐỊNH trong cùng mệnh đề không ('no gas smell', 'không có mùi khét',
    'No burning smell or sparks'). Từ khoá khác đứng trước trong mệnh đề được thay bằng dấu \\x00."""
    clause = _CLAUSE_BREAK.split(text[:start])[-1]
    toks = _WORD.findall(_EMERGENCY_RE.sub(' \x00 ', clause).lower())
    neg = max((i for i, t in enumerate(toks) if t in _NEGATIONS), default=-1)
    if neg < 0 or len(toks) - neg - 1 > 6:
        return False
    joined = False   # vừa qua 1 từ khoá khác: chỉ "or / hay" mới nối tiếp phủ định ("No burning smell or sparks")
    for t in toks[neg + 1:]:
        if t == '\x00':
            joined = True
        elif joined and t in _NEG_JOIN:
            joined = False
        elif joined or t not in _NEG_FILLER:
            return False
    return not joined


def is_emergency(text):
    """Có từ khoá nguy hiểm KHÔNG bị phủ định: 'sparks from the outlet' -> True; 'no sparks', 'không có mùi khét' -> False."""
    t = unicodedata.normalize('NFC', str(text or '')).replace('\u2019', "'")
    return any(not _negated(t, m.start()) for m in _EMERGENCY_RE.finditer(t))


def _clean(v, n):
    return re.sub(r'\s+', ' ', str(v or '')).strip()[:n]


def _geocode(business_id, address):
    """Toạ độ cho bản đồ điều phối — đúng hàm app._geocode_address (Nominatim + cache) mà POST /api/tasks dùng.
    Chỉ khi app đã nạp (gói chạy trong request của app); không thì để bản đồ điều phối tự ghim như việc tạo tay."""
    fn = getattr(sys.modules.get('app'), '_geocode_address', None)
    if not callable(fn):
        return None
    try:
        return fn(business_id, address)
    except Exception as e:
        print(f"[ai_packs.technical] geocode: {e}")
        return None


def _track_url(business_id, task_id):
    jt = sys.modules.get('job_tracking')   # job_tracking import app -> chỉ dùng khi app đã nạp (không tự import)
    if jt is None or not hasattr(jt, 'track_token'):
        return None
    base = (os.environ.get('PUBLIC_BASE_URL') or 'https://www.bitpawsoftware.com').rstrip('/')
    return f"{base}/track/{business_id}/{task_id}/{jt.track_token(business_id, task_id)}"


def _parse_day(v, today):
    if v in (None, ''):
        return None
    try:
        d = datetime.strptime(str(v).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        raise _err(f"preferred_date '{str(v)[:20]}' must be YYYY-MM-DD. Nothing was created.")
    if d < today:
        raise _err(f"{d.isoformat()} is in the past (today is {today.isoformat()} at the business). Ask for another day. Nothing was created.")
    if d > today + timedelta(days=MAX_DAYS_AHEAD):
        raise _err(f"That day is more than {MAX_DAYS_AHEAD} days ahead — ask for a nearer day. Nothing was created.")
    return d


def _flag_urgent(ctx, job_id, problem):
    """Khẩn cấp: chuyển cuộc chat cho người thật (cùng các trường handoff_to_staff ghi) để /ai_bot hiện đỏ + AI vào chế độ chờ."""
    cid = ctx.get('customer_id')
    if not cid:
        return
    now = datetime.now().isoformat()
    try:
        db.bot_customers.update_one({'id': cid}, {'$set': {
            'ai_paused': True, 'needs_human': True, 'handoff_reason': f"EMERGENCY job request #{job_id}: {problem[:200]}",
            'handoff_at': now, 'handoff_urgent': True, 'handoff_by_ai': True, 'hold_notice_at': now}})
    except Exception as e:
        print(f"[ai_packs.technical] flag urgent: {e}")


def _escalate(business_id, job, problem, svi):
    """Việc đã có (cùng khách + địa chỉ + ngày) mà giờ khách báo NGUY HIỂM -> urgency 'emergency' (nguyên tử: chỉ 1 lệnh
    nâng) + ghi vào noi_dung (Bảng điều phối / app nhân viên đọc trường này). True nếu lệnh này vừa nâng."""
    now = datetime.now().isoformat()
    before = db.tasks.find_one_and_update(
        {'business_id': business_id, 'id': job.get('id'), 'urgency': {'$ne': 'emergency'}},
        {'$set': {'urgency': 'emergency', 'emergency_problem': problem, 'escalated_at': now, 'escalated_by': 'ai_bot'}})
    if not before:
        return False
    body = before.get('noi_dung') or ''
    old = URGENCY.get(before.get('urgency') or 'normal', URGENCY['normal'])
    new = (body.replace(f"| Mức độ: {old[0]}", f"| Mức độ: {URGENCY['emergency'][0]}", 1)
               .replace(f"| Urgency: {old[1]}", f"| Urgency: {URGENCY['emergency'][1]}", 1)
           + (f"\n--- KHẨN CẤP, khách báo thêm qua chat AI: {problem}" if svi else
              f"\n--- EMERGENCY, the customer added in the AI chat: {problem}"))
    try:   # có điều kiện: không đè nếu nhân viên vừa sửa nội dung việc (urgency + báo chủ vẫn đã có)
        db.tasks.update_one({'business_id': business_id, 'id': job.get('id'), 'noi_dung': before.get('noi_dung')},
                            {'$set': {'noi_dung': new}})
    except Exception as e:
        print(f"[ai_packs.technical] escalate: {e}")
    return True


def _reply_expectation(business_id, vi):
    try:
        import ai_function_tools as aft
        return ' ' + aft.reply_expectation(business_id, vi)
    except Exception:
        return ''


def request_job(args, ctx):
    bid = _c._bid(ctx)
    address = _clean(args.get('address'), 200)
    problem = _clean(args.get('problem'), 600)
    if len(address) < 6 or not re.search(r'[^\W\d_]', address):
        raise _err('Ask for the full service address (street number and street, suburb/district, city). Nothing was created.')
    if len(problem) < 4:
        raise _err("Ask the customer to describe what's wrong (which device, what it does). Nothing was created.")
    window = str(args.get('preferred_window') or 'any').strip().lower()
    if window not in WINDOWS:
        raise _err(f"preferred_window must be one of {', '.join(WINDOWS)}. Nothing was created.")
    urgency = str(args.get('urgency') or 'normal').strip().lower()
    if urgency not in URGENCY:
        raise _err(f"urgency must be one of {', '.join(URGENCY)}. Nothing was created.")
    shop = _c._shop(bid)
    name, phone, pkey = _c._contact(args, ctx, 'creating the job request', shop)
    now = _c._now(ctx)
    day = _parse_day(args.get('preferred_date'), now.date())
    if is_emergency(problem):
        urgency = 'emergency'
    svc = None
    if args.get('service_id') not in (None, ''):
        svc = db.dichvu.find_one({'id': _c._int(args.get('service_id'), 'service_id'), 'business_id': bid},
                                 {'_id': 0, 'id': 1, 'ten_dich_vu': 1, 'gia_dich_vu': 1})
        if not svc:
            raise _err('That service_id is not in this business\'s service list — leave it out. Nothing was created.')
    svi, cur = _c.shop_vi(shop), _c.currency_of(bid, shop)
    vi = _c._vi(ctx)
    cid = ctx.get('customer_id')
    key = _c.request_key(ctx, phone, address, now.date().isoformat())

    when_vi = (f"{_c.VI_DOW[day.weekday()]} {day:%d/%m}" if day else 'chưa chọn ngày') + f", {WINDOWS[window][0]}"
    when_en = (day.strftime('%a %d %b') if day else 'no day given') + f", {WINDOWS[window][1]}"
    svc_line = (f"[DỊCH VỤ] {svc.get('ten_dich_vu')} [Giá Thu]: {_c.money(svc.get('gia_dich_vu'), cur)}\n--- " if svc else '')
    body = (f"{svc_line}[AI chat] {problem}\n--- Khách muốn: {when_vi} | Mức độ: {URGENCY[urgency][0]}" if svi else
            f"{svc_line}[AI chat] {problem}\n--- Preferred: {when_en} | Urgency: {URGENCY[urgency][1]}")
    job_id = next_mongo_id('tasks')
    doc = {'id': job_id, 'ten_khach': name, 'sdt': phone, 'dia_chi': address, 'noi_dung': body, 'trang_thai': WAITING,
           'nguoi_nhan': '', 'problem': problem, 'preferred_date': day.isoformat() if day else None,
           'preferred_window': window, 'urgency': urgency, 'service_id': svc and svc.get('id'), 'phone_key': pkey,
           'source': 'ai_bot', 'ai_conversation_id': cid, 'chat_token_hash': ctx.get('chat_token_hash') or None,
           'channel': ctx.get('channel') or 'web', 'created_at': datetime.now().isoformat(),
           'created_at_local': now.strftime('%Y-%m-%dT%H:%M')}
    pt = _geocode(bid, address)
    if pt:
        doc['lat'], doc['lng'] = pt
    # Tạo nguyên tử theo khoá (cùng khách + cùng địa chỉ + cùng ngày): khách nói "gửi giúp em" 2 lần -> vẫn 1 việc trên bảng
    saved, created = _c.insert_once(db.tasks, bid, key, doc, key_field='ai_dedupe_key')
    emergency = urgency == 'emergency'
    if not created and emergency and (saved or {}).get('trang_thai') == DONE:
        # việc cũ cùng địa chỉ hôm nay đã XONG: nguy hiểm là việc MỚI trên bảng (khoá riêng: khách báo lại vẫn chỉ 1 việc)
        saved, created = _c.insert_once(db.tasks, bid, key + ':emergency', doc, key_field='ai_dedupe_key')
    escalated = False
    if not created:
        old_id = (saved or {}).get('id')
        if not emergency or old_id is None:
            return {'success': True, 'already_requested': True, 'job_id': old_id, 'status': 'pending',
                    'note': f"A job request for this address was already sent today (job #{old_id}) — do not create "
                            "another. If this is a different problem, use ask_team to add it."}
        # KHẨN CẤP không bao giờ bị chống trùng nuốt mất: việc đang có được nâng lên khẩn cấp (báo chủ 1 lần), cuộc chat
        # vẫn chuyển người thật và khách vẫn được dặn ra chỗ an toàn + gọi số khẩn cấp
        job_id = old_id
        escalated = _escalate(bid, saved, problem, svi)
    if emergency:
        _flag_urgent(ctx, job_id, problem)
    if escalated:
        _c._notify(ctx, shop,
                   f"KHẨN CẤP — việc #{job_id} (đã có trên Bảng điều phối) giờ khách báo NGUY HIỂM qua chat AI: "
                   f"{name} {phone}, {address}. {problem[:200]}",
                   f"EMERGENCY — job #{job_id} (already on the dispatch board): the customer now reports DANGER in the AI "
                   f"chat: {name} {phone}, {address}. {problem[:200]}",
                   f"URGENT — Job request #{job_id} is now an EMERGENCY (the customer reported danger in the AI chat): "
                   f"{name} {phone}, {address}. Problem: {problem[:300]}. It is on the dispatch board — please call the "
                   "customer now.", 'technical_emergency', phone)
    elif created:
        _c._notify(ctx, shop,
                   f"{'KHẨN CẤP — ' if emergency else ''}Việc mới #{job_id} từ chat AI (đang Chờ Nhận trên Bảng điều phối): "
                   f"{name} {phone}, {address}. {problem[:200]} ({when_vi})",
                   f"{'EMERGENCY — ' if emergency else ''}New job #{job_id} from the AI chat (waiting on the dispatch board): "
                   f"{name} {phone}, {address}. {problem[:200]} ({when_en})",
                   f"{'URGENT — ' if emergency else ''}New job request #{job_id} from the AI chat: {name} {phone}, {address}. "
                   f"Problem: {problem[:300]}. Preferred: {when_en}. It is waiting on the dispatch board — please call the customer.",
                   'technical_emergency' if emergency else 'technical_job', phone)
    num = EMERGENCY_NUMBER.get(str(shop.get('country') or '').upper(), '')
    if emergency:
        tell = ((f"Nếu có nguy hiểm (mùi gas, tia lửa, khói, nước ngập gần ổ điện), mọi người ra chỗ an toàn và gọi {num or 'cấp cứu'} ngay. "
                 f"Em đã báo đội kỹ thuật yêu cầu KHẨN (việc #{job_id}); em không hứa được giờ tới, đội sẽ gọi lại cho mình.") if vi else
                (f"If anyone is in danger (gas smell, sparks, smoke, water near power), get everyone somewhere safe and call "
                 f"{num or 'emergency services'} now. I've sent your request to the team as URGENT (job #{job_id}); I can't promise "
                 "an arrival time — the team will call you.")) + _reply_expectation(bid, vi)
    else:
        tell = (f"Em đã gửi yêu cầu (việc #{job_id}) cho đội kỹ thuật. Đội sẽ gọi lại để chốt giờ ({when_vi}) — hiện CHƯA có lịch "
                "cho tới khi đội xác nhận." if vi else
                f"Your job request #{job_id} is in. The team will call you to confirm a time ({when_en}) — nothing is "
                "scheduled until they confirm.")
    out = {'success': True, 'job_id': job_id, 'status': 'pending', 'board_status': 'waiting_for_assignment',
           'urgency': urgency, 'preferred': when_en, 'located_on_map': bool(pt), 'tell_customer': tell,
           'note': 'Never promise an arrival time, a price or who will come. The job is not scheduled yet.'}
    if not created:   # khẩn cấp trên việc đã có từ trước hôm nay
        out.update({'already_requested': True, 'escalated': escalated,
                    'board_status': {WAITING: 'waiting_for_assignment', TAKEN: 'assigned', DONE: 'completed'}.get(saved.get('trang_thai'), 'in_progress'),
                    'located_on_map': saved.get('lat') is not None,
                    'note': f"Job #{job_id} for this address was already on the dispatch board today — it is now marked "
                            "EMERGENCY and the team has been alerted. Do not create another. Never promise an arrival "
                            "time, a price or who will come."})
    return out


def _job_view(t, business_id, shop):
    st = t.get('trang_thai')
    if st == DONE:
        state, meaning = 'completed', 'the job is marked completed'
    elif st == TAKEN and t.get('on_way_at'):
        state, meaning = 'on_the_way', 'someone from the team is on the way'
    elif st == TAKEN:
        state, meaning = 'assigned', 'assigned to a team member; the team confirms the visit time'
    elif st == WAITING:
        state, meaning = 'waiting', 'received — waiting to be assigned to a team member'
    else:
        state, meaning = 'in_progress', 'being handled by the team'
    out = {'job_id': t.get('id'), 'state': state, 'meaning': meaning, 'address': t.get('dia_chi') or ''}
    if t.get('source') == 'ai_bot':   # việc tạo tay: noi_dung có thể chứa hoa hồng nội bộ -> không trả
        out['problem'] = t.get('problem')
        if t.get('preferred_date') or t.get('preferred_window'):
            out['preferred'] = ' '.join(x for x in (t.get('preferred_date'), WINDOWS.get(t.get('preferred_window') or '', ('', ''))[1]) if x)
    if state in ('assigned', 'on_the_way') and t.get('nguoi_nhan'):
        parts = str(t['nguoi_nhan']).split()   # chỉ TÊN gọi (tên Việt là chữ cuối), như trang theo dõi công khai
        out['assigned_to'] = parts[-1 if str(shop.get('country') or '').upper() == 'VN' else 0] if parts else None
    if state == 'on_the_way':
        url = _track_url(business_id, t.get('id'))
        if url:
            out['live_tracking_link'] = url
    return out


def job_status(args, ctx):
    bid = _c._bid(ctx)
    ors = []
    k = _c.phone_key(ctx.get('phone'), _c._country(ctx))
    if k:  # SĐT đã xác minh: cả việc nhân viên tạo tay (sdt gõ tay dạng bất kỳ, so ĐỦ số) lẫn việc AI tạo
        ors.append({'phone_key': k})
        rx = _c.phone_regex(k)
        if rx:
            ors.append({'sdt': {'$regex': rx}})
    own = _c.owner_filter(ctx)
    for c in (own or {}).get('$or', []):
        if c not in ors:
            ors.append(c)
    if not ors:
        raise _c._not_verified(ctx, 'yêu cầu sửa chữa', 'job requests')
    flt = {'business_id': bid, '$or': ors}
    if args.get('job_id') not in (None, ''):
        flt['id'] = _c._int(args.get('job_id'), 'job_id')
    rows = list(db.tasks.find(flt, {'_id': 0, 'id': 1, 'trang_thai': 1, 'dia_chi': 1, 'nguoi_nhan': 1, 'on_way_at': 1,
                                    'source': 1, 'problem': 1, 'preferred_date': 1, 'preferred_window': 1}).sort('id', -1).limit(5))
    shop = _c._shop(bid) if rows else {}
    res = {'success': True, 'jobs': [_job_view(t, bid, shop) for t in rows]}
    if not rows:
        res['note'] = ('No job found for this chat' + (' or phone number.' if k else '.') +
                       ' Jobs booked another way may not show here — the customer can call the business.')
    return res


def facts(business_id, lang, now_local):
    """Dữ kiện riêng của gói (giờ mở cửa + thông tin tiệm + kho câu hỏi do customer_context.facts thêm cho mọi gói)."""
    lines = []
    shop = _c._shop(business_id)
    cur = _c.currency_of(business_id, shop)
    try:
        svcs = list(db.dichvu.find({'business_id': business_id}, {'_id': 0, 'id': 1, 'ten_dich_vu': 1, 'gia_dich_vu': 1})
                    .sort('id', 1).limit(40))
    except Exception:
        svcs = []
    if svcs:  # chỉ tên + giá thu của tiệm; KHÔNG bao giờ đưa tien_tua (hoa hồng thợ)
        lines.append("SERVICE PRICE LIST (the business's own list prices; parts and anything found on site are extra and "
                     "confirmed by the team):\n" + '\n'.join(f"- service_id {s.get('id')}: {s.get('ten_dich_vu')} — "
                                                            f"{_c.money(s.get('gia_dich_vu'), cur)}" for s in svcs))
    num = EMERGENCY_NUMBER.get(str(shop.get('country') or '').upper())
    lines.append("JOB REQUESTS: you can't see the team's schedule. technical_request_job puts the job on the dispatch board as "
                 "waiting; the team calls the customer to confirm the time. Service area is confirmed by the team."
                 + (f" EMERGENCY NUMBER in this country: {num}." if num else ''))
    return '\n'.join(lines)


_HANDLERS = {'technical_request_job': request_job, 'technical_job_status': job_status}


def execute(name, args, ctx):
    fn = _HANDLERS.get(name)
    if fn is None:
        raise _err(f"Unknown field-service tool '{name}'.")
    return fn(args if isinstance(args, dict) else {}, ctx or {})
