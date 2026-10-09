/**
 * scripts/industry_isolation_audit.mjs — kiểm tra TÁCH NGÀNH NGHỀ cho cả 9 ngành (xem industry_access.py):
 *   1. Đăng nhập -> vào đúng trang chủ ngành mình.
 *   2. Mọi link trong sidebar mở được (200) và KHÔNG dẫn sang trang riêng của ngành khác.
 *   3. Mở thử MỌI trang riêng của 8 ngành còn lại -> bị đưa về trang chủ ngành mình.
 *   4. Gọi thử MỌI API riêng (GET) của 8 ngành còn lại -> 403.
 *   5. Nút "POS" và "Chấm công" ở sidebar trỏ đúng ngành.
 *   6. Trang công khai cho khách: QR đặt lịch Spa mở cho tiệm Nails tự chuyển đúng trang Nails; đặt bàn /
 *      đặt phòng của tiệm khác ngành -> 404.
 *   7. Không tiệm ngành nào ngoài F&B bị tạo bàn ăn (db.dining_tables) sau khi chạy.
 * Chạy: node scripts/industry_isolation_audit.mjs   (server local đang chạy)
 */
import { chromium } from 'playwright';
import fs from 'fs';
import { execFileSync } from 'child_process';

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
const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : Object.keys(TENANTS);

function py(args) {
  const out = execFileSync('python', args, { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  return JSON.parse(out.trim().split('\n').pop());
}
const R = py(['scripts/_industry_routes.py']);
const allForeignPagePaths = new Set(Object.values(R.pages).flat());

const bids = py(['scripts/_industry_routes.py', 'bids', JSON.stringify(Object.fromEntries(Object.entries(TENANTS).map(([k, v]) => [k, v[0]])))]);
const results = [];
const rec = (ind, name, ok, note = '') => {
  results.push({ ind, name, ok, note });
  console.log(`${ok ? '✅' : '❌'} [${ind}] ${name}${note ? ' — ' + note : ''}`);
};
const pathOf = (u) => new URL(u).pathname;

// fetch trong trang (cookie phiên có cờ Secure: APIRequestContext của Playwright không gửi qua http local)
async function pageFetch(page, path, json) {
  return page.evaluate(async ({ path, json }) => {
    const r = await fetch(path, { headers: json ? { Accept: 'application/json' } : {}, redirect: 'follow' });
    return { status: r.status, finalPath: new URL(r.url).pathname, redirected: r.redirected };
  }, { path, json });
}
const RESTART = `${process.env.HOME || process.env.USERPROFILE}/restart_flask.sh`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
let loginsSinceRestart = 0;
for (const ind of ONLY) {
  // giới hạn đăng nhập 5 lần/15 phút/IP -> khởi động lại server local sau mỗi 4 tài khoản
  if (loginsSinceRestart >= 4 && !process.env.NO_SELF_RESTART && fs.existsSync(RESTART)) { execFileSync('bash', [RESTART], { stdio: 'ignore' }); loginsSinceRestart = 0; }
  loginsSinceRestart++;
  const [email, pw] = TENANTS[ind];
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  // máy dev đôi khi treo kết nối ~20-30s (Werkzeug + Avast, xem scripts/lib/nail_nav.mjs) -> thử lại
  for (let i = 0; i < 3; i++) {
    try { await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 }); break; } catch (e) { if (i === 2) throw e; }
  }
  await page.fill('#loginEmail', email);
  await page.fill('#loginPassword', pw);
  await Promise.all([page.waitForLoadState('domcontentloaded'), page.click('#btnLogin')]);
  await page.waitForLoadState('networkidle').catch(() => {});
  if (pathOf(page.url()) === '/login') { rec(ind, 'Đăng nhập', false, 'thất bại (giới hạn đăng nhập? restart server)'); await ctx.close(); continue; }
  const home = R.home[ind];
  const landed = pathOf(page.url());
  rec(ind, 'Đăng nhập -> vào đúng trang chủ ngành', landed === home || landed === home.replace('/chamcong/', '/chamcong_'), landed);

  // sidebar (POS toàn màn hình của nhiều ngành không có sidebar -> lấy từ trang Bảng lương dùng chung)
  await page.goto(`${BASE}/bangluong`, { waitUntil: 'domcontentloaded' });
  for (let i = 0; i < 3 && !(await page.locator('#app-sidebar a').count()); i++) await page.goto(`${BASE}/bangluong`, { waitUntil: 'networkidle' }).catch(() => {});
  const links = [...new Set(await page.$$eval('#app-sidebar a[href^="/"]', (as) => as.map((a) => a.getAttribute('href'))))].filter((h) => !/logout|delete/.test(h));
  const ownPages = new Set(R.pages[ind]);
  const badLinks = [];
  for (const href of links) {
    const resp = await page.goto(`${BASE}${href}`, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch((e) => ({ status: () => 'ERR ' + e.message.split('\n')[0] }));
    const final = pathOf(page.url());
    const foreign = allForeignPagePaths.has(final) && !ownPages.has(final);
    // link trỏ tới trang riêng của ngành khác (dù bị chặn về trang chủ) cũng là lỗi; /dashboard tự chuyển về
    // trang chủ của CHÍNH ngành mình là đúng thiết kế
    const hrefPath = href.split('?')[0];
    const linksForeign = allForeignPagePaths.has(hrefPath) && !ownPages.has(hrefPath);
    if (resp.status() !== 200 || foreign || linksForeign) badLinks.push(`${href}→${final} (${resp.status()})`);
  }
  rec(ind, `${links.length} link sidebar mở đúng, không dẫn sang ngành khác`, badLinks.length === 0, badLinks.join(', '));
  await page.goto(`${BASE}/bangluong`, { waitUntil: 'domcontentloaded' });
  const posHref = await page.locator('#app-sidebar a', { has: page.locator('[data-i18n="menu_pos_service"]') }).first().getAttribute('href').catch(() => null);
  if (posHref) rec(ind, 'Nút POS dịch vụ ở sidebar trỏ đúng POS của ngành', posHref === R.pos[ind], posHref);
  const ccHref = await page.locator('#app-sidebar a', { has: page.locator('[data-i18n="menu_attendance"]') }).first().getAttribute('href').catch(() => null);
  if (ccHref) rec(ind, 'Nút Chấm công ở sidebar trỏ đúng trang chấm công riêng', R.pages[ind].includes(ccHref), ccHref);

  // trang + API của ngành khác
  const leaks = [];
  for (const [other, paths] of Object.entries(R.pages)) {
    if (other === ind) continue;
    for (const p of paths) {
      if (ownPages.has(p)) continue;
      const r = await pageFetch(page, p, false);
      const homeAlt = home.replace('/chamcong/', '/chamcong_');
      if (!(r.redirected && [home, homeAlt].includes(r.finalPath))) leaks.push(`${p}:${r.status}→${r.finalPath}`);
    }
  }
  rec(ind, 'Mở trang riêng của 8 ngành khác -> bị đưa về trang chủ ngành mình', leaks.length === 0, leaks.slice(0, 8).join(', '));
  const apiLeaks = [];
  for (const [other, paths] of Object.entries(R.apis)) {
    if (other === ind) continue;
    for (const p of paths) {
      if (R.apis[ind].includes(p)) continue;
      const r = await pageFetch(page, p, true);
      if (r.status !== 403) apiLeaks.push(`${p}:${r.status}`);
    }
  }
  rec(ind, 'Gọi API riêng của 8 ngành khác -> 403', apiLeaks.length === 0, apiLeaks.slice(0, 8).join(', '));
  const ownBad = [];
  for (const p of R.pages[ind]) {
    const r = await pageFetch(page, p, false);
    // /qr_menu tự chuyển sang thực đơn của bàn đầu tiên (/qr_menu/<mã bàn>) — vẫn là trang của chính ngành
    const sameish = r.finalPath === p || r.finalPath === p.replace('/chamcong/', '/chamcong_') || r.finalPath.startsWith(p + '/');
    if (r.status !== 200 || !sameish) ownBad.push(`${p}:${r.status}→${r.finalPath}`);
  }
  rec(ind, `${R.pages[ind].length} trang riêng của chính ngành mình mở được (200)`, ownBad.length === 0, ownBad.join(', '));
  await ctx.close();
}

// Trang công khai cho khách (không đăng nhập)
const pub = await (await browser.newContext()).newPage();
async function status(path) { const r = await pub.request.get(`${BASE}${path}`, { maxRedirects: 0 }); return [r.status(), r.headers().location || '']; }
if (bids.nail && bids.spa) {
  let [s, loc] = await status(`/booking/qr/${bids.nail}`);
  rec('khách', 'QR đặt lịch kiểu Spa của tiệm Nails -> chuyển sang trang đặt lịch Nails', s === 302 && loc.includes(`/booking/nail/qr/${bids.nail}`), `${s} ${loc}`);
  [s, loc] = await status(`/booking/nail/qr/${bids.spa}`);
  rec('khách', 'QR đặt lịch kiểu Nails của tiệm Spa -> chuyển sang trang đặt lịch Spa', s === 302 && loc.includes(`/booking/qr/${bids.spa}`), `${s} ${loc}`);
  [s] = await status(`/booking/nail/qr/${bids.nail}`);
  rec('khách', 'QR đặt lịch Nails của chính tiệm Nails mở được', s === 200, String(s));
}
const crossPublic = [['/reserve/', 'fnb'], ['/karaoke/reserve/', 'karaoke'], ['/hotel/reserve/', 'hotel']];
for (const [prefix, owner] of crossPublic) {
  if (bids[owner]) { const [s] = await status(prefix + bids[owner]); rec('khách', `${prefix}<tiệm ${owner}> mở được`, s === 200, String(s)); }
  const other = owner === 'fnb' ? 'nail' : 'fnb';
  if (bids[other]) { const [s] = await status(prefix + bids[other]); rec('khách', `${prefix}<tiệm ${other}> (sai ngành) -> 404`, s === 404, String(s)); }
}
await browser.close();

const tables = py(['scripts/_industry_routes.py', 'tables']);
rec('dữ liệu', 'Không tiệm ngành nào ngoài F&B có bàn ăn (dining_tables)', Object.keys(tables).length === 0, JSON.stringify(tables));

const fail = results.filter((r) => !r.ok).length;
fs.writeFileSync('audit-results/industry_isolation_audit_report.json', JSON.stringify({ ran_at: new Date().toISOString(), results }, null, 2));
console.log(`\nTổng kết: ${results.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
