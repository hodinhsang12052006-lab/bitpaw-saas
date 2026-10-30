# -*- coding: utf-8 -*-
"""Test OFFLINE — vòng sửa 3 khách sạn Phase 2 (hotel3):
  - TRẦN GIỮ PHÒNG theo KHÁCH SẠN cho chat web CHƯA xác minh (không SĐT đã xác minh, không hội thoại nền tảng đã ký): tối đa
    ~40% số phòng mỗi loại mỗi đêm (ít nhất 1) — không dựa vào danh tính người chat (mã trình duyệt / SĐT / mạng đổi được).
    Vượt trần: AI KHÔNG giữ phòng, chuyển nguyên yêu cầu cho nhân viên (không số đặt phòng, không nói đã đặt); xem phòng
    trống nói trước; dời ngày vào đêm đã đầy bị từ chối; chat đã xác minh và đặt phòng nhân viên đã duyệt không tính; 2 chat
    cùng lúc tranh suất cuối không bao giờ vượt trần (bên kiểm lại thấy vượt trần tự huỷ phiếu của mình — có thể CẢ 2 cùng
    huỷ, xem test_phase2_fix4_hotel4);
  - form đặt phòng công khai /api/public/hotel_reservations/<id>: trần riêng theo IP chặt hơn (giờ + NGÀY), decorator đặt
    đúng chỗ nên Flask-Limiter 4.1.1 thật trả 429 (không "biến mất");
  - 4 cạnh của ngày trả phòng dự kiến (trang Quản Lý Phòng + route): (1) ngày đã qua hiện cảnh báo vàng như "chưa rõ ngày";
    (2) ngày đã lưu là hôm nay không còn bị điền sẵn rồi 400 khi Lưu; (3) sửa ngày / trả phòng / phụ thu gắn ĐÚNG lượt ở
    trang đang hiện — phòng đã đổi khách thì 409, không ghi sang khách mới; (4) khách tới sau nửa đêm / ở ngắn đi trong ngày
    được ghi "trả phòng trong hôm nay" (chọn rõ), phòng trống từ đêm nay;
  - quoted_total: '450.000' không còn đọc được cả 450 lẫn 450.000 (lệch 1000 lần), tổng VND có số lẻ khớp số làm tròn khách
    nghe ('1.234 VND' = 1234.5), chỉ đọc SỐ ĐẦU TIÊN ('$450 for 3 nights' = 450);
  - giờ mở cửa qua nửa đêm của khách sạn nói rõ giờ đóng thuộc NGÀY hôm sau (VI + EN) — đã đúng từ vòng 2 (khoá lại).

KHÔNG import app.py, KHÔNG mở MongoDB thật, KHÔNG gọi API trả phí: DB giả + stub của test_phase2_hotel_pack (mongo_client /
requests / ai_function_tools được thay TRƯỚC mọi import); route app.py lấy nguyên mã nguồn qua ast; trang chạy trong node.

Chạy: python scripts/tests/test_phase2_fix3_hotel3.py
"""
import ast
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import uuid
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_phase2_hotel_pack as hp  # noqa: E402  (DB giả + stub TRƯỚC khi nạp reservations_hotel / ai_packs.hotel)
from test_phase2_fix_hotel import OWNER_ALERTS_TEXT, _staff_route, find  # noqa: E402
from test_phase2_fix2_hotel import render  # noqa: E402

DB, BID, D, run, ctx, resv, rh, hotel = hp.DB, hp.BID, hp.D, hp.run, hp.ctx, hp.resv, hp.rh, hp.hotel
NOW, TODAY, PackError = hp.NOW, hp.TODAY, hp.PackError
from pymongo import ReturnDocument  # noqa: E402  (chỉ hằng số)

APP_PY = os.path.join(hp.ROOT, 'app.py')


def _app_tree():
    with open(APP_PY, encoding='utf-8') as fh:
        src = fh.read()
    return src, ast.parse(src)


def _routes(names):
    """Mã THẬT của các route phòng trong app.py (bỏ decorator), chạy trên DB giả."""
    _src, tree = _app_tree()
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node = copy.deepcopy(node)
            node.decorator_list = []
            nodes.append(node)
    assert len(nodes) == len(names), names
    req = types.SimpleNamespace(json=None)
    req.get_json = lambda silent=False: req.json
    ns = {'db': DB, 'session': {'business_id': BID, 'user_id': 'u-1'}, 'request': req, 'jsonify': lambda d: d,
          '_vi_en': lambda vi, en: en, 'tenant_today': lambda bid: TODAY, 'datetime': datetime,
          'ReturnDocument': ReturnDocument, 'next_mongo_id': hp._next_id, 'uuid': uuid,
          'parse_datetime': lambda s: datetime.fromisoformat(str(s)), '_record_pos_transaction': lambda *a, **k: None,
          'render_template': lambda tpl, **kw: ('html', tpl, kw)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns, req


ROOM_ROUTES = ('api_hotel_rooms_list', 'api_hotel_room_checkin', 'api_hotel_room_expected_checkout',
               'api_hotel_room_checkout', 'api_hotel_room_charges_add', 'api_hotel_room_mark_clean')


def web(n, **kw):
    """Chat web CHƯA xác minh thứ n: mã trình duyệt / SĐT / hội thoại khác nhau (như 1 người xoá mã + đổi SĐT mỗi lần)."""
    return ctx(token=f'tok-{n}', cid=f'{BID}:04999999{n:02d}', **kw)


def wa(n):
    """Chat WhatsApp đã xác minh SĐT thứ n."""
    return ctx('whatsapp', cid=f'{BID}:whatsapp:614999999{n:02d}', phone=f'+614999999{n:02d}')


class _Hotel(hp.Base):
    def book_as(self, c, n, **kw):
        args = dict(guest_name=f'Guest Number{n}', phone=f'04999999{n:02d}')
        args.update(kw)
        return self.book(c=c, **args)

    def add_standard_rooms(self, numbers):
        for i, num in enumerate(numbers):
            DB.hotel_rooms.insert_one(hp.room(10 + i, num, 'Standard', 100))

    def live_ai(self):
        return [r for r in self.live_rows() if r.get('source') == 'ai_bot']


# ================================================================ trần giữ phòng của chat web chưa xác minh
class TestWebHoldCap(_Hotel):
    def test_cap_values(self):
        self.assertEqual([rh.web_hold_cap(n) for n in (0, 1, 2, 3, 4, 5, 10, 20)], [1, 1, 1, 1, 2, 2, 4, 8])

    def test_second_unverified_chat_gets_a_staff_request_not_a_room(self):
        a = self.book_as(web(1), 1)                                 # Standard có 2 phòng -> trần 1 phòng/đêm
        self.assertEqual((a['status'], find(a['booking_id'])['ai_verified']), ('pending', False))
        b = self.book_as(web(2), 2)
        self.assertTrue(b['success'])
        self.assertTrue(b['request_sent_to_team'])
        self.assertEqual((b['room_held'], b['confirmed'], b['status']), (False, False, 'pending'))
        self.assertNotIn('booking_id', b)                          # không số đặt phòng
        self.assertIn('never say it is booked or confirmed', b['note'])
        self.assertIn('Do NOT say it is confirmed', b['say'])
        self.assertEqual(len(self.live_ai()), 1)                   # phòng thứ 2 vẫn còn cho khách đã xác minh / nhân viên
        self.assertEqual(hp.DB.hotel_room_nights.count_documents({'reservation_id': {'$ne': a['booking_id']}}), 0)
        note = hp.STAFF_NOTES[-1][2]
        for bit in ('NO room held', 'Guest Number2', '0499999902', 'not verified', 'Standard', D(8), D(10), '2 night(s)'):
            self.assertIn(bit, note)
        self.assertEqual(hp.OWNER_ALERTS[-1][3], 'hotel_webcap')
        self.assertNotIn('Guest Number1', json.dumps(b))           # không lộ khách khác
        # khách đã xác minh (WhatsApp) vẫn giữ được phòng cuối
        c = self.book_as(wa(3), 3)
        self.assertEqual((find(c['booking_id'])['room_id'], find(c['booking_id'])['ai_verified']), (2, True))
        self.assertNoDoubleBooking()

    def test_vi_staff_note_and_vi_chat(self):
        DB.businesses.update_one({'id': BID}, {'$set': {'country': 'VN', 'currency': 'VND'}})
        self.book_as(web(1), 1)
        b = self.book_as(web(2, lang='vi'), 2)
        self.assertTrue(b['request_sent_to_team'])
        self.assertIn('KHÔNG nói là đã xác nhận', b['say'])
        note = hp.STAFF_NOTES[-1][2]
        self.assertIn('CHƯA giữ phòng', note)
        self.assertIn('chưa xác minh', note)
        self.assertIn('Khách sạn > Đặt phòng', note)
        self.assertNotIn('link đặt phòng công khai', note)

    def test_cap_is_per_night_and_per_type(self):
        self.book_as(web(1), 1, checkin_date=D(8), checkout_date=D(10))
        b = self.book_as(web(2), 2, checkin_date=D(10), checkout_date=D(12))   # không đêm nào giao nhau
        self.assertEqual(find(b['booking_id'])['status'], 'pending')
        c = self.book_as(web(3), 3, checkin_date=D(9), checkout_date=D(11))    # đêm D9 + D10 đều đã 1/1
        self.assertTrue(c.get('request_sent_to_team'))
        d = self.book_as(web(4), 4, room_type='Deluxe', guests=2)              # loại khác: trần riêng
        self.assertIn('booking_id', d)
        self.assertNoDoubleBooking()

    def test_bigger_type_allows_about_40_percent(self):
        self.add_standard_rooms(['103', '104', '105'])            # Standard 5 phòng -> trần 2
        got = [self.book_as(web(n), n) for n in range(1, 5)]
        self.assertEqual(['booking_id' in g for g in got], [True, True, False, False])
        self.assertEqual(len(self.live_ai()), 2)
        for n in (5, 6, 7):                                        # khách đã xác minh lấp nốt phòng còn lại
            self.assertIn('booking_id', self.book_as(wa(n), n))
        self.assertEqual(len(self.live_ai()), 5)
        self.assertNoDoubleBooking()

    def test_staff_confirmed_unverified_holds_free_the_quota(self):
        a = self.book_as(web(1), 1)
        self.assertTrue(self.book_as(web(2), 2).get('request_sent_to_team'))
        ns, req = _staff_route()
        req.json = {'status': 'confirmed', 'from_status': 'pending'}
        self.assertEqual(ns['api_hotel_reservation_update'](a['booking_id']), {'success': True})
        self.assertTrue(find(a['booking_id']).get('staff_confirmed_at'))
        self.assertFalse(rh.unverified_web_hold(find(a['booking_id'])))
        c = self.book_as(web(3), 3)                                # người thật đã duyệt #a -> suất chat web mở lại
        self.assertIn('booking_id', c)
        self.assertNoDoubleBooking()

    def test_moved_staff_confirmed_booking_counts_again(self):
        self.settings(auto_confirm=False)
        a = self.book_as(web(1), 1, checkin_date=D(20), checkout_date=D(21))
        ns, req = _staff_route()
        req.json = {'status': 'confirmed'}
        ns['api_hotel_reservation_update'](a['booking_id'])
        doc = find(a['booking_id'])
        new, _av = rh.change_dates(BID, doc, rh.parse_day(D(22)), rh.parse_day(D(23)), today=TODAY, new_status='pending')
        self.assertIsNone(new['staff_confirmed_at'])               # duyệt cho NGÀY CŨ, ngày mới chưa ai duyệt
        self.assertTrue(rh.unverified_web_hold(find(a['booking_id'])))

    def test_who_counts(self):
        rooms = rh.list_rooms(BID)
        types = rh.room_types(rooms)
        legacy_web = resv(501, D(8), D(9), room_id=1, source='ai_bot', ai_channel='web')            # trước khi có ai_verified
        legacy_msgr = resv(502, D(8), D(9), room_id=1, source='ai_bot', ai_channel='messenger')
        form = resv(503, D(8), D(9), room_type='Standard', source='web', status='pending')
        verified = resv(504, D(8), D(9), room_id=2, source='ai_bot', ai_channel='web', ai_verified=True)
        staff_ok = resv(505, D(8), D(9), room_id=2, source='ai_bot', ai_verified=False, staff_confirmed_at='x')
        staff_then_pending = resv(506, D(8), D(9), room_id=2, source='ai_bot', ai_verified=False, status='pending',
                                  staff_confirmed_at='x')
        got = [rh.unverified_web_hold(r) for r in (legacy_web, legacy_msgr, form, verified, staff_ok, staff_then_pending)]
        self.assertEqual(got, [True, False, False, False, False, True])
        DB.hotel_reservations.insert_many([legacy_web, legacy_msgr, form, verified])
        self.assertTrue(rh.web_holds_full(BID, rooms, types, 'standard', D(8), D(9)))   # chỉ #501 (web cũ) tính: 1 + 1 > 1
        self.assertFalse(rh.web_holds_full(BID, rooms, types, 'standard', D(9), D(10)))
        self.assertFalse(rh.web_holds_full(BID, rooms, types, 'standard', D(8), D(9), ignore_id=501))
        self.assertFalse(rh.web_holds_full(BID, rooms, types, 'deluxe', D(8), D(9)))
        DB.hotel_reservations.update_one({'id': 501}, {'$set': {'status': 'cancelled'}})
        self.assertFalse(rh.web_holds_full(BID, rooms, types, 'standard', D(8), D(9)))

    def test_availability_warns_before_booking(self):
        self.book_as(web(1), 1)
        av = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10)}, web(2))
        std = next(t for t in av['room_types'] if t['room_type'] == 'Standard')
        self.assertTrue(std['available'])
        self.assertIn('passed to the hotel team', std['booking_is'])
        self.assertIn('no room can be held online', std['booking_is'])
        dlx = next(t for t in av['room_types'] if t['room_type'] == 'Deluxe')
        self.assertNotIn('booking_is', dlx)
        av = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10)}, wa(3))
        self.assertNotIn('booking_is', next(t for t in av['room_types'] if t['room_type'] == 'Standard'))

    def test_spreading_holds_then_moving_them_together_is_refused(self):
        self.book_as(web(1), 1, checkin_date=D(8), checkout_date=D(9))
        c2 = web(2)
        b = self.book_as(c2, 2, checkin_date=D(12), checkout_date=D(13))
        args = {'booking_id': b['booking_id'], 'new_checkin_date': D(8), 'new_checkout_date': D(9)}
        with self.assertRaises(PackError) as cm:
            run('hotel_change_dates', dict(args, customer_confirmed=False), c2)
        self.assertIn('NOT changed', str(cm.exception))
        self.assertIn('ask_team', str(cm.exception))
        with self.assertRaises(PackError):
            run('hotel_change_dates', dict(args, customer_confirmed=True, quoted_total='$100.00'), c2)
        self.assertEqual((find(b['booking_id'])['checkin_date'], find(b['booking_id'])['room_id']), (D(12), 1))
        # dời sang đêm còn suất: được (đêm của chính đặt phòng không tính 2 lần)
        r = run('hotel_change_dates', hp.with_quote(dict(args, new_checkin_date=D(12), new_checkout_date=D(14),
                                                         customer_confirmed=True), c2), c2)
        self.assertTrue(r['changed'])
        self.assertNoDoubleBooking()

    def test_two_chats_racing_for_the_last_slot_never_exceed_the_cap(self):
        real = rh.web_holds_full
        calls = []

        def stale_precheck(*a, **kw):
            calls.append(kw.get('extra', 1))
            if kw.get('extra', 1) == 1:
                return False      # như lượt kiểm TRƯỚC khi chat kia ghi xong
            return real(*a, **kw)
        self.book_as(web(1), 1)
        rh.web_holds_full = stale_precheck
        try:
            b = self.book_as(web(2), 2)
        finally:
            rh.web_holds_full = real
        self.assertEqual(calls, [1, 0])
        self.assertTrue(b['request_sent_to_team'])
        self.assertEqual(len(self.live_ai()), 1)
        loser = [r for r in DB.hotel_reservations.docs if r.get('cancelled_by') == 'system']
        self.assertEqual(len(loser), 1)
        self.assertEqual(loser[0]['cancel_reason'], 'unverified online hold limit reached')
        self.assertEqual(DB.hotel_room_nights.count_documents({'reservation_id': loser[0]['id']}), 0)   # phiếu đã trả

    def test_no_conversation_means_no_false_promise(self):
        self.book_as(web(1), 1)
        c = web(2)
        c['customer_id'] = None
        with self.assertRaises(PackError) as cm:
            self.book_as(c, 2)
        self.assertIn('nothing was booked', str(cm.exception))
        self.assertIn('+61 2 9999 0000', str(cm.exception))


# ================================================================ form đặt phòng công khai: trần theo IP
class TestPublicHotelFormRateLimit(unittest.TestCase):
    def _decorators_and_limit(self):
        src, tree = _app_tree()
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'api_public_hotel_reservation_create')
        consts = {}
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                    and n.targets[0].id.startswith('_PUBLIC_') and isinstance(n.value, ast.Constant):
                consts[n.targets[0].id] = n.value.value
        return fn, consts

    def test_hotel_form_has_a_stricter_daily_limit_than_tables(self):
        from limits import parse_many
        fn, consts = self._decorators_and_limit()
        decos = [ast.unparse(d) for d in fn.decorator_list]
        self.assertTrue(decos[0].startswith('app.route('), decos)            # limiter NGAY DƯỚI app.route: hàm đăng ký = hàm bọc
        self.assertEqual(decos[1], 'limiter.limit(_PUBLIC_HOTEL_RESERVE_LIMIT)')
        items = {i.GRANULARITY.name: i.amount for i in parse_many(consts['_PUBLIC_HOTEL_RESERVE_LIMIT'])}
        self.assertLessEqual(items['hour'], 10)
        self.assertLessEqual(items['day'], 30)
        table = {i.GRANULARITY.name: i.amount for i in parse_many(consts['_PUBLIC_RESERVE_LIMIT'])}
        self.assertLess(items['hour'], table['hour'])

    def test_real_flask_limiter_returns_429_on_the_real_route(self):
        import flask
        from flask_limiter import Limiter
        fn, consts = self._decorators_and_limit()
        app = flask.Flask('hotel3_limit_test')
        ip = {'v': '203.0.113.7'}
        limiter = Limiter(lambda: ip['v'], app=app, storage_uri='memory://', default_limits=['20000 per day'])
        hits = []

        def check(bid, data):
            hits.append(bid)   # tới được thân route -> chưa bị chặn
            return (flask.jsonify({'success': False, 'message': 'stub'}), 400), None
        ns = {'app': app, 'limiter': limiter, 'request': flask.request, 'jsonify': flask.jsonify,
              '_public_reservation_check': check, **consts}
        exec(compile(ast.Module(body=[copy.deepcopy(fn)], type_ignores=[]), 'app.py', 'exec'), ns)
        view = app.view_functions['api_public_hotel_reservation_create']
        self.assertEqual(getattr(view, '__wrapper-limiter-instance', None), limiter)   # đăng ký đúng hàm bọc
        client = app.test_client()
        codes = [client.post(f'/api/public/hotel_reservations/{BID}', json={'name': 'x'}).status_code for _ in range(11)]
        self.assertEqual(codes, [400] * 10 + [429])
        self.assertEqual(len(hits), 10)
        ip['v'] = '198.51.100.9'                                   # IP khác: trần riêng
        self.assertEqual(client.post(f'/api/public/hotel_reservations/{BID}', json={}).status_code, 400)


# ================================================================ ngày trả phòng dự kiến: route
class TestExpectedCheckoutRoutes(_Hotel):
    def setUp(self):
        super().setUp()
        self.ns, self.req = _routes(ROOM_ROUTES)
        self.settings(auto_confirm=True)

    def call(self, name, *a, body=None):
        self.req.json = body
        out = self.ns[name](*a)
        return (out, 200) if isinstance(out, dict) else out

    def room(self, rid):
        return DB.hotel_rooms.find_one({'id': rid}, {'_id': 0})

    def left(self, ci, co):
        av = run('hotel_check_availability', {'checkin_date': ci, 'checkout_date': co, 'room_type': 'Standard'}, wa(9))
        return av['room_types'][0]['rooms_left']

    def test_leaves_today_needs_the_explicit_choice(self):
        self.assertEqual(rh.walkin_checkout_date(D(0), TODAY, same_day=True), D(0))
        for bad, same in ((D(0), False), (D(0), 'true'), (D(0), 1), (D(-1), True)):
            with self.assertRaises(rh.HotelRequestError) as cm:
                rh.walkin_checkout_date(bad, TODAY, same_day=same)
            self.assertIn("tick 'Leaves today'", cm.exception.en)
            self.assertIn('Khách trả phòng trong hôm nay', cm.exception.vi)
        self.assertEqual(rh.walkin_checkout_date(D(2), TODAY, same_day=True), D(2))

    def test_after_midnight_guest_leaving_today_frees_tonight(self):
        out, code = self.call('api_hotel_room_checkin', 1, body={'guest_name': 'Night Owl', 'expected_checkout_date': D(0),
                                                                 'same_day': True})
        self.assertEqual(code, 200, out)
        self.assertEqual(self.room(1)['expected_checkout_date'], D(0))
        self.assertEqual(rh.open_walkins(BID, rh.list_rooms(BID), TODAY), set())     # không còn là "chưa rõ ngày đi"
        self.assertEqual(self.left(D(0), D(1)), 2)                 # đi trưa nay -> đêm nay bán được
        out, code = self.call('api_hotel_room_checkin', 2, body={'guest_name': 'Day Use', 'expected_checkout_date': D(0)})
        self.assertEqual(code, 400)                                # không chọn rõ "trả phòng trong hôm nay" -> từ chối
        self.assertIn("tick 'Leaves today'", out['message'])
        self.assertEqual(self.room(2)['status'], 'Trống')

    def test_saving_today_again_from_the_edit_window(self):
        self.call('api_hotel_room_checkin', 1, body={'guest_name': 'Walk In', 'expected_checkout_date': D(1)})
        since = self.room(1)['checkin_date']
        out, code = self.call('api_hotel_room_expected_checkout', 1,
                              body={'expected_checkout_date': D(0), 'same_day': True, 'from_checkin_date': since})
        self.assertEqual((code, self.room(1)['expected_checkout_date']), (200, D(0)))
        out, code = self.call('api_hotel_room_expected_checkout', 1,
                              body={'expected_checkout_date': D(0), 'same_day': True, 'from_checkin_date': since})
        self.assertEqual(code, 200, out)                           # Lưu lại đúng ngày đang lưu (hôm nay) không còn 400

    def test_stale_window_never_writes_to_the_next_guest(self):
        self.call('api_hotel_room_checkin', 1, body={'guest_name': 'Guest A', 'expected_checkout_date': D(2)})
        since_a = self.room(1)['checkin_date']
        self.assertEqual(self.call('api_hotel_room_checkout', 1, body={'payment_method': 'cash', 'from_checkin_date': since_a})[1], 200)
        self.call('api_hotel_room_mark_clean', 1)
        DB.hotel_rooms.update_one({'id': 1}, {'$set': {'status': 'Trống'}})
        self.call('api_hotel_room_checkin', 1, body={'guest_name': 'Guest B', 'expected_checkout_date': D(5)})
        DB.hotel_rooms.update_one({'id': 1}, {'$set': {'checkin_date': '2026-11-02T11:30:00.000001'}})   # lượt ở khác
        orders_before = DB.orders.count_documents({})
        # cửa sổ "sửa ngày" mở từ lúc khách A còn ở
        out, code = self.call('api_hotel_room_expected_checkout', 1,
                              body={'expected_checkout_date': D(3), 'from_checkin_date': since_a})
        self.assertEqual(code, 409)
        self.assertIn('different guest', out['message'])
        self.assertEqual((self.room(1)['guest_name'], self.room(1)['expected_checkout_date']), ('Guest B', D(5)))
        # cửa sổ trả phòng / phụ thu cũ của khách A
        out, code = self.call('api_hotel_room_checkout', 1, body={'payment_method': 'card', 'from_checkin_date': since_a})
        self.assertEqual(code, 409)
        self.assertIn('nothing was checked out or charged', out['message'])
        self.assertEqual((self.room(1)['status'], self.room(1)['guest_name']), ('Đang ở', 'Guest B'))
        self.assertEqual(DB.orders.count_documents({}), orders_before)
        out, code = self.call('api_hotel_room_charges_add', 1,
                              body={'description': 'Minibar', 'amount': 12, 'from_checkin_date': since_a})
        self.assertEqual(code, 409)
        self.assertEqual(DB.hotel_room_charges.count_documents({}), 0)
        # đúng lượt ở hiện tại: được
        since_b = self.room(1)['checkin_date']
        self.assertEqual(self.call('api_hotel_room_expected_checkout', 1,
                                   body={'expected_checkout_date': D(4), 'from_checkin_date': since_b})[1], 200)
        self.assertEqual(self.room(1)['expected_checkout_date'], D(4))
        self.assertEqual(self.call('api_hotel_room_charges_add', 1,
                                   body={'description': 'Minibar', 'amount': 12, 'from_checkin_date': since_b})[1], 200)
        # toán tử Mongo trong from_checkin_date không lách được (chỉ so chuỗi)
        out, code = self.call('api_hotel_room_expected_checkout', 1,
                              body={'expected_checkout_date': D(6), 'from_checkin_date': {'$ne': None}})
        self.assertEqual(code, 409)
        self.assertEqual(self.room(1)['expected_checkout_date'], D(4))
        # không gửi from_checkin_date (API cũ): như trước
        self.assertEqual(self.call('api_hotel_room_expected_checkout', 1, body={'expected_checkout_date': D(6)})[1], 200)

    def test_room_list_carries_the_hotel_today(self):
        out, code = self.call('api_hotel_rooms_list')
        self.assertEqual((code, out['hotel_today']), (200, TODAY.isoformat()))
        self.assertEqual(len(out['data']), 4)


# ================================================================ ngày trả phòng dự kiến: trang thật chạy trong node
NODE_PAGE = r'''
const fs = require('fs'), vm = require('vm');
const IN = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
class CL { constructor() { this.s = new Set(); } add(c) { this.s.add(c); } remove(c) { this.s.delete(c); }
  toggle(c, f) { const on = f === undefined ? !this.s.has(c) : !!f; if (on) this.s.add(c); else this.s.delete(c); return on; }
  contains(c) { return this.s.has(c); } }
class El { constructor(id) { this.id = id; this.value = ''; this.checked = false; this.disabled = false; this.min = '';
  this.max = ''; this.innerText = ''; this.innerHTML = ''; this.textContent = ''; this.classList = new CL(); this.style = {};
  this.dataset = {}; } addEventListener() {} closest() { return null; } querySelector() { return null; }
  querySelectorAll() { return []; } }
class Div { set innerText(v) { this._t = String(v); }
  get innerHTML() { return (this._t || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); } }
const els = new Map();
const document = { getElementById: (id) => { if (!els.has(id)) els.set(id, new El(id)); return els.get(id); },
  createElement: () => new Div(), querySelectorAll: () => [], addEventListener: () => {}, hidden: false, title: '' };
const calls = [];
const state = { rooms: IN.rooms_response, fail: {} };
const fetch = (url, opts) => {
  const method = (opts && opts.method) || 'GET';
  calls.push({ url, method, body: opts && opts.body ? JSON.parse(opts.body) : null });
  const r = method === 'GET' ? (url === '/api/hotel/rooms' ? state.rooms : { success: true, data: [] })
    : (state.fail[url] || { success: true, data: {} });
  return Promise.resolve({ ok: r.success !== false, status: r.success === false ? 409 : 200, json: async () => r });
};
const ctx = { document, window: {}, localStorage: { getItem: () => IN.lang, setItem() {} }, fetch, console,
  setTimeout: () => 0, setInterval: () => 0, Date, JSON, Promise, printReceipt: () => {}, __state: state };
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setImmediate(r)); };
(async () => {
  const out = { steps: [], errors: [] };
  try {
    vm.createContext(ctx);
    vm.runInContext(IN.script, ctx);
    await settle();
    for (const s of IN.steps) {
      document.getElementById('toast').innerText = '';
      const before = calls.length;
      let ret = vm.runInContext(s.js, ctx);
      if (ret && typeof ret.then === 'function') ret = await ret;
      await settle();
      const snap = { toast: document.getElementById('toast').innerText, calls: calls.slice(before),
                     ret: (ret === undefined || typeof ret === 'object') ? null : ret, els: {} };
      for (const id of (s.ids || [])) {
        const e = document.getElementById(id);
        snap.els[id] = { value: e.value, checked: e.checked, disabled: e.disabled, min: e.min, max: e.max,
                         text: e.textContent || e.innerText, hidden: e.classList.contains('hidden'), html: e.innerHTML };
      }
      out.steps.push(snap);
    }
  } catch (e) { out.errors.push(String(e && e.stack || e)); }
  console.log(JSON.stringify(out));
})();
'''


@unittest.skipUnless(shutil.which('node'), 'node không có trên máy này')
class TestRoomsPageExpectedCheckout(_Hotel):
    def setUp(self):
        super().setUp()
        self.ns, self.req = _routes(ROOM_ROUTES)

    def page(self, steps, lang='en'):
        """Trang Quản Lý Phòng THẬT (template render bằng jinja2) chạy trong node; GET /api/hotel/rooms = route thật."""
        html = render('hotel_rooms.html', lang=lang, tenant_currency='USD', hotel_today=TODAY.isoformat())
        script = re.findall(r'<script>([\s\S]*?)</script>', html)[-1]
        self.req.json = None
        rooms_response = json.loads(json.dumps(self.ns['api_hotel_rooms_list']()))
        tmp = tempfile.mkdtemp(prefix='p2_hotel3_')
        try:
            js, data = os.path.join(tmp, 'page.js'), os.path.join(tmp, 'in.json')
            with open(js, 'w', encoding='utf-8') as fh:
                fh.write(NODE_PAGE)
            with open(data, 'w', encoding='utf-8') as fh:
                json.dump({'script': script, 'rooms_response': rooms_response, 'steps': steps, 'lang': lang}, fh)
            r = subprocess.run(['node', js, data], capture_output=True, text=True, encoding='utf-8', timeout=120)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out['errors'], [])
        return out['steps']

    def occupy(self, rid, guest, expected, since):
        DB.hotel_rooms.update_one({'id': rid}, {'$set': {'status': 'Đang ở', 'guest_name': guest, 'checkin_date': since,
                                                         'expected_checkout_date': expected}})

    def send(self, call):
        """Gửi đúng lệnh POST trang vừa tạo qua route thật."""
        m = re.fullmatch(r'/api/hotel/rooms/(\d+)/(expected_checkout|checkin|checkout|charges)', call['url'])
        name = {'expected_checkout': 'api_hotel_room_expected_checkout', 'checkin': 'api_hotel_room_checkin',
                'checkout': 'api_hotel_room_checkout', 'charges': 'api_hotel_room_charges_add'}[m.group(2)]
        self.req.json = call['body']
        out = self.ns[name](int(m.group(1)))
        return (out, 200) if isinstance(out, dict) else out

    def test_past_date_card_is_an_amber_unknown_warning(self):
        self.occupy(1, 'Past Guest', D(-1), '2026-10-30T15:00:00')
        self.occupy(2, 'Today Guest', D(0), '2026-11-01T15:00:00')
        self.occupy(3, 'Later Guest', D(3), '2026-11-01T16:00:00')
        grid = self.page([{'js': '0', 'ids': ['roomGrid']}])[0]['els']['roomGrid']['html']
        spans = re.findall(r'<span class="(text-[^"]+)">([^<]*)</span>\s*<button onclick="event.stopPropagation\(\); '
                           r'openExpectedModal\((\d)\)', grid)
        by_room = {int(rid): (cls, text) for cls, text, rid in spans}
        self.assertEqual(by_room[1][0], 'text-amber-400/90')       # AI coi như chưa rõ ngày đi -> cảnh báo như "chưa rõ"
        self.assertIn('Past expected check-out', by_room[1][1])
        self.assertIn('date unknown', by_room[1][1])
        self.assertEqual(by_room[2], ('text-gray-400', 'Leaves today'))
        self.assertEqual(by_room[3][0], 'text-gray-400')
        self.assertTrue(by_room[3][1].startswith('Expected out: '))
        vi = self.page([{'js': '0', 'ids': ['roomGrid']}], lang='vi')[0]['els']['roomGrid']['html']
        self.assertIn('Quá ngày trả dự kiến', vi)
        self.assertIn('Trả phòng hôm nay', vi)

    def test_edit_window_for_a_date_saved_as_today_saves_without_400(self):
        self.occupy(1, 'Today Guest', D(0), '2026-11-01T15:00:00')
        steps = self.page([{'js': 'openExpectedModal(1)', 'ids': ['expectedEditDate', 'expectedEditToday', 'expectedEditNote']},
                           {'js': 'submitExpected(false)'}])
        st = steps[0]['els']
        self.assertTrue(st['expectedEditToday']['checked'])
        self.assertEqual((st['expectedEditDate']['value'], st['expectedEditDate']['disabled']), (D(0), True))
        self.assertTrue(st['expectedEditNote']['hidden'])
        call = steps[1]['calls'][0]
        self.assertEqual(call['body'], {'expected_checkout_date': D(0), 'same_day': True,
                                        'from_checkin_date': '2026-11-01T15:00:00'})
        self.assertEqual(self.send(call)[1], 200)

    def test_edit_window_for_a_passed_date_is_not_prefilled(self):
        self.occupy(1, 'Past Guest', D(-2), '2026-10-29T15:00:00')
        steps = self.page([{'js': 'openExpectedModal(1)', 'ids': ['expectedEditDate', 'expectedEditToday', 'expectedEditNote']},
                           {'js': 'submitExpected(false)'},
                           {'js': "document.getElementById('expectedEditDate').value = " + json.dumps(D(0)) + "; submitExpected(false)"},
                           {'js': "document.getElementById('expectedEditDate').value = " + json.dumps(D(2)) + "; submitExpected(false)"}])
        st = steps[0]['els']
        self.assertEqual((st['expectedEditDate']['value'], st['expectedEditDate']['min']), ('', D(1)))
        self.assertFalse(st['expectedEditToday']['checked'])
        self.assertFalse(st['expectedEditNote']['hidden'])
        self.assertIn('has passed', st['expectedEditNote']['text'])
        self.assertEqual((steps[1]['calls'], steps[1]['toast']), ([], 'Pick the expected check-out date (or tap Clear date).'))
        self.assertEqual(steps[2]['calls'], [])                    # gõ tay hôm nay mà không chọn "trả phòng trong hôm nay"
        self.assertIn('Pick a date after today', steps[2]['toast'])
        call = steps[3]['calls'][0]
        self.assertEqual(call['body']['expected_checkout_date'], D(2))
        self.assertEqual(self.send(call)[1], 200)

    def test_edit_window_opened_for_guest_a_cannot_write_to_guest_b(self):
        self.occupy(1, 'Guest A', D(2), '2026-11-01T15:00:00')
        steps = self.page([{'js': 'openExpectedModal(1)'},
                           {'js': "document.getElementById('expectedEditDate').value = " + json.dumps(D(4)) + "; submitExpected(false)"},
                           {'js': 'openCheckoutModal(1)'}, {'js': 'submitCheckout()'},
                           {'js': 'openAddChargeModal(1)'},
                           {'js': "document.getElementById('newChargeDesc').value = 'Minibar'; "
                                  "document.getElementById('newChargeAmount').value = '9'; submitAddCharge()"}])
        exp_call, out_call = steps[1]['calls'][0], steps[3]['calls'][0]
        charge_call = steps[5]['calls'][0]
        for call in (exp_call, out_call, charge_call):
            self.assertEqual(call['body']['from_checkin_date'], '2026-11-01T15:00:00')
        # trong lúc đó: khách A trả phòng ở máy khác, khách B nhận đúng phòng này
        self.occupy(1, 'Guest B', D(5), '2026-11-02T12:00:00')
        for call in (exp_call, out_call, charge_call):
            self.assertEqual(self.send(call)[1], 409, call['url'])
        room = DB.hotel_rooms.find_one({'id': 1})
        self.assertEqual((room['guest_name'], room['status'], room['expected_checkout_date']), ('Guest B', 'Đang ở', D(5)))
        self.assertEqual((DB.orders.count_documents({}), DB.hotel_room_charges.count_documents({})), (0, 0))

    def test_checkin_after_midnight_guest_leaving_today(self):
        steps = self.page([{'js': "openCheckinModal(1); handleRoomClick(1, 'Trống')", 'ids': ['expectedCheckout']},
                           {'js': "document.getElementById('guestName').value = 'Night Owl'; "
                                  "const b = document.getElementById('expectedCheckoutToday'); b.checked = true; "
                                  "syncLeavesToday('expectedCheckout', b); submitCheckin()", 'ids': ['expectedCheckout']},
                           {'js': "openCheckinModal(2); activeRoomId = 2; document.getElementById('guestName').value = 'X'; "
                                  "document.getElementById('expectedCheckout').value = " + json.dumps(D(0)) + "; submitCheckin()"}])
        self.assertEqual((steps[0]['els']['expectedCheckout']['min'], steps[0]['els']['expectedCheckout']['max']),
                         (D(1), D(366)))
        self.assertEqual((steps[1]['els']['expectedCheckout']['value'], steps[1]['els']['expectedCheckout']['disabled']),
                         (D(0), True))
        call = steps[1]['calls'][0]
        self.assertEqual((call['url'], call['body']['expected_checkout_date'], call['body']['same_day']),
                         ('/api/hotel/rooms/1/checkin', D(0), True))
        self.assertEqual(self.send(call)[1], 200)
        self.assertEqual(DB.hotel_rooms.find_one({'id': 1})['expected_checkout_date'], D(0))
        self.assertEqual(rh.open_walkins(BID, rh.list_rooms(BID), TODAY), set())
        self.assertEqual(steps[2]['calls'], [])                    # hôm nay gõ tay, không chọn rõ -> không gửi
        self.assertIn('Leaves today', steps[2]['toast'])


class TestRoomsPageTemplate(unittest.TestCase):
    def test_vi_and_en_texts_are_present(self):
        for lang, bits in (('en', ('Leaves today — arrived after midnight', 'Past expected check-out ({date})',
                                   'The saved date ({date}) has passed')),
                           ('vi', ('Khách trả phòng trong hôm nay — tới sau nửa đêm', 'Quá ngày trả dự kiến ({date})',
                                   'Ngày đã lưu ({date}) đã qua'))):
            html = render('hotel_rooms.html', lang=lang, tenant_currency='USD', hotel_today='2026-11-02')
            for b in bits:
                self.assertIn(b, html)
            self.assertIn('id="expectedCheckoutToday"', html)
            self.assertIn('id="expectedEditToday"', html)


# ================================================================ quoted_total: không lệch 1000 lần, VND có số lẻ
class TestQuotedTotal(_Hotel):
    def test_one_dot_group_is_read_one_way_per_currency(self):
        self.assertFalse(hotel._same_total('450.000', 450000.0, 'USD'))   # USD: 450.000 = 450, không phải 450 nghìn
        self.assertTrue(hotel._same_total('450.000', 450.0, 'USD'))
        self.assertFalse(hotel._same_total('450.000', 450.0, 'VND'))      # VND: 450.000 = 450 nghìn, không phải 450
        self.assertTrue(hotel._same_total('450.000', 450000.0, 'VND'))
        self.assertTrue(hotel._same_total('1.200.000', 1200000.0, 'AUD'))  # nhiều nhóm: chỉ có thể là dấu nghìn
        self.assertEqual(hotel._amounts('450.000', 'USD'), [450.0])
        self.assertEqual(hotel._amounts('450.000', 'VND'), [450000.0])

    def test_vnd_with_a_fraction_matches_what_the_guest_heard(self):
        for heard in ('1.234 VND', '1234', '1.234đ', '1,234', 1234):
            self.assertTrue(hotel._same_total(heard, 1234.5, 'VND'), heard)
        self.assertFalse(hotel._same_total('1.235', 1234.4, 'VND'))
        self.assertFalse(hotel._same_total('1234', 1234.5, 'AUD'))       # tiền có số lẻ: phải đúng tới xu

    def test_only_the_first_number_is_read(self):
        self.assertTrue(hotel._same_total('$450 for 3 nights', 450.0, 'USD'))
        self.assertTrue(hotel._same_total('$1,350.00 for 3 nights', 1350.0, 'USD'))
        self.assertTrue(hotel._same_total('$450.00.', 450.0, 'USD'))
        self.assertTrue(hotel._same_total('1 350,00 EUR', 1350.0, 'EUR'))
        self.assertFalse(hotel._same_total('$300 (was $450)', 450.0, 'USD'))
        self.assertFalse(hotel._same_total('3 nights: $450', 450.0, 'USD'))

    def test_vnd_change_with_a_fractional_total_end_to_end(self):
        DB.businesses.update_one({'id': BID}, {'$set': {'currency': 'VND', 'country': 'VN'}})
        DB.hotel_rooms.update_many({'room_type': 'Standard'}, {'$set': {'price_per_night': 1234.5}})
        c = wa(1)
        b = self.book_as(c, 1)
        args = {'booking_id': b['booking_id'], 'new_checkin_date': D(20), 'new_checkout_date': D(21)}
        q = run('hotel_change_dates', dict(args, customer_confirmed=False), c)
        self.assertEqual(q['new_total'], '1.234đ')
        r = run('hotel_change_dates', dict(args, customer_confirmed=True, quoted_total='1.234 VND'), c)
        self.assertTrue(r.get('changed'), r)
        self.assertEqual(find(b['booking_id'])['checkin_date'], D(20))


# ================================================================ giờ mở cửa qua nửa đêm (đã đúng từ vòng 2 — khoá lại)
class TestOvernightHoursText(hp.Base):
    def test_overnight_close_names_the_next_day_in_vi_and_en(self):
        hp.booking_rules.save_rules(BID, {'hours': {'fri': ['06:00', '02:00'], 'sat': ['09:00', '17:00']}},
                                    allow_overnight=True)
        hp.booking_rules._CACHE.clear()
        en, vi = hotel.facts(BID, 'en', NOW), hotel.facts(BID, 'vi', NOW)
        self.assertIn('Fri 06:00-02:00 (closes at 02:00 Sat, after midnight)', en)
        self.assertIn('T6 06:00-02:00 (đóng lúc 02:00 sáng T7, qua nửa đêm)', vi)
        self.assertIn('Sat 09:00-17:00', en)
        self.assertNotIn('09:00-17:00 (closes', en)


if __name__ == '__main__':
    unittest.main(verbosity=2)
