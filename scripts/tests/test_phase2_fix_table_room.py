# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 (khu bàn / phòng): sức chứa bàn F&B khi có nhóm lớn chờ ghép bàn, nhóm đông hơn số
khách / khung giờ, quán chưa công bố giờ mở cửa, màn nhân viên xếp phòng karaoke dùng chung khoá với AI, yêu cầu chưa xếp
phòng giữ đúng loại phòng, 1 SĐT đặt 2 phòng cùng giờ.

Dùng lại DB giả + helper của test_phase2_table_room_packs.py (mongo_client / requests / messaging được thay TRƯỚC mọi import
ở đó). KHÔNG import app.py, KHÔNG mở MongoDB thật, KHÔNG gọi mạng: route nhân viên được tách bằng ast từ app.py.

Chạy: python scripts/tests/test_phase2_fix_table_room.py
"""
import os
import sys
import types
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_table_room_packs as T  # noqa: E402  (thay mongo_client / requests / messaging trước khi nạp gói)

rc, fnb, karaoke, DB, BID, FRI = T.rc, T.fnb, T.karaoke, T.DB, T.BID, T.FRI
PackError = T.PackError


def _no_overlapping_pair(test):
    for r in DB.karaoke_room_reservations.docs:
        if r['status'] in rc.KARAOKE_ACTIVE and r.get('room_id') is not None:
            test.assertFalse(rc.karaoke_overlaps(BID, r['room_id'], r['reserved_time'], r['duration_hours'], exclude_id=r['id']),
                             r)


# ================================================================ F&B: nhóm lớn chờ ghép bàn giữ đủ bàn (finding 13)
class JoinedTablesHoldEnoughTables(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('fnb')
        T.settings(hours=T.FNB_HOURS, auto_confirm=True, table={'dining_minutes': 90})
        DB.dining_tables.insert_many([{'id': i, 'business_id': BID, 'name': f'T{i}', 'seats': 4} for i in (1, 2, 3, 4)])

    def reserve(self, party, phone, time='19:00'):
        return self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': time, 'party_size': party, 'customer_name': 'Mia',
                                                    'phone': phone})

    def test_accepted_large_group_keeps_the_tables_it_needs(self):
        big = self.reserve(12, '0411000001')
        self.assertEqual((big['status'], big['pending_reason'], big['table']), ('pending', 'large_party', None))
        results = [self.reserve(4, f'041200000{i}') for i in range(3)]
        confirmed = [r for r in results if r.get('status') == 'confirmed']
        # 12 khách cần 3 bàn 4 ghế ghép lại -> chỉ còn đúng 1 bàn cho khách khác
        self.assertEqual(len(confirmed), 1, results)
        self.assertEqual([r['reason'] for r in results if not r['success']], ['no_table', 'no_table'])
        chk = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'time': '19:00', 'party_size': 4})
        self.assertFalse(chk['requested_time']['free'])

    def test_public_form_large_request_is_counted_with_joined_tables(self):
        T.table_row(1, '2026-10-30T19:00:00', 12)                       # form công khai, chưa xếp bàn
        self.assertTrue(self.reserve(4, '0412000001')['success'])
        self.assertEqual(self.reserve(4, '0412000002')['reason'], 'no_table')

    def test_large_group_needs_enough_free_seats_not_just_one_free_table(self):
        T.table_row(1, '2026-10-30T19:00:00', 4, status='confirmed', table_id=1)
        T.table_row(2, '2026-10-30T19:00:00', 4, status='confirmed', table_id=2)
        T.table_row(3, '2026-10-30T19:00:00', 4, status='confirmed', table_id=3)
        chk = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'time': '19:00', 'party_size': 12})
        self.assertFalse(chk['requested_time']['free'])                  # 1 bàn 4 ghế không đủ cho 12 khách
        r = self.reserve(12, '0411000001')
        self.assertEqual((r['success'], r['reason']), (False, 'no_table'))
        self.assertEqual(len(DB.table_reservations.docs), 3)
        ok = self.reserve(8, '0411000002', time='21:00')                  # 21:00 cả 4 bàn trống -> nhận yêu cầu ghép bàn
        self.assertEqual((ok['status'], ok['pending_reason']), ('pending', 'large_party'))


# ================================================================ F&B: nhóm đông hơn số khách / khung giờ (finding 14)
class GroupBiggerThanSlotLimit(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('fnb')
        T.settings(hours=T.FNB_HOURS, auto_confirm=True, table={'max_covers_per_slot': 20, 'slot_minutes': 30})

    def test_is_a_large_group_request_not_fully_booked_everywhere(self):
        chk = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'time': '19:00', 'party_size': 24})
        self.assertTrue(chk['requested_time']['free'])
        self.assertIn('team reviews', chk['requested_time']['why'])
        self.assertNotIn('fully booked', chk['requested_time']['why'])
        self.assertEqual((chk['if_booked_status'], chk['pending_reason']), ('pending', 'large_party'))
        self.assertIn('19:00', chk['available_times'])
        day = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'party_size': 24})
        self.assertTrue(day['available_times'])
        r = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '19:00', 'party_size': 24, 'customer_name': 'Mia',
                                                 'phone': '0412345678'})
        self.assertTrue(r['success'])
        self.assertEqual((r['status'], r['pending_reason'], r['needs_staff']), ('pending', 'large_party', True))
        self.assertTrue(any('#%d' % r['reservation_id'] in m['content'] for m in DB.bot_messages.docs))  # chủ quán được báo
        # nhóm lớn đã chiếm trọn khung 19:00
        two = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '19:00', 'party_size': 2, 'customer_name': 'Leo',
                                                   'phone': '0499888777'})
        self.assertEqual(two['reason'], 'fully_booked')

    def test_needs_a_slot_nobody_else_booked_and_offers_real_alternatives(self):
        T.table_row(1, '2026-10-30T19:00:00', 2, status='confirmed')
        chk = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'time': '19:00', 'party_size': 24})
        self.assertFalse(chk['requested_time']['free'])
        self.assertIn('no other bookings', chk['requested_time']['why'])
        self.assertNotIn('19:00', chk['available_times'])
        self.assertIn('19:30', chk['available_times'])
        r = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '19:00', 'party_size': 24, 'customer_name': 'Mia',
                                                 'phone': '0412345678'})
        self.assertEqual((r['success'], r['reason']), (False, 'large_party_slot_taken'))
        self.assertIn('19:30', r['other_times_same_day'])
        self.assertEqual(rc.ReservationError('large_party_slot_taken').text('vi'),
                         'Nhóm đông như vậy cần 1 khung giờ chưa có ai đặt, giờ này đã có khách đặt.')

    def test_facts_tell_the_ai_about_groups_over_the_slot_limit(self):
        f = fnb.facts(BID, 'en', T.NOW)
        self.assertIn('groups over 20', f)
        self.assertIn('requests the team confirms', f)


# ================================================================ F&B: chưa công bố giờ mở cửa (finding 27)
class LiveCapacityWithoutOpeningHours(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('fnb')
        T.settings(table={'max_covers_per_slot': 4, 'slot_minutes': 30})       # sức chứa có, giờ mở cửa chưa lưu

    def test_day_check_without_time_asks_for_a_time_instead_of_looking_full(self):
        r = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'party_size': 2})
        self.assertEqual((r['availability'], r['opening_hours']), ('live', 'not published'))
        self.assertEqual(r['available_times'], [])
        self.assertIn('ask the customer for a time', r['note'])
        self.assertIn('Do not say the restaurant is full', r['note'])
        self.assertNotIn('next_available', r)

    def test_full_around_the_asked_time_offers_other_days_at_that_time(self):
        for i, m in enumerate(range(16 * 60, 22 * 60 + 1, 30)):            # 16:00-22:00 kín cả
            T.table_row(100 + i, '2026-10-30T%02d:%02d:00' % (m // 60, m % 60), 4, status='confirmed')
        chk = self.call(fnb, 'fnb_check_tables', {'date': FRI, 'time': '19:00', 'party_size': 2})
        self.assertFalse(chk['requested_time']['free'])
        self.assertEqual(chk['available_times'], [])
        self.assertTrue(chk['next_available'])
        self.assertEqual(chk['next_available'][0]['date'], '2026-10-31')
        r = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '19:00', 'party_size': 2, 'customer_name': 'Mia',
                                                 'phone': '0412345678'})
        self.assertEqual(r['reason'], 'fully_booked')
        self.assertTrue(r['next_available'])
        self.assertIn('19:00', r['next_available'][0]['first_times'])


# ================================================================ Karaoke: màn nhân viên xếp phòng dùng chung khoá (finding 31)
class StaffRoomAssignUsesTheBookingLock(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('karaoke')
        T.settings(hours=T.KTV_HOURS, auto_confirm=True)
        T.room(1, 'Room A (2-10 people)', 20)
        T.room(2, 'Room B (2-10 people)', 20)
        T.ktv_row(50, '2026-10-30T20:00:00', 2, None, status='pending')       # yêu cầu form công khai chưa xếp phòng
        ns = {'db': DB, 'datetime': datetime, 'timedelta': timedelta}
        exec(compile(T._app_function('_karaoke_reservation_overlaps'), 'app.py', 'exec'), ns)
        self.staff_overlaps = ns['_karaoke_reservation_overlaps']

    def patch(self, rid, body, overlaps=None):
        ns = {'db': DB, 'request': types.SimpleNamespace(json=body), 'session': {'business_id': BID, 'user_id': BID},
              'jsonify': lambda d: d, '_karaoke_reservation_overlaps': overlaps or self.staff_overlaps,
              '_vi_en': lambda vi, en: en}
        exec(compile(T._app_function('api_karaoke_reservation_update'), 'app.py', 'exec'), ns)
        return ns['api_karaoke_reservation_update'](rid)

    def test_ai_booking_cannot_slip_in_between_staff_check_and_write(self):
        seen = {}

        def racing(*a, **k):                     # AI đặt đúng phòng A ngay sau khi nhân viên kiểm trùng xong
            res = self.staff_overlaps(*a, **k)
            if 'ai' not in seen:
                try:
                    seen['ai'] = self.call(karaoke, 'karaoke_reserve_room',
                                           {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 4, 'room_id': 1,
                                            'customer_name': 'Kai', 'phone': '0412345678'})
                except PackError as e:
                    seen['ai'] = str(e)
            return res

        out = self.patch(50, {'room_id': 1}, overlaps=racing)
        self.assertIn('busy', str(seen['ai']))                                  # AI chờ khoá, không giữ phòng A
        self.assertEqual(out, {'success': True})
        self.assertEqual(DB.karaoke_room_reservations.find_one({'id': 50})['room_id'], 1)
        _no_overlapping_pair(self)
        self.assertEqual(DB.reservation_locks.docs, [])                         # nhả khoá sau khi ghi

    def test_staff_assignment_waits_for_an_ai_booking_in_progress(self):
        DB.reservation_locks.insert_one({'_id': f'karaoke|{BID}', 'until': 9e12, 'token': 'ai'})
        out = self.patch(50, {'room_id': 1})
        self.assertEqual(out[1], 409)
        self.assertIn('try again', out[0]['message'])
        self.assertIsNone(DB.karaoke_room_reservations.find_one({'id': 50})['room_id'])
        cancel_ok = self.patch(50, {'status': 'cancelled'})                     # huỷ không giữ phòng nào: không cần khoá
        self.assertEqual(cancel_ok, {'success': True})

    def test_reopening_a_cancelled_booking_rechecks_its_room(self):
        T.ktv_row(60, '2026-10-30T20:00:00', 2, 1, status='cancelled')
        T.ktv_row(61, '2026-10-30T21:00:00', 2, 1, status='confirmed')
        out = self.patch(60, {'status': 'confirmed'})
        self.assertEqual(out[1], 409)
        self.assertEqual(DB.karaoke_room_reservations.find_one({'id': 60})['status'], 'cancelled')
        _no_overlapping_pair(self)
        # đặt phòng đang hiệu lực đổi trạng thái (tới nơi) không bị chặn
        self.assertEqual(self.patch(61, {'status': 'arrived'}), {'success': True})
        # vẫn chặn xếp phòng trùng giờ như trước
        self.assertEqual(self.patch(50, {'room_id': 1})[1], 409)
        self.assertEqual(self.patch(50, {'room_id': 2}), {'success': True})


# ================================================================ Karaoke: yêu cầu chưa xếp phòng giữ đúng loại (finding 32)
class UnassignedRequestKeepsItsRoomKind(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('karaoke')
        T.settings(hours=T.KTV_HOURS, auto_confirm=True)
        T.room(1, 'Phòng VIP (6-10 người)', 30)
        T.room(2, 'Bàn bida 1', 8)

    def test_last_karaoke_room_is_kept_for_the_waiting_karaoke_request(self):
        T.ktv_row(50, '2026-10-30T20:00:00', 2, None, status='pending')
        chk = self.call(karaoke, 'karaoke_check_rooms', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 6})
        self.assertFalse(chk['requested_time']['free'])
        r = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 6,
                                                        'customer_name': 'Kai', 'phone': '0412345678'})
        self.assertEqual((r['success'], r['reason']), (False, 'no_room'))
        self.assertIn('22:00', r['other_start_times_same_day'])
        pool = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 2,
                                                           'room_kind': 'billiards', 'customer_name': 'Kai',
                                                           'phone': '0412345678'})
        self.assertEqual(pool['room'], 'Bàn bida 1')                         # bàn bida vẫn trống cho khách khác

    def test_billiards_request_keeps_the_table_not_the_karaoke_room(self):
        T.ktv_row(50, '2026-10-30T20:00:00', 2, None, status='pending', note='Cho mình 1 bàn bida nhé')
        r = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 6,
                                                        'customer_name': 'Kai', 'phone': '0412345678'})
        self.assertEqual(r['room'], 'Phòng VIP (6-10 người)')
        pool = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 2,
                                                           'room_kind': 'billiards', 'customer_name': 'Leo',
                                                           'phone': '0499888777'})
        self.assertEqual((pool['success'], pool['reason']), (False, 'no_room'))

    def test_unassigned_kind_rule(self):
        rooms = rc.karaoke_rooms(BID)
        self.assertEqual(rc.unassigned_kind({'note': None}, rooms), 'karaoke')
        self.assertEqual(rc.unassigned_kind({'note': 'pool table for 2'}, rooms), 'billiards')
        self.assertEqual(rc.unassigned_kind({'note': ''}, [r for r in rooms if r['kind'] == 'billiards']), 'billiards')


# ================================================================ Karaoke: 1 SĐT giữ 2 phòng cùng giờ (finding 34)
class OnePhoneTwoRoomsSameTime(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('karaoke')
        T.settings(hours=T.KTV_HOURS, auto_confirm=True)
        T.room(1, 'Room A (2-10 people)', 20)
        T.room(2, 'Room B (2-10 people)', 20)
        T.room(3, 'Pool Table 1', 6)

    def reserve(self, **kw):
        args = {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 10, 'customer_name': 'Kai', 'phone': '0412345678'}
        args.update(kw)
        return self.call(karaoke, 'karaoke_reserve_room', args)

    def test_group_split_across_two_rooms(self):
        a = self.reserve(room_id=1)
        b = self.reserve(room_id=2, group_size=10)
        self.assertTrue(b['success'])
        self.assertNotIn('already_reserved', b)
        self.assertNotEqual(a['reservation_id'], b['reservation_id'])
        self.assertEqual(sorted(r['room_id'] for r in DB.karaoke_room_reservations.docs), [1, 2])
        again = self.reserve(room_id=2)                                     # gọi lặp cho phòng B: không tạo thêm
        self.assertEqual((again['already_reserved'], again['reservation_id']), (True, b['reservation_id']))
        same_kind = self.reserve()                                          # không chọn phòng, cùng loại: vẫn là gọi lặp
        self.assertTrue(same_kind['already_reserved'])
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 2)
        _no_overlapping_pair(self)

    def test_karaoke_room_and_billiards_table_at_the_same_time(self):
        self.assertEqual(self.reserve(group_size=4)['room_id'], 1)
        pool = self.reserve(group_size=2, room_kind='billiards')
        self.assertEqual((pool['success'], pool['room']), (True, 'Pool Table 1'))
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 2)

    def test_form_request_from_the_same_phone_is_still_a_duplicate(self):
        T.ktv_row(50, '2026-10-30T20:00:00', 2, None, status='pending', phone='0412 345 678')
        r = self.reserve(room_id=1)
        self.assertTrue(r['already_reserved'])
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
