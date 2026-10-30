# -*- coding: utf-8 -*-
"""Test OFFLINE — chế độ app store (chính sách thanh toán Google Play / App Store 3.1.1).

Trong app mobile BitPaw (Flutter WebView, User-Agent "BitPawMobileApp/1.0.0 (Android; WebView)" / "(iOS; WebView)") KHÔNG
có cách nào mua / nâng cấp / xem giá gói BitPaw; trình duyệt thường (Chrome desktop...) KHÔNG đổi gì:
  1. is_store_app(request) (app.py) + biến template store_app (context processor inject_industry_config); UA thật của
     mobile_app/lib/screens/webview_screen.dart được nhận ra.
  2. Route mua / đổi gói trong app: /checkout + /pricing -> trang trung tính (tên gói hiện tại + "Plan changes are not
     available in the app.", KHÔNG link / URL / lời mời ra website); /api/checkout/*, /api/plan/* -> 403 JSON và KHÔNG ghi gì;
     /plan -> chỉ gói hiện tại (giữ sidebar), không giá / nút nâng cấp / script gửi yêu cầu; _plan_gate (trang + API) và
     plan_lock nói "không có trong gói hiện tại", không nhắc gói cao hơn; bot bán gói BitPaw (/api/ai/studio/generate ngoài
     chat đặt lịch) -> 403; trang marketing / bảng giá (gồm /landingpage) -> về đăng nhập. Danh mục MỌI route có dáng mua bán
     trong code được phân loại (route mới phải được xếp loại thì test mới qua).
  3. Template: components/pricing.html, plan.html, app_feature_unavailable.html, ai_bot.html, ai-studio.html, social.html,
     oauth_complete.html, legal/payment_*.html — bản app không link /plan, /checkout, /pricing, #bang-gia, không giá; bản trình
     duyệt giữ nguyên. Script inline render ra phải là JS hợp lệ (node --check). cskh_widget.js (bot bán gói) tự ẩn trong app,
     chat đặt lịch của tiệm vẫn chạy.
  4. Trình duyệt: cùng status + cùng HTML cho Chrome desktop / không UA / Safari iPhone / Chrome Android trên các route chính.
     So với bản TRƯỚC thay đổi (byte-for-byte, template lấy từ git): đặt STORE_APP_BASELINE=<commit>, vd
       STORE_APP_BASELINE=4b2e3f52 python scripts/tests/test_store_app_mode.py

KHÔNG import app.py, KHÔNG mở MongoDB (mongo_client bị stub trước mọi import), KHÔNG gọi mạng / API trả phí, KHÔNG chạy server:
hàm thật của app.py (kể cả decorator @app.route / before_request / context_processor) lấy qua ast và chạy trên 1 app Flask thử.
Chạy: python scripts/tests/test_store_app_mode.py
"""
import ast
import copy
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime
from functools import wraps

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ---------------------------------------------------------------- DB giả trong RAM (đủ cho các route được test)
class _Cursor(list):
    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs = []

    @staticmethod
    def _match(doc, query):
        return all(doc.get(k) == v for k, v in (query or {}).items())

    @staticmethod
    def _project(doc, proj):
        out = {k: v for k, v in doc.items() if k != '_id'}
        if proj:
            keep = [k for k, v in proj.items() if v and k != '_id']
            if keep:
                out = {k: out[k] for k in keep if k in out}
        return out

    def find_one(self, query=None, proj=None):
        for d in self.docs:
            if self._match(d, query):
                return self._project(d, proj)
        return None

    def find(self, query=None, proj=None):
        return _Cursor(self._project(d, proj) for d in self.docs if self._match(d, query))

    def insert_one(self, doc):
        doc['_id'] = len(self.docs) + 1
        self.docs.append(doc)
        return types.SimpleNamespace(inserted_id=doc['_id'])


class FakeDB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self._c.setdefault(name, FakeCollection(name))

    def reset(self):
        self._c.clear()


DB = FakeDB()
_ids = itertools.count(500)
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED')
sys.modules['requests'] = types.SimpleNamespace(post=None, get=None)   # không lệnh mạng nào được phép

from flask import Flask, flash, g, jsonify, redirect, render_template, render_template_string, request, session, url_for  # noqa: E402
from jinja2 import ChoiceLoader, FunctionLoader  # noqa: E402
from markupsafe import Markup  # noqa: E402

import industry_access  # noqa: E402
import plans  # noqa: E402
from i18n import get_translations, resolve_lang  # noqa: E402


def read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


# ---------------------------------------------------------------- mã thật của app.py qua ast (không import app.py)
APP_SRC = read('app.py')
APP_TREE = ast.parse(APP_SRC)

APP_ASSIGNS = ('INDUSTRY_CONFIG', 'SUPERADMIN_ROOT_EMAIL', 'SAAS_CURRENCIES', 'SAAS_PLANS', 'SAAS_PRICING', 'SAAS_PLAN_ALIASES',
               '_MOBILE_APP_MARKETING_PATHS', '_STORE_APP_BLOCKED_PAGES', '_STORE_APP_BLOCKED_API_PREFIXES', '_LEGAL_PAGES')
APP_FUNCS = ('_wants_json', '_vi_en', 'login_required', '_is_authorized_superadmin_email', '_is_superadmin', 'inject_industry_config',
             'is_store_app', '_store_app_plan_page', '_mobile_app_store_policy', '_render_legal_page', 'privacy_policy_page',
             'terms_page', 'payment_policy_page', 'public_checkout', 'api_checkout_payment_methods', 'inject_saas_plans',
             'api_checkout_signup', '_session_business_id', '_plan_gate', 'inject_current_plan', 'plan_page', 'api_plan_request')


def _top_nodes():
    want = set(APP_ASSIGNS) | set(APP_FUNCS)
    nodes = []
    for n in APP_TREE.body:
        if isinstance(n, ast.FunctionDef) and n.name in want:
            nodes.append(n)
        elif isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in want for t in n.targets):
            nodes.append(n)
    found = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id for n in nodes}
    missing = want - found
    assert not missing, f'app.py thiếu: {sorted(missing)}'
    return [copy.deepcopy(n) for n in sorted(nodes, key=lambda n: n.lineno)]   # đúng thứ tự file (thứ tự before_request)


EMAILS = []
FLASK = Flask('store_app_test', root_path=ROOT, template_folder='templates', static_folder='static')
FLASK.secret_key = 'test-only'
FLASK.config['TESTING'] = True
FLASK.jinja_env.globals['csrf_token'] = lambda: 'test-csrf'
FLASK.jinja_env.globals['NAIL_3D_ICONS'] = {}
_FS_LOADER = FLASK.jinja_loader

NS = dict(app=FLASK, request=request, session=session, g=g, jsonify=jsonify, render_template=render_template,
          redirect=redirect, url_for=url_for, flash=flash, Markup=Markup, wraps=wraps, resolve_lang=resolve_lang,
          get_translations=get_translations, plans=plans, industry_access=industry_access, db=DB,
          next_mongo_id=lambda c: next(_ids), re=re, os=os, json=json, datetime=datetime, _ASSET_VERSION='test',
          TenantEngine=types.SimpleNamespace(get_region_config=lambda bid: {'country': 'US', 'currency': 'USD'}),
          limiter=types.SimpleNamespace(limit=lambda *a, **k: (lambda f: f)),
          EmailService=types.SimpleNamespace(send_email=lambda *a, **k: EMAILS.append(a) or True))
exec(compile(ast.Module(body=_top_nodes(), type_ignores=[]), os.path.join(ROOT, 'app.py'), 'exec'), NS)
is_store_app = NS['is_store_app']


def _stub(rule, endpoint, body=None, methods=('GET',)):
    FLASK.add_url_rule(rule, endpoint, lambda **kw: body if body is not None else jsonify({'success': True, 'reached': endpoint}),
                       methods=list(methods))


_stub('/login', 'login', 'LOGIN-PAGE')
_stub('/', 'root', 'ROOT')
_stub('/landing', 'landingpage', 'LANDING-PAGE')
FLASK.add_url_rule('/landingpage', 'landingpage_alias', lambda: 'LANDING-PAGE')
_stub('/landing_nail', 'legacy_landing_nail', 'LANDING-NAIL')
_stub('/solutions/<industry_code>', 'solutions_page', 'SOLUTIONS-PAGE')
_stub('/roster', 'roster_page', 'ROSTER-PAGE')
_stub('/api/roster', 'api_roster', methods=('GET', 'POST'))
_stub('/api/ai/studio/generate', 'secure_ai_generate', methods=('POST',))
_stub('/account/delete', 'account_delete_page', 'DELETE-PAGE')
for _ep in sorted(set(re.findall(r"url_for\('([a-z_]+)'", read('templates/components/app_sidebar.html')))):
    if _ep != 'static' and _ep not in FLASK.view_functions:   # sidebar thật cần đủ endpoint để url_for chạy
        _stub(f'/_sidebar/{_ep}', _ep, _ep.upper())

BID = 'biz-store-1'
APP_UA_ANDROID = 'BitPawMobileApp/1.0.0 (Android; WebView)'
APP_UA_IOS = 'BitPawMobileApp/1.0.0 (iOS; WebView)'
APP_UAS = (APP_UA_ANDROID, APP_UA_IOS)
CHROME_DESKTOP = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/130.0.0.0 Safari/537.36')
BROWSER_UAS = (CHROME_DESKTOP, '',
               'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 '
               'Mobile/15E148 Safari/604.1',
               'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36')

PRICE_RE = re.compile(r'(?:A?\$|US\$)\s?\d')
# Mọi cách dẫn tới chỗ mua / xem giá gói (link, URL, lời mời ra website) — KHÔNG được có trong HTML bản app
STEERING_RE = re.compile(r'href="/plan[?"]|/checkout\b|/pricing\b|#bang-gia|/api/plan/request|bitpawsoftware\.com|https?://|'
                         r'\bwww\.|visit our website|trang web của chúng tôi|our website|Upgrade to|Nâng cấp lên|See plans</a>|'
                         r'Xem gói</a>|Xem các gói</a>', re.I)
NEUTRAL_EN = 'Plan changes are not available in the app.'
NEUTRAL_VI = 'Đổi gói không khả dụng trong ứng dụng.'


def reset_state(plan='essential', industry='nail'):
    DB.reset()
    EMAILS.clear()
    plans._PLAN_CACHE.clear()
    DB.businesses.insert_one({'id': BID, 'name': 'Lotus Nails', 'owner_name': 'Kim', 'phone': '+1 555 0100', 'plan': plan,
                              'industry_code': industry})
    DB.payment_methods.insert_one({'id': 1, 'bin_code': '970436', 'provider_name': 'Bank', 'account_number': '0123',
                                   'account_name': 'BITPAW', 'is_active': True})


def client(ua, logged_in=False, lang='en', industry='nail', role='admin'):
    c = FLASK.test_client()
    c.environ_base['HTTP_USER_AGENT'] = ua
    c.set_cookie('bitpaw_lang', lang)
    if logged_in:
        with c.session_transaction() as s:
            s.update({'user_id': BID, 'business_id': BID, 'role': role, 'business_mode': industry,
                      'user_email': 'owner@lotus.test'})
    return c


SIGNUP = {'customer_name': 'Kim', 'phone': '+1 555 0100', 'shop_name': 'Lotus Nails', 'email': 'kim@lotus.test',
          'plan': 'pro', 'currency': 'USD', 'industry': 'nail', 'country': 'US'}


def node_check(code):
    node = shutil.which('node')
    if not node:
        return None
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as fh:
        fh.write(code)
    try:
        r = subprocess.run([node, '--check', fh.name], capture_output=True, text=True, encoding='utf-8')
        return r.returncode == 0, r.stderr[-600:]
    finally:
        os.unlink(fh.name)


def inline_scripts(html):
    return [m.group(1) for m in re.finditer(r'<script(?![^>]*\bsrc=)(?![^>]*application/(?:ld\+)?json)[^>]*>(.*?)</script>', html, re.S)]


# ================================================================ 1. helper + biến template
class HelperTests(unittest.TestCase):
    def test_detects_app_user_agents_only(self):
        for ua in APP_UAS + ('Mozilla/5.0 (Linux; Android 14; wv) BitPawMobileApp/2.3.1 (Android; WebView)',):
            with FLASK.test_request_context('/', headers={'User-Agent': ua}):
                self.assertTrue(is_store_app(request), ua)
                self.assertTrue(is_store_app(), ua)
        for ua in BROWSER_UAS + ('BitPawMobileApp', 'bitpaw mobile app'):
            with FLASK.test_request_context('/', headers={'User-Agent': ua}):
                self.assertFalse(is_store_app(request), ua)
        self.assertFalse(is_store_app())                                       # ngoài request context
        self.assertTrue(is_store_app(types.SimpleNamespace(headers={'User-Agent': APP_UA_IOS})))
        self.assertFalse(is_store_app(types.SimpleNamespace(headers={})))

    def test_real_mobile_app_user_agent_is_recognised(self):
        dart = read('mobile_app/lib/screens/webview_screen.dart')
        m = re.search(r"setUserAgent\('(.*)'\)", dart)                        # 1 dòng; trong ${...} có dấu ' nên lấy tham lam
        self.assertIsNotNone(m, 'không thấy setUserAgent trong webview_screen.dart')
        for plat in ('iOS', 'Android'):
            ua = re.sub(r"\$\{[^}]*\}", plat, m.group(1))
            with FLASK.test_request_context('/', headers={'User-Agent': ua}):
                self.assertTrue(is_store_app(request), ua)
        self.assertNotIn('_MOBILE_APP_UA_RE', dart)                            # chú thích trỏ đúng hàm còn tồn tại

    def test_template_variable_from_context_processor(self):
        for ua, want in ((APP_UA_ANDROID, 'True'), (APP_UA_IOS, 'True'), (CHROME_DESKTOP, 'False'), ('', 'False')):
            with FLASK.test_request_context('/', headers={'User-Agent': ua}):
                self.assertEqual(render_template_string('{{ store_app }}'), want, ua)
        src = ast.get_source_segment(APP_SRC, next(n for n in APP_TREE.body if isinstance(n, ast.FunctionDef)
                                                   and n.name == 'inject_industry_config'))
        self.assertIn('store_app=is_store_app(request)', src)


# ================================================================ 2. route mua / đổi gói
class PurchaseRouteTests(unittest.TestCase):
    def setUp(self):
        reset_state()

    def assert_neutral_page(self, html, plan_name=None, vi=False):
        self.assertIn(NEUTRAL_VI if vi else NEUTRAL_EN, html)
        self.assertNotIn('<a ', html)
        self.assertNotIn('href', html)
        self.assertNotIn('<button', html)
        self.assertIsNone(STEERING_RE.search(html), STEERING_RE.search(html))
        self.assertIsNone(PRICE_RE.search(html))
        if plan_name:
            self.assertIn(f'<b>{plan_name}</b>', html)

    def test_checkout_page(self):
        for ua in APP_UAS:
            r = client(ua).get('/checkout?plan=pro&industry=nail&currency=USD')
            self.assertEqual(r.status_code, 200)
            self.assert_neutral_page(r.get_data(as_text=True))
            r = client(ua, logged_in=True).get('/checkout')
            self.assert_neutral_page(r.get_data(as_text=True), plan_name='Essential')
            r = client(ua, logged_in=True, lang='vi').get('/checkout')
            self.assert_neutral_page(r.get_data(as_text=True), plan_name='Essential', vi=True)
        r = client(CHROME_DESKTOP).get('/checkout')
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("fetch('/api/checkout/signup'", html)                       # trang đăng ký gói thật cho trình duyệt
        self.assertNotIn(NEUTRAL_EN, html)

    def test_pricing_path(self):
        for ua in APP_UAS:
            r = client(ua).get('/pricing')
            self.assertEqual(r.status_code, 200)
            self.assert_neutral_page(r.get_data(as_text=True))
        self.assertEqual(client(CHROME_DESKTOP).get('/pricing').status_code, 404)   # trình duyệt: như cũ (không có trang này)

    def test_checkout_apis_refused_in_app_and_nothing_saved(self):
        for ua in APP_UAS:
            for lang, word in (('en', 'Not available'), ('vi', 'Không khả dụng')):
                c = client(ua, lang=lang)
                r = c.post('/api/checkout/signup', json=SIGNUP)
                self.assertEqual(r.status_code, 403)
                self.assertIs(r.get_json()['success'], False)
                self.assertIn(word, r.get_json()['message'])
                r = c.get('/api/checkout/payment_methods')
                self.assertEqual(r.status_code, 403)
                self.assertNotIn('account_number', r.get_data(as_text=True))
        self.assertEqual(DB.saas_signups.docs, [])
        self.assertEqual(EMAILS, [])
        c = client(CHROME_DESKTOP)
        r = c.post('/api/checkout/signup', json=SIGNUP)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()['data']['plan'], 'pro')
        self.assertEqual(len(DB.saas_signups.docs), 1)
        r = c.get('/api/checkout/payment_methods')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['data'][0]['account_number'], '0123')

    def test_plan_request_api_refused_in_app(self):
        for ua in APP_UAS:
            r = client(ua, logged_in=True).post('/api/plan/request', json={'plan': 'pro'})
            self.assertEqual(r.status_code, 403)
            self.assertNotIn('monthly_fee', r.get_data(as_text=True))
        self.assertEqual(DB.saas_signups.docs, [])
        self.assertEqual(EMAILS, [])
        r = client(CHROME_DESKTOP, logged_in=True).post('/api/plan/request', json={'plan': 'pro'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(DB.saas_signups.docs[0]['type'], 'upgrade')
        self.assertEqual(len(EMAILS), 1)

    def test_plan_page_in_app_shows_only_current_plan(self):
        for ua in APP_UAS:
            for lang in ('en', 'vi'):
                r = client(ua, logged_in=True, lang=lang).get('/plan')
                self.assertEqual(r.status_code, 200)
                html = r.get_data(as_text=True)
                main = html[html.index('<main class="pl-main">'):]              # nội dung trang (sau sidebar) tới hết
                self.assertIn(NEUTRAL_VI if lang == 'vi' else NEUTRAL_EN, main)
                self.assertIn('<b>Essential</b>', main)
                self.assertIsNone(PRICE_RE.search(main), PRICE_RE.search(main))
                self.assertIsNone(STEERING_RE.search(main), STEERING_RE.search(main))
                for bad in ('data-plan=', '<button', '<script', 'invoice', 'hoá đơn', 'Pro Partner', 'Empire Scale', '/ month'):
                    self.assertNotIn(bad, main, (lang, bad))
                self.assertIn('id="app-sidebar"', html)                         # vẫn điều hướng được trong app
                self.assertIsNone(PRICE_RE.search(html))

    def test_plan_page_feature_lock_in_app_is_neutral(self):
        for ua in APP_UAS:
            html = client(ua, logged_in=True).get('/plan?feature=roster').get_data(as_text=True)
            self.assertIn('“Shift roster” is not included in your current plan.', html)
            self.assertNotIn('and above', html)
            html = client(ua, logged_in=True, lang='vi').get('/plan?feature=ai_studio').get_data(as_text=True)
            self.assertIn('“AI Studio” không có trong gói hiện tại của bạn.', html)
            self.assertNotIn('trở lên', html)

    def test_plan_page_in_browser_unchanged(self):
        html = client(CHROME_DESKTOP, logged_in=True).get('/plan?feature=roster').get_data(as_text=True)
        nail = {c['key']: c for c in plans.tier_cards('nail')}
        for key in ('essential', 'pro', 'empire'):
            self.assertIn(f"<b>${nail[key]['monthly']['USD']}</b>", html)
        self.assertIn('Upgrade to Pro Partner', html)
        self.assertIn('data-plan="pro"', html)
        self.assertIn("fetch('/api/plan/request'", html)
        self.assertIn('“Shift roster” is included in Pro Partner and above.', html)
        self.assertNotIn(NEUTRAL_EN, html)

    def test_plan_gate_page_and_api(self):
        reset_state('essential')
        for ua in APP_UAS + (CHROME_DESKTOP,):
            r = client(ua, logged_in=True).get('/roster')
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r.headers['Location'].endswith('/plan?feature=roster'))   # trong app /plan là trang trung tính
        for ua in APP_UAS:
            for lang, want in (('en', 'Shift roster is not included in your current plan.'),
                               ('vi', 'Lịch ca làm việc không có trong gói hiện tại của bạn.')):
                r = client(ua, logged_in=True, lang=lang).get('/api/roster')
                self.assertEqual(r.status_code, 403)
                self.assertEqual(r.get_json()['message'], want)
                self.assertTrue(r.get_json()['upgrade_required'])
        r = client(CHROME_DESKTOP, logged_in=True).get('/api/roster')
        self.assertEqual(r.get_json()['message'], 'Shift roster is included in Pro Partner and above.')
        self.assertEqual(client(APP_UA_IOS, logged_in=True).get('/api/roster').status_code, 403)
        reset_state('pro')
        self.assertEqual(client(APP_UA_IOS, logged_in=True).get('/api/roster').status_code, 200)   # gói đủ: không đổi gì

    def test_plan_lock_badge(self):
        reset_state('essential')
        tpl = "{{ plan_lock('roster') }}|{{ plan_lock('ai_studio') }}|{{ plan_lock('nothing_locked') }}"
        for ua in APP_UAS:
            for lang, note in (('en', 'Not included in your current plan'), ('vi', 'Không có trong gói hiện tại của bạn')):
                with FLASK.test_request_context('/', headers={'User-Agent': ua, 'Cookie': f'bitpaw_lang={lang}'}):
                    session.update({'user_id': BID, 'business_id': BID, 'role': 'admin', 'business_mode': 'nail'})
                    out = render_template_string(tpl)
                lock = f'<span class="plan-lock" title="{note}" aria-label="{note}"><i class="fas fa-lock"></i></span>'
                self.assertEqual(out, f'{lock}|{lock}|')
        with FLASK.test_request_context('/', headers={'User-Agent': CHROME_DESKTOP}):
            session.update({'user_id': BID, 'business_id': BID, 'role': 'admin', 'business_mode': 'nail'})
            out = render_template_string(tpl)
        self.assertEqual(out, '<span class="plan-lock" title="Pro Partner"><i class="fas fa-lock"></i> Pro</span>|'
                              '<span class="plan-lock" title="Empire Scale"><i class="fas fa-lock"></i> Empire</span>|')

    def test_sidebar_in_app_has_no_tier_upsell(self):
        reset_state('essential')
        for ua in APP_UAS:
            html = client(ua, logged_in=True).get('/plan').get_data(as_text=True)
            locks = re.findall(r'<span class="plan-lock"[^>]*>.*?</span>', html, re.S)
            self.assertTrue(locks)
            for s in locks:
                self.assertNotRegex(s, r'Pro|Empire|Essential|\$')
            self.assertIn('href="/plan?feature=ai_copilot"', html)   # khoá Copilot -> /plan, trong app là trang trung tính
        html = client(CHROME_DESKTOP, logged_in=True).get('/plan').get_data(as_text=True)
        self.assertIn('<i class="fas fa-lock"></i> Pro</span>', html)

    def test_sales_bot_refused_in_app_booking_chat_kept(self):
        for ua in APP_UAS:
            c = client(ua)
            for body in ({'userPrompt': 'how much is Pro?'}, {'context': 'sales', 'userPrompt': 'price?'}, None, ['x']):
                r = c.post('/api/ai/studio/generate', json=body) if body is not None else c.post('/api/ai/studio/generate')
                self.assertEqual(r.status_code, 403, body)
                self.assertNotIn('reached', r.get_data(as_text=True))
            r = c.post('/api/ai/studio/generate', json={'context': 'customer_booking', 'business_id': BID, 'customer_message': 'hi'})
            self.assertEqual(r.get_json(), {'success': True, 'reached': 'secure_ai_generate'})
        for ua in BROWSER_UAS:
            r = client(ua).post('/api/ai/studio/generate', json={'userPrompt': 'how much is Pro?'})
            self.assertEqual(r.get_json(), {'success': True, 'reached': 'secure_ai_generate'})

    def test_marketing_pages_redirect_to_login_in_app(self):
        for ua in APP_UAS:
            for path in ('/landing', '/landingpage', '/landing_nail', '/solutions/nail', '/solutions/fnb'):
                r = client(ua).get(path)
                self.assertEqual(r.status_code, 302, path)
                self.assertTrue(r.headers['Location'].endswith('/login'), (path, r.headers['Location']))
                r = client(ua, logged_in=True).get(path)
                self.assertTrue(r.headers['Location'].endswith('/'), (path, r.headers['Location']))
        for ua in BROWSER_UAS:
            for path, body in (('/landing', 'LANDING-PAGE'), ('/landingpage', 'LANDING-PAGE'), ('/solutions/nail', 'SOLUTIONS-PAGE')):
                r = client(ua).get(path)
                self.assertEqual((r.status_code, r.get_data(as_text=True)), (200, body), (ua, path))

    def test_payment_policy_has_no_pricing_link_in_app(self):
        for lang, words in (('en', 'shown on our pricing page and confirmed'), ('vi', 'niêm yết trên trang bảng giá và ghi rõ')):
            for ua in APP_UAS:
                html = client(ua).get(f'/payment-policy?lang={lang}').get_data(as_text=True)
                self.assertIn(words, html)
                self.assertNotIn('#bang-gia', html)
                self.assertNotIn('href="/landing', html)
            html = client(CHROME_DESKTOP).get(f'/payment-policy?lang={lang}').get_data(as_text=True)
            self.assertIn('<a href="/landing#bang-gia">', html)


# ================================================================ 2b. danh mục route có dáng mua bán (route mới phải được xếp loại)
ROUTE_KEYWORDS = re.compile(r'checkout|pricing|plan|subscri|upgrade|billing|payment|stripe|paypal|square|invoice|price|trial|'
                            r'license|duc_ma|signup|register|purchase|buy', re.I)
STORE_BLOCKED = {'/checkout', '/api/checkout/payment_methods', '/api/checkout/signup', '/api/plan/request'}
STORE_NEUTRAL = {'/plan'}                       # trang trung tính (gói hiện tại, không giá / nút / link)
NOT_BITPAW_PLAN_PURCHASE = {
    # Thanh toán của KHÁCH tại tiệm (dịch vụ / hàng hoá thật, dùng ngoài app — ngoài phạm vi chính sách thanh toán số)
    '/api/sales/checkout', '/api/payments/square/checkout', '/api/payments/square/status/<int:order_id>',
    '/api/payments/square/cancel', '/api/webhooks/square', '/api/pos/order_items/<int:item_id>/price', '/checkout/<int:table_id>',
    '/payment_transactions', '/update_payment_status/<int:id>', '/api/payment_transactions', '/api/payment_transactions/<int:id>',
    '/api/karaoke/rooms/<int:room_id>/checkout', '/api/hotel/rooms/<int:room_id>/expected_checkout',
    '/api/hotel/rooms/<int:room_id>/checkout', '/payment_gateway', '/api/payment/save_config', '/payment_history',
    '/payment_pending', '/api/payment/start', '/api/us-payment/start', '/api/payment/confirm', '/api/payment/local_checkout',
    '/api/payment/cancel', '/payment_success', '/api/nail_pos/checkout', '/api/nail_pos/square_checkout', '/checkout_spa',
    # Chấm công ra ca, kế hoạch nội dung AI, huỷ nhận tin — không liên quan mua gói
    '/api/chamcong/checkout', '/scene_plan', '/api/social/plan/week', '/unsubscribe',
    # Trang pháp lý (link sang bảng giá đã ẩn trong app) + đăng ký bằng mã kích hoạt cấp sẵn (không có bước thanh toán)
    '/payment-policy', '/register',
    # Chỉ super admin của BitPaw (không phải người mua)
    '/api/superadmin/saas_signups', '/api/superadmin/saas_signups/<int:signup_id>/status', '/api/superadmin/business_plan',
    '/api/superadmin/duc_ma', '/api/superadmin/payment_methods', '/api/superadmin/payment_methods/<int:id>',
}


class RouteInventoryTests(unittest.TestCase):
    def test_every_purchase_like_route_is_classified(self):
        files = [f for f in os.listdir(ROOT) if f.endswith('.py') and not f.startswith('test_')]
        files += [os.path.join('blueprints', f) for f in os.listdir(os.path.join(ROOT, 'blueprints')) if f.endswith('.py')]
        routes = set()
        for f in files:
            for m in re.finditer(r"@\w+\.route\(\s*['\"]([^'\"]+)['\"]", read(f)):
                if ROUTE_KEYWORDS.search(m.group(1)):
                    routes.add(m.group(1))
        known = STORE_BLOCKED | STORE_NEUTRAL | NOT_BITPAW_PLAN_PURCHASE
        self.assertEqual(sorted(routes - known), [], 'route mới có dáng mua bán: xếp loại + chặn trong app nếu là mua gói')
        self.assertTrue(STORE_BLOCKED <= routes)

    def test_blocked_routes_really_blocked_in_app(self):
        reset_state()
        for ua in APP_UAS:
            c = client(ua, logged_in=True)
            for path in sorted(STORE_BLOCKED):
                r = c.post(path, json={'plan': 'pro'}) if path in ('/api/checkout/signup', '/api/plan/request') else c.get(path)
                if path.startswith('/api/'):
                    self.assertEqual(r.status_code, 403, path)
                else:
                    self.assertIn(NEUTRAL_EN, r.get_data(as_text=True), path)
        self.assertEqual(DB.saas_signups.docs, [])


# ================================================================ 3. template
def render_tpl(name, store, lang='en', **ctx):
    """Render 1 template thật qua app thử (đủ context processor thật) với UA app / Chrome desktop."""
    ua = APP_UA_ANDROID if store else CHROME_DESKTOP
    with FLASK.test_request_context('/', headers={'User-Agent': ua, 'Cookie': f'bitpaw_lang={lang}'}):
        session.update({'user_id': BID, 'business_id': BID, 'role': 'admin', 'business_mode': 'nail',
                        'user_email': 'owner@lotus.test'})
        return render_template(name, **ctx)


def _lenient(name, ctx):
    """Template rất lớn (ai_bot / ai-studio / social): biến thiếu = rỗng, như test_phase1_frontend_followups."""
    from jinja2 import ChainableUndefined, Environment, select_autoescape
    from jinja2 import DictLoader
    env = Environment(loader=ChoiceLoader([DictLoader({'components/app_sidebar.html': '<aside id="app-sidebar"></aside>'}),
                                           FLASK.jinja_loader]),
                      autoescape=select_autoescape(['html']), undefined=ChainableUndefined)
    base = dict(url_for=lambda e, **kw: ('/static/' + kw['filename']) if e == 'static' else '/' + e, asset_v=lambda p: 'test',
                session={'role': 'admin', 'business_id': BID}, default_lang='en', active_industry_code='nail',
                tenant_currency='USD', tenant_country='US', menu_i18n={}, copilot_enabled=True, csrf_token=lambda: 'x')
    base.update(ctx)
    return env.get_template(name).render(**base)


BIG_TEMPLATES = ('ai_bot.html', 'ai-studio.html', 'social.html')


class TemplateTests(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_pricing_component(self):
        wrapper = "<div id=w>{% include 'components/pricing.html' %}</div>"
        for ua in APP_UAS:
            with FLASK.test_request_context('/', headers={'User-Agent': ua}):
                out = render_template_string(wrapper)
            self.assertEqual(re.sub(r'\s+', '', out), '<divid=w></div>')
        with FLASK.test_request_context('/', headers={'User-Agent': CHROME_DESKTOP}):
            out = render_template_string(wrapper)
        self.assertIn('id="bang-gia"', out)
        self.assertIn('/checkout?plan=', out)
        self.assertRegex(out, r'\$\{|\$')
        ok = node_check(inline_scripts(out)[0])
        if ok is not None:
            self.assertTrue(ok[0], ok[1])

    def test_neutral_page_template(self):
        for lang, text in (('en', NEUTRAL_EN), ('vi', NEUTRAL_VI)):
            for plan_name in (None, 'Pro Partner'):
                html = render_tpl('app_feature_unavailable.html', True, lang=lang, store_plan_name=plan_name)
                self.assertIn(text, html)
                self.assertNotIn('<a', html)
                self.assertNotIn('href', html)
                self.assertIsNone(STEERING_RE.search(html))
                self.assertEqual(plan_name is not None, f'<b>{plan_name}</b>' in html)

    def test_big_templates_store_vs_browser(self):
        for name in BIG_TEMPLATES:
            for lang in ('en', 'vi'):
                app_html = _lenient(name, {'store_app': True, 'default_lang': lang})
                web_html = _lenient(name, {'store_app': False, 'default_lang': lang})
                self.assertEqual(web_html, _lenient(name, {'default_lang': lang}), name)   # store_app vắng = trình duyệt
                self.assertNotRegex(app_html, r'href="/plan', name)
                for html, mode in ((app_html, 'app'), (web_html, 'web')):
                    for i, js in enumerate(inline_scripts(html)):
                        ok = node_check(js)
                        if ok is not None:
                            self.assertTrue(ok[0], f'{name} {mode} {lang} script#{i}: {ok[1]}')
        ai_bot_app, ai_bot_web = _lenient('ai_bot.html', {'store_app': True}), _lenient('ai_bot.html', {'store_app': False})
        self.assertIn("'The owner Copilot is not included in your current plan.'", ai_bot_app)
        self.assertNotIn('Empire Scale', ai_bot_app)
        for link in ('href="/plan?feature=ai_copilot"', 'href="/plan?feature=ai_inbox"'):
            self.assertIn(link, ai_bot_web)
        self.assertIn('is included in Empire Scale.', ai_bot_web)
        self.assertIn('href="/plan?feature=ai_studio"', _lenient('ai-studio.html', {'store_app': False}))
        social_app, social_web = _lenient('social.html', {'store_app': True}), _lenient('social.html', {'store_app': False})
        self.assertIn("upgrade: 'Not included in your current plan.'", social_app)
        self.assertIn("upgrade: 'Không có trong gói hiện tại của bạn.'", social_app)
        self.assertNotIn('higher plan', social_app)
        self.assertNotIn('gói cao hơn', social_app)
        self.assertIn("upgrade: 'This is part of a higher plan.'", social_web)

    def test_oauth_complete_has_no_checkout_line_in_app(self):
        ctx = dict(pend={'email': 'kim@lotus.test', 'name': 'Kim', 'provider': 'google'}, industry_en={}, industries={'nail': {'name': 'Nail'}})
        for lang in ('en', 'vi'):
            app_html = render_tpl('oauth_complete.html', True, lang=lang, **ctx)
            self.assertNotIn('/checkout', app_html)
            self.assertNotIn('class="help"', app_html)
            self.assertIn('<form', app_html)                                    # vẫn hoàn tất tài khoản bằng mã kích hoạt
            web_html = render_tpl('oauth_complete.html', False, lang=lang, **ctx)
            self.assertIn('<a href="/checkout">/checkout</a>', web_html)

    def test_widget_hides_sales_bot_in_app_only(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not installed')
        js = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
function started(ua, ctx) {
  let handler = null, touched = 0;
  const STOP = new Error('widget-started');
  const hit = () => { touched++; throw STOP; };
  const document = { addEventListener: (ev, fn) => { if (ev === 'DOMContentLoaded') handler = fn; },
                     getElementById: hit, querySelectorAll: hit, querySelector: hit, createElement: hit,
                     documentElement: { lang: 'en' }, head: {}, body: {} };
  new Function('document', 'window', 'navigator', src)(document, { BITPAW_CHAT_CONTEXT: ctx }, { userAgent: ua });
  try { handler(); } catch (e) { if (e !== STOP) throw e; }
  return touched > 0;
}
const APP = 'Mozilla/5.0 (Linux; Android 14; wv) BitPawMobileApp/1.0.0 (Android; WebView)';
const IOS = 'BitPawMobileApp/1.0.0 (iOS; WebView)';
const WEB = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0.0.0 Safari/537.36';
console.log(JSON.stringify({ app: started(APP), ios: started(IOS), appBooking: started(APP, 'customer_booking'),
                             web: started(WEB), webBooking: started(WEB, 'customer_booking') }));
"""
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as fh:
            fh.write(js)
        try:
            r = subprocess.run([node, fh.name, os.path.join(ROOT, 'static', 'js', 'cskh_widget.js')],
                               capture_output=True, text=True, encoding='utf-8')
        finally:
            os.unlink(fh.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'app': False, 'ios': False, 'appBooking': True, 'web': True, 'webBooking': True})


# ================================================================ 4. trình duyệt không đổi
BROWSER_ROUTES = (('GET', '/checkout', False), ('GET', '/checkout?plan=pro&industry=spa&currency=AUD', False),
                  ('GET', '/pricing', False), ('GET', '/plan', True), ('GET', '/plan?feature=roster', True),
                  ('GET', '/payment-policy?lang=en', False), ('GET', '/payment-policy?lang=vi', False), ('GET', '/terms', False),
                  ('GET', '/landing', False), ('GET', '/landingpage', False), ('GET', '/solutions/nail', False),
                  ('GET', '/roster', True), ('GET', '/api/roster', True), ('GET', '/api/checkout/payment_methods', False))


def browser_snapshot(ua):
    out = []
    for method, path, logged_in in BROWSER_ROUTES:
        reset_state()
        r = client(ua, logged_in=logged_in).open(path, method=method)
        out.append((path, r.status_code, r.headers.get('Location'), r.get_data(as_text=True)))
    return out


class BrowserUnchangedTests(unittest.TestCase):
    def test_same_status_and_html_for_every_browser_user_agent(self):
        base = browser_snapshot(CHROME_DESKTOP)
        for path, status, _loc, body in base:
            self.assertNotIn(NEUTRAL_EN, body, path)
        for ua in BROWSER_UAS[1:]:
            self.assertEqual(browser_snapshot(ua), base, ua)
        self.assertEqual(dict((p, s) for p, s, _l, _b in base),
                         {'/checkout': 200, '/checkout?plan=pro&industry=spa&currency=AUD': 200, '/pricing': 404, '/plan': 200,
                          '/plan?feature=roster': 200, '/payment-policy?lang=en': 200, '/payment-policy?lang=vi': 200,
                          '/terms': 200, '/landing': 200, '/landingpage': 200, '/solutions/nail': 200, '/roster': 302,
                          '/api/roster': 403, '/api/checkout/payment_methods': 200})

    def test_app_differs_from_browser_on_purchase_routes(self):
        app = dict((p, (s, b)) for p, s, _l, b in browser_snapshot(APP_UA_ANDROID))
        web = dict((p, (s, b)) for p, s, _l, b in browser_snapshot(CHROME_DESKTOP))
        for path in ('/checkout', '/pricing', '/plan', '/api/checkout/payment_methods', '/landing', '/payment-policy?lang=en'):
            self.assertNotEqual(app[path], web[path], path)
        self.assertEqual(app['/terms'], web['/terms'])    # trang không liên quan mua gói: y hệt

    @unittest.skipUnless(os.environ.get('STORE_APP_BASELINE'), 'đặt STORE_APP_BASELINE=<commit trước thay đổi> để so byte-for-byte')
    def test_browser_html_identical_to_baseline_templates(self):
        commit = os.environ['STORE_APP_BASELINE']

        def git_template(name):
            r = subprocess.run(['git', 'show', f'{commit}:templates/{name}'], cwd=ROOT, capture_output=True)
            return r.stdout.decode('utf-8') if r.returncode == 0 else None

        def templates():
            out = {(n, lang): _lenient(n, {'default_lang': lang}) for n in BIG_TEMPLATES for lang in ('en', 'vi')}
            oauth = dict(pend={'email': 'kim@lotus.test', 'name': 'Kim', 'provider': 'google'}, industry_en={},
                         industries={'nail': {'name': 'Nail'}})
            for lang in ('en', 'vi'):
                out[('oauth_complete.html', lang)] = render_tpl('oauth_complete.html', False, lang=lang, **oauth)
            for ind in ('', 'nail', 'fnb'):
                with FLASK.test_request_context('/', headers={'User-Agent': CHROME_DESKTOP}):
                    out[('components/pricing.html', ind)] = render_template_string(
                        "{% set pricing_industry = '" + ind + "' %}{% include 'components/pricing.html' %}")
            return out

        now_routes = browser_snapshot(CHROME_DESKTOP)
        now_big = templates()
        FLASK.jinja_loader = ChoiceLoader([FunctionLoader(git_template), _FS_LOADER])   # template của commit gốc
        FLASK.jinja_env.cache.clear()
        try:
            old_routes = browser_snapshot(CHROME_DESKTOP)
            old_big = templates()
        finally:
            FLASK.jinja_loader = _FS_LOADER
            FLASK.jinja_env.cache.clear()
        self.assertEqual(len(now_routes), len(old_routes))
        for (p, s, l, b), (p0, s0, l0, b0) in zip(now_routes, old_routes):
            self.assertEqual((p, s, l), (p0, s0, l0))
            self.assertEqual(b, b0, f'{p}: HTML trình duyệt khác bản {commit}')
        for n in now_big:
            self.assertEqual(now_big[n], old_big[n], n)


if __name__ == '__main__':
    unittest.main(verbosity=2)
