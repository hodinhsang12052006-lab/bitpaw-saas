/**
 * scripts/hotel_industry_master_audit.mjs
 *
 * QA Master Audit — Hotel Industry vertical (nhận phòng, phụ thu dịch vụ đi kèm, trả phòng
 * tự tính đêm+phụ thu, dọn phòng, đặt phòng công khai qua QR).
 *
 * Chạy:  node scripts/hotel_industry_master_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Mọi selector đã xác minh TRỰC TIẾP bằng grep + đọc code thật trong templates/hotel_rooms.html,
 * templates/hotel_reservation_public.html, app.py — KHÔNG suy đoán.
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.HOTEL_DEMO_EMAIL || 'demo.hotel.071443@bitpawdemo.com';
const PASSWORD = process.env.HOTEL_DEMO_PASSWORD || 'DemoBitPaw2026!';
const BUSINESS_ID = process.env.HOTEL_DEMO_BUSINESS_ID || '885e1075-9191-4b1e-91ee-d100e961257d';

const SCREEN_DIR = path.resolve('audit-results/screenshots/hotel_master_audit');
const REPORT_JSON = path.resolve('audit-results/hotel_master_audit_report.json');
const REPORT_MD = path.resolve('audit-results/hotel_master_audit_report.md');

fs.mkdirSync(SCREEN_DIR, { recursive: true });

const results = [];
const findings = [];

function record(name, status, ms, note = '') {
  results.push({ name, status, ms, note });
  const icon = status === 'PASS' ? '✅' : status === 'WARN' ? '⚠️' : '❌';
  console.log(`${icon} [${status}] ${name} (${ms}ms) ${note ? '— ' + note : ''}`);
}
function finding(text) {
  findings.push(text);
  console.log(`   ⚠ FINDING: ${text}`);
}
async function shot(page, name) {
  await safeScreenshot(page, { path: path.join(SCREEN_DIR, name), fullPage: true });
}

async function main() {
  console.log('=== HOTEL INDUSTRY MASTER AUDIT — bắt đầu ===\n');
  console.log(`Target: ${BASE}   Account: ${EMAIL}   Business: ${BUSINESS_ID}\n`);

  const consoleErrors = [];
  const networkErrors = [];

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('response', (res) => { if (res.status() >= 500) networkErrors.push(`${res.status()} ${res.request().method()} ${res.url()}`); });
  page.on('dialog', async (d) => { await d.accept(); });

  // ============================================================
  // TEST 1 — Đăng nhập & Khởi tạo Sơ Đồ Phòng Khách Sạn
  // ============================================================
  let t0 = Date.now();
  try {
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    const rateLimited = (await page.content()).match(/429|Too Many Requests|quá nhiều yêu cầu/i);
    if (rateLimited) throw new Error('Server đang rate-limit /login (5 lần/15 phút) — đợi hết cửa sổ giới hạn rồi chạy lại.');

    await page.fill('#loginEmail', EMAIL);
    await page.fill('#loginPassword', PASSWORD);
    await Promise.all([
      page.waitForLoadState('networkidle'),
      page.click('#btnLogin'),
    ]);

    const afterLoginUrl = page.url();
    if (afterLoginUrl.includes('/login')) throw new Error(`Đăng nhập thất bại — vẫn ở lại /login. URL: ${afterLoginUrl}`);

    await page.goto(`${BASE}/hotel_rooms`, { waitUntil: 'networkidle' });
    await page.waitForSelector('.room-card', { timeout: 10000 });

    const roomCount = await page.locator('.room-card').count();
    await shot(page, '01_hotel_launch.png');

    const errorsExcludingFavicon = consoleErrors.filter((e) => !/favicon/i.test(e));
    const pass = errorsExcludingFavicon.length === 0 && networkErrors.length === 0 && roomCount > 0;
    record('1. Đăng nhập & Khởi tạo Sơ Đồ Phòng', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `console_errors=${consoleErrors.length}, network_5xx=${networkErrors.length}, rooms=${roomCount}`);
  } catch (e) {
    record('1. Đăng nhập & Khởi tạo Sơ Đồ Phòng', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_hotel_launch_FAILED.png').catch(() => {});
    await finalize({ browser, results, findings });
    process.exit(1);
  }

  // ============================================================
  // TEST 2 — Nhận phòng (Check-in), thêm phụ thu, trả phòng (Checkout) tự tính tiền
  // ============================================================
  t0 = Date.now();
  let roomId = null;
  try {
    // Dùng class CSS ".status-trong" (không dịch theo ngôn ngữ) thay vì khớp chữ hiển thị
    // "Trống" — badge trạng thái đi qua t('hr_status_empty') nên có thể hiện "Empty"/"Available"
    // tuỳ ngôn ngữ hiện tại của trình duyệt, khớp chữ cứng sẽ không ổn định.
    const emptyRoom = page.locator('.room-card.status-trong').first();
    roomId = await emptyRoom.evaluate((el) => el.getAttribute('onclick').match(/handleRoomClick\((\d+)/)[1]);

    await emptyRoom.click();
    await page.waitForSelector('#checkinModal.active', { timeout: 3000 });
    const guestName = 'QA Audit Hotel Guest';
    await page.fill('#guestName', guestName);
    await page.fill('#guestPhone', '0497' + String(Date.now()).slice(-6));

    const [checkinResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes(`/api/hotel/rooms/${roomId}/checkin`) && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate(() => window.submitCheckin()),
    ]);
    const checkinStatus = checkinResp.status();
    const checkinBody = await checkinResp.json().catch(() => null);
    await page.waitForTimeout(500);
    await shot(page, '02a_hotel_checkin_success.png');

    // Thêm 1 phụ thu (minibar) cho phòng vừa nhận — gọi thẳng hàm JS thay vì tìm nút theo chữ
    // hiển thị (label cũng đi qua i18n, không ổn định theo ngôn ngữ hiện tại của trình duyệt).
    await page.evaluate((id) => window.openAddChargeModal(parseInt(id)), roomId);
    await page.waitForSelector('#addChargeModal.active', { timeout: 3000 });
    await page.fill('#newChargeDesc', 'Minibar - QA Audit');
    await page.fill('#newChargeAmount', '150000');

    const [chargeResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes(`/api/hotel/rooms/${roomId}/charges`) && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate(() => window.submitAddCharge()),
    ]);
    const chargeStatus = chargeResp.status();
    const chargeBody = await chargeResp.json().catch(() => null);
    await page.waitForTimeout(400);
    await shot(page, '02b_hotel_charge_added.png');

    // Trả phòng — xác nhận total = tiền phòng + phụ thu vừa thêm
    await page.evaluate((id) => window.openCheckoutModal(parseInt(id)), roomId);
    await page.waitForSelector('#checkoutModal.active', { timeout: 3000 });
    await page.waitForTimeout(300);
    await shot(page, '02c_hotel_checkout_modal.png');

    const [checkoutResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes(`/api/hotel/rooms/${roomId}/checkout`) && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate(() => window.submitCheckout()),
    ]);
    const checkoutStatus = checkoutResp.status();
    const checkoutBody = await checkoutResp.json().catch(() => null);
    await page.waitForTimeout(500);
    await shot(page, '02d_hotel_checkout_success.png');

    const extraChargesMatch = checkoutBody?.extra_charges_total === 150000;
    const totalMatch = checkoutBody?.total_amount === (checkoutBody?.room_total + checkoutBody?.extra_charges_total);

    const pass = checkinStatus === 200 && checkinBody?.success === true &&
      chargeStatus === 200 && chargeBody?.success === true &&
      checkoutStatus === 200 && checkoutBody?.success === true &&
      extraChargesMatch && totalMatch;

    record('2. Nhận Phòng, Thêm Phụ Thu & Trả Phòng', pass ? 'PASS' : 'FAIL', Date.now() - t0,
      `Phòng id=${roomId}. Checkin: HTTP ${checkinStatus}. Thêm phụ thu 150,000: HTTP ${chargeStatus}. Checkout: HTTP ${checkoutStatus}, room_total=${checkoutBody?.room_total}, extra_charges_total=${checkoutBody?.extra_charges_total} (kỳ vọng 150000), total_amount=${checkoutBody?.total_amount}.`);

    if (!extraChargesMatch) {
      finding(`Phụ thu 150,000 vừa thêm không khớp extra_charges_total trả về (${checkoutBody?.extra_charges_total}) khi trả phòng — kiểm tra lại logic gộp hotel_room_charges vào checkout.`);
    }
  } catch (e) {
    record('2. Nhận Phòng, Thêm Phụ Thu & Trả Phòng', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_hotel_room_lifecycle_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 3 — Dọn phòng (Housekeeping): "Đang dọn" -> "Trống"
  // ============================================================
  t0 = Date.now();
  try {
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('.room-card', { timeout: 10000 });

    if (!roomId) throw new Error('Không có room_id từ Test 2 để test dọn phòng.');

    const [markCleanResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes(`/api/hotel/rooms/${roomId}/mark_clean`) && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate((id) => window.markClean(parseInt(id)), roomId),
    ]);
    const status = markCleanResp.status();
    const body = await markCleanResp.json().catch(() => null);
    await page.waitForTimeout(400);
    await shot(page, '03_hotel_room_cleaned.png');

    const pass = status === 200 && body?.success === true;
    record('3. Dọn Phòng (Housekeeping)', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Phòng id=${roomId}: HTTP ${status}, body=${JSON.stringify(body).slice(0, 150)}`);
  } catch (e) {
    record('3. Dọn Phòng (Housekeeping)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_hotel_cleaning_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 4 — Đặt phòng công khai qua QR + hiện trên trang quản trị
  // ============================================================
  t0 = Date.now();
  let bookingContext = null;
  try {
    bookingContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const bookingPage = await bookingContext.newPage();
    const bookingConsoleErrors = [];
    bookingPage.on('console', (msg) => { if (msg.type() === 'error') bookingConsoleErrors.push(msg.text()); });

    await bookingPage.goto(`${BASE}/hotel/reserve/${BUSINESS_ID}`, { waitUntil: 'networkidle' });
    await bookingPage.waitForSelector('#reserveForm', { timeout: 8000 });

    const customerName = 'QA Audit Hotel Khach';
    const customerPhone = '0498' + String(Date.now()).slice(-6);
    const checkinDate = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    const checkoutDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    await bookingPage.fill('input[name="name"]', customerName);
    await bookingPage.fill('input[name="phone"]', customerPhone);
    await bookingPage.fill('input[name="checkin_date"]', checkinDate);
    await bookingPage.fill('input[name="checkout_date"]', checkoutDate);
    await bookingPage.fill('input[name="party_size"]', '2');
    await bookingPage.selectOption('select[name="room_type"]', 'Deluxe');
    await bookingPage.fill('textarea[name="note"]', 'Đặt qua audit script Hotel — kiểm tra luồng đặt phòng công khai.');
    await shot(bookingPage, '04a_hotel_reservation_form_filled.png');

    const [reserveResp] = await Promise.all([
      bookingPage.waitForResponse((res) => res.url().includes(`/api/public/hotel_reservations/${BUSINESS_ID}`) && res.request().method() === 'POST', { timeout: 10000 }),
      bookingPage.click('#submitBtn'),
    ]);
    const reserveStatus = reserveResp.status();
    const reserveBody = await reserveResp.json().catch(() => null);
    await bookingPage.waitForSelector('#successCard:not(.hidden)', { timeout: 5000 }).catch(() => {});
    await shot(bookingPage, '04b_hotel_reservation_success.png');

    await page.goto(`${BASE}/hotel/reservations`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    const adminBodyText = await page.locator('body').innerText();
    const reservationVisible = adminBodyText.includes(customerPhone) || adminBodyText.includes(customerName);
    await shot(page, '04c_hotel_reservations_admin_side.png');

    const pass = reserveStatus === 200 && reserveBody?.success === true && !!reserveBody?.id && reservationVisible && bookingConsoleErrors.length === 0;
    record('4. Đặt Phòng Công Khai QR + Hiện Trên Trang Quản Trị', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `POST /api/public/hotel_reservations/${BUSINESS_ID}: HTTP ${reserveStatus}, id=${reserveBody?.id}. Hiện trên /hotel/reservations: ${reservationVisible}. Console errors trang khách: ${bookingConsoleErrors.length}.`);

    if (!reservationVisible) {
      finding('Đặt phòng Hotel qua QR ghi API thành công nhưng KHÔNG thấy xuất hiện trên /hotel/reservations — kiểm tra lại query/filter hiển thị.');
    }
  } catch (e) {
    record('4. Đặt Phòng Công Khai QR + Hiện Trên Trang Quản Trị', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '04_hotel_reservation_FAILED.png').catch(() => {});
  } finally {
    if (bookingContext) await bookingContext.close().catch(() => {});
  }

  // ============================================================
  // TEST 5 — Chấm công Hotel + Module dùng chung
  // ============================================================
  t0 = Date.now();
  try {
    const errorsBefore = consoleErrors.length;
    await page.goto(`${BASE}/chamcong_khachsan`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    const bodyText = await page.locator('body').innerText();
    const newErrors = consoleErrors.length - errorsBefore;
    await shot(page, '05_hotel_chamcong.png');

    const sharedPages = ['/customers', '/ai_bot', '/nhanvien', '/report'];
    const sharedResults = [];
    for (const url of sharedPages) {
      const resp = await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle' }).catch((e) => ({ _err: e.message }));
      const status = resp && resp.status ? resp.status() : null;
      sharedResults.push(`${url}=${status ?? 'ERR'}`);
    }
    const allSharedOk = sharedResults.every((r) => r.endsWith('=200'));

    const pass = bodyText.length > 50 && newErrors === 0 && allSharedOk;
    record('5. Chấm Công Hotel + Module Dùng Chung', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Chấm công: ${bodyText.length} ký tự, ${newErrors} lỗi console mới. Shared: ${sharedResults.join(', ')}`);
  } catch (e) {
    record('5. Chấm Công Hotel + Module Dùng Chung', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '05_hotel_chamcong_FAILED.png').catch(() => {});
  }

  await finalize({ browser, results, findings, consoleErrors, networkErrors });
}

async function finalize({ browser, results, findings, consoleErrors = [], networkErrors = [] }) {
  await browser.close();

  const passCount = results.filter((r) => r.status === 'PASS').length;
  const warnCount = results.filter((r) => r.status === 'WARN').length;
  const failCount = results.filter((r) => r.status === 'FAIL').length;

  const reportData = {
    generatedAt: new Date().toISOString(),
    summary: { total: results.length, pass: passCount, warn: warnCount, fail: failCount },
    results,
    findings,
    consoleErrorsSample: consoleErrors.slice(0, 10),
    networkErrorsSample: networkErrors.slice(0, 10),
  };
  fs.writeFileSync(REPORT_JSON, JSON.stringify(reportData, null, 2));

  const md = [
    '# Hotel Industry Master Audit Report',
    '',
    `Generated: ${reportData.generatedAt}`,
    '',
    `**${passCount} PASS · ${warnCount} WARN · ${failCount} FAIL** (${results.length} test clusters)`,
    '',
    '| # | Chức năng | Trạng thái | Thời gian | Ghi chú |',
    '|---|---|---|---|---|',
    ...results.map((r, i) => `| ${i + 1} | ${r.name} | ${r.status} | ${r.ms}ms | ${r.note.replace(/\|/g, '\\|')} |`),
    '',
    '## Findings (Spec vs. Implementation Gaps)',
    ...findings.map((f) => `- ${f}`),
  ].join('\n');
  fs.writeFileSync(REPORT_MD, md);

  console.log('\n=== TEST EXECUTION MATRIX ===');
  console.table(results.map((r) => ({ Test: r.name, Status: r.status, 'Time (ms)': r.ms })));
  console.log(`\nTổng kết: ${passCount} PASS · ${warnCount} WARN · ${failCount} FAIL`);
  console.log(`\nBáo cáo: ${REPORT_MD}`);
  console.log(`Ảnh chụp: ${SCREEN_DIR}`);
}

main().catch((err) => {
  console.error('AUDIT SCRIPT CRASHED:', err);
  process.exit(1);
});
