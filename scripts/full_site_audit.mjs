// Quét TOÀN BỘ trang của 1 tenant demo (mọi route GET không tham số của app.py + mọi link nội bộ tìm
// thấy trên trang), trên desktop 1440x900; các trang có trong sidebar quét thêm ở mobile 390x844.
// Mỗi trang ghi lại: HTTP status, lỗi JS (pageerror/console.error), request lỗi cùng origin, ảnh vỡ,
// tràn ngang cuộn được, NÚT GỌI HÀM KHÔNG TỒN TẠI (onclick/onchange/onsubmit...), link nội bộ hỏng.
// KHÔNG bấm/tải link có dấu hiệu thao tác ghi dữ liệu qua GET (delete/toggle/logout/reset...).
//
// Chạy: TENANT=nail ROUTES=<routes.json> OUT=<thư mục> node scripts/full_site_audit.mjs
//   (routes.json xuất từ app.url_map — xem scripts/README hoặc audit-results/FINDINGS_LOG.md Pha 10)
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const TENANTS = {
  nail: ['demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!'],
  fnb: ['demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!'],
  spa: ['demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!'],
  retail: ['demo.retail.596348@bitpawdemo.com', 'DemoBitPaw2026!'],
  karaoke: ['demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!'],
  hotel: ['demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!'],
  production: ['demo.production.393328@bitpawdemo.com', 'DemoBitPaw2026!'],
  technical: ['demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!'],
  office: ['demo.office.784966@bitpawdemo.com', 'DemoBitPaw2026!'],
};
const TENANT = process.env.TENANT;
const OUT = path.resolve(process.env.OUT || 'audit-results/full_site_audit');
const routes = JSON.parse(fs.readFileSync(process.env.ROUTES, 'utf8'));
// Route không phải trang HTML / có tác dụng phụ khi GET / cố ý lỗi -> không quét như trang thường
const SKIP = new Set(['/logout', '/debug-sentry', '/sitemap.xml', '/favicon.ico', '/omnichannel/status',
  '/ad-assistant/api/facebook-status', '/ad-assistant/api/campaigns']);
const UNSAFE = /logout|delete|xoa|remove|toggle|reset|clear|cancel|approve|reject|refund|duyet|huy|\/pay\b|checkin|checkout\/\d|export|download|backup\/create|restore|seed|cron/i;
const ENV_NOISE = /ERR_CONNECTION_RESET|ERR_NO_BUFFER_SPACE|ERR_ABORTED|ERR_NETWORK_CHANGED|ERR_INTERNET_DISCONNECTED/;

if (!TENANTS[TENANT]) throw new Error('TENANT phải là 1 trong: ' + Object.keys(TENANTS).join(', '));
const [EMAIL, PASSWORD] = TENANTS[TENANT];
const shotDir = path.join(OUT, TENANT);
fs.mkdirSync(shotDir, { recursive: true });

const pageRoutes = routes.filter((r) => r.methods.includes('GET') && !r.args.length && !r.rule.startsWith('/api/') && !SKIP.has(r.rule)).map((r) => r.rule);

async function measure(page) {
  return page.evaluate(() => {
    const vw = innerWidth;
    const htmlOx = getComputedStyle(document.documentElement).overflowX;
    const vox = htmlOx !== 'visible' ? htmlOx : getComputedStyle(document.body).overflowX;
    const sw = document.scrollingElement.scrollWidth;
    const overflowX = vox !== 'hidden' && vox !== 'clip' && sw > vw + 1;
    let offender = null;
    if (overflowX) {
      for (const el of document.body.querySelectorAll('*')) {
        const r = el.getBoundingClientRect();
        if (r.right > vw + 1 && r.width > 0 && r.width < sw) { offender = (el.tagName + '.' + String(el.className).split(' ').slice(0, 3).join('.')).slice(0, 80); break; }
      }
    }
    const brokenImages = [...document.images].filter((i) => i.complete && i.naturalWidth === 0 && i.src && !i.src.startsWith('data:') && getComputedStyle(i).display !== 'none').map((i) => i.src.slice(0, 120));
    // Hàm được gọi trong thuộc tính on* nhưng không tồn tại (kể cả khai báo const/let toàn cục)
    const SKIPN = new Set(['this', 'event', 'window', 'document', 'location', 'history', 'alert', 'confirm', 'prompt', 'if', 'return', 'setTimeout', 'clearTimeout', 'parseInt', 'parseFloat', 'Number', 'String', 'encodeURIComponent', 'JSON', 'Math', 'navigator', 'console', 'fetch', 'open', 'print', 'void', 'typeof', 'new', 'function']);
    const missing = new Set();
    const attrs = ['onclick', 'onchange', 'onsubmit', 'oninput', 'onkeyup', 'onkeydown', 'onkeypress', 'onblur', 'onfocus', 'onmouseover', 'onload', 'onerror'];
    for (const el of document.querySelectorAll(attrs.map((a) => `[${a}]`).join(','))) {
      for (const a of attrs) {
        const code = el.getAttribute(a); if (!code) continue;
        const stripped = code.replace(/(['"`])(?:\\.|(?!\1).)*\1/g, '""');
        for (const m of stripped.matchAll(/(^|[^.\w$])([A-Za-z_$][\w$]*)\s*\(/g)) {
          const name = m[2];
          if (SKIPN.has(name)) continue;
          let t;
          try { t = new Function(`return typeof ${name}`)(); } catch (e) { t = 'error'; }
          if (t !== 'function') missing.add(`${name}() [${a} trên <${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}>]`);
        }
      }
    }
    const links = [...document.querySelectorAll('a[href]')].map((a) => a.getAttribute('href'))
      .filter((h) => h && h.startsWith('/') && !h.startsWith('//') && !h.startsWith('/static/'))
      .map((h) => h.split('#')[0]).filter(Boolean);
    const sidebar = [...document.querySelectorAll('#app-sidebar a[href]')].map((a) => a.getAttribute('href')).filter((h) => h && h.startsWith('/'));
    return { overflowX, scrollWidth: sw, offender, brokenImages, missingHandlers: [...missing], links: [...new Set(links)], sidebar: [...new Set(sidebar)], title: document.title.slice(0, 80) };
  });
}

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.addCookies([{ name: 'bitpaw_lang', value: 'en', url: BASE }]);
const page = await ctx.newPage();
page.on('dialog', (d) => d.dismiss().catch(() => {}));
let cur = null;
page.on('console', (m) => { if (cur && m.type() === 'error') cur.consoleErrors.push(m.text().slice(0, 220)); });
page.on('pageerror', (e) => { if (cur) cur.pageErrors.push(String(e).slice(0, 220)); });
page.on('response', (r) => { if (cur && r.url().startsWith(BASE) && r.status() >= 400) cur.badResponses.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '').slice(0, 100)}`); });

await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
await page.fill('#loginEmail', EMAIL);
await page.fill('#loginPassword', PASSWORD);
await Promise.all([page.waitForLoadState('networkidle').catch(() => {}), page.click('#btnLogin')]);
await page.waitForTimeout(1200);
if (page.url().includes('/login')) throw new Error(`Đăng nhập ${TENANT} thất bại`);
const home = page.url().replace(BASE, '');

const results = [];
async function audit(url, viewport, shot) {
  await page.setViewportSize(viewport);
  cur = { url, viewport: viewport.width, consoleErrors: [], pageErrors: [], badResponses: [] };
  let status = null;
  for (let i = 0; i < 3; i++) {
    try {
      const resp = await page.goto(BASE + url, { waitUntil: 'load', timeout: 25000 });
      status = resp ? resp.status() : null;
      break;
    } catch (e) {
      if (i === 2) { cur.pageErrors.push('NAV FAIL ' + e.message.split('\n')[0]); }
      cur.consoleErrors = []; cur.badResponses = [];
    }
  }
  await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(500);
  let m = {};
  try { m = await measure(page); } catch (e) { cur.pageErrors.push('MEASURE ' + e.message.split('\n')[0]); }
  const finalUrl = page.url().replace(BASE, '');
  const realConsole = cur.consoleErrors.filter((t) => !ENV_NOISE.test(t));
  const issues = [];
  if (status && status >= 500) issues.push(`HTTP ${status}`);
  if (cur.pageErrors.length) issues.push(`${cur.pageErrors.length} lỗi JS`);
  if (realConsole.length) issues.push(`${realConsole.length} console.error`);
  if (cur.badResponses.length) issues.push(`${cur.badResponses.length} request lỗi`);
  if (m.overflowX) issues.push(`tràn ngang ${m.scrollWidth}px`);
  if (m.brokenImages && m.brokenImages.length) issues.push(`${m.brokenImages.length} ảnh vỡ`);
  if (m.missingHandlers && m.missingHandlers.length) issues.push(`${m.missingHandlers.length} nút gọi hàm không tồn tại`);
  const file = `${viewport.width}_${url.replace(/[^\w]+/g, '_').replace(/^_|_$/g, '') || 'root'}.png`;
  if (shot || issues.length) await safeScreenshot(page, { path: path.join(shotDir, file) });
  const rec = { url, finalUrl, viewport: viewport.width, status, title: m.title, issues, pageErrors: cur.pageErrors, consoleErrors: realConsole,
    envNoise: cur.consoleErrors.length - realConsole.length, badResponses: [...new Set(cur.badResponses)], offender: m.offender,
    brokenImages: m.brokenImages, missingHandlers: m.missingHandlers, screenshot: (shot || issues.length) ? file : null };
  results.push(rec);
  cur = null;
  console.log(`${issues.length ? '⚠️ ' : '✅'} [${viewport.width}] ${url}${finalUrl !== url ? ' → ' + finalUrl : ''} ${issues.join(' | ')}`);
  return m;
}

// 1) Trang chính + sidebar (desktop + mobile, có ảnh chụp)
const first = await audit(home, { width: 1440, height: 900 }, true);
const sidebar = (first.sidebar || []).filter((h) => !UNSAFE.test(h) && h !== '/logout');
const linkSet = new Set(first.links || []);
for (const s of sidebar) {
  const m = await audit(s, { width: 1440, height: 900 }, true);
  (m.links || []).forEach((l) => linkSet.add(l));
}
for (const s of [home, ...sidebar]) await audit(s, { width: 390, height: 844 }, true);
// 2) Mọi route trang còn lại của app.py (desktop) — bắt lỗi 500/JS ở cả trang không có trong menu
const done = new Set([home, ...sidebar]);
for (const r of pageRoutes) {
  if (done.has(r)) continue;
  done.add(r);
  const m = await audit(r, { width: 1440, height: 900 }, false);
  (m.links || []).forEach((l) => linkSet.add(l));
}
// 3) Link nội bộ tìm thấy trên các trang: kiểm tra mã HTTP (GET, không theo link có tác dụng phụ)
const linkResults = [];
for (const l of [...linkSet].filter((l) => !UNSAFE.test(l) && !done.has(l.split('?')[0]))) {
  const r = await ctx.request.get(BASE + l, { maxRedirects: 5, timeout: 20000 }).catch((e) => ({ status: () => 'ERR ' + e.message.slice(0, 60) }));
  const st = r.status();
  linkResults.push({ link: l, status: st });
  if (typeof st !== 'number' || st >= 400) console.log(`⚠️  link ${l} -> ${st}`);
}
await browser.close();

const flagged = results.filter((r) => r.issues.length);
fs.writeFileSync(path.join(OUT, `${TENANT}.json`), JSON.stringify({ tenant: TENANT, home, pages: results, links: linkResults }, null, 1));
console.log(`\nTổng kết ${TENANT}: ${results.length} lượt trang (${results.length - flagged.length} sạch, ${flagged.length} có vấn đề) · ${linkResults.length} link nội bộ (${linkResults.filter((l) => typeof l.status !== 'number' || l.status >= 400).length} hỏng)`);
