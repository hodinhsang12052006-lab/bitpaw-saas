# -*- coding: utf-8 -*-
"""Test OFFLINE bảo mật h1b (đăng nhập Google/Facebook + /api/test-email):
1. OAuth khớp tài khoản theo email: NGUYÊN CHUỖI, không phân biệt hoa/thường, ký tự regex ('+', '|', '*', '(') không còn tác dụng
   ('johns+mith@outlook.com' không được liên kết vào tài khoản 'johnsmith@outlook.com'). Email trùng thật vẫn liên kết như cũ.
2. _safe_next: chặn mọi giá trị trình duyệt có thể hiểu là trang khác ('/<TAB>/evil', '//evil', '/\\evil', 'https://evil'...),
   cả ở /auth/<provider>/start lẫn lúc chuyển hướng sau đăng nhập (giá trị cũ còn trong session).
3. Tài khoản đã xoá / bị khoá (is_active=False) / thuộc tiệm đã xoá: OAuth không liên kết, không mở lại, không đăng nhập;
   người đã xoá tài khoản vẫn đăng ký lại được tài khoản MỚI bằng đúng Google đó.
4. Đăng ký qua OAuth từ chối email quản trị BitPaw (SUPERADMIN_ROOT_EMAIL + SUPERADMIN_EMAILS) — cả ở callback lẫn /auth/complete.
5. /api/test-email: không đăng nhập -> 401, không phải Super Admin -> 403, Super Admin -> chỉ gửi mẫu CỐ ĐỊNH về đúng email
   của chính mình (bỏ qua người nhận/tiêu đề/HTML người gọi gửi), lỗi SMTP không lộ ra client, tối đa 3 lần/giờ.

KHÔNG import app.py (module 'app' giả, nhưng các hàm kiểm quyền _is_authorized_superadmin_email/_is_superadmin/login_required
lấy NGUYÊN VĂN từ app.py qua AST), KHÔNG mở MongoDB (mongo_client bị stub trước mọi import), KHÔNG gọi mạng / SMTP thật,
KHÔNG chạy server. Chạy: PYTHONIOENCODING=utf-8 python scripts/tests/test_security_h1b-oauth-email.py
"""
import ast
import copy
import io
import os
import re
import sys
import time
import types
import unittest
from functools import wraps
from urllib.parse import urlsplit
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)


def _no_network(*a, **kw):
    raise AssertionError('network disabled in offline tests')


patch('requests.sessions.Session.request', _no_network).start()

# ---------------------------------------------------------------- Mongo giả (chỉ những gì oauth_login dùng)
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


def _match(doc, flt):
    for key, cond in (flt or {}).items():
        val = _get(doc, key)
        if isinstance(cond, dict) and any(str(k).startswith('$') for k in cond):
            for op, arg in cond.items():
                if op == '$options':
                    continue
                if op == '$regex':   # Mongo dùng PCRE; với các mẫu ở đây Python re cho cùng kết quả
                    flags = re.IGNORECASE if 'i' in cond.get('$options', '') else 0
                    if not isinstance(val, str) or not re.search(arg, val, flags):
                        return False
                elif op == '$ne':
                    if val is not _MISSING and val == arg:
                        return False
                else:
                    raise AssertionError(f'FakeDB: unsupported operator {op}')
        elif val is _MISSING or val != cond:
            return False
    return True


class FakeCollection:
    def __init__(self):
        self.docs = []

    def find_one(self, flt=None, projection=None):
        for d in self.docs:
            if _match(d, flt):
                return copy.deepcopy(d)
        return None

    def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))
        return types.SimpleNamespace(inserted_id=len(self.docs))

    def update_one(self, flt, upd, upsert=False):
        for d in self.docs:
            if _match(d, flt):
                for k, v in (upd.get('$set') or {}).items():
                    _set(d, k, v)
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            doc = {k: v for k, v in flt.items() if not isinstance(v, dict)}
            for k, v in (upd.get('$set') or {}).items():
                _set(doc, k, v)
            self.docs.append(doc)
        return types.SimpleNamespace(matched_count=0, modified_count=0)


class FakeDB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self._c.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return getattr(self, name)

    def reset(self):
        self._c.clear()


DB = FakeDB()
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: 1, MONGO_STATUS='CONNECTED')

_shield = types.ModuleType('security_shield')
_shield.client_ip = lambda req: '203.0.113.9'
_shield.code_attempts_blocked = lambda ip: False
_shield.record_code_failure = lambda ip, key: None
sys.modules['security_shield'] = _shield

SEND = MagicMock(name='EmailService.send_email', return_value=(True, 'ok'))
_es = types.ModuleType('email_service')
_es.EmailService = type('EmailService', (), {'send_email': staticmethod(lambda *a, **k: SEND(*a, **k))})
sys.modules['email_service'] = _es

from flask import Flask, flash, jsonify, redirect, request, session, url_for  # noqa: E402
from flask_limiter import Limiter  # noqa: E402

# ---------------------------------------------------------------- module 'app' giả, hàm kiểm quyền lấy NGUYÊN VĂN từ app.py
with io.open(os.path.join(ROOT, 'app.py'), encoding='utf-8') as _fh:
    APP_SRC = _fh.read()
_TREE = ast.parse(APP_SRC)


def _segment(pred):
    node = next(n for n in _TREE.body if pred(n))
    return ast.get_source_segment(APP_SRC, node)


FLASK = Flask(__name__)
FLASK.secret_key = 'h1b-offline-test-only'
FLASK.config['TESTING'] = True
LIMITER = Limiter(lambda: request.remote_addr or '127.0.0.1', app=FLASK, storage_uri='memory://', default_limits=[])


@FLASK.route('/login')
def login():
    return 'login page'


@FLASK.route('/')
def index():
    return 'home'


_fake_app = types.ModuleType('app')
_fake_app.__dict__.update(os=os, session=session, jsonify=jsonify, flash=flash, redirect=redirect, url_for=url_for, wraps=wraps,
                          _wants_json=lambda: True, _vi_en=lambda vi, en: en)
for _name in ('_is_authorized_superadmin_email', '_is_superadmin', 'login_required'):
    exec(_segment(lambda n, nm=_name: isinstance(n, ast.FunctionDef) and n.name == nm), _fake_app.__dict__)
exec(_segment(lambda n: isinstance(n, ast.Assign) and any(getattr(t, 'id', None) == 'SUPERADMIN_ROOT_EMAIL' for t in n.targets)),
     _fake_app.__dict__)
_fake_app._ensure_primary_membership = lambda *a, **k: None
_fake_app._get_real_client_ip = lambda: '203.0.113.9'
_fake_app.INDUSTRY_CONFIG = {'nail': {}, 'spa': {}}
_fake_app._send_welcome_email = MagicMock(name='_send_welcome_email')
_fake_app.csrf = types.SimpleNamespace(protect=lambda: None)
_fake_app.limiter = LIMITER
sys.modules['app'] = _fake_app
ROOT_ADMIN = _fake_app.SUPERADMIN_ROOT_EMAIL
ENV_ADMIN = 'ops-admin@bitpaw.test'

os.environ.update(GOOGLE_CLIENT_ID='test-client-id', GOOGLE_CLIENT_SECRET='test-client-secret', SUPERADMIN_EMAILS=ENV_ADMIN)
for _k in ('OAUTH_TEST_BASE', 'PUBLIC_BASE_URL', 'FACEBOOK_APP_ID', 'FACEBOOK_APP_SECRET'):
    os.environ.pop(_k, None)

import oauth_login  # noqa: E402
import email_test_api  # noqa: E402

oauth_login.render_template = lambda name, **ctx: f"TEMPLATE {name} | {ctx.get('error') or ''}"
FLASK.register_blueprint(oauth_login.oauth_bp)
FLASK.register_blueprint(email_test_api.email_test_bp)


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
        SEND.reset_mock()
        SEND.return_value = (True, 'ok')
        SEND.side_effect = None
        LIMITER.reset()
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

    def callback(self, sub, email, verified=True, nxt=None, provider='google'):
        with self.c.session_transaction() as s:
            s['oauth'] = {'provider': provider, 'state': 'st-1', 'verifier': 'v', 'nonce': 'n', 'ts': int(time.time()), 'next': nxt}
        info = {'sub': sub, 'email': email, 'email_verified': verified, 'name': 'Test Person'}
        with patch.object(oauth_login.requests, 'post', return_value=_Resp({'access_token': 'at-1'})), \
                patch.object(oauth_login.requests, 'get', return_value=_Resp(info)):
            return self.c.get(f'/auth/{provider}/callback?state=st-1&code=code-1')

    def sess(self):
        with self.c.session_transaction() as s:
            return dict(s)


# ================================================================ 1. exact email match
class OAuthEmailMatchTests(_Base):
    def test_regex_metacharacters_in_provider_email_never_link_someone_else(self):
        cases = [('johns+mith@outlook.com', 'johnsmith@outlook.com'),   # '+' = "1 hoặc nhiều 's'"
                 ('nailsalo+nsydney@gmail.com', 'nailsalonsydney@gmail.com'),
                 ('owner|x@evil.com', 'owner@shop.com'),                # '|' = khớp tiền tố 'owner'
                 ('own*er@shop.com', 'owner@shop.com'),
                 ('o(w)ner@shop.com', 'owner@shop.com'),
                 ('own?er@shop.com', 'owner@shop.com')]
        for attacker, victim in cases:
            with self.subTest(attacker=attacker):
                self.setUp()
                self.add_user(id='u-victim', email=victim)
                r = self.callback('g-attacker', attacker)
                s = self.sess()
                self.assertNotEqual(s.get('user_id'), 'u-victim')
                self.assertNotIn('oauth', self.user('u-victim'))          # không ghi liên kết vào tài khoản nạn nhân
                self.assertEqual(r.status_code, 302)
                self.assertTrue(r.headers['Location'].endswith('/auth/complete'), r.headers['Location'])
                self.assertEqual(s['oauth_signup']['email'], attacker)     # người lạ -> trang đăng ký (cần mã kích hoạt)

    def test_exact_email_still_links_case_insensitively(self):
        self.add_user(id='u-john', email='John.Smith@Gmail.com')        # tài khoản cũ lưu email đúng như gõ
        r = self.callback('g-john', 'john.smith@gmail.com')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sess().get('user_id'), 'u-john')
        self.assertEqual(self.user('u-john')['oauth']['google'], 'g-john')

    def test_dot_is_still_literal(self):
        self.add_user(id='u-john', email='john.smith@gmail.com')
        self.callback('g-x', 'johnxsmith@gmail.com')
        self.assertIsNone(self.sess().get('user_id'))
        self.assertNotIn('oauth', self.user('u-john'))

    def test_already_linked_account_logs_in(self):
        self.add_user(id='u-linked', email='linked@shop.com', oauth={'google': 'g-linked'})
        r = self.callback('g-linked', 'linked@shop.com')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sess().get('user_id'), 'u-linked')
        self.assertEqual(r.headers['Location'], '/')

    def test_unverified_email_is_not_linked(self):
        self.add_user(id='u-1', email='a@shop.com')
        self.callback('g-1', 'a@shop.com', verified=False)
        self.assertIsNone(self.sess().get('user_id'))
        self.assertNotIn('oauth', self.user('u-1'))


# ================================================================ 2. _safe_next
class SafeNextTests(_Base):
    REJECT = ['/\t/evil.example', '/\n/evil.example', '/\r/evil.example', '/\t\t/evil.example', '\t//evil.example',
              '//evil.example', '///evil.example', '/\\evil.example', '\\/evil.example', '/x\\y', '/\\/evil.example',
              'https://evil.example', 'http:/evil.example', 'javascript:alert(1)', 'evil.example', ' /dashboard',
              '/ /evil.example', '/\x00/evil.example', '/\x0b/evil.example', '/\x7f', '/\x85/evil.example', '', None]
    ALLOW = ['/', '/dashboard', '/nail/turns?tab=today&x=%2F', '/a/b#frag', '/%09/evil.example']

    def test_rejects_anything_a_browser_could_treat_as_another_origin(self):
        for nxt in self.REJECT:
            with self.subTest(nxt=nxt):
                self.assertIsNone(oauth_login._safe_next(nxt))

    def test_allows_plain_local_paths(self):
        for nxt in self.ALLOW:
            with self.subTest(nxt=nxt):
                self.assertEqual(oauth_login._safe_next(nxt), nxt)

    def test_start_does_not_store_tab_trick(self):
        r = self.c.get('/auth/google/start?next=/%09/evil.example')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].startswith('https://accounts.google.com/'))
        self.assertIsNone(self.sess()['oauth']['next'])
        self.c.get('/auth/google/start?next=/nail/turns')
        self.assertEqual(self.sess()['oauth']['next'], '/nail/turns')

    def _assert_local(self, loc):
        cleaned = re.sub(r'[\t\n\r]', '', loc).replace('\\', '/')
        self.assertFalse(cleaned.startswith('//'), loc)
        self.assertEqual(urlsplit(cleaned).netloc, '', loc)

    def test_stale_session_next_is_rechecked_before_redirect(self):
        self.add_user(id='u-linked', email='linked@shop.com', oauth={'google': 'g-linked'})
        for bad in ('/\t/evil.example', '//evil.example', '/\\evil.example'):
            with self.subTest(bad=bad):
                r = self.callback('g-linked', 'linked@shop.com', nxt=bad)
                self.assertEqual(r.status_code, 302)
                self._assert_local(r.headers['Location'])
                self.assertEqual(r.headers['Location'], '/')

    def test_legit_next_is_kept(self):
        self.add_user(id='u-linked', email='linked@shop.com', oauth={'google': 'g-linked'})
        r = self.callback('g-linked', 'linked@shop.com', nxt='/nail/turns')
        self.assertEqual(r.headers['Location'], '/nail/turns')


# ================================================================ 3. deleted / disabled accounts
class ClosedAccountTests(_Base):
    def _deleted_owner(self, uid='u-del', email='ann@x.com', sub='g-ann'):
        # đúng như api_delete_account(): is_deleted + đổi email + tiệm is_deleted, liên kết oauth cũ vẫn còn trên bản ghi
        self.add_user(id=uid, email=f'deleted_{uid}_{email}', is_deleted=True, deleted_at='2026-10-01T00:00:00', oauth={'google': sub})
        DB.businesses.update_one({'id': uid}, {'$set': {'is_deleted': True}})

    def test_deleted_account_is_not_revived_by_its_old_google_link(self):
        self._deleted_owner()
        r = self.callback('g-ann', 'ann@x.com')
        s = self.sess()
        self.assertNotEqual(s.get('user_id'), 'u-del')
        self.assertIsNone(s.get('user_id'))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].endswith('/auth/complete'))   # chỉ có thể đăng ký tài khoản MỚI (cần mã kích hoạt)

    def test_deleted_owner_can_sign_up_again_and_lands_in_the_new_account(self):
        self._deleted_owner()
        DB.license_codes.insert_one({'license_key': 'LIC-1', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'nail'})
        self.callback('g-ann', 'ann@x.com')
        r = self.c.post('/auth/complete', data={'license_key': 'LIC-1', 'business_name': 'Ann Nails', 'business_type': 'nail'})
        self.assertEqual(r.status_code, 302)
        new_id = self.sess().get('user_id')
        self.assertTrue(new_id and new_id != 'u-del')
        self.c.get('/login')
        with self.c.session_transaction() as s:
            s.clear()
        self.callback('g-ann', 'ann@x.com')
        self.assertEqual(self.sess().get('user_id'), new_id)

    def test_deleted_record_with_original_email_is_not_linked(self):
        self.add_user(id='u-del2', email='bob@x.com', is_deleted=True)
        self.callback('g-bob', 'bob@x.com')
        self.assertIsNone(self.sess().get('user_id'))
        self.assertNotIn('oauth', self.user('u-del2'))

    def test_disabled_linked_account_cannot_log_in(self):
        self.add_user(id='u-off', email='off@x.com', is_active=False, oauth={'google': 'g-off'})
        r = self.callback('g-off', 'off@x.com')
        self.assertIsNone(self.sess().get('user_id'))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].endswith('/login'))

    def test_disabled_account_is_not_linked_by_email(self):
        self.add_user(id='u-off2', email='off2@x.com', is_active=False)
        self.callback('g-off2', 'off2@x.com')
        self.assertIsNone(self.sess().get('user_id'))
        self.assertNotIn('oauth', self.user('u-off2'))

    def test_staff_of_deleted_business_cannot_log_in(self):
        DB.businesses.insert_one({'id': 'biz-gone', 'is_deleted': True})
        self.add_user(id='u-staff', email='staff@x.com', business_id='biz-gone', role='staff', oauth={'google': 'g-staff'})
        self.callback('g-staff', 'staff@x.com')
        self.assertIsNone(self.sess().get('user_id'))

    def test_active_staff_still_logs_in(self):
        self.add_user(id='u-owner', email='owner@x.com')
        self.add_user(id='u-staff', email='staff@x.com', business_id='u-owner', role='staff', oauth={'google': 'g-staff'})
        self.callback('g-staff', 'staff@x.com')
        s = self.sess()
        self.assertEqual((s.get('user_id'), s.get('business_id'), s.get('role')), ('u-staff', 'u-owner', 'staff'))


# ================================================================ 4. no OAuth signup for BitPaw admin emails
class SuperAdminSignupTests(_Base):
    def test_callback_refuses_signup_for_admin_emails(self):
        for email in (ROOT_ADMIN, ENV_ADMIN, ENV_ADMIN.title()):
            with self.subTest(email=email):
                self.setUp()
                r = self.callback('g-new', email)
                s = self.sess()
                self.assertNotIn('oauth_signup', s)
                self.assertIsNone(s.get('user_id'))
                self.assertEqual(r.status_code, 302)
                self.assertTrue(r.headers['Location'].endswith('/login'))

    def test_complete_refuses_admin_email_even_with_a_valid_code(self):
        for email in (ROOT_ADMIN, ENV_ADMIN):
            with self.subTest(email=email):
                self.setUp()
                DB.license_codes.insert_one({'license_key': 'LIC-9', 'trang_thai': 'Sẵn sàng'})
                with self.c.session_transaction() as s:
                    s['oauth_signup'] = {'provider': 'google', 'sub': 'g-new', 'email': email, 'name': 'X', 'ts': int(time.time())}
                r = self.c.post('/auth/complete', data={'license_key': 'LIC-9', 'business_name': 'Evil', 'business_type': 'nail'})
                self.assertEqual(DB.users.docs, [])
                self.assertEqual(DB.license_codes.find_one({'license_key': 'LIC-9'})['trang_thai'], 'Sẵn sàng')
                self.assertIsNone(self.sess().get('user_id'))
                self.assertIn(r.status_code, (302, 400, 403))

    def test_normal_signup_still_works(self):
        DB.license_codes.insert_one({'license_key': 'LIC-2', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'all'})
        r = self.callback('g-shop', 'newshop@x.com')
        self.assertTrue(r.headers['Location'].endswith('/auth/complete'))
        self.assertTrue(self.c.get('/auth/complete').get_data(as_text=True).startswith('TEMPLATE oauth_complete.html'))
        r = self.c.post('/auth/complete', data={'license_key': 'LIC-2', 'business_name': 'New Shop', 'business_type': 'spa'})
        self.assertEqual(r.status_code, 302)
        u = DB.users.find_one({'email': 'newshop@x.com'})
        self.assertEqual(u['oauth'], {'google': 'g-shop'})
        self.assertEqual(self.sess().get('user_id'), u['id'])


# ================================================================ 5. /api/test-email
ATTACK = {'nguoi_nhan': 'victim-owner@shop.com', 'tieu_de': 'BitPaw: verify your account',
          'noi_dung_html': '<a href="https://evil.example/login">Sign in</a>'}


class TestEmailEndpointTests(_Base):
    def login_as(self, email, uid='u-1'):
        with self.c.session_transaction() as s:
            s['user_id'], s['user_email'], s['business_id'], s['role'] = uid, email, uid, 'admin'

    def test_anonymous_cannot_send(self):
        r = self.c.post('/api/test-email', json=ATTACK)
        self.assertEqual(r.status_code, 401)
        SEND.assert_not_called()

    def test_shop_owner_cannot_send(self):
        self.login_as('owner@shop.com')
        r = self.c.post('/api/test-email', json=ATTACK)
        self.assertEqual(r.status_code, 403)
        SEND.assert_not_called()

    def test_superadmin_gets_fixed_template_to_own_address_only(self):
        for admin in (ENV_ADMIN, ROOT_ADMIN):
            with self.subTest(admin=admin):
                self.setUp()
                self.login_as(admin, uid='superadmin-fallback')
                r = self.c.post('/api/test-email', json=ATTACK)
                self.assertEqual(r.status_code, 200)
                SEND.assert_called_once()
                to, subject, html = SEND.call_args.args
                self.assertEqual(to, admin)
                self.assertEqual((subject, html), (email_test_api.TEST_SUBJECT, email_test_api.TEST_HTML))
                for v in ATTACK.values():
                    self.assertNotIn(v, (to, subject, html))
                self.assertNotIn('evil.example', html)

    def test_smtp_error_text_is_not_returned(self):
        self.login_as(ENV_ADMIN)
        SEND.return_value = (False, 'Gửi email thất bại: (535, b"5.7.8 Username and Password not accepted SECRETDETAIL")')
        r = self.c.post('/api/test-email', json={})
        self.assertEqual(r.status_code, 500)
        body = r.get_data(as_text=True)
        self.assertNotIn('SECRETDETAIL', body)
        self.assertNotIn('535', body)

    def test_rate_limited_to_three_per_hour(self):
        self.login_as(ENV_ADMIN)
        codes = [self.c.post('/api/test-email', json={}).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])
        self.assertEqual(SEND.call_count, 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
