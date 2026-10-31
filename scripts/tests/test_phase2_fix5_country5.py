# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 vòng 5, khu "country5" (tiền tệ + nước của tiệm):
  1. (HIGH) Không tiệm nào bị VND/'đ' mặc định: tiệm chưa lưu tiền tệ -> currency_utils.shop_currency theo
     ai_packs.shop_country (US -> USD, AU -> AUD, VN -> VND, CA -> CAD, NZ -> NZD, GB -> GBP), cuối cùng USD.
     customer_context.business / money (lễ tân AI: bảng giá BOOKABLE SERVICES, giá khi đổi dịch vụ), TenantEngine,
     app._tenant_currency, app._shop_lang_currency, shift_roster cùng 1 quy tắc.
  2. format_money định dạng đúng USD, AUD, VND, CAD, NZD, GBP ('CA$45.00', 'NZ$45.00', '£45.00'); tiền khác in kèm mã
     ('45.00 EUR'); 'đ' CHỈ cho VND. Danh sách tiền của mục "Quốc gia & tiền tệ" = đúng các tiền format_money định dạng.
  3. 'Nước khác' không bao giờ thành 'VN': quảng cáo Meta từ chối nhắm (thông báo rõ chỗ chọn nước) cho tới khi tiệm có
     nước thật; ad_assistant._shop_region không còn mặc định VN / VND.
  4. Đăng ký chọn 'Nước khác' lưu {'country': 'OTHER'} — cùng dấu với /api/business_region (múi giờ America/New_York trang
     Nhắn tin gửi lại không biến tiệm thành tiệm Mỹ).
  5. /api/business_region: POST không có currency GIỮ tiền đang lưu (không âm thầm xoá); tiền tệ cũ ngoài danh sách (EUR)
     được giữ khi sửa nước; tiền lạ -> 400 nói rõ phải chọn gì. Mục trên trang: cảnh báo định dạng hiện cả khi 'Theo quốc
     gia' ra CAD/NZD/GBP; tiền tệ cũ hiện nhãn "(hiện tại)".
  6. Các chỗ đọc thô nước của tiệm (spa_bp._shop_is_vi, job_tracking, shift_roster, ai_gateway) dùng ai_packs.shop_country.

Dùng lại DB giả + stub của test_phase2_receptionist_core.py (nạp TRƯỚC mọi import), form đăng ký giả của
test_phase2_fix3_country.py và route /api/business_region (mã nguồn app.py qua ast) của test_phase2_fix4_country4.py:
không import app.py thật, không MongoDB thật, không gọi mạng / Meta / DeepSeek / Twilio.
Chạy: python scripts/tests/test_phase2_fix5_country5.py
"""
import ast
import functools
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
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_receptionist_core as core  # noqa: E402  (DB giả, messaging giả, ai_packs thật)
import test_phase2_fix3_country as fix3  # noqa: E402  (/register + /auth/complete giả, cùng DB giả; sys.modules['app'] giả)
import test_phase2_fix4_country4 as fix4  # noqa: E402  (/api/business_region từ mã nguồn app.py)

from flask import Flask, jsonify, request, session  # noqa: E402

import ai_packs  # noqa: E402
import booking_rules  # noqa: E402
import currency_utils  # noqa: E402
import customer_context  # noqa: E402
import ai_function_tools as T  # noqa: E402
from currency_utils import format_money  # noqa: E402
from tenant_engine import TenantEngine  # noqa: E402

DB, ROOT, APP_SRC = core.DB, core.ROOT, core.APP_SRC
_TREE = ast.parse(APP_SRC)
SIX = ('USD', 'AUD', 'VND', 'CAD', 'NZD', 'GBP')
COUNTRY_CUR = {'US': 'USD', 'AU': 'AUD', 'VN': 'VND', 'CA': 'CAD', 'NZ': 'NZD', 'GB': 'GBP'}


def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def _funcs(rel, names, ns, src=None):
    """Hàm lấy nguyên mã nguồn (bỏ decorator) vào ns — không import module thật (mở MongoDB / Flask app)."""
    tree = ast.parse(src if src is not None else _read(rel))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), f'{rel}::{node.name}', 'exec'), ns)
    return ns


def _biz(bid, **fields):
    DB.businesses.insert_one(dict({'id': bid, 'name': f'Shop {bid}', 'industry_code': 'nail'}, **fields))


def _tz(bid, tz):
    DB.messaging_settings.insert_one({'business_id': bid, 'timezone': tz})


# ================================================================ 1. format_money + shop_currency
class FormatMoneyTests(unittest.TestCase):
    def test_every_supported_currency_has_its_own_format(self):
        want = {'USD': '$1,200.50', 'AUD': '$1,200.50', 'VND': '1.200.500đ', 'CAD': 'CA$1,200.50', 'NZD': 'NZ$1,200.50',
                'GBP': '£1,200.50'}
        for cur, out in want.items():
            amount = 1200500 if cur == 'VND' else 1200.5
            self.assertEqual(format_money(amount, cur), out, cur)
            self.assertEqual(format_money(amount, cur.lower()), out, cur)        # 'cad' từ dữ liệu cũ
            self.assertEqual(format_money(amount, f' {cur} '), out, cur)
        self.assertEqual(format_money(45, 'CAD'), 'CA$45.00')                    # ví dụ của bản review: không còn '45đ'
        self.assertEqual(format_money(45, 'NZD'), 'NZ$45.00')
        self.assertEqual(format_money(45, 'GBP'), '£45.00')

    def test_dong_is_only_ever_used_for_vnd(self):
        for cur in SIX + ('EUR', 'SGD', 'cad', '', None, 'đ', '12', 'VNDX'):
            out = format_money(45, cur)
            self.assertEqual(out.endswith('đ'), str(cur or '').strip().upper() == 'VND', (cur, out))

    def test_other_codes_print_their_code_and_no_currency_is_usd(self):
        self.assertEqual(format_money(1200.5, 'EUR'), '1,200.50 EUR')
        self.assertEqual(format_money(45, 'sgd'), '45.00 SGD')
        self.assertEqual(format_money(45, None), '$45.00')                       # không có tiền tệ: USD, không phải VND
        self.assertEqual(format_money(45, ''), '$45.00')
        self.assertEqual(format_money(45, 'đ'), '$45.00')                       # chuỗi lạ -> USD

    def test_amount_edge_cases(self):
        self.assertEqual(format_money(-12, 'USD'), '-$12.00')
        self.assertEqual(format_money(-12.5, 'GBP'), '-£12.50')
        self.assertEqual(format_money(-0.001, 'USD'), '$0.00')
        self.assertEqual(format_money(-1200, 'VND'), '-1.200đ')
        self.assertEqual(format_money(None, 'CAD'), 'CA$0.00')
        self.assertEqual(format_money('abc', 'NZD'), 'NZ$0.00')
        self.assertEqual(format_money('12.5', 'AUD'), '$12.50')
        self.assertEqual(format_money(float('nan'), 'VND'), '0đ')                # trước: ValueError
        self.assertEqual(format_money(float('inf'), 'USD'), '$0.00')

    def test_shop_currency_rule(self):
        self.assertEqual(currency_utils.SUPPORTED_CURRENCIES, SIX)
        for country, cur in COUNTRY_CUR.items():
            self.assertEqual(currency_utils.shop_currency(None, country), cur, country)
            self.assertEqual(currency_utils.shop_currency('', country.lower()), cur, country)
        self.assertEqual(currency_utils.shop_currency(None, 'UK'), 'GBP')
        for country in (None, '', 'OTHER', 'SG', 'DE', 'other'):
            self.assertEqual(currency_utils.shop_currency(None, country), 'USD', country)   # cuối cùng USD, không VND
        self.assertEqual(currency_utils.shop_currency('aud', 'CA'), 'AUD')                  # đã lưu thì thắng
        self.assertEqual(currency_utils.shop_currency('EUR', 'VN'), 'EUR')
        self.assertEqual(currency_utils.shop_currency('đ', 'CA'), 'CAD')                    # giá trị hỏng -> theo nước

    def test_region_currencies_are_exactly_what_format_money_formats(self):
        node = next(n for n in _TREE.body if isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == '_REGION_CURRENCIES'
                                                                              for t in n.targets))
        self.assertEqual(tuple(ast.literal_eval(node.value)), currency_utils.SUPPORTED_CURRENCIES)
        sec = re.search(r'<select id="regionCurrency".*?</select>', _read('templates/brand_settings.html'), re.S).group(0)
        self.assertEqual(re.findall(r'<option value="([A-Z]{3})"', sec), list(SIX))
        for cur in SIX:   # mỗi tiền chọn được có ký hiệu riêng, không bao giờ in thành 'đ' (trừ VND)
            self.assertEqual(format_money(45, cur).endswith('đ'), cur == 'VND', cur)
            self.assertNotRegex(format_money(45, cur), r' [A-Z]{3}$', cur)


# ================================================================ 2. (HIGH) lễ tân AI / customer_context không còn VND mặc định
class CustomerCurrencyTests(core._Base):
    CASES = [  # (businesses, múi giờ trang Nhắn tin) -> (tiền của tiệm, money(45))
        ({'country': 'CA'}, None, 'CAD', 'CA$45.00'), ({'country': 'NZ'}, None, 'NZD', 'NZ$45.00'),
        ({'country': 'GB'}, None, 'GBP', '£45.00'), ({'country': 'uk'}, None, 'GBP', '£45.00'),
        ({'country': 'US'}, None, 'USD', '$45.00'), ({'country': 'AU'}, None, 'AUD', '$45.00'),
        ({'country': 'VN'}, None, 'VND', '45đ'), ({}, None, 'USD', '$45.00'), ({'country': 'OTHER'}, None, 'USD', '$45.00'),
        ({'country': 'OTHER'}, 'Asia/Ho_Chi_Minh', 'USD', '$45.00'), ({'country': 'SG'}, None, 'USD', '$45.00'),
        ({}, 'America/Toronto', 'CAD', 'CA$45.00'), ({}, 'Australia/Sydney', 'AUD', '$45.00'),
        ({'country': 'CA', 'currency': 'CAD'}, None, 'CAD', 'CA$45.00'), ({'country': 'CA', 'currency': 'USD'}, None, 'USD', '$45.00'),
        ({'currency': 'VND'}, None, 'VND', '45đ'), ({'country': 'US', 'currency': 'eur'}, None, 'EUR', '45.00 EUR'),
    ]

    def _seed(self):
        for i, (fields, tz, _cur, _out) in enumerate(self.CASES):
            _biz(f'cur{i}', **fields)
            if tz:
                _tz(f'cur{i}', tz)

    def test_a_shop_without_currency_follows_its_country_then_usd(self):
        self._seed()
        for i, (fields, tz, cur, out) in enumerate(self.CASES):
            bid = f'cur{i}'
            self.assertEqual(customer_context.currency_of(bid), cur, (fields, tz))
            self.assertEqual(customer_context.money(bid, 45), out, (fields, tz))
            self.assertEqual(customer_context.build(bid)['currency'], cur, (fields, tz))

    def test_one_answer_for_the_ai_and_the_app_screens(self):
        self._seed()
        for i, (fields, tz, cur, _out) in enumerate(self.CASES):
            bid = f'cur{i}'
            self.assertEqual(TenantEngine.get_region_config(bid)['currency'], cur, (fields, tz))
            self.assertEqual(TenantEngine.get_region_config(bid)['currency'], customer_context.currency_of(bid), (fields, tz))

    def test_no_business_is_usd_not_vnd(self):
        self.assertEqual(customer_context.business(None)['currency'], 'USD')
        self.assertEqual(customer_context.money(None, 45), '$45.00')
        self.assertEqual(customer_context.money('ghost-shop', 45), '$45.00')    # chưa có dòng businesses
        with patch.object(DB.businesses, 'find_one', side_effect=RuntimeError('db down')):
            booking_rules._CACHE.clear()
            self.assertEqual(customer_context.currency_of('cur-err'), 'USD')

    def test_receptionist_price_list_quotes_the_shop_currency(self):
        """ai_function_tools: BOOKABLE SERVICES (prompt lễ tân) + price_list của customer_context — tiệm Canada / UK / chỉ có
        múi giờ NZ chưa lưu tiền tệ báo 'CA$45.00' / '£45.00' / 'NZ$45.00', không bao giờ '45đ'."""
        for n, (bid, fields, tz, want) in enumerate((('ca_shop', {'country': 'CA'}, None, 'CA$45.00'),
                                                     ('gb_shop', {'country': 'GB'}, None, '£45.00'),
                                                     ('nz_tz', {}, 'Pacific/Auckland', 'NZ$45.00'), ('none', {}, None, '$45.00'))):
            _biz(bid, **fields)
            if tz:
                _tz(bid, tz)
            DB.products.insert_one({'id': 901 + n, 'business_id': bid, 'name': 'Gel Manicure', 'price': 45, 'is_active': 1})
            facts = T._appointment_facts(bid)
            self.assertIn(f'Gel Manicure — {want}', facts, bid)
            self.assertNotIn('45đ', facts, bid)
            self.assertIn(f'Gel Manicure — {want}', customer_context.price_list(bid, 'PRICES'), bid)

    def test_change_service_reply_uses_customer_context_money(self):
        """ai_function_tools (đổi dịch vụ): giá mới = customer_context.money — cùng 1 bộ định dạng."""
        src = _read('ai_function_tools.py')
        self.assertIn("price = customer_context.money(business_id, svc.get('price'))", src)
        self.assertIsNone(re.search(r"or 'VND'|'currency': 'VND'", _read('customer_context.py')),
                          'customer_context.py still has a VND fallback')


# ================================================================ 3. TenantEngine / app._tenant_currency / app._shop_lang_currency
APP_NS = {'db': DB, 'TenantEngine': TenantEngine}
_funcs('app.py', ['_tenant_currency', '_shop_lang_currency'], APP_NS, src=APP_SRC)


class AppCurrencyTests(core._Base):
    def test_tenant_engine_follows_the_country(self):
        for c, cur in COUNTRY_CUR.items():
            _biz(f'te_{c}', country=c)
            self.assertEqual(TenantEngine.get_region_config(f'te_{c}'), {'country': c, 'currency': cur}, c)
        _biz('te_other', country='OTHER')
        self.assertEqual(TenantEngine.get_region_config('te_other'), {'country': '', 'currency': 'USD'})

    def test_tenant_currency_never_falls_back_to_vnd(self):
        fn = APP_NS['_tenant_currency']
        _biz('tc_ca', country='CA')
        _biz('tc_vn', country='VN', currency='VND')
        self.assertEqual(fn('tc_ca'), 'CAD')
        self.assertEqual(fn('tc_vn'), 'VND')
        self.assertEqual(fn('ghost'), 'USD')
        with patch.object(TenantEngine, 'get_region_config', side_effect=RuntimeError('boom')):
            self.assertEqual(fn('tc_vn'), 'USD')
        with patch.object(TenantEngine, 'get_region_config', return_value={'country': 'US'}):
            self.assertEqual(fn('tc_vn'), 'USD')

    def test_shop_lang_currency_uses_the_same_rule(self):
        fn = APP_NS['_shop_lang_currency']
        _biz('sl_none')
        _biz('sl_ca', country='CA')
        _biz('sl_vn', country='VN', currency='VND')
        _biz('sl_cur', currency='VND')
        _biz('sl_other', country='OTHER', currency='VND')
        _biz('sl_tz')
        _tz('sl_tz', 'Asia/Ho_Chi_Minh')
        _biz('sl_au_vi', country='AU')
        DB.messaging_settings.insert_one({'business_id': 'sl_au_vi', 'language': 'vi'})
        for bid, want in (('sl_none', ('en', 'USD')), ('ghost', ('en', 'USD')), ('sl_ca', ('en', 'CAD')),
                          ('sl_vn', ('vi', 'VND')), ('sl_cur', ('vi', 'VND')), ('sl_other', ('en', 'VND')),
                          ('sl_tz', ('vi', 'VND')), ('sl_au_vi', ('vi', 'AUD'))):
            self.assertEqual(fn(bid), want, bid)
        self.assertEqual(format_money(12, fn('sl_ca')[1]), 'CA$12.00')   # đề xuất nhập hàng / cảnh báo đối soát


# ================================================================ 4. quảng cáo: 'Nước khác' / chưa có nước không bao giờ thành VN
_tokens = types.ModuleType('ad_platform_tokens')
_tokens.get_facebook_token = MagicMock()
_tokens.save_facebook_token = MagicMock()
_tokens.mark_facebook_token_invalid = MagicMock()
sys.modules['ad_platform_tokens'] = _tokens


def _login_required(f):
    @functools.wraps(f)
    def inner(*a, **k):
        if 'user_id' not in session:
            return jsonify({'success': False}), 401
        return f(*a, **k)
    return inner


def _role_required(*roles):
    def deco(f):
        @functools.wraps(f)
        def inner(*a, **k):
            if session.get('role', 'staff') not in roles:
                return jsonify({'success': False}), 403
            return f(*a, **k)
        return inner
    return deco


_app_mod = sys.modules['app']   # 'app' giả của fix3 (oauth_login) — thêm đúng những gì ad_assistant import
_app_mod.login_required = _login_required
_app_mod.role_required = _role_required
_app_mod.limiter = types.SimpleNamespace(limit=lambda *a, **k: (lambda f: f))
_app_mod.TenantEngine = TenantEngine
import facebook_ads_client as fb  # noqa: E402
import ad_assistant  # noqa: E402

ADS = Flask('fix5_ads')
ADS.secret_key = 'test'
ADS.register_blueprint(ad_assistant.ad_assistant_bp)


class AdTargetingTests(core._Base):
    def setUp(self):
        super().setUp()
        self.c = ADS.test_client()
        _tokens.get_facebook_token.reset_mock()
        _tokens.get_facebook_token.return_value = {'access_token': 'tok', 'ad_account_id': 'act_1', 'page_id': 'p1', 'status': 'active'}

    def _create(self, bid, **body):
        with self.c.session_transaction() as s:
            s['user_id'] = bid
            s['business_id'] = bid
            s['role'] = 'admin'
        payload = {'platform': 'facebook', 'name': 'Test', 'link': 'https://shop.test', 'message': 'Hello', 'budget': 70,
                   'currency': 'USD', 'target_audience': {'age_min': 25, 'age_max': 40}}
        payload.update(body)
        with patch.object(fb, 'get_ad_account', return_value={'currency': 'USD'}), \
                patch.object(fb, 'launch_campaign', return_value={'campaign_id': 'c', 'ad_set_id': 'a', 'creative_id': 'cr',
                                                                  'ad_id': 'ad'}) as launch:
            r = self.c.post('/ad-assistant/api/create-campaign', json=payload)
        return r, launch

    def test_shop_region_has_no_vn_default(self):
        _biz('ad_other', country='OTHER')
        _biz('ad_none')
        _biz('ad_ca', country='CA')
        self.assertEqual(ad_assistant._shop_region('ad_other'), {'country': '', 'currency': 'USD'})
        self.assertEqual(ad_assistant._shop_region('ad_none'), {'country': '', 'currency': 'USD'})
        self.assertEqual(ad_assistant._shop_region('ad_ca'), {'country': 'CA', 'currency': 'CAD'})
        with patch.object(TenantEngine, 'get_region_config', side_effect=RuntimeError('boom')):
            self.assertEqual(ad_assistant._shop_region('ad_ca'), {'country': '', 'currency': 'USD'})

    def test_other_country_or_no_country_refuses_to_target_with_a_clear_message(self):
        _biz('ad_other', country='OTHER')
        _biz('ad_none')
        _biz('ad_other_tz', country='OTHER')
        _tz('ad_other_tz', 'Asia/Ho_Chi_Minh')          # 'Nước khác' thắng múi giờ: không đoán VN
        for bid in ('ad_other', 'ad_none', 'ad_other_tz'):
            r, launch = self._create(bid)
            self.assertEqual(r.status_code, 400, (bid, r.get_json()))
            body = r.get_json()
            self.assertEqual(body['code'], 'shop_country_missing', bid)
            self.assertIn('Country & currency', body['error'])            # nói rõ chỗ chọn nước
            self.assertIn('Other country', body['error'])
            launch.assert_not_called()                                    # không tiêu tiền quảng cáo thật vào Việt Nam
        self.assertEqual(DB.ad_campaigns.find({}), [])

    def test_vietnamese_shop_gets_the_message_in_vietnamese(self):
        _biz('ad_vi_other', country='OTHER', currency='VND')
        r, launch = self._create('ad_vi_other', currency='VND', budget=700000)
        self.assertEqual(r.get_json()['code'], 'shop_country_missing')
        self.assertIn('Quốc gia & tiền tệ', r.get_json()['error'])
        launch.assert_not_called()

    def test_real_countries_still_target_their_own_country(self):
        for c in ai_packs.SHOP_COUNTRIES:
            _biz(f'ad_{c}', country=c, currency='USD')
            r, launch = self._create(f'ad_{c}')
            self.assertEqual(r.status_code, 200, (c, r.get_json()))
            self.assertEqual(launch.call_args.kwargs['targeting']['geo_locations']['countries'], [c])
        _biz('ad_tz', currency='USD')
        _tz('ad_tz', 'Australia/Perth')                  # chưa lưu nước, múi giờ Úc -> nhắm AU
        r, launch = self._create('ad_tz')
        self.assertEqual(launch.call_args.kwargs['targeting']['geo_locations']['countries'], ['AU'])


# ================================================================ 5. đăng ký 'Nước khác' = dấu 'OTHER' như trang cài đặt
class SignupOtherTests(core._Base):
    def test_signup_region_marks_an_explicit_other(self):
        fn = fix3.APP_NS['_signup_region']
        app = Flask('fix5_signup')
        for data, headers, want in (({'country': 'other'}, {}, {'country': 'OTHER'}),
                                    ({'country': ' Other '}, {'X-Vercel-IP-Country': 'US'}, {'country': 'OTHER'}),
                                    ({'country': ''}, {'X-Vercel-IP-Country': 'US'}, {}),   # chưa chọn: không bịa nước
                                    ({'country': 'ZZ<script>'}, {}, {}), ({'country': 'SG'}, {}, {}),
                                    ({}, {'X-Vercel-IP-Country': 'DE'}, {}),               # chỉ đoán theo IP: không lưu
                                    ({'country': 'CA'}, {}, {'country': 'CA'}),
                                    ({'country': 'US'}, {}, {'country': 'US', 'currency': 'USD'})):
            with app.test_request_context('/register', method='POST', data=data, headers=headers):
                self.assertEqual(fn(request.form), want, (data, headers))

    def test_other_signup_is_not_turned_into_a_us_shop_by_the_messaging_time_zone(self):
        c = fix3.REG.test_client()
        DB.license_codes.insert_one({'license_key': 'BP-FIX5-1', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'nail'})
        r = c.post('/register', data={'email': 'fix5-other@example.com', 'password': 'longpassword', 'business_type': 'nail',
                                      'business_name': 'Shop Other', 'fullname': 'Owner', 'license_key': 'BP-FIX5-1',
                                      'country': 'other'}, headers={'X-Vercel-IP-Country': 'SG'})
        self.assertEqual(r.status_code, 302, fix3.FLASHES)
        biz = DB.businesses.find_one({'id': DB.users.find_one({'email': 'fix5-other@example.com'})['id']})
        self.assertEqual(biz.get('country'), 'OTHER')
        self.assertNotIn('currency', biz)
        _tz(biz['id'], 'America/New_York')     # trang Nhắn tin luôn gửi lại múi giờ đang hiện (mặc định New York)
        self.assertIsNone(ai_packs.shop_country(biz['id']))
        self.assertEqual(TenantEngine.get_region_config(biz['id']), {'country': '', 'currency': 'USD'})   # Square vẫn đóng
        self.assertEqual(ai_packs.normalize_phone('(212) 555-1234', ai_packs.shop_country(biz['id'])), '')   # không đọc NANP
        self.assertEqual(fix4.NS['_business_region_view'](biz['id'])['country'], 'other')   # trang cài đặt: 'Nước khác'

    def test_oauth_signup_other_uses_the_same_marker(self):
        c = fix3.OAUTH.test_client()
        with c.session_transaction() as s:
            s['oauth_signup'] = {'provider': 'google', 'sub': 'g5-1', 'email': 'oa5-1@example.com', 'name': 'X',
                                 'ts': int(datetime.now().timestamp())}
        DB.license_codes.insert_one({'license_key': 'BP-OA5-1', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'retail'})
        r = c.post('/auth/complete', data={'license_key': 'BP-OA5-1', 'business_name': 'Shop OA5', 'business_type': 'retail',
                                           'country': 'other'})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
        biz = DB.businesses.find_one({'name': 'Shop OA5'})
        self.assertEqual((biz.get('country'), biz.get('currency')), ('OTHER', None))


# ================================================================ 6. /api/business_region: không âm thầm xoá tiền tệ
class RegionRouteTests(core._Base):
    def setUp(self):
        super().setUp()
        booking_rules._CACHE.clear()
        self.c = fix4.WEB.test_client()

    def _login(self, bid):
        with self.c.session_transaction() as s:
            s['user_id'] = bid
            s['business_id'] = bid
            s['role'] = 'admin'

    def _post(self, body, lang='en'):
        return self.c.post('/api/business_region', json=body, headers={'Accept-Language': lang})

    def _row(self, bid):
        return DB.businesses.find_one({'id': bid}) or {}

    def test_post_without_currency_keeps_the_stored_one(self):
        _biz('k1', country='VN', currency='USD')
        self._login('k1')
        for body in ({'country': 'US'}, {'country': 'US', 'currency': None}, {'country': 'US', 'currency': ''},
                     {'country': 'US', 'currency': '  '}):
            r = self._post(body)
            self.assertEqual(r.status_code, 200, (body, r.get_data(as_text=True)))
            self.assertEqual((self._row('k1')['country'], self._row('k1').get('currency')), ('US', 'USD'), body)
        logs = DB.audit_logs.find({'business_id': 'k1'})
        self.assertEqual(len(logs), 1)                       # chỉ lần đổi nước đầu tiên; tiền tệ không đổi
        self.assertEqual(logs[0]['new_value'], {'country': 'US', 'currency': 'USD'})
        self.assertEqual(r.get_json()['data']['currency'], 'USD')
        # 'auto' (chọn rõ) vẫn xoá
        r = self._post({'country': 'CA', 'currency': 'auto'})
        self.assertNotIn('currency', self._row('k1'))
        self.assertEqual((r.get_json()['data']['currency'], r.get_json()['data']['display_currency']), ('auto', 'CAD'))

    def test_legacy_currency_is_kept_while_correcting_the_country(self):
        _biz('l1', country='VN', currency='EUR')
        self._login('l1')
        d = self.c.get('/api/business_region').get_json()['data']
        self.assertEqual((d['currency'], d['display_currency']), ('EUR', 'EUR'))
        r = self._post({'country': 'US', 'currency': 'EUR'})   # trang gửi lại đúng tiền đang chọn
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual((self._row('l1')['country'], self._row('l1')['currency']), ('US', 'EUR'))
        self.assertEqual(self._post({'country': 'AU', 'currency': 'eur'}).status_code, 200)
        self.assertEqual((self._row('l1')['country'], self._row('l1')['currency']), ('AU', 'EUR'))
        # đổi sang 1 tiền lạ KHÁC -> 400, nói rõ phải chọn gì
        r = self._post({'country': 'AU', 'currency': 'SGD'})
        self.assertEqual(r.status_code, 400)
        msg = r.get_json()['message']
        self.assertIn('USD, AUD, VND, CAD, NZD, GBP', msg)
        self.assertIn('Match the country', msg)
        r = self._post({'country': 'AU', 'currency': 'SGD'}, lang='vi')
        self.assertIn('Theo quốc gia', r.get_json()['message'])
        self.assertEqual(self._row('l1')['currency'], 'EUR')
        # chọn 1 tiền trong danh sách vẫn được
        self.assertEqual(self._post({'country': 'AU', 'currency': 'AUD'}).status_code, 200)
        self.assertEqual(self._row('l1')['currency'], 'AUD')

    def test_garbage_currency_is_refused_and_changes_nothing(self):
        _biz('g1', country='AU', currency='AUD')
        self._login('g1')
        for cur in ('<b>x</b>', 'US', 'DOLLARS', 12, 'EUR'):
            r = self._post({'country': 'NZ', 'currency': cur})
            self.assertEqual(r.status_code, 400, cur)
            self.assertIn('currency', r.get_json()['message'].lower())
        self.assertEqual((self._row('g1')['country'], self._row('g1')['currency']), ('AU', 'AUD'))
        self.assertEqual(DB.audit_logs.find({}), [])

    def test_every_offered_currency_is_accepted_and_formats(self):
        _biz('a1', country='AU', currency='AUD')
        self._login('a1')
        for cur in SIX:
            r = self._post({'country': 'AU', 'currency': cur})
            self.assertEqual(r.status_code, 200, cur)
            self.assertEqual(self._row('a1')['currency'], cur)
            self.assertEqual(r.get_json()['data']['display_currency'], cur)
            booking_rules._CACHE.clear()
            self.assertEqual(customer_context.currency_of('a1'), cur)
            self.assertEqual(customer_context.money('a1', 45).endswith('đ'), cur == 'VND', cur)


# ================================================================ 7. mục "Quốc gia & tiền tệ" trên trang
class BrandSettingsSectionTests(unittest.TestCase):
    SRC = _read('templates/brand_settings.html')

    def _translations(self):
        m = re.search(r'const translations = (\{.*?\n        \});', self.SRC, re.S)
        js = m.group(1)
        out = {}
        for lang in ('vi', 'en'):
            block = re.search(lang + r': \{(.*?)\n            \}', js, re.S).group(1)
            out[lang] = {k: a or b for k, a, b in re.findall(r"""(\w+):\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""", block)}
        return out

    def test_partial_note_is_honest_in_both_languages(self):
        tr = self._translations()
        en, vi = tr['en']['brand_settings_currency_partial'], tr['vi']['brand_settings_currency_partial']
        for s in (en, vi):
            self.assertIn('CAD', s)
            self.assertIn('VND, USD', s)
        self.assertIn('AI receptionist', en)
        self.assertIn('table-order', en)
        self.assertIn('Lễ tân AI', vi)
        self.assertIn('gọi món', vi)
        for k in ('brand_settings_currency_current',):
            self.assertIn('{c}', tr['en'][k])
            self.assertIn('{c}', tr['vi'][k])
            self.assertNotEqual(tr['en'][k], tr['vi'][k])
        m = re.search(r'data-i18n="brand_settings_currency_partial">([^<]*)<', self.SRC)
        self.assertEqual(m.group(1), en)                    # chữ mặc định trong HTML = bản EN

    def test_region_script_behaviour(self):
        """Chạy THẬT script của trang trong node với DOM giả: 'Theo quốc gia' + Canada -> cảnh báo định dạng hiện (CAD);
        đổi nước sang Mỹ -> ẩn; tiền tệ cũ EUR hiện nhãn '(hiện tại)' và vẫn được chọn."""
        if subprocess.run(['node', '--version'], capture_output=True).returncode != 0:
            self.skipTest('node not installed')
        code = re.search(r'<script type="module">(.*?)</script>', self.SRC, re.S).group(1)
        code = code.replace('{{ default_lang }}', 'en')
        code = re.sub(r'\{\{.*?\}\}', '', code, flags=re.S)
        sec = re.search(r'<form id="regionForm".*?</form>', self.SRC, re.S).group(0)
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
let regionData = {};
global.fetch = async (url, init) => { const ok = url.includes('/api/business_region');
  return { ok: true, status: 200, json: async () => ({ success: true, data: ok ? regionData : {} }) }; };
const tick = () => new Promise(r => setTimeout(r, 0));
const fire = (id, type) => (($(id).handlers[type]) || []).forEach(f => f());
const partialShown = () => !$('regionCurrencyPartial').classList.contains('hidden');
function page() {
%s
}
(async () => {
  const out = {};
  regionData = { country: 'CA', currency: 'auto', phone_country: 'CA', display_currency: 'CAD' };
  page();
  for (let i = 0; i < 5; i++) await tick();
  out.caAuto = partialShown();
  $('regionCountry').value = 'US'; fire('regionCountry', 'change');
  out.usAuto = partialShown();
  $('regionCountry').value = 'GB'; fire('regionCountry', 'change');
  out.gbAuto = partialShown();
  $('regionCountry').value = 'other'; fire('regionCountry', 'change');
  out.otherAuto = partialShown();
  $('regionCurrency').value = 'NZD'; fire('regionCurrency', 'change');
  out.nzd = partialShown();
  $('regionCurrency').value = 'AUD'; fire('regionCurrency', 'change');
  out.aud = partialShown();
  regionData = { country: 'VN', currency: 'EUR', phone_country: 'VN', display_currency: 'EUR' };
  page();
  for (let i = 0; i < 5; i++) await tick();
  const eur = $('regionCurrency').options.find(o => o.value === 'EUR');
  out.eur = { value: $('regionCurrency').value, label: eur && eur.textContent, partial: partialShown(),
              count: $('regionCurrency').options.filter(o => o.value === 'EUR').length };
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
        self.assertTrue(out['caAuto'])       # 'Theo quốc gia' cho Canada = CAD: phải nói thật
        self.assertFalse(out['usAuto'])
        self.assertTrue(out['gbAuto'])
        self.assertFalse(out['otherAuto'])   # Nước khác + tự động = USD
        self.assertTrue(out['nzd'])
        self.assertFalse(out['aud'])
        self.assertEqual(out['eur']['value'], 'EUR')
        self.assertEqual(out['eur']['label'], 'EUR (current)')
        self.assertTrue(out['eur']['partial'])
        self.assertEqual(out['eur']['count'], 1)


# ================================================================ 8. các chỗ đọc thô nước của tiệm
class RawCountryReadTests(core._Base):
    def test_spa_booking_language_follows_the_shop_country(self):
        ns = _funcs('blueprints/spa_bp.py', ['_shop_is_vi'], {'db': DB})
        _biz('sp_none')
        _biz('sp_other', country='OTHER')
        _biz('sp_vn', country='VN')
        _biz('sp_tz')
        _tz('sp_tz', 'Asia/Ho_Chi_Minh')
        _biz('sp_cur', currency='VND')
        _biz('sp_us', country='US', currency='USD')
        for bid, want in (('sp_none', False), ('ghost', False), ('sp_other', False), ('sp_vn', True), ('sp_tz', True),
                          ('sp_cur', True), ('sp_us', False)):
            self.assertEqual(ns['_shop_is_vi'](bid), want, bid)
        with patch.object(ai_packs, 'shop_country', side_effect=RuntimeError('boom')):
            self.assertFalse(ns['_shop_is_vi']('sp_vn'))

    def test_job_tracking_page_language(self):
        rendered = []
        ns = {'db': DB, 'render_template': lambda name, **kw: rendered.append(kw) or 'ok',
              '_public_task': lambda bid, tid, tok: {'id': tid}}
        _funcs('job_tracking.py', ['_shop_country', 'track_page'], ns)
        _biz('jt_tz')
        _tz('jt_tz', 'Asia/Ho_Chi_Minh')
        _biz('jt_cur', currency='VND')
        _biz('jt_other', country='OTHER', currency='VND')
        _biz('jt_au', country='AU')
        for bid, want in (('jt_tz', 'vi'), ('jt_cur', 'vi'), ('jt_other', 'en'), ('jt_au', 'en'), ('ghost', 'en')):
            ns['track_page'](bid, 1, 'tok')
            self.assertEqual(rendered[-1]['lang'], want, bid)
        self.assertEqual(rendered[0]['biz']['name'], 'Shop jt_tz')

    def test_roster_overtime_week_and_currency_follow_the_shop(self):
        ns = _funcs('shift_roster.py', ['_biz', '_shop_country', '_shop_currency', '_default_max_hours'], {'db': DB})
        _biz('ro_tz')
        _tz('ro_tz', 'Australia/Melbourne')             # Úc chỉ biết qua múi giờ: 38 giờ (Fair Work)
        _biz('ro_au', country='AU', currency='AUD')
        _biz('ro_us', country='US')
        _biz('ro_ca', country='CA')
        _biz('ro_other', country='OTHER', currency='AUD')
        for bid, hours, cur in (('ro_tz', 38, 'AUD'), ('ro_au', 38, 'AUD'), ('ro_us', 40, 'USD'), ('ro_ca', 40, 'CAD'),
                                ('ro_other', 40, 'AUD'), ('ghost', 40, 'USD')):
            self.assertEqual(ns['_default_max_hours'](bid), hours, bid)
            self.assertEqual(ns['_shop_currency'](bid), cur, bid)
            self.assertEqual(ns['_shop_currency'](bid), TenantEngine.get_region_config(bid)['currency'], bid)
        src = _read('shift_roster.py')
        self.assertNotIn("(biz.get('country') or '').upper() == 'AU'", src)
        self.assertNotIn("(biz.get('currency') or 'USD').upper(),", src)

    def test_chat_unavailable_reply_language(self):
        import ai_gateway
        _biz('gw_tz', name='Pho 24')
        _tz('gw_tz', 'Asia/Ho_Chi_Minh')
        _biz('gw_other', name='Elsewhere', country='OTHER', currency='VND')
        _biz('gw_us', name='Bay Nails', country='US', currency='USD')
        for bid, want in (('gw_tz', 'vi'), ('gw_other', 'en'), ('gw_us', 'en'), ('ghost', 'en')):
            self.assertEqual(ai_gateway.unavailable_reply(bid)['lang'], want, bid)
        self.assertEqual(ai_gateway.unavailable_reply('gw_us', 'xin chào, còn chỗ không')['lang'], 'vi')   # câu khách gõ thắng


if __name__ == '__main__':
    unittest.main(verbosity=2)
