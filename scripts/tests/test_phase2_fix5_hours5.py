# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 vòng 5, khu "hours5": thứ THIẾU trong giờ mở cửa ĐÃ LƯU nghĩa là 1 điều duy nhất ở mọi đường.

LUẬT (reservations_core.saved_week): giờ mở cửa đã lưu (dict khác rỗng trong booking_settings.hours) là CẢ TUẦN — thứ không
có khoá = NGHỈ, như None (đúng điều booking_rules.save_rules luôn ghi: đủ 7 thứ, thứ chủ không nhập = None). DEFAULT_HOURS
(9-19) chỉ dùng khi CHƯA lưu gì (không có / rỗng / không phải dict): Nails / Spa đặt lịch theo giờ mặc định như cũ, ngành đặt
chỗ coi là "chưa công bố".

Trước: booking_rules.get_rules lấp thứ thiếu bằng DEFAULT_HOURS còn reservations_core.load_rules (gói F&B / karaoke) đọc thiếu
= nghỉ -> bản ghi cũ / sửa tay {'mon':..., 'fri':...}: dòng OPENING HOURS của gói nói 'Tue closed ... Sat closed' cạnh dòng
RIGHT NOW (customer_context.hours_lines -> get_rules) coi thứ Ba mở 9:00 am – 7:00 pm; câu hẹn giờ trả lời gửi khách
(reply_expectation) nói "tiệm đang mở" trong ngày quán nghỉ; trang Cài đặt hiện 9-19 cho thứ chủ chưa từng mở.

  1) saved_week: 1 helper, 1 luật (thiếu = nghỉ; chưa lưu = None);
  2) get_rules và load_rules đọc CÙNG 1 tuần từ cùng bản ghi; giờ hư (không phải dict) = chưa lưu ở cả 2 (trước: get_rules
     giữ nguyên list -> hours_on vỡ AttributeError);
  3) prompt khách đầy đủ F&B + karaoke (EN / VI) vào đúng ngày thiếu: tuần nói 'Tue closed', RIGHT NOW nói đóng + lần mở tới
     thật; kiểm giờ của gói từ chối ngày đó; reply_expectation không nói "đang mở";
  4) Nails / Spa: tiệm chưa lưu giờ vẫn dùng DEFAULT_HOURS (prompt + kiểm giờ) như cũ, bản ghi đủ 7 thứ đọc y nguyên; bản
     ghi thiếu thứ cũng theo đúng 1 luật ở prompt, RIGHT NOW, check_slot, check_availability.

Dùng lại DB giả + stub + hàm app.py (lấy qua ast) của test_phase2_receptionist_core.py. KHÔNG import app.py, KHÔNG mở
MongoDB thật, KHÔNG gọi mạng / API trả phí.
Chạy: python scripts/tests/test_phase2_fix5_hours5.py
"""
import copy
import os
import sys
import unittest
from datetime import date, datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_receptionist_core as core  # noqa: E402  (DB giả + stub TRƯỚC mọi import của module thật)

import ai_function_tools  # noqa: E402
import ai_packs  # noqa: E402
import booking_rules  # noqa: E402
import customer_context  # noqa: E402
import reservations_core as rc  # noqa: E402
from ai_context_engine import AIContextEngine  # noqa: E402
from ai_sales_prompts import compose_booking_assistant_prompt  # noqa: E402

DB, NS = core.DB, core.NS
TUE = datetime(2026, 11, 3, 10, 0)                       # thứ Ba 10:00 giờ tiệm — thứ KHÔNG có trong bản ghi
WEEK_DAYS = [date(2026, 11, 2 + i) for i in range(7)]    # thứ Hai 2/11 -> Chủ nhật 8/11
# bản ghi cũ / sửa tay: chỉ thứ Hai + thứ Sáu (save_rules không bao giờ ghi kiểu này — luôn đủ 7 thứ)
PARTIAL = {'mon': ['11:00', '22:00'], 'fri': ['18:00', '02:00']}
PARTIAL_WEEK = {'en': 'Mon 11:00 am – 10:00 pm, Tue closed, Wed closed, Thu closed, Fri 6:00 pm – 2:00 am (Sat), '
                      'Sat closed, Sun closed',
                'vi': 'T2 11:00 – 22:00, T3 nghỉ, T4 nghỉ, T5 nghỉ, T6 18:00 – 02:00 (sáng T7), T7 nghỉ, CN nghỉ'}
RIGHT_NOW_TUE = {'en': 'RIGHT NOW: closed — next opening Fri 6:00 pm.', 'vi': 'RIGHT NOW: closed — next opening T6 18:00.'}
SALON_PARTIAL = {'mon': ['09:00', '19:00'], 'wed': ['09:00', '19:00']}   # tiệm Nails sửa tay: chỉ thứ Hai + thứ Tư


def shop(ind, hours=PARTIAL, bid=None):
    bid = bid or f'h5_{ind}'
    DB.businesses.insert_one({'id': bid, 'name': f'Shop {ind}', 'industry_code': ind, 'currency': 'USD', 'country': 'US',
                              'phone': '+12125550100'})
    if hours is not ...:
        DB.booking_settings.insert_one({'business_id': bid, 'hours': copy.deepcopy(hours), 'info': {'parking': 'Street parking'}})
    booking_rules._CACHE.clear()
    return bid


def full_prompt(bid, ind, lang):
    """Prompt khách đúng như chat web: danh tính + dữ kiện (app.py::_booking_assistant_facts) + luật gói."""
    pack = ai_packs.pack_for_business(bid)
    ctx = AIContextEngine.build_context_prompt(bid, None, include_private_data=False, audience='customer')
    return compose_booking_assistant_prompt(
        ctx['prompt'], ctx['business_name'], booking_facts=NS['_booking_assistant_facts'](bid, lang=lang),
        booking_enabled=pack is not None, pack=pack, lang=lang, can_verify=False, industry=ind)


def _span(v):
    return v if isinstance(v, tuple) else None


class _At(core._Base):
    """DB giả sạch + giờ tiệm = `NOW_AT` (booking_rules.local_now giả)."""
    NOW_AT = TUE

    def setUp(self):
        super().setUp()
        self._p[0].stop()
        self._p[0] = patch.object(booking_rules, 'local_now', lambda bid: self.NOW_AT)
        self._p[0].start()


# ================================================================ (1) 1 helper, 1 luật
class SavedWeekIsTheOneRule(unittest.TestCase):
    def test_missing_day_is_closed_and_nothing_saved_is_none(self):
        week = rc.saved_week(PARTIAL)
        self.assertEqual(list(week), rc.DAY_KEYS)                                   # đủ 7 thứ, theo thứ tự tuần
        self.assertEqual(week, {'mon': ['11:00', '22:00'], 'tue': None, 'wed': None, 'thu': None,
                                'fri': ['18:00', '02:00'], 'sat': None, 'sun': None})
        self.assertEqual(rc.saved_week({'mon': [], 'tue': '', 'wed': ['09:00', '17:00']})['tue'], None)
        for nothing in (None, {}, [], '', 'mon 9-5', [['09:00', '17:00']], 0):
            self.assertIsNone(rc.saved_week(nothing), nothing)
        self.assertEqual(rc.saved_week({'monday': ['09:00', '17:00']}), {d: None for d in rc.DAY_KEYS})
        self.assertIsNot(rc.saved_week(PARTIAL), PARTIAL)                         # bản sao: không sửa bản ghi đệm
        self.assertEqual(PARTIAL, {'mon': ['11:00', '22:00'], 'fri': ['18:00', '02:00']})

    def test_week_text_says_the_same(self):
        for lang in ('en', 'vi'):
            self.assertEqual(rc.week_hours_text(PARTIAL, lang), PARTIAL_WEEK[lang])
            self.assertEqual(rc.week_hours_text(rc.saved_week(PARTIAL), lang), PARTIAL_WEEK[lang])


# ================================================================ (2) get_rules == load_rules
class GetRulesAndLoadRulesReadOneWeek(core._Base):
    def test_partial_saved_dict(self):
        for ind in ('fnb', 'karaoke', 'nail'):
            bid = shop(ind)
            general = booking_rules.get_rules(bid)
            self.assertTrue(general['configured'])
            self.assertEqual(general['hours'], rc.saved_week(PARTIAL), ind)        # trước: tue..sun = DEFAULT_HOURS
            for kind in ('table', 'karaoke'):
                own = rc.load_rules(bid, kind)
                self.assertEqual(own['hours'], general['hours'], (ind, kind))
                for d in WEEK_DAYS:
                    with self.subTest(industry=ind, kind=kind, day=d):
                        self.assertEqual(booking_rules.hours_on(general, d), _span(rc.hours_on(own, d)))
            self.assertEqual(booking_rules.hours_on(general, WEEK_DAYS[1]), None)     # thứ Ba nghỉ ở cả 2 module
            self.assertEqual(booking_rules.hours_on(general, WEEK_DAYS[4]), (18 * 60, 26 * 60))

    def test_nothing_saved_keeps_the_appointment_defaults(self):
        for hours in (..., None, {}, ['09:00', '17:00'], 'mon-fri 9-5'):
            with self.subTest(hours=hours):
                core.seed()
                bid = shop('nail', hours=hours)
                general = booking_rules.get_rules(bid)
                self.assertFalse(general['configured'])
                self.assertEqual(general['hours'], booking_rules.DEFAULT_HOURS)     # trước: list / chuỗi giữ nguyên -> vỡ
                self.assertEqual(booking_rules.hours_on(general, WEEK_DAYS[1]), (9 * 60, 19 * 60))
                self.assertIsNone(rc.load_rules(bid, 'table')['hours'])            # ngành đặt chỗ: chưa công bố
                self.assertIsNotNone(booking_rules.open_status(bid, general, TUE))  # không vỡ

    def test_full_saved_week_reads_unchanged(self):
        week = {'mon': ['09:00', '19:00'], 'tue': ['09:00', '19:00'], 'wed': None, 'thu': ['09:00', '20:00'],
                'fri': ['09:00', '20:00'], 'sat': ['09:00', '18:00'], 'sun': None}
        bid = shop('nail', hours=week)
        self.assertEqual(booking_rules.get_rules(bid)['hours'], week)
        self.assertEqual(rc.load_rules(bid, 'table')['hours'], week)
        r = booking_rules.save_rules(bid, {'hours': {'mon': ['10:00', '18:00']}})   # save_rules: thứ không nhập = None
        self.assertEqual(r['hours'], dict({d: None for d in rc.DAY_KEYS}, mon=['10:00', '18:00']))
        self.assertEqual(DB.booking_settings.find_one({'business_id': bid})['hours'], r['hours'])

    def test_cached_row_is_not_mutated(self):
        bid = shop('fnb', hours={'mon': ['11:00', '22:00']})
        booking_rules.get_rules(bid)['hours']['tue'] = ['01:00', '02:00']
        self.assertEqual(booking_rules.get_rules(bid)['hours']['tue'], None)


# ================================================================ (3) prompt khách F&B + karaoke vào đúng ngày thiếu
class ReservationPromptAgreesOnAMissingDay(_At):
    def test_week_line_and_right_now_agree(self):
        for ind in ('fnb', 'karaoke'):
            bid = shop(ind)
            for lang in ('en', 'vi'):
                with self.subTest(industry=ind, lang=lang):
                    prompt = full_prompt(bid, ind, lang)
                    self.assertEqual(prompt.count(PARTIAL_WEEK[lang]), 1, prompt)
                    self.assertEqual(prompt.count('RIGHT NOW'), 1)
                    self.assertIn(RIGHT_NOW_TUE[lang], prompt)                     # trước: 'open until 7:00 pm.'
                    self.assertNotIn('open until', prompt)
                    for default_text in ('9:00 am – 7:00 pm', '09:00 – 19:00', 'Tue 9:00', 'T3 09:00'):
                        self.assertNotIn(default_text, prompt)                     # giờ mặc định Nails không lọt vào

    def test_reply_expectation_and_open_status(self):
        for ind in ('fnb', 'karaoke'):
            bid = shop(ind)
            st = booking_rules.open_status(bid)
            self.assertEqual((st['open_now'], st['next_open']), (False, 'Fri 6:00 pm'))   # trước: open_now True (9-19)
            self.assertIn("We're closed right now — the team will reply here when we open (Fri 6:00 pm).",
                          ai_function_tools.reply_expectation(bid))
            self.assertIn('Tiệm đang đóng cửa — nhân viên sẽ trả lời tại đây khi tiệm mở cửa (T6 18:00).',
                          ai_function_tools.reply_expectation(bid, vi=True))

    def test_pack_checks_refuse_the_missing_day(self):
        for ind, kind, hold in (('fnb', 'table', 60), ('karaoke', 'karaoke', 120)):
            bid = shop(ind)
            rules = rc.load_rules(bid, kind)
            with self.assertRaises(rc.ReservationError) as e:
                rc.check_window(rules, datetime(2026, 11, 3, 12, 0), TUE, hold)
            self.assertEqual(e.exception.reason, 'closed_that_day', ind)
            self.assertEqual(rc.day_hours_text(rules, WEEK_DAYS[1]), 'Tue closed')
            self.assertEqual(rc.day_hours_text(rules, WEEK_DAYS[5]), 'Fri 6:00 pm – 2:00 am (Sat), Sat closed')
            rc.check_window(rules, datetime(2026, 11, 6, 19, 0), TUE, hold)                # thứ Sáu tối: đặt được


# ================================================================ (4) Nails / Spa
class AppointmentShops(_At):
    def test_unconfigured_salon_still_books_default_hours(self):
        for ind in ('nail', 'spa'):
            bid = shop(ind, hours=...)
            rules = booking_rules.get_rules(bid)
            self.assertFalse(rules['configured'])
            booking_rules.check_slot(bid, datetime(2026, 11, 3, 15, 0), rules=rules, now=TUE)   # thứ Ba 9-19 mặc định
            lines = customer_context.hours_lines(bid, rules, include_defaults=True)
            self.assertEqual(lines[0], f"OPENING HOURS: {rc.week_hours_text(booking_rules.DEFAULT_HOURS)}.")
            self.assertEqual(lines[1], 'RIGHT NOW: open until 7:00 pm.')
            self.assertEqual(customer_context.hours_lines(bid, rules), [])            # gói khác: mặc định không phải giờ thật

    def test_partial_salon_doc_follows_the_one_rule_everywhere(self):
        bid = shop('nail', hours=SALON_PARTIAL)
        DB.products.insert_one({'id': 1, 'business_id': bid, 'name': 'Gel Manicure', 'price': 45, 'is_active': 1})
        prompt = full_prompt(bid, 'nail', 'en')
        self.assertIn('OPENING HOURS: Mon 9:00 am – 7:00 pm, Tue closed, Wed 9:00 am – 7:00 pm, Thu closed, Fri closed, '
                      'Sat closed, Sun closed.', prompt)
        self.assertIn('RIGHT NOW: closed — next opening tomorrow 9:00 am.', prompt)       # trước: 'open until 7:00 pm.'
        with self.assertRaises(booking_rules.SlotUnavailable) as e:
            booking_rules.check_slot(bid, datetime(2026, 11, 3, 15, 0), now=TUE)
        self.assertEqual(e.exception.reason, 'closed_that_day')                          # trước: nhận lịch thứ Ba
        self.assertEqual(booking_rules.available_slots(bid, WEEK_DAYS[1], now=TUE), [])
        out = ai_function_tools.check_availability(bid, f'{bid}:web:abc', date='2026-11-03')
        self.assertEqual((out['open'], out['opening_hours'], out['available_start_times']), (False, 'Tue closed', []))
        self.assertTrue(booking_rules.available_slots(bid, WEEK_DAYS[2], now=TUE))          # thứ Tư vẫn mở


if __name__ == '__main__':
    unittest.main(verbosity=2)
