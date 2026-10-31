# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 vòng 3, khu "identity4" (hội thoại web khoá theo SĐT khách tự gõ):
  1. Hộp thư của chủ tiệm (ai_bot.html, crm_automation.html) hiện tin khách đến từ thiết bị nào ("Device A / B" — nhãn ngắn,
     ổn định, dựng từ chat_token_hash, KHÔNG BAO GIỜ hiện mã băm); ô soạn tin gửi reply_to = tin khách đang được trả lời (mặc định
     tin khách mới nhất đang hiện lúc bấm Gửi; >= 2 thiết bị -> thanh phía trên ô soạn tin hiện rõ thiết bị nhận và cho chọn).
     /api/bot/messages ghi trả lời kèm mã băm của ĐÚNG tin đó và trả device ('A' / 'B'..., None = trả lời không hiện trên trang
     chat của khách) — ca thử của người kiểm tra: kẻ gian gõ SĐT nạn nhân nhắn SAU nạn nhân, nhân viên chọn thiết bị của nạn nhân
     -> chỉ nạn nhân thấy trả lời.
  2. Super admin (/api/superadmin/chat/messages POST, super_admin.html) trên hội thoại web (của tiệm hay lead landing) theo ĐÚNG
     luật trên: trả lời mang mã băm của tin được trả lời (trước đây không có mã -> mọi trình duyệt đã gõ SĐT đó đọc được).
  3. /api/cskh/chat/send: không lưu được (không có DB / DB lỗi) -> 503 VI / EN (trước đây success:true).
  4. 'Talk to Human Agent' trên landing (bitpaw_leads): /api/cskh/chat/messages + /api/stream/cskh_chat cần cùng bằng chứng trình
     duyệt như /portal (mã chat qua header, khoá nghe ngắn hạn cho EventSource); widget THẬT (cskh_widget.js) gửi mã chat, chỉ
     thấy trả lời gửi cho chính nó, nghe bằng khoá ngắn hạn và tự gia hạn.
Luồng thật đầu-cuối: mã JS THẬT của các trang (ai_bot.html, crm_automation.html, super_admin.html, bp_reply_target.js,
cskh_widget.js) chạy trong node (DOM / fetch / EventSource / setTimeout giả) với phản hồi THẬT của các route app.py (Flask test
client, DB giả trong RAM), rồi đúng yêu cầu mà trang gửi đi được gửi lại route thật.
Dùng lại DB giả + route đã nạp của test_phase2_fix3_identity3.py (-> test_phase2_receptionist_core.py): không import app.py thật,
không MongoDB thật, không mạng / DeepSeek / Twilio; hàm của app.py lấy nguyên mã nguồn qua ast.
Chạy: python scripts/tests/test_phase2_fix4_identity4.py
"""
import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_fix3_identity3 as id3  # noqa: E402  (DB giả, route portal / bot / cskh send, harness node của widget)

core = id3.core
DB, T, NS, ROOT, APP = id3.DB, id3.T, id3.NS, id3.ROOT, id3.APP
TOKEN_A, TOKEN_B, TOKEN_W = id3.TOKEN_A, id3.TOKEN_B, id3.TOKEN_W
HA, HB, HW = id3.HA, id3.HB, id3.HW
WEB_CID, NAIL, OTHER_NAIL = id3.WEB_CID, id3.NAIL, id3.OTHER_NAIL
TWO_BROWSERS = id3.TWO_BROWSERS
# ca thử của người kiểm tra: TWO_BROWSERS + kẻ gian (A) nhắn thêm 1 tin SAU tin cuối của nạn nhân (B)
ATTACK = TWO_BROWSERS + (('customer', 'A: any update?', HA, '2026-10-01T08:20:00'),)
B_MSG_AT = '2026-10-01T08:10:00'
LEAD_PHONE = '0412 345 678'
LEAD_CID = 'bitpaw_leads:' + LEAD_PHONE
clock, change, sse_hits, read, js_function, js_line = id3.clock, id3.change, id3.sse_hits, id3.read, id3.js_function, id3.js_line

# ---------------------------------------------------------------- hàm mới / thêm của app.py (lấy nguyên mã nguồn qua ast)
_FUNCS = ('_web_device_labels', '_web_reply_stamp', '_cskh_lead_conversation', 'api_cskh_chat_messages', 'stream_cskh_chat',
          'superadmin_chat_send_message', 'api_bot_messages_list')
SUPER = {'on': False}
NS['_is_superadmin'] = lambda: SUPER['on']
for _name in _FUNCS:
    _node = next((n for n in core._TREE.body if isinstance(n, ast.FunctionDef) and n.name == _name), None)
    if _node is None:   # mã cũ chưa có hàm này
        continue
    _node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), f'app.py::{_name}', 'exec'), NS)
APP.add_url_rule('/api/cskh/chat/messages', 'cskh_list', NS['api_cskh_chat_messages'], methods=['GET'])
APP.add_url_rule('/api/stream/cskh_chat', 'cskh_stream', NS['stream_cskh_chat'], methods=['GET'])
APP.add_url_rule('/api/superadmin/chat/messages/<path:customer_id>', 'sa_send', NS['superadmin_chat_send_message'], methods=['POST'])
APP.add_url_rule('/api/bot/messages', 'bot_list', NS['api_bot_messages_list'], methods=['GET'])


def js_block(src, start):
    """Cắt 1 khối JS bắt đầu bằng chuỗi `start` (vd 'window.handleUserSubmit = async function') tới hết cặp ngoặc nhọn + ';'."""
    i = src.find(start)
    if i < 0:
        return None
    j = src.index('{', i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == '{':
            depth += 1
        elif src[k] == '}':
            depth -= 1
            if depth == 0:
                return src[i:k + 1] + ';'
    return None


# ---------------------------------------------------------------- node: DOM / fetch giả cho trang hộp thư
NODE_DOM = r'''
const fs = require('fs');
const D = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const calls = [], toasts = [], extra = {};
function El(tag, id) {
  this.tagName = String(tag).toLowerCase(); this.id = id || ''; this.children = []; this.attrs = {}; this.listeners = {};
  this._cls = new Set(); this.textContent = ''; this.innerHTML = ''; this.disabled = false; this.selected = false;
  this.className = ''; this.style = {}; this.placeholder = ''; this.parentNode = null; this._value = '';
  const self = this;
  this.classList = { toggle(c, f) { const on = f === undefined ? !self._cls.has(c) : !!f; if (on) self._cls.add(c); else self._cls.delete(c); return on; },
                     add(...c) { c.forEach((x) => self._cls.add(x)); }, remove(...c) { c.forEach((x) => self._cls.delete(x)); },
                     contains(c) { return self._cls.has(c); } };
}
Object.defineProperty(El.prototype, 'firstChild', { get() { return this.children[0] || null; } });
Object.defineProperty(El.prototype, 'value', {
  get() { if (this.tagName === 'select') { const o = this.children.find((c) => c.selected) || this.children[0]; return o ? o.value : ''; } return this._value; },
  set(v) { if (this.tagName === 'select') this.children.forEach((c) => { c.selected = c.value === String(v); }); else this._value = v; } });
El.prototype.appendChild = function (c) { this.children.push(c); c.parentNode = this; return c; };
El.prototype.removeChild = function (c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; return c; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); };
El.prototype.dispatch = function (t) { (this.listeners[t] || []).forEach((fn) => fn({ target: this })); };
El.prototype.insertAdjacentHTML = function (pos, html) { this.innerHTML += html; };
El.prototype.focus = function () {};
El.prototype.remove = function () {};
const els = {};
global.document = { getElementById: (id) => (els[id] = els[id] || new El('div', id)), createElement: (t) => new El(t),
                    querySelectorAll: () => [], documentElement: { lang: 'en' }, title: '' };
global.window = global;
let queue = (D.responses || []).slice();
global.fetch = async (url, opts) => {
  calls.push({ url: String(url), method: (opts && opts.method) || 'GET', headers: (opts && opts.headers) || {}, body: (opts && opts.body) || null });
  const r = queue.length > 1 ? queue.shift() : queue[0];
  if (!r) throw new TypeError('Failed to fetch');
  return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body };
};
function barState(id) {
  const b = els[id];
  if (!b) return null;
  const sel = b.children.find((c) => c.tagName === 'select');
  return { hidden: b.classList.contains('hidden'), target: b.getAttribute('data-reply-target'),
           text: b.children.filter((c) => c.tagName === 'span').map((c) => c.textContent),
           options: sel ? sel.children.map((o) => [o.value, o.textContent]) : null, selected: sel ? sel.value : null };
}
function pick(id, v) { const sel = els[id].children.find((c) => c.tagName === 'select'); sel.value = v; sel.dispatch('change'); }
eval(fs.readFileSync(D.lib, 'utf8'));
(async () => {   // trạng thái của trang (let / const) + hàm thật + kịch bản trong CÙNG 1 phạm vi eval
  await eval((D.pre || '') + '\n' + D.src + '\n;(async () => {\n' + D.scenario + '\n})()');
  const html = {};
  Object.keys(els).forEach((k) => { if (els[k].innerHTML) html[k] = els[k].innerHTML; });
  console.log(JSON.stringify({ calls, toasts, extra, html }));
})().catch((e) => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
'''

LIB = os.path.join(ROOT, 'static', 'js', 'bp_reply_target.js')

AI_BOT_PRE = r'''
let currentCustomerId = D.cid, currentCustomerPhone = null, conversationHistory = [], lastLoadedMessages = [];
let allCustomers = D.customers, isMockMode = false;
const mockMessages = {};
const chatBox = document.getElementById('chatBox'), userInput = document.getElementById('userInput');
function cpLang() { return D.lang; }
function cpt(k) { return k; }
function deliveryMark() { return ''; }
function errText() { return ''; }
function appendSystemNote(t) { chatBox.innerHTML += '<note>' + t + '</note>'; }
function scrollToBottom() {}
function renderAiMode() {}
function requestReplyDraft() {}
function showToast(m, type) { toasts.push([String(m), type || '']); }
'''
CRM_PRE = r'''
let allBotCustomersCache = D.customers, currentInboxCustomerId = D.cid, currentLang = D.lang;
function t(k) { return k; }
function showToast(m, type) { toasts.push([String(m), type || '']); }
function loadInboxContacts() {}
function alert(m) { toasts.push([String(m), 'alert']); }
'''
SA_PRE = r'''
let currentChatCustomerId = null, chatConversationsCache = [], currentLang = D.lang;
function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]); }
function formatChatTime() { return 't'; }
function loadChatConversations() {}
function t(k) { return k; }
function showToast(m) { toasts.push([String(m), '']); }
'''


def run_dom(test, src, scenario, pre='', **data):
    tmp = tempfile.mkdtemp(prefix='bp_id4_')
    try:
        js, payload = os.path.join(tmp, 'harness.js'), os.path.join(tmp, 'data.json')
        with io.open(js, 'w', encoding='utf-8') as f:
            f.write(NODE_DOM)
        with io.open(payload, 'w', encoding='utf-8') as f:
            json.dump(dict(data, src=src, scenario=scenario, pre=pre, lib=LIB), f)
        r = subprocess.run(['node', js, payload], capture_output=True, text=True, encoding='utf-8', timeout=60)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lines = (r.stdout or '').strip().splitlines()
    test.assertTrue(lines, (r.stderr or '')[-800:])
    out = json.loads(lines[-1])
    test.assertNotIn('error', out, out.get('error'))
    return out


def page_src(test, rel, names, lines=(), blocks=()):
    s = read(rel)
    parts = [js_line(s, p) for p in lines] + [js_function(s, n) for n in names] + [js_block(s, b) for b in blocks]
    missing = [x for x, p in zip(list(lines) + list(names) + list(blocks), parts) if not p]
    test.assertFalse(missing, f'{rel}: không thấy {missing}')
    return '\n'.join(parts)


def ai_bot_src(test):
    return page_src(test, 'templates/ai_bot.html',
                    ('hrApi', 'escapeHtml', 'richText', 'loadMessages', 'appendUserMessageStatic', 'appendAIMessageStatic',
                     'isWebThread', 'renderReplyBar'),
                    lines=(r'^\s*let replyPlan = [^\n]*$',), blocks=('window.handleUserSubmit = async function',))


def crm_src(test):
    return page_src(test, 'templates/crm_automation.html',
                    ('escapeHtml', 'isInboxWebThread', 'renderInboxReplyBar', 'loadInboxMessages', 'sendLiveMessage'),
                    lines=(r'^\s*let inboxReplyPlan = [^\n]*$',))


def sa_src(test):
    return page_src(test, 'templates/super_admin.html',
                    ('renderChatReplyBar', 'openChatConversation', 'sendSuperAdminChatReply'),
                    lines=(r'^\s*let chatReplyPlan = [^\n]*$',))


class _Base(id3._Base):
    def setUp(self):
        super().setUp()
        SUPER['on'] = False

    def tearDown(self):
        SUPER['on'] = False
        super().tearDown()

    def owner_get(self, cid=WEB_CID, biz=NAIL):
        """Phản hồi THẬT của GET /api/bot/messages (hộp thư của chủ tiệm)."""
        with self.c.session_transaction() as s:
            s['business_id'] = biz
            s['user_id'] = 'owner-' + biz
        r = self.c.get('/api/bot/messages?customer_id=' + quote(cid, safe=''))
        with self.c.session_transaction() as s:
            s.clear()
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        return r.get_json()

    def owner_post(self, call, biz=NAIL):
        """Gửi lại ĐÚNG yêu cầu POST /api/bot/messages mà trang đã gửi (node) tới route thật."""
        self.assertEqual((call['url'], call['method']), ('/api/bot/messages', 'POST'), call)
        with self.c.session_transaction() as s:
            s['business_id'] = biz
            s['user_id'] = 'owner-' + biz
        r = self.c.post('/api/bot/messages', json=json.loads(call['body']))
        with self.c.session_transaction() as s:
            s.clear()
        return r

    def sa_post(self, cid, **body):
        SUPER['on'] = True
        with self.c.session_transaction() as s:
            s['user_id'] = 'boss'
        try:
            return self.c.post('/api/superadmin/chat/messages/' + quote(cid, safe=''), json=body)
        finally:
            SUPER['on'] = False
            with self.c.session_transaction() as s:
                s.clear()

    def lead_send(self, token, content, phone=LEAD_PHONE):
        return self.c.post('/api/cskh/chat/send', json={'phone': phone, 'content': content},
                           headers={'X-Chat-Token': token} if token else {})

    def lead_get(self, token, phone=LEAD_PHONE):
        return self.c.get('/api/cskh/chat/messages?phone=' + quote(phone, safe=''),
                          headers={'X-Chat-Token': token} if token else {})

    def lead_contents(self, token, phone=LEAD_PHONE):
        r = self.lead_get(token, phone)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        return [m['content'] for m in r.get_json()['messages']]


# ================================================================ 1. route: trả lời báo thiết bị nhận
class StaffReplyDeviceTests(_Base):
    def test_reply_goes_to_the_picked_device_and_says_which(self):
        self.seed_thread(ATTACK)
        r = self.staff_reply('Hi Jane, your 3pm gel is moved to 4pm', reply_to=B_MSG_AT)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        j = r.get_json()
        self.assertEqual((j.get('device'), j.get('reply_to')), ('B', B_MSG_AT))
        for h in (HA, HB):
            self.assertNotIn(h, r.get_data(as_text=True))           # không bao giờ trả mã băm
        self.assertIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_B))
        self.assertNotIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_A))
        # không gửi reply_to: 2 thiết bị trong hội thoại -> 409 (fix7: không mặc định tin mới nhất của A sau trả lời cho B);
        # chọn tin của A -> phản hồi nói rõ là thiết bị A
        self.assertEqual(self.staff_reply('Which booking do you mean?').get_json()['code'], 'reply_target_required')
        j = self.staff_reply('Which booking do you mean?', reply_to='2026-10-01T08:20:00').get_json()
        self.assertEqual((j.get('device'), j.get('reply_to')), ('A', '2026-10-01T08:20:00'))
        self.assertIn('Which booking do you mean?', self.contents(TOKEN_A))
        self.assertNotIn('Which booking do you mean?', self.contents(TOKEN_B))

    def test_device_labels_follow_first_message_order_and_stay_stable(self):
        self.seed_thread(ATTACK)
        self.assertEqual(NS['_web_device_labels'](WEB_CID), {HA: 'A', HB: 'B'})
        hc = T.chat_token_hash('tokC' * 6)
        DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'customer', 'content': 'C: hi', 'business_id': NAIL,
                                    'created_at': '2026-10-01T09:00:00', 'chat_token_hash': hc})
        DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'customer', 'content': 'legacy', 'business_id': NAIL,
                                    'created_at': '2026-10-01T09:01:00'})
        self.assertEqual(NS['_web_device_labels'](WEB_CID), {HA: 'A', HB: 'B', hc: 'C'})   # nhãn cũ không đổi
        self.assertEqual(self.staff_reply('hi C', reply_to='2026-10-01T09:01:00').get_json()['device'], None)   # tin không có mã
        self.assertEqual(self.staff_reply('hi C', reply_to='2026-10-01T09:00:00').get_json()['device'], 'C')

    def test_reply_that_reaches_no_browser_is_reported(self):
        self.seed_thread(TWO_BROWSERS + (('customer', 'legacy widget: hello?', None, '2026-10-01T08:20:00'),))
        r = self.staff_reply('Reply to the legacy widget', reply_to='2026-10-01T08:20:00')
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertIn('device', j)
        self.assertEqual((j['device'], j['reply_to']), (None, '2026-10-01T08:20:00'))
        # hội thoại web chưa có tin khách nào -> không thiết bị nào
        DB.bot_customers.insert_one({'id': f'{NAIL}:0499999999', 'business_id': NAIL, 'channel': 'web'})
        j = self.staff_reply('Hello?', cid=f'{NAIL}:0499999999').get_json()
        self.assertEqual((j.get('success'), j.get('device'), j.get('reply_to')), (True, None, None))


# ================================================================ 1. hộp thư THẬT (node) <-> route thật
class OwnerConsoleTests(_Base):
    CUSTOMERS = [{'id': WEB_CID, 'business_id': NAIL, 'channel': 'web'}]

    def _console(self, scenario, lang='en', responses=None, customers=None):
        return run_dom(self, ai_bot_src(self), scenario, pre=AI_BOT_PRE, cid=WEB_CID, lang=lang,
                       customers=customers or self.CUSTOMERS, responses=responses)

    def test_checker_probe_staff_picks_the_victims_device(self):
        # kẻ gian (A) nhắn sau nạn nhân (B); nhân viên thấy 2 thiết bị, chọn thiết bị của B rồi gửi -> chỉ B thấy trả lời
        self.seed_thread(ATTACK)
        thread = self.owner_get()
        scenario = '''
          await loadMessages(D.cid);
          extra.bar = barState('replyTargetBar');
          pick('replyTargetBar', 'B');
          extra.barPicked = barState('replyTargetBar');
          userInput.value = 'Hi Jane, your 3pm gel is moved to 4pm';
          await handleUserSubmit(null);
        '''
        out = self._console(scenario, responses=[{'status': 200, 'body': thread},
                                                 {'status': 200, 'body': {'success': True, 'device': 'B', 'reply_to': B_MSG_AT}},
                                                 {'status': 200, 'body': thread}])
        bar = out['extra']['bar']
        self.assertFalse(bar['hidden'], bar)
        self.assertEqual([v for v, _t in bar['options']], ['__pick__', 'A', 'B'])
        self.assertEqual(bar['selected'], '__pick__')             # p2-residuals: không mặc định thiết bị mới nhất — phải chọn
        self.assertIn('2 different devices', bar['text'][0])
        self.assertTrue(bar['options'][2][1].startswith('Device B — “B: I am Jane'), bar['options'])
        self.assertEqual(out['extra']['barPicked']['selected'], 'B')
        box = out['html']['chatBox']
        self.assertEqual(box.count('>Device A<'), 2)
        self.assertEqual(box.count('>Device B<'), 1)
        for h in (HA, HB):
            self.assertNotIn(h, json.dumps(out))                  # không bao giờ hiện mã băm
        posts = [c for c in out['calls'] if c['method'] == 'POST']
        self.assertEqual(len(posts), 1, out['calls'])
        self.assertEqual(json.loads(posts[0]['body']), {'customer_id': WEB_CID, 'content': 'Hi Jane, your 3pm gel is moved to 4pm',
                                                        'reply_to': B_MSG_AT})
        r = self.owner_post(posts[0])                             # đúng yêu cầu trang gửi -> route thật
        self.assertEqual((r.status_code, r.get_json()['device']), (200, 'B'))
        self.assertIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_B))
        self.assertNotIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_A))
        self.assertIn(['Sent to Device B — only that device sees the reply on the chat page.', 'success'], out['toasts'])

    def test_default_reply_goes_to_the_latest_message_shown_and_labels_follow(self):
        self.seed_thread(ATTACK)
        thread = self.owner_get()
        scenario = '''
          await loadMessages(D.cid);
          pick('replyTargetBar', 'A');
          userInput.value = 'Any time after 10 works';
          await handleUserSubmit(null);
        '''
        out = self._console(scenario, lang='vi', responses=[{'status': 200, 'body': thread},
                                                            {'status': 200, 'body': {'success': True, 'device': 'A'}},
                                                            {'status': 200, 'body': thread}])
        post = [c for c in out['calls'] if c['method'] == 'POST'][0]
        self.assertEqual(json.loads(post['body'])['reply_to'], '2026-10-01T08:20:00')
        self.assertIn('>Thiết bị A<', out['html']['chatBox'])
        self.assertEqual(self.owner_post(post).get_json()['device'], 'A')
        # tải lại hội thoại sau khi gửi: trả lời hiện "→ Thiết bị A"; không còn 2 thiết bị kể từ trả lời này nhưng hội thoại có 2
        # thiết bị -> thanh chọn vẫn hiện (không âm thầm gửi cho thiết bị mới nhất)
        out = self._console('await loadMessages(D.cid); extra.bar = barState("replyTargetBar");', lang='vi',
                            responses=[{'status': 200, 'body': self.owner_get()}])
        self.assertIn('→ Thiết bị A', out['html']['chatBox'])
        self.assertFalse(out['extra']['bar']['hidden'])
        self.assertIn('2 thiết bị khác nhau đã nhắn bằng số này — trả lời chỉ tới:', out['extra']['bar']['text'][0])

    def test_single_device_thread_sends_reply_to_without_a_picker(self):
        self.seed_thread(TWO_BROWSERS[2:])
        out = self._console('''
          await loadMessages(D.cid);
          extra.bar = barState('replyTargetBar');
          userInput.value = 'Done!';
          await handleUserSubmit(null);
        ''', responses=[{'status': 200, 'body': self.owner_get()}, {'status': 200, 'body': {'success': True, 'device': 'A'}}])
        self.assertTrue(out['extra']['bar']['hidden'])
        post = [c for c in out['calls'] if c['method'] == 'POST'][0]
        self.assertEqual(json.loads(post['body'])['reply_to'], B_MSG_AT)
        self.assertEqual(out['toasts'], [])                       # 1 thiết bị: không cần báo thêm
        self.assertEqual(self.owner_post(post).get_json()['device'], 'A')
        self.assertIn('Done!', self.contents(TOKEN_B))

    def test_reply_to_a_message_without_browser_id_is_flagged(self):
        self.seed_thread(TWO_BROWSERS[2:] + (('customer', 'legacy: hello?', None, '2026-10-01T08:20:00'),))
        thread = self.owner_get()
        r_real = None
        for lang, words in (('en', ('will NOT appear', 'call or text')), ('vi', ('KHÔNG hiện', 'gọi hoặc nhắn SMS'))):
            out = self._console('''
              await loadMessages(D.cid);
              pick('replyTargetBar', '');
              extra.bar = barState('replyTargetBar');
              userInput.value = 'Hello!';
              await handleUserSubmit(null);
            ''', lang=lang, responses=[{'status': 200, 'body': thread},
                                       {'status': 200, 'body': {'success': True, 'device': None, 'reply_to': '2026-10-01T08:20:00'}},
                                       {'status': 200, 'body': thread}])
            bar = out['extra']['bar']
            self.assertFalse(bar['hidden'])                        # 2 nguồn: thiết bị A + cửa sổ chat cũ -> cho chọn + cảnh báo
            self.assertEqual([v for v, _t in bar['options']], ['A', ''])
            self.assertEqual(bar['selected'], '')
            for w in words:
                self.assertTrue(any(w in t for t in bar['text']), (w, bar['text']))
                self.assertTrue(any(w in t for t, _k in out['toasts']), (w, out['toasts']))
            self.assertEqual([k for _t, k in out['toasts']], ['error'])
            post = [c for c in out['calls'] if c['method'] == 'POST'][0]
            if r_real is None:
                r_real = self.owner_post(post).get_json()
        self.assertEqual(r_real['device'], None)                  # route thật nói đúng điều trang báo

    def test_platform_thread_sends_no_reply_to_and_shows_no_devices(self):
        cid = id3.inbox_channels.record(NAIL, 'sms', '+61412345678', 'Can I move my booking?', 'customer', phone='+61412345678')
        thread = self.owner_get(cid)
        out = run_dom(self, ai_bot_src(self), '''
          await loadMessages(D.cid);
          extra.bar = barState('replyTargetBar');
          userInput.value = 'Sure';
          await handleUserSubmit(null);
        ''', pre=AI_BOT_PRE, cid=cid, lang='en', customers=[{'id': cid, 'channel': 'sms'}],
            responses=[{'status': 200, 'body': thread}, {'status': 200, 'body': {'success': True, 'delivery': {'status': 'sent'}}}])
        self.assertTrue(out['extra']['bar']['hidden'])
        self.assertNotIn('Device', out['html']['chatBox'])
        post = [c for c in out['calls'] if c['method'] == 'POST'][0]
        self.assertNotIn('reply_to', json.loads(post['body']))


class CrmInboxTests(_Base):
    def test_crm_inbox_labels_devices_and_sends_the_picked_reply_to(self):
        self.seed_thread(ATTACK)
        thread = self.owner_get()
        out = run_dom(self, crm_src(self), '''
          await loadInboxMessages(D.cid);
          extra.bar = barState('inboxReplyTargetBar');
          pick('inboxReplyTargetBar', 'B');
          document.getElementById('liveChatInput').value = 'Hi Jane, your 3pm gel is moved to 4pm';
          await sendLiveMessage();
        ''', pre=CRM_PRE, cid=WEB_CID, lang='en', customers=[{'id': WEB_CID, 'channel': 'web'}],
            responses=[{'status': 200, 'body': thread}, {'status': 200, 'body': {'success': True, 'device': 'B'}},
                       {'status': 200, 'body': thread}])
        self.assertEqual(out['extra']['bar']['options'][1][0], 'A')
        self.assertEqual(out['extra']['bar']['selected'], '__pick__')   # p2-residuals: phải chọn thiết bị
        box = out['html']['liveChatBox']
        self.assertIn('>Device A<', box)
        self.assertIn('>Device B<', box)
        for h in (HA, HB):
            self.assertNotIn(h, json.dumps(out))
        post = [c for c in out['calls'] if c['method'] == 'POST'][0]
        self.assertEqual(json.loads(post['body'])['reply_to'], B_MSG_AT)
        self.assertEqual(self.owner_post(post).get_json()['device'], 'B')
        self.assertIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_B))
        self.assertNotIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_A))


# ================================================================ 2. super admin: cùng luật đích trả lời
class SuperAdminReplyTests(_Base):
    def test_superadmin_reply_on_a_tenant_web_thread_is_stamped(self):
        self.seed_thread(ATTACK)
        r = self.sa_post(WEB_CID, content='BitPaw support: your booking is safe', reply_to=B_MSG_AT)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        self.assertEqual((r.get_json()['device'], r.get_json()['reply_to']), ('B', B_MSG_AT))
        doc = DB.bot_messages.find({'customer_id': WEB_CID, 'sender_type': 'staff'})[-1]
        self.assertEqual(doc.get('chat_token_hash'), HB)
        # A đã vào hội thoại TRƯỚC trả lời này (luật cũ "trả lời không mã băm ghi sau lúc vào" từng đưa cho A) -> giờ không thấy
        self.assertNotIn('BitPaw support: your booking is safe', self.contents(TOKEN_A))
        self.assertIn('BitPaw support: your booking is safe', self.contents(TOKEN_B))
        # không gửi reply_to: 2 thiết bị trong hội thoại -> 409 (fix7); chọn tin của A -> A; B không thấy
        self.assertEqual(self.sa_post(WEB_CID, content='Which booking?').get_json()['code'], 'reply_target_required')
        self.assertEqual(self.sa_post(WEB_CID, content='Which booking?', reply_to='2026-10-01T08:20:00').get_json()['device'], 'A')
        self.assertNotIn('Which booking?', self.contents(TOKEN_B))

    def test_superadmin_reply_errors_and_access(self):
        self.seed_thread(ATTACK)
        n = len(DB.bot_messages.find({}))
        for bad, code in (('2026-10-01T09:59:59', 404), ('2026-10-01T08:00:05', 404), (123, 400), ({'$ne': None}, 400)):
            r = self.sa_post(WEB_CID, content='nope', reply_to=bad)
            self.assertEqual(r.status_code, code, bad)
            self.assertFalse(r.get_json()['success'])
        r = self.c.post('/api/superadmin/chat/messages/' + quote(WEB_CID, safe=''), json={'content': 'nope'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(len(DB.bot_messages.find({})), n)

    def test_superadmin_page_sends_reply_to_for_the_picked_device(self):
        self.seed_thread(ATTACK)
        msgs = sorted(DB.bot_messages.find({'customer_id': WEB_CID}), key=lambda m: m['created_at'])
        for m in msgs:
            m.pop('_id', None)
        get = {'success': True, 'messages': msgs, 'customer': {'id': WEB_CID, 'business_id': NAIL, 'channel': 'web'}}
        out = run_dom(self, sa_src(self), '''
          await openChatConversation(encodeURIComponent(D.cid));
          extra.bar = barState('chatReplyTargetBar');
          pick('chatReplyTargetBar', 'B');
          document.getElementById('chatReplyInput').value = 'BitPaw support here';
          await sendSuperAdminChatReply();
        ''', pre=SA_PRE, cid=WEB_CID, lang='vi',
            responses=[{'status': 200, 'body': get}, {'status': 200, 'body': {'success': True, 'device': 'B'}},
                       {'status': 200, 'body': get}])
        self.assertEqual([v for v, _t in out['extra']['bar']['options']], ['__pick__', 'A', 'B'])
        self.assertIn('Thiết bị A', out['html']['chatMessagesBox'])
        for h in (HA, HB):
            self.assertNotIn(h, json.dumps(out))
        post = [c for c in out['calls'] if c['method'] == 'POST'][0]
        self.assertEqual(post['url'], '/api/superadmin/chat/messages/' + quote(WEB_CID, safe=''))
        body = json.loads(post['body'])
        self.assertEqual(body, {'content': 'BitPaw support here', 'reply_to': B_MSG_AT})
        self.assertEqual(self.sa_post(WEB_CID, **body).get_json()['device'], 'B')
        self.assertIn('BitPaw support here', self.contents(TOKEN_B))
        self.assertNotIn('BitPaw support here', self.contents(TOKEN_A))
        self.assertIn('Đã gửi tới Thiết bị B — chỉ thiết bị này thấy trả lời trên trang chat.', [t for t, _k in out['toasts']])


# ================================================================ 3. /api/cskh/chat/send: 503 khi không lưu được
class CskhSendStoredTests(_Base):
    def test_send_returns_503_when_nothing_was_stored(self):
        for lang in ('en', 'vi'):
            vi_en = (lambda vi, en: vi) if lang == 'vi' else (lambda vi, en: en)
            with patch.dict(NS, {'db': None, '_vi_en': vi_en}):
                r = self.lead_send(TOKEN_W, 'I need a demo')
            self.assertEqual(r.status_code, 503, lang)
            self.assertFalse(r.get_json()['success'])
            self.assertIn('CHƯA được gửi' if lang == 'vi' else 'NOT sent', r.get_json()['message'])
            with patch.dict(NS, {'_vi_en': vi_en}), patch.object(DB.bot_messages, 'insert_one', side_effect=RuntimeError('down')):
                r = self.lead_send(TOKEN_W, 'I need a demo')
            self.assertEqual((r.status_code, r.get_json()['success']), (503, False), lang)
        self.assertEqual(DB.bot_messages.find({}), [])
        r = self.lead_send(TOKEN_W, 'I need a demo')
        self.assertEqual((r.status_code, r.get_json()), (200, {'success': True}))

    def test_send_stores_only_the_browser_token_hash(self):
        self.assertEqual(self.lead_send(TOKEN_W, 'I need a demo').status_code, 200)
        doc = DB.bot_messages.find({'customer_id': LEAD_CID})[0]
        self.assertEqual(doc.get('chat_token_hash'), HW)
        self.assertNotIn(TOKEN_W, json.dumps(DB.bot_messages.find({})))
        # widget cũ (không gửi mã): tin vẫn tới đội ngũ, nhưng không trình duyệt nào đọc lại được
        self.assertEqual(self.lead_send(None, 'old widget').status_code, 200)
        self.assertNotIn('chat_token_hash', DB.bot_messages.find({'content': 'old widget'})[0])


# ================================================================ 4. 'Talk to Human Agent': bằng chứng trình duyệt
class LeadThreadProofTests(_Base):
    def test_messages_need_the_browser_that_wrote_there(self):
        self.assertEqual(self.lead_send(TOKEN_W, 'I need a demo').status_code, 200)
        self.assertEqual(self.sa_post(LEAD_CID, content='Hi! A demo link is on its way').status_code, 200)
        # chỉ SĐT (như trước đây) / mã sai / mã của trình duyệt chưa nhắn ở đây / mã trong URL -> 404, không lộ gì
        for r in (self.lead_get(None), self.lead_get(TOKEN_A), self.lead_get('x'),
                  self.c.get('/api/cskh/chat/messages?phone=' + quote(LEAD_PHONE, safe='') + '&chat_token=' + TOKEN_W)):
            self.assertEqual(r.status_code, 404)
            self.assertNotIn('demo', r.get_data(as_text=True))
        r = self.lead_get(TOKEN_W)
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertEqual([m['content'] for m in j['messages']], ['I need a demo', 'Hi! A demo link is on its way'])
        self.assertRegex(j.get('stream_key') or '', r'^[0-9]+\.[0-9a-f]{64}$')
        self.assertEqual(j.get('stream_key_ttl'), 600)
        self.assertNotIn(TOKEN_W, j['stream_key'])
        self.assertNotIn(HW, j['stream_key'])

    def test_two_browsers_on_one_phone_only_see_their_own(self):
        self.assertEqual(self.lead_send(TOKEN_B, 'Jane here, call me about pricing').status_code, 200)
        time.sleep(0.03)
        self.assertEqual(self.lead_send(TOKEN_A, 'any update?').status_code, 200)   # người gõ SĐT của Jane, nhắn sau
        jane_at = DB.bot_messages.find({'customer_id': LEAD_CID, 'chat_token_hash': HB})[0]['created_at']
        r = self.sa_post(LEAD_CID, content='Hi Jane, calling you at 3pm', reply_to=jane_at)
        self.assertEqual(r.get_json()['device'], 'A')          # Jane nhắn trước -> thiết bị A
        self.assertEqual(self.lead_contents(TOKEN_B), ['Jane here, call me about pricing', 'Hi Jane, calling you at 3pm'])
        self.assertEqual(self.lead_contents(TOKEN_A), ['any update?'])
        # trả lời cũ (trước bản sửa, không có trường mã băm): chỉ trình duyệt đã vào trước trả lời đó
        DB.bot_messages.insert_one({'customer_id': LEAD_CID, 'sender_type': 'staff', 'content': 'legacy reply',
                                    'business_id': 'bitpaw_leads', 'created_at': '2000-01-01T00:00:00'})
        self.assertNotIn('legacy reply', self.lead_contents(TOKEN_A))

    def test_stream_needs_a_signed_key_or_the_header(self):
        self.assertEqual(self.lead_send(TOKEN_W, 'I need a demo').status_code, 200)
        self.assertEqual(self.lead_send(TOKEN_A, 'hi', phone='0499 999 999').status_code, 200)
        base = '/api/stream/cskh_chat?phone=' + quote(LEAD_PHONE, safe='')
        now = time.time()
        with clock(now):
            key = self.lead_get(TOKEN_W).get_json()['stream_key']
            other = self.lead_get(TOKEN_A, phone='0499 999 999').get_json()['stream_key']
            bad = [self.c.get(base),                                              # chỉ SĐT (trước đây: nghe được)
                   self.c.get(base + '&chat_token=' + TOKEN_W),                   # mã gốc trong URL: không bao giờ
                   self.c.get(base + '&stream_key=' + quote(other, safe='')),     # khoá của hội thoại khác
                   self.c.get(base + '&stream_key=' + key[:-1] + ('0' if key[-1] != '0' else '1')),
                   self.c.get(base, headers={'X-Chat-Token': TOKEN_A})]           # trình duyệt chưa nhắn ở số này
        with clock(now + 601):
            bad.append(self.c.get(base + '&stream_key=' + quote(key, safe='')))  # hết hạn
        self.assertEqual([r.status_code for r in bad], [404] * len(bad))
        self.assertEqual(id3.SSE, [])
        with clock(now + 5):
            r = self.c.get(base + '&stream_key=' + quote(key, safe=''))
        self.assertEqual(r.status_code, 200)
        stage = id3.SSE[-1]
        self.assertTrue(sse_hits(stage, change({'customer_id': LEAD_CID, 'sender_type': 'staff', 'chat_token_hash': HW})))
        self.assertTrue(sse_hits(stage, change({'customer_id': LEAD_CID, 'sender_type': 'staff'})))   # trả lời cũ không mã
        for ev in ({'customer_id': LEAD_CID, 'sender_type': 'customer', 'chat_token_hash': HA},
                   {'customer_id': LEAD_CID, 'sender_type': 'staff', 'chat_token_hash': HA},
                   {'customer_id': LEAD_CID, 'sender_type': 'staff', 'chat_token_hash': ''},
                   {'customer_id': 'bitpaw_leads:0499 999 999', 'sender_type': 'staff', 'chat_token_hash': HW}):
            self.assertFalse(sse_hits(stage, change(ev)), ev)
        self.assertEqual(self.c.get(base, headers={'X-Chat-Token': TOKEN_W}).status_code, 200)   # client không phải trình duyệt


# ================================================================ 4. widget THẬT (node) <-> route thật
def human_src(test):
    s = read('static/js/cskh_widget.js')
    lets = [js_line(s, p) for p in (r'^\s*let humanChatStream = [^\n]*$', r'^\s*let humanChatPhone = [^\n]*$',
                                    r'^\s*let renderedStaffMessageCount = [^\n]*$', r'^\s*let humanStreamKey = [^\n]*$')]
    test.assertTrue(all(lets), lets)
    return '\n'.join(lets + [id3.widget_src(test, 'handleHumanAgentSubmit', 'humanSendError', 'startHumanAgentStream',
                                            'fetchHumanAgentReplies', 'openHumanAgentStream', 'renewHumanAgentStream',
                                            'getChatToken')])


TICKS = 'for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r));'


class HumanAgentWidgetFlowTests(_Base):
    def _check_stream(self, url, key, at, own_hash=HW):
        u = urlparse(url)
        self.assertEqual(u.path, '/api/stream/cskh_chat', url)
        q = parse_qs(u.query)
        self.assertEqual((q.get('phone'), q.get('stream_key')), ([LEAD_PHONE], [key]), url)
        self.assertNotIn(TOKEN_W, url)
        self.assertNotIn(own_hash, url)
        self.assertNotIn('chat_token', url)
        n = len(id3.SSE)
        with clock(at):
            r = self.c.get(url)                                    # đúng URL widget dựng -> route thật
        self.assertEqual(r.status_code, 200, (url, r.get_data(as_text=True)[:200]))
        self.assertEqual(len(id3.SSE), n + 1)
        self.assertTrue(sse_hits(id3.SSE[-1], change({'customer_id': LEAD_CID, 'sender_type': 'staff', 'chat_token_hash': own_hash})))
        self.assertFalse(sse_hits(id3.SSE[-1], change({'customer_id': LEAD_CID, 'sender_type': 'staff', 'chat_token_hash': HA})))

    def test_widget_sends_with_its_token_and_sees_only_its_reply(self):
        # Python gửi ĐÚNG yêu cầu widget gửi (kiểm lại bên dưới) tới route thật, rồi đưa phản hồi thật cho widget
        send = self.lead_send(TOKEN_W, 'I need a demo')
        self.assertEqual(send.status_code, 200)
        self.assertEqual(self.lead_send(TOKEN_A, 'any update?').status_code, 200)   # người khác gõ cùng SĐT, nhắn sau
        w_at = DB.bot_messages.find({'customer_id': LEAD_CID, 'chat_token_hash': HW})[0]['created_at']
        self.assertEqual(self.sa_post(LEAD_CID, content='Hi! A demo link is on its way', reply_to=w_at).get_json()['device'], 'A')
        now = time.time()
        with clock(now):
            j1 = self.lead_get(TOKEN_W).get_json()
        for vi in (False, True):
            out = id3.run_node(self, human_src(self), "await handleHumanAgentSubmit('I need a demo', '0412 345 678');\n" + TICKS,
                               vi=vi, store={'bp_chat_token': TOKEN_W},
                               responses=[{'status': 200, 'body': send.get_json()}, {'status': 200, 'body': j1}])
            self.assertEqual([(c['method'], c['url']) for c in out['calls']],
                             [('POST', '/api/cskh/chat/send'), ('GET', '/api/cskh/chat/messages?phone=0412%20345%20678')])
            for c in out['calls']:
                self.assertEqual(c['headers'].get('X-Chat-Token'), TOKEN_W, c)   # mã chỉ trong header
                self.assertNotIn(TOKEN_W, c['url'])
            self.assertEqual(json.loads(out['calls'][0]['body']), {'phone': LEAD_PHONE, 'content': 'I need a demo'})
            self.assertEqual(out['appended'], [['user', 'I need a demo'], ['ai', 'Hi! A demo link is on its way']])
            self.assertNotIn('any update?', json.dumps(out))          # tin của trình duyệt khác không tới đây
            self.assertEqual(len(out['streams']), 1, out['streams'])
            self.assertFalse(out['streams'][0]['closed'])
            self._check_stream(out['streams'][0]['url'], j1['stream_key'], now + 5)

    def test_widget_renews_the_stream_key_and_recovers(self):
        self.assertEqual(self.lead_send(TOKEN_W, 'I need a demo').status_code, 200)
        now = time.time()
        with clock(now):
            j1 = self.lead_get(TOKEN_W).get_json()
        with clock(now + 60):
            j2 = self.lead_get(TOKEN_W).get_json()
        self.assertNotEqual(j1['stream_key'], j2['stream_key'])
        scenario = '''
          await startHumanAgentStream('0412 345 678');
          extra.renewMs = timers.length ? timers[timers.length - 1].ms : null;
          await fireTimer();                       // ~8 phút sau: gia hạn trước khi khoá hết hạn
          failStream(streams[streams.length - 1]); // server từ chối kênh (máy ngủ quá 10 phút...)
          extra.retryMs = timers[timers.length - 1].ms;
          await fireTimer();
        '''
        out = id3.run_node(self, human_src(self), scenario, store={'bp_chat_token': TOKEN_W},
                           responses=[{'status': 200, 'body': j1}, {'status': 200, 'body': j2}])
        self.assertEqual(len([c for c in out['calls'] if c['method'] == 'GET']), 3, out['calls'])
        self.assertEqual([s['closed'] for s in out['streams']], [True, True, False], out['streams'])
        self.assertEqual((out['extra']['renewMs'], out['extra']['retryMs']), ((600 - 120) * 1000, 3000))
        self._check_stream(out['streams'][0]['url'], j1['stream_key'], now + 5)
        self._check_stream(out['streams'][1]['url'], j2['stream_key'], now + 65)
        self._check_stream(out['streams'][2]['url'], j2['stream_key'], now + 70)
        with clock(now + 601):
            self.assertEqual(self.c.get(out['streams'][0]['url']).status_code, 404)

    def test_widget_without_a_thread_opens_no_stream_until_it_sends(self):
        # "Talk to Human Agent" bấm khi đã gõ SĐT nhưng chưa nhắn: server 404 (THẬT) -> không mở kênh chỉ-có-SĐT như trước
        r404 = self.lead_get(TOKEN_W)
        self.assertEqual(r404.status_code, 404)
        send = self.lead_send(TOKEN_W, 'hello')
        now = time.time()
        with clock(now):
            j1 = self.lead_get(TOKEN_W).get_json()
        scenario = '''
          await startHumanAgentStream('0412 345 678');
          extra.before = streams.length;
          await handleHumanAgentSubmit('hello', '0412 345 678');
        ''' + TICKS
        out = id3.run_node(self, human_src(self), scenario, store={'bp_chat_token': TOKEN_W},
                           responses=[{'status': 404, 'body': r404.get_json()}, {'status': 200, 'body': send.get_json()},
                                      {'status': 200, 'body': j1}])
        self.assertEqual(out['extra']['before'], 0)
        self.assertEqual(len(out['streams']), 1)
        self._check_stream(out['streams'][0]['url'], j1['stream_key'], now + 5)

    def test_widget_reports_a_503_as_not_sent(self):
        with patch.dict(NS, {'db': None}):
            r = self.lead_send(TOKEN_W, 'I need a demo')
        self.assertEqual(r.status_code, 503)
        out = id3.run_node(self, human_src(self), "await handleHumanAgentSubmit('I need a demo', '0412 345 678');\n" + TICKS,
                           store={'bp_chat_token': TOKEN_W}, responses=[{'status': 503, 'body': r.get_json()}])
        self.assertEqual(out['streams'], [])
        self.assertIn('NOT sent', out['appended'][-1][1])
        self.assertEqual(out['input'], 'I need a demo')


# ================================================================ bp_reply_target.js + các trang
NODE_LIB = r'''
const fs = require('fs');
const D = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
global.window = global;
eval(fs.readFileSync(D.lib, 'utf8'));
const R = window.BPReplyTarget, out = {};
const p = R.plan(D.msgs, true);
out.map = Array.from(p.map.entries());
out.latest = p.latest; out.choices = p.choices.map((c) => c.device); out.choose = p.choose;
out.tags = D.msgs.map((m) => (m.sender_type === 'customer' ? (R.customerTag(m, p, 'en') || {}).text : R.staffTag(m, p, 'en')));
out.target = R.target(p, 'B');
const sms = R.plan(D.msgs, false);
out.sms = { latest: sms.latest, choose: sms.choose, tag: R.customerTag(D.msgs[0], sms, 'en'), target: R.target(sms, null) };
console.log(JSON.stringify(out));
'''


class ReplyTargetLibTests(_Base):
    def test_labels_match_the_server_and_never_expose_hashes(self):
        rows = list(ATTACK)
        hashes = [T.chat_token_hash(f'tok{i:02d}' * 6) for i in range(28)]
        for i, h in enumerate(hashes):                          # 28 trình duyệt: A..Z rồi '27', '28' (cùng luật server)
            rows.append(('customer', f'm{i}', h, f'2026-10-02T{i // 60:02d}:{i % 60:02d}:00'))
        rows.append(('staff', 'reply to B', HB, '2026-10-03T00:00:00'))
        rows.append(('staff', 'reply nobody sees', '', '2026-10-03T00:01:00'))
        rows.append(('staff', 'legacy reply', None, '2026-10-03T00:02:00'))
        self.seed_thread(rows)
        msgs = self.owner_get()['data']
        tmp = tempfile.mkdtemp(prefix='bp_id4lib_')
        try:
            js, payload = os.path.join(tmp, 'h.js'), os.path.join(tmp, 'd.json')
            with io.open(js, 'w', encoding='utf-8') as f:
                f.write(NODE_LIB)
            with io.open(payload, 'w', encoding='utf-8') as f:
                json.dump({'lib': LIB, 'msgs': msgs}, f)
            r = subprocess.run(['node', js, payload], capture_output=True, text=True, encoding='utf-8', timeout=60)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(dict(out['map']), NS['_web_device_labels'](WEB_CID))
        self.assertEqual(dict(out['map'])[hashes[-1]], '30')     # A, B + 28 trình duyệt -> trình duyệt thứ 30
        tags = dict(zip([m['content'] for m in msgs], out['tags']))
        self.assertEqual((tags['A: hi, any slots Friday?'], tags['B: I am Jane, can you move my 3pm gel?']), ('Device A', 'Device B'))
        self.assertEqual((tags['reply to B'], tags['reply nobody sees'], tags['legacy reply']),
                         ('→ Device B', "→ not shown on the customer's chat page", ''))
        self.assertEqual(out['choose'], True)                    # hội thoại có >= 2 thiết bị
        self.assertEqual(out['latest']['reply_to'], '2026-10-02T00:27:00')
        self.assertEqual(out['target']['reply_to'], '2026-10-01T08:10:00')
        self.assertEqual(out['sms'], {'latest': None, 'choose': False, 'tag': None, 'target': None})
        txt = json.dumps({k: v for k, v in out.items() if k != 'map'})
        for h in [HA, HB] + hashes:
            self.assertNotIn(h, txt)

    def test_pages_load_the_shared_helper_and_parse(self):
        inc = '<script src="/static/js/bp_reply_target.js?v={{ asset_v(\'js/bp_reply_target.js\') }}"></script>'
        id3.node_check(self, 'static/js/bp_reply_target.js', read('static/js/bp_reply_target.js'))
        id3.node_check(self, 'static/js/cskh_widget.js', read('static/js/cskh_widget.js'))
        for rel, use in (('templates/ai_bot.html', 'BPReplyTarget.target(plan, replyPick)'),
                         ('templates/crm_automation.html', 'BPReplyTarget.target(plan, inboxReplyPick)'),
                         ('templates/super_admin.html', 'BPReplyTarget.target(plan, chatReplyPick)')):
            s = read(rel)
            self.assertEqual(s.count(inc), 1, rel)
            self.assertLess(s.index(inc), s.index(use), rel)      # nạp trước khi dùng
            self.assertIn('payload.reply_to = target.reply_to', s, rel)
            for i, m in enumerate(re.finditer(r'<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>', s, re.S)):
                if 'application/json' in m.group(1):
                    continue
                code = re.sub(r'\{\{.*?\}\}', '0', m.group(2), flags=re.S)
                code = re.sub(r'\{%.*?%\}|\{#.*?#\}', '', code, flags=re.S)
                id3.node_check(self, f'{rel} script#{i}', code)
        # đổi hội thoại / mở live demo -> kế hoạch trả lời (reply_to, thanh chọn thiết bị) của hội thoại cũ bị bỏ ngay
        ai = read('templates/ai_bot.html')
        for fn in (js_function(ai, 'onSelectCustomer'), js_block(ai, 'window.startLiveDemo = async function')):
            self.assertRegex(fn or '', r'replyPlan = null;[^\n]*\n\s*renderReplyBar\(\);')
        self.assertRegex(js_function(read('templates/crm_automation.html'), 'openChat') or '',
                         r'inboxReplyPlan = null;[^\n]*\n\s*renderInboxReplyBar\(\);')
        self.assertIn('chatReplyPick = null; chatReplyPlan = null; renderChatReplyBar();',
                      js_function(read('templates/super_admin.html'), 'openChatConversation') or '')
        w = read('static/js/cskh_widget.js')
        self.assertNotRegex(w, r'/api/stream/cskh_chat\?phone="\s*\+\s*encodeURIComponent\(phone\)\);')   # kênh chỉ-có-SĐT cũ


if __name__ == '__main__':
    unittest.main(verbosity=2)
