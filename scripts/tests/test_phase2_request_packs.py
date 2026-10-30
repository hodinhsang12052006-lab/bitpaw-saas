# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 "gói yêu cầu" của lễ tân AI cho 4 ngành KHÔNG đặt khung giờ:
  ai_packs/retail.py (stock_hold: tra hàng thật + giữ hàng chờ lấy), ai_packs/technical.py (job: nhận việc vào db.tasks của
  bảng điều phối + tra trạng thái), ai_packs/production.py (quote: yêu cầu báo giá B2B), ai_packs/office.py (consult: yêu cầu
  tư vấn) + retail_holds_bp.py (trang / API cho nhân viên).

Mỗi công cụ: đường đúng, tranh chấp sức chứa (giữ quá tồn, 2 lệnh cùng lúc), từ chối quyền sở hữu (không lộ của người khác,
không so 'đuôi số'), pending vs confirmed (không bao giờ nói đã xác nhận), dữ liệu sai. Hợp đồng gói (INDUSTRIES, RESOURCE,
TOOLS, MANAGE_TOOLS, PROMPT_RULES, facts, execute) — nếu registry thật ai_packs/__init__.py có mặt thì chạy cả _validate của nó.

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi mạng: mongo_client / app /
ai_function_tools / requests được thay TRƯỚC mọi import. Chạy: python scripts/tests/test_phase2_request_packs.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime
from functools import wraps
from itertools import count
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)


# ---------------------------------------------------------------- DB giả trong RAM
def _get(doc, key):
    cur = doc
    for part in key.split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _expr(doc, e):
    if isinstance(e, str) and e.startswith('$'):
        return _get(doc, e[1:])
    if isinstance(e, dict) and len(e) == 1:
        op, arg = next(iter(e.items()))
        vals = [_expr(doc, a) for a in arg] if isinstance(arg, list) else [_expr(doc, arg)]
        if op == '$ifNull':
            return vals[0] if vals[0] is not None else vals[1]
        if op == '$subtract':
            return vals[0] - vals[1]
        if op == '$gte':
            return vals[0] >= vals[1]
        if op == '$lte':
            return vals[0] <= vals[1]
        raise NotImplementedError(op)
    return e


def _match_value(v, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith('$') for k in cond):
        for op, arg in cond.items():
            if op == '$in' and v not in arg:
                return False
            if op == '$nin' and v in arg:
                return False
            if op == '$ne' and v == arg:
                return False
            if op == '$exists' and (v is not None) != bool(arg):
                return False
            if op == '$regex' and not (isinstance(v, str) and re.search(arg, v)):
                return False
            if op in ('$gte', '$gt', '$lt', '$lte'):
                if v is None:
                    return False
                if (op == '$gte' and not v >= arg) or (op == '$gt' and not v > arg) or \
                        (op == '$lt' and not v < arg) or (op == '$lte' and not v <= arg):
                    return False
        return True
    return v == cond


def _matches(doc, flt):
    for k, cond in (flt or {}).items():
        if k == '$or':
            if not any(_matches(doc, f) for f in cond):
                return False
        elif k == '$expr':
            if not _expr(doc, cond):
                return False
        elif not _match_value(_get(doc, k), cond):
            return False
    return True


class _Cursor(list):
    def sort(self, key, direction=1):
        if isinstance(key, list):
            key, direction = key[0]
        return _Cursor(sorted(self, key=lambda d: (d.get(key) is None, d.get(key) if d.get(key) is not None else 0),
                              reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


def _clean(d):
    return {k: v for k, v in d.items() if k != '_id'}


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs, self.uniques, self.indexes = name, [], [], []
        self.fail_next_fam = None   # mô phỏng 2 lệnh upsert cùng lúc

    # --- index
    def create_index(self, keys, unique=False, partialFilterExpression=None, **kw):
        self.indexes.append(keys)
        if unique:
            self.uniques.append(([k for k, _ in keys], partialFilterExpression or {}))
        return 'idx'

    def _check_unique(self, doc, skip=None):
        for fields, partial in self.uniques:
            if partial and not _matches(doc, partial):
                continue
            key = tuple(_get(doc, f) for f in fields)
            for d in self.docs:
                if d is skip:
                    continue
                if partial and not _matches(d, partial):
                    continue
                if tuple(_get(d, f) for f in fields) == key:
                    raise DuplicateKeyError(f'E11000 duplicate key {self.name} {fields}')

    # --- đọc
    def find(self, flt=None, projection=None):
        return _Cursor(_clean(d) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = self.find(flt)
        if sort:
            rows = rows.sort(sort[0][0], sort[0][1])
        return dict(rows[0]) if rows else None

    def count_documents(self, flt):
        return len(self.find(flt))

    def distinct(self, field, flt=None):
        out = []
        for d in self.find(flt):
            v = _get(d, field)
            if v not in out:
                out.append(v)
        return out

    # --- ghi
    def insert_one(self, doc):
        d = dict(doc)
        self._check_unique(d)
        d.setdefault('_id', f'{self.name}-{len(self.docs) + 1}')
        self.docs.append(d)
        doc['_id'] = d['_id']
        return types.SimpleNamespace(inserted_id=d['_id'])

    @staticmethod
    def _apply(d, update):
        for k, v in (update.get('$set') or {}).items():
            d[k] = v
        for k, v in (update.get('$inc') or {}).items():
            d[k] = (d.get(k) or 0) + v
        for k in (update.get('$unset') or {}):
            d.pop(k, None)

    def _upsert_doc(self, flt, update):
        d = {k: v for k, v in flt.items() if not k.startswith('$') and not isinstance(v, dict)}
        d.update(update.get('$setOnInsert') or {})
        self._apply(d, update)
        self._check_unique(d)
        d['_id'] = f'{self.name}-{len(self.docs) + 1}'
        self.docs.append(d)
        return d

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                return types.SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            d = self._upsert_doc(flt, update)
            return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=d['_id'])
        return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def find_one_and_update(self, flt, update, upsert=False, projection=None, return_document=False, **kw):
        if self.fail_next_fam is not None:
            exc, self.fail_next_fam = self.fail_next_fam, None
            raise exc
        for d in self.docs:
            if _matches(d, flt):
                before = _clean(d)
                self._apply(d, update)
                return _clean(d) if return_document else before
        if upsert:
            d = self._upsert_doc(flt, update)
            return _clean(d) if return_document else None
        return None


class FakeDB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self[name]

    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = FakeCollection(name)
        return self._c[name]

    def reset(self):
        self._c.clear()


DB = FakeDB()
_IDS = {}


def _next_id(name):
    _IDS.setdefault(name, count(1))
    return next(_IDS[name])


_mc = types.ModuleType('mongo_client')
_mc.db = DB
_mc.next_mongo_id = _next_id
sys.modules['mongo_client'] = _mc
sys.modules['requests'] = MagicMock()

# ai_function_tools thật kéo theo booking_engine/DeepSeek...: chỉ cần 3 hàm báo nhân viên mà gói gọi
CALLS = []
_aft = types.ModuleType('ai_function_tools')
_aft._note_for_staff = lambda bid, cid, text, sender='system': CALLS.append(('note', bid, cid, text))
_aft._alert_owner = lambda bid, cid, text, kind: CALLS.append(('alert', bid, cid, text, kind)) or True
_aft.reply_expectation = lambda bid, vi=False: ('Nhân viên sẽ trả lời.' if vi else 'The team will reply here.')
sys.modules['ai_function_tools'] = _aft


# app.py thật nối DB production: chỉ cần login_required (blueprint) + _geocode_address (gói kỹ thuật)
def _login_required(f):
    from flask import jsonify, session

    @wraps(f)
    def inner(*a, **kw):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Please sign in to continue.'}), 401
        return f(*a, **kw)
    return inner


GEO = {'calls': [], 'point': (-33.8688, 151.2093)}
_app = types.ModuleType('app')
_app.login_required = _login_required
_app._geocode_address = lambda bid, addr: GEO['calls'].append(addr) or GEO['point']
sys.modules['app'] = _app

# Registry: dùng ai_packs/__init__.py thật nếu đã gộp (core), không thì gói nhỏ chỉ có PackError (hợp đồng tối thiểu)
REAL_REGISTRY = os.path.exists(os.path.join(ROOT, 'ai_packs', '__init__.py'))
if not REAL_REGISTRY:
    _pk = types.ModuleType('ai_packs')
    _pk.__path__ = [os.path.join(ROOT, 'ai_packs')]

    class PackError(Exception):
        pass
    _pk.PackError = PackError
    sys.modules['ai_packs'] = _pk

import ai_packs  # noqa: E402
import booking_rules  # noqa: E402
from ai_packs import retail, technical, production, office  # noqa: E402

PackError = ai_packs.PackError
TZ = ZoneInfo('Australia/Sydney')
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=TZ)              # thứ Sáu, giờ tiệm
SAT = datetime(2026, 10, 31, 11, 0, tzinfo=TZ)
NY_NOW = datetime(2026, 10, 30, 10, 0, tzinfo=ZoneInfo('America/New_York'))   # văn phòng ở Mỹ: thứ Sáu 10:00 giờ văn phòng
AU, VN, US_SHOP, TECH, PROD, OFFICE, OTHER = 'shop_au', 'shop_vn', 'shop_us', 'tech_au', 'prod_vn', 'office_us', 'shop_other'
# chat web thật luôn có SĐT khách gõ ('<tiệm>:<SĐT>'): mã trình duyệt chỉ là bằng chứng KÈM đúng chat này
AU_CHAT, TECH_CHAT = f'{AU}:0412345678', f'{TECH}:0412345678'
HOURS = {'mon': ['09:00', '17:30'], 'tue': ['09:00', '17:30'], 'wed': ['09:00', '17:30'], 'thu': ['09:00', '17:30'],
         'fri': ['09:00', '17:30'], 'sat': ['09:00', '13:00'], 'sun': None}


def ctx(bid=AU, **kw):
    c = {'business_id': bid, 'customer_id': None, 'thread_id': None, 'channel': 'web', 'phone': None, 'contact_phone': None,
         'chat_token_hash': 'tokA', 'lang': 'en', 'now_local': NOW, 'customer_name': None,
         'country': (DB.businesses.find_one({'id': bid}) or {}).get('country')}
    c.update(kw)
    return c


def seed():
    DB.reset()
    _IDS.clear()
    CALLS.clear()
    GEO['calls'].clear()
    booking_rules._CACHE.clear()
    retail._INDEXES.clear()
    for bid, cur, country, ind in ((AU, 'AUD', 'AU', 'retail'), (VN, 'VND', 'VN', 'retail'), (US_SHOP, 'USD', 'US', 'retail'),
                                   (TECH, 'AUD', 'AU', 'technical'), (PROD, 'VND', 'VN', 'production'),
                                   (OFFICE, 'USD', 'US', 'office'), (OTHER, 'AUD', 'AU', 'retail')):
        DB.businesses.insert_one({'id': bid, 'name': f'Shop {bid}', 'currency': cur, 'country': country, 'industry_code': ind,
                                  'phone': '+61290000000'})
    for bid in (AU, TECH, OFFICE, US_SHOP):
        DB.booking_settings.insert_one({'business_id': bid, 'hours': HOURS})
    DB.messaging_settings.insert_one({'business_id': AU, 'timezone': 'Australia/Sydney'})
    rows = [(1, AU, 'Sữa tươi Vinamilk 1L', 'Dairy', 4.5, 20, 'retail', 1), (2, AU, 'Organic Eggs 12pk', 'Dairy', 7.9, 3, 'retail', 1),
            (3, AU, 'Sourdough Loaf', 'Bakery', 6.0, 0, 'retail', 1), (4, AU, 'Old Biscuit', 'Bakery', 2.0, 50, 'retail', 0),
            (5, AU, 'Phở bò', 'Kitchen', 15.0, 99, 'fnb', 1), (6, OTHER, 'Organic Eggs 12pk', 'Dairy', 7.0, 40, 'retail', 1),
            (7, AU, 'Almond Milk 1L', 'Dairy', 3.2, 40, 'retail', 1), (8, AU, 'Oat Milk 1L', 'Dairy', 3.4, 40, 'retail', 1),
            (9, AU, 'Soy Milk 1L', 'Dairy', 2.9, 40, 'retail', 1),
            (21, VN, 'Nước mắm Phú Quốc', 'Gia vị', 85000, 10, 'retail', 1), (31, US_SHOP, 'Candle', 'Home', 12, 9, 'retail', 1),
            (41, PROD, 'Áo thun cotton', 'May mặc', 120000, 0, 'retail', 1)]
    for pid, bid, name, cat, price, stock, ch, active in rows:
        DB.products.insert_one({'id': pid, 'business_id': bid, 'name': name, 'category': cat, 'price': price, 'stock': stock,
                                'channel_type': ch, 'is_active': active})
    DB.system_settings.insert_one({'key': 'inventory_thresholds', 'business_id': AU, 'value': '{"critical": 5}'})
    DB.dichvu.insert_one({'id': 1, 'business_id': TECH, 'ten_dich_vu': 'Air-con service', 'gia_dich_vu': 129, 'tien_tua': 40})


def hold(**kw):
    args = {'product_id': 1, 'quantity': 2, 'customer_name': 'Mia', 'phone': '0412 345 678'}
    args.update(kw.pop('args', {}))
    return retail.execute('retail_hold_for_pickup', args, ctx(**kw))


def product(pid, bid=AU):
    return DB.products.find_one({'id': pid, 'business_id': bid})


# ================================================================ hợp đồng gói
class PackContractTests(unittest.TestCase):
    PACKS = ((retail, 'retail', 'stock_hold', 'retail_'), (technical, 'technical', 'job', 'technical_'),
             (production, 'production', 'quote', 'production_'), (office, 'office', 'consult', 'office_'))

    def test_exports_follow_the_contract(self):
        resources = getattr(ai_packs, 'RESOURCES', ('appointment', 'table', 'room_hour', 'room_night', 'stock_hold', 'job',
                                                    'quote', 'consult'))
        for mod, ind, res, prefix in self.PACKS:
            with self.subTest(pack=ind):
                self.assertEqual(mod.INDUSTRIES, (ind,))
                self.assertEqual(mod.RESOURCE, res)
                self.assertIn(res, resources)
                names = [t['function']['name'] for t in mod.TOOLS]
                self.assertTrue(names and all(n.startswith(prefix) for n in names), names)
                self.assertEqual(len(names), len(set(names)))
                for t in mod.TOOLS:
                    self.assertEqual(t['type'], 'function')
                    self.assertIsInstance(t['function']['description'], str)
                    self.assertEqual(t['function']['parameters']['type'], 'object')
                    for r in t['function']['parameters'].get('required', []):
                        self.assertIn(r, t['function']['parameters']['properties'])
                self.assertTrue(set(mod.MANAGE_TOOLS) <= set(names))
                self.assertTrue(mod.PROMPT_RULES['en'].strip() and mod.PROMPT_RULES['vi'].strip())
                self.assertTrue(callable(mod.facts) and callable(mod.execute))
                with self.assertRaises(PackError):
                    mod.execute(f'{prefix}nope', {}, ctx())

    def test_real_registry_accepts_the_packs(self):
        if not REAL_REGISTRY or not hasattr(ai_packs, '_validate'):
            self.skipTest('ai_packs/__init__.py (core) not merged in this worktree')
        for mod, ind, res, _ in self.PACKS:
            pack = ai_packs._validate(ind, mod)
            self.assertEqual(pack.resource, res)
            self.assertEqual(pack.industries, (ind,))
        ai_packs.reload()
        for _, ind, res, _ in self.PACKS:                    # tự phát hiện, đúng ngành, không bị bỏ qua vì lỗi
            self.assertEqual(ai_packs.pack_for(ind).name, ind)
            self.assertNotIn(ind, ai_packs.errors())
        self.assertTrue(ai_packs.pack_for('retail').facts_include_catalog)
        self.assertEqual(ai_packs.pack_for('technical').booking_collections, (('tasks', 'sdt'),))

    def test_manage_tools_and_booking_collections(self):
        self.assertEqual(retail.MANAGE_TOOLS, {'retail_my_holds', 'retail_cancel_hold'})
        self.assertEqual(technical.MANAGE_TOOLS, {'technical_job_status'})
        self.assertEqual(production.MANAGE_TOOLS, set())
        self.assertEqual(office.MANAGE_TOOLS, set())
        self.assertEqual(technical.BOOKING_COLLECTIONS, (('tasks', 'sdt'),))       # db.tasks lưu SĐT ở 'sdt'
        self.assertEqual(retail.BOOKING_COLLECTIONS, (('retail_holds', 'customer_phone'),))

    def test_vocabulary_and_honesty_in_prompts(self):
        seed()
        for mod, ind, _, _ in self.PACKS:
            bid = {'retail': AU, 'technical': TECH, 'production': PROD, 'office': OFFICE}[ind]
            text = ' '.join([mod.PROMPT_RULES['en'], mod.PROMPT_RULES['vi'], mod.facts(bid, 'en', NOW)]
                            + [t['function']['description'] for t in mod.TOOLS]).lower()
            with self.subTest(pack=ind):
                for bad in ('salon', 'technician', 'manicure', 'bitpaw', 'guaranteed!'):
                    self.assertNotIn(bad, text)
                self.assertNotIn('opening hours:', mod.facts(bid, 'en', NOW).lower())   # core thêm giờ mở cửa, không lặp


# ================================================================ phone helpers
class PhoneTests(unittest.TestCase):
    def test_full_number_keys_not_suffix(self):
        self.assertEqual(retail.phone_key('0412 345 678', 'AU'), '+61412345678')
        self.assertEqual(retail.phone_key('+61 412 345 678', 'AU'), '+61412345678')
        self.assertEqual(retail.phone_key('(312) 345-6789', 'US'), '+13123456789')
        self.assertNotEqual(retail.phone_key('(212) 345-6789', 'US'), retail.phone_key('(312) 345-6789', 'US'))
        self.assertEqual(retail.phone_key('0901 234 567', 'VN'), '+84901234567')
        self.assertIsNone(retail.phone_key('12', 'AU'))

    def test_local_fallback_matches(self):
        for raw, c, want in (('0412345678', 'AU', '+61412345678'), ('3123456789', 'US', '+13123456789'),
                             ('0901234567', 'VN', '+84901234567'), ('+44 20 7946 0958', 'GB', '+442079460958')):
            self.assertEqual(retail._e164_local(raw, c), want)

    def test_regex_matches_same_number_any_spelling_only(self):
        rx = re.compile(retail.phone_regex('+13123456789'))
        for ok in ('(312) 345-6789', '312-345-6789', '+1 312 345 6789', '3123456789', '1 (312) 345 6789'):
            self.assertTrue(rx.search(ok), ok)
        for bad in ('(212) 345-6789', '312-345-678', '(312) 345-67890', '9 (312) 345 6789'):
            self.assertFalse(rx.search(bad), bad)
        rx = re.compile(retail.phone_regex('+61412345678'))
        for ok in ('0412 345 678', '+61 412 345 678', '412345678', '0061412345678'):
            self.assertTrue(rx.search(ok), ok)
        for bad in ('0512 345 678', '0412 345 679'):
            self.assertFalse(rx.search(bad), bad)


# ================================================================ bán lẻ
class RetailFindTests(unittest.TestCase):
    def setUp(self):
        seed()

    def test_accent_insensitive_search_with_live_stock_and_currency(self):
        out = retail.execute('retail_find_products', {'query': 'sua tuoi'}, ctx())
        self.assertTrue(out['exact_match'])
        m = out['matches'][0]
        self.assertEqual((m['product_id'], m['price'], m['availability'], m['can_hold_up_to']), (1, '$4.50', 'in_stock', 10))
        eggs = retail.execute('retail_find_products', {'query': 'eggs'}, ctx())['matches']
        self.assertEqual([(e['product_id'], e['availability'], e['can_hold_up_to']) for e in eggs], [(2, 'low', 3)])  # không lấy tiệm khác
        bread = retail.execute('retail_find_products', {'query': 'sourdough'}, ctx())['matches'][0]
        self.assertEqual((bread['availability'], bread['can_hold_up_to']), ('out', 0))

    def test_inactive_and_non_retail_items_are_hidden(self):
        self.assertEqual(retail.execute('retail_find_products', {'query': 'biscuit'}, ctx())['matches'], [])
        out = retail.execute('retail_find_products', {'query': 'pho bo'}, ctx())
        self.assertEqual(out['matches'], [])
        self.assertIn("couldn't find", out['note'])

    def test_category_filter_close_match_and_vnd(self):
        out = retail.execute('retail_find_products', {'query': '', 'category': 'dairy'}, ctx())
        self.assertEqual({m['product_id'] for m in out['matches']}, {1, 2, 7, 8, 9})
        close = retail.execute('retail_find_products', {'query': 'milk chocolate'}, ctx())
        self.assertFalse(close['exact_match'])
        self.assertIn('Closest matches', close['note'])
        vn = retail.execute('retail_find_products', {'query': 'nuoc mam'}, ctx(VN, lang='vi'))
        self.assertEqual(vn['matches'][0]['price'], '85.000đ')

    def test_bad_input(self):
        with self.assertRaises(PackError):
            retail.execute('retail_find_products', {'query': '  '}, ctx())
        with self.assertRaises(PackError):
            retail.execute('retail_find_products', {'query': 'milk'}, ctx(business_id=None))


class RetailHoldTests(unittest.TestCase):
    def setUp(self):
        seed()

    def test_happy_path_creates_pending_hold_with_tags_and_deadline(self):
        out = hold(customer_id=f'{AU}:0412345678', chat_token_hash='tokA')
        self.assertTrue(out['success'])
        self.assertEqual(out['status'], 'pending')
        self.assertEqual(out['total'], '$9.00')
        self.assertEqual(out['expires_at'], '2026-10-31T13:00')          # thứ Bảy đóng cửa 13:00 = ngày làm việc kế tiếp
        self.assertIn('staff will confirm', out['tell_customer'])
        self.assertNotRegex(out['tell_customer'].lower(), r"\b(is|are|been|it's) (reserved|confirmed|guaranteed)\b|guarantee")
        h = DB.retail_holds.find_one({'id': out['hold_id']})
        self.assertEqual((h['status'], h['source'], h['ai_conversation_id'], h['chat_token_hash'], h['phone_key'], h['quantity']),
                         ('pending', 'ai_bot', f'{AU}:0412345678', 'tokA', '+61412345678', 2))
        self.assertEqual(h['customer_phone'], '+61412345678')
        self.assertEqual(product(1)['held_qty'], 2)
        self.assertEqual(product(1)['stock'], 20)                            # giữ không trừ kho; POS trừ lúc bán
        kinds = [c[0] for c in CALLS]
        self.assertEqual(kinds, ['note', 'alert'])
        self.assertIn('Pickup holds page', CALLS[1][3])
        self.assertEqual(CALLS[1][4], 'retail_hold')

    def test_saturday_hold_skips_closed_sunday_and_vi_wording(self):
        out = hold(now_local=SAT, lang='vi')
        self.assertEqual(out['expires_at'], '2026-11-02T17:30')
        self.assertIn('Cửa hàng sẽ xác nhận', out['tell_customer'])
        DB.booking_settings.docs.clear()
        booking_rules._CACHE.clear()
        self.assertEqual(retail.hold_deadline(AU, NOW.replace(tzinfo=None)), datetime(2026, 10, 31, 23, 59))

    def test_contact_required_and_contact_phone_fallback(self):
        with self.assertRaises(PackError) as e:
            retail.execute('retail_hold_for_pickup', {'product_id': 1, 'quantity': 1}, ctx())
        self.assertIn('name and phone number', str(e.exception))
        with self.assertRaises(PackError):
            hold(args={'phone': 'call me'})
        self.assertEqual(DB.retail_holds.docs, [])
        self.assertIsNone(product(1).get('held_qty'))
        out = retail.execute('retail_hold_for_pickup', {'product_id': 1, 'quantity': 1},
                             ctx(contact_phone='0412 999 888', customer_name='Lan'))
        self.assertEqual(DB.retail_holds.find_one({'id': out['hold_id']})['customer_phone'], '+61412999888')

    def test_bad_quantity_and_product(self):
        for q in (0, 11, 'abc', True, 1.5):
            with self.subTest(q=q), self.assertRaises(PackError):
                hold(args={'quantity': q})
        for pid in (4, 5, 6, 999, 'x'):      # inactive, fnb, tiệm khác, không có, sai kiểu
            with self.subTest(pid=pid), self.assertRaises(PackError):
                hold(args={'product_id': pid})
        self.assertEqual(DB.retail_holds.docs, [])

    def test_never_holds_more_than_stock(self):
        hold(args={'product_id': 2, 'quantity': 2}, chat_token_hash='tokA')
        with self.assertRaises(PackError) as e:
            hold(args={'product_id': 2, 'quantity': 2, 'phone': '0412 000 111', 'customer_name': 'Ben'}, chat_token_hash='tokB')
        self.assertIn('Only 1', str(e.exception))
        hold(args={'product_id': 2, 'quantity': 1, 'phone': '0412 000 111', 'customer_name': 'Ben'}, chat_token_hash='tokB')
        with self.assertRaises(PackError) as e:
            hold(args={'product_id': 2, 'quantity': 1, 'phone': '0412 000 222', 'customer_name': 'Cy'}, chat_token_hash='tokC')
        self.assertIn('out of stock', str(e.exception))
        self.assertEqual(product(2)['held_qty'], 3)
        found = retail.execute('retail_find_products', {'query': 'eggs'}, ctx())['matches'][0]
        self.assertEqual((found['availability'], found['can_hold_up_to']), ('out', 0))
        with self.assertRaises(PackError):
            hold(args={'product_id': 3, 'quantity': 1})       # stock 0

    def test_same_customer_twice_returns_the_existing_hold(self):
        a = hold(chat_token_hash='tokA', customer_id=AU_CHAT)
        b = hold(chat_token_hash='tokA', customer_id=AU_CHAT)
        self.assertTrue(b['already_held'])
        self.assertEqual(b['hold_id'], a['hold_id'])
        self.assertEqual(len(DB.retail_holds.docs), 1)
        self.assertEqual(product(1)['held_qty'], 2)

    def test_concurrent_duplicate_is_blocked_by_unique_active_key_without_leaking(self):
        # chat web không có mã trình duyệt ('anon:') và SĐT chưa xác minh: không chứng minh được chủ -> không có bước "đã giữ"
        anon = {'chat_token_hash': 'anon:1', 'customer_id': f'{AU}:0412345678'}
        hold(**anon)
        with self.assertRaises(PackError) as e:
            hold(**{**anon, 'chat_token_hash': 'anon:2'})
        self.assertIn('already waiting', str(e.exception))
        self.assertNotIn('Mia', str(e.exception))
        self.assertEqual(len(DB.retail_holds.docs), 1)
        self.assertEqual(product(1)['held_qty'], 2)               # số giữ của lệnh thua đã trả lại

    def test_max_active_holds_per_customer(self):
        for pid in (1, 7, 8):
            hold(args={'product_id': pid, 'quantity': 1})
        with self.assertRaises(PackError) as e:
            hold(args={'product_id': 9, 'quantity': 1})
        self.assertIn('maximum of 3', str(e.exception))
        with self.assertRaises(PackError):           # cùng SĐT ở trình duyệt khác cũng bị chặn
            hold(args={'product_id': 9, 'quantity': 1}, chat_token_hash='tokZ')

    def test_index_specs_are_created(self):
        hold()
        self.assertIn((['business_id', 'active_key'], {'active_key': {'$exists': True}}), DB.retail_holds.uniques)


class RetailManageTests(unittest.TestCase):
    def setUp(self):
        seed()
        self.a = hold(chat_token_hash='tokA', customer_id=AU_CHAT)['hold_id']
        self.us = retail.execute('retail_hold_for_pickup', {'product_id': 31, 'quantity': 1, 'customer_name': 'Joe',
                                                           'phone': '(212) 345-6789'}, ctx(US_SHOP, chat_token_hash='tokUS'))['hold_id']

    def test_my_holds_by_token_and_by_verified_phone(self):
        mine = retail.execute('retail_my_holds', {}, ctx(chat_token_hash='tokA', customer_id=AU_CHAT))['holds']
        self.assertEqual([(h['hold_id'], h['status']) for h in mine], [(self.a, 'pending')])
        self.assertIn('not confirmed', mine[0]['status_meaning'])
        by_phone = retail.execute('retail_my_holds', {}, ctx(chat_token_hash='tokOther', phone='+61412345678'))['holds']
        self.assertEqual([h['hold_id'] for h in by_phone], [self.a])
        retail.staff_set_status(AU, self.a, 'ready')
        again = retail.execute('retail_my_holds', {}, ctx(chat_token_hash='tokA', customer_id=AU_CHAT))['holds'][0]
        self.assertEqual(again['status'], 'ready')
        self.assertIn('confirmed by the store', again['status_meaning'])

    def test_other_customers_never_see_or_cancel(self):
        self.assertEqual(retail.execute('retail_my_holds', {}, ctx(chat_token_hash='tokB', customer_id=AU_CHAT))['holds'], [])
        # (312) đã xác minh không thấy hold của (212) — trùng 9 số cuối
        self.assertEqual(retail.execute('retail_my_holds', {}, ctx(US_SHOP, chat_token_hash='x', phone='+13123456789'))['holds'], [])
        with self.assertRaises(PackError):
            retail.execute('retail_cancel_hold', {'hold_id': self.a}, ctx(chat_token_hash='tokB', customer_id=AU_CHAT))
        self.assertEqual(DB.retail_holds.find_one({'id': self.a})['status'], 'pending')
        # platform id giả (không đúng dạng '<tiệm>:<kênh>:') không phải bằng chứng
        self.assertIsNone(retail.owner_filter(ctx(chat_token_hash='anon:x', channel='messenger', customer_id='zzz')))

    def test_not_verified_refusal(self):
        for c in (ctx(chat_token_hash='anon:abc'), ctx(chat_token_hash=None), ctx(chat_token_hash='', customer_id=f'{AU}:0412345678')):
            with self.assertRaises(PackError) as e:
                retail.execute('retail_my_holds', {}, c)
            self.assertIn('not_verified', str(e.exception))
            with self.assertRaises(PackError):
                retail.execute('retail_cancel_hold', {'hold_id': self.a}, c)

    def test_shared_browser_token_needs_the_phone_typed_in_this_chat(self):
        # máy tính bảng quầy: cùng mã trình duyệt, khách kế tiếp gõ SĐT khác -> không thấy / huỷ được hàng giữ của người trước
        h = hold(customer_id=f'{AU}:0412345678', chat_token_hash='tokS')['hold_id']
        nxt = ctx(chat_token_hash='tokS', customer_id=f'{AU}:0499000111', contact_phone='0499000111')
        self.assertEqual(retail.execute('retail_my_holds', {}, nxt)['holds'], [])
        with self.assertRaises(PackError):
            retail.execute('retail_cancel_hold', {'hold_id': h}, nxt)
        self.assertEqual(DB.retail_holds.find_one({'id': h})['status'], 'pending')
        same = ctx(chat_token_hash='tokS', customer_id=f'{AU}:+61412345678', contact_phone='+61412345678')
        self.assertEqual([x['hold_id'] for x in retail.execute('retail_my_holds', {}, same)['holds']], [h])
        self.assertNotIn({'chat_token_hash': 'tokS'}, retail.owner_filter(nxt)['$or'])

    def test_platform_conversation_counts_as_owner(self):
        cid = f'{AU}:messenger:psid123'
        h = hold(channel='messenger', customer_id=cid, chat_token_hash='conv:abc', args={'product_id': 7, 'quantity': 1})
        mine = retail.execute('retail_my_holds', {}, ctx(channel='messenger', customer_id=cid, chat_token_hash='conv:zzz'))['holds']
        self.assertEqual([x['hold_id'] for x in mine], [h['hold_id']])

    def test_cancel_releases_stock_once_and_allows_a_new_hold(self):
        out = retail.execute('retail_cancel_hold', {'hold_id': self.a}, ctx(chat_token_hash='tokA', customer_id=AU_CHAT))
        self.assertEqual(out['status'], 'cancelled')
        self.assertEqual(product(1)['held_qty'], 0)
        self.assertNotIn('active_key', DB.retail_holds.find_one({'id': self.a}))
        twice = retail.execute('retail_cancel_hold', {'hold_id': self.a}, ctx(chat_token_hash='tokA', customer_id=AU_CHAT))
        self.assertEqual(twice['already'], 'cancelled')
        self.assertEqual(product(1)['held_qty'], 0)
        self.assertTrue(hold(chat_token_hash='tokA', customer_id=AU_CHAT)['success'])         # khoá active_key đã gỡ -> giữ lại được
        self.assertEqual(CALLS[-1][4] if CALLS[-1][0] == 'alert' else None, 'retail_hold')
        with self.assertRaises(PackError):
            retail.execute('retail_cancel_hold', {'hold_id': 'abc'}, ctx(chat_token_hash='tokA', customer_id=AU_CHAT))

    def test_expired_holds_release_stock_lazily(self):
        DB.retail_holds.update_one({'id': self.a}, {'$set': {'expires_at_local': '2026-10-30T09:00'}})
        retail.execute('retail_find_products', {'query': 'sua'}, ctx())
        h = DB.retail_holds.find_one({'id': self.a})
        self.assertEqual(h['status'], 'expired')
        self.assertEqual(product(1)['held_qty'], 0)
        mine = retail.execute('retail_my_holds', {}, ctx(chat_token_hash='tokA', customer_id=AU_CHAT))['holds'][0]
        self.assertIsNone(mine['pickup_by'])
        self.assertIn('released', mine['status_meaning'])

    def test_staff_transitions(self):
        h, err = retail.staff_set_status(AU, self.a, 'ready', by='staff:1')
        self.assertEqual((h['status'], err), ('ready', None))
        self.assertEqual(product(1)['held_qty'], 2)                         # vẫn đang giữ
        self.assertEqual(retail.staff_set_status(AU, self.a, 'ready'), (None, 'not_allowed'))
        self.assertEqual(retail.staff_set_status(AU, self.a, 'expired'), (None, 'bad_status'))
        self.assertEqual(retail.staff_set_status(OTHER, self.a, 'picked_up'), (None, 'not_allowed'))   # tiệm khác
        h, _ = retail.staff_set_status(AU, self.a, 'picked_up')
        self.assertEqual(h['status'], 'picked_up')
        self.assertEqual(product(1)['held_qty'], 0)
        self.assertEqual(retail.staff_set_status(AU, self.a, 'cancelled'), (None, 'not_allowed'))
        self.assertEqual(product(1)['held_qty'], 0)

    def test_drifted_held_qty_is_repaired_before_refusing(self):
        DB.products.update_one({'id': 2, 'business_id': AU}, {'$set': {'held_qty': 3}})     # lệch (không có hold nào)
        out = hold(args={'product_id': 2, 'quantity': 3})
        self.assertTrue(out['success'])
        self.assertEqual(product(2)['held_qty'], 3)

    def test_facts(self):
        f = retail.facts(AU, 'en', NOW)
        self.assertIn('STORE CATEGORIES: Bakery, Dairy.', f)
        self.assertIn('retail_find_products', f)
        self.assertIn('REQUEST the staff confirm', f)
        self.assertIn('Prices are in AUD', f)
        self.assertNotIn('Kitchen', f)                # nhóm hàng F&B không phải hàng bán lẻ
        self.assertTrue(retail.FACTS_INCLUDE_CATALOG)


# ================================================================ kỹ thuật
def job(**kw):
    args = {'customer_name': 'Tom', 'phone': '0412 345 678', 'address': '12 King St, Newtown NSW',
            'problem': 'Air-con leaking water inside', 'preferred_date': '2026-11-02', 'preferred_window': 'morning'}
    args.update(kw.pop('args', {}))
    return technical.execute('technical_request_job', args, ctx(TECH, **kw))


class TechnicalTests(unittest.TestCase):
    def setUp(self):
        seed()

    def test_job_goes_on_the_dispatch_board_unassigned(self):
        out = job(customer_id=f'{TECH}:0412345678', chat_token_hash='tokT')
        self.assertEqual((out['status'], out['board_status'], out['urgency']), ('pending', 'waiting_for_assignment', 'normal'))
        self.assertIn('nothing is scheduled', out['tell_customer'])
        t = DB.tasks.find_one({'id': out['job_id']})
        self.assertEqual((t['business_id'], t['trang_thai'], t['nguoi_nhan'], t['ten_khach'], t['sdt'], t['dia_chi']),
                         (TECH, 'Chờ Nhận', '', 'Tom', '+61412345678', '12 King St, Newtown NSW'))
        self.assertEqual((t['source'], t['ai_conversation_id'], t['chat_token_hash'], t['preferred_window']),
                         ('ai_bot', f'{TECH}:0412345678', 'tokT', 'morning'))
        self.assertTrue(t['noi_dung'].startswith('[AI chat] Air-con leaking water inside'))
        self.assertIn('Mon 02 Nov, morning', t['noi_dung'])
        self.assertEqual((t['lat'], t['lng']), GEO['point'])
        self.assertTrue(out['located_on_map'])
        self.assertEqual(CALLS[-1][4], 'technical_job')
        self.assertIn((['business_id', 'ai_dedupe_key'], {'ai_dedupe_key': {'$exists': True}}), DB.tasks.uniques)

    def test_without_app_loaded_no_geocode(self):
        saved = _app._geocode_address
        del _app._geocode_address
        try:
            out = job()
        finally:
            _app._geocode_address = saved
        self.assertFalse(out['located_on_map'])
        self.assertNotIn('lat', DB.tasks.find_one({'id': out['job_id']}))

    def test_emergency_keywords_hand_off_urgently(self):
        out = job(customer_id=f'{TECH}:0412345678', args={'problem': 'I can smell gas near the heater'})
        self.assertEqual(out['urgency'], 'emergency')
        self.assertIn('000', out['tell_customer'])
        self.assertIn("can't promise", out['tell_customer'])
        bc = DB.bot_customers.find_one({'id': f'{TECH}:0412345678'})
        self.assertIsNone(bc)   # chưa có hội thoại trong DB giả -> update_one không tạo mới
        DB.bot_customers.insert_one({'id': f'{TECH}:0499000111'})
        job(customer_id=f'{TECH}:0499000111', args={'problem': 'Nước ngập sàn bếp, gần ổ điện', 'address': '5 Lê Lợi, Q1, HCM'})
        bc = DB.bot_customers.find_one({'id': f'{TECH}:0499000111'})
        self.assertTrue(bc['needs_human'] and bc['handoff_urgent'] and bc['ai_paused'])
        self.assertEqual(CALLS[-1][4], 'technical_emergency')

    def test_emergency_regex_avoids_false_alarms(self):
        for txt in ('flood light not working', 'spark plug on the mower', 'fire alarm beeping, battery low',
                    'bóng đèn bị cháy', 'máy lạnh chảy nước'):
            self.assertFalse(technical.is_emergency(txt), txt)
        for txt in ('burst pipe in the laundry', 'sparks from the power point', 'chập điện ở ổ cắm', 'mùi khét từ tủ điện',
                    'water everywhere after the hose broke'):
            self.assertTrue(technical.is_emergency(txt), txt)

    def test_validation_creates_nothing(self):
        bad = ({'address': 'here'}, {'address': '123456'}, {'problem': 'no'}, {'preferred_date': '2026-10-01'},
               {'preferred_date': '02/11/2026'}, {'preferred_date': '2027-06-01'}, {'preferred_window': 'midnight'},
               {'urgency': 'asap'}, {'service_id': 77}, {'phone': 'none'})
        for a in bad:
            with self.subTest(a=a), self.assertRaises(PackError):
                job(args=a)
        with self.assertRaises(PackError):
            technical.execute('technical_request_job', {'address': '12 King St, Newtown', 'problem': 'broken'}, ctx(TECH))
        self.assertEqual(DB.tasks.docs, [])

    def test_service_price_in_shop_currency_and_dedupe(self):
        out = job(args={'service_id': 1}, customer_id=f'{TECH}:0412345678')
        t = DB.tasks.find_one({'id': out['job_id']})
        self.assertIn('[DỊCH VỤ] Air-con service [Giá Thu]: $129.00', t['noi_dung'])
        self.assertNotIn('40', t['noi_dung'].split('[Giá Thu]')[1])     # không bao giờ ghi hoa hồng thợ
        again = job(args={'service_id': 1}, customer_id=f'{TECH}:0412345678')
        self.assertTrue(again['already_requested'])
        self.assertEqual(again['job_id'], out['job_id'])
        self.assertEqual(len(DB.tasks.docs), 1)

    def test_insert_once_survives_a_concurrent_upsert(self):
        job(customer_id=f'{TECH}:0412345678')
        DB.tasks.fail_next_fam = DuplicateKeyError('E11000')
        again = job(customer_id=f'{TECH}:0412345678')
        self.assertTrue(again['already_requested'])
        self.assertEqual(len(DB.tasks.docs), 1)

    def test_job_status_ownership_and_states(self):
        mine = job(chat_token_hash='tokT', customer_id=TECH_CHAT)['job_id']
        DB.tasks.insert_one({'id': 500, 'business_id': TECH, 'ten_khach': 'Tom', 'sdt': '0412 345 678', 'dia_chi': '1 A St',
                             'noi_dung': '[DỊCH VỤ] X [Hoa Hồng]: 50', 'trang_thai': 'Đã Nhận', 'nguoi_nhan': 'Liam Nguyen',
                             'on_way_at': '2026-10-30T09:40'})
        DB.tasks.insert_one({'id': 501, 'business_id': TECH, 'sdt': '0412 345 679', 'trang_thai': 'Chờ Nhận', 'dia_chi': 'x'})
        by_token = technical.execute('technical_job_status', {}, ctx(TECH, chat_token_hash='tokT', customer_id=TECH_CHAT))['jobs']
        self.assertEqual([(j['job_id'], j['state']) for j in by_token], [(mine, 'waiting')])
        self.assertEqual(by_token[0]['problem'], 'Air-con leaking water inside')
        jt = types.ModuleType('job_tracking')
        jt.track_token = lambda bid, tid: 'sig123'
        sys.modules['job_tracking'] = jt
        try:
            by_phone = technical.execute('technical_job_status', {}, ctx(TECH, chat_token_hash='x', phone='+61412345678'))['jobs']
        finally:
            sys.modules.pop('job_tracking', None)
        self.assertEqual([j['job_id'] for j in by_phone], [500, mine])      # mới nhất trước
        staff_made = by_phone[0]
        self.assertEqual((staff_made['state'], staff_made['assigned_to']), ('on_the_way', 'Liam'))
        self.assertTrue(staff_made['live_tracking_link'].endswith(f'/track/{TECH}/500/sig123'))
        self.assertNotIn('problem', staff_made)               # việc tạo tay: không trả noi_dung (hoa hồng nội bộ)
        self.assertNotIn('Hoa Hồng', str(by_phone))
        one = technical.execute('technical_job_status', {'job_id': 500}, ctx(TECH, chat_token_hash='x', phone='+61412345678'))
        self.assertEqual([j['job_id'] for j in one['jobs']], [500])

    def test_job_status_shared_browser_needs_the_typed_phone(self):
        mine = job(customer_id=f'{TECH}:0412345678', chat_token_hash='tokJ')['job_id']
        nxt = ctx(TECH, chat_token_hash='tokJ', customer_id=f'{TECH}:0499000111', contact_phone='0499000111')
        self.assertEqual(technical.execute('technical_job_status', {}, nxt)['jobs'], [])
        me = ctx(TECH, chat_token_hash='tokJ', customer_id=f'{TECH}:0412345678', contact_phone='0412345678')
        self.assertEqual([j['job_id'] for j in technical.execute('technical_job_status', {}, me)['jobs']], [mine])

    def test_job_status_refuses_strangers(self):
        job(chat_token_hash='tokT', customer_id=TECH_CHAT)
        self.assertEqual(technical.execute('technical_job_status', {}, ctx(TECH, chat_token_hash='tokOther',
                                                                         customer_id=TECH_CHAT))['jobs'], [])
        with self.assertRaises(PackError) as e:
            technical.execute('technical_job_status', {}, ctx(TECH, chat_token_hash='anon:1'))
        self.assertIn('not_verified', str(e.exception))
        DB.tasks.insert_one({'id': 600, 'business_id': TECH, 'sdt': '(212) 345-6789', 'trang_thai': 'Chờ Nhận', 'dia_chi': 'y'})
        out = technical.execute('technical_job_status', {}, ctx(TECH, chat_token_hash='q', phone='+13123456789', country='US'))
        self.assertEqual(out['jobs'], [])

    def test_facts_price_list_without_commission(self):
        f = technical.facts(TECH, 'en', NOW)
        self.assertIn('service_id 1: Air-con service — $129.00', f)
        self.assertNotIn('$40', f)
        self.assertIn('EMERGENCY NUMBER in this country: 000', f)


# ================================================================ sản xuất
def quote(**kw):
    args = {'product': 'Áo thun in logo', 'quantity': 500, 'unit': 'pcs', 'deadline': '2026-12-15', 'specs': 'Size S-XL, in 2 màu',
            'customer_name': 'Chị Hạnh', 'phone': '0901 234 567', 'company': 'Hanh Co', 'email': 'hanh@example.com'}
    args.update(kw.pop('args', {}))
    return production.execute('production_request_quote', args, ctx(PROD, lang='vi', **kw))


class ProductionTests(unittest.TestCase):
    def setUp(self):
        seed()

    def test_quote_request_is_saved_for_the_owner_without_prices(self):
        out = quote(customer_id=f'{PROD}:0901234567', chat_token_hash='tokP')
        self.assertEqual(out['status'], 'new')
        self.assertIn('không báo giá được', out['tell_customer'])
        q = DB.quote_requests.find_one({'id': out['quote_request_id']})
        self.assertEqual((q['business_id'], q['status'], q['quantity'], q['deadline'], q['customer_phone'], q['source'],
                          q['ai_conversation_id'], q['chat_token_hash']),
                         (PROD, 'new', 500, '2026-12-15', '+84901234567', 'ai_bot', f'{PROD}:0901234567', 'tokP'))
        self.assertEqual(CALLS[-1][4], 'quote_request')
        self.assertIn('Yêu cầu BÁO GIÁ mới', CALLS[-2][3])            # tiệm Việt Nam -> ghi chú nhân viên tiếng Việt
        self.assertNotRegex(out['tell_customer'], r'\d+\.\d{3}đ')

    def test_validation(self):
        for a in ({'quantity': 0}, {'quantity': -5}, {'quantity': 'lots'}, {'quantity': True}, {'product': 'x'},
                  {'deadline': '2026-01-01'}, {'deadline': '15/12/2026'}, {'deadline': '2030-01-01'}, {'email': 'not-an-email'},
                  {'phone': ''}, {'customer_name': ''}):
            with self.subTest(a=a), self.assertRaises(PackError):
                quote(args=a)
        self.assertEqual(DB.quote_requests.docs, [])

    def test_dedupe_same_request_same_day(self):
        a = quote(customer_id=f'{PROD}:0901234567')
        b = quote(customer_id=f'{PROD}:0901234567')
        self.assertTrue(b['already_requested'])
        self.assertEqual(b['quote_request_id'], a['quote_request_id'])
        c = quote(customer_id=f'{PROD}:0901234567', args={'quantity': 800})
        self.assertNotEqual(c['quote_request_id'], a['quote_request_id'])
        self.assertEqual(len(DB.quote_requests.docs), 2)

    def test_facts_list_names_never_prices(self):
        f = production.facts(PROD, 'vi', NOW)
        self.assertIn('Áo thun cotton', f)
        self.assertNotIn('120.000', f)
        self.assertTrue(production.FACTS_INCLUDE_CATALOG)


# ================================================================ văn phòng
def consult(**kw):
    args = {'topic': 'Set up a small company', 'preferred_date': '2026-11-03', 'preferred_time': '14:00', 'mode': 'video',
            'customer_name': 'Ana', 'phone': '(312) 555-0199'}
    args.update(kw.pop('args', {}))
    return office.execute('office_request_consultation', args, ctx(OFFICE, now_local=NY_NOW, **kw))


class OfficeTests(unittest.TestCase):
    def setUp(self):
        seed()

    def test_request_is_pending_until_the_office_calls(self):
        out = consult(chat_token_hash='tokO')
        self.assertEqual(out['status'], 'pending')
        self.assertIn('nothing is booked', out['tell_customer'])
        c = DB.consultation_requests.find_one({'id': out['consult_request_id']})
        self.assertEqual((c['status'], c['preferred_date'], c['preferred_time'], c['mode'], c['customer_phone'], c['source']),
                         ('pending', '2026-11-03', '14:00', 'video', '+13125550199', 'ai_bot'))
        self.assertEqual(CALLS[-1][4], 'consult_request')
        self.assertEqual(DB.consult_requests.docs, [])            # tên collection thống nhất với core: consultation_requests

    def test_time_checks_against_office_hours(self):
        for a, word in (({'preferred_date': '2026-11-01'}, 'closed'), ({'preferred_time': '18:00'}, 'outside office hours'),
                        ({'preferred_date': '2026-10-29'}, 'in the past'), ({'preferred_date': '', 'preferred_time': '10:00'}, 'which day'),
                        ({'preferred_time': '25:00'}, 'HH:MM'), ({'mode': 'carrier pigeon'}, 'mode'),
                        ({'preferred_date': '2026-10-30', 'preferred_time': '09:00'}, 'already passed')):
            with self.subTest(a=a):
                with self.assertRaises(PackError) as e:
                    consult(args=a)
                self.assertIn(word, str(e.exception))
        self.assertEqual(DB.consultation_requests.docs, [])

    def test_no_preferred_time_and_dedupe(self):
        a = consult(args={'preferred_date': '', 'preferred_time': '', 'mode': ''}, customer_id=f'{OFFICE}:3125550199')
        self.assertTrue(a['success'])
        b = consult(args={'preferred_date': '', 'preferred_time': '', 'mode': ''}, customer_id=f'{OFFICE}:3125550199')
        self.assertTrue(b['already_requested'])
        self.assertEqual(len(DB.consultation_requests.docs), 1)
        with self.assertRaises(PackError):
            consult(args={'topic': 'hi'})

    def test_facts_and_rules_forbid_professional_advice(self):
        self.assertIn('legal, tax', office.PROMPT_RULES['en'])
        self.assertIn('pháp lý', office.PROMPT_RULES['vi'])
        self.assertIn('office_request_consultation', office.facts(OFFICE, 'en', NOW))


# ================================================================ trang / API nhân viên (retail_holds_bp.py)
class StaffBlueprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from jinja2 import ChoiceLoader, DictLoader
        import retail_holds_bp as bp
        cls.bp = bp
        app = Flask(__name__, static_folder=os.path.join(ROOT, 'static'))
        app.secret_key = 'test'
        app.jinja_loader = ChoiceLoader([DictLoader({'components/app_sidebar.html': '<nav>sidebar</nav>'}), app.jinja_loader])
        app.register_blueprint(bp.retail_holds_bp)
        cls.app = app

    def setUp(self):
        seed()
        self.c = self.app.test_client()

    def login(self, bid=AU, mode='retail', role='staff'):
        with self.c.session_transaction() as s:
            s.update({'user_id': f'u_{bid}', 'business_id': bid, 'business_mode': mode, 'role': role})

    def _hold_far(self, **kw):
        out = hold(now_local=datetime.now(TZ), **kw)
        DB.retail_holds.update_one({'id': out['hold_id']}, {'$set': {'expires_at_local': '2099-01-01T12:00'}})
        return out['hold_id']

    def test_requires_login_and_right_industry(self):
        self.assertEqual(self.c.get('/api/retail/holds').status_code, 401)
        self.login(PROD, 'production')
        self.assertEqual(self.c.get('/api/retail/holds').status_code, 403)
        self.assertEqual(self.c.get('/retail/holds').status_code, 302)
        self.assertEqual(self.c.get('/api/requests/consultations').status_code, 403)

    def test_hold_list_is_scoped_and_formatted(self):
        hid = self._hold_far()
        DB.retail_holds.insert_one({'id': 999, 'business_id': OTHER, 'status': 'pending', 'product_name': 'Not mine', 'quantity': 1})
        self.login()
        d = self.c.get('/api/retail/holds').get_json()
        self.assertTrue(d['success'])
        self.assertEqual([i['id'] for i in d['items']], [hid])
        it = d['items'][0]
        self.assertEqual((it['product'], it['total'], it['status'], it['source'], it['open'] if 'open' in it else d['open']),
                         ('Sữa tươi Vinamilk 1L', '$9.00', 'pending', 'ai_bot', 1))
        self.assertEqual(it['pickup_by'], 'Thu 01 Jan, 12:00')

    def test_staff_confirm_pickup_and_conflicts(self):
        hid = self._hold_far()
        self.login()
        r = self.c.post(f'/api/retail/holds/{hid}/status', json={'status': 'ready'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['item']['status'], 'ready')
        self.assertEqual(self.c.post(f'/api/retail/holds/{hid}/status', json={'status': 'ready'}).status_code, 409)
        self.assertEqual(self.c.post(f'/api/retail/holds/{hid}/status', json={'status': 'expired'}).status_code, 400)
        self.assertEqual(self.c.post('/api/retail/holds/12345/status', json={'status': 'cancelled'}).status_code, 404)
        r = self.c.post(f'/api/retail/holds/{hid}/status', json={'status': 'picked_up'})
        self.assertEqual(r.get_json()['item']['status'], 'picked_up')
        self.assertEqual(product(1)['held_qty'], 0)
        self.assertEqual(self.c.get('/api/retail/holds?view=active').get_json()['items'], [])
        self.assertEqual(len(self.c.get('/api/retail/holds?view=all').get_json()['items']), 1)
        self.login(OTHER, 'retail')        # tiệm khác không đổi được hold của tiệm này
        self.assertEqual(self.c.post(f'/api/retail/holds/{hid}/status', json={'status': 'cancelled'}).status_code, 404)

    def test_expired_holds_are_released_when_staff_open_the_list(self):
        hid = self._hold_far()
        DB.retail_holds.update_one({'id': hid}, {'$set': {'expires_at_local': '2000-01-01T00:00'}})
        self.login()
        self.assertEqual(self.c.get('/api/retail/holds').get_json()['items'], [])
        self.assertEqual(DB.retail_holds.find_one({'id': hid})['status'], 'expired')
        self.assertEqual(product(1)['held_qty'], 0)

    def test_quotes_owner_only(self):
        rid = quote(customer_id=f'{PROD}:0901234567')['quote_request_id']
        self.login(PROD, 'production', 'staff')
        self.assertEqual(self.c.get('/api/requests/quotes').status_code, 403)
        self.login(PROD, 'production', 'admin')
        self.c.set_cookie('bitpaw_lang', 'vi')
        d = self.c.get('/api/requests/quotes').get_json()
        self.assertEqual([i['id'] for i in d['items']], [rid])
        self.assertEqual(d['items'][0]['deadline'], 'T3 15/12/2026')
        r = self.c.post(f'/api/requests/quotes/{rid}/status', json={'status': 'contacted', 'staff_note': ' called,  sending PDF '})
        self.assertEqual(r.get_json()['item']['staff_note'], 'called, sending PDF')
        self.assertEqual(DB.quote_requests.find_one({'id': rid})['status'], 'contacted')
        self.assertEqual(self.c.post(f'/api/requests/quotes/{rid}/status', json={'status': 'paid'}).status_code, 400)
        self.assertEqual(self.c.post('/api/requests/quotes/777/status', json={'status': 'won'}).status_code, 404)
        self.c.post(f'/api/requests/quotes/{rid}/status', json={'status': 'lost'})
        self.assertEqual(self.c.get('/api/requests/quotes').get_json()['items'], [])
        self.assertEqual(len(self.c.get('/api/requests/quotes?view=all').get_json()['items']), 1)

    def test_consultations_front_desk(self):
        rid = consult()['consult_request_id']
        self.login(OFFICE, 'office', 'staff')
        d = self.c.get('/api/requests/consultations').get_json()
        self.assertEqual(d['items'][0]['preferred'], 'Tue 03 Nov 2026 14:00')
        r = self.c.post(f'/api/requests/consultations/{rid}/status', json={'status': 'confirmed'})
        self.assertEqual(r.get_json()['item']['status'], 'confirmed')

    def test_pages_render_and_inline_script_is_valid_js(self):
        node = shutil.which('node')
        for bid, mode, role, path, title in ((AU, 'retail', 'staff', '/retail/holds', 'Pickup holds'),
                                             (PROD, 'production', 'admin', '/requests/quotes', 'Quote requests'),
                                             (OFFICE, 'office', 'staff', '/requests/consultations', 'Consultation requests')):
            self.login(bid, mode, role)
            for lang, want in (('en', title), ('vi', None)):
                self.c.set_cookie('bitpaw_lang', lang)
                r = self.c.get(path)
                html = r.get_data(as_text=True)
                self.assertEqual(r.status_code, 200, path)
                self.assertIn('<nav>sidebar</nav>', html)
                if want:
                    self.assertIn(f'<h1>{want}</h1>', html)
                else:
                    self.assertIn('lang="vi"', html)
                scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
                self.assertEqual(len(scripts), 1)
                if node:
                    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
                        f.write(scripts[0])
                    try:
                        res = subprocess.run([node, '--check', f.name], capture_output=True, text=True)
                        self.assertEqual(res.returncode, 0, res.stderr)
                    finally:
                        os.unlink(f.name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
