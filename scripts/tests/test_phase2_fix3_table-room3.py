# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 review vòng 3, khu "table-room3" (bàn F&B / phòng karaoke):

  1) karaoke_reserve_room: chat KHÔNG chứng minh được là chủ (web chưa có mã trình duyệt) đã giữ phòng A 20:00-22:00 rồi hỏi
     "phòng B lúc 21:00" — trước đây chỉ dò đặt phòng cùng SĐT ĐÚNG giờ bắt đầu nên giữ thêm phòng B, phòng A vẫn bị khoá dưới
     SĐT khách mà ghi chú cho quán không hề nhắc. Nay dò theo CHỒNG GIỜ: không tạo gì thêm, chuyển quán, không lộ gì.
  2) trang công khai /karaoke/reserve/<id>: route truyền room_kinds (loại chỗ THẬT của quán) để form hỏi phòng hát / bàn bida
     khi quán có cả 2 (trước: template có ô chọn nhưng route không truyền gì -> không bao giờ hiện).
  3) ô opening_hours của công cụ kiểm chỗ: Chủ nhật nghỉ sau ca đêm thứ Bảy không còn bị nói 'closed' (đã sửa ở vòng 2) — nay
     theo kiểu giờ chung.
  4) giả lập --mock: tiệm mẫu F&B / karaoke cố ý chỉ nhận yêu cầu (auto_confirm=True của trang cũ, không có dấu đã lưu công tắc
     chung) — sự thật của giả lập == AI == MOCK_STATUS 'pending'.
  5) MỌI chữ giờ mở cửa khách / AI đọc dùng 1 kiểu từ 1 helper (reservations_core): dữ kiện gói, ô opening_hours + lời giải
     thích của công cụ, customer_context (OPENING HOURS + RIGHT NOW), booking_rules.describe_for_ai.
     EN 'Fri 6:00 pm – 2:00 am (Sat)' / VI 'T6 18:00 – 02:00 (sáng T7)' theo ngôn ngữ chat.

Dùng lại DB giả + stub của test_phase2_table_room_packs.py (mongo_client / requests / messaging thay TRƯỚC mọi import).
KHÔNG import app.py (hàm route tách bằng ast), KHÔNG mở MongoDB thật, KHÔNG gọi mạng / API trả phí.

Chạy: python scripts/tests/test_phase2_fix3_table-room3.py
"""
import json
import os
import sys
import types
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_table_room_packs as T  # noqa: E402  (DB giả + stub TRƯỚC mọi import của module thật)

for _p in (os.path.join(T.ROOT, 'scripts', 'ai_sim'),):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import customer_context  # noqa: E402

rc, fnb, karaoke, DB, BID, FRI = T.rc, T.fnb, T.karaoke, T.DB, T.BID, T.FRI
booking_rules = T.booking_rules
SAT, SUN, MON = '2026-10-31', '2026-11-01', '2026-11-02'

LATE = {'mon': ['11:00', '22:00'], 'tue': None, 'wed': ['16:00', '24:00'], 'thu': ['00:00', '24:00'],
        'fri': ['18:00', '02:00'], 'sat': ['18:00', '02:00'], 'sun': ['17:30', '01:30']}
WEEK_EN = ('Mon 11:00 am – 10:00 pm, Tue closed, Wed 4:00 pm – midnight, Thu 12:00 am – midnight, '
           'Fri 6:00 pm – 2:00 am (Sat), Sat 6:00 pm – 2:00 am (Sun), Sun 5:30 pm – 1:30 am (Mon)')
WEEK_VI = ('T2 11:00 – 22:00, T3 nghỉ, T4 16:00 – 24:00, T5 00:00 – 24:00, '
           'T6 18:00 – 02:00 (sáng T7), T7 18:00 – 02:00 (sáng CN), CN 17:30 – 01:30 (sáng T2)')
SAT_EN = 'Fri 6:00 pm – 2:00 am (Sat), Sat 6:00 pm – 2:00 am (Sun)'      # 1 NGÀY LỊCH thứ Bảy: ca đêm thứ Sáu + ca thứ Bảy
SAT_VI = 'T6 18:00 – 02:00 (sáng T7), T7 18:00 – 02:00 (sáng CN)'
OLD_STYLES = ('18:00-02:00', '11:00-22:00', 'after midnight)', 'the next day)', 'still open from', '(closes at')


def vi_ctx(**kw):
    return T.web_ctx(lang='vi', **kw)


def with_now(now, fn):
    orig = booking_rules.local_now
    booking_rules.local_now = lambda bid: now
    try:
        return fn()
    finally:
        booking_rules.local_now = orig


# ================================================================ (1) karaoke: SĐT trùng, chồng giờ, chat không chứng minh là chủ
class UnverifiedChatOverlappingStart(T.Base):
    def setUp(self):
        super().setUp()
        T.biz('karaoke')
        T.settings(hours=T.KTV_HOURS, auto_confirm=True)
        T.room(1, 'Room A (2-10 people)', 20)
        T.room(2, 'Room B (2-10 people)', 20)
        T.room(3, 'Pool Table 1', 6)

    def reserve(self, ctx=None, **kw):
        args = {'date': FRI, 'time': '20:00', 'hours': 2, 'group_size': 6, 'customer_name': 'Kai', 'phone': '0412345678'}
        args.update(kw)
        return self.call(karaoke, 'karaoke_reserve_room', args, ctx)

    def active(self):
        return [d for d in DB.karaoke_room_reservations.docs if d['status'] in rc.KARAOKE_ACTIVE]

    def test_room_b_at_an_overlapping_start_is_passed_to_the_team_not_a_second_hold(self):
        anon = T.web_ctx(token=None)                                        # chat web chưa có mã trình duyệt
        a = self.reserve(ctx=anon, room_id=1)
        self.assertTrue(a['success'])
        r = self.reserve(ctx=dict(anon), room_id=2, time='21:00')           # "cho mình phòng B lúc 21:00 nhé"
        self.assertEqual((r.get('request_sent_to_team'), r.get('status'), r.get('confirmed')), (True, 'pending', False), r)
        self.assertEqual([(d['id'], d['room_id']) for d in self.active()], [(a['reservation_id'], 1)])   # không giữ thêm B
        dumped = json.dumps(r)
        for leak in (str(a['reservation_id']), '20:00', '22:00', 'Room A', 'existing_bookings', 'reservation_id'):
            self.assertNotIn(leak, dumped)                                  # không lộ gì về đặt phòng kia
        note = DB.bot_messages.docs[-1]['content']                          # quán biết rõ để gọi khách
        self.assertIn('#%d' % a['reservation_id'], note)
        self.assertIn('2026-10-30 21:00', note)                             # giờ khách vừa hỏi
        self.assertIn('2026-10-30 20:00', note)                             # ... và giờ của đặt phòng đang giữ
        self.assertIn('overlapping', note)

    def test_overlap_from_the_evening_before_counts_too(self):
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'hours': {d: ['18:00', '02:00'] for d in rc.DAY_KEYS}}})
        anon = T.web_ctx(token=None)
        a = self.reserve(ctx=anon, room_id=1, time='23:00', hours=2)        # thứ Sáu 23:00 -> 01:00 thứ Bảy
        self.assertTrue(a['success'], a)
        r = self.reserve(ctx=dict(anon), room_id=2, date=SAT, time='00:30', hours=1)
        self.assertTrue(r.get('request_sent_to_team'), r)
        self.assertEqual(len(self.active()), 1)

    def test_back_to_back_or_explicit_extra_room_still_books(self):
        anon = T.web_ctx(token=None)
        self.assertTrue(self.reserve(ctx=anon, room_id=1)['success'])
        self.assertTrue(self.reserve(ctx=dict(anon), room_id=2, time='22:00')['success'])     # nối tiếp, không chồng giờ
        self.assertTrue(self.reserve(ctx=dict(anon), room_id=2, time='18:00')['success'])     # trước đó, 18:00-20:00
        extra = self.reserve(ctx=dict(anon), room_id=3, time='21:00', group_size=2, extra_room=True)
        self.assertEqual((extra['success'], extra['room_id']), (True, 3))  # khách nói rõ: THÊM 1 chỗ nữa
        self.assertEqual(len(self.active()), 4)

    def test_other_phone_at_an_overlapping_time_is_not_blocked(self):
        self.assertTrue(self.reserve(ctx=T.web_ctx(token=None), room_id=1)['success'])
        leo = self.reserve(ctx=T.web_ctx(token=None, customer_id=f'{BID}:0499888777'), room_id=2, time='21:00',
                           phone='0499888777', customer_name='Leo')
        self.assertEqual((leo['success'], leo['room_id']), (True, 2))

    def test_verified_owner_still_gets_the_switch_hint_not_a_team_request(self):
        own = T.web_ctx(token=None, phone='0412345678')                     # SĐT đã xác minh = chủ đặt phòng
        a = self.reserve(ctx=own, room_id=1)
        r = self.reserve(ctx=dict(own), room_id=2, time='21:00')
        self.assertEqual(r['reason'], 'chat_already_holds_a_room')
        self.assertEqual(r['existing_bookings'][0]['reservation_id'], a['reservation_id'])


# ================================================================ (2) trang công khai karaoke: ô chọn phòng hát / bàn bida
class PublicKaraokePageGetsRoomKinds(T.Base):
    def route(self, kind='karaoke'):
        seen = {}

        def render_template(tpl, **kw):
            seen.update(kw, _template=tpl)
            return 'html'
        ns = {'_public_shop_context': lambda bid: {'shop_name': 'Test Venue', 'shop_phone': '', 'shop_address': '',
                                                   'shop_logo_url': ''},
              'render_template': render_template, 'render_message_page': lambda *a, **k: 'not found'}
        exec(compile(T._app_function('_render_public_reservation'), 'app.py', 'exec'), ns)
        self.assertEqual(ns['_render_public_reservation'](kind, BID), 'html')
        return seen

    def html(self, seen, lang='en'):
        import jinja2
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(T.ROOT, 'templates')), autoescape=True)
        kw = {k: v for k, v in seen.items() if k != '_template'}
        return env.get_template(seen['_template']).render(default_lang=lang, **kw)

    def test_venue_with_both_kinds_shows_the_choice(self):
        T.biz('karaoke')
        T.room(1, 'Room A (2-10 people)', 20)
        T.room(2, 'Pool Table 1', 6)
        T.room(3, 'Bàn bida 2', 6)
        seen = self.route()
        self.assertEqual(seen['room_kinds'], ['billiards', 'karaoke'])
        page = self.html(seen)
        self.assertIn('name="room_kind"', page)
        self.assertIn('Billiards / pool table', page)
        self.assertIn('Bàn bida', self.html(seen, 'vi'))

    def test_one_kind_or_no_rooms_or_other_pages_show_no_choice(self):
        T.biz('karaoke')
        self.assertEqual(self.route()['room_kinds'], [])
        T.room(1, 'Room A (2-10 people)', 20)
        seen = self.route()
        self.assertEqual(seen['room_kinds'], ['karaoke'])
        self.assertNotIn('name="room_kind"', self.html(seen))
        T.room(2, 'Pool Table 1', 6)
        for kind in ('table', 'hotel'):                                     # trang khác không hỏi loại phòng
            seen = self.route(kind)
            self.assertFalse(seen.get('room_kinds'))
            self.assertNotIn('name="room_kind"', self.html(seen))

    def test_room_lookup_error_still_renders_the_page(self):
        T.biz('karaoke')
        orig = rc.karaoke_rooms
        rc.karaoke_rooms = lambda bid: (_ for _ in ()).throw(RuntimeError('db down'))
        try:
            seen = self.route()
        finally:
            rc.karaoke_rooms = orig
        self.assertEqual(seen['room_kinds'], [])
        self.assertIn('id="reserveForm"', self.html(seen))


# ================================================================ (5) 1 kiểu giờ mở cửa cho mọi chữ khách / AI đọc
class OneHoursStyleHelper(unittest.TestCase):
    def test_week_text_en_and_vi(self):
        self.assertEqual(rc.week_hours_text(LATE), WEEK_EN)
        self.assertEqual(rc.week_hours_text(LATE, 'vi'), WEEK_VI)
        self.assertEqual(rc.week_hours_text(booking_rules.DEFAULT_HOURS),
                         'Mon 9:00 am – 7:00 pm, Tue 9:00 am – 7:00 pm, Wed 9:00 am – 7:00 pm, Thu 9:00 am – 8:00 pm, '
                         'Fri 9:00 am – 8:00 pm, Sat 9:00 am – 6:00 pm, Sun 10:00 am – 5:00 pm')
        self.assertEqual(rc.week_hours_text({'mon': ['12:00', '00:00']}), 'Mon 12:00 pm – midnight, ' + ', '.join(
            f'{rc.DAY_NAMES[d]} closed' for d in rc.DAY_KEYS[1:]))        # đóng 00:00 (bản ghi cũ) = nửa đêm, như hours_on
        self.assertTrue(rc.week_hours_text({'mon': ['late', '02:00']}).startswith('Mon late-02:00, Tue closed'))

    def test_hours_text_keeps_the_next_date_note(self):
        t = rc.hours_text({'hours': LATE})
        self.assertTrue(t.startswith(WEEK_EN + '; a time after midnight is on the NEXT date'), t)
        self.assertEqual(rc.hours_text({'hours': T.KTV_HOURS}), ', '.join(f'{rc.DAY_NAMES[d]} 2:00 pm – midnight'
                                                                          for d in rc.DAY_KEYS))
        self.assertTrue(rc.hours_text({'hours': LATE}, 'vi').startswith(WEEK_VI + '; a time after midnight'))
        self.assertIsNone(rc.hours_text({'hours': None}))

    def test_day_text_and_closing_labels(self):
        r = {'hours': dict(LATE, sun=None)}
        self.assertEqual(rc.day_hours_text(r, datetime(2026, 10, 31).date()), SAT_EN)
        self.assertEqual(rc.day_hours_text(r, datetime(2026, 10, 31).date(), 'vi'), SAT_VI)
        self.assertEqual(rc.day_hours_text(r, datetime(2026, 11, 1).date()), 'Sat 6:00 pm – 2:00 am (Sun), Sun closed')
        self.assertEqual(rc.day_hours_text(r, datetime(2026, 11, 1).date(), 'vi'), 'T7 18:00 – 02:00 (sáng CN), CN nghỉ')
        self.assertEqual(rc.day_hours_text(r, datetime(2026, 11, 3).date()), 'Tue closed')
        self.assertIsNone(rc.day_hours_text({'hours': None}, datetime(2026, 11, 3).date()))
        self.assertEqual((rc.close_label(1320, 'mon'), rc.close_label(1440, 'wed'), rc.close_label(1560, 'sun')),
                         ('10:00 pm', 'midnight', '2:00 am (Mon)'))
        self.assertEqual((rc.close_label(1320, 'mon', 'vi'), rc.close_label(1440, 'wed', 'vi'), rc.close_label(1560, 'sun', 'vi')),
                         ('22:00', '24:00', '02:00 (sáng T2)'))


class KaraokeAndFnbUseTheOneStyle(T.Base):
    def setUp(self):
        super().setUp()

    def ktv(self):
        T.biz('karaoke')
        T.settings(hours=LATE, auto_confirm=True)
        T.room(1, 'Room A (2-10 people)', 20)

    def opening_line(self, text):
        return next(l for l in text.splitlines() if l.startswith('OPENING HOURS: '))

    def test_every_karaoke_text_says_the_same_hours_the_same_way(self):
        self.ktv()
        facts = self.opening_line(karaoke.facts(BID, 'en', T.NOW))
        cc = customer_context.hours_lines(BID, booking_rules.get_rules(BID))[0]
        desc = booking_rules.describe_for_ai(BID).splitlines()[0]
        self.assertTrue(facts.startswith(f'OPENING HOURS: {WEEK_EN};'), facts)
        self.assertEqual(cc, f'OPENING HOURS: {WEEK_EN}.')
        self.assertEqual(desc, f'OPENING HOURS: {WEEK_EN}.')
        chk = self.call(karaoke, 'karaoke_check_rooms', {'date': SAT, 'time': '03:00', 'hours': 1, 'group_size': 4})
        self.assertEqual(chk['opening_hours'], SAT_EN)
        self.assertIn(f'Opening hours that day: {SAT_EN}.', chk['requested_time']['why'])
        for text in (facts, cc, desc, json.dumps(chk, ensure_ascii=False)):
            for old in OLD_STYLES:
                self.assertNotIn(old, text)

    def test_vietnamese_chat_gets_the_vietnamese_style_everywhere(self):
        self.ktv()
        self.assertTrue(self.opening_line(karaoke.facts(BID, 'vi', T.NOW)).startswith(f'OPENING HOURS: {WEEK_VI};'))
        self.assertEqual(customer_context.hours_lines(BID, booking_rules.get_rules(BID), lang='vi')[0],
                         f'OPENING HOURS: {WEEK_VI}.')
        chk = self.call(karaoke, 'karaoke_check_rooms', {'date': SAT, 'time': '03:00', 'hours': 1, 'group_size': 4}, vi_ctx())
        self.assertEqual(chk['opening_hours'], SAT_VI)
        self.assertIn(SAT_VI, chk['requested_time']['why'])
        late = self.call(karaoke, 'karaoke_reserve_room', {'date': FRI, 'time': '23:30', 'hours': 3, 'group_size': 4,
                                                           'customer_name': 'Kai', 'phone': '0412345678'}, vi_ctx())
        self.assertIn('It closes at 02:00 (sáng T7); the latest start that fits is 23:00.', late['message'])

    def test_customer_context_facts_pass_the_chat_language(self):
        self.ktv()
        pack = types.SimpleNamespace(resource='room_hour', facts_include_catalog=True,
                                     facts=lambda b, lang, now: karaoke.facts(b, lang, now))
        orig = customer_context.knowledge_block
        customer_context.knowledge_block = lambda bid: ''
        try:
            vi = customer_context.facts(BID, pack, '2026-10-26T15:00', 'Monday', lang='vi')
            en = customer_context.facts(BID, pack, '2026-10-26T15:00', 'Monday', lang='en')
        finally:
            customer_context.knowledge_block = orig
        self.assertIn(f'OPENING HOURS: {WEEK_VI}.', vi)                     # customer_context.hours_lines theo ngôn ngữ chat
        self.assertTrue(self.opening_line(vi).startswith(f'OPENING HOURS: {WEEK_VI};'))   # ... cùng kiểu với dữ kiện gói
        self.assertNotIn(' pm', vi)
        self.assertIn(f'OPENING HOURS: {WEEK_EN}.', en)
        self.assertNotIn(WEEK_VI, en)

    def test_closing_time_in_refusals(self):
        self.ktv()
        r = self.call(karaoke, 'karaoke_check_rooms', {'date': FRI, 'time': '23:30', 'hours': 3, 'group_size': 4})
        self.assertIn('It closes at 2:00 am (Sat); the latest start that fits is 23:00.', r['requested_time']['why'])
        r = self.call(karaoke, 'karaoke_check_rooms', {'date': SAT, 'time': '01:30', 'hours': 1, 'group_size': 4})
        self.assertIn('It closes at 2:00 am (Sat); the latest start that fits is 01:00.', r['requested_time']['why'])
        r = self.call(karaoke, 'karaoke_check_rooms', {'date': '2026-11-04', 'time': '23:30', 'hours': 1, 'group_size': 4})
        self.assertIn('It closes at midnight; the latest start that fits is 23:00.', r['requested_time']['why'])

    def test_fnb_facts_tool_field_and_refusal(self):
        T.biz('fnb')
        T.settings(hours=LATE, auto_confirm=True, table={'max_covers_per_slot': 20, 'last_booking_before_close': 30})
        facts = self.opening_line(fnb.facts(BID, 'en', T.NOW))
        self.assertTrue(facts.startswith(f'OPENING HOURS: {WEEK_EN};'), facts)
        self.assertTrue(self.opening_line(fnb.facts(BID, 'vi', T.NOW)).startswith(f'OPENING HOURS: {WEEK_VI};'))
        chk = self.call(fnb, 'fnb_check_tables', {'date': SAT, 'time': '03:00', 'party_size': 2})
        self.assertEqual(chk['opening_hours'], SAT_EN)
        self.assertIn(f'Opening hours that day: {SAT_EN}.', chk['requested_time']['why'])
        self.assertEqual(self.call(fnb, 'fnb_check_tables', {'date': SAT, 'party_size': 2}, vi_ctx())['opening_hours'], SAT_VI)
        late = self.call(fnb, 'fnb_reserve_table', {'date': SAT, 'time': '01:45', 'party_size': 2, 'customer_name': 'Mia',
                                                    'phone': '0412345678'})
        self.assertIn('It closes at 2:00 am (Sat); the latest start that fits is 01:30.', late['message'])
        ch = self.call(fnb, 'fnb_reserve_table', {'date': FRI, 'time': '19:00', 'party_size': 2, 'customer_name': 'Mia',
                                                  'phone': '0412345678'})
        moved = self.call(fnb, 'fnb_change_reservation', {'reservation_id': ch['reservation_id'], 'time': '12:00'}, vi_ctx())
        self.assertIn('Opening hours that day: T6 18:00 – 02:00 (sáng T7).', moved['message'])


# ================================================================ (3) Chủ nhật nghỉ sau ca đêm thứ Bảy, theo kiểu chung
class ClosedDayAfterALateNight(T.Base):
    LATE_SAT = {'mon': None, 'tue': None, 'wed': None, 'thu': None, 'fri': None, 'sat': ['18:00', '02:00'], 'sun': None}

    def test_karaoke_and_fnb_sunday_1am(self):
        T.biz('karaoke')
        T.settings(hours=self.LATE_SAT, auto_confirm=True, table={'max_covers_per_slot': 20})
        T.room(1, 'Room A (2-10 people)', 20)
        k = self.call(karaoke, 'karaoke_check_rooms', {'date': SUN, 'time': '00:30', 'hours': 1, 'group_size': 4})
        f = self.call(fnb, 'fnb_check_tables', {'date': SUN, 'time': '01:00', 'party_size': 2})
        for r in (k, f):
            self.assertEqual(r['opening_hours'], 'Sat 6:00 pm – 2:00 am (Sun), Sun closed')
            self.assertTrue(r['requested_time']['free'], r)                # 01:00 Chủ nhật đặt được thật
            self.assertEqual(r['if_booked_status'], 'confirmed')
        self.assertEqual(self.call(karaoke, 'karaoke_check_rooms', {'date': SUN}, vi_ctx())['opening_hours'],
                         'T7 18:00 – 02:00 (sáng CN), CN nghỉ')
        self.assertEqual(self.call(fnb, 'fnb_check_tables', {'date': MON, 'party_size': 2})['opening_hours'], 'Mon closed')


# ================================================================ RIGHT NOW: cùng kiểu giờ, quyết định vẫn từ open_status
class RightNowLine(T.Base):
    def line(self, now, lang='en', hours=LATE):
        rules = {'configured': True, 'hours': hours, 'info': {}}
        return with_now(now, lambda: customer_context.hours_lines(BID, rules, lang=lang)[1])

    def test_open_and_closed_wording(self):
        tail = 'A team member can reply when the business opens.'
        cases = [
            (datetime(2026, 10, 30, 23, 0), 'open until 2:00 am (Sat).', 'open until 02:00 (sáng T7).'),
            (datetime(2026, 10, 31, 1, 15), 'open until 2:00 am (Sat).', 'open until 02:00 (sáng T7).'),   # ca đêm thứ Sáu
            (datetime(2026, 10, 31, 3, 0), f'closed — next opening today 6:00 pm. {tail}',
             f'closed — next opening hôm nay 18:00. {tail}'),
            (datetime(2026, 11, 2, 23, 0), f'closed — next opening Wed 4:00 pm. {tail}',
             f'closed — next opening T4 16:00. {tail}'),                    # thứ Hai đã đóng, thứ Ba nghỉ
            (datetime(2026, 11, 3, 12, 0), f'closed — next opening tomorrow 4:00 pm. {tail}',
             f'closed — next opening ngày mai 16:00. {tail}'),
            (datetime(2026, 11, 4, 23, 30), 'open until midnight.', 'open until 24:00.'),
        ]
        for now, en, vi in cases:
            self.assertEqual(self.line(now), 'RIGHT NOW: ' + en, now)
            self.assertEqual(self.line(now, 'vi'), 'RIGHT NOW: ' + vi, now)
        self.assertEqual(self.line(datetime(2026, 10, 30, 10, 0), hours=booking_rules.DEFAULT_HOURS),
                         'RIGHT NOW: open until 8:00 pm.')

    def test_describe_for_ai_uses_the_same_lines(self):
        T.biz('nail')
        booking_rules.save_rules(BID, {'hours': booking_rules.DEFAULT_HOURS})
        now = datetime(2026, 10, 31, 8, 0)
        desc = with_now(now, lambda: booking_rules.describe_for_ai(BID)).splitlines()
        cc = with_now(now, lambda: customer_context.hours_lines(BID, booking_rules.get_rules(BID)))
        self.assertEqual(desc[0], cc[0])
        self.assertEqual(desc[0], 'OPENING HOURS: Mon 9:00 am – 7:00 pm, Tue 9:00 am – 7:00 pm, Wed 9:00 am – 7:00 pm, '
                                  'Thu 9:00 am – 8:00 pm, Fri 9:00 am – 8:00 pm, Sat 9:00 am – 6:00 pm, Sun 10:00 am – 5:00 pm.')
        right_now = next(l for l in desc if l.startswith('RIGHT NOW: '))
        self.assertEqual(right_now, cc[1])
        self.assertEqual(right_now, 'RIGHT NOW: closed — next opening today 9:00 am. A team member can reply when the business '
                                    'opens.')

    def test_no_hours_at_all_prints_nothing(self):
        self.assertEqual(customer_context.hours_lines(BID, {'configured': False, 'hours': {}, 'info': {}},
                                                      include_defaults=True), [])


# ================================================================ (4) giả lập --mock: tiệm mẫu F&B / karaoke chỉ nhận yêu cầu
class SimMockShopIsRequestOnly(T.Base):
    def test_mock_shop_truth_matches_the_ai_and_mock_status(self):
        import scenarios_common
        import scenarios_fnb
        import scenarios_karaoke
        import sim_receptionist as sim
        for industry, kind, sub, mod in (('karaoke', 'karaoke', 'karaoke_reservations', scenarios_karaoke),
                                         ('fnb', 'table', 'table_reservations', scenarios_fnb)):
            DB.reset()
            booking_rules._CACHE.clear()
            sim.mock_fixture(DB, industry)
            bs = DB.booking_settings.find_one({'business_id': sim.MOCK_BIZ})
            self.assertIs(bs['auto_confirm'], True)                         # giá trị trang Cài đặt đặt lịch CŨ ghi cho mọi ngành
            self.assertNotIn(rc.GENERAL_SAVED_MARK, bs)
            self.assertIs(rc.load_rules(sim.MOCK_BIZ, kind)['auto_confirm'], False)
            self.assertIs(scenarios_common.auto_confirm_of(bs, sub), False)
            self.assertEqual(mod.MOCK_STATUS, 'pending')


if __name__ == '__main__':
    unittest.main(verbosity=2)
