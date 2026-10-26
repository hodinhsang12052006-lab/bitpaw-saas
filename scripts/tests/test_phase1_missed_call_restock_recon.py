# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 1 "missed-call text-back, restock reasons, reconciliation":
  1) Cuộc gọi nhỡ (messaging_routes.py): câu <Say> + SMS theo NGÔN NGỮ tiệm (tiệm VN đọc giọng vi-VN), từ ngữ theo
     NGÀNH (không gọi mọi doanh nghiệp là "tiệm"), link đặt chỗ THẬT theo ngành (nail/spa đặt lịch, fnb /reserve,
     karaoke /karaoke/reserve, hotel /hotel/reserve; ngành khác chỉ "trả lời tin / gọi lại"), và KHÔNG nói "đã nhắn tin"
     khi không có tin nào được gửi.
  2) Đề xuất nhập hàng (app.py): lý do bằng ngôn ngữ tiệm, tiền theo tiền tệ tiệm; DeepSeek qua ai_deepseek_client
     (Desktop -> AI Proxy), ghi sổ token; AI lỗi / bịa số / sai ngôn ngữ / gói thấp -> câu mẫu (số thật). Đơn bán thật
     (order_items không có created_at) được đếm; dịch vụ (không có stock) bị bỏ qua.
  3) Đối soát thanh toán (app.py): ngưỡng lệch theo tiền tệ (1.000đ vs $1.00), câu báo theo ngôn ngữ tiệm.

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi DeepSeek/Twilio:
mongo_client được thay bằng DB giả trong RAM TRƯỚC mọi import; hàm của app.py lấy nguyên mã nguồn qua ast.

Chạy: python scripts/tests/test_phase1_missed_call_restock_recon.py
"""
import ast
import io
import os
import re
import sys
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from pymongo.errors import DuplicateKeyError  # noqa: E402


# ---------------------------------------------------------------- DB giả trong RAM
def _get(doc, key):
    cur = doc
    for part in key.split('.'):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


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
            if op in ('$gte', '$gt', '$lt', '$lte'):
                if v is None:
                    return False
                if op == '$gte' and not v >= arg or op == '$gt' and not v > arg or \
                        op == '$lt' and not v < arg or op == '$lte' and not v <= arg:
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


class _Cursor(list):
    def sort(self, key, direction=1):
        return _Cursor(sorted(self, key=lambda d: (d.get(key) is None, d.get(key) or ''), reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs = name, []

    def create_index(self, *a, **k):
        return 'ok'

    def insert_one(self, doc):
        d = dict(doc)
        if self.name == 'outbound_messages' and d.get('dedupe_key') and \
                any(x.get('dedupe_key') == d['dedupe_key'] for x in self.docs):
            raise DuplicateKeyError('dup dedupe_key')
        d.setdefault('_id', len(self.docs) + 1)
        self.docs.append(d)
        return types.SimpleNamespace(inserted_id=d['_id'])

    def find_one(self, flt=None, projection=None, sort=None):
        rows = self.find(flt)
        return dict(rows[0]) if rows else None

    def find(self, flt=None, projection=None):
        return _Cursor(dict(d) for d in self.docs if _matches(d, flt or {}))

    def count_documents(self, flt=None):
        return len(self.find(flt))

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                d.update(update.get('$set') or {})
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            d = {k: v for k, v in flt.items() if not str(k).startswith('$')}
            d.update(update.get('$set') or {})
            self.docs.append(d)
        return types.SimpleNamespace(matched_count=0, modified_count=0)

    def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                d.update(update.get('$set') or {})
                n += 1
        return types.SimpleNamespace(matched_count=n, modified_count=n)

    def delete_many(self, flt):
        self.docs = [d for d in self.docs if not _matches(d, flt)]


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
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED',
                                                    load_env_file=lambda *a, **k: None)
_vault = types.ModuleType('nurture_channel_tokens')
_vault.get_channel_token = lambda bid, ch: {'access_token': 'tok'} if ch == 'twilio' else None
_vault.save_channel_token = lambda *a, **k: None
sys.modules['nurture_channel_tokens'] = _vault
_be = types.ModuleType('booking_engine')
_be.book_appointment = MagicMock(side_effect=AssertionError('no booking in this test'))
_be.SlotAlreadyBookedError = type('SlotAlreadyBookedError', (Exception,), {})
sys.modules['booking_engine'] = _be
_ds = types.ModuleType('ai_deepseek_client')
_ds.deepseek_chat_completion = MagicMock(side_effect=AssertionError('DeepSeek must not be called here'))
sys.modules['ai_deepseek_client'] = _ds


def _identity_decorator(*a, **k):
    if len(a) == 1 and callable(a[0]) and not k:
        return a[0]
    return lambda f: f


_fake_app = types.ModuleType('app')
_fake_app._get_all_active_business_ids = lambda: []
_fake_app.login_required = _identity_decorator
_fake_app.role_required = _identity_decorator
sys.modules['app'] = _fake_app

import requests  # noqa: E402
from flask import Flask  # noqa: E402

import booking_rules  # noqa: E402
import messaging  # noqa: E402
import messaging_routes as MR  # noqa: E402
import plans  # noqa: E402
from currency_utils import format_money  # noqa: E402

VI_CHARS = re.compile(r'[ăâđêôơưàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]', re.I)
BASE = 'https://shop.example.test'


def _shop(bid, country, industry, name, currency=None, missed=True, sms=True, language=None, plan=None, shop_phone=''):
    DB.businesses.insert_one({'id': bid, 'name': name, 'country': country, 'industry_code': industry,
                              **({'currency': currency} if currency else {}), **({'plan': plan} if plan else {})})
    ms = {'business_id': bid, 'missed_call_enabled': missed, 'sms_enabled': sms, 'twilio_account_sid': 'ACxx',
          'twilio_from': '+15550001111', 'shop_phone': shop_phone}
    if language:
        ms['language'] = language
    DB.messaging_settings.insert_one(ms)


class _Base(unittest.TestCase):
    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()
        plans._PLAN_CACHE.clear()
        self._env = patch.dict(os.environ, {'PUBLIC_BASE_URL': BASE}, clear=False)
        self._env.start()
        for k in ('DEEPSEEK_API_KEY', 'BITPAW_DESKTOP_MODE', 'BITPAW_AI_PROXY_KEY'):
            os.environ.pop(k, None)
        self._net = patch.object(requests, 'post', side_effect=AssertionError('no network in tests'))
        self._net.start()

    def tearDown(self):
        self._net.stop()
        self._env.stop()


# ================================================================ 1. missed-call text-back
class MissedCallTests(_Base):
    def setUp(self):
        super().setUp()
        self.flask = Flask('t')
        self.flask.register_blueprint(MR.messaging_bp)
        self.client = self.flask.test_client()
        self._ver = patch.object(MR, '_verify_twilio', return_value=True)
        self._ver.start()
        self.pump = patch.object(messaging, 'pump', return_value={'sent': 1})
        self.pump_mock = self.pump.start()

    def tearDown(self):
        self.pump.stop()
        self._ver.stop()
        super().tearDown()

    def _call(self, bid, after=False, caller='+84901234567', status='no-answer'):
        url = f'/api/twilio/voice/{bid}' + ('/after' if after else '')
        data = {'From': caller, 'To': '+15550001111', 'CallSid': 'CAx'}
        if after:
            data['DialCallStatus'] = status
        r = self.client.post(url, data=data)
        self.assertEqual(r.status_code, 200)
        return r.get_data(as_text=True)

    def _sms(self, bid):
        return [m for m in DB.outbound_messages.docs if m['business_id'] == bid and m['kind'] == 'missed_call']

    def test_vn_restaurant_vietnamese_voice_sms_and_reserve_link(self):
        _shop('vn-fnb', 'VN', 'fnb', 'Quán Phở Hà')
        xml = self._call('vn-fnb')
        self.assertIn('<Say voice="Google.vi-VN-Standard-A" language="vi-VN">', xml)
        self.assertIn('Cảm ơn quý khách đã gọi Quán Phở Hà. Quán sẽ nhắn tin cho quý khách ngay.', xml)
        self.assertNotIn('Thanks for calling', xml)
        self.assertTrue(xml.rstrip().endswith('<Hangup/></Response>'))
        [m] = self._sms('vn-fnb')
        self.assertIn(f'Đặt bàn online: {BASE}/reserve/vn-fnb', m['body'])
        self.assertIn('quán sẽ liên hệ lại ngay', m['body'])
        self.assertNotIn('tiệm', m['body'] + xml)
        self.assertEqual(m['to'], '+84901234567')
        self.pump_mock.assert_called_once_with('vn-fnb', produce=False)

    def test_us_karaoke_after_no_answer_english_room_link(self):
        _shop('us-kara', 'US', 'karaoke', 'Star Karaoke', shop_phone='+15550002222')
        xml = self._call('us-kara')
        self.assertIn('<Dial timeout="20"', xml)
        self.assertEqual(self._sms('us-kara'), [])
        xml = self._call('us-kara', after=True, caller='+15551234567')
        self.assertIn('<Say>Sorry we missed you at Star Karaoke. We just sent you a text.</Say><Hangup/>', xml)
        [m] = self._sms('us-kara')
        self.assertIn(f'Book a room online: {BASE}/karaoke/reserve/us-kara', m['body'])
        self.assertIn('our karaoke team', m['body'])
        self.assertIsNone(VI_CHARS.search(m['body']))

    def test_au_hotel_stay_link_front_desk(self):
        _shop('au-hotel', 'AU', 'hotel', 'Harbour Inn')
        self._call('au-hotel', caller='+61400111222')
        [m] = self._sms('au-hotel')
        self.assertIn(f'Book your stay online: {BASE}/hotel/reserve/au-hotel', m['body'])
        self.assertIn('our front desk', m['body'])

    def test_nail_and_spa_keep_their_booking_pages(self):
        _shop('vn-nail', 'VN', 'nail', 'Lily Nails')
        _shop('us-spa', 'US', 'spa', 'Calm Spa')
        self._call('vn-nail')
        self._call('us-spa', caller='+15559876543')
        [n] = self._sms('vn-nail')
        [s] = self._sms('us-spa')
        self.assertIn(f'Đặt lịch online: {BASE}/booking/nail/qr/vn-nail', n['body'])
        self.assertIn('tiệm sẽ liên hệ lại', n['body'])          # "tiệm" đúng cho tiệm nail
        self.assertIn(f'Book online anytime: {BASE}/booking/qr/us-spa', s['body'])

    def test_industries_without_public_page_get_reply_or_call_only(self):
        _shop('vn-retail', 'VN', 'retail', 'Cửa hàng Minh An')
        _shop('us-prod', 'US', 'production', 'Acme Works')
        self._call('vn-retail')
        self._call('us-prod', caller='+15550009999')
        [r] = self._sms('vn-retail')
        [p] = self._sms('us-prod')
        self.assertNotIn('http', r['body'] + p['body'])
        self.assertIn('Quý khách trả lời tin này hoặc gọi lại sau, cửa hàng sẽ liên hệ lại ngay.', r['body'])
        self.assertNotIn('tiệm', r['body'])
        self.assertIn('Reply here or call us back, and our team will get back to you shortly.', p['body'])

    def test_no_text_claim_when_feature_off_or_twilio_not_ready(self):
        _shop('vn-off', 'VN', 'fnb', 'Quán Off', missed=False)
        _shop('us-nosms', 'US', 'retail', 'No SMS Store', sms=False, shop_phone='+15550003333')
        xml = self._call('vn-off')
        self.assertIn('Hiện chưa có ai nghe máy, quý khách vui lòng gọi lại sau.', xml)
        self.assertNotIn('nhắn tin', xml)
        xml = self._call('us-nosms', after=True, caller='+15551112222')
        self.assertIn('<Say>Sorry we missed you at No SMS Store. Please call again a little later.</Say>', xml)
        self.assertNotIn('text', xml.lower())
        self.assertEqual(DB.outbound_messages.docs, [])
        self.pump_mock.assert_not_called()

    def test_opted_out_caller_gets_no_text_and_no_claim(self):
        _shop('us-opt', 'US', 'nail', 'Opt Nails')
        messaging.opt_out('us-opt', 'sms', '+15557778888', source='STOP')
        xml = self._call('us-opt', caller='+15557778888')
        self.assertIn('Sorry, no one can take your call right now. Please call again later.', xml)
        self.assertEqual(self._sms('us-opt'), [])

    def test_repeat_call_within_30_min_one_text_and_still_honest(self):
        _shop('us-rep', 'US', 'fnb', 'Rep Diner')
        self._call('us-rep', caller='+15554443333')
        xml = self._call('us-rep', caller='+15554443333')
        self.assertIn('We will text you right away.', xml)       # đã nhắn số này trong 30 phút qua
        self.assertEqual(len(self._sms('us-rep')), 1)

    def test_unnamed_shop_and_language_override(self):
        _shop('vn-en', 'VN', 'hotel', 'owner@example.com', language='en')   # tên là email -> không đọc
        xml = self._call('vn-en')
        self.assertIn('<Say>Thanks for calling. We will text you right away.</Say>', xml)
        [m] = self._sms('vn-en')
        self.assertTrue(m['body'].startswith('Hi — sorry we missed your call!'))
        self.assertNotIn('@', m['body'])

    def test_answered_status_just_hangs_up(self):
        _shop('us-ok', 'US', 'nail', 'OK Nails', shop_phone='+15550004444')
        xml = self._call('us-ok', after=True, status='completed')
        self.assertEqual(xml.split('<Response>')[1], '<Hangup/></Response>')
        self.assertEqual(DB.outbound_messages.docs, [])

    def test_signature_still_required(self):
        self._ver.stop()
        try:
            _shop('us-sig', 'US', 'nail', 'Sig Nails')
            r = self.client.post('/api/twilio/voice/us-sig', data={'From': '+15550001234'},
                                 headers={'X-Twilio-Signature': 'bogus'})
            self.assertEqual(r.status_code, 403)
            self.assertEqual(DB.outbound_messages.docs, [])
        finally:
            self._ver.start()


# ================================================================ hàm của app.py (lấy mã nguồn qua ast)
with io.open(os.path.join(ROOT, 'app.py'), encoding='utf-8') as _fh:
    APP_SRC = _fh.read()
_TREE = ast.parse(APP_SRC)
_FUNCS = ('_shop_lang_currency', '_fmt_num', '_restock_reason_template', '_restock_ai_text_ok', '_log_restock_ai_usage',
          '_generate_restock_reason_with_ai', '_run_inventory_forecast_for_business', '_reconciliation_threshold',
          '_reconciliation_details', '_run_payment_reconciliation_for_business', '_log_ai_run')
_ASSIGNS = ('_VI_DIACRITIC_RE', '_RECON_MIN_MISMATCH', '_REVENUE_ORDER_FILTER')


def _load_app_funcs():
    nodes = []
    for n in _TREE.body:
        if isinstance(n, ast.FunctionDef) and n.name in _FUNCS:
            n.decorator_list = []
            nodes.append(n)
        elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in _ASSIGNS for t in n.targets):
            nodes.append(n)
    found = {getattr(n, 'name', None) or n.targets[0].id for n in nodes}
    missing = set(_FUNCS + _ASSIGNS) - found
    assert not missing, f'app.py is missing {missing}'
    ns = {'db': DB, 'next_mongo_id': lambda c: next(_ids), 'datetime': datetime, 'timedelta': timedelta, 'timezone': timezone,
          'time': time, 'os': os, 're': re, 'format_money': format_money, 'plans': plans,
          'deepseek_chat_completion': MagicMock(side_effect=AssertionError('DeepSeek must not be called here'))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns


NS = _load_app_funcs()


def _sales(bid, product_id, qty_per_day, days=14, status='completed', with_created_at=False):
    """Đơn bán thật như POS: order có created_at, order_items KHÔNG có created_at."""
    for d in range(days):
        oid = next(_ids)
        DB.orders.insert_one({'id': oid, 'business_id': bid, 'status': status, 'total_amount': 1,
                              'created_at': (datetime.now() - timedelta(days=d, hours=1)).isoformat()})
        item = {'id': next(_ids), 'order_id': oid, 'product_id': product_id, 'quantity': qty_per_day}
        if with_created_at:
            item['created_at'] = datetime.now().isoformat()
        DB.order_items.insert_one(item)


def _forecast(bid):
    return NS['_run_inventory_forecast_for_business'](bid, 14, (datetime.now() - timedelta(days=14)).isoformat())


def _ai_reply(text, tokens=(60, 25)):
    return {'choices': [{'message': {'content': text}}],
            'usage': {'prompt_tokens': tokens[0], 'completion_tokens': tokens[1], 'total_tokens': sum(tokens)}}


# ================================================================ 2. restock reasons
class RestockTests(_Base):
    def setUp(self):
        super().setUp()
        self.ds = MagicMock(side_effect=AssertionError('DeepSeek must not be called here'))
        NS['deepseek_chat_completion'] = self.ds

    def _us_retail(self, bid='us-retail', plan=None):
        _shop(bid, 'US', 'retail', 'Corner Store', currency='USD', plan=plan)
        DB.products.insert_one({'id': 1, 'business_id': bid, 'name': 'Cold Brew', 'stock': 2, 'cost_price': 3.5, 'is_active': 1})
        _sales(bid, 1, 1)                                 # 14 bán / 14 ngày -> 1/ngày, còn 2 -> 2 ngày

    def test_us_retail_reason_english_and_usd(self):
        self._us_retail()
        self.assertEqual(_forecast('us-retail'), 1)
        [p] = DB.restock_proposals.docs
        self.assertEqual((p['lang'], p['currency'], p['reason_source']), ('en', 'USD', 'template'))
        self.assertEqual(p['suggested_qty'], 5)
        self.assertEqual(p['est_cost'], 17.5)
        self.assertEqual(p['reason'], "'Cold Brew': 2 left, selling about 1/day over the last 14 days — runs out in about 2 days. "
                                      "Suggest ordering 5 (about $17.50 at cost).")
        self.assertIsNone(VI_CHARS.search(p['reason']))
        self.ds.assert_not_called()                       # không có khoá API -> không gọi AI

    def test_vn_shop_reason_vietnamese_and_vnd(self):
        _shop('vn-shop', 'VN', 'retail', 'Tạp hoá Lan')
        DB.products.insert_one({'id': 2, 'business_id': 'vn-shop', 'name': 'Sữa tươi', 'stock': 3, 'cost_price': 25000, 'is_active': True})
        _sales('vn-shop', 2, 1.5)                         # 21 / 14 = 1,5/ngày -> 2 ngày
        self.assertEqual(_forecast('vn-shop'), 1)
        [p] = DB.restock_proposals.docs
        self.assertEqual((p['lang'], p['currency']), ('vi', 'VND'))
        self.assertIn("'Sữa tươi' còn 3, bán trung bình 1,5/ngày trong 14 ngày qua — dự kiến hết sau khoảng 2 ngày.", p['reason'])
        self.assertIn('Đề xuất nhập 7 (khoảng 175.000đ theo giá vốn).', p['reason'])

    def test_real_pos_sales_counted_services_and_failed_orders_ignored(self):
        _shop('us-mix', 'US', 'nail', 'Mix Nails', currency='USD')
        DB.products.insert_one({'id': 10, 'business_id': 'us-mix', 'name': 'Gel manicure', 'is_active': 1, 'price': 30})  # dịch vụ
        DB.products.insert_one({'id': 11, 'business_id': 'us-mix', 'name': 'Cuticle oil', 'stock': 1, 'is_active': 1})
        DB.products.insert_one({'id': 12, 'business_id': 'us-mix', 'name': 'Top coat', 'stock': 1, 'is_active': 1})
        _sales('us-mix', 10, 3)
        _sales('us-mix', 11, 1)                           # order_items không có created_at -> vẫn được đếm
        _sales('us-mix', 12, 5, status='failed')          # đơn thất bại -> không tính
        self.assertEqual(_forecast('us-mix'), 1)
        self.assertEqual([p['product_name'] for p in DB.restock_proposals.docs], ['Cuticle oil'])
        self.assertEqual(_forecast('us-mix'), 0)          # đề xuất đang chờ -> không tạo trùng

    def test_out_of_stock_wording(self):
        _shop('au-out', 'AU', 'retail', 'Out Store')
        DB.products.insert_one({'id': 20, 'business_id': 'au-out', 'name': 'Chips', 'stock': 0, 'is_active': 1})
        _sales('au-out', 20, 2)
        _forecast('au-out')
        [p] = DB.restock_proposals.docs
        self.assertEqual(p['currency'], 'AUD')
        self.assertIn('already out of stock', p['reason'])
        self.assertIsNone(p['est_cost'])

    def test_ai_path_uses_client_logs_tokens_and_keeps_numbers(self):
        os.environ['DEEPSEEK_API_KEY'] = 'sk-test'
        self.ds.side_effect = None
        self.ds.return_value = _ai_reply('Cold Brew is down to 2 and sells about 1 a day — order 5 now (about $17.50).')
        self._us_retail()
        _forecast('us-retail')
        [p] = DB.restock_proposals.docs
        self.assertEqual(p['reason_source'], 'ai')
        self.assertEqual(p['reason'], 'Cold Brew is down to 2 and sells about 1 a day — order 5 now (about $17.50).')
        args, kwargs = self.ds.call_args
        self.assertEqual(kwargs['business_id'], 'us-retail')
        self.assertEqual(kwargs['direct_api_key'], 'sk-test')
        self.assertIsNone(kwargs['proxy_api_key'])
        prompt = args[0]['messages']
        self.assertIn('in English', prompt[0]['content'])
        self.assertIn('Estimated cost at cost price: $17.50', prompt[1]['content'])
        [u] = DB.ai_usage.docs
        self.assertEqual((u['feature'], u['kind'], u['units'], u['prompt_tokens'], u['completion_tokens']),
                         ('restock_reason', 'text', 85, 60, 25))
        [run] = DB.ai_runs.docs
        self.assertEqual((run['persona'], run['fallback']), ('restock_reason', False))

    def test_ai_invented_number_or_wrong_language_falls_back(self):
        os.environ['DEEPSEEK_API_KEY'] = 'sk-test'
        self.ds.side_effect = None
        for bad in ('Cold Brew sells 40 a week, order 5 now.', 'Cold Brew còn 2, hãy nhập thêm 5 nhé.', ''):
            DB.reset()
            plans._PLAN_CACHE.clear()
            self.ds.return_value = _ai_reply(bad)
            self._us_retail()
            _forecast('us-retail')
            [p] = DB.restock_proposals.docs
            self.assertEqual(p['reason_source'], 'template', bad)
            self.assertTrue(p['reason'].startswith("'Cold Brew': 2 left"), bad)
            self.assertEqual(len(DB.ai_usage.docs), 1)      # token đã tốn vẫn vào sổ
            self.assertTrue(DB.ai_runs.docs[0]['fallback'])

    def test_ai_error_falls_back(self):
        os.environ['DEEPSEEK_API_KEY'] = 'sk-test'
        self.ds.side_effect = RuntimeError('timeout')
        self._us_retail()
        _forecast('us-retail')
        [p] = DB.restock_proposals.docs
        self.assertEqual(p['reason_source'], 'template')
        self.assertIn('timeout', DB.ai_runs.docs[0]['error'])

    def test_desktop_mode_goes_through_proxy(self):
        os.environ.update({'BITPAW_DESKTOP_MODE': '1', 'BITPAW_AI_PROXY_KEY': 'proxy-key', 'DEEPSEEK_API_KEY': 'sk-should-not-be-used'})
        self.ds.side_effect = None
        self.ds.return_value = _ai_reply('Cold Brew: 2 left, about 1 sold a day, order 5 soon.')
        self._us_retail()
        _forecast('us-retail')
        kwargs = self.ds.call_args.kwargs
        self.assertEqual(kwargs['proxy_api_key'], 'proxy-key')
        self.assertIsNone(kwargs['direct_api_key'])

    def test_plan_without_stock_alerts_gets_no_paid_ai(self):
        os.environ['DEEPSEEK_API_KEY'] = 'sk-test'
        self._us_retail(plan='essential')
        _forecast('us-retail')
        self.ds.assert_not_called()
        self.assertEqual(DB.restock_proposals.docs[0]['reason_source'], 'template')

    def test_no_direct_deepseek_http_in_restock_code(self):
        fn = next(n for n in _TREE.body if isinstance(n, ast.FunctionDef) and n.name == '_generate_restock_reason_with_ai')
        src = ast.get_source_segment(APP_SRC, fn)
        self.assertNotIn('api.deepseek.com', src)
        self.assertNotIn('requests.post', src)
        self.assertIn('deepseek_chat_completion(', src)

    def test_fmt_num(self):
        f = NS['_fmt_num']
        self.assertEqual((f(1234.5, 'en'), f(1234.5, 'vi'), f(2.0, 'vi'), f(7, 'en', 0)), ('1,234.5', '1.234,5', '2', '7'))


# ================================================================ 3. payment reconciliation
class ReconciliationTests(_Base):
    def _pair(self, bid, txn_id, amount, order_total, status='completed', created=None):
        when = (created or datetime.now() - timedelta(hours=1)).isoformat()
        DB.payment_transactions.insert_one({'business_id': bid, 'transaction_id': txn_id, 'amount': amount, 'status': status,
                                            'created_at': when})
        if order_total is not None:
            DB.orders.insert_one({'id': next(_ids), 'business_id': bid, 'total_amount': order_total, 'created_at': when,
                                  'metadata': {'order_code': txn_id}})

    def _run(self, bid):
        return NS['_run_payment_reconciliation_for_business'](bid, 14)

    def test_usd_threshold_is_one_dollar_and_text_english(self):
        _shop('us-rec', 'US', 'fnb', 'Diner', currency='USD')
        self._pair('us-rec', 'TX1', 20.0, 21.5)          # lệch $1.50 -> báo (trước đây cần lệch 1.000 mới báo)
        self._pair('us-rec', 'TX2', 20.0, 20.4)          # lệch $0.40 -> không báo
        self.assertEqual(self._run('us-rec'), 1)
        [a] = DB.reconciliation_alerts.docs
        self.assertEqual((a['transaction_id'], a['issue_type'], a['currency']), ('TX1', 'amount_mismatch', 'USD'))
        self.assertEqual(a['details'], 'Payment TX1: $20.00 was recorded, but the order total is $21.50 ($1.50 short).')

    def test_vnd_threshold_is_1000_and_text_vietnamese(self):
        _shop('vn-rec', 'VN', 'fnb', 'Quán')
        self._pair('vn-rec', 'GD1', 100000, 100500)       # lệch 500đ -> không báo
        self._pair('vn-rec', 'GD2', 100000, 95000)        # thu thừa 5.000đ
        self.assertEqual(self._run('vn-rec'), 1)
        [a] = DB.reconciliation_alerts.docs
        self.assertEqual(a['details'], 'Giao dịch GD2: số tiền ghi nhận 100.000đ nhưng đơn hàng thực tế 95.000đ (thu thừa 5.000đ).')

    def test_missing_order_and_stale_pending_in_shop_language(self):
        _shop('au-rec', 'AU', 'retail', 'AU Store')
        self._pair('au-rec', 'SQ,9', 50, None)                       # dấu phẩy trong mã giữ nguyên
        self._pair('au-rec', 'SQ10', 30, None, status='pending', created=datetime.now() - timedelta(hours=3, minutes=30))
        self.assertEqual(self._run('au-rec'), 2)
        by = {a['issue_type']: a for a in DB.reconciliation_alerts.docs}
        self.assertEqual(by['missing_order']['details'], 'Payment SQ,9 is marked completed, but no matching order was found.')
        self.assertEqual(by['stale_pending']['details'], 'Payment SQ10 is still pending after 3.5 hours — the money may not have arrived.')
        self.assertEqual(self._run('au-rec'), 0)                     # không báo trùng

    def test_language_setting_overrides_country(self):
        _shop('vn-en-rec', 'VN', 'fnb', 'Quán', language='en')
        self._pair('vn-en-rec', 'GD9', 100000, 120000)
        self._run('vn-en-rec')
        [a] = DB.reconciliation_alerts.docs
        self.assertEqual(a['details'], 'Payment GD9: 100.000đ was recorded, but the order total is 120.000đ (20.000đ short).')

    def test_us_shop_without_currency_field_is_not_vnd(self):
        _shop('us-nocur', 'US', 'retail', 'No Currency Store')
        self.assertEqual(NS['_shop_lang_currency']('us-nocur'), ('en', 'USD'))
        self.assertEqual(NS['_shop_lang_currency']('legacy-no-row'), ('vi', 'VND'))
        self.assertEqual(NS['_reconciliation_threshold']('USD'), 1.0)
        self.assertEqual(NS['_reconciliation_threshold']('VND'), 1000.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
