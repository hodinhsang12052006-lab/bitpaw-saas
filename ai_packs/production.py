# -*- coding: utf-8 -*-
"""
Gói AI cho ngành SẢN XUẤT (production) — RESOURCE 'quote': nhận YÊU CẦU BÁO GIÁ B2B (khách sỉ / doanh nghiệp).

Trước đây ngành Sản xuất không có gì cho khách bên ngoài. Giống Yelp Smart Lead Reply / form báo giá của xưởng: AI hỏi
sản phẩm, số lượng, hạn cần hàng, quy cách / chất liệu, ngân sách (nếu có), công ty, tên + SĐT -> 1 dòng db.quote_requests
(status 'new') mà chủ xưởng xem ở trang Yêu cầu báo giá (/requests/quotes — retail_holds_bp.py) + email báo chủ.
AI KHÔNG bao giờ tự báo giá, thời gian sản xuất hay số lượng tối thiểu: xưởng gửi báo giá sau.
Dùng chung tiện ích SĐT / tiền tệ / giờ tiệm / chống trùng với ai_packs/retail.py.
"""
import re
from datetime import datetime, timedelta

import ai_packs
from ai_packs import retail as _c
from mongo_client import db, next_mongo_id

INDUSTRIES = ('production',)
RESOURCE = 'quote'
# facts() chỉ nêu TÊN sản phẩm: giá bán lẻ trong danh mục không phải báo giá sỉ/đặt làm -> không chèn bảng giá chung
FACTS_INCLUDE_CATALOG = True
STATUSES = ('new', 'contacted', 'quoted', 'won', 'lost')
MAX_DAYS_AHEAD = 730


def _fn(name, desc, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': desc,
                                             'parameters': {'type': 'object', 'properties': props, 'required': list(required)}}}


TOOLS = [
    _fn('production_request_quote',
        "Send a REAL quote request to the business (it appears on the owner's Quote requests list). Collect first: the "
        "product, quantity, the date they need it by, specifications / material if any, budget if they want to share it, "
        "company name if any, and the contact person's name and phone number. The business replies with a quote — never "
        "state or estimate a price, lead time or minimum order yourself.",
        {'product': {'type': 'string', 'description': 'What they want made (product, model or a short description).'},
         'quantity': {'type': 'number', 'description': 'How many units.'},
         'unit': {'type': 'string', 'description': 'Unit, e.g. pcs, sets, kg, m (optional).'},
         'deadline': {'type': 'string', 'description': 'Date they need it by, YYYY-MM-DD (optional).'},
         'specs': {'type': 'string', 'description': 'Size, colour, print/logo, packaging and other specifications (optional).'},
         'material': {'type': 'string', 'description': 'Material or quality wanted (optional).'},
         'budget': {'type': 'string', 'description': "Customer's budget, in their words (optional)."},
         'company': {'type': 'string', 'description': 'Company name (optional).'},
         'customer_name': {'type': 'string', 'description': 'Contact person name.'},
         'phone': {'type': 'string', 'description': 'Contact phone number.'},
         'email': {'type': 'string', 'description': 'Contact email (optional).'}},
        ['product', 'quantity']),
]
MANAGE_TOOLS = set()

PROMPT_RULES = {
    'en': ("QUOTE RULES: You collect quote requests; the business sends the quote. Ask only what's missing, a couple of "
           "questions at a time: product, quantity, needed-by date, specifications / material, budget (optional), company, "
           "contact name and phone. Never state, estimate or hint at a unit price, total, discount, lead time, minimum order "
           "or delivery date — say the team will reply with a quote. Don't promise capacity or that the order is accepted."),
    'vi': ("LUẬT BÁO GIÁ: Em chỉ NHẬN yêu cầu báo giá; xưởng gửi báo giá sau. Hỏi phần còn thiếu, mỗi lần 1-2 câu: sản phẩm, "
           "số lượng, ngày cần hàng, quy cách / chất liệu, ngân sách (nếu khách muốn), công ty, tên + SĐT người liên hệ. Không "
           "bao giờ nói hay ước đơn giá, tổng tiền, chiết khấu, thời gian sản xuất, số lượng tối thiểu hay ngày giao — nói đội "
           "sẽ gửi báo giá. Không hứa nhận đơn hay đủ năng lực sản xuất."),
}


def _err(msg):
    return ai_packs.PackError(msg)


def _clean(v, n):
    return re.sub(r'\s+', ' ', str(v or '')).strip()[:n]


def _qty(v):
    try:
        if isinstance(v, bool):
            raise ValueError
        q = float(str(v).replace(',', '').strip())
    except (TypeError, ValueError):
        raise _err('quantity must be a number (how many units). Nothing was sent.')
    if not 0 < q <= 1e9:
        raise _err('quantity must be more than 0. Nothing was sent.')
    return int(q) if q == int(q) else q


def request_quote(args, ctx):
    bid = _c._bid(ctx)
    product = _clean(args.get('product'), 200)
    if len(product) < 2:
        raise _err('Ask what product they want a quote for. Nothing was sent.')
    qty = _qty(args.get('quantity'))
    now = _c._now(ctx)
    deadline = None
    if args.get('deadline') not in (None, ''):
        try:
            deadline = datetime.strptime(str(args['deadline']).strip()[:10], '%Y-%m-%d').date()
        except ValueError:
            raise _err(f"deadline '{str(args['deadline'])[:20]}' must be YYYY-MM-DD. Nothing was sent.")
        if deadline < now.date():
            raise _err(f"{deadline.isoformat()} is already past (today is {now.date().isoformat()}). Ask for the real needed-by date. Nothing was sent.")
        if deadline > now.date() + timedelta(days=MAX_DAYS_AHEAD):
            raise _err('That needed-by date is more than 2 years away — check it with the customer. Nothing was sent.')
    email = _c.clean_email(args.get('email'))
    shop = _c._shop(bid)
    name, phone, pkey = _c._contact(args, ctx, 'sending the quote request', shop)
    unit = _clean(args.get('unit'), 30)
    specs, material = _clean(args.get('specs'), 1000), _clean(args.get('material'), 200)
    budget, company = _clean(args.get('budget'), 120), _clean(args.get('company'), 120)
    _c.ensure_indexes('quote_requests')
    vi = _c._vi(ctx)
    rid = next_mongo_id('quote_requests')
    key = _c.request_key(ctx, phone, product, str(qty), str(deadline or ''), now.date().isoformat())
    doc = {'id': rid, 'business_id': bid, 'product': product, 'quantity': qty, 'unit': unit,
           'deadline': deadline.isoformat() if deadline else None, 'specs': specs, 'material': material, 'budget': budget,
           'company': company, 'customer_name': name, 'customer_phone': phone, 'phone_key': pkey,
           'email': email, 'status': 'new', 'source': 'ai_bot', 'ai_conversation_id': ctx.get('customer_id'),
           'chat_token_hash': ctx.get('chat_token_hash') or None, 'channel': ctx.get('channel') or 'web',
           'created_at': datetime.now().isoformat(), 'created_at_local': now.strftime('%Y-%m-%dT%H:%M')}
    saved, created = _c.insert_once(db.quote_requests, bid, key, doc)
    if not created:
        return {'success': True, 'already_requested': True, 'quote_request_id': (saved or {}).get('id'), 'status': 'new',
                'note': 'This exact quote request was already sent today — do not send it again.'}
    what = ' '.join(x for x in (f"{qty:,}" if isinstance(qty, int) else f"{qty:g}", unit, product) if x)
    by = f", cần trước {deadline:%d/%m/%Y}" if deadline else ''
    _c._notify(ctx, shop,
               f"Yêu cầu BÁO GIÁ mới #{rid} từ chat AI: {what}{by} — {name} {phone}" + (f" ({company})" if company else '')
               + (f". Quy cách: {specs[:200]}" if specs else ''),
               f"New QUOTE request #{rid} from the AI chat: {what}" + (f", needed by {deadline:%d %b %Y}" if deadline else '')
               + f" — {name} {phone}" + (f" ({company})" if company else '') + (f". Specs: {specs[:200]}" if specs else ''),
               f"New quote request #{rid}: {what}" + (f", needed by {deadline:%d %b %Y}" if deadline else '')
               + f". Contact: {name} {phone}" + (f", {email}" if email else '') + (f", {company}" if company else '')
               + (f". Specs: {specs[:300]}" if specs else '') + (f". Material: {material}" if material else '')
               + (f". Budget: {budget}" if budget else '') + ". See Quote requests in BitPaw.", 'quote_request', phone)
    tell = (f"Em đã gửi yêu cầu báo giá #{rid} ({what}) cho xưởng. Bên em sẽ liên hệ {name} qua số {phone} để gửi báo giá — "
            "em không báo giá được trong chat." if vi else
            f"I've sent your quote request #{rid} ({what}) to the team. They'll contact {name} on {phone} with a quote — I "
            "can't give prices in this chat.")
    return {'success': True, 'quote_request_id': rid, 'status': 'new', 'tell_customer': tell,
            'note': 'No price, lead time, minimum order or acceptance was promised — do not add any.'}


def facts(business_id, lang, now_local):
    """Dữ kiện riêng của gói (giờ mở cửa + thông tin xưởng + kho câu hỏi do customer_context.facts thêm cho mọi gói)."""
    lines = []
    try:
        names = [str(p.get('name')).strip() for p in db.products.find({'business_id': business_id, 'is_active': {'$in': [1, True]}},
                                                                      {'_id': 0, 'name': 1}).limit(30) if p.get('name')]
    except Exception:
        names = []
    if names:
        lines.append('PRODUCTS ON FILE (names only): ' + ', '.join(names) + '.')
    lines.append("QUOTES: prices, minimum order, lead time and delivery for custom or bulk orders come ONLY from the team in a "
                 "written quote — never state or estimate any price here. Use production_request_quote to send the request; "
                 "the team replies to the contact.")
    return '\n'.join(lines)


_HANDLERS = {'production_request_quote': request_quote}


def execute(name, args, ctx):
    fn = _HANDLERS.get(name)
    if fn is None:
        raise _err(f"Unknown production tool '{name}'.")
    return fn(args if isinstance(args, dict) else {}, ctx or {})
