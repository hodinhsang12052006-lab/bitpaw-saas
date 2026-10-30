"""
Kịch bản lễ tân AI — BÁN LẺ: hỏi còn hàng + GIỮ HÀNG chờ lấy thật vào db.retail_holds (gói ai_packs/retail.py: giữ nguyên tử
products.held_qty <= tồn kho, hold 'pending' chờ nhân viên xác nhận, có hạn lấy).

Sự thật DB: đúng sản phẩm + số lượng, không bao giờ giữ quá số còn bán được (stock - held_qty), hết hàng thì không có hold,
huỷ đúng hold của CHÍNH khách; giá bot nêu phải là giá thật x số lượng.
Dọn: hold giả lập ghi thẳng cũng cộng held_qty như gói làm (seed_hook); cuối lượt đếm lại held_qty của đúng các sản phẩm đó
từ các hold còn hiệu lực (cùng cách gói tự sửa — _recount_held), nên không làm lệch tồn kho đang giữ của khách thật.
"""
from datetime import timedelta

import scenarios_common as k

INDUSTRY = 'retail'
RESOURCE = 'stock_hold'
C = 'retail_holds'
COLLECTIONS = {C: {'phone': 'customer_phone', 'name': 'customer_name', 'time': 'expires_at_local'}}
PUBLIC_PAGE = None   # bán lẻ chưa có trang đặt chỗ công khai riêng: mở /login để lấy phiên + CSRF như trình duyệt
MOCK_STATUS = 'pending'
ACTIVE = ('pending', 'ready')
MAX_HOLD_QTY = 10


def _avail(p):
    return int(k.num(p.get('stock'))) - int(k.num(p.get('held_qty')))


def load(db, shop):
    biz = shop['id']
    rows = k.products(db, biz, channel='retail')
    for p in rows:
        p['available'] = _avail(p)
    return {'products': rows}


def facts(shop, data):
    cur = shop['currency']
    lines = ['PRODUCTS (real catalogue: price in ' + cur + ', units that can still be sold/held = stock - already held):']
    for p in data['products'][:80]:
        a = p['available']
        lines.append(f"- {p['name']}: {k.money(p.get('price'), cur)} — " + ('OUT OF STOCK' if a <= 0 else f'{a} available'))
    if not data['products']:
        lines.append('- none published: the assistant cannot confirm stock or prices.')
    lines.append(f'- Pickup holds: at most {MAX_HOLD_QTY} units per hold and never more than available; a hold is a REQUEST '
                 "(status pending) staff confirm; it expires at the store's pickup deadline. Payment happens in store, not in "
                 'the chat. Items not in the list above are not sold here (the assistant must not invent them).')
    lines.append(k.info_line(shop))
    return '\n'.join(lines)


def scenarios(shop, data):
    d = shop['dates']
    cur = shop['currency']
    ps = data['products']
    out = []

    def sc(sid, goal, checks, **kw):
        out.append(dict({'id': sid, 'goal': goal, 'checks': checks, 'currency': cur}, **kw))

    instock = sorted((p for p in ps if p['available'] >= 3), key=lambda p: -p['available'])
    out_ = [p for p in ps if p['available'] <= 0]
    low = sorted((p for p in ps if 1 <= p['available'] <= MAX_HOLD_QTY - 3), key=lambda p: p['available'])
    # 1. còn hàng không + giữ 2 cái
    if instock:
        p = instock[0]
        sc('stock_then_hold_2', f"Ask if '{p['name']}' is in stock, and ask them to hold 2 for you to pick up later today.",
           [k.created(C, {'product_id': p['id'], 'quantity': 2}, ['pending']),
            k.check('max_qty', field='quantity', max=p['available'])],
           mock_doc={'product_name': p['name'], 'unit_price': k.num(p['price'])})
    # 2. hết hàng — không được giữ
    if out_:
        p = out_[0]
        sc('out_of_stock_hold', f"Ask them to hold 1 '{p['name']}' for you to pick up tomorrow. If they can't, ask when it will be "
           "back in stock.", [k.check('none')], psych='rushed')
    # 3. xin giữ nhiều hơn số còn
    if low:
        p = low[0]
        want = p['available'] + 3
        sc('hold_more_than_stock', f"Ask them to hold {want} of '{p['name']}' for a party. If they can't hold that many, accept "
           "however many they really can.",
           [k.check('max_qty', field='quantity', max=p['available']), k.check('at_most_one')],
           # bot mẫu (--mock): giữ đúng số còn bán được (như gói làm khi khách xin quá tồn)
           mock_effect={'op': 'create', 'collection': C,
                        'doc': {'product_id': p['id'], 'quantity': p['available'], 'product_name': p['name']}})
    # 4. hỏi giá + tổng
    if len(ps) >= 2:
        a, b = ps[0], ps[1]
        pa, pb = k.num(a['price']), k.num(b['price'])
        sc('price_total', f"Ask the price of '{a['name']}' and '{b['name']}', and what 3 x '{a['name']}' plus 1 x '{b['name']}' "
           "would cost. Don't hold anything.",
           [k.check('none')], price_check=True, psych='price_sensitive',
           valid_amounts=sorted({k.num(p['price']) for p in ps} | {round(3 * pa + pb, 2), round(pa + pb, 2)}))
    # 5. huỷ hold đã giữ
    if instock:
        p = instock[-1]
        exp = (shop['now'] + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        hold = {'product_id': p['id'], 'product_name': p['name'], 'unit_price': k.num(p['price']), 'currency': cur,
                'quantity': 1, 'status': 'pending', 'expires_at_local': exp}
        sc('cancel_hold', f"Earlier, from this same chat, you asked them to hold 1 '{p['name']}' for pickup. You don't need it any "
           "more — cancel the hold.",
           [k.check('cancelled'), k.check('foreign_untouched')],
           seed={'collection': C, 'doc': dict(hold)},
           foreign_seeds=[{'collection': C, 'doc': dict(hold), 'name': 'Linda Sim'}])
    # 6. món không có trong danh mục
    sc('not_in_catalogue', "Ask if they sell a PlayStation 5 console and AirPods Pro, and the price. If not, ask what similar "
       "things they have.", [k.check('none')], psych='skeptical', price_check=True,
       valid_amounts=sorted({k.num(p['price']) for p in ps}))
    # 7. khách Việt
    if instock:
        p = instock[0]
        sc('vi_hold_1', f"(Write in Vietnamese.) Hỏi '{p['name']}' còn hàng không và nhờ giữ 1 cái, chiều mai ({k.say_day(d['tomorrow'])}) "
           "ghé lấy.",
           [k.created(C, {'product_id': p['id'], 'quantity': 1}, ['pending'])], lang='VI',
           mock_doc={'product_name': p['name']})
    return out


def seed_hook(db, biz, coll, doc):
    """Hold do giả lập ghi THẲNG (hạt giống / bot mẫu) cũng cộng held_qty như gói (_reserve) — hold còn hiệu lực luôn khớp
    với held_qty, gói huỷ hold thì trừ đúng phần của nó."""
    if coll == C and str(doc.get('status') or '').lower() in ACTIVE and doc.get('product_id') is not None:
        db.products.update_one({'id': doc['product_id'], 'business_id': biz}, {'$inc': {'held_qty': int(k.num(doc.get('quantity')))}})


def cleanup_extra(db, biz, rows):
    """Sau khi xoá hold của lượt chạy: held_qty của ĐÚNG các sản phẩm đó = tổng hold còn hiệu lực (như gói _recount_held)."""
    pids = sorted({r.get('product_id') for c, r in rows if c == C and r.get('product_id') is not None}, key=str)
    n = 0
    for pid in pids:
        p = db.products.find_one({'id': pid, 'business_id': biz}, {'_id': 0, 'held_qty': 1})
        if p is None:
            continue
        actual = sum(int(k.num(h.get('quantity'))) for h in db[C].find(
            {'business_id': biz, 'product_id': pid, 'status': {'$in': list(ACTIVE)}}, {'_id': 0, 'quantity': 1}))
        if 'held_qty' in p or actual:
            db.products.update_one({'id': pid, 'business_id': biz}, {'$set': {'held_qty': actual}})
            n += 1
    return {'products_held_qty_recounted': n}
