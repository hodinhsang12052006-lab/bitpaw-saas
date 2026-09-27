/**
 * scripts/shared_modules_pha6_audit.mjs
 *
 * QA Audit — Pha 6 (module dùng chung, không thuộc riêng 1 ngách): Brand Settings (verify fix
 * bug redirect sai ngành), Checkout công khai (đăng ký mua gói SaaS), Quản lý Khuyến mãi (CRUD).
 *
 * Chạy:  node scripts/shared_modules_pha6_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Dùng tài khoản demo F&B (KHÔNG PHẢI Spa) để test Brand Settings — đây chính xác là ca lộ bug
 * cũ: mọi tenant không phải Spa lưu xong bị đẩy nhầm sang /spa.
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.FNB_DEMO_EMAIL || 'demo.fnb.343602@bitpawdemo.com';
const PASSWORD = process.env.FNB_DEMO_PASSWORD || 'DemoBitPaw2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/shared_modules_pha6');
const REPORT_JSON = path.resolve('audit-results/shared_modules_pha6_report.json');
const REPORT_MD = path.resolve('audit-results/shared_modules_pha6_report.md');

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
  console.log('=== PHA 6 SHARED MODULES AUDIT — bắt đầu ===\n');

  const consoleErrors = [];
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('dialog', async (d) => { await d.accept(); });

  // ============================================================
  // TEST 1 — Brand Settings: tenant F&B lưu xong KHÔNG bị đẩy sang /spa (regression bug đã fix)
  // ============================================================
  let t0 = Date.now();
  try {
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    const rateLimited = (await page.content()).match(/429|Too Many Requests|quá nhiều yêu cầu/i);
    if (rateLimited) throw new Error('Server đang rate-limit /login (5 lần/15 phút) — đợi hết cửa sổ giới hạn rồi chạy lại.');

    await page.fill('#loginEmail', EMAIL);
    await page.fill('#loginPassword', PASSWORD);
    await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
    if (page.url().includes('/login')) throw new Error('Đăng nhập thất bại.');

    await page.goto(`${BASE}/brand_settings`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#brandNameInput', { timeout: 8000 });

    const newName = 'QA Audit F&B Brand ' + Date.now();
    await page.fill('#brandNameInput', newName);

    const [saveResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/brand_settings') && res.request().method() === 'POST', { timeout: 10000 }),
      page.click('#saveBtn'),
    ]);
    const saveStatus = saveResp.status();
    const saveBody = await saveResp.json().catch(() => null);
    await page.waitForTimeout(2000); // đợi qua mốc setTimeout cũ (1500ms) nếu redirect còn tồn tại
    const urlAfterSave = page.url();
    await shot(page, '01_brand_settings_after_save.png');

    const wronglyRedirectedToSpa = urlAfterSave.includes('/spa');
    const pass = saveStatus === 200 && saveBody?.success === true && !wronglyRedirectedToSpa && urlAfterSave.includes('brand_settings');
    record('1. Brand Settings — Tenant F&B Lưu Xong Không Bị Đẩy Sang /spa', pass ? 'PASS' : 'FAIL', Date.now() - t0,
      `HTTP ${saveStatus}. URL sau khi lưu: ${urlAfterSave}. Bị đẩy sang /spa (bug cũ): ${wronglyRedirectedToSpa}.`);

    if (wronglyRedirectedToSpa) {
      finding('REGRESSION: brand_settings vẫn còn đẩy tenant F&B sang /spa sau khi lưu — fix chưa có hiệu lực.');
    }
  } catch (e) {
    record('1. Brand Settings — Tenant F&B Lưu Xong Không Bị Đẩy Sang /spa', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_brand_settings_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 2 — Checkout công khai (đăng ký mua gói SaaS, không cần đăng nhập)
  // ============================================================
  t0 = Date.now();
  let checkoutContext = null;
  try {
    checkoutContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const checkoutPage = await checkoutContext.newPage();
    const checkoutConsoleErrors = [];
    checkoutPage.on('console', (msg) => { if (msg.type() === 'error') checkoutConsoleErrors.push(msg.text()); });

    await checkoutPage.goto(`${BASE}/checkout?plan=pos`, { waitUntil: 'networkidle' });
    await checkoutPage.waitForSelector('#checkoutForm', { timeout: 8000 });

    const priceText = await checkoutPage.locator('#totalPriceDisplay').innerText();
    await shot(checkoutPage, '02a_checkout_page_loaded.png');

    await checkoutPage.fill('#custName', 'QA Audit Checkout Lead');
    await checkoutPage.fill('#custPhone', '0499' + String(Date.now()).slice(-6));
    await checkoutPage.fill('#custShop', 'QA Audit Test Shop');
    await checkoutPage.fill('#custEmail', 'qa.audit.checkout@example.com');
    await shot(checkoutPage, '02b_checkout_form_filled.png');

    const [signupResp] = await Promise.all([
      checkoutPage.waitForResponse((res) => res.url().includes('/api/checkout/signup') && res.request().method() === 'POST', { timeout: 10000 }),
      checkoutPage.click('#btnSubmit'),
    ]);
    const signupStatus = signupResp.status();
    const signupBody = await signupResp.json().catch(() => null);
    await checkoutPage.waitForTimeout(500);
    const successVisible = await checkoutPage.locator('#successScreen').isVisible().catch(() => false);
    await shot(checkoutPage, '02c_checkout_success_screen.png');

    const pass = signupStatus === 200 && signupBody?.success === true && successVisible && checkoutConsoleErrors.length === 0;
    record('2. Checkout Công Khai — Đăng Ký Mua Gói SaaS', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Plan "pos", giá hiển thị ${priceText}. POST /api/checkout/signup: HTTP ${signupStatus}, id=${signupBody?.data?.id}. Success screen hiện: ${successVisible}. Console errors: ${checkoutConsoleErrors.length}.`);
  } catch (e) {
    record('2. Checkout Công Khai — Đăng Ký Mua Gói SaaS', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_checkout_FAILED.png').catch(() => {});
  } finally {
    if (checkoutContext) await checkoutContext.close().catch(() => {});
  }

  // ============================================================
  // TEST 3 — Quản lý Khuyến mãi: tạo mã giảm giá mới, xác nhận hiện trong danh sách
  // ============================================================
  t0 = Date.now();
  try {
    await page.goto(`${BASE}/promotions`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#addPromoBtn', { timeout: 8000 });
    await page.click('#addPromoBtn');
    await page.waitForSelector('#promoModal.active', { timeout: 3000 });

    const promoCode = 'QAAUDIT' + String(Date.now()).slice(-6);
    await page.fill('#code', promoCode);
    await page.fill('#name', 'QA Audit Promotion');
    await page.selectOption('#discountType', 'percentage');
    await page.fill('#discountValue', '15');
    await shot(page, '03a_promotion_form_filled.png');

    const [addResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/add_promotion') && res.request().method() === 'POST', { timeout: 10000 }),
      page.click('#promoForm button[type="submit"]'),
    ]);
    const addStatus = addResp.status();
    const addBody = await addResp.json().catch(() => null);
    await page.waitForTimeout(1200); // loadPromotions() tự fetch lại danh sách sau khi lưu — cần đợi đủ lâu hơn 500ms

    const tableText = await page.locator('#promoTableBody').innerText();
    const showsInTable = tableText.includes(promoCode);
    await shot(page, '03b_promotion_created_in_list.png');

    const pass = addStatus === 200 && addBody?.success === true && showsInTable;
    record('3. Quản Lý Khuyến Mãi — Tạo Mã Giảm Giá', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Mã "${promoCode}" (giảm 15%). HTTP ${addStatus}. Hiện trong danh sách: ${showsInTable}.`);
  } catch (e) {
    record('3. Quản Lý Khuyến Mãi — Tạo Mã Giảm Giá', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_promotion_FAILED.png').catch(() => {});
  }

  await finalize({ browser, results, findings, consoleErrors });
}

async function finalize({ browser, results, findings, consoleErrors = [] }) {
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
  };
  fs.writeFileSync(REPORT_JSON, JSON.stringify(reportData, null, 2));

  const md = [
    '# Pha 6 Shared Modules Audit Report',
    '',
    `Generated: ${reportData.generatedAt}`,
    '',
    `**${passCount} PASS · ${warnCount} WARN · ${failCount} FAIL** (${results.length} test clusters)`,
    '',
    '| # | Chức năng | Trạng thái | Thời gian | Ghi chú |',
    '|---|---|---|---|---|',
    ...results.map((r, i) => `| ${i + 1} | ${r.name} | ${r.status} | ${r.ms}ms | ${r.note.replace(/\|/g, '\\|')} |`),
    '',
    '## Findings',
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
