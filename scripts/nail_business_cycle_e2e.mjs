/**
 * scripts/nail_business_cycle_e2e.mjs
 *
 * MASTER E2E — mô phỏng 1 chu trình kinh doanh thật của tiệm Nails, đúng 4 bước theo yêu cầu:
 *   1) Khách đặt lịch công khai (chọn dịch vụ + thợ, hôm nay)
 *   2) Check-in từ /calendar -> "Vào vé" trên POS (không gõ tay lại)
 *   3) Thêm tip mặt/thẻ, xác nhận thanh toán
 *   4) Đối soát: order_id thật trong DB, chamcong tăng đúng số, phiếu lương 3 dòng khớp từng xu
 *
 * Chạy:  node scripts/nail_business_cycle_e2e.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { execFileSync } from 'child_process';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';

// Đối soát DB trực tiếp qua chính mongo_client.py của app (pymongo) thay vì thêm dependency
// Node MongoDB driver mới vào package.json chỉ cho 1 script test — python + pymongo đã sẵn có
// và đã được dùng để verify DB thật trong audit trước đó cùng session.
function dbQuery(...args) {
  const out = execFileSync('python', ['scripts/_e2e_db_helper.py', ...args], { encoding: 'utf-8' });
  // mongo_client.py in ("[*] Reading environment parameters...", "[*] MongoDB client connected...")
  // print thêm vài dòng log ra stdout ngay lúc import — JSON thật luôn là dòng CUỐI CÙNG.
  const lines = out.trim().split('\n');
  return JSON.parse(lines[lines.length - 1]);
}

const SCREEN_DIR = path.resolve('audit-results/screenshots/nail_business_cycle_e2e');
const REPORT_MD = path.resolve('audit-results/nail_business_cycle_e2e_report.md');
fs.mkdirSync(SCREEN_DIR, { recursive: true });

const steps = [];
function record(name, status, note = '') {
  steps.push({ name, status, note });
  const icon = status === 'PASS' ? '✅' : status === 'WARN' ? '⚠️' : '❌';
  console.log(`${icon} [${status}] ${name}${note ? ' — ' + note : ''}`);
}
async function shot(page, name) {
  await page.screenshot({ path: path.join(SCREEN_DIR, name), fullPage: true });
}
// BUG THẬT đã vá (phát hiện khi retest sau UI polish): toISOString() luôn trả về ngày theo UTC,
// trong khi giờ/phút của lịch hẹn (Bước 1) lại lấy từ getHours()/getMinutes() theo GIỜ ĐỊA
// PHƯƠNG — máy chạy ở UTC+7 nên gần nửa đêm giờ VN, 2 nguồn ngày/giờ LỆCH NHAU 1 ngày, ghép ra
// 1 chuỗi datetime-local đã ở QUÁ KHỨ so với "bây giờ" thật (server + input min chặn im lặng,
// không request nào bắn ra, waitForResponse timeout vô lý dù luồng đặt lịch hoàn toàn không có
// bug). Dùng ngày ĐỊA PHƯƠNG nhất quán (giống todayVN()) thay vì UTC.
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function todayVN() {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`;
}

async function main() {
  console.log('=== NAIL BUSINESS CYCLE E2E — bắt đầu ===\n');

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('dialog', async (d) => { await d.accept(); });

  let businessId = null;
  let appointmentId = null;
  let orderId = null;
  let checkoutResponseBody = null;

  // ============================================================
  // Đăng nhập chủ tiệm — cần business_id để build link booking công khai
  // ============================================================
  try {
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.fill('#loginEmail', EMAIL);
    await page.fill('#loginPassword', PASSWORD);
    await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
    if (page.url().includes('/login')) throw new Error('Đăng nhập thất bại.');

    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 10000 });
    await shot(page, '01_service_grid_professional.png');
    businessId = await page.evaluate(() => (typeof BUSINESS_ID !== 'undefined' ? BUSINESS_ID : null));
    record('0. Đăng nhập chủ tiệm + chụp lưới dịch vụ', businessId ? 'PASS' : 'FAIL', `business_id=${businessId}`);
  } catch (e) {
    record('0. Đăng nhập chủ tiệm', 'FAIL', e.message);
    await finalize({ browser, steps }); process.exit(1);
  }

  // ============================================================
  // BƯỚC 1 — Khách đặt lịch công khai: Acrylic Full Set + Ava Robertson, hôm nay
  // ============================================================
  let acrylicServiceId = null;
  let avaStaffId = null;
  let bookingDateStr = todayISO(); // ghi đè bằng ngày THẬT của lịch hẹn ngay dưới đây — có thể
  // khác "hôm nay" nếu random offset đẩy qua nửa đêm địa phương.
  try {
    const bookingContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const bookingPage = await bookingContext.newPage();
    await bookingPage.goto(`${BASE}/booking/nail/qr/${businessId}`, { waitUntil: 'networkidle' });

    const svcList = await bookingPage.evaluate(() => services);
    const techList = await bookingPage.evaluate(() => technicians);
    const acrylic = svcList.find((s) => /acrylic full set/i.test(s.name));
    const ava = techList.find((t) => /ava\s*robertson/i.test(t.name));
    if (!acrylic) throw new Error('Không tìm thấy dịch vụ "Acrylic Full Set" trong danh sách công khai.');
    if (!ava) throw new Error('Không tìm thấy thợ "Ava Robertson" trong danh sách công khai.');
    acrylicServiceId = acrylic.id;
    avaStaffId = ava.id;

    const customerName = 'E2E Business Cycle Khach';
    const customerPhone = '0490' + String(Date.now()).slice(-6);
    await bookingPage.fill('#cus_name', customerName);
    await bookingPage.fill('#cus_phone', customerPhone);
    await bookingPage.fill('#cus_address', '456 Business Cycle St');
    await bookingPage.selectOption('#cus_service', String(acrylic.id));
    await bookingPage.waitForTimeout(150);
    const staffVisible = await bookingPage.locator('#staffFieldWrap').isVisible().catch(() => false);
    if (staffVisible) await bookingPage.selectOption('#cus_staff', String(ava.id));

    // Giờ hẹn: HÔM NAY, +1 giờ tính từ hiện tại (không được ở quá khứ — JS chặn) CỘNG random
    // 1-58 phút — book_appointment() chặn double-booking đúng thợ/đúng phút (đã thấy thật khi
    // chạy lại script trong cùng giờ), nên mỗi lần chạy phải rơi vào 1 slot khác nhau.
    const randomOffsetMin = 1 + Math.floor(Math.random() * 58);
    const now = new Date(Date.now() + 60 * 60 * 1000 + randomOffsetMin * 60 * 1000);
    // Lấy NGUYÊN cả ngày/giờ/phút từ CÙNG 1 object `now` (địa phương) — không gọi todayISO()
    // riêng ở đây nữa, vì nó phản ánh "hôm nay" tại THỜI ĐIỂM GỌI, có thể khác ngày với `now`
    // nếu offset đẩy qua nửa đêm địa phương (chính là bug gốc đã vá phía trên).
    bookingDateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    const dtLocal = `${bookingDateStr}T${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    await bookingPage.fill('#cus_datetime', dtLocal);
    await bookingPage.fill('#cus_note', 'E2E business-cycle test.');

    const [apptResp] = await Promise.all([
      bookingPage.waitForResponse((r) => r.url().includes('/create_appointment') && r.request().method() === 'POST', { timeout: 10000 }),
      bookingPage.click('#btnSubmit'),
    ]);
    const apptBody = await apptResp.json().catch(() => null);
    if (!apptBody?.success || !apptBody?.id) throw new Error('Đặt lịch thất bại: ' + JSON.stringify(apptBody));
    appointmentId = apptBody.id;
    await shot(bookingPage, '02_booking_submitted.png');
    await bookingContext.close();

    record('1. Khách đặt lịch công khai (Acrylic Full Set + Ava Robertson, hôm nay)', 'PASS',
      `appointment_id=${appointmentId}, service_id=${acrylicServiceId}, staff_id=${avaStaffId}`);
  } catch (e) {
    record('1. Khách đặt lịch công khai', 'FAIL', e.message);
    await finalize({ browser, steps }); process.exit(1);
  }

  // ============================================================
  // BƯỚC 2a — Check-in từ /calendar
  // ============================================================
  try {
    await page.goto(`${BASE}/calendar?date=${bookingDateStr}`, { waitUntil: 'networkidle' });
    const row = page.locator(`tr[data-appt-id="${appointmentId}"]`);
    await row.waitFor({ timeout: 8000 });
    await row.locator('button:has-text("Check-in")').click();
    await page.waitForTimeout(400);
    const badgeText = await row.locator('[data-status-cell]').innerText();
    await shot(page, '03_calendar_checked_in.png');

    const pass = /Check-in/i.test(badgeText);
    record('2a. Check-in lịch hẹn trên /calendar', pass ? 'PASS' : 'FAIL', `status badge: "${badgeText.trim()}"`);
  } catch (e) {
    record('2a. Check-in lịch hẹn trên /calendar', 'FAIL', e.message);
  }

  // ============================================================
  // BƯỚC 2b — POS: "Vào vé" từ panel Checked-In (không gõ tay)
  // ============================================================
  try {
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 10000 });
    await page.evaluate(() => openCheckedInModal());
    await page.waitForSelector('#checkedInModal.active', { timeout: 5000 });
    await page.waitForTimeout(400);

    const loadBtn = page.locator('#checkedInList button', { hasText: /Load Ticket|Vào Vé/i }).first();
    await loadBtn.waitFor({ timeout: 5000 });
    await loadBtn.click();
    await page.waitForTimeout(400);

    const cartCount = await page.locator('#cartItems .cart-item').count();
    const firstLineTech = await page.locator('#cartItems .cart-item select').first().inputValue();
    const firstLineName = (await page.locator('#cartItems .cart-item').first().innerText());
    await shot(page, '04_pos_ticket_loaded_from_checkin.png');

    const pass = cartCount >= 1 && firstLineTech === avaStaffId && /acrylic/i.test(firstLineName);
    record('2b. POS "Vào vé" — dịch vụ + thợ tự động vào giỏ', pass ? 'PASS' : 'FAIL',
      `cart_count=${cartCount}, assigned_tech=${firstLineTech} (expected ${avaStaffId})`);
  } catch (e) {
    record('2b. POS "Vào vé"', 'FAIL', e.message);
    await finalize({ browser, steps }); process.exit(1);
  }

  // ============================================================
  // Đối soát TRƯỚC thanh toán — snapshot chamcong hôm nay của Ava Robertson
  // ============================================================
  const beforeAgg = sumChamcongToday(businessId, avaStaffId);

  // ============================================================
  // BƯỚC 3 — Tip mặt $10 + Tip thẻ $5, xác nhận thanh toán
  // ============================================================
  try {
    await page.evaluate(() => switchLeftTab('ticket'));
    await page.waitForTimeout(200);
    await page.fill('#cashTip', '10');
    await page.fill('#cardTip', '5');
    await page.locator('#cashTip').dispatchEvent('input');
    await page.locator('#cardTip').dispatchEvent('input');
    await page.waitForTimeout(200);

    // Dual Pricing (#sumCashPrice/#sumCardPrice) đã được xây và test kỹ riêng ở Test 10 của
    // nail_industry_master_audit.mjs — bước này chỉ cần xác nhận UI còn tồn tại, không lặp lại
    // toàn bộ phép kiểm chứng số học ở đó.
    const dualPricingExists = (await page.locator('#sumCashPrice, #sumCardPrice').count()) > 0;
    if (!dualPricingExists) {
      record('FINDING', 'WARN', '#sumCashPrice/#sumCardPrice không tìm thấy — kiểm tra lại Dual Pricing UI trong pos_nail.html.');
    }

    await page.click('#checkoutBtn', { force: true });
    await page.waitForSelector('#paymentModal.active', { timeout: 3000 });
    await page.click('.pay-method-btn[data-method="cash"]');
    await page.waitForTimeout(150);

    const [checkoutResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/nail_pos/checkout') && r.request().method() === 'POST', { timeout: 15000 }),
      page.click('#confirmPaymentBtn'),
    ]);
    checkoutResponseBody = await checkoutResp.json().catch(() => null);
    orderId = checkoutResponseBody?.order_id ?? null;
    await page.waitForSelector('#receiptModal.active', { timeout: 8000 });
    await shot(page, '05_payment_confirmed.png');

    const pass = checkoutResp.status() === 200 && checkoutResponseBody?.success === true && !!orderId;
    record('3. Xác nhận thanh toán (Tip mặt $10 + Tip thẻ $5)', pass ? 'PASS' : 'FAIL',
      `HTTP ${checkoutResp.status()}, order_id=${orderId}, total=${checkoutResponseBody?.total_amount}`);
  } catch (e) {
    record('3. Xác nhận thanh toán', 'FAIL', e.message);
    await finalize({ browser, steps }); process.exit(1);
  }

  // ============================================================
  // BƯỚC 4a — Đối soát Database trực tiếp (order_id thật, không phải RAM)
  // ============================================================
  try {
    const orderDoc = dbQuery('get_order', String(orderId), businessId);
    const pass = !!orderDoc && orderDoc.status === 'completed' && orderDoc.total_amount === checkoutResponseBody.total_amount;
    record('4a. order_id thật trong MongoDB (không chỉ RAM)', pass ? 'PASS' : 'FAIL',
      `db.orders: status=${orderDoc?.status}, total_amount=${orderDoc?.total_amount}`);
  } catch (e) {
    record('4a. Đối soát DB orders', 'FAIL', e.message);
  }

  // ============================================================
  // BƯỚC 4b — chamcong tăng đúng số (commission + tip mặt/thẻ TÁCH RIÊNG)
  // ============================================================
  const techPaid = checkoutResponseBody?.techs_paid?.find((t) => t.ma_nv === avaStaffId);
  let afterAgg;
  try {
    afterAgg = sumChamcongToday(businessId, avaStaffId);
    const deltaCommission = round2(afterAgg.commission - beforeAgg.commission);
    const deltaTipCash = round2(afterAgg.tipCash - beforeAgg.tipCash);
    const deltaTipCard = round2(afterAgg.tipCard - beforeAgg.tipCard);

    // Lưu ý QUAN TRỌNG: tip thẻ ghi vào chamcong là NET sau phí xử lý thẻ (cc_fee_percent=3%
    // hardcode ở buildCheckoutPayload) — $5 tip thẻ khách nhập thực nhận vào chamcong là
    // $5 * (1 - 3%) = $4.85, KHÔNG PHẢI $5.00 nguyên. Đây là hành vi ĐÚNG theo thiết kế hệ
    // thống (đã có từ trước, không phải bug), không phải sai số làm tròn.
    const pass = techPaid
      && Math.abs(deltaCommission - techPaid.commission) < 0.01
      && Math.abs(deltaTipCash - techPaid.tip_cash) < 0.01
      && Math.abs(deltaTipCard - techPaid.tip_card) < 0.01;

    record('4b. db.chamcong tăng đúng: hoa hồng + tip mặt/thẻ tách riêng', pass ? 'PASS' : 'FAIL',
      `Δcommission=${deltaCommission} (kỳ vọng ${techPaid?.commission}), Δtip_cash=${deltaTipCash} (kỳ vọng ${techPaid?.tip_cash}), ` +
      `Δtip_card=${deltaTipCard} (kỳ vọng ${techPaid?.tip_card} — đã trừ phí thẻ 3% trên $5 gốc = $4.85)`);
  } catch (e) {
    record('4b. Đối soát db.chamcong', 'FAIL', e.message);
  }

  // ============================================================
  // BƯỚC 4c — Phiếu lương (Cash Payout / Check-Direct Deposit / Tax Withheld) khớp từng xu
  // ============================================================
  try {
    await page.goto(`${BASE}/chamcong/nail`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#employeeGrid', { timeout: 8000 });
    await page.locator(`#employeeGrid [data-ma-nv="${avaStaffId}"] [data-action="open"]`).first().click();
    await page.waitForSelector('#screen_pos.active', { timeout: 5000 });
    await page.waitForTimeout(900); // loadPayrollMonthSummary() async

    const todayKey = todayVN();
    const dayCellHasData = await page.locator(`#payrollCalendarGrid button:not([disabled])`, { hasText: new RegExp(`^${parseInt(todayKey)}$`) }).count();
    await page.evaluate((key) => selectPayrollDay(key), todayKey);
    await page.waitForTimeout(300);
    // #paystubPanel nằm TRONG 1 container overflow-y-auto riêng (card bên trái) — screenshot
    // fullPage của Playwright chỉ mở rộng theo scroll của TRANG NGOÀI CÙNG, không tự cuộn các
    // vùng overflow lồng bên trong, nên phải tự cuộn phần tử này vào khung hình trước khi chụp.
    await page.locator('#paystubPanel').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
    await shot(page, '06_payroll_reconciliation.png');

    const paystubVisible = await page.locator('#paystubPanel').isVisible();
    const cashPayoutText = await page.locator('#paystubCashPayout').innerText();
    const checkDepositText = await page.locator('#paystubCheckDeposit').innerText();
    const taxWithheldText = await page.locator('#paystubTaxWithheld').innerText();
    const netTotalText = await page.locator('#paystubNetTotal').innerText();

    const num = (s) => parseFloat(String(s).replace(/[^0-9.-]/g, ''));
    const TAX_RATE = 15;
    const expectedCashPayout = round2(afterAgg.tipCash);
    const expectedCheckGross = round2(afterAgg.commission + afterAgg.tipCard);
    const expectedTax = round2(expectedCheckGross * TAX_RATE / 100);
    const expectedCheckNet = round2(expectedCheckGross - expectedTax);
    const expectedNetTotal = round2(expectedCashPayout + expectedCheckNet);

    // paystubTaxWithheld hiển thị CÓ dấu trừ ("-$92.78") vì đây là khoản khấu trừ trên UI —
    // đúng thiết kế UX (khoản trừ nên hiện âm), nên so khớp trị tuyệt đối thay vì giá trị có dấu.
    const pass = paystubVisible
      && Math.abs(num(cashPayoutText) - expectedCashPayout) < 0.02
      && Math.abs(num(checkDepositText) - expectedCheckNet) < 0.02
      && Math.abs(Math.abs(num(taxWithheldText)) - expectedTax) < 0.02
      && Math.abs(num(netTotalText) - expectedNetTotal) < 0.02;

    record('4c. Phiếu lương 3 dòng khớp từng xu (Cash Payout / Check-Deposit / Tax Withheld)', pass ? 'PASS' : 'FAIL',
      `Panel hiện: cash=${cashPayoutText}, check=${checkDepositText}, tax=${taxWithheldText}, net=${netTotalText} — ` +
      `kỳ vọng: cash=$${expectedCashPayout}, check=$${expectedCheckNet}, tax=$${expectedTax}, net=$${expectedNetTotal} (thuế ước tính ${TAX_RATE}%, không phải engine thuế thật)`);
  } catch (e) {
    record('4c. Phiếu lương', 'FAIL', e.message);
  }

  record('Console errors trong toàn bộ chu trình', consoleErrors.length === 0 ? 'PASS' : 'WARN', `${consoleErrors.length} lỗi: ${consoleErrors.slice(0, 3).join(' | ')}`);

  await finalize({ browser, steps });
}

function sumChamcongToday(businessId, maNv) {
  return dbQuery('sum_chamcong', businessId, maNv, todayVN());
}
function round2(n) { return Math.round((n + Number.EPSILON) * 100) / 100; }

async function finalize({ browser, steps }) {
  await browser.close();
  const passCount = steps.filter((s) => s.status === 'PASS').length;
  const warnCount = steps.filter((s) => s.status === 'WARN').length;
  const failCount = steps.filter((s) => s.status === 'FAIL').length;

  const md = [
    '# Nail Business Cycle E2E — Booking → Check-in → POS → Payroll',
    '', `Generated: ${new Date().toISOString()}`, '',
    `**${passCount} PASS · ${warnCount} WARN · ${failCount} FAIL**`, '',
    '| Step | Status | Note |', '|---|---|---|',
    ...steps.map((s) => `| ${s.name} | ${s.status} | ${s.note.replace(/\|/g, '\\|')} |`),
  ].join('\n');
  fs.writeFileSync(REPORT_MD, md);

  console.log('\n=== KẾT QUẢ ===');
  console.table(steps.map((s) => ({ Step: s.name, Status: s.status })));
  console.log(`\nTổng kết: ${passCount} PASS · ${warnCount} WARN · ${failCount} FAIL`);
  console.log(`Báo cáo: ${REPORT_MD}`);
  console.log(`Ảnh chụp: ${SCREEN_DIR}`);

  if (failCount > 0) process.exitCode = 1;
}

main().catch((err) => {
  console.error('E2E SCRIPT CRASHED:', err);
  process.exit(1);
});
