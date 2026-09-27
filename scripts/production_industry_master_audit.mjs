/**
 * scripts/production_industry_master_audit.mjs
 *
 * QA Master Audit — Production (Sản Xuất) Industry vertical: ghi nhận sản lượng công nhân
 * (/production_output), quản lý nguyên vật liệu + công thức tiêu hao NVL theo sản lượng
 * (/production/materials).
 *
 * Chạy:  node scripts/production_industry_master_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Mọi selector đã xác minh TRỰC TIẾP bằng grep + đọc code thật trong
 * templates/production_output.html, templates/production_materials.html, app.py.
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.PRODUCTION_DEMO_EMAIL || 'demo.production.393328@bitpawdemo.com';
const PASSWORD = process.env.PRODUCTION_DEMO_PASSWORD || 'DemoBitPaw2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/production_master_audit');
const REPORT_JSON = path.resolve('audit-results/production_master_audit_report.json');
const REPORT_MD = path.resolve('audit-results/production_master_audit_report.md');

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
  console.log('=== PRODUCTION INDUSTRY MASTER AUDIT — bắt đầu ===\n');
  console.log(`Target: ${BASE}   Account: ${EMAIL}\n`);

  const consoleErrors = [];
  const networkErrors = [];
  const stageName = 'QA Audit Stage ' + Date.now();

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('response', (res) => { if (res.status() >= 500) networkErrors.push(`${res.status()} ${res.request().method()} ${res.url()}`); });
  page.on('dialog', async (d) => { await d.accept(); });

  // ============================================================
  // TEST 1 — Đăng nhập & Ghi nhận sản lượng công nhân
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

    await page.goto(`${BASE}/production_output`, { waitUntil: 'networkidle' });
    // <option> không bao giờ được Playwright coi là "visible" (render bởi UI dropdown của hệ
    // điều hành, không phải layout thường) — chờ số lượng option nạp xong thay vì chờ visible.
    await page.waitForFunction(() => document.querySelectorAll('#logWorker option').length > 1, { timeout: 10000 });
    await shot(page, '01_production_launch.png');

    await page.selectOption('#logWorker', { index: 1 });
    const workerLabel = await page.locator('#logWorker').inputValue();
    await page.fill('#logStage', stageName);
    await page.fill('#logQty', '20');
    await page.selectOption('#logShift', { index: 1 });

    const [outputResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/production/output') && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate(() => window.submitOutput()),
    ]);
    const outputStatus = outputResp.status();
    const outputBody = await outputResp.json().catch(() => null);
    await page.waitForTimeout(500);
    await shot(page, '01b_production_output_logged.png');

    const recentText = await page.locator('#recentEntries').innerText();
    const showsInRecent = recentText.includes(stageName) || recentText.includes('20');

    const errorsExcludingFavicon = consoleErrors.filter((e) => !/favicon/i.test(e));
    const pass = outputStatus === 200 && outputBody?.success === true && errorsExcludingFavicon.length === 0 && networkErrors.length === 0 && showsInRecent;
    record('1. Đăng Nhập & Ghi Nhận Sản Lượng Công Nhân', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Công nhân "${workerLabel}", công đoạn "${stageName}", số lượng 20. HTTP ${outputStatus}. Hiện trong "Bản Ghi Gần Đây": ${showsInRecent}. console_errors=${consoleErrors.length}`);
  } catch (e) {
    record('1. Đăng Nhập & Ghi Nhận Sản Lượng Công Nhân', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '01_production_launch_FAILED.png').catch(() => {});
    await finalize({ browser, results, findings });
    process.exit(1);
  }

  // ============================================================
  // TEST 2 — Nguyên vật liệu + Công thức: tạo NVL, tạo công thức khớp công đoạn, ghi thêm sản
  // lượng cho ĐÚNG công đoạn đó -> xác nhận tồn kho NVL bị trừ đúng công thức.
  // ============================================================
  t0 = Date.now();
  try {
    await page.goto(`${BASE}/production/materials`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#newMaterialName', { timeout: 8000 });

    const materialName = 'QA Audit Vải ' + Date.now();
    await page.fill('#newMaterialName', materialName);
    await page.fill('#newMaterialUnit', 'm');
    await page.fill('#newMaterialStock', '100');

    const [createMatResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/production/materials') && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate(() => window.addMaterial()),
    ]);
    const matBody = await createMatResp.json().catch(() => null);
    const materialId = matBody?.data?.id;
    await page.waitForTimeout(400);
    await shot(page, '02a_production_material_created.png');

    // Tạo công thức: 1 đơn vị sản lượng của `stageName` (Test 1) tiêu 2m vải/đơn vị
    await page.fill('#recipeOutputName', stageName);
    await page.evaluate(() => { document.getElementById('recipeMaterialRows').innerHTML = ''; window.addRecipeMaterialRow(); });
    await page.waitForTimeout(200);
    await page.selectOption('.recipe-material-select', String(materialId));
    await page.fill('.recipe-qty-input', '2');

    const [recipeResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/production/recipes') && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate(() => window.saveRecipe()),
    ]);
    const recipeStatus = recipeResp.status();
    const recipeBody = await recipeResp.json().catch(() => null);
    await page.waitForTimeout(400);
    await shot(page, '02b_production_recipe_saved.png');

    // Ghi thêm 10 đơn vị sản lượng cho ĐÚNG công đoạn có công thức -> kỳ vọng trừ 20m vải (10 x 2)
    await page.goto(`${BASE}/production_output`, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.querySelectorAll('#logWorker option').length > 1, { timeout: 8000 });
    await page.selectOption('#logWorker', { index: 1 });
    await page.fill('#logStage', stageName);
    await page.fill('#logQty', '10');
    await page.selectOption('#logShift', { index: 1 });

    const [output2Resp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/production/output') && res.request().method() === 'POST', { timeout: 10000 }),
      page.evaluate(() => window.submitOutput()),
    ]);
    const output2Body = await output2Resp.json().catch(() => null);
    await page.waitForTimeout(300);
    await shot(page, '02c_production_output_with_recipe.png');

    // Xác nhận tồn kho NVL đã bị trừ đúng 20m (100 - 20 = 80) qua API list
    const materialsCheck = await page.evaluate(async () => {
      const r = await fetch('/api/production/materials');
      return r.json();
    });
    const updatedMaterial = (materialsCheck.data || []).find((m) => m.id === materialId);
    const stockCorrect = updatedMaterial && Math.abs(updatedMaterial.stock_qty - 80) < 0.01;
    await shot(page, '02d_production_material_stock_after.png');

    const pass = createMatResp.status() === 200 && recipeStatus === 200 && recipeBody?.success === true &&
      output2Body?.success === true && stockCorrect;
    record('2. Nguyên Vật Liệu & Công Thức Tiêu Hao Tự Động', pass ? 'PASS' : 'FAIL', Date.now() - t0,
      `NVL "${materialName}" (id=${materialId}) tồn 100m. Công thức "${stageName}": 2m/đơn vị. Ghi thêm 10 đơn vị -> kỳ vọng còn 80m, thực tế ${updatedMaterial?.stock_qty}m. material_warnings=${JSON.stringify(output2Body?.material_warnings)}`);

    if (!stockCorrect) {
      finding(`Tồn kho NVL sau khi ghi sản lượng theo công thức không khớp kỳ vọng (mong 80m, thực tế ${updatedMaterial?.stock_qty}m) — kiểm tra lại _consume_recipe_materials() hoặc khớp tên công đoạn (normalize/lowercase).`);
    }
  } catch (e) {
    record('2. Nguyên Vật Liệu & Công Thức Tiêu Hao Tự Động', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '02_production_materials_FAILED.png').catch(() => {});
  }

  // ============================================================
  // TEST 3 — Chấm công công nhân + Module dùng chung
  // ============================================================
  t0 = Date.now();
  try {
    const errorsBefore = consoleErrors.length;
    await page.goto(`${BASE}/chamcong_congnhan`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    const bodyText = await page.locator('body').innerText();
    const newErrors = consoleErrors.length - errorsBefore;
    await shot(page, '03_production_chamcong.png');

    const sharedPages = ['/customers', '/ai_bot', '/nhanvien', '/report'];
    const sharedResults = [];
    for (const url of sharedPages) {
      const resp = await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle' }).catch((e) => ({ _err: e.message }));
      const status = resp && resp.status ? resp.status() : null;
      sharedResults.push(`${url}=${status ?? 'ERR'}`);
    }
    const allSharedOk = sharedResults.every((r) => r.endsWith('=200'));

    const pass = bodyText.length > 50 && newErrors === 0 && allSharedOk;
    record('3. Chấm Công Công Nhân + Module Dùng Chung', pass ? 'PASS' : 'WARN', Date.now() - t0,
      `Chấm công: ${bodyText.length} ký tự, ${newErrors} lỗi console mới. Shared: ${sharedResults.join(', ')}`);
  } catch (e) {
    record('3. Chấm Công Công Nhân + Module Dùng Chung', 'FAIL', Date.now() - t0, e.message);
    await shot(page, '03_production_chamcong_FAILED.png').catch(() => {});
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
    '# Production Industry Master Audit Report',
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
