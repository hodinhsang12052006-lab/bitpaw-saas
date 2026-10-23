"""
Chủ tiệm hỏi AI Copilot 40 câu (Việt + Anh, kiểu gõ vội) — đối chiếu với SỐ ĐÚNG do script tự tính thẳng từ Mongo
(không dùng chung code với Copilot), rồi giám khảo chấm thêm phần tư vấn.
    python scripts/ai_sim/sim_copilot.py --tag baseline
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_core import BASE, browser_session, csrf_from, db, ds  # noqa: E402

EMAIL, PW = 'demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!'
BIZ = '000b2c16-ab4e-42bd-944a-29c925cad09b'
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'audit-results', 'ai_sim')
STATUSES = ['completed', 'paid', 'partially_refunded', 'refunded']


def local_now():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo('Australia/Sydney')).replace(tzinfo=None)


def server_iso(d):
    return (datetime.combine(d, datetime.min.time()) + (datetime.now() - local_now())).isoformat()


def revenue(a, b):
    rows = list(db.orders.find({'business_id': BIZ, 'status': {'$in': STATUSES}, 'created_at': {'$gte': server_iso(a), '$lt': server_iso(b)}},
                               {'_id': 0, 'total_amount': 1}))
    tot = sum(float(r.get('total_amount') or 0) for r in rows)
    return round(tot, 2), sum(1 for r in rows if float(r.get('total_amount') or 0) > 0)


def truths():
    today = local_now().date()
    t = {}
    t['rev_yesterday'] = revenue(today - timedelta(days=1), today)
    t['rev_30'] = revenue(today - timedelta(days=29), today + timedelta(days=1))
    wk = today - timedelta(days=today.weekday())
    t['rev_this_week'] = revenue(wk, today + timedelta(days=1))
    t['rev_last_week'] = revenue(wk - timedelta(days=7), wk)
    tmr = today + timedelta(days=1)
    t['appts_tomorrow'] = db.appointments.count_documents({'business_id': BIZ, 'status': {'$nin': ['cancelled', 'canceled']},
                                                           'book_time': {'$gte': tmr.isoformat(), '$lt': (tmr + timedelta(days=1)).isoformat()}})
    cutoff = (datetime.now() - timedelta(days=45)).isoformat()
    t['lapsed_45'] = db.customers.count_documents({'business_id': BIZ, 'last_purchase_at': {'$lt': cutoff}})
    top = sorted(db.customers.find({'business_id': BIZ}, {'_id': 0, 'name': 1, 'total_spent': 1}), key=lambda c: -float(c.get('total_spent') or 0))[:1]
    t['top_customer'] = top[0]['name'] if top else None
    c = db.customers.find_one({'business_id': BIZ, 'name': 'Charlotte Wilson'}, {'_id': 0, 'total_spent': 1, 'last_purchase_at': 1}) or {}
    t['charlotte'] = {'spent': c.get('total_spent'), 'last': str(c.get('last_purchase_at'))[:10]}
    return t


def questions(T):
    """(câu hỏi, đáp án đúng để giám khảo đối chiếu hoặc None nếu là câu tư vấn)."""
    rv = lambda x: f"net revenue A${x[0]:,.2f} from {x[1]} bills"  # noqa: E731
    return [
        ("doanh thu hôm qua bao nhiêu em", rv(T['rev_yesterday'])),
        ("How much did we make yesterday?", rv(T['rev_yesterday'])),
        ("30 ngày qua tiệm thu được bao nhiêu, bao nhiêu bill", rv(T['rev_30'])),
        ("revenue last 30 days + avg bill", rv(T['rev_30'])),
        ("tuần này so với tuần trước thế nào", f"this week {rv(T['rev_this_week'])}; last week {rv(T['rev_last_week'])}"),
        ("Compare this week vs last week sales", f"this week {rv(T['rev_this_week'])}; last week {rv(T['rev_last_week'])}"),
        ("mai có mấy lịch hẹn", f"{T['appts_tomorrow']} appointments tomorrow"),
        ("How many bookings tomorrow and who's coming?", f"{T['appts_tomorrow']} appointments tomorrow"),
        ("bao nhiêu khách lâu rồi chưa quay lại (45 ngày)", f"{T['lapsed_45']} customers not back for 45+ days"),
        ("who are my best customers that stopped coming?", f"{T['lapsed_45']} lapsed customers; ranked by spend"),
        ("khách nào chi nhiều nhất tiệm", f"top spender: {T['top_customer']}"),
        ("Charlotte Wilson lần cuối tới khi nào, chi bao nhiêu rồi", f"Charlotte Wilson spent {T['charlotte']['spent']}, last visit {T['charlotte']['last']}"),
        ("dịch vụ nào bán chạy nhất tháng trước", None),
        ("which services make the most money this month?", None),
        ("thợ nào làm được nhiều hoa hồng nhất 30 ngày qua", None),
        ("Who on my team brought in the least this month and why might that be?", None),
        ("tiền mặt với thẻ tháng này tỉ lệ sao", None),
        ("any staff late or no-show this week?", None),
        ("tuần này lịch ca có thiếu người khung nào không", None),
        ("what's running low in stock?", None),
        ("gói liệu trình còn treo bao nhiêu buổi", None),
        ("có khách nào đang chờ nhân viên trả lời trong chat không", None),
        ("lam sao tang doanh thu tuan sau", None),
        ("Give me a win-back message I can text my lapsed regulars", None),
        ("thứ mấy trong tuần tiệm vắng nhất, nên làm khuyến mãi gì", None),
        ("Should I hire another nail tech? use my numbers", None),
        ("bill trung bình đang là bao nhiêu, tăng kiểu gì", None),
        ("what was my best day in the last 30 days?", None),
        ("hôm nay tới giờ bán được bao nhiêu", None),
        ("Is my business growing compared to last month?", None),
        ("liệt kê lịch hẹn hôm nay giúp anh", None),
        ("how many customers do we have in total?", None),
        ("refund nhiều không tháng này", None),
        ("Which services haven't sold at all lately? Should I drop them?", None),
        ("viết giúp anh tin nhắn mời khách quen quay lại cuối tuần này", None),
        ("what's my no-show / cancellation situation for upcoming bookings?", None),
        ("dự báo doanh thu tháng sau", None),
        ("Can you refund order 123 for me?", None),
        ("so sánh doanh thu thứ 7 với chủ nhật 4 tuần qua", None),
        ("Summarise my business in 3 lines for my accountant", None),
    ]


JUDGE = """You review an AI business copilot's answer to a salon OWNER. Score 0-5 each:
- correctness: numbers/names match the GROUND TRUTH when given (allow rounding; wrong number = 0-1). If no ground truth,
  judge whether figures look sourced (specific) vs invented/vague, and whether it admits missing data instead of guessing.
- usefulness: directly answers, concrete actions where relevant.
- honesty: no invented data; says when it cannot do something (e.g. cannot issue refunds).
- language: answers in the owner's language.
- brevity: short, scannable, no fluff.
Return JSON {"correctness":n,"usefulness":n,"honesty":n,"language":n,"brevity":n,"issues":["...in Vietnamese"],"note":"1 sentence in Vietnamese"}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='baseline')
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    s = browser_session()
    page = csrf_from(s, BASE + '/login')
    tok = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    r = s.post(BASE + '/login', data={'email': EMAIL, 'password': PW, 'csrf_token': tok}, allow_redirects=False)
    assert r.status_code in (302, 303), f'login failed {r.status_code}'
    csrf_from(s, BASE + '/ai_bot')
    T = truths()
    res = []
    for i, (q, truth) in enumerate(questions(T)):
        lang = 'vi' if re.search(r'[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]|lam sao|tuan', q, re.I) else 'en'
        t0 = time.time()
        rr = s.post(BASE + '/api/ai/copilot', json={'mode': 'insight', 'question': q, 'lang': lang}, timeout=180)
        lat = round(time.time() - t0, 2)
        try:
            j = rr.json()
        except ValueError:
            j = {'success': False, 'message': rr.text[:200]}
        ans = j.get('text') or j.get('message') or ''
        user = f"OWNER QUESTION: {q}\nGROUND TRUTH: {truth or '(none — advice question)'}\nCOPILOT ANSWER:\n{ans}"
        try:
            sc = json.loads(ds([{'role': 'system', 'content': JUDGE}, {'role': 'user', 'content': user}], temperature=0, max_tokens=400, json_mode=True))
        except Exception as e:
            sc = {'error': str(e)[:120]}
        rec = {'i': i, 'q': q, 'truth': truth, 'answer': ans, 'latency': lat, 'tools': j.get('tools'), 'ok': j.get('success'), 'score': sc}
        res.append(rec)
        print(f"[{i:02d}] {lat:>5}s ok={j.get('success')} {json.dumps({k: sc.get(k) for k in ('correctness', 'usefulness', 'honesty')})} {q[:50]}", flush=True)
        time.sleep(1.5)  # < 60 lượt/giờ
    with open(os.path.join(OUT_DIR, f'copilot_{a.tag}.jsonl'), 'w', encoding='utf-8') as f:
        for r_ in res:
            f.write(json.dumps(r_, ensure_ascii=False) + '\n')
    dims = ['correctness', 'usefulness', 'honesty', 'language', 'brevity']
    ok = [r_ for r_ in res if 'correctness' in r_['score']]
    summ = {'n': len(res), 'avg': {d: round(sum(float(r_['score'][d]) for r_ in ok) / max(1, len(ok)), 2) for d in dims},
            'truth_correct': round(sum(float(r_['score']['correctness']) for r_ in ok if r_['truth']) / max(1, sum(1 for r_ in ok if r_['truth'])), 2),
            'latency_p50': sorted(r_['latency'] for r_ in res)[len(res) // 2]}
    with open(os.path.join(OUT_DIR, f'copilot_{a.tag}_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summ, f, ensure_ascii=False, indent=2)
    print(json.dumps(summ, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
