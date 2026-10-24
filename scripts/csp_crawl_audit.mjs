// csp_crawl_audit.mjs — Pha 28: Content-Security-Policy mới có chặn nhầm gì trên trang thật không?
// Mở mọi trang (đăng nhập chủ tiệm Nails + 1 số ngành khác + khách vãng lai), ghi lại mọi vi phạm CSP
// (securitypolicyviolation + console "Content Security Policy") và lỗi JS. Ghi audit-results/csp_crawl.json.
//   node scripts/csp_crawl_audit.mjs   (CHỈ local)
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const ROUTES = JSON.parse(fs.readFileSync(process.env.ROUTES_FILE, 'utf-8'));
const ACCOUNTS = [
  ['nail', 'demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!'],
  ['spa', 'demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!'],
  ['fnb', 'demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!'],
  ['hotel', 'demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!'],
  ['karaoke', 'demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!'],
  ['technical', 'demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!'],
];
const PUBLIC = ['/', '/login', '/checkout', '/privacy', '/terms', '/payment-policy', '/about', '/founder',
  ...['nail', 'spa', 'fnb', 'retail', 'hotel', 'karaoke', 'production', 'technical', 'office'].map((c) => `/solutions/${c}`),
  '/booking/nail/qr/000b2c16-ab4e-42bd-944a-29c925cad09b', '/booking/qr/3cd48d09-8028-486d-82da-038db3ac2892'];
const INDUSTRY_PAGES = ['/pos', '/sell', '/retail_pos', '/spa', '/karaoke', '/hotel_rooms', '/kitchen_display', '/fnb_dashboard', '/map_dashboard',
  '/production/materials', '/technical/parts', '/chamcong', '/app_nhanvien', '/ai_bot', '/roster', '/settings/booking', '/calendar', '/dashboard'];

const out = { violations: {}, js_errors: {}, visited: 0 };
const b = await chromium.launch({ channel: 'chrome' });

async function crawl(page, label, paths) {
  for (const path of paths) {
    const v = [], errs = [];
    const onConsole = (m) => { const t = m.text(); if (/Content Security Policy|Refused to (load|connect|execute|apply|frame)/i.test(t)) v.push(t.slice(0, 220)); };
    const onErr = (e) => errs.push(e.message.slice(0, 160));
    page.on('console', onConsole); page.on('pageerror', onErr);
    try {
      await page.goto(BASE + path, { waitUntil: 'networkidle', timeout: 25000 });
      await page.waitForTimeout(700);
      const ev = await page.evaluate(() => (window.__csp || []).splice(0));
      v.push(...ev.map((e) => `${e.d} ${e.u}`));
    } catch (e) { errs.push('nav: ' + e.message.slice(0, 100)); }
    page.off('console', onConsole); page.off('pageerror', onErr);
    out.visited++;
    if (v.length) out.violations[`${label} ${path}`] = [...new Set(v)];
    if (errs.length) out.js_errors[`${label} ${path}`] = [...new Set(errs)];
  }
}

async function ctxWithHook() {
  const ctx = await b.newContext({ viewport: { width: 1366, height: 900 } });
  await ctx.addInitScript(() => {
    window.__csp = [];
    document.addEventListener('securitypolicyviolation', (e) => window.__csp.push({ d: e.violatedDirective, u: e.blockedURI }));
  });
  return ctx;
}

{ // khách vãng lai
  const ctx = await ctxWithHook(); const p = await ctx.newPage();
  await crawl(p, 'public', PUBLIC);
  await ctx.close();
}
for (const [ind, email, pw] of ACCOUNTS) {
  const ctx = await ctxWithHook(); const p = await ctx.newPage();
  await p.goto(BASE + '/login'); await p.fill('#loginEmail', email); await p.fill('#loginPassword', pw);
  await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
  await crawl(p, ind, ind === 'nail' ? ROUTES.filter((r) => !r.includes('super')) : INDUSTRY_PAGES);
  await ctx.close();
}
await b.close();
fs.writeFileSync('audit-results/csp_crawl.json', JSON.stringify(out, null, 2));
const vCount = Object.keys(out.violations).length;
console.log(`visited ${out.visited} · pages with CSP violations: ${vCount} · pages with JS errors: ${Object.keys(out.js_errors).length}`);
for (const [k, v] of Object.entries(out.violations)) console.log('CSP', k, '→', v.slice(0, 3).join(' | '));
for (const [k, v] of Object.entries(out.js_errors)) console.log('JS ', k, '→', v.slice(0, 2).join(' | '));
process.exit(vCount ? 1 : 0);
