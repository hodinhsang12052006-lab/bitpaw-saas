# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 1 "AI core gateway + runtime plan gate":
  1) ai_gateway.chat ghi db.ai_usage từ trường usage THẬT (token, chi phí theo bảng giá), thử lại đúng 1 lần chỉ khi lỗi tạm thời,
     tắt thử lại chồng của SDK; lệnh gọi thẳng ai_deepseek_client vẫn vào sổ theo phạm vi (không ghi 2 lần);
  2) ai_gateway.allowed: Essential bị chặn, Pro/Empire/tiệm cũ (chưa có gói) được; hạ gói có hiệu lực sau cache 60 giây;
  3) app.py secure_ai_generate: chat trang đặt lịch của tiệm Essential trả ai_unavailable (không AI, không ghi gì), tiệm Pro
     chạy AI + mọi vòng DeepSeek ghi sổ 'booking_chat' + _log_ai_run kèm token/chi phí;
  4) app.py _inbox_ai_reply / _inbox_sms_inbound: hạ gói -> chỉ lưu tin + needs_human, không gọi AI; gói đủ -> sổ theo kênh;
  5) GET /api/ai/usage: chỉ chủ tiệm/admin, tổng THẬT theo tính năng trong tháng theo giờ của tiệm, bỏ dòng qa_test;
  6) scripts/ai_sim/sim_booking.py gửi chat_token + lịch hạt giống mang đúng mã băm Phase 0 dùng.

KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi DeepSeek/mạng, KHÔNG import app.py (lấy hàm qua ast).
Chạy: python scripts/tests/test_phase1_ai_gateway.py
"""
import ast
import io
import json
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
os.environ.pop('BITPAW_DESKTOP_MODE', None)
os.environ['DEEPSEEK_API_KEY'] = 'unit-test-key'


# ---------------------------------------------------------------- DB giả trong RAM
def _cmp(v, op, arg):
    if v is None:
        return False
    return {'$gte': v >= arg, '$gt': v > arg, '$lt': v < arg, '$lte': v <= arg}[op]


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


class _Cursor(list):
    def sort(self, key, direction=1):
        return _Cursor(sorted(self, key=lambda d: (d.get(key) is None, d.get(key) or ''), reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs = name, []

    def insert_one(self, doc):
        d = dict(doc)
        d.setdefault('_id', len(self.docs) + 1)
        self.docs.append(d)
        return types.SimpleNamespace(inserted_id=d['_id'])

    def find(self, flt=None, projection=None):
        return _Cursor(dict(d) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = self.find(flt)
        return dict(rows[0]) if rows else None

    def count_documents(self, flt=None):
        return len(self.find(flt))

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                d.update(update.get('$set') or {})
                return types.SimpleNamespace(matched_count=1)
        return types.SimpleNamespace(matched_count=0)

    def aggregate(self, pipeline):
        rows = [dict(d) for d in self.docs]
        for stage in pipeline:
            if '$match' in stage:
                rows = [d for d in rows if _matches(d, stage['$match'])]
            elif '$group' in stage:
                spec, out = stage['$group'], {}
                for d in rows:
                    key = {k: d.get(v[1:]) for k, v in spec['_id'].items()}
                    k = json.dumps(key, sort_keys=True, default=str)
                    g = out.setdefault(k, {'_id': key})
                    for field, acc in spec.items():
                        if field == '_id':
                            continue
                        src = acc['$sum']
                        g[field] = g.get(field, 0) + (src if isinstance(src, (int, float)) else (d.get(src[1:]) or 0))
                rows = list(out.values())
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
_ids = count(5000)
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED')
_msg = types.ModuleType('messaging')
_msg.get_settings = lambda bid: {'timezone': 'Australia/Sydney', 'language': 'en'}
sys.modules['messaging'] = _msg


class _SlotErr(Exception):
    pass


_be = types.ModuleType('booking_engine')
_be.book_appointment = MagicMock()
_be.SlotAlreadyBookedError = _SlotErr
sys.modules['booking_engine'] = _be


def _no_network(*a, **kw):
    raise AssertionError('network disabled in offline tests')


patch('requests.sessions.Session.request', _no_network).start()

from flask import Flask, jsonify, request, session  # noqa: E402
import requests  # noqa: E402

import plans  # noqa: E402
import ai_deepseek_client  # noqa: E402  (module THẬT — client OpenAI giả được cài vào _client_cache bên dưới)
import ai_gateway  # noqa: E402
import ai_function_tools  # noqa: E402
import booking_rules  # noqa: E402


# ---------------------------------------------------------------- client OpenAI giả cho ai_deepseek_client thật
class FakeOpenAI:
    """Thay openai.OpenAI trong _client_cache: ghi lại max_retries đã đặt + trả usage như DeepSeek."""
    def __init__(self):
        self.calls, self.retries_seen, self.script = [], [], []
        outer = self

        class _Completions:
            def create(self_inner, timeout=None, **payload):
                outer.calls.append(payload)
                if outer.script:
                    step = outer.script.pop(0)
                    if isinstance(step, Exception):
                        raise step
                usage = {'prompt_tokens': 2000, 'completion_tokens': 100, 'prompt_cache_hit_tokens': 1500}
                return types.SimpleNamespace(model_dump=lambda: {'model': 'deepseek-chat', 'usage': usage,
                                                                  'choices': [{'message': {'content': 'hello', 'role': 'assistant'}}]})
        self.chat = types.SimpleNamespace(completions=_Completions())
        self._retries = 2

    def with_options(self, max_retries=None, **kw):
        self.retries_seen.append(max_retries)
        return self


FAKE = FakeOpenAI()
ai_deepseek_client._client_cache['unit-test-key'] = FAKE
COST_ONE_CALL = (1500 * 0.028 + 500 * 0.28 + 100 * 0.42) / 1e6


class _Status(Exception):
    def __init__(self, code):
        super().__init__(f'HTTP {code}')
        self.status_code = code


class APITimeoutError(Exception):
    pass


def _wrapped(exc):
    """Như ai_deepseek_client: lỗi gốc được bọc RuntimeError ... from e."""
    try:
        raise RuntimeError(f'wrapped: {exc}') from exc
    except RuntimeError as e:
        return e


# ---------------------------------------------------------------- hàm của app.py (lấy mã nguồn qua ast, bỏ decorator)
def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


APP_SRC = _read('app.py')
_TREE = ast.parse(APP_SRC)
_FUNCS = ('secure_ai_generate', '_inbox_ai_reply', '_inbox_sms_inbound', '_log_ai_run', 'api_ai_usage')
_ASSIGNS = ('_VI_CHARS_RE', '_VI_WORDS_RE')
LOGGED = []


def _ctx_prompt(*a, **kw):
    return {'prompt': 'TENANT', 'business_name': 'Golden Nails'}


def _deepseek_rounds(n, fail_after=None):
    """Thay _call_deepseek_with_tools: n vòng gọi ai_deepseek_client THẬT (như vòng Function Calling), không qua gateway."""
    def run(messages, temperature, max_tokens, business_id, customer_id, api_key, tools=None):
        result = None
        for i in range(n):
            if fail_after is not None and i == fail_after:
                raise RuntimeError('DeepSeek down mid-loop')
            result = ai_deepseek_client.deepseek_chat_completion({'model': 'deepseek-chat', 'messages': messages},
                                                                 business_id=business_id, direct_api_key=api_key)
        result['tools_used'] = []
        return result
    return run


INBOX = types.SimpleNamespace(record=MagicMock(return_value='biz-ess:sms:+61400000001'), ai_auto_reply_on=MagicMock(return_value=True),
                              plain_text=lambda s: s, CHANNELS={'sms': {'label': 'SMS'}, 'messenger': {'label': 'Messenger'}})
NS = {
    'db': DB, 'request': request, 'session': session, 'jsonify': jsonify, 'os': os, 're': re, 'time': time, 'json': json,
    'datetime': datetime, 'timedelta': timedelta, 'requests': requests,
    'AIContextEngine': types.SimpleNamespace(build_context_prompt=_ctx_prompt),
    'compose_booking_assistant_prompt': lambda *a, **k: 'SYSTEM', 'compose_system_prompt': lambda *a, **k: 'SYSTEM',
    'classify_objection': MagicMock(return_value=None), 'get_conversation_memory': MagicMock(return_value=''),
    'maybe_distill_memory_async': MagicMock(), 'BOOKING_TOOLS': ai_function_tools.BOOKING_TOOLS, 'SALES_TOOLS': ai_function_tools.SALES_TOOLS,
    '_booking_assistant_facts': lambda *a, **k: 'FACTS', '_persist_chat_turn': MagicMock(), '_paused_holding_reply': MagicMock(return_value=''),
    '_booking_chat_history': lambda *a, **k: [], '_load_recent_chat_history': lambda *a, **k: [],
    '_call_deepseek_with_tools': _deepseek_rounds(2), 'SAAS_PLANS': {}, 'SAAS_CURRENCIES': {},
    'inbox_channels': INBOX, '_inbox_walkin': lambda b: 'Client', '_inbox_ai_throttled': lambda cid: False,
    '_vi_en': lambda vi, en: en,
}
for node in _TREE.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in _ASSIGNS for t in node.targets):
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'app.py', 'exec'), NS)
for name in _FUNCS:
    node = next(n for n in _TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), f'app.py::{name}', 'exec'), NS)

FLASK = Flask(__name__)
FLASK.secret_key = 'unit-test'


def _reset():
    DB.reset()
    plans._PLAN_CACHE.clear()
    booking_rules._CACHE.clear()
    FAKE.calls.clear()
    FAKE.retries_seen.clear()
    FAKE.script.clear()
    DB.businesses.insert_one({'id': 'biz-ess', 'name': 'Essential Nails', 'plan': 'essential', 'industry_code': 'nail',
                              'phone': '+61 2 9000 0001', 'country': 'AU', 'currency': 'AUD'})
    DB.businesses.insert_one({'id': 'biz-pro', 'name': 'Pro Nails', 'plan': 'pro', 'industry_code': 'nail', 'country': 'AU'})
    DB.businesses.insert_one({'id': 'biz-old', 'name': 'Old Salon', 'industry_code': 'nail'})   # chưa có gói = Empire
    DB.businesses.insert_one({'id': 'biz-vn', 'name': 'Tiệm Hoa', 'plan': 'essential', 'country': 'VN', 'currency': 'VND'})


def _usage(**flt):
    return list(DB.ai_usage.find(flt))


# ================================================================ 1. gateway: sổ token thật + thử lại
class GatewayChatTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_chat_records_real_usage_and_cost(self):
        out = ai_gateway.chat('studio_text', 'biz-pro', {'model': 'deepseek-chat', 'messages': []})
        self.assertEqual(out['choices'][0]['message']['content'], 'hello')
        rows = _usage()
        self.assertEqual(len(rows), 1, 'chat() ghi 1 dòng, client không ghi thêm dòng thứ 2')
        r = rows[0]
        self.assertEqual((r['business_id'], r['feature'], r['kind'], r['prompt_tokens'], r['completion_tokens'],
                          r['cache_hit_tokens'], r['units'], r['usage_missing']), ('biz-pro', 'studio_text', 'text', 2000, 100, 1500, 2100, 0))
        self.assertAlmostEqual(r['cost_usd'], COST_ONE_CALL, places=12)
        self.assertIsNotNone(r['created_at'].tzinfo)
        self.assertEqual(FAKE.retries_seen, [0], 'gateway tắt thử lại của SDK (tự quyết thử lại)')

    def test_missing_usage_is_flagged_not_invented(self):
        row = ai_gateway.usage_row('inbox_reply', 'b', {'choices': []}, {'model': 'deepseek-chat'})
        self.assertEqual((row['prompt_tokens'], row['completion_tokens'], row['cost_usd'], row['usage_missing']), (0, 0, 0.0, 1))
        row = ai_gateway.usage_row('weird-feature', 'b', {'usage': {'prompt_tokens': 10, 'completion_tokens': 5,
                                                                   'prompt_tokens_details': {'cached_tokens': 10}}})
        self.assertEqual((row['feature'], row['cache_hit_tokens']), ('other', 10))
        self.assertAlmostEqual(row['cost_usd'], (10 * 0.028 + 5 * 0.42) / 1e6, places=12)

    def test_retry_once_on_transient_only(self):
        FAKE.script[:] = [_Status(503)]
        ai_gateway.chat('studio_text', 'biz-pro', {'model': 'deepseek-chat', 'messages': []})
        self.assertEqual(len(FAKE.calls), 2, '503 -> thử lại 1 lần')
        self.assertEqual(len(_usage()), 1)
        FAKE.calls.clear()
        FAKE.script[:] = [_Status(429), _Status(500)]
        with self.assertRaises(RuntimeError):
            ai_gateway.chat('studio_text', 'biz-pro', {'model': 'deepseek-chat', 'messages': []})
        self.assertEqual(len(FAKE.calls), 2, 'tối đa 1 lần thử lại')
        for exc in (_Status(400), _Status(401), APITimeoutError('read timed out'), ValueError('bad')):
            FAKE.calls.clear()
            FAKE.script[:] = [exc]
            with self.assertRaises(RuntimeError):
                ai_gateway.chat('studio_text', 'biz-pro', {'model': 'deepseek-chat', 'messages': []})
            self.assertEqual(len(FAKE.calls), 1, f'không thử lại: {exc!r}')
        self.assertEqual(len(_usage()), 1, 'lệnh lỗi không ghi sổ')

    def test_transient_classifier(self):
        self.assertTrue(ai_gateway._transient(_wrapped(_Status(502))))
        self.assertTrue(ai_gateway._transient(_wrapped(requests.exceptions.ConnectionError('reset'))))
        self.assertFalse(ai_gateway._transient(_wrapped(requests.exceptions.ReadTimeout('slow'))))
        self.assertFalse(ai_gateway._transient(RuntimeError('DeepSeek down for this batch')))
        self.assertFalse(ai_gateway._transient(_wrapped(_Status(402))))

    def test_final_error_keeps_original_type(self):
        def boom(payload, **kw):
            raise requests.exceptions.Timeout('slow')
        with patch.object(ai_deepseek_client, 'deepseek_chat_completion', boom):
            with self.assertRaises(requests.exceptions.Timeout):
                ai_gateway.text('studio_text', 'biz-pro', 's', 'u')

    def test_direct_client_calls_use_open_scope_once(self):
        with ai_gateway.scope('inbox_reply', 'biz-pro'):
            ai_deepseek_client.deepseek_chat_completion({'model': 'deepseek-chat', 'messages': []}, direct_api_key='unit-test-key')
            ai_deepseek_client.deepseek_chat_completion({'model': 'deepseek-chat', 'messages': []}, direct_api_key='unit-test-key')
            totals = ai_gateway.run_totals()
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('inbox_reply', 'biz-pro')] * 2)
        self.assertEqual((totals['ai_calls'], totals['prompt_tokens'], totals['completion_tokens']), (2, 4000, 200))
        self.assertIsNone(ai_gateway._SCOPE.get(), 'phạm vi đóng lại sau with')
        self.assertEqual(ai_gateway.run_totals(), {})
        # ngoài phạm vi: vẫn vào sổ (tính năng 'other') với business_id truyền cho client
        ai_deepseek_client.deepseek_chat_completion({'model': 'deepseek-chat', 'messages': []}, business_id='biz-old',
                                                    direct_api_key='unit-test-key')
        self.assertEqual((_usage()[-1]['feature'], _usage()[-1]['business_id']), ('other', 'biz-old'))
        self.assertEqual(FAKE.retries_seen, [], 'gọi thẳng client giữ nguyên thử lại mặc định của SDK')

    def test_require_plan(self):
        with self.assertRaises(ai_gateway.AIPlanBlocked):
            ai_gateway.chat('inbox_reply', 'biz-ess', {'model': 'deepseek-chat', 'messages': []}, require='ai_inbox')
        self.assertEqual(FAKE.calls, [])
        self.assertTrue(issubclass(ai_gateway.AIPlanBlocked, RuntimeError))

    def test_untagged_call_in_known_route_uses_route_and_session_shop(self):
        if 'api_ai_copilot' not in FLASK.view_functions:
            FLASK.add_url_rule('/api/ai/copilot', 'api_ai_copilot', lambda: '', methods=['POST'])
        with FLASK.test_request_context('/api/ai/copilot', method='POST'):
            session['user_id'], session['business_id'] = 'u1', 'biz-old'
            ai_deepseek_client.deepseek_chat_completion({'model': 'deepseek-chat', 'messages': []}, direct_api_key='unit-test-key')
        r = _usage()[-1]
        self.assertEqual((r['feature'], r['business_id'], r['endpoint']), ('copilot', 'biz-old', 'api_ai_copilot'))

    def test_hook_never_opens_a_db_connection_itself(self):
        saved = sys.modules.pop('mongo_client')
        try:
            with patch.dict(sys.modules, {'mongo_client': None}):   # import mongo_client sẽ lỗi nếu bị gọi
                self.assertIsNone(ai_gateway._db(load=False))
                row = ai_gateway.on_client_completion({'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}, None, 'b')
            self.assertEqual(row['prompt_tokens'], 1)
        finally:
            sys.modules['mongo_client'] = saved


# ================================================================ 2. cổng gói lúc chạy
class PlanGateTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_allowed_by_plan_with_grandfathering(self):
        self.assertFalse(ai_gateway.allowed('biz-ess', 'ai_inbox'))
        self.assertFalse(ai_gateway.allowed('biz-ess', 'booking_chat'))   # tính năng ghi sổ -> ai_inbox
        self.assertTrue(ai_gateway.allowed('biz-pro', 'ai_inbox'))
        self.assertFalse(ai_gateway.allowed('biz-pro', 'ai_copilot'))
        self.assertTrue(ai_gateway.allowed('biz-old', 'ai_copilot'), 'tiệm cũ chưa có gói = Empire')
        self.assertTrue(ai_gateway.allowed('biz-missing', 'ai_inbox'))
        self.assertTrue(ai_gateway.allowed('biz-ess', 'sales_bot'))   # không khoá
        self.assertTrue(plans.business_allows(DB, 'biz-pro', 'ai_inbox'))

    def test_downgrade_stops_ai_within_cache_ttl(self):
        self.assertTrue(ai_gateway.allowed('biz-pro', 'ai_inbox'))
        DB.businesses.update_one({'id': 'biz-pro'}, {'$set': {'plan': 'essential'}})
        self.assertTrue(ai_gateway.allowed('biz-pro', 'ai_inbox'), 'trong 60 giây vẫn dùng gói đã cache')
        plan, at = plans._PLAN_CACHE['biz-pro']
        plans._PLAN_CACHE['biz-pro'] = (plan, at - ai_gateway.CACHE_TTL - 1)
        self.assertFalse(ai_gateway.allowed('biz-pro', 'ai_inbox'), 'hết TTL -> gói mới có hiệu lực')
        self.assertEqual(ai_gateway.CACHE_TTL, 60)


# ================================================================ 3. secure_ai_generate
def _booking_request(bid, msg='Hi, can I book a gel manicure?', path='/api/ai/studio/generate', **extra):
    body = {'business_id': bid, 'context': 'customer_booking', 'customer_message': msg, 'userPrompt': msg,
            'customer_phone': '+61400000009', 'chat_token': 'a' * 32, **extra}
    return FLASK.test_request_context(path, method='POST', json=body)


class BookingChatGateTests(unittest.TestCase):
    def setUp(self):
        _reset()
        NS['_call_deepseek_with_tools'] = _deepseek_rounds(2)
        NS['_persist_chat_turn'].reset_mock()

    def test_essential_booking_page_gets_no_ai_fallback(self):
        with _booking_request('biz-ess'):
            resp = NS['secure_ai_generate']()
            data = resp.get_json()
        self.assertTrue(data['ai_unavailable'])
        self.assertEqual(data['reason'], 'plan')
        self.assertEqual(data['contact'], {'name': 'Essential Nails', 'phone': '+61 2 9000 0001'})
        text = data['choices'][0]['message']['content']
        self.assertIn('form on this page', text)
        self.assertIn('+61 2 9000 0001', text)
        self.assertNotIn('AI', text)
        self.assertEqual(FAKE.calls, [], 'không gọi DeepSeek')
        self.assertEqual(_usage(), [])
        NS['_persist_chat_turn'].assert_not_called()

    def test_vietnamese_fallback(self):
        with _booking_request('biz-vn', msg='chị muốn làm móng'):
            data = NS['secure_ai_generate']().get_json()
        self.assertEqual(data['lang'], 'vi')
        self.assertIn('đặt lịch được bằng form', data['choices'][0]['message']['content'])
        with _booking_request('biz-vn', msg=''):
            self.assertEqual(NS['secure_ai_generate']().get_json()['lang'], 'vi')   # không có tin -> theo nước của tiệm

    def test_pro_booking_chat_runs_and_logs_every_round(self):
        with _booking_request('biz-pro'):
            data = NS['secure_ai_generate']().get_json()
        self.assertNotIn('ai_unavailable', data)
        self.assertEqual(data['choices'][0]['message']['content'], 'hello')
        rows = _usage()
        self.assertEqual([(r['feature'], r['business_id']) for r in rows], [('booking_chat', 'biz-pro')] * 2)
        run = DB.ai_runs.find_one({'persona': 'booking'})
        self.assertEqual((run['ai_calls'], run['prompt_tokens'], run['completion_tokens']), (2, 4000, 200))
        self.assertAlmostEqual(run['cost_usd'], 2 * COST_ONE_CALL, places=10)

    def test_grandfathered_shop_keeps_ai(self):
        with _booking_request('biz-old'):
            data = NS['secure_ai_generate']().get_json()
        self.assertNotIn('ai_unavailable', data)
        self.assertEqual(len(_usage(business_id='biz-old')), 2)

    def test_sales_bot_cost_is_not_billed_to_a_shop(self):
        body = {'business_id': 'biz-pro', 'userPrompt': 'how much is BitPaw?', 'industry': 'nail'}
        with FLASK.test_request_context('/api/ai/studio/generate', method='POST', json=body):
            NS['secure_ai_generate']()
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('sales_bot', None)] * 2)

    def test_mid_loop_failure_still_logs_paid_rounds(self):
        NS['_call_deepseek_with_tools'] = _deepseek_rounds(3, fail_after=1)
        with _booking_request('biz-pro'):
            data = NS['secure_ai_generate']().get_json()
        self.assertTrue(data['fallback'])
        self.assertEqual(len(_usage(feature='booking_chat')), 1)


# ================================================================ 4. hộp thư + SMS
class InboxGateTests(unittest.TestCase):
    def setUp(self):
        _reset()
        NS['_call_deepseek_with_tools'] = _deepseek_rounds(2)
        INBOX.record.reset_mock()

    def test_downgraded_inbox_marks_needs_human_without_ai(self):
        DB.bot_customers.insert_one({'id': 'biz-ess:messenger:42', 'business_id': 'biz-ess', 'channel': 'messenger'})
        with FLASK.test_request_context('/webhooks/inbox/messenger/k', method='POST'):
            reply, failed = NS['_inbox_ai_reply']('biz-ess', 'biz-ess:messenger:42', 'hello?')
        self.assertEqual((reply, failed), ('', False))
        bc = DB.bot_customers.find_one({'id': 'biz-ess:messenger:42'})
        self.assertTrue(bc['needs_human'])
        self.assertIn('plan', bc['handoff_reason'])
        self.assertEqual(FAKE.calls, [])
        self.assertEqual(_usage(), [])

    def test_pro_inbox_and_sms_log_by_channel(self):
        DB.bot_customers.insert_one({'id': 'biz-pro:messenger:7', 'business_id': 'biz-pro', 'channel': 'messenger'})
        DB.bot_customers.insert_one({'id': 'biz-pro:sms:+61400000002', 'business_id': 'biz-pro', 'channel': 'sms', 'phone': '+61400000002'})
        reply, failed = NS['_inbox_ai_reply']('biz-pro', 'biz-pro:messenger:7', 'hi')   # ngoài request (worker) cũng được
        self.assertEqual((reply, failed), ('hello', False))
        NS['_inbox_ai_reply']('biz-pro', 'biz-pro:sms:+61400000002', 'hi')
        self.assertEqual([r['feature'] for r in _usage()], ['inbox_reply', 'inbox_reply', 'sms_reply', 'sms_reply'])
        self.assertIsNone(ai_gateway._SCOPE.get(), 'phạm vi ghi sổ không rò sang lượt sau')
        runs = list(DB.ai_runs.find({'persona': 'booking'}))
        self.assertEqual([r['ai_calls'] for r in runs], [2, 2])

    def test_inbox_error_resets_scope(self):
        DB.bot_customers.insert_one({'id': 'biz-pro:messenger:8', 'business_id': 'biz-pro', 'channel': 'messenger'})
        NS['_call_deepseek_with_tools'] = _deepseek_rounds(3, fail_after=1)
        self.assertEqual(NS['_inbox_ai_reply']('biz-pro', 'biz-pro:messenger:8', 'hi'), ('', True))
        self.assertEqual(len(_usage(feature='inbox_reply')), 1)
        self.assertIsNone(ai_gateway._SCOPE.get())
        self.assertEqual(DB.ai_runs.find_one({'fallback': True})['ai_calls'], 1)

    def test_downgraded_sms_stores_message_only(self):
        DB.bot_customers.insert_one({'id': 'biz-ess:sms:+61400000001', 'business_id': 'biz-ess', 'channel': 'sms'})
        out = NS['_inbox_sms_inbound']('biz-ess', '+61400000001', 'can I book tomorrow?')
        self.assertEqual(out, '')
        INBOX.record.assert_called_once()
        self.assertEqual(INBOX.record.call_args[0][3], 'can I book tomorrow?')
        bc = DB.bot_customers.find_one({'id': 'biz-ess:sms:+61400000001'})
        self.assertTrue(bc['needs_human'])
        self.assertEqual(bc['handoff_reason'], ai_gateway.PLAN_PAUSED_REASON)
        self.assertEqual(FAKE.calls, [])


# ================================================================ 5. /api/ai/usage
class UsageApiTests(unittest.TestCase):
    def setUp(self):
        _reset()
        utc = timezone.utc
        rows = [
            # 31/10 14:00 UTC = 01/11 01:00 giờ Sydney -> thuộc tháng 11 của tiệm
            {'feature': 'booking_chat', 'kind': 'text', 'prompt_tokens': 1000, 'completion_tokens': 100, 'cost_usd': 0.0003,
             'units': 1100, 'usage_missing': 0, 'created_at': datetime(2026, 10, 31, 14, 0, tzinfo=utc)},
            {'feature': 'booking_chat', 'kind': 'text', 'prompt_tokens': 500, 'completion_tokens': 50, 'cost_usd': 0.0002,
             'units': 550, 'usage_missing': 0, 'created_at': datetime(2026, 10, 10, 3, 0, tzinfo=utc)},
            {'feature': 'booking_chat', 'kind': 'text', 'prompt_tokens': 0, 'completion_tokens': 0, 'cost_usd': 0.0,
             'units': 0, 'usage_missing': 1, 'created_at': datetime(2026, 10, 11, 3, 0, tzinfo=utc)},
            {'feature': 'sms_reply', 'kind': 'text', 'prompt_tokens': 300, 'completion_tokens': 30, 'cost_usd': 0.0001,
             'units': 330, 'usage_missing': 0, 'created_at': datetime(2026, 10, 12, 3, 0, tzinfo=utc)},
            {'kind': 'text', 'units': 2000, 'cost_usd': 0.0, 'created_at': datetime(2026, 10, 12, 4, 0, tzinfo=utc)},   # dòng cũ
            {'kind': 'image', 'units': 1, 'cost_usd': 0.04, 'job_id': 1, 'created_at': datetime(2026, 10, 13, 3, 0, tzinfo=utc)},
            {'kind': 'image', 'units': 1, 'cost_usd': 0.04, 'job_id': 2, 'qa_test': True, 'created_at': datetime(2026, 10, 13, 4, 0, tzinfo=utc)},
        ]
        for r in rows:
            DB.ai_usage.insert_one(dict(r, business_id='biz-pro'))
        DB.ai_usage.insert_one({'business_id': 'biz-ess', 'feature': 'booking_chat', 'kind': 'text', 'prompt_tokens': 9, 'completion_tokens': 9,
                                'cost_usd': 9.0, 'created_at': datetime(2026, 10, 10, 3, 0, tzinfo=utc)})

    def _get(self, qs, role='admin', bid='biz-pro'):
        with FLASK.test_request_context('/api/ai/usage' + qs):
            session['user_id'], session['business_id'], session['role'] = 'u1', bid, role
            resp = NS['api_ai_usage']()
        if isinstance(resp, tuple):
            return resp[1], resp[0].get_json()
        return resp.status_code, resp.get_json()

    def test_staff_cannot_read_costs(self):
        code, data = self._get('?month=2026-10', role='staff')
        self.assertEqual((code, data['code']), (403, 'owner_only'))

    def test_bad_month(self):
        for m in ('2026-13', 'oct', '2026-1', '1999-01'):
            code, data = self._get(f'?month={m}')
            self.assertEqual((code, data['code']), (400, 'bad_month'), m)

    def test_month_totals_per_feature_in_shop_timezone(self):
        code, data = self._get('?month=2026-10')
        self.assertEqual(code, 200)
        self.assertTrue(data['success'])
        self.assertEqual((data['month'], data['timezone'], data['currency'], data['plan']), ('2026-10', 'Australia/Sydney', 'USD', 'pro'))
        by = {r['feature']: r for r in data['text']}
        self.assertEqual(set(by), {'booking_chat', 'sms_reply'})
        bc = by['booking_chat']
        self.assertEqual((bc['calls'], bc['prompt_tokens'], bc['completion_tokens'], bc['calls_without_usage']), (2, 500, 50, 1))
        self.assertAlmostEqual(bc['cost_usd'], 0.0002)
        self.assertTrue(bc['label_vi'] and bc['label_en'])
        self.assertEqual(data['untracked_text_calls'], 1)
        self.assertEqual([(m['kind'], m['jobs'], m['units']) for m in data['media']], [('image', 1, 1)], 'bỏ dòng qa_test')
        self.assertEqual(data['totals']['calls'], 3)
        self.assertAlmostEqual(data['totals']['cost_usd'], 0.0002 + 0.0001 + 0.04)
        self.assertTrue(data['ai_replies_enabled'])
        code, nov = self._get('?month=2026-11')
        self.assertEqual([(r['feature'], r['calls']) for r in nov['text']], [('booking_chat', 1)], '31/10 UTC = 1/11 ở Sydney')

    def test_other_shop_rows_never_leak(self):
        code, data = self._get('?month=2026-10', bid='biz-ess')
        self.assertEqual([(r['feature'], r['calls']) for r in data['text']], [('booking_chat', 1)])
        self.assertFalse(data['ai_replies_enabled'])
        self.assertEqual(data['plan'], 'essential')

    def test_default_month_is_current_shop_month(self):
        label, tz, start, end = ai_gateway.month_window('biz-pro', now=datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc))
        self.assertEqual(label, '2026-11')
        self.assertEqual(start, datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc))   # 1/11 00:00 AEDT


# ================================================================ 6. callers + giả lập đặt lịch
class CallerAndSimTests(unittest.TestCase):
    def test_owned_text_calls_go_through_gateway(self):
        src = {f: _read(f) for f in ('ai_studio_bp.py', 'social_planner.py')}
        self.assertNotIn('log_text_usage', src['ai_studio_bp.py'], 'ghi max_tokens xin + chi phí 0 đã thay bằng token thật')
        self.assertNotIn('ai_media.deepseek_text', src['ai_studio_bp.py'])
        self.assertIn("ai_gateway.text('studio_scene_plan'", src['ai_studio_bp.py'])
        self.assertNotIn('deepseek_chat_completion', src['social_planner.py'])
        self.assertIn("ai_gateway.chat(\n            'social_plan'", src['social_planner.py'].replace('\r\n', '\n'))
        self.assertIn("feature='social_review'", src['social_planner.py'])

    def test_sim_booking_sends_chat_token_and_tags_seed(self):
        _reset()
        sys.modules['sim_core'] = types.SimpleNamespace(BASE='http://127.0.0.1:5001', Pacer=object, browser_session=None,
                                                        csrf_from=None, db=DB, judge=None, run_conversation=None, summarize=None)
        sys.path.insert(0, os.path.join(ROOT, 'scripts', 'ai_sim'))
        import sim_booking
        tok = sim_booking.new_chat_token()
        self.assertEqual(ai_function_tools.chat_token_hash(tok), sim_booking.chat_token_hash(tok), 'cùng mã băm với Phase 0')
        now = datetime(2026, 10, 26, 10, 0)
        body = sim_booking.booking_payload('biz-pro', 'nail', '+61491570001', now, 'hi', [], tok)
        self.assertEqual((body['chat_token'], body['context'], body['customer_message']), (tok, 'customer_booking', 'hi'))
        aid = sim_booking.seed_appt('biz-pro', '+61491570001', {'id': 1, 'name': 'Gel'}, now + timedelta(days=3), chat_token=tok)
        appt = DB.appointments.find_one({'id': aid})
        # đúng điều kiện chat web của Phase 0 (ai_function_tools._ownership_filter): SĐT + mã băm của trình duyệt này
        with ai_function_tools.chat_scope(tok):
            own = ai_function_tools._ownership_filter('biz-pro:+61491570001')
        self.assertTrue(ai_function_tools._matches(appt, own), (appt, own))
        with ai_function_tools.chat_scope(sim_booking.new_chat_token()):
            other = ai_function_tools._ownership_filter('biz-pro:+61491570001')
        self.assertFalse(ai_function_tools._matches(appt, other), 'trình duyệt khác không đụng được lịch này')


if __name__ == '__main__':
    unittest.main(verbosity=1)
