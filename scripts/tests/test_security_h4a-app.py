# -*- coding: utf-8 -*-
"""Test OFFLINE — security h4a "app":
  1) /api/ai/studio/generate: every anonymous call is metered. Booking chats (context=customer_booking) need a REAL shop whose
     plan has the AI inbox (otherwise no model call), and have their own daily caps per IP and per shop; sales chats keep
     the global cap; anonymous history is capped (turn count + size) and the booking prompt is cut.
  2) HR reads (/api/hr/chamcong, .../month_summary, /api/stream/payroll, /api/leave_requests, /api/expense_requests,
     /api/staff/<id>/income_today, /api/staff): owner/admin see the whole shop; a staff account sees only its OWN rows, the
     employee being the staff profile whose email is the account's sign-in email (server side), never a ?ma_nv= param.
  3) /api/portal/upload (anonymous chat photos) has its own per-shop byte quota and never counts against the shop's own
     media cap used by /api/storage/upload (staff check-in / sign-off photos).
  4) /api/backup/restore restores business_mode only when it is one of the industries and allowed by the activation code's
     industry lock; otherwise the current industry is kept (and no other field of the backed-up row is written).
  5) Automated messaging (messaging.pump / produce_* / deliver, birthday + loyalty from app.py) checks at create AND send
     time that the shop's current plan has 'messaging'; transactional messages (owner alerts, on-my-way, tests) still go.
  6) register() stores businesses.license_industry from the activation code ('all' for shared codes, whose dropdown value
     must be a real industry); /setup locks to it (shared code = free choice, old profiles fall back to industry_code).
  7) _ensure_primary_membership (called on every login / OAuth login) only gives the shop OWNER a primary branch row; a
     staff account no longer gets a "primary branch" of its own id, and a stale one cannot be switched into.
  8) templates/dashboard.html: leave notes (chamcong.ghi_chu, may hold AI/customer text) are escaped in the calendar title
     attribute; templates/index.html: the Fast Check-in comment matches the code (signed-in only, lookup scoped to the shop).

KHÔNG chạy Flask server, KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi
DeepSeek/Twilio/email: mongo_client được thay bằng DB giả trong RAM TRƯỚC mọi import; hàm của app.py lấy mã nguồn qua ast.
H4A_APP_SRC=<file> (+ H4A_MODULE_DIR=<thư mục có messaging.py>) chạy cùng bộ test trên 1 bản app.py / messaging.py khác
(vd bản trước khi vá, để thấy test đỏ).

Chạy: python scripts/tests/test_security_h4a-app.py
"""
import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
if os.environ.get('H4A_MODULE_DIR'):            # thư mục chứa messaging.py khác (vd bản trước khi vá)
    sys.path.insert(0, os.environ['H4A_MODULE_DIR'])

from bson import ObjectId  # noqa: E402
from bson.errors import InvalidId  # noqa: E402
from gridfs.errors import NoFile  # noqa: E402


# ---------------------------------------------------------------- DB giả trong RAM (toán tử / projection như Mongo)
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


def _project(doc, projection):
    d = dict(doc)
    if not projection:
        return d
    inc = {k for k, v in projection.items() if v and k != '_id'}
    if inc:
        out = {k: d[k] for k in inc if k in d}
        if projection.get('_id', 1) and '_id' in d:
            out['_id'] = d['_id']
        return out
    for k, v in projection.items():
        if not v:
            d.pop(k, None)
    return d


class _Cursor(list):
    def sort(self, key, direction=1):
        if isinstance(key, list):
            key, direction = key[0]
        return _Cursor(sorted(self, key=lambda d: (d.get(key) is None, str(d.get(key) or '')), reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs = name, []

    def insert_one(self, doc):
        doc.setdefault('_id', ObjectId())
        self.docs.append(dict(doc))
        return types.SimpleNamespace(inserted_id=doc['_id'])

    def insert_many(self, docs):
        for d in docs:
            self.insert_one(d)

    def find(self, flt=None, projection=None, sort=None, **kw):
        rows = _Cursor(_project(d, projection) for d in self.docs if _matches(d, flt or {}))
        return rows.sort(*sort[0]) if sort else rows

    def find_one(self, flt=None, projection=None, sort=None, **kw):
        rows = self.find(flt, projection or kw.get('projection'), sort=sort)
        return rows[0] if rows else None

    def count_documents(self, flt=None):
        return sum(1 for d in self.docs if _matches(d, flt or {}))

    @staticmethod
    def _apply(d, update):
        before = dict(d)
        for k, v in (update.get('$set') or {}).items():
            d[k] = v
        for k in (update.get('$unset') or {}):
            d.pop(k, None)
        for k, v in (update.get('$inc') or {}).items():
            d[k] = (d.get(k) or 0) + v
        return d != before

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                changed = self._apply(d, update)
                return types.SimpleNamespace(matched_count=1, modified_count=int(changed), upserted_id=None)
        if upsert:
            d = {k: v for k, v in flt.items() if not str(k).startswith('$') and not isinstance(v, dict)}
            d.update(update.get('$setOnInsert') or {})
            self._apply(d, update)
            d.setdefault('_id', ObjectId())
            self.docs.append(d)
            return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=d['_id'])
        return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                n += 1
        return types.SimpleNamespace(matched_count=n, modified_count=n)

    def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                del self.docs[i]
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)

    def delete_many(self, flt):
        keep = [d for d in self.docs if not _matches(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs[:] = keep
        return types.SimpleNamespace(deleted_count=n)

    def create_index(self, *a, **k):
        return 'idx'

    def aggregate(self, pipeline):
        rows = [dict(d) for d in self.docs]
        for stage in pipeline:
            if '$match' in stage:
                rows = [d for d in rows if _matches(d, stage['$match'])]
            elif '$group' in stage:
                spec = stage['$group']
                g = {'_id': None}
                for field, acc in spec.items():
                    if field != '_id':
                        src = acc['$sum']
                        g[field] = sum((src if isinstance(src, (int, float)) else (d.get(src[1:]) or 0)) for d in rows)
                rows = [g] if rows else []
        return iter(rows)


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
_ids = count(1000)


class FakeGridFS:
    """media_fs giả: file doc vào DB['media.files'] (đếm/tổng dung lượng như GridFS thật), bytes giữ trong RAM."""
    def __init__(self, coll='media.files'):
        self.coll, self.blobs = coll, {}

    def put(self, data, **kw):
        oid = ObjectId()
        doc = {k: v for k, v in kw.items() if k != 'content_type'}
        doc.update({'_id': oid, 'length': len(data), 'contentType': kw.get('content_type')})
        DB[self.coll].insert_one(doc)
        self.blobs[oid] = bytes(data)
        return oid

    def find_one(self, flt):
        doc = DB[self.coll].find_one(flt)
        if not doc:
            return None
        blob = self.blobs.get(doc['_id'], b'')
        return types.SimpleNamespace(read=lambda: blob, **{k: v for k, v in doc.items() if k != '_id'})


MEDIA_FS = FakeGridFS('media.files')
BACKUP_FS = FakeGridFS('backups.files')

# stub TRƯỚC mọi import có thể kéo mongo_client thật / gửi tin thật
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED')
_vault = types.ModuleType('nurture_channel_tokens')
_vault.encrypt_secret = lambda s: s
_vault.decrypt_secret = lambda s: s
_vault.get_channel_token = lambda bid, ch: None
_vault.save_channel_token = lambda *a, **k: None
sys.modules['nurture_channel_tokens'] = _vault
_mail = types.ModuleType('email_service')


class _NoEmail:
    def __init__(self, *a, **k):
        raise AssertionError('no real email in offline tests')


_mail.EmailService = _NoEmail
sys.modules['email_service'] = _mail
sys.modules['ai_deepseek_client'] = types.SimpleNamespace(
    deepseek_chat_completion=lambda *a, **k: (_ for _ in ()).throw(AssertionError('no DeepSeek in offline tests')))


def _no_network(*a, **kw):
    raise AssertionError('network disabled in offline tests')


patch('requests.sessions.Session.request', _no_network).start()

from flask import Flask, jsonify, redirect, request, session, url_for, Response, flash  # noqa: E402
from werkzeug.utils import secure_filename  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402
import requests  # noqa: E402
import hmac  # noqa: E402
import hashlib  # noqa: E402
import uuid  # noqa: E402

import plans  # noqa: E402
import ai_gateway  # noqa: E402
import messaging  # noqa: E402

# module con mà secure_ai_generate import bên trong hàm (stub: không gọi DeepSeek/DB thật)
_ft = types.ModuleType('ai_function_tools')
_ft.chat_token_hash = lambda tok: None
_ft.has_booking_pack = lambda bid: False
_ft.QA_TOOLS = []


@contextmanager
def _chat_scope(tok):
    yield


_ft.chat_scope = _chat_scope
_ft.reply_expectation = lambda *a: ''
_ft._alert_owner = lambda *a, **k: None
sys.modules['ai_function_tools'] = _ft
_sp = types.ModuleType('ai_sales_prompts')
_sp.bitpaw_facts = lambda *a, **k: ''
_sp.WAITING_FOR_TEAM = '{reason}{expectation}'
sys.modules['ai_sales_prompts'] = _sp


# ---------------------------------------------------------------- hàm của app.py (lấy mã nguồn qua ast, bỏ decorator)
def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


APP_PATH = os.environ.get('H4A_APP_SRC') or os.path.join(ROOT, 'app.py')
with io.open(APP_PATH, encoding='utf-8') as _fh:
    APP_SRC = _fh.read()
TREE = ast.parse(APP_SRC)
_ASSIGNS = ('_HR_MANAGER_ROLES', 'ALLOWED_MEDIA_EXTENSIONS', '_STORAGE_UPLOAD_KINDS', '_STORAGE_UPLOAD_MAX_BYTES',
            '_PORTAL_UPLOAD_MAX_BYTES', '_PORTAL_UPLOADS_PER_CONVERSATION_DAY', '_PORTAL_UPLOADS_PER_SHOP_DAY',
            '_LEGACY_MEDIA_SHOP_CAP_BYTES', 'SUPERADMIN_ROOT_EMAIL', '_PRIMARY_BRANCH_DEFAULT_NAME', 'BACKUP_TABLES')
_FUNCS = (
    # 1. chat AI công khai
    'secure_ai_generate', '_booking_chat_history', '_load_recent_chat_history',
    # 2. dữ liệu nhân sự theo tài khoản
    '_session_employee_code', '_hr_scope_ma_nv', '_hr_denied', 'api_hr_chamcong_list', 'api_hr_chamcong_month_summary',
    '_month_ngay_cham_list', 'api_leave_requests_list', 'api_expense_requests_list', 'stream_payroll', '_sse_tenant_match',
    'api_staff_income_today', 'api_staff_list',
    # 3. ảnh chat khách / ảnh của tiệm
    '_allowed_media_file', '_sniff_image_type', '_legacy_media_usage_bytes', '_portal_chat_sig', '_resolve_portal_customer',
    'api_storage_upload', 'api_portal_upload',
    # 4. khôi phục bản sao lưu
    'restore_backup', '_license_locked_industry', '_session_business_id', 'setup',
    # 5. tin tự động
    '_queue_loyalty_notification',
    # 6. đăng ký
    'register', '_email_query', '_is_authorized_superadmin_email',
    # 7. chi nhánh chính
    '_ensure_primary_membership', '_get_owned_business_ids', 'api_switch_branch', '_multi_location_denied',
)
INDUSTRIES = ('retail', 'fnb', 'spa', 'nail', 'karaoke', 'hotel', 'production', 'technical', 'office')

CALLS = []          # lệnh "gọi DeepSeek" (giả)
SSE = []            # (watchable, match_stage) mà stream_payroll mở


def _fake_call_deepseek(messages, temperature, max_tokens, business_id, customer_id, api_key, tools=None):
    CALLS.append({'messages': messages, 'max_tokens': max_tokens, 'business_id': business_id})
    return {'choices': [{'message': {'content': 'ok'}}], 'tools_used': []}


def _render(name, **kw):
    from flask import get_flashed_messages
    return f'TPL:{name}|' + '|'.join(get_flashed_messages())


NS = {
    'db': DB, 'request': request, 'session': session, 'jsonify': jsonify, 'url_for': url_for, 'redirect': redirect,
    'Response': Response, 'flash': flash, 'render_template': _render,
    'os': os, 're': re, 'time': time, 'json': json, 'hmac': hmac, 'hashlib': hashlib, 'uuid': uuid,
    'datetime': datetime, 'timedelta': timedelta, 'timezone': timezone, 'requests': requests,
    'ObjectId': ObjectId, 'InvalidId': InvalidId, 'NoFile': NoFile, 'secure_filename': secure_filename,
    'media_fs': MEDIA_FS, 'fs': BACKUP_FS, 'app': types.SimpleNamespace(secret_key='unit-test-secret'),
    'plans': plans, 'INDUSTRY_CONFIG': {k: {} for k in INDUSTRIES}, 'next_mongo_id': lambda c: next(_ids),
    '_vi_en': lambda vi, en: en, 'resolve_lang': lambda req: 'en', '_is_superadmin': lambda: False,
    '_wants_json': lambda: True, 'render_message_page': lambda status, *a, **k: (f'message page {status}', status),
    '_log_audit': lambda *a, **k: None,
    # 1
    'AIContextEngine': types.SimpleNamespace(build_context_prompt=lambda *a, **k: {'prompt': 'TENANT', 'business_name': 'Shop'}),
    'compose_booking_assistant_prompt': lambda *a, **k: 'SYSTEM', 'compose_system_prompt': lambda *a, **k: 'SYSTEM',
    'classify_objection': MagicMock(return_value=None), 'get_conversation_memory': MagicMock(return_value=''),
    'maybe_distill_memory_async': MagicMock(), 'BOOKING_TOOLS': [], 'SALES_TOOLS': [],
    '_call_deepseek_with_tools': _fake_call_deepseek, '_log_ai_run': lambda *a, **k: None,
    '_tenant_currency': lambda bid: 'USD', 'SAAS_PLANS': {}, 'SAAS_CURRENCIES': {},
    '_persist_chat_turn': MagicMock(), '_booking_assistant_facts': lambda *a, **k: '',
    '_paused_holding_reply': lambda *a, **k: 'paused',
    # 2
    '_sse_change_signal': lambda watchable, match, payload_colls=(): SSE.append((watchable, match)) or 'SSE',
    'tenant_day_bounds': lambda bid: ('2026-10-31T00:00:00', '2026-11-01T00:00:00'), '_REVENUE_ORDER_FILTER': {},
    '_calendar_lib': __import__('calendar'),
    # 6
    'csrf': types.SimpleNamespace(protect=lambda: None),
    'security_shield': types.SimpleNamespace(code_attempts_blocked=lambda ip: False, record_code_failure=lambda *a: None),
    '_get_real_client_ip': lambda: request.remote_addr or '127.0.0.1',
    'generate_password_hash': lambda pw: generate_password_hash(pw, method='pbkdf2:sha256:1000'),
    '_send_welcome_email': MagicMock(),
    'messaging': messaging,
}
MISSING = []
for node in TREE.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in _ASSIGNS for t in node.targets):
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'app.py', 'exec'), NS)
FUNC_NODES = {n.name: n for n in TREE.body if isinstance(n, ast.FunctionDef)}
DECORATORS = {name: [ast.unparse(d) for d in n.decorator_list] for name, n in FUNC_NODES.items()}
for name in _FUNCS:
    node = FUNC_NODES.get(name)
    if node is None:
        MISSING.append(name)
        continue
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), f'app.py::{name}', 'exec'), NS)

FLASK = Flask(__name__)
FLASK.secret_key = 'unit-test-secret'
FLASK.add_url_rule('/api/storage/file/<file_id>', 'api_storage_file', lambda file_id: '')
FLASK.add_url_rule('/api/public/storage/file/<file_id>', 'api_public_storage_file', lambda file_id: '')
for _ep in ('login', 'index', 'plan_page', 'setup'):
    FLASK.add_url_rule('/' + _ep, _ep, lambda: _ep)

OLD = '2026-10-01T09:00:00'      # trước ngày ra mắt gói (plans.GRANDFATHER_BEFORE)
NEW = '2026-10-29T09:00:00'      # sau ngày ra mắt gói
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 64


def _need(*names):
    missing = [n for n in names if n not in NS]
    if missing:
        raise AssertionError(f'app.py is missing {missing} (fix not applied)')


@contextmanager
def _ctx(path='/', method='GET', user=None, role=None, bid=None, email=None, ip='198.51.100.7', **kw):
    kw.setdefault('environ_base', {})['REMOTE_ADDR'] = ip
    with FLASK.test_request_context(path, method=method, **kw):
        if user:
            session['user_id'] = user
            session['business_id'] = bid or user
            if role:
                session['role'] = role
            if email:
                session['user_email'] = email
        yield


def _call(fn, *a, **k):
    out = NS[fn](*a, **k)
    if isinstance(out, tuple):
        resp, status = out[0], out[1]
    else:
        resp, status = out, getattr(out, 'status_code', 200)
    if isinstance(resp, str):
        return status, resp
    try:
        return status, resp.get_json()
    except Exception:
        return status, resp


def _reset():
    DB.reset()
    plans._PLAN_CACHE.clear()
    CALLS.clear()
    SSE.clear()
    NS['_persist_chat_turn'].reset_mock()


def _owner(bid, plan=None, created_at=NEW, industry='nail', **extra):
    """Chủ tiệm như register(): users + businesses."""
    DB.users.insert_one({'id': bid, 'email': f'{bid}@x.test', 'business_id': bid, 'role': 'admin', 'created_at': created_at})
    doc = {'id': bid, 'name': bid, 'industry_code': industry, 'created_at': created_at, **extra}
    if plan:
        doc['plan'] = plan
    DB.businesses.insert_one(doc)


# ================================================================ 1. chat AI công khai: mọi lượt ẩn danh đều được đếm
class BookingChatMeterTests(unittest.TestCase):
    ENV = ('BOOKING_CHAT_DAILY_CAP_PER_IP', 'BOOKING_CHAT_DAILY_CAP_PER_SHOP', 'SALES_BOT_DAILY_CAP')

    def setUp(self):
        _reset()
        os.environ['DEEPSEEK_API_KEY'] = 'unit-test-key'   # không có lệnh gọi thật: _call_deepseek_with_tools là bản giả
        os.environ.pop('BITPAW_DESKTOP_MODE', None)
        for k in self.ENV:
            os.environ.pop(k, None)
        _owner('pro-nails', plan='pro')
        _owner('ess-nails', plan='essential')
        _owner('old-salon', created_at=OLD)                                     # tiệm cũ chưa có gói = Empire
        DB.users.insert_one({'id': 'legacy-own', 'email': 'l@x.test', 'created_at': OLD})   # chủ tiệm cũ chưa có hồ sơ
        DB.businesses.insert_one({'id': 'pro-branch', 'parent_business_id': 'pro-nails', 'created_at': NEW})
        DB.business_memberships.insert_one({'owner_user_id': 'old-salon', 'business_id': 'old-branch', 'is_primary': False})
        DB.users.insert_one({'id': 'staff-u', 'email': 's@x.test', 'business_id': 'pro-nails', 'role': 'staff', 'created_at': NEW})

    def tearDown(self):
        for k in self.ENV:
            os.environ.pop(k, None)

    def _book(self, bid, msg='Can I book a gel manicure tomorrow?', ip='198.51.100.7', user=None, user_bid=None, **extra):
        body = {'context': 'customer_booking', 'customer_message': msg, 'userPrompt': msg, **extra}
        if bid is not None:
            body['business_id'] = bid
        with _ctx('/api/ai/studio/generate', method='POST', ip=ip, user=user, role='admin' if user else None, bid=user_bid,
                  json=body):
            return _call('secure_ai_generate')

    def _sales(self, prompt='how much is BitPaw?', ip='198.51.100.7', **extra):
        with _ctx('/api/ai/studio/generate', method='POST', ip=ip, json={'userPrompt': prompt, 'industry': 'nail', **extra}):
            return _call('secure_ai_generate')

    def test_unknown_or_missing_shop_never_reaches_the_model(self):
        for bid in (None, '', '   ', 'made-up-shop', 'staff-u', 'x' * 300):
            status, body = self._book(bid)
            self.assertIn(status, (400, 404), (bid, body))
            self.assertTrue(body.get('ai_unavailable'), (bid, body))
        status, _ = self._book({'$ne': None})
        self.assertEqual(status, 400)
        self.assertEqual(CALLS, [], 'no DeepSeek call for a shop that does not exist')
        NS['_persist_chat_turn'].assert_not_called()

    def test_real_shops_still_chat(self):
        for bid in ('pro-nails', 'old-salon', 'legacy-own', 'pro-branch', 'old-branch'):
            status, body = self._book(bid)
            self.assertEqual(status, 200, (bid, body))
            self.assertNotIn('ai_unavailable', body, bid)
        self.assertEqual([c['business_id'] for c in CALLS], ['pro-nails', 'old-salon', 'legacy-own', 'pro-branch', 'old-branch'])

    def test_plan_without_ai_inbox_gets_the_no_ai_reply(self):
        status, body = self._book('ess-nails')
        self.assertTrue(body.get('ai_unavailable'))
        self.assertEqual(body.get('reason'), 'plan')
        self.assertEqual(CALLS, [])

    def test_per_shop_daily_cap(self):
        os.environ['BOOKING_CHAT_DAILY_CAP_PER_SHOP'] = '3'
        for i in range(3):
            self.assertNotIn('ai_unavailable', self._book('pro-nails', ip=f'203.0.113.{i}')[1])
        status, body = self._book('pro-nails', ip='203.0.113.99')
        self.assertTrue(body.get('ai_unavailable'))
        self.assertEqual(body.get('reason'), 'daily_limit')
        self.assertEqual(len(CALLS), 3, 'no DeepSeek call once the shop is over its daily cap')
        self.assertNotIn('ai_unavailable', self._book('old-salon', ip='203.0.113.98')[1], 'other shops are not affected')

    def test_per_ip_daily_cap_counts_every_shop(self):
        os.environ['BOOKING_CHAT_DAILY_CAP_PER_IP'] = '2'
        self.assertNotIn('ai_unavailable', self._book('pro-nails', ip='192.0.2.1')[1])
        self.assertNotIn('ai_unavailable', self._book('old-salon', ip='192.0.2.1')[1])
        status, body = self._book('pro-branch', ip='192.0.2.1')       # đổi tiệm không né được trần theo IP
        self.assertEqual(body.get('reason'), 'daily_limit')
        self.assertEqual(len(CALLS), 2)
        self.assertNotIn('ai_unavailable', self._book('pro-branch', ip='192.0.2.2')[1])

    def test_ip_refusals_do_not_use_up_the_shop_cap(self):
        os.environ['BOOKING_CHAT_DAILY_CAP_PER_IP'] = '1'
        os.environ['BOOKING_CHAT_DAILY_CAP_PER_SHOP'] = '2'
        self._book('pro-nails', ip='192.0.2.10')
        for _ in range(5):
            self.assertEqual(self._book('pro-nails', ip='192.0.2.10')[1].get('reason'), 'daily_limit')
        self.assertNotIn('ai_unavailable', self._book('pro-nails', ip='192.0.2.11')[1])
        self.assertEqual(self._book('pro-nails', ip='192.0.2.12')[1].get('reason'), 'daily_limit')
        self.assertEqual(len(CALLS), 2)

    def test_signed_in_tablet_of_that_shop_is_not_ip_capped_but_still_counted(self):
        os.environ['BOOKING_CHAT_DAILY_CAP_PER_IP'] = '1'
        for _ in range(3):
            body = self._book('pro-nails', ip='192.0.2.20', user='pro-nails', user_bid='pro-nails')[1]
            self.assertNotIn('ai_unavailable', body)
        day = time.strftime('%Y-%m-%d', time.gmtime())
        self.assertEqual(DB.ai_budget.find_one({'_id': f'booking_shop:{day}:pro-nails'})['n'], 3)
        # tài khoản của tiệm KHÁC mở trang đặt lịch của tiệm này: tính như khách ẩn danh
        self._book('pro-nails', ip='192.0.2.21', user='ess-nails', user_bid='ess-nails')
        self.assertEqual(self._book('pro-nails', ip='192.0.2.21', user='ess-nails', user_bid='ess-nails')[1].get('reason'),
                         'daily_limit')

    def test_counters_expire_and_do_not_store_raw_ips(self):
        self._book('pro-nails', ip='192.0.2.30')
        rows = DB.ai_budget.docs
        self.assertTrue(rows)
        self.assertTrue(all(isinstance(r.get('expires_at'), datetime) for r in rows), rows)
        self.assertFalse(any('192.0.2.30' in str(r['_id']) for r in rows))

    def test_booking_prompt_without_customer_message_is_cut(self):
        self._book('pro-nails', msg=None, userPrompt='y' * 50000)
        self.assertLessEqual(len(CALLS[-1]['messages'][-1]['content']), 2000)

    def test_anonymous_history_is_capped(self):
        history = [{'role': 'user' if i % 2 else 'assistant', 'content': f'{i:03d}' + 'h' * 2997} for i in range(40)]
        history.insert(len(history) - 1, {'role': 'user', 'content': {'$gt': ''}})   # không phải chuỗi: không lỗi 500
        status, _ = self._sales(history=history)
        self.assertEqual(status, 200)
        turns = CALLS[-1]['messages'][1:-1]
        self.assertLessEqual(len(turns), 10)
        self.assertLessEqual(sum(len(t['content']) for t in turns), 8000)
        self.assertTrue(turns and turns[-1]['content'].startswith('039'), 'the newest turns are kept')
        self._book('pro-nails', history=history)                       # chat đặt lịch (không mã chat): cũng có trần
        turns = CALLS[-1]['messages'][1:-1]
        self.assertLessEqual(sum(len(t['content']) for t in turns), 8000)

    def test_sales_chat_keeps_the_global_cap_and_the_two_budgets_are_separate(self):
        os.environ['SALES_BOT_DAILY_CAP'] = '1'
        self.assertNotIn('fallback', self._sales(ip='192.0.2.40')[1])
        self.assertEqual(self._sales(ip='192.0.2.41')[1].get('error'), 'daily_budget')
        self.assertNotIn('ai_unavailable', self._book('pro-nails', ip='192.0.2.42')[1])
        self.assertEqual(len(CALLS), 2)


# ================================================================ 2. dữ liệu nhân sự: nhân viên chỉ thấy dòng của mình
MONTH, YEAR = 10, 2026


class HrOwnRecordsTests(unittest.TestCase):
    def setUp(self):
        _reset()
        for code, email, sid in (('NV0001', 'alice@a.test', 11), ('NV0002', 'bob@a.test', 12), ('NV0003', None, 13)):
            DB.employees.insert_one({'business_id': 'shopA', 'ma_nv': code, 'ho_ten': code, 'email': email, 'staff_id': sid})
            DB.staff.insert_one({'id': sid, 'business_id': 'shopA', 'ma_nv': code, 'name': code, 'phone': '+1555000' + code[-2:],
                                 'commission_rate': 0.4, 'salary_config': {'luong_gio': 25}, 'role': 'Tech', 'is_active': True})
            for day in ('05/10/2026', '06/10/2026'):
                DB.chamcong.insert_one({'id': next(_ids), 'business_id': 'shopA', 'ma_nv': code, 'ngay_cham': day,
                                        'tien_tua': 100.0, 'tien_tips': 20.0, 'phu_cap': 5.0, 'toa_do': '10.7,106.6',
                                        'anh_checkin': f'/api/storage/file/{code}'})
            DB.leave_requests.insert_one({'id': next(_ids), 'business_id': 'shopA', 'ma_nv': code, 'reason': f'sick {code}'})
            DB.expense_requests.insert_one({'id': next(_ids), 'business_id': 'shopA', 'ma_nv': code, 'amount': 50})
        # cùng email ở tiệm KHÁC: không bao giờ được dùng cho shopA
        DB.employees.insert_one({'business_id': 'shopB', 'ma_nv': 'NV0009', 'email': 'carol@a.test'})

    def _get(self, fn, path, *a, user='u-alice', role='staff', email='Alice@A.test', bid='shopA', query=None):
        with _ctx(path, user=user, role=role, bid=bid, email=email, query_string=query or {}):
            if role is None:
                session.pop('role', None)
            return _call(fn, *a)

    def _rows(self, status_body):
        status, body = status_body
        self.assertEqual(status, 200, body)
        return sorted({r['ma_nv'] for r in body['data']})

    def test_staff_chamcong_list_is_only_their_own_rows(self):
        _need('_hr_scope_ma_nv')
        self.assertEqual(self._rows(self._get('api_hr_chamcong_list', '/api/hr/chamcong')), ['NV0001'])
        rows = self._get('api_hr_chamcong_list', '/api/hr/chamcong', query={'ma_nv': 'nv0001', 'month': MONTH, 'year': YEAR})
        self.assertEqual(self._rows(rows), ['NV0001'])
        self.assertEqual(len(rows[1]['data']), 2)

    def test_staff_cannot_read_a_colleague_by_query_param(self):
        for code in ('NV0002', 'NV0003', 'NV0009'):
            status, body = self._get('api_hr_chamcong_list', '/api/hr/chamcong', query={'ma_nv': code})
            self.assertEqual(status, 403, (code, body))
            self.assertNotIn('data', body)
            self.assertEqual(body['code'], 'own_records_only')
            self.assertTrue(body['error'] and body['message'])

    def test_unlinked_staff_account_reads_nothing(self):
        for email in ('carol@a.test', None, ''):     # email của tiệm khác / phiên không có email
            status, body = self._get('api_hr_chamcong_list', '/api/hr/chamcong', email=email, query={'ma_nv': 'NV0003'})
            self.assertEqual(status, 403, email)
            self.assertEqual(body['code'], 'staff_not_linked')
        # phiên thiếu role = nhân viên
        self.assertEqual(self._rows(self._get('api_hr_chamcong_list', '/api/hr/chamcong', role=None)), ['NV0001'])

    def test_email_shared_by_two_profiles_is_not_a_link(self):
        DB.employees.insert_one({'business_id': 'shopA', 'ma_nv': 'NV0004', 'email': 'ALICE@a.test '})
        self.assertEqual(self._get('api_hr_chamcong_list', '/api/hr/chamcong')[0], 403)

    def test_owner_keeps_the_whole_shop_and_the_filter(self):
        rows = self._get('api_hr_chamcong_list', '/api/hr/chamcong', user='owner-a', role='admin', email='o@a.test')
        self.assertEqual(self._rows(rows), ['NV0001', 'NV0002', 'NV0003'])
        rows = self._get('api_hr_chamcong_list', '/api/hr/chamcong', user='owner-a', role='admin', query={'ma_nv': 'NV0002'})
        self.assertEqual(self._rows(rows), ['NV0002'])
        self.assertEqual(rows[1]['data'][0]['tien_tua'], 100.0)

    def test_month_summary(self):
        q = {'ma_nv': 'NV0002', 'month': MONTH, 'year': YEAR}
        self.assertEqual(self._get('api_hr_chamcong_month_summary', '/x', query=q)[0], 403)
        status, body = self._get('api_hr_chamcong_month_summary', '/x', query=dict(q, ma_nv='NV0001'))
        self.assertEqual((status, body['days']['05/10/2026']['commission']), (200, 100.0))
        status, body = self._get('api_hr_chamcong_month_summary', '/x', user='owner-a', role='admin', query=q)
        self.assertEqual((status, sorted(body['days'])), (200, ['05/10/2026', '06/10/2026']))

    def test_leave_and_expense_lists(self):
        for fn, path in (('api_leave_requests_list', '/api/leave_requests'), ('api_expense_requests_list', '/api/expense_requests')):
            self.assertEqual(self._rows(self._get(fn, path)), ['NV0001'], fn)
            self.assertEqual(self._rows(self._get(fn, path, query={'ma_nv': 'NV0001'})), ['NV0001'], fn)
            self.assertEqual(self._get(fn, path, query={'ma_nv': 'NV0002'})[0], 403, fn)
            self.assertEqual(self._rows(self._get(fn, path, user='owner-a', role='admin')), ['NV0001', 'NV0002', 'NV0003'])

    def test_payroll_stream_follows_only_the_own_rows(self):
        self.assertEqual(self._get('stream_payroll', '/api/stream/payroll')[1], 'SSE')
        watchable, match = SSE[-1]
        self.assertIs(watchable, DB.chamcong)
        self.assertIn('NV0001', json.dumps(match, default=str))
        self.assertEqual(self._get('stream_payroll', '/api/stream/payroll', query={'ma_nv': 'NV0002'})[0], 403)
        SSE.clear()
        self._get('stream_payroll', '/api/stream/payroll', user='owner-a', role='admin')   # bangluong: cả tiệm
        self.assertIs(SSE[-1][0], DB)

    def test_income_today(self):
        self.assertEqual(self._get('api_staff_income_today', '/x', 11)[0], 200)
        self.assertEqual(self._get('api_staff_income_today', '/x', 12)[0], 403)
        self.assertEqual(self._get('api_staff_income_today', '/x', 12, email='nobody@a.test')[0], 403)
        self.assertEqual(self._get('api_staff_income_today', '/x', 12, user='owner-a', role='admin')[0], 200)

    def test_staff_list_hides_pay_and_phone_from_staff(self):
        status, body = self._get('api_staff_list', '/api/staff')
        self.assertEqual(status, 200)
        for r in body['data']:
            for f in ('salary_config', 'commission_rate', 'phone'):
                self.assertNotIn(f, r)
            self.assertIn('name', r)
        status, body = self._get('api_staff_list', '/api/staff', user='owner-a', role='admin')
        self.assertTrue(all(r['salary_config'] == {'luong_gio': 25} for r in body['data']))

    def test_staff_app_earnings_call_still_works(self):
        """app_nhanvien.html gọi /api/hr/chamcong?ma_nv=<mã đã đăng nhập>&month&year và /api/stream/payroll?ma_nv=<mã>."""
        src = _read('templates/app_nhanvien.html')
        self.assertIn('/api/hr/chamcong?ma_nv=${encodeURIComponent(currentUser.code)}&month=', src)
        self.assertIn('/api/stream/payroll?ma_nv=${encodeURIComponent(currentUser.code)}', src)
        rows = self._get('api_hr_chamcong_list', '/api/hr/chamcong', query={'ma_nv': 'NV0001', 'month': MONTH, 'year': YEAR})
        self.assertEqual(rows[1]['data'][0]['tien_tua'], 100.0)


# ================================================================ 3. ảnh chat của khách: trần riêng, không ăn vào ảnh của tiệm
class PortalUploadQuotaTests(unittest.TestCase):
    CID = 'shopA:+15550001'

    def setUp(self):
        _reset()
        os.environ.pop('PORTAL_CHAT_SHOP_CAP_BYTES', None)
        DB.bot_customers.insert_one({'id': self.CID, 'business_id': 'shopA', 'channel': 'web'})
        DB.bot_customers.insert_one({'id': 'shopB:+15550002', 'business_id': 'shopB', 'channel': 'web'})
        self.cap = NS['_LEGACY_MEDIA_SHOP_CAP_BYTES']
        self.old = datetime.now(timezone.utc) - timedelta(days=3)    # ngoài trần số ảnh/ngày

    def tearDown(self):
        os.environ.pop('PORTAL_CHAT_SHOP_CAP_BYTES', None)

    def _staff_upload(self, bid='shopA'):
        form = {'kind': 'checkin', 'file': (io.BytesIO(PNG), 'checkin.png')}
        with _ctx('/api/storage/upload', method='POST', user='u-1', role='staff', bid=bid, data=form,
                  content_type='multipart/form-data'):
            return _call('api_storage_upload')

    def _portal_upload(self, cid=None):
        form = {'customer_id': cid or self.CID, 'file': (io.BytesIO(JPEG), 'p.jpg')}
        with _ctx('/api/portal/upload', method='POST', data=form, content_type='multipart/form-data'):
            return _call('api_portal_upload')

    def _portal_bytes(self, bid, n):
        DB['media.files'].insert_one({'business_id': bid, 'kind': 'portal_chat', 'customer_id': f'{bid}:+1999',
                                      'uploaded_at': self.old, 'length': n})

    def test_anonymous_chat_photos_never_fill_the_shop_media_cap(self):
        self._portal_bytes('shopA', self.cap)               # khách lạ đã tải đầy bằng trần ảnh của tiệm
        status, body = self._staff_upload()
        self.assertEqual(status, 200, body)                 # trước bản vá: 413 -> nhân viên không chấm công có ảnh được

    def test_the_shop_media_cap_still_applies_to_staff_photos(self):
        DB['media.files'].insert_one({'business_id': 'shopA', 'kind': 'checkin', 'length': self.cap})
        self.assertEqual(self._staff_upload()[0], 413)
        self.assertEqual(self._staff_upload('shopB')[0], 200)

    def test_anonymous_chat_photos_have_their_own_quota(self):
        os.environ['PORTAL_CHAT_SHOP_CAP_BYTES'] = '5000'
        self.assertEqual(self._portal_upload()[0], 200)
        self._portal_bytes('shopA', 5000)
        status, body = self._portal_upload()
        self.assertEqual(status, 413, body)
        self.assertEqual(self._portal_upload('shopB:+15550002')[0], 200, 'quota is per shop')
        self.assertEqual(self._staff_upload()[0], 200, "the shop's own uploads are not blocked by the chat quota")

    def test_staff_photos_do_not_use_the_chat_quota(self):
        os.environ['PORTAL_CHAT_SHOP_CAP_BYTES'] = '5000'
        DB['media.files'].insert_one({'business_id': 'shopA', 'kind': 'checkin', 'length': 10 ** 9})
        self.assertEqual(self._portal_upload()[0], 200)


# ================================================================ 4. khôi phục sao lưu không đặt được ngành tuỳ ý
class BackupRestoreIndustryTests(unittest.TestCase):
    def setUp(self):
        _reset()
        _owner('shopA', plan='pro', industry='nail', created_at=NEW)     # tiệm mới: khoá theo ngành của mã kích hoạt
        _owner('leg1', industry='fnb', created_at=OLD)                   # tiệm cũ: đổi ngành tự do
        for bid, mode in (('shopA', 'nail'), ('leg1', 'fnb')):
            DB.system_settings.insert_one({'key': f'business_mode_{bid}', 'value': mode})

    def _backup(self, bid, settings_rows, name='backup_1.json'):
        data = {'products': [{'id': 1, 'name': 'Gel', 'business_id': 'someone-else'}], 'system_settings': settings_rows,
                '_backup_metadata': {'business_id': bid}}
        BACKUP_FS.put(json.dumps(data).encode('utf-8'), filename=name, business_id=bid, content_type='application/json')
        return name

    def _restore(self, bid, name):
        with _ctx('/api/backup/restore', method='POST', user=bid, role='admin', json={'filename': name}):
            return _call('restore_backup')

    def _mode_row(self, bid):
        return DB.system_settings.find_one({'key': f'business_mode_{bid}'}, {'_id': 0})

    def test_unknown_mode_in_a_backup_is_not_restored(self):
        name = self._backup('shopA', [{'key': 'business_mode_shopA', 'value': 'evil', 'is_admin': True}])
        status, body = self._restore('shopA', name)
        self.assertEqual(status, 200, body)
        self.assertEqual(self._mode_row('shopA'), {'key': 'business_mode_shopA', 'value': 'nail'})
        self.assertTrue(body.get('business_mode_kept'))
        self.assertEqual([p['business_id'] for p in DB.products.find({})], ['shopA'], 'table data is still restored')

    def test_locked_shop_cannot_switch_industry_through_a_backup(self):
        name = self._backup('shopA', [{'key': 'business_mode_shopA', 'value': 'production'}])
        self._restore('shopA', name)
        self.assertEqual(self._mode_row('shopA')['value'], 'nail')

    def test_valid_allowed_mode_is_restored(self):
        name = self._backup('leg1', [{'key': 'business_mode_leg1', 'value': ' Hotel ', 'extra': 1}])
        status, body = self._restore('leg1', name)
        self.assertEqual(status, 200, body)
        self.assertEqual(self._mode_row('leg1'), {'key': 'business_mode_leg1', 'value': 'hotel'})
        name = self._backup('shopA', [{'key': 'business_mode_shopA', 'value': 'nail'}], name='backup_2.json')
        self.assertNotIn('business_mode_kept', self._restore('shopA', name)[1])

    def test_malformed_settings_rows_keep_the_current_mode(self):
        for i, rows in enumerate(([{'value': {'$gt': ''}}], ['nail'], {'value': 'hotel'})):
            name = self._backup('leg1', rows, name=f'backup_m{i}.json')
            status, body = self._restore('leg1', name)
            self.assertEqual(status, 200, (rows, body))
            self.assertEqual(self._mode_row('leg1')['value'], 'fnb', rows)


# ================================================================ 5. tin tự động chỉ khi gói có 'messaging'
PRODUCERS = ('produce_appointment_reminders', 'produce_review_requests', 'produce_nurture', 'produce_owner_report')
AUTO = ('appointment_reminder', 'review_request', 'nurture', 'birthday', 'loyalty', 'missed_call', 'owner_report')
TRANSACTIONAL = ('staff_alert', 'on_my_way', 'test')


class AutomatedMessagingPlanTests(unittest.TestCase):
    def setUp(self):
        _reset()
        _owner('ess', plan='essential')
        _owner('pro', plan='pro')
        DB.businesses.insert_one({'id': 'ess-b1', 'parent_business_id': 'ess', 'created_at': NEW})
        DB.businesses.insert_one({'id': 'pro-b1', 'parent_business_id': 'pro', 'created_at': NEW})
        for bid in ('ess', 'pro'):
            DB.messaging_settings.insert_one({'business_id': bid, 'send_window_start': 0, 'send_window_end': 24})
        self.sent = []
        self.producers = {n: MagicMock(return_value=0) for n in PRODUCERS}
        for n, m in self.producers.items():
            m.__name__ = n
        self._patches = [patch.object(messaging, 'send_now', side_effect=self._send)] + \
                        [patch.object(messaging, n, m) for n, m in self.producers.items()]
        for pt in self._patches:
            pt.start()

    def tearDown(self):
        for pt in self._patches:
            pt.stop()

    def _send(self, m, *a, **k):
        self.sent.append((m['business_id'], m['kind']))
        return 'provider-1'

    def _queue_all(self, bid):
        ids = {}
        for kind in AUTO + TRANSACTIONAL:
            ids[kind] = messaging.queue(bid, 'email', f'{kind}@cust.test', f'hello {kind}', kind,
                                        meta={'campaign_message_id': 77} if kind == 'nurture' else None)
        DB.campaign_messages.insert_one({'id': 77, 'business_id': bid, 'delivery_status': 'queued'})
        return ids

    def _status(self, mid):
        return DB.outbound_messages.find_one({'id': mid})

    def test_plan_check_follows_the_paying_shop(self):
        _need('_queue_loyalty_notification')
        self.assertTrue(hasattr(messaging, 'automation_allowed'), 'messaging.automation_allowed missing (fix not applied)')
        self.assertEqual([messaging.automation_allowed(b) for b in ('ess', 'ess-b1', 'pro', 'pro-b1')], [False, False, True, True])

    def test_essential_shop_sends_no_automated_messages(self):
        ids = self._queue_all('ess')
        messaging.pump('ess')
        for n, m in self.producers.items():
            m.assert_not_called()
        self.assertEqual(sorted(k for _b, k in self.sent), sorted(TRANSACTIONAL))
        for kind in AUTO:
            row = self._status(ids[kind])
            self.assertEqual(row['status'], 'cancelled', kind)
            self.assertIn('plan', row['error'])
        self.assertEqual(DB.campaign_messages.find_one({'id': 77})['delivery_status'], 'cancelled')

    def test_pro_shop_is_unchanged(self):
        self._queue_all('pro')
        messaging.pump('pro')
        for n, m in self.producers.items():
            m.assert_called_once()
        self.assertEqual(sorted(k for _b, k in self.sent), sorted(AUTO + TRANSACTIONAL))

    def test_downgrade_stops_already_queued_automation_at_send_time(self):
        mid = messaging.queue('pro', 'email', 'c@cust.test', 'reminder', 'appointment_reminder')
        DB.businesses.update_one({'id': 'pro'}, {'$set': {'plan': 'essential'}})
        plans._PLAN_CACHE.clear()                                    # hết 60 giây cache
        messaging.pump('pro')
        self.assertEqual(self._status(mid)['status'], 'cancelled')
        self.assertEqual(self.sent, [])

    def test_deliver_checks_the_plan_too(self):
        auto = messaging.queue('ess', 'email', 'c@cust.test', 'review us', 'review_request')
        alert = messaging.queue('ess', 'email', 'owner@ess.test', 'a customer is waiting', 'staff_alert')
        self.assertFalse(messaging.deliver(auto))
        self.assertEqual(self._status(auto)['status'], 'cancelled')
        self.assertTrue(messaging.deliver(alert))
        self.assertEqual(self.sent, [('ess', 'staff_alert')])

    def test_birthday_and_loyalty_are_not_queued_without_the_plan(self):
        cust = {'id': 5, 'name': 'Lan', 'email': 'lan@cust.test'}
        for event in ('birthday', 'points_awarded', 'appointment_reminder'):
            self.assertEqual(NS['_queue_loyalty_notification']('ess', cust, event, 'Hi {shop}'), 'not_in_plan', event)
        self.assertEqual(DB.outbound_messages.count_documents({'business_id': 'ess'}), 0)
        self.assertEqual(NS['_queue_loyalty_notification']('pro', cust, 'birthday', 'Happy birthday from {shop}'), 'queued')
        self.assertEqual(DB.outbound_messages.count_documents({'business_id': 'pro', 'kind': 'birthday'}), 1)


# ================================================================ 6. đăng ký ghi ngành của mã kích hoạt, /setup khoá theo
class LicenseIndustryTests(unittest.TestCase):
    def setUp(self):
        _reset()
        os.environ.pop('SUPERADMIN_EMAILS', None)

    def _code(self, key, nganh):
        doc = {'license_key': key, 'trang_thai': 'Sẵn sàng', 'plan': 'pro'}
        if nganh is not None:
            doc['nganh_nghe'] = nganh
        DB.license_codes.insert_one(doc)
        return key

    def _register(self, code, business_type, email='owner@shop.test'):
        form = {'email': email, 'password': 'owner-pass-123', 'business_type': business_type, 'business_name': 'Shop',
                'fullname': 'Owner', 'license_key': code}
        with _ctx('/register', method='POST', data=form):
            out = NS['register']()
        return getattr(out, 'status_code', 200), out

    def _biz(self, email='owner@shop.test'):
        user = DB.users.find_one({'email': email})
        return DB.businesses.find_one({'id': user['id']}) if user else None

    def _setup(self, bid, mode):
        with _ctx('/setup', method='POST', user=bid, role='admin', data={'mode': mode}):
            out = NS['setup']()
        return out[1] if isinstance(out, tuple) else out.status_code

    def test_single_industry_code_is_recorded(self):
        status, _ = self._register(self._code('C-NAIL', 'Nail'), 'spa')
        self.assertEqual(status, 302)
        biz = self._biz()
        self.assertEqual((biz['industry_code'], biz.get('license_industry')), ('nail', 'nail'))

    def test_shared_code_is_recorded_as_all(self):
        for i, nganh in enumerate(('all', 'ALL', '', None)):
            email = f'o{i}@shop.test'
            status, _ = self._register(self._code(f'C-ALL-{i}', nganh), 'spa', email=email)
            self.assertEqual(status, 302, nganh)
            biz = self._biz(email)
            self.assertEqual((biz['industry_code'], biz.get('license_industry')), ('spa', 'all'), nganh)

    def test_shared_code_with_a_made_up_industry_is_refused_and_the_code_kept(self):
        status, out = self._register(self._code('C-ALL', 'all'), 'evil')
        self.assertEqual(status, 200)
        self.assertIn('business type', str(out))
        self.assertIsNone(DB.users.find_one({'email': 'owner@shop.test'}))
        self.assertEqual(DB.license_codes.find_one({'license_key': 'C-ALL'})['trang_thai'], 'Sẵn sàng')

    def test_setup_lock_follows_the_code(self):
        self._register(self._code('C-OFF', 'office'), 'office', email='off@shop.test')
        self._register(self._code('C-ALL', 'all'), 'spa', email='any@shop.test')
        off, anyb = self._biz('off@shop.test')['id'], self._biz('any@shop.test')['id']
        self.assertEqual(self._setup(off, 'hotel'), 403)
        self.assertEqual(self._setup(off, 'office'), 302)
        self.assertEqual(self._setup(anyb, 'hotel'), 302, 'a shared code is not locked to the dropdown choice')
        self.assertEqual(DB.system_settings.find_one({'key': f'business_mode_{anyb}'})['value'], 'hotel')

    def test_profiles_without_the_field_keep_the_old_rule(self):
        _owner('pre', industry='office', created_at=NEW)       # tạo trước bản vá: chưa có license_industry
        _owner('leg', industry='office', created_at=OLD)
        self.assertEqual(self._setup('pre', 'hotel'), 403)
        self.assertEqual(self._setup('leg', 'hotel'), 302)


# ================================================================ 7. dòng "chi nhánh chính" chỉ cho chủ tiệm
class PrimaryMembershipTests(unittest.TestCase):
    def setUp(self):
        _reset()
        _owner('shopA', plan='pro', created_at=OLD)
        DB.users.insert_one({'id': 'staff-1', 'email': 'st@a.test', 'business_id': 'shopA', 'role': 'staff', 'created_at': NEW})
        DB.users.insert_one({'id': 'legacy-own', 'email': 'lo@a.test', 'role': 'admin', 'created_at': OLD})   # thiếu business_id

    def _rows(self, uid):
        return list(DB.business_memberships.find({'owner_user_id': uid}, {'_id': 0}))

    def test_staff_login_gets_no_primary_branch_of_its_own(self):
        _need('_ensure_primary_membership')
        NS['_ensure_primary_membership']('staff-1', 'staff-1')
        self.assertEqual(self._rows('staff-1'), [])
        NS['_ensure_primary_membership']('ghost', 'ghost')               # không có tài khoản: không tạo gì
        self.assertEqual(self._rows('ghost'), [])

    def test_owners_keep_their_primary_branch(self):
        for uid in ('shopA', 'legacy-own'):
            NS['_ensure_primary_membership'](uid, uid)
            NS['_ensure_primary_membership'](uid, uid)                   # idempotent
            rows = self._rows(uid)
            self.assertEqual([(r['business_id'], r['is_primary']) for r in rows], [(uid, True)], uid)

    def _switch(self, uid, bid, target, role='staff'):
        with _ctx('/api/switch_branch', method='POST', user=uid, role=role, bid=bid, json={'business_id': target}):
            status, body = _call('api_switch_branch')
            return status, body, session.get('business_id')

    def test_stale_primary_row_of_a_staff_account_cannot_be_switched_into(self):
        DB.business_memberships.insert_one({'owner_user_id': 'staff-1', 'business_id': 'staff-1', 'is_primary': True,
                                            'branch_name': 'Chi nhánh chính'})   # dòng do bản cũ tạo
        status, body, active = self._switch('staff-1', 'shopA', 'staff-1')
        self.assertEqual(status, 403, body)
        self.assertEqual(active, 'shopA')

    def test_owner_switches_back_to_the_main_location(self):
        NS['_ensure_primary_membership']('shopA', 'shopA')
        DB.businesses.insert_one({'id': 'shopA-b1', 'parent_business_id': 'shopA', 'created_at': NEW})
        DB.business_memberships.insert_one({'owner_user_id': 'shopA', 'business_id': 'shopA-b1', 'is_primary': False})
        status, body, active = self._switch('shopA', 'shopA-b1', 'shopA', role='admin')
        self.assertEqual((status, active), (200, 'shopA'), body)


# ================================================================ 8. giao diện: ghi chú nghỉ phép được escape
def _inline_scripts(html):
    """<script> inline (không src), thay biểu thức Jinja bằng 0 để node --check được."""
    out = []
    for m in re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S):
        code = re.sub(r'\{\{.*?\}\}', '0', m.group(1), flags=re.S)
        code = re.sub(r'\{%.*?%\}|\{#.*?#\}', '', code, flags=re.S)
        out.append(code)
    return out


def _node(code, *args):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(code)
    try:
        return subprocess.run(['node', *args, f.name], capture_output=True, text=True, encoding='utf-8', timeout=60)
    finally:
        os.unlink(f.name)


class TemplateTests(unittest.TestCase):
    def test_leave_note_cannot_break_out_of_the_title_attribute(self):
        src = _read('templates/dashboard.html')
        line = next(l for l in src.splitlines() if 'const titleAttr' in l)
        esc = next(l for l in src.splitlines() if l.startswith('window.__escHtml = '))
        js = (esc.replace('window.__escHtml', 'const __escHtml') + '\n'
              + "const t = (k) => 'On leave:';\n"
              + "const leaves = [{note: '\\\" onmouseover=\\\"alert(1)'}, {note: '<img src=x onerror=alert(2)>'}];\n"
              + line.strip() + '\nprocess.stdout.write(titleAttr);')
        r = _node(js)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith('title="On leave: '), r.stdout)
        self.assertNotIn('" onmouseover', r.stdout)
        self.assertNotIn('<img', r.stdout)
        self.assertIn('&quot; onmouseover=&quot;', r.stdout)
        self.assertEqual(r.stdout.count('"'), 2, 'only the attribute quotes remain')

    def test_touched_templates_inline_js_parses(self):
        for rel in ('templates/dashboard.html', 'templates/index.html'):
            for i, code in enumerate(_inline_scripts(_read(rel))):
                r = _node(code, '--check')
                self.assertEqual(r.returncode, 0, f'{rel} script #{i}: {r.stderr[-400:]}')

    def test_fast_checkin_comment_matches_the_code(self):
        src = _read('templates/index.html')
        i = src.index("hrApi(`/api/public/hr/employees/lookup?ma_nv=")
        comment = src[max(0, i - 700):i]
        self.assertNotIn('TRƯỚC KHI đăng nhập', comment)
        self.assertIn('401', comment)
        self.assertNotIn('{%', comment)          # không chèn cú pháp Jinja vào chú thích JS


class CompileTests(unittest.TestCase):
    def test_py_compile_touched_files(self):
        import py_compile
        for rel in ('app.py', 'messaging.py', 'scripts/tests/test_security_h4a-app.py', 'scripts/tests/test_security_h3-exposure.py'):
            py_compile.compile(os.path.join(ROOT, rel), doraise=True)


if __name__ == '__main__':
    if MISSING:
        print('NOTE: app.py has no', MISSING)
    unittest.main(verbosity=2)
