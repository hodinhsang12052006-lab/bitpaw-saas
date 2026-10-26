# -*- coding: utf-8 -*-
"""
Bảng xoay tua thợ Nails (turn board) — trước đây landing Nails + thẻ giá Essential quảng cáo "xoay tua thợ công bằng"
nhưng hệ thống KHÔNG có gì cả (Phase 0 đã gỡ dòng trên thẻ giá). File này là tính năng thật.

Cách tiệm nail người Việt ở Mỹ/Úc chạy tua (và cách các app "turn tracker" làm):
  - Thợ vào ca theo thứ tự check-in (app nhân viên / camera chấm công ghi db.chamcong: ngay_cham DD/MM/YYYY + gio_den HH:MM).
    Check-in trong ngày tự đưa thợ lên bảng; quầy cũng thêm tay được (thợ không dùng app).
  - Khách walk-in vào: giao cho thợ ĐỨNG ĐẦU HÀNG đang rảnh. Hàng xếp theo: ít tua nhất trước; bằng tua thì ai chờ
    trong hàng lâu hơn trước (thứ tự check-in, hoặc lúc làm xong khách trước).
  - Tua đủ / nửa tua theo giá vé: vé >= ngưỡng (tiền của tiệm, chủ tiệm đặt) = 1 tua; dưới ngưỡng = nửa tua
    ("2 nửa tua = 1 tua"). Chưa biết giá lúc giao khách -> tạm tính 1 tua, chốt giá lúc "Xong" (gắn vé POS hoặc gõ số).
  - Khách request (chỉ định thợ): mặc định KHÔNG tính tua (cài được nửa/đủ) và thợ giữ nguyên chỗ trong hàng.
    Lịch hẹn "thợ nào cũng được": mặc định tính như walk-in theo giá (cài được đủ/nửa/không tính).
  - Bỏ lượt (skip/pass): thợ xuống cuối nhóm cùng số tua (cài được phạt nửa/1 tua). Nghỉ trưa: giữ chỗ, không nhận khách.
    Thợ vào muộn: vào CUỐI hàng (bắt đầu bằng số tua thấp nhất của người đang làm), không "đuổi kịp" bằng cách nhận liền
    nhiều khách.
  - Mọi thao tác là 1 dòng nhật ký (db.nail_turns) — trạng thái bảng = gấp lại nhật ký; "Hoàn tác" = đánh dấu voided
    (không xoá), nên tranh cãi "ai tới lượt" có lịch sử để xem lại.

Lưu trữ: db.nail_turns (nhật ký theo business_id + day giờ tiệm), db.nail_turn_settings (1 dòng/tiệm).
Quyền: mọi tài khoản của tiệm Nails XEM được; admin/super_admin thao tác (nhân viên thao tác được nếu chủ tiệm bật
"máy quầy dùng tài khoản nhân viên"); cài đặt + sửa ngày cũ + huỷ 1 dòng bất kỳ chỉ admin.
Đăng ký: app.py `from nail_turns import nail_turns_bp; app.register_blueprint(nail_turns_bp)`.
"""
import re
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, session

from app import login_required
from mongo_client import db, next_mongo_id

nail_turns_bp = Blueprint('nail_turns', __name__)

ADMIN_ROLES = ('admin', 'super_admin')
CHECKIN_STATES = ('Có mặt', 'Trọn Ngày', 'Check-in')          # các trạng thái chấm công = đã tới tiệm
COUNT_RULES = {'none': 0.0, 'half': 0.5, 'full': 1.0}
APPT_RULES = ('amount', 'full', 'half', 'none')
KINDS = ('walk_in', 'appointment', 'request')
ACTIONS = ('join', 'skip', 'break', 'back', 'leave')
DEFAULT_FULL_TURN_MIN = {'USD': 30.0, 'AUD': 45.0, 'CAD': 35.0, 'NZD': 45.0, 'GBP': 25.0, 'VND': 150000.0}
COUNTRY_CURRENCY = {'US': 'USD', 'AU': 'AUD', 'VN': 'VND', 'CA': 'CAD', 'NZ': 'NZD', 'GB': 'GBP'}
POS_CHANNELS = ['nail_pos', 'nail_pos_square']
POS_PAID = ['completed', 'PAID', 'paid', 'partially_refunded']
HHMM = re.compile(r'^\s*([01]?\d|2[0-3]):([0-5]\d)')
DAY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
HISTORY_DAYS = 62
MAX_MONEY = 10_000_000
LOG_LIMIT = 120
_CACHE = {}
_CACHE_TTL = 30


# ------------------------------------------------------------------ phiên / quyền / ngôn ngữ
def _bid():
    return session.get('business_id') or session.get('user_id')


def _role():
    return session.get('role') or 'staff'


def _is_admin():
    return _role() in ADMIN_ROLES


def _vi():
    try:
        from i18n import resolve_lang
        return resolve_lang(request) == 'vi'
    except Exception:
        return (request.cookies.get('bitpaw_lang') or '') == 'vi'


def _t(vi, en):
    return vi if _vi() else en


def _err(status, vi, en, **extra):
    return jsonify({'success': False, 'message': _t(vi, en), **extra}), status


def _wants_json():
    return request.path.startswith('/api/') or 'application/json' in (request.headers.get('Accept') or '')


def nail_only(f):
    """Bảng tua chỉ dành cho tiệm Nails (industry_access chưa có dòng cho endpoint này -> tự chặn ở đây)."""
    @wraps(f)
    def inner(*args, **kwargs):
        if _role() != 'super_admin' and (session.get('business_mode') or '').strip().lower() != 'nail':
            if _wants_json():
                return _err(403, 'Bảng xoay tua chỉ dành cho tiệm Nails.', 'The turn board is for nail salons only.')
            return redirect('/')
        if not _bid():
            return _err(401, 'Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại.', 'Your session has ended. Please sign in again.')
        return f(*args, **kwargs)
    return inner


def _cached(key, fn, ttl=_CACHE_TTL):
    hit = _CACHE.get(key)
    now = time.time()
    if hit and now - hit[1] < ttl:
        return hit[0]
    val = fn()
    _CACHE[key] = (val, now)
    return val


# ------------------------------------------------------------------ tiệm: tiền tệ + giờ địa phương
def _biz(bid):
    return _cached(('biz', bid), lambda: db.businesses.find_one({'id': bid}, {'_id': 0, 'country': 1, 'currency': 1, 'name': 1}) or {})


def shop_currency(bid):
    biz = _biz(bid)
    cur = str(biz.get('currency') or '').strip().upper()
    if re.fullmatch(r'[A-Z]{3}', cur):
        return cur
    return COUNTRY_CURRENCY.get(str(biz.get('country') or '').strip().upper(), 'USD')


def _local_now(bid):
    """Giờ hiện tại CỦA TIỆM (máy chủ Vercel chạy UTC) — cùng nguồn múi giờ với lịch hẹn (booking_rules)."""
    try:
        import booking_rules
        return booking_rules.local_now(bid)
    except Exception:
        return datetime.now()


def _server_now():
    return datetime.now()


def _server_bounds(bid, day):
    """[đầu ngày, đầu ngày sau) của ngày `day` giờ tiệm, đổi ra giờ máy chủ (orders.created_at = datetime.now() máy chủ)."""
    off = _server_now() - _local_now(bid)
    off = timedelta(minutes=round(off.total_seconds() / 60))
    start = datetime.strptime(day, '%Y-%m-%d') + off
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def _ngay_cham(day):
    y, m, d = day.split('-')
    return f'{d}/{m}/{y}'


def _parse_day(raw, today):
    """Ngày xem (YYYY-MM-DD), mặc định hôm nay; chỉ trong HISTORY_DAYS ngày gần nhất, không xem ngày tương lai."""
    raw = str(raw or '').strip()
    if not raw:
        return today
    if not DAY_RE.match(raw):
        return None
    try:
        d = datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None
    t = datetime.strptime(today, '%Y-%m-%d').date()
    if d > t or (t - d).days > HISTORY_DAYS:
        return None
    return raw


def _money(v):
    """(số tiền | None, lỗi). Rỗng/0 = chưa biết giá."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, None
    try:
        x = round(float(str(v).replace(',', '').strip()), 2)
    except (TypeError, ValueError):
        return None, ('Số tiền không hợp lệ.', 'That amount is not a number.')
    if x != x or x < 0 or x > MAX_MONEY:
        return None, ('Số tiền không hợp lệ.', 'That amount is out of range.')
    return (x if x > 0 else None), None


# ------------------------------------------------------------------ cài đặt
def default_settings(currency):
    return {'full_turn_min': DEFAULT_FULL_TURN_MIN.get(currency, 30.0), 'request_counts': 'none',
            'appointment_counts': 'amount', 'skip_counts': 'none', 'staff_can_assign': False, 'exclude': []}


def get_settings(bid):
    cur = shop_currency(bid)
    s = default_settings(cur)
    row = db.nail_turn_settings.find_one({'business_id': bid}, {'_id': 0}) or {}
    clean, _ = clean_settings(row, s, partial=True)
    s.update(clean)
    s['currency'] = cur
    s['configured'] = bool(row)
    return s


def clean_settings(data, current, partial=False):
    """(dict hợp lệ, lỗi (vi, en) | None). partial=True: bỏ qua khoá thiếu/sai (đọc DB), False: báo lỗi (người dùng gửi)."""
    out = {}
    if 'full_turn_min' in data:
        v, e = _money(data.get('full_turn_min'))
        if e or v is None:
            if not partial:
                return {}, ('Ngưỡng tua đủ phải là số lớn hơn 0.', 'The full-turn price must be a number above 0.')
        else:
            out['full_turn_min'] = v
    for key, allowed in (('request_counts', COUNT_RULES), ('appointment_counts', APPT_RULES), ('skip_counts', COUNT_RULES)):
        if key in data:
            v = str(data.get(key) or '').strip().lower()
            if v in allowed:
                out[key] = v
            elif not partial:
                return {}, ('Lựa chọn không hợp lệ.', 'That option is not valid.')
    if 'staff_can_assign' in data:
        out['staff_can_assign'] = bool(data.get('staff_can_assign'))
    if 'exclude' in data:
        raw = data.get('exclude') or []
        if isinstance(raw, list):
            out['exclude'] = sorted({str(x).strip()[:64] for x in raw if str(x).strip()})[:200]
        elif not partial:
            return {}, ('Danh sách thợ không hợp lệ.', 'The technician list is not valid.')
    return out, None


def can_assign(settings):
    return _is_admin() or (_role() == 'staff' and bool(settings.get('staff_can_assign')))


def turn_value(kind, amount, settings):
    """(giá trị tua, tạm tính?) — 1 = tua đủ, 0.5 = nửa tua, 0 = không tính."""
    if kind == 'request':
        return COUNT_RULES.get(settings.get('request_counts'), 0.0), False
    if kind == 'appointment' and settings.get('appointment_counts') in COUNT_RULES:
        return COUNT_RULES[settings['appointment_counts']], False
    if amount is None:
        return 1.0, True                       # chưa có giá: tạm tính tua đủ, chốt lúc "Xong"
    return (1.0 if amount >= float(settings.get('full_turn_min') or 0) - 1e-9 else 0.5), False


# ------------------------------------------------------------------ gấp nhật ký -> trạng thái bảng (hàm thuần, test được)
def _ev_key(ev):
    return (str(ev.get('at') or ''), int(ev.get('id') or 0))


def fold(events):
    """Trạng thái từng thợ sau khi áp lần lượt mọi dòng nhật ký CÒN HIỆU LỰC (không voided), theo thời gian rồi id.

    Thứ tự hàng: (số tua, rank) tăng dần. rank = số thứ tự của dòng nhật ký gần nhất đưa thợ về cuối nhóm cùng số tua:
    vào bảng, làm xong 1 khách CÓ tính tua, hoặc bỏ lượt. Khách không tính tua (request) và nghỉ trưa giữ nguyên chỗ.
    """
    members, turns = {}, {}
    idx = 0
    for ev in sorted((e for e in events if not e.get('voided')), key=_ev_key):
        idx += 1
        typ, ma = ev.get('type'), ev.get('ma_nv')
        m = members.get(ma)
        if typ == 'join':
            working = [x['turns'] for x in members.values() if x['status'] in ('available', 'busy')]
            floor = min(working) if working else 0.0
            if m is None:
                members[ma] = {'ma_nv': ma, 'name': ev.get('name') or ma, 'status': 'available', 'turns': floor,
                               'start_turns': floor, 'rank': idx, 'joined_at': ev.get('at'), 'source': ev.get('source'),
                               'checkin': ev.get('checkin') or '', 'current_turn': None, 'busy_since': None,
                               'turn_ids': [], 'skips': 0}
            elif m['status'] == 'left':
                m['status'] = 'available'
                if m['turns'] < floor:
                    m['start_turns'] += floor - m['turns']
                    m['turns'] = floor
                m['rank'] = idx
            continue
        if m is None:
            continue                            # dòng của thợ chưa vào bảng (dữ liệu hỏng) -> bỏ qua
        if typ == 'turn':
            v = float(ev.get('value') or 0)
            m['turns'] += v
            m['status'] = 'busy'
            m['current_turn'] = ev.get('id')
            m['busy_since'] = ev.get('at')
            m['turn_ids'].append(ev.get('id'))
            turns[ev.get('id')] = ev
        elif typ == 'done':
            t = turns.get(ev.get('turn_id'))
            if m['current_turn'] == ev.get('turn_id'):
                m['status'] = 'available'
                m['current_turn'] = None
                m['busy_since'] = None
                if t is not None and float(t.get('value') or 0) > 0:
                    m['rank'] = idx
        elif typ == 'skip':
            m['turns'] += float(ev.get('value') or 0)
            m['skips'] += 1
            m['rank'] = idx
        elif typ == 'break':
            if m['status'] == 'available':
                m['status'] = 'break'
        elif typ == 'back':
            if m['status'] == 'break':
                m['status'] = 'available'
        elif typ == 'leave':
            if m['status'] in ('available', 'break'):
                m['status'] = 'left'
    for m in members.values():
        m['turns'] = round(m['turns'], 3)
    return members, turns


def line_order(members):
    """Mọi thợ còn ở tiệm theo thứ tự tua (ít tua trước, rồi ai chờ lâu hơn)."""
    return sorted((m for m in members.values() if m['status'] != 'left'), key=lambda m: (m['turns'], m['rank']))


def next_up(members):
    for m in line_order(members):
        if m['status'] == 'available':
            return m['ma_nv']
    return None


# ------------------------------------------------------------------ đọc dữ liệu thật của tiệm
def _technicians(bid, settings):
    """{ma_nv: hồ sơ} — thợ Nails (linh_vuc 'Nails', cùng nguồn với POS /sell); tiệm chưa gắn lĩnh vực thì lấy mọi nhân viên.
    Bỏ người chủ tiệm đánh dấu "không xếp tua" (lễ tân, chủ...)."""
    rows = list(db.employees.find({'business_id': bid}, {'_id': 0, 'ma_nv': 1, 'ho_ten': 1, 'linh_vuc': 1}).sort('ho_ten', 1))
    rows = [r for r in rows if r.get('ma_nv')]
    nails = [r for r in rows if str(r.get('linh_vuc') or '').strip().lower() in ('nails', 'nail')]
    excl = set(settings.get('exclude') or [])
    return {str(r['ma_nv']): {'ma_nv': str(r['ma_nv']), 'name': r.get('ho_ten') or str(r['ma_nv'])}
            for r in (nails or rows) if str(r['ma_nv']) not in excl}


def _all_staff(bid):
    rows = db.employees.find({'business_id': bid}, {'_id': 0, 'ma_nv': 1, 'ho_ten': 1, 'linh_vuc': 1}).sort('ho_ten', 1)
    return [{'ma_nv': str(r['ma_nv']), 'name': r.get('ho_ten') or str(r['ma_nv']), 'dept': r.get('linh_vuc') or ''}
            for r in rows if r.get('ma_nv')]


def checkins(bid, day):
    """{ma_nv: 'HH:MM' giờ check-in sớm nhất trong ngày ('' nếu bản ghi không có giờ)} từ db.chamcong."""
    out = {}
    q = {'business_id': bid, 'ngay_cham': _ngay_cham(day), 'trang_thai': {'$in': list(CHECKIN_STATES)}}
    for r in db.chamcong.find(q, {'_id': 0, 'ma_nv': 1, 'gio_den': 1}):
        ma = str(r.get('ma_nv') or '').strip()
        if not ma:
            continue
        mt = HHMM.match(str(r.get('gio_den') or ''))
        t = f'{int(mt.group(1)):02d}:{mt.group(2)}' if mt else ''
        prev = out.get(ma)
        if prev is None or (t and (not prev or t < prev)):
            out[ma] = t
    return out


def _events(bid, day):
    return list(db.nail_turns.find({'business_id': bid, 'day': day}, {'_id': 0}).sort('id', 1))


def _stamp(bid):
    return {'at': _local_now(bid).strftime('%Y-%m-%dT%H:%M:%S'), 'created_at': _server_now().isoformat(),
            'by': str(session.get('user_email') or session.get('user_id') or ''), 'by_role': _role()}


def sync_attendance(bid, day, events, techs, ins=None):
    """Thợ đã check-in hôm nay (chấm công thật) mà chưa có trên bảng -> thêm 1 dòng 'join' (nguồn: chấm công).
    Giờ vào bảng = giờ check-in, nhưng không bao giờ chen TRƯỚC các thao tác đã ghi (không đảo lịch sử): check-in nhập
    muộn vào cuối hàng. Không ghi gì nếu không có ai mới."""
    seen = {e.get('ma_nv') for e in events if e.get('type') == 'join' and e.get('source') == 'attendance'}
    present = {e.get('ma_nv') for e in events if e.get('type') == 'join' and not e.get('voided')}
    ins = checkins(bid, day) if ins is None else ins
    fresh = [(t, ma) for ma, t in ins.items() if ma in techs and ma not in seen and ma not in present]
    if not fresh:
        return events
    now_at = _local_now(bid).strftime('%Y-%m-%dT%H:%M:%S')
    last_at = max((str(e.get('at') or '') for e in events), default='')
    added = []
    for t, ma in sorted(fresh, key=lambda x: (x[0] or '99:99', x[1])):
        at = f'{day}T{t}:00' if t else now_at
        at = min(max(at, last_at), now_at) if last_at <= now_at else now_at
        doc = {'id': next_mongo_id('nail_turns'), 'business_id': bid, 'day': day, 'type': 'join', 'ma_nv': ma,
               'name': techs[ma]['name'], 'source': 'attendance', 'checkin': t, 'at': at,
               'created_at': _server_now().isoformat(), 'by': 'attendance', 'by_role': 'system', 'voided': False}
        # 2 máy quầy cùng tải bảng: upsert theo khoá (tiệm, ngày, thợ, nguồn chấm công) -> chỉ 1 dòng
        db.nail_turns.update_one({'business_id': bid, 'day': day, 'type': 'join', 'source': 'attendance', 'ma_nv': ma},
                                 {'$setOnInsert': doc}, upsert=True)
        added.append(doc)
    return _events(bid, day) if added else events


def _today(bid):
    return _local_now(bid).strftime('%Y-%m-%d')


def _load(bid, day, settings, sync=True, with_checkins=False):
    """(thợ, nhật ký, trạng thái thợ, tua còn hiệu lực, giờ check-in | None). Hôm nay: tự thêm thợ vừa check-in."""
    techs = _technicians(bid, settings)
    events = _events(bid, day)
    ins = checkins(bid, day) if (with_checkins or (sync and day == _today(bid))) else None
    if sync and day == _today(bid):
        events = sync_attendance(bid, day, events, techs, ins)
    members, turns = fold(events)
    excl = set(settings.get('exclude') or [])
    for ma in [x for x in members if x in excl]:
        members.pop(ma)
    return techs, events, members, turns, ins


def _pos_lines(bid, since_iso, until_iso=None, ma_list=None):
    """[(order_id, created_at, ma_nv, số tiền dòng dịch vụ)] của vé POS Nails đã thu tiền trong khoảng giờ máy chủ."""
    q = {'business_id': bid, 'created_at': {'$gte': since_iso}, 'metadata.channel': {'$in': POS_CHANNELS},
         'status': {'$in': POS_PAID}}
    if until_iso:
        q['created_at']['$lt'] = until_iso
    orders = {o['id']: o for o in db.orders.find(q, {'_id': 0, 'id': 1, 'created_at': 1, 'status': 1}) if o.get('id') is not None}
    if not orders:
        return []
    iq = {'order_id': {'$in': list(orders)}, 'business_id': bid}
    if ma_list is not None:
        iq['ma_nv'] = {'$in': list(ma_list)}
    out = []
    for it in db.order_items.find(iq, {'_id': 0, 'order_id': 1, 'ma_nv': 1, 'total_price': 1}):
        try:
            amt = float(it.get('total_price') or 0)
        except (TypeError, ValueError):
            amt = 0.0
        if it.get('ma_nv'):
            out.append((it['order_id'], orders[it['order_id']].get('created_at'), str(it['ma_nv']), amt))
    return out


def _ticket_amount_for(bid, order_id, ma):
    """Tổng tiền các dòng dịch vụ của thợ `ma` trên 1 vé POS của tiệm (None = vé không tồn tại / thợ không có trên vé)."""
    try:
        oid = int(order_id)
    except (TypeError, ValueError):
        return None
    if not db.orders.find_one({'id': oid, 'business_id': bid, 'metadata.channel': {'$in': POS_CHANNELS}}, {'_id': 0, 'id': 1}):
        return None
    total, found = 0.0, False
    for it in db.order_items.find({'order_id': oid, 'business_id': bid, 'ma_nv': ma}, {'_id': 0, 'total_price': 1}):
        found = True
        try:
            total += float(it.get('total_price') or 0)
        except (TypeError, ValueError):
            pass
    return round(total, 2) if found else None


def _linked_orders(turns):
    return {t.get('order_id') for t in turns.values() if t.get('order_id') is not None}


def _pos_suggestions(bid, members, turns):
    """Vé POS đã thu cho thợ đang làm khách, tạo SAU lúc giao khách và chưa gắn vào tua nào -> gợi ý 1 chạm lúc "Xong"."""
    busy = {m['ma_nv']: turns.get(m['current_turn']) for m in members.values() if m['status'] == 'busy' and turns.get(m['current_turn'])}
    if not busy:
        return {}
    since = min(str(t.get('created_at') or '') for t in busy.values())
    linked = _linked_orders(turns)
    sums = {}
    for oid, created, ma, amt in _pos_lines(bid, since, ma_list=list(busy)):
        t = busy.get(ma)
        if t is None or oid in linked or str(created or '') < str(t.get('created_at') or ''):
            continue
        key = (ma, oid)
        sums[key] = (round(sums.get(key, (0, ''))[0] + amt, 2), created)
    out = {}
    for (ma, oid), (amt, created) in sums.items():
        out.setdefault(ma, []).append({'order_id': oid, 'amount': amt, 'created_at': created})
    for ma in out:
        out[ma].sort(key=lambda x: x['created_at'] or '', reverse=True)
        out[ma] = out[ma][:3]
    return out


def _services(bid):
    rows = db.products.find({'business_id': bid, 'is_active': 1}, {'_id': 0, 'id': 1, 'name': 1, 'price': 1, 'category': 1}).sort('name', 1)
    out = []
    for r in rows:
        try:
            price = round(float(r.get('price') or 0), 2)
        except (TypeError, ValueError):
            price = 0.0
        if r.get('id') is not None and r.get('name'):
            out.append({'id': r['id'], 'name': str(r['name'])[:80], 'price': price})
    return out[:300]


def _appointments_today(bid, day, techs, turns):
    linked = {t.get('appointment_id') for t in turns.values() if t.get('appointment_id') is not None}
    q = {'business_id': bid, 'book_time': {'$gte': f'{day}T00:00', '$lte': f'{day}T23:59'},
         'status': {'$in': ['pending', 'confirmed', 'checked_in']}}
    rows = list(db.appointments.find(q, {'_id': 0, 'id': 1, 'book_time': 1, 'customer_name': 1, 'service_id': 1,
                                         'staff_id': 1, 'status': 1}).sort('book_time', 1))
    svc_ids = list({r['service_id'] for r in rows if r.get('service_id') is not None})
    names = {}
    if svc_ids:
        for p in db.products.find({'id': {'$in': svc_ids}, 'business_id': bid}, {'_id': 0, 'id': 1, 'name': 1, 'price': 1}):
            names[p['id']] = p
    out = []
    for r in rows:
        if r.get('id') in linked:
            continue
        svc = names.get(r.get('service_id')) or {}
        first = str(r.get('customer_name') or '').strip().split(' ')[0][:24]
        staff = str(r['staff_id']) if r.get('staff_id') else None
        out.append({'id': r['id'], 'time': str(r.get('book_time') or '')[11:16], 'customer': first,
                    'service': svc.get('name'), 'price': svc.get('price'), 'status': r.get('status'),
                    'staff_id': staff, 'staff_name': (techs.get(staff) or {}).get('name') if staff else None})
    return out[:60]


# ------------------------------------------------------------------ trình bày
def _member_out(m, turns, suggestions=None):
    live = [turns[i] for i in m['turn_ids'] if i in turns]
    cur = turns.get(m['current_turn']) if m['current_turn'] else None
    return {
        'ma_nv': m['ma_nv'], 'name': m['name'], 'status': m['status'], 'turns': m['turns'],
        'checkin': m['checkin'], 'joined_at': (m['joined_at'] or '')[11:16], 'source': m['source'],
        'start_turns': round(m['start_turns'], 3), 'skips': m['skips'],
        'pips': [float(t.get('value') or 0) for t in live],
        'current': _turn_out(cur) if cur else None,
        'pos_suggestions': (suggestions or {}).get(m['ma_nv'], []),
    }


def _turn_out(t):
    return {'id': t.get('id'), 'kind': t.get('kind'), 'amount': t.get('amount'), 'value': float(t.get('value') or 0),
            'provisional': bool(t.get('provisional')), 'service': t.get('service'), 'order_id': t.get('order_id'),
            'appointment_id': t.get('appointment_id'), 'at': str(t.get('at') or '')[11:16]}


def _log_out(events, show_by):
    rows = []
    for e in sorted(events, key=_ev_key, reverse=True)[:LOG_LIMIT]:
        r = {'id': e.get('id'), 'type': e.get('type'), 'ma_nv': e.get('ma_nv'), 'name': e.get('name'),
             'time': str(e.get('at') or '')[11:16], 'voided': bool(e.get('voided')), 'source': e.get('source'),
             'checkin': e.get('checkin'), 'kind': e.get('kind'), 'amount': e.get('amount'),
             'value': e.get('value'), 'provisional': bool(e.get('provisional')), 'service': e.get('service'),
             'order_id': e.get('order_id'), 'out_of_turn': bool(e.get('out_of_turn')), 'turn_id': e.get('turn_id'),
             'next_up_name': e.get('next_up_name')}
        if show_by:
            r['by'] = e.get('by')
            r['voided_by'] = e.get('voided_by')
        rows.append(r)
    return rows


def _undoable(events):
    """Dòng cuối cùng còn hiệu lực mà quầy được hoàn tác (không tính dòng tự thêm từ chấm công)."""
    live = [e for e in events if not e.get('voided') and not (e.get('type') == 'join' and e.get('source') == 'attendance')]
    return max(live, key=_ev_key) if live else None


def board_payload(bid, day, settings, lite=False):
    """Toàn bộ bảng tua của 1 ngày. lite=True (máy quầy hỏi lại mỗi vài giây): bỏ danh sách dịch vụ (ít đổi)."""
    today = _today(bid)
    is_today = day == today
    techs, events, members, turns, ins = _load(bid, day, settings, sync=is_today, with_checkins=True)
    may = can_assign(settings) and is_today
    order = line_order(members)
    nxt = next_up(members)
    sugg = _pos_suggestions(bid, members, turns) if may else {}
    line, busy, brk = [], [], []
    for m in order:
        out = _member_out(m, turns, sugg)
        {'available': line, 'busy': busy, 'break': brk}[m['status']].append(out)
    busy.sort(key=lambda x: (x['current'] or {}).get('at') or '')
    gone = [_member_out(m, turns) for m in sorted(members.values(), key=lambda x: x['name'].lower()) if m['status'] == 'left']
    not_on = [{'ma_nv': ma, 'name': t['name'], 'checkin': ins.get(ma)} for ma, t in techs.items() if ma not in members]
    last = _undoable(events) if may else None
    payload = {
        'success': True, 'day': day, 'today': today, 'is_today': is_today,
        'now': _local_now(bid).strftime('%H:%M:%S'), 'currency': settings['currency'],
        'settings': {k: settings[k] for k in ('full_turn_min', 'request_counts', 'appointment_counts', 'skip_counts',
                                              'staff_can_assign', 'exclude', 'configured')},
        'can_assign': may, 'can_admin': _is_admin(), 'role': _role(),
        'rev': max((int(e.get('id') or 0) for e in events), default=0),
        'next_up': nxt, 'line': line, 'busy': busy, 'on_break': brk, 'gone': gone, 'not_on_board': not_on,
        'tech_count': len(techs), 'log': _log_out(events, _is_admin()),
        'undo': {'id': last.get('id'), 'type': last.get('type'), 'name': last.get('name')} if last else None,
    }
    if may:
        if not lite:
            payload['services'] = _services(bid)
        payload['appointments'] = _appointments_today(bid, day, techs, turns)
    return payload


def summary_rows(bid, day, settings):
    """Tổng kết cuối ngày theo từng thợ: số tua (đủ / nửa / không tính), bỏ lượt, tiền vé ghi trên bảng, doanh số dịch vụ POS."""
    _techs, events, members, turns, _ins = _load(bid, day, settings, sync=False)
    lo, hi = _server_bounds(bid, day)
    pos = {}
    for _oid, _c, ma, amt in _pos_lines(bid, lo, hi):
        pos[ma] = round(pos.get(ma, 0.0) + amt, 2)
    rows = []
    for m in sorted(members.values(), key=lambda x: (x['joined_at'] or '', x['name'].lower())):
        live = [turns[i] for i in m['turn_ids'] if i in turns]
        vals = [float(t.get('value') or 0) for t in live]
        rows.append({
            'ma_nv': m['ma_nv'], 'name': m['name'], 'checkin': m['checkin'], 'status': m['status'],
            'clients': len(live), 'turns': round(sum(vals), 3),
            'full': sum(1 for v in vals if v >= 1), 'half': sum(1 for v in vals if 0 < v < 1),
            'not_counted': sum(1 for v in vals if v <= 0),
            'requests': sum(1 for t in live if t.get('kind') == 'request'),
            'appointments': sum(1 for t in live if t.get('kind') == 'appointment'),
            'pending_price': sum(1 for t in live if t.get('provisional')),
            'skips': m['skips'], 'skip_turns': round(m['turns'] - m['start_turns'] - sum(vals), 3),
            'ticket_total': round(sum(float(t.get('amount') or 0) for t in live), 2),
            'pos_sales': pos.get(m['ma_nv'], 0.0),
        })
    tot = {k: round(sum(r[k] for r in rows), 3 if k in ('turns', 'skip_turns') else 2)
           for k in ('clients', 'turns', 'full', 'half', 'not_counted', 'requests', 'appointments', 'pending_price',
                     'skips', 'skip_turns', 'ticket_total', 'pos_sales')}
    for k in ('clients', 'full', 'half', 'not_counted', 'requests', 'appointments', 'pending_price', 'skips'):
        tot[k] = int(tot[k])
    off_board = round(sum(v for ma, v in pos.items() if ma not in members), 2)
    return {'success': True, 'day': day, 'currency': settings['currency'], 'rows': rows, 'total': tot,
            'pos_sales_not_on_board': off_board}


# ------------------------------------------------------------------ ghi nhật ký
def _insert(bid, day, typ, ma, name, **fields):
    doc = {'id': next_mongo_id('nail_turns'), 'business_id': bid, 'day': day, 'type': typ, 'ma_nv': ma, 'name': name,
           'voided': False, **_stamp(bid), **fields}
    db.nail_turns.insert_one(doc)
    doc.pop('_id', None)
    return doc


def _void(bid, ev, reason=None):
    db.nail_turns.update_one({'id': ev['id'], 'business_id': bid},
                             {'$set': {'voided': True, 'voided_at': _local_now(bid).strftime('%Y-%m-%dT%H:%M:%S'),
                                       'voided_by': str(session.get('user_email') or session.get('user_id') or ''),
                                       'void_reason': reason or 'undo'}})


def _fresh(bid, settings, status=200, **extra):
    body = board_payload(bid, _today(bid), settings)
    body.update(extra)
    return jsonify(body), status


def _guard_write(bid):
    """(settings, lỗi | None) cho thao tác trên bảng HÔM NAY."""
    settings = get_settings(bid)
    if not can_assign(settings):
        return settings, _err(403, 'Tài khoản của bạn chỉ xem được bảng tua. Chủ tiệm cho phép máy quầy thao tác trong Cài đặt tua.',
                              'Your account can view the turn board only. The owner can allow the front desk in Turn settings.')
    return settings, None


# ------------------------------------------------------------------ routes
@nail_turns_bp.route('/nail/turns')
@login_required
@nail_only
def turns_page():
    return render_template('nail_turns.html')


@nail_turns_bp.route('/api/nail_turns/board', methods=['GET'])
@login_required
@nail_only
def api_board():
    bid = _bid()
    settings = get_settings(bid)
    day = _parse_day(request.args.get('day'), _today(bid))
    if not day:
        return _err(400, f'Chỉ xem được {HISTORY_DAYS} ngày gần nhất (YYYY-MM-DD).', f'Pick a day in the last {HISTORY_DAYS} days (YYYY-MM-DD).')
    return jsonify(board_payload(bid, day, settings, lite=request.args.get('lite') == '1'))


@nail_turns_bp.route('/api/nail_turns/summary', methods=['GET'])
@login_required
@nail_only
def api_summary():
    bid = _bid()
    settings = get_settings(bid)
    day = _parse_day(request.args.get('day'), _today(bid))
    if not day:
        return _err(400, f'Chỉ xem được {HISTORY_DAYS} ngày gần nhất (YYYY-MM-DD).', f'Pick a day in the last {HISTORY_DAYS} days (YYYY-MM-DD).')
    return jsonify(summary_rows(bid, day, settings))


@nail_turns_bp.route('/api/nail_turns/action', methods=['POST'])
@login_required
@nail_only
def api_action():
    """Vào bảng (join) / bỏ lượt (skip) / nghỉ (break) / quay lại (back) / về (leave) cho 1 thợ, hôm nay."""
    bid = _bid()
    settings, err = _guard_write(bid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    action = str(data.get('action') or '').strip().lower()
    ma = str(data.get('ma_nv') or '').strip()
    if action not in ACTIONS or not ma:
        return _err(400, 'Thiếu thợ hoặc thao tác.', 'Missing technician or action.')
    day = _today(bid)
    techs, events, members, _turns, _ins = _load(bid, day, settings)
    m = members.get(ma)
    if action == 'join':
        if ma not in techs:
            return _err(404, 'Không thấy thợ này trong danh sách thợ Nails của tiệm.', 'This person is not on your nail technician list.')
        if m and m['status'] != 'left':
            return _fresh(bid, settings, message=_t('Thợ đã có trên bảng.', 'Already on the board.'))
        _insert(bid, day, 'join', ma, techs[ma]['name'], source='manual')
        return _fresh(bid, settings)
    if m is None:
        return _err(409, 'Thợ chưa có trên bảng hôm nay.', 'This technician is not on today\'s board.')
    allowed = {'skip': ('available',), 'break': ('available',), 'back': ('break',), 'leave': ('available', 'break')}[action]
    if m['status'] not in allowed:
        msgs = {'busy': ('Thợ đang làm khách — bấm "Xong" trước.', 'This technician is with a client. Tap "Done" first.'),
                'break': ('Thợ đang nghỉ.', 'This technician is on a break.'),
                'available': ('Thợ đang trong hàng chờ, không nghỉ.', 'This technician is in the line, not on a break.'),
                'left': ('Thợ đã về.', 'This technician has gone home.')}
        vi, en = msgs.get(m['status'], ('Không làm được lúc này.', 'Not possible right now.'))
        return _err(409, vi, en, board=board_payload(bid, day, settings))
    extra = {}
    if action == 'skip':
        extra['value'] = COUNT_RULES.get(settings.get('skip_counts'), 0.0)
    _insert(bid, day, action, ma, m['name'], **extra)
    return _fresh(bid, settings)


@nail_turns_bp.route('/api/nail_turns/assign', methods=['POST'])
@login_required
@nail_only
def api_assign():
    """Giao 1 khách cho thợ: walk-in (theo lượt), khách request (chỉ định thợ), lịch hẹn. Ghi 1 tua."""
    bid = _bid()
    settings, err = _guard_write(bid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    ma = str(data.get('ma_nv') or '').strip()
    kind = str(data.get('kind') or '').strip().lower()
    day = _today(bid)
    techs, events, members, turns, _ins = _load(bid, day, settings)
    amount, merr = _money(data.get('amount'))
    if merr:
        return _err(400, *merr)
    service, service_id = None, None
    if data.get('service_id') not in (None, ''):
        try:
            service_id = int(data.get('service_id'))
        except (TypeError, ValueError):
            return _err(400, 'Dịch vụ không hợp lệ.', 'That service is not valid.')
        p = db.products.find_one({'id': service_id, 'business_id': bid}, {'_id': 0, 'id': 1, 'name': 1, 'price': 1})
        if not p:
            return _err(404, 'Không thấy dịch vụ này.', 'Service not found.')
        service = str(p.get('name') or '')[:80]
        if amount is None:
            amount, _ = _money(p.get('price'))
    appt_id = None
    if data.get('appointment_id') not in (None, ''):
        try:
            appt_id = int(data.get('appointment_id'))
        except (TypeError, ValueError):
            return _err(400, 'Lịch hẹn không hợp lệ.', 'That appointment is not valid.')
        appt = db.appointments.find_one({'id': appt_id, 'business_id': bid}, {'_id': 0, 'id': 1, 'staff_id': 1, 'service_id': 1})
        if not appt:
            return _err(404, 'Không thấy lịch hẹn này.', 'Appointment not found.')
        if any(t.get('appointment_id') == appt_id for t in turns.values()):
            return _err(409, 'Lịch hẹn này đã được giao cho thợ.', 'This appointment is already on the board.')
        if not kind:
            kind = 'request' if appt.get('staff_id') and str(appt['staff_id']) == ma else 'appointment'
        if service is None and appt.get('service_id') is not None:
            p = db.products.find_one({'id': appt['service_id'], 'business_id': bid}, {'_id': 0, 'name': 1, 'price': 1}) or {}
            service = str(p.get('name') or '')[:80] or None
            if amount is None:
                amount, _ = _money(p.get('price'))
    kind = kind or 'walk_in'
    if kind not in KINDS:
        return _err(400, 'Loại khách không hợp lệ.', 'Unknown client type.')
    m = members.get(ma)
    if m is None:
        return _err(409, 'Thợ chưa có trên bảng hôm nay — thêm thợ vào bảng trước.', 'This technician is not on today\'s board. Add them first.')
    ok_status = ('available', 'break') if kind == 'request' else ('available',)
    if m['status'] not in ok_status:
        vi, en = {'busy': ('Thợ đang làm khách khác.', 'This technician is already with a client.'),
                  'break': ('Thợ đang nghỉ — chỉ khách request mới gọi thợ đang nghỉ.', 'This technician is on a break. Only a requested client can call them back.'),
                  'left': ('Thợ đã về.', 'This technician has gone home.')}.get(m['status'], ('Không giao được.', 'Cannot assign now.'))
        return _err(409, vi, en, board=board_payload(bid, day, settings))
    nxt = next_up(members)
    out_of_turn = kind != 'request' and nxt is not None and nxt != ma
    if out_of_turn and not data.get('override'):
        name = members[nxt]['name']
        return _err(409, f'Tới lượt {name}. Giao cho người khác thì ghi là "giao ngoài lượt".',
                    f'{name} is next. Giving this client to someone else is logged as out of turn.',
                    code='not_next', next_up=nxt, next_up_name=name, board=board_payload(bid, day, settings))
    value, provisional = turn_value(kind, amount, settings)
    rev = max((int(e.get('id') or 0) for e in events), default=0)
    doc = _insert(bid, day, 'turn', ma, m['name'], kind=kind, amount=amount, value=value, provisional=provisional,
                  service=service, service_id=service_id, appointment_id=appt_id, order_id=None,
                  out_of_turn=out_of_turn, next_up=nxt, next_up_name=members[nxt]['name'] if nxt else None,
                  note=str(data.get('note') or '').strip()[:120] or None, history=[])
    # 2 máy quầy giao cùng lúc cho 1 thợ: dòng id nhỏ hơn thắng, dòng sau tự huỷ và báo bảng mới
    rival = db.nail_turns.find_one({'business_id': bid, 'day': day, 'type': 'turn', 'ma_nv': ma, 'voided': False,
                                    'id': {'$gt': rev, '$lt': doc['id']}}, {'_id': 0, 'id': 1})
    if rival:
        _void(bid, doc, reason='conflict')
        return _err(409, 'Máy khác vừa giao khách cho thợ này. Bảng đã cập nhật.', 'Another device just gave this technician a client. The board is updated.',
                    board=board_payload(bid, day, settings))
    return _fresh(bid, settings, turn_id=doc['id'])


def _settle(bid, settings, turn, data):
    """Chốt giá 1 tua (gắn vé POS hoặc số tiền) -> tính lại tua đủ/nửa. Trả (cập nhật $set, lỗi | None)."""
    ma = turn.get('ma_nv')
    amount, merr = _money(data.get('amount'))
    if merr:
        return None, _err(400, *merr)
    order_id = turn.get('order_id')
    if data.get('order_id') not in (None, ''):
        amt = _ticket_amount_for(bid, data.get('order_id'), ma)
        if amt is None:
            return None, _err(404, 'Vé POS này không có dịch vụ nào của thợ.', 'That POS ticket has no service for this technician.')
        order_id = int(data.get('order_id'))
        others = db.nail_turns.find_one({'business_id': bid, 'type': 'turn', 'order_id': order_id, 'voided': False,
                                         'id': {'$ne': turn['id']}}, {'_id': 0, 'id': 1, 'name': 1})
        if others:
            return None, _err(409, f'Vé #{order_id} đã gắn vào tua của {others.get("name")}.', f'Ticket #{order_id} is already on {others.get("name")}\'s turn.')
        amount = amt
    kind = str(data.get('kind') or turn.get('kind') or 'walk_in').strip().lower()
    if kind not in KINDS:
        return None, _err(400, 'Loại khách không hợp lệ.', 'Unknown client type.')
    if amount is None:
        amount = turn.get('amount')
    value, provisional = turn_value(kind, amount, settings)
    hist = list(turn.get('history') or [])[-20:]
    hist.append({'at': _local_now(bid).strftime('%Y-%m-%dT%H:%M:%S'), 'by': str(session.get('user_email') or session.get('user_id') or ''),
                 'amount': turn.get('amount'), 'value': turn.get('value'), 'kind': turn.get('kind'), 'order_id': turn.get('order_id')})
    return {'amount': amount, 'value': value, 'provisional': provisional, 'kind': kind, 'order_id': order_id, 'history': hist}, None


@nail_turns_bp.route('/api/nail_turns/done', methods=['POST'])
@login_required
@nail_only
def api_done():
    """Thợ làm xong khách: chốt giá (vé POS / số tiền) rồi thợ về hàng chờ đúng chỗ."""
    bid = _bid()
    settings, err = _guard_write(bid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        turn_id = int(data.get('turn_id'))
    except (TypeError, ValueError):
        return _err(400, 'Thiếu tua cần chốt.', 'Missing the turn to finish.')
    day = _today(bid)
    _techs, _events, members, turns, _ins = _load(bid, day, settings)
    turn = turns.get(turn_id)
    m = members.get(turn.get('ma_nv')) if turn else None
    if not turn or not m or m['current_turn'] != turn_id:
        return _err(409, 'Tua này đã xong hoặc đã huỷ.', 'This turn is already finished or undone.', board=board_payload(bid, day, settings))
    upd, e = _settle(bid, settings, turn, data)
    if e:
        return e
    db.nail_turns.update_one({'id': turn_id, 'business_id': bid}, {'$set': upd})
    _insert(bid, day, 'done', m['ma_nv'], m['name'], turn_id=turn_id)
    return _fresh(bid, settings)


@nail_turns_bp.route('/api/nail_turns/turn/<int:turn_id>', methods=['POST'])
@login_required
@nail_only
def api_turn_edit(turn_id):
    """Sửa giá / loại khách / vé POS của 1 tua đã ghi (tính lại tua đủ/nửa). Quầy: hôm nay. Chủ tiệm: ngày cũ."""
    bid = _bid()
    settings, err = _guard_write(bid)
    if err:
        return err
    turn = db.nail_turns.find_one({'id': turn_id, 'business_id': bid, 'type': 'turn'}, {'_id': 0})
    if not turn or turn.get('voided'):
        return _err(404, 'Không thấy tua này.', 'Turn not found.')
    if turn.get('day') != _today(bid) and not _is_admin():
        return _err(403, 'Chỉ chủ tiệm sửa được tua của ngày cũ.', 'Only the owner can change a past day.')
    upd, e = _settle(bid, settings, turn, request.get_json(silent=True) or {})
    if e:
        return e
    db.nail_turns.update_one({'id': turn_id, 'business_id': bid}, {'$set': upd})
    if turn.get('day') != _today(bid):
        return jsonify({'success': True, 'turn_id': turn_id})
    return _fresh(bid, settings)


@nail_turns_bp.route('/api/nail_turns/undo', methods=['POST'])
@login_required
@nail_only
def api_undo():
    """Hoàn tác: không có event_id = dòng cuối cùng (quầy); có event_id = 1 dòng bất kỳ hôm nay (chỉ chủ tiệm).
    Không xoá — đánh dấu voided để nhật ký vẫn còn."""
    bid = _bid()
    settings, err = _guard_write(bid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    day = _today(bid)
    _techs, events, members, _turns, _ins = _load(bid, day, settings)
    last = _undoable(events)
    if data.get('event_id') not in (None, ''):
        try:
            eid = int(data.get('event_id'))
        except (TypeError, ValueError):
            return _err(400, 'Dòng không hợp lệ.', 'That entry is not valid.')
        ev = next((e for e in events if e.get('id') == eid), None)
        if not ev or ev.get('voided'):
            return _err(404, 'Không thấy dòng này (hoặc đã hoàn tác).', 'Entry not found or already undone.')
        if (not last or last.get('id') != eid) and not _is_admin():
            return _err(403, 'Quầy chỉ hoàn tác được thao tác cuối cùng. Chủ tiệm huỷ được dòng cũ hơn.',
                        'The front desk can undo only the last action. The owner can undo older entries.')
    else:
        ev = last
        if not ev:
            return _err(409, 'Không còn gì để hoàn tác hôm nay.', 'Nothing to undo today.')
    if ev.get('type') == 'join':
        if ev.get('source') == 'attendance':
            return _err(409, 'Thợ vào bảng từ chấm công — bấm "Về" để gỡ khỏi bảng.', 'Added by their clock-in. Use "Gone home" to take them off the board.')
        later = [e for e in events if not e.get('voided') and e.get('ma_nv') == ev.get('ma_nv') and _ev_key(e) > _ev_key(ev)]
        if later:
            return _err(409, 'Thợ đã có thao tác sau khi vào bảng — hoàn tác các thao tác đó trước.', 'This technician has later entries. Undo those first.')
    _void(bid, ev)
    if ev.get('type') == 'turn':                     # huỷ tua thì huỷ luôn dòng "xong" của tua đó
        for e in events:
            if e.get('type') == 'done' and e.get('turn_id') == ev.get('id') and not e.get('voided'):
                _void(bid, e)
    return _fresh(bid, settings, undone=ev.get('id'))


@nail_turns_bp.route('/api/nail_turns/settings', methods=['GET', 'POST'])
@login_required
@nail_only
def api_settings():
    bid = _bid()
    if request.method == 'GET':
        s = get_settings(bid)
        return jsonify({'success': True, 'settings': s, 'staff': _all_staff(bid), 'defaults': default_settings(s['currency'])})
    if not _is_admin():
        return _err(403, 'Chỉ chủ tiệm đổi được cài đặt tua.', 'Only the owner can change turn settings.')
    current = get_settings(bid)
    clean, e = clean_settings(request.get_json(silent=True) or {}, current)
    if e:
        return _err(400, *e)
    clean.update({'business_id': bid, 'updated_at': _server_now().isoformat(),
                  'updated_by': str(session.get('user_email') or session.get('user_id') or '')})
    db.nail_turn_settings.update_one({'business_id': bid}, {'$set': clean}, upsert=True)
    return jsonify({'success': True, 'settings': get_settings(bid)})
