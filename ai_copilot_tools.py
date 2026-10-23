"""
Công cụ CHỈ ĐỌC cho AI Copilot của chủ tiệm (Pha 27) — AI hỏi gì tra nấy từ dữ liệu thật thay vì chỉ nhìn 1 bảng tóm tắt
cố định (giống Shopify Sidekick / Square AI: "doanh thu thứ 7 tuần trước?", "Chloe tháng này được bao nhiêu hoa hồng?",
"mai có bao nhiêu lịch?", "khách Linh lần cuối tới khi nào?"). Mọi hàm lọc theo business_id lấy từ phiên đăng nhập.
"""
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from mongo_client import db
from currency_utils import format_money
import booking_rules

REVENUE_STATUSES = ['completed', 'paid', 'partially_refunded', 'refunded']


def _fn(name, desc, props, required=()):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props, "required": list(required)}}}


PERIOD = {"type": "string", "description": "today | yesterday | this_week | last_week | this_month | last_month | last_7_days | "
                                         "last_30_days | YYYY-MM-DD (1 ngày) | YYYY-MM-DD..YYYY-MM-DD (khoảng ngày)"}
COPILOT_TOOLS = [
    _fn("sales_report", "Doanh thu ròng (đã trừ hoàn tiền), số bill, bill trung bình trong 1 kỳ; group_by để xem theo ngày/dịch vụ/thợ/cách thanh toán.",
        {"period": PERIOD, "group_by": {"type": "string", "enum": ["none", "day", "service", "staff", "payment"]}}, ["period"]),
    _fn("appointments_on", "Lịch hẹn trong 1 ngày hoặc khoảng ngày (giờ, khách, dịch vụ, thợ, trạng thái).", {"period": PERIOD}, ["period"]),
    _fn("customer_lookup", "Tra khách theo tên hoặc số điện thoại: tổng chi, điểm, hạng, lần cuối tới, lịch sắp tới, gói liệu trình.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("lapsed_customers", "Khách đã từng chi tiêu nhưng lâu chưa quay lại (mặc định 45 ngày), xếp theo tổng chi.",
        {"days": {"type": "integer"}, "limit": {"type": "integer"}}),
    _fn("staff_report", "Theo từng nhân viên trong kỳ: hoa hồng/doanh số từ POS, số khách, giờ theo lịch ca, số lần đi trễ/vắng so với ca đã công bố.",
        {"period": PERIOD}, ["period"]),
    _fn("roster_week", "Lịch ca của 1 tuần (đã công bố/nháp), khung còn thiếu người, ước tính chi phí lương.",
        {"week_of": {"type": "string", "description": "Ngày bất kỳ trong tuần, YYYY-MM-DD (bỏ trống = tuần này)."}}),
    _fn("stock_status", "Hàng sắp hết (dưới ngưỡng), hàng không bán được 30 ngày, đề xuất nhập hàng đang chờ.", {}),
    _fn("packages_summary", "Gói liệu trình đang có hiệu lực: số buổi khách còn treo (nghĩa vụ phục vụ), gói sắp hết hạn.", {}),
    _fn("inbox_status", "Hộp thư khách (AI Bot): hội thoại chờ nhân viên trả lời, khách vừa phàn nàn.", {}),
]


def _tz_now(bid):
    return booking_rules.local_now(bid)


def _range(bid, period):
    """(start_local, end_local, label) theo giờ của tiệm."""
    now = _tz_now(bid)
    today = now.date()
    p = str(period or 'today').strip().lower()
    m = re.match(r'^(\d{4}-\d{2}-\d{2})(?:\.\.(\d{4}-\d{2}-\d{2}))?$', p)
    if m:
        a = datetime.strptime(m.group(1), '%Y-%m-%d').date()
        b = datetime.strptime(m.group(2), '%Y-%m-%d').date() if m.group(2) else a
        return a, b + timedelta(days=1), f"{a}..{b}"
    if p == 'yesterday':
        a = today - timedelta(days=1)
        return a, today, str(a)
    if p == 'this_week':
        a = today - timedelta(days=today.weekday())
        return a, today + timedelta(days=1), f"this week (from {a})"
    if p == 'last_week':
        a = today - timedelta(days=today.weekday() + 7)
        return a, a + timedelta(days=7), f"last week ({a}..{a + timedelta(days=6)})"
    if p == 'this_month':
        a = today.replace(day=1)
        return a, today + timedelta(days=1), f"this month (from {a})"
    if p == 'last_month':
        first = today.replace(day=1)
        a = (first - timedelta(days=1)).replace(day=1)
        return a, first, f"last month ({a:%Y-%m})"
    if p in ('last_7_days', 'last_30_days'):
        n = 7 if '7' in p else 30
        return today - timedelta(days=n - 1), today + timedelta(days=1), f"last {n} days"
    return today, today + timedelta(days=1), str(today)


def _server_iso(bid, d):
    """Mốc ngày giờ địa phương của tiệm -> chuỗi giờ máy chủ (created_at của đơn lưu theo giờ máy chủ)."""
    from zoneinfo import ZoneInfo
    local_now = _tz_now(bid)
    offset = datetime.now() - local_now  # chênh lệch giờ máy chủ - giờ tiệm
    return (datetime.combine(d, datetime.min.time()) + offset).isoformat()


def _money(bid):
    cur = (db.businesses.find_one({'id': bid}, {'_id': 0, 'currency': 1}) or {}).get('currency') or 'USD'
    return lambda v: format_money(v or 0, cur)


def sales_report(bid, period='today', group_by='none'):
    a, b, label = _range(bid, period)
    money = _money(bid)
    q = {'business_id': bid, 'status': {'$in': REVENUE_STATUSES}, 'created_at': {'$gte': _server_iso(bid, a), '$lt': _server_iso(bid, b)}}
    orders = list(db.orders.find(q, {'_id': 0, 'id': 1, 'total_amount': 1, 'payment_method': 1, 'created_at': 1, 'metadata.payment_bucket': 1}))
    total = sum(float(o.get('total_amount') or 0) for o in orders)
    bills = [o for o in orders if float(o.get('total_amount') or 0) > 0]
    out = {"period": label, "net_revenue": money(total), "bills": len(bills), "avg_bill": money(total / len(bills) if bills else 0)}
    g = (group_by or 'none').lower()
    if g == 'day':
        offset = datetime.now() - _tz_now(bid)
        by = defaultdict(float)
        for o in orders:
            try:
                by[(datetime.fromisoformat(str(o['created_at'])[:19]) - offset).date().isoformat()] += float(o.get('total_amount') or 0)
            except ValueError:
                pass
        out["by_day"] = {k: money(v) for k, v in sorted(by.items())}
    elif g == 'payment':
        by = defaultdict(float)
        for o in orders:
            by[(o.get('payment_method') or 'cash').lower()] += float(o.get('total_amount') or 0)
        out["by_payment"] = {k: money(v) for k, v in sorted(by.items(), key=lambda kv: -kv[1])}
    elif g in ('service', 'staff'):
        ids = [o['id'] for o in bills]
        ids_any = ids + [int(i) for i in ids if str(i).isdigit()] + [str(i) for i in ids]
        by = defaultdict(lambda: [0.0, 0])
        if g == 'service':
            names = {str(p['id']): p['name'] for p in db.products.find({'business_id': bid}, {'_id': 0, 'id': 1, 'name': 1})}
            for it in db.order_items.find({'order_id': {'$in': ids_any}}, {'_id': 0, 'product_id': 1, 'quantity': 1, 'total_price': 1}):
                k = names.get(str(it.get('product_id')), f"#{it.get('product_id')}")
                by[k][0] += float(it.get('total_price') or 0)
                by[k][1] += int(it.get('quantity') or 1)
            out["by_service"] = [{"service": k, "revenue": money(v[0]), "qty": v[1]} for k, v in sorted(by.items(), key=lambda kv: -kv[1][0])[:15]]
        else:
            out["by_staff"] = staff_report(bid, period).get('staff')
    return out


def appointments_on(bid, period='today'):
    a, b, label = _range(bid, period)
    names = booking_rules._staff_names(bid)
    svc = {str(p['id']): p['name'] for p in db.products.find({'business_id': bid}, {'_id': 0, 'id': 1, 'name': 1})}
    rows = []
    for x in db.appointments.find({'business_id': bid, 'book_time': {'$gte': a.isoformat(), '$lt': b.isoformat()}},
                                  {'_id': 0}).sort('book_time', 1).limit(80):
        rows.append({"time": str(x.get('book_time'))[:16].replace('T', ' '), "customer": x.get('customer_name'),
                     "service": svc.get(str(x.get('service_id')), x.get('service_name')), "staff": names.get(str(x.get('staff_id'))) or 'any',
                     "status": x.get('status'), "source": x.get('source')})
    live = [r for r in rows if r['status'] not in ('cancelled', 'canceled')]
    return {"period": label, "count": len(live), "cancelled": len(rows) - len(live), "appointments": rows[:60]}


def customer_lookup(bid, query=''):
    q = str(query or '').strip()
    if len(q) < 2:
        return {"error": "Query too short."}
    digits = re.sub(r'\D', '', q)
    cond = [{'name': {'$regex': re.escape(q), '$options': 'i'}}]
    if len(digits) >= 4:
        cond.append({'phone': {'$regex': digits[-6:]}})
    money = _money(bid)
    out = []
    for c in db.customers.find({'business_id': bid, '$or': cond}, {'_id': 0}).limit(5):
        phone = c.get('phone') or ''
        upcoming = db.appointments.count_documents({'business_id': bid, 'customer_phone': phone, 'status': {'$nin': ['cancelled', 'canceled']},
                                                    'book_time': {'$gte': _tz_now(bid).strftime('%Y-%m-%dT%H:%M')}})
        pk = list(db.customer_packages.find({'business_id': bid, 'customer_phone': re.sub(r'[^\d+]', '', phone), 'sessions_left': {'$gt': 0}},
                                            {'_id': 0, 'name': 1, 'sessions_left': 1}))
        out.append({"name": c.get('name'), "phone": phone, "total_spent": money(float(c.get('total_spent') or 0)),
                    "points": c.get('loyalty_points'), "tier": c.get('tier'), "last_visit": str(c.get('last_purchase_at') or '')[:10] or None,
                    "upcoming_appointments": upcoming, "packages": pk, "notes": (c.get('ai_notes') or '')[:200]})
    return {"matches": out}


def lapsed_customers(bid, days=45, limit=10):
    days = max(14, min(int(days or 45), 365))
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    money = _money(bid)
    rows = list(db.customers.find({'business_id': bid, 'last_purchase_at': {'$lt': cutoff}}, {'_id': 0, 'name': 1, 'phone': 1, 'total_spent': 1, 'last_purchase_at': 1}))
    rows.sort(key=lambda c: -float(c.get('total_spent') or 0))
    return {"days": days, "count": len(rows), "top": [{"name": c.get('name'), "spent": money(float(c.get('total_spent') or 0)),
                                                       "last_visit": str(c.get('last_purchase_at'))[:10]} for c in rows[:max(1, min(int(limit or 10), 25))]]}


def staff_report(bid, period='this_month'):
    a, b, label = _range(bid, period)
    money = _money(bid)
    emps = {e['ma_nv']: e.get('ho_ten') or e['ma_nv'] for e in db.employees.find({'business_id': bid}, {'_id': 0, 'ma_nv': 1, 'ho_ten': 1}) if e.get('ma_nv')}
    per = defaultdict(lambda: {'commission': 0.0, 'tips': 0.0, 'clients': 0, 'hours_rostered': 0.0, 'late': 0, 'late_min': 0, 'no_show': 0})
    d = a
    while d < b:
        for r in db.chamcong.find({'business_id': bid, 'ngay_cham': d.strftime('%d/%m/%Y')}, {'_id': 0, 'ma_nv': 1, 'tien_tua': 1, 'tien_tips': 1, 'ghi_chu': 1}):
            if r.get('ma_nv') in emps and ('Order #' in str(r.get('ghi_chu') or '') or float(r.get('tien_tua') or 0)):
                per[r['ma_nv']]['commission'] += float(r.get('tien_tua') or 0)
                per[r['ma_nv']]['tips'] += float(r.get('tien_tips') or 0)
                per[r['ma_nv']]['clients'] += 1
        d += timedelta(days=1)
    try:
        import shift_roster
        for s in db.roster_shifts.find({'business_id': bid, 'status': 'published', 'date': {'$gte': a.isoformat(), '$lt': b.isoformat()}}, {'_id': 0}):
            if s['ma_nv'] in emps:
                per[s['ma_nv']]['hours_rostered'] += shift_roster.shift_hours(s['start'], s['end'])
        wk = a - timedelta(days=a.weekday())
        while wk < b:
            rows, _ = shift_roster.attendance(bid, wk)
            for r in rows:
                if a.isoformat() <= r['date'] < b.isoformat() and r['ma_nv'] in emps:
                    if r['status'] == 'late':
                        per[r['ma_nv']]['late'] += 1
                        per[r['ma_nv']]['late_min'] += r['late_min'] or 0
                    elif r['status'] == 'no_show':
                        per[r['ma_nv']]['no_show'] += 1
            wk += timedelta(days=7)
    except Exception:
        pass
    staff = [{"name": emps[k], "commission": money(v['commission']), "tips": money(v['tips']), "pos_clients": v['clients'],
              "rostered_hours": round(v['hours_rostered'], 1), "late_times": v['late'], "late_minutes": v['late_min'], "no_shows": v['no_show']}
             for k, v in sorted(per.items(), key=lambda kv: -kv[1]['commission'])]
    return {"period": label, "staff": staff, "staff_without_activity": [n for k, n in emps.items() if k not in per][:15]}


def roster_week(bid, week_of=None):
    import shift_roster
    ws = shift_roster.week_start(week_of)
    shifts = shift_roster._week_shifts(bid, ws)
    needs, _ = shift_roster._needs(bid)
    cov = shift_roster.coverage(needs, shifts, ws)
    by = defaultdict(float)
    for s in shifts:
        by[s.get('ho_ten') or s['ma_nv']] += shift_roster.shift_hours(s['start'], s['end'])
    return {"week_start": ws.isoformat(), "shifts": len(shifts), "drafts": sum(1 for s in shifts if s.get('status') == 'draft'),
            "hours_by_person": {k: round(v, 1) for k, v in sorted(by.items(), key=lambda kv: -kv[1])},
            "understaffed": [{"date": c['date'], "time": f"{c['start']}-{c['end']}", "missing": c['short']} for c in cov if c['short']]}


def stock_status(bid):
    import messaging
    low = messaging.low_stock(bid)
    sold30 = set()
    since = (datetime.now() - timedelta(days=30)).isoformat()
    ids = [o['id'] for o in db.orders.find({'business_id': bid, 'created_at': {'$gte': since}}, {'_id': 0, 'id': 1}).limit(5000)]
    ids_any = ids + [int(i) for i in ids if str(i).isdigit()] + [str(i) for i in ids]
    for it in db.order_items.find({'order_id': {'$in': ids_any}}, {'_id': 0, 'product_id': 1}):
        sold30.add(str(it.get('product_id')))
    idle = [p['name'] for p in db.products.find({'business_id': bid, 'is_active': {'$in': [1, True]}, 'stock': {'$exists': True, '$gt': 0, '$lt': 900}},
                                                {'_id': 0, 'id': 1, 'name': 1}) if str(p['id']) not in sold30][:10]
    sugg = list(db.restock_proposals.find({'business_id': bid, 'status': 'pending'}, {'_id': 0, 'product_name': 1, 'suggested_qty': 1}).limit(10)) \
        if 'restock_proposals' in db.list_collection_names() else []
    return {"low_stock": low[:15], "not_sold_30_days": idle, "pending_restock_suggestions": sugg}


def packages_summary(bid):
    now = datetime.now().isoformat()
    rows = list(db.customer_packages.find({'business_id': bid, 'sessions_left': {'$gt': 0}, '$or': [{'expires_at': None}, {'expires_at': {'$gt': now}}]}, {'_id': 0}))
    money = _money(bid)
    owed = sum(r['sessions_left'] * float(r.get('session_value') or 0) for r in rows)
    soon = [r for r in rows if r.get('expires_at') and r['expires_at'] < (datetime.now() + timedelta(days=30)).isoformat()]
    return {"active_packages": len(rows), "sessions_owed": sum(r['sessions_left'] for r in rows), "value_of_sessions_owed": money(owed),
            "expiring_within_30_days": [{"customer": r.get('customer_name') or r['customer_phone'], "package": r['name'], "left": r['sessions_left'],
                                         "expires": r['expires_at'][:10]} for r in soon[:10]]}


def inbox_status(bid):
    pref = {'$regex': f'^{re.escape(bid)}:'}
    waiting = list(db.bot_customers.find({'id': pref, 'needs_human': True},
                                         {'_id': 0, 'full_name': 1, 'handoff_reason': 1, 'handoff_at': 1}).sort('handoff_at', -1).limit(10))
    return {"waiting_for_staff": waiting, "count": len(waiting)}


DISPATCH = {"sales_report": sales_report, "appointments_on": appointments_on, "customer_lookup": customer_lookup,
            "lapsed_customers": lapsed_customers, "staff_report": staff_report, "roster_week": roster_week,
            "stock_status": stock_status, "packages_summary": packages_summary, "inbox_status": inbox_status}


def run_tool(bid, tool_call):
    name = (tool_call.get('function') or {}).get('name')
    try:
        args = json.loads((tool_call.get('function') or {}).get('arguments') or '{}')
    except ValueError:
        args = {}
    fn = DISPATCH.get(name)
    if not fn:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        return json.dumps(fn(bid, **args), ensure_ascii=False, default=str)[:12000]
    except TypeError as e:
        return json.dumps({"error": f"bad arguments: {e}"})
    except Exception as e:
        return json.dumps({"error": f"tool failed: {str(e)[:200]}"})
