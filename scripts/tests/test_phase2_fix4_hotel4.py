# -*- coding: utf-8 -*-
"""Test OFFLINE — vòng sửa 4 khách sạn Phase 2 (hotel4): trần giữ phòng của chat web CHƯA xác minh.
  - chỉ tính lượt giữ CHƯA người thật nào của khách sạn ghi nhận: nhân viên duyệt / sửa / xếp phòng / bấm "Đã xem" trên
    /hotel/reservations (khách sạn bật tự xác nhận: AI ghi thẳng 'confirmed', trước đây không có cách nào nhả suất), hoặc khách
    nhận phòng tại quầy -> suất mở lại; khách tự dời ngày trong chat -> tính lại (cả khi dời vào đêm đã đầy);
  - trần theo CẢ KHÁCH SẠN cộng với trần theo loại: tổng lượt giữ chưa xác minh mỗi đêm <= max(1, ~40% tổng số phòng) —
    khách sạn nhỏ mỗi phòng / villa 1 loại không còn bị giữ hết phòng;
  - vượt trần: yêu cầu thành 1 dòng 'requested' (chưa giữ phòng, không chiếm phòng) trên trang Đặt phòng của nhân viên để
    Duyệt (kiểm lại phòng trống) / Từ chối, hội thoại được gắn needs_human + handoff_reason như ask_team; ghi chú cho nhân viên
    chỉ tới trang Đặt phòng — không còn bảo nhập qua link đặt phòng công khai (giới hạn theo IP);
  - 2 chat cùng lúc tranh suất cuối mà cả 2 cùng ghi trước khi bên nào kiểm lại: CẢ 2 cùng huỷ (an toàn, không vượt trần) —
    đúng như tài liệu create_hold nói giờ (trước đây ghi sai là "bên vượt trần tự huỷ");
  - scripts/ai_sim: kịch bản đặt phòng nhận dòng 'requested' khi trần đầy (2 lượt chạy cùng đêm), dữ kiện cho giám khảo nói rõ.

KHÔNG import app.py, KHÔNG mở MongoDB thật, KHÔNG gọi API trả phí: DB giả + stub của test_phase2_hotel_pack (mongo_client /
requests / ai_function_tools được thay TRƯỚC mọi import); route app.py lấy nguyên mã nguồn qua ast; trang render bằng jinja2 thật.

Chạy: python scripts/tests/test_phase2_fix4_hotel4.py
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
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_phase2_hotel_pack as hp  # noqa: E402  (DB giả + stub TRƯỚC khi nạp reservations_hotel / ai_packs.hotel)
from test_phase2_fix_hotel import _staff_route, find  # noqa: E402
from test_phase2_fix2_hotel import page_state, render  # noqa: E402
from test_phase2_fix3_hotel3 import ROOM_ROUTES, _Hotel, _routes, wa, web  # noqa: E402

DB, BID, D, run, resv, rh, hotel = hp.DB, hp.BID, hp.D, hp.run, hp.resv, hp.rh, hp.hotel
TODAY, PackError = hp.TODAY, hp.PackError
APP_PY = os.path.join(hp.ROOT, 'app.py')


def _page():
    """Route THẬT hotel_reservations_page (bỏ decorator) trên DB giả: trả đúng context nó đưa cho template."""
    with open(APP_PY, encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    node = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'hotel_reservations_page'))
    node.decorator_list = []
    captured = {}
    ns = {'db': DB, 'session': {'business_id': BID, 'user_id': 'u-1'}, 'tenant_today': lambda bid: TODAY,
          'flash': lambda *a, **k: None, 'url_for': lambda *a, **k: 'https://example.test/hotel/reserve',
          'render_template': lambda tpl, **ctx: captured.update(ctx, _tpl=tpl) or 'html'}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), ns)
    ns['hotel_reservations_page']()
    return captured


def _page_html(lang='en'):
    ctx = _page()
    html = render('hotel_reservations.html', lang=lang, reservations=ctx['reservations'], rooms=ctx['rooms'],
                  today=TODAY.isoformat(), reservation_link='x')
    return ctx, html


def _row(html, rid):
    m = re.search(r'<tr class="([^"]*)" data-res-id="%d">(.*?)</tr>' % rid, html, re.S)
    assert m, rid
    return m.group(1), m.group(2)


class _Staff(_Hotel):
    def setUp(self):
        super().setUp()
        self.ns, self.req = _staff_route()

    def staff(self, rid, **body):
        """PATCH /api/hotel_reservations/<rid> như trang gửi: kèm đúng những gì dòng đó đang hiện (from_*)."""
        self.req.json = dict(page_state(rid), **body)
        out = self.ns['api_hotel_reservation_update'](rid)
        return out if isinstance(out, tuple) else (out, 200)

    def requests_(self):
        return [r for r in DB.hotel_reservations.docs if r.get('status') == rh.STAFF_REQUEST]


# ================================================================ suất được nhả khi người thật của khách sạn đã ghi nhận
class TestAcknowledgedHoldsLeaveTheQuota(_Staff):
    def test_auto_confirm_hotel_has_a_mark_reviewed_lever(self):
        self.settings(auto_confirm=True)
        a = self.book_as(web(1), 1)                                 # Standard 2 phòng -> trần 1; AI ghi thẳng 'confirmed'
        self.assertEqual(find(a['booking_id'])['status'], 'confirmed')
        self.assertTrue(self.book_as(web(2), 2).get('request_sent_to_team'))
        ctx, html = _page_html()
        self.assertTrue(next(r for r in ctx['reservations'] if r['id'] == a['booking_id'])['needs_review'])
        _cls, cells = _row(html, a['booking_id'])
        self.assertIn(f"markReviewed({a['booking_id']}, this)", cells)
        self.assertIn('Mark reviewed', cells)
        self.assertIn('counts toward the online hold limit until staff review it', cells)
        self.assertIn('Đã xem', _row(_page_html('vi')[1], a['booking_id'])[1])
        out, code = self.staff(a['booking_id'], reviewed=True)
        self.assertEqual((out, code), ({'success': True}, 200))
        doc = find(a['booking_id'])
        self.assertEqual((doc['status'], doc['room_id']), ('confirmed', 1))       # chỉ ghi nhận, không đổi gì khác
        self.assertTrue(doc.get('staff_reviewed_at'))
        self.assertFalse(rh.unverified_web_hold(doc))
        ctx, html = _page_html()
        self.assertFalse(next(r for r in ctx['reservations'] if r['id'] == a['booking_id'])['needs_review'])
        self.assertNotIn('markReviewed(', _row(html, a['booking_id'])[1])
        c = self.book_as(web(3), 3)                                 # suất chat web mở lại
        self.assertIn('booking_id', c)
        self.assertNoDoubleBooking()

    def test_mark_reviewed_button_only_on_unreviewed_unverified_ai_rows(self):
        self.settings(auto_confirm=True)
        a = self.book_as(web(1), 1)
        b = self.book_as(wa(2), 2, room_type='Deluxe')              # chat đã xác minh: không tính vào trần
        DB.hotel_reservations.insert_one(resv(600, D(8), D(9), room_id=4, source='web'))       # form công khai / nhân viên
        ctx, html = _page_html()
        flags = {r['id']: r['needs_review'] for r in ctx['reservations']}
        self.assertEqual(flags, {a['booking_id']: True, b['booking_id']: False, 600: False})
        self.assertEqual(html.count('onclick="markReviewed('), 1)
        js = ''.join(re.findall(r'<script>(.*?)</script>', html, re.S))
        self.assertIn('JSON.stringify({ reviewed: true, ...shownState(row) })', js)
        node = shutil.which('node')
        if node:
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as fh:
                fh.write(js)
            try:
                res = subprocess.run([node, '--check', fh.name], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, res.stderr)
            finally:
                os.unlink(fh.name)

    def test_assigning_a_room_to_a_pending_ai_hold_releases_it(self):
        a = self.book_as(web(1), 1)                                 # chờ duyệt, phòng 101
        self.assertTrue(self.book_as(web(2), 2).get('request_sent_to_team'))
        out, code = self.staff(a['booking_id'], room_id=2)          # nhân viên đổi sang phòng 102 (vẫn chờ duyệt)
        self.assertEqual((out, code), ({'success': True}, 200))
        doc = find(a['booking_id'])
        self.assertEqual((doc['status'], doc['room_id']), ('pending', 2))
        self.assertTrue(doc.get('staff_reviewed_at'))
        self.assertFalse(rh.unverified_web_hold(doc))
        c = self.book_as(web(3), 3)
        self.assertEqual(find(c['booking_id'])['room_id'], 1)
        self.assertNoDoubleBooking()

    def test_stale_page_cannot_mark_reviewed(self):
        self.settings(auto_confirm=True)
        a = self.book_as(web(1), 1, checkin_date=D(20), checkout_date=D(21))
        shown = page_state(a['booking_id'])                         # trang mở lúc khách chưa dời ngày
        run('hotel_change_dates', hp.with_quote({'booking_id': a['booking_id'], 'new_checkin_date': D(22),
                                                 'new_checkout_date': D(23), 'customer_confirmed': True}, web(1)), web(1))
        self.req.json = dict(shown, reviewed=True)
        out = self.ns['api_hotel_reservation_update'](a['booking_id'])
        self.assertEqual(out[1], 409)                               # không ghi nhận ngày nhân viên chưa thấy
        self.assertFalse(find(a['booking_id']).get('staff_reviewed_at'))

    def test_guest_moving_the_dates_counts_again(self):
        c1 = web(1)
        a = self.book_as(c1, 1, checkin_date=D(20), checkout_date=D(21))
        self.assertEqual(self.staff(a['booking_id'], reviewed=True)[1], 200)
        self.assertFalse(rh.unverified_web_hold(find(a['booking_id'])))
        r = run('hotel_change_dates', hp.with_quote({'booking_id': a['booking_id'], 'new_checkin_date': D(22),
                                                     'new_checkout_date': D(23), 'customer_confirmed': True}, c1), c1)
        self.assertTrue(r['changed'])
        doc = find(a['booking_id'])
        self.assertIsNone(doc['staff_reviewed_at'])                 # nhân viên xem NGÀY CŨ
        self.assertTrue(rh.unverified_web_hold(doc))

    def test_reviewed_hold_cannot_be_moved_into_a_full_night(self):
        self.book_as(web(1), 1, checkin_date=D(8), checkout_date=D(9))
        c2 = web(2)
        b = self.book_as(c2, 2, checkin_date=D(12), checkout_date=D(13))
        self.assertEqual(self.staff(b['booking_id'], reviewed=True)[1], 200)
        args = {'booking_id': b['booking_id'], 'new_checkin_date': D(8), 'new_checkout_date': D(9)}
        with self.assertRaises(PackError) as cm:
            run('hotel_change_dates', dict(args, customer_confirmed=False), c2)
        self.assertIn('NOT changed', str(cm.exception))
        self.assertEqual(find(b['booking_id'])['checkin_date'], D(12))

    def test_guest_check_in_at_the_desk_releases_the_hold(self):
        a = self.book_as(web(1), 1, checkin_date=D(0), checkout_date=D(2))      # khách tới hôm nay, phòng 101
        other = self.book_as(wa(5), 5, room_type='Deluxe', checkin_date=D(0), checkout_date=D(2))
        self.assertTrue(self.book_as(web(2), 2, checkin_date=D(0), checkout_date=D(2)).get('request_sent_to_team'))
        ns, req = _routes(ROOM_ROUTES)
        req.json = {'guest_name': 'Guest Number1', 'expected_checkout_date': D(2)}
        out = ns['api_hotel_room_checkin'](1)
        self.assertTrue(out['success'], out)
        doc = find(a['booking_id'])
        self.assertTrue(doc.get('checked_in_at'))
        self.assertFalse(rh.unverified_web_hold(doc))
        self.assertFalse(find(other['booking_id']).get('checked_in_at'))      # chỉ đặt phòng của CHÍNH phòng đó
        b = self.book_as(web(3), 3, checkin_date=D(0), checkout_date=D(2))
        self.assertEqual(find(b['booking_id'])['room_id'], 2)
        self.assertNoDoubleBooking()

    def test_mark_checked_in_only_stays_covering_tonight(self):
        DB.hotel_reservations.insert_many([
            resv(701, D(-1), D(1), room_id=1, source='ai_bot', ai_verified=False),
            resv(702, D(3), D(5), room_id=1, source='ai_bot', ai_verified=False),
            resv(703, D(-2), D(0), room_id=1, source='ai_bot', ai_verified=False),   # trả phòng sáng nay
            resv(704, D(0), D(1), room_id=2, source='ai_bot', ai_verified=False),
            resv(705, D(0), D(1), room_id=1, source='ai_bot', ai_verified=False, status='cancelled')])
        # khách vừa tới = khách của đặt phòng (resv() mặc định 'Other Guest'); khách khác: test_phase2_fix5_hotel5
        self.assertEqual(rh.mark_checked_in(BID, 1, TODAY, guest_name='Other Guest'), 1)
        self.assertEqual([r['id'] for r in DB.hotel_reservations.docs if r.get('checked_in_at')], [701])


# ================================================================ trần theo cả khách sạn
class TestHotelWideCap(_Staff):
    def test_holds_across_types_are_capped_for_the_whole_hotel(self):
        self.assertEqual(rh.web_hold_cap(len(rh.list_rooms(BID))), 2)          # 4 phòng -> tối đa 2 lượt chưa xác minh/đêm
        a = self.book_as(web(1), 1)
        b = self.book_as(web(2), 2, room_type='Deluxe')
        c = self.book_as(web(3), 3, room_type='Suite', guests=2)                # loại riêng còn trống, nhưng cả khách sạn đã 2/2
        self.assertIn('booking_id', a)
        self.assertIn('booking_id', b)
        self.assertTrue(c.get('request_sent_to_team'))
        self.assertNotIn('booking_id', c)
        self.assertEqual(len(self.live_ai()), 2)
        self.assertIn('booking_id', self.book_as(wa(4), 4, room_type='Suite'))  # chat đã xác minh không bị trần chặn
        d = self.book_as(web(6), 6, room_type='Suite', checkin_date=D(10), checkout_date=D(11))   # đêm D10: chưa ai giữ
        self.assertIn('booking_id', d)
        self.assertNoDoubleBooking()

    def test_boutique_with_one_room_per_type(self):
        DB.hotel_rooms.docs[:] = []
        for i, name in enumerate(('Garden', 'Ocean', 'Hill', 'River', 'Forest')):
            DB.hotel_rooms.insert_one(hp.room(20 + i, f'V{i + 1}', f'Villa {name}', 200, cap=2))
        got = [self.book_as(web(n), n, room_type=f'Villa {name}')
               for n, name in enumerate(('Garden', 'Ocean', 'Hill', 'River', 'Forest'), start=1)]
        self.assertEqual(['booking_id' in g for g in got], [True, True, False, False, False])   # 5 villa -> trần 2
        self.assertTrue(all(g.get('request_sent_to_team') for g in got[2:]))
        self.assertEqual(len(self.live_ai()), 2)
        self.assertEqual(len(self.requests_()), 3)

    def test_availability_warns_for_every_type_when_the_hotel_is_full(self):
        self.book_as(web(1), 1)
        self.book_as(web(2), 2, room_type='Deluxe')
        av = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10)}, web(3))
        free = [t for t in av['room_types'] if t['available']]
        self.assertEqual({t['room_type'] for t in free}, {'Standard', 'Suite'})
        for t in free:
            self.assertIn('no room can be held online', t['booking_is'])
        av = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10)}, wa(4))
        self.assertTrue(all('booking_is' not in t for t in av['room_types']))

    def test_moving_into_a_night_full_hotel_wide_is_refused(self):
        self.book_as(web(1), 1, checkin_date=D(8), checkout_date=D(9))
        self.book_as(web(2), 2, room_type='Deluxe', checkin_date=D(8), checkout_date=D(9))
        c3 = web(3)
        b = self.book_as(c3, 3, room_type='Suite', checkin_date=D(12), checkout_date=D(13))
        with self.assertRaises(PackError) as cm:
            run('hotel_change_dates', {'booking_id': b['booking_id'], 'new_checkin_date': D(8), 'new_checkout_date': D(9),
                                       'customer_confirmed': False}, c3)
        self.assertIn('across the hotel', str(cm.exception))
        self.assertEqual(find(b['booking_id'])['checkin_date'], D(12))

    def test_web_holds_full_hotel_wide_directly(self):
        rooms = rh.list_rooms(BID)
        types = rh.room_types(rooms)
        DB.hotel_reservations.insert_many([resv(801, D(8), D(9), room_id=1, source='ai_bot', ai_verified=False),
                                           resv(802, D(8), D(9), room_id=3, source='ai_bot', ai_verified=False)])
        self.assertTrue(rh.web_holds_full(BID, rooms, types, 'suite', D(8), D(9)))            # 2 + 1 > 2
        self.assertFalse(rh.web_holds_full(BID, rooms, types, 'suite', D(8), D(9), ignore_id=802))
        self.assertFalse(rh.web_holds_full(BID, rooms, types, 'suite', D(8), D(9), extra=0))  # đúng 2/2: chưa vượt
        DB.hotel_reservations.update_one({'id': 802}, {'$set': {'staff_reviewed_at': 'x'}})
        self.assertFalse(rh.web_holds_full(BID, rooms, types, 'suite', D(8), D(9)))


# ================================================================ vượt trần: yêu cầu không bị lạc
class TestOverCapRequestIsTracked(_Staff):
    def over_cap(self, n=2, lang='en', **kw):
        self.book_as(web(1), 1)
        c = web(n, lang=lang)
        DB.bot_customers.update_one({'id': c['customer_id']}, {'$set': {'business_id': BID}}, upsert=True)
        return c, self.book_as(c, n, **kw)

    def test_request_is_a_row_staff_see_and_the_chat_is_flagged(self):
        c, b = self.over_cap(special_requests='Late arrival')
        self.assertTrue(b['request_sent_to_team'])
        self.assertEqual((b['room_held'], b['confirmed'], b['status']), (False, False, 'pending'))
        [req] = self.requests_()
        self.assertEqual({k: req.get(k) for k in ('guest_name', 'guest_phone', 'checkin_date', 'checkout_date', 'party_size',
                                                   'room_type', 'room_id', 'source', 'ai_verified', 'request_reason',
                                                   'ai_conversation_id', 'special_requests')},
                         {'guest_name': 'Guest Number2', 'guest_phone': '0499999902', 'checkin_date': D(8),
                          'checkout_date': D(10), 'party_size': 2, 'room_type': 'Standard', 'room_id': None,
                          'source': 'ai_bot', 'ai_verified': False, 'request_reason': 'web_hold_cap',
                          'ai_conversation_id': c['customer_id'], 'special_requests': 'Late arrival'})
        self.assertNotIn('booking_id', b)
        self.assertNotIn(str(req['id']), json.dumps(b))             # khách không nhận số nào
        self.assertNotIn(rh.STAFF_REQUEST, rh.LIVE_STATUSES)
        self.assertEqual(DB.hotel_room_nights.count_documents({'reservation_id': req['id']}), 0)
        # hội thoại có huy hiệu "cần nhân viên" + lý do (như ask_team) — không chỉ 1 dòng ghi chú + email
        bc = DB.bot_customers.find_one({'id': c['customer_id']})
        self.assertTrue(bc['needs_human'])
        for bit in (f"#{req['id']}", 'no room held', 'Hotel > Reservations', 'Guest Number2', 'Standard', D(8)):
            self.assertIn(bit, bc['handoff_reason'])
        # ghi chú cho nhân viên: tới trang Đặt phòng của nhân viên, KHÔNG bảo nhập qua link công khai (giới hạn theo IP)
        note = hp.STAFF_NOTES[-1][2]
        self.assertIn(f"#{req['id']}", note)
        self.assertIn('listed on Hotel > Reservations', note)
        self.assertNotIn('public booking link', note)
        self.assertEqual(hp.OWNER_ALERTS[-1][3], 'hotel_webcap')
        # yêu cầu không chiếm phòng: khách đã xác minh vẫn đặt được phòng còn lại
        av = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10), 'room_type': 'Standard'}, wa(3))
        self.assertEqual(av['room_types'][0]['rooms_left'], 1)
        self.assertEqual(find(self.book_as(wa(3), 3)['booking_id'])['room_id'], 2)
        # trang Đặt phòng của nhân viên hiện yêu cầu, nổi bật như chờ duyệt, Duyệt / Từ chối, chưa xếp phòng được
        ctx, html = _page_html()
        self.assertIn(req['id'], [r['id'] for r in ctx['reservations']])
        cls, cells = _row(html, req['id'])
        self.assertIn('is-pending', cls)
        self.assertIn('Request — no room held', cells)
        self.assertIn(f"updateStatus({req['id']}, 'confirmed', this)", cells)
        self.assertIn(f"updateStatus({req['id']}, 'cancelled', this)", cells)
        self.assertIn('Decline', cells)
        self.assertRegex(cells, r'<select class="room-select"[^>]*disabled')
        vi_cells = _row(_page_html('vi')[1], req['id'])[1]
        self.assertIn('Yêu cầu — chưa giữ phòng', vi_cells)
        self.assertIn('Từ chối', vi_cells)
        self.assertNoDoubleBooking()

    def test_vi_hotel_note_and_reason(self):
        DB.businesses.update_one({'id': BID}, {'$set': {'country': 'VN', 'currency': 'VND'}})
        c, b = self.over_cap(lang='vi')
        self.assertTrue(b['request_sent_to_team'])
        note = hp.STAFF_NOTES[-1][2]
        self.assertIn('Khách sạn > Đặt phòng', note)
        self.assertIn('Duyệt', note)
        self.assertNotIn('link đặt phòng công khai', note)
        reason = DB.bot_customers.find_one({'id': c['customer_id']})['handoff_reason']
        self.assertIn('CHƯA giữ phòng', reason)
        self.assertIn('Khách sạn > Đặt phòng', reason)

    def test_same_request_twice_in_a_chat_makes_one_row(self):
        c, _b = self.over_cap()
        again = self.book_as(c, 2)
        self.assertTrue(again['request_sent_to_team'])
        self.assertEqual(len(self.requests_()), 1)
        self.assertEqual(sum(1 for a in hp.OWNER_ALERTS if a[3] == 'hotel_webcap'), 1)    # không báo nhân viên 2 lần
        self.book_as(c, 2, checkin_date=D(9), checkout_date=D(10))                         # ngày khác = yêu cầu khác
        self.assertEqual(len(self.requests_()), 2)

    def test_waiting_handoff_keeps_its_reason(self):
        c = web(2)
        DB.bot_customers.insert_one({'id': c['customer_id'], 'business_id': BID, 'ai_paused': True,
                                     'handoff_reason': 'Complaint about noise'})
        self.book_as(web(1), 1)
        self.assertTrue(self.book_as(c, 2).get('request_sent_to_team'))
        bc = DB.bot_customers.find_one({'id': c['customer_id']})
        self.assertEqual((bc['needs_human'], bc['handoff_reason']), (True, 'Complaint about noise'))

    def test_staff_approve_rechecks_rooms_then_assign(self):
        self.over_cap()
        [req] = self.requests_()
        out, code = self.staff(req['id'], status='confirmed')       # không cần reopen=true: đây không phải đặt phòng đã huỷ
        self.assertEqual((out, code), ({'success': True}, 200))
        doc = find(req['id'])
        self.assertEqual((doc['status'], doc['room_id']), ('confirmed', None))
        self.assertTrue(doc.get('staff_confirmed_at') and doc.get('staff_reviewed_at'))
        self.assertFalse(rh.unverified_web_hold(doc))
        out, code = self.staff(req['id'], room_id=2)
        self.assertEqual((out, code), ({'success': True}, 200))
        self.assertEqual(find(req['id'])['room_id'], 2)
        self.assertEqual(DB.hotel_room_nights.count_documents({'reservation_id': req['id']}), 2)
        self.assertNoDoubleBooking()

    def test_staff_approve_when_no_room_is_left(self):
        self.over_cap()
        [req] = self.requests_()
        self.book_as(wa(3), 3)                                      # phòng Standard cuối vừa bán cho khách đã xác minh
        out, code = self.staff(req['id'], status='confirmed')
        self.assertEqual(code, 409)
        self.assertIn('the request was not accepted', out['message'])
        self.assertEqual(find(req['id'])['status'], rh.STAFF_REQUEST)
        self.assertNoDoubleBooking()

    def test_staff_decline(self):
        self.over_cap()
        [req] = self.requests_()
        self.assertEqual(self.staff(req['id'], status='cancelled'), ({'success': True}, 200))
        self.assertEqual(find(req['id'])['status'], 'cancelled')

    def test_guest_cannot_change_or_cancel_a_request_in_chat(self):
        self.over_cap()
        [req] = self.requests_()
        owner = wa(2)                                               # đúng SĐT khách đã gõ, nay đã xác minh
        with self.assertRaises(PackError) as cm:
            run('hotel_cancel_booking', {'booking_id': req['id'], 'customer_confirmed': True}, owner)
        self.assertIn('request the hotel team is still handling', str(cm.exception))
        with self.assertRaises(PackError):
            run('hotel_change_dates', {'booking_id': req['id'], 'new_checkin_date': D(9), 'new_checkout_date': D(11),
                                       'customer_confirmed': False}, owner)
        self.assertEqual(find(req['id'])['status'], rh.STAFF_REQUEST)
        self.assertEqual(run('hotel_my_bookings', {}, owner)['bookings'], [])   # không liệt kê như 1 đặt phòng


# ================================================================ 2 chat cùng lúc: có thể CẢ 2 cùng huỷ (an toàn)
class TestTwoChatsBothCancel(_Staff):
    def test_both_written_before_either_rechecks_both_cancel(self):
        """A và B đều qua bước kiểm TRƯỚC khi ghi, A ghi, B ghi, rồi mới tới lượt kiểm lại: cả 2 đều thấy 2 > trần 1."""
        real = rh.web_holds_full
        state = {'phase': 'A'}
        seen = {}

        def interleave(*a, **kw):
            if kw.get('extra', 1) == 1:
                return False if state['phase'] == 'B' else real(*a, **kw)   # bước kiểm trước của B: lúc A chưa ghi
            if state['phase'] == 'A':                                        # A vừa ghi xong, sắp kiểm lại...
                state['phase'] = 'B'
                seen['b'] = self.book_as(web(2), 2)                           # ...thì B chạy trọn trong khoảng đó
                return seen['a_recheck']
            seen['a_recheck'] = seen['b_recheck'] = real(*a, **kw)           # kiểm lại lúc CẢ 2 lượt giữ còn sống
            return seen['b_recheck']
        rh.web_holds_full = interleave
        try:
            a = self.book_as(web(1), 1)
        finally:
            rh.web_holds_full = real
        self.assertEqual((seen['a_recheck'], seen['b_recheck']), (True, True))
        for out in (a, seen['b']):
            self.assertTrue(out['request_sent_to_team'])
            self.assertNotIn('booking_id', out)
        self.assertEqual(self.live_ai(), [])                                 # không bao giờ vượt trần; suất để trống
        losers = [r for r in DB.hotel_reservations.docs if r.get('cancelled_by') == 'system']
        self.assertEqual(len(losers), 2)
        self.assertTrue(all(r['cancel_reason'] == 'unverified online hold limit reached' for r in losers))
        self.assertEqual(DB.hotel_room_nights.count_documents({}), 0)        # mọi phiếu đã trả
        self.assertEqual(sorted(r['guest_name'] for r in self.requests_()), ['Guest Number1', 'Guest Number2'])
        # khách đã xác minh / nhân viên vẫn lấy được suất đó
        self.assertIn('booking_id', self.book_as(wa(3), 3))
        self.assertNoDoubleBooking()

    def test_docstring_no_longer_claims_only_one_side_cancels(self):
        doc = rh.create_hold.__doc__
        self.assertNotIn('bên vượt trần tự huỷ phiếu của mình', doc)
        self.assertIn('CẢ 2 cùng huỷ', doc)
        self.assertIn('không bao giờ vượt trần', doc)


# ================================================================ scripts/ai_sim: trần đầy là kết quả đúng
class TestSimScenarios(unittest.TestCase):
    def test_booking_scenarios_accept_a_staff_request_and_facts_say_why(self):
        sys.path.insert(0, os.path.join(hp.ROOT, 'scripts', 'ai_sim'))
        import scenarios_hotel as sh
        from datetime import timedelta
        nxt = lambda n: TODAY + timedelta(days=n)  # noqa: E731
        shop = {'currency': 'AUD', 'info': {}, 'dates': {'today': TODAY, 'sat': nxt(5), 'next_fri': nxt(11),
                                                       'next_sat': nxt(12)}}
        data = {'types': {'Standard': {'name': 'Standard', 'rooms': 3, 'rates': {100.0}, 'cap': 4, 'unpriced': 0}},
                'auto_confirm': True, 'checkin_time': None, 'checkout_time': None, 'free_cancel_hours': None,
                'min_nights': 1}
        created = [ck for sc in sh.scenarios(shop, data) for ck in sc['checks'] if ck['kind'] == 'created']
        self.assertEqual(len(created), 3)
        for ck in created:
            self.assertIn(sh.STAFF_REQUEST, ck['status_in'])
            self.assertIn('pending', ck['status_in'])
        self.assertEqual(sh.STAFF_REQUEST, rh.STAFF_REQUEST)
        self.assertEqual(sh._status(dict(data, auto_confirm=False), 2), ['pending', 'requested'])
        facts = sh.facts(shop, data)
        self.assertIn('Online hold limit', facts)
        self.assertIn('never "confirmed"', facts)


if __name__ == '__main__':
    unittest.main(verbosity=1)
