/**
 * scripts/fnb_industry_master_audit.mjs
 *
 * QA Master Audit — F&B Industry vertical (POS bàn ăn, Bếp real-time, QR tự gọi món,
 * Đặt bàn công khai, Thanh toán cash/card/split, Chấm công/Payroll).
 *
 * Chạy:  node scripts/fnb_industry_master_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Mọi selector trong script này đã được xác minh TRỰC TIẾP bằng grep + đọc code thật
 * trong templates/pos.html, templates/payment_pending.html, templates/kitchen_display.html,
 * templates/table_order.html, templates/table_reservation_public.html — KHÔNG suy đoán.
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.FNB_DEMO_EMAIL || 'demo.fnb.343602@bitpawdemo.com';
const PASSWORD = process.env.FNB_DEMO_PASSWORD || 'DemoBitPaw2026!';
const BUSINESS_ID = process.env.FNB_DEMO_BUSINESS_ID || '39821fa8-e42a-4052-bc9d-eb061eaaae11';

const SCREEN_DIR = path.resolve('audit-results/screenshots/fnb_master_audit');
const REPORT_JSON = path.resolve('audit-results/fnb_master_audit_report.json');
const REPORT_MD = path.resolve('audit-results/fnb_master_audit_report.md');

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
  console.log('=== F&B INDUSTRY MASTER AUDIT — bắt đầu ===\n');
  console.log(`Target: ${BASE}   Account: ${EMAIL}   Business: ${BUSINESS_ID}\n`);

  const consoleErrors = [];
  const networkErrors = [];
  let paidOrderTxnId = null;
  let firstTableId = null;
  let firstTableName = null;

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('response', (res) => { if (res.status() >= 500) networkErrors.push(`${res.status()} ${res.request().method()} ${res.url()}`); });
  page.on('dialog', async (d) => { await d.accept(); });

  // ============================================================
  // TEST 1 — Đăng nhập & Khởi tạo POS F&B (bàn + menu)
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

    await page.goto(`${BASE}/pos`, { waitUntil: 'networkidle' });
    await page.waitForSelector('.table-item', { timeout: 10000 });

    const tableCount = await page.locator('.table-item').count();
    const menuCount = await page.locator('[data-product-id]').count();

    // Xác nhận bàn tiếng Việt có dấu ("Bàn 1"...) hiển thị đúng — regression check cho
    // bug thật đã fix (stripDiacritics) trong lượt audit này.
    const vietnameseTableVisible = await page.locator('.table-item', { hasText: /Bàn/ }).count();
    if (vietnameseTableVisible === 0) {
      finding('Không thấy bàn tên tiếng Việt có dấu ("Bàn ...") nào hiển thị trên lưới bàn — kiểm tra lại fix stripDiacritics() trong pos.html.');
    }

    await shot(page, '01_pos_fnb_launch.png');

    const pass = consoleErrors.length === 0 && networkErrors.length === 0 && tableCount > 0 && menuCount > 0 && vietnameseTableVisible > 0;
    record('1. Đăng nhập & Khởi tạo POS F&B', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `console_errors=${consoleErrors.length}, network_5xx=${networkErrors.length}, tables=${tableCount}, menu_items=${menuCount}, bàn_tiếng_việt_hiển_thị=${vietnameseTableVisible}`);
  } catch (e) {
    record('1. Đăng nhập & Khởi tạo POS F&B', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_pos_fnb_launch_FAILED.png').catch(() => {});
    await finalize({ browser, results, findings });
    process.exit(1);
  }

  // ============================================================
  // TEST 2 — Chọn bàn, thêm món vào order (qua modal số lượng)
  // ============================================================
  t0 = Date.now();
  try {
    const firstTable = page.locator('.table-item').first();
    firstTableId = await firstTable.getAttribute('data-table-id');
    firstTableName = await firstTable.getAttribute('data-table-name');
    await firstTable.click();
    await page.waitForTimeout(400);

    // Thêm 2 món khác nhau qua modal orderModal (mở khi click [data-product-id])
    const products = page.locator('[data-product-id]');
    const productCount = await products.count();
    const addCount = Math.min(2, productCount);
    for (let i = 0; i < addCount; i++) {
      await products.nth(i).click();
      await page.waitForSelector('#orderModal.active', { timeout: 3000 });
      await page.click('#increaseQty'); // qty = 2
      await page.click('#confirmOrderBtn');
      await page.waitForTimeout(700);
    }

    await shot(page, '02_fnb_table_selected_items_added.png');

    const checkoutSectionVisible = await page.locator('#orderCheckoutSection').isVisible().catch(() => false);
    const pass = !!firstTableId && addCount > 0 && checkoutSectionVisible;
    record('2. Chọn Bàn & Thêm Món Vào Order', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Bàn "${firstTableName}" (id=${firstTableId}). Đã thêm ${addCount} món (mỗi món x2). Khu vực Checkout hiện: ${checkoutSectionVisible}.`);
  } catch (e) {
    record('2. Chọn Bàn & Thêm Món Vào Order', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_fnb_add_items_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 3 — Thanh toán tiền mặt qua luồng thật: /api/payment/start -> /payment_pending -> /api/payment/confirm
  // ============================================================
  t0 = Date.now();
  try {
    // Đảm bảo phương thức "Tiền mặt" đang active (mặc định)
    await page.click('.pos-pm-btn[data-method="cash"]');
    await page.waitForTimeout(150);

    const [startResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/payment/start') && res.request().method() === 'POST', { timeout: 10000 }),
      page.click('#posCheckoutBtn'),
    ]);
    const startStatus = startResp.status();
    const startBody = await startResp.json().catch(() => null);

    await page.waitForURL(/\/payment_pending/, { timeout: 8000 });
    await shot(page, '03a_fnb_payment_pending_page.png');

    await page.waitForSelector('#confirmPaymentBtn', { timeout: 5000 });
    const [confirmResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/payment/confirm') && res.request().method() === 'POST', { timeout: 10000 }),
      page.click('#confirmPaymentBtn'),
    ]);
    const confirmStatus = confirmResp.status();
    const confirmBody = await confirmResp.json().catch(() => null);

    await page.waitForURL(/\/payment_success/, { timeout: 8000 }).catch(() => {});
    await shot(page, '03b_fnb_payment_success.png');

    paidOrderTxnId = startBody?.txn_id || null;

    const pass = (startStatus === 200) && (confirmStatus === 200) && (confirmBody?.success === true);
    record('3. Thanh Toán Tiền Mặt (payment/start -> pending -> confirm)', pass ? 'PASS' : 'FAIL', Date.now() - t0,
      `start: HTTP ${startStatus} txn_id=${paidOrderTxnId}. confirm: HTTP ${confirmStatus} success=${confirmBody?.success}. URL cuối: ${page.url()}`);
  } catch (e) {
    record('3. Thanh Toán Tiền Mặt (payment/start -> pending -> confirm)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_fnb_cash_payment_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 4 — Split payment (Chia đôi) trên 1 bàn/order mới
  // ============================================================
  t0 = Date.now();
  try {
    await page.goto(`${BASE}/pos`, { waitUntil: 'networkidle' });
    await page.waitForSelector('.table-item', { timeout: 10000 });

    // Chọn bàn thứ 2 (khác bàn vừa thanh toán ở Test 3) để tránh đụng order vừa đóng.
    const secondTable = page.locator('.table-item').nth(1);
    const secondTableId = await secondTable.getAttribute('data-table-id');
    await secondTable.click();
    await page.waitForTimeout(400);

    await page.locator('[data-product-id]').first().click();
    await page.waitForSelector('#orderModal.active', { timeout: 3000 });
    await page.click('#confirmOrderBtn');
    await page.waitForTimeout(300);

    await page.click('.pos-pm-btn[data-method="split"]');
    await page.waitForTimeout(150);
    const splitActive = await page.locator('.pos-pm-btn[data-method="split"]').evaluate((el) => el.classList.contains('active'));

    await shot(page, '04_fnb_split_payment_selected.png');

    const [startResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/payment/start') && res.request().method() === 'POST', { timeout: 10000 }),
      page.click('#posCheckoutBtn'),
    ]);
    const startStatus = startResp.status();
    const startBody = await startResp.json().catch(() => null);

    const pass = splitActive && startStatus === 200 && startBody?.success !== false;
    record('4. Chọn Phương Thức Thanh Toán Chia Đôi (Split)', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Bàn id=${secondTableId}. Nút Split active: ${splitActive}. /api/payment/start: HTTP ${startStatus}, body=${JSON.stringify(startBody).slice(0, 200)}`);
  } catch (e) {
    record('4. Chọn Phương Thức Thanh Toán Chia Đôi (Split)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '04_fnb_split_payment_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 5 — Kitchen Display (SSE real-time) nhận đơn mới từ QR khách hàng
  // ============================================================
  t0 = Date.now();
  let qrContext = null;
  try {
    const kitchenPage = await context.newPage();
    const kitchenConsoleErrors = [];
    kitchenPage.on('console', (msg) => { if (msg.type() === 'error') kitchenConsoleErrors.push(msg.text()); });
    await kitchenPage.goto(`${BASE}/kitchen_display`, { waitUntil: 'networkidle' });
    await kitchenPage.waitForSelector('#ordersContainer', { timeout: 8000 });
    const ordersBefore = await kitchenPage.locator('.order-card').count();

    // Khách quét QR (context ẩn danh mới, không cookie đăng nhập) đặt món qua /table_order
    qrContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const qrPage = await qrContext.newPage();
    const qrConsoleErrors = [];
    qrPage.on('console', (msg) => { if (msg.type() === 'error') qrConsoleErrors.push(msg.text()); });

    // table_order lấy bàn theo qr_token qua query ?table_id=<token> (xem renderTables() ở pos.html)
    await page.goto(`${BASE}/pos`, { waitUntil: 'networkidle' });
    await page.waitForSelector('.table-item', { timeout: 8000 });
    const qrLink = await page.evaluate(() => {
      const el = document.querySelector('.table-item a[target="_blank"]');
      return el ? el.getAttribute('href') : null;
    });
    if (!qrLink) throw new Error('Không lấy được link QR tự gọi món (a[target=_blank]) từ lưới bàn.');

    await qrPage.goto(qrLink, { waitUntil: 'networkidle' });
    await qrPage.waitForSelector('[data-product-id]', { timeout: 8000 });
    await qrPage.locator('.add-to-cart-btn').first().click();
    await qrPage.waitForTimeout(300);
    await qrPage.click('#cartButton');
    await qrPage.waitForTimeout(200);

    const [submitResp] = await Promise.all([
      qrPage.waitForResponse((res) => res.url().includes('/api/submit_qr_order') && res.request().method() === 'POST', { timeout: 10000 }),
      qrPage.click('#submitOrderBtn'),
    ]);
    const submitStatus = submitResp.status();
    const submitBody = await submitResp.json().catch(() => null);
    await shot(qrPage, '05a_fnb_qr_customer_order_submitted.png');

    // Đợi SSE đẩy đơn mới về Kitchen Display (không reload trang)
    await kitchenPage.waitForTimeout(3000);
    const ordersAfter = await kitchenPage.locator('.order-card').count();
    await shot(kitchenPage, '05b_fnb_kitchen_display_realtime.png');

    const pass = submitStatus === 200 && submitBody?.success !== false && ordersAfter > ordersBefore && qrConsoleErrors.length === 0;
    record('5. QR Tự Gọi Món (khách) -> Kitchen Display Real-time (SSE)', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `submit_qr_order: HTTP ${submitStatus} success=${submitBody?.success}. Kitchen orders: ${ordersBefore} -> ${ordersAfter} (không reload, chờ SSE). Console errors trang khách: ${qrConsoleErrors.length}.`);

    if (ordersAfter <= ordersBefore) {
      finding('Kitchen Display không nhận đơn mới qua SSE trong 3s sau khi khách gửi qua QR — kiểm tra lại /api/stream/kitchen (Change Streams) hoặc cơ chế fallback polling 5s.');
    }
    await kitchenPage.close();
  } catch (e) {
    record('5. QR Tự Gọi Món (khách) -> Kitchen Display Real-time (SSE)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '05_fnb_qr_kitchen_FAILED.png').catch(() => {});
  } finally {
    if (qrContext) await qrContext.close().catch(() => {});
  }

  // ============================================================
  // TEST 6 — Đặt bàn công khai (Table Reservation, khách vãng lai không đăng nhập)
  // ============================================================
  t0 = Date.now();
  let reserveContext = null;
  try {
    reserveContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const reservePage = await reserveContext.newPage();
    const reserveConsoleErrors = [];
    reservePage.on('console', (msg) => { if (msg.type() === 'error') reserveConsoleErrors.push(msg.text()); });

    await reservePage.goto(`${BASE}/reserve/${BUSINESS_ID}`, { waitUntil: 'networkidle' });
    await reservePage.waitForSelector('#reserveForm', { timeout: 8000 });

    const customerName = 'QA Audit FnB Khach';
    const customerPhone = '0492' + String(Date.now()).slice(-6);
    await reservePage.fill('input[name="name"]', customerName);
    await reservePage.fill('input[name="phone"]', customerPhone);
    await reservePage.fill('input[name="party_size"]', '4');
    const futureDate = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    await reservePage.fill('input[name="date"]', futureDate);
    await reservePage.fill('input[name="time"]', '19:00');
    await reservePage.fill('textarea[name="note"]', 'Đặt qua audit script F&B — kiểm tra luồng đặt bàn công khai.');

    await shot(reservePage, '06a_fnb_reservation_form_filled.png');

    const [reserveResp] = await Promise.all([
      reservePage.waitForResponse((res) => res.url().includes(`/api/public/reservations/${BUSINESS_ID}`) && res.request().method() === 'POST', { timeout: 10000 }),
      reservePage.click('#submitBtn'),
    ]);
    const reserveStatus = reserveResp.status();
    const reserveBody = await reserveResp.json().catch(() => null);

    await reservePage.waitForSelector('#successCard:not(.hidden)', { timeout: 5000 }).catch(() => {});
    await shot(reservePage, '06b_fnb_reservation_success.png');

    const pass = reserveStatus === 200 && reserveBody?.success !== false && reserveConsoleErrors.length === 0;
    record('6. Đặt Bàn Công Khai (khách vãng lai, không đăng nhập)', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `POST /api/public/reservations/${BUSINESS_ID}: HTTP ${reserveStatus}, body=${JSON.stringify(reserveBody).slice(0, 200)}. Console errors: ${reserveConsoleErrors.length}.`);
  } catch (e) {
    record('6. Đặt Bàn Công Khai (khách vãng lai, không đăng nhập)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '06_fnb_reservation_FAILED.png').catch(() => {});
  } finally {
    if (reserveContext) await reserveContext.close().catch(() => {});
  }

  // ============================================================
  // TEST 7 — Chấm công & Payroll F&B (hourly + tip)
  // ============================================================
  t0 = Date.now();
  try {
    const errorsBefore = consoleErrors.length;
    await page.goto(`${BASE}/chamcong_fnb`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const bodyText = await page.locator('body').innerText();
    const hasEmployeeContent = bodyText.length > 50 && !/lỗi|error|exception/i.test(bodyText.slice(0, 300));
    // So sánh DELTA lỗi console phát sinh riêng trên trang này — không tính lỗi đã có từ trước
    // (vd /favicon.ico 404 lúc load /pos ở Test 1), tránh 1 lỗi cũ dây chuyền làm WARN oan
    // mọi test chạy sau nó.
    const newErrors = consoleErrors.length - errorsBefore;

    await shot(page, '07_fnb_chamcong.png');

    const pass = hasEmployeeContent && newErrors === 0;
    record('7. Chấm Công F&B (/chamcong_fnb)', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Trang tải nội dung dài ${bodyText.length} ký tự, ${newErrors} lỗi console mới. Snippet: "${bodyText.slice(0, 150).replace(/\s+/g, ' ')}"`);
  } catch (e) {
    record('7. Chấm Công F&B (/chamcong_fnb)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '07_fnb_chamcong_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 8 — Module dùng chung cho ngách F&B (CRM, AI bot, Settings) theo INDUSTRY_CONFIG['fnb']
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
    await shot(page, '08_fnb_shared_modules.png');

    const allOk = sharedResults.every((r) => r.endsWith('=200'));
    record('8. Module Dùng Chung Cho F&B (CRM/AI Bot/Nhân Viên/Báo Cáo)', allOk ? 'PASS' : 'WARN', Date.now() - t0,
      sharedResults.join(', '));
  } catch (e) {
    record('8. Module Dùng Chung Cho F&B (CRM/AI Bot/Nhân Viên/Báo Cáo)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '08_fnb_shared_modules_FAILED.png').catch(() => {});
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
    '# F&B Industry Master Audit Report',
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
