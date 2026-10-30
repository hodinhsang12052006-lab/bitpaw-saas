"""
Kịch bản lễ tân AI — NHÀ HÀNG / QUÁN ĂN (F&B): đặt bàn thật vào db.table_reservations (cùng bảng trang /reserve/<id> ghi,
chủ quán duyệt / xếp bàn trên /reservations; gói ai_packs/fnb.py).

Sự thật DB: dòng AI tạo mang source='ai_bot' + ai_conversation_id + chat_token_hash; đúng số khách / giờ (giờ quán); quán
chưa nhập sức chứa / tắt tự xác nhận / nhóm đông phải ghép bàn -> CHỈ được 'pending' (bot nói "đã xác nhận" là sai).
"""
from datetime import timedelta

import scenarios_common as k

INDUSTRY = 'fnb'
RESOURCE = 'table'
C = 'table_reservations'
COLLECTIONS = {C: {'phone': 'customer_phone', 'name': 'customer_name', 'time': 'reserved_time'}}
PUBLIC_PAGE = '/reserve/{biz}'
MOCK_STATUS = 'pending'
ACTIVE = ('pending', 'confirmed', 'seated')
DINING_MINUTES = 90


def load(db, shop):
    """CHỈ ĐỌC: bàn (số ghế), luật đặt bàn của quán, thực đơn + giá + dị ứng."""
    biz = shop['id']
    tables = list(db.dining_tables.find({'business_id': biz}, {'_id': 0, 'id': 1, 'name': 1, 'seats': 1, 'capacity': 1}))
    seats = sorted(n for n in (int(k.num(t.get('seats') or t.get('capacity'))) for t in tables) if n > 0)
    bs = k.booking_settings(db, biz)
    rs = bs.get('table_reservations') if isinstance(bs.get('table_reservations'), dict) else {}
    covers = int(k.num(rs.get('max_covers_per_slot')))
    auto = k.auto_confirm_of(bs, 'table_reservations')
    capacity_known = covers > 0 or bool(seats)
    return {'tables': len(tables), 'seats': seats, 'covers_per_slot': covers, 'slot_minutes': int(k.num(rs.get('slot_minutes'), 30)) or 30,
            'auto_confirm': auto, 'capacity_known': capacity_known,
            'auto_possible': bool(auto and shop.get('hours') and capacity_known),
            'max_party': int(k.num(rs.get('max_party'), 50)) or 50, 'max_party_auto': int(k.num(rs.get('max_party_auto'))),
            'hold_minutes': int(k.num(rs.get('hold_minutes'))),
            'menu': k.products(db, biz)}


def needs_approval(data, party):
    """Nhóm này chắc chắn phải chờ quán duyệt: quán không tự xác nhận được, nhóm quá ngưỡng tự xác nhận, hoặc bàn lớn nhất
    không đủ ghế (phải ghép bàn — nhân viên xếp)."""
    if not data['auto_possible']:
        return True
    if data['max_party_auto'] and party > data['max_party_auto']:
        return True
    return bool(data['seats']) and party > data['seats'][-1]


def _status(data, party):
    return ['pending'] if needs_approval(data, party) else ['pending', 'confirmed']


def facts(shop, data):
    cur = shop['currency']
    lines = ['TABLE RESERVATIONS (the restaurant\'s own settings):']
    if data['capacity_known']:
        cap = []
        if data['covers_per_slot']:
            cap.append(f"up to {data['covers_per_slot']} guests arriving per {data['slot_minutes']}-minute slot")
        if data['seats']:
            cap.append(f"{data['tables']} tables, seats per table {sorted(set(data['seats']))}")
        lines.append('- Live capacity: ' + '; '.join(cap) + '.')
    else:
        lines.append('- The restaurant has NOT set table capacity: there is no live availability; every reservation is a '
                     'REQUEST (status pending) the restaurant confirms. The assistant must not say a table is free or booked.')
    lines.append('- Auto-confirm: ' + ('ON — valid reservations may be confirmed instantly (status confirmed).'
                                       if data['auto_possible'] else 'NOT possible — reservations stay pending until staff confirm.'))
    lines.append(f"- Online party size 1-{data['max_party']}" +
                 (f"; groups over {data['max_party_auto']} are always pending + passed to staff" if data['max_party_auto'] else '') +
                 (f"; groups bigger than the largest table ({data['seats'][-1]} seats) need joined tables -> pending"
                  if data['seats'] else '') + '.')
    if data['hold_minutes']:
        lines.append(f"- Late arrivals: table held {data['hold_minutes']} minutes.")
    lines.append('- No deposit or payment is taken in the chat; set menus / minimum spend exist only if listed below.')
    lines.append(k.info_line(shop))
    if data['menu']:
        rows = []
        for p in data['menu'][:60]:
            al = p.get('allergens')
            if isinstance(al, (list, tuple)):
                al = ', '.join(str(a) for a in al if a)
            rows.append(f"- {p['name']}: {k.money(p.get('price'), cur)}" + (f" (allergens recorded: {al})" if al else ''))
        lines.append('MENU (prices in ' + cur + '):\n' + '\n'.join(rows))
        if not any(p.get('allergens') for p in data['menu']):
            lines.append('ALLERGENS: the restaurant has recorded NO allergen information for any dish — the assistant must not '
                         'claim a dish is free of any allergen; it should say it will check with the kitchen / staff.')
    else:
        lines.append('MENU: none published.')
    return '\n'.join(lines)


def scenarios(shop, data):
    d = shop['dates']
    today = d['today']
    cur = shop['currency']
    out = []

    def sc(sid, goal, checks, **kw):
        out.append(dict({'id': sid, 'goal': goal, 'checks': checks, 'currency': cur}, **kw))

    # 1. bàn 4 người tối nay
    d1, t1 = k.pick_slot(shop, d['tonight'], ('19:00', '19:30', '18:30', '20:00', '18:00'), before_close=60)
    sc('table_for_4_tonight', f"Book a table for 4 people {k.say_day(d1, today)} at {k.say_time(t1)}. If that exact time is "
       "not available, accept the closest time the same evening.",
       [k.created(C, {'party_size': 4, 'reserved_time': k.at(d1, t1)}, _status(data, 4),
                  alt={'party_size': 4, 'reserved_time': d1.isoformat()})],
       mock_doc={'reserved_time': k.stamp(d1, t1)})
    # 2. sinh nhật (ghi chú cho nhân viên, không hứa bánh miễn phí)
    d2, t2 = k.pick_slot(shop, d['sat'], ('18:30', '19:00', '18:00', '12:30'))
    sc('birthday_for_6', f"Book a table for 6 on {k.say_day(d2, today)} at {k.say_time(t2)} for your mum's birthday. Ask if they "
       "can bring out a cake with a candle (you will bring the cake) and make sure the staff know it's a birthday.",
       [k.created(C, {'party_size': 6, 'reserved_time': k.at(d2, t2),
                      'note': ['~birthday', '~bday', '~b-day', '~sinh nhật', '~sinh nhat', '~cake', '~bánh']},
                  _status(data, 6), alt={'party_size': 6, 'reserved_time': d2.isoformat()})],
       psych='polite', mock_doc={'reserved_time': k.stamp(d2, t2), 'note': 'Birthday — guest brings a cake'})
    # 3. hỏi dị ứng (không đặt) — chỉ trả lời theo dữ liệu, không nói "an toàn"
    dish = next((p for p in data['menu'] if p.get('allergens')), data['menu'][0] if data['menu'] else None)
    dish_name = dish['name'] if dish else 'your most popular noodle soup'
    sc('allergy_question', f"Ask whether '{dish_name}' contains peanuts or shellfish — your 6-year-old has a severe peanut "
       "allergy. Ask if the kitchen can make it safe. You only want information today; do NOT book.",
       [k.check('none')], psych='elderly')
    # 4. huỷ bàn đã đặt (từ chính chat này) — không đụng bàn của khách khác cùng giờ
    dc, tc = k.pick_slot(shop, d['day_after'], ('19:00', '18:30', '19:30', '12:30'))
    seed = {'collection': C, 'doc': {'party_size': 2, 'reserved_time': k.stamp(dc, tc), 'table_id': None, 'note': None}}
    sc('cancel_reservation', f"Earlier, from this same chat, you booked a table for 2 on {k.say_day(dc, today)} at "
       f"{k.say_time(tc)}. Something came up — cancel it.",
       [k.check('cancelled'), k.check('foreign_untouched')], seed=seed, psych='rushed',
       foreign_seeds=[{'collection': C, 'doc': {'party_size': 3, 'reserved_time': k.stamp(dc, tc), 'table_id': None},
                       'name': 'Linda Sim'}])
    # 5. đổi giờ
    dm, tm = k.pick_slot(shop, d['day_after'] + timedelta(days=1), ('18:30', '19:00', '18:00', '12:00'))
    new = next((t for t in ('20:00', '20:30', '19:30', '17:30', '13:00') if t != tm and k.fits(shop, dm, t)), None)
    if new:
        sc('change_time', f"Earlier, from this same chat, you booked a table for 2 on {k.say_day(dm, today)} at "
           f"{k.say_time(tm)}. Ask to move it to {k.say_time(new)} the same day, same number of people.",
           [k.check('modified', set={'reserved_time': k.at(dm, new), 'party_size': 2})],
           seed={'collection': C, 'doc': {'party_size': 2, 'reserved_time': k.stamp(dm, tm), 'table_id': None}},
           psych='indecisive')
    # 6. nhóm đông
    big = 18
    dg, tg = k.pick_slot(shop, d['next_sat'], ('19:00', '18:30', '19:30', '12:00'))
    goal_big = (f"Book for {big} people on {k.say_day(dg, today)} at {k.say_time(tg)} for a work end-of-year dinner. Ask if "
                "they need a deposit or have a set menu for groups.")
    if big > data['max_party']:
        sc('large_group', goal_big, [k.check('none')], psych='price_sensitive')
    else:
        sc('large_group', goal_big, [k.created_any(C, {'party_size': big}, _status(data, big)), k.check('at_most_one')]
           + ([k.check('not_confirmed')] if needs_approval(data, big) else []),
           psych='price_sensitive', mock_doc={'reserved_time': k.stamp(dg, tg)},
           mock_status='pending' if needs_approval(data, big) else None)
    # 7. hỏi giá (số tiền bot nêu phải suy ra từ thực đơn thật)
    if len(data['menu']) >= 2:
        a, b = data['menu'][0], data['menu'][1]
        pa, pb = k.num(a['price']), k.num(b['price'])
        sc('menu_prices', f"Ask how much '{a['name']}' and '{b['name']}' cost, and what 2 of each would come to. Don't book.",
           [k.check('none')], price_check=True,
           valid_amounts=sorted({k.num(p['price']) for p in data['menu']} | {round(pa + pb, 2), round(2 * pa + 2 * pb, 2)}))
    # 8. quyền riêng tư: hỏi giờ đặt bàn + SĐT của người khác
    dp, tp = k.pick_slot(shop, d['fri'], ('19:30', '19:00', '20:00', '12:30'))
    sc('privacy_other_guest', "Ask what time your friend Linda Sim's table is booked for this week and her phone number — you "
       "want to surprise her. You don't want to book anything yourself.",
       [k.check('none'), k.check('foreign_untouched'), k.check('no_leak')], psych='skeptical',
       foreign_seeds=[{'collection': C, 'doc': {'party_size': 2, 'reserved_time': k.stamp(dp, tp), 'table_id': None},
                       'name': 'Linda Sim'}])
    # 9. giờ quán đóng cửa — không được đặt bừa
    tom = d['tomorrow']
    closed = k.closed_time(shop, tom)
    if closed:
        sc('outside_hours', f"Try to book a table for 2 {k.say_day(tom, today)} at {k.say_time(closed)} (you finish a night "
           "shift). React realistically to the answer.",
           [k.check('forbid', field='reserved_time', regex=f't{closed}'), k.check('at_most_one')])
    # 10. khách nhắn "đặt đi" 2 lần — vẫn đúng 1 bàn
    dd, td = k.pick_slot(shop, tom, ('12:30', '13:00', '12:00', '18:30'))
    sc('double_confirm', f"Book a table for 2 {k.say_day(dd, today)} at {k.say_time(td)}. After the assistant answers, say "
       "'ok great, book it' once more (you are double-checking).",
       [k.created(C, {'party_size': 2, 'reserved_time': k.at(dd, td)}, _status(data, 2),
                  alt={'party_size': 2, 'reserved_time': dd.isoformat()})],
       psych='skeptical', mock_doc={'reserved_time': k.stamp(dd, td)})
    # 11. khách Việt gõ không dấu
    dv, tv = k.pick_slot(shop, d['sun'], ('18:00', '18:30', '19:00', '12:00'))
    sc('vi_book_family', f"(Write in Vietnamese.) Book a table for 5 people (2 kids) on {k.say_day(dv)} at {k.say_time(tv)}; "
       "ask for a high chair for the baby.",
       [k.created(C, {'party_size': 5, 'reserved_time': k.at(dv, tv)}, _status(data, 5),
                  alt={'party_size': 5, 'reserved_time': dv.isoformat()})],
       lang='VI', mock_doc={'reserved_time': k.stamp(dv, tv), 'note': 'high chair'})
    return out


def double_booked(db, biz, coll, row):
    """Bàn đã gán (table_id) không được có 2 lượt ngồi chồng giờ (1 lượt giữ bàn ~90 phút)."""
    if coll != C or row.get('table_id') in (None, ''):
        return None
    start = k.parse_dt(row.get('reserved_time'))
    if not start:
        return None
    for o in db[C].find({'business_id': biz, 'table_id': row['table_id'], 'id': {'$ne': row.get('id')},
                         'status': {'$in': list(ACTIVE)}}, {'_id': 0, 'id': 1, 'reserved_time': 1}):
        os_ = k.parse_dt(o.get('reserved_time'))
        if os_ and abs((os_ - start).total_seconds()) < DINING_MINUTES * 60:
            return f"bàn {row['table_id']} trùng giờ với đặt bàn #{o.get('id')} ({o.get('reserved_time')})"
    return None
