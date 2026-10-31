# -*- coding: utf-8 -*-
"""Test OFFLINE bảo mật h1a-auth (đăng nhập / Super Admin / JWT / xoá tài khoản / khoá đăng nhập).

Bất biến được kiểm:
1. Quyền Super Admin CHỈ đến từ quyết định phía server lúc đăng nhập God Mode đã so hash — không từ chuỗi email.
   /register (và mọi luồng tạo tài khoản) từ chối email Super Admin; /api/auth/token không bao giờ cấp JWT mang quyền
   Super Admin; JWT cũ mang email/role/uid Super Admin bị coi là hỏng. Đăng nhập God Mode thật vẫn chạy.
2. Xoá tài khoản thu hồi MỌI phiên cookie + JWT khác, gỡ liên kết Google/Facebook, chủ tiệm xoá -> nhân viên của tiệm hết
   phiên; nhân viên tự xoá không đóng tiệm của chủ; tài khoản chỉ OAuth nhận lỗi rõ (không 500).
3. Người lạ dò sai 10 lần/email không khoá được chủ tiệm ở MÁY QUEN (cookie HMAC); máy lạ vẫn bị chặn như cũ.
4. Phiên God Mode thu hồi được: "đăng xuất mọi nơi", đổi hash, hết hạn 12 giờ, gỡ email khỏi danh sách; vẫn chạy khi DB sập.

KHÔNG import app.py (mã nguồn các hàm được lấy qua ast rồi chạy trên 1 Flask app thử), KHÔNG mở MongoDB thật (mongo_client
bị stub trước mọi import, DB là bộ nhớ trong), KHÔNG chạy server, KHÔNG gọi mạng/API trả phí.
Chạy: PYTHONIOENCODING=utf-8 python scripts/tests/test_security_h1a-auth.py
(H1A_APP_SRC=<đường dẫn app.py khác> để chạy cùng bộ test trên 1 bản app.py cũ — dùng khi chứng minh test fail trước bản vá.)
"""
import ast
import base64
import hashlib
import hmac
import io
import itertools
import os
import re
import secrets
import sys
import time
import types
import unittest
import uuid
import warnings
from datetime import datetime, timedelta, timezone
from functools import wraps
from unittest.mock import MagicMock, patch

warnings.simplefilter('ignore', DeprecationWarning)   # datetime.utcnow() trong app.py
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------- stub TRƯỚC mọi import của module thật
sys.modules['mongo_client'] = types.SimpleNamespace(db=MagicMock(name='db'), next_mongo_id=lambda c: 1, MONGO_STATUS='CONNECTED')

import jwt as pyjwt  # noqa: E402
from flask import (Flask, jsonify, request, session, redirect, flash, g, current_app,  # noqa: E402
                   get_flashed_messages, after_this_request)
from werkzeug.security import generate_password_hash, check_password_hash  # noqa: E402

APP_PATH = os.environ.get('H1A_APP_SRC') or os.path.join(ROOT, 'app.py')
with io.open(APP_PATH, encoding='utf-8') as _fh:
    APP_SRC = _fh.read()
_TREE = ast.parse(APP_SRC)

_FUNCS = {
    '_get_bearer_token', '_load_session_from_jwt', '_hybrid_auth_and_csrf', '_user_session_state', 'bump_session_version',
    '_session_guard', '_wants_json', 'login_required', '_login_attempts_blocked', '_record_login_failure', 'register',
    '_email_query', '_is_authorized_superadmin_email', '_superadmin_emergency_login', 'login', 'api_auth_token',
    'api_delete_account', 'logout', '_is_superadmin', '_superadmin_session_ok', '_superadmin_fallback_hash',
    '_superadmin_key_fingerprint', '_superadmin_session_ver', '_known_device_token', '_is_known_login_device',
    '_remember_login_device',
}
_ASSIGNS = {
    'SUPERADMIN_ROOT_EMAIL', '_LOGIN_FAIL_WINDOW_SECONDS', '_LOGIN_FAIL_MAX_PER_IP', '_LOGIN_FAIL_MAX_PER_EMAIL',
    '_login_fail_ttl_ready', '_TOO_MANY_LOGIN_MSG', '_SESSION_STATE_CACHE', '_SESSION_STATE_TTL',
    'SUPERADMIN_SESSION_MAX_SECONDS', '_SUPERADMIN_VER_CACHE', '_KNOWN_DEVICE_COOKIE', '_KNOWN_DEVICE_MAX_AGE',
}


def _select(node):
    if isinstance(node, ast.FunctionDef) and node.name in _FUNCS:
        node.decorator_list = []
        return True
    if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) in _ASSIGNS for t in node.targets):
        return True
    return False


_CODE = compile(ast.fix_missing_locations(ast.Module(body=[n for n in _TREE.body if _select(n)], type_ignores=[])),
                'app.py::h1a-auth', 'exec')
ROOT_EMAIL = re.search(r"^SUPERADMIN_ROOT_EMAIL = '([^']+)'", APP_SRC, re.M).group(1)
OPS_EMAIL = 'ops@bitpaw.test'
SA_PASSWORD = 'god-mode-test-pass-1'
JWT_SECRET = 'h1a-jwt-test-secret-0123456789abcdef'
FAST = 'pbkdf2:sha256:1000'


# ---------------------------------------------------------------- MongoDB giả (bộ nhớ trong)
def _get(doc, dotted):
    cur = doc
    for part in dotted.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def _match_value(val, present, cond):
    if isinstance(cond, dict) and any(k.startswith('$') for k in cond):
        for op, arg in cond.items():
            if op == '$regex':
                flags = re.I if 'i' in cond.get('$options', '') else 0
                if not (present and isinstance(val, str) and re.search(arg, val, flags)):
                    return False
            elif op == '$options':
                continue
            elif op == '$gte':
                if not (present and val is not None and val >= arg):
                    return False
            elif op == '$ne':
                if present and val == arg:
                    return False
            elif op == '$in':
                if not (present and val in arg):
                    return False
            elif op == '$exists':
                if bool(present) != bool(arg):
                    return False
            else:
                raise NotImplementedError(op)
        return True
    return present and val == cond


def _matches(doc, query):
    return all(_match_value(*_get(doc, k), v) for k, v in (query or {}).items())


def _set_path(doc, dotted, value):
    parts = dotted.split('.')
    for part in parts[:-1]:
        doc = doc.setdefault(part, {})
    doc[parts[-1]] = value


def _unset_path(doc, dotted):
    parts = dotted.split('.')
    for part in parts[:-1]:
        doc = doc.get(part)
        if not isinstance(doc, dict):
            return
    doc.pop(parts[-1], None)


class _Result(types.SimpleNamespace):
    pass


class FakeCollection:
    def __init__(self):
        self.docs = []

    def _proj(self, doc, projection):
        out = dict(doc)
        out.pop('_id', None)
        return out

    def find_one(self, query=None, projection=None, **_kw):
        for d in self.docs:
            if _matches(d, query):
                return self._proj(d, projection)
        return None

    def find(self, query=None, projection=None, **_kw):
        return [self._proj(d, projection) for d in self.docs if _matches(d, query)]

    def count_documents(self, query, limit=None, **_kw):
        n = sum(1 for d in self.docs if _matches(d, query))
        return min(n, limit) if limit else n

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return _Result(inserted_id=len(self.docs))

    def _apply(self, d, update):
        for k, v in (update.get('$set') or {}).items():
            _set_path(d, k, v)
        for k, v in (update.get('$inc') or {}).items():
            cur, _ = _get(d, k)
            _set_path(d, k, (cur or 0) + v)
        for k in (update.get('$unset') or {}):
            _unset_path(d, k)

    def update_one(self, query, update, upsert=False, **_kw):
        for d in self.docs:
            if _matches(d, query):
                self._apply(d, update)
                return _Result(matched_count=1, modified_count=1)
        if upsert:
            d = {k: v for k, v in query.items() if not isinstance(v, dict)}
            self._apply(d, update)
            for k, v in (update.get('$setOnInsert') or {}).items():
                _set_path(d, k, v)
            self.docs.append(d)
        return _Result(matched_count=0, modified_count=0)

    def update_many(self, query, update, **_kw):
        n = 0
        for d in self.docs:
            if _matches(d, query):
                self._apply(d, update)
                n += 1
        return _Result(matched_count=n, modified_count=n)

    def create_index(self, *_a, **_kw):
        return 'idx'


class FakeDB:
    def __init__(self):
        self._cols = {}

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self._cols.setdefault(name, FakeCollection())


class BrokenDB:
    """DB đứt kết nối: mọi truy vấn đều lỗi (God Mode phải vẫn chạy)."""
    def __getattr__(self, name):
        raise RuntimeError('mongo down')


class Clock:
    def __init__(self):
        self.offset = 0

    def time(self):
        return time.time() + self.offset


# ---------------------------------------------------------------- Flask app thử chạy đúng các hàm thật của app.py
class Harness(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.clock = Clock()
        self.flask = Flask(__name__)
        self.flask.secret_key = 'h1a-flask-test-secret'
        self.flask.logger.disabled = True
        self.ids = itertools.count(1)
        self.env = patch.dict(os.environ, {
            'SUPERADMIN_EMAILS': OPS_EMAIL,
            'SUPERADMIN_FALLBACK_HASH_B64': base64.b64encode(generate_password_hash(SA_PASSWORD, method=FAST).encode()).decode(),
            'SUPERADMIN_FALLBACK_HASH': '',
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        def render_template(name, **_kw):
            return f'TPL:{name}|' + '|'.join(get_flashed_messages())

        ns = {
            '__name__': 'app_h1a', 'db': self.db, 'session': session, 'request': request, 'jsonify': jsonify,
            'redirect': redirect, 'flash': flash, 'g': g, 'current_app': current_app, 'after_this_request': after_this_request,
            'render_template': render_template, 'url_for': lambda endpoint, **kw: '/' + endpoint,
            'csrf': types.SimpleNamespace(protect=lambda: None), '_CSRF_EXEMPT_ENDPOINTS': set(),
            'security_shield': types.SimpleNamespace(code_attempts_blocked=lambda ip: False, record_code_failure=lambda *a: None,
                                                     log_event=lambda *a, **k: None),
            '_get_real_client_ip': lambda: request.remote_addr or '127.0.0.1',
            '_vi_en': lambda vi, en: en, 'wraps': wraps, 'os': os, 're': re, 'time': self.clock, 'uuid': uuid,
            'base64': base64, 'hmac': hmac, 'hashlib': hashlib, 'secrets': secrets,
            'datetime': datetime, 'timedelta': timedelta, 'timezone': timezone,
            'generate_password_hash': generate_password_hash, 'check_password_hash': check_password_hash,
            'pyjwt': pyjwt, 'JWT_SECRET': JWT_SECRET, 'JWT_ALGORITHM': 'HS256', 'JWT_EXPIRY_HOURS': 720,
            'next_mongo_id': lambda c: next(self.ids), 'plans': types.SimpleNamespace(PLAN_ORDER=('essential', 'pro', 'empire')),
            '_send_welcome_email': MagicMock(name='welcome'), '_ensure_primary_membership': MagicMock(name='membership'),
            'INDUSTRY_CONFIG': {}, 'app': self.flask, 'print': lambda *a, **k: None,
        }
        exec(_CODE, ns)
        self.ns = ns
        app = self.flask
        app.before_request(ns['_hybrid_auth_and_csrf'])
        app.before_request(ns['_session_guard'])
        app.add_url_rule('/register', 'register', ns['register'], methods=['GET', 'POST'])
        app.add_url_rule('/login', 'login', ns['login'], methods=['GET', 'POST'])
        app.add_url_rule('/api/auth/token', 'api_auth_token', ns['api_auth_token'], methods=['POST'])
        app.add_url_rule('/api/users/delete-account', 'api_delete_account', ns['login_required'](ns['api_delete_account']),
                         methods=['POST'])
        app.add_url_rule('/logout', 'logout', ns['logout'])

        def probe():
            return jsonify(success=True, uid=session.get('user_id'), business_id=session.get('business_id'),
                           superadmin=bool(ns['_is_superadmin']()))
        app.add_url_rule('/api/superadmin/probe', 'probe', ns['login_required'](probe))

    # ------------------------------------------------------------ helpers
    def client(self, ip='10.0.0.1'):
        c = self.flask.test_client()
        c.environ_base['REMOTE_ADDR'] = ip
        return c

    def add_user(self, email, password='owner-pass-123', **extra):
        uid = extra.pop('id', None) or str(uuid.uuid4())
        doc = {'id': uid, 'email': email, 'password_hash': generate_password_hash(password, method=FAST) if password else None,
               'business_id': extra.pop('business_id', uid), 'role': extra.pop('role', 'admin'), 'created_at': 'x'}
        doc.update(extra)
        self.db.users.insert_one(doc)
        return doc

    def add_code(self, key='CODE-1', plan='pro'):
        self.db.license_codes.insert_one({'license_key': key, 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'nail', 'plan': plan})
        return key

    def register(self, c, email, password='attacker-pass-1', code='CODE-1'):
        return c.post('/register', data={'email': email, 'password': password, 'business_type': 'nail',
                                         'business_name': 'Shop', 'fullname': 'Owner', 'license_key': code})

    def token(self, c, email, password):
        return c.post('/api/auth/token', json={'email': email, 'password': password})

    def probe(self, c, bearer=None):
        headers = {'Authorization': f'Bearer {bearer}'} if bearer else {}
        return c.get('/api/superadmin/probe', headers=headers)

    def mint(self, **claims):
        now = datetime.now(timezone.utc)
        payload = {'sv': 0, 'business_mode': 'nail', 'role': 'admin', 'iat': now, 'exp': now + timedelta(hours=1)}
        payload.update(claims)
        return pyjwt.encode(payload, JWT_SECRET, algorithm='HS256')

    def god_login(self, c, email=None, password=SA_PASSWORD):
        return c.post('/login', data={'email': email or ROOT_EMAIL, 'password': password})


# ================================================================ 1. Super Admin không đến từ chuỗi email
class SuperadminAuthorityTests(Harness):
    def test_attack_chain_register_root_email_then_mobile_token_gets_no_superadmin(self):
        """Kịch bản audit: chủ tiệm có 1 mã kích hoạt -> đăng ký email root -> lấy JWT -> gọi API Super Admin."""
        self.add_code()
        c = self.client()
        self.register(c, ROOT_EMAIL)
        self.assertIsNone(self.db.users.find_one({'email': ROOT_EMAIL}), 'register must refuse the super-admin email')
        tok = self.token(c, ROOT_EMAIL, 'attacker-pass-1')
        self.assertEqual(tok.status_code, 401)
        self.assertNotIn('access_token', tok.get_json())

    def test_register_refuses_every_superadmin_email_with_the_generic_message_and_keeps_the_code(self):
        for i, email in enumerate((ROOT_EMAIL, ' ' + ROOT_EMAIL.upper() + ' ', OPS_EMAIL, 'OPS@BitPaw.Test')):
            code = self.add_code(f'CODE-{i}')
            resp = self.register(self.client(), email, code=code)
            self.assertEqual(resp.status_code, 200, email)
            self.assertIn('already registered', resp.get_data(as_text=True), email)
            self.assertEqual(self.db.users.count_documents({}), 0, email)
            self.assertEqual(self.db.license_codes.find_one({'license_key': code})['trang_thai'], 'Sẵn sàng', email)

    def test_normal_owner_registration_login_and_mobile_token_still_work(self):
        self.add_code()
        c = self.client()
        resp = self.register(c, 'Owner@Shop.test', password='owner-pass-123')
        self.assertEqual(resp.status_code, 302)
        user = self.db.users.find_one({'email': 'owner@shop.test'})
        self.assertIsNotNone(user)
        resp = c.post('/login', data={'email': 'owner@shop.test', 'password': 'owner-pass-123'})
        self.assertEqual(resp.status_code, 302)
        body = self.probe(c).get_json()
        self.assertEqual((body['uid'], body['superadmin']), (user['id'], False))
        tok = self.token(self.client(), 'owner@shop.test', 'owner-pass-123')
        self.assertEqual(tok.status_code, 200)
        jwt_body = self.probe(self.client(), tok.get_json()['access_token']).get_json()
        self.assertEqual((jwt_body['uid'], jwt_body['superadmin']), (user['id'], False))

    def test_token_endpoint_never_mints_for_a_db_row_holding_a_superadmin_email_or_role(self):
        # bản ghi do kẻ tấn công tạo TRƯỚC bản vá (hoặc DB lỡ có) — đúng mật khẩu vẫn không được token
        self.add_user(ROOT_EMAIL, password='attacker-pass-1')
        self.add_user(OPS_EMAIL.upper(), password='attacker-pass-1')
        self.add_user('weird@shop.test', password='attacker-pass-1', role='super_admin')
        for email in (ROOT_EMAIL, OPS_EMAIL, 'weird@shop.test'):
            resp = self.token(self.client(), email, 'attacker-pass-1')
            self.assertEqual(resp.status_code, 401, email)
            self.assertNotIn('access_token', resp.get_json(), email)

    def test_jwt_carrying_superadmin_email_role_or_uid_is_rejected(self):
        row = self.add_user(ROOT_EMAIL, password='attacker-pass-1')
        bad = [
            self.mint(user_id=row['id'], business_id=row['id'], user_email=ROOT_EMAIL),        # JWT cấp trước bản vá
            self.mint(user_id=row['id'], business_id=row['id'], user_email=OPS_EMAIL),
            self.mint(user_id=row['id'], business_id=row['id'], user_email='x@shop.test', role='super_admin'),
            self.mint(user_id='superadmin-fallback', business_id='superadmin-fallback', user_email='x@shop.test'),
        ]
        for tok in bad:
            resp = self.probe(self.client(), tok)
            self.assertEqual(resp.status_code, 401, pyjwt.decode(tok, JWT_SECRET, algorithms=['HS256']))
            self.assertNotIn('superadmin', resp.get_json())

    def test_cookie_session_with_superadmin_email_but_no_god_mode_login_is_not_superadmin(self):
        # vd đăng nhập Google/Facebook vào 1 bản ghi trùng email root: phiên thường, email root
        row = self.add_user(ROOT_EMAIL, password=None)
        c = self.client()
        with c.session_transaction() as s:
            s.update({'user_id': row['id'], 'business_id': row['id'], 'user_email': ROOT_EMAIL, 'role': 'admin', 'sv': 0})
        body = self.probe(c).get_json()
        self.assertEqual(body['uid'], row['id'])
        self.assertFalse(body['superadmin'])

    def test_hand_made_fallback_session_without_server_marker_is_not_superadmin(self):
        c = self.client()
        with c.session_transaction() as s:
            s.update({'user_id': 'superadmin-fallback', 'business_id': 'superadmin-fallback', 'user_email': ROOT_EMAIL,
                      'role': 'super_admin', 'business_mode': 'none'})
        resp = self.probe(c)
        self.assertFalse(resp.status_code == 200 and resp.get_json().get('superadmin'))

    def test_real_god_mode_login_still_grants_superadmin_for_root_and_env_emails(self):
        for email in (ROOT_EMAIL, OPS_EMAIL):
            c = self.client()
            resp = self.god_login(c, email)
            self.assertEqual(resp.status_code, 302, email)
            self.assertTrue(resp.headers['Location'].endswith('/super_admin'), email)
            body = self.probe(c).get_json()
            self.assertEqual((body['uid'], body['superadmin']), ('superadmin-fallback', True), email)

    def test_god_mode_wrong_password_and_removed_env_email_get_nothing(self):
        c = self.client()
        resp = self.god_login(c, password='wrong-password-1')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.probe(c).status_code, 401)
        c = self.client()
        self.god_login(c, OPS_EMAIL)
        with patch.dict(os.environ, {'SUPERADMIN_EMAILS': ''}):    # gỡ email khỏi danh sách -> mất quyền ngay
            resp = self.probe(c)
            self.assertFalse(resp.status_code == 200 and resp.get_json().get('superadmin'))

    def test_god_mode_login_works_while_mongodb_is_down(self):
        self.ns['db'] = BrokenDB()
        c = self.client()
        resp = self.god_login(c)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.probe(c).get_json()['superadmin'])


# ================================================================ 2. Xoá tài khoản thu hồi mọi phiên + JWT
class AccountDeletionTests(Harness):
    def login(self, c, email, password='owner-pass-123'):
        resp = c.post('/login', data={'email': email, 'password': password})
        self.assertEqual(resp.status_code, 302, resp.get_data(as_text=True))
        return resp

    def delete(self, c, password='owner-pass-123', bearer=None):
        headers = {'Authorization': f'Bearer {bearer}'} if bearer else {}
        return c.post('/api/users/delete-account', json={'password': password}, headers=headers)

    def test_delete_revokes_other_cookie_sessions_and_30_day_jwts_immediately(self):
        owner = self.add_user('owner@shop.test', oauth={'google': 'g-sub-1'}, oauth_linked_at={'google': 'x'})
        self.db.businesses.insert_one({'id': owner['id'], 'name': 'Shop'})
        laptop, phone_web, attacker = self.client(), self.client('10.0.0.2'), self.client('10.6.6.6')
        self.login(laptop, 'owner@shop.test')
        self.login(attacker, 'owner@shop.test')                   # cookie bị lấy cắp / máy POS dùng chung
        jwt_tok = self.token(self.client(), 'owner@shop.test', 'owner-pass-123').get_json()['access_token']
        for c, tok in ((attacker, None), (phone_web, jwt_tok)):  # đã dùng trước khi xoá -> bộ nhớ đệm phiên đã nạp
            self.assertEqual(self.probe(c, tok).status_code, 200)
        resp = self.delete(laptop)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self.probe(attacker).status_code, 401)
        self.assertEqual(self.probe(phone_web, jwt_tok).status_code, 401)
        self.assertEqual(self.probe(laptop).status_code, 401)
        doc = self.db.users.find_one({'id': owner['id']})
        self.assertTrue(doc['is_deleted'])
        self.assertIs(doc['is_active'], False)
        self.assertNotIn('oauth', doc)                            # Google/Facebook không còn vào lại tài khoản đã xoá
        self.assertNotIn('oauth_linked_at', doc)
        self.assertTrue(self.db.businesses.find_one({'id': owner['id']})['is_deleted'])

    def test_owner_deletion_signs_out_and_locks_the_shop_staff(self):
        owner = self.add_user('owner@shop.test')
        staff = self.add_user('staff@shop.test', password='staff-pass-123', business_id=owner['id'], role='staff')
        other = self.add_user('other@else.test', password='other-pass-123')
        s = self.client('10.0.0.5')
        self.login(s, 'staff@shop.test', 'staff-pass-123')
        staff_jwt = self.token(self.client(), 'staff@shop.test', 'staff-pass-123').get_json()['access_token']
        o = self.client('10.0.0.6')
        self.login(o, 'other@else.test', 'other-pass-123')
        self.assertEqual(self.delete(self.login_client('owner@shop.test')).status_code, 200)
        self.assertEqual(self.probe(s).status_code, 401)
        self.assertEqual(self.probe(self.client(), staff_jwt).status_code, 401)
        self.assertEqual(self.token(self.client(), 'staff@shop.test', 'staff-pass-123').status_code, 401)
        self.assertIs(self.db.users.find_one({'id': staff['id']})['is_active'], False)
        self.assertEqual(self.probe(o).status_code, 200)          # tiệm khác không bị ảnh hưởng
        self.assertIsNot(self.db.users.find_one({'id': other['id']}).get('is_active'), False)

    def login_client(self, email, password='owner-pass-123'):
        c = self.client('10.0.0.9')
        self.login(c, email, password)
        return c

    def test_staff_deleting_own_account_does_not_close_the_owners_shop(self):
        owner = self.add_user('owner@shop.test')
        self.add_user('staff@shop.test', password='staff-pass-123', business_id=owner['id'], role='staff')
        self.db.businesses.insert_one({'id': owner['id'], 'name': 'Shop'})
        o = self.login_client('owner@shop.test')
        st = self.login_client('staff@shop.test', 'staff-pass-123')
        self.assertEqual(self.delete(st, 'staff-pass-123').status_code, 200)
        self.assertEqual(self.probe(o).status_code, 200)
        self.assertIsNot(self.db.users.find_one({'id': owner['id']}).get('is_active'), False)
        self.assertFalse(self.db.businesses.find_one({'id': owner['id']}).get('is_deleted'))

    def test_account_deleted_before_this_fix_loses_its_live_sessions(self):
        # bản xoá cũ: is_deleted=True nhưng session_ver giữ nguyên -> phiên/JWT cũ trước đây vẫn sống
        u = self.add_user('deleted_x_old@shop.test', is_deleted=True, deleted_at='x')
        c = self.client()
        with c.session_transaction() as s:
            s.update({'user_id': u['id'], 'business_id': u['id'], 'user_email': 'old@shop.test', 'role': 'admin', 'sv': 0})
        self.assertEqual(self.probe(c).status_code, 401)
        tok = self.mint(user_id=u['id'], business_id=u['id'], user_email='old@shop.test')
        self.assertEqual(self.probe(self.client(), tok).status_code, 401)

    def test_deleted_or_disabled_accounts_cannot_sign_in_again(self):
        self.add_user('gone@shop.test', is_deleted=True)
        self.add_user('off@shop.test', is_active=False)
        for email in ('gone@shop.test', 'off@shop.test'):
            self.assertEqual(self.token(self.client(), email, 'owner-pass-123').status_code, 401, email)
            c = self.client()
            resp = c.post('/login', data={'email': email, 'password': 'owner-pass-123'})
            self.assertEqual(resp.status_code, 200, email)
            self.assertIn('Incorrect email or password', resp.get_data(as_text=True))

    def test_oauth_only_accounts_get_clear_errors_instead_of_500(self):
        u = self.add_user('google@shop.test', password=None, oauth={'google': 'g-2'})
        c = self.client()
        with c.session_transaction() as s:
            s.update({'user_id': u['id'], 'business_id': u['id'], 'user_email': 'google@shop.test', 'role': 'admin', 'sv': 0})
        resp = self.delete(c, 'anything-123')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Forgot password', resp.get_json()['message'])
        self.assertFalse(self.db.users.find_one({'id': u['id']}).get('is_deleted'))
        self.assertEqual(self.token(self.client(), 'google@shop.test', 'anything-123').status_code, 401)

    def test_wrong_password_deletes_nothing(self):
        u = self.add_user('owner@shop.test')
        c = self.login_client('owner@shop.test')
        self.assertEqual(self.delete(c, 'wrong-pass-123').status_code, 401)
        self.assertFalse(self.db.users.find_one({'id': u['id']}).get('is_deleted'))
        self.assertEqual(self.probe(c).status_code, 200)


# ================================================================ 3. Khoá theo email không khoá được chủ tiệm ở máy quen
class LoginLockoutTests(Harness):
    def hammer(self, email, n=10, ips=('203.0.113.7', '203.0.113.8', '198.51.100.9')):
        """Người lạ (không tài khoản) gửi n lần sai mật khẩu cho email của nạn nhân, rải qua vài IP."""
        for i in range(n):
            self.client(ips[i % len(ips)]).post('/login', data={'email': email, 'password': f'guess-{i}-xxxx'})

    def test_strangers_cannot_lock_the_owner_out_of_their_known_device(self):
        self.add_user('owner@shop.test')
        known = self.client('10.0.0.42')
        self.assertEqual(known.post('/login', data={'email': 'owner@shop.test', 'password': 'owner-pass-123'}).status_code, 302)
        known.get('/logout')
        self.hammer('owner@shop.test')
        resp = known.post('/login', data={'email': 'Owner@Shop.test', 'password': 'owner-pass-123'})
        self.assertEqual(resp.status_code, 302, resp.get_data(as_text=True))
        self.assertEqual(self.probe(known).status_code, 200)
        self.assertEqual(self.token(known, 'owner@shop.test', 'owner-pass-123').status_code, 200)

    def test_unknown_devices_stay_blocked_with_the_same_answer_for_right_and_wrong_passwords(self):
        self.add_user('owner@shop.test')
        self.hammer('owner@shop.test')
        for pw in ('owner-pass-123', 'wrong-pass-123'):
            resp = self.client('192.0.2.50').post('/login', data={'email': 'owner@shop.test', 'password': pw})
            self.assertEqual(resp.status_code, 429, pw)
            self.assertEqual(self.token(self.client('192.0.2.51'), 'owner@shop.test', pw).status_code, 429, pw)

    def test_known_device_is_still_capped_on_its_own_ip_and_per_ip_cap_holds(self):
        self.add_user('owner@shop.test')
        known = self.client('10.0.0.43')
        known.post('/login', data={'email': 'owner@shop.test', 'password': 'owner-pass-123'})
        known.get('/logout')
        for i in range(10):
            known.post('/login', data={'email': 'owner@shop.test', 'password': f'bad-{i}-xxxx'})
        self.assertEqual(known.post('/login', data={'email': 'owner@shop.test', 'password': 'owner-pass-123'}).status_code, 429)

    def test_known_device_cookie_only_helps_the_email_it_was_earned_for(self):
        self.add_user('owner@shop.test')
        self.add_user('victim@shop.test', password='victim-pass-123')
        c = self.client('10.0.0.44')
        c.post('/login', data={'email': 'owner@shop.test', 'password': 'owner-pass-123'})
        c.get('/logout')
        self.hammer('victim@shop.test')
        self.assertEqual(c.post('/login', data={'email': 'victim@shop.test', 'password': 'victim-pass-123'}).status_code, 429)

    def test_known_device_cookie_is_httponly_secure_and_holds_no_raw_email(self):
        self.add_user('owner@shop.test')
        resp = self.client().post('/login', data={'email': 'owner@shop.test', 'password': 'owner-pass-123'})
        cookie = next(h for h in resp.headers.getlist('Set-Cookie') if h.startswith('bp_kd='))
        self.assertIn('HttpOnly', cookie)
        self.assertIn('Secure', cookie)
        self.assertNotIn('owner', cookie.lower())
        bad = self.client().post('/login', data={'email': 'owner@shop.test', 'password': 'wrong-pass-123'})
        self.assertFalse(any(h.startswith('bp_kd=') for h in bad.headers.getlist('Set-Cookie')))

    def test_super_admin_known_device_survives_a_lockout_attack(self):
        known = self.client('10.0.0.45')
        self.assertEqual(self.god_login(known).status_code, 302)
        known.get('/logout')
        self.hammer(ROOT_EMAIL)
        self.assertEqual(self.god_login(self.client('192.0.2.60')).status_code, 429)
        resp = self.god_login(known)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.probe(known).get_json()['superadmin'])


# ================================================================ 4. Phiên God Mode thu hồi được
class SuperadminSessionRevocationTests(Harness):
    def signed_in(self, ip='10.0.1.1'):
        c = self.client(ip)
        self.assertEqual(self.god_login(c).status_code, 302)
        self.assertTrue(self.probe(c).get_json()['superadmin'])
        return c

    def assert_signed_out(self, c):
        resp = self.probe(c)
        self.assertEqual(resp.status_code, 401, resp.get_json())
        with c.session_transaction() as s:
            self.assertNotIn('user_id', s)

    def test_sign_out_everywhere_ends_every_god_mode_session(self):
        a, b = self.signed_in(), self.signed_in('10.0.1.2')
        self.ns['bump_session_version']('superadmin-fallback')     # /api/account/logout_all gọi đúng hàm này
        self.assert_signed_out(a)
        self.assert_signed_out(b)
        self.assertEqual(self.db.users.count_documents({}), 0)
        c = self.signed_in('10.0.1.3')                              # đăng nhập lại vẫn được, mang số phiên bản mới
        with c.session_transaction() as s:
            self.assertEqual(s['sv'], 1)

    def test_rotating_the_fallback_hash_ends_existing_god_mode_sessions(self):
        a = self.signed_in()
        new_hash = base64.b64encode(generate_password_hash('rotated-pass-2', method=FAST).encode()).decode()
        with patch.dict(os.environ, {'SUPERADMIN_FALLBACK_HASH_B64': new_hash}):
            self.assert_signed_out(a)
            c = self.client('10.0.1.9')
            self.assertEqual(self.god_login(c, password='rotated-pass-2').status_code, 302)
            self.assertTrue(self.probe(c).get_json()['superadmin'])

    def test_god_mode_session_has_an_absolute_lifetime(self):
        a = self.signed_in()
        self.clock.offset = 11 * 3600
        self.assertTrue(self.probe(a).get_json()['superadmin'])
        self.clock.offset = 12 * 3600 + 60
        self.assert_signed_out(a)

    def test_legacy_or_hand_made_god_mode_cookie_is_signed_out(self):
        c = self.client()
        with c.session_transaction() as s:   # phiên God Mode cấp trước bản vá: không có dấu thời gian/hash/phiên bản
            s.update({'user_id': 'superadmin-fallback', 'business_id': 'superadmin-fallback', 'user_email': ROOT_EMAIL,
                      'role': 'super_admin', 'business_mode': 'none'})
        self.assert_signed_out(c)

    def test_removed_env_email_is_signed_out(self):
        c = self.client()
        self.god_login(c, OPS_EMAIL)
        with patch.dict(os.environ, {'SUPERADMIN_EMAILS': ''}):
            self.assert_signed_out(c)

    def test_god_mode_session_keeps_working_while_mongodb_is_down_but_still_expires(self):
        a = self.signed_in()
        self.ns['db'] = BrokenDB()
        self.ns['_SUPERADMIN_VER_CACHE'].clear()
        self.assertTrue(self.probe(a).get_json()['superadmin'])
        self.clock.offset = 13 * 3600
        self.assert_signed_out(a)

    def test_normal_owner_sign_out_everywhere_still_works(self):
        u = self.add_user('owner@shop.test')
        c = self.client()
        c.post('/login', data={'email': 'owner@shop.test', 'password': 'owner-pass-123'})
        self.assertEqual(self.probe(c).status_code, 200)
        self.ns['bump_session_version'](u['id'])
        self.assertEqual(self.probe(c).status_code, 401)


if __name__ == '__main__':
    unittest.main(verbosity=2, warnings='ignore')
