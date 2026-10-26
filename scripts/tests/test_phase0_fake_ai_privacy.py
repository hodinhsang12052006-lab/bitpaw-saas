# -*- coding: utf-8 -*-
"""Test OFFLINE cho Phase 0 — "gỡ AI giả + chặn rò rỉ riêng tư trên các trang".

Không chạy server, KHÔNG import app.py / mongo_client thật (mongo_client nối thẳng DB PRODUCTION), không gọi API thật:
- route /api/portal/messages (POST) lấy nguyên mã nguồn từ app.py qua ast, chạy trong Flask test app với db giả;
- logic "gợi ý thợ rảnh gần nhất" của map_dashboard.html chạy trong node với Leaflet/hrApi giả;
- --browser: Chrome thật (Playwright của repo chính), mọi request đều do page.route trả lời (không máy chủ nào lắng nghe):
  cskh_widget.js ở 3 ngữ cảnh (trang đặt lịch / trang của tiệm / landing BitPaw), table_order.html, portal.html.

Chạy:  python scripts/tests/test_phase0_fake_ai_privacy.py            # tĩnh + route + node
       python scripts/tests/test_phase0_fake_ai_privacy.py --browser  # thêm kiểm thử trên Chrome thật
"""
import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

# stub TRƯỚC mọi import có thể kéo mongo_client thật
sys.modules['mongo_client'] = types.SimpleNamespace(db=MagicMock(name='db'), next_mongo_id=lambda c: 1, MONGO_STATUS='CONNECTED')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def check(name, ok, note=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {note}' if note and not ok else ''))
    if not ok:
        FAILS.append(name)


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding='utf-8').read()


def inline_scripts(html):
    """<script> inline (không src), thay biểu thức Jinja bằng 0 để node --check được."""
    out = []
    for m in re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S):
        code = re.sub(r'\{\{.*?\}\}', '0', m.group(1), flags=re.S)
        code = re.sub(r'\{%.*?%\}|\{#.*?#\}', '', code, flags=re.S)
        out.append(code)
    return out


def node_check(name, code):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(code)
    r = subprocess.run(['node', '--check', f.name], capture_output=True, text=True, encoding='utf-8')
    os.unlink(f.name)
    check(f'node --check {name}', r.returncode == 0, r.stderr[-400:])


def js_function(src, name):
    """Cắt nguyên 1 function JS (đếm ngoặc nhọn) — đủ cho các hàm trong test này."""
    m = re.search(r'(async\s+)?function\s+' + re.escape(name) + r'\s*\(', src)
    if not m:
        return None
    i = src.index('{', m.end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    return None


# ============================================================ 1. table_order.html: không còn bot bán hàng BitPaw
def test_table_order():
    s = read('templates/table_order.html')
    check('table_order: không nạp cskh_widget.js', re.search(r'<script[^>]+cskh_widget\.js', s) is None)
    check('table_order: không nạp cskh_track.js (form gửi /api/cskh/request)', re.search(r'<script[^>]+cskh_track\.js', s) is None)
    check('table_order: không fetch /api/cskh/*', re.search(r'fetch\([^)]*/api/cskh/', s) is None)
    check('table_order: không đặt BITPAW_BUSINESS_ID cho widget', 'window.BITPAW_BUSINESS_ID' not in s)
    for i, code in enumerate(inline_scripts(s)):
        node_check(f'table_order.html script#{i}', code)


# ============================================================ 2. cskh_widget.js: lead BitPaw chỉ từ landing BitPaw + chat_token
def test_widget_static():
    s = read('static/js/cskh_widget.js')
    node_check('static/js/cskh_widget.js', s)
    check('widget: cờ IS_BITPAW_MARKETING_PAGE = không business_id + không customer_booking',
          "const IS_BITPAW_MARKETING_PAGE = !BUSINESS_ID && CHAT_CONTEXT !== 'customer_booking';" in s)
    calls = [m.start() for m in re.finditer(r'fetch\("/api/cskh/request"', s)]
    guarded = all('if (IS_BITPAW_MARKETING_PAGE) {' in s[max(0, c - 200):c] for c in calls)
    check('widget: mọi lời gọi /api/cskh/request nằm trong if (IS_BITPAW_MARKETING_PAGE)', len(calls) == 1 and guarded, f'{len(calls)} lời gọi')
    gens = [m.start() for m in re.finditer(r'fetch\("/api/ai/studio/generate"', s)]
    with_tok = [g for g in gens if '...bookingTokenField()' in s[g:g + 2600]]
    check('widget: mọi /api/ai/studio/generate gửi kèm chat_token (customer_booking)', len(gens) == 2 and len(with_tok) == 2, f'{len(with_tok)}/{len(gens)}')
    check('widget: token lưu localStorage "bp_chat_token", 32 hex', '"bp_chat_token"' in s and '/^[0-9a-f]{32}$/' in s and 'new Uint8Array(16)' in s)
    check('widget: localStorage bọc try/catch', 'try { tok = localStorage.getItem("bp_chat_token")' in s and 'try { localStorage.setItem("bp_chat_token", tok); }' in s)
    check('widget: chỉ hứa "chuyên viên BitPaw sẽ liên hệ" khi lead thật sự được ghi',
          re.search(r'if \(IS_BITPAW_MARKETING_PAGE\) \{[^\n]*\n\s*// Lượt đầu: xác nhận đã nhận SĐT', s) is not None)


# ============================================================ 3. portal.html: không còn "AI" giả
def test_portal_static():
    s = read('templates/portal.html')
    for bad in ('getAIResponse', 'applyHumanTypo', 'followUpTimer', 'resetFollowUpTimer', 'detectHandOff', 'typeMessageWithDelay',
                'sendMultipleMessages', 'processUserMessage', '2.5 triệu', '800k', 'voucher 200k', 'giảm 20%', 'Quản lý kho lên đơn',
                'có đang online đó không', 'Online 24/7', 'Bảo mật tuyệt đối', 'Fully Secure', 'Trợ lý chốt sale', 'portal_welcome_message'):
        check(f'portal: đã gỡ "{bad}"', bad not in s)
    check("portal: chỉ POST sender_type 'customer'", "sender_type: 'customer'" in s and "'ai')" not in s and 'sender_type: senderType' not in s)
    check('portal: id từ URL không chèn innerHTML', 'ID: ${currentCustomerId}`;' not in s and 'createTextNode' in s)
    check('portal: link ảnh lọc dấu nháy/<> (không chèn được thuộc tính vào <img>)', '[^\\s"\'<>]+' in s)
    for k in ('portal_staff_label', 'portal_ai_label', 'portal_empty_note', 'portal_err_send', 'portal_qm_booking'):
        check(f'portal: khoá i18n {k} có cả VI và EN', len(re.findall(r'^\s*' + k + r':', s, re.M)) == 2)
    for i, code in enumerate(inline_scripts(s)):
        node_check(f'portal.html script#{i}', code)


# ============================================================ 4. /api/portal/messages POST: ẩn danh chỉ ghi 'customer'
def test_portal_route():
    from flask import Flask, jsonify, request
    from datetime import datetime
    src = read('app.py')
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'api_portal_messages_create')
    node.decorator_list = []
    db = MagicMock(name='db')
    ns = {'request': request, 'jsonify': jsonify, 'db': db, 'datetime': datetime,
          '_resolve_portal_customer': lambda cid: {'id': cid, 'business_id': 'biz1'} if cid == 'biz1:0412345678' else None}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'app.py::api_portal_messages_create', 'exec'), ns)
    app = Flask('t')
    app.add_url_rule('/api/portal/messages', 'c', ns['api_portal_messages_create'], methods=['POST'])
    c = app.test_client()
    for st in ('ai', 'staff', 'AI', 'system'):
        db.reset_mock()
        r = c.post('/api/portal/messages', json={'customer_id': 'biz1:0412345678', 'content': 'giả danh', 'sender_type': st})
        check(f"route: sender_type='{st}' ẩn danh -> 400, không ghi gì", r.status_code == 400 and not db.bot_messages.insert_one.called, str(r.status_code))
    db.reset_mock()
    r = c.post('/api/portal/messages', json={'customer_id': 'biz1:0412345678', 'content': 'Parking?', 'sender_type': 'customer'})
    doc = db.bot_messages.insert_one.call_args[0][0] if db.bot_messages.insert_one.called else {}
    check("route: sender_type='customer' -> 200 + ghi đúng 1 tin của khách", r.status_code == 200 and doc.get('sender_type') == 'customer'
          and doc.get('business_id') == 'biz1' and doc.get('content') == 'Parking?', f'{r.status_code} {doc}')
    db.reset_mock()
    r = c.post('/api/portal/messages', json={'customer_id': 'biz1:0412345678', 'content': 'hi'})
    doc = db.bot_messages.insert_one.call_args[0][0] if db.bot_messages.insert_one.called else {}
    check('route: thiếu sender_type -> mặc định customer', r.status_code == 200 and doc.get('sender_type') == 'customer')
    r = c.post('/api/portal/messages', json={'customer_id': 'biz1:0000', 'content': 'x', 'sender_type': 'customer'})
    check('route: customer_id lạ -> 404', r.status_code == 404)


# ============================================================ 5. map_dashboard.html
MAP_HARNESS = r'''
const SRC = JSON.parse(process.env.MAP_FUNCS);
const out = []; const ok = (n, c, note) => out.push({ name: n, ok: !!c, note: note || '' });
const alerts = [], patches = [], toasts = [];
let tasksDb = [];
global.__escHtml = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
global.t = (k) => k;
global.tf = (k, p) => k + ' ' + JSON.stringify(p);
global.showAIAlert = (msg, title, action) => alerts.push({ msg, title, action });
global.showToast = (m) => toasts.push(m);
global.setTimeout = (fn) => fn();
const btn = { innerHTML: 'x', disabled: false };
global.document = { getElementById: () => btn };
global.map = { removeLayer() {}, flyToBounds() {} };
global.activeLaserLine = null; global.activeTargetMarker = null;
global.L = {
  latLng: (a, b) => ({ a, b, distanceTo(o) { return Math.hypot(this.a - o.a, this.b - o.b) * 111000; } }),
  divIcon: () => ({}), marker: () => ({ addTo() { return this; } }), polyline: () => ({ addTo() { return this; } }),
  latLngBounds: () => ({}),
};
global.hrApi = async (path, opt) => {
  if (opt && opt.method === 'PATCH') { patches.push({ path, body: JSON.parse(opt.body) }); return { success: true }; }
  if (path === '/api/tasks') return { success: true, data: JSON.parse(JSON.stringify(tasksDb)) };
  throw new Error('unexpected ' + path);
};
// /api/tasks trả id GIẢM DẦN (sort('id', -1)) — việc chờ lâu nhất là id nhỏ nhất
tasksDb = [
  { id: 9, trang_thai: 'Chờ Nhận', lat: 10.0, lng: 10.0, dia_chi: 'new job' },
  { id: 7, trang_thai: 'Đã Nhận', lat: 0, lng: 0, dia_chi: 'taken' },
  { id: 4, trang_thai: 'Chờ Nhận', lat: 1.0, lng: 1.0, dia_chi: '1 Old St <b>' },
];
global.currentWorkersData = [
  { ho_ten: 'Far <script>', trang_thai_gps: 'Rảnh', toa_do_lat: 5, toa_do_lng: 5 },
  { ho_ten: 'Near Ann', trang_thai_gps: 'Rảnh', toa_do_lat: 1.01, toa_do_lng: 1.0 },
  { ho_ten: 'Busy Bob', trang_thai_gps: 'Bận', toa_do_lat: 1.0, toa_do_lng: 1.0 },
];
eval(SRC.join('\n') + '\nglobal.goiYThoRanhGanNhat = goiYThoRanhGanNhat; global.assignSuggestedJob = assignSuggestedJob;');
(async () => {
  await goiYThoRanhGanNhat();
  const a = alerts[alerts.length - 1] || {};
  ok('map: gợi ý việc CHỜ LÂU NHẤT (#4), không phải mới nhất (#9)', /"jobid":4/.test(a.msg || ''), a.msg);
  ok('map: chọn thợ đang Rảnh gần nhất (Near Ann), bỏ thợ Bận', /"name":"Near Ann"/.test(a.msg || ''), a.msg);
  ok('map: địa chỉ/tên được escape trước khi chèn HTML', /1 Old St &lt;b&gt;/.test(a.msg || ''), a.msg);
  ok('map: CHƯA giao việc khi mới chỉ gợi ý (không PATCH trạng thái)', patches.filter((p) => p.body.trang_thai).length === 0, JSON.stringify(patches));
  ok('map: hộp gợi ý có nút xác nhận', a.action && typeof a.action.onConfirm === 'function');
  await a.action.onConfirm();
  const p = patches.find((x) => x.body.trang_thai);
  ok('map: bấm Giao việc -> PATCH /api/tasks/4 Đã Nhận cho Near Ann', p && p.path === '/api/tasks/4' && p.body.trang_thai === 'Đã Nhận' && p.body.nguoi_nhan === 'Near Ann', JSON.stringify(p));
  // việc đã bị thợ khác nhận trong lúc chờ xác nhận -> không ghi đè
  patches.length = 0; alerts.length = 0;
  tasksDb = tasksDb.map((x) => x.id === 4 ? Object.assign({}, x, { trang_thai: 'Đã Nhận', nguoi_nhan: 'Someone' }) : x);
  await assignSuggestedJob(4, 'Near Ann');
  ok('map: việc vừa bị nhận -> không PATCH, báo đã đổi trạng thái', patches.length === 0 && /map_dashboard_suggest_job_taken/.test((alerts[0] || {}).msg || ''), JSON.stringify(alerts));
  // không còn việc chờ
  tasksDb = [{ id: 1, trang_thai: 'Hoàn Thành' }]; alerts.length = 0;
  await goiYThoRanhGanNhat();
  ok('map: không có việc chờ -> báo không có việc, không PATCH', /map_dashboard_ai_no_jobs/.test((alerts[0] || {}).msg || '') && patches.length === 0);
  ok('map: không lỗi', toasts.length === 0, toasts.join(' | '));
  console.log(JSON.stringify(out));
})().catch((e) => { out.push({ name: 'map harness crashed', ok: false, note: String(e.stack || e) }); console.log(JSON.stringify(out)); });
'''


def test_map_dashboard():
    s = read('templates/map_dashboard.html')
    for bad in ('kichHoatBotAI', 'kichHoatAIDieuPhoi', 'map_dashboard_slacking_alert', 'LƯỜI BIẾNG', 'SLACKING', 'trừ thi đua',
                'performance deduction', 'QUÉT VI PHẠM', 'SCAN VIOLATIONS', 'Routing AI', 'AI Routing', 'AI Dispatch', 'AI Điều Phối',
                'Auto-Dispatch', 'thuật toán AI', 'AI algorithm', 'fa-brain'):
        check(f'map: đã gỡ "{bad}"', bad not in s)
    check('map: nút đổi tên trung thực (EN)', "map_dashboard_btn_suggest: 'Suggest nearest free technician'" in s)
    check('map: nút đổi tên trung thực (VI)', "map_dashboard_btn_suggest: 'Gợi ý thợ rảnh gần nhất'" in s)
    for k in ('map_dashboard_suggest_found', 'map_dashboard_suggest_assigned', 'map_dashboard_suggest_job_taken', 'map_dashboard_suggest_dismiss'):
        check(f'map: khoá i18n {k} có cả VI và EN', len(re.findall(r'^\s*' + k + r':', s, re.M)) == 2)
    check('map: ghi rõ khoảng cách là đường chim bay', 'đường chim bay' in s and 'straight line' in s)
    scripts = inline_scripts(s)
    for i, code in enumerate(scripts):
        node_check(f'map_dashboard.html script#{i}', code)
    body = '\n'.join(scripts)
    funcs = [js_function(body, n) for n in ('goiYThoRanhGanNhat', 'assignSuggestedJob')]
    if not all(funcs):
        check('map: tìm thấy goiYThoRanhGanNhat + assignSuggestedJob', False)
        return
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(MAP_HARNESS)
    r = subprocess.run(['node', f.name], capture_output=True, text=True, encoding='utf-8', env=dict(os.environ, MAP_FUNCS=json.dumps(funcs)), timeout=60)
    os.unlink(f.name)
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        check('map harness chạy được', False, (r.stderr or r.stdout)[-600:])
        return
    for row in rows:
        check(row['name'], row['ok'], row.get('note', ''))


# ============================================================ 6. chamcong_kythuat / inventory_alert / add_expense / nurturing engine
def test_other_pages():
    s = read('templates/chamcong_kythuat.html')
    check('chamcong_kythuat: không còn nhãn/claim "AI"', re.search(r'\bAI\b', s) is None, (re.search(r'.{0,40}\bAI\b.{0,40}', s) or [''])[0])
    check('chamcong_kythuat: hàm mẫu vật tư đổi tên trung thực', 'function applyMaterialTemplate()' in s and 'autoSuggestMaterials' not in s)
    check('chamcong_kythuat: nhãn chọn mẫu VI + EN', "'-- Mẫu vật tư theo loại việc (tuỳ chọn) --'" in s and "'-- Preset materials by job type (optional) --'" in s)
    for i, code in enumerate(inline_scripts(s)):
        node_check(f'chamcong_kythuat.html script#{i}', code)

    s = read('templates/inventory_alert.html')
    check('inventory_alert: tiêu đề biểu đồ không còn "Demand Forecast"/"Dự báo nhu cầu"', 'Demand Forecast' not in s and 'Dự báo nhu cầu' not in s)
    check('inventory_alert: tiêu đề biểu đồ nói đúng thứ được vẽ (VI + EN)',
          "inventory_alert_chart_heading: 'Tồn kho hiện tại so với ngưỡng cảnh báo'" in s and "inventory_alert_chart_heading: 'Current stock vs warning threshold'" in s)
    check('inventory_alert: nhãn 2 dataset theo ngôn ngữ', "label: t('inventory_alert_chart_stock')" in s and "label: t('inventory_alert_chart_threshold')" in s
          and len(re.findall(r'^\s*inventory_alert_chart_stock:', s, re.M)) == 2)
    for i, code in enumerate(inline_scripts(s)):
        node_check(f'inventory_alert.html script#{i}', code)

    s = read('templates/add_expense.html')
    check('add_expense: không còn claim AI phân tích chi tiêu', re.search(r'\bAI\b', s) is None and 'AI phân tích' not in s and 'the AI can analy' not in s)
    for i, code in enumerate(inline_scripts(s)):
        node_check(f'add_expense.html script#{i}', code)

    src = read('ai_nurturing_engine.py')
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AINurturingEngine')
    names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    check('nurturing: đã xoá get_industry_recommendations (số liệu bịa)', 'get_industry_recommendations' not in names and 'get_industry_recommendations' not in src)
    check('nurturing: không còn câu số bịa', '12 khách hàng VIP' not in src and '25 lịch hẹn' not in src and 'AI phát hiện 24%' not in src)
    check('nurturing: real_recommendations (số liệu thật) vẫn còn', 'real_recommendations' in names)
    import py_compile
    for f in ('ai_nurturing_engine.py', 'app.py'):
        try:
            py_compile.compile(os.path.join(ROOT, f), doraise=True)
            check(f'py_compile {f}', True)
        except py_compile.PyCompileError as e:
            check(f'py_compile {f}', False, str(e)[:300])


# ============================================================ 7. --browser: Chrome thật, mọi request qua page.route
def find_playwright():
    d = ROOT
    for _ in range(6):
        p = os.path.join(d, 'node_modules', 'playwright')
        if os.path.isdir(p):
            return p
        d = os.path.dirname(d)
    return None


def render(tpl, **ctx):
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(loader=FileSystemLoader(os.path.join(ROOT, 'templates')), autoescape=select_autoescape(['html']))
    url_for = lambda endpoint, **kw: '/static/' + kw['filename'] if endpoint == 'static' else '/' + endpoint
    return env.get_template(tpl).render(url_for=url_for, asset_v=lambda p: 'test', session={}, **ctx)


WIDGET_PAGE = '''<!DOCTYPE html><html lang="%(lang)s"><head><meta charset="utf-8"><title>t</title></head><body>
<h1>page</h1><script>%(globals)s</script><script src="/static/js/cskh_widget.js"></script></body></html>'''

NODE_BROWSER = r'''
const { chromium } = require(process.env.PW_PATH);
const fs = require('fs'), path = require('path');
const STATIC = process.env.STATIC_DIR, PAGES = JSON.parse(fs.readFileSync(process.env.PAGES_FILE, 'utf8'));
const BASE = 'https://p0.test';
const out = []; const ok = (name, cond, note) => out.push({ name, ok: !!cond, note: note || '' });
const S = { cskh: [], gen: [], portalPosts: [], other: [] };
const PORTAL_MSGS = [
  { sender_type: 'customer', content: 'Hello', created_at: '2026-10-26T01:00:00Z' },
  { sender_type: 'staff', content: 'Hi! How can we help?', created_at: '2026-10-26T01:01:00Z' },
  { sender_type: 'ai', content: 'I can book that for you.', created_at: '2026-10-26T01:02:00Z' },
  { sender_type: 'staff', content: '[IMG]https://x.test/a.png" onerror="window.__xss=1', created_at: '2026-10-26T01:03:00Z' },
  { sender_type: 'customer', content: '[IMG]/api/public/storage/file/abc123', created_at: '2026-10-26T01:04:00Z' },
];
(async () => {
  const browser = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
  const run = async (fn, opts) => {
    const ctx = await browser.newContext(Object.assign({ viewport: { width: 390, height: 844 } }, opts || {}));
    const page = await ctx.newPage();
    const errs = []; page.on('pageerror', (e) => errs.push(e.message));
    page.on('dialog', (d) => d.dismiss());
    await ctx.route('**/*', async (route) => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname, m = req.method();
      if (url.host !== 'p0.test') return route.abort();          // không ra Internet (font, Font Awesome...)
      const json = (o, st) => route.fulfill({ status: st || 200, contentType: 'application/json', body: JSON.stringify(o) });
      if (PAGES[p]) return route.fulfill({ status: 200, contentType: 'text/html', body: PAGES[p] });
      if (p.startsWith('/static/')) { const f = path.join(STATIC, p.slice(8)); return fs.existsSync(f) ? route.fulfill({ path: f }) : route.fulfill({ status: 404, body: '' }); }
      if (p.startsWith('/api/cskh/')) { S.cskh.push(p + ' ' + (req.postData() || '')); return json({ success: true }); }
      if (p === '/api/ai/studio/generate') { S.gen.push(req.postDataJSON()); return json({ choices: [{ message: { content: 'Sure — what time works for you?' } }] }); }
      if (p === '/api/public/pos/products') return json({ success: true, data: [{ id: 1, name: 'Iced coffee', price: 4.5, category: 'Coffee', stock: 9 }] });
      if (p === '/api/portal/messages' && m === 'GET') {
        if (url.searchParams.get('customer_id') !== 'biz1:0412345678') return json({ success: false, message: 'not found' }, 404);
        return json({ success: true, data: PORTAL_MSGS, shop_name: 'Lotus Nails' });
      }
      if (p === '/api/portal/messages' && m === 'POST') { S.portalPosts.push(req.postDataJSON()); return json({ success: true }); }
      if (p === '/api/portal/stream') return route.fulfill({ status: 204, body: '' });
      if (p.startsWith('/api/public/storage/file/')) return route.fulfill({ path: path.join(STATIC, 'cho1.jpg'), contentType: 'image/jpeg' });
      S.other.push(m + ' ' + p); return json({ success: false }, 404);
    });
    try { await fn(page, ctx); } finally { ok('không lỗi JS (' + (opts && opts.label || 'trang') + ')', errs.length === 0, errs.join(' | ')); await ctx.close(); }
  };
  const chatOnce = async (page, phone, msgs) => {
    await page.click('#mascot-toggle-btn');
    await page.fill('#chatPhone', phone);
    for (const msg of msgs) {
      const n = S.gen.length;
      await page.waitForFunction(() => !document.getElementById('chatMsg').disabled);
      await page.fill('#chatMsg', msg);
      await page.click('#chatSendBtn');
      for (let i = 0; i < 50 && S.gen.length === n; i++) await page.waitForTimeout(100);
      await page.waitForTimeout(1000);   // finishSubmit chạy sau ~800 ms
    }
  };

  // ---- A. trang đặt lịch của tiệm (customer_booking): không lead BitPaw, chat_token 32 hex ổn định qua tải lại
  S.cskh = []; S.gen = [];
  await run(async (page) => {
    await page.goto(BASE + '/booking', { waitUntil: 'load' });
    await chatOnce(page, '0412345678', ['Can I book a gel manicure tomorrow at 3pm?', 'Yes please']);
    const toks = S.gen.map((b) => b.chat_token);
    ok('A. đặt lịch: không request nào tới /api/cskh/request', S.cskh.filter((x) => x.startsWith('/api/cskh/request')).length === 0, S.cskh.join(' | '));
    ok('A. đặt lịch: 2 lượt chat đều gửi chat_token 32 hex giống nhau', toks.length === 2 && toks.every((x) => /^[0-9a-f]{32}$/.test(x || '')) && toks[0] === toks[1], JSON.stringify(toks));
    const stored = await page.evaluate(() => localStorage.getItem('bp_chat_token'));
    ok('A. đặt lịch: token lưu ở localStorage bp_chat_token', stored === toks[0], stored);
    await page.reload({ waitUntil: 'load' });
    S.gen = [];
    await chatOnce(page, '0412345678', ['Hi again']);
    ok('A. đặt lịch: tải lại trang -> cùng token', S.gen.length === 1 && S.gen[0].chat_token === toks[0], JSON.stringify(S.gen.map((b) => b.chat_token)));
    const txt = await page.textContent('#chat-messages-container');
    ok('A. đặt lịch: không hứa "chuyên viên BitPaw sẽ liên hệ"', !/BitPaw specialist|chuyên viên BitPaw/.test(txt), txt.slice(0, 200));
  }, { label: 'A booking' });

  // ---- A2. localStorage bị chặn: vẫn chat được, token trong bộ nhớ, ổn định trong phiên
  S.cskh = []; S.gen = [];
  await run(async (page, ctx) => {
    await ctx.addInitScript(() => {
      const thrower = () => { throw new DOMException('blocked', 'SecurityError'); };
      Object.defineProperty(window, 'localStorage', { get: thrower, configurable: true });
    });
    await page.goto(BASE + '/booking', { waitUntil: 'load' });
    await chatOnce(page, '0412345678', ['Book me in', 'Thanks']);
    const toks = S.gen.map((b) => b.chat_token);
    ok('A2. localStorage bị chặn: vẫn gửi chat_token 32 hex, giống nhau trong phiên', toks.length === 2 && /^[0-9a-f]{32}$/.test(toks[0] || '') && toks[0] === toks[1], JSON.stringify(toks));
  }, { label: 'A2 storage blocked' });

  // ---- B. trang của tiệm (có BITPAW_BUSINESS_ID, không customer_booking): không lead BitPaw, không chat_token
  S.cskh = []; S.gen = [];
  await run(async (page) => {
    await page.goto(BASE + '/tenant_page', { waitUntil: 'load' });
    await chatOnce(page, '0412345678', ['hello']);
    ok('B. trang tiệm: không request nào tới /api/cskh/request', S.cskh.filter((x) => x.startsWith('/api/cskh/request')).length === 0, S.cskh.join(' | '));
    ok('B. trang tiệm: không gửi chat_token ngoài ngữ cảnh đặt lịch', S.gen.length === 1 && !('chat_token' in S.gen[0]), JSON.stringify(S.gen));
    const txt = await page.textContent('#chat-messages-container');
    ok('B. trang tiệm: không hứa "BitPaw specialist will reach out" khi không ghi lead', !/BitPaw specialist/.test(txt), txt.slice(0, 300));
  }, { label: 'B tenant' });

  // ---- C. landing BitPaw (không business_id): lead ghi đúng 1 lần, không chat_token
  S.cskh = []; S.gen = [];
  await run(async (page) => {
    await page.goto(BASE + '/landing_nail', { waitUntil: 'load' });
    await chatOnce(page, '0412345678', ['How much is it?', 'ok']);
    const leads = S.cskh.filter((x) => x.startsWith('/api/cskh/request'));
    ok('C. landing BitPaw: ghi lead /api/cskh/request đúng 1 lần', leads.length === 1, S.cskh.join(' | '));
    ok('C. landing BitPaw: không gửi chat_token', S.gen.length === 2 && S.gen.every((b) => !('chat_token' in b)));
  }, { label: 'C landing' });

  // ---- D. table_order.html (QR bàn): không bong bóng BitPaw, không request /api/cskh/*
  S.cskh = [];
  await run(async (page) => {
    await page.goto(BASE + '/table_order', { waitUntil: 'load' });
    await page.waitForTimeout(1500);
    const hasWidget = await page.evaluate(() => !!(document.getElementById('bitpawCskhFloating') || document.getElementById('chatWidget') || document.getElementById('mascot-toggle-btn')));
    ok('D. QR bàn: không có bong bóng chat bán hàng BitPaw', !hasWidget);
    ok('D. QR bàn: 0 request tới /api/cskh/*', S.cskh.length === 0, S.cskh.join(' | '));
    ok('D. QR bàn: menu vẫn tải', /Iced coffee/.test(await page.textContent('body')));
  }, { label: 'D table_order' });

  // ---- E. portal.html: hội thoại thật với nhân viên tiệm, không AI giả
  S.portalPosts = [];
  await run(async (page) => {
    await page.goto(BASE + '/portal?id=biz1:0412345678', { waitUntil: 'load' });
    await page.waitForSelector('#chatBox .chat-ai');
    await page.waitForTimeout(400);
    const box = await page.textContent('#chatBox');
    ok('E. portal: tiêu đề = tên tiệm', (await page.title()) === 'Lotus Nails' && (await page.textContent('#portalTitle')) === 'Lotus Nails');
    ok('E. portal: tin nhân viên ghi tên tiệm, tin AI thật ghi rõ là AI', /Lotus Nails/.test(box) && /Booking assistant \(AI\)/.test(box), box.slice(0, 300));
    ok('E. portal: link ảnh độc hại không chạy script', await page.evaluate(() => window.__xss === undefined));
    ok('E. portal: ảnh tải lên (đường dẫn nội bộ /api/public/storage/file) hiện thành <img>',
       await page.evaluate(() => !!document.querySelector('#chatBox img[src="/api/public/storage/file/abc123"]')));
    const body = await page.textContent('body');
    ok('E. portal: không còn "Online 24/7" / "BitPaw Assistant" / "Fully Secure"', !/Online 24\/7|BitPaw Assistant|Fully Secure/.test(body));
    const before = await page.$$eval('#chatBox .chat-ai', (els) => els.length);
    await page.fill('#messageInput', 'Parking?');
    await page.press('#messageInput', 'Enter');
    await page.waitForTimeout(3500);   // AI giả cũ trả lời sau 1.5-2.5 s, gõ sai sau 1.5 s
    const after = await page.$$eval('#chatBox .chat-ai', (els) => els.length);
    ok('E. portal: gửi tin -> đúng 1 POST, sender_type customer, nội dung nguyên văn', S.portalPosts.length === 1 && S.portalPosts[0].sender_type === 'customer' && S.portalPosts[0].content === 'Parking?', JSON.stringify(S.portalPosts));
    ok('E. portal: không có câu trả lời tự động nào hiện ra', after === before, `${before} -> ${after}`);
    ok('E. portal: tin của khách hiện ngay trong khung chat', /Parking\?/.test(await page.textContent('#chatBox')));
    ok('E. portal: báo trung thực "đã gửi tới tiệm"', /Sent to the shop/.test(await page.textContent('#chatBox')));
    await page.click('button[onclick="sendQuickMessage(\'booking\')"]');
    await page.waitForTimeout(800);
    ok('E. portal: nút gợi ý gửi đúng ngôn ngữ trang (EN)', S.portalPosts.length === 2 && S.portalPosts[1].content === "I'd like to book an appointment", JSON.stringify(S.portalPosts[1]));
    ok('E. portal: không POST sender_type nào khác customer', S.portalPosts.every((b) => b.sender_type === 'customer'));
  }, { label: 'E portal' });

  // ---- F. portal: id trong URL không chạy script (trước đây chèn innerHTML)
  await run(async (page) => {
    await page.goto(BASE + '/portal?id=' + encodeURIComponent('<img src=x onerror="window.__xss2=1">'), { waitUntil: 'load' });
    await page.waitForTimeout(800);
    ok('F. portal: ?id=<img onerror> không chạy script', await page.evaluate(() => window.__xss2 === undefined));
    ok('F. portal: badge hiện id dạng chữ', /<img src=x/.test(await page.textContent('#customerIdBadge')));
  }, { label: 'F portal xss' });

  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { out.push({ name: 'browser test crashed', ok: false, note: String(e && e.stack || e).slice(0, 800) }); console.log(JSON.stringify(out)); });
'''


def test_browser():
    pw = find_playwright()
    if not pw:
        check('Playwright có sẵn (node_modules/playwright ở repo chính)', False, 'npm i -D playwright')
        return
    pages = {
        '/booking': WIDGET_PAGE % {'lang': 'en', 'globals': "window.BITPAW_BUSINESS_ID='biz1';window.BITPAW_BUSINESS_NAME='Lotus Nails';window.BITPAW_CHAT_CONTEXT='customer_booking';"},
        '/tenant_page': WIDGET_PAGE % {'lang': 'en', 'globals': "window.BITPAW_BUSINESS_ID='biz1';"},
        '/landing_nail': WIDGET_PAGE % {'lang': 'en', 'globals': ''},
        '/table_order': render('table_order.html', table=SimpleNamespace(name='Table 5', id=5, qr_token='tok5', business_id='biz1'),
                               default_lang='en', tenant_currency='USD', tenant_country='US', shop_name='Pho Corner'),
        '/portal': render('portal.html', default_lang='en'),
    }
    tmp = tempfile.mkdtemp(prefix='p0_browser_')
    pages_file = os.path.join(tmp, 'pages.json')
    js_file = os.path.join(tmp, 'browser_test.js')
    with open(pages_file, 'w', encoding='utf-8') as f:
        json.dump(pages, f)
    with open(js_file, 'w', encoding='utf-8') as f:
        f.write(NODE_BROWSER)
    env = dict(os.environ, PW_PATH=pw, PAGES_FILE=pages_file, STATIC_DIR=os.path.join(ROOT, 'static'))
    r = subprocess.run(['node', js_file], capture_output=True, text=True, encoding='utf-8', env=env, timeout=300)
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        check('browser tests chạy được', False, (r.stderr or r.stdout)[-800:])
        return
    for row in rows:
        check('browser: ' + row['name'], row['ok'], row.get('note', ''))


def main():
    test_table_order()
    test_widget_static()
    test_portal_static()
    test_portal_route()
    test_map_dashboard()
    test_other_pages()
    if '--browser' in sys.argv:
        test_browser()
    print(f'\n{"OK" if not FAILS else "FAILED"} — {len(FAILS)} lỗi')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
