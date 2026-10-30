"""
Owner knowledge base for the AI receptionist (db.ai_knowledge) — Phase 2.

The owner writes the answers the AI may give: question/answer pairs ("Do you have parking?") and free-text policies
(deposit, cancellation, allergies, kids, pets...). customer_context puts them into every customer chat prompt (web chat,
Messenger, Instagram, WhatsApp, Zalo, Viber, SMS); the AI answers from them and never invents what is not written. A question
the AI cannot answer goes to the team (ask_team) and shows up on /ai/knowledge as "questions the AI could not answer".

Document: {id, business_id, kind 'faq'|'policy', topic, question, answer, active, created_at, updated_at, updated_by}
Only public facts belong here — the page says so; nothing private about customers is ever read from this collection.
"""
import re
import secrets
from datetime import datetime, timedelta

from mongo_client import db

KINDS = ('faq', 'policy')
TOPICS = ('parking', 'deposit', 'cancellation', 'allergies', 'kids', 'pets', 'accessibility', 'payments', 'dress_code',
          'delivery', 'groups', 'other')
TOPIC_LABELS = {
    'parking': ('Parking', 'Chỗ đỗ xe'), 'deposit': ('Deposits', 'Đặt cọc'),
    'cancellation': ('Cancellation / late policy', 'Huỷ / đến trễ'), 'allergies': ('Allergies & dietary', 'Dị ứng & ăn kiêng'),
    'kids': ('Kids', 'Trẻ em'), 'pets': ('Pets', 'Thú cưng'), 'accessibility': ('Accessibility', 'Lối đi cho xe lăn / hỗ trợ'),
    'payments': ('Payments', 'Thanh toán'), 'dress_code': ('Dress code', 'Trang phục'), 'delivery': ('Delivery / pick-up', 'Giao hàng / tự lấy'),
    'groups': ('Groups & events', 'Đoàn & sự kiện'), 'other': ('Other', 'Khác'),
}
MAX_ENTRIES = 80
MAX_QUESTION = 200
MAX_ANSWER = 1200
PROMPT_MAX_CHARS = 4500
_CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_ID_RE = re.compile(r'^[a-f0-9]{16}$')


class KnowledgeError(ValueError):
    """Invalid entry; message in both languages ('EN / VI') like booking_rules.REASON_TEXT."""


def _clean(value, limit):
    text = _CTRL_RE.sub('', str(value or '')).replace('\r\n', '\n').strip()
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text[:limit]


def _validate(data, partial=False, current=None):
    data = data if isinstance(data, dict) else {}
    cur = current or {}
    out = {}
    if 'kind' in data or not partial:
        kind = str(data.get('kind') or cur.get('kind') or 'faq').strip().lower()
        if kind not in KINDS:
            raise KnowledgeError('Type must be "faq" or "policy". / Loại phải là "faq" hoặc "policy".')
        out['kind'] = kind
    if 'topic' in data or not partial:
        topic = str(data.get('topic') or 'other').strip().lower()
        out['topic'] = topic if topic in TOPICS else 'other'
    if 'question' in data or not partial:
        out['question'] = _clean(data.get('question'), MAX_QUESTION)
    if 'answer' in data or not partial:
        out['answer'] = _clean(data.get('answer'), MAX_ANSWER)
        if not out['answer']:
            raise KnowledgeError('Please write the answer. / Vui lòng nhập câu trả lời.')
    if 'active' in data:
        out['active'] = bool(data.get('active'))
    elif not partial:
        out['active'] = True
    kind = out.get('kind') or cur.get('kind') or 'faq'
    question = out['question'] if 'question' in out else cur.get('question')
    if kind == 'faq' and not question:
        raise KnowledgeError('A question & answer needs the question. / Mục hỏi-đáp cần có câu hỏi.')
    return out


def _public(doc):
    d = {k: doc.get(k) for k in ('id', 'kind', 'topic', 'question', 'answer', 'active', 'created_at', 'updated_at')}
    d['active'] = d.get('active') is not False
    en, vi = TOPIC_LABELS.get(d.get('topic') or 'other', TOPIC_LABELS['other'])
    d['topic_label_en'], d['topic_label_vi'] = en, vi
    return d


def list_entries(business_id, active_only=False):
    if not business_id:
        return []
    flt = {'business_id': business_id}
    if active_only:
        flt['active'] = {'$ne': False}
    rows = list(db.ai_knowledge.find(flt, {'_id': 0}).sort('created_at', 1).limit(MAX_ENTRIES + 20))
    order = {t: i for i, t in enumerate(TOPICS)}
    rows.sort(key=lambda r: (order.get(r.get('topic'), 99), r.get('created_at') or ''))
    return [_public(r) for r in rows]


def create(business_id, data, user=None):
    if not business_id:
        raise KnowledgeError('No business. / Không xác định được tiệm.')
    clean = _validate(data)
    if db.ai_knowledge.count_documents({'business_id': business_id}) >= MAX_ENTRIES:
        raise KnowledgeError(f'Up to {MAX_ENTRIES} entries — edit or delete an old one first. / '
                             f'Tối đa {MAX_ENTRIES} mục — sửa hoặc xoá bớt mục cũ trước.')
    now = datetime.now().isoformat()
    doc = {'id': secrets.token_hex(8), 'business_id': business_id, **clean, 'created_at': now, 'updated_at': now,
           'updated_by': str(user or '')[:80] or None}
    db.ai_knowledge.insert_one(dict(doc))
    return _public(doc)


def _find(business_id, entry_id):
    if not business_id or not isinstance(entry_id, str) or not _ID_RE.match(entry_id):
        return None
    return db.ai_knowledge.find_one({'business_id': business_id, 'id': entry_id}, {'_id': 0})


def update(business_id, entry_id, data, user=None):
    cur = _find(business_id, entry_id)
    if not cur:
        raise LookupError('Entry not found. / Không tìm thấy mục này.')
    clean = _validate(data, partial=True, current=cur)
    if not clean:
        return _public(cur)
    clean['updated_at'] = datetime.now().isoformat()
    clean['updated_by'] = str(user or '')[:80] or None
    db.ai_knowledge.update_one({'business_id': business_id, 'id': entry_id}, {'$set': clean})
    return _public({**cur, **clean})


def delete(business_id, entry_id):
    cur = _find(business_id, entry_id)
    if not cur:
        raise LookupError('Entry not found. / Không tìm thấy mục này.')
    db.ai_knowledge.delete_one({'business_id': business_id, 'id': entry_id})
    return True


def prompt_block(business_id, max_chars=PROMPT_MAX_CHARS):
    """The block the customer AI reads (exactly what /ai/knowledge previews). '' when the owner wrote nothing."""
    try:
        rows = list_entries(business_id, active_only=True)
    except Exception as e:
        print(f"[ai_knowledge] {e}")
        return ''
    if not rows:
        return ''
    lines, used = [], 0
    for r in rows:
        label = TOPIC_LABELS.get(r['topic'], TOPIC_LABELS['other'])[0]
        answer = ' '.join(str(r.get('answer') or '').split())
        if r.get('kind') == 'faq' and r.get('question'):
            line = f"- {label} — Q: {' '.join(r['question'].split())} A: {answer}"
        else:
            title = f" ({' '.join(r['question'].split())})" if r.get('question') else ''
            line = f"- {label} policy{title}: {answer}"
        if used + len(line) > max_chars:
            lines.append('- (more answers exist but did not fit; for anything not listed, use ask_team)')
            break
        lines.append(line)
        used += len(line)
    return ("OWNER'S ANSWERS (written by the business — answer from these first, in the customer's language; never add details "
            "they do not contain; if a question is not covered, say you'll check and use ask_team):\n" + "\n".join(lines))


def unanswered_questions(business_id, days=30, limit=15):
    """Questions customers asked that the AI had no data for (the ask_team notes in /ai_bot) — the owner answers them here."""
    if not business_id:
        return []
    since = (datetime.now() - timedelta(days=days)).isoformat()
    out, seen = [], set()
    try:
        cur = db.bot_messages.find({'business_id': business_id, 'sender_type': 'system', 'content': {'$regex': '^❓'},
                                    'created_at': {'$gte': since}}, {'_id': 0, 'content': 1, 'created_at': 1})
        for m in cur.sort('created_at', -1).limit(80):
            q = str(m.get('content') or '').split(':', 1)[-1].strip()
            if q and q.lower() not in seen:
                seen.add(q.lower())
                out.append({'question': q[:200], 'at': str(m.get('created_at') or '')[:10]})
            if len(out) >= limit:
                break
    except Exception as e:
        print(f"[ai_knowledge] gaps: {e}")
    return out
