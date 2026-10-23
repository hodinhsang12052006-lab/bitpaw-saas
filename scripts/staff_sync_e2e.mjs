// 2 danh sách nhân viên đã gộp: thêm ở "Staff Management" (/staff) -> có hồ sơ nhân sự + MÃ ĐĂNG NHẬP app (NV0001…),
// đăng nhập app nhân viên được, có trong bảng lương; thêm ở HR (/nhanvien) -> có dòng /staff liên kết. 9 ngành, dọn sau mỗi ngành.
//   DEVICE=desktop|mobile node scripts/staff_sync_e2e.mjs     (CHỈ server local)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';
import { ownerContextOptions, DEVICE } from './lib/device.mjs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const T = {
  nail: ['demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!', 'Nails'], fnb: ['demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!', 'F&B'],
  spa: ['demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!', 'Spa & Beauty'], retail: ['demo.retail.596348@bitpawdemo.com', 'DemoBitPaw2026!', 'Retail'],
  karaoke: ['demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!', 'Karaoke'], hotel: ['demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!', 'Khách Sạn'],
  production: ['demo.production.393328@bitpawdemo.com', 'DemoBitPaw2026!', 'Sản Xuất'], technical: ['demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!', 'Kỹ Thuật'],
  office: ['demo.office.784966@bitpawdemo.com', 'DemoBitPaw2026!', 'Văn Phòng'],
};
const py = (code) => JSON.parse(execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop());
const results = [];
const rec = (ind, name, ok, note = '') => { results.push({ ok }); console.log(`${ok ? '✅' : '❌'} [${DEVICE}][${ind}] ${name}${note ? ' — ' + note : ''}`); };
const browser = await chromium.launch({ channel: 'chrome', headless: true });
for (const [ind, [email, pw, dept]] of Object.entries(T)) {
  const name = `QA Sync ${ind} ${Date.now() % 100000}`;
  const ctx = await browser.newContext(ownerContextOptions());
  const page = await ctx.newPage();
  let code = null;
  try {
    await page.goto(BASE + '/login');
    await page.fill('#loginEmail', email); await page.fill('#loginPassword', pw);
    await Promise.all([page.waitForLoadState('networkidle').catch(() => {}), page.click('#btnLogin')]);
    await page.goto(BASE + '/staff', { waitUntil: 'networkidle' });
    await page.click('#addStaffBtn');
    await page.fill('#staffName', name); await page.fill('#staffPhone', '0400' + String(Date.now()).slice(-6));
    const [resp] = await Promise.all([page.waitForResponse((r) => r.url().endsWith('/add_staff')), page.click('#saveStaffBtn')]);
    code = (await resp.json()).ma_nv;
    await page.waitForTimeout(600);
    const toast = await page.evaluate(() => document.getElementById('toast')?.innerText || '');
    rec(ind, 'Thêm ở Staff Management -> báo mã đăng nhập app', !!code && toast.includes(code), toast.slice(0, 90));
    const st = py(`
import json
from mongo_client import db
bid = db.users.find_one({'email': '${email}'})['business_id']
e = db.employees.find_one({'business_id': bid, 'ma_nv': '${code}'}, {'_id': 0, 'linh_vuc': 1, 'staff_id': 1, 'ho_ten': 1})
s = db.staff.find_one({'business_id': bid, 'ma_nv': '${code}'}, {'_id': 0, 'id': 1})
print(json.dumps({'e': e, 's': s}))`);
    rec(ind, 'Có hồ sơ nhân sự đúng phòng ban + liên kết 2 chiều', st.e && st.e.linh_vuc === dept && st.s && st.e.staff_id === st.s.id, st.e ? `${st.e.linh_vuc}` : 'không có');
    const app = await ctx.newPage();
    await app.goto(BASE + '/app_nhanvien', { waitUntil: 'networkidle' });
    await app.fill('#login_manv', code.toLowerCase()); await app.click('#btn_login_submit');
    const ok = await app.waitForSelector('#checkinScreen:not(.hidden), #mainApp:not(.hidden)', { timeout: 10000 }).then(() => true).catch(() => false);
    rec(ind, 'Nhân viên thêm ở Staff Management đăng nhập được app', ok);
    await page.goto(BASE + '/bangluong', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => typeof rawEmployeesData !== 'undefined' && rawEmployeesData.length > 0, null, { timeout: 15000 }).catch(() => {});
    rec(ind, 'Có tên trong Bảng lương', await page.evaluate((c) => rawEmployeesData.some((e) => e.ma_nv === c), code));
    // chiều ngược lại: HR -> /staff
    const hrCode = 'QS' + String(Date.now()).slice(-5);
    const r = await page.evaluate(async (c) => (await fetch('/api/hr/employees', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ma_nv: c, ho_ten: 'QA Sync HR ' + c, linh_vuc: 'Văn Phòng' }) })).json(), hrCode);
    const staffList = await page.evaluate(async () => (await fetch('/api/staff')).json());
    rec(ind, 'Thêm ở HR -> có dòng ở Staff Management', r.success && staffList.data.some((s) => s.ma_nv === hrCode && s.id === r.data.staff_id));
    py(`
import json
from mongo_client import db
bid = db.users.find_one({'email': '${email}'})['business_id']
print(json.dumps({'s': db.staff.delete_many({'business_id': bid, 'ma_nv': {'$in': ['${code}', '${hrCode}']}}).deleted_count,
                  'e': db.employees.delete_many({'business_id': bid, 'ma_nv': {'$in': ['${code}', '${hrCode}']}}).deleted_count}))`);
  } catch (e) {
    rec(ind, 'LỖI KHÔNG MONG MUỐN', false, e.message.split('\n')[0]);
  } finally {
    await ctx.close();
  }
}
await browser.close();
console.log(`\nTổng kết: ${results.filter((r) => r.ok).length} PASS · ${results.filter((r) => !r.ok).length} FAIL`);
