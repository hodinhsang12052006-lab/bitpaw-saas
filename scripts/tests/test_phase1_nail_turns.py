# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 1 "bảng xoay tua thợ Nails" (nail_turns.py + templates/nail_turns.html):
  1) thứ tự tua đúng bảng quy tắc: ít tua trước, bằng tua thì ai chờ lâu hơn; vé >= ngưỡng = tua đủ, dưới = nửa tua;
     khách request không tính + giữ chỗ; bỏ lượt xuống cuối nhóm; nghỉ giữ chỗ; thợ vào muộn đứng cuối hàng;
  2) thợ vào bảng từ chấm công THẬT (db.chamcong ngay_cham/gio_den theo giờ tiệm), chỉ thợ Nails, không ghi lặp;
  3) quyền: nhân viên chỉ xem (trừ khi chủ tiệm bật máy quầy), cài đặt chỉ admin, ngành khác bị chặn;
  4) giao ngoài lượt phải xác nhận + ghi nhật ký; 2 máy giao cùng lúc -> dòng sau tự huỷ;
  5) chốt giá bằng vé POS thật (order_items của thợ), hoàn tác = voided (không xoá), tổng kết cộng đúng từ từng dòng;
  6) tiền tệ + múi giờ của tiệm; template render được, JS inline hợp lệ; thẻ giá nail có dòng bảng tua, ngành khác không.

KHÔNG import app.py, KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi mạng: mongo_client/app/requests
được thay TRƯỚC mọi import. Chạy: python scripts/tests/test_phase1_nail_turns.py
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime
from functools import wraps
from itertools import count
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)


# ---------------------------------------------------------------- DB giả trong RAM
def _get(doc, key):
    cur = doc
    for part in key.split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


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
            if op in ('$gte', '$gt', '$lt', '$lte'):
                if v is None:
                    return False
                if (op == '$gte' and not v >= arg) or (op == '$gt' and not v > arg) or \
                        (op == '$lt' and not v < arg) or (op == '$lte' and not v <= arg):
                    return False
        return True
    return v == cond


def _matches(doc, flt):
    for k, cond in (flt or {}).items():
        if k == '$or':
            if not any(_matches(doc, f) for f in cond):
                return False
        elif not _match_value(_get(doc, k), cond):
            return False
    return True


class _Cursor(list):
    def sort(self, key, direction=1):
        if isinstance(key, list):
            key, direction = key[0]
        return _Cursor(sorted(self, key=lambda d: (d.get(key) is None, d.get(key) if d.get(key) is not None else ''),
                              reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self, name, log):
        self.name, self.docs, self.log = name, [], log

    def insert_one(self, doc):
        self.log.append((self.name, 'insert_one'))
        d = dict(doc)
        d.setdefault('_id', f'{self.name}-{len(self.docs) + 1}')
        self.docs.append(d)
        doc['_id'] = d['_id']
        return types.SimpleNamespace(inserted_id=d['_id'])

    def find(self, flt=None, projection=None):
        return _Cursor(dict(d) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = self.find(flt)
        if sort:
            rows = rows.sort(sort[0][0], sort[0][1])
        return dict(rows[0]) if rows else None

    def update_one(self, flt, update, upsert=False):
        self.log.append((self.name, 'update_one'))
        for d in self.docs:
            if _matches(d, flt):
                for k, v in (update.get('$set') or {}).items():
                    d[k] = v
                return types.SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            d = {k: v for k, v in flt.items() if not isinstance(v, dict)}
            d.update(update.get('$setOnInsert') or {})
            d.update(update.get('$set') or {})
            d['_id'] = f'{self.name}-{len(self.docs) + 1}'
            self.docs.append(d)
            return types.SimpleNamespace(matched_count=0, upserted_id=d['_id'])
        return types.SimpleNamespace(matched_count=0, upserted_id=None)

    def writes(self):
        return sum(1 for n, _ in self.log if n == self.name)


class FakeDB:
    def __init__(self):
        self._c, self.log = {}, []

    def __getattr__(self, name):
        if name.startswith('_') or name == 'log':
            raise AttributeError(name)
        if name not in self._c:
            self._c[name] = FakeCollection(name, self.log)
        return self._c[name]

    def reset(self):
        self._c.clear()
        self.log.clear()


DB = FakeDB()
_ids = count(1)
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED')


class _NoNetwork(types.ModuleType):
    def __getattr__(self, name):
        raise AssertionError(f'network module used in an offline test: requests.{name}')


sys.modules['requests'] = _NoNetwork('requests')

from flask import Flask, jsonify, session  # noqa: E402


def _login_required(f):
    @wraps(f)
    def inner(*a, **k):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Please sign in to continue.'}), 401
        return f(*a, **k)
    return inner


_app_stub = types.ModuleType('app')
_app_stub.login_required = _login_required
sys.modules['app'] = _app_stub

import nail_turns as nt  # noqa: E402
import plans  # noqa: E402

BIZ = 'shop-nail-1'
DAY = '2026-10-26'
S_USD = dict(nt.default_settings('USD'), currency='USD')


def ev(i, typ, ma, at, **kw):
    return dict({'id': i, 'type': typ, 'ma_nv': ma, 'name': ma, 'at': f'{DAY}T{at}:00', 'voided': False}, **kw)


class Seq:
    """Dựng nhật ký như quầy bấm: mỗi thao tác 1 dòng, giờ tăng dần."""

    def __init__(self, settings=S_USD):
        self.events, self.i, self.min, self.s = [], 0, 0, settings
        self.open = {}

    def _at(self):
        self.min += 1
        return f'{9 + self.min // 60:02d}:{self.min % 60:02d}'

    def add(self, typ, ma, **kw):
        self.i += 1
        e = ev(self.i, typ, ma, self._at(), **kw)
        self.events.append(e)
        return e

    def client(self, ma, amount, kind='walk_in'):
        v, p = nt.turn_value(kind, amount, self.s)
        t = self.add('turn', ma, kind=kind, amount=amount, value=v, provisional=p)
        self.add('done', ma, turn_id=t['id'])
        return t

    def order(self):
        return [m['ma_nv'] for m in nt.line_order(nt.fold(self.events)[0])]

    def next(self):
        return nt.next_up(nt.fold(self.events)[0])


# ================================================================ 1. quy tắc thứ tự tua (hàm thuần)
class TurnOrderSpec(unittest.TestCase):
    def test_spec_table_half_full_and_request(self):
        """3 thợ, vé $20 (nửa tua), $45 (tua đủ), khách request (không tính) -> thứ tự đúng bảng."""
        q = Seq()
        for ma in ('A', 'B', 'C'):
            q.add('join', ma, source='attendance')
        steps = [
            (None, None, None, ['A', 'B', 'C']),
            ('A', 20, 'walk_in', ['B', 'C', 'A']),      # $20 < $30 -> nửa tua: A 0.5
            ('B', 45, 'walk_in', ['C', 'A', 'B']),      # $45 -> tua đủ: B 1
            ('A', 60, 'request', ['C', 'A', 'B']),      # request: A không tính, giữ chỗ
            ('C', 35, 'walk_in', ['A', 'B', 'C']),      # C 1, xong sau B -> sau B
            ('A', 25, 'walk_in', ['B', 'C', 'A']),      # A 0.5 + 0.5 = 1, vừa xong -> cuối nhóm 1 tua
        ]
        for ma, amt, kind, expect in steps:
            if ma:
                q.client(ma, amt, kind)
            self.assertEqual(q.order(), expect, (ma, amt, kind))
            self.assertEqual(q.next(), expect[0])
        members = nt.fold(q.events)[0]
        self.assertEqual({k: m['turns'] for k, m in members.items()}, {'A': 1.0, 'B': 1.0, 'C': 1.0})

    def test_threshold_is_inclusive_and_unknown_price_is_provisional_full(self):
        self.assertEqual(nt.turn_value('walk_in', 30.0, S_USD), (1.0, False))
        self.assertEqual(nt.turn_value('walk_in', 29.99, S_USD), (0.5, False))
        self.assertEqual(nt.turn_value('walk_in', None, S_USD), (1.0, True))
        s = dict(S_USD, appointment_counts='none', request_counts='half')
        self.assertEqual(nt.turn_value('appointment', 80, s), (0.0, False))
        self.assertEqual(nt.turn_value('request', 80, s), (0.5, False))
        self.assertEqual(nt.turn_value('appointment', 80, S_USD), (1.0, False))   # mặc định: như walk-in

    def test_busy_and_break_are_never_next_but_keep_their_place(self):
        q = Seq()
        for ma in ('A', 'B', 'C'):
            q.add('join', ma)
        t = q.add('turn', 'A', kind='request', amount=50, value=0.0, provisional=False)
        self.assertEqual(q.next(), 'B')                 # A đang làm khách request
        q.add('break', 'B')
        self.assertEqual(q.next(), 'C')                 # B nghỉ
        q.add('done', 'A', turn_id=t['id'])
        self.assertEqual(q.next(), 'A')                 # request không tính: A về đúng chỗ đầu hàng
        q.add('back', 'B')
        self.assertEqual(q.order(), ['A', 'B', 'C'])    # nghỉ xong: B giữ chỗ cũ

    def test_skip_moves_behind_same_count_with_optional_penalty(self):
        q = Seq()
        for ma in ('A', 'B', 'C'):
            q.add('join', ma)
        q.client('C', 45)
        q.add('skip', 'A', value=0.0)
        self.assertEqual(q.order(), ['B', 'A', 'C'])    # A sau B (cùng 0 tua), vẫn trước C (1 tua)
        q2 = Seq()
        for ma in ('A', 'B'):
            q2.add('join', ma)
        q2.add('skip', 'A', value=1.0)                 # cài đặt phạt 1 tua
        self.assertEqual(nt.fold(q2.events)[0]['A']['turns'], 1.0)

    def test_late_arrival_joins_end_of_line_without_catching_up(self):
        q = Seq()
        for ma in ('A', 'B'):
            q.add('join', ma)
        q.client('A', 45)
        q.client('B', 45)
        q.client('A', 45)                              # A 2, B 1
        q.add('join', 'D')                             # vào muộn: bắt đầu bằng tua thấp nhất (1)
        members = nt.fold(q.events)[0]
        self.assertEqual(members['D']['turns'], 1.0)
        self.assertEqual(q.order(), ['B', 'D', 'A'])
        q.client('B', 45)
        self.assertEqual(q.next(), 'D')
        q.client('D', 45)
        self.assertNotEqual(q.next(), 'D')             # không nhận liền 2 khách để "đuổi kịp"

    def test_voided_entries_are_ignored_and_leave_rejoin(self):
        q = Seq()
        for ma in ('A', 'B'):
            q.add('join', ma)
        t = q.add('turn', 'A', kind='walk_in', amount=45, value=1.0, provisional=False)
        t['voided'] = True
        self.assertEqual(q.next(), 'A')
        q.add('leave', 'A')
        self.assertEqual(q.order(), ['B'])
        q.client('B', 45)
        q.add('join', 'A')                             # quay lại: không thấp hơn tua thấp nhất đang làm
        self.assertEqual(nt.fold(q.events)[0]['A']['turns'], 1.0)


# ================================================================ 2-6. route (Flask test client, DB giả)
class _Clock:
    local = datetime(2026, 10, 26, 10, 0, 0)
    server = datetime(2026, 10, 26, 10, 0, 0)


class RouteTests(unittest.TestCase):
    def setUp(self):
        DB.reset()
        nt._CACHE.clear()
        _Clock.local = datetime(2026, 10, 26, 10, 0, 0)
        _Clock.server = datetime(2026, 10, 26, 10, 0, 0)
        self.p1 = patch.object(nt, '_local_now', lambda bid: _Clock.local)
        self.p2 = patch.object(nt, '_server_now', lambda: _Clock.server)
        self.p1.start()
        self.p2.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)
        DB.businesses.docs.append({'id': BIZ, 'name': 'Lily Nails', 'country': 'US', 'currency': 'USD'})
        for ma, name, dept in (('NV1', 'Anna', 'Nails'), ('NV2', 'Bao', 'Nails'), ('NV3', 'Chi', 'Nails'), ('NV9', 'Desk Dana', 'Lễ tân')):
            DB.employees.docs.append({'business_id': BIZ, 'ma_nv': ma, 'ho_ten': name, 'linh_vuc': dept})
        DB.employees.docs.append({'business_id': 'other-shop', 'ma_nv': 'NV1', 'ho_ten': 'Other', 'linh_vuc': 'Nails'})
        for ma, t in (('NV2', '09:05'), ('NV1', '08:58'), ('NV9', '08:30')):
            DB.chamcong.docs.append({'business_id': BIZ, 'ma_nv': ma, 'ngay_cham': '26/10/2026', 'gio_den': t, 'trang_thai': 'Có mặt'})
        DB.chamcong.docs.append({'business_id': BIZ, 'ma_nv': 'NV3', 'ngay_cham': '25/10/2026', 'gio_den': '09:00', 'trang_thai': 'Có mặt'})
        DB.chamcong.docs.append({'business_id': 'other-shop', 'ma_nv': 'NV3', 'ngay_cham': '26/10/2026', 'gio_den': '07:00', 'trang_thai': 'Có mặt'})
        DB.products.docs.append({'id': 501, 'business_id': BIZ, 'name': 'Gel manicure', 'price': 45, 'is_active': 1})
        DB.products.docs.append({'id': 502, 'business_id': BIZ, 'name': 'Polish change', 'price': 18, 'is_active': 1})
        self.app = Flask(__name__, template_folder=os.path.join(ROOT, 'templates'))
        self.app.secret_key = 'test'
        self.app.register_blueprint(nt.nail_turns_bp)
        self.c = self.app.test_client()

    def login(self, role='admin', mode='nail'):
        with self.c.session_transaction() as s:
            s.update({'user_id': BIZ, 'business_id': BIZ, 'role': role, 'business_mode': mode, 'user_email': f'{role}@lily.test'})

    def board(self, **q):
        r = self.c.get('/api/nail_turns/board', query_string=q)
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()

    def post(self, path, body, status=200):
        r = self.c.post(path, json=body)
        self.assertEqual(r.status_code, status, r.get_json())
        return r.get_json()

    # ---- 2. chấm công thật -> bảng
    def test_board_built_from_real_clock_ins_once_and_only_nail_techs(self):
        self.login('staff')
        b = self.board()
        self.assertEqual([m['name'] for m in b['line']], ['Anna', 'Bao'])         # theo giờ check-in 08:58, 09:05
        self.assertEqual(b['next_up'], 'NV1')
        self.assertEqual([m['ma_nv'] for m in b['not_on_board']], ['NV3'])        # Chi chưa check-in hôm nay
        everyone = {m['ma_nv'] for k in ('line', 'busy', 'on_break', 'gone', 'not_on_board') for m in b[k]}
        self.assertNotIn('NV9', everyone)                                          # lễ tân không xếp tua
        self.assertFalse(b['can_assign'])
        self.assertNotIn('services', b)
        joins = [d for d in DB.nail_turns.docs if d['type'] == 'join']
        self.assertEqual(len(joins), 2)
        self.assertTrue(all(d['source'] == 'attendance' and d['business_id'] == BIZ for d in joins))
        writes = DB.nail_turns.writes()
        self.board()
        self.assertEqual(DB.nail_turns.writes(), writes)                           # lần tải sau: không ghi gì

    def test_late_clock_in_is_not_inserted_before_recorded_history(self):
        self.login('admin')
        self.board()
        _Clock.local = datetime(2026, 10, 26, 10, 30)
        self.post('/api/nail_turns/assign', {'ma_nv': 'NV1', 'kind': 'walk_in', 'amount': 45})
        # Chi check-in lúc 09:00 nhưng bản ghi tới muộn (nhập sau 10:30) -> vào cuối hàng, không lên đầu
        DB.chamcong.docs.append({'business_id': BIZ, 'ma_nv': 'NV3', 'ngay_cham': '26/10/2026', 'gio_den': '09:00', 'trang_thai': 'Có mặt'})
        _Clock.local = datetime(2026, 10, 26, 10, 40)
        b = self.board()
        self.assertEqual([m['ma_nv'] for m in b['line']], ['NV2', 'NV3'])
        self.assertEqual(b['next_up'], 'NV2')

    # ---- 3. quyền + ngành
    def test_staff_view_only_unless_owner_allows_front_desk(self):
        self.login('staff')
        self.board()
        n = DB.nail_turns.writes()
        r = self.c.post('/api/nail_turns/assign', json={'ma_nv': 'NV1', 'kind': 'walk_in'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(DB.nail_turns.writes(), n)
        self.assertEqual(self.c.post('/api/nail_turns/settings', json={'staff_can_assign': True}).status_code, 403)
        self.login('admin')
        self.post('/api/nail_turns/settings', {'staff_can_assign': True})
        self.login('staff')
        b = self.post('/api/nail_turns/assign', {'ma_nv': 'NV1', 'kind': 'walk_in', 'amount': 45})
        self.assertEqual([m['ma_nv'] for m in b['busy']], ['NV1'])
        turn = next(d for d in DB.nail_turns.docs if d['type'] == 'turn')
        self.assertEqual(turn['by_role'], 'staff')
        self.assertNotIn('by', b['log'][0])                                         # nhân viên không thấy email người bấm

    def test_other_industries_and_anonymous_are_blocked(self):
        self.assertEqual(self.c.get('/api/nail_turns/board').status_code, 401)
        self.login('admin', mode='fnb')
        self.assertEqual(self.c.get('/api/nail_turns/board').status_code, 403)
        self.assertEqual(self.c.post('/api/nail_turns/assign', json={'ma_nv': 'NV1'}).status_code, 403)
        r = self.c.get('/nail/turns')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(DB.nail_turns.writes(), 0)

    def test_settings_validation_and_currency_defaults(self):
        self.login('admin')
        r = self.c.get('/api/nail_turns/settings').get_json()
        self.assertEqual((r['settings']['full_turn_min'], r['settings']['currency']), (30.0, 'USD'))
        self.assertIn('Desk Dana', [p['name'] for p in r['staff']])
        self.assertEqual(self.c.post('/api/nail_turns/settings', json={'full_turn_min': -5}).status_code, 400)
        self.assertEqual(self.c.post('/api/nail_turns/settings', json={'request_counts': 'double'}).status_code, 400)
        s = self.post('/api/nail_turns/settings', {'full_turn_min': '35', 'request_counts': 'half', 'exclude': ['NV2']})['settings']
        self.assertEqual((s['full_turn_min'], s['request_counts'], s['exclude']), (35.0, 'half', ['NV2']))
        b = self.board()
        self.assertEqual([m['ma_nv'] for m in b['line']], ['NV1'])                 # Bao bị bỏ khỏi bảng tua
        DB.nail_turn_settings.docs.clear()
        for cur, country, expect_cur, expect_min in (('AUD', 'AU', 'AUD', 45.0), ('VND', 'VN', 'VND', 150000.0),
                                                     ('', 'AU', 'AUD', 45.0), ('', '', 'USD', 30.0)):
            DB.businesses.docs[0].update({'currency': cur, 'country': country})
            nt._CACHE.clear()
            s = nt.get_settings(BIZ)
            self.assertEqual((s['currency'], s['full_turn_min']), (expect_cur, expect_min), (cur, country))

    # ---- 4. giao ngoài lượt + 2 máy cùng lúc
    def test_out_of_turn_needs_confirmation_and_is_logged(self):
        self.login('admin')
        self.board()
        r = self.c.post('/api/nail_turns/assign', json={'ma_nv': 'NV2', 'kind': 'walk_in'})
        self.assertEqual(r.status_code, 409)
        body = r.get_json()
        self.assertEqual((body['code'], body['next_up']), ('not_next', 'NV1'))
        self.assertFalse([d for d in DB.nail_turns.docs if d['type'] == 'turn'])
        self.post('/api/nail_turns/assign', {'ma_nv': 'NV2', 'kind': 'walk_in', 'override': True})
        turn = next(d for d in DB.nail_turns.docs if d['type'] == 'turn')
        self.assertTrue(turn['out_of_turn'])
        self.assertEqual(turn['next_up_name'], 'Anna')
        # khách request không cần đúng lượt
        self.post('/api/nail_turns/action', {'action': 'join', 'ma_nv': 'NV3'})
        self.post('/api/nail_turns/assign', {'ma_nv': 'NV3', 'kind': 'request'})

    def test_two_devices_assigning_same_tech_lower_id_wins(self):
        self.login('admin')
        self.board()
        real_load = nt._load
        fired = []

        def racing_load(*a, **k):
            out = real_load(*a, **k)
            if not fired:       # máy quầy thứ 2 ghi tua cho Anna ngay sau khi máy này đọc bảng
                fired.append(1)
                DB.nail_turns.docs.append({'id': next(_ids), 'business_id': BIZ, 'day': DAY, 'type': 'turn', 'ma_nv': 'NV1',
                                           'name': 'Anna', 'kind': 'walk_in', 'value': 1.0, 'at': f'{DAY}T10:00:00',
                                           'created_at': f'{DAY}T10:00:00', 'voided': False, 'by_role': 'other-device'})
            return out
        with patch.object(nt, '_load', side_effect=racing_load):
            r = self.c.post('/api/nail_turns/assign', json={'ma_nv': 'NV1', 'kind': 'walk_in'})
        self.assertEqual(r.status_code, 409)
        turns = [d for d in DB.nail_turns.docs if d['type'] == 'turn']
        mine = next(d for d in turns if d.get('by_role') == 'admin')
        rival = next(d for d in turns if d.get('by_role') == 'other-device')
        self.assertLess(rival['id'], mine['id'])
        self.assertEqual((mine['voided'], mine['void_reason'], rival['voided']), (True, 'conflict', False))
        self.assertEqual([m['ma_nv'] for m in r.get_json()['board']['busy']], ['NV1'])

    def test_busy_or_absent_tech_cannot_take_a_walk_in(self):
        self.login('admin')
        self.board()
        self.post('/api/nail_turns/assign', {'ma_nv': 'NV1', 'kind': 'walk_in'})
        self.assertEqual(self.c.post('/api/nail_turns/assign', json={'ma_nv': 'NV1', 'kind': 'walk_in', 'override': True}).status_code, 409)
        self.assertEqual(self.c.post('/api/nail_turns/assign', json={'ma_nv': 'NV3', 'kind': 'walk_in', 'override': True}).status_code, 409)
        self.post('/api/nail_turns/action', {'action': 'break', 'ma_nv': 'NV2'})
        self.assertEqual(self.c.post('/api/nail_turns/assign', json={'ma_nv': 'NV2', 'kind': 'walk_in', 'override': True}).status_code, 409)
        b = self.post('/api/nail_turns/assign', {'ma_nv': 'NV2', 'kind': 'request'})   # khách request gọi thợ đang nghỉ
        self.assertEqual({m['ma_nv'] for m in b['busy']}, {'NV1', 'NV2'})
        self.assertEqual(self.c.post('/api/nail_turns/action', json={'action': 'leave', 'ma_nv': 'NV1'}).status_code, 409)

    # ---- 5. vé POS, hoàn tác, tổng kết
    def _pos_ticket(self, oid, ma, amount, created, status='completed'):
        DB.orders.docs.append({'id': oid, 'business_id': BIZ, 'created_at': created, 'status': status,
                               'total_amount': amount, 'metadata': {'channel': 'nail_pos'}})
        DB.order_items.docs.append({'id': oid * 10, 'order_id': oid, 'business_id': BIZ, 'ma_nv': ma, 'total_price': amount})

    def test_service_price_then_pos_ticket_settles_full_or_half(self):
        self.login('admin')
        self.board()
        b = self.post('/api/nail_turns/assign', {'ma_nv': 'NV1', 'kind': 'walk_in', 'service_id': 501})
        cur = b['busy'][0]['current']
        self.assertEqual((cur['service'], cur['amount'], cur['value'], cur['provisional']), ('Gel manicure', 45.0, 1.0, False))
        self.assertEqual(b['next_up'], 'NV2')
        _Clock.server = datetime(2026, 10, 26, 10, 20)
        self._pos_ticket(9001, 'NV1', 20.0, '2026-10-26T10:20:00')
        self._pos_ticket(9000, 'NV1', 99.0, '2026-10-26T09:00:00')                 # vé TRƯỚC lúc giao khách: không gợi ý
        b = self.board()
        self.assertEqual([s['order_id'] for s in b['busy'][0]['pos_suggestions']], [9001])
        b = self.post('/api/nail_turns/done', {'turn_id': cur['id'], 'order_id': 9001})
        turn = next(d for d in DB.nail_turns.docs if d['id'] == cur['id'])
        self.assertEqual((turn['amount'], turn['value'], turn['order_id']), (20.0, 0.5, 9001))   # $20 < $30 -> nửa tua
        self.assertEqual(turn['history'][-1]['amount'], 45.0)                                   # lịch sử sửa giá còn
        self.assertEqual([m['ma_nv'] for m in b['line']], ['NV2', 'NV1'])
        # vé không có dịch vụ của thợ -> từ chối
        self.post('/api/nail_turns/assign', {'ma_nv': 'NV2', 'kind': 'walk_in'})
        t2 = next(d for d in DB.nail_turns.docs if d['type'] == 'turn' and d['ma_nv'] == 'NV2')
        self.assertEqual(self.c.post('/api/nail_turns/done', json={'turn_id': t2['id'], 'order_id': 9001}).status_code, 404)

    def test_undo_marks_voided_never_deletes_and_desk_only_last(self):
        self.login('admin')
        self.board()
        b = self.post('/api/nail_turns/assign', {'ma_nv': 'NV1', 'kind': 'walk_in', 'amount': 45})
        tid = b['busy'][0]['current']['id']
        self.post('/api/nail_turns/done', {'turn_id': tid})
        self.post('/api/nail_turns/action', {'action': 'break', 'ma_nv': 'NV2'})
        n_docs = len(DB.nail_turns.docs)
        b = self.post('/api/nail_turns/undo', {})                                    # hoàn tác "nghỉ"
        self.assertEqual([m['ma_nv'] for m in b['line']], ['NV2', 'NV1'])
        self.assertEqual(len(DB.nail_turns.docs), n_docs)                           # không xoá dòng nào
        self.login('admin')
        self.post('/api/nail_turns/settings', {'staff_can_assign': True})
        self.login('staff')
        r = self.c.post('/api/nail_turns/undo', json={'event_id': tid})              # quầy: không huỷ dòng cũ
        self.assertEqual(r.status_code, 403)
        self.login('admin')
        b = self.post('/api/nail_turns/undo', {'event_id': tid})                     # chủ tiệm: huỷ tua -> huỷ luôn "xong"
        voided = {d['type'] for d in DB.nail_turns.docs if d.get('voided')}
        self.assertTrue({'turn', 'done', 'break'} <= voided)
        self.assertEqual(b['next_up'], 'NV1')
        join = next(d for d in DB.nail_turns.docs if d['type'] == 'join' and d['ma_nv'] == 'NV1')
        self.assertEqual(self.c.post('/api/nail_turns/undo', json={'event_id': join['id']}).status_code, 409)

    def test_summary_rows_add_up_and_pos_sales_use_shop_day(self):
        self.login('admin')
        self.board()
        for ma, amt in (('NV1', 20), ('NV2', 45)):
            b = self.post('/api/nail_turns/assign', {'ma_nv': ma, 'kind': 'walk_in', 'amount': amt})
            self.post('/api/nail_turns/done', {'turn_id': next(m for m in b['busy'] if m['ma_nv'] == ma)['current']['id']})
        b = self.post('/api/nail_turns/assign', {'ma_nv': 'NV1', 'kind': 'request', 'amount': 60})
        self.post('/api/nail_turns/action', {'action': 'skip', 'ma_nv': 'NV2'})
        self._pos_ticket(7001, 'NV1', 20.0, '2026-10-26T10:05:00')
        self._pos_ticket(7002, 'NV2', 45.0, '2026-10-26T11:00:00')
        self._pos_ticket(7003, 'NV2', 30.0, '2026-10-25T23:00:00')                  # hôm qua: không tính
        self._pos_ticket(7004, 'NV1', 80.0, '2026-10-26T12:00:00', status='refunded')
        s = self.c.get('/api/nail_turns/summary').get_json()
        rows = {r['ma_nv']: r for r in s['rows']}
        self.assertEqual((rows['NV1']['turns'], rows['NV1']['half'], rows['NV1']['not_counted'], rows['NV1']['requests']), (0.5, 1, 1, 1))
        self.assertEqual((rows['NV2']['turns'], rows['NV2']['full'], rows['NV2']['skips']), (1.0, 1, 1))
        self.assertEqual((rows['NV1']['ticket_total'], rows['NV1']['pos_sales'], rows['NV2']['pos_sales']), (80.0, 20.0, 45.0))
        for k in ('clients', 'turns', 'full', 'half', 'not_counted', 'ticket_total', 'pos_sales'):
            self.assertAlmostEqual(s['total'][k], sum(r[k] for r in s['rows']), places=3, msg=k)

    def test_shop_timezone_decides_the_day_for_clock_ins_and_pos(self):
        """Tiệm Úc 08:00 ngày 27 trong khi máy chủ (UTC) còn 21:00 ngày 26."""
        _Clock.local = datetime(2026, 10, 27, 8, 0)
        _Clock.server = datetime(2026, 10, 26, 21, 0)
        DB.chamcong.docs.append({'business_id': BIZ, 'ma_nv': 'NV3', 'ngay_cham': '27/10/2026', 'gio_den': '07:50', 'trang_thai': 'Có mặt'})
        self.login('admin')
        b = self.board()
        self.assertEqual(b['day'], '2026-10-27')
        self.assertEqual([m['ma_nv'] for m in b['line']], ['NV3'])
        self.assertEqual(nt._server_bounds(BIZ, '2026-10-27'), ('2026-10-26T13:00:00', '2026-10-27T13:00:00'))
        self.assertEqual(self.c.get('/api/nail_turns/board?day=2026-10-28').status_code, 400)      # ngày tương lai
        past = self.board(day='2026-10-26')
        self.assertFalse(past['can_assign'])
        self.assertFalse(past['is_today'])

    # ---- 6. trang
    def test_page_renders_vi_and_en(self):
        self.login('admin')
        loader_stub = {'components/app_sidebar.html': '<aside id="app-sidebar"></aside>'}
        from jinja2 import ChoiceLoader, DictLoader
        self.app.jinja_loader = ChoiceLoader([DictLoader(loader_stub), self.app.jinja_loader])

        @self.app.context_processor
        def _ctx():
            from flask import request
            return {'default_lang': 'vi' if request.cookies.get('bitpaw_lang') == 'vi' else 'en'}
        en = self.c.get('/nail/turns').get_data(as_text=True)
        self.assertIn('Turn board', en)
        self.assertIn('Next walk-in goes to', en)
        self.c.set_cookie('bitpaw_lang', 'vi')
        vi = self.c.get('/nail/turns').get_data(as_text=True)
        self.assertIn('Bảng xoay tua', vi)
        self.assertIn('const VI = true', vi)
        for bad in ('₫', '(VND)', 'Lorem', 'John Doe'):
            self.assertNotIn(bad, en)


class StaticChecks(unittest.TestCase):
    with io.open(os.path.join(ROOT, 'templates', 'nail_turns.html'), encoding='utf-8') as _fh:
        SRC = _fh.read()

    def test_inline_script_is_valid_js(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not installed')
        js = re.search(r'<script>(.*?)</script>', self.SRC, re.S).group(1)
        js = js.replace("{{ 'true' if vi else 'false' }}", 'true')
        self.assertNotIn('{{', js)
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as fh:
            fh.write(js)
        try:
            r = subprocess.run([node, '--check', fh.name], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.unlink(fh.name)

    def test_touch_targets_and_responsive_breakpoints(self):
        self.assertIn('min-height: 48px', self.SRC)
        self.assertIn('@media (max-width: 767px)', self.SRC)
        self.assertIn('prefers-reduced-motion', self.SRC)

    def test_plan_card_claims_turn_board_only_for_nail_and_feature_exists(self):
        ess = next(c for c in plans.tier_cards('nail') if c['key'] == 'essential')
        self.assertTrue(any('turn board' in en.lower() and 'xoay tua' in vi.lower() for _i, vi, en in ess['items']))
        app = Flask(__name__)
        app.register_blueprint(nt.nail_turns_bp)
        rules = {r.rule for r in app.url_map.iter_rules()}
        self.assertTrue({'/nail/turns', '/api/nail_turns/board', '/api/nail_turns/assign', '/api/nail_turns/done',
                         '/api/nail_turns/undo', '/api/nail_turns/summary', '/api/nail_turns/settings'} <= rules)
        for ind in plans.INDUSTRY_PRICES:
            if ind == 'nail':
                continue
            for card in plans.tier_cards(ind):
                for _i, vi, en in card['items']:
                    self.assertNotIn('turn board', en.lower(), ind)
                    self.assertNotIn('xoay tua', vi.lower(), ind)

    def test_sidebar_item_is_nail_only(self):
        with io.open(os.path.join(ROOT, 'templates', 'components', 'app_sidebar.html'), encoding='utf-8') as fh:
            sb = fh.read()
        i = sb.index('href="/nail/turns"')
        self.assertIn("{% if active_industry_code == 'nail' %}", sb[max(0, i - 400):i])


if __name__ == '__main__':
    unittest.main(verbosity=2)
