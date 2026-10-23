// map_latency_probe.mjs — Bản đồ nhân viên: thợ đổi vị trí/trạng thái trên app -> chấm trên /map_dashboard của chủ dời theo bao nhiêu ms
// (luồng SSE /api/stream/hr_employees, chỉ dời đúng 1 chấm). Ghi audit-results/ai_sim/map_latency_<tag>.json.
//   node scripts/map_latency_probe.mjs [tag]   (CHỈ local; tự dọn nhân viên thử)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';
import fs from 'fs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const TAG = process.argv[2] || 'run';
const EMAIL = process.env.MAP_EMAIL || 'demo.technical.393328@bitpawdemo.com', PW = process.env.MAP_PW || 'DemoBitPaw2026!';
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();

const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1366, height: 900 } });
const owner = await ctx.newPage(); const errs = []; owner.on('pageerror', (e) => errs.push(e.message));
await owner.goto(BASE + '/login');
await owner.fill('#loginEmail', EMAIL); await owner.fill('#loginPassword', PW);
await Promise.all([owner.waitForLoadState('networkidle').catch(() => {}), owner.click('#btnLogin')]);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const MA = 'MAPQ' + String(Date.now()).slice(-4);
const api = (page, url, method = 'GET', body) => page.evaluate(async ([u, m, bd]) => { const r = await fetch(u, { method: m, headers: { 'Content-Type': 'application/json' }, body: bd ? JSON.stringify(bd) : undefined }); let j = {}; try { j = await r.json(); } catch (e) {} return { status: r.status, ...j }; }, [url, method, body]);
await api(owner, '/api/hr/employees', 'POST', { ma_nv: MA, ho_ten: 'Map Probe Tech', linh_vuc: 'Kỹ thuật' });
await api(owner, `/api/hr/employees/${MA}`, 'PATCH', { toa_do_lat: -33.8688, toa_do_lng: 151.2093, trang_thai_gps: 'Rảnh' });

await owner.goto(BASE + '/map_dashboard', { waitUntil: 'networkidle' });
await owner.waitForFunction((m) => typeof markers !== 'undefined' && markers[m], MA, { timeout: 15000 }).catch(() => {});
// "điện thoại thợ": 1 trang khác cùng phiên tiệm gửi vị trí như app nhân viên
const phone = await ctx.newPage();
await phone.goto(BASE + '/app_nhanvien', { waitUntil: 'domcontentloaded' });
const lat = [];
let reqs = 0; owner.on('request', (r) => { if (r.url().includes('/api/hr/employees') && r.method() === 'GET') reqs++; });
for (let i = 1; i <= 12; i++) {
  const la = -33.8688 + i * 0.0007, lo = 151.2093 + i * 0.0005;
  const t0 = Date.now();
  await api(phone, `/api/hr/employees/${MA}`, 'PATCH', { toa_do_lat: la, toa_do_lng: lo, trang_thai_gps: i % 2 ? 'Bận' : 'Rảnh', nhiem_vu_hien_tai: i % 2 ? `Job #${i}` : '' });
  const ok = await owner.waitForFunction(([m, a]) => markers[m] && Math.abs(markers[m].getLatLng().lat - a) < 1e-6, [MA, la], { timeout: 10000, polling: 25 }).then(() => true).catch(() => false);
  lat.push(ok ? Date.now() - t0 : null);
  await owner.waitForTimeout(400);
}
const ok = lat.filter((x) => x != null).sort((a, z) => a - z);
const res = { tag: TAG, latency_ms: lat, p50: ok[Math.floor(ok.length / 2)], p90: ok[Math.floor(ok.length * 0.9)], max: ok[ok.length - 1],
              missed: lat.filter((x) => x == null).length, full_list_reloads: reqs, js_errors: errs.length };
fs.writeFileSync(`audit-results/ai_sim/map_latency_${TAG}.json`, JSON.stringify(res, null, 2));
console.log(JSON.stringify(res, null, 2));
py(`
from mongo_client import db
db.employees.delete_many({'business_id': '${bid}', 'ma_nv': '${MA}'}); db.staff.delete_many({'business_id': '${bid}', 'ma_nv': '${MA}'})
print('cleaned')`);
await b.close();
process.exit(res.missed || errs.length ? 1 : 0);
