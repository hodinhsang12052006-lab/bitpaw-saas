# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 1 follow-up "mọi lệnh DeepSeek còn lại đi qua ai_gateway + cổng gói":
  1) ai_gateway: feature=None ghi theo phạm vi caller; bot bán BitPaw không bao giờ vào sổ tiệm; tiệm trong phiên làm cổng
     gói khi không truyền business_id; deadline (webhook SMS) cắt thời gian chờ + không thử lại khi hết giờ;
  2) app._call_deepseek_with_tools: mỗi vòng 1 dòng sổ đúng phạm vi; đường SMS (Twilio ~15 giây) hạn chót 10 giây, mỗi lệnh
     <= 8 giây — chạy THẬT qua _inbox_ai_reply kênh SMS: hết giờ -> ('', True), không treo;
  3) app.api_ai_copilot: insight (vòng công cụ) + reply đều qua gateway, sổ 'copilot', _log_ai_run kèm tổng token;
  4) app._generate_restock_reason_with_ai: gói không có 'inventory' -> câu mẫu, KHÔNG gọi AI, không ghi ai_runs;
  5) ai_sales_prompts.classify_objection: qua gateway, 8 giây, không thử lại, sổ 'sales_bot' không gắn tiệm;
  6) ai_media.prompt_from_text: đúng 1 dòng sổ token thật, không còn dòng log_text_usage(…, 300);
  7) ai_memory_engine / ai_nurturing_engine / nurture_scheduler: cổng gói (ai_inbox / crm_ai), tiệm cũ chưa có gói = Empire;
  8) messaging.missed_call_reply đã xoá (không ai gọi); shift_roster + sim_copilot dùng ai_copilot_tools.REVENUE_STATUSES.

KHÔNG mở MongoDB thật (mongo_client giả trước mọi import), KHÔNG gọi DeepSeek/mạng (ai_deepseek_client giả, requests chặn),
KHÔNG import app.py (lấy hàm qua ast), KHÔNG chạy Flask server.
Chạy: python scripts/tests/test_phase1_gateway_followups.py
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
def _match_value(v, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith('$') for k in cond):
        for op, arg in cond.items():
            if op == '$in' and v not in arg:
                return False
            if op == '$nin' and v in arg:
                return False
            if op == '$ne' and v == arg:
                return False
            if op in ('$gte', '$gt', '$lt', '$lte'):
                if v is None or not {'$gte': v >= arg, '$gt': v > arg, '$lt': v < arg, '$lte': v <= arg}[op]:
                    return False
        return True
    return v == cond


def _matches(doc, flt):
    return all(_match_value(doc.get(k), c) for k, c in (flt or {}).items())


class _Cursor(list):
    def sort(self, key, direction=1):
        return _Cursor(sorted(self, key=lambda d: (d.get(key) is None, d.get(key) or ''), reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return types.SimpleNamespace(inserted_id=len(self.docs))

    def find(self, flt=None, projection=None):
        return _Cursor(dict(d) for d in self.docs if _matches(d, flt))

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
        if upsert:
            self.insert_one({**flt, **(update.get('$set') or {})})
        return types.SimpleNamespace(matched_count=0)


class FakeDB:
    def __init__(self):
        self.__dict__['_c'] = {}

    def __getattr__(self, name):
        return self._c.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return getattr(self, name)

    def reset(self):
        self._c.clear()


DB = FakeDB()
_ids = count(7000)
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED')
_msg = types.ModuleType('messaging')
_msg.get_settings = lambda bid: {'timezone': 'Australia/Sydney', 'language': 'en'}
_msg.normalize_channel = lambda ch, default=None: (ch or default)
sys.modules['messaging'] = _msg
_be = types.ModuleType('booking_engine')
_be.book_appointment = MagicMock(side_effect=AssertionError('no booking in this test'))
_be.SlotAlreadyBookedError = type('SlotAlreadyBookedError', (Exception,), {})
sys.modules['booking_engine'] = _be
_ace = types.ModuleType('ai_context_engine')
_ace.AIContextEngine = types.SimpleNamespace(_load_purchase_history=lambda *a, **k: [],
                                             build_context_prompt=lambda *a, **k: {'prompt': 'TENANT', 'business_name': 'Pro Nails'})
sys.modules['ai_context_engine'] = _ace
_fake_app = types.ModuleType('app')   # shift_roster: from app import login_required, role_required
_fake_app.login_required = lambda f: f
_fake_app.role_required = lambda *a, **k: (lambda f: f)
sys.modules['app'] = _fake_app


# ---------------------------------------------------------------- DeepSeek giả (module ai_deepseek_client trong sys.modules)
class FakeClock:
    """Đồng hồ giả cho time.monotonic/sleep của gateway + app: mỗi lệnh DeepSeek giả 'tốn' step giây."""
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeDeepSeek:
    def __init__(self):
        self.calls, self.script, self.step, self.clock = [], [], 0.0, None

    def __call__(self, payload, **kw):
        self.calls.append((payload, kw))
        if self.clock is not None:
            self.clock.t += self.step
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            msg = step
        else:
            msg = {'role': 'assistant', 'content': 'hello'}
        return {'model': 'deepseek-chat', 'choices': [{'message': msg}],
                'usage': {'prompt_tokens': 1000, 'completion_tokens': 50, 'prompt_cache_hit_tokens': 0}}


DS = FakeDeepSeek()
_ds_mod = types.ModuleType('ai_deepseek_client')
_ds_mod.deepseek_chat_completion = DS
sys.modules['ai_deepseek_client'] = _ds_mod


def _no_network(*a, **kw):
    raise AssertionError('network disabled in offline tests')


patch('requests.sessions.Session.request', _no_network).start()

from flask import Flask, jsonify, request, session  # noqa: E402
import requests  # noqa: E402

import plans  # noqa: E402
import ai_gateway  # noqa: E402
import ai_function_tools  # noqa: E402
import booking_rules  # noqa: E402
import ai_copilot_tools  # noqa: E402
import ai_memory_engine  # noqa: E402
import ai_nurturing_engine  # noqa: E402
import nurture_scheduler  # noqa: E402
import shift_roster  # noqa: E402
from ai_nurturing_engine import AINurturingEngine  # noqa: E402
from ai_sales_prompts import classify_objection  # noqa: E402
from currency_utils import format_money  # noqa: E402


def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def _func_src(rel, name):
    src = _read(rel)
    node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, node)


# ---------------------------------------------------------------- hàm của app.py (qua ast, bỏ decorator)
APP_SRC = _read('app.py')
_TREE = ast.parse(APP_SRC)
_FUNCS = ('_call_deepseek_with_tools', '_inbox_ai_reply', '_log_ai_run', 'api_ai_copilot', '_shop_lang_currency', '_fmt_num',
          '_restock_reason_template', '_restock_ai_text_ok', '_generate_restock_reason_with_ai')
_ASSIGNS = ('_VI_CHARS_RE', '_VI_WORDS_RE', '_VI_DIACRITIC_RE')
CLOCK = FakeClock()
FAKE_TIME = types.SimpleNamespace(monotonic=CLOCK.monotonic, time=CLOCK.time, sleep=CLOCK.sleep)
TOOL_RESULTS = []


def _exec_tool(tool_call, business_id=None, customer_id=None, allowed=None):
    TOOL_RESULTS.append((tool_call['function']['name'], business_id))
    return tool_call.get('id'), json.dumps({'success': True, 'slots': ['10:00']})


NS = {
    'db': DB, 'request': request, 'session': session, 'jsonify': jsonify, 'os': os, 're': re, 'time': time, 'json': json,
    'datetime': datetime, 'timedelta': timedelta, 'timezone': timezone, 'requests': requests, 'plans': plans,
    'format_money': format_money, 'TOOL_SCHEMAS': ai_function_tools.BOOKING_TOOLS, 'BOOKING_TOOLS': ai_function_tools.BOOKING_TOOLS,
    'execute_tool_call': _exec_tool, 'AIContextEngine': _ace.AIContextEngine,
    'compose_booking_assistant_prompt': lambda *a, **k: 'SYSTEM', '_booking_assistant_facts': lambda *a, **k: 'FACTS',
    '_paused_holding_reply': MagicMock(return_value=''), '_vi_en': lambda vi, en: en,
    'inbox_channels': types.SimpleNamespace(plain_text=lambda s: s, CHANNELS={'sms': {'label': 'SMS'}, 'messenger': {'label': 'Messenger'}}),
    '_assert_owns_bot_customer': lambda cid, bid: True,
    'deepseek_chat_completion': MagicMock(side_effect=AssertionError('app.py must not call ai_deepseek_client directly')),
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
    DS.calls.clear()
    DS.script.clear()
    DS.step, DS.clock = 0.0, None
    TOOL_RESULTS.clear()
    NS['time'] = time
    DB.businesses.insert_one({'id': 'biz-ess', 'name': 'Essential Nails', 'plan': 'essential', 'industry_code': 'nail', 'country': 'AU'})
    DB.businesses.insert_one({'id': 'biz-pro', 'name': 'Pro Nails', 'plan': 'pro', 'industry_code': 'nail', 'country': 'AU'})
    DB.businesses.insert_one({'id': 'biz-old', 'name': 'Old Salon', 'industry_code': 'nail', 'country': 'US'})   # chưa có gói = Empire


def _usage(**flt):
    return list(DB.ai_usage.find(flt))


def _tool_call(name='check_availability', cid='call_1'):
    return {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}]}


class _Status(Exception):
    def __init__(self, code):
        super().__init__(f'HTTP {code}')
        self.status_code = code


# ================================================================ 1. gateway: phạm vi, bot BitPaw, tiệm trong phiên, deadline
class GatewayLedgerTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_feature_none_follows_open_scope_and_client_still_gets_shop(self):
        with ai_gateway.scope('sms_reply', 'biz-pro'):
            self.assertEqual(ai_gateway.current_feature(), 'sms_reply')
            ai_gateway.chat(None, 'biz-pro', {'model': 'deepseek-chat', 'messages': []})
        self.assertIsNone(ai_gateway.current_feature())
        self.assertEqual([(r['feature'], r['business_id'], r['prompt_tokens']) for r in _usage()], [('sms_reply', 'biz-pro', 1000)])
        self.assertEqual(DS.calls[0][1]['business_id'], 'biz-pro')

    def test_sales_bot_never_billed_to_a_shop(self):
        with FLASK.test_request_context('/api/ai/studio/generate', method='POST'):
            session['user_id'] = session['business_id'] = 'biz-pro'
            ai_gateway.tag_request('sales_bot', None)
            ai_gateway.chat(None, 'biz-pro', {'model': 'deepseek-chat', 'messages': []})   # vòng công cụ: tiệm chỉ cho Proxy
        with FLASK.test_request_context('/x', method='POST'):
            session['user_id'] = session['business_id'] = 'biz-pro'
            ai_gateway.chat('sales_bot', 'biz-pro', {'model': 'deepseek-chat', 'messages': []})   # không phạm vi vẫn không gắn tiệm
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('sales_bot', None)] * 2)
        self.assertEqual([kw['business_id'] for _p, kw in DS.calls], ['biz-pro', 'biz-pro'])

    def test_session_shop_is_the_gate_when_no_business_id_given(self):
        for bid, ok in (('biz-ess', False), ('biz-pro', True), ('biz-old', True)):
            with FLASK.test_request_context('/api/ai/nurture/generate-campaign', method='POST'):
                session['user_id'] = session['business_id'] = bid
                if ok:
                    ai_gateway.chat('nurture', None, {'model': 'deepseek-chat', 'messages': []}, require='crm_ai')
                else:
                    with self.assertRaises(ai_gateway.AIPlanBlocked):
                        ai_gateway.chat('nurture', None, {'model': 'deepseek-chat', 'messages': []}, require='crm_ai')
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('nurture', 'biz-pro'), ('nurture', 'biz-old')])
        self.assertEqual(len(DS.calls), 2, 'tiệm Essential: không gọi AI')

    def test_new_features_map_to_plan_features(self):
        self.assertEqual({f: ai_gateway.plan_feature(f) for f in ('restock_reason', 'nurture', 'chat_memory', 'sales_bot')},
                         {'restock_reason': 'inventory', 'nurture': 'crm_ai', 'chat_memory': 'ai_inbox', 'sales_bot': None})
        for f in ('restock_reason', 'nurture', 'chat_memory'):
            lab = ai_gateway.USAGE_FEATURES[f]
            self.assertTrue(lab[1] and lab[2] and lab[1] != lab[2], 'nhãn VI + EN')
            self.assertFalse(ai_gateway.allowed('biz-ess', f))
            self.assertTrue(ai_gateway.allowed('biz-old', f), 'tiệm cũ chưa có gói = Empire')

    def test_deadline_caps_each_call_and_stops_when_no_time_left(self):
        with patch.object(ai_gateway, 'time', FAKE_TIME):
            ai_gateway.chat('sms_reply', 'biz-pro', {'model': 'deepseek-chat', 'messages': []}, timeout=8, deadline=CLOCK.t + 5)
            self.assertEqual(DS.calls[-1][1]['timeout'], 5, 'chỉ chờ phần thời gian còn lại')
            ai_gateway.chat('sms_reply', 'biz-pro', {'model': 'deepseek-chat', 'messages': []}, timeout=8, deadline=CLOCK.t + 30)
            self.assertEqual(DS.calls[-1][1]['timeout'], 8)
            n = len(DS.calls)
            with self.assertRaises(ai_gateway.AIUnavailable) as cm:
                ai_gateway.chat('sms_reply', 'biz-pro', {'model': 'deepseek-chat', 'messages': []}, timeout=8, deadline=CLOCK.t + 1)
            self.assertEqual(cm.exception.code, 'timeout')
            self.assertTrue(isinstance(cm.exception, RuntimeError))
            self.assertEqual(len(DS.calls), n, 'hết giờ: không gọi DeepSeek')
            # lỗi tạm thời nhưng không còn đủ giờ -> không thử lại, ném NGUYÊN lỗi
            DS.script[:] = [_Status(503)]
            with self.assertRaises(_Status):
                ai_gateway.chat('sms_reply', 'biz-pro', {'model': 'deepseek-chat', 'messages': []}, timeout=8, deadline=CLOCK.t + 2.2)
            self.assertEqual(len(DS.calls), n + 1)
            # còn nhiều giờ -> thử lại 1 lần như thường
            DS.script[:] = [_Status(503)]
            ai_gateway.chat('sms_reply', 'biz-pro', {'model': 'deepseek-chat', 'messages': []}, timeout=8, deadline=CLOCK.t + 20)
            self.assertEqual(len(DS.calls), n + 3)


# ================================================================ 2. vòng Function Calling + đường SMS
class ToolLoopTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_each_round_logged_once_under_caller_scope(self):
        DS.script[:] = [_tool_call(), {'role': 'assistant', 'content': 'We have 10:00 tomorrow.'}]
        with ai_gateway.scope('inbox_reply', 'biz-pro'):
            out = NS['_call_deepseek_with_tools']([{'role': 'user', 'content': 'tomorrow?'}], 0.4, 600, 'biz-pro', 'c1', 'unit-test-key')
        self.assertEqual(out['choices'][0]['message']['content'], 'We have 10:00 tomorrow.')
        self.assertEqual(out['tools_used'], [{'tool': 'check_availability', 'ok': True}])
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('inbox_reply', 'biz-pro')] * 2)
        self.assertEqual([kw['timeout'] for _p, kw in DS.calls], [45, 45], 'web/Messenger: thời gian chờ như cũ')
        self.assertEqual(TOOL_RESULTS, [('check_availability', 'biz-pro')])
        NS['deepseek_chat_completion'].assert_not_called()

    def test_sms_webhook_has_short_budget(self):
        NS['time'] = FAKE_TIME
        DS.clock, DS.step = CLOCK, 4.5          # mỗi vòng DeepSeek giả mất 4,5 giây
        DS.script[:] = [_tool_call(cid='a'), _tool_call(cid='b'), _tool_call(cid='c')]
        with patch.object(ai_gateway, 'time', FAKE_TIME), ai_gateway.scope('sms_reply', 'biz-pro'):
            with self.assertRaises(ai_gateway.AIUnavailable):
                NS['_call_deepseek_with_tools']([{'role': 'user', 'content': 'book me'}], 0.4, 600, 'biz-pro', 'c1', 'k')
        self.assertEqual([kw['timeout'] for _p, kw in DS.calls], [8, 5.5], 'tối đa 8 giây/lệnh, cả lượt <= 10 giây')
        self.assertEqual(len(_usage(feature='sms_reply')), 2, 'các vòng đã trả tiền vẫn vào sổ')

    def test_sms_inbox_reply_end_to_end_times_out_cleanly(self):
        DB.bot_customers.insert_one({'id': 'biz-pro:sms:+61400000009', 'business_id': 'biz-pro', 'channel': 'sms', 'phone': '+61400000009'})
        NS['time'] = FAKE_TIME
        DS.clock, DS.step = CLOCK, 6.0
        DS.script[:] = [_tool_call(cid='a'), _tool_call(cid='b')]
        with patch.object(ai_gateway, 'time', FAKE_TIME):
            reply, failed = NS['_inbox_ai_reply']('biz-pro', 'biz-pro:sms:+61400000009', 'can I come at 3?')
        self.assertEqual((reply, failed), ('', True), 'hết giờ -> báo chủ tiệm trả lời, không để Twilio cắt ngang')
        self.assertEqual([kw['timeout'] for _p, kw in DS.calls], [8, 4], '2 vòng (6 + 6 giây) rồi dừng ở mốc 10 giây')
        run = DB.ai_runs.find_one({'persona': 'booking'})
        self.assertTrue(run['fallback'])
        self.assertIn('No time left', run['error'])
        self.assertEqual(run['ai_calls'], 2)
        self.assertIsNone(ai_gateway._SCOPE.get())

    def test_sms_inbox_reply_fast_answer_goes_through(self):
        DB.bot_customers.insert_one({'id': 'biz-pro:sms:+61400000010', 'business_id': 'biz-pro', 'channel': 'sms', 'phone': '+61400000010'})
        reply, failed = NS['_inbox_ai_reply']('biz-pro', 'biz-pro:sms:+61400000010', 'open today?')
        self.assertEqual((reply, failed), ('hello', False))
        self.assertEqual([kw['timeout'] for _p, kw in DS.calls], [8])
        self.assertEqual([r['feature'] for r in _usage()], ['sms_reply'])

    def test_no_direct_client_call_left_in_tool_loop(self):
        src = _func_src('app.py', '_call_deepseek_with_tools')
        self.assertIn('ai_gateway.chat(None', src)
        self.assertNotIn('deepseek_chat_completion(', src)


# ================================================================ 3. AI Copilot
class CopilotTests(unittest.TestCase):
    def setUp(self):
        _reset()
        cop = types.ModuleType('ai_copilot')
        cop.business_snapshot = lambda bid, mode=None: ('SNAPSHOT', 'Old Salon', 'nail')
        cop.INSIGHT_TOPICS = {'revenue': 'How is revenue?'}
        cop.agent_messages = lambda snap, q, lang, today: [{'role': 'system', 'content': 'S'}, {'role': 'user', 'content': q}]
        cop.reply_messages = lambda snap, facts, convo: [{'role': 'system', 'content': 'S'}]
        tools = types.ModuleType('ai_copilot_tools')
        tools.COPILOT_TOOLS = []
        tools.run_tool = lambda bid, tc: '{"net": 1200}'
        br = types.ModuleType('booking_rules')
        br.local_now = lambda bid: datetime(2026, 10, 26, 9, 0)
        self.mods = {'ai_copilot': cop, 'ai_copilot_tools': tools, 'booking_rules': br}

    def _call(self, body):
        with patch.dict(sys.modules, self.mods), FLASK.test_request_context('/api/ai/copilot', method='POST', json=body):
            session['user_id'] = session['business_id'] = 'biz-old'
            session['role'] = 'admin'
            resp = NS['api_ai_copilot']()
            return resp if isinstance(resp, tuple) else (resp, 200)

    def test_insight_loop_goes_through_gateway_and_run_has_totals(self):
        DS.script[:] = [_tool_call('sales_report'), {'role': 'assistant', 'content': 'Revenue is $1,200.'}]
        resp, status = self._call({'mode': 'insight', 'topic': 'revenue', 'lang': 'en'})
        self.assertEqual(status, 200, resp.get_json())
        self.assertEqual(resp.get_json()['text'], 'Revenue is $1,200.')
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('copilot', 'biz-old')] * 2)
        run = DB.ai_runs.find_one({'persona': 'copilot'})
        self.assertEqual((run['ai_calls'], run['prompt_tokens'], run['completion_tokens']), (2, 2000, 100))
        NS['deepseek_chat_completion'].assert_not_called()

    def test_reply_mode_and_errors(self):
        DB.bot_messages.insert_one({'customer_id': 'biz-old:+15550001', 'sender_type': 'customer', 'content': 'hi', 'created_at': '1'})
        resp, status = self._call({'mode': 'reply', 'customer_id': 'biz-old:+15550001', 'lang': 'en'})
        self.assertEqual((status, resp.get_json()['text']), (200, 'hello'))
        self.assertEqual(len(_usage(feature='copilot')), 1)
        DS.script[:] = [RuntimeError('DeepSeek down')]
        resp, status = self._call({'mode': 'reply', 'customer_id': 'biz-old:+15550001', 'lang': 'vi'})
        self.assertEqual(status, 502)
        self.assertIn('AI đang bận', resp.get_json()['message'])


# ================================================================ 4. lý do nhập hàng: cổng gói 'inventory'
class RestockGateTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def _reason(self, bid):
        return NS['_generate_restock_reason_with_ai']('Cold Brew', 2, 1.0, 2.0, business_id=bid, suggested_qty=5, lang='en',
                                                      currency='USD', unit_cost=3.5, use_ai=True)

    def test_plan_without_inventory_gets_template_without_ai(self):
        text, source = self._reason('biz-ess')
        self.assertEqual(source, 'template')
        self.assertTrue(text.startswith("'Cold Brew': 2 left"))
        self.assertEqual(DS.calls, [])
        self.assertEqual(_usage(), [])
        self.assertEqual(DB.ai_runs.docs, [], 'gói chặn không phải 1 lượt AI lỗi')

    def test_pro_shop_uses_ai_and_logs_once(self):
        DS.script[:] = [{'role': 'assistant', 'content': 'Cold Brew is down to 2 — order 5 soon (about $17.50).'}]
        text, source = self._reason('biz-pro')
        self.assertEqual(source, 'ai')
        self.assertEqual([(r['feature'], r['business_id'], r['units']) for r in _usage()], [('restock_reason', 'biz-pro', 1050)])
        self.assertEqual(DS.calls[0][1]['timeout'], 10)


# ================================================================ 5. bộ phân loại phản đối (bot bán BitPaw)
class ObjectionTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_classifier_goes_through_gateway_fast_and_unbilled(self):
        DS.script[:] = [{'role': 'assistant', 'content': ' price\n'}]
        with FLASK.test_request_context('/api/ai/studio/generate', method='POST'):
            session['user_id'] = session['business_id'] = 'biz-pro'
            self.assertEqual(classify_objection('that is way too expensive for a small salon'), 'PRICE')
        payload, kw = DS.calls[0]
        self.assertEqual((payload['temperature'], payload['max_tokens'], kw['timeout']), (0, 8, 8))
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('sales_bot', None)])

    def test_classifier_no_retry_and_quiet_failures(self):
        DS.script[:] = [_Status(503)]
        self.assertIsNone(classify_objection('you are more expensive than Fresha'))
        self.assertEqual(len(DS.calls), 1, 'router call: không thử lại')
        self.assertIsNone(classify_objection('ok'))   # rõ ràng không phải phản đối -> không gọi AI
        self.assertEqual(len(DS.calls), 1)
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': ''}):
            self.assertIsNone(classify_objection('too pricey'))
        self.assertEqual(len(DS.calls), 1)
        src = _func_src('ai_sales_prompts.py', 'classify_objection')
        self.assertNotIn('requests.post', src)
        self.assertNotIn('api.deepseek.com', src)


# ================================================================ 6. AI Studio: prompt ảnh từ chữ
class PromptFromTextTests(unittest.TestCase):
    def setUp(self):
        _reset()
        src = _read('ai_media.py')
        node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == 'prompt_from_text')
        self.err = type('MediaError', (Exception,), {'__init__': lambda s, code, msg, status=400: Exception.__init__(s, code)})
        self.ns = {'re': re, 'brand_context': lambda bid: 'Brand: Pro Nails', 'MediaError': self.err,
                   'log_text_usage': MagicMock(side_effect=AssertionError('old logger must not run')),
                   'deepseek_text': MagicMock(side_effect=AssertionError('must go through ai_gateway'))}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'ai_media.py', 'exec'), self.ns)

    def test_one_real_usage_row_no_untracked_row(self):
        DS.script[:] = [{'role': 'assistant', 'content': '"A bright pedicure chair, soft light"'}]
        out = self.ns['prompt_from_text']('biz-old', 'Autumn special', 'image', 'en')
        self.assertEqual(out, 'A bright pedicure chair, soft light')
        rows = _usage()
        self.assertEqual([(r['feature'], r['business_id'], r['prompt_tokens'], r['completion_tokens']) for r in rows],
                         [('studio_image_prompt', 'biz-old', 1000, 50)])
        self.assertEqual(DS.calls[0][0]['max_tokens'], 300)
        self.assertNotIn('log_text_usage(', _func_src('ai_media.py', 'prompt_from_text'))

    def test_ai_error_is_honest(self):
        DS.script[:] = [ValueError('bad request')]
        with self.assertRaises(self.err):
            self.ns['prompt_from_text']('biz-old', 'Autumn special', 'image', 'en')
        self.assertEqual(_usage(), [])


# ================================================================ 7. trí nhớ, AI Nurture, cron nhắc khách: cổng gói
class MemoryAndNurtureGateTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_memory_distill_respects_ai_inbox_plan(self):
        for bid in ('biz-ess', 'biz-pro', 'biz-old'):
            DB.bot_customers.insert_one({'id': f'{bid}:+1555'})
            DS.script[:] = [{'role': 'assistant', 'content': f'memory of {bid}'}]
            ai_memory_engine._distill_now(f'{bid}:+1555', '', [{'role': 'user', 'content': 'I love gel'}])
        self.assertIsNone(DB.bot_customers.find_one({'id': 'biz-ess:+1555'}).get('ai_memory'), 'Essential: không tóm tắt')
        self.assertEqual(DB.bot_customers.find_one({'id': 'biz-pro:+1555'})['ai_memory'], 'memory of biz-pro')
        self.assertEqual(DB.bot_customers.find_one({'id': 'biz-old:+1555'})['ai_memory'], 'memory of biz-old')
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('chat_memory', 'biz-pro'), ('chat_memory', 'biz-old')])
        self.assertEqual(len(DS.calls), 2)
        self.assertNotIn('deepseek_chat_completion', _read('ai_memory_engine.py'))

    def test_nurture_engine_gate_and_ledger(self):
        fb = AINurturingEngine.generate_sequence_template('Essential Nails', 'nail', 'RECALL', 'friendly', 'en', business_id='biz-ess')
        self.assertIn('{first_name}', fb['7days'])            # câu mẫu trung thực, không gọi AI
        self.assertEqual(DS.calls, [])
        DS.script[:] = [{'role': 'assistant', 'content': json.dumps({'3days': 'Hi {first_name} A', '7days': 'Hi {first_name} B',
                                                                    '14days': 'Hi {first_name} C'})}]
        out = AINurturingEngine.generate_sequence_template('Pro Nails', 'nail', 'RECALL', 'friendly', 'en', business_id='biz-pro')
        self.assertEqual(out['7days'], 'Hi {first_name} B')
        self.assertEqual(DS.calls[0][0]['response_format'], {'type': 'json_object'})
        # route của chủ tiệm không truyền business_id: gateway lấy tiệm trong phiên làm cổng + sổ
        with FLASK.test_request_context('/api/ai/nurture/generate-campaign', method='POST'):
            session['user_id'] = session['business_id'] = 'biz-ess'
            txt = AINurturingEngine.generate_single_nurture_message('Essential Nails', 'nail', 'RECALL', 'friendly', 'Lan', lang='en')
        self.assertEqual(txt, AINurturingEngine._fallback_copy('Lan', 'en')['7days'])
        with FLASK.test_request_context('/api/ai/nurture/generate-campaign', method='POST'):
            session['user_id'] = session['business_id'] = 'biz-old'
            txt = AINurturingEngine.generate_single_nurture_message('Old Salon', 'nail', 'RECALL', 'friendly', 'Lan', lang='en')
        self.assertEqual(txt, 'hello')
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('nurture', 'biz-pro'), ('nurture', 'biz-old')])
        self.assertNotIn('deepseek_chat_completion', _read('ai_nurturing_engine.py'))

    def _rule(self, rid, bid):
        DB.customers.insert_one({'id': rid * 10, 'business_id': bid, 'name': 'Kim Lee', 'phone': f'+6141200{rid}',
                                 'last_purchase_at': (datetime.now() - timedelta(days=40)).isoformat()})
        rule = {'id': rid, 'business_id': bid, 'name': 'Lapsed', 'condition_days': 30, 'channel': 'sms', 'auto_send': False,
                'is_active': True, 'industry': 'nail'}
        DB.nurture_schedule_rules.insert_one(rule)
        return rule

    def test_scheduler_skips_rules_of_plans_without_crm_ai(self):
        nurture_scheduler._process_rule(self._rule(1, 'biz-ess'))
        self.assertEqual(DB.campaign_messages.docs, [])
        self.assertEqual(DS.calls, [], 'Essential: không gọi AI trả phí, không tự xếp tin')
        DS.script[:] = [{'role': 'assistant', 'content': json.dumps({'3days': 'a {first_name}', '7days': 'Hi {first_name}, see you soon',
                                                                    '14days': 'c'})}]
        nurture_scheduler._process_rule(self._rule(2, 'biz-pro'))
        nurture_scheduler._process_rule(self._rule(3, 'biz-old'))   # tiệm cũ chưa có gói = Empire
        self.assertEqual([(m['business_id'], m['approval_status']) for m in DB.campaign_messages.docs],
                         [('biz-pro', 'PENDING'), ('biz-old', 'PENDING')])
        self.assertTrue(DB.campaign_messages.docs[0]['message_body'].startswith('Hi Kim, see you soon'))
        self.assertEqual([(r['feature'], r['business_id']) for r in _usage()], [('nurture', 'biz-pro'), ('nurture', 'biz-old')])


# ================================================================ 8. dọn dẹp: missed_call_reply, 1 định nghĩa doanh thu
class CleanupTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_missed_call_reply_removed_and_unused(self):
        names = {n.name for n in ast.parse(_read('messaging.py')).body if isinstance(n, ast.FunctionDef)}
        self.assertNotIn('missed_call_reply', names)
        self.assertIn('handle_inbound_sms', names)
        for dirpath, dirnames, files in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in ('.git', '.claude', 'node_modules', '__pycache__', 'venv', '.venv')]
            for f in files:
                if f.endswith(('.py', '.html', '.js')) and f != os.path.basename(__file__):
                    try:
                        with io.open(os.path.join(dirpath, f), encoding='utf-8', errors='ignore') as fh:
                            self.assertNotIn('missed_call_reply', fh.read(), os.path.join(dirpath, f))
                    except OSError:
                        pass

    def test_roster_sales_use_the_one_revenue_definition(self):
        now = datetime.now()
        for i, (st, amt) in enumerate((('completed', 100), ('PAID', 40), ('refunded', -10), ('failed', 999), ('pending', 50))):
            DB.orders.insert_one({'id': i, 'business_id': 'biz-pro', 'status': st, 'total_amount': amt,
                                  'created_at': (now - timedelta(days=1)).isoformat()})
        self.assertEqual(shift_roster._sales_last_7_days('biz-pro'), 130.0, "đơn Square 'PAID' được tính, failed/pending thì không")
        self.assertIn('PAID', ai_copilot_tools.REVENUE_STATUSES)
        src = _func_src('shift_roster.py', '_sales_last_7_days')
        self.assertIn('REVENUE_STATUSES', src)
        self.assertNotIn("'partially_refunded'", src)

    def test_sim_copilot_imports_revenue_statuses(self):
        tree = ast.parse(_read(os.path.join('scripts', 'ai_sim', 'sim_copilot.py')))
        imports = [(n.module, a.name, a.asname) for n in tree.body if isinstance(n, ast.ImportFrom) for a in n.names]
        self.assertIn(('ai_copilot_tools', 'REVENUE_STATUSES', 'STATUSES'), imports)
        self.assertFalse([n for n in tree.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'STATUSES' for t in n.targets)], 'không còn bản chép riêng')

    def test_no_direct_deepseek_calls_left_in_owned_call_sites(self):
        for fn in ('api_ai_copilot', '_generate_restock_reason_with_ai', '_call_deepseek_with_tools'):
            self.assertNotIn('deepseek_chat_completion(', _func_src('app.py', fn), fn)
        self.assertNotIn('def _log_restock_ai_usage', APP_SRC)


if __name__ == '__main__':
    unittest.main(verbosity=2)
