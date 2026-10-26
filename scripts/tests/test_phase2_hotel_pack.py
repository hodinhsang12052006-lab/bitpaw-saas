# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 gói đặt phòng KHÁCH SẠN (ai_packs/hotel.py + reservations_hotel.py + route công khai):
  - xem phòng trống theo loại phòng / ngày / số khách, giá thật × số đêm, tiền của khách sạn;
  - tạo đặt phòng (giữ phòng-đêm nguyên tử, pending / confirmed theo cài đặt của chủ, gắn nguồn ai_bot + hội thoại);
  - xem / huỷ (theo chính sách) / đổi ngày CHỈ đặt phòng chứng minh được của chat này;
  - không bao giờ 2 đặt phòng cùng 1 phòng cùng 1 đêm (phiếu giữ, phiếu cũ lấy lại được, tranh chỗ đồng thời);
  - route /api/public/hotel_reservations gọi cùng module (giữ nguyên hành vi + thông báo VI/EN).

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi API trả phí: mongo_client,
requests, ai_function_tools được thay TRƯỚC mọi import; hàm trong app.py lấy nguyên mã nguồn qua ast.

Chạy: python scripts/tests/test_phase2_hotel_pack.py
"""
import ast
import copy
import itertools
import os
import random
import re
import sys
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from pymongo import ReturnDocument  # noqa: E402  (chỉ hằng số, không kết nối)
from pymongo.errors import DuplicateKeyError  # noqa: E402


# ---------------------------------------------------------------- DB giả trong RAM
def _get(doc, key):
    cur = doc
    for part in str(key).split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _match_value(v, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith('$') for k in cond):
        for op, arg in cond.items():
            if op == '$in':
                if v not in arg:
                    return False
            elif op == '$nin':
                if v in arg:
                    return False
            elif op == '$ne':
                if v == arg:
                    return False
            elif op == '$exists':
                if (v is not None) != bool(arg):
                    return False
            elif op in ('$gt', '$gte', '$lt', '$lte'):
                if v is None:
                    return False
                try:
                    if (op == '$gt' and not v > arg) or (op == '$gte' and not v >= arg) or \
                            (op == '$lt' and not v < arg) or (op == '$lte' and not v <= arg):
                        return False
                except TypeError:
                    return False
            elif op == '$regex':
                if not isinstance(v, str) or not re.search(arg, v, re.I if 'i' in cond.get('$options', '') else 0):
                    return False
            elif op == '$options':
                continue
            else:
                raise NotImplementedError(op)
        return True
    return v == cond


def _matches(doc, flt):
    for k, cond in (flt or {}).items():
        if k == '$or':
            if not any(_matches(doc, f) for f in cond):
                return False
        elif k == '$and':
            if not all(_matches(doc, f) for f in cond):
                return False
        elif not _match_value(_get(doc, k), cond):
            return False
    return True


def _project(doc, projection):
    d = copy.deepcopy(doc)
    if not projection:
        return d
    inc = [k for k, v in projection.items() if v and k != '_id']
    if inc:
        out = {k: d[k] for k in inc if k in d}
        if projection.get('_id', 1) and '_id' in d:
            out['_id'] = d['_id']
        return out
    if projection.get('_id') == 0:
        d.pop('_id', None)
    return d


class _Cursor(list):
    def sort(self, key, direction=1):
        return _Cursor(sorted(self, key=lambda d: (d.get(key) is None, d.get(key) if d.get(key) is not None else ''),
                              reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class _Res(types.SimpleNamespace):
    pass


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs, self._oid = name, [], itertools.count(1)

    def insert_one(self, doc):
        if '_id' not in doc:
            doc['_id'] = f"oid{next(self._oid)}"
        if any(d['_id'] == doc['_id'] for d in self.docs):
            raise DuplicateKeyError(f"E11000 duplicate key error collection: {self.name} _id: {doc['_id']}")
        self.docs.append(copy.deepcopy(doc))
        return _Res(inserted_id=doc['_id'])

    def insert_many(self, docs):
        for d in docs:
            self.insert_one(d)

    def find(self, flt=None, projection=None):
        return _Cursor(_project(d, projection) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = _Cursor(d for d in self.docs if _matches(d, flt or {}))
        if sort:
            rows = rows.sort(*sort[0])
        return _project(rows[0], projection) if rows else None

    def count_documents(self, flt=None):
        return sum(1 for d in self.docs if _matches(d, flt or {}))

    @staticmethod
    def _apply(d, update, inserting=False):
        for k, v in (update.get('$set') or {}).items():
            d[k] = copy.deepcopy(v)
        for k in (update.get('$unset') or {}):
            d.pop(k, None)
        for k, v in (update.get('$inc') or {}).items():
            d[k] = (d.get(k) or 0) + v
        if inserting:
            for k, v in (update.get('$setOnInsert') or {}).items():
                d.setdefault(k, v)

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                return _Res(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            d = {k: v for k, v in flt.items() if not str(k).startswith('$') and not isinstance(v, dict)}
            self._apply(d, update, inserting=True)
            self.insert_one(d)
            return _Res(matched_count=0, modified_count=0, upserted_id=d['_id'])
        return _Res(matched_count=0, modified_count=0, upserted_id=None)

    def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                n += 1
        return _Res(matched_count=n, modified_count=n)

    def find_one_and_update(self, flt, update, projection=None, return_document=ReturnDocument.BEFORE, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                before = copy.deepcopy(d)
                self._apply(d, update)
                return _project(d if return_document == ReturnDocument.AFTER else before, projection)
        return None

    def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                del self.docs[i]
                return _Res(deleted_count=1)
        return _Res(deleted_count=0)

    def delete_many(self, flt):
        keep = [d for d in self.docs if not _matches(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs = keep
        return _Res(deleted_count=n)


class FakeDB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self._c.setdefault(name, FakeCollection(name))

    def __getitem__(self, name):
        return getattr(self, name)

    def reset(self):
        self._c.clear()


DB = FakeDB()
_ids = {}


def _next_id(coll):
    _ids.setdefault(coll, itertools.count(1000))
    return next(_ids[coll])


sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=_next_id, MONGO_STATUS='CONNECTED')
sys.modules['requests'] = types.SimpleNamespace(post=None, get=None)  # không có lệnh mạng nào được phép
STAFF_NOTES, OWNER_ALERTS = [], []
sys.modules['ai_function_tools'] = types.SimpleNamespace(
    _note_for_staff=lambda bid, cid, text, sender='system': STAFF_NOTES.append((bid, cid, text)),
    _alert_owner=lambda bid, cid, text, kind: OWNER_ALERTS.append((bid, cid, text, kind)) or True)


class PackError(Exception):
    pass


# Gói được nạp độc lập với registry (ai_packs/__init__.py của người tích hợp): package giả chỉ có PackError.
_pkg = types.ModuleType('ai_packs')
_pkg.__path__ = [os.path.join(ROOT, 'ai_packs')]
_pkg.PackError = PackError
sys.modules['ai_packs'] = _pkg

import booking_rules  # noqa: E402
import reservations_hotel as rh  # noqa: E402
import ai_packs.hotel as hotel  # noqa: E402

BID = 'hotel-1'
TZ = ZoneInfo('Australia/Sydney')
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=TZ)   # thứ Hai 2/11/2026, 10:00 giờ khách sạn
TODAY = NOW.date()


def D(days):
    return (TODAY + timedelta(days=days)).isoformat()


def ctx(kind='web', token='tok-A', lang='en', now=NOW, phone=None, cid=None):
    if kind == 'web':
        return {'business_id': BID, 'customer_id': cid or f'{BID}:0412345678', 'channel': 'web', 'phone': None,
                'chat_token_hash': token, 'lang': lang, 'now_local': now, 'customer_name': None}
    if kind == 'messenger':
        return {'business_id': BID, 'customer_id': cid or f'{BID}:messenger:PSID-1', 'channel': 'messenger', 'phone': None,
                'chat_token_hash': None, 'lang': lang, 'now_local': now, 'customer_name': 'Ann'}
    if kind == 'whatsapp':
        return {'business_id': BID, 'customer_id': cid or f'{BID}:whatsapp:61412345678', 'channel': 'whatsapp',
                'phone': phone or '+61412345678', 'chat_token_hash': None, 'lang': lang, 'now_local': now,
                'customer_name': None}
    raise ValueError(kind)


def room(rid, number, rtype, price, cap=2, status='Trống'):
    return {'id': rid, 'business_id': BID, 'room_number': number, 'room_type': rtype, 'price_per_night': price,
            'capacity': cap, 'floor': '', 'status': status, 'guest_name': None, 'guest_phone': None, 'checkin_date': None}


def resv(rid, ci, co, room_id=None, room_type=None, status='confirmed', phone='0400000000', **kw):
    d = {'id': rid, 'business_id': BID, 'guest_name': kw.pop('guest_name', 'Other Guest'), 'guest_phone': phone,
         'party_size': 2, 'checkin_date': ci, 'checkout_date': co, 'room_type': room_type, 'room_id': room_id,
         'note': None, 'status': status, 'created_at': datetime.now().isoformat()}
    d.update(kw)
    return d


def run(name, args, c=None):
    return hotel.execute(name, args, c or ctx())


class Base(unittest.TestCase):
    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()
        STAFF_NOTES.clear()
        OWNER_ALERTS.clear()
        DB.businesses.insert_one({'id': BID, 'name': 'Harbour Stay', 'phone': '+61 2 9999 0000', 'address': '1 Quay St, Sydney',
                                  'currency': 'AUD', 'country': 'AU', 'industry_code': 'hotel'})
        DB.hotel_rooms.insert_many([room(1, '101', 'Standard', 100), room(2, '102', 'Standard', 110),
                                    room(3, '201', 'Deluxe', 150, cap=3), room(4, '301', 'Suite', 300, cap=4)])

    def settings(self, **kw):
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'hotel': kw}}, upsert=True)

    def live_rows(self):
        return [r for r in DB.hotel_reservations.docs if r.get('status') in ('pending', 'confirmed')]

    def assertNoDoubleBooking(self):
        """Không 2 đặt phòng còn hiệu lực nào cùng 1 phòng có đêm giao nhau (kiểm bằng chính điều kiện của màn nhân viên)."""
        rows = [r for r in self.live_rows() if r.get('room_id') is not None]
        for a, b in itertools.combinations(rows, 2):
            if a['room_id'] == b['room_id']:
                self.assertFalse(a['checkin_date'] < b['checkout_date'] and a['checkout_date'] > b['checkin_date'],
                                 f"double-booked room {a['room_id']}: #{a['id']} and #{b['id']}")

    def book(self, c=None, **kw):
        args = {'checkin_date': D(8), 'checkout_date': D(10), 'guests': 2, 'room_type': 'Standard',
                'guest_name': 'Jane Citizen', 'phone': '0412 345 678'}
        args.update(kw)
        return run('hotel_create_booking', args, c)


# ================================================================ hợp đồng gói
class TestContract(Base):
    def test_contract_shape(self):
        self.assertEqual(hotel.INDUSTRIES, ('hotel',))
        self.assertEqual(hotel.RESOURCE, 'room_night')
        names = [t['function']['name'] for t in hotel.TOOLS]
        self.assertTrue(all(n.startswith('hotel_') for n in names), names)
        self.assertEqual(set(names), set(hotel.HANDLERS))
        self.assertTrue(hotel.MANAGE_TOOLS <= set(names))
        self.assertEqual(hotel.MANAGE_TOOLS, {'hotel_my_bookings', 'hotel_cancel_booking', 'hotel_change_dates'})
        for t in hotel.TOOLS:
            self.assertEqual(t['type'], 'function')
            self.assertEqual(t['function']['parameters']['type'], 'object')
        self.assertEqual(set(hotel.PROMPT_RULES), {'en', 'vi'})

    def test_no_salon_vocabulary(self):
        texts = [hotel.PROMPT_RULES['en'], hotel.PROMPT_RULES['vi'], hotel.facts(BID, 'en', NOW), hotel.facts(BID, 'vi', NOW)]
        texts += [t['function']['description'] for t in hotel.TOOLS]
        for txt in texts:
            for bad in ('salon', 'technician', 'manicure', 'BitPaw'):
                self.assertNotIn(bad.lower(), txt.lower())

    def test_unknown_tool_and_missing_business(self):
        with self.assertRaises(PackError):
            run('hotel_nope', {})
        with self.assertRaises(PackError):
            hotel.execute('hotel_my_bookings', {}, {'customer_id': 'x'})


# ================================================================ dữ kiện cho prompt
class TestFacts(Base):
    def test_facts_real_rates_currency_rules(self):
        f = hotel.facts(BID, 'en', NOW)
        self.assertIn('2026-11-02 (Monday)', f)
        self.assertIn('AUD', f)
        self.assertIn('Standard: 2 room(s), up to 2 guests per room, $100.00–$110.00 per night depending on the room', f)
        self.assertIn('Deluxe: 1 room(s), up to 3 guests per room, $150.00 per night', f)
        self.assertIn('Suite: 1 room(s), up to 4 guests per room, $300.00 per night', f)
        self.assertIn("REQUESTS the hotel confirms (status 'pending')", f)
        self.assertIn('not published', f)        # giờ nhận/trả phòng chưa đặt -> không bịa
        self.assertIn('Phone: +61 2 9999 0000', f)
        self.assertIn('Address: 1 Quay St, Sydney', f)
        self.assertNotIn('OPENING HOURS', f)     # chủ chưa nhập giờ mở cửa -> không đưa giờ mặc định 9-19

    def test_facts_settings_and_vi_and_vnd(self):
        self.settings(auto_confirm=True, min_nights=2, checkin_time='14:00', checkout_time='11:00', free_cancel_hours=48)
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'info': {'parking': 'Free on site',
                                                                               'cancellation_policy': 'Free until 48h before'}}})
        f = hotel.facts(BID, 'en', NOW)
        self.assertIn('minimum stay 2 nights', f)
        self.assertIn('check-in from 14:00, check-out by 11:00', f)
        self.assertIn("confirmed instantly", f)
        self.assertIn('48 hours before check-in', f)
        self.assertIn('Parking: Free on site', f)
        self.assertIn("written cancellation policy: Free until 48h before", f)
        DB.businesses.update_one({'id': BID}, {'$set': {'currency': 'VND', 'country': 'VN'}})
        DB.hotel_rooms.update_one({'id': 4}, {'$set': {'price_per_night': 1200000}})
        v = hotel.facts(BID, 'vi', NOW)
        self.assertIn('LOẠI PHÒNG & GIÁ/ĐÊM (VND', v)
        self.assertIn('1.200.000đ/đêm', v)
        self.assertIn('tối thiểu 2 đêm', v)

    def test_currency_never_defaults_to_vnd_abroad(self):
        DB.businesses.update_one({'id': BID}, {'$set': {'currency': None, 'country': 'US'}})
        f = hotel.facts(BID, 'en', NOW)
        self.assertIn('NIGHTLY RATES (USD', f)
        self.assertIn('$150.00 per night', f)
        self.assertNotIn('đ', f)
        DB.businesses.update_one({'id': BID}, {'$set': {'currency': '', 'country': ''}})
        self.assertEqual(run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(9)})['currency'], 'USD')
        DB.businesses.update_one({'id': BID}, {'$set': {'currency': 'gbp', 'country': 'GB'}})
        r = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10), 'room_type': 'Suite'})
        self.assertEqual((r['currency'], r['room_types'][0]['total']), ('GBP', '600.00 GBP'))

    def test_vi_facts_use_vietnamese_day_names(self):
        self.assertIn('2026-11-02 (Thứ Hai)', hotel.facts(BID, 'vi', NOW))

    def test_facts_no_rooms(self):
        DB.hotel_rooms.docs.clear()
        f = hotel.facts(BID, 'en', NOW)
        self.assertIn("none listed for online booking", f)
        self.assertNotIn('per night', f)


# ================================================================ xem phòng trống
class TestCheckAvailability(Base):
    def test_happy_path_rates_and_totals(self):
        r = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10), 'guests': 2})
        self.assertTrue(r['success'])
        self.assertEqual((r['nights'], r['currency']), (2, 'AUD'))
        by = {t['room_type']: t for t in r['room_types']}
        self.assertEqual(by['Standard']['rate_per_night'], '$100.00')   # phòng rẻ nhất còn trống của loại
        self.assertEqual(by['Standard']['total'], '$200.00')
        self.assertEqual(by['Standard']['rooms_left'], 2)
        self.assertEqual(by['Suite']['total'], '$600.00')
        self.assertEqual([t['room_type'] for t in r['room_types']], ['Standard', 'Deluxe', 'Suite'])
        self.assertIn('request', r['booking_is'])
        for t in r['room_types']:
            self.assertNotIn('_room', t)  # không lộ phòng nội bộ

    def test_one_type_case_insensitive(self):
        r = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(9), 'room_type': 'deluxe room'})
        self.assertEqual([t['room_type'] for t in r['room_types']], ['Deluxe'])
        self.assertEqual(r['room_types'][0]['total'], '$150.00')

    def test_capacity_conflict_offers_other_types_and_dates(self):
        DB.hotel_reservations.insert_many([resv(1, D(8), D(10), room_id=1), resv(2, D(7), D(9), room_id=2)])
        r = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10), 'room_type': 'Standard'})
        st = r['room_types'][0]
        self.assertFalse(st['available'])
        self.assertIn('fully booked', st['why'])
        self.assertNotIn('total', st)
        self.assertEqual({t['room_type'] for t in r['other_room_types_free']}, {'Deluxe', 'Suite'})
        self.assertTrue(r['nearby_dates_free'])
        first = r['nearby_dates_free'][0]
        # phòng 102 trả phòng sáng D(9) -> D(9)..D(11) (cùng 2 đêm, lệch +1 ngày) đã bán lại được
        self.assertEqual((first['checkin_date'], first['checkout_date']), (D(9), D(11)))
        self.assertEqual(first['room_types'][0], {'room_type': 'Standard', 'total': '$220.00'})

    def test_checkout_day_is_not_an_overlap(self):
        DB.hotel_reservations.insert_many([resv(1, D(6), D(8), room_id=1), resv(2, D(10), D(12), room_id=2)])
        r = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10), 'room_type': 'Standard'})
        self.assertEqual(r['room_types'][0]['rooms_left'], 2)

    def test_unassigned_public_requests_take_capacity(self):
        # 1 phòng Standard đã xếp + 1 yêu cầu Standard chưa xếp phòng (form công khai) => hết Standard
        DB.hotel_reservations.insert_many([resv(1, D(8), D(10), room_id=1), resv(2, D(9), D(11), room_type='standard', status='pending')])
        r = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10), 'room_type': 'Standard'})
        self.assertFalse(r['room_types'][0]['available'])
        # yêu cầu không rõ loại phòng chiếm 1 phòng bất kỳ: 3 phòng đã xếp + 1 yêu cầu "Bất kỳ" => hết sạch
        DB.hotel_reservations.docs.clear()
        DB.hotel_reservations.insert_many([resv(1, D(8), D(10), room_id=1), resv(2, D(8), D(10), room_id=2),
                                           resv(3, D(8), D(10), room_id=3), resv(4, D(8), D(10), room_type=None, status='pending')])
        r = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10)})
        self.assertFalse(any(t['available'] for t in r['room_types']))

    def test_cancelled_bookings_free_the_room(self):
        DB.hotel_reservations.insert_many([resv(1, D(8), D(10), room_id=1, status='cancelled')])
        r = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10), 'room_type': 'Standard'})
        self.assertEqual(r['room_types'][0]['rooms_left'], 2)

    def test_in_house_guest_blocks_tonight_unless_leaving_today(self):
        DB.hotel_rooms.update_one({'id': 1}, {'$set': {'status': 'Đang ở', 'guest_name': 'Walk In'}})
        r = run('hotel_check_availability', {'checkin_date': D(0), 'checkout_date': D(1), 'room_type': 'Standard'})
        self.assertEqual(r['room_types'][0]['rooms_left'], 1)
        self.assertEqual(r['room_types'][0]['rate_per_night'], '$110.00')
        # khách đang ở có đặt phòng trả phòng hôm nay -> phòng bán lại được đêm nay
        DB.hotel_reservations.insert_one(resv(9, D(-2), D(0), room_id=1))
        r = run('hotel_check_availability', {'checkin_date': D(0), 'checkout_date': D(1), 'room_type': 'Standard'})
        self.assertEqual(r['room_types'][0]['rooms_left'], 2)
        # đêm sau không bị chặn bởi khách đang ở
        DB.hotel_reservations.docs.clear()
        r = run('hotel_check_availability', {'checkin_date': D(1), 'checkout_date': D(2), 'room_type': 'Standard'})
        self.assertEqual(r['room_types'][0]['rooms_left'], 2)

    def test_too_many_guests_for_one_room(self):
        r = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(9), 'guests': 6})
        self.assertFalse(any(t['available'] for t in r['room_types']))
        self.assertIn('largest room fits 4', r['note'])
        self.assertIn('fits up to 2 guests', {t['room_type']: t for t in r['room_types']}['Standard']['why'])

    def test_bad_input(self):
        bad = [
            ({'checkin_date': D(10), 'checkout_date': D(8)}, 'Check-out must be after check-in'),
            ({'checkin_date': D(-1), 'checkout_date': D(1)}, 'in the past'),
            ({'checkin_date': D(1), 'checkout_date': D(70)}, 'Up to 60 nights'),
            ({'checkin_date': D(400), 'checkout_date': D(401)}, 'one year'),
            ({'checkin_date': '12/11/2026', 'checkout_date': D(9)}, 'not a valid date'),
            ({'checkin_date': D(8), 'checkout_date': D(9), 'room_type': 'Penthouse'}, 'Room types: Standard, Deluxe, Suite'),
            ({'checkin_date': D(8), 'checkout_date': D(9), 'guests': 'many'}, 'whole number'),
            ({'checkin_date': D(8), 'checkout_date': D(9), 'guests': 0}, 'whole number'),
        ]
        for args, msg in bad:
            with self.assertRaises(PackError, msg=str(args)) as cm:
                run('hotel_check_availability', args)
            self.assertIn(msg, str(cm.exception))
        with self.assertRaises(PackError) as cm:
            run('hotel_check_availability', {'checkin_date': D(10), 'checkout_date': D(8)}, ctx(lang='vi'))
        self.assertIn('Ngày trả phòng phải sau ngày nhận phòng', str(cm.exception))

    def test_min_stay_and_no_rooms(self):
        self.settings(min_nights=3)
        with self.assertRaises(PackError) as cm:
            run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10)})
        self.assertIn('minimum stay is 3 nights', str(cm.exception))
        DB.hotel_rooms.docs.clear()
        with self.assertRaises(PackError) as cm:
            run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(11)})
        self.assertIn("hasn't listed its rooms", str(cm.exception))


# ================================================================ tạo đặt phòng
class TestCreateBooking(Base):
    def test_happy_path_pending_by_default(self):
        r = self.book(arrival_time='18:30', special_requests='High floor please', email='jane@example.com')
        self.assertTrue(r['success'])
        self.assertEqual(r['status'], 'pending')
        self.assertIn('Do NOT say it is confirmed', r['say'])
        self.assertEqual((r['total'], r['rate_per_night'], r['nights'], r['currency']), ('$200.00', '$100.00', 2, 'AUD'))
        doc = DB.hotel_reservations.find_one({'id': r['booking_id']})
        self.assertEqual(doc['room_id'], 1)
        self.assertEqual((doc['checkin_date'], doc['checkout_date'], doc['party_size']), (D(8), D(10), 2))
        self.assertEqual((doc['source'], doc['ai_conversation_id'], doc['chat_token_hash'], doc['ai_channel']),
                         ('ai_bot', f'{BID}:0412345678', 'tok-A', 'web'))
        self.assertEqual((doc['guest_name'], doc['guest_phone'], doc['guest_email']), ('Jane Citizen', '0412 345 678', 'jane@example.com'))
        self.assertEqual((doc['arrival_time'], doc['special_requests'], doc['quoted_total']), ('18:30', 'High floor please', 200.0))
        self.assertIn('Arrival 18:30', doc['note'])
        claims = sorted(c['_id'] for c in DB.hotel_room_nights.docs)
        self.assertEqual(claims, [f'{BID}|1|{D(8)}', f'{BID}|1|{D(9)}'])
        self.assertEqual(len(STAFF_NOTES), 1)
        self.assertIn('please confirm or decline', OWNER_ALERTS[0][2])
        self.assertEqual(DB.appointments.count_documents({}), 0)   # không bao giờ ghi lịch hẹn "ma"

    def test_staff_notice_in_hotel_language(self):
        DB.businesses.update_one({'id': BID}, {'$set': {'currency': 'VND', 'country': 'VN'}})
        r = self.book()
        self.assertIn(f"nhận yêu cầu đặt phòng #{r['booking_id']}", STAFF_NOTES[0][2])
        self.assertIn('cần xác nhận hoặc từ chối', STAFF_NOTES[0][2])
        self.assertEqual(OWNER_ALERTS[0][2], STAFF_NOTES[0][2])
        self.assertEqual(OWNER_ALERTS[0][3], f"hotel_new_{r['booking_id']}")

    def test_json_string_arguments(self):
        r = hotel.execute('hotel_check_availability', '{"checkin_date": "%s", "checkout_date": "%s"}' % (D(8), D(9)), ctx())
        self.assertTrue(r['success'])

    def test_confirmed_when_owner_auto_confirms(self):
        self.settings(auto_confirm=True)
        r = self.book()
        self.assertEqual(r['status'], 'confirmed')
        self.assertEqual(r['say'], 'Booked and confirmed.')
        self.assertEqual(DB.hotel_reservations.find_one({'id': r['booking_id']})['status'], 'confirmed')

    def test_unpriced_room_type_stays_pending(self):
        self.settings(auto_confirm=True)
        DB.hotel_rooms.update_one({'id': 2}, {'$set': {'price_per_night': 0}})
        r = self.book()
        self.assertEqual(r['status'], 'pending')

    def test_last_room_cannot_be_double_booked(self):
        a = self.book(room_type='Deluxe', guest_name='Alice First')
        b = self.book(c=ctx(token='tok-B', cid=f'{BID}:0499999999'), room_type='Deluxe', guest_name='Bob Second',
                      phone='0499 999 999')
        self.assertTrue(a['success'])
        self.assertFalse(b['success'])
        self.assertIn('nothing was booked', b['message'])
        self.assertEqual({t['room_type'] for t in b['other_room_types_free']}, {'Standard', 'Suite'})
        self.assertEqual(DB.hotel_reservations.count_documents({'room_type': 'Deluxe'}), 1)
        self.assertNoDoubleBooking()

    def test_partial_overlap_is_refused_and_suggests_dates(self):
        DB.hotel_rooms.docs[:] = [d for d in DB.hotel_rooms.docs if d['id'] == 3]   # chỉ còn 1 phòng Deluxe
        self.book(room_type='Deluxe')
        r = self.book(c=ctx(token='tok-B'), room_type='Deluxe', checkin_date=D(9), checkout_date=D(11),
                      guest_name='Bob Second', phone='0499 999 999')
        self.assertFalse(r['success'])
        self.assertEqual(r['nearby_dates_free'][0]['checkin_date'], D(10))
        self.assertNoDoubleBooking()

    def test_same_request_twice_is_not_two_rooms(self):
        a = self.book()
        b = self.book()
        self.assertTrue(b['already_booked'])
        self.assertEqual(b['booking_id'], a['booking_id'])
        self.assertEqual(len(self.live_rows()), 1)

    def test_another_room_and_per_guest_cap(self):
        a = self.book()
        b = self.book(another_room=True)
        self.assertNotEqual(a['booking_id'], b['booking_id'])
        rooms = {DB.hotel_reservations.find_one({'id': x['booking_id']})['room_id'] for x in (a, b)}
        self.assertEqual(rooms, {1, 2})
        self.book(another_room=True, room_type='Suite')
        with self.assertRaises(PackError) as cm:
            self.book(another_room=True, room_type='Deluxe')
        self.assertIn('group booking', str(cm.exception))
        self.assertEqual(len(self.live_rows()), 3)
        self.assertNoDoubleBooking()

    def test_party_too_big_for_room_type_is_honest(self):
        r = self.book(guests=3)   # Standard tối đa 2 khách/phòng
        self.assertFalse(r['success'])
        self.assertEqual(r['reason'], 'too_many_guests')
        self.assertIn('fits up to 2 guests', r['message'])
        self.assertEqual({t['room_type'] for t in r['other_room_types_free']}, {'Deluxe', 'Suite'})
        self.assertNotIn('nearby_dates_free', r)
        self.assertEqual(DB.hotel_reservations.count_documents({}), 0)
        self.assertEqual(DB.hotel_room_nights.count_documents({}), 0)
        r = self.book(c=ctx(lang='vi'), guests=3)
        self.assertIn('tối đa 2 khách', r['message'])

    def test_hourly_cap(self):
        for i in range(hotel.MAX_AI_BOOKINGS_PER_HOUR):
            DB.hotel_reservations.insert_one(resv(500 + i, D(200), D(201), status='cancelled', source='ai_bot'))
        with self.assertRaises(PackError) as cm:
            self.book()
        self.assertIn('paused', str(cm.exception))

    def test_bad_input_never_writes(self):
        cases = [
            ({'guest_name': ''}, "full name"),
            ({'phone': 'abc'}, 'mobile number'),
            ({'email': 'not-an-email'}, 'email'),
            ({'arrival_time': '25:00'}, 'valid time'),
            ({'room_type': 'Penthouse'}, 'Ask which room type'),
            ({'guests': None}, 'Missing guests'),
            ({'checkin_date': D(-3), 'checkout_date': D(-1)}, 'in the past'),
            ({'checkin_date': D(8), 'checkout_date': D(8)}, 'Check-out must be after check-in'),
        ]
        for kw, msg in cases:
            with self.assertRaises(PackError, msg=str(kw)) as cm:
                self.book(**kw)
            self.assertIn(msg, str(cm.exception))
        self.assertEqual(DB.hotel_reservations.count_documents({}), 0)
        self.assertEqual(DB.hotel_room_nights.count_documents({}), 0)

    def test_room_type_required_only_when_several(self):
        args = {'checkin_date': D(8), 'checkout_date': D(9), 'guests': 1, 'guest_name': 'Jane Citizen', 'phone': '0412345678'}
        with self.assertRaises(PackError):
            run('hotel_create_booking', args)
        DB.hotel_rooms.docs[:] = [d for d in DB.hotel_rooms.docs if d['room_type'] == 'Standard']
        self.assertTrue(run('hotel_create_booking', args)['success'])

    def test_whatsapp_uses_verified_phone(self):
        r = run('hotel_create_booking', {'checkin_date': D(8), 'checkout_date': D(9), 'guests': 1, 'room_type': 'Suite',
                                         'guest_name': 'Wes Apps'}, ctx('whatsapp'))
        doc = DB.hotel_reservations.find_one({'id': r['booking_id']})
        self.assertEqual((doc['guest_phone'], doc['ai_channel'], doc['chat_token_hash']), ('+61412345678', 'whatsapp', None))

    def test_live_claim_of_another_booking_in_flight_is_respected(self):
        # 1 lượt đặt khác vừa giữ phòng 101 (chưa kịp ghi đặt phòng) -> lượt này phải lấy 102, không đè
        for n in (D(8), D(9)):
            DB.hotel_room_nights.insert_one({'_id': f'{BID}|1|{n}', 'business_id': BID, 'room_id': 1, 'night': n,
                                             'reservation_id': 99999, 'claimed_at': datetime.now(timezone.utc).isoformat()})
        r = self.book()
        self.assertEqual(DB.hotel_reservations.find_one({'id': r['booking_id']})['room_id'], 2)
        self.assertEqual(r['rate_per_night'], '$110.00')

    def test_stale_claims_are_taken_over(self):
        DB.hotel_reservations.insert_one(resv(77, D(8), D(10), room_id=1, status='cancelled'))
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        for n in (D(8), D(9)):
            DB.hotel_room_nights.insert_one({'_id': f'{BID}|1|{n}', 'business_id': BID, 'room_id': 1, 'night': n,
                                             'reservation_id': 77, 'claimed_at': old})
        # phiếu mồ côi đã quá hạn (đặt phòng không bao giờ được ghi)
        DB.hotel_room_nights.insert_one({'_id': f'{BID}|2|{D(8)}', 'business_id': BID, 'room_id': 2, 'night': D(8),
                                         'reservation_id': 88888, 'claimed_at': old})
        r = self.book()
        self.assertEqual(DB.hotel_reservations.find_one({'id': r['booking_id']})['room_id'], 1)
        self.assertEqual({c['reservation_id'] for c in DB.hotel_room_nights.docs if c['room_id'] == 1}, {r['booking_id']})
        r2 = self.book(another_room=True)
        self.assertEqual(DB.hotel_reservations.find_one({'id': r2['booking_id']})['room_id'], 2)
        self.assertNoDoubleBooking()

    def test_staff_assigned_room_without_claim_is_respected(self):
        DB.hotel_reservations.insert_one(resv(5, D(9), D(12), room_id=1))   # nhân viên xếp tay (không có phiếu giữ)
        r = self.book()
        self.assertEqual(DB.hotel_reservations.find_one({'id': r['booking_id']})['room_id'], 2)
        self.assertNoDoubleBooking()

    def test_concurrent_claim_on_last_counted_room_backs_off(self):
        # Standard: 2 phòng, 1 yêu cầu Standard chưa xếp phòng -> còn đúng 1 chỗ. Một lượt khác giữ phòng 102 đúng lúc
        # giữa "xem còn phòng" và "giữ phòng" của lượt này -> lượt này phải lùi (không bán quá số phòng).
        DB.hotel_reservations.insert_one(resv(6, D(8), D(10), room_type='Standard', status='pending'))
        real = rh.availability
        calls = {'n': 0}

        def racing(*a, **kw):
            out = real(*a, **kw)
            calls['n'] += 1
            if calls['n'] == 1:
                for n in (D(8), D(9)):
                    DB.hotel_room_nights.insert_one({'_id': f'{BID}|2|{n}', 'business_id': BID, 'room_id': 2, 'night': n,
                                                     'reservation_id': 4242, 'claimed_at': datetime.now(timezone.utc).isoformat()})
            return out
        rh.availability = racing
        try:
            r = self.book()
        finally:
            rh.availability = real
        self.assertFalse(r['success'])
        self.assertEqual(self.live_rows(), [DB.hotel_reservations.find_one({'id': 6})])
        self.assertEqual({c['reservation_id'] for c in DB.hotel_room_nights.docs}, {4242})   # phiếu của lượt này đã trả

    def test_vietnamese_messages(self):
        with self.assertRaises(PackError) as cm:
            self.book(c=ctx(lang='vi'), guest_name='')
        self.assertIn('họ tên', str(cm.exception))
        r = self.book(c=ctx(lang='vi'))
        self.assertIn('KHÔNG nói là đã xác nhận', r['say'])


# ================================================================ xem đặt phòng của mình
class TestMyBookings(Base):
    def test_web_token_sees_only_its_own(self):
        mine = self.book()
        self.book(c=ctx(token='tok-B', cid=f'{BID}:0499999999'), guest_name='Bob Second', phone='0499999999', room_type='Suite')
        r = run('hotel_my_bookings', {})
        self.assertEqual([b['booking_id'] for b in r['bookings']], [mine['booking_id']])
        self.assertEqual(r['bookings'][0]['total'], '$200.00')
        self.assertIn('Only bookings made in this chat', r['scope'])

    def test_same_typed_phone_without_token_is_not_proof(self):
        self.book()
        with self.assertRaises(PackError) as cm:
            run('hotel_my_bookings', {}, ctx(token=None))   # cùng customer_id "<tiệm>:<SĐT tự gõ>", không có mã chat
        self.assertIn("For your security", str(cm.exception))
        self.assertIn('+61 2 9999 0000', str(cm.exception))
        r = run('hotel_my_bookings', {}, ctx(token='tok-OTHER'))
        self.assertEqual(r['bookings'], [])
        self.assertIn('call the hotel', r['tell_customer'])

    def test_whatsapp_verified_phone_sees_public_form_booking(self):
        DB.hotel_reservations.insert_many([resv(10, D(3), D(5), room_type='Deluxe', status='pending', phone='0412 345 678',
                                                guest_name='Jane Citizen'),
                                           resv(11, D(3), D(5), room_type='Suite', phone='0499 111 222')])
        self.settings(checkin_time='14:00')
        r = run('hotel_my_bookings', {}, ctx('whatsapp'))
        self.assertEqual([b['booking_id'] for b in r['bookings']], [10])
        self.assertEqual(r['stay_times'], {'check_in_from': '14:00'})
        self.assertNotIn('scope', r)

    def test_messenger_conversation(self):
        b = self.book(c=ctx('messenger'))
        self.assertEqual([x['booking_id'] for x in run('hotel_my_bookings', {}, ctx('messenger'))['bookings']], [b['booking_id']])
        other = ctx('messenger', cid=f'{BID}:messenger:PSID-2')
        self.assertEqual(run('hotel_my_bookings', {}, other)['bookings'], [])
        # customer_id không đúng khuôn kênh nền tảng (giả mạo kênh) -> không phải bằng chứng
        fake = dict(ctx('messenger'), customer_id=f'{BID}:0412345678')
        with self.assertRaises(PackError):
            run('hotel_my_bookings', {}, fake)

    def test_past_and_cancelled_hidden(self):
        DB.hotel_reservations.insert_many([resv(20, D(-5), D(-3), phone='+61412345678'),
                                           resv(21, D(5), D(6), phone='+61412345678', status='cancelled')])
        self.assertEqual(run('hotel_my_bookings', {}, ctx('whatsapp'))['bookings'], [])


# ================================================================ huỷ đặt phòng
class TestCancel(Base):
    def test_needs_confirmation_then_cancels_and_frees_room(self):
        b = self.book()
        r = run('hotel_cancel_booking', {'booking_id': b['booking_id']})
        self.assertTrue(r['needs_confirmation'])
        self.assertEqual(DB.hotel_reservations.find_one({'id': b['booking_id']})['status'], 'pending')
        r = run('hotel_cancel_booking', {'booking_id': b['booking_id'], 'customer_confirmed': True})
        self.assertTrue(r['cancelled'])
        doc = DB.hotel_reservations.find_one({'id': b['booking_id']})
        self.assertEqual((doc['status'], doc['cancelled_by']), ('cancelled', 'customer_ai_chat'))
        self.assertEqual(DB.hotel_room_nights.count_documents({}), 0)
        self.assertIn('cancelled booking', OWNER_ALERTS[-1][2])
        av = run('hotel_check_availability', {'checkin_date': D(8), 'checkout_date': D(10), 'room_type': 'Standard'})
        self.assertEqual(av['room_types'][0]['rooms_left'], 2)
        again = run('hotel_cancel_booking', {'booking_id': b['booking_id'], 'customer_confirmed': True})
        self.assertTrue(again['already_cancelled'])

    def test_other_chats_booking_is_refused_without_leaking(self):
        b = self.book()
        other = ctx(token='tok-B')
        with self.assertRaises(PackError) as e1:
            run('hotel_cancel_booking', {'booking_id': b['booking_id'], 'customer_confirmed': True}, other)
        with self.assertRaises(PackError) as e2:
            run('hotel_cancel_booking', {'booking_id': 999999, 'customer_confirmed': True}, other)
        self.assertEqual(str(e1.exception).replace(str(b['booking_id']), '#'), str(e2.exception).replace('999999', '#'))
        self.assertEqual(DB.hotel_reservations.find_one({'id': b['booking_id']})['status'], 'pending')

    def test_confirmed_policy_window(self):
        self.settings(free_cancel_hours=48, checkin_time='14:00')
        DB.hotel_reservations.insert_many([resv(30, D(1), D(3), room_id=3, phone='+61412345678'),     # nhận phòng mai 14:00
                                           resv(31, D(5), D(7), room_id=4, phone='+61412345678')])
        with self.assertRaises(PackError) as cm:
            run('hotel_cancel_booking', {'booking_id': 30, 'customer_confirmed': True}, ctx('whatsapp'))
        self.assertIn('NOT cancelled', str(cm.exception))
        self.assertEqual(DB.hotel_reservations.find_one({'id': 30})['status'], 'confirmed')
        self.assertTrue(run('hotel_cancel_booking', {'booking_id': 31, 'customer_confirmed': True}, ctx('whatsapp'))['cancelled'])

    def test_default_policy_until_day_before_and_pending_any_time(self):
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'info': {'cancellation_policy': 'One night charged within 24h'}}},
                                       upsert=True)
        DB.hotel_reservations.insert_many([resv(40, D(0), D(2), room_id=1, phone='+61412345678'),
                                           resv(41, D(0), D(2), room_id=2, phone='+61412345678', status='pending'),
                                           resv(42, D(1), D(2), room_id=3, phone='+61412345678')])
        with self.assertRaises(PackError):
            run('hotel_cancel_booking', {'booking_id': 40, 'customer_confirmed': True}, ctx('whatsapp'))
        self.assertTrue(run('hotel_cancel_booking', {'booking_id': 41, 'customer_confirmed': True}, ctx('whatsapp'))['cancelled'])
        r = run('hotel_cancel_booking', {'booking_id': 42, 'customer_confirmed': True}, ctx('whatsapp'))
        self.assertTrue(r['cancelled'])
        self.assertEqual(r['hotel_policy'], 'One night charged within 24h')

    def test_ended_stay_and_bad_id(self):
        DB.hotel_reservations.insert_one(resv(50, D(-3), D(0), room_id=1, phone='+61412345678'))
        with self.assertRaises(PackError) as cm:
            run('hotel_cancel_booking', {'booking_id': 50, 'customer_confirmed': True}, ctx('whatsapp'))
        self.assertIn('already ended', str(cm.exception))
        with self.assertRaises(PackError):
            run('hotel_cancel_booking', {'booking_id': 'abc', 'customer_confirmed': True}, ctx('whatsapp'))


# ================================================================ đổi ngày
class TestChangeDates(Base):
    def change(self, bid_, ci, co, c=None, **kw):
        args = {'booking_id': bid_, 'new_checkin_date': ci, 'new_checkout_date': co, 'customer_confirmed': True}
        args.update(kw)
        return run('hotel_change_dates', args, c)

    def test_needs_confirmation_first(self):
        b = self.book()
        r = self.change(b['booking_id'], D(9), D(11), customer_confirmed=False)
        self.assertTrue(r['needs_confirmation'])
        self.assertEqual(DB.hotel_reservations.find_one({'id': b['booking_id']})['checkin_date'], D(8))

    def test_same_room_claims_move(self):
        b = self.book()
        r = self.change(b['booking_id'], D(9), D(12))
        self.assertTrue(r['changed'])
        self.assertEqual((r['checkin_date'], r['checkout_date'], r['total']), (D(9), D(12), '$300.00'))
        self.assertEqual(r['old_dates'], {'checkin_date': D(8), 'checkout_date': D(10)})
        self.assertEqual(r['old_total'], '$200.00')
        doc = DB.hotel_reservations.find_one({'id': b['booking_id']})
        self.assertEqual((doc['room_id'], doc['status'], doc['changed_from']['checkin_date']), (1, 'pending', D(8)))
        self.assertEqual(sorted(c['night'] for c in DB.hotel_room_nights.docs), [D(9), D(10), D(11)])
        self.assertIn('please confirm the new dates', OWNER_ALERTS[-1][2])

    def test_confirmed_goes_back_to_pending_unless_auto_confirm(self):
        DB.hotel_reservations.insert_one(resv(60, D(8), D(10), room_id=3, phone='+61412345678'))
        r = self.change(60, D(9), D(10), c=ctx('whatsapp'))
        self.assertEqual(r['status'], 'pending')
        self.assertIn('Do NOT say it is confirmed', r['say'])
        self.settings(auto_confirm=True)
        DB.hotel_reservations.update_one({'id': 60}, {'$set': {'status': 'confirmed'}})
        r = self.change(60, D(15), D(16), c=ctx('whatsapp'))
        self.assertEqual(r['status'], 'confirmed')

    def test_moves_to_other_room_of_same_type_when_needed(self):
        b = self.book()
        DB.hotel_reservations.insert_one(resv(61, D(11), D(13), room_id=1))
        r = self.change(b['booking_id'], D(11), D(12))
        doc = DB.hotel_reservations.find_one({'id': b['booking_id']})
        self.assertEqual(doc['room_id'], 2)
        self.assertEqual(r['total'], '$110.00')
        self.assertEqual({(c['room_id'], c['night']) for c in DB.hotel_room_nights.docs}, {(2, D(11))})
        self.assertNoDoubleBooking()

    def test_no_room_for_new_dates_leaves_booking_unchanged(self):
        b = self.book(room_type='Deluxe')
        DB.hotel_reservations.insert_one(resv(62, D(20), D(22), room_id=3))
        r = self.change(b['booking_id'], D(20), D(21))
        self.assertFalse(r['success'])
        self.assertIn('NOT changed', r['message'])
        doc = DB.hotel_reservations.find_one({'id': b['booking_id']})
        self.assertEqual((doc['checkin_date'], doc['checkout_date'], doc['room_id']), (D(8), D(10), 3))
        self.assertEqual(sorted(c['night'] for c in DB.hotel_room_nights.docs), [D(8), D(9)])
        self.assertNoDoubleBooking()

    def test_extending_over_own_nights_is_fine(self):
        DB.hotel_rooms.docs[:] = [d for d in DB.hotel_rooms.docs if d['id'] == 4]
        b = self.book(room_type='Suite')
        r = self.change(b['booking_id'], D(8), D(12))
        self.assertTrue(r['changed'])
        self.assertEqual(r['total'], '$1,200.00')

    def test_ownership_and_rules(self):
        b = self.book()
        with self.assertRaises(PackError):
            self.change(b['booking_id'], D(9), D(11), c=ctx(token='tok-B'))
        DB.hotel_reservations.insert_one(resv(63, D(0), D(2), room_id=2, phone='+61412345678'))
        with self.assertRaises(PackError) as cm:
            self.change(63, D(1), D(3), c=ctx('whatsapp'))
        self.assertIn('check-in day', str(cm.exception))
        for ci, co, msg in ((D(12), D(11), 'after check-in'), (D(-1), D(2), 'in the past'), ('soon', D(2), 'valid date')):
            with self.assertRaises(PackError) as cm:
                self.change(b['booking_id'], ci, co)
            self.assertIn(msg, str(cm.exception))
        with self.assertRaises(PackError) as cm:
            self.change(b['booking_id'], D(9), D(10), guests=3)   # Standard tối đa 2 khách -> không đổi được
        self.assertIn('fits up to 2 guests', str(cm.exception))
        self.assertIn('NOT changed', str(cm.exception))
        self.assertEqual(DB.hotel_reservations.find_one({'id': b['booking_id']})['checkin_date'], D(8))
        DB.hotel_reservations.update_one({'id': b['booking_id']}, {'$set': {'status': 'cancelled'}})
        with self.assertRaises(PackError):
            self.change(b['booking_id'], D(9), D(11))

    def test_unassigned_public_request_counts_by_type(self):
        DB.hotel_reservations.insert_one(resv(64, D(5), D(6), room_type='Deluxe', status='pending', phone='0412 345 678'))
        r = self.change(64, D(6), D(8), c=ctx('whatsapp'))
        self.assertTrue(r['changed'])
        doc = DB.hotel_reservations.find_one({'id': 64})
        self.assertEqual((doc['checkin_date'], doc['room_id'], doc['quoted_total']), (D(6), None, 300.0))
        DB.hotel_reservations.insert_one(resv(65, D(10), D(12), room_id=3))
        r = self.change(64, D(10), D(11), c=ctx('whatsapp'))
        self.assertFalse(r['success'])
        self.assertEqual(DB.hotel_reservations.find_one({'id': 64})['checkin_date'], D(6))


# ================================================================ logic dùng chung + route công khai
def _app_function(name):
    with open(os.path.join(ROOT, 'app.py'), encoding='utf-8') as fh:
        src = fh.read()
    tree = ast.parse(src)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return src, node


class TestSharedLogic(Base):
    def test_overlaps_matches_staff_screen_function(self):
        _src, node = _app_function('_hotel_reservation_overlaps')
        ns = {'db': DB}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), ns)
        app_fn = ns['_hotel_reservation_overlaps']
        rnd = random.Random(7)
        for i in range(60):
            a = rnd.randint(0, 20)
            DB.hotel_reservations.insert_one(resv(2000 + i, D(a), D(a + rnd.randint(1, 4)), room_id=rnd.randint(1, 3),
                                                  status=rnd.choice(['pending', 'confirmed', 'cancelled'])))
        for _ in range(300):
            a = rnd.randint(0, 22)
            args = (BID, rnd.randint(1, 3), D(a), D(a + rnd.randint(1, 5)))
            ex = rnd.choice([None, 2000 + rnd.randint(0, 59)])
            self.assertEqual(app_fn(*args, exclude_id=ex), rh.overlaps(*args, exclude_id=ex))

    def test_public_route_calls_shared_helper(self):
        src, node = _app_function('api_public_hotel_reservation_create')
        body = ast.get_source_segment(src, node)
        self.assertIn('reservations_hotel.create_request', body)
        self.assertNotIn('insert_one', body)

        node.decorator_list = []
        state = {}
        ns = {'request': types.SimpleNamespace(json=None), 'jsonify': lambda d: d,
              '_public_reservation_check': lambda bid, data: (None, (data, state.get('vi', False)))}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), ns)
        route = ns['api_public_hotel_reservation_create']

        ns['request'].json = {'name': 'Jo', 'phone': '0412345678', 'checkin_date': D(8), 'checkout_date': D(10),
                              'party_size': 3, 'room_type': '', 'note': '  late  '}
        out = route(BID)
        self.assertTrue(out['success'])
        doc = DB.hotel_reservations.find_one({'id': out['id']}, {'_id': 0})
        self.assertEqual(set(doc), {'id', 'business_id', 'guest_name', 'guest_phone', 'party_size', 'checkin_date',
                                    'checkout_date', 'room_type', 'room_id', 'note', 'status', 'created_at', 'source'})
        self.assertEqual((doc['status'], doc['room_id'], doc['room_type'], doc['note'], doc['source'], doc['party_size']),
                         ('pending', None, None, 'late', 'web', 3))
        self.assertEqual(DB.hotel_room_nights.count_documents({}), 0)   # form công khai không giữ phòng (nhân viên xếp)

        for data, vi, msg, code in (
                ({'name': 'Jo', 'phone': '1', 'checkin_date': D(8)}, False, 'Please enter your name, phone number and dates.', 400),
                ({'name': 'Jo', 'phone': '1', 'checkin_date': D(8)}, True, 'Vui lòng nhập đầy đủ tên, số điện thoại và ngày nhận/trả phòng.', 400),
                ({'name': 'Jo', 'phone': '1', 'checkin_date': D(8), 'checkout_date': D(8)}, False, 'Check-out must be after check-in.', 400),
                ({'name': 'Jo', 'phone': '1', 'checkin_date': D(1), 'checkout_date': D(70)}, True, 'Tối đa 60 đêm cho 1 yêu cầu.', 400)):
            state['vi'] = vi
            ns['request'].json = data
            body, status = route(BID)
            self.assertEqual((body['success'], body['message'], status), (False, msg, code))

    def test_assign_room_helper_for_staff_screen(self):
        DB.hotel_reservations.insert_many([resv(70, D(3), D(5), room_type='Deluxe', status='pending'),
                                           resv(71, D(4), D(6), room_type='Deluxe', status='pending')])
        self.assertTrue(rh.assign_room(BID, DB.hotel_reservations.find_one({'id': 70}), 3))
        self.assertFalse(rh.assign_room(BID, DB.hotel_reservations.find_one({'id': 71}), 3))
        self.assertIsNone(DB.hotel_reservations.find_one({'id': 71})['room_id'])
        self.assertEqual({c['reservation_id'] for c in DB.hotel_room_nights.docs}, {70})
        self.assertNoDoubleBooking()

    def test_settings_roundtrip_and_validation(self):
        out = rh.save_hotel_settings(BID, {'auto_confirm': 1, 'min_nights': '2', 'checkin_time': '2:00',
                                           'checkout_time': '11:30', 'free_cancel_hours': 24})
        self.assertEqual(out, {'auto_confirm': True, 'min_nights': 2, 'checkin_time': '02:00', 'checkout_time': '11:30',
                               'free_cancel_hours': 24})
        self.assertEqual(rh.hotel_settings(BID), out)
        with self.assertRaises(rh.HotelRequestError):
            rh.save_hotel_settings(BID, {'checkin_time': '2pm'})
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'hotel': {'min_nights': 'x', 'checkin_time': 'bad'}}})
        self.assertEqual(rh.hotel_settings(BID), rh.SETTINGS_DEFAULTS)   # dữ liệu hỏng -> mặc định an toàn

    def test_cancel_allowed_matrix(self):
        s = dict(rh.SETTINGS_DEFAULTS)
        conf = {'status': 'confirmed', 'checkin_date': D(1)}
        self.assertEqual(rh.cancel_allowed({'status': 'pending', 'checkin_date': D(0)}, s, NOW), (True, 'pending_request'))
        self.assertEqual(rh.cancel_allowed(conf, s, NOW), (True, 'before_checkin_day'))
        self.assertEqual(rh.cancel_allowed({'status': 'confirmed', 'checkin_date': D(0)}, s, NOW)[0], False)
        s.update(free_cancel_hours=24, checkin_time='14:00')
        self.assertEqual(rh.cancel_allowed(conf, s, NOW), (True, 'within_free_cancellation'))   # hạn: mai 14:00 - 24h = nay 14:00
        self.assertEqual(rh.cancel_allowed(conf, s, NOW.replace(hour=15))[0], False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
