# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 1 "customer messaging delivery":
  1) xin đánh giá đọc SĐT/tên/email trong order.metadata (nơi mọi đơn lưu) -> thật sự xếp + gửi; tôn trọng STOP, khung giờ,
     mỗi khách 1 lần / N ngày; đơn vãng lai không chiếm suất; không lọc theo số sao;
  2) tin chăm sóc Zalo/Messenger: 1 bộ kênh chữ thường, gửi qua inbox_channels.send_text bằng kênh CHÍNH tiệm (không token
     chung), chỉ trong khung trả lời của nền tảng (Messenger 24 giờ, Zalo 48 giờ) — ngoài khung -> SMS/email hoặc bỏ qua có
     lý do; chạy trong messaging.pump; worker cũ chỉ còn là lớp mỏng, không ghi đè dòng SMS/EMAIL;
  3) API luật tự động nhận sms/email/zalo/messenger (zalo_oa -> zalo);
  4) sinh nhật + tích điểm qua kênh của tiệm hoặc SMS/email, đúng giờ + ngôn ngữ tiệm, không dùng ZALO_OA_ACCESS_TOKEN /
     FB_PAGE_ACCESS_TOKEN của máy chủ, không hứa ưu đãi tự bịa;
  5) hạng chi tiêu theo phân vị chi tiêu của CHÍNH tiệm (USD/AUD/VND như nhau), ghi chú theo ngôn ngữ tiệm.

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi Twilio/Zalo/Meta/DeepSeek/Gmail:
mongo_client, requests, email_service, nurture_channel_tokens, ai_deepseek_client, ai_context_engine được thay TRƯỚC mọi
import; hàm của app.py lấy nguyên mã nguồn qua ast.

Chạy: python scripts/tests/test_phase1_messaging_delivery.py
"""
import ast
import io
import os
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
os.environ.pop('DEEPSEEK_API_KEY', None)
# Token CHUNG của máy chủ — code mới KHÔNG được dùng tới (tin phải đi từ OA/Page của chính tiệm)
os.environ['ZALO_OA_ACCESS_TOKEN'] = 'GLOBAL-SERVER-ZALO-TOKEN'
os.environ['FB_PAGE_ACCESS_TOKEN'] = 'GLOBAL-SERVER-FB-TOKEN'


# ---------------------------------------------------------------- DB giả trong RAM
class DuplicateKeyError(Exception):
    pass


def _get(doc, key):
    cur = doc
    for part in str(key).split('.'):
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
                try:
                    if op == '$gte' and not v >= arg or op == '$gt' and not v > arg or \
                            op == '$lt' and not v < arg or op == '$lte' and not v <= arg:
                        return False
                except TypeError:
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
        elif not _match_value(_get(doc, k), cond):
            return False
    return True


class _Cursor(list):
    def sort(self, key, direction=1):
        if isinstance(key, list):
            key, direction = key[0]
        rows = sorted(self, key=lambda d: (_get(d, key) is None, str(_get(d, key) or '')), reverse=direction == -1)
        return _Cursor(rows)

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs, self._n = name, [], count(1)

    def create_index(self, *a, **k):
        return None

    def insert_one(self, doc, session=None):
        if self.name == 'outbound_messages' and doc.get('dedupe_key') and \
                any(d.get('dedupe_key') == doc['dedupe_key'] for d in self.docs):
            raise DuplicateKeyError(doc['dedupe_key'])
        d = dict(doc)
        d.setdefault('_id', f"{self.name}-{next(self._n)}")
        doc['_id'] = d['_id']
        self.docs.append(d)
        return types.SimpleNamespace(inserted_id=d['_id'])

    def insert_many(self, docs, ordered=True):
        for d in docs:
            self.insert_one(d)

    def find(self, flt=None, projection=None):
        return _Cursor(dict(d) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = self.find(flt)
        if sort:
            rows = rows.sort(sort[0][0], sort[0][1])
        return dict(rows[0]) if rows else None

    def count_documents(self, flt=None):
        return len(self.find(flt))

    def distinct(self, key, flt=None):
        out = []
        for d in self.find(flt):
            v = _get(d, key)
            if v not in out:
                out.append(v)
        return out

    @staticmethod
    def _apply(d, update):
        for k, v in (update.get('$set') or {}).items():
            d[k] = v
        for k, v in (update.get('$inc') or {}).items():
            d[k] = (d.get(k) or 0) + v
        for k in (update.get('$unset') or {}):
            d.pop(k, None)

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            d = {k: v for k, v in flt.items() if not str(k).startswith('$') and not isinstance(v, dict)}
            d.update(update.get('$setOnInsert') or {})
            self._apply(d, update)
            d.setdefault('_id', f"{self.name}-{next(self._n)}")
            self.docs.append(d)
        return types.SimpleNamespace(matched_count=0, modified_count=0)

    def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                n += 1
        return types.SimpleNamespace(matched_count=n, modified_count=n)

    def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                del self.docs[i]
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)

    def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, flt)]
        return types.SimpleNamespace(deleted_count=before - len(self.docs))

    def aggregate(self, pipeline):
        return iter([])


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
_pe = types.ModuleType('pymongo.errors')
_pe.DuplicateKeyError = DuplicateKeyError
sys.modules['pymongo.errors'] = _pe
sys.modules.setdefault('pymongo', types.ModuleType('pymongo')).errors = _pe


# ---------------------------------------------------------------- requests giả: ghi lại mọi lệnh gọi nền tảng
class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload
        self.content = b'{}'
        self.text = str(payload)
        self.ok = status < 300

    def json(self):
        return self._p


CALLS = []


def _fake_post(url, data=None, json=None, params=None, headers=None, auth=None, timeout=None, **kw):
    CALLS.append({'url': url, 'data': data, 'json': json, 'params': params, 'headers': headers or {}, 'auth': auth})
    if '/Messages.json' in url:
        return _Resp(201, {'sid': f"SM{len(CALLS)}"})
    if '/oa/message/cs' in url:
        return _Resp(200, {'error': 0, 'data': {'message_id': f"z{len(CALLS)}"}})
    if '/me/messages' in url:
        return _Resp(200, {'message_id': f"m{len(CALLS)}"})
    return _Resp(404, {'error': {'message': 'unexpected url in test'}})


_rq = types.ModuleType('requests')
_rq.post = _fake_post
_rq.get = MagicMock(side_effect=AssertionError('no GET expected'))
_rq.exceptions = types.SimpleNamespace(RequestException=type('RequestException', (Exception,), {}),
                                       Timeout=type('Timeout', (Exception,), {}))
sys.modules['requests'] = _rq

_vault = types.ModuleType('nurture_channel_tokens')
_vault.encrypt_secret = lambda s: s
_vault.decrypt_secret = lambda s: s
_vault.get_channel_token = lambda bid, platform: {'access_token': f"tw-secret-{bid}"} if platform == 'twilio' else None
_vault.save_channel_token = MagicMock()
sys.modules['nurture_channel_tokens'] = _vault

EMAILS = []
_es = types.ModuleType('email_service')
_es.EmailService = types.SimpleNamespace(send_email=lambda to, subject, html: (EMAILS.append((to, subject, html)) or (True, 'ok')))
sys.modules['email_service'] = _es
_ds = types.ModuleType('ai_deepseek_client')
_ds.deepseek_chat_completion = MagicMock(side_effect=AssertionError('DeepSeek must not be called'))
sys.modules['ai_deepseek_client'] = _ds
_ace = types.ModuleType('ai_context_engine')
_ace.AIContextEngine = types.SimpleNamespace(_load_purchase_history=lambda *a, **k: [])
sys.modules['ai_context_engine'] = _ace

import messaging  # noqa: E402
import inbox_channels  # noqa: E402
import message_delivery_worker  # noqa: E402
import nurture_scheduler  # noqa: E402
import ai_nurturing_engine  # noqa: E402
from ai_nurturing_engine import AINurturingEngine  # noqa: E402
from flask import Flask, jsonify, request, session  # noqa: E402


# ---------------------------------------------------------------- hàm của app.py (mã nguồn qua ast, bỏ decorator)
def _read(path):
    with io.open(path, encoding='utf-8') as f:
        return f.read()


APP_SRC = _read(os.path.join(ROOT, 'app.py'))
_TREE = ast.parse(APP_SRC)
NS = {'db': DB, 'jsonify': jsonify, 'request': request, 'session': session, 'datetime': datetime, 'timedelta': timedelta,
      'timezone': timezone, 'os': os, 're': re, 'next_mongo_id': lambda c: next(_ids), '_vi_en': lambda vi, en: en,
      'AINurturingEngine': AINurturingEngine, 'requests': _rq}
_FUNCS = ('_queue_loyalty_notification', '_run_birthday_check_for_business', 'nurture_rules_create', 'nurture_rules_list',
          'nurture_approve_message', 'nurture_generate_campaign', '_nurture_connect_moved', 'nurture_test_connection',
          'nurture_toggle_connection', '_run_appointment_reminder_check_for_business')
for _name in _FUNCS:
    _node = next(n for n in _TREE.body if isinstance(n, ast.FunctionDef) and n.name == _name)
    _node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), f'app.py::{_name}', 'exec'), NS)


def _src_of(name, tree=_TREE, src=APP_SRC):
    """Mã nguồn 1 hàm, BỎ chú thích # và docstring (câu giải thích "trước đây..." không tính là mã)."""
    import tokenize
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    seg = ast.get_source_segment(src, node)
    doc = ast.get_docstring(node, clean=False)
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(seg).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and doc is not None and doc in tok.string:
            continue
        out.append(tok.string)
    return ' '.join(out)


FLASK = Flask(__name__)
FLASK.secret_key = 'test'
VI_RE = re.compile(r'[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]', re.I)

AU, US, VN = 'biz-au', 'biz-us', 'biz-vn'


def _naive(dt):
    return messaging._server_naive(dt).isoformat()


def _at_local(tz, hour, day_offset=0):
    loc = datetime.now(ZoneInfo(tz)).replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    return loc.astimezone(timezone.utc)


def _setup_shops(twilio=True):
    DB.reset()
    CALLS.clear()
    EMAILS.clear()
    DB.businesses.insert_one({'id': AU, 'name': 'Lan Nails Sydney', 'country': 'AU', 'currency': 'AUD'})
    DB.businesses.insert_one({'id': US, 'name': 'Bella Nails NYC', 'country': 'US', 'currency': 'USD'})
    DB.businesses.insert_one({'id': VN, 'name': 'Tiệm Hoa', 'country': 'VN', 'currency': 'VND'})
    for bid in (AU, US, VN):
        row = {'business_id': bid, 'reviews_enabled': True, 'google_review_url': 'https://g.page/r/demo/review'}
        if twilio:
            row.update({'sms_enabled': True, 'twilio_account_sid': f'AC{bid}', 'twilio_from': '+61400000000'})
        DB.messaging_settings.insert_one(row)


def _connect(bid, channel, token):
    DB.inbox_channels.insert_one({'business_id': bid, 'channel': channel, 'status': 'connected', 'access_token_enc': token,
                                  'token_saved_at': datetime.now().isoformat(), 'hook_key': 'k' * 20})


def _customer_said(bid, channel, uid, when_utc):
    DB.bot_customers.insert_one({'id': inbox_channels.conversation_id(bid, channel, uid), 'business_id': bid, 'channel': channel,
                                 'last_inbound_at': _naive(when_utc)})


def _platform_calls(fragment):
    return [c for c in CALLS if fragment in c['url']]


# ================================================================ 1) xin đánh giá
class ReviewRequestTests(unittest.TestCase):
    def setUp(self):
        _setup_shops()
        self.now = _at_local('Australia/Sydney', 11)
        self.st = messaging.get_settings(AU)

    def _order(self, oid, hours_ago, **meta):
        DB.orders.insert_one({'id': oid, 'business_id': AU, 'status': 'completed', 'total_amount': 80, 'payment_method': 'card',
                              'created_at': _naive(self.now - timedelta(hours=hours_ago)), 'metadata': meta})

    def test_paid_order_with_metadata_phone_queues_and_sends_one_review_sms(self):
        self._order(9001, 2, customer_phone='0412 000 111', customer_name='Mia Wong')
        self.assertEqual(messaging.produce_review_requests(AU, self.st, self.now), 1)
        rows = DB.outbound_messages.find({'kind': 'review_request'})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['channel'], rows[0]['to']), ('sms', '+61412000111'))
        self.assertIn('Hi Mia,', rows[0]['body'])
        self.assertIn('https://g.page/r/demo/review', rows[0]['body'])
        self.assertTrue(DB.orders.find_one({'id': 9001})['review_requested'])
        stats = messaging.pump(AU, now_utc=self.now, produce=False)
        self.assertEqual(stats['sent'], 1)
        tw = _platform_calls('/Messages.json')
        self.assertEqual(len(tw), 1)
        self.assertEqual(tw[0]['data']['To'], '+61412000111')
        self.assertTrue(tw[0]['data']['Body'].endswith('Reply STOP to opt out.'))
        self.assertEqual(tw[0]['auth'], (f'AC{AU}', f'tw-secret-{AU}'))

    def test_one_request_per_customer_per_cooldown(self):
        self._order(9001, 3, customer_phone='0412 000 111', customer_name='Mia Wong')
        self.assertEqual(messaging.produce_review_requests(AU, self.st, self.now), 1)
        self._order(9002, 2, customer_phone='0412000111', customer_name='Mia Wong')   # quay lại sau 1 giờ
        self.assertEqual(messaging.produce_review_requests(AU, self.st, self.now), 0)
        self.assertEqual(DB.outbound_messages.count_documents({'kind': 'review_request'}), 1)

    def test_opted_out_customer_gets_nothing(self):
        messaging.opt_out(AU, 'sms', '+61412000222', source='STOP')
        self._order(9003, 2, customer_phone='0412 000 222', customer_name='Ava')
        self.assertEqual(messaging.produce_review_requests(AU, self.st, self.now), 0)
        self.assertEqual(DB.outbound_messages.count_documents({'kind': 'review_request'}), 0)

    def test_walk_in_orders_without_contact_are_not_scanned(self):
        self._order(9004, 2)
        self.assertEqual(messaging.produce_review_requests(AU, self.st, self.now), 0)
        self.assertNotIn('review_requested', DB.orders.find_one({'id': 9004}))

    def test_too_fresh_or_too_old_orders_wait_or_are_ignored(self):
        self._order(9005, 0.5, customer_phone='0412 000 555')     # < 90 phút
        self._order(9006, 60, customer_phone='0412 000 666')      # > 48 giờ
        self.assertEqual(messaging.produce_review_requests(AU, self.st, self.now), 0)

    def test_email_from_customer_record_when_sms_not_connected(self):
        _setup_shops(twilio=False)
        st = messaging.get_settings(AU)
        DB.customers.insert_one({'id': 77, 'business_id': AU, 'phone': '0412 000 333', 'name': 'Zoe Lee', 'email': 'Zoe@Example.com'})
        self._order(9007, 2, customer_phone='0412 000 333')
        self.assertEqual(messaging.produce_review_requests(AU, st, self.now), 1)
        row = DB.outbound_messages.find_one({'kind': 'review_request'})
        self.assertEqual((row['channel'], row['to']), ('email', 'zoe@example.com'))
        self.assertIn('Hi Zoe,', row['body'])
        messaging.pump(AU, now_utc=self.now, produce=False)
        self.assertEqual(len(EMAILS), 1)
        self.assertIn('Unsubscribe', EMAILS[0][2])

    def test_legacy_top_level_contact_still_works(self):
        DB.orders.insert_one({'id': 9008, 'business_id': AU, 'status': 'paid', 'created_at': _naive(self.now - timedelta(hours=5)),
                              'customer_phone': '0412 000 888', 'customer_name': 'Old Order'})
        self.assertEqual(messaging.produce_review_requests(AU, self.st, self.now), 1)

    def test_outside_send_window_is_deferred(self):
        self._order(9001, 2, customer_phone='0412 000 111')
        night = _at_local('Australia/Sydney', 22)
        DB.orders.update_one({'id': 9001}, {'$set': {'created_at': _naive(night - timedelta(hours=2))}})
        messaging.produce_review_requests(AU, self.st, night)
        stats = messaging.pump(AU, now_utc=night, produce=False)
        self.assertEqual((stats['sent'], stats['deferred']), (0, 1))
        self.assertEqual(_platform_calls('/Messages.json'), [])

    def test_no_rating_gating_and_reads_metadata(self):
        src = _src_of('produce_review_requests', ast.parse(_read(os.path.join(ROOT, 'messaging.py'))),
                      _read(os.path.join(ROOT, 'messaging.py')))
        self.assertNotRegex(src, r'rating|stars?\b')
        self.assertIn("metadata.customer_phone", src)
        self.assertIn("'metadata'", _src_of('_order_contact', ast.parse(_read(os.path.join(ROOT, 'messaging.py'))),
                                             _read(os.path.join(ROOT, 'messaging.py'))))


# ================================================================ 2) tin chăm sóc Zalo / Messenger
class NurtureDeliveryTests(unittest.TestCase):
    def setUp(self):
        _setup_shops()
        self.now = _at_local('Australia/Sydney', 11)

    def _cust(self, cid, **f):
        DB.customers.insert_one({'id': cid, 'business_id': AU, 'name': f.pop('name', 'Lan Tran'), **f})

    def _camp(self, mid, cid, channel, step=0, approved=None):
        DB.campaign_messages.insert_one({'id': mid, 'business_id': AU, 'campaign_id': 'camp-1', 'customer_id': cid, 'step_delay': step,
                                         'channel': channel, 'message_body': f'Hi there, ready for your next visit? ({mid})',
                                         'approval_status': 'APPROVED',
                                         'approved_at': (approved or self.now - timedelta(hours=1)).isoformat()})

    def test_normalize_channel(self):
        n = messaging.normalize_channel
        self.assertEqual([n(x) for x in ('SMS', 'EMAIL', 'ZALO', 'FACEBOOK', 'zalo_oa', 'facebook', 'Messenger', ' Zalo OA ')],
                         ['sms', 'email', 'zalo', 'messenger', 'zalo', 'messenger', 'messenger', 'zalo'])
        self.assertIsNone(n('pigeon'))
        self.assertEqual(messaging.CHANNELS, ('sms', 'email', 'zalo', 'messenger'))

    def test_worker_run_sends_zalo_with_shop_token_and_leaves_sms_email_rows_correct(self):
        _connect(AU, 'zalo', 'SHOP-OWN-ZALO-TOKEN')
        self._cust(501, phone='0412 345 678', zalo_user_id='zu-1')
        self._cust(502, phone='0412 345 000')
        self._cust(503, email='only.email@example.com')
        _customer_said(AU, 'zalo', 'zu-1', self.now - timedelta(hours=3))
        self._camp('m-zalo', 501, 'ZALO')
        self._camp('m-sms', 502, 'SMS')
        self._camp('m-email', 503, 'EMAIL')
        out = message_delivery_worker.run_once(now_utc=self.now)
        self.assertEqual(out['businesses'], 1)
        zalo = _platform_calls('/oa/message/cs')
        self.assertEqual(len(zalo), 1)
        self.assertEqual(zalo[0]['headers'].get('access_token'), 'SHOP-OWN-ZALO-TOKEN')
        self.assertEqual(zalo[0]['json']['recipient']['user_id'], 'zu-1')
        self.assertFalse(any('GLOBAL-SERVER' in str(c) for c in CALLS))
        rows = {r['id']: r for r in DB.campaign_messages.find({})}
        self.assertEqual((rows['m-zalo']['delivery_status'], rows['m-zalo']['delivery_channel'], rows['m-zalo']['channel']),
                         ('success', 'zalo', 'zalo'))
        self.assertEqual((rows['m-sms']['delivery_status'], rows['m-sms']['delivery_channel']), ('success', 'sms'))
        self.assertEqual((rows['m-email']['delivery_status'], rows['m-email']['delivery_channel']), ('success', 'email'))
        self.assertEqual(len(_platform_calls('/Messages.json')), 1)
        self.assertEqual(len(EMAILS), 1)
        # tin hiện trong hội thoại Zalo của khách ở hộp thư chung (đã gửi)
        bubble = DB.bot_messages.find_one({'customer_id': inbox_channels.conversation_id(AU, 'zalo', 'zu-1')})
        self.assertEqual((bubble['sender_type'], bubble['delivery']['status']), ('ai', 'sent'))
        # lượt thứ 2: không còn tin chờ, không gửi lại
        CALLS.clear()
        self.assertEqual(message_delivery_worker.run_once(now_utc=self.now)['businesses'], 0)
        messaging.pump(AU, now_utc=self.now)
        self.assertEqual(CALLS, [])

    def test_worker_never_writes_campaign_rows_itself(self):
        src = _read(os.path.join(ROOT, 'message_delivery_worker.py'))
        self.assertNotIn('campaign_messages.update', src)
        self.assertNotIn('graph.facebook.com', src)
        self.assertNotIn('openapi.zalo.me', src)
        self.assertIn('messaging.pump', src)

    def test_messenger_inside_24h_sends_with_page_token(self):
        _connect(AU, 'messenger', 'SHOP-OWN-PAGE-TOKEN')
        self._cust(601, fb_psid='psid-1', phone='0412 111 222')
        _customer_said(AU, 'messenger', 'psid-1', self.now - timedelta(hours=2))
        self._camp('m-fb', 601, 'FACEBOOK')
        messaging.pump(AU, now_utc=self.now)
        fb = _platform_calls('/me/messages')
        self.assertEqual(len(fb), 1)
        self.assertEqual(fb[0]['params']['access_token'], 'SHOP-OWN-PAGE-TOKEN')
        self.assertEqual(fb[0]['json']['messaging_type'], 'RESPONSE')
        self.assertEqual(_platform_calls('/Messages.json'), [])
        self.assertEqual(DB.campaign_messages.find_one({'id': 'm-fb'})['delivery_status'], 'success')

    def test_messenger_outside_24h_goes_by_sms_never_messenger(self):
        _connect(AU, 'messenger', 'SHOP-OWN-PAGE-TOKEN')
        self._cust(602, fb_psid='psid-2', phone='0412 111 333')
        _customer_said(AU, 'messenger', 'psid-2', self.now - timedelta(hours=30))
        self._camp('m-fb2', 602, 'facebook')
        messaging.pump(AU, now_utc=self.now)
        self.assertEqual(_platform_calls('/me/messages'), [])
        tw = _platform_calls('/Messages.json')
        self.assertEqual([c['data']['To'] for c in tw], ['+61412111333'])
        row = DB.campaign_messages.find_one({'id': 'm-fb2'})
        self.assertEqual((row['delivery_status'], row['delivery_channel']), ('success', 'sms'))

    def test_window_closed_at_send_time_without_contact_is_skipped_with_reason(self):
        _connect(AU, 'messenger', 'SHOP-OWN-PAGE-TOKEN')
        self._cust(603, fb_psid='psid-3')     # không SĐT / email
        _customer_said(AU, 'messenger', 'psid-3', self.now - timedelta(hours=1))
        self._camp('m-fb3', 603, 'messenger', step=3)
        messaging.pump(AU, now_utc=self.now)   # tin hẹn 3 ngày sau -> đã xếp hàng qua Messenger
        q = DB.outbound_messages.find_one({'meta.campaign_message_id': 'm-fb3'})
        self.assertEqual((q['channel'], q['status']), ('messenger', 'queued'))
        later = self.now + timedelta(days=3, minutes=1)
        stats = messaging.pump(AU, now_utc=later)
        self.assertEqual(_platform_calls('/me/messages'), [])
        q = DB.outbound_messages.find_one({'id': q['id']})
        self.assertEqual(q['status'], 'cancelled')
        self.assertTrue(q['error'].startswith('skipped: outside messaging window'))
        row = DB.campaign_messages.find_one({'id': 'm-fb3'})
        self.assertEqual((row['delivery_status'], row['delivery_error']), ('skipped', 'outside messaging window'))
        self.assertEqual(stats['skipped'], 1)

    def test_window_closed_at_send_time_falls_back_to_email(self):
        _connect(AU, 'zalo', 'SHOP-OWN-ZALO-TOKEN')
        _setup_no_twilio = DB.messaging_settings.update_one({'business_id': AU}, {'$set': {'sms_enabled': False}})  # noqa: F841
        self._cust(604, zalo_user_id='zu-4', email='kim@example.com', phone='0412 999 000')
        _customer_said(AU, 'zalo', 'zu-4', self.now - timedelta(hours=1))
        self._camp('m-z4', 604, 'zalo', step=3)
        messaging.pump(AU, now_utc=self.now)
        messaging.pump(AU, now_utc=self.now + timedelta(days=3, minutes=1))   # 3 ngày sau: hết khung 48 giờ
        self.assertEqual(_platform_calls('/oa/message/cs'), [])
        self.assertEqual([e[0] for e in EMAILS], ['kim@example.com'])
        row = DB.campaign_messages.find_one({'id': 'm-z4'})
        self.assertEqual((row['delivery_status'], row['delivery_channel']), ('success', 'email'))

    def test_zalo_not_connected_or_unlinked_uses_sms(self):
        self._cust(605, zalo_user_id='zu-5', phone='0412 555 000')   # tiệm chưa nối Zalo ở hộp thư chung
        self._camp('m-z5', 605, 'ZALO')
        messaging.pump(AU, now_utc=self.now)
        self.assertEqual(_platform_calls('/oa/message/cs'), [])
        self.assertEqual(DB.campaign_messages.find_one({'id': 'm-z5'})['delivery_channel'], 'sms')

    def test_stale_old_social_messages_are_expired_not_sent_late(self):
        self._cust(606, zalo_user_id='zu-6', phone='0412 666 000')
        self._camp('m-old', 606, 'ZALO', approved=self.now - timedelta(days=60))
        messaging.pump(AU, now_utc=self.now)
        self.assertEqual(CALLS, [])
        self.assertEqual(DB.campaign_messages.find_one({'id': 'm-old'})['delivery_status'], 'expired')

    def test_old_worker_successes_are_not_resent(self):
        self._cust(607, phone='0412 777 000')
        self._camp('m-done', 607, 'ZALO')
        DB.campaign_messages.update_one({'id': 'm-done'}, {'$set': {'sent_at': datetime.now().isoformat(), 'delivery_status': 'success'}})
        messaging.pump(AU, now_utc=self.now)
        self.assertEqual(CALLS, [])

    def test_opted_out_customer_is_not_messaged(self):
        self._cust(608, phone='0412 888 000')
        messaging.opt_out(AU, 'sms', '+61412888000')
        self._camp('m-opt', 608, 'sms')
        messaging.pump(AU, now_utc=self.now)
        self.assertEqual(CALLS, [])
        self.assertEqual(DB.campaign_messages.find_one({'id': 'm-opt'})['delivery_status'], 'opted_out')


# ================================================================ 3) API luật + chiến dịch + duyệt
class NurtureApiTests(unittest.TestCase):
    def setUp(self):
        _setup_shops()

    def _post(self, fn, bid, body, *args):
        with FLASK.test_request_context('/x', method='POST', json=body):
            session['user_id'] = bid
            session['business_id'] = bid
            session['business_mode'] = 'nail'
            out = fn(*args)
        return out if isinstance(out, tuple) else (out, 200)

    def test_rules_accept_all_four_channels_and_fix_zalo_oa(self):
        fn = NS['nurture_rules_create']
        for given, want in (('zalo_oa', 'zalo'), ('facebook', 'messenger'), ('SMS', 'sms'), ('email', 'email'), (None, 'sms')):
            resp, code = self._post(fn, AU, {'name': 'Lapsed', 'condition_days': 30, **({'channel': given} if given else {})})
            self.assertEqual(code, 200, resp.get_json())
            self.assertEqual(resp.get_json()['channel'], want)
        self.assertEqual(sorted(r['channel'] for r in DB.nurture_schedule_rules.find({})), ['email', 'messenger', 'sms', 'sms', 'zalo'])
        resp, code = self._post(fn, VN, {'name': 'Lâu chưa ghé', 'condition_days': 30})
        self.assertEqual(resp.get_json()['channel'], 'zalo')   # VN mặc định Zalo
        resp, code = self._post(fn, AU, {'name': 'x', 'condition_days': 30, 'channel': 'pigeon'})
        self.assertEqual(code, 400)
        self.assertIn('sms, email, zalo, messenger', resp.get_json()['message'])
        resp, code = self._post(fn, AU, {'name': 'x', 'condition_days': 'abc'})
        self.assertEqual(code, 400)
        resp, code = self._post(fn, VN, {'name': 'x', 'condition_days': 30, 'channel': 'pigeon'})
        self.assertRegex(resp.get_json()['message'], VI_RE)    # câu lỗi theo ngôn ngữ tiệm

    def test_rules_list_normalizes_legacy_values(self):
        DB.nurture_schedule_rules.insert_one({'id': 1, 'business_id': AU, 'channel': 'zalo_oa', 'created_at': '1'})
        with FLASK.test_request_context('/x'):
            session['business_id'] = AU
            data = NS['nurture_rules_list']().get_json()
        self.assertEqual(data['data'][0]['channel'], 'zalo')

    def test_scheduler_stores_normalized_channel_and_utc_approval(self):
        now = datetime.now()
        DB.customers.insert_one({'id': 801, 'business_id': AU, 'name': 'Kim', 'phone': '0412 801 000', 'total_spent': 90})
        DB.orders.insert_one({'id': 1, 'business_id': AU, 'status': 'completed', 'created_at': (now - timedelta(days=40)).isoformat(),
                              'metadata': {'customer_phone': '0412 801 000'}})
        DB.customers.insert_one({'id': 802, 'business_id': AU, 'name': 'Nobody', 'total_spent': 0,
                                 'last_purchase_at': (now - timedelta(days=40)).isoformat()})   # không liên lạc được
        DB.nurture_schedule_rules.insert_one({'id': 5, 'business_id': AU, 'name': 'Lapsed', 'condition_days': 30, 'channel': 'zalo_oa',
                                              'auto_send': True, 'is_active': True, 'industry': 'nail'})
        nurture_scheduler.run_once()
        rows = DB.campaign_messages.find({'rule_id': 5})
        self.assertEqual([(r['customer_id'], r['channel'], r['approval_status']) for r in rows], [(801, 'zalo', 'APPROVED')])
        self.assertIsNotNone(datetime.fromisoformat(rows[0]['approved_at']).tzinfo)
        self.assertNotRegex(rows[0]['message_body'], VI_RE)   # tiệm Úc -> tiếng Anh

    def test_generate_campaign_stores_lowercase_channel_and_percentile_vip(self):
        for cid, spent in ((1, 50), (2, 100), (3, 200), (4, 800)):
            DB.customers.insert_one({'id': cid, 'business_id': US, 'name': f'C{cid}', 'phone': f'+1212555000{cid}', 'total_spent': spent})
        resp, code = self._post(NS['nurture_generate_campaign'], US, {'segment': 'VIP', 'goal': 'RECALL', 'channel': 'FACEBOOK'})
        body = resp.get_json()
        self.assertTrue(body['success'], body)
        self.assertEqual(body['channel'], 'messenger')
        self.assertEqual(body['target_count'], 1)                # top 25% chi tiêu của chính tiệm = khách $800
        self.assertEqual({r['channel'] for r in DB.campaign_messages.find({})}, {'messenger'})
        self.assertEqual(DB.nurturing_campaigns.find_one({})['channel'], 'messenger')
        src = _src_of('nurture_generate_campaign')
        self.assertNotIn('5000000', src)
        self.assertNotRegex(src, r"'ZALO'|'FACEBOOK'")

    def test_reject_after_approval_cancels_queued_message(self):
        DB.customers.insert_one({'id': 9, 'business_id': AU, 'name': 'Ivy', 'phone': '0412 009 000'})
        DB.campaign_messages.insert_one({'id': 'cm-9', 'business_id': AU, 'customer_id': 9, 'step_delay': 3, 'channel': 'sms',
                                         'message_body': 'Hi Ivy', 'approval_status': 'PENDING'})
        resp, _ = self._post(NS['nurture_approve_message'], AU, {'message_id': 'cm-9', 'action': 'APPROVED'})
        self.assertRegex(resp.get_json()['message'], r'by sms')
        messaging.pump(AU, now_utc=_at_local('Australia/Sydney', 11))
        self.assertEqual(DB.outbound_messages.find_one({'meta.campaign_message_id': 'cm-9'})['status'], 'queued')
        self._post(NS['nurture_approve_message'], AU, {'message_id': 'cm-9', 'action': 'REJECTED'})
        self.assertEqual(DB.outbound_messages.find_one({'meta.campaign_message_id': 'cm-9'})['status'], 'cancelled')

    def test_approve_social_explains_platform_window(self):
        DB.campaign_messages.insert_one({'id': 'cm-z', 'business_id': AU, 'customer_id': 9, 'step_delay': 0, 'channel': 'ZALO',
                                         'message_body': 'Hi', 'approval_status': 'PENDING'})
        resp, _ = self._post(NS['nurture_approve_message'], AU, {'message_id': 'cm-z', 'action': 'APPROVED'})
        msg = resp.get_json()['message']
        self.assertIn('by zalo', msg)
        self.assertIn('48 hours', msg)

    def test_legacy_token_connect_routes_point_to_inbox_channels(self):
        for name in ('nurture_test_connection', 'nurture_toggle_connection'):
            resp, code = self._post(NS[name], AU, {'platform': 'zalo', 'access_token': 'x'})
            self.assertEqual(code, 410)
            self.assertEqual(resp.get_json()['redirect'], '/inbox/channels')
        _vault.save_channel_token.assert_not_called()


# ================================================================ 4) sinh nhật + tích điểm
class BirthdayLoyaltyTests(unittest.TestCase):
    def setUp(self):
        _setup_shops()

    def test_birthday_plan_uses_shop_local_day(self):
        us = messaging.get_settings(US)
        p = messaging.birthday_plan(us, datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc))   # 22:00 ngày 26 ở New York
        self.assertEqual(p['birthday'].isoformat(), '2026-10-27')
        self.assertEqual(p['send_after'], datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc))   # 9:00 sáng giờ New York
        au = messaging.get_settings(AU)
        p = messaging.birthday_plan(au, datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc))      # 12:00 ngày 27 ở Sydney
        self.assertEqual((p['birthday'].isoformat(), p['send_after']), ('2026-10-27', datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)))
        p = messaging.birthday_plan(dict(au, birthday_days_before=3), datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc))
        self.assertEqual(p['birthday'].isoformat(), '2026-10-30')
        p = messaging.birthday_plan(au, datetime(2027, 2, 28, 1, 0, tzinfo=timezone.utc))
        self.assertIn('02-29', p['match_md'])

    def test_au_birthday_goes_by_shop_sms_in_english_without_server_tokens(self):
        DB.customers.insert_one({'id': 11, 'business_id': AU, 'name': 'Chloe Smith', 'phone': '0412 011 000', 'dob': '1992-10-27',
                                 'zalo_user_id': 'zu-11', 'fb_psid': 'psid-11'})
        DB.customers.insert_one({'id': 12, 'business_id': AU, 'name': 'Not Today', 'phone': '0412 012 000', 'dob': '1992-10-28'})
        now = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(NS['_run_birthday_check_for_business'](AU, now), 1)
        row = DB.outbound_messages.find_one({'kind': 'birthday'})
        self.assertEqual((row['channel'], row['to']), ('sms', '+61412011000'))
        self.assertTrue(row['body'].startswith('Happy birthday, Chloe!'))
        self.assertIn('Lan Nails Sydney', row['body'])
        self.assertNotRegex(row['body'], r'(?i)offer|gift|discount|voucher')
        self.assertEqual(NS['_run_birthday_check_for_business'](AU, now), 0)        # 1 lần / năm
        self.assertEqual(DB.outbound_messages.count_documents({'kind': 'birthday'}), 1)
        self.assertEqual(DB.loyalty_events.find_one({'event_type': 'birthday'})['status'], 'queued')
        self.assertFalse(any('GLOBAL-SERVER' in str(c) for c in CALLS))
        self.assertEqual(_platform_calls('openapi.zalo.me') + _platform_calls('graph.facebook.com'), [])

    def test_vn_birthday_in_vietnamese_and_us_scheduled_for_local_morning(self):
        DB.customers.insert_one({'id': 21, 'business_id': VN, 'name': 'Nguyễn Thu', 'email': 'thu@example.com', 'dob': '1990-10-27'})
        DB.customers.insert_one({'id': 22, 'business_id': US, 'name': 'Rita', 'phone': '(212) 555-0122', 'dob': '1985-10-27'})
        NS['_run_birthday_check_for_business'](VN, datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc))
        NS['_run_birthday_check_for_business'](US, datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc))
        vn = DB.outbound_messages.find_one({'business_id': VN, 'kind': 'birthday'})
        self.assertRegex(vn['body'], VI_RE)
        self.assertTrue(vn['body'].startswith('Chúc mừng sinh nhật Thu!'), vn['body'])   # gọi tên, không gọi họ
        self.assertEqual(vn['channel'], 'email')
        us = DB.outbound_messages.find_one({'business_id': US, 'kind': 'birthday'})
        self.assertEqual(us['send_after'], datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc).isoformat())

    def test_birthday_via_shop_zalo_when_customer_chatted_recently(self):
        # 10:00 ở Việt Nam HÔM NAY: khung 48 giờ của Zalo tính theo giờ thật (queue_customer_message không nhận now)
        now = datetime.now(timezone.utc).replace(hour=3, minute=0, second=0, microsecond=0)
        _connect(VN, 'zalo', 'VN-SHOP-OA-TOKEN')
        DB.customers.insert_one({'id': 31, 'business_id': VN, 'name': 'Hà', 'zalo_user_id': 'zu-31',
                                 'dob': '2000-' + now.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%m-%d')})
        _customer_said(VN, 'zalo', 'zu-31', now - timedelta(hours=5))
        NS['_run_birthday_check_for_business'](VN, now)
        row = DB.outbound_messages.find_one({'business_id': VN, 'kind': 'birthday'})
        self.assertEqual((row['channel'], row['to']), ('zalo', 'zu-31'))
        messaging.pump(VN, now_utc=now, produce=False)
        z = _platform_calls('/oa/message/cs')
        self.assertEqual([c['headers'].get('access_token') for c in z], ['VN-SHOP-OA-TOKEN'])

    def test_loyalty_points_email_by_default_sms_only_when_owner_enables(self):
        fn = NS['_queue_loyalty_notification']
        cust = {'id': 41, 'phone': '0412 041 000', 'email': 'pts@example.com'}
        msg = ("Thanks for visiting {shop}! You earned 10 reward points — you now have 30.", "Cảm ơn bạn đã ghé {shop}!")
        self.assertEqual(fn(AU, cust, 'points_awarded', msg), 'queued')
        row = DB.outbound_messages.find_one({'kind': 'loyalty'})
        self.assertEqual(row['channel'], 'email')
        self.assertIn('Lan Nails Sydney', row['body'])
        self.assertEqual(fn(AU, {'id': 42, 'phone': '0412 042 000'}, 'points_awarded', msg), 'skipped_no_channel')
        DB.messaging_settings.update_one({'business_id': AU}, {'$set': {'loyalty_sms_enabled': True}})
        self.assertEqual(fn(AU, {'id': 42, 'phone': '0412 042 000'}, 'points_awarded', msg), 'queued')
        self.assertEqual(DB.outbound_messages.find_one({'meta.customer_id': 42})['channel'], 'sms')
        DB.messaging_settings.update_one({'business_id': AU}, {'$set': {'loyalty_messages_enabled': False}})
        self.assertEqual(fn(AU, cust, 'tier_upgrade', msg), 'disabled')
        self.assertFalse(any('GLOBAL-SERVER' in str(c) for c in CALLS))

    def test_vn_legacy_reminder_uses_shop_zalo_only_and_cron_uses_shop_local_time(self):
        now = datetime.now(timezone.utc).replace(hour=3, minute=0, second=0, microsecond=0)   # 10:00 ở Việt Nam hôm nay
        local = now.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).replace(tzinfo=None)
        _connect(VN, 'zalo', 'VN-SHOP-OA-TOKEN')
        DB.customers.insert_one({'id': 51, 'business_id': VN, 'name': 'Lê Mai', 'phone': '0901000051', 'zalo_user_id': 'zu-51'})
        DB.customers.insert_one({'id': 52, 'business_id': VN, 'name': 'Trần An', 'phone': '0901000052'})
        _customer_said(VN, 'zalo', 'zu-51', now - timedelta(hours=6))
        for aid, phone in ((1, '0901000051'), (2, '0901000052')):
            DB.appointments.insert_one({'id': aid, 'business_id': VN, 'status': 'confirmed', 'customer_phone': phone,
                                        'customer_name': 'Khách', 'book_time': (local + timedelta(hours=5)).isoformat()})
        NS['_run_appointment_reminder_check_for_business'](VN, local)
        rows = DB.outbound_messages.find({'business_id': VN, 'kind': 'appointment_reminder'})
        self.assertEqual([(r['channel'], r['to']) for r in rows], [('zalo', 'zu-51')])   # khách không Zalo: không SMS ở đây
        cron = _src_of('cron_daily_tasks')
        self.assertIn('messaging . local_now ( msg_settings )', cron)
        self.assertLess(cron.index('messaging . pump ( business_id , base_url = base_url )'),
                        cron.index('_run_appointment_reminder_check_for_business'))   # pump (SMS/email) trước, Zalo cũ sau

    def test_app_sources_drop_server_tokens_and_invented_offers(self):
        q = _src_of('_queue_loyalty_notification')
        self.assertNotIn("os.environ.get('ZALO_OA_ACCESS_TOKEN')", q)
        self.assertNotIn("os.environ.get('FB_PAGE_ACCESS_TOKEN')", q)
        self.assertNotIn('requests.post', q)
        award = _src_of('_award_loyalty_points')
        self.assertNotIn('special offer', award)
        self.assertNotIn('ưu đãi đặc biệt', award)
        bday = _src_of('_run_birthday_check_for_business')
        self.assertNotIn('ưu đãi', bday)
        self.assertNotIn("datetime.now().strftime('%m-%d')", bday)


# ================================================================ 5) hạng chi tiêu + ghi chú
class ChurnScoringTests(unittest.TestCase):
    def setUp(self):
        _setup_shops()

    def test_usd_spend_ranked_inside_the_shop(self):
        now = datetime.now()
        for cid, spent in ((1, 800), (2, 50)):
            DB.customers.insert_one({'id': cid, 'business_id': US, 'phone': f'+1212555010{cid}', 'total_spent': spent})
            DB.orders.insert_one({'id': cid, 'business_id': US, 'created_at': (now - timedelta(days=10)).isoformat(),
                                  'metadata': {'customer_phone': f'+1212555010{cid}'}})
        ai_nurturing_engine.recompute_customer_segments(US)
        big, small = DB.customers.find_one({'id': 1}), DB.customers.find_one({'id': 2})
        self.assertGreater(big['potential_score'], small['potential_score'])
        self.assertNotRegex(big['ai_notes'], VI_RE)
        self.assertNotRegex(small['ai_notes'], VI_RE)

    def test_vnd_shop_same_rule_and_vietnamese_notes(self):
        now = datetime.now()
        for cid, spent in ((1, 5_000_000), (2, 200_000)):
            DB.customers.insert_one({'id': cid, 'business_id': VN, 'phone': f'09000000{cid}', 'total_spent': spent})
            DB.orders.insert_one({'id': cid, 'business_id': VN, 'created_at': (now - timedelta(days=100)).isoformat(),
                                  'metadata': {'customer_phone': f'09000000{cid}'}})
        ai_nurturing_engine.recompute_customer_segments(VN)
        big, small = DB.customers.find_one({'id': 1}), DB.customers.find_one({'id': 2})
        self.assertEqual(big['nurturing_status'], 'CHURN_RISK')
        self.assertGreater(big['potential_score'], small['potential_score'])
        self.assertRegex(big['ai_notes'], VI_RE)

    def test_predict_is_currency_agnostic_and_offers_nothing(self):
        p = AINurturingEngine.predict_churn_risk
        self.assertEqual(p(10, 800, spend_rank=0.95, lang='en')[1], 95)
        self.assertEqual(p(10, 800, spend_rank=0.5, lang='en')[1], 65)
        self.assertEqual(p(10, 10_000_000, spend_rank=None, lang='en')[1], 50)   # không còn ngưỡng VND
        for days in (5, 30, 60, 120):
            for lang in ('en', 'vi'):
                notes = p(days, 0, spend_rank=0.0, lang=lang)[2]
                self.assertNotRegex(notes, r'(?i)voucher|quà tặng|ưu đãi|gift|discount')

    def test_top_spend_threshold_and_no_invented_numbers(self):
        for cid, spent in ((1, 50), (2, 100), (3, 200), (4, 800), (5, 0)):
            DB.customers.insert_one({'id': cid, 'business_id': AU, 'total_spent': spent})
        self.assertEqual(ai_nurturing_engine.top_spend_threshold(AU), 800)
        self.assertIsNone(ai_nurturing_engine.top_spend_threshold('empty-shop'))
        src = _read(os.path.join(ROOT, 'ai_nurturing_engine.py'))
        code = '\n'.join(l for l in src.splitlines() if not l.strip().startswith('#'))
        for bad in ('10000000', '5000000', '1000000', 'else 400', 'quà tặng lớn', 'ưu đãi nhỏ'):
            self.assertNotIn(bad, code)


if __name__ == '__main__':
    unittest.main(verbosity=2)
