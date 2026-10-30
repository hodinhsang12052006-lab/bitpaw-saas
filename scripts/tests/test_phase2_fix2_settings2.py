# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 review vòng 2, mục "settings2":

  1) customer_context.hours_lines (prompt khách của MỌI kênh chat): ngày mở QUA nửa đêm nói rõ giờ đóng thật + ngày hôm sau
     ('Fri 6:00 pm – 2:00 am (Sat)'), không in trơn 'Fri 18:00-02:00' (dễ hiểu thành đóng 2 giờ sáng CÙNG ngày);
  2) scripts/ai_sim/scenarios_common.auto_confirm_of (sự thật DB của giả lập) == reservations_core.load_rules (điều AI làm):
     công tắc chung chỉ tính khi chủ đã lưu nó ở trang Cài đặt đặt chỗ (reservations_general_saved_at); báo cáo
     scripts/ai_demo_readiness.py báo đúng luật đó cho bàn F&B + phòng karaoke;
  3) trang Cài đặt đặt chỗ: ô Đặt trước tối thiểu / tối đa đã lưu rồi xoá trống thì bấm Lưu XOÁ được (trước: ô trống không
     được gửi nên số cũ ở lại mãi, AI vẫn dùng) — route Flask thật + script thật của trang trong node.

Dùng lại DB giả + Flask + decorator thật + khung chạy script trang của test_phase2_settings_hours.py /
test_phase2_owner_settings.py. KHÔNG import app.py, KHÔNG mở MongoDB thật, KHÔNG gọi mạng.

Chạy: python scripts/tests/test_phase2_fix2_settings2.py
"""
import itertools
import os
import shutil
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_settings_hours as H  # noqa: E402  (DB giả + stub mongo_client / app TRƯỚC mọi import của module thật)

S, DB, BID, rc, booking_rules, ROOT = H.S, H.DB, H.BID, H.rc, H.booking_rules, H.ROOT
for _p in (os.path.join(ROOT, 'scripts'), os.path.join(ROOT, 'scripts', 'ai_sim')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import customer_context  # noqa: E402
import scenarios_common  # noqa: E402
import ai_demo_readiness as rd  # noqa: E402

MARK = H.MARK
LATE = {'mon': ['11:00', '22:00'], 'tue': None, 'wed': ['16:00', '24:00'], 'thu': ['00:00', '24:00'],
        'fri': ['18:00', '02:00'], 'sat': ['18:00', '02:00'], 'sun': ['17:30', '01:30']}


# ================================================================ (1) giờ mở cửa trong prompt khách
class CustomerHoursLines(unittest.TestCase):
    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()

    def opening_line(self):
        rules = booking_rules.save_rules(BID, {'hours': LATE}, allow_overnight=True)   # đúng đường lưu của trang Cài đặt
        lines = customer_context.hours_lines(BID, rules)
        self.assertTrue(lines[0].startswith('OPENING HOURS: '), lines)
        return lines[0]

    def test_overnight_days_state_the_real_close_and_the_next_day(self):
        line = self.opening_line()
        self.assertIn('Fri 6:00 pm – 2:00 am (Sat)', line)
        self.assertIn('Sat 6:00 pm – 2:00 am (Sun)', line)
        self.assertIn('Sun 5:30 pm – 1:30 am (Mon)', line)            # Chủ nhật qua đêm -> thứ Hai (vòng tuần)
        self.assertNotIn('18:00-02:00', line)
        self.assertNotIn('17:30-01:30', line)

    def test_same_day_hours_are_unchanged(self):
        line = self.opening_line()
        self.assertIn('Mon 11:00-22:00, Tue closed, Wed 16:00-24:00, Thu 00:00-24:00', line)   # như cũ (test lõi dựa vào)
        nail = customer_context.hours_lines('nail-1', {'configured': True, 'hours': booking_rules.DEFAULT_HOURS})
        self.assertTrue(nail[0].startswith('OPENING HOURS: Mon 09:00-19:00, Tue 09:00-19:00'), nail[0])
        self.assertNotIn(' am', nail[0])
        self.assertNotIn(' pm', nail[0])

    def test_unreadable_saved_value_is_printed_as_before(self):
        line = customer_context.hours_lines('x', {'configured': True, 'hours': {'mon': ['late', '02:00'], 'tue': None}})[0]
        self.assertIn('Mon late-02:00', line)          # không đoán, không vỡ prompt
        self.assertTrue(customer_context.hours_lines('x', {'configured': False, 'hours': LATE}) == [])   # chưa lưu: không in

    def test_right_now_line_still_from_open_status(self):
        rules = booking_rules.save_rules(BID, {'hours': LATE}, allow_overnight=True)
        fri_23 = datetime(2026, 10, 30, 23, 0)
        orig = booking_rules.local_now
        booking_rules.local_now = lambda bid: fri_23
        try:
            lines = customer_context.hours_lines(BID, rules)
        finally:
            booking_rules.local_now = orig
        self.assertEqual(lines[1], 'RIGHT NOW: open until 02:00 (after midnight).')


# ================================================================ (2) giả lập + báo cáo demo == luật AI
SUBS = {'table': 'table_reservations', 'karaoke': 'karaoke_reservations'}


def _docs():
    """Mọi tổ hợp: công tắc chung (vắng / True / False) x dấu đã lưu (vắng / có / rỗng) x khối riêng (vắng / None / True /
    False) — đúng các trạng thái trang cũ, trang Đặt chỗ, seed demo có thể để lại."""
    for general, mark, own in itertools.product(('-', True, False), ('-', '2026-10-30T09:00:00', ''), ('-', None, True, False)):
        doc = {'business_id': BID, 'hours': S.HOURS}
        if general != '-':
            doc['auto_confirm'] = general
        if mark != '-':
            doc[MARK] = mark
        if own != '-':
            for sub in SUBS.values():
                doc[sub] = {'auto_confirm': own, 'hold_minutes': 15}
        yield doc


class SimTruthMatchesTheAi(unittest.TestCase):
    def setUp(self):
        DB.reset()

    def test_auto_confirm_of_mirrors_load_rules_for_every_combination(self):
        self.assertEqual(scenarios_common.GENERAL_SAVED_MARK, rc.GENERAL_SAVED_MARK)
        n = 0
        for doc in _docs():
            DB.reset()
            DB.booking_settings.insert_one(dict(doc))
            for kind, sub in SUBS.items():
                with self.subTest(doc={k: v for k, v in doc.items() if k not in ('business_id', 'hours')}, kind=kind):
                    self.assertIs(scenarios_common.auto_confirm_of(dict(doc), sub), rc.load_rules(BID, kind)['auto_confirm'])
                    n += 1
        self.assertEqual(n, 72)

    def test_old_nails_page_default_is_not_auto_confirm_in_the_sim(self):
        legacy = dict(H.LEGACY)                        # trang Cài đặt đặt lịch CŨ: auto_confirm=True, không có dấu
        self.assertIs(scenarios_common.auto_confirm_of(legacy, 'table_reservations'), False)
        self.assertIs(scenarios_common.auto_confirm_of(legacy, 'karaoke_reservations'), False)
        self.assertIs(scenarios_common.auto_confirm_of(dict(legacy, **{MARK: '2026-10-30T09:00:00'}), 'table_reservations'), True)
        self.assertIs(scenarios_common.auto_confirm_of(dict(legacy, table_reservations={'auto_confirm': True}),
                                                       'table_reservations'), True)


class ReadinessReportsTheRealRule(unittest.TestCase):
    def setUp(self):
        DB.reset()

    def info(self, industry, settings):
        r = rd.Report(industry, 'demo@bitpawdemo.com')
        fn = rd.SPECIFIC[industry]
        fn(rd.ReadOnlyDB(DB), r, BID, {'settings': settings}, date(2026, 10, 30))
        return {i['key']: i for i in r.items}

    def test_legacy_general_switch_is_reported_as_pending(self):
        items = self.info('fnb', dict(H.LEGACY))
        self.assertTrue(items['table_auto_confirm']['detail'].startswith('tự xác nhận đặt bàn: False'),
                        items['table_auto_confirm'])
        self.assertIn('không tính', items['table_auto_confirm']['detail'])
        items = self.info('karaoke', dict(H.LEGACY))
        self.assertTrue(items['karaoke_auto_confirm']['detail'].startswith('tự xác nhận đặt phòng hát: False'),
                        items['karaoke_auto_confirm'])

    def test_report_matches_load_rules_for_every_combination(self):
        for doc in _docs():
            DB.reset()
            DB.booking_settings.insert_one(dict(doc))
            for industry, kind, key in (('fnb', 'table', 'table_auto_confirm'), ('karaoke', 'karaoke', 'karaoke_auto_confirm')):
                with self.subTest(doc={k: v for k, v in doc.items() if k not in ('business_id', 'hours')}, kind=kind):
                    want = rc.load_rules(BID, kind)['auto_confirm']
                    self.assertTrue(self.info(industry, dict(doc))[key]['detail'].split(': ', 1)[1].startswith(f'{want} ('))

    def test_report_still_reads_only(self):
        with self.assertRaises(rd.ReadOnlyError):
            rd.ReadOnlyDB(DB).booking_settings.update_one


# ================================================================ (3) xoá trống Đặt trước tối thiểu / tối đa
class ClearBookingWindow(H.Base):
    def save_window(self, lead=30, adv=90):
        code, g = self.general('POST', {'min_lead_minutes': lead, 'max_advance_days': adv, 'auto_confirm': False})
        self.assertEqual(code, 200, g)
        self.assertEqual((self.stored()['min_lead_minutes'], self.stored()['max_advance_days']), (lead, adv))

    def test_cleared_fields_are_removed_and_the_ai_goes_back_to_not_set(self):
        self.save_window()
        code, g = self.general('POST', {'min_lead_minutes': None, 'max_advance_days': None, 'auto_confirm': False})
        self.assertEqual(code, 200, g)
        doc = self.stored()
        self.assertNotIn('min_lead_minutes', doc)
        self.assertNotIn('max_advance_days', doc)
        self.assertEqual((g['rules']['min_lead_minutes'], g['rules']['max_advance_days']), (None, None))   # ô hiện "Chưa đặt"
        k = rc.load_rules(BID, 'karaoke')
        self.assertEqual((k['min_lead_minutes'], k['max_advance_days']), (0, 366))
        self.assertEqual((self.get('karaoke')[1]['min_lead_minutes'], self.get('karaoke')[1]['max_advance_days']), (0, 366))

    def test_clearing_one_keeps_the_other_and_empty_string_also_clears(self):
        self.login('fnb')
        self.save_window()
        code, g = self.general('POST', {'min_lead_minutes': '', 'max_advance_days': 45})
        self.assertEqual(code, 200, g)
        doc = self.stored()
        self.assertNotIn('min_lead_minutes', doc)
        self.assertEqual(doc['max_advance_days'], 45)
        t = rc.load_rules(BID, 'table')
        self.assertEqual((t['min_lead_minutes'], t['max_advance_days']), (0, 45))

    def test_clearing_does_not_touch_other_saved_rules(self):
        DB.booking_settings.insert_one(dict(H.LEGACY, **{MARK: '2026-10-30T09:00:00'}))
        code, g = self.general('POST', {'min_lead_minutes': None, 'max_advance_days': None})
        self.assertEqual(code, 200, g)
        doc = self.stored()
        self.assertEqual((doc['hours'], doc['auto_confirm'], doc[MARK], doc['info']['address']),
                         (S.HOURS, True, '2026-10-30T09:00:00', '1 Main St'))
        self.assertNotIn('min_lead_minutes', doc)

    def test_nail_rules_are_unchanged(self):
        self.login('nail')
        self.general('POST', {'min_lead_minutes': 30})
        code, g = self.general('POST', {'min_lead_minutes': None})
        self.assertEqual((code, g['message']), (400, 'Minimum notice: must be a number.'))   # Nails: luật cũ, không xoá
        self.assertEqual(self.stored()['min_lead_minutes'], 30)

    def test_save_rules_unset_only_touches_known_rule_keys(self):
        booking_rules.save_rules(BID, {'min_lead_minutes': 30, 'max_advance_days': 90})
        r = booking_rules.save_rules(BID, {'max_advance_days': 20}, unset=['min_lead_minutes', 'max_advance_days', 'business_id'])
        doc = self.stored()
        self.assertNotIn('min_lead_minutes', doc)
        self.assertEqual((doc['max_advance_days'], doc['business_id']), (20, BID))   # giá trị trong data thắng; khoá lạ bỏ qua
        self.assertEqual(r['min_lead_minutes'], booking_rules.DEFAULTS['min_lead_minutes'])


@unittest.skipUnless(shutil.which('node'), 'node không có trên máy này')
class ClearBookingWindowOnThePage(H.Base):
    run_page = H.PageScript.run_page

    def test_owner_clears_saved_fields_on_the_page(self):
        DB.booking_settings.insert_one(dict(H.LEGACY))                     # đã lưu 60 phút / 60 ngày
        out = self.run_page('karaoke', [{'op': 'value', 'id': 'lead', 'value': ''}, {'op': 'value', 'id': 'adv', 'value': ''},
                                        {'op': 'save'}])
        self.assertEqual((out['snaps']['loaded']['lead'], out['snaps']['loaded']['adv']), ('60', '60'))
        body = out['posts'][0]['body']
        self.assertEqual(out['posts'][0]['url'], '/api/booking/settings')
        self.assertIsNone(body['min_lead_minutes'])
        self.assertIsNone(body['max_advance_days'])
        doc = self.stored()
        self.assertNotIn('min_lead_minutes', doc)
        self.assertNotIn('max_advance_days', doc)
        k = rc.load_rules(BID, 'karaoke')
        self.assertEqual((k['min_lead_minutes'], k['max_advance_days'], k['auto_confirm']), (0, 366, False))
        self.assertEqual(self.general()[1]['rules']['min_lead_minutes'], None)

    def test_kept_values_are_still_sent(self):
        DB.booking_settings.insert_one(dict(H.LEGACY))
        out = self.run_page('fnb', [{'op': 'value', 'id': 'adv', 'value': '30'}, {'op': 'save'}])
        body = out['posts'][0]['body']
        self.assertEqual((body['min_lead_minutes'], body['max_advance_days']), (60, 30))
        self.assertEqual((self.stored()['min_lead_minutes'], self.stored()['max_advance_days']), (60, 30))

    def test_nail_page_never_sends_null(self):
        out = self.run_page('nail', [{'op': 'value', 'id': 'lead', 'value': ''}, {'op': 'save'}])
        self.assertEqual(out['posts'][0]['body']['min_lead_minutes'], 0)   # Nails: như cũ (ô trống = 0 phút)


if __name__ == '__main__':
    unittest.main(verbosity=2)
