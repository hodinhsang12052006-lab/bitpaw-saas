/**
 * scripts/nail_persona_e2e.mjs — test ngách Nails bằng cách ĐÓNG VAI 3 người dùng thật:
 *   THỢ (app nhân viên /app_nhanvien trên máy của tiệm): đăng nhập mã NV, chấm công camera+GPS, gửi đơn
 *     xin nghỉ / hoàn ứng, khen đồng nghiệp, báo cáo công việc, đăng xuất.
 *   CHỦ TIỆM: duyệt đơn xin nghỉ / hoàn ứng, nhập ca có giờ thật, bán bill POS gán thợ, xem bảng lương —
 *     đối chiếu từng con số với DB.
 *   KHÁCH: trang đặt lịch công khai thấy thợ mới + đặt lịch, không vào được trang nội bộ / API nội bộ,
 *     portal chat không bị dò dữ liệu.
 * Thợ test (mã QA####) được tạo khi bắt đầu và XOÁ SẠCH mọi dữ liệu liên quan khi kết thúc.
 *
 * Chạy: node scripts/nail_persona_e2e.mjs   (server local http://127.0.0.1:5001 phải đang chạy)
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { execFileSync } from 'child_process';
import { gotoSell, safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';
const OUT = path.resolve('audit-results/screenshots/nail_persona_e2e');
fs.mkdirSync(OUT, { recursive: true });

const MA_NV = 'QA' + String(Math.floor(1000 + Math.random() * 9000));
const HO_TEN = `QA Persona Tech ${MA_NV}`;
const ENV_NOISE = /ERR_CONNECTION_RESET|ERR_ABORTED|ERR_NETWORK_CHANGED|net::ERR_FAILED/;
// Request lỗi do CHÍNH script cố tình gửi sai (mã NV sai, tạo trùng mã, đặt trùng lịch, dữ liệu dị dạng)
const EXPECTED_HTTP = [/^HTTP 404 GET \/api\/hr\/employees\/KHONGTONTAI99$/, /^HTTP 409 POST \/api\/hr\/employees$/, /^HTTP (409|400) POST \/create_appointment$/];

function db(...args) {
  const out = execFileSync('python', ['scripts/_nail_persona_db.py', ...args], {
    encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  return JSON.parse(out.trim().split('\n').pop());
}

const results = [];
function record(role, name, status, note = '') {
  results.push({ role, name, status, note });
  const icon = status === 'PASS' ? '✅' : status === 'WARN' ? '⚠️ ' : '❌';
  console.log(`${icon} [${role}] ${name}${note ? ' — ' + note : ''}`);
}
const check = (role, name, ok, note = '') => record(role, name, ok ? 'PASS' : 'FAIL', note);

function watchErrors(page, bucket) {
  page.on('pageerror', (e) => bucket.push('pageerror: ' + e.message.split('\n')[0]));
  page.on('console', (m) => {
    // "Failed to load resource" không có URL -> ghi URL thật ở listener response bên dưới
    if (m.type() === 'error' && !ENV_NOISE.test(m.text()) && !m.text().startsWith('Failed to load resource')) bucket.push('console: ' + m.text().slice(0, 160));
  });
  page.on('response', (r) => {
    if (r.status() < 400 || !r.url().startsWith(BASE)) return;
    const line = `HTTP ${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`;
    if (!EXPECTED_HTTP.some((re) => re.test(line))) bucket.push(line);
  });
}

// fetch chạy TRONG trang (đã có CSRF bootstrap của app gắn header X-CSRFToken tự động)
async function api(page, method, url, body) {
  return page.evaluate(async ({ method, url, body }) => {
    const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    let json = null; try { json = await r.json(); } catch (e) { /* not json */ }
    return { status: r.status, json };
  }, { method, url, body });
}

async function loginOwner(ctx) {
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await page.fill('#loginEmail', EMAIL);
  await page.fill('#loginPassword', PASSWORD);
  await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
  if (page.url().includes('/login')) throw new Error('Đăng nhập chủ tiệm thất bại (rate limit?) — restart server rồi chạy lại');
  return page;
}

const todayGB = new Date().toLocaleDateString('en-GB');
const browser = await chromium.launch({
  channel: 'chrome', headless: true,
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
});
const { business_id: BID } = db('business', EMAIL);
let colleague = null; let colleagueKudoBefore = 0;

try {
  // ============================ CHỦ TIỆM: chuẩn bị thợ mới ============================
  const ownerCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ownerCtx.addCookies([{ name: 'bitpaw_lang', value: 'vi', url: BASE }]);
  const owner = await loginOwner(ownerCtx);
  const ownerErrors = []; watchErrors(owner, ownerErrors);
  check('Chủ tiệm', 'Đăng nhập -> vào trang chủ Nails', /chamcong/.test(owner.url()), owner.url().replace(BASE, ''));
  const created = await api(owner, 'POST', '/api/hr/employees', { ma_nv: MA_NV, ho_ten: HO_TEN, linh_vuc: 'Nails', chuc_vu: 'Nail Technician', luong_gio: 20 });
  check('Chủ tiệm', `Thêm thợ mới ${MA_NV} (Nails, $20/giờ)`, created.status === 200 && created.json?.success, `HTTP ${created.status}`);
  const dup = await api(owner, 'POST', '/api/hr/employees', { ma_nv: MA_NV, ho_ten: 'Trùng mã', linh_vuc: 'Nails' });
  check('Chủ tiệm', 'Tạo trùng mã NV bị từ chối (409)', dup.status === 409, `HTTP ${dup.status}`);
  const emps = (await api(owner, 'GET', '/api/hr/employees')).json?.data || [];
  colleague = emps.find((e) => e.ma_nv !== MA_NV && (e.linh_vuc || '').includes('Nails'));
  colleagueKudoBefore = colleague ? db('kudo', BID, colleague.ma_nv).diem_kudo : 0;

  // ============================ THỢ: app nhân viên trên máy tiệm ============================
  const staffCtx = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    permissions: ['camera', 'geolocation'], geolocation: { latitude: -33.8688, longitude: 151.2093 },
    storageState: await ownerCtx.storageState(),
  });
  const staff = await staffCtx.newPage();
  const staffErrors = []; watchErrors(staff, staffErrors);
  await staff.goto(`${BASE}/app_nhanvien`, { waitUntil: 'networkidle' });
  await staff.click('#tabRegister');
  const regHtml = await staff.locator('#formRegister').innerText();
  check('Thợ', 'Tab "New Account" không còn mã công ty ghi cứng, hướng dẫn nhờ chủ tiệm thêm',
    !(await staff.content()).includes('BITPAW2026') && /Staff Management/i.test(regHtml));
  await staff.click('#tabLogin');
  await staff.fill('#login_manv', 'KHONGTONTAI99');
  await staff.click('#btn_login_submit');
  await staff.waitForTimeout(1200);
  check('Thợ', 'Gõ sai mã NV -> không vào được app', await staff.locator('#authScreen').isVisible());
  await staff.fill('#login_manv', MA_NV.toLowerCase());
  await staff.click('#btn_login_submit');
  await staff.waitForSelector('#checkinScreen:not(.hidden)', { timeout: 8000 });
  check('Thợ', 'Đăng nhập bằng mã NV (gõ chữ thường) -> màn chấm công đúng tên', (await staff.locator('#checkin_name').innerText()).includes(HO_TEN));
  await safeScreenshot(staff, { path: path.join(OUT, '01_staff_checkin_screen.png') });

  // nút CLOCK IN có hiệu ứng nhịp thở (btn-glow) liên tục -> Playwright coi là "không đứng yên"; người thật bấm bình thường
  await staff.click('[onclick="startCameraAndGPS()"]', { force: true });
  await staff.waitForSelector('#captureBtn:not([disabled])', { timeout: 15000 });
  await staff.click('#captureBtn');
  await staff.waitForSelector('#mainApp:not(.hidden)', { timeout: 15000 });
  await staff.waitForTimeout(800);
  let st = db('state', BID, MA_NV);
  const checkin = st.chamcong.find((r) => r.trang_thai === 'Có mặt');
  check('Thợ', 'Chấm công camera + GPS -> 1 bản ghi "Có mặt" có ảnh + toạ độ',
    !!checkin && !!checkin.anh_checkin && /^-33\.86/.test(checkin.toa_do || ''), checkin ? `${checkin.ngay_cham} ${checkin.toa_do}` : 'không có bản ghi');
  await safeScreenshot(staff, { path: path.join(OUT, '02_staff_home_after_checkin.png') });

  const again = await api(staff, 'POST', '/api/hr/chamcong', { ma_nv: MA_NV, ngay_cham: todayGB, gio_den: '10:00', trang_thai: 'Có mặt', nganh_nghe: 'Nails' });
  st = db('state', BID, MA_NV);
  check('Thợ', 'Chấm công lần 2 trong ngày (đăng xuất/đăng nhập lại) không tạo thêm ngày công',
    again.json?.duplicate === true && st.chamcong.filter((r) => r.trang_thai === 'Có mặt').length === 1);

  // Báo cáo công việc: thợ Nails không tự khai tiền vào lương
  const moneyVisible = await staff.locator('#work_money').isVisible();
  check('Thợ', 'Báo cáo công việc: ẩn ô tự khai Revenue/Tips (Nails ăn hoa hồng theo bill POS)', !moneyVisible);
  await staff.fill('#work_content', 'Full set acrylic, khách hài lòng');
  await staff.click('#btn_submit_report');
  await staff.waitForTimeout(1500);
  st = db('state', BID, MA_NV);
  const report = st.chamcong.find((r) => (r.ghi_chu || '').includes('Full set acrylic'));
  check('Thợ', 'Gửi báo cáo -> lưu với tiền tua/tips = 0', !!report && !report.tien_tua && !report.tien_tips,
    report ? `tua=${report.tien_tua} tips=${report.tien_tips}` : 'không thấy báo cáo');

  // Tab tiện ích: xin nghỉ, hoàn ứng, khen đồng nghiệp
  await staff.click('[onclick="switchAppTab(\'apps\')"]');
  const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  await staff.fill('#app_leave_date', tomorrow);
  await staff.fill('#app_leave_reason', 'QA persona: đưa con đi khám');
  await staff.click('[onclick="sendLeaveRequest()"]');
  await staff.waitForFunction(() => document.getElementById('myLeaveRequestsBox').innerText.trim().length > 0, null, { timeout: 8000 }).catch(() => {});
  check('Thợ', 'Gửi đơn xin nghỉ -> hiện "Chờ duyệt" trong app', /Chờ duyệt/.test(await staff.locator('#myLeaveRequestsBox').innerText()));
  await staff.fill('#app_expense_amount', '25');
  await staff.fill('#app_expense_desc', 'QA persona: mua gel top coat');
  await staff.click('[onclick="sendExpenseRequest()"]');
  await staff.waitForFunction(() => document.getElementById('myExpenseRequestsBox').innerText.trim().length > 0, null, { timeout: 8000 }).catch(() => {});
  const expText = await staff.locator('#myExpenseRequestsBox').innerText();
  check('Thợ', 'Gửi đơn hoàn ứng $25 -> hiện đúng tiền tệ của tiệm (không còn "₫")', /25/.test(expText) && !expText.includes('₫'), expText.split('\n')[0]);
  if (colleague) {
    await staff.selectOption('#app_kudo_receiver', colleague.ma_nv);
    await staff.click('[onclick="sendKudo()"]');
    await staff.waitForTimeout(1200);
    const after = db('kudo', BID, colleague.ma_nv).diem_kudo;
    check('Thợ', `Khen đồng nghiệp ${colleague.ho_ten} -> +1 điểm`, after === colleagueKudoBefore + 1, `${colleagueKudoBefore} -> ${after}`);
    await api(staff, 'POST', `/api/hr/employees/${colleague.ma_nv}/kudo`, { points: 999999 });
    const after2 = db('kudo', BID, colleague.ma_nv).diem_kudo;
    check('Thợ', 'Gửi điểm khen 999999 qua API bị giới hạn (tối đa 5)', after2 - after <= 5, `+${after2 - after}`);
  } else record('Thợ', 'Khen đồng nghiệp', 'WARN', 'tiệm demo không có thợ Nails khác');
  await safeScreenshot(staff, { path: path.join(OUT, '03_staff_apps_requests.png') });
  const offW = await staff.evaluate(() => document.scrollingElement.scrollWidth - innerWidth);
  check('Thợ', 'App nhân viên trên điện thoại không tràn ngang', offW <= 1, `scrollWidth-innerWidth=${offW}`);

  await staff.click('[onclick="switchAppTab(\'profile\')"]');
  await staff.click('[onclick="dangXuat()"]');
  await staff.click('#btn-confirm-yes');
  await staff.waitForEvent('load', { timeout: 10000 }).catch(() => {});
  await staff.waitForTimeout(800);
  check('Thợ', 'Đăng xuất -> về màn đăng nhập mã NV', await staff.locator('#authScreen').isVisible());
  check('Thợ', 'Không có lỗi JS trong suốt ca làm', staffErrors.length === 0, staffErrors.slice(0, 3).join(' | '));

  // ============================ CHỦ TIỆM: duyệt đơn, nhập ca, bán bill, xem lương ============================
  st = db('state', BID, MA_NV);
  const leave = st.leave[0]; const exp = st.expense[0];
  await owner.goto(`${BASE}/leave_requests`, { waitUntil: 'networkidle' });
  const leaveRow = owner.locator(`button[onclick="respond(${leave?.id}, 'approved')"]`);
  check('Chủ tiệm', 'Thấy đơn xin nghỉ của thợ ở /leave_requests', leave && await leaveRow.count() === 1);
  if (leave && await leaveRow.count()) { await leaveRow.click(); await owner.waitForTimeout(1200); }
  await owner.goto(`${BASE}/expense_requests`, { waitUntil: 'networkidle' });
  const expRow = owner.locator(`button[onclick="respond(${exp?.id}, 'approved')"]`);
  check('Chủ tiệm', 'Thấy đơn hoàn ứng của thợ ở /expense_requests', exp && await expRow.count() === 1);
  if (exp && await expRow.count()) { await expRow.click(); await owner.waitForTimeout(1200); }
  st = db('state', BID, MA_NV);
  check('Chủ tiệm', 'Duyệt 2 đơn -> trạng thái approved trong DB', st.leave[0]?.status === 'approved' && st.expense[0]?.status === 'approved');

  // Chủ tiệm nhập ca có giờ thật cho ngày thợ đã check-in camera -> lương giờ không cộng thêm 8h mặc định
  await owner.goto(`${BASE}/chamcong/nail`, { waitUntil: 'networkidle' });
  const shift = await api(owner, 'POST', '/api/hr/chamcong', { ma_nv: MA_NV, ngay_cham: todayGB, nganh_nghe: 'Nails', trang_thai: 'Có mặt', gio_den: '09:00', gio_ve: '15:00', so_gio: 6, ghi_chu: '[SHIFT] 09:00 - 15:00', tien_tua: 0, tien_tips: 0 });
  st = db('state', BID, MA_NV);
  check('Chủ tiệm', 'Nhập ca 6 giờ -> lượt check-in camera chuyển "Check-in" (không tính thêm 8h)',
    shift.json?.success && st.chamcong.filter((r) => r.trang_thai === 'Có mặt').length === 1 && st.chamcong.some((r) => r.trang_thai === 'Check-in'));

  // Bán 1 bill POS gán cho thợ test: dịch vụ thật của tiệm + tip thẻ
  await gotoSell(owner, BASE);
  const services = await owner.evaluate(() => SERVICES);
  const svc = services.find((s) => Number(s.price) > 0);
  const sale = await api(owner, 'POST', '/api/nail_pos/checkout', {
    items: [{ product_id: svc.id, quantity: 1, ma_nv: MA_NV }], payment_method: 'card',
    card_tip: 10, cc_fee_percent: 3, currency: 'AUD',
  });
  check('Chủ tiệm', `Bán bill POS "${svc?.name}" $${svc?.price} gán thợ test`, sale.json?.success && sale.json?.order_id, `order #${sale.json?.order_id}`);
  st = db('state', BID, MA_NV);
  const commission = st.chamcong.filter((r) => r.trang_thai === 'Đã chốt').reduce((a, r) => a + (r.tien_tua || 0), 0);
  check('Chủ tiệm', 'Hoa hồng của thợ ghi vào chấm công từ bill', commission > 0, `$${commission}`);

  await owner.goto(`${BASE}/bangluong`, { waitUntil: 'networkidle' });
  await owner.waitForFunction((code) => (globalPayrollData || []).some((p) => p.ma_nv === code), MA_NV, { timeout: 15000 }).catch(() => {});
  const pay = await owner.evaluate((code) => (globalPayrollData || []).find((p) => p.ma_nv === code), MA_NV);
  const expectHourly = 6 * 20;
  check('Chủ tiệm', 'Bảng lương: lương giờ = 6h × $20 (không cộng dư giờ check-in)', pay && Math.abs(pay.luong_hien_thi - expectHourly) < 0.01, pay ? `lương chính $${pay.luong_hien_thi}` : 'không thấy thợ trong bảng lương');
  check('Chủ tiệm', 'Bảng lương: hoa hồng khớp DB, không có tiền tự khai', pay && Math.abs(pay.cot2_hien_thi - commission) < 0.01, pay ? `hoa hồng $${pay.cot2_hien_thi} / DB $${commission}` : '');
  await safeScreenshot(owner, { path: path.join(OUT, '04_owner_payroll.png') });
  check('Chủ tiệm', 'Không có lỗi JS ở các trang chủ tiệm vừa dùng', ownerErrors.length === 0, ownerErrors.slice(0, 3).join(' | '));

  // ============================ KHÁCH HÀNG (không đăng nhập) ============================
  const custCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const cust = await custCtx.newPage();
  const custErrors = []; watchErrors(cust, custErrors);
  await cust.goto(`${BASE}/booking/nail/qr/${BID}`, { waitUntil: 'networkidle' });
  await cust.waitForFunction(() => document.querySelectorAll('#cus_staff option').length > 1, null, { timeout: 10000 }).catch(() => {});
  const staffOptions = await cust.locator('#cus_staff option').allInnerTexts();
  check('Khách', 'Trang đặt lịch QR hiện thợ mới trong danh sách chọn thợ', staffOptions.some((t) => t.includes(HO_TEN)), `${staffOptions.length - 1} thợ`);
  const bookTime = new Date(Date.now() + 2 * 86400000); bookTime.setMinutes(0, 0, 0);
  const localIso = new Date(bookTime - bookTime.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  await cust.fill('#cus_name', `QA Persona Khách ${MA_NV}`);
  await cust.fill('#cus_phone', '0400000' + MA_NV.slice(2));
  await cust.selectOption('#cus_service', String(svc.id));
  const techVal = await cust.locator('#cus_staff option', { hasText: HO_TEN }).getAttribute('value');
  if (techVal) await cust.selectOption('#cus_staff', techVal);
  await cust.fill('#cus_datetime', localIso);
  await cust.fill('#cus_address', 'QA');
  await cust.click('#btnSubmit');
  await cust.waitForTimeout(2500);
  const appt = db('appts', BID, `QA Persona Khách ${MA_NV}`);
  check('Khách', 'Khách đặt lịch với thợ mới -> lịch hẹn lưu đúng thợ, đúng giờ', appt.count === 1 && String(appt.items[0]?.staff_id) === String(techVal) && (appt.items[0]?.book_time || '').startsWith(localIso),
    appt.count ? `staff_id=${appt.items[0].staff_id} ${appt.items[0].book_time}` : 'không có lịch hẹn');
  await owner.goto(`${BASE}/calendar?date=${localIso.slice(0, 10)}`, { waitUntil: 'networkidle' });
  check('Chủ tiệm', 'Lịch hẹn của khách hiện trên /calendar', (await owner.content()).includes(`QA Persona Khách ${MA_NV}`));
  await safeScreenshot(cust, { path: path.join(OUT, '05_customer_booking.png') });
  const dupBook = await cust.evaluate(async ({ sid, staffId, t, code }) => {
    const r = await fetch('/create_appointment', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: `QA Persona Khách 2 ${code}`, phone: '0411111111', service_id: sid, staff_id: staffId, book_time: t }) });
    return r.status;
  }, { sid: svc.id, staffId: techVal, t: localIso, code: MA_NV });
  check('Khách', 'Khách khác đặt trùng giờ trùng thợ -> bị chặn (409)', dupBook === 409, `HTTP ${dupBook}`);
  const badBook = await cust.evaluate(async () => (await fetch('/create_appointment', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ service_id: { $gt: 0 }, name: 'x', phone: '1', book_time: '2030-01-01T10:00' }) })).status);
  check('Khách', 'Gửi dữ liệu đặt lịch dị dạng (NoSQL injection) -> 400, không lỗi server', badBook === 400, `HTTP ${badBook}`);

  const internal = ['/sell', '/bangluong', '/customers', '/app_nhanvien', '/leave_requests', '/calendar', '/chamcong/nail', '/report_consolidated'];
  const leaked = [];
  for (const p of internal) {
    const r = await cust.request.get(`${BASE}${p}`, { maxRedirects: 0 });
    if (!(r.status() === 302 && /\/login/.test(r.headers().location || ''))) leaked.push(`${p}:${r.status()}`);
  }
  check('Khách', `${internal.length} trang nội bộ đều chuyển về đăng nhập`, leaked.length === 0, leaked.join(', '));
  const apis = ['/api/hr/employees', '/api/leave_requests', '/api/expense_requests', `/api/hr/employees/${MA_NV}`, '/api/hr/chamcong', '/api/desktop/sync_status'];
  const apiLeaks = [];
  for (const p of apis) {
    const r = await cust.request.get(`${BASE}${p}`, { headers: { Accept: 'application/json' }, maxRedirects: 0 });
    if (![401, 302].includes(r.status())) apiLeaks.push(`${p}:${r.status()}`);
  }
  check('Khách', `${apis.length} API nội bộ đều từ chối khi chưa đăng nhập`, apiLeaks.length === 0, apiLeaks.join(', '));
  const portalProbe = await cust.request.get(`${BASE}/api/portal/messages?customer_id[$ne]=x`);
  const portalFake = await cust.request.get(`${BASE}/api/portal/messages?customer_id=${BID}:0000000000`);
  check('Khách', 'Portal chat: dò customer_id giả / toán tử -> 404, không lộ tin nhắn', portalProbe.status() === 404 && portalFake.status() === 404, `${portalProbe.status()}/${portalFake.status()}`);
  const staffPost = await cust.request.post(`${BASE}/api/portal/messages`, { data: { customer_id: `${BID}:0000000000`, content: 'x', sender_type: 'staff' } });
  check('Khách', 'Portal: khách không giả danh nhân viên trả lời được', [400, 404].includes(staffPost.status()), `HTTP ${staffPost.status()}`);
  check('Khách', 'Không có lỗi JS trên trang đặt lịch', custErrors.length === 0, custErrors.slice(0, 3).join(' | '));

  await custCtx.close(); await staffCtx.close(); await ownerCtx.close();
} catch (e) {
  record('Hệ thống', 'LỖI KHÔNG MONG MUỐN', 'FAIL', e.message.split('\n')[0]);
} finally {
  if (colleague) {
    // trả lại điểm kudo của đồng nghiệp như trước khi test
    execFileSync('python', ['-c', `import sys; sys.path.insert(0,'.'); from mongo_client import db; db.employees.update_one({'business_id': ${JSON.stringify(BID)}, 'ma_nv': ${JSON.stringify(colleague.ma_nv)}}, {'$set': {'diem_kudo': ${colleagueKudoBefore}}})`], { encoding: 'utf-8' });
  }
  const cleaned = db('cleanup', BID, MA_NV, HO_TEN);
  console.log('Dọn dữ liệu test:', JSON.stringify(cleaned));
  await browser.close();
}

const pass = results.filter((r) => r.status === 'PASS').length;
const warn = results.filter((r) => r.status === 'WARN').length;
const fail = results.filter((r) => r.status === 'FAIL').length;
fs.writeFileSync('audit-results/nail_persona_e2e_report.json', JSON.stringify({ ran_at: new Date().toISOString(), results }, null, 2));
console.log(`\nTổng kết: ${pass} PASS · ${warn} WARN · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
