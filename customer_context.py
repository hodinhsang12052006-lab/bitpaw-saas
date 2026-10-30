"""
What the customer-facing AI may know about a shop — PUBLIC facts only (Phase 2).

Used by every customer chat (booking-page web chat, Messenger, Instagram, WhatsApp, Zalo, Viber, SMS) and by the owner's
reply drafts. Sources, all written by the owner for customers to see:
  - db.businesses: name, industry, currency, country, phone, address
  - booking_rules (Booking settings page): opening hours, business info (address, parking, payments, gift cards,
    cancellation policy, other notes)
  - db.products: services / menu / items with prices in the SHOP currency
  - ai_knowledge (AI knowledge base page): the owner's question/answer pairs and policies
  - the industry's booking pack (ai_packs): its own facts (capacity rules, room rates...)
Never: revenue, other customers, loyalty tiers, purchase history, BitPaw/SaaS wording or upsell instructions.
"""
import re
from datetime import datetime

from mongo_client import db
from currency_utils import format_money

import booking_rules

_VI_RE = re.compile(r'[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]'
                    r'|\b(khong|duoc|bao nhieu|nhieu|em oi|anh oi|chi oi|minh|cho em|cua|nhe|nha|vay|gium|giup|tiem|quan)\b', re.I)
_PLACEHOLDER_NAME_RE = re.compile(r'^(client|khách|customer)\b', re.I)
DAY_NAMES = {'mon': 'Mon', 'tue': 'Tue', 'wed': 'Wed', 'thu': 'Thu', 'fri': 'Fri', 'sat': 'Sat', 'sun': 'Sun'}

# Customer-facing words per industry (en, vi). 'technician' only for nail, 'therapist' for spa (plan: vocabulary per pack;
# prompts for the other 7 industries must not contain 'salon', 'technician' or 'manicure').
INDUSTRY_WORDS = {
    'nail': {'place': ('nail salon', 'tiệm nail'), 'team': ('technician', 'thợ')},
    'spa': {'place': ('spa', 'spa'), 'team': ('therapist', 'kỹ thuật viên')},
    'fnb': {'place': ('restaurant', 'nhà hàng / quán'), 'team': ('staff', 'nhân viên')},
    'karaoke': {'place': ('karaoke & billiards venue', 'quán karaoke / bida'), 'team': ('staff', 'nhân viên')},
    'hotel': {'place': ('hotel / homestay', 'khách sạn / homestay'), 'team': ('front desk', 'lễ tân')},
    'retail': {'place': ('shop', 'cửa hàng'), 'team': ('staff', 'nhân viên')},
    'technical': {'place': ('repair & technical service', 'dịch vụ sửa chữa / kỹ thuật'), 'team': ('service team', 'đội kỹ thuật')},
    'production': {'place': ('workshop', 'xưởng sản xuất'), 'team': ('team', 'đội ngũ')},
    'office': {'place': ('office', 'văn phòng'), 'team': ('team', 'đội ngũ')},
}


def _norm_industry(code):
    code = str(code or '').strip().lower()
    return {'nails': 'nail'}.get(code, code)


def business(business_id):
    """Public profile of the shop (cached ~20 s like the booking rules)."""
    def _load():
        b = {}
        try:
            b = db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'industry_code': 1, 'currency': 1,
                                                             'country': 1, 'phone': 1, 'address': 1}) or {}
        except Exception as e:
            print(f"[customer_context] business: {e}")
        name = str(b.get('name') or '').strip()
        if '@' in name:   # old accounts used the owner's e-mail as the shop name — never show it to customers
            name = ''
        profile_country = (b.get('country') or '').upper() or None
        try:   # 'country' = the ONE shop country every phone normaliser uses (profile -> Messaging time zone -> currency)
            import ai_packs
            country = ai_packs.shop_country(dict(b, id=business_id))
        except Exception as e:
            print(f"[customer_context] country: {e}")
            country = profile_country
        return {'id': business_id, 'name': name or None, 'industry': _norm_industry(b.get('industry_code')) or None,
                'currency': (b.get('currency') or 'VND').upper(), 'country': country, 'profile_country': profile_country,
                'phone': str(b.get('phone') or '').strip(), 'address': str(b.get('address') or '').strip()}
    if not business_id:
        return {'id': None, 'name': None, 'industry': None, 'currency': 'VND', 'country': None, 'profile_country': None,
                'phone': '', 'address': ''}
    return booking_rules._cached(('cc_business', business_id), _load)


def currency_of(business_id):
    return business(business_id)['currency']


def money(business_id, amount):
    return format_money(amount or 0, currency_of(business_id))


def tz_name(business_id):
    """Same source as booking_rules.local_now: Messaging settings time zone, else the main zone of the country on the shop
    profile (profile_country — not a country guessed from the currency, which booking_rules.local_now does not use either)."""
    def _load():
        try:
            t = (db.messaging_settings.find_one({'business_id': business_id}, {'_id': 0, 'timezone': 1}) or {}).get('timezone')
        except Exception:
            t = None
        return t or booking_rules.COUNTRY_TZ.get(business(business_id).get('profile_country') or '')
    return booking_rules._cached(('cc_tz', business_id), _load) if business_id else None


def now_local(business_id):
    """Timezone-aware 'now' at the shop (server zone only when the shop has no zone and no known country)."""
    from zoneinfo import ZoneInfo
    tz = tz_name(business_id)
    try:
        return datetime.now(ZoneInfo(tz)) if tz else datetime.now().astimezone()
    except Exception:
        return datetime.now().astimezone()


def detect_lang(text, default='en'):
    if not isinstance(text, str) or not text.strip():
        return default
    return 'vi' if _VI_RE.search(text) else 'en'


def words(industry, lang='en'):
    w = INDUSTRY_WORDS.get(_norm_industry(industry)) or {'place': ('business', 'cửa hàng'), 'team': ('staff', 'nhân viên')}
    i = 1 if lang == 'vi' else 0
    return {k: v[i] for k, v in w.items()}


def is_placeholder_name(name):
    return not name or bool(_PLACEHOLDER_NAME_RE.match(str(name).strip()))


# ---------------------------------------------------------------- blocks
def identity_block(business_id):
    """1-2 lines: who the AI answers for. AIContextEngine (audience='customer') returns this as the tenant context."""
    b = business(business_id)
    if not b['name']:
        return ''
    place = words(b['industry'])['place']
    return f"BUSINESS: {b['name']}" + (f" — a {place}." if b['industry'] else '.')


def info_items(business_id, rules=None):
    """[(label, value)] the owner published: address (Booking settings, else the shop profile), phone, parking, payments..."""
    rules = rules or booking_rules.get_rules(business_id)
    info = dict(rules.get('info') or {})
    b = business(business_id)
    if not str(info.get('address') or '').strip() and b['address']:
        info['address'] = b['address']
    items = []
    try:
        phone = booking_rules.business_phone(business_id)
    except Exception:
        phone = b['phone']
    if phone:
        items.append(('Phone', phone))
    for k in booking_rules.DEFAULTS['info']:
        v = ' '.join(str(info.get(k) or '').split())
        if v:
            items.append((booking_rules.INFO_LABELS.get(k, k), v))
    return items


def info_line(business_id, rules=None, appointment=False):
    items = info_items(business_id, rules)
    head = ('BUSINESS INFO (only these facts are confirmed — for anything else, say you will check with the team): '
            if appointment else 'BUSINESS INFO (only these facts are confirmed): ')
    return head + ('; '.join(f"{k}: {v}" for k, v in items) if items else 'none published yet.')


def _ampm(m):
    h, mi = divmod(int(m) % (24 * 60), 60)
    return f"{h % 12 or 12}:{mi:02d} {'am' if h < 12 else 'pm'}"


def _day_hours(d, v):
    """'Mon 09:00-19:00' / 'Tue closed'. A day open PAST midnight (closing time earlier than opening time — only reservation
    venues can save it, booking_rules.save_rules allow_overnight) states the real close and the next day:
    'Fri 6:00 pm – 2:00 am (Sat)'. Before: 'Fri 18:00-02:00', easy to read as closing at 2 am the SAME day."""
    name = DAY_NAMES.get(d, d)
    if not v:
        return f"{name} closed"
    try:
        o, c = booking_rules._hm(v[0]), booking_rules._hm(v[1])
    except (ValueError, IndexError, TypeError):
        o = c = None
    if o is not None and 0 < c < o and d in booking_rules.DAY_KEYS:
        nxt = booking_rules.DAY_KEYS[(booking_rules.DAY_KEYS.index(d) + 1) % 7]
        return f"{name} {_ampm(o)} – {_ampm(c)} ({DAY_NAMES[nxt]})"
    return f"{name} {v[0]}-{v[1]}"


def hours_lines(business_id, rules=None, include_defaults=False):
    """OPENING HOURS + RIGHT NOW. Default hours (9-19) are NOT the shop's real hours, so they are only shown where bookings
    are really checked against them (appointment pack, include_defaults=True)."""
    rules = rules or booking_rules.get_rules(business_id)
    if not rules.get('configured') and not include_defaults:
        return []
    hours = ', '.join(_day_hours(d, v) for d, v in (rules.get('hours') or {}).items())
    out = [f"OPENING HOURS: {hours}."]
    try:
        st = booking_rules.open_status(business_id, rules)
        out.append('RIGHT NOW: ' + (f"open until {st['closes_at']}." if st['open_now'] else
                                    f"closed — next opening {st['next_open'] or 'not set'}. A team member can reply when the business opens."))
    except Exception as e:
        print(f"[customer_context] open status: {e}")
    return out


def catalog_items(business_id, limit=60):
    try:
        return list(db.products.find({'business_id': business_id, 'is_active': 1},
                                     {'_id': 0, 'id': 1, 'name': 1, 'price': 1}).limit(limit))
    except Exception as e:
        print(f"[customer_context] products: {e}")
        return []


def price_list(business_id, header, limit=60):
    items = catalog_items(business_id, limit)
    if not items:
        return ''
    cur = currency_of(business_id)
    return header + "\n" + "\n".join(f"- {s.get('name')} — {format_money(s.get('price') or 0, cur)}" for s in items)


def knowledge_block(business_id):
    try:
        import ai_knowledge
        return ai_knowledge.prompt_block(business_id)
    except Exception as e:
        print(f"[customer_context] knowledge: {e}")
        return ''


def facts(business_id, pack=None, now_str=None, weekday=None, lang='en'):
    """Everything public the customer AI needs this turn, as one text block (the 'booking facts' layer of the prompt).
    pack=None -> questions + handoff (price list is information only, link to the shop's own reservation form).
    pack.resource == 'appointment' -> the built-in nail/spa pack (service ids + durations + booking rules).
    other packs -> the pack's own facts + the generic public facts."""
    if not now_str:
        now_str = now_local(business_id).strftime('%Y-%m-%dT%H:%M') if business_id else datetime.now().strftime('%Y-%m-%dT%H:%M')
    if not weekday:
        try:
            weekday = datetime.fromisoformat(now_str).strftime('%A')
        except ValueError:
            weekday = ''
    lines = []
    if pack is None:
        lines.append(f"CURRENT LOCAL DATE/TIME AT THE BUSINESS: {now_str} ({weekday}). Use it to understand 'today', 'tomorrow', "
                     f"'Friday'... when you pass a request to the team.")
    elif pack.resource == 'appointment':
        lines.append(f"CURRENT LOCAL DATE/TIME AT THE BUSINESS: {now_str} ({weekday}). Resolve 'today', 'tomorrow', "
                     f"'this Friday', 'chiều mai'... from this, and pass appointment_time as local time without timezone "
                     f"(e.g. 2026-08-01T15:00:00). Never book a time in the past.")
    else:
        tz = tz_name(business_id)
        lines.append(f"CURRENT LOCAL DATE/TIME AT THE BUSINESS: {now_str} ({weekday}{', ' + tz if tz else ''}). Resolve 'today', "
                     f"'tomorrow', 'Friday night', 'tối mai'... from this and give tools dates/times in this local time. "
                     f"Never book anything in the past.")
    if not business_id or db is None:
        return "\n\n".join(lines)
    try:
        rules = booking_rules.get_rules(business_id)
    except Exception as e:
        print(f"[customer_context] rules: {e}")
        rules = {'configured': False, 'info': {}, 'hours': {}}
    try:
        if pack is None:
            pl = price_list(business_id, "PRICE LIST (information only — nothing here can be booked, reserved, held or ordered in this chat):")
            if pl:
                lines.append(pl)
            hours = hours_lines(business_id, rules)
            if hours:
                lines.append("\n".join(hours))
            lines.append(info_line(business_id, rules))
        else:
            pf = pack.facts(business_id, lang, now_local(business_id))
            if pf:
                lines.append(pf)
            if pack.resource != 'appointment' and not pack.facts_include_catalog:
                pl = price_list(business_id, "PRICE LIST (from the business's product list, for information — bookings go only "
                                             "through the booking tools):")
                if pl:
                    lines.append(pl)
            hours = hours_lines(business_id, rules, include_defaults=pack.resource == 'appointment')
            if hours:
                lines.append("\n".join(hours))
            lines.append(info_line(business_id, rules, appointment=True))
        kb = knowledge_block(business_id)
        if kb:
            lines.append(kb)
        if pack is None:
            import ai_function_tools
            link = ai_function_tools.reservation_link(business_id)
            if link:
                lines.append(f"ONLINE RESERVATION PAGE (the business's own form; the business confirms each request): {link}")
    except Exception as e:
        print(f"[customer_context] facts: {e}")
    return "\n\n".join(x for x in lines if x)


def build(business_id, pack=None, lang='en', now_str=None):
    """Customer prompt context in one call: {'prompt': identity + facts, 'business_name', 'industry', 'currency'}."""
    b = business(business_id)
    text = "\n\n".join(x for x in (identity_block(business_id), facts(business_id, pack, now_str, lang=lang)) if x)
    return {'prompt': text, 'business_name': b['name'], 'industry': b['industry'], 'currency': b['currency']}
