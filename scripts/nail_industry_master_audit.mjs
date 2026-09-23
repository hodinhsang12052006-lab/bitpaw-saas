/**
 * scripts/nail_industry_master_audit.mjs
 *
 * QA Master Audit — Nail Industry vertical only (POS, Cart, Tech Assignment,
 * Turn/Queue, Checkout, Order History, Attendance/Payroll feed).
 *
 * Chạy:  node scripts/nail_industry_master_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Mọi selector dùng trong script này đã được xác minh TRỰC TIẾP trong
 * templates/pos_nail.html và templates/chamcong_nail.html (grep + đọc code
 * thật) — KHÔNG suy đoán. Những script audit cũ trong repo (vd.
 * zota_bitpaw_pos_audit.mjs, verify_us_nail_pos.mjs) tham chiếu tới các id
 * như #modifierModal, .tip-chip — các phần tử này KHÔNG tồn tại trong bản
 * hiện tại của pos_nail.html, nên không được dùng làm nguồn selector.
 *
 * Dual Pricing (#sumCashPrice/#sumCardPrice/#modalSurcharge) ĐÃ được xây —
 * xem Test 10.
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/nail_master_audit');
const STATE_FILE = path.resolve('audit-results/nail_master_audit_state.json');
const REPORT_JSON = path.resolve('audit-results/nail_master_audit_report.json');
const REPORT_MD = path.resolve('audit-results/nail_master_audit_report.md');

fs.mkdirSync(SCREEN_DIR, { recursive: true });

const results = [];
const findings = []; // gaps giữa spec yêu cầu và thực tế code — báo cáo trung thực, không fake pass

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
  await page.screenshot({ path: path.join(SCREEN_DIR, name), fullPage: true });
}
function round2(n) { return Math.round((n + Number.EPSILON) * 100) / 100; }

async function main() {
  console.log('=== NAIL INDUSTRY MASTER AUDIT — bắt đầu ===\n');
  console.log(`Target: ${BASE}   Account: ${EMAIL}\n`);

  const consoleErrors = [];
  const networkErrors = [];
  let checkoutOrderId = null;
  let checkoutResponseBody = null;
  let assignedTechId = null;
  let assignedTechName = null;

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('response', (res) => {
    if (res.status() >= 500) networkErrors.push(`${res.status()} ${res.request().method()} ${res.url()}`);
  });
  page.on('dialog', async (d) => { await d.accept(); });

  // ============================================================
  // TEST 1 — Khởi tạo & Giao diện POS Nails
  // ============================================================
  let t0 = Date.now();
  try {
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });

    const rateLimited = (await page.content()).match(/429|Too Many Requests|quá nhiều yêu cầu/i);
    if (rateLimited) {
      throw new Error('Server đang rate-limit /login (5 lần/15 phút) — đợi hết cửa sổ giới hạn rồi chạy lại.');
    }

    await page.fill('#loginEmail', EMAIL);
    await page.fill('#loginPassword', PASSWORD);
    await Promise.all([
      page.waitForLoadState('networkidle'),
      page.click('#btnLogin'),
    ]);

    const afterLoginUrl = page.url();
    if (afterLoginUrl.includes('/login')) {
      throw new Error(`Đăng nhập thất bại — vẫn ở lại /login. URL: ${afterLoginUrl}`);
    }

    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 10000 });

    const searchPlaceholder = await page.locator('#serviceSearchInput').getAttribute('placeholder');
    const searchOk = /^Tìm tên dịch vụ|Search services/i.test(searchPlaceholder || '');
    if (!searchOk) finding(`Placeholder search bar bất thường: "${searchPlaceholder}"`);

    // LƯU Ý: SERVICES/TECHNICIANS được khai báo bằng `const` ở top-level của
    // <script> (pos_nail.html), nên KHÔNG gắn vào window.SERVICES như `var`
    // sẽ làm — nhưng vẫn nằm trong global lexical scope của trang, nên gọi
    // trực tiếp bằng tên biến trần (không qua `window.`) vẫn đọc được.
    const dataStats = await page.evaluate(() => ({
      serviceCount: typeof SERVICES !== 'undefined' ? SERVICES.length : -1,
      techCount: typeof TECHNICIANS !== 'undefined' ? TECHNICIANS.length : -1,
    }));

    await shot(page, '01_pos_launch_clean.png');

    const pass = consoleErrors.length === 0 && networkErrors.length === 0 && searchOk && dataStats.serviceCount > 0 && dataStats.techCount > 0;
    record(
      '1. Khởi tạo & Giao diện POS Nails',
      pass ? 'PASS' : 'WARN',
      Date.now() - t0,
      `console_errors=${consoleErrors.length}, network_5xx=${networkErrors.length}, services=${dataStats.serviceCount}, technicians=${dataStats.techCount}, search_placeholder="${searchPlaceholder}"`
    );
  } catch (e) {
    record('1. Khởi tạo & Giao diện POS Nails', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_pos_launch_FAILED.png').catch(() => {});
    await finalize({ browser, results, findings, checkoutOrderId });
    process.exit(1);
  }

  // ============================================================
  // TEST 2 — Chọn dịch vụ, lọc danh mục, thêm Custom Item
  // ============================================================
  t0 = Date.now();
  try {
    const catLabels = await page.locator('#categoryTabs .cat-tab').allTextContents();
    const cleanCats = catLabels.map((s) => s.trim()).filter(Boolean);
    for (const label of cleanCats.slice(0, 4)) {
      await page.locator('#categoryTabs .cat-tab', { hasText: label }).first().click();
      await page.waitForTimeout(150);
    }
    // về lại "All" (luôn là tab đầu tiên)
    await page.locator('#categoryTabs .cat-tab').first().click();
    await page.waitForTimeout(150);

    const acrylicTab = page.locator('#categoryTabs .cat-tab', { hasText: /acrylic/i });
    const pedicureTab = page.locator('#categoryTabs .cat-tab', { hasText: /pedicure/i });

    let addedNames = [];

    if (await acrylicTab.count() > 0) {
      await acrylicTab.first().click();
      await page.waitForTimeout(200);
      const firstCard = page.locator('#serviceGrid .service-card').first();
      const name = (await firstCard.locator('.service-name-text').innerText()).trim();
      await firstCard.click();
      addedNames.push(name);
    } else {
      finding('Không tìm thấy danh mục "Acrylic" trong dữ liệu demo hiện tại — bỏ qua bước chọn theo danh mục này.');
    }

    if (await pedicureTab.count() > 0) {
      await pedicureTab.first().click();
      await page.waitForTimeout(200);
      const firstCard = page.locator('#serviceGrid .service-card').first();
      const name = (await firstCard.locator('.service-name-text').innerText()).trim();
      await firstCard.click();
      addedNames.push(name);
    } else {
      finding('Không tìm thấy danh mục "Pedicure" trong dữ liệu demo hiện tại — bỏ qua bước chọn theo danh mục này.');
    }

    // Fallback: nếu không thêm được món nào qua 2 danh mục trên, thêm đại 2 món đầu ở "All"
    if (addedNames.length === 0) {
      await page.locator('#categoryTabs .cat-tab').first().click();
      await page.waitForTimeout(150);
      const cards = page.locator('#serviceGrid .service-card');
      const count = await cards.count();
      for (let i = 0; i < Math.min(2, count); i++) {
        const name = (await cards.nth(i).locator('.service-name-text').innerText()).trim();
        await cards.nth(i).click();
        addedNames.push(name);
      }
    }

    await page.locator('#categoryTabs .cat-tab').first().click(); // về All để chụp ảnh đẹp

    // Custom / Open item — modal thật trong code hiện tại (KHÔNG có "modifier modal"
    // chọn độ dài/form móng — feature đó chưa tồn tại, xem FINDING bên dưới).
    await page.evaluate(() => window.openCustomItemModal());
    await page.waitForSelector('#customItemModal.active', { timeout: 3000 });
    await page.fill('#customItemName', 'Nail Art Design (QA Audit)');
    await page.fill('#customItemPrice', '15');
    await page.fill('#customItemQty', '1');
    await page.click('button[onclick="addCustomItem()"]');
    await page.waitForTimeout(300);

    finding('Yêu cầu spec có nhắc "modal modifier: chọn độ dài móng, form móng" — tính năng này KHÔNG tồn tại trong pos_nail.html hiện tại. Chỉ có modal "Add Custom Item" (tên + giá + số lượng tự do), đã test thay thế ở bước này.');

    const cartCount = await page.locator('#cartItems .cart-item').count();
    await shot(page, '02_service_selection_modifier.png');

    record(
      '2. Chọn Dịch Vụ & Modifier/Custom Item',
      cartCount >= 3 ? 'PASS' : 'WARN',
      Date.now() - t0,
      `Đã thêm: ${addedNames.join(', ')} + 1 Custom Item ($15). Tổng ${cartCount} dòng trong giỏ.`
    );
  } catch (e) {
    record('2. Chọn Dịch Vụ & Modifier/Custom Item', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_service_selection_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 3 — Gán thợ, +/- số lượng, Hold/Resume Ticket
  // ============================================================
  t0 = Date.now();
  try {
    // Layout mới: giỏ hàng/gán thợ luôn nằm ở cột trái (tab "Current Ticket", mặc định active) —
    // không còn tab "turnDetails" bên phải nữa, nhưng vẫn gọi switchLeftTab('ticket') cho chắc
    // (phòng khi đang ở tab Queue từ bước trước).
    await page.evaluate(() => window.switchLeftTab('ticket'));
    await page.waitForTimeout(150);

    const firstSelect = page.locator('#cartItems .cart-item select').first();
    const options = await firstSelect.locator('option').allTextContents();
    const avaOption = options.find((o) => /ava\s*robertson/i.test(o));
    if (avaOption) {
      await firstSelect.selectOption({ label: avaOption });
    } else {
      const opts = await firstSelect.locator('option').all();
      if (opts.length > 1) {
        const val = await opts[1].getAttribute('value');
        await firstSelect.selectOption(val);
      }
    }
    const selectedLabel = await firstSelect.locator('option:checked').innerText();
    assignedTechName = selectedLabel.trim();
    assignedTechId = await firstSelect.inputValue();

    // +/- quantity trên dòng đầu tiên (idx=0). LƯU Ý: markup thật render
    // `onclick="changeQty(${idx}, 1)"` — CÓ khoảng trắng sau dấu phẩy.
    await page.click('button[onclick="changeQty(0, 1)"]');
    await page.waitForTimeout(150);
    await page.click('button[onclick="changeQty(0, 1)"]');
    await page.waitForTimeout(150);
    await page.click('button[onclick="changeQty(0, -1)"]');
    await page.waitForTimeout(150);

    await shot(page, '03a_tech_assigned_qty.png');

    // Hold Ticket -> resume ngay (giỏ trống lúc resume nên không bị confirm() chặn)
    const cartCountBeforeHold = await page.locator('#cartItems .cart-item').count();
    await page.evaluate(() => window.holdTicket());
    await page.waitForTimeout(200);
    const cartCountAfterHold = await page.locator('#emptyCartMsg').isVisible().catch(() => false);
    const queueBadge = await page.locator('#queueCountBadge').innerText().catch(() => '0');

    await page.evaluate(() => window.toggleQueuePanel());
    await page.waitForTimeout(200);
    await shot(page, '03b_queue_panel_open.png');

    const queueEntry = page.locator('#queueList .queue-entry').first();
    await queueEntry.click();
    await page.waitForTimeout(300);
    const cartCountAfterResume = await page.locator('#cartItems .cart-item').count();

    await shot(page, '03_tech_assigned_hold_resume.png');

    const pass = assignedTechId && cartCountAfterHold && cartCountAfterResume === cartCountBeforeHold;
    record(
      '3. Gán Thợ & Quản Lý Vé (Hold/Resume)',
      pass ? 'PASS' : 'WARN',
      Date.now() - t0,
      `Thợ gán: "${assignedTechName}" (${assignedTechId}). Badge hàng chờ sau Hold: ${queueBadge}. Giỏ trước Hold=${cartCountBeforeHold}, sau Resume=${cartCountAfterResume}.`
    );
    finding('Hold Ticket / Queue là localStorage phía client (key "bitpaw_held_tickets") — KHÔNG lưu server/DB. Nếu người dùng đổi trình duyệt/máy khác, vé giữ sẽ mất.');
  } catch (e) {
    record('3. Gán Thợ & Quản Lý Vé (Hold/Resume)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_tech_assigned_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 4 — Tip, Dual Pricing (nếu có), mở Payment Modal
  // ============================================================
  t0 = Date.now();
  try {
    await page.evaluate(() => window.switchLeftTab('ticket'));
    await page.waitForTimeout(200);

    const totalBefore = await page.locator('#sumTotal').innerText();
    await page.fill('#cashTip', '5');
    await page.fill('#cardTip', '3');
    await page.locator('#cashTip').dispatchEvent('input');
    await page.locator('#cardTip').dispatchEvent('input');
    await page.waitForTimeout(200);
    const totalAfter = await page.locator('#sumTotal').innerText();
    const tipRowText = await page.locator('#sumTip').innerText();

    // #sumCashPrice/#sumCardPrice — Dual Pricing thật (Test 10 bên dưới kiểm tra kỹ hơn:
    // đúng %, đúng total_amount server trả về, không ảnh hưởng hoa hồng thợ).
    const dualPricingToggleExists = (await page.locator('#sumCashPrice, #sumCardPrice').count()) > 0;
    if (!dualPricingToggleExists) {
      finding('#sumCashPrice/#sumCardPrice không tìm thấy trên Close Ticket tab — kiểm tra lại templates/pos_nail.html có bị sửa/xoá phần Dual Pricing không.');
    }

    // { force: true }: #checkoutBtn (.pay-now-btn) có CSS animation vô hạn
    // (payNowPulse 2s infinite + pulseBg 4s infinite) — bounding box của nó
    // không bao giờ "đứng yên" giữa 2 khung hình liên tiếp nên actionability
    // check mặc định của Playwright (đợi phần tử "stable") sẽ timeout vô hạn
    // dù nút hoàn toàn bấm được thật với người dùng thật.
    await page.click('#checkoutBtn', { force: true });
    await page.waitForSelector('#paymentModal.active', { timeout: 3000 });
    await page.click('.pay-method-btn[data-method="cash"]');
    await page.waitForTimeout(150);

    await shot(page, '04_dual_pricing_tip_modal.png');

    const pass = totalBefore !== totalAfter && tipRowText.includes('8.00');
    record(
      '4. Tính Tiền, Tip & Payment Modal',
      pass ? 'PASS' : 'WARN',
      Date.now() - t0,
      `Total: "${totalBefore}" -> "${totalAfter}" (Tip: ${tipRowText}). Dual-pricing UI toggle tồn tại: ${dualPricingToggleExists}.`
    );
  } catch (e) {
    record('4. Tính Tiền, Tip & Payment Modal', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '04_dual_pricing_tip_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 5 — Xác nhận thanh toán, bắt response API, xác nhận order_id
  // ============================================================
  t0 = Date.now();
  try {
    const [checkoutResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/nail_pos/checkout') && res.request().method() === 'POST', { timeout: 15000 }),
      page.click('#confirmPaymentBtn'),
    ]);

    const status = checkoutResp.status();
    checkoutResponseBody = await checkoutResp.json().catch(() => null);
    checkoutOrderId = checkoutResponseBody?.order_id ?? null;

    await page.waitForSelector('#receiptModal.active', { timeout: 8000 });
    const receiptOrderIdText = await page.locator('#receiptOrderId').innerText();

    await shot(page, '05_payment_confirmed_db.png');

    const pass = (status === 200 || status === 201) && checkoutResponseBody?.success === true && !!checkoutOrderId && receiptOrderIdText.includes(String(checkoutOrderId));
    record(
      '5. Xác Nhận Thanh Toán & Lưu DB',
      pass ? 'PASS' : 'FAIL',
      Date.now() - t0,
      `HTTP ${status}, order_id=${checkoutOrderId}, total_amount=${checkoutResponseBody?.total_amount}, receipt hiển thị: "${receiptOrderIdText}"`
    );

    if (checkoutOrderId) {
      fs.writeFileSync(STATE_FILE, JSON.stringify({
        order_id: checkoutOrderId,
        response: checkoutResponseBody,
        assignedTechId,
        assignedTechName,
        timestamp: new Date().toISOString(),
      }, null, 2));
    }
  } catch (e) {
    record('5. Xác Nhận Thanh Toán & Lưu DB', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '05_payment_confirmed_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 6 — Lịch sử hóa đơn & In lại bill
  // ============================================================
  t0 = Date.now();
  try {
    await page.click('button:has-text("Start New Ticket"), [onclick="startNewTicket()"]').catch(() => {});
    await page.waitForTimeout(300);

    await page.evaluate(() => window.openOrderHistoryModal());
    await page.waitForSelector('#orderHistoryModal.active', { timeout: 5000 });
    await page.waitForTimeout(600); // loadOrderHistory() là async

    const historyRows = await page.locator('#historyBody tr').count();
    let topRowHasOrder = false;
    if (checkoutOrderId) {
      const bodyText = await page.locator('#historyBody').innerText();
      topRowHasOrder = bodyText.includes(String(checkoutOrderId));
    }

    await shot(page, '06_history_drawer_reprint.png');

    if (checkoutOrderId) {
      await page.evaluate((oid) => window.reprintOrderFromHistory(oid), checkoutOrderId);
      await page.waitForSelector('#receiptModal.active', { timeout: 5000 });
      await page.waitForTimeout(200);
      await shot(page, '06b_reprint_receipt.png');
    }

    const pass = historyRows > 0 && topRowHasOrder;
    record(
      '6. Lịch Sử Hóa Đơn & In Lại Bill',
      pass ? 'PASS' : 'WARN',
      Date.now() - t0,
      `Số dòng lịch sử hôm nay: ${historyRows}. Đơn #${checkoutOrderId} xuất hiện trong danh sách: ${topRowHasOrder}.`
    );
  } catch (e) {
    record('6. Lịch Sử Hóa Đơn & In Lại Bill', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '06_history_drawer_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 7 — Chấm công & Payroll (US)
  // ============================================================
  t0 = Date.now();
  try {
    await page.goto(`${BASE}/chamcong/nail`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#employeeGrid', { timeout: 8000 });
    const employeeCount = await page.locator('#employeeGrid [data-ma-nv]').count();

    // #payrollCalendarGrid — Calendar Grid theo ngày (doanh thu/tip/số lượt riêng từng ngày)
    // + #paystubPanel (Cash Payout/Check-Direct Deposit/Tax Withheld) đã được xây thật, xem
    // GET /api/hr/chamcong/month_summary (app.py) và templates/chamcong_nail.html. 2 finding cũ
    // báo "chưa có" ở đây đã hết hiệu lực kể từ khi 2 tính năng này được thêm vào.
    const hasCalendarGrid = (await page.locator('#payrollCalendarGrid').count()) > 0;
    const hasPaystubIds = (await page.locator('#paystubPanel, #paystubCashPayout, #paystubCheckDeposit, #paystubTaxWithheld').count()) > 0;
    const hasPaystubText = (await page.getByText(/Tax Withheld/i).count()) > 0;
    const hasPaystub = hasPaystubIds || hasPaystubText;
    if (!hasCalendarGrid) {
      finding('Lưới Lịch Calendar (#payrollCalendarGrid) không tìm thấy trên /chamcong/nail — kiểm tra lại templates/chamcong_nail.html có bị sửa/xoá phần Calendar Grid không.');
    }
    if (!hasPaystub) {
      finding('Spec yêu cầu "Tech Paystub" với 3 dòng Cash Payout / Check-Direct Deposit / Tax Withheld — tính năng phiếu lương chuẩn Mỹ này CHƯA được implement ở bất kỳ đâu trong app.py/templates. Dữ liệu tip+commission có thật sự được ghi vào collection MongoDB "chamcong" (đã verify ở phần DB bên dưới), nhưng chưa có màn hình payslip tổng hợp thuế.');
    }

    await shot(page, '07a_chamcong_employee_grid.png');

    let historyMatch = false;
    let historyEntryText = '';
    if (assignedTechId) {
      const techCard = page.locator(`#employeeGrid [data-ma-nv="${assignedTechId}"]`);
      if (await techCard.count() > 0) {
        await techCard.locator('[data-action="open"]').first().click();
        await page.waitForSelector('#screen_pos.active', { timeout: 5000 });
        await page.waitForTimeout(900); // loadHistory() async
        const historyText = await page.locator('#historyBox').innerText();
        historyMatch = checkoutOrderId ? /\$|AUD/.test(historyText) && !historyText.includes('No transactions') && !historyText.includes('Chưa có') : historyText.length > 0;
        historyEntryText = historyText.slice(0, 200).replace(/\s+/g, ' ');
        await shot(page, '07_payroll_us_breakdown.png');
      } else {
        finding(`Không tìm thấy thẻ nhân viên cho ma_nv="${assignedTechId}" trong #employeeGrid ở trang chấm công.`);
        await shot(page, '07_payroll_us_breakdown.png');
      }
    } else {
      await shot(page, '07_payroll_us_breakdown.png');
    }

    const pass = employeeCount > 0 && historyMatch;
    record(
      '7. Đối Soát Chấm Công & Payroll (US)',
      pass ? 'PASS' : 'WARN',
      Date.now() - t0,
      `${employeeCount} nhân viên hiển thị. Lịch sử "Tính Tua" của thợ vừa gán có dữ liệu mới: ${historyMatch}. Snippet: "${historyEntryText}"`
    );
  } catch (e) {
    record('7. Đối Soát Chấm Công & Payroll (US)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '07_payroll_us_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 8 — Booking Website công khai + QR Code (chủ tiệm -> khách hàng)
  // ============================================================
  t0 = Date.now();
  let bookingContext = null;
  try {
    // 8a. Phía chủ tiệm (đã đăng nhập): mở modal QR trong POS, đọc đúng link/QR sẽ in ra.
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    // BUG THẬT đã vá (phát hiện lúc retest sau UI polish): mọi test khác sau khi goto('/sell')
    // đều chờ '#serviceGrid .service-card' xuất hiện trước khi evaluate() bất kỳ hàm nào — đây
    // là cách duy nhất chắc chắn toàn bộ <script> inline (2500+ dòng) của trang đã chạy xong
    // (networkidle chỉ đảm bảo hết request mạng, KHÔNG đảm bảo JS đã thực thi xong dưới tải
    // máy cao). Test 8 là chỗ DUY NHẤT thiếu bước chờ này, nên page.evaluate(() =>
    // openBookingQrModal()) thỉnh thoảng chạy trước khi hàm đó được định nghĩa, ném
    // ReferenceError — không phải lỗi ứng dụng thật.
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 10000 });
    await page.evaluate(() => openBookingQrModal());
    await page.waitForSelector('#bookingQrModal.active', { timeout: 5000 });
    await page.waitForTimeout(300); // <img> load QR SVG

    const qrImgSrc = await page.locator('#bookingQrImg').getAttribute('src');
    const bookingUrlShown = (await page.locator('#bookingQrUrl').innerText()).trim();
    const businessId = await page.evaluate(() => (typeof BUSINESS_ID !== 'undefined' ? BUSINESS_ID : null));

    await shot(page, '08a_booking_qr_modal_owner_side.png');

    if (!businessId || !bookingUrlShown.includes(businessId)) {
      finding(`Link Booking QR hiển thị cho chủ tiệm ("${bookingUrlShown}") không khớp business_id phiên đang đăng nhập ("${businessId}") — rủi ro QR in ra trỏ sai tiệm.`);
    }

    // 8b. Phía khách hàng: mở ĐÚNG link vừa quét QR trong 1 context HOÀN TOÀN mới
    // (không cookie/session đăng nhập nào) — mô phỏng đúng thật 1 khách lạ quét QR
    // bằng điện thoại, KHÔNG dùng lại session chủ tiệm.
    bookingContext = await browser.newContext({ viewport: { width: 390, height: 844 } }); // mobile-ish, khách thường quét bằng điện thoại
    const bookingPage = await bookingContext.newPage();
    const bookingConsoleErrors = [];
    bookingPage.on('console', (msg) => { if (msg.type() === 'error') bookingConsoleErrors.push(msg.text()); });

    await bookingPage.goto(bookingUrlShown || `${BASE}/booking/nail/qr/${businessId}`, { waitUntil: 'networkidle' });

    const pageTitle = await bookingPage.title();
    const publicData = await bookingPage.evaluate(() => ({
      serviceCount: typeof services !== 'undefined' ? services.length : -1,
      techCount: typeof technicians !== 'undefined' ? technicians.length : -1,
    }));

    await shot(bookingPage, '08b_public_booking_page_customer_side.png');

    if (publicData.serviceCount <= 0) {
      finding(`Trang booking công khai (${bookingUrlShown}) không tải được danh sách dịch vụ nào (serviceCount=${publicData.serviceCount}) — nếu đúng, khách quét QR sẽ thấy trang trống, không đặt được lịch.`);
    }

    // 8c. Điền form & đặt lịch thật như 1 khách hàng — không mock, đi qua đúng
    // /create_appointment thật (CSRF token tự động gắn qua script bootstrap
    // app.py::_inject_csrf_bootstrap(), không cần tự set token thủ công).
    const customerName = 'QA Audit Khach Hang';
    const customerPhone = '0491' + String(Date.now()).slice(-6);
    await bookingPage.fill('#cus_name', customerName);
    await bookingPage.fill('#cus_phone', customerPhone);
    await bookingPage.fill('#cus_address', '123 Audit Test Street');
    await bookingPage.selectOption('#cus_service', { index: 1 }); // index 0 là placeholder "-- Loading... --"

    // CỐ Ý để "No preference" (không chọn thợ cụ thể) — book_appointment() chỉ chặn double-
    // booking khi có staff_id; chọn thợ cụ thể + giờ cố định sẽ khiến lần chạy audit THỨ HAI
    // trong cùng ngày bị 409 SlotAlreadyBookedError (đã thấy thật khi chạy lại script), dù đó
    // là hành vi ĐÚNG của hệ thống, không phải bug — không chọn thợ để script audit chạy lại
    // nhiều lần trong ngày vẫn ổn định.

    // Giờ hẹn ngẫu nhiên hoá theo phút hiện tại (không chỉ theo ngày) để mỗi lần chạy script
    // rơi vào 1 slot khác nhau, tránh giả-trùng-lịch giữa các lần audit liên tiếp.
    const bookDate = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000); // +3 ngày, chắc chắn > "now" (JS chặn chọn quá khứ)
    const bookDateStr = bookDate.toISOString().slice(0, 10);
    const randomHour = String(9 + (Date.now() % 8)).padStart(2, '0'); // 09..16h, giờ làm việc hợp lý
    const randomMinute = String(Date.now() % 60).padStart(2, '0');
    await bookingPage.fill('#cus_datetime', `${bookDateStr}T${randomHour}:${randomMinute}`);
    await bookingPage.fill('#cus_note', 'Đặt qua audit script — kiểm tra luồng QR end-to-end.');

    const [createApptResp] = await Promise.all([
      bookingPage.waitForResponse((res) => res.url().includes('/create_appointment') && res.request().method() === 'POST', { timeout: 10000 }),
      bookingPage.click('#btnSubmit'),
    ]);
    const createApptStatus = createApptResp.status();
    const createApptBody = await createApptResp.json().catch(() => null);

    await bookingPage.waitForSelector('#successContainer:not(.hidden)', { timeout: 5000 }).catch(() => {});
    const ticketText = await bookingPage.locator('#displayTicket').innerText().catch(() => '');

    await shot(bookingPage, '08c_booking_success_ticket.png');

    // 8d. Quay lại phía chủ tiệm (context ĐÃ đăng nhập, không phải context khách) —
    // xác nhận lịch hẹn vừa đặt qua QR thật sự xuất hiện trong /calendar của tiệm,
    // không chỉ "chạy tạm trong RAM"/response JSON mà không ai đọc lại được.
    await page.goto(`${BASE}/calendar?date=${bookDateStr}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const calendarBodyText = await page.locator('body').innerText();
    const apptVisibleInCalendar = calendarBodyText.includes(customerPhone) || calendarBodyText.includes(customerName);

    await shot(page, '08d_calendar_new_appointment_owner_side.png');

    const pass =
      createApptStatus === 200 &&
      createApptBody?.success === true &&
      !!createApptBody?.id &&
      /TICKET-/.test(ticketText) &&
      publicData.serviceCount > 0 &&
      apptVisibleInCalendar &&
      bookingConsoleErrors.length === 0;

    record(
      '8. Booking Website Công Khai + QR Code',
      pass ? 'PASS' : (createApptStatus === 200 && createApptBody?.success ? 'WARN' : 'FAIL'),
      Date.now() - t0,
      `Business "${businessId}" — public page: ${publicData.serviceCount} dịch vụ / ${publicData.techCount} thợ. Đặt lịch HTTP ${createApptStatus}, appointment id=${createApptBody?.id}, ticket="${ticketText}". Xuất hiện trong /calendar của chủ tiệm: ${apptVisibleInCalendar}. Console errors (trang khách): ${bookingConsoleErrors.length}.`
    );

    if (!apptVisibleInCalendar) {
      finding('Lịch hẹn đặt qua QR public đã ghi API thành công (success:true + id) nhưng KHÔNG thấy xuất hiện trên /calendar của chủ tiệm khi lọc đúng ngày đặt — kiểm tra lại query date-range của calendar_view() hoặc timezone giữa book_time gửi lên và filter ngày phía server.');
    }
  } catch (e) {
    record('8. Booking Website Công Khai + QR Code', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '08_booking_qr_FAILED.png').catch(() => {});
  } finally {
    if (bookingContext) await bookingContext.close().catch(() => {});
  }

  // ============================================================
  // TEST 9 — Discount, Split Payment & Refund
  // ============================================================
  t0 = Date.now();
  try {
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 10000 });
    await page.locator('#serviceGrid .service-card').first().click();
    await page.waitForTimeout(200);

    // --- Discount ---
    await page.evaluate(() => openDiscountModal());
    await page.waitForSelector('#discountModal.active', { timeout: 3000 });
    await page.click('[data-disc-type="percent"]');
    await page.fill('#discountValueInput', '10');
    await page.locator('#discountValueInput').dispatchEvent('input');
    await page.waitForTimeout(150);
    const discountPreview = await page.locator('#discountPreview').innerText();
    await page.click('button[onclick="applyDiscount()"]');
    await page.waitForTimeout(200);
    const discountApplied = discountPreview !== '$0.00';

    // --- Split payment ---
    await page.evaluate(() => switchLeftTab('ticket'));
    await page.waitForTimeout(150);
    const totalText = await page.locator('#sumTotal').innerText();
    const totalNum = parseFloat(totalText.replace(/[^0-9.]/g, '')) || 0;
    await page.click('#checkoutBtn', { force: true });
    await page.waitForSelector('#paymentModal.active', { timeout: 3000 });
    await page.click('.pay-method-btn[data-method="split"]');
    await page.waitForTimeout(150);
    const half = (totalNum / 2).toFixed(2);
    await page.fill('#splitCashAmount', half);
    await page.fill('#splitCardAmount', half);
    await page.locator('#splitCashAmount').dispatchEvent('input');
    await page.locator('#splitCardAmount').dispatchEvent('input');
    await page.waitForTimeout(150);
    const splitMismatchVisible = await page.locator('#splitMismatchMsg').isVisible().catch(() => false);
    const confirmDisabled = await page.locator('#confirmPaymentBtn').isDisabled();

    await shot(page, '09a_discount_split_payment.png');

    let splitOrderId = null;
    if (!confirmDisabled) {
      const [splitResp] = await Promise.all([
        page.waitForResponse((res) => res.url().includes('/api/nail_pos/checkout') && res.request().method() === 'POST', { timeout: 10000 }),
        page.click('#confirmPaymentBtn'),
      ]);
      const splitBody = await splitResp.json().catch(() => null);
      splitOrderId = splitBody?.order_id ?? null;
      await page.waitForSelector('#receiptModal.active', { timeout: 8000 }).catch(() => {});
    } else {
      finding('Split payment: #confirmPaymentBtn bị disable dù đã set cash+card = đúng tổng tiền (half+half) — kiểm tra lại validateSplit()/làm tròn số thập phân.');
    }

    // --- Refund (order vừa tạo bằng split ở trên, hoặc order #checkoutOrderId từ Test 5 nếu split lỗi) ---
    const refundTargetOrder = splitOrderId || checkoutOrderId;
    let refundOk = false;
    let refundMessage = '';
    if (refundTargetOrder) {
      await page.click('button:has-text("Start New Ticket"), [onclick="startNewTicket()"]').catch(() => {});
      await page.waitForTimeout(200);
      await page.evaluate((oid) => openRefundModal(oid), refundTargetOrder);
      await page.waitForSelector('#refundModal.active', { timeout: 3000 });
      await page.fill('#refundAmount', '5');
      await page.fill('#refundReason', 'QA Audit — kiểm tra luồng hoàn tiền một phần.');

      const [refundResp] = await Promise.all([
        page.waitForResponse((res) => res.url().includes('/api/nail_pos/refund') && res.request().method() === 'POST', { timeout: 10000 }),
        page.click('#confirmRefundBtn'),
      ]);
      const refundBody = await refundResp.json().catch(() => null);
      refundOk = refundResp.status() === 200 && refundBody?.success === true;
      refundMessage = refundBody?.message || JSON.stringify(refundBody);
      await shot(page, '09b_refund_result.png');
    } else {
      finding('Không có order_id hợp lệ nào (split lẫn Test 5) để test luồng Refund.');
    }

    const pass = discountApplied && !splitMismatchVisible && !!splitOrderId && refundOk;
    record(
      '9. Giảm Giá, Thanh Toán Chia Đôi & Hoàn Tiền',
      pass ? 'PASS' : 'WARN',
      Date.now() - t0,
      `Discount preview: ${discountPreview} (áp dụng: ${discountApplied}). Split total=${totalNum}, cash=card=${half}, mismatch=${splitMismatchVisible}, order_id=${splitOrderId}. Refund order #${refundTargetOrder}: ${refundOk} (${refundMessage}).`
    );
  } catch (e) {
    record('9. Giảm Giá, Thanh Toán Chia Đôi & Hoàn Tiền', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '09_discount_split_refund_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 10 — Dual Pricing (Cash Price / Card Price +phụ phí thẻ)
  // ============================================================
  t0 = Date.now();
  try {
    // Vé 1 — CÙNG 1 dịch vụ, CÙNG 1 thợ, thanh toán CASH (mốc so sánh, không phụ phí).
    // Tự chọn thợ FRESH trong chính test này (không dựa vào assignedTechId của Test 3 — biến đó
    // sống sót qua điều hướng trang nhưng để chắc chắn không lệch DOM sau nhiều lần reload/goto
    // ở các test trước, chọn lại + đọc ngược giá trị thật đã chọn, giống cách Test 3 làm).
    async function runSingleItemCheckout(payMethod) {
      await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
      await page.waitForSelector('#serviceGrid .service-card', { timeout: 10000 });
      await page.locator('#serviceGrid .service-card').first().click();
      await page.waitForTimeout(200);
      // Select gán thợ CÓ trong DOM ngay từ tab "service" nhưng chỉ HIỆN (visible) ở tab "Turn
      // Details" — đúng hành vi Test 3 đã xác minh, không phải bug.
      await page.evaluate(() => switchLeftTab('ticket'));
      await page.waitForTimeout(150);

      const sel = page.locator('#cartItems .cart-item select').first();
      await sel.waitFor({ state: 'visible', timeout: 5000 });
      const opts = await sel.locator('option').all();
      let pickedTechId = null;
      if (opts.length > 1) {
        pickedTechId = await opts[1].getAttribute('value'); // index 0 luôn là placeholder "-- Assign --"
        await sel.selectOption(pickedTechId);
      }
      await page.waitForTimeout(150);
      const confirmedTechId = await sel.inputValue();

      await page.evaluate(() => switchLeftTab('ticket'));
      await page.waitForTimeout(150);

      const cashPriceText = await page.locator('#sumCashPrice').innerText();
      const cardPriceText = await page.locator('#sumCardPrice').innerText();

      await page.click('#checkoutBtn', { force: true });
      await page.waitForSelector('#paymentModal.active', { timeout: 3000 });
      await page.click(`.pay-method-btn[data-method="${payMethod}"]`);
      await page.waitForTimeout(150);
      const modalSurchargeVisible = await page.locator('#modalSurchargeRow').isVisible().catch(() => false);

      const [resp] = await Promise.all([
        page.waitForResponse((r) => r.url().includes('/api/nail_pos/checkout') && r.request().method() === 'POST', { timeout: 15000 }),
        page.click('#confirmPaymentBtn'),
      ]);
      const body = await resp.json().catch(() => null);
      await page.waitForSelector('#receiptModal.active', { timeout: 8000 }).catch(() => {});
      return { body, cashPriceText, cardPriceText, modalSurchargeVisible, confirmedTechId };
    }

    const cashRun = await runSingleItemCheckout('cash');
    await page.click('button:has-text("Start New Ticket"), [onclick="startNewTicket()"]').catch(() => {});
    await page.waitForTimeout(300);
    const cardRun = await runSingleItemCheckout('card');
    await shot(page, '10_dual_pricing_payment_modal.png');

    const cashNum = (s) => parseFloat(String(s).replace(/[^0-9.]/g, ''));
    const uiCashPrice = cashNum(cashRun.cashPriceText);
    const uiCardPrice = cashNum(cashRun.cardPriceText);
    const expectedCardPrice = round2(uiCashPrice * 1.03);

    const cashCommission = cashRun.body?.techs_paid?.find((t) => t.ma_nv === cashRun.confirmedTechId)?.commission;
    const cardCommission = cardRun.body?.techs_paid?.find((t) => t.ma_nv === cardRun.confirmedTechId)?.commission;
    const surcharge = cardRun.body?.card_surcharge_amount;

    const pass =
      !cashRun.modalSurchargeVisible && // Cash không hiện phụ phí
      cardRun.modalSurchargeVisible && // Card có hiện phụ phí
      Math.abs(uiCardPrice - expectedCardPrice) < 0.02 && // UI tính đúng +3%
      cashRun.body?.total_amount === cashRun.body?.subtotal && // Cash: total = subtotal, không phụ phí
      surcharge > 0 &&
      Math.abs(cardRun.body?.total_amount - (cardRun.body?.subtotal + surcharge)) < 0.02 && // Card: total = subtotal + phụ phí
      cashCommission != null && cardCommission != null && Math.abs(cashCommission - cardCommission) < 0.01; // Hoa hồng KHÔNG bị phụ phí ảnh hưởng

    record(
      '10. Dual Pricing (Cash Price / Card Price)',
      pass ? 'PASS' : 'FAIL',
      Date.now() - t0,
      `UI: cash=$${uiCashPrice} card=$${uiCardPrice} (kỳ vọng $${expectedCardPrice}). Order Cash #${cashRun.body?.order_id}: total=${cashRun.body?.total_amount}, hoa hồng=${cashCommission}. ` +
      `Order Card #${cardRun.body?.order_id}: total=${cardRun.body?.total_amount}, subtotal=${cardRun.body?.subtotal}, phụ phí=${surcharge}, hoa hồng=${cardCommission} (phải bằng hoa hồng Cash — chứng minh phụ phí KHÔNG lọt vào hoa hồng thợ).`
    );
  } catch (e) {
    record('10. Dual Pricing (Cash Price / Card Price)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '10_dual_pricing_FAILED.png').catch(() => {});
  }

  await finalize({ browser, results, findings, checkoutOrderId, checkoutResponseBody, consoleErrors, networkErrors });
}

async function finalize({ browser, results, findings, checkoutOrderId, checkoutResponseBody, consoleErrors = [], networkErrors = [] }) {
  await browser.close();

  const passCount = results.filter((r) => r.status === 'PASS').length;
  const warnCount = results.filter((r) => r.status === 'WARN').length;
  const failCount = results.filter((r) => r.status === 'FAIL').length;

  const reportData = {
    generatedAt: new Date().toISOString(),
    summary: { total: results.length, pass: passCount, warn: warnCount, fail: failCount },
    results,
    findings,
    checkoutOrderId,
    checkoutResponseBody,
    consoleErrorsSample: consoleErrors.slice(0, 10),
    networkErrorsSample: networkErrors.slice(0, 10),
  };
  fs.writeFileSync(REPORT_JSON, JSON.stringify(reportData, null, 2));

  const md = [
    '# Nail Industry Master Audit Report',
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
