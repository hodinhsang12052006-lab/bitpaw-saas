# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2, khu "requests" (ai_packs/technical.py, ai_packs/retail.py, production.py,
office.py, retail_holds_bp.py):
  1. KHẨN CẤP không bao giờ bị chống trùng nuốt mất: việc cũ cùng khách + địa chỉ + ngày được nâng lên khẩn cấp, cuộc chat
     chuyển người thật, chủ tiệm được báo, khách được dặn ra chỗ an toàn + gọi số khẩn cấp.
  2. Từ khoá nguy hiểm bị PHỦ ĐỊNH ('no gas smell', 'không có mùi khét', 'không bị điện giật') không bật khẩn cấp.
  3. held_qty đúng tuyệt đối khi 2 lệnh chạy cùng lúc: _recount_held không đặt lại giữa _reserve và insert, hay giữa
     lệnh đổi trạng thái và _release.
  4. Tiệm chưa nhập nước: SĐT giữ nguyên số khách gõ, không bịa +1; số Mỹ sai (mã vùng 0/1) không thành +1.
  5. API đổi trạng thái báo giá / tư vấn chỉ đi đúng luật chuyển; trang cũ bấm sau -> 409, không đè.

Dùng lại DB giả + stub của test_phase2_request_packs.py (nạp TRƯỚC mọi gói): không import app.py thật, không MongoDB
thật, không gọi mạng. Chạy: python scripts/tests/test_phase2_requests_fixes.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_request_packs as base  # noqa: E402  (cài mongo_client / app / ai_function_tools giả)

from test_phase2_request_packs import (AU, CALLS, DB, NOW, NY_NOW, OFFICE, PROD, TECH, US_SHOP, VN, PackError,  # noqa: E402
                                       consult, ctx, hold, job, product, quote, retail, seed, technical)
from ai_packs import office, production  # noqa: E402

NC_RETAIL, NC_TECH, NC_PROD, NC_OFFICE, TECH_VN = 'nc_retail', 'nc_tech', 'nc_prod', 'nc_office', 'tech_vn'


def seed_more():
    """Tiệm tự đăng ký (app.py signup): KHÔNG có country / currency. Thêm 1 tiệm kỹ thuật ở Việt Nam."""
    for bid, ind in ((NC_RETAIL, 'retail'), (NC_TECH, 'technical'), (NC_PROD, 'production'), (NC_OFFICE, 'office')):
        DB.businesses.insert_one({'id': bid, 'name': f'Shop {bid}', 'industry_code': ind})
    DB.businesses.insert_one({'id': TECH_VN, 'name': 'Điện lạnh Sài Gòn', 'currency': 'VND', 'country': 'VN',
                              'industry_code': 'technical'})
    DB.products.insert_one({'id': 71, 'business_id': NC_RETAIL, 'name': 'Bánh mì', 'category': 'Bakery', 'price': 20000,
                            'stock': 5, 'channel_type': 'retail', 'is_active': 1})


def alerts():
    return [c for c in CALLS if c[0] == 'alert']


# ================================================================ 1. khẩn cấp + chống trùng
class EmergencyNeverDedupedTests(unittest.TestCase):
    def setUp(self):
        seed()
        seed_more()
        self.cid = f'{TECH}:0412345678'
        DB.bot_customers.insert_one({'id': self.cid})

    def test_emergency_after_a_normal_request_escalates_the_same_job(self):
        first = job(customer_id=self.cid)                                  # 'Air-con leaking water inside' -> bình thường
        self.assertEqual(first['urgency'], 'normal')
        CALLS.clear()
        out = job(customer_id=self.cid, args={'problem': 'Now there are sparks and a burning smell from the unit'})
        self.assertEqual(out['job_id'], first['job_id'])
        self.assertTrue(out['already_requested'])
        self.assertTrue(out['escalated'])
        self.assertEqual(out['urgency'], 'emergency')
        self.assertIn('000', out['tell_customer'])                          # số khẩn cấp ở Úc
        self.assertIn('somewhere safe', out['tell_customer'])
        self.assertIn(f"job #{first['job_id']}", out['tell_customer'])
        self.assertEqual(len(DB.tasks.docs), 1)                             # vẫn 1 việc trên bảng
        t = DB.tasks.find_one({'id': first['job_id']})
        self.assertEqual(t['urgency'], 'emergency')
        self.assertIn('Urgency: EMERGENCY', t['noi_dung'])                  # bảng điều phối đọc noi_dung
        self.assertNotIn('Urgency: normal', t['noi_dung'])
        self.assertIn('sparks and a burning smell', t['noi_dung'])
        bc = DB.bot_customers.find_one({'id': self.cid})
        self.assertTrue(bc['needs_human'] and bc['handoff_urgent'] and bc['ai_paused'])
        self.assertIn(f"#{first['job_id']}", bc['handoff_reason'])
        al = alerts()
        self.assertEqual([a[4] for a in al], ['technical_emergency'])
        self.assertIn(f"#{first['job_id']}", al[0][3])
        self.assertIn('EMERGENCY', al[0][3])

    def test_repeating_the_emergency_still_hands_off_without_a_second_job_or_alert(self):
        job(customer_id=self.cid, args={'problem': 'I can smell gas near the heater'})
        DB.bot_customers.update_one({'id': self.cid}, {'$set': {'ai_paused': False, 'needs_human': False, 'handoff_urgent': False}})
        CALLS.clear()
        again = job(customer_id=self.cid, args={'problem': 'Gas smell is getting stronger'})
        self.assertTrue(again['already_requested'])
        self.assertFalse(again['escalated'])                                # đã khẩn cấp từ trước
        self.assertEqual(again['urgency'], 'emergency')
        self.assertIn('000', again['tell_customer'])
        bc = DB.bot_customers.find_one({'id': self.cid})
        self.assertTrue(bc['needs_human'] and bc['handoff_urgent'] and bc['ai_paused'])
        self.assertEqual(alerts(), [])                                      # chủ đã được báo khẩn cấp cho việc này
        self.assertEqual(len(DB.tasks.docs), 1)

    def test_vi_shop_ai_marked_emergency_without_keyword(self):
        cid = f'{TECH_VN}:0901234567'
        first = technical.execute('technical_request_job', {'customer_name': 'Anh Nam', 'phone': '0901 234 567',
                                                            'address': '5 Lê Lợi, Quận 1, TP HCM', 'problem': 'Máy lạnh kêu to'},
                                  ctx(TECH_VN, customer_id=cid, lang='vi'))
        self.assertEqual(first['urgency'], 'normal')
        out = technical.execute('technical_request_job', {'customer_name': 'Anh Nam', 'phone': '0901 234 567',
                                                          'address': '5 Lê Lợi, Quận 1, TP HCM', 'urgency': 'emergency',
                                                          'problem': 'Bình nóng lạnh nổ lớn, nước phun ra'},
                                ctx(TECH_VN, customer_id=cid, lang='vi'))
        self.assertEqual((out['job_id'], out['urgency'], out['escalated']), (first['job_id'], 'emergency', True))
        self.assertIn('114', out['tell_customer'])
        self.assertIn('ra chỗ an toàn', out['tell_customer'])
        t = DB.tasks.find_one({'id': first['job_id']})
        self.assertIn('Mức độ: KHẨN CẤP', t['noi_dung'])
        self.assertNotIn('Mức độ: bình thường', t['noi_dung'])
        self.assertIn('KHẨN CẤP, khách báo thêm qua chat AI: Bình nóng lạnh nổ lớn', t['noi_dung'])
        self.assertIn('KHẨN CẤP — việc #', [c for c in CALLS if c[0] == 'note'][-1][3])   # ghi chú nhân viên tiếng Việt

    def test_emergency_after_a_completed_job_is_a_new_urgent_job(self):
        first = job(customer_id=self.cid)
        DB.tasks.update_one({'id': first['job_id']}, {'$set': {'trang_thai': technical.DONE}})
        CALLS.clear()
        out = job(customer_id=self.cid, args={'problem': 'Burst pipe under the sink, water everywhere'})
        self.assertNotEqual(out['job_id'], first['job_id'])
        self.assertNotIn('already_requested', out)
        t = DB.tasks.find_one({'id': out['job_id']})
        self.assertEqual((t['urgency'], t['trang_thai']), ('emergency', technical.WAITING))
        self.assertEqual([a[4] for a in alerts()], ['technical_emergency'])
        again = job(customer_id=self.cid, args={'problem': 'Burst pipe still spraying'})
        self.assertEqual(again['job_id'], out['job_id'])                    # báo lại: không thêm việc thứ 3
        self.assertIn('000', again['tell_customer'])
        self.assertEqual(len(DB.tasks.docs), 2)

    def test_normal_duplicate_is_unchanged(self):
        first = job(customer_id=self.cid)
        CALLS.clear()
        again = job(customer_id=self.cid, args={'problem': 'Air-con still leaking'})
        self.assertTrue(again['already_requested'])
        self.assertEqual(again['job_id'], first['job_id'])
        self.assertNotIn('tell_customer', again)
        self.assertEqual(alerts(), [])
        self.assertEqual(DB.tasks.find_one({'id': first['job_id']})['urgency'], 'normal')


# ================================================================ 2. phủ định
class EmergencyNegationTests(unittest.TestCase):
    def setUp(self):
        seed()
        seed_more()

    def test_negated_danger_words_are_not_emergencies(self):
        for txt in ('Aircon not cooling. No burning smell or sparks.', 'Máy lạnh không lạnh, không có mùi khét',
                    'no gas smell', 'not sparking, just dead', 'Không có khói', 'không bị giật', 'không bị điện giật',
                    "I don't smell gas", 'I don\u2019t smell gas', 'There are no signs of a gas leak',
                    'không có mùi gas hay tia lửa gì', 'khong co mui khet', 'No flooding, no sparks',
                    'Fridge not cooling - no smoke coming out', 'không thấy chập điện', 'Nhà không bị ngập nước',
                    'Heater has not been sparking', 'no longer flooding'):
            with self.subTest(txt=txt):
                self.assertFalse(technical.is_emergency(txt), txt)

    def test_real_danger_is_still_caught(self):
        for txt in ('Aircon not cooling, burning smell from the unit', 'No power and sparks from the outlet',
                    'The heater does not turn on, sparks coming out', 'không có mùi gas nhưng có mùi khét',
                    'Máy không chạy có mùi khét', 'no hot water and water everywhere', 'not sure if it is a gas leak',
                    'Aircon not cooling burning smell', 'No burning smell. Sparks now.', 'Không lạnh. Có khói bốc ra',
                    'burst pipe in the laundry', 'sparks from the power point', 'chập điện ở ổ cắm',
                    'No gas smell there is smoke coming out', 'không có điện, bị điện giật khi chạm vào'):
            with self.subTest(txt=txt):
                self.assertTrue(technical.is_emergency(txt), txt)

    def test_screening_answer_keeps_a_normal_job_normal(self):
        cid = f'{TECH}:0412345678'
        DB.bot_customers.insert_one({'id': cid})
        out = job(customer_id=cid, args={'problem': 'Aircon not cooling. No burning smell or sparks.'})
        self.assertEqual(out['urgency'], 'normal')
        self.assertNotIn('000', out['tell_customer'])
        self.assertEqual([a[4] for a in alerts()], ['technical_job'])
        self.assertIsNone(DB.bot_customers.find_one({'id': cid}).get('needs_human'))
        vi = technical.execute('technical_request_job', {'customer_name': 'Chị Lan', 'phone': '0901 234 567',
                                                         'address': '9 Nguyễn Huệ, Quận 1, TP HCM',
                                                         'problem': 'Máy lạnh không lạnh, không có mùi khét'},
                               ctx(TECH_VN, lang='vi'))
        self.assertEqual(vi['urgency'], 'normal')
        self.assertIn('Mức độ: bình thường', DB.tasks.find_one({'id': vi['job_id']})['noi_dung'])


# ================================================================ 3. held_qty khi chạy cùng lúc
class HeldQtyConcurrencyTests(unittest.TestCase):
    def setUp(self):
        seed()

    def _active(self, pid):
        return DB.retail_holds.find({'business_id': AU, 'product_id': pid, 'status': {'$in': list(retail.ACTIVE)}})

    def test_last_unit_is_never_held_twice_when_a_recount_runs_mid_hold(self):
        DB.products.update_one({'id': 2, 'business_id': AU}, {'$set': {'stock': 1}})
        coll, real_insert, other = DB.retail_holds, DB.retail_holds.insert_one, {}

        def racing_insert(doc):
            # khách A đã cộng held_qty nhưng chưa ghi dòng hold: đúng lúc đó khách B giữ cùng món cuối cùng
            if 'b' not in other:
                other['b'] = 'running'
                try:
                    other['b'] = hold(args={'product_id': 2, 'quantity': 1, 'phone': '0412 000 111', 'customer_name': 'Ben'},
                                      chat_token_hash='tokB')
                except PackError as e:
                    other['b'] = e
            return real_insert(doc)
        coll.insert_one = racing_insert
        try:
            a = hold(args={'product_id': 2, 'quantity': 1}, chat_token_hash='tokA')
        finally:
            del coll.insert_one
        self.assertTrue(a['success'])
        self.assertIsInstance(other['b'], PackError, other['b'])
        self.assertIn('out of stock', str(other['b']))
        self.assertEqual(len(self._active(2)), 1)
        self.assertEqual(product(2)['held_qty'], 1)

    def test_recount_between_status_change_and_release_does_not_release_twice(self):
        hold(args={'product_id': 1, 'quantity': 2}, chat_token_hash='tokA')
        b = hold(args={'product_id': 1, 'quantity': 1, 'phone': '0412 000 111', 'customer_name': 'Ben'}, chat_token_hash='tokB',
                 customer_id=f'{AU}:0412000111')                           # chat web thật: mã trình duyệt + đúng chat này
        self.assertEqual(product(1)['held_qty'], 3)
        # bộ đếm "cũ" (đứng yên lâu) -> nếu không có dấu "đang đổi", recount được phép sửa
        DB.products.update_one({'id': 1, 'business_id': AU}, {'$set': {'held_qty_at': time.time() - 3600}})
        real_release = retail._release

        def racing_release(bid, h):
            retail._recount_held(bid, h.get('product_id'))      # 1 khách khác giữ hụt -> recount chạy đúng lúc này
            return real_release(bid, h)
        retail._release = racing_release
        try:
            out = retail.execute('retail_cancel_hold', {'hold_id': b['hold_id']},
                                 ctx(chat_token_hash='tokB', customer_id=f'{AU}:0412000111'))
        finally:
            retail._release = real_release
        self.assertEqual(out['status'], 'cancelled')
        self.assertEqual(product(1)['held_qty'], 2)                          # = hold 2 cái còn giữ, không phải 1
        self.assertEqual(sum(h['quantity'] for h in self._active(1)), 2)

    def test_staff_transition_is_protected_too(self):
        a = hold(args={'product_id': 1, 'quantity': 2}, chat_token_hash='tokA')
        hold(args={'product_id': 1, 'quantity': 1, 'phone': '0412 000 111', 'customer_name': 'Ben'}, chat_token_hash='tokB')
        DB.products.update_one({'id': 1, 'business_id': AU}, {'$set': {'held_qty_at': time.time() - 3600}})
        real_release = retail._release
        retail._release = lambda bid, h: (retail._recount_held(bid, h.get('product_id')), real_release(bid, h))[1]
        try:
            h, err = retail.staff_set_status(AU, a['hold_id'], 'picked_up', by='staff:1')
        finally:
            retail._release = real_release
        self.assertEqual((h['status'], err), ('picked_up', None))
        self.assertEqual(product(1)['held_qty'], 1)

    def test_drift_is_repaired_only_once_the_counter_is_quiet(self):
        DB.products.update_one({'id': 2, 'business_id': AU}, {'$set': {'held_qty': 3, 'held_qty_at': time.time()}})
        self.assertFalse(retail._recount_held(AU, 2))                       # vừa đổi: có thể lệnh khác đang chạy dở
        self.assertEqual(product(2)['held_qty'], 3)
        DB.products.update_one({'id': 2, 'business_id': AU}, {'$set': {'held_qty_at': time.time() - retail.HELD_GRACE_SECONDS - 5}})
        self.assertTrue(hold(args={'product_id': 2, 'quantity': 3})['success'])   # lệch thật (tiến trình chết) -> sửa rồi giữ
        self.assertEqual(product(2)['held_qty'], 3)

    def test_every_counter_change_stamps_the_product(self):
        t0 = time.time()
        a = hold(chat_token_hash='tokA', customer_id=f'{AU}:0412345678')
        self.assertGreaterEqual(product(1)['held_qty_at'], t0)
        DB.products.update_one({'id': 1, 'business_id': AU}, {'$set': {'held_qty_at': 0}})
        retail.execute('retail_cancel_hold', {'hold_id': a['hold_id']}, ctx(chat_token_hash='tokA', customer_id=f'{AU}:0412345678'))
        self.assertGreaterEqual(product(1)['held_qty_at'], t0)
        self.assertEqual(product(1)['held_qty'], 0)


# ================================================================ 4. SĐT khi tiệm chưa nhập nước
class UnknownCountryPhoneTests(unittest.TestCase):
    def setUp(self):
        seed()
        seed_more()

    def test_phone_key_never_guesses_us(self):
        self.assertIsNone(retail.phone_key('0912 345 678', None))
        self.assertIsNone(retail.phone_key('0912 345 678', ''))
        self.assertIsNone(retail.phone_key('0412345678'))
        self.assertEqual(retail.phone_key('+84 912 345 678', None), '+84912345678')
        self.assertEqual(retail.phone_key('0084912345678', None), '+84912345678')
        self.assertIsNone(retail.phone_key('0412 345 678', 'US'))           # mã vùng Mỹ không bắt đầu bằng 0
        self.assertIsNone(retail.phone_key('1412345678', 'CA'))
        self.assertEqual(retail.phone_key('(312) 345-6789', 'US'), '+13123456789')
        self.assertEqual(retail.phone_key('0912 345 678', 'VN'), '+84912345678')
        self.assertEqual(retail._e164_local('0912345678', None), '')

    def test_hold_keeps_the_typed_number(self):
        out = retail.execute('retail_hold_for_pickup', {'product_id': 71, 'quantity': 1, 'customer_name': 'Lan',
                                                        'phone': '0912 345 678'},
                             ctx(NC_RETAIL, chat_token_hash='tokN', customer_id=f'{NC_RETAIL}:0912 345 678'))
        self.assertTrue(out['success'])
        h = DB.retail_holds.find_one({'id': out['hold_id']})
        self.assertEqual(h['customer_phone'], '0912345678')
        self.assertIsNone(h['phone_key'])
        self.assertNotIn('+1', str(h))
        self.assertNotIn('+10912345678', str(CALLS))
        self.assertIn('0912345678', alerts()[-1][3])
        mine = retail.execute('retail_my_holds', {}, ctx(NC_RETAIL, chat_token_hash='tokN',
                                                         customer_id=f'{NC_RETAIL}:0912 345 678'))['holds']   # mã trình duyệt + đúng chat
        with self.assertRaises(PackError):                                  # mã trình duyệt MỘT MÌNH không phải bằng chứng
            retail.execute('retail_my_holds', {}, ctx(NC_RETAIL, chat_token_hash='tokN'))
        self.assertEqual([x['hold_id'] for x in mine], [out['hold_id']])
        # cùng SĐT ở trình duyệt khác: giới hạn hold / khách vẫn tính theo số khách gõ (khoá E.164 = None)
        args = {'product_id': 71, 'quantity': 1, 'customer_name': 'Lan', 'phone': '0912345678'}
        for tok in ('tokX0', 'tokX1'):
            retail.execute('retail_hold_for_pickup', args, ctx(NC_RETAIL, chat_token_hash=tok))
        with self.assertRaises(PackError) as e:
            retail.execute('retail_hold_for_pickup', args, ctx(NC_RETAIL, chat_token_hash='tokX2'))
        self.assertIn(f'maximum of {retail.MAX_ACTIVE_HOLDS}', str(e.exception))

    def test_job_quote_and_consult_keep_the_typed_number(self):
        j = technical.execute('technical_request_job', {'customer_name': 'Tom', 'phone': '0412 345 678',
                                                        'address': '12 King St, Newtown', 'problem': 'Heater not working'},
                              ctx(NC_TECH))
        self.assertEqual(DB.tasks.find_one({'id': j['job_id']})['sdt'], '0412345678')
        q = production.execute('production_request_quote', {'product': 'Áo thun in logo', 'quantity': 100,
                                                            'customer_name': 'Chị Hạnh', 'phone': '0901 234 567'},
                               ctx(NC_PROD, lang='vi'))
        self.assertEqual(DB.quote_requests.find_one({'id': q['quote_request_id']})['customer_phone'], '0901234567')
        self.assertIn('0901234567', q['tell_customer'])
        c = office.execute('office_request_consultation', {'topic': 'Set up a small company', 'customer_name': 'Ana',
                                                           'phone': '0901 234 567'}, ctx(NC_OFFICE, now_local=NY_NOW))
        self.assertEqual(DB.consultation_requests.find_one({'id': c['consult_request_id']})['customer_phone'], '0901234567')
        self.assertNotIn('+1', c['tell_customer'])

    def test_shop_country_is_used_when_the_chat_context_has_none(self):
        out = retail.execute('retail_hold_for_pickup', {'product_id': 21, 'quantity': 1, 'customer_name': 'Lan',
                                                        'phone': '0901 234 567'}, ctx(VN, country=None))
        self.assertEqual(DB.retail_holds.find_one({'id': out['hold_id']})['customer_phone'], '+84901234567')

    def test_us_shop_does_not_turn_a_foreign_local_number_into_plus_one(self):
        out = retail.execute('retail_hold_for_pickup', {'product_id': 31, 'quantity': 1, 'customer_name': 'Mia',
                                                        'phone': '0412 345 678'}, ctx(US_SHOP, chat_token_hash='tokUS'))
        h = DB.retail_holds.find_one({'id': out['hold_id']})
        self.assertEqual((h['customer_phone'], h['phone_key']), ('0412345678', None))

    def test_dedupe_without_a_conversation_is_still_per_phone(self):
        args = {'customer_name': 'Tom', 'address': '12 King St, Newtown', 'problem': 'Heater not working'}
        a = technical.execute('technical_request_job', {**args, 'phone': '0412 345 678'}, ctx(NC_TECH))
        b = technical.execute('technical_request_job', {**args, 'phone': '0412 999 888', 'customer_name': 'Sue'}, ctx(NC_TECH))
        c = technical.execute('technical_request_job', {**args, 'phone': '0412345678'}, ctx(NC_TECH))
        self.assertNotEqual(a['job_id'], b['job_id'])                         # 2 khách khác nhau -> 2 việc
        self.assertEqual(c['job_id'], a['job_id'])                            # cùng số gõ lại -> chống trùng
        self.assertTrue(c['already_requested'])


# ================================================================ 5. luật chuyển trạng thái báo giá / tư vấn
class RequestStatusTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from jinja2 import ChoiceLoader, DictLoader
        import retail_holds_bp as bp
        cls.bp = bp
        app = Flask(__name__, static_folder=os.path.join(base.ROOT, 'static'))
        app.secret_key = 'test'
        app.jinja_loader = ChoiceLoader([DictLoader({'components/app_sidebar.html': '<nav>sidebar</nav>'}), app.jinja_loader])
        app.register_blueprint(bp.retail_holds_bp)
        cls.app = app

    def setUp(self):
        seed()
        self.c = self.app.test_client()

    def login(self, bid, mode, role='staff'):
        with self.c.session_transaction() as s:
            s.update({'user_id': f'u_{bid}', 'business_id': bid, 'business_mode': mode, 'role': role})

    def post(self, kind, rid, status):
        return self.c.post(f'/api/requests/{kind}/{rid}/status', json={'status': status})

    def test_stale_page_cannot_bring_back_a_cancelled_consultation(self):
        rid = consult()['consult_request_id']
        self.login(OFFICE, 'office')
        self.assertEqual(self.post('consultations', rid, 'cancelled').status_code, 200)
        r = self.post('consultations', rid, 'confirmed')                      # trang cũ còn nút "Đã gọi, chốt giờ"
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()['current_status'], 'cancelled')
        self.assertIn('Cancelled', r.get_json()['message'])
        self.assertEqual(DB.consultation_requests.find_one({'id': rid})['status'], 'cancelled')
        self.assertEqual(self.c.get('/api/requests/consultations').get_json()['items'], [])   # không quay lại danh sách mở
        self.c.set_cookie('bitpaw_lang', 'vi')
        self.assertIn('Đã huỷ', self.post('consultations', rid, 'done').get_json()['message'])

    def test_consultation_path_and_no_jump_back(self):
        rid = consult()['consult_request_id']
        self.login(OFFICE, 'office')
        self.assertEqual(self.post('consultations', rid, 'done').status_code, 409)       # chưa chốt giờ thì chưa "đã tư vấn"
        self.assertEqual(self.post('consultations', rid, 'confirmed').status_code, 200)
        self.assertEqual(self.post('consultations', rid, 'confirmed').status_code, 409)  # bấm 2 lần
        self.assertEqual(self.post('consultations', rid, 'declined').status_code, 409)
        self.assertEqual(self.post('consultations', rid, 'done').status_code, 200)
        self.assertEqual(self.post('consultations', rid, 'pending').status_code, 409)    # done -> pending không được
        self.assertEqual(DB.consultation_requests.find_one({'id': rid})['status'], 'done')
        self.assertEqual(self.post('consultations', 4040, 'confirmed').status_code, 404)
        self.assertEqual(self.post('consultations', rid, 'paid').status_code, 400)

    def test_quote_transitions_follow_the_page_buttons(self):
        rid = quote(customer_id=f'{PROD}:0901234567')['quote_request_id']
        self.login(PROD, 'production', 'admin')
        self.assertEqual(self.post('quotes', rid, 'won').status_code, 409)               # new -> won không có nút
        for st in ('contacted', 'quoted', 'won', 'quoted', 'lost', 'new', 'quoted'):      # gồm 2 nút "Mở lại"
            with self.subTest(st=st):
                r = self.post('quotes', rid, st)
                self.assertEqual(r.status_code, 200, r.get_json())
                self.assertEqual(DB.quote_requests.find_one({'id': rid})['status'], st)
        self.assertEqual(self.post('quotes', rid, 'contacted').status_code, 409)         # quoted -> contacted không có nút
        self.assertEqual(self.post('quotes', 777, 'won').status_code, 404)

    def test_server_rules_match_the_page_buttons(self):
        for kind in ('quotes', 'consultations'):
            for lang in ('vi', 'en'):
                with self.subTest(kind=kind, lang=lang):
                    acts = self.bp.PAGE_TEXT[kind][lang]['actions']
                    self.assertEqual({st: tuple(a[0] for a in lst) for st, lst in acts.items()}, self.bp.KINDS[kind]['next'])
                    for nxt in self.bp.KINDS[kind]['next'].values():
                        self.assertTrue(set(nxt) <= set(self.bp.KINDS[kind]['set']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
