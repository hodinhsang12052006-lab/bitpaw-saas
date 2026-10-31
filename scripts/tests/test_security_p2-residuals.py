# -*- coding: utf-8 -*-
"""Test OFFLINE — security p2-residuals (phần còn sót của review Phase 2 vòng 5):
  1. (HIGH) AIContextEngine.build_context_prompt (chat nội bộ /api/ai/chat của chủ tiệm): bảng giá, doanh thu 30 ngày, tổng chi
     tiêu của khách KHÔNG bao giờ mặc định VND — tiền đã lưu, else tiền của nước tiệm (ai_packs.shop_country: hồ sơ -> múi giờ
     trang Nhắn tin -> tiền), else USD. Tiệm {country:'CA'} / {country:'OTHER'} / {} từng bị báo '45đ'.
  2. (MEDIUM) ai_packs/retail.currency_of (AI bán lẻ cho KHÁCH: giá retail_find_products, my_holds, 'Prices are in ...'):
     cùng quy tắc trên — tiệm 'Nước khác' / chưa có nước không còn báo giá bằng đ.
  3. (MEDIUM) Hộp thư web: từ 2 thiết bị trở lên nhắn từ sau trả lời gần nhất của nhân viên -> ô soạn tin KHÔNG âm thầm gửi cho
     thiết bị mới nhất (kẻ gian gõ SĐT nạn nhân, nhắn liên tục để tin của mình luôn mới nhất): Gửi bị chặn tới khi nhân viên
     chọn thiết bị; server từ chối trả lời không có reply_to trên hội thoại như vậy bằng 409 (reply_target_required) mà trang
     xử lý (báo rõ + tải lại hội thoại + hiện thanh chọn thiết bị).
  4. (LOW) Khách sạn: yêu cầu đang chờ nhân viên (STAFF_REQUEST) của chính chat này — khách sửa số khách / nói lại y hệt — đi
     thẳng vào đường cập nhật / trùng TRƯỚC giới hạn số phòng mỗi chat (_caps), không bị từ chối "đặt đoàn"; và khi trần giữ
     phòng web đã nhả, lời sửa đó không ghi thêm 1 phòng thật bên cạnh yêu cầu cũ (nhân viên Duyệt = 2 phòng cho 1 khách).

Hai bộ DB giả không chung được 1 tiến trình (test_phase2_receptionist_core thay ai_packs thật; test_phase2_hotel_pack thay
ai_packs bằng gói nhỏ): chạy không tham số -> mỗi nhóm 1 tiến trình con (P2R_GROUP=core | hotel).
KHÔNG import app.py thật, KHÔNG MongoDB thật, KHÔNG mạng / API trả phí. Mã JS THẬT của trang chạy trong node.
Chạy: python scripts/tests/test_security_p2-residuals.py
"""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
GROUP = os.environ.get('P2R_GROUP', '')
MONEY_DONG = re.compile(r'\d[\d.,]*\s?đ')   # số tiền in bằng đ ('45đ', '45.000đ') — chữ tiếng Việt có 'đ' không tính


if GROUP == 'core':
    import test_phase2_fix4_identity4 as id4  # noqa: E402  (DB giả + stub của test_phase2_receptionist_core, route bot / portal)

    core = id4.core
    DB, ROOT = core.DB, core.ROOT

    import booking_rules  # noqa: E402
    import ai_context_engine as ACE  # noqa: E402
    from ai_packs import retail  # noqa: E402

    def _shop(bid, tz=None, **fields):
        DB.businesses.insert_one(dict({'id': bid, 'name': f'Shop {bid}', 'industry_code': 'retail'}, **fields))
        if tz:
            DB.messaging_settings.insert_one({'business_id': bid, 'timezone': tz})

    # ============================================================ 1. AIContextEngine: không VND mặc định
    class ContextEngineCurrencyTests(unittest.TestCase):
        def setUp(self):
            DB.reset()
            booking_rules._CACHE.clear()

        def prompt(self, bid, price=45, spent=120, **shop):
            _shop(bid, **shop)
            DB.products.insert_one({'id': 1, 'business_id': bid, 'is_active': 1, 'name': 'Widget', 'category': 'x', 'price': price})
            DB.customers.insert_one({'business_id': bid, 'phone': '0412345678', 'name': 'Ann', 'tier': 'VIP', 'total_spent': spent})
            return ACE.AIContextEngine.build_context_prompt(bid, None, customer_phone='0412345678',
                                                            include_private_data=True)['prompt']

        def test_checker_probe_shops_without_a_stored_currency_never_get_dong(self):
            for bid, shop, want in (('ca', {'country': 'CA'}, 'CA$'), ('other', {'country': 'OTHER'}, '$'),
                                    ('blank', {}, '$'), ('nz', {'country': 'NZ'}, 'NZ$'), ('gb', {'country': 'GB'}, '£')):
                p = self.prompt(bid, **shop)
                self.assertIn(f'- Widget (x): {want}45.00', p, bid)                 # bảng giá
                self.assertIn(f'Tổng chi tiêu từ trước tới nay: {want}120.00', p, bid)   # tổng chi tiêu của khách
                self.assertIn(f'30 ngày gần nhất: {want}0.00.', p, bid)             # doanh thu
                self.assertFalse(MONEY_DONG.search(p), (bid, MONEY_DONG.findall(p)))

        def test_messaging_time_zone_decides_for_a_shop_without_country(self):
            p = self.prompt('tz-ca', tz='America/Toronto')
            self.assertIn('- Widget (x): CA$45.00', p)
            self.assertFalse(MONEY_DONG.search(p))

        def test_vietnamese_and_stored_currencies_are_kept(self):
            p = self.prompt('vn', price=45000, spent=1200000, country='VN')
            self.assertIn('- Widget (x): 45.000đ', p)
            self.assertIn('1.200.000đ', p)
            self.assertIn('- Widget (x): $45.00', self.prompt('au', currency='AUD', country='AU'))
            self.assertIn('- Widget (x): 45.00 EUR', self.prompt('eur', currency='EUR', country='VN'))   # tiền đã lưu thắng
            self.assertIn('- Widget (x): 45.000đ', self.prompt('vnd', price=45000, currency='VND'))

        def test_no_shop_record_is_usd(self):
            self.assertEqual(ACE._tenant_currency('ghost', None), 'USD')
            self.assertEqual(ACE._tenant_currency('ghost', {}), 'USD')

    # ============================================================ 2. AI bán lẻ (khách): currency_of không VND mặc định
    class RetailCurrencyTests(unittest.TestCase):
        def setUp(self):
            DB.reset()
            booking_rules._CACHE.clear()
            retail._INDEXES.clear()

        def test_checker_probe_other_and_blank_shops_are_usd(self):
            _shop('other', country='OTHER')
            _shop('blank')
            for bid in ('other', 'blank'):
                cur = retail.currency_of(bid)
                self.assertEqual(cur, 'USD', bid)
                self.assertEqual(retail.money(45, cur), '$45.00')
                self.assertIn('Prices are in USD.', retail.facts(bid, 'en', None))   # prompt của AI bán lẻ

        def test_country_and_time_zone_follow_shop_country(self):
            _shop('ca', country='CA')
            _shop('tz', tz='America/Toronto')
            _shop('vn', country='VN')
            _shop('au', currency='aud', country='CA')
            self.assertEqual([retail.currency_of(b) for b in ('ca', 'tz', 'vn', 'au')], ['CAD', 'CAD', 'VND', 'AUD'])
            self.assertEqual(retail.currency_of('x', {'country': 'OTHER'}), 'USD')     # tài liệu shop truyền sẵn

        def test_customer_facing_product_search_quotes_usd_not_dong(self):
            _shop('other', country='OTHER')
            DB.products.insert_one({'id': 71, 'business_id': 'other', 'is_active': 1, 'channel_type': 'retail',
                                    'name': 'Blue Widget', 'category': 'Tools', 'price': 45, 'stock': 9})
            ctx = {'business_id': 'other', 'customer_id': None, 'channel': 'web', 'phone': None, 'contact_phone': None,
                   'chat_token_hash': 'tokA', 'lang': 'en', 'now_local': None, 'customer_name': None}
            out = retail.execute('retail_find_products', {'query': 'widget'}, ctx)
            self.assertEqual(out['currency'], 'USD')
            self.assertEqual(out['matches'][0]['price'], '$45.00')
            self.assertFalse(MONEY_DONG.search(json.dumps(out, ensure_ascii=False)))

    # ============================================================ 3. hộp thư web: >= 2 thiết bị -> phải chọn thiết bị
    ATTACK, B_MSG_AT, TWO_BROWSERS = id4.ATTACK, id4.B_MSG_AT, id4.TWO_BROWSERS
    WEB_CID, NAIL, HA, HB = id4.WEB_CID, id4.NAIL, id4.HA, id4.HB
    TOKEN_A, TOKEN_B = id4.TOKEN_A, id4.TOKEN_B
    A_LAST_AT = ATTACK[-1][3]          # tin mới nhất của kẻ gian (thiết bị A), SAU tin của nạn nhân (B)
    PICK = '__pick__'
    MUST_PICK_EN = "Choose which device gets this reply before sending"
    MUST_PICK_VI = "Chọn thiết bị nhận trả lời trước khi gửi"

    def _lib(test, scenario, **data):
        """Chỉ static/js/bp_reply_target.js THẬT (không trang nào) trong node."""
        return id4.run_dom(test, '', scenario, **data)

    def _posts(out):
        return [c for c in out['calls'] if c['method'] == 'POST']

    class ReplyTargetServerTests(id4._Base):
        def test_checker_probe_no_reply_to_on_a_two_device_thread_is_refused(self):
            # kẻ gian (A) gõ SĐT nạn nhân, nhắn SAU nạn nhân (B): trả lời không reply_to KHÔNG còn âm thầm tới A
            self.seed_thread(ATTACK)
            n = len(DB.bot_messages.find({}))
            r = self.staff_reply('Hi Jane, your 3pm gel is moved to 4pm')
            self.assertEqual(r.status_code, 409, r.get_data(as_text=True)[:200])
            j = r.get_json()
            self.assertEqual((j['success'], j['code']), (False, 'reply_target_required'))
            self.assertIn('2 different devices', j['message'])
            self.assertIn('Nothing was sent', j['message'])
            for h in (HA, HB):
                self.assertNotIn(h, r.get_data(as_text=True))
            self.assertEqual(len(DB.bot_messages.find({})), n)                    # không ghi gì
            self.assertNotIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_A))
            self.assertFalse((DB.bot_customers.find_one({'id': WEB_CID}) or {}).get('ai_paused'))   # AI không bị tắt
            # chọn thiết bị (reply_to) -> gửi được, chỉ thiết bị đó thấy
            r = self.staff_reply('Hi Jane, your 3pm gel is moved to 4pm', reply_to=B_MSG_AT)
            self.assertEqual((r.status_code, r.get_json()['device']), (200, 'B'))
            self.assertIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_B))
            self.assertNotIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_A))

        def test_single_device_since_the_last_reply_keeps_the_newest_default(self):
            self.seed_thread(ATTACK)
            self.assertEqual(self.staff_reply('Hello Jane', reply_to=B_MSG_AT).status_code, 200)
            # từ sau trả lời đó chỉ 1 thiết bị nhắn -> không cần chọn (luồng thường không bị chặn)
            DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'customer', 'content': 'B: thanks!',
                                        'business_id': NAIL, 'created_at': '2099-01-01T00:00:00', 'chat_token_hash': HB})
            j = self.staff_reply('You are welcome').get_json()
            self.assertEqual((j['success'], j['device'], j['reply_to']), (True, 'B', '2099-01-01T00:00:00'))
            # thiết bị thứ 2 nhắn tiếp từ sau trả lời gần nhất -> lại phải chọn
            DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'customer', 'content': 'B: one more thing',
                                        'business_id': NAIL, 'created_at': '2099-01-02T00:00:00', 'chat_token_hash': HB})
            DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'customer', 'content': 'A: hello??',
                                        'business_id': NAIL, 'created_at': '2099-01-02T00:00:01', 'chat_token_hash': HA})
            self.assertEqual(self.staff_reply('Which of you?').status_code, 409)

        def test_a_message_without_browser_id_counts_as_another_device(self):
            self.seed_thread(TWO_BROWSERS[2:] + (('customer', 'legacy: hello?', None, '2026-10-01T08:20:00'),))
            r = self.staff_reply('Hello!')
            self.assertEqual((r.status_code, r.get_json()['code']), (409, 'reply_target_required'))
            self.assertEqual(self.staff_reply('Hello!', reply_to='2026-10-01T08:20:00').get_json()['device'], None)

        def test_superadmin_and_landing_lead_threads_follow_the_same_rule(self):
            self.seed_thread(ATTACK)
            r = self.sa_post(WEB_CID, content='BitPaw support here')
            self.assertEqual((r.status_code, r.get_json()['code']), (409, 'reply_target_required'))
            self.assertEqual(self.sa_post(WEB_CID, content='BitPaw support here', reply_to=B_MSG_AT).status_code, 200)
            # landing 'Talk to Human Agent': kẻ gian gõ SĐT của Jane, nhắn liên tục để tin mình luôn mới nhất
            self.assertEqual(self.lead_send(TOKEN_B, 'Jane here, call me about pricing').status_code, 200)
            for i in range(3):
                id4.time.sleep(0.02)
                self.assertEqual(self.lead_send(TOKEN_A, f'any update? {i}').status_code, 200)
            r = self.sa_post(id4.LEAD_CID, content='Hi Jane, your quote is $49/month')
            self.assertEqual((r.status_code, r.get_json()['code']), (409, 'reply_target_required'))
            self.assertNotIn('Hi Jane, your quote is $49/month', json.dumps(self.lead_contents(TOKEN_A)))
            jane_at = DB.bot_messages.find({'customer_id': id4.LEAD_CID, 'chat_token_hash': HB})[0]['created_at']
            self.assertEqual(self.sa_post(id4.LEAD_CID, content='Hi Jane, your quote is $49/month', reply_to=jane_at).status_code, 200)
            self.assertIn('Hi Jane, your quote is $49/month', self.lead_contents(TOKEN_B))
            self.assertNotIn('Hi Jane, your quote is $49/month', self.lead_contents(TOKEN_A))

        def test_page_rule_and_server_rule_agree(self):
            threads = {'attack': ATTACK, 'one': TWO_BROWSERS[2:], 'legacy': TWO_BROWSERS[2:] + (
                ('customer', 'legacy: hello?', None, '2026-10-01T08:20:00'),),
                'after_reply': ATTACK + (('staff', 'Hello Jane', HB, '2026-10-01T08:30:00'),
                                         ('customer', 'A: ??', HA, '2026-10-01T08:31:00'))}
            got = {}
            for name, rows in threads.items():
                cid = f'{NAIL}:04000000{len(got)}'
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
                             {'attack': True, 'one': False, 'legacy': True, 'after_reply': False})

    class ReplyTargetLibTests(id4._Base):
        def test_plan_needs_an_explicit_pick_and_the_prompt_is_not_a_device(self):
            self.seed_thread(ATTACK)
            out = _lib(self, '''
              const p = BPReplyTarget.plan(D.thread, true);
              const bar = document.getElementById('bar');
              let picked = null;
              const draw = () => BPReplyTarget.renderBar(bar, p, picked, 'en', (d) => { picked = d; draw(); });
              draw();
              extra.before = barState('bar');
              extra.t0 = BPReplyTarget.target(p, null);
              pick('bar', '__pick__');                          // dòng nhắc không phải thiết bị: không đổi gì
              extra.afterPrompt = [picked, barState('bar').target];
              pick('bar', 'B');
              extra.after = barState('bar');
              extra.t1 = BPReplyTarget.target(p, picked);
              extra.need = [BPReplyTarget.needsPick(p, null), BPReplyTarget.needsPick(p, 'B'), BPReplyTarget.needsPick(p, 'Z')];
              extra.web = BPReplyTarget.needsPick(BPReplyTarget.plan(D.thread, false), null);
            ''', thread=self.owner_get()['data'])
            x = out['extra']
            self.assertIsNone(x['t0'])                            # không bao giờ âm thầm lấy tin mới nhất (A)
            self.assertEqual(x['before']['target'], 'pick')
            self.assertEqual(x['before']['selected'], PICK)
            self.assertEqual([v for v, _t in x['before']['options']], [PICK, 'A', 'B'])
            self.assertIn(MUST_PICK_EN, ' '.join(x['before']['text']))
            self.assertEqual(x['afterPrompt'], [None, 'pick'])
            self.assertEqual((x['after']['selected'], x['after']['target']), ('B', 'B'))
            self.assertEqual([v for v, _t in x['after']['options']], ['A', 'B'])
            self.assertNotIn(MUST_PICK_EN, ' '.join(x['after']['text']))
            self.assertEqual(x['t1']['reply_to'], B_MSG_AT)
            self.assertEqual(x['need'], [True, False, True])
            self.assertFalse(x['web'])                            # Messenger / SMS...: không có thiết bị

    class ReplyTargetPageTests(id4._Base):
        CUSTOMERS = [{'id': WEB_CID, 'business_id': NAIL, 'channel': 'web'}]

        def _ai_bot(self, scenario, responses, lang='en'):
            return id4.run_dom(self, id4.ai_bot_src(self), scenario, pre=id4.AI_BOT_PRE, cid=WEB_CID, lang=lang,
                               customers=self.CUSTOMERS, responses=responses)

        def test_checker_probe_owner_console_blocks_send_until_a_device_is_picked(self):
            self.seed_thread(ATTACK)
            thread = self.owner_get()
            for lang, must in (('en', MUST_PICK_EN), ('vi', MUST_PICK_VI)):
                out = self._ai_bot('''
                  await loadMessages(D.cid);
                  userInput.value = 'Hi Jane, your 3pm gel is moved to 4pm';
                  await handleUserSubmit(null);
                  extra.blocked = { input: userInput.value, posts: calls.filter((c) => c.method === 'POST').length,
                                    bar: barState('replyTargetBar'), box: chatBox.innerHTML };
                  pick('replyTargetBar', 'B');
                  await handleUserSubmit(null);
                ''', [{'status': 200, 'body': thread}, {'status': 200, 'body': {'success': True, 'device': 'B', 'reply_to': B_MSG_AT}},
                      {'status': 200, 'body': thread}], lang=lang)
                b = out['extra']['blocked']
                self.assertEqual((b['posts'], b['input']), (0, 'Hi Jane, your 3pm gel is moved to 4pm'))   # chữ không mất
                self.assertNotIn('Hi Jane, your 3pm gel', b['box'])   # không hiện như đã gửi
                self.assertEqual((b['bar']['hidden'], b['bar']['selected']), (False, PICK))
                self.assertIn(must, out['toasts'][0][0])
                self.assertEqual(out['toasts'][0][1], 'error')
                posts = _posts(out)
                self.assertEqual(len(posts), 1)
                self.assertEqual(json.loads(posts[0]['body'])['reply_to'], B_MSG_AT)
            r = self.owner_post(posts[0])
            self.assertEqual((r.status_code, r.get_json()['device']), (200, 'B'))
            self.assertIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_B))
            self.assertNotIn('Hi Jane, your 3pm gel is moved to 4pm', self.contents(TOKEN_A))

        def test_silent_reload_race_does_not_redirect_a_typed_reply(self):
            # nhân viên đang gõ khi chỉ thấy tin của nạn nhân; SSE tải lại khi tin của kẻ gian tới -> Gửi bị chặn, không tới A
            self.seed_thread(TWO_BROWSERS)
            self.assertEqual(self.staff_reply('Hello both', reply_to=B_MSG_AT).status_code, 200)
            DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'customer', 'content': 'B: can you move it?',
                                        'business_id': NAIL, 'created_at': '2099-01-01T00:00:00', 'chat_token_hash': HB})
            only_victim = self.owner_get()
            DB.bot_messages.insert_one({'customer_id': WEB_CID, 'sender_type': 'customer', 'content': 'A: any update?',
                                        'business_id': NAIL, 'created_at': '2099-01-01T00:00:05', 'chat_token_hash': HA})
            with_attacker = self.owner_get()
            out = self._ai_bot('''
              await loadMessages(D.cid);
              extra.first = barState('replyTargetBar');
              userInput.value = 'Moved to 4pm, Jane';
              await loadMessages(D.cid, { silent: true });        // tín hiệu SSE: tin mới của thiết bị khác
              await handleUserSubmit(null);
              extra.input = userInput.value;
            ''', [{'status': 200, 'body': only_victim}, {'status': 200, 'body': with_attacker}])
            self.assertTrue(out['extra']['first']['hidden'] or out['extra']['first']['selected'] != PICK)
            self.assertEqual(_posts(out), [])
            self.assertEqual(out['extra']['input'], 'Moved to 4pm, Jane')

        def test_owner_console_handles_the_server_409(self):
            # Gửi lúc hội thoại chưa tải xong (replyPlan = null như onSelectCustomer) -> không reply_to -> server 409
            self.seed_thread(ATTACK)
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
            self.assertEqual(out['extra']['input'], 'Hi Jane')                         # chữ được trả lại ô soạn
            self.assertIn(['2 different devices have messaged from this number since the last reply — choose which device '
                           'gets your reply, then send again. Nothing was sent.', 'error'], out['toasts'])
            self.assertEqual([c['method'] for c in out['calls']], ['POST', 'GET'])      # tải lại hội thoại
            self.assertEqual((out['extra']['bar']['hidden'], out['extra']['bar']['selected']), (False, PICK))
            self.assertNotIn('Hi Jane', out['html'].get('chatBox', ''))                  # bong bóng tạm bị xoá khi tải lại

        def test_crm_inbox_blocks_then_handles_409(self):
            self.seed_thread(ATTACK)
            thread = self.owner_get()
            refused = self.staff_reply('Hi Jane').get_json()
            out = id4.run_dom(self, id4.crm_src(self), '''
              await loadInboxMessages(D.cid);
              const input = document.getElementById('liveChatInput');
              input.value = 'Hi Jane';
              await sendLiveMessage();
              extra.blocked = [input.value, calls.filter((c) => c.method === 'POST').length, barState('inboxReplyTargetBar').selected];
              inboxReplyPlan = null;                               // Gửi lúc hội thoại đang tải lại
              await sendLiveMessage();
              extra.after = [input.value, barState('inboxReplyTargetBar').selected];
              pick('inboxReplyTargetBar', 'B');
              await sendLiveMessage();
            ''', pre=id4.CRM_PRE, cid=WEB_CID, lang='en', customers=self.CUSTOMERS,
                responses=[{'status': 200, 'body': thread}, {'status': 409, 'body': refused}, {'status': 200, 'body': thread},
                           {'status': 200, 'body': {'success': True, 'device': 'B'}}, {'status': 200, 'body': thread}])
            self.assertEqual(out['extra']['blocked'], ['Hi Jane', 0, PICK])
            self.assertIn(MUST_PICK_EN, out['toasts'][0][0])
            self.assertEqual(out['extra']['after'], ['Hi Jane', PICK])
            self.assertIn('Nothing was sent', out['toasts'][1][0])
            posts = _posts(out)
            self.assertEqual(len(posts), 2)
            self.assertNotIn('reply_to', json.loads(posts[0]['body']))
            self.assertEqual(json.loads(posts[1]['body'])['reply_to'], B_MSG_AT)
            self.assertEqual(self.owner_post(posts[1]).get_json()['device'], 'B')

        def test_superadmin_blocks_then_handles_409(self):
            self.seed_thread(ATTACK)
            msgs = sorted(DB.bot_messages.find({'customer_id': WEB_CID}), key=lambda m: m['created_at'])
            for m in msgs:
                m.pop('_id', None)
            get = {'success': True, 'messages': msgs, 'customer': {'id': WEB_CID, 'business_id': NAIL, 'channel': 'web'}}
            refused = self.sa_post(WEB_CID, content='BitPaw support here').get_json()
            out = id4.run_dom(self, id4.sa_src(self), '''
              const input = document.getElementById('chatReplyInput');
              currentChatCustomerId = D.cid;                        // Gửi trước khi hội thoại tải xong -> server 409
              input.value = 'BitPaw support here';
              await sendSuperAdminChatReply();
              extra.after409 = [input.value, barState('chatReplyTargetBar').selected];
              await sendSuperAdminChatReply();                      // vẫn chưa chọn: trang chặn, không gửi
              extra.blocked = calls.filter((c) => c.method === 'POST').length;
              pick('chatReplyTargetBar', 'B');
              await sendSuperAdminChatReply();
            ''', pre=id4.SA_PRE, cid=WEB_CID, lang='en',
                responses=[{'status': 409, 'body': refused}, {'status': 200, 'body': get},
                           {'status': 200, 'body': {'success': True, 'device': 'B'}}, {'status': 200, 'body': get}])
            self.assertEqual(out['extra']['after409'], ['BitPaw support here', PICK])
            self.assertEqual(out['extra']['blocked'], 1)
            toasts = [t for t, _k in out['toasts']]
            self.assertIn('Nothing was sent', toasts[0])
            self.assertIn(MUST_PICK_EN, toasts[1])
            posts = _posts(out)
            self.assertEqual([json.loads(p['body']).get('reply_to') for p in posts], [None, B_MSG_AT])
            self.assertEqual(self.sa_post(WEB_CID, **json.loads(posts[1]['body'])).get_json()['device'], 'B')


elif GROUP == 'hotel':
    import test_phase2_fix5_hotel5 as h5  # noqa: E402  (DB giả + stub của test_phase2_hotel_pack, chat web vượt trần)

    hp, DB, rh, hotel, PackError, find, web, D, run = h5.hp, h5.DB, h5.rh, h5.hotel, h5.PackError, h5.find, h5.web, h5.D, h5.run
    PER_GUEST, PER_NETWORK = hotel.MAX_LIVE_AI_BOOKINGS_PER_GUEST, hotel.MAX_LIVE_AI_BOOKINGS_PER_NETWORK

    # ============================================================ 4. khách sạn: yêu cầu đang chờ của chính chat này
    class HotelWaitingRequestTests(h5._Req):
        def fill_to_the_guest_limit(self, c):
            self.assertTrue(self.book_as(c, 2, guests=1)['request_sent_to_team'])
            for _ in range(PER_GUEST - 1):
                self.assertTrue(self.book_as(c, 2, guests=1, another_room=True)['request_sent_to_team'])
            self.assertEqual(len(self.requests_()), PER_GUEST)

        def test_checker_probe_party_size_correction_at_the_per_chat_limit(self):
            c = self.over_cap_chat()
            self.fill_to_the_guest_limit(c)
            out = self.book_as(c, 2, guests=2)                     # "2 người chứ không phải 1" — không another_room
            self.assertTrue(out['request_sent_to_team'])
            self.assertNotIn('booking_id', out)
            reqs = self.requests_()
            self.assertEqual(len(reqs), PER_GUEST)                 # không thêm dòng ...
            self.assertEqual(sorted(r['party_size'] for r in reqs), [1] * (PER_GUEST - 1) + [2])   # ... đúng số khách mới
            [changed] = [r for r in reqs if r['party_size'] == 2]
            self.assertEqual(changed.get('party_size_was'), 1)
            self.assertEqual(hp.OWNER_ALERTS[-1][3], 'hotel_webcap_change')
            self.assertIn('1 → 2', hp.STAFF_NOTES[-1][2])
            self.assertIn(f"#{changed['id']}", hp.STAFF_NOTES[-1][2])

        def test_checker_probe_identical_repeat_at_the_limit_is_not_a_group_booking(self):
            c = self.over_cap_chat()
            self.fill_to_the_guest_limit(c)
            notes = len(hp.STAFF_NOTES)
            out = self.book_as(c, 2, guests=1)                     # khách hỏi lại đúng phòng đó
            self.assertTrue(out['request_sent_to_team'])
            self.assertNotIn('group booking', json.dumps(out))
            self.assertEqual(len(self.requests_()), PER_GUEST)
            self.assertEqual(len(hp.STAFF_NOTES), notes)           # không báo thêm

        def test_more_rooms_at_the_limit_are_still_refused(self):
            c = self.over_cap_chat()
            self.fill_to_the_guest_limit(c)
            for kw in ({'another_room': True}, {'checkin_date': D(12), 'checkout_date': D(14)}, {'guest_name': 'Someone Else'}):
                with self.assertRaises(PackError) as cm:
                    self.book_as(c, 2, guests=1, **kw)
                self.assertIn('group booking', str(cm.exception))
            self.assertEqual(len(self.requests_()), PER_GUEST)
            # trình duyệt khác gõ cùng SĐT (cùng hội thoại), khác số khách: không sửa được yêu cầu của chat kia -> vẫn qua giới hạn
            with self.assertRaises(PackError):
                self.book_as(dict(c, chat_token_hash='tok-someone-else'), 2, guests=2)
            self.assertEqual(sorted(r['party_size'] for r in self.requests_()), [1] * PER_GUEST)

        def test_party_size_correction_at_the_per_network_limit(self):
            self.assertIn('booking_id', self.book_as(web(1), 1))   # chat 1 giữ suất web duy nhất -> các chat sau vượt trần
            chats = []
            for n in range(2, 2 + PER_NETWORK):
                c = dict(web(n), client_key='net:shared')
                DB.bot_customers.update_one({'id': c['customer_id']}, {'$set': {'business_id': hp.BID}}, upsert=True)
                self.assertTrue(self.book_as(c, n, guests=1)['request_sent_to_team'])
                chats.append(c)
            self.assertEqual(len(self.requests_()), PER_NETWORK)
            out = self.book_as(chats[0], 2, guests=2)              # sửa số khách của yêu cầu đang chờ
            self.assertTrue(out['request_sent_to_team'])
            self.assertEqual(sorted(r['party_size'] for r in self.requests_()), [1] * (PER_NETWORK - 1) + [2])
            with self.assertRaises(PackError) as cm:               # phòng MỚI từ cùng mạng: vẫn bị chặn
                self.book_as(chats[0], 2, guests=1, another_room=True)
            self.assertIn('same connection', str(cm.exception))

        def test_correction_after_the_cap_frees_does_not_add_a_second_room(self):
            hold = self.book_as(web(1), 1)
            c = web(2)
            DB.bot_customers.update_one({'id': c['customer_id']}, {'$set': {'business_id': hp.BID}}, upsert=True)
            self.assertTrue(self.book_as(c, 2, guests=1)['request_sent_to_team'])
            [req] = self.requests_()
            r = run('hotel_cancel_booking', {'booking_id': hold['booking_id'], 'customer_confirmed': True}, web(1))
            self.assertTrue(r['cancelled'])                        # trần giữ phòng web nhả ra
            out = self.book_as(c, 2, guests=2)                     # lời sửa số khách tới SAU khi trần nhả
            self.assertTrue(out['request_sent_to_team'])
            self.assertNotIn('booking_id', out)
            self.assertEqual([x for x in self.live_ai() if x.get('ai_conversation_id') == c['customer_id']], [])
            [req2] = self.requests_()
            self.assertEqual((req2['id'], req2['party_size']), (req['id'], 2))   # 1 khách = 1 yêu cầu, đúng số khách
            # khách THỰC SỰ xin thêm 1 phòng lúc trần đã nhả: vẫn giữ được phòng thật (luồng thường không bị chặn)
            more = self.book_as(c, 2, guests=2, another_room=True)
            self.assertIn('booking_id', more)
            self.assertNoDoubleBooking()

        def test_match_only_never_writes(self):
            kw = dict(checkin=D(8), checkout=D(10), room_type='Standard', guest_name='Guest Number2', guest_phone='0499999902',
                      extra={'ai_conversation_id': 'conv-2', 'chat_token_hash': 'tok-2', 'source': 'ai_bot'})
            self.assertEqual(rh.create_staff_request(hp.BID, guests=2, match_only=True, **kw), (None, None))
            self.assertEqual(self.requests_(), [])
            a, _s = rh.create_staff_request(hp.BID, guests=2, **kw)
            self.assertEqual(rh.create_staff_request(hp.BID, guests=2, match_only=True, **kw)[1], 'duplicate')
            row, state = rh.create_staff_request(hp.BID, guests=3, match_only=True, **kw)
            self.assertEqual((row['id'], state), (a['id'], 'updated'))
            self.assertEqual(find(a['id'])['party_size'], 2)       # dò thôi: không sửa
            other = dict(kw, extra=dict(kw['extra'], chat_token_hash='tok-other'))
            self.assertEqual(rh.create_staff_request(hp.BID, guests=3, match_only=True, **other), (None, None))
            self.assertEqual(rh.create_staff_request(hp.BID, guests=2, another_room=True, match_only=True, **kw), (None, None))
            self.assertEqual(len(self.requests_()), 1)


def _run_groups():
    rc = 0
    for g in ('core', 'hotel'):
        print(f'===== P2R_GROUP={g}', flush=True)
        rc |= subprocess.run([sys.executable, os.path.abspath(__file__)] + sys.argv[1:],
                             env=dict(os.environ, P2R_GROUP=g)).returncode
    return rc


if __name__ == '__main__':
    if not GROUP:
        sys.exit(_run_groups())
    unittest.main(verbosity=2)
