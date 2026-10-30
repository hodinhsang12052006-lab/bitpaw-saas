"""
AI booking pack — nhà hàng / quán ăn (F&B): đặt bàn THẬT vào db.table_reservations, cùng bảng mà trang công khai
/reserve/<id> ghi và chủ quán duyệt / xếp bàn trên /reservations.

Sức chứa đúng như quán đã nhập (reservations_core): số khách tối đa mỗi khung 15/30 phút và/hoặc số ghế từng bàn.
Quán chưa nhập sức chứa -> không có "còn bàn" để nói: AI chỉ ghi YÊU CẦU (status 'pending'), quán xác nhận.
Tự xác nhận ('confirmed') chỉ khi: quán bật tự xác nhận + đã công bố giờ mở cửa + đã nhập sức chứa + nhóm không quá ngưỡng.
Xem / đổi / huỷ chỉ với đặt bàn chứng minh được là của cuộc chat này (reservations_core.is_owned).
"""
from datetime import datetime, timedelta

import ai_packs
import reservations_core as rc
from mongo_client import db

INDUSTRIES = ('fnb',)
RESOURCE = 'table'
FACTS_INCLUDE_CATALOG = True   # facts() đã liệt kê thực đơn + giá (kèm dị ứng nếu quán ghi) -> lõi không lặp bảng giá chung


def _fn(name, desc, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': desc,
                                             'parameters': {'type': 'object', 'properties': props, 'required': list(required)}}}


_DATE = {'type': 'string', 'description': 'Day YYYY-MM-DD in the restaurant local time.'}
_TIME = {'type': 'string', 'description': 'Time HH:MM (24-hour), restaurant local time.'}
_PARTY = {'type': 'integer', 'description': 'Number of guests, children included.'}
_RID = {'type': 'integer', 'description': 'reservation_id from fnb_my_reservations or from the reservation just made.'}

TOOLS = [
    _fn('fnb_check_tables',
        'Real table availability for one day (and the exact time if the customer named one) for a party size. ALWAYS call it '
        'before suggesting or promising a time. Returns requested_time.free, nearby free times and other days when full. '
        'availability="request_only" means the restaurant has no live table availability: a reservation is only a request it '
        'confirms — never say a table is free.',
        {'date': _DATE, 'time': _TIME, 'party_size': _PARTY}, ['date', 'party_size']),
    _fn('fnb_reserve_table',
        'Create the real table reservation. Call it only after the customer agreed to the exact day, time and party size AND '
        'gave their name and phone number. Availability is re-checked. Returns status "confirmed" (booked) or "pending" (the '
        'restaurant still has to confirm — never call it confirmed). Calling twice with the same details does not double-book.',
        {'date': _DATE, 'time': _TIME, 'party_size': _PARTY,
         'customer_name': {'type': 'string', 'description': "Name for the reservation (ask the customer)."},
         'phone': {'type': 'string', 'description': "Customer's phone number (ask the customer if you don't have it)."},
         'note': {'type': 'string', 'description': 'Requests for the staff: high chair, birthday, wheelchair access, '
                                                   'allergies, seating preference. Under 500 characters.'}},
        ['date', 'time', 'party_size', 'customer_name']),
    _fn('fnb_my_reservations',
        "Upcoming table reservations that belong to THIS chat (made in this chat, or under the customer's verified phone). "
        'If it returns verified=false or tell_customer, say nothing about other reservations and pass that text on.', {}),
    _fn('fnb_cancel_reservation',
        "Cancel one of THIS chat's table reservations. Ask the customer to confirm before calling.",
        {'reservation_id': _RID}, ['reservation_id']),
    _fn('fnb_change_reservation',
        "Move one of THIS chat's reservations to another day/time and/or party size; availability is re-checked. "
        'Ask the customer to confirm the new details first. Leave out what does not change.',
        {'reservation_id': _RID, 'date': _DATE, 'time': _TIME, 'party_size': _PARTY}, ['reservation_id']),
]
MANAGE_TOOLS = {'fnb_my_reservations', 'fnb_cancel_reservation', 'fnb_change_reservation'}

PROMPT_RULES = {
    'en': (
        "TABLE RESERVATIONS (fnb_* tools):\n"
        "- To book you need: day, time, number of guests, the customer's name and phone number. Ask only for what is missing.\n"
        "- Call fnb_check_tables before suggesting or promising any time; offer the times it returns. Never invent availability, "
        "wait times, set menus, minimum spend or deposits.\n"
        "- Confirm day, date, time and party size in one line, then call fnb_reserve_table once the customer says yes.\n"
        "- Status \"confirmed\" = booked. Status \"pending\" = the request is in and the restaurant will confirm it — never say "
        "confirmed, reserved or held for a pending request. If availability is \"request_only\", say the restaurant confirms "
        "every request.\n"
        "- High chair, birthday, wheelchair access, seating wishes, allergies: put them in note and say the team will see the "
        "note — never promise them.\n"
        "- Allergies and ingredients: answer only from the menu facts; always add that guests with severe allergies must tell "
        "staff when they arrive. Never say a dish is safe or allergen-free.\n"
        "- No payment or deposit is taken in this chat.\n"
        "- View, change or cancel only through fnb_my_reservations / fnb_change_reservation / fnb_cancel_reservation; if a tool "
        "refuses, pass on its message (call the restaurant) and reveal nothing about other reservations. Ask before cancelling."),
    'vi': (
        "ĐẶT BÀN (công cụ fnb_*):\n"
        "- Cần đủ: ngày, giờ, số khách, tên và số điện thoại của khách. Chỉ hỏi phần còn thiếu.\n"
        "- Luôn gọi fnb_check_tables trước khi gợi ý hay hứa giờ nào; chỉ đưa các giờ công cụ trả về. Không bịa còn bàn, thời "
        "gian chờ, set menu, mức chi tối thiểu hay tiền cọc.\n"
        "- Nhắc lại ngày, giờ, số khách trong 1 câu, khách đồng ý thì gọi fnb_reserve_table.\n"
        "- Trạng thái \"confirmed\" = đã đặt xong. \"pending\" = đã gửi yêu cầu, quán sẽ xác nhận — tuyệt đối không nói đã xác "
        "nhận / đã giữ bàn. Nếu availability là \"request_only\": nói quán sẽ xác nhận từng yêu cầu.\n"
        "- Ghế em bé, sinh nhật, xe lăn, chỗ ngồi, dị ứng: ghi vào note và nói nhân viên sẽ xem — không hứa chắc.\n"
        "- Dị ứng / thành phần: chỉ trả lời theo thực đơn có trong dữ liệu; luôn dặn khách dị ứng nặng báo nhân viên khi tới. "
        "Không bao giờ nói món nào chắc chắn an toàn.\n"
        "- Không nhận thanh toán hay tiền cọc trong chat.\n"
        "- Xem / đổi / huỷ chỉ qua fnb_my_reservations / fnb_change_reservation / fnb_cancel_reservation; công cụ từ chối thì "
        "chuyển nguyên lời nhắn (gọi quán), không tiết lộ gì về đặt bàn khác. Hỏi lại khách trước khi huỷ."),
}


# ---------------------------------------------------------------- facts cho prompt
def _menu(business_id, cur, limit=60):
    rows = list(db.products.find({'business_id': business_id, 'is_active': {'$in': [1, True]}},
                                 {'_id': 0, 'name': 1, 'price': 1, 'category': 1, 'allergens': 1}).limit(200))
    rows.sort(key=lambda p: (str(p.get('category') or ''), str(p.get('name') or '')))
    out = []
    for p in rows[:limit]:
        if not p.get('name'):
            continue
        line = f"- {p['name']} — {rc.money(p.get('price') or 0, cur)}"
        al = p.get('allergens')
        if isinstance(al, (list, tuple)):
            al = ', '.join(str(a) for a in al if a)
        if al:
            line += f" (allergens listed by the restaurant: {al})"
        out.append(line)
    return '\n'.join(out)


def facts(business_id, lang, now_local):
    rules = rc.load_rules(business_id, 'table')
    now = rc.naive_now(business_id, now_local)
    cur = rc.currency(business_id)
    model = rc.table_model(rules, rc.tables_with_seats(business_id))
    lines = [f"TABLE RESERVATIONS — current local date/time at the restaurant: {now:%Y-%m-%d %H:%M} ({now:%A}). Resolve "
             "'tonight', 'Friday', 'tối mai'... from this and pass date YYYY-MM-DD + time HH:MM in local time."]
    ht = rc.hours_text(rules)
    lines.append(f"OPENING HOURS: {ht}. The last reservation starts {rules['last_booking_before_close']} min before closing."
                 if ht else "OPENING HOURS: not published — do not state opening hours.")
    if model == 'none':
        lines.append("TABLE AVAILABILITY: the restaurant has not set its table capacity, so there is no live availability. "
                     "A reservation made here is a REQUEST (status pending) that the restaurant confirms.")
    else:
        lines.append("TABLE AVAILABILITY: live — fnb_check_tables checks the restaurant's real capacity "
                     + ("(guests per time slot and tables by seats)." if model == 'tables+covers' else
                        "(tables by number of seats)." if model == 'tables' else
                        f"(up to {rules['max_covers_per_slot']} guests arriving per {rules['slot_minutes']}-minute slot)."))
    big = (f"; groups over {rules['max_party_auto']} are requests the team confirms" if rules['max_party_auto'] else '')
    if 0 < rules['max_covers_per_slot'] < rules['max_party']:
        big += (f"; groups over {rules['max_covers_per_slot']} (the guests-per-slot limit) are requests the team confirms and "
                "need a time slot with no other bookings")
    lines.append(f"GROUP SIZE: 1-{rules['max_party']} guests can book online{big}. Bigger groups: offer to pass the request "
                 "to the team.")
    status, _why = rc.table_status_for(rules, model, 1)
    lines.append("CONFIRMATION: reservations that pass the checks are CONFIRMED instantly (status confirmed)." if status == 'confirmed'
                 else "CONFIRMATION: reservations are REQUESTS the restaurant approves (status pending) — say the request "
                      "is in and the restaurant will confirm; never say confirmed.")
    if rules['hold_minutes']:
        lines.append(f"LATE ARRIVALS: the table is held for {rules['hold_minutes']} minutes after the reservation time.")
    lines.append("PAYMENT: no deposit or payment is taken in this chat (mention a deposit only if the business info says so).")
    lines.append(rc.business_info_line(business_id, rules))
    menu = _menu(business_id, cur)
    if menu:
        lines.append("MENU (information only — this chat books tables, it does not take food orders; for allergies use only "
                     "what is written here and always ask guests with severe allergies to tell staff):\n" + menu)
    return '\n'.join(lines)


# ---------------------------------------------------------------- công cụ
def _vi(ctx):
    return (ctx or {}).get('lang') == 'vi'


def _when(day, minute):
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute)


def _stamp(dt):
    return dt.strftime('%Y-%m-%d %H:%M') if dt else None


def _table_names(business_id):
    return {t.get('id'): t.get('name') for t in db.dining_tables.find({'business_id': business_id}, {'_id': 0, 'id': 1, 'name': 1})}


def _cannot_manage(ctx):
    phone = rc.shop_phone(ctx.get('business_id'))
    if _vi(ctx):
        return ("Vì bảo mật, em chỉ xem và đổi được đặt bàn đã đặt trong khung chat này. "
                + (f"Mình gọi quán số {phone} " if phone else "Mình gọi điện cho quán ") + "để kiểm tra đặt bàn khác nhé.")
    return ("For your security I can only see and change reservations made in this chat. "
            + (f"Please call the restaurant on {phone} " if phone else "Please call the restaurant ") + "about any other reservation.")


def _not_yours(ctx):
    return ("No reservation with that id belongs to this chat — do not reveal or change anything. Tell the customer: "
            + _cannot_manage(ctx))


def _staff_note(ctx, vi_text, en_text):
    vi_shop = rc.currency(ctx['business_id']) == 'VND'
    rc.note_for_staff(ctx['business_id'], rc.staff_thread(ctx), vi_text if vi_shop else en_text)


def _say(status, ctx):
    if status == 'confirmed':
        return 'Booked and confirmed.'
    return 'Request received — the restaurant confirms it. Do NOT say confirmed, booked or held.'


def _other_days(business_id, rules, tables, day, party, now, around=None):
    around = None if rules['hours'] else around      # giờ mở cửa chưa công bố: chỉ kiểm được quanh giờ khách hỏi
    out = []
    for k in range(1, 15):
        d = day + timedelta(days=k)
        times = rc.table_free_times(business_id, rules, tables, d, party, now, around=around)
        if times:
            out.append({'date': d.isoformat(), 'weekday': d.strftime('%A'),
                        'first_times': rc.nearest_times(times, around, 4) if around is not None else times[:4]})
        if len(out) >= 3:
            break
    return out


def _alternatives(business_id, rules, tables, day, party, now, want_min, exclude_id=None):
    if rc.table_model(rules, tables) == 'none':
        return {}
    times = rc.table_free_times(business_id, rules, tables, day, party, now, exclude_id=exclude_id, around=want_min)
    out = {'other_times_same_day': rc.nearest_times(times, want_min)}
    if not times:
        out['next_available'] = _other_days(business_id, rules, tables, day, party, now, around=want_min)
    return out


def _check(args, ctx):
    bid = ctx['business_id']
    rules = rc.load_rules(bid, 'table')
    now = rc.naive_now(bid, ctx.get('now_local'))
    day = rc.parse_day(args.get('date'))
    party = rc.parse_party(args.get('party_size'), rules['max_party'])
    want = rc.parse_hm(args['time']) if str(args.get('time') or '').strip() else None
    tables = rc.tables_with_seats(bid)
    model = rc.table_model(rules, tables)
    hrs = rc.hours_on(rules, day)
    out = {'success': True, 'date': day.isoformat(), 'weekday': day.strftime('%A'), 'party_size': party,
           'opening_hours': ('not published' if hrs == rc.UNKNOWN else 'closed' if hrs is None
                             else f"{rc.fmt_min(hrs[0])}-{rc.fmt_min(hrs[1])}"),
           'availability': 'request_only' if model == 'none' else 'live'}
    rows = rc.table_rows(bid, day) if model != 'none' else []
    fit_reason = None
    if want is not None:
        req = {'time': rc.fmt_min(want)}
        try:
            rc.check_window(rules, _when(day, want), now, rules['last_booking_before_close'])
            ok, why, _tid = rc.table_fit(rules, tables, rows, _when(day, want), party)
            fit_reason = why
            if ok is None:
                req.update(free=None, can_request=True)
            else:
                req['free'] = bool(ok)
                if why:
                    req['why'] = ("No single table seats the whole group — the restaurant joins tables and confirms it."
                                  if why == 'needs_joined_tables' else rc.REASONS[why][0])
        except rc.ReservationError as e:
            req.update(free=False, why=rc.explain(e))
        out['requested_time'] = req
    if model == 'none':
        ok_times = []
        for m in rc.table_candidate_times(rules, day):
            try:
                rc.check_window(rules, _when(day, m), now, rules['last_booking_before_close'])
                ok_times.append(rc.fmt_min(m))
            except rc.ReservationError:
                pass
        if ok_times:
            out['request_times'] = rc.nearest_times(ok_times, want, 8) if want is not None else rc.spread(ok_times, 8)
        out['note'] = ("No live table availability: a reservation here is a REQUEST the restaurant confirms. Never say a "
                       "table is free, held or confirmed.")
    elif hrs == rc.UNKNOWN and want is None:
        # Giờ mở cửa chưa công bố: chỉ kiểm được quanh 1 giờ khách nói — danh sách rỗng ở đây KHÔNG có nghĩa là kín chỗ.
        out['available_times'] = []
        out['note'] = ('Opening hours are not published — ask the customer for a time and check that time. Do not say the '
                       'restaurant is full.')
    else:
        free = rc.table_free_times(bid, rules, tables, day, party, now, around=want, rows=rows)
        out['available_times'] = rc.nearest_times(free, want) if want is not None else rc.spread(free)
        if not free:
            out['next_available'] = _other_days(bid, rules, tables, day, party, now, around=want)
    status, why = rc.table_status_for(rules, model, party, fit_reason)
    out['if_booked_status'] = status
    if why:
        out['pending_reason'] = why
    if rules['hold_minutes']:
        out['hold_policy'] = f"Tables are held {rules['hold_minutes']} minutes after the reservation time."
    return out


def _dup_result(dup, ctx, name, note):
    if not rc.is_owned(dup, ctx):
        # Chat chưa chứng minh là chủ: KHÔNG nói "SĐT này đã có bàn đúng giờ này" (ai gõ SĐT người khác cũng dò được giờ người
        # đó tới quán). Không tạo bàn thứ 2; ghi chú cho quán tự liên hệ khách — trả lời như 1 yêu cầu chờ quán xác nhận.
        when = str(dup.get('reserved_time') or '')[:16].replace('T', ' ')
        _staff_note(ctx, f"📅 Chat AI xin đặt bàn {when} cho {name} — SĐT này đã có đặt bàn #{dup.get('id')} đúng giờ đó nên "
                         "AI KHÔNG tạo thêm (chat chưa xác minh là chủ). Quán liên hệ khách để xác nhận.",
                    f"📅 The AI chat asked for a table at {when} for {name} — this phone number already has reservation "
                    f"#{dup.get('id')} at that time, so nothing new was created (the chat isn't verified as its owner). "
                    "Please confirm with the customer.")
        return {'success': True, 'request_sent_to_team': True, 'confirmed': False, 'status': 'pending',
                'say': _say('pending', ctx),
                'note': 'Passed to the restaurant, which confirms it with the customer by phone. Nothing new was booked in '
                        'this chat: give no reservation number and never say it is confirmed.'}
    upd = {}
    if name and name != dup.get('customer_name'):
        upd['customer_name'] = name
    if note and not dup.get('note'):
        upd['note'] = str(note).strip()[:500]
    if upd:
        db.table_reservations.update_one({'id': dup['id'], 'business_id': dup['business_id']}, {'$set': upd})
    start = rc.parse_dt(dup.get('reserved_time'))
    return {'success': True, 'already_reserved': True, 'reservation_id': dup['id'], 'status': dup.get('status'),
            'time': _stamp(start), 'party_size': dup.get('party_size'),
            'note': 'Same reservation as before — nothing new was created. To change the party size or time use '
                    'fnb_change_reservation.'}


def _reserve(args, ctx):
    bid = ctx['business_id']
    rules = rc.load_rules(bid, 'table')
    now = rc.naive_now(bid, ctx.get('now_local'))
    name, phone = rc.booking_contact(args, ctx)
    day = rc.parse_day(args.get('date'))
    if not str(args.get('time') or '').strip():
        raise rc.ReservationError('bad_time')
    want = rc.parse_hm(args['time'])
    when = _when(day, want)
    party = rc.parse_party(args.get('party_size'), rules['max_party'])
    note = args.get('note')
    tables = rc.tables_with_seats(bid)
    model = rc.table_model(rules, tables)
    try:
        rc.check_window(rules, when, now, rules['last_booking_before_close'])
    except rc.ReservationError as e:
        return {'success': False, 'reason': e.reason, 'message': rc.explain(e),
                **_alternatives(bid, rules, tables, day, party, now, want)}
    country = rc.ctx_country(ctx)
    with rc.reservation_lock(bid, 'table'):
        dup = rc.find_duplicate(db.table_reservations, bid, phone, when, rc.TABLE_ACTIVE, country)  # trong khoá: 2 lượt gọi
        if dup:                                                                                     # trùng không thành 2 bàn
            return _dup_result(dup, ctx, name, note)
        ok, why, table_id = rc.table_fit(rules, tables, rc.table_rows(bid, day), when, party)
        if ok is not False:
            status, pending_reason = rc.table_status_for(rules, model, party, why)
            doc = rc.create_table_reservation(bid, name, phone, party, rc.iso_slot(when), note, status=status,
                                              source='ai_bot', table_id=table_id, extra=rc.ai_tags(ctx))
    if ok is False:
        return {'success': False, 'reason': why, 'message': rc.REASONS[why][0],
                **_alternatives(bid, rules, tables, day, party, now, want)}
    table_name = _table_names(bid).get(table_id) if table_id is not None else None
    _staff_note(ctx, f"📅 AI đặt bàn #{doc['id']}: {party} khách, {when:%d/%m %H:%M}, {name} ({phone}) — "
                     + ('đã xác nhận' if status == 'confirmed' else 'CHỜ quán duyệt trên Đặt bàn'),
                f"📅 AI table reservation #{doc['id']}: {party} guests, {when:%a %d %b %H:%M}, {name} ({phone}) — "
                + ('confirmed' if status == 'confirmed' else 'PENDING your approval on Reservations'))
    out = {'success': True, 'reservation_id': doc['id'], 'status': status, 'time': _stamp(when), 'weekday': when.strftime('%A'),
           'party_size': party, 'name': name, 'table': table_name, 'say': _say(status, ctx)}
    if pending_reason:
        out['pending_reason'] = pending_reason
    if pending_reason == 'large_party':
        out['needs_staff'] = True
        out['note'] = 'Large group: the team reviews it and will confirm with the customer.'
    if rules['hold_minutes']:
        out['hold_policy'] = f"Tables are held {rules['hold_minutes']} minutes after the reservation time."
    return out


def _mine(args, ctx):
    bid = ctx['business_id']
    if not rc.can_prove_owner(ctx):
        return {'success': True, 'verified': False, 'reservations': [], 'tell_customer': _cannot_manage(ctx)}
    now = rc.naive_now(bid, ctx.get('now_local'))
    names = _table_names(bid)
    out = []
    for r in rc.owned_upcoming(db.table_reservations, bid, ctx, rc.TABLE_ACTIVE, now):
        start = rc.parse_dt(r.get('reserved_time'))
        out.append({'reservation_id': r['id'], 'time': _stamp(start), 'weekday': start.strftime('%A') if start else None,
                    'party_size': r.get('party_size'), 'status': r.get('status'), 'table': names.get(r.get('table_id')),
                    'note': r.get('note')})
    res = {'success': True, 'verified': True, 'reservations': out}
    if not ctx.get('phone'):
        res['scope'] = 'Only reservations made in this chat are listed.'
        if not out:
            res['tell_customer'] = _cannot_manage(ctx)
    return res


def _rid(args):
    try:
        return int(str(args.get('reservation_id')).strip())
    except (TypeError, ValueError):
        raise ai_packs.PackError('reservation_id must be a number from fnb_my_reservations.')


def _own_row(ctx, rid):
    doc = db.table_reservations.find_one({'id': rid, 'business_id': ctx['business_id']}, {'_id': 0})
    if not doc or not rc.is_owned(doc, ctx):
        raise ai_packs.PackError(_not_yours(ctx))
    return doc


def _cancel(args, ctx):
    bid = ctx['business_id']
    rid = _rid(args)
    doc = _own_row(ctx, rid)
    start = rc.parse_dt(doc.get('reserved_time'))
    if doc.get('status') == 'cancelled':
        return {'success': True, 'already_cancelled': True, 'reservation_id': rid, 'time': _stamp(start)}
    if doc.get('status') not in rc.CHANGEABLE:
        raise ai_packs.PackError(f"This reservation is '{doc.get('status')}' and can't be cancelled in chat — offer to pass "
                                 'it to the team.')
    now = rc.naive_now(bid, ctx.get('now_local'))
    if start and start < now:
        raise ai_packs.PackError('This reservation time has already passed — it cannot be cancelled in chat.')
    res = db.table_reservations.update_one(
        {'id': rid, 'business_id': bid, 'status': {'$in': list(rc.CHANGEABLE)}},
        {'$set': {'status': 'cancelled', 'cancelled_by': 'customer_ai_chat', 'cancelled_at': datetime.now().isoformat()}})
    if not res.matched_count:
        raise ai_packs.PackError('This reservation was changed by the restaurant just now — call fnb_my_reservations again.')
    _staff_note(ctx, f"Khách tự huỷ đặt bàn #{rid} ({_stamp(start)}, {doc.get('party_size')} khách) qua chat AI.",
                f"Guest cancelled table reservation #{rid} ({_stamp(start)}, {doc.get('party_size')} guests) in the AI chat.")
    return {'success': True, 'cancelled': True, 'reservation_id': rid, 'time': _stamp(start)}


def _change(args, ctx):
    bid = ctx['business_id']
    rid = _rid(args)
    doc = _own_row(ctx, rid)
    if doc.get('status') not in rc.CHANGEABLE:
        raise ai_packs.PackError(f"This reservation is '{doc.get('status')}' and can't be changed in chat — offer to pass "
                                 'it to the team.')
    rules = rc.load_rules(bid, 'table')
    now = rc.naive_now(bid, ctx.get('now_local'))
    old = rc.parse_dt(doc.get('reserved_time'))
    if old is None or old < now:
        raise ai_packs.PackError('This reservation time has already passed — it cannot be changed in chat.')
    day = rc.parse_day(args['date']) if str(args.get('date') or '').strip() else old.date()
    want = rc.parse_hm(args['time']) if str(args.get('time') or '').strip() else old.hour * 60 + old.minute
    party = (rc.parse_party(args['party_size'], rules['max_party']) if args.get('party_size') not in (None, '')
             else max(1, int(doc.get('party_size') or 1)))
    when = _when(day, want)
    if when == old and party == doc.get('party_size'):
        return {'success': True, 'unchanged': True, 'reservation_id': rid, 'time': _stamp(old), 'status': doc.get('status')}
    tables = rc.tables_with_seats(bid)
    model = rc.table_model(rules, tables)
    try:
        rc.check_window(rules, when, now, rules['last_booking_before_close'])
    except rc.ReservationError as e:
        return {'success': False, 'reason': e.reason, 'message': rc.explain(e), 'reservation_unchanged': True,
                **_alternatives(bid, rules, tables, day, party, now, want, exclude_id=rid)}
    with rc.reservation_lock(bid, 'table'):
        ok, why, table_id = rc.table_fit(rules, tables, rc.table_rows(bid, day, exclude_id=rid), when, party)
        if ok is not False:
            status, pending_reason = rc.table_status_for(rules, model, party, why)
            upd = {'reserved_time': rc.iso_slot(when), 'party_size': party, 'status': status,
                   'rescheduled_from': doc.get('reserved_time'), 'changed_at': datetime.now().isoformat(),
                   'changed_by': 'customer_ai_chat'}
            if tables:
                upd['table_id'] = table_id
            elif when != old:
                upd['table_id'] = None  # bàn chủ quán đã xếp có thể không còn trống giờ mới -> xếp lại
            res = db.table_reservations.update_one({'id': rid, 'business_id': bid, 'status': {'$in': list(rc.CHANGEABLE)}},
                                                   {'$set': upd})
    if ok is False:
        return {'success': False, 'reason': why, 'message': rc.REASONS[why][0], 'reservation_unchanged': True,
                **_alternatives(bid, rules, tables, day, party, now, want, exclude_id=rid)}
    if not res.matched_count:
        raise ai_packs.PackError('This reservation was changed by the restaurant just now — call fnb_my_reservations again.')
    _staff_note(ctx, f"Khách đổi đặt bàn #{rid}: {_stamp(old)} ({doc.get('party_size')} khách) -> {_stamp(when)} ({party} khách)"
                     + (' — CHỜ duyệt lại' if status == 'pending' else ''),
                f"Guest changed table reservation #{rid}: {_stamp(old)} ({doc.get('party_size')} guests) -> {_stamp(when)} "
                f"({party} guests)" + (' — PENDING approval' if status == 'pending' else ''))
    out = {'success': True, 'reservation_id': rid, 'old_time': _stamp(old), 'time': _stamp(when), 'weekday': when.strftime('%A'),
           'party_size': party, 'status': status, 'previous_status': doc.get('status'), 'say': _say(status, ctx)}
    if pending_reason:
        out['pending_reason'] = pending_reason
    if status == 'pending' and doc.get('status') == 'confirmed':
        out['note'] = 'The change needs the restaurant to confirm it again — say so.'
    return out


_HANDLERS = {'fnb_check_tables': _check, 'fnb_reserve_table': _reserve, 'fnb_my_reservations': _mine,
             'fnb_cancel_reservation': _cancel, 'fnb_change_reservation': _change}


def execute(name, args, ctx):
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ai_packs.PackError(f"Unknown table tool '{name}'.")
    if not (ctx or {}).get('business_id'):
        raise ai_packs.PackError('No business in this chat.')
    try:
        return handler(args if isinstance(args, dict) else {}, ctx)
    except rc.ReservationError as e:
        raise ai_packs.PackError(rc.explain(e))
