"""
Phần dùng chung cho các module kịch bản scenarios_<ngành>.py của sim_receptionist.py (chỉ hàm thuần + ĐỌC dữ liệu tiệm).

Mọi ngày/giờ trong kịch bản là giờ TIỆM (shop['now'], shop['dates'] do sim_receptionist.load_shop tính theo múi giờ tiệm);
mục tiêu của khách giả lập luôn ghi kèm ngày cụ thể (vd "Friday 14/11") để giám khảo và DB so được chính xác.
"""
import re
from datetime import datetime, timedelta

DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def money(amount, currency):
    cur = (currency or 'USD').upper()
    try:
        a = float(amount or 0)
    except (TypeError, ValueError):
        return str(amount)
    if cur == 'VND':
        return f"{a:,.0f}₫".replace(',', '.')
    sym = {'USD': '$', 'AUD': 'A$', 'CAD': 'C$', 'NZD': 'NZ$'}.get(cur, cur + ' ')
    return f'{sym}{a:,.2f}'


def num(v, default=0.0):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if x == x and abs(x) != float('inf') else default


def hm(s):
    h, m = str(s).split(':')[:2]
    return int(h) * 60 + int(m)


def fmt_hm(minutes):
    minutes = int(minutes) % (24 * 60)
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def hours_on(shop, day):
    """(mở, đóng) theo phút của ngày `day` nếu chủ đã công bố giờ mở cửa; None = đóng cửa; 'unknown' = chưa công bố."""
    hours = shop.get('hours')
    if not hours:
        return 'unknown'
    v = hours.get(DAY_KEYS[day.weekday()])
    if not v:
        return None
    a, b = hm(v[0]), hm(v[1])
    if b <= a:
        b += 24 * 60
    return a, b


def fits(shop, day, hhmm, before_close=60, lead_minutes=90):
    """Giờ này có hợp lý để đặt không: trong giờ mở cửa (nếu đã công bố), kết thúc trước giờ đóng, chưa qua."""
    t = hm(hhmm)
    when = datetime.combine(day, datetime.min.time()) + timedelta(minutes=t)
    if when < shop['now'] + timedelta(minutes=lead_minutes):
        return False
    h = hours_on(shop, day)
    if h == 'unknown':
        return True
    if h is None:
        return False
    return h[0] <= t <= h[1] - before_close


def pick_slot(shop, start_day, prefer=('19:00', '18:30', '19:30', '18:00', '20:00', '12:30'), before_close=60, max_days=10):
    """(ngày, 'HH:MM') đầu tiên từ start_day mà một trong các giờ ưa thích hợp lệ; không có thì giờ mở cửa + 1 tiếng."""
    for k in range(max_days):
        d = start_day + timedelta(days=k)
        for t in prefer:
            if fits(shop, d, t, before_close):
                return d, t
    for k in range(max_days):
        d = start_day + timedelta(days=k)
        h = hours_on(shop, d)
        if isinstance(h, tuple):
            t = fmt_hm(min(h[0] + 60, h[1] - before_close))
            if fits(shop, d, t, before_close):
                return d, t
    return start_day + timedelta(days=1), prefer[0]


def closed_time(shop, day):
    """Một giờ CHẮC CHẮN ngoài giờ mở cửa của ngày `day` (để thử bot có đặt bừa không) — None nếu không biết giờ mở cửa."""
    h = hours_on(shop, day)
    if h == 'unknown':
        return None
    if h is None:
        return '12:00'
    for t in ('03:00', '04:30', '05:00'):
        m = hm(t)
        if not (h[0] <= m < h[1] or h[0] <= m + 24 * 60 < h[1]):
            return t
    return None


def at(day, hhmm):
    return f'{day.isoformat()}T{hhmm}'


def stamp(day, hhmm):
    """Định dạng giờ lưu trong bảng đặt chỗ (giống form công khai): 'YYYY-MM-DDTHH:MM:00'."""
    return f'{day.isoformat()}T{hhmm}:00'


def say_day(day, today=None):
    """'Friday 14/11' (+ 'today' / 'tomorrow') — khách giả lập nói ngày cụ thể, không mơ hồ."""
    base = f'{DAY_NAMES[day.weekday()]} {day:%d/%m}'
    if today is not None:
        if day == today:
            return f'today ({base})'
        if day == today + timedelta(days=1):
            return f'tomorrow ({base})'
    return base


def say_time(hhmm):
    h, m = map(int, hhmm.split(':'))
    suffix = 'am' if h < 12 else 'pm'
    h12 = h % 12 or 12
    return f'{h12}{":%02d" % m if m else ""}{suffix}'


def products(db, biz, channel=None, priced=True, limit=300):
    """Sản phẩm / dịch vụ ĐANG BÁN của tiệm (chỉ đọc)."""
    flt = {'business_id': biz, 'is_active': {'$in': [1, True]}}
    if channel:
        flt['channel_type'] = channel
    rows = []
    for p in db.products.find(flt, {'_id': 0, 'id': 1, 'name': 1, 'price': 1, 'stock': 1, 'held_qty': 1, 'category': 1,
                                    'allergens': 1, 'channel_type': 1}).limit(limit):
        if not p.get('name'):
            continue
        if priced and not num(p.get('price')) > 0:
            continue
        rows.append(p)
    rows.sort(key=lambda p: (str(p.get('category') or ''), str(p.get('name') or '')))
    return rows


def price_lines(rows, currency, limit=60):
    return '\n'.join(f"- {p['name']}: {money(p.get('price'), currency)}" for p in rows[:limit])


def booking_settings(db, biz):
    return db.booking_settings.find_one({'business_id': biz}, {'_id': 0}) or {}


# = reservations_core.GENERAL_SAVED_MARK: chủ quán đã lưu công tắc chung ở trang Cài đặt đặt chỗ. Trang Cài đặt đặt lịch CŨ
# luôn ghi auto_confirm=True (mặc định Nails) cho mọi ngành — giá trị đó không phải lựa chọn của quán, AI không tính.
GENERAL_SAVED_MARK = 'reservations_general_saved_at'


def auto_confirm_of(bs, sub_key=None):
    """Tự xác nhận theo đúng thứ tự gói đặt chỗ đọc (reservations_core.load_rules): khối riêng của loại chỗ (True / False) >
    công tắc chung CHỈ khi chủ đã lưu nó ở trang Cài đặt đặt chỗ (GENERAL_SAVED_MARK) > còn lại = chờ duyệt."""
    sub = bs.get(sub_key) if sub_key and isinstance(bs.get(sub_key), dict) else {}
    if isinstance(sub.get('auto_confirm'), bool):
        return sub['auto_confirm']
    if 'auto_confirm' in bs and bs.get(GENERAL_SAVED_MARK):
        return bool(bs['auto_confirm'])
    return False


def statuses(auto_possible):
    """Trạng thái hợp lệ của dòng AI tạo: tiệm không thể tự xác nhận -> CHỈ 'pending' (bot xác nhận là sai)."""
    return ['pending', 'confirmed'] if auto_possible else ['pending']


_PEOPLE = r'(?:người|nguoi|pax|people|persons?|guests?|ppl|khách|khach)'
_SIZE_RANGE_RE = re.compile(r'\(\s*(\d{1,3})\s*(?:-|–|—|~|to|đến)\s*(\d{1,3})\s*' + _PEOPLE + r'?\s*\)|'
                            r'(\d{1,3})\s*(?:-|–|—|~|to|đến)\s*(\d{1,3})\s*' + _PEOPLE + r'(?!\w)', re.I)
_SIZE_MAX_RE = re.compile(r'(?:max|tối đa|up to)\s*(\d{1,3})|(\d{1,3})\s*' + _PEOPLE + r'(?!\w)', re.I)


def room_size(room):
    """Sức chứa phòng: trường số nếu có, không thì từ tên ('Family Room (6–8)') — None nếu không biết (không đoán)."""
    for k in ('max_guests', 'capacity', 'size', 'seats'):
        n = int(num(room.get(k)))
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


def info_line(shop):
    if not shop.get('info'):
        return 'Owner-published policies (deposit / cancellation / parking...): none published.'
    return 'Owner-published policies: ' + '; '.join(f'{k}: {v}' for k, v in shop['info'].items()) + '.'


def created(collection, match, status_in=None, alt=None):
    c = {'kind': 'created', 'collection': collection, 'match': match}
    if status_in:
        c['status_in'] = list(status_in)
    if alt:
        c['alt'] = alt
    return c


def created_any(collection, match, status_in=None):
    c = {'kind': 'created_any', 'collection': collection, 'match': match}
    if status_in:
        c['status_in'] = list(status_in)
    return c


def check(kind, **kw):
    return dict(kw, kind=kind)


# cùng tập trạng thái "đã huỷ / hết hiệu lực" với sim_receptionist.CANCELLED (đọc trạng thái kiểu status hoặc trang_thai)
DEAD = {'cancelled', 'canceled', 'released', 'expired', 'declined', 'rejected', 'void', 'voided', 'picked_up',
        'đã hủy', 'hủy', 'da huy', 'huy', 'đã từ chối'}


def is_live(row):
    s = str((row or {}).get('status') or (row or {}).get('trang_thai') or '').strip().lower().replace('huỷ', 'hủy')
    return s not in DEAD


def parse_dt(v):
    try:
        return datetime.fromisoformat(str(v)[:19])
    except (TypeError, ValueError):
        return None


def words(name, min_len=3):
    """Từ khoá nhận ra 1 món trong ghi chú ('Beer Bucket (24 cans)' -> ['~beer', '~bucket', '~cans'])."""
    return ['~' + w for w in re.findall(r'[^\W\d_]+', str(name or '').lower()) if len(w) >= min_len][:4]
