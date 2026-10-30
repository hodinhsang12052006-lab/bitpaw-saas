# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 vòng 4, khu "hours4": MỘT kiểu giờ mở cửa cho mọi chữ AI / khách đọc, từ 1 helper
(reservations_core): EN 12 giờ 'Mon 9:00 am – 7:00 pm', qua đêm 'Fri 6:00 pm – 2:00 am (Sat)'; VI 24 giờ 'T2 09:00 – 19:00',
qua đêm 'T6 18:00 – 02:00 (sáng T7)'.

  1) prompt khách ĐẦY ĐỦ (compose_booking_assistant_prompt + _booking_assistant_facts của app.py) của 1 tiệm mỗi ngành trong
     9 ngành, EN + VI: giờ cả tuần nói ĐÚNG 1 lần theo kiểu chung + 1 dòng RIGHT NOW. Trước: khách sạn nói 2 lần 2 kiểu
     ('Mon 11:00-22:00 ... (closes at 02:00 Sat, after midnight)' cạnh 'Mon 11:00 am – 10:00 pm'), F&B / karaoke nói 2 lần
     (dòng của gói + dòng của customer_context);
  2) Nails / Spa: ô opening_hours của check_availability == chữ trong prompt (trước: prompt 12 giờ, công cụ '09:00-19:00');
  3) reply_expectation (gửi thẳng cho khách) + booking_rules.open_status: 'today 11:00 am' / 'hôm nay 11:00', thứ trong tuần
     theo ngôn ngữ khách ('T4 16:00' — trước: 'Wed 16:00' cả trong câu tiếng Việt);
  4) văn phòng: lời từ chối ngày nghỉ / ngoài giờ theo kiểu chung + ngôn ngữ chat (retail._hours_line);
  5) check_window: giờ bắt đầu muộn nhất thuộc tối hôm trước, chat VI không còn chữ Anh 'the evening before';
  6) giả lập: giờ mở cửa trong dữ kiện cho giám khảo theo kiểu chung.

Dùng lại DB giả + stub + hàm app.py (lấy qua ast) của test_phase2_receptionist_core.py. KHÔNG import app.py, KHÔNG mở
MongoDB thật, KHÔNG gọi mạng / API trả phí.
Chạy: python scripts/tests/test_phase2_fix4_hours4.py
"""
import os
import re
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_receptionist_core as core  # noqa: E402  (DB giả + stub TRƯỚC mọi import của module thật)

import ai_packs  # noqa: E402
import booking_rules  # noqa: E402
import reservations_core as rc  # noqa: E402
from ai_context_engine import AIContextEngine  # noqa: E402
from ai_sales_prompts import compose_booking_assistant_prompt  # noqa: E402

DB, NS, T = core.DB, core.NS, core.T
NOW = core.NOW                                            # thứ Hai 2026-11-02 08:00 giờ tiệm (booking_rules.local_now giả)
INDUSTRIES = ('nail', 'spa', 'fnb', 'karaoke', 'hotel', 'retail', 'technical', 'production', 'office')
LATE = {'mon': ['11:00', '22:00'], 'tue': None, 'wed': ['16:00', '24:00'], 'thu': ['09:00', '17:00'],
        'fri': ['18:00', '02:00'], 'sat': ['18:00', '02:00'], 'sun': ['17:30', '01:30']}
SALON = {'mon': ['09:00', '19:00'], 'tue': ['09:00', '19:00'], 'wed': ['09:00', '19:00'], 'thu': ['09:00', '20:00'],
         'fri': ['09:00', '20:00'], 'sat': ['09:00', '18:00'], 'sun': None}     # Nails / Spa không mở qua nửa đêm
WEEK = {'en': 'Mon 11:00 am – 10:00 pm, Tue closed, Wed 4:00 pm – midnight, Thu 9:00 am – 5:00 pm, '
              'Fri 6:00 pm – 2:00 am (Sat), Sat 6:00 pm – 2:00 am (Sun), Sun 5:30 pm – 1:30 am (Mon)',
        'vi': 'T2 11:00 – 22:00, T3 nghỉ, T4 16:00 – 24:00, T5 09:00 – 17:00, '
              'T6 18:00 – 02:00 (sáng T7), T7 18:00 – 02:00 (sáng CN), CN 17:30 – 01:30 (sáng T2)'}
SALON_WEEK = {'en': 'Mon 9:00 am – 7:00 pm, Tue 9:00 am – 7:00 pm, Wed 9:00 am – 7:00 pm, Thu 9:00 am – 8:00 pm, '
                    'Fri 9:00 am – 8:00 pm, Sat 9:00 am – 6:00 pm, Sun closed',
              'vi': 'T2 09:00 – 19:00, T3 09:00 – 19:00, T4 09:00 – 19:00, T5 09:00 – 20:00, T6 09:00 – 20:00, '
                    'T7 09:00 – 18:00, CN nghỉ'}
# 1 lần nhắc giờ mở cửa = tên thứ + giờ / nghỉ (kiểu EN hoặc VI); kiểu cũ = khoảng 24 giờ có gạch nối, chữ qua đêm cũ
DAY_TIME = re.compile(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b\.?\s+(?:\d{1,2}:\d{2}|closed|midnight)'
                      r'|\b(?:T[2-7]|CN)\s+(?:\d{1,2}:\d{2}|nghỉ)')
OLD = re.compile(r'\b\d{1,2}:\d{2}\s?-\s?\d{1,2}:\d{2}\b|after midnight\)|qua nửa đêm\)|\(next day\)|\(closes at|đóng lúc')
AMPM = re.compile(r'\b\d{1,2}:\d{2}\s?(?:am|pm)\b', re.I)


def shop(ind):
    bid = f'h4_{ind}'
    DB.businesses.insert_one({'id': bid, 'name': f'Shop {ind}', 'industry_code': ind, 'currency': 'USD', 'country': 'US',
                              'phone': '+12125550100'})
    hours = SALON if ind in ('nail', 'spa') else LATE
    DB.booking_settings.insert_one({'business_id': bid, 'hours': hours, 'info': {'parking': 'Street parking'}})
    DB.products.insert_one({'id': 700, 'business_id': bid, 'name': 'House item', 'price': 10, 'is_active': 1})
    booking_rules._CACHE.clear()
    return bid, hours


def full_prompt(bid, ind, lang):
    """Prompt khách đúng như chat web: danh tính + dữ kiện (app.py::_booking_assistant_facts) + luật gói."""
    pack = ai_packs.pack_for_business(bid)
    ctx = AIContextEngine.build_context_prompt(bid, None, include_private_data=False, audience='customer')
    prompt = compose_booking_assistant_prompt(
        ctx['prompt'], ctx['business_name'], booking_facts=NS['_booking_assistant_facts'](bid, lang=lang),
        booking_enabled=pack is not None, pack=pack, lang=lang, can_verify=False, industry=ind)
    return pack, prompt


# ================================================================ (1) prompt khách đầy đủ, 9 ngành x EN / VI
class FullCustomerPromptStatesHoursOnce(core._Base):
    def test_every_industry_states_the_week_once_in_the_helper_style(self):
        for ind in INDUSTRIES:
            bid, hours = shop(ind)
            rules = booking_rules.get_rules(bid)
            for lang in ('en', 'vi'):
                with self.subTest(industry=ind, lang=lang):
                    pack, prompt = full_prompt(bid, ind, lang)
                    self.assertEqual(pack.name, 'appointment' if ind in ('nail', 'spa') else ind)   # gói THẬT của ngành
                    week = rc.week_hours_text(hours, lang)
                    self.assertEqual(week, (SALON_WEEK if ind in ('nail', 'spa') else WEEK)[lang])
                    self.assertEqual(prompt.count(week), 1, f'{ind}/{lang}: the week must be stated once')
                    self.assertEqual(len(re.findall(r'OPENING HOURS|GIỜ MỞ CỬA', prompt)), 1, prompt)
                    right_now = 'RIGHT NOW: ' + rc.right_now_text(rules, NOW, booking_rules.open_status(bid, rules, NOW), lang)
                    self.assertEqual(prompt.count('RIGHT NOW'), 1)
                    self.assertEqual(prompt.count(right_now), 1, right_now)
                    rest = prompt.replace(week, '').replace(right_now, '')
                    self.assertEqual(DAY_TIME.findall(rest), [], f'{ind}/{lang}: hours stated outside the one helper line')
                    self.assertEqual(OLD.findall(prompt), [], f'{ind}/{lang}: old hours style')
                    if lang == 'vi':
                        self.assertEqual(AMPM.findall(prompt), [])                  # chat VI: không lẫn kiểu 12 giờ
                    else:
                        self.assertNotIn('(sáng ', prompt)

    def test_right_now_words_follow_the_chat_language(self):
        bid, _h = shop('karaoke')
        en, vi = full_prompt(bid, 'karaoke', 'en')[1], full_prompt(bid, 'karaoke', 'vi')[1]
        self.assertIn('RIGHT NOW: closed — next opening today 11:00 am.', en)
        self.assertIn('RIGHT NOW: closed — next opening hôm nay 11:00.', vi)

    def test_pack_line_keeps_its_booking_notes_and_the_hotel_line_is_gone(self):
        bid, _h = shop('fnb')
        fnb_prompt = full_prompt(bid, 'fnb', 'en')[1]
        self.assertIn(f"OPENING HOURS: {WEEK['en']}; a time after midnight is on the NEXT date", fnb_prompt)
        self.assertIn('The last reservation starts 60 min before closing.', fnb_prompt)
        hbid, _h = shop('hotel')
        hotel = ai_packs.pack_for('hotel').module
        for lang in ('en', 'vi'):
            own = hotel.facts(hbid, lang, NOW)
            self.assertNotIn('OPENING HOURS', own)                                  # 1 nguồn: customer_context.hours_lines
            self.assertNotIn('GIỜ MỞ CỬA', own)
            self.assertIn(f'OPENING HOURS: {WEEK[lang]}.', full_prompt(hbid, 'hotel', lang)[1])


# ================================================================ (2) Nails / Spa: công cụ nói giờ đúng như prompt
class AppointmentToolSaysWhatThePromptSays(core._Base):
    def test_check_availability_opening_hours_match_the_prompt(self):
        for ind in ('nail', 'spa'):
            bid, _h = shop(ind)
            for lang, wed, sun in (('en', 'Wed 9:00 am – 7:00 pm', 'Sun closed'), ('vi', 'T4 09:00 – 19:00', 'CN nghỉ')):
                with self.subTest(industry=ind, lang=lang):
                    prompt = full_prompt(bid, ind, lang)[1]
                    with T.chat_scope(lang=lang):
                        open_day = T.check_availability(bid, f'{bid}:0412345678', date='2026-11-04')
                        closed_day = T.check_availability(bid, f'{bid}:0412345678', date='2026-11-08')
                    self.assertEqual((open_day['open'], open_day['opening_hours']), (True, wed))
                    self.assertEqual((closed_day['open'], closed_day['opening_hours']), (False, sun))
                    self.assertIn(wed, prompt)
                    self.assertIn(sun, prompt)
                    self.assertNotIn('09:00-19:00', str(open_day))

    def test_default_language_is_english(self):
        bid, _h = shop('nail')
        self.assertEqual(T.check_availability(bid, None, date='2026-11-05')['opening_hours'], 'Thu 9:00 am – 8:00 pm')


# ================================================================ (3) lời hẹn giờ trả lời gửi khách + open_status
class ReplyExpectationUsesTheOneStyle(core._Base):
    def expect(self, now, vi=False):
        with patch.object(booking_rules, 'local_now', lambda bid: now):
            return T.reply_expectation(self.bid, vi)

    def test_closed_wording_en_and_vi(self):
        self.bid, _h = shop('fnb')
        cases = [(NOW, 'today 11:00 am', 'hôm nay 11:00'),                                  # thứ Hai 08:00
                 (datetime(2026, 11, 3, 12, 0), 'tomorrow 4:00 pm', 'ngày mai 16:00'),     # thứ Ba nghỉ
                 (datetime(2026, 11, 2, 23, 0), 'Wed 4:00 pm', 'T4 16:00')]                # thứ Hai đã đóng, thứ Ba nghỉ
        for now, en, vi in cases:
            self.assertIn(f"We're closed right now — the team will reply here when we open ({en}).", self.expect(now))
            self.assertIn(f'Tiệm đang đóng cửa — nhân viên sẽ trả lời tại đây khi tiệm mở cửa ({vi}).', self.expect(now, True))
        for text in (self.expect(NOW), self.expect(NOW, True)):
            self.assertIn('call +12125550100', text.replace('gọi', 'call'))
        self.assertIn('The team is in today', self.expect(datetime(2026, 10, 31, 1, 0)))  # thứ Bảy 01:00 = ca đêm thứ Sáu

    def test_open_status_strings_use_the_helper(self):
        r = {'hours': dict(LATE)}
        cases = [(datetime(2026, 10, 30, 23, 0), 'closes_at', '2:00 am (Sat)', '02:00 (sáng T7)'),
                 (datetime(2026, 10, 31, 1, 15), 'closes_at', '2:00 am (Sat)', '02:00 (sáng T7)'),
                 (datetime(2026, 11, 2, 12, 0), 'closes_at', '10:00 pm', '22:00'),
                 (datetime(2026, 11, 4, 23, 30), 'closes_at', 'midnight', '24:00'),
                 (datetime(2026, 10, 31, 3, 0), 'next_open', 'today 6:00 pm', 'hôm nay 18:00'),
                 (datetime(2026, 11, 2, 23, 0), 'next_open', 'Wed 4:00 pm', 'T4 16:00')]
        for now, key, en, vi in cases:
            self.assertEqual(booking_rules.open_status('x', r, now)[key], en, now)
            self.assertEqual(booking_rules.open_status('x', r, now, lang='vi')[key], vi, now)
        self.assertEqual(booking_rules.open_status('x', r, datetime(2026, 11, 2, 23, 0))['next_open_day'], 2)


# ================================================================ (4) văn phòng: lời từ chối theo kiểu chung + ngôn ngữ chat
class OfficeRefusalsUseTheOneStyle(core._Base):
    def refuse(self, bid, lang, **args):
        office = ai_packs.pack_for('office').module
        ctx = {'business_id': bid, 'lang': lang, 'now_local': NOW, 'customer_id': None, 'channel': 'web'}
        with self.assertRaises(ai_packs.PackError) as e:
            office.execute('office_request_consultation', dict({'topic': 'Set up a small company'}, **args), ctx)
        return str(e.exception)

    def test_closed_day_and_outside_hours(self):
        bid, _h = shop('office')
        for lang, thu in (('en', 'Thu 9:00 am – 5:00 pm'), ('vi', 'T5 09:00 – 17:00')):
            closed = self.refuse(bid, lang, preferred_date='2026-11-03')                     # thứ Ba nghỉ
            self.assertIn(f'The office is closed on Tuesday (OPENING HOURS: {WEEK[lang]}.).', closed)
            late = self.refuse(bid, lang, preferred_date='2026-11-05', preferred_time='18:00')
            self.assertIn(f'18:00 is outside office hours on Thursday ({thu}).', late)
            for msg in (closed, late):
                self.assertEqual(OLD.findall(msg), [], msg)
        self.assertEqual(DB.consultation_requests.docs, [])

    def test_retail_hours_line(self):
        retail = ai_packs.pack_for('retail').module
        self.assertEqual(retail._hours_line({'hours': LATE}), f"OPENING HOURS: {WEEK['en']}.")
        self.assertEqual(retail._hours_line({'hours': LATE}, 'vi'), f"OPENING HOURS: {WEEK['vi']}.")
        self.assertEqual(retail._hours_line({'hours': {'mon': ['09:00', '17:00']}}),
                         'OPENING HOURS: Mon 9:00 am – 5:00 pm, ' + ', '.join(f'{rc.DAY_NAMES[d]} closed' for d in rc.DAY_KEYS[1:]) + '.')


# ================================================================ (5) giờ bắt đầu muộn nhất thuộc tối hôm trước
class LatestStartFromTheEveningBefore(unittest.TestCase):
    def test_vi_chat_gets_vietnamese_words(self):
        r = {'hours': dict(LATE), 'min_lead_minutes': 0, 'max_advance_days': 366}
        when, now = datetime(2026, 10, 31, 0, 30), datetime(2026, 10, 26, 15, 0)       # thứ Bảy 00:30 = đêm thứ Sáu
        for lang, closes, latest in (('en', '2:00 am (Sat)', '23:00 the evening before'),
                                     ('vi', '02:00 (sáng T7)', '23:00 (tối T6)')):
            with self.assertRaises(rc.ReservationError) as e:
                rc.check_window(r, when, now, 180, lang=lang)                              # 00:30 + 3 giờ > 02:00
            self.assertEqual((e.exception.reason, e.exception.detail['closes_at'], e.exception.detail['latest_start']),
                             ('too_close_to_closing', closes, latest))
        with self.assertRaises(rc.ReservationError) as e:
            rc.check_window(r, datetime(2026, 10, 31, 1, 30), now, 60, lang='vi')
        self.assertEqual(e.exception.detail['latest_start'], '01:00')                    # cùng ngày lịch: giờ trơn như cũ


# ================================================================ (6) giả lập: dữ kiện cho giám khảo
class SimJudgeFactsUseTheOneStyle(unittest.TestCase):
    def test_common_facts(self):
        sim_dir = os.path.join(core.ROOT, 'scripts', 'ai_sim')
        if sim_dir not in sys.path:
            sys.path.insert(0, sim_dir)
        import sim_receptionist as sr
        shop_ = {'name': 'X', 'noun': 'restaurant', 'currency': 'USD', 'tz': 'America/New_York', 'now': NOW, 'hours': LATE,
                 'address': '', 'phone': '', 'info': {}}
        facts = sr.common_facts(shop_)
        self.assertIn(f"Opening hours: {WEEK['en']}.", facts)
        self.assertEqual(OLD.findall(facts), [])
        self.assertIn('Opening hours: NOT published', sr.common_facts(dict(shop_, hours=None)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
