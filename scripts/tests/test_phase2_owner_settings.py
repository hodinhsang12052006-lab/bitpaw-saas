# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 "owner settings": chủ quán tự đặt luật đặt chỗ mà AI lễ tân dùng, trên /settings/booking.
  - API /api/booking/reservation_settings/<table|karaoke|hotel> (booking_settings_routes.py): GET/POST đúng ngành, giới hạn
    được kẹp bởi reservations_core / reservations_hotel (không lặp kiểm tra), 3 lựa chọn tự xác nhận, lỗi 400 VI/EN, sai
    ngành / nhân viên / chưa đăng nhập bị từ chối, tự xác nhận khách sạn đi + về;
  - route nhân viên PATCH /api/hotel_reservations/<id> (app.py) xếp phòng qua reservations_hotel.assign_room (giữ phòng-đêm,
    cùng phiếu giữ với AI) — xếp lần 2 cùng phòng/đêm bị chặn, phiếu AI đang ghi dở được tôn trọng, mở lại đặt phòng đã
    huỷ kiểm lại phòng trống, huỷ / bỏ xếp phòng trả phiếu giữ;
  - 3 trang danh sách đặt chỗ của nhân viên trả trường source + hiện chip "AI" cho source == 'ai_bot', dòng chờ duyệt vẫn
    nổi bật; trang Cài đặt hiện đúng mục Đặt chỗ theo ngành.

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi mạng: mongo_client + requests được
thay TRƯỚC mọi import; decorator đăng nhập / phân quyền và các route của app.py lấy nguyên mã nguồn qua ast.

Chạy: python scripts/tests/test_phase2_owner_settings.py
"""
import ast
import copy
import io
import itertools
import os
import re
import sys
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from functools import wraps

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from pymongo import ReturnDocument  # noqa: E402  (chỉ hằng số, không kết nối)
from pymongo.errors import DuplicateKeyError  # noqa: E402


# ---------------------------------------------------------------- DB giả trong RAM (cùng khuôn test_phase2_hotel_pack.py,
# thêm $set theo đường dẫn 'a.b' như test_phase2_table_room_packs.py — save_reservation_settings ghi 'table_reservations.x')
def _get(doc, key):
    cur = doc
    for part in str(key).split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_path(doc, key, value):
    parts = key.split('.')
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


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
            _set_path(d, k, copy.deepcopy(v))
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

from flask import (Flask, flash, g, jsonify, redirect, request, session, url_for)  # noqa: E402
import jinja2  # noqa: E402

from i18n import resolve_lang  # noqa: E402


# ---------------------------------------------------------------- mã nguồn thật của app.py (không import app.py)
with io.open(os.path.join(ROOT, 'app.py'), encoding='utf-8') as _fh:
    APP_SRC = _fh.read()
APP_TREE = ast.parse(APP_SRC)


def app_functions(*names, strip_decorators=True):
    nodes = []
    for name in names:
        node = copy.deepcopy(next(n for n in APP_TREE.body if isinstance(n, ast.FunctionDef) and n.name == name))
        if strip_decorators:
            node.decorator_list = []
        nodes.append(node)
    return ast.Module(body=nodes, type_ignores=[])


def app_source(name):
    return ast.get_source_segment(APP_SRC, next(n for n in APP_TREE.body if isinstance(n, ast.FunctionDef) and n.name == name))


# Module 'app' giả cho blueprint: login_required / role_required / _wants_json / _vi_en là mã THẬT của app.py.
_auth_ns = {'wraps': wraps, 'session': session, 'jsonify': jsonify, 'request': request, 'g': g, 'flash': flash,
            'redirect': redirect, 'url_for': url_for, 'resolve_lang': resolve_lang}
exec(compile(app_functions('_vi_en', '_wants_json', 'login_required', 'role_required'), 'app.py', 'exec'), _auth_ns)
_fake_app = types.ModuleType('app')
_fake_app.login_required = _auth_ns['login_required']
_fake_app.role_required = _auth_ns['role_required']
_fake_app.limiter = types.SimpleNamespace(limit=lambda *a, **k: (lambda f: f))
sys.modules['app'] = _fake_app

import booking_rules  # noqa: E402
import reservations_core as rc  # noqa: E402
import reservations_hotel as rh  # noqa: E402
import booking_settings_routes as bsr  # noqa: E402

FLASK = Flask('owner_settings_test', template_folder=os.path.join(ROOT, 'templates'))
FLASK.secret_key = 'test-only'
FLASK.register_blueprint(bsr.booking_settings_bp)
FLASK.add_url_rule('/', 'index', lambda: 'home')
FLASK.add_url_rule('/login', 'login', lambda: 'login')

BID = 'biz-1'
HOURS = {'mon': ['11:00', '22:00'], 'tue': ['11:00', '22:00'], 'wed': ['11:00', '22:00'], 'thu': ['11:00', '22:00'],
         'fri': ['11:00', '23:00'], 'sat': ['11:00', '23:00'], 'sun': None}
URL = '/api/booking/reservation_settings/'


class Base(unittest.TestCase):
    industry = 'fnb'
    role = 'admin'

    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()
        self.client = FLASK.test_client()
        self.login(self.industry, self.role)

    def login(self, industry, role='admin', lang='en'):
        with self.client.session_transaction() as s:
            s.clear()
            s.update({'user_id': 'u-1', 'business_id': BID, 'role': role, 'business_mode': industry})
        self.client.set_cookie('bitpaw_lang', lang)

    def get(self, kind):
        r = self.client.get(URL + kind)
        return r.status_code, r.get_json()

    def post(self, kind, body):
        r = self.client.post(URL + kind, json=body)
        return r.status_code, r.get_json()

    def stored(self):
        return DB.booking_settings.find_one({'business_id': BID}, {'_id': 0}) or {}


# ================================================================ API luật đặt bàn (F&B)
class TableSettingsApi(Base):
    def test_get_defaults_are_honest(self):
        code, j = self.get('table')
        self.assertEqual(code, 200)
        self.assertTrue(j['success'])
        self.assertEqual(j['kind'], 'table')
        s = j['settings']
        self.assertEqual(set(s), set(rc._LIMITS['table']) | {'auto_confirm'})
        self.assertEqual((s['max_covers_per_slot'], s['slot_minutes'], s['auto_confirm']), (0, 30, 'follow'))
        self.assertEqual(j['limits']['max_covers_per_slot'], [0, 2000])
        self.assertEqual(j['capacity_model'], 'none')           # 0 khách / khung + bàn chưa có ghế -> chỉ nhận yêu cầu
        self.assertFalse(j['hours_published'])
        self.assertFalse(j['effective_auto_confirm'])
        self.assertIsNone(j['general_auto_confirm'])             # công tắc chung chưa từng lưu

    def test_post_saves_through_core_and_clamps(self):
        DB.booking_settings.insert_one({'business_id': BID, 'hours': HOURS, 'auto_confirm': True, 'info': {'parking': 'Street'}})
        code, j = self.post('table', {'max_covers_per_slot': 5000, 'slot_minutes': 20, 'max_party': 0, 'max_party_auto': '8',
                                      'dining_minutes': 10, 'last_booking_before_close': 999, 'hold_minutes': -5,
                                      'auto_confirm': 'never', 'unknown': 1})
        self.assertEqual(code, 200, j)
        s = j['settings']
        self.assertEqual((s['max_covers_per_slot'], s['slot_minutes'], s['max_party'], s['max_party_auto'], s['dining_minutes'],
                          s['last_booking_before_close'], s['hold_minutes'], s['auto_confirm']),
                         (2000, 30, 1, 8, 30, 240, 0, 'never'))
        doc = self.stored()
        self.assertEqual(doc['hours'], HOURS)                    # Cài đặt đặt lịch chung không bị ghi đè
        self.assertEqual(doc['info'], {'parking': 'Street'})
        self.assertIs(doc['table_reservations']['auto_confirm'], False)
        self.assertNotIn('unknown', doc['table_reservations'])
        self.assertEqual(rc.load_rules(BID, 'table')['max_covers_per_slot'], 2000)   # AI đọc đúng giá trị đã lưu
        self.assertEqual((j['capacity_model'], j['hours_published'], j['effective_auto_confirm']), ('covers', True, False))

    def test_auto_confirm_tri_state(self):
        DB.booking_settings.insert_one({'business_id': BID, 'hours': HOURS, 'auto_confirm': True,
                                        rc.GENERAL_SAVED_MARK: '2026-10-20T09:00:00'})   # công tắc chung chủ đã lưu ở trang mới
        for mode, stored, effective in (('always', True, True), ('never', False, False), ('follow', None, True)):
            code, j = self.post('table', {'auto_confirm': mode})
            self.assertEqual(code, 200)
            self.assertEqual(j['settings']['auto_confirm'], mode)
            self.assertEqual(self.stored()['table_reservations']['auto_confirm'], stored)
            self.assertEqual(j['effective_auto_confirm'], effective)
            self.assertIs(rc.load_rules(BID, 'table')['auto_confirm'], effective)
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'auto_confirm': False}})   # công tắc chung tắt
        self.assertFalse(self.get('table')[1]['effective_auto_confirm'])
        code, j = self.post('table', {'auto_confirm': 'sometimes'})
        self.assertEqual(code, 400)
        self.assertIn('follow the general switch', j['message'])
        code, j = self.post('table', {'auto_confirm': ['always']})
        self.assertEqual(code, 400)

    def test_partial_post_keeps_other_fields(self):
        self.post('table', {'max_covers_per_slot': 40, 'hold_minutes': 15})
        code, j = self.post('table', {'max_party': 12, 'hold_minutes': ''})   # ô trống -> giữ giá trị cũ
        self.assertEqual((j['settings']['max_covers_per_slot'], j['settings']['hold_minutes'], j['settings']['max_party']),
                         (40, 15, 12))

    def test_seated_tables_count_as_capacity(self):
        DB.dining_tables.insert_many([{'id': 1, 'business_id': BID, 'name': 'T1', 'seats': 4},
                                      {'id': 2, 'business_id': BID, 'name': 'T2'}])
        code, j = self.get('table')
        self.assertEqual((j['tables_with_seats'], j['capacity_model']), (1, 'tables'))

    def test_bad_number_is_400_in_both_languages(self):
        code, j = self.post('table', {'max_party': 'lots'})
        self.assertEqual(code, 400)
        self.assertEqual(j['message'], 'Largest party online: must be a number.')
        self.login('fnb', lang='vi')
        code, j = self.post('table', {'max_party': 'lots'})
        self.assertEqual(code, 400)
        self.assertEqual(j['message'], 'Nhóm lớn nhất đặt online: phải là một con số.')
        self.assertNotIn('table_reservations', self.stored())
        code, j = self.post('table', ['not', 'a', 'dict'])
        self.assertEqual(code, 400)
        self.assertEqual(j['message'], 'Dữ liệu không hợp lệ.')

    def test_save_clears_booking_rules_cache(self):
        booking_rules._CACHE[('rules', BID)] = (9e18, {'stale': True})
        self.post('table', {'max_party': 10})
        self.assertNotIn(('rules', BID), booking_rules._CACHE)


# ================================================================ API luật đặt phòng theo giờ (Karaoke)
class KaraokeSettingsApi(Base):
    industry = 'karaoke'

    def test_get_and_post_clamped(self):
        code, j = self.get('karaoke')
        self.assertEqual(code, 200)
        self.assertEqual(set(j['settings']), set(rc._LIMITS['karaoke']) | {'auto_confirm'})
        self.assertEqual((j['settings']['min_hours'], j['settings']['max_hours'], j['settings']['in_use_buffer_hours']),
                         (0.5, 12.0, 2.0))
        self.assertNotIn('capacity_model', j)
        code, j = self.post('karaoke', {'min_hours': 0.1, 'max_hours': 20, 'max_party': 500, 'hold_minutes': 15,
                                        'in_use_buffer_hours': 1.5, 'auto_confirm': 'always'})
        self.assertEqual(code, 200, j)
        s = j['settings']
        self.assertEqual((s['min_hours'], s['max_hours'], s['max_party'], s['hold_minutes'], s['in_use_buffer_hours'],
                          s['auto_confirm']), (0.5, 12.0, 200, 15, 1.5, 'always'))
        self.assertTrue(j['effective_auto_confirm'])
        self.assertFalse(j['hours_published'])       # chưa lưu giờ mở cửa -> AI vẫn chỉ nhận yêu cầu (karaoke_status_for)
        self.assertEqual(rc.karaoke_status_for(rc.load_rules(BID, 'karaoke')), ('pending', 'hours_not_published'))
        DB.booking_settings.update_one({'business_id': BID}, {'$set': {'hours': HOURS}})
        self.assertEqual(rc.karaoke_status_for(rc.load_rules(BID, 'karaoke')), ('confirmed', None))

    def test_min_above_max_is_resolved_by_core(self):
        code, j = self.post('karaoke', {'min_hours': 4, 'max_hours': 2})
        self.assertEqual(code, 200)
        self.assertEqual((j['settings']['min_hours'], j['settings']['max_hours']), (4.0, 4.0))

    def test_bad_value_message(self):
        code, j = self.post('karaoke', {'in_use_buffer_hours': 'soon'})
        self.assertEqual((code, j['message']), (400, 'Buffer while a room is in use: must be a number.'))


# ================================================================ API cài đặt khách sạn
class HotelSettingsApi(Base):
    industry = 'hotel'

    def test_defaults_and_auto_confirm_round_trip(self):
        code, j = self.get('hotel')
        self.assertEqual(code, 200)
        self.assertEqual(j['settings'], rh.SETTINGS_DEFAULTS)
        self.assertFalse(j['settings']['auto_confirm'])          # mặc định an toàn: chờ khách sạn duyệt
        self.assertEqual(j['limits'], {'min_nights': [1, rh.MAX_NIGHTS], 'free_cancel_hours': [0, 1440]})
        body = {'auto_confirm': True, 'min_nights': 2, 'checkin_time': '14:00', 'checkout_time': '11:00', 'free_cancel_hours': 48}
        code, j = self.post('hotel', body)
        self.assertEqual(code, 200, j)
        self.assertEqual(j['settings'], body)
        self.assertEqual(self.get('hotel')[1]['settings'], body)
        self.assertEqual(rh.hotel_settings(BID), body)            # đúng chỗ AI khách sạn đọc
        self.assertEqual(self.stored()['hotel'], body)
        code, j = self.post('hotel', {'auto_confirm': False})     # chỉ gửi 1 ô -> các ô khác giữ nguyên
        self.assertEqual(j['settings'], dict(body, auto_confirm=False))
        self.assertFalse(rh.hotel_settings(BID)['auto_confirm'])

    def test_clamp_and_clear(self):
        code, j = self.post('hotel', {'min_nights': 500, 'free_cancel_hours': 99999, 'checkin_time': '2:00'})
        self.assertEqual((j['settings']['min_nights'], j['settings']['free_cancel_hours'], j['settings']['checkin_time']),
                         (rh.MAX_NIGHTS, 1440, '02:00'))
        code, j = self.post('hotel', {'free_cancel_hours': None, 'checkin_time': None, 'min_nights': None})
        self.assertEqual((j['settings']['free_cancel_hours'], j['settings']['checkin_time'], j['settings']['min_nights']),
                         (None, None, 1))

    def test_bad_time_is_400_vi_en_and_nothing_saved(self):
        self.post('hotel', {'checkin_time': '14:00'})
        code, j = self.post('hotel', {'checkin_time': '2pm'})
        self.assertEqual(code, 400)
        self.assertEqual(j['message'], "'2pm' is not a valid time (use HH:MM, 24-hour).")
        self.login('hotel', lang='vi')
        code, j = self.post('hotel', {'checkout_time': '25:00'})
        self.assertEqual((code, j['message']), (400, "'25:00' không phải giờ hợp lệ (dạng HH:MM, 24 giờ)."))
        code, j = self.post('hotel', {'min_nights': 'two'})
        self.assertEqual((code, j['message']), (400, 'min_nights phải là số.'))
        self.assertEqual(rh.hotel_settings(BID)['checkin_time'], '14:00')


# ================================================================ ai được dùng API
class Access(Base):
    def test_wrong_industry_is_refused(self):
        for industry, kind in (('fnb', 'karaoke'), ('fnb', 'hotel'), ('karaoke', 'table'), ('hotel', 'table'),
                               ('nail', 'table'), ('spa', 'hotel'), ('retail', 'karaoke'), ('', 'table')):
            self.login(industry)
            code, j = self.get(kind)
            self.assertEqual(code, 403, (industry, kind))
            self.assertEqual(j['message'], 'These reservation rules do not apply to your type of business.')
            code, j = self.post(kind, {'max_party': 5, 'auto_confirm': True})
            self.assertEqual(code, 403, (industry, kind))
        self.assertEqual(DB.booking_settings.count_documents({}), 0)
        self.login('nail', lang='vi')
        self.assertEqual(self.get('table')[1]['message'], 'Mục đặt chỗ này không dùng cho ngành của tiệm bạn.')

    def test_unknown_kind_404(self):
        code, j = self.get('spaceship')
        self.assertEqual(code, 404)

    def test_staff_gets_403(self):
        for industry, kind in (('fnb', 'table'), ('karaoke', 'karaoke'), ('hotel', 'hotel')):
            self.login(industry, role='staff')
            self.assertEqual(self.get(kind)[0], 403)
            code, j = self.post(kind, {'auto_confirm': True})
            self.assertEqual(code, 403)
            self.assertFalse(j['success'])
        self.assertEqual(DB.booking_settings.count_documents({}), 0)

    def test_super_admin_allowed_and_anonymous_401(self):
        self.login('hotel', role='super_admin')
        self.assertEqual(self.get('hotel')[0], 200)
        with self.client.session_transaction() as s:
            s.clear()
        self.assertEqual(self.get('hotel')[0], 401)


# ================================================================ route nhân viên xếp phòng khách sạn (app.py)
NOW = datetime(2026, 11, 2, 10, 0)


def D(days):
    return (NOW.date() + timedelta(days=days)).isoformat()


def room(rid, number, rtype, price, cap=2):
    return {'id': rid, 'business_id': BID, 'room_number': number, 'room_type': rtype, 'price_per_night': price,
            'capacity': cap, 'status': 'Trống'}


def resv(rid, ci, co, room_id=None, room_type='Standard', status='pending', **kw):
    d = {'id': rid, 'business_id': BID, 'guest_name': 'Guest', 'guest_phone': '0400000000', 'party_size': 2,
         'checkin_date': ci, 'checkout_date': co, 'room_type': room_type, 'room_id': room_id, 'note': None,
         'status': status, 'created_at': '2026-10-01T10:00:00'}
    d.update(kw)
    return d


class HotelStaffPatch(unittest.TestCase):
    def setUp(self):
        DB.reset()
        DB.hotel_rooms.insert_many([room(1, '101', 'Standard', 100), room(2, '102', 'Standard', 110),
                                    room(3, '201', 'Deluxe', 150, cap=3)])
        self.req = types.SimpleNamespace(json=None)
        self.lang = 'en'
        ns = {'db': DB, 'session': {'business_id': BID, 'user_id': 'u-1'}, 'request': self.req, 'jsonify': lambda d: d,
              '_vi_en': lambda vi, en: vi if self.lang == 'vi' else en}
        exec(compile(app_functions('api_hotel_reservation_update', '_hotel_request_has_room'), 'app.py', 'exec'), ns)
        self.route = ns['api_hotel_reservation_update']

    def patch(self, rid, body):
        self.req.json = body
        out = self.route(rid)
        return (out, 200) if isinstance(out, dict) else out

    def doc(self, rid):
        return DB.hotel_reservations.find_one({'id': rid}, {'_id': 0})

    def claims(self, rid=None):
        return sorted((c['room_id'], c['night']) for c in DB.hotel_room_nights.docs
                      if rid is None or c['reservation_id'] == rid)

    def test_route_uses_assign_room_not_bare_overlap_check(self):
        body = app_source('api_hotel_reservation_update')
        self.assertIn('reservations_hotel.assign_room(', body)
        self.assertNotIn('_hotel_reservation_overlaps(', body)

    def test_assign_holds_room_nights_and_second_assign_fails(self):
        DB.hotel_reservations.insert_many([resv(10, D(8), D(10)), resv(11, D(9), D(11))])
        self.assertEqual(self.patch(10, {'room_id': 1}), ({'success': True}, 200))
        self.assertEqual(self.doc(10)['room_id'], 1)
        self.assertEqual(self.claims(10), [(1, D(8)), (1, D(9))])
        out, code = self.patch(11, {'room_id': 1})
        self.assertEqual((code, out), (409, {'success': False, 'message': 'Phòng này đã có khách khác đặt trùng khoảng ngày này.'}))
        self.assertIsNone(self.doc(11)['room_id'])
        self.assertEqual(self.claims(11), [])
        self.assertEqual(self.patch(11, {'room_id': 2}), ({'success': True}, 200))
        # đổi phòng: phiếu phòng cũ được trả, phiếu phòng mới giữ đủ đêm
        self.assertEqual(self.patch(10, {'room_id': 3}), ({'success': True}, 200))
        self.assertEqual(self.claims(10), [(3, D(8)), (3, D(9))])
        self.assertEqual(self.patch(11, {'room_id': 1}), ({'success': True}, 200))

    def test_in_flight_ai_claim_blocks_staff_assign(self):
        # AI vừa giữ phòng 101 đêm D(9) (đặt phòng chưa kịp ghi) -> màn nhân viên không được xếp đè (route cũ thì được)
        DB.hotel_room_nights.insert_one({'_id': f'{BID}|1|{D(9)}', 'business_id': BID, 'room_id': 1, 'night': D(9),
                                         'reservation_id': 99999, 'claimed_at': datetime.now(timezone.utc).isoformat()})
        DB.hotel_reservations.insert_one(resv(12, D(8), D(10)))
        out, code = self.patch(12, {'room_id': 1})
        self.assertEqual(code, 409)
        self.assertIsNone(self.doc(12)['room_id'])
        self.assertEqual(self.claims(12), [])

    def test_staff_assign_in_progress_is_not_stolen_by_ai(self):
        # Nhân viên đang xếp phòng 101 cho #13 (phiếu đã giữ, room_id chưa ghi): AI đặt phòng Standard cùng đêm phải lấy 102
        # (trước đây phiếu của đặt phòng còn sống nhưng chưa ghi room_id bị coi là phiếu cũ -> AI lấy mất phòng 101).
        DB.hotel_reservations.insert_one(resv(13, D(8), D(10), room_type='Deluxe', status='confirmed'))
        stamp = datetime.now(timezone.utc).isoformat()
        for n in (D(8), D(9)):
            DB.hotel_room_nights.insert_one({'_id': f'{BID}|1|{n}', 'business_id': BID, 'room_id': 1, 'night': n,
                                             'reservation_id': 13, 'claimed_at': stamp})
        doc, _av = rh.create_hold(BID, checkin=D(8), checkout=D(10), guests=1, room_type_key='standard', guest_name='AI Guest',
                                  guest_phone='0412345678', status='pending', extra={'source': 'ai_bot'})
        self.assertEqual(doc['room_id'], 2)
        self.assertEqual({c['reservation_id'] for c in DB.hotel_room_nights.docs if c['room_id'] == 1}, {13})

    def test_assign_room_rechecks_after_writing(self):
        # Một lượt ghi KHÔNG giữ phiếu chen vào giữa kiểm trùng và ghi: assign_room kiểm lại sau khi ghi và trả phòng cũ.
        DB.hotel_reservations.insert_many([resv(14, D(8), D(10)), resv(15, D(9), D(10), room_id=1, status='confirmed')])
        real, calls = rh.overlaps, {'n': 0}

        def late_writer(*a, **kw):
            calls['n'] += 1
            return False if calls['n'] == 1 else real(*a, **kw)
        rh.overlaps = late_writer
        try:
            self.assertFalse(rh.assign_room(BID, self.doc(14), 1))
        finally:
            rh.overlaps = real
        self.assertIsNone(self.doc(14)['room_id'])
        self.assertEqual(self.claims(14), [])

    def test_ai_cannot_book_a_room_staff_assigned(self):
        DB.hotel_reservations.insert_one(resv(16, D(8), D(10), room_type='Deluxe'))
        self.assertEqual(self.patch(16, {'room_id': 3, 'status': 'confirmed'}), ({'success': True}, 200))
        self.assertEqual(self.doc(16)['status'], 'confirmed')
        doc, av = rh.create_hold(BID, checkin=D(9), checkout=D(11), guests=1, room_type_key='deluxe', guest_name='AI Guest',
                                 guest_phone='0412345678', status='pending')
        self.assertIsNone(doc)
        self.assertEqual(next(t for t in av['types'] if t['key'] == 'deluxe')['reason'], 'sold_out')

    def test_cancel_and_unassign_release_holds(self):
        DB.hotel_reservations.insert_many([resv(17, D(8), D(10)), resv(18, D(8), D(10))])
        self.patch(17, {'room_id': 1})
        self.patch(18, {'room_id': 2})
        self.assertEqual(self.patch(17, {'status': 'cancelled'}), ({'success': True}, 200))
        self.assertEqual(self.claims(17), [])
        self.assertEqual(self.patch(18, {'room_id': None}), ({'success': True}, 200))
        self.assertEqual(self.claims(18), [])
        self.assertEqual(DB.hotel_room_nights.count_documents({}), 0)

    def test_reopening_cancelled_booking_rechecks_its_room(self):
        DB.hotel_reservations.insert_one(resv(20, D(8), D(10), room_type='Deluxe'))
        self.patch(20, {'room_id': 3, 'status': 'confirmed'})
        self.patch(20, {'status': 'cancelled'})
        # sau khi huỷ, AI bán phòng 201 cho khách khác đêm D(9)
        other, _ = rh.create_hold(BID, checkin=D(9), checkout=D(10), guests=1, room_type_key='deluxe', guest_name='New Guest',
                                  guest_phone='0499999999', status='confirmed')
        self.assertEqual(other['room_id'], 3)
        out, code = self.patch(20, {'status': 'confirmed', 'reopen': True})   # mở lại có chủ đích
        self.assertEqual((code, out['message']), (409, 'Phòng này đã có khách khác đặt trùng khoảng ngày này.'))
        self.assertEqual(self.doc(20)['status'], 'cancelled')        # không mở lại, không xếp trùng
        self.assertEqual(self.claims(20), [])
        rh.cancel(BID, other['id'], by='guest')
        self.assertEqual(self.patch(20, {'status': 'confirmed', 'reopen': True}), ({'success': True}, 200))
        self.assertEqual((self.doc(20)['status'], self.doc(20)['room_id']), ('confirmed', 3))
        self.assertEqual(self.claims(20), [(3, D(8)), (3, D(9))])  # mở lại = giữ lại phòng-đêm

    def test_reopening_unassigned_request_rechecks_availability(self):
        DB.hotel_reservations.insert_one(resv(30, D(8), D(10), room_type='Deluxe', status='cancelled'))
        DB.hotel_reservations.insert_one(resv(31, D(9), D(10), room_type='Deluxe', room_id=3, status='confirmed'))
        out, code = self.patch(30, {'status': 'pending', 'reopen': True})
        self.assertEqual(code, 409)
        self.assertEqual(out['message'], 'No room is free for these dates any more, so the booking was not reopened — '
                                         'change the dates or assign another room.')
        self.lang = 'vi'
        self.assertIn('Không còn phòng trống', self.patch(30, {'status': 'pending', 'reopen': True})[0]['message'])
        self.assertEqual(self.doc(30)['status'], 'cancelled')
        # Chủ xếp luôn 1 phòng còn trống khi mở lại -> được (kiểm theo đúng phòng đó)
        self.assertEqual(self.patch(30, {'status': 'pending', 'room_id': 1, 'reopen': True}), ({'success': True}, 200))
        self.assertEqual((self.doc(30)['status'], self.doc(30)['room_id']), ('pending', 1))
        DB.hotel_reservations.insert_one(resv(32, D(20), D(21), room_type='Deluxe', status='cancelled'))
        self.assertEqual(self.patch(32, {'status': 'pending', 'reopen': True}), ({'success': True}, 200))

    def test_unchanged_messages_and_shape(self):
        self.assertEqual(self.patch(404, {'status': 'confirmed'}),
                         ({'success': False, 'message': 'Không tìm thấy yêu cầu đặt phòng.'}, 404))
        DB.hotel_reservations.insert_one(resv(40, D(8), D(10)))
        self.assertEqual(self.patch(40, {'status': 'seated'}), ({'success': False, 'message': 'Trạng thái không hợp lệ.'}, 400))
        self.assertEqual(self.patch(40, {'room_id': 77}), ({'success': False, 'message': 'Phòng không tồn tại.'}, 404))
        self.assertEqual(self.patch(40, {}), ({'success': False, 'message': 'Không có gì để cập nhật.'}, 400))
        self.assertEqual(self.patch(40, {'status': 'confirmed'}), ({'success': True}, 200))


# ================================================================ danh sách đặt chỗ của nhân viên: source + chip AI
class _Loader(jinja2.FileSystemLoader):
    def get_source(self, environment, template):
        if template.startswith('components/'):
            return '', None, lambda: True   # sidebar cần cả trăm biến ngữ cảnh — không phải đối tượng test
        return super().get_source(environment, template)


JINJA = jinja2.Environment(loader=_Loader(os.path.join(ROOT, 'templates')))
JINJA.globals['url_for'] = lambda *a, **k: '/x'


def render(name, **ctx):
    base = {'session': {'business_id': BID, 'role': 'admin'}, 'default_lang': 'en', 'active_industry_code': 'fnb'}
    base.update(ctx)
    return JINJA.get_template(name).render(**base)


class StaffLists(unittest.TestCase):
    def setUp(self):
        DB.reset()

    def run_page(self, name):
        captured = {}
        ns = {'db': DB, 'session': {'business_id': BID, 'user_id': 'u-1'}, 'datetime': datetime,
              'request': types.SimpleNamespace(args={}), 'tenant_today': lambda bid: date(2026, 10, 30),
              'flash': lambda *a, **k: None, 'url_for': lambda *a, **k: 'https://example.test/reserve',
              'render_template': lambda tpl, **ctx: captured.update(ctx, _tpl=tpl) or 'html'}
        exec(compile(app_functions(name), 'app.py', 'exec'), ns)
        ns[name]()
        return captured

    def test_list_pages_return_source(self):
        DB.table_reservations.insert_many([
            {'id': 1, 'business_id': BID, 'customer_name': 'Mia', 'party_size': 2, 'reserved_time': '2026-10-30T19:00:00',
             'status': 'pending', 'source': 'ai_bot', 'table_id': None},
            {'id': 2, 'business_id': BID, 'customer_name': 'Leo', 'party_size': 4, 'reserved_time': '2026-10-30T20:00:00',
             'status': 'confirmed', 'source': 'web', 'table_id': None}])
        DB.karaoke_room_reservations.insert_one({'id': 3, 'business_id': BID, 'customer_name': 'Kai', 'party_size': 5,
                                                 'reserved_time': '2026-10-30T21:00:00', 'duration_hours': 2,
                                                 'status': 'confirmed', 'source': 'ai_bot', 'room_id': None})
        DB.hotel_reservations.insert_one(resv(4, '2026-11-01', '2026-11-03', status='pending', source='ai_bot'))
        for page, tpl, ids in (('reservations_page', 'reservations.html', {1: 'ai_bot', 2: 'web'}),
                               ('karaoke_reservations_page', 'karaoke_reservations.html', {3: 'ai_bot'}),
                               ('hotel_reservations_page', 'hotel_reservations.html', {4: 'ai_bot'})):
            ctx = self.run_page(page)
            self.assertEqual(ctx['_tpl'], tpl)
            self.assertEqual({r['id']: r.get('source') for r in ctx['reservations']}, ids, page)

    def test_ai_chip_and_pending_row(self):
        rows = [{'id': 1, 'reserved_time': '2026-10-30T19:00:00', 'customer_name': 'Mia', 'party_size': 2, 'status': 'pending',
                 'source': 'ai_bot'},
                {'id': 2, 'reserved_time': '2026-10-30T20:00:00', 'customer_name': 'Leo', 'party_size': 2, 'status': 'confirmed',
                 'source': 'web'},
                {'id': 5, 'reserved_time': '2026-10-30T21:00:00', 'customer_name': 'Ivy', 'party_size': 2, 'status': 'confirmed'}]
        hrows = [{'id': 1, 'checkin_date': '2026-11-01', 'checkout_date': '2026-11-03', 'guest_name': 'Mia', 'party_size': 2,
                  'status': 'pending', 'source': 'ai_bot'},
                 {'id': 2, 'checkin_date': '2026-11-01', 'checkout_date': '2026-11-03', 'guest_name': 'Leo', 'party_size': 2,
                  'status': 'confirmed', 'source': 'web'}]
        pages = (('reservations.html', dict(reservations=rows, tables=[], selected_date='2026-10-30', reservation_link='x')),
                 ('karaoke_reservations.html', dict(reservations=rows, rooms=[], selected_date='2026-10-30', reservation_link='x')),
                 ('hotel_reservations.html', dict(reservations=hrows, rooms=[], today='2026-10-30', reservation_link='x')))
        for tpl, ctx in pages:
            for lang, title in (('en', 'Booked by the AI receptionist'), ('vi', 'AI lễ tân đặt')):
                html = render(tpl, default_lang=lang, **ctx)
                self.assertEqual(html.count('class="ai-chip"'), 1, tpl)          # chỉ dòng source == 'ai_bot'
                self.assertIn(f'title="{title}"', html)
                trs = dict(re.findall(r'<tr class="([^"]*)" data-res-id="(\d+)">', html)[i][::-1] for i in range(2))
                self.assertIn('is-pending', trs['1'], tpl)                       # dòng AI còn chờ duyệt vẫn nổi bật chờ duyệt
                self.assertNotIn('is-pending', trs['2'], tpl)
                self.assertIn("row.classList.toggle('is-pending', status === 'pending')", html)
                self.assertIn('href="/settings/booking#resv"', html)             # chủ quán tới được luật đặt chỗ
            staff = render(tpl, session={'business_id': BID, 'role': 'staff'}, **ctx)
            self.assertNotIn('/settings/booking#resv', staff)


# ================================================================ trang Cài đặt hiện đúng mục theo ngành
class SettingsPage(unittest.TestCase):
    def page(self, industry, lang='en'):
        return render('booking_settings.html', active_industry_code=industry, default_lang=lang)

    @staticmethod
    def section_attrs(html, icon):
        m = re.search(r'<section class="box"([^>]*)>\s*<h2><i class="fas ' + icon, html)
        return m.group(1) if m else None

    def test_table_section_for_fnb(self):
        html = self.page('fnb')
        self.assertIn('id="resv"', html)
        for k in ('max_covers_per_slot', 'slot_minutes', 'max_party', 'max_party_auto', 'dining_minutes',
                  'last_booking_before_close', 'hold_minutes', 'auto_confirm'):
            self.assertIn(f'data-rv="{k}"', html)
        self.assertIn('0 = no capacity set', html)
        self.assertIn('<option value="follow">', html)
        self.assertIn("const RK = \"table\";", html)
        self.assertIn('hidden', self.section_attrs(html, 'fa-stopwatch'))      # thời lượng dịch vụ Nails ẩn
        self.assertIn('hidden', self.section_attrs(html, 'fa-magnifying-glass'))
        self.assertNotIn('hidden', self.section_attrs(html, 'fa-sliders'))    # luật chung (đặt trước tối thiểu / tối đa) giữ
        self.assertNotIn('never more clients than technicians on shift', html)   # lời dẫn Nails không hiện cho nhà hàng
        self.assertIn('never more guests than the capacity you enter', html)
        self.assertIn('Reservation settings', html)
        vi = self.page('fnb', 'vi')
        self.assertIn('Thông tin quán cho khách và AI', vi)
        self.assertIn('Chờ quán duyệt', vi)

    def test_karaoke_and_hotel_sections(self):
        k = self.page('karaoke')
        for key in ('min_hours', 'max_hours', 'max_party', 'hold_minutes', 'in_use_buffer_hours', 'auto_confirm'):
            self.assertIn(f'data-rv="{key}"', k)
        self.assertNotIn('data-rv="max_covers_per_slot"', k)
        self.assertIn('set the closing time to 00:00', k)
        h = self.page('hotel')
        for key in ('auto_confirm', 'min_nights', 'checkin_time', 'checkout_time', 'free_cancel_hours'):
            self.assertIn(f'data-rv="{key}"', h)
        self.assertIn('Booking.com', h)
        self.assertIn('Airbnb', h)
        self.assertIn('hidden', self.section_attrs(h, 'fa-sliders'))           # luật chung không áp dụng cho khách sạn
        self.assertIn('Opening / front-desk hours', h)
        hv = self.page('hotel', 'vi')
        self.assertIn('Thông tin khách sạn cho khách và AI', hv)
        self.assertIn('Chờ khách sạn duyệt (an toàn)', hv)

    def test_nail_page_unchanged(self):
        html = self.page('nail')
        self.assertNotIn('id="resv"', html)
        self.assertNotIn('data-rv=', html.split('<script>', 1)[0])
        self.assertIsNone(re.search(r'<section class="box" hidden', html))
        self.assertIn('Booking settings', html)
        self.assertIn('const RK = "";', html)
        self.assertIn('never more clients than technicians on shift', html)

    def test_midnight_close_round_trips(self):
        # Giờ đóng 24:00 (đã có trong dữ liệu karaoke / lễ tân 24/7) phải hiện + lưu lại được (ô type=time không nhận 24:00)
        html = self.page('karaoke')
        self.assertIn("value=\"${v[1] === '24:00' ? '00:00' : v[1]}\"", html)
        self.assertIn("t[1].value === '00:00' ? '24:00' : t[1].value", html)
        rules = booking_rules.save_rules(BID, {'hours': {d: ['16:00', '24:00'] for d in booking_rules.DAY_KEYS}})
        self.assertEqual(rules['hours']['mon'], ['16:00', '24:00'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
