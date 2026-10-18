// Trang tải về tự nhận diện máy + file tải đúng tên/đúng loại + icon/PWA — CHỈ server local 127.0.0.1:5001.
//   node scripts/download_device_e2e.mjs
import { chromium, devices } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const OUT = path.resolve('audit-results/screenshots/download_device_e2e');
fs.mkdirSync(OUT, { recursive: true });
const strip = ({ defaultBrowserType, ...d }) => d;
const UA_WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';
const UA_MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15';
const UA_SUNMI = 'Mozilla/5.0 (Linux; Android 11; SUNMI T2s) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';
const CASES = [
  ['Windows', { viewport: { width: 1440, height: 900 }, userAgent: UA_WIN }, 'windows', 'windows', '/download/nail/windows'],
  ['Mac', { viewport: { width: 1440, height: 900 }, userAgent: UA_MAC }, 'mac', 'web', '/login?industry=nail&tab=register'],
  ['iPhone 13', strip(devices['iPhone 13']), 'iphone', 'ios', null],
  // iPadOS 13+ tự xưng là Mac (UA "Macintosh") nhưng có cảm ứng -> phải nhận ra iPad
  ['iPad (iPadOS, UA giống Mac)', { ...strip(devices['iPad Pro 11']), userAgent: UA_MAC }, 'ipad', 'ios', null],
  ['Android phone (Pixel 7)', strip(devices['Pixel 7']), 'android_phone', 'android', '/download/nail/android'],
  ['Android tablet (Galaxy Tab S4)', strip(devices['Galaxy Tab S4']), 'android_tablet', 'android', '/download/nail/android'],
  ['Máy POS Sunmi T2s (Android)', { viewport: { width: 1280, height: 800 }, userAgent: UA_SUNMI, hasTouch: true }, 'android_pos', 'android', '/download/nail/android'],
];
const results = [];
const rec = (name, ok, note = '') => { results.push({ name, ok }); console.log(`${ok ? '✅' : '❌'} ${name}${note ? ' — ' + note : ''}`); };

const browser = await chromium.launch({ channel: 'chrome', headless: true });
for (const [label, opts, kind, recCard, href] of CASES) {
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  await page.goto(BASE + '/download/nail', { waitUntil: 'networkidle' });
  const r = await page.evaluate(() => ({
    kind: window.bpDetectDevice().kind,
    rec: document.querySelector('.bpdl-rec')?.getAttribute('data-bpdl-platform'),
    name: document.querySelector('[data-bpdl-detect-name]').textContent,
    btn: document.querySelector('[data-bpdl-detect-btn]').getAttribute('href'),
    overflow: document.scrollingElement.scrollWidth > innerWidth + 1,
  }));
  rec(`[${label}] nhận diện đúng máy`, r.kind === kind && r.rec === recCard, `${r.name} · thẻ khuyên dùng: ${r.rec}`);
  if (href) rec(`[${label}] nút khuyên dùng trỏ đúng bản`, r.btn === href, r.btn);
  if (recCard === 'ios') {
    await page.click('[data-bpdl-detect-btn]');
    const steps = await page.locator('[data-bpdl-sheet].bpdl-open [data-bpdl-sheet-steps] li').count();
    const sameLang = await page.evaluate(() => {
      const en = document.getElementById('tai-ve').classList.contains('bpdl-en');
      const t = document.querySelector('[data-bpdl-sheet-steps]').innerText;
      return en ? /Tap|Open/.test(t) : /Bấm|Mở|Chọn/.test(t);
    });
    rec(`[${label}] hướng dẫn cùng ngôn ngữ với trang`, sameLang);
    rec(`[${label}] bấm "Cài lên ${kind === 'ipad' ? 'iPad' : 'iPhone'}" -> hiện hướng dẫn Thêm vào MH chính`, steps >= 3, `${steps} bước`);
  }
  rec(`[${label}] không tràn ngang, không lỗi JS`, !r.overflow && errs.length === 0, errs.join(' | '));
  await page.screenshot({ path: path.join(OUT, `${label.replace(/[^\w]+/g, '_')}.png`), fullPage: true }).catch(() => {});
  await ctx.close();
}

// File tải về: đúng tên theo ngành, đúng loại, đúng kích thước
const ctx = await browser.newContext({ acceptDownloads: true, userAgent: UA_WIN });
const page = await ctx.newPage();
for (const [url, want, minMB] of [['/download/spa/windows', 'BitPaw-Spa.exe', 15], ['/download/fnb/windows', 'BitPaw-FnB.exe', 15], ['/download/nail/android', 'BitPaw.apk', 30]]) {
  const r = await page.request.get(BASE + url, { maxRedirects: 5 });
  const cd = r.headers()['content-disposition'] || '';
  const size = (await r.body()).length / 1048576;
  rec(`Tải ${url}`, r.status() === 200 && cd.includes(want) && size > minMB, `${r.status()} · ${cd} · ${size.toFixed(1)} MB · ${r.headers()['content-type']}`);
}
// Icon / PWA
const html = await (await page.request.get(BASE + '/login')).text();
rec('Trang có khai báo icon mới + manifest (chèn tự động)', html.includes('data-bp-pwa') && html.includes('/manifest.webmanifest') && html.includes('apple-touch-icon.png'));
const man = await (await page.request.get(BASE + '/manifest.webmanifest')).json();
rec('Manifest cài app: standalone, có icon 192/512 + maskable', man.display === 'standalone' && man.icons.length === 4, man.start_url);
for (const u of ['/favicon.ico', '/static/brand/apple-touch-icon.png', '/static/brand/icon-512.png', '/sw.js']) {
  const r = await page.request.get(BASE + u);
  rec(`${u}`, r.status() === 200, `${r.headers()['content-type']} · ${(await r.body()).length} B`);
}
await browser.close();
console.log(`\nTổng kết: ${results.filter((r) => r.ok).length} PASS · ${results.filter((r) => !r.ok).length} FAIL`);
