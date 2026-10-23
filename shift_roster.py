"""
Xếp lịch ca làm việc theo tuần (roster). Trước đây landing HRM/Office/F&B quảng cáo "AI tự xếp ca" nhưng hệ thống
chỉ có đổi ca (cho_doi_ca) — không có lịch ca nào để đổi.

Cách hoạt động:
  - Chủ tiệm khai "nhu cầu người" theo khung giờ từng thứ (vd T7 9:00–17:00 cần 3 người, vai trò "Nail").
  - Tự xếp: lấp các khung còn thiếu người bằng nhân viên hợp lệ — không trùng giờ, không rơi vào ngày nghỉ phép ĐÃ DUYỆT,
    không vào thứ nhân viên báo bận, không vượt số giờ tối đa/tuần; ưu tiên người đang ít giờ nhất (chia đều).
    Khung nào không đủ người thì báo rõ lý do, không bịa.
  - Ca tự xếp/chép tuần trước là NHÁP. "Công bố" -> nhân viên thấy trong app + nhận SMS/email (qua messaging.py, nếu có SĐT/email).
  - Đối chiếu chấm công: ca đã công bố so với giờ check-in thật (db.chamcong.gio_den) -> đi trễ / vắng.
"""
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, session

from app import login_required, role_required
from mongo_client import db, next_mongo_id

roster_bp = Blueprint('roster', __name__)
TIME_RE = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')
LATE_GRACE_MIN = 5
DAYS_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
DAYS_VI = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']


def _bid():
    return session.get('business_id') or session.get('user_id')


def _biz(business_id):
    return db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'country': 1, 'currency': 1}) or {}


def _default_max_hours(business_id):
    # Úc: tuần làm việc tiêu chuẩn 38 giờ (Fair Work NES); Mỹ: 40 giờ (FLSA, quá 40 giờ là tăng ca)
    return 38 if (_biz(business_id).get('country') or '').upper() == 'AU' else 40


def week_start(value=None):
    try:
        d = datetime.strptime(str(value)[:10], '%Y-%m-%d').date() if value else date.today()
    except ValueError:
        d = date.today()
    return d - timedelta(days=d.weekday())


def _minutes(hhmm):
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def shift_span(start, end):
    """(phút bắt đầu, phút kết thúc) — ca qua đêm (kết thúc <= bắt đầu) cộng 24h."""
    a, b = _minutes(start), _minutes(end)
    return a, (b + 1440 if b <= a else b)


def shift_hours(start, end):
    a, b = shift_span(start, end)
    return round((b - a) / 60, 2)


def _overlap(s1, e1, s2, e2):
    a1, b1 = shift_span(s1, e1)
    a2, b2 = shift_span(s2, e2)
    return a1 < b2 and a2 < b1


def _staff(business_id):
    rows = list(db.employees.find({'business_id': business_id, 'roster_exclude': {'$ne': True}},
                                  {'_id': 0, 'ma_nv': 1, 'ho_ten': 1, 'chuc_vu': 1, 'linh_vuc': 1, 'luong_gio': 1,
                                   'phone': 1, 'email': 1, 'unavailable_days': 1, 'max_hours': 1}).sort('ma_nv', 1))
    return [r for r in rows if r.get('ma_nv')]


def _approved_leave(business_id, d0, d1):
    """{ma_nv: set('YYYY-MM-DD')} ngày nghỉ phép đã duyệt trong [d0, d1]."""
    out = {}
    q = {'business_id': business_id, 'status': 'approved', 'from_date': {'$lte': d1.isoformat()}, 'to_date': {'$gte': d0.isoformat()}}
    for lv in db.leave_requests.find(q, {'_id': 0, 'ma_nv': 1, 'from_date': 1, 'to_date': 1}):
        try:
            a = max(d0, datetime.strptime(lv['from_date'][:10], '%Y-%m-%d').date())
            b = min(d1, datetime.strptime((lv.get('to_date') or lv['from_date'])[:10], '%Y-%m-%d').date())
        except (ValueError, KeyError):
            continue
        while a <= b:
            out.setdefault(lv['ma_nv'], set()).add(a.isoformat())
            a += timedelta(days=1)
    return out


def _week_shifts(business_id, ws):
    days = [(ws + timedelta(days=i)).isoformat() for i in range(7)]
    return list(db.roster_shifts.find({'business_id': business_id, 'date': {'$in': days}}, {'_id': 0}).sort([('date', 1), ('start', 1)]))


def _needs(business_id):
    row = db.roster_needs.find_one({'business_id': business_id}, {'_id': 0}) or {}
    return row.get('needs') or [], row.get('max_hours_week') or _default_max_hours(business_id)


def _clean_need(n):
    try:
        wd = int(n.get('weekday'))
        cnt = int(n.get('count'))
    except (TypeError, ValueError):
        return None
    st, en = str(n.get('start') or ''), str(n.get('end') or '')
    if not (0 <= wd <= 6 and 1 <= cnt <= 50 and TIME_RE.match(st) and TIME_RE.match(en)) or st == en:
        return None
    return {'weekday': wd, 'start': st, 'end': en, 'count': cnt, 'role': str(n.get('role') or '').strip()[:40]}


def _role_match(emp, role):
    if not role:
        return True
    hay = f"{emp.get('chuc_vu') or ''} {emp.get('linh_vuc') or ''}".lower()
    return role.lower() in hay


def coverage(needs, shifts, ws):
    """Mỗi nhu cầu trong tuần: cần bao nhiêu, đã có bao nhiêu ca phủ trọn khung đó."""
    out = []
    for i in range(7):
        d = (ws + timedelta(days=i)).isoformat()
        for n in needs:
            if n['weekday'] != i:
                continue
            a, b = shift_span(n['start'], n['end'])
            have = sum(1 for s in shifts if s['date'] == d and shift_span(s['start'], s['end'])[0] <= a
                       and shift_span(s['start'], s['end'])[1] >= b and (not n['role'] or n['role'].lower() in (s.get('role') or '').lower()))
            out.append({**n, 'date': d, 'have': have, 'short': max(0, n['count'] - have)})
    return out


def auto_fill(business_id, ws):
    """Lấp các khung thiếu người bằng ca NHÁP. Trả (ca đã tạo, khung chưa đủ người kèm lý do)."""
    needs, default_max = _needs(business_id)
    staff = _staff(business_id)
    d0, d1 = ws, ws + timedelta(days=6)
    leave = _approved_leave(business_id, d0, d1)
    shifts = _week_shifts(business_id, ws)
    hours = {e['ma_nv']: 0.0 for e in staff}
    days_worked = {e['ma_nv']: set() for e in staff}
    for s in shifts:
        if s['ma_nv'] in hours:
            hours[s['ma_nv']] += shift_hours(s['start'], s['end'])
            days_worked[s['ma_nv']].add(s['date'])
    created, unfilled = [], []
    for need in sorted(coverage(needs, shifts, ws), key=lambda n: (n['date'], n['start'])):
        short = need['short']
        if not short:
            continue
        h = shift_hours(need['start'], need['end'])
        reasons = {'leave': 0, 'unavailable': 0, 'busy': 0, 'max_hours': 0, 'role': 0}
        pool = []
        for e in staff:
            code = e['ma_nv']
            if not _role_match(e, need['role']):
                reasons['role'] += 1
                continue
            if need['date'] in leave.get(code, ()):
                reasons['leave'] += 1
                continue
            if need['weekday'] in (e.get('unavailable_days') or []):
                reasons['unavailable'] += 1
                continue
            if any(s['ma_nv'] == code and s['date'] == need['date'] and _overlap(s['start'], s['end'], need['start'], need['end']) for s in shifts):
                reasons['busy'] += 1
                continue
            cap = float(e.get('max_hours') or default_max)
            if hours[code] + h > cap + 1e-6:
                reasons['max_hours'] += 1
                continue
            pool.append(e)
        # chia đều: ít giờ nhất trước, rồi ít ngày làm nhất
        pool.sort(key=lambda e: (hours[e['ma_nv']], len(days_worked[e['ma_nv']]), e['ma_nv']))
        for e in pool[:short]:
            doc = {'id': next_mongo_id('roster_shifts'), 'business_id': business_id, 'ma_nv': e['ma_nv'], 'ho_ten': e.get('ho_ten') or e['ma_nv'],
                   'date': need['date'], 'start': need['start'], 'end': need['end'], 'role': need['role'], 'note': '',
                   'status': 'draft', 'source': 'auto', 'created_at': datetime.now().isoformat()}
            db.roster_shifts.insert_one(doc)
            doc.pop('_id', None)
            shifts.append(doc)
            created.append(doc)
            hours[e['ma_nv']] += h
            days_worked[e['ma_nv']].add(need['date'])
        left = short - min(short, len(pool))
        if left:
            unfilled.append({'date': need['date'], 'start': need['start'], 'end': need['end'], 'role': need['role'],
                             'missing': left, 'reasons': {k: v for k, v in reasons.items() if v}})
    return created, unfilled


def attendance(business_id, ws):
    """Ca đã công bố (đến hôm nay) so với check-in thật: đúng giờ / trễ X phút / vắng."""
    today = date.today().isoformat()
    now_min = datetime.now().hour * 60 + datetime.now().minute
    rows = []
    for s in _week_shifts(business_id, ws):
        if s.get('status') != 'published' or s['date'] > today:
            continue
        ngay = datetime.strptime(s['date'], '%Y-%m-%d').strftime('%d/%m/%Y')
        recs = list(db.chamcong.find({'business_id': business_id, 'ma_nv': s['ma_nv'], 'ngay_cham': ngay,
                                      'gio_den': {'$exists': True, '$nin': [None, '']}}, {'_id': 0, 'gio_den': 1}))
        times = sorted(r['gio_den'][:5] for r in recs if TIME_RE.match(str(r['gio_den'])[:5]))
        start_m, end_m = shift_span(s['start'], s['end'])
        row = {'shift_id': s['id'], 'ma_nv': s['ma_nv'], 'ho_ten': s.get('ho_ten'), 'date': s['date'], 'start': s['start'], 'end': s['end']}
        if times:
            first = _minutes(times[0])
            late = first - start_m
            row.update({'check_in': times[0], 'late_min': late if late > LATE_GRACE_MIN else 0,
                        'status': 'late' if late > LATE_GRACE_MIN else 'on_time'})
        elif s['date'] < today or now_min > start_m + 30:
            row.update({'check_in': None, 'late_min': None, 'status': 'no_show'})
        else:
            row.update({'check_in': None, 'late_min': None, 'status': 'upcoming'})
        rows.append(row)
    summary = {}
    for r in rows:
        x = summary.setdefault(r['ma_nv'], {'ma_nv': r['ma_nv'], 'ho_ten': r['ho_ten'], 'shifts': 0, 'late': 0, 'late_min': 0, 'no_show': 0})
        x['shifts'] += 1
        if r['status'] == 'late':
            x['late'] += 1
            x['late_min'] += r['late_min']
        if r['status'] == 'no_show':
            x['no_show'] += 1
    return rows, sorted(summary.values(), key=lambda x: (-x['no_show'], -x['late_min']))


def _notify_text(lang, biz_name, name, ws, shifts):
    days = DAYS_VI if lang == 'vi' else DAYS_EN
    parts = []
    for s in shifts:
        d = datetime.strptime(s['date'], '%Y-%m-%d').date()
        parts.append(f"{days[d.weekday()]} {d.day}/{d.month} {s['start']}-{s['end']}")
    first = (name or '').split(' ')[0]
    if lang == 'vi':
        return f"{biz_name}: Lịch làm tuần {ws.day}/{ws.month} của {first}: " + '; '.join(parts) + '.'
    return f"{biz_name}: Hi {first}, your shifts for the week of {ws.day}/{ws.month}: " + '; '.join(parts) + '.'


def publish(business_id, ws, base_url=''):
    """Công bố mọi ca nháp của tuần + gửi lịch cho từng nhân viên (SMS nếu đã nối Twilio, không thì email)."""
    days = [(ws + timedelta(days=i)).isoformat() for i in range(7)]
    res = db.roster_shifts.update_many({'business_id': business_id, 'date': {'$in': days}, 'status': 'draft'},
                                       {'$set': {'status': 'published', 'published_at': datetime.now().isoformat()}})
    notified, no_contact = 0, []
    try:
        import messaging
        st = messaging.get_settings(business_id)
    except Exception:
        messaging, st = None, None
    shifts = [s for s in _week_shifts(business_id, ws) if s.get('status') == 'published']
    version = datetime.now().strftime('%Y%m%d%H%M')
    for e in _staff(business_id):
        mine = [s for s in shifts if s['ma_nv'] == e['ma_nv']]
        if not mine:
            continue
        if not messaging or not (e.get('phone') or e.get('email')):
            no_contact.append(e.get('ho_ten') or e['ma_nv'])
            continue
        body = _notify_text(st['language'], st['business_name'], e.get('ho_ten'), ws, mine)
        if e.get('phone') and st['twilio_ready']:
            ch, to = 'sms', messaging.normalize_phone(e['phone'], st['country'])
        else:
            ch, to = 'email', e.get('email')
        if not to:
            no_contact.append(e.get('ho_ten') or e['ma_nv'])
            continue
        subject = ('Lịch làm việc tuần ' if st['language'] == 'vi' else 'Your shifts — week of ') + f"{ws.day}/{ws.month}"
        if messaging.queue(business_id, ch, to, body, 'roster', subject=subject,
                           dedupe_key=f"roster:{business_id}:{e['ma_nv']}:{ws.isoformat()}:{version}"):
            notified += 1
    if notified and messaging:
        try:
            messaging.pump(business_id, base_url=base_url, produce=False)
        except Exception as ex:
            print(f"[roster] pump: {ex}")
    return {'published': res.modified_count, 'notified': notified, 'no_contact': no_contact}


# ---------------------------------------------------------------- routes
def _valid_shift(data):
    d, st, en = str(data.get('date') or ''), str(data.get('start') or ''), str(data.get('end') or '')
    try:
        datetime.strptime(d, '%Y-%m-%d')
    except ValueError:
        return 'Invalid date.'
    if not TIME_RE.match(st) or not TIME_RE.match(en) or st == en:
        return 'Start and end must be HH:MM and different.'
    if shift_hours(st, en) > 16:
        return 'A shift cannot be longer than 16 hours.'
    return None


def _conflicts(business_id, ma_nv, d, st, en, exclude_id=None):
    for s in db.roster_shifts.find({'business_id': business_id, 'ma_nv': ma_nv, 'date': d}, {'_id': 0}):
        if s['id'] != exclude_id and _overlap(s['start'], s['end'], st, en):
            return f"Overlaps another shift {s['start']}-{s['end']}."
    dd = datetime.strptime(d, '%Y-%m-%d').date()
    if d in _approved_leave(business_id, dd, dd).get(ma_nv, ()):
        return 'This person has approved leave that day.'
    return None


@roster_bp.route('/roster')
@login_required
@role_required('admin', 'super_admin')
def roster_page():
    return render_template('roster.html')


@roster_bp.route('/api/roster', methods=['GET'])
@login_required
@role_required('admin', 'super_admin')
def roster_get():
    bid = _bid()
    ws = week_start(request.args.get('week'))
    staff = _staff(bid)
    shifts = _week_shifts(bid, ws)
    needs, max_h = _needs(bid)
    leave = _approved_leave(bid, ws, ws + timedelta(days=6))
    hours = {}
    for s in shifts:
        hours[s['ma_nv']] = round(hours.get(s['ma_nv'], 0) + shift_hours(s['start'], s['end']), 2)
    cost = round(sum(hours.get(e['ma_nv'], 0) * float(e.get('luong_gio') or 0) for e in staff), 2)
    for e in staff:
        e['hours'] = hours.get(e['ma_nv'], 0)
        e['leave_dates'] = sorted(leave.get(e['ma_nv'], ()))
        e['max_hours'] = e.get('max_hours') or max_h
    biz = _biz(bid)
    return jsonify({'success': True, 'week_start': ws.isoformat(), 'days': [(ws + timedelta(days=i)).isoformat() for i in range(7)],
                    'staff': staff, 'shifts': shifts, 'needs': needs, 'max_hours_week': max_h,
                    'coverage': coverage(needs, shifts, ws), 'labor_cost': cost, 'currency': (biz.get('currency') or 'USD').upper(),
                    'drafts': sum(1 for s in shifts if s.get('status') == 'draft')})


@roster_bp.route('/api/roster/shifts', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def roster_shift_create():
    bid = _bid()
    data = request.json or {}
    err = _valid_shift(data)
    emp = db.employees.find_one({'business_id': bid, 'ma_nv': str(data.get('ma_nv') or '')}, {'_id': 0, 'ma_nv': 1, 'ho_ten': 1})
    if not emp:
        err = err or 'Employee not found.'
    if err:
        return jsonify({'success': False, 'message': err}), 400
    clash = _conflicts(bid, emp['ma_nv'], data['date'], data['start'], data['end'])
    if clash:
        return jsonify({'success': False, 'message': clash}), 409
    doc = {'id': next_mongo_id('roster_shifts'), 'business_id': bid, 'ma_nv': emp['ma_nv'], 'ho_ten': emp.get('ho_ten') or emp['ma_nv'],
           'date': data['date'], 'start': data['start'], 'end': data['end'], 'role': str(data.get('role') or '')[:40],
           'note': str(data.get('note') or '')[:200], 'status': 'draft', 'source': 'manual', 'created_at': datetime.now().isoformat()}
    db.roster_shifts.insert_one(doc)
    doc.pop('_id', None)
    return jsonify({'success': True, 'data': doc})


@roster_bp.route('/api/roster/shifts/<int:shift_id>', methods=['PATCH', 'DELETE'])
@login_required
@role_required('admin', 'super_admin')
def roster_shift_update(shift_id):
    bid = _bid()
    s = db.roster_shifts.find_one({'business_id': bid, 'id': shift_id}, {'_id': 0})
    if not s:
        return jsonify({'success': False, 'message': 'Shift not found.'}), 404
    if request.method == 'DELETE':
        db.roster_shifts.delete_one({'business_id': bid, 'id': shift_id})
        return jsonify({'success': True})
    data = {**s, **{k: v for k, v in (request.json or {}).items() if k in ('date', 'start', 'end', 'role', 'note')}}
    err = _valid_shift(data) or _conflicts(bid, s['ma_nv'], data['date'], data['start'], data['end'], exclude_id=shift_id)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    upd = {k: data[k] for k in ('date', 'start', 'end', 'role', 'note')}
    if s.get('status') == 'published':
        upd['status'] = 'draft'  # đổi ca đã công bố -> phải công bố lại để nhân viên được báo
    db.roster_shifts.update_one({'business_id': bid, 'id': shift_id}, {'$set': upd})
    return jsonify({'success': True, 'data': {**s, **upd}})


@roster_bp.route('/api/roster/needs', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def roster_needs_save():
    bid = _bid()
    data = request.json or {}
    needs = [n for n in (_clean_need(x) for x in (data.get('needs') or [])[:80]) if n]
    try:
        max_h = max(1, min(int(data.get('max_hours_week') or _default_max_hours(bid)), 80))
    except (TypeError, ValueError):
        max_h = _default_max_hours(bid)
    db.roster_needs.update_one({'business_id': bid}, {'$set': {'needs': needs, 'max_hours_week': max_h,
                                                                'updated_at': datetime.now().isoformat()}}, upsert=True)
    return jsonify({'success': True, 'needs': needs, 'max_hours_week': max_h})


@roster_bp.route('/api/roster/staff/<ma_nv>', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def roster_staff_update(ma_nv):
    """Liên hệ + giới hạn của nhân viên dùng cho xếp ca: SĐT/email nhận lịch, thứ bận, số giờ tối đa/tuần."""
    bid = _bid()
    data = request.json or {}
    upd = {}
    if 'phone' in data:
        upd['phone'] = re.sub(r'[^\d+]', '', str(data['phone'] or ''))[:20]
    if 'email' in data:
        em = str(data['email'] or '').strip()[:120]
        if em and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', em):
            return jsonify({'success': False, 'message': 'Invalid email.'}), 400
        upd['email'] = em
    if 'unavailable_days' in data:
        upd['unavailable_days'] = sorted({int(x) for x in (data['unavailable_days'] or []) if str(x).isdigit() and 0 <= int(x) <= 6})
    if 'max_hours' in data:
        try:
            upd['max_hours'] = max(0, min(int(data['max_hours'] or 0), 80)) or None
        except (TypeError, ValueError):
            pass
    if 'roster_exclude' in data:
        upd['roster_exclude'] = bool(data['roster_exclude'])
    r = db.employees.update_one({'business_id': bid, 'ma_nv': ma_nv}, {'$set': upd})
    if not r.matched_count:
        return jsonify({'success': False, 'message': 'Employee not found.'}), 404
    return jsonify({'success': True, 'data': upd})


@roster_bp.route('/api/roster/auto', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def roster_auto():
    bid = _bid()
    data = request.json or {}
    ws = week_start(data.get('week'))
    if data.get('replace_drafts'):
        days = [(ws + timedelta(days=i)).isoformat() for i in range(7)]
        db.roster_shifts.delete_many({'business_id': bid, 'date': {'$in': days}, 'status': 'draft', 'source': 'auto'})
    if not _needs(bid)[0]:
        return jsonify({'success': False, 'message': 'Add staffing needs first (how many people per time block).'}), 400
    created, unfilled = auto_fill(bid, ws)
    return jsonify({'success': True, 'created': len(created), 'unfilled': unfilled})


@roster_bp.route('/api/roster/copy', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def roster_copy_last_week():
    bid = _bid()
    ws = week_start((request.json or {}).get('week'))
    prev = _week_shifts(bid, ws - timedelta(days=7))
    copied, skipped = 0, []
    for s in prev:
        d = (datetime.strptime(s['date'], '%Y-%m-%d').date() + timedelta(days=7)).isoformat()
        clash = _conflicts(bid, s['ma_nv'], d, s['start'], s['end'])
        if clash:
            skipped.append({'ho_ten': s.get('ho_ten'), 'date': d, 'reason': clash})
            continue
        db.roster_shifts.insert_one({'id': next_mongo_id('roster_shifts'), 'business_id': bid, 'ma_nv': s['ma_nv'], 'ho_ten': s.get('ho_ten'),
                                     'date': d, 'start': s['start'], 'end': s['end'], 'role': s.get('role', ''), 'note': s.get('note', ''),
                                     'status': 'draft', 'source': 'copy', 'created_at': datetime.now().isoformat()})
        copied += 1
    return jsonify({'success': True, 'copied': copied, 'skipped': skipped})


@roster_bp.route('/api/roster/publish', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def roster_publish():
    bid = _bid()
    ws = week_start((request.json or {}).get('week'))
    return jsonify({'success': True, **publish(bid, ws, base_url=request.host_url)})


@roster_bp.route('/api/roster/attendance', methods=['GET'])
@login_required
@role_required('admin', 'super_admin')
def roster_attendance():
    rows, summary = attendance(_bid(), week_start(request.args.get('week')))
    return jsonify({'success': True, 'rows': rows, 'summary': summary})


@roster_bp.route('/api/roster/my', methods=['GET'])
@login_required
def roster_my():
    """App nhân viên: ca ĐÃ CÔNG BỐ của tôi từ hôm nay tới 14 ngày tới."""
    bid = _bid()
    ma_nv = str(request.args.get('ma_nv') or '')
    today = date.today()
    days = [(today + timedelta(days=i)).isoformat() for i in range(14)]
    rows = list(db.roster_shifts.find({'business_id': bid, 'ma_nv': ma_nv, 'status': 'published', 'date': {'$in': days}},
                                      {'_id': 0, 'date': 1, 'start': 1, 'end': 1, 'role': 1, 'note': 1}).sort([('date', 1), ('start', 1)]))
    return jsonify({'success': True, 'data': rows, 'hours': round(sum(shift_hours(r['start'], r['end']) for r in rows), 2)})
