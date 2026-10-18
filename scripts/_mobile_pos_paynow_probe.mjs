// iPhone 13: POS Nails — thêm 1 dịch vụ rồi bấm PAY NOW như ngón tay thật (tap, không ép click) -> hộp thanh toán phải mở.
import { chromium, devices } from 'playwright';

const BASE = 'http://127.0.0.1:5001';
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const b = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await b.newContext({ ...iphone, deviceScaleFactor: 2 });
const p = await ctx.newPage();
const errs = [];
p.on('pageerror', (e) => errs.push(String(e).slice(0, 150)));
await p.goto(BASE + '/login');
await p.fill('#loginEmail', 'demo.nails.au.006758@bitpawdemo.com'); await p.fill('#loginPassword', 'DemoNails2026!');
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
await p.goto(BASE + '/sell', { waitUntil: 'networkidle' });
await p.waitForSelector('#serviceGrid .service-card', { timeout: 15000 });
const info = async (label) => console.log(label, JSON.stringify(await p.evaluate(() => {
  const btn = document.getElementById('checkoutBtn'); const r = btn.getBoundingClientRect();
  const atCenter = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return { checkoutBtn: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height), disabled: btn.disabled, vh: innerHeight },
           elementAtCenter: atCenter ? `${atCenter.tagName}#${atCenter.id}.${String(atCenter.className).slice(0, 60)}` : null,
           cartCount: document.querySelectorAll('#cartItems .cart-item').length, modalActive: document.getElementById('paymentModal').classList.contains('active') };
})));
await info('trước khi thêm:');
await p.locator('#serviceGrid .service-card').first().tap();
await p.waitForTimeout(300);
await info('sau khi chạm 1 dịch vụ:');
await p.screenshot({ path: 'audit-results/screenshots/mobile_pos_after_add.png' });
const bb = await p.locator('#checkoutBtn').boundingBox();
await p.touchscreen.tap(bb.x + bb.width / 2, bb.y + bb.height / 2);  // chạm ngay sau khi thêm, lúc toast vẫn đang hiện
await p.waitForTimeout(800);
await info('sau khi chạm PAY NOW:');
await p.screenshot({ path: 'audit-results/screenshots/mobile_pos_after_paynow.png' });
console.log('lỗi JS:', errs);
await b.close();
