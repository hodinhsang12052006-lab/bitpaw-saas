// Bắt lỗi "mở trang lên ổn, đợi vài giây thì lỗi": mở từng trang trong menu của 1 ngành, NGỒI LẠI LINGER giây (mặc định 35s
// — quá 1 chu kỳ luồng real-time SSE 25s tự nối lại) trên MÁY TÍNH (1440x900) và ĐIỆN THOẠI (giả lập iPhone 13: UA iOS, cảm
// ứng), ghi lại MỌI lỗi kèm giây thứ mấy nó xuất hiện: lỗi JS, console.error, request cùng origin trả >=400 hoặc rớt,
// thông báo lỗi (toast/alert) hiện lên muộn, tràn ngang trên điện thoại. Chụp ảnh toàn trang cuối lượt để soi bằng mắt.
//
// Chạy: TENANT=nail [LINGER=35] [POOL=6] node scripts/linger_audit.mjs     (CHỈ server local 127.0.0.1:5001)
import { chromium, devices } from 'playwright';
import fs from 'fs';
import path from 'path';

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
const LINGER = Number(process.env.LINGER || 35) * 1000;
const POOL = Number(process.env.POOL || 6);
const OUT = path.resolve('audit-results/linger_audit');
const UNSAFE = /logout|delete|xoa|remove|toggle|reset|clear|cancel|approve|reject|refund|duyet|huy|\/pay\b|checkin|checkout\/\d|export|download|backup\/create|restore|seed|cron/i;
const ENV_NOISE = /ERR_CONNECTION_RESET|ERR_NO_BUFFER_SPACE|ERR_NETWORK_CHANGED|ERR_INTERNET_DISCONNECTED/;
const ERR_TEXT = /lỗi|error|failed|thất bại|không thể|could not|couldn't|unable|không tải được|exception|undefined|NaN|null\b/i;
if (!TENANTS[TENANT]) throw new Error('TENANT phải là 1 trong: ' + Object.keys(TENANTS).join(', '));
const [EMAIL, PASSWORD] = TENANTS[TENANT];
const shotDir = path.join(OUT, TENANT);
fs.mkdirSync(shotDir, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const DEVICES = { desktop: { viewport: { width: 1440, height: 900 } }, mobile: { ...iphone, deviceScaleFactor: 2 } };

// đăng nhập 1 lần, dùng lại phiên cho mọi tab của cả 2 thiết bị
const loginCtx = await browser.newContext(DEVICES.desktop);
await loginCtx.addCookies([{ name: 'bitpaw_lang', value: 'en', url: BASE }]);
const lp = await loginCtx.newPage();
await lp.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
await lp.fill('#loginEmail', EMAIL);
await lp.fill('#loginPassword', PASSWORD);
await Promise.all([lp.waitForLoadState('networkidle').catch(() => {}), lp.click('#btnLogin')]);
await lp.waitForTimeout(1500);
if (lp.url().includes('/login')) throw new Error(`Đăng nhập ${TENANT} thất bại`);
const home = lp.url().replace(BASE, '').split('#')[0];
const sidebarOf = async () => lp.evaluate(() => [...new Set([...document.querySelectorAll('#app-sidebar a[href]')].map((a) => a.getAttribute('href')).filter((h) => h && h.startsWith('/')))]);
let menu = await sidebarOf();
if (!menu.length) { await lp.goto(BASE + '/ai_bot', { waitUntil: 'networkidle' }).catch(() => {}); menu = await sidebarOf(); }
// Git Bash tự đổi "/nhanvien" thành "C:/Program Files/Git/nhanvien" khi truyền qua biến môi trường -> gỡ lại
const pages = process.env.PAGES ? process.env.PAGES.split(',').map((x) => x.replace(/^[A-Za-z]:\/[^,]*?\/Git(?=\/)/, ''))  // PAGES=/a,/b: chỉ quét đúng các trang này
  : [...new Set([home, ...menu.map((h) => h.split('#')[0]), '/app_nhanvien'])].filter((h) => h !== '/logout' && !UNSAFE.test(h));
const state = await loginCtx.storageState();
await loginCtx.close();
console.log(`${TENANT}: ${pages.length} trang × 2 thiết bị, ngồi lại ${LINGER / 1000}s mỗi trang, ${POOL} tab song song`);

async function lingerOne(ctx, device, url) {
  const page = await ctx.newPage();
  const ev = [];
  let t0 = Date.now();
  const at = () => Math.round((Date.now() - t0) / 100) / 10;
  page.on('dialog', (d) => { ev.push({ t: at(), kind: 'dialog', text: d.message().slice(0, 160) }); d.dismiss().catch(() => {}); });
  page.on('pageerror', (e) => ev.push({ t: at(), kind: 'js_error', text: String(e).slice(0, 200) }));
  page.on('console', (m) => { if (m.type() === 'error' && !ENV_NOISE.test(m.text())) ev.push({ t: at(), kind: 'console_error', text: m.text().slice(0, 200) }); });
  page.on('response', (r) => {
    if (r.url().startsWith(BASE) && r.status() >= 400) ev.push({ t: at(), kind: 'http_' + r.status(), text: `${r.request().method()} ${r.url().replace(BASE, '').slice(0, 110)}` });
  });
  page.on('requestfailed', (r) => {
    const f = r.failure()?.errorText || '';
    if (r.url().startsWith(BASE) && !/ERR_ABORTED/.test(f) && !ENV_NOISE.test(f)) ev.push({ t: at(), kind: 'request_failed', text: `${f} ${r.url().replace(BASE, '').slice(0, 100)}` });
  });
  let status = null;
  try {
    const resp = await page.goto(BASE + url, { waitUntil: 'load', timeout: 30000 });
    status = resp ? resp.status() : null;
  } catch (e) { ev.push({ t: at(), kind: 'nav_fail', text: e.message.split('\n')[0].slice(0, 160) }); }
  await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
  const loadedAt = at();
  const seenToasts = new Set();
  const end = Date.now() + LINGER;
  while (Date.now() < end) {
    await page.waitForTimeout(2000);
    const toasts = await page.evaluate(() => {
      const sel = '[role="alert"], [class*="toast" i], [id*="toast" i], .swal2-popup, [class*="notif" i], [class*="error" i]';
      return [...document.querySelectorAll(sel)].filter((el) => {
        const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0.1 && r.bottom > 0 && r.top < innerHeight;
      }).map((el) => el.innerText.trim().replace(/\s+/g, ' ').slice(0, 160)).filter(Boolean);
    }).catch(() => []);
    for (const tx of toasts) if (!seenToasts.has(tx)) { seenToasts.add(tx); ev.push({ t: at(), kind: 'toast', text: tx }); }
  }
  const m = await page.evaluate(() => {
    const vw = innerWidth; const sw = document.scrollingElement.scrollWidth;
    const ox = getComputedStyle(document.documentElement).overflowX;
    return { overflowX: !['hidden', 'clip'].includes(ox) && getComputedStyle(document.body).overflowX !== 'hidden' && sw > vw + 1, scrollWidth: sw,
             brokenImages: [...document.images].filter((i) => i.complete && i.naturalWidth === 0 && i.src && !i.src.startsWith('data:') && getComputedStyle(i).display !== 'none').length,
             title: document.title.slice(0, 80), finalUrl: location.pathname };
  }).catch(() => ({}));
  const file = `${device}_${url.replace(/[^\w]+/g, '_').replace(/^_|_$/g, '') || 'root'}.png`;
  await page.screenshot({ path: path.join(shotDir, file), fullPage: true, timeout: 30000 }).catch(() => {});
  await page.close();
  const bad = ev.filter((e) => e.kind !== 'toast' || ERR_TEXT.test(e.text));
  const late = bad.filter((e) => e.t > loadedAt + 1);
  return { url, device, status, loadedAt, events: ev, problems: bad, lateProblems: late, ...m, screenshot: file };
}

const results = [];
for (const [device, opts] of Object.entries(DEVICES)) {
  const ctx = await browser.newContext({ ...opts, storageState: state, permissions: ['geolocation', 'camera'] });
  const queue = [...pages];
  await Promise.all(Array.from({ length: Math.min(POOL, queue.length) }, async () => {
    while (queue.length) {
      const url = queue.shift();
      const r = await lingerOne(ctx, device, url);
      results.push(r);
      const flags = [];
      if (r.status >= 500) flags.push('HTTP ' + r.status);
      if (r.problems.length) flags.push(`${r.problems.length} lỗi (${r.lateProblems.length} xuất hiện muộn)`);
      if (r.overflowX) flags.push(`tràn ngang ${r.scrollWidth}px`);
      if (r.brokenImages) flags.push(`${r.brokenImages} ảnh vỡ`);
      console.log(`${flags.length ? '⚠️ ' : '✅'} [${device}] ${url}${r.finalUrl && r.finalUrl !== url ? ' → ' + r.finalUrl : ''} tải ${r.loadedAt}s ${flags.join(' | ')}`);
      for (const p of r.problems.slice(0, 6)) console.log(`      +${p.t}s ${p.kind}: ${p.text}`);
    }
  }));
  await ctx.close();
}
await browser.close();
const flagged = results.filter((r) => r.problems.length || r.overflowX || r.brokenImages || r.status >= 500);
fs.writeFileSync(path.join(OUT, `${TENANT}.json`), JSON.stringify({ tenant: TENANT, linger_s: LINGER / 1000, results }, null, 1));
console.log(`\nTổng kết ${TENANT}: ${results.length} lượt (${results.length - flagged.length} sạch, ${flagged.length} có vấn đề; `
  + `${results.filter((r) => r.lateProblems.length).length} có lỗi xuất hiện muộn)`);
