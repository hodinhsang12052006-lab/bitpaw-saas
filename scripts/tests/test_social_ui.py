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
                     '/chunk?index=', '/finish', '/api/social/tiktok/creator_info'):
            self.assertIn(path, MAIN_JS, path)

    def test_error_dict_paired(self):
        block = re.search(r'const E = \{(.*?)\n        \};', MAIN_JS, re.S).group(1)
        en = re.search(r'en: \{(.*?)\n            \},\n            vi:', block, re.S).group(1)
        vi = block.split('\n            vi: {', 1)[1]
        key = re.compile(r"(?:^|[\s,{])([A-Za-z_][A-Za-z0-9_]*):\s*['`\"]")
        en_keys, vi_keys = set(key.findall(en)), set(key.findall(vi))
        self.assertEqual(sorted(en_keys ^ vi_keys), [])
        for code in ('oauth_denied', 'scope_missing', 'youtube_no_channel', 'gbp_no_location', 'app_misconfigured',
                     'server_error', 'media_too_large', 'needs_location'):
            self.assertIn(code, en_keys)

    def test_is_admin_flag_rendered(self):
        self.assertIn('const IS_ADMIN = false;', render())                 # thiếu biến -> ít quyền nhất
        self.assertIn('const IS_ADMIN = true;', render(is_admin=True))
        self.assertIn('const USER_ID = "42";', render(session={'user_id': 42}))
        self.assertIn('const USER_ID = "";', render())

    def test_no_hardcoded_upload_chunk(self):
        # F2: cỡ lát lấy từ /upload/init — không còn tự chia 3 MB
        self.assertIsNone(re.search(r'(?<!\d)3000000(?!\d)', MAIN_JS))
        self.assertIn('chunkPlan(blob.size, init)', MAIN_JS)

    def test_no_blocking_dialogs(self):
        code = re.sub(r'//[^\n]*', '', MAIN_JS)   # bỏ chú thích ("thay cho confirm()")
        m = re.search(r'(?<![\w.])(alert|confirm|prompt)\(', code)
        self.assertIsNone(m, m and code[max(0, m.start() - 60):m.end() + 20])


# ---------------------------------------------------------------------------------------------------------------
# Chạy THẬT script của trang trong node (vm + DOM/fetch giả) để kiểm tra hành vi từng lỗi đã sửa. Không mạng, không Mongo.
HARNESS = r"""
const vm = require('vm'); const fs = require('fs');
const [mainPath, scenPath] = process.argv.slice(2);
const els = {};
function mkEl(id) {
  return { id, innerHTML: '', textContent: '', value: '', hidden: false, disabled: false, dataset: {}, style: {}, options: [], selectedIndex: 0, attrs: {},
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {}, setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; },
    removeAttribute(k) { delete this.attrs[k]; }, hasAttribute() { return false; }, focus() {}, load() {},
    querySelector(sel) { return sel === 'span' ? mkEl('_span') : null; }, querySelectorAll() { return []; }, closest() { return null; } };
}
const listeners = {};
let ctx = null;
const document = {
  getElementById: (id) => els[id] || (els[id] = mkEl(id)),
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
  createElement: (tag) => {
    const el = mkEl(tag);
    if (tag === 'video') {   // <video> giả: báo độ dài = globalThis.__videoDuration (không có -> lỗi đọc)
      Object.defineProperty(el, 'src', { get() { return el._src; }, set(v) { el._src = v; setTimeout(() => {
        const d = ctx.__videoDuration; if (d === undefined) { if (el.onerror) el.onerror(); } else { el.duration = d; if (el.onloadedmetadata) el.onloadedmetadata(); } }, 0); } });
    }
    return el;
  },
  documentElement: { lang: 'en' }, title: '', visibilityState: 'visible', activeElement: null,
};
const store = {};
const storage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } };
const calls = [], routes = {};
async function fetch(path, init) {
  path = String(path); init = init || {};
  const b = init.body;
  calls.push({ path, method: init.method || 'GET', body: (b && typeof b === 'object' && b.size !== undefined) ? { size: b.size } : b });
  const key = Object.keys(routes).filter((k) => path.startsWith(k)).sort((x, y) => y.length - x.length)[0];
  let res = key ? routes[key] : { success: true };
  if (typeof res === 'function') res = res(path, init);
  const status = (res && res.__status) || 200;
  return { ok: status < 400, status, redirected: false, url: path, json: async () => res };
}
const tick = (ms) => new Promise((r) => setTimeout(r, ms || 0));
const H = { els, calls, routes, store, tick,
  click(dataset) { const el = Object.assign(mkEl('btn'), { dataset }); el.closest = () => el; (listeners.click || []).forEach((fn) => fn({ target: el })); return el; } };
ctx = { document, localStorage: storage, sessionStorage: storage, location: { search: '', hash: '', pathname: '/social' },
  history: { replaceState() {} }, fetch, console, setTimeout, clearTimeout, Intl, URLSearchParams, H,
  URL: { createObjectURL: () => 'blob:local', revokeObjectURL() {} }, CSS: { escape: (s) => String(s) }, Image: function () {} };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(mainPath, 'utf8'), ctx, { filename: 'social_main.js' });
(async () => {
  await tick(30);      // init() của trang chạy xong
  calls.length = 0;
  let out;
  try { out = await vm.runInContext('(async () => {\n' + fs.readFileSync(scenPath, 'utf8') + '\n})()', ctx, { filename: 'scenario.js' }); }
  catch (e) { out = { __error: String((e && e.stack) || e) }; }
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})();
"""


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class SocialBehaviourTests(unittest.TestCase):
    """Hồi quy cho các lỗi review đã xác minh (F2, F4, F5, F6, F7, F8, F10, F11, F12)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='social_ui_')
        cls.harness = os.path.join(cls.tmp, 'harness.js')
        with open(cls.harness, 'w', encoding='utf-8') as f:
            f.write(HARNESS)
        cls.main = {}
        for who, ctx in (('admin', dict(is_admin=True, session={'user_id': 'u-owner'})),
                         ('staff', dict(is_admin=False, session={'user_id': 'u-me'}))):
            js = max(re.findall(r'<script>(.*?)</script>', render(tenant_currency='AUD', **ctx), re.S), key=len)
            path = os.path.join(cls.tmp, f'main_{who}.js')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(js)
            cls.main[who] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_js(self, scenario, who='admin'):
        path = os.path.join(self.tmp, 'scenario.js')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(scenario)
        r = subprocess.run(['node', self.harness, self.main[who], path], capture_output=True, text=True, timeout=60, encoding='utf-8')
        self.assertEqual(r.returncode, 0, r.stderr)
        import json
        out = json.loads(r.stdout)
        self.assertNotIn('__error', out if isinstance(out, dict) else {}, out)
        return out

    def test_f2_upload_uses_server_chunk_plan(self):
        out = self.run_js(r"""
            const res = [];
            for (const size of [3200000, 7000000, 18500000]) {
              const chunks = Math.ceil(size / 3500000), uid = 'u' + size;
              H.routes['/api/media/upload/init'] = { success: true, upload_id: uid, chunk_size: 3500000, chunks };
              // giống media_store.upload_chunk: index ngoài [0, chunks) -> 400 bad_index
              H.routes['/api/media/upload/' + uid + '/chunk'] = (path) => { const i = +/index=(\d+)/.exec(path)[1];
                return i < chunks ? { success: true, received: i } : { __status: 400, success: false, code: 'bad_index', message: 'Chunk index out of range.' }; };
              H.routes['/api/media/upload/' + uid + '/finish'] = { success: true, file_id: 'abcdefabcdefabcdefabcdef', url: '/m/x.mp4', content_type: 'video/mp4' };
              globalThis.__videoDuration = 42;
              C.media = []; H.calls.length = 0;
              await handleFile({ type: 'video/mp4', size, slice(a, b) { return { size: b - a }; } });
              const ch = H.calls.filter((c) => c.path.includes('/chunk?index='));
              res.push({ size, n: ch.length, sizes: ch.map((c) => c.body.size), media: C.media.length, duration: C.media[0] ? C.media[0].duration : null });
            }
            return res;
        """)
        self.assertEqual([r['n'] for r in out], [1, 2, 6])
        self.assertEqual(out[0]['sizes'], [3200000])
        self.assertEqual(out[1]['sizes'], [3500000, 3500000])
        self.assertEqual(sum(out[2]['sizes']), 18500000)
        self.assertTrue(all(r['media'] == 1 and r['duration'] == 42 for r in out), out)

    def test_f4_tiktok_creator_info(self):
        out = self.run_js(r"""
            S.accLoaded = true;
            S.accounts = { tiktok: { connected: true, status: 'connected', account_name: 'shop', requirement_codes: ['tiktok_audit', 'tiktok_manual'], requirements: [] } };
            H.routes['/api/social/tiktok/creator_info'] = { success: true, data: { creator_nickname: 'Nail Spa Sydney', creator_username: 'nailspa',
              privacy_level_options: ['PUBLIC_TO_EVERYONE', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY'], comment_disabled: true, duet_disabled: false,
              stitch_disabled: false, max_video_post_duration_sec: 60 } };
            Object.assign(C, newCompose());
            C.tt.privacy = 'PUBLIC_TO_EVERYONE'; C.tt.comment = true;      // lựa chọn cũ không còn hợp lệ
            H.calls.length = 0;
            H.click({ act: 'toggle-plat', p: 'tiktok' });
            await H.tick(10);
            const h1 = H.els.cmpTiktok.innerHTML;
            const audit = { called: H.calls.some((c) => c.path === '/api/social/tiktok/creator_info'), opts: ttInfo().opts, privacy: C.tt.privacy,
              comment: C.tt.comment, name: h1.includes('Nail Spa Sydney'), pub: h1.includes('value="PUBLIC_TO_EVERYONE"'),
              self: h1.includes('value="SELF_ONLY"'), commentOff: /data-tt="comment"[^>]*disabled/.test(h1), auditNote: h1.includes(t('ttAuditOnly')) };
            S.accounts.tiktok.requirement_codes = ['tiktok_manual'];
            renderTiktok();
            const h2 = H.els.cmpTiktok.innerHTML;
            const after = { opts: ttInfo().opts, privacy: C.tt.privacy, pub: h2.includes('value="PUBLIC_TO_EVERYONE"'), mutual: h2.includes('value="MUTUAL_FOLLOW_FRIENDS"') };
            C.media = [{ file_id: 'f'.repeat(24), content_type: 'video/mp4', url: '/m/v.mp4', duration: 95 }];
            C.tt.privacy = 'SELF_ONLY';
            const blocks = () => problems(false).filter((w) => w.block).map((w) => w.msg);
            const tooLong = blocks();
            C.media[0].duration = 30;
            const okLen = blocks();
            H.routes['/api/social/tiktok/creator_info'] = { __status: 502, success: false, code: 'provider_busy', message: 'TikTok is busy', platform: 'tiktok' };
            await loadTtInfo(true);
            const err = { state: S.tti.state, retry: H.els.cmpTiktok.innerHTML.includes('data-act="tt-retry"'), blocked: blocks().includes(t('w_ttInfo')) };
            return { audit, after, tooLong, okLen, err, msg: t('w_ttTooLong', { s: 95, max: 60 }) };
        """)
        a = out['audit']
        self.assertTrue(a['called'])
        self.assertEqual(a['opts'], ['SELF_ONLY'])                  # chưa audit: chỉ "Chỉ mình tôi"
        self.assertEqual(a['privacy'], '')                          # không giữ / không chọn sẵn mức không hợp lệ
        self.assertFalse(a['comment'])
        self.assertTrue(a['name'] and a['self'] and a['commentOff'] and a['auditNote'])
        self.assertFalse(a['pub'])
        self.assertEqual(out['after']['opts'], ['PUBLIC_TO_EVERYONE', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY'])
        self.assertTrue(out['after']['pub'])
        self.assertFalse(out['after']['mutual'])                    # chỉ các mức TikTok trả về, không danh sách cứng
        self.assertEqual(out['after']['privacy'], '')
        self.assertIn(out['msg'], out['tooLong'])
        self.assertEqual(out['okLen'], [])
        self.assertEqual(out['err'], {'state': 'error', 'retry': True, 'blocked': True})

    def test_f5_gbp_location_picker(self):
        out = self.run_js(r"""
            const accs = () => ({ google_business: { connected: true, status: 'connected', account_name: 'Salon One', external_id: 'accounts/1/locations/11',
              connected_via: 'oauth', can_oauth: true, requirements: [], requirement_codes: [],
              location_choices: [{ id: 'accounts/1/locations/11', name: 'Salon One' }, { id: 'accounts/1/locations/22', name: 'Salon Two' }] } });
            S.accLoaded = true; S.accounts = accs();
            renderAccounts();
            const html = H.els.accCards.innerHTML;
            H.els.gbpLoc = Object.assign(H.els.gbpLoc || {}, { value: 'accounts/1/locations/22', selectedIndex: 1, options: [{ textContent: 'Salon One' }, { textContent: 'Salon Two' }] });
            H.routes['/api/social/accounts/google_business'] = { success: true, data: {} };
            H.calls.length = 0;
            H.click({ act: 'gbp-loc-save', p: 'google_business' });
            await H.tick(10);
            const post = H.calls.find((c) => c.path === '/api/social/accounts/google_business');
            S.accounts = accs(); S.accounts.google_business.needs_location = true;
            renderAccounts();
            const html2 = H.els.accCards.innerHTML;
            Object.assign(C, newCompose()); C.caption = 'Hi'; C.targets = ['google_business'];
            return { select: html.includes('id="gbpLoc"'), two: html.includes('Salon Two'), cur: /value="accounts\/1\/locations\/11" selected/.test(html),
              body: post ? JSON.parse(post.body) : null, method: post && post.method, note: html2.includes(t('gbpPickNeeded')), ph: html2.includes(t('gbpChoose')),
              warn: problems(false).filter((w) => w.block).map((w) => w.msg), expect: t('w_gbpLocation') };
        """)
        self.assertTrue(out['select'] and out['two'] and out['cur'])
        self.assertEqual(out['method'], 'POST')
        self.assertEqual(out['body'], {'action': 'connect_token', 'fields': {'location': 'accounts/1/locations/22'}})
        self.assertTrue(out['note'] and out['ph'])
        self.assertIn(out['expect'], out['warn'])

    def test_f6_insights_nested_totals(self):
        out = self.run_js(r"""
            S.insights = { totals: { facebook: { posts: 3, posts_with_metrics: 2, metrics: { views: 1500, likes: 42 }, metric_posts: { views: 2, likes: 2 } } },
              posts: [{ post: { id: 7, caption: 'Autumn nails', media_type: 'image', scheduled_at: '2026-10-01T10:00:00Z', permalink: 'https://www.facebook.com/123_456' },
                        platform: 'facebook', metrics: { views: 1000, likes: 30 }, fetched_at: '2026-10-02T10:00:00Z' }] };
            S.perfErr = '';
            renderInsights();
            const h = H.els.perfBody.innerHTML;
            return { views: h.includes('<b>1,500</b>'), likes: h.includes('<b>42</b>'), link: h.includes('href="https://www.facebook.com/123_456"'),
                     withStats: h.includes(t('withStats', { n: '2' })) };
        """)
        self.assertEqual(out, {'views': True, 'likes': True, 'link': True, 'withStats': True})

    def test_f7_oauth_error_codes_translated(self):
        out = self.run_js(r"""
            const codes = ['oauth_denied', 'oauth_expired', 'oauth_state', 'scope_missing', 'youtube_no_channel', 'gbp_no_location', 'app_misconfigured',
              'server_error', 'app_not_configured', 'forbidden', 'token_invalid', 'provider_busy', 'google_quota', 'google_permission', 'oauth_failed',
              'media_too_large', 'needs_location'];
            const en = codes.map((c) => [c, errText({ code: c, platform: 'youtube', detail: '' })]);
            H.store.bitpaw_lang = 'vi';
            const vi = codes.map((c) => [c, errText({ code: c, platform: 'youtube', detail: '' })]);
            delete H.store.bitpaw_lang;
            return { en, vi };
        """)
        for (code, en), (_, vi) in zip(out['en'], out['vi']):
            for s in (en, vi):
                self.assertNotRegex(s, r'Something went wrong \(HTTP|Có lỗi xảy ra \(HTTP', code)
                self.assertNotIn('{', s, code)
                self.assertNotEqual(s, code)
            self.assertNotEqual(en, vi, code)

    def test_f8_retry_failed_targets(self):
        out = self.run_js(r"""
            S.posts = [{ id: 5, status: 'partial', caption: 'x', targets: [{ platform: 'facebook', status: 'published', permalink: 'https://facebook.com/1' },
                                                                         { platform: 'instagram', status: 'failed', error: { code: 'token_invalid', message: 'expired' } }] },
                       { id: 6, status: 'published', caption: 'y', targets: [{ platform: 'facebook', status: 'published' }] }];
            S.sheetId = 5; renderSheet(); const h5 = H.els.sheetBody.innerHTML;
            S.sheetId = 6; renderSheet(); const h6 = H.els.sheetBody.innerHTML;
            H.routes['/api/social/posts/5/publish_now'] = { success: true, run: {}, post: { id: 5, status: 'published',
              targets: [{ platform: 'facebook', status: 'published' }, { platform: 'instagram', status: 'published' }] } };
            H.calls.length = 0;
            H.click({ act: 'retry-post', id: '5' });
            await H.tick(10);
            return { shown: h5.includes('data-act="retry-post"'), hint: h5.includes(t('retryHint')), onPublished: h6.includes('data-act="retry-post"'),
                     called: H.calls.some((c) => c.path === '/api/social/posts/5/publish_now' && c.method === 'POST') };
        """)
        self.assertEqual(out, {'shown': True, 'hint': True, 'onPublished': False, 'called': True})

    def test_f10_limits_match_backend(self):
        out = self.run_js(r"""
            S.accLoaded = true;
            S.accounts = { facebook: { connected: true, status: 'connected' }, youtube: { connected: true, status: 'connected' } };
            const blocks = (d) => problems(!!d).filter((w) => w.block).map((w) => w.msg);
            Object.assign(C, newCompose());
            C.targets = ['facebook']; C.caption = 'a'.repeat(5001); const fb = blocks();
            C.caption = 'a'.repeat(5000); const fbOk = blocks();
            C.targets = ['youtube']; C.caption = 'desc'; C.media = [{ file_id: 'f'.repeat(24), content_type: 'video/mp4', url: '/m/v.mp4' }];
            C.title = 't'.repeat(95); const yt = blocks();
            C.title = 't'.repeat(90); const ytOk = blocks();
            C.targets = []; C.media = []; C.caption = 'b'.repeat(5001); const draft = blocks(true);
            return { fbLimit: PLAT.facebook.limit, ytTitle: PLAT.youtube.titleLimit, fb, fbOk, yt, ytOk, draft,
                     ytMsg: t('w_ytTitleLong', { max: 90 }), mainMsg: t('w_mainTooLong', { n: fmtNum(5001), max: fmtNum(5000) }) };
        """)
        self.assertEqual((out['fbLimit'], out['ytTitle']), (5000, 90))
        self.assertTrue(any('Facebook' in m for m in out['fb']), out['fb'])
        self.assertEqual(out['fbOk'], [])
        self.assertIn(out['ytMsg'], out['yt'])
        self.assertEqual(out['ytOk'], [])
        self.assertIn(out['mainMsg'], out['draft'])

    def test_f11_staff_sees_no_admin_actions(self):
        out = self.run_js(r"""
            S.accLoaded = true;
            S.accounts = { facebook: { connected: true, status: 'connected', account_name: 'Page', inbox_available: true, requirements: [] },
              youtube: { connected: true, status: 'connected', can_oauth: true, requirements: [] },
              google_business: { connected: true, status: 'connected', can_oauth: true, account_name: 'Salon One', external_id: 'accounts/1/locations/11', requirements: [],
                location_choices: [{ id: 'accounts/1/locations/11', name: 'Salon One' }, { id: 'accounts/1/locations/22', name: 'Salon Two' }] } };
            renderAccounts();
            const acc = H.els.accCards.innerHTML;
            S.posts = [{ id: 8, status: 'scheduled', author_id: 'u-other', scheduled_at: '2030-01-01T10:00:00Z', targets: [{ platform: 'facebook', status: 'pending' }] },
                       { id: 9, status: 'failed', author_id: 'u-other', targets: [{ platform: 'facebook', status: 'failed', error: { code: 'token_invalid' } }] }];
            S.sheetId = 8; renderSheet(); const sh8 = H.els.sheetBody.innerHTML;
            S.sheetId = 9; renderSheet(); const sh9 = H.els.sheetBody.innerHTML;
            S.pending = [{ id: 10, status: 'pending_approval', created_by: 'ai', author_id: 'u-other', caption: 'AI', targets: [{ platform: 'facebook' }] },
                         { id: 12, status: 'pending_approval', created_by: 'owner', author_id: 'u-me', caption: 'Mine', targets: [{ platform: 'facebook' }] }];
            renderPending(); const pend = H.els.pendList.innerHTML;
            Object.assign(C, newCompose()); C.caption = 'New nails'; C.targets = ['facebook']; C.when = 'now';
            H.routes['/api/social/posts'] = (path, init) => (init.method === 'POST'
              ? { success: true, post: Object.assign({ id: 11 }, JSON.parse(init.body), { status: 'pending_approval' }) } : { success: true, data: [] });
            renderWarn();
            const label = H.els.btnSubmit.innerHTML;
            H.calls.length = 0;
            await submitCompose(false, H.els.btnSubmit);
            const created = H.calls.find((c) => c.path === '/api/social/posts' && c.method === 'POST');
            return { accOff: acc.includes('acc-off'), oauth: acc.includes('oauth-start'), token: acc.includes('acc-token-open'), inbox: acc.includes('acc-inbox'),
              gbpSelect: acc.includes('id="gbpLoc"'), publishNow: sh8.includes('publish-now'), cancel: sh8.includes('cancel-post'), retry: sh9.includes('retry-post'),
              retryStaff: sh9.includes(t('retryStaff')), approve: pend.includes('data-act="approve"'), rejectOther: pend.includes('data-act="reject" data-id="10"'),
              rejectMine: pend.includes('data-act="reject" data-id="12"'), approveAllHidden: H.els.btnApproveAll.hidden, accNote: H.els.accStaffNote.hidden === false,
              label: label.includes(t('btnSendApproval')), status: created ? JSON.parse(created.body).status : null,
              publishNowCalled: H.calls.some((c) => c.path.includes('/publish_now')), tab: S.tab };
        """, who='staff')
        for k in ('accOff', 'oauth', 'token', 'inbox', 'gbpSelect', 'publishNow', 'cancel', 'retry', 'approve', 'rejectOther', 'publishNowCalled'):
            self.assertFalse(out[k], k)
        for k in ('retryStaff', 'rejectMine', 'approveAllHidden', 'accNote', 'label'):
            self.assertTrue(out[k], k)
        self.assertEqual(out['status'], 'pending_approval')
        self.assertEqual(out['tab'], 'approvals')

    def test_f11_admin_still_publishes_now(self):
        out = self.run_js(r"""
            S.accLoaded = true; S.accounts = { facebook: { connected: true, status: 'connected', requirements: [] } };
            Object.assign(C, newCompose()); C.caption = 'New nails'; C.targets = ['facebook']; C.when = 'now';
            H.routes['/api/social/posts'] = (path, init) => (init.method === 'POST'
              ? { success: true, post: Object.assign({ id: 11 }, JSON.parse(init.body)) } : { success: true, data: [] });
            H.routes['/api/social/posts/11/publish_now'] = { success: true, post: { id: 11, status: 'published', targets: [{ platform: 'facebook', status: 'published' }] } };
            H.calls.length = 0;
            await submitCompose(false, H.els.btnSubmit);
            const created = H.calls.find((c) => c.path === '/api/social/posts' && c.method === 'POST');
            return { status: created ? JSON.parse(created.body).status : null, publishNow: H.calls.some((c) => c.path === '/api/social/posts/11/publish_now') };
        """)
        self.assertEqual(out, {'status': 'scheduled', 'publishNow': True})

    def test_f12_best_time_note_in_ui_language(self):
        out = self.run_js(r"""
            S.bt = { facebook: { source: 'default', slots: [{ weekday: 1, hour: 10 }], sample_size: 3,
                                 note: 'Industry default (published research) — switches to your own results after 10 posts', note_vi: 'x' },
                     instagram: { source: 'learned', slots: [{ weekday: 2, hour: 18 }], sample_size: 14, note: 'Learned from 14 of your Instagram posts' } };
            S.btPlats = ['facebook', 'instagram'];
            H.store.bitpaw_lang = 'vi';
            renderBestTable(); const vi = H.els.btTable.innerHTML;
            delete H.store.bitpaw_lang;
            renderBestTable(); const en = H.els.btTable.innerHTML;
            return { viDefault: vi.includes('Mặc định theo ngành (từ các báo cáo công khai)'), viLearned: vi.includes('Học từ 14 bài Instagram'),
                     viNoEn: !vi.includes('Industry default (published research)') && !vi.includes('Learned from 14'),
                     enDefault: en.includes('once Facebook has 10 posts with real stats (you have 3)'), enLearned: en.includes('Learned from 14 of your Instagram posts') };
        """)
        self.assertEqual(out, {'viDefault': True, 'viLearned': True, 'viNoEn': True, 'enDefault': True, 'enLearned': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
