"""
Đặt bàn (F&B) + đặt phòng / bàn bida theo giờ (Karaoke) — logic DÙNG CHUNG cho form công khai (/reserve/<id>,
/karaoke/reserve/<id>) và trợ lý AI (ai_packs/fnb.py, ai_packs/karaoke.py). Khách sạn nằm ở reservations_hotel.py (riêng).

Trước đây việc ghi db.table_reservations / db.karaoke_room_reservations nằm thẳng trong thân route, không có luật sức chứa
nào: mọi yêu cầu là 'pending', chủ quán tự xếp bàn / phòng trên /reservations, /karaoke/reservations. Module này:
  - create_table_reservation / create_karaoke_reservation: ĐÚNG khuôn bản ghi route công khai đang tạo (route gọi lại các
    hàm này), thêm source ('web' | 'ai_bot') + thẻ hội thoại AI khi AI đặt;
  - luật đặt chỗ của quán: giờ mở cửa + đặt trước tối thiểu/tối đa + "tự xác nhận" lấy từ Cài đặt đặt lịch
    (db.booking_settings, cùng trang chủ quán đang dùng), cộng 1 khối riêng cho từng loại chỗ
    (booking_settings.table_reservations / booking_settings.karaoke_reservations — save_reservation_settings);
  - sức chứa F&B: số khách tối đa mỗi khung 15/30 phút (chủ quán nhập) và/hoặc số ghế từng bàn (dining_tables.seats);
    quán chưa nhập gì -> KHÔNG đoán: chỉ nhận yêu cầu, quán xác nhận;
  - sức chứa Karaoke: phòng thật (db.karaoke_rooms), chồng giờ theo ĐÚNG luật _karaoke_reservation_overlaps của app.py
    (pending/confirmed/arrived, bản ghi cũ thiếu duration_hours = 2 giờ), giá = price_per_hour x số giờ;
  - khoá ghi theo quán (reservation_lock — find_one_and_update trên _id duy nhất): kiểm chỗ + ghi là 1 khối, 2 khách
    cùng đặt chỗ cuối cùng không thể cùng được nhận.

Không import app.py (app.py, ai_packs/* đều import được module này). Không biết gì về AI (lời nhắn cho AI nằm ở ai_packs/*).
"""
import contextlib
import re
import time
import uuid
from datetime import datetime, timedelta

from mongo_client import db, next_mongo_id

try:
    from pymongo.errors import DuplicateKeyError
except ImportError:  # pragma: no cover - pymongo luôn có trên máy chủ
    class DuplicateKeyError(Exception):
        pass


TABLE_ACTIVE = ('pending', 'confirmed', 'seated')           # trạng thái còn giữ chỗ — /reservations (api_reservation_update)
KARAOKE_ACTIVE = ('pending', 'confirmed', 'arrived')        # = _karaoke_reservation_overlaps() trong app.py
CHANGEABLE = ('pending', 'confirmed')                       # khách tự huỷ / đổi được (đã ngồi / đã tới thì không)
KARAOKE_DEFAULT_HOURS = 2.0                                 # route công khai + bản ghi cũ chưa có duration_hours
KARAOKE_MIN_HOURS, KARAOKE_MAX_HOURS = 0.5, 12.0            # route công khai kẹp đúng khoảng này
KARAOKE_IN_USE = 'Đang chơi'                                # db.karaoke_rooms.status khi phòng đang có khách
DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
DAY_NAMES = {'mon': 'Mon', 'tue': 'Tue', 'wed': 'Wed', 'thu': 'Thu', 'fri': 'Fri', 'sat': 'Sat', 'sun': 'Sun'}

SETTINGS_KEY = {'table': 'table_reservations', 'karaoke': 'karaoke_reservations'}
TABLE_DEFAULTS = {
    'auto_confirm': None,           # None = theo "tự xác nhận" của Cài đặt đặt lịch (nếu chủ đã lưu), chưa lưu = chờ duyệt
    'max_covers_per_slot': 0,       # 0 = quán chưa nhập sức chứa -> chỉ nhận yêu cầu, không bao giờ tự xác nhận
    'slot_minutes': 30,             # khung đếm số khách (15 hoặc 30 phút)
    'max_party': 50,                # đặt online tối đa (= ô "Số khách" của form công khai)
    'max_party_auto': 0,            # nhóm lớn hơn -> luôn chờ quán duyệt + báo nhân viên (0 = không giới hạn riêng)
    'dining_minutes': 90,           # 1 lượt ngồi giữ bàn bao lâu (chỉ dùng khi bàn có số ghế)
    'last_booking_before_close': 60,  # nhận đặt muộn nhất trước giờ đóng cửa bao nhiêu phút
    'hold_minutes': 0,              # giữ bàn bao lâu nếu khách tới trễ (0 = quán chưa công bố)
}
KARAOKE_DEFAULTS = {
    'auto_confirm': None,
    'min_hours': KARAOKE_MIN_HOURS,
    'max_hours': KARAOKE_MAX_HOURS,
    'max_party': 100,               # = ô "Số người" của form công khai
    'slot_minutes': 30,             # bước giờ khi gợi ý giờ khác
    'hold_minutes': 0,              # giữ phòng bao lâu nếu khách tới trễ (0 = quán chưa công bố)
    'in_use_buffer_hours': 2.0,     # phòng đang có khách vãng lai: không nhận đặt bắt đầu trong khoảng này
}
_LIMITS = {
    'table': {'max_covers_per_slot': (0, 2000), 'slot_minutes': (15, 30), 'max_party': (1, 200), 'max_party_auto': (0, 200),
              'dining_minutes': (30, 300), 'last_booking_before_close': (0, 240), 'hold_minutes': (0, 120)},
    'karaoke': {'min_hours': (0.5, 12), 'max_hours': (0.5, 12), 'max_party': (1, 200), 'slot_minutes': (15, 60),
                'hold_minutes': (0, 120), 'in_use_buffer_hours': (0, 12)},
}

REASONS = {
    'in_the_past': ('That time has already passed.', 'Giờ này đã qua rồi.'),
    'too_soon': ('That is too soon — please book a little further ahead.', 'Giờ này sát quá, vui lòng đặt muộn hơn một chút.'),
    'too_far_ahead': ('That date is too far ahead for online booking.', 'Ngày này xa quá, chưa nhận đặt online.'),
    'closed_that_day': ('The venue is closed that day.', 'Hôm đó quán nghỉ.'),
    'outside_opening_hours': ('That time is outside opening hours.', 'Giờ này ngoài giờ mở cửa.'),
    'too_close_to_closing': ('That is too close to closing time.', 'Giờ này sát giờ đóng cửa quá.'),
    'fully_booked': ('That time is fully booked.', 'Giờ này đã kín chỗ.'),
    'no_table': ('No table for that party size is free at that time.', 'Giờ này không còn bàn đủ chỗ cho nhóm.'),
    'large_party_request': ('The group is bigger than the number of guests the restaurant takes per time slot — it is a '
                            'request the team reviews and confirms.',
                            'Nhóm đông hơn số khách quán nhận mỗi khung giờ — đây là yêu cầu, quán xem lại và xác nhận.'),
    'large_party_slot_taken': ('A group this size needs a time slot with no other bookings, and this time already has some.',
                               'Nhóm đông như vậy cần 1 khung giờ chưa có ai đặt, giờ này đã có khách đặt.'),
    'no_room': ('No suitable room is free at that time.', 'Giờ này không còn phòng phù hợp.'),
    'room_taken': ('That room is already booked at that time.', 'Phòng này đã có khách đặt giờ đó.'),
    'no_rooms_listed': ('The venue has not listed its rooms yet.', 'Quán chưa nhập danh sách phòng.'),
    'bad_date': ('The date must be YYYY-MM-DD.', 'Ngày phải có dạng YYYY-MM-DD.'),
    'bad_time': ('The time must be HH:MM (24-hour).', 'Giờ phải có dạng HH:MM (24 giờ).'),
    'bad_party': ('The number of guests must be a whole number from 1.', 'Số khách phải là số nguyên từ 1.'),
    'party_too_large': ('That group is too large to book online.', 'Nhóm đông quá, không đặt online được.'),
    'bad_duration': ('That duration is not bookable.', 'Thời lượng này không đặt được.'),
    'name_required': ("The customer's name is required.", 'Cần tên khách.'),
    'phone_required': ("A valid phone number (at least 8 digits) is required.", 'Cần số điện thoại hợp lệ (ít nhất 8 số).'),
    'busy': ('The booking system is busy — please try again in a moment.', 'Hệ thống đặt chỗ đang bận, thử lại sau giây lát.'),
}


class ReservationError(ValueError):
    """Không đặt / đổi được (giờ đã qua, ngoài giờ mở cửa, hết chỗ, dữ liệu sai). `reason` = khoá của REASONS."""

    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}

    def text(self, lang='en'):
        en, vi = REASONS.get(self.reason, (self.reason, self.reason))
        return vi if lang == 'vi' else en


class ReservationBusy(ReservationError):
    def __init__(self):
        super().__init__('busy')


def explain(e):
    """Câu tiếng Anh cho AI (AI tự nói lại theo ngôn ngữ của khách), kèm chi tiết thật: giờ mở cửa, giờ muộn nhất..."""
    msg = REASONS.get(e.reason, (e.reason,))[0]
    d = getattr(e, 'detail', None) or {}
    if d.get('opening_hours'):
        msg += f" Opening hours that day: {d['opening_hours']}."
    if d.get('closes_at'):
        msg += f" It closes at {d['closes_at']}; the latest start that fits is {d['latest_start']}."
    if d.get('earliest'):
        msg += f" Earliest bookable time: {d['earliest']}."
    if d.get('max_days'):
        msg += f" Online booking is open up to {d['max_days']} days ahead."
    if d.get('max_online'):
        msg += f" The online limit is {d['max_online']} — offer to pass the request to the team instead."
    if d.get('allowed'):
        msg += f" Allowed: {d['allowed']}."
    return msg


def nearest_times(times, want_min, n=6):
    """n giờ 'HH:MM' gần giờ khách hỏi nhất, xếp theo giờ."""
    mins = lambda t: int(t[:2]) * 60 + int(t[3:5])  # noqa: E731
    return sorted(sorted(times, key=lambda t: (abs(mins(t) - want_min), mins(t)))[:n])


def spread(times, limit=12):
    """Rải đều cả ngày thay vì chỉ lấy buổi sớm nhất."""
    if len(times) <= limit:
        return list(times)
    step = len(times) / limit
    return [times[int(i * step)] for i in range(limit)]


# ---------------------------------------------------------------- tạo bản ghi (route công khai + AI dùng chung)
def _clean_note(note):
    return str(note or '').strip()[:500] or None


def create_table_reservation(business_id, name, phone, party_size, reserved_time, note=None, status='pending',
                             source='web', table_id=None, extra=None):
    """Ghi 1 yêu cầu đặt bàn vào db.table_reservations — đúng khuôn /api/public/reservations/<id> vẫn tạo
    (table_id None + 'pending' cho form công khai; chủ quán duyệt/xếp bàn trên /reservations)."""
    doc = {
        'id': next_mongo_id('table_reservations'),
        'business_id': business_id,
        'customer_name': name,
        'customer_phone': phone,
        'party_size': party_size,
        'reserved_time': reserved_time,
        'table_id': table_id,
        'note': _clean_note(note),
        'status': status,
        'source': source,
        'created_at': datetime.now().isoformat(),
    }
    if extra:
        doc.update({k: v for k, v in extra.items() if v is not None})
    db.table_reservations.insert_one(doc)
    doc.pop('_id', None)
    return doc


def karaoke_hours(value, default=KARAOKE_DEFAULT_HOURS):
    """Số giờ đặt phòng như route công khai: không đọc được -> 2 giờ, kẹp trong [0.5, 12]."""
    try:
        hours = float(value or default)
    except (TypeError, ValueError):
        hours = float(default)
    return max(KARAOKE_MIN_HOURS, min(KARAOKE_MAX_HOURS, hours))


def create_karaoke_reservation(business_id, name, phone, party_size, reserved_time, duration_hours=None, note=None,
                               status='pending', source='web', room_id=None, extra=None):
    """Ghi 1 yêu cầu đặt phòng vào db.karaoke_room_reservations — đúng khuôn /api/public/karaoke_reservations/<id>
    (room_id None + 'pending' cho form công khai; chủ quán xếp phòng trên /karaoke/reservations)."""
    doc = {
        'id': next_mongo_id('karaoke_room_reservations'),
        'business_id': business_id,
        'customer_name': name,
        'customer_phone': phone,
        'party_size': party_size,
        'reserved_time': reserved_time,
        'duration_hours': karaoke_hours(duration_hours),
        'room_id': room_id,
        'note': _clean_note(note),
        'status': status,
        'source': source,
        'created_at': datetime.now().isoformat(),
    }
    if extra:
        doc.update({k: v for k, v in extra.items() if v is not None})
    db.karaoke_room_reservations.insert_one(doc)
    doc.pop('_id', None)
    return doc


# ---------------------------------------------------------------- khoá ghi theo quán (kiểm chỗ + ghi = 1 khối)
LOCK_TTL_SECONDS = 10
LOCK_WAIT_SECONDS = 3.0


@contextlib.contextmanager
def reservation_lock(business_id, kind):
    """Khoá loại trừ cho 1 quán + 1 loại chỗ: chỉ 1 lượt đặt/đổi được kiểm sức chứa rồi ghi tại 1 thời điểm (giống
    slot_key của booking_engine nhưng đếm lại từ dữ liệu thật mỗi lần, nên huỷ / xếp tay trên màn nhân viên không làm lệch
    sổ). Lấy khoá = find_one_and_update nguyên tử trên _id duy nhất; khoá hết hạn sau LOCK_TTL_SECONDS nếu tiến trình chết."""
    key, token = f"{kind}|{business_id}", uuid.uuid4().hex
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        now = time.time()
        try:
            db.reservation_locks.find_one_and_update({'_id': key, 'until': {'$lt': now}},
                                                     {'$set': {'until': now + LOCK_TTL_SECONDS, 'token': token}}, upsert=True)
            break
        except DuplicateKeyError:
            if time.monotonic() >= deadline:
                raise ReservationBusy()
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            db.reservation_locks.delete_one({'_id': key, 'token': token})
        except Exception:
            pass


# ---------------------------------------------------------------- luật đặt chỗ của quán
def _num(v, default=0, cast=int):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


# Đặt bởi booking_settings_routes khi chủ quán F&B / karaoke lưu "công tắc chung" ở trang Cài đặt đặt chỗ (Phase 2). Trang Cài
# đặt đặt lịch CŨ luôn gửi auto_confirm=True (mặc định lịch hẹn Nails) cho MỌI ngành — giá trị đó không phải lựa chọn của quán.
GENERAL_SAVED_MARK = 'reservations_general_saved_at'


def load_rules(business_id, kind):
    """Luật đặt chỗ hiện hành của quán cho 1 loại chỗ ('table' | 'karaoke'): khối riêng + giờ mở cửa / đặt trước tối thiểu,
    tối đa / thông tin quán của Cài đặt đặt lịch. Giờ mở cửa CHỈ khi chủ đã lưu (mặc định 9-19 của Nails không phải giờ thật
    của nhà hàng / karaoke): hours=None -> 'chưa công bố', không bao giờ tự xác nhận."""
    raw = db.booking_settings.find_one({'business_id': business_id}, {'_id': 0}) or {}
    defaults = TABLE_DEFAULTS if kind == 'table' else KARAOKE_DEFAULTS
    sub = raw.get(SETTINGS_KEY[kind]) if isinstance(raw.get(SETTINGS_KEY[kind]), dict) else {}
    rules = dict(defaults)
    for k, (lo, hi) in _LIMITS[kind].items():
        if sub.get(k) is not None:
            cast = float if isinstance(defaults[k], float) else int
            rules[k] = max(lo, min(hi, _num(sub[k], defaults[k], cast)))
    if kind == 'table' and rules['slot_minutes'] not in (15, 30):
        rules['slot_minutes'] = 30
    if kind == 'karaoke' and rules['max_hours'] < rules['min_hours']:
        rules['max_hours'] = rules['min_hours']
    if isinstance(sub.get('auto_confirm'), bool):
        rules['auto_confirm'] = sub['auto_confirm']
    elif 'auto_confirm' in raw and raw.get(GENERAL_SAVED_MARK):
        rules['auto_confirm'] = bool(raw['auto_confirm'])
    else:
        rules['auto_confirm'] = False
    rules['hours'] = raw['hours'] if isinstance(raw.get('hours'), dict) and raw.get('hours') else None
    rules['min_lead_minutes'] = max(0, _num(raw.get('min_lead_minutes'), 0)) if 'min_lead_minutes' in raw else 0
    rules['max_advance_days'] = max(1, _num(raw.get('max_advance_days'), 366)) if 'max_advance_days' in raw else 366
    rules['info'] = raw.get('info') if isinstance(raw.get('info'), dict) else {}
    rules['kind'] = kind
    return rules


def save_reservation_settings(business_id, kind, data):
    """Lưu khối luật riêng của 1 loại chỗ (cho trang cài đặt của chủ quán). Chỉ nhận đúng các khoá đã biết, kẹp giới hạn."""
    if kind not in SETTINGS_KEY or not isinstance(data, dict):
        raise ValueError('kind / data không hợp lệ.')
    defaults = TABLE_DEFAULTS if kind == 'table' else KARAOKE_DEFAULTS
    clean = {}
    for k, (lo, hi) in _LIMITS[kind].items():
        if k in data and data[k] not in (None, ''):
            cast = float if isinstance(defaults[k], float) else int
            try:
                clean[k] = max(lo, min(hi, cast(data[k])))
            except (TypeError, ValueError):
                raise ValueError(f'{k} không hợp lệ.')
    if 'auto_confirm' in data:
        clean['auto_confirm'] = None if data['auto_confirm'] is None else bool(data['auto_confirm'])
    if kind == 'table' and 'slot_minutes' in clean and clean['slot_minutes'] not in (15, 30):
        clean['slot_minutes'] = 30
    db.booking_settings.update_one({'business_id': business_id},
                                   {'$set': {f"{SETTINGS_KEY[kind]}.{k}": v for k, v in clean.items()}}, upsert=True)
    return load_rules(business_id, kind)


UNKNOWN = 'unknown'


def hours_on(rules, day):
    """(mở, đóng) tính bằng phút từ 00:00 của `day`; None = nghỉ; UNKNOWN = quán chưa công bố giờ mở cửa.
    Giờ đóng <= giờ mở = quán mở QUA nửa đêm, đóng sáng hôm sau (booking_rules.save_rules lưu đúng như chủ nhập):
    ['18:00', '02:00'] -> (1080, 1560). Phần sau nửa đêm thuộc NGÀY LỊCH hôm sau — check_window / *_candidate_* xét cả ca
    đêm của hôm trước (overnight_tail)."""
    if not rules.get('hours'):
        return UNKNOWN
    v = rules['hours'].get(DAY_KEYS[day.weekday()])
    if not v:
        return None
    try:
        o, c = _hm_to_min(v[0]), _hm_to_min(v[1])
    except (ValueError, IndexError, TypeError):
        return None
    return (o, c + 24 * 60) if c <= o else (o, c)


def overnight_tail(rules, day):
    """Ca đêm của HÔM TRƯỚC còn mở tới phút nào của `day` (mở 18:00-02:00 thứ Sáu -> thứ Bảy 120); 0 = không có."""
    prev = hours_on(rules, day - timedelta(days=1))
    return prev[1] - 24 * 60 if isinstance(prev, tuple) and prev[1] > 24 * 60 else 0


def _ampm(m):
    h, mi = divmod(int(m) % (24 * 60), 60)
    return f"{h % 12 or 12}:{mi:02d} {'am' if h < 12 else 'pm'}"


def close_label(m):
    """Giờ ĐÓNG cho AI nói đúng: '22:00', '24:00 (midnight)', '02:00 (2:00 am the next day)'."""
    if m > 24 * 60:
        return f"{fmt_min(m)} ({_ampm(m)} the next day)"
    return '24:00 (midnight)' if m == 24 * 60 else fmt_min(m)


def day_hours_text(rules, day):
    """Giờ mở cửa của 1 NGÀY LỊCH: '18:00-02:00 (2:00 am the next day)', kèm phần sau nửa đêm của ca hôm trước
    ('00:00-02:00 (still open from Friday night) and ...'); 'closed'; None = chưa công bố."""
    hrs = hours_on(rules, day)
    if hrs == UNKNOWN:
        return None
    parts = []
    tail = overnight_tail(rules, day)
    if tail:
        parts.append(f"00:00-{fmt_min(tail)} (still open from {day - timedelta(days=1):%A} night)")
    if hrs:
        parts.append(f"{fmt_min(hrs[0])}-{close_label(hrs[1])}")
    return ' and '.join(parts) or 'closed'


def hours_text(rules):
    """'Mon 11:00-22:00, Tue closed, Fri 18:00-02:00 (closes at 2:00 am Sat, after midnight), ...' hoặc None khi chưa
    công bố. Có ngày mở qua nửa đêm thì nói rõ giờ sau nửa đêm thuộc NGÀY hôm sau (AI truyền đúng ngày cho công cụ)."""
    if not rules.get('hours'):
        return None
    out, late = [], False
    for i, d in enumerate(DAY_KEYS):
        v = rules['hours'].get(d)
        if not v:
            out.append(f"{DAY_NAMES[d]} closed")
            continue
        line = f"{DAY_NAMES[d]} {v[0]}-{v[1]}"
        try:
            o, c = _hm_to_min(v[0]), _hm_to_min(v[1])
        except (ValueError, IndexError, TypeError):
            o = c = None
        if c is not None and 0 < c < o:
            line += f" (closes at {_ampm(c)} {DAY_NAMES[DAY_KEYS[(i + 1) % 7]]}, after midnight)"
            late = True
        out.append(line)
    text = ', '.join(out)
    if late:
        text += ("; a time after midnight is on the NEXT date (Friday night 01:00 = Saturday 01:00) — pass that date to the "
                 "tools")
    return text


def _hm_to_min(s):
    h, m = str(s).split(':')[:2]
    return int(h) * 60 + int(m)


def fmt_min(m):
    """Phút -> 'HH:MM'. Đúng 24:00 (giờ ĐÓNG lúc nửa đêm) giữ '24:00' — '00:00' dễ bị hiểu là 0 giờ sáng cùng ngày; giờ sau
    nửa đêm (đóng 02:00 hôm sau = 1560) -> '02:00'. Giờ BẮT ĐẦU luôn < 24:00 (parse_hm, *_candidate_*)."""
    m = int(m)
    if m == 24 * 60:
        return '24:00'
    m %= 24 * 60
    return f"{m // 60:02d}:{m % 60:02d}"


def check_window(rules, when, now, minutes_after_start=0):
    """Raise ReservationError nếu `when` (giờ địa phương của quán) không đặt được theo luật thời gian: đã qua, sát quá,
    xa quá, quán nghỉ, ngoài giờ mở cửa, hoặc phần sau giờ bắt đầu (`minutes_after_start`: thời lượng phòng / khoảng nhận
    đặt muộn nhất trước giờ đóng) vượt giờ đóng cửa."""
    if when < now:
        raise ReservationError('in_the_past')
    if when < now + timedelta(minutes=rules['min_lead_minutes']):
        raise ReservationError('too_soon', {'earliest': (now + timedelta(minutes=rules['min_lead_minutes'])).strftime('%Y-%m-%d %H:%M')})
    if (when.date() - now.date()).days > rules['max_advance_days']:
        raise ReservationError('too_far_ahead', {'max_days': rules['max_advance_days']})
    hrs = hours_on(rules, when.date())
    if hrs == UNKNOWN:
        return
    start = when.hour * 60 + when.minute
    tail = overnight_tail(rules, when.date())
    if start < tail and not (hrs and hrs[0] <= start < hrs[1]):
        # 00:30 thứ Bảy của quán mở 18:00-02:00 thứ Sáu: vẫn là ca đêm thứ Sáu (đã qua nửa đêm -> giờ đóng nói thẳng '02:00')
        prev = hours_on(rules, when.date() - timedelta(days=1))
        if start + 24 * 60 + minutes_after_start > prev[1]:
            latest = max(prev[0], prev[1] - minutes_after_start)
            raise ReservationError('too_close_to_closing', {
                'closes_at': fmt_min(prev[1]),
                'latest_start': fmt_min(latest % (24 * 60)) if latest >= 24 * 60 else f"{fmt_min(latest)} the evening before"})
        return
    if hrs is None:
        raise ReservationError('closed_that_day')
    if start < hrs[0] or start >= hrs[1]:
        raise ReservationError('outside_opening_hours', {'opening_hours': day_hours_text(rules, when.date())})
    if start + minutes_after_start > hrs[1]:
        latest = max(hrs[0], hrs[1] - minutes_after_start)
        raise ReservationError('too_close_to_closing', {'closes_at': close_label(hrs[1]),
                                                         'latest_start': fmt_min(latest % (24 * 60))})


# ---------------------------------------------------------------- tiện ích chung (đọc tham số, giờ, khách)
def naive_now(business_id, now_local=None):
    """Giờ hiện tại tại quán, không múi giờ, tròn phút (ctx.now_local đã là giờ quán; thiếu thì booking_rules.local_now)."""
    if isinstance(now_local, datetime):
        return now_local.replace(tzinfo=None, second=0, microsecond=0)
    import booking_rules
    return booking_rules.local_now(business_id).replace(second=0, microsecond=0)


def parse_day(value):
    try:
        return datetime.strptime(str(value or '').strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        raise ReservationError('bad_date')


_HM_RE = re.compile(r'^(\d{1,2})\s*(?:[:h.]\s*(\d{2})?)?\s*(am|pm|a\.m\.|p\.m\.)?$', re.I)


def parse_hm(value):
    """'19:00' / '7:30pm' / '19h30' / '2026-10-30T19:00' -> phút trong ngày."""
    s = str(value or '').strip().lower()
    if re.match(r'^\d{4}-\d{2}-\d{2}[t ]', s):
        s = s[11:16]
    m = _HM_RE.match(s.strip())
    if not m:
        raise ReservationError('bad_time')
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or '').replace('.', '')
    if ap:
        if not 1 <= h <= 12:
            raise ReservationError('bad_time')
        h = (h % 12) + (12 if ap == 'pm' else 0)
    if h > 23 or mi > 59:
        raise ReservationError('bad_time')
    return h * 60 + mi


def parse_party(value, max_party):
    try:
        n = int(str(value).strip()) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        n = None
    if n is None or n < 1:
        raise ReservationError('bad_party')
    if n > max_party:
        raise ReservationError('party_too_large', {'max_online': max_party})
    return n


def clean_name(value):
    name = re.sub(r'\s+', ' ', str(value or '')).strip()[:80]
    if not name or not re.search(r'[^\W\d_]', name):
        raise ReservationError('name_required')
    return name


def clean_phone(value):
    phone = re.sub(r'[^0-9+() .-]', '', str(value or ''))[:24].strip()
    if len(re.sub(r'\D', '', phone)) < 8:
        raise ReservationError('phone_required')
    return phone


_CC = {'US': '1', 'CA': '1', 'AU': '61', 'NZ': '64', 'GB': '44', 'VN': '84'}


def e164(phone, country=None):
    """'+61412345678' hoặc '' — BẢN SAO ĐÚNG luật ai_packs.normalize_phone (scripts/tests/test_phase2_fix3_country.py so
    từng ca; gói nạp riêng không có registry vẫn dùng được): số nội địa theo nước quán (country_of); quán CHƯA BIẾT nước ->
    '' (không đoán là số Mỹ); Mỹ / Canada chỉ số NANP hợp lệ; số 0 trung kế ghi sau mã nước Úc / NZ / Anh / VN được bỏ."""
    raw = str(phone or '').strip()
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return ''
    if raw.startswith('+') or raw.startswith('00'):
        d = digits if raw.startswith('+') else digits[2:]
        cc = next((x for x in _TRUNK0_CC if d.startswith(x + '0')), None)
        if cc and len(d) - len(cc) - 1 >= 7:
            d = cc + d[len(cc) + 1:]
        return '+' + d if 8 <= len(d) <= 15 else ''
    c = str(country or '').strip().upper()
    if not c:
        return ''
    if c in ('US', 'CA'):
        if len(digits) == 10 and digits[0] not in '01':
            return '+1' + digits
        if len(digits) == 11 and digits[0] == '1' and digits[1] not in '01':
            return '+' + digits
        if digits[0] == '1':
            return ''   # +1 nhưng không phải số NANP hợp lệ
    elif c == 'AU':
        if len(digits) == 10 and digits.startswith('0'):
            return '+61' + digits[1:]
        if len(digits) == 9 and digits[0] in '23478':
            return '+61' + digits
        if len(digits) == 11 and digits.startswith('61'):
            return '+' + digits
    elif c == 'VN':
        if len(digits) == 10 and digits.startswith('0'):
            return '+84' + digits[1:]
        if len(digits) == 9 and digits[0] in '35789':
            return '+84' + digits
        if len(digits) == 11 and digits.startswith('84'):
            return '+' + digits
    elif c in ('NZ', 'GB'):
        if digits.startswith('0') and 9 <= len(digits) <= 11:
            return '+' + _CC[c] + digits[1:]
        if digits.startswith(_CC[c]) and 10 <= len(digits) <= 13:
            return '+' + digits
    if 11 <= len(digits) <= 15 and digits[0] != '0':
        return '+' + digits
    return ''


def same_phone(a, b, country=None):
    """Cùng 1 số điện thoại dù khác cách ghi ('0412 345 678' = '+61 412 345 678' ở quán Úc): trùng toàn bộ chữ số, hoặc
    trùng số quốc tế sau khi chuẩn hoá theo nước của quán. Không so 'mấy số cuối' (2 số Mỹ khác mã vùng từng bị coi là 1)."""
    da, dbb = re.sub(r'\D', '', str(a or '')), re.sub(r'\D', '', str(b or ''))
    if len(da) < 8 or len(dbb) < 8:
        return False
    if da == dbb:
        return True
    ea, eb = e164(a, country), e164(b, country)
    return bool(ea and eb and ea == eb)


def country_of(business_id):
    """Nước của quán ('AU'...) hoặc None — CÙNG 1 nguồn với mọi chỗ chuẩn hoá SĐT: ai_packs.shop_country (hồ sơ quán -> múi
    giờ trang Nhắn tin -> tiền tệ). Không qua TenantEngine (mặc định 'VN' khi hồ sơ chưa có nước: quán Úc / Mỹ tự đăng ký
    từng bị đọc số nội địa như số Việt Nam)."""
    try:
        import ai_packs
        return ai_packs.shop_country(business_id)
    except Exception:
        return None


def parse_dt(value):
    try:
        return datetime.fromisoformat(str(value)[:19])
    except (TypeError, ValueError):
        return None


def iso_slot(when):
    """Định dạng reserved_time giống form công khai gửi lên ('YYYY-MM-DDTHH:MM:00')."""
    return when.strftime('%Y-%m-%dT%H:%M:00')


def currency(business_id):
    try:
        from tenant_engine import TenantEngine
        return (TenantEngine.get_region_config(business_id) or {}).get('currency') or 'VND'
    except Exception:
        return 'VND'


def money(amount, cur):
    from currency_utils import format_money
    return format_money(amount, cur)


def shop_phone(business_id):
    try:
        import booking_rules
        return booking_rules.business_phone(business_id)
    except Exception:
        return ''


INFO_LABELS = {'address': 'Address', 'parking': 'Parking', 'payments': 'Payment methods accepted',
               'gift_cards': 'Gift cards / vouchers', 'cancellation_policy': 'Cancellation / late policy', 'other': 'Other notes'}


def business_info_line(business_id, rules):
    """Thông tin quán ĐÃ CÔNG BỐ (Cài đặt đặt lịch -> Thông tin + SĐT + địa chỉ hồ sơ quán)."""
    info = dict(rules.get('info') or {})
    if not str(info.get('address') or '').strip():
        biz = db.businesses.find_one({'id': business_id}, {'_id': 0, 'address': 1}) or {}
        if str(biz.get('address') or '').strip():
            info['address'] = str(biz['address']).strip()
    parts = [f"{INFO_LABELS.get(k, k)}: {str(v).strip()}" for k, v in info.items() if str(v or '').strip()]
    phone = shop_phone(business_id)
    if phone:
        parts.insert(0, f"Phone: {phone}")
    return ('BUSINESS INFO (only these facts are confirmed — anything else: say you will check with the team): '
            + ('; '.join(parts) if parts else 'none published yet.'))


# ---------------------------------------------------------------- ai sở hữu đặt chỗ nào (xem / huỷ / đổi)
def _token_proof(ctx):
    """chat_token_hash chứng minh được chủ: có, và không phải mã tạm 'anon:...' (chat web không có mã trình duyệt)."""
    th = (ctx or {}).get('chat_token_hash')
    return th if th and not str(th).startswith('anon:') else None


def _conversation_proof(ctx):
    """ai_conversation_id chứng minh được chủ CHỈ trên kênh nền tảng (id người gửi do nền tảng ký). Chat web: customer_id là
    '<quán>:<SĐT khách gõ>' — ai gõ SĐT đó cũng có -> không bao giờ tính (bằng chứng web = chat_token_hash), đúng
    ai_packs.manage_filter."""
    cid = (ctx or {}).get('customer_id')
    if not cid:
        return None
    channel = str(ctx.get('channel') or 'web').lower()
    return cid if channel != 'web' else None


def ctx_country(ctx):
    if 'country' not in ctx or not ctx.get('country'):
        ctx['country'] = country_of(ctx.get('business_id'))
    return ctx['country']


def _typed_phone(ctx):
    """SĐT khách gõ trong CHÍNH chat web này (ctx.contact_phone, không thì id hội thoại web '<quán>:<SĐT>'). Không bao giờ là
    bằng chứng một mình (ai cũng gõ được SĐT người khác) — chỉ để gắn mã trình duyệt với đúng người đang chat."""
    if ctx.get('contact_phone'):
        return str(ctx['contact_phone'])
    cid = str(ctx.get('customer_id') or '')
    if str(ctx.get('channel') or 'web').lower() == 'web' and ':' in cid:
        rest = cid.split(':', 1)[1].split('~', 1)[0].strip()
        return rest if re.fullmatch(r'\+?[0-9(][0-9 ().-]{5,31}', rest) else None
    return None


_TRUNK0_CC = ('61', '64', '44', '84')


def _untrunk(phone):
    """'+61 (0)412 345 678' / '+610412345678' / '0061 0412...' (mã nước + số 0 đầu của số nội địa — cách ghi hay gặp ở Úc / NZ /
    Anh / VN) -> '+61412345678'; mọi cách ghi khác giữ nguyên. Chỉ cho so khớp chủ đặt chỗ: lọc ứng viên (_phone_regex) và
    kiểm từng dòng (is_owned / _token_owns) phải nhận CÙNG các cách ghi, không thì đặt chỗ của khách đã xác minh bị rơi mất."""
    raw = str(phone or '').strip()
    if not (raw.startswith('+') or raw.startswith('00')):
        return phone
    d = re.sub(r'\D', '', raw)
    d = d if raw.startswith('+') else d[2:]
    cc = next((x for x in _TRUNK0_CC if d.startswith(x + '0')), None)
    return ('+' + cc + d[len(cc) + 1:]) if cc and len(d) - len(cc) - 1 >= 7 else phone


def _token_owns(doc, ctx):
    """Mã chat khớp VÀ (chat web) đặt chỗ thuộc đúng chat này: tạo trong cùng hội thoại web, hoặc lưu đúng SĐT khách gõ ở đây.
    1 trình duyệt (máy tính bảng quầy lễ tân) dùng chung 1 mã cho mọi khách: khách kế tiếp gõ SĐT khác không thừa hưởng đặt
    chỗ của người trước. Hội thoại kênh nền tảng ('conv:<băm>') không cần thêm gì. Cùng luật ai_packs.token_owns."""
    th = _token_proof(ctx)
    if not th or doc.get('chat_token_hash') != th:
        return False
    if str(ctx.get('channel') or 'web').lower() != 'web':
        return True
    cid = ctx.get('customer_id')
    if cid and doc.get('ai_conversation_id') == cid:
        return True
    typed = _typed_phone(ctx)
    return bool(typed) and same_phone(_untrunk(doc.get('customer_phone')), _untrunk(typed), ctx_country(ctx))


def is_owned(doc, ctx):
    """Đặt chỗ này CHỨNG MINH được là của cuộc chat đang nói chuyện: SĐT đã xác minh trùng (NGUYÊN số), hoặc mã chat web của
    đúng trình duyệt KÈM đúng chat này (_token_owns), hoặc cùng hội thoại kênh nền tảng (xem _conversation_proof). Chat web
    không có mã: không gì cả. Cùng luật ai_packs.manage_filter của phần lõi."""
    if not doc or not ctx:
        return False
    if ctx.get('phone') and same_phone(_untrunk(doc.get('customer_phone')), _untrunk(ctx['phone']), ctx_country(ctx)):
        return True
    if _token_owns(doc, ctx):
        return True
    cid = _conversation_proof(ctx)
    return bool(cid and doc.get('ai_conversation_id') == cid)


def can_prove_owner(ctx):
    return bool(ctx and (ctx.get('phone') or _token_proof(ctx) or _conversation_proof(ctx)))


def staff_thread(ctx):
    """Hội thoại /ai_bot để ghi dòng báo chủ quán: ctx.thread_id, không có thì phần trước '~' của customer_id web."""
    tid = (ctx or {}).get('thread_id')
    if tid:
        return tid
    cid = (ctx or {}).get('customer_id')
    return str(cid).split('~', 1)[0] if cid else cid


def booking_contact(args, ctx):
    """(tên, SĐT) cho đặt chỗ MỚI: khách nói trong chat (args) > SĐT đã xác minh > SĐT khách đã đưa (chưa xác minh,
    ctx.contact_phone — chỉ làm liên lạc, không bao giờ làm bằng chứng chủ) ; tên đã biết của khách nếu AI không truyền."""
    name = clean_name(args.get('customer_name') or ctx.get('customer_name'))
    phone = clean_phone(args.get('phone') or ctx.get('phone') or ctx.get('contact_phone'))
    return name, phone


def ai_tags(ctx):
    """Thẻ gắn lên mọi đặt chỗ AI tạo (contract ai_packs): nguồn + hội thoại + mã chat web (băm)."""
    return {'ai_conversation_id': ctx.get('customer_id'), 'chat_token_hash': ctx.get('chat_token_hash'),
            'ai_channel': ctx.get('channel') or 'web'}


def _phone_regex(phone, country=None):
    """Regex Mongo khớp ĐÚNG số này dù ghi kiểu gì ('0412-345-678', '+61 412 345 678', '(212) 555-1234'): đủ mọi chữ số, neo
    2 đầu, trước số quốc gia chỉ cho mã nước hoặc số 0 đầu (Úc / NZ / Anh / VN: cả 2, '+61 (0)412...') — không bao giờ khớp số
    khác chỉ trùng mấy số cuối. Cùng các cách ghi is_owned nhận (_untrunk)."""
    d = re.sub(r'\D', '', e164(_untrunk(phone), country) or '')
    if not 8 <= len(d) <= 15:
        return None
    cc = next((c for c in sorted(set(_CC.values()), key=len, reverse=True) if d.startswith(c) and len(d) - len(c) >= 7), '')
    sp = r'\D*'.join
    trunk = r'(?:0\D*)?' if cc in _TRUNK0_CC else ''
    prefix = (r'(?:(?:\+|00)?\D*' + sp(cc) + r'\D*' + trunk + r'|0\D*)?') if cc else r'(?:\+|00)?\D*'
    return r'^\D*' + prefix + sp(d[len(cc):]) + r'\D*$'


def ownership_query(ctx):
    """Lọc ỨNG VIÊN ngay trong Mongo (mã chat / hội thoại / SĐT đã xác minh — NGUYÊN số, mọi cách ghi) để quán đông khách
    không làm rơi đặt chỗ của khách khỏi trang kết quả; is_owned() vẫn kiểm chính xác từng dòng sau đó (mã chat web chỉ tính
    kèm đúng chat này). None = không có bằng chứng nào."""
    ors = []
    th, cid = _token_proof(ctx), _conversation_proof(ctx)
    if th:
        ors.append({'chat_token_hash': th})
    if cid:
        ors.append({'ai_conversation_id': cid})
    rx = _phone_regex((ctx or {}).get('phone'), ctx_country(ctx)) if (ctx or {}).get('phone') else None
    if rx:
        ors.append({'customer_phone': {'$regex': rx}})
    return {'$or': ors} if ors else None


def owned_upcoming(coll, business_id, ctx, statuses, now, back_hours=2, limit=10):
    """Đặt chỗ sắp tới (và lượt đang diễn ra trong `back_hours`) của CHÍNH cuộc chat này."""
    own = ownership_query(ctx)
    if own is None:
        return []
    since = (now - timedelta(hours=back_hours)).strftime('%Y-%m-%dT%H:%M')
    rows = coll.find(dict(own, business_id=business_id, status={'$in': list(statuses)}, reserved_time={'$gte': since}),
                     {'_id': 0}).sort('reserved_time', 1).limit(200)
    return [r for r in rows if is_owned(r, ctx)][:limit]


def find_duplicate(coll, business_id, phone, when, statuses, country=None):
    """Cùng SĐT + cùng giờ + còn hiệu lực (khách nói "đặt giúp" 2 lần) -> bản ghi cũ."""
    stamp = when.strftime('%Y-%m-%dT%H:%M')
    country = country or country_of(business_id)
    for r in coll.find({'business_id': business_id, 'status': {'$in': list(statuses)},
                        'reserved_time': {'$gte': stamp, '$lte': stamp + ':59'}}, {'_id': 0}):
        if same_phone(r.get('customer_phone'), phone, country):
            return r
    return None


def _rows_around(coll, business_id, day, statuses, exclude_id=None):
    """Đặt chỗ còn hiệu lực từ hôm trước tới hôm sau của `day` (đủ cho mọi khoảng chồng giờ <= 24 giờ)."""
    lo, hi = (day - timedelta(days=1)).isoformat(), (day + timedelta(days=2)).isoformat()
    out = []
    for r in coll.find({'business_id': business_id, 'status': {'$in': list(statuses)},
                        'reserved_time': {'$gte': lo, '$lt': hi}}, {'_id': 0}):
        if exclude_id is not None and r.get('id') == exclude_id:
            continue
        start = parse_dt(r.get('reserved_time'))
        if start is not None:
            out.append(dict(r, _start=start))
    return out


def _party(r):
    return max(1, _num(r.get('party_size'), 1))


# ---------------------------------------------------------------- F&B: sức chứa bàn
def tables_with_seats(business_id):
    """Bàn có số ghế (dining_tables.seats hoặc .capacity > 0), bé -> lớn. Rỗng = quán chưa nhập số ghế."""
    out = []
    for t in db.dining_tables.find({'business_id': business_id}, {'_id': 0, 'id': 1, 'name': 1, 'seats': 1, 'capacity': 1}):
        seats = _num(t.get('seats') or t.get('capacity'), 0)
        if seats > 0:
            out.append({'id': t.get('id'), 'name': t.get('name') or f"#{t.get('id')}", 'seats': seats})
    return sorted(out, key=lambda t: (t['seats'], str(t['name'])))


def table_model(rules, tables):
    """'covers' (số khách / khung giờ), 'tables' (số ghế từng bàn), 'tables+covers', hoặc 'none' (chỉ nhận yêu cầu)."""
    parts = (['tables'] if tables else []) + (['covers'] if rules['max_covers_per_slot'] > 0 else [])
    return '+'.join(parts) if parts else 'none'


def table_rows(business_id, day, exclude_id=None):
    return _rows_around(db.table_reservations, business_id, day, TABLE_ACTIVE, exclude_id)


def _bucket(dt, slot):
    return dt.date(), (dt.hour * 60 + dt.minute) // slot


def table_fit(rules, tables, rows, when, party):
    """(còn chỗ?, lý do, table_id giữ cho khách hoặc None) theo sức chứa quán đã nhập. Không có mô hình nào -> (None, None,
    None): không biết, chỉ nhận yêu cầu."""
    if table_model(rules, tables) == 'none':
        return None, None, None
    large = None
    if rules['max_covers_per_slot'] > 0:
        b = _bucket(when, rules['slot_minutes'])
        used = sum(_party(r) for r in rows if _bucket(r['_start'], rules['slot_minutes']) == b)
        if party > rules['max_covers_per_slot']:
            # Riêng 1 nhóm đã đông hơn số khách / khung giờ: không phải "kín chỗ" ở mọi giờ mọi ngày — là yêu cầu nhóm lớn
            # quán duyệt (không tự xác nhận), cần trọn 1 khung giờ chưa có ai đặt.
            if used:
                return False, 'large_party_slot_taken', None
            large = 'large_party_request'
        elif used + party > rules['max_covers_per_slot']:
            return False, 'fully_booked', None
    if not tables:
        return True, large, None
    stay = timedelta(minutes=rules['dining_minutes'])
    overlapping = [r for r in rows if r['_start'] < when + stay and r['_start'] + stay > when]
    busy = {r.get('table_id') for r in overlapping if r.get('table_id') is not None}
    free = [t for t in tables if t['id'] not in busy]
    # Yêu cầu chưa xếp bàn (form công khai, nhóm lớn đã nhận chờ ghép bàn) cũng cần bàn: nhóm lớn trước, mỗi nhóm lấy bàn
    # nhỏ nhất vừa đủ; không bàn nào đủ ghế -> ghép bàn: lấy bàn lớn nhất trước tới khi đủ ghế (không đủ: giữ hết bàn còn lại).
    for r in sorted((r for r in overlapping if r.get('table_id') is None), key=_party, reverse=True):
        need = _party(r)
        fit = next((t for t in free if t['seats'] >= need), None)
        if fit:
            free.remove(fit)
            continue
        for t in sorted(free, key=lambda t: t['seats'], reverse=True):
            free.remove(t)
            need -= t['seats']
            if need <= 0:
                break
    if party > tables[-1]['seats']:
        # Không bàn nào đủ ghế cho cả nhóm (quán ghép bàn) -> chỉ nhận yêu cầu, nhân viên xếp; bàn trống phải đủ ghế cho cả nhóm.
        return (True, 'needs_joined_tables', None) if sum(t['seats'] for t in free) >= party else (False, 'no_table', None)
    pick = next((t for t in free if t['seats'] >= party), None)
    return (True, large, pick['id']) if pick else (False, 'no_table', None)


def table_candidate_times(rules, day, around=None):
    """Giờ bắt đầu có thể nhận đặt trong NGÀY LỊCH `day` (phút < 24:00), theo bước khung giờ — gồm cả phần sau nửa đêm của ca
    đêm hôm trước (mở 17:00-01:00 thứ Sáu -> thứ Bảy có 00:00, 00:30); quán chưa công bố giờ -> quanh giờ khách hỏi."""
    step = rules['slot_minutes']
    hrs = hours_on(rules, day)
    if hrs == UNKNOWN:
        if around is None:
            return []
        return [m for m in range(around - 180, around + 181, step) if 0 <= m < 24 * 60]
    last = rules['last_booking_before_close']
    tail = overnight_tail(rules, day)
    out = list(range(0, tail - last + 1, step)) if tail else []
    if hrs is not None:
        first = -(-hrs[0] // step) * step
        out += range(first, min(hrs[1] - last, 24 * 60 - 1) + 1, step)
    return sorted(set(out))


def table_free_times(business_id, rules, tables, day, party, now, exclude_id=None, around=None, rows=None):
    """Giờ còn bàn thật trong ngày `day` ('HH:MM'), chỉ khi quán đã nhập sức chứa."""
    if table_model(rules, tables) == 'none':
        return []
    rows = table_rows(business_id, day, exclude_id) if rows is None else rows
    out = []
    for m in table_candidate_times(rules, day, around):
        when = datetime.combine(day, datetime.min.time()) + timedelta(minutes=m)
        try:
            check_window(rules, when, now, rules['last_booking_before_close'])
        except ReservationError:
            continue
        ok, _why, _t = table_fit(rules, tables, rows, when, party)
        if ok:
            out.append(fmt_min(m))
    return out


def table_status_for(rules, model, party, fit_reason=None):
    """('confirmed'|'pending', lý do chờ) — chỉ tự xác nhận khi quán bật tự xác nhận, đã công bố giờ mở cửa, đã nhập sức
    chứa, nhóm không vượt ngưỡng 'nhóm lớn' và có bàn cụ thể / còn suất trong khung giờ."""
    if model == 'none':
        return 'pending', 'no_live_availability'
    if not rules['hours']:
        return 'pending', 'hours_not_published'
    if fit_reason in ('needs_joined_tables', 'large_party_request') or (rules['max_party_auto'] and party > rules['max_party_auto']):
        return 'pending', 'large_party'
    if not rules['auto_confirm']:
        return 'pending', 'shop_confirms'
    return 'confirmed', None


# ---------------------------------------------------------------- Karaoke / Bida: phòng theo giờ
_PEOPLE = r'(?:người|ng|people|persons|ppl|pax|guests|khách)'
# Khoảng cỡ phòng chỉ khi nằm trong ngoặc '(6-8)' hoặc có chữ chỉ người '6-8 người' — 'Phòng 1-2' là tên, không phải cỡ.
_SIZE_RANGE_RE = re.compile(r'\(\s*(\d{1,3})\s*(?:-|–|—|~|to|đến)\s*(\d{1,3})\s*' + _PEOPLE + r'?\s*\)|'
                            r'(\d{1,3})\s*(?:-|–|—|~|to|đến)\s*(\d{1,3})\s*' + _PEOPLE + r'(?!\w)', re.I)
_SIZE_MAX_RE = re.compile(r'(?:max|tối đa|up to)\s*(\d{1,3})|(\d{1,3})\s*' + _PEOPLE + r'(?!\w)', re.I)
_BILLIARDS_RE = re.compile(r'bida|bi-a|billiard|pool|snooker|carom', re.I)


def room_size(room):
    """Số người tối đa của phòng: trường số (max_guests / capacity / size) nếu có, không thì từ chính tên chủ quán đặt
    ('Phòng Gia Đình (6-8 người)', 'Couple Room (2–4)'); không có -> None (không đoán)."""
    for k in ('max_guests', 'capacity', 'size'):
        n = _num(room.get(k), 0)
        if n > 0:
            return n
    name = str(room.get('name') or '')
    m = _SIZE_RANGE_RE.search(name)
    if m:
        lo, hi = int(m.group(1) or m.group(3)), int(m.group(2) or m.group(4))
        if 0 < lo <= hi:
            return hi
    m = _SIZE_MAX_RE.search(name)
    if m:
        return int(m.group(1) or m.group(2))
    return None


def room_kind(room):
    return 'billiards' if _BILLIARDS_RE.search(str(room.get('name') or '') + ' ' + str(room.get('room_type') or '')) else 'karaoke'


def unassigned_kind(row, rooms):
    """Loại chỗ (karaoke | billiards) của 1 đặt phòng CHƯA xếp phòng: loại khách chọn trên form công khai (room_kind) nếu quán
    có loại đó; không thì ghi chú nhắc bida / pool -> 'billiards' — CHỈ khi quán thật sự có bàn bida (quán chỉ có phòng hát:
    "sau buổi pool party" vẫn là 1 yêu cầu phòng hát, phải được chừa phòng); còn lại = loại mặc định của quán, cùng luật trợ lý
    AI dùng khi khách không nói (có phòng karaoke -> 'karaoke')."""
    kinds = {r['kind'] for r in rooms}
    chosen = str(row.get('room_kind') or '').strip().lower()
    if chosen in kinds:
        return chosen
    if 'billiards' in kinds and _BILLIARDS_RE.search(str(row.get('note') or '')):
        return 'billiards'
    return 'karaoke' if 'karaoke' in kinds or not kinds else 'billiards'


def karaoke_rooms(business_id):
    rooms = []
    for r in db.karaoke_rooms.find({'business_id': business_id}, {'_id': 0}).sort('id', 1):
        rooms.append({'id': r.get('id'), 'name': r.get('name') or f"#{r.get('id')}",
                      'rate': float(_num(r.get('price_per_hour'), 0.0, float) or 0.0), 'max_guests': room_size(r),
                      'kind': room_kind(r), 'in_use': r.get('status') == KARAOKE_IN_USE})
    return rooms


def _fold(s):
    import unicodedata
    s = unicodedata.normalize('NFD', str(s or '').lower().replace('đ', 'd'))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def rooms_matching(rooms, kind=None, room_type=None):
    """Lọc theo loại (karaoke | billiards) + từ khoá loại phòng khách nói ('VIP', 'family'...) khớp tên phòng."""
    out = [r for r in rooms if not kind or r['kind'] == kind]
    q = _fold(room_type).strip()
    if q and q not in ('karaoke', 'billiards', 'bida', 'pool', 'any', 'room', 'phong'):
        out = [r for r in out if q in _fold(r['name'])]
    return out


def karaoke_overlaps(business_id, room_id, reserved_time, duration_hours, exclude_id=None):
    """ĐÚNG luật _karaoke_reservation_overlaps() của app.py (màn nhân viên xếp phòng): True nếu room_id đã có 1 đặt phòng
    KHÁC còn hiệu lực giao với [reserved_time, reserved_time + duration_hours)."""
    try:
        new_start = datetime.fromisoformat(reserved_time)
    except (TypeError, ValueError):
        return False
    new_end = new_start + timedelta(hours=duration_hours)
    query = {'business_id': business_id, 'room_id': room_id, 'status': {'$in': list(KARAOKE_ACTIVE)}}
    if exclude_id is not None:
        query['id'] = {'$ne': exclude_id}
    for other in db.karaoke_room_reservations.find(query, {'id': 1, 'reserved_time': 1, 'duration_hours': 1, '_id': 0}):
        try:
            other_start = datetime.fromisoformat(other['reserved_time'])
        except (TypeError, ValueError):
            continue
        other_end = other_start + timedelta(hours=float(other.get('duration_hours') or 2))
        if new_start < other_end and new_end > other_start:
            return True
    return False


def karaoke_rows(business_id, day, exclude_id=None):
    return _rows_around(db.karaoke_room_reservations, business_id, day, KARAOKE_ACTIVE, exclude_id)


def karaoke_free(rules, rooms, rows, start, hours, now, group=None, kind=None, room_type=None):
    """Phòng còn trống thật cho [start, start+hours): không chồng giờ với đặt phòng đã xếp vào phòng đó, không đang có khách
    vãng lai nếu giờ bắt đầu sát hiện tại, và trừ hao các yêu cầu CHƯA xếp phòng chồng giờ (mỗi yêu cầu sẽ chiếm 1 phòng
    ĐÚNG LOẠI của nó — unassigned_kind: phòng karaoke cuối cùng không được đem cho khách sau khi còn yêu cầu karaoke chờ xếp).
    Trả (phòng hợp nhóm còn trống — vừa cỡ trước, rồi rẻ trước —, phòng trống nhưng không rõ cỡ / chưa đủ thông tin)."""
    end = start + timedelta(hours=hours)
    overlapping = [r for r in rows if r['_start'] < end and r['_start'] + timedelta(hours=float(r.get('duration_hours') or 2)) > start]
    busy = {r.get('room_id') for r in overlapping if r.get('room_id') is not None}
    near = start < now + timedelta(hours=rules['in_use_buffer_hours'])
    free_all = [r for r in rooms if r['id'] not in busy and not (near and r['in_use'])]
    left = {}                                       # phòng trống còn lại theo loại, sau khi chừa cho yêu cầu chưa xếp phòng
    for r in free_all:
        left[r['kind']] = left.get(r['kind'], 0) + 1
    for r in overlapping:
        if r.get('room_id') is None:
            k = unassigned_kind(r, rooms)
            left[k] = left.get(k, 0) - 1
    cands = [r for r in rooms_matching(free_all, kind, room_type) if left.get(r['kind'], 0) > 0]
    fits = [r for r in cands if group and r['max_guests'] is not None and r['max_guests'] >= group]
    unknown = [r for r in cands if r['max_guests'] is None or not group]
    fits.sort(key=lambda r: (r['max_guests'], r['rate'], r['id']))
    unknown.sort(key=lambda r: (r['rate'], r['id']))
    return fits, unknown


def karaoke_candidate_starts(rules, day, hours, around=None):
    """Giờ bắt đầu trong NGÀY LỊCH `day` (phút < 24:00) mà lượt `hours` giờ kết thúc trước giờ đóng — cả phần sau nửa đêm của
    ca đêm hôm trước (mở 18:00-02:00 thứ Sáu -> thứ Bảy 00:00 hát 2 giờ)."""
    step = rules['slot_minutes']
    hrs = hours_on(rules, day)
    if hrs == UNKNOWN:
        if around is None:
            return []
        return [m for m in range(around - 180, around + 181, step) if 0 <= m < 24 * 60]
    tail = overnight_tail(rules, day)
    out = list(range(0, int(tail - hours * 60) + 1, step)) if tail else []
    if hrs is not None:
        first = -(-hrs[0] // step) * step
        out += range(first, min(int(hrs[1] - hours * 60), 24 * 60 - 1) + 1, step)
    return sorted(set(out))


def karaoke_status_for(rules):
    if not rules['hours']:
        return 'pending', 'hours_not_published'
    if not rules['auto_confirm']:
        return 'pending', 'shop_confirms'
    return 'confirmed', None


def note_for_staff(business_id, customer_id, text):
    """1 dòng trong hộp thư AI của chủ quán (cùng cách ai_function_tools ghi khi khách huỷ / dời lịch). Best-effort."""
    try:
        from ai_function_tools import _note_for_staff
        _note_for_staff(business_id, customer_id, text)
    except Exception as e:
        print(f"[reservations_core] staff note: {e}")
