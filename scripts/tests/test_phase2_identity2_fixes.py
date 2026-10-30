# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 vòng 2, khu "identity2":
  1. /api/portal/* (public, không session): hội thoại kênh nền tảng (SMS / WhatsApp / Messenger...) KHÔNG BAO GIỜ được đọc,
     ghi, nghe tín hiệu hay tải ảnh lên; hội thoại web chỉ mở cho ĐÚNG trình duyệt đã chat ở đó (mã chat 'bp_chat_token' có
     mã băm trên tin của hội thoại); 2 trình duyệt gõ cùng 1 SĐT không đọc được tin của nhau; luồng widget thật (chat ->
     nghe trả lời của nhân viên -> giữ hội thoại cho nhân viên) vẫn chạy, widget + portal.html gửi đúng mã đó.
  2. /api/cskh/chat/send: SĐT sai dạng ('sms:+614...') -> 400, không còn success:true mà không lưu gì.
  3. ai_packs.normalize_phone: tiệm chưa có nước -> không đoán số Mỹ; Mỹ / Canada chỉ số NANP hợp lệ; số 0 đầu ghi sau mã
     nước AU / NZ / GB / VN ('+61 (0)412...') vẫn là cùng 1 số; mã SMS 1 lần không bao giờ tới số +1 bịa ra.
  4. request_client_key: không có BITPAW_OTP_SECRET / FLASK_SECRET_KEY -> không có khoá mạng (HMAC khoá rỗng dò ngược được IP).
  5. reservations_core: lọc ứng viên trong Mongo (regex) và kiểm từng dòng (is_owned) nhận CÙNG các cách ghi của SĐT đã xác minh.
  6. check_availability: giờ mở cửa qua đêm hiện '18:00-02:00 (next day)', không phải '26:00'.

Dùng lại DB giả + stub của test_phase2_receptionist_core.py (nạp TRƯỚC mọi import): không import app.py thật, không MongoDB
thật, không gọi mạng / DeepSeek / Twilio; hàm của app.py lấy nguyên mã nguồn qua ast.
Chạy: python scripts/tests/test_phase2_identity2_fixes.py
"""
import ast
import hashlib
import hmac
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_receptionist_core as core  # noqa: E402  (DB giả, messaging giả, secure_ai_generate qua ast)

from flask import Flask, Response  # noqa: E402

import ai_packs  # noqa: E402
import booking_rules  # noqa: E402
import inbox_channels  # noqa: E402
import reservations_core as rc  # noqa: E402

DB, T, NS, ROOT = core.DB, core.T, core.NS, core.ROOT
NAIL, PHONE, TOKEN_A, TOKEN_B = core.NAIL, core.PHONE, core.TOKEN_A, core.TOKEN_B
WEB_PHONE = '0412345678'
WEB_CID = f'{NAIL}:{WEB_PHONE}'

# ---------------------------------------------------------------- route /api/portal/* + /api/cskh/chat/send của app.py
_PORTAL_FUNCS = ('_portal_chat_token', '_resolve_portal_customer', '_portal_conversation', 'api_portal_messages_list',
                 'api_portal_messages_create', 'api_portal_upload', 'api_portal_stream', 'api_cskh_chat_send',
                 '_portal_stream_sig', '_portal_stream_key', '_portal_stream_owner')   # khoá nghe ngắn hạn (identity3)
SSE, UPLOADS = [], []


class _FakeFS:
    def put(self, data, **kw):
        UPLOADS.append(kw)
        return 'f1'


def _fake_sse(watchable, match_stage, payload_colls=()):
    SSE.append(match_stage)
    return Response('retry: 1000\n\n', mimetype='text/event-stream')


NS.update({'_public_shop_context': lambda bid: {'shop_name': 'Rose Nails'}, '_sse_change_signal': _fake_sse,
           'media_fs': _FakeFS(), 'secure_filename': lambda f: f, '_allowed_media_file': lambda f: True,
           '_safe_image_content_type': lambda f: 'image/gif', 'Response': Response,
           'url_for': lambda name, **kw: '/api/public/storage/file/' + str(kw.get('file_id')),
           'BITPAW_LEADS_BUSINESS_ID': 'bitpaw_leads', 'hmac': hmac, 'hashlib': hashlib})
for _node in core._TREE.body:   # _PORTAL_STREAM_KEY_TTL
    if isinstance(_node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_PORTAL_STREAM_KEY_TTL' for t in _node.targets):
        exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), 'app.py', 'exec'), NS)
for _name in _PORTAL_FUNCS:
    _node = next((n for n in core._TREE.body if isinstance(n, ast.FunctionDef) and n.name == _name), None)
    if _node is None:   # mã cũ chưa có hàm này
        continue
    _node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), f'app.py::{_name}', 'exec'), NS)

APP = Flask('identity2')
APP.secret_key = 'test'
NS['app'] = APP   # khoá bí mật ký khoá nghe /api/portal/stream
APP.add_url_rule('/api/ai/studio/generate', 'gen', NS['secure_ai_generate'], methods=['POST'])
APP.add_url_rule('/api/portal/messages', 'portal_list', NS['api_portal_messages_list'], methods=['GET'])
APP.add_url_rule('/api/portal/messages', 'portal_create', NS['api_portal_messages_create'], methods=['POST'])
APP.add_url_rule('/api/portal/upload', 'portal_upload', NS['api_portal_upload'], methods=['POST'])
APP.add_url_rule('/api/portal/stream', 'portal_stream', NS['api_portal_stream'], methods=['GET'])
APP.add_url_rule('/api/cskh/chat/send', 'cskh_send', NS['api_cskh_chat_send'], methods=['POST'])


def read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def node_check(test, name, code):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(code)
    try:
        r = subprocess.run(['node', '--check', f.name], capture_output=True, text=True, encoding='utf-8')
    finally:
        os.unlink(f.name)
    test.assertEqual(r.returncode, 0, f'{name}: {r.stderr[-400:]}')


def js_function(src, name):
    """Cắt nguyên 1 function JS (đếm ngoặc nhọn)."""
    m = re.search(r'(async\s+)?function\s+' + re.escape(name) + r'\s*\(', src)
    if not m:
        return None
    i = src.index('{', m.end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    return None


def _upload(c, cid, token=None):
    data = {'customer_id': cid, 'file': (io.BytesIO(b'GIF89a'), 'a.gif')}
    if token:
        data['chat_token'] = token
    return c.post('/api/portal/upload', data=data, content_type='multipart/form-data')


# ================================================================ 1. portal
class PortalTests(core._Base):
    def setUp(self):
        super().setUp()
        SSE.clear()
        UPLOADS.clear()
        self.c = APP.test_client()

    def _chat(self, token, phone=WEB_PHONE, msg='Can I book a gel manicure tomorrow?'):
        body = {'business_id': NAIL, 'context': 'customer_booking', 'customer_phone': phone, 'customer_message': msg}
        if token:
            body['chat_token'] = token
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test'}):
            r = self.c.post('/api/ai/studio/generate', json=body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])

    def _get(self, cid, token=None, how='header'):
        url = '/api/portal/messages?customer_id=' + quote(cid, safe='')
        if token and how == 'query':
            url += '&chat_token=' + quote(token, safe='')
        return self.c.get(url, headers={'X-Chat-Token': token} if (token and how == 'header') else {})

    def test_platform_threads_are_never_served(self):
        th_a = T.chat_token_hash(TOKEN_A)
        for channel, uid in (('sms', PHONE), ('whatsapp', '61412345678'), ('messenger', 'psid-77')):
            cid = inbox_channels.record(NAIL, channel, uid, 'Can I move my booking?', 'customer',
                                        phone=None if channel == 'messenger' else PHONE)
            inbox_channels.record(NAIL, channel, uid, 'Your gel manicure is Wed 10:00 at 12 King St', 'ai')
            # trường hợp xấu nhất: 1 tin của hội thoại này mang mã băm của trình duyệt -> hội thoại nền tảng vẫn đóng
            DB.bot_messages.insert_one({'customer_id': cid, 'sender_type': 'customer', 'content': 'x', 'business_id': NAIL,
                                        'created_at': '2026-11-02T08:00:00', 'chat_token_hash': th_a})
            before = len(DB.bot_messages.find({'customer_id': cid}))
            for token, how in ((None, 'header'), (TOKEN_A, 'header'), (TOKEN_A, 'query')):
                r = self._get(cid, token, how)
                self.assertEqual(r.status_code, 404, (channel, how, r.get_data(as_text=True)[:200]))
                self.assertNotIn('King St', r.get_data(as_text=True))
            for body in ({'customer_id': cid, 'content': 'Cancel all my bookings'},
                         {'customer_id': cid, 'content': 'Cancel all my bookings', 'chat_token': TOKEN_A}):
                self.assertEqual(self.c.post('/api/portal/messages', json=body).status_code, 404, channel)
            self.assertEqual(len(DB.bot_messages.find({'customer_id': cid})), before, channel)   # không ghi gì
            for url in ('/api/portal/stream?customer_id=' + quote(cid, safe=''),
                        '/api/portal/stream?customer_id=' + quote(cid, safe='') + '&chat_token=' + TOKEN_A):
                self.assertEqual(self.c.get(url).status_code, 404, channel)
            self.assertEqual(_upload(self.c, cid, TOKEN_A).status_code, 404, channel)
        self.assertEqual(SSE, [])
        self.assertEqual(UPLOADS, [])

    def test_web_thread_opens_only_for_the_browser_that_chatted(self):
        self._chat(TOKEN_A)
        self.assertEqual({m['sender_type'] for m in DB.bot_messages.find({'customer_id': WEB_CID})}, {'customer', 'ai'})
        r = self._get(WEB_CID, TOKEN_A, 'header')
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertEqual([m['sender_type'] for m in j['data']], ['customer', 'ai'])
        self.assertEqual(j['shop_name'], 'Rose Nails')
        # mã chat gốc trong URL (lộ vào log truy cập) không còn được nhận (identity3)
        self.assertEqual(self._get(WEB_CID, TOKEN_A, 'query').status_code, 404)
        # biết tiệm + SĐT (khoá cũ) là chưa đủ
        for tok in (None, TOKEN_B, 'short'):
            self.assertEqual(self._get(WEB_CID, tok).status_code, 404, tok)
        self.assertEqual(self._get(f'{NAIL}:0499999999', TOKEN_A).status_code, 404)   # SĐT khác: không phải hội thoại của mã này
        n = len(DB.bot_messages.find({'customer_id': WEB_CID}))
        for body in ({'customer_id': WEB_CID, 'content': 'Cancel my booking please'},
                     {'customer_id': WEB_CID, 'content': 'Cancel my booking please', 'chat_token': TOKEN_B},
                     {'customer_id': WEB_CID, 'content': 'Cancel my booking please', 'chat_token': {'$ne': None}},
                     {'customer_id': {'$ne': None}, 'content': 'x', 'chat_token': TOKEN_A}):
            self.assertEqual(self.c.post('/api/portal/messages', json=body).status_code, 404, body)
        self.assertEqual(len(DB.bot_messages.find({'customer_id': WEB_CID})), n)
        # chủ hội thoại (đúng trình duyệt) ghi được; tin mang mã băm của trình duyệt đó (lịch sử riêng của nó), kênh web
        r = self.c.post('/api/portal/messages', json={'customer_id': WEB_CID, 'content': 'Also a gel removal please',
                                                      'chat_token': TOKEN_A, 'sender_type': 'customer'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        last = DB.bot_messages.find({'customer_id': WEB_CID})[-1]
        self.assertEqual((last['sender_type'], last['content'], last.get('chat_token_hash'), last.get('channel')),
                         ('customer', 'Also a gel removal please', T.chat_token_hash(TOKEN_A), 'web'))
        # nhân viên trả lời trong /ai_bot -> trình duyệt đó thấy
        DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'staff', 'content': 'See you at 3pm!',
                                    'business_id': NAIL, 'created_at': '2999-01-01T00:00:00', 'channel': 'web'})
        self.assertIn('See you at 3pm!', [m['content'] for m in self._get(WEB_CID, TOKEN_A).get_json()['data']])
        # tín hiệu SSE: cần mã, và chỉ của ĐÚNG hội thoại này (không còn mọi thay đổi của cả tiệm)
        self.assertEqual(self.c.get('/api/portal/stream?customer_id=' + quote(WEB_CID, safe='')).status_code, 404)
        self.assertEqual(SSE, [])
        self.assertEqual(self.c.get('/api/portal/stream?customer_id=' + quote(WEB_CID, safe='') + '&chat_token=' + TOKEN_A).status_code,
                         404)   # mã gốc trong URL: không (identity3 — trình duyệt dùng ?stream_key=)
        self.assertEqual(SSE, [])
        r = self.c.get('/api/portal/stream?customer_id=' + quote(WEB_CID, safe=''), headers={'X-Chat-Token': TOKEN_A})
        self.assertEqual(r.status_code, 200)
        stage = json.dumps(SSE[-1])
        self.assertIn(WEB_CID, stage)
        self.assertNotIn('fullDocument.business_id', stage)
        # ảnh: chỉ chủ hội thoại
        self.assertEqual(_upload(self.c, WEB_CID).status_code, 404)
        self.assertEqual(_upload(self.c, WEB_CID, TOKEN_B).status_code, 404)
        self.assertEqual(UPLOADS, [])
        self.assertEqual(_upload(self.c, WEB_CID, TOKEN_A).status_code, 200)

    def test_two_browsers_typing_the_same_phone_do_not_read_each_other(self):
        ha, hb = T.chat_token_hash(TOKEN_A), T.chat_token_hash(TOKEN_B)
        DB.bot_customers.insert_one({'id': WEB_CID, 'business_id': NAIL, 'channel': 'web', 'phone': WEB_PHONE})
        rows = (('customer', 'A: I am Jane, booking for Friday', ha, '2026-11-02T08:00:00'),
                ('ai', 'A: Booked Friday 10:00 for Jane at 12 King St', ha, '2026-11-02T08:00:05'),
                ('staff', 'S1: Jane, your gel is confirmed', None, '2026-11-02T08:05:00'),
                ('customer', 'B: hello', hb, '2026-11-02T08:10:00'),
                ('ai', 'B: hi there', hb, '2026-11-02T08:10:05'),
                ('staff', 'S2: we will call you back', None, '2026-11-02T08:15:00'))
        for st, content, h, at in rows:
            doc = {'customer_id': WEB_CID, 'sender_type': st, 'content': content, 'business_id': NAIL, 'created_at': at,
                   'channel': 'web'}
            if h:
                doc['chat_token_hash'] = h
            DB.bot_messages.insert_one(doc)
        b = [m['content'] for m in self._get(WEB_CID, TOKEN_B).get_json()['data']]
        self.assertEqual(b, ['B: hello', 'B: hi there', 'S2: we will call you back'])
        a = [m['content'] for m in self._get(WEB_CID, TOKEN_A).get_json()['data']]
        self.assertEqual(a, ['A: I am Jane, booking for Friday', 'A: Booked Friday 10:00 for Jane at 12 King St',
                             'S1: Jane, your gel is confirmed', 'S2: we will call you back'])


# ================================================================ 1b. widget + portal.html gửi đúng mã của trình duyệt
NODE_WIDGET = r'''
const SRC = JSON.parse(process.env.WIDGET_SRC);
const calls = [];
const store = {};
global.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
global.window = { crypto: require('crypto').webcrypto };
global.fetch = async (url, opts) => { calls.push({ url: String(url), opts: opts || {} });
  return { ok: true, status: 200, json: async () => ({ success: true, data: [], stream_key: '1700000600.' + 'ab'.repeat(32), stream_key_ttl: 600 }) }; };
global.EventSource = function (url) { calls.push({ es: String(url) }); this.url = url; this.close = () => {}; };
global.setTimeout = () => 0; global.clearTimeout = () => {};   // gia hạn khoá nghe: không chạy thật trong test này
const CHAT_CONTEXT = 'customer_booking', BUSINESS_ID = 'biz1';
let chatTokenMem = null, shopReplyStream = null, shopReplySeen = null;
function appendMessage() {}
eval(SRC);
(async () => {
  await startShopReplyStream('0412345678');
  await keepThreadForTeam('biz1:0412345678', 'Hello there');
  console.log(JSON.stringify({ tok: store.bp_chat_token || chatTokenMem, calls }));
})().catch((e) => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
'''


class WidgetAndPortalPageTests(unittest.TestCase):
    def test_widget_sends_its_browser_token_on_every_portal_call(self):
        s = read('static/js/cskh_widget.js')
        node_check(self, 'static/js/cskh_widget.js', s)
        parts = [js_function(s, n) for n in ('getChatToken', 'fetchShopReplies', 'startShopReplyStream', 'openShopReplyStream',
                                             'renewShopReplyStream', 'keepThreadForTeam')]
        self.assertTrue(all(parts), 'widget functions not found')
        auth = re.search(r'^\s*const portalAuth = [^\n]*$', s, re.M)
        state = re.search(r'^\s*let shopStreamKey = [^\n]*$', s, re.M)
        src = '\n'.join(parts + ([auth.group(0)] if auth else []) + ([state.group(0)] if state else []))
        r = subprocess.run(['node', '-e', NODE_WIDGET], capture_output=True, text=True, encoding='utf-8',
                           env=dict(os.environ, WIDGET_SRC=json.dumps(src)), timeout=60)
        out = json.loads((r.stdout.strip().splitlines() or ['{}'])[-1])
        self.assertNotIn('error', out, out.get('error'))
        tok = out['tok']
        self.assertRegex(tok or '', r'^[0-9a-f]{32}$')
        gets = [c for c in out['calls'] if 'url' in c and (c['opts'].get('method') or 'GET') == 'GET']
        posts = [c for c in out['calls'] if 'url' in c and c['opts'].get('method') == 'POST']
        streams = [c['es'] for c in out['calls'] if 'es' in c]
        self.assertEqual(len(gets), 2, out['calls'])            # fetchShopReplies + keepThreadForTeam
        for g in gets:
            self.assertTrue(g['url'].startswith('/api/portal/messages?customer_id='), g)
            self.assertEqual((g['opts'].get('headers') or {}).get('X-Chat-Token'), tok, g)
            self.assertNotIn(tok, g['url'])                     # mã trong header, không nằm trong URL / log truy cập
        self.assertEqual(len(posts), 1, out['calls'])
        body = json.loads(posts[0]['opts']['body'])
        self.assertEqual((body['customer_id'], body['sender_type'], body.get('chat_token')), ('biz1:0412345678', 'customer', tok))
        self.assertEqual(len(streams), 1, out['calls'])          # EventSource không gửi được header -> khoá nghe ngắn hạn
        self.assertIn('/api/portal/stream?customer_id=', streams[0])
        self.assertIn('stream_key=' + quote('1700000600.' + 'ab' * 32, safe=''), streams[0])
        self.assertNotIn(tok, streams[0])                        # mã chat gốc không bao giờ nằm trong URL (identity3)
        self.assertNotIn('chat_token', streams[0])

    def test_portal_page_uses_the_same_browser_token(self):
        s = read('templates/portal.html')
        self.assertIn("localStorage.getItem('bp_chat_token')", s)
        gets = re.findall(r"fetch\(`/api/portal/messages\?customer_id=[^\n]*", s)
        self.assertEqual(len(gets), 2, gets)
        self.assertTrue(all('portalHeaders()' in g for g in gets), gets)
        self.assertRegex(s, r"JSON\.stringify\(\{ customer_id: currentCustomerId, content, sender_type: 'customer', "
                            r"chat_token: portalChatToken\(\) \}\)")
        self.assertIn("formData.append('chat_token', portalChatToken());", s)
        es = re.findall(r'new EventSource\(`/api/portal/stream[^\n]*', s)
        self.assertTrue(len(es) == 1 and 'stream_key=${encodeURIComponent(streamKey)}' in es[0] and 'chat_token' not in es[0], es)
        self.assertEqual(len(re.findall(r'^\s*portal_err_no_access:', s, re.M)), 2)   # VI + EN
        self.assertIn("res.status === 404 ? 'portal_err_no_access' : 'portal_err_load_history'", s)
        for i, m in enumerate(re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', s, re.S)):
            code = re.sub(r'\{\{.*?\}\}', '0', m.group(1), flags=re.S)
            code = re.sub(r'\{%.*?%\}|\{#.*?#\}', '', code, flags=re.S)
            node_check(self, f'portal.html script#{i}', code)


# ================================================================ 2. /api/cskh/chat/send
class CskhChatSendTests(core._Base):
    def test_bad_phone_is_refused_instead_of_a_silent_success(self):
        c = APP.test_client()
        for phone in ('sms:+61412345678', 'whatsapp:61412345678', 'messenger:psid-1', 'abc', '12', '+61 412 345 678 999 999 9'):
            r = c.post('/api/cskh/chat/send', json={'phone': phone, 'content': 'hi'})
            self.assertEqual(r.status_code, 400, phone)
            self.assertFalse(r.get_json()['success'])
            self.assertTrue(r.get_json()['message'])
        self.assertEqual(DB.bot_messages.find({}), [])
        for phone in ('0412 345 678', '+61 (412) 345-678', 412345678):
            r = c.post('/api/cskh/chat/send', json={'phone': phone, 'content': 'hello'})
            self.assertEqual((r.status_code, r.get_json()['success']), (200, True), phone)
        self.assertEqual({m['customer_id'] for m in DB.bot_messages.find({})},
                         {'bitpaw_leads:0412 345 678', 'bitpaw_leads:+61 (412) 345-678', 'bitpaw_leads:412345678'})


# ================================================================ 3. SĐT
class PhoneRulesTests(unittest.TestCase):
    def test_unknown_country_never_guesses_us(self):
        for raw in ('0412 345 678', '0912345678', '(212) 555-1234', '2125551234', '61412345678'):
            for country in (None, ''):
                self.assertEqual(ai_packs.normalize_phone(raw, country), '', (raw, country))
        self.assertEqual(ai_packs.normalize_phone('+61 412 345 678', None), '+61412345678')
        self.assertEqual(ai_packs.normalize_phone('0061 412 345 678', None), '+61412345678')
        self.assertFalse(ai_packs.same_phone('(212) 555-1234', '+12125551234', None))   # không biết nước: không đoán
        self.assertTrue(ai_packs.same_phone('0412 345 678', '0412345678', None))          # cùng chữ số vẫn là 1 số
        self.assertFalse(any(v.startswith('+1') for v in ai_packs.phone_variants('0412 345 678', None)))

    def test_us_and_canada_only_valid_nanp_numbers(self):
        for raw in ('0412 345 678', '1412345678', '10412345678', '11234567890', '1 041 234 5678'):
            for country in ('US', 'CA', 'us'):
                self.assertEqual(ai_packs.normalize_phone(raw, country), '', (raw, country))
        self.assertEqual(ai_packs.normalize_phone('(212) 555-1234', 'US'), '+12125551234')
        self.assertEqual(ai_packs.normalize_phone('1 212 555 1234', 'US'), '+12125551234')
        self.assertEqual(ai_packs.normalize_phone('604-555-0199', 'CA'), '+16045550199')
        self.assertEqual(ai_packs.normalize_phone('61412345678', 'US'), '+61412345678')   # số nước ngoài quên dấu +

    def test_trunk_zero_after_the_country_code_is_the_same_number(self):
        for raw in ('+61 (0)412 345 678', '+610412345678', '+61 0412 345 678', '0061 (0) 412 345 678'):
            for country in ('AU', None):
                self.assertEqual(ai_packs.normalize_phone(raw, country), '+61412345678', (raw, country))
        self.assertEqual(ai_packs.normalize_phone('+44 (0)20 7946 0000', 'GB'), '+442079460000')
        self.assertEqual(ai_packs.normalize_phone('+84 (0)912 345 678', 'VN'), '+84912345678')
        self.assertEqual(ai_packs.normalize_phone('+64 (0)21 123 4567', 'NZ'), '+64211234567')
        self.assertTrue(ai_packs.same_phone('+61 (0)412 345 678', '0412 345 678', 'AU'))
        self.assertFalse(ai_packs.same_phone('+61 (0)412 345 679', '0412 345 678', 'AU'))
        v = ai_packs.phone_variants('+61412345678', 'AU')
        for s in ('+61 (0)412 345 678', '+610412345678', '+61 0412 345 678'):
            self.assertIn(s, v)
        for s in v:
            self.assertEqual(ai_packs.normalize_phone(s, 'AU'), '+61412345678', s)


class OtpUnknownCountryTests(core._Base):
    def test_code_never_goes_to_an_invented_plus_one_number(self):
        core.TWILIO['ready'] = True
        DB.businesses.insert_one({'id': 'biz_nc', 'name': 'New Nails', 'industry_code': 'nail'})   # tự đăng ký: chưa có nước
        DB.appointments.insert_one({'id': 77, 'business_id': 'biz_nc', 'customer_phone': '0412 345 678', 'service_id': 1,
                                    'book_time': f'{core.DAY}T10:00', 'status': 'confirmed', 'source': 'web'})
        cid = 'biz_nc:0412345678'
        with T.chat_scope(TOKEN_A, channel='web'):
            out = core._call('send_verification_code', {'phone': '0412 345 678'}, 'biz_nc', cid)
        self.assertFalse(out.get('success'), out)
        self.assertIn('country code', json.dumps(out))
        self.assertEqual(DB.ai_chat_verifications.find({}), [])
        core._msg._twilio_send.assert_not_called()
        with T.chat_scope(TOKEN_A, channel='web'):
            ok = core._call('send_verification_code', {'phone': '+61 412 345 678'}, 'biz_nc', cid)
        self.assertTrue(ok.get('success'), ok)
        self.assertEqual([d['phone'] for d in DB.ai_chat_verifications.find({})], ['+61412345678'])


# ================================================================ 4. khoá mạng
class ClientKeyTests(unittest.TestCase):
    def test_no_secret_means_no_network_key(self):
        env = {k: v for k, v in os.environ.items() if k not in ('BITPAW_OTP_SECRET', 'FLASK_SECRET_KEY')}
        with patch.dict(os.environ, env, clear=True):
            with APP.test_request_context('/', headers={'X-Forwarded-For': '203.0.113.5'}):
                self.assertIsNone(T.request_client_key())
                with T.chat_scope(TOKEN_A, channel='web', client=T.request_client_key()):
                    self.assertIsNone(T._scope().get('client'))
        for var in ('BITPAW_OTP_SECRET', 'FLASK_SECRET_KEY'):
            with patch.dict(os.environ, dict(env, **{var: 'unit-test-secret'}), clear=True):
                with APP.test_request_context('/', headers={'X-Forwarded-For': '203.0.113.5'}):
                    k = T.request_client_key()
            self.assertTrue(k and k.startswith('net:'), var)
            self.assertNotIn('203.0.113.5', k)


# ================================================================ 5. lọc ứng viên == kiểm từng dòng
class OwnershipSpellingTests(unittest.TestCase):
    def _both(self, ctx, phones):
        own = rc.ownership_query(dict(ctx))
        rx = next(o['customer_phone']['$regex'] for o in own['$or'] if 'customer_phone' in o)
        return {p: (bool(re.search(rx, p)), rc.is_owned({'customer_phone': p}, dict(ctx))) for p in phones}

    def test_trunk_zero_spellings_are_found_and_owned(self):
        ctx = {'business_id': 'b', 'channel': 'sms', 'customer_id': 'b:sms:+61412345678', 'phone': '+61412345678', 'country': 'AU'}
        same = ('+61 (0)412 345 678', '+610412345678', '+61 0412 345 678', '0061 (0)412 345 678', '0412 345 678',
                '+61 412 345 678', '61412345678', '0412-345-678')
        other = ('+61 (0)412 345 679', '+61 412 345 677', '0412 345 679', '+44 412 345 678', '+610412345679', '412 345 67')
        res = self._both(ctx, same + other)
        for p in same:
            self.assertEqual(res[p], (True, True), p)
        for p in other:
            self.assertEqual(res[p], (False, False), p)

    def test_us_spellings_unchanged(self):
        ctx = {'business_id': 'b', 'channel': 'sms', 'customer_id': 'b:sms:+12125551234', 'phone': '+12125551234', 'country': 'US'}
        same = ('(212) 555-1234', '+1 (212) 555-1234', '1 212 555 1234', '212.555.1234', '+12125551234')
        other = ('(312) 555-1234', '+1 (212) 555-1235', '(212) 555-123')
        res = self._both(ctx, same + other)
        for p in same:
            self.assertEqual(res[p], (True, True), p)
        for p in other:
            self.assertEqual(res[p], (False, False), p)

    def test_owned_upcoming_finds_the_trunk_spelling(self):
        DB.reset()
        for i, p in enumerate(('+61 (0)412 345 678', '+61 (0)412 345 679')):
            DB.table_reservations.insert_one({'id': i + 1, 'business_id': 'b', 'customer_phone': p, 'status': 'confirmed',
                                              'reserved_time': '2026-11-04T19:00:00'})
        from datetime import datetime
        ctx = {'business_id': 'b', 'channel': 'sms', 'customer_id': 'b:sms:+61412345678', 'phone': '+61412345678', 'country': 'AU'}
        rows = rc.owned_upcoming(DB.table_reservations, 'b', ctx, ('confirmed',), datetime(2026, 11, 2, 8, 0))
        self.assertEqual([r['id'] for r in rows], [1])


# ================================================================ 6. giờ qua đêm
class OvernightHoursTests(core._Base):
    def test_overnight_close_is_shown_as_next_day(self):
        with patch.object(booking_rules, 'hours_on', return_value=(18 * 60, 26 * 60)), \
                patch.object(booking_rules, 'available_slots', return_value=['18:00', '18:30']):
            out = T.check_availability(NAIL, f'{NAIL}:{PHONE}', date=core.DAY)
        self.assertEqual(out['opening_hours'], '18:00-02:00 (next day)')
        with patch.object(booking_rules, 'hours_on', return_value=(9 * 60, 19 * 60)), \
                patch.object(booking_rules, 'available_slots', return_value=['09:00']):
            self.assertEqual(T.check_availability(NAIL, f'{NAIL}:{PHONE}', date=core.DAY)['opening_hours'], '09:00-19:00')


if __name__ == '__main__':
    unittest.main(verbosity=2)
