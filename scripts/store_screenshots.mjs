// Ảnh chụp nộp CH Play + App Store, chụp từ server local bằng tài khoản demo Nails, với User-Agent
// của app (trang bán gói bị ẩn đúng như người dùng thấy trong app). Kích thước đúng yêu cầu store:
//   - iPhone 6.9": 1290x2796 (430x932 @3x)   - iPad 13": 2064x2752 (1032x1376 @2x)
//   - Android phone: 1080x2160 (360x720 @3x, đúng tỉ lệ tối đa 2:1 theo quy định Google Play)
//   - Google Play feature graphic: 1024x500
// Chạy: node scripts/store_screenshots.mjs   (server local phải đang chạy)
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { gotoSell, safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const OUT = path.resolve('mobile_app/store_assets');
const DEVICES = [
  { dir: 'ios_iphone_6.9', platform: 'iOS', viewport: { width: 430, height: 932 }, scale: 3 },
  { dir: 'ios_ipad_13', platform: 'iOS', viewport: { width: 1032, height: 1376 }, scale: 2 },
  { dir: 'android_phone', platform: 'Android', viewport: { width: 360, height: 720 }, scale: 3 },
];
const SCREENS = [
  ['01_pos_checkout', async (page) => {
    await gotoSell(page, BASE);
    await page.locator('#serviceGrid .service-card').nth(0).click();
    await page.locator('#serviceGrid .service-card').nth(4).click();
    await page.waitForTimeout(2600); // chờ toast "added to ticket" tự ẩn
  }],
  ['02_appointments', async (page) => { await page.goto(`${BASE}/calendar`, { waitUntil: 'networkidle' }); }],
  ['03_customers_crm', async (page) => { await page.goto(`${BASE}/customers`, { waitUntil: 'networkidle' }); await page.waitForTimeout(800); }],
  ['04_payroll', async (page) => { await page.goto(`${BASE}/bangluong`, { waitUntil: 'networkidle' }); await page.waitForTimeout(800); }],
  ['05_ai_copilot', async (page) => { await page.goto(`${BASE}/ai_bot`, { waitUntil: 'networkidle' }); }],
  ['06_staff_attendance', async (page) => { await page.goto(`${BASE}/chamcong/nail`, { waitUntil: 'networkidle' }); }],
];

const browser = await chromium.launch({ channel: 'chrome', headless: true });
for (const dev of DEVICES) {
  const dir = path.join(OUT, dev.dir);
  fs.mkdirSync(dir, { recursive: true });
  const ctx = await browser.newContext({
    viewport: dev.viewport, deviceScaleFactor: dev.scale, isMobile: dev.dir !== 'ios_ipad_13', hasTouch: true,
    userAgent: `BitPawMobileApp/1.0.0 (${dev.platform}; WebView)`,
  });
  await ctx.addCookies([{ name: 'bitpaw_lang', value: 'en', url: BASE }]);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await safeScreenshot(page, { path: path.join(dir, '00_sign_in.png') });
  await page.fill('#loginEmail', 'demo.nails.au.006758@bitpawdemo.com');
  await page.fill('#loginPassword', 'DemoNails2026!');
  await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
  if (page.url().includes('/login')) throw new Error('Đăng nhập demo thất bại (rate limit?) — restart server rồi chạy lại');
  for (const [name, go] of SCREENS) {
    await go(page);
    // Ẩn widget nổi (mascot/chat) để ảnh store gọn, không che nội dung
    await page.addStyleTag({ content: '#cskh-widget-root,.cskh-launcher,#bpFab,.bp-fab{display:none!important}' }).catch(() => {});
    await safeScreenshot(page, { path: path.join(dir, `${name}.png`) });
  }
  console.log(`✅ ${dev.dir}: ${SCREENS.length + 1} ảnh`);
  await ctx.close();
}

// Google Play feature graphic 1024x500
const fg = await browser.newPage({ viewport: { width: 1024, height: 500 } });
const logo = fs.readFileSync('static/icon.jpg').toString('base64');
await fg.setContent(`<html><body style="margin:0;width:1024px;height:500px;display:flex;align-items:center;gap:48px;padding:0 72px;box-sizing:border-box;
  background:radial-gradient(circle at 15% 20%,rgba(245,158,11,.25),transparent 45%),radial-gradient(circle at 85% 80%,rgba(6,182,212,.3),transparent 45%),linear-gradient(160deg,#0B132B,#1C2541 55%,#0a2324);
  font-family:'Segoe UI',system-ui,sans-serif;color:#fff">
  <img src="data:image/jpeg;base64,${logo}" style="width:220px;height:220px;border-radius:48px;box-shadow:0 0 60px rgba(6,182,212,.45)">
  <div><div style="font-size:58px;font-weight:900;letter-spacing:1px">Bit<span style="color:#22d3ee">Paw</span> Software</div>
  <div style="font-size:30px;font-weight:700;margin-top:12px;color:#e2e8f0">Salon POS · Booking · Payroll</div>
  <div style="font-size:22px;margin-top:14px;color:#94a3b8">Run your nail salon from one app</div></div></body></html>`);
await fg.screenshot({ path: path.join(OUT, 'google_play_feature_graphic_1024x500.png') });
console.log('✅ feature graphic 1024x500');
await browser.close();
