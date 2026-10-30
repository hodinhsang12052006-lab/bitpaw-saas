# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 "AI receptionist that really books": gói đặt bàn F&B (ai_packs/fnb.py, RESOURCE 'table') và gói
đặt phòng karaoke / bida theo giờ (ai_packs/karaoke.py, RESOURCE 'room_hour'), logic chung reservations_core.py, và 2 route
công khai /api/public/reservations/<id>, /api/public/karaoke_reservations/<id> nay gọi chung hàm ghi.

Mỗi công cụ: đường thuận, hết chỗ / chồng giờ, từ chối khi không phải đặt chỗ của chat này, pending vs confirmed theo cài đặt
của quán, dữ liệu sai. Giờ theo múi giờ quán (ctx.now_local), tiền theo tiền tệ của quán.

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi DeepSeek / mạng:
mongo_client + requests được thay TRƯỚC mọi import. Route công khai được tách bằng ast từ app.py và chạy với request giả.

Chạy: python scripts/tests/test_phase2_table_room_packs.py
"""
import ast
import copy
import io
import json
import os
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from itertools import count

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from pymongo.errors import DuplicateKeyError  # noqa: E402  (chỉ lớp lỗi, không kết nối)


# ---------------------------------------------------------------- DB giả trong RAM
def _get(doc, key):
    cur = doc
    for part in str(key).split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _cmp(v, op, arg):
    if v is None:
        return False
    try:
        return {'$gte': v >= arg, '$gt': v > arg, '$lt': v < arg, '$lte': v <= arg}[op]
    except TypeError:
        return False


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
            if op == '$regex' and not (isinstance(v, str) and re.search(arg, v, re.I if 'i' in str(cond.get('$options', '')) else 0)):
                return False
            if op in ('$gte', '$gt', '$lt', '$lte') and not _cmp(v, op, arg):
                return False
        return True
    return v == cond


def _matches(doc, flt):
    for k, cond in (flt or {}).items():
        if k == '$or':
            if not any(_matches(doc, f) for f in cond):
                return False
        elif k == '$and':
            if not all(_matches(doc, f) for f in cond):
                return False
        elif k == '$nor':
            if any(_matches(doc, f) for f in cond):
                return False
        elif not _match_value(_get(doc, k), cond):
            return False
    return True


def _set_path(doc, key, value):
    parts = key.split('.')
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


class _Cursor(list):
    def sort(self, key, direction=1):
        def k(d):
            v = d.get(key)
            return (v is None, v if isinstance(v, (int, float)) else str(v or ''))
        return _Cursor(sorted(self, key=k, reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs = name, []

    def insert_one(self, doc):
        if '_id' in doc and any(d.get('_id') == doc['_id'] for d in self.docs):
            raise DuplicateKeyError('E11000 duplicate key')
        self.docs.append(copy.deepcopy(doc))
        return types.SimpleNamespace(inserted_id=doc.get('_id'))

    def insert_many(self, docs):
        for d in docs:
            self.insert_one(d)

    def find(self, flt=None, projection=None):
        return _Cursor(copy.deepcopy(d) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = self.find(flt)
        if sort:
            rows = rows.sort(*sort[0])
        return rows[0] if rows else None

    def count_documents(self, flt=None):
        return len(self.find(flt))

    @staticmethod
    def _apply(doc, update, inserting=False):
        for k, v in (update.get('$set') or {}).items():
            _set_path(doc, k, copy.deepcopy(v))
        for k in (update.get('$unset') or {}):
            doc.pop(k, None)
        for k, v in (update.get('$inc') or {}).items():
            doc[k] = (doc.get(k) or 0) + v
        if inserting:
            for k, v in (update.get('$setOnInsert') or {}).items():
                _set_path(doc, k, v)

    @staticmethod
    def _seed(flt):
        return {k: v for k, v in flt.items() if not k.startswith('$') and not isinstance(v, dict)}

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                return types.SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            new = self._seed(flt)
            self._apply(new, update, inserting=True)
            self.insert_one(new)
        return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                n += 1
        return types.SimpleNamespace(matched_count=n, modified_count=n)

    def find_one_and_update(self, flt, update, upsert=False, projection=None, return_document=False, sort=None):
        for d in self.docs:
            if _matches(d, flt):
                before = copy.deepcopy(d)
                self._apply(d, update)
                return copy.deepcopy(d) if return_document else before
        if upsert:
            new = self._seed(flt)
            self._apply(new, update, inserting=True)
            self.insert_one(new)  # _id đã có (khoá đang bị giữ) -> DuplicateKeyError như Mongo thật
            return copy.deepcopy(new) if return_document else None
        return None

    def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                del self.docs[i]
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)


class FakeDB:
    def __init__(self):
        self.__dict__['_c'] = {}

    def __getattr__(self, name):
        if name not in self._c:
            self._c[name] = FakeCollection(name)
        return self._c[name]

    def __getitem__(self, name):
        return getattr(self, name)

    def reset(self):
        self._c.clear()


DB = FakeDB()
_ids = count(7000)
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED',
                                                    load_env_file=lambda *a, **k: None)
_req = types.ModuleType('requests')          # không bao giờ gọi mạng
_req.post = _req.get = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network call in offline test'))
sys.modules['requests'] = _req
_msg = types.ModuleType('messaging')         # không gửi email / SMS thật
_msg.get_settings = lambda bid: {}
_msg.queue = lambda *a, **k: None
_msg.deliver = lambda *a, **k: None
sys.modules['messaging'] = _msg

# ai_packs/__init__.py (registry + PackError) thuộc phần core; chưa có / không nạp được trong môi trường test này thì dùng
# gói giả tối thiểu trỏ đúng thư mục ai_packs/ để nạp 2 gói thật.
try:
    import ai_packs  # noqa: E402
    ai_packs.PackError  # noqa: B018
except Exception:
    for _k in [k for k in sys.modules if k == 'ai_packs' or k.startswith('ai_packs.')]:
        del sys.modules[_k]
    ai_packs = types.ModuleType('ai_packs')
    ai_packs.__path__ = [os.path.join(ROOT, 'ai_packs')]

    class PackError(Exception):
        pass
    ai_packs.PackError = PackError
    sys.modules['ai_packs'] = ai_packs

import booking_rules  # noqa: E402
import reservations_core as rc  # noqa: E402
from ai_packs import fnb, karaoke  # noqa: E402

PackError = ai_packs.PackError
BID = 'biz-p2'
TZ = timezone(timedelta(hours=11))                # giờ quán (AEDT) — khác giờ máy chủ
NOW = datetime(2026, 10, 26, 15, 0, tzinfo=TZ)    # thứ Hai 15:00 tại quán
FRI = '2026-10-30'
SUN = '2026-11-01'
FNB_HOURS = {'mon': ['11:00', '22:00'], 'tue': ['11:00', '22:00'], 'wed': ['11:00', '22:00'], 'thu': ['11:00', '22:00'],
             'fri': ['11:00', '23:00'], 'sat': ['11:00', '23:00'], 'sun': None}
KTV_HOURS = {d: ['14:00', '24:00'] for d in rc.DAY_KEYS}


def web_ctx(token='t' * 40, phone=None, **kw):
    ctx = {'business_id': BID, 'customer_id': f"{BID}:0412345678", 'channel': 'web', 'phone': phone,
           'chat_token_hash': ('h-' + token) if token else None, 'lang': 'en', 'now_local': NOW, 'customer_name': None}
    ctx.update(kw)
    return ctx


def biz(industry, currency='USD', country='AU', address='12 George St, Sydney'):
    DB.businesses.insert_one({'id': BID, 'name': 'Test Venue', 'industry_code': industry, 'currency': currency,
                              'country': country, 'address': address, 'phone': '02 9000 1234'})


def settings(hours=None, auto_confirm=None, table=None, karaoke_rules=None, **extra):
    doc = {'business_id': BID}
    if hours is not None:
        doc['hours'] = hours
    if auto_confirm is not None:
        doc['auto_confirm'] = auto_confirm
    if table is not None:
        doc['table_reservations'] = table
    if karaoke_rules is not None:
        doc['karaoke_reservations'] = karaoke_rules
    doc.update(extra)
    DB.booking_settings.insert_one(doc)


def table_row(rid, when, party, status='pending', table_id=None, phone='0400 000 000', **kw):
    doc = {'id': rid, 'business_id': BID, 'customer_name': 'Walk-in form', 'customer_phone': phone, 'party_size': party,
           'reserved_time': when, 'table_id': table_id, 'note': None, 'status': status, 'created_at': '2026-10-20T10:00:00'}
    doc.update(kw)
    DB.table_reservations.insert_one(doc)


def room(rid, name, rate, status='Trống'):
    DB.karaoke_rooms.insert_one({'id': rid, 'business_id': BID, 'name': name, 'price_per_hour': rate, 'status': status,
                                 'start_time': None})


def ktv_row(rid, when, hours, room_id, status='confirmed', phone='0400 000 000', **kw):
    doc = {'id': rid, 'business_id': BID, 'customer_name': 'Form', 'customer_phone': phone, 'party_size': 4,
           'reserved_time': when, 'duration_hours': hours, 'room_id': room_id, 'note': None, 'status': status,
           'created_at': '2026-10-20T10:00:00'}
    doc.update(kw)
    DB.karaoke_room_reservations.insert_one(doc)


class Base(unittest.TestCase):
    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()
        self._lock_wait = rc.LOCK_WAIT_SECONDS
        rc.LOCK_WAIT_SECONDS = 0.2

    def tearDown(self):
        rc.LOCK_WAIT_SECONDS = self._lock_wait

    def call(self, pack, name, args, ctx=None):
        return pack.execute(name, args, ctx or web_ctx())

    def refuse(self, pack, name, args, ctx=None):
        with self.assertRaises(PackError) as cm:
            self.call(pack, name, args, ctx)
        return str(cm.exception)


# ================================================================ contract
class PackContract(unittest.TestCase):
    def test_both_packs_follow_the_contract(self):
        for pack, industries, resource, prefix in ((fnb, ('fnb',), 'table', 'fnb_'), (karaoke, ('karaoke',), 'room_hour', 'karaoke_')):
            self.assertEqual(pack.INDUSTRIES, industries)
            self.assertEqual(pack.RESOURCE, resource)
            names = [t['function']['name'] for t in pack.TOOLS]
            self.assertTrue(all(n.startswith(prefix) for n in names), names)
            self.assertEqual(len(names), 5)
            self.assertTrue(pack.MANAGE_TOOLS <= set(names))
            self.assertEqual(len(pack.MANAGE_TOOLS), 3)
            for t in pack.TOOLS:
                self.assertEqual(t['type'], 'function')
                params = t['function']['parameters']
                self.assertEqual(params['type'], 'object')
                self.assertTrue(set(params['required']) <= set(params['properties']), t['function']['name'])
                self.assertGreater(len(t['function']['description']), 40)
            self.assertEqual(set(pack.PROMPT_RULES), {'en', 'vi'})
            self.assertTrue(callable(pack.facts) and callable(pack.execute))
            self.assertIs(pack.FACTS_INCLUDE_CATALOG, True)       # facts() đã có thực đơn / phòng + giá

    @unittest.skipUnless(hasattr(ai_packs, '_validate'), 'registry lõi ai_packs/__init__.py chưa có trong worktree này')
    def test_core_registry_accepts_both_packs(self):
        for name, mod in (('fnb', fnb), ('karaoke', karaoke)):
            pack = ai_packs._validate(name, mod)
            self.assertEqual((pack.resource, pack.industries), (mod.RESOURCE, mod.INDUSTRIES))
            self.assertEqual(pack.manage_tools, frozenset(mod.MANAGE_TOOLS))
            self.assertTrue(pack.facts_include_catalog)

    def test_no_salon_vocabulary_in_pack_text(self):
        DB.reset()
        biz('fnb')
        settings(hours=FNB_HOURS)
        DB.products.insert_one({'id': 1, 'business_id': BID, 'name': 'Pho', 'price': 14.5, 'is_active': 1})
        room(1, 'VIP 1', 30)
        text = json.dumps([fnb.TOOLS, karaoke.TOOLS, fnb.PROMPT_RULES, karaoke.PROMPT_RULES], ensure_ascii=False)
        text += fnb.facts(BID, 'en', NOW) + karaoke.facts(BID, 'en', NOW)
        for word in ('salon', 'technician', 'manicure', 'nail', 'BitPaw'):
            self.assertNotIn(word.lower(), text.lower(), word)

    def test_unknown_tool_and_missing_business_are_refused(self):
        with self.assertRaises(PackError):
            fnb.execute('book_appointment', {}, web_ctx())
        with self.assertRaises(PackError):
            karaoke.execute('karaoke_check_rooms', {'date': FRI}, dict(web_ctx(), business_id=None))


# ================================================================ F&B facts
class FnbFacts(Base):
    def test_request_only_shop_without_hours_or_capacity(self):
        biz('fnb')
        DB.products.insert_many([{'id': 1, 'business_id': BID, 'name': 'Pho', 'price': 14.5, 'is_active': 1, 'allergens': ['peanut']},
                                 {'id': 2, 'business_id': BID, 'name': 'Old dish', 'price': 9, 'is_active': 0}])
        f = fnb.facts(BID, 'en', NOW)
        self.assertIn('2026-10-26 15:00 (Monday)', f)               # giờ quán, không phải giờ máy chủ
        self.assertIn('OPENING HOURS: not published', f)
        self.assertIn('no live availability', f)
        self.assertIn('REQUESTS the restaurant approves', f)
        self.assertIn('Pho — $14.50', f)                             # tiền tệ của quán (AUD hiển thị $)
        self.assertIn('allergens listed by the restaurant: peanut', f)
        self.assertNotIn('Old dish', f)
        self.assertIn('12 George St, Sydney', f)                      # địa chỉ hồ sơ quán khi Thông tin chưa ghi
        self.assertIn('02 9000 1234', f)
        self.assertNotIn('₫', f)

    def test_live_capacity_and_auto_confirm_are_stated(self):
        biz('fnb', currency='VND', country='VN')
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 20, 'slot_minutes': 15, 'hold_minutes': 15,
                                                             'max_party_auto': 8},
                 info={'parking': 'Free parking at the back', 'cancellation_policy': 'Call 2h ahead'})
        DB.products.insert_one({'id': 1, 'business_id': BID, 'name': 'Phở bò', 'price': 65000, 'is_active': 1})
        f = fnb.facts(BID, 'vi', NOW)
        self.assertIn('Mon 11:00-22:00', f)
        self.assertIn('Sun closed', f)
        self.assertIn('up to 20 guests arriving per 15-minute slot', f)
        self.assertIn('CONFIRMED instantly', f)
        self.assertIn('groups over 8 are requests', f)
        self.assertIn('held for 15 minutes', f)
        self.assertIn('Free parking at the back', f)
        self.assertIn('65.000đ', f)


# ================================================================ F&B tools
class FnbRequestOnly(Base):
    """Quán chưa nhập sức chứa: AI chỉ ghi YÊU CẦU 'pending' — không bao giờ nói còn bàn."""

    def setUp(self):
        super().setUp()
        biz('fnb')

    def test_check_never_claims_free(self):
        r = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'time': '19:00', 'party_size': 4})
        self.assertEqual(r['availability'], 'request_only')
        self.assertIsNone(r['requested_time']['free'])
        self.assertTrue(r['requested_time']['can_request'])
        self.assertEqual(r['if_booked_status'], 'pending')
        self.assertEqual(r['pending_reason'], 'no_live_availability')
        self.assertNotIn('available_times', r)

    def test_reserve_creates_one_pending_row_tagged_ai_and_no_appointment(self):
        r = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '7pm', 'party_size': 4, 'customer_name': 'Mia Chen',
                                                 'phone': '0412 345 678', 'note': 'High chair please, birthday'})
        self.assertTrue(r['success'])
        self.assertEqual(r['status'], 'pending')
        self.assertIn('do not say confirmed', r['say'].lower())
        rows = DB.table_reservations.docs
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['reserved_time'], '2026-10-30T19:00:00')   # giờ quán, đúng khuôn form công khai
        self.assertEqual((row['party_size'], row['status'], row['source'], row['table_id']), (4, 'pending', 'ai_bot', None))
        self.assertEqual(row['ai_conversation_id'], f"{BID}:0412345678")
        self.assertEqual(row['chat_token_hash'], 'h-' + 't' * 40)
        self.assertEqual(row['note'], 'High chair please, birthday')
        self.assertEqual(DB.appointments.docs, [])
        self.assertTrue(any('#%d' % row['id'] in m['content'] for m in DB.bot_messages.docs))  # chủ quán thấy trong hộp thư AI

    def test_bad_input_is_refused(self):
        msg = self.refuse(fnb, 'fnb_check_tables', {'date': '30/10/2026', 'party_size': 2})
        self.assertIn('YYYY-MM-DD', msg)
        self.refuse(fnb, 'fnb_check_tables', {'date': FRI, 'time': '25:00', 'party_size': 2})
        self.refuse(fnb, 'fnb_check_tables', {'date': FRI, 'party_size': 0})
        self.assertIn('online limit is 50', self.refuse(fnb, 'fnb_check_tables', {'date': FRI, 'party_size': 80}))
        base = {'date': FRI, 'time': '19:00', 'party_size': 2, 'phone': '0412345678'}
        self.assertIn('name', self.refuse(fnb, 'fnb_reserve_table', dict(base, customer_name='  ')))
        self.assertIn('phone', self.refuse(fnb, 'fnb_reserve_table', dict(base, customer_name='Mia', phone='123')))
        self.refuse(fnb, 'fnb_reserve_table', {'date': FRI, 'party_size': 2, 'customer_name': 'Mia', 'phone': '0412345678'})
        self.assertEqual(DB.table_reservations.docs, [])

    def test_past_time_in_shop_timezone(self):
        r = self.call(fnb, 'fnb_reserve_table', {'date': '2026-10-26', 'time': '14:30', 'party_size': 2, 'customer_name': 'Mia',
                                                 'phone': '0412345678'})
        self.assertFalse(r['success'])
        self.assertEqual(r['reason'], 'in_the_past')
        self.assertEqual(DB.table_reservations.docs, [])
        ok = self.call(fnb, 'fnb_reserve_table', {'date': '2026-10-26', 'time': '15:30', 'party_size': 2, 'customer_name': 'Mia',
                                                  'phone': '0412345678'})
        self.assertTrue(ok['success'])

    def test_verified_phone_is_used_when_customer_gave_none(self):
        ctx = web_ctx(token=None, phone='+61412345678', channel='sms', customer_id=f"{BID}:sms:+61412345678")
        r = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '19:00', 'party_size': 2, 'customer_name': 'Mia'}, ctx)
        self.assertTrue(r['success'])
        self.assertEqual(DB.table_reservations.docs[0]['customer_phone'], '+61412345678')


class FnbCovers(Base):
    """Quán đã nhập 'tối đa N khách mỗi khung giờ' + giờ mở cửa."""

    def setUp(self):
        super().setUp()
        biz('fnb')

    def reserve(self, time='19:00', party=4, name='Mia', phone='0412345678', ctx=None, date=FRI):
        return self.call(fnb, 'fnb_reserve_table', {'date': date, 'time': time, 'party_size': party, 'customer_name': name,
                                                    'phone': phone}, ctx)

    def test_capacity_conflict_offers_real_alternatives(self):
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 10, 'slot_minutes': 30})
        table_row(1, '2026-10-30T19:00:00', 6)                   # yêu cầu từ form công khai (pending) cũng chiếm chỗ
        table_row(2, '2026-10-30T19:15', 2, status='confirmed')
        table_row(3, '2026-10-30T19:00:00', 8, status='cancelled')  # đã huỷ: không tính
        chk = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'time': '19:00', 'party_size': 4})
        self.assertEqual(chk['availability'], 'live')
        self.assertFalse(chk['requested_time']['free'])
        self.assertNotIn('19:00', chk['available_times'])
        self.assertIn('19:30', chk['available_times'])
        self.assertIn('18:30', chk['available_times'])
        r = self.reserve(party=4)
        self.assertFalse(r['success'])
        self.assertEqual(r['reason'], 'fully_booked')
        self.assertIn('19:30', r['other_times_same_day'])
        self.assertEqual(len(DB.table_reservations.docs), 3)
        ok = self.reserve(party=2)                                 # 8 + 2 = 10 vừa đủ
        self.assertTrue(ok['success'])
        self.assertEqual(ok['status'], 'confirmed')
        self.assertEqual(self.reserve(party=1, name='Leo', phone='0499888777')['reason'], 'fully_booked')

    def test_pending_when_shop_did_not_turn_on_auto_confirm(self):
        settings(hours=FNB_HOURS, table={'max_covers_per_slot': 30})          # chưa từng lưu "tự xác nhận"
        r = self.reserve()
        self.assertEqual((r['status'], r['pending_reason']), ('pending', 'shop_confirms'))
        DB.reset()
        biz('fnb')
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 30, 'auto_confirm': False})
        self.assertEqual(self.reserve()['status'], 'pending')

    def test_pending_without_published_hours(self):
        settings(auto_confirm=True, table={'max_covers_per_slot': 30})
        r = self.reserve()
        self.assertEqual((r['status'], r['pending_reason']), ('pending', 'hours_not_published'))

    def test_large_party_is_pending_and_flags_staff(self):
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 40, 'max_party_auto': 6})
        r = self.reserve(party=9)
        self.assertEqual((r['status'], r['pending_reason']), ('pending', 'large_party'))
        self.assertTrue(r['needs_staff'])
        self.assertEqual(self.reserve(party=6, phone='0499888777', name='Leo')['status'], 'confirmed')

    def test_opening_hours_closed_day_and_last_booking(self):
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 30, 'last_booking_before_close': 60})
        r = self.reserve(date=SUN)
        self.assertEqual(r['reason'], 'closed_that_day')
        self.assertEqual(r['next_available'][0]['date'], '2026-11-02')
        late = self.reserve(time='22:30')
        self.assertEqual(late['reason'], 'too_close_to_closing')
        self.assertIn('latest start that fits is 22:00', late['message'])
        early = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'time': '09:00', 'party_size': 2})
        self.assertFalse(early['requested_time']['free'])
        self.assertIn('11:00-23:00', early['requested_time']['why'])
        self.assertEqual(DB.table_reservations.docs, [])

    def test_owner_min_lead_time_is_respected(self):
        settings(hours=FNB_HOURS, auto_confirm=True, min_lead_minutes=120, table={'max_covers_per_slot': 30})
        r = self.reserve(date='2026-10-26', time='16:00')
        self.assertEqual(r['reason'], 'too_soon')
        self.assertTrue(self.reserve(date='2026-10-26', time='17:00')['success'])

    def test_double_submit_returns_the_same_reservation(self):
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 30})
        a = self.reserve()
        b = self.reserve(name='Mia Chen')
        self.assertTrue(b['already_reserved'])
        self.assertEqual(a['reservation_id'], b['reservation_id'])
        self.assertEqual(len(DB.table_reservations.docs), 1)
        self.assertEqual(DB.table_reservations.docs[0]['customer_name'], 'Mia Chen')
        self.assertEqual(DB.reservation_locks.docs, [])                         # trả bản cũ cũng nhả khoá
        # kiểm trùng nằm TRONG khoá: lượt gọi thứ 2 chạy song song (khoá đang bị giữ) bị báo bận, không tạo bàn thứ 2
        DB.reservation_locks.insert_one({'_id': f"table|{BID}", 'until': 9e12, 'token': 'other'})
        self.assertIn('busy', self.refuse(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '19:00', 'party_size': 2,
                                                                     'customer_name': 'Mia', 'phone': '0412345678'}))
        self.assertEqual(len(DB.table_reservations.docs), 1)

    def test_same_phone_booked_elsewhere_is_not_revealed(self):
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 30})
        table_row(50, '2026-10-30T19:00:00', 2, phone='0412 345 678')        # form công khai, cùng SĐT
        r = self.reserve()
        # chat chưa chứng minh là chủ: không nói "SĐT này đã có bàn đúng giờ này" (dò được giờ người khác tới quán) — trả lời
        # chung như 1 yêu cầu chờ quán xác nhận, không tạo bàn thứ 2, quán nhận ghi chú để tự liên hệ khách
        self.assertNotIn('already_reserved', r)
        self.assertNotIn('reservation_id', r)
        self.assertNotIn('already', json.dumps(r).lower())
        self.assertTrue(r['request_sent_to_team'])
        self.assertEqual(r['status'], 'pending')
        self.assertIn('do not say confirmed', r['say'].lower())
        self.assertEqual(len(DB.table_reservations.docs), 1)
        self.assertTrue(any('#50' in m['content'] for m in DB.bot_messages.docs))

    def test_lock_held_by_another_booking_is_refused_honestly(self):
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 30})
        DB.reservation_locks.insert_one({'_id': f"table|{BID}", 'until': 9e12, 'token': 'other'})
        self.assertIn('busy', self.refuse(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '19:00', 'party_size': 2,
                                                                     'customer_name': 'Mia', 'phone': '0412345678'}))
        self.assertEqual(DB.table_reservations.docs, [])
        DB.reservation_locks.docs[0]['until'] = 0                               # khoá hết hạn (tiến trình chết) -> lấy lại được
        self.assertTrue(self.reserve()['success'])
        self.assertEqual(DB.reservation_locks.docs, [])                         # nhả khoá sau khi ghi


class FnbTables(Base):
    """Bàn có số ghế (dining_tables.seats): giữ đúng 1 bàn, tính cả yêu cầu chưa xếp bàn."""

    def setUp(self):
        super().setUp()
        biz('fnb')
        settings(hours=FNB_HOURS, auto_confirm=True, table={'dining_minutes': 90})
        DB.dining_tables.insert_many([{'id': 1, 'business_id': BID, 'name': 'T1', 'seats': 2},
                                      {'id': 2, 'business_id': BID, 'name': 'T2', 'seats': 4},
                                      {'id': 3, 'business_id': BID, 'name': 'T3', 'seats': 4},
                                      {'id': 4, 'business_id': BID, 'name': 'T4', 'seats': 6},
                                      {'id': 5, 'business_id': BID, 'name': 'Bar'}])           # không có số ghế: bỏ qua

    def reserve(self, party, time='19:00', phone='0412345678'):
        return self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': time, 'party_size': party, 'customer_name': 'Mia',
                                                    'phone': phone})

    def test_assigns_smallest_fitting_table_and_blocks_when_full(self):
        table_row(1, '2026-10-30T18:30:00', 5, status='confirmed', table_id=4)   # T4 bận 18:30-20:00
        table_row(2, '2026-10-30T19:30:00', 4)                                    # chưa xếp bàn: sẽ cần 1 bàn 4
        r = self.reserve(3)
        # bàn 4 ghế (T2 hoặc T3 — 1 bàn được trừ hao cho yêu cầu 19:30 chưa xếp), không lấy T4 đang bận, không T1 (2 ghế)
        self.assertEqual(r['status'], 'confirmed')
        self.assertIn(r['table'], ('T2', 'T3'))
        self.assertIn(DB.table_reservations.find_one({'id': r['reservation_id']})['table_id'], (2, 3))
        # bàn 4 ghế còn lại phải dành cho yêu cầu 19:30 chưa xếp -> nhóm 4 lúc 19:00 hết bàn
        full = self.reserve(4, phone='0499888777')
        self.assertFalse(full['success'])
        self.assertEqual(full['reason'], 'no_table')
        self.assertTrue(full['other_times_same_day'])
        self.assertEqual(self.reserve(2, phone='0499111222')['table'], 'T1')

    def test_party_bigger_than_any_table_is_a_pending_request(self):
        r = self.reserve(10)
        self.assertEqual((r['status'], r['pending_reason'], r['table']), ('pending', 'large_party', None))


class FnbManage(Base):
    def setUp(self):
        super().setUp()
        biz('fnb')
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 10})
        self.mine = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '19:00', 'party_size': 2, 'customer_name': 'Mia',
                                                         'phone': '0412345678'})['reservation_id']
        table_row(900, '2026-10-30T20:00:00', 3, status='confirmed', phone='0412345678')  # cùng SĐT, đặt qua form

    def test_my_reservations_only_this_chat(self):
        r = self.call(fnb, 'fnb_my_reservations', {})
        self.assertEqual([x['reservation_id'] for x in r['reservations']], [self.mine])
        self.assertEqual(r['reservations'][0]['time'], '2026-10-30 19:00')
        other = self.call(fnb, 'fnb_my_reservations', {}, web_ctx(token='x' * 40))
        self.assertEqual(other['reservations'], [])
        self.assertIn('02 9000 1234', other['tell_customer'])
        anon = self.call(fnb, 'fnb_my_reservations', {}, web_ctx(token=None))
        self.assertFalse(anon['verified'])
        self.assertEqual(anon['reservations'], [])
        vi = self.call(fnb, 'fnb_my_reservations', {}, web_ctx(token=None, lang='vi'))
        self.assertIn('Vì bảo mật', vi['tell_customer'])

    def test_verified_phone_sees_form_reservations_in_any_format(self):
        ctx = web_ctx(token=None, phone='+61 412 345 678', channel='sms', customer_id=f"{BID}:sms:+61412345678")
        ids = [x['reservation_id'] for x in self.call(fnb, 'fnb_my_reservations', {}, ctx)['reservations']]
        self.assertEqual(ids, [self.mine, 900])

    def test_messenger_conversation_owns_its_bookings(self):
        cid = f"{BID}:messenger:psid-1"
        ctx = web_ctx(token=None, channel='messenger', customer_id=cid)
        rid = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '18:00', 'party_size': 2, 'customer_name': 'Ana',
                                                   'phone': '0433222111'}, ctx)['reservation_id']
        self.assertEqual([x['reservation_id'] for x in self.call(fnb, 'fnb_my_reservations', {}, ctx)['reservations']], [rid])
        # cùng customer_id nhưng trên chat web (không có mã trình duyệt) -> không chứng minh được
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': rid}, dict(ctx, channel='web'))

    def test_cancel_own_and_refuse_others(self):
        msg = self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': 900})
        self.assertIn('does not belong', msg.replace('No reservation with that id belongs', 'does not belong'))
        self.assertEqual(DB.table_reservations.find_one({'id': 900})['status'], 'confirmed')
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': 123456})     # không tồn tại: cùng câu, không lộ gì
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': 'abc'})
        r = self.call(fnb, 'fnb_cancel_reservation', {'reservation_id': self.mine})
        self.assertTrue(r['cancelled'])
        row = DB.table_reservations.find_one({'id': self.mine})
        self.assertEqual((row['status'], row['cancelled_by']), ('cancelled', 'customer_ai_chat'))
        self.assertTrue(self.call(fnb, 'fnb_cancel_reservation', {'reservation_id': self.mine})['already_cancelled'])

    def test_seated_or_past_cannot_be_cancelled(self):
        DB.table_reservations.update_one({'id': self.mine}, {'$set': {'status': 'seated'}})
        self.assertIn("'seated'", self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': self.mine}))
        DB.table_reservations.update_one({'id': self.mine}, {'$set': {'status': 'confirmed', 'reserved_time': '2026-10-26T12:00:00'}})
        self.assertIn('passed', self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': self.mine}))

    def test_change_time_rechecks_capacity(self):
        table_row(901, '2026-10-30T20:30:00', 9, status='confirmed')
        full = self.call(fnb, 'fnb_change_reservation', {'reservation_id': self.mine, 'time': '20:30'})
        self.assertFalse(full['success'])
        self.assertTrue(full['reservation_unchanged'])
        self.assertEqual(DB.table_reservations.find_one({'id': self.mine})['reserved_time'], '2026-10-30T19:00:00')
        r = self.call(fnb, 'fnb_change_reservation', {'reservation_id': self.mine, 'time': '21:00', 'party_size': 4})
        self.assertTrue(r['success'])
        row = DB.table_reservations.find_one({'id': self.mine})
        self.assertEqual((row['reserved_time'], row['party_size'], row['status']), ('2026-10-30T21:00:00', 4, 'confirmed'))
        self.assertEqual(row['rescheduled_from'], '2026-10-30T19:00:00')
        # đổi chính nó không tự chặn mình: 19:00 có 2 chỗ của mình -> đổi số khách 2 -> 10 vẫn vừa khung trống
        same = self.call(fnb, 'fnb_change_reservation', {'reservation_id': self.mine, 'time': '21:00', 'party_size': 10})
        self.assertTrue(same['success'])

    def test_change_needs_reapproval_when_shop_confirms_by_hand(self):
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'auto_confirm': False}})
        DB.table_reservations.update_one({'id': self.mine}, {'$set': {'status': 'confirmed', 'table_id': 3}})
        r = self.call(fnb, 'fnb_change_reservation', {'reservation_id': self.mine, 'date': '2026-10-29', 'time': '18:00'})
        self.assertEqual((r['status'], r['previous_status']), ('pending', 'confirmed'))
        self.assertIn('confirm it again', r['note'])
        self.assertIsNone(DB.table_reservations.find_one({'id': self.mine})['table_id'])  # bàn cũ có thể không còn trống

    def test_change_refuses_other_people(self):
        self.refuse(fnb, 'fnb_change_reservation', {'reservation_id': 900, 'time': '21:00'})
        self.assertEqual(DB.table_reservations.find_one({'id': 900})['reserved_time'], '2026-10-30T20:00:00')


class OwnershipAndContact(Base):
    """Cùng luật chứng minh chủ với lõi (ai_packs.manage_filter): mã 'anon:' không là bằng chứng, customer_id web
    không bao giờ là bằng chứng (chỉ hội thoại kênh nền tảng), SĐT so theo nước quán (không so 'mấy số cuối'), contact_phone chỉ để liên lạc."""

    def setUp(self):
        super().setUp()
        biz('fnb')
        settings(hours=FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 30})

    def reserve(self, ctx, time='19:00', **kw):
        args = {'date': FRI, 'time': time, 'party_size': 2, 'customer_name': 'Mia', 'phone': '0412345678'}
        args.update(kw)
        return self.call(fnb, 'fnb_reserve_table', args, ctx)

    def test_anon_token_is_not_proof(self):
        anon = web_ctx(token=None, chat_token_hash='anon:1f2e3d', customer_id=f"{BID}:0412345678~anon")
        rid = self.reserve(anon)['reservation_id']
        self.assertEqual(DB.table_reservations.find_one({'id': rid})['chat_token_hash'], 'anon:1f2e3d')
        mine = self.call(fnb, 'fnb_my_reservations', {}, dict(anon))
        self.assertFalse(mine['verified'])
        self.assertEqual(mine['reservations'], [])
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': rid}, dict(anon))
        self.assertEqual(DB.table_reservations.find_one({'id': rid})['status'], 'confirmed')

    def test_web_conversation_id_is_never_proof_and_staff_note_goes_to_the_thread(self):
        thread = f"{BID}:0412345678"                     # chat web: '<quán>:<SĐT khách gõ>' — ai gõ SĐT đó cũng có
        ctx = web_ctx(token='a' * 40, customer_id=thread)
        rid = self.reserve(ctx)['reservation_id']
        row = DB.table_reservations.find_one({'id': rid})
        self.assertEqual((row['ai_conversation_id'], row['chat_token_hash'], row['source']), (thread, 'h-' + 'a' * 40, 'ai_bot'))
        self.assertTrue(any(m['customer_id'] == thread and '#%d' % rid in m['content'] for m in DB.bot_messages.docs))
        # cùng thread (cùng SĐT đã gõ) nhưng trình duyệt khác (mã chat khác) -> không thấy, không huỷ / đổi được
        stranger = web_ctx(token='c' * 40, customer_id=thread)
        self.assertEqual(self.call(fnb, 'fnb_my_reservations', {}, stranger)['reservations'], [])
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': rid}, stranger)
        self.refuse(fnb, 'fnb_change_reservation', {'reservation_id': rid, 'time': '20:00'}, stranger)
        # chỉ có customer_id web, không mã chat, không SĐT xác minh -> không có gì để chứng minh
        bare = web_ctx(token=None, customer_id=thread)
        self.assertFalse(self.call(fnb, 'fnb_my_reservations', {}, bare)['verified'])
        self.assertEqual(rc.ownership_query(bare), None)
        # kể cả dạng cũ '<thread>~<băm>' trên web cũng không còn là bằng chứng (lõi chỉ tin mã chat / SĐT xác minh)
        legacy = web_ctx(token=None, customer_id=thread + '~0123456789abcdef')
        DB.table_reservations.update_one({'id': rid}, {'$set': {'ai_conversation_id': thread + '~0123456789abcdef'}})
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': rid}, legacy)
        # cùng mã chat -> của mình; dòng báo chủ quán vào đúng thread_id khi có
        explicit = web_ctx(token='a' * 40, customer_id=thread, thread_id='thread-77')
        self.call(fnb, 'fnb_cancel_reservation', {'reservation_id': rid}, explicit)
        self.assertEqual(DB.table_reservations.find_one({'id': rid})['status'], 'cancelled')
        self.assertTrue(any(m['customer_id'] == 'thread-77' for m in DB.bot_messages.docs))

    def test_shared_browser_token_alone_is_not_proof(self):
        # máy tính bảng quầy lễ tân: 1 mã trình duyệt cho mọi khách -> khách kế tiếp gõ SĐT khác không thấy / đổi / huỷ được
        # bàn của người trước; cùng khách gõ lại SĐT của mình (cách viết khác) vẫn là của mình
        a = web_ctx(token='a' * 40, customer_id=f"{BID}:0412345678", contact_phone='0412345678')
        rid = self.reserve(a)['reservation_id']
        b = web_ctx(token='a' * 40, customer_id=f"{BID}:0499000111", contact_phone='0499000111')
        self.assertEqual(self.call(fnb, 'fnb_my_reservations', {}, b)['reservations'], [])
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': rid}, b)
        self.refuse(fnb, 'fnb_change_reservation', {'reservation_id': rid, 'time': '20:00'}, b)
        self.assertEqual(DB.table_reservations.find_one({'id': rid})['status'], 'confirmed')
        again = web_ctx(token='a' * 40, customer_id=f"{BID}:+61412345678", contact_phone='+61412345678')
        self.assertEqual([x['reservation_id'] for x in self.call(fnb, 'fnb_my_reservations', {}, again)['reservations']], [rid])
        self.assertFalse(rc.is_owned(DB.table_reservations.find_one({'id': rid}), b))
        self.assertTrue(rc.is_owned(DB.table_reservations.find_one({'id': rid}), a))
        # karaoke: cùng luật
        room(1, 'Room A (2-6 people)', 20)
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'hours': KTV_HOURS}})
        k = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 4,
                                                        'customer_name': 'Kai', 'phone': '0412345678'}, dict(a))
        self.assertEqual(self.call(karaoke, 'karaoke_my_reservations', {}, dict(b))['reservations'], [])
        self.refuse(karaoke, 'karaoke_cancel_reservation', {'reservation_id': k['reservation_id']}, dict(b))
        self.assertEqual([x['reservation_id'] for x in self.call(karaoke, 'karaoke_my_reservations', {}, dict(a))['reservations']],
                         [k['reservation_id']])

    def test_platform_conversation_id_is_proof(self):
        conv = f"{BID}:messenger:psid-123"
        ctx = web_ctx(token=None, channel='messenger', customer_id=conv, chat_token_hash='conv:' + 'd' * 48)
        rid = self.reserve(ctx)['reservation_id']
        same_thread = dict(ctx, chat_token_hash='conv:' + 'e' * 48)   # cùng hội thoại nền tảng ký -> của mình
        self.assertEqual([x['reservation_id'] for x in self.call(fnb, 'fnb_my_reservations', {}, same_thread)['reservations']], [rid])
        other = web_ctx(token=None, channel='messenger', customer_id=f"{BID}:messenger:psid-999", chat_token_hash='conv:' + 'f' * 48)
        self.assertEqual(self.call(fnb, 'fnb_my_reservations', {}, other)['reservations'], [])
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': rid}, other)

    def test_phone_match_follows_the_shop_country(self):
        self.assertTrue(rc.same_phone('0412 345 678', '+61 412 345 678', 'AU'))
        self.assertTrue(rc.same_phone('(212) 555-1234', '+12125551234', 'US'))
        self.assertFalse(rc.same_phone('(312) 555-1234', '+12125551234', 'US'))   # chỉ trùng 9 số cuối: KHÁC người
        self.assertTrue(rc.same_phone('0912 345 678', '+84912345678', 'VN'))
        self.assertFalse(rc.same_phone('1234567', '1234567', 'US'))                # quá ngắn: không bao giờ là bằng chứng
        DB.businesses.update_one({'id': BID}, {'$set': {'country': 'US'}})
        table_row(70, '2026-10-30T20:00:00', 2, status='confirmed', phone='(312) 555-1234')
        table_row(71, '2026-10-30T21:00:00', 2, status='confirmed', phone='212.555.1234')
        ctx = web_ctx(token=None, phone='+12125551234', channel='sms', customer_id=f"{BID}:sms:+12125551234")
        ids = [x['reservation_id'] for x in self.call(fnb, 'fnb_my_reservations', {}, ctx)['reservations']]
        self.assertEqual(ids, [71])
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': 70}, ctx)

    def test_own_bookings_are_found_in_a_busy_restaurant(self):
        for i in range(600):                                  # 600 đặt bàn của người khác xếp TRƯỚC đặt bàn của khách
            table_row(10000 + i, '2026-10-27T12:00:00', 1, status='confirmed', phone=f'0400 {i:06d}')
        rid = self.reserve(web_ctx())['reservation_id']
        table_row(90, '2026-11-20T19:00:00', 2, status='pending', phone='0412-345-678')   # form, cách ghi khác
        self.assertEqual([x['reservation_id'] for x in self.call(fnb, 'fnb_my_reservations', {})['reservations']], [rid])
        ctx = web_ctx(token=None, phone='+61412345678', channel='sms', customer_id=f"{BID}:sms:+61412345678")
        self.assertEqual([x['reservation_id'] for x in self.call(fnb, 'fnb_my_reservations', {}, ctx)['reservations']],
                         [rid, 90])
        self.assertIsNone(rc.ownership_query(web_ctx(token=None)))
        self.assertIsNone(rc.ownership_query(web_ctx(token=None, chat_token_hash='anon:5', customer_id=f"{BID}:1~anon")))

    def test_contact_phone_books_but_never_proves_ownership(self):
        table_row(80, '2026-10-30T20:00:00', 2, status='confirmed', phone='0412345678')   # form công khai, cùng SĐT
        ctx = web_ctx(token=None, chat_token_hash='anon:9', contact_phone='0412 345 678', customer_name='Mia Chen')
        r = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '18:00', 'party_size': 2}, ctx)
        self.assertTrue(r['success'])
        row = DB.table_reservations.find_one({'id': r['reservation_id']})
        self.assertEqual((row['customer_phone'], row['customer_name']), ('0412 345 678', 'Mia Chen'))
        self.assertFalse(self.call(fnb, 'fnb_my_reservations', {}, dict(ctx))['verified'])
        self.refuse(fnb, 'fnb_cancel_reservation', {'reservation_id': 80}, dict(ctx))
        # thiếu cả SĐT lẫn tên -> phải hỏi khách, không ghi gì
        self.assertIn('phone', self.refuse(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '18:30', 'party_size': 2,
                                                                      'customer_name': 'Leo'}, web_ctx()))
        self.assertIn('name', self.refuse(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '18:30', 'party_size': 2,
                                                                     'phone': '0499888777'}, web_ctx()))
        self.assertEqual(len(DB.table_reservations.docs), 2)

    def test_karaoke_uses_the_same_ownership_rules(self):
        room(1, 'Room A (2-6 people)', 20)
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'hours': KTV_HOURS}})
        anon = web_ctx(token=None, chat_token_hash='anon:2', contact_phone='0412345678')
        r = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 4,
                                                        'customer_name': 'Kai'}, anon)
        self.assertTrue(r['success'])
        row = DB.karaoke_room_reservations.find_one({'id': r['reservation_id']})
        self.assertEqual((row['customer_phone'], row['source'], row['room_id']), ('0412345678', 'ai_bot', 1))
        self.assertFalse(self.call(karaoke, 'karaoke_my_reservations', {}, dict(anon))['verified'])
        self.refuse(karaoke, 'karaoke_cancel_reservation', {'reservation_id': r['reservation_id']}, dict(anon))
        verified = web_ctx(token=None, phone='+61412345678', channel='whatsapp', customer_id=f"{BID}:whatsapp:61412345678")
        self.assertTrue(self.call(karaoke, 'karaoke_cancel_reservation', {'reservation_id': r['reservation_id']},
                                  verified)['cancelled'])


# ================================================================ Karaoke
class KaraokeBase(Base):
    def setUp(self):
        super().setUp()
        biz('karaoke')
        room(1, 'VIP Room 1', 25)
        room(2, 'Couple Room (2–4)', 12)
        room(3, 'Family Room (6-8 people)', 18)
        room(4, 'Pool Table 1', 6)

    def reserve(self, time='20:00', hours=2, group=4, phone='0412345678', ctx=None, date=FRI, **kw):
        args = {'date': date, 'time': time, 'hours': hours, 'group_size': group, 'customer_name': 'Kai', 'phone': phone}
        args.update(kw)
        return self.call(karaoke, 'karaoke_reserve_room', args, ctx)


class KaraokeFacts(KaraokeBase):
    def test_rooms_rates_sizes_and_policies(self):
        settings(hours=KTV_HOURS, auto_confirm=True, karaoke_rules={'hold_minutes': 15})
        DB.products.insert_many([{'id': 1, 'business_id': BID, 'name': 'Tiger beer', 'price': 8, 'is_active': 1},
                                 {'id': 2, 'business_id': BID, 'name': 'Karaoke room time', 'price': 0, 'is_active': 1,
                                  'is_room_fee': True},
                                 {'id': 3, 'business_id': BID, 'name': 'Tap water', 'price': 0, 'is_active': 1}])
        f = karaoke.facts(BID, 'en', NOW)
        self.assertIn('VIP Room 1 (room_id 1, karaoke room) — $25.00/hour, size not listed', f)
        self.assertIn('Couple Room (2–4) (room_id 2, karaoke room) — $12.00/hour, up to 4 people', f)
        self.assertIn('Pool Table 1 (room_id 4, billiards table)', f)
        self.assertIn('Mon 14:00-24:00', f)
        self.assertIn('held 15 minutes', f)
        self.assertIn('CONFIRMED instantly', f)
        self.assertIn('Tiger beer — $8.00', f)
        self.assertNotIn('Karaoke room time', f)
        self.assertNotIn('Tap water', f)                                  # menu QR phòng hát chỉ có món có giá

    def test_vnd_venue_prices(self):
        DB.businesses.update_one({'id': BID}, {'$set': {'currency': 'VND', 'country': 'VN'}})
        DB.karaoke_rooms.update_one({'id': 1}, {'$set': {'price_per_hour': 250000}})
        self.assertIn('250.000đ/hour', karaoke.facts(BID, 'vi', NOW))
        r = self.call(karaoke, 'karaoke_check_rooms', {'date': FRI, 'time': '20:00', 'hours': 3, 'group_size': 2,
                                                       'room_type': 'VIP'})
        self.assertEqual(r['rooms'][0]['estimated_room_charge'], '750.000đ')

    def test_no_rooms_listed(self):
        DB.karaoke_rooms.docs.clear()
        self.assertIn('not listed its rooms', karaoke.facts(BID, 'en', NOW))
        self.assertIn('not listed its rooms', self.refuse(karaoke, 'karaoke_check_rooms', {'date': FRI}))


class KaraokeBooking(KaraokeBase):
    def setUp(self):
        super().setUp()
        settings(hours=KTV_HOURS, auto_confirm=True)

    def test_check_quotes_rate_times_hours_and_filters_by_size_and_kind(self):
        r = self.call(karaoke, 'karaoke_check_rooms', {'date': FRI, 'time': '20:00', 'hours': 2.5, 'group_size': 6})
        names = [x['name'] for x in r['rooms']]
        self.assertEqual(names[0], 'Family Room (6-8 people)')          # vừa cỡ trước
        self.assertNotIn('Couple Room (2–4)', names)                     # 4 chỗ < 6 người
        self.assertNotIn('Pool Table 1', names)                          # mặc định phòng karaoke
        self.assertIn('VIP Room 1', names)
        self.assertTrue(next(x for x in r['rooms'] if x['name'] == 'VIP Room 1')['size_unknown'])
        self.assertEqual(r['rooms'][0]['estimated_room_charge'], '$45.00')   # 18 x 2.5
        self.assertEqual((r['start'], r['end']), ('20:00', '22:30'))
        self.assertEqual(r['if_booked_status'], 'confirmed')
        pool = self.call(karaoke, 'karaoke_check_rooms', {'date': FRI, 'time': '20:00', 'hours': 1, 'group_size': 2,
                                                          'room_type': 'bida'})
        self.assertEqual([x['name'] for x in pool['rooms']], ['Pool Table 1'])
        self.assertEqual(pool['rooms'][0]['estimated_room_charge'], '$6.00')

    def test_reserve_holds_a_room_and_overlap_moves_to_another_room(self):
        a = self.reserve(group=6)
        self.assertEqual((a['status'], a['room'], a['estimated_room_charge']), ('confirmed', 'Family Room (6-8 people)', '$36.00'))
        row = DB.karaoke_room_reservations.find_one({'id': a['reservation_id']})
        self.assertEqual((row['room_id'], row['duration_hours'], row['reserved_time'], row['source']),
                         (3, 2.0, '2026-10-30T20:00:00', 'ai_bot'))
        self.assertEqual(row['estimated_room_charge'], 36.0)
        # 21:00-23:00 chồng giờ với phòng 3 -> chọn đúng phòng 3 bị từ chối, kèm phòng khác còn trống
        taken = self.reserve(time='21:00', group=6, room_id=3, phone='0499888777')
        self.assertFalse(taken['success'])
        self.assertEqual(taken['reason'], 'room_taken')
        self.assertEqual([x['name'] for x in taken['other_free_rooms']], ['VIP Room 1'])
        moved = self.reserve(time='21:00', group=6, phone='0499888777')
        self.assertEqual(moved['room'], 'VIP Room 1')
        self.assertTrue(moved['size_unknown'])
        self._assert_no_overlapping_pair()

    def _assert_no_overlapping_pair(self):
        for r in DB.karaoke_room_reservations.docs:
            if r['status'] in rc.KARAOKE_ACTIVE and r.get('room_id') is not None:
                self.assertFalse(rc.karaoke_overlaps(BID, r['room_id'], r['reserved_time'], r['duration_hours'], exclude_id=r['id']),
                                 r)

    def test_everything_busy_offers_other_times_and_counts_unassigned_requests(self):
        ktv_row(1, '2026-10-30T19:00:00', 3, 1)
        ktv_row(2, '2026-10-30T20:00:00', 2, 2)
        ktv_row(3, '2026-10-30T18:00:00', 4, None, status='pending', note='Pool table please')  # form chưa xếp: giữ 1 bàn bida
        ktv_row(4, '2026-10-30T19:30', 2, None, status='cancelled')        # đã huỷ: không tính
        r = self.reserve(time='20:00', group=3)                             # còn phòng 3 + bàn bida, 1 yêu cầu bida chưa xếp
        self.assertTrue(r['success'])
        self.assertEqual(r['room'], 'Family Room (6-8 people)')
        pool = self.reserve(time='20:00', group=2, phone='0499111222', room_kind='billiards')
        self.assertEqual(pool['reason'], 'no_room')                         # bàn bida duy nhất dành cho yêu cầu bida đang chờ
        full = self.reserve(time='20:30', group=3, phone='0499888777')
        self.assertFalse(full['success'])
        self.assertEqual(full['reason'], 'no_room')
        self.assertIn('22:00', full['other_start_times_same_day'])
        self.assertNotIn('20:30', full['other_start_times_same_day'])
        self._assert_no_overlapping_pair()

    def test_walk_in_room_in_use_is_not_offered_right_now(self):
        DB.karaoke_rooms.update_many({'id': {'$in': [1, 2, 3]}}, {'$set': {'status': 'Đang chơi'}})
        soon = self.call(karaoke, 'karaoke_check_rooms', {'date': '2026-10-26', 'time': '16:00', 'hours': 1, 'group_size': 2})
        self.assertFalse(soon['requested_time']['free'])
        later = self.call(karaoke, 'karaoke_check_rooms', {'date': '2026-10-26', 'time': '19:00', 'hours': 1, 'group_size': 2})
        self.assertTrue(later['requested_time']['free'])

    def test_session_must_end_by_closing(self):
        r = self.reserve(time='23:00', hours=2)
        self.assertEqual(r['reason'], 'too_close_to_closing')
        self.assertIn('latest start that fits is 22:00', r['message'])
        self.assertTrue(self.reserve(time='22:00', hours=2)['success'])

    def test_bad_input(self):
        self.assertIn('0.5-12 hours', self.refuse(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 20,
                                                                                    'group_size': 2, 'customer_name': 'Kai',
                                                                                    'phone': '0412345678'}))
        self.refuse(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 0.25, 'group_size': 2,
                                                      'customer_name': 'Kai', 'phone': '0412345678'})
        self.refuse(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'group_size': 2, 'customer_name': 'Kai',
                                                      'phone': '0412345678'})          # thiếu số giờ: không tự đoán khi ĐẶT
        self.refuse(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 0,
                                                      'customer_name': 'Kai', 'phone': '0412345678'})
        self.assertIn('room_id', self.refuse(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2,
                                                                               'group_size': 2, 'customer_name': 'Kai',
                                                                               'phone': '0412345678', 'room_id': 99}))
        self.assertIn('up to 4', self.refuse(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2,
                                                                               'group_size': 6, 'customer_name': 'Kai',
                                                                               'phone': '0412345678', 'room_id': 2}))
        self.assertIn('phone', self.refuse(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2,
                                                                             'group_size': 2, 'customer_name': 'Kai'}))
        self.assertEqual(DB.karaoke_room_reservations.docs, [])

    def test_check_without_hours_assumes_two_and_says_so(self):
        r = self.call(karaoke, 'karaoke_check_rooms', {'date': FRI, 'time': '20:00'})
        self.assertIn('hours_assumed', r)
        self.assertIn('group_size_missing', r)
        day = self.call(karaoke, 'karaoke_check_rooms', {'date': FRI, 'hours': 2, 'group_size': 2})
        self.assertIn('14:00', day['free_start_times'])
        self.assertNotIn('23:00', day['free_start_times'])

    def test_same_phone_booked_elsewhere_is_not_revealed(self):
        ktv_row(60, '2026-10-30T20:00:00', 2, 1, phone='0412 345 678')        # form công khai, cùng SĐT, cùng giờ
        r = self.reserve()
        self.assertNotIn('already_reserved', r)
        self.assertNotIn('reservation_id', r)
        self.assertNotIn('already', json.dumps(r).lower())
        self.assertTrue(r['request_sent_to_team'])
        self.assertEqual(r['status'], 'pending')
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 1)
        self.assertTrue(any('#60' in m['content'] for m in DB.bot_messages.docs))

    def test_double_submit_is_one_booking(self):
        a = self.reserve()
        b = self.reserve()
        self.assertEqual(a['reservation_id'], b['reservation_id'])
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 1)
        self.assertTrue(b['already_reserved'])
        self.assertEqual(DB.reservation_locks.docs, [])


class KaraokeStatus(KaraokeBase):
    def test_pending_without_hours_or_without_auto_confirm(self):
        settings(auto_confirm=True)
        r = self.reserve()
        self.assertEqual((r['status'], r['pending_reason']), ('pending', 'hours_not_published'))
        self.assertIn('do not say confirmed', r['say'].lower())
        DB.reset()
        KaraokeBase.setUp(self)
        settings(hours=KTV_HOURS, auto_confirm=False)
        self.assertEqual(self.reserve()['pending_reason'], 'shop_confirms')
        DB.reset()
        KaraokeBase.setUp(self)
        settings(hours=KTV_HOURS)                       # chủ quán chưa từng lưu "tự xác nhận" -> chờ duyệt
        self.assertEqual(self.reserve()['status'], 'pending')
        DB.reset()
        KaraokeBase.setUp(self)
        settings(hours=KTV_HOURS, auto_confirm=False, karaoke_rules={'auto_confirm': True, 'hold_minutes': 10})
        r = self.reserve()
        self.assertEqual(r['status'], 'confirmed')
        self.assertIn('10 minutes', r['hold_policy'])


class KaraokeManage(KaraokeBase):
    def setUp(self):
        super().setUp()
        settings(hours=KTV_HOURS, auto_confirm=True)
        self.mine = self.reserve(group=2, room_id=2)['reservation_id']               # Couple room 20:00-22:00
        ktv_row(900, '2026-10-30T18:00:00', 2, 1, phone='0412345678')                # cùng SĐT, form công khai

    def test_my_reservations_scope(self):
        r = self.call(karaoke, 'karaoke_my_reservations', {})
        self.assertEqual([x['reservation_id'] for x in r['reservations']], [self.mine])
        self.assertEqual((r['reservations'][0]['room'], r['reservations'][0]['estimated_room_charge']), ('Couple Room (2–4)', '$24.00'))
        self.assertEqual(self.call(karaoke, 'karaoke_my_reservations', {}, web_ctx(token='z' * 40))['reservations'], [])
        self.assertFalse(self.call(karaoke, 'karaoke_my_reservations', {}, web_ctx(token=None))['verified'])

    def test_cancel(self):
        self.refuse(karaoke, 'karaoke_cancel_reservation', {'reservation_id': 900})
        self.assertEqual(DB.karaoke_room_reservations.find_one({'id': 900})['status'], 'confirmed')
        self.assertTrue(self.call(karaoke, 'karaoke_cancel_reservation', {'reservation_id': self.mine})['cancelled'])
        self.assertEqual(DB.karaoke_room_reservations.find_one({'id': self.mine})['status'], 'cancelled')
        # phòng mở lại cho người khác
        self.assertEqual(self.reserve(group=2, room_id=2, phone='0499888777')['room'], 'Couple Room (2–4)')

    def test_change_keeps_room_when_free_else_moves(self):
        r = self.call(karaoke, 'karaoke_change_reservation', {'reservation_id': self.mine, 'hours': 3})
        self.assertEqual((r['room'], r['room_changed'], r['estimated_room_charge']), ('Couple Room (2–4)', False, '$36.00'))
        ktv_row(901, '2026-10-30T23:30', 0.5, 2)
        moved = self.call(karaoke, 'karaoke_change_reservation', {'reservation_id': self.mine, 'time': '21:30', 'hours': 2.5})
        self.assertTrue(moved['room_changed'])
        self.assertNotEqual(moved['room'], 'Couple Room (2–4)')
        row = DB.karaoke_room_reservations.find_one({'id': self.mine})
        self.assertEqual((row['reserved_time'], row['duration_hours']), ('2026-10-30T21:30:00', 2.5))
        self.assertFalse(rc.karaoke_overlaps(BID, row['room_id'], row['reserved_time'], row['duration_hours'], exclude_id=self.mine))

    def test_change_with_nothing_free_leaves_booking_unchanged(self):
        for rid, room_id in ((910, 1), (911, 3), (912, 4)):
            ktv_row(rid, '2026-10-31T19:00:00', 4, room_id)
        ktv_row(913, '2026-10-31T19:00:00', 4, 2)
        r = self.call(karaoke, 'karaoke_change_reservation', {'reservation_id': self.mine, 'date': '2026-10-31', 'time': '20:00'})
        self.assertFalse(r['success'])
        self.assertTrue(r['reservation_unchanged'])
        self.assertEqual(DB.karaoke_room_reservations.find_one({'id': self.mine})['reserved_time'], '2026-10-30T20:00:00')

    def test_change_refuses_other_people(self):
        self.refuse(karaoke, 'karaoke_change_reservation', {'reservation_id': 900, 'time': '21:00'})


# ================================================================ cùng luật với màn nhân viên + route công khai
def _app_source():
    with io.open(os.path.join(ROOT, 'app.py'), encoding='utf-8') as fh:
        return fh.read()


def _app_function(name):
    src = _app_source()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    fn.decorator_list = []
    return ast.Module(body=[fn], type_ignores=[])


class SameRulesAsStaffScreens(Base):
    def test_overlap_rule_matches_app_karaoke_reservation_overlaps(self):
        ns = {'db': DB, 'datetime': datetime, 'timedelta': timedelta}
        exec(compile(_app_function('_karaoke_reservation_overlaps'), 'app.py', 'exec'), ns)
        staff = ns['_karaoke_reservation_overlaps']
        ktv_row(1, '2026-10-30T19:00:00', 2, 7)
        ktv_row(2, '2026-10-30T22:00', None, 7)                  # bản ghi cũ thiếu số giờ = 2 giờ
        ktv_row(3, '2026-10-30T12:00:00', 3, 7, status='cancelled')
        ktv_row(4, '2026-10-30T15:00:00', 1, 7, status='arrived')
        ktv_row(5, '2026-10-30T13:00:00', 1, 8)
        cases = 0
        for room_id in (7, 8):
            for h in range(11, 25):
                for m in (0, 30):
                    for dur in (0.5, 1, 2, 3.5):
                        when = f"2026-10-30T{h % 24:02d}:{m:02d}:00" if h < 24 else f"2026-10-31T00:{m:02d}:00"
                        for ex in (None, 1):
                            self.assertEqual(rc.karaoke_overlaps(BID, room_id, when, dur, ex), staff(BID, room_id, when, dur, ex),
                                             (room_id, when, dur, ex))
                            cases += 1
        self.assertGreater(cases, 400)


class PublicRoutes(Base):
    def run_route(self, name, body):
        ns = {'request': types.SimpleNamespace(json=body), 'jsonify': lambda d: d,
              '_public_reservation_check': lambda bid, data: (None, (data, False)), 'datetime': datetime}
        exec(compile(_app_function(name), 'app.py', 'exec'), ns)
        return ns[name](BID)

    def test_table_route_writes_the_same_document_through_the_shared_helper(self):
        out = self.run_route('api_public_reservation_create', {'name': 'Mia', 'phone': '0412 345 678', 'party_size': 3,
                                                               'reserved_time': '2026-10-30T19:00:00', 'note': '  window seat '})
        self.assertTrue(out['success'])
        row = DB.table_reservations.find_one({'id': out['id']})
        self.assertEqual({k: row[k] for k in ('business_id', 'customer_name', 'customer_phone', 'party_size', 'reserved_time',
                                              'table_id', 'note', 'status', 'source')},
                         {'business_id': BID, 'customer_name': 'Mia', 'customer_phone': '0412 345 678', 'party_size': 3,
                          'reserved_time': '2026-10-30T19:00:00', 'table_id': None, 'note': 'window seat',
                          'status': 'pending', 'source': 'web'})
        self.assertNotIn('ai_conversation_id', row)
        empty = self.run_route('api_public_reservation_create', {'name': 'Leo', 'phone': '0499888777', 'party_size': 0,
                                                                 'reserved_time': '2026-10-30T19:00:00', 'note': ''})
        row = DB.table_reservations.find_one({'id': empty['id']})
        self.assertEqual((row['party_size'], row['note']), (1, None))
        missing = self.run_route('api_public_reservation_create', {'name': 'Leo', 'phone': '0499888777'})
        self.assertEqual(missing[1], 400)

    def test_karaoke_route_keeps_duration_rules(self):
        for raw, expect in ((None, 2.0), ('abc', 2.0), (3, 3.0), (20, 12.0), (0.25, 0.5), ('1.5', 1.5)):
            out = self.run_route('api_public_karaoke_reservation_create',
                                 {'name': 'Kai', 'phone': '0412345678', 'party_size': 5, 'reserved_time': '2026-10-30T20:00:00',
                                  'duration_hours': raw, 'note': ''})
            row = DB.karaoke_room_reservations.find_one({'id': out['id']})
            self.assertEqual(row['duration_hours'], expect, raw)
            self.assertEqual((row['room_id'], row['status'], row['source'], row['party_size']), (None, 'pending', 'web', 5))

    def test_routes_call_reservations_core(self):
        src = _app_source()
        for name, helper in (('api_public_reservation_create', 'create_table_reservation'),
                             ('api_public_karaoke_reservation_create', 'create_karaoke_reservation')):
            body = ast.get_source_segment(src, next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name))
            self.assertIn(f'reservations_core.{helper}(', body)
            self.assertNotIn('insert_one', body)


class Settings(Base):
    def test_save_and_load_reservation_settings(self):
        biz('fnb')
        settings(hours=FNB_HOURS, auto_confirm=True, info={'parking': 'Street'})
        r = rc.save_reservation_settings(BID, 'table', {'max_covers_per_slot': 5000, 'slot_minutes': 20, 'max_party_auto': '8',
                                                        'auto_confirm': False, 'unknown': 1})
        self.assertEqual((r['max_covers_per_slot'], r['slot_minutes'], r['max_party_auto'], r['auto_confirm']), (2000, 30, 8, False))
        doc = DB.booking_settings.find_one({'business_id': BID})
        self.assertEqual(doc['hours'], FNB_HOURS)                       # Cài đặt đặt lịch không bị ghi đè
        self.assertEqual(doc['info'], {'parking': 'Street'})
        self.assertNotIn('unknown', doc['table_reservations'])
        k = rc.save_reservation_settings(BID, 'karaoke', {'min_hours': 1, 'hold_minutes': 15})
        self.assertEqual((k['min_hours'], k['max_hours'], k['hold_minutes'], k['auto_confirm']), (1.0, 12.0, 15, True))
        with self.assertRaises(ValueError):
            rc.save_reservation_settings(BID, 'table', {'max_party': 'lots'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
