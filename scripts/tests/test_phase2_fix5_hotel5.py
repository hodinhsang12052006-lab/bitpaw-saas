# -*- coding: utf-8 -*-
"""Test OFFLINE — vòng sửa 5 khách sạn Phase 2 (hotel5):
  - yêu cầu cho nhân viên khi vượt trần giữ phòng của chat web chưa xác minh (create_staff_request): khách xin THÊM 1 phòng
    (another_room=true) = 1 dòng yêu cầu mới + 1 ghi chú mới cho nhân viên (trước đây bị gộp vào yêu cầu cũ: nhân viên thấy 1
    phòng trong khi khách xin 2); khách sửa số khách (2 -> 4) = cập nhật party_size của yêu cầu đang chờ + báo nhân viên
    (trước đây dòng giữ số khách cũ, không ghi chú gì). Yêu cầu đang chờ tính vào giới hạn số phòng mỗi chat (không ghi vô hạn
    yêu cầu bằng another_room);
  - AI Copilot của chủ: dòng 'requested' (chưa giữ phòng) KHÔNG tính là khách đến / trả phòng; được báo riêng;
  - nhận khách tại quầy (mark_checked_in): chỉ đánh dấu đặt phòng của ĐÚNG khách vừa tới (SĐT trùng, hoặc tên trùng mà SĐT
    không mâu thuẫn) — khách vãng lai vào phòng đang có đặt phòng AI chưa xác minh (không tới / giả) không nhả suất đó;
  - khách tự đổi ngày trong chat (change_dates): luôn xoá dấu "Đã xem" / "đã duyệt" của nhân viên, kể cả khi nhân viên bấm
    giữa lúc chat đọc và lúc chat ghi.

KHÔNG import app.py, KHÔNG mở MongoDB thật, KHÔNG gọi API trả phí: DB giả + stub của test_phase2_hotel_pack (mongo_client /
requests / ai_function_tools được thay TRƯỚC mọi import); route app.py lấy nguyên mã nguồn qua ast.

Chạy: python scripts/tests/test_phase2_fix5_hotel5.py
"""
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_phase2_hotel_pack as hp  # noqa: E402  (DB giả + stub TRƯỚC khi nạp reservations_hotel / ai_packs.hotel)
from test_phase2_fix_hotel import find  # noqa: E402
from test_phase2_fix3_hotel3 import ROOM_ROUTES, _Hotel, _routes, wa, web  # noqa: E402

DB, BID, D, run, resv, rh, hotel = hp.DB, hp.BID, hp.D, hp.run, hp.resv, hp.rh, hp.hotel
TODAY, PackError = hp.TODAY, hp.PackError

import ai_copilot  # noqa: E402  (cùng DB giả: mongo_client đã bị thay ở test_phase2_hotel_pack)


class _Req(_Hotel):
    def requests_(self):
        return [r for r in DB.hotel_reservations.docs if r.get('status') == rh.STAFF_REQUEST]

    def over_cap_chat(self, n=2, lang='en'):
        """Standard có 2 phòng -> trần 1 lượt giữ chưa xác minh/đêm: chat web(1) giữ suất đó, chat web(n) vượt trần."""
        self.assertIn('booking_id', self.book_as(web(1), 1))
        c = web(n, lang=lang)
        DB.bot_customers.update_one({'id': c['customer_id']}, {'$set': {'business_id': BID}}, upsert=True)
        return c


# ================================================================ 1) yêu cầu vượt trần: thêm phòng / sửa số khách
class TestStaffRequestDedupe(_Req):
    def test_another_room_makes_a_second_request_and_a_second_note(self):
        c = self.over_cap_chat()
        first = self.book_as(c, 2, guests=2)
        self.assertTrue(first['request_sent_to_team'])
        notes_before = len(hp.STAFF_NOTES)
        second = self.book_as(c, 2, guests=2, another_room=True)          # khách xin THÊM 1 phòng cùng loại, cùng ngày
        self.assertTrue(second['request_sent_to_team'])
        self.assertNotIn('booking_id', second)
        reqs = self.requests_()
        self.assertEqual(len(reqs), 2)                                    # nhân viên thấy ĐỦ 2 phòng khách xin
        self.assertEqual({r['party_size'] for r in reqs}, {2})
        self.assertEqual(len(hp.STAFF_NOTES), notes_before + 1)
        note = hp.STAFF_NOTES[-1][2]
        self.assertIn(f"#{reqs[1]['id']}", note)
        self.assertIn('ADDITIONAL room', note)
        self.assertEqual(DB.hotel_room_nights.count_documents({'reservation_id': {'$in': [r['id'] for r in reqs]}}), 0)
        self.assertNoDoubleBooking()

    def test_vi_note_for_an_additional_room(self):
        DB.businesses.update_one({'id': BID}, {'$set': {'country': 'VN', 'currency': 'VND'}})
        c = self.over_cap_chat(lang='vi')
        self.book_as(c, 2)
        self.book_as(c, 2, another_room=True)
        self.assertEqual(len(self.requests_()), 2)
        self.assertIn('THÊM 1 phòng', hp.STAFF_NOTES[-1][2])

    def test_party_size_correction_updates_the_waiting_request(self):
        c = self.over_cap_chat()
        self.assertTrue(self.book_as(c, 2, guests=1)['request_sent_to_team'])
        [req] = self.requests_()
        self.assertEqual(req['party_size'], 1)
        again = self.book_as(c, 2, guests=2)                              # "à, 2 người chứ không phải 1"
        self.assertTrue(again['request_sent_to_team'])
        [req] = self.requests_()                                          # vẫn 1 yêu cầu (cùng 1 phòng) ...
        self.assertEqual(req['party_size'], 2)                            # ... nhưng đúng số khách mới
        self.assertEqual(req.get('party_size_was'), 1)
        note = hp.STAFF_NOTES[-1][2]
        self.assertIn(f"#{req['id']}", note)
        self.assertIn('1 → 2', note)
        self.assertEqual(hp.OWNER_ALERTS[-1][3], 'hotel_webcap_change')
        self.assertIn('2 guest(s)', DB.bot_customers.find_one({'id': c['customer_id']})['handoff_reason'])
        # nói lại đúng yêu cầu đó lần nữa: không ghi thêm, không báo thêm
        n_notes = len(hp.STAFF_NOTES)
        self.assertTrue(self.book_as(c, 2, guests=2)['request_sent_to_team'])
        self.assertEqual(len(self.requests_()), 1)
        self.assertEqual(len(hp.STAFF_NOTES), n_notes)

    def test_party_size_update_never_touches_a_request_staff_already_handled(self):
        c = self.over_cap_chat()
        self.book_as(c, 2, guests=1)
        [req] = self.requests_()
        real_update = DB.hotel_reservations.update_one

        def staff_declines_first(flt, update, upsert=False):
            if flt.get('id') == req['id'] and flt.get('status') == rh.STAFF_REQUEST:
                real_update({'id': req['id']}, {'$set': {'status': 'cancelled'}})   # nhân viên vừa bấm Từ chối
            return real_update(flt, update, upsert=upsert)
        DB.hotel_reservations.update_one = staff_declines_first
        try:
            out = self.book_as(c, 2, guests=2)
        finally:
            DB.hotel_reservations.update_one = real_update
        self.assertTrue(out['request_sent_to_team'])
        self.assertEqual(find(req['id'])['status'], 'cancelled')
        self.assertEqual(find(req['id'])['party_size'], 1)                # không sửa dòng nhân viên đã xử lý
        [new] = self.requests_()                                          # yêu cầu mới không bị lạc
        self.assertEqual(new['party_size'], 2)

    def test_another_browser_with_the_same_typed_phone_cannot_edit_the_request(self):
        c = self.over_cap_chat()
        self.book_as(c, 2, guests=1)
        [req] = self.requests_()
        other = dict(c, chat_token_hash='tok-someone-else')                # cùng hội thoại '<khách sạn>:<SĐT gõ>', máy khác
        out = self.book_as(other, 2, guests=2)
        self.assertTrue(out['request_sent_to_team'])
        self.assertEqual(find(req['id'])['party_size'], 1)                # yêu cầu của chat kia KHÔNG bị sửa
        self.assertNotIn('party_size_was', find(req['id']))
        self.assertEqual(sorted(r['party_size'] for r in self.requests_()), [1, 2])   # máy khác = yêu cầu mới
        self.assertNotIn(str(req['id']), str(out))

    def test_create_staff_request_states(self):
        kw = dict(checkin=D(8), checkout=D(10), room_type='Standard', guest_name='Guest Number2', guest_phone='0499999902',
                  extra={'ai_conversation_id': 'conv-2', 'source': 'ai_bot'})
        a, s1 = rh.create_staff_request(BID, guests=2, **kw)
        b, s2 = rh.create_staff_request(BID, guests=2, **kw)
        c, s3 = rh.create_staff_request(BID, guests=3, **kw)
        d, s4 = rh.create_staff_request(BID, guests=3, another_room=True, **kw)
        self.assertEqual((s1, s2, s3, s4), ('created', 'duplicate', 'updated', 'created'))
        self.assertEqual(a['id'], b['id'])
        self.assertEqual((c['id'], c['party_size'], c['party_size_was']), (a['id'], 3, 2))
        self.assertNotEqual(d['id'], a['id'])
        self.assertEqual(len(self.requests_()), 2)

    def test_waiting_requests_count_toward_the_rooms_per_chat_limit(self):
        c = self.over_cap_chat()
        self.book_as(c, 2)
        for _ in range(hotel.MAX_LIVE_AI_BOOKINGS_PER_GUEST - 1):
            self.assertTrue(self.book_as(c, 2, another_room=True)['request_sent_to_team'])
        self.assertEqual(len(self.requests_()), hotel.MAX_LIVE_AI_BOOKINGS_PER_GUEST)
        with self.assertRaises(PackError) as cm:                          # không ghi vô hạn yêu cầu bằng another_room
            self.book_as(c, 2, another_room=True)
        self.assertIn('group booking', str(cm.exception))
        self.assertIn('booked or requested', str(cm.exception))
        self.assertEqual(len(self.requests_()), hotel.MAX_LIVE_AI_BOOKINGS_PER_GUEST)

    def test_declined_or_past_requests_do_not_count(self):
        c = self.over_cap_chat()
        self.book_as(c, 2)
        self.book_as(c, 2, another_room=True)
        for r in self.requests_():
            DB.hotel_reservations.update_one({'id': r['id']}, {'$set': {'status': 'cancelled'}})
        DB.hotel_reservations.insert_one(resv(990, D(-5), D(-3), source='ai_bot', status=rh.STAFF_REQUEST,
                                              ai_conversation_id=c['customer_id']))
        for _ in range(hotel.MAX_LIVE_AI_BOOKINGS_PER_GUEST):
            self.assertTrue(self.book_as(c, 2, another_room=True)['request_sent_to_team'])


# ================================================================ 2) AI Copilot: 'requested' không phải khách đến
class TestCopilotArrivals(unittest.TestCase):
    def setUp(self):
        DB.reset()

    def block(self):
        ctx = types.SimpleNamespace(bid=BID, today=TODAY, money=lambda v: f"${v:.2f}", bills30=lambda: [])
        return '\n'.join(ai_copilot._block_hotel(ctx))

    def test_requests_are_not_arrivals_and_are_reported_apart(self):
        DB.hotel_reservations.insert_many([
            resv(1, D(0), D(2), status='confirmed'),
            resv(2, D(3), D(5), status='pending'),
            resv(3, D(1), D(2), status='cancelled'),
            resv(4, D(-3), D(0), status='confirmed'),
            resv(5, D(0), D(1), status=rh.STAFF_REQUEST),        # yêu cầu chưa giữ phòng: hôm nay
            resv(6, D(4), D(6), status=rh.STAFF_REQUEST),
            resv(7, D(20), D(22), status=rh.STAFF_REQUEST),      # ngoài 7 ngày nhưng vẫn đang chờ
            resv(8, D(-2), D(0), status=rh.STAFF_REQUEST),       # ngày đã qua: không còn tính
        ])
        text = self.block()
        self.assertIn('ARRIVALS (reservations): today 1, next 7 days 2 (1 still pending); departures today 1.', text)
        self.assertIn('BOOKING REQUESTS waiting for the team (no room held yet, not counted as arrivals above): 3 '
                      '(2 arriving in the next 7 days)', text)
        self.assertIn('Hotel > Reservations', text)

    def test_no_request_line_when_there_are_none(self):
        DB.hotel_reservations.insert_one(resv(1, D(0), D(2), status='confirmed'))
        text = self.block()
        self.assertIn('ARRIVALS (reservations): today 1, next 7 days 1 (0 still pending); departures today 0.', text)
        self.assertNotIn('BOOKING REQUESTS', text)

    def test_uses_the_reservations_module_status(self):
        with open(os.path.join(hp.ROOT, 'ai_copilot.py'), encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('STAFF_REQUEST', src)
        self.assertNotIn("'requested'", src)


# ================================================================ 3) nhận khách tại quầy: chỉ đặt phòng của đúng khách
class TestCheckInMatchesTheGuest(_Req):
    def checkin(self, room_id, **body):
        ns, req = _routes(ROOM_ROUTES)
        req.json = dict({'expected_checkout_date': D(2)}, **body)
        return ns['api_hotel_room_checkin'](room_id)

    def test_walk_in_does_not_release_someone_elses_unverified_hold(self):
        a = self.book_as(web(1), 1, checkin_date=D(0), checkout_date=D(2))      # AI giữ phòng 101 cho "Guest Number1"
        self.assertEqual(find(a['booking_id'])['room_id'], 1)
        out = self.checkin(1, guest_name='Walk In Person', guest_phone='0411 111 111')   # khách vãng lai, người khác
        self.assertTrue(out['success'], out)
        doc = find(a['booking_id'])
        self.assertFalse(doc.get('checked_in_at'))
        self.assertFalse(doc.get('staff_reviewed_at'))
        self.assertTrue(rh.unverified_web_hold(doc))                           # vẫn tính vào trần
        b = self.book_as(web(2), 2, checkin_date=D(0), checkout_date=D(2))
        self.assertTrue(b.get('request_sent_to_team'))
        self.assertNotIn('booking_id', b)

    def test_multi_night_no_show_hold_is_not_released_by_a_walk_in(self):
        DB.hotel_reservations.insert_one(resv(901, D(-1), D(3), room_id=1, source='ai_bot', ai_verified=False,
                                              guest_name='No Show', phone='0477777777'))
        self.assertEqual(rh.mark_checked_in(BID, 1, TODAY, guest_name='Someone Else', guest_phone='0466666666'), 0)
        self.assertFalse(find(901).get('checked_in_at'))
        self.assertTrue(rh.unverified_web_hold(find(901)))

    def test_the_booked_guest_is_recognised(self):
        rows = [resv(911, D(0), D(2), room_id=1, source='ai_bot', ai_verified=False, guest_name='Guest Number1',
                     phone='0499999901')]
        cases = [({'guest_name': 'G. Number', 'guest_phone': '0499 999 901'}, True),     # cùng SĐT, ghi khác cách
                 ({'guest_name': '  guest   NUMBER1 '}, True),                           # cùng tên, quầy không ghi SĐT
                 ({'guest_name': 'Guest Number1', 'guest_phone': '0488888888'}, False),  # cùng tên nhưng SĐT khác hẳn
                 ({'guest_name': 'Guest Number2', 'guest_phone': ''}, False),
                 ({'guest_name': '', 'guest_phone': ''}, False)]
        for who, stamped in cases:
            with self.subTest(who=who):
                DB.hotel_reservations.docs[:] = [dict(r) for r in rows]
                n = rh.mark_checked_in(BID, 1, TODAY, **who)
                self.assertEqual((n, bool(find(911).get('checked_in_at'))), (int(stamped), stamped))
                self.assertEqual(rh.unverified_web_hold(find(911)), not stamped)

    def test_phone_in_international_format_matches_with_the_hotel_country(self):
        DB.hotel_reservations.insert_one(resv(921, D(0), D(2), room_id=1, source='ai_bot', ai_verified=False,
                                              guest_name='Guest Number1', phone='0499999901'))
        pkg = sys.modules['ai_packs']
        had = hasattr(pkg, 'shop_country')
        pkg.shop_country = lambda bid: 'AU'
        try:
            self.assertEqual(rh.mark_checked_in(BID, 1, TODAY, guest_name='Mr Number', guest_phone='+61 499 999 901'), 1)
        finally:
            if not had:
                del pkg.shop_country
        self.assertTrue(find(921).get('checked_in_at'))

    def test_only_the_matching_booking_of_that_room_tonight(self):
        DB.hotel_reservations.insert_many([
            resv(701, D(-1), D(1), room_id=1, source='ai_bot', ai_verified=False, guest_name='Ann Lee'),
            resv(702, D(3), D(5), room_id=1, source='ai_bot', ai_verified=False, guest_name='Ann Lee'),   # chưa tới ngày
            resv(704, D(0), D(1), room_id=2, source='ai_bot', ai_verified=False, guest_name='Ann Lee'),   # phòng khác
            resv(705, D(0), D(1), room_id=1, source='ai_bot', ai_verified=False, guest_name='Ann Lee', status='cancelled')])
        self.assertEqual(rh.mark_checked_in(BID, 1, TODAY, guest_name='Ann Lee'), 1)
        self.assertEqual([r['id'] for r in DB.hotel_reservations.docs if r.get('checked_in_at')], [701])

    def test_route_passes_the_arriving_guest(self):
        a = self.book_as(web(1), 1, checkin_date=D(0), checkout_date=D(2))
        out = self.checkin(1, guest_name='Someone', guest_phone='0499 999 901')   # SĐT đúng khách đã đặt
        self.assertTrue(out['success'], out)
        self.assertTrue(find(a['booking_id']).get('checked_in_at'))
        self.assertIn('booking_id', self.book_as(web(2), 2, checkin_date=D(0), checkout_date=D(2)))
        self.assertNoDoubleBooking()


# ================================================================ 4) đổi ngày luôn xoá dấu nhân viên đã xem / đã duyệt
class TestChangeDatesClearsStaffStamps(_Req):
    def test_mark_reviewed_between_read_and_write_does_not_survive_the_move(self):
        a = self.book_as(web(1), 1, checkin_date=D(20), checkout_date=D(21))
        res = find(a['booking_id'])                                        # chat đọc đặt phòng (chưa ai xem)
        self.assertFalse(res.get('staff_reviewed_at'))
        DB.hotel_reservations.update_one({'id': a['booking_id']},          # nhân viên bấm "Đã xem" đúng lúc đó (ngày cũ)
                                         {'$set': {'staff_reviewed_at': '2026-11-02T00:00:00',
                                                   'staff_confirmed_at': '2026-11-02T00:00:00'}})
        doc, _av = rh.change_dates(BID, res, D(22), D(23), today=TODAY)
        self.assertIsNotNone(doc)
        row = find(a['booking_id'])
        self.assertEqual((row['checkin_date'], row['checkout_date']), (D(22), D(23)))
        self.assertIsNone(row['staff_reviewed_at'])                        # ngày mới chưa ai xem
        self.assertIsNone(row['staff_confirmed_at'])
        self.assertTrue(rh.unverified_web_hold(row))                       # tính lại vào trần ở đêm mới
        rooms = rh.list_rooms(BID)
        self.assertTrue(rh.web_holds_full(BID, rooms, rh.room_types(rooms), 'standard', D(22), D(23)))

    def test_unassigned_booking_move_clears_the_stamps_too(self):
        DB.hotel_reservations.insert_one(resv(931, D(20), D(21), room_type='Standard', source='ai_bot', ai_verified=False,
                                              status='pending'))
        res = find(931)
        DB.hotel_reservations.update_one({'id': 931}, {'$set': {'staff_reviewed_at': 'x'}})
        doc, _av = rh.change_dates(BID, res, D(22), D(23), today=TODAY)
        self.assertIsNotNone(doc)
        self.assertIsNone(find(931)['staff_reviewed_at'])


if __name__ == '__main__':
    unittest.main(verbosity=1)
