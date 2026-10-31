# -*- coding: utf-8 -*-
"""Test OFFLINE bảo mật h4b-auth-inbox:
1. OAuth (oauth_login.py)
   - callback / _login không mở phiên cho tài khoản đã xoá (is_deleted) / bị khoá (is_active False), kể cả gọi _login trực tiếp;
   - KHÔNG tự liên kết, KHÔNG đăng nhập vào bản ghi mang email quản trị BitPaw (SUPERADMIN_ROOT_EMAIL + SUPERADMIN_EMAILS),
     kể cả bản ghi đã liên kết Google/Facebook từ trước; email nhà cung cấp chỉ khác ở gộp hoa/thường Unicode ('ſ' ~ 's')
     không được liên kết vào tài khoản người khác;
   - /auth/complete từ chối email quản trị TRƯỚC khi dùng mã kích hoạt; ghi businesses.license_industry (ngành của mã).
   Người dùng thường: liên kết theo email trùng, đăng nhập bằng liên kết cũ, nhân viên đăng nhập — vẫn chạy như cũ.
2. POST /api/account/logout_all: Super Admin (phiên God Mode) "đăng xuất mọi nơi" gọi bump_session_version('superadmin-fallback')
   (tăng system_settings.superadmin_session_ver); chủ tiệm vẫn tăng session_ver của chính mình; chưa đăng nhập -> 401.
3. SĐT gõ trong Messenger/Zalo (inbox_channels.link_customer): tự gắn id kênh vào hồ sơ khách CHỈ khi hồ sơ đó chưa có id của
   nền tảng đó VÀ đúng 1 khách của tiệm có SĐT đó (và id kênh chưa gắn hồ sơ khác); còn lại -> liên kết chờ duyệt. Chủ tiệm/admin
   Xác nhận / Bỏ qua qua POST /api/bot/customer_link (nhân viên / tiệm khác / toán tử Mongo -> 403). Thanh "liên kết chờ duyệt"
   ở đầu hội thoại ai_bot.html (VI/EN, escape mọi chữ, chỉ chủ tiệm/admin) — kiểm bằng node.

KHÔNG import app.py (module 'app' giả; các hàm cần kiểm lấy NGUYÊN VĂN từ app.py qua ast), KHÔNG mở MongoDB (mongo_client bị
stub trước mọi import — .env trỏ PRODUCTION), KHÔNG gọi mạng / SMTP / Meta / Zalo, KHÔNG chạy server.
Chạy: PYTHONIOENCODING=utf-8 python scripts/tests/test_security_h4b-auth-inbox.py
"""
import ast
import copy
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
from datetime import datetime, timedelta
from functools import wraps
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)


def _no_network(*a, **kw):
    raise AssertionError('network disabled in offline tests')


patch('requests.sessions.Session.request', _no_network).start()

# ---------------------------------------------------------------- Mongo giả trong RAM (đường dẫn có dấu chấm, toán tử cơ bản)
_MISSING = object()


def _get(doc, path):
    cur = doc
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _set(doc, path, value):
    parts = path.split('.')
    cur = doc
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _unset(doc, path):
    parts = path.split('.')
    cur = doc
    for part in parts[:-1]:
        cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            return
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


def _match_value(val, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith('$') for k in cond):
        v = None if val is _MISSING else val          # Mongo: thiếu field = null khi so sánh
        for op, arg in cond.items():
            if op == '$options':
                continue
            if op == '$regex':                        # Mongo dùng PCRE; với các mẫu ở đây Python re cho cùng kết quả
                flags = re.IGNORECASE if 'i' in cond.get('$options', '') else 0
                if not isinstance(v, str) or not re.search(arg, v, flags):
                    return False
            elif op == '$ne':
                if v == arg:
                    return False
            elif op == '$in':
                if v not in arg:
                    return False
            elif op == '$exists':
                if (val is not _MISSING) != bool(arg):
                    return False
            else:
                raise AssertionError(f'FakeDB: unsupported operator {op}')
        return True
    if val is _MISSING:
        return cond is None
    return val == cond


def _matches(doc, flt):
    return all(_match_value(_get(doc, k), cond) for k, cond in (flt or {}).items())


def _project(doc, projection):
    d = copy.deepcopy(doc)
    if not projection:
        return d
    inc = [k for k, v in projection.items() if v and k != '_id']
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
        return _Cursor(sorted(self, key=lambda d: str(d.get(key) or ''), reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self):
        self.docs = []

    def find(self, flt=None, projection=None):
        return _Cursor(_project(d, projection) for d in self.docs if _matches(d, flt))

    def find_one(self, flt=None, projection=None):
        for d in self.docs:
            if _matches(d, flt):
                return _project(d, projection)
        return None

    def count_documents(self, flt=None):
        return sum(1 for d in self.docs if _matches(d, flt))

    def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))
        return types.SimpleNamespace(inserted_id=len(self.docs))

    @staticmethod
    def _apply(d, upd):
        before = copy.deepcopy(d)
        for k, v in (upd.get('$set') or {}).items():
            _set(d, k, copy.deepcopy(v))
        for k in (upd.get('$unset') or {}):
            _unset(d, k)
        for k, v in (upd.get('$inc') or {}).items():
            cur = _get(d, k)
            _set(d, k, (0 if cur is _MISSING or cur is None else cur) + v)
        return d != before

    def update_one(self, flt, upd, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                return types.SimpleNamespace(matched_count=1, modified_count=int(self._apply(d, upd)), upserted_id=None)
        if upsert:
            d = {k: v for k, v in flt.items() if not isinstance(v, dict) and not str(k).startswith('$')}
            for k, v in (upd.get('$setOnInsert') or {}).items():
                _set(d, k, v)
            self._apply(d, upd)
            self.docs.append(d)
            return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=len(self.docs))
        return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def create_index(self, *a, **k):
        return None


class FakeDB:
    def __init__(self):
        self.__dict__['_c'] = {}

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self._c.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return getattr(self, name)

    def reset(self):
        self._c.clear()


DB = FakeDB()

# ---------------------------------------------------------------- stub TRƯỚC mọi import của module thật
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: 1, MONGO_STATUS='CONNECTED')
LOG_EVENTS = []
_shield = types.ModuleType('security_shield')
_shield.client_ip = lambda req: '203.0.113.9'
_shield.code_attempts_blocked = lambda ip: False
_shield.record_code_failure = MagicMock(name='record_code_failure')
_shield.honeypot_tripped = lambda data: False
_shield.log_event = lambda *a, **k: LOG_EVENTS.append(a)
sys.modules['security_shield'] = _shield
SEND = MagicMock(name='EmailService.send_email', return_value=(True, 'ok'))
_es = types.ModuleType('email_service')
_es.EmailService = type('EmailService', (), {'send_email': staticmethod(lambda *a, **k: SEND(*a, **k))})
sys.modules['email_service'] = _es
_vault = types.ModuleType('nurture_channel_tokens')
_vault.encrypt_secret = lambda s: s
_vault.decrypt_secret = lambda s: s
sys.modules['nurture_channel_tokens'] = _vault
_ft = types.ModuleType('ai_function_tools')   # inbox_channels.ai_default_on() import bên trong hàm
_ft.has_booking_pack = lambda bid: False
sys.modules['ai_function_tools'] = _ft

from flask import Flask, flash, g, jsonify, redirect, request, session, url_for  # noqa: E402
from flask_limiter import Limiter  # noqa: E402

FLASK = Flask(__name__)
FLASK.secret_key = 'h4b-offline-test-only'
FLASK.config['TESTING'] = True
LIMITER = Limiter(lambda: request.remote_addr or '127.0.0.1', app=FLASK, storage_uri='memory://', default_limits=[])


@FLASK.route('/login')
def login():
    return 'login page'


@FLASK.route('/')
def index():
    return 'home'


import inbox_channels  # noqa: E402  (mongo_client = DB giả)

inbox_channels.send_text = MagicMock(side_effect=AssertionError('no real send in this test'))


# ---------------------------------------------------------------- module 'app' giả, hàm lấy NGUYÊN VĂN từ app.py qua ast
def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


APP_SRC = _read('app.py')
_TREE = ast.parse(APP_SRC)
_FN = {n.name: n for n in _TREE.body if isinstance(n, ast.FunctionDef)}
DECORATORS = {name: [ast.unparse(d) for d in n.decorator_list] for name, n in _FN.items()}

APP = types.ModuleType('app')
APP.__dict__.update(
    os=os, re=re, json=json, time=time, datetime=datetime, timedelta=timedelta, wraps=wraps,
    session=session, request=request, g=g, jsonify=jsonify, flash=flash, redirect=redirect, url_for=url_for,
    db=DB, app=FLASK, inbox_channels=inbox_channels,
    _vi_en=lambda vi, en: en,
    _inbox_after_customer_message=lambda *a, **k: None, _inbox_walkin=lambda bid: 'Client',
    _ensure_primary_membership=lambda *a, **k: None, _get_real_client_ip=lambda: '203.0.113.9',
    INDUSTRY_CONFIG={'nail': {}, 'spa': {}, 'fnb': {}}, _send_welcome_email=MagicMock(name='_send_welcome_email'),
    csrf=types.SimpleNamespace(protect=lambda: None), limiter=LIMITER,
)
for _node in _TREE.body:   # hằng số / cache ở cấp module
    if isinstance(_node, ast.Assign) and any(getattr(t, 'id', None) in ('SUPERADMIN_ROOT_EMAIL', '_SESSION_STATE_CACHE',
                                                                         '_SUPERADMIN_VER_CACHE') for t in _node.targets):
        exec(compile(ast.Module(body=[_node], type_ignores=[]), 'app.py', 'exec'), APP.__dict__)
# thứ tự: decorator trước, route sau (route giữ NGUYÊN decorator @app.route/@login_required/@role_required của app.py)
for _name in ('_is_authorized_superadmin_email', 'bump_session_version', '_email_query', '_wants_json', 'login_required',
              'role_required', '_assert_owns_bot_customer', '_inbox_handle_event', 'api_bot_customer_link'):
    exec(compile(ast.Module(body=[_FN[_name]], type_ignores=[]), f'app.py::{_name}', 'exec'), APP.__dict__)
sys.modules['app'] = APP
ROOT_ADMIN = APP.SUPERADMIN_ROOT_EMAIL
ENV_ADMIN = 'ops-admin@bitpaw.test'

os.environ.update(GOOGLE_CLIENT_ID='test-client-id', GOOGLE_CLIENT_SECRET='test-client-secret', SUPERADMIN_EMAILS=ENV_ADMIN)
for _k in ('OAUTH_TEST_BASE', 'PUBLIC_BASE_URL', 'FACEBOOK_APP_ID', 'FACEBOOK_APP_SECRET'):
    os.environ.pop(_k, None)

import oauth_login  # noqa: E402
import password_reset  # noqa: E402

oauth_login.render_template = lambda name, **ctx: f"TEMPLATE {name} | {ctx.get('error') or ''}"
FLASK.register_blueprint(oauth_login.oauth_bp)
FLASK.register_blueprint(password_reset.reset_bp)


class _Resp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._d


class _Base(unittest.TestCase):
    def setUp(self):
        DB.reset()
        LIMITER.reset()
        LOG_EVENTS.clear()
        APP._SUPERADMIN_VER_CACHE.clear()
        APP._SESSION_STATE_CACHE.clear()
        _shield.record_code_failure.reset_mock()
        self.c = FLASK.test_client()

    def add_user(self, **doc):
        doc.setdefault('business_id', doc['id'])
        doc.setdefault('role', 'admin')
        doc.setdefault('session_ver', 0)
        DB.users.insert_one(doc)
        if not DB.businesses.find_one({'id': doc['business_id']}):
            DB.businesses.insert_one({'id': doc['business_id'], 'name': 'Shop ' + doc['business_id']})
        return doc

    def user(self, uid):
        return DB.users.find_one({'id': uid})

    def callback(self, sub, email, verified=True, provider='google'):
        with self.c.session_transaction() as s:
            s['oauth'] = {'provider': provider, 'state': 'st-1', 'verifier': 'v', 'nonce': 'n', 'ts': int(time.time()), 'next': None}
        info = {'sub': sub, 'email': email, 'email_verified': verified, 'name': 'Test Person'}
        with patch.object(oauth_login.requests, 'post', return_value=_Resp({'access_token': 'at-1'})), \
                patch.object(oauth_login.requests, 'get', return_value=_Resp(info)):
            return self.c.get(f'/auth/{provider}/callback?state=st-1&code=code-1')

    def sess(self):
        with self.c.session_transaction() as s:
            return dict(s)

    def login_as(self, uid, role='admin', bid=None, email=None):
        with self.c.session_transaction() as s:
            s.update({'user_id': uid, 'role': role, 'business_id': bid or uid, 'user_email': email or f'{uid}@shop.test'})

    def assert_refused(self, r):
        s = self.sess()
        self.assertIsNone(s.get('user_id'))
        self.assertNotIn('oauth_signup', s)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].endswith('/login'), r.headers['Location'])


# ================================================================ 1a. OAuth: tài khoản quản trị / đã xoá / bị khoá
class OAuthAccountGateTests(_Base):
    def test_admin_email_row_is_never_auto_linked_or_logged_in(self):
        for stored in (ROOT_ADMIN, ENV_ADMIN, ENV_ADMIN.upper()):
            with self.subTest(stored=stored):
                self.setUp()
                self.add_user(id='u-adm', email=stored)
                r = self.callback('g-somebody', stored.lower())
                self.assert_refused(r)
                self.assertNotIn('oauth', self.user('u-adm'))          # không ghi liên kết Google vào bản ghi quản trị
                self.assertNotIn('oauth_linked_at', self.user('u-adm'))

    def test_admin_email_row_linked_before_the_fix_cannot_log_in(self):
        for stored in (ROOT_ADMIN, ENV_ADMIN):
            with self.subTest(stored=stored):
                self.setUp()
                self.add_user(id='u-adm', email=stored, oauth={'google': 'g-adm'})
                self.assert_refused(self.callback('g-adm', stored))
                self.assert_refused(self.callback('g-adm', 'renamed-google@x.com'))   # nhận ra bằng sub, email Google đã đổi

    def test_login_helper_itself_refuses_admin_closed_and_disabled_rows(self):
        rows = [{'id': 'u-a', 'email': ROOT_ADMIN}, {'id': 'u-e', 'email': ' ' + ENV_ADMIN.title() + ' '},
                {'id': 'u-d', 'email': 'gone@x.com', 'is_deleted': True}, {'id': 'u-off', 'email': 'off@x.com', 'is_active': False}]
        for row in rows:
            with self.subTest(row=row['id']):
                DB.reset()
                DB.businesses.insert_one({'id': row['id'], 'name': 'Shop'})
                with FLASK.test_request_context('/auth/google/callback'):
                    resp = oauth_login._login(dict(row), 'google', '/dashboard')
                    self.assertNotIn('user_id', session)
                    self.assertEqual(resp.status_code, 302)
                    self.assertTrue(resp.headers['Location'].endswith('/login'))

    def test_deleted_and_disabled_linked_accounts_get_no_session(self):
        self.add_user(id='u-off', email='off@x.com', is_active=False, oauth={'google': 'g-off'})
        self.add_user(id='u-del', email='deleted_u-del_del@x.com', is_deleted=True, oauth={'google': 'g-del'})
        self.assert_refused(self.callback('g-off', 'off@x.com'))
        r = self.callback('g-del', 'del@x.com')
        self.assertIsNone(self.sess().get('user_id'))
        self.assertTrue(r.headers['Location'].endswith('/auth/complete'))   # chỉ có thể đăng ký tài khoản MỚI (cần mã kích hoạt)

    def test_unicode_case_folding_lookalike_is_not_linked(self):
        """'ſ' (U+017F) khớp 's' trong regex không phân biệt hoa/thường của Mongo, nhưng không phải cùng 1 email."""
        self.add_user(id='u-john', email='johnsmith@gmail.com')
        DB.license_codes.insert_one({'license_key': 'LIC-L', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'nail'})
        lookalike = 'johnſmith@gmail.com'
        r = self.callback('g-evil', lookalike)
        self.assertIsNone(self.sess().get('user_id'))
        self.assertNotIn('oauth', self.user('u-john'))
        self.assertTrue(r.headers['Location'].endswith('/auth/complete'))
        r = self.c.post('/auth/complete', data={'license_key': 'LIC-L', 'business_name': 'Evil', 'business_type': 'nail'})
        self.assertEqual(r.status_code, 400)                                    # "đã có tài khoản với email này"
        self.assertEqual(DB.license_codes.find_one({'license_key': 'LIC-L'})['trang_thai'], 'Sẵn sàng')
        self.assertEqual(len(DB.users.docs), 1)

    def test_existing_users_still_sign_in_with_google(self):
        self.add_user(id='u-own', email='Owner@Shop.com')
        r = self.callback('g-own', 'owner@shop.com')                            # liên kết theo email trùng (hoa/thường)
        self.assertEqual((r.status_code, r.headers['Location']), (302, '/'))
        self.assertEqual(self.sess().get('user_id'), 'u-own')
        self.assertEqual(self.user('u-own')['oauth']['google'], 'g-own')
        with self.c.session_transaction() as s:
            s.clear()
        self.callback('g-own', 'owner@shop.com')                                 # lần sau: nhận ra bằng liên kết
        self.assertEqual(self.sess().get('user_id'), 'u-own')
        self.add_user(id='u-staff', email='staff@shop.com', business_id='u-own', role='staff', oauth={'google': 'g-staff'})
        with self.c.session_transaction() as s:
            s.clear()
        self.callback('g-staff', 'staff@shop.com')
        s = self.sess()
        self.assertEqual((s.get('user_id'), s.get('business_id'), s.get('role')), ('u-staff', 'u-own', 'staff'))


# ================================================================ 1b. /auth/complete
class OAuthCompleteTests(_Base):
    def pend(self, email):
        with self.c.session_transaction() as s:
            s['oauth_signup'] = {'provider': 'google', 'sub': 'g-new', 'email': email, 'name': 'New Owner', 'ts': int(time.time())}

    def test_admin_email_is_refused_before_the_activation_code_is_used(self):
        for email in (ROOT_ADMIN, ENV_ADMIN, ENV_ADMIN.upper()):
            for method in ('GET', 'POST'):
                with self.subTest(email=email, method=method):
                    self.setUp()
                    DB.license_codes.insert_one({'license_key': 'LIC-9', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'nail'})
                    self.pend(email)
                    if method == 'GET':
                        r = self.c.get('/auth/complete')
                    else:
                        r = self.c.post('/auth/complete', data={'license_key': 'LIC-9', 'business_name': 'Evil', 'business_type': 'nail'})
                    self.assert_refused(r)
                    self.assertEqual(DB.license_codes.find_one({'license_key': 'LIC-9'})['trang_thai'], 'Sẵn sàng')
                    self.assertEqual((DB.users.docs, DB.businesses.docs), ([], []))
                    _shield.record_code_failure.assert_not_called()

    def test_signup_records_the_activation_code_industry(self):
        cases = [({'nganh_nghe': 'spa'}, 'nail', 'spa', 'spa'),       # mã 1 ngành: ngành của mã thắng lựa chọn trên form
                 ({'nganh_nghe': 'all'}, 'spa', 'spa', 'all'),         # mã mọi ngành: lựa chọn trên form, license_industry = all
                 ({'nganh_nghe': ' Fnb '}, 'nail', 'fnb', 'fnb'),
                 ({}, 'fnb', 'fnb', 'all')]                            # mã cũ không ghi ngành
        for i, (code, chosen, industry, lic) in enumerate(cases):
            with self.subTest(code=code):
                self.setUp()
                DB.license_codes.insert_one(dict(code, license_key=f'LIC-{i}', trang_thai='Sẵn sàng', plan='pro'))
                self.pend(f'new{i}@shop.test')
                r = self.c.post('/auth/complete', data={'license_key': f'LIC-{i}', 'business_name': 'New Shop', 'business_type': chosen})
                self.assertEqual(r.status_code, 302, r.get_data(as_text=True))
                uid = self.sess().get('user_id')
                biz = DB.businesses.find_one({'id': uid})
                self.assertEqual((biz['industry_code'], biz.get('license_industry'), biz['plan']), (industry, lic, 'pro'))
                self.assertEqual(DB.license_codes.find_one({'license_key': f'LIC-{i}'})['trang_thai'], 'Đã kích hoạt')


# ================================================================ 2. Đăng xuất mọi nơi
class SignOutEverywhereTests(_Base):
    def test_god_mode_sign_out_everywhere_bumps_the_god_mode_session_version(self):
        for n in (1, 2):
            self.login_as('superadmin-fallback', role='super_admin', email=ROOT_ADMIN)
            APP._SUPERADMIN_VER_CACHE['v'] = (0, time.time())
            r = self.c.post('/api/account/logout_all')
            self.assertEqual(r.status_code, 200, r.get_json())
            self.assertTrue(r.get_json()['success'])
            self.assertEqual(DB.system_settings.find_one({'key': 'superadmin_session_ver'})['value'], n)
            self.assertEqual(APP._SUPERADMIN_VER_CACHE, {})                      # mọi phiên God Mode khác kiểm lại ngay
            self.assertNotIn('user_id', self.sess())
        self.assertEqual(DB.users.docs, [])
        self.assertTrue(any(e[0] == 'logout_all' for e in LOG_EVENTS))

    def test_shop_owner_sign_out_everywhere_still_bumps_own_version(self):
        self.add_user(id='u-own', email='owner@shop.com', session_ver=3)
        self.login_as('u-own')
        r = self.c.post('/api/account/logout_all')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.user('u-own')['session_ver'], 4)
        self.assertIsNone(DB.system_settings.find_one({'key': 'superadmin_session_ver'}))
        self.assertNotIn('user_id', self.sess())

    def test_signed_out_request_is_refused(self):
        r = self.c.post('/api/account/logout_all')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(DB.system_settings.docs, [])


# ================================================================ 3a. SĐT gõ trong Messenger/Zalo -> hồ sơ khách
CUSTOMERS = [
    {'id': 7, 'business_id': 'shopA', 'name': 'Jane', 'phone': '0412 345 678', 'fb_psid': 'JANE_PSID'},
    {'id': 8, 'business_id': 'shopA', 'name': 'Kim', 'phone': '0412 999 111'},
    {'id': 9, 'business_id': 'shopA', 'name': 'Lan', 'phone': '0412 777 333'},
    {'id': 10, 'business_id': 'shopA', 'name': 'Lan (old card)', 'phone': '+61 412 777 333'},
    {'id': 11, 'business_id': 'shopB', 'name': 'Kim at shop B', 'phone': '0412999111'},
    {'id': 12, 'business_id': 'shopA', 'name': 'Tom', 'phone': '0412-555-444', 'zalo_user_id': 'Z_TOM'},
    {'id': 13, 'business_id': 'shopA', 'name': 'Ann', 'phone': '0499 000 111', 'fb_psid': 'PSID_ANN'},
    {'id': 14, 'business_id': 'shopA', 'name': 'Bea', 'phone': '0412 888 222', 'fb_psid': ''},
]


def _cust(cid):
    return DB.customers.find_one({'id': cid})


class InboxPhoneLinkTests(_Base):
    def setUp(self):
        super().setUp()
        for c in CUSTOMERS:
            DB.customers.insert_one(c)

    def event(self, user, text, mid, channel='messenger', bid='shopA'):
        doc = {'business_id': bid, 'channel': channel, 'status': 'connected'}
        APP._inbox_handle_event(doc, {'kind': 'customer', 'user_id': user, 'text': text, 'ext_msg_id': mid, 'name': None, 'phone': None})
        return DB.bot_customers.find_one({'id': f'{bid}:{channel}:{user}'})

    def test_unique_customer_without_channel_id_is_linked_automatically(self):
        conv = self.event('PSID_K', 'hi, call me on 0412999111', 'm1')
        self.assertEqual(_cust(8)['fb_psid'], 'PSID_K')
        self.assertNotIn('pending_customer_link', conv)
        self.assertNotIn('fb_psid', _cust(11))                         # cùng SĐT ở tiệm khác: không đụng tới, không tính
        self.assertEqual(conv['phone'], '0412999111')

    def test_zalo_fills_only_the_zalo_field(self):
        conv = self.event('Z_KIM', 'sdt em 0412 999 111 nha', 'z1', channel='zalo')
        self.assertEqual(_cust(8)['zalo_user_id'], 'Z_KIM')
        self.assertNotIn('fb_psid', _cust(8))
        self.assertNotIn('pending_customer_link', conv)

    def test_id_for_another_platform_does_not_block_this_platform(self):
        self.event('PSID_TOM', 'my number is 0412 555 444', 'm2')
        self.assertEqual((_cust(12)['fb_psid'], _cust(12)['zalo_user_id']), ('PSID_TOM', 'Z_TOM'))

    def test_empty_string_channel_id_counts_as_not_linked(self):
        self.event('PSID_BEA', '0412888222', 'm3')
        self.assertEqual(_cust(14)['fb_psid'], 'PSID_BEA')

    def test_existing_channel_id_is_never_replaced(self):
        conv = self.event('ATTACKER_PSID', 'hi, my number is 0412 345 678', 'm4')
        self.assertEqual(_cust(7)['fb_psid'], 'JANE_PSID')
        p = conv['pending_customer_link']
        self.assertEqual((p['customer_id'], p['field'], p['user_id'], p['replaces'], p['customer_name']),
                         (7, 'fb_psid', 'ATTACKER_PSID', True, 'Jane'))
        z = self.event('Z_ATTACKER', '0412 555 444', 'z2', channel='zalo')       # Tom đã có Zalo -> chờ duyệt
        self.assertEqual(_cust(12)['zalo_user_id'], 'Z_TOM')
        self.assertTrue(z['pending_customer_link']['replaces'])

    def test_phone_shared_by_two_customers_stays_pending(self):
        conv = self.event('PSID_LAN', 'its 0412777333', 'm5')
        self.assertNotIn('fb_psid', _cust(9))
        self.assertNotIn('fb_psid', _cust(10))
        p = conv['pending_customer_link']
        self.assertIn(p['customer_id'], (9, 10))
        self.assertEqual((p['matches'], p['replaces']), (2, False))

    def test_channel_id_already_on_another_customer_stays_pending(self):
        conv = self.event('PSID_ANN', 'actually use 0412 999 111', 'm6')        # id Messenger này đã thuộc hồ sơ Ann
        self.assertNotIn('fb_psid', _cust(8))
        self.assertEqual(_cust(13)['fb_psid'], 'PSID_ANN')
        self.assertEqual(conv['pending_customer_link']['customer_id'], 8)

    def test_already_linked_to_this_id_is_a_no_op(self):
        DB.bot_customers.insert_one({'id': 'shopA:messenger:JANE_PSID', 'business_id': 'shopA'})
        self.assertTrue(inbox_channels.link_customer('shopA', 'messenger', 'JANE_PSID', '+61412345678', conversation='shopA:messenger:JANE_PSID'))
        self.assertNotIn('pending_customer_link', DB.bot_customers.find_one({'id': 'shopA:messenger:JANE_PSID'}))

    def test_owner_linking_at_the_same_moment_is_not_overwritten(self):
        """Hồ sơ được gắn id khác ngay sau khi đọc (chủ tiệm duyệt / tin khác tới cùng lúc): lệnh ghi có điều kiện -> chờ duyệt."""
        DB.bot_customers.insert_one({'id': 'shopA:messenger:PSID_RACE', 'business_id': 'shopA'})
        real_find = DB.customers.find

        def find_then_other_writer(*a, **k):
            rows = real_find(*a, **k)
            DB.customers.update_one({'id': 8}, {'$set': {'fb_psid': 'OWNER_SET'}})
            return rows

        with patch.object(DB.customers, 'find', side_effect=find_then_other_writer):
            ok = inbox_channels.link_customer('shopA', 'messenger', 'PSID_RACE', '0412999111', conversation='shopA:messenger:PSID_RACE')
        self.assertFalse(ok)
        self.assertEqual(_cust(8)['fb_psid'], 'OWNER_SET')
        p = DB.bot_customers.find_one({'id': 'shopA:messenger:PSID_RACE'})['pending_customer_link']
        self.assertEqual((p['customer_id'], p['replaces']), (8, True))

    def test_no_match_or_unusable_phone_changes_nothing(self):
        before = copy.deepcopy(DB.customers.docs)
        conv = self.event('PSID_X', 'call 0400 000 000', 'm7')
        self.assertNotIn('pending_customer_link', conv)
        self.assertFalse(inbox_channels.link_customer('shopA', 'messenger', 'PSID_X', '1234', conversation='shopA:messenger:PSID_X'))
        self.assertFalse(inbox_channels.link_customer('shopA', 'web', 'PSID_X', '0412999111'))
        self.assertEqual(DB.customers.docs, before)

    def test_platform_name_loses_angle_brackets_but_keeps_the_rest(self):
        cid = inbox_channels.record('shopA', 'messenger', 'PSID_N', 'hi <3', 'customer', name='<img src=x onerror=alert(1)>Mai')
        conv = DB.bot_customers.find_one({'id': cid})
        self.assertEqual(conv['full_name'], 'img src=x onerror=alert(1)Mai')
        self.assertEqual(DB.bot_messages.find_one({'customer_id': cid})['content'], 'hi <3')   # nội dung tin giữ nguyên
        cid = inbox_channels.record('shopA', 'zalo', 'Z_VN', 'chào', 'customer', name='Nguyễn Thị Hồng')
        self.assertEqual(DB.bot_customers.find_one({'id': cid})['full_name'], 'Nguyễn Thị Hồng')
        cid = inbox_channels.record('shopA', 'messenger', 'PSID_9876', 'x', 'customer', name='<>')
        self.assertEqual(DB.bot_customers.find_one({'id': cid})['full_name'], 'Client · Messenger 9876')

    def test_second_number_in_the_same_conversation_links_nothing(self):
        self.event('PSID_Z', 'my number 0412 000 222', 'm8')                      # không khớp ai, nhưng hội thoại đã có SĐT
        conv = self.event('PSID_Z', 'actually 0412 999 111', 'm9')
        self.assertNotIn('fb_psid', _cust(8))
        self.assertNotIn('pending_customer_link', conv)


# ================================================================ 3b. POST /api/bot/customer_link
class CustomerLinkRouteTests(_Base):
    CONV = 'shopA:messenger:ATTACKER_PSID'

    def setUp(self):
        super().setUp()
        for c in CUSTOMERS:
            DB.customers.insert_one(c)
        APP._inbox_handle_event({'business_id': 'shopA', 'channel': 'messenger'},
                                {'kind': 'customer', 'user_id': 'ATTACKER_PSID', 'text': 'my number is 0412 345 678',
                                 'ext_msg_id': 'm1', 'name': None, 'phone': None})
        self.assertIn('pending_customer_link', DB.bot_customers.find_one({'id': self.CONV}))

    def post(self, body):
        return self.c.post('/api/bot/customer_link', json=body)

    def pending(self):
        return DB.bot_customers.find_one({'id': self.CONV}).get('pending_customer_link')

    def test_route_is_owner_admin_only(self):
        self.assertIn("role_required('admin', 'super_admin')", DECORATORS['api_bot_customer_link'])
        self.assertIn('login_required', DECORATORS['api_bot_customer_link'])

    def test_owner_confirms_the_pending_link(self):
        self.login_as('owner-a', bid='shopA')
        r = self.post({'customer_id': self.CONV, 'confirm': True})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(_cust(7)['fb_psid'], 'ATTACKER_PSID')
        self.assertIsNone(self.pending())
        self.assertEqual(self.post({'customer_id': self.CONV, 'confirm': True}).status_code, 404)   # đã xử lý xong

    def test_owner_dismisses_the_pending_link(self):
        self.login_as('owner-a', bid='shopA')
        for body in ({'customer_id': self.CONV, 'confirm': False},):
            self.assertEqual(self.post(body).status_code, 200)
        self.assertEqual(_cust(7)['fb_psid'], 'JANE_PSID')
        self.assertIsNone(self.pending())

    def test_non_boolean_confirm_never_links(self):
        self.login_as('owner-a', bid='shopA')
        self.assertEqual(self.post({'customer_id': self.CONV, 'confirm': 'true'}).status_code, 200)
        self.assertEqual(_cust(7)['fb_psid'], 'JANE_PSID')

    def test_staff_other_shop_operator_and_anonymous_are_refused(self):
        self.assertEqual(self.post({'customer_id': self.CONV, 'confirm': True}).status_code, 401)
        self.login_as('staff-a', role='staff', bid='shopA')
        self.assertEqual(self.post({'customer_id': self.CONV, 'confirm': True}).status_code, 403)
        self.login_as('owner-b', bid='shopB')
        self.assertEqual(self.post({'customer_id': self.CONV, 'confirm': True}).status_code, 403)
        self.login_as('owner-a', bid='shopA')
        self.assertEqual(self.post({'customer_id': {'$ne': None}, 'confirm': True}).status_code, 403)
        self.assertEqual(self.post(['not', 'a', 'dict']).status_code, 403)
        self.assertEqual(_cust(7)['fb_psid'], 'JANE_PSID')
        self.assertIsNotNone(self.pending())


# ================================================================ 3c. ai_bot.html: thanh "liên kết chờ duyệt"
def _js_between(src, start_marker, end_marker):
    a = src.index(start_marker)
    return src[a:src.index(end_marker, a)]


def _render_ai_bot(role, lang='en'):
    from jinja2 import ChainableUndefined, ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape
    loader = ChoiceLoader([DictLoader({'components/app_sidebar.html': '<nav id="app-sidebar"></nav>'}),
                           FileSystemLoader(os.path.join(ROOT, 'templates'))])
    env = Environment(loader=loader, autoescape=select_autoescape(['html']), undefined=ChainableUndefined)
    url_for_ = lambda endpoint, **kw: ('/static/' + kw['filename']) if endpoint == 'static' else '/' + endpoint  # noqa: E731
    return env.get_template('ai_bot.html').render(
        url_for=url_for_, asset_v=lambda p: 'test', session={'role': role, 'business_id': 'biz1'}, default_lang=lang,
        active_industry_code='nail', tenant_currency='AUD', tenant_country='AU', menu_i18n={}, sales_demo=False,
        is_vn_shop=(lang == 'vi'), copilot_enabled=True, profile={'has_profile': True, 'name': 'Lotus Nails'})


_UI_HARNESS = r"""
const bar = { innerHTML: '', hidden: true, classList: {
    add(c) { if (c === 'hidden') bar.hidden = true; },
    remove(c) { if (c === 'hidden') bar.hidden = false; },
    toggle(c, force) { if (c === 'hidden') bar.hidden = force === undefined ? !bar.hidden : !!force; } } };
let HAS_BAR = true;
globalThis.document = { getElementById: (id) => (id === 'pendingLinkBar' && HAS_BAR ? bar : null) };
globalThis.window = globalThis;
const CALLS = [], TOASTS = [];
let API_FAIL = false;
async function hrApi(path, opts) {
    CALLS.push({ path, method: opts && opts.method, body: opts && opts.body ? JSON.parse(opts.body) : null });
    if (API_FAIL) throw new Error('<b>server said no</b>');
    return { success: true };
}
function showToast(message, type) { TOASTS.push([message, type]); }
let LANG = 'en';
function cpLang() { return LANG; }
let CP_OWNER = true;
const CH = { messenger: { label: 'Messenger' }, zalo: { label: 'Zalo' }, web: { label: 'Website' } };
let currentCustomerId = 'shopA:messenger:P1';
const XSS = '<img src=x onerror=alert(1)>';
let allCustomers = [
    { id: 'shopA:messenger:P1', channel: 'messenger', full_name: 'Visitor',
      pending_customer_link: { customer_id: 7, customer_name: XSS + ' $& $1', phone: '<svg onload=alert(2)>0412', channel: 'messenger',
                               field: 'fb_psid', user_id: 'P1', replaces: true, matches: 2 } },
    { id: 'shopA:zalo:Z1', channel: 'zalo', pending_customer_link: { customer_id: 9, phone: '0412 777 333', channel: 'zalo', replaces: false } },
    { id: 'shopA:messenger:P2', channel: 'messenger' },
    { id: 'mock-1', pending_customer_link: { customer_id: 1, phone: '1' } },
];
//__ESCAPE__
//__BLOCK__
(async () => {
    const out = {};
    const snap = () => ({ html: bar.innerHTML, hidden: bar.hidden });
    renderPendingLink(allCustomers[0]); out.en = snap();
    LANG = 'vi'; renderPendingLink(allCustomers[0]); out.vi = snap(); LANG = 'en';
    renderPendingLink(allCustomers[1]); out.zalo = snap();
    renderPendingLink(allCustomers[2]); out.none = snap();
    renderPendingLink(allCustomers[3]); out.mock = snap();
    renderPendingLink(null); out.nullc = snap();
    CP_OWNER = false; renderPendingLink(allCustomers[0]); out.staff = snap(); CP_OWNER = true;
    HAS_BAR = false; renderPendingLink(allCustomers[0]); HAS_BAR = true; out.nobar = 'ok';
    API_FAIL = true; renderPendingLink(allCustomers[0]); await resolvePendingLink(true); out.failed = snap();
    out.failToast = TOASTS.slice(); API_FAIL = false;
    CALLS.length = 0; TOASTS.length = 0;
    renderPendingLink(allCustomers[0]);
    await Promise.all([resolvePendingLink(true), resolvePendingLink(true)]); out.confirmed = snap();   // bấm 2 lần = 1 lệnh
    out.confirmCalls = CALLS.slice(); out.confirmToast = TOASTS.slice();
    out.localCleared = !('pending_customer_link' in allCustomers[0]);
    CALLS.length = 0;
    renderPendingLink(allCustomers[1]); currentCustomerId = 'shopA:messenger:P2'; await resolvePendingLink(false); out.dismissed = snap();
    out.dismissCalls = CALLS.slice();
    CALLS.length = 0; await resolvePendingLink(true); out.noTargetCalls = CALLS.slice();
    process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""


class PendingLinkBannerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read('templates/ai_bot.html')

    def run_harness(self):
        s = self.src
        esc = _js_between(s, 'function escapeHtml(str) {', '// Escape rồi mới đổi')
        block = _js_between(s, '// ====== h4b: liên kết chờ duyệt', '// ====== h4b end')
        js = _UI_HARNESS.replace('//__ESCAPE__', esc).replace('//__BLOCK__', block)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'banner.js')
            with io.open(p, 'w', encoding='utf-8') as f:
                f.write(js)
            r = subprocess.run(['node', p], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return json.loads(r.stdout)

    def test_banner_escapes_text_and_shows_both_languages(self):
        out = self.run_harness()
        en, vi = out['en'], out['vi']
        self.assertFalse(en['hidden'])
        for html in (en['html'], vi['html']):
            for bad in ('<img', '<svg', '<b>server'):
                self.assertNotIn(bad, html)
            self.assertIn('&lt;img src=x onerror=alert(1)&gt; $&amp; $1', html)   # chữ giữ nguyên (không bị diễn giải $&)
            self.assertIn('&lt;svg onload=alert(2)&gt;0412', html)
            self.assertIn('resolvePendingLink(true)', html)
            self.assertIn('resolvePendingLink(false)', html)
        self.assertIn('Confirm', en['html'])
        self.assertIn('Dismiss', en['html'])
        self.assertIn('Messenger', en['html'])           # "đã gắn 1 tài khoản Messenger khác" (replaces)
        self.assertRegex(en['html'], r'\b2 profiles\b')   # nhiều hồ sơ cùng SĐT
        self.assertIn('Xác nhận', vi['html'])
        self.assertIn('Bỏ qua', vi['html'])
        self.assertIn('#9', out['zalo']['html'])          # liên kết chờ duyệt cũ (chưa có tên khách) vẫn hiện được
        self.assertNotIn('Zalo account', out['zalo']['html'])

    def test_banner_hidden_without_pending_link_or_for_staff(self):
        out = self.run_harness()
        for k in ('none', 'mock', 'nullc', 'staff'):
            with self.subTest(case=k):
                self.assertTrue(out[k]['hidden'])
                self.assertEqual(out[k]['html'], '')
        self.assertEqual(out['nobar'], 'ok')

    def test_buttons_post_to_customer_link_for_the_conversation_shown(self):
        out = self.run_harness()
        self.assertEqual(out['confirmCalls'], [{'path': '/api/bot/customer_link', 'method': 'POST',
                                                 'body': {'customer_id': 'shopA:messenger:P1', 'confirm': True}}])
        self.assertTrue(out['confirmed']['hidden'])
        self.assertTrue(out['localCleared'])
        self.assertEqual(out['confirmToast'][0][1], 'success')
        # conversation đổi giữa chừng: vẫn gửi đúng hội thoại có thanh đang hiện
        self.assertEqual(out['dismissCalls'], [{'path': '/api/bot/customer_link', 'method': 'POST',
                                                 'body': {'customer_id': 'shopA:zalo:Z1', 'confirm': False}}])
        self.assertEqual(out['noTargetCalls'], [])
        # lỗi server: thanh vẫn còn, toast không chèn chữ của server
        self.assertFalse(out['failed']['hidden'])
        self.assertEqual(out['failToast'][0][1], 'error')
        self.assertNotIn('server said no', out['failToast'][0][0])

    def test_banner_markup_only_for_owner_and_admin(self):
        for role, shown in (('admin', True), ('super_admin', True), ('staff', False)):
            with self.subTest(role=role):
                html = _render_ai_bot(role)
                self.assertEqual('id="pendingLinkBar"' in html, shown)
        html = _render_ai_bot('admin')
        header = html.index('id="copilotChatHeader"')
        self.assertTrue(header < html.index('id="pendingLinkBar"') < html.index('id="aiClosingAlert"'))

    def test_selecting_or_refreshing_a_conversation_renders_the_banner(self):
        s = self.src
        select = _js_between(s, 'async function onSelectCustomer(customer) {', 'async function loadMessages(')
        self.assertIn('renderPendingLink(customer);', select)
        fetch = _js_between(s, 'async function fetchCustomers() {', 'function renderEmptyState() {')
        self.assertIn('renderPendingLink(allCustomers.find(c => c.id === currentCustomerId) || null);', fetch)
        block = _js_between(s, '// ====== h4b: liên kết chờ duyệt', '// ====== h4b end')
        self.assertNotIn('fetch(', block.replace('hrApi(', ''))   # đi qua hrApi -> fetch được bootstrap CSRF gắn X-CSRFToken

    def test_template_scripts_still_parse(self):
        for role in ('admin', 'staff'):
            for lang in ('en', 'vi'):
                html = _render_ai_bot(role, lang)
                for i, m in enumerate(re.finditer(r'<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>(.*?)</script>', html, re.S)):
                    with tempfile.TemporaryDirectory() as d:
                        p = os.path.join(d, f's{i}.js')
                        with io.open(p, 'w', encoding='utf-8') as f:
                            f.write(m.group(1))
                        r = subprocess.run(['node', '--check', p], capture_output=True, text=True, encoding='utf-8')
                    self.assertEqual(r.returncode, 0, f'{role}/{lang} script #{i}: {r.stderr[-400:]}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
