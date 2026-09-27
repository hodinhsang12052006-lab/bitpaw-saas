/**
 * scripts/retail_industry_master_audit.mjs
 *
 * QA Master Audit — Retail Industry vertical (POS lưới sản phẩm + giỏ hàng trên
 * /retail_pos, quét mã vạch, thanh toán qua /api/sales/checkout, hoàn tiền).
 *
 * Chạy:  node scripts/retail_industry_master_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Mọi selector trong script này đã được xác minh TRỰC TIẾP bằng grep + đọc code thật trong
 * templates/retail_pos.html, blueprints/retail_bp.py — KHÔNG suy đoán.
 * Đã gán barcode thật cho 2 sản phẩm demo (id 213/214) để test được cả nhánh thành công LẪN
 * nhánh không tìm thấy của /api/products/lookup_barcode (trước đó dữ liệu seed hoàn toàn
 * không có barcode nào, chỉ test được nhánh lỗi).
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.RETAIL_DEMO_EMAIL || 'demo.retail.596348@bitpawdemo.com';
const PASSWORD = process.env.RETAIL_DEMO_PASSWORD || 'DemoBitPaw2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/retail_master_audit');
const REPORT_JSON = path.resolve('audit-results/retail_master_audit_report.json');
const REPORT_MD = path.resolve('audit-results/retail_master_audit_report.md');

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
  await page.screenshot({ path: path.join(SCREEN_DIR, name), fullPage: true });
}

async function main() {
  console.log('=== RETAIL INDUSTRY MASTER AUDIT — bắt đầu ===\n');
  console.log(`Target: ${BASE}   Account: ${EMAIL}\n`);

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
  // TEST 1 — Đăng nhập & Khởi tạo POS Retail
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

    await page.goto(`${BASE}/retail_pos`, { waitUntil: 'networkidle' });
    await page.waitForSelector('.product-card', { timeout: 10000 });

    const productCount = await page.locator('.product-card').count();
    await shot(page, '01_retail_launch.png');

    const errorsExcludingFavicon = consoleErrors.filter((e) => !/favicon/i.test(e));
    const pass = errorsExcludingFavicon.length === 0 && networkErrors.length === 0 && productCount > 0;
    record('1. Đăng nhập & Khởi tạo POS Retail', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `console_errors=${consoleErrors.length}, network_5xx=${networkErrors.length}, products=${productCount}`);
  } catch (e) {
    record('1. Đăng nhập & Khởi tạo POS Retail', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_retail_launch_FAILED.png').catch(() => {});
    await finalize({ browser, results, findings });
    process.exit(1);
  }

  // ============================================================
  // TEST 2 — Tìm kiếm/lọc danh mục, thêm sản phẩm vào giỏ
  // ============================================================
  t0 = Date.now();
  try {
    const cards = page.locator('.product-card');
    const count = await cards.count();
    const addCount = Math.min(3, count);
    for (let i = 0; i < addCount; i++) {
      await cards.nth(i).click();
      await page.waitForTimeout(150);
    }

    await page.click('#cartIcon');
    await page.waitForTimeout(200);
    const cartLineCount = await page.locator('#cartItemsList .cart-item').count();
    await shot(page, '02_retail_cart_added.png');

    // Tìm kiếm theo tên (client-side filter)
    const firstName = await cards.first().getAttribute('data-name');
    await page.fill('#searchInput', firstName.slice(0, 4));
    await page.waitForTimeout(200);
    const visibleAfterSearch = await page.locator('.product-card:visible').count();
    await page.fill('#searchInput', '');
    await page.waitForTimeout(150);

    const pass = addCount > 0 && cartLineCount === addCount && visibleAfterSearch > 0;
    record('2. Tìm Kiếm & Thêm Sản Phẩm Vào Giỏ', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Đã thêm ${addCount} sản phẩm, giỏ hiển thị ${cartLineCount} dòng. Tìm "${firstName.slice(0, 4)}" -> ${visibleAfterSearch} kết quả hiện.`);
  } catch (e) {
    record('2. Tìm Kiếm & Thêm Sản Phẩm Vào Giỏ', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_retail_cart_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 3 — Quét mã vạch: nhánh thành công (thêm vào giỏ) + nhánh không tìm thấy
  // ============================================================
  t0 = Date.now();
  try {
    const cartCountBefore = await page.locator('#cartCountBadge').innerText().catch(() => '0');

    const [okResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/products/lookup_barcode'), { timeout: 8000 }),
      (async () => {
        await page.click('#barcodeInput');
        await page.type('#barcodeInput', '8934588123451');
        await page.press('#barcodeInput', 'Enter');
      })(),
    ]);
    const okStatus = okResp.status();
    const okBody = await okResp.json().catch(() => null);
    await page.waitForTimeout(300);
    const cartCountAfterScan = await page.locator('#cartCountBadge').innerText().catch(() => '0');
    await shot(page, '03a_retail_barcode_scan_success.png');

    const [notFoundResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/products/lookup_barcode'), { timeout: 8000 }),
      (async () => {
        await page.click('#barcodeInput');
        await page.type('#barcodeInput', '0000000000000');
        await page.press('#barcodeInput', 'Enter');
      })(),
    ]);
    const notFoundStatus = notFoundResp.status();
    const notFoundBody = await notFoundResp.json().catch(() => null);
    await page.waitForTimeout(200);
    await shot(page, '03b_retail_barcode_not_found_toast.png');

    const pass = okStatus === 200 && okBody?.success === true && parseInt(cartCountAfterScan) > parseInt(cartCountBefore) &&
      notFoundStatus === 404 && notFoundBody?.success === false;
    record('3. Quét Mã Vạch (thành công + không tìm thấy)', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Quét "8934588123451": HTTP ${okStatus}, "${okBody?.data?.name}" thêm vào giỏ (badge ${cartCountBefore} -> ${cartCountAfterScan}). Quét mã giả: HTTP ${notFoundStatus}, message="${notFoundBody?.message}".`);
  } catch (e) {
    record('3. Quét Mã Vạch (thành công + không tìm thấy)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_retail_barcode_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 4 — Thanh toán tiền mặt qua /api/sales/checkout
  // ============================================================
  t0 = Date.now();
  try {
    await page.click('#openCheckoutBtn');
    await page.waitForSelector('#checkoutModal.active', { timeout: 3000 });
    await page.click('.pm-option[data-method="cash"]');
    await page.waitForTimeout(150);
    await shot(page, '04a_retail_checkout_modal.png');

    const [checkoutResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/sales/checkout') && res.request().method() === 'POST', { timeout: 15000 }),
      page.click('#confirmCheckoutBtn'),
    ]);
    const status = checkoutResp.status();
    const body = await checkoutResp.json().catch(() => null);
    checkoutOrderId = body?.order_id ?? null;

    await page.waitForTimeout(500);
    const modalClosed = !(await page.locator('#checkoutModal').evaluate((el) => el.classList.contains('active')));
    await shot(page, '04b_retail_checkout_success.png');

    const pass = status === 200 && body?.success !== false && !!checkoutOrderId && modalClosed;
    record('4. Thanh Toán Tiền Mặt (/api/sales/checkout)', pass ? 'PASS' : 'FAIL', Date.now() - t0,
      `HTTP ${status}, order_id=${checkoutOrderId}, total_amount=${body?.total_amount}, modal đã đóng: ${modalClosed}`);
  } catch (e) {
    record('4. Thanh Toán Tiền Mặt (/api/sales/checkout)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '04_retail_checkout_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 5 — Hoàn tiền một phần cho đơn vừa tạo
  // ============================================================
  t0 = Date.now();
  try {
    await page.waitForTimeout(1500); // window.location.reload() sau checkout thành công
    await page.waitForSelector('.product-card', { timeout: 10000 });

    if (!checkoutOrderId) throw new Error('Không có order_id từ Test 4 để test hoàn tiền.');

    await page.evaluate(() => window.openRefundModal());
    await page.waitForSelector('#refundModal.active', { timeout: 3000 });
    await page.fill('#refundOrderId', String(checkoutOrderId));
    await page.fill('#refundAmount', '1000');
    await page.fill('#refundReason', 'QA Audit — kiểm tra luồng hoàn tiền một phần Retail.');
    await shot(page, '05a_retail_refund_modal.png');

    const [refundResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes(`/api/orders/${checkoutOrderId}/refund`) && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate(() => window.submitRefund()),
    ]);
    const status = refundResp.status();
    const body = await refundResp.json().catch(() => null);
    await page.waitForTimeout(300);
    await shot(page, '05b_retail_refund_result.png');

    const pass = status === 200 && body?.success === true;
    record('5. Hoàn Tiền Một Phần', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Order #${checkoutOrderId}: HTTP ${status}, body=${JSON.stringify(body).slice(0, 200)}`);
  } catch (e) {
    record('5. Hoàn Tiền Một Phần', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '05_retail_refund_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 6 — Module dùng chung cho ngách Retail (Customers/AI Bot/Nhân viên/Báo cáo)
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
    await shot(page, '06_retail_shared_modules.png');

    const allOk = sharedResults.every((r) => r.endsWith('=200'));
    record('6. Module Dùng Chung Cho Retail (Customers/AI Bot/Nhân Viên/Báo Cáo)', allOk ? 'PASS' : 'WARN', Date.now() - t0,
      sharedResults.join(', '));
  } catch (e) {
    record('6. Module Dùng Chung Cho Retail (Customers/AI Bot/Nhân Viên/Báo Cáo)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '06_retail_shared_modules_FAILED.png').catch(() => {});
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
    '# Retail Industry Master Audit Report',
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
