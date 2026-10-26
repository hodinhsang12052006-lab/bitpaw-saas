"""Kiểm thử OFFLINE: ước tính click của templates/ad_assistant.html (review F14).

Trước đây trang vẽ biểu đồ 7 ngày nhân với 1 "đường học" tự bịa [0.8 … 1.1] (tăng dần không dựa trên dữ liệu nào) và dùng
bảng giá mỗi click USD cho cả tiệm AUD. Giờ chỉ còn 1 KHOẢNG = tổng ngân sách ÷ giá mỗi click tham khảo (thấp–cao) theo
đúng tiền tệ, ghi rõ giả định; tiền tệ không có trong bảng thì không ước tính.

Không chạy Flask, không import app.py / mongo_client, không gọi mạng: render template bằng Jinja2 thuần rồi chạy đúng
các hàm JS của trang trong node với DOM giả.

    python scripts/tests/test_ad_assistant_estimate.py
"""
import json
import os
import re
import subprocess
import tempfile
import unittest

import jinja2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
TPL = 'ad_assistant.html'


def render(currency='USD', lang='en'):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(ROOT, 'templates')))
    env.globals.update(url_for=lambda *a, **k: '/static/x', shop_header_name=lambda: 'Lotus Nails')
    return env.get_template(TPL).render(tenant_currency=currency, tenant_country='AU', default_lang=lang)


def extract_js(script, name):
    """Nguyên văn `function name(...) {...}` / `const name = ...` (đếm ngoặc {})."""
    m = re.search(r'function\s+%s\s*\(' % re.escape(name), script) or re.search(r'const\s+%s\s*=' % re.escape(name), script)
    if not m:
        return None
    i, nl, br = m.start(), script.find('\n', m.end()), script.find('{', m.end())
    line = script[i:nl]
    if br == -1 or (nl != -1 and nl < br) or (line.startswith('const') and line.count('{') == line.count('}')):
        return line
    depth = 0
    for j in range(br, len(script)):
        depth += (script[j] == '{') - (script[j] == '}')
        if depth == 0:
            end = j + 1
            return script[i:end + (1 if script[end:end + 1] == ';' else 0)]
    return None


HARNESS = r'''
const els = {};
const document = { getElementById: (id) => (els[id] = els[id] || { textContent: '' }) };
const platformSelect = { value: 'facebook', selectedIndex: 0,
  options: [{ text: 'Facebook / Instagram' }, { text: 'TikTok' }, { text: 'Google Ads' }] };
const DURATION_DAYS = 7;
let currentLang = 'en', budgetCurrency = 'USD';
const cases = JSON.parse(process.env.CASES);
const out = [];
for (const c of cases) {
  currentLang = c.lang; budgetCurrency = c.cur;
  platformSelect.value = c.platform; platformSelect.selectedIndex = ['facebook', 'tiktok', 'google'].indexOf(c.platform);
  updateEstimate(c.budget);
  out.push({ estimate: els.clickEstimate.textContent, basis: els.clickEstimateBasis.textContent, range: clickRange(c.budget, c.platform, c.cur) });
}
console.log(JSON.stringify(out));
'''


class AdEstimateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = render()
        with open(os.path.join(ROOT, 'templates', TPL), encoding='utf-8') as f:
            cls.src = f.read()
        cls.script = '\n'.join(re.findall(r'<script>(.*?)</script>', cls.html, re.S))

    def run_cases(self, cases):
        parts = [extract_js(self.script, n) for n in ('translations', 't', 'tf', 'fmtMoney', 'REF_CPC', 'clickRange', 'updateEstimate')]
        self.assertTrue(all(parts), 'không cắt được hàm JS cần thử')
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write('\n'.join(parts) + '\n' + HARNESS)
            tmp = f.name
        try:
            r = subprocess.run(['node', tmp], capture_output=True, text=True, encoding='utf-8', timeout=60,
                               env=dict(os.environ, CASES=json.dumps(cases)))
        finally:
            os.unlink(tmp)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    # ---------------------------------------------------------------- không còn biểu đồ bịa
    def test_no_invented_ramp_or_chart(self):
        for bad in ('ramp', '0.8, 0.9, 1, 1.05', 'roiChart', 'new Chart(', 'cdn.jsdelivr.net/npm/chart.js', 'updateChart', 'Math.random'):
            self.assertNotIn(bad, self.src, bad)
        self.assertIn('id="clickEstimate"', self.src)
        self.assertIn('id="clickEstimateBasis"', self.src)

    def test_strings_exist_in_both_languages(self):
        for key in ('ad_assistant_forecast_title', 'ad_assistant_forecast_note', 'ad_assistant_forecast_empty',
                    'ad_assistant_forecast_range', 'ad_assistant_forecast_basis', 'ad_assistant_forecast_no_ref'):
            self.assertEqual(self.src.count(key + ':'), 2, key)

    # ---------------------------------------------------------------- khoảng ước tính, ghi rõ giả định + tiền tệ
    def test_usd_range_and_basis(self):
        r = self.run_cases([{'budget': 70, 'platform': 'facebook', 'cur': 'USD', 'lang': 'en'}])[0]
        self.assertEqual((r['range']['lo'], r['range']['hi']), (35, 140))
        self.assertEqual(r['estimate'], '≈ 35–140 clicks in 7 days')
        self.assertIn('$0.50–$2.00', r['basis'])
        self.assertIn('Facebook / Instagram', r['basis'])
        self.assertIn('(USD)', r['basis'])
        self.assertIn('not data from your ad account', r['basis'])

    def test_aud_uses_its_own_table_not_usd(self):
        r = self.run_cases([{'budget': 70, 'platform': 'facebook', 'cur': 'AUD', 'lang': 'en'}])[0]
        self.assertEqual((r['range']['lo'], r['range']['hi']), (23, 93))   # 70 ÷ A$3.00 … 70 ÷ A$0.75
        self.assertIn('(AUD)', r['basis'])
        self.assertIn('A$0.75', r['basis'])

    def test_vnd_vietnamese(self):
        r = self.run_cases([{'budget': 700000, 'platform': 'tiktok', 'cur': 'VND', 'lang': 'vi'}])[0]
        self.assertEqual((r['range']['lo'], r['range']['hi']), (140, 700))
        self.assertEqual(r['estimate'], '≈ 140–700 lượt click trong 7 ngày')
        self.assertIn('TikTok', r['basis'])
        self.assertIn('(VND)', r['basis'])

    def test_unknown_currency_shows_no_numbers(self):
        r = self.run_cases([{'budget': 500, 'platform': 'google', 'cur': 'EUR', 'lang': 'en'}])[0]
        self.assertIsNone(r['range'])
        self.assertEqual(r['estimate'], '')
        self.assertIn('No reference cost per click for EUR', r['basis'])
        self.assertFalse(re.search(r'\d', r['basis'].replace('EUR', '')), r['basis'])

    def test_empty_budget_prompts_instead_of_zero(self):
        r = self.run_cases([{'budget': 0, 'platform': 'facebook', 'cur': 'USD', 'lang': 'en'}])[0]
        self.assertEqual(r['estimate'], '')
        self.assertIn('Enter a total budget', r['basis'])

    def test_range_is_flat_total_not_a_curve(self):
        # khoảng chỉ phụ thuộc tổng ngân sách và giá mỗi click: gấp đôi ngân sách -> gấp đôi click, không có hệ số theo ngày
        a, b = self.run_cases([{'budget': 100, 'platform': 'google', 'cur': 'USD', 'lang': 'en'},
                               {'budget': 200, 'platform': 'google', 'cur': 'USD', 'lang': 'en'}])
        self.assertEqual((a['range']['lo'], a['range']['hi']), (16, 100))
        self.assertEqual((b['range']['lo'], b['range']['hi']), (33, 200))


if __name__ == '__main__':
    unittest.main(verbosity=2)
