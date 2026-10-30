# -*- coding: utf-8 -*-
"""
Gói AI cho ngành BÁN LẺ (retail) — RESOURCE 'stock_hold': tra hàng THẬT (giá + còn hàng từ db.products) và
GIỮ HÀNG CHỜ LẤY (hold for pickup).

Cách chạy (giống Shopify Inbox / Tidio Lyro "hold"): khách hỏi "còn sữa tươi không" -> AI tra db.products (cùng
bộ lọc màn POS bán lẻ: channel_type 'retail', is_active) và chỉ trả lời CÒN / SẮP HẾT / HẾT, không bao giờ hứa quá
tồn kho. Khách muốn giữ -> 1 dòng db.retail_holds (status 'pending' = YÊU CẦU, nhân viên xác nhận trên trang
/retail/holds — retail_holds_bp.py), hết hạn lúc đóng cửa NGÀY LÀM VIỆC KẾ TIẾP (theo giờ mở cửa chủ tiệm nhập ở
Cài đặt đặt lịch; chưa nhập thì hết ngày mai), trả tiền khi tới lấy (chat không thu tiền gì).

Chống giữ trùng / giữ quá tồn: products.held_qty = tổng số đang giữ; giữ mới = 1 lệnh find_one_and_update NGUYÊN
TỬ với điều kiện (stock - held_qty) >= số lượng, nên 2 khách giữ cùng món cuối cùng chỉ 1 người được. Hold không
trừ stock: nhân viên bán qua POS lúc khách tới lấy (POS trừ stock như mọi đơn), rồi bấm "Đã lấy" -> trả held_qty.
Hết hạn / huỷ / đã lấy -> trả held_qty (chuyển trạng thái bằng find_one_and_update để chỉ trả 1 lần).

Chỉ xem/huỷ hold CHỨNG MINH được là của khách đang chat: SĐT đã xác minh (ctx.phone, so ĐỦ số E.164 — không so đuôi số),
mã chat web của đúng trình duyệt (chat_token_hash, trừ mã 'anon:' tạm), hoặc hội thoại nền tảng (Messenger/Zalo/...) đã
ký. Không lộ hold của người khác. Mỗi khách chỉ 1 hold đang giữ / 1 món: khoá active_key + unique index (nguyên tử).

File này cũng chứa tiện ích dùng chung cho 3 gói "yêu cầu" còn lại (technical / production / office): SĐT, quyền sở hữu,
tiền tệ, chống trùng (insert_once), báo nhân viên (_notify).
"""
import hashlib
import json
import re
import unicodedata
from datetime import datetime, time as dtime, timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import ai_packs
import booking_rules
from currency_utils import format_money
from mongo_client import db, next_mongo_id

INDUSTRIES = ('retail',)
RESOURCE = 'stock_hold'
# facts() chỉ nêu nhóm hàng + bảo AI tra retail_find_products (giá + tồn THẬT lúc hỏi) — không chèn bảng giá chung 60 món
# (bảng tĩnh khiến AI tự trả lời "còn hàng" mà không tra tồn kho)
FACTS_INCLUDE_CATALOG = True
BOOKING_COLLECTIONS = (('retail_holds', 'customer_phone'),)   # mã SMS 1 lần chỉ gửi cho SĐT từng giữ hàng ở tiệm này

ACTIVE = ('pending', 'ready')                       # còn giữ hàng (held_qty đang tính)
STATUSES = ('pending', 'ready', 'picked_up', 'cancelled', 'expired')
STAFF_NEXT = {'pending': ('ready', 'picked_up', 'cancelled'), 'ready': ('picked_up', 'cancelled')}
MAX_HOLD_QTY = 10                                   # 1 lần giữ tối đa bấy nhiêu cái (chống giữ cả kho qua chat)
MAX_ACTIVE_HOLDS = 3                                # mỗi khách / cuộc chat tối đa bấy nhiêu hold đang giữ
MAX_RESULTS = 8
PLATFORM_CHANNELS = ('messenger', 'instagram', 'whatsapp', 'zalo', 'viber', 'sms')
COUNTRY_CURRENCY = {'US': 'USD', 'AU': 'AUD', 'VN': 'VND', 'CA': 'CAD', 'NZ': 'NZD', 'GB': 'GBP'}
VI_DOW = ('thứ Hai', 'thứ Ba', 'thứ Tư', 'thứ Năm', 'thứ Sáu', 'thứ Bảy', 'Chủ nhật')


def _fn(name, desc, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': desc,
                                             'parameters': {'type': 'object', 'properties': props, 'required': list(required)}}}


TOOLS = [
    _fn('retail_find_products',
        "Look up the store's real products by name, brand or category: price in the store currency and whether it is "
        "in stock / low / out of stock right now, plus how many can be held. ALWAYS call this before saying an item is "
        "available, and never promise more than can_hold_up_to.",
        {'query': {'type': 'string', 'description': 'What the customer is looking for, e.g. "fresh milk 1L" or a brand.'},
         'category': {'type': 'string', 'description': 'Optional category name from the store categories list.'}}),
    _fn('retail_hold_for_pickup',
        "Ask the store to set aside an in-stock item for the customer to collect and pay for in store. Creates a REAL hold "
        "REQUEST that the staff confirm (status pending) — it is not confirmed or paid. Needs the product_id from "
        "retail_find_products, the quantity, the customer's name and phone number. Confirm item + quantity with the "
        "customer before calling.",
        {'product_id': {'type': 'integer', 'description': 'product_id from retail_find_products.'},
         'quantity': {'type': 'integer', 'description': f'How many to hold (1-{MAX_HOLD_QTY}, never above can_hold_up_to).'},
         'customer_name': {'type': 'string', 'description': "Customer's name."},
         'phone': {'type': 'string', 'description': "Customer's phone number (ask for it if you don't have it)."},
         'note': {'type': 'string', 'description': 'Optional note for the staff (size, colour, pickup time).'}},
        ['product_id', 'quantity']),
    _fn('retail_my_holds',
        "List the pickup holds that belong to THIS customer (made in this chat, or under their verified phone number), "
        "with status and pickup deadline. If it fails with not_verified, say nothing about any hold and pass on the message.",
        {}),
    _fn('retail_cancel_hold',
        "Cancel one of THIS customer's own pickup holds (hold_id from retail_my_holds). Ask the customer to confirm first.",
        {'hold_id': {'type': 'integer'}}, ['hold_id']),
]
MANAGE_TOOLS = {'retail_my_holds', 'retail_cancel_hold'}

PROMPT_RULES = {
    'en': ("STORE RULES: Stock and prices come only from retail_find_products — never guess whether something is in stock "
           "and never promise more than can_hold_up_to. A pickup hold is a request the staff confirm: say \"I've asked the "
           "store to set it aside — they'll confirm\", never \"it's reserved\" or \"guaranteed\". Before holding, get the "
           "exact item, quantity, the customer's name and phone number. Payment happens in store at pickup; never take or "
           "mention card details. Holds end at the pickup deadline the tool returns. No delivery, shipping or online "
           "payment is offered in this chat unless the facts say so — use ask_team for anything not in the data."),
    'vi': ("LUẬT CỬA HÀNG: Còn hàng và giá CHỈ lấy từ retail_find_products — không bao giờ đoán còn hay hết và không hứa "
           "quá can_hold_up_to. Giữ hàng là YÊU CẦU, nhân viên xác nhận: nói \"em đã báo cửa hàng giữ, cửa hàng sẽ xác nhận "
           "lại\", không nói \"đã giữ chắc\". Trước khi giữ cần đúng món, số lượng, tên và số điện thoại của khách. Khách trả "
           "tiền tại cửa hàng khi tới lấy; không bao giờ hỏi thông tin thẻ. Hàng giữ tới hạn lấy mà công cụ trả về. Chat "
           "này không giao hàng hay thanh toán online trừ khi dữ liệu ghi rõ — thiếu dữ liệu thì dùng ask_team."),
}


# ------------------------------------------------------------------ tiện ích chung
def _err(msg):
    return ai_packs.PackError(msg)


def _bid(ctx):
    b = ctx.get('business_id')
    if not b or not isinstance(b, str):
        raise _err('This chat is not linked to a business.')
    return b


def _now(ctx):
    """Giờ ĐỊA PHƯƠNG của tiệm, không múi giờ (cùng kiểu với giờ lưu trong db) — ctx.now_local là datetime có múi giờ."""
    n = ctx.get('now_local')
    if not isinstance(n, datetime):
        n = booking_rules.local_now(_bid(ctx))
    return n.replace(tzinfo=None, second=0, microsecond=0)


def _vi(ctx):
    return str(ctx.get('lang') or '').lower().startswith('vi')


def _int(v, what):
    try:
        if isinstance(v, bool):
            raise ValueError
        f = float(str(v).strip())
        if f != int(f):
            raise ValueError
        return int(f)
    except (TypeError, ValueError):
        raise _err(f'{what} must be a whole number.')


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


_CC = {'US': '1', 'CA': '1', 'AU': '61', 'NZ': '64', 'GB': '44', 'VN': '84'}


def _e164_local(phone, country=None):
    """Bản dự phòng của ai_packs.normalize_phone (cùng luật) khi registry chưa có hàm đó."""
    raw = str(phone or '').strip()
    d = re.sub(r'\D', '', raw)
    if not d:
        return ''
    if raw.startswith('+') or raw.startswith('00'):
        d = d if raw.startswith('+') else d[2:]
        return '+' + d if 8 <= len(d) <= 15 else ''
    c = str(country or 'US').upper()
    cc = _CC.get(c)
    if c in ('US', 'CA'):
        if len(d) == 10:
            return '+1' + d
        if len(d) == 11 and d.startswith('1'):
            return '+' + d
    elif cc:
        if d.startswith('0') and 9 <= len(d) <= 11:
            return '+' + cc + d[1:]
        if c == 'AU' and len(d) == 9 and d[0] in '23478':
            return '+61' + d
        if c == 'VN' and len(d) == 9 and d[0] in '35789':
            return '+84' + d
        if d.startswith(cc) and 10 <= len(d) <= 13:
            return '+' + d
    if 11 <= len(d) <= 15:
        return '+' + d
    return ''


def phone_key(phone, country=None):
    """SĐT dạng E.164 ĐẦY ĐỦ ('+61412345678'), hoặc None. So khớp quyền sở hữu bằng NGUYÊN số — không bao giờ so 'đuôi
    9 số' (ở Mỹ '(212) 345-6789' và '(312) 345-6789' trùng 9 số cuối)."""
    fn = getattr(ai_packs, 'normalize_phone', None)
    out = ''
    if callable(fn):
        try:
            out = fn(phone, country) or ''
        except Exception:
            out = ''
    return (out or _e164_local(phone, country)) or None


def phone_regex(phone, country=None):
    """Regex Mongo khớp ĐÚNG số này dù nhân viên gõ kiểu gì ('(312) 345-6789', '0412 345 678', '+61 412...'): neo 2 đầu,
    trước số quốc gia chỉ cho mã nước hoặc số 0 đầu — không khớp số khác có cùng đuôi."""
    e = phone_key(phone, country)
    d = re.sub(r'\D', '', e or '')
    if not 8 <= len(d) <= 15:
        return None
    cc = next((c for c in sorted(set(_CC.values()), key=len, reverse=True) if d.startswith(c) and len(d) - len(c) >= 7), '')
    nat = d[len(cc):]
    sp = r'\D*'.join
    prefix = (r'(?:(?:\+|00)?\D*' + sp(cc) + r'\D*|0\D*)?') if cc else r'(?:\+|00)?\D*'
    return r'^\D*' + prefix + sp(nat) + r'\D*$'


def _clean_phone(phone):
    raw = str(phone or '').strip()
    d = re.sub(r'\D', '', raw)
    if not 8 <= len(d) <= 15:
        return None
    return ('+' if raw.startswith('+') else '') + d


def _country(ctx, shop=None):
    return str(ctx.get('country') or (shop or {}).get('country') or '').upper() or None


def _contact(args, ctx, doing, shop=None):
    """(tên, SĐT, khoá SĐT E.164 | None) của khách — bắt buộc trước khi tạo yêu cầu. SĐT: khách đưa trong chat (tham số),
    không thì SĐT đã xác minh (ctx.phone), không thì SĐT khách đã gõ trước đó trong hội thoại (ctx.contact_phone)."""
    given = args.get('phone')
    if given not in (None, '') and not _clean_phone(given):
        raise _err(f"The phone number '{str(given)[:30]}' doesn't look valid — ask the customer to re-type it. Nothing was created.")
    raw = _clean_phone(given) or _clean_phone(ctx.get('phone')) or _clean_phone(ctx.get('contact_phone'))
    name = re.sub(r'\s+', ' ', str(args.get('customer_name') or ctx.get('customer_name') or '')).strip()[:80]
    if re.fullmatch(r"[\d\s+().-]*", name):
        name = ''
    missing = [w for w, ok in (('name', name), ('phone number', raw)) if not ok]
    if missing:
        raise _err(f"Ask the customer for their {' and '.join(missing)} before {doing}. Nothing was created.")
    key = phone_key(raw, _country(ctx, shop))
    return name, (key or raw), key


def real_token(ctx):
    """chat_token_hash chứng minh được trình duyệt / hội thoại (mã 'anon:' tạm của chat web không có mã thì KHÔNG)."""
    th = ctx.get('chat_token_hash')
    return th if isinstance(th, str) and th and not th.startswith('anon:') else None


def _typed_phone(ctx):
    """SĐT khách gõ trong CHÍNH chat web này (ctx.contact_phone, không thì id hội thoại web '<tiệm>:<SĐT>') — không bao giờ
    là bằng chứng một mình."""
    if ctx.get('contact_phone'):
        return str(ctx['contact_phone'])
    cid = str(ctx.get('customer_id') or '')
    if str(ctx.get('channel') or 'web').lower() == 'web' and ':' in cid:
        rest = cid.split(':', 1)[1].split('~', 1)[0].strip()
        return rest if re.fullmatch(r'\+?[0-9(][0-9 ().-]{5,31}', rest) else None
    return None


def owner_filter(ctx):
    """Điều kiện Mongo cho bản ghi CHỨNG MINH được là của khách đang chat, hoặc None (không chứng minh được).
    Chat web: mã chat của đúng trình duyệt KÈM đúng chat này — cùng hội thoại web, hoặc đúng SĐT (NGUYÊN số) khách gõ ở đây:
    1 máy tính bảng quầy dùng chung 1 mã trình duyệt, khách kế tiếp gõ SĐT khác không thấy / huỷ được hàng giữ của người
    trước. Id hội thoại web một mình ('<tiệm>:<SĐT tự gõ>', ai cũng gõ được) KHÔNG bao giờ là bằng chứng."""
    ors = []
    k = phone_key(ctx.get('phone'), _country(ctx))
    if k:
        ors.append({'phone_key': k})
    th = real_token(ctx)
    cid, ch = ctx.get('customer_id'), ctx.get('channel')
    if th and str(ch or 'web').lower() != 'web':
        ors.append({'chat_token_hash': th})   # 'conv:<băm>' của hội thoại nền tảng
    elif th:
        mine = [{'ai_conversation_id': cid}] if cid else []
        typed = phone_key(_typed_phone(ctx), _country(ctx))
        if typed:
            mine.append({'phone_key': typed})
        if mine:
            ors.append({'chat_token_hash': th, '$or': mine})
    if cid and ch in PLATFORM_CHANNELS and str(cid).startswith(f"{ctx.get('business_id')}:{ch}:"):
        ors.append({'ai_conversation_id': cid})
    return {'$or': ors} if ors else None


def _shop(business_id):
    return db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'country': 1, 'currency': 1}) or {}


def currency_of(business_id, shop=None):
    shop = shop if shop is not None else _shop(business_id)
    return (shop.get('currency') or COUNTRY_CURRENCY.get(str(shop.get('country') or '').upper()) or 'VND').upper()


def money(amount, cur):
    if cur in ('VND', 'USD', 'AUD'):
        return format_money(amount, cur)
    return f"{_num(amount):,.2f} {cur}"


def when_label(dt, vi):
    return f"{dt:%H:%M} {VI_DOW[dt.weekday()]} {dt:%d/%m}" if vi else dt.strftime('%a %d %b, %H:%M')


def _hours_line(rules):
    names = {'mon': 'Mon', 'tue': 'Tue', 'wed': 'Wed', 'thu': 'Thu', 'fri': 'Fri', 'sat': 'Sat', 'sun': 'Sun'}
    return 'OPENING HOURS: ' + ', '.join(f"{names.get(d, d)} {v[0]}-{v[1]}" if v else f"{names.get(d, d)} closed"
                                         for d, v in (rules.get('hours') or {}).items()) + '.'


def shop_vi(shop):
    """Ngôn ngữ của NGƯỜI TIỆM (ghi chú cho nhân viên): tiệm Việt Nam -> tiếng Việt, còn lại tiếng Anh."""
    return str((shop or {}).get('country') or '').upper() == 'VN'


def _notify(ctx, shop, staff_vi, staff_en, owner_text, kind, phone=None):
    """Ghi 1 dòng vào hộp thư /ai_bot (theo ngôn ngữ của tiệm) + email báo chủ tiệm (tối đa 1 thư / khách / giờ).
    Lỗi báo không làm hỏng yêu cầu đã lưu."""
    try:
        import ai_function_tools as aft
        cid = ctx.get('customer_id')
        if cid:
            aft._note_for_staff(ctx['business_id'], cid, staff_vi if shop_vi(shop) else staff_en)
        # chat web chưa có hội thoại: gom email theo SĐT khách (không gộp mọi khách ẩn danh vào 1 thư / giờ)
        aft._alert_owner(ctx['business_id'], cid or (f"{ctx['business_id']}:{phone}" if phone else ''), owner_text, kind)
    except Exception as e:
        print(f"[ai_packs.retail] notify: {e}")


def _fold(s):
    s = unicodedata.normalize('NFD', str(s or '').lower().replace('đ', 'd'))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def clean_email(v):
    e = str(v or '').strip()[:120]
    if e and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', e):
        raise _err(f"The email '{e[:40]}' doesn't look valid — ask the customer to re-type it, or leave it out. Nothing was created.")
    return e or None


# Index cho các collection MỚI của 4 gói yêu cầu (tạo lười 1 lần / tiến trình, lỗi không chặn việc ghi).
# dedupe_key unique: khách bấm/nói "gửi giúp em" 2 lần cùng lúc vẫn chỉ ra 1 yêu cầu.
def _unique_on(field):
    return ([('business_id', 1), (field, 1)], {'unique': True, 'partialFilterExpression': {field: {'$exists': True}}})


_UNIQUE_DEDUPE = _unique_on('dedupe_key')
INDEX_SPECS = {
    # active_key: chỉ có khi hold ĐANG GIỮ (xoá lúc huỷ / hết hạn / đã lấy) -> 1 khách chỉ 1 hold đang giữ cho 1 món
    'retail_holds': [([('business_id', 1), ('status', 1), ('expires_at_local', 1)], {}), ([('business_id', 1), ('id', 1)], {}),
                     _unique_on('active_key')],
    'quote_requests': [([('business_id', 1), ('id', 1)], {}), _UNIQUE_DEDUPE],
    'consultation_requests': [([('business_id', 1), ('id', 1)], {}), _UNIQUE_DEDUPE],
    # db.tasks có sẵn (bảng điều phối): chỉ thêm index 1 phần cho việc AI tạo (trường ai_dedupe_key chỉ việc AI tạo mới có)
    'tasks': [_unique_on('ai_dedupe_key')],
}
_INDEXES = set()


def ensure_indexes(name):
    if name in _INDEXES or name not in INDEX_SPECS:
        return
    try:
        for keys, opts in INDEX_SPECS[name]:
            db[name].create_index(keys, **opts)
        _INDEXES.add(name)
    except Exception as e:
        print(f"[ai_packs] index {name}: {e}")


def insert_once(coll, business_id, key, doc, key_field='dedupe_key'):
    """Tạo 1 yêu cầu NGUYÊN TỬ theo khoá chống trùng (upsert + $setOnInsert): (bản ghi đang lưu, True nếu vừa tạo).
    Cùng khách gửi lại cùng yêu cầu -> trả bản ghi cũ, không tạo dòng thứ 2."""
    ensure_indexes(getattr(coll, 'name', ''))
    flt = {'business_id': business_id, key_field: key}
    body = {k: v for k, v in doc.items() if k not in ('business_id', key_field)}
    try:
        saved = coll.find_one_and_update(flt, {'$setOnInsert': body}, upsert=True, projection={'_id': 0},
                                         return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:   # 2 lệnh upsert cùng lúc: unique index cho 1 lệnh thắng, lệnh kia đọc lại bản đã lưu
        saved = coll.find_one(flt, {'_id': 0})
    return saved, bool(saved) and saved.get('id') == doc.get('id')


def request_key(ctx, phone, *parts):
    """Khoá chống trùng: người gửi (hội thoại, hoặc SĐT) + nội dung chính + ngày tại tiệm."""
    who = ctx.get('customer_id') or phone_key(phone, _country(ctx)) or ''
    return hashlib.sha1('|'.join([str(who)] + [_fold(p) for p in parts]).encode('utf-8')).hexdigest()[:24]


def _active_key(ctx, business_id, product_id, pkey):
    """Khoá '1 hold đang giữ / 1 món / 1 khách': mã trình duyệt (hoặc hội thoại nền tảng), không có thì theo SĐT."""
    who = real_token(ctx)
    who = f"tok:{who}" if who else f"phone:{pkey or ''}"
    return hashlib.sha1(f"{business_id}|{product_id}|{who}".encode('utf-8')).hexdigest()[:32]


def _ensure_indexes():
    ensure_indexes('retail_holds')


# ------------------------------------------------------------------ tồn kho / hạn giữ
def _critical(business_id):
    """Ngưỡng "sắp hết" của tiệm (trang Cảnh báo tồn kho — cùng nguồn với messaging.low_stock), mặc định 5."""
    doc = db.system_settings.find_one({'key': 'inventory_thresholds', 'business_id': business_id}, {'value': 1, '_id': 0})
    try:
        return float(json.loads(doc['value']).get('critical', 5)) if doc else 5.0
    except (ValueError, TypeError, AttributeError, KeyError):
        return 5.0


def _available(p):
    return int(_num(p.get('stock')) - _num(p.get('held_qty')))


def _band(avail, critical):
    return 'out' if avail <= 0 else ('low' if avail <= critical else 'in_stock')


def hold_deadline(business_id, now_local):
    """Hạn lấy hàng = giờ ĐÓNG CỬA của ngày làm việc kế tiếp (giờ mở cửa chủ tiệm đã nhập); chưa nhập giờ -> hết ngày mai."""
    rules = booking_rules.get_rules(business_id)
    if rules.get('configured'):
        for i in range(1, 9):
            d = now_local.date() + timedelta(days=i)
            hrs = booking_rules.hours_on(rules, d)
            if hrs:
                end = min(hrs[1], 23 * 60 + 59)
                return datetime.combine(d, dtime(end // 60, end % 60))
    return datetime.combine(now_local.date() + timedelta(days=1), dtime(23, 59))


def _release(business_id, hold):
    try:
        db.products.update_one({'id': hold.get('product_id'), 'business_id': business_id}, {'$inc': {'held_qty': -int(hold.get('quantity') or 0)}})
        db.products.update_one({'id': hold.get('product_id'), 'business_id': business_id, 'held_qty': {'$lt': 0}}, {'$set': {'held_qty': 0}})
    except Exception as e:
        print(f"[ai_packs.retail] release: {e}")


def _transition(business_id, hold_id, new_status, extra_filter=None, by='customer_ai_chat'):
    """Đổi trạng thái 1 hold ĐANG GIỮ -> new_status (nguyên tử: chỉ 1 lệnh thắng). Rời trạng thái giữ thì trả held_qty.
    Trả hold TRƯỚC khi đổi, hoặc None nếu hold không còn ở trạng thái được phép đổi."""
    if new_status in ('cancelled', 'expired'):
        allowed_from = list(ACTIVE)
    else:
        allowed_from = [s for s, nxt in STAFF_NEXT.items() if new_status in nxt]
    flt = {'id': hold_id, 'business_id': business_id, 'status': {'$in': allowed_from}}
    flt.update(extra_filter or {})
    now = datetime.now().isoformat()
    upd = {'$set': {'status': new_status, f'{new_status}_at': now, 'updated_at': now, 'updated_by': by}}
    if new_status not in ACTIVE:
        upd['$unset'] = {'active_key': ''}   # hết giữ -> khách giữ lại món này được
    before = db.retail_holds.find_one_and_update(flt, upd)
    if before and before.get('status') in ACTIVE and new_status not in ACTIVE:
        _release(business_id, before)
    return before


def release_expired_holds(business_id, now_local=None):
    """Hold quá hạn lấy -> 'expired' + trả lại hàng. Gọi lười trước mọi lần đọc tồn/hold (không cần cron)."""
    now_local = (now_local or booking_rules.local_now(business_id)).replace(tzinfo=None)
    cutoff = now_local.strftime('%Y-%m-%dT%H:%M')
    n = 0
    for h in list(db.retail_holds.find({'business_id': business_id, 'status': {'$in': list(ACTIVE)},
                                        'expires_at_local': {'$lt': cutoff}}, {'_id': 0, 'id': 1}).limit(200)):
        if _transition(business_id, h['id'], 'expired', by='expiry'):
            n += 1
    return n


def staff_set_status(business_id, hold_id, new_status, by='staff'):
    """Nhân viên đổi trạng thái hold trên /retail/holds (retail_holds_bp.py): pending -> ready / picked_up / cancelled,
    ready -> picked_up / cancelled. Trả (hold sau khi đổi | None, lỗi | None)."""
    if new_status not in ('ready', 'picked_up', 'cancelled'):
        return None, 'bad_status'
    before = _transition(business_id, hold_id, new_status, by=by)
    if not before:
        return None, 'not_allowed'
    return db.retail_holds.find_one({'id': hold_id, 'business_id': business_id}, {'_id': 0}), None


def _recount_held(business_id, product_id):
    """Sửa held_qty lệch (vd tiến trình chết giữa 2 lệnh ghi): đặt lại = tổng hold đang giữ. Có điều kiện để không đè lệnh khác."""
    p = db.products.find_one({'id': product_id, 'business_id': business_id}, {'_id': 0, 'held_qty': 1}) or {}
    actual = sum(int(h.get('quantity') or 0) for h in db.retail_holds.find(
        {'business_id': business_id, 'product_id': product_id, 'status': {'$in': list(ACTIVE)}}, {'_id': 0, 'quantity': 1}))
    if int(_num(p.get('held_qty'))) > actual:
        db.products.update_one({'id': product_id, 'business_id': business_id, 'held_qty': p.get('held_qty')},
                               {'$set': {'held_qty': actual}})
        return True
    return False


def _reserve(business_id, product_id, qty):
    """+qty vào held_qty CHỈ KHI (stock - held_qty) >= qty — 1 lệnh nguyên tử, không bao giờ giữ quá tồn."""
    return db.products.find_one_and_update(
        {'id': product_id, 'business_id': business_id,
         '$expr': {'$gte': [{'$subtract': [{'$ifNull': ['$stock', 0]}, {'$ifNull': ['$held_qty', 0]}]}, qty]}},
        {'$inc': {'held_qty': qty}}, projection={'_id': 0, 'id': 1, 'stock': 1, 'held_qty': 1},
        return_document=ReturnDocument.AFTER)


def _public_hold(h, cur, vi):
    exp = h.get('expires_at_local')
    try:
        exp_label = when_label(datetime.fromisoformat(exp), vi) if exp else None
    except ValueError:
        exp_label = exp
    return {'hold_id': h.get('id'), 'product': h.get('product_name'), 'quantity': h.get('quantity'),
            'total': money(_num(h.get('unit_price')) * int(h.get('quantity') or 0), cur), 'status': h.get('status'),
            'pickup_by': exp_label if h.get('status') in ACTIVE else None,
            'status_meaning': {'pending': 'requested — the store has not confirmed yet',
                               'ready': 'confirmed by the store and set aside for pickup',
                               'picked_up': 'collected', 'cancelled': 'cancelled',
                               'expired': 'pickup deadline passed — the item was released'}.get(h.get('status'), h.get('status'))}


# ------------------------------------------------------------------ công cụ
def find_products(args, ctx):
    bid = _bid(ctx)
    q = str(args.get('query') or '').strip()[:80]
    cat = str(args.get('category') or '').strip()[:60]
    tokens = [t for t in re.split(r'[^0-9a-z]+', _fold(q)) if t]
    if not tokens and not cat:
        raise _err('Give a product name, brand or category to look up.')
    release_expired_holds(bid, _now(ctx))
    rows = list(db.products.find({'business_id': bid, 'is_active': {'$in': [1, True]}, 'channel_type': 'retail'},
                                 {'_id': 0, 'id': 1, 'name': 1, 'category': 1, 'price': 1, 'stock': 1, 'held_qty': 1,
                                  'barcode': 1}).limit(3000))
    fq, fcat = _fold(q), _fold(cat)
    # tìm không dấu: "sua tuoi" khớp "Sữa tươi", khớp cả tên + nhóm hàng + mã vạch
    pool = [(p, _fold(f"{p.get('name') or ''} {p.get('category') or ''} {p.get('barcode') or ''}"))
            for p in rows if not fcat or fcat in _fold(p.get('category'))]
    hits = [p for p, hay in pool if all(t in hay for t in tokens)]
    exact = True
    if not hits and tokens:  # không khớp đủ mọi chữ: gợi ý món gần nhất (khớp 1 chữ dài >= 3), báo rõ là gần đúng
        hits = [p for p, hay in pool if any(len(t) >= 3 and t in hay for t in tokens)]
        exact = False
    hits.sort(key=lambda p: (0 if _fold(p.get('name')) == fq else 1 if _fold(p.get('name')).startswith(fq) else 2,
                             str(p.get('name') or '')))
    shop = _shop(bid)
    cur, crit = currency_of(bid, shop), _critical(bid)
    out = []
    for p in hits[:MAX_RESULTS]:
        avail = _available(p)
        out.append({'product_id': p.get('id'), 'name': p.get('name'), 'category': p.get('category'),
                    'price': money(p.get('price'), cur), 'availability': _band(avail, crit),
                    'can_hold_up_to': max(0, min(avail, MAX_HOLD_QTY))})
    res = {'success': True, 'matches': out, 'exact_match': exact, 'currency': cur}
    if len(hits) > MAX_RESULTS:
        res['more_matches'] = len(hits) - MAX_RESULTS
    if not out:
        res['note'] = ("No product in the store matches. Don't guess or suggest other shops — say you couldn't find it "
                       "and offer ask_team if they want the store to check.")
    elif not exact:
        res['note'] = 'Closest matches only — check with the customer that one of these is what they mean.'
    return res


def hold_for_pickup(args, ctx):
    bid = _bid(ctx)
    pid = _int(args.get('product_id'), 'product_id')
    qty = _int(args.get('quantity') if args.get('quantity') not in (None, '') else 1, 'quantity')
    if not 1 <= qty <= MAX_HOLD_QTY:
        raise _err(f'Quantity must be between 1 and {MAX_HOLD_QTY} for a pickup hold. Nothing was held.')
    shop = _shop(bid)
    name, phone, pkey = _contact(args, ctx, 'holding an item', shop)
    now = _now(ctx)
    vi = _vi(ctx)
    _ensure_indexes()
    release_expired_holds(bid, now)
    p = db.products.find_one({'id': pid, 'business_id': bid, 'is_active': {'$in': [1, True]}, 'channel_type': 'retail'},
                             {'_id': 0, 'id': 1, 'name': 1, 'price': 1, 'stock': 1, 'held_qty': 1})
    if not p:
        raise _err(f'There is no product_id {pid} in this store — use retail_find_products and its product_id. Nothing was held.')
    cur = currency_of(bid, shop)
    own = owner_filter(ctx)
    cid = ctx.get('customer_id')
    if own:  # chỉ so với hold CHỨNG MINH được là của khách này (không lộ hold của người khác)
        same = db.retail_holds.find_one({'business_id': bid, 'product_id': pid, 'status': {'$in': list(ACTIVE)}, **own}, {'_id': 0})
        if same:  # khách nói "giữ giúp em" 2 lần -> không giữ thêm, báo lại hold cũ
            return {'success': True, 'already_held': True, **_public_hold(same, cur, vi),
                    'note': 'This customer already has an active hold for this item — do not create another. To change '
                            'the quantity, cancel it (retail_cancel_hold) and hold again.'}
    caps = ([own] if own else []) + ([{'phone_key': pkey}] if pkey else [{'customer_phone': phone}])
    if any(db.retail_holds.count_documents({'business_id': bid, 'status': {'$in': list(ACTIVE)}, **c}) >= MAX_ACTIVE_HOLDS
           for c in caps):
        raise _err(f'This customer / phone number already has the maximum of {MAX_ACTIVE_HOLDS} active holds. Nothing new '
                   'was held — they can cancel one (retail_my_holds) or ask_team for a bigger order.')
    reserved = _reserve(bid, pid, qty)
    if reserved is None and _recount_held(bid, pid):
        reserved = _reserve(bid, pid, qty)
    if reserved is None:
        fresh = db.products.find_one({'id': pid, 'business_id': bid}, {'_id': 0, 'stock': 1, 'held_qty': 1}) or {}
        avail = max(0, _available(fresh))
        if avail <= 0:
            raise _err(f"'{p.get('name')}' is out of stock right now (nothing left that can be held). Nothing was held.")
        raise _err(f"Only {avail} of '{p.get('name')}' can be held right now — offer to hold {avail} instead. Nothing was held.")
    deadline = hold_deadline(bid, now)
    hold_id = next_mongo_id('retail_holds')
    note = re.sub(r'\s+', ' ', str(args.get('note') or '')).strip()[:300]
    akey = _active_key(ctx, bid, pid, pkey or phone)
    doc = {'id': hold_id, 'business_id': bid, 'product_id': pid, 'product_name': p.get('name'),
           'unit_price': _num(p.get('price')), 'currency': cur, 'quantity': qty, 'customer_name': name,
           'customer_phone': phone, 'phone_key': pkey, 'note': note, 'status': 'pending', 'active_key': akey,
           'expires_at_local': deadline.strftime('%Y-%m-%dT%H:%M'), 'created_at': datetime.now().isoformat(),
           'created_at_local': now.strftime('%Y-%m-%dT%H:%M'), 'source': 'ai_bot', 'ai_conversation_id': cid,
           'chat_token_hash': ctx.get('chat_token_hash') or None, 'channel': ctx.get('channel') or 'web'}
    try:
        db.retail_holds.insert_one(doc)
    except DuplicateKeyError:   # cùng khách bấm "giữ" 2 lần cùng lúc: unique active_key cho 1 lệnh thắng
        _release(bid, {'product_id': pid, 'quantity': qty})
        same = db.retail_holds.find_one({'business_id': bid, 'active_key': akey, **own}, {'_id': 0}) if own else None
        if same:
            return {'success': True, 'already_held': True, **_public_hold(same, cur, vi),
                    'note': 'This customer already has an active hold for this item — do not create another.'}
        raise _err('A pickup hold for this item is already waiting under these details — nothing new was held. The store '
                   'will confirm it; for changes use ask_team.')
    except Exception as e:
        _release(bid, {'product_id': pid, 'quantity': qty})
        raise _err(f'The hold could not be saved ({str(e)[:80]}). Nothing was held — use ask_team.')
    doc.pop('_id', None)
    total = money(_num(p.get('price')) * qty, cur)
    _notify(ctx, shop,
            f"Khách nhờ GIỮ HÀNG chờ lấy #{hold_id} (AI tạo, chờ nhân viên xác nhận ở trang Giữ hàng): {qty} x {p.get('name')} — "
            f"{name} {phone}. Hạn lấy {deadline:%H:%M %d/%m}." + (f" Ghi chú: {note}" if note else ''),
            f"Pickup hold request #{hold_id} from the AI chat (please confirm on the Pickup holds page): {qty} x {p.get('name')} — "
            f"{name} {phone}. Pickup by {deadline:%a %d %b %H:%M}." + (f" Note: {note}" if note else ''),
            f"Pickup hold request #{hold_id}: {qty} x {p.get('name')} ({total}) for {name} {phone}, pickup by "
            f"{deadline:%a %d %b %H:%M}. Confirm it on the Pickup holds page.", 'retail_hold', phone)
    tell = (f"Em đã gửi yêu cầu giữ {qty} {p.get('name')} (tổng {total}). Cửa hàng sẽ xác nhận lại; nếu được xác nhận, hàng "
            f"được giữ tới {when_label(deadline, True)}. Mình thanh toán tại cửa hàng khi tới lấy." if vi else
            f"I've asked the store to hold {qty} x {p.get('name')} ({total} total). The staff will confirm; once confirmed "
            f"it's kept for you until {when_label(deadline, False)}. You pay in store when you pick it up.")
    return {'success': True, 'hold_id': hold_id, 'status': 'pending', 'product': p.get('name'), 'quantity': qty,
            'total': total, 'pickup_by': when_label(deadline, vi), 'expires_at': doc['expires_at_local'],
            'tell_customer': tell, 'note': 'Status is pending: never say it is confirmed, reserved or guaranteed. Nothing was charged.'}


def _not_verified(ctx, what_vi='yêu cầu giữ hàng', what_en='holds'):
    """Lỗi trả cho AI khi cuộc chat KHÔNG chứng minh được là chủ yêu cầu: không xem / không đổi gì, chỉ đường cho khách."""
    phone = ''
    try:
        phone = booking_rules.business_phone(_bid(ctx))
    except Exception:
        pass
    if _vi(ctx):
        tell = (f"Vì bảo mật, em chỉ xem được {what_vi} tạo trong khung chat này. "
                + (f"Mình gọi số {phone} nhé." if phone else 'Mình gọi điện cho bên em nhé.'))
    else:
        tell = (f"For your security I can only see {what_en} made in this chat. "
                + (f"Please call us on {phone}." if phone else 'Please give us a call.'))
    return _err(f"not_verified: do not reveal, cancel or change anything existing. Tell the customer: {tell}")


def my_holds(args, ctx):
    bid = _bid(ctx)
    own = owner_filter(ctx)
    if own is None:
        raise _not_verified(ctx)
    release_expired_holds(bid, _now(ctx))
    cur, vi = currency_of(bid), _vi(ctx)
    rows = list(db.retail_holds.find({'business_id': bid, **own}, {'_id': 0}).sort('id', -1).limit(10))
    rows.sort(key=lambda h: h.get('status') not in ACTIVE)
    res = {'success': True, 'holds': [_public_hold(h, cur, vi) for h in rows]}
    if not rows:
        res['note'] = ('No holds found for this chat' + (' or phone number.' if phone_key(ctx.get('phone'), _country(ctx)) else '.')
                       + ' Holds made another way (in store, by phone) may not show here.')
    return res


def cancel_hold(args, ctx):
    bid = _bid(ctx)
    hid = _int(args.get('hold_id'), 'hold_id')
    own = owner_filter(ctx)
    if own is None:
        raise _not_verified(ctx)
    before = _transition(bid, hid, 'cancelled', extra_filter=own)
    if before:
        _notify(ctx, _shop(bid),
                f"Khách tự huỷ yêu cầu giữ hàng #{hid} ({before.get('quantity')} x {before.get('product_name')}) qua chat AI.",
                f"The customer cancelled pickup hold #{hid} ({before.get('quantity')} x {before.get('product_name')}) in the AI chat.",
                f"Pickup hold #{hid} ({before.get('quantity')} x {before.get('product_name')}) was cancelled by the customer.",
                'retail_hold_cancel', before.get('customer_phone'))
        return {'success': True, 'hold_id': hid, 'status': 'cancelled', 'product': before.get('product_name'),
                'quantity': before.get('quantity')}
    h = db.retail_holds.find_one({'id': hid, 'business_id': bid, **own}, {'_id': 0, 'id': 1, 'status': 1})
    if h:
        return {'success': True, 'hold_id': hid, 'already': h.get('status'),
                'note': f"This hold is already {h.get('status')} — nothing to cancel."}
    raise _err(f"Hold {hid} is not one of this customer's holds in this chat. Nothing was changed — check retail_my_holds.")


# ------------------------------------------------------------------ dữ kiện cho prompt
def facts(business_id, lang, now_local):
    """Dữ kiện RIÊNG của gói. Giờ mở cửa, thông tin tiệm (địa chỉ, SĐT, đỗ xe...) và kho câu hỏi của chủ tiệm do
    customer_context.facts thêm cho mọi gói — không lặp lại ở đây."""
    now = (now_local or booking_rules.local_now(business_id)).replace(tzinfo=None)
    rules = booking_rules.get_rules(business_id)
    lines = ["PRODUCTS: price and stock change all the time — for ANY item call retail_find_products (live price in the "
             "store currency + in stock / low / out) before answering; never answer availability from memory."]
    try:
        cats = sorted({str(c).strip() for c in db.products.distinct(
            'category', {'business_id': business_id, 'is_active': {'$in': [1, True]}, 'channel_type': 'retail'}) if c and str(c).strip()})
    except Exception:
        cats = []
    if cats:
        lines.append('STORE CATEGORIES: ' + ', '.join(cats[:25]) + '.')
    deadline = hold_deadline(business_id, now)
    lines.append(f"PICKUP HOLDS: customers can ask the store to set aside up to {MAX_HOLD_QTY} of an item that "
                 f"retail_find_products shows can be held (max {MAX_ACTIVE_HOLDS} active holds per customer). It is a REQUEST "
                 f"the staff confirm (status pending). A hold made now lasts until {when_label(deadline, False)} "
                 f"({'closing time of the next business day' if rules.get('configured') else 'end of tomorrow'}), then the item "
                 "is released automatically. Payment is in store at pickup — nothing is paid or charged in this chat. "
                 f"Prices are in {currency_of(business_id)}.")
    return '\n'.join(lines)


_HANDLERS = {'retail_find_products': find_products, 'retail_hold_for_pickup': hold_for_pickup,
             'retail_my_holds': my_holds, 'retail_cancel_hold': cancel_hold}


def execute(name, args, ctx):
    fn = _HANDLERS.get(name)
    if fn is None:
        raise _err(f"Unknown retail tool '{name}'.")
    return fn(args if isinstance(args, dict) else {}, ctx or {})
