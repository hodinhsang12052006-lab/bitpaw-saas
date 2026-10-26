# -*- coding: utf-8 -*-
"""Test OFFLINE — đặt trùng lịch qua trang đặt lịch công khai (POST /create_appointment):
  1 thợ + giờ chồng lấn (theo thời lượng dịch vụ) => 409 kèm câu báo rõ ràng đúng ngôn ngữ của tiệm, KHÔNG lưu lịch thứ 2.

Bối cảnh: scripts/nail_persona_e2e.mjs bước "Khách khác đặt trùng giờ trùng thợ -> bị chặn (409)" báo HTTP 200. Nguyên nhân
là TEST (lịch đầu đặt ở giờ trống pickSlot chọn, vd 09:30; lịch "trùng" lại gửi localIso = giờ hiện tại + 2 ngày, vd
12:00 — 2 giờ khác nhau nên server nhận là đúng). File này chứng minh server chặn lịch trùng THẬT, kể cả các biến thể:
staff_id số/chuỗi, giờ có giây / dấu cách, giờ chồng lấn theo thời lượng, 2 người bấm cùng lúc (khoá slot_key).

Chạy route THẬT (blueprints/spa_bp.py::create_appointment, lấy mã nguồn qua ast, bỏ decorator) + booking_engine.py +
booking_rules.py THẬT. KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gửi email,
KHÔNG gọi mạng: mongo_client / email_service / requests / security_shield được thay TRƯỚC mọi import.

Chạy: python scripts/tests/test_booking_duplicate_conflict.py
"""
import ast
import io
import os
import sys
import types
import unittest
from datetime import date, datetime, timedelta
from itertools import count
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from pymongo.errors import DuplicateKeyError  # noqa: E402  (chỉ lớp lỗi, không kết nối)


# ---------------------------------------------------------------- DB giả trong RAM
def _match_value(v, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith('$') for k in cond):
        for op, arg in cond.items():
            if op == '$in' and v not in arg:
                return False
            if op == '$nin' and v in arg:
                return False
            if op == '$ne' and v == arg:
                return False
            if op in ('$gte', '$gt', '$lt', '$lte'):
                if v is None:
                    return False
                if (op == '$gte' and not v >= arg) or (op == '$gt' and not v > arg) or \
                        (op == '$lt' and not v < arg) or (op == '$lte' and not v <= arg):
                    return False
        return True
    return v == cond


def _matches(doc, flt):
    return all(_match_value(doc.get(k), c) for k, c in (flt or {}).items())


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs = name, []

    def insert_one(self, doc):
        # index unique một phần (business_id, slot_key) như scripts/ensure_indexes.py
        if self.name == 'appointments' and isinstance(doc.get('slot_key'), str) and any(
                d.get('business_id') == doc.get('business_id') and d.get('slot_key') == doc['slot_key'] for d in self.docs):
            raise DuplicateKeyError('E11000 duplicate key error: slot_key')
        doc.setdefault('_id', f'oid{len(self.docs) + 1}')
        self.docs.append(dict(doc))
        return types.SimpleNamespace(inserted_id=doc['_id'])

    def find(self, flt=None, projection=None):
        return [dict(d) for d in self.docs if _matches(d, flt)]

    def find_one(self, flt=None, projection=None, **kw):
        rows = self.find(flt)
        return rows[0] if rows else None

    def count_documents(self, flt=None):
        return len(self.find(flt))

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                d.update(update.get('$set') or {})
                for k in (update.get('$unset') or {}):
                    d.pop(k, None)
                return types.SimpleNamespace(matched_count=1)
        return types.SimpleNamespace(matched_count=0)

    def find_one_and_update(self, flt, update, upsert=False, return_document=None):
        return {'n': 1}


class FakeDB:
    def __init__(self):
        self.__dict__['_c'] = {}

    def __getattr__(self, name):
        return self._c.setdefault(name, FakeCollection(name))

    def __getitem__(self, name):
        return getattr(self, name)

    def reset(self):
        self._c.clear()


DB = FakeDB()
_ids = count(1)
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED',
                                                    load_env_file=lambda *a, **k: None)


def _no_network(*a, **k):
    raise AssertionError('network call in an offline test')


_requests = types.ModuleType('requests')
for _n in ('get', 'post', 'put', 'patch', 'delete', 'request'):
    setattr(_requests, _n, _no_network)
_requests.Session = _no_network
_requests.RequestException = Exception
sys.modules['requests'] = _requests

_email = types.ModuleType('email_service')
_email.EmailService = types.SimpleNamespace(send_email=MagicMock(return_value=(True, 'stub')))
sys.modules['email_service'] = _email

_shield = types.ModuleType('security_shield')
_shield.honeypot_tripped = lambda data: False
_shield.strike = MagicMock()
_shield.client_ip = lambda req: '198.51.100.9'
sys.modules['security_shield'] = _shield

from flask import Flask, jsonify, request  # noqa: E402

import booking_rules  # noqa: E402
import booking_engine  # noqa: E402

# ---------------------------------------------------------------- route THẬT từ blueprints/spa_bp.py
with io.open(os.path.join(ROOT, 'blueprints', 'spa_bp.py'), encoding='utf-8') as _f:
    _TREE = ast.parse(_f.read())
NS = {'db': DB, 'request': request, 'jsonify': jsonify, 'datetime': datetime,
      'book_appointment': booking_engine.book_appointment, 'SlotAlreadyBookedError': booking_engine.SlotAlreadyBookedError}
for _node in _TREE.body:
    if isinstance(_node, ast.Assign) and any(getattr(t, 'id', '') == 'PUBLIC_BOOKINGS_PER_PHONE' for t in _node.targets):
        exec(compile(ast.Module(body=[_node], type_ignores=[]), 'spa_bp.py', 'exec'), NS)
    if isinstance(_node, ast.FunctionDef) and _node.name in ('create_appointment', '_shop_is_vi'):
        _node.decorator_list = []
        exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), f'spa_bp.py::{_node.name}', 'exec'), NS)
assert 'create_appointment' in NS and '_shop_is_vi' in NS, 'blueprints/spa_bp.py::create_appointment không còn ở chỗ cũ'

APP = Flask(__name__)
APP.add_url_rule('/create_appointment', 'create_appointment', NS['create_appointment'], methods=['POST'])

AU, VN, SPA = 'biz_au_nails', 'biz_vn_nails', 'biz_us_spa'


def _next_weekday(min_days=3):
    d = date.today() + timedelta(days=min_days)
    while d.weekday() >= 5:  # Thứ 2–6: giờ mặc định 09:00–19:00
        d += timedelta(days=1)
    return d.isoformat()


DAY = _next_weekday()


def T(hm, sep='T'):
    return f'{DAY}{sep}{hm}'


VI_CHARS = set('ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹáàãéèíìóòõúùýĐ')


class DuplicateBookingTest(unittest.TestCase):
    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()
        _email.EmailService.send_email.reset_mock()
        DB.businesses.insert_one({'id': AU, 'name': 'Rose Nails', 'country': 'AU', 'industry_code': 'nail'})
        DB.businesses.insert_one({'id': VN, 'name': 'Tiệm Hoa', 'country': 'VN', 'industry_code': 'nail'})
        DB.businesses.insert_one({'id': SPA, 'name': 'Calm Spa', 'country': 'US', 'industry_code': 'spa'})
        for bid, code, name in ((AU, 'QA1001', 'Tech Anna'), (AU, 'QA1002', 'Tech Bea'), (VN, 'VN01', 'Thợ Lan'),
                                (VN, 'VN02', 'Thợ Mai')):
            DB.employees.insert_one({'business_id': bid, 'ma_nv': code, 'ho_ten': name, 'linh_vuc': 'Nails'})
        DB.staff.insert_one({'business_id': SPA, 'id': 7, 'name': 'Linh'})
        DB.staff.insert_one({'business_id': SPA, 'id': 8, 'name': 'Mai'})
        DB.products.insert_one({'id': 501, 'business_id': AU, 'name': 'Gel manicure'})
        DB.products.insert_one({'id': 601, 'business_id': VN, 'name': 'Sơn gel'})
        DB.products.insert_one({'id': 701, 'business_id': SPA, 'name': 'Massage'})
        self.client = APP.test_client()
        self._phone = count(100)

    def book(self, service_id, staff_id, book_time, name=None):
        n = next(self._phone)
        r = self.client.post('/create_appointment', json={'name': name or f'Customer {n}', 'phone': f'0400000{n}',
                                                          'service_id': service_id, 'staff_id': staff_id, 'book_time': book_time})
        return r.status_code, r.get_json()

    def appts(self, bid):
        return [a for a in DB.appointments.docs if a['business_id'] == bid]

    # ---- trùng đúng giờ + đúng thợ (đúng tình huống bước e2e muốn kiểm)
    def test_exact_duplicate_same_tech_same_time_is_409_in_shop_language(self):
        code, body = self.book('501', 'QA1001', T('10:00'))
        self.assertEqual(code, 200, body)
        self.assertEqual(body['book_time'], T('10:00'))
        stored = self.appts(AU)[0]
        # khách thứ 2 gửi ĐÚNG book_time + staff_id đã lưu (như e2e đã sửa)
        code, body = self.book('501', stored['staff_id'], stored['book_time'])
        self.assertEqual(code, 409, body)
        self.assertFalse(body['success'])
        self.assertEqual(body['message'], 'That team member is already booked then.')
        self.assertEqual(len(self.appts(AU)), 1, 'lịch trùng không được lưu')

    def test_old_e2e_duplicate_was_a_different_slot(self):
        """Tái hiện lần chạy FAIL 2026-10-26: lịch đầu lưu 09:30 (giờ trống đầu tiên), bước "trùng" gửi localIso = giờ hiện
        tại + 2 ngày (12:00 khi chạy lúc 12:22) -> KHÔNG trùng, server nhận (200) là ĐÚNG. Gửi lại đúng 09:30 -> 409."""
        self.assertEqual(self.book('501', 'QA1001', T('09:30'))[0], 200)
        self.assertEqual(self.book('501', 'QA1001', T('12:00'))[0], 200)
        self.assertEqual(self.book('501', 'QA1001', T('09:30'))[0], 409)

    def test_duplicate_message_is_vietnamese_for_vn_shop(self):
        self.assertEqual(self.book('601', 'VN01', T('10:00'))[0], 200)
        code, body = self.book('601', 'VN01', T('10:00'))
        self.assertEqual(code, 409, body)
        self.assertEqual(body['message'], 'Thợ này đã có khách giờ đó.')
        self.assertEqual(len(self.appts(VN)), 1)

    # ---- chồng lấn theo thời lượng dịch vụ (mặc định 60 phút; cấu hình riêng 90 phút)
    def test_overlap_by_service_duration_blocks_but_back_to_back_is_allowed(self):
        self.assertEqual(self.book('501', 'QA1001', T('10:00'))[0], 200)       # 10:00–11:00
        self.assertEqual(self.book('501', 'QA1001', T('10:30'))[0], 409)       # bắt đầu giữa lịch đầu
        self.assertEqual(self.book('501', 'QA1001', T('09:15'))[0], 409)       # 09:15–10:15 đè vào 10:00
        self.assertEqual(self.book('501', 'QA1001', T('11:00'))[0], 200)       # nối tiếp ngay sau: không chặn oan
        self.assertEqual(self.book('501', 'QA1001', T('09:00'))[0], 200)       # 09:00–10:00 kết thúc đúng lúc lịch đầu bắt đầu
        self.assertEqual(len(self.appts(AU)), 3)

    def test_configured_service_duration_is_used(self):
        DB.booking_settings.insert_one({'business_id': AU, 'durations': {'501': 90}})
        self.assertEqual(self.book('501', 'QA1001', T('10:00'))[0], 200)       # 10:00–11:30
        code, body = self.book('501', 'QA1001', T('11:00'))
        self.assertEqual(code, 409, body)
        self.assertEqual(self.book('501', 'QA1001', T('11:30'))[0], 200)

    # ---- biến thể định dạng giờ / kiểu staff_id không lách được
    def test_time_format_variants_are_the_same_slot(self):
        self.assertEqual(self.book('501', 'QA1001', T('10:00'))[0], 200)
        self.assertEqual(self.book('501', 'QA1001', T('10:00:00'))[0], 409)
        self.assertEqual(self.book('501', 'QA1001', T('10:00', sep=' '))[0], 409)
        self.assertEqual([a['book_time'] for a in self.appts(AU)], [T('10:00')])

    def test_staff_id_int_and_string_are_the_same_tech(self):
        code, body = self.book(701, 7, T('10:00'))          # JSON số
        self.assertEqual(code, 200, body)
        self.assertEqual(self.appts(SPA)[0]['staff_id'], '7')
        code, body = self.book('701', '7', T('10:00'))      # chuỗi (select.value của trang đặt lịch)
        self.assertEqual(code, 409, body)
        self.assertEqual(body['message'], 'That team member is already booked then.')

    def test_legacy_appointment_with_int_staff_id_and_seconds_still_blocks(self):
        DB.appointments.insert_one({'id': 9001, 'business_id': SPA, 'staff_id': 8, 'service_id': 701,
                                    'book_time': T('14:00:00'), 'status': 'confirmed', 'customer_name': 'Old'})
        self.assertEqual(self.book('701', '8', T('14:00'))[0], 409)
        self.assertEqual(self.book('701', '8', T('14:30'))[0], 409)
        self.assertEqual(self.book('701', '8', T('15:00'))[0], 200)

    # ---- không chặn oan
    def test_other_tech_or_no_preference_same_time_is_allowed(self):
        self.assertEqual(self.book('501', 'QA1001', T('10:00'))[0], 200)
        self.assertEqual(self.book('501', 'QA1002', T('10:00'))[0], 200)       # 2 thợ, 2 khách
        code, body = self.book('501', '', T('10:00'))                          # hết chỗ (2 thợ đều bận)
        self.assertEqual(code, 409, body)
        self.assertEqual(body['message'], 'That time is fully booked.')

    def test_cancelled_booking_frees_the_slot(self):
        self.assertEqual(self.book('501', 'QA1001', T('10:00'))[0], 200)
        first = self.appts(AU)[0]
        DB.appointments.update_one({'id': first['id']}, {'$set': {'status': 'cancelled'}, '$unset': {'slot_key': ''}})
        self.assertEqual(self.book('501', 'QA1001', T('10:00'))[0], 200)

    # ---- 2 khách bấm cùng lúc: cả 2 đều thấy "còn trống" trước khi ai kịp ghi -> khoá slot_key nguyên tử chặn người sau
    def test_race_both_saw_free_atomic_slot_lock_returns_409_in_english_for_au_shop(self):
        self.assertEqual(self.book('501', 'QA1001', T('10:00'))[0], 200)
        with patch.object(booking_rules, 'check_slot', lambda *a, **k: True), \
                patch.object(DB.appointments, 'find_one', lambda *a, **k: None):
            code, body = self.book('501', 'QA1001', T('10:00'))
        self.assertEqual(code, 409, body)
        self.assertIn('already booked at 10:00', body['message'])
        self.assertFalse(VI_CHARS & set(body['message']), f'tiệm AU không được thấy tiếng Việt: {body["message"]}')
        self.assertEqual(len(self.appts(AU)), 1)

    def test_race_message_is_vietnamese_for_vn_shop(self):
        self.assertEqual(self.book('601', 'VN01', T('10:00'))[0], 200)
        with patch.object(booking_rules, 'check_slot', lambda *a, **k: True):
            code, body = self.book('601', 'VN01', T('10:00'))     # find_one thấy lịch trùng (nhánh bỏ qua luật tiệm)
        self.assertEqual(code, 409, body)
        self.assertTrue(body['message'].startswith('Nhân viên đã có lịch hẹn khác lúc 10:00 ngày '), body['message'])

    def test_engine_error_carries_reason_for_ai_tool(self):
        booking_engine.book_appointment(AU, {'name': 'A', 'phone': '1'}, 'QA1001', T('10:00'), service_id=501, source='ai_bot',
                                        enforce_rules=False)
        with self.assertRaises(booking_engine.SlotAlreadyBookedError) as cm:
            booking_engine.book_appointment(AU, {'name': 'B', 'phone': '2'}, 'QA1001', T('10:00'), service_id=501,
                                            source='ai_bot', enforce_rules=False)
        self.assertEqual(getattr(cm.exception, 'reason', None), 'staff_busy')
        en, vi = str(cm.exception).split(' / ', 1)
        self.assertIn('already booked at 10:00', en)
        self.assertIn('10:00', vi)

    def test_no_real_email_or_network(self):
        self.book('501', 'QA1001', T('10:00'))
        _email.EmailService.send_email.assert_not_called()   # không có chủ tiệm trong DB giả -> không gửi


if __name__ == '__main__':
    unittest.main(verbosity=2)
