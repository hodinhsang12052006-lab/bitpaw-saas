"""
Luật đặt lịch của từng tiệm — DÙNG CHUNG cho form đặt lịch công khai, trợ lý AI và lịch của chủ tiệm.

Trước đây không có giờ mở cửa / thời lượng dịch vụ / sức chứa: khách (và AI) đặt được 11 giờ đêm, 2 khách đặt cùng giờ
dù chỉ 1 thợ đi làm, AI không biết tiệm ở đâu, có chỗ gửi xe không. Giống các phần mềm đặt lịch đang dẫn đầu
(Fresha, Square Appointments, Vagaro): giờ mở cửa theo thứ, bước giờ, đặt trước tối thiểu/tối đa, thời lượng từng
dịch vụ, sức chứa = số thợ đang có ca (lấy từ Lịch ca tuần đã công bố — shift_roster.py), và "thông tin tiệm" cho AI.

Không import app.py (để booking_engine.py, ai_function_tools.py đều import được).
"""
import time
from datetime import date, datetime, timedelta

from mongo_client import db

DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
DEFAULT_HOURS = {'mon': ['09:00', '19:00'], 'tue': ['09:00', '19:00'], 'wed': ['09:00', '19:00'], 'thu': ['09:00', '20:00'],
                 'fri': ['09:00', '20:00'], 'sat': ['09:00', '18:00'], 'sun': ['10:00', '17:00']}
DEFAULTS = {
    'hours': DEFAULT_HOURS,          # None cho ngày nghỉ
    'slot_minutes': 15,
    'min_lead_minutes': 60,          # đặt trước tối thiểu
    'max_advance_days': 60,
    'default_duration': 60,
    'capacity': 0,                   # 0 = tự tính theo số thợ đang có ca / đang làm
    'durations': {},                 # {"<service_id>": phút}
    'auto_confirm': True,            # lịch hợp lệ (đúng giờ mở cửa, còn chỗ) xác nhận ngay như Fresha; False = chủ tiệm duyệt tay
    'info': {'address': '', 'parking': '', 'payments': '', 'gift_cards': '', 'cancellation_policy': '', 'other': ''},
}
INFO_LABELS = {'address': 'Address', 'parking': 'Parking', 'payments': 'Payment methods accepted', 'gift_cards': 'Gift cards / vouchers',
               'cancellation_policy': 'Cancellation / late policy', 'other': 'Other notes'}


REASON_TEXT = {
    'in_the_past': ('That time has already passed.', 'Giờ này đã qua rồi.'),
    'too_soon': ('That is too soon — please book a little further ahead.', 'Giờ này sát quá, vui lòng đặt muộn hơn một chút.'),
    'too_far_ahead': ('That date is too far ahead for online booking.', 'Ngày này xa quá, chưa nhận đặt online.'),
    'closed_that_day': ('The business is closed that day.', 'Hôm đó tiệm nghỉ.'),
    'outside_opening_hours': ('That time is outside opening hours.', 'Giờ này ngoài giờ mở cửa.'),
    'staff_not_working': ('That team member is not working then.', 'Thợ này không có ca giờ đó.'),
    'staff_busy': ('That team member is already booked then.', 'Thợ này đã có khách giờ đó.'),
    'fully_booked': ('That time is fully booked.', 'Giờ này đã kín chỗ.'),
}


class SlotUnavailable(Exception):
    """Giờ khách chọn không đặt được (đóng cửa, quá sát giờ, quá xa, hết chỗ, thợ không có ca/bận)."""

    def __init__(self, reason, alternatives=None):
        super().__init__(reason)
        self.reason = reason
        self.alternatives = alternatives or []


COUNTRY_TZ = {'AU': 'Australia/Sydney', 'US': 'America/New_York', 'VN': 'Asia/Ho_Chi_Minh', 'CA': 'America/Toronto',
              'NZ': 'Pacific/Auckland', 'GB': 'Europe/London'}


_CACHE = {}
CACHE_TTL = 20  # giây — mỗi lượt AI đặt lịch đọc lại luật/tên thợ/múi giờ ~13 lần tới Atlas (~1 giây); lưu cài đặt thì xoá ngay


def _cached(key, fn, ttl=CACHE_TTL):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


def local_now(business_id):
    """Giờ hiện tại tại tiệm (không múi giờ) — theo múi giờ ở trang Nhắn tin, không có thì theo quốc gia."""
    from zoneinfo import ZoneInfo
    def _tz():
        t = (db.messaging_settings.find_one({'business_id': business_id}, {'_id': 0, 'timezone': 1}) or {}).get('timezone')
        if not t:
            country = ((db.businesses.find_one({'id': business_id}, {'_id': 0, 'country': 1}) or {}).get('country') or '').upper()
            t = COUNTRY_TZ.get(country)
        return t
    tz = _cached(('tz', business_id), _tz)
    try:
        return datetime.now(ZoneInfo(tz)).replace(tzinfo=None) if tz else datetime.now()
    except Exception:
        return datetime.now()


def _hm(s):
    h, m = str(s).split(':')[:2]
    return int(h) * 60 + int(m)


def get_rules(business_id):
    row = _cached(('rules', business_id), lambda: db.booking_settings.find_one({'business_id': business_id}, {'_id': 0}) or {})
    rules = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k in DEFAULTS:
        if k in row and row[k] is not None:
            if isinstance(DEFAULTS[k], dict) and isinstance(row[k], dict):
                rules[k].update(row[k])
            else:
                rules[k] = row[k]
    rules['configured'] = bool(row.get('hours'))
    return rules


def save_rules(business_id, data):
    clean = {}
    hours = data.get('hours')
    if isinstance(hours, dict):
        h = {}
        for d in DAY_KEYS:
            v = hours.get(d)
            if not v:
                h[d] = None
                continue
            try:
                o, c = str(v[0]), str(v[1])
                if not (0 <= _hm(o) < _hm(c) <= 24 * 60):
                    raise ValueError
            except (ValueError, IndexError, TypeError):
                raise ValueError(f'Giờ mở cửa ngày {d} không hợp lệ.')
            h[d] = [o[:5], c[:5]]
        clean['hours'] = h
    for k, lo, hi in (('slot_minutes', 5, 120), ('min_lead_minutes', 0, 7 * 24 * 60), ('max_advance_days', 1, 365),
                      ('default_duration', 5, 600), ('capacity', 0, 200)):
        if k in data:
            try:
                clean[k] = max(lo, min(int(data[k]), hi))
            except (TypeError, ValueError):
                raise ValueError(f'{k} không hợp lệ.')
    if isinstance(data.get('durations'), dict):
        dur = {}
        for sid, mins in data['durations'].items():
            try:
                m = int(mins)
            except (TypeError, ValueError):
                continue
            if 5 <= m <= 600:
                dur[str(int(sid))] = m
        clean['durations'] = dur
    if 'auto_confirm' in data:
        clean['auto_confirm'] = bool(data['auto_confirm'])
    if isinstance(data.get('info'), dict):
        clean['info'] = {k: str(data['info'].get(k) or '').strip()[:600] for k in DEFAULTS['info']}
    clean['updated_at'] = datetime.now().isoformat()
    db.booking_settings.update_one({'business_id': business_id}, {'$set': clean}, upsert=True)
    _CACHE.pop(('rules', business_id), None)
    return get_rules(business_id)


def duration_of(rules, service_id):
    return int((rules.get('durations') or {}).get(str(service_id)) or rules['default_duration'])


def hours_on(rules, day):
    v = (rules.get('hours') or {}).get(DAY_KEYS[day.weekday()])
    return (_hm(v[0]), _hm(v[1])) if v else None


def _parse(book_time):
    return datetime.fromisoformat(str(book_time)[:19])


def _day_appointments(business_id, day, exclude_id=None, rules=None):
    """Lịch còn hiệu lực trong ngày: [(start_min, end_min, staff_id)] (thời lượng theo dịch vụ của từng lịch)."""
    rules = rules or get_rules(business_id)
    out = []
    for a in db.appointments.find({'business_id': business_id, 'status': {'$nin': ['cancelled', 'canceled']},
                                   'book_time': {'$gte': day.isoformat(), '$lt': (day + timedelta(days=1)).isoformat()}},
                                  {'_id': 0, 'id': 1, 'book_time': 1, 'service_id': 1, 'staff_id': 1}):
        if exclude_id is not None and a.get('id') == exclude_id:
            continue
        try:
            t = _parse(a['book_time'])
        except (ValueError, KeyError):
            continue
        s = t.hour * 60 + t.minute
        out.append((s, s + duration_of(rules, a.get('service_id')), a.get('staff_id')))
    return out


def _staff_names(business_id):
    return _cached(('staff', business_id), lambda: _staff_names_db(business_id))


def _staff_names_db(business_id):
    """{mã thợ (chuỗi): tên} theo ĐÚNG loại mã lịch hẹn của ngành đó đang dùng: Nails = mã nhân viên (employees.ma_nv, như
    trang đặt lịch Nails/POS Nails), ngành khác = staff.id (như trang đặt lịch Spa)."""
    biz = db.businesses.find_one({'id': business_id}, {'_id': 0, 'industry_code': 1}) or {}
    if (biz.get('industry_code') or '') == 'nail':
        rows = {e['ma_nv']: e.get('ho_ten') or '' for e in db.employees.find({'business_id': business_id, 'linh_vuc': 'Nails'},
                                                                              {'_id': 0, 'ma_nv': 1, 'ho_ten': 1}) if e.get('ma_nv')}
        if rows:
            return rows
    return {str(s['id']): s.get('name') or '' for s in db.staff.find({'business_id': business_id, 'is_active': {'$ne': False}},
                                                                      {'_id': 0, 'id': 1, 'name': 1})}


def _roster_on(business_id, day):
    """Ca ĐÃ CÔNG BỐ trong ngày (Lịch ca tuần): {tên_nhân_viên_thường: [(start,end)]}. Rỗng = chưa xếp ca ngày này."""
    shifts = {}
    for s in db.roster_shifts.find({'business_id': business_id, 'date': day.isoformat(), 'status': 'published'},
                                   {'_id': 0, 'ho_ten': 1, 'start': 1, 'end': 1}):
        a, b = _hm(s['start']), _hm(s['end'])
        if b <= a:
            b += 24 * 60
        shifts.setdefault((s.get('ho_ten') or '').strip().lower(), []).append((a, b))
    return shifts


def find_staff(business_id, name):
    """Khớp tên thợ khách nói ("Chloe") với danh sách thợ. Trả (id, tên đầy đủ) hoặc None."""
    if not name:
        return None
    key = str(name).strip().lower()
    names = _staff_names(business_id)
    exact = [(i, n) for i, n in names.items() if n.lower() == key]
    first = [(i, n) for i, n in names.items() if n.lower().split(' ')[0] == key.split(' ')[0]]
    part = [(i, n) for i, n in names.items() if key in n.lower()]
    for group in (exact, first, part):
        if len(group) == 1:
            return group[0]
    return None


def capacity_at(business_id, rules, day, start, end, roster=None):
    """Bao nhiêu khách cùng lúc được trong khoảng [start,end): số thợ có ca phủ khoảng đó (nếu ngày đã xếp ca),
    không thì sức chứa cấu hình, không nữa thì số thợ đang làm (tối thiểu 1)."""
    roster = _roster_on(business_id, day) if roster is None else roster
    if roster:
        return sum(1 for spans in roster.values() if any(a <= start and b >= end for a, b in spans))
    if rules.get('capacity'):
        return int(rules['capacity'])
    return max(1, len(_staff_names(business_id)))


def _day_context(business_id, day, rules, exclude_id=None):
    """Dữ liệu 1 ngày đọc 1 lần (lịch hẹn, ca, tên thợ) — available_slots thử ~40 giờ trong ngày; trước đây mỗi giờ
    đọc lại DB 5 lần (~200 lượt gọi Atlas, 10-28 giây mỗi câu trả lời của AI)."""
    return {'day': day, 'appts': _day_appointments(business_id, day, exclude_id, rules), 'roster': _roster_on(business_id, day),
            'names': _staff_names(business_id)}


def check_slot(business_id, when, service_id=None, staff_id=None, rules=None, now=None, guests=1, exclude_id=None, _ctx=None):
    """Raise SlotUnavailable nếu không đặt được `when` (datetime giờ địa phương của tiệm)."""
    rules = rules or get_rules(business_id)
    now = now or local_now(business_id)
    dur = duration_of(rules, service_id)
    day = when.date()
    start = when.hour * 60 + when.minute
    end = start + dur
    hrs = hours_on(rules, day)
    if when < now + timedelta(minutes=rules['min_lead_minutes']):
        raise SlotUnavailable('too_soon' if when >= now else 'in_the_past')
    if day > (now + timedelta(days=rules['max_advance_days'])).date():
        raise SlotUnavailable('too_far_ahead')
    if not hrs:
        raise SlotUnavailable('closed_that_day')
    if start < hrs[0] or end > hrs[1]:
        raise SlotUnavailable('outside_opening_hours')
    ctx = _ctx if (_ctx and _ctx.get('day') == day) else _day_context(business_id, day, rules, exclude_id)
    appts = ctx['appts']
    overlap = [a for a in appts if a[0] < end and start < a[1]]
    roster = ctx['roster']
    if staff_id is not None:
        name = (ctx['names'].get(str(staff_id)) or '').strip().lower()
        if roster and not any(a <= start and b >= end for a, b in roster.get(name, [])):
            raise SlotUnavailable('staff_not_working')
        if any(str(a[2]) == str(staff_id) for a in overlap):
            raise SlotUnavailable('staff_busy')
    if roster:
        cap = sum(1 for spans in roster.values() if any(a <= start and b >= end for a, b in spans))
    else:
        cap = int(rules['capacity']) if rules.get('capacity') else max(1, len(ctx['names']))
    if len(overlap) + guests > cap:
        raise SlotUnavailable('fully_booked')
    return True


def available_slots(business_id, day, service_id=None, staff_id=None, limit=12, now=None, guests=1, exclude_id=None):
    """Các giờ bắt đầu còn đặt được trong ngày `day` (date), theo bước giờ của tiệm."""
    rules = get_rules(business_id)
    now = now or local_now(business_id)
    hrs = hours_on(rules, day)
    if not hrs:
        return []
    out = []
    t = hrs[0]
    ctx = _day_context(business_id, day, rules, exclude_id)
    while t + duration_of(rules, service_id) <= hrs[1] and len(out) < limit * 4:
        when = datetime.combine(day, datetime.min.time()) + timedelta(minutes=t)
        try:
            check_slot(business_id, when, service_id, staff_id, rules=rules, now=now, guests=guests, exclude_id=exclude_id, _ctx=ctx)
            out.append(when.strftime('%H:%M'))
        except SlotUnavailable:
            pass
        t += rules['slot_minutes']
    if len(out) > limit:  # rải đều trong ngày thay vì chỉ lấy buổi sáng
        step = len(out) / limit
        out = [out[int(i * step)] for i in range(limit)]
    return out


def open_status(business_id, rules=None, now=None):
    """Tiệm đang mở không, đóng lúc mấy giờ, lần mở tới là khi nào (để hẹn khách lúc nào nhân viên trả lời)."""
    rules = rules or get_rules(business_id)
    now = now or local_now(business_id)
    m = now.hour * 60 + now.minute
    hrs = hours_on(rules, now.date())
    if hrs and hrs[0] <= m < hrs[1]:
        return {'open_now': True, 'closes_at': f"{hrs[1] // 60:02d}:{hrs[1] % 60:02d}", 'next_open': None}
    for i in range(0, 8):
        d = now.date() + timedelta(days=i)
        h = hours_on(rules, d)
        if h and (i > 0 or m < h[0]):
            label = 'today' if i == 0 else ('tomorrow' if i == 1 else DAY_KEYS[d.weekday()].title())
            return {'open_now': False, 'closes_at': None, 'next_open': f"{label} {h[0] // 60:02d}:{h[0] % 60:02d}",
                    'next_open_day': i}
    return {'open_now': False, 'closes_at': None, 'next_open': None}


def business_phone(business_id):
    return _cached(('phone', business_id), lambda: _business_phone_db(business_id), ttl=300)


def _business_phone_db(business_id):
    b = db.businesses.find_one({'id': business_id}, {'_id': 0, 'phone': 1, 'hotline': 1}) or {}
    phone = b.get('phone') or b.get('hotline')
    if not phone:
        st = db.messaging_settings.find_one({'business_id': business_id}, {'_id': 0, 'twilio_from': 1}) or {}
        phone = st.get('twilio_from')
    return str(phone or '').strip()


def describe_for_ai(business_id):
    """Khối dữ kiện ngắn cho AI: giờ mở cửa, quy tắc đặt, thời lượng dịch vụ, thông tin tiệm."""
    r = get_rules(business_id)
    names = {'mon': 'Mon', 'tue': 'Tue', 'wed': 'Wed', 'thu': 'Thu', 'fri': 'Fri', 'sat': 'Sat', 'sun': 'Sun'}
    hours = ', '.join(f"{names[d]} {v[0]}-{v[1]}" if v else f"{names[d]} closed" for d, v in (r['hours'] or {}).items())
    lines = [f"OPENING HOURS: {hours}.",
             f"BOOKING RULES: book at least {r['min_lead_minutes']} min ahead, up to {r['max_advance_days']} days ahead; "
             f"start times every {r['slot_minutes']} min; a service must finish before closing. "
             "Always use check_availability before promising a time."]
    st = open_status(business_id, r)
    lines.append('RIGHT NOW: ' + (f"open until {st['closes_at']}." if st['open_now'] else
                                  f"closed — next opening {st['next_open'] or 'not set'}. A team member can reply when the business opens."))
    lines.append('CONFIRMATION: ' + ('bookings that pass these checks are CONFIRMED instantly (tool returns status "confirmed").'
                                     if r.get('auto_confirm', True) else
                                     'online bookings are REQUESTS the business approves (tool returns status "pending") — '
                                     'say "your request is in, the salon will confirm", never "confirmed".'))
    phone = business_phone(business_id)
    info = [f"{INFO_LABELS[k]}: {v}" for k, v in (r.get('info') or {}).items() if v]
    if phone:
        info.insert(0, f"Phone: {phone}")
    lines.append('BUSINESS INFO (only these facts are confirmed — for anything else, say you will check with the team): '
                 + ('; '.join(info) if info else 'none published yet.'))
    return '\n'.join(lines)
