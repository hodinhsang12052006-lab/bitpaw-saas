// landing_shots.mjs — chụp 11 trang landing (máy tính 1440px + iPhone 13): màn đầu + toàn trang thu nhỏ, để soát giao diện.
//   OUT=<thư mục> node scripts/landing_shots.mjs [nhãn]   (CHỈ local)
import { chromium, devices } from 'playwright';
import fs from 'fs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const OUT = process.env.OUT || 'audit-results/landing_shots';
const TAG = process.argv[2] || 'now';
fs.mkdirSync(OUT, { recursive: true });
const PAGES = [['main', '/landing'], ...['nail', 'spa', 'fnb', 'karaoke', 'hotel', 'retail', 'production', 'technical', 'office', 'hr'].map((c) => [c, `/solutions/${c}`])];
const only = (process.env.ONLY || '').split(',').filter(Boolean);
const b = await chromium.launch({ channel: 'chrome' });
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const report = [];
for (const [dev, opts] of [['pc', { viewport: { width: 1440, height: 900 } }], ['mob', iphone]]) {
  const ctx = await b.newContext({ ...opts, locale: 'vi-VN' });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  for (const [name, path] of PAGES) {
    if (only.length && !only.includes(name)) continue;
    errs.length = 0;
    await p.goto(BASE + path, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
    await p.waitForTimeout(1500);
    await p.screenshot({ path: `${OUT}/${TAG}_${dev}_${name}.png` });
    if (process.env.FULL) {
      // hiện hết các khối "hiện khi cuộn" (AOS) trước khi chụp toàn trang, không thì ảnh trống từng đoạn
      await p.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 700) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); }
        document.querySelectorAll('[data-aos]').forEach((el) => el.classList.add('aos-animate')); window.scrollTo(0, 0); });
      await p.waitForTimeout(800);
      await p.screenshot({ path: `${OUT}/${TAG}_${dev}_${name}_full.png`, fullPage: true }).catch(() => {});
    }
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    report.push({ dev, name, overflow, jsErrors: errs.slice() });
  }
  await ctx.close();
}
await b.close();
for (const r of report) if (r.overflow > 2 || r.jsErrors.length) console.log(JSON.stringify(r));
console.log('pages', report.length);
