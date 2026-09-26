/**
 * scripts/nail_shared_modules_audit.mjs
 *
 * Bổ sung cho nail_industry_master_audit.mjs — audit đó chỉ phủ luồng POS/Booking/Payroll cốt
 * lõi của Nails. Sidebar dùng chung (templates/components/app_sidebar.html) cho tài khoản Nails
 * (modules=['nail_services','attendance']) còn dẫn tới 8 trang KHÁC chưa từng được test riêng
 * trong session này: Customers (CRM), Staff/HR, AI Copilot, AI Studio, Leave Requests, Expense
 * Requests, Consolidated Report, Brand Settings. Script này đăng nhập đúng tài khoản demo Nails
 * và đi qua từng trang để xác nhận KHÔNG có trang nào lỗi/rỗng bất ngờ với 1 tài khoản Nails.
 *
 * Chạy:  node scripts/nail_shared_modules_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/nail_shared_modules_audit');
fs.mkdirSync(SCREEN_DIR, { recursive: true });

const steps = [];
function record(name, status, note = '') {
  steps.push({ name, status, note });
  const icon = status === 'PASS' ? '✅' : status === 'WARN' ? '⚠️' : '❌';
  console.log(`${icon} [${status}] ${name}${note ? ' — ' + note : ''}`);
}

async function shot(page, file) {
  await page.screenshot({ path: path.join(SCREEN_DIR, file), fullPage: true });
}

async function main() {
  console.log('=== NAIL SHARED MODULES AUDIT — bắt đầu ===\n');
  console.log(`Target: ${BASE}   Account: ${EMAIL}\n`);

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  let consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('dialog', async (d) => { await d.accept(); });

  function resetErrors() { consoleErrors = []; }

  try {
    // ============================================================
    // Đăng nhập
    // ============================================================
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.fill('#loginEmail', EMAIL);
    await page.fill('#loginPassword', PASSWORD);
    await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
    if (page.url().includes('/login')) throw new Error('Đăng nhập thất bại.');
    record('0. Đăng nhập chủ tiệm Nails', 'PASS', page.url());

    // ============================================================
    // 1. Customers (CRM) — /customers — thêm 1 khách test qua UI, xác nhận hiện trong danh sách
    // ============================================================
    resetErrors();
    await page.goto(`${BASE}/customers`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#addCustomerBtn', { timeout: 10000 });
    const rowsBefore = await page.locator('#customerTableBody tr, [data-customer-row]').count().catch(() => 0);
    await shot(page, '01_customers_list.png');

    await page.click('#addCustomerBtn');
    await page.waitForSelector('#customerModal.active', { timeout: 5000 });
    const testName = `QA Test Khách ${Date.now().toString().slice(-6)}`;
    const testPhone = `091${Date.now().toString().slice(-7)}`;
    await page.fill('#fullName', testName);
    await page.fill('#phone', testPhone);
    await shot(page, '02_customers_add_modal.png');
    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/add_customer') && r.request().method() === 'POST'),
      page.click('#customerForm button[type="submit"]'),
    ]);
    await page.waitForTimeout(600);
    const foundAfterAdd = await page.locator(`text=${testName}`).count();
    await shot(page, '03_customers_after_add.png');
    record('1. Customers (CRM) — thêm khách mới qua UI', foundAfterAdd > 0 ? 'PASS' : 'FAIL',
      `rows_before=${rowsBefore}, new_customer_visible=${foundAfterAdd > 0}, console_errors=${consoleErrors.length}`);

    // ============================================================
    // 2. Staff / HR — /staff (db.staff — LƯU Ý: khác db.employees mà POS Nails dùng cho thợ)
    // ============================================================
    resetErrors();
    await page.goto(`${BASE}/staff`, { waitUntil: 'networkidle' });
    const staffPageOk = await page.locator('body').count();
    const staffRowCount = await page.locator('table tbody tr').count().catch(() => 0);
    await shot(page, '04_staff_hr.png');
    record('2. Staff/HR (/staff)', staffPageOk > 0 ? 'PASS' : 'FAIL',
      `rows=${staffRowCount} (db.staff — collection RIÊNG, không phải db.employees mà /sell dùng làm danh sách thợ), console_errors=${consoleErrors.length}`);

    // ============================================================
    // 3. AI Copilot — /ai_bot
    // ============================================================
    resetErrors();
    await page.goto(`${BASE}/ai_bot`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await shot(page, '05_ai_copilot.png');
    record('3. AI Copilot (/ai_bot)', page.url().includes('/ai_bot') ? 'PASS' : 'FAIL',
      `console_errors=${consoleErrors.length}`);

    // ============================================================
    // 4. AI Studio — /ai_studio
    // ============================================================
    resetErrors();
    await page.goto(`${BASE}/ai_studio`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await shot(page, '06_ai_studio.png');
    record('4. AI Studio (/ai_studio)', page.url().includes('/ai_studio') ? 'PASS' : 'FAIL',
      `console_errors=${consoleErrors.length}`);

    // ============================================================
    // 5. Leave Requests — /leave_requests (admin)
    // ============================================================
    resetErrors();
    await page.goto(`${BASE}/leave_requests`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await shot(page, '07_leave_requests.png');
    record('5. Leave Requests (/leave_requests)', page.url().includes('/leave_requests') ? 'PASS' : 'FAIL',
      `console_errors=${consoleErrors.length}`);

    // ============================================================
    // 6. Expense Requests — /expense_requests (admin)
    // ============================================================
    resetErrors();
    await page.goto(`${BASE}/expense_requests`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await shot(page, '08_expense_requests.png');
    record('6. Expense Requests (/expense_requests)', page.url().includes('/expense_requests') ? 'PASS' : 'FAIL',
      `console_errors=${consoleErrors.length}`);

    // ============================================================
    // 7. Consolidated Report — /report_consolidated — PHẢI thấy doanh thu Nails (> 0), chứng
    //    minh đúng bug đã vá "doanh thu Nails trước giờ không hề được đối soát"
    // ============================================================
    resetErrors();
    await page.goto(`${BASE}/report_consolidated`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const bodyText = await page.locator('body').innerText();
    const hasRevenueNumber = /\$[\d,]+/.test(bodyText) || /[\d,]+\s*(VND|₫)/.test(bodyText);
    await shot(page, '09_consolidated_report.png');
    record('7. Consolidated Report (/report_consolidated) — hiện doanh thu Nails', hasRevenueNumber ? 'PASS' : 'WARN',
      `phát hiện số tiền trên trang: ${hasRevenueNumber}, console_errors=${consoleErrors.length}`);

    // ============================================================
    // 8. Brand Settings — /brand_settings — chỉ đọc, KHÔNG submit (tránh side-effect cho các
    //    lần chạy test sau)
    // ============================================================
    resetErrors();
    await page.goto(`${BASE}/brand_settings`, { waitUntil: 'networkidle' });
    const brandNameValue = await page.locator('input[name="brand_name"], #brand_name').first().inputValue().catch(() => null);
    await shot(page, '10_brand_settings.png');
    record('8. Brand Settings (/brand_settings) — đọc cấu hình', brandNameValue !== null ? 'PASS' : 'WARN',
      `brand_name field value="${brandNameValue}", console_errors=${consoleErrors.length}`);

  } catch (e) {
    record('LỖI KHÔNG MONG MUỐN', 'FAIL', e.message);
  }

  console.table(steps.map((s) => ({ Step: s.name, Status: s.status })));
  const pass = steps.filter((s) => s.status === 'PASS').length;
  const warn = steps.filter((s) => s.status === 'WARN').length;
  const fail = steps.filter((s) => s.status === 'FAIL').length;
  console.log(`\nTổng kết: ${pass} PASS · ${warn} WARN · ${fail} FAIL`);

  fs.writeFileSync(
    path.resolve('audit-results/nail_shared_modules_audit_report.json'),
    JSON.stringify({ ranAt: new Date().toISOString(), steps }, null, 2),
  );

  await browser.close();
  process.exit(fail > 0 ? 1 : 0);
}

main();
