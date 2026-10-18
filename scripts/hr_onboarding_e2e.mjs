// Chủ tiệm MỚI tự thêm nhân viên bằng giao diện (không gọi API tắt), ở cả 9 ngành:
//   menu "Nhân viên & tài khoản app" -> form thêm (phòng ban phải chọn sẵn đúng ngành) -> nhân viên đăng nhập app nhân viên
//   bằng mã vừa tạo -> tới màn chấm công -> có tên trong Bảng lương của tiệm. Dọn nhân viên thử sau mỗi ngành.
// Trước đây chỉ Nails có đường tới trang thêm nhân viên; Bán lẻ/Karaoke còn không có phòng ban của mình.
//   DEVICE=desktop|mobile node scripts/hr_onboarding_e2e.mjs      (CHỈ server local)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';
import { ownerContextOptions, DEVICE } from './lib/device.mjs';

const BASE = 'http://127.0.0.1:5001';
const T = {
  nail: ['demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!', 'Nails'],
  fnb: ['demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!', 'F&B'],
  spa: ['demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!', 'Spa & Beauty'],
  retail: ['demo.retail.596348@bitpawdemo.com', 'DemoBitPaw2026!', 'Retail'],
  karaoke: ['demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!', 'Karaoke'],
  hotel: ['demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!', 'Khách Sạn'],
  production: ['demo.production.393328@bitpawdemo.com', 'DemoBitPaw2026!', 'Sản Xuất'],
  technical: ['demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!', 'Kỹ Thuật'],
  office: ['demo.office.784966@bitpawdemo.com', 'DemoBitPaw2026!', 'Văn Phòng'],
};
const db = (...a) => JSON.parse(execFileSync('python', ['scripts/_nail_persona_db.py', ...a], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop());
const results = [];
const rec = (ind, name, ok, note = '') => { results.push({ ind, name, ok }); console.log(`${ok ? '✅' : '❌'} [${DEVICE}][${ind}] ${name}${note ? ' — ' + note : ''}`); };

const browser = await chromium.launch({ channel: 'chrome', headless: true });
for (const [ind, [email, pw, dept]] of Object.entries(T)) {
  const code = 'QH' + String(Math.floor(1000 + Math.random() * 9000));
  const ctx = await browser.newContext(ownerContextOptions());
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  try {
    await page.goto(BASE + '/login');
    await page.fill('#loginEmail', email); await page.fill('#loginPassword', pw);
    await Promise.all([page.waitForLoadState('networkidle').catch(() => {}), page.click('#btnLogin')]);
    // mở trang có menu (trang chủ POS của vài ngành không có sidebar)
    await page.goto(BASE + '/ai_bot', { waitUntil: 'networkidle' });
    const link = page.locator('#app-sidebar a[href="/nhanvien"]');
    rec(ind, 'Menu có mục "Nhân viên & tài khoản app"', (await link.count()) === 1);
    await page.goto(BASE + '/nhanvien', { waitUntil: 'networkidle' });
    const preset = await page.locator('#linh_vuc').inputValue();
    rec(ind, 'Form thêm nhân viên chọn sẵn đúng ngành', preset === dept, `"${preset}"`);
    await page.fill('#ma_nv', code);
    await page.fill('#ho_ten', `QA Onboard ${ind} ${code}`);
    await page.click('button[onclick="addEmployee()"]');
    await page.waitForTimeout(1500);
    const st = db('state', db('business', email).business_id, code);
    rec(ind, 'Lưu hồ sơ nhân viên bằng giao diện', !!st.employee, st.employee ? `${st.employee.ma_nv} / ${st.employee.linh_vuc}` : 'không thấy trong DB');
    // nhân viên đăng nhập app nhân viên bằng mã vừa tạo
    const staff = await ctx.newPage();
    await staff.goto(BASE + '/app_nhanvien', { waitUntil: 'networkidle' });
    await staff.fill('#login_manv', code.toLowerCase());
    await staff.click('#btn_login_submit');
    const okLogin = await staff.waitForSelector('#checkinScreen:not(.hidden), #mainApp:not(.hidden)', { timeout: 10000 }).then(() => true).catch(() => false);
    rec(ind, 'Nhân viên mới đăng nhập được app nhân viên', okLogin);
    await page.goto(BASE + '/bangluong', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => typeof globalPayrollData !== 'undefined' && document.querySelectorAll('#payrollBox > *').length > 0, null, { timeout: 15000 }).catch(() => {});
    const inPayroll = await page.evaluate((c) => (rawEmployeesData || []).some((e) => e.ma_nv === c), code);
    rec(ind, 'Có tên trong Bảng lương của tiệm', inPayroll);
    rec(ind, 'Không lỗi JS', errs.length === 0, errs.join(' | '));
  } catch (e) {
    rec(ind, 'LỖI KHÔNG MONG MUỐN', false, e.message.split('\n')[0]);
  } finally {
    const bid = db('business', email).business_id;
    console.log('   dọn:', JSON.stringify(db('cleanup', bid, code, `QA Onboard ${ind} ${code}`)));
    await ctx.close();
  }
}
await browser.close();
console.log(`\nTổng kết: ${results.filter((r) => r.ok).length} PASS · ${results.filter((r) => !r.ok).length} FAIL`);
