# -*- coding: utf-8 -*-
"""Test OFFLINE — security h3 "exposure":
  A) GET /api/hr/employees, /api/hr/employees/<ma_nv>, /api/stream/hr_employees: staff accounts get a directory only
     (no salary / allowance / live GPS); owner/admin keep every field.
  B) /api/public/hr/employees/lookup: never answers across shops (scoped to the signed-in shop, 401 without a session),
     returns only ma_nv + ho_ten, has its own rate limit.
  C) templates/chamcong_kythuat.html loadHistory(): AI/customer text copied into ghi_chu (and the other row fields) is
     escaped before innerHTML (stored XSS in the owner's session).
  D) POST /api/bot/messages: a JSON operator as customer_id ({"$in": [...]}) no longer passes the ownership check.
  E) /api/storage/upload: client 'kind' allow-listed, magic bytes checked, size cap, per-shop storage quota.
  F) /api/portal/upload: magic bytes, size cap, per-conversation / per-shop daily caps, signed public link.
  G) /api/public/storage/file/<id>: portal_chat needs the HMAC signature (old unsigned links only until the migration
     date), private files answer 404 like missing ones (no existence oracle).
  H) inbox_channels.link_customer / capture_phone: a phone typed in Messenger/Zalo never re-points an existing customer's
     channel id; it becomes a pending link the owner confirms (POST /api/bot/customer_link). (h4b: a customer that is the
     ONLY match and has no id for that platform is linked automatically — see test_security_h4b-auth-inbox.py.)
  I) /api/ai/studio/generate anonymous sales chat: global daily call cap (no DeepSeek call once over it), prompt cut,
     extra per-IP daily limit only for anonymous non-booking chats.

KHÔNG chạy Flask server, KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi
DeepSeek/Meta/Zalo: mongo_client được thay bằng DB giả trong RAM TRƯỚC mọi import; hàm của app.py lấy mã nguồn qua ast.

Chạy: python scripts/tests/test_security_h3-exposure.py
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
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from bson import ObjectId  # noqa: E402
from bson.errors import InvalidId  # noqa: E402
from gridfs.errors import NoFile  # noqa: E402


# ---------------------------------------------------------------- DB giả trong RAM (có projection / toán tử như Mongo)
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
            if op == '$regex' and not (isinstance(v, str) and re.search(arg, v)):
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
        elif not _match_value(doc.get(k), cond):
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

    def find(self, flt=None, projection=None):
        return _Cursor(_project(d, projection) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = [d for d in self.docs if _matches(d, flt or {})]
        return _project(rows[0], projection) if rows else None

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


class FakeGridFS:
    """media_fs giả: file doc vào DB['media.files'] (để đếm/tổng dung lượng như GridFS thật), bytes giữ trong RAM."""
    def __init__(self):
        self.blobs = {}

    def put(self, data, **kw):
        oid = ObjectId()
        doc = {k: v for k, v in kw.items() if k != 'content_type'}
        doc.update({'_id': oid, 'length': len(data), 'contentType': kw.get('content_type')})
        DB['media.files'].insert_one(doc)
        self.blobs[oid] = bytes(data)
        return oid

    def get(self, oid):
        doc = DB['media.files'].find_one({'_id': oid})
        if not doc:
            raise NoFile('no file')
        blob = self.blobs.get(oid, b'')
        out = types.SimpleNamespace(**{k: v for k, v in doc.items() if k != 'contentType'})
        out.content_type = doc.get('contentType')
        out.read = lambda: blob
        return out


MEDIA_FS = FakeGridFS()

# stub TRƯỚC mọi import có thể kéo mongo_client thật / gửi tin thật
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: 1, MONGO_STATUS='CONNECTED')
_vault = types.ModuleType('nurture_channel_tokens')
_vault.encrypt_secret = lambda s: s
_vault.decrypt_secret = lambda s: s
sys.modules['nurture_channel_tokens'] = _vault

from flask import Flask, jsonify, request, session, url_for, Response  # noqa: E402
from werkzeug.utils import secure_filename  # noqa: E402
import requests  # noqa: E402
import hmac  # noqa: E402
import hashlib  # noqa: E402

import inbox_channels  # noqa: E402  (mongo_client = DB giả)

inbox_channels.send_text = MagicMock(side_effect=AssertionError('no real send in this test'))


# ---------------------------------------------------------------- hàm của app.py (lấy mã nguồn qua ast, bỏ decorator)
def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


APP_SRC = _read('app.py')
TREE = ast.parse(APP_SRC)
_ASSIGNS = ('_EMPLOYEE_SORT_FIELDS', '_EMPLOYEE_DIRECTORY_FIELDS', 'ALLOWED_MEDIA_EXTENSIONS', '_SAFE_IMAGE_CONTENT_TYPES',
            '_PUBLIC_MEDIA_KINDS', '_STORAGE_UPLOAD_KINDS', '_STORAGE_UPLOAD_MAX_BYTES', '_PORTAL_UPLOAD_MAX_BYTES',
            '_PORTAL_UPLOADS_PER_CONVERSATION_DAY', '_PORTAL_UPLOADS_PER_SHOP_DAY', '_LEGACY_MEDIA_SHOP_CAP_BYTES',
            '_PORTAL_CHAT_LEGACY_UNTIL', '_VI_CHARS_RE', '_VI_WORDS_RE')
_FUNCS = ('_employee_projection', 'api_hr_employees_list', 'api_hr_employees_get', 'stream_hr_employees',
          'api_public_employee_lookup', '_assert_owns_bot_customer', 'api_bot_messages_create', 'api_bot_customer_link',
          '_allowed_media_file', '_safe_image_content_type', '_sniff_image_type', '_legacy_media_usage_bytes',
          '_portal_chat_sig', '_portal_chat_link_ok', 'api_storage_upload', 'api_portal_upload', 'api_public_storage_file',
          '_resolve_portal_customer', '_inbox_handle_event', 'secure_ai_generate', '_anon_sales_chat_request')

SSE_CALLS = []
DEEPSEEK_CALLS = []
PERSISTED = []


def _fake_call_deepseek(messages, temperature, max_tokens, business_id, customer_id, api_key, tools=None):
    DEEPSEEK_CALLS.append({'messages': messages, 'max_tokens': max_tokens, 'business_id': business_id})
    return {'choices': [{'message': {'content': 'ok'}}], 'tools_used': []}


NS = {
    'db': DB, 'request': request, 'session': session, 'jsonify': jsonify, 'url_for': url_for, 'Response': Response,
    'os': os, 're': re, 'time': time, 'json': json, 'hmac': hmac, 'hashlib': hashlib,
    'datetime': datetime, 'timedelta': timedelta, 'timezone': timezone, 'requests': requests,
    'ObjectId': ObjectId, 'InvalidId': InvalidId, 'NoFile': NoFile, 'secure_filename': secure_filename,
    'media_fs': MEDIA_FS, 'inbox_channels': inbox_channels, 'app': types.SimpleNamespace(secret_key='unit-test-secret'),
    '_sse_tenant_match': lambda *a: {'$match': {}},
    '_sse_change_signal': lambda src, match, payload_colls=None: SSE_CALLS.append(payload_colls) or 'SSE',
    # secure_ai_generate
    'AIContextEngine': types.SimpleNamespace(build_context_prompt=lambda *a, **k: {'prompt': 'TENANT', 'business_name': 'BitPaw'}),
    'compose_booking_assistant_prompt': lambda *a, **k: 'SYSTEM', 'compose_system_prompt': lambda *a, **k: 'SYSTEM',
    'classify_objection': MagicMock(return_value=None), 'get_conversation_memory': MagicMock(return_value=''),
    'maybe_distill_memory_async': MagicMock(), 'BOOKING_TOOLS': [], 'SALES_TOOLS': [],
    '_call_deepseek_with_tools': _fake_call_deepseek, '_log_ai_run': lambda *a, **k: None,
    '_tenant_currency': lambda bid: 'USD', 'SAAS_PLANS': {}, 'SAAS_CURRENCIES': {},
    '_persist_chat_turn': lambda *a, **k: PERSISTED.append(a), '_booking_chat_history': lambda *a, **k: [],
    '_load_recent_chat_history': lambda *a, **k: [], '_booking_assistant_facts': lambda *a, **k: '',
    '_paused_holding_reply': lambda *a, **k: 'paused',
    # _inbox_handle_event
    '_inbox_after_customer_message': lambda *a, **k: None, '_inbox_walkin': lambda bid: 'Client',
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

# module con mà secure_ai_generate import bên trong hàm (stub, không gọi DeepSeek/DB thật)
_gw = types.ModuleType('ai_gateway')
_gw.allowed = lambda bid, feature: True
_gw.unavailable_reply = lambda bid, msg=None: {'ai_unavailable': True}
_gw.tag_request = lambda feature, bid=None: None
sys.modules['ai_gateway'] = _gw
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
os.environ['DEEPSEEK_API_KEY'] = 'unit-test-key'   # không có lệnh gọi thật: _call_deepseek_with_tools là bản giả
os.environ.pop('BITPAW_DESKTOP_MODE', None)

FLASK = Flask(__name__)
FLASK.secret_key = 'unit-test-secret'
FLASK.add_url_rule('/api/storage/file/<file_id>', 'api_storage_file', lambda file_id: '')
if 'api_public_storage_file' in NS:
    FLASK.add_url_rule('/api/public/storage/file/<file_id>', 'api_public_storage_file', NS['api_public_storage_file'])

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 64
GIF = b'GIF89a' + b'\x00' * 64
HTML = b'<html><script>alert(1)</script></html>' + b' ' * 32


def _need(*names):
    missing = [n for n in names if n not in NS]
    if missing:
        raise AssertionError(f'app.py is missing {missing} (fix not applied)')


@contextmanager
def _ctx(path='/', method='GET', user=None, role=None, bid=None, **kw):
    with FLASK.test_request_context(path, method=method, **kw):
        if user:
            session['user_id'] = user
            session['business_id'] = bid or user
            if role:
                session['role'] = role
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


def _upload_kw(data, name='photo.png', **fields):
    form = dict(fields)
    form['file'] = (io.BytesIO(data), name)
    return {'data': form, 'content_type': 'multipart/form-data'}


SECRET_FIELDS = ('luong_cb', 'luong_gio', 'phu_cap', 'toa_do_lat', 'toa_do_lng', 'trang_thai_gps', 'nhiem_vu_hien_tai', 'gps_at',
                 'face_template')


def _seed_employees():
    for i, (bid, code, name) in enumerate((('shopA', 'NV0001', 'Alice A'), ('shopA', 'NV0002', 'Bob A'),
                                           ('shopB', 'NV0001', 'Carol B'), ('shopB', 'NV0003', 'Dan B'))):
        DB.employees.insert_one({'id': i + 1, 'business_id': bid, 'ma_nv': code, 'ho_ten': name, 'linh_vuc': 'Nails',
                                 'chuc_vu': 'Tech', 'avatar_url': '/a.png', 'diem_kudo': 3, 'thu_tu_tua': i,
                                 'luong_cb': 9000000, 'luong_gio': 50000, 'phu_cap': 700000, 'toa_do_lat': 10.77,
                                 'toa_do_lng': 106.7, 'trang_thai_gps': 'online', 'nhiem_vu_hien_tai': 'job 5',
                                 'gps_at': '2026-10-31T08:00:00', 'face_template': [0.1, 0.2]})


# ================================================================ A. danh sách nhân viên theo vai trò
class EmployeeExposureTests(unittest.TestCase):
    def setUp(self):
        DB.reset()
        _seed_employees()
        SSE_CALLS.clear()

    def test_staff_list_is_directory_only(self):
        with _ctx('/api/hr/employees', user='staff-1', role='staff', bid='shopA'):
            status, body = _call('api_hr_employees_list')
        self.assertEqual(status, 200)
        rows = body['data']
        self.assertEqual(sorted(r['ma_nv'] for r in rows), ['NV0001', 'NV0002'])   # vẫn chỉ tiệm của mình
        for r in rows:
            for f in SECRET_FIELDS:
                self.assertNotIn(f, r, f'staff must not see {f}')
            for f in ('ma_nv', 'ho_ten', 'avatar_url', 'linh_vuc'):   # app_nhanvien / app_chat cần các trường này
                self.assertIn(f, r)

    def test_session_without_role_is_treated_as_staff(self):
        with _ctx('/api/hr/employees', user='u-x', bid='shopA'):
            session.pop('role', None)
            status, body = _call('api_hr_employees_list')
        self.assertTrue(all('luong_cb' not in r for r in body['data']))

    def test_admin_list_keeps_payroll_fields(self):
        with _ctx('/api/hr/employees', user='owner-a', role='admin', bid='shopA'):
            status, body = _call('api_hr_employees_list')
        self.assertEqual(status, 200)
        self.assertTrue(all(r['luong_cb'] == 9000000 and r['toa_do_lat'] == 10.77 for r in body['data']))
        self.assertTrue(all('face_template' not in r for r in body['data']))

    def test_staff_get_one_hides_salary_but_keeps_login_fields(self):
        with _ctx('/api/hr/employees/NV0002', user='staff-1', role='staff', bid='shopA'):
            status, body = _call('api_hr_employees_get', 'NV0002')
        self.assertEqual(status, 200)
        emp = body['data']
        self.assertEqual((emp['ma_nv'], emp['ho_ten'], emp['linh_vuc'], emp['avatar_url']), ('NV0002', 'Bob A', 'Nails', '/a.png'))
        for f in SECRET_FIELDS:
            self.assertNotIn(f, emp)
        with _ctx('/api/hr/employees/NV0002', user='owner-a', role='admin', bid='shopA'):
            self.assertEqual(_call('api_hr_employees_get', 'NV0002')[1]['data']['phu_cap'], 700000)

    def test_stream_payload_has_gps_only_for_admin(self):
        with _ctx('/api/stream/hr_employees', user='staff-1', role='staff', bid='shopA'):
            NS['stream_hr_employees']()
        with _ctx('/api/stream/hr_employees', user='owner-a', role='admin', bid='shopA'):
            NS['stream_hr_employees']()
        staff_fields, admin_fields = SSE_CALLS[0]['employees'], SSE_CALLS[1]['employees']
        self.assertFalse({'toa_do_lat', 'toa_do_lng', 'trang_thai_gps', 'nhiem_vu_hien_tai', 'gps_at'} & set(staff_fields))
        self.assertIn('toa_do_lat', admin_fields)


# ================================================================ B. tra cứu mã nhân viên (Fast Check-in)
class EmployeeLookupTests(unittest.TestCase):
    def setUp(self):
        DB.reset()
        _seed_employees()

    def test_anonymous_lookup_reveals_nothing(self):
        with _ctx('/api/public/hr/employees/lookup?ma_nv=NV0001'):
            status, body = _call('api_public_employee_lookup')
        self.assertEqual(status, 401)
        self.assertNotIn('Alice', json.dumps(body))
        self.assertNotIn('Carol', json.dumps(body))

    def test_lookup_never_crosses_shops(self):
        with _ctx('/api/public/hr/employees/lookup?ma_nv=NV0003', user='owner-a', role='admin', bid='shopA'):
            status, body = _call('api_public_employee_lookup')
        self.assertEqual(status, 404)            # NV0003 chỉ có ở shopB
        self.assertNotIn('Dan B', json.dumps(body))
        with _ctx('/api/public/hr/employees/lookup?ma_nv=NV0001', user='owner-a', role='admin', bid='shopA'):
            status, body = _call('api_public_employee_lookup')
        self.assertEqual(status, 200)
        self.assertEqual(body['data'], {'ma_nv': 'NV0001', 'ho_ten': 'Alice A'})   # đúng tiệm, chỉ 2 trường

    def test_lookup_has_its_own_rate_limit(self):
        self.assertTrue(any(d.startswith('limiter.limit(') for d in DECORATORS['api_public_employee_lookup']),
                        DECORATORS['api_public_employee_lookup'])

    def test_fast_checkin_button_only_rendered_for_signed_in_users(self):
        """Lý do route đòi phiên đăng nhập: nút mở Fast Check-in (index.html) chỉ nằm trong khối {% if session.get('user_id') %}."""
        s = _read('templates/index.html')
        start = s.index("{% if session.get('user_id') %}")
        btn = s.index('onclick="openFastCheckin()"')
        depth, els = 0, None
        for m in re.finditer(r'\{%-?\s*(if|endif|else|elif)\b', s[start:]):
            tag = m.group(1)
            if tag == 'if':
                depth += 1
            elif tag == 'endif':
                depth -= 1
            elif depth == 1:
                els = start + m.start()   # {% else %} / {% elif %} của CHÍNH khối đăng nhập
                break
        self.assertIsNotNone(els)
        self.assertTrue(start < btn < els, (start, btn, els))
        self.assertEqual(s.count('openFastCheckin()') - s.count('function openFastCheckin()'), 1)   # không có lối mở nào khác


# ================================================================ C. stored XSS ở lịch sử chấm công Kỹ thuật
def _js_between(src, start_marker, end_marker):
    a = src.index(start_marker)
    return src[a:src.index(end_marker, a)]


class TechHistoryXssTests(unittest.TestCase):
    def test_history_rows_are_escaped(self):
        s = _read('templates/chamcong_kythuat.html')
        esc = '\n'.join(l for l in s.splitlines() if l.startswith('window.__escHtml') or l.startswith('window.__escJsAttr'))
        load_history = _js_between(s, 'async function loadHistory(', 'function viewPhoto(')
        rows = [{'ghi_chu': '<img src=x onerror=alert(1)>\nline2', 'trang_thai': 'Co mat<svg onload=alert(2)>',
                 'ngay_cham': '01/01/2026<b>x</b>', 'gio_den': '<i>8:00</i>',
                 'anh_checkin': "/api/storage/file/abc');alert(3);//", 'tang_ca': 2, 'phu_cap': 0, 'tien_tips': 0,
                 'latitude': "1');alert(5);//", 'longitude': 2}]
        js = ('const window = globalThis;\n' + esc + '\n'
              'const box = { innerHTML: "" };\n'
              'globalThis.document = { getElementById: () => box };\n'
              'globalThis.t = (k) => k;\n'
              'globalThis.hrApi = async () => ({ data: ' + json.dumps(rows) + ' });\n'
              + load_history + '\n'
              'loadHistory("NV1").then(() => process.stdout.write(JSON.stringify(box.innerHTML)));\n')
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'h.js')
            with io.open(p, 'w', encoding='utf-8') as f:
                f.write(js)
            r = subprocess.run(['node', p], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        html = json.loads(r.stdout)
        for bad in ('<img', '<svg', '<b>', '<i>8', "');alert(3)", "');alert(5)"):
            self.assertNotIn(bad, html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;<br>line2', html)   # xuống dòng vẫn giữ
        self.assertIn('2h OT', html)

    def test_template_scripts_still_parse(self):
        s = _read('templates/chamcong_kythuat.html')
        blocks = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', s, re.S)
        for i, code in enumerate(blocks):
            code = re.sub(r'\{\{.*?\}\}', '0', code)
            code = re.sub(r'\{%.*?%\}', '', code)
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, f's{i}.js')
                with io.open(p, 'w', encoding='utf-8') as f:
                    f.write(code)
                r = subprocess.run(['node', '--check', p], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(r.returncode, 0, f'script #{i}: {r.stderr[-400:]}')


# ================================================================ D. /api/bot/messages POST — kiểu customer_id
class BotMessagesTypeTests(unittest.TestCase):
    def setUp(self):
        DB.reset()
        DB.bot_customers.insert_one({'id': 'shopA:+15550001', 'business_id': 'shopA', 'channel': 'web'})
        DB.bot_customers.insert_one({'id': 'shopB:+15550002', 'business_id': 'shopB', 'channel': 'web'})

    def _post(self, body, bid='shopA'):
        with _ctx('/api/bot/messages', method='POST', user='owner-' + bid, role='admin', bid=bid, json=body):
            return _call('api_bot_messages_create')

    def test_operator_customer_id_is_rejected(self):
        status, _ = self._post({'customer_id': {'$in': ['shopA:+15550001', 'shopB:+15550002']}, 'content': 'hi'})
        self.assertEqual(status, 403)
        self.assertEqual(DB.bot_messages.count_documents({}), 0)

    def test_helper_requires_a_string_id_of_this_shop(self):
        _need('_assert_owns_bot_customer')
        self.assertFalse(NS['_assert_owns_bot_customer']({'$ne': None}, 'shopA'))
        self.assertFalse(NS['_assert_owns_bot_customer'](['shopA:+15550001'], 'shopA'))
        self.assertFalse(NS['_assert_owns_bot_customer']('shopB:+15550002', 'shopA'))
        self.assertTrue(NS['_assert_owns_bot_customer']('shopA:+15550001', 'shopA'))

    def test_own_conversation_reply_still_works(self):
        status, body = self._post({'customer_id': 'shopA:+15550001', 'content': 'See you at 3pm'})
        self.assertEqual(status, 200)
        self.assertTrue(body['success'])
        self.assertEqual(DB.bot_messages.find_one({})['customer_id'], 'shopA:+15550001')
        status, _ = self._post({'customer_id': 'shopB:+15550002', 'content': 'x'})
        self.assertEqual(status, 403)


# ================================================================ E. /api/storage/upload
class StorageUploadTests(unittest.TestCase):
    def setUp(self):
        DB.reset()

    def _up(self, data, name='photo.png', bid='shopA', **fields):
        with _ctx('/api/storage/upload', method='POST', user='staff-1', role='staff', bid=bid, **_upload_kw(data, name, **fields)):
            return _call('api_storage_upload')

    def test_client_kind_cannot_make_a_file_public(self):
        for kind in ('brand_logo', 'portal_chat', 'product_image', 'social_upload', 'ai_video'):
            status, body = self._up(PNG, kind=kind)
            self.assertEqual(status, 200, body)
            self.assertEqual(DB['media.files'].find_one({'_id': ObjectId(body['file_id'])})['kind'], 'misc')
        status, body = self._up(PNG, kind='checkin')
        self.assertEqual(DB['media.files'].find_one({'_id': ObjectId(body['file_id'])})['kind'], 'checkin')

    def test_every_kind_the_frontends_send_is_kept(self):
        for kind in ('avatar', 'checkin', 'evidence', 'signature', 'chat', 'job_photo', 'job_signature', 'misc'):
            status, body = self._up(JPEG, name='a.jpg', kind=kind)
            self.assertEqual(status, 200, (kind, body))
            self.assertEqual(DB['media.files'].find_one({'_id': ObjectId(body['file_id'])})['kind'], kind)

    def test_non_image_bytes_are_rejected(self):
        status, body = self._up(HTML, name='x.png', kind='checkin')
        self.assertEqual(status, 400)
        self.assertEqual(DB['media.files'].count_documents({}), 0)

    def test_content_type_comes_from_the_bytes(self):
        status, body = self._up(GIF, name='x.png', kind='chat')
        self.assertEqual(DB['media.files'].find_one({'_id': ObjectId(body['file_id'])})['contentType'], 'image/gif')

    def test_size_cap_and_shop_quota(self):
        _need('_STORAGE_UPLOAD_MAX_BYTES', '_LEGACY_MEDIA_SHOP_CAP_BYTES')
        big = PNG + b'\x00' * NS['_STORAGE_UPLOAD_MAX_BYTES']
        self.assertEqual(self._up(big, kind='checkin')[0], 413)
        DB['media.files'].insert_one({'business_id': 'shopA', 'kind': 'checkin', 'length': NS['_LEGACY_MEDIA_SHOP_CAP_BYTES']})
        self.assertEqual(self._up(PNG, kind='checkin')[0], 413)
        # AI Studio media (media_store có trần riêng) không tính vào trần này; tiệm khác không bị ảnh hưởng
        self.assertEqual(self._up(PNG, kind='checkin', bid='shopB')[0], 200)
        DB['media.files'].insert_one({'business_id': 'shopC', 'kind': 'ai_video', 'length': NS['_LEGACY_MEDIA_SHOP_CAP_BYTES']})
        self.assertEqual(self._up(PNG, kind='checkin', bid='shopC')[0], 200)

    def test_route_has_its_own_rate_limit(self):
        self.assertTrue(any(d.startswith('limiter.limit(') for d in DECORATORS['api_storage_upload']))


# ================================================================ F + G. ảnh chat CSKH: tải lên + link công khai
class PortalMediaTests(unittest.TestCase):
    CID = 'shopA:+15550001'

    def setUp(self):
        DB.reset()
        DB.bot_customers.insert_one({'id': self.CID, 'business_id': 'shopA', 'channel': 'web'})

    def _up(self, data, name='p.jpg', cid=None):
        with _ctx('/api/portal/upload', method='POST', **_upload_kw(data, name, customer_id=cid or self.CID)):
            return _call('api_portal_upload')

    def _get(self, url):
        path, _, qs = url.partition('?')
        fid = path.rsplit('/', 1)[1]
        with _ctx(url):
            return _call('api_public_storage_file', fid)

    def test_non_image_rejected_and_real_image_gets_signed_link(self):
        self.assertEqual(self._up(HTML, name='x.png')[0], 400)
        status, body = self._up(JPEG)
        self.assertEqual(status, 200, body)
        self.assertRegex(body['url'], r'^/api/public/storage/file/[0-9a-f]{24}\?sig=[0-9a-f]{32}$')
        doc = DB['media.files'].find_one({'_id': ObjectId(body['file_id'])})
        self.assertEqual((doc['kind'], doc['business_id'], doc['customer_id'], doc['contentType']),
                         ('portal_chat', 'shopA', self.CID, 'image/jpeg'))
        self.assertEqual(self._get(body['url'])[0], 200)
        # chỉ biết ObjectId (đoán/dò được) thì không đọc được ảnh chat
        self.assertEqual(self._get(body['url'].split('?')[0])[0], 404)
        self.assertEqual(self._get(body['url'].split('?')[0] + '?sig=' + '0' * 32)[0], 404)

    def test_portal_size_cap_and_daily_caps(self):
        _need('_PORTAL_UPLOAD_MAX_BYTES', '_PORTAL_UPLOADS_PER_CONVERSATION_DAY', '_PORTAL_UPLOADS_PER_SHOP_DAY')
        self.assertEqual(self._up(JPEG + b'\x00' * NS['_PORTAL_UPLOAD_MAX_BYTES'])[0], 413)
        now = datetime.now(timezone.utc)
        for _ in range(NS['_PORTAL_UPLOADS_PER_CONVERSATION_DAY']):
            DB['media.files'].insert_one({'business_id': 'shopA', 'kind': 'portal_chat', 'customer_id': self.CID,
                                          'uploaded_at': now, 'length': 10})
        self.assertEqual(self._up(JPEG)[0], 429)
        DB.reset()
        DB.bot_customers.insert_one({'id': self.CID, 'business_id': 'shopA', 'channel': 'web'})
        for i in range(NS['_PORTAL_UPLOADS_PER_SHOP_DAY']):
            DB['media.files'].insert_one({'business_id': 'shopA', 'kind': 'portal_chat', 'customer_id': f'shopA:+1{i}',
                                          'uploaded_at': now, 'length': 10})
        self.assertEqual(self._up(JPEG)[0], 429)
        # ảnh của hôm qua không còn tính
        for d in DB['media.files'].docs:
            d['uploaded_at'] = now - timedelta(days=2)
        self.assertEqual(self._up(JPEG)[0], 200)

    def test_private_files_answer_like_missing_ones(self):
        oid = MEDIA_FS.put(PNG, business_id='shopA', kind='checkin', content_type='image/png')
        status_private, _ = self._get(f'/api/public/storage/file/{oid}')
        status_missing, _ = self._get(f'/api/public/storage/file/{ObjectId()}')
        self.assertEqual((status_private, status_missing), (404, 404))

    def test_brand_and_product_images_stay_public_without_signature(self):
        for kind in ('brand_logo', 'brand_cover', 'product_image'):
            oid = MEDIA_FS.put(PNG, business_id='shopA', kind=kind, content_type='image/png')
            self.assertEqual(self._get(f'/api/public/storage/file/{oid}')[0], 200, kind)

    def test_legacy_unsigned_chat_links_only_during_migration_window(self):
        _need('_PORTAL_CHAT_LEGACY_UNTIL', '_portal_chat_sig')
        old = MEDIA_FS.put(JPEG, business_id='shopA', kind='portal_chat', content_type='image/jpeg')   # trước bản vá: không cờ
        saved = NS['_PORTAL_CHAT_LEGACY_UNTIL']
        try:
            NS['_PORTAL_CHAT_LEGACY_UNTIL'] = (datetime.now(timezone.utc) + timedelta(days=5)).strftime('%Y-%m-%d')
            self.assertEqual(self._get(f'/api/public/storage/file/{old}')[0], 200)
            NS['_PORTAL_CHAT_LEGACY_UNTIL'] = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
            self.assertEqual(self._get(f'/api/public/storage/file/{old}')[0], 404)
            # link cũ được ký lại (thêm ?sig=) vẫn mở được sau hạn
            self.assertEqual(self._get(f'/api/public/storage/file/{old}?sig={NS["_portal_chat_sig"](str(old))}')[0], 200)
        finally:
            NS['_PORTAL_CHAT_LEGACY_UNTIL'] = saved

    def test_portal_chat_link_still_renders_in_widgets(self):
        """portal.html (MEDIA_RE) và chat.html (safeUrl) phải nhận link có ?sig=."""
        url = '/api/public/storage/file/' + 'a' * 24 + '?sig=' + 'b' * 32
        portal = _read('templates/portal.html')
        media_re = re.search(r"const MEDIA_RE = /(.+)/;", portal).group(1)
        js = f"const re = /{media_re}/; const m = ('[IMG]{url}').match(re); process.stdout.write(m ? m[2] : 'NO');"
        r = subprocess.run(['node', '-e', js], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(r.stdout, url, r.stderr)


# ================================================================ H. SĐT gõ trong Messenger/Zalo
class InboxPhoneLinkTests(unittest.TestCase):
    def setUp(self):
        DB.reset()
        DB.customers.insert_one({'id': 7, 'business_id': 'shopA', 'name': 'Jane', 'phone': '0412 345 678', 'fb_psid': 'JANE_PSID'})
        DB.customers.insert_one({'id': 8, 'business_id': 'shopA', 'name': 'Kim', 'phone': '0412 999 111'})

    def _event(self, user, text, mid):
        doc = {'business_id': 'shopA', 'channel': 'messenger', 'status': 'connected'}
        NS['_inbox_handle_event'](doc, {'kind': 'customer', 'user_id': user, 'text': text, 'ext_msg_id': mid,
                                        'name': None, 'phone': None})

    def test_typed_phone_never_repoints_an_existing_customer(self):
        self._event('ATTACKER_PSID', 'hi, my number is 0412 345 678', 'm1')
        self.assertEqual(DB.customers.find_one({'id': 7})['fb_psid'], 'JANE_PSID')
        conv = DB.bot_customers.find_one({'id': 'shopA:messenger:ATTACKER_PSID'})
        self.assertEqual(conv['phone'], '0412345678')   # AI vẫn có SĐT để hỏi đáp/đặt lịch như trước
        pending = conv.get('pending_customer_link') or {}
        self.assertEqual((pending.get('customer_id'), pending.get('field'), pending.get('user_id')), (7, 'fb_psid', 'ATTACKER_PSID'))

    def test_typed_phone_links_a_unique_customer_without_channel(self):
        # h4b: hồ sơ DUY NHẤT có SĐT này và chưa có id Messenger -> tự gắn (không ghi đè ai); không cần chủ tiệm duyệt
        self._event('PSID_K', 'call me 0412999111', 'm2')
        self.assertEqual(DB.customers.find_one({'id': 8})['fb_psid'], 'PSID_K')
        self.assertNotIn('pending_customer_link', DB.bot_customers.find_one({'id': 'shopA:messenger:PSID_K'}))

    def test_second_number_in_same_conversation_links_nothing(self):
        self._event('PSID_Z', 'my number 0412 000 222', 'm3')       # không khớp ai, nhưng hội thoại đã có SĐT
        self.assertIsNone(inbox_channels.capture_phone('shopA:messenger:PSID_Z', 'actually 0412 345 678'))
        self._event('PSID_Z', 'actually 0412 345 678', 'm4')
        self.assertNotIn('pending_customer_link', DB.bot_customers.find_one({'id': 'shopA:messenger:PSID_Z'}))

    def test_owner_confirms_or_dismisses_the_pending_link(self):
        _need('api_bot_customer_link')
        # 2 hồ sơ cùng SĐT -> không tự gắn (h4b), thành liên kết chờ duyệt cho hồ sơ đầu tiên (Kim, id 8)
        DB.customers.insert_one({'id': 9, 'business_id': 'shopA', 'name': 'Kim (old card)', 'phone': '+61 412 999 111'})
        self._event('PSID_K', 'call me 0412999111', 'm2')
        conv_id = 'shopA:messenger:PSID_K'
        with _ctx('/api/bot/customer_link', method='POST', user='owner-b', role='admin', bid='shopB',
                  json={'customer_id': conv_id, 'confirm': True}):
            self.assertEqual(_call('api_bot_customer_link')[0], 403)      # tiệm khác
        with _ctx('/api/bot/customer_link', method='POST', user='owner-a', role='admin', bid='shopA',
                  json={'customer_id': {'$ne': None}, 'confirm': True}):
            self.assertEqual(_call('api_bot_customer_link')[0], 403)      # toán tử thay vì chuỗi
        with _ctx('/api/bot/customer_link', method='POST', user='owner-a', role='admin', bid='shopA',
                  json={'customer_id': conv_id, 'confirm': True}):
            status, body = _call('api_bot_customer_link')
        self.assertEqual(status, 200, body)
        self.assertEqual(DB.customers.find_one({'id': 8})['fb_psid'], 'PSID_K')
        self.assertNotIn('pending_customer_link', DB.bot_customers.find_one({'id': conv_id}))
        # bỏ qua: không gắn gì
        self._event('ATTACKER_PSID', 'hi, my number is 0412 345 678', 'm9')
        with _ctx('/api/bot/customer_link', method='POST', user='owner-a', role='admin', bid='shopA',
                  json={'customer_id': 'shopA:messenger:ATTACKER_PSID', 'confirm': False}):
            self.assertEqual(_call('api_bot_customer_link')[0], 200)
        self.assertEqual(DB.customers.find_one({'id': 7})['fb_psid'], 'JANE_PSID')
        self.assertTrue(any('admin' in d for d in DECORATORS['api_bot_customer_link']))


# ================================================================ I. bot bán phần mềm ẩn danh: trần chi phí chung mỗi ngày
class SalesBotBudgetTests(unittest.TestCase):
    def setUp(self):
        DB.reset()
        DEEPSEEK_CALLS.clear()
        PERSISTED.clear()
        NS['classify_objection'].reset_mock()
        os.environ['SALES_BOT_DAILY_CAP'] = '3'

    def tearDown(self):
        os.environ.pop('SALES_BOT_DAILY_CAP', None)

    def _gen(self, body, user=None):
        with _ctx('/api/ai/studio/generate', method='POST', user=user, role='admin' if user else None, json=body):
            return _call('secure_ai_generate')

    def test_anonymous_sales_chat_stops_calling_deepseek_after_daily_cap(self):
        for i in range(3):
            status, body = self._gen({'userPrompt': f'how much is BitPaw? {i}', 'industry': 'nail'})
            self.assertNotIn('fallback', body)
        self.assertEqual(len(DEEPSEEK_CALLS), 3)
        status, body = self._gen({'userPrompt': 'how much is BitPaw?', 'industry': 'nail'})
        self.assertEqual(status, 200)
        self.assertTrue(body.get('fallback'))
        self.assertIn('BitPaw team', body['choices'][0]['message']['content'])
        self.assertEqual(len(DEEPSEEK_CALLS), 3, 'no DeepSeek call once the daily cap is reached')
        self.assertEqual(NS['classify_objection'].call_count, 3, 'the objection router (also DeepSeek) is skipped too')
        status, body = self._gen({'userPrompt': 'giá bao nhiêu vậy?', 'industry': 'nail'})
        self.assertIn('BitPaw', body['choices'][0]['message']['content'])
        self.assertIn('Dạ', body['choices'][0]['message']['content'])

    def test_booking_chats_and_signed_in_users_are_not_counted(self):
        DB.businesses.insert_one({'id': 'shopA', 'name': 'Shop A'})   # h4a: chat đặt lịch chỉ chạy cho tiệm có thật
        for _ in range(5):
            self._gen({'context': 'customer_booking', 'business_id': 'shopA', 'customer_message': 'book a gel mani'})
            self._gen({'userPrompt': 'internal test', 'industry': 'nail'}, user='owner-a')
        self.assertEqual(len(DEEPSEEK_CALLS), 10)
        self.assertNotIn('fallback', self._gen({'userPrompt': 'hello', 'industry': 'nail'})[1])

    def test_anonymous_prompt_and_tokens_are_cut(self):
        self._gen({'userPrompt': 'x' * 50000, 'industry': 'nail', 'max_tokens': 2000})
        call = DEEPSEEK_CALLS[-1]
        self.assertLessEqual(len(call['messages'][-1]['content']), 2000)
        self.assertLessEqual(call['max_tokens'], 600)

    def test_extra_daily_ip_limit_only_for_anonymous_sales_chat(self):
        _need('_anon_sales_chat_request')
        decos = DECORATORS['secure_ai_generate']
        self.assertTrue(any('per day' in d and 'exempt_when' in d for d in decos), decos)
        with _ctx('/x', method='POST', json={'userPrompt': 'hi'}):
            self.assertTrue(NS['_anon_sales_chat_request']())
        with _ctx('/x', method='POST', json={'context': 'customer_booking'}):
            self.assertFalse(NS['_anon_sales_chat_request']())
        with _ctx('/x', method='POST', user='owner-a', json={'userPrompt': 'hi'}):
            self.assertFalse(NS['_anon_sales_chat_request']())
        with _ctx('/x', method='POST', data='not json', content_type='text/plain'):
            self.assertTrue(NS['_anon_sales_chat_request']())


class CompileTests(unittest.TestCase):
    def test_py_compile_touched_files(self):
        import py_compile
        for rel in ('app.py', 'inbox_channels.py'):
            py_compile.compile(os.path.join(ROOT, rel), doraise=True)


if __name__ == '__main__':
    if MISSING:
        print('NOTE: app.py has no', MISSING)
    unittest.main(verbosity=2)
