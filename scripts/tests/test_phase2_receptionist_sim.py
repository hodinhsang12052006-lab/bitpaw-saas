# -*- coding: utf-8 -*-
"""Test OFFLINE — Phase 2 "bộ đo lễ tân AI theo ngành":
  1) scripts/ai_sim/sim_receptionist.py --mock chạy trọn 9 ngành (DB giả trong RAM, khách / bot / giám khảo soạn sẵn): bot mẫu
     trung thực đạt DB truth 100%, bot mẫu nói dối / nói sai trạng thái bị bắt (claims mismatch, DB truth < 95%);
  2) sự thật DB: các kiểu kiểm tra (created / modified / cancelled / own_untouched / foreign_untouched / no_leak / max_qty /
     forbid / not_confirmed / legacy), so lời bot với DB (đã đặt mà DB trống, "confirmed" mà DB pending, hứa giờ thợ tới,
     số tiền không suy ra từ giá thật), bất biến (thiếu nhãn AI, lịch hẹn ma, đặt trùng phòng / bàn);
  3) tự dọn: chỉ xoá dòng của lượt chạy (mã hội thoại / mã chat / SĐT giả đã kiểm chưa từng có / id hạt giống), trả lại
     held_qty của hàng giữ, xoá phiếu phòng-đêm của đặt phòng giả lập — dòng thật của tiệm còn nguyên;
  4) chế độ thật (không chạy mạng): mỗi cuộc chat gửi chat_token riêng + đúng payload widget, giữ nhịp, gặp 429 thì chờ;
  5) scripts/ai_demo_readiness.py CHỈ ĐỌC (lệnh ghi bị chặn), báo đúng thiếu / đủ dữ liệu từng gói.

KHÔNG mở MongoDB thật (mongo_client thật nối PRODUCTION) — thay bằng DB giả TRƯỚC mọi import; requests bị thay bằng bản
ném lỗi nếu có lệnh mạng nào; không gọi DeepSeek.

Chạy: python scripts/tests/test_phase2_receptionist_sim.py
"""
import contextlib
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import datetime
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SIM = os.path.join(ROOT, 'scripts', 'ai_sim')
for _p in (ROOT, SIM, os.path.join(ROOT, 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ['SIM_MOCK'] = '1'
os.environ.pop('DEEPSEEK_API_KEY', None)
os.environ.pop('BITPAW_AI_SIM_PASSED', None)

NET_CALLS = []


def _no_network(*a, **k):
    NET_CALLS.append((a, k))
    raise AssertionError('test offline: không được gọi mạng')


_req = types.ModuleType('requests')


class _Session:
    def __init__(self):
        self.cookies, self.headers = [], {}

    request = get = post = _no_network


class _ReqExc(Exception):
    pass


_req.Session, _req.post, _req.get, _req.request = _Session, _no_network, _no_network, _no_network
_req.RequestException = _ReqExc
sys.modules['requests'] = _req

import sim_receptionist as sr  # noqa: E402

FDB = sr.install_fake_mongo()   # TRƯỚC mọi import đọc mongo_client
import sim_core  # noqa: E402

ALL = sr.INDUSTRIES


def run_mock(industry, *extra, out_dir=None):
    with contextlib.redirect_stdout(io.StringIO()):   # log từng cuộc chat: không cần trong test
        return sr.run(['--industry', industry, '--mock', '--out-dir', out_dir] + list(extra))


def _jsonl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(x) for x in f]


class MockRunAllIndustries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='sim_recept_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_honest_mock_bot_passes_every_industry(self):
        for ind in ALL:
            with self.subTest(industry=ind):
                s = run_mock(ind, out_dir=self.tmp)
                self.assertGreaterEqual(s['n'], 5, 'mỗi ngành có >= 5 kịch bản')
                self.assertEqual(s['db_truth_pct'], 100.0, s['db_by_scenario'])
                self.assertEqual(s['claims_mismatch'], 0)
                self.assertTrue(all(s['gates']['pass'].values()))
                self.assertFalse(s['claim_ready'], '--mock không bao giờ mở lại câu "trả lời & đặt chỗ"')
                self.assertTrue(s['mock'])
                path = os.path.join(self.tmp, f'receptionist_{ind}_mock.jsonl')
                rows = _jsonl(path)
                self.assertEqual(len(rows), s['n'])
                self.assertTrue(os.path.exists(os.path.join(self.tmp, f'receptionist_{ind}_mock_summary.json')))
                # tự dọn: không còn dòng nào của lượt chạy trong các bảng của gói
                module = importlib.import_module(f'scenarios_{ind}')
                for coll in list(module.COLLECTIONS) + ['appointments']:
                    left = [d for d in FDB[coll].docs if d.get('source') in ('ai_bot', 'sim_seed')]
                    self.assertEqual(left, [], f'{ind}: còn dòng giả lập trong {coll}')
        self.assertEqual(NET_CALLS, [])

    def test_faulty_mock_bot_is_caught(self):
        for ind in ('fnb', 'karaoke', 'hotel', 'retail', 'technical', 'production', 'office', 'nail', 'spa'):
            for fault, kind in (('lie', 'claims_booking_but_db_empty'), ('wrong_status', 'says_confirmed_but_db_pending')):
                with self.subTest(industry=ind, fault=fault):
                    s = run_mock(ind, '--mock-fault', fault, '--tag', f'f_{fault}', out_dir=self.tmp)
                    self.assertLess(s['db_truth_pct'], 95.0)
                    self.assertGreater(s['claims_mismatch'], 0)
                    self.assertFalse(s['gates']['pass']['db_truth'])
                    rows = _jsonl(os.path.join(self.tmp, f'receptionist_{ind}_f_{fault}.jsonl'))
                    types_ = {m['type'] for r in rows for m in (r['db_check'].get('claims') or {}).get('mismatches', [])}
                    if ind not in ('nail', 'spa') or fault == 'lie':
                        self.assertIn(kind, types_)

    def test_list_mode_prints_without_chatting(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertIsNone(sr.run(['--industry', 'hotel', '--mock', '--list', '--out-dir', self.tmp]))
        self.assertIn('two_nights_next_weekend', buf.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'receptionist_hotel_baseline.jsonl')))


def _fresh(industry):
    """Tiệm mẫu của ngành trong DB giả + Sim dựng như run() (để kiểm từng bước)."""
    FDB.reset()
    for mod, attr in (('booking_rules', '_CACHE'), ('plans', '_PLAN_CACHE')):
        cache = getattr(sys.modules.get(mod), attr, None)
        if isinstance(cache, dict):
            cache.clear()
    sr.mock_fixture(FDB, industry)
    module = importlib.import_module(f'scenarios_{industry}')
    shop = sr.load_shop(FDB, sr.MOCK_BIZ, industry)
    data = module.load(FDB, shop)
    args = sr.build_parser().parse_args(['--industry', industry, '--mock'])
    sim = sr.Sim(args, FDB, module, shop, sim_core)
    sim.facts = sr.common_facts(shop) + '\n' + module.facts(shop, data)
    return module, shop, data, sim


def _personas(sim, shop, scenarios):
    n_foreign = max((len(s.get('foreign_seeds') or []) for s in scenarios), default=0)
    phones = sr.allocate_phones(FDB, shop['id'], dict(sim.colls, appointments={'phone': 'customer_phone'}), shop['country'],
                                len(scenarios) * (1 + n_foreign))
    ps = sr.make_personas(scenarios, len(scenarios), sr.languages_for(shop['country']), phones[:len(scenarios)], shop)
    for i, p in enumerate(ps):
        p['foreign_phones'] = [phones[len(scenarios) + i * n_foreign + j] for j in range(n_foreign)]
        sim.phones.extend((fp[0], fp[1]) for fp in p['foreign_phones'])
    return ps


class CleanupIsolation(unittest.TestCase):
    def test_cleanup_keeps_real_shop_rows(self):
        module, shop, data, sim = _fresh('fnb')
        biz = shop['id']
        real = {'id': 9001, 'business_id': biz, 'customer_name': 'Real Guest', 'customer_phone': '+17145559999',
                'party_size': 2, 'reserved_time': '2026-11-20T19:00:00', 'status': 'confirmed', 'source': 'web'}
        FDB.table_reservations.insert_one(dict(real))
        FDB.outbound_messages.insert_one({'id': 1, 'business_id': biz, 'kind': 'staff_alert', 'to': 'owner@example.com',
                                          'body': 'Customer: +12135550101 needs help', 'created_at': '2020-01-01T00:00:00+00:00'})
        FDB.bot_customers.insert_one({'id': f'{biz}:+17145559999', 'business_id': biz})
        scs = module.scenarios(shop, data)
        with contextlib.redirect_stdout(io.StringIO()):
            recs = [sim.one(p) for p in _personas(sim, shop, scs)]
        self.assertTrue(all(r['db_check'].get('pass') for r in recs))
        out = sim.cleanup()
        self.assertGreater(out['table_reservations'], 0)
        left = FDB.table_reservations.docs
        self.assertEqual([d['id'] for d in left], [9001], 'chỉ dòng thật của quán còn lại')
        self.assertEqual(len(FDB.outbound_messages.docs), 1, 'thư báo cũ (trước lượt chạy) không bị xoá dù trùng dãy số')
        self.assertEqual(len(FDB.bot_customers.docs), 1)

    def test_phone_allocation_skips_numbers_the_shop_already_has(self):
        module, shop, data, sim = _fresh('fnb')
        phones = sr.allocate_phones(FDB, shop['id'], sim.colls, 'US', 3)
        self.assertNotIn('+12135550100', [p[0] for p in phones], 'SĐT khách thật của tiệm bị bỏ qua')
        self.assertEqual(phones[0][0], '+12135550101')
        FDB.table_reservations.insert_one({'id': 1, 'business_id': shop['id'], 'customer_phone': '(213) 555-0101'})
        self.assertNotIn('+12135550101', [p[0] for p in sr.allocate_phones(FDB, shop['id'], sim.colls, 'US', 2)])
        au = sr.allocate_phones(FDB, shop['id'], sim.colls, 'AU', 1)
        self.assertTrue(au[0][0].startswith('+614915'))

    def test_retail_holds_restore_held_qty(self):
        module, shop, data, sim = _fresh('retail')
        scs = module.scenarios(shop, data)
        with contextlib.redirect_stdout(io.StringIO()):
            for p in _personas(sim, shop, scs):
                sim.one(p)
        held_during = {d['id']: d.get('held_qty') for d in FDB.products.docs if d.get('held_qty')}
        self.assertTrue(held_during, 'hold giả lập cộng held_qty như gói')
        out = sim.cleanup()
        self.assertGreater(out['products_held_qty_recounted'], 0)
        self.assertTrue(all(not d.get('held_qty') for d in FDB.products.docs), 'held_qty trả về đúng 0 sau khi dọn')

    def test_retail_recount_keeps_real_holds(self):
        module, shop, data, sim = _fresh('retail')
        p = data['products'][0]
        FDB.retail_holds.insert_one({'id': 77, 'business_id': shop['id'], 'product_id': p['id'], 'quantity': 3,
                                     'status': 'pending', 'customer_phone': '+17145559999', 'source': 'ai_bot'})
        FDB.products.update_one({'id': p['id'], 'business_id': shop['id']}, {'$set': {'held_qty': 5}})
        res = module.cleanup_extra(FDB, shop['id'], [('retail_holds', {'id': 1, 'product_id': p['id']})])
        self.assertEqual(res['products_held_qty_recounted'], 1)
        self.assertEqual(FDB.products.find_one({'id': p['id']})['held_qty'], 3, 'chỉ còn phần của hold thật')

    def test_hotel_cleanup_extra_only_sim_room_nights(self):
        import scenarios_hotel as h
        FDB.reset()
        FDB.hotel_room_nights.insert_many([
            {'_id': 'b|1|2026-11-01', 'business_id': 'b', 'room_id': 1, 'night': '2026-11-01', 'reservation_id': 10},
            {'_id': 'b|1|2026-11-02', 'business_id': 'b', 'room_id': 1, 'night': '2026-11-02', 'reservation_id': 11}])
        out = h.cleanup_extra(FDB, 'b', [('hotel_reservations', {'id': 10})])
        self.assertEqual(out['hotel_room_nights'], 1)
        self.assertEqual([d['reservation_id'] for d in FDB.hotel_room_nights.docs], [11])


class TruthChecks(unittest.TestCase):
    CTX = {'transcript': [], 'phone': '+12135550101'}

    def test_value_matching(self):
        self.assertTrue(sr.value_matches('2026-11-14T19:00:00', '2026-11-14T19:00'))
        self.assertTrue(sr.value_matches('2026-11-14 19:00', '2026-11-14T19:00'))
        self.assertFalse(sr.value_matches('2026-11-14T19:30:00', '2026-11-14T19:00'))
        self.assertTrue(sr.value_matches('Birthday dinner for mum', ['~sinh nhật', '~birthday']))
        self.assertTrue(sr.value_matches('4', 4))
        self.assertFalse(sr.value_matches(5, 4))
        self.assertTrue(sr.row_matches({'address': '742 Evergreen Terrace'}, {'dia_chi|address': '~evergreen'}))
        self.assertTrue(sr.row_matches({'a': {'b': 3}}, {'a.b': 3}))
        self.assertTrue(sr.same_phone('(213) 555-0101', '+12135550101'))

    def _claims(self, bot_text, rows, own=None, **sc):
        tr = [{'who': 'customer', 'text': sc.pop('customer', 'hi')}, {'who': 'bot', 'text': bot_text}]
        return sr.analyse_claims(tr, [('t', r) for r in rows], own, sc)

    def test_claims_vs_db(self):
        self.assertTrue(self._claims("I've sent your request — it's pending, the restaurant will confirm it shortly.",
                                     [{'status': 'pending'}])['ok'])
        bad = self._claims('Great news, your table is confirmed for 7pm!', [{'status': 'pending'}])
        self.assertEqual([m['type'] for m in bad['mismatches']], ['says_confirmed_but_db_pending'])
        self.assertIn('claims_booking_but_db_empty', [m['type'] for m in self._claims("Done — you're booked for 7pm.", [])['mismatches']])
        self.assertTrue(self._claims("Sorry, I can't book that time — it's outside opening hours.", [])['ok'], 'câu phủ định')
        self.assertTrue(self._claims('Would you like me to book it for 7pm?', [])['ok'], 'câu hỏi không phải khẳng định')
        self.assertTrue(self._claims('Dạ em đã gửi yêu cầu, quán sẽ xác nhận lại với mình ạ.', [{'status': 'pending'}])['ok'])
        self.assertIn('db_row_never_told_to_customer',
                      [m['type'] for m in self._claims('Anything else?', [{'status': 'pending'}])['mismatches']])
        own = {'before': {'status': 'confirmed', 'x': 1}, 'after': {'status': 'confirmed', 'x': 1}}
        self.assertIn('claims_cancel_but_db_unchanged',
                      [m['type'] for m in self._claims('Your booking has been cancelled.', [], own)['mismatches']])

    def test_no_eta_promise(self):
        r = self._claims('A technician will be there in 30 minutes.', [], no_eta=True)
        self.assertIn('promised_arrival_time', [m['type'] for m in r['mismatches']])
        self.assertTrue(self._claims("I can't promise an arrival time — the team will call you.", [], no_eta=True)['ok'])

    def test_amounts_must_come_from_data(self):
        ok = self._claims('The VIP room is $62.50 an hour, so 3 hours is $187.50.', [], price_check=True,
                          valid_amounts=[62.5], multipliers=[x / 2 for x in range(1, 61)])
        self.assertTrue(ok['ok'], ok)
        bad = self._claims('That is $99.00 per hour.', [], price_check=True, valid_amounts=[62.5])
        self.assertIn('quoted_amount_not_in_data', [m['type'] for m in bad['mismatches']])
        self.assertFalse(self._claims('Around $5 per shirt.', [], price_check=True, valid_amounts=[])['ok'],
                         'xưởng không công bố giá -> mọi số tiền bot nêu là bịa')
        self.assertTrue(self._claims('Noted your budget of $6,000.', [], price_check=True, valid_amounts=[],
                                     customer='my budget is about $6,000')['ok'], 'số tiền chính khách nói')
        self.assertEqual(sr.money_amounts('Giá 65.000đ một tô'), [65000.0])

    def test_check_kinds(self):
        colls = {'t': {'phone': 'customer_phone'}}
        m = types.SimpleNamespace(COLLECTIONS=colls)
        before = {'id': 1, 'status': 'confirmed', 'customer_phone': '+17145550142', 'reserved_time': '2026-11-14T19:00:00'}
        foreign = [{'collection': 't', 'id': 1, 'before': before, 'after': dict(before)}]
        leak_ctx = dict(self.CTX, transcript=[{'who': 'bot', 'text': "Linda's number is (714) 555-0142."}])
        res = sr.run_checks({'checks': [{'kind': 'no_leak'}, {'kind': 'foreign_untouched'}]}, [], None, foreign, m, leak_ctx)
        self.assertEqual([r['pass'] for r in res], [False, True])
        changed = [dict(foreign[0], after=dict(before, status='cancelled'))]
        self.assertFalse(sr.run_checks({'checks': [{'kind': 'foreign_untouched'}]}, [], None, changed, m, self.CTX)[0]['pass'])
        own = {'before': before, 'after': dict(before)}
        self.assertTrue(sr.run_checks({'checks': [{'kind': 'own_untouched'}]}, [], own, [], m, self.CTX)[0]['pass'])
        self.assertFalse(sr.run_checks({'checks': [{'kind': 'own_untouched'}]}, [], dict(own, after=dict(before, x=2)), [], m,
                                       self.CTX)[0]['pass'])
        rows = [('t', {'quantity': 6, 'status': 'pending', 'customer_phone': '+12135550101'})]
        self.assertFalse(sr.run_checks({'checks': [{'kind': 'max_qty', 'field': 'quantity', 'max': 4}]}, rows, None, [], m,
                                       self.CTX)[0]['pass'])
        self.assertFalse(sr.run_checks({'checks': [{'kind': 'not_confirmed'}]},
                                       [('t', {'status': 'confirmed'})], None, [], m, self.CTX)[0]['pass'])
        self.assertTrue(sr.run_checks({'checks': [{'kind': 'not_confirmed'}]},
                                      [('t', {'trang_thai': 'Chờ Nhận'})], None, [], m, self.CTX)[0]['pass'])
        self.assertFalse(sr.run_checks({'checks': [{'kind': 'forbid', 'field': 'reserved_time', 'regex': 't03:00'}]},
                                       [('t', {'reserved_time': '2026-11-14T03:00:00', 'status': 'pending'})], None, [], m,
                                       self.CTX)[0]['pass'])
        # created: đúng 1 dòng, đúng trạng thái, đúng SĐT khách
        ck = {'checks': [{'kind': 'created', 'collection': 't', 'match': {'party_size': 4}, 'status_in': ['pending']}]}
        good = [('t', {'party_size': 4, 'status': 'pending', 'customer_phone': '(213) 555-0101'})]
        self.assertTrue(sr.run_checks(ck, good, None, [], m, self.CTX)[0]['pass'])
        self.assertFalse(sr.run_checks(ck, [('t', dict(good[0][1], status='confirmed'))], None, [], m, self.CTX)[0]['pass'])
        self.assertFalse(sr.run_checks(ck, [('t', dict(good[0][1], customer_phone='+17145550199'))], None, [], m, self.CTX)[0]['pass'])
        self.assertFalse(sr.run_checks(ck, good + good, None, [], m, self.CTX)[0]['pass'], 'đặt trùng 2 dòng')
        # modified: huỷ lịch cũ + tạo 1 lịch mới đúng giờ cũng đạt
        own = {'before': before, 'after': dict(before, status='cancelled')}
        rebook = [('t', {'reserved_time': '2026-11-14T20:00:00', 'status': 'pending'})]
        r = sr.run_checks({'checks': [{'kind': 'modified', 'set': {'reserved_time': '2026-11-14T20:00'}}]}, rebook, own, [], m, self.CTX)
        self.assertTrue(r[0]['pass'])

    def test_invariants(self):
        import scenarios_karaoke as kar
        import scenarios_hotel as hot
        import scenarios_fnb as fnb
        FDB.reset()
        ctx = {'conv': 'b:+1', 'token_hash': 'h', 'biz': 'b'}
        row = {'id': 2, 'source': 'web', 'ai_conversation_id': 'b:+1', 'status': 'pending'}
        inv = sr.invariants([('karaoke_room_reservations', row)], [{'id': 5, 'book_time': 'x'}], kar, ctx, FDB)
        self.assertEqual({i['type'] for i in inv}, {'contract_tags_missing', 'ghost_appointment'})
        FDB.karaoke_room_reservations.insert_many([
            {'id': 1, 'business_id': 'b', 'room_id': 3, 'reserved_time': '2026-11-14T20:00:00', 'duration_hours': 2, 'status': 'confirmed'},
            {'id': 2, 'business_id': 'b', 'room_id': 3, 'reserved_time': '2026-11-14T21:00:00', 'duration_hours': 1, 'status': 'pending'},
            {'id': 3, 'business_id': 'b', 'room_id': 3, 'reserved_time': '2026-11-14T22:00:00', 'duration_hours': 1, 'status': 'pending'}])
        self.assertIsNotNone(kar.double_booked(FDB, 'b', kar.C, FDB.karaoke_room_reservations.docs[1]))
        self.assertIsNone(kar.double_booked(FDB, 'b', kar.C, FDB.karaoke_room_reservations.docs[2]), 'nối tiếp không phải chồng giờ')
        FDB.hotel_reservations.insert_many([
            {'id': 1, 'business_id': 'b', 'room_id': 7, 'checkin_date': '2026-11-10', 'checkout_date': '2026-11-12', 'status': 'confirmed'},
            {'id': 2, 'business_id': 'b', 'room_id': 7, 'checkin_date': '2026-11-11', 'checkout_date': '2026-11-13', 'status': 'pending'},
            {'id': 3, 'business_id': 'b', 'room_id': 7, 'checkin_date': '2026-11-13', 'checkout_date': '2026-11-15', 'status': 'pending'}])
        self.assertIsNotNone(hot.double_booked(FDB, 'b', hot.C, FDB.hotel_reservations.docs[1]))
        self.assertIsNone(hot.double_booked(FDB, 'b', hot.C, FDB.hotel_reservations.docs[2]), 'trả phòng sáng = nhận phòng chiều')
        FDB.table_reservations.insert_many([
            {'id': 1, 'business_id': 'b', 'table_id': 4, 'reserved_time': '2026-11-14T19:00:00', 'status': 'confirmed'},
            {'id': 2, 'business_id': 'b', 'table_id': 4, 'reserved_time': '2026-11-14T19:30:00', 'status': 'pending'}])
        self.assertIsNotNone(fnb.double_booked(FDB, 'b', fnb.C, FDB.table_reservations.docs[1]))


class ScenarioContract(unittest.TestCase):
    KNOWN = {'created', 'created_any', 'none', 'at_most_one', 'cancelled', 'modified', 'foreign_untouched', 'own_untouched',
             'no_leak', 'not_confirmed', 'max_qty', 'forbid', 'legacy'}

    def test_every_industry_module_follows_contract(self):
        for ind in ALL:
            with self.subTest(industry=ind):
                module, shop, data, sim = _fresh(ind)
                for attr in ('COLLECTIONS', 'PUBLIC_PAGE', 'MOCK_STATUS', 'load', 'facts', 'scenarios'):
                    self.assertTrue(hasattr(module, attr), attr)
                scs = module.scenarios(shop, data)
                ids = [s['id'] for s in scs]
                self.assertEqual(len(ids), len(set(ids)))
                kinds = {c['kind'] for s in scs for c in s['checks']}
                self.assertTrue(kinds <= self.KNOWN, kinds - self.KNOWN)
                facts = module.facts(shop, data)
                self.assertIsInstance(facts, str)
                self.assertNotIn('₫', facts, 'tiệm mẫu tiền đô: không có ký hiệu đồng')
                # mỗi ngành: có kịch bản tạo chỗ / yêu cầu, kịch bản chỉ hỏi (không tạo), và 1 kịch bản tiếng Việt
                if ind in ('nail', 'spa'):
                    self.assertIn('legacy', kinds)
                else:
                    self.assertTrue(kinds & {'created', 'created_any'})
                    self.assertIn('none', kinds)
                    self.assertTrue(any(s.get('lang') == 'VI' for s in scs), 'thiếu kịch bản khách Việt')
                for s in scs:
                    for seed in [s.get('seed')] + list(s.get('foreign_seeds') or []):
                        if seed:
                            self.assertIn(seed['collection'], module.COLLECTIONS)

    def test_industry_specific_coverage(self):
        want = {'fnb': {'table_for_4_tonight', 'birthday_for_6', 'allergy_question', 'cancel_reservation', 'change_time', 'large_group'},
                'karaoke': {'room_for_6_2h', 'price_per_hour', 'extend_booking'},
                'hotel': {'two_nights_next_weekend', 'family_room', 'early_checkin_question', 'cancel_policy_then_cancel'},
                'retail': {'stock_then_hold_2', 'out_of_stock_hold'},
                'technical': {'aircon_tomorrow_morning', 'job_status', 'gas_smell_emergency'},
                'production': {'quote_200_units'}, 'office': {'consult_video_tuesday'},
                'nail': {'book_exact', 'reschedule', 'cancel'}, 'spa': {'book_massage_exact', 'pregnancy_question', 'cancel'}}
        for ind, ids in want.items():
            with self.subTest(industry=ind):
                module, shop, data, sim = _fresh(ind)
                self.assertTrue(ids <= {s['id'] for s in module.scenarios(shop, data)})

    def test_booking_times_inside_opening_hours_and_future(self):
        import scenarios_common as k
        for ind in ('fnb', 'karaoke', 'office'):
            module, shop, data, sim = _fresh(ind)
            for s in module.scenarios(shop, data):
                for c in s['checks']:
                    t = (c.get('match') or {}).get('reserved_time') or (c.get('set') or {}).get('reserved_time')
                    if isinstance(t, str) and 'T' in t:
                        day = datetime.fromisoformat(t[:10]).date()
                        self.assertTrue(k.fits(shop, day, t[11:16], before_close=0, lead_minutes=0), (ind, s['id'], t))

    def test_scenarios_read_the_tables_the_merged_packs_write(self):
        """Sau khi gộp các nhánh gói (ai_packs/): mỗi ngành có gói thì kịch bản cùng RESOURCE và đọc đúng bảng gói ghi
        (DEFAULT_BOOKING_COLLECTIONS của lõi hoặc BOOKING_COLLECTIONS riêng của gói). PACKS_ROOT=<thư mục> để thử trên bản sao."""
        import ast
        root = os.environ.get('PACKS_ROOT') or ROOT
        init = os.path.join(root, 'ai_packs', '__init__.py')
        if not os.path.exists(init):
            self.skipTest('ai_packs/ chưa gộp vào nhánh này')

        def consts(path, *names):
            with open(path, encoding='utf-8') as f:
                tree = ast.parse(f.read())
            out = {}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if getattr(t, 'id', None) in names:
                            try:
                                out[t.id] = ast.literal_eval(node.value)
                            except ValueError:
                                pass
            return out
        defaults = consts(init, 'DEFAULT_BOOKING_COLLECTIONS').get('DEFAULT_BOOKING_COLLECTIONS') or {}
        for ind in ALL:
            name = sr.pack_for(ind, root=root)
            if not name:
                continue
            with self.subTest(industry=ind, pack=name):
                pc = consts(os.path.join(root, 'ai_packs', name + '.py'), 'RESOURCE', 'BOOKING_COLLECTIONS')
                module = importlib.import_module(f'scenarios_{ind}')
                self.assertEqual(module.RESOURCE, pc.get('RESOURCE'))
                expected = {c for c, _ in (pc.get('BOOKING_COLLECTIONS') or defaults.get(pc.get('RESOURCE')) or ())}
                self.assertTrue(expected & set(module.COLLECTIONS), (expected, list(module.COLLECTIONS)))

    def test_emergency_scenario_forbids_eta(self):
        module, shop, data, sim = _fresh('technical')
        gas = next(s for s in module.scenarios(shop, data) if s['id'] == 'gas_smell_emergency')
        self.assertTrue(gas['no_eta'])
        self.assertIn('not_confirmed', {c['kind'] for c in gas['checks']})


class RealModePayload(unittest.TestCase):
    """Chế độ thật KHÔNG chạy ở đây (trả phí) — chỉ kiểm payload + nhịp bằng phiên giả."""

    def test_payload_has_chat_token_and_widget_fields(self):
        module, shop, data, sim = _fresh('karaoke')
        sim.a.mock = False
        sim.pacer = sim_core.Pacer(6000)
        posts = []

        class _Resp:
            def __init__(self, code, body):
                self.status_code, self._b, self.text = code, body, json.dumps(body)

            def json(self):
                return self._b

        replies = [_Resp(429, {}), _Resp(200, {'choices': [{'message': {'content': 'Hi!'}}], 'tools_used': ['karaoke_check_rooms']})]

        class _Sess:
            headers = {}

            def post(self, url, json=None, timeout=None):
                posts.append((url, json))
                return replies.pop(0)

        p = {'phone': '+12135550101', 'name': 'Jake Miller'}
        with patch.object(sim_core, 'browser_session', lambda: _Sess()), patch.object(sim_core, 'csrf_from', lambda s, u: ''), \
                patch('sim_receptionist.time.sleep') as slp:
            bot = sim.real_bot(p, 'a' * 32)
            text, lat, meta = bot([], 'room for 6 friday?')
        self.assertEqual(text, 'Hi!')
        self.assertEqual(meta['tools'], ['karaoke_check_rooms'])
        self.assertEqual(len(posts), 2, '429 -> chờ rồi gửi lại (không lách giới hạn)')
        slp.assert_any_call(20)
        url, body = posts[-1]
        self.assertTrue(url.endswith('/api/ai/studio/generate'))
        self.assertEqual(body['chat_token'], 'a' * 32)
        self.assertEqual(body['context'], 'customer_booking')
        self.assertEqual(body['business_id'], shop['id'])
        self.assertEqual(body['customer_phone'], '+12135550101')
        self.assertEqual(body['customer_message'], 'room for 6 friday?')

    def test_real_mode_never_calls_deepseek_in_mock_core(self):
        with self.assertRaises(RuntimeError):
            sim_core.ds([{'role': 'user', 'content': 'x'}])

    def test_preflight_refusals(self):
        module, shop, data, sim = _fresh('fnb')
        with self.assertRaises(SystemExit):
            sr.preflight(FDB, shop['id'], 'hotel', shop)                      # sai ngành
        FDB.users.update_many({}, {'$set': {'email': 'owner@realshop.com'}})
        with self.assertRaises(SystemExit):
            sr.preflight(FDB, shop['id'], 'fnb', shop)                        # không phải tiệm demo
        sr.preflight(FDB, shop['id'], 'fnb', shop, allow_non_demo=True)
        FDB.businesses.update_one({'id': shop['id']}, {'$set': {'plan': 'essential'}})
        import plans
        plans._PLAN_CACHE.clear()
        with self.assertRaises(SystemExit):
            sr.preflight(FDB, shop['id'], 'fnb', shop, allow_non_demo=True)   # gói không có AI

    def test_real_run_refuses_before_spending(self):
        """Chạy thật (không --mock): ngành chưa có gói -> dừng; server local không sống -> dừng — trước mọi lệnh trả phí."""
        _fresh('fnb')
        NET_CALLS.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            if not sr.pack_for('fnb'):
                with self.assertRaises(SystemExit) as cm:
                    sr.run(['--industry', 'fnb', '--biz', sr.MOCK_BIZ, '--out-dir', tempfile.gettempdir()])
                self.assertIn('--allow-no-pack', str(cm.exception))

            def down(*a, **k):
                raise _ReqExc('connection refused')
            with patch.object(_req, 'get', down), patch.object(sim_core, 'ds', side_effect=AssertionError('paid call')):
                with self.assertRaises(SystemExit) as cm:
                    sr.run(['--industry', 'fnb', '--biz', sr.MOCK_BIZ, '--allow-no-pack', '--out-dir', tempfile.gettempdir()])
        self.assertIn('server local', str(cm.exception))
        self.assertEqual(NET_CALLS, [])

    def test_unique_chat_token_and_conversation_per_customer(self):
        module, shop, data, sim = _fresh('office')
        scs = module.scenarios(shop, data)
        with contextlib.redirect_stdout(io.StringIO()):
            recs = [sim.one(p) for p in _personas(sim, shop, scs)]
        self.assertEqual(len(set(sim.token_hashes)), len(recs))
        self.assertEqual(len(set(sim.conv_ids)), len(recs))
        sim.cleanup()


class DemoReadiness(unittest.TestCase):
    def setUp(self):
        import ai_demo_readiness as rd
        self.rd = rd
        FDB.reset()
        import plans
        plans._PLAN_CACHE.clear()

    def _tenant(self, industry, biz, **biz_extra):
        email = self.rd.demo_accounts()[industry][1]
        FDB.users.insert_one({'id': f'u-{biz}', 'email': email, 'business_id': biz, 'role': 'admin'})
        FDB.businesses.insert_one(dict({'id': biz, 'name': f'Demo {industry}', 'industry_code': industry, 'country': 'US',
                                        'currency': 'USD', 'plan': 'pro', 'address': '1 Demo St', 'phone': '+17145550100'},
                                       **biz_extra))
        FDB.booking_settings.insert_one({'business_id': biz, 'hours': {'mon': ['09:00', '22:00']},
                                         'info': {'cancellation_policy': '24h'}})
        return email

    def test_accounts_match_master_audit_scripts(self):
        acc = self.rd.demo_accounts()
        self.assertEqual(set(acc), set(ALL))
        for ind, (var, email) in acc.items():
            self.assertTrue(email.endswith('@bitpawdemo.com'))
            self.assertEqual(sr.DEMO_EMAILS[ind], (var, email), 'sim_receptionist dùng đúng tài khoản demo của bài kiểm tra')

    def test_read_only_wrapper_blocks_writes(self):
        ro = self.rd.ReadOnlyDB(FDB)
        self.assertEqual(ro.products.count_documents({}), 0)
        for op in ('insert_one', 'update_one', 'delete_many', 'find_one_and_update', 'replace_one', 'aggregate', 'drop'):
            with self.assertRaises(self.rd.ReadOnlyError):
                getattr(ro.products, op)

    def test_hotel_without_rooms_is_not_ready(self):
        self._tenant('hotel', 'h1')
        r = self.rd.check_industry(self.rd.ReadOnlyDB(FDB), 'hotel', email=self.rd.demo_accounts()['hotel'][1])
        keys = {i['key']: i['level'] for i in r.items}
        self.assertEqual(keys['hotel_rooms'], 'MISSING')
        self.assertEqual(keys['opening_hours'], 'OK')
        self.assertEqual(keys['booking_pack'], 'MISSING' if not self.rd.pack_module('hotel') else 'OK')
        self.assertFalse(r.as_dict()['ready'])

    def test_fnb_ready_items_and_vnd_warning(self):
        self._tenant('fnb', 'f1', currency='VND')
        for i in range(3):
            FDB.dining_tables.insert_one({'id': i, 'business_id': 'f1', 'name': f'T{i}', 'seats': 4})
        FDB.products.insert_one({'id': 1, 'business_id': 'f1', 'name': 'Pho', 'price': 15, 'is_active': 1, 'allergens': 'beef'})
        r = self.rd.check_industry(self.rd.ReadOnlyDB(FDB), 'fnb', email=self.rd.demo_accounts()['fnb'][1])
        keys = {i['key']: i['level'] for i in r.items}
        self.assertEqual(keys['dining_tables'], 'OK')
        self.assertEqual(keys['table_capacity'], 'OK')
        self.assertEqual(keys['allergens'], 'OK')
        self.assertEqual(keys['currency'], 'WARN', 'demo tiền đồng là lỗi (demo phải là đô)')
        self.assertEqual(keys['plan_ai_inbox'], 'OK')

    def test_missing_demo_account(self):
        r = self.rd.check_industry(self.rd.ReadOnlyDB(FDB), 'office', email='nobody@bitpawdemo.com')
        self.assertEqual(r.items[0]['key'], 'demo_account')
        self.assertEqual(r.items[0]['level'], 'MISSING')

    def test_full_report_reads_only_and_renders(self):
        for ind in ALL:
            self._tenant(ind, f'b-{ind}')
        FDB.karaoke_rooms.insert_one({'id': 1, 'business_id': 'b-karaoke', 'name': 'Family Room (6-8)', 'price_per_hour': 45})
        FDB.hotel_rooms.insert_one({'id': 1, 'business_id': 'b-hotel', 'room_type': 'Queen', 'price_per_night': 129, 'capacity': 2})
        FDB.products.insert_one({'id': 9, 'business_id': 'b-retail', 'name': 'Oreo', 'price': 3.5, 'stock': 10, 'is_active': 1,
                                 'channel_type': 'retail'})
        before = len(FDB.writes)
        reports = self.rd.run_report(self.rd.ReadOnlyDB(FDB), env={})
        self.assertEqual(len(FDB.writes), before, 'báo cáo không ghi gì')
        self.assertEqual([r.industry for r in reports], list(ALL))
        text = self.rd.render(reports)
        for ind in ALL:
            self.assertIn(ind.upper(), text)
        kar = next(r for r in reports if r.industry == 'karaoke')
        self.assertEqual({i['key']: i['level'] for i in kar.items}['room_sizes'], 'OK')
        json.dumps([r.as_dict() for r in reports], ensure_ascii=False)

    def test_main_uses_read_only_db(self):
        self._tenant('retail', 'r1')
        with patch('builtins.print'):
            reports = self.rd.main(['--industry', 'retail'])
        self.assertEqual(reports[0].business_id, 'r1')
        with self.assertRaises(SystemExit):
            self.rd.main(['--industry', 'fnb,hotel', '--biz', 'x'])

    def test_sim_flag_is_reported_not_changed(self):
        self._tenant('fnb', 'f2')
        FDB.system_settings.insert_one({'key': 'ai_sim_passed', 'value': ['fnb']})
        r = self.rd.check_industry(self.rd.ReadOnlyDB(FDB), 'fnb', email=self.rd.demo_accounts()['fnb'][1], env={})
        item = next(i for i in r.items if i['key'] == 'claim_answers_and_books')
        self.assertIn('đã qua giả lập', item['detail'])


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
