# -*- coding: utf-8 -*-
"""Test OFFLINE cho đợt sửa "honesty-fixes" (Ad Assistant tiền/an toàn, kịch bản CRM, xem trước tin AI, route giả đã gỡ).

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối thẳng PRODUCTION), KHÔNG gọi Meta/DeepSeek thật:
- mọi module ngoài được thay bằng stub TRƯỚC khi import module cần test;
- các route trong app.py được lấy nguyên mã nguồn qua ast rồi chạy trong namespace có stub (bỏ decorator);
- route dùng SQLite 'database.db' chạy trong thư mục tạm (không đụng database.db của repo).

Chạy: python scripts/tests/test_honesty_fixes.py
"""
import ast
import io
import os
import re
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from functools import wraps
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------- stub TRƯỚC mọi import của module thật
_db = MagicMock(name='db')
sys.modules['mongo_client'] = types.SimpleNamespace(db=_db, next_mongo_id=lambda c: 1, MONGO_STATUS='CONNECTED')
_tokens = types.ModuleType('ad_platform_tokens')
_tokens.get_facebook_token = MagicMock()
_tokens.save_facebook_token = MagicMock()
_tokens.mark_facebook_token_invalid = MagicMock()
sys.modules['ad_platform_tokens'] = _tokens
_ds = types.ModuleType('ai_deepseek_client')
_ds.deepseek_chat_completion = MagicMock(side_effect=AssertionError('DeepSeek không được gọi trong test'))
sys.modules['ai_deepseek_client'] = _ds

from flask import Flask, jsonify, request, session  # noqa: E402

_REGION = {'country': 'VN', 'currency': 'VND'}


def _login_required(f):
    @wraps(f)
    def inner(*a, **k):
        if 'user_id' not in session:
            return jsonify({'success': False}), 401
        return f(*a, **k)
    return inner


def _role_required(*roles):
    def deco(f):
        @wraps(f)
        def inner(*a, **k):
            if session.get('role', 'staff') not in roles:
                return jsonify({'success': False, 'message': 'forbidden'}), 403
            return f(*a, **k)
        return inner
    return deco


class _Limiter:
    def limit(self, *_a, **_k):
        return lambda f: f


class _TenantEngine:
    @staticmethod
    def get_region_config(business_id=None):
        return dict(_REGION)


_app_stub = types.ModuleType('app')
_app_stub.login_required = _login_required
_app_stub.role_required = _role_required
_app_stub.limiter = _Limiter()
_app_stub.TenantEngine = _TenantEngine
sys.modules['app'] = _app_stub

import facebook_ads_client as fb  # noqa: E402  (chỉ dùng requests -> đã patch trong từng test)
import ad_assistant  # noqa: E402


def _resp(status, body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = str(body)
    return r


# ================================================================ facebook_ads_client
class FacebookClientTests(unittest.TestCase):
    def test_minor_units_respect_zero_decimal_currencies(self):
        self.assertEqual(fb.to_minor_units(100000, 'VND'), 100000)   # VND không có đơn vị lẻ (trước: x100)
        self.assertEqual(fb.to_minor_units(1500, 'JPY'), 1500)
        self.assertEqual(fb.to_minor_units(12.5, 'USD'), 1250)
        self.assertEqual(fb.to_minor_units(10, 'aud'), 1000)

    def test_normalize_ad_account_id(self):
        self.assertEqual(fb.normalize_ad_account_id('123456'), 'act_123456')
        self.assertEqual(fb.normalize_ad_account_id(' act_99 '), 'act_99')

    def test_ad_set_requires_country_no_hidden_AU_default(self):
        with patch.object(fb.requests, 'post') as post:
            with self.assertRaises(ValueError):
                fb.create_ad_set('tok', 'act_1', 'c1', 'n', 1000, None)
            post.assert_not_called()

    def test_launch_sends_targeting_end_time_and_budget(self):
        calls = []

        def fake_post(url, params=None, timeout=None, **_):
            calls.append((url, dict(params or {})))
            return _resp(200, {'id': f'id{len(calls)}'})

        tg = {'geo_locations': {'countries': ['US']}, 'age_min': 21, 'age_max': 45}
        with patch.object(fb.requests, 'post', side_effect=fake_post):
            out = fb.launch_campaign('tok', 'act_1', 'page1', 'Camp', 'OUTCOME_TRAFFIC', 1000, 'msg', 'https://x.test',
                                     targeting=tg, end_time='2026-11-01T00:00:00+0000')
        adset = [p for u, p in calls if u.endswith('/adsets')][0]
        self.assertEqual(adset['daily_budget'], 1000)
        self.assertIn('"US"', adset['targeting'])
        self.assertEqual(adset['end_time'], '2026-11-01T00:00:00+0000')
        self.assertEqual(adset['status'], 'PAUSED')
        self.assertEqual(out['campaign_id'], 'id1')

    def test_launch_without_targeting_creates_nothing(self):
        with patch.object(fb.requests, 'post') as post:
            with self.assertRaises(ValueError):
                fb.launch_campaign('tok', 'act_1', 'p', 'n', 'OUTCOME_TRAFFIC', 1000, 'm', 'https://x.test')
            post.assert_not_called()

    def test_base_url_env_overridable(self):
        self.assertTrue(fb.GRAPH_BASE.endswith('/' + fb.GRAPH_API_VERSION))


# ================================================================ ad_assistant routes
class AdAssistantRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'test'
        self.app.register_blueprint(ad_assistant.ad_assistant_bp)
        self.client = self.app.test_client()
        _tokens.get_facebook_token.reset_mock()
        _tokens.save_facebook_token.reset_mock()
        _tokens.mark_facebook_token_invalid.reset_mock()
        _tokens.get_facebook_token.return_value = {'access_token': 'tok', 'ad_account_id': 'act_1', 'page_id': 'p1', 'status': 'active'}
        _db.generated_media.count_documents.return_value = 1
        _REGION.update({'country': 'VN', 'currency': 'VND'})

    def login(self, role='admin'):
        with self.client.session_transaction() as s:
            s['user_id'] = 7
            s['business_id'] = 7
            s['role'] = role

    def create(self, **body):
        payload = {'platform': 'facebook', 'name': 'Test', 'link': 'https://shop.test', 'message': 'Hello',
                   'target_audience': {'age_min': 25, 'age_max': 40}}
        payload.update(body)
        return self.client.post('/ad-assistant/api/create-campaign', json=payload)

    def test_staff_cannot_create_or_connect(self):
        self.login('staff')
        with patch.object(fb, 'launch_campaign') as launch:
            self.assertEqual(self.create(budget=100).status_code, 403)
            launch.assert_not_called()
        r = self.client.post('/ad-assistant/api/connect-facebook', json={'access_token': 't', 'ad_account_id': '1'})
        self.assertEqual(r.status_code, 403)
        _tokens.save_facebook_token.assert_not_called()

    def test_blank_budget_is_rejected_not_defaulted(self):
        self.login()
        with patch.object(fb, 'get_ad_account') as acct, patch.object(fb, 'launch_campaign') as launch:
            for b in ('', None, 0, -5, 'abc', 'nan'):
                r = self.create(budget=b)
                self.assertEqual(r.status_code, 400, b)
                self.assertEqual(r.get_json()['code'], 'budget_required')
            launch.assert_not_called()
            acct.assert_not_called()

    def test_vnd_total_budget_split_per_day_without_x100(self):
        self.login()
        with patch.object(fb, 'get_ad_account', return_value={'currency': 'VND'}), \
                patch.object(fb, 'launch_campaign', return_value={'campaign_id': 'c', 'ad_set_id': 'a', 'creative_id': 'cr', 'ad_id': 'ad'}) as launch:
            r = self.create(budget=700000)
        self.assertEqual(r.status_code, 200, r.get_json())
        kw = launch.call_args.kwargs
        self.assertEqual(kw['daily_budget_minor'], 100000)          # 700.000đ / 7 ngày, KHÔNG x100
        self.assertEqual(kw['targeting']['geo_locations']['countries'], ['VN'])
        self.assertEqual((kw['targeting']['age_min'], kw['targeting']['age_max']), (25, 40))
        end = datetime.strptime(kw['end_time'], '%Y-%m-%dT%H:%M:%S+0000').replace(tzinfo=timezone.utc)
        self.assertAlmostEqual((end - datetime.now(timezone.utc)).total_seconds(), 7 * 86400, delta=120)
        body = r.get_json()
        self.assertEqual(body['facebook_status'], 'PAUSED')
        self.assertEqual(body['currency'], 'VND')

    def test_usd_shop_targets_own_country_in_cents(self):
        self.login()
        _REGION.update({'country': 'US', 'currency': 'USD'})
        with patch.object(fb, 'get_ad_account', return_value={'currency': 'USD'}), \
                patch.object(fb, 'launch_campaign', return_value={'campaign_id': 'c', 'ad_set_id': 'a', 'creative_id': 'cr', 'ad_id': 'ad'}) as launch:
            r = self.create(budget=70)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(launch.call_args.kwargs['daily_budget_minor'], 1000)   # $10/ngày = 1000 cent
        self.assertEqual(launch.call_args.kwargs['targeting']['geo_locations']['countries'], ['US'])

    def test_currency_mismatch_creates_nothing(self):
        self.login()
        with patch.object(fb, 'get_ad_account', return_value={'currency': 'USD'}), patch.object(fb, 'launch_campaign') as launch:
            r = self.create(budget=700000)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['code'], 'currency_mismatch')
        self.assertEqual(r.get_json()['account_currency'], 'USD')
        launch.assert_not_called()
        # Nhập lại đúng tiền của tài khoản -> tạo được
        with patch.object(fb, 'get_ad_account', return_value={'currency': 'USD'}), \
                patch.object(fb, 'launch_campaign', return_value={'campaign_id': 'c', 'ad_set_id': 'a', 'creative_id': 'cr', 'ad_id': 'ad'}) as launch:
            r = self.create(budget=70, currency='USD')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(launch.call_args.kwargs['daily_budget_minor'], 1000)

    def test_link_and_objective_validated(self):
        self.login()
        with patch.object(fb, 'launch_campaign') as launch:
            self.assertEqual(self.create(budget=10, link='javascript:alert(1)').get_json()['code'], 'link_required')
            self.assertEqual(self.create(budget=10, objective='HACK').get_json()['code'], 'invalid_objective')
            launch.assert_not_called()

    def test_connect_verifies_token_before_saving(self):
        self.login()
        with patch.object(fb, 'verify_token', side_effect=fb.FacebookTokenExpiredError('bad')):
            r = self.client.post('/ad-assistant/api/connect-facebook', json={'access_token': 't', 'ad_account_id': '123'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['code'], 'token_invalid')
        _tokens.save_facebook_token.assert_not_called()

        with patch.object(fb, 'verify_token', return_value={'id': '1', 'name': 'Owner'}), \
                patch.object(fb, 'get_ad_account', return_value={'name': 'Shop ads', 'currency': 'VND'}):
            r = self.client.post('/ad-assistant/api/connect-facebook', json={'access_token': 't', 'ad_account_id': '123', 'page_id': 'p'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['account_currency'], 'VND')
        _tokens.save_facebook_token.assert_called_once_with(7, 't', 'act_123', 'p')

    def test_suggest_has_no_hidden_budget_default(self):
        self.login()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': ''}):
            r = self.client.post('/ad-assistant/api/suggest', json={'product_name': 'Gel nails'})
        s = r.get_json()['suggestions']
        self.assertTrue(s['fallback'])
        self.assertIsNone(s['budget_recommendation'])


# ================================================================ app.py routes (lấy mã nguồn qua ast, không import app.py)
APP_SRC = io.open(os.path.join(ROOT, 'app.py'), encoding='utf-8').read()
_APP_TREE = ast.parse(APP_SRC)


def _load_route(name, ns):
    node = next(n for n in ast.walk(_APP_TREE) if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    mod = ast.Module(body=[node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(mod), f'app.py::{name}', 'exec'), ns)
    return ns[name]


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        self.flask = Flask(__name__)
        self.flask.secret_key = 'test'
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)   # route dùng sqlite3.connect('database.db') tương đối -> chỉ đụng file tạm
        conn = sqlite3.connect('database.db')
        conn.execute("CREATE TABLE bot_scenarios (id TEXT PRIMARY KEY, business_id TEXT, name TEXT, description TEXT, channel TEXT,"
                     " trigger_type TEXT, message_template TEXT, delay_minutes INTEGER DEFAULT 0, status TEXT DEFAULT 'ACTIVE',"
                     " max_send_per_day INTEGER DEFAULT 100, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE bot_message_logs (id TEXT PRIMARY KEY, business_id TEXT, scenario_id TEXT, customer_id TEXT, channel TEXT,"
                     " message_content TEXT, status TEXT, error_message TEXT, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_at TIMESTAMP)")
        conn.commit()
        conn.close()
        self.db = MagicMock(name='db')
        self.ns = {
            'jsonify': jsonify, 'request': request, 'session': session, 'datetime': datetime, 're': re, 'os': os,
            'sqlite3': sqlite3, 'db': self.db, 'uuid': __import__('uuid'), 'json': __import__('json'),
            '_get_tenant_business_id_or_401': lambda: (7, None),
            '_vi_en': lambda vi, en: en,
            'next_mongo_id': MagicMock(side_effect=AssertionError('preview must not allocate ids')),
        }

    def tearDown(self):
        os.chdir(self.cwd)

    def test_scenarios_list_no_longer_auto_seeds(self):
        fn = _load_route('get_bot_scenarios', self.ns)
        with self.flask.test_request_context('/api/bot/scenarios'):
            body = fn().get_json()
        self.assertEqual(body['data'], [])
        conn = sqlite3.connect('database.db')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM bot_scenarios').fetchone()[0], 0)
        conn.close()

    def test_scenario_test_is_preview_with_real_data_and_sends_nothing(self):
        conn = sqlite3.connect('database.db')
        conn.execute("INSERT INTO bot_scenarios (id, business_id, name, channel, trigger_type, message_template) VALUES "
                     "('s1', '7', 'Reminder', 'zalo_oa', 'booking', 'Hi {customer_name}, {service_name} at {appointment_time}. Ref {order_code}')")
        conn.commit()
        conn.close()
        self.db.customers.find_one.return_value = {'id': 5, 'name': 'Lan Tran', 'phone': '+61400000000'}
        self.db.appointments.find_one.return_value = {'book_time': '2026-11-02T15:30', 'service_id': 9}
        self.db.products.find_one.return_value = {'name': 'Gel manicure'}
        self.db.orders.find_one.return_value = None    # khách chưa có đơn -> biến giữ nguyên, báo thiếu
        fn = _load_route('test_bot_scenario', self.ns)
        with self.flask.test_request_context('/x', method='POST', json={'customer_id': '5'}):
            body = fn('s1').get_json()
        self.assertTrue(body['success'])
        self.assertFalse(body['sent'])
        self.assertEqual(body['preview'], 'Hi Lan Tran, Gel manicure at 2026-11-02 15:30. Ref {order_code}')
        self.assertEqual(body['missing_vars'], ['order_code'])
        self.assertNotIn('OK 200', body['message'])
        for fake in ('Hắc Ín', 'BP-MOCK', '15:30 Ngày mai'):
            self.assertNotIn(fake, body['preview'])
        conn = sqlite3.connect('database.db')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM bot_message_logs').fetchone()[0], 0)
        conn.close()

    def test_omnichannel_legacy_test_is_honest(self):
        fn = _load_route('omnichannel_test_api', self.ns)
        with self.flask.test_request_context('/omnichannel/test/zalo', method='POST'):
            resp, status = fn('zalo')
        self.assertEqual(status, 410)
        self.assertFalse(resp.get_json()['success'])
        self.assertEqual(resp.get_json()['redirect'], '/inbox/channels')

    def test_nurture_preview_creates_no_campaign(self):
        msgs = types.ModuleType('messaging')
        msgs.get_settings = lambda bid: {'language': 'en'}
        msgs.normalize_channel = lambda v, default=None: (str(v).strip().lower() or default) if v else default
        ane = types.ModuleType('ai_nurturing_engine')
        ane.customer_fill_values = lambda *a: ('Lan', '', None)
        ace = types.ModuleType('ai_context_engine')
        ace.AIContextEngine = types.SimpleNamespace(_load_purchase_history=lambda *a, **k: [{'products': {'name': 'Gel'}}])
        engine = MagicMock()
        engine.generate_single_nurture_message.return_value = 'Hi Lan, time for a refill?'
        engine._fallback_copy.return_value = {'7days': 'generic'}
        self.ns.update({'AINurturingEngine': engine})
        self.db.customers.find_one.return_value = {'id': 5, 'name': 'Lan Tran', 'phone': '+61400000000'}
        self.db.businesses.find_one.return_value = {'name': 'Lan Nails'}
        fn = _load_route('nurture_generate_campaign', self.ns)
        with patch.dict(sys.modules, {'messaging': msgs, 'ai_nurturing_engine': ane, 'ai_context_engine': ace}), \
                patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'x'}):
            with self.flask.test_request_context('/x', method='POST', json={'preview_customer_id': '5', 'goal': 'RECALL'}):
                session['user_id'] = 7
                session['business_id'] = 7
                body = fn().get_json()
        self.assertTrue(body['preview'])
        self.assertFalse(body['saved'])
        self.assertEqual(body['message'], 'Hi Lan, time for a refill?')
        self.assertTrue(body['ai_generated'])
        self.assertTrue(body['used_purchase_history'])
        self.db.nurturing_campaigns.insert_one.assert_not_called()
        self.db.campaign_messages.insert_many.assert_not_called()
        q = self.db.customers.find_one.call_args.args[0]
        self.assertEqual(q['business_id'], 7)                 # chỉ khách của đúng tiệm
        self.assertEqual(q['id'], {'$in': ['5', 5]})


# ================================================================ dấu vết đồ giả đã gỡ khỏi template / app.py
class StaticHonestyTests(unittest.TestCase):
    def read(self, rel):
        return io.open(os.path.join(ROOT, rel), encoding='utf-8').read()

    def test_fake_endpoint_removed(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'ad_suggest_api.py')))
        self.assertNotIn('from ad_suggest_api import', APP_SRC)
        self.assertNotIn('wow the admin', APP_SRC)
        self.assertNotIn('Phản hồi từ Máy chủ đối tác: OK (200)', APP_SRC)

    def test_templates_have_no_fabrications(self):
        bad = {
            'templates/ad_assistant.html': ['BitPaw Ads', '@bitpaw_ads', 'parseMessage', 'setTimeout(() => {\n                if (chatMessages',
                                            '15 phút', '15 minutes', '|| 1000000', '1 giờ trước'],
            'templates/campaign_builder.html': ['predOpen', 'predCTR', 'predROI', 'charCodeAt'],
            'templates/customer_nurturing.html': ['mock_text', 'churnProb', 'giảm giá 35%', 'giảm ngay 30%', 'momentOffsetDate', '5000000', 'segment: "ALL"'],
            'templates/crm_automation.html': ['Hồ Đình Sang', 'BP-LUCKY', 'Làm Móng Nhung VIP'],
        }
        for rel, needles in bad.items():
            src = self.read(rel)
            for n in needles:
                self.assertNotIn(n, src, f'{rel}: {n!r}')

    def test_templates_parse(self):
        import jinja2
        env = jinja2.Environment()
        for rel in ('templates/ad_assistant.html', 'templates/campaign_builder.html',
                    'templates/customer_nurturing.html', 'templates/crm_automation.html'):
            env.parse(self.read(rel))

    def test_ad_assistant_renders_shop_name(self):
        import jinja2
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(ROOT, 'templates')))
        env.globals.update(url_for=lambda *a, **k: '/static/x', shop_header_name=lambda: 'Lan <Nails>')
        html = env.get_template('ad_assistant.html').render(tenant_currency='USD', tenant_country='US', default_lang='en')
        self.assertIn('const SHOP_NAME = "Lan \\u003cNails\\u003e";', html)
        self.assertIn('const SHOP_COUNTRY = "US";', html)


if __name__ == '__main__':
    unittest.main(verbosity=2)
