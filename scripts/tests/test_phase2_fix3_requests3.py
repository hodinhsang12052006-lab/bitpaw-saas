# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 vòng 3, khu "requests3" (ai_packs/technical.py, production.py, office.py, retail.py):
  1. Phân loại NGUY HIỂM mới (technical.classify_hazard -> 'danger' | 'negated' | 'none'), theo từng câu, câu CUỐI nói về mỗi
     nguy hiểm quyết định:
       - việc thường không còn bị ép khẩn cấp: máy hút mùi / ống khói / khói bếp / khói thuốc, smoke test / seal / damper /
         sensor / -free, báo khói, gas bill, "no power";
       - câu sàng lọc phủ định rõ ("No sparks or burning smell when switching on", "không có mùi khét khi bật máy") là việc
         thường; câu chỉ HỎI / GIẢ ĐỊNH ("is it dangerous if there is smoke?") cũng vậy — kèm câu dặn an toàn (safety_tip);
       - phủ định lúc trước rồi CÓ bây giờ ("Didn't smell gas this morning, but I do now", "hôm qua không có khói, hôm nay
         có") là KHẨN CẤP; "smelled gas earlier, it's gone now" / "giờ hết mùi rồi" là đã hết (+ dặn an toàn).
     Bảng >= 120 câu EN + VI (gồm mọi câu trong báo cáo review, cả 2 chiều, trộn ngôn ngữ, gõ sai "smel gas", "mui gas").
  2. Yêu cầu trùng (job / quote / consult) mà chat KHÔNG chứng minh được là chủ (trình duyệt khác gõ cùng SĐT -> cùng id hội
     thoại web) nhận câu chung "đã chuyển cho đội", KHÔNG có mã yêu cầu (giống fnb / karaoke / hotel); chat chủ vẫn nhận mã.

Dùng lại DB giả + stub của test_phase2_request_packs.py (nạp TRƯỚC mọi gói): không import app.py thật, không MongoDB thật,
không gọi mạng. Chạy: python scripts/tests/test_phase2_fix3_requests3.py
"""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_request_packs as base  # noqa: E402,F401  (cài mongo_client / app / ai_function_tools giả)

from test_phase2_request_packs import (CALLS, DB, OFFICE, PROD, TECH, consult, ctx, job, office, production,  # noqa: E402
                                       quote, retail, seed, technical)

# ================================================================ bảng câu
# --- báo cáo review, mục 1: việc thường bị ép khẩn cấp -> 'none'
ITEM1_NONE = (
    'Máy hút mùi yếu, bếp nhiều khói', 'hood không hút hết khói', 'máy hút mùi không hút được khói', 'thông ống khói bếp',
    'vệ sinh ống khói', 'khói bếp bám tường, cần vệ sinh', 'lắp cảm biến khói', 'khói thuốc lá bay vào phòng, lắp quạt hút',
    'range hood not pulling smoke out', "exhaust fan doesn't clear the smoke when cooking",
    'BBQ smoke goes into the house, need exhaust fan', 'Plumbing smoke test needed', 'Install smoke seals on doors',
    'smoke damper service', 'replace smoke sensor', 'Smoke-free area sign install',
)
# --- mục 2: câu sàng lọc phủ định rõ -> 'negated'
ITEM2_NEGATED = (
    'No sparks or burning smell when switching on', 'No burning smell or sparks when it trips',
    'Customer confirms no gas smell when the heater runs', "Heater won't ignite. Customer says no gas smell before or after.",
    'No sparks if I flip the switch', 'No sparks so it should be safe', 'no burning smell when I checked',
    'không có mùi khét khi bật máy', 'không có khói nếu bật', "I haven't seen any smoke or sparks",
)
# --- mục 3: phủ định lúc trước, CÓ bây giờ -> 'danger'
ITEM3_DANGER = (
    "Didn't smell gas this morning, but I do now", "Didn't smell gas this morning but now I do",
    "We didn't smell burning yesterday, today we do", 'There was no gas smell yesterday, today there is',
    'hôm qua không có khói, hôm nay có', 'hôm qua chưa có mùi khét, nay có',
)
BRIEF = (
    ("didn't smell gas this morning, but I do now", 'danger'),
    ("smelled gas earlier, it's gone now", 'negated'),
    ('Lúc nãy có mùi gas, giờ hết mùi rồi', 'negated'),
    ('Có mùi khét lúc nãy, hết mùi rồi', 'negated'),
    ('Is it dangerous if there is smoke?', 'none'),
    ('no power', 'none'), ('No power since this morning', 'none'),
    ('Gas bill question', 'none'), ('Quote to install a gas stove', 'none'), ('báo giá lắp bếp gas', 'none'),
    ('Smoke alarm battery keeps chirping', 'none'), ('Install smoke detectors in 3 bedrooms', 'none'),
    ('lắp báo khói cho phòng ngủ', 'none'), ('thay pin báo khói', 'none'), ('vệ sinh máy hút mùi', 'none'),
    ('chimney sweep needed', 'none'), ('khói bếp nhiều quá, cần lắp máy hút khói', 'none'),
)
DANGER_EN = (
    'I can smell gas in the kitchen', 'Strong gas smell near the meter', 'gas leak at the back of the house',
    'Sparks coming out of the power point', 'The outlet sparked when I plugged in the kettle', 'switchboard is arcing',
    'Burning smell from the switchboard', 'It smells like burning plastic', 'Smells like something burning near the fan',
    'Smoke coming out of the aircon unit', 'There is smoke coming from the wall socket', 'the fridge is smoking',
    'I got a shock from the oven door', 'My son got an electric shock from the tap', 'tingling when I touch the shower tap',
    'Water pouring through the ceiling light', 'water dripping into the light fitting', 'The laundry is flooded',
    'burst pipe, water everywhere', 'CO alarm going off in the hallway', 'Carbon monoxide alarm keeps going off',
    'The heater caught fire', 'Flames coming out of the heater', 'The water heater exploded',
    "I've never seen sparks like this", "I didn't notice the burning smell until now", 'No smoke until I switched it on',
    "No burning smell when it's off", 'At first there was no smoke, then it started pouring out',
    "not sure if it's sparking", "I don't think it's a gas leak", 'no i can smell gas', 'no the gas smell is really strong',
    'almost no smoke now', 'No power, sparks or smoke from the board', 'No gas smell, sparks.',
    'the smoke alarm went off and there is smoke', 'No burning smell. Sparks now.',
    'There was no gas smell, but now there is.', 'Gas smell is back', 'It stopped sparking but now it smells like burning',
    'Range hood motor is smoking', 'smoke from the outlet behind the range hood', 'Gas smell? Yes',
    'smoke is coming out, is it dangerous?', 'Is this smoke dangerous?', 'Is it normal that sparks come out of the plug?',
    'If I flip the switch there are sparks', 'Sparks if I flip the switch', 'The outlet sparked this morning',
    'Smelled gas earlier today', 'Something is burning in the switchboard', 'sparks yesterday and again today',
    'Gas smell since yesterday', 'The gas smell went away but came back', "There's a strong smell of gas",
    'I think we have a gas leak', 'My kid got zapped by the outlet', 'The tap gives me a shock', 'the switchboard is wet',
    'Gas smell is faint now', 'gas smell mostly gone', 'Had sparks last night, still happening',
    'hissing sound from the gas line', 'smells like rotten eggs', 'What should I do? I smell gas',
    'what do I do there are sparks coming from the outlet', 'How dangerous is the smoke coming out of my fridge?',
    "Didn't spark before, now it does", 'Sparks from the outlet when I plug anything in', 'LPG bottle leaking',
    'Gas meter hissing', 'ceiling light full of water', 'rain water coming in near the switchboard', 'smoke and CO alarms going off',
    'the smoke detector keeps going off and I can smell smoke', 'it sparked and now the power is out',
)
DANGER_VI = (
    'Nghe mùi gas trong bếp', 'Bếp gas bị xì', 'Bình gas bị rò rỉ', 'rò rỉ gas ở van', 'Ổ cắm có tia lửa',
    'chập điện ở ổ cắm', 'Tủ điện có mùi khét', 'Ổ cắm có mùi khét', 'Máy lạnh xì khói đen', 'Khói từ ổ cắm',
    'Có khói bốc ra từ tủ điện', 'Tủ lạnh bị rò điện, chạm vào tê tay', 'không có điện, bị điện giật khi chạm vào',
    'Nước ngập sàn bếp, gần ổ điện', 'Nước chảy vào ổ cắm', 'Bình nóng lạnh phát nổ', 'Ổ điện bốc cháy',
    'Chưa bao giờ thấy tia lửa như vầy', 'Lúc đầu không có mùi khét', 'Không để ý mùi khét cho đến giờ',
    'Không có mùi khét nhưng giờ thì có rồi', 'Hông có mùi khét lúc đầu, giờ khét lẹt', 'khong biet co ro ri gas khong',
    'Vẫn chưa hết mùi gas', 'không hết mùi khét', 'Sắp hết mùi khét', 'Nước tràn hết ngập nhà', 'không phải không có khói',
    'không có mùi gas nhưng có mùi khét', 'Máy không chạy có mùi khét', 'Không lạnh. Có khói bốc ra',
    'Máy hút mùi bị chập điện', 'Máy hút mùi có mùi khét', 'có tia lửa ở ổ cắm có sao không',
    'Có mùi khét không biết có sao không', 'Hôm qua hết mùi gas, nay lại có', 'lúc nãy hết khói rồi mà giờ lại có',
    'Tủ điện có tia lửa, em đã tắt cầu dao', 'Hôm qua bình thường, hôm nay có mùi khét',
    'Không có tia lửa trước đây, giờ thì có', 'Mùi gas: có', 'khói đen từ máy giặt', 'Ổ điện xẹt lửa', 'ổ cắm bị nóng chảy',
    'dây điện bốc khói', 'tủ điện bị cháy', 'chạm vào máy giặt bị giật', 'nước tràn vào tủ điện', 'nhà bị ngập',
    'nghe tiếng nổ ở cầu dao', 'aptomat nhảy, có mùi khét', 'Báo động khí CO kêu', 'nhà đang cháy', 'phòng bị cháy',
    'ổ cắm có lửa', 'điện bị rò ở bình nóng lạnh', 'vỏ máy giặt có điện', 'tủ điện bị ướt', 'Mùi như cháy dây điện',
    'nghe hơi gas trong bếp',
)
DANGER_MIX = (   # trộn tiếng Việt / tiếng Anh, gõ sai, không dấu
    'smel gas in the kitchen', 'i can smel gas', 'mui gas nồng lắm', 'mui gas trong bep', 'gass leak',
    'burnig smell from outlet', 'ổ cắm có sparks', 'outlet bốc khói', 'có smell gas', 'switchboard có mùi khét',
    'chap dien o cau dao', 'tia lua o o cam', 'bi dien giat', 'dien giat khi cham vao tu lanh', 'khói from the socket',
    'sparkin outlet', 'smokin power point', 'SPARKS FROM OUTLET',
)
NEGATED_EN = (
    'no gas smell', 'not sparking', 'without smoke', 'Aircon not cooling. No burning smell or sparks.', "I don't smell gas",
    'I do not smell gas', 'There is no smoke coming out', "No sparks, no smoke, just won't turn on",
    "It doesn't smell like burning", "Haven't seen any sparks", "I can't see any smoke", "I don't see any sparks or smoke",
    'no longer flooding', 'There are no signs of a gas leak', 'Heater has not been sparking', 'Neither smoke nor sparks',
    'Fridge stopped working - no smoke or burning smell', "It isn't sparking any more", 'No flooding, no sparks',
    'Aircon not cooling, making a loud noise. No gas smell, sparks or smoke.', 'Not sparking, smoking, or flooding.',
    'No sparks or anything like that', 'No gas smell, sparks and smoke.', 'No burning smell and sparks when switching on',
    "I didn't get a shock", 'Customer did not smell gas', 'The sparks stopped', 'gas smell is gone now', 'Sparks? No',
    'Gas smell: none', 'Smoke - no', 'Never had sparks from it', 'Didnt smell gas', "There's no gas smell, sparks or smoke?",
    "There's no gas smell at all", "Doesn't smell of gas", 'No gas smell. No sparks. No smoke.',
    'It was sparking, now it is not', 'The sparking stopped after I turned off the breaker',
    'gas smell went away after we opened the windows', 'No smoke now',
    'customer was asked about sparks/smoke/gas smell: none',
)
NEGATED_VI = (
    'không có mùi khét', 'hết mùi gas', 'Đã hết mùi gas rồi', 'không bị điện giật', 'Không có khói', 'không thấy tia lửa',
    'không còn mùi gas', 'ko có mùi khét gì hết', 'Máy lạnh không lạnh, không có mùi khét hay tia lửa', 'không hề có khói',
    'khong co mui gas', 'Nhà không bị ngập nước', 'không thấy khói bốc ra', 'Đèn không chập điện, chỉ không sáng',
    'chưa thấy có khói', 'Không ngửi thấy mùi gas', 'không có dấu hiệu rò gas', 'không có mùi gas, tia lửa hay khói',
    'Giờ đã hết mùi gas', 'hết bị chập điện', 'Không có mùi khét và tia lửa', 'mùi gas hết rồi', 'khói tan rồi',
    'không có tia lửa hay gì như vậy', 'no mùi khét', 'không có gas leak', 'khong co tia lua', 'ko thấy khói hay tia lửa gì',
    'chưa thấy dấu hiệu chập điện', 'Có mùi khét, giờ thì không còn', 'Có tia lửa lúc nãy, giờ hết rồi', 'Không còn khói nữa',
)
NONE_ALL = (
    'flood light not working', 'spark plug on the mower', 'fire alarm beeping, battery low', 'bóng đèn bị cháy',
    'máy lạnh chảy nước', 'Air-con leaking water inside', 'máy hút khói không hút được', 'Đầu báo khói kêu liên tục',
    'Smoke alarm keeps beeping, battery low', 'Smoke detector chirping every minute, needs new battery',
    'CO alarm beeping, needs a new battery', 'Need a gas leak test for the compliance certificate', 'Flood damage repair quote',
    'đèn bị chập chờn', 'cầu chì bị cháy, cần thay', 'Our sparky is on leave', 'Spark broadband modem not working',
    'Gas heater not lighting, pilot flame keeps going out', 'What should I do if I smell gas?',
    'Is it safe to stay inside if there is no gas smell?', 'Is there a gas leak?', 'Could it be a gas leak?',
    'Có khói thì có nguy hiểm không?', 'Không có mùi gas thì có nguy hiểm không?', 'Nếu không có khói thì có sao không',
    'Có rò rỉ gas không?', 'If there are sparks, should I turn off the power?',
    'The outlet sparked last week, now it does not work', 'We had a gas leak last year, want a new heater installed',
    'Tháng trước bị chập điện một lần, giờ muốn kiểm tra lại', 'cooking smoke sets off the alarm, need a better range hood',
    'khói nướng bay vào nhà, cần lắp quạt hút', 'máy không khởi động được', 'ra khỏi nhà thì tắt máy lạnh',
    'need a new gas hot water system', 'Gas fitter needed for cooktop install', 'Smoke alarm replacement x5',
    'Interconnected smoke alarms', 'replace smoke alarms and test RCDs', 'fire alarm panel fault',
    "Burner on the stove won't light", 'Hot water leaking from the relief valve', 'Need exhaust fan installed in bathroom',
    'Spark arrestor for chimney', 'TV burnt out', 'the breaker keeps tripping', 'Gas cooktop flame is yellow',
    'Annual gas safety check', 'Lắp máy hút mùi', 'máy lạnh có mùi hôi', 'sửa bếp ga', 'đổi bình gas',
    'cầu dao nhảy liên tục', 'Có cần lắp báo khói không?', 'Kitchen is smoky when we cook, need a bigger range hood',
    'Smoke from the BBQ comes in through the window', 'Our fireplace chimney needs cleaning, smoke comes back in',
    'The burnt toast set off the smoke alarm', 'bếp nhiều khói quá khi nấu, cần thay máy hút mùi',
    'Install smoke and heat detectors', 'replace smoke/CO alarms', 'dịch vụ diệt côn trùng phun khói',
    'smoke bomb for pest control', 'Install CO alarm', 'Gas leak detector install', 'bếp gas không lên lửa',
    'electric fire not heating', 'lắp bình chữa cháy', 'kiểm tra hệ thống báo cháy',
)
# --- câu sàng lọc AI / nhân viên ghi vào mô tả việc: câu trả lời ngay sau câu hỏi quyết định
SCREENING = (
    ('Sparks: yes | gas: no', 'danger'), ('Checked for sparks: yes', 'danger'), ('Checked for sparks and found some', 'danger'),
    ('Asked if there is any gas smell: yes', 'danger'), ('Customer confirmed gas smell', 'danger'),
    ('Kiểm tra thấy chập điện', 'danger'), ('Sparks, smoke: yes', 'danger'), ('Mùi khét? Khách nói có', 'danger'),
    ('Asked about gas smell, sparks, smoke: none', 'negated'), ('Asked about gas smell: customer says no', 'negated'),
    ('Hỏi khách về mùi gas: không có', 'negated'), ('Đã hỏi mùi khét, tia lửa: khách nói không', 'negated'),
    ('Smelled gas earlier, opened the windows, it is gone now', 'negated'), ('Any sparks? Nope', 'negated'),
    ('Asked about gas smell', 'none'), ('Hỏi khách có mùi gas không', 'none'),
)
TABLE = ([(t, 'none') for t in ITEM1_NONE] + [(t, 'negated') for t in ITEM2_NEGATED] + [(t, 'danger') for t in ITEM3_DANGER]
         + list(BRIEF) + [(t, 'danger') for t in DANGER_EN + DANGER_VI + DANGER_MIX]
         + [(t, 'negated') for t in NEGATED_EN + NEGATED_VI] + [(t, 'none') for t in NONE_ALL] + list(SCREENING))
# phase2-fix4 (emergency4) — ƯU TIÊN KHÔNG BỎ SÓT: tin nhắn có nhắc nguy hiểm chỉ còn là việc thường ('none' /
# 'negated') khi phủ định RÕ hoặc là cụm không-nguy-hiểm trong danh sách. Các dòng dưới đây vòng 3 ghi 'none' (việc
# thường) — nay là 'uncertain' (việc GẤP + người thật gọi kiểm tra + câu dặn an toàn có điều kiện) hoặc 'danger'.
# Bảng mới đầy đủ: test_phase2_fix5_emergency5.py.
FIX4_CHANGED = {
    # câu HỎI / GIẢ ĐỊNH về nguy hiểm: khách chưa loại trừ nguy hiểm -> 'uncertain' (không còn lặng lẽ là việc thường)
    'Is it dangerous if there is smoke?': 'uncertain', 'What should I do if I smell gas?': 'uncertain',
    'Is it safe to stay inside if there is no gas smell?': 'uncertain', 'Is there a gas leak?': 'uncertain',
    'Could it be a gas leak?': 'uncertain', 'Có khói thì có nguy hiểm không?': 'uncertain',
    'Không có mùi gas thì có nguy hiểm không?': 'uncertain', 'Nếu không có khói thì có sao không': 'uncertain',
    'Có rò rỉ gas không?': 'uncertain', 'If there are sparks, should I turn off the power?': 'uncertain',
    # chuyện ĐÃ QUA mà không nói đã hết -> 'uncertain' (người thật gọi hỏi xem còn không)
    'The outlet sparked last week, now it does not work': 'uncertain',
    'We had a gas leak last year, want a new heater installed': 'uncertain',
    'Tháng trước bị chập điện một lần, giờ muốn kiểm tra lại': 'uncertain',
    # câu sàng lọc CHƯA có câu trả lời: chưa loại trừ -> 'uncertain'
    'Asked about gas smell': 'uncertain', 'Hỏi khách có mùi gas không': 'uncertain',
    # đầu báo khói đang kêu liên tục (không nói hết pin / do nấu ăn) = chuông báo ĐANG kêu -> 'danger'
    'Đầu báo khói kêu liên tục': 'danger',
}
TABLE = [(t, FIX4_CHANGED.get(t, w)) for t, w in TABLE]
_VI_CHARS = 'ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ'


def alerts():
    return [c for c in CALLS if c[0] == 'alert']


def notes():
    return [c for c in CALLS if c[0] == 'note']


# ================================================================ 1. phân loại nguy hiểm
class HazardClassifierTableTests(unittest.TestCase):
    def test_table_size_languages_and_review_phrases(self):
        self.assertGreaterEqual(len(TABLE), 120)
        self.assertEqual(len({t for t, _ in TABLE}), len(TABLE), 'duplicate rows')
        vi = [t for t, _ in TABLE if any(ch in t.lower() for ch in _VI_CHARS)]
        self.assertGreaterEqual(len(vi), 60)
        self.assertGreaterEqual(len(TABLE) - len(vi), 60)
        for want in ('danger', 'negated', 'none'):
            self.assertGreaterEqual(sum(w == want for _, w in TABLE), 30, want)
        rows = dict(TABLE)
        for t in ITEM1_NONE + ITEM2_NEGATED + ITEM3_DANGER:   # mọi câu trong báo cáo review đều có trong bảng
            self.assertIn(t, rows)

    def test_every_phrase_classified(self):
        for txt, want in TABLE:
            with self.subTest(txt=txt):
                self.assertEqual(technical.classify_hazard(txt), want)
                self.assertEqual(technical.is_emergency(txt), want == 'danger')

    def test_last_statement_about_each_hazard_wins(self):
        self.assertEqual(technical.hazard_check("didn't smell gas this morning, but I do now"), ('danger', {'gas': 'present'}))
        self.assertEqual(technical.hazard_check("smelled gas earlier, it's gone now"), ('negated', {'gas': 'negated'}))
        verdict, st = technical.hazard_check('Gas smell? No. Sparks? Yes')
        self.assertEqual((verdict, st), ('danger', {'gas': 'negated', 'sparks': 'present'}))
        verdict, st = technical.hazard_check('Lúc nãy có mùi gas và tia lửa, giờ hết mùi rồi')   # "hết mùi" chỉ kết thúc mùi gas
        self.assertEqual((verdict, st['gas'], st['sparks']), ('danger', 'negated', 'present'))
        self.assertEqual(technical.hazard_check('sparked last week and smells burnt now'),
                         ('danger', {'sparks': 'past', 'burning': 'present'}))

    def test_a_bare_answer_belongs_to_the_screening_question_right_before_it(self):
        # "no" after "gas:" (không phải từ khoá nguy hiểm) KHÔNG được xoá "Sparks: yes" — trước đây bỏ sót tia lửa
        self.assertEqual(technical.hazard_check('Sparks: yes | gas: no'), ('danger', {'sparks': 'present'}))
        self.assertEqual(technical.hazard_check('Gas smell? No. Sparks? Yes'),
                         ('danger', {'gas': 'negated', 'sparks': 'present'}))
        self.assertEqual(technical.hazard_check('Asked about gas smell, sparks, smoke: none'),
                         ('negated', {'gas': 'negated', 'sparks': 'negated', 'smoke': 'negated'}))
        # phase2-fix4: câu sàng lọc CHƯA có trả lời là chưa loại trừ -> 'uncertain' (trước: 'none')
        self.assertEqual(technical.hazard_check('Asked about gas smell'), ('uncertain', {'gas': 'question'}))
        self.assertEqual(technical.hazard_check('Kiểm tra thấy chập điện'), ('danger', {'sparks': 'present'}))

    def test_questions_and_hypotheticals_are_not_emergencies_but_are_hazard_mentions(self):
        for txt in ('Is it dangerous if there is smoke?', 'What should I do if I smell gas?', 'Có rò rỉ gas không?',
                    'Nếu có khói thì sao?', 'Có khói thì có nguy hiểm không?'):
            with self.subTest(txt=txt):
                verdict, st = technical.hazard_check(txt)
                self.assertEqual(verdict, 'uncertain')   # phase2-fix4: không khẩn cấp nhưng KHÔNG phải việc thường
                self.assertTrue(st and set(st.values()) <= {'question', 'hypothetical'}, st)

    def test_exclusions_are_not_hazard_mentions_at_all(self):
        for txt in ITEM1_NONE + ('Smoke alarm battery keeps chirping', 'Gas bill question', 'no power'):
            with self.subTest(txt=txt):
                self.assertEqual(technical.hazard_check(txt), ('none', {}))

    def test_case_curly_apostrophe_empty_and_long_input(self):
        self.assertEqual(technical.classify_hazard('I DON’T SMELL GAS'), 'negated')
        self.assertEqual(technical.classify_hazard('Didn’t smell gas this morning, but I do now'), 'danger')
        for empty in (None, '', '   ', 12345):
            self.assertEqual(technical.hazard_check(empty), ('none', {}))
        long = ('Aircon not cooling, making a loud noise, ' * 15) + 'no gas smell, sparks or smoke.'
        self.assertEqual(technical.classify_hazard(long), 'negated')
        self.assertEqual(technical.classify_hazard(long + ' Now the outlet is sparking.'), 'danger')


# ================================================================ 1b. qua công cụ thật: mức gấp, chuyển người, câu dặn
class HazardJobToolTests(unittest.TestCase):
    def setUp(self):
        seed()
        self.cid = f'{TECH}:0412345678'
        DB.bot_customers.insert_one({'id': self.cid})

    def assert_normal(self, out, tip):
        self.assertEqual(out['urgency'], 'normal')
        self.assertNotIn('000', out['tell_customer'])
        self.assertNotIn('somewhere safe', out['tell_customer'])
        self.assertIsNone(DB.bot_customers.find_one({'id': self.cid}).get('needs_human'))
        self.assertEqual([a[4] for a in alerts()], ['technical_job'])
        t = DB.tasks.find_one({'id': out['job_id']})
        self.assertEqual(t['urgency'], 'normal')
        if tip:
            self.assertIn('000', out['safety_tip'])
            self.assertIn('safety_tip', out['note'])
        else:
            self.assertNotIn('safety_tip', out)

    def test_review_false_alarms_are_normal_jobs_without_a_safety_line(self):
        for i, problem in enumerate(ITEM1_NONE[:6] + ITEM1_NONE[-6:]):
            with self.subTest(problem=problem):
                CALLS.clear()
                out = job(customer_id=self.cid, args={'problem': problem, 'address': f'{i + 1} King St, Newtown NSW'})
                self.assert_normal(out, tip=False)

    def test_screening_answers_are_normal_jobs_with_a_safety_line(self):
        for i, problem in enumerate(ITEM2_NEGATED + ("smelled gas earlier, it's gone now",)):
            with self.subTest(problem=problem):
                CALLS.clear()
                out = job(customer_id=self.cid, args={'problem': problem, 'address': f'{i + 1} King St, Newtown NSW'})
                self.assert_normal(out, tip=True)

    def test_a_safety_question_is_an_urgent_job_checked_by_a_person(self):
        # phase2-fix4 (ưu tiên không bỏ sót): câu hỏi về nguy hiểm không còn là việc thường — việc GẤP, người thật gọi
        # kiểm tra, câu dặn an toàn CÓ ĐIỀU KIỆN nằm trong tell_customer, không bảo sơ tán ngay
        out = job(customer_id=self.cid, args={'problem': 'Aircon noisy. Is it dangerous if there is smoke?'})
        self.assertEqual(out['urgency'], 'urgent')
        self.assertIn('leave the area and call 000', out['tell_customer'])
        self.assertNotIn('somewhere safe', out['tell_customer'])
        self.assertTrue(DB.bot_customers.find_one({'id': self.cid})['needs_human'])
        self.assertEqual([a[4] for a in alerts()], ['technical_hazard_check'])

    def test_past_negation_then_danger_now_is_an_emergency(self):
        for i, problem in enumerate(ITEM3_DANGER):
            with self.subTest(problem=problem):
                DB.bot_customers.update_one({'id': self.cid}, {'$set': {'needs_human': False, 'ai_paused': False}})
                CALLS.clear()
                out = job(customer_id=self.cid, args={'problem': problem, 'address': f'{i + 1} King St, Newtown NSW'})
                self.assertEqual(out['urgency'], 'emergency')
                self.assertIn('000', out['tell_customer'])
                self.assertIn(f"job #{out['job_id']}", out['tell_customer'])
                self.assertNotIn('safety_tip', out)
                bc = DB.bot_customers.find_one({'id': self.cid})
                self.assertTrue(bc['needs_human'] and bc['handoff_urgent'] and bc['ai_paused'])
                self.assertEqual([a[4] for a in alerts()], ['technical_emergency'])

    def test_classifier_never_downgrades_an_emergency_the_ai_chose(self):
        out = job(customer_id=self.cid, args={'problem': 'No sparks or burning smell when switching on', 'urgency': 'emergency'})
        self.assertEqual(out['urgency'], 'emergency')
        self.assertIn('000', out['tell_customer'])

    def test_vi_shop_gets_the_vi_safety_line_with_114(self):
        DB.businesses.insert_one({'id': 'tech_vn3', 'name': 'Điện lạnh Q3', 'currency': 'VND', 'country': 'VN',
                                  'industry_code': 'technical'})
        out = technical.execute('technical_request_job', {'customer_name': 'Anh Nam', 'phone': '0901 234 567',
                                                          'address': '5 Lê Lợi, Quận 1, TP HCM',
                                                          'problem': 'Lúc nãy có mùi gas, giờ hết mùi rồi'},
                                ctx('tech_vn3', lang='vi'))
        self.assertEqual(out['urgency'], 'normal')
        self.assertIn('gọi 114', out['safety_tip'])
        self.assertIn('ra chỗ an toàn', out['safety_tip'])
        self.assertNotIn('114', out['tell_customer'])

    def test_shop_without_a_country_names_no_fake_number(self):
        DB.businesses.insert_one({'id': 'nc_tech3', 'name': 'NC', 'industry_code': 'technical'})
        out = technical.execute('technical_request_job', {'customer_name': 'Tom', 'phone': '0412 345 678',
                                                          'address': '12 King St, Newtown', 'problem': 'No gas smell'},
                                ctx('nc_tech3', country=None))
        self.assertIn('call emergency services', out['safety_tip'])
        self.assertFalse(re.search(r'\b(000|911|114|111|999)\b', out['safety_tip']))

    def test_prompt_and_tool_text_say_danger_happening_now(self):
        desc = technical.TOOLS[0]['function']['description']
        self.assertIn('danger happening now', desc)
        self.assertIn('range hood', desc)
        self.assertIn('happening now', technical.PROMPT_RULES['en'])
        self.assertIn('only ask whether something is dangerous', technical.PROMPT_RULES['en'])
        self.assertIn('đang xảy ra', technical.PROMPT_RULES['vi'])
        self.assertIn('Máy hút mùi', technical.PROMPT_RULES['vi'])


# ================================================================ 2. yêu cầu trùng chưa chứng minh là chủ: không lộ mã
class UnprovenDuplicateTests(unittest.TestCase):
    def setUp(self):
        seed()

    def assert_generic(self, out, *ids):
        self.assertTrue(out['success'])
        self.assertTrue(out['request_sent_to_team'])
        self.assertFalse(out['confirmed'])
        for k in ('job_id', 'quote_request_id', 'consult_request_id', 'already_requested', 'board_status', 'escalated',
                  'located_on_map', 'preferred'):
            self.assertNotIn(k, out)
        blob = json.dumps(out, ensure_ascii=False)
        for i in ids:
            self.assertNotRegex(blob, rf'#\s*{i}\b')
        self.assertIn('give no', out['note'].lower())

    # ---------------------------------------------------------------- kỹ thuật
    def test_job_from_another_browser_gets_no_job_number_but_the_owner_still_does(self):
        cid = f'{TECH}:0412345678'
        first = job(customer_id=cid, chat_token_hash='tokOwner')
        CALLS.clear()
        out = job(customer_id=cid, chat_token_hash='tokStranger')
        self.assert_generic(out, first['job_id'])
        self.assertEqual(out['status'], 'pending')
        self.assertIn('passed your request to the team', out['tell_customer'])
        self.assertIn('Nothing is scheduled', out['tell_customer'])
        self.assertEqual(len(DB.tasks.docs), 1)                                       # không tạo việc thứ 2
        self.assertEqual(alerts(), [])                                                 # không email chủ lần 2
        nt = notes()
        self.assertEqual(len(nt), 1)
        self.assertEqual(nt[0][2], cid)
        self.assertIn(f"job #{first['job_id']}", nt[0][3])                             # nhân viên biết việc nào
        self.assertIn("isn't verified", nt[0][3])
        mine = job(customer_id=cid, chat_token_hash='tokOwner')                        # chat chủ vẫn nhận mã của mình
        self.assertEqual((mine['already_requested'], mine['job_id']), (True, first['job_id']))

    def test_anonymous_token_is_not_proof_but_a_verified_phone_is(self):
        cid = f'{TECH}:0412345678'
        first = job(customer_id=cid, chat_token_hash='tokOwner')
        self.assert_generic(job(customer_id=cid, chat_token_hash='anon:abc'), first['job_id'])
        verified = job(customer_id=cid, chat_token_hash='tokOther', phone='+61412345678')
        self.assertEqual(verified['job_id'], first['job_id'])

    def test_vi_customer_gets_the_vi_generic_reply(self):
        cid = f'{TECH}:0412345678'
        first = job(customer_id=cid, chat_token_hash='tokOwner')
        out = job(customer_id=cid, chat_token_hash='tokStranger', lang='vi')
        self.assert_generic(out, first['job_id'])
        self.assertIn('Em đã chuyển yêu cầu cho đội kỹ thuật', out['tell_customer'])
        self.assertIn('CHƯA', out['tell_customer'])

    def test_stranger_mentioning_a_ruled_out_danger_still_gets_the_safety_line(self):
        cid = f'{TECH}:0412345678'
        first = job(customer_id=cid, chat_token_hash='tokOwner')
        out = job(customer_id=cid, chat_token_hash='tokStranger', args={'problem': 'Aircon leaking, no gas smell'})
        self.assert_generic(out, first['job_id'])
        self.assertIn('000', out['safety_tip'])

    def test_emergency_from_another_browser_escalates_the_job_without_revealing_it(self):
        cid = f'{TECH}:0412345678'
        DB.bot_customers.insert_one({'id': cid})
        first = job(customer_id=cid, chat_token_hash='tokOwner')
        CALLS.clear()
        out = job(customer_id=cid, chat_token_hash='tokStranger',
                  args={'problem': 'There are sparks coming from the switchboard'})
        self.assert_generic(out, first['job_id'])
        self.assertEqual(out['urgency'], 'emergency')
        self.assertIn('000', out['tell_customer'])                                    # vẫn dặn ra chỗ an toàn + gọi 000
        self.assertIn('somewhere safe', out['tell_customer'])
        self.assertNotIn('job #', out['tell_customer'])
        self.assertEqual(len(DB.tasks.docs), 1)
        self.assertEqual(DB.tasks.find_one({'id': first['job_id']})['urgency'], 'emergency')   # nguy hiểm không bị nuốt
        bc = DB.bot_customers.find_one({'id': cid})
        self.assertTrue(bc['needs_human'] and bc['handoff_urgent'])
        al = alerts()
        self.assertEqual([a[4] for a in al], ['technical_emergency'])
        self.assertIn(f"#{first['job_id']}", al[0][3])                                # chủ tiệm biết đúng việc
        self.assertIn("isn't verified", notes()[-1][3])

    def test_emergency_after_the_owners_job_is_done_is_the_strangers_own_new_job(self):
        cid = f'{TECH}:0412345678'
        first = job(customer_id=cid, chat_token_hash='tokOwner')
        DB.tasks.update_one({'id': first['job_id']}, {'$set': {'trang_thai': technical.DONE}})
        out = job(customer_id=cid, chat_token_hash='tokStranger', args={'problem': 'I can smell gas in the kitchen'})
        self.assertNotEqual(out['job_id'], first['job_id'])
        self.assertNotIn('already_requested', out)
        self.assertIn(f"job #{out['job_id']}", out['tell_customer'])                  # việc MỚI của chính chat này

    def test_same_browser_without_a_conversation_and_same_typed_phone_is_the_owner(self):
        DB.businesses.insert_one({'id': 'nc_tech4', 'name': 'NC', 'industry_code': 'technical'})
        args = {'customer_name': 'Tom', 'address': '12 King St, Newtown', 'problem': 'Heater not working',
                'phone': '0412 345 678'}
        a = technical.execute('technical_request_job', args, ctx('nc_tech4', chat_token_hash='tokS'))
        b = technical.execute('technical_request_job', args, ctx('nc_tech4', chat_token_hash='tokS'))
        self.assertEqual((b['already_requested'], b['job_id']), (True, a['job_id']))
        c = technical.execute('technical_request_job', args, ctx('nc_tech4', chat_token_hash='tokOther'))
        self.assert_generic(c, a['job_id'])

    # ---------------------------------------------------------------- sản xuất
    def test_quote_from_another_browser_gets_no_quote_number(self):
        cid = f'{PROD}:0901234567'
        first = quote(customer_id=cid, chat_token_hash='tokOwner')
        CALLS.clear()
        out = quote(customer_id=cid, chat_token_hash='tokStranger')
        self.assert_generic(out, first['quote_request_id'])
        self.assertEqual(out['status'], 'new')
        self.assertIn('Em đã chuyển yêu cầu báo giá cho xưởng', out['tell_customer'])
        self.assertIn('không báo giá được', out['tell_customer'])
        self.assertEqual(len(DB.quote_requests.docs), 1)
        self.assertEqual(alerts(), [])
        nt = notes()
        self.assertEqual(len(nt), 1)
        self.assertIn(f"báo giá #{first['quote_request_id']}", nt[0][3])              # tiệm VN: ghi chú tiếng Việt
        self.assertIn('chưa xác minh', nt[0][3])
        mine = quote(customer_id=cid, chat_token_hash='tokOwner')
        self.assertEqual((mine['already_requested'], mine['quote_request_id']), (True, first['quote_request_id']))
        args = {'product': 'Áo thun in logo', 'quantity': 500, 'unit': 'pcs', 'deadline': '2026-12-15',
                'specs': 'Size S-XL, in 2 màu', 'customer_name': 'Chị Hạnh', 'phone': '0901 234 567', 'company': 'Hanh Co',
                'email': 'hanh@example.com'}                                          # = quote() mặc định, khách nói tiếng Anh
        en = production.execute('production_request_quote', args,
                                ctx(PROD, lang='en', customer_id=cid, chat_token_hash='tokStranger2'))
        self.assert_generic(en, first['quote_request_id'])
        self.assertIn("I've passed your quote request to the team", en['tell_customer'])
        verified = quote(customer_id=cid, chat_token_hash='tokStranger3', phone='+84901234567')
        self.assertEqual(verified['quote_request_id'], first['quote_request_id'])

    # ---------------------------------------------------------------- văn phòng
    def test_consultation_from_another_browser_gets_no_request_number(self):
        cid = f'{OFFICE}:3125550199'
        first = consult(customer_id=cid, chat_token_hash='tokOwner')
        CALLS.clear()
        out = consult(customer_id=cid, chat_token_hash='tokStranger')
        self.assert_generic(out, first['consult_request_id'])
        self.assertEqual(out['status'], 'pending')
        self.assertIn("I've passed your consultation request to the office", out['tell_customer'])
        self.assertIn('Nothing is booked', out['tell_customer'])
        self.assertEqual(len(DB.consultation_requests.docs), 1)
        self.assertEqual(alerts(), [])
        nt = notes()
        self.assertEqual(len(nt), 1)
        self.assertIn(f"consultation request #{first['consult_request_id']}", nt[0][3])   # tiệm Mỹ: tiếng Anh
        mine = consult(customer_id=cid, chat_token_hash='tokOwner')
        self.assertEqual((mine['already_requested'], mine['consult_request_id']), (True, first['consult_request_id']))
        vi = consult(customer_id=cid, chat_token_hash='tokStranger2', lang='vi')
        self.assert_generic(vi, first['consult_request_id'])
        self.assertIn('Em đã chuyển yêu cầu tư vấn cho văn phòng', vi['tell_customer'])

    # ---------------------------------------------------------------- quy tắc chứng minh là chủ
    def test_owns_request_follows_the_owner_filter_rules(self):
        cid = f'{TECH}:0412345678'
        doc = {'phone_key': '+61412345678', 'customer_phone': '+61412345678', 'chat_token_hash': 'tokA',
               'ai_conversation_id': cid}
        own = retail.owns_request
        self.assertTrue(own(doc, ctx(TECH, customer_id=cid, chat_token_hash='tokA')))
        self.assertFalse(own(doc, ctx(TECH, customer_id=cid, chat_token_hash='tokB')))             # trình duyệt khác
        self.assertFalse(own(doc, ctx(TECH, customer_id=cid, chat_token_hash='anon:1')))
        self.assertFalse(own(doc, ctx(TECH, customer_id=f'{TECH}:0499000111', chat_token_hash='tokA',   # máy dùng chung,
                                      contact_phone='0499000111')))                                  # khách kế tiếp
        self.assertTrue(own(doc, ctx(TECH, chat_token_hash='tokA', contact_phone='0412 345 678')))
        self.assertTrue(own(doc, ctx(TECH, chat_token_hash='tokA'), '+61412345678'))                # SĐT gõ trong yêu cầu
        self.assertFalse(own(doc, ctx(TECH, chat_token_hash='tokB'), '+61412345678'))
        self.assertTrue(own(doc, ctx(TECH, chat_token_hash='tokZ', phone='+61412345678')))          # SĐT đã xác minh
        self.assertFalse(own(doc, ctx(TECH, chat_token_hash='tokZ', phone='+61499000111')))
        conv = {'chat_token_hash': 'conv:x', 'ai_conversation_id': f'{TECH}:messenger:9'}
        self.assertTrue(own(conv, ctx(TECH, channel='messenger', customer_id=f'{TECH}:messenger:9', chat_token_hash='conv:x')))
        self.assertTrue(own(conv, ctx(TECH, channel='messenger', customer_id=f'{TECH}:messenger:9', chat_token_hash=None)))
        self.assertFalse(own(conv, ctx(TECH, channel='messenger', customer_id=f'{TECH}:messenger:8',
                                       chat_token_hash='conv:y')))
        self.assertFalse(own(None, ctx(TECH, customer_id=cid, chat_token_hash='tokA')))
        self.assertFalse(own({}, ctx(TECH, chat_token_hash=None)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
