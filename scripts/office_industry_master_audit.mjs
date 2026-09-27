/**
 * scripts/office_industry_master_audit.mjs
 *
 * QA Master Audit — Office (Văn Phòng) Industry vertical. Ngách mỏng nhất cùng nhóm với
 * Technical (chỉ 'attendance' + 'payroll' trong INDUSTRY_CONFIG) — bảng chấm công kiểu Excel
 * (mỗi nhân viên 1 dòng: giờ vào/ra/OT/trạng thái) + xin nghỉ phép nhanh + bảng vinh danh Kudos.
 *
 * Chạy:  node scripts/office_industry_master_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Mọi selector đã xác minh TRỰC TIẾP bằng grep + đọc code thật trong templates/chamcong_vanphong.html.
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.OFFICE_DEMO_EMAIL || 'demo.office.784966@bitpawdemo.com';
const PASSWORD = process.env.OFFICE_DEMO_PASSWORD || 'DemoBitPaw2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/office_master_audit');
const REPORT_JSON = path.resolve('audit-results/office_master_audit_report.json');
const REPORT_MD = path.resolve('audit-results/office_master_audit_report.md');

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
  console.log('=== OFFICE INDUSTRY MASTER AUDIT — bắt đầu ===\n');
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
  // TEST 1 — Đăng nhập & Bảng chấm công kiểu Excel
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
    if (!afterLoginUrl.includes('vanphong')) throw new Error(`redirect_after_login không đúng — kỳ vọng chứa "vanphong", thực tế: ${afterLoginUrl}`);

    await page.waitForSelector('#officeTable tr', { timeout: 10000 });
    const rowCount = await page.locator('#officeTable tr').count();
    await shot(page, '01_office_launch.png');

    const errorsExcludingFavicon = consoleErrors.filter((e) => !/favicon/i.test(e));
    const pass = errorsExcludingFavicon.length === 0 && networkErrors.length === 0 && rowCount > 0;
    record('1. Đăng Nhập & Bảng Chấm Công Excel', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `URL: ${afterLoginUrl}. Số dòng nhân viên: ${rowCount}. console_errors=${consoleErrors.length}`);
  } catch (e) {
    record('1. Đăng Nhập & Bảng Chấm Công Excel', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_office_launch_FAILED.png').catch(() => {});
    await finalize({ browser, results, findings });
    process.exit(1);
  }

  // ============================================================
  // TEST 2 — Ghi nhận chấm công 1 nhân viên (giờ vào/ra/OT/trạng thái)
  // ============================================================
  t0 = Date.now();
  try {
    // Dòng đã lưu trong ngày bị khoá (input disabled) — không phải bug, là chặn sửa lại chấm
    // công đã chốt. Chọn dòng ĐẦU TIÊN chưa khoá để script chạy lại nhiều lần trong ngày vẫn ổn
    // định, thay vì luôn lấy .first() (sẽ luôn trúng dòng đã khoá từ lần chạy trước đó).
    const openRow = page.locator('#officeTable tr').filter({ has: page.locator('input[id^="in_"]:not([disabled])') }).first();
    const maNv = await openRow.locator('input[id^="in_"]').first().getAttribute('id').then((id) => id.replace('in_', ''));

    await page.fill(`#in_${maNv}`, '08:00');
    await page.fill(`#out_${maNv}`, '17:30');
    await page.fill(`#ot_${maNv}`, '1.5');
    await page.selectOption(`#status_${maNv}`, 'Có mặt');

    const [saveResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/hr/chamcong') && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate((id) => window.saveRow(id), maNv),
    ]);
    const status = saveResp.status();
    const body = await saveResp.json().catch(() => null);
    await page.waitForTimeout(500);
    await shot(page, '02_office_attendance_saved.png');

    const rowDisabled = await page.locator(`#in_${maNv}`).isDisabled().catch(() => false);

    const pass = status === 200 && body?.success !== false && rowDisabled;
    record('2. Ghi Nhận Chấm Công (Giờ Vào/Ra/OT)', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Nhân viên ${maNv}: 08:00-17:30, OT 1.5h, "Có mặt". HTTP ${status}. Dòng đã khoá sau khi lưu: ${rowDisabled}.`);
  } catch (e) {
    record('2. Ghi Nhận Chấm Công (Giờ Vào/Ra/OT)', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_office_attendance_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 3 — Duyệt nghỉ phép siêu tốc
  // ============================================================
  t0 = Date.now();
  try {
    await page.reload({ waitUntil: 'networkidle' });
    // <option> không bao giờ được Playwright coi là "visible" — chờ số lượng option nạp xong.
    await page.waitForFunction(() => document.querySelectorAll('#nv_xin_phep option').length > 1, { timeout: 8000 });
    await page.selectOption('#nv_xin_phep', { index: 1 });
    await page.selectOption('#loai_nghi', 'Nghỉ Phép');
    await page.fill('#ly_do_nghi', 'QA Audit — kiểm tra luồng duyệt nghỉ phép siêu tốc.');
    await shot(page, '03a_office_leave_form_filled.png');

    const [leaveResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/hr/chamcong') && res.request().method() === 'POST', { timeout: 10000 }).catch(() => null),
      page.evaluate(() => window.duyetNghiPhep()),
    ]);
    await page.waitForTimeout(500);
    await shot(page, '03b_office_leave_approved.png');

    const leaveStatus = leaveResp ? leaveResp.status() : null;
    const leaveBody = leaveResp ? await leaveResp.json().catch(() => null) : null;

    const pass = leaveResp !== null && leaveStatus === 200 && leaveBody?.success !== false;
    record('3. Duyệt Nghỉ Phép Siêu Tốc', pass ? 'PASS' : 'WARN', Date.now() - t0,
      leaveResp ? `HTTP ${leaveStatus}, body=${JSON.stringify(leaveBody).slice(0, 150)}` : 'Không bắt được request POST /api/hr/chamcong nào — kiểm tra lại hàm duyetNghiPhep().');
  } catch (e) {
    record('3. Duyệt Nghỉ Phép Siêu Tốc', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_office_leave_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 4 — Bảng vinh danh Kudos + Module dùng chung
  // ============================================================
  t0 = Date.now();
  try {
    const kudoText = await page.locator('#kudoList').innerText().catch(() => '');
    await shot(page, '04a_office_kudos.png');

    const sharedPages = ['/customers', '/ai_bot', '/nhanvien', '/report'];
    const sharedResults = [];
    for (const url of sharedPages) {
      const resp = await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle' }).catch((e) => ({ _err: e.message }));
      const status = resp && resp.status ? resp.status() : null;
      sharedResults.push(`${url}=${status ?? 'ERR'}`);
    }
    await shot(page, '04b_office_shared_modules.png');

    const allOk = sharedResults.every((r) => r.endsWith('=200'));
    const pass = kudoText.length > 0 && allOk;
    record('4. Bảng Vinh Danh Kudos + Module Dùng Chung', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Kudos: "${kudoText.slice(0, 100).replace(/\s+/g, ' ')}". Shared: ${sharedResults.join(', ')}`);
  } catch (e) {
    record('4. Bảng Vinh Danh Kudos + Module Dùng Chung', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '04_office_kudos_FAILED.png').catch(() => {});
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
    '# Office Industry Master Audit Report',
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
