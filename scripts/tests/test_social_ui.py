"""Kiểm tra offline cho templates/social.html (slice social-ui) — KHÔNG import app.py, không Mongo, không mạng.

Chạy: python scripts/tests/test_social_ui.py
- Jinja parse + render với sidebar giả (biến shop_timezone có thể thiếu)
- node --check script chính (bỏ qua nếu máy không có node)
- mọi $('id') / getElementById('id') trong JS đều có trong HTML
- từ điển T: en và vi đủ cặp khoá
- các câu chữ bắt buộc của TikTok / trạng thái trung thực có mặt, quyền riêng tư TikTok không chọn sẵn
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import jinja2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SRC = open(os.path.join(ROOT, 'templates', 'social.html'), encoding='utf-8').read()
SIDEBAR_STUB = '<aside id="app-sidebar"></aside>'


def render(**ctx):
    env = jinja2.Environment(loader=jinja2.DictLoader({'social.html': SRC, 'components/app_sidebar.html': SIDEBAR_STUB}),
                             autoescape=True)
    base = dict(url_for=lambda ep, **kw: '/static/' + kw.get('filename', ''), default_lang='en')
    base.update(ctx)
    return env.get_template('social.html').render(**base)


HTML = render(tenant_currency='AUD')
MAIN_JS = max(re.findall(r'<script>(.*?)</script>', HTML, re.S), key=len)


class SocialTemplateTests(unittest.TestCase):
    def test_render_without_optional_vars(self):
        html = render()   # thiếu tenant_currency + shop_timezone vẫn render
        self.assertIn('const CURRENCY = "USD";', html)
        self.assertIn('const SERVER_TZ = "";', html)
        html = render(tenant_currency='USD', shop_timezone='America/New_York')
        self.assertIn('const SERVER_TZ = "America/New_York";', html)

    def test_sidebar_included(self):
        self.assertIn('id="app-sidebar"', HTML)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_main_script_syntax(self):
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(MAIN_JS)
            path = f.name
        try:
            r = subprocess.run(['node', '--check', path], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.unlink(path)

    def test_static_ids_exist(self):
        ids_html = set(re.findall(r'\bid="([^"$]+)"', HTML))
        used = set(re.findall(r"\$\('([^']+)'\)", MAIN_JS)) | set(re.findall(r"getElementById\('([^']+)'\)", MAIN_JS))
        missing = sorted(i for i in used if i not in ids_html)
        self.assertEqual(missing, [])
        for n in ('calendar', 'compose', 'approvals', 'accounts', 'performance'):
            self.assertIn('tab-' + n, ids_html)
            self.assertIn('pane-' + n, ids_html)

    def test_translation_keys_paired(self):
        block = re.search(r'const T = \{(.*?)\n        \};', MAIN_JS, re.S).group(1)
        en = re.search(r'en: \{(.*?)\n            \},\n            vi:', block, re.S).group(1)
        vi = block.split('\n            vi: {', 1)[1]
        key = re.compile(r"(?:^|[\s,{])([A-Za-z_][A-Za-z0-9_]*):\s*['`\"]")
        en_keys, vi_keys = set(key.findall(en)), set(key.findall(vi))
        self.assertEqual(sorted(en_keys - vi_keys), [])
        self.assertEqual(sorted(vi_keys - en_keys), [])
        static = set(re.findall(r'data-t[pa]?="([^"]+)"', HTML)) | set(re.findall(r"\bt\('([A-Za-z_][A-Za-z0-9_]*)'", MAIN_JS))
        self.assertEqual(sorted(k for k in static if k not in en_keys and not k.endswith('_')), [])

    def test_tiktok_compliance_texts(self):
        self.assertIn("By posting, you agree to TikTok's ", MAIN_JS)
        self.assertIn("ttMusic: 'Music Usage Confirmation'", MAIN_JS)
        self.assertIn('https://www.tiktok.com/legal/page/global/music-usage-confirmation/en', MAIN_JS)
        for lvl in ('PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY'):
            self.assertIn(lvl, MAIN_JS)
        # quyền riêng tư: chỉ có option rỗng được chọn sẵn; công tắc comment/duet/stitch mặc định tắt
        self.assertIn("privacy: '', comment: false, duet: false, stitch: false, disclose: false", MAIN_JS)
        self.assertIn("<option value=\"\" ${C.tt.privacy ? '' : 'selected'} disabled>", MAIN_JS)
        self.assertIn("if (!C.tt.privacy) add(t('w_ttPrivacy'), true);", MAIN_JS)

    def test_honest_labels(self):
        for s in ('No published posts with stats yet', 'Learned from your posts', 'Industry default', 'Scheduled on {p}'):
            self.assertIn(s, MAIN_JS)

    def test_api_contract_paths(self):
        for path in ('/api/social/accounts', '/api/social/posts', '/api/social/plan/week', '/api/social/captions',
                     '/api/social/best_times?platform=', '/api/social/insights?days=', '/api/social/review', '/api/social/pump',
                     '/publish_now', '/approve', '/cancel', '/social/oauth/', '/api/ai_studio/media', '/api/media/upload/init',
                     '/chunk?index=', '/finish'):
            self.assertIn(path, MAIN_JS, path)

    def test_no_blocking_dialogs(self):
        code = re.sub(r'//[^\n]*', '', MAIN_JS)   # bỏ chú thích ("thay cho confirm()")
        m = re.search(r'(?<![\w.])(alert|confirm|prompt)\(', code)
        self.assertIsNone(m, m and code[max(0, m.start() - 60):m.end() + 20])


if __name__ == '__main__':
    unittest.main(verbosity=2)
