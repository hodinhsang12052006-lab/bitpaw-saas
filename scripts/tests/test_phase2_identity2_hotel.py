# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi review Phase 2 vòng 2, khu "identity2", gói KHÁCH SẠN (ai_packs/hotel.py _create_booking):
đặt phòng TRÙNG (cùng tên + ngày + loại phòng) từ 1 chat web KHÔNG chứng minh được là chủ (trình duyệt khác gõ cùng SĐT, hay
không có mã trình duyệt) không còn được nghe "đặt phòng này đã có rồi": trả lời chung như 1 yêu cầu chờ khách sạn xác nhận —
không mã đặt phòng, không tên / ngày / ghi chú của đặt phòng đã có, không tạo thêm gì; khách sạn nhận ghi chú để tự liên hệ.
Chủ thật (đúng trình duyệt) và hội thoại nền tảng đã ký (Messenger...) vẫn nhận lại đúng đặt phòng cũ.

Dùng lại DB giả + stub của test_phase2_hotel_pack.py (nạp TRƯỚC mọi import): không app.py, không MongoDB thật, không mạng.
Chạy: python scripts/tests/test_phase2_identity2_hotel.py
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_hotel_pack as hp  # noqa: E402  (DB giả, ai_function_tools giả, ai_packs.hotel thật)

from test_phase2_hotel_pack import D, DB, OWNER_ALERTS, STAFF_NOTES, ctx  # noqa: E402


class DuplicateFromAnUnprovenWebChatTests(hp.Base):
    def _generic(self, out, existing):
        text = json.dumps(out, ensure_ascii=False)
        self.assertTrue(out['success'])
        self.assertTrue(out['request_sent_to_team'])
        self.assertFalse(out['confirmed'])
        self.assertEqual(out['status'], 'pending')                  # trạng thái của YÊU CẦU, không phải của đặt phòng đã có
        self.assertNotIn('already', text.lower())
        for leak in ('booking_id', f"#{existing['booking_id']}", str(existing['booking_id']), 'Jane', 'Citizen', D(8), D(10),
                     'room_number', '"101"', 'Late arrival'):
            self.assertNotIn(leak, text, leak)

    def test_same_phone_typed_in_another_browser_learns_nothing(self):
        a = self.book(special_requests='Late arrival, quiet room')
        self.assertTrue(a['success'])
        STAFF_NOTES.clear()
        OWNER_ALERTS.clear()
        for c in (ctx(token='tok-B'), ctx(token=None)):            # trình duyệt khác / không có mã, gõ đúng SĐT đó
            out = self.book(c=c)
            self._generic(out, a)
        self.assertEqual(len(self.live_rows()), 1)                  # không tạo thêm gì
        self.assertEqual(DB.hotel_reservations.find_one({'id': a['booking_id']})['special_requests'], 'Late arrival, quiet room')
        self.assertTrue(STAFF_NOTES and all(f"#{a['booking_id']}" in n[2] for n in STAFF_NOTES), STAFF_NOTES)   # khách sạn được báo
        self.assertEqual(len(OWNER_ALERTS), 2)

    def test_vi_chat_gets_the_same_generic_answer(self):
        a = self.book()
        out = self.book(c=ctx(token='tok-B', lang='vi'))
        self._generic(out, a)
        self.assertIn('KHÔNG', out['say'])

    def test_real_owner_and_signed_platform_thread_still_get_their_booking(self):
        a = self.book()
        again = self.book()                                         # cùng trình duyệt nói "đặt giúp" 2 lần
        self.assertTrue(again['already_booked'])
        self.assertEqual(again['booking_id'], a['booking_id'])
        m = self.book(c=ctx('messenger'), guest_name='Ann Lee', phone='0499 111 222', room_type='Suite')
        m2 = self.book(c=ctx('messenger'), guest_name='Ann Lee', phone='0499 111 222', room_type='Suite')
        self.assertTrue(m2['already_booked'])
        self.assertEqual(m2['booking_id'], m['booking_id'])
        self.assertEqual(len(self.live_rows()), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
