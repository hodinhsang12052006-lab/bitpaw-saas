"""Kiểm thử OFFLINE cho lát studio-ui: templates/ai-studio.html + static/js/promo_video.js.

Không chạy Flask, không import app.py / mongo_client (mongo_client mở kết nối tới DB PRODUCTION), không gọi API thật.

    python scripts/tests/test_studio_ui.py             # tĩnh + node: cú pháp JS, id, từ điển EN/VI, promo_video.js với encoder giả
    python scripts/tests/test_studio_ui.py --browser   # thêm: Chrome thật (Playwright của repo chính), mọi /api/* là bản giả
                                                       # qua page.route — dựng MP4 thật bằng WebCodecs + mp4-muxer (jsdelivr)

Chế độ --browser render template bằng Jinja2 thuần (stub url_for/session), phục vụ trang + /static qua page.route
(không có máy chủ nào lắng nghe), rồi kiểm: không lỗi JS, 390 px không cuộn ngang, ảnh/video job + poll 3 s, mã lỗi
quota_exceeded / upgrade_required / not_configured, chọn ảnh tiệm, video quảng cáo -> tải lên theo khúc ≤ 3.4 MB có 'ftyp',
tải về theo lát Range, đổi EN/VI, không còn alert().
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
TPL = os.path.join(ROOT, 'templates', 'ai-studio.html')
JS = os.path.join(ROOT, 'static', 'js', 'promo_video.js')

FAILS = []


def check(name, ok, note=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {note}' if note else ''))
    if not ok:
        FAILS.append(name)


def node(code_or_file, *args, is_file=False, env=None, timeout=120):
    cmd = ['node', code_or_file, *args] if is_file else ['node', '-e', code_or_file, *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', env=env, timeout=timeout)


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


# ------------------------------------------------------------------------------------------------
# 1. Kiểm tra tĩnh template
# ------------------------------------------------------------------------------------------------
def static_checks(html):
    # giao diện giả mà spec §5 yêu cầu bỏ
    for bad in ('Load Algorithm', 'ANTI-BOT', 'Ecosystem Connected', 'Unique (Brand Match)', '>10K<', '>500<',
                'SEO Hacker', 'Algorithm Hacker', 'Enterprise V8', 'images.unsplash.com'):
        check(f'không còn "{bad}"', bad not in html)
    check('không còn alert(...)', not re.search(r'(?<![\w.])alert\(\s*[^)\s]', html))
    check('dùng sidebar chung components/app_sidebar.html', "{% include 'components/app_sidebar.html' %}" in html)
    check('nạp promo_video.js', "filename='js/promo_video.js'" in html)

    ids = set(re.findall(r'\bid="([A-Za-z][\w-]*)"', html))
    dup = [i for i in ids if len(re.findall(r'\bid="%s"' % re.escape(i), html)) > 1]
    check('không trùng id', not dup, ','.join(dup))
    refs = set(re.findall(r"""\$\('([\w-]+)'\)""", html)) | set(re.findall(r"""getElementById\('([\w-]+)'\)""", html))
    refs |= set(re.findall(r"""querySelector(?:All)?\('#([\w-]+)""", html))
    missing = sorted(r for r in refs if r not in ids)
    check('mọi id JS dùng đều có trong HTML', not missing, ','.join(missing))

    # các id/hàm mà scripts/ai_studio_e2e.mjs đang dùng
    for need in ('brandModal', 'brandName', 'brandUsp', 'brandAudience', 'brandBlacklist', 'brandSaveBtn', 'subtitleFile', 'userPrompt',
                 'aiScript', 'aiResultText', 'aiModal', 'aiLoading', 'aiModalActions', 'matrixGoal', 'matrixLoading', 'matrixResult',
                 'channelLink', 'channelStats', 'doctorLoading', 'doctorResult'):
        check(f'giữ id #{need}', need in ids)
    script = '\n'.join(re.findall(r'<script>(.*?)</script>', html, re.S))
    defined = set(re.findall(r'function\s+([A-Za-z_$][\w$]*)\s*\(', script)) | set(re.findall(r'window\.([A-Za-z_$][\w$]*)\s*=', script))
    handlers = set(re.findall(r'on(?:click|change|input)="([A-Za-z_$][\w$]*)\(', re.sub(r'/\*.*?\*/', '', html, flags=re.S)))
    check('mọi onclick/onchange gọi hàm có thật', handlers <= defined, ','.join(sorted(handlers - defined)))
    for sel in ('openBrandModal()', 'startDeepSeekRewrite(this)', 'buildFacelessKit(this)', 'speakScript(this)', 'generateMatrix(this)',
                'diagnoseChannel(this)', 'exportMobilePackage(this)', 'copyAndCloseAiModal(this)'):
        check(f'giữ nút onclick="{sel}"', f'onclick="{sel}"' in html)
    for fn in ('getOriginalText', 'testHooks', 'generateKOCBrief', 'repurposeContent', 'analyzeVideoEdit', 'analyzeAlgorithm', 'closeAiModal',
               'openMatrixModal', 'closeMatrixModal', 'openDoctorModal', 'closeDoctorModal', 'openMobileOptimizerModal', 'createNewProject', 'populatePrompt'):
        check(f'giữ hàm {fn}()', fn in defined)
    return ids, script


def js_checks(html, script):
    # 2a. cú pháp: thay {{ ... }} của Jinja bằng null rồi node --check
    src = re.sub(r'\{\{.*?\}\}', 'null', script, flags=re.S)
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(src)
        tmp = f.name
    r = node('--check', tmp, is_file=True)
    check('node --check script trong template', r.returncode == 0, r.stderr.strip()[:300])
    r = node('--check', JS, is_file=True)
    check('node --check promo_video.js', r.returncode == 0, r.stderr.strip()[:300])
    # code (ngoài comment) chỉ dùng ASCII: file .js phục vụ không kèm charset sẽ bị đọc thành windows-1252 và regex
    # chứa ký tự tổ hợp hỏng cú pháp (đã gặp thật khi thử). Comment tiếng Việt thì vô hại.
    code = re.sub(r'/\*.*?\*/', '', read(JS), flags=re.S)
    bad = [i for i, ln in enumerate(code.splitlines(), 1) if re.search(r'[^\x00-\x7f]', re.sub(r'(?<![:\'"])//.*$', '', ln))]
    check('promo_video.js: code chỉ dùng ASCII', not bad, f'dòng (sau khi bỏ comment): {bad[:5]}')
    os.unlink(tmp)

    # 2b. từ điển EN/VI: cùng khoá, mọi khoá đang dùng đều có
    m = re.search(r'const T = (\{.*?\n    \});\n', script, re.S)
    check('tìm thấy từ điển T', bool(m))
    if not m:
        return
    r = node('const T = ' + m.group(1) + '; console.log(JSON.stringify({en: Object.keys(T.en), vi: Object.keys(T.vi)}));')
    check('từ điển T chạy được', r.returncode == 0, r.stderr.strip()[:300])
    if r.returncode != 0:
        return
    keys = json.loads(r.stdout)
    en, vi = set(keys['en']), set(keys['vi'])
    check('EN và VI cùng bộ khoá', en == vi, f'thiếu VI: {sorted(en - vi)[:10]} · thiếu EN: {sorted(vi - en)[:10]}')
    used = set(re.findall(r'data-t[pa]?="([\w]+)"', html)) | set(re.findall(r"""\bt\('([\w]+)'""", script))
    for name_key, desc_key in re.findall(r"""name: '(\w+)', desc: '(\w+)'""", script):   # khoá trong bảng PRESETS
        used |= {name_key, desc_key}
    used |= set(k for _, k in re.findall(r"""\['([\d:]+)', '(\w+)'\]""", script))       # khoá nhãn khung hình
    missing = sorted(k for k in used if k not in en)
    check('mọi khoá t()/data-t có trong từ điển', not missing, ','.join(missing[:20]))


# ------------------------------------------------------------------------------------------------
# 2. promo_video.js với canvas/encoder giả (node thuần)
# ------------------------------------------------------------------------------------------------
NODE_PROMO_TESTS = r'''
const fs = require('fs');
const out = []; const ok = (name, cond, note) => out.push({ name, ok: !!cond, note: note || '' });
function fakeCtx() {
  const ops = { drawImage: 0, fillText: 0, alphaBad: 0 };
  const st = [];
  return { font: '10px x', globalAlpha: 1, ops, textAlign: 'left', textBaseline: 'top',
    measureText(s) { const m = /(\d+)px/.exec(this.font); return { width: String(s).length * (m ? +m[1] : 10) * 0.55 }; },
    fillRect() {}, drawImage() { ops.drawImage++; },
    fillText() { ops.fillText++; if (!(this.globalAlpha >= 0 && this.globalAlpha <= 1)) ops.alphaBad++; },
    beginPath() {}, moveTo() {}, lineTo() {}, quadraticCurveTo() {}, closePath() {}, fill() {},
    save() { st.push(this.globalAlpha); }, restore() { this.globalAlpha = st.pop(); }, translate() {}, scale() {},
    getImageData() { return { data: [0, 0, 0, 0] }; },
    createLinearGradient() { return { addColorStop(o) { if (!(o >= 0 && o <= 1)) throw new Error('bad stop ' + o); } }; },
    createRadialGradient() { return { addColorStop(o) { if (!(o >= 0 && o <= 1)) throw new Error('bad stop ' + o); } }; },
  };
}
const canvases = [];
function fakeCanvas() { const c = { width: 8, height: 8, _ctx: fakeCtx(), getContext() { return c._ctx; } }; canvases.push(c); return c; }
globalThis.document = { createElement: (t) => (t === 'canvas' ? fakeCanvas() : {}), head: { appendChild() {} }, hidden: false };
globalThis.location = { origin: 'http://studio.test' };
new Function(fs.readFileSync(process.argv[2], 'utf8'))();
const P = globalThis.BitPawPromoVideo, I = P._internal;

// --- kịch bản ---
let s = I.normalizeScenes([{ start: 0, end: 3, on_screen_text: 'A' }, { start: 2, end: 2, on_screen_text: 'B' }, { start: 9, end: 30, on_screen_text: 'C' }, null, 'x']);
ok('normalizeScenes: nối liền từ 0, cảnh hỏng = 3 s, cảnh dài kẹp 8 s', s.length === 3 && s[0].start === 0 && s[1].start === 3 && s[1].end === 6 && s[2].end === 14, JSON.stringify(s.map(x => [x.start, x.end])));
s = I.normalizeScenes(Array.from({ length: 30 }, () => ({ start: 0, end: 8 })));
ok('normalizeScenes: tổng ≤ 60 s, ≤ 20 cảnh', s.length <= 20 && s[s.length - 1].end <= 60, s.length + ' cảnh / ' + s[s.length - 1].end + ' s');
ok('normalizeScenes: rỗng -> []', I.normalizeScenes(undefined).length === 0 && I.normalizeScenes([]).length === 0);
const three = [{ start: 0, end: 3, on_screen_text: 'Gel-X that lasts 4 weeks', visual: 'photo', photo_hint: 'gel-x' },
               { start: 3, end: 6, on_screen_text: 'No damage', visual: 'text' },
               { start: 6, end: 9, on_screen_text: 'Relaxing pedicure', visual: 'photo', photo_hint: 'pedicure' }];
ok('planDuration: 9 s + thẻ kết 2.6 s khi có tên tiệm', Math.abs(P.planDuration(three, 'Lotus') - 11.6) < 1e-9 && P.planDuration(three, {}) === 9);

// --- chọn ảnh ---
const pA = { img: { width: 1200, height: 800 }, label: 'Pedicure spa chair' }, pB = { img: { width: 800, height: 1200 }, label: 'Gel-X full set' };
let it = I.normalizeScenes(three); I.assignPhotos(it, [pA, pB]);
ok('assignPhotos: khớp photo_hint với tên ảnh', it[0].img === pB.img && it[2].img === pA.img);
ok('assignPhotos: cảnh "text" không có ảnh', it[1].img === null);
it = I.normalizeScenes([{ visual: 'photo', photo: 0, photo_hint: 'gel-x' }]); I.assignPhotos(it, [pA, pB]);
ok('assignPhotos: chủ tiệm chọn tay thắng gợi ý', it[0].img === pA.img);
it = I.normalizeScenes([{}, {}, {}, {}]); I.assignPhotos(it, [pA, pB]);
ok('assignPhotos: xoay vòng, không lặp liền nhau', it.every((x, i) => i === 0 || x.img !== it[i - 1].img), it.map(x => x.img === pA.img ? 'A' : 'B').join(''));
it = I.normalizeScenes([{}, {}]); I.assignPhotos(it, [{ img: null, label: 'broken' }]);
ok('assignPhotos: ảnh hỏng -> thẻ chữ', it.every(x => x.img === null));

// --- chữ ---
const c = fakeCtx();
const long = 'Our brand new Gel-X extensions last a full four weeks without any damage to your natural nails, book online today';
const f = I.fitText(c, long, 570, 4, 68, 40, 800);
c.font = '800 ' + f.size + 'px x';
ok('fitText: ≤ 4 dòng, mỗi dòng vừa khung', f.lines.length <= 4 && f.lines.every(l => c.measureText(l).width <= 570), f.size + 'px × ' + f.lines.length);
c.font = '800 60px x';
const w = I.wrapLines(c, 'https://example.com/a-very-long-booking-link-that-cannot-fit', 300);
ok('wrapLines: từ quá dài bị cắt theo ký tự', w.length > 1 && w.every(l => c.measureText(l).width <= 300));

// --- vẽ mọi khung hình ---
const plan = I.buildPlan({ scenes: three, brand: { name: 'Lotus Nails Sydney', cta: 'Book online — link in bio', accent: '#f472b6' } }, [pA, pB]);
const fc = fakeCtx(); let err = null;
try { for (let i = 0; i <= Math.round(plan.duration * 30); i++) I.drawFrame(fc, plan, Math.min(i / 30, plan.duration - 1e-3)); } catch (e) { err = e; }
ok('drawFrame: mọi khung 0→hết không lỗi', !err, err ? err.message : plan.items.length + ' mục, ' + plan.duration + ' s');
ok('drawFrame: có vẽ ảnh + chữ, alpha luôn 0–1', fc.ops.drawImage > 0 && fc.ops.fillText > 0 && fc.ops.alphaBad === 0, JSON.stringify(fc.ops));
ok('buildPlan: thẻ kết cuối cùng, kích thước chẵn', plan.items[plan.items.length - 1].kind === 'end' && plan.W === 720 && plan.H === 1280);
const odd = I.buildPlan({ scenes: three, width: 721, height: 1281, brand: '' }, []);
ok('buildPlan: kích thước lẻ -> làm chẵn, không tên tiệm = không thẻ kết', odd.W % 2 === 0 && odd.H % 2 === 0 && odd.items.every(x => x.kind !== 'end'));

// --- render(): WebCodecs + mp4-muxer giả ---
function installFakes(supported, opts) {
  opts = opts || {};
  const log = { frames: 0, keys: 0, ts: [], chunks: 0, configured: null };
  globalThis.VideoFrame = class { constructor(cv, init) { this.timestamp = init.timestamp; this.duration = init.duration; } close() {} };
  globalThis.VideoEncoder = class {
    static isConfigSupported(cfg) { return Promise.resolve({ supported: supported.includes(cfg.codec), config: cfg }); }
    constructor(o) { this.o = o; this.encodeQueueSize = 0; this.state = 'unconfigured'; }
    configure(cfg) { this.state = 'configured'; log.configured = cfg; }
    encode(fr, o) {
      log.frames++; log.ts.push(fr.timestamp); if (o.keyFrame) log.keys++;
      if (opts.failAt && log.frames === opts.failAt) { this.o.error(new Error('hw encoder died')); return; }
      this.o.output({ type: o.keyFrame ? 'key' : 'delta', timestamp: fr.timestamp, byteLength: 100 }, o.keyFrame ? { decoderConfig: { codec: 'avc1' } } : undefined);
    }
    flush() { return Promise.resolve(); } close() { this.state = 'closed'; } addEventListener() {} removeEventListener() {}
  };
  globalThis.Mp4Muxer = {
    ArrayBufferTarget: class { constructor() { this.buffer = null; } },
    Muxer: class { constructor(o) { this.o = o; this.n = 0; } addVideoChunk() { this.n++; log.chunks++; } finalize() { this.o.target.buffer = new ArrayBuffer(this.n * 100); } },
  };
  return log;
}
(async () => {
  let log = installFakes(['avc1.42E01F']);
  const prog = [];
  const blob = await P.render({ scenes: three, photos: [], brand: 'Lotus', width: 720, height: 1280, fps: 30, bitrate: 2000000, onProgress: (p) => prog.push(p.phase) });
  const frames = Math.round(11.6 * 30);
  ok('render: MP4 qua VideoEncoder avc1.42E01F', blob.type === 'video/mp4' && P.lastInfo.codec === 'avc1.42E01F' && log.configured.codec === 'avc1.42E01F', blob.type + ' ' + P.lastInfo.codec);
  ok('render: đủ khung (' + frames + '), keyframe mỗi 2 s, timestamp tăng dần', log.frames === frames && log.keys === Math.ceil(frames / 60) && log.ts.every((t, i) => i === 0 || t > log.ts[i - 1]), log.frames + ' khung, ' + log.keys + ' key');
  ok('render: cấu hình 720×1280, 2 Mbps, 30 fps', log.configured.width === 720 && log.configured.height === 1280 && log.configured.bitrate === 2000000 && log.configured.framerate === 30);
  ok('render: báo tiến độ loading → encoding → done', prog[0] === 'loading' && prog.includes('encoding') && prog[prog.length - 1] === 'done', [...new Set(prog)].join('>'));

  log = installFakes(['avc1.42E020']);
  await P.render({ scenes: three, brand: '' });
  ok('render: thử codec dự phòng khi 42E01F bị từ chối', P.lastInfo.codec === 'avc1.42E020');

  installFakes([]);
  let e1 = null; try { await P.render({ scenes: three }); } catch (e) { e1 = e; }
  ok('render: không H.264 + không MediaRecorder -> lỗi "unsupported" (không treo)', e1 && e1.code === 'unsupported', e1 && e1.code);

  installFakes(['avc1.42E01F'], { failAt: 20 });
  let e2 = null; try { await P.render({ scenes: three }); } catch (e) { e2 = e; }
  ok('render: encoder chết giữa chừng -> chuyển dự phòng, báo lỗi rõ', e2 && e2.code === 'unsupported', e2 && e2.code);

  installFakes(['avc1.42E01F']);
  const ac = new AbortController(); ac.abort();
  let e3 = null; try { await P.render({ scenes: three, signal: ac.signal }); } catch (e) { e3 = e; }
  ok('render: huỷ -> lỗi "aborted"', e3 && e3.code === 'aborted', e3 && e3.code);

  let e4 = null; try { await P.render({ scenes: [] }); } catch (e) { e4 = e; }
  ok('render: không có cảnh -> lỗi "no_scenes"', e4 && e4.code === 'no_scenes', e4 && e4.code);
  ok('MUXER_URL đúng hợp đồng', I.MUXER_URL === 'https://cdn.jsdelivr.net/npm/mp4-muxer@5/build/mp4-muxer.min.js' && I.AVC_CODECS[0] === 'avc1.42E01F');
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { out.push({ name: 'promo tests crashed', ok: false, note: String(e && e.stack || e) }); console.log(JSON.stringify(out)); process.exit(0); });
'''


def promo_unit_tests():
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(NODE_PROMO_TESTS)
        tmp = f.name
    try:
        r = node(tmp, JS, is_file=True)
    finally:
        os.unlink(tmp)
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        check('promo_video.js unit tests chạy được', False, (r.stderr or r.stdout)[:400])
        return
    for row in rows:
        check('promo_video: ' + row['name'], row['ok'], row.get('note', ''))


# ------------------------------------------------------------------------------------------------
# 3. (tuỳ chọn) Chrome thật + API giả
# ------------------------------------------------------------------------------------------------
def render_standalone(lang='en', currency='USD', industry='nail'):
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    def url_for(endpoint, **kw):
        return '/static/' + kw['filename'] if endpoint == 'static' else '/' + endpoint

    class Req:
        path = '/ai-studio'

    env = Environment(loader=FileSystemLoader(os.path.join(ROOT, 'templates')), autoescape=select_autoescape(['html']))
    menu = defaultdict(lambda: 'Menu')
    return env.get_template('ai-studio.html').render(
        url_for=url_for, session={'user_id': 1, 'role': 'admin'}, request=Req(), default_lang=lang, tenant_currency=currency,
        active_industry_code=industry, active_industry_cfg={'modules': ['nail_services', 'attendance', 'payroll']},
        menu_i18n=menu, menu_i18n_all={'en': {}, 'vi': {}}, industry_pos_url='/sell', industry_chamcong_url='/chamcong',
        asset_version='test')


def find_playwright():
    d = ROOT
    for _ in range(6):
        p = os.path.join(d, 'node_modules', 'playwright')
        if os.path.isdir(p):
            return p
        d = os.path.dirname(d)
    return None


NODE_BROWSER = r'''
const { chromium } = require(process.env.PW_PATH);
const fs = require('fs'), path = require('path');
const HTML = fs.readFileSync(process.env.HTML_FILE, 'utf8'), STATIC = process.env.STATIC_DIR, SHOTS = process.env.SHOTS;
// https: WebCodecs (VideoEncoder) chỉ có trong "secure context" — trang http giả sẽ luôn rơi về WebM
const BASE = 'https://studio.test';
const out = []; const ok = (name, cond, note) => { out.push({ name, ok: !!cond, note: note || '' }); };
const HEX = (c) => c.repeat(24);
const BIG = Buffer.alloc(8000000, 7);   // file > 3.5 MB để thử tải về nhiều lát Range
const S = {
  quota: { plan: 'empire', month: '2026-10', images: { used: 3, limit: 50 }, video_seconds: { used: 10, limit: 120 } },
  items: [
    { id: HEX('a'), file_id: HEX('a'), kind: 'image', preset: 'hd', prompt: 'Glossy nude gel nails', status: 'succeeded', public_url: '/m/a.jpg', url: '/m/a.jpg', content_type: 'image/jpeg', created_at: '2026-10-20T10:00:00Z', cost_estimate_usd: 0.04, source: 'replicate' },
    { id: HEX('e'), file_id: HEX('e'), kind: 'promo_video', public_url: '/m/big.mp4', url: '/m/big.mp4', content_type: 'video/mp4', created_at: '2026-10-21T10:00:00Z', source: 'browser' },
  ],
  jobMode: 'ok', polls: 0, bodies: [], chunks: [], init: null, finish: 0, deleted: [], dialogs: [], plan: null,
};
(async () => {
  const browser = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errs = []; page.on('pageerror', (e) => errs.push(e.message));
  page.on('dialog', async (d) => { S.dialogs.push(d.type()); await d.accept(); });
  await ctx.route('**/*', async (route) => {
    const req = route.request(), url = new URL(req.url()), m = req.method(), p = url.pathname;
    if (url.host === 'example.com') return route.abort();
    if (url.host !== 'studio.test') return route.continue();      // font, Font Awesome, mp4-muxer (jsdelivr)
    const json = (o, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(o) });
    if (p === '/ai-studio') return route.fulfill({ status: 200, contentType: 'text/html', body: HTML });
    if (p.startsWith('/static/')) { const f = path.join(STATIC, p.slice(8)); return fs.existsSync(f) ? route.fulfill({ path: f }) : route.fulfill({ status: 404, body: '' }); }
    if (p.startsWith('/api/public/storage/file/') || p === '/m/a.jpg' || p === '/m/tok.jpg') return route.fulfill({ path: path.join(STATIC, 'cho1.jpg'), contentType: 'image/jpeg' });
    if (p === '/m/big.mp4') {
      const r = /bytes=(\d+)-(\d*)/.exec(req.headers()['range'] || '');
      if (!r) return route.fulfill({ status: 206, headers: { 'Content-Range': `bytes 0-3499999/${BIG.length}`, 'Content-Type': 'video/mp4' }, body: BIG.subarray(0, 3500000) });
      const a = +r[1], b = Math.min(r[2] ? +r[2] : a + 3499999, a + 3499999, BIG.length - 1);
      return route.fulfill({ status: 206, headers: { 'Content-Range': `bytes ${a}-${b}/${BIG.length}`, 'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes' }, body: BIG.subarray(a, b + 1) });
    }
    if (p === '/api/ai_studio/brand') return json({ success: true, brand: { name: 'Lotus Nails Sydney', usp: 'Gel-X that lasts 4 weeks' } });
    if (p === '/api/ai_studio/quota') return json({ success: true, quota: S.quota });
    if (p === '/api/ai_studio/media' && m === 'GET') return json({ success: true, items: S.items, quota: S.quota });
    if (p === '/api/ai_studio/media/jobs' && m === 'POST') {
      const body = req.postDataJSON(); S.bodies.push(body);
      if (S.jobMode === 'quota') return json({ success: false, code: 'quota_exceeded', message: 'Monthly image quota used' }, 402);
      if (S.jobMode === 'upgrade') return json({ success: false, upgrade_required: true, plan: 'pro', required_plan: 'empire', feature: 'ai_studio', message: 'AI Studio is included in Empire and above.' }, 403);
      if (S.jobMode === 'notconf') return json({ success: false, code: 'not_configured', message: 'REPLICATE_API_TOKEN missing' }, 503);
      S.polls = 0;
      return json({ success: true, job: { id: 77, kind: body.kind, preset: body.preset, status: 'queued', prompt: body.prompt || 'derived prompt from script' }, quota: S.quota });
    }
    if (/^\/api\/ai_studio\/media\/jobs\/77$/.test(p)) {
      S.polls++;
      if (S.polls < 2) return json({ success: true, job: { id: 77, kind: 'image', preset: 'hd', status: 'running' } });
      return json({ success: true, job: { id: 77, kind: 'image', preset: 'hd', status: 'succeeded', file_id: HEX('f'), public_url: '/m/tok.jpg', content_type: 'image/jpeg', cost_estimate_usd: 0.04, prompt: 'derived' } });
    }
    if (m === 'DELETE' && p.startsWith('/api/ai_studio/media/')) { S.deleted.push(p); return json({ success: true }); }
    if (p === '/api/inventory/products') return json({ success: true, data: [
      { id: 1, name: 'Gel-X full set', image: '/api/public/storage/file/' + HEX('b') },
      { id: 2, name: 'Spa pedicure', image: '/api/public/storage/file/' + HEX('c') },
      { id: 3, name: 'Linked photo', image: 'https://example.com/x.jpg' }, { id: 4, name: 'No photo' } ] });
    if (p === '/api/ai_studio/scene_plan') { S.plan = req.postDataJSON(); return json({ success: true, title: 'Gel-X', caption: 'Book your Gel-X today #nails', scenes: [
      { start: 0, end: 3, on_screen_text: 'Gel-X that lasts 4 weeks', voiceover: 'Meet Gel-X', visual: 'photo', photo_hint: 'gel-x' },
      { start: 3, end: 6, on_screen_text: 'No damage to your nails', visual: 'text' },
      { start: 6, end: 9, on_screen_text: 'Relax with a spa pedicure', visual: 'photo', photo_hint: 'pedicure' } ] }); }
    if (p === '/api/media/upload/init') { S.init = req.postDataJSON(); S.chunks = []; return json({ success: true, upload_id: 'up1' }); }
    if (p === '/api/media/upload/up1/chunk') { const buf = req.postDataBuffer() || Buffer.alloc(0); S.chunks.push({ index: +url.searchParams.get('index'), size: buf.length, head: buf.subarray(0, 12).toString('latin1') }); return json({ success: true, received: buf.length }); }
    if (p === '/api/media/upload/up1/finish') { S.finish++; return json({ success: true, file_id: HEX('d'), url: '/m/promo.mp4', public_url: '/m/promo.mp4' }); }
    if (p === '/api/ai_studio/generate_text') return json({ success: true, choices: [{ message: { content: 'HOOK: Gel-X that lasts four weeks\nShot 1: close-up\nBook online today #nails #gelx' } }] });
    if (p === '/api/messages/pump') return json({ success: true });
    return json({ success: false, message: 'no mock for ' + p }, 404);
  });

  await page.goto(BASE + '/ai-studio', { waitUntil: 'load' });
  await page.waitForTimeout(1200);
  ok('tải trang không lỗi JS', errs.length === 0, errs.join(' | '));
  ok('hạn mức thật từ /quota', /Images 3\/50 this month/.test(await page.textContent('#qImages')), await page.textContent('#qImages'));

  // Viết
  await page.fill('#userPrompt', 'A TikTok for Gel-X');
  await page.click('button[onclick="startDeepSeekRewrite(this)"]');
  await page.waitForFunction(() => /HOOK/.test(document.getElementById('aiScript').value), null, { timeout: 10000 });
  ok('Viết: kịch bản về ô + nhãn "Brand DNA used" (có DNA thật)', await page.isVisible('#brandChip'));
  await page.click('button[onclick="diagnoseChannel(this)"]', { trial: true }).catch(() => {});
  await page.evaluate(() => openDoctorModal()); await page.click('button[onclick="diagnoseChannel(this)"]');
  ok('Khám kênh thiếu số -> toast (không alert)', /Paste the numbers/.test(await page.textContent('#toast')) && !S.dialogs.includes('alert'));
  await page.evaluate(() => closeDoctorModal());

  // 390 px: không cuộn ngang ở mọi tab, thanh công cụ thấy được
  await page.setViewportSize({ width: 390, height: 844 });
  for (const tab of ['write', 'images', 'video', 'gallery']) {
    await page.evaluate((t) => setTab(t), tab); await page.waitForTimeout(250);
    const sw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    ok(`390px tab ${tab}: không cuộn ngang`, sw[0] <= sw[1], sw.join(' vs '));
    await page.screenshot({ path: path.join(SHOTS, `studio_390_${tab}.png`), fullPage: true });
  }
  for (const mode of ['photo', 'promo']) {
    await page.evaluate((m) => { setTab('video'); setVMode(m); }, mode); await page.waitForTimeout(200);
    const sw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    ok(`390px video/${mode}: không cuộn ngang`, sw[0] <= sw[1], sw.join(' vs '));
  }
  await page.evaluate(() => setTab('write'));
  const tb = await page.$('button[onclick="openBrandModal()"]'); const bb = tb && await tb.boundingBox();
  ok('390px: menu công cụ (Brand DNA…) hiện và bấm được', !!bb && bb.width > 0 && bb.x >= 0 && bb.x + bb.width <= 390);
  await page.setViewportSize({ width: 1440, height: 950 });

  // Ảnh: job + poll 3 s
  await page.evaluate(() => setTab('images'));
  await page.check('input[name=imgPreset][value=hd]');
  ok('preset hiện giá + hạn mức còn lại', /US\$0\.04/.test(await page.textContent('#imgPresets')) && /47 images left/.test(await page.textContent('#imgPresets')));
  await page.fill('#imgPrompt', 'Glossy gel nails on marble');
  await page.click('#imgGo');
  await page.waitForSelector('#imgJobs .st-pill.run');
  ok('POST jobs đúng hợp đồng', JSON.stringify(S.bodies[0]) === JSON.stringify({ kind: 'image', preset: 'hd', aspect: '1:1', prompt: 'Glossy gel nails on marble' }), JSON.stringify(S.bodies[0]));
  await page.waitForSelector('#imgJobs .st-pill.ok', { timeout: 12000 });
  ok('poll mỗi 3 s tới khi xong + nút "Use in a post"', S.polls >= 2 && /compose=1&media=f{24}/.test(await page.getAttribute('#imgJobs a.btn', 'href')));
  await page.click('#panel-images button[onclick="useScript(\'image\')"]');
  ok('"From my script" hiện chip', await page.isVisible('#imgScriptChip'));
  await page.click('#imgGo'); await page.waitForTimeout(300);
  ok('from_text gửi kịch bản', (S.bodies[1].from_text || '').startsWith('HOOK') && !S.bodies[1].prompt, JSON.stringify(S.bodies[1]).slice(0, 120));
  for (const [mode, re] of [['quota', /allowance/], ['upgrade', /Empire and above/], ['notconf', /not switched on/]]) {
    S.jobMode = mode; await page.click('#imgGo'); await page.waitForTimeout(300);
    const txt = await page.textContent('#imgAlert');
    ok(`lỗi ${mode} nói rõ`, re.test(txt) && (mode === 'notconf' || /See plans/.test(txt)), txt);
  }
  S.jobMode = 'ok';

  // Video: clip premium 8 s + làm ảnh chuyển động từ ảnh tiệm
  await page.evaluate(() => { setTab('video'); setVMode('clip'); });
  await page.check('input[name=vidPreset][value=premium]');
  await page.click('#vidSeconds [data-s="8"]');
  ok('premium 8 s = US$1.20', /US\$1\.20/.test(await page.textContent('#vidCostLine')));
  await page.fill('#vidPrompt', 'Slow pan across the salon');
  await page.click('#vidGo'); await page.waitForTimeout(300);
  const vb = S.bodies[S.bodies.length - 1];
  ok('POST video: preset/duration/aspect', vb.kind === 'video' && vb.preset === 'premium' && vb.duration === 8 && vb.aspect === '9:16', JSON.stringify(vb));
  await page.evaluate(() => setVMode('photo'));
  await page.evaluate(() => openPicker('animate'));
  await page.waitForSelector('#pickGrid [data-key]');
  ok('ảnh link ngoài bị khoá khi làm chuyển động', await page.$eval('#pickGrid [data-key*="example.com"]', (b) => b.disabled));
  await page.click('#pickGrid [data-key]:not([disabled])');
  await page.click('#vidGo'); await page.waitForTimeout(300);
  const pb = S.bodies[S.bodies.length - 1];
  ok('animate: gửi image_file_id của ảnh tiệm', pb.image_file_id === HEX('b') && !!pb.prompt, JSON.stringify(pb).slice(0, 160));

  // Video quảng cáo miễn phí
  await page.evaluate(() => setVMode('promo'));
  await page.fill('#promoTopic', 'Gel-X extensions, 4 weeks of wear');
  await page.click('#promoPlanBtn');
  await page.waitForSelector('#promoScenes .scene');
  ok('scene_plan: gửi topic/seconds/lang', S.plan && S.plan.topic && S.plan.seconds === 15 && S.plan.lang === 'en', JSON.stringify(S.plan));
  await page.evaluate(() => openPicker('promo'));
  await page.waitForSelector('#pickGrid [data-key]');
  const keys = await page.$$('#pickGrid [data-key]');
  await keys[0].click(); await keys[1].click(); await page.click('#pickDone');
  ok('đã chọn 2 ảnh tiệm', (await page.$$('#promoPhotos .ph')).length === 2);
  const fmt = await page.textContent('#promoSupport');
  await page.click('#promoGo');
  await page.waitForSelector('#promoUse:not(.hidden)', { timeout: 120000 }).catch(() => {});
  const totalUp = S.chunks.reduce((a, c) => a + c.size, 0);
  ok('video dựng xong và lưu (init → chunk → finish)', S.finish === 1 && S.init && totalUp === S.init.size, JSON.stringify({ init: S.init, chunks: S.chunks.length, totalUp, err: await page.textContent('#promoAlert') }));
  ok('mỗi khúc ≤ 3.4 MB', S.chunks.every((c) => c.size <= 3400000));
  ok('MP4 thật qua WebCodecs (hộp ftyp) — ' + fmt, S.init && S.init.content_type === 'video/mp4' && S.chunks[0].head.slice(4, 8) === 'ftyp', S.init && S.init.content_type);
  ok('mp4-muxer nạp từ jsdelivr', await page.evaluate(() => !!(window.Mp4Muxer && window.Mp4Muxer.Muxer)));
  const dur = await page.evaluate(() => new Promise((r) => { const v = document.getElementById('promoVideo'); if (v.readyState >= 1) r(v.duration); else { v.onloadedmetadata = () => r(v.duration); setTimeout(() => r(v.duration), 4000); } }));
  ok('độ dài video ≈ 11.6 s (3 cảnh + thẻ kết)', Math.abs(dur - 11.6) < 0.6 || !isFinite(dur), String(dur));
  ok('"Use in a post" trỏ /social với file_id', /\/social\?compose=1&media=d{24}/.test(await page.getAttribute('#promoUse', 'href')));
  // file 8 MB (video 30 s) -> 3 khúc 3.4 + 3.4 + 1.2 MB, đúng thứ tự index
  const up = await page.evaluate(async () => (await uploadChunked(new Blob([new Uint8Array(8000000)], { type: 'video/mp4' }), 'promo_video')).file_id);
  ok('tải lên 8 MB = 3 khúc ≤ 3.4 MB theo thứ tự', up === HEX('d') && S.chunks.map((c) => c.index).join() === '0,1,2' && S.chunks.map((c) => c.size).join() === '3400000,3400000,1200000', JSON.stringify(S.chunks.map((c) => [c.index, c.size])));
  await page.screenshot({ path: path.join(SHOTS, 'studio_1440_promo.png'), fullPage: true });

  // Thư viện: tải nhiều lát Range + xoá
  await page.evaluate(() => { GAL_FILTER = 'video'; setTab('gallery'); renderGallery(); });
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 15000 }).catch(() => null), page.click('#galGrid [data-dl="/m/big.mp4"]')]);
  const size = dl ? fs.statSync(await dl.path()).size : -1;
  ok('tải về ghép đủ các lát Range (8 MB)', size === BIG.length, String(size));
  await page.evaluate(() => { GAL_FILTER = 'all'; renderGallery(); });
  await page.click('#galGrid [data-del]'); await page.waitForTimeout(300);
  ok('xoá file gọi DELETE /api/ai_studio/media/<id>', S.deleted.length === 1 && S.dialogs.includes('confirm'));

  // EN/VI tại chỗ
  await page.evaluate(() => { localStorage.setItem('bitpaw_lang', 'vi'); changeLanguage('vi'); setTab('images'); });
  ok('đổi sang tiếng Việt tại chỗ', (await page.textContent('#tab-write')).includes('Viết') && (await page.textContent('#imgGo')).includes('Tạo ảnh') && /Ảnh 3\/50/.test(await page.textContent('#qImages')));
  await page.screenshot({ path: path.join(SHOTS, 'studio_1440_images_vi.png'), fullPage: true });
  await page.evaluate(() => { localStorage.setItem('bitpaw_lang', 'en'); changeLanguage('en'); setTab('write'); });
  await page.screenshot({ path: path.join(SHOTS, 'studio_1440_write.png'), fullPage: true });
  ok('không có hộp alert() nào', !S.dialogs.includes('alert'), S.dialogs.join(','));
  ok('không lỗi JS suốt quá trình', errs.length === 0, errs.join(' | '));
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { out.push({ name: 'browser test crashed', ok: false, note: String(e && e.stack || e).slice(0, 600) }); console.log(JSON.stringify(out)); process.exit(0); });
'''


def browser_tests():
    pw = find_playwright()
    if not pw:
        check('Playwright có sẵn (node_modules/playwright)', False, 'cài ở repo chính: npm i -D playwright')
        return
    shots = os.environ.get('STUDIO_SHOTS') or tempfile.mkdtemp(prefix='studio_shots_')
    html = render_standalone()
    tmpdir = tempfile.mkdtemp(prefix='studio_ui_')
    html_file = os.path.join(tmpdir, 'ai-studio.html')
    js_file = os.path.join(tmpdir, 'browser_test.js')
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html)
    with open(js_file, 'w', encoding='utf-8') as f:
        f.write(NODE_BROWSER)
    env = dict(os.environ, PW_PATH=pw, HTML_FILE=html_file, STATIC_DIR=os.path.join(ROOT, 'static'), SHOTS=shots)
    r = node(js_file, is_file=True, env=env, timeout=400)
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        check('browser tests chạy được', False, (r.stderr or r.stdout)[-600:])
        return
    for row in rows:
        check('browser: ' + row['name'], row['ok'], row.get('note', ''))
    print(f'  screenshots: {shots}')


def main():
    html = read(TPL)
    ids, script = static_checks(html)
    js_checks(html, script)
    promo_unit_tests()
    if '--browser' in sys.argv:
        browser_tests()
    print(f'\n{"OK" if not FAILS else "FAILED"} — {len(FAILS)} lỗi')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
