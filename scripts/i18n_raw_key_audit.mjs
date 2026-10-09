// Tìm KHOÁ DỊCH THÔ hiện ra màn hình (vd sidebar ghi "menu_dashboard" thay vì "Tổng quan") trên mọi trang
// trong sidebar của 1 tenant demo, ở cả tiếng Việt và tiếng Anh, kể cả sau khi bấm nút đổi ngôn ngữ EN/VI.
// full_site_audit.mjs không bắt được lỗi này (trang vẫn tải 200, không có lỗi JS).
//
// Chạy: node scripts/i18n_raw_key_audit.mjs   (server local phải đang chạy; TENANT_EMAIL/TENANT_PASSWORD tuỳ chọn)
import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.TENANT_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.TENANT_PASSWORD || 'DemoNails2026!';
// 1 text node chỉ gồm khoá dạng snake_case có tiền tố quen thuộc của bộ dịch (menu_, cnl_, npos_...)
const RAW_KEY = /^[a-z][a-z0-9]*(_[a-z0-9]+){1,}$/;

async function rawKeys(page) {
  return page.evaluate((src) => {
    const re = new RegExp(src);
    const out = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const n = walker.currentNode; const txt = n.nodeValue.trim();
      if (!txt || !re.test(txt)) continue;
      const el = n.parentElement;
      if (!el || ['SCRIPT', 'STYLE', 'CODE', 'PRE', 'TEXTAREA', 'OPTION'].includes(el.tagName)) continue;
      const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
      if (cs.display === 'none' || cs.visibility === 'hidden' || (r.width === 0 && r.height === 0)) continue;
      out.add(txt);
    }
    return [...out];
  }, RAW_KEY.source);
}

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
await page.fill('#loginEmail', EMAIL);
await page.fill('#loginPassword', PASSWORD);
await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
if (page.url().includes('/login')) throw new Error('Đăng nhập thất bại (giới hạn 5 lần/15 phút?) — restart server rồi chạy lại');
// Trang lớn đôi khi bị reset kết nối trên máy dev (xem scripts/lib/nail_nav.mjs) -> tải lại tới khi có sidebar
for (let i = 0; i < 4 && !(await page.locator('#app-sidebar a').count()); i++) {
  await page.goto(page.url(), { waitUntil: 'networkidle' }).catch(() => {});
}
let links = [...new Set(await page.$$eval('#app-sidebar a[href^="/"]', (as) => as.map((a) => a.getAttribute('href'))))]
  .filter((h) => !/logout|delete/.test(h));
// Trang không nằm trong sidebar nhưng chủ tiệm Nails vẫn mở tới (nút, link trong trang)
for (const extra of ['/map_dashboard', '/nhanvien', '/add', '/quanly_dichvu', '/app_nhanvien', '/diemdanh', '/crm_automation',
  '/campaign_builder', '/promotion_management', '/customer_nurturing', '/quanly_thuchi', '/baocao_loinhuan', '/cauhinh_luong', '/user_logs', '/backup_restore']) {
  if (!links.includes(extra)) links.push(extra);
}

if (process.env.PAGES) links = process.env.PAGES.split(',');   // vd PAGES=/map_dashboard,/sell

const problems = [];
for (const lang of ['vi', 'en']) {
  await ctx.addCookies([{ name: 'bitpaw_lang', value: lang, url: BASE }]);
  await page.evaluate((l) => localStorage.setItem('bitpaw_lang', l), lang);
  for (const href of links) {
    try {
      await page.goto(`${BASE}${href}`, { waitUntil: 'networkidle', timeout: 30000 });
      await page.waitForTimeout(400);
      let keys = await rawKeys(page);
      // bấm nút EN/VI của sidebar (đổi ngôn ngữ không reload) rồi soát lại
      const toggled = await page.evaluate(() => { if (typeof __bitpawToggleLang !== 'function') return false; __bitpawToggleLang(); return true; });
      if (toggled) {
        // trang không có changeLanguage() riêng thì sidebar reload trang -> chờ tải xong rồi mới soát
        await page.waitForLoadState('networkidle').catch(() => {});
        await page.waitForTimeout(800);
        const after = await rawKeys(page).catch(async () => { await page.waitForLoadState('networkidle'); return rawKeys(page); });
        keys = keys.concat(after.map((k) => k + ' (sau khi đổi ngôn ngữ)'));
      }
      await page.evaluate((l) => { localStorage.setItem('bitpaw_lang', l); document.cookie = `bitpaw_lang=${l};path=/`; }, lang);
      if (keys.length) problems.push({ lang, href, keys });
      console.log(`${keys.length ? '❌' : '✅'} [${lang}] ${href}${keys.length ? ' — ' + keys.slice(0, 6).join(', ') : ''}`);
    } catch (e) {
      console.log(`⚠️  [${lang}] ${href} — ${e.message.split('\n')[0]}`);
    }
  }
}
await browser.close();
console.log(`\nTổng: ${links.length} trang × 2 ngôn ngữ · ${problems.length} lượt có khoá dịch thô`);
process.exit(problems.length ? 1 : 0);
