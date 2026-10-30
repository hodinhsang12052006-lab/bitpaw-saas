"""
AI booking pack — karaoke / bida theo giờ: đặt phòng (hoặc bàn bida) THẬT vào db.karaoke_room_reservations, cùng bảng
trang công khai /karaoke/reserve/<id> ghi và chủ quán duyệt / xếp phòng trên /karaoke/reservations.

Phòng thật (db.karaoke_rooms): giá theo giờ price_per_hour, cỡ phòng nếu chủ quán ghi (trường số hoặc ngay trong tên
"Phòng Gia Đình (6-8 người)"), loại phòng karaoke / bàn bida theo tên. Chồng giờ theo đúng luật màn xếp phòng của nhân
viên (reservations_core.karaoke_overlaps = app._karaoke_reservation_overlaps). AI xếp luôn 1 phòng cụ thể để giữ chỗ
(nhân viên vẫn đổi phòng được); yêu cầu chưa xếp phòng từ form công khai được trừ hao. Giá báo = giá giờ x số giờ.
"""
from datetime import datetime, timedelta

import ai_packs
import reservations_core as rc
from mongo_client import db

INDUSTRIES = ('karaoke',)
RESOURCE = 'room_hour'
FACTS_INCLUDE_CATALOG = True   # facts() đã liệt kê phòng + giá giờ + đồ ăn uống (bỏ món "phí giờ") -> lõi không lặp bảng giá


def _fn(name, desc, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': desc,
                                             'parameters': {'type': 'object', 'properties': props, 'required': list(required)}}}


_DATE = {'type': 'string', 'description': 'Day YYYY-MM-DD in the venue local time.'}
_TIME = {'type': 'string', 'description': 'Start time HH:MM (24-hour), venue local time.'}
_HOURS = {'type': 'number', 'description': 'How many hours (e.g. 1, 1.5, 2, 3). Ask the customer; 2 is only a default.'}
_GROUP = {'type': 'integer', 'description': 'Number of people in the group.'}
_KIND = {'type': 'string', 'enum': ['karaoke', 'billiards'], 'description': 'Karaoke room or billiards / pool table.'}
_TYPE = {'type': 'string', 'description': "Optional room wish matched against room names, e.g. 'VIP', 'family'."}
_RID = {'type': 'integer', 'description': 'reservation_id from karaoke_my_reservations or from the booking just made.'}

TOOLS = [
    _fn('karaoke_check_rooms',
        'Real free rooms (or billiards tables) for a start time + number of hours + group size, with each room\'s hourly rate '
        'and the estimated room charge. Without a time it lists start times that still have a room that day. ALWAYS call '
        'it before suggesting or promising a room or time. When nothing is free it returns the nearest start times and '
        'other days.',
        {'date': _DATE, 'time': _TIME, 'hours': _HOURS, 'group_size': _GROUP, 'room_kind': _KIND, 'room_type': _TYPE},
        ['date']),
    _fn('karaoke_reserve_room',
        'Create the real room booking (a specific room is held for the time). Call it only after the customer agreed to '
        'the day, start time, hours and the room / price, AND gave their name and phone number. Availability is re-checked. '
        'Returns status "confirmed" (booked) or "pending" (the venue still has to confirm — never call it confirmed). '
        'Calling twice with the same details does not double-book.',
        {'date': _DATE, 'time': _TIME, 'hours': _HOURS, 'group_size': _GROUP,
         'room_id': {'type': 'integer', 'description': 'room_id from karaoke_check_rooms (leave out = best free room).'},
         'room_kind': _KIND, 'room_type': _TYPE,
         'customer_name': {'type': 'string', 'description': 'Name for the booking (ask the customer).'},
         'phone': {'type': 'string', 'description': "Customer's phone number (ask the customer if you don't have it)."},
         'note': {'type': 'string', 'description': 'For the staff: drink / food pre-order, birthday, decorations, other '
                                                   'wishes. Under 500 characters. Nothing in it is ordered or charged.'}},
        ['date', 'time', 'hours', 'group_size', 'customer_name']),
    _fn('karaoke_my_reservations',
        "Upcoming room bookings that belong to THIS chat (made in this chat, or under the customer's verified phone). If it "
        'returns verified=false or tell_customer, say nothing about other bookings and pass that text on.', {}),
    _fn('karaoke_cancel_reservation',
        "Cancel one of THIS chat's room bookings. Ask the customer to confirm before calling.",
        {'reservation_id': _RID}, ['reservation_id']),
    _fn('karaoke_change_reservation',
        "Move one of THIS chat's room bookings to another day / start time, length or group size; rooms are re-checked "
        '(same room kept when it is still free). Ask the customer to confirm first. Leave out what does not change.',
        {'reservation_id': _RID, 'date': _DATE, 'time': _TIME, 'hours': _HOURS, 'group_size': _GROUP}, ['reservation_id']),
]
MANAGE_TOOLS = {'karaoke_my_reservations', 'karaoke_cancel_reservation', 'karaoke_change_reservation'}

PROMPT_RULES = {
    'en': (
        "ROOM BOOKINGS BY THE HOUR (karaoke_* tools):\n"
        "- To book you need: day, start time, how many hours, how many people, karaoke room or billiards table (and any "
        "wish like VIP), the customer's name and phone number. Ask only for what is missing.\n"
        "- Call karaoke_check_rooms before suggesting any room or time; offer only rooms and times it returns.\n"
        "- Price = the room's hourly rate x hours, exactly as the tool gives it. It covers room time only: food and drinks "
        "are extra, and the bill at checkout counts the actual time used. Never invent peak rates, discounts, packages, "
        "minimum spend or deposits.\n"
        "- Room sizes: only state a size the tool returns; if size_unknown, say the staff will seat the group in a suitable "
        "room.\n"
        "- If the tool returns hold_policy, tell the customer before booking.\n"
        "- Confirm day, date, start-end time, room and estimated price in one line, then call karaoke_reserve_room when the "
        "customer says yes.\n"
        "- Status \"confirmed\" = booked. Status \"pending\" = the request is in and the venue will confirm it — never say "
        "confirmed or held for a pending booking.\n"
        "- Drink / food pre-orders, birthdays, decorations: put them in note and say the staff will see it — nothing is "
        "ordered or charged in this chat.\n"
        "- View, change or cancel only through karaoke_my_reservations / karaoke_change_reservation / "
        "karaoke_cancel_reservation; if a tool refuses, pass on its message and reveal nothing about other bookings. Ask "
        "before cancelling."),
    'vi': (
        "ĐẶT PHÒNG THEO GIỜ (công cụ karaoke_*):\n"
        "- Cần đủ: ngày, giờ bắt đầu, mấy tiếng, mấy người, phòng karaoke hay bàn bida (và mong muốn như phòng VIP), tên và "
        "số điện thoại của khách. Chỉ hỏi phần còn thiếu.\n"
        "- Luôn gọi karaoke_check_rooms trước khi gợi ý phòng hay giờ; chỉ đưa phòng và giờ công cụ trả về.\n"
        "- Giá = giá giờ của phòng x số giờ, đúng như công cụ đưa. Chỉ là tiền giờ phòng: đồ ăn uống tính riêng, tính tiền "
        "theo thời gian dùng thực tế. Không bịa giá giờ vàng, giảm giá, combo, mức chi tối thiểu hay tiền cọc.\n"
        "- Cỡ phòng: chỉ nói cỡ công cụ trả về; nếu size_unknown thì nói nhân viên sẽ xếp phòng phù hợp với nhóm.\n"
        "- Nếu công cụ có hold_policy (giữ phòng bao lâu), nói cho khách trước khi đặt.\n"
        "- Nhắc lại ngày, giờ bắt đầu-kết thúc, phòng, giá ước tính trong 1 câu, khách đồng ý thì gọi karaoke_reserve_room.\n"
        "- \"confirmed\" = đã đặt xong. \"pending\" = đã gửi yêu cầu, quán sẽ xác nhận — không nói đã xác nhận / đã giữ phòng.\n"
        "- Đặt trước đồ uống / đồ ăn, sinh nhật, trang trí: ghi vào note, nói nhân viên sẽ xem — chat không gọi món hay thu tiền.\n"
        "- Xem / đổi / huỷ chỉ qua karaoke_my_reservations / karaoke_change_reservation / karaoke_cancel_reservation; công cụ "
        "từ chối thì chuyển nguyên lời nhắn, không tiết lộ gì về đặt phòng khác. Hỏi lại khách trước khi huỷ."),
}

_FEE_CATEGORIES = {'phòng', 'phòng hát', 'rooms', 'room'}
_FEE_NAMES = {'phí giờ karaoke', 'karaoke room time'}


def _food_menu(business_id, cur, limit=30):
    """Đồ ăn uống của quán (bỏ món "phí giờ" — cùng bộ lọc _KARAOKE_FEE_NOR của menu QR phòng hát)."""
    out = []
    rows = db.products.find({'business_id': business_id, 'is_active': {'$in': [1, True]}},
                            {'_id': 0, 'name': 1, 'price': 1, 'category': 1, 'is_room_fee': 1}).limit(200)
    for p in sorted(rows, key=lambda p: (str(p.get('category') or ''), str(p.get('name') or ''))):
        if (p.get('is_room_fee') or str(p.get('category') or '').strip().lower() in _FEE_CATEGORIES
                or str(p.get('name') or '').strip().lower() in _FEE_NAMES or not p.get('name')
                or not rc._num(p.get('price'), 0.0, float) > 0):  # menu QR phòng hát (_karaoke_menu) cũng chỉ bán món có giá
            continue
        out.append(f"- {p['name']} — {rc.money(p.get('price') or 0, cur)}")
        if len(out) >= limit:
            break
    return '\n'.join(out)


def _room_line(room, cur):
    size = f"up to {room['max_guests']} people" if room['max_guests'] else 'size not listed'
    kind = 'billiards table' if room['kind'] == 'billiards' else 'karaoke room'
    return f"- {room['name']} (room_id {room['id']}, {kind}) — {rc.money(room['rate'], cur)}/hour, {size}"


def facts(business_id, lang, now_local):
    rules = rc.load_rules(business_id, 'karaoke')
    now = rc.naive_now(business_id, now_local)
    cur = rc.currency(business_id)
    rooms = rc.karaoke_rooms(business_id)
    lines = [f"ROOM BOOKINGS BY THE HOUR — current local date/time at the venue: {now:%Y-%m-%d %H:%M} ({now:%A}). Resolve "
             "'tonight', 'Saturday', 'tối nay'... from this and pass date YYYY-MM-DD + start time HH:MM in local time."]
    ht = rc.hours_text(rules)
    lines.append(f"OPENING HOURS: {ht}. A booking must end by closing time." if ht else
                 "OPENING HOURS: not published — do not state opening hours.")
    if rooms:
        lines.append("ROOMS (hourly rate = room time only; food and drinks are extra; the bill at checkout counts the actual "
                     "time used, rounded up to 15 minutes):\n" + '\n'.join(_room_line(r, cur) for r in rooms[:40]))
    else:
        lines.append("ROOMS: the venue has not listed its rooms yet — you cannot book a room; offer to pass the request to "
                     "the team.")
    lines.append(f"DURATION: {rules['min_hours']:g}-{rules['max_hours']:g} hours per booking; groups up to "
                 f"{rules['max_party']} people online.")
    status, _why = rc.karaoke_status_for(rules)
    lines.append("CONFIRMATION: bookings that pass the checks are CONFIRMED instantly (status confirmed)." if status == 'confirmed'
                 else "CONFIRMATION: bookings are REQUESTS the venue approves (status pending) — say the request is in and "
                      "the venue will confirm; never say confirmed.")
    if rules['hold_minutes']:
        lines.append(f"HOLD POLICY: a booked room is held {rules['hold_minutes']} minutes after the start time, then released.")
    lines.append("PAYMENT: no deposit or payment is taken in this chat (mention a deposit only if the business info says so).")
    lines.append(rc.business_info_line(business_id, rules))
    menu = _food_menu(business_id, cur)
    if menu:
        lines.append("FOOD & DRINKS (information only — pre-orders go in the booking note; nothing is ordered or charged in "
                     "chat):\n" + menu)
    return '\n'.join(lines)


# ---------------------------------------------------------------- công cụ
def _vi(ctx):
    return (ctx or {}).get('lang') == 'vi'


def _when(day, minute):
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute)


def _stamp(dt):
    return dt.strftime('%Y-%m-%d %H:%M') if dt else None


def _hours(value, rules, required=False):
    if value in (None, ''):
        if required:
            raise rc.ReservationError('bad_duration', {'allowed': f"{rules['min_hours']:g}-{rules['max_hours']:g} hours"})
        return rc.KARAOKE_DEFAULT_HOURS, True
    try:
        h = round(float(value) * 4) / 4  # bước 15 phút, như tính tiền lúc trả phòng
    except (TypeError, ValueError):
        h = -1
    if not rules['min_hours'] <= h <= rules['max_hours']:
        raise rc.ReservationError('bad_duration', {'allowed': f"{rules['min_hours']:g}-{rules['max_hours']:g} hours"})
    return h, False


def _kind(args, rooms):
    k = str(args.get('room_kind') or '').strip().lower()
    if k in ('karaoke', 'billiards'):
        return k
    if rc.room_kind({'name': args.get('room_type') or ''}) == 'billiards':
        return 'billiards'
    kinds = {r['kind'] for r in rooms}
    return 'karaoke' if 'karaoke' in kinds or not kinds else 'billiards'


def _room_out(room, hours, cur):
    return {'room_id': room['id'], 'name': room['name'], 'kind': room['kind'], 'max_guests': room['max_guests'],
            'size_unknown': room['max_guests'] is None, 'hourly_rate': rc.money(room['rate'], cur),
            'estimated_room_charge': rc.money(round(room['rate'] * hours, 2), cur)}


def _cannot_manage(ctx):
    phone = rc.shop_phone(ctx.get('business_id'))
    if _vi(ctx):
        return ("Vì bảo mật, em chỉ xem và đổi được đặt phòng đã đặt trong khung chat này. "
                + (f"Mình gọi quán số {phone} " if phone else "Mình gọi điện cho quán ") + "để kiểm tra đặt phòng khác nhé.")
    return ("For your security I can only see and change bookings made in this chat. "
            + (f"Please call the venue on {phone} " if phone else "Please call the venue ") + "about any other booking.")


def _not_yours(ctx):
    return "No booking with that id belongs to this chat — do not reveal or change anything. Tell the customer: " + _cannot_manage(ctx)


def _staff_note(ctx, vi_text, en_text):
    vi_shop = rc.currency(ctx['business_id']) == 'VND'
    rc.note_for_staff(ctx['business_id'], rc.staff_thread(ctx), vi_text if vi_shop else en_text)


def _say(status):
    if status == 'confirmed':
        return 'Booked and confirmed.'
    return 'Request received — the venue confirms it. Do NOT say confirmed, booked or held.'


def _hold(rules):
    if rules['hold_minutes']:
        return f"The room is held {rules['hold_minutes']} minutes after the start time, then released."
    return None


def _free_starts(bid, rules, rooms, day, hours, group, now, kind, room_type, around=None, exclude_id=None, rows=None):
    rows = rc.karaoke_rows(bid, day, exclude_id) if rows is None else rows
    out = []
    for m in rc.karaoke_candidate_starts(rules, day, hours, around):
        start = _when(day, m)
        try:
            rc.check_window(rules, start, now, int(hours * 60))
        except rc.ReservationError:
            continue
        fits, unknown = rc.karaoke_free(rules, rooms, rows, start, hours, now, group, kind, room_type)
        if fits or unknown:
            out.append(rc.fmt_min(m))
    return out


def _alternatives(bid, rules, rooms, day, hours, group, now, kind, room_type, want, exclude_id=None):
    starts = _free_starts(bid, rules, rooms, day, hours, group, now, kind, room_type, around=want, exclude_id=exclude_id)
    out = {'other_start_times_same_day': rc.nearest_times(starts, want) if want is not None else rc.spread(starts, 6)}
    if not starts:
        days = []
        for k in range(1, 15):
            d = day + timedelta(days=k)
            s = _free_starts(bid, rules, rooms, d, hours, group, now, kind, room_type, around=want if rules['hours'] is None else None)
            if s:
                days.append({'date': d.isoformat(), 'weekday': d.strftime('%A'),
                             'start_times': rc.nearest_times(s, want, 4) if want is not None else s[:4]})
            if len(days) >= 3:
                break
        out['next_available'] = days
    return out


def _setup(ctx):
    bid = ctx['business_id']
    rules = rc.load_rules(bid, 'karaoke')
    rooms = rc.karaoke_rooms(bid)
    if not rooms:
        raise rc.ReservationError('no_rooms_listed')
    return bid, rules, rooms, rc.naive_now(bid, ctx.get('now_local')), rc.currency(bid)


def _check(args, ctx):
    bid, rules, rooms, now, cur = _setup(ctx)
    day = rc.parse_day(args.get('date'))
    hours, assumed = _hours(args.get('hours'), rules)
    group = rc.parse_party(args['group_size'], rules['max_party']) if args.get('group_size') not in (None, '') else None
    kind, room_type = _kind(args, rooms), args.get('room_type')
    want = rc.parse_hm(args['time']) if str(args.get('time') or '').strip() else None
    hrs = rc.hours_on(rules, day)
    out = {'success': True, 'date': day.isoformat(), 'weekday': day.strftime('%A'), 'hours': hours, 'group_size': group,
           'room_kind': kind, 'opening_hours': ('not published' if hrs == rc.UNKNOWN else 'closed' if hrs is None
                                                else f"{rc.fmt_min(hrs[0])}-{rc.fmt_min(hrs[1])}")}
    if assumed:
        out['hours_assumed'] = 'The customer has not said how long — 2 hours was assumed; ask them.'
    if group is None:
        out['group_size_missing'] = 'Ask how many people — room sizes depend on it.'
    rows = rc.karaoke_rows(bid, day)
    if want is not None:
        start = _when(day, want)
        out.update(start=rc.fmt_min(want), end=_stamp(start + timedelta(hours=hours))[11:])
        try:
            rc.check_window(rules, start, now, int(hours * 60))
            fits, unknown = rc.karaoke_free(rules, rooms, rows, start, hours, now, group, kind, room_type)
            out['rooms'] = [_room_out(r, hours, cur) for r in (fits + unknown)[:6]]
            out['requested_time'] = {'free': bool(out['rooms'])}
            if not out['rooms']:
                out['requested_time']['why'] = rc.REASONS['no_room'][0]
            elif not fits and group:
                out['size_note'] = 'No free room lists its size — the staff seat the group in a suitable room.'
        except rc.ReservationError as e:
            out['requested_time'] = {'free': False, 'why': rc.explain(e)}
        if not out['requested_time']['free']:
            out.update(_alternatives(bid, rules, rooms, day, hours, group, now, kind, room_type, want))
    else:
        starts = _free_starts(bid, rules, rooms, day, hours, group, now, kind, room_type, rows=rows)
        out['free_start_times'] = rc.spread(starts)
        if not starts:
            out.update(_alternatives(bid, rules, rooms, day, hours, group, now, kind, room_type, None)
                       if rules['hours'] else {})
            if rules['hours'] is None:
                out['note'] = 'Opening hours are not published — ask the customer for a start time and check that time.'
    status, why = rc.karaoke_status_for(rules)
    out['if_booked_status'] = status
    if why:
        out['pending_reason'] = why
    if _hold(rules):
        out['hold_policy'] = _hold(rules)
    out['price_note'] = 'Room time only; food and drinks extra; checkout bills the actual time used.'
    return out


def _dup_result(dup, ctx, name, note, cur):
    if not rc.is_owned(dup, ctx):
        return {'success': True, 'already_reserved': True,
                'note': "This phone number already has a booking at exactly this time. Do not create another one. It can't "
                        'be viewed or changed from this chat — the customer can call the venue.'}
    upd = {}
    if name and name != dup.get('customer_name'):
        upd['customer_name'] = name
    if note and not dup.get('note'):
        upd['note'] = str(note).strip()[:500]
    if upd:
        db.karaoke_room_reservations.update_one({'id': dup['id'], 'business_id': dup['business_id']}, {'$set': upd})
    start = rc.parse_dt(dup.get('reserved_time'))
    return {'success': True, 'already_reserved': True, 'reservation_id': dup['id'], 'status': dup.get('status'),
            'start': _stamp(start), 'hours': dup.get('duration_hours'),
            'note': 'Same booking as before — nothing new was created. To change it use karaoke_change_reservation.'}


def _pick(fits, unknown, room_id):
    cands = fits + unknown
    if room_id in (None, ''):
        return cands[0] if cands else None
    try:
        rid = int(room_id)
    except (TypeError, ValueError):
        return None
    return next((r for r in cands if r['id'] == rid), None)


def _same_booking(row, rooms, kind, chosen):
    """Đặt phòng cũ cùng SĐT + cùng giờ có phải CHÍNH yêu cầu này (AI gọi lặp) không: khách chọn phòng và đặt cũ đã có phòng
    -> cùng phòng; còn lại -> cùng loại (karaoke / bida; đặt cũ chưa xếp phòng theo rc.unassigned_kind)."""
    if chosen is not None and row.get('room_id') is not None:
        return str(row['room_id']) == str(chosen['id'])
    room = next((r for r in rooms if str(r['id']) == str(row.get('room_id'))), None)
    return (room['kind'] if room else rc.unassigned_kind(row, rooms)) == kind


def _reserve(args, ctx):
    bid, rules, rooms, now, cur = _setup(ctx)
    name, phone = rc.booking_contact(args, ctx)
    day = rc.parse_day(args.get('date'))
    if not str(args.get('time') or '').strip():
        raise rc.ReservationError('bad_time')
    want = rc.parse_hm(args['time'])
    start = _when(day, want)
    hours, _a = _hours(args.get('hours'), rules, required=True)
    group = rc.parse_party(args.get('group_size'), rules['max_party'])
    kind, room_type = _kind(args, rooms), args.get('room_type')
    chosen = None
    if args.get('room_id') not in (None, ''):  # phòng khách chọn: đúng loại của chính phòng đó, không lọc theo từ khoá
        chosen = next((r for r in rooms if str(r['id']) == str(args['room_id']).strip()), None)
        if chosen is None:
            raise ai_packs.PackError('That room_id is not one of this venue\'s rooms — use a room_id from karaoke_check_rooms.')
        if chosen['max_guests'] is not None and chosen['max_guests'] < group:
            raise ai_packs.PackError(f"{chosen['name']} fits up to {chosen['max_guests']} people — offer a bigger room.")
        kind, room_type = chosen['kind'], None
    try:
        rc.check_window(rules, start, now, int(hours * 60))
    except rc.ReservationError as e:
        return {'success': False, 'reason': e.reason, 'message': rc.explain(e),
                **_alternatives(bid, rules, rooms, day, hours, group, now, kind, room_type, want)}
    country = rc.ctx_country(ctx)
    stamp = rc.iso_slot(start)
    with rc.reservation_lock(bid, 'karaoke'):
        rows = rc.karaoke_rows(bid, day)
        dup = rc.find_duplicate(db.karaoke_room_reservations, bid, phone, start, rc.KARAOKE_ACTIVE, country)  # trong khoá
        if dup and not _same_booking(dup, rooms, kind, chosen):
            # 1 SĐT giữ được nhiều phòng cùng giờ (nhóm đông chia phòng, phòng karaoke + bàn bida): chỉ là gọi lặp khi trùng
            # đúng phòng / loại — tìm trong các đặt phòng khác của SĐT này cùng giờ.
            dup = next(({k: v for k, v in r.items() if k != '_start'} for r in rows
                        if r['_start'].replace(second=0) == start and rc.same_phone(r.get('customer_phone'), phone, country)
                        and _same_booking(r, rooms, kind, chosen)), None)
        if dup:
            return _dup_result(dup, ctx, name, args.get('note'), cur)
        fits, unknown = rc.karaoke_free(rules, rooms, rows, start, hours, now, group, kind, room_type)
        room = _pick(fits, unknown, args.get('room_id'))
        if room is not None and rc.karaoke_overlaps(bid, room['id'], stamp, hours):  # đúng luật màn xếp phòng, lần cuối
            room = None
        if room is not None:
            status, pending_reason = rc.karaoke_status_for(rules)
            estimate = round(room['rate'] * hours, 2)
            doc = rc.create_karaoke_reservation(bid, name, phone, group, stamp, hours, args.get('note'), status=status,
                                                source='ai_bot', room_id=room['id'],
                                                extra=dict(rc.ai_tags(ctx), estimated_room_charge=estimate,
                                                           hourly_rate=room['rate']))
    if room is None:
        why = 'room_taken' if args.get('room_id') not in (None, '') and (fits or unknown) else 'no_room'
        out = {'success': False, 'reason': why, 'message': rc.REASONS[why][0]}
        if why == 'room_taken':
            out['other_free_rooms'] = [_room_out(r, hours, cur) for r in (fits + unknown)[:4]]
        else:
            out.update(_alternatives(bid, rules, rooms, day, hours, group, now, kind, room_type, want))
        return out
    end = start + timedelta(hours=hours)
    _staff_note(ctx, f"🎤 AI đặt phòng #{doc['id']}: {room['name']}, {start:%d/%m %H:%M}-{end:%H:%M} ({hours:g}h), {group} người, "
                     f"{name} ({phone}) — " + ('đã xác nhận' if status == 'confirmed' else 'CHỜ quán duyệt trên Đặt phòng'),
                f"🎤 AI room booking #{doc['id']}: {room['name']}, {start:%a %d %b %H:%M}-{end:%H:%M} ({hours:g}h), {group} people, "
                f"{name} ({phone}) — " + ('confirmed' if status == 'confirmed' else 'PENDING your approval on Reservations'))
    out = {'success': True, 'reservation_id': doc['id'], 'status': status, 'room': room['name'], 'room_id': room['id'],
           'start': _stamp(start), 'end': _stamp(end), 'weekday': start.strftime('%A'), 'hours': hours, 'group_size': group,
           'hourly_rate': rc.money(room['rate'], cur), 'estimated_room_charge': rc.money(estimate, cur),
           'price_note': 'Room time only; food and drinks extra; checkout bills the actual time used.', 'say': _say(status)}
    if pending_reason:
        out['pending_reason'] = pending_reason
    if room['max_guests'] is None:
        out['size_unknown'] = True
    if _hold(rules):
        out['hold_policy'] = _hold(rules)
    return out


def _rid(args):
    try:
        return int(str(args.get('reservation_id')).strip())
    except (TypeError, ValueError):
        raise ai_packs.PackError('reservation_id must be a number from karaoke_my_reservations.')


def _own_row(ctx, rid):
    doc = db.karaoke_room_reservations.find_one({'id': rid, 'business_id': ctx['business_id']}, {'_id': 0})
    if not doc or not rc.is_owned(doc, ctx):
        raise ai_packs.PackError(_not_yours(ctx))
    return doc


def _mine(args, ctx):
    bid = ctx['business_id']
    if not rc.can_prove_owner(ctx):
        return {'success': True, 'verified': False, 'reservations': [], 'tell_customer': _cannot_manage(ctx)}
    now = rc.naive_now(bid, ctx.get('now_local'))
    cur = rc.currency(bid)
    rooms = {r['id']: r for r in rc.karaoke_rooms(bid)}
    out = []
    for r in rc.owned_upcoming(db.karaoke_room_reservations, bid, ctx, rc.KARAOKE_ACTIVE, now, back_hours=12):
        start = rc.parse_dt(r.get('reserved_time'))
        hours = float(r.get('duration_hours') or rc.KARAOKE_DEFAULT_HOURS)
        if start and start + timedelta(hours=hours) < now:
            continue
        room = rooms.get(r.get('room_id'))
        row = {'reservation_id': r['id'], 'start': _stamp(start), 'end': _stamp(start + timedelta(hours=hours)) if start else None,
               'weekday': start.strftime('%A') if start else None, 'hours': hours, 'group_size': r.get('party_size'),
               'status': r.get('status'), 'room': room['name'] if room else None, 'note': r.get('note')}
        if room:
            row['estimated_room_charge'] = rc.money(round(room['rate'] * hours, 2), cur)
        out.append(row)
    res = {'success': True, 'verified': True, 'reservations': out}
    if not ctx.get('phone'):
        res['scope'] = 'Only bookings made in this chat are listed.'
        if not out:
            res['tell_customer'] = _cannot_manage(ctx)
    return res


def _cancel(args, ctx):
    bid = ctx['business_id']
    rid = _rid(args)
    doc = _own_row(ctx, rid)
    start = rc.parse_dt(doc.get('reserved_time'))
    if doc.get('status') == 'cancelled':
        return {'success': True, 'already_cancelled': True, 'reservation_id': rid, 'start': _stamp(start)}
    if doc.get('status') not in rc.CHANGEABLE:
        raise ai_packs.PackError(f"This booking is '{doc.get('status')}' and can't be cancelled in chat — offer to pass it to "
                                 'the team.')
    now = rc.naive_now(bid, ctx.get('now_local'))
    if start and start < now:
        raise ai_packs.PackError('This booking has already started or passed — it cannot be cancelled in chat.')
    res = db.karaoke_room_reservations.update_one(
        {'id': rid, 'business_id': bid, 'status': {'$in': list(rc.CHANGEABLE)}},
        {'$set': {'status': 'cancelled', 'cancelled_by': 'customer_ai_chat', 'cancelled_at': datetime.now().isoformat()}})
    if not res.matched_count:
        raise ai_packs.PackError('This booking was changed by the venue just now — call karaoke_my_reservations again.')
    _staff_note(ctx, f"Khách tự huỷ đặt phòng #{rid} ({_stamp(start)}) qua chat AI.",
                f"Guest cancelled room booking #{rid} ({_stamp(start)}) in the AI chat.")
    return {'success': True, 'cancelled': True, 'reservation_id': rid, 'start': _stamp(start)}


def _change(args, ctx):
    bid, rules, rooms, now, cur = _setup(ctx)
    rid = _rid(args)
    doc = _own_row(ctx, rid)
    if doc.get('status') not in rc.CHANGEABLE:
        raise ai_packs.PackError(f"This booking is '{doc.get('status')}' and can't be changed in chat — offer to pass it to "
                                 'the team.')
    old = rc.parse_dt(doc.get('reserved_time'))
    if old is None or old < now:
        raise ai_packs.PackError('This booking has already started or passed — it cannot be changed in chat.')
    old_hours = float(doc.get('duration_hours') or rc.KARAOKE_DEFAULT_HOURS)
    day = rc.parse_day(args['date']) if str(args.get('date') or '').strip() else old.date()
    want = rc.parse_hm(args['time']) if str(args.get('time') or '').strip() else old.hour * 60 + old.minute
    hours = _hours(args['hours'], rules)[0] if args.get('hours') not in (None, '') else old_hours
    group = (rc.parse_party(args['group_size'], rules['max_party']) if args.get('group_size') not in (None, '')
             else max(1, int(doc.get('party_size') or 1)))
    start = _when(day, want)
    if start == old and hours == old_hours and group == doc.get('party_size'):
        return {'success': True, 'unchanged': True, 'reservation_id': rid, 'start': _stamp(old), 'status': doc.get('status')}
    current = next((r for r in rooms if r['id'] == doc.get('room_id')), None)
    kind = current['kind'] if current else _kind(args, rooms)
    try:
        rc.check_window(rules, start, now, int(hours * 60))
    except rc.ReservationError as e:
        return {'success': False, 'reason': e.reason, 'message': rc.explain(e), 'reservation_unchanged': True,
                **_alternatives(bid, rules, rooms, day, hours, group, now, kind, None, want, exclude_id=rid)}
    stamp = rc.iso_slot(start)
    with rc.reservation_lock(bid, 'karaoke'):
        fits, unknown = rc.karaoke_free(rules, rooms, rc.karaoke_rows(bid, day, exclude_id=rid), start, hours, now, group, kind)
        keep = current and next((r for r in fits + unknown if r['id'] == current['id']), None)
        room = keep or _pick(fits, unknown, None)
        if room is not None and rc.karaoke_overlaps(bid, room['id'], stamp, hours, exclude_id=rid):
            room = None
        if room is not None:
            status, pending_reason = rc.karaoke_status_for(rules)
            estimate = round(room['rate'] * hours, 2)
            res = db.karaoke_room_reservations.update_one(
                {'id': rid, 'business_id': bid, 'status': {'$in': list(rc.CHANGEABLE)}},
                {'$set': {'reserved_time': stamp, 'duration_hours': hours, 'party_size': group, 'room_id': room['id'],
                          'status': status, 'estimated_room_charge': estimate, 'hourly_rate': room['rate'],
                          'rescheduled_from': doc.get('reserved_time'), 'changed_at': datetime.now().isoformat(),
                          'changed_by': 'customer_ai_chat'}})
    if room is None:
        return {'success': False, 'reason': 'no_room', 'message': rc.REASONS['no_room'][0], 'reservation_unchanged': True,
                **_alternatives(bid, rules, rooms, day, hours, group, now, kind, None, want, exclude_id=rid)}
    if not res.matched_count:
        raise ai_packs.PackError('This booking was changed by the venue just now — call karaoke_my_reservations again.')
    end = start + timedelta(hours=hours)
    _staff_note(ctx, f"Khách đổi đặt phòng #{rid}: {_stamp(old)} ({old_hours:g}h) -> {_stamp(start)} ({hours:g}h), {room['name']}"
                     + (' — CHỜ duyệt lại' if status == 'pending' else ''),
                f"Guest changed room booking #{rid}: {_stamp(old)} ({old_hours:g}h) -> {_stamp(start)} ({hours:g}h), {room['name']}"
                + (' — PENDING approval' if status == 'pending' else ''))
    out = {'success': True, 'reservation_id': rid, 'old_start': _stamp(old), 'start': _stamp(start), 'end': _stamp(end),
           'weekday': start.strftime('%A'), 'hours': hours, 'group_size': group, 'room': room['name'],
           'room_changed': bool(current) and room['id'] != current['id'], 'status': status,
           'previous_status': doc.get('status'), 'estimated_room_charge': rc.money(estimate, cur), 'say': _say(status)}
    if pending_reason:
        out['pending_reason'] = pending_reason
    if status == 'pending' and doc.get('status') == 'confirmed':
        out['note'] = 'The change needs the venue to confirm it again — say so.'
    return out


_HANDLERS = {'karaoke_check_rooms': _check, 'karaoke_reserve_room': _reserve, 'karaoke_my_reservations': _mine,
             'karaoke_cancel_reservation': _cancel, 'karaoke_change_reservation': _change}


def execute(name, args, ctx):
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ai_packs.PackError(f"Unknown room tool '{name}'.")
    if not (ctx or {}).get('business_id'):
        raise ai_packs.PackError('No business in this chat.')
    try:
        return handler(args if isinstance(args, dict) else {}, ctx)
    except rc.ReservationError as e:
        raise ai_packs.PackError(rc.explain(e))
