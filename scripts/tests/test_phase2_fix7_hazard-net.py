# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 vòng 7, khu "hazard-net" (ai_packs/technical.py): bộ phân loại NGUY HIỂM chính xác + LỚP LƯỚI
AN TOÀN chạy sau nó (technical.classify_hazard / hazard_check).

Hợp đồng được kiểm:
  - 29 câu NGUY HIỂM ĐANG xảy ra mà checker độc lập tìm thấy bị trả 'none' (đúng nguyên câu) nay là 'danger' (từ vựng /
    khoảng cách: reeks / whiff, "smells a lot like gas", propane smell, khí đốt, buzzing / crackling của tủ điện, "and" tách
    chủ ngữ khỏi vị ngữ, "wires behind the tv are melting", burn marks, "bị giật" / "tê tê", "day dien bi chay"...);
  - câu báo NHẦM (người hút thuốc, ống khói / lò sưởi / wood heater tạt khói vào phòng, ngập đã khô) KHÔNG còn 'danger';
  - LƯỚI AN TOÀN: tin nhắn có BẤT KỲ từ nào thuộc họ nguy hiểm (gas / smell / spark / smoke / burn / shock / nước + đồ
    điện / alarm going off / fire, mọi ngôn ngữ, hoa thường, có dấu hay không dấu) mà không được giải quyết sạch là
    'negated' và không nằm trong cụm không-nguy-hiểm trong danh sách -> ít nhất 'uncertain' (việc GẤP + chuyển người thật
    + báo chủ + câu dặn an toàn có điều kiện, không bảo sơ tán); lưới không bao giờ tự lên 'danger'; 'none' chỉ khi không
    còn từ nào thuộc họ nguy hiểm.
Dùng lại DB giả + stub của test_phase2_request_packs.py (nạp TRƯỚC mọi gói): không import app.py thật, không MongoDB thật
(.env = PRODUCTION), không gọi mạng / API trả phí. Chạy: python scripts/tests/test_phase2_fix7_hazard-net.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_request_packs as base  # noqa: E402,F401  (cài mongo_client / app / ai_function_tools giả)

from test_phase2_request_packs import CALLS, DB, TECH, job, seed, technical  # noqa: E402

# ================================================================ báo cáo checker — đúng nguyên câu
# 29 câu "critical": nguy hiểm ĐANG / VỪA xảy ra (mọi câu đều nói rõ hiện tại) -> 'danger'
CHECKER_PRESENT = (
    ('my gas bottle on the bbq is hissing and wont stop', 'gas'),
    ('Our gas heater smells weird, like gas, kids are home', 'gas'),
    ('The whole unit reeks of gas', 'gas'),
    ('I turned the gas off at the meter but I can still smell it', 'gas'),
    ('Hello, booking for tomorrow arvo if possible. Actually wait, the smell is back - definitely gas, coming from the oven. '
     'Should I still wait till tomorrow?', 'gas'),
    ('I can get a whiff of gas in the hallway', 'gas'),
    ('smells a lot like gas in here', 'gas'),
    ('smells kind of like natural gas near the water heater', 'gas'),
    ("there's a faint gas-like smell by the stove", 'gas'),
    ('propane smell in the camper', 'gas'),
    ('strong smell of propane near the bbq', 'gas'),
    ('I smell something like gas', 'gas'),
    ('hissing sound from the stove and a smell', 'gas'),
    ('The panel is crackling and buzzing', 'sparks'),
    ('the switchboard is humming and crackling', 'sparks'),
    ('the light switch is buzzing and hot', 'sparks'),
    ('the outlet is buzzing loudly and warm', 'sparks'),
    ('wires behind the tv are melting', 'burning'),
    ('black marks and melted plastic on the power point', 'burning'),
    ('socket has burn marks and smells', 'burning'),
    ('Cái plug của máy lạnh bị melted', 'burning'),
    ('Dây điện ngoài cột bị cháy', 'fire'),
    ('day dien bi chay', 'fire'),
    ('bếp bị cháy', 'fire'),
    ('mùi khí đốt nồng nặc', 'gas'),
    ('Chào shop, em ở Q7, nhà em xài máy nước nóng Ariston được 5 năm rồi, dạo này tắm thấy hơi tê tê khi chạm vào vòi, '
     'hồi nãy con em la lên là bị giật, em sợ quá, nhờ bên mình qua kiểm tra giúp em liền nha', 'shock'),
    ('mẹ em vừa bị giật khi cắm nồi cơm', 'shock'),
    ('chạm vô cửa tủ lạnh thấy tê tê', 'shock'),
    ('tu lanh bi giat', 'shock'),
)
# 8 câu "medium" (việc thường bị bảo gọi cấp cứu) + 1 câu "low" (ngập đã khô) -> KHÔNG 'danger'
CHECKER_OVER_ALERT = (
    'we smoke outside, the screen door is broken',
    'we smoke on the balcony, the door lock is broken',
    'My husband smokes, the ceiling is yellow, can you paint',
    'chimney is blocked, smoke comes into the living room when we light the fire',
    'the fireplace smokes into the room',
    'wood heater is smoking into the room, needs a flue clean',
    'Ống khói lò sưởi bị nghẹt, khói tạt ngược vào nhà',
    'khói tạt ngược từ ống khói vào nhà, cần vệ sinh ống khói',
    'basement flooded last week, all dried out now, need dehumidifier installed',
)

# ================================================================ câu MỚI
PRESENT_NEW = (   # biến thể cùng loại lỗi (từ vựng / khoảng cách / "and" / không dấu) -> 'danger'
    'the kitchen reeks of propane', 'got a whiff of lpg near the caravan', 'it smells sort of like gas in the laundry',
    'smells really strongly of natural gas', 'butane smell from the camping stove', 'lpg-like odour near the bottle',
    'the gas cylinder behind the shed is leaking', 'the cooktop keeps hissing even when off',
    'hissing noise near the burner', 'the breaker is buzzing', 'the power point buzzes when I plug the kettle in',
    'buzzing sound from the light switch', 'the fuse box is buzzing and warm', 'the outlet in the hallway is crackling',
    'cable behind the fridge is melting', 'melted plastic around the socket', 'burn marks on the power board',
    'the switch has black marks', 'the plug in the bedroom is crackling and smells',
    'ổ cắm ngoài ban công bị cháy', 'dây điện trong trần nhà đang cháy', 'nhà bếp bị cháy', 'o cam bi chay',
    'cong tac ngoai hien bi chay', 'mùi khí đốt trong bếp', 'phích cắm nồi cơm bị chảy', 'bé nhà em vừa bị giật ở ổ cắm',
    'sờ vô vỏ máy giặt thấy tê tê', 'tắm thấy tê tê khi chạm vòi sen', 'may giat bi giat',
    "There's a smell in the hallway - definitely gas", 'Something smells off, like gas, near the heater',
    'The gas company left but I can still smell it',
)
NET_UNCERTAIN = (   # CHỈ lưới an toàn thấy (không có cụm chính xác) -> 'uncertain', không phải 'danger'
    'the fridge is buzzing', "there's a strange smell in the kitchen", 'I turned the gas off', 'heard a bang upstairs',
    'something is crackling', 'the heater makes a hissing noise', 'the alarm is going off', 'detector keeps beeping',
    'fire', 'fire?', 'the tv is flashing', 'a weird odour in the bedroom', 'fumes in the garage',
    'something stinks in the laundry', 'the gas heater is leaking', 'bếp từ bị cháy mạch', 'tủ lạnh kêu rè',
    'mùi lạ trong bếp', 'hôi quá anh ơi', 'nghe tiếng xì xì sau tủ', 'có lửa', 'tê tê', 'giật giật ở tay nắm cửa',
    'mui la trong phong', 'khi dot', 'te tay', 'co lua', 'nong chay', 'ổ cắm kêu rè và nóng', 'báo động kêu liên tục',
    'fridge leaking water, power point behind it', 'dột ngay đèn phòng khách',
    'No gas smell. The fridge is buzzing', 'Không có mùi gas, tủ lạnh kêu rè', 'there was a weird smell last week',
    'Is there a smell?', 'what if it buzzes?', 'GAS', 'Propane', 'Mùi', 'XẸT ở đâu đó',
)
NET_NEGATED = (   # từ của lưới bị phủ định rõ / đã hết -> 'negated' (việc thường + câu dặn an toàn)
    'the outlet is not crackling', 'No smell or buzzing', 'No gas smell, buzzing or crackling',
    'There was a weird smell, it is gone now', 'the gas heater is not hissing', 'không bị giật', 'dây điện không bị cháy',
    'no strange smell at all', 'không có mùi lạ', 'Không có mùi gas và tia lửa',
)
NET_NONE = (   # cụm KHÔNG nguy hiểm trong danh sách (_HZ_NET_SAFE / _HZ_EXCLUDE...) -> 'none'
    'Need my gas heater serviced before winter', 'Gas bottle delivery', 'Convert BBQ to natural gas',
    'Is the hot water gas or electric?', 'aircon needs a regas', 'nạp gas máy lạnh', 'máy lạnh thiếu gas',
    'đổi bình gas giúp em', 'we ran out of gas for the bbq', 'Need a gas safety certificate for my rental',
    'I want the gas meter moved for a renovation', 'smells fine, gas heater works', 'Aircon smells musty when it turns on',
    'Bồn cầu có mùi hôi', 'may lanh co mui hoi', 'Máy lạnh có mùi ẩm mốc', 'the speaker is crackling', 'loa bị rè',
    'Intercom buzzer broken', 'Coffee machine steam wand hissing a lot', 'Solar inverter showing an error light flashing',
    'the light keeps flashing an error code', 'the pipes bang when I turn off the tap',
    'The washing machine bangs during the spin cycle', 'Kettle element burnt out', 'Light globe burnt out in the hallway',
    'ice cream is melting, freezer not cold', "There's a burning sensation in my eyes from the cleaning products lol",
    'Máy lạnh bị chảy nước, cần thợ', 'trời nắng cháy da, cần lắp máy lạnh', 'Trời nóng như đổ lửa mà máy lạnh không mát',
    'Tivi bị giật hình', 'Wifi bị giật lag', 'em giật mình', 'bồn cầu không giật nước', 'I was shocked by the price of the quote',
    'Ceiling has water stains near the downlight', 'Aircon is dripping water inside', 'Need a fan installed in the wet area',
    'The security alarm keeps going off at night', 'car alarm going off outside', 'báo trộm kêu liên tục',
    'fire up the bbq', 'the gas log fire needs a service', 'His cooking is fire lol, anyway the oven light is broken',
    'Bếp gas đánh lửa không lên', 'Pest control smoke treatment', 'Paint the ceiling, it\'s yellow from cigarettes',
    'the previous tenants smoked inside, walls are stained', 'he quit smoking last year',
    "We had smoke from cooking and the alarm went off, it's fine now, but the hood needs fixing",
    'Sơn lại tường bị ố vàng do khói thuốc', 'Wood heater flue needs cleaning', 'Chimney sweep and inspection',
    'Chimney clean to prevent a chimney fire',
)
STILL_DANGER = (   # cụm không-nguy-hiểm KHÔNG được che mất nguy hiểm thật bên cạnh
    'I smell smoke in the hallway', 'they smoke when I plug in the heater', 'The outlets, they smoke when I plug in',
    'Smoke coming into the room from the outlet, we have a fireplace', 'we have a fireplace but there is smoke in the house',
    'we smoke outside but now the power point is sparking', 'chạm vào tivi bị giật', 'khách báo khói ở ổ cắm',
    'khách báo cháy ổ điện', 'my gas heater smells like gas', 'water near the power point',
    'chimney fire, smoke is pouring into the room', 'the flue is blocked and there is a fire in the roof',
)
# Mọi từ thuộc HỌ nguy hiểm (mọi dạng) trong câu trung tính -> ít nhất 'uncertain'
FAMILY_EN = ('gas', 'GAS', 'Propane', 'LPG', 'butane', 'smell', 'smells', 'smelly', 'odour', 'odor', 'reek', 'whiff', 'stink',
             'stench', 'fumes', 'spark', 'sparks', 'arc', 'arcing', 'crackle', 'crackling', 'buzz', 'buzzing', 'hiss',
             'hissing', 'flash', 'flashed', 'bang', 'banged', 'smoke', 'smoking', 'smoky', 'burn', 'burnt', 'burning',
             'scorch', 'scorched', 'melt', 'melted', 'melting', 'charred', 'shock', 'shocked', 'tingle', 'tingling',
             'electrocuted', 'zapped', 'fire', 'FIRE', 'alarm going off', 'detector beeping', 'siren wailing')
FAMILY_VI = ('gas', 'khí đốt', 'bình ga', 'mùi', 'hôi', 'khét', 'tia lửa', 'xẹt', 'lách tách', 'rè', 'xì', 'khói', 'bốc khói',
             'cháy', 'chảy', 'nóng chảy', 'giật', 'tê', 'rò điện', 'lửa', 'báo động kêu', 'đầu báo hú', 'KHÓI', 'Mùi',
             'khi dot', 'mui', 'khet', 'lach tach', 'boc khoi', 'bi chay', 'nong chay', 'bi giat', 'ro dien', 'te tay', 'co lua')
CARRIERS_EN = ('{x}', 'there is some {x} in the kitchen', 'I noticed {x} near the hallway',
               'something {x} upstairs, can you come', 'Hi, quick one: {x}?', 'my tenant mentioned {x} this morning')
CARRIERS_VI = ('{x}', 'trong bếp có {x}', 'nhà em thấy {x} ở phòng khách', 'hình như có {x}, anh qua xem giúp',
               'chị ơi {x} nè', 'khách báo {x} sáng nay')
WATER_ELEC = ('water and the power point', 'there is water by the switchboard area', 'flooding, the lights are on',
              'wet floor where the extension cord is', 'leak above the downlight', 'nước chỗ ổ cắm', 'ngập sân, tủ điện ngoài sân',
              'ướt hết rồi, công tắc gần đó', 'nuoc o cho o cam', 'dột ngay đèn phòng khách')
_VI_CHARS = 'ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ'


def alerts():
    return [c for c in CALLS if c[0] == 'alert']


def _net_only(states):
    return bool(states) and all(k.startswith('possible_') for k in states)


# ================================================================ 1. bảng câu
class CheckerPhraseTests(unittest.TestCase):
    def test_every_checker_present_hazard_is_danger_with_the_right_kind(self):
        self.assertEqual(len(CHECKER_PRESENT), 29)
        for txt, kind in CHECKER_PRESENT:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual(verdict, 'danger', states)
                self.assertEqual(states.get(kind), 'present', states)
                self.assertTrue(technical.is_emergency(txt))

    def test_checker_over_alerts_are_not_emergencies(self):
        for txt in CHECKER_OVER_ALERT:
            with self.subTest(txt=txt):
                self.assertNotEqual(technical.classify_hazard(txt), 'danger')
                self.assertFalse(technical.is_emergency(txt))
        for txt in CHECKER_OVER_ALERT[:8]:   # cụm không-nguy-hiểm trong danh sách: việc thường, không còn từ nào
            self.assertEqual(technical.hazard_check(txt), ('none', {}), txt)
        self.assertEqual(technical.hazard_check(CHECKER_OVER_ALERT[8]), ('negated', {'water': 'negated'}))   # đã khô

    def test_new_present_phrasings_are_danger(self):
        for txt in PRESENT_NEW + STILL_DANGER:
            with self.subTest(txt=txt):
                self.assertEqual(technical.classify_hazard(txt), 'danger', technical.hazard_check(txt)[1])

    def test_table_size_languages_and_no_overlap(self):
        import test_phase2_fix3_requests3 as r3
        import test_phase2_fix5_emergency5 as e5
        rows = ([t for t, _ in CHECKER_PRESENT] + list(CHECKER_OVER_ALERT) + list(PRESENT_NEW) + list(NET_UNCERTAIN)
                + list(NET_NEGATED) + list(NET_NONE) + list(STILL_DANGER))
        self.assertEqual(len(set(rows)), len(rows), 'duplicate rows')
        old = {t for t, _ in r3.TABLE} | {t for t, _ in e5.BRIEF} | {t for t, _ in e5.NEW}
        self.assertFalse(set(rows) & old, 'rows already in an earlier table')
        self.assertGreaterEqual(len(rows), 180)
        self.assertGreaterEqual(sum(any(ch in t.lower() for ch in _VI_CHARS) for t in rows), 45)


# ================================================================ 2. lưới an toàn
class SafetyNetTests(unittest.TestCase):
    def test_net_only_mentions_are_uncertain_never_danger(self):
        for txt in NET_UNCERTAIN:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual(verdict, 'uncertain', states)
                self.assertFalse(technical.is_emergency(txt))
                self.assertTrue(any(k.startswith('possible_') for k in states), states)
                self.assertNotIn('present', states.values())

    def test_net_terms_with_an_explicit_negation_are_negated(self):
        for txt in NET_NEGATED:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual(verdict, 'negated', states)
                self.assertEqual(set(states.values()), {'negated'})

    def test_listed_non_hazard_compounds_are_none_with_no_states(self):
        for txt in NET_NONE:
            with self.subTest(txt=txt):
                self.assertEqual(technical.hazard_check(txt), ('none', {}))

    def test_every_family_term_in_every_form_is_at_least_uncertain(self):
        n = 0
        for words, carriers in ((FAMILY_EN, CARRIERS_EN), (FAMILY_VI, CARRIERS_VI)):
            for w in words:
                for c in carriers:
                    txt = c.format(x=w)
                    n += 1
                    with self.subTest(txt=txt):
                        self.assertIn(technical.classify_hazard(txt), ('danger', 'uncertain'),
                                      technical.hazard_check(txt)[1])
        for txt in WATER_ELEC:   # nước / ngập + đồ điện trong cùng tin nhắn
            with self.subTest(txt=txt):
                self.assertIn(technical.classify_hazard(txt), ('danger', 'uncertain'))
        self.assertGreaterEqual(n, 500)

    def test_water_without_anything_electrical_stays_a_plumbing_job(self):
        for txt in ('Aircon is dripping water inside', 'Leaking tap in the bathroom', 'The shower is leaking into the wall',
                    'Máy lạnh bị chảy nước, cần thợ', 'vòi nước bị rỉ nước'):
            with self.subTest(txt=txt):
                self.assertEqual(technical.hazard_check(txt), ('none', {}))

    def test_none_only_when_no_family_term_is_left(self):
        rx = technical._HZ_NET
        for txt in NET_NONE + CHECKER_OVER_ALERT[:8]:
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual((verdict, states), ('none', {}))
        # câu có từ của lưới ngoài mọi cụm trong danh sách thì không bao giờ là 'none'
        for txt in NET_UNCERTAIN + NET_NEGATED:
            with self.subTest(txt=txt):
                self.assertTrue(rx.search(technical._hz_norm(txt)))
                self.assertNotEqual(technical.classify_hazard(txt), 'none')

    def test_net_never_lowers_a_precise_verdict(self):
        for txt in ('I can smell gas and the fridge is buzzing', 'Sparks from the outlet, smells weird',
                    'Khói từ ổ cắm, có mùi lạ', 'smoke alarm going off and a strange smell'):
            with self.subTest(txt=txt):
                verdict, states = technical.hazard_check(txt)
                self.assertEqual(verdict, 'danger')
                self.assertFalse(_net_only(states))
                self.assertFalse(any(k.startswith('possible_') for k in states))   # dict 'danger' = loại chính xác
        verdict, states = technical.hazard_check('No sparks. The fridge is buzzing')
        self.assertEqual((verdict, states.get('sparks'), states.get('possible_sparks')), ('uncertain', 'negated', 'uncertain'))

    def test_net_follows_the_statement_rules(self):
        self.assertEqual(technical.hazard_check('weird smell? no'), ('negated', {'possible_smell': 'negated'}))
        self.assertEqual(technical.hazard_check('weird smell last week'), ('uncertain', {'possible_smell': 'past'}))
        self.assertEqual(technical.hazard_check('Is there a smell?'), ('uncertain', {'possible_smell': 'question'}))
        self.assertEqual(technical.hazard_check('no smell, but now it is back'), ('uncertain', {'possible_smell': 'uncertain'}))
        self.assertEqual(technical.hazard_check('Có mùi lạ, giờ hết mùi rồi'), ('negated', {'possible_smell': 'negated'}))

    def test_layer_is_documented_at_the_top_of_the_classifier(self):
        src = open(technical.__file__, encoding='utf-8').read()
        head = src[src.index('# Phát hiện NGUY HIỂM'):src.index('_HZ_ALARM_PRE = (')]
        self.assertIn('LƯỚI AN TOÀN (_HZ_NET', head)
        for fam in ('gas', 'smell', 'sparks', 'smoke', 'burning', 'shock', 'water', 'alarm', 'fire'):
            self.assertTrue(re.search(r'#\s+' + fam + r'\s', head), fam)
        self.assertIn("'none' CHỈ khi không còn từ nào thuộc họ nguy hiểm", head)
        self.assertIn('_HZ_NET_SAFE', head)
        self.assertIn('_HZ_PERSON_SMOKE', head)


# ================================================================ 3. qua công cụ thật
class HazardNetJobToolTests(unittest.TestCase):
    def setUp(self):
        seed()
        self.cid = f'{TECH}:0412345678'
        DB.bot_customers.insert_one({'id': self.cid})

    def run_job(self, problem, i):
        DB.bot_customers.update_one({'id': self.cid}, {'$set': {'needs_human': None, 'ai_paused': None,
                                                                 'handoff_urgent': None}})
        CALLS.clear()
        return job(customer_id=self.cid, args={'problem': problem, 'address': f'{i + 1} King St, Newtown NSW'})

    def test_net_only_problem_is_urgent_with_a_person_an_owner_alert_and_a_conditional_safety_line(self):
        for i, problem in enumerate(('the fridge is buzzing', 'I turned the gas off', 'tủ lạnh kêu rè',
                                     "there's a strange smell in the kitchen", 'bếp từ bị cháy mạch')):
            with self.subTest(problem=problem):
                out = self.run_job(problem, i)
                self.assertEqual(out['urgency'], 'urgent')
                self.assertTrue(out['possible_hazard'])
                tell = out['tell_customer']
                self.assertIn('right now, leave the area and call 000', tell)
                for evacuate in ('somewhere safe', 'get everyone', 'If anyone is in danger'):
                    self.assertNotIn(evacuate, tell)
                bc = DB.bot_customers.find_one({'id': self.cid})
                self.assertTrue(bc['needs_human'] and bc['handoff_urgent'] and bc['ai_paused'])
                self.assertEqual([a[4] for a in alerts()], ['technical_hazard_check'])
                self.assertEqual(DB.tasks.find_one({'id': out['job_id']})['urgency'], 'urgent')

    def test_checker_hazards_are_emergencies(self):
        for i, (problem, _) in enumerate(CHECKER_PRESENT[:6] + CHECKER_PRESENT[-6:]):
            with self.subTest(problem=problem):
                out = self.run_job(problem[:600], 20 + i)
                self.assertEqual(out['urgency'], 'emergency')
                self.assertIn('000', out['tell_customer'])
                self.assertEqual([a[4] for a in alerts()], ['technical_emergency'])

    def test_over_alerts_are_normal_jobs(self):
        for i, problem in enumerate(CHECKER_OVER_ALERT[:8] + ('Need my gas heater serviced before winter', 'nạp gas máy lạnh')):
            with self.subTest(problem=problem):
                out = self.run_job(problem, 40 + i)
                self.assertEqual(out['urgency'], 'normal')
                self.assertNotIn('000', out['tell_customer'])
                self.assertNotIn('possible_hazard', out)
                self.assertEqual([a[4] for a in alerts()], ['technical_job'])
                self.assertFalse(DB.bot_customers.find_one({'id': self.cid}).get('needs_human'))

    def test_negated_net_term_is_a_normal_job_with_the_safety_tip(self):
        out = self.run_job('No smell or buzzing, it just will not turn on', 60)
        self.assertEqual(out['urgency'], 'normal')
        self.assertIn('call 000', out['safety_tip'])
        self.assertEqual([a[4] for a in alerts()], ['technical_job'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
