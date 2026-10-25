// landing_mobile_blank_audit.mjs — iPhone: cuộn từng màn hình 11 landing x 2 ngôn ngữ, không màn nào trống chữ; khu tải về cùng ngôn ngữ với trang. (server local)
import { chromium, devices } from 'playwright';
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const PAGES = ['landing', 'nail', 'spa', 'fnb', 'karaoke', 'hotel', 'retail', 'production', 'technical', 'office', 'hr'];
const b = await chromium.launch({ channel: 'chrome' });
let bad = 0;
for (const loc of ['vi-VN', 'en-US']) {
  const ctx = await b.newContext({ ...iphone, locale: loc });
  for (const pg of PAGES) {
    const p = await ctx.newPage();
    const errs = []; p.on('pageerror', (e) => errs.push(e.message));
    await p.goto((process.env.BASE || 'http://127.0.0.1:5001') + (pg === 'landing' ? '/landing' : '/solutions/' + pg), { waitUntil: 'load' });
    await p.waitForTimeout(900);
    const H = await p.evaluate(() => document.documentElement.scrollHeight);
    const vh = await p.evaluate(() => innerHeight);
    const blanks = [];
    for (let y = 0; y < H - vh; y += vh) {
      await p.evaluate((yy) => scrollTo(0, yy), y);
      await p.waitForTimeout(650);
      const n = await p.evaluate(() => {
        let c = 0; const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let t;
        while ((t = w.nextNode())) {
          if (t.textContent.trim().length < 3) continue;
          const el = t.parentElement; if (!el || el.closest('nav, header, .bp-bottom-nav, .bp-fab, #bitpawCskhFloating, .bp-sheet')) continue;
          const r = el.getBoundingClientRect(); if (r.bottom < 90 || r.top > innerHeight - 70 || r.width === 0) continue;
          let e = el, op = 1; while (e && e !== document.body) { op *= +getComputedStyle(e).opacity; e = e.parentElement; }
          if (op > 0.6) c++;
        }
        return c;
      });
      if (n === 0) blanks.push(Math.round(y / vh));
    }
    const lang = await p.evaluate(() => ({ page: document.documentElement.getAttribute('data-bp-lang'), dl: document.querySelector('.bpdl') ? (document.querySelector('.bpdl').classList.contains('bpdl-en') ? 'en' : 'vi') : null }));
    const ok = blanks.length === 0 && errs.length === 0 && (lang.dl === null || lang.dl === lang.page);
    if (!ok) bad++;
    console.log(`${ok ? '✅' : '❌'} [${loc}] ${pg}: ${Math.round(H / vh)} màn · màn trống: ${blanks.length ? blanks.join(',') : 0} · ngôn ngữ trang=${lang.page} khu tải=${lang.dl} · lỗi JS=${errs.length}`);
    await p.close();
  }
  await ctx.close();
}
await b.close();
console.log(bad ? `❌ ${bad} trang lỗi` : '✅ tất cả đạt');
