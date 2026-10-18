"""AI Copilot cho CHỦ TIỆM (trang /ai_bot) — tách hẳn 2 việc trước đây bị trộn chung 1 ô nhập:

  1. "reply"   — soạn SẴN câu trả lời cho tin nhắn mới nhất của khách (chủ tiệm xem, sửa rồi mới gửi).
  2. "insight" — tư vấn RIÊNG cho chủ tiệm (doanh thu, giữ chân khách, kho, xếp thợ...) dựa trên số liệu
                 thật của tiệm. Khách KHÔNG BAO GIỜ thấy phần này.

BUG THẬT đã vá (đóng vai chủ tiệm, 10/2026): 4 nút "Revenue/Customer Care/Inventory/Staffing Tips" trước đây
gửi NGUYÊN câu hỏi nội bộ ("Suggest a revenue-boosting campaign for this week?") cho KHÁCH như 1 tin nhắn của
tiệm, rồi AI trả lời với vai "BitPaw AI Advisor" (tư vấn bán phần mềm) — sai người nhận, sai vai.

Dữ liệu chỉ đọc theo business_id lấy từ session (route gọi module này có @login_required).
"""
from collections import defaultdict
from datetime import datetime, timedelta

from mongo_client import db
from currency_utils import format_money

INDUSTRY_LABEL = {
    'nail': 'nail salon', 'spa': 'spa / beauty salon', 'fnb': 'restaurant / cafe', 'karaoke': 'karaoke & billiards venue',
    'hotel': 'hotel / homestay', 'retail': 'retail store', 'production': 'production workshop',
    'technical': 'field technical services company', 'office': 'office / HR team',
}

INSIGHT_TOPICS = {
    'revenue': "How can I grow revenue in the next 7 days? Give concrete promotions/upsells based on my best and weakest services.",
    'retention': "Which customers should I win back and exactly what message/offer should I send them?",
    'inventory': "Review my stock/products: what is running low, what is not selling, what should I reorder, bundle or discount?",
    'staffing': "How should I schedule and motivate my staff this week based on bookings and their performance?",
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


def business_snapshot(business_id, industry_code=None, now=None):
    """Số liệu thật, ngắn gọn (để nhúng vào prompt): doanh thu 30 ngày so với 30 ngày trước, dịch vụ bán chạy /
    bán chậm, lịch hẹn, thợ, khách lâu chưa quay lại, hàng sắp hết. Mỗi khối tự bắt lỗi riêng."""
    now = now or datetime.now()
    biz = db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'currency': 1, 'industry_code': 1}) or {}
    cur = biz.get('currency') or 'VND'
    code = industry_code or biz.get('industry_code') or ''
    money = lambda v: format_money(v, cur)  # noqa: E731
    lines = [f"BUSINESS: {biz.get('name') or 'this business'} — {INDUSTRY_LABEL.get(code, code or 'business')}, currency {cur}.",
             f"TODAY: {now.strftime('%A %d/%m/%Y %H:%M')}"]
    d30, d60 = (now - timedelta(days=30)).isoformat(), (now - timedelta(days=60)).isoformat()

    try:
        def rev(frm, to):
            r = list(db.orders.aggregate([
                {'$match': {'business_id': business_id, 'created_at': {'$gte': frm, '$lt': to}}},
                {'$group': {'_id': None, 's': {'$sum': {'$toDouble': '$total_amount'}}, 'n': {'$sum': 1}}}]))
            return (r[0]['s'], r[0]['n']) if r else (0, 0)
        cur_rev, cur_n = rev(d30, now.isoformat())
        prev_rev, prev_n = rev(d60, d30)
        change = f"{(cur_rev - prev_rev) / prev_rev * 100:+.0f}%" if prev_rev else "n/a"
        avg = cur_rev / cur_n if cur_n else 0
        lines.append(f"REVENUE last 30 days: {money(cur_rev)} from {cur_n} bills (avg {money(avg)}/bill); "
                     f"previous 30 days {money(prev_rev)} from {prev_n} bills; change {change}.")
    except Exception:
        pass

    try:
        recent_ids = [o['id'] for o in db.orders.find(
            {'business_id': business_id, 'created_at': {'$gte': d30}}, {'id': 1, '_id': 0}).limit(5000)]
        by_prod = defaultdict(lambda: [0.0, 0])
        for it in db.order_items.find({'business_id': business_id, 'order_id': {'$in': recent_ids}},
                                      {'product_id': 1, 'quantity': 1, 'total_price': 1, '_id': 0}):
            p = by_prod[str(it.get('product_id'))]
            p[0] += _num(it.get('total_price'))
            p[1] += int(_num(it.get('quantity')) or 1)
        products = {str(p['id']): p for p in db.products.find(
            {'business_id': business_id}, {'_id': 0, 'id': 1, 'name': 1, 'price': 1, 'stock': 1, 'is_active': 1,
                                           'category': 1, 'cost_price': 1})}
        ranked = sorted(by_prod.items(), key=lambda kv: -kv[1][0])
        named = [(products[k]['name'], v) for k, v in ranked if k in products]
        if named:
            lines.append("TOP SELLERS (30d): " + "; ".join(f"{n} {money(v[0])} ({v[1]} sold)" for n, v in named[:5]))
        sold = {k for k, _ in ranked}
        idle = [p['name'] for k, p in products.items() if str(p.get('is_active')) in ('1', 'True') and k not in sold]
        if idle:
            lines.append("NOT SOLD IN 30 DAYS: " + ", ".join(idle[:8]))
        low = [f"{p['name']} ({int(_num(p.get('stock')))} left)" for p in products.values()
               if p.get('stock') is not None and _num(p.get('stock')) <= 5 and str(p.get('is_active')) in ('1', 'True')]
        if low:
            lines.append("LOW STOCK: " + ", ".join(low[:8]))
        margins = [(p['name'], _num(p.get('price')) - _num(p.get('cost_price'))) for p in products.values()
                   if p.get('cost_price') is not None and _num(p.get('price'))]
        if margins:
            best = sorted(margins, key=lambda x: -x[1])[:3]
            lines.append("HIGHEST MARGIN ITEMS: " + ", ".join(f"{n} (+{money(m)})" for n, m in best))
    except Exception:
        pass

    try:
        upcoming = db.appointments.count_documents({'business_id': business_id, 'status': {'$nin': ['cancelled', 'canceled']},
                                                    'book_time': {'$gte': now.strftime('%Y-%m-%dT%H:%M'),
                                                                  '$lt': (now + timedelta(days=7)).strftime('%Y-%m-%d')}})
        lines.append(f"APPOINTMENTS booked for the next 7 days: {upcoming}.")
    except Exception:
        pass

    try:
        emps = {e['ma_nv']: e.get('ho_ten') or e['ma_nv'] for e in db.employees.find(
            {'business_id': business_id}, {'_id': 0, 'ma_nv': 1, 'ho_ten': 1}) if e.get('ma_nv')}
        perf = defaultdict(lambda: [0.0, 0])
        for r in db.chamcong.find({'business_id': business_id, 'ghi_chu': {'$regex': 'Order #'}},
                                  {'_id': 0, 'ma_nv': 1, 'ngay_cham': 1, 'tien_tua': 1}).sort('id', -1).limit(3000):
            d = _parse_dmy(r.get('ngay_cham'))
            if d and d >= now - timedelta(days=30) and r.get('ma_nv') in emps:
                perf[r['ma_nv']][0] += _num(r.get('tien_tua'))
                perf[r['ma_nv']][1] += 1
        staff_line = f"STAFF: {len(emps)} people."
        if perf:
            staff_line += " Commission earned last 30d: " + "; ".join(
                f"{emps[k]} {money(v[0])} ({v[1]} clients)" for k, v in sorted(perf.items(), key=lambda kv: -kv[1][0]))
            quiet = [emps[k] for k in emps if k not in perf]
            if quiet:
                staff_line += ". No POS sales in 30d: " + ", ".join(quiet[:6])
        lines.append(staff_line)
    except Exception:
        pass

    try:
        cutoff = (now - timedelta(days=45)).isoformat()
        total = db.customers.count_documents({'business_id': business_id})
        lapsed = list(db.customers.find({'business_id': business_id, 'last_purchase_at': {'$lt': cutoff}},
                                        {'_id': 0, 'name': 1, 'total_spent': 1, 'last_purchase_at': 1})
                      .sort('total_spent', -1).limit(5))
        line = f"CUSTOMERS: {total} saved."
        if lapsed:
            line += " High-value customers not back for 45+ days: " + "; ".join(
                f"{c.get('name')} (spent {money(c.get('total_spent'))}, last visit {str(c.get('last_purchase_at'))[:10]})"
                for c in lapsed)
        lines.append(line)
    except Exception:
        pass
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
