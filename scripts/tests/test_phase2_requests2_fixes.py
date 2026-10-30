# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 vòng 2, khu "requests2" (ai_packs/technical.py):
  1. Lưới an toàn khẩn cấp AN TOÀN TRƯỚC: chỉ coi từ khoá nguy hiểm là bị phủ định khi có từ phủ định RÕ đứng ngay trước
     ("no gas smell", "not sparking", "without smoke", "không có mùi khét", "không bị giật", "hết mùi gas"). "never seen
     sparks like this", "didn't notice the burning smell until now", "I can smell gas", "smells like burning", "is it
     dangerous if there is smoke?" vẫn là KHẨN CẤP (bỏ sót nguy hiểm là chết người, báo nhầm chỉ phiền).
  2. Việc khẩn cấp hôm nay ĐÃ XONG mà khách báo nguy hiểm lần nữa: tạo việc MỚI đang Chờ Nhận + báo chủ, không trả về việc
     đã Hoàn Thành; khách báo lại thì vẫn chỉ 1 việc đang mở.

Dùng lại DB giả + stub của test_phase2_request_packs.py (nạp TRƯỚC mọi gói): không import app.py thật, không MongoDB
thật, không gọi mạng. Chạy: python scripts/tests/test_phase2_requests2_fixes.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_request_packs as base  # noqa: E402,F401  (cài mongo_client / app / ai_function_tools giả)

from test_phase2_request_packs import CALLS, DB, TECH, ctx, job, seed, technical  # noqa: E402

# ---------------------------------------------------------------- bảng câu: phải là KHẨN CẤP
DANGER = (
    # 4 câu checker đo được là bị bỏ sót (never / động từ giác quan quá khứ)
    "I've never seen sparks like this",
    'never seen smoke coming out like that',
    "I didn't notice the burning smell until now",
    "didn't see the sparks at first",
    # không có phủ định
    'I can smell gas in the kitchen',
    'It smells like burning',
    'Smells like something burning near the switchboard',
    'Is it dangerous if there is smoke?',
    'What should I do if I smell gas?',
    'The outlet sparked when I plugged in the kettle',
    'I got a shock from the oven door',
    'The water heater exploded',
    'Flames coming out of the heater',
    # phủ định nhưng nói về lúc trước / điều kiện / câu hỏi an toàn / bị lật lại
    'There was no burning smell before but now there is',
    'There was no gas smell, but now there is.',
    'At first there was no smoke, then it started pouring out',
    "I haven't seen sparks like this before",
    'No smoke until I switched it on',
    "No burning smell when it's off",
    'Is it safe to stay inside if there is no gas smell?',
    # từ phủ định KHÔNG trực tiếp chi phối từ khoá (đoán, thiếu dấu phẩy...)
    "not sure if it's sparking",
    'no i can smell gas',
    'no there is smoke coming out',
    'no the gas smell is really strong',
    "I don't think it's a gas leak",
    "It doesn't seem to be sparking",
    'almost no smoke now',
    # danh sách không phải danh sách từ khoá thuần / không đóng bằng "or" / là câu hỏi
    'No power, sparks or smoke from the board',
    'No gas smell, sparks.',
    "There's no gas smell, sparks or smoke?",
    'the smoke alarm went off and there is smoke',
    # tiếng Việt
    'Chưa bao giờ thấy tia lửa như vầy',
    'Lúc đầu không có mùi khét',
    'Không để ý mùi khét cho đến giờ',
    'Có khói thì có nguy hiểm không?',
    'Không có mùi gas thì có nguy hiểm không?',
    'Nếu không có khói thì có sao không',
    'Trước giờ chưa thấy chập điện như vậy',
    'Không có mùi khét nhưng giờ thì có rồi',
    'Hông có mùi khét lúc đầu, giờ khét lẹt',
    'Tủ lạnh bị rò điện, chạm vào tê tay',
    'Bình nóng lạnh phát nổ',
    'Nghe mùi ga trong bếp',
    'Máy lạnh xì khói đen',
    'khong biet co ro ri gas khong',
    'Ổ cắm có mùi khét',
    'không có điện, bị điện giật khi chạm vào',
    'Khói từ ổ cắm',
    # phủ định kép / "gần như" / 'hết' nghĩa "toàn bộ"
    'Vẫn chưa hết mùi gas',
    'không hết mùi khét',
    'Sắp hết mùi khét',
    'Nước tràn hết ngập nhà',
    'không phải không có khói',
)

# ---------------------------------------------------------------- bảng câu: phủ định RÕ -> KHÔNG khẩn cấp
NEGATED = (
    'no gas smell',
    'not sparking',
    'without smoke',
    'Aircon not cooling. No burning smell or sparks.',
    "I don't smell gas",
    'I do not smell gas',
    'There is no smoke coming out',
    "No sparks, no smoke, just won't turn on",
    "It doesn't smell like burning",
    "Haven't seen any sparks",
    "I can't see any smoke",
    "I don't see any sparks or smoke",
    'no longer flooding',
    'There are no signs of a gas leak',
    'Heater has not been sparking',
    'Neither smoke nor sparks',
    'Fridge stopped working - no smoke or burning smell',
    "It isn't sparking any more",
    'No flooding, no sparks',
    'Smoke alarm keeps beeping, battery low',
    'Smoke detector chirping every minute, needs new battery',
    'Aircon not cooling, making a loud noise. No gas smell, sparks or smoke.',
    'Not sparking, smoking, or flooding.',
    # tiếng Việt
    'không có mùi khét',
    'không bị giật',
    'hết mùi gas',
    'Đã hết mùi gas rồi',
    'không bị điện giật',
    'Không có khói',
    'không thấy tia lửa',
    'không còn mùi gas',
    'ko có mùi khét gì hết',
    'Máy lạnh không lạnh, không có mùi khét hay tia lửa',
    'không hề có khói',
    'khong co mui gas',
    'Nhà không bị ngập nước',
    'không thấy khói bốc ra',
    'Đèn không chập điện, chỉ không sáng',
    'chưa thấy có khói',
    'Không ngửi thấy mùi gas',
    'không có dấu hiệu rò gas',
    'máy hút khói không hút được',
    'Đầu báo khói kêu liên tục',
    'không có mùi gas, tia lửa hay khói',
    'Giờ đã hết mùi gas',
    'hết bị chập điện',
)


class EmergencyPhrasingTableTests(unittest.TestCase):
    def test_table_is_big_enough_both_ways(self):
        self.assertGreaterEqual(len(DANGER), 30)
        self.assertGreaterEqual(len(NEGATED), 30)
        self.assertTrue(any(any(ch in t for ch in 'ăâđêôơư') for t in DANGER))
        self.assertTrue(any(any(ch in t for ch in 'ăâđêôơư') for t in NEGATED))

    def test_danger_phrasings_are_emergencies(self):
        for txt in DANGER:
            with self.subTest(txt=txt):
                self.assertTrue(technical.is_emergency(txt), txt)

    def test_clearly_negated_phrasings_are_not_emergencies(self):
        for txt in NEGATED:
            with self.subTest(txt=txt):
                self.assertFalse(technical.is_emergency(txt), txt)

    def test_curly_apostrophe_and_case_do_not_change_the_answer(self):
        self.assertTrue(technical.is_emergency('I’ve NEVER seen sparks like this'))
        self.assertTrue(technical.is_emergency('I didn’t notice the burning smell until now'))
        self.assertFalse(technical.is_emergency('I don’t smell gas'))


class NeverSeenSparksJobTests(unittest.TestCase):
    """Câu "never seen sparks like this" qua công cụ thật: AI chọn 'normal' vẫn được nâng lên khẩn cấp."""

    def setUp(self):
        seed()
        self.cid = f'{TECH}:0412345678'
        DB.bot_customers.insert_one({'id': self.cid})

    def test_ai_picked_normal_but_the_customer_described_danger(self):
        out = job(customer_id=self.cid, args={'problem': "Switchboard: I've never seen sparks like this", 'urgency': 'normal'})
        self.assertEqual(out['urgency'], 'emergency')
        self.assertIn('000', out['tell_customer'])
        self.assertIn('somewhere safe', out['tell_customer'])
        bc = DB.bot_customers.find_one({'id': self.cid})
        self.assertTrue(bc['needs_human'] and bc['handoff_urgent'] and bc['ai_paused'])
        self.assertEqual([c[4] for c in CALLS if c[0] == 'alert'], ['technical_emergency'])

    def test_screening_answer_still_stays_normal(self):
        out = job(customer_id=self.cid, args={'problem': "Aircon not cooling. I don't smell gas, no sparks or smoke."})
        self.assertEqual(out['urgency'], 'normal')
        self.assertIsNone(DB.bot_customers.find_one({'id': self.cid}).get('needs_human'))


# ---------------------------------------------------------------- 2. việc khẩn cấp đã xong -> việc mới
class EmergencyAfterACompletedEmergencyTests(unittest.TestCase):
    def setUp(self):
        seed()
        self.cid = f'{TECH}:0412345678'
        DB.bot_customers.insert_one({'id': self.cid})

    def done(self, job_id):
        DB.tasks.update_one({'id': job_id}, {'$set': {'trang_thai': technical.DONE}})

    def reset_handoff(self):
        DB.bot_customers.update_one({'id': self.cid}, {'$set': {'ai_paused': False, 'needs_human': False,
                                                                 'handoff_urgent': False}})
        CALLS.clear()

    def alerts(self):
        return [c for c in CALLS if c[0] == 'alert']

    def assert_new_open_emergency(self, out, old_ids):
        self.assertNotIn(out['job_id'], old_ids)
        self.assertNotIn('already_requested', out)
        self.assertEqual(out['board_status'], 'waiting_for_assignment')
        self.assertEqual(out['urgency'], 'emergency')
        self.assertIn('000', out['tell_customer'])
        self.assertIn(f"job #{out['job_id']}", out['tell_customer'])
        t = DB.tasks.find_one({'id': out['job_id']})
        self.assertEqual((t['urgency'], t['trang_thai']), ('emergency', technical.WAITING))
        al = self.alerts()
        self.assertEqual([a[4] for a in al], ['technical_emergency'])
        self.assertIn(f"#{out['job_id']}", al[0][3])
        bc = DB.bot_customers.find_one({'id': self.cid})
        self.assertTrue(bc['needs_human'] and bc['handoff_urgent'] and bc['ai_paused'])
        self.assertIn(f"#{out['job_id']}", bc['handoff_reason'])

    def test_normal_done_then_emergency_done_then_new_emergency(self):
        first = job(customer_id=self.cid)                                          # việc thường
        self.done(first['job_id'])
        e1 = job(customer_id=self.cid, args={'problem': 'Burst pipe under the sink, water everywhere'})
        self.assertNotEqual(e1['job_id'], first['job_id'])
        self.done(e1['job_id'])                                                    # đội đã xử lý xong việc khẩn cấp
        self.reset_handoff()
        e2 = job(customer_id=self.cid, args={'problem': 'Now there are sparks from the switchboard'})
        self.assert_new_open_emergency(e2, (first['job_id'], e1['job_id']))
        self.assertEqual(len(DB.tasks.docs), 3)
        # khách báo lại: vẫn đúng việc đang mở, không thêm việc / không báo chủ lần 2
        self.reset_handoff()
        again = job(customer_id=self.cid, args={'problem': 'Sparks are still coming out'})
        self.assertEqual(again['job_id'], e2['job_id'])
        self.assertTrue(again['already_requested'])
        self.assertEqual(again['board_status'], 'waiting_for_assignment')
        self.assertIn('000', again['tell_customer'])
        self.assertEqual(self.alerts(), [])
        self.assertTrue(DB.bot_customers.find_one({'id': self.cid})['needs_human'])
        self.assertEqual(len(DB.tasks.docs), 3)

    def test_first_emergency_done_twice_in_one_day(self):
        e1 = job(customer_id=self.cid, args={'problem': 'I can smell gas near the heater'})
        self.assertEqual(e1['urgency'], 'emergency')
        self.done(e1['job_id'])
        e2 = job(customer_id=self.cid, args={'problem': 'Gas smell is back, getting stronger'})
        self.assertNotEqual(e2['job_id'], e1['job_id'])
        self.done(e2['job_id'])
        self.reset_handoff()
        e3 = job(customer_id=self.cid, args={'problem': 'Gas smell again near the heater'})
        self.assert_new_open_emergency(e3, (e1['job_id'], e2['job_id']))
        self.assertEqual(len(DB.tasks.docs), 3)

    def test_normal_duplicate_of_a_done_job_is_unchanged(self):
        first = job(customer_id=self.cid)
        self.done(first['job_id'])
        CALLS.clear()
        again = job(customer_id=self.cid, args={'problem': 'Air-con still leaking'})   # không nguy hiểm: như cũ
        self.assertEqual((again['job_id'], again['already_requested']), (first['job_id'], True))
        self.assertEqual(self.alerts(), [])
        self.assertEqual(len(DB.tasks.docs), 1)

    def test_vi_shop_new_emergency_job_text(self):
        DB.businesses.insert_one({'id': 'tech_vn2', 'name': 'Điện lạnh Q1', 'currency': 'VND', 'country': 'VN',
                                  'industry_code': 'technical'})
        cid = 'tech_vn2:0901234567'
        DB.bot_customers.insert_one({'id': cid})
        args = {'customer_name': 'Anh Nam', 'phone': '0901 234 567', 'address': '5 Lê Lợi, Quận 1, TP HCM'}
        ids = []
        for problem in ('Ổ cắm có mùi khét', 'Lại có mùi khét ở ổ cắm', 'Ổ cắm bốc khói'):
            out = technical.execute('technical_request_job', {**args, 'problem': problem}, ctx('tech_vn2', customer_id=cid, lang='vi'))
            self.assertEqual(out['urgency'], 'emergency')
            self.assertNotIn(out['job_id'], ids)
            self.assertIn('114', out['tell_customer'])
            self.assertIn(f"việc #{out['job_id']}", out['tell_customer'])
            ids.append(out['job_id'])
            self.done(out['job_id'])
        self.assertEqual(len(DB.tasks.docs), 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
