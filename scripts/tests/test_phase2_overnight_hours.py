# -*- coding: utf-8 -*-
"""Test OFFLINE — quán mở QUA nửa đêm (karaoke 18:00-02:00, quán bar, nhà hàng tới 1 giờ sáng).

Trước đây Cài đặt đặt lịch chỉ lưu được giờ mở < giờ đóng <= 24:00, nên quán karaoke mở tới 2 giờ sáng phải nhập 24:00:
AI từ chối lượt hát 23:00 x 3 giờ ("It closes at 00:00"), coi 00:30 thứ Bảy (vẫn là đêm thứ Sáu) là ngoài giờ mở cửa, và nói
sai giờ đóng cửa. Quy ước MỚI (booking_rules.py / reservations_core.py): ngành đặt chỗ (F&B, karaoke, khách sạn) lưu đúng như
chủ nhập, giờ đóng NHỎ HƠN giờ mở = đóng sáng hôm sau (['18:00', '02:00'] -> hours_on = (1080, 1560)); giờ sau nửa đêm thuộc
NGÀY LỊCH hôm sau. Nails/Spa (lịch hẹn) giữ nguyên luật + hành vi cũ.

Dùng lại DB giả + stub của test_phase2_table_room_packs.py (mongo_client / requests / messaging thay TRƯỚC mọi import).
KHÔNG import app.py, KHÔNG mở MongoDB thật, KHÔNG gọi mạng.

Chạy: python scripts/tests/test_phase2_overnight_hours.py
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_table_room_packs as T  # noqa: E402  (DB giả + stub TRƯỚC mọi import của module thật)

DB, rc, booking_rules, karaoke, fnb = T.DB, T.rc, T.booking_rules, T.karaoke, T.fnb
MARK = 'reservations_general_saved_at'          # chủ đã lưu công tắc chung ở trang Cài đặt đặt chỗ (không phải mặc định Nails)
LATE = {d: ['18:00', '02:00'] for d in rc.DAY_KEYS}
NOWN = datetime(2026, 10, 26, 15, 0)            # thứ Hai 15:00 giờ quán
FRI_D, SAT_D, SUN_D, MON_D = date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2)


def rules(hours, **kw):
    r = {'hours': hours, 'min_lead_minutes': 0, 'max_advance_days': 366, 'slot_minutes': 30, 'last_booking_before_close': 60}
    r.update(kw)
    return r


def at(d, hh, mm=0):
    return datetime.combine(d, datetime.min.time()) + timedelta(hours=hh, minutes=mm)


def refused(r, when, minutes):
    try:
        rc.check_window(r, when, NOWN, minutes)
    except rc.ReservationError as e:
        return e
    raise AssertionError(f'{when} x {minutes} min was accepted')


# ================================================================ reservations_core: cửa sổ giờ mở cửa
class OvernightWindow(unittest.TestCase):
    def test_hours_on_wraps_past_midnight(self):
        self.assertEqual(rc.hours_on(rules(LATE), FRI_D), (1080, 1560))
        self.assertEqual(rc.hours_on(rules({'fri': ['16:00', '24:00']}), FRI_D), (960, 1440))   # đóng lúc nửa đêm: như cũ
        self.assertEqual(rc.hours_on(rules({'fri': ['11:00', '22:00']}), FRI_D), (660, 1320))
        self.assertIsNone(rc.hours_on(rules({'fri': None}), FRI_D))
        self.assertEqual(rc.hours_on({'hours': None}, FRI_D), rc.UNKNOWN)

    def test_session_that_ends_at_2am_fits(self):
        r = rules(LATE)
        rc.check_window(r, at(FRI_D, 23), NOWN, 180)             # 23:00 + 3 giờ = 02:00 đúng giờ đóng
        rc.check_window(r, at(FRI_D, 21), NOWN, 180)
        e = refused(r, at(FRI_D, 23, 30), 180)
        self.assertEqual(e.reason, 'too_close_to_closing')
        msg = rc.explain(e)
        self.assertIn('It closes at 2:00 am (Sat)', msg)                # giờ đóng thật + NGÀY đóng (kiểu giờ chung)
        self.assertIn('the latest start that fits is 23:00', msg)
        self.assertNotIn('00:00', msg)

    def test_after_midnight_is_still_the_previous_night(self):
        r = rules(LATE)
        rc.check_window(r, at(SAT_D, 0, 30), NOWN, 90)           # thứ Bảy 00:30 = đêm thứ Sáu, hát tới 02:00
        e = refused(r, at(SAT_D, 1, 30), 60)
        self.assertEqual(e.reason, 'too_close_to_closing')
        self.assertIn('the latest start that fits is 01:00', rc.explain(e))
        e = refused(r, at(SAT_D, 3), 60)
        self.assertEqual(e.reason, 'outside_opening_hours')
        msg = rc.explain(e)
        self.assertIn('Fri 6:00 pm – 2:00 am (Sat), Sat 6:00 pm – 2:00 am (Sun)', msg)   # ca đêm thứ Sáu + ca thứ Bảy

    def test_closed_day_after_a_late_night(self):
        r = rules(dict(LATE, sun=None))
        rc.check_window(r, at(SUN_D, 1), NOWN, 60)               # Chủ nhật nghỉ, nhưng đêm thứ Bảy còn mở tới 02:00
        self.assertEqual(refused(r, at(SUN_D, 20), 60).reason, 'closed_that_day')
        self.assertEqual(refused(r, at(MON_D, 1), 60).reason, 'outside_opening_hours')   # Chủ nhật nghỉ: không có đêm CN

    def test_candidate_starts_use_calendar_dates(self):
        r = rules(dict(LATE, thu=['18:00', '24:00']))
        fri = rc.karaoke_candidate_starts(r, FRI_D, 2)
        self.assertEqual((fri[0], fri[-1]), (1080, 1410))       # 23:30 + 2 giờ = 01:30; 00:00 trở đi thuộc thứ Bảy
        self.assertTrue(all(m < 24 * 60 for m in fri))
        sat = rc.karaoke_candidate_starts(r, SAT_D, 2)
        self.assertEqual(sat[0], 0)                              # 00:00 thứ Bảy (đêm thứ Sáu) hát 2 giờ tới 02:00
        self.assertNotIn(30, sat)
        self.assertIn(1080, sat)
        self.assertEqual(rc.table_candidate_times(r, SAT_D)[:4], [0, 30, 60, 1080])   # đặt muộn nhất 60 phút trước 02:00
        self.assertEqual(rc.table_candidate_times(r, FRI_D)[-1], 1410)
        self.assertEqual(rc.table_candidate_times(rules(dict(LATE, sun=None)), SUN_D), [0, 30, 60])

    def test_same_day_hours_behave_as_before(self):
        ktv = rules(T.KTV_HOURS)
        self.assertEqual(rc.karaoke_candidate_starts(ktv, FRI_D, 2), list(range(840, 1320 + 1, 30)))
        fnb_r = rules(T.FNB_HOURS, slot_minutes=15)
        self.assertEqual(rc.table_candidate_times(fnb_r, FRI_D), list(range(660, 1380 - 60 + 1, 15)))
        self.assertEqual(rc.table_candidate_times(fnb_r, SUN_D), [])
        e = refused(ktv, at(FRI_D, 23, 30), 60)
        self.assertIn('It closes at midnight; the latest start that fits is 23:00.', rc.explain(e))
        e = refused(ktv, at(FRI_D, 10), 60)
        self.assertIn('Opening hours that day: Fri 2:00 pm – midnight', rc.explain(e))
        self.assertEqual((rc.fmt_min(0), rc.fmt_min(1410), rc.fmt_min(1440), rc.fmt_min(1560)), ('00:00', '23:30', '24:00', '02:00'))

    def test_hours_text_states_the_real_closing_time(self):
        t = rc.hours_text(rules(dict(LATE, mon=['14:00', '24:00'], tue=None)))
        self.assertIn('Mon 2:00 pm – midnight, Tue closed', t)
        self.assertIn('Fri 6:00 pm – 2:00 am (Sat)', t)
        self.assertIn('Sun 6:00 pm – 2:00 am (Mon)', t)
        self.assertIn('after midnight is on the NEXT date', t)
        self.assertEqual(rc.hours_text(rules(T.KTV_HOURS)),
                         ', '.join(f"{rc.DAY_NAMES[d]} 2:00 pm – midnight" for d in rc.DAY_KEYS))


# ================================================================ booking_rules: lưu giờ + "đang mở không"
class BookingRulesHours(unittest.TestCase):
    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()

    def test_nail_validation_is_unchanged(self):
        for bad in (['18:00', '02:00'], ['09:00', '09:00'], ['09:00', '24:30'], ['x', '19:00'], ['09:00', '00:00'], ['09:00']):
            with self.assertRaises(ValueError) as cm:
                booking_rules.save_rules('nail-1', {'hours': {'mon': bad}})
            self.assertEqual(str(cm.exception), 'Giờ mở cửa ngày mon không hợp lệ.', bad)
        self.assertEqual(DB.booking_settings.count_documents({}), 0)
        r = booking_rules.save_rules('nail-1', {'hours': {'mon': ['09:00', '19:00'], 'tue': ['16:00', '24:00']}})
        self.assertEqual((r['hours']['mon'], r['hours']['tue']), (['09:00', '19:00'], ['16:00', '24:00']))
        self.assertEqual(booking_rules.hours_on(r, MON_D), (540, 1140))
        self.assertEqual(booking_rules.hours_on(r, MON_D + timedelta(days=1)), (960, 1440))

    def test_reservation_venues_save_overnight_hours_as_entered(self):
        r = booking_rules.save_rules('ktv-1', {'hours': {'fri': ['18:00', '02:00'], 'sat': ['00:00', '00:00'],
                                                         'sun': ['10:00', '00:00'], 'mon': ['22:00', '08:00']}},
                                     allow_overnight=True)
        self.assertEqual(r['hours']['fri'], ['18:00', '02:00'])
        self.assertEqual(r['hours']['sat'], ['00:00', '24:00'])       # mở cả ngày
        self.assertEqual(r['hours']['sun'], ['10:00', '24:00'])       # đóng lúc nửa đêm, không phải "qua đêm"
        self.assertEqual(r['hours']['mon'], ['22:00', '08:00'])
        self.assertEqual(booking_rules.hours_on(r, FRI_D), (1080, 1560))
        self.assertEqual(booking_rules.hours_on(r, SAT_D), (0, 1440))
        for bad, code in ((['18:00', '09:00'], 'overnight_late'), (['18:00', '18:00'], 'same'), (['25:00', '02:00'], 'format'),
                          (['9am', '02:00'], 'format')):
            with self.assertRaises(booking_rules.HoursError) as cm:
                booking_rules.save_rules('ktv-1', {'hours': {'fri': bad}}, allow_overnight=True)
            self.assertEqual((cm.exception.day, cm.exception.code), ('fri', code), bad)
        self.assertEqual(booking_rules.get_rules('ktv-1')['hours']['fri'], ['18:00', '02:00'])   # lỗi không ghi gì

    def test_open_status_across_midnight(self):
        r = {'hours': dict(LATE, sun=None)}
        st = booking_rules.open_status('ktv-1', r, now=at(FRI_D, 23))
        self.assertEqual((st['open_now'], st['closes_at']), (True, '02:00 (after midnight)'))
        st = booking_rules.open_status('ktv-1', r, now=at(SAT_D, 1, 15))
        self.assertEqual((st['open_now'], st['closes_at']), (True, '02:00'))
        st = booking_rules.open_status('ktv-1', r, now=at(SAT_D, 3))
        self.assertEqual((st['open_now'], st['next_open']), (False, 'today 18:00'))
        self.assertTrue(booking_rules.open_status('ktv-1', r, now=at(SUN_D, 1))['open_now'])
        self.assertFalse(booking_rules.open_status('ktv-1', r, now=at(MON_D, 1))['open_now'])
        nail = {'hours': booking_rules.DEFAULT_HOURS}
        self.assertEqual(booking_rules.open_status('n', nail, now=at(FRI_D, 10))['closes_at'], '20:00')
        st = booking_rules.open_status('n', nail, now=at(SAT_D, 1))
        self.assertEqual((st['open_now'], st['next_open']), (False, 'today 09:00'))


# ================================================================ gói AI thật (karaoke / F&B) với giờ qua nửa đêm
class KaraokeLateNight(T.KaraokeBase):
    def setUp(self):
        super().setUp()
        T.settings(hours=LATE, auto_confirm=True, **{MARK: '2026-10-30T09:00:00'})

    def test_facts_state_the_2am_close(self):
        f = karaoke.facts(T.BID, 'en', T.NOW)
        self.assertIn('Fri 6:00 pm – 2:00 am (Sat)', f)
        self.assertNotIn('00:00', f.split('OPENING HOURS:')[1].split('\n')[0])

    def test_books_a_session_that_runs_past_midnight(self):
        r = self.reserve(time='23:00', hours=3)
        self.assertTrue(r['success'], r)
        self.assertEqual(r['status'], 'confirmed')
        row = DB.karaoke_room_reservations.find_one({'id': r['reservation_id']})
        self.assertEqual((row['reserved_time'], row['duration_hours']), ('2026-10-30T23:00:00', 3.0))

    def test_books_after_midnight_on_the_next_date(self):
        r = self.reserve(time='00:30', hours=1, date='2026-10-31')
        self.assertTrue(r['success'], r)
        self.assertEqual(DB.karaoke_room_reservations.find_one({'id': r['reservation_id']})['reserved_time'],
                         '2026-10-31T00:30:00')

    def test_too_late_states_the_real_close_and_real_alternatives(self):
        r = self.call(karaoke, 'karaoke_check_rooms', {'date': T.FRI, 'time': '23:30', 'hours': 3, 'group_size': 4})
        self.assertFalse(r['requested_time']['free'])
        self.assertIn('closes at 2:00 am (Sat)', r['requested_time']['why'])
        self.assertIn('23:00', r['other_start_times_same_day'])
        self.assertNotIn('00:00', r['other_start_times_same_day'])          # 00:00 là ngày lịch thứ Bảy


class FnbLateNight(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('fnb')
        T.settings(hours={d: ['17:00', '01:00'] for d in rc.DAY_KEYS}, auto_confirm=True,
                   table={'max_covers_per_slot': 20, 'last_booking_before_close': 30}, **{MARK: '2026-10-30T09:00:00'})

    def test_reserves_00_15_on_saturday_for_friday_night(self):
        r = self.call(fnb, 'fnb_reserve_table', {'date': '2026-10-31', 'time': '00:15', 'party_size': 2,
                                                 'customer_name': 'Mia', 'phone': '0412345678'})
        self.assertTrue(r['success'], r)
        self.assertEqual(r['status'], 'confirmed')
        late = self.call(fnb, 'fnb_reserve_table', {'date': '2026-10-31', 'time': '00:45', 'party_size': 2,
                                                    'customer_name': 'Leo', 'phone': '0412345679'})
        self.assertFalse(late['success'])
        self.assertEqual(late['reason'], 'too_close_to_closing')
        self.assertIn('closes at 1:00 am (Sat)', late['message'])
        self.assertIn('latest start that fits is 00:30', late['message'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
