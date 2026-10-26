"""AI Copilot cho CHỦ TIỆM (trang /ai_bot) — tách hẳn 2 việc trước đây bị trộn chung 1 ô nhập:

  1. "reply"   — soạn SẴN câu trả lời cho tin nhắn mới nhất của khách (chủ tiệm xem, sửa rồi mới gửi).
  2. "insight" — tư vấn RIÊNG cho chủ tiệm (doanh thu, giữ chân khách, kho, xếp thợ...) dựa trên số liệu
                 thật của tiệm. Khách KHÔNG BAO GIỜ thấy phần này.

BUG THẬT đã vá (đóng vai chủ tiệm, 10/2026): 4 nút "Revenue/Customer Care/Inventory/Staffing Tips" trước đây
gửi NGUYÊN câu hỏi nội bộ ("Suggest a revenue-boosting campaign for this week?") cho KHÁCH như 1 tin nhắn của
tiệm, rồi AI trả lời với vai "BitPaw AI Advisor" (tư vấn bán phần mềm) — sai người nhận, sai vai.

Dữ liệu chỉ đọc theo business_id lấy từ session (route gọi module này có @login_required).

Pha 1 (10/2026): bảng tóm tắt THEO NGÀNH. Trước đây mọi tiệm đều nhận khối "lịch hẹn 7 ngày tới" và "No POS sales in 30d:
<tên nhân viên>" kiểu tiệm nail — nhà hàng / khách sạn / xưởng / văn phòng bị AI khuyên sai ("nhân viên X không bán được gì").
Giờ mỗi ngành chỉ có số liệu THẬT từ đúng collection của ngành đó (bàn + đặt bàn, giờ phòng hát, công suất phòng, hàng hết,
sản lượng + nguyên vật liệu, việc kỹ thuật + phụ tùng, chấm công + nghỉ phép), không có dữ liệu thì ghi rõ "chưa có".
Doanh thu dùng đúng bộ lọc ai_copilot_tools.REVENUE_ORDER_FILTER và cùng khung ngày (giờ tiệm) với công cụ sales_report.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from mongo_client import db
import ai_copilot_tools as tools

INDUSTRY_LABEL = {
    'nail': 'nail salon', 'spa': 'spa / beauty salon', 'fnb': 'restaurant / cafe', 'karaoke': 'karaoke & billiards venue',
    'hotel': 'hotel / homestay', 'retail': 'retail store', 'production': 'production workshop',
    'technical': 'field technical services company', 'office': 'office / HR team',
}
SALON = ('nail', 'spa')          # ngành có lịch hẹn + hoa hồng POS theo thợ (chamcong 'Order #')
_CANCELLED = ['cancelled', 'canceled', 'no_show', 'rejected']

INSIGHT_TOPICS = {
    'revenue': "How can I grow revenue in the next 7 days? Give concrete promotions/upsells based on my best and weakest services.",
    'retention': "Which customers should I win back and exactly what message/offer should I send them?",
    'inventory': "Review my stock/products: what is running low, what is not selling, what should I reorder, bundle or discount?",
    'staffing': "How should I schedule and motivate my staff this week based on bookings and their performance?",
    # Nút hỏi nhanh theo ngành (templates/ai_bot.html, khối cpTopicsData) — câu hỏi bám đúng các dòng của bảng tóm tắt ngành.
    'revenue_general': "How is revenue trending (last 30 days vs the 30 days before) and what are 2-3 concrete ways to grow it "
                       "in the next 7 days, based on my best and weakest sellers?",
    'staffing_general': "How should I plan my team this week based on the attendance, workload and roster data you have?",
    'nail_week': "How full are the next 7 days of appointments? Which days or times look empty, and who should I invite to fill them?",
    'spa_packages': "How many package sessions do clients still have to use, which packages expire within 30 days, "
                    "and who should I remind first?",
    'fnb_menu': "Which menu items sold best and worst in the last 30 days, and what should I push, bundle or take off this week?",
    'fnb_tables': "How busy are my tables: table bills in the last 30 days, tables in service now and reservations for the next "
                  "7 days? What should I do about the quiet times?",
    'karaoke_rooms': "How are my rooms used: sessions and room-hours per room in the last 30 days, utilisation if it is known, "
                     "and reservations for the next 7 days? How can I fill idle rooms?",
    'karaoke_fnb': "How much do groups spend on food and drinks per session compared with room time, and how can I raise it?",
    'hotel_occupancy': "What is my occupancy now and over the last 30 days, and how many arrivals and departures are coming "
                       "in the next 7 days?",
    'hotel_rate': "What average nightly rate did I get in the last 30 days and how much did extras add? "
                  "Any pricing ideas for quiet nights?",
    'retail_stock': "Which products are out of stock or running low, what is not selling, and what should I reorder first?",
    'retail_top': "What are my top sellers and best-margin products in the last 30 days, and what should I promote this week?",
    'production_output': "How much did we produce in the last 30 days compared with the 30 days before, by product and by worker?",
    'production_materials': "Which materials are out of stock or will run out soon at the current usage, and what should I reorder?",
    'technical_jobs': "How many jobs are waiting, in progress and completed in the last 30 days? What should I prioritise today?",
    'technical_techs': "How is the workload spread across my technicians (completed and in-progress jobs)?",
    'technical_parts': "Which parts are out of stock or running low, and how much did we bill for parts in the last 30 days?",
    'office_attendance': "How is attendance: timesheets and hours in the last 30 days, and who has not logged any time this week?",
    'office_leave': "Which leave requests and expense claims are waiting for me, and who is on leave in the next 7 days?",
}

# Ngành -> khoá câu hỏi nhanh (giữ khớp với khối cpTopicsData trong templates/ai_bot.html; test đối chiếu cả 2 phía)
INDUSTRY_TOPICS = {
    'nail': ['revenue', 'retention', 'nail_week', 'inventory', 'staffing'],   # 4 nút cũ giữ nguyên (scripts/ai_copilot_e2e.mjs)
    'spa': ['revenue', 'retention', 'spa_packages', 'staffing'],
    'fnb': ['fnb_menu', 'fnb_tables', 'revenue_general', 'retention'],
    'karaoke': ['karaoke_rooms', 'karaoke_fnb', 'revenue_general', 'retention'],
    'hotel': ['hotel_occupancy', 'hotel_rate', 'revenue_general', 'retention'],
    'retail': ['retail_stock', 'retail_top', 'revenue_general', 'retention'],
    'production': ['production_output', 'production_materials', 'staffing_general'],
    'technical': ['technical_jobs', 'technical_techs', 'technical_parts', 'revenue_general'],
    'office': ['office_attendance', 'office_leave', 'staffing_general'],
    '_default': ['revenue_general', 'retention', 'inventory', 'staffing_general'],
}

# Bao lâu chưa quay lại thì coi là "lâu chưa tới" (để định hướng; công cụ lapsed_customers nhận số ngày khác)
LAPSE_DAYS = {'nail': 45, 'spa': 45, 'fnb': 30, 'karaoke': 45, 'retail': 60, 'hotel': 180, 'technical': 180}

# Dòng NOTE cuối bảng tóm tắt: nói cho AI biết công cụ nào KHÔNG áp dụng cho ngành + trang BitPaw để xem chi tiết
_NOT_SALON_NOTE = ("NOTE: this business does not take salon appointments and staff do not earn POS commission — do not use "
                   "appointments_on, packages_summary or the commission/POS-client figures of staff_report.")
INDUSTRY_NOTE = {
    'fnb': _NOT_SALON_NOTE + " Details: Reservations (/reservations), Kitchen Display (/kitchen_display).",
    'karaoke': _NOT_SALON_NOTE + " Details: Rooms (/karaoke), Room reservations (/karaoke/reservations).",
    'hotel': _NOT_SALON_NOTE + " Details: Rooms (/hotel_rooms), Reservations (/hotel/reservations).",
    'retail': _NOT_SALON_NOTE + " Details: Inventory (/inventory_alert).",
    'production': _NOT_SALON_NOTE + " Details: Output (/production_output), Materials (/production/materials).",
    'technical': _NOT_SALON_NOTE + " Details: Jobs (/quanly_dichvu), Parts (/technical/parts), GPS map (/map_dashboard).",
    'office': _NOT_SALON_NOTE + " Details: Leave (/leave_requests), Expense claims (/expense_requests), Roster (/roster).",
}


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_dmy(s):
    try:
        return datetime.strptime(str(s), '%d/%m/%Y')
    except ValueError:
        return None


def _parse_ymd(s):
    try:
        return datetime.strptime(str(s or '')[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _meta(o):
    m = o.get('metadata')
    return m if isinstance(m, dict) else {}


def _active(p):
    return str(p.get('is_active')) in ('1', 'True', 'true')


def _is_room_fee(p):
    return bool(p.get('is_room_fee')) or p.get('name') == 'Phí Giờ Karaoke'


def _industry(code, biz):
    for c in (code, biz.get('industry_code')):
        c = str(c or '').strip().lower()
        if c in INDUSTRY_LABEL:
            return c
    return ''


def _pct(x):
    return f"{x * 100:.0f}%"


class _Ctx:
    """Bối cảnh 1 lần dựng bảng tóm tắt — đọc đơn / sản phẩm / dòng hàng 30 ngày 1 lần, các khối dùng chung."""

    ORDER_FIELDS = {'_id': 0, 'id': 1, 'total_amount': 1, 'created_at': 1, 'status': 1, 'payment_method': 1, 'metadata': 1}

    def __init__(self, bid, code, now, offset, money):
        self.bid, self.code, self.now, self.offset, self.money = bid, code, now, offset, money
        self.today = now.date()
        self.server_now = now + offset        # mốc giờ máy chủ (created_at, last_purchase_at lưu theo giờ máy chủ)
        self._orders30 = self._products = self._items30 = None

    def orders30(self):
        """Đơn tính doanh thu 30 ngày gần nhất (giờ tiệm, gồm hôm nay) — đúng khung 'last_30_days' của sales_report."""
        if self._orders30 is None:
            self._orders30 = tools.revenue_orders(self.bid, self.today - timedelta(days=29), self.today + timedelta(days=1),
                                                  projection=self.ORDER_FIELDS, offset=self.offset)
        return self._orders30

    def bills30(self):
        return [o for o in self.orders30() if _num(o.get('total_amount')) > 0]

    def products(self):
        if self._products is None:
            self._products = {str(p['id']): p for p in db.products.find(
                {'business_id': self.bid}, {'_id': 0, 'id': 1, 'name': 1, 'price': 1, 'stock': 1, 'is_active': 1,
                                            'category': 1, 'cost_price': 1, 'is_room_fee': 1}) if p.get('id') is not None}
        return self._products

    def items30(self):
        """Dòng hàng của các bill 30 ngày (lọc theo order_id của chính tiệm — order_items cũ không có business_id)."""
        if self._items30 is None:
            ids = [o['id'] for o in self.bills30() if o.get('id') is not None]
            ids_any = ids + [int(i) for i in ids if str(i).isdigit()] + [str(i) for i in ids]
            self._items30 = list(db.order_items.find(
                {'order_id': {'$in': ids_any}}, {'_id': 0, 'order_id': 1, 'product_id': 1, 'quantity': 1, 'total_price': 1})) \
                if ids else []
        return self._items30


def _block_revenue(ctx):
    money, today = ctx.money, ctx.today
    cur_rev, cur_n = tools.revenue_totals(ctx.orders30())
    prev = tools.revenue_orders(ctx.bid, today - timedelta(days=59), today - timedelta(days=29),
                                projection={'_id': 0, 'total_amount': 1}, offset=ctx.offset)
    prev_rev, prev_n = tools.revenue_totals(prev)
    if not cur_n and not prev_n and not cur_rev and not prev_rev:
        if ctx.code in ('production', 'office'):
            return []          # ngành không bán qua POS: không nhắc "chưa có doanh thu"
        return ["REVENUE: no paid bills recorded in the last 60 days yet."]
    change = f"{(cur_rev - prev_rev) / prev_rev * 100:+.0f}%" if prev_rev > 0 else "n/a (no revenue in the previous 30 days)"
    avg = cur_rev / cur_n if cur_n else 0
    return [f"REVENUE last 30 days ({today - timedelta(days=29)}..{today}, paid bills, net of refunds): {money(cur_rev)} from "
            f"{cur_n} bills (avg {money(avg)}/bill); previous 30 days {money(prev_rev)} from {prev_n} bills; change {change}."]


def _block_items(ctx):
    """Bán chạy / không bán / sắp hết / lãi cao — từ products + order_items (nail, spa, fnb, karaoke, retail, hotel)."""
    money, code = ctx.money, ctx.code
    products = ctx.products()
    lines = []
    if not products:
        if code == 'fnb':
            return ["MENU: no menu items set up yet."]
        if code == 'retail':
            return ["PRODUCTS: no products set up yet."]
        return []
    skip = {k for k, p in products.items() if _is_room_fee(p)}       # phí giờ phòng hát không phải "món"
    sold = defaultdict(lambda: [0.0, 0])
    for it in ctx.items30():
        p = sold[str(it.get('product_id'))]
        p[0] += _num(it.get('total_price'))
        p[1] += int(_num(it.get('quantity')) or 1)
    ranked = sorted(((k, v) for k, v in sold.items() if k in products and k not in skip), key=lambda kv: -kv[1][0])
    top_label = {'fnb': 'TOP MENU ITEMS', 'karaoke': 'TOP FOOD & DRINKS'}.get(code, 'TOP SELLERS')
    idle_label = {'fnb': 'MENU ITEMS NOT ORDERED IN 30 DAYS', 'karaoke': 'FOOD & DRINKS NOT SOLD IN 30 DAYS'}.get(
        code, 'NOT SOLD IN 30 DAYS')
    if ranked:
        lines.append(f"{top_label} (30d): " + "; ".join(f"{products[k]['name']} {money(v[0])} ({v[1]} sold)" for k, v in ranked[:5]))
        idle = [p['name'] for k, p in products.items() if _active(p) and k not in sold and k not in skip]
        if idle:
            lines.append(f"{idle_label}: " + ", ".join(idle[:8]))
    elif code in ('fnb', 'retail', 'karaoke'):
        lines.append(f"{top_label}: nothing sold in the last 30 days yet.")
    crit = tools.critical_stock(ctx.bid)
    stocked = [p for k, p in products.items() if _active(p) and k not in skip and p.get('stock') is not None]
    if code == 'retail':
        outs = [p for p in stocked if _num(p.get('stock')) <= 0]
        low = sorted((p for p in stocked if 0 < _num(p.get('stock')) <= crit), key=lambda p: _num(p.get('stock')))
        if stocked:
            lines.append("STOCK-OUTS: " + (", ".join(p['name'] for p in outs[:10]) if outs else "none") + ".")
        if low:
            lines.append(f"LOW STOCK (at or below your critical level {crit:g}): " +
                         ", ".join(f"{p['name']} ({_num(p.get('stock')):g} left)" for p in low[:10]))
    else:
        low = sorted((p for p in stocked if _num(p.get('stock')) <= crit), key=lambda p: _num(p.get('stock')))
        if low:
            lines.append(f"LOW STOCK (at or below {crit:g}): " +
                         ", ".join(f"{p['name']} ({_num(p.get('stock')):g} left)" for p in low[:8]))
    margins = [(p['name'], _num(p.get('price')) - _num(p.get('cost_price'))) for k, p in products.items()
               if k not in skip and p.get('cost_price') is not None and _num(p.get('price'))]
    if margins:
        best = sorted(margins, key=lambda x: -x[1])[:3]
        lines.append("HIGHEST MARGIN ITEMS (price - cost): " + ", ".join(f"{n} (+{money(m)})" for n, m in best))
    return lines


def _block_appointments(ctx):
    now, today = ctx.now, ctx.today
    live = {'business_id': ctx.bid, 'status': {'$nin': ['cancelled', 'canceled']}}
    upcoming = db.appointments.count_documents({**live, 'book_time': {'$gte': now.strftime('%Y-%m-%dT%H:%M'),
                                                                       '$lt': (today + timedelta(days=7)).isoformat()}})
    rest_today = db.appointments.count_documents({**live, 'book_time': {'$gte': now.strftime('%Y-%m-%dT%H:%M'),
                                                                         '$lt': (today + timedelta(days=1)).isoformat()}})
    return [f"APPOINTMENTS booked for the next 7 days: {upcoming} (rest of today: {rest_today})."]


def _block_staff(ctx):
    emps = {e['ma_nv']: e.get('ho_ten') or e['ma_nv'] for e in db.employees.find(
        {'business_id': ctx.bid}, {'_id': 0, 'ma_nv': 1, 'ho_ten': 1}) if e.get('ma_nv')}
    if not emps:
        return ["STAFF: no employees added yet."]
    line = f"STAFF: {len(emps)} people."
    if ctx.code not in SALON:
        return [line]       # chỉ tiệm nail/spa có hoa hồng POS theo thợ — ngành khác không có "doanh số của nhân viên"
    since = ctx.today - timedelta(days=29)
    perf = defaultdict(lambda: [0.0, 0])
    for r in db.chamcong.find({'business_id': ctx.bid, 'ghi_chu': {'$regex': 'Order #'}},
                              {'_id': 0, 'ma_nv': 1, 'ngay_cham': 1, 'tien_tua': 1}).sort('id', -1).limit(3000):
        d = _parse_dmy(r.get('ngay_cham'))
        if d and d.date() >= since and r.get('ma_nv') in emps:
            perf[r['ma_nv']][0] += _num(r.get('tien_tua'))
            perf[r['ma_nv']][1] += 1
    if perf:
        line += " Commission earned last 30d: " + "; ".join(
            f"{emps[k]} {ctx.money(v[0])} ({v[1]} clients)" for k, v in sorted(perf.items(), key=lambda kv: -kv[1][0]))
        quiet = [emps[k] for k in emps if k not in perf]
        if quiet:
            line += ". No POS sales in 30d: " + ", ".join(quiet[:6])
    return [line]


def _block_customers(ctx):
    days = LAPSE_DAYS.get(ctx.code, 45)
    total = db.customers.count_documents({'business_id': ctx.bid})
    if not total:
        return ["CUSTOMERS: none saved yet."]
    cutoff = (ctx.server_now - timedelta(days=days)).isoformat()
    lapsed = list(db.customers.find({'business_id': ctx.bid, 'last_purchase_at': {'$lt': cutoff}},
                                    {'_id': 0, 'name': 1, 'total_spent': 1, 'last_purchase_at': 1})
                  .sort('total_spent', -1).limit(5))
    line = f"CUSTOMERS: {total} saved."
    if lapsed:
        line += f" High-value customers not back for {days}+ days: " + "; ".join(
            f"{c.get('name')} (spent {ctx.money(c.get('total_spent'))}, last visit {str(c.get('last_purchase_at'))[:10]})"
            for c in lapsed)
    return [line]


def _upcoming(coll, ctx, field, extra=None):
    """Đặt chỗ còn hiệu lực từ đầu hôm nay tới hết 6 ngày sau (field lưu 'YYYY-MM-DD[THH:MM]' theo giờ tiệm)."""
    q = {'business_id': ctx.bid, 'status': {'$nin': _CANCELLED},
         field: {'$gte': ctx.today.isoformat(), '$lt': (ctx.today + timedelta(days=7)).isoformat()}}
    q.update(extra or {})
    return list(coll.find(q, {'_id': 0}).limit(500))


def _block_fnb(ctx):
    money, lines = ctx.money, []
    tables = {t.get('id'): t for t in db.dining_tables.find({'business_id': ctx.bid}, {'_id': 0, 'id': 1, 'name': 1, 'status': 1})}
    bills = ctx.bills30()
    by_table = defaultdict(lambda: [0, 0.0])
    for o in bills:
        tid = _meta(o).get('table_id')
        if tid is not None:
            by_table[tid][0] += 1
            by_table[tid][1] += _num(o.get('total_amount'))
    if by_table:
        n_tab = sum(v[0] for v in by_table.values())
        busiest = sorted(by_table.items(), key=lambda kv: -kv[1][1])[:3]
        lines.append(f"TABLE BILLS last 30 days: {n_tab} of {len(bills)} bills were for a table, across {len(by_table)} tables "
                     f"(about {n_tab / len(by_table):.1f} bills per table used); busiest: " + ", ".join(
                         f"{(tables.get(k) or {}).get('name') or f'Table {k}'} {money(v[1])} ({v[0]} bills)" for k, v in busiest) + ".")
    else:
        lines.append("TABLE BILLS: no bills linked to a table in the last 30 days yet.")
    if tables:
        busy = sum(1 for t in tables.values() if t.get('status') == 'Đang phục vụ')
        lines.append(f"TABLES IN SERVICE NOW: {busy} of {len(tables)} tables.")
    res = _upcoming(db.table_reservations, ctx, 'reserved_time')
    if res:
        guests = sum(int(_num(r.get('party_size')) or 1) for r in res)
        today_n = sum(1 for r in res if str(r.get('reserved_time'))[:10] == ctx.today.isoformat())
        pending = sum(1 for r in res if r.get('status') == 'pending')
        lines.append(f"RESERVATIONS next 7 days: {len(res)} bookings for {guests} guests (today {today_n}; "
                     f"{pending} still waiting for confirmation).")
    else:
        lines.append("RESERVATIONS next 7 days: none.")
    lines.append("COVERS: guest counts are not recorded on bills, so covers and spend per head are known only for reservations.")
    since = (ctx.server_now - timedelta(hours=12)).isoformat()
    waiting = db.kitchen_orders.count_documents({'business_id': ctx.bid, 'status': {'$in': ['pending', 'cooking']},
                                                 'created_at': {'$gte': since}})
    if waiting:
        lines.append(f"KITCHEN: {waiting} tickets waiting or cooking right now.")
    return lines


def _open_minutes(rules, day):
    import booking_rules
    span = booking_rules.hours_on(rules, day)
    if not span:
        return 0
    start, end = span
    return (end + 1440 - start) if end <= start else (end - start)     # mở qua nửa đêm (18:00-02:00)


def _block_karaoke(ctx):
    money, lines = ctx.money, []
    rooms = {r.get('id'): r for r in db.karaoke_rooms.find({'business_id': ctx.bid},
                                                           {'_id': 0, 'id': 1, 'name': 1, 'status': 1, 'price_per_hour': 1})}
    if rooms:
        lines.append(f"ROOMS IN USE NOW: {sum(1 for r in rooms.values() if r.get('status') == 'Đang chơi')} of {len(rooms)} rooms.")
    else:
        lines.append("ROOMS: no karaoke rooms set up yet.")
    sessions = [o for o in ctx.bills30() if _meta(o).get('channel') == 'karaoke']
    if sessions:
        fee_ids = {k for k, p in ctx.products().items() if _is_room_fee(p)}
        time_by, fb_by = defaultdict(float), defaultdict(float)
        for it in ctx.items30():
            (time_by if str(it.get('product_id')) in fee_ids else fb_by)[str(it.get('order_id'))] += _num(it.get('total_price'))
        per = defaultdict(lambda: {'n': 0, 'time': 0.0, 'fb': 0.0, 'hours': 0.0})
        hours_known = True
        for o in sessions:
            oid, rid = str(o.get('id')), _meta(o).get('room_id')
            fb = fb_by.get(oid, 0.0)
            t = time_by[oid] if oid in time_by else max(0.0, _num(o.get('total_amount')) - fb)
            r = per[rid]
            r['n'] += 1
            r['time'] += t
            r['fb'] += fb
            rate = _num((rooms.get(rid) or {}).get('price_per_hour'))
            if rate > 0:
                r['hours'] += t / rate
            elif t > 0:
                hours_known = False
        tot_time = sum(v['time'] for v in per.values())
        tot_fb = sum(v['fb'] for v in per.values())
        tot_h = sum(v['hours'] for v in per.values())
        lines.append(f"ROOM SESSIONS last 30 days: {len(sessions)} sessions, about {tot_h:.1f} room-hours (room-time charge ÷ "
                     f"the room's current hourly rate{'' if hours_known else '; rooms without an hourly rate not counted'}); "
                     f"room time {money(tot_time)}, food & drinks {money(tot_fb)} ({money(tot_fb / len(sessions))} per session).")
        ranked = sorted(per.items(), key=lambda kv: -kv[1]['hours'])[:6]
        lines.append("BY ROOM (30d): " + "; ".join(
            f"{(rooms.get(k) or {}).get('name') or f'Room {k}'} {v['n']} sessions ~{v['hours']:.1f} h, "
            f"{money(v['time'] + v['fb'])}" for k, v in ranked))
        try:
            import booking_rules
            rules = booking_rules.get_rules(ctx.bid)
            if rooms and rules.get('configured'):
                open_min = sum(_open_minutes(rules, ctx.today - timedelta(days=i)) for i in range(30))
                if open_min:
                    lines.append(f"UTILISATION last 30 days: about {_pct(tot_h / (len(rooms) * open_min / 60))} of open "
                                 f"room-hours sold (opening hours from Booking settings).")
            else:
                lines.append("UTILISATION: unknown — opening hours are not set in Booking settings.")
        except Exception:
            pass
    else:
        lines.append("ROOM SESSIONS: no room sessions billed in the last 30 days yet.")
    res = _upcoming(db.karaoke_room_reservations, ctx, 'reserved_time')
    if res:
        today_n = sum(1 for r in res if str(r.get('reserved_time'))[:10] == ctx.today.isoformat())
        lines.append(f"RESERVATIONS next 7 days: {len(res)} bookings (today {today_n}; "
                     f"{sum(1 for r in res if r.get('status') == 'pending')} still waiting for confirmation).")
    else:
        lines.append("RESERVATIONS next 7 days: none.")
    return lines


def _block_hotel(ctx):
    money, lines = ctx.money, []
    rooms = list(db.hotel_rooms.find({'business_id': ctx.bid}, {'_id': 0, 'id': 1, 'status': 1, 'room_type': 1}))
    if rooms:
        occ = sum(1 for r in rooms if r.get('status') == 'Đang ở')
        cleaning = sum(1 for r in rooms if r.get('status') == 'Đang dọn')
        lines.append(f"OCCUPANCY NOW: {occ} of {len(rooms)} rooms occupied ({_pct(occ / len(rooms))}); {cleaning} being cleaned.")
    else:
        lines.append("ROOMS: no hotel rooms set up yet.")
    stays = [o for o in ctx.bills30() if _meta(o).get('channel') == 'hotel']
    if stays:
        nights = sum(_num(_meta(o).get('nights')) for o in stays)
        room_rev = sum(_num(_meta(o).get('room_total')) for o in stays)
        extras = sum(_num(_meta(o).get('extra_charges_total')) for o in stays)
        line = (f"STAYS CHECKED OUT last 30 days: {len(stays)} stays, {nights:g} room-nights, average rate "
                f"{money(room_rev / nights if nights else 0)}/night (room charges only), extras {money(extras)}")
        if rooms:
            line += (f"; occupancy about {_pct(nights / (len(rooms) * 30))} (room-nights checked out ÷ {len(rooms)} rooms × 30 "
                     f"nights — guests still in-house are counted when they check out)")
        lines.append(line + ".")
    else:
        lines.append("STAYS: no check-outs billed in the last 30 days yet.")
    today = ctx.today.isoformat()
    live = {'business_id': ctx.bid, 'status': {'$nin': _CANCELLED}}
    arrivals = list(db.hotel_reservations.find({**live, 'checkin_date': {'$gte': today,
                                                                          '$lt': (ctx.today + timedelta(days=7)).isoformat()}},
                                               {'_id': 0, 'checkin_date': 1, 'status': 1}).limit(500))
    departures = db.hotel_reservations.count_documents({**live, 'checkout_date': today})
    a_today = sum(1 for r in arrivals if str(r.get('checkin_date'))[:10] == today)
    lines.append(f"ARRIVALS (reservations): today {a_today}, next 7 days {len(arrivals)} "
                 f"({sum(1 for r in arrivals if r.get('status') == 'pending')} still pending); departures today {departures}.")
    return lines


def _block_retail(ctx):
    n = db.restock_proposals.count_documents({'business_id': ctx.bid, 'status': 'pending'})
    return [f"RESTOCK SUGGESTIONS waiting for approval: {n} (Inventory page)."] if n else []


def _block_production(ctx):
    lines, today = [], ctx.today
    units, prev = 0.0, 0.0
    by_prod, by_worker, entries = defaultdict(float), defaultdict(float), 0
    usage_rows = []
    for r in db.production_output.find({'business_id': ctx.bid}, {'_id': 0, 'ngay': 1, 'so_luong': 1, 'cong_doan': 1,
                                                                  'ho_ten': 1, 'ma_nv': 1}).sort('id', -1).limit(5000):
        d = _parse_dmy(r.get('ngay'))
        if not d:
            continue
        age = (today - d.date()).days
        qty = _num(r.get('so_luong'))
        if 0 <= age < 30:
            entries += 1
            units += qty
            by_prod[str(r.get('cong_doan') or '?').strip()] += qty
            by_worker[r.get('ho_ten') or r.get('ma_nv') or '?'] += qty
            usage_rows.append(r)
        elif 30 <= age < 60:
            prev += qty
    if entries:
        change = f"{(units - prev) / prev * 100:+.0f}%" if prev else "n/a (nothing logged in the previous 30 days)"
        lines.append(f"OUTPUT last 30 days: {units:g} units in {entries} entries; previous 30 days {prev:g} units; change {change}.")
        lines.append("OUTPUT BY PRODUCT/STAGE (30d): " + "; ".join(
            f"{k} {v:g}" for k, v in sorted(by_prod.items(), key=lambda kv: -kv[1])[:5]))
        lines.append("OUTPUT BY WORKER (30d): " + "; ".join(
            f"{k} {v:g}" for k, v in sorted(by_worker.items(), key=lambda kv: -kv[1])[:5]))
    else:
        lines.append("OUTPUT: no production output logged in the last 30 days yet.")
    mats = {m.get('id'): m for m in db.raw_materials.find({'business_id': ctx.bid}, {'_id': 0, 'id': 1, 'name': 1, 'unit': 1,
                                                                                       'stock_qty': 1})}
    if not mats:
        lines.append("MATERIALS: none tracked yet.")
        return lines
    recipes = {str(r.get('output_name_normalized') or '').strip().lower(): r for r in db.product_recipes.find(
        {'business_id': ctx.bid}, {'_id': 0, 'output_name_normalized': 1, 'materials': 1})}
    used = defaultdict(float)          # NVL đã dùng 30 ngày = sản lượng × định mức công thức (đúng cách app trừ kho)
    for r in usage_rows:
        rec = recipes.get(str(r.get('cong_doan') or '').strip().lower())
        for m in (rec or {}).get('materials') or []:
            used[m.get('material_id')] += _num(m.get('qty_per_unit')) * _num(r.get('so_luong'))
    outs = [m for m in mats.values() if _num(m.get('stock_qty')) <= 0]
    line = f"MATERIALS: {len(mats)} tracked, recipes for {len(recipes)} products."
    if outs:
        line += " Out (at or below zero): " + ", ".join(
            f"{m.get('name')} ({_num(m.get('stock_qty')):g}{' ' + m['unit'] if m.get('unit') else ''})" for m in outs[:8]) + "."
    lines.append(line)
    soon = []
    for mid, qty in used.items():
        m = mats.get(mid)
        stock = _num((m or {}).get('stock_qty'))
        if m and qty > 0 and stock > 0:
            days_left = stock / (qty / 30)
            if days_left <= 14:
                soon.append((days_left, m))
    if soon:
        lines.append("MATERIALS RUNNING OUT (at the last-30-day usage from recipes): " + ", ".join(
            f"{m.get('name')} ~{d:.0f} days left" for d, m in sorted(soon, key=lambda x: x[0])[:8]))
    return lines


def _block_technical(ctx):
    lines, since = [], ctx.today - timedelta(days=29)
    tasks = list(db.tasks.find({'business_id': ctx.bid}, {'_id': 0, 'trang_thai': 1, 'nguoi_nhan': 1, 'completed_at': 1})
                 .limit(5000))
    if not tasks:
        lines.append("JOBS: no jobs recorded yet.")
    else:
        waiting = sum(1 for t in tasks if t.get('trang_thai') == 'Chờ Nhận')
        doing = [t for t in tasks if t.get('trang_thai') == 'Đã Nhận']
        done = [t for t in tasks if t.get('trang_thai') == 'Hoàn Thành' and (_parse_ymd(t.get('completed_at')) or date.min) >= since]
        undated = sum(1 for t in tasks if t.get('trang_thai') == 'Hoàn Thành' and not _parse_ymd(t.get('completed_at')))
        lines.append(f"JOBS: {waiting} waiting for a technician, {len(doing)} in progress, {len(done)} completed in the last 30 days"
                     + (f" ({undated} older completed jobs have no completion date)" if undated else "") + ".")
        per = defaultdict(lambda: [0, 0])
        for t in done:
            per[t.get('nguoi_nhan') or '?'][0] += 1
        for t in doing:
            per[t.get('nguoi_nhan') or '?'][1] += 1
        if per:
            lines.append("TECHNICIANS: " + "; ".join(f"{k} {v[0]} completed (30d), {v[1]} in progress"
                                                     for k, v in sorted(per.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))[:8]))
    parts_orders = [o for o in ctx.bills30() if _meta(o).get('channel') == 'technical_parts']
    if parts_orders:
        lines.append(f"PARTS BILLED last 30 days: {ctx.money(sum(_num(o.get('total_amount')) for o in parts_orders))} on "
                     f"{len(parts_orders)} jobs (labour charges are not recorded in BitPaw, so revenue covers parts only).")
    parts = list(db.tech_parts.find({'business_id': ctx.bid}, {'_id': 0, 'name': 1, 'stock': 1}))
    if parts:
        crit = tools.critical_stock(ctx.bid)
        low = sorted((p for p in parts if _num(p.get('stock')) <= crit), key=lambda p: _num(p.get('stock')))
        lines.append(f"PARTS: {len(parts)} tracked" + ("; at or below your critical level {:g}: ".format(crit) + ", ".join(
            f"{p.get('name')} ({_num(p.get('stock')):g} left)" for p in low[:8]) if low else "; none running low") + ".")
    else:
        lines.append("PARTS: none tracked yet.")
    return lines


def _block_office(ctx):
    lines, today = [], ctx.today
    emps = {e['ma_nv']: e.get('ho_ten') or e['ma_nv'] for e in db.employees.find(
        {'business_id': ctx.bid}, {'_id': 0, 'ma_nv': 1, 'ho_ten': 1}) if e.get('ma_nv')}
    rows, hours, ot, people, recent = 0, 0.0, 0.0, set(), set()
    for r in db.chamcong.find({'business_id': ctx.bid}, {'_id': 0, 'ma_nv': 1, 'ngay_cham': 1, 'so_gio': 1, 'tang_ca': 1}) \
            .sort('id', -1).limit(5000):
        d = _parse_dmy(r.get('ngay_cham'))
        if not d:
            continue
        age = (today - d.date()).days
        if 0 <= age < 30:
            rows += 1
            hours += _num(r.get('so_gio'))
            ot += _num(r.get('tang_ca'))
            people.add(r.get('ma_nv'))
            if age < 7:
                recent.add(r.get('ma_nv'))
    if rows:
        lines.append(f"TIMESHEETS last 30 days: {rows} days logged by {len(people)} of {len(emps)} staff, {hours:g} hours "
                     f"(+{ot:g} overtime).")
        missing = [n for k, n in emps.items() if k not in recent]
        if missing:
            lines.append("NO TIMESHEET in the last 7 days: " + ", ".join(missing[:8]))
    else:
        lines.append("TIMESHEETS: no attendance logged in the last 30 days yet.")
    pending = list(db.leave_requests.find({'business_id': ctx.bid, 'status': 'pending'}, {'_id': 0, 'ho_ten': 1, 'from_date': 1,
                                                                                           'to_date': 1}).limit(50))
    week_end = (today + timedelta(days=6)).isoformat()
    on_leave = [r for r in db.leave_requests.find({'business_id': ctx.bid, 'status': 'approved', 'from_date': {'$lte': week_end}},
                                                   {'_id': 0, 'ho_ten': 1, 'from_date': 1, 'to_date': 1}).limit(200)
                if str(r.get('to_date') or r.get('from_date') or '') >= today.isoformat()]
    line = f"LEAVE: {len(pending)} requests waiting for approval"
    if pending:
        line += " (" + ", ".join(f"{r.get('ho_ten')} {r.get('from_date')}..{r.get('to_date')}" for r in pending[:6]) + ")"
    line += "; on approved leave in the next 7 days: " + (", ".join(
        f"{r.get('ho_ten')} {r.get('from_date')}..{r.get('to_date')}" for r in on_leave[:8]) if on_leave else "nobody") + "."
    lines.append(line)
    claims = list(db.expense_requests.find({'business_id': ctx.bid, 'status': 'pending'}, {'_id': 0, 'amount': 1}).limit(500))
    lines.append(f"EXPENSE CLAIMS waiting for approval: {len(claims)}"
                 + (f" totalling {ctx.money(sum(_num(c.get('amount')) for c in claims))}" if claims else "") + ".")
    return lines


# Khối số liệu theo ngành (thứ tự = thứ tự trong prompt). Lịch hẹn + hoa hồng thợ CHỈ cho nail/spa.
INDUSTRY_BLOCKS = {
    'nail': [_block_revenue, _block_items, _block_appointments, _block_staff, _block_customers],
    'spa': [_block_revenue, _block_items, _block_appointments, _block_staff, _block_customers],
    'fnb': [_block_revenue, _block_fnb, _block_items, _block_staff, _block_customers],
    'karaoke': [_block_revenue, _block_karaoke, _block_items, _block_staff, _block_customers],
    'hotel': [_block_revenue, _block_hotel, _block_items, _block_staff, _block_customers],
    'retail': [_block_revenue, _block_items, _block_retail, _block_staff, _block_customers],
    'production': [_block_revenue, _block_production, _block_staff],
    'technical': [_block_revenue, _block_technical, _block_staff, _block_customers],
    'office': [_block_office, _block_revenue],
}
_GENERIC_BLOCKS = [_block_revenue, _block_items, _block_staff, _block_customers]


def business_snapshot(business_id, industry_code=None, now=None):
    """Số liệu thật, ngắn gọn (để nhúng vào prompt), THEO NGÀNH — xem INDUSTRY_BLOCKS. `now` = giờ hiện tại của tiệm
    (mặc định booking_rules.local_now); truyền `now` (test) thì coi giờ máy chủ = giờ tiệm. Mỗi khối tự bắt lỗi riêng.
    Trả (văn bản, tên tiệm, mã ngành)."""
    biz = db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'currency': 1, 'country': 1, 'industry_code': 1}) or {}
    cur = tools.business_currency(business_id, biz)
    code = _industry(industry_code, biz)
    if now is None:
        now = tools._tz_now(business_id)
        offset = datetime.now() - now
    else:
        offset = timedelta(0)
    ctx = _Ctx(business_id, code, now, offset, tools.money_formatter(cur))
    lines = [f"BUSINESS: {biz.get('name') or 'this business'} — {INDUSTRY_LABEL.get(code, 'business')}"
             f"{f' (industry {code})' if code else ''}, currency {cur}.",
             f"TODAY (shop local time): {now.strftime('%A %d/%m/%Y %H:%M')}"]
    for block in INDUSTRY_BLOCKS.get(code, _GENERIC_BLOCKS):
        try:
            lines.extend(block(ctx) or [])
        except Exception as e:  # 1 khối lỗi không làm hỏng cả bảng tóm tắt
            print(f"[ai_copilot] snapshot block {block.__name__} failed for {business_id}: {e}")
    if code in INDUSTRY_NOTE:
        lines.append(INDUSTRY_NOTE[code])
    return "\n".join(lines), biz.get('name') or '', code


def insight_messages(snapshot, question, lang):
    language = 'Vietnamese' if lang == 'vi' else 'English'
    system = (
        "You are the private business advisor of the OWNER of the business described below — not a customer-facing "
        "bot and not a software salesperson. Only the owner reads your answer.\n"
        "Base every recommendation on the real numbers below; quote them. If a number needed is missing, say what to "
        "track instead of inventing it. Never invent services, prices, staff or customers.\n"
        f"Answer in {language}. Format: a one-line diagnosis, then 3-5 numbered concrete actions for this week, "
        "EACH ACTION ON ITS OWN LINE (who / what / when, with a ready-to-send customer message when relevant). "
        "Max ~180 words. Plain text, no markdown tables or headings.\n\nBUSINESS DATA:\n" + snapshot)
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': question}]


def agent_messages(snapshot, question, lang, today_line):
    """Copilot dạng trợ lý dữ liệu (Pha 27): có công cụ tra số thật — xem ai_copilot_tools.COPILOT_TOOLS."""
    language = 'Vietnamese' if lang == 'vi' else 'English'
    system = (
        "You are the private business copilot of the OWNER of the business below (only the owner reads this). You have "
        "read-only tools over the real data: sales_report, appointments_on, customer_lookup, lapsed_customers, staff_report, "
        "roster_week, stock_status, packages_summary, inbox_status.\n"
        "RULES:\n- Every number, date, name or list must come from a tool result or from a line of the BUSINESS SNAPSHOT below "
        "(the snapshot is computed from the live database for the period each line names — quote it with that period). "
        "Never estimate or invent. For any other period, breakdown or lookup, call a tool; use several tools if the "
        "question needs it (e.g. compare this week vs last week = two sales_report calls).\n"
        "- appointments_on, packages_summary and the commission / POS-client figures of staff_report only fit nail and spa "
        "salons: if the snapshot's NOTE line says they do not apply, do not use them for this business.\n"
        "- If the data simply isn't there, say exactly what is missing and how to start tracking it.\n"
        "- Periods are in the business's local time; money is already formatted in its currency — copy it as given.\n"
        f"- Answer in {language}. Start with the direct answer in 1-2 lines with the key numbers.\n"
        "- Match the length to the question: a lookup (\"how much yesterday\", \"who is booked tomorrow\", \"how many packages\") "
        "gets the answer plus at most ONE short tip that is about that same thing. Only open questions (\"how is business\", "
        "\"what should I do\", \"how do I fill quiet days\") get up to 3 numbered actions for this week (who / what / when; "
        "a ready-to-send customer message only when it is the point). Max ~120 words; plain text, no tables or headings.\n"
        "- Don't repeat the same advice in every answer (e.g. the same lapsed customers) unless the question is about it. "
        "If you notice test or odd data (names like \"QA\", \"Test\", a bill with no service), say it once, briefly.\n"
        "- You cannot change data (no refunds, bookings or price changes) — suggest where in BitPaw the owner can do it.\n\n"
        f"{today_line}\nBUSINESS SNAPSHOT (live figures for the periods stated; use tools for anything else):\n{snapshot}")
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': question}]


def reply_messages(snapshot, booking_facts, conversation, lang_hint=None):
    system = (
        "You draft the NEXT message the salon/business staff will send to this customer. The staff member reviews and "
        "edits it before sending — write only the message itself, no notes, no quotes.\n"
        "Reply in the customer's language. Warm, brief (under 300 characters), helpful. Use only real services, prices "
        "and times from the data below. If the customer wants to book, confirm service + date/time and ask for any "
        "missing detail; never claim a booking is made — staff will do it.\n\nBUSINESS DATA:\n" + snapshot +
        ("\n\n" + booking_facts if booking_facts else ""))
    msgs = [{'role': 'system', 'content': system}]
    for m in conversation[-12:]:
        role = 'user' if m.get('sender_type') == 'customer' else 'assistant'
        text = str(m.get('content') or '').strip()
        if text:
            msgs.append({'role': role, 'content': text[:1500]})
    if len(msgs) == 1 or msgs[-1]['role'] != 'user':
        msgs.append({'role': 'user', 'content': '(Write a friendly follow-up message to this customer.)'})
    return msgs
