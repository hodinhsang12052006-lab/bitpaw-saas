// spa_ui_survey.mjs — chụp MỌI màn hình của ngành Spa (chủ tiệm theo menu thật + trang khách đặt lịch) trên PC 1440 và iPhone 13,
// đo nhanh: tràn ngang, chữ quá nhỏ, nút nhỏ hơn 44px trên điện thoại, độ tương phản chữ thấp, lỗi JS. Chỉ đọc — không bấm lưu/xoá.
//   OUT=<thư mục> node scripts/spa_ui_survey.mjs   (CHỈ local)
import { chromium, devices } from 'playwright';
import fs from 'fs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const OUT = process.env.OUT || 'audit-results/spa_ui_survey';
const [EMAIL, PW] = (process.env.ACCT || 'demo.spa.596348@bitpawdemo.com:DemoBitPaw2026!').split(':');
const SPA_BID = '3cd48d09-8028-486d-82da-038db3ac2892';
fs.mkdirSync(OUT, { recursive: true });
const b = await chromium.launch({ channel: 'chrome' });
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];

const metrics = () => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const lum = (c) => { const m = c.match(/[\d.]+/g); if (!m) return null; const [r, g, bb] = m.slice(0, 3).map((v) => { v = v / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * bb; };
  const bgOf = (el) => { while (el) { const c = getComputedStyle(el).backgroundColor; const m = c.match(/[\d.]+/g); if (m && (m.length < 4 || +m[3] > 0.5)) return c; el = el.parentElement; } return 'rgb(11,17,32)'; };
  let small = 0, lowContrast = 0, samples = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el) || !el.childNodes.length) continue;
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!own) continue;
    const s = getComputedStyle(el); const fs = parseFloat(s.fontSize);
    if (fs < 11) small++;
    const L1 = lum(s.color), L2 = lum(bgOf(el));
    if (L1 != null && L2 != null) { const cr = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05); if (cr < 4.5 && fs < 18) { lowContrast++; if (samples.length < 4) samples.push(el.textContent.trim().slice(0, 30) + ' ' + cr.toFixed(1)); } }
  }
  const taps = [...document.querySelectorAll('a,button,input,select,[onclick]')].filter(vis).filter((el) => { const r = el.getBoundingClientRect(); return r.height < 40 || r.width < 40; }).length;
  return { ov: document.documentElement.scrollWidth - innerWidth, small, lowContrast, samples, smallTaps: taps, h: document.documentElement.scrollHeight, title: document.title };
};

const report = [];
for (const [dev, opts] of [['pc', { viewport: { width: 1440, height: 900 } }], ['mob', iphone]]) {
  const ctx = await b.newContext({ ...opts, timezoneId: 'Australia/Sydney', locale: 'en-AU' });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message.slice(0, 120)));
  // trang khách (chưa đăng nhập)
  await p.goto(`${BASE}/booking/qr/${SPA_BID}?lang=en`, { waitUntil: 'networkidle' }); await p.waitForTimeout(900);
  await p.screenshot({ path: `${OUT}/${dev}_public_booking.png`, fullPage: true });
  report.push({ dev, r: '/booking/qr (public)', ...(await p.evaluate(metrics)), errs: errs.splice(0) });
  await p.goto(BASE + '/login'); await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
  await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
  // menu thật của tiệm Spa
  await p.goto(BASE + '/spa?lang=en', { waitUntil: 'networkidle' });
  let routes = await p.evaluate(() => [...new Set([...document.querySelectorAll('aside a[href^="/"], nav a[href^="/"], #sidebar a[href^="/"]')]
    .map((a) => a.getAttribute('href').split('#')[0]).filter((h) => h && !/logout|delete|download|\.exe|\.apk|lang=/.test(h)))]);
  if (process.env.ROUTES) routes = process.env.ROUTES.split(',');
  if (dev === 'pc') console.log('menu:', routes.join(' '));
  for (const r of routes) {
    try {
      const res = await p.goto(BASE + r + (r.includes('?') ? '&' : '?') + 'lang=en', { waitUntil: 'networkidle', timeout: 25000 });
      await p.waitForTimeout(700);
      const name = r.replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '') || 'root';
      await p.screenshot({ path: `${OUT}/${dev}_${name}.png`, fullPage: dev === 'mob' ? false : false });
      report.push({ dev, r, status: res && res.status(), url: p.url().replace(BASE, ''), ...(await p.evaluate(metrics)), errs: errs.splice(0) });
    } catch (e) { report.push({ dev, r, err: e.message.slice(0, 100) }); }
  }
  await ctx.close();
}
fs.writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 1));
for (const x of report) console.log(x.dev, x.r, x.status || '', x.url && x.url !== x.r ? '->' + x.url : '', 'ov', x.ov, 'small', x.small, 'lowCR', x.lowContrast, 'taps<40', x.smallTaps, x.errs && x.errs.length ? 'ERR ' + x.errs[0] : '', x.err || '');
await b.close();
