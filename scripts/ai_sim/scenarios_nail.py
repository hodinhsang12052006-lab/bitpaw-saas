"""
Kịch bản lễ tân AI — TIỆM NAIL: lịch hẹn thật (db.appointments, công cụ đặt lịch có sẵn ai_function_tools + booking_engine).
Dùng NGUYÊN bộ kịch bản + cách chấm DB của sim_booking.py (baseline booking_p28f) để số liệu so được với các lượt cũ; khác
duy nhất: chạy qua khung sim_receptionist (mã chat riêng từng khách, SĐT giả đã kiểm chưa từng có, so lời bot với DB, dọn
theo mã hội thoại).
"""
from datetime import datetime, timedelta

INDUSTRY = 'nail'
RESOURCE = 'appointment'
C = 'appointments'
COLLECTIONS = {C: {'phone': 'customer_phone', 'name': 'customer_name', 'time': 'book_time'}}
PUBLIC_PAGE = '/booking/nail/qr/{biz}'
MOCK_STATUS = 'confirmed'


def _sb():
    import sim_booking   # nạp lười: sim_booking đọc db của sim_core (DB giả khi --mock)
    return sim_booking


def load(db, shop):
    import booking_rules
    biz = shop['id']
    rules = booking_rules.get_rules(biz)
    sv = _sb().services(biz)
    team = sorted({n for n in booking_rules._staff_names(biz).values() if n})
    return {'services': sv, 'rules': rules, 'team': team}


def facts(shop, data):
    import booking_rules
    rules = data['rules']
    return ("Services (price, duration): " + '; '.join(
        f"{s['name']} {s['price']} ({booking_rules.duration_of(rules, s['id'])} min)" for s in data['services']) +
            f"\nTeam: {', '.join(data['team']) or 'none listed'}\n" + booking_rules.describe_for_ai(shop['id']) +
            "\nThe assistant has live tools: check_availability returns REAL free times from the booking system (opening hours, "
            "team on the roster, existing bookings), so times it offers after checking are real, not invented. A record with "
            "source 'sim_seed' is the customer's ORIGINAL booking made before the chat: if its time differs from the original, "
            "the assistant really MOVED it (a correct reschedule, not a duplicate).")


def stamp(when):
    return when.strftime('%Y-%m-%dT%H:%M:%S')


def legacy_mock_effect(check, default_svc, seeded_when, now):
    """Hiệu ứng DB của bot mẫu (--mock) làm ĐÚNG theo kiểu kiểm tra cũ của sim_booking."""
    kind = check[0]
    if kind in ('booked', 'booked_once'):
        svc, when = check[1], check[2]
        return {'op': 'create', 'collection': C, 'doc': {'service_id': svc['id'], 'service_name': svc['name'],
                                                         'book_time': stamp(when)}}
    if kind == 'booked_any':
        svc = check[1]
        when = datetime.combine((now + timedelta(days=2)).date(), datetime.min.time()).replace(hour=14)
        return {'op': 'create', 'collection': C, 'doc': {'service_id': svc['id'], 'service_name': svc['name'],
                                                         'book_time': stamp(when)}}
    if kind == 'rescheduled' and seeded_when:
        return {'op': 'update_seed', 'set': {'book_time': stamp(seeded_when + timedelta(days=1))}}
    if kind == 'cancelled':
        return {'op': 'update_seed', 'set': {'status': 'cancelled'}}
    return None


def wrap(raw, sv, now, pick_psych=None):
    """Kịch bản sim_booking ({'id','goal','check','seed','svc'}) -> hợp đồng sim_receptionist (checks 'legacy')."""
    out = []
    for s in raw:
        sc = {'id': s['id'], 'goal': s['goal'], 'checks': []}
        if s.get('check') and s['check'][0] != 'any':
            sc['checks'] = [{'kind': 'legacy', 'legacy': s['check']}]
        when = None
        if s.get('seed') == 'appt' and sv:
            when = datetime.combine((now + timedelta(days=3)).date(), datetime.min.time()).replace(hour=13)
            sc['seed'] = {'collection': C, 'doc': {'service_id': sv[0]['id'], 'service_name': sv[0]['name'],
                                                   'book_time': stamp(when)}}
            sc['legacy_when'] = when
            sc['goal'] += f" (Your existing booking: '{sv[0]['name']}' on {when:%A %d/%m at %H:%M}.)"
        if s.get('check'):
            eff = legacy_mock_effect(s['check'], sv[0] if sv else None, when, now)
            if eff:
                sc['mock_effect'] = eff
        if pick_psych and s['id'] in pick_psych:
            sc['psych'] = pick_psych[s['id']]
        out.append(sc)
    return out


def scenarios(shop, data):
    if not data['services']:
        return []
    raw, sv = _sb().build_scenarios(shop['id'], shop['now'])
    return wrap(raw, sv, shop['now'], {'is_human': 'skeptical', 'elderly_slow': 'elderly', 'discount_haggle': 'price_sensitive',
                                       'change_mind': 'indecisive', 'cancel': 'rushed'})


def evaluate_legacy(check, ctx):
    """Chấm đúng như sim_booking.evaluate (cùng 'giờ hiện tại' của cuộc chat để biết giờ xin lúc đầu có thật sự kín không)."""
    sb = _sb()
    sb.CONVO_NOW = ctx['now']
    return sb.evaluate(check, ctx['biz'], ctx['phone'], ctx.get('seeded') or {})
