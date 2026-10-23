// geofence_checkin_e2e.mjs — "Chỉ chấm công tại tiệm": chủ tiệm đặt vị trí + bán kính, check-in ngoài bán kính bị chặn,
// trong bán kính (kể cả sai số GPS) được nhận, bản ghi offline chỉ bị đánh dấu.   node scripts/geofence_checkin_e2e.mjs (CHỈ local)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const SHOP = { latitude: -33.8688, longitude: 151.2093 };   // Sydney CBD
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();

const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1366, height: 900 }, permissions: ['geolocation'], geolocation: SHOP });
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
await p.goto(BASE + '/login');
await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const B = JSON.stringify(bid);
const api = (url, method = 'GET', body) => p.evaluate(async ([u, m, bd]) => { const r = await fetch(u, { method: m, headers: { 'Content-Type': 'application/json' }, body: bd ? JSON.stringify(bd) : undefined }); let j = {}; try { j = await r.json(); } catch (e) {} return { status: r.status, ...j }; }, [url, method, body]);
const before = await api('/api/business/geofence');
const CODE = 'QG' + String(Date.now()).slice(-5);
await api('/api/hr/employees', 'POST', { ma_nv: CODE, ho_ten: 'QA Geofence', linh_vuc: 'Nails' });
const day = (n) => { const d = new Date(Date.now() + n * 86400000); return d.toLocaleDateString('en-GB'); };

// chủ tiệm bật từ trang Nhân sự (đứng tại tiệm, bán kính 150 m)
await api('/api/business/geofence', 'POST', { latitude: null, longitude: null });
await p.goto(BASE + '/nhanvien', { waitUntil: 'networkidle' }); await p.waitForTimeout(500);
rec('Nút "Chỉ chấm công tại tiệm" hiện trạng thái TẮT', /OFF|TẮT/.test(await p.textContent('#geoToggleLabel')));
p.once('dialog', (d) => d.accept('150'));
await Promise.all([p.waitForResponse((r) => r.url().endsWith('/api/business/geofence') && r.request().method() === 'POST'), p.click('#geoToggleBtn')]);
await p.waitForTimeout(800);
const lbl = await p.textContent('#geoToggleLabel');
const g = await api('/api/business/geofence');
rec('Bật bằng vị trí máy hiện tại + bán kính 150 m', /ON|BẬT/.test(lbl) && /150/.test(lbl) && Math.abs(g.latitude - SHOP.latitude) < 1e-4 && g.radius_m === 150, lbl);

// check-in qua API của app nhân viên
let r = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: day(0), gio_den: '09:00', trang_thai: 'Có mặt', toa_do: '-33.8800,151.2093', gps_accuracy: 20 });
rec('Ngoài bán kính (~1,2 km) -> chặn, báo khoảng cách', r.status === 403 && r.geofence === true && /m from the shop/.test(r.error || ''), r.error);
r = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: day(0), gio_den: '09:00', trang_thai: 'Có mặt', toa_do: 'null,null' });
rec('Không có GPS khi tiệm bật giới hạn -> chặn', r.status === 403 && /Location is required/.test(r.error || ''));
r = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: day(0), gio_den: '09:00', trang_thai: 'Có mặt', toa_do: '-33.8702,151.2093', gps_accuracy: 40 });
rec('Cách 156 m nhưng sai số GPS 40 m -> vẫn nhận (không chặn oan)', r.success && r.data.geo_distance_m >= 150 && r.data.geo_radius_m === 150, JSON.stringify({ d: r.data && r.data.geo_distance_m }));
r = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: day(-1), gio_den: '09:00', trang_thai: 'Có mặt', toa_do: '-33.9000,151.2093', offline_sync: true });
rec('Bản ghi offline đồng bộ sau, ngoài bán kính -> nhận nhưng đánh dấu "outside"', r.success && r.data.geo_flag === 'outside');
r = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: day(-2), gio_den: '09:00', trang_thai: 'Có mặt', note: 'manual' });
rec('Chủ tiệm nhập công tay (không có toạ độ) không bị ảnh hưởng', r.success);
r = await api('/api/business/geofence', 'POST', { latitude: 200, longitude: 10 });
rec('Toạ độ sai -> từ chối', r.status === 400);

// app nhân viên: đứng xa tiệm -> thấy thông báo rõ ràng
{
  const far = await b.newContext({ viewport: { width: 420, height: 860 }, permissions: ['geolocation', 'camera'], geolocation: { latitude: -33.95, longitude: 151.2093 }, storageState: await ctx.storageState() });
  const m = await far.newPage();
  await m.goto(BASE + '/app_nhanvien', { waitUntil: 'networkidle' });
  const out = await m.evaluate(async (code) => {
      const r = await fetch('/api/hr/chamcong', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ma_nv: code, ngay_cham: new Date(Date.now() + 3 * 86400000).toLocaleDateString('en-GB'), gio_den: '09:00', trang_thai: 'Có mặt', toa_do: '-33.95,151.2093', gps_accuracy: 10 }) });
      return { status: r.status, ...(await r.json()) };
  }, CODE);
  rec('Từ trang app nhân viên (cách ~9 km) -> 403 với lời nhắn dễ hiểu', out.status === 403 && /Clock-in is only allowed within 150 m/.test(out.error), out.error);
  await far.close();
}

// tắt lại
p.once('dialog', (d) => d.accept());
await Promise.all([p.waitForResponse((r) => r.url().endsWith('/api/business/geofence') && r.request().method() === 'POST'), p.click('#geoToggleBtn')]);
await p.waitForTimeout(600);
rec('Tắt giới hạn -> chấm công ở đâu cũng được', /OFF|TẮT/.test(await p.textContent('#geoToggleLabel')) && (await api('/api/business/geofence')).latitude == null);
rec('Không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

// dọn + khôi phục
if (before.latitude != null) await api('/api/business/geofence', 'POST', { latitude: before.latitude, longitude: before.longitude, radius_m: before.radius_m });
py(`
from mongo_client import db
db.chamcong.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'})
db.employees.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'})
db.staff.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'})
print('cleaned')`);
await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
