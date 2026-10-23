/**
 * scripts/landing_download_audit.mjs — khu "Tải về & dùng ngay" đúng ngành trên 10 landing + landing chính.
 * Mỗi trang: có khu #tai-ve đúng ngành, link Windows /download/<ngành>/windows, mã QR, mọi nút Đăng ký/Đăng nhập
 * của trang mang đúng ngành, gợi ý đúng nền tảng (Windows / điện thoại), không tràn ngang trên mobile.
 * Form đăng ký chọn sẵn ngành; /download/<ngành>/windows trả đúng file (hoặc trang chờ khi chưa phát hành).
 *   node scripts/landing_download_audit.mjs     (server local 127.0.0.1:5001)
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const OUT = path.resolve('audit-results/screenshots/landing_download_audit');
fs.mkdirSync(OUT, { recursive: true });
const PAGES = { nail: 'nail', spa: 'spa', fnb: 'fnb', karaoke: 'karaoke', hotel: 'hotel', retail: 'retail',
  production: 'production', technical: 'technical', office: 'office', hr: 'office' };
const FILES = { nail: 'BitPaw-Nails.exe', spa: 'BitPaw-Spa.exe', fnb: 'BitPaw-FnB.exe', karaoke: 'BitPaw-Karaoke.exe',
  hotel: 'BitPaw-Hotel.exe', retail: 'BitPaw-Retail.exe', production: 'BitPaw-Production.exe',
  technical: 'BitPaw-Technical.exe', office: 'BitPaw-Office.exe' };
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok, note }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };

const browser = await chromium.launch({ channel: 'chrome' });
const desk = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const mob = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' });
const errors = [];

for (const [page, code] of Object.entries(PAGES)) {
  for (const [kind, ctx] of [['desktop', desk], ['mobile', mob]]) {
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errors.push(`${page}/${kind}: ${e.message}`));
    await p.goto(`${BASE}/solutions/${page}`, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
    await p.waitForSelector('#tai-ve', { timeout: 15000 }).catch(() => {});
    const info = await p.evaluate(() => {
      const s = document.getElementById('tai-ve');
      if (!s) return null;
      const links = Array.from(document.querySelectorAll('a[href]')).map((a) => a.getAttribute('href'));
      const r = s.querySelector('.bpdl-rec');
      return {
        industry: s.dataset.industry,
        win: s.querySelector('a[data-bpdl-track="windows"]')?.getAttribute('href'),
        apk: s.querySelector('a[data-bpdl-track="android"]')?.getAttribute('href'),
        ios: !!s.querySelector('[data-bpdl-platform="ios"] [data-bpdl-ios-guide]'),
        meta: s.querySelector('[data-bpdl-platform="windows"]')?.textContent || '',
        qr: !!s.querySelector('.bpdl-qr svg path'),
        authLinks: links.filter((h) => /^\/(login|register)\b/.test(h)),
        rec: r ? r.dataset.bpdlPlatform : null,
        overflow: document.documentElement.scrollWidth - innerWidth,
      };
    });
    if (!info) { rec(`${page} ${kind}: có khu Tải về`, false); await p.close(); continue; }
    const badAuth = info.authLinks.filter((h) => !h.includes(`industry=${code}`));
    // iPhone -> thẻ iPhone & iPad (web app cài lên màn hình chính); máy tính -> thẻ Windows
    const ok = info.industry === code && info.win === `/download/${code}/windows` && info.meta.includes(FILES[code])
      && info.apk === `/download/${code}/android` && info.ios
      && info.qr && badAuth.length === 0 && info.overflow <= 1 && info.rec === (kind === 'mobile' ? 'ios' : 'windows');
    rec(`${page} ${kind}: Tải về đúng ngành ${code}`, ok,
      `win=${info.win} · ${info.authLinks.length} nút đăng ký/đăng nhập${badAuth.length ? ' SAI: ' + badAuth.join(',') : ' đúng ngành'} · gợi ý=${info.rec} · tràn=${info.overflow}`);
    await p.locator('#tai-ve').scrollIntoViewIfNeeded().catch(() => {});
    await p.locator('#tai-ve').screenshot({ path: path.join(OUT, `${page}_${kind}.png`) }).catch(() => {});
    await p.close();
  }
}

// Form đăng ký chọn sẵn ngành
for (const code of Object.keys(FILES)) {
  const p = await desk.newPage();
  await p.goto(`${BASE}/register?industry=${code}`, { waitUntil: 'domcontentloaded' });
  const v = await p.evaluate(() => ({ sel: document.getElementById('reg_business_type')?.value,
    reg: document.getElementById('registerForm')?.classList.contains('active') }));
  rec(`Đăng ký ?industry=${code}: chọn sẵn ngành`, v.sel === code && v.reg, JSON.stringify(v));
  await p.close();
}
const lp = await desk.newPage();
await lp.goto(`${BASE}/login?industry=spa&tab=register`, { waitUntil: 'domcontentloaded' });
const lv = await lp.evaluate(() => ({ sel: document.getElementById('reg_business_type')?.value,
  reg: document.getElementById('registerForm')?.classList.contains('active') }));
rec('/login?industry=spa&tab=register -> tab Đăng ký + Spa', lv.sel === 'spa' && lv.reg, JSON.stringify(lv));
await lp.close();

// Route tải
for (const code of [...Object.keys(FILES), 'nails', 'hr']) {
  const r = await fetch(`${BASE}/download/${code}/windows`, { redirect: 'manual' });
  const loc = r.headers.get('location') || '';
  const real = { nails: 'nail', hr: 'office' }[code] || code;
  const body = r.status === 503 ? await r.text() : '';
  // file nằm trên chính website: /dl/<file>?v=<sha8> (đổi bản là đổi link, CDN không trả bản cũ)
  const ok = (r.status === 302 && /^\/dl\/[^?]+\?v=[0-9a-f]{8}$/.test(loc) && loc.split('?')[0].endsWith('/' + FILES[real]))
    || (r.status === 503 && body.includes(FILES[real]));
  rec(`/download/${code}/windows`, ok, r.status === 302 ? `302 -> ${loc}` : `${r.status} trang chờ (chưa phát hành)`);
}
for (const code of ['android', 'nail/android', 'spa/android']) {
  const r = await fetch(`${BASE}/download/${code}`, { redirect: 'manual' });
  const loc = r.headers.get('location') || '';
  rec(`/download/${code} -> BitPaw.apk`, r.status === 302 && /^\/dl\/BitPaw\.apk\?v=[0-9a-f]{8}$/.test(loc), `${r.status} -> ${loc}`);
}
const bad = await fetch(`${BASE}/download/khongton/windows`, { redirect: 'manual' });
rec('/download/<ngành lạ>/windows -> về landing', bad.status === 302 && !(bad.headers.get('location') || '').includes('github'),
  `${bad.status} ${bad.headers.get('location')}`);

// Landing chính: popup chọn ngành
const mp = await desk.newPage();
await mp.goto(`${BASE}/landing`, { waitUntil: 'domcontentloaded' });
await mp.waitForFunction(() => typeof openDownloadModal === 'function', null, { timeout: 15000 }).catch(() => {});
await mp.evaluate(() => openDownloadModal());
await mp.waitForTimeout(600);
const modal = await mp.evaluate(() => {
  const m = document.getElementById('downloadModal');
  const hrefs = Array.from(m.querySelectorAll('a')).map((a) => a.getAttribute('href'));
  return { win: hrefs.filter((h) => /^\/download\/\w+\/windows$/.test(h)).length,
    web: hrefs.filter((h) => /industry=\w+&tab=register/.test(h)).length,
    fake: hrefs.some((h) => /drive\.google|apps\.apple/.test(h)) };
});
await mp.screenshot({ path: path.join(OUT, 'landing_main_modal.png') });
rec('Landing chính: popup Tải về chọn 9 ngành, không còn link Drive/Mac giả', modal.win === 9 && modal.web === 9 && !modal.fake, JSON.stringify(modal));
await mp.close();

rec('Không lỗi JS', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
fs.writeFileSync('audit-results/landing_download_audit.json', JSON.stringify({ ranAt: new Date().toISOString(), steps }, null, 2));
process.exit(fail ? 1 : 0);
