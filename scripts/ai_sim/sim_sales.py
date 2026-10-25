"""
60 chủ tiệm (Mỹ / Úc / Việt) hỏi bot tư vấn phần mềm BitPaw trên landing — kiểm giá có đúng bảng giá, có hứa tính năng
không có không, có lưu thông tin liên hệ thật (db.cskh_requests) khi khách đồng ý không.
    python scripts/ai_sim/sim_sales.py --n 60 --tag baseline
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
from datetime import datetime
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_core import BASE, Pacer, browser_session, csrf_from, db, judge, run_conversation, summarize  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'audit-results', 'ai_sim')
INDUSTRIES = [('nail', 'nail salon', '/solutions/nail'), ('spa', 'day spa', '/solutions/spa'), ('fnb', 'cafe', '/solutions/fnb'),
              ('retail', 'gift shop', '/solutions/retail'), ('hotel', '12-room motel', '/solutions/hotel'), ('karaoke', 'karaoke bar', '/solutions/karaoke'),
              ('technical', 'air-con repair team of 8', '/solutions/technical'), ('office', 'accounting office of 15', '/solutions/office'),
              ('production', 'small furniture workshop', '/solutions/production')]
GOALS = [
    ('price', 'Find out exactly what it costs per month and upfront in your currency, and what you get for it. Decide if you would consider it.', False),
    ('compare', 'You currently use {comp}. Ask how BitPaw is different and whether switching is worth it. Push for honest answers.', False),
    ('missing_feature', 'Ask whether it can {feat}. You really need that.', False),
    ('security', 'You are worried about customer data and payments security. Ask pointed questions (who can see data, where is it stored, card numbers).', False),
    ('demo', 'You are interested. Ask for a demo / someone to call you, and give your contact ({contact}) when asked.', True),
    ('trial_discount', 'Ask for a free trial and a discount. Be persistent but realistic.', False),
    ('fit', 'Describe your daily mess (manual paper bookings, payroll by hand, no-shows) and ask which plan fits. If convinced, leave your email ({contact}).', True),
    ('skeptic', 'You think software is a waste of money and this is probably a scam. Test the bot, ask for proof and who the company is.', False),
]
COMPS = ['Fresha', 'Square Appointments', 'Vagaro', 'Toast POS', 'Deputy', 'Mindbody', 'Lightspeed', 'pen and paper + Excel']
FEATS = ['sync my Shopee and Shopify stock', 'take bookings from Booking.com and Agoda automatically', 'connect to Xero accounting',
         'run payroll with tax withholding and super', 'print barcode labels', 'do online booking with deposits']
PSY = [('busy', 'Busy owner between clients: short messages, wants straight answers fast.'),
       ('analytical', 'Detail-oriented: asks follow-ups, notices contradictions.'),
       ('friendly', 'Chatty and warm, but cautious with money.'),
       ('skeptical', 'Distrustful of sales talk; calls out vague answers.'),
       ('non_tech', 'Not tech-savvy: worries it will be hard to set up and use.')]
COUNTRY = [('US', 'English (American)', 'USD'), ('AU', 'English (Australian)', 'AUD'), ('VN-US', 'Vietnamese (a Vietnamese owner living in the US)', 'USD'),
           ('AU-VI', 'Vietnamese typed without diacritics (Vietnamese owner in Sydney)', 'AUD')]


LEAD_IDS = set()
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
PHONE_RE = re.compile(r'\+?\d[\d\s().-]{7,}\d')


def leads_from_transcript(transcript, contact, since):
    """Lead do cuộc chat này tạo: tìm theo email/SĐT mà khách giả lập THẬT SỰ gõ (cả liên hệ persona)."""
    text = ' '.join(t['text'] for t in transcript if t['who'] == 'customer') + ' ' + contact
    # khách đánh vần email ("dave at shop dot com dot au") — bot ghép lại đúng, bộ kiểm cũng phải nhận ra
    text += ' ' + re.sub(r'\s+dot\s+', '.', re.sub(r'\s+at\s+', '@', text, flags=re.I), flags=re.I)
    emails = sorted(set(e.lower().rstrip('.') for e in EMAIL_RE.findall(text)))
    tails = sorted(set(re.sub(r'\D', '', ph)[-8:] for ph in PHONE_RE.findall(text) if len(re.sub(r'\D', '', ph)) >= 8))
    ors = [{'email': {'$in': emails}}] if emails else []
    ors += [{'phone': {'$regex': t + '$'}} for t in tails]
    if not ors:
        return []
    return list(db.cskh_requests.find({'source': 'ai_sales_chat', 'created_at': {'$gte': since}, '$or': ors}, {'_id': 0, 'id': 1}))


def personas(n):
    out = []
    for i in range(n):
        ind = INDUSTRIES[i % len(INDUSTRIES)]
        g = GOALS[(i * 3) % len(GOALS)]
        psy = PSY[(i * 7) % len(PSY)]
        c = COUNTRY[(i * 5 + i // 9) % len(COUNTRY)]
        contact = f"sim.owner{i:03d}@example.com" if i % 2 else f"+1 555 01{i:02d} 7{i % 10}0{i % 7}"
        goal = g[1].format(comp=COMPS[i % len(COMPS)], feat=FEATS[i % len(FEATS)], contact=contact) + \
            f" If you ever give contact details, use exactly: {contact} (and your first name)."
        out.append({'idx': i, 'scenario': g[0], 'industry': ind[0], 'page': ind[2], 'contact': contact, 'expects_lead': g[2],
                    'persona': f"Owner of a {ind[1]} in {c[0].split('-')[0]}, {psy[0]}", 'psychology': psy[1], 'language': c[1], 'goal': goal,
                    'currency': c[2]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=60)
    ap.add_argument('--tag', default='baseline')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--per-minute', type=int, default=17)
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    # Giá THEO NGÀNH (25/10/2026): giám khảo chấm theo ĐÚNG khối dữ kiện bot được nạp (plans.py — cùng nguồn bảng giá/checkout).
    # Trước đây ghi cứng bảng giá phẳng cũ (Essential $99 + $999...) -> chấm sai mọi câu báo giá đúng theo ngành.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from ai_sales_prompts import bitpaw_facts
    facts = "\n".join([
        "REAL BITPAW FACTS (same source as the website price table and checkout):",
        bitpaw_facts(None, None),
        "- No free trial or discount code is published. Data on MongoDB Atlas (encrypted at rest), per-business isolation, cards via Square.",
        "- Any price, fee, discount or free item different from the lines above is an accuracy failure."])
    pacer = Pacer(a.per_minute)
    ps = personas(a.n)
    results = []
    started = time.strftime('%Y-%m-%dT%H:%M:%S')

    def one(p):
        sess = browser_session()
        csrf_from(sess, BASE + p['page'])

        def bot(history, msg):
            payload = {'business_id': None, 'industry': p['industry'], 'context': None, 'customer_phone': None,
                       'client_now': time.strftime('%Y-%m-%dT%H:%M:%S'), 'customer_message': msg, 'history': history[-10:], 'userPrompt': msg}
            pacer.wait()
            t0 = time.time()
            for _ in range(3):
                r = sess.post(BASE + '/api/ai/studio/generate', json=payload, timeout=120)
                if r.status_code != 429:
                    break
                time.sleep(20)
            lat = time.time() - t0
            try:
                j = r.json()
                return (j.get('choices') or [{}])[0].get('message', {}).get('content') or '', lat, {'fallback': bool(j.get('fallback'))}
            except ValueError:
                return '', lat, {'error': r.status_code}

        try:
            convo_start = datetime.now().isoformat()
            transcript, lats, metas = run_conversation(p, bot, max_turns=7)
            leads = leads_from_transcript(transcript, p['contact'], convo_start)
            LEAD_IDS.update(x['id'] for x in leads)
            lead = leads[0] if leads else None
            check = {'lead_saved': bool(lead), 'expects_lead': p['expects_lead'], 'leads_saved': len(leads)}
            if p['expects_lead']:
                check['pass'] = bool(lead)
            score = judge(p, transcript, facts, check)
        except Exception as e:
            transcript, lats, metas, check, score = [], [], [], {}, {'error': str(e)[:200]}
        rec = {'idx': p['idx'], 'scenario': p['scenario'], 'industry': p['industry'], 'persona': p['persona'], 'psychology': p['psychology'],
               'language': p['language'], 'goal': p['goal'], 'transcript': transcript, 'latencies': lats, 'db_check': check, 'score': score,
               'fallbacks': sum(1 for m in metas if m.get('fallback'))}
        print(f"[{p['idx']:02d}] {p['scenario']:<15} {p['industry']:<10} lead={check.get('lead_saved')} "
              f"{json.dumps({k: score.get(k) for k in ('task_success', 'accuracy', 'honesty')})} lat={lats}", flush=True)
        return rec

    try:
        with cf.ThreadPoolExecutor(a.workers) as ex, open(os.path.join(OUT_DIR, f'sales_{a.tag}.jsonl'), 'w', encoding='utf-8') as f:
            for rec in ex.map(one, ps):
                results.append(rec)
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    finally:
        # chỉ xoá lead của CHÍNH các cuộc chat giả lập (đúng liên hệ khách giả lập đã gõ) — không đụng lead thật cùng giờ
        removed = db.cskh_requests.delete_many({'id': {'$in': sorted(LEAD_IDS)}, 'source': 'ai_sales_chat'}).deleted_count
        print('cleaned leads', removed)
    summ = summarize(results)
    with open(os.path.join(OUT_DIR, f'sales_{a.tag}_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summ, f, ensure_ascii=False, indent=2)
    print(json.dumps(summ, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
