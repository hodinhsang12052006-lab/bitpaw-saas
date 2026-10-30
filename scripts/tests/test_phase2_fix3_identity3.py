# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 vòng 3, khu "identity3" (hội thoại web công khai /api/portal/* + widget):
  1. Trả lời của nhân viên (/api/bot/messages) trên hội thoại web chỉ tới ĐÚNG trình duyệt nó trả lời: tin lưu kèm mã băm của
     tin khách được trả lời (mặc định tin khách MỚI NHẤT; reply_to = created_at của 1 tin khách cụ thể). /api/portal/messages chỉ
     trả trả lời đó cho trình duyệt có cùng mã băm — kể cả khi 1 trình duyệt khác gõ cùng SĐT đã vào hội thoại TRƯỚC (kẻ gian chat
     1 lần bằng SĐT nạn nhân). Tin khách mới nhất không có mã (widget cũ) -> không trình duyệt nào đọc được trả lời đó qua trang
     công khai. Trả lời cũ không có trường mã băm: giữ luật cũ (chỉ trình duyệt đã vào hội thoại trước trả lời đó).
  2. /api/portal/stream chỉ báo tín hiệu của ĐÚNG trình duyệt (tin mang mã băm của nó + trả lời cũ không mã băm); trình duyệt kia
     nhắn tin hay bot_customers đổi last_message không còn báo.
  3. Mã chat gốc (bp_chat_token) KHÔNG BAO GIỜ được nhận qua URL (lộ vào log truy cập); EventSource dùng khoá nghe ngắn hạn
     (HMAC khoá bí mật của app trên hội thoại + mã băm + hạn, 10 phút) do GET /api/portal/messages cấp. Khoá sai hội thoại / sai
     chữ ký / hết hạn / khoá bí mật khác / hội thoại SMS -> 404. Widget + portal.html mở kênh bằng khoá đó và tự gia hạn.
  4. Widget: /api/cskh/chat/send trả lỗi (400 SĐT sai, 429, 5xx, mất mạng, success:false) -> báo rõ VI / EN là tin CHƯA được
     gửi, giữ lại tin để gửi lại, KHÔNG mở kênh nghe như thể đã gửi được.
Luồng thật đầu-cuối: mã JS THẬT của widget / portal.html chạy trong node (fetch / EventSource / setTimeout giả) với phản hồi THẬT
của các route app.py (Flask test client, DB giả trong RAM), rồi URL kênh nghe mà trang dựng được gửi lại đúng route thật.
Dùng lại DB giả + stub của test_phase2_receptionist_core.py: không import app.py thật, không MongoDB thật, không mạng / DeepSeek /
Twilio; hàm của app.py lấy nguyên mã nguồn qua ast.
Chạy: python scripts/tests/test_phase2_fix3_identity3.py
"""
import ast
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_receptionist_core as core  # noqa: E402  (DB giả, messaging giả, secure_ai_generate qua ast)

from flask import Flask, Response  # noqa: E402

import inbox_channels  # noqa: E402

DB, T, NS, ROOT = core.DB, core.T, core.NS, core.ROOT
NAIL, OTHER_NAIL, TOKEN_A, TOKEN_B = core.NAIL, core.OTHER_NAIL, core.TOKEN_A, core.TOKEN_B
TOKEN_W = '0123456789abcdef' * 2          # mã đúng dạng widget tạo (32 hex) — dùng cho luồng JS thật
WEB_PHONE = '0412345678'
WEB_CID = f'{NAIL}:{WEB_PHONE}'
SECRET = 'unit-test-secret-identity3'

# ---------------------------------------------------------------- DB giả: thêm distinct (pymongo thật có sẵn)
if not hasattr(core.FakeCollection, 'distinct'):
    def _distinct(self, key, flt=None):
        out = []
        for d in self.find(flt or {}):
            v = core._get(d, key)
            if v is not None and v not in out:
                out.append(v)
        return out
    core.FakeCollection.distinct = _distinct

# ---------------------------------------------------------------- route của app.py (lấy nguyên mã nguồn qua ast, bỏ decorator)
_FUNCS = ('_portal_chat_token', '_resolve_portal_customer', '_portal_conversation', '_portal_stream_sig', '_portal_stream_key',
          '_portal_stream_owner', 'api_portal_messages_list', 'api_portal_messages_create', 'api_portal_upload',
          'api_portal_stream', 'api_cskh_chat_send', '_assert_owns_bot_customer', 'api_bot_messages_create',
          '_web_device_labels', '_web_reply_stamp')   # identity4: đích trả lời + nhãn thiết bị (api_bot_messages_create gọi)
_ASSIGNS = ('_PORTAL_STREAM_KEY_TTL',)
SSE, UPLOADS = [], []


class _FakeFS:
    def put(self, data, **kw):
        UPLOADS.append(kw)
        return 'f1'


def _fake_sse(watchable, match_stage, payload_colls=()):
    SSE.append(match_stage)
    return Response('retry: 1000\n\n', mimetype='text/event-stream')


APP = Flask('identity3')
APP.secret_key = SECRET
NS.update({'_public_shop_context': lambda bid: {'shop_name': 'Rose Nails'}, '_sse_change_signal': _fake_sse,
           'media_fs': _FakeFS(), 'secure_filename': lambda f: f, '_allowed_media_file': lambda f: True,
           '_safe_image_content_type': lambda f: 'image/gif', 'Response': Response,
           'url_for': lambda name, **kw: '/api/public/storage/file/' + str(kw.get('file_id')),
           'BITPAW_LEADS_BUSINESS_ID': 'bitpaw_leads', 'app': APP, 'hmac': hmac, 'hashlib': hashlib})
for _node in core._TREE.body:
    if isinstance(_node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in _ASSIGNS for t in _node.targets):
        exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), 'app.py', 'exec'), NS)
for _name in _FUNCS:
    _node = next((n for n in core._TREE.body if isinstance(n, ast.FunctionDef) and n.name == _name), None)
    if _node is None:   # mã cũ chưa có hàm này
        continue
    _node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), f'app.py::{_name}', 'exec'), NS)


def _route(path, endpoint, name, methods):
    if name in NS:
        APP.add_url_rule(path, endpoint, NS[name], methods=methods)


APP.add_url_rule('/api/ai/studio/generate', 'gen', NS['secure_ai_generate'], methods=['POST'])
_route('/api/portal/messages', 'portal_list', 'api_portal_messages_list', ['GET'])
_route('/api/portal/messages', 'portal_create', 'api_portal_messages_create', ['POST'])
_route('/api/portal/upload', 'portal_upload', 'api_portal_upload', ['POST'])
_route('/api/portal/stream', 'portal_stream', 'api_portal_stream', ['GET'])
_route('/api/cskh/chat/send', 'cskh_send', 'api_cskh_chat_send', ['POST'])
_route('/api/bot/messages', 'bot_create', 'api_bot_messages_create', ['POST'])

KEY_RE = re.compile(r'^([0-9]+)\.([0-9a-f]{64})$')


def read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


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


def js_line(src, pattern):
    m = re.search(pattern, src, re.M)
    return m.group(0) if m else None


def node_check(test, name, code):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(code)
    try:
        r = subprocess.run(['node', '--check', f.name], capture_output=True, text=True, encoding='utf-8')
    finally:
        os.unlink(f.name)
    test.assertEqual(r.returncode, 0, f'{name}: {r.stderr[-400:]}')


def sse_hits(stage, event):
    """Change event của MongoDB có khớp $match của /api/portal/stream không (cùng bộ so khớp của DB giả)."""
    return core._matches(event, stage['$match'])


def change(doc, coll='bot_messages', op='insert'):
    return {'operationType': op, 'ns': {'db': 'bitpaw', 'coll': coll}, 'fullDocument': doc}


def clock(t):
    """Đồng hồ giả cho các hàm app.py chạy trong NS (khoá nghe dùng time.time())."""
    return patch.dict(NS, {'time': types.SimpleNamespace(time=lambda: t, sleep=time.sleep, perf_counter=time.perf_counter)})


# ---------------------------------------------------------------- node: chạy mã JS THẬT với fetch / EventSource / setTimeout giả
NODE_HARNESS = r'''
const fs = require('fs');
const D = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const calls = [], streams = [], timers = [], appended = [], started = [], focused = [], rendered = [], notes = [], extra = {};
const store = Object.assign({}, D.store || {});
global.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
global.window = { crypto: require('crypto').webcrypto };
let queue = (D.responses || []).slice();
global.fetch = async (url, opts) => {
  calls.push({ url: String(url), opts: opts || {} });
  const r = queue.length > 1 ? queue.shift() : queue[0];
  if (!r || r.throw) throw new TypeError('Failed to fetch');
  return { ok: r.status >= 200 && r.status < 300, status: r.status,
           json: async () => { if (r.body === undefined || r.body === null) throw new SyntaxError('Unexpected token <'); return r.body; } };
};
global.EventSource = function (url) { this.url = String(url); this.readyState = 0; this.close = () => { this.readyState = 2; this.closed = true; }; streams.push(this); };
global.setTimeout = (fn, ms) => { timers.push({ fn, ms, cleared: false, fired: false }); return timers.length; };
global.clearTimeout = (id) => { if (id && timers[id - 1]) timers[id - 1].cleared = true; };
async function fireTimer() {           // chạy timer mới nhất còn hiệu lực (giả lập thời gian trôi tới lúc đó)
  for (let i = timers.length - 1; i >= 0; i--) {
    const t = timers[i];
    if (!t.cleared && !t.fired) { t.fired = true; await t.fn(); return t.ms; }
  }
  return null;
}
function failStream(es) { es.readyState = 2; if (es.onerror) es.onerror(new Event('error')); }   // server từ chối kênh (404)
// ---- widget (static/js/cskh_widget.js)
const CHAT_CONTEXT = 'customer_booking', BUSINESS_ID = D.business_id || null;
function appendMessage(who, text) { appended.push([who, String(text)]); }
function startHumanAgentStream(phone) { started.push(phone); }
function pageLangIsVi() { return !!D.vi; }
let chatHistory = [];
const chatMsgInput = { value: '', disabled: false, focus() { focused.push('msg'); } };
const chatSendBtn = { disabled: false };
const chatPhoneInput = { value: D.phone || '', focus() { focused.push('phone'); } };
const phoneContainer = { style: { display: 'none' } };
let chatTokenMem = null, shopReplyStream = null, shopReplySeen = null;
// ---- portal.html
let currentCustomerId = D.customer_id || null, shopName = '', eventSource = null, knownMessageCount = 0;
const ownPendingContents = [];
function renderStoredMessage(m) { rendered.push(String(m.content)); }
function appendNote(text) { notes.push(String(text)); }
function scrollToBottom() {}
function t(k) { return k; }
const chatBox = { innerHTML: '' };
global.document = { getElementById: (id) => (id === 'phone-container' ? phoneContainer : { textContent: '' }), title: '' };
eval(D.src);
(async () => {
  await eval('(async () => {\n' + D.scenario + '\n})()');
  console.log(JSON.stringify({
    calls: calls.map((c) => ({ url: c.url, method: (c.opts.method || 'GET'), headers: c.opts.headers || {}, body: c.opts.body || null })),
    streams: streams.map((s) => ({ url: s.url, closed: !!s.closed })),
    timers: timers.map((t) => ({ ms: t.ms, cleared: t.cleared, fired: t.fired })),
    appended, started, focused, rendered, notes, extra, input: chatMsgInput.value, msgDisabled: chatMsgInput.disabled,
    btnDisabled: chatSendBtn.disabled, phoneShown: phoneContainer.style.display, tok: store.bp_chat_token || chatTokenMem,
    eventSourceUrl: eventSource ? eventSource.url : null, chatBox: chatBox.innerHTML }));
})().catch((e) => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
'''


def run_node(test, src, scenario, **data):
    tmp = tempfile.mkdtemp(prefix='bp_id3_')
    try:
        js, payload = os.path.join(tmp, 'harness.js'), os.path.join(tmp, 'data.json')
        with io.open(js, 'w', encoding='utf-8') as f:
            f.write(NODE_HARNESS)
        with io.open(payload, 'w', encoding='utf-8') as f:
            json.dump(dict(data, src=src, scenario=scenario), f)
        r = subprocess.run(['node', js, payload], capture_output=True, text=True, encoding='utf-8', timeout=60)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lines = (r.stdout or '').strip().splitlines()
    test.assertTrue(lines, (r.stderr or '')[-800:])
    out = json.loads(lines[-1])
    test.assertNotIn('error', out, out.get('error'))
    return out


def widget_src(test, *names):
    s = read('static/js/cskh_widget.js')
    parts = [js_function(s, n) for n in names]
    missing = [n for n, p in zip(names, parts) if not p]
    test.assertFalse(missing, f'widget: không thấy function {missing}')
    extra = [js_line(s, r'^\s*const portalAuth = [^\n]*$'), js_line(s, r'^\s*let shopStreamKey = [^\n]*$')]
    test.assertTrue(all(extra), 'widget: thiếu portalAuth / trạng thái khoá nghe (shopStreamKey)')
    return '\n'.join(extra + parts)


def portal_src(test):
    s = read('templates/portal.html')
    names = ('portalChatToken', 'refreshFromServer', 'subscribeToRealtime', 'renewRealtime', 'loadHistory')
    parts = [js_function(s, n) for n in names]
    missing = [n for n, p in zip(names, parts) if not p]
    test.assertFalse(missing, f'portal.html: không thấy function {missing}')
    extra = [js_line(s, r'^\s*const portalHeaders = [^\n]*$'), js_line(s, r'^\s*let streamKey = [^\n]*$')]
    test.assertTrue(all(extra), 'portal.html: thiếu portalHeaders / trạng thái khoá nghe (streamKey)')
    return '\n'.join(extra + parts)


class _Base(core._Base):
    def setUp(self):
        super().setUp()
        SSE.clear()
        UPLOADS.clear()
        self.c = APP.test_client()

    # ---- khách chat thật qua trợ lý đặt lịch (secure_ai_generate) -> hội thoại web '<tiệm>:<SĐT>' có tin mang mã băm
    def chat(self, token, phone=WEB_PHONE, msg='Can I book a gel manicure tomorrow?'):
        body = {'business_id': NAIL, 'context': 'customer_booking', 'customer_phone': phone, 'customer_message': msg,
                'chat_token': token}
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test'}):
            r = self.c.post('/api/ai/studio/generate', json=body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])

    def get(self, token, cid=WEB_CID):
        return self.c.get('/api/portal/messages?customer_id=' + quote(cid, safe=''),
                          headers={'X-Chat-Token': token} if token else {})

    def contents(self, token, cid=WEB_CID):
        r = self.get(token, cid)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        return [m['content'] for m in r.get_json()['data']]

    def staff_reply(self, content, biz=NAIL, cid=WEB_CID, **extra):
        with self.c.session_transaction() as s:
            s['business_id'] = biz
            s['user_id'] = 'owner-' + biz
        r = self.c.post('/api/bot/messages', json=dict({'customer_id': cid, 'content': content}, **extra))
        with self.c.session_transaction() as s:
            s.clear()
        return r

    def seed_thread(self, rows, cid=WEB_CID, channel='web', ext=None):
        doc = {'id': cid, 'business_id': NAIL, 'channel': channel, 'phone': WEB_PHONE}
        if ext:
            doc['ext_user_id'] = ext
        DB.bot_customers.insert_one(doc)
        for st, content, h, at in rows:
            m = {'customer_id': cid, 'sender_type': st, 'content': content, 'business_id': NAIL, 'created_at': at,
                 'channel': channel}
            if h is not None:
                m['chat_token_hash'] = h
            DB.bot_messages.insert_one(m)


HA, HB, HW = T.chat_token_hash(TOKEN_A), T.chat_token_hash(TOKEN_B), T.chat_token_hash(TOKEN_W)
# A (kẻ gian gõ SĐT của nạn nhân) vào hội thoại TRƯỚC; B (chủ SĐT thật) nhắn SAU -> tin khách mới nhất là của B
TWO_BROWSERS = (('customer', 'A: hi, any slots Friday?', HA, '2026-10-01T08:00:00'),
                ('ai', 'A: we have 10:00 and 15:00', HA, '2026-10-01T08:00:05'),
                ('customer', 'B: I am Jane, can you move my 3pm gel?', HB, '2026-10-01T08:10:00'),
                ('ai', 'B: a staff member will reply here', HB, '2026-10-01T08:10:05'))


# ================================================================ 1. trả lời của nhân viên chỉ tới đúng trình duyệt
class StaffReplyAddressingTests(_Base):
    def test_reply_reaches_only_the_browser_it_answers(self):
        self.seed_thread(TWO_BROWSERS)
        r = self.staff_reply('Hi Jane, your 3pm gel is moved to 4pm')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        staff = [m for m in DB.bot_messages.find({'customer_id': WEB_CID, 'sender_type': 'staff'})]
        self.assertEqual([(m['content'], m.get('chat_token_hash')) for m in staff], [('Hi Jane, your 3pm gel is moved to 4pm', HB)])
        self.assertIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_B))
        # A vào hội thoại TRƯỚC trả lời này (luật cũ "trả lời sau lúc trình duyệt vào" từng đưa cho A) -> giờ không thấy
        a = self.contents(TOKEN_A)
        self.assertNotIn('Hi Jane, your 3pm gel is moved to 4pm', a)
        self.assertEqual(a, ['A: hi, any slots Friday?', 'A: we have 10:00 and 15:00'])
        # A nhắn tiếp (qua trang công khai, đúng trình duyệt) -> trả lời tiếp theo của nhân viên là của A, B không thấy
        r = self.c.post('/api/portal/messages', json={'customer_id': WEB_CID, 'content': 'A: is 10:00 still free?',
                                                      'chat_token': TOKEN_A})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.staff_reply('Yes, 10:00 is yours').status_code, 200)
        self.assertEqual(self.contents(TOKEN_A)[-2:], ['A: is 10:00 still free?', 'Yes, 10:00 is yours'])
        b = self.contents(TOKEN_B)
        self.assertNotIn('Yes, 10:00 is yours', b)
        self.assertNotIn('A: is 10:00 still free?', b)
        self.assertEqual(b[-1], 'Hi Jane, your 3pm gel is moved to 4pm')
        # tiệm vẫn thấy đủ mọi tin trong /ai_bot (không đổi)
        self.assertEqual(len(DB.bot_messages.find({'customer_id': WEB_CID})), 7)

    def test_reply_to_a_specific_customer_message(self):
        self.seed_thread(TWO_BROWSERS)
        r = self.staff_reply('A: Friday 10:00 is booked', reply_to='2026-10-01T08:00:00')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        self.assertIn('A: Friday 10:00 is booked', self.contents(TOKEN_A))
        self.assertNotIn('A: Friday 10:00 is booked', self.contents(TOKEN_B))
        n = len(DB.bot_messages.find({}))
        # tin không có trong hội thoại / tin AI (không phải tin khách) / kiểu sai: không đoán, không ghi gì
        for bad, code in (('2026-10-01T09:59:59', 404), ('2026-10-01T08:00:05', 404), (123, 400), ({'$ne': None}, 400),
                          ('', 400), (['2026-10-01T08:00:00'], 400)):
            r = self.staff_reply('should not be stored', reply_to=bad)
            self.assertEqual(r.status_code, code, (bad, r.get_data(as_text=True)[:200]))
            self.assertFalse(r.get_json()['success'])
            self.assertTrue(r.get_json()['message'])
        self.assertEqual(len(DB.bot_messages.find({})), n)
        self.assertNotIn('should not be stored', json.dumps(DB.bot_messages.find({})))

    def test_reply_to_a_message_without_a_browser_token_is_not_published(self):
        self.seed_thread(TWO_BROWSERS + (('customer', 'legacy widget: hello?', None, '2026-10-01T08:20:00'),))
        self.assertEqual(self.staff_reply('Reply to the legacy widget').status_code, 200)
        doc = DB.bot_messages.find({'customer_id': WEB_CID, 'sender_type': 'staff'})[-1]
        self.assertEqual(doc.get('chat_token_hash'), '')        # có chủ đích: không trình duyệt nào trên trang công khai
        for tok in (TOKEN_A, TOKEN_B):
            self.assertNotIn('Reply to the legacy widget', self.contents(tok))
        self.assertIsNone(T.chat_token_hash(''))                 # '' không bao giờ là mã băm của 1 trình duyệt

    def test_legacy_staff_replies_keep_the_joined_after_rule(self):
        # trả lời cũ (ghi trước bản sửa / từ /super_admin): không có trường mã băm -> chỉ trình duyệt đã vào trước trả lời đó
        self.seed_thread(TWO_BROWSERS[:2] + (('staff', 'S1: legacy reply before B joined', None, '2026-10-01T08:05:00'),)
                         + TWO_BROWSERS[2:] + (('staff', 'S2: legacy reply after both joined', None, '2026-10-01T08:15:00'),))
        self.assertEqual(self.contents(TOKEN_A), ['A: hi, any slots Friday?', 'A: we have 10:00 and 15:00',
                                                  'S1: legacy reply before B joined', 'S2: legacy reply after both joined'])
        self.assertEqual(self.contents(TOKEN_B), ['B: I am Jane, can you move my 3pm gel?', 'B: a staff member will reply here',
                                                  'S2: legacy reply after both joined'])

    def test_real_widget_chat_then_staff_reply(self):
        # luồng thật: 2 trình duyệt chat qua trợ lý đặt lịch (secure_ai_generate) cùng 1 SĐT, nhân viên trả lời
        self.chat(TOKEN_A, msg='Can I book Friday?')
        time.sleep(0.03)                                         # created_at khác nhau (đồng hồ Windows ~15 ms)
        self.chat(TOKEN_B, msg='Please move my booking')
        self.assertEqual(self.staff_reply('Moved to 4pm, see you!').status_code, 200)
        self.assertIn('Moved to 4pm, see you!', self.contents(TOKEN_B))
        self.assertNotIn('Moved to 4pm, see you!', self.contents(TOKEN_A))

    def test_platform_threads_still_go_out_on_their_channel(self):
        cid = inbox_channels.record(NAIL, 'sms', '+61412345678', 'Can I move my booking?', 'customer', phone='+61412345678')
        with patch.object(inbox_channels, 'deliver', MagicMock(return_value={'status': 'sent'})) as d:
            r = self.staff_reply('Sure, done', cid=cid)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        self.assertEqual((r.get_json()['channel'], r.get_json()['delivery']), ('sms', {'status': 'sent'}))
        d.assert_called_once_with(NAIL, 'sms', '+61412345678', 'Sure, done', 'staff')

    def test_other_shop_cannot_reply(self):
        self.seed_thread(TWO_BROWSERS)
        n = len(DB.bot_messages.find({}))
        self.assertEqual(self.staff_reply('hijack', biz=OTHER_NAIL).status_code, 403)
        self.assertEqual(len(DB.bot_messages.find({})), n)


# ================================================================ 2 + 3. kênh nghe: khoá ngắn hạn, không mã chat trong URL
class StreamKeyTests(_Base):
    def test_raw_chat_token_is_never_accepted_from_the_url(self):
        self.chat(TOKEN_A)
        q = 'customer_id=' + quote(WEB_CID, safe='') + '&chat_token=' + quote(TOKEN_A, safe='')
        self.assertEqual(self.c.get('/api/portal/messages?' + q).status_code, 404)
        self.assertEqual(self.c.get('/api/portal/stream?' + q).status_code, 404)
        self.assertEqual(SSE, [])
        n = len(DB.bot_messages.find({}))
        r = self.c.post('/api/portal/messages?chat_token=' + quote(TOKEN_A, safe=''),
                        json={'customer_id': WEB_CID, 'content': 'Cancel my booking'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(DB.bot_messages.find({})), n)
        r = self.c.post('/api/portal/upload?chat_token=' + quote(TOKEN_A, safe=''), content_type='multipart/form-data',
                        data={'customer_id': WEB_CID, 'file': (io.BytesIO(b'GIF89a'), 'a.gif')})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(UPLOADS, [])
        # header / body vẫn là đường chính
        self.assertEqual(self.get(TOKEN_A).status_code, 200)
        self.assertEqual(self.c.post('/api/portal/messages', json={'customer_id': WEB_CID, 'content': 'hi',
                                                                   'chat_token': TOKEN_A}).status_code, 200)
        r = self.c.post('/api/portal/upload', content_type='multipart/form-data',
                        data={'customer_id': WEB_CID, 'chat_token': TOKEN_A, 'file': (io.BytesIO(b'GIF89a'), 'a.gif')})
        self.assertEqual(r.status_code, 200)
        r = self.c.get('/api/portal/stream?customer_id=' + quote(WEB_CID, safe=''), headers={'X-Chat-Token': TOKEN_A})
        self.assertEqual(r.status_code, 200)

    def test_messages_hand_out_a_short_lived_signed_stream_key(self):
        self.chat(TOKEN_A)
        now = time.time()
        with clock(now):
            j = self.get(TOKEN_A).get_json()
        key = j.get('stream_key')
        m = KEY_RE.match(key or '')
        self.assertTrue(m, j)
        self.assertEqual(j.get('stream_key_ttl'), 600)
        self.assertEqual(int(m.group(1)), int(now) + 600)
        for secret in (TOKEN_A, HA, quote(TOKEN_A, safe='')):     # khoá không chứa mã chat hay mã băm của trình duyệt
            self.assertNotIn(secret, key)
        expect = hmac.new(SECRET.encode(), f'portal-stream|{WEB_CID}|{HA}|{int(now) + 600}'.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(m.group(2), expect)                      # HMAC khoá bí mật của app trên hội thoại + mã băm + hạn
        with clock(now + 30):
            r = self.c.get('/api/portal/stream?customer_id=' + quote(WEB_CID, safe='') + '&stream_key=' + quote(key, safe=''))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        stage = SSE[-1]
        self.assertTrue(sse_hits(stage, change({'customer_id': WEB_CID, 'sender_type': 'staff', 'chat_token_hash': HA})))
        self.assertFalse(sse_hits(stage, change({'customer_id': WEB_CID, 'sender_type': 'staff', 'chat_token_hash': HB})))
        # không có khoá bí mật của app -> không cấp khoá (không bao giờ ký bằng khoá rỗng / khoá đoán được)
        with patch.dict(APP.config, {'SECRET_KEY': None}):
            self.assertIsNone(self.get(TOKEN_A).get_json().get('stream_key'))

    def test_stream_key_is_bound_to_thread_browser_secret_and_expiry(self):
        self.chat(TOKEN_A)
        self.chat(TOKEN_A, phone='0499999999')                    # cùng trình duyệt, hội thoại khác
        other = f'{NAIL}:0499999999'
        now = time.time()
        with clock(now):
            key = self.get(TOKEN_A).get_json()['stream_key']

        def stream(cid, k, at=now + 1):
            with clock(at):
                return self.c.get('/api/portal/stream?customer_id=' + quote(cid, safe='') + '&stream_key=' + quote(k, safe=''))

        self.assertEqual(stream(WEB_CID, key).status_code, 200)
        self.assertEqual(stream(WEB_CID, key, now + 590).status_code, 200)
        SSE.clear()
        exp, sig = key.split('.')
        flipped = sig[:-1] + ('0' if sig[-1] != '0' else '1')
        bad = [stream(other, key),                                # khoá của hội thoại khác
               stream(WEB_CID, key, now + 601),                   # hết hạn
               stream(WEB_CID, f'{int(exp) + 1}.{sig}'),          # sửa hạn
               stream(WEB_CID, f'{exp}.{flipped}'),               # sửa chữ ký
               stream(WEB_CID, f'{exp}.{sig.upper()}'),
               stream(WEB_CID, TOKEN_A), stream(WEB_CID, HA), stream(WEB_CID, ''), stream(WEB_CID, 'x' * 5000)]
        with patch.dict(APP.config, {'SECRET_KEY': 'another-secret'}):  # khoá bí mật khác (đổi khoá / máy khác) -> khoá cũ vô hiệu
            bad.append(stream(WEB_CID, key))
        # khoá hạn quá xa (vượt 10 phút) dù chữ ký đúng -> từ chối
        far = int(now) + 7 * 86400
        bad.append(stream(WEB_CID, f'{far}.' + hmac.new(SECRET.encode(), f'portal-stream|{WEB_CID}|{HA}|{far}'.encode(),
                                                         hashlib.sha256).hexdigest()))
        # hội thoại SMS (kể cả khi có tin mang mã băm và chữ ký đúng) -> không bao giờ mở ở trang công khai
        sms = inbox_channels.record(NAIL, 'sms', '+61412345678', 'Can I move my booking?', 'customer', phone='+61412345678')
        DB.bot_messages.insert_one({'customer_id': sms, 'sender_type': 'customer', 'content': 'x', 'business_id': NAIL,
                                    'created_at': '2026-10-01T08:00:00', 'chat_token_hash': HA})
        with clock(now):
            sms_key = NS['_portal_stream_key'](sms, HA)
        bad.append(stream(sms, sms_key))
        self.assertEqual([r.status_code for r in bad], [404] * len(bad))
        self.assertEqual(SSE, [])
        # cùng trình duyệt lấy khoá của hội thoại kia qua đúng đường -> mở được hội thoại kia
        with clock(now):
            k2 = self.get(TOKEN_A, other).get_json()['stream_key']
        self.assertEqual(stream(other, k2).status_code, 200)

    def test_stream_signals_only_this_browser(self):
        self.seed_thread(TWO_BROWSERS)
        now = time.time()
        with clock(now):
            ka = self.get(TOKEN_A).get_json()['stream_key']
            r = self.c.get('/api/portal/stream?customer_id=' + quote(WEB_CID, safe='') + '&stream_key=' + quote(ka, safe=''))
        self.assertEqual(r.status_code, 200)
        stage = SSE[-1]
        hit = {
            'A: tin của chính nó': change({'customer_id': WEB_CID, 'sender_type': 'customer', 'chat_token_hash': HA}),
            'A: trả lời của nhân viên cho nó': change({'customer_id': WEB_CID, 'sender_type': 'staff', 'chat_token_hash': HA}),
            'A: nhân viên đọc tin của nó (update)': change({'customer_id': WEB_CID, 'sender_type': 'customer', 'chat_token_hash': HA,
                                                            'is_read': True}, op='update'),
            'trả lời cũ không có mã băm': change({'customer_id': WEB_CID, 'sender_type': 'staff'}),
            'xoá tin': {'operationType': 'delete', 'ns': {'coll': 'bot_messages'}},
        }
        miss = {
            'B nhắn tin': change({'customer_id': WEB_CID, 'sender_type': 'customer', 'chat_token_hash': HB}),
            'AI trả lời B': change({'customer_id': WEB_CID, 'sender_type': 'ai', 'chat_token_hash': HB}),
            'nhân viên trả lời B': change({'customer_id': WEB_CID, 'sender_type': 'staff', 'chat_token_hash': HB}),
            'trả lời không công khai': change({'customer_id': WEB_CID, 'sender_type': 'staff', 'chat_token_hash': ''}),
            'tin khách không mã': change({'customer_id': WEB_CID, 'sender_type': 'customer'}),
            'bot_customers đổi last_message': change({'id': WEB_CID, 'business_id': NAIL, 'last_message': 'B: ...'},
                                                     coll='bot_customers', op='update'),
            'hội thoại khác': change({'customer_id': f'{NAIL}:0499999999', 'sender_type': 'staff', 'chat_token_hash': HA}),
            'tiệm khác': change({'customer_id': f'{OTHER_NAIL}:{WEB_PHONE}', 'sender_type': 'customer', 'chat_token_hash': HA}),
        }
        for name, ev in hit.items():
            self.assertTrue(sse_hits(stage, ev), name)
        for name, ev in miss.items():
            self.assertFalse(sse_hits(stage, ev), name)
        self.assertNotIn('fullDocument.business_id', json.dumps(stage))


# ================================================================ 4. widget + portal.html thật (node) <-> route thật
class _StreamFlow(_Base):
    def _keys(self):
        """2 phản hồi THẬT của GET /api/portal/messages (cách nhau 60 giây -> 2 khoá khác nhau)."""
        self.chat(TOKEN_W)
        now = time.time()
        with clock(now):
            j1 = self.get(TOKEN_W).get_json()
        with clock(now + 60):
            j2 = self.get(TOKEN_W).get_json()
        self.assertTrue(j1['stream_key'] and j2['stream_key'] and j1['stream_key'] != j2['stream_key'], (j1, j2))
        return now, j1, j2

    def _check_stream_url(self, url, key, at):
        u = urlparse(url)
        self.assertEqual(u.path, '/api/portal/stream', url)
        q = parse_qs(u.query)
        self.assertEqual(q.get('customer_id'), [WEB_CID], url)
        self.assertEqual(q.get('stream_key'), [key], url)
        self.assertNotIn('chat_token', q, url)
        self.assertNotIn(TOKEN_W, url)
        self.assertNotIn(HW, url)
        n = len(SSE)
        with clock(at):
            r = self.c.get(url)                                   # đúng URL trang dựng -> route thật
        self.assertEqual(r.status_code, 200, (url, r.get_data(as_text=True)[:200]))
        self.assertEqual(len(SSE), n + 1)
        self.assertTrue(sse_hits(SSE[-1], change({'customer_id': WEB_CID, 'sender_type': 'staff', 'chat_token_hash': HW})))
        self.assertFalse(sse_hits(SSE[-1], change({'customer_id': WEB_CID, 'sender_type': 'staff', 'chat_token_hash': HA})))


class WidgetStreamFlowTests(_StreamFlow):
    def test_widget_listens_with_the_signed_key_and_renews_it(self):
        now, j1, j2 = self._keys()
        src = widget_src(self, 'getChatToken', 'fetchShopReplies', 'startShopReplyStream', 'openShopReplyStream',
                         'renewShopReplyStream', 'keepThreadForTeam')
        scenario = '''
          await startShopReplyStream('0412345678');
          extra.renewMs = timers.length ? timers[timers.length - 1].ms : null;
          await fireTimer();                       // ~8 phút sau: gia hạn trước khi khoá hết hạn
          failStream(streams[streams.length - 1]); // server từ chối kênh (vd máy ngủ quá 10 phút)
          extra.retryMs = timers[timers.length - 1].ms;
          await fireTimer();
          await keepThreadForTeam('biz_nail:0412345678', 'Hello there');
        '''
        out = run_node(self, src, scenario, business_id=NAIL, store={'bp_chat_token': TOKEN_W},
                       responses=[{'status': 200, 'body': j1}, {'status': 200, 'body': j2}])
        self.assertEqual(out['tok'], TOKEN_W)
        gets = [c for c in out['calls'] if c['method'] == 'GET']
        posts = [c for c in out['calls'] if c['method'] == 'POST']
        self.assertEqual(len(gets), 4, out['calls'])              # mở + gia hạn + mở lại sau lỗi + keepThreadForTeam
        for g in gets:
            self.assertTrue(g['url'].startswith('/api/portal/messages?customer_id='), g)
            self.assertEqual(g['headers'].get('X-Chat-Token'), TOKEN_W, g)
            self.assertNotIn(TOKEN_W, g['url'])
        self.assertEqual(len(posts), 1)
        self.assertEqual(json.loads(posts[0]['body']).get('chat_token'), TOKEN_W)   # mã gốc chỉ trong body
        streams = out['streams']
        self.assertEqual(len(streams), 3, streams)
        self.assertEqual([s['closed'] for s in streams], [True, True, False])
        self.assertEqual(out['extra']['renewMs'], (600 - 120) * 1000)                 # gia hạn 2 phút trước khi hết hạn
        self.assertEqual(out['extra']['retryMs'], 3000)                               # kênh bị từ chối -> gia hạn ngay
        self._check_stream_url(streams[0]['url'], j1['stream_key'], now + 5)
        self._check_stream_url(streams[1]['url'], j2['stream_key'], now + 65)
        self._check_stream_url(streams[2]['url'], j2['stream_key'], now + 70)
        with clock(now + 601):                                   # khoá đầu hết hạn -> route thật từ chối (trang tự gia hạn)
            self.assertEqual(self.c.get(streams[0]['url']).status_code, 404)

    def test_widget_without_a_stream_key_does_not_fall_back_to_the_chat_token(self):
        src = widget_src(self, 'getChatToken', 'fetchShopReplies', 'startShopReplyStream', 'openShopReplyStream',
                         'renewShopReplyStream')
        out = run_node(self, src, "await startShopReplyStream('0412345678');", business_id=NAIL, store={'bp_chat_token': TOKEN_W},
                       responses=[{'status': 200, 'body': {'success': True, 'data': []}}])
        self.assertEqual(out['streams'], [])
        out = run_node(self, src, "await startShopReplyStream('0412345678');", business_id=NAIL, store={'bp_chat_token': TOKEN_W},
                       responses=[{'status': 404, 'body': {'success': False, 'message': 'not found'}}])
        self.assertEqual(out['streams'], [])                      # hội thoại chưa lưu -> không nghe

    def test_widget_gives_up_after_repeated_renewal_failures(self):
        now, j1, _j2 = self._keys()
        src = widget_src(self, 'getChatToken', 'fetchShopReplies', 'startShopReplyStream', 'openShopReplyStream',
                         'renewShopReplyStream')
        scenario = '''
          await startShopReplyStream('0412345678');
          failStream(streams[0]);
          for (let i = 0; i < 10; i++) { if (await fireTimer() === null) break; }
          await startShopReplyStream('0412345678');   // tin nhắn tiếp theo của khách mở lại kênh
        '''
        out = run_node(self, src, scenario, business_id=NAIL, store={'bp_chat_token': TOKEN_W},
                       responses=[{'status': 200, 'body': j1}, {'status': 404, 'body': {'success': False}},
                                  {'status': 404, 'body': {'success': False}}, {'status': 404, 'body': {'success': False}},
                                  {'status': 404, 'body': {'success': False}}, {'status': 404, 'body': {'success': False}},
                                  {'status': 404, 'body': {'success': False}}, {'status': 200, 'body': j1}])
        gets = [c for c in out['calls'] if c['method'] == 'GET']
        self.assertEqual(len(gets), 1 + 6 + 1, out['calls'])    # mở + 6 lần gia hạn hỏng (1 + 5 lần thử lại) + mở lại
        self.assertEqual(len(out['streams']), 2, out['streams'])
        self.assertTrue(out['streams'][0]['closed'])
        self.assertFalse(out['streams'][1]['closed'])
        self._check_stream_url(out['streams'][1]['url'], j1['stream_key'], now + 5)


class PortalPageFlowTests(_StreamFlow):
    def test_portal_page_listens_with_the_signed_key_and_renews_it(self):
        now, j1, j2 = self._keys()
        scenario = '''
          await loadHistory();
          extra.renewMs = timers.length ? timers[timers.length - 1].ms : null;
          await fireTimer();                        // gia hạn trước khi khoá hết hạn
          failStream(streams[streams.length - 1]); // server từ chối kênh
          extra.retryMs = timers[timers.length - 1].ms;
          await fireTimer();
        '''
        out = run_node(self, portal_src(self), scenario, customer_id=WEB_CID, store={'bp_chat_token': TOKEN_W},
                       responses=[{'status': 200, 'body': j1}, {'status': 200, 'body': j2}])
        self.assertEqual(out['rendered'][:2], ['Can I book a gel manicure tomorrow?', 'ok'])
        gets = [c for c in out['calls'] if c['method'] == 'GET']
        self.assertEqual(len(gets), 3, out['calls'])
        for g in gets:
            self.assertEqual(g['headers'].get('X-Chat-Token'), TOKEN_W, g)
            self.assertNotIn(TOKEN_W, g['url'])
        streams = out['streams']
        self.assertEqual([s['closed'] for s in streams], [True, True, False], streams)
        self.assertEqual(out['eventSourceUrl'], streams[-1]['url'])
        self.assertEqual((out['extra']['renewMs'], out['extra']['retryMs']), ((600 - 120) * 1000, 3000))
        self._check_stream_url(streams[0]['url'], j1['stream_key'], now + 5)
        self._check_stream_url(streams[1]['url'], j2['stream_key'], now + 65)
        self._check_stream_url(streams[2]['url'], j2['stream_key'], now + 70)

    def test_portal_page_keeps_retrying_slowly_when_the_server_is_down(self):
        now, j1, _j2 = self._keys()
        scenario = '''
          await loadHistory();
          failStream(streams[0]);                  // máy chủ từ chối kênh, rồi tải tin cũng lỗi một lúc
          extra.fired = [];
          for (let i = 0; i < 7; i++) extra.fired.push(await fireTimer());
        '''
        down = [{'status': 503, 'body': None}, {'status': 500, 'body': {'success': False}}]
        out = run_node(self, portal_src(self), scenario, customer_id=WEB_CID, store={'bp_chat_token': TOKEN_W},
                       responses=[{'status': 200, 'body': j1}] + down * 3 + [{'status': 200, 'body': j1}])
        self.assertEqual(out['extra']['fired'], [3000, 30000, 30000, 30000, 30000, 30000, 300000])   # thưa dần, không bỏ hẳn
        self.assertEqual(len([c for c in out['calls'] if c['method'] == 'GET']), 8)
        self.assertEqual([s['closed'] for s in out['streams']], [True, False], out['streams'])
        self._check_stream_url(out['streams'][1]['url'], j1['stream_key'], now + 5)

    def test_portal_page_without_access_or_key_opens_no_stream(self):
        src = portal_src(self)
        out = run_node(self, src, 'await loadHistory();', customer_id=WEB_CID, store={'bp_chat_token': TOKEN_W},
                       responses=[{'status': 200, 'body': {'success': True, 'data': [], 'shop_name': 'Rose Nails'}}])
        self.assertEqual(out['streams'], [])
        self.assertEqual(out['notes'], ['portal_empty_note'])
        out = run_node(self, src, 'await loadHistory();', customer_id=WEB_CID, store={},
                       responses=[{'status': 404, 'body': {'success': False}}])
        self.assertEqual(out['streams'], [])
        self.assertIn('portal_err_no_access', out['chatBox'])

    def test_pages_never_put_the_chat_token_in_a_url(self):
        w, p = read('static/js/cskh_widget.js'), read('templates/portal.html')
        node_check(self, 'static/js/cskh_widget.js', w)
        for name, s in (('widget', w), ('portal.html', p)):
            self.assertNotIn('chat_token=', s, name)
            self.assertNotRegex(s, r'[?&]chat_token', name)
            self.assertRegex(s, r'stream_key=', name)
        for i, m in enumerate(re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', p, re.S)):
            code = re.sub(r'\{\{.*?\}\}', '0', m.group(1), flags=re.S)
            code = re.sub(r'\{%.*?%\}|\{#.*?#\}', '', code, flags=re.S)
            node_check(self, f'portal.html script#{i}', code)


# ================================================================ 5. widget: lỗi khi gửi cho nhân viên BitPaw
class HumanAgentSendTests(_Base):
    def _real(self, phone):
        r = self.c.post('/api/cskh/chat/send', json={'phone': phone, 'content': 'I need a demo'})
        return {'status': r.status_code, 'body': r.get_json()}

    def test_send_errors_are_shown_and_no_stream_is_started(self):
        bad, good = self._real('sms:+61412345678'), self._real('0412 345 678')
        self.assertEqual((bad['status'], good['status']), (400, 200))
        src = widget_src(self, 'handleHumanAgentSubmit', 'humanSendError', 'getChatToken')   # identity4: gửi kèm mã chat (header)
        scenario = "await handleHumanAgentSubmit(D.msg, D.phone);"
        cases = {
            'ok': good,
            'bad_phone': bad,
            'rate_limited': {'status': 429, 'body': {'success': False, 'message': 'Too Many Requests'}},
            'server_error': {'status': 503, 'body': None},                    # trang lỗi HTML, không phải JSON
            'server_500_json': {'status': 500, 'body': {'success': False, 'message': 'boom'}},
            'refused_200': {'status': 200, 'body': {'success': False, 'message': 'x'}},
            'offline': {'throw': True},
        }
        expect = {   # từ khoá phải có trong câu báo lỗi (EN, VI)
            'bad_phone': (('NOT sent', 'phone number'), ('CHƯA được gửi', 'số điện thoại')),
            'rate_limited': (('NOT sent', 'too quickly', 'minute'), ('CHƯA được gửi', 'quá nhanh', 'phút')),
            'server_error': (('NOT sent', 'try again'), ('CHƯA được gửi', 'thử lại')),
            'server_500_json': (('NOT sent', 'try again'), ('CHƯA được gửi', 'thử lại')),
            'refused_200': (('NOT sent', 'try again'), ('CHƯA được gửi', 'thử lại')),
            'offline': (('NOT sent', 'connection'), ('CHƯA được gửi', 'kết nối')),
        }
        for name, resp in cases.items():
            for vi in (False, True):
                phone = 'sms:+61412345678' if name == 'bad_phone' else '0412 345 678'
                out = run_node(self, src, scenario, vi=vi, msg='I need a demo', phone=phone, responses=[resp])
                sends = [c for c in out['calls'] if c['url'] == '/api/cskh/chat/send']
                self.assertEqual(len(sends), 1, (name, out['calls']))
                self.assertEqual(json.loads(sends[0]['body']), {'phone': phone, 'content': 'I need a demo'})
                self.assertEqual(out['appended'][0], ['user', 'I need a demo'], name)
                self.assertFalse(out['msgDisabled'] or out['btnDisabled'], name)   # mở khoá lại ô nhập
                if name == 'ok':
                    self.assertEqual(out['started'], [phone], name)
                    self.assertEqual(out['appended'], [['user', 'I need a demo']], name)
                    self.assertEqual(out['input'], '')
                    continue
                self.assertEqual(out['started'], [], (name, vi))          # không nghe như thể đã gửi được
                self.assertEqual(len(out['appended']), 2, (name, out['appended']))
                text = out['appended'][1][1]
                for word in expect[name][1 if vi else 0]:
                    self.assertIn(word, text, (name, vi, text))
                self.assertEqual(out['input'], 'I need a demo', name)    # giữ lại tin để gửi lại
                if name == 'bad_phone':
                    self.assertEqual(out['focused'][-1], 'phone')
                    self.assertEqual(out['phoneShown'], '')               # hiện lại ô SĐT để sửa
                else:
                    self.assertEqual(out['focused'][-1], 'msg')

    def test_corrected_phone_gets_its_own_reply_stream(self):
        # khách gõ số sai rồi bấm "Talk to Human Agent" (kênh nghe mở cho số sai), gửi -> 400 + báo lỗi; sửa số, gửi lại -> 200:
        # kênh nghe phải chuyển sang số mới (trước đây giữ mãi kênh của số đầu tiên -> trả lời của nhân viên không bao giờ hiện)
        bad, good = self._real('sms:+61412345678'), self._real('0412 345 678')
        s = read('static/js/cskh_widget.js')
        lets = [js_line(s, r'^\s*let humanChatStream = [^\n]*$'), js_line(s, r'^\s*let renderedStaffMessageCount = [^\n]*$')]
        self.assertTrue(all(lets), lets)
        lets += [x for x in (js_line(s, r'^\s*let humanChatPhone = [^\n]*$'),) if x]   # trạng thái thêm của bản sửa (nếu có)
        # identity4: kênh nghe 'Talk to Human Agent' mở bằng khoá ngắn hạn (stream_key) của GET /api/cskh/chat/messages, không chỉ SĐT
        lets.append(js_line(s, r'^\s*let humanStreamKey = [^\n]*$'))
        self.assertTrue(lets[-1], 'widget: thiếu trạng thái khoá nghe humanStreamKey')
        src = widget_src(self, 'handleHumanAgentSubmit', 'humanSendError', 'startHumanAgentStream', 'fetchHumanAgentReplies',
                         'openHumanAgentStream', 'renewHumanAgentStream', 'getChatToken')
        src = '\n'.join(lets + [src])
        k1, k2 = '1700000600.' + 'ab' * 32, '1700000660.' + 'cd' * 32
        scenario = '''
          const tick = () => new Promise((r) => setImmediate(r));
          startHumanAgentStream('sms:+61412345678');
          await tick();
          await handleHumanAgentSubmit('I need a demo', 'sms:+61412345678');
          extra.afterBad = streams.length;
          await handleHumanAgentSubmit('I need a demo', '0412 345 678');
          for (let i = 0; i < 5; i++) await tick();
        '''
        staff = {'status': 200, 'body': {'success': True, 'stream_key': k2, 'stream_key_ttl': 600, 'messages': [
            {'sender_type': 'customer', 'content': 'I need a demo'}, {'sender_type': 'staff', 'content': 'Hi! A demo link is on its way'}]}}
        for vi in (False, True):
            out = run_node(self, src, scenario, vi=vi, store={'bp_chat_token': TOKEN_W},
                           responses=[{'status': 200, 'body': {'success': True, 'messages': [], 'stream_key': k1, 'stream_key_ttl': 600}},
                                      bad, good, staff])
            self.assertEqual(out['extra']['afterBad'], 1)                           # lỗi -> không mở thêm kênh nào
            self.assertEqual([(st['url'], st['closed']) for st in out['streams']],
                             [('/api/stream/cskh_chat?phone=sms%3A%2B61412345678&stream_key=' + k1, True),
                              ('/api/stream/cskh_chat?phone=0412%20345%20678&stream_key=' + k2, False)])
            for c in out['calls']:                                                  # mã chat chỉ trong header, không trong URL
                self.assertEqual(c['headers'].get('X-Chat-Token'), TOKEN_W, c)
                self.assertNotIn(TOKEN_W, c['url'])
            texts = [t for _w, t in out['appended']]
            self.assertIn('CHƯA được gửi' if vi else 'NOT sent', texts[1])
            self.assertEqual(texts[-1], 'Hi! A demo link is on its way')            # trả lời của nhân viên hiện ra
            self.assertEqual(out['input'], '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
