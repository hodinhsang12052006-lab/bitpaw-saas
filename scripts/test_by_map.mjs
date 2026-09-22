// scripts/test_by_map.mjs
// Duyệt map.json theo phase để né rate-limit login (5/15 phút/IP, lưu memory theo process
// Flask). Mỗi phase append vào audit-results/results.json thay vì ghi đè.
// Cách dùng:
//   node scripts/test_by_map.mjs public
//   node scripts/test_by_map.mjs industry nail
//   node scripts/test_by_map.mjs common
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const MAP = JSON.parse(fs.readFileSync('map.json', 'utf-8'));
const BASE = MAP.base_url;
const SHOT_DIR = 'audit-results/screenshots';
const VIDEO_DIR = 'audit-results/videos';
const RESULTS_FILE = 'audit-results/results.json';
fs.mkdirSync(SHOT_DIR, { recursive: true });
fs.mkdirSync(VIDEO_DIR, { recursive: true });

function loadResults() {
  if (fs.existsSync(RESULTS_FILE)) {
    try { return JSON.parse(fs.readFileSync(RESULTS_FILE, 'utf-8')); } catch (_) { return []; }
  }
  return [];
}
function saveResults(results) {
  fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2), 'utf-8');
}

let results = loadResults();
let stt = results.length;

function safeName(name) {
  return name.replace(/[^a-zA-Z0-9_\-]/g, '_');
}

async function visitAndCapture(page, name, urlPath, context) {
  stt += 1;
  const fname = `${String(stt).padStart(3, '0')}_${safeName(name)}.png`;
  const consoleErrors = [];
  const apiErrors = [];

  const consoleListener = (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 500));
  };
  const responseListener = (resp) => {
    const st = resp.status();
    if (st >= 400) apiErrors.push(`${st} ${resp.request().method()} ${resp.url()}`);
  };
  page.on('console', consoleListener);
  page.on('response', responseListener);

  let httpStatus = null;
  let note = '';
  let entryStatus = 'PASS';

  try {
    const resp = await page.goto(`${BASE}${urlPath}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    httpStatus = resp ? resp.status() : null;
    await page.waitForTimeout(1200);

    const bodyText = await page.evaluate(() => document.body ? document.body.innerText.trim() : '');
    if (!bodyText && !(await page.$('img, svg, canvas'))) {
      entryStatus = 'FAIL';
      note += 'Trang trắng (không có nội dung text/hình ảnh). ';
    }
    if (httpStatus && httpStatus >= 500) {
      entryStatus = 'FAIL';
      note += `HTTP ${httpStatus} server error. `;
    }
    const seriousConsoleErrors = consoleErrors.filter(e =>
      !/favicon|ERR_BLOCKED_BY_CLIENT|analytics|gtag|third-party/i.test(e)
    );
    if (seriousConsoleErrors.length > 0) {
      entryStatus = entryStatus === 'FAIL' ? 'FAIL' : 'WARN';
      note += `Console errors: ${seriousConsoleErrors.length}. `;
    }
    const seriousApiErrors = apiErrors.filter(e => !/\/favicon/i.test(e));
    if (seriousApiErrors.length > 0) {
      entryStatus = 'FAIL';
      note += `API errors: ${seriousApiErrors.length}. `;
    }

    await page.screenshot({ path: path.join(SHOT_DIR, fname), fullPage: true });
  } catch (err) {
    entryStatus = 'FAIL';
    note += `Exception: ${err.message}`;
    try { await page.screenshot({ path: path.join(SHOT_DIR, fname), fullPage: true }); } catch (_) {}
  }

  page.off('console', consoleListener);
  page.off('response', responseListener);

  results.push({
    stt, name, path: urlPath, context, httpStatus,
    status: entryStatus, note: note.trim(),
    screenshot: fname,
    consoleErrors: consoleErrors.slice(0, 10),
    apiErrors: apiErrors.slice(0, 10),
  });
  console.log(`[${entryStatus}] #${stt} ${context} :: ${urlPath} (HTTP ${httpStatus})${note ? ' -- ' + note : ''}`);
  saveResults(results);
}

async function login(page, email, password) {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.fill('#loginEmail', email);
  await page.fill('#loginPassword', password);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => null),
    page.click('#btnLogin'),
  ]);
  await page.waitForTimeout(800);
}

async function runPublic(page) {
  for (const p of MAP.public_pages) {
    await visitAndCapture(page, p.name, p.path, 'public');
  }
}

async function runIndustry(page, code) {
  const ind = MAP.industries.find(i => i.code === code);
  if (!ind) throw new Error(`Unknown industry code: ${code}`);
  await login(page, ind.login.email, ind.login.password);
  const loggedInUrl = page.url();
  const loginOk = loggedInUrl && !loggedInUrl.endsWith('/login');
  stt += 1;
  results.push({
    stt, name: `login_${ind.code}`, path: '/login', context: 'auth', httpStatus: null,
    status: loginOk ? 'PASS' : 'FAIL',
    note: loginOk ? `Đăng nhập OK -> ${loggedInUrl}` : 'Đăng nhập THẤT BẠI (vẫn ở trang /login)',
    screenshot: null, consoleErrors: [], apiErrors: [],
  });
  console.log(`[${loginOk ? 'PASS' : 'FAIL'}] login_${ind.code} -> ${loggedInUrl}`);
  saveResults(results);
  if (loginOk) {
    for (const pg of ind.pages) {
      await visitAndCapture(page, `${ind.code}_${pg}`, pg, `industry:${ind.code}`);
    }
  }
  return loginOk;
}

async function runCommon(page) {
  const commonAccount = MAP.industries.find(i => i.code === 'retail') || MAP.industries[0];
  await login(page, commonAccount.login.email, commonAccount.login.password);
  const loggedInUrl = page.url();
  const loginOk = loggedInUrl && !loggedInUrl.endsWith('/login');
  console.log(`[${loginOk ? 'PASS' : 'FAIL'}] login_common(${commonAccount.code}) -> ${loggedInUrl}`);
  if (!loginOk) throw new Error('Common login failed');
  for (const pg of MAP.common_authenticated_pages) {
    await visitAndCapture(page, `common_${pg}`, pg, 'common');
  }
}

async function main() {
  const [, , phase, arg] = process.argv;
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    recordVideo: { dir: VIDEO_DIR, size: { width: 1366, height: 768 } },
  });
  const page = await context.newPage();

  if (phase === 'public') await runPublic(page);
  else if (phase === 'industry') await runIndustry(page, arg);
  else if (phase === 'common') await runCommon(page);
  else throw new Error('Usage: node test_by_map.mjs <public|industry <code>|common>');

  await context.close();
  await browser.close();

  const total = results.length;
  const pass = results.filter(r => r.status === 'PASS').length;
  const warn = results.filter(r => r.status === 'WARN').length;
  const fail = results.filter(r => r.status === 'FAIL').length;
  console.log(`\n=== TỔNG KẾT (lũy kế): ${total} mục | PASS ${pass} | WARN ${warn} | FAIL ${fail} ===`);
}

main().catch(err => { console.error('FATAL:', err); process.exit(1); });
