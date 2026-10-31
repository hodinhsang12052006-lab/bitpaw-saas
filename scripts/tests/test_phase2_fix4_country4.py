# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 vòng 4, khu "country4" (nước + tiền tệ của tiệm):
  1. Chủ tiệm (admin) SỬA ĐƯỢC nước + tiền tệ sau khi đăng ký: mục "Quốc gia & tiền tệ" trên trang Cài đặt thương hiệu
     (/brand_settings) + API /api/business_region (GET/POST, chỉ admin, VI/EN). 'other' -> lưu 'OTHER' (ai_packs.shop_country
     = None, không đoán theo múi giờ / tiền tệ); 'auto' -> xoá tiền tệ đã lưu. Mỗi lần đổi ghi audit_logs (cũ -> mới).
  2. messaging.get_settings / save_settings: s['country'] = ai_packs.shop_country (không còn mặc định 'US') -> SĐT nhắc lịch /
     xin đánh giá / tin thử / nhân viên đọc CÙNG luật với lễ tân AI + mã SMS.
  3. TenantEngine.get_region_config: tiệm chưa có nước -> country '' + currency USD (không còn VN/VND); nước theo
     ai_packs.shop_country; tiền tệ chưa lưu: VN -> VND, AU -> AUD, còn lại -> USD.
  4. Đăng ký (/register + /auth/complete): CHỈ lưu tiền tệ app định dạng được (format_money / bp-currency.js: VND/USD/AUD);
     CA/NZ/GB -> chỉ lưu nước, tiền tệ để trống cho từng module tự theo nước (hotel / retail / nail_turns: CAD/NZD/GBP).
  5. ai_packs.hotel._country: theo ai_packs.shop_country (có bước múi giờ; 'SG' / 'OTHER' -> None).

Dùng lại DB giả + stub của test_phase2_receptionist_core.py (nạp TRƯỚC mọi import) và form đăng ký giả của
test_phase2_fix3_country.py: không import app.py thật, không MongoDB thật, không gọi mạng / Twilio / DeepSeek. Hàm của app.py
lấy nguyên mã nguồn qua ast; messaging.py THẬT nạp dưới tên khác (core thay 'messaging' bằng bản giả).
Chạy: python scripts/tests/test_phase2_fix4_country4.py
"""
import ast
import functools
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime
from itertools import count
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_receptionist_core as core  # noqa: E402  (DB giả, messaging giả, ai_packs thật)
import test_phase2_fix3_country as fix3  # noqa: E402  (/register + /auth/complete giả, cùng DB giả)

from flask import Flask, jsonify, redirect, request, session  # noqa: E402

import ai_packs  # noqa: E402
import booking_rules  # noqa: E402
import customer_context  # noqa: E402
import i18n  # noqa: E402
import ai_packs.hotel as hotel  # noqa: E402
from currency_utils import format_money  # noqa: E402
from tenant_engine import TenantEngine  # noqa: E402

DB, ROOT = core.DB, core.ROOT
_ids = count(9000)


def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------- messaging.py THẬT (tên khác, không đè bản giả của core)
if not hasattr(sys.modules['nurture_channel_tokens'], 'save_channel_token'):
    sys.modules['nurture_channel_tokens'].save_channel_token = MagicMock()
if 'email_service' not in sys.modules:
    _es = types.ModuleType('email_service')
    _es.EmailService = types.SimpleNamespace(send_email=MagicMock(side_effect=AssertionError('no e-mail in this test')))
    sys.modules['email_service'] = _es
_spec = importlib.util.spec_from_file_location('messaging_real_fix4', os.path.join(ROOT, 'messaging.py'))
MSG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MSG)


# ---------------------------------------------------------------- route của app.py (mã nguồn qua ast, GIỮ decorator quyền)
APP_SRC = core.APP_SRC
_TREE = ast.parse(APP_SRC)


def _is_app_route(dec):
    return (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name)
            and dec.func.value.id in ('app', 'limiter'))


def _route_of(node):
    """(đường dẫn, methods) của @app.route trên 1 hàm."""
    for dec in node.decorator_list:
        if _is_app_route(dec) and dec.func.attr == 'route':
            path = ast.literal_eval(dec.args[0])
            methods = next((ast.literal_eval(k.value) for k in dec.keywords if k.arg == 'methods'), ['GET'])
            return path, methods
    return None, None


def _decorator_names(node):
    out = []
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name):
            out.append((target.id, [ast.literal_eval(a) for a in dec.args] if isinstance(dec, ast.Call) else []))
    return out


AUDIT = []
NS = {
    'db': DB, 'request': request, 'session': session, 'jsonify': jsonify, 'redirect': redirect, 'datetime': datetime,
    're': re, 'wraps': functools.wraps, 'url_for': lambda name, **kw: '/' + name, 'flash': lambda *a, **k: None,
    'resolve_lang': i18n.resolve_lang, 'TenantEngine': TenantEngine, 'next_mongo_id': lambda c: next(_ids),
    '_wants_json': lambda: True,
}
ROUTES = {}
for _node in _TREE.body:
    if isinstance(_node, ast.FunctionDef) and _node.name in ('_vi_en', 'login_required', 'role_required', '_log_audit',
                                                               '_business_region_view', 'api_business_region_get',
                                                               'api_business_region_save'):
        _path, _methods = _route_of(_node)
        _node.decorator_list = [d for d in _node.decorator_list if not _is_app_route(d)]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), f'app.py::{_node.name}', 'exec'), NS)
        if _path:
            ROUTES[_node.name] = (_path, _methods)
    elif isinstance(_node, ast.Assign) and any(getattr(t, 'id', '') == '_REGION_CURRENCIES' for t in _node.targets):
        exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), 'app.py::_REGION_CURRENCIES', 'exec'), NS)

WEB = Flask('fix4_region')
WEB.secret_key = 'test'
for _name, (_path, _methods) in ROUTES.items():
    WEB.add_url_rule(_path, _name, NS[_name], methods=_methods)


def _biz(bid, **fields):
    DB.businesses.insert_one(dict({'id': bid, 'name': f'Shop {bid}', 'industry_code': 'nail'}, **fields))


def _row(bid):
    return DB.businesses.find_one({'id': bid}) or {}


# ================================================================ 1. chủ tiệm sửa nước + tiền tệ
class RegionRouteTests(core._Base):
    def setUp(self):
        super().setUp()
        booking_rules._CACHE.clear()
        self.c = WEB.test_client()

    def _login(self, bid, role='admin', client=None):
        with (client or self.c).session_transaction() as s:
            s['user_id'] = bid
            s['business_id'] = bid
            s['role'] = role

    def _post(self, body, lang='en'):
        return self.c.post('/api/business_region', json=body, headers={'Accept-Language': lang})

    def test_routes_exist_admin_only_on_the_brand_settings_api(self):
        self.assertIn('api_business_region_get', ROUTES, 'GET /api/business_region missing in app.py')
        self.assertIn('api_business_region_save', ROUTES, 'POST /api/business_region missing in app.py')
        self.assertEqual(ROUTES['api_business_region_get'], ('/api/business_region', ['GET']))
        self.assertEqual(ROUTES['api_business_region_save'], ('/api/business_region', ['POST']))
        for name in ROUTES:
            node = next(n for n in ast.parse(APP_SRC).body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(_decorator_names(node), [('login_required', []), ('role_required', ['admin', 'super_admin'])], name)

    def test_wrong_country_from_signup_can_be_corrected_and_is_audit_logged(self):
        """Tiệm Mỹ đăng ký từ IP Việt Nam để nguyên 'Việt Nam' -> country=VN, currency=VND. Chủ tiệm sửa thành US / USD."""
        _biz('us1', country='VN', currency='VND')
        self._login('us1')
        self.assertEqual(ai_packs.normalize_phone('(212) 555-1234', ai_packs.shop_country('us1')), '')   # trước khi sửa
        self.assertEqual(customer_context.business('us1')['country'], 'VN')   # nạp vào bộ nhớ đệm của lễ tân AI
        r = self.c.get('/api/business_region')
        self.assertEqual(r.status_code, 200)
        d = r.get_json()['data']
        self.assertEqual((d['country'], d['currency'], d['phone_country'], d['display_currency']), ('VN', 'VND', 'VN', 'VND'))
        self.assertEqual(d['countries'], list(ai_packs.SHOP_COUNTRIES) + ['other'])
        self.assertEqual(d['currencies'], ['USD', 'AUD', 'VND', 'CAD', 'NZD', 'GBP'])

        r = self._post({'country': 'US', 'currency': 'USD'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        body = r.get_json()
        self.assertTrue(body['success'] and body['changed'])
        self.assertEqual((_row('us1')['country'], _row('us1')['currency']), ('US', 'USD'))
        self.assertEqual((body['data']['country'], body['data']['currency']), ('US', 'USD'))
        # mọi module đọc theo nước mới
        self.assertEqual(ai_packs.shop_country('us1'), 'US')
        self.assertEqual(ai_packs.normalize_phone('(212) 555-1234', ai_packs.shop_country('us1')), '+12125551234')
        self.assertEqual(customer_context.business('us1')['country'], 'US')   # bộ nhớ đệm 20 giây của lễ tân AI đã xoá
        self.assertEqual(TenantEngine.get_region_config('us1'), {'country': 'US', 'currency': 'USD'})   # Square + '$'
        self.assertEqual(MSG.get_settings('us1')['country'], 'US')
        # nhật ký: ai, cũ -> mới
        logs = DB.audit_logs.find({'business_id': 'us1'})
        self.assertEqual(len(logs), 1)
        self.assertEqual((logs[0]['action'], logs[0]['entity_type'], logs[0]['user_id']), ('business_region_update', 'business', 'us1'))
        self.assertEqual(logs[0]['old_value'], {'country': 'VN', 'currency': 'VND'})
        self.assertEqual(logs[0]['new_value'], {'country': 'US', 'currency': 'USD'})
        # lưu lại y hệt: không ghi gì thêm
        r = self._post({'country': 'us', 'currency': 'usd'})
        self.assertEqual((r.status_code, r.get_json()['changed']), (200, False))
        self.assertEqual(len(DB.audit_logs.find({'business_id': 'us1'})), 1)

    def test_other_country_stops_guessing_and_auto_currency_unsets_it(self):
        _biz('o1', currency='VND')   # chưa có nước: shop_country đoán VN theo tiền tệ
        DB.messaging_settings.insert_one({'business_id': 'o1', 'timezone': 'Asia/Ho_Chi_Minh'})
        self._login('o1')
        d = self.c.get('/api/business_region').get_json()['data']
        self.assertEqual((d['country'], d['currency'], d['phone_country']), ('', 'VND', 'VN'))   # chưa lưu, đang đoán
        r = self._post({'country': 'other', 'currency': 'auto'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        row = _row('o1')
        self.assertEqual(row['country'], 'OTHER')
        self.assertNotIn('currency', row)
        self.assertIsNone(ai_packs.shop_country('o1'))   # chủ tiệm nói "nước khác": không đoán theo múi giờ / tiền tệ
        self.assertEqual(ai_packs.normalize_phone('0912 345 678', ai_packs.shop_country('o1')), '')
        self.assertEqual(ai_packs.normalize_phone('+65 9123 4567', ai_packs.shop_country('o1')), '+6591234567')
        self.assertEqual(TenantEngine.get_region_config('o1'), {'country': '', 'currency': 'USD'})
        d = r.get_json()['data']
        self.assertEqual((d['country'], d['currency'], d['phone_country'], d['display_currency']), ('other', 'auto', '', 'USD'))
        log = DB.audit_logs.find({'business_id': 'o1'})[-1]
        self.assertEqual((log['old_value'], log['new_value']), ({'country': None, 'currency': 'VND'}, {'country': 'OTHER', 'currency': None}))

    def test_canada_shop_can_pick_cad_or_automatic(self):
        _biz('ca1', country='CA', currency='USD')   # đăng ký cũ: CA lưu cứng USD
        self._login('ca1')
        self.assertEqual(self._post({'country': 'CA', 'currency': 'CAD'}).status_code, 200)
        self.assertEqual(_row('ca1')['currency'], 'CAD')
        self.assertEqual(TenantEngine.get_region_config('ca1'), {'country': 'CA', 'currency': 'CAD'})
        self.assertEqual(hotel._currency(_row('ca1')), 'CAD')
        self.assertEqual(self._post({'country': 'CA', 'currency': 'auto'}).status_code, 200)
        self.assertNotIn('currency', _row('ca1'))
        self.assertEqual(hotel._currency(_row('ca1')), 'CAD')                            # module tự theo nước
        # fix5: 'Theo quốc gia' = CAD ở mọi nơi (currency_utils.shop_currency; format_money: 'CA$45.00')
        self.assertEqual(TenantEngine.get_region_config('ca1'), {'country': 'CA', 'currency': 'CAD'})

    def test_bad_input_is_refused_in_the_viewer_language(self):
        _biz('b1', country='AU', currency='AUD')
        self._login('b1')
        for body in ({}, {'country': ''}, {'country': 'DE', 'currency': 'EUR'}, {'country': 'ZZ<script>'}, {'country': None}):
            r = self._post(body)
            self.assertEqual(r.status_code, 400, body)
            self.assertEqual(r.get_json()['message'], 'Please choose your shop country.')
        r = self._post({'country': 'AU', 'currency': 'EUR'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('currency', r.get_json()['message'].lower())
        r = self._post({'country': 'AU', 'currency': 'EUR'}, lang='vi')
        self.assertIn('Tiền tệ', r.get_json()['message'])
        r = self._post({'country': ''}, lang='vi')
        self.assertEqual(r.get_json()['message'], 'Hãy chọn quốc gia của tiệm.')
        r = self.c.post('/api/business_region', data='not json', content_type='text/plain')
        self.assertEqual(r.status_code, 400)
        self.assertEqual((_row('b1')['country'], _row('b1')['currency']), ('AU', 'AUD'))   # không đổi gì
        self.assertEqual(DB.audit_logs.find({}), [])

    def test_only_the_owner_of_this_shop_and_only_admins(self):
        _biz('own', country='AU', currency='AUD')
        _biz('other_shop', country='US', currency='USD')
        # chưa đăng nhập
        self.assertEqual(self.c.get('/api/business_region').status_code, 401)
        self.assertEqual(self._post({'country': 'VN', 'currency': 'VND'}).status_code, 401)
        # nhân viên / quản lý không phải admin
        for role in ('staff', 'manager', 'cashier'):
            self._login('own', role=role)
            self.assertEqual(self.c.get('/api/business_region').status_code, 403, role)
            self.assertEqual(self._post({'country': 'VN', 'currency': 'VND'}).status_code, 403, role)
        self.assertEqual((_row('own')['country'], _row('own')['currency']), ('AU', 'AUD'))
        # admin chỉ sửa đúng tiệm trong phiên — business_id trong body bị bỏ qua
        self._login('own')
        r = self._post({'country': 'NZ', 'currency': 'NZD', 'business_id': 'other_shop', 'id': 'other_shop'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((_row('own')['country'], _row('own')['currency']), ('NZ', 'NZD'))
        self.assertEqual((_row('other_shop')['country'], _row('other_shop')['currency']), ('US', 'USD'))

    def test_missing_profile_is_not_invented(self):
        self.assertIn('api_business_region_save', ROUTES)
        self._login('ghost')
        self.assertEqual(self.c.get('/api/business_region').status_code, 404)
        self.assertEqual(self._post({'country': 'US', 'currency': 'USD'}).status_code, 404)
        self.assertEqual(DB.businesses.find({'id': 'ghost'}), [])   # không tạo hồ sơ tiệm rỗng

    def test_db_error_answers_honestly(self):
        _biz('e1', country='AU', currency='AUD')
        self._login('e1')
        with patch.object(DB.businesses, 'update_one', side_effect=RuntimeError('timeout')):
            r = self._post({'country': 'US', 'currency': 'USD'})
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.get_json()['success'])
        self.assertNotIn('timeout', r.get_json()['message'])
        self.assertEqual(DB.audit_logs.find({}), [])   # không ghi nhật ký cho thay đổi chưa xảy ra


class BrandSettingsTemplateTests(unittest.TestCase):
    SRC = _read('templates/brand_settings.html')

    def _section(self):
        m = re.search(r'<form id="regionForm".*?</form>', self.SRC, re.S)
        self.assertIsNotNone(m, 'country & currency section missing on brand_settings.html')
        return m.group(0)

    def _translations(self):
        m = re.search(r'const translations = (\{.*?\n        \});', self.SRC, re.S)
        js = m.group(1)
        out = {}
        for lang in ('vi', 'en'):
            block = re.search(lang + r': \{(.*?)\n            \}', js, re.S).group(1)
            out[lang] = {k: a or b for k, a, b in re.findall(r"""(\w+):\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""", block)}
        return out

    def test_section_offers_every_country_and_currency(self):
        sec = self._section()
        country = re.search(r'<select id="regionCountry".*?</select>', sec, re.S).group(0)
        currency = re.search(r'<select id="regionCurrency".*?</select>', sec, re.S).group(0)
        self.assertEqual(re.findall(r'<option value="([^"]*)"', country), [''] + list(ai_packs.SHOP_COUNTRIES) + ['other'])
        self.assertEqual(re.findall(r'<option value="([^"]*)"', currency), ['auto', 'USD', 'AUD', 'VND', 'CAD', 'NZD', 'GBP'])
        self.assertIn("'/api/business_region'", self.SRC)
        self.assertNotIn('required', re.search(r'<select id="regionCountry"[^>]*>', sec).group(0))   # JS báo lỗi VI/EN

    def test_every_label_is_translated_vi_and_en(self):
        tr = self._translations()
        keys = set(re.findall(r'data-i18n="([^"]+)"', self._section()))
        keys |= set(re.findall(r"t\('(brand_settings_(?:region|country|currency)_\w+)'\)", self.SRC))
        self.assertGreater(len(keys), 15)
        for k in sorted(keys):
            self.assertIn(k, tr['vi'], k)
            self.assertIn(k, tr['en'], k)
            self.assertNotEqual(tr['vi'][k], tr['en'][k] if k not in ('brand_settings_country_ca', 'brand_settings_country_nz') else None, k)
        # nói thật: đổi tiền tệ không quy đổi số đã ghi; CAD/NZD/GBP chưa định dạng được ở mọi màn hình
        self.assertIn('not convert', tr['en']['brand_settings_currency_no_convert'])
        self.assertIn('không quy đổi', tr['vi']['brand_settings_currency_no_convert'])
        self.assertIn('CAD', tr['en']['brand_settings_currency_partial'])
        self.assertIn('CAD', tr['vi']['brand_settings_currency_partial'])

    def test_page_still_renders(self):
        app = Flask('fix4_tpl', template_folder=os.path.join(ROOT, 'templates'), static_folder=os.path.join(ROOT, 'static'))
        app.add_url_rule('/', 'index', lambda: '')
        app.add_url_rule('/spa', 'spa', lambda: '')
        for lang in ('vi', 'en'):
            with app.test_request_context('/brand_settings'):
                from flask import render_template
                html = render_template('brand_settings.html', default_lang=lang, brand_name='Rose Nails', brand_color='#06b6d4',
                                       error_message=None)
            self.assertIn('id="regionForm"', html)
            self.assertIn('id="brandSettingsForm"', html)   # form thương hiệu cũ vẫn nguyên

    def test_region_script_behaviour(self):
        """Chạy THẬT đoạn script của trang trong node với DOM giả: tải -> ghi chú đúng; chọn CAD -> cảnh báo định dạng; chưa
        chọn nước -> báo lỗi, không gửi; lưu -> POST đúng JSON; tải lỗi -> khoá nút lưu; đổi ngôn ngữ -> dịch ghi chú."""
        if subprocess.run(['node', '--version'], capture_output=True).returncode != 0:
            self.skipTest('node not installed')
        code = re.search(r'<script type="module">(.*?)</script>', self.SRC, re.S).group(1)
        code = code.replace('{{ default_lang }}', 'en')
        code = re.sub(r'\{\{.*?\}\}', '', code, flags=re.S)
        sec = self._section()
        options = {sid: re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)<', re.search(r'<select id="%s".*?</select>' % sid, sec, re.S).group(0))
                   for sid in ('regionCountry', 'regionCurrency')}
        harness = r'''
const OPTIONS = %s;
const els = {};
function makeEl(id) {
  const el = { id, value: '', innerText: '', textContent: '', innerHTML: '', disabled: false, files: [], style: { setProperty() {} },
    _cls: new Set(), handlers: {}, options: (OPTIONS[id] || []).map(([v, t]) => ({ value: v, textContent: t })),
    addEventListener(type, fn) { (el.handlers[type] = el.handlers[type] || []).push(fn); },
    querySelector(sel) { const m = /option\[value="([^"]*)"\]/.exec(sel); return m ? (el.options.find(o => o.value === m[1]) || null) : null; },
    appendChild(o) { el.options.push(o); }, focus() { el.focused = true; }, getAttribute() { return null; }, setAttribute() {},
    closest() { return null; } };
  el.classList = { add: c => el._cls.add(c), remove: c => el._cls.delete(c), contains: c => el._cls.has(c),
    toggle: (c, on) => { const w = on === undefined ? !el._cls.has(c) : !!on; if (w) el._cls.add(c); else el._cls.delete(c); return w; } };
  return el;
}
const $ = id => els[id] || (els[id] = makeEl(id));
['regionCountryNote', 'regionCurrencyPartial'].forEach(id => $(id).classList.add('hidden'));
global.document = { getElementById: $, querySelectorAll: () => [], createElement: () => ({}), body: { style: { setProperty() {} } },
                    readyState: 'complete' };
global.localStorage = { getItem: () => null, setItem() {} };
console.error = () => {};
const calls = [];
let responder = () => ({ status: 200, body: { success: true, data: {} } });
global.fetch = async (url, init) => { calls.push([url, init || {}]); const r = responder(url, init || {});
  return { ok: r.status < 300, status: r.status, json: async () => r.body }; };
const tick = () => new Promise(r => setTimeout(r, 0));
function page() {
%s
}
(async () => {
  const out = {};
  responder = (url) => url.includes('/api/business_region') ? { status: 200, body: { success: true, data:
      { country: '', currency: 'AUD', phone_country: 'AU', display_currency: 'AUD' } } }
    : { status: 200, body: { success: true, data: {} } };
  page();
  for (let i = 0; i < 5; i++) await tick();
  out.load = { country: $('regionCountry').value, currency: $('regionCurrency').value, note: $('regionCountryNote').textContent,
               noteHidden: $('regionCountryNote').classList.contains('hidden'), partialHidden: $('regionCurrencyPartial').classList.contains('hidden') };
  $('regionCurrency').value = 'CAD';
  $('regionCurrency').handlers.change.forEach(f => f());
  out.cad = { partialHidden: $('regionCurrencyPartial').classList.contains('hidden') };
  const before = calls.length;
  await $('regionForm').handlers.submit[0]({ preventDefault() {} });
  out.noCountry = { posted: calls.length - before, toast: $('toast').innerText, focused: !!$('regionCountry').focused };
  responder = (url, init) => ({ status: 200, body: { success: true, changed: true, data:
      { country: 'US', currency: 'CAD', phone_country: 'US', display_currency: 'CAD' } } });
  $('regionCountry').value = 'US';
  await $('regionForm').handlers.submit[0]({ preventDefault() {} });
  const last = calls[calls.length - 1];
  out.save = { url: last[0], method: last[1].method, body: JSON.parse(last[1].body), toast: $('toast').innerText,
               noteHidden: $('regionCountryNote').classList.contains('hidden'), disabled: $('regionSaveBtn').disabled };
  responder = () => ({ status: 200, body: { success: true, data: { country: 'other', currency: 'EUR', phone_country: '' } } });
  page();
  for (let i = 0; i < 5; i++) await tick();
  out.other = { note: $('regionCountryNote').textContent, currency: $('regionCurrency').value,
                hasEur: $('regionCurrency').options.some(o => o.value === 'EUR') };
  $('langToggleBtn').handlers.click[$('langToggleBtn').handlers.click.length - 1]();
  out.vi = { note: $('regionCountryNote').textContent };
  responder = (url) => url.includes('/api/business_region') ? { status: 404, body: { success: false, message: 'Business profile not found.' } }
    : { status: 200, body: { success: true, data: {} } };
  page();
  for (let i = 0; i < 5; i++) await tick();
  out.fail = { note: $('regionCountryNote').textContent, disabled: $('regionSaveBtn').disabled,
               noteHidden: $('regionCountryNote').classList.contains('hidden') };
  process.stdout.write(JSON.stringify(out));
})().catch(e => { process.stdout.write('ERR ' + (e && e.stack || e)); process.exit(1); });
''' % (json.dumps(options), code)
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(harness)
        try:
            r = subprocess.run(['node', f.name], capture_output=True, text=True, encoding='utf-8', timeout=60)
        finally:
            os.unlink(f.name)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-1500:])
        out = json.loads(r.stdout)
        self.assertEqual((out['load']['country'], out['load']['currency']), ('', 'AUD'))
        self.assertEqual(out['load']['note'], 'Not saved yet: client phone numbers are currently read as Australia '
                                              '(from your time zone or currency).')
        self.assertFalse(out['load']['noteHidden'])
        self.assertTrue(out['load']['partialHidden'])
        self.assertFalse(out['cad']['partialHidden'])                       # CAD: nói thật là chưa định dạng được mọi nơi
        self.assertEqual(out['noCountry'], {'posted': 0, 'toast': 'Please choose your shop country.', 'focused': True})
        self.assertEqual((out['save']['url'], out['save']['method'], out['save']['body']),
                         ('/api/business_region', 'POST', {'country': 'US', 'currency': 'CAD'}))
        self.assertEqual(out['save']['toast'], 'Country and currency saved.')
        self.assertTrue(out['save']['noteHidden'])
        self.assertFalse(out['save']['disabled'])
        self.assertEqual(out['other']['note'], 'Other country: client phone numbers need their country code (+...).')
        self.assertEqual(out['other']['currency'], 'EUR')                   # tiền tệ cũ ngoài danh sách: không tự đổi
        self.assertTrue(out['other']['hasEur'])
        self.assertEqual(out['vi']['note'], 'Nước khác: số điện thoại của khách cần có mã nước (+...).')
        self.assertEqual(out['fail']['note'], 'Business profile not found.')
        self.assertTrue(out['fail']['disabled'])                            # chưa biết giá trị hiện tại: không cho lưu đè
        self.assertFalse(out['fail']['noteHidden'])

    def test_bp_currency_label_fixer_leaves_the_currency_names_alone(self):
        """bp-currency.js (tiệm USD/AUD) đổi '(VND)', '(₫)', 'VND/' và chữ 'VND' đứng một mình — tên tiền trong ô chọn không được
        bị đổi thành 'USD'."""
        sec = self._section()
        tr = self._translations()
        texts = re.findall(r'<option value="[A-Z]{3}"[^>]*>([^<]*)<', sec) + [tr[l][k] for l in tr for k in tr[l]
                                                                             if k.startswith('brand_settings_currency_')]
        for s in texts:
            self.assertIsNone(re.search(r'\((?:VND|VNĐ|vnđ|vnd|₫|đ)\)|\b(?:VND|VNĐ)\s*/|^\s*(?:₫|đ|VND|VNĐ)\s*$', s), s)

    def test_inline_scripts_still_parse(self):
        if subprocess.run(['node', '--version'], capture_output=True).returncode != 0:
            self.skipTest('node not installed')
        scripts = list(re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', self.SRC, re.S))
        self.assertTrue(scripts)
        for i, m in enumerate(scripts):
            code = re.sub(r'\{\{.*?\}\}', '0', m.group(1), flags=re.S)
            code = re.sub(r'\{%.*?%\}|\{#.*?#\}', '', code, flags=re.S)
            with tempfile.NamedTemporaryFile('w', suffix='.mjs', delete=False, encoding='utf-8') as f:
                f.write(code)
            try:
                r = subprocess.run(['node', '--check', f.name], capture_output=True, text=True, encoding='utf-8')
            finally:
                os.unlink(f.name)
            self.assertEqual(r.returncode, 0, f'brand_settings.html script#{i}: {r.stderr[-400:]}')


# ================================================================ 2. messaging: nước của SĐT = ai_packs.shop_country
class MessagingCountryTests(core._Base):
    def test_country_is_the_shop_country_resolver_never_a_silent_us(self):
        cases = [  # (businesses, messaging time zone) -> s['country']
            ({}, 'Australia/Sydney', 'AU'), ({}, None, ''), ({'country': 'OTHER'}, 'America/Chicago', ''),
            ({'country': 'SG', 'currency': 'USD'}, None, ''), ({'currency': 'VND'}, None, 'VN'), ({'currency': 'AUD'}, None, 'AU'),
            ({'country': 'us'}, None, 'US'), ({'country': 'UK'}, None, 'GB'), ({'country': 'VN', 'currency': 'VND'}, None, 'VN'),
        ]
        for n, (fields, tz, want) in enumerate(cases):
            bid = f'm{n}'
            _biz(bid, **fields)
            if tz:
                DB.messaging_settings.insert_one({'business_id': bid, 'timezone': tz})
            s = MSG.get_settings(bid)
            self.assertEqual(s['country'], want, (fields, tz))
            self.assertEqual(s['country'], ai_packs.shop_country(bid) or '', (fields, tz))
        self.assertEqual(MSG.get_settings('no-such-shop')['country'], '')

    def test_reminder_review_and_test_sms_read_au_numbers_for_an_au_time_zone_shop(self):
        """Checker: tiệm chưa có nước + múi giờ Australia/Sydney: lễ tân AI đọc '0412345678' = +61412345678, nhưng tin nhắc lịch /
        xin đánh giá trước đây dùng 'US' -> '' -> bỏ qua im lặng."""
        _biz('au_tz')
        DB.messaging_settings.insert_one({'business_id': 'au_tz', 'timezone': 'Australia/Sydney'})
        s = MSG.get_settings('au_tz')
        self.assertEqual(MSG.normalize_phone('0412345678', s['country']), '+61412345678')
        self.assertEqual(MSG.normalize_phone('0412345678', s['country']),
                         ai_packs.normalize_phone('0412345678', customer_context.business('au_tz')['country']))
        sms, _email = MSG._customer_contacts('au_tz', '0412 345 678', None, s)
        self.assertEqual(sms, '+61412345678')

    def test_unknown_shop_never_turns_a_national_number_into_a_us_one(self):
        _biz('nc')
        s = MSG.get_settings('nc')
        for raw in ('(212) 555-1234', '0412345678', '0912 345 678'):
            self.assertEqual(MSG.normalize_phone(raw, s['country']), '', raw)
        self.assertEqual(MSG.normalize_phone('+1 212 555 1234', s['country']), '+12125551234')
        # múi giờ / ngôn ngữ vẫn có giá trị mặc định dùng được (chỉ là giờ gửi tin, không phải nước của SĐT)
        self.assertEqual((s['timezone'], s['language']), ('America/New_York', 'en'))

    def test_time_zone_and_language_defaults_follow_the_same_country(self):
        _biz('cur_au', currency='AUD')     # trước đây: múi giờ mặc định New York (nước 'US' tự đặt)
        _biz('cur_vn', currency='VND')
        _biz('uk', country='UK')
        self.assertEqual((MSG.get_settings('cur_au')['timezone'], MSG.get_settings('cur_au')['language']), ('Australia/Sydney', 'en'))
        self.assertEqual((MSG.get_settings('cur_vn')['timezone'], MSG.get_settings('cur_vn')['language']), ('Asia/Ho_Chi_Minh', 'vi'))
        self.assertEqual(MSG.get_settings('uk')['timezone'], 'Europe/London')
        DB.messaging_settings.insert_one({'business_id': 'cur_vn', 'timezone': 'America/Chicago', 'language': 'en'})
        self.assertEqual((MSG.get_settings('cur_vn')['timezone'], MSG.get_settings('cur_vn')['language']), ('America/Chicago', 'en'))

    def test_save_settings_normalises_shop_numbers_with_the_shop_country(self):
        _biz('au_cur', currency='AUD')
        s = MSG.save_settings('au_cur', {'shop_phone': '0412 345 678', 'twilio_from': '0412 000 111'})
        self.assertEqual((s['shop_phone'], s['twilio_from']), ('+61412345678', '+61412000111'))
        # messaging_routes truyền country = get_settings()['country'] (giờ là '' cho tiệm chưa rõ nước): giữ nguyên số đã gõ
        _biz('nc2')
        s = MSG.save_settings('nc2', {'shop_phone': '(212) 555-1234', 'country': MSG.get_settings('nc2')['country']})
        self.assertEqual(s['shop_phone'], '(212) 555-1234')   # trước đây: +12125551234 (đoán là số Mỹ)
        s = MSG.save_settings('nc2', {'shop_phone': '+1 212 555 1234'})
        self.assertEqual(s['shop_phone'], '+12125551234')

    def test_db_error_reads_as_unknown_not_us(self):
        _biz('err', country='AU')
        with patch.object(ai_packs, 'shop_country', side_effect=RuntimeError('boom')):
            s = MSG.get_settings('err')
        self.assertEqual(s['country'], '')
        self.assertEqual(s['timezone'], 'America/New_York')


# ================================================================ 3. TenantEngine.get_region_config
class RegionConfigTests(core._Base):
    def test_no_silent_vn_vnd(self):
        cases = [  # (businesses fields | None = không có dòng, messaging time zone) -> region
            (None, None, {'country': '', 'currency': 'USD'}), ({}, None, {'country': '', 'currency': 'USD'}),
            ({'country': 'OTHER'}, 'Asia/Ho_Chi_Minh', {'country': '', 'currency': 'USD'}),
            ({'country': 'SG', 'currency': 'USD'}, None, {'country': '', 'currency': 'USD'}),
            ({'country': 'VN'}, None, {'country': 'VN', 'currency': 'VND'}), ({'country': 'AU'}, None, {'country': 'AU', 'currency': 'AUD'}),
            ({'country': 'US'}, None, {'country': 'US', 'currency': 'USD'}), ({'country': 'CA'}, None, {'country': 'CA', 'currency': 'CAD'}),
            ({'country': 'NZ'}, None, {'country': 'NZ', 'currency': 'NZD'}), ({'country': 'gb'}, None, {'country': 'GB', 'currency': 'GBP'}),
            ({'currency': 'VND'}, None, {'country': 'VN', 'currency': 'VND'}), ({'currency': 'aud'}, None, {'country': 'AU', 'currency': 'AUD'}),
            ({}, 'Australia/Perth', {'country': 'AU', 'currency': 'AUD'}), ({}, 'Asia/Ho_Chi_Minh', {'country': 'VN', 'currency': 'VND'}),
            ({'country': 'CA', 'currency': 'CAD'}, None, {'country': 'CA', 'currency': 'CAD'}),
            ({'country': 'US', 'currency': 'USD'}, 'Australia/Sydney', {'country': 'US', 'currency': 'USD'}),   # hồ sơ thắng
        ]
        for n, (fields, tz, want) in enumerate(cases):
            bid = f'r{n}'
            if fields is not None:
                _biz(bid, **fields)
            if tz:
                DB.messaging_settings.insert_one({'business_id': bid, 'timezone': tz})
            self.assertEqual(TenantEngine.get_region_config(bid), want, (fields, tz))
        self.assertEqual(TenantEngine.get_region_config(None), {'country': '', 'currency': 'USD'})
        self.assertEqual(TenantEngine.get_region_config(''), {'country': '', 'currency': 'USD'})

    def test_currency_always_formats_and_square_gate_needs_a_real_us_shop(self):
        _biz('us', country='US', currency='USD')
        _biz('blank')
        _biz('other', country='OTHER')
        for bid in ('blank', 'other', 'no-row'):
            region = TenantEngine.get_region_config(bid)
            self.assertFalse(format_money(1200.5, region['currency']).endswith('đ'), bid)   # không còn '1.201đ'
            self.assertFalse(region['country'] == 'US' and region['currency'] == 'USD', bid)   # Square chỉ cho tiệm Mỹ thật
        region = TenantEngine.get_region_config('us')
        self.assertTrue(region['country'] == 'US' and region['currency'] == 'USD')

    def test_db_errors_fall_back_to_usd_without_a_country(self):
        _biz('e', country='VN', currency='VND')
        with patch.object(DB.businesses, 'find_one', side_effect=RuntimeError('timeout')):
            self.assertEqual(TenantEngine.get_region_config('e'), {'country': '', 'currency': 'USD'})
        with patch.object(ai_packs, 'shop_country', side_effect=RuntimeError('boom')):
            self.assertEqual(TenantEngine.get_region_config('e'), {'country': '', 'currency': 'VND'})

    def test_country_comes_from_the_shared_resolver(self):
        src = _read('tenant_engine.py')
        fn = ast.get_source_segment(src, next(n for n in ast.walk(ast.parse(src))
                                              if isinstance(n, ast.FunctionDef) and n.name == 'get_region_config'))
        self.assertIn('shop_country', fn)
        self.assertNotIn("'VN'", re.sub(r'"""[\s\S]*?"""|#.*', '', fn).replace("{'VN': 'VND', 'AU': 'AUD'}", ''))


# ================================================================ 4. đăng ký: chỉ lưu tiền tệ app định dạng được
class SignupCurrencyTests(core._Base):
    def setUp(self):
        super().setUp()
        fix3.FLASHES.clear()
        self.c = fix3.REG.test_client()

    def _register(self, n, country):
        key = f'BP-FIX4-{n}'
        DB.license_codes.insert_one({'license_key': key, 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'hotel'})
        r = self.c.post('/register', data={'email': f'fix4-{n}@example.com', 'password': 'longpassword', 'business_type': 'hotel',
                                           'business_name': f'Hotel {n}', 'fullname': 'Owner', 'license_key': key,
                                           'country': country})
        self.assertEqual(r.status_code, 302, (n, fix3.FLASHES))
        return DB.businesses.find_one({'id': DB.users.find_one({'email': f'fix4-{n}@example.com'})['id']})

    def test_ca_nz_gb_store_the_country_but_no_currency(self):
        want = {'US': 'USD', 'AU': 'AUD', 'VN': 'VND', 'CA': None, 'NZ': None, 'GB': None}
        for n, (country, cur) in enumerate(want.items()):
            biz = self._register(n, country)
            self.assertEqual((biz.get('country'), biz.get('currency')), (country, cur), country)
            if cur is None:
                self.assertNotIn('currency', biz)
            else:   # tiền tệ đã lưu luôn được format_money / bp-currency.js định dạng đúng
                self.assertEqual(format_money(1250, cur), '1.250đ' if cur == 'VND' else '$1,250.00', country)
        # CA/NZ/GB: từng module tự theo nước — không gắn cứng 'USD' cho khách sạn / cửa hàng Canada
        for n, country in ((3, 'CA'), (4, 'NZ'), (5, 'GB')):
            biz = DB.businesses.find_one({'name': f'Hotel {n}'})
            self.assertEqual(hotel._currency(biz), {'CA': 'CAD', 'NZ': 'NZD', 'GB': 'GBP'}[country])
            self.assertEqual(TenantEngine.get_region_config(biz['id']),   # fix5: theo nước, không gắn cứng USD
                             {'country': country, 'currency': {'CA': 'CAD', 'NZ': 'NZD', 'GB': 'GBP'}[country]})
            self.assertEqual(ai_packs.shop_country(biz['id']), country)

    def test_signup_region_only_stores_formattable_currencies(self):
        fn = fix3.APP_NS['_signup_region']
        app = Flask('fix4_signup')
        for raw, want in (('US', {'country': 'US', 'currency': 'USD'}), ('au', {'country': 'AU', 'currency': 'AUD'}),
                          ('VN', {'country': 'VN', 'currency': 'VND'}), ('CA', {'country': 'CA'}), ('nz', {'country': 'NZ'}),
                          ('UK', {'country': 'GB'}), ('GB', {'country': 'GB'}), ('other', {'country': 'OTHER'}), ('', {}),
                          ('SG', {})):   # fix5: 'Nước khác' = dấu 'OTHER' như /api/business_region
            with app.test_request_context('/register', method='POST', data={'country': raw}):
                self.assertEqual(fn(request.form), want, raw)
        with app.test_request_context('/register', method='POST', data={}, headers={'X-Vercel-IP-Country': 'NZ'}):
            self.assertEqual(fn(request.form), {'country': 'NZ'})

    def test_oauth_signup_uses_the_same_rule(self):
        c = fix3.OAUTH.test_client()
        for n, (country, want) in enumerate((('GB', ('GB', None)), ('AU', ('AU', 'AUD')))):
            with c.session_transaction() as s:
                s['oauth_signup'] = {'provider': 'google', 'sub': f'g4-{n}', 'email': f'oa4-{n}@example.com', 'name': 'X',
                                     'ts': int(datetime.now().timestamp())}
            DB.license_codes.insert_one({'license_key': f'BP-OA4-{n}', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'retail'})
            r = c.post('/auth/complete', data={'license_key': f'BP-OA4-{n}', 'business_name': f'Shop OA4-{n}',
                                               'business_type': 'retail', 'country': country})
            self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
            biz = DB.businesses.find_one({'name': f'Shop OA4-{n}'})
            self.assertEqual((biz.get('country'), biz.get('currency')), want, country)


# ================================================================ 5. hotel._country = ai_packs.shop_country
class HotelCountryTests(core._Base):
    def _c(self, bid, **ctx):
        return hotel._Ctx(dict({'business_id': bid, 'channel': 'web', 'lang': 'en'}, **ctx))

    def test_hotel_uses_the_shared_resolver(self):
        _biz('h_tz')
        DB.messaging_settings.insert_one({'business_id': 'h_tz', 'timezone': 'Australia/Sydney'})
        _biz('h_sg', country='SG', currency='SGD')
        _biz('h_other', country='OTHER', currency='VND')
        _biz('h_cur', currency='AUD')
        _biz('h_none')
        for bid, want in (('h_tz', 'AU'), ('h_sg', None), ('h_other', None), ('h_cur', 'AU'), ('h_none', None)):
            self.assertEqual(hotel._country(self._c(bid)), want, bid)
            self.assertEqual(hotel._country(self._c(bid)), ai_packs.shop_country(bid), bid)
        self.assertEqual(hotel._country(self._c('h_none', country='US')), 'US')    # ctx (customer_context) vẫn thắng
        self.assertIsNone(hotel._country(self._c('h_none', country='SG')))         # nước chưa có luật -> không đoán
        # '0412 345 678' của khách sạn chỉ có múi giờ Úc = +61412345678
        self.assertTrue(hotel._same_phone('0412 345 678', '+61412345678', hotel._country(self._c('h_tz'))))
        self.assertFalse(hotel._same_phone('0912 345 678', '+6591234567', hotel._country(self._c('h_sg'))))

    def test_db_error_reads_as_unknown(self):
        _biz('h_err', country='AU')
        with patch.object(ai_packs, 'shop_country', side_effect=RuntimeError('boom')):
            self.assertIsNone(hotel._country(self._c('h_err')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
