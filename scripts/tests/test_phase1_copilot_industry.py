# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 1 "Copilot per industry + sidebar split":
  1) business_snapshot theo ngành: lịch hẹn + hoa hồng thợ ("No POS sales in 30d") CHỈ cho nail/spa; nhà hàng thấy bàn /
     đặt bàn / món, karaoke giờ phòng / công suất, khách sạn công suất / khách đến, bán lẻ hết hàng / bán chạy, xưởng sản
     lượng / nguyên liệu, kỹ thuật việc / thợ / phụ tùng, văn phòng chấm công / nghỉ phép — chỉ từ dữ liệu thật, "chưa có" khi trống;
  2) doanh thu dùng 1 bộ lọc duy nhất (ai_copilot_tools.REVENUE_STATUSES) cho công cụ lẫn bảng tóm tắt, số khớp sales_report;
     tiền tệ không bao giờ rơi về VND cho tiệm ngoài Việt Nam;
  3) nút hỏi nhanh theo ngành trong ai_bot.html khớp ai_copilot.INSIGHT_TOPICS / INDUSTRY_TOPICS;
  4) sidebar: "Hộp thư AI / AI Inbox" (Pro) tách khỏi "AI Copilot" (chỉ admin, /ai_bot#copilot, khoá Empire); nhân viên không thấy.

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi DeepSeek / mạng:
mongo_client + requests được thay TRƯỚC mọi import.

Chạy: python scripts/tests/test_phase1_copilot_industry.py
"""
import contextlib
import io
import json
import os
import re
import sys
import types
import unittest
from datetime import datetime, timedelta
from itertools import count

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)


def _read(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------- DB giả trong RAM (đủ cho các truy vấn của Copilot)
def _get(doc, key):
    cur = doc
    for part in str(key).split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _cmp(v, op, arg):
    if v is None:
        return False
    try:
        return {'$gte': v >= arg, '$gt': v > arg, '$lt': v < arg, '$lte': v <= arg}[op]
    except TypeError:
        return False


def _match_value(v, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith('$') for k in cond):
        for op, arg in cond.items():
            if op == '$in' and v not in arg:
                return False
            if op == '$nin' and v in arg:
                return False
            if op == '$ne' and v == arg:
                return False
            if op == '$exists' and (v is not None) != bool(arg):
                return False
            if op == '$regex' and not (isinstance(v, str) and re.search(arg, v, re.I if 'i' in str(cond.get('$options', '')) else 0)):
                return False
            if op in ('$gte', '$gt', '$lt', '$lte') and not _cmp(v, op, arg):
                return False
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
        elif k == '$nor':
            if any(_matches(doc, f) for f in cond):
                return False
        elif not _match_value(_get(doc, k), cond):
            return False
    return True


class _Cursor(list):
    def sort(self, key, direction=1):
        def k(d):
            v = d.get(key)
            return (v is None, v if isinstance(v, (int, float)) else str(v or ''))
        return _Cursor(sorted(self, key=k, reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs = name, []

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def insert_many(self, docs):
        for d in docs:
            self.insert_one(d)

    def find(self, flt=None, projection=None):
        return _Cursor(dict(d) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = self.find(flt)
        if sort:
            rows = rows.sort(*sort[0])
        return dict(rows[0]) if rows else None

    def count_documents(self, flt=None):
        return len(self.find(flt))

    def aggregate(self, pipeline):
        raise AssertionError('Copilot snapshot must not depend on aggregate() here')


class FakeDB:
    def __init__(self):
        self.__dict__['_c'] = {}

    def __getattr__(self, name):
        if name not in self._c:
            self._c[name] = FakeCollection(name)
        return self._c[name]

    def __getitem__(self, name):
        return getattr(self, name)

    def list_collection_names(self):
        return [k for k, c in self._c.items() if c.docs]

    def reset(self):
        self._c.clear()


DB = FakeDB()
_ids = count(5000)
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED',
                                                    load_env_file=lambda *a, **k: None)
_req = types.ModuleType('requests')          # không bao giờ gọi mạng
_req.post = _req.get = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network call in offline test'))
sys.modules['requests'] = _req

import ai_copilot  # noqa: E402
import ai_copilot_tools as tools  # noqa: E402
import booking_rules  # noqa: E402

BID = 'biz-p1'
NOW = datetime(2026, 10, 26, 15, 0)        # thứ Hai, 15:00 giờ tiệm (test truyền `now` -> giờ máy chủ = giờ tiệm)


def ago(days=0, hours=0):
    return (NOW - timedelta(days=days, hours=hours)).isoformat()


def dmy(days):
    return (NOW - timedelta(days=days)).strftime('%d/%m/%Y')


def ymd(days_from_today):
    return (NOW.date() + timedelta(days=days_from_today)).isoformat()


def biz(industry, currency='USD', country='US', name='Test Shop'):
    doc = {'id': BID, 'name': name, 'industry_code': industry}
    if currency:
        doc['currency'] = currency
    if country:
        doc['country'] = country
    DB.businesses.insert_one(doc)


def order(oid, total, days_ago, status='completed', **meta):
    DB.orders.insert_one({'id': oid, 'business_id': BID, 'created_at': ago(days_ago, 1), 'status': status,
                          'total_amount': total, 'payment_method': meta.pop('payment_method', 'cash'), 'metadata': meta})


def item(oid, pid, qty, line):
    DB.order_items.insert_one({'id': next(_ids), 'order_id': oid, 'product_id': pid, 'quantity': qty, 'total_price': line})


class Base(unittest.TestCase):
    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()

    def snap(self, code, now=NOW):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            text, _name, ind = ai_copilot.business_snapshot(BID, code, now=now)
        self.assertNotIn('snapshot block', out.getvalue(), f"a snapshot block crashed:\n{out.getvalue()}")
        return text, ind

    def assertNoSalonLines(self, text):
        self.assertNotIn('APPOINTMENTS', text)
        self.assertNotIn('No POS sales', text)
        self.assertNotIn('Commission earned', text)


# ---------------------------------------------------------------- 1) bảng tóm tắt theo ngành
class TestSalonSnapshot(Base):
    def test_nail_keeps_appointments_commission_and_filters_revenue(self):
        biz('nail')
        order(1, 100, 2)
        order(2, 50, 3, status='PAID')                           # Square bán lẻ đã quẹt -> tính
        order(3, 999, 1, status='failed')                        # thẻ bị từ chối -> KHÔNG tính
        order(4, 777, 1, status='pending', payment_method='square')   # còn chờ quẹt -> KHÔNG tính
        order(5, -20, 1, status='refunded', original_order_id=1)      # hoàn tiền -> trừ
        order(6, 80, 40)                                         # 30 ngày trước đó
        DB.employees.insert_many([{'business_id': BID, 'ma_nv': 'NV1', 'ho_ten': 'Anna'},
                                  {'business_id': BID, 'ma_nv': 'NV2', 'ho_ten': 'Ben'}])
        DB.chamcong.insert_one({'id': 1, 'business_id': BID, 'ma_nv': 'NV1', 'ngay_cham': dmy(2), 'tien_tua': 30,
                                'ghi_chu': '[NAIL POS] Order #1'})
        for i, (when, st) in enumerate([(NOW + timedelta(days=1), 'confirmed'), (NOW + timedelta(days=3), 'pending'),
                                        (NOW + timedelta(days=2), 'cancelled')]):
            DB.appointments.insert_one({'id': i, 'business_id': BID, 'status': st, 'book_time': when.strftime('%Y-%m-%dT%H:%M')})
        text, ind = self.snap('nail')
        self.assertEqual(ind, 'nail')
        self.assertIn('$130.00 from 2 bills', text)
        self.assertIn('previous 30 days $80.00 from 1 bills; change +62%', text)
        self.assertIn('APPOINTMENTS booked for the next 7 days: 2', text)
        self.assertIn('Commission earned last 30d: Anna $30.00 (1 clients)', text)
        self.assertIn('No POS sales in 30d: Ben', text)
        self.assertNotIn('NOTE: this business does not take salon appointments', text)
        self.assertNotIn('đ', text)
        self.assertNotIn('VND', text)


class TestRevenueSingleFilter(Base):
    def test_snapshot_revenue_equals_sales_report_last_30_days(self):
        biz('retail')
        real_now = datetime.now()
        for oid, total, days, st in [(1, 120.5, 2, 'completed'), (2, 30, 5, 'PAID'), (3, 500, 3, 'failed'),
                                     (4, -10, 4, 'refunded'), (5, 64, 45, 'completed')]:
            DB.orders.insert_one({'id': oid, 'business_id': BID, 'status': st, 'total_amount': total,
                                  'created_at': (real_now - timedelta(days=days)).isoformat(), 'metadata': {}})
        rep = tools.sales_report(BID, 'last_30_days')
        text, _ = self.snap('retail', now=None)
        self.assertEqual(rep['net_revenue'], '$140.50')
        self.assertEqual(rep['bills'], 2)
        self.assertIn(f"{rep['net_revenue']} from {rep['bills']} bills", text)

    def test_revenue_statuses_defined_once(self):
        self.assertIn('PAID', tools.REVENUE_STATUSES)
        self.assertEqual(tools.REVENUE_ORDER_FILTER, {'status': {'$in': tools.REVENUE_STATUSES}})
        src = _read('ai_copilot.py')
        self.assertNotIn('partially_refunded', src, 'ai_copilot.py must use ai_copilot_tools.REVENUE_ORDER_FILTER, not its own list')
        tsrc = _read('ai_copilot_tools.py')
        self.assertEqual(tsrc.count("'partially_refunded'"), 1)

    def test_stock_status_ignores_failed_orders(self):
        biz('retail')
        DB.products.insert_many([{'id': 1, 'business_id': BID, 'name': 'Mug', 'stock': 40, 'is_active': 1},
                                 {'id': 2, 'business_id': BID, 'name': 'Cap', 'stock': 40, 'is_active': 1}])
        DB.orders.insert_one({'id': 10, 'business_id': BID, 'status': 'failed', 'total_amount': 9,
                              'created_at': (datetime.now() - timedelta(days=1)).isoformat()})
        DB.orders.insert_one({'id': 11, 'business_id': BID, 'status': 'completed', 'total_amount': 9,
                              'created_at': (datetime.now() - timedelta(days=1)).isoformat()})
        item(10, 1, 1, 9)
        item(11, 2, 1, 9)
        res = tools.stock_status(BID)
        self.assertIn('Mug', res['not_sold_30_days'])       # chỉ bán trong 1 đơn thất bại -> vẫn là "không bán được"
        self.assertNotIn('Cap', res['not_sold_30_days'])


class TestFnbSnapshot(Base):
    def test_restaurant_sees_tables_reservations_menu_not_salon_lines(self):
        biz('fnb', currency=None, country='AU')                  # thiếu currency -> theo quốc gia (AUD), không phải VND
        DB.dining_tables.insert_many([{'id': 1, 'business_id': BID, 'name': 'T1', 'status': 'Đang phục vụ'},
                                      {'id': 2, 'business_id': BID, 'name': 'T2', 'status': 'Còn trống'},
                                      {'id': 3, 'business_id': BID, 'name': 'T3'}])
        DB.products.insert_many([{'id': 7, 'business_id': BID, 'name': 'Pho', 'price': 15, 'stock': 100, 'is_active': 1},
                                 {'id': 8, 'business_id': BID, 'name': 'Iced tea', 'price': 4, 'stock': 100, 'is_active': 1}])
        order(21, 40, 1, channel='fnb', table_id=1)
        order(22, 60, 2, channel='fnb', table_id=1)
        order(23, 25, 3, channel='fnb', table_id=2)
        item(21, 7, 2, 30)
        item(22, 7, 4, 60)
        DB.table_reservations.insert_many([
            {'id': 1, 'business_id': BID, 'party_size': 4, 'status': 'pending', 'reserved_time': ymd(0) + 'T19:00'},
            {'id': 2, 'business_id': BID, 'party_size': 2, 'status': 'confirmed', 'reserved_time': ymd(3) + 'T12:30'},
            {'id': 3, 'business_id': BID, 'party_size': 8, 'status': 'cancelled', 'reserved_time': ymd(2) + 'T12:30'},
            {'id': 4, 'business_id': BID, 'party_size': 5, 'status': 'confirmed', 'reserved_time': ymd(-2) + 'T12:30'}])
        DB.kitchen_orders.insert_one({'id': 1, 'business_id': BID, 'status': 'cooking', 'created_at': ago(hours=1)})
        DB.employees.insert_many([{'business_id': BID, 'ma_nv': 'NV1', 'ho_ten': 'Chef'},
                                  {'business_id': BID, 'ma_nv': 'NV2', 'ho_ten': 'Waiter'}])
        DB.chamcong.insert_one({'id': 1, 'business_id': BID, 'ma_nv': 'NV1', 'ngay_cham': dmy(1), 'tien_tua': 5,
                                'ghi_chu': 'Order #21'})
        text, ind = self.snap('fnb')
        self.assertEqual(ind, 'fnb')
        self.assertNoSalonLines(text)
        self.assertIn('currency AUD', text)
        self.assertIn('TABLE BILLS last 30 days: 3 of 3 bills were for a table, across 2 tables (about 1.5 bills per table used)', text)
        self.assertIn('busiest: T1 $100.00 (2 bills)', text)
        self.assertIn('TABLES IN SERVICE NOW: 1 of 3 tables.', text)
        self.assertIn('RESERVATIONS next 7 days: 2 bookings for 6 guests (today 1; 1 still waiting for confirmation).', text)
        self.assertIn('TOP MENU ITEMS (30d): Pho $90.00 (6 sold)', text)
        self.assertIn('MENU ITEMS NOT ORDERED IN 30 DAYS: Iced tea', text)
        self.assertIn('COVERS: guest counts are not recorded on bills', text)
        self.assertIn('KITCHEN: 1 tickets waiting or cooking right now.', text)
        self.assertIn('STAFF: 2 people.', text)
        self.assertIn('do not use appointments_on', text)
        self.assertNotIn('đ', text)


class TestKaraokeSnapshot(Base):
    def _seed(self):
        biz('karaoke')
        DB.karaoke_rooms.insert_many([{'id': 1, 'business_id': BID, 'name': 'VIP 1', 'status': 'Đang chơi', 'price_per_hour': 20},
                                      {'id': 2, 'business_id': BID, 'name': 'Room 2', 'status': 'Trống', 'price_per_hour': 30}])
        DB.products.insert_many([
            {'id': 900, 'business_id': BID, 'name': 'Karaoke room time', 'is_room_fee': True, 'stock': 0, 'is_active': 1, 'price': 20},
            {'id': 901, 'business_id': BID, 'name': 'Beer', 'stock': 3, 'is_active': 1, 'price': 5}])
        order(31, 70, 2, channel='karaoke', room_id=1)
        item(31, 900, 1, 50)                 # 50 / 20 = 2.5 giờ
        item(31, 901, 4, 20)
        order(32, 45, 4, channel='karaoke', room_id=2)
        item(32, 900, 1, 45)                 # 45 / 30 = 1.5 giờ
        DB.karaoke_room_reservations.insert_one({'id': 1, 'business_id': BID, 'status': 'pending', 'reserved_time': ymd(1) + 'T20:00'})

    def test_room_hours_fnb_and_unknown_utilisation(self):
        self._seed()
        text, _ = self.snap('karaoke')
        self.assertNoSalonLines(text)
        self.assertIn('ROOMS IN USE NOW: 1 of 2 rooms.', text)
        self.assertIn('ROOM SESSIONS last 30 days: 2 sessions, about 4.0 room-hours', text)
        self.assertIn('room time $95.00, food & drinks $20.00 ($10.00 per session)', text)
        self.assertIn('VIP 1 1 sessions ~2.5 h, $70.00', text)
        self.assertIn('UTILISATION: unknown — opening hours are not set in Booking settings.', text)
        self.assertIn('RESERVATIONS next 7 days: 1 bookings (today 0; 1 still waiting for confirmation).', text)
        self.assertIn('TOP FOOD & DRINKS (30d): Beer $20.00 (4 sold)', text)
        self.assertIn('LOW STOCK (at or below 5): Beer (3 left)', text)
        self.assertNotIn('Karaoke room time (0 left)', text)     # phí giờ phòng không phải hàng tồn kho
        self.assertNotIn('TOP FOOD & DRINKS (30d): Karaoke room time', text)

    def test_utilisation_uses_configured_opening_hours(self):
        self._seed()
        DB.booking_settings.insert_one({'business_id': BID, 'hours': {d: ['18:00', '02:00'] for d in booking_rules.DAY_KEYS}})
        text, _ = self.snap('karaoke')
        # 4.0 giờ đã bán / (2 phòng x 30 ngày x 8 giờ mở cửa qua nửa đêm) = 0.83% -> "about 1%"
        self.assertIn('UTILISATION last 30 days: about 1% of open room-hours sold', text)


class TestHotelSnapshot(Base):
    def test_occupancy_rate_and_arrivals(self):
        biz('hotel')
        DB.hotel_rooms.insert_many([{'id': i, 'business_id': BID, 'status': st} for i, st in
                                    enumerate(['Đang ở', 'Đang dọn', 'Trống', 'Trống'], 1)])
        order(41, 320, 3, channel='hotel', nights=3, room_total=300, extra_charges_total=20)
        order(42, 200, 10, channel='hotel', nights=2, room_total=200, extra_charges_total=0)
        DB.hotel_reservations.insert_many([
            {'id': 1, 'business_id': BID, 'status': 'confirmed', 'checkin_date': ymd(0), 'checkout_date': ymd(2)},
            {'id': 2, 'business_id': BID, 'status': 'pending', 'checkin_date': ymd(3), 'checkout_date': ymd(5)},
            {'id': 3, 'business_id': BID, 'status': 'cancelled', 'checkin_date': ymd(1), 'checkout_date': ymd(2)},
            {'id': 4, 'business_id': BID, 'status': 'confirmed', 'checkin_date': ymd(-3), 'checkout_date': ymd(0)}])
        text, _ = self.snap('hotel')
        self.assertNoSalonLines(text)
        self.assertIn('OCCUPANCY NOW: 1 of 4 rooms occupied (25%); 1 being cleaned.', text)
        self.assertIn('STAYS CHECKED OUT last 30 days: 2 stays, 5 room-nights, average rate $100.00/night (room charges only), '
                      'extras $20.00; occupancy about 4%', text)
        self.assertIn('ARRIVALS (reservations): today 1, next 7 days 2 (1 still pending); departures today 1.', text)
        self.assertIn('Rooms (/hotel_rooms)', text)


class TestRetailSnapshot(Base):
    def test_stockouts_low_stock_top_sellers_restock_in_shop_currency(self):
        biz('retail', currency='VND', country='VN')
        DB.system_settings.insert_one({'key': 'inventory_thresholds', 'business_id': BID, 'value': json.dumps({'critical': 4})})
        DB.products.insert_many([
            {'id': 1, 'business_id': BID, 'name': 'Ao', 'stock': 0, 'is_active': 1, 'price': 100000},
            {'id': 2, 'business_id': BID, 'name': 'Mu', 'stock': 3, 'is_active': 1, 'price': 50000},
            {'id': 3, 'business_id': BID, 'name': 'Giay', 'stock': 50, 'is_active': 1, 'price': 500000, 'cost_price': 300000},
            {'id': 4, 'business_id': BID, 'name': 'Cu', 'stock': 0, 'is_active': 0, 'price': 1}])
        order(51, 1000000, 2)
        item(51, 3, 2, 1000000)
        DB.restock_proposals.insert_many([{'business_id': BID, 'status': 'pending'}, {'business_id': BID, 'status': 'pending'},
                                          {'business_id': BID, 'status': 'approved'}])
        text, _ = self.snap('retail')
        self.assertNoSalonLines(text)
        self.assertIn('STOCK-OUTS: Ao.', text)
        self.assertIn('LOW STOCK (at or below your critical level 4): Mu (3 left)', text)
        self.assertIn('TOP SELLERS (30d): Giay 1.000.000đ (2 sold)', text)
        self.assertIn('NOT SOLD IN 30 DAYS: Ao, Mu', text)
        self.assertIn('HIGHEST MARGIN ITEMS (price - cost): Giay (+200.000đ)', text)
        self.assertIn('RESTOCK SUGGESTIONS waiting for approval: 2', text)
        self.assertNotIn('Cu', text.split('NOT SOLD IN 30 DAYS:')[1].split('\n')[0])


class TestProductionSnapshot(Base):
    def test_output_and_materials_from_recipes(self):
        biz('production')
        DB.production_output.insert_many([
            {'id': 1, 'business_id': BID, 'cong_doan': 'Ao thun', 'so_luong': 100, 'ho_ten': 'Lan', 'ngay': dmy(5)},
            {'id': 2, 'business_id': BID, 'cong_doan': 'Ao thun', 'so_luong': 50, 'ho_ten': 'Minh', 'ngay': dmy(10)},
            {'id': 3, 'business_id': BID, 'cong_doan': 'Quan', 'so_luong': 30, 'ho_ten': 'Lan', 'ngay': dmy(12)},
            {'id': 4, 'business_id': BID, 'cong_doan': 'Quan', 'so_luong': 60, 'ho_ten': 'Lan', 'ngay': dmy(40)}])
        DB.raw_materials.insert_many([{'id': 1, 'business_id': BID, 'name': 'Vai', 'unit': 'm', 'stock_qty': 30},
                                      {'id': 2, 'business_id': BID, 'name': 'Chi', 'unit': 'cuon', 'stock_qty': 0}])
        DB.product_recipes.insert_one({'business_id': BID, 'output_name_normalized': 'ao thun',
                                       'materials': [{'material_id': 1, 'qty_per_unit': 0.5}]})
        DB.employees.insert_one({'business_id': BID, 'ma_nv': 'NV1', 'ho_ten': 'Lan'})
        text, _ = self.snap('production')
        self.assertNoSalonLines(text)
        self.assertNotIn('REVENUE', text)                         # xưởng không bán qua POS: không nhắc "chưa có doanh thu"
        self.assertNotIn('CUSTOMERS', text)
        self.assertIn('OUTPUT last 30 days: 180 units in 3 entries; previous 30 days 60 units; change +200%.', text)
        self.assertIn('OUTPUT BY PRODUCT/STAGE (30d): Ao thun 150; Quan 30', text)
        self.assertIn('OUTPUT BY WORKER (30d): Lan 130; Minh 50', text)
        self.assertIn('MATERIALS: 2 tracked, recipes for 1 products. Out (at or below zero): Chi (0 cuon).', text)
        # 150 áo x 0.5 m = 75 m / 30 ngày = 2.5 m/ngày; còn 30 m -> ~12 ngày
        self.assertIn('MATERIALS RUNNING OUT (at the last-30-day usage from recipes): Vai ~12 days left', text)


class TestTechnicalSnapshot(Base):
    def test_jobs_technicians_parts(self):
        biz('technical')
        DB.tasks.insert_many([
            {'id': 1, 'business_id': BID, 'trang_thai': 'Chờ Nhận'},
            {'id': 2, 'business_id': BID, 'trang_thai': 'Chờ Nhận'},
            {'id': 3, 'business_id': BID, 'trang_thai': 'Đã Nhận', 'nguoi_nhan': 'Tuan'},
            {'id': 4, 'business_id': BID, 'trang_thai': 'Hoàn Thành', 'nguoi_nhan': 'Tuan', 'completed_at': ago(3)},
            {'id': 5, 'business_id': BID, 'trang_thai': 'Hoàn Thành', 'nguoi_nhan': 'Tuan',
             'completed_at': (NOW - timedelta(days=5)).strftime('%Y-%m-%dT%H:%M:%S.000Z')},
            {'id': 6, 'business_id': BID, 'trang_thai': 'Hoàn Thành', 'nguoi_nhan': 'Hoa', 'completed_at': ago(60)},
            {'id': 7, 'business_id': BID, 'trang_thai': 'Hoàn Thành', 'nguoi_nhan': 'Hoa'}])
        DB.tech_parts.insert_many([{'business_id': BID, 'name': 'Capacitor', 'stock': 1},
                                   {'business_id': BID, 'name': 'Gas R32', 'stock': 10}])
        order(61, 30, 3, channel='technical_parts', task_id=4)
        order(62, 45, 5, channel='technical_parts', task_id=5)
        text, _ = self.snap('technical')
        self.assertNoSalonLines(text)
        self.assertIn('JOBS: 2 waiting for a technician, 1 in progress, 2 completed in the last 30 days '
                      '(1 older completed jobs have no completion date).', text)
        self.assertIn('TECHNICIANS: Tuan 2 completed (30d), 1 in progress', text)
        self.assertIn('PARTS BILLED last 30 days: $75.00 on 2 jobs (labour charges are not recorded in BitPaw', text)
        self.assertIn('PARTS: 2 tracked; at or below your critical level 5: Capacitor (1 left).', text)


class TestOfficeSnapshot(Base):
    def test_attendance_leave_expenses(self):
        biz('office', currency='AUD', country='AU')
        DB.employees.insert_many([{'business_id': BID, 'ma_nv': 'NV1', 'ho_ten': 'An'},
                                  {'business_id': BID, 'ma_nv': 'NV2', 'ho_ten': 'Binh'},
                                  {'business_id': BID, 'ma_nv': 'NV3', 'ho_ten': 'Chi'}])
        DB.chamcong.insert_many([
            {'id': 1, 'business_id': BID, 'ma_nv': 'NV1', 'ngay_cham': dmy(2), 'so_gio': 8, 'tang_ca': 1},
            {'id': 2, 'business_id': BID, 'ma_nv': 'NV2', 'ngay_cham': dmy(10), 'so_gio': 8, 'tang_ca': 0},
            {'id': 3, 'business_id': BID, 'ma_nv': 'NV2', 'ngay_cham': dmy(45), 'so_gio': 8, 'tang_ca': 0}])
        DB.leave_requests.insert_many([
            {'business_id': BID, 'ho_ten': 'Chi', 'status': 'pending', 'from_date': ymd(5), 'to_date': ymd(6)},
            {'business_id': BID, 'ho_ten': 'Binh', 'status': 'approved', 'from_date': ymd(1), 'to_date': ymd(2)},
            {'business_id': BID, 'ho_ten': 'An', 'status': 'approved', 'from_date': ymd(-10), 'to_date': ymd(-9)}])
        DB.expense_requests.insert_many([{'business_id': BID, 'status': 'pending', 'amount': 100},
                                         {'business_id': BID, 'status': 'pending', 'amount': 50},
                                         {'business_id': BID, 'status': 'approved', 'amount': 999}])
        text, _ = self.snap('office')
        self.assertNoSalonLines(text)
        self.assertNotIn('REVENUE', text)
        self.assertNotIn('CUSTOMERS', text)
        self.assertIn('TIMESHEETS last 30 days: 2 days logged by 2 of 3 staff, 16 hours (+1 overtime).', text)
        self.assertIn('NO TIMESHEET in the last 7 days: Binh, Chi', text)
        self.assertIn(f'LEAVE: 1 requests waiting for approval (Chi {ymd(5)}..{ymd(6)})', text)
        self.assertIn(f'on approved leave in the next 7 days: Binh {ymd(1)}..{ymd(2)}.', text)
        self.assertIn('EXPENSE CLAIMS waiting for approval: 2 totalling $150.00.', text)


class TestEmptyAndCurrency(Base):
    EMPTY_LINES = {
        'nail': ['REVENUE: no paid bills recorded in the last 60 days yet.', 'APPOINTMENTS booked for the next 7 days: 0'],
        'spa': ['APPOINTMENTS booked for the next 7 days: 0', 'CUSTOMERS: none saved yet.'],
        'fnb': ['TABLE BILLS: no bills linked to a table', 'RESERVATIONS next 7 days: none.', 'MENU: no menu items set up yet.'],
        'karaoke': ['ROOMS: no karaoke rooms set up yet.', 'ROOM SESSIONS: no room sessions billed'],
        'hotel': ['ROOMS: no hotel rooms set up yet.', 'STAYS: no check-outs billed', 'ARRIVALS (reservations): today 0'],
        'retail': ['PRODUCTS: no products set up yet.', 'STAFF: no employees added yet.'],
        'production': ['OUTPUT: no production output logged', 'MATERIALS: none tracked yet.'],
        'technical': ['JOBS: no jobs recorded yet.', 'PARTS: none tracked yet.'],
        'office': ['TIMESHEETS: no attendance logged', 'LEAVE: 0 requests waiting for approval; on approved leave in the next 7 days: nobody.',
                   'EXPENSE CLAIMS waiting for approval: 0.'],
    }

    def test_every_industry_with_no_data_says_so_and_never_vnd(self):
        self.assertEqual(set(self.EMPTY_LINES), set(ai_copilot.INDUSTRY_LABEL))
        for code, expected in self.EMPTY_LINES.items():
            with self.subTest(code=code):
                DB.reset()
                biz(code, currency=None, country=None)          # không có tiền tệ lẫn quốc gia -> USD, KHÔNG phải VND
                text, ind = self.snap(code)
                self.assertEqual(ind, code)
                self.assertIn('currency USD', text)
                self.assertNotIn('VND', text)
                self.assertNotIn('đ', text)
                for line in expected:
                    self.assertIn(line, text)
                if code not in ai_copilot.SALON:
                    self.assertNoSalonLines(text)

    def test_unknown_session_mode_falls_back_to_business_industry(self):
        biz('hotel')
        _text, ind = self.snap('none')
        self.assertEqual(ind, 'hotel')

    def test_currency_resolution_and_formatting(self):
        self.assertEqual(tools.business_currency(BID, {'currency': 'aud'}), 'AUD')
        self.assertEqual(tools.business_currency(BID, {'country': 'AU'}), 'AUD')
        self.assertEqual(tools.business_currency(BID, {'country': 'VN'}), 'VND')
        self.assertEqual(tools.business_currency(BID, {'country': 'US'}), 'USD')
        self.assertEqual(tools.business_currency(BID, {}), 'USD')
        self.assertEqual(tools.money_formatter('USD')(5), '$5.00')
        self.assertEqual(tools.money_formatter('VND')(1200000), '1.200.000đ')
        self.assertEqual(tools.money_formatter('EUR')(1234.5), '1,234.50 EUR')    # không còn in 'đ' cho tiền lạ
        biz('nail', currency=None, country='AU')
        self.assertEqual(tools._money(BID)(10), '$10.00')

    def test_agent_prompt_trusts_snapshot_and_excludes_salon_tools(self):
        msgs = ai_copilot.agent_messages('SNAP', 'q', 'en', 'TODAY')
        system = msgs[0]['content']
        self.assertIn('from a line of the BUSINESS SNAPSHOT', system)
        self.assertIn('only fit nail and spa salons', system)
        self.assertNotIn('orientation only', system)


# ---------------------------------------------------------------- 3) nút hỏi nhanh theo ngành
class TestIndustryTopics(unittest.TestCase):
    def setUp(self):
        html = _read('templates', 'ai_bot.html')
        m = re.search(r'<script type="application/json" id="cpTopicsData">(.*?)</script>', html, re.S)
        self.assertTrue(m, 'cpTopicsData block missing in ai_bot.html')
        self.data = json.loads(m.group(1))
        self.html = html

    def test_every_industry_has_topics_known_to_the_api(self):
        for code in list(ai_copilot.INDUSTRY_LABEL) + ['_default']:
            keys = ai_copilot.INDUSTRY_TOPICS[code]
            self.assertGreaterEqual(len(keys), 3, code)
            for k in keys:
                self.assertIn(k, ai_copilot.INSIGHT_TOPICS, f'{code}: topic {k} unknown to /api/ai/copilot')

    def test_template_topics_match_python_and_have_vi_en_labels(self):
        self.assertEqual(self.data['byIndustry'], ai_copilot.INDUSTRY_TOPICS)
        for keys in self.data['byIndustry'].values():
            for k in keys:
                d = self.data['topics'][k]
                self.assertTrue(d.get('en') and d.get('vi') and d.get('icon', '').startswith('fa-'), k)

    def test_non_salon_industries_do_not_get_salon_topics(self):
        for code in ('fnb', 'karaoke', 'hotel', 'retail', 'production', 'technical', 'office'):
            self.assertNotIn('staffing', ai_copilot.INDUSTRY_TOPICS[code])     # "based on bookings" = câu của tiệm nail
            self.assertNotIn('revenue', ai_copilot.INDUSTRY_TOPICS[code])      # "best and weakest services"

    def test_route_still_resolves_topics_through_insight_topics(self):
        app_src = _read('app.py')
        self.assertIn('ai_copilot.INSIGHT_TOPICS.get(topic)', app_src)

    def test_copilot_bar_is_owner_only_and_hash_opens_panel(self):
        self.assertRegex(self.html, r"\{% if session\.get\('role'\) in \('admin', 'super_admin'\) %\}\s*<div id=\"cpTopicBar\"")
        self.assertIn("location.hash !== '#copilot'", self.html)
        self.assertIn("window.addEventListener('hashchange', openCopilotFromHash)", self.html)
        self.assertNotIn("onclick=\"askCopilot('staffing')\"", self.html)     # 4 nút cố định kiểu tiệm nail đã bỏ


# ---------------------------------------------------------------- 4) sidebar: Hộp thư AI vs AI Copilot
class TestSidebarSplit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from jinja2 import Environment, FileSystemLoader
        from markupsafe import Markup
        cls.Markup = Markup
        cls.env = Environment(loader=FileSystemLoader(os.path.join(ROOT, 'templates')))
        cls.menu_en = json.loads(_read('translations', 'en.json'))['menu']
        cls.menu_vi = json.loads(_read('translations', 'vi.json'))['menu']

    def render(self, role, locked=(), lang='en', industry='nail'):
        def url_for(endpoint, **kw):
            return '/' + endpoint + (('#' + kw['_anchor']) if kw.get('_anchor') else '')

        def plan_lock(feat):
            return self.Markup('<span class="plan-lock">LOCK-%s</span>' % feat) if feat in locked else ''
        tpl = self.env.get_template('components/app_sidebar.html')
        return tpl.render(session={'role': role}, url_for=url_for, plan_lock=plan_lock,
                          menu_i18n=self.menu_vi if lang == 'vi' else self.menu_en,
                          menu_i18n_all={'en': self.menu_en, 'vi': self.menu_vi}, default_lang=lang,
                          active_industry_code=industry, active_industry_cfg={'modules': ['nail_services', 'attendance']},
                          request=types.SimpleNamespace(path='/dashboard'), industry_pos_url='/pos',
                          industry_chamcong_url='/chamcong', current_plan='empire')

    def test_menu_translations(self):
        self.assertEqual(self.menu_en['ai_inbox'], 'AI Inbox')
        self.assertEqual(self.menu_vi['ai_inbox'], 'Hộp thư AI')
        self.assertEqual(self.menu_en['ai_copilot'], 'AI Copilot')

    def test_admin_sees_inbox_and_copilot_entries(self):
        html = self.render('admin')
        self.assertIn('<span data-i18n="menu_ai_inbox">AI Inbox</span>', html)
        self.assertIn('href="/ai_bot#copilot"', html)
        self.assertIn('<span data-i18n="menu_ai_copilot">AI Copilot</span>', html)
        self.assertEqual(html.count('href="/ai_bot"'), 1)

    def test_pro_admin_copilot_links_to_upgrade_with_empire_lock(self):
        html = self.render('admin', locked=('ai_copilot',), lang='vi')
        self.assertIn('<span data-i18n="menu_ai_inbox">Hộp thư AI</span>', html)
        self.assertIn('href="/plan?feature=ai_copilot"', html)
        self.assertIn('LOCK-ai_copilot', html)
        self.assertNotIn('LOCK-ai_inbox', html)
        self.assertNotIn('href="/ai_bot#copilot"', html)

    def test_essential_inbox_shows_pro_lock(self):
        html = self.render('admin', locked=('ai_inbox', 'ai_copilot'))
        inbox = html.split('data-i18n="menu_ai_inbox"')[1].split('</a>')[0]
        self.assertIn('LOCK-ai_inbox', inbox)

    def test_staff_never_sees_copilot(self):
        html = self.render('staff')
        self.assertNotIn('data-i18n="menu_ai_copilot"', html)
        self.assertNotIn('#copilot', html)
        self.assertNotIn('feature=ai_copilot', html)
        self.assertNotIn('data-nav="ai-copilot"', html)
        self.assertNotIn('data-i18n="menu_ai_inbox"', html)      # nhân viên vốn không có mục hộp thư ở sidebar


if __name__ == '__main__':
    unittest.main(verbosity=2)
