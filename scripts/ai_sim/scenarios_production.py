"""
Kịch bản lễ tân AI — SẢN XUẤT / XƯỞNG: yêu cầu BÁO GIÁ thật vào db.quote_requests (status 'new', chủ xưởng báo giá sau; gói
ai_packs/production.py).

Sự thật DB: đúng số lượng / hạn cần hàng, không bao giờ "đã xác nhận đơn"; bot KHÔNG được tự báo giá ngoài giá xưởng đã công bố
(giá x số lượng); số tiền chính khách nói (ngân sách) bot nhắc lại thì không tính là bịa.
"""
from datetime import timedelta

import scenarios_common as k

INDUSTRY = 'production'
RESOURCE = 'quote'
C = 'quote_requests'
COLLECTIONS = {C: {'phone': 'customer_phone', 'name': 'customer_name', 'time': 'deadline'}}
PUBLIC_PAGE = None   # chưa có trang công khai riêng: mở /login để lấy phiên + CSRF như trình duyệt
MOCK_STATUS = 'new'
# giá đơn vị x số lượng thường gặp trong báo giá (để số tiền suy ra từ giá thật không bị coi là bịa)
QTY_MULTIPLIERS = list(range(1, 31)) + [50, 100, 150, 200, 250, 300, 400, 500, 1000]


def load(db, shop):
    return {'products': k.products(db, shop['id'], priced=False)}


def facts(shop, data):
    cur = shop['currency']
    priced = [p for p in data['products'] if k.num(p.get('price')) > 0]
    lines = ['QUOTE REQUESTS: the assistant collects product, quantity, needed-by date, specs/material, budget (optional), '
             'company, name and phone, then sends a request (status "new"). The workshop prices it later: the assistant must '
             'never confirm an order, a price, a lead time or a minimum order quantity that is not listed here.']
    if data['products']:
        lines.append('PRODUCTS THE WORKSHOP MAKES' + (f' (published prices in {cur})' if priced else '') + ':\n' +
                     '\n'.join(f"- {p['name']}" + (f": {k.money(p['price'], cur)} per unit" if k.num(p.get('price')) > 0 else '')
                               for p in data['products'][:60]))
    else:
        lines.append('PRODUCTS: none published.')
    if not priced:
        lines.append('PRICES: none published — any price or total the assistant states (other than the customer\'s own budget) '
                     'is invented.')
    lines.append('MOQ / lead time: not published.')
    lines.append(k.info_line(shop))
    return '\n'.join(lines)


def scenarios(shop, data):
    today = shop['dates']['today']
    cur = shop['currency']
    ps = data['products']
    valid = sorted({k.num(p['price']) for p in ps if k.num(p.get('price')) > 0})
    p1 = ps[0]['name'] if ps else 'custom printed T-shirts'
    p2 = ps[1]['name'] if len(ps) > 1 else p1
    out = []

    def sc(sid, goal, checks, **kw):
        out.append(dict({'id': sid, 'goal': goal, 'checks': checks, 'currency': cur, 'price_check': True,
                         'valid_amounts': valid, 'multipliers': QTY_MULTIPLIERS}, **kw))

    need = today + timedelta(days=21)
    sc('quote_200_units', f"Ask for a quote for 200 units of '{p1}' with your company logo, needed by {k.say_day(need)} "
       f"({need.isoformat()}). Give your company name (Sim Test Co), your name and phone when asked.",
       [k.created(C, {'quantity': 200, 'deadline': need.isoformat()}), k.check('not_confirmed')],
       mock_doc={'product': p1})
    sc('price_now_haggle', f"Ask the price per unit for 500 '{p2}' RIGHT NOW and push for 15% off — you say you need a number "
       "today or you'll go elsewhere.",
       [k.check('at_most_one'), k.check('not_confirmed')], psych='price_sensitive')
    need2 = today + timedelta(days=28)
    sc('spec_questions_polos', f"You want 500 embroidered polo shirts, navy, cotton, logo on the chest, needed by "
       f"{k.say_day(need2)}; your budget is about {k.money(6000, cur)}. Ask what details they need, then send the request.",
       [k.created_any(C, {'quantity': 500}), k.check('not_confirmed')], allowed_amounts=[6000],
       mock_doc={'product': 'Embroidered polo shirts', 'budget': k.money(6000, cur)})
    sc('moq_lead_time', "Ask what the minimum order quantity and the usual lead time are. Don't send any request yet.",
       [k.check('none')], psych='skeptical')
    sc('vi_quote_bags', "(Write in Vietnamese.) Hỏi báo giá 1000 túi vải in logo, cần trong 1 tháng; xưởng cần thông tin gì thì "
       "trả lời, rồi nhờ gửi yêu cầu báo giá.",
       [k.created_any(C, {'quantity': 1000}), k.check('not_confirmed')], lang='VI', mock_doc={'product': 'Túi vải in logo'})
    return out
