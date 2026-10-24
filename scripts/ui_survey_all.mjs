// ui_survey_all.mjs — chụp NHANH mọi trang (danh sách route) trên iPhone 13 bằng 1 tài khoản, để soát giao diện cả hệ thống.
// Báo các trang: lỗi, tràn ngang, mã HTTP >= 400, và tiệm Mỹ/Úc mà trang hiện tiền Việt (₫ / VND / 100.000đ).
//   ROUTES_FILE=routes.json OUT=<thư mục> [ACCT=email:pass] [DEV=mob|pc] node scripts/ui_survey_all.mjs   (CHỈ local)
import { chromium, devices } from 'playwright';
import fs from 'fs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const OUT = process.env.OUT || 'audit-results/ui_survey_all';
const [EMAIL, PW] = (process.env.ACCT || 'demo.nails.au.006758@bitpawdemo.com:DemoNails2026!').split(':');
fs.mkdirSync(OUT, { recursive: true });
const SKIP = /\/api\/|logout|debug|\.json|stream|export|download|webhook|\/static\/|sitemap|robots|favicon|\.html$|landing|solutions|founder|ho-dinh-sang|about|privacy|terms|policy|^\/$|^\/index/;
const routes = JSON.parse(fs.readFileSync(process.env.ROUTES_FILE, 'utf8')).filter((r) => !SKIP.test(r));
const b = await chromium.launch({ channel: 'chrome' });
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const ctx = await b.newContext(process.env.DEV === 'pc' ? { viewport: { width: 1440, height: 900 } } : iphone);
const p = await ctx.newPage();
await p.goto(BASE + '/login'); await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const VND_RE = /[^\n]{0,30}(₫|\bVND\b|\bVNĐ|\d\.\d{3}\s?đ\b)[^\n]{0,20}/g;
const report = [];
for (const r of routes) {
  try {
    const res = await p.goto(BASE + r, { waitUntil: 'networkidle', timeout: 20000 });
    await p.waitForTimeout(600);
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    const vnd = ((await p.innerText('body').catch(() => '')).match(VND_RE) || []).slice(0, 3);
    const name = r.replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '') || 'root';
    await p.screenshot({ path: `${OUT}/${name}.png` });
    report.push({ r, status: res ? res.status() : 0, url: p.url().replace(BASE, ''), overflow, vnd });
  } catch (e) { report.push({ r, err: e.message.slice(0, 80) }); }
}
fs.writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 1));
for (const x of report) if (x.err || x.overflow > 2 || (x.status && x.status >= 400) || (x.vnd && x.vnd.length)) console.log(JSON.stringify(x));
console.log('pages', report.length);
await b.close();
