/**
 * scripts/spa_industry_master_audit.mjs
 *
 * QA Master Audit — Spa Industry vertical (Dịch vụ + giỏ hàng trên /spa, thanh toán qua
 * /api/sales/checkout, đặt lịch công khai qua QR /booking/qr/<spa_id>, chấm công).
 *
 * Chạy:  node scripts/spa_industry_master_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Mọi selector trong script này đã được xác minh TRỰC TIẾP bằng grep + đọc code thật trong
 * templates/spa.html, templates/booking.html, blueprints/spa_bp.py — KHÔNG suy đoán.
 * Lưu ý: Spa KHÔNG dùng chung pos.html với F&B/Retail — có UI giỏ hàng + checkout riêng
 * (spa.html), và route checkout_spa() trong spa_bp.py là DEAD CODE (không template nào gọi tới,
 * spa.html thật sự POST /api/sales/checkout) — xem FINDINGS_LOG.md.
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.SPA_DEMO_EMAIL || 'demo.spa.596348@bitpawdemo.com';
const PASSWORD = process.env.SPA_DEMO_PASSWORD || 'DemoBitPaw2026!';
const BUSINESS_ID = process.env.SPA_DEMO_BUSINESS_ID || '3cd48d09-8028-486d-82da-038db3ac2892';

const SCREEN_DIR = path.resolve('audit-results/screenshots/spa_master_audit');
const REPORT_JSON = path.resolve('audit-results/spa_master_audit_report.json');
const REPORT_MD = path.resolve('audit-results/spa_master_audit_report.md');

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
  console.log('=== SPA INDUSTRY MASTER AUDIT — bắt đầu ===\n');
  console.log(`Target: ${BASE}   Account: ${EMAIL}   Business: ${BUSINESS_ID}\n`);

  const consoleErrors = [];
  const networkErrors = [];
  let checkoutOrderId = null;

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('response', (res) => { if (res.status() >= 500) networkErrors.push(`${res.status()} ${res.request().method()} ${res.url()}`); });
  page.on('dialog', async (d) => { await d.accept(); });

  // ============================================================
  // TEST 1 — Đăng nhập & Khởi tạo POS Spa (danh sách dịch vụ)
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

    await page.goto(`${BASE}/spa`, { waitUntil: 'networkidle' });
    await page.waitForSelector('.product-card', { timeout: 10000 });

    const serviceCount = await page.locator('.product-card').count();
    await shot(page, '01_spa_launch.png');

    const pass = consoleErrors.length === 0 && networkErrors.length === 0 && serviceCount > 0;
    record('1. Đăng nhập & Khởi tạo POS Spa', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `console_errors=${consoleErrors.length}, network_5xx=${networkErrors.length}, services=${serviceCount}`);
  } catch (e) {
    record('1. Đăng nhập & Khởi tạo POS Spa', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_spa_launch_FAILED.png').catch(() => {});
    await finalize({ browser, results, findings });
    process.exit(1);
  }

  // ============================================================
  // TEST 2 — Thêm dịch vụ vào giỏ, mở modal Checkout
  // ============================================================
  t0 = Date.now();
  try {
    const cards = page.locator('.product-card');
    const count = await cards.count();
    const addCount = Math.min(2, count);
    for (let i = 0; i < addCount; i++) {
      await cards.nth(i).locator('.btn-add-cart').click();
      await page.waitForTimeout(200);
    }

    await page.click('#cartIcon');
    await page.waitForTimeout(200);
    const cartLineCount = await page.locator('#cartItemsList .cart-item').count();
    await shot(page, '02_spa_cart_added.png');

    await page.click('#openCheckoutModalBtn');
    await page.waitForTimeout(300);
    const modalVisible = await page.locator('#globalCheckoutModal').isVisible().catch(() => false);
    await shot(page, '02b_spa_checkout_modal.png');

    const pass = addCount > 0 && cartLineCount === addCount && modalVisible;
    record('2. Thêm Dịch Vụ Vào Giỏ & Mở Checkout', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Đã thêm ${addCount} dịch vụ, giỏ hiển thị ${cartLineCount} dòng, modal checkout hiện: ${modalVisible}.`);
  } catch (e) {
    record('2. Thêm Dịch Vụ Vào Giỏ & Mở Checkout', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_spa_cart_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 3 — Thanh toán tiền mặt qua /api/sales/checkout
  // ============================================================
  t0 = Date.now();
  try {
    await page.click('.payment-method[data-method="cash"]');
    await page.waitForTimeout(150);
    await page.fill('#custName', 'QA Audit Spa Khach');
    await page.fill('#custEmail', 'qa.audit.spa@example.com');
    await page.fill('#custPhone', '0493' + String(Date.now()).slice(-6));

    const [checkoutResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/sales/checkout') && res.request().method() === 'POST', { timeout: 15000 }),
      page.click('#finalPayBtn'),
    ]);
    const status = checkoutResp.status();
    const body = await checkoutResp.json().catch(() => null);
    checkoutOrderId = body?.order_id ?? null;

    await page.waitForSelector('#resultModal:not(.hidden)', { timeout: 8000 });
    const resTxnText = await page.locator('#resTxn').innerText();
    await shot(page, '03_spa_checkout_success.png');

    const pass = (status === 200) && body?.success !== false && !!checkoutOrderId && resTxnText.includes(String(checkoutOrderId));
    record('3. Thanh Toán Tiền Mặt (/api/sales/checkout)', pass ? 'PASS' : 'FAIL', Date.now() - t0,
      `HTTP ${status}, order_id=${checkoutOrderId}, total_amount=${body?.total_amount}, receipt hiển thị: "${resTxnText}"`);
  } catch (e) {
    record('3. Thanh Toán Tiền Mặt (/api/sales/checkout)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_spa_checkout_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 4 — Đặt lịch công khai qua QR (khách vãng lai) + cách ly đa tiệm
  // ============================================================
  t0 = Date.now();
  let bookingContext = null;
  try {
    bookingContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const bookingPage = await bookingContext.newPage();
    const bookingConsoleErrors = [];
    bookingPage.on('console', (msg) => { if (msg.type() === 'error') bookingConsoleErrors.push(msg.text()); });

    await bookingPage.goto(`${BASE}/booking/qr/${BUSINESS_ID}`, { waitUntil: 'networkidle' });
    await bookingPage.waitForTimeout(400);

    const publicData = await bookingPage.evaluate(() => ({
      serviceCount: typeof services !== 'undefined' ? services.length : -1,
      technicianCount: typeof technicians !== 'undefined' ? technicians.length : -1,
    }));
    await shot(bookingPage, '04a_spa_public_booking_page.png');

    // Regression check cho bug thật đã vá trước đây (spa_bp.py comment): thiếu spa_id từng làm
    // lộ dịch vụ của MỌI tiệm Spa trộn chung — kiểm tra KHÔNG có bằng cách gọi thiếu tham số.
    const noIdPage = await bookingContext.newPage();
    await noIdPage.goto(`${BASE}/booking`, { waitUntil: 'networkidle' });
    const noIdData = await noIdPage.evaluate(() => ({
      serviceCount: typeof services !== 'undefined' ? services.length : -1,
    }));
    await noIdPage.close();
    if (noIdData.serviceCount > 0) {
      finding(`Regression NGHIÊM TRỌNG: /booking (thiếu spa_id) trả về ${noIdData.serviceCount} dịch vụ thay vì rỗng — lỗi cách ly đa tiệm đã fix trước đây có thể bị tái phát.`);
    }

    const customerName = 'QA Audit Spa Khach Hang';
    const customerPhone = '0494' + String(Date.now()).slice(-6);
    await bookingPage.fill('#cus_name', customerName);
    await bookingPage.fill('#cus_phone', customerPhone);
    await bookingPage.fill('#cus_address', '456 Audit Test Street');
    await bookingPage.selectOption('#cus_service', { index: 1 });

    const bookDate = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000);
    const bookDateStr = bookDate.toISOString().slice(0, 10);
    const randomHour = String(9 + (Date.now() % 8)).padStart(2, '0');
    const randomMinute = String(Date.now() % 60).padStart(2, '0');
    await bookingPage.fill('#cus_datetime', `${bookDateStr}T${randomHour}:${randomMinute}`);
    await bookingPage.fill('#cus_note', 'Đặt qua audit script Spa — kiểm tra luồng QR end-to-end.');

    const [createApptResp] = await Promise.all([
      bookingPage.waitForResponse((res) => res.url().includes('/create_appointment') && res.request().method() === 'POST', { timeout: 10000 }),
      bookingPage.click('#btnSubmit'),
    ]);
    const createApptStatus = createApptResp.status();
    const createApptBody = await createApptResp.json().catch(() => null);

    await bookingPage.waitForSelector('#successContainer:not(.hidden)', { timeout: 5000 }).catch(() => {});
    const ticketText = await bookingPage.locator('#displayTicket').innerText().catch(() => '');
    await shot(bookingPage, '04b_spa_booking_success_ticket.png');

    await page.goto(`${BASE}/calendar?date=${bookDateStr}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const calendarBodyText = await page.locator('body').innerText();
    const apptVisibleInCalendar = calendarBodyText.includes(customerPhone) || calendarBodyText.includes(customerName);
    await shot(page, '04c_spa_calendar_owner_side.png');

    const pass =
      createApptStatus === 200 &&
      createApptBody?.success === true &&
      !!createApptBody?.id &&
      /TICKET-/.test(ticketText) &&
      publicData.serviceCount > 0 &&
      noIdData.serviceCount <= 0 &&
      apptVisibleInCalendar &&
      bookingConsoleErrors.length === 0;

    record('4. Đặt Lịch Công Khai QR + Cách Ly Đa Tiệm', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Business "${BUSINESS_ID}" — public page: ${publicData.serviceCount} dịch vụ / ${publicData.technicianCount} thợ. /booking (thiếu id): ${noIdData.serviceCount} dịch vụ (phải = 0). Đặt lịch HTTP ${createApptStatus}, id=${createApptBody?.id}, ticket="${ticketText}". Hiện trong /calendar chủ tiệm: ${apptVisibleInCalendar}. Console errors: ${bookingConsoleErrors.length}.`);
  } catch (e) {
    record('4. Đặt Lịch Công Khai QR + Cách Ly Đa Tiệm', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '04_spa_booking_FAILED.png').catch(() => {});
  } finally {
    if (bookingContext) await bookingContext.close().catch(() => {});
  }

  // ============================================================
  // TEST 5 — Chấm công Spa (/chamcong/spa)
  // ============================================================
  t0 = Date.now();
  try {
    const errorsBefore = consoleErrors.length;
    await page.goto(`${BASE}/chamcong/spa`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(700);
    const staffRows = await page.locator('#spaTable tr').count();
    const bodyText = await page.locator('body').innerText();
    const newErrors = consoleErrors.length - errorsBefore;
    await shot(page, '05_spa_chamcong.png');

    const pass = staffRows > 0 && newErrors === 0;
    record('5. Chấm Công Spa (/chamcong/spa)', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `${staffRows} dòng nhân viên trong bảng, ${newErrors} lỗi console mới. Nội dung dài ${bodyText.length} ký tự.`);
  } catch (e) {
    record('5. Chấm Công Spa (/chamcong/spa)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '05_spa_chamcong_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 6 — Module dùng chung cho ngách Spa (Customers/AI Bot/Nhân viên/Báo cáo)
  // ============================================================
  t0 = Date.now();
  try {
    const sharedPages = ['/customers', '/ai_bot', '/nhanvien', '/report'];
    const sharedResults = [];
    for (const url of sharedPages) {
      const resp = await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle' }).catch((e) => ({ _err: e.message }));
      const status = resp && resp.status ? resp.status() : null;
      sharedResults.push(`${url}=${status ?? 'ERR'}`);
    }
    await shot(page, '06_spa_shared_modules.png');

    const allOk = sharedResults.every((r) => r.endsWith('=200'));
    record('6. Module Dùng Chung Cho Spa (Customers/AI Bot/Nhân Viên/Báo Cáo)', allOk ? 'PASS' : 'WARN', Date.now() - t0,
      sharedResults.join(', '));
  } catch (e) {
    record('6. Module Dùng Chung Cho Spa (Customers/AI Bot/Nhân Viên/Báo Cáo)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '06_spa_shared_modules_FAILED.png').catch(() => {});
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
    '# Spa Industry Master Audit Report',
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
