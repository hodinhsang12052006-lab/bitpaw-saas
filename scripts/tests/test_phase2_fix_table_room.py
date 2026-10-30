# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 (khu bàn / phòng): sức chứa bàn F&B khi có nhóm lớn chờ ghép bàn, nhóm đông hơn số
khách / khung giờ, quán chưa công bố giờ mở cửa, màn nhân viên xếp phòng karaoke dùng chung khoá với AI, yêu cầu chưa xếp
phòng giữ đúng loại phòng, 1 SĐT đặt 2 phòng cùng giờ.
Vòng 2: đổi phòng đi qua karaoke_change_reservation (room_id, nhả phòng cũ) — karaoke_reserve_room không lặng lẽ tạo đặt phòng
thứ 2 khi chat đã giữ 1 phòng giờ đó (trừ extra_room=true); quán chỉ có phòng karaoke không đoán 'bida' từ ghi chú; ô
opening_hours của công cụ kiểm chỗ tính cả ca đêm qua nửa đêm; form công khai lưu room_kind.

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
                                                           'phone': '0499888777'},
                         T.web_ctx(token='z' * 40, customer_id=f'{BID}:0499888777'))     # khách khác, chat khác
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
        b = self.reserve(room_id=2, group_size=10, extra_room=True)         # khách nói rõ: thêm 1 phòng nữa
        self.assertTrue(b['success'])
        self.assertNotIn('already_reserved', b)
        self.assertNotEqual(a['reservation_id'], b['reservation_id'])
        self.assertEqual([h['reservation_id'] for h in b['also_holds']], [a['reservation_id']])   # AI nói đủ cả 2 phòng
        self.assertEqual(sorted(r['room_id'] for r in DB.karaoke_room_reservations.docs), [1, 2])
        again = self.reserve(room_id=2, extra_room=True)                    # gọi lặp cho phòng B: không tạo thêm
        self.assertEqual((again['already_reserved'], again['reservation_id']), (True, b['reservation_id']))
        same_kind = self.reserve()                                          # không chọn phòng, cùng loại: vẫn là gọi lặp
        self.assertTrue(same_kind['already_reserved'])
        self.assertIn('extra_room=true', same_kind['note'])                 # ... và chỉ AI cách giữ thêm phòng (room_id)
        self.assertIn('room_id', same_kind['note'])
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 2)
        _no_overlapping_pair(self)

    def test_karaoke_room_and_billiards_table_at_the_same_time(self):
        self.assertEqual(self.reserve(group_size=4)['room_id'], 1)
        pool = self.reserve(group_size=2, room_kind='billiards', extra_room='true')
        self.assertEqual((pool['success'], pool['room']), (True, 'Pool Table 1'))
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 2)

    def test_form_request_from_the_same_phone_is_still_a_duplicate(self):
        T.ktv_row(50, '2026-10-30T20:00:00', 2, None, status='pending', phone='0412 345 678')
        r = self.reserve(room_id=1)
        # chat chưa chứng minh là chủ: không tạo dòng thứ 2, không lộ số / giờ / phòng của đặt phòng kia
        self.assertTrue(r['request_sent_to_team'])
        self.assertEqual(r['status'], 'pending')
        for key in ('already_reserved', 'reservation_id', 'start', 'existing_bookings', 'also_holds'):
            self.assertNotIn(key, r)
        self.assertNotIn('50', T.json.dumps(r))
        self.assertNotIn('20:00', T.json.dumps(r))
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 1)
        self.assertTrue(any('#50' in m['content'] for m in DB.bot_messages.docs))           # quán được báo để gọi khách
        # khách nói rõ muốn THÊM phòng B: đặt được, và vẫn không lộ gì về đặt phòng kia
        extra = self.reserve(room_id=2, extra_room=True)
        self.assertEqual((extra['success'], extra['room_id']), (True, 2))
        self.assertNotIn('also_holds', extra)
        DB.karaoke_room_reservations.docs[:] = [d for d in DB.karaoke_room_reservations.docs if d['id'] == 50]
        # chat CHỨNG MINH được là chủ (SĐT đã xác minh): vẫn là gọi lặp, đúng đặt phòng cũ
        own = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 10,
                                                          'customer_name': 'Kai', 'room_id': 1},
                        T.web_ctx(phone='0412345678'))
        self.assertEqual((own['already_reserved'], own['reservation_id']), (True, 50))
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 1)


# ================================================================ Karaoke: đổi phòng = karaoke_change_reservation (vòng 2, #34)
class SwitchingRoomsGoesThroughChange(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('karaoke')
        T.settings(hours=T.KTV_HOURS, auto_confirm=True)
        T.room(1, 'Room A (2-10 people)', 20)
        T.room(2, 'VIP Room (2-10 people)', 40)
        T.room(3, 'Mini Room (2-4 people)', 10)
        T.room(4, 'Pool Table 1', 6)

    def reserve(self, ctx=None, **kw):
        args = {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 6, 'customer_name': 'Kai', 'phone': '0412345678'}
        args.update(kw)
        return self.call(karaoke, 'karaoke_reserve_room', args, ctx)

    def change(self, ctx=None, **kw):
        return self.call(karaoke, 'karaoke_change_reservation', kw, ctx)

    def active(self):
        return [d for d in DB.karaoke_room_reservations.docs if d['status'] in rc.KARAOKE_ACTIVE]

    def test_switch_asked_through_reserve_books_nothing_and_points_to_change(self):
        a = self.reserve()                                                  # phòng A, AI không chọn phòng
        self.assertEqual(a['room_id'], 1)
        r = self.reserve(room_id=2)                                         # "cho mình đổi sang phòng VIP"
        self.assertFalse(r['success'])
        self.assertEqual(r['reason'], 'chat_already_holds_a_room')
        self.assertTrue(r['nothing_created'])
        self.assertEqual([(b['reservation_id'], b['room']) for b in r['existing_bookings']],
                         [(a['reservation_id'], 'Room A (2-10 people)')])
        self.assertIn('karaoke_change_reservation', r['message'])
        self.assertIn('extra_room=true', r['message'])
        self.assertEqual([(d['id'], d['room_id']) for d in self.active()], [(a['reservation_id'], 1)])
        # chồng giờ dù khác giờ bắt đầu (20:00-22:00 và 21:00) cũng không lặng lẽ thành 2 phòng
        later = self.reserve(room_id=2, time='21:00')
        self.assertEqual(later['reason'], 'chat_already_holds_a_room')
        self.assertEqual(len(self.active()), 1)
        # nối tiếp (22:00, hết chồng giờ) là đặt phòng mới bình thường
        self.assertTrue(self.reserve(room_id=2, time='22:00')['success'])

    def test_change_with_room_id_moves_the_booking_and_releases_the_old_room(self):
        a = self.reserve()
        r = self.change(reservation_id=a['reservation_id'], room_id=2)
        self.assertTrue(r['success'])
        self.assertEqual((r['room'], r['room_changed'], r['previous_room']), ('VIP Room (2-10 people)', True,
                                                                                 'Room A (2-10 people)'))
        self.assertEqual((r['start'], r['estimated_room_charge']), ('2026-10-30 20:00', '$80.00'))
        self.assertEqual([(d['id'], d['room_id']) for d in self.active()], [(a['reservation_id'], 2)])
        self.assertTrue(any('#%d' % a['reservation_id'] in m['content'] and 'Room A' in m['content'] and 'VIP' in m['content']
                            for m in DB.bot_messages.docs))                    # quán thấy phòng cũ -> phòng mới
        leo = T.web_ctx(token='z' * 40, customer_id=f'{BID}:0499888777')
        other = self.reserve(ctx=leo, room_id=1, phone='0499888777', customer_name='Leo')   # phòng A đã nhả cho khách khác
        self.assertEqual((other['success'], other['room_id']), (True, 1))
        _no_overlapping_pair(self)
        self.assertEqual(DB.reservation_locks.docs, [])

    def test_change_room_and_time_together(self):
        a = self.reserve()
        r = self.change(reservation_id=a['reservation_id'], room_id=2, time='21:00', hours=3)
        self.assertEqual((r['success'], r['room'], r['start'], r['end']),
                         (True, 'VIP Room (2-10 people)', '2026-10-30 21:00', '2026-10-31 00:00'))

    def test_change_to_a_taken_room_leaves_the_booking_unchanged(self):
        T.ktv_row(60, '2026-10-30T19:00:00', 3, 2)                          # VIP của khách khác 19:00-22:00
        a = self.reserve()
        r = self.change(reservation_id=a['reservation_id'], room_id=2)
        self.assertEqual((r['success'], r['reason'], r['reservation_unchanged']), (False, 'room_taken', True))
        self.assertNotIn(2, [x['room_id'] for x in r['other_free_rooms']])
        self.assertEqual(DB.karaoke_room_reservations.find_one({'id': a['reservation_id']})['room_id'], 1)
        _no_overlapping_pair(self)

    def test_change_room_checks_the_room_under_the_booking_lock(self):
        a = self.reserve()
        DB.reservation_locks.insert_one({'_id': f'karaoke|{T.BID}', 'until': 9e12, 'token': 'staff'})
        msg = self.refuse(karaoke, 'karaoke_change_reservation', {'reservation_id': a['reservation_id'], 'room_id': 2})
        self.assertIn('busy', msg)
        self.assertEqual(DB.karaoke_room_reservations.find_one({'id': a['reservation_id']})['room_id'], 1)

    def test_change_room_id_must_be_a_real_room_that_fits_the_group(self):
        a = self.reserve()
        self.assertIn('room_id', self.refuse(karaoke, 'karaoke_change_reservation',
                                             {'reservation_id': a['reservation_id'], 'room_id': 99}))
        self.assertIn('up to 4', self.refuse(karaoke, 'karaoke_change_reservation',
                                             {'reservation_id': a['reservation_id'], 'room_id': 3}))
        self.assertTrue(self.change(reservation_id=a['reservation_id'], room_id=1)['unchanged'])    # đúng phòng đang giữ
        small = self.change(reservation_id=a['reservation_id'], room_id=3, group_size=4)            # nhóm ít lại -> vừa
        self.assertEqual((small['room'], small['group_size']), ('Mini Room (2-4 people)', 4))

    def test_change_room_refuses_other_peoples_bookings(self):
        T.ktv_row(60, '2026-10-30T20:00:00', 2, 1, phone='0412345678')      # cùng SĐT, form công khai: không phải của chat
        self.refuse(karaoke, 'karaoke_change_reservation', {'reservation_id': 60, 'room_id': 2})
        self.assertEqual(DB.karaoke_room_reservations.find_one({'id': 60})['room_id'], 1)

    def test_extra_room_when_the_customer_clearly_wants_another_room(self):
        a = self.reserve(group_size=10)
        b = self.reserve(room_id=2, group_size=8, extra_room=True)
        self.assertTrue(b['success'])
        self.assertEqual(b['room_id'], 2)
        self.assertEqual(b['also_holds'][0]['reservation_id'], a['reservation_id'])
        self.assertIn('extra room', b['also_holds_note'])
        self.assertEqual(len(self.active()), 2)
        self.assertTrue(any('#%d' % a['reservation_id'] in m['content'] and '#%d' % b['reservation_id'] in m['content']
                            for m in DB.bot_messages.docs))                    # quán biết đây là phòng thêm

    def test_chat_that_cannot_prove_ownership_gets_no_second_room_and_no_details(self):
        anon = T.web_ctx(token=None)
        a = self.reserve(ctx=anon)
        self.assertTrue(a['success'])
        r = self.reserve(ctx=anon, room_id=2)                               # đổi phòng? thêm phòng? chat không chứng minh được
        self.assertTrue(r['request_sent_to_team'])
        self.assertNotIn('existing_bookings', r)
        self.assertNotIn(str(a['reservation_id']), T.json.dumps(r))
        self.assertEqual(len(self.active()), 1)
        self.assertTrue(self.reserve(ctx=anon, room_id=2, extra_room=True)['success'])            # nói rõ: thêm phòng

    def test_unassigned_owned_request_keeps_its_kind_when_moved(self):
        T.ktv_row(70, '2026-10-30T20:00:00', 2, None, status='pending', phone='0412345678', note='1 bàn pool nhé')
        own = T.web_ctx(phone='0412345678')                                 # SĐT đã xác minh = chủ đặt phòng form công khai
        r = self.change(ctx=own, reservation_id=70, time='21:00')
        self.assertEqual((r['success'], r['room']), (True, 'Pool Table 1'))  # vẫn là bàn bida, không bị đổi thành phòng hát

    def test_tool_contract_tells_the_ai_which_tool_to_use(self):
        tools = {t['function']['name']: t['function'] for t in karaoke.TOOLS}
        change, reserve = tools['karaoke_change_reservation'], tools['karaoke_reserve_room']
        self.assertEqual(change['parameters']['properties']['room_id']['type'], 'integer')
        self.assertNotIn('room_id', change['parameters']['required'])
        self.assertIn('room', change['description'].lower())
        self.assertEqual(reserve['parameters']['properties']['extra_room']['type'], 'boolean')
        self.assertNotIn('extra_room', reserve['parameters']['required'])
        self.assertIn('karaoke_change_reservation', reserve['description'])
        self.assertIn('karaoke_change_reservation', reserve['parameters']['properties']['extra_room']['description'])
        for lang in ('en', 'vi'):
            self.assertIn('extra_room', karaoke.PROMPT_RULES[lang])
            self.assertIn('room_id', karaoke.PROMPT_RULES[lang])


# ================================================================ Karaoke: quán chỉ có phòng hát không đoán 'bida' (vòng 2, #32)
class BilliardsGuessOnlyWhenTheVenueHasBilliards(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('karaoke')
        T.settings(hours=T.KTV_HOURS, auto_confirm=True)

    def test_karaoke_only_venue_counts_a_pool_party_note_as_a_karaoke_request(self):
        T.room(1, 'Room A (2-10 people)', 20)
        T.ktv_row(50, '2026-10-30T20:00:00', 2, None, status='pending', note='after the pool party')
        chk = self.call(karaoke, 'karaoke_check_rooms', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 4})
        self.assertFalse(chk['requested_time']['free'])
        r = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 4,
                                                        'customer_name': 'Kai', 'phone': '0412345678'})
        self.assertEqual((r['success'], r['reason']), (False, 'no_room'))     # phòng duy nhất vẫn chừa cho yêu cầu chờ xếp
        self.assertEqual(len(DB.karaoke_room_reservations.docs), 1)

    def test_unassigned_kind_rules(self):
        T.room(1, 'Room A (2-10 people)', 20)
        ktv_only = rc.karaoke_rooms(T.BID)
        T.room(2, 'Bàn bida 1', 8)
        mixed = rc.karaoke_rooms(T.BID)
        pool_only = [r for r in mixed if r['kind'] == 'billiards']
        ua = rc.unassigned_kind
        self.assertEqual(ua({'note': 'after the pool party'}, ktv_only), 'karaoke')
        self.assertEqual(ua({'note': 'cho 1 bàn bida'}, ktv_only), 'karaoke')
        self.assertEqual(ua({'note': 'pool table for 2'}, mixed), 'billiards')
        self.assertEqual(ua({'note': None}, mixed), 'karaoke')
        self.assertEqual(ua({'note': None}, pool_only), 'billiards')
        # loại khách chọn trên form công khai thắng mọi phỏng đoán — nếu quán có loại đó
        self.assertEqual(ua({'room_kind': 'billiards', 'note': None}, mixed), 'billiards')
        self.assertEqual(ua({'room_kind': 'karaoke', 'note': 'bida sau'}, mixed), 'karaoke')
        self.assertEqual(ua({'room_kind': 'billiards', 'note': None}, ktv_only), 'karaoke')
        self.assertEqual(ua({'room_kind': 'VIP', 'note': None}, mixed), 'karaoke')

    def test_form_request_that_chose_billiards_holds_the_table(self):
        T.room(1, 'Room A (2-10 people)', 20)
        T.room(2, 'Bàn bida 1', 8)
        T.ktv_row(50, '2026-10-30T20:00:00', 2, None, status='pending', room_kind='billiards')
        pool = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 2,
                                                           'room_kind': 'billiards', 'customer_name': 'Kai',
                                                           'phone': '0412345678'})
        self.assertEqual((pool['success'], pool['reason']), (False, 'no_room'))
        ktv = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 2,
                                                          'customer_name': 'Kai', 'phone': '0412345678'})
        self.assertEqual(ktv['room'], 'Room A (2-10 people)')


# ================================================================ ô opening_hours của công cụ kiểm chỗ: ca đêm qua nửa đêm
LATE_SAT = {'mon': None, 'tue': None, 'wed': None, 'thu': None, 'fri': None, 'sat': ['18:00', '02:00'], 'sun': None}
SAT = '2026-10-31'


class OpeningHoursFieldKnowsOvernightShifts(T.Base):
    def test_fnb_closed_day_after_a_late_night_is_not_closed(self):
        T.biz('fnb')
        T.settings(hours=LATE_SAT, table={'max_covers_per_slot': 20})
        sun = self.call(fnb, 'fnb_check_tables', {'date': T.SUN, 'time': '01:00', 'party_size': 2})
        self.assertNotEqual(sun['opening_hours'], 'closed')
        self.assertEqual(sun['opening_hours'], 'Sat 6:00 pm – 2:00 am (Sun), Sun closed')   # vòng 3: kiểu giờ chung
        self.assertTrue(sun['requested_time']['free'])                    # 01:00 Chủ nhật đặt được thật
        sat = self.call(fnb, 'fnb_check_tables', {'date': SAT, 'party_size': 2})
        self.assertEqual(sat['opening_hours'], 'Sat 6:00 pm – 2:00 am (Sun)')
        mon = self.call(fnb, 'fnb_check_tables', {'date': '2026-11-02', 'party_size': 2})
        self.assertEqual(mon['opening_hours'], 'Mon closed')

    def test_karaoke_closed_day_after_a_late_night_is_not_closed(self):
        T.biz('karaoke')
        T.settings(hours=LATE_SAT, auto_confirm=True)
        T.room(1, 'Room A (2-10 people)', 20)
        sun = self.call(karaoke, 'karaoke_check_rooms', {'date': T.SUN, 'time': '00:00', 'hours': 1, 'group_size': 4})
        self.assertEqual(sun['opening_hours'], 'Sat 6:00 pm – 2:00 am (Sun), Sun closed')   # vòng 3: kiểu giờ chung
        self.assertNotEqual(sun['opening_hours'], 'closed')
        self.assertTrue(sun['requested_time']['free'])
        self.assertEqual(self.call(karaoke, 'karaoke_check_rooms', {'date': SAT})['opening_hours'],
                         'Sat 6:00 pm – 2:00 am (Sun)')
        self.assertEqual(self.call(karaoke, 'karaoke_check_rooms', {'date': '2026-11-02'})['opening_hours'], 'Mon closed')

    def test_not_published_is_still_said(self):
        T.biz('karaoke')
        T.room(1, 'Room A (2-10 people)', 20)
        self.assertEqual(self.call(karaoke, 'karaoke_check_rooms', {'date': FRI})['opening_hours'], 'not published')


# ================================================================ form công khai: khách chọn phòng hát / bàn bida (room_kind)
class PublicFormRoomKind(T.Base):
    def run_route(self, body):
        ns = {'request': types.SimpleNamespace(json=body), 'jsonify': lambda d: d,
              '_public_reservation_check': lambda bid, data: (None, (data, False)), 'datetime': datetime}
        exec(compile(T._app_function('api_public_karaoke_reservation_create'), 'app.py', 'exec'), ns)
        out = ns['api_public_karaoke_reservation_create'](BID)
        return DB.karaoke_room_reservations.find_one({'id': out['id']})

    def body(self, **kw):
        b = {'name': 'Kai', 'phone': '0412345678', 'party_size': 2, 'reserved_time': '2026-10-30T20:00:00', 'note': ''}
        b.update(kw)
        return b

    def test_route_stores_only_a_kind_the_venue_really_has(self):
        T.biz('karaoke')
        T.room(1, 'Room A (2-10 people)', 20)
        self.assertNotIn('room_kind', self.run_route(self.body(room_kind='billiards')))   # quán không có bàn bida
        T.room(2, 'Pool Table 1', 6)
        self.assertEqual(self.run_route(self.body(room_kind='Billiards '))['room_kind'], 'billiards')
        self.assertEqual(self.run_route(self.body(room_kind='karaoke'))['room_kind'], 'karaoke')
        for junk in ('vip', '', None, ['billiards'], {'$ne': 1}):
            self.assertNotIn('room_kind', self.run_route(self.body(room_kind=junk)), junk)
        row = self.run_route(self.body())
        self.assertEqual((row['room_id'], row['status'], row['source']), (None, 'pending', 'web'))

    def render(self, **kw):
        import jinja2
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(T.ROOT, 'templates')), autoescape=True)
        ctx = dict(kind='karaoke', business_id=BID, default_lang='en', shop_name='Test Venue', shop_phone='', shop_address='',
                   shop_logo_url='')
        ctx.update(kw)
        return env.get_template('public_reservation.html').render(**ctx)

    def test_form_shows_the_choice_only_when_the_venue_has_both_kinds(self):
        both = self.render(room_kinds=['karaoke', 'billiards'])
        self.assertIn('name="room_kind"', both)
        self.assertIn('Billiards / pool table', both)
        self.assertIn('Bàn bida', self.render(room_kinds=['karaoke', 'billiards'], default_lang='vi'))
        self.assertIn("body.room_kind", both)
        for kw in ({}, {'room_kinds': ['karaoke']}, {'room_kinds': ['billiards']}):
            self.assertNotIn('name="room_kind"', self.render(**kw), kw)
        self.assertNotIn('name="room_kind"', self.render(kind='table', room_kinds=['karaoke', 'billiards']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
