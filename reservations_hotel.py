"""
Đặt phòng khách sạn theo ĐÊM (room-night) — logic DÙNG CHUNG cho form đặt phòng công khai
(/api/public/hotel_reservations/<id> trong app.py) và trợ lý AI lễ tân (ai_packs/hotel.py).

Dữ liệu (không đổi khuôn): db.hotel_rooms (room_number, room_type, price_per_night, capacity, status hiện tại
'Trống'/'Đang ở'/'Đang dọn') và db.hotel_reservations (guest_name, guest_phone, party_size, checkin_date,
checkout_date 'YYYY-MM-DD', room_type, room_id, note, status pending/confirmed/cancelled) — đúng những gì màn
/hotel/reservations và /hotel_rooms của nhân viên đang đọc.

Chặn trùng phòng-đêm NGUYÊN TỬ: mỗi đêm một phòng bị giữ = 1 tài liệu db.hotel_room_nights có _id
"<business_id>|<room_id>|<YYYY-MM-DD>" (_id luôn unique, không cần tạo index mới) — 2 lượt đặt cùng lúc không thể cùng
giữ 1 phòng 1 đêm (giống slot_key của booking_engine). Nguồn sự thật vẫn là hotel_reservations: phiếu giữ của đặt phòng
đã huỷ / đã đổi phòng / đã đổi ngày là phiếu "cũ" và được lấy lại an toàn (find_one_and_update có điều kiện).
Xếp phòng tay trên /hotel/reservations vẫn chặn bằng cùng điều kiện giao nhau như app._hotel_reservation_overlaps
(hàm overlaps() dưới đây giữ ĐÚNG truy vấn đó).

Không import app.py (app.py và ai_packs/hotel.py đều import được module này).
"""
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from mongo_client import db, next_mongo_id

LIVE_STATUSES = ('pending', 'confirmed')
MAX_NIGHTS = 60             # giống giới hạn form công khai
MAX_ADVANCE_DAYS = 366      # giống _public_reservation_check (trong vòng 1 năm)
MAX_GUESTS = 50             # ô "Số khách" của form công khai max=50
CLAIM_GRACE_SECONDS = 120   # phiếu giữ chưa kịp có đặt phòng (đang ghi dở) được coi là còn hiệu lực trong ngần này giây
# Chat web CHƯA xác minh (không SĐT đã xác minh, không hội thoại nền tảng đã ký) giữ tối đa ~40% số phòng MỖI LOẠI MỖI ĐÊM
# VÀ ~40% TỔNG số phòng của khách sạn mỗi đêm (ít nhất 1 phòng) — giới hạn theo khách sạn, KHÔNG dựa vào danh tính người
# chat: xoá mã trình duyệt, đổi SĐT, đổi mạng cũng không giữ được hết phòng (kể cả khách sạn nhỏ mỗi phòng / villa là 1
# loại riêng). Chỉ tính lượt giữ CHƯA người thật nào của khách sạn ghi nhận (unverified_web_hold). Vượt trần -> AI KHÔNG giữ
# phòng mà ghi 1 yêu cầu STAFF_REQUEST cho nhân viên (ai_packs/hotel.py).
UNVERIFIED_WEB_SHARE = 0.4
# Yêu cầu đặt phòng AI chuyển cho nhân viên mà KHÔNG giữ phòng (create_staff_request): hiện trên /hotel/reservations để nhân
# viên Duyệt / Từ chối. KHÔNG thuộc LIVE_STATUSES: không chiếm phòng, không tính vào trần, khách không đổi / huỷ qua chat.
STAFF_REQUEST = 'requested'
OCCUPIED = 'Đang ở'
DEFAULT_ROOM_TYPE = 'Standard'
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_HHMM_RE = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')


class HotelRequestError(ValueError):
    """Yêu cầu không hợp lệ / không làm được — mang sẵn câu EN + VI để route công khai và AI nói thật với khách."""

    def __init__(self, code, en, vi):
        super().__init__(en)
        self.code, self.en, self.vi = code, en, vi

    def text(self, lang='en'):
        return self.vi if lang == 'vi' else self.en


def _require_db():
    if db is None:
        raise RuntimeError("Không có kết nối Database — không thể xử lý đặt phòng lúc này.")


# ---------------------------------------------------------------- kiểm tra dữ liệu khách nhập
def clean_name(value):
    return str(value or '').strip()[:80]


def clean_phone(value):
    return re.sub(r'[^0-9+() .-]', '', str(value or ''))[:24].strip()


def phone_ok(phone):
    return len(re.sub(r'\D', '', phone or '')) >= 6


def parse_day(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value or '').strip()
    if _DATE_RE.match(s):
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            pass
    raise HotelRequestError('bad_date', f"'{s[:20]}' is not a valid date (use YYYY-MM-DD).",
                            f"'{s[:20]}' không phải ngày hợp lệ (dạng YYYY-MM-DD).")


def parse_hhmm(value):
    s = str(value or '').strip()
    m = _HHMM_RE.match(s)
    if not m:
        raise HotelRequestError('bad_time', f"'{s[:10]}' is not a valid time (use HH:MM, 24-hour).",
                                f"'{s[:10]}' không phải giờ hợp lệ (dạng HH:MM, 24 giờ).")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def check_stay(checkin, checkout, today=None, min_nights=1):
    """(ngày nhận, ngày trả, số đêm) hoặc HotelRequestError. today=None: không kiểm quá khứ/quá xa (form công khai đã
    kiểm theo ngày máy chủ ở _public_reservation_check); AI truyền ngày hôm nay THEO GIỜ CỦA KHÁCH SẠN."""
    ci, co = parse_day(checkin), parse_day(checkout)
    if co <= ci:
        raise HotelRequestError('checkout_before_checkin', 'Check-out must be after check-in.',
                                'Ngày trả phòng phải sau ngày nhận phòng.')
    nights = (co - ci).days
    if nights > MAX_NIGHTS:
        raise HotelRequestError('too_many_nights', 'Up to 60 nights per request.', 'Tối đa 60 đêm cho 1 yêu cầu.')
    if today is not None:
        if ci < today:
            raise HotelRequestError('in_the_past', f"Check-in {ci.isoformat()} is in the past (today is {today.isoformat()}).",
                                    f"Ngày nhận phòng {ci.isoformat()} đã qua (hôm nay là {today.isoformat()}).")
        if (ci - today).days > MAX_ADVANCE_DAYS:
            raise HotelRequestError('too_far_ahead', 'Bookings open up to one year ahead.',
                                    'Chỉ nhận đặt phòng trong vòng 1 năm tới.')
    if min_nights and nights < min_nights:
        raise HotelRequestError('min_stay', f"The minimum stay is {min_nights} nights.",
                                f"Khách sạn nhận tối thiểu {min_nights} đêm.")
    return ci, co, nights


def nights_of(ci, co):
    return [(ci + timedelta(days=i)).isoformat() for i in range((co - ci).days)]


# ---------------------------------------------------------------- form đặt phòng công khai (không giữ phòng cụ thể)
def create_request(business_id, *, guest_name, guest_phone, checkin_date, checkout_date, party_size=1,
                   room_type=None, note=None, source=None):
    """Yêu cầu đặt phòng từ form công khai /hotel/reserve/<id>: luôn 'pending', CHƯA xếp phòng (room_id None) — nhân
    viên xếp phòng trên /hotel/reservations (lúc đó mới chặn trùng). Tách nguyên văn từ thân route cũ."""
    _require_db()
    name = str(guest_name or '').strip()
    phone = str(guest_phone or '').strip()
    checkin = str(checkin_date or '').strip()
    checkout = str(checkout_date or '').strip()
    if not business_id or not name or not phone or not checkin or not checkout:
        raise HotelRequestError('missing', 'Please enter your name, phone number and dates.',
                                'Vui lòng nhập đầy đủ tên, số điện thoại và ngày nhận/trả phòng.')
    check_stay(checkin, checkout)
    try:
        party_size = int(party_size or 1)
    except (TypeError, ValueError, OverflowError):
        party_size = 1
    if party_size < 1:
        party_size = 1
    doc = {
        'id': next_mongo_id('hotel_reservations'),
        'business_id': business_id,
        'guest_name': name,
        'guest_phone': phone,
        'party_size': party_size,
        'checkin_date': checkin,
        'checkout_date': checkout,
        'room_type': room_type or None,
        'room_id': None,
        'note': (note or '').strip() or None,
        'status': 'pending',
        'created_at': datetime.now().isoformat(),
    }
    if source:
        doc['source'] = source
    db.hotel_reservations.insert_one(doc)
    doc.pop('_id', None)
    return doc


# ---------------------------------------------------------------- phòng & loại phòng (dữ liệu thật của /hotel_rooms)
def type_key(name):
    return re.sub(r'\s+', ' ', str(name or '')).strip().casefold()


def _rate(value):
    try:
        v = round(float(value), 2)
    except (TypeError, ValueError):
        return None
    return v if v > 0 and v == v and v != float('inf') else None


def _cap(value):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 2  # mặc định của api_hotel_rooms_create


def list_rooms(business_id):
    _require_db()
    rows = list(db.hotel_rooms.find({'business_id': business_id},
                                    {'_id': 0, 'id': 1, 'room_number': 1, 'room_type': 1, 'price_per_night': 1,
                                     'capacity': 1, 'status': 1, 'expected_checkout_date': 1}))
    out = []
    for r in rows:
        if r.get('id') is None:
            continue
        r['room_type'] = str(r.get('room_type') or '').strip() or DEFAULT_ROOM_TYPE
        r['_key'] = type_key(r['room_type'])
        r['_rate'] = _rate(r.get('price_per_night'))
        r['_cap'] = _cap(r.get('capacity'))
        out.append(r)
    return out


def room_types(rooms):
    """{key: {'key','name','rooms','max_guests','rate_min','rate_max'}} — gộp theo room_type (không phân biệt hoa thường)."""
    out = {}
    for r in rooms:
        t = out.setdefault(r['_key'], {'key': r['_key'], '_names': Counter(), 'rooms': []})
        t['_names'][r['room_type']] += 1
        t['rooms'].append(r)
    for t in out.values():
        t['name'] = t.pop('_names').most_common(1)[0][0]
        rates = [r['_rate'] for r in t['rooms'] if r['_rate']]
        t['rate_min'] = min(rates) if rates else None
        t['rate_max'] = max(rates) if rates else None
        t['max_guests'] = max(r['_cap'] for r in t['rooms'])
    return out


def match_type(types, wanted):
    """Khoá loại phòng khớp tên khách nói ('deluxe room' -> 'Deluxe'), None nếu không khớp / mơ hồ."""
    k = type_key(wanted)
    if not k:
        return None
    if k in types:
        return k
    hits = [key for key in types if key and (key in k or k in key)]
    return hits[0] if len(hits) == 1 else None


def _room_sort(r):
    return (r['_rate'] is None, r['_rate'] or 0, str(r.get('room_number') or ''), str(r['id']))


# ---------------------------------------------------------------- trùng lịch (cùng điều kiện với màn nhân viên)
def overlaps(business_id, room_id, checkin_date, checkout_date, exclude_id=None):
    """GIỐNG HỆT app._hotel_reservation_overlaps: room_id đã có đặt phòng KHÁC (pending/confirmed) giao nhau với
    [checkin, checkout) — existing.checkin < new.checkout AND existing.checkout > new.checkin."""
    query = {
        'business_id': business_id, 'room_id': room_id, 'status': {'$in': ['pending', 'confirmed']},
        'checkin_date': {'$lt': checkout_date}, 'checkout_date': {'$gt': checkin_date},
    }
    if exclude_id is not None:
        query['id'] = {'$ne': exclude_id}
    return db.hotel_reservations.find_one(query, {'id': 1, '_id': 0}) is not None


# ---------------------------------------------------------------- phiếu giữ phòng-đêm (nguyên tử)
def _utcnow():
    return datetime.now(timezone.utc)


def _claim_key(business_id, room_id, night):
    return f"{business_id}|{room_id}|{night}"


def _young(claim, now):
    try:
        t = datetime.fromisoformat(str(claim.get('claimed_at')))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (now - t).total_seconds() < CLAIM_GRACE_SECONDS
    except (TypeError, ValueError):
        return False


def _covers(res, night):
    return str(res.get('checkin_date') or '') <= night < str(res.get('checkout_date') or '')


def _claim_live(claim, res, now):
    """Phiếu còn hiệu lực: đặt phòng của nó còn sống, đúng phòng, đêm nằm trong khoảng ở; hoặc chưa có đặt phòng nhưng
    phiếu vừa tạo (lượt đặt khác đang ghi dở). Đặt phòng còn sống nhưng CHƯA khớp phòng / đêm của phiếu = đang xếp phòng
    (assign_room) hoặc đổi ngày (change_dates) dở dang — phiếu giữ trước, room_id / ngày ghi sau — nên phiếu vừa tạo cũng
    còn hiệu lực (trước đây lượt đặt khác lấy lại được đúng phiếu đó giữa 2 bước)."""
    if res is None:
        return _young(claim, now)
    if res.get('status') not in LIVE_STATUSES:
        return False
    if res.get('room_id') == claim.get('room_id') and _covers(res, claim.get('night') or ''):
        return True
    return _young(claim, now)


def _claim_still_live(business_id, claim, now):
    res = db.hotel_reservations.find_one({'business_id': business_id, 'id': claim.get('reservation_id')},
                                         {'_id': 0, 'status': 1, 'room_id': 1, 'checkin_date': 1, 'checkout_date': 1})
    return _claim_live(claim, res, now)


def _drop_claims(keys, reservation_id):
    if keys:
        db.hotel_room_nights.delete_many({'_id': {'$in': list(keys)}, 'reservation_id': reservation_id})


def claim_nights(business_id, room_id, nights, reservation_id, now=None):
    """Giữ phòng room_id cho từng đêm trong `nights` cho reservation_id. Trả list khoá MỚI giữ được (đêm đã là của chính
    đặt phòng này thì bỏ qua), hoặc None nếu có đêm đang bị đặt phòng khác giữ (đã trả lại mọi khoá vừa giữ)."""
    now = now or _utcnow()
    stamp = now.isoformat()
    taken = []
    for night in nights:
        key = _claim_key(business_id, room_id, night)
        doc = {'_id': key, 'business_id': business_id, 'room_id': room_id, 'night': night,
               'reservation_id': reservation_id, 'claimed_at': stamp}
        done = False
        for _attempt in range(3):
            try:
                db.hotel_room_nights.insert_one(dict(doc))
                taken.append(key)
                done = True
                break
            except DuplicateKeyError:
                cur = db.hotel_room_nights.find_one({'_id': key})
                if cur is None:
                    continue  # vừa được trả -> thử giữ lại
                if cur.get('reservation_id') == reservation_id:
                    done = True  # đêm này vốn đã là của đặt phòng này (đổi ngày giữ nguyên phòng)
                    break
                if _claim_still_live(business_id, cur, now):
                    break
                # phiếu cũ (đặt phòng đã huỷ / đổi phòng / đổi ngày): lấy lại có điều kiện — 2 lượt cùng lấy chỉ 1 thắng
                got = db.hotel_room_nights.find_one_and_update(
                    {'_id': key, 'reservation_id': cur.get('reservation_id'), 'claimed_at': cur.get('claimed_at')},
                    {'$set': {'reservation_id': reservation_id, 'claimed_at': stamp}})
                if got is not None:
                    taken.append(key)
                    done = True
                break
        if not done:
            _drop_claims(taken, reservation_id)
            return None
    return taken


def release_claims(business_id, reservation_id, keep=()):
    """Trả mọi phiếu giữ của 1 đặt phòng (trừ `keep`) — huỷ / đổi ngày / đổi phòng."""
    flt = {'business_id': business_id, 'reservation_id': reservation_id}
    if keep:
        flt['_id'] = {'$nin': list(keep)}
    db.hotel_room_nights.delete_many(flt)


# ---------------------------------------------------------------- tình trạng phòng theo đêm
def _night_state(business_id, rooms, nights, today=None, ignore_id=None, now=None):
    """busy[đêm] = phòng không bán được đêm đó; unassigned[đêm][loại] / untyped[đêm] = yêu cầu CHƯA xếp phòng (form
    công khai) vẫn chiếm chỗ theo loại phòng khách chọn (hoặc chiếm 1 phòng bất kỳ nếu không rõ loại)."""
    now = now or _utcnow()
    first, last = nights[0], (parse_day(nights[-1]) + timedelta(days=1)).isoformat()
    room_ids = {r['id'] for r in rooms}
    keys = {r['_key'] for r in rooms}
    busy, unassigned, untyped = defaultdict(set), defaultdict(Counter), Counter()
    live = {}
    for res in db.hotel_reservations.find(
            {'business_id': business_id, 'status': {'$in': list(LIVE_STATUSES)},
             'checkin_date': {'$lt': last}, 'checkout_date': {'$gt': first}},
            {'_id': 0, 'id': 1, 'room_id': 1, 'room_type': 1, 'status': 1, 'checkin_date': 1, 'checkout_date': 1}).limit(20000):
        if ignore_id is not None and res.get('id') == ignore_id:
            continue
        live[res.get('id')] = res
        for n in nights:
            if not _covers(res, n):
                continue
            if res.get('room_id') is not None and res.get('room_id') in room_ids:
                busy[n].add(res['room_id'])
            elif type_key(res.get('room_type')) in keys:
                unassigned[n][type_key(res.get('room_type'))] += 1
            else:
                untyped[n] += 1
    claims = list(db.hotel_room_nights.find({'business_id': business_id, 'night': {'$in': list(nights)}},
                                            {'room_id': 1, 'night': 1, 'reservation_id': 1, 'claimed_at': 1}))
    unknown = {c.get('reservation_id') for c in claims if c.get('reservation_id') not in live and c.get('reservation_id') != ignore_id}
    known_elsewhere = {}
    if unknown:
        for r in db.hotel_reservations.find({'business_id': business_id, 'id': {'$in': list(unknown)}},
                                            {'_id': 0, 'id': 1, 'status': 1, 'room_id': 1, 'checkin_date': 1, 'checkout_date': 1}):
            known_elsewhere[r.get('id')] = r
    for c in claims:
        rid = c.get('reservation_id')
        if rid == ignore_id:
            continue
        res = live.get(rid) or known_elsewhere.get(rid)
        if _claim_live(c, res, now):
            busy[c.get('night')].add(c.get('room_id'))
    # Khách đang ở (check-in tại quầy, có thể không có đặt phòng): phòng 'Đang ở' bận đêm nay, trừ khi đặt phòng của
    # chính phòng đó trả phòng hôm nay (khách cũ đi trưa nay) hoặc khách vãng lai báo trả phòng đúng hôm nay.
    t = today.isoformat() if today else None
    if t and t in nights:
        occupied = [r['id'] for r in rooms if r.get('status') == OCCUPIED and _walkin_until(r, t) != t]
        if occupied:
            leaving = {r.get('room_id') for r in db.hotel_reservations.find(
                {'business_id': business_id, 'status': {'$in': list(LIVE_STATUSES)}, 'checkout_date': t,
                 'room_id': {'$in': occupied}}, {'_id': 0, 'room_id': 1})}
            for rid in occupied:
                if rid not in leaving:
                    busy[t].add(rid)
    # Khách vãng lai đã báo ngày trả phòng (db.hotel_rooms.expected_checkout_date): phòng bận MỌI đêm tới ngày đó, không chỉ
    # đêm nay. Chưa báo ngày -> open_walkins() (không tự xác nhận phòng đó cho các đêm sau).
    if t:
        for r in rooms:
            until = _walkin_until(r, t)
            if until:
                for n in nights:
                    if t <= n < until:
                        busy[n].add(r['id'])
    return busy, unassigned, untyped


def _walkin_until(room, t):
    """Ngày trả phòng dự kiến (hôm nay hoặc sau) của khách vãng lai đang ở phòng này; None nếu không có / đã quá ngày đó
    (khách ở quá ngày đã báo = lại chưa rõ ngày đi)."""
    until = str(room.get('expected_checkout_date') or '').strip()
    return until if (room.get('status') == OCCUPIED and _DATE_RE.match(until) and until >= t) else None


def walkin_checkout_date(value, today, same_day=False):
    """Ngày trả phòng dự kiến nhân viên nhập khi khách vãng lai check-in tại quầy / ở thêm (/api/hotel/rooms/<id>/checkin,
    /expected_checkout): để trống -> None (chưa rõ ngày đi); có thì phải là ngày 'YYYY-MM-DD' theo giờ khách sạn, SAU hôm
    nay, trong vòng 1 năm. HÔM NAY chỉ nhận khi nhân viên chọn rõ "khách trả phòng trong hôm nay" (same_day=True — khách tới
    sau nửa đêm / ở ngắn rồi đi trong ngày): phòng đó trống từ đêm nay, nên không bao giờ suy ra từ 1 ô ngày chọn nhầm.
    Sai -> HotelRequestError (câu VI + EN cho nhân viên)."""
    s = str(value if value is not None else '').strip()
    if not s:
        return None
    day = parse_day(s)
    if day < today or (day == today and same_day is not True):
        raise HotelRequestError('expected_checkout_not_after_today',
                                f"The expected check-out date must be after today ({today.isoformat()}) — for a guest who "
                                "leaves later today (arrived after midnight or a short stay), tick 'Leaves today'.",
                                f"Ngày trả phòng dự kiến phải sau hôm nay ({today.isoformat()}) — khách đi trong hôm nay (tới "
                                "sau nửa đêm hoặc ở ngắn) thì chọn 'Khách trả phòng trong hôm nay'.")
    if (day - today).days > MAX_ADVANCE_DAYS:
        raise HotelRequestError('too_far_ahead', 'The expected check-out date must be within one year.',
                                'Ngày trả phòng dự kiến phải trong vòng 1 năm tới.')
    return day.isoformat()


def open_walkins(business_id, rooms, today):
    """Phòng 'Đang ở' KHÔNG rõ ngày khách rời đi: không có đặt phòng nào của chính phòng đó phủ hôm nay / trả phòng hôm nay,
    cũng không có expected_checkout_date (hoặc đã quá ngày đó) — khách vãng lai check-in tại quầy mà nhân viên để trống ô
    ngày trả phòng dự kiến. Đêm nay đã bận (_night_state); các đêm sau chưa biết khách còn ở hay không nên phòng đó chỉ
    được xếp khi các phòng khác cùng loại đã hết, và KHÔNG BAO GIỜ tự xác nhận (pending + báo nhân viên)."""
    if today is None:
        return set()
    t = today.isoformat()
    occupied = [r['id'] for r in rooms if r.get('status') == OCCUPIED and not _walkin_until(r, t)]
    if not occupied:
        return set()
    known = {r.get('room_id') for r in db.hotel_reservations.find(
        {'business_id': business_id, 'status': {'$in': list(LIVE_STATUSES)}, 'room_id': {'$in': occupied},
         'checkin_date': {'$lte': t}, 'checkout_date': {'$gte': t}}, {'_id': 0, 'room_id': 1})}
    return {rid for rid in occupied if rid not in known}


def _per_type(rooms, types, nights, busy, unassigned, untyped, guests):
    out = {}
    for k, t in types.items():
        per_night = []
        for n in nights:
            free_t = sum(1 for r in t['rooms'] if r['id'] not in busy[n]) - unassigned[n][k]
            total = (sum(1 for r in rooms if r['id'] not in busy[n]) - sum(unassigned[n].values()) - untyped[n])
            per_night.append(min(free_t, total))
        cands = sorted((r for r in t['rooms'] if r['_cap'] >= guests and all(r['id'] not in busy[n] for n in nights)),
                       key=_room_sort)
        out[k] = {'left': min(per_night) if per_night else 0, 'candidates': cands}
    return out


def availability(business_id, checkin, checkout, guests=1, today=None, min_nights=1, ignore_id=None, now=None):
    """Tình trạng THẬT từng loại phòng cho [checkin, checkout): còn mấy phòng, giá/đêm của phòng sẽ được giữ (rẻ nhất còn
    trống, vừa số khách), tổng = giá × số đêm. Mục '_room' là phòng sẽ giữ (nội bộ, không đưa cho khách). '_walkins' = phòng
    có khách vãng lai chưa rõ ngày đi (xếp sau mọi phòng trống khác cùng loại, không tự xác nhận)."""
    ci, co, n = check_stay(checkin, checkout, today=today, min_nights=min_nights)
    guests = max(1, int(guests or 1))
    rooms = list_rooms(business_id)
    types = room_types(rooms)
    out = {'checkin': ci, 'checkout': co, 'nights': n, 'guests': guests, 'types': [], 'rooms_total': len(rooms),
           '_rooms': rooms, '_types': types, '_walkins': set()}
    if not rooms:
        return out
    nights = nights_of(ci, co)
    busy, unassigned, untyped = _night_state(business_id, rooms, nights, today=today, ignore_id=ignore_id, now=now)
    per = _per_type(rooms, types, nights, busy, unassigned, untyped, guests)
    walkins = out['_walkins'] = open_walkins(business_id, rooms, today)
    for k, t in types.items():
        p = per[k]
        if walkins:   # sort ổn định: giữ thứ tự rẻ nhất trước trong từng nhóm
            p['candidates'].sort(key=lambda r: r['id'] in walkins)
        room = p['candidates'][0] if (p['candidates'] and p['left'] > 0) else None
        reason = None
        if guests > t['max_guests']:
            reason = 'too_many_guests'
        elif room is None:
            reason = 'sold_out'
        rate = room['_rate'] if room else None
        out['types'].append({
            'key': k, 'room_type': t['name'], 'rooms_in_type': len(t['rooms']), 'max_guests': t['max_guests'],
            'available': room is not None, 'rooms_left': min(p['left'], len(p['candidates'])) if room else 0,
            'rate_per_night': rate, 'total': round(rate * n, 2) if rate else None, 'reason': reason,
            'rate_min': t['rate_min'], 'rate_max': t['rate_max'], '_room': room, '_candidates': p['candidates'],
        })
    out['types'].sort(key=lambda x: (not x['available'], x['rate_per_night'] is None, x['rate_per_night'] or 0, x['room_type']))
    return out


def _capacity_ok(business_id, rooms, types, ci, co, room, today, ignore_id, now):
    """Kiểm lại SAU khi đã giữ phiếu (phòng vừa giữ tính là bận mọi đêm): loại phòng đó không bị âm chỗ — 2 lượt đặt cùng
    lúc tranh phòng cuối với 1 yêu cầu chưa xếp phòng (form công khai) thì 1 bên phải lùi."""
    nights = nights_of(ci, co)
    busy, unassigned, untyped = _night_state(business_id, rooms, nights, today=today, ignore_id=ignore_id, now=now)
    for n in nights:
        busy[n].add(room['id'])
    per = _per_type(rooms, types, nights, busy, unassigned, untyped, 1)
    return per[room['_key']]['left'] >= 0


# ---------------------------------------------------------------- trần giữ phòng của chat web CHƯA xác minh
def unverified_web_hold(res):
    """Đặt phòng còn hiệu lực do AI giữ từ chat web CHƯA xác minh mà CHƯA người thật nào của khách sạn ghi nhận. Đặt phòng cũ
    (trước khi có trường ai_verified) tính theo kênh: 'web' = chưa xác minh. Không tính vào trần nữa khi: nhân viên đã xem /
    duyệt / sửa / xếp phòng / bấm "Đã xem" trên /hotel/reservations (staff_reviewed_at — khách sạn bật tự xác nhận thì AI ghi
    thẳng 'confirmed', nhân viên không có nút Duyệt), khách đã nhận phòng tại quầy (checked_in_at), hoặc nhân viên đã xác
    nhận (staff_confirmed_at, còn 'confirmed' — dấu của vòng trước). Khách tự đổi ngày trong chat -> change_dates xoá các
    dấu đó (ngày mới chưa ai xem)."""
    if res.get('source') != 'ai_bot':
        return False
    if res.get('staff_reviewed_at') or res.get('checked_in_at'):
        return False
    if res.get('status') == 'confirmed' and res.get('staff_confirmed_at'):
        return False
    if 'ai_verified' in res:
        return not res.get('ai_verified')
    return str(res.get('ai_channel') or 'web').strip().lower() in ('', 'web')


def web_hold_cap(rooms_in_type):
    """Số phòng tối đa của 1 loại phòng mà chat web chưa xác minh được giữ cùng 1 đêm: ~40%, ít nhất 1 (loại chỉ có 1-2 phòng
    vẫn đặt online được)."""
    return max(1, int(round(int(rooms_in_type or 0) * UNVERIFIED_WEB_SHARE)))


def web_holds_full(business_id, rooms, types, key, checkin, checkout, ignore_id=None, extra=1):
    """True nếu ở 1 đêm nào trong [checkin, checkout), số phòng đang bị chat web chưa xác minh giữ (+ `extra` lượt sắp giữ)
    vượt trần THEO LOẠI `key` (web_hold_cap của số phòng loại đó) HOẶC THEO CẢ KHÁCH SẠN (web_hold_cap của tổng số phòng `rooms`,
    mọi loại cộng lại — khách sạn nhỏ mỗi phòng / villa là 1 loại thì trần theo loại = 100% từng phòng). Đếm theo KHÁCH SẠN —
    không theo khách / mã trình duyệt / mạng (những thứ đổi được)."""
    t = types.get(key)
    if not t:
        return False
    ci, co = parse_day(checkin), parse_day(checkout)
    nights = nights_of(ci, co)
    if not nights:
        return False
    cap = web_hold_cap(len(t['rooms']))
    hotel_cap = web_hold_cap(len(rooms))
    room_key = {r['id']: r['_key'] for r in rooms}
    held, held_all = Counter(), Counter()
    for res in db.hotel_reservations.find(
            {'business_id': business_id, 'source': 'ai_bot', 'status': {'$in': list(LIVE_STATUSES)},
             'checkin_date': {'$lt': co.isoformat()}, 'checkout_date': {'$gt': ci.isoformat()}},
            {'_id': 0, 'id': 1, 'source': 1, 'status': 1, 'room_id': 1, 'room_type': 1, 'checkin_date': 1,
             'checkout_date': 1, 'ai_verified': 1, 'ai_channel': 1, 'staff_confirmed_at': 1, 'staff_reviewed_at': 1,
             'checked_in_at': 1}).limit(20000):
        if ignore_id is not None and res.get('id') == ignore_id:
            continue
        if not unverified_web_hold(res):
            continue
        same_type = (room_key.get(res.get('room_id')) or type_key(res.get('room_type'))) == key
        for n in nights:
            if _covers(res, n):
                held_all[n] += 1
                if same_type:
                    held[n] += 1
    return any(held[n] + extra > cap or held_all[n] + extra > hotel_cap for n in nights)


def _web_cap_error():
    return HotelRequestError('web_hold_cap',
                             'Too many rooms (of this room type or in the whole hotel) are already held by unverified online '
                             'chats for these dates — nothing was held; the hotel team takes this request.',
                             'Đã có nhiều phòng (của loại phòng này hoặc của cả khách sạn) được giữ qua chat online chưa xác '
                             'minh những ngày này — chưa giữ phòng nào; nhân viên khách sạn sẽ nhận yêu cầu này.')


def _party(value):
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def create_staff_request(business_id, *, checkin, checkout, guests, room_type, guest_name, guest_phone, extra=None,
                         another_room=False, match_only=False):
    """Yêu cầu đặt phòng mà AI KHÔNG giữ phòng (chat web chưa xác minh vượt trần — web_holds_full): ghi 1 dòng
    db.hotel_reservations trạng thái STAFF_REQUEST, chưa xếp phòng, để nhân viên thấy trên /hotel/reservations (Duyệt = kiểm
    lại phòng trống rồi thành đặt phòng thật; Từ chối = huỷ) — không chỉ là 1 dòng trong hộp thư AI + email chủ (email gộp theo
    giờ, bỏ qua nếu chủ chưa có email). STAFF_REQUEST không thuộc LIVE_STATUSES nên KHÔNG chiếm phòng trong bảng phòng trống
    và không tính vào trần. Cùng hội thoại + ngày + loại phòng + tên đã có yêu cầu đang chờ:
    - cùng số khách -> trả lại yêu cầu đó, không ghi thêm ('duplicate');
    - khác số khách (khách sửa 2 -> 4) -> cập nhật party_size của yêu cầu đó (party_size_was = số cũ) ('updated'), chỉ khi
      dòng VẪN đang chờ (nhân viên vừa Duyệt / Từ chối thì không sửa dòng đã xử lý mà ghi yêu cầu mới) VÀ do CHÍNH chat này
      ghi (cùng mã trình duyệt chat_token_hash — hội thoại web '<khách sạn>:<SĐT tự gõ>' trùng nhau khi 2 trình duyệt gõ cùng
      SĐT: trình duyệt khác không sửa được yêu cầu của người khác, mà ghi yêu cầu mới);
    - another_room=True (khách xin THÊM 1 phòng — như _create_booking giữ thêm phòng thật) -> luôn ghi dòng mới.
    match_only=True: chỉ dò, KHÔNG ghi gì — (dòng, 'duplicate' | 'updated') nếu lời này đi vào 1 trong 2 đường trên, else
    (None, None). ai_packs.hotel._create_booking dò TRƯỚC giới hạn số phòng mỗi chat (_caps): sửa số khách / nói lại y hệt
    yêu cầu đang chờ không phải xin thêm phòng (không bị từ chối 'đặt đoàn', không giữ thêm 1 phòng thật bên cạnh yêu cầu).
    Trả (doc, 'created' | 'updated' | 'duplicate')."""
    _require_db()
    ci, co = parse_day(checkin), parse_day(checkout)
    extra = dict(extra or {})
    party = _party(guests)
    conv = extra.get('ai_conversation_id')
    if conv and not another_room:
        same = [r for r in db.hotel_reservations.find({'business_id': business_id, 'status': STAFF_REQUEST,
                                                       'ai_conversation_id': conv, 'checkin_date': ci.isoformat(),
                                                       'checkout_date': co.isoformat()}, {'_id': 0}).limit(50)
                if type_key(r.get('room_type')) == type_key(room_type)
                and clean_name(r.get('guest_name')).casefold() == clean_name(guest_name).casefold()]
        for r in same:
            if _party(r.get('party_size')) == party:
                return r, 'duplicate'
        token = extra.get('chat_token_hash') or None
        for r in sorted(same, key=lambda x: str(x.get('created_at') or ''), reverse=True):
            if (r.get('chat_token_hash') or None) != token:
                continue
            if match_only:
                return r, 'updated'
            upd = {'party_size': party, 'party_size_was': _party(r.get('party_size')),
                   'updated_at': datetime.now().isoformat()}
            if db.hotel_reservations.update_one({'id': r['id'], 'business_id': business_id, 'status': STAFF_REQUEST},
                                                {'$set': upd}).matched_count:
                return {**r, **upd}, 'updated'
    if match_only:
        return None, None
    doc = {'id': next_mongo_id('hotel_reservations'), 'business_id': business_id, 'guest_name': guest_name,
           'guest_phone': guest_phone, 'party_size': party, 'checkin_date': ci.isoformat(),
           'checkout_date': co.isoformat(), 'room_type': room_type, 'nights': (co - ci).days,
           'created_at': datetime.now().isoformat()}
    doc.update(extra)
    doc.update({'status': STAFF_REQUEST, 'room_id': None})
    db.hotel_reservations.insert_one(doc)
    doc.pop('_id', None)
    return doc, 'created'


def _name_key(value):
    return ' '.join(clean_name(value).split()).casefold()


def same_guest(res, guest_name=None, guest_phone=None, country=None):
    """Khách vừa tới quầy có phải khách của đặt phòng `res`: SĐT trùng NGUYÊN số (reservations_core.same_phone, chuẩn hoá
    theo nước của khách sạn), hoặc họ tên trùng (bỏ hoa/thường, khoảng trắng thừa) mà quầy KHÔNG ghi 1 SĐT đầy đủ khác hẳn
    SĐT của đặt phòng. Không có tên / SĐT nào để so -> False."""
    import reservations_core
    phone = str(guest_phone or '').strip()
    booked_phone = str(res.get('guest_phone') or '').strip()
    if phone and booked_phone and reservations_core.same_phone(booked_phone, phone, country):
        return True
    name = _name_key(guest_name)
    if not name or name != _name_key(res.get('guest_name')):
        return False
    return not (len(re.sub(r'\D', '', phone)) >= 8 and len(re.sub(r'\D', '', booked_phone)) >= 8)


def mark_checked_in(business_id, room_id, today, now=None, guest_name=None, guest_phone=None):
    """Nhân viên vừa nhận khách vào phòng room_id tại quầy (/api/hotel/rooms/<id>/checkin, tên + SĐT khách nhập ở quầy):
    đặt phòng còn hiệu lực của CHÍNH phòng đó phủ đêm nay (nhận phòng <= hôm nay < trả phòng, theo giờ khách sạn) VÀ là của
    ĐÚNG khách vừa tới (same_guest) = người thật của đặt phòng đó đã tới -> checked_in_at + staff_reviewed_at, không còn tính
    vào trần giữ phòng của chat web chưa xác minh. Khách vãng lai / người khác nhận vào phòng đang có đặt phòng AI chưa xác
    minh (khách đó không tới, đặt giả, hay lượt giữ nhiều đêm bắt đầu từ hôm trước) -> đặt phòng đó VẪN tính vào trần (đúng
    là khách đó thì nhân viên bấm "Đã xem" trên /hotel/reservations). Trả số đặt phòng được đánh dấu."""
    _require_db()
    t = today.isoformat()
    stamp = (now or _utcnow()).isoformat()
    country = None
    if str(guest_phone or '').strip():
        import reservations_core
        country = reservations_core.country_of(business_id)
    live = {'business_id': business_id, 'room_id': room_id, 'status': {'$in': list(LIVE_STATUSES)},
            'checkin_date': {'$lte': t}, 'checkout_date': {'$gt': t}}
    marked = 0
    for res in db.hotel_reservations.find(live, {'_id': 0, 'id': 1, 'guest_name': 1, 'guest_phone': 1}).limit(50):
        if not same_guest(res, guest_name, guest_phone, country):
            continue
        marked += db.hotel_reservations.update_one(
            dict(live, id=res['id']), {'$set': {'checked_in_at': stamp, 'staff_reviewed_at': stamp}}).modified_count
    return marked


# ---------------------------------------------------------------- giữ phòng + tạo / đổi / huỷ đặt phòng
MAX_ROOMS_TRIED = 8


def _try_room(business_id, room, rooms, types, ci, co, reservation_id, today, now, exclude_id=None):
    """Giữ đủ các đêm của 1 phòng cho reservation_id rồi kiểm lại sức chứa + trùng lịch với màn nhân viên.
    Trả (khoá vừa giữ, None) khi thành công; (None, 'room_taken') nếu phòng này vừa bị giữ (thử phòng khác);
    (None, 'sold_out') nếu loại phòng đã hết chỗ (đừng thử thêm phòng cùng loại)."""
    taken = claim_nights(business_id, room['id'], nights_of(ci, co), reservation_id, now=now)
    if taken is None:
        return None, 'room_taken'
    if not _capacity_ok(business_id, rooms, types, ci, co, room, today, exclude_id, now):
        _drop_claims(taken, reservation_id)
        return None, 'sold_out'
    if overlaps(business_id, room['id'], ci.isoformat(), co.isoformat(), exclude_id=exclude_id):
        _drop_claims(taken, reservation_id)
        return None, 'room_taken'
    return taken, None


def create_hold(business_id, *, checkin, checkout, guests, room_type_key, guest_name, guest_phone, status,
                today=None, min_nights=1, extra=None, now=None, unverified=False):
    """Đặt phòng GIỮ PHÒNG CỤ THỂ (dùng cho trợ lý AI): chọn phòng rẻ nhất còn trống của loại khách chọn, giữ nguyên tử
    từng đêm, ghi db.hotel_reservations với room_id. Trả (doc, availability) — doc None nếu hết phòng.
    unverified=True (chat web chưa xác minh — đặt phòng ghi source='ai_bot', ai_verified=False): loại phòng hoặc cả khách
    sạn đã chạm trần (web_holds_full) ở 1 đêm nào -> HotelRequestError 'web_hold_cap', không giữ gì. Kiểm lại SAU khi ghi
    (đếm cả lượt vừa ghi): 2 chat cùng lúc tranh suất cuối mà cả 2 đều qua bước kiểm trước rồi cùng ghi xong trước khi bên nào
    kiểm lại thì CẢ 2 đều thấy vượt trần và CẢ 2 cùng huỷ phiếu của mình (an toàn: không bao giờ vượt trần — cả 2 thành yêu
    cầu cho nhân viên, suất đó để trống cho khách đã xác minh / nhân viên); chỉ khi 1 bên kiểm lại sau lúc bên kia đã huỷ thì
    bên kia mới giữ được."""
    _require_db()
    now = now or _utcnow()
    av = availability(business_id, checkin, checkout, guests=guests, today=today, min_nights=min_nights, now=now)
    for _attempt in range(2):
        t = next((x for x in av['types'] if x['key'] == room_type_key), None)
        if not t or not t['available']:
            return None, av
        rooms, types = av['_rooms'], av['_types']
        ci, co = av['checkin'], av['checkout']
        if unverified and web_holds_full(business_id, rooms, types, room_type_key, ci, co):
            raise _web_cap_error()
        res_id = next_mongo_id('hotel_reservations')
        for room in t['_candidates'][:MAX_ROOMS_TRIED]:
            taken, why = _try_room(business_id, room, rooms, types, ci, co, res_id, today, now)
            if taken is None:
                if why == 'sold_out':
                    break
                continue
            doc = {
                'id': res_id, 'business_id': business_id, 'guest_name': guest_name, 'guest_phone': guest_phone,
                'party_size': av['guests'], 'checkin_date': ci.isoformat(), 'checkout_date': co.isoformat(),
                'room_type': t['room_type'], 'room_id': room['id'],
                'status': 'pending' if (status == 'confirmed' and room['id'] in av['_walkins']) else status,
                'nights': av['nights'], 'rate_per_night': room['_rate'],
                'quoted_total': round(room['_rate'] * av['nights'], 2) if room['_rate'] else None,
                'created_at': datetime.now().isoformat(),
            }
            doc.update(extra or {})
            if unverified:   # lượt giữ này phải tự được đếm ở bước kiểm trần SAU khi ghi (unverified_web_hold)
                doc.setdefault('source', 'ai_bot')
                doc['ai_verified'] = False
            db.hotel_reservations.insert_one(doc)
            doc.pop('_id', None)
            if overlaps(business_id, room['id'], doc['checkin_date'], doc['checkout_date'], exclude_id=res_id):
                # Nhân viên vừa xếp tay đúng phòng này đúng lúc này (màn nhân viên không giữ phiếu): nhường, thử lại.
                db.hotel_reservations.update_one({'id': res_id, 'business_id': business_id},
                                                 {'$set': {'status': 'cancelled', 'cancelled_by': 'system',
                                                           'cancel_reason': 'room assigned by staff at the same moment',
                                                           'cancelled_at': datetime.now().isoformat()}})
                release_claims(business_id, res_id)
                break
            if unverified and web_holds_full(business_id, rooms, types, room_type_key, ci, co, extra=0):
                # Chat web chưa xác minh khác vừa giữ cùng lúc: tự huỷ, không vượt trần (bên kia cũng có thể huỷ — xem docstring).
                db.hotel_reservations.update_one({'id': res_id, 'business_id': business_id},
                                                 {'$set': {'status': 'cancelled', 'cancelled_by': 'system',
                                                           'cancel_reason': 'unverified online hold limit reached',
                                                           'cancelled_at': datetime.now().isoformat()}})
                release_claims(business_id, res_id)
                raise _web_cap_error()
            return doc, av
        av = availability(business_id, checkin, checkout, guests=guests, today=today, min_nights=min_nights, now=now)
    return None, av


def _change_plan(business_id, res, checkin, checkout, guests, today, min_nights, now):
    """Phương án đổi ngày DÙNG CHUNG cho báo giá (quote_change) và ghi (change_dates): xem phòng trống KHÔNG tính chính đặt
    phòng này là bận; giữ nguyên phòng nếu còn trống, không thì phòng rẻ nhất còn trống CÙNG loại — giá báo = giá sẽ ghi."""
    guests = max(1, int(guests or res.get('party_size') or 1))
    av = availability(business_id, checkin, checkout, guests=guests, today=today, min_nights=min_nights,
                      ignore_id=res['id'], now=now)
    cur_room = {r['id']: r for r in av['_rooms']}.get(res.get('room_id'))
    key = cur_room['_key'] if cur_room else match_type(av['_types'], res.get('room_type'))
    t = next((x for x in av['types'] if x['key'] == key), None)
    if t and t['reason'] == 'too_many_guests':
        raise HotelRequestError(
            'too_many_guests',
            f"A {t['room_type']} room fits up to {t['max_guests']} guests, so the booking was NOT changed. For more guests "
            "book an additional room or ask the hotel.",
            f"Phòng {t['room_type']} tối đa {t['max_guests']} khách nên đặt phòng CHƯA được đổi. Đông hơn thì đặt thêm phòng "
            "hoặc hỏi khách sạn.")
    order = []
    if res.get('room_id') is None or cur_room is None:
        ok = (t['available'] if t else any(x['available'] for x in av['types']))
        rate = t['rate_per_night'] if (t and ok) else None
    else:
        ok = bool(t and t['available'])
        if ok:
            order = ([r for r in t['_candidates'] if r['id'] == cur_room['id']]
                     + [r for r in t['_candidates'] if r['id'] != cur_room['id']])
        rate = order[0]['_rate'] if order else None
    return {'av': av, 'guests': guests, 'cur_room': cur_room, 'key': key, 't': t, 'available': bool(ok), 'order': order,
            'room': order[0] if order else None, 'rate': rate,
            'total': round(rate * av['nights'], 2) if rate else None}


def quote_change(business_id, res, checkin, checkout, guests=None, today=None, min_nights=1, now=None):
    """Báo giá đổi ngày / số khách TRƯỚC khi khách đồng ý: còn phòng không (đêm của CHÍNH đặt phòng này không tính là bận),
    phòng sẽ giữ và tổng tiền THẬT change_dates sẽ ghi nếu đổi lúc này. HotelRequestError nếu ngày sai / quá số khách."""
    _require_db()
    return _change_plan(business_id, res, checkin, checkout, guests, today, min_nights, now or _utcnow())


_ANY_RATE = object()


def change_dates(business_id, res, checkin, checkout, guests=None, today=None, min_nights=1, new_status=None, now=None,
                 expect_rate=_ANY_RATE):
    """Đổi ngày ở (kiểm lại phòng trống thật). Giữ nguyên phòng nếu còn trống, không thì phòng khác CÙNG loại. Đặt phòng
    chưa xếp phòng (form công khai) chỉ kiểm theo số phòng của loại đó (nhân viên vẫn xếp phòng sau).
    expect_rate = giá/đêm đã báo khách (quote_change): chỉ ghi ĐÚNG giá đó — giá vừa đổi (phòng vừa bị giữ...) thì
    HotelRequestError 'price_changed', không ghi gì. Đặt phòng đã xác nhận được đánh dấu was_confirmed: về 'pending' vẫn theo
    hạn huỷ của đặt phòng đã xác nhận. Phòng có khách vãng lai chưa rõ ngày đi -> không giữ 'confirmed'.
    Trả (doc mới, availability) — doc None nếu ngày mới hết phòng. HotelRequestError nếu đặt phòng vừa bị đổi nơi khác."""
    _require_db()
    now = now or _utcnow()
    plan = _change_plan(business_id, res, checkin, checkout, guests, today, min_nights, now)
    av, cur_room, guests = plan['av'], plan['cur_room'], plan['guests']
    ci, co = av['checkin'], av['checkout']
    rooms, types = av['_rooms'], av['_types']
    if plan['available'] and expect_rate is not _ANY_RATE and plan['rate'] != expect_rate:
        raise _price_changed()
    cas = {'id': res['id'], 'business_id': business_id, 'status': {'$in': list(LIVE_STATUSES)},
           'checkin_date': res.get('checkin_date'), 'checkout_date': res.get('checkout_date'), 'room_id': res.get('room_id')}
    upd = {'checkin_date': ci.isoformat(), 'checkout_date': co.isoformat(), 'party_size': guests, 'nights': av['nights'],
           'changed_from': {'checkin_date': res.get('checkin_date'), 'checkout_date': res.get('checkout_date'),
                            'room_id': res.get('room_id')},
           'changed_at': datetime.now().isoformat()}
    if new_status:
        upd['status'] = new_status
    if res.get('status') == 'confirmed' or res.get('was_confirmed'):
        upd['was_confirmed'] = True   # hạn huỷ của đặt phòng đã xác nhận vẫn áp dụng khi chờ khách sạn xác nhận lại
    # Nhân viên duyệt / xem (Đã xem / sửa / xếp phòng) NGÀY CŨ; ngày mới chưa ai duyệt / xem (trần chat web chưa xác minh).
    # LUÔN xoá, không theo bản `res` đã đọc: CAS bên dưới không canh 2 trường này, nhân viên bấm giữa lúc đọc và lúc ghi thì
    # dấu của ngày cũ cũng không được sống sót trên ngày mới.
    upd['staff_confirmed_at'] = None
    upd['staff_reviewed_at'] = None

    if res.get('room_id') is None or cur_room is None:
        if not plan['available']:
            return None, av
        rate = plan['rate']
        upd.update({'rate_per_night': rate, 'quoted_total': round(rate * av['nights'], 2) if rate else None})
        if db.hotel_reservations.update_one(cas, {'$set': upd}).matched_count == 0:
            raise _changed_meanwhile()
        return {**res, **upd}, av

    if not plan['available']:
        return None, av
    tried, sold_out = plan['order'][:MAX_ROOMS_TRIED], False
    for room in tried:
        if room['_rate'] != plan['rate']:
            continue   # không bao giờ ghi giá khác giá đã báo khách
        taken, why = _try_room(business_id, room, rooms, types, ci, co, res['id'], today, now, exclude_id=res['id'])
        if taken is None:
            if why == 'sold_out':
                sold_out = True
                break
            continue
        rate = room['_rate']
        upd.update({'room_id': room['id'], 'rate_per_night': rate,
                    'quoted_total': round(rate * av['nights'], 2) if rate else None})
        if room['id'] in av['_walkins'] and upd.get('status', res.get('status')) == 'confirmed':
            upd['status'] = 'pending'
        if db.hotel_reservations.update_one(cas, {'$set': upd}).matched_count == 0:
            _drop_claims(taken, res['id'])
            raise _changed_meanwhile()
        release_claims(business_id, res['id'], keep=[_claim_key(business_id, room['id'], n) for n in nights_of(ci, co)])
        return {**res, **upd}, av
    if not sold_out and any(r['_rate'] != plan['rate'] for r in tried):
        raise _price_changed()   # chỉ còn phòng giá khác -> báo lại giá, không tự đổi giá
    return None, av


def _price_changed():
    return HotelRequestError('price_changed',
                             'The price for these dates just changed, so the booking was NOT changed. Check the new total '
                             'with the guest before changing it.',
                             'Giá những ngày này vừa thay đổi nên đặt phòng CHƯA được đổi. Báo lại tổng tiền mới cho khách '
                             'trước khi đổi.')


def _changed_meanwhile():
    return HotelRequestError('changed_meanwhile', 'This booking was just changed by the hotel — please check it again.',
                             'Đặt phòng này vừa được khách sạn cập nhật — vui lòng xem lại.')


def cancel(business_id, reservation_id, by, extra=None):
    """Huỷ 1 đặt phòng còn hiệu lực (nguyên tử: chỉ pending/confirmed) và trả phiếu giữ phòng. None nếu đã huỷ trước đó."""
    _require_db()
    fields = {'status': 'cancelled', 'cancelled_by': by, 'cancelled_at': datetime.now().isoformat()}
    fields.update(extra or {})
    doc = db.hotel_reservations.find_one_and_update(
        {'id': reservation_id, 'business_id': business_id, 'status': {'$in': list(LIVE_STATUSES)}},
        {'$set': fields}, projection={'_id': 0}, return_document=ReturnDocument.AFTER)
    if doc:
        release_claims(business_id, reservation_id)
    return doc


def assign_room(business_id, res, room_id, now=None):
    """Xếp phòng cụ thể cho 1 đặt phòng có giữ phiếu nguyên tử — để màn /hotel/reservations dùng thay cho kiểm trùng
    không nguyên tử (việc của người tích hợp). True nếu xếp được, False nếu phòng đã có khách khác; HotelRequestError
    'changed_meanwhile' nếu đặt phòng vừa bị đổi ngày / phòng / huỷ ở nơi khác so với bản `res` (không ghi gì)."""
    _require_db()
    now = now or _utcnow()
    ci, co = parse_day(res['checkin_date']), parse_day(res['checkout_date'])
    taken = claim_nights(business_id, room_id, nights_of(ci, co), res['id'], now=now)
    if taken is None:
        return False
    if overlaps(business_id, room_id, ci.isoformat(), co.isoformat(), exclude_id=res['id']):
        _drop_claims(taken, res['id'])
        return False
    # Ghi CÓ ĐIỀU KIỆN theo đúng bản đã giữ phiếu (giống change_dates): khách vừa dời ngày trong chat thì phiếu vừa giữ là
    # cho các đêm CŨ — ghi room_id lên ngày MỚI sẽ xếp trùng phòng.
    snap = {'id': res['id'], 'business_id': business_id, 'status': {'$in': list(LIVE_STATUSES)},
            'checkin_date': res.get('checkin_date'), 'checkout_date': res.get('checkout_date'), 'room_id': res.get('room_id')}
    if db.hotel_reservations.update_one(snap, {'$set': {'room_id': room_id}}).matched_count == 0:
        _drop_claims(taken, res['id'])
        raise _changed_meanwhile()
    if overlaps(business_id, room_id, ci.isoformat(), co.isoformat(), exclude_id=res['id']):
        # Lượt khác vừa ghi đúng phòng này đúng lúc này (giống kiểm lại sau khi ghi của create_hold): trả lại phòng cũ.
        db.hotel_reservations.update_one({'id': res['id'], 'business_id': business_id, 'room_id': room_id},
                                         {'$set': {'room_id': res.get('room_id')}})
        _drop_claims(taken, res['id'])
        return False
    release_claims(business_id, res['id'], keep=[_claim_key(business_id, room_id, n) for n in nights_of(ci, co)])
    return True


# ---------------------------------------------------------------- cài đặt khách sạn của chủ (db.booking_settings.hotel)
SETTINGS_DEFAULTS = {
    'auto_confirm': False,       # chỉ True khi chủ xác nhận BitPaw là lịch phòng DUY NHẤT (không bán song song Booking/Airbnb)
    'min_nights': 1,
    'checkin_time': None,        # 'HH:MM' giờ địa phương
    'checkout_time': None,
    'free_cancel_hours': None,   # huỷ miễn phí tới N giờ trước giờ nhận phòng (đặt phòng đã xác nhận); None = chưa đặt
}


def _clean_settings(raw, strict):
    out = dict(SETTINGS_DEFAULTS)
    raw = raw if isinstance(raw, dict) else {}
    if 'auto_confirm' in raw:
        out['auto_confirm'] = bool(raw.get('auto_confirm'))
    for k, lo, hi in (('min_nights', 1, MAX_NIGHTS), ('free_cancel_hours', 0, 24 * 60)):
        v = raw.get(k)
        if v in (None, ''):
            continue
        try:
            out[k] = max(lo, min(int(v), hi))
        except (TypeError, ValueError):
            if strict:
                raise HotelRequestError('bad_setting', f"{k} must be a number.", f"{k} phải là số.")
    for k in ('checkin_time', 'checkout_time'):
        v = raw.get(k)
        if v in (None, ''):
            continue
        try:
            out[k] = parse_hhmm(v)
        except HotelRequestError:
            if strict:
                raise
    return out


def hotel_settings(business_id):
    row = db.booking_settings.find_one({'business_id': business_id}, {'_id': 0, 'hotel': 1}) or {}
    return _clean_settings(row.get('hotel'), strict=False)


def save_hotel_settings(business_id, data):
    """Cho trang cài đặt của chủ (người tích hợp nối vào /settings/booking). $set riêng khoá 'hotel' — không đụng luật
    đặt lịch khác (booking_rules.save_rules cũng chỉ $set khoá của nó)."""
    clean = _clean_settings(data, strict=True)
    db.booking_settings.update_one({'business_id': business_id},
                                   {'$set': {'hotel': clean, 'updated_at': datetime.now().isoformat()}}, upsert=True)
    return clean


def cancel_allowed(res, settings, now_local):
    """(được huỷ qua chat?, mã lý do). Yêu cầu còn 'pending' mà khách sạn CHƯA TỪNG xác nhận: được (AI còn chặn từ ngày nhận
    phòng); đặt phòng đã xác nhận — kể cả đã xác nhận rồi đổi ngày, đang chờ xác nhận lại (was_confirmed): trước hạn huỷ
    miễn phí của chủ (free_cancel_hours trước giờ nhận phòng, chưa đặt giờ nhận phòng thì tính từ 00:00 ngày nhận phòng),
    chưa đặt hạn thì trước NGÀY nhận phòng. Sau đó khách sạn quyết (có thể mất phí) — AI chuyển cho nhân viên."""
    if res.get('status') == 'pending' and not res.get('was_confirmed'):
        return True, 'pending_request'
    ci = parse_day(res.get('checkin_date'))
    now = now_local.replace(tzinfo=None) if getattr(now_local, 'tzinfo', None) else now_local
    hours = settings.get('free_cancel_hours')
    if hours is not None:
        hh, mm = (settings.get('checkin_time') or '00:00').split(':')
        deadline = datetime.combine(ci, time(int(hh), int(mm))) - timedelta(hours=int(hours))
        return (now < deadline), ('within_free_cancellation' if now < deadline else 'past_free_cancellation')
    return (now.date() < ci), ('before_checkin_day' if now.date() < ci else 'checkin_day_or_later')
