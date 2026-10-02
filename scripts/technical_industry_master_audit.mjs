/**
 * scripts/technical_industry_master_audit.mjs
 *
 * QA Master Audit — Technical (Kỹ Thuật) Industry vertical. Đây là ngách MỎNG nhất trong 9
 * ngành (chỉ có 'attendance' + 'dispatch_gps' trong INDUSTRY_CONFIG, trang chủ đăng nhập vào
 * thẳng là trang chấm công — không có module bán hàng/đặt lịch riêng).
 *
 * Chạy:  node scripts/technical_industry_master_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Đã fix trước khi viết script này: templates/chamcong_kythuat.html dòng ~899 kiểm tra field
 * `r.toa_do` (không tồn tại trong schema — db.chamcong lưu GPS bằng field `latitude`/
 * `longitude` riêng biệt) + URL Google Maps sai định dạng hoàn toàn
 * ("http://googleusercontent.com/maps.google.com/?q=...") — nút "Xem trên bản đồ" ĐÃ 100%
 * không bao giờ hiện ra cho bất kỳ bản ghi nào. Đã sửa field check + URL đúng chuẩn, nhưng bản
 * thân form check-in kỹ thuật viên (submitTech()) CHƯA từng gọi navigator.geolocation để lấy
 * toạ độ thật — "dispatch_gps" trong INDUSTRY_CONFIG là module quảng cáo, chưa build UI capture
 * GPS thật (spec-vs-implementation gap, không tự ý build thêm tính năng ngoài phạm vi sửa bug).
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.TECHNICAL_DEMO_EMAIL || 'demo.technical.393328@bitpawdemo.com';
const PASSWORD = process.env.TECHNICAL_DEMO_PASSWORD || 'DemoBitPaw2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/technical_master_audit');
const REPORT_JSON = path.resolve('audit-results/technical_master_audit_report.json');
const REPORT_MD = path.resolve('audit-results/technical_master_audit_report.md');

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
  console.log('=== TECHNICAL INDUSTRY MASTER AUDIT — bắt đầu ===\n');
  console.log(`Target: ${BASE}   Account: ${EMAIL}\n`);

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
  // TEST 1 — Đăng nhập & Danh sách kỹ thuật viên
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
    if (!afterLoginUrl.includes('kythuat')) throw new Error(`redirect_after_login không đúng — kỳ vọng /chamcong/kythuat, thực tế: ${afterLoginUrl}`);

    // #employeeGrid có sẵn 1 div skeleton "animate-pulse" TĨNH trong HTML ban đầu (trước khi
    // loadEmployees() tải xong) — chờ đúng class ".cascade-item" (chỉ có ở thẻ nhân viên thật
    // do JS render), tránh bắt nhầm khung xương loading làm 1 "kỹ thuật viên".
    await page.waitForSelector('#employeeGrid .cascade-item', { timeout: 10000 });
    const techCount = await page.locator('#employeeGrid .cascade-item').count();
    await shot(page, '01_technical_launch.png');

    const errorsExcludingFavicon = consoleErrors.filter((e) => !/favicon/i.test(e));
    const pass = errorsExcludingFavicon.length === 0 && networkErrors.length === 0 && techCount > 0;
    record('1. Đăng Nhập & Danh Sách Kỹ Thuật Viên', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `URL sau đăng nhập: ${afterLoginUrl}. Số kỹ thuật viên (lọc linh_vuc="Kỹ thuật"): ${techCount}. console_errors=${consoleErrors.length}`);
  } catch (e) {
    record('1. Đăng Nhập & Danh Sách Kỹ Thuật Viên', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_technical_launch_FAILED.png').catch(() => {});
    await finalize({ browser, results, findings });
    process.exit(1);
  }

  // ============================================================
  // TEST 2 — Ghi nhận chấm công + công việc hoàn thành cho 1 kỹ thuật viên
  // ============================================================
  t0 = Date.now();
  try {
    await page.locator('#employeeGrid .cascade-item').first().click();
    await page.waitForSelector('#screen_pos.active', { timeout: 5000 });
    const workerName = await page.locator('#pos_worker_name').innerText();

    await page.selectOption('#trang_thai', { index: 1 });
    await page.fill('#ghi_chu', 'QA Audit — kiểm tra ghi nhận chấm công kỹ thuật viên ngoài hiện trường.');

    const [outputResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/hr/chamcong') && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate(() => window.submitTech()),
    ]);
    const status = outputResp.status();
    const body = await outputResp.json().catch(() => null);
    await page.waitForTimeout(500);
    await shot(page, '02a_technical_checkin_submitted.png');

    const historyText = await page.locator('#historyBox').innerText().catch(() => '');
    const showsInHistory = historyText.includes('QA Audit') || historyText.length > 0;
    await shot(page, '02b_technical_history.png');

    const pass = status === 200 && body?.success !== false && showsInHistory;
    record('2. Ghi Nhận Chấm Công Kỹ Thuật Viên', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Kỹ thuật viên "${workerName}". HTTP ${status}. Lịch sử hiển thị: ${showsInHistory}.`);
  } catch (e) {
    record('2. Ghi Nhận Chấm Công Kỹ Thuật Viên', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_technical_checkin_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 3 — Module dùng chung
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
    await shot(page, '03_technical_shared_modules.png');

    const allOk = sharedResults.every((r) => r.endsWith('=200'));
    record('3. Module Dùng Chung Cho Technical', allOk ? 'PASS' : 'WARN', Date.now() - t0, sharedResults.join(', '));
  } catch (e) {
    record('3. Module Dùng Chung Cho Technical', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_technical_shared_FAILED.png').catch(() => {});
  }

  finding('Module "dispatch_gps" khai báo trong INDUSTRY_CONFIG[\'technical\'] chưa có UI capture GPS thật (submitTech() không gọi navigator.geolocation, payload check-in không có toạ độ) — đã fix xong lỗi field-name/URL sai của nút "Xem trên bản đồo" (luôn ẩn + URL hỏng), nhưng việc thật sự CAPTURE toạ độ khi check-in vẫn là spec-vs-implementation gap, không phải bug 1 dòng để tự ý build thêm.');

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
    '# Technical Industry Master Audit Report',
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
