# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 "lễ tân AI cho cả 9 ngành": lõi + kho gói đặt chỗ.
  1) ai_packs: tự tìm gói, kiểm tra hợp đồng, công tắc tắt gói, tools_for, claim_ready (cờ env / DB), pack_for;
  2) execute_tool_call đi qua pack.execute(name, args, ctx) — ctx đúng hợp đồng (SĐT đã xác minh, mã chat, ngôn ngữ, giờ tiệm);
  3) customer_context: prompt khách hàng CHỈ dữ kiện công khai (tên, địa chỉ, SĐT, giờ, giá theo tiền tiệm, kho câu trả lời);
     không 'salon'/'technician'/'manicure' ngoài Nails/Spa;
  4) kho câu trả lời của chủ (ai_knowledge + API /api/ai/knowledge + trang /ai/knowledge VI/EN);
  5) mã SMS 1 lần cho chat web/Messenger (6 số, 10 phút, 5 lần, giới hạn gửi, chỉ lưu mã băm, không lộ "số này có lịch");
  6) change_service: đổi dịch vụ không huỷ-đặt lại (vừa giờ / không vừa / tranh chỗ / không phải lịch của chat / sai dữ liệu);
  7) nối dây app.py: secure_ai_generate, _inbox_ai_reply, _inbox_sms_inbound, _booking_assistant_facts.

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi DeepSeek/Twilio/Meta:
mongo_client được thay bằng 1 DB giả trong RAM TRƯỚC mọi import; hàm trong app.py lấy nguyên mã nguồn qua ast.

Chạy: python scripts/tests/test_phase2_receptionist_core.py
"""
import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
os.environ.pop('BITPAW_AI_PACKS_OFF', None)
os.environ.pop('BITPAW_AI_SIM_PASSED', None)


# ---------------------------------------------------------------- DB giả trong RAM
def _get(doc, key):
    cur = doc
    for part in str(key).split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


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
            if op == '$regex':
                flags = re.I if 'i' in str(cond.get('$options') or '') else 0
                if not isinstance(v, str) or not re.search(arg, v, flags):
                    return False
            if op in ('$gte', '$gt', '$lt', '$lte'):
                if v is None:
                    return False
                try:
                    if op == '$gte' and not v >= arg or op == '$gt' and not v > arg or \
                            op == '$lt' and not v < arg or op == '$lte' and not v <= arg:
                        return False
                except TypeError:
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
        elif not _match_value(_get(doc, k), cond):
            return False
    return True


class DuplicateKeyError(Exception):
    pass


class _Cursor(list):
    def sort(self, key, direction=1):
        if isinstance(key, list):
            key, direction = key[0]
        return _Cursor(sorted(self, key=lambda d: (d.get(key) is None, d.get(key) if d.get(key) is not None else ''),
                              reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    UNIQUE = {'appointments': ('business_id', 'slot_key')}

    def __init__(self, name, log):
        self.name, self.docs, self.log = name, [], log

    def _check_unique(self, doc, skip=None):
        keys = self.UNIQUE.get(self.name)
        if not keys or any(doc.get(k) in (None, '') for k in keys):
            return
        for d in self.docs:
            if d is not skip and all(d.get(k) == doc.get(k) for k in keys):
                raise DuplicateKeyError(f'E11000 {self.name} {keys}')

    def insert_one(self, doc):
        self.log.append((self.name, 'insert_one'))
        d = dict(doc)
        d.setdefault('_id', len(self.docs) + 1)
        self._check_unique(d)
        self.docs.append(d)
        return types.SimpleNamespace(inserted_id=d['_id'])

    def find(self, flt=None, projection=None):
        return _Cursor(dict(d) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = self.find(flt)
        if sort:
            rows = rows.sort(sort[0][0], sort[0][1])
        return dict(rows[0]) if rows else None

    def count_documents(self, flt=None):
        return len(self.find(flt))

    @staticmethod
    def _apply(d, update):
        for k, v in (update.get('$set') or {}).items():
            d[k] = v
        for k in (update.get('$unset') or {}):
            d.pop(k, None)
        for k, v in (update.get('$inc') or {}).items():
            d[k] = (d.get(k) or 0) + v

    def update_one(self, flt, update, upsert=False):
        self.log.append((self.name, 'update_one'))
        for d in self.docs:
            if _matches(d, flt):
                new = dict(d)
                self._apply(new, update)
                self._check_unique(new, skip=d)
                d.clear()
                d.update(new)
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            d = {k: v for k, v in flt.items() if not str(k).startswith('$') and not isinstance(v, dict)}
            d.update(update.get('$setOnInsert') or {})
            self._apply(d, update)
            d.setdefault('_id', len(self.docs) + 1)
            self.docs.append(d)
        return types.SimpleNamespace(matched_count=0, modified_count=0)

    def update_many(self, flt, update):
        self.log.append((self.name, 'update_many'))
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                n += 1
        return types.SimpleNamespace(matched_count=n, modified_count=n)

    def find_one_and_update(self, flt, update, projection=None, sort=None, upsert=False, return_document=False):
        self.log.append((self.name, 'find_one_and_update'))
        rows = [d for d in self.docs if _matches(d, flt)]
        if sort:
            key, direction = sort[0]
            rows.sort(key=lambda d: d.get(key) or '', reverse=direction == -1)
        if not rows:
            return None
        before = dict(rows[0])
        self._apply(rows[0], update)
        return dict(rows[0]) if return_document else before

    def delete_one(self, flt):
        self.log.append((self.name, 'delete_one'))
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                del self.docs[i]
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)

    def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, flt)]
        return types.SimpleNamespace(deleted_count=before - len(self.docs))

    def aggregate(self, pipeline):
        return iter([])

    def create_index(self, *a, **k):
        return 'ix'


class FakeDB:
    def __init__(self):
        self.__dict__['_c'] = {}
        self.__dict__['writes'] = []

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        if name not in self._c:
            self._c[name] = FakeCollection(name, self.writes)
        return self._c[name]

    def __getitem__(self, name):
        return getattr(self, name)

    def reset(self):
        self._c.clear()
        self.writes.clear()


DB = FakeDB()
_ids = count(5000)
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED',
                                                    load_env_file=lambda *a, **k: None)


class SlotAlreadyBookedError(Exception):
    pass


def _fake_book(business_id, customer_info, staff_id, book_time, service_id=None, note=None, source='web', status=None,
               enforce_rules=None):
    doc = {'id': next(_ids), 'business_id': business_id, 'customer_name': customer_info.get('name'),
           'customer_phone': customer_info.get('phone'), 'service_id': service_id, 'staff_id': staff_id,
           'book_time': book_time, 'status': 'confirmed', 'source': source, 'created_at': datetime.now().isoformat()}
    if staff_id:
        doc['slot_key'] = f"{staff_id}|{book_time}"
    DB.appointments.insert_one(doc)
    return doc


_be = types.ModuleType('booking_engine')
_be.book_appointment = _fake_book
_be.SlotAlreadyBookedError = SlotAlreadyBookedError
sys.modules['booking_engine'] = _be
_ds = types.ModuleType('ai_deepseek_client')
_ds.deepseek_chat_completion = MagicMock(side_effect=AssertionError('DeepSeek must not be called in this test'))
sys.modules['ai_deepseek_client'] = _ds
_vault = types.ModuleType('nurture_channel_tokens')
_vault.encrypt_secret = lambda s: s
_vault.decrypt_secret = lambda s: s
_vault.get_channel_token = lambda *a, **k: None
sys.modules['nurture_channel_tokens'] = _vault
_sp = types.ModuleType('service_packages')
_sp.active_for = MagicMock(return_value=[])
sys.modules['service_packages'] = _sp

TWILIO = {'ready': False, 'language': 'en'}
_msg = types.ModuleType('messaging')   # không gửi SMS / email thật
_msg.get_settings = lambda bid: {'twilio_ready': TWILIO['ready'], 'business_name': 'Rose Nails', 'language': TWILIO['language']}
_msg._twilio_send = MagicMock(return_value='SM_fake')
_msg.is_opted_out = MagicMock(return_value=False)
_msg.queue = MagicMock(return_value=None)
_msg.deliver = MagicMock()
sys.modules['messaging'] = _msg

from flask import Flask, jsonify, request, session  # noqa: E402
import requests  # noqa: E402

import booking_rules  # noqa: E402
import ai_packs  # noqa: E402
import ai_function_tools as T  # noqa: E402
import ai_knowledge  # noqa: E402
import customer_context  # noqa: E402
import inbox_channels  # noqa: E402
from ai_context_engine import AIContextEngine  # noqa: E402
from ai_sales_prompts import compose_booking_assistant_prompt, compose_system_prompt  # noqa: E402
from currency_utils import format_money  # noqa: E402


# ---------------------------------------------------------------- gói THỬ (đúng hợp đồng) + gói hỏng, trong thư mục tạm
PACK_DIR = tempfile.mkdtemp(prefix='bp_packs_')
_TEST_PACK = r'''
"""Gói thử: đặt bàn tối giản theo đúng hợp đồng ai_packs (dùng trong test lõi)."""
from datetime import datetime
import ai_packs
from mongo_client import db, next_mongo_id

INDUSTRIES = ('testfood',)
RESOURCE = 'table'
TOOLS = [
    {'type': 'function', 'function': {'name': 'zz_check_tables', 'description': 'Check free tables.',
                                      'parameters': {'type': 'object', 'properties': {'party_size': {'type': 'integer'}}}}},
    {'type': 'function', 'function': {'name': 'zz_reserve', 'description': 'Reserve a table.',
                                      'parameters': {'type': 'object', 'properties': {
                                          'time': {'type': 'string'}, 'party_size': {'type': 'integer'},
                                          'customer_name': {'type': 'string'}, 'phone': {'type': 'string'}}}}},
    {'type': 'function', 'function': {'name': 'zz_my_reservations', 'description': 'List my reservations.',
                                      'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {'name': 'zz_cancel', 'description': 'Cancel my reservation.',
                                      'parameters': {'type': 'object', 'properties': {'reservation_id': {'type': 'integer'}}}}},
]
MANAGE_TOOLS = {'zz_my_reservations', 'zz_cancel'}
PROMPT_RULES = {'en': 'ZZ-EN-RULE: always ask the party size; never promise a window seat.',
                'vi': 'ZZ-VI-RULE: luôn hỏi số khách; không hứa bàn cạnh cửa sổ.'}
BOOKING_COLLECTIONS = (('zz_reservations', 'customer_phone'),)
CALLS = []


def facts(business_id, lang, now_local):
    return f"ZZ TABLE FACTS lang={lang} aware={now_local is not None and now_local.tzinfo is not None} max party 8"


def execute(name, args, ctx):
    CALLS.append((name, dict(args), dict(ctx)))
    bid = ctx['business_id']
    if name == 'zz_check_tables':
        if int(args.get('party_size') or 0) > 8:
            raise ai_packs.PackError('Groups above 8 are handled by the team (pending + handoff).', 'large_party')
        return {'success': True, 'free': ['19:00', '19:30']}
    if name == 'zz_reserve':
        phone = args.get('phone') or ctx.get('contact_phone')
        if not phone or not args.get('customer_name'):
            raise ai_packs.PackError('Ask for the name and a phone number first.', 'missing_contact')
        party = int(args.get('party_size') or 2)
        status = 'pending' if party > 6 else 'confirmed'
        doc = {'id': next_mongo_id('zz_reservations'), 'business_id': bid, 'customer_phone': phone, 'party_size': party,
               'reserved_time': args.get('time'), 'status': status, 'source': 'ai_bot',
               'ai_conversation_id': ctx.get('customer_id'), 'chat_token_hash': ctx.get('chat_token_hash'),
               'ai_channel': ctx.get('channel')}
        db.zz_reservations.insert_one(dict(doc))
        return {'success': True, 'reservation_id': doc['id'], 'status': status}
    flt = ai_packs.manage_filter(ctx)
    if flt is None:
        raise ai_packs.PackError('Cannot verify this chat.', 'not_verified')
    if name == 'zz_my_reservations':
        rows = db.zz_reservations.find({'business_id': bid, **flt})
        return {'success': True, 'reservations': [{'reservation_id': r['id'], 'status': r['status']} for r in rows]}
    if name == 'zz_cancel':
        doc = db.zz_reservations.find_one({'business_id': bid, 'id': int(args.get('reservation_id') or 0), **flt})
        if not doc:
            raise ai_packs.PackError("That reservation isn't one this chat can change.", 'not_yours')
        db.zz_reservations.update_one({'id': doc['id'], 'business_id': bid}, {'$set': {'status': 'cancelled'}})
        return {'success': True, 'cancelled': True}
    raise ai_packs.PackError('unknown tool')
'''
_BROKEN = {
    'zz_badresource': "INDUSTRIES=('x1',)\nRESOURCE='spaceship'\nTOOLS=[{'type':'function','function':{'name':'x1_go','parameters':{}}}]\n"
                      "def execute(n,a,c): return {}\n",
    'zz_reserved': "INDUSTRIES=('x2',)\nRESOURCE='table'\nTOOLS=[{'type':'function','function':{'name':'ask_team','parameters':{}}}]\n"
                   "def execute(n,a,c): return {}\n",
    'zz_badmanage': "INDUSTRIES=('x3',)\nRESOURCE='table'\nTOOLS=[{'type':'function','function':{'name':'x3_go','parameters':{}}}]\n"
                    "MANAGE_TOOLS={'x3_other'}\ndef execute(n,a,c): return {}\n",
    'zz_noexec': "INDUSTRIES=('x4',)\nRESOURCE='job'\nTOOLS=[{'type':'function','function':{'name':'x4_go','parameters':{}}}]\n",
    'zz_importerror': "import module_that_does_not_exist_anywhere\n",
}
with io.open(os.path.join(PACK_DIR, 'zz_tables.py'), 'w', encoding='utf-8') as _f:
    _f.write(_TEST_PACK)
for _n, _src in _BROKEN.items():
    with io.open(os.path.join(PACK_DIR, _n + '.py'), 'w', encoding='utf-8') as _f:
        _f.write(_src)
ai_packs.__path__.append(PACK_DIR)
ai_packs.reload()


def _zz():
    ai_packs.packs()   # la phat hien (lazy): nap goi neu chua nap
    return sys.modules['ai_packs.zz_tables']


# ---------------------------------------------------------------- hàm của app.py (lấy mã nguồn qua ast, bỏ decorator)
def _read(path):
    with io.open(path, encoding='utf-8') as f:
        return f.read()


APP_SRC = _read(os.path.join(ROOT, 'app.py'))
_TREE = ast.parse(APP_SRC)
_FUNCS = ('secure_ai_generate', '_booking_assistant_facts', '_persist_chat_turn', '_booking_chat_history',
          '_load_recent_chat_history', '_inbox_ai_reply', '_inbox_sms_inbound', '_inbox_ai_throttled', '_inbox_walkin',
          '_paused_holding_reply')
_ASSIGNS = ('_VI_CHARS_RE', '_VI_WORDS_RE', '_CLIENT_NOW_RE')
CALLS = []
SCRIPTED_TOOL = []


def _fake_call_deepseek(messages, temperature, max_tokens, business_id, customer_id, api_key, tools=None):
    """Thay _call_deepseek_with_tools: ghi lại prompt + công cụ; chạy THẬT các tool test đặt sẵn qua execute_tool_call."""
    names = [t['function']['name'] for t in tools or []]
    CALLS.append({'messages': messages, 'tools': names, 'business_id': business_id, 'customer_id': customer_id,
                  'scope': dict(T._CHAT_SCOPE.get() or {})})
    used = []
    for name, args in SCRIPTED_TOOL:
        _id, out = T.execute_tool_call({'id': 'c1', 'function': {'name': name, 'arguments': json.dumps(args)}},
                                       business_id=business_id, customer_id=customer_id, allowed=set(names))
        used.append(json.loads(out))
    return {'choices': [{'message': {'content': 'ok'}}], 'tools_used': used}


NS = {
    'db': DB, 'request': request, 'session': session, 'jsonify': jsonify, 'os': os, 're': re, 'time': time, 'json': json,
    'datetime': datetime, 'timedelta': timedelta, 'requests': requests, 'AIContextEngine': AIContextEngine,
    'compose_booking_assistant_prompt': compose_booking_assistant_prompt, 'compose_system_prompt': compose_system_prompt,
    'classify_objection': MagicMock(return_value=None), 'get_conversation_memory': MagicMock(return_value=''),
    'maybe_distill_memory_async': MagicMock(), 'BOOKING_TOOLS': T.BOOKING_TOOLS, 'SALES_TOOLS': T.SALES_TOOLS,
    '_call_deepseek_with_tools': _fake_call_deepseek, '_log_ai_run': lambda *a, **k: None,
    '_tenant_currency': lambda bid: customer_context.currency_of(bid), 'format_money': format_money,
    'inbox_channels': inbox_channels, 'SAAS_PLANS': {}, 'SAAS_CURRENCIES': {}, '_vi_en': lambda vi, en: en,
}
for node in _TREE.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in _ASSIGNS for t in node.targets):
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'app.py', 'exec'), NS)
for name in _FUNCS:
    node = next(n for n in _TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), f'app.py::{name}', 'exec'), NS)

FLASK = Flask(__name__)
FLASK.secret_key = 'test'
FLASK.add_url_rule('/api/ai/studio/generate', 'gen', NS['secure_ai_generate'], methods=['POST'])

NAIL, SPA, FOOD, QA_SHOP, OTHER_NAIL = 'biz_nail', 'biz_spa', 'biz_food', 'biz_qa', 'biz_nail2'
TOKEN_A, TOKEN_B = 'tokA' * 6, 'tokB' * 6
NOW = datetime(2026, 11, 2, 8, 0)                     # thứ Hai, giờ tiệm
DAY = '2026-11-04'                                   # thứ Tư, 09:00-19:00
PHONE = '+61412345678'
FORM_PHONE = '0412 345 678'                          # khách gõ ở form đặt lịch (cùng số, cách viết khác)


def seed():
    DB.reset()
    booking_rules._CACHE.clear()
    ai_packs._FLAG_CACHE.clear()
    CALLS.clear()
    SCRIPTED_TOOL.clear()
    _zz().CALLS.clear()
    TWILIO.update(ready=False, language='en')
    _msg._twilio_send.reset_mock(return_value=True, side_effect=True)
    _msg._twilio_send.return_value = 'SM_fake'
    _msg.is_opted_out.reset_mock(return_value=True, side_effect=True)
    _msg.is_opted_out.return_value = False
    _sp.active_for.reset_mock(return_value=True, side_effect=True)
    _sp.active_for.return_value = []
    DB.businesses.insert_one({'id': NAIL, 'name': 'Rose Nails', 'industry_code': 'nail', 'currency': 'AUD', 'country': 'AU',
                              'phone': '+61290000001', 'address': '12 King St, Newtown NSW'})
    DB.businesses.insert_one({'id': OTHER_NAIL, 'name': 'Other Nails', 'industry_code': 'nail', 'currency': 'AUD', 'country': 'AU'})
    DB.businesses.insert_one({'id': SPA, 'name': 'Calm Spa', 'industry_code': 'spa', 'currency': 'USD', 'country': 'US'})
    DB.businesses.insert_one({'id': FOOD, 'name': 'Golden Test Kitchen', 'industry_code': 'testfood', 'currency': 'VND',
                              'country': 'VN', 'phone': '0281234567', 'address': '5 Lê Lợi, Q1'})
    DB.businesses.insert_one({'id': QA_SHOP, 'name': 'Corner Office', 'industry_code': 'office', 'currency': 'USD', 'country': 'US'})
    DB.booking_settings.insert_one({'business_id': NAIL, 'hours': {d: ['09:00', '19:00'] for d in booking_rules.DAY_KEYS},
                                    'capacity': 1, 'durations': {'1': 60, '2': 90, '3': 45}, 'slot_minutes': 30,
                                    'info': {'parking': 'Free parking behind the shop'}})
    for bid, items in ((NAIL, [(1, 'Gel Manicure', 45), (2, 'Deluxe Pedicure', 70), (3, 'Polish Change', 20)]),
                       (FOOD, [(7, 'Phở bò', 65000), (8, 'Cơm tấm', 55000)]),
                       (SPA, [(11, 'Swedish Massage', 90)]), (QA_SHOP, [(21, 'Consultation', 150)])):
        for pid, nm, price in items:
            DB.products.insert_one({'id': pid, 'business_id': bid, 'name': nm, 'price': price, 'is_active': 1})
    # dữ liệu RIÊNG không bao giờ được vào prompt khách hàng
    DB.orders.insert_one({'business_id': NAIL, 'total_amount': 98765, 'created_at': datetime.now().isoformat()})
    DB.customers.insert_one({'business_id': NAIL, 'phone': PHONE, 'name': 'Vip Vera', 'tier': 'Diamond', 'total_spent': 54321})
    DB.writes.clear()


class _Base(unittest.TestCase):
    def setUp(self):
        seed()
        self._p = [patch.object(booking_rules, 'local_now', lambda bid: NOW)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        os.environ.pop('BITPAW_AI_PACKS_OFF', None)
        os.environ.pop('BITPAW_AI_SIM_PASSED', None)


def _call(name, args, bid, cid, allowed=None):
    _id, out = T.execute_tool_call({'id': 'x', 'function': {'name': name, 'arguments': json.dumps(args)}},
                                   business_id=bid, customer_id=cid, allowed=allowed)
    return json.loads(out)


def _names(tools):
    return [t['function']['name'] for t in tools]


# ================================================================ (1) kho gói
class RegistryTests(_Base):
    def test_discovery_builtin_and_test_pack(self):
        packs = ai_packs.packs()
        self.assertIn('appointment', packs)
        self.assertTrue(packs['appointment'].builtin)
        self.assertEqual(ai_packs.pack_for('nail').name, 'appointment')
        self.assertEqual(ai_packs.pack_for('nails').name, 'appointment')
        self.assertEqual(ai_packs.pack_for('spa').name, 'appointment')
        self.assertEqual(ai_packs.pack_for('testfood').name, 'zz_tables')
        self.assertEqual(ai_packs.pack_for('testfood').resource, 'table')
        self.assertIsNone(ai_packs.pack_for('unknown_industry'))
        self.assertIsNone(ai_packs.pack_for(None))
        self.assertEqual(ai_packs.pack_for_business(FOOD).name, 'zz_tables')
        self.assertIsNone(ai_packs.pack_for_business(None))
        self.assertIn('change_service', ai_packs.pack_for('nail').tool_names)
        self.assertEqual(ai_packs.pack_for('nail').manage_tools, frozenset(T.APPOINTMENT_MANAGE_TOOLS))

    def test_broken_packs_are_skipped_with_a_reason(self):
        errs = ai_packs.errors()
        for name, needle in (('zz_badresource', 'RESOURCE'), ('zz_reserved', 'reserved'), ('zz_badmanage', 'MANAGE_TOOLS'),
                             ('zz_noexec', 'execute'), ('zz_importerror', 'ModuleNotFoundError')):
            self.assertIn(name, errs)
            self.assertIn(needle, errs[name])
            self.assertNotIn(name, ai_packs.packs())
        for ind in ('x1', 'x2', 'x3', 'x4'):
            self.assertIsNone(ai_packs.pack_for(ind))

    def test_tools_for_pack_industry(self):
        with T.chat_scope(TOKEN_A):
            names = _names(T.customer_tools(FOOD, f'{FOOD}:{PHONE}'))
        self.assertEqual(names, ['zz_check_tables', 'zz_reserve', 'zz_my_reservations', 'zz_cancel', 'ask_team', 'handoff_to_staff'])
        self.assertNotIn('request_booking', names)
        self.assertNotIn('book_appointment', names)
        waiting = _names(T.customer_tools(FOOD, f'{FOOD}:{PHONE}', waiting=True))
        self.assertNotIn('ask_team', waiting)
        self.assertNotIn('handoff_to_staff', waiting)

    def test_verify_tools_only_when_the_shop_can_text_and_chat_has_an_identity(self):
        cid = f'{NAIL}:{PHONE}'
        with T.chat_scope(TOKEN_A):
            self.assertNotIn('send_verification_code', _names(T.customer_tools(NAIL, cid)))
        TWILIO['ready'] = True
        with T.chat_scope(TOKEN_A):
            names = _names(T.customer_tools(NAIL, cid))
        self.assertIn('send_verification_code', names)
        self.assertIn('verify_code', names)
        with T.chat_scope(None):   # widget cũ không có mã trình duyệt: không có gì để gắn mã -> không mời
            self.assertNotIn('send_verification_code', _names(T.customer_tools(NAIL, cid)))
        sms = inbox_channels.record(NAIL, 'sms', PHONE, 'hi', 'customer', phone=PHONE)
        self.assertNotIn('send_verification_code', _names(T.customer_tools(NAIL, sms)))   # SMS: số đã do nhà mạng xác minh

    def test_industry_without_pack_stays_questions_and_handoff(self):
        self.assertEqual(set(_names(T.customer_tools(QA_SHOP))), {'request_booking', 'ask_team', 'handoff_to_staff'})
        self.assertFalse(T.books_in_chat(QA_SHOP))
        self.assertFalse(T.has_booking_pack(QA_SHOP))

    def test_kill_switch(self):
        os.environ['BITPAW_AI_PACKS_OFF'] = 'testfood'
        self.assertIsNone(ai_packs.pack_for('testfood'))
        self.assertEqual(set(_names(T.customer_tools(FOOD))), {'request_booking', 'ask_team', 'handoff_to_staff'})
        os.environ['BITPAW_AI_PACKS_OFF'] = 'zz_tables'   # theo tên gói cũng được
        self.assertIsNone(ai_packs.pack_for('testfood'))
        os.environ.pop('BITPAW_AI_PACKS_OFF')
        self.assertIsNotNone(ai_packs.pack_for('testfood'))

    def test_claim_ready_needs_pack_and_sim_flag_and_nothing_flips_it(self):
        self.assertFalse(ai_packs.claim_ready('testfood'))       # có gói, chưa qua sim
        self.assertFalse(ai_packs.claim_ready('nail'))           # không tự bật cho gói dựng sẵn
        os.environ['BITPAW_AI_SIM_PASSED'] = 'testfood,office'
        self.assertTrue(ai_packs.claim_ready('testfood'))
        self.assertFalse(ai_packs.claim_ready('office'))         # cờ có nhưng KHÔNG có gói -> False
        os.environ.pop('BITPAW_AI_SIM_PASSED')
        DB.system_settings.insert_one({'key': 'ai_sim_passed', 'value': {'testfood': {'passed': True, 'overall': 4.6}}})
        ai_packs._FLAG_CACHE.clear()
        self.assertTrue(ai_packs.claim_ready('testfood'))
        DB.system_settings.update_one({'key': 'ai_sim_passed'}, {'$set': {'value': {'testfood': {'passed': False}}}})
        ai_packs._FLAG_CACHE.clear()
        self.assertFalse(ai_packs.claim_ready('testfood'))
        DB.system_settings.update_one({'key': 'ai_sim_passed'}, {'$set': {'value': ['testfood']}})
        ai_packs._FLAG_CACHE.clear()
        self.assertTrue(ai_packs.claim_ready('testfood'))
        writes = [w for w in DB.writes if w[0] == 'system_settings']
        self.assertEqual(len(writes), 3)   # chỉ 3 lần test tự ghi — ai_packs không bao giờ ghi cờ

    def test_has_booking_pack_auto_on_only_builtin_or_sim_passed(self):
        self.assertTrue(T.has_booking_pack(NAIL))
        self.assertTrue(T.books_in_chat(FOOD))
        self.assertFalse(T.has_booking_pack(FOOD))               # gói mới: đặt được khi chủ tự bật AI, không tự bật mặc định
        self.assertFalse(inbox_channels.ai_auto_reply_on(FOOD, 'messenger'))
        os.environ['BITPAW_AI_SIM_PASSED'] = 'testfood'
        self.assertTrue(T.has_booking_pack(FOOD))

    def test_spa_override_pack_replaces_builtin_for_spa_only(self):
        d = tempfile.mkdtemp(prefix='bp_packs_spa_')
        with io.open(os.path.join(d, 'zz_spa_rooms.py'), 'w', encoding='utf-8') as f:
            f.write("INDUSTRIES=('spa',)\nRESOURCE='appointment'\nTOOLS=[{'type':'function','function':{'name':'spa_rooms_check',"
                    "'parameters':{'type':'object','properties':{}}}}]\ndef execute(n,a,c): return {'success': True}\n")
        ai_packs.__path__.append(d)
        try:
            ai_packs.reload()
            self.assertEqual(ai_packs.pack_for('spa').name, 'zz_spa_rooms')
            self.assertEqual(ai_packs.pack_for('nail').name, 'appointment')
        finally:
            ai_packs.__path__.remove(d)
            shutil.rmtree(d, ignore_errors=True)
            sys.modules.pop('ai_packs.zz_spa_rooms', None)
            ai_packs.reload()
        self.assertEqual(ai_packs.pack_for('spa').name, 'appointment')

    def test_phone_helpers(self):
        self.assertEqual(ai_packs.normalize_phone('0412 345 678', 'AU'), PHONE)
        self.assertEqual(ai_packs.normalize_phone('(555) 123-4567', 'US'), '+15551234567')
        self.assertEqual(ai_packs.normalize_phone('0901234567', 'VN'), '+84901234567')
        self.assertEqual(ai_packs.normalize_phone('12', 'AU'), '')
        v = ai_packs.phone_variants(PHONE, 'AU')
        for spelled in (PHONE, '61412345678', '0412345678', FORM_PHONE):
            self.assertIn(spelled, v)
        self.assertTrue(ai_packs.same_phone('+1 (555) 123-4567', '5551234567', 'US'))
        self.assertTrue(ai_packs.conversation_hash('b:messenger:1').startswith('conv:'))

    def test_default_booking_collections_match_the_public_forms(self):
        # /reserve -> table_reservations.customer_phone, /karaoke/reserve -> karaoke_room_reservations.customer_phone,
        # /hotel/reserve -> hotel_reservations.guest_phone (mã SMS chỉ gửi tới số đã có đặt chỗ ở đúng chỗ đó)
        d = ai_packs.DEFAULT_BOOKING_COLLECTIONS
        self.assertEqual(d['table'], (('table_reservations', 'customer_phone'),))
        self.assertEqual(d['room_hour'], (('karaoke_room_reservations', 'customer_phone'),))
        self.assertEqual(d['room_night'], (('hotel_reservations', 'guest_phone'),))
        hotel = ai_packs.Pack('hoteltest', industries=('hoteltest',), resource='room_night', tools=[
            {'type': 'function', 'function': {'name': 'ht_x', 'parameters': {}}}], execute=lambda *a: {})
        DB.hotel_reservations.insert_one({'business_id': NAIL, 'guest_phone': FORM_PHONE, 'status': 'pending'})
        self.assertTrue(ai_packs.phone_has_bookings(hotel, NAIL, ai_packs.phone_variants(PHONE, 'AU')))
        self.assertFalse(ai_packs.phone_has_bookings(hotel, OTHER_NAIL, ai_packs.phone_variants(PHONE, 'AU')))
        flt = ai_packs.manage_filter({'phone': PHONE, 'country': 'AU', 'chat_token_hash': 'anon:x', 'channel': 'web'},
                                     phone_fields=('guest_phone',))
        self.assertEqual(list(flt['$or'][0]), ['guest_phone'])
        self.assertEqual(len(flt['$or']), 1)                                 # mã 'anon:' không bao giờ là bằng chứng


# ================================================================ (2) điều phối qua pack.execute + ctx
class DispatchTests(_Base):
    def test_web_ctx_matches_the_contract(self):
        cid = f'{FOOD}:{PHONE}'
        DB.bot_customers.insert_one({'id': cid, 'phone': PHONE, 'full_name': f'Khách {PHONE}'})
        with T.chat_scope(TOKEN_A, lang='vi', channel='web'):
            out = _call('zz_check_tables', {'party_size': 4}, FOOD, cid)
        self.assertTrue(out['success'])
        name, args, ctx = _zz().CALLS[-1]
        self.assertEqual((name, args), ('zz_check_tables', {'party_size': 4}))
        self.assertEqual(ctx['business_id'], FOOD)
        self.assertEqual(ctx['customer_id'], cid)
        self.assertEqual(ctx['channel'], 'web')
        self.assertIsNone(ctx['phone'])                      # SĐT tự gõ trên web KHÔNG phải SĐT đã xác minh
        self.assertEqual(ctx['contact_phone'], PHONE)
        self.assertEqual(ctx['chat_token_hash'], hashlib.sha256(TOKEN_A.encode()).hexdigest())
        self.assertEqual(ctx['lang'], 'vi')
        self.assertIsNotNone(ctx['now_local'].tzinfo)
        self.assertEqual(str(ctx['now_local'].tzinfo), 'Asia/Ho_Chi_Minh')
        self.assertIsNone(ctx['customer_name'])              # tên giữ chỗ 'Khách +61...' không phải tên thật
        self.assertEqual(ctx['country'], 'VN')

    def test_channel_ctx_messenger_and_sms(self):
        m = inbox_channels.record(FOOD, 'messenger', 'psid1', 'hi', 'customer', name='Lan Anh')
        _call('zz_check_tables', {}, FOOD, m)
        ctx = _zz().CALLS[-1][2]
        self.assertEqual(ctx['channel'], 'messenger')
        self.assertEqual(ctx['chat_token_hash'], ai_packs.conversation_hash(m))
        self.assertIsNone(ctx['phone'])
        self.assertEqual(ctx['customer_name'], 'Lan Anh')
        s = inbox_channels.record(FOOD, 'sms', '+84901234567', 'hi', 'customer', phone='+84901234567')
        _call('zz_check_tables', {}, FOOD, s)
        ctx = _zz().CALLS[-1][2]
        self.assertEqual((ctx['channel'], ctx['phone']), ('sms', '+84901234567'))   # số do nhà mạng xác nhận

    def test_no_token_web_gets_anon_hash_never_none(self):
        with T.chat_scope(None):
            _call('zz_check_tables', {}, FOOD, None)
        th = _zz().CALLS[-1][2]['chat_token_hash']
        self.assertTrue(th and th.startswith('anon:'))

    def test_reserve_records_ai_tags_and_status(self):
        cid = f'{FOOD}:{PHONE}'
        with T.chat_scope(TOKEN_A):
            ok = _call('zz_reserve', {'time': f'{DAY}T19:00', 'party_size': 4, 'customer_name': 'An'}, FOOD, cid)
            big = _call('zz_reserve', {'time': f'{DAY}T20:00', 'party_size': 7, 'customer_name': 'An'}, FOOD, cid)
        self.assertEqual(ok['status'], 'confirmed')
        self.assertEqual(big['status'], 'pending')
        row = DB.zz_reservations.find_one({'id': ok['reservation_id']})
        self.assertEqual((row['source'], row['ai_conversation_id'], row['ai_channel']), ('ai_bot', cid, 'web'))
        self.assertEqual(row['chat_token_hash'], T.chat_token_hash(TOKEN_A))
        self.assertEqual(DB.appointments.count_documents({}), 0)

    def test_pack_error_is_relayed_honestly(self):
        with T.chat_scope(TOKEN_A):
            out = _call('zz_reserve', {'time': f'{DAY}T19:00'}, FOOD, None)
            big = _call('zz_check_tables', {'party_size': 12}, FOOD, None)
        self.assertEqual(out, {'success': False, 'refused': True, 'error': 'Ask for the name and a phone number first.',
                               'reason': 'missing_contact'})
        self.assertEqual(big['reason'], 'large_party')

    def test_manage_tool_without_any_proof_is_refused_before_the_pack_runs(self):
        cid = f'{FOOD}:{PHONE}'
        with T.chat_scope(None):
            out = _call('zz_my_reservations', {}, FOOD, cid)
        self.assertEqual(out['reason'], 'not_verified')
        self.assertEqual(_zz().CALLS, [])

    def test_ownership_other_browser_cannot_cancel(self):
        cid = f'{FOOD}:{PHONE}'
        with T.chat_scope(TOKEN_A):
            rid = _call('zz_reserve', {'time': f'{DAY}T19:00', 'customer_name': 'An'}, FOOD, cid)['reservation_id']
        with T.chat_scope(TOKEN_B):   # cùng SĐT, trình duyệt khác
            self.assertEqual(_call('zz_my_reservations', {}, FOOD, cid)['reservations'], [])
            out = _call('zz_cancel', {'reservation_id': rid}, FOOD, cid)
        self.assertEqual(out['reason'], 'not_yours')
        self.assertEqual(DB.zz_reservations.find_one({'id': rid})['status'], 'confirmed')
        with T.chat_scope(TOKEN_A):
            self.assertTrue(_call('zz_cancel', {'reservation_id': rid}, FOOD, cid)['cancelled'])

    def test_tools_of_other_industries_and_unknown_tools_are_refused(self):
        cid = f'{FOOD}:{PHONE}'
        DB.bot_customers.insert_one({'id': cid, 'phone': PHONE})
        out = _call('book_appointment', {'service_id': '7', 'appointment_time': f'{DAY}T10:00'}, FOOD, cid)
        self.assertFalse(out['success'])
        self.assertEqual(DB.appointments.count_documents({}), 0)
        out = _call('zz_reserve', {'time': f'{DAY}T19:00', 'customer_name': 'X', 'phone': PHONE}, QA_SHOP, f'{QA_SHOP}:{PHONE}')
        self.assertIn('no online booking', out['error'])
        self.assertEqual(DB.zz_reservations.count_documents({}), 0)
        self.assertFalse(_call('drop_database', {}, FOOD, cid)['success'])
        # allowlist của persona thắng mọi thứ
        self.assertFalse(_call('zz_check_tables', {}, FOOD, cid, allowed={'ask_team'})['success'])
        self.assertFalse(_call('zz_check_tables', '[1,2]', FOOD, cid)['success'])   # tham số không phải object

    def test_nail_tools_still_run_through_the_builtin_pack(self):
        cid = f'{NAIL}:{PHONE}'
        DB.bot_customers.insert_one({'id': cid, 'phone': PHONE})
        with T.chat_scope(TOKEN_A):
            out = _call('book_appointment', {'service_id': '1', 'appointment_time': f'{DAY}T10:00:00', 'customer_name': 'Mia'},
                        NAIL, cid)
        self.assertTrue(out['success'], out)
        appt = DB.appointments.find_one({'id': out['appointment_id']})
        self.assertEqual((appt['source'], appt['ai_conversation_id']), ('ai_bot', cid))
        self.assertEqual(appt['chat_token_hash'], T.chat_token_hash(TOKEN_A))


# ================================================================ (3) prompt khách hàng: chỉ dữ kiện công khai
BANNED_OUTSIDE_NAIL_SPA = ('salon', 'technician', 'manicure')


class CustomerContextTests(_Base):
    def test_public_facts_only_with_address_hours_currency_and_knowledge(self):
        ai_knowledge.create(NAIL, {'kind': 'faq', 'topic': 'deposit', 'question': 'Do I need a deposit?',
                                   'answer': 'No deposit for bookings under 3 people.'})
        ai_knowledge.create(NAIL, {'kind': 'policy', 'topic': 'kids', 'answer': 'Kids welcome with an adult.', 'active': False})
        facts = NS['_booking_assistant_facts'](NAIL)
        self.assertIn('service_id 1: Gel Manicure — $45.00, 60 min', facts)
        self.assertIn('Address: 12 King St, Newtown NSW', facts)      # từ hồ sơ tiệm khi trang Cài đặt đặt lịch chưa ghi
        self.assertIn('Parking: Free parking behind the shop', facts)
        self.assertIn('Phone: +61290000001', facts)
        self.assertIn('OPENING HOURS: Mon 09:00-19:00', facts)
        self.assertIn('No deposit for bookings under 3 people.', facts)
        self.assertNotIn('Kids welcome', facts)                        # mục đang tắt
        self.assertIn("OWNER'S ANSWERS", facts)
        for leak in ('98765', '98,765', 'Diamond', '54321', 'Vip Vera', 'BitPaw', 'SaaS'):
            self.assertNotIn(leak, facts)

    def test_food_pack_facts_use_pack_facts_shop_currency_and_tz(self):
        facts = NS['_booking_assistant_facts'](FOOD, lang='vi')
        self.assertIn('ZZ TABLE FACTS lang=vi aware=True', facts)
        self.assertIn('Phở bò — 65.000đ', facts)
        self.assertIn('Asia/Ho_Chi_Minh', facts)
        self.assertIn('Address: 5 Lê Lợi, Q1', facts)
        self.assertNotIn('BOOKABLE SERVICES', facts)
        self.assertNotIn('information only — nothing here can be booked', facts)

    def test_qa_facts_unchanged_for_industries_without_pack(self):
        facts = NS['_booking_assistant_facts'](QA_SHOP)
        self.assertIn('information only', facts)
        self.assertIn('Consultation — $150.00', facts)
        self.assertNotIn('OPENING HOURS', facts)     # chủ chưa nhập giờ -> không bịa 9-19

    def test_context_engine_customer_audience_is_identity_only(self):
        out = AIContextEngine.build_context_prompt(NAIL, 'nail', customer_phone=PHONE, include_private_data=True, audience='customer')
        self.assertEqual(out['business_name'], 'Rose Nails')
        self.assertEqual(out['prompt'], 'BUSINESS: Rose Nails — a nail salon.')
        DB.businesses.update_one({'id': FOOD}, {'$set': {'name': 'owner@example.com'}})
        booking_rules._CACHE.clear()
        self.assertIsNone(AIContextEngine.build_context_prompt(FOOD, None, audience='customer')['business_name'])

    def test_vocabulary_outside_nail_and_spa(self):
        fake = {}
        for ind in ('fnb', 'karaoke', 'hotel', 'retail', 'technical', 'production', 'office'):
            bid = f'biz_{ind}'
            DB.businesses.insert_one({'id': bid, 'name': f'Shop {ind}', 'industry_code': ind, 'currency': 'USD', 'country': 'US'})
            DB.products.insert_one({'id': 900, 'business_id': bid, 'name': 'House item', 'price': 10, 'is_active': 1})
            fake[ind] = ai_packs.Pack(f'fake_{ind}', industries=(ind,), resource='table',
                                      tools=[{'type': 'function', 'function': {'name': f'{ind}_check', 'parameters': {}}}],
                                      manage_tools=(), prompt_rules={'en': f'{ind} rules', 'vi': f'luật {ind}'},
                                      facts=lambda b, l, n: 'pack facts')
        booking_rules._CACHE.clear()
        for ind, pack in fake.items():
            bid = f'biz_{ind}'
            ctx = AIContextEngine.build_context_prompt(bid, None, include_private_data=False, audience='customer')
            for mode in ('pack', 'qa'):
                p = pack if mode == 'pack' else None
                prompt = compose_booking_assistant_prompt(
                    ctx['prompt'], ctx['business_name'], booking_facts=NS['_booking_assistant_facts'](bid, booking=p or False),
                    booking_enabled=p is not None, pack=p, lang='en', can_verify=True, industry=ind)
                for banned in BANNED_OUTSIDE_NAIL_SPA:
                    self.assertNotIn(banned, prompt.lower(), f'{ind}/{mode}: {banned}')
                self.assertNotIn('BitPaw Software', prompt)
            self.assertIn(f'{ind} rules', compose_booking_assistant_prompt('', 'X', pack=pack, lang='en'))
            self.assertIn(f'luật {ind}', compose_booking_assistant_prompt('', 'X', pack=pack, lang='vi'))

    def test_spa_prompt_uses_therapist_and_nail_prompt_keeps_change_service(self):
        nail = ai_packs.pack_for('nail')
        spa_prompt = compose_booking_assistant_prompt('', 'Calm Spa', pack=nail, industry='spa')
        self.assertNotIn('technician', spa_prompt.lower())
        self.assertNotIn('salon', spa_prompt.lower())
        self.assertIn('therapist', spa_prompt)
        nail_prompt = compose_booking_assistant_prompt('', 'Rose Nails', pack=nail, industry='nail')
        self.assertIn('change_service', nail_prompt)
        self.assertIn('never cancel and rebook', nail_prompt)
        self.assertIn('YOU ARE BOOKING FOR: Rose Nails', nail_prompt)

    def test_verify_rule_only_when_shop_can_text(self):
        pack = ai_packs.pack_for('testfood')
        self.assertNotIn('send_verification_code', compose_booking_assistant_prompt('', 'X', pack=pack))
        self.assertIn('send_verification_code', compose_booking_assistant_prompt('', 'X', pack=pack, can_verify=True))
        qa = compose_booking_assistant_prompt('', 'X', booking_enabled=False, can_verify=True)
        self.assertNotIn('send_verification_code', qa)
        self.assertIn('CANNOT BOOK', qa)


# ================================================================ (4) kho câu trả lời của chủ tiệm
class KnowledgeTests(_Base):
    def test_validation(self):
        with self.assertRaises(ai_knowledge.KnowledgeError):
            ai_knowledge.create(NAIL, {'kind': 'faq', 'answer': 'x'})                  # hỏi-đáp thiếu câu hỏi
        with self.assertRaises(ai_knowledge.KnowledgeError):
            ai_knowledge.create(NAIL, {'kind': 'faq', 'question': 'Parking?', 'answer': '   '})
        with self.assertRaises(ai_knowledge.KnowledgeError):
            ai_knowledge.create(NAIL, {'kind': 'menu', 'question': 'q', 'answer': 'a'})
        with self.assertRaises(ai_knowledge.KnowledgeError):
            ai_knowledge.create(None, {'kind': 'policy', 'answer': 'a'})
        e = ai_knowledge.create(NAIL, {'kind': 'policy', 'topic': 'weird', 'answer': 'Line1\x00\x07\r\n\n\n\nLine2' + 'x' * 2000})
        self.assertEqual(e['topic'], 'other')
        self.assertNotIn('\x00', e['answer'])
        self.assertIn('Line1\n\nLine2', e['answer'])
        self.assertEqual(len(e['answer']), ai_knowledge.MAX_ANSWER)
        self.assertTrue(e['active'])

    def test_crud_isolated_per_business_and_prompt_block(self):
        e = ai_knowledge.create(NAIL, {'kind': 'faq', 'topic': 'parking', 'question': 'Parking?', 'answer': 'Behind the shop.'})
        with self.assertRaises(LookupError):
            ai_knowledge.update(OTHER_NAIL, e['id'], {'answer': 'hijack'})
        with self.assertRaises(LookupError):
            ai_knowledge.delete(OTHER_NAIL, e['id'])
        with self.assertRaises(LookupError):
            ai_knowledge.update(NAIL, '../../etc', {'answer': 'x'})
        self.assertEqual(ai_knowledge.list_entries(OTHER_NAIL), [])
        self.assertEqual(ai_knowledge.prompt_block(OTHER_NAIL), '')
        block = ai_knowledge.prompt_block(NAIL)
        self.assertIn('Parking — Q: Parking? A: Behind the shop.', block)
        self.assertIn('never add details', block)
        ai_knowledge.update(NAIL, e['id'], {'active': False})
        self.assertEqual(ai_knowledge.prompt_block(NAIL), '')
        ai_knowledge.update(NAIL, e['id'], {'active': True, 'answer': 'Free, behind the shop.'})
        self.assertIn('Free, behind the shop.', ai_knowledge.prompt_block(NAIL))
        ai_knowledge.delete(NAIL, e['id'])
        self.assertEqual(ai_knowledge.list_entries(NAIL), [])

    def test_max_entries_and_prompt_size_cap(self):
        for i in range(ai_knowledge.MAX_ENTRIES):
            DB.ai_knowledge.insert_one({'id': f'{i:016x}', 'business_id': NAIL, 'kind': 'policy', 'topic': 'other',
                                        'answer': 'y' * 300, 'active': True, 'created_at': f'2026-10-01T00:{i:02d}'})
        with self.assertRaises(ai_knowledge.KnowledgeError):
            ai_knowledge.create(NAIL, {'kind': 'policy', 'answer': 'one more'})
        block = ai_knowledge.prompt_block(NAIL)
        self.assertLess(len(block), ai_knowledge.PROMPT_MAX_CHARS + 600)
        self.assertIn('use ask_team', block)

    def test_unanswered_questions_come_from_ask_team_notes(self):
        cid = f'{NAIL}:{PHONE}'
        DB.bot_customers.insert_one({'id': cid, 'phone': PHONE})
        T.ask_team(NAIL, cid, question='Do you do kids nails?')
        T.ask_team(NAIL, cid, question='Do you do kids nails?')
        gaps = ai_knowledge.unanswered_questions(NAIL)
        self.assertEqual([g['question'] for g in gaps], ['Do you do kids nails?'])
        self.assertEqual(ai_knowledge.unanswered_questions(OTHER_NAIL), [])


def _knowledge_app():
    """Flask nhỏ với blueprint thật; decorator của app.py thay bằng bản tối giản cùng hành vi (đăng nhập + vai trò)."""
    from functools import wraps
    from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

    def login_required(f):
        @wraps(f)
        def w(*a, **k):
            if 'user_id' not in session:
                return jsonify({'success': False, 'message': 'login'}), 401
            return f(*a, **k)
        return w

    def role_required(*roles):
        def deco(f):
            @wraps(f)
            def w(*a, **k):
                if session.get('role', 'staff') not in roles:
                    return jsonify({'success': False, 'message': 'forbidden'}), 403
                return f(*a, **k)
            return w
        return deco

    limiter = types.SimpleNamespace(limit=lambda *a, **k: (lambda f: f))
    sys.modules['app'] = types.SimpleNamespace(login_required=login_required, role_required=role_required, limiter=limiter)
    sys.modules.pop('ai_knowledge_bp', None)
    import ai_knowledge_bp
    app = Flask('kb', template_folder=os.path.join(ROOT, 'templates'))
    app.secret_key = 'kb'
    app.jinja_loader = ChoiceLoader([DictLoader({'components/app_sidebar.html': '<nav>sidebar</nav>'}),
                                     FileSystemLoader(os.path.join(ROOT, 'templates'))])
    app.register_blueprint(ai_knowledge_bp.ai_knowledge_bp)
    LANG = {'v': 'en'}

    @app.context_processor
    def _lang():
        return {'default_lang': LANG['v']}
    return app, LANG


class KnowledgeApiTests(_Base):
    def setUp(self):
        super().setUp()
        self.app, self.lang = _knowledge_app()
        self.c = self.app.test_client()

    def _login(self, bid=NAIL, role='admin'):
        with self.c.session_transaction() as s:
            s.clear()
            s.update({'user_id': bid, 'business_id': bid, 'role': role})

    def test_auth_and_roles(self):
        self.assertEqual(self.c.get('/api/ai/knowledge').status_code, 401)
        self._login(role='staff')
        self.assertEqual(self.c.get('/api/ai/knowledge').status_code, 403)
        self.assertEqual(self.c.post('/api/ai/knowledge', json={'kind': 'policy', 'answer': 'x'}).status_code, 403)
        self.assertEqual(DB.ai_knowledge.count_documents({}), 0)

    def test_crud_api(self):
        self._login()
        r = self.c.post('/api/ai/knowledge', json={'kind': 'faq', 'topic': 'parking', 'question': 'Parking?', 'answer': 'Behind.'})
        j = r.get_json()
        self.assertEqual(r.status_code, 200, j)
        eid = j['entry']['id']
        self.assertIn('Behind.', j['preview'])
        self.assertEqual([t['key'] for t in j['topics']][:2], ['parking', 'deposit'])
        self.assertIn(['Address', '12 King St, Newtown NSW'], j['info'])
        bad = self.c.post('/api/ai/knowledge', json={'kind': 'faq', 'answer': 'no question'})
        self.assertEqual(bad.status_code, 400)
        self.assertIn(' / ', bad.get_json()['message'])          # EN / VI
        r = self.c.put(f'/api/ai/knowledge/{eid}', json={'active': False})
        self.assertEqual(r.get_json()['preview'], '')
        self._login(bid=OTHER_NAIL)                                # tiệm khác không sửa / xoá được
        self.assertEqual(self.c.put(f'/api/ai/knowledge/{eid}', json={'answer': 'hijack'}).status_code, 404)
        self.assertEqual(self.c.delete(f'/api/ai/knowledge/{eid}').status_code, 404)
        self.assertEqual(self.c.get('/api/ai/knowledge').get_json()['entries'], [])
        self._login()
        self.assertEqual(self.c.delete(f'/api/ai/knowledge/{eid}').status_code, 200)
        self.assertEqual(DB.ai_knowledge.count_documents({}), 0)

    def test_page_renders_in_both_languages_and_script_parses(self):
        self._login()
        for lang, needles in (('vi', ('Kiến thức cho trợ lý AI', 'AI dùng trang này thế nào', 'AI đọc gì')),
                              ('en', ('AI knowledge base', 'How the AI uses this page', 'What the AI reads'))):
            self.lang['v'] = lang
            r = self.c.get('/ai/knowledge')
            html = r.get_data(as_text=True)
            self.assertEqual(r.status_code, 200)
            for n in needles:
                self.assertIn(n, html)
            self.assertIn(f'const VI = {"true" if lang == "vi" else "false"};', html)
            script = re.findall(r'<script>([\s.\S]*?)</script>', html)[-1]
            node = shutil.which('node')
            if node:
                path = os.path.join(PACK_DIR, f'kb_{lang}.js')
                with io.open(path, 'w', encoding='utf-8') as f:
                    f.write(script)
                res = subprocess.run([node, '--check', path], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, res.stderr)
        self._login(role='staff')
        self.assertEqual(self.c.get('/ai/knowledge').status_code, 403)


# ================================================================ (5) mã SMS 1 lần
class VerificationTests(_Base):
    def setUp(self):
        super().setUp()
        TWILIO['ready'] = True
        self.cid = f'{NAIL}:{PHONE}'
        DB.bot_customers.insert_one({'id': self.cid, 'phone': PHONE, 'business_id': NAIL})
        # lịch đặt qua FORM (SĐT gõ kiểu khác) — không phải của chat nào
        DB.appointments.insert_one({'id': 1, 'business_id': NAIL, 'customer_phone': FORM_PHONE, 'service_id': 1,
                                    'book_time': f'{DAY}T10:00', 'status': 'confirmed', 'source': 'web'})

    def _sent_code(self):
        body = _msg._twilio_send.call_args[0][3]
        return re.search(r'\b(\d{6})\b', body).group(1)

    def test_without_twilio_phase0_refusal_stays(self):
        TWILIO['ready'] = False
        with T.chat_scope(TOKEN_A):
            out = _call('my_appointments', {}, NAIL, self.cid)
            self.assertIn('+61290000001', out['tell_customer'])
            self.assertNotIn('can_verify_by_sms', out)
            ref = _call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)
        self.assertEqual(ref['reason'], 'verification_unavailable')
        _msg._twilio_send.assert_not_called()

    def test_full_flow_form_booking_becomes_manageable(self):
        with T.chat_scope(TOKEN_A):
            listed = _call('my_appointments', {}, NAIL, self.cid)
            self.assertEqual(listed['upcoming'], [])
            self.assertTrue(listed['can_verify_by_sms'])
            self.assertIn('6-digit code', listed['tell_customer'])
            self.assertEqual(_call('cancel_appointment', {'appointment_id': 1}, NAIL, self.cid)['reason'], 'not_verified')
            sent = _call('send_verification_code', {'phone': '0412345678'}, NAIL, self.cid)
            self.assertTrue(sent['success'])
            self.assertEqual(sent['phone'], '•••678')
            _msg._twilio_send.assert_called_once()
            self.assertEqual(_msg._twilio_send.call_args[0][2], PHONE)
            self.assertTrue(_msg._twilio_send.call_args[0][3].startswith('Rose Nails: your verification code is '))
            code = self._sent_code()
            rec = DB.ai_chat_verifications.find_one({})
            self.assertNotIn(code, json.dumps(rec))                       # chỉ lưu mã băm
            self.assertEqual(rec['conv_key'], 'web:' + T.chat_token_hash(TOKEN_A))
            ok = _call('verify_code', {'code': f' {code[:3]} {code[3:]} '}, NAIL, self.cid)
            self.assertTrue(ok['verified'], ok)
            listed = _call('my_appointments', {}, NAIL, self.cid)
            self.assertEqual([a['appointment_id'] for a in listed['upcoming']], [1])
            self.assertNotIn('can_verify_by_sms', listed)
            self.assertIn('verified with the SMS code', listed['scope'])     # không còn "chỉ lịch đặt trong chat này"
            self.assertNotIn('tell_customer', listed)
            self.assertTrue(_call('cancel_appointment', {'appointment_id': 1}, NAIL, self.cid)['success'])
        self.assertEqual(DB.appointments.find_one({'id': 1})['status'], 'cancelled')
        with T.chat_scope(TOKEN_B):   # trình duyệt khác vẫn chưa xác minh
            self.assertEqual(_call('my_appointments', {}, NAIL, self.cid)['upcoming'], [])

    def test_result_never_reveals_whether_a_number_has_bookings(self):
        with T.chat_scope(TOKEN_A):
            with_booking = _call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)
        with T.chat_scope(TOKEN_B):
            without = _call('send_verification_code', {'phone': '0499 000 111'}, NAIL, self.cid)
        self.assertEqual(_msg._twilio_send.call_count, 1)                 # số lạ: không tốn SMS, không làm phiền
        self.assertEqual(sorted(with_booking), sorted(without))
        self.assertEqual(with_booking['tell_customer'].replace('678', '111'), without['tell_customer'])
        with T.chat_scope(TOKEN_B):   # đoán mã cho số không có lịch: luôn sai, vẫn trừ lượt
            self.assertEqual(_call('verify_code', {'code': '000000'}, NAIL, self.cid)['reason'], 'wrong_code')

    def test_wrong_codes_lock_after_five_tries_atomically(self):
        with T.chat_scope(TOKEN_A):
            _call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)
            code = self._sent_code()
            wrong = '%06d' % ((int(code) + 1) % 10 ** 6)
            lefts = [_call('verify_code', {'code': wrong}, NAIL, self.cid).get('tries_left') for _ in range(5)]
            self.assertEqual(lefts, [4, 3, 2, 1, 0])
            late = _call('verify_code', {'code': code}, NAIL, self.cid)
        self.assertEqual(late['reason'], 'no_active_code')
        self.assertEqual(DB.ai_chat_verifications.find_one({})['status'], 'locked')

    def test_expired_code_and_bad_input(self):
        with T.chat_scope(TOKEN_A):
            _call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)
            code = self._sent_code()
            DB.ai_chat_verifications.update_many({}, {'$set': {'expires_at': '2000-01-01T00:00:00+00:00'}})
            self.assertEqual(_call('verify_code', {'code': code}, NAIL, self.cid)['reason'], 'no_active_code')
            self.assertIn('6 digits', _call('verify_code', {'code': '12'}, NAIL, self.cid)['error'])
            self.assertIn('full phone number', _call('send_verification_code', {'phone': '12ab'}, NAIL, self.cid)['error'])

    def test_send_rate_limits(self):
        with T.chat_scope(TOKEN_A):
            outs = [_call('send_verification_code', {'phone': PHONE}, NAIL, self.cid) for _ in range(4)]
        self.assertEqual([o.get('reason') for o in outs], [None, None, None, 'rate_limited'])
        self.assertEqual(_msg._twilio_send.call_count, 3)
        with T.chat_scope('tokC' * 6):   # trình duyệt mới, cùng SĐT: giới hạn theo SĐT vẫn chặn
            self.assertEqual(_call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)['reason'], 'rate_limited')
        self.assertEqual(DB.ai_chat_verifications.count_documents({'status': 'sent'}), 1)   # mã cũ bị thay

    def test_new_code_replaces_old_and_verification_expires(self):
        with T.chat_scope(TOKEN_A):
            _call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)
            first = self._sent_code()
            _call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)
            second = self._sent_code()
            if first != second:
                self.assertEqual(_call('verify_code', {'code': first}, NAIL, self.cid)['reason'], 'wrong_code')
            self.assertTrue(_call('verify_code', {'code': second}, NAIL, self.cid)['verified'])
        DB.ai_chat_verifications.update_many({'status': 'verified'}, {'$set': {'valid_until': '2000-01-01T00:00:00+00:00'}})
        with T.chat_scope(TOKEN_A):
            self.assertEqual(_call('cancel_appointment', {'appointment_id': 1}, NAIL, self.cid)['reason'], 'not_verified')

    def test_opted_out_and_twilio_failure(self):
        _msg.is_opted_out.return_value = True
        with T.chat_scope(TOKEN_A):
            out = _call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)
        self.assertTrue(out['success'])
        _msg._twilio_send.assert_not_called()
        _msg.is_opted_out.return_value = False
        _msg._twilio_send.side_effect = RuntimeError('Twilio 401')
        with T.chat_scope(TOKEN_B):
            out = _call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)
        self.assertEqual(out['reason'], 'sms_failed')
        self.assertIn('+61290000001', out['tell_customer'])

    def test_code_text_never_prints_an_owner_email_as_the_shop_name(self):
        DB.businesses.update_one({'id': NAIL}, {'$set': {'name': 'owner@example.com'}})
        booking_rules._CACHE.clear()
        real = {'twilio_ready': True, 'business_name': 'owner@example.com', 'language': 'vi'}   # messaging thật lấy businesses.name
        with patch.object(_msg, 'get_settings', lambda bid: dict(real)), T.chat_scope(TOKEN_A, lang='vi'):
            self.assertTrue(_call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)['success'])
        body = _msg._twilio_send.call_args[0][3]
        self.assertNotIn('@', body)
        self.assertTrue(body.startswith('Lịch đặt của bạn: mã xác minh của bạn là '), body)

    def test_web_without_token_cannot_verify(self):
        with T.chat_scope(None):
            self.assertEqual(_call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)['reason'],
                             'verification_unavailable')
        _msg._twilio_send.assert_not_called()

    def test_messenger_verification_unlocks_packages_and_pack_hint(self):
        m = inbox_channels.record(NAIL, 'messenger', 'psid9', 'hi', 'customer')
        DB.bot_customers.update_one({'id': m}, {'$set': {'phone': '0400 000 000'}})
        self.assertEqual(_call('my_packages', {}, NAIL, m)['reason'], 'not_verified')
        _sp.active_for.side_effect = lambda bid, p: ([{'name': '10 gels', 'sessions_left': 4, 'sessions_total': 10}]
                                                     if p == FORM_PHONE else [])
        _call('send_verification_code', {'phone': PHONE}, NAIL, m)
        self.assertTrue(_call('verify_code', {'code': self._sent_code()}, NAIL, m)['verified'])
        self.assertEqual(DB.ai_chat_verifications.find_one({'status': 'verified'})['conv_key'], f'conv:{m}')
        pk = _call('my_packages', {}, NAIL, m)
        self.assertEqual(pk['packages'][0]['sessions_left'], 4)
        self.assertEqual([a['appointment_id'] for a in _call('my_appointments', {}, NAIL, m)['upcoming']], [1])
        # gói không dựng sẵn: kết quả thiếu lịch -> gợi ý mã SMS (chưa xác minh) ; đã xác minh -> ctx.phone có số
        f = inbox_channels.record(FOOD, 'messenger', 'psid10', 'hi', 'customer')
        out = _call('zz_my_reservations', {}, FOOD, f)
        self.assertTrue(out['can_verify_by_sms'])
        self.assertIn('send_verification_code', out['verify_hint'])

    def test_sms_reply_with_the_code_is_not_given_to_the_ai(self):
        with T.chat_scope(TOKEN_A):
            _call('send_verification_code', {'phone': PHONE}, NAIL, self.cid)
        code = self._sent_code()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test'}):
            reply = NS['_inbox_sms_inbound'](NAIL, PHONE, code)
        self.assertIn('type this code in the chat', reply)
        self.assertEqual(CALLS, [])
        contents = [m['content'] for m in DB.bot_messages.find({'customer_id': f'{NAIL}:sms:{PHONE}'})]
        self.assertIn(T.HIDDEN_CODE_TEXT, contents)
        self.assertFalse(any(code in c for c in contents))
        # 6 số bình thường từ người không có mã đang chờ -> AI vẫn xử lý như mọi tin
        self.assertIsNone(T.sms_code_reply(NAIL, '+61499999999', '123456'))


# ================================================================ (6) change_service
class ChangeServiceTests(_Base):
    def setUp(self):
        super().setUp()
        self.cid = f'{NAIL}:{PHONE}'
        DB.bot_customers.insert_one({'id': self.cid, 'phone': PHONE, 'business_id': NAIL})
        th = T.chat_token_hash(TOKEN_A)
        DB.appointments.insert_one({'id': 10, 'business_id': NAIL, 'customer_phone': PHONE, 'service_id': 1, 'staff_id': None,
                                    'book_time': f'{DAY}T10:00', 'status': 'confirmed', 'source': 'ai_bot',
                                    'ai_conversation_id': self.cid, 'chat_token_hash': th})
        # khách khác lúc 11:00 (sức chứa 1)
        DB.appointments.insert_one({'id': 11, 'business_id': NAIL, 'customer_phone': '+61400000002', 'service_id': 1,
                                    'book_time': f'{DAY}T11:00', 'status': 'confirmed', 'source': 'web'})

    def _change(self, token=TOKEN_A, **args):
        with T.chat_scope(token):
            return _call('change_service', {'appointment_id': 10, **args}, NAIL, self.cid)

    def test_happy_path_keeps_the_time(self):
        out = self._change(service_id='3')                 # 45 phút: vừa 10:00-10:45
        self.assertTrue(out['success'], out)
        self.assertEqual((out['new_service'], out['old_service'], out['time'], out['time_changed']),
                         ('Polish Change', 'Gel Manicure', f'{DAY}T10:00', False))
        self.assertEqual(out['price'], '$20.00')            # tiền của tiệm (AUD)
        self.assertEqual(out['status'], 'confirmed')
        a = DB.appointments.find_one({'id': 10})
        self.assertEqual((a['service_id'], a['service_changed_from'], a['book_time']), (3, 1, f'{DAY}T10:00'))
        self.assertEqual(DB.appointments.count_documents({'business_id': NAIL}), 2)   # không huỷ - đặt lại
        note = DB.bot_messages.find_one({'customer_id': self.cid, 'sender_type': 'system'})
        self.assertIn('Polish Change', note['content'])

    def test_capacity_conflict_changes_nothing_and_offers_times(self):
        out = self._change(service_id='2')                 # 90 phút: 10:00-11:30 đè lịch 11:00 (sức chứa 1)
        self.assertFalse(out['success'])
        self.assertEqual(out['reason'], 'fully_booked')
        self.assertIn('Do NOT cancel', out['note'])
        self.assertTrue(out['other_times_same_day'])
        self.assertNotIn('10:00', out['other_times_same_day'])
        a = DB.appointments.find_one({'id': 10})
        self.assertEqual((a['service_id'], a['book_time'], a['status']), (1, f'{DAY}T10:00', 'confirmed'))
        out = self._change(service_id='2', new_time=f'{DAY}T13:00:00')   # khách chọn giờ khác
        self.assertTrue(out['success'], out)
        self.assertTrue(out['time_changed'])
        a = DB.appointments.find_one({'id': 10})
        self.assertEqual((a['service_id'], a['book_time'], a['rescheduled_from']), (2, f'{DAY}T13:00', f'{DAY}T10:00'))

    def test_atomic_slot_race_with_a_staff_member(self):
        DB.appointments.update_one({'id': 10}, {'$set': {'staff_id': 'S1', 'slot_key': f'S1|{DAY}T10:00'}})
        DB.appointments.insert_one({'id': 12, 'business_id': NAIL, 'customer_phone': '+61400000003', 'service_id': 1,
                                    'staff_id': 'S1', 'slot_key': f'S1|{DAY}T15:00', 'book_time': f'{DAY}T15:00',
                                    'status': 'confirmed'})
        # người khác giữ 15:00 của thợ S1 ngay sau bước kiểm tra -> khoá (business_id, slot_key) chặn khi ghi
        with patch.object(booking_rules, 'check_slot', lambda *a, **k: True):
            out = self._change(service_id='3', new_time=f'{DAY}T15:00')
        self.assertEqual(out['reason'], 'staff_busy')
        a = DB.appointments.find_one({'id': 10})
        self.assertEqual((a['service_id'], a['book_time'], a['slot_key']), (1, f'{DAY}T10:00', f'S1|{DAY}T10:00'))

    def test_pending_status_is_reported_not_confirmed(self):
        DB.appointments.update_one({'id': 10}, {'$set': {'status': 'pending'}})
        out = self._change(service_id='3')
        self.assertEqual(out['status'], 'pending')

    def test_ownership_refusals(self):
        self.assertEqual(self._change(token=TOKEN_B, service_id='3')['reason'], 'not_verified')
        self.assertEqual(self._change(token=None, service_id='3')['reason'], 'not_verified')
        with T.chat_scope(TOKEN_A):
            other = _call('change_service', {'appointment_id': 11, 'service_id': '3'}, NAIL, self.cid)
        self.assertEqual(other['reason'], 'not_verified')
        self.assertEqual(DB.appointments.find_one({'id': 11})['service_id'], 1)
        self.assertEqual(DB.appointments.find_one({'id': 10})['service_id'], 1)

    def test_bad_input(self):
        self.assertIn('appointment_id', _call_scoped(self.cid, {'appointment_id': 'abc', 'service_id': '3'})['error'])
        self.assertIn('service_id', _call_scoped(self.cid, {'appointment_id': 10, 'service_id': ''})['error'])
        self.assertIn('Không tìm thấy dịch vụ', _call_scoped(self.cid, {'appointment_id': 10, 'service_id': '999'})['error'])
        self.assertIn('ISO 8601', _call_scoped(self.cid, {'appointment_id': 10, 'service_id': '3', 'new_time': 'tomorrow'})['error'])
        self.assertTrue(_call_scoped(self.cid, {'appointment_id': 10, 'service_id': '1'})['unchanged'])
        DB.appointments.update_one({'id': 10}, {'$set': {'status': 'cancelled'}})
        self.assertEqual(_call_scoped(self.cid, {'appointment_id': 10, 'service_id': '3'})['reason'], 'cancelled')

    def test_change_service_is_not_offered_outside_appointment_industries(self):
        self.assertNotIn('change_service', _names(T.customer_tools(FOOD)))
        self.assertNotIn('change_service', _names(T.customer_tools(QA_SHOP)))


def _call_scoped(cid, args):
    with T.chat_scope(TOKEN_A):
        return _call('change_service', args, NAIL, cid)


# ================================================================ (7) nối dây app.py
class WiringTests(_Base):
    def _post(self, body):
        c = FLASK.test_client()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test'}):
            return c.post('/api/ai/studio/generate', json=body)

    def test_web_chat_for_a_pack_industry(self):
        SCRIPTED_TOOL.append(('zz_reserve', {'time': f'{DAY}T19:00', 'party_size': 2, 'customer_name': 'An'}))
        r = self._post({'business_id': FOOD, 'context': 'customer_booking', 'customer_phone': '0901234567',
                        'customer_message': 'cho em đặt bàn 2 người tối mai nhé', 'chat_token': TOKEN_A})
        self.assertEqual(r.status_code, 200)
        call = CALLS[-1]
        self.assertEqual(call['tools'], ['zz_check_tables', 'zz_reserve', 'zz_my_reservations', 'zz_cancel', 'ask_team',
                                         'handoff_to_staff'])
        prompt = call['messages'][0]['content']
        self.assertIn('ZZ-VI-RULE', prompt)                      # luật của gói theo ngôn ngữ khách
        self.assertIn('ZZ TABLE FACTS lang=vi', prompt)
        self.assertIn('YOU ARE BOOKING FOR: Golden Test Kitchen', prompt)
        self.assertIn('BUSINESS: Golden Test Kitchen', prompt)
        self.assertIn('reply in Vietnamese', prompt)
        for banned in BANNED_OUTSIDE_NAIL_SPA + ('BitPaw Software', 'SaaS'):
            self.assertNotIn(banned.lower(), prompt.lower())
        self.assertEqual(call['scope']['lang'], 'vi')
        row = DB.zz_reservations.find_one({})
        self.assertEqual(row['chat_token_hash'], T.chat_token_hash(TOKEN_A))
        self.assertEqual(row['ai_conversation_id'], f'{FOOD}:0901234567')
        self.assertIsNone(T._CHAT_SCOPE.get())

    def test_web_chat_nail_offers_verification_when_twilio_is_connected(self):
        TWILIO['ready'] = True
        self._post({'business_id': NAIL, 'context': 'customer_booking', 'customer_phone': PHONE,
                    'customer_message': 'can I move my booking?', 'chat_token': TOKEN_A})
        call = CALLS[-1]
        for t in ('book_appointment', 'change_service', 'send_verification_code', 'verify_code'):
            self.assertIn(t, call['tools'])
        prompt = call['messages'][0]['content']
        self.assertIn('CHECKING IT', prompt)
        self.assertIn('service_id 1: Gel Manicure — $45.00, 60 min', prompt)
        self.assertIn('MORE BOOKING RULES', prompt)
        for leak in ('Diamond', '54321', '98765', 'Vip Vera'):
            self.assertNotIn(leak, prompt)
        self._post({'business_id': NAIL, 'context': 'customer_booking', 'customer_phone': PHONE,
                    'customer_message': 'hi'})   # widget cũ không mã: không mời mã SMS
        self.assertNotIn('send_verification_code', CALLS[-1]['tools'])
        self.assertNotIn('CHECKING IT', CALLS[-1]['messages'][0]['content'])

    def test_web_chat_without_pack_is_qa(self):
        self._post({'business_id': QA_SHOP, 'context': 'customer_booking', 'customer_phone': '+15550001111',
                    'customer_message': 'can I book a meeting?', 'chat_token': TOKEN_A})
        self.assertEqual(set(CALLS[-1]['tools']), {'request_booking', 'ask_team', 'handoff_to_staff'})
        self.assertIn('CANNOT BOOK', CALLS[-1]['messages'][0]['content'])

    def test_inbox_messenger_for_pack_industry(self):
        cid = inbox_channels.record(FOOD, 'messenger', 'psid3', 'table for 4 friday 7pm', 'customer')
        SCRIPTED_TOOL.append(('zz_check_tables', {'party_size': 4}))
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test'}):
            reply, failed = NS['_inbox_ai_reply'](FOOD, cid, 'table for 4 friday 7pm')
        self.assertEqual((reply, failed), ('ok', False))
        call = CALLS[-1]
        self.assertIn('zz_reserve', call['tools'])
        self.assertEqual(call['scope']['channel'], 'messenger')
        self.assertEqual(call['scope']['lang'], 'en')
        prompt = call['messages'][0]['content']
        self.assertIn('ZZ-EN-RULE', prompt)
        self.assertIn('CHANNEL: this conversation is on', prompt)
        self.assertIn('ask for it before booking', prompt)          # chưa có SĐT
        ctx = _zz().CALLS[-1][2]
        self.assertEqual((ctx['channel'], ctx['chat_token_hash']), ('messenger', ai_packs.conversation_hash(cid)))
        self.assertEqual(DB.appointments.count_documents({}), 0)
        self.assertIsNone(T._CHAT_SCOPE.get())

    def test_inbox_waiting_for_team_has_no_second_handoff(self):
        cid = inbox_channels.record(FOOD, 'messenger', 'psid4', 'hello?', 'customer')
        DB.bot_customers.update_one({'id': cid}, {'$set': {'ai_paused': True, 'handoff_by_ai': True, 'handoff_reason': 'complaint',
                                                           'handoff_at': datetime.now().isoformat()}})
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test'}):
            NS['_inbox_ai_reply'](FOOD, cid, 'hello?')
        self.assertNotIn('handoff_to_staff', CALLS[-1]['tools'])
        self.assertIn('zz_reserve', CALLS[-1]['tools'])

    def test_copilot_reply_facts_signature_still_works(self):
        facts = NS['_booking_assistant_facts'](NAIL, '2026-11-02T08:00')
        self.assertIn('BOOKABLE SERVICES', facts)
        self.assertIn('2026-11-02T08:00', facts)


def tearDownModule():
    shutil.rmtree(PACK_DIR, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=1)
