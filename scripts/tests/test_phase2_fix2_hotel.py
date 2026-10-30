# -*- coding: utf-8 -*-
"""Test OFFLINE — vòng sửa 2 khách sạn Phase 2 (sau khi kiểm tra lại các bản sửa vòng 1):
  #28 check-in khách vãng lai nhận NGÀY TRẢ PHÒNG DỰ KIẾN tuỳ chọn (ô ngày trên trang Phòng + API, ngày theo giờ khách sạn,
      phải sau hôm nay), lưu trên phòng, sửa được khi khách ở thêm, xoá khi trả phòng / dọn xong; AI coi phòng bận mọi đêm
      tới ngày đó; không có ngày thì AI không bao giờ tự xác nhận phòng đó cho các đêm sau (pending + báo nhân viên);
  #18 trang /hotel/reservations gửi kèm đúng những gì dòng đang hiện (trạng thái, ngày, số khách, phòng): khách dời ngày /
      đổi số khách trong chat (vẫn 'pending') thì "Duyệt" / xếp phòng trên trang cũ -> 409, không duyệt ngày chưa thấy;
  #17 lượt xác nhận đổi ngày KHÔNG kèm quoted_total không được ghi im lặng (giá có thể đã đổi từ lượt báo giá) — báo lại
      giá; _same_total không còn khớp nhầm số tiền lệch 100 lần ('450000' với $4,500.00);
  sim: câu "sự thật" về huỷ phòng của scenarios_hotel khớp luật đang áp; giờ mở cửa qua nửa đêm nói rõ ngày hôm sau.

KHÔNG import app.py, KHÔNG mở MongoDB thật, KHÔNG gọi API trả phí: DB giả + stub của test_phase2_hotel_pack (mongo_client /
requests / ai_function_tools được thay TRƯỚC mọi import); route app.py lấy nguyên mã nguồn qua ast; template render bằng
jinja2 thuần.

Chạy: python scripts/tests/test_phase2_fix2_hotel.py
"""
import ast
import copy
import os
import re
import sys
import types
import unittest
import uuid
from datetime import datetime

import jinja2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_phase2_hotel_pack as hp  # noqa: E402  (DB giả + stub TRƯỚC khi nạp reservations_hotel / ai_packs.hotel)
from test_phase2_fix_hotel import (OWNER_ALERTS_TEXT, _staff_route, change, claims_of,  # noqa: E402
                                   find)

DB, BID, D, run, ctx, resv, rh, hotel = hp.DB, hp.BID, hp.D, hp.run, hp.ctx, hp.resv, hp.rh, hp.hotel
NOW, TODAY = hp.NOW, hp.TODAY
from pymongo import ReturnDocument  # noqa: E402  (chỉ hằng số)


# ---------------------------------------------------------------- route phòng (mã thật của app.py qua ast)
ROOM_ROUTES = ('api_hotel_room_checkin', 'api_hotel_room_expected_checkout', 'api_hotel_room_checkout',
               'api_hotel_room_mark_clean', 'hotel_rooms_page')


def _room_routes():
    with open(os.path.join(hp.ROOT, 'app.py'), encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ROOM_ROUTES:
            node = copy.deepcopy(node)
            node.decorator_list = []
            nodes.append(node)
    req = types.SimpleNamespace(json=None)
    req.get_json = lambda silent=False: req.json
    ns = {'db': DB, 'session': {'business_id': BID, 'user_id': 'u-1'}, 'request': req, 'jsonify': lambda d: d,
          '_vi_en': lambda vi, en: en, 'tenant_today': lambda bid: TODAY, 'datetime': datetime,
          'ReturnDocument': ReturnDocument, 'next_mongo_id': hp._next_id, 'uuid': uuid,
          'parse_datetime': lambda s: datetime.fromisoformat(str(s)), '_record_pos_transaction': lambda *a, **k: None,
          'render_template': lambda tpl, **kw: ('html', tpl, kw)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns, req


# ---------------------------------------------------------------- template thật (jinja2 thuần, sidebar bỏ qua)
class _Loader(jinja2.FileSystemLoader):
    def get_source(self, environment, template):
        if template.startswith('components/'):
            return '', None, lambda: True
        return super().get_source(environment, template)


JINJA = jinja2.Environment(loader=_Loader(os.path.join(hp.ROOT, 'templates')))
JINJA.globals['url_for'] = lambda *a, **k: '/x'
JINJA.globals['asset_v'] = lambda *a, **k: '1'


def render(name, lang='en', **kw):
    base = {'session': {'business_id': BID, 'role': 'admin'}, 'default_lang': lang, 'active_industry_code': 'hotel'}
    base.update(kw)
    return JINJA.get_template(name).render(**base)


# Cách JS shownState() của trang đặt phòng đổi data-* của ô phòng thành tham số from_* (kiểm có đúng trong template ở dưới).
SHOWN_KEYS = (('from_status', 'status'), ('from_checkin_date', 'checkin'), ('from_checkout_date', 'checkout'),
              ('from_party_size', 'party'), ('from_room_id', 'room'))


def page_state(rid):
    """Đúng những gì trang /hotel/reservations đang hiện cho đặt phòng rid (render template thật, đọc data-* của ô phòng)."""
    rows = [find(rid)]
    rooms = [{'id': r['id'], 'room_number': r['room_number'], 'room_type': r['room_type']} for r in DB.hotel_rooms.docs]
    html = render('hotel_reservations.html', reservations=rows, rooms=rooms, today=TODAY.isoformat(), reservation_link='x')
    cell = re.search(r'<td class="px-6 py-4" data-room-cell([^>]*)>', html).group(1)
    attrs = dict(re.findall(r'data-(\w+)="([^"]*)"', cell))
    return {key: attrs[attr] for key, attr in SHOWN_KEYS}


# ================================================================ #28 khách vãng lai: ngày trả phòng dự kiến
class TestWalkInExpectedCheckout(hp.Base):
    def setUp(self):
        super().setUp()
        self.ns, self.req = _room_routes()
        self.settings(auto_confirm=True)

    def call(self, name, rid, body=None):
        self.req.json = body
        out = self.ns[name](rid)
        return (out, 200) if isinstance(out, dict) else out

    def room(self, rid):
        return DB.hotel_rooms.find_one({'id': rid}, {'_id': 0})

    def left(self, ci, co):
        av = run('hotel_check_availability', {'checkin_date': ci, 'checkout_date': co, 'room_type': 'Standard'})
        return av['room_types'][0]['rooms_left']

    def other(self, n, **kw):
        c = ctx(token=f'tok-{n}', cid=f'{BID}:04999999{n:02d}')
        return self.book(c=c, guest_name=f'Guest Number{n}', phone=f'04999999{n:02d}', **kw)

    def test_checkin_stores_expected_date_and_ai_blocks_those_nights(self):
        out, code = self.call('api_hotel_room_checkin', 1, {'guest_name': 'Walk In', 'expected_checkout_date': D(3)})
        self.assertEqual(code, 200, out)
        self.assertEqual((self.room(1)['status'], self.room(1)['expected_checkout_date']), ('Đang ở', D(3)))
        self.assertEqual(out['data']['expected_checkout_date'], D(3))
        for ci, co in ((D(0), D(1)), (D(1), D(2)), (D(2), D(3))):
            self.assertEqual(self.left(ci, co), 1, ci)
        a = self.book(checkin_date=D(1), checkout_date=D(2))
        self.assertEqual((find(a['booking_id'])['room_id'], a['status']), (2, 'confirmed'))
        b = self.other(1, checkin_date=D(1), checkout_date=D(2))       # phòng 101 khách vãng lai còn ở tới D3
        self.assertFalse(b['success'])
        self.assertEqual(b['reason'], 'sold_out')
        self.assertNoDoubleBooking()
        # từ ngày khách báo trả phòng, phòng 101 bán lại được và tự xác nhận như phòng trống
        self.assertEqual(self.left(D(3), D(4)), 2)
        r = self.other(2, checkin_date=D(3), checkout_date=D(4))
        self.assertEqual((find(r['booking_id'])['room_id'], r['status']), (1, 'confirmed'))
        self.assertNotIn('walk-in', OWNER_ALERTS_TEXT())

    def test_checkin_without_date_never_auto_confirms_later_nights(self):
        out, code = self.call('api_hotel_room_checkin', 1, {'guest_name': 'Walk In', 'guest_phone': '0400 111 222'})
        self.assertEqual(code, 200, out)
        self.assertIsNone(self.room(1)['expected_checkout_date'])
        self.assertEqual(rh.open_walkins(BID, rh.list_rooms(BID), TODAY), {1})
        a = self.book(c=ctx('whatsapp'), checkin_date=D(1), checkout_date=D(2))   # đã xác minh: không tính vào trần chat web
        self.assertEqual((find(a['booking_id'])['room_id'], a['status']), (2, 'confirmed'))
        b = self.other(1, checkin_date=D(1), checkout_date=D(2))
        doc = find(b['booking_id'])
        self.assertEqual((doc['room_id'], doc['status'], b['status']), (1, 'pending', 'pending'))
        self.assertIn('Do NOT say it is confirmed', b['say'])
        alerts = OWNER_ALERTS_TEXT()
        self.assertIn('walk-in', alerts)
        self.assertIn('expected check-out date on the Room Management page', alerts)   # nhân viên biết sửa ở đâu
        self.assertNotIn('Walk In', str(b))                        # không lộ khách khác cho người đang chat
        self.assertNotIn('0400 111 222', str(b))

    def test_bad_expected_dates_are_refused_and_room_stays_free(self):
        for bad, msg in ((D(0), 'after today'), (D(-2), 'after today'), ('soon', 'valid date'),
                         ('2026-02-30', 'valid date'), (D(400), 'within one year'), (20261105, 'valid date')):
            out, code = self.call('api_hotel_room_checkin', 1, {'guest_name': 'Walk In', 'expected_checkout_date': bad})
            self.assertEqual(code, 400, bad)
            self.assertIn(msg, out['message'])
            self.assertEqual(self.room(1)['status'], 'Trống')
            self.assertNotIn('expected_checkout_date', self.room(1))
        self.ns['_vi_en'] = lambda vi, en: vi
        out, code = self.call('api_hotel_room_checkin', 1, {'guest_name': 'Walk In', 'expected_checkout_date': D(0)})
        self.assertEqual(code, 400)
        self.assertIn('phải sau hôm nay', out['message'])
        for empty in ('', None, '   '):
            self.assertIsNone(rh.walkin_checkout_date(empty, TODAY))

    def test_checkout_and_clean_clear_the_date(self):
        self.call('api_hotel_room_checkin', 1, {'guest_name': 'Walk In', 'expected_checkout_date': D(3)})
        real_next = self.ns['next_mongo_id']
        self.ns['next_mongo_id'] = lambda coll: (_ for _ in ()).throw(RuntimeError('db down'))
        out, code = self.call('api_hotel_room_checkout', 1, {'payment_method': 'cash'})
        self.assertEqual(code, 500)                                # chưa ghi được hoá đơn -> trả lại phòng nguyên trạng
        self.assertEqual((self.room(1)['status'], self.room(1)['expected_checkout_date']), ('Đang ở', D(3)))
        self.ns['next_mongo_id'] = real_next
        out, code = self.call('api_hotel_room_checkout', 1, {'payment_method': 'cash'})
        self.assertEqual(code, 200, out)
        self.assertEqual((self.room(1)['status'], self.room(1)['expected_checkout_date']), ('Đang dọn', None))
        DB.hotel_rooms.update_one({'id': 1}, {'$set': {'expected_checkout_date': D(5)}})   # dữ liệu cũ còn sót
        self.assertEqual(self.call('api_hotel_room_mark_clean', 1), ({'success': True}, 200))
        self.assertEqual((self.room(1)['status'], self.room(1)['expected_checkout_date']), ('Trống', None))
        # khách vãng lai kế tiếp không ghi ngày: không thừa hưởng ngày của khách trước -> lại là "chưa rõ ngày đi"
        self.call('api_hotel_room_checkin', 1, {'guest_name': 'Next Walk In'})
        self.assertIsNone(self.room(1)['expected_checkout_date'])
        self.assertEqual(rh.open_walkins(BID, rh.list_rooms(BID), TODAY), {1})

    def test_staff_can_extend_or_clear_the_date(self):
        self.call('api_hotel_room_checkin', 1, {'guest_name': 'Walk In', 'expected_checkout_date': D(2)})
        self.assertEqual(self.left(D(2), D(3)), 2)                 # theo ngày cũ: đêm D2 phòng 101 đã trống
        out, code = self.call('api_hotel_room_expected_checkout', 1, {'expected_checkout_date': D(4)})   # khách ở thêm
        self.assertEqual((code, self.room(1)['expected_checkout_date']), (200, D(4)))
        self.assertEqual((self.left(D(2), D(3)), self.left(D(3), D(4)), self.left(D(4), D(5))), (1, 1, 2))
        out, code = self.call('api_hotel_room_expected_checkout', 1, {'expected_checkout_date': None})   # chưa rõ ngày đi
        self.assertEqual(code, 200, out)
        self.assertIsNone(self.room(1)['expected_checkout_date'])
        self.assertEqual(rh.open_walkins(BID, rh.list_rooms(BID), TODAY), {1})
        out, code = self.call('api_hotel_room_expected_checkout', 1, {'expected_checkout_date': D(0)})
        self.assertEqual(code, 400)
        self.assertIsNone(self.room(1)['expected_checkout_date'])
        out, code = self.call('api_hotel_room_expected_checkout', 2, {'expected_checkout_date': D(3)})  # phòng trống
        self.assertEqual(code, 409)
        self.assertNotIn('expected_checkout_date', self.room(2))
        DB.hotel_rooms.insert_one(dict(hp.room(9, '901', 'Standard', 90), business_id='other-hotel', status='Đang ở'))
        out, code = self.call('api_hotel_room_expected_checkout', 9, {'expected_checkout_date': D(3)})  # khách sạn khác
        self.assertEqual(code, 409)
        self.assertNotIn('expected_checkout_date', DB.hotel_rooms.find_one({'id': 9}))

    def test_guest_leaving_today_frees_tonight(self):
        DB.hotel_rooms.update_one({'id': 1}, {'$set': {'status': 'Đang ở', 'guest_name': 'Walk In',
                                                       'expected_checkout_date': D(-1)}})
        # khách ở quá ngày đã báo = lại chưa rõ ngày đi: bận đêm nay, không tự xác nhận các đêm sau
        self.assertEqual(rh.open_walkins(BID, rh.list_rooms(BID), TODAY), {1})
        self.assertEqual(self.left(D(0), D(1)), 1)
        DB.hotel_rooms.update_one({'id': 1}, {'$set': {'expected_checkout_date': D(0)}})
        DB.hotel_reservations.insert_one(resv(70, D(0), D(1), room_id=2))   # 102 đã có khách đêm nay
        self.assertEqual(self.left(D(0), D(1)), 1)                 # như đặt phòng trả phòng hôm nay: trưa nay khách đi
        self.assertEqual(rh.open_walkins(BID, rh.list_rooms(BID), TODAY), set())
        r = self.book(checkin_date=D(0), checkout_date=D(1))
        self.assertEqual((find(r['booking_id'])['room_id'], r['status']), (1, 'confirmed'))
        self.assertNotIn('walk-in', OWNER_ALERTS_TEXT())

    def test_rooms_page_gets_the_hotel_local_today(self):
        out = self.ns['hotel_rooms_page']()
        self.assertEqual(out, ('html', 'hotel_rooms.html', {'hotel_today': TODAY.isoformat()}))


# ================================================================ trang nhân viên (template thật)
class TestStaffPagesTemplates(unittest.TestCase):
    def test_rooms_page_has_the_expected_checkout_field_and_edit(self):
        for lang, label in (('en', 'Expected check-out date (optional)'), ('vi', 'Ngày trả phòng dự kiến (không bắt buộc)')):
            html = render('hotel_rooms.html', lang=lang, tenant_currency='USD', hotel_today='2026-11-02')
            self.assertIn('<input type="date" id="expectedCheckout" class="field-input">', html)
            self.assertIn("expected_checkout_date: document.getElementById('expectedCheckout').value || null", html)
            self.assertIn('exp.min = addDaysIso(isoToday(), 1);', html)
            self.assertIn('const HOTEL_TODAY = "2026-11-02";', html)
            self.assertIn('`/api/hotel/rooms/${activeRoomId}/expected_checkout`', html)
            self.assertIn('openExpectedModal(${r.id})', html)
            self.assertIn(label, html)
            self.assertIn("won't auto-confirm this room for later nights", html)
            self.assertIn('không tự xác nhận phòng này cho các đêm sau', html)

    def test_reservations_page_sends_what_the_row_shows(self):
        rows = [{'id': 1, 'checkin_date': '2026-11-10', 'checkout_date': '2026-11-12', 'guest_name': 'Mia', 'party_size': 2,
                 'status': 'pending', 'source': 'ai_bot', 'room_id': 3},
                {'id': 2, 'checkin_date': '2026-11-10', 'checkout_date': '2026-11-11', 'guest_name': 'Leo', 'party_size': None,
                 'status': 'confirmed', 'room_id': None}]
        html = render('hotel_reservations.html', reservations=rows, rooms=[{'id': 3, 'room_number': '201', 'room_type': 'Deluxe'}],
                      today='2026-11-02', reservation_link='x')
        cells = re.findall(r'<td class="px-6 py-4" data-room-cell([^>]*)>', html)
        self.assertEqual([dict(re.findall(r'data-(\w+)="([^"]*)"', c)) for c in cells], [
            {'status': 'pending', 'checkin': '2026-11-10', 'checkout': '2026-11-12', 'party': '2', 'room': '3'},
            {'status': 'confirmed', 'checkin': '2026-11-10', 'checkout': '2026-11-11', 'party': '', 'room': ''}])
        js = ''.join(re.findall(r'<script>(.*?)</script>', html, re.S))
        for key, attr in SHOWN_KEYS:
            self.assertIn(f'{key}: cell.dataset.{attr}', js)
        self.assertIn('JSON.stringify({ status, ...shownState(row) })', js)
        self.assertIn('JSON.stringify({ room_id: roomId, ...shownState(row) })', js)
        self.assertIn("row.querySelector('[data-room-cell]').dataset.status = status;", js)
        self.assertIn("row.querySelector('[data-room-cell]').dataset.room = select.value;", js)
        # dòng vẫn đúng khuôn mà các test khác (chip AI, vạch chờ duyệt) dựa vào
        self.assertEqual(len(re.findall(r'<tr class="[^"]*" data-res-id="\d+">', html)), 2)


# ================================================================ #18 "Duyệt" / xếp phòng trên trang cũ
class TestStaleStaffPage(hp.Base):
    def setUp(self):
        super().setUp()
        self.ns, self.req = _staff_route()

    def patch(self, rid, body):
        self.req.json = body
        out = self.ns['api_hotel_reservation_update'](rid)
        return (out, 200) if isinstance(out, dict) else out

    def test_approve_after_guest_moved_pending_dates_is_409(self):
        b = self.book()                                            # pending D8..D10, phòng 101
        seen = page_state(b['booking_id'])                         # nhân viên mở trang
        self.assertTrue(change(b['booking_id'], D(20), D(22))['changed'])   # khách dời ngày trong chat — vẫn 'pending'
        out, code = self.patch(b['booking_id'], dict(seen, status='confirmed'))
        self.assertEqual(code, 409)
        self.assertIn('changed elsewhere', out['message'])
        doc = find(b['booking_id'])
        self.assertEqual((doc['status'], doc['checkin_date']), ('pending', D(20)))
        # tải lại trang (thấy ngày mới) rồi duyệt -> được
        self.assertEqual(self.patch(b['booking_id'], dict(page_state(b['booking_id']), status='confirmed')),
                         ({'success': True}, 200))
        self.assertEqual(find(b['booking_id'])['status'], 'confirmed')

    def test_approve_after_guest_changed_guest_count_is_409(self):
        b = self.book()                                            # 2 khách
        seen = page_state(b['booking_id'])
        self.assertTrue(change(b['booking_id'], D(8), D(10), guests=1)['changed'])
        out, code = self.patch(b['booking_id'], dict(seen, status='confirmed'))
        self.assertEqual(code, 409)
        self.assertEqual(find(b['booking_id'])['status'], 'pending')

    def test_assign_from_stale_page_is_409_and_holds_nothing(self):
        b = self.book()                                            # phòng 101, D8..D10
        seen = page_state(b['booking_id'])
        self.assertTrue(change(b['booking_id'], D(20), D(22))['changed'])
        out, code = self.patch(b['booking_id'], dict(seen, room_id=2))
        self.assertEqual(code, 409)
        doc = find(b['booking_id'])
        self.assertEqual((doc['room_id'], doc['checkin_date']), (1, D(20)))
        self.assertEqual(claims_of(b['booking_id']), [(1, D(20)), (1, D(21))])
        self.assertNoDoubleBooking()

    def test_fresh_page_is_never_a_false_409(self):
        DB.hotel_reservations.insert_one(resv(85, D(5), D(6), room_type='Deluxe', status='pending', party_size=None))
        self.assertEqual(page_state(85)['from_party_size'], '')
        self.assertEqual(page_state(85)['from_room_id'], '')
        self.assertEqual(self.patch(85, dict(page_state(85), room_id=3)), ({'success': True}, 200))
        self.assertEqual(page_state(85)['from_room_id'], '3')      # JS: dataset.room = select.value sau khi xếp
        self.assertEqual(self.patch(85, dict(page_state(85), status='confirmed')), ({'success': True}, 200))
        self.assertEqual((find(85)['status'], find(85)['room_id']), ('confirmed', 3))
        self.assertEqual(self.patch(85, dict(page_state(85), status='cancelled')), ({'success': True}, 200))
        self.assertEqual(DB.hotel_room_nights.count_documents({'reservation_id': 85}), 0)


# ================================================================ #17 xác nhận đổi ngày phải kèm quoted_total
class TestConfirmNeedsQuotedTotal(hp.Base):
    def args(self, bid, **kw):
        a = {'booking_id': bid, 'new_checkin_date': D(20), 'new_checkout_date': D(22)}
        a.update(kw)
        return a

    def test_price_change_between_quote_and_confirm_is_never_saved_silently(self):
        b = self.book()                                            # phòng 101 $100, D8..D10 = $200
        q = run('hotel_change_dates', self.args(b['booking_id'], customer_confirmed=False))
        self.assertEqual(q['new_total'], '$200.00')
        DB.hotel_rooms.update_many({'room_type': 'Standard'}, {'$set': {'price_per_night': 130}})   # chủ đổi giá giữa chừng
        r = run('hotel_change_dates', self.args(b['booking_id'], customer_confirmed=True))         # AI bỏ quên quoted_total
        self.assertFalse(r['success'])
        self.assertTrue(r['quoted_total_missing'])
        self.assertTrue(r['needs_confirmation'])
        self.assertEqual(r['new_total'], '$260.00')
        self.assertIn('NOT changed', r['ask_customer'])
        self.assertIn('quoted_total=$260.00', r['ask_customer'])
        doc = find(b['booking_id'])
        self.assertEqual((doc['checkin_date'], doc['quoted_total']), (D(8), 200.0))
        self.assertEqual(claims_of(b['booking_id']), [(1, D(8)), (1, D(9))])
        r = run('hotel_change_dates', self.args(b['booking_id'], customer_confirmed=True, quoted_total=q['new_total']))
        self.assertTrue(r['price_changed'])                        # giá khách nghe lúc trước không còn đúng
        self.assertEqual(find(b['booking_id'])['checkin_date'], D(8))
        r = run('hotel_change_dates', self.args(b['booking_id'], customer_confirmed=True, quoted_total='$260.00'))
        self.assertTrue(r['changed'])
        self.assertEqual((r['total'], find(b['booking_id'])['quoted_total']), ('$260.00', 260.0))

    def test_missing_quote_is_refused_even_when_the_price_did_not_move(self):
        b = self.book()
        r = run('hotel_change_dates', self.args(b['booking_id'], customer_confirmed=True), ctx(lang='vi'))
        self.assertTrue(r['quoted_total_missing'])
        self.assertIn('CHƯA được đổi', r['ask_customer'])
        self.assertEqual(find(b['booking_id'])['checkin_date'], D(8))
        self.assertEqual(hp.OWNER_ALERTS[-1][3], f"hotel_new_{b['booking_id']}")   # không báo nhân viên 1 lần đổi chưa xảy ra

    def test_unpublished_rate_has_nothing_to_quote(self):
        DB.hotel_rooms.update_many({'room_type': 'Standard'}, {'$set': {'price_per_night': 0}})
        b = self.book()
        r = run('hotel_change_dates', self.args(b['booking_id'], customer_confirmed=True))
        self.assertTrue(r['changed'])
        self.assertEqual((find(b['booking_id'])['checkin_date'], r['status']), (D(20), 'pending'))

    def test_tool_schema_says_quoted_total_is_required_to_confirm(self):
        tool = next(t for t in hotel.TOOLS if t['function']['name'] == 'hotel_change_dates')
        self.assertIn('REQUIRED with customer_confirmed=true', tool['function']['parameters']['properties']['quoted_total']['description'])
        self.assertIn('quoted_total = that total', hotel.PROMPT_RULES['en'])
        self.assertIn('quoted_total = đúng tổng tiền đó', hotel.PROMPT_RULES['vi'])

    def test_same_total_never_matches_amounts_100x_apart(self):
        for wrong, total, cur in (('450000', 4500.0, 'USD'), ('4500', 45.0, 'USD'), ('$45.00', 4500.0, 'USD'),
                                  ('45000', 450.0, 'AUD'), ('4.500', 45.0, 'USD'), ('', 300.0, 'AUD')):
            self.assertFalse(hotel._same_total(wrong, total, cur), (wrong, total))
        for ok, total, cur in (('$4,500.00', 4500.0, 'USD'), ('4500', 4500.0, 'USD'), ('4,500', 4500.0, 'AUD'),
                               ('450.000đ', 450000.0, 'VND'), ('450.000', 450000.0, 'VND'), ('450,000', 450000.0, 'VND'),
                               ('1.200.000 ₫', 1200000.0, 'VND'), ('1.200,50', 1200.5, 'AUD'), ('300.00 AUD', 300.0, 'AUD'),
                               (300, 300.0, 'AUD'), ('$300', 300.0, 'AUD')):
            self.assertTrue(hotel._same_total(ok, total, cur), (ok, total))


# ================================================================ lời "sự thật" của sim + giờ mở cửa qua nửa đêm
class TestTruthTexts(hp.Base):
    def test_sim_cancellation_truth_matches_the_enforced_rules(self):
        sys.path.insert(0, os.path.join(hp.ROOT, 'scripts', 'ai_sim'))
        import scenarios_hotel as sh
        shop = {'currency': 'AUD', 'info': {}}
        data = {'types': {}, 'auto_confirm': False, 'checkin_time': None, 'checkout_time': None,
                'free_cancel_hours': None, 'min_nights': 1}
        f = sh.facts(shop, data)
        self.assertNotIn('anytime', f)
        self.assertIn('pending requests can be cancelled until the day before check-in', f)
        self.assertIn('confirmed bookings free until the day before check-in', f)
        self.assertIn('24 hours before 00:00 (the start) of the check-in day', sh.facts(shop, dict(data, free_cancel_hours=24)))
        self.assertIn('24 hours before check-in (14:00)',
                      sh.facts(shop, dict(data, free_cancel_hours=24, checkin_time='14:00')))

    def test_overnight_hours_say_which_day_they_close(self):
        hp.booking_rules.save_rules(BID, {'hours': {'fri': ['18:00', '02:00'], 'sat': ['09:00', '17:00'],
                                                    'sun': ['20:00', '01:00'], 'mon': ['08:00', '00:00']}},
                                    allow_overnight=True)
        hp.booking_rules._CACHE.clear()
        en, vi = hotel.facts(BID, 'en', NOW), hotel.facts(BID, 'vi', NOW)
        self.assertIn('Fri 18:00-02:00 (closes at 02:00 Sat, after midnight)', en)
        self.assertIn('Sun 20:00-01:00 (closes at 01:00 Mon, after midnight)', en)
        self.assertIn('Sat 09:00-17:00,', en)
        self.assertIn('Mon 08:00-24:00,', en)                      # đóng lúc nửa đêm không phải "qua đêm"
        self.assertIn('T6 18:00-02:00 (đóng lúc 02:00 sáng T7, qua nửa đêm)', vi)


if __name__ == '__main__':
    unittest.main(verbosity=2)
