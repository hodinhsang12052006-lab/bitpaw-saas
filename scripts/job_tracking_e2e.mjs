// job_tracking_e2e.mjs — Kỹ thuật: "thợ đang đến" (SMS + link theo dõi), tới nơi ẩn vị trí, vị trí cũ không hiện, xong việc.
//   Server local chạy với TWILIO_API_BASE=http://127.0.0.1:5099 (scratchpad/restart_msg.sh).  node scripts/job_tracking_e2e.mjs
import { chromium, devices } from 'playwright';
import { execFileSync } from 'child_process';
import http from 'http';
import crypto from 'crypto';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const SID = 'AC' + 'e2e'.padEnd(32, '0'), TOKEN = 'tok_' + crypto.randomBytes(8).toString('hex');
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const sent = [];
const stub = http.createServer((req, res) => {
  let body = ''; req.on('data', (c) => (body += c)); req.on('end', () => {
    sent.push(Object.fromEntries(new URLSearchParams(body)));
    res.writeHead(201, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ sid: 'SM' + crypto.randomBytes(8).toString('hex'), status: 'queued' }));
  });
}).listen(5099);

const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1280, height: 860 } });
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
await p.goto(BASE + '/login');
await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const B = JSON.stringify(bid);
const api = (url, method = 'GET', body) => p.evaluate(async ([u, m, bd]) => { const r = await fetch(u, { method: m, headers: { 'Content-Type': 'application/json' }, body: bd ? JSON.stringify(bd) : undefined }); let j = {}; try { j = await r.json(); } catch (e) {} return { status: r.status, ...j }; }, [url, method, body]);
const backup = py(`
import json
from mongo_client import db
print(json.dumps({'s': db.messaging_settings.find_one({'business_id': ${B}}, {'_id': 0}), 't': db.nurture_channel_tokens.find_one({'business_id': ${B}, 'platform': 'twilio'}, {'_id': 0})}, default=str))`);
await api('/api/messaging/settings', 'POST', { sms_enabled: false });

const CODE = 'QT' + String(Date.now()).slice(-5), NAME = 'Sam Tracker QA';
await api('/api/hr/employees', 'POST', { ma_nv: CODE, ho_ten: NAME, linh_vuc: 'Kỹ Thuật' });
const DEST = [-33.8688, 151.2093];
const setTech = (lat, lng, minsAgo = 0) => py(`
from datetime import datetime, timedelta
from mongo_client import db
db.employees.update_one({'business_id': ${B}, 'ma_nv': '${CODE}'}, {'$set': {'toa_do_lat': ${lat}, 'toa_do_lng': ${lng}, 'trang_thai_gps': 'Bận', 'gps_at': (datetime.now() - timedelta(minutes=${minsAgo})).isoformat()}})
print('ok')`);
let r = await api('/api/tasks', 'POST', { ten_khach: 'Olivia Brown', sdt: '0400 222 333', dia_chi: '1 Martin Place, Sydney NSW', noi_dung: 'Aircon not cooling', lat: DEST[0], lng: DEST[1], trang_thai: 'Chờ Nhận', nguoi_nhan: '' });
const TID = r.data.id;
r = await api(`/api/tasks/${TID}/on_my_way`, 'POST', {});
rec('Chưa nhận việc -> chưa gửi "đang đến" được (409)', r.status === 409);
await api(`/api/tasks/${TID}`, 'PATCH', { trang_thai: 'Đã Nhận', nguoi_nhan: NAME });
setTech(-33.8960, 151.2093);   // cách ~3 km, vị trí mới
r = await api(`/api/tasks/${TID}/on_my_way`, 'POST', {});
const url = r.url || '';
rec('Chưa nối Twilio: trả SĐT chuẩn + tin soạn sẵn để thợ tự nhắn', r.success && r.sent === false && r.phone === '+61400222333' && /Sam is on the way \(about \d+ min\)/.test(r.text) && /\/track\/.+\/[0-9a-f]{20}$/.test(url), r.text);
rec('Thời gian dự kiến hợp lý (~3 km -> 5–10 phút)', r.eta_min >= 5 && r.eta_min <= 10, `${r.eta_min} min`);

// trang khách trên iPhone
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const cctx = await b.newContext(iphone); const c = await cctx.newPage(); const cerr = []; c.on('pageerror', (e) => cerr.push(e.message));
await c.goto(url, { waitUntil: 'networkidle' }); await c.waitForTimeout(800);
const title = await c.textContent('#title');
const mapShown = await c.locator('#map').isVisible();
rec('Khách mở link: "Sam is on the way", có phút dự kiến + bản đồ', /Sam is on the way/.test(title) && await c.locator('#etaBox').isVisible() && mapShown, title);
rec('Trang khách không lộ họ đầy đủ của thợ / SĐT khách', !(await c.content()).includes('Tracker QA') && !(await c.content()).includes('222 333'));
const ov = await c.evaluate(() => document.documentElement.scrollWidth - innerWidth);
rec('Trang khách vừa màn hình điện thoại', ov <= 1);
await c.screenshot({ path: 'audit-results/screenshots/job_tracking_customer.png' }).catch(() => {});
const pub = (u) => c.evaluate(async (x) => { const r = await fetch(x); return { status: r.status, ...(await r.json().catch(() => ({}))) }; }, u);
const apiUrl = url.replace(BASE + '/track/', '/api/public/track/');
r = await pub(apiUrl.replace(/[0-9a-f]{20}$/, '0'.repeat(20)));
rec('Link giả -> 404', r.status === 404);
setTech(-33.8689, 151.2094);
r = await pub(apiUrl);
rec('Thợ tới nơi (<150 m) -> "arrived", không còn hiện vị trí', r.state === 'arrived' && r.tech_pos === null);
setTech(-33.95, 151.2093, 25);
r = await pub(apiUrl);
rec('Vị trí cũ hơn 15 phút -> không hiện vị trí', r.state === 'on_way' && r.tech_pos === null);

// có Twilio -> tự gửi SMS
r = await api('/api/messaging/settings', 'POST', { sms_enabled: true, twilio_account_sid: SID, twilio_auth_token: TOKEN, twilio_from: '+61 2 5550 1234', country: 'AU' });
setTech(-33.8960, 151.2093);
r = await api(`/api/tasks/${TID}/on_my_way`, 'POST', {});
await new Promise((x) => setTimeout(x, 800));
const sms = sent.find((m) => m.To === '+61400222333');
rec('Đã nối Twilio: SMS tự gửi tới khách kèm link theo dõi', r.sent === true && sms && /on the way/.test(sms.Body) && sms.Body.includes('/track/'), sms && sms.Body);

// app thợ: nút ON MY WAY
{
  const tctx = await b.newContext({ ...iphone, storageState: await ctx.storageState(), permissions: ['geolocation'], geolocation: { latitude: -33.896, longitude: 151.2093 } });
  const t = await tctx.newPage();
  await t.goto(BASE + '/app_nhanvien', { waitUntil: 'networkidle' });
  await t.evaluate(([code, name]) => { localStorage.setItem('bp_emp_code', code); localStorage.setItem('bp_emp_name', name); localStorage.setItem('bp_emp_linhvuc', 'Kỹ Thuật'); localStorage.setItem('bp_da_diem_danh', new Date().toDateString()); }, [CODE, NAME]);
  await t.reload({ waitUntil: 'networkidle' }); await t.waitForTimeout(1500);
  await t.evaluate(() => typeof switchAppTab === 'function' && switchAppTab('jobs')); await t.waitForTimeout(1500);
  const btn = t.locator(`[data-task-id="${TID}"] [data-action="onway"]`);
  const has = await btn.count();
  rec('App thợ: việc của tôi có nút "ON MY WAY"', has === 1, has ? (await btn.textContent()).trim() : '');
  if (has) {
    const before = sent.length;
    await btn.click(); await t.waitForTimeout(2000);
    rec('Bấm ON MY WAY trong app -> khách nhận SMS', sent.length > before);
  }
  await tctx.close();
}

await api(`/api/tasks/${TID}`, 'PATCH', { trang_thai: 'Hoàn Thành' });
r = await pub(apiUrl);
rec('Xong việc -> trang khách báo hoàn thành, không vị trí', r.state === 'done' && r.tech_pos === null);
rec('Không lỗi JS', errs.length === 0 && cerr.length === 0, [...errs, ...cerr].slice(0, 2).join(' | '));

// dọn + khôi phục
await cctx.close();
py(`
import json
from mongo_client import db
bk = json.loads(${JSON.stringify(backup)})
db.tasks.delete_many({'business_id': ${B}, 'id': ${TID}})
db.employees.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'})
db.staff.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'})
db.outbound_messages.delete_many({'business_id': ${B}, 'kind': 'on_my_way'})
if bk['s']: db.messaging_settings.replace_one({'business_id': ${B}}, bk['s'], upsert=True)
else: db.messaging_settings.delete_many({'business_id': ${B}})
if bk['t']: db.nurture_channel_tokens.replace_one({'business_id': ${B}, 'platform': 'twilio'}, bk['t'], upsert=True)
else: db.nurture_channel_tokens.delete_many({'business_id': ${B}, 'platform': 'twilio'})
print('cleaned')`);
stub.close(); await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
