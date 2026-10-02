/**
 * scripts/karaoke_industry_master_audit.mjs
 *
 * QA Master Audit — Karaoke Industry vertical (tính giờ phòng theo /api/karaoke/rooms/*,
 * đặt phòng công khai qua QR, quản trị đặt phòng).
 *
 * Chạy:  node scripts/karaoke_industry_master_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Mọi selector đã xác minh TRỰC TIẾP bằng grep + đọc code thật trong templates/karaoke.html,
 * templates/karaoke_reservation_public.html, app.py — KHÔNG suy đoán.
 * Lưu ý: route /toggle_room/<id> trong app.py là DEAD CODE (karaoke.html thật sự dùng
 * /api/karaoke/rooms/<id>/start và /checkout) — xem FINDINGS_LOG.md.
 * Module "pos_ordering" khai báo trong INDUSTRY_CONFIG['karaoke'] KHÔNG có UI tương ứng trong
 * karaoke.html (không có giỏ hàng gọi đồ uống) — chỉ tính tiền phòng theo giờ.
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.KARAOKE_DEMO_EMAIL || 'demo.karaoke.071443@bitpawdemo.com';
const PASSWORD = process.env.KARAOKE_DEMO_PASSWORD || 'DemoBitPaw2026!';
const BUSINESS_ID = process.env.KARAOKE_DEMO_BUSINESS_ID || '0cc47d38-b306-46f3-9da1-cdf2d840d79b';

const SCREEN_DIR = path.resolve('audit-results/screenshots/karaoke_master_audit');
const REPORT_JSON = path.resolve('audit-results/karaoke_master_audit_report.json');
const REPORT_MD = path.resolve('audit-results/karaoke_master_audit_report.md');

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
  console.log('=== KARAOKE INDUSTRY MASTER AUDIT — bắt đầu ===\n');
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
  // TEST 1 — Đăng nhập & Khởi tạo màn hình Phòng Karaoke
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

    await page.goto(`${BASE}/karaoke`, { waitUntil: 'networkidle' });
    await page.waitForSelector('[data-room-id]', { timeout: 10000 });

    const roomCount = await page.locator('[data-room-id]').count();
    await shot(page, '01_karaoke_launch.png');

    const errorsExcludingFavicon = consoleErrors.filter((e) => !/favicon/i.test(e));
    const pass = errorsExcludingFavicon.length === 0 && networkErrors.length === 0 && roomCount > 0;
    record('1. Đăng nhập & Khởi tạo Phòng Karaoke', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `console_errors=${consoleErrors.length}, network_5xx=${networkErrors.length}, rooms=${roomCount}`);
  } catch (e) {
    record('1. Đăng nhập & Khởi tạo Phòng Karaoke', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_karaoke_launch_FAILED.png').catch(() => {});
    await finalize({ browser, results, findings });
    process.exit(1);
  }

  // ============================================================
  // TEST 2 — Mở phòng (Start), chốt phòng (Checkout) qua API thật
  // ============================================================
  t0 = Date.now();
  try {
    // Tìm 1 phòng đang "Trống" để Start (phòng demo có thể còn đang "Đang chơi" từ lượt chạy trước)
    let emptyRoom = page.locator('[data-room-id][data-status="Trống"]').first();
    if ((await emptyRoom.count()) === 0) {
      // Không còn phòng trống -> chốt phòng đầu tiên đang chơi để giải phóng, rồi dùng chính nó
      const busyRoom = page.locator('[data-room-id][data-status="Đang chơi"]').first();
      const busyRoomId = await busyRoom.getAttribute('data-room-id');
      await page.evaluate((id) => window.endRoom(id, ''), busyRoomId);
      await page.waitForTimeout(800);
      await page.reload({ waitUntil: 'networkidle' });
      await page.waitForSelector('[data-room-id]', { timeout: 10000 });
      emptyRoom = page.locator('[data-room-id][data-status="Trống"]').first();
    }
    const roomId = await emptyRoom.getAttribute('data-room-id');
    const roomName = await emptyRoom.locator('h3, .room-name, [class*=name]').first().innerText().catch(() => `Room ${roomId}`);

    const [startResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes(`/api/karaoke/rooms/${roomId}/start`) && res.request().method() === 'POST', { timeout: 10000 }),
      page.locator(`.start-room[data-id="${roomId}"]`).click(),
    ]);
    const startStatus = startResp.status();
    const startBody = await startResp.json().catch(() => null);
    await page.waitForTimeout(500);
    await shot(page, '02a_karaoke_room_started.png');

    // Chốt phòng ngay (thời gian tối thiểu tính là 15 phút theo logic server dù vừa mở)
    await page.locator(`.checkout-room[data-id="${roomId}"]`).click();
    await page.waitForSelector('#checkoutModal.active', { timeout: 3000 });
    await page.fill('#custPhone', '0495' + String(Date.now()).slice(-6));
    await shot(page, '02b_karaoke_checkout_modal.png');

    const [checkoutResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes(`/api/karaoke/rooms/${roomId}/checkout`) && res.request().method() === 'POST', { timeout: 10000 }),
      page.click('#confirmCheckoutBtn'),
    ]);
    const checkoutStatus = checkoutResp.status();
    const checkoutBody = await checkoutResp.json().catch(() => null);
    await page.waitForTimeout(500);
    await shot(page, '02c_karaoke_checkout_success.png');

    const pass = startStatus === 200 && startBody?.success === true && checkoutStatus === 200 && checkoutBody?.success === true && !!checkoutBody?.order_id;
    record('2. Mở Phòng & Chốt Phòng (tính giờ tự động)', pass ? 'PASS' : 'FAIL', Date.now() - t0,
      `Phòng "${roomName}" (id=${roomId}). Start: HTTP ${startStatus}. Checkout: HTTP ${checkoutStatus}, order_id=${checkoutBody?.order_id}, total_amount=${checkoutBody?.total_amount}.`);
  } catch (e) {
    record('2. Mở Phòng & Chốt Phòng (tính giờ tự động)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_karaoke_room_lifecycle_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 3 — Đặt phòng công khai qua QR (khách vãng lai) + xuất hiện trong /karaoke/reservations
  // ============================================================
  t0 = Date.now();
  let bookingContext = null;
  try {
    bookingContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const bookingPage = await bookingContext.newPage();
    const bookingConsoleErrors = [];
    bookingPage.on('console', (msg) => { if (msg.type() === 'error') bookingConsoleErrors.push(msg.text()); });

    await bookingPage.goto(`${BASE}/karaoke/reserve/${BUSINESS_ID}`, { waitUntil: 'networkidle' });
    await bookingPage.waitForSelector('#reserveForm', { timeout: 8000 });

    const customerName = 'QA Audit Karaoke Khach';
    const customerPhone = '0496' + String(Date.now()).slice(-6);
    await bookingPage.fill('input[name="name"]', customerName);
    await bookingPage.fill('input[name="phone"]', customerPhone);
    await bookingPage.fill('input[name="party_size"]', '6');
    const futureDate = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    await bookingPage.fill('input[name="date"]', futureDate);
    await bookingPage.fill('input[name="time"]', '20:00');
    await bookingPage.selectOption('select[name="duration_hours"]', '3');
    await bookingPage.fill('textarea[name="note"]', 'Đặt qua audit script Karaoke — kiểm tra luồng đặt phòng công khai.');
    await shot(bookingPage, '03a_karaoke_reservation_form_filled.png');

    const [reserveResp] = await Promise.all([
      bookingPage.waitForResponse((res) => res.url().includes(`/api/public/karaoke_reservations/${BUSINESS_ID}`) && res.request().method() === 'POST', { timeout: 10000 }),
      bookingPage.click('#submitBtn'),
    ]);
    const reserveStatus = reserveResp.status();
    const reserveBody = await reserveResp.json().catch(() => null);
    await bookingPage.waitForSelector('#successCard:not(.hidden)', { timeout: 5000 }).catch(() => {});
    await shot(bookingPage, '03b_karaoke_reservation_success.png');

    await page.goto(`${BASE}/karaoke/reservations?date=${futureDate}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    const adminBodyText = await page.locator('body').innerText();
    const reservationVisible = adminBodyText.includes(customerPhone) || adminBodyText.includes(customerName);
    await shot(page, '03c_karaoke_reservations_admin_side.png');

    const pass = reserveStatus === 200 && reserveBody?.success === true && !!reserveBody?.id && reservationVisible && bookingConsoleErrors.length === 0;
    record('3. Đặt Phòng Công Khai QR + Hiện Trên Trang Quản Trị', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `POST /api/public/karaoke_reservations/${BUSINESS_ID}: HTTP ${reserveStatus}, id=${reserveBody?.id}. Hiện trên /karaoke/reservations: ${reservationVisible}. Console errors trang khách: ${bookingConsoleErrors.length}.`);

    if (!reservationVisible) {
      finding('Đặt phòng Karaoke qua QR ghi API thành công (success:true + id) nhưng KHÔNG thấy xuất hiện trên /karaoke/reservations khi lọc đúng ngày đặt — kiểm tra lại query date-range hoặc format reserved_time.');
    }
  } catch (e) {
    record('3. Đặt Phòng Công Khai QR + Hiện Trên Trang Quản Trị', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_karaoke_reservation_FAILED.png').catch(() => {});
  } finally {
    if (bookingContext) await bookingContext.close().catch(() => {});
  }

  // ============================================================
  // TEST 4 — Chấm công Karaoke (/chamcong_karaoke) + Module dùng chung
  // ============================================================
  t0 = Date.now();
  try {
    const errorsBefore = consoleErrors.length;
    await page.goto(`${BASE}/chamcong_karaoke`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    const bodyText = await page.locator('body').innerText();
    const newErrors = consoleErrors.length - errorsBefore;
    await shot(page, '04_karaoke_chamcong.png');

    const sharedPages = ['/customers', '/ai_bot', '/nhanvien', '/report'];
    const sharedResults = [];
    for (const url of sharedPages) {
      const resp = await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle' }).catch((e) => ({ _err: e.message }));
      const status = resp && resp.status ? resp.status() : null;
      sharedResults.push(`${url}=${status ?? 'ERR'}`);
    }

    const allSharedOk = sharedResults.every((r) => r.endsWith('=200'));
    const pass = bodyText.length > 50 && newErrors === 0 && allSharedOk;
    record('4. Chấm Công Karaoke + Module Dùng Chung', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Chấm công: ${bodyText.length} ký tự, ${newErrors} lỗi console mới. Shared: ${sharedResults.join(', ')}`);
  } catch (e) {
    record('4. Chấm Công Karaoke + Module Dùng Chung', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '04_karaoke_chamcong_FAILED.png').catch(() => {});
  }

  finding('Module "pos_ordering" khai báo trong INDUSTRY_CONFIG[\'karaoke\'] không có UI tương ứng trong karaoke.html — không có giỏ hàng gọi đồ uống/đồ ăn trong lúc chơi, chỉ tính tiền phòng theo giờ khi chốt phòng. Ghi nhận là spec-vs-implementation gap, không phải bug.');

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
    '# Karaoke Industry Master Audit Report',
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
