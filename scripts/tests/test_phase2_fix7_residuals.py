# -*- coding: utf-8 -*-
"""Test OFFLINE — phase2-fix7-residuals (phần còn sót sau p2-residuals):
  1. (MEDIUM) Hộp thư web (ai_bot.html, crm_automation.html, super_admin.html qua static/js/bp_reply_target.js;
     app.py::_web_reply_stamp cho /api/bot/messages POST + /api/superadmin/chat/messages POST): hội thoại có >= 2 thiết bị ở
     BẤT KỲ đâu (không chỉ nhắn từ sau trả lời gần nhất của nhân viên) -> ô soạn tin KHÔNG mặc định thiết bị mới nhất, phải
     chọn thiết bị trước MỖI lần gửi; server từ chối trả lời không có reply_to trên hội thoại như vậy bằng 409
     (reply_target_required) mà trang xử lý. Ca thử của người kiểm tra: nạn nhân V nhắn, kẻ gian X nhắn sau (X mới nhất),
     nhân viên chọn V và trả lời -> trả lời tiếp theo (không ai nhắn từ sau trả lời) từng âm thầm tới X; X nhắn 1 tin ngay sau
     mỗi trả lời (SSE tải lại im lặng, since = {X}) cũng từng nhận trả lời tiếp theo.
  2. (LOW) Không còn VND mặc định trên đường tiền của AI / khách: reservations_core.currency (gói fnb, karaoke), nhánh import
     lỗi của app.py (TenantEngine dự phòng từng trả VN/VND cho MỌI tiệm; format_money dự phòng mặc định VND và in mọi tiền khác
     USD kiểu '45đ'), ai_copilot_tools.business_currency, nail_turns.shop_currency, ai_packs/hotel._currency — tất cả theo
     currency_utils.shop_currency(tiền đã lưu, ai_packs.shop_country: hồ sơ -> múi giờ trang Nhắn tin -> tiền), cuối cùng USD;
     tiệm Việt Nam vẫn VND.

KHÔNG import app.py thật, KHÔNG MongoDB thật, KHÔNG mạng / API trả phí. Mã JS THẬT của trang chạy trong node.
Chạy: python scripts/tests/test_phase2_fix7_residuals.py
"""
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_phase2_fix4_identity4 as id4  # noqa: E402  (DB giả + stub của test_phase2_receptionist_core, route bot / portal)

core = id4.core
DB, ROOT, NS, T = core.DB, core.ROOT, id4.NS, id4.T
WEB_CID, NAIL, HA, HB = id4.WEB_CID, id4.NAIL, id4.HA, id4.HB
TOKEN_A, TOKEN_B = id4.TOKEN_A, id4.TOKEN_B
TWO_BROWSERS, ATTACK, B_MSG_AT = id4.TWO_BROWSERS, id4.ATTACK, id4.B_MSG_AT
A_LAST_AT = ATTACK[-1][3]          # tin mới nhất của kẻ gian (thiết bị A), SAU tin của nạn nhân (B)
# ca thử của người kiểm tra: V (B) nhắn, X (A) nhắn sau, nhân viên chọn V và trả lời -> từ sau trả lời không ai nhắn
AFTER_REPLY = ATTACK + (('staff', 'Hi Jane, your 3pm gel is moved to 4pm', HB, '2026-10-01T08:30:00'),)
PICK = '__pick__'
MUST_PICK_EN = "Choose which device gets this reply before sending"
WIDE_EN = '2 different devices have messaged from this number in this conversation'


def _lib(test, scenario, **data):
    """Chỉ static/js/bp_reply_target.js THẬT (không trang nào) trong node."""
    return id4.run_dom(test, '', scenario, **data)


def _posts(out):
    return [c for c in out['calls'] if c['method'] == 'POST']


def _customer_at(cid, h):
    return max(m['created_at'] for m in DB.bot_messages.find({'customer_id': cid, 'sender_type': 'customer'})
               if m.get('chat_token_hash') == h)


# ============================================================ 1. server: >= 2 thiết bị ở bất kỳ đâu -> phải chọn
class ReplyTargetServerTests(id4._Base):
    def test_checker_probe_follow_up_after_picking_the_victim_is_refused(self):
        self.seed_thread(ATTACK)
        r = self.staff_reply('Hi Jane, your 3pm gel is moved to 4pm', reply_to=B_MSG_AT)
        self.assertEqual((r.status_code, r.get_json()['device']), (200, 'B'))
        n = len(DB.bot_messages.find({}))
        # từ sau trả lời không ai nhắn (since = {}) nhưng hội thoại có 2 thiết bị: không tự gửi cho tin mới nhất (A = kẻ gian)
        r = self.staff_reply('Anything else, Jane?')
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True)[:200])
        j = r.get_json()
        self.assertEqual((j['success'], j['code']), (False, 'reply_target_required'))
        self.assertIn(WIDE_EN, j['message'])
        self.assertIn('Nothing was sent', j['message'])
        for h in (HA, HB):
            self.assertNotIn(h, r.get_data(as_text=True))
        self.assertEqual(len(DB.bot_messages.find({})), n)                      # không ghi gì
        self.assertNotIn('Anything else, Jane?', self.contents(TOKEN_A))
        r = self.staff_reply('Anything else, Jane?', reply_to=B_MSG_AT)
        self.assertEqual((r.status_code, r.get_json()['device']), (200, 'B'))
        self.assertIn('Anything else, Jane?', self.contents(TOKEN_B))
        self.assertNotIn('Anything else, Jane?', self.contents(TOKEN_A))

    def test_checker_probe_attacker_posting_once_after_each_reply_gets_nothing(self):
        self.seed_thread(TWO_BROWSERS)
        for i in range(3):
            r = self.staff_reply(f'Reply {i} for Jane', reply_to=_customer_at(WEB_CID, HB))
            self.assertEqual((r.status_code, r.get_json()['device']), (200, 'B'))
            time.sleep(0.03)                                   # created_at khác nhau (đồng hồ Windows ~15 ms)
            r = self.c.post('/api/portal/messages', json={'customer_id': WEB_CID, 'content': f'A: update {i}?',
                                                          'chat_token': TOKEN_A})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
            # since = {A}: 1 thiết bị từ sau trả lời — trước đây không cần chọn, trả lời tiếp theo tới A
            r = self.staff_reply(f'Follow-up {i}')
            self.assertEqual((r.status_code, r.get_json()['code']), (409, 'reply_target_required'))
            time.sleep(0.03)
        leaked = [c for c in self.contents(TOKEN_A) if c.startswith(('Reply ', 'Follow-up'))]
        self.assertEqual(leaked, [])
        self.assertEqual([c for c in self.contents(TOKEN_B) if c.startswith('Reply ')],
                         ['Reply 0 for Jane', 'Reply 1 for Jane', 'Reply 2 for Jane'])

    def test_a_single_device_thread_keeps_the_newest_default(self):
        self.seed_thread(TWO_BROWSERS[2:])
        j = self.staff_reply('Hello Jane').get_json()
        self.assertEqual((j['success'], j['device'], j['reply_to']), (True, 'A', B_MSG_AT))   # 1 thiết bị = 'A'
        DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'customer', 'content': 'B: thanks!',
                                    'business_id': NAIL, 'created_at': '2099-01-01T00:00:00', 'chat_token_hash': HB})
        j = self.staff_reply('You are welcome').get_json()
        self.assertEqual((j['success'], j['device'], j['reply_to']), (True, 'A', '2099-01-01T00:00:00'))

    def test_a_legacy_message_before_the_last_reply_still_counts(self):
        # tin không có mã trình duyệt (cửa sổ chat cũ) TRƯỚC trả lời gần nhất vẫn là 1 thiết bị khác
        self.seed_thread((('customer', 'legacy: hello?', None, '2026-10-01T07:00:00'),) + TWO_BROWSERS[2:])
        self.assertEqual(self.staff_reply('Hello Jane', reply_to=B_MSG_AT).status_code, 200)
        r = self.staff_reply('Follow-up')
        self.assertEqual((r.status_code, r.get_json()['code']), (409, 'reply_target_required'))

    def test_two_devices_since_the_reply_keep_the_since_wording_and_both_languages(self):
        self.seed_thread(ATTACK)
        stamp, err = NS['_web_reply_stamp'](WEB_CID, None)       # chưa có trả lời: cả 2 thiết bị nhắn "từ sau trả lời"
        self.assertIsNone(stamp)
        self.assertEqual((err[0], err[3]), (409, 'reply_target_required'))
        self.assertIn('since the last reply', err[2])
        self.assertIn('từ sau trả lời gần nhất', err[1])
        self.assertEqual(self.staff_reply('Hello Jane', reply_to=B_MSG_AT).status_code, 200)
        stamp, err = NS['_web_reply_stamp'](WEB_CID, None)       # sau trả lời: cả hội thoại
        self.assertIsNone(stamp)
        self.assertEqual((err[0], err[3]), (409, 'reply_target_required'))
        self.assertIn(WIDE_EN, err[2])
        self.assertIn('2 thiết bị khác nhau đã nhắn bằng số này trong hội thoại', err[1])
        self.assertIn('CHƯA được gửi', err[1])
        stamp, err = NS['_web_reply_stamp'](WEB_CID, B_MSG_AT)   # chọn thiết bị: luôn được
        self.assertIsNone(err)
        self.assertEqual((stamp['chat_token_hash'], stamp['device'], stamp['reply_to']), (HB, 'B', B_MSG_AT))

    def test_superadmin_follow_ups_on_tenant_and_landing_lead_threads(self):
        self.seed_thread(ATTACK)
        self.assertEqual(self.sa_post(WEB_CID, content='BitPaw support here', reply_to=B_MSG_AT).status_code, 200)
        r = self.sa_post(WEB_CID, content='BitPaw support: anything else?')
        self.assertEqual((r.status_code, r.get_json()['code']), (409, 'reply_target_required'))
        self.assertNotIn('BitPaw support: anything else?', self.contents(TOKEN_A))
        # landing 'Talk to Human Agent': Jane (B) nhắn, kẻ gian (A) nhắn sau, admin chọn Jane; A nhắn 1 tin sau trả lời
        self.assertEqual(self.lead_send(TOKEN_B, 'Jane here, call me about pricing').status_code, 200)
        time.sleep(0.03)
        self.assertEqual(self.lead_send(TOKEN_A, 'any update?').status_code, 200)
        jane_at = _customer_at(id4.LEAD_CID, HB)
        self.assertEqual(self.sa_post(id4.LEAD_CID, content='Hi Jane, your quote is $49/month', reply_to=jane_at).status_code, 200)
        r = self.sa_post(id4.LEAD_CID, content='Follow-up for Jane')
        self.assertEqual((r.status_code, r.get_json()['code']), (409, 'reply_target_required'))
        time.sleep(0.03)
        self.assertEqual(self.lead_send(TOKEN_A, 'and me?').status_code, 200)
        r = self.sa_post(id4.LEAD_CID, content='Follow-up for Jane')
        self.assertEqual((r.status_code, r.get_json()['code']), (409, 'reply_target_required'))
        a = json.dumps(self.lead_contents(TOKEN_A))
        for text in ('Hi Jane, your quote is $49/month', 'Follow-up for Jane'):
            self.assertNotIn(text, a)
        self.assertIn('Hi Jane, your quote is $49/month', self.lead_contents(TOKEN_B))


# ============================================================ 1. bp_reply_target.js THẬT
class ReplyTargetLibTests(id4._Base):
    def test_checker_probe_plan_after_picking_the_victim_has_no_default(self):
        self.seed_thread(AFTER_REPLY)
        out = _lib(self, '''
          const p = BPReplyTarget.plan(D.thread, true);
          extra.p = { mustPick: p.mustPick, choose: p.choose, since: p.sinceCount,
                      choices: p.choices.map((c) => [c.device, c.reply_to]) };
          extra.t = BPReplyTarget.target(p, null);
          extra.tB = BPReplyTarget.target(p, 'B');
          extra.need = [BPReplyTarget.needsPick(p, null), BPReplyTarget.needsPick(p, 'B'), BPReplyTarget.needsPick(p, 'A'),
                        BPReplyTarget.needsPick(p, 'Z')];
          BPReplyTarget.renderBar(document.getElementById('bar'), p, null, 'en', () => {});
          extra.bar = barState('bar');
        ''', thread=self.owner_get()['data'])
        x = out['extra']
        self.assertEqual(x['p'], {'mustPick': True, 'choose': True, 'since': 0,
                                  'choices': [['A', A_LAST_AT], ['B', B_MSG_AT]]})
        self.assertIsNone(x['t'])                                  # trước: tin mới nhất = A (kẻ gian)
        self.assertEqual(x['tB']['reply_to'], B_MSG_AT)
        self.assertEqual(x['need'], [True, False, False, True])
        self.assertEqual((x['bar']['hidden'], x['bar']['target'], x['bar']['selected']), (False, 'pick', PICK))
        self.assertEqual([v for v, _t in x['bar']['options']], [PICK, 'A', 'B'])
        self.assertIn('2 different devices have messaged from this number — your reply goes only to:', x['bar']['text'])
        self.assertIn(MUST_PICK_EN, ' '.join(x['bar']['text']))

    def test_every_device_stays_pickable_when_two_others_write_after_the_reply(self):
        hc = T.chat_token_hash('tokC' * 6)
        # nạn nhân (HB) nhắn đầu tiên -> 'A'; nhân viên trả lời; 2 trình duyệt khác (HA -> 'B', hc -> 'C') nhắn sau đó
        rows = (('customer', 'Jane: can you move my 3pm gel?', HB, '2026-10-01T08:00:00'),
                ('staff', 'Hi Jane, moved to 4pm', HB, '2026-10-01T08:05:00'),
                ('customer', 'X1: any update?', HA, '2026-10-01T08:06:00'),
                ('customer', 'X2: hello??', hc, '2026-10-01T08:07:00'))
        self.seed_thread(rows)
        out = _lib(self, '''
          const p = BPReplyTarget.plan(D.thread, true);
          let picked = null;
          const draw = () => BPReplyTarget.renderBar(document.getElementById('bar'), p, picked, 'en', (d) => { picked = d; draw(); });
          draw();
          extra.before = barState('bar');
          pick('bar', 'A');
          extra.after = barState('bar');
          extra.t = BPReplyTarget.target(p, picked);
        ''', thread=self.owner_get()['data'])
        x = out['extra']
        self.assertEqual([v for v, _t in x['before']['options']], [PICK, 'A', 'B', 'C'])   # nạn nhân vẫn chọn được
        self.assertIn('2 different devices have messaged from this number since your last reply — your reply goes only to:',
                      x['before']['text'])
        self.assertEqual((x['after']['selected'], x['t']['reply_to']), ('A', '2026-10-01T08:00:00'))
        r = self.staff_reply('x')
        self.assertEqual((r.status_code, r.get_json()['code']), (409, 'reply_target_required'))
        r = self.staff_reply('Anything else, Jane?', reply_to=x['t']['reply_to'])
        self.assertEqual((r.status_code, r.get_json()['device']), (200, 'A'))
        self.assertIn('Anything else, Jane?', self.contents(TOKEN_B))
        self.assertNotIn('Anything else, Jane?', self.contents(TOKEN_A))

    def test_page_rule_and_server_rule_agree(self):
        threads = {'attack': ATTACK, 'after_reply': AFTER_REPLY, 'one': TWO_BROWSERS[2:],
                   'one_after_reply': TWO_BROWSERS[2:] + (('staff', 'Hello Jane', HB, '2026-10-01T08:30:00'),),
                   'legacy_before_reply': (('customer', 'legacy: hello?', None, '2026-10-01T07:00:00'),) + TWO_BROWSERS[2:]
                   + (('staff', 'Hello Jane', HB, '2026-10-01T08:30:00'),),
                   'attacker_once_after_reply': AFTER_REPLY + (('customer', 'A: ??', HA, '2026-10-01T08:31:00'),)}
        got = {}
        for name, rows in threads.items():
            cid = f'{NAIL}:04100000{len(got)}'
            self.seed_thread(rows, cid=cid)
            got[name] = (self.owner_get(cid)['data'], self.staff_reply('x', cid=cid).status_code == 409)
        out = _lib(self, '''
          extra.r = {};
          Object.keys(D.threads).forEach((k) => { const p = BPReplyTarget.plan(D.threads[k], true);
            extra.r[k] = [p.mustPick, BPReplyTarget.needsPick(p, null), BPReplyTarget.target(p, null) === null]; });
        ''', threads={k: v[0] for k, v in got.items()})
        for name, (_rows, refused) in got.items():
            self.assertEqual(out['extra']['r'][name], [refused] * 3, name)
        self.assertEqual({k: v[1] for k, v in got.items()},
                         {'attack': True, 'after_reply': True, 'one': False, 'one_after_reply': False,
                          'legacy_before_reply': True, 'attacker_once_after_reply': True})


# ============================================================ 1. trang THẬT (node) <-> route thật
class ReplyTargetPageTests(id4._Base):
    CUSTOMERS = [{'id': WEB_CID, 'business_id': NAIL, 'channel': 'web'}]

    def _ai_bot(self, scenario, responses, lang='en'):
        return id4.run_dom(self, id4.ai_bot_src(self), scenario, pre=id4.AI_BOT_PRE, cid=WEB_CID, lang=lang,
                           customers=self.CUSTOMERS, responses=responses)

    def test_checker_probe_owner_console_needs_a_pick_before_every_send(self):
        self.seed_thread(AFTER_REPLY)
        thread = self.owner_get()
        out = self._ai_bot('''
          await loadMessages(D.cid);
          extra.bar0 = barState('replyTargetBar');
          userInput.value = 'Anything else, Jane?';
          await handleUserSubmit(null);
          extra.blocked = [userInput.value, calls.filter((c) => c.method === 'POST').length];
          pick('replyTargetBar', 'B');
          await handleUserSubmit(null);
          extra.afterSend = barState('replyTargetBar');
          await new Promise((r) => setTimeout(r, 30));            // tải lại hội thoại sau khi gửi
          extra.afterReload = barState('replyTargetBar');
          userInput.value = 'One more thing, Jane';
          await handleUserSubmit(null);
          extra.second = [userInput.value, calls.filter((c) => c.method === 'POST').length];
        ''', [{'status': 200, 'body': thread},
              {'status': 200, 'body': {'success': True, 'device': 'B', 'reply_to': B_MSG_AT}},
              {'status': 200, 'body': thread}])
        x = out['extra']
        self.assertEqual((x['bar0']['hidden'], x['bar0']['selected']), (False, PICK))   # trước: 'A' (kẻ gian) chọn sẵn
        self.assertEqual(x['blocked'], ['Anything else, Jane?', 0])
        self.assertIn(MUST_PICK_EN, out['toasts'][0][0])
        self.assertEqual(x['afterSend']['selected'], PICK)        # thiết bị vừa chọn không thành mặc định
        self.assertEqual(x['afterReload']['selected'], PICK)
        self.assertEqual(x['second'], ['One more thing, Jane', 1])
        self.assertIn(MUST_PICK_EN, out['toasts'][-1][0])
        posts = _posts(out)
        self.assertEqual(json.loads(posts[0]['body'])['reply_to'], B_MSG_AT)
        r = self.owner_post(posts[0])
        self.assertEqual((r.status_code, r.get_json()['device']), (200, 'B'))
        self.assertIn('Anything else, Jane?', self.contents(TOKEN_B))
        self.assertNotIn('Anything else, Jane?', self.contents(TOKEN_A))

    def test_checker_probe_silent_reload_after_the_attacker_posts_once(self):
        # nhân viên vừa trả lời V và đang gõ tiếp; X nhắn 1 tin -> SSE tải lại (since = {X}) -> Gửi bị chặn, không tới X
        self.seed_thread(AFTER_REPLY)
        before = self.owner_get()
        DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'customer', 'content': 'A: any news?',
                                    'business_id': NAIL, 'created_at': '2026-10-01T08:31:00', 'chat_token_hash': HA})
        after = self.owner_get()
        out = self._ai_bot('''
          await loadMessages(D.cid);
          userInput.value = 'Moved to 4pm, Jane';
          await loadMessages(D.cid, { silent: true });
          await handleUserSubmit(null);
          extra.input = userInput.value;
          extra.bar = barState('replyTargetBar');
        ''', [{'status': 200, 'body': before}, {'status': 200, 'body': after}])
        self.assertEqual(_posts(out), [])
        self.assertEqual(out['extra']['input'], 'Moved to 4pm, Jane')
        self.assertEqual((out['extra']['bar']['hidden'], out['extra']['bar']['selected']), (False, PICK))
        self.assertEqual([v for v, _t in out['extra']['bar']['options']], [PICK, 'A', 'B'])
        self.assertEqual(self.staff_reply('Moved to 4pm, Jane').status_code, 409)   # server cũng chặn

    def test_owner_console_handles_the_conversation_wide_409(self):
        # Gửi lúc hội thoại chưa tải xong (replyPlan = null) -> không reply_to -> server 409 -> báo + trả chữ + hiện thanh chọn
        self.seed_thread(AFTER_REPLY)
        thread = self.owner_get()
        refused = self.staff_reply('Hi Jane')
        self.assertEqual(refused.status_code, 409)
        out = self._ai_bot('''
          userInput.value = 'Hi Jane';
          await handleUserSubmit(null);
          await new Promise((r) => setTimeout(r, 30));
          extra.input = userInput.value;
          extra.bar = barState('replyTargetBar');
        ''', [{'status': 409, 'body': refused.get_json()}, {'status': 200, 'body': thread}])
        self.assertNotIn('reply_to', json.loads(_posts(out)[0]['body']))
        self.assertEqual(out['extra']['input'], 'Hi Jane')
        self.assertTrue(any(WIDE_EN in m and kind == 'error' for m, kind in out['toasts']), out['toasts'])
        self.assertEqual([c['method'] for c in out['calls']], ['POST', 'GET'])
        self.assertEqual((out['extra']['bar']['hidden'], out['extra']['bar']['selected']), (False, PICK))

    def test_crm_inbox_needs_a_pick_before_every_send(self):
        self.seed_thread(AFTER_REPLY)
        thread = self.owner_get()
        refused = self.staff_reply('Hi Jane').get_json()
        out = id4.run_dom(self, id4.crm_src(self), '''
          await loadInboxMessages(D.cid);
          const input = document.getElementById('liveChatInput');
          input.value = 'Anything else?';
          await sendLiveMessage();
          extra.blocked = [input.value, calls.filter((c) => c.method === 'POST').length, barState('inboxReplyTargetBar').selected];
          pick('inboxReplyTargetBar', 'B');
          await sendLiveMessage();
          extra.after = barState('inboxReplyTargetBar').selected;
          input.value = 'One more';
          await sendLiveMessage();
          extra.second = [input.value, calls.filter((c) => c.method === 'POST').length];
          inboxReplyPlan = null;                               // Gửi lúc hội thoại đang tải lại -> server 409
          await sendLiveMessage();
          extra.after409 = [input.value, barState('inboxReplyTargetBar').selected];
        ''', pre=id4.CRM_PRE, cid=WEB_CID, lang='en', customers=self.CUSTOMERS,
            responses=[{'status': 200, 'body': thread}, {'status': 200, 'body': {'success': True, 'device': 'B'}},
                       {'status': 200, 'body': thread}, {'status': 409, 'body': refused}, {'status': 200, 'body': thread}])
        x = out['extra']
        self.assertEqual(x['blocked'], ['Anything else?', 0, PICK])
        self.assertEqual(x['after'], PICK)
        self.assertEqual(x['second'], ['One more', 1])
        self.assertEqual(x['after409'], ['One more', PICK])
        self.assertTrue(any(WIDE_EN in m for m, _k in out['toasts']), out['toasts'])
        posts = _posts(out)
        self.assertEqual(len(posts), 2)
        self.assertEqual(json.loads(posts[0]['body'])['reply_to'], B_MSG_AT)
        self.assertNotIn('reply_to', json.loads(posts[1]['body']))
        self.assertEqual(self.owner_post(posts[0]).get_json()['device'], 'B')

    def test_superadmin_needs_a_pick_before_every_send(self):
        self.seed_thread(AFTER_REPLY)
        msgs = sorted(DB.bot_messages.find({'customer_id': WEB_CID}), key=lambda m: m['created_at'])
        for m in msgs:
            m.pop('_id', None)
        get = {'success': True, 'messages': msgs, 'customer': {'id': WEB_CID, 'business_id': NAIL, 'channel': 'web'}}
        refused = self.sa_post(WEB_CID, content='BitPaw support here')
        self.assertEqual(refused.status_code, 409)
        out = id4.run_dom(self, id4.sa_src(self), '''
          const input = document.getElementById('chatReplyInput');
          await openChatConversation(encodeURIComponent(D.cid));
          extra.bar0 = barState('chatReplyTargetBar').selected;
          input.value = 'BitPaw support here';
          await sendSuperAdminChatReply();
          extra.blocked = [input.value, calls.filter((c) => c.method === 'POST').length];
          pick('chatReplyTargetBar', 'B');
          await sendSuperAdminChatReply();
          extra.after = [input.value, barState('chatReplyTargetBar').selected];
          input.value = 'Anything else?';
          await sendSuperAdminChatReply();
          extra.second = [input.value, calls.filter((c) => c.method === 'POST').length];
        ''', pre=id4.SA_PRE, cid=WEB_CID, lang='en',
            responses=[{'status': 200, 'body': get}, {'status': 200, 'body': {'success': True, 'device': 'B'}},
                       {'status': 200, 'body': get}])
        x = out['extra']
        self.assertEqual(x['bar0'], PICK)
        self.assertEqual(x['blocked'], ['BitPaw support here', 0])
        self.assertEqual(x['after'], ['', PICK])
        self.assertEqual(x['second'], ['Anything else?', 1])
        posts = _posts(out)
        self.assertEqual([json.loads(p['body']).get('reply_to') for p in posts], [B_MSG_AT])
        self.assertEqual(self.sa_post(WEB_CID, **json.loads(posts[0]['body'])).get_json()['device'], 'B')


# ============================================================ 2. không VND mặc định trên đường tiền của AI / khách
import ast  # noqa: E402
import inspect  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import types  # noqa: E402
from datetime import datetime  # noqa: E402
from unittest.mock import patch  # noqa: E402

import ai_packs  # noqa: E402
import booking_rules  # noqa: E402
import currency_utils  # noqa: E402
import reservations_core as rc  # noqa: E402
import ai_copilot_tools as copilot_tools  # noqa: E402
import ai_packs.hotel as hotel  # noqa: E402
from tenant_engine import TenantEngine  # noqa: E402

_app = sys.modules.get('app')   # nail_turns: `from app import login_required` — 'app' giả, KHÔNG BAO GIỜ nạp app.py thật
if _app is None:
    _app = sys.modules['app'] = types.ModuleType('app')
if not hasattr(_app, 'login_required'):
    _app.login_required = lambda f: f
import nail_turns  # noqa: E402

MONEY_DONG = re.compile(r'\d[\d.,]*\s?đ')   # số tiền in bằng đ ('45đ', '45.000đ')
# (id, múi giờ trang Nhắn tin, hồ sơ, tiền mong đợi, nước mong đợi)
SHOPS = (('cur_ca', None, {'country': 'CA'}, 'CAD', 'CA'),
         ('cur_gb', None, {'country': 'UK'}, 'GBP', 'GB'),
         ('cur_us', None, {'country': 'US'}, 'USD', 'US'),
         ('cur_vn', None, {'country': 'VN', 'currency': 'VND'}, 'VND', 'VN'),
         ('cur_vn_auto', None, {'country': 'VN'}, 'VND', 'VN'),
         ('cur_old_vnd', None, {'currency': 'VND'}, 'VND', 'VN'),
         ('cur_tz_au', 'Australia/Melbourne', {}, 'AUD', 'AU'),
         ('cur_tz_nz', 'Pacific/Auckland', {}, 'NZD', 'NZ'),
         ('cur_tz_ca', 'America/Toronto', {}, 'CAD', 'CA'),
         ('cur_other', 'America/New_York', {'country': 'OTHER'}, 'USD', ''),
         ('cur_blank', None, {}, 'USD', ''),
         ('cur_eur', None, {'country': 'OTHER', 'currency': 'EUR'}, 'EUR', ''))
WANT = {bid: cur for bid, _tz, _f, cur, _c in SHOPS}


def _app_import_fallback(module):
    """Nhánh `except` của `try: from <module> import ...` ở đầu app.py (mã nguồn THẬT qua ast), chạy như khi import lỗi."""
    for node in core._TREE.body:
        if isinstance(node, ast.Try) and any(isinstance(s, ast.ImportFrom) and s.module == module for s in node.body):
            ns = {'db': DB, 're': re, 'math': math, '_import_err': ImportError(module), 'print': lambda *a, **k: None}
            body = ast.Module(body=node.handlers[0].body, type_ignores=[])
            exec(compile(ast.fix_missing_locations(body), f'app.py::except {module}', 'exec'), ns)
            return ns
    raise AssertionError(f'app.py: không thấy try: from {module} import ...')


class CurrencyFallbackTests(unittest.TestCase):
    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()
        nail_turns._CACHE.clear()
        for bid, tz, fields, _cur, _c in SHOPS:
            DB.businesses.insert_one(dict({'id': bid, 'name': f'Shop {bid}'}, **fields))
            if tz:
                DB.messaging_settings.insert_one({'business_id': bid, 'timezone': tz})

    def tearDown(self):
        nail_turns._CACHE.clear()

    def all_of(self, fn):
        return {bid: fn(bid) for bid in WANT}

    def test_reservations_core_currency_never_defaults_to_dong(self):
        self.assertEqual(self.all_of(rc.currency), WANT)                          # đường thường (TenantEngine)
        # tenant_engine không nạp được (trước: 'VND' cho MỌI quán), trả {} hay lỗi (trước: `or 'VND'`)
        with patch.dict(sys.modules, {'tenant_engine': None}):
            self.assertEqual(self.all_of(rc.currency), WANT)
            self.assertEqual((rc.currency('ghost'), rc.currency(None)), ('USD', 'USD'))
        with patch.object(TenantEngine, 'get_region_config', return_value={}):
            self.assertEqual(self.all_of(rc.currency), WANT)
        with patch.object(TenantEngine, 'get_region_config', side_effect=RuntimeError('boom')):
            self.assertEqual(self.all_of(rc.currency), WANT)
            self.assertEqual(rc.currency('ghost'), 'USD')
            self.assertEqual(rc.money(45, rc.currency('cur_ca')), 'CA$45.00')   # gói fnb / karaoke: không '45đ'
            self.assertEqual(rc.money(45000, rc.currency('cur_vn')), '45.000đ')  # quán Việt Nam vẫn VND
        fn = ast.parse(inspect.getsource(rc.currency)).body[0]
        fn.body = fn.body[1:]                                   # bỏ docstring: chỉ xét mã
        self.assertNotIn('VND', ast.unparse(fn))

    def test_app_tenant_engine_import_fallback_follows_the_shop(self):
        te = _app_import_fallback('tenant_engine')['TenantEngine']
        for bid, _tz, _f, cur, country in SHOPS:
            self.assertEqual(te.get_region_config(bid), {'country': country, 'currency': cur}, bid)
            self.assertEqual(te.get_region_config(bid), TenantEngine.get_region_config(bid), bid)   # = tenant_engine thật
        for bid in ('ghost', None, ''):
            self.assertEqual(te.get_region_config(bid), {'country': '', 'currency': 'USD'}, bid)   # trước: VN / VND
        self.assertIsNone(te.resolve_tenant('u1'))

    def test_app_format_money_import_fallback_matches_currency_utils(self):
        fm = _app_import_fallback('currency_utils')['format_money']
        for cur in (None, '', 'USD', 'usd', 'AUD', 'VND', 'vnd', 'CAD', 'NZD', 'GBP', 'EUR', 'đ', 'x'):
            for amount in (45, 45000, 1200.5, -12, 0, None, 'abc', float('nan'), float('inf'), -0.001):
                self.assertEqual(fm(amount, cur), currency_utils.format_money(amount, cur), (amount, cur))
        self.assertEqual(fm(45), '$45.00')                    # trước: '45đ' (mặc định VND)
        self.assertEqual(fm(45, 'AUD'), '$45.00')             # trước: '45đ' (mọi tiền khác USD)
        self.assertEqual(fm(45, 'CAD'), 'CA$45.00')
        self.assertEqual(fm(45000, 'VND'), '45.000đ')
        for cur in (None, 'USD', 'AUD', 'CAD', 'NZD', 'GBP', 'EUR'):
            self.assertIsNone(MONEY_DONG.search(fm(1234, cur)), cur)

    def test_app_has_no_vn_vnd_region_default_left(self):
        self.assertNotIn('"currency": "VND"}', core.APP_SRC)
        self.assertNotIn("def format_money(amount, currency='VND')", core.APP_SRC)

    def test_copilot_business_currency_follows_the_shop_country(self):
        for bid, cur in WANT.items():
            biz = DB.businesses.find_one({'id': bid}, {'_id': 0, 'currency': 1, 'country': 1})   # như ai_copilot.business_snapshot
            self.assertEqual(copilot_tools.business_currency(bid, biz), cur, bid)
            self.assertEqual(copilot_tools.business_currency(bid), cur, bid)                  # tự đọc DB
        self.assertEqual(copilot_tools.business_currency('ghost'), 'USD')
        self.assertEqual(copilot_tools.business_currency(None, {'country': 'GB'}), 'GBP')     # trước: USD
        self.assertEqual(copilot_tools.business_currency(None, {'currency': 'aud'}), 'AUD')
        self.assertIsNone(MONEY_DONG.search(copilot_tools._money('cur_tz_au')(1234)))
        self.assertEqual(copilot_tools._money('cur_vn')(1200000), '1.200.000đ')

    def test_nail_turns_shop_currency_follows_the_shop_country(self):
        self.assertEqual(self.all_of(nail_turns.shop_currency), WANT)   # trước: tiệm chỉ có múi giờ -> USD, 'UK' -> USD
        self.assertEqual(nail_turns.shop_currency('ghost'), 'USD')

    def test_hotel_currency_follows_the_shop_country(self):
        for bid, cur in WANT.items():
            self.assertEqual(hotel._currency(hotel._shop(bid), bid), cur, bid)
            self.assertEqual(hotel._currency(DB.businesses.find_one({'id': bid})), cur, bid)   # dòng đủ (có 'id')
        self.assertEqual((hotel._currency({}, 'ghost'), hotel._currency({}), hotel._currency(None)), ('USD', 'USD', 'USD'))
        with patch.object(hotel.ai_packs, 'shop_country', None):   # gói nạp riêng (registry chưa có shop_country)
            self.assertEqual([hotel._currency({'country': c}) for c in ('UK', 'OTHER', 'VN', 'nz')], ['GBP', 'USD', 'VND', 'NZD'])
        with patch.object(hotel.ai_packs, 'shop_country', side_effect=RuntimeError('boom')):
            self.assertEqual(hotel._currency({'country': 'CA'}, 'cur_ca'), 'CAD')

    def test_hotel_prompt_quotes_rates_in_the_hotel_currency(self):
        for rid, (bid, price) in enumerate((('cur_tz_nz', 120), ('cur_vn_auto', 1200000), ('cur_blank', 99)), start=1):
            DB.hotel_rooms.insert_one({'id': rid, 'business_id': bid, 'room_number': f'10{rid}', 'room_type': 'Deluxe',
                                       'price_per_night': price, 'capacity': 2, 'status': 'available'})
        now = datetime(2026, 10, 1, 10, 0)
        nz = hotel.facts('cur_tz_nz', 'en', now)
        self.assertIn('120.00 NZD per night', nz)           # trước: '$120.00' (khách sạn chỉ có múi giờ -> USD)
        self.assertIsNone(MONEY_DONG.search(nz))
        self.assertIn('1.200.000đ', hotel.facts('cur_vn_auto', 'vi', now))
        blank = hotel.facts('cur_blank', 'en', now)
        self.assertIn('$99.00 per night', blank)
        self.assertIsNone(MONEY_DONG.search(blank))


if __name__ == '__main__':
    unittest.main(verbosity=2)
