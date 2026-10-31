# -*- coding: utf-8 -*-
"""Test OFFLINE — bảo mật h2-plans: tiệm chỉ được tính năng trả phí từ gói nó ĐÃ trả.
  1) plans.business_plan: Empire miễn phí chỉ cho tiệm có trước ngày ra mắt gói (GRANDFATHER_BEFORE); tiệm mới thiếu plan,
     id rỗng, id của tài khoản không phải chủ = Essential; chi nhánh (hồ sơ có parent_business_id hoặc dòng
     business_memberships cũ) = gói của tiệm chính; ai_gateway.allowed theo đúng gói đó;
  2) plans.ROUTE_FEATURES: /api/* của tính năng có khoá gói (SMS, gói liệu trình, đặt chỗ, nghỉ phép/chi phí, tồn kho,
     nguyên vật liệu, bếp, phụ tùng, lãi lỗ/thu chi/công nợ, CRM AI, QR gọi món, đồng bộ TMĐT) bị app._plan_gate chặn;
     luồng Essential (kho cơ bản, trừ buổi gói đã mua, trang khách) vẫn mở;
  3) app.py /add_branch + /api/switch_branch: chỉ chủ tiệm Empire tạo chi nhánh, chi nhánh mới có hồ sơ trỏ về tiệm chính,
     hạ gói thì chi nhánh hạ theo, về chi nhánh chính luôn được, giới hạn số chi nhánh;
  4) ai_media: chi nhánh dùng CHUNG hạn mức ảnh/video của tiệm chính (tạo chi nhánh không sinh thêm hạn mức Replicate);
  5) app.py /setup: chỉ 9 ngành hợp lệ; tiệm tạo từ ngày bán gói theo ngành chỉ dùng ngành của mã kích hoạt.

KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION), KHÔNG gọi mạng/API trả phí, KHÔNG import app.py (lấy hàm qua ast,
bỏ decorator), KHÔNG chạy server.
Chạy: python scripts/tests/test_security_h2-plans.py
(H2_PLANS_ROOT=<thư mục mã nguồn khác> để chạy cùng bộ test trên bản cũ — xem nó FAIL trước bản vá.)
"""
import ast
import io
import os
import sys
import types
import unittest
from datetime import datetime
from itertools import count
from unittest.mock import patch

ROOT = os.environ.get('H2_PLANS_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
os.environ.pop('BITPAW_DESKTOP_MODE', None)


# ---------------------------------------------------------------- DB giả trong RAM
def _cmp(v, op, arg):
    if v is None:
        return False
    try:
        return {'$gte': v >= arg, '$gt': v > arg, '$lt': v < arg, '$lte': v <= arg}[op]
    except TypeError:
        return False


def _match_value(present, v, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith('$') for k in cond):
        for op, arg in cond.items():
            if op == '$in' and v not in arg:
                return False
            if op == '$nin' and v in arg:
                return False
            if op == '$ne' and v == arg:
                return False
            if op == '$exists' and present != bool(arg):
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
        elif not _match_value(k in doc, doc.get(k), cond):
            return False
    return True


class _Cursor(list):
    def sort(self, key, direction=1):
        return _Cursor(sorted(self, key=lambda d: (d.get(key) is None, str(d.get(key))), reverse=direction == -1))

    def limit(self, n):
        return _Cursor(self[:n] if n else self)


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs = name, []

    def insert_one(self, doc):
        d = dict(doc)
        d.setdefault('_id', f'{self.name}-{len(self.docs) + 1}')
        self.docs.append(d)
        return types.SimpleNamespace(inserted_id=d['_id'])

    def find(self, flt=None, projection=None):
        return _Cursor(dict(d) for d in self.docs if _matches(d, flt or {}))

    def find_one(self, flt=None, projection=None, sort=None):
        rows = self.find(flt)
        return dict(rows[0]) if rows else None

    def count_documents(self, flt=None):
        return len(self.find(flt))

    def _apply(self, d, update, inserting=False):
        d.update(update.get('$set') or {})
        for k, v in (update.get('$inc') or {}).items():
            d[k] = (d.get(k) or 0) + v
        if inserting:
            d.update(update.get('$setOnInsert') or {})

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            new = {k: v for k, v in flt.items() if not k.startswith('$') and not isinstance(v, dict)}
            self._apply(new, update, inserting=True)
            self.docs.append(new)
        return types.SimpleNamespace(matched_count=0, modified_count=0)

    def find_one_and_update(self, flt, update, projection=None, return_document=False, upsert=False, **kw):
        for d in self.docs:
            if _matches(d, flt):
                before = dict(d)
                self._apply(d, update)
                return dict(d) if return_document else before
        return None

    def aggregate(self, pipeline):
        rows = [dict(d) for d in self.docs]
        for stage in pipeline:
            if '$match' in stage:
                rows = [d for d in rows if _matches(d, stage['$match'])]
            elif '$group' in stage:
                spec, out = stage['$group'], {}
                for d in rows:
                    key = d.get(spec['_id'][1:])
                    g = out.setdefault(key, {'_id': key})
                    for field, acc in spec.items():
                        if field != '_id':
                            src = acc['$sum']
                            g[field] = g.get(field, 0) + (src if isinstance(src, (int, float)) else (d.get(src[1:]) or 0))
                rows = list(out.values())
        return iter(rows)


class FakeDB:
    def __init__(self):
        self.__dict__['_c'] = {}

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        if name not in self._c:
            self._c[name] = FakeCollection(name)
        return self._c[name]

    def __getitem__(self, name):
        return getattr(self, name)

    def reset(self):
        self._c.clear()


DB = FakeDB()
_ids = count(9000)
sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=lambda c: next(_ids), MONGO_STATUS='CONNECTED')
sys.modules['ai_deepseek_client'] = types.SimpleNamespace(
    deepseek_chat_completion=lambda *a, **k: (_ for _ in ()).throw(AssertionError('no DeepSeek in offline tests')))


def _no_network(*a, **kw):
    raise AssertionError('network disabled in offline tests')


patch('requests.sessions.Session.request', _no_network).start()

from flask import Flask, jsonify, redirect, request, session, url_for  # noqa: E402

import plans  # noqa: E402
import ai_gateway  # noqa: E402
import ai_media  # noqa: E402
import uuid  # noqa: E402


# ---------------------------------------------------------------- hàm của app.py (lấy mã nguồn qua ast, bỏ decorator)
with io.open(os.path.join(ROOT, 'app.py'), encoding='utf-8') as f:
    _TREE = ast.parse(f.read())
_FUNCS = ('_session_business_id', '_get_owned_business_ids', '_multi_location_denied', 'api_switch_branch', 'add_branch',
          '_license_locked_industry', 'setup', '_plan_gate')
INDUSTRIES = ('retail', 'fnb', 'spa', 'nail', 'karaoke', 'hotel', 'production', 'technical', 'office')
NS = {
    'db': DB, 'session': session, 'request': request, 'jsonify': jsonify, 'redirect': redirect, 'url_for': url_for,
    'plans': plans, 'uuid': uuid, 'datetime': datetime, 'INDUSTRY_CONFIG': {k: {} for k in INDUSTRIES},
    '_is_superadmin': lambda: False, 'resolve_lang': lambda req: 'en', '_vi_en': lambda vi, en: en,
    '_PRIMARY_BRANCH_DEFAULT_NAME': 'Chi nhánh chính',
    '_wants_json': lambda: request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json',
    'render_message_page': lambda status, *a, **k: (f'message page {status}', status),
    'render_template': lambda name, **k: f'rendered {name}',
}
for _name in _FUNCS:
    _node = next((n for n in _TREE.body if isinstance(n, ast.FunctionDef) and n.name == _name), None)
    if _node is None:   # bản cũ chưa có hàm phụ này -> bỏ qua (route vẫn chạy theo mã cũ)
        continue
    _node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[_node], type_ignores=[])), f'app.py::{_name}', 'exec'), NS)

APP = Flask(__name__)
APP.secret_key = 'unit-test'
APP.before_request(NS['_plan_gate'])
APP.add_url_rule('/add_branch', 'add_branch', NS['add_branch'], methods=['POST'])
APP.add_url_rule('/api/switch_branch', 'api_switch_branch', NS['api_switch_branch'], methods=['POST'])
APP.add_url_rule('/setup', 'setup', NS['setup'], methods=['GET', 'POST'])
APP.add_url_rule('/dashboard', 'index', lambda: 'dashboard')
APP.add_url_rule('/plan', 'plan_page', lambda: 'plan page')
APP.add_url_rule('/<path:anything>', 'anything', lambda anything: jsonify({'success': True, 'reached': anything}),
                 methods=['GET', 'POST', 'PATCH', 'DELETE'])

OLD = '2026-10-01T09:00:00.000000'      # trước ngày ra mắt gói
NEW = '2026-10-29T09:00:00.000000'      # sau ngày ra mắt gói


def _reset():
    DB.reset()
    plans._PLAN_CACHE.clear()


def _owner(bid, plan=None, created_at=NEW, industry='nail', **extra):
    """Chủ tiệm như register(): users + businesses + dòng chi nhánh chính."""
    DB.users.insert_one({'id': bid, 'email': f'{bid}@x.test', 'business_id': bid, 'role': 'admin', 'created_at': created_at})
    doc = {'id': bid, 'name': bid, 'industry_code': industry, 'created_at': created_at, **extra}
    if plan:
        doc['plan'] = plan
    DB.businesses.insert_one(doc)
    DB.business_memberships.insert_one({'owner_user_id': bid, 'business_id': bid, 'branch_name': 'Chi nhánh chính', 'is_primary': True})


def _client(user_id, business_id=None, role='admin', mode='nail'):
    c = APP.test_client()
    with c.session_transaction() as s:
        s['user_id'] = user_id
        s['business_id'] = business_id or user_id
        s['role'] = role
        s['business_mode'] = mode
    return c


def _session_of(c):
    with c.session_transaction() as s:
        return dict(s)


# ================================================================ 1. phân giải gói
class PlanResolutionTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_shops_from_before_the_launch_keep_empire(self):
        DB.businesses.insert_one({'id': 'old-iso', 'created_at': OLD})
        DB.businesses.insert_one({'id': 'old-nodate'})                                  # hồ sơ cũ không có created_at
        DB.businesses.insert_one({'id': 'old-dt', 'created_at': datetime(2026, 9, 1, 8, 0)})
        DB.businesses.insert_one({'id': 'old-edge', 'created_at': '2026-10-25T23:59:59'})
        for bid in ('old-iso', 'old-nodate', 'old-dt', 'old-edge'):
            self.assertEqual(plans.business_plan(DB, bid), 'empire', bid)

    def test_new_shop_without_plan_fails_closed(self):
        # trước bản vá: mọi hồ sơ thiếu plan = Empire, kể cả tiệm đăng ký hôm qua bằng mã kích hoạt cũ không ghi gói
        DB.businesses.insert_one({'id': 'new-noplan', 'created_at': NEW})
        DB.businesses.insert_one({'id': 'new-edge', 'created_at': '2026-10-26T00:00:00'})
        self.assertEqual(plans.business_plan(DB, 'new-noplan'), 'essential')
        self.assertEqual(plans.business_plan(DB, 'new-edge'), 'essential')
        self.assertFalse(ai_gateway.allowed('new-noplan', 'ai_studio'))

    def test_explicit_plan_always_wins(self):
        DB.businesses.insert_one({'id': 'p-pro', 'plan': 'pro', 'created_at': NEW})
        DB.businesses.insert_one({'id': 'p-ess-old', 'plan': 'essential', 'created_at': OLD})
        self.assertEqual(plans.business_plan(DB, 'p-pro'), 'pro')
        self.assertEqual(plans.business_plan(DB, 'p-ess-old'), 'essential')

    def test_empty_or_non_string_id_is_essential(self):
        # trước bản vá: None/'' = Empire, dict (toán tử Mongo lọt từ JSON) làm business_plan nổ TypeError
        DB.businesses.insert_one({'id': 'any', 'plan': 'empire'})
        self.assertEqual(plans.business_plan(DB, None), 'essential')
        self.assertEqual(plans.business_plan(DB, ''), 'essential')
        self.assertEqual(plans.business_plan(DB, {'$ne': None}), 'essential')
        self.assertFalse(ai_gateway.allowed(None, 'ai_inbox'))

    def test_unknown_plan_value_never_means_empire(self):
        self.assertFalse(plans.allows('gold', 'ai_studio'))
        self.assertFalse(plans.allows(None, 'roster'))
        self.assertTrue(plans.allows(None, 'not-a-gated-feature'))

    def test_owner_account_without_business_row(self):
        DB.users.insert_one({'id': 'u-old', 'business_id': 'u-old', 'created_at': OLD})
        DB.users.insert_one({'id': 'u-new', 'business_id': 'u-new', 'created_at': NEW})
        DB.users.insert_one({'id': 'staff-9', 'business_id': 'shop-9', 'created_at': OLD})   # không phải chủ id staff-9
        self.assertEqual(plans.business_plan(DB, 'u-old'), 'empire')
        self.assertEqual(plans.business_plan(DB, 'u-new'), 'essential')
        # trước bản vá: nhân viên chuyển phiên sang dòng "chi nhánh chính" = id riêng của mình -> Empire
        self.assertEqual(plans.business_plan(DB, 'staff-9'), 'essential')

    def test_branch_row_inherits_the_parent_plan(self):
        _owner('chain', plan='essential')
        DB.businesses.insert_one({'id': 'chain-b1', 'parent_business_id': 'chain', 'created_at': NEW})
        self.assertEqual(plans.business_plan(DB, 'chain-b1'), 'essential')
        DB.businesses.update_one({'id': 'chain'}, {'$set': {'plan': 'pro'}})
        plans._PLAN_CACHE.clear()
        self.assertEqual(plans.business_plan(DB, 'chain-b1'), 'pro')
        DB.businesses.insert_one({'id': 'legacy', 'created_at': OLD})
        DB.businesses.insert_one({'id': 'legacy-b1', 'parent_business_id': 'legacy', 'created_at': NEW})
        self.assertEqual(plans.business_plan(DB, 'legacy-b1'), 'empire', 'chi nhánh của tiệm cũ giữ Empire')

    def test_old_membership_only_branch_inherits_the_owner_plan(self):
        # chi nhánh tạo bằng /add_branch trước bản vá: chỉ có dòng business_memberships, KHÔNG có hồ sơ businesses
        _owner('ess-owner', plan='essential')
        DB.business_memberships.insert_one({'owner_user_id': 'ess-owner', 'business_id': 'free-branch', 'is_primary': False})
        self.assertEqual(plans.business_plan(DB, 'free-branch'), 'essential')     # trước bản vá: 'empire'
        self.assertFalse(ai_gateway.allowed('free-branch', 'ai_copilot'))
        self.assertFalse(ai_gateway.allowed('free-branch', 'ai_inbox'))
        # chi nhánh do NHÂN VIÊN tạo (owner_user_id = id nhân viên): theo tiệm nhân viên thuộc về
        DB.users.insert_one({'id': 'emp-1', 'business_id': 'ess-owner', 'role': 'staff', 'created_at': OLD})
        DB.business_memberships.insert_one({'owner_user_id': 'emp-1', 'business_id': 'staff-branch', 'is_primary': False})
        self.assertEqual(plans.business_plan(DB, 'staff-branch'), 'essential')
        _owner('emp-owner', created_at=OLD)            # tiệm cũ = Empire -> chi nhánh cũ của nó vẫn Empire
        DB.business_memberships.insert_one({'owner_user_id': 'emp-owner', 'business_id': 'emp-branch', 'is_primary': False})
        self.assertEqual(plans.business_plan(DB, 'emp-branch'), 'empire')


# ================================================================ 2. cổng gói theo đường dẫn
GATED_API = {
    '/api/messaging/settings': 'messaging', '/api/messaging/test': 'messaging', '/api/messaging/log': 'messaging',
    '/api/packages': 'packages', '/api/packages/sell': 'packages',
    '/api/reservations/5': 'reservations', '/api/hotel_reservations/5': 'reservations', '/api/karaoke_reservations/5': 'reservations',
    '/api/leave_requests': 'requests', '/api/leave_requests/3': 'requests',
    '/api/expense_requests': 'requests', '/api/expense_requests/3': 'requests',
    '/api/inventory/thresholds': 'inventory', '/api/restock_proposals': 'inventory', '/api/restock_proposals/2': 'inventory',
    '/api/production/materials': 'materials', '/api/production/materials/4': 'materials',
    '/api/kitchen/orders': 'kds', '/api/kitchen/orders/9': 'kds', '/api/stream/kitchen': 'kds',
    '/api/tech_parts': 'parts', '/api/tech_parts/7': 'parts',
    '/api/transactions': 'finance', '/api/transactions/8': 'finance', '/api/report/profit': 'finance',
    '/api/debt_transactions': 'finance',
    '/api/ai/nurture/rules': 'crm_ai', '/api/ai/nurture/generate-campaign': 'crm_ai', '/api/ai/campaigns/summary': 'crm_ai',
    '/api/stream/bot_chat': 'ai_inbox',
    '/api/qr/table/3': 'qr_ordering', '/qr/poster/table/3': 'qr_ordering',
    '/api/ecommerce/sync': 'marketing_pro', '/api/ecommerce/connections': 'marketing_pro',
}
OPEN_PATHS = (
    '/api/packages/customer', '/api/packages/12',            # POS spa trừ buổi gói khách đã mua; ngừng bán gói cũ
    '/api/inventory', '/api/inventory/5', '/api/inventory/products', '/api/products/5/restock', '/api/stream/inventory',
    '/api/expenses', '/api/shift_swaps', '/api/report/summary', '/api/chat/messages',
    '/api/public/reservations/biz', '/api/public/hotel_reservations/biz', '/api/submit_qr_order', '/qr_menu/abc',
    '/api/qr/nail_booking', '/qr/poster/booking', '/reserve/biz', '/api/twilio/sms/biz', '/api/my_branches',
)


class RouteGateTests(unittest.TestCase):
    def setUp(self):
        _reset()
        _owner('ess', plan='essential')
        _owner('emp', plan='empire')

    def test_api_routes_of_gated_features_are_mapped(self):
        missing = {p: plans.feature_for_path(p) for p, feat in GATED_API.items() if plans.feature_for_path(p) != feat}
        self.assertEqual(missing, {}, 'API của tính năng có khoá gói không được map')

    def test_essential_flows_stay_open(self):
        self.assertEqual({p: plans.feature_for_path(p) for p in OPEN_PATHS if plans.feature_for_path(p)}, {})

    def test_plan_gate_blocks_essential_shop_on_api_calls(self):
        c = _client('ess')
        for method, path in (('post', '/api/messaging/settings'), ('post', '/api/packages/sell'), ('post', '/api/packages'),
                             ('patch', '/api/reservations/5'), ('patch', '/api/leave_requests/3'), ('get', '/api/transactions'),
                             ('post', '/api/inventory/thresholds'), ('post', '/api/ai/nurture/rules'), ('get', '/api/qr/table/3')):
            r = getattr(c, method)(path, json={})
            body = r.get_json() or {}
            self.assertEqual((r.status_code, body.get('upgrade_required')), (403, True), f'{method} {path}')
        self.assertEqual(c.get('/api/packages/customer?phone=1').status_code, 200)
        self.assertEqual(c.post('/api/inventory', json={}).status_code, 200)
        r = _client('emp').post('/api/messaging/settings', json={})
        self.assertEqual(r.status_code, 200)


# ================================================================ 3. tạo / chuyển chi nhánh
class BranchRouteTests(unittest.TestCase):
    def setUp(self):
        _reset()
        _owner('ess', plan='essential', country='AU', currency='AUD')
        _owner('pro', plan='pro')
        _owner('emp', created_at=OLD, industry='spa', country='AU', currency='AUD')   # tiệm cũ chưa có plan = Empire

    def test_essential_and_pro_owners_cannot_create_branches(self):
        for owner in ('ess', 'pro'):
            r = _client(owner).post('/add_branch', json={'branch_name': 'x'})
            body = r.get_json() or {}
            self.assertEqual(r.status_code, 403, owner)                 # trước bản vá: 200 + chi nhánh "Empire" miễn phí
            self.assertTrue(body.get('upgrade_required'))
            self.assertEqual(body.get('feature'), 'multi_location')
        self.assertEqual(DB.business_memberships.count_documents({'is_primary': False}), 0)
        self.assertEqual(DB.businesses.count_documents({'parent_business_id': {'$exists': True}}), 0)

    def test_staff_cannot_create_branches(self):
        r = _client('staff-1', business_id='emp', role='staff').post('/add_branch', json={'branch_name': 'x'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(DB.business_memberships.count_documents({'is_primary': False}), 0)

    def test_empire_branch_points_to_the_parent_and_follows_its_plan(self):
        c = _client('emp', mode='spa')
        r = c.post('/add_branch', json={'branch_name': 'Bondi'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        new_id = r.get_json()['business_id']
        doc = DB.businesses.find_one({'id': new_id})
        self.assertIsNotNone(doc, 'chi nhánh mới phải có hồ sơ businesses')
        self.assertEqual(doc['parent_business_id'], 'emp')
        self.assertEqual(doc['owner_user_id'], 'emp')
        self.assertNotIn('plan', doc)
        self.assertTrue(doc.get('created_at'))
        self.assertEqual((doc.get('industry_code'), doc.get('country'), doc.get('currency')), ('spa', 'AU', 'AUD'))
        self.assertEqual(plans.business_plan(DB, new_id), 'empire')
        r = c.post('/api/switch_branch', json={'business_id': new_id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_session_of(c)['business_id'], new_id)
        # tạo tiếp khi đang đứng ở chi nhánh: vẫn trỏ về tiệm chính
        r = c.post('/add_branch', json={'branch_name': 'Manly'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(DB.businesses.find_one({'id': r.get_json()['business_id']})['parent_business_id'], 'emp')
        # hạ gói tiệm chính -> chi nhánh hạ theo; không vào được chi nhánh phụ nhưng luôn về được chi nhánh chính
        DB.businesses.update_one({'id': 'emp'}, {'$set': {'plan': 'essential'}})
        plans._PLAN_CACHE.clear()
        self.assertEqual(plans.business_plan(DB, new_id), 'essential')
        self.assertFalse(ai_gateway.allowed(new_id, 'ai_studio'))
        r = c.post('/api/switch_branch', json={'business_id': 'emp'})
        self.assertEqual(r.status_code, 200)
        r = c.post('/api/switch_branch', json={'business_id': new_id})
        self.assertEqual(r.status_code, 403)
        self.assertTrue((r.get_json() or {}).get('upgrade_required'))
        self.assertEqual(_session_of(c)['business_id'], 'emp')

    def test_essential_owner_cannot_enter_a_branch_made_by_the_old_bug(self):
        DB.business_memberships.insert_one({'owner_user_id': 'ess', 'business_id': 'free-branch', 'branch_name': 'x', 'is_primary': False})
        c = _client('ess')
        r = c.post('/api/switch_branch', json={'business_id': 'free-branch'})
        self.assertEqual(r.status_code, 403)                            # trước bản vá: 200 -> phiên chạy gói Empire
        self.assertEqual(_session_of(c)['business_id'], 'ess')
        self.assertEqual(c.post('/api/switch_branch', json={'business_id': 'ess'}).status_code, 200)
        self.assertEqual(c.post('/api/switch_branch', json={'business_id': 'emp'}).status_code, 403, 'không phải của mình')

    def test_owner_always_gets_back_to_the_main_location(self):
        # dòng chi nhánh chính cũ không có cờ is_primary: chủ tiệm Essential đang đứng ở chi nhánh vẫn về được tiệm của mình
        _reset()
        DB.users.insert_one({'id': 'own2', 'business_id': 'own2', 'role': 'admin', 'created_at': NEW})
        DB.businesses.insert_one({'id': 'own2', 'plan': 'essential', 'created_at': NEW})
        DB.business_memberships.insert_one({'owner_user_id': 'own2', 'business_id': 'own2', 'branch_name': 'Main'})
        DB.business_memberships.insert_one({'owner_user_id': 'own2', 'business_id': 'own2-b', 'is_primary': False})
        c = _client('own2', business_id='own2-b')
        self.assertEqual(c.post('/api/switch_branch', json={'business_id': 'own2'}).status_code, 200)
        self.assertEqual(_session_of(c)['business_id'], 'own2')
        self.assertEqual(plans.business_plan(DB, 'own2'), 'essential')

    def test_branch_count_is_capped(self):
        for i in range(plans.BRANCH_LIMIT):
            DB.business_memberships.insert_one({'owner_user_id': 'emp', 'business_id': f'b{i}', 'is_primary': False})
        r = _client('emp').post('/add_branch', json={'branch_name': 'one too many'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(DB.business_memberships.count_documents({'owner_user_id': 'emp', 'is_primary': False}), plans.BRANCH_LIMIT)


# ================================================================ 4. hạn mức AI media theo tiệm trả tiền
class MediaQuotaScopeTests(unittest.TestCase):
    def setUp(self):
        _reset()
        _owner('chain', created_at=OLD)                                  # Empire cũ: 300 ảnh/tháng
        DB.businesses.insert_one({'id': 'chain-b1', 'parent_business_id': 'chain', 'created_at': NEW})
        DB.business_memberships.insert_one({'owner_user_id': 'chain', 'business_id': 'chain-b1', 'is_primary': False})
        self.month = ai_media._month_start().strftime('%Y-%m')
        now = ai_media._now()
        DB.ai_usage.insert_one({'business_id': 'chain', 'kind': 'image', 'units': 300, 'created_at': now})

    def test_branch_shares_the_parent_quota(self):
        q = ai_media.quota_status('chain-b1')
        self.assertEqual(q['images']['limit'], 300)
        self.assertEqual(q['images']['used'], 300)                      # trước bản vá: 0 -> thêm 300 ảnh Replicate / chi nhánh
        with self.assertRaises(ai_media.MediaError) as e:
            ai_media._check_quota('chain-b1', 'image', 1)
        self.assertEqual(e.exception.code, 'quota_exceeded')
        DB.ai_media_quota.insert_one({'_id': f'chain|{self.month}', 'business_id': 'chain', 'month': self.month,
                                      'images': 300, 'video_seconds': 0})
        with self.assertRaises(ai_media.MediaError):
            ai_media._reserve('chain-b1', 'image', 1)
        self.assertIsNone(DB.ai_media_quota.find_one({'_id': f'chain-b1|{self.month}'}), 'không có ô hạn mức riêng cho chi nhánh')

    def test_branch_usage_counts_against_the_parent(self):
        DB.ai_usage.docs.clear()
        DB.ai_usage.insert_one({'business_id': 'chain-b1', 'kind': 'image', 'units': 7, 'created_at': ai_media._now()})
        self.assertEqual(ai_media.quota_status('chain')['images']['used'], 7)
        self.assertEqual(ai_media._reserve('chain-b1', 'image', 1), f'chain|{self.month}')

    def test_single_location_shop_is_unchanged(self):
        _owner('solo', created_at=OLD)
        DB.ai_usage.insert_one({'business_id': 'solo', 'kind': 'image', 'units': 5, 'created_at': ai_media._now()})
        self.assertEqual(ai_media.quota_status('solo')['images']['used'], 5)
        self.assertEqual(ai_media._reserve('solo', 'image', 1), f'solo|{self.month}')


# ================================================================ 5. /setup đổi ngành
class SetupIndustryTests(unittest.TestCase):
    def setUp(self):
        _reset()
        _owner('off1', plan='essential', industry='office', created_at=NEW)   # mã kích hoạt ngành Văn phòng ($39)
        _owner('leg1', industry='fnb', created_at=OLD)                       # tiệm cũ

    def _mode(self, bid):
        return (DB.system_settings.find_one({'key': f'business_mode_{bid}'}) or {}).get('value')

    def test_unknown_mode_is_rejected(self):
        c = _client('off1', mode='office')
        r = c.post('/setup', data={'mode': 'x'})
        self.assertEqual(r.status_code, 400)                            # trước bản vá: lưu 'x' -> tắt cách ly ngành
        self.assertIsNone(self._mode('off1'))
        self.assertEqual(_session_of(c)['business_mode'], 'office')

    def test_new_shop_is_locked_to_the_license_industry(self):
        c = _client('off1', mode='office')
        r = c.post('/setup', data={'mode': 'production'})
        self.assertEqual(r.status_code, 403)                            # trước bản vá: đổi sang ngành $89 khi trả $39
        self.assertIsNone(self._mode('off1'))
        self.assertEqual(_session_of(c)['business_mode'], 'office')
        r = c.post('/setup', data={'mode': 'office'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._mode('off1'), 'office')

    def test_staff_session_of_a_locked_shop_cannot_switch_either(self):
        r = _client('staff-x', business_id='off1', role='staff', mode='office').post('/setup', data={'mode': 'hotel'})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self._mode('staff-x'))

    def test_legacy_shop_can_still_switch(self):
        c = _client('leg1', mode='fnb')
        r = c.post('/setup', data={'mode': 'hotel'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._mode('leg1'), 'hotel')
        self.assertEqual(_session_of(c)['business_mode'], 'hotel')


if __name__ == '__main__':
    unittest.main(verbosity=2)
