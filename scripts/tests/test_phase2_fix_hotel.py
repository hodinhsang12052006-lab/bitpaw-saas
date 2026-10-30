# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi khách sạn Phase 2 tìm được qua rà soát đối kháng (ai_packs/hotel.py, reservations_hotel.py,
route nhân viên PATCH /api/hotel_reservations/<id> trong app.py):
  #9  kéo dài / dời ngày không bị báo "kín phòng" vì tính cả đặt phòng của CHÍNH khách (báo giá + gợi ý ngày gần);
  #16 đổi ngày / số khách không thoát được hạn huỷ miễn phí của đặt phòng đã xác nhận (was_confirmed);
  #17 giá báo khi đổi ngày = giá được ghi (cùng phòng, cùng giá; giá đổi giữa chừng -> không ghi);
  #18 nhân viên bấm "Duyệt" trên trang cũ không mở lại đặt phòng khách đã huỷ trong chat;
  #19 xếp phòng theo bản đọc cũ (khách vừa đổi ngày trong chat) không thể xếp trùng phòng;
  #28 khách vãng lai đang ở (không có ngày trả phòng) không bị AI tự xác nhận phòng đó cho các đêm sau;
  #35 yêu cầu còn 'pending' không huỷ được qua chat từ ngày nhận phòng (giữa kỳ lưu trú);
  #36 có free_cancel_hours mà chưa có giờ nhận phòng: AI nói đúng mốc 00:00 mà hệ thống áp dụng.

KHÔNG import app.py, KHÔNG mở MongoDB thật, KHÔNG gọi API trả phí: dùng lại DB giả + stub của test_phase2_hotel_pack
(mongo_client / requests / ai_function_tools được thay TRƯỚC mọi import); route app.py lấy nguyên mã nguồn qua ast.

Chạy: python scripts/tests/test_phase2_fix_hotel.py
"""
import ast
import copy
import os
import sys
import types
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_phase2_hotel_pack as hp  # noqa: E402  (DB giả + stub TRƯỚC khi nạp reservations_hotel / ai_packs.hotel)

DB, BID, D, run, ctx, resv, rh, hotel, PackError = (hp.DB, hp.BID, hp.D, hp.run, hp.ctx, hp.resv, hp.rh, hp.hotel,
                                                     hp.PackError)
NOW, TODAY = hp.NOW, hp.TODAY
PHONE = '+61412345678'


def WA(**kw):
    return ctx('whatsapp', **kw)


def find(rid):
    return DB.hotel_reservations.find_one({'id': rid}, {'_id': 0})


def claims_of(rid):
    return sorted((c['room_id'], c['night']) for c in DB.hotel_room_nights.docs if c['reservation_id'] == rid)


def change(bid, ci, co, c=None, **kw):
    args = {'booking_id': bid, 'new_checkin_date': ci, 'new_checkout_date': co, 'customer_confirmed': True}
    args.update(kw)
    return run('hotel_change_dates', hp.with_quote(args, c), c)


def cancel(bid, c=None, confirmed=True):
    return run('hotel_cancel_booking', {'booking_id': bid, 'customer_confirmed': confirmed}, c)


# ---------------------------------------------------------------- route nhân viên (mã thật của app.py qua ast)
def _staff_route():
    with open(os.path.join(hp.ROOT, 'app.py'), encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    nodes = []
    for name in ('api_hotel_reservation_update', '_hotel_request_has_room'):
        node = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name))
        node.decorator_list = []
        nodes.append(node)
    req = types.SimpleNamespace(json=None)
    ns = {'db': DB, 'session': {'business_id': BID, 'user_id': 'u-1'}, 'request': req, 'jsonify': lambda d: d,
          '_vi_en': lambda vi, en: en}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns, req


class _HookColl:
    """db.hotel_reservations của route: ngay sau lần đọc đầu tiên chạy các hook (mô phỏng chat AI ghi chen vào)."""

    def __init__(self, real, hooks):
        self._real, self._hooks = real, hooks

    def find_one(self, *a, **kw):
        out = self._real.find_one(*a, **kw)
        while self._hooks:
            self._hooks.pop(0)()
        return out

    def __getattr__(self, name):
        return getattr(self._real, name)


class _HookDB:
    def __init__(self, real, hooks):
        self._real, self._hooks = real, hooks

    def __getattr__(self, name):
        coll = getattr(self._real, name)
        return _HookColl(coll, self._hooks) if name == 'hotel_reservations' else coll


# ================================================================ #9 kéo dài / dời ngày không tính đặt phòng của chính khách
class TestChangeCountsOwnBookingAsFree(hp.Base):
    def setUp(self):
        super().setUp()
        DB.hotel_rooms.docs[:] = [d for d in DB.hotel_rooms.docs if d['id'] == 3]   # chỉ 1 phòng Deluxe $150

    def test_extension_quote_is_available_with_the_real_total(self):
        b = self.book(room_type='Deluxe')                                       # D8..D10
        q = change(b['booking_id'], D(8), D(11), customer_confirmed=False)
        self.assertTrue(q['needs_confirmation'])
        self.assertTrue(q['available'])
        self.assertEqual(q['new_total'], '$450.00')
        self.assertNotIn('hotel_check_availability', q['ask_customer'])          # công cụ đó tính cả đêm của chính khách
        r = change(b['booking_id'], D(8), D(11), quoted_total=q['new_total'])
        self.assertTrue(r['changed'])
        self.assertEqual(r['total'], q['new_total'])
        self.assertNoDoubleBooking()

    def test_unavailable_change_suggests_dates_overlapping_own_nights(self):
        b = self.book(room_type='Deluxe')                                       # D8..D10
        DB.hotel_reservations.insert_one(resv(62, D(10), D(12), room_id=3))
        for confirmed in (False, True):
            r = change(b['booking_id'], D(9), D(11), customer_confirmed=confirmed)
            self.assertFalse(r['success'])
            self.assertEqual(r['reason'], 'no_rooms')
            self.assertIn('NOT changed', r['message'])
            starts = [x['checkin_date'] for x in r.get('nearby_dates_free', [])]
            self.assertIn(D(7), starts)       # D7..D9 trùng đêm D8 của CHÍNH khách -> vẫn là lựa chọn thật
            self.assertNotIn(D(8), starts)    # đúng ngày hiện tại thì không phải "đổi"
        doc = find(b['booking_id'])
        self.assertEqual((doc['checkin_date'], doc['checkout_date']), (D(8), D(10)))
        self.assertEqual(claims_of(b['booking_id']), [(3, D(8)), (3, D(9))])


# ================================================================ #16 không thoát hạn huỷ bằng cách đổi ngày / số khách
class TestCancelWindowCannotBeBypassed(hp.Base):
    def setUp(self):
        super().setUp()
        self.settings(free_cancel_hours=72, checkin_time='14:00')
        # đã xác nhận, nhận phòng D2 14:00 -> hạn huỷ miễn phí D-1 14:00 đã qua
        DB.hotel_reservations.insert_one(resv(80, D(2), D(4), room_id=3, phone=PHONE, source='ai_bot'))

    def test_guest_count_change_inside_window_is_refused(self):
        with self.assertRaises(PackError):
            cancel(80, WA())
        with self.assertRaises(PackError) as cm:
            change(80, D(2), D(4), WA(), guests=1)
        self.assertIn('ask_team', str(cm.exception))
        self.assertIn('NOT changed', str(cm.exception))
        doc = find(80)
        self.assertEqual((doc['status'], doc['party_size']), ('confirmed', 2))
        with self.assertRaises(PackError):
            cancel(80, WA())
        self.assertEqual(find(80)['status'], 'confirmed')

    def test_auto_confirm_move_far_away_inside_window_is_refused(self):
        self.settings(free_cancel_hours=72, checkin_time='14:00', auto_confirm=True)
        with self.assertRaises(PackError):
            change(80, D(40), D(42), WA(), customer_confirmed=False)    # không hỏi khách xác nhận 1 việc sẽ bị từ chối
        with self.assertRaises(PackError):
            change(80, D(40), D(42), WA())
        self.assertEqual((find(80)['checkin_date'], find(80)['status']), (D(2), 'confirmed'))
        with self.assertRaises(PackError):
            cancel(80, WA())

    def test_confirmed_booking_moved_closer_keeps_confirmed_rules(self):
        DB.hotel_reservations.insert_one(resv(81, D(10), D(12), room_id=4, phone=PHONE))   # Suite, ngoài hạn huỷ
        r = change(81, D(2), D(4), WA())
        self.assertTrue(r['changed'])
        self.assertEqual(r['status'], 'pending')
        self.assertTrue(find(81)['was_confirmed'])
        with self.assertRaises(PackError) as cm:
            cancel(81, WA())
        self.assertIn('NOT cancelled', str(cm.exception))
        self.assertEqual(find(81)['status'], 'pending')

    def test_never_confirmed_request_still_cancels_before_checkin_day(self):
        DB.hotel_reservations.insert_one(resv(82, D(10), D(12), room_id=1, phone=PHONE, status='pending'))
        r = change(82, D(2), D(4), WA())
        self.assertEqual(r['status'], 'pending')
        self.assertFalse(find(82).get('was_confirmed'))
        self.assertTrue(cancel(82, WA())['cancelled'])

    def test_cancel_allowed_treats_was_confirmed_as_confirmed(self):
        s = dict(rh.SETTINGS_DEFAULTS, free_cancel_hours=72, checkin_time='14:00')
        self.assertEqual(rh.cancel_allowed({'status': 'pending', 'was_confirmed': True, 'checkin_date': D(2)}, s, NOW),
                         (False, 'past_free_cancellation'))
        self.assertEqual(rh.cancel_allowed({'status': 'pending', 'checkin_date': D(2)}, s, NOW), (True, 'pending_request'))


# ================================================================ #17 giá báo khi đổi ngày = giá được ghi
class TestChangePriceIsThePriceSaved(hp.Base):
    def test_quote_matches_saved_total_when_guest_holds_the_dearer_room(self):
        DB.hotel_reservations.insert_one(resv(90, D(8), D(10), room_id=1))    # 101 ($100) đã có khách -> khách giữ 102 ($110)
        b = self.book()
        self.assertEqual(find(b['booking_id'])['room_id'], 2)
        q = change(b['booking_id'], D(20), D(22), customer_confirmed=False)
        self.assertEqual(q['new_total'], '$220.00')
        r = change(b['booking_id'], D(20), D(22), quoted_total=q['new_total'])
        self.assertTrue(r['changed'])
        self.assertEqual(r['total'], q['new_total'])
        self.assertEqual(find(b['booking_id'])['quoted_total'], 220.0)

    def test_wrong_quoted_total_is_not_saved(self):
        b = self.book()                                                        # phòng 101, D8..D10, $200
        r = change(b['booking_id'], D(20), D(23), quoted_total='$200.00')       # thật: 3 đêm = $300
        self.assertFalse(r['success'])
        self.assertTrue(r['price_changed'])
        self.assertEqual(r['new_total'], '$300.00')
        self.assertEqual(find(b['booking_id'])['checkin_date'], D(8))
        for same in ('$300.00', '300', 300, '300.00 AUD'):
            self.assertTrue(hotel._same_total(same, 300.0, 'AUD'), same)
        for other in ('$200.00', '3.00', True, 'abc'):
            self.assertFalse(hotel._same_total(other, 300.0, 'AUD'), other)

    def test_room_lost_mid_change_never_saves_a_different_price(self):
        DB.hotel_reservations.insert_one(resv(90, D(8), D(10), room_id=1))
        b = self.book()                                                        # phòng 102 ($110)
        DB.hotel_reservations.update_one({'id': 90}, {'$set': {'status': 'cancelled'}})
        q = change(b['booking_id'], D(20), D(22), customer_confirmed=False)
        self.assertEqual(q['new_total'], '$220.00')
        real, calls = rh.availability, {'n': 0}

        def racing(*a, **kw):
            out = real(*a, **kw)
            calls['n'] += 1
            if calls['n'] == 1:   # lượt khác giữ phòng 102 đêm D20 ngay sau khi xem phòng
                DB.hotel_room_nights.insert_one({'_id': f'{BID}|2|{D(20)}', 'business_id': BID, 'room_id': 2, 'night': D(20),
                                                 'reservation_id': 4242, 'claimed_at': datetime.now(timezone.utc).isoformat()})
            return out
        rh.availability = racing
        try:
            try:
                r = change(b['booking_id'], D(20), D(22), quoted_total=q['new_total'])
            except PackError as e:
                r = {'success': False, 'error': str(e)}
        finally:
            rh.availability = real
        doc = find(b['booking_id'])
        if doc['checkin_date'] == D(20):
            self.assertEqual(doc['quoted_total'], 220.0)    # chỉ được ghi đúng giá đã báo
        else:
            self.assertFalse(r['success'])
            self.assertEqual((doc['room_id'], doc['quoted_total']), (2, 220.0))
            self.assertEqual(claims_of(b['booking_id']), [(2, D(8)), (2, D(9))])
        self.assertNoDoubleBooking()


# ================================================================ #18 / #19 route nhân viên
class TestStaffRoute(hp.Base):
    def setUp(self):
        super().setUp()
        self.ns, self.req = _staff_route()

    def patch(self, rid, body):
        self.req.json = body
        out = self.ns['api_hotel_reservation_update'](rid)
        return (out, 200) if isinstance(out, dict) else out

    def test_stale_approve_does_not_reopen_guest_cancelled_booking(self):
        b = self.book()                                                        # pending, phòng 101
        self.assertTrue(cancel(b['booking_id'])['cancelled'])                  # khách huỷ trong chat
        out, code = self.patch(b['booking_id'], {'status': 'confirmed'})       # trang cũ vẫn hiện "Duyệt"
        self.assertEqual(code, 409)
        self.assertIn('cancelled', out['message'])
        self.assertIn('chat', out['message'])
        self.assertEqual(find(b['booking_id'])['status'], 'cancelled')
        self.assertEqual(DB.hotel_room_nights.count_documents({}), 0)
        out, code = self.patch(b['booking_id'], {'status': 'confirmed', 'from_status': 'pending'})
        self.assertEqual(code, 409)
        # mở lại CÓ CHỦ ĐÍCH vẫn được (và vẫn kiểm lại phòng)
        self.assertEqual(self.patch(b['booking_id'], {'status': 'confirmed', 'reopen': True}), ({'success': True}, 200))
        self.assertEqual(find(b['booking_id'])['status'], 'confirmed')
        self.assertEqual(claims_of(b['booking_id']), [(1, D(8)), (1, D(9))])

    def test_from_status_mismatch_is_409(self):
        b = self.book()
        DB.hotel_reservations.update_one({'id': b['booking_id']}, {'$set': {'status': 'confirmed'}})   # nhân viên khác vừa duyệt
        out, code = self.patch(b['booking_id'], {'status': 'cancelled', 'from_status': 'pending'})
        self.assertEqual(code, 409)
        self.assertEqual(find(b['booking_id'])['status'], 'confirmed')
        self.assertEqual(self.patch(b['booking_id'], {'status': 'cancelled', 'from_status': 'confirmed'}),
                         ({'success': True}, 200))

    def test_assign_room_with_stale_snapshot_never_double_books(self):
        b = self.book()                                                        # phòng 101, D8..D10
        DB.hotel_reservations.insert_one(resv(77, D(20), D(22), room_id=2))
        stale = find(b['booking_id'])
        rh.change_dates(BID, find(b['booking_id']), D(20), D(22), today=TODAY)   # khách dời ngày trong chat
        with self.assertRaises(rh.HotelRequestError) as cm:
            rh.assign_room(BID, stale, 2)
        self.assertEqual(cm.exception.code, 'changed_meanwhile')
        self.assertNoDoubleBooking()
        doc = find(b['booking_id'])
        self.assertEqual((doc['room_id'], doc['checkin_date']), (1, D(20)))
        self.assertEqual(claims_of(b['booking_id']), [(1, D(20)), (1, D(21))])

    def test_route_assign_while_guest_moves_dates_is_409(self):
        b = self.book()
        DB.hotel_reservations.insert_one(resv(77, D(20), D(22), room_id=2))
        real = rh.assign_room

        def interleaved(bid, res, room_id, now=None):
            rh.change_dates(BID, find(b['booking_id']), D(20), D(22), today=TODAY)
            return real(bid, res, room_id, now=now)
        rh.assign_room = interleaved
        try:
            out, code = self.patch(b['booking_id'], {'room_id': 2})
        finally:
            rh.assign_room = real
        self.assertEqual(code, 409)
        self.assertIn('changed elsewhere', out['message'])
        self.assertNoDoubleBooking()
        self.assertEqual(find(b['booking_id'])['room_id'], 1)
        self.assertEqual(claims_of(b['booking_id']), [(1, D(20)), (1, D(21))])

    def test_route_approve_when_booking_changes_after_read_is_409(self):
        b = self.book()                                                        # pending D8..D10
        hooks = [lambda: rh.change_dates(BID, find(b['booking_id']), D(20), D(22), today=TODAY, new_status='pending')]
        self.ns['db'] = _HookDB(DB, hooks)
        out, code = self.patch(b['booking_id'], {'status': 'confirmed'})
        self.assertEqual(code, 409)
        doc = find(b['booking_id'])
        self.assertEqual((doc['status'], doc['checkin_date']), ('pending', D(20)))


# ================================================================ #28 khách vãng lai đang ở, chưa có ngày trả phòng
class TestWalkInGuest(hp.Base):
    def setUp(self):
        super().setUp()
        DB.hotel_rooms.update_one({'id': 1}, {'$set': {'status': 'Đang ở', 'guest_name': 'Walk In'}})   # check-in tại quầy
        self.settings(auto_confirm=True)

    def test_free_room_preferred_and_walk_in_room_never_auto_confirmed(self):
        av = run('hotel_check_availability', {'checkin_date': D(1), 'checkout_date': D(2), 'room_type': 'Standard'})
        self.assertEqual((av['room_types'][0]['rooms_left'], av['room_types'][0]['rate_per_night']), (2, '$110.00'))
        self.assertNotIn('booking_is', av['room_types'][0])
        a = self.book(checkin_date=D(1), checkout_date=D(2))
        self.assertEqual((find(a['booking_id'])['room_id'], a['status'], a['total']), (2, 'confirmed', '$110.00'))
        av = run('hotel_check_availability', {'checkin_date': D(1), 'checkout_date': D(2), 'room_type': 'Standard'})
        self.assertEqual(av['room_types'][0]['booking_is'], 'a request the hotel confirms (status pending)')
        b = self.book(c=ctx(token='tok-B', cid=f'{BID}:0499999999'), checkin_date=D(1), checkout_date=D(2),
                      guest_name='Bob Second', phone='0499 999 999')
        doc = find(b['booking_id'])
        self.assertEqual((doc['room_id'], doc['status'], b['status']), (1, 'pending', 'pending'))
        self.assertIn('Do NOT say it is confirmed', b['say'])
        self.assertIn('walk-in', OWNER_ALERTS_TEXT())
        self.assertNotIn('Walk In', str(b))   # không lộ khách khác cho người đang chat

    def test_occupant_with_a_booking_is_not_open_ended(self):
        DB.hotel_reservations.insert_one(resv(95, D(-1), D(1), room_id=1))      # khách đang ở có đặt phòng tới mai
        r = self.book(checkin_date=D(1), checkout_date=D(2))
        self.assertEqual((find(r['booking_id'])['room_id'], r['status']), (1, 'confirmed'))

    def test_known_expected_checkout_blocks_those_nights(self):
        DB.hotel_rooms.update_one({'id': 1}, {'$set': {'expected_checkout_date': D(3)}})
        av = run('hotel_check_availability', {'checkin_date': D(1), 'checkout_date': D(2), 'room_type': 'Standard'})
        self.assertEqual(av['room_types'][0]['rooms_left'], 1)
        av = run('hotel_check_availability', {'checkin_date': D(3), 'checkout_date': D(4), 'room_type': 'Standard'})
        self.assertEqual((av['room_types'][0]['rooms_left'], av['room_types'][0]['rate_per_night']), (2, '$100.00'))
        r = self.book(checkin_date=D(3), checkout_date=D(4))
        self.assertEqual((find(r['booking_id'])['room_id'], r['status']), (1, 'confirmed'))

    def test_change_into_walk_in_room_is_not_auto_confirmed(self):
        DB.hotel_reservations.insert_many([resv(96, D(8), D(10), room_id=2, phone=PHONE),
                                           resv(97, D(1), D(2), room_id=2)])
        q = change(96, D(1), D(2), WA(), customer_confirmed=False)
        self.assertEqual(q['new_total'], '$100.00')
        r = change(96, D(1), D(2), WA(), quoted_total=q['new_total'])
        self.assertEqual((r['status'], find(96)['room_id'], r['total']), ('pending', 1, '$100.00'))
        self.assertIn('walk-in', OWNER_ALERTS_TEXT())
        self.assertNoDoubleBooking()


def OWNER_ALERTS_TEXT():
    return ' '.join(a[2] for a in hp.OWNER_ALERTS)


# ================================================================ #35 không huỷ 'pending' qua chat từ ngày nhận phòng
class TestPendingCancelFromCheckinDay(hp.Base):
    def test_mid_stay_pending_cancel_is_refused(self):
        DB.hotel_reservations.insert_one(resv(91, D(-1), D(3), room_id=1, phone=PHONE, status='pending'))
        for n in (D(-1), D(0), D(1), D(2)):
            DB.hotel_room_nights.insert_one({'_id': f'{BID}|1|{n}', 'business_id': BID, 'room_id': 1, 'night': n,
                                             'reservation_id': 91, 'claimed_at': datetime.now(timezone.utc).isoformat()})
        for confirmed in (False, True):
            with self.assertRaises(PackError) as cm:
                cancel(91, WA(), confirmed=confirmed)
            self.assertIn('front desk', str(cm.exception))
            self.assertIn('NOT cancelled', str(cm.exception))
        self.assertEqual(find(91)['status'], 'pending')
        self.assertEqual(len(claims_of(91)), 4)
        r = self.book(checkin_date=D(1), checkout_date=D(3), room_type='Standard')
        self.assertNotEqual(find(r['booking_id'])['room_id'], 1)
        self.assertNoDoubleBooking()

    def test_checkin_day_refused_day_before_allowed(self):
        DB.hotel_reservations.insert_many([resv(92, D(0), D(2), room_id=1, phone=PHONE, status='pending'),
                                           resv(93, D(1), D(2), room_id=2, phone=PHONE, status='pending')])
        with self.assertRaises(PackError) as cm:
            cancel(92, WA(lang='vi'))
        self.assertIn('lễ tân', str(cm.exception))
        self.assertEqual(find(92)['status'], 'pending')
        self.assertTrue(cancel(93, WA())['cancelled'])


# ================================================================ #36 lời AI nói = luật hệ thống áp dụng
class TestCancelWindowWording(hp.Base):
    def test_window_without_checkin_time_is_counted_from_midnight(self):
        self.settings(free_cancel_hours=24)
        f = hotel.facts(BID, 'en', NOW)
        self.assertIn('24 hours before the start (00:00) of the check-in day', f)
        self.assertIn('0:00 (đầu ngày) của ngày nhận phòng', hotel.facts(BID, 'vi', NOW))
        # đúng luật thật: nhận phòng D2 -> hạn D1 00:00; lúc D0 10:00 còn huỷ được, D1 08:00 thì không
        conf = {'status': 'confirmed', 'checkin_date': D(2)}
        s = rh.hotel_settings(BID)
        self.assertTrue(rh.cancel_allowed(conf, s, NOW)[0])
        self.assertFalse(rh.cancel_allowed(conf, s, NOW.replace(day=NOW.day + 1, hour=8))[0])
        self.settings(free_cancel_hours=24, checkin_time='14:00')
        self.assertIn('24 hours before check-in (14:00)', hotel.facts(BID, 'en', NOW))

    def test_pending_rule_matches_the_check_in_day_guard(self):
        f = hotel.facts(BID, 'en', NOW)
        self.assertNotIn('any time', f)
        self.assertIn('pending requests can be cancelled in this chat until the day before check-in', f)
        self.assertNotIn('bất cứ lúc nào', hotel.facts(BID, 'vi', NOW))


if __name__ == '__main__':
    unittest.main(verbosity=2)
