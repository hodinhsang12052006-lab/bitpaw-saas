"""
Booking packs — ONE receptionist engine for all 9 industries, tools chosen per industry (Phase 2).

The customer-facing AI (booking-page web chat, Messenger, Instagram, WhatsApp, Zalo, Viber, SMS) always gets the same base
tools (ask_team, handoff_to_staff). An industry that has a pack also gets that pack's tools; an industry without a pack stays
"questions + pass the request to the team" (ai_function_tools.QA_TOOLS) and nothing is ever booked for it.

PACK CONTRACT — a module ai_packs/<name>.py (discovered automatically, nothing to register) exports:
    INDUSTRIES = ('fnb',)                    # db.businesses.industry_code values this pack serves
    RESOURCE = 'table'                       # one of RESOURCES below
    TOOLS = [{'type': 'function', 'function': {'name', 'description', 'parameters'}}, ...]   # names prefixed by the pack
    MANAGE_TOOLS = {'fnb_my_reservations', 'fnb_cancel_reservation'}                         # read/change EXISTING bookings
    PROMPT_RULES = {'en': '...', 'vi': '...'}                                                 # short pack instructions
    def facts(business_id, lang, now_local) -> str                                           # public facts, real data only
    def execute(name, args, ctx) -> dict                                                      # raise PackError to refuse
  Optional: FACTS_INCLUDE_CATALOG = True when facts() already lists the shop's products/prices (the generic price list
  is then left out of the prompt so it is not repeated).

ctx passed to execute() (a fresh copy per call):
    business_id      the shop
    customer_id      conversation id to store as ai_conversation_id. Web chat: '<thread>~<16 hex of the chat token hash>'
                     (anyone can type a phone number, so the plain '<shop>:<phone>' thread id is NOT proof of ownership);
                     split at '~' to link the /ai_bot thread. Other channels: the platform-signed thread id.
    thread_id        the /ai_bot thread id (db.bot_customers.id)
    channel          web | messenger | instagram | whatsapp | zalo | viber | sms
    phone            VERIFIED phone (E.164) or None: SMS/WhatsApp = the carrier-verified number; web/Messenger/... = the number
                     confirmed with a one-time SMS code in this chat (ai_function_tools.verify_code)
    contact_phone    the phone the customer GAVE (unverified) — use it as the contact for NEW bookings only
    chat_token_hash  never None: web = sha256 of the browser's chat token ('anon:<random>' without one); other channels =
                     'conv:<hash of the thread>'. Store it on bookings the AI creates.
    lang             'vi' | 'en' (the customer's latest message)
    now_local        timezone-aware datetime in the shop's timezone
    customer_name    name we already know (None when only a placeholder) ; country  shop country code
  A MANAGE tool on web chat with neither a chat token nor a verified phone is refused here, before the pack runs.
  manage_filter(ctx) builds the ownership filter the contract asks for (verified phone OR chat_token_hash OR conversation).

Other helpers: pack_for(industry), pack_for_business(business_id), tools_for(...), claim_ready(industry),
normalize_phone(), phone_variants(), errors() (modules skipped at discovery and why).
"""
import hashlib
import importlib
import os
import pkgutil
import re
import threading
import time

RESOURCES = ('appointment', 'table', 'room_hour', 'room_night', 'stock_hold', 'job', 'quote', 'consult')
BASE_TOOL_NAMES = ('ask_team', 'handoff_to_staff')
VERIFY_TOOL_NAMES = ('send_verification_code', 'verify_code')
# Names a pack can never take (they belong to the shared engine or to the BitPaw sales bot)
RESERVED_TOOL_NAMES = frozenset(BASE_TOOL_NAMES + VERIFY_TOOL_NAMES + ('request_booking', 'capture_lead'))
_TOOL_NAME_RE = re.compile(r'^[a-z][a-z0-9_]{1,63}$')

# Kill switch per pack or industry, without a deploy of code: BITPAW_AI_PACKS_OFF="fnb,karaoke"
DISABLE_ENV = 'BITPAW_AI_PACKS_OFF'
# 'answers & books' claim per industry: BITPAW_AI_SIM_PASSED="fnb,hotel" or db.system_settings {key: 'ai_sim_passed', value:
# ['fnb'] | {'fnb': {'passed': True, ...}} | {'fnb': True}}. Only ever read here — nothing in this module flips a claim.
SIM_FLAG_ENV = 'BITPAW_AI_SIM_PASSED'
SIM_FLAG_KEY = 'ai_sim_passed'
FLAG_TTL = 60


class PackError(Exception):
    """A pack refuses or rejects a request. The message is written for the AI to relay honestly to the customer."""

    def __init__(self, message, code=None, **extra):
        super().__init__(str(message))
        self.code = code
        self.extra = extra

    def as_result(self):
        out = {'success': False, 'refused': True, 'error': str(self)}
        if self.code:
            out['reason'] = self.code
        for k, v in (self.extra or {}).items():
            out.setdefault(k, v)
        return out


class Pack:
    """One booking pack (a discovered module, or the built-in appointment pack of ai_function_tools)."""

    def __init__(self, name, *, industries, resource, tools, manage_tools=(), prompt_rules=None, facts=None, execute=None,
                 builtin=False, facts_include_catalog=False, module=None):
        self.name = name
        self.industries = tuple(industries)
        self.resource = resource
        self.tools = list(tools)
        self.tool_names = frozenset(t['function']['name'] for t in self.tools)
        self.manage_tools = frozenset(n for n in (manage_tools or ()) if n in self.tool_names)
        self.prompt_rules = dict(prompt_rules or {})
        self._facts = facts
        self._execute = execute
        self.builtin = builtin
        self.facts_include_catalog = bool(facts_include_catalog)
        self.module = module

    def __repr__(self):
        return f"<Pack {self.name} {self.resource} {','.join(self.industries)}>"

    def rules(self, lang='en'):
        r = self.prompt_rules
        return str(r.get(lang) or r.get('en') or next(iter(r.values()), '') or '').strip()

    def facts(self, business_id, lang='en', now_local=None):
        """Pack facts for the prompt; a broken facts() never breaks the chat (the tools still check everything)."""
        if not callable(self._facts):
            return ''
        try:
            return str(self._facts(business_id, lang, now_local) or '').strip()
        except Exception as e:
            print(f"[ai_packs] {self.name}.facts failed: {e}")
            return ''

    def run(self, name, args, ctx):
        if name not in self.tool_names:
            raise PackError(f"'{name}' is not available for this business.", 'unknown_tool')
        out = self._execute(name, dict(args or {}), dict(ctx or {}))
        if not isinstance(out, dict):
            out = {'success': bool(out), 'result': out}
        return out


# ---------------------------------------------------------------- discovery
_LOCK = threading.Lock()
_STATE = {'packs': None, 'by_industry': None, 'errors': {}}
_FLAG_CACHE = {}


def _validate(name, mod):
    industries = getattr(mod, 'INDUSTRIES', None)
    if isinstance(industries, str):
        industries = (industries,)
    industries = tuple(str(i).strip().lower() for i in (industries or ()) if str(i).strip())
    if not industries:
        raise ValueError('INDUSTRIES is empty')
    resource = getattr(mod, 'RESOURCE', None)
    if resource not in RESOURCES:
        raise ValueError(f'RESOURCE {resource!r} is not one of {RESOURCES}')
    tools = getattr(mod, 'TOOLS', None)
    if not isinstance(tools, (list, tuple)) or not tools:
        raise ValueError('TOOLS is empty')
    seen = set()
    for t in tools:
        fn = (t or {}).get('function') if isinstance(t, dict) else None
        tname = (fn or {}).get('name')
        if (t.get('type') != 'function' or not isinstance(fn, dict) or not isinstance(tname, str)
                or not _TOOL_NAME_RE.match(tname) or not isinstance(fn.get('parameters', {}), dict)):
            raise ValueError(f'bad tool schema: {tname or t!r}')
        if tname in RESERVED_TOOL_NAMES:
            raise ValueError(f'tool name {tname!r} is reserved for the shared engine')
        if tname in seen:
            raise ValueError(f'duplicate tool {tname!r}')
        seen.add(tname)
    if not callable(getattr(mod, 'execute', None)):
        raise ValueError('execute(name, args, ctx) is missing')
    manage = set(getattr(mod, 'MANAGE_TOOLS', None) or ())
    unknown = manage - seen
    if unknown:
        raise ValueError(f'MANAGE_TOOLS not in TOOLS: {sorted(unknown)}')
    rules = getattr(mod, 'PROMPT_RULES', None) or {}
    if not isinstance(rules, dict):
        raise ValueError('PROMPT_RULES must be a dict {lang: text}')
    return Pack(name, industries=industries, resource=resource, tools=tools, manage_tools=manage, prompt_rules=rules,
                facts=getattr(mod, 'facts', None), execute=mod.execute,
                facts_include_catalog=getattr(mod, 'FACTS_INCLUDE_CATALOG', False), module=mod)


def _builtin_packs():
    try:
        import ai_function_tools
        return [ai_function_tools.appointment_pack()]
    except Exception as e:   # the appointment pack lives with its tools; never let it take the registry down
        print(f"[ai_packs] built-in appointment pack unavailable: {e}")
        _STATE['errors']['appointment'] = str(e)[:300]
        return []


def _discover():
    packs, errors = {}, {}
    for p in _builtin_packs():
        packs[p.name] = p
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        name = info.name
        if name.startswith('_') or info.ispkg:
            continue
        try:
            mod = importlib.import_module(f'{__name__}.{name}')
            pack = _validate(name, mod)
        except Exception as e:   # 1 broken pack must not stop the others (or the chat)
            errors[name] = f'{type(e).__name__}: {e}'[:300]
            print(f"[ai_packs] skipped pack '{name}': {errors[name]}")
            continue
        if name in packs:
            errors[name] = 'name clashes with a built-in pack'
            continue
        packs[name] = pack
    by_industry = {}
    # built-in first, discovered modules (sorted by name) override it for the industries they list — e.g. a future spa pack
    # with rooms + therapists replaces the built-in appointment tools for spa only
    for p in sorted(packs.values(), key=lambda x: (not x.builtin, x.name)):
        for ind in p.industries:
            prev = by_industry.get(ind)
            if prev is not None and not prev.builtin:
                errors.setdefault(p.name, f"industry '{ind}' already served by pack '{prev.name}'")
                continue
            by_industry[ind] = p
    return packs, by_industry, errors


def _load():
    if _STATE['packs'] is None:
        with _LOCK:
            if _STATE['packs'] is None:
                packs, by_industry, errors = _discover()
                _STATE['errors'] = {**_STATE.get('errors', {}), **errors}
                _STATE['by_industry'] = by_industry
                _STATE['packs'] = packs
    return _STATE['packs'], _STATE['by_industry']


def reload():
    """Forget discovered packs (tests, or after adding a pack file in a long-running process)."""
    with _LOCK:
        _STATE['packs'] = None
        _STATE['by_industry'] = None
        _STATE['errors'] = {}
    _FLAG_CACHE.clear()


def packs():
    return dict(_load()[0])


def errors():
    _load()
    return dict(_STATE['errors'])


def _disabled():
    return {x.strip().lower() for x in (os.environ.get(DISABLE_ENV) or '').split(',') if x.strip()}


def _norm_industry(industry):
    code = str(industry or '').strip().lower()
    return {'nails': 'nail', 'restaurant': 'fnb', 'f&b': 'fnb'}.get(code, code)


def pack_for(industry):
    """The pack serving this industry code, or None (questions + handoff only)."""
    ind = _norm_industry(industry)
    if not ind:
        return None
    pack = _load()[1].get(ind)
    if pack is None:
        return None
    off = _disabled()
    if ind in off or pack.name in off:
        return None
    return pack


def industry_of(business_id):
    try:
        import ai_function_tools
        return ai_function_tools.business_industry(business_id)
    except Exception:
        return None


def pack_for_business(business_id):
    if not business_id or not isinstance(business_id, str):
        return None
    return pack_for(industry_of(business_id))


def all_pack_tool_names():
    names = set()
    for p in _load()[0].values():
        names |= p.tool_names
    return names


_UNSET = object()


def tools_for(business_id=None, pack=_UNSET, waiting=False, can_verify=False):
    """Tool schemas for the customer AI of 1 shop: pack tools (+ SMS-code verification when the pack manages bookings and the
    shop can text) + ask_team/handoff_to_staff; no pack -> request_booking + ask_team + handoff_to_staff.
    waiting=True (already handed to a person): no second handoff/ask_team."""
    import ai_function_tools as T
    if pack is _UNSET:
        pack = pack_for_business(business_id)
    if pack is None:
        tools = list(T.QA_TOOLS)
    else:
        tools = list(pack.tools)
        if can_verify and pack.manage_tools:
            tools += list(T.VERIFY_TOOLS)
        tools += list(T.BASE_TOOLS)
    if waiting:
        tools = [t for t in tools if t['function']['name'] not in BASE_TOOL_NAMES]
    return tools


# ---------------------------------------------------------------- 'answers & books' claim per industry
def _sim_flag_db():
    hit = _FLAG_CACHE.get('db')
    if hit and time.time() - hit[0] < FLAG_TTL:
        return hit[1]
    val = None
    try:
        import sys
        mc = sys.modules.get('mongo_client')
        if mc is None:
            import mongo_client as mc
        db = getattr(mc, 'db', None)
        if db is not None:
            val = (db.system_settings.find_one({'key': SIM_FLAG_KEY}, {'_id': 0, 'value': 1}) or {}).get('value')
    except Exception as e:
        print(f"[ai_packs] sim flag: {e}")
    _FLAG_CACHE['db'] = (time.time(), val)
    return val


def sim_passed(industry):
    ind = _norm_industry(industry)
    if ind in {x.strip().lower() for x in (os.environ.get(SIM_FLAG_ENV) or '').split(',') if x.strip()}:
        return True
    val = _sim_flag_db()
    if isinstance(val, (list, tuple, set)):
        return ind in {str(x).strip().lower() for x in val}
    if isinstance(val, dict):
        v = val.get(ind)
        return v is True or (isinstance(v, dict) and v.get('passed') is True)
    return False


def claim_ready(industry):
    """True only when the industry HAS a live pack AND its ai_sim run is marked as passed (env or DB flag). plans can use it
    to say 'answers & books' for that industry; until then the honest 'answers & passes requests' claim stays."""
    return pack_for(industry) is not None and sim_passed(industry)


# ---------------------------------------------------------------- phones (bookings store what the customer typed)
_CC = {'US': '1', 'CA': '1', 'AU': '61', 'NZ': '64', 'GB': '44', 'VN': '84'}


def normalize_phone(phone, country=None):
    """E.164 ('+61412345678') or '' when it is not a phone number. Same rules as messaging.normalize_phone + NZ/GB/VN extras."""
    raw = str(phone or '').strip()
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return ''
    if raw.startswith('+') or raw.startswith('00'):
        d = digits if raw.startswith('+') else digits[2:]
        return '+' + d if 8 <= len(d) <= 15 else ''
    c = (country or 'US').upper()
    if c in ('US', 'CA'):
        if len(digits) == 10:
            return '+1' + digits
        if len(digits) == 11 and digits.startswith('1'):
            return '+' + digits
    elif c == 'AU':
        if len(digits) == 10 and digits.startswith('0'):
            return '+61' + digits[1:]
        if len(digits) == 9 and digits[0] in '23478':
            return '+61' + digits
        if len(digits) == 11 and digits.startswith('61'):
            return '+' + digits
    elif c == 'VN':
        if len(digits) == 10 and digits.startswith('0'):
            return '+84' + digits[1:]
        if len(digits) == 9 and digits[0] in '35789':
            return '+84' + digits
        if len(digits) == 11 and digits.startswith('84'):
            return '+' + digits
    elif c in ('NZ', 'GB'):
        if digits.startswith('0') and 9 <= len(digits) <= 11:
            return '+' + _CC[c] + digits[1:]
        if digits.startswith(_CC[c]) and 10 <= len(digits) <= 13:
            return '+' + digits
    if 11 <= len(digits) <= 15:
        return '+' + digits
    return ''


def phone_variants(phone, country=None):
    """Spellings the same number may be stored under (bookings keep what the customer typed): raw, digits, E.164, national."""
    raw = str(phone or '').strip()
    digits = re.sub(r'\D', '', raw)
    if len(digits) < 6:
        return []
    out = {raw, digits, '+' + digits}
    e164 = normalize_phone(raw, country)
    if e164:
        out.update((e164, e164[1:]))
        for cc in sorted(set(_CC.values()), key=len, reverse=True):
            if e164[1:].startswith(cc):
                nat = e164[1 + len(cc):]
                if cc == '1':
                    out.update((nat, f"({nat[:3]}) {nat[3:6]}-{nat[6:]}", f"{nat[:3]}-{nat[3:6]}-{nat[6:]}",
                                f"{nat[:3]}.{nat[3:6]}.{nat[6:]}", f"{nat[:3]} {nat[3:6]} {nat[6:]}"))
                else:
                    local = '0' + nat
                    out.update((local, f"{local[:4]} {local[4:7]} {local[7:]}", f"+{cc} {nat}"))
                break
    return sorted(x for x in out if x)


def same_phone(a, b, country=None):
    ea, eb = normalize_phone(a, country), normalize_phone(b, country)
    if ea and eb:
        return ea == eb
    da, db_ = re.sub(r'\D', '', str(a or '')), re.sub(r'\D', '', str(b or ''))
    return bool(da) and da == db_


def conversation_hash(customer_id):
    """chat_token_hash for non-web channels: stable, never None, and different from any web token hash."""
    return 'conv:' + hashlib.sha256(str(customer_id or '').encode('utf-8')).hexdigest()[:48]


def manage_filter(ctx, phone_fields=('customer_phone',)):
    """Mongo filter (AND it with business_id) for bookings this chat may read/change, or None when nothing proves ownership:
    a VERIFIED phone (any of its spellings) OR the chat_token_hash stored at creation OR (non-web) the conversation id."""
    ors = []
    if ctx.get('phone'):
        variants = phone_variants(ctx['phone'], ctx.get('country'))
        for f in phone_fields:
            ors.append({f: {'$in': variants}})
    th = ctx.get('chat_token_hash')
    if th and not str(th).startswith('anon:'):
        ors.append({'chat_token_hash': th})
    cid = ctx.get('customer_id')
    if cid and (ctx.get('channel') != 'web' or ('~' in str(cid) and '~anon' not in str(cid))):
        ors.append({'ai_conversation_id': cid})
    return {'$or': ors} if ors else None
