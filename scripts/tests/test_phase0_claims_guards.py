# -*- coding: utf-8 -*-
"""Test OFFLINE cho Phase 0 "claims, guards, credentials":
1. Thẻ giá (plans.py) nói đúng sự thật theo ngành: Pro "trả lời & đặt lịch" CHỈ nail/spa; ngành khác "trả lời & chuyển yêu cầu";
   bỏ "xoay tua thợ công bằng" (chưa có).
2. Bot bán hàng (ai_sales_prompts): không còn giá cũ $99/$299/$599 + setup, không còn câu sai "hotel online booking NOT available",
   chỉ nạp dòng giá của ĐÚNG ngành trang đang xem (cả 9 dòng chỉ ở landing chung).
3. /api/ai/copilot: chỉ admin/super_admin — nhân viên nhận 403 kèm lời nhắn rõ (VI/EN).
4. Script test/QA không còn ghi cứng email + mật khẩu super admin: đọc biến môi trường, thiếu thì dừng với lời nhắn rõ.

KHÔNG import app.py, KHÔNG mở MongoDB (mongo_client bị stub trước mọi import), KHÔNG gọi DeepSeek/API thật, KHÔNG chạy server.
Chạy: python scripts/tests/test_phase0_claims_guards.py
"""
import ast
import io
import os
import re
import subprocess
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------- stub TRƯỚC mọi import của module thật
sys.modules['mongo_client'] = types.SimpleNamespace(db=MagicMock(name='db'), next_mongo_id=lambda c: 1, MONGO_STATUS='CONNECTED')
_ds = types.ModuleType('ai_deepseek_client')
_ds.deepseek_chat_completion = MagicMock(side_effect=AssertionError('DeepSeek must not be called in tests'))
sys.modules['ai_deepseek_client'] = _ds

from flask import Flask, jsonify, request, session  # noqa: E402

import plans  # noqa: E402
import ai_sales_prompts  # noqa: E402

with io.open(os.path.join(ROOT, 'app.py'), encoding='utf-8') as _fh:
    APP_SRC = _fh.read()
_APP_TREE = ast.parse(APP_SRC)


def _fn_node(name, tree=_APP_TREE):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _robot_item(card):
    return next(it for it in card['items'] if it[0] == 'fa-robot')


# ================================================================ 1. plans.py card text
class PlanCardClaimTests(unittest.TestCase):
    def test_only_nail_and_spa_claim_ai_booking(self):
        for ind in plans.INDUSTRY_PRICES:
            pro = next(c for c in plans.tier_cards(ind) if c['key'] == 'pro')
            _ico, vi, en = _robot_item(pro)
            if ind in ('nail', 'spa'):
                self.assertIn('answers & books', en, ind)
                self.assertIn('đặt lịch', vi, ind)
            else:
                self.assertIn('answers questions & passes requests to your team', en, ind)
                self.assertNotIn('book', en.lower(), ind)
                self.assertIn('chuyển yêu cầu cho đội', vi, ind)
                self.assertNotIn('đặt', vi, ind)
            self.assertIn('CRM win-back', en, ind)            # phần còn lại của dòng giữ nguyên
            self.assertIn('CRM nhắc khách cũ quay lại', vi, ind)

    def test_no_fair_turn_rotation_claim_anywhere_on_cards(self):
        for ind in plans.INDUSTRY_PRICES:
            for card in plans.tier_cards(ind):
                for _ico, vi, en in card['items']:
                    self.assertNotIn('turn rotation', en.lower(), (ind, card['key']))
                    self.assertNotIn('xoay tua', vi.lower(), (ind, card['key']))

    def test_nail_essential_keeps_true_lines(self):
        ess = next(c for c in plans.tier_cards('nail') if c['key'] == 'essential')
        ens = [en for _i, _v, en in ess['items']]
        self.assertIn('Automatic tip & commission split', ens)
        self.assertIn('Online booking page + QR code for your salon', ens)
        self.assertEqual(len(ens), 6)   # POS, tip/commission, booking page, time clock, apps, location

    def test_card_shape_and_prices_unchanged(self):
        for ind, tiers in plans.INDUSTRY_PRICES.items():
            for card in plans.tier_cards(ind):
                self.assertEqual(card['monthly']['USD'], tiers[card['key']][0])
                self.assertEqual(card['setup']['USD'], tiers[card['key']][1])
                for item in card['items']:
                    self.assertEqual(len(item), 3)
                    self.assertTrue(all(isinstance(x, str) and x for x in item))

    def test_facts_lines_one_row_per_known_industry(self):
        self.assertEqual(len(plans.facts_lines()), len(plans.INDUSTRY_PRICES))
        self.assertEqual(len(plans.facts_lines('not-an-industry')), len(plans.INDUSTRY_PRICES))
        for ind, tiers in plans.INDUSTRY_PRICES.items():
            rows = plans.facts_lines(ind)
            self.assertEqual(len(rows), 1, ind)
            self.assertTrue(rows[0].startswith(f"- {plans.INDUSTRY_LABELS[ind][1]}:"), rows[0])
            for key in plans.PLAN_ORDER:
                self.assertIn(f"${tiers[key][0]}/mo", rows[0])


# ================================================================ 2. sales bot (ai_sales_prompts)
_ROW_LABELS = [f"- {plans.INDUSTRY_LABELS[i][1]}:" for i in plans.INDUSTRY_PRICES]


class SalesBotHonestyTests(unittest.TestCase):
    with io.open(os.path.join(ROOT, 'ai_sales_prompts.py'), encoding='utf-8') as _fh:
        SRC = _fh.read()

    def test_no_stale_hardcoded_prices_or_false_lines(self):
        for bad in ('$99', '$299', '$599', 'one-time setup)', 'plus a one-time setup',
                    'Online booking and OTA sync are NOT available', 'fair turn rotation'):
            self.assertNotIn(bad, self.SRC, bad)

    def _rows(self, text):
        return [lbl for lbl in _ROW_LABELS if lbl in text]

    def test_known_industry_gets_only_its_own_row(self):
        for ind in plans.INDUSTRY_PRICES:
            facts = ai_sales_prompts.bitpaw_facts(None, None, industry=ind)
            self.assertEqual(self._rows(facts), [f"- {plans.INDUSTRY_LABELS[ind][1]}:"], ind)
            m, s = plans.INDUSTRY_PRICES[ind]['pro']
            self.assertIn(f"${m}/mo", facts)

    def test_hr_page_maps_to_office_row_and_case_is_ignored(self):
        self.assertEqual(self._rows(ai_sales_prompts.bitpaw_facts(None, None, industry='hr')), ['- Office & HR:'])
        self.assertEqual(self._rows(ai_sales_prompts.bitpaw_facts(None, None, industry=' NAIL ')), ['- Nails & Salon:'])

    def test_general_landing_gets_all_rows(self):
        for ind in ('general', None, '', 'unknown', 123, ['nail']):
            facts = ai_sales_prompts.bitpaw_facts(None, None, industry=ind)
            self.assertEqual(len(self._rows(facts)), len(plans.INDUSTRY_PRICES), repr(ind))
        # chữ ký cũ (sim_sales gọi bitpaw_facts(None, None)) vẫn chạy
        self.assertEqual(len(self._rows(ai_sales_prompts.bitpaw_facts(None, None))), len(plans.INDUSTRY_PRICES))

    def test_ai_claim_per_industry(self):
        for ind in plans.INDUSTRY_PRICES:
            facts = ai_sales_prompts.bitpaw_facts(None, None, industry=ind)
            if ind in ('nail', 'spa'):
                self.assertIn('answers & books', facts, ind)
            else:
                self.assertNotIn('answers & books', facts, ind)
                self.assertIn('passes requests to your team', facts, ind)
        general = ai_sales_prompts.bitpaw_facts(None, None, industry='general')
        self.assertIn('Nails & Salon, Spa & Beauty: 24/7 AI assistant that answers & books', general)
        self.assertIn('Every other industry: 24/7 AI assistant that answers questions & passes requests', general)

    def test_persona_and_playbook_hold_no_hardcoded_price(self):
        # Mọi con số giá chỉ được đến từ BITPAW FACTS (plans.py) — persona, ví dụ few-shot, playbook phản đối không ghi giá.
        for ind in list(ai_sales_prompts.INDUSTRY_DELTAS) + ['unknown']:
            for objection in [None] + list(ai_sales_prompts.OBJECTION_PLAYBOOK):
                prompt = ai_sales_prompts.compose_system_prompt('', ind, objection, None, bitpaw=None)
                self.assertIsNone(re.search(r'\$\s?\d', prompt), (ind, objection))
        # /hotel/reserve/<id> có thật -> không được nói "hotel online booking NOT available"
        self.assertNotIn('online booking', ai_sales_prompts.INDUSTRY_DELTAS['hotel'].lower())
        self.assertNotIn('not available', ai_sales_prompts.INDUSTRY_DELTAS['hotel'].lower())
        self.assertIn('hotel/reserve', APP_SRC)

    def test_every_quoted_price_matches_plans(self):
        for ind in list(plans.INDUSTRY_PRICES) + ['general']:
            facts = ai_sales_prompts.bitpaw_facts(None, None, industry=ind)
            allowed = {str(v) for t in plans.INDUSTRY_PRICES.values() for m, s in t.values() for v in (m, s)}
            for amount in re.findall(r'(?<![A-Z])\$([\d,]+)', facts):
                self.assertIn(amount.replace(',', ''), allowed, (ind, amount))

    def test_secure_ai_generate_passes_page_industry(self):
        node = _fn_node('secure_ai_generate')
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'bitpaw_facts']
        self.assertEqual(len(calls), 1)
        kw = {k.arg: k.value for k in calls[0].keywords}
        self.assertIn('industry', kw)
        self.assertEqual(getattr(kw['industry'], 'id', None), 'industry')


# ================================================================ 3. /api/ai/copilot role guard
class CopilotRoleGuardTests(unittest.TestCase):
    def setUp(self):
        self.flask = Flask(__name__)
        self.flask.secret_key = 'test'
        self.copilot = types.ModuleType('ai_copilot')
        self.copilot.business_snapshot = MagicMock(return_value=('SNAPSHOT', 'Shop', 'nail'))
        self.copilot.INSIGHT_TOPICS = {}
        node = _fn_node('api_ai_copilot')
        node.decorator_list = []
        ns = {'jsonify': jsonify, 'request': request, 'session': session, 'os': os,
              '_vi_en': lambda vi, en: 'AUTO:' + en,
              'deepseek_chat_completion': MagicMock(side_effect=AssertionError('no AI call expected')),
              'db': MagicMock(side_effect=AssertionError('no DB expected'))}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'app.py::api_ai_copilot', 'exec'), ns)
        self.fn = ns['api_ai_copilot']

    def call(self, role, body):
        with patch.dict(sys.modules, {'ai_copilot': self.copilot}):
            with self.flask.test_request_context('/api/ai/copilot', method='POST', json=body):
                session['user_id'] = 7
                session['business_id'] = 7
                if role is not None:
                    session['role'] = role
                resp = self.fn()
                return resp if isinstance(resp, tuple) else (resp, 200)

    def test_staff_gets_403_with_clear_message_and_no_data_read(self):
        resp, status = self.call('staff', {'mode': 'insight', 'topic': 'revenue', 'lang': 'en'})
        self.assertEqual(status, 403)
        body = resp.get_json()
        self.assertFalse(body['success'])
        self.assertEqual(body['code'], 'owner_only')
        self.assertIn('owner / admin account only', body['message'])
        self.copilot.business_snapshot.assert_not_called()

    def test_staff_message_vietnamese_and_fallback(self):
        resp, status = self.call('staff', {'mode': 'reply', 'lang': 'vi'})
        self.assertEqual(status, 403)
        self.assertIn('chỉ dành cho tài khoản chủ tiệm', resp.get_json()['message'])
        resp, status = self.call('staff', {'mode': 'reply'})
        self.assertEqual(status, 403)
        self.assertTrue(resp.get_json()['message'].startswith('AUTO:'))

    def test_missing_or_unknown_role_is_denied(self):
        for role in (None, 'cashier', 'manager-ish'):
            _resp, status = self.call(role, {'mode': 'insight', 'lang': 'en'})
            self.assertEqual(status, 403, role)
        self.copilot.business_snapshot.assert_not_called()

    def test_admin_and_super_admin_pass_the_guard(self):
        for role in ('admin', 'super_admin'):
            self.copilot.business_snapshot.reset_mock()
            resp, status = self.call(role, {'mode': 'nope', 'lang': 'en'})
            self.assertEqual(status, 400, role)                       # đi qua guard, tới bước kiểm tra mode
            self.assertEqual(resp.get_json()['message'], 'Invalid mode.')
            self.copilot.business_snapshot.assert_called_once()

    def test_route_still_requires_login(self):
        names = [getattr(d, 'id', None) for d in _fn_node('api_ai_copilot', ast.parse(APP_SRC)).decorator_list]
        self.assertIn('login_required', names)


# ================================================================ 4. no hardcoded super-admin credentials
_CRED_PY = {
    'auto_screenshot_marketing.py': ('EMAIL', 'PASSWORD'),
    'e2e_bot.py': ('ADMIN_EMAIL', 'ADMIN_PASSWORD'),
    'test_login_e2e.py': ('ADMIN_EMAIL', 'ADMIN_PASSWORD'),
    'test_pos_fnb_e2e.py': ('ADMIN_EMAIL', 'ADMIN_PASSWORD'),
    'test_pos_nails_e2e.py': ('ADMIN_EMAIL', 'ADMIN_PASSWORD'),
    'test_saas_signup_e2e.py': ('ADMIN_EMAIL', 'ADMIN_PASSWORD'),
    'testtay.py': ('ADMIN_EMAIL', 'ADMIN_PASSWORD'),
    'setup_demo_nails.py': ('ADMIN_EMAIL', 'ADMIN_PASSWORD'),
    'setup_demo_other_industries.py': ('ADMIN_EMAIL', 'ADMIN_PASSWORD'),
}
_CRED_MJS = 'scripts/exhaustive_common_audit.mjs'
_ROOT_EMAIL = re.search(r"^SUPERADMIN_ROOT_EMAIL = '([^']+)'", APP_SRC, re.M).group(1)
# env SUPERADMIN_*/BITPAW_QA_SUPERADMIN_* kèm giá trị mặc định KHÁC rỗng = mật khẩu/email ghi cứng quay lại
_PY_DEFAULT_RE = re.compile(r'''(?:SUPERADMIN|BITPAW_QA_SUPERADMIN)_(?:EMAIL|PASSWORD)["']\s*,\s*["'][^"']+["']''')
_JS_DEFAULT_RE = re.compile(r'''(?:SUPERADMIN|BITPAW_QA_SUPERADMIN)_(?:EMAIL|PASSWORD)\s*\|\|\s*['"`][^'"`]+['"`]''')


def _read(rel, errors='strict'):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8', errors=errors) as fh:
        return fh.read()


class NoHardcodedSuperadminCredsTests(unittest.TestCase):
    def test_files_read_env_and_hold_no_literals(self):
        for rel, (e, p) in _CRED_PY.items():
            src = _read(rel)
            self.assertNotIn(_ROOT_EMAIL, src, rel)
            self.assertIn('BITPAW_QA_SUPERADMIN_PASSWORD', src, rel)
            self.assertIsNone(_PY_DEFAULT_RE.search(src), rel)
            tree = ast.parse(src)
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) in (e, p) for t in node.targets):
                    self.assertNotIsInstance(node.value, ast.Constant, f'{rel}: {e}/{p} is a literal again')
        js = _read(_CRED_MJS)
        self.assertNotIn(_ROOT_EMAIL, js)
        self.assertIn('BITPAW_QA_SUPERADMIN_PASSWORD', js)
        self.assertIsNone(_JS_DEFAULT_RE.search(js))
        self.assertIn('process.exit(1)', js)

    def _cred_snippet(self, rel, e, p):
        """Chỉ lấy 2 dòng gán email/mật khẩu + câu kiểm tra đầu khối __main__ (không import playwright/app/Mongo)."""
        tree = ast.parse(_read(rel))
        body = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in (e, p) for t in n.targets)]
        main = next(n for n in tree.body if isinstance(n, ast.If) and 'name' in ast.dump(n.test) and '__main__' in ast.dump(n.test))
        guard = main.body[0]
        self.assertIsInstance(guard, ast.If, f'{rel}: credential check must be the first statement of __main__')
        return compile(ast.fix_missing_locations(ast.Module(body=body + [guard], type_ignores=[])), rel, 'exec')

    def test_scripts_stop_with_clear_message_when_env_missing(self):
        for rel, (e, p) in _CRED_PY.items():
            code = self._cred_snippet(rel, e, p)
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit) as cm:
                    exec(code, {'os': os, '__name__': '__main__'})
            self.assertIn('BITPAW_QA_SUPERADMIN_EMAIL', str(cm.exception.code), rel)
            self.assertIn('BITPAW_QA_SUPERADMIN_PASSWORD', str(cm.exception.code), rel)

    def test_scripts_use_env_values_when_set(self):
        env = {'BITPAW_QA_SUPERADMIN_EMAIL': 'qa@example.test', 'BITPAW_QA_SUPERADMIN_PASSWORD': 'from-env'}
        legacy = {'SUPERADMIN_EMAIL': 'old@example.test', 'SUPERADMIN_PASSWORD': 'old-env'}
        for rel, (e, p) in _CRED_PY.items():
            code = self._cred_snippet(rel, e, p)
            for values, want in ((env, ('qa@example.test', 'from-env')), (legacy, ('old@example.test', 'old-env'))):
                ns = {'os': os, '__name__': '__main__'}
                with patch.dict(os.environ, values, clear=True):
                    exec(code, ns)
                self.assertEqual((ns[e], ns[p]), want, rel)

    def test_mjs_syntax_and_env_check(self):
        try:
            out = subprocess.run(['node', '--check', os.path.join(ROOT, _CRED_MJS)], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            self.skipTest('node not available')
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_no_tracked_script_reintroduces_superadmin_defaults(self):
        try:
            files = subprocess.run(['git', 'ls-files', '*.py', '*.mjs', '*.js'], cwd=ROOT, capture_output=True,
                                   text=True, timeout=60).stdout.split()
        except (OSError, subprocess.SubprocessError):
            self.skipTest('git not available')
        offenders = []
        for rel in files:
            if rel.startswith(('static/js/vendor', 'node_modules/')) or rel.endswith('.min.js'):
                continue
            try:
                src = _read(rel, errors='ignore')
            except OSError:
                continue
            if _PY_DEFAULT_RE.search(src) or _JS_DEFAULT_RE.search(src):
                offenders.append(rel)
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
