# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 vòng 3, khu "country" (nước của tiệm cho mọi chỗ chuẩn hoá SĐT):
  1. Đăng ký mới (/register email + Google/Facebook /auth/complete) LƯU nước 2 chữ của tiệm: ô "Quốc gia của tiệm" trên
     form (chọn sẵn theo header X-Vercel-IP-Country), form cũ không có ô đó -> theo header, 'Nước khác' / không rõ -> không
     lưu; tiền tệ đi kèm theo quy ước sẵn có (VN -> VND, AU -> AUD, nước khác -> USD).
  2. ai_packs.shop_country(business): businesses.country -> múi giờ trang Nhắn tin -> tiền tệ -> None — 1 nguồn cho
     customer_context.business (ai_function_tools + ctx['country'] của gói) và reservations_core.country_of.
  3. reservations_core.e164, messaging.normalize_phone, ai_packs.retail._e164_local == ai_packs.normalize_phone ĐÚNG từng ca
     (không còn mặc định Mỹ / Việt; country_of không còn trả 'VN' cho quán Úc / Mỹ chưa nhập nước); bảng ca theo tiệm
     Mỹ / Úc / Việt / chưa rõ nước.
  4. ai_packs.retail.owner_filter: tiệm chưa có nước -> SĐT khách gõ (không có khoá E.164) vẫn so NGUYÊN chữ số với hold,
     chỉ KÈM mã trình duyệt của chính chat này.

Dùng lại DB giả + stub của test_phase2_receptionist_core.py (nạp TRƯỚC mọi import): không import app.py thật, không MongoDB
thật, không gọi mạng / DeepSeek / Twilio; hàm của app.py / messaging.py lấy nguyên mã nguồn qua ast.
Chạy: python scripts/tests/test_phase2_fix3_country.py
"""
import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_receptionist_core as core  # noqa: E402  (DB giả, messaging giả, ai_packs thật)

from flask import Flask, redirect, render_template_string, request, session  # noqa: E402

import ai_packs  # noqa: E402
import customer_context  # noqa: E402
import plans  # noqa: E402
import reservations_core as rc  # noqa: E402
from ai_packs import retail  # noqa: E402
from currency_utils import format_money  # noqa: E402

DB, T, ROOT = core.DB, core.T, core.ROOT
COUNTRIES = ('US', 'AU', 'VN', 'CA', 'NZ', 'GB')


def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def _source_funcs(rel, names, ns):
    """Hàm lấy nguyên mã nguồn (bỏ decorator) — không import module thật (messaging thật mở MongoDB / Twilio)."""
    tree = ast.parse(_read(rel))
    for name in names:
        node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
        if node is None:   # mã cũ chưa có hàm này -> các test cần nó báo lỗi rõ, không làm hỏng cả file
            continue
        node.decorator_list = []
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), f'{rel}::{name}', 'exec'), ns)
    return ns


MSG_NS = _source_funcs('messaging.py', ['normalize_phone'], {'re': re})
msg_normalize = MSG_NS['normalize_phone']

# ---------------------------------------------------------------- /register của app.py (mã nguồn qua ast, DB giả)
FLASHES, WELCOME = [], MagicMock()
APP_NS = {
    'db': DB, 'request': request, 'session': session, 'redirect': redirect, 're': re, 'uuid': uuid, 'datetime': datetime,
    'plans': plans, 'url_for': lambda name, **kw: '/' + name,
    'flash': lambda msg, cat=None: FLASHES.append((cat, msg)),
    'render_template': lambda name, **kw: f'render:{name}:{kw.get("active_tab")}',
    'csrf': types.SimpleNamespace(protect=lambda: None),
    'security_shield': types.SimpleNamespace(code_attempts_blocked=lambda ip: False, record_code_failure=lambda ip, k='': None),
    '_get_real_client_ip': lambda: '203.0.113.7', 'generate_password_hash': lambda p: 'hash:' + str(len(p)),
    '_send_welcome_email': WELCOME,
}
_source_funcs('app.py', ['_email_query', '_signup_region', 'register'], APP_NS)

REG = Flask('fix3_register')
REG.secret_key = 'test'
REG.add_url_rule('/register', 'register', APP_NS['register'], methods=['GET', 'POST'])

# ---------------------------------------------------------------- /auth/complete (oauth_login.py thật, 'app' giả gọn)
_fake_app = types.ModuleType('app')
_fake_app.INDUSTRY_CONFIG = {'nail': {'name': 'Nails'}, 'fnb': {'name': 'Nhà hàng'}, 'retail': {'name': 'Bán lẻ'}}
_fake_app._send_welcome_email = MagicMock()
_fake_app._signup_region = APP_NS.get('_signup_region')
_fake_app.csrf = types.SimpleNamespace(protect=lambda: None)
_fake_app._ensure_primary_membership = lambda *a, **k: None
_fake_app._get_real_client_ip = lambda: '203.0.113.7'
sys.modules['app'] = _fake_app

import oauth_login  # noqa: E402

OAUTH = Flask('fix3_oauth', template_folder=os.path.join(ROOT, 'templates'), static_folder=os.path.join(ROOT, 'static'))
OAUTH.secret_key = 'test'
OAUTH.jinja_env.globals['csrf_token'] = lambda: 'csrf-test'
OAUTH.register_blueprint(oauth_login.oauth_bp)
OAUTH.add_url_rule('/login', 'login', lambda: 'login page')
OAUTH.add_url_rule('/', 'index', lambda: 'home')

# Chuỗi SĐT dùng cho bảng so khớp (mọi cách ghi hay gặp + ca biên)
PHONES = ('0412 345 678', '0412345678', '412345678', '61412345678', '+61 412 345 678', '+61 (0)412 345 678', '+610412345678',
          '0061 412 345 678', '0061 (0) 412 345 678', '(212) 555-1234', '212-555-1234', '2125551234', '1 212 555 1234',
          '12125551234', '+1 212 555 1234', '001 212 555 1234', '0212555123', '1412345678', '10412345678', '11234567890',
          '1 041 234 5678', '04123456789', '0912 345 678', '0912345678', '912345678', '84912345678', '+84 (0)912 345 678',
          '090 123 4567', '021 123 4567', '64211234567', '+64 (0)21 123 4567', '020 7946 0000', '02079460000',
          '442079460000', '+44 (0)20 7946 0000', '(02) 9000 0001', '0290000001', '290000001', '12', '', None, 'abc',
          '+0412345678', '+123', '1234567890123456', '4915112345678', '015112345678', '00412345678', '+1 (041) 234-5678')
COUNTRY_ARGS = (None, '', 'US', 'us', 'CA', 'AU', ' au ', 'VN', 'vn', 'NZ', 'GB', 'DE', 'other')


def _biz(bid, **fields):
    DB.businesses.insert_one(dict({'id': bid, 'name': f'Shop {bid}', 'industry_code': 'nail'}, **fields))


# ================================================================ 1. đăng ký mới lưu nước + tiền tệ
class RegisterCountryTests(core._Base):
    def setUp(self):
        super().setUp()
        FLASHES.clear()
        self.c = REG.test_client()

    def _register(self, n, form_country=None, header=None, plan=None):
        key = f'BP-TEST{n}'
        DB.license_codes.insert_one({'license_key': key, 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'nail',
                                     **({'plan': plan} if plan else {})})
        data = {'email': f'owner{n}@example.com', 'password': 'longpassword', 'business_type': 'nail',
                'business_name': f'Shop {n}', 'fullname': 'Owner', 'license_key': key}
        if form_country is not None:
            data['country'] = form_country
        r = self.c.post('/register', data=data, headers={'X-Vercel-IP-Country': header} if header else {})
        self.assertEqual(r.status_code, 302, (n, FLASHES))
        user = DB.users.find_one({'email': f'owner{n}@example.com'})
        return DB.businesses.find_one({'id': user['id']})

    def test_country_comes_from_the_form_first_then_the_vercel_header(self):
        cases = [  # (ô form, header Vercel) -> (country, currency) lưu trên businesses
            ('AU', 'US', ('AU', 'AUD')), ('us', None, ('US', 'USD')), ('VN', 'AU', ('VN', 'VND')),
            # CA/NZ/GB: chỉ lưu nước — tiền tệ để trống (CAD/NZD/GBP chưa định dạng được; mỗi module tự theo nước, fix4)
            ('CA', None, ('CA', None)), ('NZ', None, ('NZ', None)), ('GB', None, ('GB', None)), ('uk', None, ('GB', None)),
            (None, 'AU', ('AU', 'AUD')), (None, 'vn', ('VN', 'VND')), (None, 'US', ('US', 'USD')),
            ('other', 'AU', ('OTHER', None)), ('', 'US', (None, None)), ('ZZ<script>', None, (None, None)),
            (None, 'DE', (None, None)), (None, None, (None, None)),
        ]
        for n, (form_country, header, want) in enumerate(cases):
            biz = self._register(n, form_country, header)
            self.assertEqual((biz.get('country'), biz.get('currency')), want, (form_country, header))
            if want[0] is None:   # không rõ nước: KHÔNG lưu gì (không bịa nước / tiền tệ)
                self.assertNotIn('country', biz)
                self.assertNotIn('currency', biz)
            self.assertEqual((biz['industry_code'], biz['name']), ('nail', f'Shop {n}'))

    def test_currency_matches_what_the_app_already_derives_from_a_country(self):
        """Tiền tệ lưu khi đăng ký == app._shop_lang_currency / ai_copilot_tools.business_currency suy từ nước (gói bán USD/AUD,
        format_money chỉ VND/USD/AUD) — không đặt quy ước mới."""
        tree = ast.parse(core.APP_SRC)
        from tenant_engine import TenantEngine
        ns = {'db': DB, 'TenantEngine': TenantEngine}
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_shop_lang_currency')
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'app.py::_shop_lang_currency', 'exec'), ns)
        saas = next(n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'SAAS_CURRENCIES'
                                                                              for t in n.targets))
        sold_in = set(ast.literal_eval(saas.value))   # tiền tệ BitPaw bán gói (checkout / plans.price): USD, AUD
        import ai_copilot_tools
        for n, country in enumerate(COUNTRIES):
            biz = self._register(100 + n, country)
            # tiền tệ THẬT của tiệm (lễ tân AI, màn hình, đề xuất gửi chủ) luôn định dạng đúng: '$1,200.50' / '1.201đ' /
            # 'CA$1,200.50' — fix5: CA/NZ/GB không lưu tiền tệ ('Theo quốc gia') nhưng KHÔNG còn ra 'VND' / '1.201đ'
            effective = customer_context.currency_of(biz['id'])
            self.assertEqual(effective, {'US': 'USD', 'AU': 'AUD', 'VN': 'VND', 'CA': 'CAD', 'NZ': 'NZD', 'GB': 'GBP'}[country])
            self.assertEqual(ns['_shop_lang_currency'](biz['id'])[1], effective, country)
            self.assertEqual(format_money(1200.5, effective).endswith('đ'), effective == 'VND', country)
            if country in ('CA', 'NZ', 'GB'):   # fix4: chỉ lưu nước, tiền tệ theo nước (test_phase2_fix4_country4.py)
                self.assertNotIn('currency', biz, country)
                continue
            self.assertEqual(biz['currency'], ai_copilot_tools.business_currency(None, {'country': country}), country)
            self.assertIn(biz['currency'], sold_in | {'VND'}, country)

    def test_new_us_shop_reads_national_numbers_as_us(self):
        biz = self._register(200, 'US')
        bid = biz['id']
        self.assertEqual(ai_packs.shop_country(bid), 'US')
        self.assertEqual(customer_context.business(bid)['country'], 'US')
        self.assertTrue(ai_packs.same_phone('(212) 555-1234', '+1 212 555 1234', customer_context.business(bid)['country']))
        self.assertIn('(212) 555-1234', ai_packs.phone_variants('+12125551234', customer_context.business(bid)['country']))

    def test_plan_from_the_activation_code_is_still_kept(self):
        biz = self._register(300, 'AU', plan='pro')
        self.assertEqual((biz.get('plan'), biz.get('country'), biz.get('currency')), ('pro', 'AU', 'AUD'))

    def test_signup_region_never_blocks_signup(self):
        with patch.object(ai_packs, 'country_code', side_effect=RuntimeError('boom')):
            biz = self._register(400, 'AU')
        self.assertNotIn('country', biz)


class OAuthCompleteCountryTests(core._Base):
    def setUp(self):
        super().setUp()
        self.c = OAUTH.test_client()
        with self.c.session_transaction() as s:
            s['oauth_signup'] = {'provider': 'google', 'sub': 'g-1', 'email': 'new@example.com', 'name': 'New Owner',
                                 'ts': int(datetime.now().timestamp())}

    def _selected(self, html):
        sel = re.search(r'<select id="country" name="country">(.*?)</select>', html, re.S)
        self.assertIsNotNone(sel, 'country select missing on /auth/complete')
        return re.findall(r'<option value="([^"]*)" selected', sel.group(1)), re.findall(r'<option value="([^"]*)"', sel.group(1))

    def test_form_shows_a_country_select_defaulting_from_the_vercel_header(self):
        for header, want in (('AU', ['AU']), ('us', ['US']), ('UK', ['GB']), ('DE', ['other']), (None, [''])):
            r = self.c.get('/auth/complete', headers={'X-Vercel-IP-Country': header} if header else {})
            self.assertEqual(r.status_code, 200)
            picked, values = self._selected(r.get_data(as_text=True))
            self.assertEqual(picked, want, header)
            self.assertEqual(values, [''] + list(ai_packs.SHOP_COUNTRIES) + ['other'])

    def test_new_account_stores_country_and_currency(self):
        DB.license_codes.insert_one({'license_key': 'BP-OAUTH1', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'nail', 'plan': 'pro'})
        r = self.c.post('/auth/complete', data={'license_key': 'BP-OAUTH1', 'business_name': 'Bella Nails', 'business_type': 'nail',
                                                'country': 'US'}, headers={'X-Vercel-IP-Country': 'AU'})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
        biz = DB.businesses.find_one({'name': 'Bella Nails'})
        self.assertEqual((biz.get('country'), biz.get('currency'), biz.get('plan')), ('US', 'USD', 'pro'))

    def test_header_used_when_the_form_has_no_country_field_and_other_stores_the_other_marker(self):
        for n, (form_country, header, want) in enumerate(((None, 'VN', ('VN', 'VND')), ('other', 'AU', ('OTHER', None)),
                                                          (None, None, (None, None)))):
            with self.c.session_transaction() as s:
                s['oauth_signup'] = {'provider': 'google', 'sub': f'g-{n}', 'email': f'n{n}@example.com', 'name': 'X',
                                     'ts': int(datetime.now().timestamp())}
            DB.license_codes.insert_one({'license_key': f'BP-OA{n}', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'nail'})
            data = {'license_key': f'BP-OA{n}', 'business_name': f'Shop OA{n}', 'business_type': 'nail'}
            if form_country is not None:
                data['country'] = form_country
            r = self.c.post('/auth/complete', data=data, headers={'X-Vercel-IP-Country': header} if header else {})
            self.assertEqual(r.status_code, 302)
            biz = DB.businesses.find_one({'name': f'Shop OA{n}'})
            self.assertEqual((biz.get('country'), biz.get('currency')), want, (form_country, header))

    def test_error_page_keeps_the_chosen_country(self):
        r = self.c.post('/auth/complete', data={'license_key': 'BP-NOPE', 'business_name': 'Shop X', 'business_type': 'nail',
                                                'country': 'NZ'}, headers={'X-Vercel-IP-Country': 'US'})
        self.assertEqual(r.status_code, 400)
        picked, _values = self._selected(r.get_data(as_text=True))
        self.assertEqual(picked, ['NZ'])
        self.assertEqual(DB.businesses.find({'name': 'Shop X'}), [])


class RegisterTemplateTests(unittest.TestCase):
    """index.html (form /register): ô Quốc gia chọn sẵn theo header Vercel; giá trị = ai_packs.SHOP_COUNTRIES + other."""
    SRC = _read('templates/index.html')

    def _fragment(self):
        m = re.search(r'\{# Nước của tiệm.*?</select>\s*</div>', self.SRC, re.S)
        self.assertIsNotNone(m, 'country select missing in the register form')
        self.assertIn('name="country"', m.group(0))
        form = re.search(r'<form id="registerFormElement".*?</form>', self.SRC, re.S).group(0)
        self.assertIn(m.group(0), form)   # nằm TRONG form đăng ký -> gửi cùng request /register
        return m.group(0)

    def test_select_defaults_from_the_header(self):
        frag = self._fragment()
        app = Flask('fix3_tpl')
        for header, lang, want, label in (('AU', 'en', ['AU'], 'Australia'), ('nz', 'vi', ['NZ'], 'New Zealand'),
                                          ('UK', 'en', ['GB'], 'United Kingdom'), ('SG', 'en', ['other'], 'Other'),
                                          (None, 'vi', [''], 'Chọn quốc gia'), (None, 'en', [''], 'Select country')):
            with app.test_request_context('/', headers={'x-vercel-ip-country': header} if header else {}):
                html = render_template_string(frag, default_lang=lang)
            picked = re.findall(r'<option value="([^"]*)"[^>]*\sselected>([^<]*)<', html)
            self.assertEqual([p[0] for p in picked], want, header)
            self.assertEqual(picked[0][1].strip(), label)
            self.assertEqual(re.findall(r'<option value="([^"]*)"', html), [''] + list(ai_packs.SHOP_COUNTRIES) + ['other'])
            self.assertNotIn('required', re.search(r'<select[^>]*>', html).group(0))   # không chặn form cũ / e2e cũ

    def test_language_switch_translates_the_country_options(self):
        self.assertIn("index_reg_country_label: { vi: 'Quốc gia của tiệm', en: 'Shop country' }", self.SRC)
        self.assertIn("document.querySelectorAll('#reg_business_type option[data-vi], #reg_country option[data-vi]')", self.SRC)

    def test_inline_scripts_still_parse(self):
        if subprocess.run(['node', '--version'], capture_output=True).returncode != 0:
            self.skipTest('node not installed')
        for i, m in enumerate(re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', self.SRC, re.S)):
            code = re.sub(r'\{\{.*?\}\}', '0', m.group(1), flags=re.S)
            code = re.sub(r'\{%.*?%\}|\{#.*?#\}', '', code, flags=re.S)
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
                f.write(code)
            try:
                r = subprocess.run(['node', '--check', f.name], capture_output=True, text=True, encoding='utf-8')
            finally:
                os.unlink(f.name)
            self.assertEqual(r.returncode, 0, f'index.html script#{i}: {r.stderr[-400:]}')


# ================================================================ 2. 1 nguồn nước của tiệm
class ShopCountryTests(core._Base):
    def test_resolver_order_profile_then_timezone_then_currency(self):
        cases = [  # (businesses fields, messaging_settings.timezone) -> country
            ({'country': 'au', 'currency': 'USD'}, 'America/New_York', 'AU'),        # hồ sơ thắng
            ({'country': 'US'}, None, 'US'), ({'country': ' vn '}, None, 'VN'), ({'country': 'UK'}, None, 'GB'),
            ({'country': 'OTHER', 'currency': 'USD'}, 'America/Chicago', None),     # nước đã ghi mà BitPaw chưa có luật
            ({'country': 'SG', 'currency': 'USD'}, None, None),                     # -> None, không đoán theo tiền
            ({'currency': 'USD'}, 'Australia/Perth', 'AU'),                         # múi giờ trước tiền tệ
            ({}, 'Australia/Sydney', 'AU'), ({}, 'America/Toronto', 'CA'), ({}, 'America/Los_Angeles', 'US'),
            ({}, 'Pacific/Honolulu', 'US'), ({}, 'Asia/Ho_Chi_Minh', 'VN'), ({}, 'Pacific/Auckland', 'NZ'),
            ({}, 'Europe/London', 'GB'), ({}, 'US/Eastern', 'US'), ({'currency': 'VND'}, 'Europe/Berlin', 'VN'),
            ({'currency': 'USD'}, None, 'US'), ({'currency': 'aud'}, None, 'AU'), ({'currency': 'VND'}, '', 'VN'),
            ({'currency': 'CAD'}, None, 'CA'), ({'currency': 'NZD'}, None, 'NZ'), ({'currency': 'GBP'}, None, 'GB'),
            ({'currency': 'EUR'}, None, None), ({}, None, None), ({'country': ''}, 'Europe/Berlin', None),
        ]
        for n, (fields, tz, want) in enumerate(cases):
            bid = f'sc{n}'
            _biz(bid, **fields)
            if tz is not None:
                DB.messaging_settings.insert_one({'business_id': bid, 'timezone': tz})
            self.assertEqual(ai_packs.shop_country(bid), want, (fields, tz))
            doc = DB.businesses.find_one({'id': bid})
            self.assertEqual(ai_packs.shop_country(doc), want, (fields, tz, 'doc'))
            self.assertEqual(customer_context.business(bid)['country'], want, (fields, tz, 'customer_context'))
            self.assertEqual(rc.country_of(bid), want, (fields, tz, 'reservations_core'))
        for missing in (None, '', 'no-such-shop'):
            self.assertIsNone(ai_packs.shop_country(missing))
            self.assertIsNone(rc.country_of(missing))

    def test_db_errors_read_as_not_set(self):
        _biz('err1', currency='AUD')
        with patch.object(DB.messaging_settings, 'find_one', side_effect=RuntimeError('timeout')):
            self.assertEqual(ai_packs.shop_country('err1'), 'AU')
        with patch.object(DB.businesses, 'find_one', side_effect=RuntimeError('timeout')):
            self.assertIsNone(ai_packs.shop_country('err1'))

    def test_country_of_never_defaults_to_vn_for_au_or_us_shops(self):
        _biz('au_cur', currency='AUD')
        _biz('us_tz')
        DB.messaging_settings.insert_one({'business_id': 'us_tz', 'timezone': 'America/Chicago'})
        _biz('legacy')   # chưa có nước, múi giờ, tiền tệ
        self.assertEqual((rc.country_of('au_cur'), rc.country_of('us_tz'), rc.country_of('legacy')), ('AU', 'US', None))
        # AU: '0912 345 678' là số Úc +61912345678, không phải số Việt +84912345678
        self.assertFalse(rc.same_phone('0912 345 678', '+84912345678', rc.country_of('au_cur')))
        self.assertTrue(rc.same_phone('0412 345 678', '+61 412 345 678', rc.country_of('au_cur')))
        self.assertTrue(rc.same_phone('(212) 555-1234', '+1 212 555 1234', rc.country_of('us_tz')))
        self.assertFalse(rc.same_phone('(212) 555-1234', '+1 212 555 1234', rc.country_of('legacy')))   # không đoán
        self.assertTrue(rc.same_phone('(212) 555-1234', '212.555.1234', rc.country_of('legacy')))      # cùng chữ số
        ctx = {'business_id': 'au_cur', 'channel': 'sms'}
        self.assertEqual(rc.ctx_country(ctx), 'AU')

    def test_tool_context_and_customer_context_use_the_resolver_but_time_zone_stays_on_the_profile(self):
        _biz('cur_only', currency='USD')
        _biz('tz_only')
        DB.messaging_settings.insert_one({'business_id': 'tz_only', 'timezone': 'Australia/Sydney'})
        with T.chat_scope('tok' * 8, channel='web'):
            self.assertEqual(T.tool_context('cur_only', 'cur_only:2125551234')['country'], 'US')
            self.assertEqual(T.tool_context('tz_only', 'tz_only:0412345678')['country'], 'AU')
            self.assertEqual(T.tool_context(core.NAIL, f'{core.NAIL}:0412345678')['country'], 'AU')
        b = customer_context.business('cur_only')
        self.assertEqual((b['country'], b['profile_country'], b['currency']), ('US', None, 'USD'))
        # "bây giờ" của tiệm: cùng nguồn booking_rules.local_now (múi giờ Nhắn tin, không thì nước trên HỒ SƠ) — tiền tệ không
        # đổi múi giờ (không thì lời AI và bộ đặt lịch lệch giờ nhau)
        self.assertIsNone(customer_context.tz_name('cur_only'))
        self.assertEqual(customer_context.tz_name('tz_only'), 'Australia/Sydney')
        self.assertEqual(customer_context.tz_name(core.NAIL), 'Australia/Sydney')
        self.assertEqual(customer_context.business(None)['country'], None)


class VerificationCodeCountryTests(core._Base):
    def test_us_shop_without_a_profile_country_accepts_a_us_national_number(self):
        core.TWILIO['ready'] = True
        _biz('us_legacy', currency='USD')   # tiệm cũ có tiền tệ mà chưa có nước
        DB.appointments.insert_one({'id': 91, 'business_id': 'us_legacy', 'customer_phone': '(212) 555-1234', 'service_id': 1,
                                    'book_time': f'{core.DAY}T10:00', 'status': 'confirmed', 'source': 'web'})
        with T.chat_scope(core.TOKEN_A, channel='web'):
            out = core._call('send_verification_code', {'phone': '(212) 555-1234'}, 'us_legacy', 'us_legacy:2125551234')
        self.assertTrue(out.get('success'), out)
        self.assertEqual([d['phone'] for d in DB.ai_chat_verifications.find({})], ['+12125551234'])
        core._msg._twilio_send.assert_called_once()

    def test_au_time_zone_shop_reads_0412_as_australian(self):
        core.TWILIO['ready'] = True
        _biz('au_tz')
        DB.messaging_settings.insert_one({'business_id': 'au_tz', 'timezone': 'Australia/Melbourne'})
        with T.chat_scope(core.TOKEN_A, channel='web'):
            out = core._call('send_verification_code', {'phone': '0412 345 678'}, 'au_tz', 'au_tz:0412345678')
        self.assertTrue(out.get('success'), out)
        self.assertEqual([d['phone'] for d in DB.ai_chat_verifications.find({})], ['+61412345678'])

    def test_unknown_shop_still_never_guesses(self):
        core.TWILIO['ready'] = True
        _biz('nc2')
        with T.chat_scope(core.TOKEN_A, channel='web'):
            out = core._call('send_verification_code', {'phone': '0412 345 678'}, 'nc2', 'nc2:0412345678')
        self.assertFalse(out.get('success'), out)
        self.assertIn('country code', json.dumps(out))
        self.assertEqual(DB.ai_chat_verifications.find({}), [])


# ================================================================ 3. mọi bản chuẩn hoá SĐT == ai_packs.normalize_phone
class PhoneRuleParityTests(unittest.TestCase):
    IMPLS = (('reservations_core.e164', rc.e164), ('messaging.normalize_phone', msg_normalize),
             ('retail._e164_local', retail._e164_local))

    def test_every_copy_matches_ai_packs_case_by_case(self):
        n = 0
        for raw in PHONES:
            for country in COUNTRY_ARGS:
                want = ai_packs.normalize_phone(raw, country)
                for name, fn in self.IMPLS:
                    self.assertEqual(fn(raw, country), want, (name, raw, country))
                    n += 1
        self.assertGreater(n, 1500)

    def test_table_per_shop_country(self):
        table = {  # nước tiệm -> {cách khách gõ: E.164 mong đợi}
            'US': {'(212) 555-1234': '+12125551234', '1 212 555 1234': '+12125551234', '0412 345 678': '',
                   '1 041 234 5678': '', '10412345678': '', '04123456789': '', '61412345678': '+61412345678',
                   '+61 (0)412 345 678': '+61412345678', '0912 345 678': ''},
            'AU': {'0412 345 678': '+61412345678', '412345678': '+61412345678', '61412345678': '+61412345678',
                   '+61 (0)412 345 678': '+61412345678', '0061 412 345 678': '+61412345678', '(02) 9000 0001': '+61290000001',
                   '(212) 555-1234': '', '04123456789': '', '0912 345 678': '+61912345678'},
            'VN': {'0912 345 678': '+84912345678', '912345678': '+84912345678', '84912345678': '+84912345678',
                   '+84 (0)912 345 678': '+84912345678', '090 123 4567': '+84901234567', '(212) 555-1234': '',
                   '0412 345 678': '+84412345678'},
            None: {'0412 345 678': '', '(212) 555-1234': '', '0912 345 678': '', '61412345678': '',
                   '+61 412 345 678': '+61412345678', '0061 (0) 412 345 678': '+61412345678', '+1 212 555 1234': '+12125551234'},
        }
        for country, cases in table.items():
            for raw, want in cases.items():
                self.assertEqual(ai_packs.normalize_phone(raw, country), want, (country, raw))
                for name, fn in self.IMPLS:
                    self.assertEqual(fn(raw, country), want, (name, country, raw))

    def test_no_silent_default_country(self):
        self.assertEqual(msg_normalize('0912 345 678'), '')            # trước đây mặc định 'US' -> +10912345678
        self.assertEqual(msg_normalize('(212) 555-1234'), '')
        self.assertEqual(msg_normalize('+1 212 555 1234'), '+12125551234')
        self.assertEqual(rc.e164('0412 345 678'), '')                  # trước đây mặc định Mỹ -> +10412345678
        self.assertEqual(retail._e164_local('0412 345 678'), '')

    def test_phone_regex_and_ownership_follow_the_same_rule(self):
        own_us = {'business_id': 'b', 'channel': 'sms', 'customer_id': 'b:sms:+12125551234', 'phone': '+12125551234', 'country': 'US'}
        self.assertTrue(rc.is_owned({'customer_phone': '(212) 555-1234'}, dict(own_us)))
        self.assertFalse(rc.is_owned({'customer_phone': '(312) 555-1234'}, dict(own_us)))
        self.assertIsNone(rc._phone_regex('0412 345 678', None))         # chưa biết nước: không dựng regex cho số đoán bừa
        self.assertIsNotNone(rc._phone_regex('0412 345 678', 'AU'))
        self.assertEqual(retail.phone_key('0412 345 678', 'AU'), '+61412345678')
        self.assertIsNone(retail.phone_key('0412 345 678', None))
        self.assertIsNone(retail.phone_key('0412 345 678', 'US'))


# ================================================================ 4. retail.owner_filter: tiệm chưa có nước
class RetailOwnerFilterTests(core._Base):
    def _hold(self, hid, phone, token, conv):
        DB.retail_holds.insert_one({'id': hid, 'business_id': 'shop_nc', 'customer_phone': retail._clean_phone(phone),
                                    'phone_key': retail.phone_key(phone, None), 'chat_token_hash': token,
                                    'ai_conversation_id': conv, 'status': 'pending', 'channel': 'web'})

    def _ids(self, ctx):
        own = retail.owner_filter(ctx)
        return sorted(h['id'] for h in DB.retail_holds.find({'business_id': 'shop_nc', **own})) if own else None

    def test_typed_national_number_proves_a_hold_only_with_this_browser_token(self):
        self._hold(1, '0412 345 678', 'tokA', 'shop_nc:0412 345 678~old')   # cùng trình duyệt, chat web trước
        self._hold(2, '0412 345 679', 'tokA', 'shop_nc:0412 345 679')        # khách KHÁC ở cùng máy tính bảng quầy
        self._hold(3, '0412 345 678', 'tokB', 'shop_nc:0412 345 678')        # cùng số, trình duyệt KHÁC
        self._hold(4, '+61 412 345 678', 'tokA', 'shop_nc:+61412345678')     # số quốc tế (có khoá) — khác chữ số
        ctx = {'business_id': 'shop_nc', 'channel': 'web', 'customer_id': 'shop_nc:0412-345-678', 'chat_token_hash': 'tokA',
               'country': None, 'phone': None, 'contact_phone': None}
        self.assertEqual(self._ids(ctx), [1])
        self.assertEqual(self._ids(dict(ctx, contact_phone='0412 345 679')), [2])
        self.assertIsNone(self._ids(dict(ctx, chat_token_hash='anon:x')))                       # không mã trình duyệt: không gì
        self.assertEqual(self._ids(dict(ctx, customer_id='shop_nc:0499 999 999')), [])
        # SĐT gõ một mình (không kèm mã trình duyệt của chat này) không bao giờ là bằng chứng
        flt = retail.owner_filter(dict(ctx, chat_token_hash=None))
        self.assertIsNone(flt)

    def test_known_country_still_matches_by_e164_key(self):
        DB.retail_holds.insert_one({'id': 9, 'business_id': 'shop_nc', 'customer_phone': '+61412345678', 'phone_key': '+61412345678',
                                    'chat_token_hash': 'tokA', 'ai_conversation_id': 'x', 'status': 'pending'})
        ctx = {'business_id': 'shop_nc', 'channel': 'web', 'customer_id': 'shop_nc:0412 345 678', 'chat_token_hash': 'tokA',
               'country': 'AU', 'phone': None, 'contact_phone': None}
        self.assertEqual(self._ids(ctx), [9])
        self.assertNotIn({'phone_key': None, 'customer_phone': '0412345678'}, retail.owner_filter(ctx)['$or'][0]['$or'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
