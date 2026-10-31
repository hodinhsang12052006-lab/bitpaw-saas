# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 vòng 8, khu "hazard" (ai_packs/technical.py): LUẬT AN TOÀN THEO CẤU TRÚC (safe-by-construction)
của bộ phân loại nguy hiểm (technical.classify_hazard / hazard_check).

Hợp đồng được kiểm:
  1. SÀN THÔ: họ nguy hiểm được tính trên văn bản GỐC (chữ thường, bản CÓ DẤU + bản BỎ DẤU) TRƯỚC mọi lớp che. 'none' chỉ
     khi văn bản gốc không có từ nào thuộc họ; có từ thuộc họ -> ít nhất 'uncertain', trừ khi MỌI lần nhắc đều nằm trong
     phủ định rõ mà không có gì nhắc lại (-> 'negated'). Cụm không-nguy-hiểm (máy hút mùi, ống khói tạt khói, khói nấu ăn,
     đồ ăn cháy, người hút thuốc, pin báo khói, nước chỉ do ống nước / nước mưa ngoài sân, thành ngữ nóng, tên thiết bị /
     dịch vụ) chỉ chặn 'danger' (trần 'uncertain'), không bao giờ hạ dưới 'uncertain' — kể cả khi mọi lớp che bị thay bằng
     1 lớp che "che hết" (thử nghiệm đối kháng).
  2. Lớp che không giấu từ mà cách đọc có-phủ-định cho thấy ĐANG có ("we don't have a fireplace but smoke is coming into
     the bedroom" = 'danger'; pin báo khói không che báo CO đang kêu).
  3. 'danger' chính xác bắt được các câu bỏ sót trong báo cáo (chích điện, jolt, "bites you when you touch it", insulation
     bubbling, nóng quá / nóng ran / hot + đồ điện, "xet lua" / "chay o cam" / "day dien chay" không dấu, "ống ga ... rò rỉ").
  4. Báo nhầm 'medium' trong báo cáo: tối đa 'uncertain' (không bao giờ khẩn cấp / bảo sơ tán).
  5. Thuộc tính: >= 300 câu sinh ra trộn MỌI từ thuộc họ với MỌI cụm không-nguy-hiểm và cụm bị phủ định -> không bao giờ
     'none'; cụm bị phủ định + câu nguy hiểm ĐANG có -> vẫn 'danger'.
Dùng lại DB giả + stub của test_phase2_request_packs.py (nạp TRƯỚC mọi gói): không import app.py thật, không MongoDB thật
(.env = PRODUCTION), không gọi mạng / API trả phí. Chạy: python scripts/tests/test_phase2_fix8_hazard.py
"""
import importlib
import inspect
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_request_packs as base  # noqa: E402,F401  (cài mongo_client / app / ai_function_tools giả)

from test_phase2_request_packs import CALLS, DB, TECH, ctx, job, seed, technical  # noqa: E402

_RANK = {'none': 0, 'negated': 1, 'uncertain': 2, 'danger': 3}

# ================================================================ báo cáo p2_fix8_hazard — đúng nguyên câu
# critical: nguy hiểm ĐANG có -> 'danger' với đúng loại
CRITICAL_DANGER = (
    ("we don't have a fireplace but smoke is coming into the bedroom", 'smoke'),
    ("haven't used the fireplace in years, now smoke is coming into the house from somewhere", 'smoke'),
    ('no fireplace here, smoke keeps coming into the house', 'smoke'),
    ('Chimney sweep booked for next week. Right now smoke is coming into the kids room and we have no fire going', 'smoke'),
    ('chimney was swept last month. Today smoke is pouring into the hallway, no fire lit', 'smoke'),
    ('smoke is getting into the room and the smoke alarm is not going off, we have a wood heater but its off', 'smoke'),
    ('Nhà không có lò sưởi mà khói tràn vào phòng ngủ', 'smoke'),
    ('khói bay vào nhà từ đâu không biết, nhà có ống khói nhưng không dùng', 'smoke'),
    ('low battery on the smoke alarm in the hall, but the CO alarm in the bedroom is beeping', 'co'),
    ('low battery chirp from smoke alarm and the gas detector is beeping', 'co'),
    ('ống ga sau bếp bị rò rỉ', 'gas'),
    ('o cam xet lua', 'sparks'), ('o cam bi xet', 'sparks'),
    ('chay o cam', 'fire'), ('day dien chay', 'fire'),
    ('Need someone for a quote on downlights. Unrelated but the switch in the hall is getting hot', 'burning'),
    ('ổ cắm nóng quá', 'burning'), ('o cam nong qua', 'burning'), ('phích cắm nóng ran', 'burning'),
    ('công tắc nóng ran, sờ vô phỏng tay', 'burning'),
    ('bị chích điện khi chạm máy giặt', 'shock'), ('bị điện cắn', 'shock'),
    ('touched the shower mixer and felt a jolt', 'shock'), ('got a jolt from the kettle', 'shock'),
    ('the dryer bites you when you touch it', 'shock'), ('my hand went numb when I touched the switch', 'shock'),
    ('the metal railing is live, my dog yelped', 'shock'),
    ('the cable insulation is bubbling', 'burning'),
)
# critical "at least uncertain": ấm (chưa phải nóng) -> người thật kiểm tra, không bảo sơ tán
CRITICAL_AT_LEAST_UNCERTAIN = ('light switch feels warm',)
# medium: báo nhầm khẩn cấp cho cụm không-nguy-hiểm -> tối đa 'uncertain' (sàn thô giữ đúng 'uncertain')
MEDIUM_NOT_DANGER = (
    'range hood doesnt suck the smoke out when cooking', 'the chimney smokes back in when its windy',
    'can you sweep the flue, the wood heater smokes', 'nấu cơm bị cháy khét, nồi cơm hỏng nút',
    'storm water flooding the backyard',
)
# low (quá gấp): việc thường có từ thuộc họ nguy hiểm -> 'uncertain' theo sàn thô (không bao giờ khẩn cấp, không 'none')
LOW_OVER_URGENT = (
    'ice in the freezer is melting', 'tủ lạnh không lạnh, đá chảy hết', 'fridge smells bad, food went off', 'the drain stinks',
    'convert my stove from natural gas to LPG', 'I quit smoking so want to remove the cigarette smell from the aircon',
    "the thermostat flashes 'heat'",
)
# low (bỏ sót mức): câu nói rõ ĐANG có -> nay 'danger'; 1 chữ trơ trọi ('Gas!!', 'fire') giữ 'uncertain'
LOW_UNDER_ESCALATION = (
    ('lửa ở ổ cắm', 'fire'), ('o cam co lua', 'fire'), ('cái bình gas kêu xì', 'gas'),
    ('butane canister in the camping stove is leaking', 'gas'), ('hey mate theres a real strong gas pong in the kitchen', 'gas'),
    ('charred wires behind the stove', 'burning'), ('something is crackling inside the wall near the outlet', 'sparks'),
    ('máy sấy tóc phụt lửa', 'fire'), ('the oven gives a small shock whenever you touch it', 'shock'),
    ('Q: is there any smell of gas? A: yes strong', 'gas'),
    ('chào anh... hôm qua tắm bị tê, hôm nay đứa nhỏ tắm cũng bị nữa', 'shock'),
)
LOW_BARE_WORDS = ('Gas!!', 'fire')

# ================================================================ thành phần cho câu sinh ra (thuộc tính)
FAMILY_TERMS_EN = (
    'gas', 'propane', 'a gas smell', 'smoke', 'smoking', 'a spark', 'sparks', 'arcing', 'crackling', 'buzzing', 'hissing',
    'a flash', 'a bang', 'a burning smell', 'burnt plastic', 'scorch marks', 'melted plastic', 'charred wires', 'a shock',
    'a jolt', 'tingling', 'numbness', 'a strange smell', 'fumes', 'a stench', 'fire', 'flames', 'the alarm going off',
    'the detector beeping', 'flooding near the switchboard', 'water near the power point', 'bubbling insulation',
    'an outlet getting hot', 'a gas pong',
)
FAMILY_TERMS_VI = (
    'mùi gas', 'khí đốt', 'bình ga', 'ống ga', 'mùi', 'mùi khét', 'khói', 'tia lửa', 'xẹt', 'lách tách', 'cháy', 'giật', 'tê tay',
    'chích điện', 'điện cắn', 'lửa', 'rò điện', 'báo động kêu', 'nước gần ổ cắm', 'ổ cắm nóng quá', 'dây điện phồng rộp',
    # không dấu
    'mui gas', 'mui khet', 'boc khoi', 'tia lua', 'xet lua', 'chay o cam', 'day dien chay', 'bi giat', 'chich dien',
    'o cam nong qua', 'ro ri gas', 'bao khoi dang keu', 'khet', 'co lua',
)
CARRIER_EN = 'there is {x} in the kitchen'
CARRIER_VI = 'trong bếp có {x}'
NON_HAZARD_COMPOUNDS = (   # cụm KHÔNG nguy hiểm trong danh sách: chỉ được chặn 'danger'
    'the range hood doesnt suck the smoke out when cooking', 'the chimney smokes back in when its windy',
    'can you sweep the flue', 'the wood heater smokes', 'cooking smoke fills the kitchen', 'I burnt the toast',
    'nấu cơm bị cháy khét', 'my husband smokes outside', 'the smoke alarm battery is low and it chirps',
    'the toilet overflowed and flooded the bathroom', 'storm water flooding the backyard', "it's burning hot today",
    'trời nóng như đổ lửa', 'need my gas heater serviced', 'gas bottle swap', 'máy hút mùi yếu', 'vệ sinh ống khói',
    'đổi bình gas', 'Light globe burnt out', 'ice cream is melting', 'the smoke alarm goes off whenever I cook',
)
NEGATED_COMPOUNDS = (      # cụm không-nguy-hiểm mà ngữ cảnh bị PHỦ ĐỊNH / không dùng
    "we don't have a fireplace", 'no fireplace here', "haven't used the fireplace in years",
    'we have a wood heater but its off', 'nhà không có lò sưởi', 'nhà có ống khói nhưng không dùng', 'we have no fire going',
    "we weren't cooking", 'the smoke is not from cooking', 'không nấu ăn', "we don't smoke", 'the toilet is fine',
)
DANGER_CLAUSES = (         # mỗi câu một mình là 'danger'
    'smoke is coming into the bedroom', 'smoke keeps pouring into the hallway', 'khói tràn vào phòng ngủ',
    'I can smell gas in the kitchen', 'the outlet is sparking', 'the switch in the hall is getting hot', 'ổ cắm nóng quá',
    'o cam xet lua', 'the CO alarm in the bedroom is beeping', 'there is a fire in the roof',
    'water is pouring onto the power point', 'bị chích điện khi chạm máy giặt', 'felt a jolt from the tap',
)
EXPLICIT_NEGATIONS = (     # phủ định RÕ, không nhắc lại -> 'negated' (việc thường + câu dặn an toàn)
    "we don't have a fireplace and there's no smoke", 'No gas smell, no sparks, no smoke', 'o cam khong bi xet',
    'ổ cắm không bị xẹt', 'khong co mui khet', 'No sparks or burning smell when switching on',
    "Heater won't ignite. Customer says no gas smell before or after.", 'Lúc nãy có mùi gas, giờ hết mùi rồi',
    'the heater is not hissing', 'không bị chích điện', 'no jolt, no tingling',
)
HOMOGRAPHS_NONE = (        # bản bỏ dấu trùng từ thuộc họ nhưng nghĩa KHÁC / không có từ nào -> 'none'
    'dây điện chạy âm tường', 'day dien chay am tuong', 'máy giặt hỏng', 'thay mũi khoan', 'thay mui khoan',
    'ra khỏi nhà tắt điện', 'xem xét giúp em', 'nhà ga gần đây', 'bé bị té', 'đồng hồ điện chạy nhanh',
    'dong ho dien chay nhanh', 'o cam am tuong', 'khoi dong may khong duoc', 'xì gà', 'may lanh chay on',
    'cần lắp thêm ổ cắm', 'quat tran chay cham', 'nồi cơm điện bị hư',
)
UNACCENTED_FAMILY = (      # gõ không dấu: ít nhất 'uncertain'
    'xet lua', 'chay o cam', 'day dien chay', 'chich dien', 'o cam nong qua', 'ong ga bi ro ri', 'bao khoi dang keu', 'khet',
    'tia lua', 'bi giat', 'lap bao khoi', 've sinh ong khoi', 'bep ga bi xi', 'mui la', 'te tay',
)


def alerts():
    return [c for c in CALLS if c[0] == 'alert']


def _floor(text):
    """Sàn thô (bước 0) của 1 câu: 'none' | 'negated' | 'uncertain'."""
    raw = technical._hz_raw_scan(technical._hz_norm(text))
    if not raw:
        return 'none'
    return 'negated' if set(raw.values()) == {'negated'} else 'uncertain'


def _generated():
    """>= 300 câu: MỌI từ thuộc họ (trong câu mang) x MỌI cụm không-nguy-hiểm và cụm bị phủ định (thứ tự và cách nối
    xoay vòng theo cặp)."""
    joins = (', ', '. ', ' but ')
    out = []
    compounds = NON_HAZARD_COMPOUNDS + NEGATED_COMPOUNDS
    for terms, carrier in ((FAMILY_TERMS_EN, CARRIER_EN), (FAMILY_TERMS_VI, CARRIER_VI)):
        for i, x in enumerate(terms):
            clause = carrier.format(x=x)
            for j, c in enumerate(compounds):
                sep = joins[(i + j) % 3]
                out.append(f'{c}{sep}{clause}' if (i + j) % 2 else f'{clause}{sep}{c}')
    return out


# ================================================================ 1. từng câu trong báo cáo
class ReviewItemTests(unittest.TestCase):
    def test_critical_items_are_emergencies_with_the_right_kind(self):
        for txt, kind in CRITICAL_DANGER:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual(verdict, 'danger', states)
                self.assertEqual(states.get(kind), 'present', states)
                self.assertTrue(technical.is_emergency(txt))

    def test_warm_switch_is_a_person_check_not_an_emergency(self):
        for txt in CRITICAL_AT_LEAST_UNCERTAIN:
            verdict, states = technical.hazard_check(txt)
            self.assertEqual(verdict, 'uncertain', states)
            self.assertTrue(all(k.startswith('possible_') for k in states), states)

    def test_medium_over_alerts_are_at_most_uncertain(self):
        for txt in MEDIUM_NOT_DANGER:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual(verdict, 'uncertain', states)   # trần 'uncertain' do cụm, sàn 'uncertain' do từ thuộc họ
                self.assertFalse(technical.is_emergency(txt))
                self.assertNotIn('present', states.values())

    def test_low_over_urgent_jobs_stay_uncertain_by_the_raw_floor(self):
        for txt in LOW_OVER_URGENT:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual(verdict, 'uncertain', states)
                self.assertEqual(_floor(txt), 'uncertain')
                self.assertNotIn('present', states.values())

    def test_low_under_escalations_that_are_clearly_current_are_emergencies(self):
        for txt, kind in LOW_UNDER_ESCALATION:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual((verdict, states.get(kind)), ('danger', 'present'), states)
        for txt in LOW_BARE_WORDS:   # 1 chữ trơ trọi: người thật gọi kiểm tra, không bảo sơ tán
            self.assertEqual(technical.classify_hazard(txt), 'uncertain', txt)

    def test_item_file_variants(self):
        self.assertEqual(technical.classify_hazard('range hood doesn\'t suck the smoke out when cooking'), 'uncertain')
        self.assertEqual(technical.classify_hazard('the chimney is not smoking'), 'negated')
        self.assertEqual(technical.classify_hazard('the outlet is hot'), 'danger')
        self.assertEqual(technical.classify_hazard('the outlet is not hot'), 'none')   # không có từ thuộc họ nào
        self.assertEqual(technical.classify_hazard('ổ cắm bình nóng lạnh bị lỏng'), 'none')   # "nóng lạnh" = máy nước nóng
        self.assertEqual(technical.classify_hazard('công tắc phải đấu vào dây nóng'), 'none')   # "dây nóng" = dây pha
        self.assertEqual(technical.classify_hazard('the electric fence is live'), 'none')
        self.assertEqual(technical.classify_hazard('the toilet overflowed and the hallway power point is wet'), 'danger')
        self.assertEqual(technical.classify_hazard('storm water is flooding into the house'), 'danger')   # trong nhà
        self.assertEqual(technical.classify_hazard('storm water flooding the backyard near the power box'), 'danger')
        self.assertEqual(technical.classify_hazard('nồi cơm điện bị cháy khét'), 'danger')   # thiết bị cháy, không phải đồ ăn


# ================================================================ 2. luật an toàn theo cấu trúc
class SafeByConstructionTests(unittest.TestCase):
    def test_generated_sentences_mixing_every_family_term_with_every_compound_are_never_none(self):
        rows = _generated()
        self.assertGreaterEqual(len(rows), 300)
        for txt in rows:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertNotEqual(verdict, 'none', states)
                self.assertTrue(states)

    def test_every_family_term_alone_and_in_a_carrier_is_at_least_uncertain(self):
        for terms, carrier in ((FAMILY_TERMS_EN, CARRIER_EN), (FAMILY_TERMS_VI, CARRIER_VI)):
            for x in terms:
                for txt in (x, carrier.format(x=x)):
                    with self.subTest(txt=txt):
                        self.assertIn(technical.classify_hazard(txt), ('uncertain', 'danger'))
                        self.assertEqual(_floor(txt), 'uncertain')

    def test_negated_compound_never_hides_a_current_hazard(self):
        n = 0
        for d in DANGER_CLAUSES:
            self.assertEqual(technical.classify_hazard(d), 'danger', d)
            for c in NEGATED_COMPOUNDS:
                for sep in (', ', '. ', ' but '):
                    txt = f'{c}{sep}{d}'
                    n += 1
                    with self.subTest(txt=txt):
                        self.assertEqual(technical.classify_hazard(txt), 'danger', technical.hazard_check(txt)[1])
        self.assertGreaterEqual(n, 300)

    def test_listed_compounds_alone_never_make_an_emergency_and_never_hide_their_family_term(self):
        for c in NON_HAZARD_COMPOUNDS:
            with self.subTest(txt=c):
                verdict = technical.classify_hazard(c)
                self.assertNotEqual(verdict, 'danger')
                self.assertGreaterEqual(_RANK[verdict], _RANK[_floor(c)])
                self.assertEqual(verdict == 'none', _floor(c) == 'none')   # "can you sweep the flue": không có từ thuộc họ

    def test_verdict_is_never_below_the_raw_floor_and_none_only_without_family_terms(self):
        import test_phase2_fix3_requests3 as r3
        import test_phase2_fix5_emergency5 as e5
        n7 = importlib.import_module('test_phase2_fix7_hazard-net')
        rows = ([t for t, _ in r3.TABLE] + [t for t, _ in e5.BRIEF] + [t for t, _ in e5.NEW] + list(n7.NET_NONE)
                + list(n7.NET_UNCERTAIN) + list(n7.NET_NEGATED) + list(n7.CHECKER_OVER_ALERT) + [t for t, _ in CRITICAL_DANGER]
                + list(MEDIUM_NOT_DANGER) + list(LOW_OVER_URGENT) + list(EXPLICIT_NEGATIONS) + list(HOMOGRAPHS_NONE)
                + _generated()[::7])
        self.assertGreaterEqual(len(rows), 800)
        for txt in rows:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                floor = _floor(txt)
                self.assertGreaterEqual(_RANK[verdict], _RANK[floor], states)
                self.assertEqual(verdict == 'none', floor == 'none', states)
                if verdict == 'none':
                    self.assertEqual(states, {})
                if verdict == 'negated':
                    self.assertEqual(floor, 'negated')
                    self.assertEqual(set(states.values()), {'negated'})

    def test_an_adversarial_mask_that_hides_everything_cannot_lower_the_verdict(self):
        # mọi lớp che cụm không-nguy-hiểm bị thay bằng 1 regex che MỌI chữ: bước 1-5 không còn thấy gì, nhưng kết luận vẫn
        # >= sàn thô (bước 0 tính trên văn bản gốc, trước mọi lớp che) và không bao giờ lên 'danger'
        hide = re.compile(r"[^\W_]+")
        names = ('_HZ_EXCLUDE', '_HZ_PERSON_SMOKE', '_HZ_COOK_SMOKE', '_HZ_HOOD_WEAK', '_HZ_FOOD_BURNT', '_HZ_VENT_SMOKE',
                 '_HZ_HEAT', '_HZ_NET_SAFE')
        rows = [t for t, _ in CRITICAL_DANGER] + list(MEDIUM_NOT_DANGER) + list(LOW_OVER_URGENT) + _generated()[::11]
        expected = {t: _floor(t) for t in rows}
        with mock.patch.multiple(technical, **{n: hide for n in names}):
            for txt in rows:
                with self.subTest(txt=txt):
                    verdict, states = technical.hazard_check(txt)
                    self.assertNotEqual(verdict, 'none', states)
                    self.assertGreaterEqual(_RANK[verdict], _RANK[expected[txt]], states)
        self.assertGreaterEqual(len(rows), 150)

    def test_explicit_negations_stay_negated(self):
        for txt in EXPLICIT_NEGATIONS:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual(verdict, 'negated', states)
                self.assertEqual(_floor(txt), 'negated')

    def test_homographs_and_plain_jobs_are_none(self):
        for txt in HOMOGRAPHS_NONE:
            with self.subTest(txt=txt):
                self.assertEqual(technical.hazard_check(txt), ('none', {}))
                self.assertEqual(_floor(txt), 'none')

    def test_unaccented_family_terms_reach_the_floor(self):
        for txt in UNACCENTED_FAMILY:
            with self.subTest(txt=txt):
                self.assertIn(technical.classify_hazard(txt), ('uncertain', 'danger'))
                self.assertEqual(_floor(txt), 'uncertain')

    def test_raw_scan_reads_both_the_accented_and_the_folded_copy(self):
        self.assertEqual(technical._hz_fold('cháy ổ cắm, đèn'), 'chay o cam, den')
        for s in ('Nhà không có lò sưởi mà khói tràn vào phòng ngủ', 'ổ cắm nóng quá', 'xì gà'):
            self.assertEqual(len(technical._hz_fold(technical._hz_norm(s))), len(technical._hz_norm(s)))
        self.assertIn('sparks', technical._hz_raw_scan('o cam bị xet lua'))   # gõ lẫn: bản bỏ dấu vẫn thấy
        self.assertEqual(technical._hz_raw_scan('dây điện chạy dọc tường'), {})   # 'chạy' có dấu = chạy, không phải cháy


# ================================================================ 3. ngữ cảnh cả tin nhắn chỉ tính khi được nhắc KHẲNG ĐỊNH
class ContextLivenessTests(unittest.TestCase):
    def test_vent_context_is_negation_and_idle_aware(self):
        live = technical._hz_ctx_live
        for txt in ('the chimney is blocked', 'we have a fireplace', 'Ống khói lò sưởi bị nghẹt', 'can you sweep the flue',
                    'Chimney sweep booked for next week'):
            self.assertTrue(live(technical._hz_norm(txt), technical._HZ_VENT_CTX), txt)
        for txt in ("we don't have a fireplace", 'no fireplace here', "haven't used the fireplace in years",
                    'we have a wood heater but its off', 'nhà không có lò sưởi', 'nhà có ống khói nhưng không dùng',
                    "it's not the chimney", 'the fireplace hasn\'t been used'):
            self.assertFalse(live(technical._hz_norm(txt), technical._HZ_VENT_CTX), txt)
        self.assertTrue(technical._HZ_NO_FIRE.search('we have no fire going'))
        self.assertTrue(technical._HZ_NO_FIRE.search('no fire lit'))
        self.assertTrue(technical._HZ_UNKNOWN_SRC.search('khói bay vào nhà từ đâu không biết'))
        self.assertTrue(technical._HZ_UNKNOWN_SRC.search('smoke is coming into the house from somewhere'))
        self.assertFalse(technical._HZ_CTX_NEG_BEFORE.search('thông '))   # 'thông' chứa 'hông' nhưng không phải phủ định

    def test_battery_only_covers_the_alarm_kind_it_is_said_about(self):
        kinds = technical._hz_battery_kinds
        self.assertEqual(kinds('low battery on the smoke alarm in the hall, but the co alarm in the bedroom is beeping'),
                         {'smoke'})
        self.assertEqual(kinds('the smoke alarm keeps chirping. i think the battery is low'), {'*'})
        self.assertEqual(kinds('the co alarm is beeping'), set())
        self.assertTrue(technical._hz_battery_covers({'smoke'}, 'smoke alarm keeps beeping'))
        self.assertFalse(technical._hz_battery_covers({'smoke'}, 'co alarm in the bedroom is beeping'))
        self.assertEqual(technical.classify_hazard('Smoke alarm battery low, keeps beeping'), 'uncertain')
        self.assertEqual(technical.classify_hazard('the smoke alarm battery is low but the gas alarm is going off'), 'danger')

    def test_masks_with_a_negation_inside_or_right_before_are_not_applied(self):
        self.assertEqual(technical.classify_hazard('the smoke is not from cooking, it is coming into the bedroom'), 'danger')
        self.assertEqual(technical.classify_hazard('không nấu ăn mà khói tràn vào phòng'), 'danger')
        self.assertEqual(technical.classify_hazard("it's not the fireplace, smoke is coming into the room"), 'danger')
        # lò sưởi được nhắc KHẲNG ĐỊNH (đang có, "never smokes" = bình thường không khói): cụm tạt khói chỉ chặn 'danger'
        self.assertEqual(technical.classify_hazard('the fireplace never smokes, but now smoke is coming into the room'),
                         'uncertain')


# ================================================================ 4. qua công cụ thật
class Fix8JobToolTests(unittest.TestCase):
    def setUp(self):
        seed()
        self.cid = f'{TECH}:0412345678'
        DB.bot_customers.insert_one({'id': self.cid})

    def run_job(self, problem, i):
        DB.bot_customers.update_one({'id': self.cid}, {'$set': {'needs_human': None, 'ai_paused': None,
                                                                 'handoff_urgent': None}})
        CALLS.clear()
        return job(customer_id=self.cid, args={'problem': problem, 'address': f'{i + 1} Smith St, Fitzroy VIC'})

    def test_critical_items_create_emergencies(self):
        for i, (problem, _) in enumerate(CRITICAL_DANGER[:10] + CRITICAL_DANGER[-6:]):
            with self.subTest(problem=problem):
                out = self.run_job(problem, i)
                self.assertEqual(out['urgency'], 'emergency')
                self.assertIn('somewhere safe', out['tell_customer'])
                self.assertIn('000', out['tell_customer'])
                self.assertEqual([a[4] for a in alerts()], ['technical_emergency'])
                bc = DB.bot_customers.find_one({'id': self.cid})
                self.assertTrue(bc['needs_human'] and bc['handoff_urgent'] and bc['ai_paused'])

    def test_listed_compounds_are_urgent_person_checks_never_emergencies(self):
        for i, problem in enumerate(MEDIUM_NOT_DANGER + LOW_OVER_URGENT[:3]):
            with self.subTest(problem=problem):
                out = self.run_job(problem, 30 + i)
                self.assertEqual(out['urgency'], 'urgent')
                self.assertTrue(out['possible_hazard'])
                tell = out['tell_customer']
                self.assertIn('right now, leave the area and call 000', tell)
                for evacuate in ('somewhere safe', 'get everyone', 'If anyone is in danger'):
                    self.assertNotIn(evacuate, tell)
                self.assertEqual([a[4] for a in alerts()], ['technical_hazard_check'])
                self.assertEqual(DB.tasks.find_one({'id': out['job_id']})['urgency'], 'urgent')

    def test_explicit_negation_is_a_normal_job_with_the_safety_tip(self):
        for i, problem in enumerate(EXPLICIT_NEGATIONS[:5]):
            with self.subTest(problem=problem):
                out = self.run_job(problem, 60 + i)
                self.assertEqual(out['urgency'], 'normal')
                self.assertIn('call 000', out['safety_tip'])
                self.assertEqual([a[4] for a in alerts()], ['technical_job'])

    def test_vi_shop_gets_an_emergency_for_a_negated_heater_context(self):
        DB.businesses.insert_one({'id': 'tech_vn8', 'name': 'Điện lạnh Q8', 'currency': 'VND', 'country': 'VN',
                                  'industry_code': 'technical'})
        out = technical.execute('technical_request_job', {'customer_name': 'Chị Lan', 'phone': '0901 234 568',
                                                          'address': '8 Lê Lợi, Quận 1, TP HCM',
                                                          'problem': 'Nhà không có lò sưởi mà khói tràn vào phòng ngủ'},
                                ctx('tech_vn8', lang='vi'))
        self.assertEqual(out['urgency'], 'emergency')
        self.assertIn('114', out['tell_customer'])


# ================================================================ 5. tài liệu ở đầu bộ phân loại + thứ tự trong mã
class DocumentationTests(unittest.TestCase):
    def test_rule_is_documented_at_the_top_of_the_classifier(self):
        src = open(technical.__file__, encoding='utf-8').read()
        head = src[src.index('# Phát hiện NGUY HIỂM'):src.index('_HZ_ALARM_PRE = (')]
        for needle in ('LUẬT AN TOÀN THEO CẤU TRÚC', 'SAFE-BY-CONSTRUCTION', '_hz_raw_scan', '_hz_fold', '_HZ_FOLD',
                       '_hz_ctx_live', '_hz_battery_kinds', '_hz_mask', "'none'", 'TRƯỚC MỌI lớp che', "trần 'uncertain'",
                       "KHÔNG BAO GIỜ hạ dưới 'uncertain'", 'gas heater service'):
            self.assertIn(needle, head)

    def test_raw_floor_is_computed_before_any_mask_and_applied_last(self):
        code = inspect.getsource(technical.hazard_check)
        raw_at = code.index('_hz_raw_scan(')
        for mask in ('_hz_mask(', '_HZ_SMELL_IT', '_hz_mask_heat(', '_hz_join_lists('):
            self.assertLess(raw_at, code.index(mask), mask)
        self.assertGreater(code.index('for c, v in raw.items()'), code.index("_hz_scan(t, net)"))
        self.assertNotIn('_hz_mask', inspect.getsource(technical._hz_raw_scan))
        self.assertNotIn('_HZ_NET_SAFE', inspect.getsource(technical._hz_raw_scan))

    def test_crlf_line_endings_kept(self):
        raw = open(technical.__file__, 'rb').read()
        self.assertEqual(raw.count(b'\r\n'), raw.count(b'\n'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
